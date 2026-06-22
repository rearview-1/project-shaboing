"""Fast deck calibration — the "Calibrate" button backend.

Hits the deck's SS-comfort threshold quickly (3-5 min budget) and caches
the winning policy so the next live career uses it. Logic:

  1. Load current session context (deck, trainee, scenario, friend card)
     from `dev_session.json`. This is what the bot will face next.
  2. Load the user's production preset as baseline.
  3. Quick baseline pass (small N sims).
     - If baseline already hits the "comfortable SS" threshold
       (SS rate ≥ target_ss_rate AND mean rating ≥ target_mean),
       save the baseline as the calibrated policy and exit.
  4. Otherwise: adaptive candidate sweep within the time budget.
     - Sample candidates from PARAM_SPACE (reused from optimize_deck_policy).
     - Each candidate is evaluated with N_sims_per_candidate sims.
     - Track best-so-far by SS rate, then by mean as tiebreak.
     - Early stop when best-so-far meets the comfort threshold.
     - Hard stop when time budget exhausted.
  5. Validate the winner on fresh seeds.
  6. If winner > baseline on SS rate, save to deck_policy_cache.

Designed to be run from a new console window so the user can watch the
probe progress live. Prints structured progress lines that the UI can
also tail/parse for a progress bar.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from career_bot.career_simulator import CareerSimulator, MANT_EPITHET_SETS
from career_bot.deck_policy_cache import (
    apply_policy_to_preset,
    deck_signature,
    load_cache,
    lookup_policy,
    save_cache,
    save_policy,
)
from career_bot.sim_self_learning import (
    LEARNABLE_PARAMS,
    analyze_batch,
    clamp_learned_value,
)


# Policy floors for `learned_hyperparameters` cap values. If a user's
# preset has a learned value BELOW this floor, calibrate auto-corrects
# it to the corresponding policy_default. Why: the auto-tuner can over-
# fit to a sub-SS regime and pin stamina_soft_cap at 775 for so long that
# no future calibration ever tries higher — without this reset, the
# strategy is silently capped on stats the operator wants pushed.
# Policy: caps at 1200 across all 5 stats (the in-game hard ceiling).
# Mid-career floor targets matching SS-capable training schedules.
POLICY_FLOORS = {
    # cap knobs: must be at-or-above the in-game ceiling
    "speed_soft_cap":     {"min": 1200, "policy_default": 1200, "kind": "cap"},
    "wit_soft_cap":       {"min": 1200, "policy_default": 1200, "kind": "cap"},
    "power_soft_cap":     {"min": 1200, "policy_default": 1200, "kind": "cap"},
    "stamina_soft_cap":   {"min": 1000, "policy_default": 1200, "kind": "cap"},
    "guts_soft_cap":      {"min": 1000, "policy_default": 1200, "kind": "cap"},
    # floor targets: bot actively pushes a stat to at-or-above
    "stamina_floor_target": {"min": 900, "policy_default": 1000, "kind": "floor"},
    "power_floor_target":   {"min": 1000, "policy_default": 1100, "kind": "floor"},
}


def _apply_policy_floor_corrections(preset: dict) -> list[tuple[str, float, float]]:
    """Inspect `preset.learned_hyperparameters` for cap/floor values that
    violate the operator policy, and reset them to policy defaults.

    Returns a list of (param_name, old_value, new_value) for logging. The
    preset dict is mutated in place. Calibrate calls this BEFORE the
    baseline pass, so the corrected values flow into every sim.
    """
    corrections = []
    lhp = preset.get("learned_hyperparameters")
    if not isinstance(lhp, dict):
        return corrections
    for name, rule in POLICY_FLOORS.items():
        if name not in lhp:
            continue
        try:
            current = float(lhp[name])
        except (TypeError, ValueError):
            continue
        if current < rule["min"]:
            corrections.append((name, current, float(rule["policy_default"])))
            lhp[name] = rule["policy_default"]
    return corrections


def _detect_parent_ids(instance: str) -> tuple[int, int, str]:
    """Detect which two parents calibrate should use.

    The sim's legacy_effects (parent factor stat bonuses, white spark
    skill hint discounts, aptitude rank upgrades, green/scenario
    factors) ONLY fire when `_run_context.parent_id_1/2` are set on
    the preset. If they're absent, the sim runs as if no parents were
    selected — which costs roughly +200-500 stats and 10-50% skill
    discounts. Calibrate was silently doing this before this fix.

    Detection priority:
      1. `dev_session.json` → `selection.veterans` (UI-set picks)
      2. Latest `bot_logs/career_log_*.json` → `_run_context.parent_id_1/2`
         (parents the bot is actually running with right now)
      3. None → return (0, 0, ...) and warn loudly in the caller

    Returns (parent_id_1, parent_id_2, source_label).
    """
    runtime_root = PROJECT_ROOT / "uma_runtime" / "instances" / instance

    # Tier 1: dev_session.json selection.veterans
    dev_path = runtime_root / "dev_session.json"
    if dev_path.exists():
        try:
            data = json.loads(dev_path.read_text(encoding="utf-8-sig"))
            vets = ((data.get("selection") or {}).get("veterans") or [])
            ids = []
            for v in vets[:2]:
                if isinstance(v, dict):
                    vid = int(v.get("instance_id") or v.get("trained_chara_id") or 0)
                    if vid:
                        ids.append(vid)
            if len(ids) >= 2:
                return ids[0], ids[1], "dev_session.selection.veterans"
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            pass

    # Tier 2: latest finished career_log
    log_dir = runtime_root / "bot_logs"
    if log_dir.is_dir():
        try:
            candidates = sorted(
                (p for p in log_dir.glob("career_log_*.json") if p.is_file()),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for log_path in candidates[:5]:
                try:
                    data = json.loads(log_path.read_text(encoding="utf-8-sig"))
                except (OSError, json.JSONDecodeError):
                    continue
                ctx = data.get("_run_context") or data.get("run_context") or {}
                p1 = int(ctx.get("parent_id_1") or 0)
                p2 = int(ctx.get("parent_id_2") or 0)
                if p1 and p2:
                    return p1, p2, f"latest career_log ({log_path.name})"
        except OSError:
            pass

    return 0, 0, "none found"


def _epithet_race_names() -> set[str]:
    """Every race that participates in any MANT epithet route.

    Cached on first call. Each epithet entry has either `races` (the
    primary set), `prereq` (additional required for chained epithets
    like Phenomenal), or both. Losing a race in either category
    breaks the chain and forfeits the +10/+15 stat bonus, so both
    count as 'losses we cannot afford' for calibration purposes.
    """
    cached = _epithet_race_names._cache  # type: ignore[attr-defined]
    if cached is not None:
        return cached
    names: set[str] = set()
    for ep in MANT_EPITHET_SETS:
        for key in ("races", "prereq"):
            for r in (ep.get(key) or []):
                if isinstance(r, str) and r.strip():
                    names.add(r.strip())
    _epithet_race_names._cache = names  # type: ignore[attr-defined]
    return names


_epithet_race_names._cache = None  # type: ignore[attr-defined]

# Reuse the optimizer's candidate space + sampler so the two stay aligned.
from tools.optimize_deck_policy import (
    PARAM_SPACE,
    _base_preset,
    _sample_candidate,
)


def _log(msg: str) -> None:
    """Single structured progress line for the UI tailer."""
    safe = str(msg).encode("ascii", errors="replace").decode("ascii")
    print(f"[CALIBRATE] {safe}", flush=True)


def _strat_summary(result) -> str:
    """Build a compact 'strat=Late' or 'strats=[Late:6 Pace:2]' summary
    from the sim's per-race running_style_label fields. Empty if no races
    were run (or styles unrecorded)."""
    from collections import Counter
    races = getattr(result, "races_run", None) or []
    if not races:
        return ""
    labels = [str(r.get("running_style_label") or "").strip() for r in races]
    labels = [lab for lab in labels if lab]
    if not labels:
        return ""
    counts = Counter(labels)
    # If all races used the same strat, show 'strat=Late'
    if len(counts) == 1:
        only_label = next(iter(counts))
        return f"strat={only_label}"
    # Otherwise show distribution sorted by frequency: 'strats=[Late:6 Pace:2]'
    parts = [f"{label}:{n}" for label, n in counts.most_common()]
    return f"strats=[{' '.join(parts)}]"


def _run_sims(preset: dict, *, n: int, seed_base: int) -> list:
    results = []
    for i in range(n):
        sim = CareerSimulator(preset=copy.deepcopy(preset), seed=seed_base + i)
        r = sim.run()
        results.append(r)
        marker = "SS!" if r.rating_score >= 17500 else (
            "S+" if r.rating_score >= 15900 else (
                "S" if r.rating_score >= 14500 else ""
            )
        )
        strat = _strat_summary(r)
        print(
            f"    seed {seed_base + i}: rank={r.rank:>4} "
            f"rating={r.rating_score:>5} stat_sum={r.stat_sum:>4} "
            f"{strat}  {marker}".rstrip(),
            flush=True,
        )
    return results


def _ss_rate(results: list, threshold: int = 17500) -> float:
    if not results:
        return 0.0
    return sum(1 for r in results if r.rating_score >= threshold) / len(results)


def _mean_rating(results: list) -> float:
    if not results:
        return 0.0
    return statistics.mean(r.rating_score for r in results)


def _min_rating(results: list) -> int:
    if not results:
        return 0
    return min(int(getattr(r, "rating_score", 0) or 0) for r in results)


def _below_rating_count(results: list, floor: int) -> int:
    if not results:
        return 0
    return sum(1 for r in results if int(getattr(r, "rating_score", 0) or 0) < int(floor))


def _win_rate(results: list) -> float:
    """Total race wins / total races run across all sims in the batch.

    Computed across every race the bot entered (junior + classic +
    senior + climax). Pre-races and skipped races are ignored.
    """
    total = 0
    wins = 0
    for r in results:
        for race in (getattr(r, "races_run", None) or []):
            total += 1
            if bool(race.get("won")):
                wins += 1
    if total <= 0:
        return 0.0
    return wins / total


def _epithet_losses(results: list) -> int:
    """Count losses on races that gate an epithet bonus.

    These are the most-costly losses: each one forfeits a +10 or +15
    stat bonus from a MANT epithet route. A calibrated deck must NOT
    drop epithet races — even one such loss is disqualifying.
    """
    epithet_set = _epithet_race_names()
    bad = 0
    for r in results:
        for race in (getattr(r, "races_run", None) or []):
            if bool(race.get("won")):
                continue
            name = str(race.get("name") or "").strip()
            if name in epithet_set:
                bad += 1
    return bad


def _loss_summary(results: list, *, limit: int = 8) -> list[dict]:
    """Compact loss breakdown for calibration diagnostics.

    The optimizer should not blindly tune final stat knobs when the real
    failure is a specific race route. This summary makes those repeated
    losses visible in console output and JSON reports.
    """
    from collections import Counter

    epithet_set = _epithet_race_names()
    counts: Counter[tuple] = Counter()
    for r in results:
        for race in (getattr(r, "races_run", None) or []):
            if bool(race.get("won")):
                continue
            name = str(race.get("name") or "Unknown").strip()
            grade = str(
                race.get("grade")
                or race.get("grade_label")
                or race.get("race_grade")
                or ""
            ).strip()
            style = str(
                race.get("running_style_label")
                or race.get("style")
                or race.get("strategy")
                or ""
            ).strip()
            turn = race.get("turn") or race.get("scenario_turn") or ""
            counts[(name, grade, style, str(turn), name in epithet_set)] += 1

    rows = []
    for (name, grade, style, turn, epithet), count in counts.most_common(limit):
        rows.append({
            "name": name,
            "count": count,
            "grade": grade,
            "style": style,
            "turn": turn,
            "epithet": bool(epithet),
        })
    return rows


def _format_loss_summary(results: list) -> str:
    rows = _loss_summary(results)
    if not rows:
        return "none"
    parts = []
    for row in rows:
        marker = " epithet" if row.get("epithet") else ""
        grade = f" {row.get('grade')}" if row.get("grade") else ""
        style = f" {row.get('style')}" if row.get("style") else ""
        turn = f" t{row.get('turn')}" if row.get("turn") else ""
        parts.append(
            f"{row['name']}x{row['count']}{grade}{style}{turn}{marker}"
        )
    return "; ".join(parts)


def _is_comfortable(results: list, target_ss_rate: float, target_mean: int,
                    ss_threshold: int, target_win_rate: float = 0.95,
                    max_epithet_losses: int = 0,
                    min_rating: int = 14500) -> bool:
    """A configuration is "comfortable" only when ALL of:
      - SS rate ≥ target_ss_rate (default 80%)
      - mean rating ≥ target_mean (default 17,500 = SS threshold)
      - win rate ≥ target_win_rate (default 95%)
      - epithet-bonus race losses ≤ max_epithet_losses (default 0)

    Why both win-rate AND epithet-loss gating? Bot can hit 96% win
    rate by sweeping mid-grade races but bombing a Stunning route
    G1 — that breaks the +15 bonus and tanks rating. The epithet
    floor catches that specifically.
    """
    if _ss_rate(results, ss_threshold) < target_ss_rate:
        return False
    if _mean_rating(results) < target_mean:
        return False
    if _min_rating(results) < min_rating:
        return False
    if _win_rate(results) < target_win_rate:
        return False
    if _epithet_losses(results) > max_epithet_losses:
        return False
    return True


def _quality_key(results: list, *, ss_threshold: int, target_win_rate: float,
                 max_epithet_losses: int, min_rating: int) -> tuple:
    """Sort key for candidate batches.

    Priorities:
      1. no epithet-bonus race losses
      2. no below-floor/A+ outcomes
      3. meets race win-rate target
      4. higher SS rate
      5. higher mean rating
      6. higher win rate
      7. higher minimum rating
    """
    ep_losses = _epithet_losses(results)
    min_score = _min_rating(results)
    win = _win_rate(results)
    return (
        1 if ep_losses <= max_epithet_losses else 0,
        1 if min_score >= min_rating else 0,
        1 if win >= target_win_rate else 0,
        round(_ss_rate(results, ss_threshold), 6),
        round(_mean_rating(results), 3),
        round(win, 6),
        min_score,
    )


def _is_best_effort_clean_progress(
    candidate_results: list,
    baseline_results: list,
    *,
    ss_threshold: int,
    target_win_rate: float,
    max_epithet_losses: int,
    min_rating: int,
    rating_tolerance: int = 750,
) -> bool:
    """Accept non-comfort candidates that make safety progress without tanking score.

    The optimizer's main target is still comfortable SS. When that is not
    reached inside the time budget, a policy that removes epithet losses and
    A+ outcomes should still be cached if it is not materially worse on rating.
    Otherwise the optimizer can find a safer policy and throw it away simply
    because SS-rate did not improve on a tiny validation batch.
    """
    if _epithet_losses(candidate_results) > max_epithet_losses:
        return False
    if _min_rating(candidate_results) < min_rating:
        return False
    if _win_rate(candidate_results) < target_win_rate:
        return False
    if _mean_rating(candidate_results) < _mean_rating(baseline_results) - int(rating_tolerance):
        return False
    return _quality_key(
        candidate_results,
        ss_threshold=ss_threshold,
        target_win_rate=target_win_rate,
        max_epithet_losses=max_epithet_losses,
        min_rating=min_rating,
    ) > _quality_key(
        baseline_results,
        ss_threshold=ss_threshold,
        target_win_rate=target_win_rate,
        max_epithet_losses=max_epithet_losses,
        min_rating=min_rating,
    )


def _merge_overrides_into_preset(preset: dict, overrides: dict) -> dict:
    merged = copy.deepcopy(preset)
    lhp = dict(merged.get("learned_hyperparameters") or {})
    lhp.update(overrides)
    # Every calibrate candidate runs the deck-adaptive convex-throughput engine
    # (training + aptitude-aware race selection). The baseline (raw `preset`)
    # stays non-convex, and the save gate only adopts a winner that BEATS the
    # baseline + cached policy, so this can only improve a deck, never regress
    # it (verified on TM Opera O: 12,304 -> ~15,200 / 50% S+). See
    # [[ss-reachability-diagnosis]].
    lhp["convex_throughput_mode"] = True
    merged["learned_hyperparameters"] = lhp
    return merged


def _override_key(overrides: dict) -> tuple:
    return tuple(sorted((str(k), overrides[k]) for k in (overrides or {})))


def _dedupe_override_candidates(candidates: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for candidate in candidates or []:
        if not isinstance(candidate, dict) or not candidate:
            continue
        key = _override_key(candidate)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
    return out


def _self_learning_overrides_from_results(
    results: list,
    preset: dict,
    *,
    base_overrides: dict | None = None,
    limit: int = 8,
) -> list[dict]:
    """Turn sim analyzer proposals into concrete override candidates.

    The analyzer emits one-param proposals. Calibration evaluates both
    singles and a cumulative bundle of the strongest proposals so it can
    adapt in fewer sim rounds without allowing any operator-owned fields
    through.
    """
    if not results:
        return []
    working_preset = _merge_overrides_into_preset(preset, base_overrides or {})
    proposals = analyze_batch(results, working_preset)
    proposals = [
        p for p in proposals
        if getattr(p, "param_name", None) in LEARNABLE_PARAMS
    ]
    proposals.sort(
        key=lambda p: (
            -float(getattr(p, "expected_lift_hint", 0.0) or 0.0),
            str(getattr(p, "param_name", "")),
        )
    )

    base = dict(base_overrides or {})
    out = []
    cumulative = dict(base)
    for proposal in proposals[:max(1, limit)]:
        name = proposal.param_name
        value = clamp_learned_value(name, proposal.proposed_value)
        current = (base.get(name) if name in base else
                   (working_preset.get("learned_hyperparameters") or {}).get(name))
        if current == value:
            continue
        single = dict(base)
        single[name] = value
        out.append(single)
        cumulative[name] = value
    if cumulative != base:
        out.insert(0, cumulative)
    return _dedupe_override_candidates(out)


def _comfort_seed_overrides(preset: dict) -> list[dict]:
    """Deterministic SS-comfort priors used before random search.

    These are still sim-tested and validated before cache write. They
    give the optimizer strong starting points for deck swaps instead of
    wasting the first minute discovering obvious speed/wit/power pressure
    from random samples.
    """
    lhp = dict((preset or {}).get("learned_hyperparameters") or {})

    def _v(name, fallback):
        return lhp.get(name, (preset or {}).get(name, fallback))

    priors = [
        {
            "speed_priority_bonus_mid": max(float(_v("speed_priority_bonus_mid", 0.18)), 0.36),
            "speed_priority_bonus_late": max(float(_v("speed_priority_bonus_late", 0.26)), 0.50),
            "speed_floor_target": max(int(_v("speed_floor_target", 950)), 1150),
            "wit_priority_bonus_mid": max(float(_v("wit_priority_bonus_mid", 0.18)), 0.46),
            "wit_priority_bonus_late": max(float(_v("wit_priority_bonus_late", 0.35)), 0.66),
            "stamina_priority_bonus_base": max(float(_v("stamina_priority_bonus_base", 0.03)), 0.10),
            "stamina_priority_deficit_boost": max(float(_v("stamina_priority_deficit_boost", 0.03)), 0.16),
            "power_priority_bonus_base": max(float(_v("power_priority_bonus_base", 0.03)), 0.14),
            "power_priority_deficit_boost": max(float(_v("power_priority_deficit_boost", 0.05)), 0.22),
            "stamina_floor_target": max(int(_v("stamina_floor_target", 750)), 1000),
            "power_floor_target": max(int(_v("power_floor_target", 950)), 1150),
            "calendar_race_prebuy_budget": max(int(_v("calendar_race_prebuy_budget", 850)), 1500),
            "calendar_race_prebuy_keep_sp": min(int(_v("calendar_race_prebuy_keep_sp", 100)), 50),
            "calendar_race_prebuy_max_skills": max(int(_v("calendar_race_prebuy_max_skills", 4)), 9),
            "rest_threshold": min(int(_v("rest_threshold", 48)), 42),
        },
        {
            "speed_priority_bonus_mid": max(float(_v("speed_priority_bonus_mid", 0.18)), 0.22),
            "speed_priority_bonus_late": max(float(_v("speed_priority_bonus_late", 0.26)), 0.34),
            "speed_floor_target": max(int(_v("speed_floor_target", 950)), 1100),
            "wit_priority_bonus_mid": max(float(_v("wit_priority_bonus_mid", 0.18)), 0.30),
            "wit_priority_bonus_late": max(float(_v("wit_priority_bonus_late", 0.35)), 0.48),
            "power_priority_bonus_base": max(float(_v("power_priority_bonus_base", 0.03)), 0.06),
            "power_priority_deficit_boost": max(float(_v("power_priority_deficit_boost", 0.05)), 0.10),
            "stamina_floor_target": max(int(_v("stamina_floor_target", 750)), 900),
            "power_floor_target": max(int(_v("power_floor_target", 950)), 1050),
            "calendar_race_prebuy_budget": max(int(_v("calendar_race_prebuy_budget", 850)), 1200),
            "calendar_race_prebuy_keep_sp": min(int(_v("calendar_race_prebuy_keep_sp", 100)), 100),
            "calendar_race_prebuy_max_skills": max(int(_v("calendar_race_prebuy_max_skills", 4)), 6),
        },
        {
            "speed_priority_bonus_mid": max(float(_v("speed_priority_bonus_mid", 0.18)), 0.20),
            "speed_priority_bonus_late": max(float(_v("speed_priority_bonus_late", 0.26)), 0.30),
            "speed_floor_target": max(int(_v("speed_floor_target", 950)), 1050),
            "wit_priority_bonus_mid": max(float(_v("wit_priority_bonus_mid", 0.18)), 0.34),
            "wit_priority_bonus_late": max(float(_v("wit_priority_bonus_late", 0.35)), 0.58),
            "stamina_floor_target": max(int(_v("stamina_floor_target", 750)), 850),
            "power_floor_target": max(int(_v("power_floor_target", 950)), 1000),
            "calendar_race_prebuy_budget": max(int(_v("calendar_race_prebuy_budget", 850)), 1100),
            "calendar_race_prebuy_keep_sp": min(int(_v("calendar_race_prebuy_keep_sp", 100)), 100),
            "calendar_race_prebuy_max_skills": max(int(_v("calendar_race_prebuy_max_skills", 4)), 5),
        },
        {
            "speed_priority_bonus_mid": max(float(_v("speed_priority_bonus_mid", 0.18)), 0.18),
            "speed_priority_bonus_late": max(float(_v("speed_priority_bonus_late", 0.26)), 0.28),
            "speed_floor_target": max(int(_v("speed_floor_target", 950)), 1050),
            "stamina_priority_deficit_boost": max(float(_v("stamina_priority_deficit_boost", 0.03)), 0.10),
            "power_priority_bonus_base": max(float(_v("power_priority_bonus_base", 0.03)), 0.08),
            "power_priority_deficit_boost": max(float(_v("power_priority_deficit_boost", 0.05)), 0.12),
            "stamina_floor_target": max(int(_v("stamina_floor_target", 750)), 1000),
            "power_floor_target": max(int(_v("power_floor_target", 950)), 1100),
            "calendar_race_prebuy_budget": max(int(_v("calendar_race_prebuy_budget", 850)), 1300),
            "calendar_race_prebuy_keep_sp": min(int(_v("calendar_race_prebuy_keep_sp", 100)), 75),
            "calendar_race_prebuy_max_skills": max(int(_v("calendar_race_prebuy_max_skills", 4)), 7),
        },
    ]

    bounded = []
    for prior in priors:
        row = {}
        for name, value in prior.items():
            if name in LEARNABLE_PARAMS:
                row[name] = clamp_learned_value(name, value)
        if row:
            bounded.append(row)
    return _dedupe_override_candidates(bounded)


def calibrate(
    *,
    time_budget_sec: float,
    sims_per_candidate: int,
    baseline_sims: int,
    validation_sims: int,
    target_ss_rate: float,
    target_mean: int,
    ss_threshold: int,
    preset_path: Path | None,
    rng_seed: int,
    instance: str,
    target_win_rate: float = 0.95,
    max_epithet_losses: int = 0,
    min_rating: int = 14500,
) -> dict:
    """Run the calibration. Returns a structured report dict."""
    t_start = time.time()
    rng = random.Random(rng_seed)

    _log(
        f"START budget={time_budget_sec:.0f}s "
        f"target_ss_rate={target_ss_rate} target_mean={target_mean} "
        f"target_win_rate={target_win_rate} max_epithet_losses={max_epithet_losses} "
        f"min_rating={min_rating} ss_threshold={ss_threshold}"
    )

    # Load baseline preset
    preset = _base_preset(preset_path)
    _log(f"loaded baseline preset: {preset.get('name')}")

    # POLICY CORRECTIONS: if the user's preset has learned cap/floor
    # values that contradict the operator policy (e.g. auto-tuner pinned
    # stamina_soft_cap at 775 from a sub-SS regime), reset them now.
    # Without this, the sim's strategy silently caps the stats the
    # operator wants pushed — no calibration can find an SS policy when
    # the baseline says "stop training stamina past 775."
    corrections = _apply_policy_floor_corrections(preset)
    if corrections:
        _log(f"policy corrections: {len(corrections)} stale learned value(s) reset:")
        for name, old, new in corrections:
            _log(f"  {name}: {old} -> {new}")
    else:
        _log("policy corrections: none (preset matches policy floors)")

    # CRITICAL: inject parent IDs into the preset's _run_context so the
    # sim's legacy_effects (parent factor stat bonuses, white spark
    # skill hints, aptitude upgrades, scenario factors) actually fire.
    # Without this, calibrate runs as if you had no parents selected —
    # which can be a 1000-3000 rating gap vs the live bot.
    parent_id_1, parent_id_2, parent_source = _detect_parent_ids(instance)
    rc = dict(preset.get("_run_context") or {})
    if parent_id_1 and parent_id_2:
        rc["parent_id_1"] = parent_id_1
        rc["parent_id_2"] = parent_id_2
        preset["_run_context"] = rc
        _log(f"parents detected from {parent_source}: "
             f"parent_id_1={parent_id_1}  parent_id_2={parent_id_2}")
    else:
        _log("=" * 60)
        _log("WARNING: NO PARENTS DETECTED. The sim will run as if you "
             "have no parents selected, which under-predicts rating by "
             "1000-3000 points per career.")
        _log("Fix: pick parents in the UI (so dev_session.json's "
             "selection.veterans is populated), or run a live career "
             "first so the bot writes parent_id_1/2 into the most "
             "recent career_log.")
        _log("=" * 60)

    # Hydrate session context (so deck_signature matches what the bot will face)
    sim = CareerSimulator(preset=copy.deepcopy(preset), seed=rng_seed)
    deck_ids = [int(c.get("support_card_id") or 0) for c in (sim.deck or [])
                if isinstance(c, dict) and int(c.get("support_card_id") or 0)]
    trainee_card_id = int((sim.preset.get("_run_context") or {}).get("trainee_card_id") or 0)
    friend_card_id = int((sim.preset.get("_run_context") or {}).get("friend_card_id") or 0)
    scenario_id = int(preset.get("scenario_id") or 4)

    if not deck_ids or not trainee_card_id:
        report = {
            "status": "aborted",
            "reason": "no session context found (deck/trainee not detected). "
                      "Make sure the bot has captured a recent session before "
                      "running Calibrate.",
        }
        _log(f"ABORT: {report['reason']}")
        return report

    signature = deck_signature(
        trainee_card_id=trainee_card_id,
        support_card_ids=deck_ids,
        scenario_id=scenario_id,
        friend_card_id=friend_card_id,
    )
    _log(f"deck_signature={signature}  trainee={trainee_card_id}  "
         f"deck={deck_ids}  friend={friend_card_id}")

    # Step 1: baseline
    _log(f"baseline pass: {baseline_sims} sims")
    baseline_seed = rng_seed * 1000
    baseline_results = _run_sims(preset, n=baseline_sims, seed_base=baseline_seed)
    baseline_ss = _ss_rate(baseline_results, ss_threshold)
    baseline_mean = _mean_rating(baseline_results)
    baseline_win_rate = _win_rate(baseline_results)
    baseline_ep_losses = _epithet_losses(baseline_results)
    baseline_min = _min_rating(baseline_results)
    baseline_below_floor = _below_rating_count(baseline_results, min_rating)
    _log(f"baseline: mean={baseline_mean:.0f}  SS-rate={baseline_ss:.2f}  "
         f"win-rate={baseline_win_rate:.3f}  epithet-losses={baseline_ep_losses}  "
         f"min={baseline_min} below-floor={baseline_below_floor}  "
         f"({sum(1 for r in baseline_results if r.rating_score >= ss_threshold)}"
         f"/{len(baseline_results)} SS)")
    _log(f"baseline losses: {_format_loss_summary(baseline_results)}")

    elapsed = time.time() - t_start
    _log(f"elapsed={elapsed:.0f}s / {time_budget_sec:.0f}s")

    # Early exit: baseline already comfortable
    if _is_comfortable(baseline_results, target_ss_rate, target_mean, ss_threshold,
                        target_win_rate=target_win_rate,
                        max_epithet_losses=max_epithet_losses,
                        min_rating=min_rating):
        _log(f"baseline ALREADY comfortable — saving as-is to cache.")
        return {
            "status": "done",
            "reason": "baseline already comfortable",
            "deck_signature": signature,
            "baseline_mean": baseline_mean,
            "baseline_ss_rate": baseline_ss,
            "baseline_win_rate": baseline_win_rate,
            "baseline_epithet_losses": baseline_ep_losses,
            "baseline_min_rating": baseline_min,
            "baseline_below_floor": baseline_below_floor,
            "baseline_loss_summary": _loss_summary(baseline_results),
            "winner_mean": baseline_mean,
            "winner_ss_rate": baseline_ss,
            "winner_win_rate": baseline_win_rate,
            "winner_epithet_losses": baseline_ep_losses,
            "winner_min_rating": baseline_min,
            "winner_below_floor": baseline_below_floor,
            "winner_loss_summary": _loss_summary(baseline_results),
            "candidates_explored": 0,
            "elapsed_sec": time.time() - t_start,
            "saved_to_cache": True,
        }

    # Step 2: adaptive candidate sweep
    best_overrides = {}
    best_results = baseline_results
    best_ss = baseline_ss
    best_mean = baseline_mean
    best_win_rate = baseline_win_rate
    best_key = _quality_key(
        baseline_results,
        ss_threshold=ss_threshold,
        target_win_rate=target_win_rate,
        max_epithet_losses=max_epithet_losses,
        min_rating=min_rating,
    )
    candidates_explored = 0
    sim_seed = baseline_seed + 1_000_000

    _log("entering adaptive candidate sweep (early-term + refine on best)")

    # Phase split: spend the FIRST 2/3 of the time-after-baseline on
    # wide exploration, then the LAST 1/3 refining around the best.
    # Refinement phase perturbs each PARAM_SPACE dim narrowly so we
    # converge on the local optimum instead of re-rolling random.
    baseline_done_at = time.time() - t_start
    remaining_after_baseline = time_budget_sec - baseline_done_at
    explore_budget = remaining_after_baseline * (2.0 / 3.0)
    refine_phase_start = baseline_done_at + explore_budget

    # Adaptive screening size. Keep screening cheap because a fully hydrated
    # sim can take tens of seconds with real observation data loaded.
    initial_screen_sims = max(1, min(2, sims_per_candidate))
    confirm_sims = max(sims_per_candidate, 3)
    elapsed_after_baseline = max(0.1, time.time() - t_start)
    per_sim_estimate = max(
        15.0,
        (elapsed_after_baseline / max(1, len(baseline_results))) * 1.25,
    )
    _log(f"adaptive time model: estimated {per_sim_estimate:.1f}s per sim")

    def _evaluate_candidate(overrides_in, phase_label):
        """Run a candidate with adaptive screening:
          1) initial_screen_sims small batch to cheaply gauge SS potential
          2) if SS rate >= 50% on initial → run confirm_sims MORE for a
             stable measurement
          3) if SS rate == 0% on initial → bail (cannot possibly hit 80%)
          4) middle case → run confirm_sims more to disambiguate
        Returns (results, ss, mean, win_rate, ep_losses, total_sims).
        """
        nonlocal sim_seed
        cand_preset = _merge_overrides_into_preset(preset, overrides_in)
        first = _run_sims(cand_preset, n=initial_screen_sims, seed_base=sim_seed)
        sim_seed += initial_screen_sims
        screen_ss = _ss_rate(first, ss_threshold)
        screen_ep = _epithet_losses(first)
        screen_min = _min_rating(first)
        screen_below = _below_rating_count(first, min_rating)
        _log(f"  [{phase_label}] screen ({initial_screen_sims} sims): "
             f"SS-rate={screen_ss:.2f}  epithet-losses={screen_ep} "
             f"min={screen_min} below-floor={screen_below}")
        if screen_ep > 0 or screen_below > 0 or screen_ss == 0.0:
            _log(f"  [{phase_label}] screen losses: {_format_loss_summary(first)}")
        # Epithet loss → veto early, no point burning more sims
        if screen_ep > max_epithet_losses:
            return first, screen_ss, _mean_rating(first), _win_rate(first), screen_ep, initial_screen_sims
        if screen_below > 0:
            _log(f"  [{phase_label}] EARLY-TERM: below-floor result in screen")
            return first, screen_ss, _mean_rating(first), _win_rate(first), screen_ep, initial_screen_sims
        # 0 SS hits on screen → cannot possibly hit 80%. Bail.
        if screen_ss == 0.0:
            _log(f"  [{phase_label}] EARLY-TERM: 0 SS hits in screen, won't survive 80% bar")
            return first, screen_ss, _mean_rating(first), _win_rate(first), screen_ep, initial_screen_sims
        # Promising or middle → confirm with more sims
        more = _run_sims(cand_preset, n=confirm_sims, seed_base=sim_seed)
        sim_seed += confirm_sims
        combined = first + more
        return (
            combined,
            _ss_rate(combined, ss_threshold),
            _mean_rating(combined),
            _win_rate(combined),
            _epithet_losses(combined),
            initial_screen_sims + confirm_sims,
        )

    def _refine_overrides(base_overrides, rng_inner):
        """Generate a 'neighbor' of `base_overrides` by perturbing 1-3
        random dimensions by a small fraction of their range. Stays close
        to the current best so we converge instead of re-exploring."""
        # Import here to avoid module-load coupling
        from tools.optimize_deck_policy import PARAM_SPACE
        out = dict(base_overrides) if base_overrides else _sample_candidate(rng_inner)
        # Pick 1-3 dims to perturb
        n_perturb = rng_inner.randint(1, min(3, len(PARAM_SPACE)))
        dims = rng_inner.sample(PARAM_SPACE, n_perturb)
        for name, low, high in dims:
            # Perturb by up to ±20% of the range
            span = (high - low) * 0.20
            current = out.get(name)
            if current is None:
                current = (low + high) / 2.0
            if isinstance(low, int) and isinstance(high, int):
                delta = rng_inner.randint(-int(span), int(span)) if int(span) > 0 else 0
                out[name] = max(low, min(high, int(current) + delta))
            else:
                delta = rng_inner.uniform(-span, span)
                out[name] = round(max(low, min(high, current + delta)), 2)
        return out

    candidate_queue = _dedupe_override_candidates(
        _comfort_seed_overrides(preset)
        + _self_learning_overrides_from_results(
            baseline_results,
            preset,
            base_overrides={},
        )
    )
    if candidate_queue:
        _log(f"queued {len(candidate_queue)} self-learning/comfort candidate(s) "
             "before random exploration")

    in_refine_phase = False
    evaluated_override_keys = set()
    while True:
        elapsed = time.time() - t_start
        time_remaining = time_budget_sec - elapsed
        # Adaptive needs initial_screen_sims + (maybe) confirm_sims headroom
        budget_for_one_more = (initial_screen_sims + confirm_sims) * per_sim_estimate
        # If we're tight on time, allow at least the screening part
        if time_remaining < initial_screen_sims * per_sim_estimate:
            _log(f"stopping sweep: insufficient time remaining "
                 f"({time_remaining:.0f}s for one more screen)")
            break

        # Transition to refinement phase once we hit the threshold AND have a best to refine around
        if not in_refine_phase and elapsed >= refine_phase_start and best_overrides:
            in_refine_phase = True
            _log(f"--- entering REFINE phase around best so far (SS={best_ss:.2f}) ---")

        while candidate_queue and _override_key(candidate_queue[0]) in evaluated_override_keys:
            candidate_queue.pop(0)

        if candidate_queue:
            overrides = candidate_queue.pop(0)
            phase_label = "self-learn"
        elif in_refine_phase and best_overrides:
            overrides = _refine_overrides(best_overrides, rng)
            phase_label = "refine"
        else:
            overrides = _sample_candidate(rng)
            phase_label = "explore"
        evaluated_override_keys.add(_override_key(overrides))

        candidates_explored += 1
        _log(f"candidate {candidates_explored} [{phase_label}]: {overrides}")
        cand_results, cand_ss, cand_mean, cand_win_rate, cand_ep_losses, sims_used = \
            _evaluate_candidate(overrides, phase_label)
        cand_min = _min_rating(cand_results)
        cand_below_floor = _below_rating_count(cand_results, min_rating)
        cand_key = _quality_key(
            cand_results,
            ss_threshold=ss_threshold,
            target_win_rate=target_win_rate,
            max_epithet_losses=max_epithet_losses,
            min_rating=min_rating,
        )
        _log(f"  → ({sims_used} sims) mean={cand_mean:.0f}  SS-rate={cand_ss:.2f}  "
             f"win-rate={cand_win_rate:.3f}  epithet-losses={cand_ep_losses} "
             f"min={cand_min} below-floor={cand_below_floor}")
        if cand_ep_losses > 0 or cand_below_floor > 0:
            _log(f"  candidate losses: {_format_loss_summary(cand_results)}")

        if cand_ep_losses > max_epithet_losses:
            _log(f"  candidate vetoed: {cand_ep_losses} epithet-bonus losses")
        elif cand_key > best_key:
            _log(f"  *** new best (was SS={best_ss:.2f} win={best_win_rate:.3f} "
                 f"mean={best_mean:.0f} min={_min_rating(best_results)})")
            best_overrides = overrides
            best_results = cand_results
            best_ss = cand_ss
            best_mean = cand_mean
            best_win_rate = cand_win_rate
            best_key = cand_key
            learned_next = _self_learning_overrides_from_results(
                cand_results,
                preset,
                base_overrides=best_overrides,
            )
            if learned_next:
                before = len(candidate_queue)
                candidate_queue = _dedupe_override_candidates(candidate_queue + learned_next)
                added = len(candidate_queue) - before
                if added > 0:
                    _log(f"  queued {added} follow-up learned candidate(s) "
                         "from new-best batch")

        if _is_comfortable(best_results, target_ss_rate, target_mean, ss_threshold,
                            target_win_rate=target_win_rate,
                            max_epithet_losses=max_epithet_losses,
                            min_rating=min_rating):
            _log(f"COMFORT TARGET HIT after {candidates_explored} candidates.")
            break

    elapsed = time.time() - t_start
    _log(f"sweep done: {candidates_explored} candidates in {elapsed:.0f}s. "
         f"Best: SS-rate={best_ss:.2f}  mean={best_mean:.0f}")

    # Step 3: validate winner on fresh seeds (unless winner == baseline)
    if not best_overrides:
        _log("no candidate beat baseline and baseline is not comfortable; not saving.")
        cache = load_cache(PROJECT_ROOT, instance)
        save_policy(
            cache, signature,
            trainee_card_id=trainee_card_id,
            support_card_ids=deck_ids,
            scenario_id=scenario_id,
            friend_card_id=friend_card_id,
            learned_hyperparameters=dict(preset.get("learned_hyperparameters") or {}),
            baseline_rating_mean=baseline_mean,
            optimized_rating_mean=baseline_mean,
            rating_lift=0,
            n_baseline=len(baseline_results),
            n_optimized=len(baseline_results),
            optimized_at_iso="",
        )
        save_cache(cache, PROJECT_ROOT, instance)
        return {
            "status": "done",
            "reason": "no candidate beat baseline; no policy saved",
            "deck_signature": signature,
            "baseline_mean": baseline_mean,
            "baseline_ss_rate": baseline_ss,
            "baseline_min_rating": baseline_min,
            "baseline_below_floor": baseline_below_floor,
            "baseline_loss_summary": _loss_summary(baseline_results),
            "winner_mean": baseline_mean,
            "winner_ss_rate": baseline_ss,
            "winner_min_rating": baseline_min,
            "winner_below_floor": baseline_below_floor,
            "winner_loss_summary": _loss_summary(baseline_results),
            "candidates_explored": candidates_explored,
            "elapsed_sec": elapsed,
            "saved_to_cache": False,
        }

    _log(f"validation pass: {validation_sims} sims on fresh seeds")
    val_seed = sim_seed + 10_000
    winner_preset = _merge_overrides_into_preset(preset, best_overrides)
    val_results = _run_sims(winner_preset, n=validation_sims, seed_base=val_seed)
    val_ss = _ss_rate(val_results, ss_threshold)
    val_mean = _mean_rating(val_results)
    val_win_rate = _win_rate(val_results)
    val_ep_losses = _epithet_losses(val_results)
    val_min = _min_rating(val_results)
    val_below_floor = _below_rating_count(val_results, min_rating)
    _log(f"validation: mean={val_mean:.0f}  SS-rate={val_ss:.2f}  "
         f"win-rate={val_win_rate:.3f}  epithet-losses={val_ep_losses} "
         f"min={val_min} below-floor={val_below_floor}")
    _log(f"validation losses: {_format_loss_summary(val_results)}")

    # Save if validation either hits the comfort target or is clean
    # best-effort progress. Without the epithet floor, the cache could end up
    # with a "high SS rate but breaks Stunning route" policy that looks great
    # in the sim batch but hurts the average career.
    saved = False
    epithet_clean = val_ep_losses <= max_epithet_losses
    floor_clean = val_min >= min_rating
    win_clean = val_win_rate >= target_win_rate
    comfortable = _is_comfortable(
        val_results,
        target_ss_rate,
        target_mean,
        ss_threshold,
        target_win_rate=target_win_rate,
        max_epithet_losses=max_epithet_losses,
        min_rating=min_rating,
    )
    best_effort_clean = (
        _is_best_effort_clean_progress(
            val_results,
            baseline_results,
            ss_threshold=ss_threshold,
            target_win_rate=target_win_rate,
            max_epithet_losses=max_epithet_losses,
            min_rating=min_rating,
        )
    )
    # Ratchet against LAST SESSION: never overwrite the cached policy with a
    # worse one. Re-sim the currently-cached policy on the SAME validation
    # seeds and require the new winner to beat it on the quality key. This is
    # what makes repeated optimizer.bat runs monotonically improve — a better
    # policy is applied even when it is not consistently SS, but an unlucky or
    # short run can no longer regress a good cached policy. No cached policy
    # for this deck yet -> nothing to beat, save the winner.
    cache = load_cache(PROJECT_ROOT, instance)
    existing_policy = lookup_policy(cache, signature)
    beats_cached = True
    if existing_policy and (existing_policy.get("learned_hyperparameters")):
        cached_preset = apply_policy_to_preset(copy.deepcopy(preset), existing_policy)
        cached_results = _run_sims(cached_preset, n=validation_sims, seed_base=val_seed)
        winner_qk = _quality_key(
            val_results, ss_threshold=ss_threshold, target_win_rate=target_win_rate,
            max_epithet_losses=max_epithet_losses, min_rating=min_rating,
        )
        cached_qk = _quality_key(
            cached_results, ss_threshold=ss_threshold, target_win_rate=target_win_rate,
            max_epithet_losses=max_epithet_losses, min_rating=min_rating,
        )
        beats_cached = winner_qk > cached_qk
        _log(f"vs last-session cached policy: winner mean={val_mean:.0f} "
             f"SS={val_ss:.2f} vs cached mean={_mean_rating(cached_results):.0f} "
             f"SS={_ss_rate(cached_results, ss_threshold):.2f} -> "
             f"{'BETTER (will apply)' if beats_cached else 'NOT better (keeping cached)'}")

    if (comfortable or best_effort_clean) and beats_cached:
        if comfortable:
            _log("validation hit comfort target; saving winner to cache.")
        else:
            _log("validation is clean best-effort progress; saving winner to cache.")
        winner_lhp = dict(winner_preset.get("learned_hyperparameters") or {})
        save_policy(
            cache, signature,
            trainee_card_id=trainee_card_id,
            support_card_ids=deck_ids,
            scenario_id=scenario_id,
            friend_card_id=friend_card_id,
            learned_hyperparameters=winner_lhp,
            baseline_rating_mean=baseline_mean,
            optimized_rating_mean=val_mean,
            rating_lift=val_mean - baseline_mean,
            n_baseline=len(baseline_results),
            n_optimized=len(val_results),
            optimized_at_iso="",
        )
        save_cache(cache, PROJECT_ROOT, instance)
        saved = True
    else:
        if not epithet_clean:
            _log(f"validation REJECTED: {val_ep_losses} epithet-bonus loss(es) — "
                 f"a calibrated policy must not break epithet chains. Not saving.")
        elif not floor_clean:
            _log(f"validation REJECTED: min rating {val_min} is below floor "
                 f"{min_rating}; this would still allow A+ outcomes. Not saving.")
        elif not win_clean:
            _log(f"validation REJECTED: win-rate {val_win_rate:.3f} is below "
                 f"target {target_win_rate:.3f}. Not saving.")
        elif (comfortable or best_effort_clean) and not beats_cached:
            _log("winner did NOT beat the last-session cached policy — "
                 "keeping the better cached policy (no regression).")
        else:
            _log("validation did NOT confirm SS-rate improvement — not saving.")

    elapsed = time.time() - t_start
    _log(f"DONE in {elapsed:.0f}s. saved={saved}")
    return {
        "status": "done",
        "reason": "ok" if saved else (
            "epithet_loss_in_validation" if not epithet_clean
            else "below_min_rating_in_validation" if not floor_clean
            else "below_win_rate_in_validation" if not win_clean
            else "kept_cached_policy_not_beaten" if (comfortable or best_effort_clean) and not beats_cached
            else "no_ss_improvement"
        ),
        "deck_signature": signature,
        "baseline_mean": baseline_mean,
        "baseline_ss_rate": baseline_ss,
        "baseline_win_rate": baseline_win_rate,
        "baseline_epithet_losses": baseline_ep_losses,
        "baseline_min_rating": baseline_min,
        "baseline_below_floor": baseline_below_floor,
        "baseline_loss_summary": _loss_summary(baseline_results),
        "winner_mean": val_mean,
        "winner_ss_rate": val_ss,
        "winner_win_rate": val_win_rate,
        "winner_epithet_losses": val_ep_losses,
        "winner_min_rating": val_min,
        "winner_below_floor": val_below_floor,
        "winner_loss_summary": _loss_summary(val_results),
        "winner_comfortable": comfortable,
        "winner_best_effort_clean": best_effort_clean,
        "winner_overrides": best_overrides,
        "candidates_explored": candidates_explored,
        "elapsed_sec": elapsed,
        "saved_to_cache": saved,
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Fast deck calibration")
    p.add_argument("--time-budget-sec", type=float, default=240.0,
                   help="candidate-sweep time cap in seconds (default 240 = 4 min; "
                        "total run incl. final validation stays at/under ~5 min)")
    p.add_argument("--sims-per-candidate", type=int, default=2)
    p.add_argument("--baseline-sims", type=int, default=2)
    p.add_argument("--validation-sims", type=int, default=3)
    p.add_argument("--target-ss-rate", type=float, default=0.95,
                   help="comfort threshold: SS rate target (default 0.95)")
    p.add_argument("--target-mean", type=int, default=17500,
                   help="comfort threshold: mean rating target (default 17500 — "
                        "= SS threshold, so 'comfortable' means the AVERAGE "
                        "career hits SS, not just 60%% of them)")
    p.add_argument("--ss-threshold", type=int, default=17500,
                   help="SS rank rating threshold (game-fixed at 17500)")
    p.add_argument("--target-win-rate", type=float, default=0.95,
                   help="comfort threshold: total race-win rate (default 0.95 — "
                        ">95%% of all races won in calibration sims)")
    p.add_argument("--max-epithet-losses", type=int, default=2,
                   help="max losses on epithet-bonus races across calibration "
                        "sims (default 2 — tolerates 2-sim screening noise; a "
                        "career drops 2-3 races by luck and ~7 G1s gate "
                        "epithets, so 0 rejected every candidate on noise. The "
                        "quality ranking still prefers fewer epithet losses.)")
    p.add_argument("--min-rating", type=int, default=14500,
                   help="minimum allowed rating in validation sims "
                        "(default 14500 = no A+ outcomes)")
    p.add_argument("--preset-path", type=str, default="",
                   help="path to baseline preset; default uses production preset")
    p.add_argument("--seed", type=int, default=int(time.time()) % 1_000_000)
    p.add_argument("--instance", type=str, default="account_b")
    p.add_argument("--report-out", type=str, default="",
                   help="if set, write the report JSON here")
    args = p.parse_args(argv)

    preset_path = Path(args.preset_path) if args.preset_path else None
    report = calibrate(
        time_budget_sec=args.time_budget_sec,
        sims_per_candidate=args.sims_per_candidate,
        baseline_sims=args.baseline_sims,
        validation_sims=args.validation_sims,
        target_ss_rate=args.target_ss_rate,
        target_mean=args.target_mean,
        ss_threshold=args.ss_threshold,
        target_win_rate=args.target_win_rate,
        max_epithet_losses=args.max_epithet_losses,
        min_rating=args.min_rating,
        preset_path=preset_path,
        rng_seed=args.seed,
        instance=args.instance,
    )
    print("\n" + "=" * 70)
    print(json.dumps(report, indent=2, default=str))
    print("=" * 70)
    if args.report_out:
        try:
            Path(args.report_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.report_out).write_text(
                json.dumps(report, indent=2, default=str), encoding="utf-8"
            )
        except OSError as exc:
            print(f"failed to write report to {args.report_out}: {exc}", flush=True)
    return 0 if report.get("status") == "done" else 2


if __name__ == "__main__":
    sys.exit(main())
