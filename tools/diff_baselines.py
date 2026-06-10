"""Diff two baseline JSON files from compute_baseline_metrics.

Use to compare:
- pre-Wave-0 vs post-Wave-0 (corpus-replay, no live careers needed)
- pre-Wave-N vs post-Wave-N (after running live careers)

Shows which metrics moved toward target and which didn't, plus the
delta in concrete numbers. Designed for the validation workflow in the
handoff plan's Step 3.
"""

import argparse
import json
from pathlib import Path

# (metric_key, "lower-is-better" | "higher-is-better" | None, target_value or None)
# target = the value at which "success" is achieved per redesign Step 2.
METRIC_GOALS = {
    "mean_score_last_10": ("higher", None),
    "median_score_last_10": ("higher", None),
    "g1_win_rate_last_10": ("higher", 1.0),
    "g1_wins_last_10": ("higher", None),
    "g1_attempts_last_10": (None, None),
    "junior_friendship_rainbows_per_turn_last_10": ("higher", 0.40),
    "median_cards_at_80_bond_by_turn_35_last_10": ("higher", 5),
    "top_bottom_action_ratio": ("lower", 4.0),
    "top_sample_score_balanced_any_deck_q_3": ("higher", 17500.0),
    "wrong_signed_feature_count": ("lower", 0),
    "feature_weights_count": (None, None),
    "career_sample_count": (None, None),
}


def _fmt(value):
    if value is None:
        return "-"
    if isinstance(value, float):
        if abs(value) < 100:
            return f"{value:.3f}"
        return f"{value:,.1f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _delta_indicator(direction, before, after, target=None):
    if before is None or after is None:
        return ""
    try:
        b = float(before)
        a = float(after)
    except (TypeError, ValueError):
        return ""
    if direction == "higher":
        if a > b:
            arrow = "UP"
        elif a < b:
            arrow = "DN"
        else:
            arrow = "--"
    elif direction == "lower":
        if a < b:
            arrow = "UP"  # UP = "improvement direction" - counterintuitively a drop
        elif a > b:
            arrow = "DN"
        else:
            arrow = "--"
    else:
        return ""
    # Goal-met indicator
    if target is not None:
        if direction == "higher" and a >= target:
            arrow += " [hit]"
        elif direction == "lower" and a <= target:
            arrow += " [hit]"
    return arrow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("before", help="Pre-state baseline JSON")
    parser.add_argument("after", help="Post-state baseline JSON")
    args = parser.parse_args()

    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))

    before_m = before.get("metrics") or {}
    after_m = after.get("metrics") or {}

    print(f"Before: {args.before}")
    print(f"After:  {args.after}")
    print(f"Before account: {before.get('account')}, After account: {after.get('account')}")
    print()

    header = f"{'Metric':<55} {'Before':>14} {'After':>14}  {'Delta':<6} {'Target':>10}"
    print(header)
    print("-" * len(header))

    keys = list(METRIC_GOALS.keys())
    for key in keys:
        b = before_m.get(key)
        a = after_m.get(key)
        direction, target = METRIC_GOALS[key]
        arrow = _delta_indicator(direction, b, a, target)
        target_str = _fmt(target) if target is not None else "-"
        print(f"{key:<55} {_fmt(b):>14} {_fmt(a):>14}  {arrow:<6} {target_str:>10}")

    # Wrong-sign feature comparison
    before_violations = before.get("wrong_signed_features") or []
    after_violations = after.get("wrong_signed_features") or []
    print()
    print(f"Wrong-signed features: {len(before_violations)} -> {len(after_violations)}")
    before_names = {v.get("feature") for v in before_violations}
    after_names = {v.get("feature") for v in after_violations}
    resolved = before_names - after_names
    introduced = after_names - before_names
    if resolved:
        print(f"  Resolved: {sorted(resolved)}")
    if introduced:
        print(f"  Newly violating: {sorted(introduced)}")


if __name__ == "__main__":
    main()
