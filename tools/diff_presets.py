"""Side-by-side diff of two presets (typically a learned preset vs its backup).

Use after a `learn_preset` pass when you want to sanity-check the proposed
changes BEFORE applying them, or to investigate suspicious regressions by
diffing the current preset against the backup of an earlier known-good
version under `data/presets/backups/`.

Example:
  python tools/diff_presets.py \\
      "data/presets/xguri parent.json" \\
      "data/presets/backups/xguri parent_20260514_134627.json"

Output focuses on the keys the auto-tuner actually adjusts. Unchanged keys
are suppressed. Large structural changes (matrix shape changes, new keys
appearing) are flagged separately as warnings — those are usually a sign
of a refactor or schema drift, not a legitimate tune.
"""

import argparse
import json
import math
import sys
from pathlib import Path


# Keys the auto-tuner is allowed to change. Anything else flagged.
TUNED_KEYS = {
    "expect_attribute",
    "stat_value_multiplier",
    "extra_weight",
    "base_score",
    "score_value",
    "rest_threshold",
    "learn_skill_threshold",
    "mant_config",
    "optional_race_max_training_score",
    "optional_race_min_value",
    "optional_race_epithet_bonus",
    "optional_race_rival_bonus",
    "optional_race_skip_if_stamina_low",
    "training_policy_model",
    "training_policy_model_enabled",
    "training_policy_model_weight",
    "training_policy_model_max_bonus",
    "training_policy_validation",
    "learning_metadata",
    "parent_farming_rules",
}


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _fmt(value, width=8):
    if value is None:
        return "None".rjust(width)
    if _is_number(value):
        return f"{value:>{width}.4g}"
    text = json.dumps(value, separators=(",", ":"))
    if len(text) > width:
        text = text[: max(0, width - 1)] + "…"
    return text.rjust(width)


def _flatten(value, prefix=""):
    """Yield (path, value) pairs for every scalar leaf in a nested dict/list."""
    if isinstance(value, dict):
        for key, sub in value.items():
            yield from _flatten(sub, f"{prefix}.{key}" if prefix else key)
    elif isinstance(value, list):
        for idx, sub in enumerate(value):
            yield from _flatten(sub, f"{prefix}[{idx}]")
    else:
        yield prefix, value


def _significant_diff(old_value, new_value):
    """Heuristic: do we surface this change? Numeric diffs under 0.001 abs
    or 0.5% relative are suppressed as noise."""
    if old_value == new_value:
        return False
    if _is_number(old_value) and _is_number(new_value):
        if math.isnan(old_value) or math.isnan(new_value):
            return True
        delta = abs(new_value - old_value)
        if delta < 0.001:
            return False
        denom = max(abs(old_value), abs(new_value), 1e-9)
        if delta / denom < 0.005:
            return False
    return True


def diff_presets(left, right, *, all_keys=False, include_metadata=False):
    left_flat = dict(_flatten(left))
    right_flat = dict(_flatten(right))
    all_paths = sorted(set(left_flat.keys()) | set(right_flat.keys()))

    changes = []
    structural_warnings = []
    untracked_changes = []

    for path in all_paths:
        old_value = left_flat.get(path)
        new_value = right_flat.get(path)
        top_key = path.split(".")[0].split("[")[0]
        if top_key not in TUNED_KEYS and not all_keys:
            if old_value != new_value and _significant_diff(old_value, new_value):
                untracked_changes.append((path, old_value, new_value))
            continue
        if top_key == "learning_metadata" and not include_metadata:
            continue
        if not _significant_diff(old_value, new_value):
            continue
        # Type changes / appearing keys = structural warning
        if old_value is None or new_value is None or type(old_value) is not type(new_value):
            structural_warnings.append((path, old_value, new_value))
        else:
            changes.append((path, old_value, new_value))

    return {
        "changes": changes,
        "structural_warnings": structural_warnings,
        "untracked_changes": untracked_changes,
    }


def print_report(result, left_path, right_path):
    print(f"LEFT  = {left_path}")
    print(f"RIGHT = {right_path}")
    print()
    changes = result["changes"]
    structural = result["structural_warnings"]
    untracked = result["untracked_changes"]
    if not changes and not structural and not untracked:
        print("No meaningful differences.")
        return
    if changes:
        print(f"=== Tuned-key changes ({len(changes)}) ===")
        print(f"{'path':<50} {'left':>14}    {'right':>14}")
        print("-" * 84)
        for path, old, new in changes:
            print(f"{path:<50} {_fmt(old, 14)} -> {_fmt(new, 14)}")
        print()
    if structural:
        print(f"=== Structural warnings ({len(structural)}) ===")
        print("Type changed, key appeared/disappeared, or null involved. Investigate:")
        for path, old, new in structural:
            print(f"  {path}: {old!r}  ->  {new!r}")
        print()
    if untracked:
        print(f"=== Untracked-key changes ({len(untracked)}) ===")
        print("These keys aren't in the auto-tuner's allow-list. Flag if unexpected:")
        for path, old, new in untracked[:30]:
            print(f"  {path}: {_fmt(old)}  ->  {_fmt(new)}")
        if len(untracked) > 30:
            print(f"  ... and {len(untracked) - 30} more")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("left", help="LEFT preset path (usually the older or backup version)")
    parser.add_argument("right", help="RIGHT preset path (usually the newer or candidate version)")
    parser.add_argument("--all", action="store_true", help="Include keys not in the auto-tuner allow-list as primary diff (default: warn only).")
    parser.add_argument("--include-metadata", action="store_true", help="Show learning_metadata changes (usually noisy timestamps).")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON instead of a human-friendly report.")
    args = parser.parse_args()

    left = _load(args.left)
    right = _load(args.right)
    result = diff_presets(left, right, all_keys=args.all, include_metadata=args.include_metadata)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return 0
    print_report(result, args.left, args.right)
    return 0


if __name__ == "__main__":
    sys.exit(main())
