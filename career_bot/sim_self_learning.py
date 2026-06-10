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
    "calendar_race_prebuy_max_skills",
    "calendar_race_prebuy_keep_sp",
    "skill_point_drain_floor",
    # Rest / training caution
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
        proposed = current + step
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


def analyze_batch(results: list, preset: dict | None = None) -> list[Proposal]:
    """High-level entry point. Run all enabled analyzers and concatenate
    their proposals.

    For now there's just the priority-bonus analyzer. Future modules
    (skill-buy timing, outing stat target, item usage) get added here
    as additional `propose_*` calls.
    """
    out: list[Proposal] = []
    out.extend(propose_priority_bonus_adjustments(results, preset))
    return out
