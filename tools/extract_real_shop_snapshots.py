"""Extract observed MANT shop, item, and rival-race telemetry.

This complements the simulator's real training/race datasets. Career logs
contain the bot-visible shop rows, item inventory, item-use decisions, active
item effects, coin state, and rival-race IDs. The simulator can use this to
model shop value and rival race bonuses instead of relying only on an end-run
flat stat correction.

Usage:
    python -m tools.extract_real_shop_snapshots
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from career_bot.items import ITEM_NAMES


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


def as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def unwrap_items(value: Any) -> list[Any]:
    if isinstance(value, dict) and isinstance(value.get("$items"), list):
        return value.get("$items") or []
    if isinstance(value, list):
        return value
    return []


def walk_dicts(value: Any, *, max_depth: int = 8, _depth: int = 0):
    if _depth > max_depth:
        return
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk_dicts(child, max_depth=max_depth, _depth=_depth + 1)
    elif isinstance(value, list):
        for child in value:
            yield from walk_dicts(child, max_depth=max_depth, _depth=_depth + 1)


def compact_stats(row: dict[str, Any] | None) -> dict[str, int]:
    row = row or {}
    return {
        "hp": as_int(row.get("hp")),
        "max_hp": as_int(row.get("max_hp")),
        "motivation": as_int(row.get("motivation")),
        "speed": as_int(row.get("speed")),
        "stamina": as_int(row.get("stamina")),
        "power": as_int(row.get("power")),
        "guts": as_int(row.get("guts")),
        "wit": as_int(row.get("wit", row.get("wiz"))),
        "skill_point": as_int(row.get("skill_point")),
    }


def compact_shop_row(row: dict[str, Any]) -> dict[str, Any]:
    item_id = as_int(row.get("item_id"))
    return {
        "shop_item_id": as_int(row.get("shop_item_id")),
        "item_id": item_id,
        "name": row.get("name") or ITEM_NAMES.get(item_id, ""),
        "cost": as_int(row.get("cost") or row.get("coin_num")),
        "original_cost": as_int(row.get("original_cost") or row.get("original_coin_num")),
        "current_num": as_int(row.get("current_num") or row.get("item_buy_num")),
        "limit": as_int(row.get("limit") or row.get("limit_buy_count")),
        "limit_turn": as_int(row.get("limit_turn")),
        "skip_reason": row.get("skip_reason"),
    }


def compact_inventory_row(row: dict[str, Any]) -> dict[str, Any]:
    item_id = as_int(row.get("item_id"))
    return {
        "item_id": item_id,
        "name": row.get("name") or ITEM_NAMES.get(item_id, ""),
        "current_num": as_int(row.get("current_num") or row.get("num") or row.get("item_num")),
    }


def compact_item_effect(row: dict[str, Any]) -> dict[str, Any]:
    item_id = as_int(row.get("item_id"))
    return {
        "item_id": item_id,
        "name": row.get("name") or ITEM_NAMES.get(item_id, ""),
        "effect_type": as_int(row.get("effect_type")),
        "end_turn": as_int(row.get("end_turn")),
        "turn": as_int(row.get("turn")),
    }


def compact_selected(row: dict[str, Any]) -> dict[str, Any]:
    item_id = as_int(row.get("item_id"))
    return {
        "item_id": item_id,
        "name": row.get("name") or ITEM_NAMES.get(item_id, ""),
        "shop_item_id": as_int(row.get("shop_item_id")),
        "cost": as_int(row.get("cost") or row.get("coin_num")),
        "current_num": as_int(row.get("current_num") or row.get("num") or row.get("item_num")),
        "use_num": as_int(row.get("use_num") or row.get("num") or row.get("item_num"), 1),
        "reason": row.get("reason") or row.get("skip_reason"),
    }


def selected_from_attempts(rows: Any) -> list[dict[str, Any]]:
    selected = []
    for attempt in rows or []:
        if not isinstance(attempt, dict):
            continue
        for row in attempt.get("selected") or attempt.get("items") or []:
            if isinstance(row, dict):
                selected.append(compact_selected(row))
    return selected


def iter_log_files(include_legacy: bool):
    roots = [PROJECT_ROOT / "uma_runtime"]
    legacy = PROJECT_ROOT.parent / "uma_runtime"
    if include_legacy and legacy.exists() and legacy not in roots:
        roots.append(legacy)
    seen = set()
    for root in roots:
        if not root.exists():
            continue
        for pattern in ("instances/*/bot_logs/career_log_*.json", "bot_logs/career_log_*.json"):
            for path in root.glob(pattern):
                if any(part in {"ml_reference_backups", "reference_backups"} for part in path.parts):
                    continue
                resolved = str(path.resolve()).lower()
                if resolved in seen:
                    continue
                seen.add(resolved)
                yield path


def extract_file(path: Path) -> list[dict[str, Any]]:
    try:
        if path.stat().st_size > 50 * 1024 * 1024:
            return []
        root = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return []
    turns = root.get("turns") if isinstance(root, dict) else None
    if not isinstance(turns, list):
        return []

    snapshots = []
    for turn_row in turns:
        if not isinstance(turn_row, dict):
            continue
        turn = as_int(turn_row.get("turn"))
        if turn <= 0:
            continue
        shop_rows = [compact_shop_row(row) for row in turn_row.get("bot_shop_candidates") or [] if isinstance(row, dict)]
        selected_buy = [compact_selected(row) for row in turn_row.get("bot_shop_selected") or [] if isinstance(row, dict)]
        selected_use = [compact_selected(row) for row in turn_row.get("bot_item_use_selected") or [] if isinstance(row, dict)]
        selected_buy.extend(selected_from_attempts(turn_row.get("item_buy_attempts")))
        selected_use.extend(selected_from_attempts(turn_row.get("item_usage_attempts")))
        active_effects = [compact_item_effect(row) for row in turn_row.get("active_item_effects") or [] if isinstance(row, dict)]
        inventory = [compact_inventory_row(row) for row in turn_row.get("inventory") or [] if isinstance(row, dict)]
        rival_program_ids = set()
        for obj in walk_dicts(turn_row):
            if obj.get("rival") is True and as_int(obj.get("program_id")):
                rival_program_ids.add(as_int(obj.get("program_id")))
            for key in ("rival_race_info_array", "rival_info_array"):
                for row in unwrap_items(obj.get(key)):
                    if isinstance(row, dict) and as_int(row.get("program_id")):
                        rival_program_ids.add(as_int(row.get("program_id")))
            free = obj.get("free_data_set") or obj.get("free_scenario") or {}
            for row in unwrap_items(free.get("rival_race_info_array")):
                if isinstance(row, dict) and as_int(row.get("program_id")):
                    rival_program_ids.add(as_int(row.get("program_id")))
        if not any((shop_rows, selected_buy, selected_use, active_effects, inventory, rival_program_ids, turn_row.get("mant_coin"))):
            continue
        snapshots.append({
            "source": str(path),
            "run_status": root.get("status") or "",
            "preset_name": root.get("preset_name") or "",
            "turn": turn,
            "event": turn_row.get("event") or "",
            "action": turn_row.get("current_action_taken") or "",
            "mant_coin": as_int(turn_row.get("mant_coin")),
            "skill_point": as_int(turn_row.get("skill_point")),
            "stats": compact_stats(turn_row.get("stats")),
            "inventory": inventory,
            "shop_rows": shop_rows,
            "selected_buy": selected_buy,
            "selected_use": selected_use,
            "active_effects": active_effects,
            "rival_program_ids": sorted(rival_program_ids),
        })
    return snapshots


def percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    if len(values) == 1:
        return float(values[0])
    index = int(round((max(0.0, min(100.0, pct)) / 100.0) * (len(values) - 1)))
    return float(values[index])


def summarize(snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    shop_seen = Counter()
    bought = Counter()
    used = Counter()
    active = Counter()
    rival = Counter()
    coin_by_turn = defaultdict(list)
    bought_by_turn_bucket = defaultdict(Counter)
    used_by_turn_bucket = defaultdict(Counter)

    for snapshot in snapshots:
        turn = as_int(snapshot.get("turn"))
        bucket = str(((turn - 1) // 12) * 12 + 1) if turn else "0"
        coin = as_int(snapshot.get("mant_coin"))
        if coin:
            coin_by_turn[str(turn)].append(coin)
        for row in snapshot.get("shop_rows") or []:
            shop_seen[str(row.get("item_id"))] += 1
        for row in snapshot.get("selected_buy") or []:
            item_id = str(row.get("item_id"))
            bought[item_id] += 1
            bought_by_turn_bucket[bucket][item_id] += 1
        for row in snapshot.get("selected_use") or []:
            item_id = str(row.get("item_id"))
            used[item_id] += 1
            used_by_turn_bucket[bucket][item_id] += 1
        for row in snapshot.get("active_effects") or []:
            active[str(row.get("item_id"))] += 1
        for pid in snapshot.get("rival_program_ids") or []:
            rival[str(pid)] += 1

    item_ids = sorted(
        set(shop_seen) | set(bought) | set(used) | set(active),
        key=lambda value: as_int(value),
    )
    item_summary = {}
    for item_id in item_ids:
        iid = as_int(item_id)
        item_summary[item_id] = {
            "name": ITEM_NAMES.get(iid, ""),
            "shop_seen": shop_seen[item_id],
            "bought": bought[item_id],
            "used": used[item_id],
            "active_seen": active[item_id],
        }

    return {
        "snapshots": len(snapshots),
        "shop_rows": sum(len(s.get("shop_rows") or []) for s in snapshots),
        "buy_events": sum(bought.values()),
        "use_events": sum(used.values()),
        "active_effect_rows": sum(active.values()),
        "rival_programs": dict(rival.most_common(100)),
        "coin_by_turn": {
            turn: {
                "samples": len(values),
                "p25": round(percentile(values, 25), 2),
                "p50": round(percentile(values, 50), 2),
                "p75": round(percentile(values, 75), 2),
            }
            for turn, values in sorted(coin_by_turn.items(), key=lambda item: as_int(item[0]))
        },
        "item_summary": item_summary,
        "bought_by_turn_bucket": {
            bucket: dict(counter.most_common())
            for bucket, counter in sorted(bought_by_turn_bucket.items(), key=lambda item: as_int(item[0]))
        },
        "used_by_turn_bucket": {
            bucket: dict(counter.most_common())
            for bucket, counter in sorted(used_by_turn_bucket.items(), key=lambda item: as_int(item[0]))
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(DATA_DIR / "real_shop_snapshots.json"))
    parser.add_argument("--include-legacy", action="store_true", default=True)
    parser.add_argument("--no-legacy", dest="include_legacy", action="store_false")
    parser.add_argument("--max-files", type=int, default=0, help="0 means no limit")
    args = parser.parse_args()

    snapshots = []
    scanned = 0
    for path in iter_log_files(args.include_legacy):
        if args.max_files and scanned >= args.max_files:
            break
        scanned += 1
        snapshots.extend(extract_file(path))

    payload = {
        "schema": "sweepy_real_shop_snapshots_v1",
        "generated_at": int(time.time()),
        "files_scanned": scanned,
        "summary": summarize(snapshots),
        "snapshots": snapshots,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"scanned {scanned} files")
    print(f"wrote {len(snapshots)} shop snapshots -> {output}")
    print(json.dumps(payload["summary"], indent=2)[:5000])


if __name__ == "__main__":
    main()
