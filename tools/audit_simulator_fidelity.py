"""Compare simulator output against real finished career logs.

This is a calibration report, not a pass/fail test. Use it after changing
career_bot/career_simulator.py to see whether the simulator drifted away from
real bot careers.

Usage:
    python -m tools.audit_simulator_fidelity --n 20
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean, median


STATS = ("speed", "stamina", "power", "guts", "wit")


def _runtime_instance_from_env():
    for key in ("SWEEPY_SIM_INSTANCE_NAME", "SWEEPY_INSTANCE_NAME"):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    runtime_dir = str(os.environ.get("UMA_RUNTIME_DIR") or "").strip()
    if runtime_dir:
        path = Path(runtime_dir)
        if path.parent.name.lower() == "instances":
            return path.name
    return "account_b"


def _default_preset_path(project_root: Path, instance: str):
    candidates = []
    preset_dir = project_root / "uma_runtime" / "instances" / instance / "instance_learning" / "presets"
    if preset_dir.exists():
        candidates.extend(sorted(preset_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True))
    fallback = project_root / "uma_runtime" / "instances" / "account_b" / "instance_learning" / "presets" / "xguri parent.json"
    candidates.append(fallback)
    return next((path for path in candidates if path.exists()), fallback)


def _estimated_skill_point_cost(skill_id, name="", hint_level=0):
    try:
        skill_id = int(skill_id or 0)
    except (TypeError, ValueError):
        skill_id = 0
    try:
        hint_level = int(hint_level or 0)
    except (TypeError, ValueError):
        hint_level = 0
    name = str(name or "")
    if 0 < skill_id < 200000:
        return 0
    circle_markers = ("○", "◯", "◎", "\u25cb", "\u25ef", "Ã¢â€”â€¹", "Ã¢â€”Â¯")
    if any(marker in name for marker in circle_markers):
        base = 110
    elif skill_id >= 900000:
        base = 200
    elif skill_id % 10 >= 2:
        base = 180
    else:
        base = 120
    return max(1, int(base * (100 - min(max(hint_level, 0), 5) * 10) / 100))


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _real_log_paths(project_root: Path):
    roots = [
        project_root / "uma_runtime",
        project_root.parent / "uma_runtime",
    ]
    seen = set()
    for root in roots:
        for path in root.rglob("career_log_*.json") if root.exists() else []:
            key = str(path.resolve())
            if key in seen:
                continue
            seen.add(key)
            yield path


def _actual_skill_spend_from_turns(turns):
    snapshots = []
    for turn in turns or []:
        if not isinstance(turn, dict):
            continue
        stats = turn.get("stats") or {}
        raw = stats.get("skill_point", turn.get("skill_point"))
        if raw is None:
            continue
        snapshots.append((int(turn.get("turn") or 0), int(raw or 0)))
    if len(snapshots) < 2:
        return 0
    snapshots.sort(key=lambda row: row[0])
    spent = 0
    previous = snapshots[0][1]
    for _turn, current in snapshots[1:]:
        delta = current - previous
        if delta < 0:
            spent += -delta
        previous = current
    return max(0, int(spent))


def _event_state_skill_point(raw_state):
    state = raw_state or {}
    if not isinstance(state, dict):
        return None
    stats = state.get("stats") if isinstance(state.get("stats"), dict) else {}
    value = state.get("skill_point")
    if value is None:
        value = stats.get("skill_point")
    if value is None:
        return None
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return None


def _selected_training_snapshot_skill_point(turn):
    command = (turn or {}).get("current_command") or (turn or {}).get("command") or {}
    if not isinstance(command, dict):
        return 0
    try:
        if int(command.get("command_type") or 0) != 1:
            return 0
        command_id = int(command.get("command_id") or 0)
        command_group_id = int(command.get("command_group_id") or 0)
    except (TypeError, ValueError):
        return 0
    snapshot = (turn or {}).get("training_snapshot") or {}
    trainings = snapshot.get("trainings") or snapshot.get("command_info_array") or snapshot.get("commands") or []
    for row in trainings:
        if not isinstance(row, dict):
            continue
        try:
            row_command_id = int(row.get("command_id") or 0)
            row_group_id = int(row.get("command_group_id") or 0)
        except (TypeError, ValueError):
            continue
        if command_id and row_command_id != command_id:
            continue
        if command_group_id and row_group_id != command_group_id:
            continue
        stat_gain = row.get("stat_gain") or {}
        if isinstance(stat_gain, dict):
            try:
                return max(0, int(stat_gain.get("skill_point") or stat_gain.get("skill_pt") or 0))
            except (TypeError, ValueError):
                return 0
    return 0


def _sp_event_source_bucket(event, turn_no=0, after_race=False):
    story_id = str((event or {}).get("story_id") or "")
    try:
        event_id = int((event or {}).get("event_id") or 0)
    except (TypeError, ValueError):
        event_id = 0
    climax_story_ids = {"400004051", "400004061", "400004071"}
    climax_event_ids = {203102, 203104, 203106}
    race_reward_story_ids = {"400000035", "501020509", "501020708", "501020709"}
    race_reward_event_ids = {1011, 7004, 7005, 7006}
    if story_id in climax_story_ids or event_id in climax_event_ids:
        return "climax"
    if story_id in race_reward_story_ids or event_id in race_reward_event_ids:
        return "races"
    if int(turn_no or 0) <= 1 and story_id.startswith("501"):
        return "initial"
    if story_id.startswith(("8", "83")):
        return "support_events"
    if story_id.startswith("4"):
        return "fixed_events"
    return "general_events"


def _career_sp_source_ledger(data):
    ledger = defaultdict(int)
    for turn in data.get("turns") or []:
        if not isinstance(turn, dict):
            continue
        try:
            turn_no = int(turn.get("turn") or 0)
        except (TypeError, ValueError):
            turn_no = 0
        training_sp = _selected_training_snapshot_skill_point(turn)
        if training_sp > 0:
            ledger["training"] += training_sp
        after_race = False
        for event in turn.get("events") or []:
            if not isinstance(event, dict):
                continue
            if event.get("event") == "race_result":
                after_race = True
                continue
            if event.get("event") != "event_resolution":
                continue
            before_sp = _event_state_skill_point(event.get("state_before"))
            after_sp = _event_state_skill_point(event.get("state_after"))
            if before_sp is None or after_sp is None:
                continue
            delta = after_sp - before_sp
            if delta > 0:
                ledger[_sp_event_source_bucket(event, turn_no=turn_no, after_race=after_race)] += delta
    return dict(ledger)


def _real_finished_careers(project_root: Path):
    postmortem_losses = {}
    for root in (project_root / "uma_runtime", project_root.parent / "uma_runtime"):
        for path in root.rglob("postmortem_*.json") if root.exists() else []:
            data = _load_json(path)
            if not isinstance(data, dict):
                continue
            career_log = data.get("career_log")
            if not career_log:
                continue
            try:
                postmortem_losses[str(Path(career_log).resolve())] = len(data.get("g1_losses") or [])
            except OSError:
                postmortem_losses[str(career_log)] = len(data.get("g1_losses") or [])
    rows = []
    for path in _real_log_paths(project_root):
        data = _load_json(path)
        if not isinstance(data, dict) or data.get("status") != "finished":
            continue
        turns = [turn for turn in data.get("turns") or [] if isinstance(turn, dict) and turn.get("stats")]
        if not turns:
            continue
        last = max(turns, key=lambda turn: int(turn.get("turn") or 0))
        stats_raw = last.get("stats") or {}
        stats = {stat: int(stats_raw.get(stat) or 0) for stat in STATS}
        stat_sum = sum(stats.values())
        owned_skills = last.get("owned_skills") or []
        owned_skill_count = len(owned_skills) if isinstance(owned_skills, list) else 0
        estimated_skill_spend = sum(
            _estimated_skill_point_cost(row.get("skill_id"), row.get("name") or "", row.get("hint_level") or 0)
            for row in owned_skills
            if isinstance(row, dict)
        )
        actual_skill_spend = _actual_skill_spend_from_turns(turns)
        if actual_skill_spend > 0:
            estimated_skill_spend = actual_skill_spend
        sp_source_ledger = _career_sp_source_ledger(data)
        try:
            resolved = str(path.resolve())
        except OSError:
            resolved = str(path)
        rows.append({
            "path": str(path),
            "stat_sum": stat_sum,
            "stats": stats,
            "turns": len(turns),
            "final_sp": int(last.get("skill_point") or stats_raw.get("skill_point") or 0),
            "owned_skill_count": owned_skill_count,
            "estimated_skill_spend": estimated_skill_spend,
            "sp_source_ledger": sp_source_ledger,
            "source_sp_total": sum(max(0, int(value or 0)) for value in sp_source_ledger.values()),
            "g1_losses": postmortem_losses.get(resolved, 0),
        })
    return rows


def _summary(values):
    if not values:
        return "n=0"
    return (
        f"n={len(values)} median={int(median(values))} "
        f"mean={int(mean(values))} min={min(values)} max={max(values)}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=20, help="number of simulated careers")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--instance", default="", help="runtime instance to hydrate from, e.g. account_a/account_b")
    parser.add_argument("--preset", default="", help="preset JSON path; defaults to newest preset for --instance")
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))

    from career_bot.career_simulator import CareerSimulator, hydrate_preset_with_latest_session_context, run_sweep

    real = _real_finished_careers(project_root)
    real_sums = [row["stat_sum"] for row in real]
    real_final_sp = [row["final_sp"] for row in real if row.get("final_sp") is not None]
    real_skill_counts = [row["owned_skill_count"] for row in real if row.get("owned_skill_count") is not None]
    real_skill_spend = [row["estimated_skill_spend"] for row in real if row.get("estimated_skill_spend")]
    real_source_sp_total = [row["source_sp_total"] for row in real if row.get("source_sp_total")]
    real_g1_losses = [row["g1_losses"] for row in real if row.get("g1_losses") is not None]
    real_sp_source_keys = sorted({
        key
        for row in real
        for key in (row.get("sp_source_ledger") or {})
    })
    print("=== Real finished career logs ===")
    print(f"  Stat sum: {_summary(real_sums)}")
    print(f"  Final SP: {_summary(real_final_sp)}")
    print(f"  Owned skills: {_summary(real_skill_counts)}")
    print(f"  Skill SP spend audit only: {_summary(real_skill_spend)}")
    print(f"  Observed SP source total: {_summary(real_source_sp_total)}")
    if real_sp_source_keys:
        print("  Observed SP by source:")
        for key in real_sp_source_keys:
            values = [(row.get("sp_source_ledger") or {}).get(key, 0) for row in real]
            print(f"    {key}: {_summary(values)}")
    print(f"  G1 losses: {_summary(real_g1_losses)}")

    instance = args.instance or _runtime_instance_from_env()
    preset_path = Path(args.preset) if args.preset else _default_preset_path(project_root, instance)
    if not preset_path.exists():
        print(f"ERROR: preset not found: {preset_path}")
        return 2
    preset = _load_json(preset_path)
    if not isinstance(preset, dict):
        print(f"ERROR: preset is not valid JSON: {preset_path}")
        return 2
    if instance:
        preset["sim_runtime_instance"] = instance
    preset = hydrate_preset_with_latest_session_context(preset, project_root)
    deck = (preset.get("_run_context") or {}).get("support_cards") or None

    probe = CareerSimulator(preset=preset, deck=deck, seed=args.seed)
    print("\n=== Simulator data coverage ===")
    ctx = probe.preset.get("_run_context") or {}
    print(f"  Resolved context source: {probe.latest_session_context_source or 'preset/default'}")
    print(
        "  Resolved setup: "
        f"deck={ctx.get('deck_name') or ctx.get('deck_id') or '?'} "
        f"trainee={ctx.get('trainee_card_id') or '?'} "
        f"borrow={ctx.get('friend_card_id') or '?'}@{ctx.get('friend_viewer_id') or 0} "
        f"parents={ctx.get('parent_id_1') or '?'} / {ctx.get('parent_id_2') or '?'}"
    )
    print(f"  Real training snapshots: {len(probe.real_training_snapshots)}")
    print(f"  Exact deck snapshot matches: {probe._exact_training_snapshot_deck_matches}")
    print(f"  Real race result samples: {len(probe.real_race_result_samples)}")
    print(f"  Real race field samples: {len(probe.real_race_field_samples)}")

    sweep = run_sweep(n_runs=args.n, preset=preset, deck=deck, seed_base=args.seed)
    sim_sums = [result.stat_sum for result in sweep["results"]]
    sim_ratings = [result.rating_score for result in sweep["results"]]
    sim_losses = [sum(1 for race in result.races_run if not race.get("won")) for result in sweep["results"]]
    sim_g1_losses = [result.g1_losses for result in sweep["results"]]
    sim_events = [len(result.events_fired) for result in sweep["results"]]
    sim_final_sp = [result.final_sp for result in sweep["results"]]
    sim_skill_counts = [result.skills_bought for result in sweep["results"]]
    sim_skill_spend = [sum(row.get("discounted_cost") or 0 for row in result.purchased_skills) for result in sweep["results"]]
    sim_source_sp_total = [
        sum(max(0, int(value or 0)) for value in ((getattr(result, "sp_gain_sources", {}) or {}).values()))
        for result in sweep["results"]
    ]
    sim_skill_score = [result.skill_rating_score for result in sweep["results"]]
    sp_source_keys = sorted({
        key
        for result in sweep["results"]
        for key in (getattr(result, "sp_gain_sources", {}) or {})
    })

    print("\n=== Simulated careers ===")
    print(f"  Stat sum: {_summary(sim_sums)}")
    print(f"  Rating:   {_summary(sim_ratings)}")
    print(f"  Skill score: {_summary(sim_skill_score)}")
    print(f"  Final SP: {_summary(sim_final_sp)}")
    print(f"  Skills bought: {_summary(sim_skill_counts)}")
    print(f"  Skill SP spent: {_summary(sim_skill_spend)}")
    print(f"  SP source total: {_summary(sim_source_sp_total)}")
    print(f"  Race losses: {_summary(sim_losses)}")
    print(f"  G1 losses: {_summary(sim_g1_losses)}")
    print(f"  Events:   {_summary(sim_events)}")
    if sp_source_keys:
        print("  SP gains by source:")
        for key in sp_source_keys:
            values = [(getattr(result, "sp_gain_sources", {}) or {}).get(key, 0) for result in sweep["results"]]
            print(f"    {key}: {_summary(values)}")

    if real_sums and sim_sums:
        real_med = int(median(real_sums))
        sim_med = int(median(sim_sums))
        print("\n=== Gap ===")
        print(f"  Sim stat-sum median delta vs real: {sim_med - real_med:+d}")
        if real_final_sp and sim_final_sp:
            print(f"  Sim final-SP median delta vs real: {int(median(sim_final_sp)) - int(median(real_final_sp)):+d}")
        if real_skill_spend and sim_skill_spend:
            print(f"  Sim skill-spend median delta vs real estimate: {int(median(sim_skill_spend)) - int(median(real_skill_spend)):+d}")
        if real_source_sp_total and sim_source_sp_total:
            print(f"  Sim source-SP-total median delta vs real: {int(median(sim_source_sp_total)) - int(median(real_source_sp_total)):+d}")
            common_keys = sorted(set(real_sp_source_keys) & set(sp_source_keys))
            for key in common_keys:
                real_values = [(row.get("sp_source_ledger") or {}).get(key, 0) for row in real]
                sim_values = [(getattr(result, "sp_gain_sources", {}) or {}).get(key, 0) for result in sweep["results"]]
                print(f"  Sim {key} SP median delta vs real: {int(median(sim_values)) - int(median(real_values)):+d}")
        if real_g1_losses and sim_g1_losses:
            print(f"  Sim G1-loss median delta vs real: {int(median(sim_g1_losses)) - int(median(real_g1_losses)):+d}")

    warnings = sorted({
        warning
        for result in sweep["results"]
        for warning in getattr(result, "fidelity_warnings", [])
    })
    if warnings:
        print("\n=== Fidelity warnings ===")
        for warning in warnings:
            print(f"  - {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
