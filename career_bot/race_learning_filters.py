import json
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

APTITUDE_RANKS = {
    "G": 1,
    "F": 2,
    "E": 3,
    "D": 4,
    "C": 5,
    "B": 6,
    "A": 7,
    "S": 8,
}
OFF_LEARNING_MAX_RANK = APTITUDE_RANKS["C"]

STYLE_ID_TO_KEY = {
    1: "front",
    2: "pace",
    3: "late",
    4: "end",
}
STYLE_NAME_TO_KEY = {
    "front": "front",
    "front_runner": "front",
    "nige": "front",
    "pace": "pace",
    "pace_chaser": "pace",
    "senko": "pace",
    "late": "late",
    "late_surger": "late",
    "sashi": "late",
    "end": "end",
    "end_closer": "end",
    "oikomi": "end",
}
DISTANCE_NAME_TO_KEY = {
    "short": "sprint",
    "sprint": "sprint",
    "mile": "mile",
    "middle": "medium",
    "medium": "medium",
    "long": "long",
}
SURFACE_NAME_TO_KEY = {
    "turf": "turf",
    "grass": "turf",
    "dirt": "dirt",
}


def _safe_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


@lru_cache(maxsize=1)
def chara_aptitude_map():
    path = PROJECT_ROOT / "public" / "assets" / "data" / "chara_aptitude_map.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def aptitude_rank(value):
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    text = str(value).strip().upper()
    if not text:
        return 0
    if text.isdigit():
        return _safe_int(text)
    return APTITUDE_RANKS.get(text, 0)


def normalize_style_key(value):
    style_id = _safe_int(value)
    if style_id:
        return STYLE_ID_TO_KEY.get(style_id, "")
    text = str(value or "").strip().lower()
    return STYLE_NAME_TO_KEY.get(text, "")


def normalize_distance_key(value):
    text = str(value or "").strip().lower()
    return DISTANCE_NAME_TO_KEY.get(text, "")


def normalize_surface_key(value):
    text = str(value or "").strip().lower()
    return SURFACE_NAME_TO_KEY.get(text, "")


def sample_chara_key(sample_or_context):
    sample = sample_or_context or {}
    run_context = sample.get("run_context") if isinstance(sample.get("run_context"), dict) else sample
    candidates = [
        run_context.get("trainee_card_id"),
        run_context.get("single_mode_chara_id"),
        run_context.get("card_id"),
        run_context.get("trained_chara_id"),
        sample.get("trainee_card_id"),
        sample.get("single_mode_chara_id"),
        sample.get("card_id"),
        sample.get("trained_chara_id"),
    ]
    bot_parent_info = sample.get("bot_parent_info") if isinstance(sample.get("bot_parent_info"), dict) else {}
    candidates.extend([
        bot_parent_info.get("trainee_card_id"),
        bot_parent_info.get("single_mode_chara_id"),
        bot_parent_info.get("card_id"),
    ])
    for value in candidates:
        key = str(_safe_int(value)).strip()
        if key and key != "0":
            return key
    return ""


def sample_chara_aptitudes(sample_or_context):
    key = sample_chara_key(sample_or_context)
    if not key:
        return {}
    row = chara_aptitude_map().get(key) or {}
    aptitudes = row.get("aptitudes") if isinstance(row, dict) else {}
    return dict(aptitudes) if isinstance(aptitudes, dict) else {}


def postmortem_player_aptitudes(loss_row):
    raw = (loss_row or {}).get("player_aptitude") or {}
    if not isinstance(raw, dict):
        return {}
    return {
        "turf": raw.get("ground_turf"),
        "dirt": raw.get("ground_dirt"),
        "sprint": raw.get("distance_short"),
        "mile": raw.get("distance_mile"),
        "medium": raw.get("distance_medium"),
        "long": raw.get("distance_long"),
        "front": raw.get("running_style_front"),
        "pace": raw.get("running_style_pace"),
        "late": raw.get("running_style_late"),
        "end": raw.get("running_style_end"),
    }


def off_aptitude_dimensions_for_learning(
    race_row,
    aptitudes,
    max_safe_rank=OFF_LEARNING_MAX_RANK,
):
    if not isinstance(race_row, dict) or not isinstance(aptitudes, dict) or not aptitudes:
        return []

    out = []
    surface = normalize_surface_key(
        race_row.get("terrain")
        or race_row.get("surface")
        or race_row.get("ground")
        or ((race_row.get("race") or {}).get("terrain") if isinstance(race_row.get("race"), dict) else "")
    )
    if surface:
        rank = aptitude_rank(aptitudes.get(surface))
        if 0 < rank <= max_safe_rank:
            out.append({"axis": "surface", "key": surface, "rank": rank})

    distance = normalize_distance_key(
        race_row.get("distance")
        or ((race_row.get("race") or {}).get("distance") if isinstance(race_row.get("race"), dict) else "")
    )
    if distance:
        rank = aptitude_rank(aptitudes.get(distance))
        if 0 < rank <= max_safe_rank:
            out.append({"axis": "distance", "key": distance, "rank": rank})

    style = normalize_style_key(
        race_row.get("style")
        or race_row.get("running_style")
        or race_row.get("player_running_style")
        or ((race_row.get("race") or {}).get("style") if isinstance(race_row.get("race"), dict) else "")
    )
    if style:
        rank = aptitude_rank(aptitudes.get(style))
        if 0 < rank <= max_safe_rank:
            out.append({"axis": "style", "key": style, "rank": rank})
    return out


def race_is_off_aptitude_for_learning(race_row, aptitudes, max_safe_rank=OFF_LEARNING_MAX_RANK):
    return bool(
        off_aptitude_dimensions_for_learning(
            race_row,
            aptitudes,
            max_safe_rank=max_safe_rank,
        )
    )
