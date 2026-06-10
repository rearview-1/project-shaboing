"""Per-decision quality scoring for the auto-tuner.

The auto-tuner historically treats each career as one data point — top vs
bottom careers get pooled and the tune_* functions compare their action
distributions. That's coarse: a 78-turn career has ~50 training decisions,
and treating them as a uniform "this career was good" doesn't tell us
*which* of those 50 decisions were the good ones.

This module produces a per-action quality score so the same career can
contribute meaningfully different weights for its individual actions.
A high-quality training (rainbow, low failure, big stat gain) accumulates
weight toward the preset's preferences; a low-quality training (one
partner, high failure, low stat) accumulates less.

The implementation deliberately keeps the scoring formula simple and
explainable rather than fitting another model — we have ~150 careers,
and an opaque inner-loop model is exactly what we don't want at this
sample size. The coefficients are chosen so the dominant term is
`weighted_gain` (the bot's own decision score for this tile) and the
modifiers swing it by 20-50% rather than completely overwriting it.
"""


_STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")
_LONG_HORIZON_WINDOW_WEIGHTS = ((2, 0.5), (4, 0.3), (8, 0.2))


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        result = float(value)
    except (TypeError, ValueError):
        return default
    # NaN poisons every downstream computation because `max(0.0, nan)`,
    # `nan < x`, and `nan > x` all return paths that propagate the NaN
    # instead of recovering. Treating it as the default makes
    # decision_quality robust against bad logged values.
    if result != result:  # NaN check without importing math
        return default
    return result


def score_action(action):
    """Return a non-negative quality score for one training action.

    Signal A — local efficiency from the action's own features:
      - `weighted_gain` is the dominant term (the bot's own decision score)
      - `rainbow_count` adds +8 per rainbow partner (rainbow tiles really
        do produce ~30% more stat output, so they should weight more)
      - `hint_count` adds +3 per hint partner (smaller but real upside)
      - `failure_rate` subtracts 0.4× the percent (a 25% failure tile
        loses 10 from the score, comparable to one weak partner)
      - `energy_delta` only penalises when negative — losing 20 energy
        on a turn costs -4 from the quality, enough to deprioritise but
        not enough to make energy-positive trains universally win
    """
    if not isinstance(action, dict):
        return 0.0
    quality = _safe_float(action.get("weighted_gain"))
    quality += _safe_float(action.get("rainbow_count")) * 8.0
    quality += _safe_float(action.get("hint_count")) * 3.0
    quality -= _safe_float(action.get("failure_rate")) * 0.4
    energy = _safe_float(action.get("energy_delta"))
    if energy < 0:
        quality -= abs(energy) * 0.2
    return max(0.0, quality)


def score_action_against_alternatives(action, snapshot=None):
    """Signal B — quality relative to the alternatives the bot considered.

    When the action's source snapshot is available (the bot's view of all
    available tiles at that turn), Signal B is `chosen_score - second_best_score`.
    Positive = the chosen tile was clearly the best; negative = there was a
    better alternative. Without a snapshot we return 0 — the caller should
    fall back to Signal A only.
    """
    if not snapshot or not isinstance(snapshot, dict):
        return 0.0
    tiles = snapshot.get("trainings") or snapshot.get("options") or []
    scores = sorted(
        (_safe_float(tile.get("weighted_gain") or tile.get("score")) for tile in tiles if isinstance(tile, dict)),
        reverse=True,
    )
    if len(scores) < 2:
        return 0.0
    chosen = _safe_float(action.get("weighted_gain"))
    second_best = scores[1]
    return chosen - second_best


def score_action_followthrough(action):
    """Signal C — short forward follow-through from the sampled turn log.

    This is intentionally lightweight rather than pretending to be full
    credit assignment. It rewards actions that are followed by:
      - strong short-window stat progress
      - bond gain on the partners trained with
      - rainbow unlocks for those partners

    The signal is capped so it can sway close calls without overpowering the
    action's local efficiency or the immediate relative-to-alternatives view.
    """
    if not isinstance(action, dict):
        return 0.0
    windows = action.get("future_window_metrics")
    if not isinstance(windows, dict) or not windows:
        windows = {
            "4": {
                "future_total_gain": action.get("future_total_gain"),
                "future_partner_bond_gain": action.get("future_partner_bond_gain"),
                "future_rainbow_unlocks": action.get("future_rainbow_unlocks"),
                "best_training_gain_delta": action.get("future_best_training_gain_delta"),
                "selected_partner_best_training_reuse": action.get("future_selected_partner_reuse"),
            }
        }
    quality = 0.0
    for window, weight in _LONG_HORIZON_WINDOW_WEIGHTS:
        row = windows.get(str(window)) or windows.get(window)
        if not isinstance(row, dict):
            continue
        future_total_gain = _safe_float(row.get("total_gain", row.get("future_total_gain")))
        partner_bond_gain = _safe_float(row.get("partner_bond_gain", row.get("future_partner_bond_gain")))
        rainbow_unlocks = _safe_float(row.get("rainbow_unlocks", row.get("future_rainbow_unlocks")))
        best_gain_delta = _safe_float(row.get("best_training_gain_delta", row.get("future_best_training_gain_delta")))
        partner_reuse = _safe_float(row.get("selected_partner_best_training_reuse", row.get("future_selected_partner_reuse")))
        window_quality = 0.0
        if future_total_gain > 0:
            window_quality += min(10.0, future_total_gain * 0.06)
        if partner_bond_gain > 0:
            window_quality += min(4.0, partner_bond_gain * 0.14)
        if rainbow_unlocks > 0:
            window_quality += min(6.0, rainbow_unlocks * 3.5)
        if best_gain_delta > 0:
            window_quality += min(4.0, best_gain_delta * 0.05)
        if partner_reuse > 0:
            window_quality += min(3.0, partner_reuse * 1.0)
        quality += window_quality * weight
    return max(0.0, quality)


def combined_decision_quality(action, snapshot=None, signal_b_weight=0.4, signal_c_weight=0.35):
    """Combined Signal A + Signal B score.

    Signal B only contributes when a snapshot is available; without one
    the result equals Signal A plus any precomputed short-horizon
    follow-through. `signal_b_weight` controls how much the
    relative-to-alternatives signal can shift the score — defaults to
    0.4 so a 10-point margin over second-best adds 4 to the quality.
    `signal_c_weight` keeps the short-horizon credit assignment useful
    without letting noisy future outcomes dominate the local decision.
    """
    a = score_action(action)
    b = score_action_against_alternatives(action, snapshot)
    c = score_action_followthrough(action)
    return max(0.0, a + b * signal_b_weight + c * signal_c_weight)


def annotate_actions_with_quality(sample):
    """Walk a sample's actions and inject a `decision_quality` field on each.

    Idempotent — safe to re-run. Returns the sample for chaining; mutates
    the action dicts in place. Snapshot is optional per-action (under
    `training_snapshot`); when absent only Signal A contributes.
    """
    if not isinstance(sample, dict):
        return sample
    for action in sample.get("actions") or []:
        if not isinstance(action, dict):
            continue
        snapshot = action.get("training_snapshot")
        action["long_horizon_quality"] = round(score_action_followthrough(action), 4)
        action["decision_quality"] = round(combined_decision_quality(action, snapshot), 4)
    return sample


def quality_multiplier(quality, baseline=20.0, floor=0.3, ceiling=2.0):
    """Convert a raw quality score to a multiplier for weighted aggregation.

    Clamped to a sensible range so a single super-rainbow turn can't
    completely dominate the distribution, and a barely-trained turn
    still contributes some signal. Defensively coerces NaN inputs to the
    floor so a single bad log entry can't poison the entire distribution."""
    if baseline <= 0:
        return 1.0
    quality = _safe_float(quality)  # filters NaN/None
    ratio = quality / baseline
    if ratio != ratio:  # ratio is NaN (e.g., if baseline math went weird)
        return floor
    if ratio < floor:
        return floor
    if ratio > ceiling:
        return ceiling
    return ratio
