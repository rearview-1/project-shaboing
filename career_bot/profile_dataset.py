"""Public profile/career dataset ingestion from captured API traces.

The collector intentionally works from authenticated API responses the client
has already received. It does not discover or call profile endpoints itself.
"""

from __future__ import annotations

import hashlib
import json
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


DATASET_SCHEMA = "sweepy_public_career_record_v1"
DATASET_FILENAME = "public_career_records.jsonl"

STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")
STAT_ALIASES = {
    "spd": "speed",
    "speed": "speed",
    "sta": "stamina",
    "stamina": "stamina",
    "stm": "stamina",
    "pwr": "power",
    "pow": "power",
    "power": "power",
    "gut": "guts",
    "guts": "guts",
    "wiz": "wit",
    "wisdom": "wit",
    "wit": "wit",
    "int": "wit",
}

APTITUDE_FIELDS = {
    "proper_ground_turf": ("track", "turf"),
    "proper_ground_dirt": ("track", "dirt"),
    "proper_distance_short": ("distance", "sprint"),
    "proper_distance_mile": ("distance", "mile"),
    "proper_distance_middle": ("distance", "medium"),
    "proper_distance_long": ("distance", "long"),
    "proper_running_style_nige": ("style", "front"),
    "proper_running_style_senko": ("style", "pace"),
    "proper_running_style_sashi": ("style", "late"),
    "proper_running_style_oikomi": ("style", "end"),
}

APTITUDE_RANKS = {
    1: "G",
    2: "F",
    3: "E",
    4: "D",
    5: "C",
    6: "B",
    7: "A",
    8: "S",
}

STYLE_NAMES = {
    1: "front",
    2: "pace",
    3: "late",
    4: "end",
    "1": "front",
    "2": "pace",
    "3": "late",
    "4": "end",
}


def as_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def dataset_dir(runtime_root: Path) -> Path:
    return Path(runtime_root) / "profile_dataset"


def dataset_path(runtime_root: Path) -> Path:
    return dataset_dir(runtime_root) / DATASET_FILENAME


def load_json(path: Path, fallback: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return fallback


def load_name_maps(project_root: Path) -> Dict[str, Dict[str, Any]]:
    project_root = Path(project_root)
    support_map = load_json(project_root / "data" / "support_list.json", {}) or {}
    chara_map = load_json(project_root / "data" / "chara_list.json", {}) or {}
    factor_map = load_json(project_root / "data" / "factor_map.json", {}) or {}
    race_map = load_json(project_root / "data" / "race_map.json", {}) or {}
    master_map = load_json(project_root / "data" / "master_map.json", {}) or {}
    return {
        "support": support_map if isinstance(support_map, dict) else {},
        "chara": chara_map if isinstance(chara_map, dict) else {},
        "factor": factor_map if isinstance(factor_map, dict) else {},
        "race": race_map if isinstance(race_map, dict) else {},
        "master": master_map if isinstance(master_map, dict) else {},
    }


def stat_from_chara(chara: Dict[str, Any], stat: str) -> int:
    stat = STAT_ALIASES.get(str(stat or "").lower(), str(stat or "").lower())
    if stat == "power":
        return as_int(chara.get("power", chara.get("pow")))
    if stat == "wit":
        return as_int(chara.get("wit", chara.get("wiz")))
    return as_int(chara.get(stat))


def trained_chara_stats(chara: Dict[str, Any]) -> Dict[str, int]:
    return {
        "speed": stat_from_chara(chara, "speed"),
        "stamina": stat_from_chara(chara, "stamina"),
        "power": stat_from_chara(chara, "power"),
        "guts": stat_from_chara(chara, "guts"),
        "wit": stat_from_chara(chara, "wit"),
        "skill_point": as_int(chara.get("skill_point", chara.get("skill_pt"))),
        "fans": as_int(chara.get("fans")),
    }


def max_stats(chara: Dict[str, Any]) -> Dict[str, int]:
    return {
        "speed": as_int(chara.get("max_speed"), 1200),
        "stamina": as_int(chara.get("max_stamina"), 1200),
        "power": as_int(chara.get("max_power"), 1200),
        "guts": as_int(chara.get("max_guts"), 1200),
        "wit": as_int(chara.get("max_wit", chara.get("max_wiz")), 1200),
    }


def normalize_aptitudes(chara: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    result: Dict[str, Dict[str, Any]] = {"track": {}, "distance": {}, "style": {}}
    for field, (category, name) in APTITUDE_FIELDS.items():
        value = as_int(chara.get(field))
        if value:
            result[category][name] = {"value": value, "rank": APTITUDE_RANKS.get(value, str(value))}
    return result


def support_name(support_map: Dict[str, Any], support_id: int) -> Tuple[str, str, str]:
    info = support_map.get(str(support_id)) or {}
    if not isinstance(info, dict):
        return f"Support {support_id}", "", ""
    return (
        str(info.get("name") or f"Support {support_id}"),
        str(info.get("type") or ""),
        str(info.get("rarity") or ""),
    )


def normalize_support_cards(chara: Dict[str, Any], support_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    for raw in chara.get("support_card_array") or chara.get("support_card_list") or chara.get("support_cards") or []:
        if not isinstance(raw, dict):
            continue
        support_id = as_int(raw.get("support_card_id") or raw.get("id"))
        if not support_id:
            continue
        key = (as_int(raw.get("position")), support_id)
        if key in seen:
            continue
        seen.add(key)
        name, card_type, rarity = support_name(support_map, support_id)
        rows.append({
            "position": as_int(raw.get("position")),
            "support_card_id": support_id,
            "name": name,
            "type": card_type,
            "rarity": rarity,
            "limit_break_count": as_int(raw.get("limit_break_count"), -1),
            "owner_viewer_id": as_int(raw.get("owner_viewer_id")),
            "level": as_int(raw.get("level")),
            "exp": as_int(raw.get("exp")),
        })

    if not rows:
        ids = chara.get("support_card_id_array") or chara.get("support_card_id_list") or chara.get("support_card_ids") or []
        for idx, raw_id in enumerate(ids, start=1):
            support_id = as_int(raw_id)
            if not support_id:
                continue
            name, card_type, rarity = support_name(support_map, support_id)
            rows.append({
                "position": idx,
                "support_card_id": support_id,
                "name": name,
                "type": card_type,
                "rarity": rarity,
                "limit_break_count": -1,
                "owner_viewer_id": 0,
                "level": 0,
                "exp": 0,
            })
    return rows


def normalize_skills(chara: Dict[str, Any], master_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    skill_names = master_map.get("skill") if isinstance(master_map.get("skill"), dict) else {}
    rows: List[Dict[str, Any]] = []
    seen = set()
    for raw in chara.get("skill_array") or chara.get("skill_list") or chara.get("skills") or []:
        if isinstance(raw, dict):
            skill_id = as_int(raw.get("skill_id") or raw.get("id"))
            level = as_int(raw.get("level"), 1)
        else:
            skill_id = as_int(raw)
            level = 1
        if not skill_id or skill_id in seen:
            continue
        seen.add(skill_id)
        rows.append({
            "skill_id": skill_id,
            "name": str(skill_names.get(str(skill_id)) or f"Skill {skill_id}"),
            "level": level,
        })
    for raw in chara.get("skill_id_array") or chara.get("skill_id_list") or chara.get("skill_ids") or []:
        skill_id = as_int(raw)
        if not skill_id or skill_id in seen:
            continue
        seen.add(skill_id)
        rows.append({
            "skill_id": skill_id,
            "name": str(skill_names.get(str(skill_id)) or f"Skill {skill_id}"),
            "level": 1,
        })
    rows.sort(key=lambda row: (str(row.get("name") or "").lower(), row.get("skill_id") or 0))
    return rows


def normalize_factors(chara: Dict[str, Any], factor_map: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    seen = set()
    for raw in chara.get("factor_info_array") or chara.get("factor_info_list") or chara.get("factors") or []:
        if isinstance(raw, dict):
            factor_id = as_int(raw.get("factor_id") or raw.get("id"))
            level = as_int(raw.get("level"), 0)
        else:
            factor_id = as_int(raw)
            level = 0
        if not factor_id or (factor_id, level) in seen:
            continue
        seen.add((factor_id, level))
        info = factor_map.get(str(factor_id)) or {}
        if not isinstance(info, dict):
            info = {}
        stars = as_int(info.get("stars") or level or _stars_from_factor_id(factor_id))
        rows.append({
            "factor_id": factor_id,
            "name": str(info.get("name") or f"Factor {factor_id}"),
            "category": str(info.get("category") or ""),
            "level": level,
            "stars": stars,
        })
    for raw in chara.get("factor_id_array") or chara.get("factor_id_list") or chara.get("factor_ids") or []:
        factor_id = as_int(raw)
        if not factor_id or any(row.get("factor_id") == factor_id for row in rows):
            continue
        info = factor_map.get(str(factor_id)) or {}
        if not isinstance(info, dict):
            info = {}
        rows.append({
            "factor_id": factor_id,
            "name": str(info.get("name") or f"Factor {factor_id}"),
            "category": str(info.get("category") or ""),
            "level": 0,
            "stars": as_int(info.get("stars") or _stars_from_factor_id(factor_id)),
        })
    return rows


def _stars_from_factor_id(factor_id: int) -> int:
    suffix = abs(int(factor_id or 0)) % 10
    return suffix if 1 <= suffix <= 3 else 0


def _race_program_map(race_map: Dict[str, Any]) -> Dict[str, Any]:
    program = race_map.get("program")
    return program if isinstance(program, dict) else {}


def _race_meta_map(race_map: Dict[str, Any]) -> Dict[str, Any]:
    meta = race_map.get("meta")
    return meta if isinstance(meta, dict) else {}


def race_name_for_program(race_map: Dict[str, Any], program_id: int) -> str:
    program = _race_program_map(race_map).get(str(program_id)) or {}
    if isinstance(program, dict) and program.get("name"):
        return str(program.get("name"))
    for row in _race_meta_map(race_map).values():
        if isinstance(row, dict) and as_int(row.get("program_id")) == int(program_id or 0):
            return str(row.get("name") or f"Program {program_id}")
    return f"Program {program_id}" if program_id else ""


def normalize_races(chara: Dict[str, Any], root_data: Dict[str, Any], race_map: Dict[str, Any]) -> Dict[str, Any]:
    raw_history = (
        chara.get("race_history")
        or root_data.get("race_history")
        or chara.get("race_result_array")
        or chara.get("race_result_list")
        or root_data.get("race_result_array")
        or root_data.get("race_result_list")
        or []
    )
    history: List[Dict[str, Any]] = []
    for raw in raw_history:
        if not isinstance(raw, dict):
            continue
        program_id = as_int(raw.get("program_id") or raw.get("race_program_id"))
        style_raw = raw.get("running_style", raw.get("race_running_style"))
        result_rank = as_int(raw.get("result_rank") or raw.get("rank") or raw.get("result"))
        row = {
            "turn": as_int(raw.get("turn")),
            "program_id": program_id,
            "race_instance_id": as_int(raw.get("race_instance_id")),
            "race_id": as_int(raw.get("race_id")),
            "name": str(raw.get("name") or race_name_for_program(race_map, program_id)),
            "grade": str(raw.get("grade") or "").upper(),
            "result_rank": result_rank,
            "running_style": as_int(style_raw),
            "style": STYLE_NAMES.get(style_raw, STYLE_NAMES.get(str(style_raw), "")),
            "race_time": raw.get("race_time", raw.get("result_time")),
        }
        history.append(row)
    win_saddle_ids = [as_int(value) for value in (chara.get("win_saddle_id_array") or root_data.get("win_saddle_id_array") or []) if as_int(value)]
    losses = [row for row in history if as_int(row.get("result_rank")) > 1]
    return {
        "history": history,
        "win_saddle_ids": win_saddle_ids,
        "history_count": len(history),
        "loss_count": len(losses),
    }


def owner_from_context(container: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    container = container or {}
    return {
        "viewer_id": as_int(container.get("viewer_id")),
        "trainer_name": str(container.get("name") or container.get("trainer_name") or ""),
        "trainer_rank_score": as_int(container.get("rank_score")),
        "team_evaluation_point": as_int(container.get("team_evaluation_point")),
        "friend_state": as_int(container.get("friend_state")),
    }


def _record_hash(parts: Iterable[Any]) -> str:
    text = json.dumps(list(parts), sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def make_record_key(owner_viewer_id: int, trained_chara_id: int, chara: Dict[str, Any]) -> str:
    if owner_viewer_id and trained_chara_id:
        return f"viewer:{owner_viewer_id}:trained:{trained_chara_id}"
    if trained_chara_id:
        return f"trained:{trained_chara_id}"
    digest = _record_hash([
        owner_viewer_id,
        chara.get("card_id"),
        chara.get("rank_score"),
        trained_chara_stats(chara),
        chara.get("register_time"),
        chara.get("factor_id_array"),
    ])
    return f"hash:{digest}"


def detail_score(record: Dict[str, Any]) -> int:
    stats = record.get("stats") or {}
    races = record.get("races") or {}
    return (
        sum(1 for key in STAT_KEYS if as_int(stats.get(key)) > 0) * 8
        + len(record.get("support_cards") or []) * 5
        + len(record.get("skills") or []) * 3
        + len(record.get("factors") or [])
        + len(races.get("history") or []) * 4
        + (20 if as_int(record.get("rank_score")) > 0 else 0)
    )


def normalize_trained_chara_record(
    chara: Dict[str, Any],
    *,
    root_data: Optional[Dict[str, Any]] = None,
    owner: Optional[Dict[str, Any]] = None,
    source: Optional[Dict[str, Any]] = None,
    maps: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Optional[Dict[str, Any]]:
    if not isinstance(chara, dict):
        return None
    card_id = as_int(chara.get("card_id") or chara.get("chara_card_id"))
    trained_chara_id = as_int(chara.get("trained_chara_id") or chara.get("single_mode_chara_id"))
    rank_score = as_int(chara.get("rank_score") or chara.get("score") or chara.get("rating"))
    if not card_id:
        return None
    if not trained_chara_id and not rank_score and not chara.get("factor_id_array") and not chara.get("support_card_array"):
        return None

    root_data = root_data or {}
    owner = owner_from_context(owner)
    maps = maps or {}
    support_map = maps.get("support") or {}
    chara_map = maps.get("chara") or {}
    factor_map = maps.get("factor") or {}
    race_map = maps.get("race") or {}
    master_map = maps.get("master") or {}

    owner_viewer_id = as_int(chara.get("viewer_id") or owner.get("viewer_id"))
    stats = trained_chara_stats(chara)
    supports = normalize_support_cards(chara, support_map)
    skills = normalize_skills(chara, master_map)
    factors = normalize_factors(chara, factor_map)
    races = normalize_races(chara, root_data, race_map)
    record = {
        "schema": DATASET_SCHEMA,
        "record_key": make_record_key(owner_viewer_id, trained_chara_id, chara),
        "first_seen_at": now_stamp(),
        "seen_at": now_stamp(),
        "source": source or {},
        "owner": owner,
        "viewer_id": owner_viewer_id,
        "trainer_name": owner.get("trainer_name") or "",
        "trained_chara_id": trained_chara_id,
        "single_mode_chara_id": as_int(chara.get("single_mode_chara_id")),
        "card_id": card_id,
        "chara_name": str(chara_map.get(str(card_id)) or f"Chara {card_id}"),
        "rank": as_int(chara.get("rank")),
        "rank_score": rank_score,
        "rarity": as_int(chara.get("rarity")),
        "talent_level": as_int(chara.get("talent_level")),
        "register_time": str(chara.get("register_time") or ""),
        "stats": stats,
        "max_stats": max_stats(chara),
        "aptitudes": normalize_aptitudes(chara),
        "support_cards": supports,
        "support_card_ids": [row.get("support_card_id") for row in supports if row.get("support_card_id")],
        "skills": skills,
        "skill_ids": [row.get("skill_id") for row in skills if row.get("skill_id")],
        "skill_count": as_int(chara.get("skill_count")) or len(skills),
        "factors": factors,
        "factor_ids": [row.get("factor_id") for row in factors if row.get("factor_id")],
        "parents": {
            "succession_trained_chara_id_1": as_int(chara.get("succession_trained_chara_id_1")),
            "succession_trained_chara_id_2": as_int(chara.get("succession_trained_chara_id_2")),
        },
        "races": races,
        "raw_available_fields": sorted(str(key) for key in chara.keys()),
    }
    record["detail_score"] = detail_score(record)
    return record


def unwrap_response_payload(row_data: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(row_data, dict):
        return {}
    data = row_data.get("data")
    if isinstance(data, dict) and "data" in data and isinstance(data.get("data"), dict):
        return data.get("data") or {}
    if isinstance(data, dict):
        return data
    return row_data


def _looks_like_self_library(endpoint: str, path: List[str]) -> bool:
    endpoint = str(endpoint or "")
    if endpoint == "load/index":
        return True
    if endpoint.startswith("single_mode_free/"):
        return True
    return False


def extract_profile_records_from_response(
    endpoint: str,
    payload: Dict[str, Any],
    *,
    source: Optional[Dict[str, Any]] = None,
    include_self: bool = False,
    maps: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Extract public trained-character records from a response payload."""

    if not isinstance(payload, dict):
        return []
    records: List[Dict[str, Any]] = []
    seen_keys = set()
    source = dict(source or {})

    def add(chara: Dict[str, Any], root: Dict[str, Any], owner: Dict[str, Any], path: List[str], kind: str) -> None:
        if not include_self and _looks_like_self_library(endpoint, path):
            return
        src = dict(source)
        src.update({"endpoint": endpoint, "path": ".".join(path), "kind": kind})
        record = normalize_trained_chara_record(chara, root_data=root, owner=owner, source=src, maps=maps)
        if not record:
            return
        key = record.get("record_key")
        if key in seen_keys:
            return
        seen_keys.add(key)
        records.append(record)

    def walk(obj: Any, path: List[str], owner: Optional[Dict[str, Any]], root: Dict[str, Any]) -> None:
        if isinstance(obj, dict):
            current_owner = owner
            if any(key in obj for key in ("viewer_id", "name", "trainer_name", "rank_score", "team_evaluation_point")):
                current_owner = owner_from_context({**(owner or {}), **obj})

            utc = obj.get("user_trained_chara")
            if isinstance(utc, dict):
                add(utc, root, current_owner or {}, path + ["user_trained_chara"], "user_trained_chara")

            # Some profile/detail payloads expose the character directly.
            if "card_id" in obj and ("trained_chara_id" in obj or "rank_score" in obj or "factor_id_array" in obj):
                add(obj, root, current_owner or {}, path, "direct_chara")

            for key, value in obj.items():
                if key == "user_trained_chara":
                    continue
                if isinstance(value, list) and key in {
                    "trained_chara",
                    "trained_chara_array",
                    "user_trained_chara_array",
                    "succession_trained_chara_array",
                    "team_trained_chara_array",
                    "team_member_array",
                    "entry_chara_array",
                    "league_chara_array",
                }:
                    for idx, item in enumerate(value):
                        if isinstance(item, dict):
                            child_owner = current_owner
                            if any(k in item for k in ("viewer_id", "name", "trainer_name")):
                                child_owner = owner_from_context({**(current_owner or {}), **item})
                            if isinstance(item.get("user_trained_chara"), dict):
                                add(item["user_trained_chara"], root, child_owner or {}, path + [key, str(idx), "user_trained_chara"], key)
                            else:
                                add(item, root, child_owner or {}, path + [key, str(idx)], key)
                            walk(item, path + [key, str(idx)], child_owner, root)
                    continue
                walk(value, path + [str(key)], current_owner, root)
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                walk(item, path + [str(idx)], owner, root)

    walk(payload, ["data"], {}, payload)
    return records


def load_dataset(path: Path) -> Dict[str, Dict[str, Any]]:
    records: Dict[str, Dict[str, Any]] = {}
    path = Path(path)
    if not path.exists():
        return records
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                key = row.get("record_key")
                if key:
                    records[str(key)] = row
    except Exception:
        return records
    return records


def write_dataset(path: Path, records: Dict[str, Dict[str, Any]]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(records.values(), key=lambda row: (str(row.get("first_seen_at") or ""), str(row.get("record_key") or "")))
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")


def merge_records(existing: Dict[str, Dict[str, Any]], incoming: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts = {"added": 0, "updated": 0, "skipped": 0}
    for record in incoming:
        key = str(record.get("record_key") or "")
        if not key:
            counts["skipped"] += 1
            continue
        old = existing.get(key)
        if not old:
            existing[key] = record
            counts["added"] += 1
            continue
        if as_int(record.get("detail_score")) > as_int(old.get("detail_score")):
            record["first_seen_at"] = old.get("first_seen_at") or record.get("first_seen_at")
            existing[key] = record
            counts["updated"] += 1
        else:
            old["seen_at"] = record.get("seen_at") or now_stamp()
            counts["skipped"] += 1
    return counts


def trace_files(trace_dir: Path, recent_files: int = 5) -> List[Path]:
    trace_dir = Path(trace_dir)
    if not trace_dir.exists():
        return []
    try:
        recent_files = max(1, min(int(recent_files or 5), 50))
    except (TypeError, ValueError):
        recent_files = 5
    return sorted(
        [path for path in trace_dir.glob("*_payloads.jsonl") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[:recent_files]


def iter_trace_response_rows(paths: Iterable[Path]) -> Iterable[Tuple[Path, int, Dict[str, Any]]]:
    markers = ("trained_chara", "user_trained_chara", "rank_score", "support_card_array", "race_history")
    for path in paths:
        try:
            handle = Path(path).open("r", encoding="utf-8", errors="replace")
        except Exception:
            continue
        with handle:
            for line_no, line in enumerate(handle, start=1):
                if not any(marker in line for marker in markers):
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("direction") != "RES":
                    continue
                yield Path(path), line_no, row


def ingest_trace_dataset(
    project_root: Path,
    runtime_root: Path,
    *,
    recent_files: int = 5,
    limit: int = 1000,
    include_self: bool = False,
) -> Dict[str, Any]:
    project_root = Path(project_root)
    runtime_root = Path(runtime_root)
    trace_dir = runtime_root / "trace_logs" / "api_payloads"
    out_path = dataset_path(runtime_root)
    maps = load_name_maps(project_root)
    files = trace_files(trace_dir, recent_files=recent_files)
    records = load_dataset(out_path)
    removed_self = 0
    if not include_self and records:
        kept = {}
        for key, record in records.items():
            source = record.get("source") or {}
            endpoint = str(source.get("endpoint") or "")
            if endpoint == "load/index" or endpoint.startswith("single_mode_free/"):
                removed_self += 1
                continue
            kept[key] = record
        records = kept
    counts = {"added": 0, "updated": 0, "skipped": 0}
    extracted = 0
    scanned_rows = 0
    endpoints = Counter()
    try:
        limit = max(1, int(limit or 1000))
    except (TypeError, ValueError):
        limit = 1000

    for path, line_no, row in iter_trace_response_rows(files):
        scanned_rows += 1
        endpoint = str(row.get("endpoint") or "")
        endpoints[endpoint] += 1
        payload = unwrap_response_payload(row.get("data") or {})
        source = {
            "trace_file": path.name,
            "line": line_no,
            "req_id": str(row.get("req_id") or ""),
        }
        found = extract_profile_records_from_response(
            endpoint,
            payload,
            source=source,
            include_self=include_self,
            maps=maps,
        )
        if found:
            extracted += len(found)
            delta = merge_records(records, found)
            for key, value in delta.items():
                counts[key] += value
        if counts["added"] + counts["updated"] >= limit:
            break

    write_dataset(out_path, records)
    return {
        "dataset_path": str(out_path),
        "trace_dir": str(trace_dir),
        "trace_files": [path.name for path in files],
        "scanned_rows": scanned_rows,
        "extracted_records": extracted,
        "total_records": len(records),
        "endpoints": dict(endpoints.most_common()),
        "removed_self_records": removed_self,
        **counts,
    }


def record_stat_value(record: Dict[str, Any], stat: str) -> int:
    key = STAT_ALIASES.get(str(stat or "").lower(), str(stat or "").lower())
    stats = record.get("stats") or {}
    return as_int(stats.get(key))


def summarize_dataset(
    project_root: Path,
    runtime_root: Path,
    *,
    stat: str = "",
    min_value: int = 0,
    limit: int = 20,
) -> Dict[str, Any]:
    records = list(load_dataset(dataset_path(runtime_root)).values())
    stat_key = STAT_ALIASES.get(str(stat or "").lower(), str(stat or "").lower())
    try:
        min_value = max(0, int(min_value or 0))
    except (TypeError, ValueError):
        min_value = 0
    try:
        limit = max(1, min(int(limit or 20), 100))
    except (TypeError, ValueError):
        limit = 20

    filtered = records
    if stat_key in STAT_KEYS and min_value:
        filtered = [row for row in records if record_stat_value(row, stat_key) >= min_value]

    support_counter = Counter()
    support_meta: Dict[int, Dict[str, Any]] = {}
    trainee_counter = Counter()
    rank_scores = []
    for record in filtered:
        card_id = as_int(record.get("card_id"))
        if card_id:
            trainee_counter[(card_id, str(record.get("chara_name") or f"Chara {card_id}"))] += 1
        score = as_int(record.get("rank_score"))
        if score:
            rank_scores.append(score)
        for card in record.get("support_cards") or []:
            sid = as_int(card.get("support_card_id"))
            if not sid:
                continue
            support_counter[sid] += 1
            support_meta.setdefault(sid, card)

    top_supports = []
    for sid, count in support_counter.most_common(limit):
        meta = support_meta.get(sid) or {}
        top_supports.append({
            "support_card_id": sid,
            "name": meta.get("name") or f"Support {sid}",
            "type": meta.get("type") or "",
            "rarity": meta.get("rarity") or "",
            "count": count,
            "share": round(count / max(1, len(filtered)), 4),
        })

    top_trainees = [
        {"card_id": card_id, "name": name, "count": count}
        for (card_id, name), count in trainee_counter.most_common(limit)
    ]

    score_summary = {}
    if rank_scores:
        rank_scores_sorted = sorted(rank_scores)
        score_summary = {
            "min": rank_scores_sorted[0],
            "median": rank_scores_sorted[len(rank_scores_sorted) // 2],
            "max": rank_scores_sorted[-1],
            "average": round(sum(rank_scores_sorted) / len(rank_scores_sorted), 2),
        }

    return {
        "dataset_path": str(dataset_path(runtime_root)),
        "total_records": len(records),
        "filtered_records": len(filtered),
        "filter": {"stat": stat_key if stat_key in STAT_KEYS else "", "min_value": min_value},
        "top_support_cards": top_supports,
        "top_trainees": top_trainees,
        "rank_score": score_summary,
    }


def list_dataset_records(
    runtime_root: Path,
    *,
    stat: str = "",
    min_value: int = 0,
    limit: int = 100,
) -> Dict[str, Any]:
    records = list(load_dataset(dataset_path(runtime_root)).values())
    stat_key = STAT_ALIASES.get(str(stat or "").lower(), str(stat or "").lower())
    try:
        min_value = max(0, int(min_value or 0))
    except (TypeError, ValueError):
        min_value = 0
    try:
        limit = max(1, min(int(limit or 100), 500))
    except (TypeError, ValueError):
        limit = 100
    if stat_key in STAT_KEYS and min_value:
        records = [row for row in records if record_stat_value(row, stat_key) >= min_value]
    records.sort(key=lambda row: (as_int(row.get("rank_score")), as_int(row.get("detail_score"))), reverse=True)

    compact = []
    for row in records[:limit]:
        compact.append({
            "record_key": row.get("record_key"),
            "viewer_id": row.get("viewer_id"),
            "trainer_name": row.get("trainer_name"),
            "trained_chara_id": row.get("trained_chara_id"),
            "card_id": row.get("card_id"),
            "chara_name": row.get("chara_name"),
            "rank": row.get("rank"),
            "rank_score": row.get("rank_score"),
            "stats": row.get("stats") or {},
            "support_cards": row.get("support_cards") or [],
            "skill_count": row.get("skill_count"),
            "factor_count": len(row.get("factors") or []),
            "race_history_count": (row.get("races") or {}).get("history_count", 0),
            "source": row.get("source") or {},
            "detail_score": row.get("detail_score"),
        })
    return {
        "dataset_path": str(dataset_path(runtime_root)),
        "total_matching": len(records),
        "records": compact,
    }
