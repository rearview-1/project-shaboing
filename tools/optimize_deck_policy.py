"""Per-deck offline hyperparameter optimization.

Runs N candidate hyperparameter sets through the sim against the
user's current deck/trainee/scenario, picks the candidate with the
highest mean rating, and writes the winning policy to
`uma_runtime/instances/<instance>/sim_calibration/deck_policies.json`.

This is the "offline knowledge generation" half of the many-worlds
architecture: the sim explores parameter space; the bot reads the
winning policy from the cache during real-career hydration.

Usage:
    python tools/optimize_deck_policy.py \
        --candidates 8 --sims-per-candidate 5 --validation-sims 8

Outputs (stdout): baseline mean, candidate scores, winning policy,
validation comparison, and the cache-write confirmation.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import random
import sys
import statistics
import time
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from career_bot.career_simulator import CareerSimulator  # noqa: E402
from career_bot.deck_policy_cache import (  # noqa: E402
    apply_policy_to_preset,
    deck_signature,
    load_cache,
    lookup_policy,
    save_cache,
    save_policy,
)


def _base_preset(preset_path: Path | None = None) -> dict:
    """Load the preset to use as baseline.

    Uses the SAME resolution path as the live bot's
    `resolve_effective_preset`: config layer (where the UI save lands)
    merged with the instance-learning override (where auto-tuning lands),
    with `_preserve_operator_owned_fields` keeping the operator's UI
    saves (skill_profile_style, skill_buy_on_sight, learn_skill_list,
    etc.) winning over any stale learned values. Without this, calibrate
    would silently load only the instance override and run a strategy
    the operator no longer wants — exactly the "calibrate runs Front
    when I saved Pace" symptom.

    Caller can still pass `preset_path` to bypass auto-resolution and
    load a raw file directly (used by unit tests).
    """
    if preset_path is not None:
        if preset_path and preset_path.exists():
            preset = json.loads(preset_path.read_text(encoding="utf-8-sig"))
            preset.setdefault("scenario_id", preset.get("scenario", 4))
            preset.setdefault("sim_use_latest_session_context", True)
            preset["name"] = f"{preset.get('name', 'preset')}__optimizer"
            return preset
        # Fall through to vanilla shape below
    else:
        # Auto-resolve using main's preset resolution (same path live bot uses)
        try:
            import sys as _sys
            _sys.path.insert(0, str(PROJECT_ROOT))
            import main as _main
            preset_name = _main.default_run_preset_name() or "xguri parent"
            preset = _main.resolve_effective_preset(preset_name)
            if preset:
                preset.setdefault("scenario_id", preset.get("scenario", 4))
                preset.setdefault("sim_use_latest_session_context", True)
                preset["name"] = f"{preset.get('name', 'preset')}__optimizer"
                return preset
        except Exception as exc:
            print(f"[calibrate] resolve_effective_preset failed: {exc!r}; "
                  f"falling back to direct file load.", flush=True)
        # Fallback: load the instance learning override file directly
        default_path = (
            PROJECT_ROOT / "uma_runtime" / "instances" / "account_b"
            / "instance_learning" / "presets" / "xguri parent.json"
        )
        if default_path.exists():
            preset = json.loads(default_path.read_text(encoding="utf-8-sig"))
            preset.setdefault("scenario_id", preset.get("scenario", 4))
            preset.setdefault("sim_use_latest_session_context", True)
            preset["name"] = f"{preset.get('name', 'preset')}__optimizer"
            return preset
    # Vanilla fallback (only used if no preset file exists)
    return {
        "name": "deck_policy_optimizer_vanilla",
        "scenario_id": 4,
        "learn_skill_threshold": 444,
        "manual_purchase_at_end": True,
        "calendar_race_prebuy_enabled": True,
        "calendar_race_prebuy_budget": 850,
        "calendar_race_prebuy_keep_sp": 100,
        "calendar_race_prebuy_max_skills": 4,
        "stat_value_multiplier": [0.022, 0.016, 0.018, 0.012, 0.016, 0.01],
        "score_value": [[0.11, 0.1, 0.006, 0.09]] * 5,
        "base_score": [0, 0, 0, 0, 0],
        "extra_weight": [[0, 0, 0, 0, 0]] * 4,
        "compensate_failure": True,
        "expect_attribute": [9999, 9999, 9999, 9999, 9999],
        "stat_priority_architecture_enabled": True,
        "sim_use_latest_session_context": True,
    }


# Curated parameters that meaningfully shift the rating distribution
# without exploding the search space. Each entry: (name, low, high).
# Values are sampled uniformly from [low, high] when generating a candidate.
#
# Soft cap knobs (speed_soft_cap, wit_soft_cap, power_soft_cap,
# stamina_soft_cap) were REMOVED from the search space on 2026-06-09.
# Operator policy is now:
#   - Mid-career: high baked-in defaults (1200 for main rating stats,
#     1000 for support stats) — bot pushes freely
#   - Last week (T >= 70): hard clamp to 1100 regardless of any tuned
#     override (mant._per_stat_soft_cap late-week clamp wins over
#     learned_hyperparameters)
# Sampling cap values here just burned budget on a dimension that
# couldn't move the rating curve in either direction under that policy.
# The optimizer now focuses its samples on the priority bonuses and
# race-prebuy skill counts — the dimensions that DO move the result.
PARAM_SPACE = [
    ("speed_priority_bonus_mid",        0.16, 0.45),
    ("speed_priority_bonus_late",       0.22, 0.60),
    ("speed_floor_target",              900, 1200),
    ("wit_priority_bonus_mid",          0.14, 0.55),
    ("wit_priority_bonus_late",         0.30, 0.70),
    ("stamina_priority_bonus_base",     0.00, 0.25),
    ("stamina_priority_deficit_boost",  0.00, 0.25),
    ("stamina_floor_target",            650, 1100),
    ("power_priority_bonus_base",       0.00, 0.30),
    ("power_priority_deficit_boost",    0.00, 0.30),
    ("power_floor_target",              850, 1200),
    ("calendar_race_prebuy_budget",     850, 1800),
    ("calendar_race_prebuy_keep_sp",    0, 250),
    ("calendar_race_prebuy_max_skills", 4, 12),
    ("rest_threshold",                  28, 62),
]


def _objective_score(results, objective: str, threshold: int = 17500) -> float:
    """Score a set of sim results by the chosen objective.

    - "mean": traditional mean rating (max expected rating)
    - "ss_rate": fraction of sims hitting >= threshold (default SS = 17500).
      Aligns with user's framing of tuning for unreached ranks rather
      than averaging.
    - "p80": 80th-percentile rating (max top-tail)
    """
    ratings = [r.rating_score for r in results]
    if not ratings:
        return 0.0
    if objective == "ss_rate":
        return sum(1 for r in ratings if r >= threshold) / len(ratings)
    if objective == "p80":
        return statistics.quantiles(ratings, n=5)[3] if len(ratings) >= 5 else max(ratings)
    return statistics.mean(ratings)


def _sample_candidate(rng: random.Random) -> dict:
    cand = {}
    for name, low, high in PARAM_SPACE:
        if isinstance(low, int) and isinstance(high, int):
            cand[name] = rng.randint(low, high)
        else:
            # Snap to 2 decimals for log readability
            cand[name] = round(rng.uniform(low, high), 2)
    return cand


def _run_sims(preset: dict, *, n: int, seed_base: int, label: str) -> list:
    results = []
    t0 = time.time()
    for i in range(n):
        sim = CareerSimulator(preset=copy.deepcopy(preset), seed=seed_base + i)
        r = sim.run()
        results.append(r)
    elapsed = time.time() - t0
    ratings = [r.rating_score for r in results]
    print(f"  [{label}] n={n}  mean={statistics.mean(ratings):.0f}  "
          f"median={statistics.median(ratings):.0f}  "
          f"min={min(ratings)}  max={max(ratings)}  ({elapsed:.0f}s)",
          flush=True)
    return results


def _summary(results):
    ratings = [r.rating_score for r in results]
    return {
        "rating_mean": float(statistics.mean(ratings)),
        "rating_median": float(statistics.median(ratings)),
        "rating_min": int(min(ratings)),
        "rating_max": int(max(ratings)),
        "stat_sum_mean": float(statistics.mean([r.stat_sum for r in results])),
        "g1_wins_mean": float(statistics.mean([r.g1_wins for r in results])),
        "g1_losses_mean": float(statistics.mean([r.g1_losses for r in results])),
        "ranks": [r.rank for r in results],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--candidates", type=int, default=8,
                    help="Random hyperparameter candidates to evaluate")
    ap.add_argument("--sims-per-candidate", type=int, default=5,
                    help="Sim runs per candidate (more = lower variance)")
    ap.add_argument("--baseline-sims", type=int, default=8,
                    help="Sim runs to establish baseline rating with defaults")
    ap.add_argument("--validation-sims", type=int, default=8,
                    help="Sim runs to validate winning policy vs baseline")
    ap.add_argument("--seed", type=int, default=42,
                    help="RNG seed for candidate generation (reproducibility)")
    ap.add_argument("--instance", default="account_b")
    ap.add_argument("--baseline-seed-base", type=int, default=10_000)
    ap.add_argument("--candidate-seed-base", type=int, default=20_000)
    ap.add_argument("--validation-seed-base", type=int, default=30_000)
    ap.add_argument("--preset-path", type=str, default=None,
                    help="Path to a baseline preset .json. Defaults to the "
                         "user's production preset at "
                         "uma_runtime/instances/<instance>/instance_learning/"
                         "presets/*.json (first match).")
    ap.add_argument("--objective", choices=("mean", "ss_rate", "p80"),
                    default="ss_rate",
                    help="Objective function for ranking candidates: "
                         "mean (max expected rating), "
                         "ss_rate (max P(rating >= SS threshold)), "
                         "p80 (max 80th-percentile rating). Default ss_rate.")
    ap.add_argument("--ss-threshold", type=int, default=17500,
                    help="Rating threshold for ss_rate objective. Default 17500 (SS).")
    args = ap.parse_args()

    print("=" * 70, flush=True)
    print("Per-deck hyperparameter optimization", flush=True)
    print(f"  objective: {args.objective}"
          + (f" (threshold={args.ss_threshold})" if args.objective == "ss_rate" else ""),
          flush=True)
    print("=" * 70, flush=True)

    preset_path = Path(args.preset_path) if args.preset_path else None
    base_preset = _base_preset(preset_path)
    print(f"  baseline preset: {base_preset.get('name')}", flush=True)
    lhp_count = len((base_preset.get("learned_hyperparameters") or {}))
    print(f"  baseline carries {lhp_count} learned_hyperparameters from preset",
          flush=True)

    # Hydrate from latest session context to pull in trainee + deck.
    print("\nHydrating with latest session context (trainee + deck)...",
          flush=True)
    probe = CareerSimulator(preset=copy.deepcopy(base_preset), seed=999)
    deck = probe.deck or []
    deck_ids = [int(c.get("support_card_id") or c.get("id") or 0)
                for c in deck if isinstance(c, dict)]
    deck_ids = [i for i in deck_ids if i]
    trainee_card_id = int(probe.trainee_card_id or 0)
    friend_card_id = 0
    run_context = (base_preset.get("_run_context") or {})
    if not run_context:
        run_context = (probe.preset.get("_run_context") or {})
    friend_card_id = int(run_context.get("friend_card_id") or 0)
    scenario_id = int(base_preset.get("scenario_id") or 4)

    print(f"  trainee_card_id: {trainee_card_id}")
    print(f"  scenario_id:     {scenario_id}")
    print(f"  friend_card_id:  {friend_card_id}")
    print(f"  deck ({len(deck_ids)} cards): {deck_ids}")

    signature = deck_signature(
        trainee_card_id=trainee_card_id,
        support_card_ids=deck_ids,
        scenario_id=scenario_id,
        friend_card_id=friend_card_id,
    )
    print(f"  deck signature: {signature}")

    # Step 1: Baseline
    print(f"\n[1/4] Baseline (defaults), {args.baseline_sims} sims:", flush=True)
    baseline_results = _run_sims(
        base_preset,
        n=args.baseline_sims,
        seed_base=args.baseline_seed_base,
        label="baseline",
    )
    baseline = _summary(baseline_results)

    # Step 2: Candidate exploration
    print(f"\n[2/4] Candidate exploration: {args.candidates} candidates "
          f"× {args.sims_per_candidate} sims each", flush=True)
    rng = random.Random(args.seed)
    candidates = []
    for i in range(args.candidates):
        hp_sample = _sample_candidate(rng)
        cand_preset = copy.deepcopy(base_preset)
        # Merge candidate overrides into the preset's existing
        # learned_hyperparameters (so we keep the baseline values for
        # parameters not in PARAM_SPACE). Candidate sample WINS.
        merged = dict(cand_preset.get("learned_hyperparameters") or {})
        merged.update(hp_sample)
        cand_preset["learned_hyperparameters"] = merged
        print(f"\n  candidate {i+1}/{args.candidates}: {hp_sample}", flush=True)
        results = _run_sims(
            cand_preset,
            n=args.sims_per_candidate,
            seed_base=args.candidate_seed_base + i * 100,
            label=f"cand{i+1}",
        )
        s = _summary(results)
        score = _objective_score(results, args.objective, args.ss_threshold)
        s["objective_score"] = score
        if args.objective == "ss_rate":
            ss_hits = sum(1 for r in results if r.rating_score >= args.ss_threshold)
            print(f"    objective={args.objective} score={score:.3f} "
                  f"(SS-hits: {ss_hits}/{len(results)})", flush=True)
        else:
            print(f"    objective={args.objective} score={score:.0f}", flush=True)
        candidates.append({
            "hp_sample": hp_sample,  # only the sampled keys
            "hp_full": merged,        # baseline + sampled (what bot would use)
            "summary": s,
        })

    # Pick winner by chosen objective
    candidates.sort(key=lambda c: -c["summary"]["objective_score"])
    winner = candidates[0]
    print(f"\n[winner] objective={args.objective} score={winner['summary']['objective_score']:.3f} "
          f"mean_rating={winner['summary']['rating_mean']:.0f}", flush=True)
    print(f"  sampled overrides: {winner['hp_sample']}", flush=True)

    # Step 3: Validation (winner vs baseline on fresh seeds)
    print(f"\n[3/4] Validation: {args.validation_sims} sims each "
          f"(fresh seeds)", flush=True)
    print("  -- baseline --", flush=True)
    val_baseline = _run_sims(
        base_preset,
        n=args.validation_sims,
        seed_base=args.validation_seed_base,
        label="val_baseline",
    )
    print("  -- winner --", flush=True)
    winner_preset = copy.deepcopy(base_preset)
    winner_preset["learned_hyperparameters"] = winner["hp_full"]
    val_winner = _run_sims(
        winner_preset,
        n=args.validation_sims,
        seed_base=args.validation_seed_base,
        label="val_winner",
    )

    base_mean = statistics.mean(r.rating_score for r in val_baseline)
    win_mean = statistics.mean(r.rating_score for r in val_winner)
    base_obj = _objective_score(val_baseline, args.objective, args.ss_threshold)
    win_obj = _objective_score(val_winner, args.objective, args.ss_threshold)
    lift = win_mean - base_mean
    obj_lift = win_obj - base_obj
    base_ss = sum(1 for r in val_baseline if r.rating_score >= args.ss_threshold)
    win_ss = sum(1 for r in val_winner if r.rating_score >= args.ss_threshold)
    n_val = args.validation_sims
    print(f"\nValidation: baseline mean={base_mean:.0f}  winner mean={win_mean:.0f}  mean lift={lift:+.0f}", flush=True)
    print(f"  baseline SS hits: {base_ss}/{n_val}  winner SS hits: {win_ss}/{n_val}", flush=True)
    print(f"  baseline {args.objective} score: {base_obj:.3f}  winner {args.objective} score: {win_obj:.3f}  obj lift: {obj_lift:+.3f}", flush=True)

    # Step 4: Cache if winner is meaningfully better on the chosen objective
    saved = False
    if obj_lift > 0:
        print(f"\n[4/4] Winner outperformed baseline on {args.objective} "
              f"(lift={obj_lift:+.3f}). Saving policy to cache.", flush=True)
        cache = load_cache(PROJECT_ROOT, args.instance)
        save_policy(
            cache,
            signature,
            trainee_card_id=trainee_card_id,
            support_card_ids=deck_ids,
            scenario_id=scenario_id,
            friend_card_id=friend_card_id,
            learned_hyperparameters=winner["hp_sample"],
            baseline_rating_mean=base_mean,
            optimized_rating_mean=win_mean,
            rating_lift=lift,
            n_baseline=args.validation_sims,
            n_optimized=args.validation_sims,
            optimized_at_iso=datetime.now().isoformat(timespec="seconds"),
        )
        save_cache(cache, PROJECT_ROOT, args.instance)
        from career_bot.deck_policy_cache import cache_path as _cp
        print(f"  saved → {_cp(PROJECT_ROOT, args.instance)}", flush=True)
        saved = True
    else:
        print(f"\n[4/4] Winner did NOT outperform baseline on {args.objective} "
              f"(lift={obj_lift:+.3f}). Not saving.", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("Summary:", flush=True)
    print(f"  Objective: {args.objective}"
          + (f" (threshold={args.ss_threshold})" if args.objective == "ss_rate" else ""),
          flush=True)
    print(f"  Baseline mean rating: {base_mean:.0f}  SS hits: {base_ss}/{n_val}", flush=True)
    print(f"  Winner   mean rating: {win_mean:.0f}  SS hits: {win_ss}/{n_val}", flush=True)
    print(f"  Mean rating lift:     {lift:+.0f}", flush=True)
    print(f"  Objective score lift: {obj_lift:+.3f}", flush=True)
    print(f"  Winning overrides:    {winner['hp_sample']}", flush=True)
    print(f"  Saved to cache:       {saved}", flush=True)
    print("=" * 70, flush=True)


if __name__ == "__main__":
    main()
