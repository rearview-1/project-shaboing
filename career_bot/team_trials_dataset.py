"""Read-only Team Trials dataset normalization for the Sweepy web UI."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from career_bot.profile_dataset import (
    APTITUDE_RANKS,
    STYLE_NAMES,
    as_int,
    load_name_maps,
    normalize_aptitudes,
    normalize_factors,
    normalize_races,
    normalize_skills,
    normalize_support_cards,
)


TEAM_TRIALS_SCHEMA = "sweepy_team_trials_dataset_v1"
TEAM_TRIALS_FILENAME = "team_trials_records.json"

DISTANCE_BY_ROUND = {
    1: "sprint",
    2: "mile",
    3: "medium",
    4: "long",
    5: "dirt",
}

RANK_LABELS = {
    1: "G",
    2: "G+",
    3: "F",
    4: "F+",
    5: "E",
    6: "E+",
    7: "D",
    8: "D+",
    9: "C",
    10: "C+",
    11: "B",
    12: "B+",
    13: "A",
    14: "A+",
    15: "S",
    16: "S+",
    17: "SS",
    18: "SS+",
    19: "UG",
    20: "UF",
    21: "UE",
    22: "UD",
}

STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")


def now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def default_source_dir() -> Path:
    env = os.environ.get("SWEEPY_TEAM_TRIALS_DIR")
    if env:
        return Path(env)
    return Path.home() / "Documents" / "Saved races" / "Team trials"


def dataset_dir(runtime_root: Path) -> Path:
    return Path(runtime_root) / "team_trials_dataset"


def dataset_path(runtime_root: Path) -> Path:
    return dataset_dir(runtime_root) / TEAM_TRIALS_FILENAME


def _load_json(path: Path, fallback: Any = None) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except Exception:
        return fallback


def _load_support_bonus_catalog(project_root: Path) -> Dict[str, Any]:
    data = _load_json(Path(project_root) / "data" / "support_card_bonuses.json", {}) or {}
    return data if isinstance(data, dict) else {}


def _write_cache(runtime_root: Path, payload: Dict[str, Any]) -> None:
    target = dataset_path(runtime_root)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _support_name(maps: Dict[str, Dict[str, Any]], support_id: int) -> str:
    row = (maps.get("support") or {}).get(str(support_id)) or {}
    if isinstance(row, dict):
        return str(row.get("name") or f"Support {support_id}")
    return f"Support {support_id}"


def _race_bonus_for_support(card: Dict[str, Any], support_bonus_catalog: Dict[str, Any]) -> Optional[int]:
    support_id = as_int(card.get("support_card_id") or card.get("id"))
    lb = as_int(card.get("limit_break_count"), -1)
    if not support_id or lb < 0:
        return None
    entry = support_bonus_catalog.get(str(support_id)) or {}
    if not isinstance(entry, dict):
        return None
    levels = entry.get("lb_levels") or []
    if not isinstance(levels, list) or not levels:
        return None
    rows = [row for row in levels if isinstance(row, dict)]
    exact = next((row for row in rows if as_int(row.get("lb"), -1) == lb), None)
    chosen = exact
    if chosen is None:
        eligible = [row for row in rows if as_int(row.get("lb"), -1) <= lb]
        chosen = sorted(eligible, key=lambda row: as_int(row.get("lb"), -1), reverse=True)[0] if eligible else None
    if chosen is None or chosen.get("race_bonus") is None:
        return None
    return as_int(chosen.get("race_bonus"))


def deck_race_bonus_summary(support_cards: List[Dict[str, Any]], support_bonus_catalog: Dict[str, Any]) -> Dict[str, Any]:
    """Compute actual deck race bonus from support card IDs + LB levels.

    Saved Team Trials exports also have a support_card_bonus field, but that is a
    match/export bonus. It is not the career deck race bonus shown in Career Info.
    """

    if not support_cards:
        return {
            "deck_race_bonus_pct": None,
            "deck_race_bonus_available": False,
            "deck_race_bonus_missing_ids": [],
        }
    total = 0
    missing: List[int] = []
    for card in support_cards:
        if not isinstance(card, dict):
            continue
        support_id = as_int(card.get("support_card_id") or card.get("id"))
        value = _race_bonus_for_support(card, support_bonus_catalog)
        if value is None:
            if support_id:
                missing.append(support_id)
            continue
        total += value
    available = not missing and total >= 0
    return {
        "deck_race_bonus_pct": total if available else None,
        "deck_race_bonus_available": available,
        "deck_race_bonus_missing_ids": sorted(set(missing)),
    }


def _chara_name(maps: Dict[str, Dict[str, Any]], card_id: int) -> str:
    return str((maps.get("chara") or {}).get(str(card_id)) or f"Chara {card_id}")


def _skill_rows(raw: Dict[str, Any], maps: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    return normalize_skills(raw, maps.get("master") or {})


def _parent_nodes(raw: Dict[str, Any], maps: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    factor_map = maps.get("factor") or {}
    for node in raw.get("succession_chara_array") or raw.get("parents") or []:
        if not isinstance(node, dict):
            continue
        card_id = as_int(node.get("card_id") or node.get("chara_card_id"))
        rank = as_int(node.get("rank") or node.get("chara_grade"))
        rows.append({
            "position_id": as_int(node.get("position_id") or node.get("position")),
            "card_id": card_id,
            "name": _chara_name(maps, card_id) if card_id else "Unknown",
            "rank": rank,
            "rank_label": RANK_LABELS.get(rank, str(rank) if rank else ""),
            "rarity": as_int(node.get("rarity")),
            "talent_level": as_int(node.get("talent_level")),
            "factors": normalize_factors(node, factor_map),
            "win_saddle_ids": [as_int(v) for v in (node.get("win_saddle_id_array") or []) if as_int(v)],
        })
    return rows


def _prepare_detail_source(raw: Dict[str, Any]) -> Dict[str, Any]:
    detail = dict(raw or {})
    if "support_card_array" not in detail and isinstance(detail.get("support_card_list"), list):
        detail["support_card_array"] = detail.get("support_card_list")
    if "race_result_array" not in detail and isinstance(detail.get("race_result_list"), list):
        detail["race_result_array"] = detail.get("race_result_list")
    if "power" not in detail and "pow" in detail:
        detail["power"] = detail.get("pow")
    if "wit" not in detail and "wiz" in detail:
        detail["wit"] = detail.get("wiz")
    return detail


def _detail_by_trained_id(source_dir: Path) -> Dict[int, Dict[str, Any]]:
    vets_path = Path(source_dir).parent / "veterans.json"
    rows = _load_json(vets_path, []) or []
    result: Dict[int, Dict[str, Any]] = {}
    if not isinstance(rows, list):
        return result
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        trained_id = as_int(raw.get("trained_chara_id") or raw.get("single_mode_chara_id"))
        if trained_id:
            result[trained_id] = raw
    return result


def _trainer_id(raw: Dict[str, Any], team_meta: Optional[Dict[str, Any]] = None) -> int:
    team_meta = team_meta or {}
    for key in (
        "viewer_id",
        "trainer_id",
        "owner_viewer_id",
        "owner_trainer_id",
        "user_id",
        "opponent_viewer_id",
    ):
        value = as_int(raw.get(key) or team_meta.get(key))
        if value:
            return value
    return 0


def _team_rating(raw: Dict[str, Any], team_meta: Optional[Dict[str, Any]] = None) -> int:
    team_meta = team_meta or {}
    for key in (
        "team_rank_rating",
        "team_evaluation_point",
        "evaluation_point",
        "rank_score",
        "score",
        "rating",
    ):
        value = as_int(raw.get(key) or team_meta.get(key))
        if value:
            return value
    return 0


def _team_class(raw: Dict[str, Any], team_meta: Optional[Dict[str, Any]] = None) -> int:
    team_meta = team_meta or {}
    for key in ("class", "team_class", "rank_class", "team_stadium_class"):
        value = as_int(raw.get(key) or team_meta.get(key))
        if value:
            return value
    return 0


def _stats_from_horse(raw: Dict[str, Any]) -> Dict[str, int]:
    return {
        "speed": as_int(raw.get("speed")),
        "stamina": as_int(raw.get("stamina")),
        "power": as_int(raw.get("power", raw.get("pow"))),
        "guts": as_int(raw.get("guts")),
        "wit": as_int(raw.get("wit", raw.get("wiz"))),
    }


def _normalize_character(
    horse: Dict[str, Any],
    *,
    detail_source: Optional[Dict[str, Any]],
    maps: Dict[str, Dict[str, Any]],
    file_name: str,
    distance: str,
    round_no: int,
    race_instance_id: int,
    support_bonus_raw: int,
    support_bonus_catalog: Dict[str, Any],
    source_mtime: float,
) -> Dict[str, Any]:
    detail = _prepare_detail_source(detail_source or {})
    base = dict(detail)
    base.update({
        "card_id": as_int(horse.get("card_id") or detail.get("card_id")),
        "trained_chara_id": as_int(horse.get("trained_chara_id") or horse.get("single_mode_chara_id") or detail.get("trained_chara_id")),
        "skill_array": horse.get("skill_array") or detail.get("skill_array") or [],
        "speed": horse.get("speed", detail.get("speed")),
        "stamina": horse.get("stamina", detail.get("stamina")),
        "pow": horse.get("pow", detail.get("pow", detail.get("power"))),
        "guts": horse.get("guts", detail.get("guts")),
        "wiz": horse.get("wiz", detail.get("wiz", detail.get("wit"))),
    })

    card_id = as_int(base.get("card_id"))
    trained_id = as_int(base.get("trained_chara_id") or base.get("single_mode_chara_id"))
    final_grade = as_int(horse.get("final_grade") or detail.get("rank") or detail.get("chara_grade"))
    stats = _stats_from_horse(base)
    support_cards = normalize_support_cards(base, maps.get("support") or {})
    deck_rb = deck_race_bonus_summary(support_cards, support_bonus_catalog)
    races = normalize_races(base, base, maps.get("race") or {})
    parents = _parent_nodes(base, maps)
    running_style_raw = horse.get("running_style", detail.get("running_style"))
    running_style = as_int(running_style_raw)
    name = str(horse.get("name") or detail.get("name") or _chara_name(maps, card_id))
    if name and name.strip().isdigit():
        name = _chara_name(maps, card_id)

    return {
        "key": f"{file_name}:{round_no}:{as_int(horse.get('team_id'))}:{as_int(horse.get('team_member_id'))}:{trained_id}:{card_id}",
        "source_file": file_name,
        "source_mtime": source_mtime,
        "round": round_no,
        "distance": distance,
        "race_instance_id": race_instance_id,
        "team_id": as_int(horse.get("team_id")),
        "team_member_id": as_int(horse.get("team_member_id")),
        "is_ace": as_int(horse.get("team_member_id")) == 1,
        "trainer_name": str(horse.get("trainer_name") or horse.get("owner_trainer_name") or ""),
        "trainer_id": _trainer_id(horse),
        "trained_chara_id": trained_id,
        "single_mode_chara_id": as_int(horse.get("single_mode_chara_id")),
        "card_id": card_id,
        "chara_id": as_int(horse.get("chara_id")),
        "name": name,
        "rank": final_grade,
        "rank_label": RANK_LABELS.get(final_grade, str(final_grade) if final_grade else ""),
        "rank_score": as_int(detail.get("rank_score") or horse.get("rank_score")),
        "rarity": as_int(horse.get("rarity") or detail.get("rarity")),
        "talent_level": as_int(horse.get("talent_level") or detail.get("talent_level")),
        "stats": stats,
        "stat_sum": sum(stats.values()),
        "aptitudes": normalize_aptitudes(base),
        "running_style": running_style,
        "style": STYLE_NAMES.get(running_style_raw, STYLE_NAMES.get(str(running_style_raw), "")),
        "skills": _skill_rows(base, maps),
        "support_cards": support_cards,
        "parents": parents,
        "races": races,
        "career_wins": as_int(horse.get("single_mode_win_count") or detail.get("wins")),
        "win_saddle_ids": [as_int(v) for v in (horse.get("win_saddle_id_array") or detail.get("win_saddle_id_array") or []) if as_int(v)],
        "saved_match_bonus_raw": support_bonus_raw,
        "saved_match_bonus_pct": round(support_bonus_raw / 100.0, 2) if support_bonus_raw else 0,
        "support_card_bonus_raw": support_bonus_raw,
        "support_card_bonus_pct": round(support_bonus_raw / 100.0, 2) if support_bonus_raw else 0,
        **deck_rb,
        "has_detail_record": bool(detail_source),
        "detail_available": {
            "support_cards": bool(support_cards),
            "parents": bool(parents),
            "career_races": bool(races.get("history")),
        },
    }


def _matches_query(team: Dict[str, Any], query: str) -> bool:
    query = str(query or "").strip().lower()
    if not query:
        return True
    haystack = [
        team.get("trainer_name"),
        team.get("trainer_id"),
        team.get("source_file"),
        team.get("team_class"),
        team.get("team_rank_rating"),
    ]
    for member in team.get("members") or []:
        haystack.extend([
            member.get("name"),
            member.get("card_id"),
            member.get("trained_chara_id"),
            member.get("rank_label"),
            member.get("style"),
            member.get("distance"),
            member.get("career_wins"),
        ])
        for skill in member.get("skills") or []:
            haystack.append(skill.get("name"))
        for support in member.get("support_cards") or []:
            haystack.append(support.get("name"))
    return query in " ".join(str(value or "").lower() for value in haystack)


def _team_leader(members: List[Dict[str, Any]]) -> Dict[str, Any]:
    if not members:
        return {}
    return sorted(
        members,
        key=lambda row: (
            1 if row.get("is_ace") else 0,
            as_int(row.get("rank")),
            as_int(row.get("rank_score")),
            as_int(row.get("stat_sum")),
        ),
        reverse=True,
    )[0]


def _finish_team(team: Dict[str, Any]) -> Dict[str, Any]:
    members = team.get("members") or []
    leader = _team_leader(members)
    team["leader"] = leader
    team["leader_card_id"] = leader.get("card_id") or 0
    team["leader_name"] = leader.get("name") or ""
    team["member_count"] = len(members)
    team["max_rank"] = max([as_int(row.get("rank")) for row in members] or [0])
    team["max_rank_label"] = RANK_LABELS.get(team["max_rank"], str(team["max_rank"]) if team["max_rank"] else "")
    team["total_career_wins"] = sum(as_int(row.get("career_wins")) for row in members)
    team["best_stat_sum"] = max([as_int(row.get("stat_sum")) for row in members] or [0])
    team["has_any_detail_records"] = any(row.get("has_detail_record") for row in members)
    return team


def _team_sort_key(team: Dict[str, Any]) -> tuple:
    return (
        as_int(team.get("team_rank_rating")),
        as_int(team.get("max_rank")),
        as_int(team.get("best_stat_sum")),
        as_int(team.get("total_career_wins")),
        float(team.get("source_mtime") or 0),
    )


def _build_dataset(project_root: Path, source_dir: Path, *, limit_files: int = 250) -> Dict[str, Any]:
    maps = load_name_maps(Path(project_root))
    support_bonus_catalog = _load_support_bonus_catalog(Path(project_root))
    source_dir = Path(source_dir)
    files = sorted(source_dir.glob("TT-*.json"), key=lambda path: path.stat().st_mtime, reverse=True)[: max(1, limit_files)]
    detail_lookup = _detail_by_trained_id(source_dir)
    teams_by_key: Dict[str, Dict[str, Any]] = {}
    scanned_files: List[Dict[str, Any]] = []
    errors: List[Dict[str, str]] = []

    for file_path in files:
        data = _load_json(file_path, None)
        if not isinstance(data, dict):
            errors.append({"file": file_path.name, "error": "could not parse JSON"})
            continue
        source_mtime = file_path.stat().st_mtime
        file_name = file_path.name
        support_bonus_raw = as_int(data.get("support_card_bonus"))
        scanned_files.append({
            "name": file_name,
            "mtime": source_mtime,
            "size": file_path.stat().st_size,
            "support_card_bonus_raw": support_bonus_raw,
        })
        for round_payload in data.get("race_start_params_array") or []:
            if not isinstance(round_payload, dict):
                continue
            round_no = as_int(round_payload.get("round"))
            distance = DISTANCE_BY_ROUND.get(round_no, f"round_{round_no}" if round_no else "unknown")
            race_instance_id = as_int(round_payload.get("race_instance_id"))
            for horse in round_payload.get("race_horse_data_array") or []:
                if not isinstance(horse, dict):
                    continue
                team_id = as_int(horse.get("team_id"))
                trainer_name = str(horse.get("trainer_name") or horse.get("owner_trainer_name") or "").strip()
                if not trainer_name or team_id <= 0:
                    continue
                trainer_id = _trainer_id(horse)
                team_key = f"{trainer_name.lower()}|{trainer_id}|{file_name}|{team_id}"
                team = teams_by_key.get(team_key)
                if not team:
                    team = {
                        "key": team_key,
                        "trainer_name": trainer_name,
                        "trainer_id": trainer_id,
                        "trainer_id_label": str(trainer_id) if trainer_id else "ID unavailable in saved export",
                        "team_id": team_id,
                        "team_class": _team_class(horse),
                        "team_rank_rating": _team_rating(horse),
                        "source_file": file_name,
                        "source_mtime": source_mtime,
                        "captured_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(source_mtime)),
                        "support_card_bonus_raw": support_bonus_raw,
                        "support_card_bonus_pct": round(support_bonus_raw / 100.0, 2) if support_bonus_raw else 0,
                        "saved_match_bonus_raw": support_bonus_raw,
                        "saved_match_bonus_pct": round(support_bonus_raw / 100.0, 2) if support_bonus_raw else 0,
                        "members": [],
                        "members_by_distance": {name: [] for name in DISTANCE_BY_ROUND.values()},
                    }
                    teams_by_key[team_key] = team
                trained_id = as_int(horse.get("trained_chara_id") or horse.get("single_mode_chara_id"))
                detail = detail_lookup.get(trained_id)
                member = _normalize_character(
                    horse,
                    detail_source=detail,
                    maps=maps,
                    file_name=file_name,
                    distance=distance,
                    round_no=round_no,
                    race_instance_id=race_instance_id,
                    support_bonus_raw=support_bonus_raw,
                    support_bonus_catalog=support_bonus_catalog,
                    source_mtime=source_mtime,
                )
                team["members"].append(member)
                team.setdefault("members_by_distance", {}).setdefault(distance, []).append(member)

    teams = [_finish_team(team) for team in teams_by_key.values()]
    teams.sort(key=_team_sort_key, reverse=True)
    for idx, team in enumerate(teams, start=1):
        team["display_rank"] = idx
        team["score_label"] = f"{as_int(team.get('team_rank_rating')):,} pts" if as_int(team.get("team_rank_rating")) else "Score unavailable in saved export"
        team["class_label"] = str(as_int(team.get("team_class"))) if as_int(team.get("team_class")) else "--"

    return {
        "schema": TEAM_TRIALS_SCHEMA,
        "generated_at": now_stamp(),
        "source_dir": str(source_dir),
        "source_exists": source_dir.exists(),
        "files_scanned": scanned_files,
        "file_count": len(scanned_files),
        "errors": errors,
        "team_count": len(teams),
        "teams": teams,
    }


def _dedupe_latest_players(teams: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    latest: Dict[str, Dict[str, Any]] = {}
    for team in teams:
        trainer_name = str(team.get("trainer_name") or "").strip().lower()
        trainer_id = as_int(team.get("trainer_id"))
        key = f"id:{trainer_id}" if trainer_id else f"name:{trainer_name}"
        if not key:
            continue
        old = latest.get(key)
        if not old or float(team.get("source_mtime") or 0) > float(old.get("source_mtime") or 0):
            latest[key] = team
    rows = list(latest.values())
    rows.sort(key=_team_sort_key, reverse=True)
    for idx, team in enumerate(rows, start=1):
        team["display_rank"] = idx
    return rows


def load_team_trials_dataset(
    project_root: Path,
    runtime_root: Path,
    *,
    source_dir: Optional[Path] = None,
    refresh: bool = True,
    query: str = "",
    limit: int = 100,
    limit_files: int = 250,
) -> Dict[str, Any]:
    """Return normalized Team Trials data without modifying the source folder."""

    project_root = Path(project_root)
    runtime_root = Path(runtime_root)
    source = Path(source_dir) if source_dir else default_source_dir()
    target = dataset_path(runtime_root)
    if refresh or not target.exists():
        payload = _build_dataset(project_root, source, limit_files=limit_files)
        _write_cache(runtime_root, payload)
    else:
        payload = _load_json(target, {}) or {}

    teams = payload.get("teams") if isinstance(payload.get("teams"), list) else []
    players = _dedupe_latest_players(teams)
    filtered = [team for team in players if _matches_query(team, query)]
    try:
        limit = max(1, min(int(limit or 100), 500))
    except (TypeError, ValueError):
        limit = 100

    result = dict(payload)
    result["all_snapshot_count"] = len(teams)
    result["teams"] = filtered[:limit]
    result["player_count"] = len(players)
    result["filtered_count"] = len(filtered)
    result["cache_path"] = str(target)
    result["read_only_source"] = True
    result["query"] = str(query or "")
    return result
