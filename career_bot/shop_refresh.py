"""MANT shop refresh pool data and per-turn shop decision snapshots."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SHOP_REFRESH_POOLS_PATH = ROOT / "data" / "shop_refresh_pools.json"
SCHEDULED_REFRESH_TURNS = (12, 18, 24, 30, 36, 42, 48, 54, 60, 66, 72)


@lru_cache(maxsize=1)
def load_shop_refresh_pools(path: str | Path = SHOP_REFRESH_POOLS_PATH) -> dict[str, Any]:
    data_path = Path(path)
    if not data_path.exists():
        return {}
    try:
        data = json.loads(data_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    if data.get("schema") != "sweepy_shop_refresh_pools_v1":
        return {}
    return data


def scheduled_refresh_turn_for(turn: int) -> int | None:
    turn = int(turn or 0)
    return turn if turn in SCHEDULED_REFRESH_TURNS else None


def next_scheduled_refresh_turn(turn: int) -> int | None:
    turn = int(turn or 0)
    for refresh_turn in SCHEDULED_REFRESH_TURNS:
        if refresh_turn > turn:
            return refresh_turn
    return None


def last_scheduled_refresh_turn(turn: int) -> int | None:
    turn = int(turn or 0)
    last = None
    for refresh_turn in SCHEDULED_REFRESH_TURNS:
        if refresh_turn <= turn:
            last = refresh_turn
        else:
            break
    return last


def _coin_count(free: dict[str, Any]) -> int:
    coin_val = free.get("coin_num")
    if coin_val is None:
        coin_val = free.get("gained_coin_num")
    return int(coin_val or 0)


def _mant_cfg(preset: dict[str, Any] | None) -> dict[str, Any]:
    return dict((preset or {}).get("mant_config") or {})


def _refresh_cost(cfg: dict[str, Any], free: dict[str, Any]) -> tuple[int | None, bool]:
    for key in ("shop_refresh_cost", "mant_shop_refresh_cost", "refresh_shop_cost"):
        if cfg.get(key) is not None:
            return int(cfg.get(key) or 0), True
    for key in ("shop_refresh_coin_num", "refresh_shop_coin_num", "shop_refresh_cost"):
        if free.get(key) is not None:
            return int(free.get(key) or 0), True
    return None, False


def build_shop_decision_state(
    state: dict[str, Any],
    *,
    preset: dict[str, Any] | None = None,
    item_names: dict[int, str] | None = None,
) -> dict[str, Any]:
    """Return the shop state the policy can reason about this turn.

    This deliberately does not execute a paid refresh. The current codebase has
    no captured endpoint/payload for that command, so the action is exposed as a
    descriptor until an observed packet can wire it safely.
    """

    data = (state or {}).get("data") or {}
    free = data.get("free_data_set") or {}
    chara = data.get("chara_info") or {}
    current_turn = int(chara.get("turn") or 0)
    pools = load_shop_refresh_pools()
    scheduled_key = str(scheduled_refresh_turn_for(current_turn) or "")
    last_scheduled_key = str(last_scheduled_refresh_turn(current_turn) or "")
    scheduled_pool = (pools.get("scheduled_refreshes") or {}).get(scheduled_key) or {}
    last_scheduled_pool = (pools.get("scheduled_refreshes") or {}).get(last_scheduled_key) or {}
    scheduled_items = pools.get("scheduled") or {}

    mant_coin = _coin_count(free)
    cfg = _mant_cfg(preset)
    cost, cost_known = _refresh_cost(cfg, free)
    endpoint = str(cfg.get("shop_refresh_endpoint") or cfg.get("refresh_shop_endpoint") or "").strip()
    offers = []
    for row in free.get("pick_up_item_info_array") or []:
        item_id = int((row or {}).get("item_id") or 0)
        shop_item_id = int((row or {}).get("shop_item_id") or 0)
        item_pool = scheduled_items.get(str(item_id)) or {}
        exact_item_pool = (scheduled_pool.get("items") or {}).get(str(item_id)) or {}
        last_item_pool = (last_scheduled_pool.get("items") or {}).get(str(item_id)) or {}
        cost_value = int((row or {}).get("coin_num") or 0)
        original_cost = int((row or {}).get("original_coin_num") or cost_value)
        offers.append({
            "shop_item_id": shop_item_id,
            "item_id": item_id,
            "name": (item_names or {}).get(item_id, ""),
            "cost": cost_value,
            "original_cost": original_cost,
            "discounted": original_cost > 0 and cost_value < original_cost,
            "item_buy_num": int((row or {}).get("item_buy_num") or 0),
            "limit_buy_count": int((row or {}).get("limit_buy_count") or 0),
            "limit_turn": int((row or {}).get("limit_turn") or 0),
            "expected_scheduled_copies_this_turn": exact_item_pool.get("expected_copies"),
            "appearance_rate_this_turn": exact_item_pool.get("appearance_rate"),
            "expected_scheduled_copies_last_refresh": last_item_pool.get("expected_copies"),
            "appearance_rate_last_refresh": last_item_pool.get("appearance_rate"),
            "expected_copies_by_scheduled_turn": item_pool.get("expected_copies_by_turn") or {},
        })

    can_afford_refresh = bool(cost_known and cost is not None and mant_coin >= int(cost))
    refresh_available = bool(offers and cost_known and endpoint and can_afford_refresh)
    unavailable_reasons = []
    if not offers:
        unavailable_reasons.append("no_current_offers")
    if not cost_known:
        unavailable_reasons.append("refresh_cost_unknown")
    elif cost is not None and mant_coin < int(cost):
        unavailable_reasons.append("not_enough_mant_coin")
    if not endpoint:
        unavailable_reasons.append("refresh_endpoint_not_configured")

    return {
        "schema": "sweepy_shop_decision_state_v1",
        "turn": current_turn,
        "mant_coin": mant_coin,
        "scheduled_refresh_turn": scheduled_refresh_turn_for(current_turn),
        "last_scheduled_refresh_turn": last_scheduled_refresh_turn(current_turn),
        "next_scheduled_refresh_turn": next_scheduled_refresh_turn(current_turn),
        "scheduled_pool": {
            "turn": scheduled_pool.get("turn"),
            "samples": scheduled_pool.get("samples"),
            "avg_new_items": scheduled_pool.get("avg_new_items"),
            "items_per_refresh_distribution": scheduled_pool.get("items_per_refresh_distribution") or {},
        } if scheduled_pool else {},
        "current_offers": offers,
        "refresh_shop": {
            "action": "refresh_shop",
            "available": refresh_available,
            "safe_to_execute": refresh_available,
            "cost": cost,
            "cost_known": cost_known,
            "endpoint": endpoint,
            "unavailable_reasons": unavailable_reasons,
        },
    }
