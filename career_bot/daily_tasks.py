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

TASK_LABELS = {
    "daily_race": "Daily Race",
    "legend_race": "Legend Race",
    "daily_legend_race": "Daily Legend Race",
}

WEATHER_LABELS = {
    1: "Sunny",
    2: "Cloudy",
    3: "Rainy",
    4: "Snowy",
}

GROUND_CONDITION_LABELS = {
    1: "Firm",
    2: "Good",
    3: "Soft",
    4: "Heavy",
}

SURFACE_LABELS = {
    1: "Turf",
    2: "Dirt",
}

DISTANCE_TYPE_LABELS = {
    1: "Sprint",
    2: "Mile",
    3: "Medium",
    4: "Long",
}

ROTATION_LABELS = {
    1: "Right",
    2: "Left",
    3: "Straight",
}

TRACK_KIND_LABELS = {
    1: "Inner",
    2: "Outer",
}

SEASON_LABELS = {
    1: "Spring",
    2: "Summer",
    3: "Fall",
    4: "Winter",
}

RACE_INFO_FIELD_SPECS = (
    ("course_prefecture", "Course prefecture", None, ("course_prefecture", "prefecture", "course", "venue", "race_track_name")),
    ("surface", "Surface", SURFACE_LABELS, ("surface", "terrain", "ground", "ground_type", "race_track_type")),
    ("distance_meters", "Distance", None, ("distance_meters", "distance", "distance_value", "race_distance")),
    ("distance_type", "Type of race", DISTANCE_TYPE_LABELS, ("distance_type", "distance_category", "distance_category_id")),
    ("rotation", "Track rotation", ROTATION_LABELS, ("rotation", "turn_direction", "direction", "left_right", "course_set")),
    ("track_kind", "Track layout", TRACK_KIND_LABELS, ("track_kind", "track_layout", "inout", "around")),
    ("season", "Season", SEASON_LABELS, ("season", "season_id")),
    ("weather", "Weather", WEATHER_LABELS, ("weather", "weather_id")),
    ("ground_condition", "Ground condition", GROUND_CONDITION_LABELS, ("ground_condition", "condition", "baba_condition")),
)

_RACE_META_BY_INSTANCE: dict[int, dict[str, Any]] | None = None


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


def _load_race_meta_by_instance() -> dict[int, dict[str, Any]]:
    global _RACE_META_BY_INSTANCE
    if _RACE_META_BY_INSTANCE is not None:
        return _RACE_META_BY_INSTANCE
    index: dict[int, dict[str, Any]] = {}
    path = Path(__file__).resolve().parents[1] / "data" / "race_map.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    for section_name in ("meta", "program"):
        for row_id, raw in _as_dict(data.get(section_name)).items():
            row = _as_dict(raw)
            instance_id = _safe_int(row.get("race_instance_id"))
            if instance_id <= 0:
                continue
            merged = dict(index.get(instance_id) or {})
            merged.update(row)
            merged.setdefault("source_section", section_name)
            merged.setdefault("source_id", _safe_int(row_id))
            index[instance_id] = merged
    _RACE_META_BY_INSTANCE = index
    return index


def _first_present(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return None


def _display_value(value: Any, enum_map: dict[int, str] | None = None, *, field_key: str = "") -> str:
    if value is None or value == "":
        return ""
    if enum_map:
        mapped = enum_map.get(_safe_int(value))
        if mapped:
            return mapped
    if field_key == "distance_meters":
        distance = _safe_int(value)
        return f"{distance}m" if distance > 0 else str(value)
    return str(value)


def _record_id(row: dict[str, Any], key: str) -> int:
    return _safe_int(row.get(key))


def _record_name(row: dict[str, Any], race_meta: dict[str, Any]) -> str:
    raw_name = _first_present(
        row,
        "name",
        "race_name",
        "legend_race_name",
        "daily_race_name",
        "opponent_name",
        "opponent_chara_name",
        "chara_name",
    )
    return str(raw_name or race_meta.get("name") or "").strip()


def _race_meta_for_record(row: dict[str, Any]) -> dict[str, Any]:
    race_instance_id = _safe_int(
        _first_present(row, "race_instance_id", "program_id", "race_program_id", "single_mode_race_program_id")
    )
    if race_instance_id <= 0:
        return {}
    return dict(_load_race_meta_by_instance().get(race_instance_id) or {})


def _record_course_info(row: dict[str, Any], race_meta: dict[str, Any]) -> list[dict[str, Any]]:
    combined = dict(race_meta)
    combined.update(row)
    info = []
    for field_key, label, enum_map, aliases in RACE_INFO_FIELD_SPECS:
        value = _first_present(combined, *aliases)
        display = _display_value(value, enum_map, field_key=field_key)
        if not display:
            continue
        info.append({"key": field_key, "label": label, "value": display, "raw": value})
    return info


def _status_label(row: dict[str, Any]) -> str:
    if _safe_int(row.get("is_played")):
        return "Played"
    if _safe_int(row.get("is_cleared")):
        return "Cleared"
    return "Unplayed"


def _enrich_race_record(row: dict[str, Any], id_key: str, fallback_prefix: str) -> dict[str, Any]:
    race_meta = _race_meta_for_record(row)
    record_id = _record_id(row, id_key)
    name = _record_name(row, race_meta)
    label = name or (f"{fallback_prefix} #{record_id}" if record_id else fallback_prefix)
    course_info = _record_course_info(row, race_meta)
    enriched = dict(row)
    enriched.update(
        {
            "record_id": record_id,
            "record_key": id_key,
            "display_name": label,
            "label": label,
            "status_label": _status_label(row),
            "played": bool(_safe_int(row.get("is_played"))),
            "cleared": bool(_safe_int(row.get("is_cleared"))),
            "course_info": course_info,
            "course_summary": " / ".join(item["value"] for item in course_info),
        }
    )
    return enriched


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

    daily_records = [
        _enrich_race_record(_as_dict(row), "daily_race_id", TASK_LABELS["daily_race"])
        for row in _as_list(daily_info.get("daily_race_record_array"))
    ]
    legend_records = [
        _enrich_race_record(_as_dict(row), "legend_race_id", TASK_LABELS["legend_race"])
        for row in _as_list(legend_info.get("legend_race_record_array"))
    ]
    daily_legend_records = [
        _enrich_race_record(_as_dict(row), "legend_race_id", TASK_LABELS["daily_legend_race"])
        for row in _as_list(daily_legend_info.get("daily_legend_race_record"))
    ]

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
            "label": TASK_LABELS["daily_race"],
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
            "label": TASK_LABELS["legend_race"],
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
            "label": TASK_LABELS["daily_legend_race"],
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
