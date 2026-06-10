"""Read-only learning samples from observed public Team Trials profiles.

These records do not include turn-by-turn decisions, so they must not train the
behavior policy. They are useful as high-level examples for deck, style,
distance, skill, and race-route priors.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


OBSERVATION_SCHEMA = "sweepy_team_trials_observation_v1"
OBSERVATION_DIR = "team_trials_observations"
OBSERVATION_FILENAME = "observations.jsonl"

STYLE_TO_PROFILE = {
    "front": "front_runner",
    "front runner": "front_runner",
    "front_runner": "front_runner",
    "nige": "front_runner",
    "pace": "pace_chaser",
    "pace chaser": "pace_chaser",
    "pace_chaser": "pace_chaser",
    "senko": "pace_chaser",
    "late": "late_surger",
    "late surger": "late_surger",
    "late_surger": "late_surger",
    "sashi": "late_surger",
    "end": "end_closer",
    "end closer": "end_closer",
    "end_closer": "end_closer",
    "closer": "end_closer",
    "oikomi": "end_closer",
}
DISTANCE_TO_PROFILE = {
    "sprint": "sprint",
    "short": "sprint",
    "mile": "mile",
    "medium": "medium",
    "middle": "medium",
    "long": "long",
}
STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _now_stamp() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def observation_path(runtime_root: Path) -> Path:
    return Path(runtime_root) / OBSERVATION_DIR / OBSERVATION_FILENAME


def normalize_observed_style(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    text = " ".join(text.replace("_", " ").split())
    return STYLE_TO_PROFILE.get(text, "")


def normalize_observed_distance(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_")
    text = " ".join(text.replace("_", " ").split())
    return DISTANCE_TO_PROFILE.get(text, "")


def _support_ids(member: Dict[str, Any]) -> List[int]:
    ids: List[int] = []
    for row in member.get("support_cards") or []:
        if not isinstance(row, dict):
            continue
        support_id = _safe_int(row.get("support_card_id") or row.get("id") or row.get("card_id"))
        if support_id:
            ids.append(support_id)
    return ids


def _support_cards(member: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in member.get("support_cards") or []:
        if not isinstance(row, dict):
            continue
        support_id = _safe_int(row.get("support_card_id") or row.get("id") or row.get("card_id"))
        if not support_id:
            continue
        rows.append({
            "id": support_id,
            "support_card_id": support_id,
            "name": str(row.get("name") or f"Support {support_id}"),
            "type": str(row.get("type") or ""),
            "rarity": str(row.get("rarity") or ""),
            "limit_break_count": _safe_int(row.get("limit_break_count"), -1),
            "level": _safe_int(row.get("level") or row.get("support_card_level")),
            "position": _safe_int(row.get("position")),
        })
    return rows


def _race_quality(member: Dict[str, Any]) -> Dict[str, Any]:
    races = member.get("races") if isinstance(member.get("races"), dict) else {}
    history = races.get("history") if isinstance(races.get("history"), list) else []
    wins = sum(1 for race in history if _safe_int((race or {}).get("result_rank")) == 1)
    losses = sum(1 for race in history if _safe_int((race or {}).get("result_rank")) > 1)
    return {
        "race_total": len(history),
        "race_wins": wins,
        "race_losses": losses,
    }


def observation_sample_from_member(team: Dict[str, Any], member: Dict[str, Any], *, source: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    if not isinstance(team, dict) or not isinstance(member, dict):
        return None
    support_ids = _support_ids(member)
    if len(support_ids) < 3:
        return None
    card_id = _safe_int(member.get("card_id"))
    trained_id = _safe_int(member.get("trained_chara_id"))
    rank_score = _safe_int(member.get("rank_score"))
    stats = member.get("stats") if isinstance(member.get("stats"), dict) else {}
    final_stats = {key: _safe_int(stats.get(key)) for key in STAT_KEYS}
    if not rank_score and not any(final_stats.values()):
        return None

    style_profile = normalize_observed_style(member.get("style") or member.get("running_style"))
    distance_slot = str(member.get("distance") or "").strip().lower()
    distance_profile = normalize_observed_distance(distance_slot)
    race_quality = _race_quality(member)
    team_id = _safe_int(team.get("trainer_id"))
    member_id = _safe_int(member.get("team_member_id"))
    observed_key = f"{team_id}:{trained_id}:{card_id}:{distance_slot}:{member_id}:{rank_score}"
    score = rank_score or sum(final_stats.values())
    weight = 0.28
    if rank_score >= 20000:
        weight += 0.16
    if member.get("is_ace"):
        weight += 0.04
    if race_quality["race_total"] >= 30:
        weight += 0.05

    run_context = {
        "source": "team_trials_observation",
        "trainer_id": team_id,
        "trainer_name": team.get("trainer_name") or member.get("trainer_name") or "",
        "team_rank_rating": _safe_int(team.get("team_rank_rating")),
        "team_class": _safe_int(team.get("team_class")),
        "distance_slot": distance_slot,
        "team_trials_distance_slot": distance_slot,
        "team_member_id": member_id,
        "is_ace": bool(member.get("is_ace")),
        "style": style_profile,
        "style_target": style_profile,
        "skill_profile_style": style_profile,
        "skill_profile_distance": distance_profile,
        "support_card_ids": support_ids,
        "support_cards": _support_cards(member),
        "trainee_card_id": card_id,
        "trainee_name": member.get("name") or "",
        "deck_name": f"observed TT {distance_slot or 'unknown'} {style_profile or 'style'}",
    }

    return {
        "schema": OBSERVATION_SCHEMA,
        "source": "team_trials_observation",
        "path": f"team_trials_observation#{observed_key}",
        "observation_key": observed_key,
        "created_at": _now_stamp(),
        "observed_at": _now_stamp(),
        "status": "observed_profile",
        "has_turn_data": False,
        "full_career_capture": False,
        "final_turn": 78,
        "turn_count": 0,
        "trainer_id": team_id,
        "trainer_name": run_context["trainer_name"],
        "team_rank_rating": run_context["team_rank_rating"],
        "team_class": run_context["team_class"],
        "trained_chara_id": trained_id,
        "trainee_card_id": card_id,
        "trainee_name": member.get("name") or "",
        "rank": _safe_int(member.get("rank")),
        "rank_label": member.get("rank_label") or "",
        "rank_score": rank_score,
        "score": float(score),
        "final_stats": final_stats,
        "stat_sum": sum(final_stats.values()),
        "race_wins": race_quality["race_wins"],
        "race_losses": race_quality["race_losses"],
        "race_total": race_quality["race_total"],
        "style": style_profile,
        "distance": distance_profile,
        "team_trials_distance_slot": distance_slot,
        "support_card_ids": support_ids,
        "support_cards": run_context["support_cards"],
        "skills": member.get("skills") or [],
        "races": (member.get("races") or {}).get("history") or [],
        "parents": member.get("parents") or [],
        "run_context": run_context,
        "actions": [],
        "support_actions": [],
        "sample_weight": round(weight, 4),
        "read_only_observation": True,
        "not_behavior_learning": True,
        "source_endpoint": (source or {}).get("endpoint") or team.get("source_endpoint") or "",
    }


def samples_from_team(team: Dict[str, Any], *, source: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for member in (team or {}).get("members") or []:
        sample = observation_sample_from_member(team, member, source=source)
        if sample:
            rows.append(sample)
    return rows


def append_team_observations(runtime_root: Path, team: Dict[str, Any], *, source: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    path = observation_path(runtime_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = set()
    if path.exists():
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    key = str(row.get("observation_key") or "")
                    if key:
                        existing.add(key)
        except Exception:
            existing = set()
    rows = samples_from_team(team, source=source)
    written = 0
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            key = str(row.get("observation_key") or "")
            if not key or key in existing:
                continue
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            existing.add(key)
            written += 1
    return {
        "path": str(path),
        "candidate_count": len(rows),
        "written_count": written,
        "total_known_keys": len(existing),
    }


def _iter_observation_paths(runtime_root: Path) -> Iterable[Path]:
    root = Path(runtime_root)
    yield observation_path(root)
    instances = root / "instances"
    if instances.exists():
        for child in sorted(instances.iterdir()):
            if child.is_dir():
                yield observation_path(child)


def load_observation_samples(runtime_root: Path, *, recent: Optional[int] = None, style: str = "", distance: str = "", min_score: int = 0) -> List[Dict[str, Any]]:
    style = normalize_observed_style(style) or str(style or "").strip()
    distance = normalize_observed_distance(distance) or str(distance or "").strip().lower()
    rows_by_key: Dict[str, Dict[str, Any]] = {}
    for path in _iter_observation_paths(runtime_root):
        if not path.exists():
            continue
        try:
            with path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if not line.strip():
                        continue
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    if row.get("schema") != OBSERVATION_SCHEMA:
                        continue
                    key = str(row.get("observation_key") or row.get("path") or "")
                    if not key:
                        continue
                    if min_score and _safe_int(row.get("rank_score") or row.get("score")) < min_score:
                        continue
                    row_style = str(row.get("style") or ((row.get("run_context") or {}).get("skill_profile_style")) or "")
                    row_distance = str(row.get("distance") or ((row.get("run_context") or {}).get("skill_profile_distance")) or "")
                    row_slot = str(row.get("team_trials_distance_slot") or ((row.get("run_context") or {}).get("team_trials_distance_slot")) or "")
                    if style and row_style != style:
                        continue
                    if distance and row_distance != distance and row_slot != distance:
                        continue
                    row["path"] = str(row.get("path") or f"{path}#{key}")
                    row["runtime_root"] = str(Path(runtime_root))
                    rows_by_key[key] = row
        except Exception:
            continue
    rows = sorted(rows_by_key.values(), key=lambda row: (_safe_int(row.get("rank_score")), str(row.get("observed_at") or "")), reverse=True)
    if recent:
        rows = rows[: max(0, int(recent))]
    return rows


def summarize_observation_samples(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_style: Dict[str, int] = {}
    by_distance: Dict[str, int] = {}
    by_card: Dict[int, Dict[str, Any]] = {}
    for sample in samples or []:
        style = str(sample.get("style") or "")
        distance = str(sample.get("team_trials_distance_slot") or sample.get("distance") or "")
        if style:
            by_style[style] = by_style.get(style, 0) + 1
        if distance:
            by_distance[distance] = by_distance.get(distance, 0) + 1
        for card in sample.get("support_cards") or []:
            card_id = _safe_int(card.get("support_card_id") or card.get("id"))
            if not card_id:
                continue
            row = by_card.setdefault(card_id, {"id": card_id, "name": card.get("name") or f"Support {card_id}", "count": 0, "score_sum": 0.0})
            row["count"] += 1
            row["score_sum"] += _safe_float(sample.get("rank_score") or sample.get("score"))
    top_cards = []
    for row in by_card.values():
        count = max(1, int(row.get("count") or 0))
        top_cards.append({
            "id": row["id"],
            "name": row["name"],
            "count": count,
            "avg_rank_score": round(row["score_sum"] / count, 2),
        })
    top_cards.sort(key=lambda row: (row["count"], row["avg_rank_score"]), reverse=True)
    return {
        "schema": "sweepy_team_trials_observation_summary_v1",
        "sample_count": len(samples or []),
        "by_style": by_style,
        "by_distance": by_distance,
        "top_support_cards": top_cards[:12],
    }
