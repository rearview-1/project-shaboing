"""Extract game-computed training command tiles from Hachimi/API snapshots.

The game already returns training gains, partner placement, failure rates, and
facility levels in `SingleModeCommandInfo`. This script distills those captured
responses into a compact dataset the simulator can sample from.

Usage:
    python -m tools.extract_real_training_snapshots
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_HACHIMI_ROOT = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\UmamusumePrettyDerby\hachimi\Career turn data"
)

COMMAND_TO_STAT = {
    101: "speed",
    105: "stamina",
    102: "power",
    103: "guts",
    106: "wit",
}

STAT_TO_TARGET_TYPE = {
    "speed": 1,
    "stamina": 2,
    "power": 3,
    "guts": 4,
    "wit": 5,
    "skill_point": 30,
    "hp": 10,
}


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


def compact_params(raw: Any) -> list[dict[str, int]]:
    params = []
    for item in unwrap_items(raw):
        if not isinstance(item, dict):
            continue
        target_type = as_int(item.get("target_type"))
        value = as_int(item.get("value"))
        if target_type:
            params.append({"target_type": target_type, "value": value})
    return params


def compact_int_array(raw: Any) -> list[int]:
    return [as_int(item) for item in unwrap_items(raw) if as_int(item)]


def support_cards_from_run_context(root: dict[str, Any]) -> list[dict[str, int]]:
    context = root.get("run_context") or {}
    cards = []
    seen = set()
    for index, row in enumerate(context.get("support_cards") or [], start=1):
        if not isinstance(row, dict):
            continue
        support_id = as_int(row.get("support_card_id") or row.get("id"))
        if support_id and support_id not in seen:
            cards.append({
                "position": index,
                "support_card_id": support_id,
                "lb": as_int(row.get("limit_break_count"), as_int(row.get("lb_level"), 0)),
            })
            seen.add(support_id)
    friend_id = as_int(context.get("friend_card_id"))
    if friend_id and friend_id not in seen:
        cards.append({
            "position": 6,
            "support_card_id": friend_id,
            "lb": as_int(context.get("friend_limit_break_count"), 4),
        })
    return cards[:6]


def find_chara_context(root: Any) -> dict[str, Any]:
    best = {}
    best_score = -1
    for obj in walk_dicts(root):
        if not isinstance(obj, dict):
            continue
        score = 0
        for key in ("single_mode_chara_id", "card_id", "turn", "scenario_id", "speed", "stamina", "power", "guts", "wiz", "vital", "skill_point"):
            if key in obj:
                score += 1
        if score > best_score and {"turn", "scenario_id", "speed", "stamina", "power", "guts", "wiz"} <= set(obj):
            best = obj
            best_score = score
    return best


def find_support_cards(root: Any) -> list[dict[str, int]]:
    cards = []
    seen = set()
    for obj in walk_dicts(root):
        if not isinstance(obj, dict) or "support_card_id" not in obj or "position" not in obj:
            continue
        support_id = as_int(obj.get("support_card_id"))
        position = as_int(obj.get("position"))
        key = (position, support_id)
        if support_id and position and key not in seen:
            cards.append({
                "position": position,
                "support_card_id": support_id,
                "lb": as_int(obj.get("limit_break_count"), 0),
            })
            seen.add(key)
    cards.sort(key=lambda item: item["position"])
    return cards[:6]


def find_bonds(root: Any) -> dict[str, int]:
    bonds = {}
    for obj in walk_dicts(root):
        if not isinstance(obj, dict) or "target_id" not in obj or "evaluation" not in obj:
            continue
        target_id = as_int(obj.get("target_id"))
        if target_id:
            bonds[str(target_id)] = max(bonds.get(str(target_id), 0), as_int(obj.get("evaluation")))
    return bonds


def find_training_levels(root: Any) -> dict[str, int]:
    levels = {}
    for obj in walk_dicts(root):
        if not isinstance(obj, dict) or "command_id" not in obj or "level" not in obj:
            continue
        command_id = as_int(obj.get("command_id"))
        if command_id in COMMAND_TO_STAT:
            levels[str(command_id)] = max(levels.get(str(command_id), 0), as_int(obj.get("level"), 1))
    return levels


def find_training_commands(root: Any, levels: dict[str, int]) -> list[dict[str, Any]]:
    commands = []
    seen = set()
    for obj in walk_dicts(root):
        if not isinstance(obj, dict):
            continue
        command_id = as_int(obj.get("command_id"))
        if command_id not in COMMAND_TO_STAT or as_int(obj.get("command_type")) != 1:
            continue
        params = compact_params(obj.get("params_inc_dec_info_array"))
        if not params:
            continue
        partners = compact_int_array(obj.get("training_partner_array"))
        tips = compact_int_array(obj.get("tips_event_partner_array"))
        key = (
            command_id,
            tuple((p["target_type"], p["value"]) for p in params),
            tuple(partners),
            tuple(tips),
            as_int(obj.get("failure_rate")),
        )
        if key in seen:
            continue
        seen.add(key)
        commands.append({
            "command_id": command_id,
            "command_type": 1,
            "stat": COMMAND_TO_STAT[command_id],
            "level": as_int(levels.get(str(command_id)), 1),
            "is_enable": as_int(obj.get("is_enable"), 1),
            "training_partner_array": partners,
            "tips_event_partner_array": tips,
            "params_inc_dec_info_array": params,
            "failure_rate": as_int(obj.get("failure_rate")),
            "partner_count": len(partners),
            "tips_count": len(tips),
            "rainbow_partner_count": sum(1 for partner in partners if 1 <= partner <= 6),
        })
    commands.sort(key=lambda item: item["command_id"])
    return commands


def compact_career_log_training_commands(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    commands = []
    for training in snapshot.get("trainings") or []:
        if not isinstance(training, dict):
            continue
        command_id = as_int(training.get("command_id"))
        stat = COMMAND_TO_STAT.get(command_id)
        if not stat:
            continue
        params = []
        stat_gain = training.get("stat_gain") or {}
        for key, target_type in STAT_TO_TARGET_TYPE.items():
            if key not in stat_gain:
                continue
            value = as_int(stat_gain.get(key))
            if target_type and value:
                params.append({"target_type": target_type, "value": value})
        if not params:
            continue
        partners = [
            as_int(row.get("target_id"))
            for row in training.get("partners") or []
            if isinstance(row, dict) and as_int(row.get("target_id"))
        ]
        tips = [
            as_int(row.get("target_id"))
            for row in training.get("partners") or []
            if isinstance(row, dict) and as_int(row.get("target_id")) and row.get("hint")
        ]
        level = as_int(training.get("facility_level"), as_int(training.get("level"), 1))
        commands.append({
            "command_id": command_id,
            "command_type": 1,
            "stat": stat,
            "level": level,
            "is_enable": 1 if training.get("enabled", True) else 0,
            "training_partner_array": partners,
            "tips_event_partner_array": tips,
            "params_inc_dec_info_array": params,
            "failure_rate": as_int(training.get("failure_rate")),
            "partner_count": as_int(training.get("partner_count"), len(partners)),
            "tips_count": len(tips),
            "rainbow_partner_count": as_int(training.get("rainbow_count")),
        })
    commands.sort(key=lambda item: item["command_id"])
    return commands


def extract_career_log_snapshots(root: dict[str, Any], path: Path) -> list[dict[str, Any]]:
    if not isinstance(root, dict) or not isinstance(root.get("turns"), list):
        return []
    cards = support_cards_from_run_context(root)
    deck_signature = "-".join(str(card["support_card_id"]) for card in cards)
    context = root.get("run_context") or {}
    snapshots = []
    for turn_row in root.get("turns") or []:
        if not isinstance(turn_row, dict):
            continue
        training_snapshot = turn_row.get("training_snapshot") or {}
        if not isinstance(training_snapshot, dict):
            continue
        commands = compact_career_log_training_commands(training_snapshot)
        if not commands:
            continue
        stats_raw = training_snapshot.get("stats") or turn_row.get("stats") or {}
        bonds = {}
        for training in training_snapshot.get("trainings") or []:
            for partner in (training or {}).get("partners") or []:
                target_id = as_int((partner or {}).get("target_id"))
                if target_id:
                    bonds[str(target_id)] = max(bonds.get(str(target_id), 0), as_int((partner or {}).get("bond")))
        snapshots.append({
            "source": str(path),
            "turn": as_int(training_snapshot.get("turn"), as_int(turn_row.get("turn"))),
            "scenario_id": as_int(root.get("scenario_id"), 4),
            "card_id": as_int(context.get("trainee_card_id")),
            "motivation": as_int(stats_raw.get("motivation"), as_int(turn_row.get("motivation"), 3)),
            "vital": as_int(stats_raw.get("hp"), as_int(stats_raw.get("vital"))),
            "max_vital": as_int(stats_raw.get("max_hp"), 100),
            "skill_point": as_int(stats_raw.get("skill_point"), as_int(turn_row.get("skill_point"))),
            "stats": {
                "speed": as_int(stats_raw.get("speed")),
                "stamina": as_int(stats_raw.get("stamina")),
                "power": as_int(stats_raw.get("power")),
                "guts": as_int(stats_raw.get("guts")),
                "wit": as_int(stats_raw.get("wit", stats_raw.get("wiz"))),
            },
            "support_cards": cards,
            "deck_signature": deck_signature,
            "bonds": bonds,
            "training_levels": {str(command["command_id"]): command["level"] for command in commands},
            "commands": commands,
        })
    return snapshots


def extract_file(path: Path) -> dict[str, Any] | None:
    try:
        root = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    career_log_rows = extract_career_log_snapshots(root, path)
    if career_log_rows:
        return {"_multiple_snapshots": career_log_rows}
    chara = find_chara_context(root)
    levels = find_training_levels(root)
    commands = find_training_commands(root, levels)
    if not chara or not commands:
        return None
    cards = find_support_cards(root)
    bonds = find_bonds(root)
    deck_signature = "-".join(str(card["support_card_id"]) for card in cards)
    return {
        "source": str(path),
        "turn": as_int(chara.get("turn")),
        "scenario_id": as_int(chara.get("scenario_id")),
        "card_id": as_int(chara.get("card_id")),
        "motivation": as_int(chara.get("motivation"), 3),
        "vital": as_int(chara.get("vital"), as_int(chara.get("hp"), 0)),
        "max_vital": as_int(chara.get("max_vital"), as_int(chara.get("max_hp"), 100)),
        "skill_point": as_int(chara.get("skill_point")),
        "stats": {
            "speed": as_int(chara.get("speed")),
            "stamina": as_int(chara.get("stamina")),
            "power": as_int(chara.get("power")),
            "guts": as_int(chara.get("guts")),
            "wit": as_int(chara.get("wiz")),
        },
        "support_cards": cards,
        "deck_signature": deck_signature,
        "bonds": bonds,
        "training_levels": levels,
        "commands": commands,
    }


def iter_candidate_files(hachimi_root: Path, include_runtime: bool):
    if hachimi_root.exists():
        yield from hachimi_root.rglob("*.json")
    if include_runtime:
        runtime = PROJECT_ROOT / "uma_runtime" / "instances"
        if runtime.exists():
            yield from runtime.glob("*/bot_logs/career_log_*.json")
            yield from runtime.glob("*/manual_career_logs/**/*.json")


def summarize(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    by_stat = {stat: {"count": 0, "values": []} for stat in COMMAND_TO_STAT.values()}
    for snap in snapshots:
        for command in snap.get("commands") or []:
            stat = command["stat"]
            by_stat[stat]["count"] += 1
            by_stat[stat]["values"].append({
                str(param["target_type"]): param["value"]
                for param in command.get("params_inc_dec_info_array") or []
            })
    return {
        "snapshots": len(snapshots),
        "commands": sum(len(s.get("commands") or []) for s in snapshots),
        "by_stat": {stat: {"count": row["count"]} for stat, row in by_stat.items()},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hachimi-root", default=str(DEFAULT_HACHIMI_ROOT))
    parser.add_argument("--output", default=str(DATA_DIR / "real_training_snapshots.json"))
    parser.add_argument("--include-runtime", action="store_true")
    parser.add_argument("--max-files", type=int, default=0, help="0 means no limit")
    parser.add_argument("--max-mb", type=float, default=40.0)
    args = parser.parse_args()

    snapshots = []
    scanned = 0
    max_bytes = int(args.max_mb * 1024 * 1024)
    for path in iter_candidate_files(Path(args.hachimi_root), args.include_runtime):
        if args.max_files and scanned >= args.max_files:
            break
        try:
            if path.stat().st_size > max_bytes:
                continue
        except OSError:
            continue
        scanned += 1
        snap = extract_file(path)
        if isinstance(snap, dict) and isinstance(snap.get("_multiple_snapshots"), list):
            snapshots.extend(snap.get("_multiple_snapshots") or [])
        elif snap:
            snapshots.append(snap)

    payload = {
        "schema": "sweepy_real_training_snapshots_v1",
        "generated_at": int(time.time()),
        "source_root": str(args.hachimi_root),
        "summary": summarize(snapshots),
        "snapshots": snapshots,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"scanned {scanned} files")
    print(f"wrote {len(snapshots)} snapshots -> {output}")
    print(json.dumps(payload["summary"], indent=2))


if __name__ == "__main__":
    main()
