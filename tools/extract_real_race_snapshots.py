"""Extract observed race data for the career simulator.

The simulator needs race outcomes that behave like the game. Bot career logs
already contain two useful kinds of data:

* pre-race snapshots paired with the final result rank
* occasional full race_start_info fields with every opponent's stats

This script compacts both into data/real_race_snapshots.json.

Usage:
    python -m tools.extract_real_race_snapshots
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


def unwrap_items(value: Any) -> list[Any]:
    if isinstance(value, dict) and isinstance(value.get("$items"), list):
        return value.get("$items") or []
    if isinstance(value, list):
        return value
    return []


def walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child)


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def stat_dict(row: dict[str, Any] | None) -> dict[str, int]:
    row = row or {}
    return {
        "speed": as_int(row.get("speed")),
        "stamina": as_int(row.get("stamina")),
        "power": as_int(row.get("power", row.get("pow"))),
        "guts": as_int(row.get("guts")),
        "wit": as_int(row.get("wit", row.get("wiz"))),
    }


def compact_skill_ids(value: Any) -> list[int]:
    ids = []
    for item in unwrap_items(value):
        if not isinstance(item, dict):
            continue
        skill_id = as_int(item.get("skill_id"))
        if skill_id:
            ids.append(skill_id)
    return ids


def compact_horse(row: dict[str, Any]) -> dict[str, Any]:
    skill_ids = compact_skill_ids(row.get("skill_array"))
    return {
        "frame_order": as_int(row.get("frame_order")),
        "viewer_id_present": bool(as_int(row.get("viewer_id")) or as_int(row.get("owner_viewer_id"))),
        "single_mode_chara_id": as_int(row.get("single_mode_chara_id")),
        "trained_chara_id": as_int(row.get("trained_chara_id")),
        "chara_id": as_int(row.get("chara_id")),
        "card_id": as_int(row.get("card_id")),
        "npc_type": as_int(row.get("npc_type")),
        "final_grade": as_int(row.get("final_grade")),
        "popularity": as_int(row.get("popularity")),
        "running_style": as_int(row.get("running_style")),
        "motivation": as_int(row.get("motivation"), 3),
        "stats": stat_dict(row),
        "aptitudes": {
            "turf": as_int(row.get("proper_ground_turf")),
            "dirt": as_int(row.get("proper_ground_dirt")),
            "sprint": as_int(row.get("proper_distance_short")),
            "mile": as_int(row.get("proper_distance_mile")),
            "medium": as_int(row.get("proper_distance_middle")),
            "long": as_int(row.get("proper_distance_long")),
            "front": as_int(row.get("proper_running_style_nige")),
            "pace": as_int(row.get("proper_running_style_senko")),
            "late": as_int(row.get("proper_running_style_sashi")),
            "end": as_int(row.get("proper_running_style_oikomi")),
        },
        "skill_count": len(skill_ids),
        "skill_ids": skill_ids[:40],
    }


def find_player_horse(horses: list[dict[str, Any]]) -> dict[str, Any] | None:
    for horse in horses:
        if as_int(horse.get("viewer_id")):
            return horse
    for horse in horses:
        if as_int(horse.get("owner_viewer_id")) and as_int(horse.get("card_id")):
            return horse
    for horse in horses:
        if as_int(horse.get("card_id")):
            return horse
    return None


def normalize_distance(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"short", "sprint"}:
        return "sprint"
    if text in {"mile", "miles"}:
        return "mile"
    if text in {"middle", "medium", "mid"}:
        return "medium"
    if text in {"long"}:
        return "long"
    return text


def normalize_style(value: Any) -> str:
    if isinstance(value, int):
        return {1: "front", 2: "pace", 3: "late", 4: "end"}.get(value, "")
    text = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    aliases = {
        "front runner": "front",
        "front": "front",
        "nige": "front",
        "pace chaser": "pace",
        "pace": "pace",
        "senko": "pace",
        "late surger": "late",
        "late": "late",
        "sashi": "late",
        "end closer": "end",
        "end": "end",
        "oikomi": "end",
    }
    return aliases.get(text, text)


def race_meta_from_event(event: dict[str, Any] | None) -> dict[str, Any]:
    race = dict((event or {}).get("race") or {})
    return {
        "program_id": as_int((event or {}).get("program_id") or race.get("program_id")),
        "race_id": as_int(race.get("race_id") or race.get("id")),
        "race_instance_id": as_int(race.get("race_instance_id")),
        "name": race.get("name") or "",
        "turn": as_int((event or {}).get("turn") or race.get("turn")),
        "grade": race.get("grade") or race.get("type") or "",
        "terrain": race.get("terrain") or "",
        "distance": normalize_distance(race.get("distance")),
        "venue": race.get("venue") or "",
        "date": race.get("date") or "",
    }


def race_meta_from_pre_event(event: dict[str, Any] | None) -> dict[str, Any]:
    event = event or {}
    race = dict(event.get("race") or event.get("entry") or {})
    return {
        "program_id": as_int(event.get("program_id") or race.get("program_id")),
        "race_id": as_int(race.get("race_id") or race.get("id")),
        "race_instance_id": as_int(race.get("race_instance_id")),
        "name": race.get("name") or "",
        "turn": as_int(event.get("turn") or race.get("turn")),
        "grade": race.get("grade") or race.get("type") or "",
        "terrain": race.get("terrain") or "",
        "distance": normalize_distance(race.get("distance")),
        "venue": race.get("venue") or "",
        "date": race.get("date") or "",
    }


def extract_pre_result_sample(
    source: Path,
    run_status: str,
    turn_row: dict[str, Any],
    pre_event: dict[str, Any],
    result_event: dict[str, Any],
) -> dict[str, Any] | None:
    stamina_check = pre_event.get("stamina_check") or {}
    raw_stats = stat_dict(stamina_check.get("raw_stats") or pre_event.get("stats"))
    if not any(raw_stats.values()):
        return None
    effective_stats = stat_dict(stamina_check.get("effective_visible_stats"))
    if not any(effective_stats.values()):
        effective_stats = raw_stats
    race = race_meta_from_event(result_event)
    if not race["program_id"]:
        race = race_meta_from_pre_event(pre_event)
    if not race["program_id"]:
        return None

    owned_skills = turn_row.get("owned_skills") or []
    skill_count = len(owned_skills) if isinstance(owned_skills, list) else 0
    if not skill_count:
        skill_count = as_int((stamina_check.get("empirical_success_viability") or {}).get("profile", {}).get("skill_count_at_race"))

    running_style = (
        normalize_style(result_event.get("running_style"))
        or normalize_style(stamina_check.get("style"))
        or normalize_style((result_event.get("style_change") or {}).get("applied_style"))
    )
    rank = as_int(result_event.get("finish_rank") or result_event.get("result_rank"))
    return {
        "source": str(source),
        "run_status": run_status,
        "turn": as_int(result_event.get("turn") or pre_event.get("turn") or turn_row.get("turn")),
        "program_id": race["program_id"],
        "race": race,
        "result_rank": rank,
        "won": bool(result_event.get("won")) if rank else False,
        "running_style": running_style,
        "motivation": as_int(pre_event.get("motivation") or raw_stats.get("motivation"), 3),
        "skill_point": as_int(pre_event.get("skill_point")),
        "skill_count": skill_count,
        "stamina_recovery_skill_count": as_int(stamina_check.get("stamina_recovery_skill_count")),
        "career_invisible_stat_bonus": as_int(stamina_check.get("career_invisible_stat_bonus")),
        "active_item_count": len(pre_event.get("active_item_effects") or []),
        "raw_stats": raw_stats,
        "effective_visible_stats": effective_stats,
        "requirements": stat_dict(stamina_check.get("requirements")),
    }


def extract_field_sample(
    source: Path,
    run_status: str,
    container: dict[str, Any],
    result_event: dict[str, Any] | None,
) -> dict[str, Any] | None:
    race_start = container.get("race_start_info") or {}
    horses = [h for h in unwrap_items(race_start.get("race_horse_data")) if isinstance(h, dict)]
    if len(horses) < 2:
        return None
    player = find_player_horse(horses)
    if not player:
        return None
    pid = as_int(race_start.get("program_id") or (result_event or {}).get("program_id"))
    if not pid:
        return None
    result_meta = race_meta_from_event(result_event)
    race = {
        "program_id": pid,
        "race_id": result_meta.get("race_id") or 0,
        "race_instance_id": result_meta.get("race_instance_id") or 0,
        "name": result_meta.get("name") or "",
        "turn": result_meta.get("turn") or as_int(container.get("current_turn")),
        "grade": result_meta.get("grade") or "",
        "terrain": result_meta.get("terrain") or "",
        "distance": result_meta.get("distance") or "",
        "venue": result_meta.get("venue") or "",
        "date": result_meta.get("date") or "",
        "weather": as_int(race_start.get("weather")),
        "ground_condition": as_int(race_start.get("ground_condition")),
    }
    player_compact = compact_horse(player)
    opponent_compact = [compact_horse(horse) for horse in horses if horse is not player]
    result_rank = as_int((result_event or {}).get("finish_rank") or (result_event or {}).get("result_rank"))
    return {
        "source": str(source),
        "run_status": run_status,
        "turn": race["turn"],
        "program_id": pid,
        "race": race,
        "result_rank": result_rank,
        "won": bool((result_event or {}).get("won")) if result_rank else None,
        "player": player_compact,
        "opponents": opponent_compact,
        "field_size": len(horses),
    }


def iter_log_files(include_legacy: bool, include_error_snapshots: bool):
    roots = [PROJECT_ROOT / "uma_runtime"]
    legacy = PROJECT_ROOT.parent / "uma_runtime"
    if include_legacy and legacy.exists() and legacy not in roots:
        roots.append(legacy)

    seen = set()
    for root in roots:
        if not root.exists():
            continue
        patterns = ["instances/*/bot_logs/career_log_*.json", "bot_logs/career_log_*.json"]
        if include_error_snapshots:
            patterns.extend(["instances/*/error_snapshots/**/*.json", "error_snapshots/**/*.json"])
        for pattern in patterns:
            for path in root.glob(pattern):
                if any(part in {"ml_reference_backups", "reference_backups", "project_zips"} for part in path.parts):
                    continue
                resolved = str(path.resolve()).lower()
                if resolved in seen:
                    continue
                seen.add(resolved)
                yield path


def extract_file(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        if path.stat().st_size > 50 * 1024 * 1024:
            return [], []
        root = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return [], []

    run_status = str(root.get("status") or "")
    result_samples = []
    field_samples = []

    turns = root.get("turns") if isinstance(root, dict) else None
    if isinstance(turns, list):
        for turn_row in turns:
            if not isinstance(turn_row, dict):
                continue
            events = [event for event in (turn_row.get("events") or []) if isinstance(event, dict)]
            pre_by_pid = {}
            for event in events:
                if event.get("event") in {"g1_pre_race", "pre_race"}:
                    meta = race_meta_from_pre_event(event)
                    if meta["program_id"]:
                        pre_by_pid[meta["program_id"]] = event
            result_by_pid = {}
            for event in events:
                if event.get("event") != "race_result":
                    continue
                pid = as_int(event.get("program_id"))
                if pid:
                    result_by_pid[pid] = event
                    pre_event = pre_by_pid.get(pid)
                    if pre_event:
                        sample = extract_pre_result_sample(path, run_status, turn_row, pre_event, event)
                        if sample:
                            result_samples.append(sample)

            containers = [turn_row.get("current_command") or {}, turn_row]
            containers.extend(events)
            for container in containers:
                if not isinstance(container, dict) or not container.get("race_start_info"):
                    continue
                pid = as_int((container.get("race_start_info") or {}).get("program_id"))
                sample = extract_field_sample(path, run_status, container, result_by_pid.get(pid))
                if sample:
                    field_samples.append(sample)
        return result_samples, field_samples

    # Error snapshots and raw response dumps can still contain race_start_info.
    result_by_pid = {}
    for obj in walk_dicts(root):
        if not isinstance(obj, dict) or obj.get("event") != "race_result":
            continue
        pid = as_int(obj.get("program_id"))
        if pid:
            result_by_pid[pid] = obj
    for obj in walk_dicts(root):
        if not isinstance(obj, dict) or not obj.get("race_start_info"):
            continue
        pid = as_int((obj.get("race_start_info") or {}).get("program_id"))
        sample = extract_field_sample(path, run_status, obj, result_by_pid.get(pid))
        if sample:
            field_samples.append(sample)
    return result_samples, field_samples


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    if len(values) == 1:
        return float(values[0])
    idx = max(0, min(len(values) - 1, int(round((pct / 100.0) * (len(values) - 1)))))
    return float(values[idx])


def summarize(result_samples: list[dict[str, Any]], field_samples: list[dict[str, Any]]) -> dict[str, Any]:
    by_program = Counter(sample["program_id"] for sample in result_samples)
    wins_by_program = Counter(sample["program_id"] for sample in result_samples if sample.get("won"))
    losses_by_program = Counter(sample["program_id"] for sample in result_samples if not sample.get("won"))
    field_by_program = Counter(sample["program_id"] for sample in field_samples)

    score_profiles = {}
    grouped: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for sample in result_samples:
        grouped[int(sample["program_id"])].append(sample)
    for pid, rows in grouped.items():
        win_sums = [sum((row.get("raw_stats") or {}).values()) for row in rows if row.get("won")]
        loss_sums = [sum((row.get("raw_stats") or {}).values()) for row in rows if not row.get("won")]
        score_profiles[str(pid)] = {
            "samples": len(rows),
            "wins": len(win_sums),
            "losses": len(loss_sums),
            "win_stat_sum_p25": round(percentile(win_sums, 25), 2),
            "win_stat_sum_p50": round(percentile(win_sums, 50), 2),
            "loss_stat_sum_p75": round(percentile(loss_sums, 75), 2),
        }

    return {
        "result_samples": len(result_samples),
        "field_samples": len(field_samples),
        "paired_field_results": sum(1 for sample in field_samples if sample.get("result_rank")),
        "programs_with_results": len(by_program),
        "programs_with_fields": len(field_by_program),
        "top_programs": [
            {
                "program_id": pid,
                "samples": count,
                "wins": wins_by_program.get(pid, 0),
                "losses": losses_by_program.get(pid, 0),
                "field_samples": field_by_program.get(pid, 0),
            }
            for pid, count in by_program.most_common(25)
        ],
        "score_profiles": score_profiles,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DATA_DIR / "real_race_snapshots.json"))
    parser.add_argument("--include-legacy", action="store_true", default=True)
    parser.add_argument("--no-legacy", dest="include_legacy", action="store_false")
    parser.add_argument("--include-error-snapshots", action="store_true", default=True)
    parser.add_argument("--no-error-snapshots", dest="include_error_snapshots", action="store_false")
    parser.add_argument("--max-files", type=int, default=0, help="0 means no limit")
    args = parser.parse_args()

    result_samples = []
    field_samples = []
    scanned = 0
    for path in iter_log_files(args.include_legacy, args.include_error_snapshots):
        if args.max_files and scanned >= args.max_files:
            break
        scanned += 1
        results, fields = extract_file(path)
        result_samples.extend(results)
        field_samples.extend(fields)

    payload = {
        "schema": "sweepy_real_race_snapshots_v1",
        "generated_at": int(time.time()),
        "files_scanned": scanned,
        "summary": summarize(result_samples, field_samples),
        "result_samples": result_samples,
        "field_samples": field_samples,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"scanned {scanned} files")
    print(f"wrote {len(result_samples)} result samples and {len(field_samples)} field samples -> {output}")
    print(json.dumps(payload["summary"], indent=2)[:5000])


if __name__ == "__main__":
    main()
