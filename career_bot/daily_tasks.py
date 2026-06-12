"""Daily/event status parsing and guarded automation scaffolding.

The game exposes availability for most daily/event tasks in load/index, but
action endpoints for special modes must be captured before they are safe to
call. This module keeps the state parsing deterministic and routes optional
actions through an explicit endpoint config instead of guessing payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any


STYLE_ID_TO_LABEL = {
    1: "Front",
    2: "Pace",
    3: "Late",
    4: "End",
}

STYLE_LABEL_TO_ID = {
    "front": 1,
    "front_runner": 1,
    "nige": 1,
    "pace": 2,
    "pace_chaser": 2,
    "senko": 2,
    "late": 3,
    "late_surger": 3,
    "sashi": 3,
    "end": 4,
    "end_closer": 4,
    "oikomi": 4,
}


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except Exception:
        return default


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def normalize_style_id(value: Any) -> int:
    if isinstance(value, str):
        return STYLE_LABEL_TO_ID.get(value.strip().lower(), _safe_int(value))
    return _safe_int(value)


def style_label(value: Any) -> str:
    return STYLE_ID_TO_LABEL.get(normalize_style_id(value), "Unset")


def _pending_count(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if _safe_int(row.get("mission_status")) != 2)


def _claimable_count(rows: list[dict[str, Any]]) -> int:
    return sum(1 for row in rows if _safe_int(row.get("mission_status")) == 1)


def _difficulty_label(index: int) -> str:
    labels = {
        1: "Difficulty 1",
        2: "Difficulty 2",
        3: "Difficulty 3",
        4: "Difficulty 4",
        5: "Difficulty 5",
    }
    return labels.get(index, f"Difficulty {index}")


def showtime_difficulty_options(load_data: dict[str, Any]) -> list[dict[str, Any]]:
    options: list[dict[str, Any]] = []
    for raw in _as_list(load_data.get("single_mode_difficulty_info_array")):
        row = _as_dict(raw)
        difficulty_id = _safe_int(row.get("difficulty_id"))
        open_index = max(0, _safe_int(row.get("open_difficulty_index")))
        if difficulty_id <= 0 or open_index <= 0:
            continue
        for difficulty in range(1, open_index + 1):
            options.append(
                {
                    "difficulty_id": difficulty_id,
                    "difficulty": difficulty,
                    "label": f"{_difficulty_label(difficulty)} (ID {difficulty_id})",
                    "box_id": _safe_int(row.get("box_id")),
                    "item_num": _safe_int(row.get("item_num")),
                    "box_item_num": _safe_int(row.get("box_item_num")),
                    "open_difficulty_index": open_index,
                }
            )
    return options


def _first_unplayed_id(rows: list[dict[str, Any]], key: str) -> int:
    for row in rows:
        if not _safe_int(row.get("is_played")):
            value = _safe_int(row.get(key))
            if value > 0:
                return value
    return 0


def summarize_daily_event_status(load_data: dict[str, Any]) -> dict[str, Any]:
    common = _as_dict(load_data.get("common_define"))
    daily_info = _as_dict(load_data.get("daily_race_playing_info"))
    legend_info = _as_dict(load_data.get("legend_race_playing_info"))
    daily_legend_info = _as_dict(load_data.get("daily_legend_race_playing_info"))
    limited_shop = _as_dict(load_data.get("limited_shop_info"))
    menu_badge = _as_dict(load_data.get("menu_badge_info"))
    rp_info = _as_dict(load_data.get("rp_info"))
    team_rows = [_as_dict(row) for row in _as_list(load_data.get("team_data_array"))]
    story_missions = [_as_dict(row) for row in _as_list(load_data.get("story_event_mission_list"))]
    difficulty_options = showtime_difficulty_options(load_data)

    daily_records = [_as_dict(row) for row in _as_list(daily_info.get("daily_race_record_array"))]
    legend_records = [_as_dict(row) for row in _as_list(legend_info.get("legend_race_record_array"))]
    daily_legend_records = [_as_dict(row) for row in _as_list(daily_legend_info.get("daily_legend_race_record"))]

    team_lineup = []
    for row in team_rows:
        team_lineup.append(
            {
                "trained_chara_id": _safe_int(row.get("trained_chara_id")),
                "distance_type": _safe_int(row.get("distance_type")),
                "member_id": _safe_int(row.get("member_id")),
                "running_style": normalize_style_id(row.get("running_style")),
                "style_label": style_label(row.get("running_style")),
            }
        )

    return {
        "success": True,
        "showtime": {
            "available": bool(difficulty_options),
            "difficulty_options": difficulty_options,
            "story_event_id": _safe_int(load_data.get("story_event_id")),
            "roulette_coin_num": _safe_int(load_data.get("story_event_roulette_coin_num")),
            "missions_total": len(story_missions),
            "missions_pending": _pending_count(story_missions),
            "missions_claimable": _claimable_count(story_missions),
            "raw_difficulty_count": len(_as_list(load_data.get("single_mode_difficulty_info_array"))),
        },
        "daily_race": {
            "state": _safe_int(daily_info.get("state")),
            "trained_chara_id": _safe_int(daily_info.get("trained_chara_id")),
            "records": daily_records,
            "records_total": len(daily_records),
            "unplayed_count": sum(1 for row in daily_records if not _safe_int(row.get("is_played"))),
            "uncleared_count": sum(1 for row in daily_records if not _safe_int(row.get("is_cleared"))),
            "next_daily_race_id": _first_unplayed_id(daily_records, "daily_race_id"),
            "ticket_cap": _safe_int(common.get("daily_race_ticket_max_num")),
        },
        "legend_race": {
            "state": _safe_int(legend_info.get("state")),
            "trained_chara_id": _safe_int(legend_info.get("trained_chara_id")),
            "group_id": _safe_int(legend_info.get("group_id")),
            "next_group_id": legend_info.get("next_group_id"),
            "records": legend_records,
            "records_total": len(legend_records),
            "unplayed_count": sum(1 for row in legend_records if not _safe_int(row.get("is_played"))),
            "next_legend_race_id": _first_unplayed_id(legend_records, "legend_race_id"),
            "ticket_cap": _safe_int(common.get("legend_race_ticket_max_num")),
        },
        "daily_legend_race": {
            "state": _safe_int(daily_legend_info.get("state")),
            "trained_chara_id": _safe_int(daily_legend_info.get("trained_chara_id")),
            "new_flag": _safe_int(daily_legend_info.get("new_flag")),
            "records": daily_legend_records,
            "records_total": len(daily_legend_records),
            "unplayed_count": sum(1 for row in daily_legend_records if not _safe_int(row.get("is_played"))),
            "next_legend_race_id": _first_unplayed_id(daily_legend_records, "legend_race_id"),
            "ticket_cap": _safe_int(common.get("daily_legend_race_ticket_max_num")),
        },
        "team_trials": {
            "race_status": _safe_int(load_data.get("team_stadium_race_status")),
            "rp_current": _safe_int(rp_info.get("current_rp")),
            "rp_max": _safe_int(rp_info.get("max_rp")),
            "team_class": _safe_int(_as_dict(load_data.get("team_stadium_user")).get("team_class")),
            "best_point": _safe_int(_as_dict(load_data.get("team_stadium_user")).get("best_point")),
            "lineup": team_lineup,
            "can_race_once": _safe_int(rp_info.get("current_rp")) > 0 and len(team_lineup) >= 15,
        },
        "shops": {
            "limited_shop": {
                "limited_exchange_id": _safe_int(limited_shop.get("limited_exchange_id")),
                "open_flag": _safe_int(limited_shop.get("open_flag")),
                "appear_flag": _safe_int(limited_shop.get("appear_flag")),
                "close_time": _safe_int(limited_shop.get("close_time")),
                "open_count": _safe_int(limited_shop.get("open_count")),
                "available": bool(_safe_int(limited_shop.get("open_flag")) or _safe_int(limited_shop.get("appear_flag"))),
            },
            "configured_shop_count": 0,
        },
        "missions": {
            "normal_badge_count": _safe_int(menu_badge.get("mission_num")),
            "legend_badge_count": _safe_int(menu_badge.get("legend_mission_num")),
            "limited_badge_count": _safe_int(menu_badge.get("view_limited_mission_num")),
            "story_event": story_missions,
        },
    }


@dataclass(frozen=True)
class DailyAutomationConfig:
    path: Path
    data: dict[str, Any]

    @classmethod
    def load(cls, path: Path) -> "DailyAutomationConfig":
        if not path.exists():
            return cls(path=path, data={"schema": "sweepy_daily_automation_v1", "actions": {}})
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {"schema": "sweepy_daily_automation_v1", "actions": {}}
        if not isinstance(data, dict):
            data = {"schema": "sweepy_daily_automation_v1", "actions": {}}
        data.setdefault("schema", "sweepy_daily_automation_v1")
        data.setdefault("actions", {})
        return cls(path=path, data=data)

    def action(self, name: str) -> dict[str, Any]:
        return _as_dict(_as_dict(self.data.get("actions")).get(name))

    def configured_shop_count(self) -> int:
        shops = _as_list(self.action("daily_shops").get("shops"))
        return len(shops)


def action_config_error(action_name: str) -> str:
    return (
        f"{action_name} action endpoints are not configured yet. Capture that in-game action once "
        "with API trace logging, then add the endpoint/payload template to data/daily_automation_endpoints.json."
    )


PLACEHOLDER_RE = re.compile(r"^\{([A-Za-z0-9_.-]+)\}$")
INLINE_PLACEHOLDER_RE = re.compile(r"\{([A-Za-z0-9_.-]+)\}")


def _context_value(context: dict[str, Any], key: str) -> Any:
    current: Any = context
    for part in key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            return ""
    return current


def render_template_value(value: Any, context: dict[str, Any]) -> Any:
    """Render a JSON-safe endpoint template value.

    A string that is exactly "{trained_chara_id}" keeps the underlying value's
    type. Inline placeholders are rendered into strings. Lists/dicts recurse.
    """

    if isinstance(value, dict):
        return {str(k): render_template_value(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [render_template_value(item, context) for item in value]
    if isinstance(value, str):
        exact = PLACEHOLDER_RE.match(value)
        if exact:
            return _context_value(context, exact.group(1))
        return INLINE_PLACEHOLDER_RE.sub(lambda m: str(_context_value(context, m.group(1))), value)
    return value


def normalize_action_steps(action_cfg: dict[str, Any]) -> list[dict[str, Any]]:
    if not action_cfg:
        return []
    steps = action_cfg.get("steps")
    if isinstance(steps, list) and steps:
        return [_as_dict(step) for step in steps if isinstance(step, dict)]
    if action_cfg.get("endpoint"):
        return [action_cfg]
    return []

