"""Compute the 7 baseline metrics from the user's redesign handoff Step 1.

Reads career logs from `uma_runtime/instances/<account>/bot_logs/` and the
latest learning report from `.../learning/`. Writes baseline JSON to
`validation/baselines/pre_redesign_<DATE>.json`.

Metrics computed (from claude-code-handoff-deep-audit-continuation Step 1):
  1. mean_score_last_10
  2. median_score_last_10
  3. g1_win_rate_last_10
  4. junior_friendship_rainbows_per_turn_last_10
  5. median_cards_at_80_bond_by_turn_35_last_10
  6. top_bottom_action_ratio  (from latest learning report)
  7. top_sample_score_balanced_any_deck_q_3  (from latest learning report)
  8. wrong_signed_feature_count  (Hygiene 1 floors from redesign handoff)
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean, median

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from career_bot.learning import normalize_bot_like_log


HYGIENE_1_FLOORS = {
    "lagging_stat_alignment": 0.0,
    "blue_goal_training": 0.0,
    "race_demand_pressure": 0.0,
    "rainbow_setup_pressure": 0.0,
    "first_summer_friendship_pressure": 0.02,
    "friendship_unlocked_gap": 0.02,
    "high_bond_count": 0.0,
    "rainbow_count": 0.0,
}

JUNIOR_TURNS = set(range(1, 13))
BOND_CHECKPOINT_TURN = 35
BOND_RAINBOW_THRESHOLD = 80


def _latest_n(paths, n):
    return sorted(paths, key=lambda p: p.stat().st_mtime, reverse=True)[:n]


def _load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _normalize_for_scoring(path, raw):
    """Use the project's own normalizer to compute estimate_score + race quality."""
    parent_goals = (raw.get("run_context") or {}).get("desired_parent_sparks") or {}
    try:
        return normalize_bot_like_log(path, raw, source="bot_log", parent_goals=parent_goals)
    except Exception:
        return None


def _career_score(normalized):
    if not normalized:
        return None
    score = normalized.get("score")
    if isinstance(score, (int, float)) and score > 0:
        return float(score)
    return None


def _career_g1_record(normalized):
    if not normalized:
        return 0, 0
    rq = normalized.get("race_quality") or {}
    return int(rq.get("g1_wins") or 0), int(rq.get("g1_losses") or 0)


def _selected_training(turn):
    """Return the trainings entry the bot actually picked this turn, or None."""
    cmd = (turn.get("current_command") or {})
    if cmd.get("command_type") != 1:
        return None  # not a training turn
    chosen_id = cmd.get("command_id")
    if not chosen_id:
        return None
    snapshot = turn.get("training_snapshot") or {}
    for tr in snapshot.get("trainings") or []:
        if tr.get("command_id") == chosen_id:
            return tr
    return None


def _junior_rainbow_count(career):
    """Sum rainbow_count across selected Junior-year trainings."""
    total = 0
    junior_train_turns = 0
    for turn in career.get("turns") or []:
        if turn.get("turn") not in JUNIOR_TURNS:
            continue
        selected = _selected_training(turn)
        if not selected:
            continue
        junior_train_turns += 1
        total += int(selected.get("rainbow_count") or 0)
    return total, junior_train_turns


def _bond_at_turn(career, target_turn):
    """At target_turn, return list of bond values across deck partners.

    Aggregates from the union of partners listed across all training options
    that turn. Each partner is keyed by target_id to dedupe."""
    bonds = {}
    for turn in career.get("turns") or []:
        if turn.get("turn") != target_turn:
            continue
        snapshot = turn.get("training_snapshot") or {}
        for tr in snapshot.get("trainings") or []:
            for p in tr.get("partners") or []:
                target_id = p.get("target_id")
                if target_id is None:
                    continue
                bond = int(p.get("bond") or 0)
                # Take the max in case different trainings report different values.
                bonds[target_id] = max(bonds.get(target_id, 0), bond)
        break  # one turn match is enough
    return list(bonds.values())


def _latest_full_learning_report(learning_dir):
    """Find the most recent learning report that contains a training_policy_model."""
    candidates = sorted(
        learning_dir.glob("learning_report_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        d = _load_json(path)
        if not isinstance(d, dict):
            continue
        if isinstance(d.get("training_policy_model"), dict) and d["training_policy_model"].get("feature_weights"):
            return path, d
    return None, None


def _compute(account_dir, n=10):
    bot_logs_dir = account_dir / "bot_logs"
    learning_dir = account_dir / "learning"
    careers = []
    if bot_logs_dir.exists():
        for path in _latest_n(list(bot_logs_dir.glob("career_log_*.json")), n):
            data = _load_json(path)
            if isinstance(data, dict):
                careers.append((path, data))

    scores = []
    g1_wins_total = 0
    g1_attempts_total = 0
    junior_rainbow_rates = []
    bond_counts_at_35 = []

    for path, c in careers:
        normalized = _normalize_for_scoring(path, c)
        score = _career_score(normalized)
        if score is not None:
            scores.append(score)
        g1w, g1l = _career_g1_record(normalized)
        g1_wins_total += g1w
        g1_attempts_total += g1w + g1l
        rainbows, junior_turns = _junior_rainbow_count(c)
        if junior_turns > 0:
            junior_rainbow_rates.append(rainbows / junior_turns)
        bonds = _bond_at_turn(c, BOND_CHECKPOINT_TURN)
        if bonds:
            bond_counts_at_35.append(sum(1 for b in bonds if b >= BOND_RAINBOW_THRESHOLD))

    # 5-7: from latest full learning report
    report_path, report = _latest_full_learning_report(learning_dir) if learning_dir.exists() else (None, None)

    top_bottom_ratio = None
    top_sample_deck_q_3 = None
    wrong_signed = []
    feature_count = 0
    if report:
        tpm = report.get("training_policy_model") or {}
        top_actions = tpm.get("top_action_count") or 0
        bottom_actions = tpm.get("bottom_action_count") or 0
        if top_actions > 0:
            top_bottom_ratio = round(bottom_actions / top_actions, 3)

        # Deck-q-3 top sample score
        strat = report.get("sample_stratification") or {}
        for key, entry in strat.items():
            if isinstance(entry, dict) and "deck_q=3" in str(key):
                ranges = entry.get("top_score_range")
                if isinstance(ranges, (list, tuple)) and len(ranges) >= 2:
                    top_sample_deck_q_3 = float(ranges[1])  # high end
                    break

        # Hygiene 1 sign audit
        fw = tpm.get("feature_weights") or {}
        feature_count = len(fw)
        for name, floor in HYGIENE_1_FLOORS.items():
            if name in fw and float(fw[name]) < float(floor):
                wrong_signed.append({
                    "feature": name,
                    "value": float(fw[name]),
                    "floor": float(floor),
                })

    return {
        "metrics": {
            "career_sample_count": len(careers),
            "mean_score_last_10": round(mean(scores), 2) if scores else None,
            "median_score_last_10": round(median(scores), 2) if scores else None,
            "g1_win_rate_last_10": round(g1_wins_total / g1_attempts_total, 4) if g1_attempts_total else None,
            "g1_wins_last_10": g1_wins_total,
            "g1_attempts_last_10": g1_attempts_total,
            "junior_friendship_rainbows_per_turn_last_10": round(mean(junior_rainbow_rates), 4) if junior_rainbow_rates else None,
            "median_cards_at_80_bond_by_turn_35_last_10": median(bond_counts_at_35) if bond_counts_at_35 else None,
            "top_bottom_action_ratio": top_bottom_ratio,
            "top_sample_score_balanced_any_deck_q_3": top_sample_deck_q_3,
            "wrong_signed_feature_count": len(wrong_signed),
            "feature_weights_count": feature_count,
        },
        "wrong_signed_features": wrong_signed,
        "career_log_paths_used": [str(p) for p, _ in careers],
        "learning_report_used": str(report_path) if report_path else None,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--account", default="account_b", help="Account directory under uma_runtime/instances/")
    parser.add_argument("--n", type=int, default=10, help="Number of most-recent careers to include")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--output-dir", default="validation/baselines", help="Where to write baseline JSON")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    account_dir = root / "uma_runtime" / "instances" / args.account
    if not account_dir.exists():
        print(f"ERROR: account dir not found: {account_dir}", file=sys.stderr)
        sys.exit(1)

    result = _compute(account_dir, n=args.n)
    result.update({
        "schema": "sweepy_baseline_metrics_v1",
        "account": args.account,
        "n_careers": args.n,
        "computed_at_date": date.today().isoformat(),
    })

    output_dir = root / args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    date_tag = date.today().strftime("%Y%m%d")
    output_path = output_dir / f"pre_redesign_{date_tag}.json"
    output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")

    print(f"Wrote: {output_path}")
    print()
    print("Metrics:")
    for key, value in result["metrics"].items():
        print(f"  {key}: {value}")
    if result["wrong_signed_features"]:
        print()
        print(f"Wrong-signed features ({len(result['wrong_signed_features'])}):")
        for f in result["wrong_signed_features"]:
            print(f"  {f['feature']}: {f['value']} < floor {f['floor']}")


if __name__ == "__main__":
    main()
