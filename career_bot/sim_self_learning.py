"""Sim self-learning: extract execution patterns from a sim batch.

The bot's job: run a batch of sims with the operator's locked
deck/calendar/strategy, observe which sims hit SS vs A+/S, and propose
concrete numeric tweaks to its OWN execution-layer hyperparameters
(priority bonuses, floor targets, etc.) — never the operator-owned
intent fields (deck, calendar, skill_profile_style, parents).

This module is the analyzer half. It takes a batch of SimResults and
emits Proposals. The caller (calibrate, or a future self-learning loop)
is responsible for testing each proposal in a fresh sim batch and
keeping the winners.

Design notes:
  - Compares top-quartile (highest rating) to bottom-quartile sims
  - Looks at training-pick distribution by stat
  - Maps observed deltas to specific learned_hyperparameter changes
  - Each proposal carries a rationale string the operator can audit
  - Proposals only target keys in `LEARNABLE_PARAMS` — operator-owned
    intent fields are explicitly excluded
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Iterable


# Hyperparameter keys the bot is ALLOWED to propose adjustments to.
# Conspicuously NOT in this list: skill_profile_style, deck composition,
# race calendar entries, parent IDs — those are operator-owned.
LEARNABLE_PARAMS = {
    # Per-stat priority bonuses — drive training tile picks
    "speed_priority_bonus_mid",
    "speed_priority_bonus_late",
    "stamina_priority_bonus_base",
    "stamina_priority_deficit_boost",
    "power_priority_bonus_base",
    "power_priority_bonus_late",
    "power_priority_deficit_boost",
    "wit_priority_bonus_mid",
    "wit_priority_bonus_late",
    # Floor targets — push stats to at-least N
    "speed_floor_target",
    "stamina_floor_target",
    "power_floor_target",
    # Skill-buy timing & budget
    "calendar_race_prebuy_budget",
    "calendar_race_prebuy_max_skills",
    "calendar_race_prebuy_keep_sp",
    "skill_point_drain_floor",
    # Rest / training caution
    "rest_threshold",
    # Race-targeting weights — let the optimizer learn to TRAIN toward the stat
    # profile that historically WINS each upcoming race (race_success) and away
    # from what lost it (race_specific demand), instead of only chasing raw
    # rating via speed/wit priorities (which kept losing the balanced G1s).
    "race_success_bonus_cap",
    "race_specific_demand_cap",
}

# Conservative bounds for values the sim is allowed to test/write.
# These are execution-layer knobs, not user intent. Bounds prevent a
# noisy sim batch from generating impossible or destructive policies.
LEARNABLE_PARAM_BOUNDS = {
    "speed_priority_bonus_mid": (0.00, 0.45),
    "speed_priority_bonus_late": (0.00, 0.60),
    "stamina_priority_bonus_base": (0.00, 0.25),
    "stamina_priority_deficit_boost": (0.00, 0.25),
    "power_priority_bonus_base": (0.00, 0.30),
    "power_priority_bonus_late": (0.00, 0.40),
    "power_priority_deficit_boost": (0.00, 0.30),
    "wit_priority_bonus_mid": (0.00, 0.55),
    "wit_priority_bonus_late": (0.00, 0.70),
    "speed_floor_target": (700, 1200),
    "stamina_floor_target": (450, 1100),
    "power_floor_target": (650, 1200),
    "calendar_race_prebuy_budget": (400, 1800),
    "calendar_race_prebuy_max_skills": (0, 12),
    "calendar_race_prebuy_keep_sp": (0, 350),
    "skill_point_drain_floor": (0, 250),
    "rest_threshold": (20, 75),
    "race_success_bonus_cap": (0.04, 0.45),
    "race_specific_demand_cap": (0.10, 0.40),
}

INTEGER_PARAMS = {
    "speed_floor_target",
    "stamina_floor_target",
    "power_floor_target",
    "calendar_race_prebuy_budget",
    "calendar_race_prebuy_max_skills",
    "calendar_race_prebuy_keep_sp",
    "skill_point_drain_floor",
    "rest_threshold",
}


@dataclass
class Proposal:
    """One concrete numeric adjustment for a learned_hyperparameter.

    Caller is expected to merge `(param_name, proposed_value)` into the
    preset's `learned_hyperparameters`, run the sim batch, and decide
    whether the proposal improved the outcome. Caller MUST verify
    `param_name in LEARNABLE_PARAMS` before applying — the analyzer
    enforces this on its own output but a defensive caller protects
    against future bugs.
    """
    param_name: str
    current_value: float
    proposed_value: float
    rationale: str
    # Optional priority hint — caller may test high-priority proposals first
    expected_lift_hint: float = 0.0


def _train_pick_counts(result) -> dict[str, int]:
    """Per-stat training pick counts for one sim result."""
    by_stat = getattr(result, "train_picks_by_stat", None) or {}
    return {k: int(v or 0) for k, v in by_stat.items()}


def _train_pick_rates(results: Iterable) -> dict[str, float]:
    """Aggregated per-stat training pick RATE across a batch of results.

    Returns the fraction of all training picks (across all sims in the
    batch) that went to each stat. Caller compares top-quartile vs
    bottom-quartile rates to spot patterns.
    """
    totals = {"speed": 0, "stamina": 0, "power": 0, "guts": 0, "wit": 0}
    for r in results:
        for stat, n in _train_pick_counts(r).items():
            if stat in totals:
                totals[stat] += n
    grand = sum(totals.values())
    if grand <= 0:
        return {k: 0.0 for k in totals}
    return {k: v / grand for k, v in totals.items()}


def _quartile_split(results: list, lo_pct=25, hi_pct=75) -> tuple[list, list]:
    """Split results into bottom-quartile (worst rating) and top-quartile
    (best rating) lists. Returns (bottom, top)."""
    ranked = sorted(results, key=lambda r: getattr(r, "rating_score", 0))
    if len(ranked) < 2:
        return ([], [])
    n = len(ranked)
    lo_n = max(1, int(round(n * lo_pct / 100)))
    hi_n = max(1, int(round(n * (100 - hi_pct) / 100)))
    bottom = ranked[:lo_n]
    top = ranked[-hi_n:]
    return bottom, top


def _current_lhp_value(preset: dict | None, key: str, default: float) -> float:
    """Read the current value of a learned hyperparameter from the
    preset, falling back to the supplied default."""
    if not isinstance(preset, dict):
        return float(default)
    lhp = preset.get("learned_hyperparameters") or {}
    if key in lhp:
        try:
            return float(lhp[key])
        except (TypeError, ValueError):
            return float(default)
    return float(default)


def clamp_learned_value(param_name: str, value):
    """Clamp a proposed learned_hyperparameter to its safe range.

    Unknown params are returned unchanged so this helper is harmless for
    tests and future expansion, but callers should still only apply
    params in LEARNABLE_PARAMS.
    """
    if param_name not in LEARNABLE_PARAM_BOUNDS:
        return value
    low, high = LEARNABLE_PARAM_BOUNDS[param_name]
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = float(low)
    numeric = max(float(low), min(float(high), numeric))
    if param_name in INTEGER_PARAMS:
        return int(round(numeric))
    return round(numeric, 4)


# Defaults for the priority bonuses we compute proposals over. These
# are the auto-tuner defaults from hyperparameter_tuner.py — used only
# as a fallback when the preset hasn't pinned a value yet.
_PRIORITY_BONUS_DEFAULTS = {
    "speed_priority_bonus_mid":    0.04,
    "speed_priority_bonus_late":   0.22,
    "stamina_priority_bonus_base": 0.03,
    "power_priority_bonus_base":   0.03,
    "power_priority_bonus_late":   0.05,
    "wit_priority_bonus_mid":      0.14,
    "wit_priority_bonus_late":     0.30,
}


def propose_priority_bonus_adjustments(
    results: list,
    preset: dict | None = None,
    *,
    min_rate_delta: float = 0.04,
    step: float = 0.02,
) -> list[Proposal]:
    """Compare top vs bottom quartile training pick rates and propose
    priority-bonus adjustments for stats where the gap is real.

    Args:
      results: at least 4 sim results (less → no proposals).
      preset: current preset, used to read existing values.
      min_rate_delta: minimum top-vs-bottom pick-rate delta to act on.
        Tunable. Default 0.04 (4 percentage points) — below this we
        consider the difference noise.
      step: numeric increment per proposal. Default 0.02. Caller can
        accept-or-reject; rejected proposals are just no-ops.

    Returns:
      List of Proposal objects, possibly empty. Each carries
      param_name, current/proposed values, and a plain-language rationale
      the operator can audit.
    """
    if not results or len(results) < 4:
        return []
    bottom, top = _quartile_split(results)
    if not bottom or not top:
        return []
    bottom_rates = _train_pick_rates(bottom)
    top_rates = _train_pick_rates(top)
    # Mean ratings, for the rationale string
    top_mean = statistics.mean(
        getattr(r, "rating_score", 0) for r in top
    )
    bot_mean = statistics.mean(
        getattr(r, "rating_score", 0) for r in bottom
    )

    proposals: list[Proposal] = []
    # For each stat with a meaningful late-game priority knob, look at
    # whether top quartile picked it more often than bottom. If yes,
    # propose lifting that stat's priority bonus.
    stat_to_late_knob = {
        "speed":   "speed_priority_bonus_late",
        "stamina": "stamina_priority_bonus_base",  # no _late variant — use base
        "power":   "power_priority_bonus_late",
        "wit":     "wit_priority_bonus_late",
    }
    for stat, knob in stat_to_late_knob.items():
        if knob not in LEARNABLE_PARAMS:
            continue
        top_r = top_rates.get(stat, 0.0)
        bot_r = bottom_rates.get(stat, 0.0)
        delta = top_r - bot_r
        if delta < min_rate_delta:
            continue
        current = _current_lhp_value(
            preset, knob,
            _PRIORITY_BONUS_DEFAULTS.get(knob, 0.05),
        )
        proposed = clamp_learned_value(knob, current + step)
        rationale = (
            f"top-quartile sims (mean {top_mean:.0f}) picked {stat} "
            f"on {top_r * 100:.1f}% of training turns vs "
            f"{bot_r * 100:.1f}% for bottom-quartile (mean {bot_mean:.0f}). "
            f"Δ={delta * 100:.1f}pp suggests pushing {stat} priority."
        )
        proposals.append(Proposal(
            param_name=knob,
            current_value=current,
            proposed_value=proposed,
            rationale=rationale,
            expected_lift_hint=top_mean - bot_mean,
        ))
    return proposals


def _mean_final_stats(results: list) -> dict[str, float]:
    totals = {"speed": 0.0, "stamina": 0.0, "power": 0.0, "guts": 0.0, "wit": 0.0}
    count = 0
    for r in results or []:
        stats = getattr(r, "final_stats", None) or {}
        if not isinstance(stats, dict):
            continue
        any_stat = False
        for stat in totals:
            if stat not in stats:
                continue
            try:
                totals[stat] += float(stats.get(stat) or 0)
                any_stat = True
            except (TypeError, ValueError):
                pass
        if any_stat:
            count += 1
    if count <= 0:
        return {}
    return {k: v / count for k, v in totals.items()}


def propose_final_stat_pressure_adjustments(
    results: list,
    preset: dict | None = None,
    *,
    target_stats: dict[str, int] | None = None,
    min_shortfall: int = 80,
) -> list[Proposal]:
    """Propose SS-oriented pressure when the batch misses final stats.

    The priority-rate analyzer only learns from relative patterns inside
    a batch. If every sim is undertraining Speed/Wit/Power, there may be
    no top-vs-bottom contrast to learn from. This analyzer adds absolute
    pressure toward SS-capable end stats while staying in safe bounded
    learned_hyperparameters.
    """
    if not results or len(results) < 2:
        return []
    targets = dict(target_stats or {
        "speed": 1120,
        "stamina": 650,
        "power": 950,
        "guts": 450,
        "wit": 1120,
    })
    means = _mean_final_stats(results)
    if not means:
        return []
    proposals: list[Proposal] = []

    def _append(param_name: str, default: float, proposed, stat: str, shortfall: float):
        if param_name not in LEARNABLE_PARAMS:
            return
        current = _current_lhp_value(preset, param_name, default)
        bounded = clamp_learned_value(param_name, proposed)
        try:
            if float(bounded) <= float(current):
                return
        except (TypeError, ValueError):
            return
        proposals.append(Proposal(
            param_name=param_name,
            current_value=current,
            proposed_value=bounded,
            rationale=(
                f"batch mean {stat}={means.get(stat, 0.0):.0f} is "
                f"{shortfall:.0f} below SS target {targets[stat]}; "
                f"raise {param_name} to increase {stat} pressure."
            ),
            expected_lift_hint=shortfall,
        ))

    for stat, target in targets.items():
        mean = means.get(stat, 0.0)
        shortfall = float(target) - mean
        if shortfall < min_shortfall:
            continue
        if stat == "speed":
            cur_bonus = _current_lhp_value(preset, "speed_priority_bonus_late", 0.22)
            _append("speed_priority_bonus_late", 0.22, cur_bonus + 0.03, stat, shortfall)
        elif stat == "stamina":
            cur_floor = _current_lhp_value(preset, "stamina_floor_target", 650)
            _append("stamina_floor_target", 650, max(cur_floor + 50, min(target, 1100)), stat, shortfall)
            cur_bonus = _current_lhp_value(preset, "stamina_priority_deficit_boost", 0.03)
            _append("stamina_priority_deficit_boost", 0.03, cur_bonus + 0.03, stat, shortfall)
        elif stat == "power":
            cur_floor = _current_lhp_value(preset, "power_floor_target", 900)
            _append("power_floor_target", 900, max(cur_floor + 50, min(target, 1200)), stat, shortfall)
            cur_bonus = _current_lhp_value(preset, "power_priority_deficit_boost", 0.04)
            _append("power_priority_deficit_boost", 0.04, cur_bonus + 0.03, stat, shortfall)
        elif stat == "wit":
            cur_mid = _current_lhp_value(preset, "wit_priority_bonus_mid", 0.14)
            _append("wit_priority_bonus_mid", 0.14, cur_mid + 0.03, stat, shortfall)
            cur_late = _current_lhp_value(preset, "wit_priority_bonus_late", 0.30)
            _append("wit_priority_bonus_late", 0.30, cur_late + 0.04, stat, shortfall)

    return proposals


def propose_race_reliability_adjustments(
    results: list,
    preset: dict | None = None,
    *,
    target_win_rate: float = 0.95,
) -> list[Proposal]:
    """Propose safety changes when sims are still losing scheduled races.

    This is intentionally direct: race failures should cause the optimizer to
    test more pre-race skill spend and higher stamina/power pressure. The
    calendar itself remains locked; this only changes how safely the bot enters
    those required races.
    """
    total = 0
    wins = 0
    g1_losses = 0
    for result in results or []:
        for race in getattr(result, "races_run", None) or []:
            if not isinstance(race, dict):
                continue
            total += 1
            won = bool(race.get("won"))
            if won:
                wins += 1
            else:
                grade = str(race.get("grade") or race.get("grade_label") or "").upper()
                if grade == "G1":
                    g1_losses += 1
    if total <= 0:
        return []
    win_rate = wins / total
    if win_rate >= target_win_rate and g1_losses <= 0:
        return []

    proposals: list[Proposal] = []

    def _append(param_name: str, default: float, proposed, rationale: str, lift: float):
        if param_name not in LEARNABLE_PARAMS:
            return
        current = _current_lhp_value(preset, param_name, default)
        bounded = clamp_learned_value(param_name, proposed)
        if bounded == current:
            return
        proposals.append(Proposal(
            param_name=param_name,
            current_value=current,
            proposed_value=bounded,
            rationale=rationale,
            expected_lift_hint=lift,
        ))

    shortfall = max(0.0, target_win_rate - win_rate)
    reason = (
        f"sim race win-rate {win_rate:.3f} is below target {target_win_rate:.3f}"
        + (f" with {g1_losses} G1 loss(es)" if g1_losses else "")
        + "; increase race-safety pressure."
    )
    lift = shortfall * 1000.0 + g1_losses * 250.0

    max_skills = _current_lhp_value(preset, "calendar_race_prebuy_max_skills", 4)
    budget = _current_lhp_value(preset, "calendar_race_prebuy_budget", 850)
    keep_sp = _current_lhp_value(preset, "calendar_race_prebuy_keep_sp", 100)
    stamina_bonus = _current_lhp_value(preset, "stamina_priority_deficit_boost", 0.03)
    power_bonus = _current_lhp_value(preset, "power_priority_deficit_boost", 0.03)

    _append("calendar_race_prebuy_max_skills", 4, max_skills + 2, reason, lift)
    _append("calendar_race_prebuy_budget", 850, budget + 200, reason, lift)
    _append("calendar_race_prebuy_keep_sp", 100, max(0, keep_sp - 50), reason, lift)
    _append("stamina_priority_deficit_boost", 0.03, stamina_bonus + 0.04, reason, lift * 0.75)
    _append("power_priority_deficit_boost", 0.03, power_bonus + 0.04, reason, lift * 0.75)
    # Lean harder on the LEARNED race profiles: train toward the stats that
    # historically WIN these races (success cap) and away from what lost them
    # (demand cap). Without this the optimizer only chased rating via speed/wit
    # and kept losing the balanced power/stamina G1s despite high stat sums.
    success_cap = _current_lhp_value(preset, "race_success_bonus_cap", 0.10)
    demand_cap = _current_lhp_value(preset, "race_specific_demand_cap", 0.25)
    _append("race_success_bonus_cap", 0.10, success_cap + 0.06, reason, lift * 0.9)
    _append("race_specific_demand_cap", 0.25, demand_cap + 0.06, reason, lift * 0.8)
    return proposals


def analyze_batch(results: list, preset: dict | None = None) -> list[Proposal]:
    """High-level entry point. Run all enabled analyzers and concatenate
    their proposals.

    For now there's just the priority-bonus analyzer. Future modules
    (skill-buy timing, outing stat target, item usage) get added here
    as additional `propose_*` calls.
    """
    out: list[Proposal] = []
    out.extend(propose_priority_bonus_adjustments(results, preset))
    out.extend(propose_final_stat_pressure_adjustments(results, preset))
    out.extend(propose_race_reliability_adjustments(results, preset))
    return out
