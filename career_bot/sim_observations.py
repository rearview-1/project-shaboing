"""Normalized simulator observations from real bot careers.

Career logs are intentionally rich and UI/debug oriented.  This module writes a
small JSONL stream the simulator can consume directly after each run.
"""

from __future__ import annotations

import json
import os
import shutil
import time
import copy
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from career_bot.mant_fixed_events import (
    MANT_STATIC_FIXED_EVENTS,
    career_turn_calendar,
    career_turn_label,
    static_mant_event_for_story,
)


SCHEMA = "sweepy_sim_observation_v1"
SUMMARY_SCHEMA = "sweepy_sim_observation_summary_v1"
STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")
EVENT_DELTA_KEYS = ("speed", "stamina", "power", "guts", "wit", "hp", "motivation", "skill_point", "mant_coin")
STATIC_EFFECT_TO_DELTA_KEY = {
    "Speed": "speed",
    "Stamina": "stamina",
    "Power": "power",
    "Guts": "guts",
    "Wisdom": "wit",
    "Wit": "wit",
    "Mood": "motivation",
    "Skill Pts": "skill_point",
    "Skill Pt": "skill_point",
    "SP": "skill_point",
    "HP": "hp",
    "Coin": "mant_coin",
}
_OBSERVATION_CACHE: dict[tuple[Any, ...], Any] = {}
EVENT_SOURCE_BUCKETS = {
    "support_card_events": "support_card",
    "chara_events": "chara",
    "scenario_events": "scenario",
    "guest_events": "guest",
}
KNOWN_RECURRING_EVENT_NAMES = {
    "Victory!",
    "Solid Showing",
    "Extra Training",
    "Get Well Soon!",
    "Don't Overdo It!",
}
KNOWN_RECURRING_STORY_SUFFIXES = {"708", "709", "713", "715"}


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_default(value: Any) -> str:
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _runtime_instance_from_path(path: Path) -> str:
    parts = Path(path).parts
    for idx, part in enumerate(parts):
        if part.lower() == "instances" and idx + 1 < len(parts):
            return parts[idx + 1]
    return ""


def _runtime_root_from_career_log(path: Path) -> Path:
    path = Path(path)
    if path.parent.name.lower() == "bot_logs":
        return path.parent.parent
    return path.parent


def _runtime_roots(project_root: Path | str | None) -> list[Path]:
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
    roots: list[Path] = []
    candidates: list[Path] = []
    env_runtime = os.environ.get("UMA_RUNTIME_DIR")
    if env_runtime:
        candidates.append(Path(env_runtime).expanduser())
    candidates.extend([root / "uma_runtime", root.parent / "uma_runtime"])
    seen = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        key = str(resolved).lower()
        if resolved.exists() and key not in seen:
            roots.append(resolved)
            seen.add(key)
    return roots


def _compact_stats(row: dict[str, Any] | None) -> dict[str, int]:
    row = row or {}
    return {
        "hp": _as_int(row.get("hp") or row.get("vital")),
        "max_hp": _as_int(row.get("max_hp") or row.get("max_vital")),
        "motivation": _as_int(row.get("motivation")),
        "speed": _as_int(row.get("speed")),
        "stamina": _as_int(row.get("stamina")),
        "power": _as_int(row.get("power")),
        "guts": _as_int(row.get("guts")),
        "wit": _as_int(row.get("wit", row.get("wiz"))),
        "skill_point": _as_int(row.get("skill_point")),
    }


def _stat_delta(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, int]:
    before = _compact_stats(before)
    after = _compact_stats(after)
    keys = ("hp", "motivation", "speed", "stamina", "power", "guts", "wit", "skill_point")
    return {key: _as_int(after.get(key)) - _as_int(before.get(key)) for key in keys}


def _compact_support_card(row: dict[str, Any] | None, position: int = 0) -> dict[str, Any]:
    row = row or {}
    support_id = _as_int(row.get("support_card_id") or row.get("id") or row.get("card_id"))
    lb = row.get("lb_level")
    if lb is None:
        lb = row.get("limit_break_count")
    if lb is None:
        lb = row.get("lb")
    out = {
        "support_card_id": support_id,
        "name": row.get("name") or "",
        "type": row.get("type") or "",
        "rarity": row.get("rarity") or "",
        "lb_level": _as_int(lb),
        "level": _as_int(row.get("support_card_level") or row.get("level")),
    }
    if position:
        out["position"] = position
    return {key: value for key, value in out.items() if value or key in {"support_card_id", "lb_level", "level"}}


def _compact_run_context(ctx: dict[str, Any] | None) -> dict[str, Any]:
    ctx = ctx or {}
    out: dict[str, Any] = {}
    for key in (
        "preset_name",
        "deck_id",
        "deck_name",
        "deck_quality_bucket",
        "trainee_card_id",
        "chara_id",
        "friend_card_id",
        "friend_viewer_id",
        "parent_id_1",
        "parent_id_2",
        "rental_viewer_id",
        "rental_trained_chara_id",
        "runtime_instance",
        "skill_profile_style",
        "skill_profile_distance",
        "style",
        "running_style",
        "scenario_id",
    ):
        value = ctx.get(key)
        if value not in (None, "", [], {}):
            out[key] = value
    cards = []
    for index, raw in enumerate(ctx.get("support_cards") or [], start=1):
        if isinstance(raw, dict):
            card = _compact_support_card(raw, index)
            if card.get("support_card_id"):
                cards.append(card)
    if cards:
        out["support_cards"] = cards
        out["support_card_ids"] = [card["support_card_id"] for card in cards if card.get("support_card_id")]
    elif ctx.get("support_card_ids"):
        out["support_card_ids"] = [_as_int(value) for value in ctx.get("support_card_ids") or [] if _as_int(value)]
    if isinstance(ctx.get("support_card_lb_levels"), dict):
        out["support_card_lb_levels"] = ctx.get("support_card_lb_levels")
    schedule = ctx.get("custom_race_schedule")
    if isinstance(schedule, list):
        out["custom_race_schedule_count"] = len(schedule)
        out["custom_race_program_ids"] = [
            _as_int((row or {}).get("program_id"))
            for row in schedule
            if isinstance(row, dict) and _as_int(row.get("program_id"))
        ]
    parents = []
    for raw in ctx.get("parents") or []:
        if not isinstance(raw, dict):
            continue
        parents.append({
            "instance_id": _as_int(raw.get("instance_id") or raw.get("id")),
            "card_id": _as_int(raw.get("card_id")),
            "name": raw.get("name") or "",
            "score": _as_int(raw.get("score")),
        })
    if parents:
        out["parents"] = parents[:2]
    return out


def _command_stat(command: dict[str, Any] | None) -> str:
    command = command or {}
    command_id = _as_int(command.get("command_id"))
    return {
        101: "speed",
        105: "stamina",
        102: "power",
        103: "guts",
        106: "wit",
        601: "speed",
        602: "stamina",
        603: "power",
        604: "guts",
        605: "wit",
    }.get(command_id, "")


def _compact_command(command: dict[str, Any] | None) -> dict[str, Any]:
    command = command or {}
    keys = (
        "command_type",
        "command_id",
        "command_group_id",
        "select_id",
        "current_turn",
        "current_vital",
        "program_id",
    )
    out = {key: command.get(key) for key in keys if command.get(key) is not None}
    stat = _command_stat(command)
    if stat:
        out["stat"] = stat
    if isinstance(command.get("race"), dict):
        race = command.get("race") or {}
        out["race"] = {
            "program_id": _as_int(command.get("program_id") or race.get("program_id")),
            "name": race.get("name") or "",
            "grade": race.get("grade") or "",
            "distance": race.get("distance") or "",
            "terrain": race.get("terrain") or "",
        }
    return out


def _bucket_for_turn(turn: int) -> str:
    return str(((max(1, int(turn or 1)) - 1) // 12) * 12 + 1)


def _phase_for_turn(turn: int) -> str:
    turn = max(1, _as_int(turn, 1))
    if turn <= 24:
        return "junior"
    if turn <= 48:
        return "classic"
    if turn <= 72:
        return "senior"
    return "climax"


def _static_effects_to_delta(effects: dict[str, Any] | None) -> dict[str, int]:
    out = {key: 0 for key in EVENT_DELTA_KEYS}
    for raw_key, raw_value in (effects or {}).items():
        key = STATIC_EFFECT_TO_DELTA_KEY.get(str(raw_key))
        if not key:
            continue
        out[key] += _as_int(raw_value)
    return out


def _event_effect_flags(delta: dict[str, Any] | None, static_effects: dict[str, Any] | None = None) -> dict[str, Any]:
    values = {key: _as_int((delta or {}).get(key)) for key in EVENT_DELTA_KEYS}
    static_values = _static_effects_to_delta(static_effects)
    combined = {
        key: values.get(key, 0) if values.get(key, 0) else static_values.get(key, 0)
        for key in EVENT_DELTA_KEYS
    }
    stat_keys = ("speed", "stamina", "power", "guts", "wit")
    stat_gain_total = sum(max(0, _as_int(combined.get(key))) for key in stat_keys)
    return {
        "stat_gain": stat_gain_total > 0,
        "stat_gain_total": stat_gain_total,
        "sp_gain": _as_int(combined.get("skill_point")) > 0,
        "sp_delta": _as_int(combined.get("skill_point")),
        "mood_up": _as_int(combined.get("motivation")) > 0,
        "mood_down": _as_int(combined.get("motivation")) < 0,
        "mood_delta": _as_int(combined.get("motivation")),
        "hp_gain": _as_int(combined.get("hp")) > 0,
        "hp_loss": _as_int(combined.get("hp")) < 0,
        "hp_delta": _as_int(combined.get("hp")),
        "mant_coin_gain": _as_int(combined.get("mant_coin")) > 0,
        "mant_coin_delta": _as_int(combined.get("mant_coin")),
        "has_known_static_effect": any(_as_int(value) for value in static_values.values()),
    }


def _median_int(values: list[int]) -> int:
    values = sorted(int(v) for v in values)
    if not values:
        return 0
    mid = len(values) // 2
    if len(values) % 2:
        return int(values[mid])
    return int(round((values[mid - 1] + values[mid]) / 2))


def _event_profiles_from_records(records: list[dict[str, Any]], *, career_count: int = 0) -> dict[str, Any]:
    """Build cross-career event timing/effect profiles for the simulator.

    Fixed-event detection is intentionally conservative. Scenario and trainee
    events that repeatedly land on the same turn are safe to replay in the
    simulator. Support-card events are still exported as profiles, but they are
    not considered fixed by default because they depend on deck RNG, bond, and
    outing state.
    """

    profiles: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("record_type") != "event_resolution":
            continue
        metadata = record.get("event_metadata") if isinstance(record.get("event_metadata"), dict) else {}
        story_id = str(metadata.get("story_id") or record.get("story_id") or "").strip()
        if not story_id:
            continue
        entry = profiles.setdefault(story_id, {
            "story_id": story_id,
            "event_id": _as_int(metadata.get("event_id") or record.get("event_id")),
            "event_name": metadata.get("event_name") or "",
            "source": metadata.get("source") or "unknown",
            "source_id": str(metadata.get("source_id") or ""),
            "event_kind": metadata.get("event_kind") or "unknown",
            "support_card_id": _as_int(metadata.get("support_card_id")),
            "chara_id": _as_int(metadata.get("chara_id")),
            "count": 0,
            "career_ids": set(),
            "turns": Counter(),
            "turn_buckets": Counter(),
            "phases": Counter(),
            "effect_values": defaultdict(list),
        })
        entry["count"] += 1
        if record.get("career_id"):
            entry["career_ids"].add(str(record.get("career_id")))
        turn = _as_int(record.get("turn"))
        if turn:
            entry["turns"][str(turn)] += 1
            entry["turn_buckets"][_bucket_for_turn(turn)] += 1
            entry["phases"][_phase_for_turn(turn)] += 1
        delta = record.get("event_effect_delta") if isinstance(record.get("event_effect_delta"), dict) else {}
        for key in EVENT_DELTA_KEYS:
            value = _as_int(delta.get(key))
            if value:
                entry["effect_values"][key].append(value)

    serialized = []
    fixed = []
    for story_id, entry in profiles.items():
        turns = Counter(entry["turns"])
        top_turn, top_turn_count = ("", 0)
        if turns:
            top_turn, top_turn_count = turns.most_common(1)[0]
        count = max(1, int(entry.get("count") or 0))
        top_turn_share = float(top_turn_count) / count if count else 0.0
        effect_medians = {
            key: _median_int(values)
            for key, values in (entry.get("effect_values") or {}).items()
            if values
        }
        static_event = static_mant_event_for_story(story_id)
        static_turn = _as_int((static_event or {}).get("turn"))
        static_effects = copy.deepcopy((static_event or {}).get("effects") or {})
        profile = {
            "story_id": story_id,
            "event_id": _as_int(entry.get("event_id")),
            "event_name": entry.get("event_name") or "",
            "source": entry.get("source") or "unknown",
            "source_id": str(entry.get("source_id") or ""),
            "event_kind": entry.get("event_kind") or "unknown",
            "support_card_id": _as_int(entry.get("support_card_id")),
            "chara_id": _as_int(entry.get("chara_id")),
            "count": count,
            "career_count": len(entry.get("career_ids") or []),
            "turns": dict(turns),
            "turn_buckets": dict(entry.get("turn_buckets") or {}),
            "phases": dict(entry.get("phases") or {}),
            "top_turn": _as_int(top_turn),
            "top_turn_label": career_turn_label(_as_int(top_turn)),
            "top_turn_count": int(top_turn_count),
            "top_turn_share": round(top_turn_share, 4),
            "effect_medians": effect_medians,
            "effect_flags": _event_effect_flags(effect_medians, static_effects),
            "is_static_mant_fixed_event": bool(static_event),
            "static_mant_expected_turn": static_turn,
            "static_mant_expected_turn_label": career_turn_label(static_turn),
            "static_mant_turn_match": bool(static_turn and _as_int(top_turn) == static_turn),
            "static_mant_effects": static_effects,
        }
        serialized.append(profile)

        kind = str(profile.get("event_kind") or "")
        source = str(profile.get("source") or "")
        min_count = max(2, min(5, int(round(max(1, career_count) * 0.20))))
        fixed_candidate = (
            profile["top_turn"] > 0
            and profile["count"] >= min_count
            and profile["top_turn_share"] >= 0.80
            and source in {"scenario", "chara"}
            and kind not in {"race_win_recurring", "race_loss_or_place_recurring", "inheritance_inspiration", "guest_event", "unknown"}
        )
        if fixed_candidate:
            fixed.append(profile)

    serialized.sort(key=lambda row: (row.get("top_turn") or 999, row.get("source") or "", row.get("story_id") or ""))
    fixed.sort(key=lambda row: (row.get("top_turn") or 999, row.get("source") or "", row.get("story_id") or ""))
    return {
        "profiles": serialized,
        "fixed_turn_events": fixed,
    }


def _extract_training_snapshots(report: dict[str, Any], career_log_path: Path) -> list[dict[str, Any]]:
    try:
        from tools.extract_real_training_snapshots import extract_career_log_snapshots

        snapshots = extract_career_log_snapshots(report, career_log_path)
        if snapshots:
            return snapshots
    except Exception:
        pass
    snapshots = []
    cards = []
    ctx = report.get("run_context") or {}
    for index, raw in enumerate(ctx.get("support_cards") or [], start=1):
        card = _compact_support_card(raw if isinstance(raw, dict) else {}, index)
        if card.get("support_card_id"):
            cards.append(card)
    deck_signature = "-".join(str(card["support_card_id"]) for card in cards)
    for turn in report.get("turns") or []:
        if not isinstance(turn, dict):
            continue
        snapshot = turn.get("training_snapshot") or {}
        trainings = snapshot.get("trainings") if isinstance(snapshot, dict) else None
        if not trainings:
            continue
        commands = []
        for row in trainings:
            if not isinstance(row, dict):
                continue
            stat_gain = row.get("stat_gain") or {}
            params = []
            for key, target_type in (
                ("speed", 1),
                ("stamina", 2),
                ("power", 3),
                ("guts", 4),
                ("wit", 5),
                ("skill_point", 30),
                ("hp", 10),
            ):
                if key in stat_gain and _as_int(stat_gain.get(key)):
                    params.append({"target_type": target_type, "value": _as_int(stat_gain.get(key))})
            if not params:
                continue
            partners = [
                _as_int(partner.get("target_id"))
                for partner in row.get("partners") or []
                if isinstance(partner, dict) and _as_int(partner.get("target_id"))
            ]
            commands.append({
                "command_id": _as_int(row.get("command_id")),
                "command_type": 1,
                "stat": _command_stat(row),
                "level": _as_int(row.get("facility_level") or row.get("level"), 1),
                "is_enable": 1 if row.get("enabled", True) else 0,
                "training_partner_array": partners,
                "tips_event_partner_array": [
                    _as_int(partner.get("target_id"))
                    for partner in row.get("partners") or []
                    if isinstance(partner, dict) and partner.get("hint") and _as_int(partner.get("target_id"))
                ],
                "params_inc_dec_info_array": params,
                "failure_rate": _as_int(row.get("failure_rate")),
                "partner_count": _as_int(row.get("partner_count"), len(partners)),
                "tips_count": _as_int(row.get("hint_count")),
                "rainbow_partner_count": _as_int(row.get("rainbow_count")),
            })
        if commands:
            stats = (snapshot.get("stats") if isinstance(snapshot, dict) else None) or turn.get("stats") or {}
            snapshots.append({
                "source": str(career_log_path),
                "turn": _as_int((snapshot or {}).get("turn") or turn.get("turn")),
                "scenario_id": _as_int(report.get("scenario_id"), 4),
                "card_id": _as_int(ctx.get("trainee_card_id")),
                "motivation": _as_int(stats.get("motivation") or turn.get("motivation"), 3),
                "vital": _as_int(stats.get("hp") or stats.get("vital")),
                "max_vital": _as_int(stats.get("max_hp") or stats.get("max_vital"), 100),
                "skill_point": _as_int(stats.get("skill_point") or turn.get("skill_point")),
                "stats": {
                    "speed": _as_int(stats.get("speed")),
                    "stamina": _as_int(stats.get("stamina")),
                    "power": _as_int(stats.get("power")),
                    "guts": _as_int(stats.get("guts")),
                    "wit": _as_int(stats.get("wit", stats.get("wiz"))),
                },
                "support_cards": cards,
                "deck_signature": deck_signature,
                "bonds": {},
                "training_levels": {str(command["command_id"]): command["level"] for command in commands},
                "commands": commands,
            })
    return snapshots


def _extract_race_samples(career_log_path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    try:
        from tools.extract_real_race_snapshots import extract_file

        return extract_file(career_log_path)
    except Exception:
        return [], []


def _extract_shop_snapshots(career_log_path: Path) -> list[dict[str, Any]]:
    try:
        from tools.extract_real_shop_snapshots import extract_file

        return extract_file(career_log_path)
    except Exception:
        return []


def _event_program_id(event: dict[str, Any]) -> int:
    race = event.get("race") if isinstance(event.get("race"), dict) else {}
    return _as_int(event.get("program_id") or race.get("program_id"))


def _project_root_from_log(path: Path) -> Path:
    for parent in [path.parent, *path.parents]:
        if (parent / "career_bot").exists() and (parent / "data").exists():
            return parent
    return Path(__file__).resolve().parents[1]


def _event_lookup_for_project(project_root: Path) -> dict[str, dict[str, Any]]:
    try:
        resolved = project_root.resolve()
    except OSError:
        resolved = project_root
    cache_key = ("event_lookup", str(resolved).lower())
    cached = _OBSERVATION_CACHE.get(cache_key)
    if isinstance(cached, dict):
        return cached

    index = _read_json(project_root / "data" / "event_id_index.json") or {}
    lookup: dict[str, dict[str, Any]] = {}

    def add_rows(bucket: str, rows_by_source: Any, *, observed: bool = False) -> None:
        if not isinstance(rows_by_source, dict):
            return
        source = EVENT_SOURCE_BUCKETS.get(bucket, "guest")
        for source_id, rows in rows_by_source.items():
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                story_id = str(row.get("story_id") or "").strip()
                if not story_id:
                    continue
                entry = lookup.setdefault(story_id, {
                    "story_id": story_id,
                    "source": source,
                    "source_id": str(source_id or ""),
                    "event_name": "",
                    "choice_counts": {},
                    "observed_count": 0,
                    "chain_max": 0,
                    "chain_num": 0,
                })
                if entry.get("source") == "guest" or source != "guest":
                    entry["source"] = source
                    entry["source_id"] = str(source_id or entry.get("source_id") or "")
                if row.get("event_name") and not entry.get("event_name"):
                    entry["event_name"] = row.get("event_name")
                if row.get("choice_counts"):
                    merged = dict(entry.get("choice_counts") or {})
                    for choice, count in (row.get("choice_counts") or {}).items():
                        merged[str(choice)] = _as_int(merged.get(str(choice))) + _as_int(count)
                    entry["choice_counts"] = merged
                entry["observed_count"] = max(_as_int(entry.get("observed_count")), _as_int(row.get("count")))
                entry["chain_max"] = max(_as_int(entry.get("chain_max")), _as_int(row.get("chain_max")))
                entry["chain_num"] = max(_as_int(entry.get("chain_num")), _as_int(row.get("chain_num")))
                if row.get("choices") and not entry.get("choices"):
                    entry["choices"] = copy.deepcopy(row.get("choices"))
                if observed:
                    entry["observed"] = True

    for bucket in EVENT_SOURCE_BUCKETS:
        add_rows(bucket, index.get(bucket), observed=False)
    observed = index.get("observed") if isinstance(index.get("observed"), dict) else {}
    for bucket in EVENT_SOURCE_BUCKETS:
        add_rows(bucket, observed.get(bucket), observed=True)

    _OBSERVATION_CACHE[cache_key] = lookup
    return lookup


def _story_source_fallback(story_id: str, report: dict[str, Any], payload: dict[str, Any]) -> tuple[str, str]:
    story = str(story_id or "")
    if len(story) >= 9 and story.startswith("8") and story[1:6].isdigit():
        return "support_card", str(int(story[1:6]))
    if story.startswith("5"):
        ctx = report.get("run_context") or {}
        return "chara", str(ctx.get("trainee_card_id") or payload.get("chara_id") or "")
    if story.startswith("4"):
        return "scenario", str(report.get("scenario_id") or (report.get("run_context") or {}).get("scenario_id") or 4)
    return "guest", "0"


def _support_ids_for_run(report: dict[str, Any]) -> set[int]:
    ctx = report.get("run_context") or {}
    ids = {_as_int(value) for value in ctx.get("support_card_ids") or [] if _as_int(value)}
    for card in ctx.get("support_cards") or []:
        if isinstance(card, dict) and _as_int(card.get("support_card_id")):
            ids.add(_as_int(card.get("support_card_id")))
    if _as_int(ctx.get("friend_card_id")):
        ids.add(_as_int(ctx.get("friend_card_id")))
    return ids


def _event_metadata(
    event: dict[str, Any],
    report: dict[str, Any],
    event_lookup: dict[str, dict[str, Any]],
    story_total: int,
    occurrence_index: int,
) -> dict[str, Any]:
    payload = event.get("event_payload") if isinstance(event.get("event_payload"), dict) else {}
    raw = payload.get("raw_event") if isinstance(payload.get("raw_event"), dict) else {}
    story_id = str(event.get("story_id") or payload.get("story_id") or raw.get("story_id") or "").strip()
    turn = _as_int(event.get("turn"))
    turn_calendar = career_turn_calendar(turn)
    lookup = event_lookup.get(story_id) or {}
    source = str(lookup.get("source") or "").strip()
    source_id = str(lookup.get("source_id") or "").strip()
    if not source:
        source, source_id = _story_source_fallback(story_id, report, payload)
    event_name = (
        payload.get("event_title")
        or lookup.get("event_name")
        or raw.get("event_name")
        or raw.get("name")
        or ""
    )
    support_card_id = _as_int(payload.get("support_card_id") or raw.get("support_card_id"))
    if not support_card_id and source == "support_card":
        support_card_id = _as_int(source_id)
    chara_id = _as_int(payload.get("chara_id") or raw.get("chara_id"))
    if not chara_id and source == "chara":
        chara_id = _as_int(source_id)

    run_support_ids = _support_ids_for_run(report)
    suffix = story_id[-3:] if len(story_id) >= 3 else ""
    known_recurring = (
        story_total > 1
        or event_name in KNOWN_RECURRING_EVENT_NAMES
        or suffix in KNOWN_RECURRING_STORY_SUFFIXES
        or _as_int(lookup.get("observed_count")) >= 20 and event_name in KNOWN_RECURRING_EVENT_NAMES
    )
    succession = raw.get("succession_event_info")
    is_inspiration = bool(succession) or "inherit" in str(event_name).lower() or "succession" in str(event_name).lower()
    if suffix == "708":
        event_kind = "race_win_recurring"
    elif suffix == "709":
        event_kind = "race_loss_or_place_recurring"
    elif is_inspiration:
        event_kind = "inheritance_inspiration"
    elif source == "support_card":
        event_kind = "support_card_event"
    elif source == "chara":
        event_kind = "trainee_event"
    elif source == "scenario":
        event_kind = "scenario_event"
    else:
        event_kind = "guest_event"
    static_event = static_mant_event_for_story(story_id)
    static_turn = _as_int((static_event or {}).get("turn"))
    static_effects = copy.deepcopy((static_event or {}).get("effects") or {})

    return {
        "story_id": story_id,
        "event_id": _as_int(event.get("event_id") or payload.get("event_id") or raw.get("event_id")),
        "event_name": event_name,
        "source": source,
        "source_id": source_id,
        "event_kind": event_kind,
        "support_card_id": support_card_id,
        "support_in_run": bool(support_card_id and support_card_id in run_support_ids),
        "chara_id": chara_id,
        "chain_max": _as_int(lookup.get("chain_max")),
        "chain_num": _as_int(lookup.get("chain_num")),
        "turn_label": turn_calendar.get("label") or "",
        "turn_calendar": turn_calendar,
        "known_recurring": bool(known_recurring),
        "is_repeat_in_career": story_total > 1,
        "is_inspiration": bool(is_inspiration),
        "is_static_mant_fixed_event": bool(static_event),
        "static_mant_expected_turn": static_turn,
        "static_mant_expected_turn_label": career_turn_label(static_turn),
        "static_mant_turn_match": bool(static_turn and turn == static_turn),
        "static_mant_effects": static_effects,
        "effect_flags": _event_effect_flags({}, static_effects),
        "recurrence": {
            "occurrence_index": max(1, _as_int(occurrence_index, 1)),
            "total_in_career": max(0, _as_int(story_total)),
        },
        "choice_counts_seen": lookup.get("choice_counts") or {},
    }


def _event_state_delta(before: dict[str, Any] | None, after: dict[str, Any] | None) -> dict[str, int]:
    before = before or {}
    after = after or {}
    before_stats = before.get("stats") if isinstance(before.get("stats"), dict) else {}
    after_stats = after.get("stats") if isinstance(after.get("stats"), dict) else {}
    keys = ("speed", "stamina", "power", "guts", "wit")
    delta = {key: _as_int(after_stats.get(key)) - _as_int(before_stats.get(key)) for key in keys}
    delta["hp"] = _as_int(after.get("hp", after_stats.get("hp"))) - _as_int(before.get("hp", before_stats.get("hp")))
    delta["motivation"] = _as_int(after.get("motivation", after_stats.get("motivation"))) - _as_int(before.get("motivation", before_stats.get("motivation")))
    delta["skill_point"] = _as_int(after.get("skill_point", after_stats.get("skill_point"))) - _as_int(before.get("skill_point", before_stats.get("skill_point")))
    delta["mant_coin"] = _as_int(after.get("mant_coin")) - _as_int(before.get("mant_coin"))
    return delta


def _record_base(report: dict[str, Any], career_log_path: Path) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "career_id": career_log_path.stem,
        "source_log": str(career_log_path),
        "runtime_instance": _runtime_instance_from_path(career_log_path),
        "preset_name": report.get("preset_name") or "",
        "status": report.get("status") or "",
        "scenario_id": _as_int(report.get("scenario_id")),
    }


def build_sim_observation_records(career_log_path: str | Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    career_log_path = Path(career_log_path)
    report = _read_json(career_log_path)
    if not report:
        return [], {
            "schema": SUMMARY_SCHEMA,
            "career_id": career_log_path.stem,
            "source_log": str(career_log_path),
            "error": "career_log_unreadable",
        }

    base = _record_base(report, career_log_path)
    turns = [turn for turn in report.get("turns") or [] if isinstance(turn, dict)]
    turns.sort(key=lambda row: _as_int(row.get("turn")))
    next_by_index = {idx: turns[idx + 1] for idx in range(max(0, len(turns) - 1))}
    records: list[dict[str, Any]] = []
    event_lookup = _event_lookup_for_project(_project_root_from_log(career_log_path))
    event_story_totals: Counter[str] = Counter()
    for turn in turns:
        for event in turn.get("events") or []:
            if not isinstance(event, dict) or event.get("event") != "event_choice":
                continue
            payload = event.get("event_payload") if isinstance(event.get("event_payload"), dict) else {}
            raw = payload.get("raw_event") if isinstance(payload.get("raw_event"), dict) else {}
            story_id = str(event.get("story_id") or payload.get("story_id") or raw.get("story_id") or "").strip()
            if story_id:
                event_story_totals[story_id] += 1
    event_story_seen: Counter[str] = Counter()
    event_summary = {
        "by_source": Counter(),
        "by_kind": Counter(),
        "by_story": Counter(),
        "recurring_stories": Counter(),
        "resolution_by_turn_label": Counter(),
        "inspiration_events": 0,
        "mood_up_events": 0,
        "hp_delta_events": 0,
        "sp_gain_events": 0,
        "stat_gain_events": 0,
        "static_mant_fixed_events": [],
    }

    setup = dict(base)
    setup.update({
        "record_type": "setup",
        "started_at": report.get("started_at"),
        "ended_at": report.get("ended_at"),
        "run_context": _compact_run_context(report.get("run_context") or {}),
        "desired_parent_sparks": report.get("desired_parent_sparks") or {},
        "parent_farming_rules": report.get("parent_farming_rules") or {},
    })
    records.append(setup)
    ctx = report.get("run_context") or {}
    if isinstance(ctx.get("parents"), dict) or report.get("desired_parent_sparks"):
        inspiration_setup = dict(base)
        inspiration_setup.update({
            "record_type": "parent_inspiration_setup",
            "turn": 0,
            "parent_id_1": _as_int(ctx.get("parent_id_1")),
            "parent_id_2": _as_int(ctx.get("parent_id_2")),
            "parents": copy.deepcopy(ctx.get("parents") or {}),
            "desired_parent_sparks": copy.deepcopy(report.get("desired_parent_sparks") or ctx.get("desired_parent_sparks") or {}),
        })
        records.append(inspiration_setup)

    training_by_turn = {
        _as_int(snapshot.get("turn")): snapshot
        for snapshot in _extract_training_snapshots(report, career_log_path)
        if isinstance(snapshot, dict) and _as_int(snapshot.get("turn"))
    }
    race_result_samples, race_field_samples = _extract_race_samples(career_log_path)
    shop_by_turn: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for snapshot in _extract_shop_snapshots(career_log_path):
        shop_by_turn[_as_int(snapshot.get("turn"))].append(snapshot)

    for idx, turn in enumerate(turns):
        turn_no = _as_int(turn.get("turn"))
        turn_calendar = career_turn_calendar(turn_no)
        turn_label = str(turn_calendar.get("label") or "")
        next_turn = next_by_index.get(idx) or {}
        stats_before = _compact_stats(turn.get("stats"))
        stats_after = _compact_stats(next_turn.get("stats")) if next_turn else {}
        delta = _stat_delta(turn.get("stats"), next_turn.get("stats")) if next_turn else {}
        selected_action = turn.get("current_action_taken") or turn.get("selected_action") or ""
        command = _compact_command(turn.get("current_command") if isinstance(turn.get("current_command"), dict) else {})

        if turn_no in training_by_turn:
            row = dict(base)
            row.update({
                "record_type": "training_snapshot",
                "turn": turn_no,
                "turn_label": turn_label,
                "turn_calendar": turn_calendar,
                "selected_action": selected_action,
                "selected_command": command,
                "chosen_training_stat": command.get("stat") if command.get("command_type") == 1 else "",
                "stats_before": stats_before,
                "stats_after": stats_after,
                "delta_to_next_turn": delta,
                "snapshot": training_by_turn[turn_no],
            })
            records.append(row)

        if any(turn.get(key) for key in ("bot_skill_candidates", "bot_skill_selected", "bot_skill_attempt", "bot_skill_result", "skill_buy_attempts")):
            row = dict(base)
            row.update({
                "record_type": "skill_purchase",
                "turn": turn_no,
                "turn_label": turn_label,
                "turn_calendar": turn_calendar,
                "skill_point": _as_int(turn.get("skill_point")),
                "selected_action": selected_action,
                "candidates": turn.get("bot_skill_candidates") or [],
                "selected": turn.get("bot_skill_selected") or [],
                "attempt": turn.get("bot_skill_attempt") or [],
                "result": turn.get("bot_skill_result") or {},
                "attempt_events": turn.get("skill_buy_attempts") or [],
            })
            records.append(row)

        if shop_by_turn.get(turn_no) or any(turn.get(key) for key in (
            "bot_shop_candidates",
            "bot_shop_selected",
            "bot_shop_attempt",
            "bot_shop_result",
            "bot_item_use_selected",
            "bot_item_use_attempt",
            "bot_item_use_result",
            "item_buy_attempts",
            "item_usage_attempts",
        )):
            row = dict(base)
            row.update({
                "record_type": "shop_item_phase",
                "turn": turn_no,
                "turn_label": turn_label,
                "turn_calendar": turn_calendar,
                "mant_coin": _as_int(turn.get("mant_coin")),
                "skill_point": _as_int(turn.get("skill_point")),
                "selected_action": selected_action,
                "stats": stats_before,
                "shop_snapshots": shop_by_turn.get(turn_no) or [],
                "buy_candidates": turn.get("bot_shop_candidates") or [],
                "buy_selected": turn.get("bot_shop_selected") or [],
                "buy_attempt": turn.get("bot_shop_attempt") or [],
                "buy_result": turn.get("bot_shop_result") or {},
                "use_selected": turn.get("bot_item_use_selected") or [],
                "use_attempt": turn.get("bot_item_use_attempt") or [],
                "use_result": turn.get("bot_item_use_result") or {},
                "buy_attempt_events": turn.get("item_buy_attempts") or [],
                "use_attempt_events": turn.get("item_usage_attempts") or [],
                "inventory": turn.get("inventory") or [],
                "active_item_effects": turn.get("active_item_effects") or [],
            })
            records.append(row)

        for event in turn.get("events") or []:
            if not isinstance(event, dict):
                continue
            kind = str(event.get("event") or "")
            row = dict(base)
            row.update({
                "record_type": kind or "event",
                "turn": turn_no,
                "turn_label": turn_label,
                "turn_calendar": turn_calendar,
                "stats_before": stats_before,
                "stats_after": stats_after,
                "delta_to_next_turn": delta,
            })
            if kind == "race_result":
                race = event.get("race") if isinstance(event.get("race"), dict) else {}
                row.update({
                    "program_id": _event_program_id(event),
                    "race": {
                        "program_id": _event_program_id(event),
                        "name": race.get("name") or "",
                        "grade": race.get("grade") or "",
                        "distance": race.get("distance") or "",
                        "terrain": race.get("terrain") or "",
                        "venue": race.get("venue") or "",
                    },
                    "finish_rank": _as_int(event.get("finish_rank") or event.get("result_rank")),
                    "won": bool(event.get("won")),
                    "running_style": event.get("running_style"),
                    "desired_running_style": event.get("desired_running_style"),
                    "style_change": event.get("style_change") or {},
                    "raw_event": event,
                })
            elif kind in {"pre_race", "g1_pre_race"}:
                row.update({
                    "record_type": "pre_race",
                    "program_id": _event_program_id(event),
                    "phase": kind,
                    "stamina_check": event.get("stamina_check") or {},
                    "selected": event.get("selected") or [],
                    "attempt": event.get("attempt") or [],
                    "result": event.get("result") or {},
                    "raw_event": event,
                })
            elif kind == "event_choice":
                story_id = str(event.get("story_id") or "")
                event_story_seen[story_id] += 1
                metadata = _event_metadata(
                    event,
                    report,
                    event_lookup,
                    event_story_totals.get(story_id, 0),
                    event_story_seen.get(story_id, 1),
                )
                metadata = dict(metadata)
                metadata["turn_bucket"] = _bucket_for_turn(turn_no)
                metadata["turn_phase"] = _phase_for_turn(turn_no)
                metadata["turn_label"] = turn_label
                metadata["turn_calendar"] = turn_calendar
                event_summary["by_source"][metadata.get("source") or "unknown"] += 1
                event_summary["by_kind"][metadata.get("event_kind") or "unknown"] += 1
                event_summary["by_story"][metadata.get("story_id") or ""] += 1
                if metadata.get("known_recurring") or metadata.get("is_repeat_in_career"):
                    event_summary["recurring_stories"][metadata.get("story_id") or ""] += 1
                if metadata.get("is_inspiration"):
                    event_summary["inspiration_events"] += 1
                row.update({
                    "event_id": _as_int(event.get("event_id")),
                    "story_id": story_id,
                    "choice_index": _as_int(event.get("choice_index")),
                    "available_choices": _as_int(event.get("available_choices")),
                    "available_choice_options": event.get("available_choice_options") or [],
                    "state_before": event.get("state_before") or {},
                    "event_metadata": metadata,
                    "event_payload": event.get("event_payload") or {},
                    "raw_event": event,
                })
            elif kind == "event_resolution":
                story_id = str(event.get("story_id") or "")
                occurrence_index = event_story_seen.get(story_id, 0)
                if not occurrence_index and story_id:
                    event_story_seen[story_id] += 1
                    occurrence_index = event_story_seen[story_id]
                metadata = _event_metadata(
                    event,
                    report,
                    event_lookup,
                    event_story_totals.get(story_id, 0),
                    occurrence_index or 1,
                )
                metadata = dict(metadata)
                metadata["turn_bucket"] = _bucket_for_turn(turn_no)
                metadata["turn_phase"] = _phase_for_turn(turn_no)
                metadata["turn_label"] = turn_label
                metadata["turn_calendar"] = turn_calendar
                state_before = event.get("state_before") or {}
                state_after = event.get("state_after") or {}
                effected_factors = state_after.get("event_effected_factor_array") if isinstance(state_after, dict) else []
                event_delta = _event_state_delta(state_before, state_after) if state_before and state_after else {}
                was_inspiration = bool(metadata.get("is_inspiration"))
                if effected_factors:
                    metadata = dict(metadata)
                    metadata["is_inspiration"] = True
                    metadata["event_kind"] = "inheritance_inspiration"
                    metadata["event_effected_factor_count"] = len(effected_factors)
                    if not was_inspiration:
                        event_summary["inspiration_events"] += 1
                    event_summary["by_kind"]["inheritance_inspiration"] += 1
                metadata["effect_flags"] = _event_effect_flags(event_delta, metadata.get("static_mant_effects") or {})
                if event.get("success") is not False:
                    flags = metadata.get("effect_flags") or {}
                    event_summary["resolution_by_turn_label"][turn_label or str(turn_no)] += 1
                    if flags.get("mood_up"):
                        event_summary["mood_up_events"] += 1
                    if flags.get("hp_delta"):
                        event_summary["hp_delta_events"] += 1
                    if flags.get("sp_gain"):
                        event_summary["sp_gain_events"] += 1
                    if flags.get("stat_gain"):
                        event_summary["stat_gain_events"] += 1
                    if metadata.get("is_static_mant_fixed_event"):
                        event_summary["static_mant_fixed_events"].append({
                            "turn": turn_no,
                            "turn_label": turn_label,
                            "story_id": story_id,
                            "event_id": _as_int(event.get("event_id")),
                            "expected_turn": metadata.get("static_mant_expected_turn"),
                            "expected_turn_label": metadata.get("static_mant_expected_turn_label"),
                            "turn_match": bool(metadata.get("static_mant_turn_match")),
                            "expected_effects": copy.deepcopy(metadata.get("static_mant_effects") or {}),
                            "observed_delta": copy.deepcopy(event_delta),
                            "effect_flags": copy.deepcopy(flags),
                        })
                row.update({
                    "event_id": _as_int(event.get("event_id")),
                    "story_id": story_id,
                    "choice_index": _as_int(event.get("choice_index")),
                    "success": bool(event.get("success")),
                    "state_before": state_before,
                    "state_after": state_after,
                    "event_effect_delta": event_delta,
                    "event_metadata": metadata,
                    "event_payload": event.get("event_payload") or {},
                    "raw_event": event,
                })
                if metadata.get("is_inspiration"):
                    insp = dict(base)
                    insp.update({
                        "record_type": "inspiration_event",
                        "turn": turn_no,
                        "event_id": row["event_id"],
                        "story_id": story_id,
                        "choice_index": row["choice_index"],
                        "event_metadata": metadata,
                        "state_before": state_before,
                        "state_after": state_after,
                        "event_effect_delta": row["event_effect_delta"],
                        "event_effected_factor_array": effected_factors or [],
                        "succession_event_info": (
                            ((event.get("event_payload") or {}).get("raw_event") or {}).get("succession_event_info")
                            if isinstance(event.get("event_payload"), dict)
                            else None
                        ),
                    })
                    records.append(insp)
            else:
                row["raw_event"] = event
            records.append(row)

    for sample in race_result_samples:
        row = dict(base)
        row.update({
            "record_type": "race_result_sample",
            "turn": _as_int(sample.get("turn")),
            "program_id": _as_int(sample.get("program_id")),
            "sample": sample,
        })
        records.append(row)
    for sample in race_field_samples:
        row = dict(base)
        row.update({
            "record_type": "race_field_sample",
            "turn": _as_int(sample.get("turn")),
            "program_id": _as_int(sample.get("program_id")),
            "sample": sample,
        })
        records.append(row)

    final_turn = turns[-1] if turns else {}
    race_results = [
        record for record in records
        if record.get("record_type") == "race_result"
    ]
    final = dict(base)
    final.update({
        "record_type": "final",
        "turn": _as_int(final_turn.get("turn")),
        "final_stats": _compact_stats(final_turn.get("stats")),
        "final_sp": _as_int(final_turn.get("skill_point") or (final_turn.get("stats") or {}).get("skill_point")),
        "race_count": len(race_results),
        "race_wins": sum(1 for record in race_results if record.get("won")),
        "race_losses": sum(1 for record in race_results if not record.get("won")),
        "g1_losses": sum(
            1 for record in race_results
            if not record.get("won") and str(((record.get("race") or {}).get("grade") or "")).upper() == "G1"
        ),
    })
    records.append(final)

    counts = Counter(record.get("record_type") for record in records)
    event_profiles = _event_profiles_from_records(records, career_count=1)
    event_resolution_records = [
        record for record in records
        if record.get("record_type") == "event_resolution"
    ]
    event_turn_counts = Counter(str(_as_int(record.get("turn"))) for record in event_resolution_records if _as_int(record.get("turn")))
    event_phase_counts = Counter(_phase_for_turn(_as_int(record.get("turn"))) for record in event_resolution_records if _as_int(record.get("turn")))
    event_summary_serial = {
        "by_source": dict(event_summary["by_source"]),
        "by_kind": dict(event_summary["by_kind"]),
        "unique_story_count": len([key for key in event_summary["by_story"] if key]),
        "recurring_stories": dict(event_summary["recurring_stories"]),
        "inspiration_events": int(event_summary["inspiration_events"]),
        "mood_up_events": int(event_summary["mood_up_events"]),
        "hp_delta_events": int(event_summary["hp_delta_events"]),
        "sp_gain_events": int(event_summary["sp_gain_events"]),
        "stat_gain_events": int(event_summary["stat_gain_events"]),
        "resolution_by_turn": dict(event_turn_counts),
        "resolution_by_turn_label": dict(event_summary["resolution_by_turn_label"]),
        "resolution_by_phase": dict(event_phase_counts),
        "event_profiles": event_profiles.get("profiles") or [],
        "fixed_turn_events": event_profiles.get("fixed_turn_events") or [],
        "static_mant_fixed_events": event_summary["static_mant_fixed_events"],
        "static_mant_fixed_event_catalog": [
            {
                "turn": _as_int(event.get("turn")),
                "turn_label": career_turn_label(_as_int(event.get("turn"))),
                "story_id": str(event.get("story_id") or ""),
                "event_id": _as_int(event.get("event_id")),
                "expected_effects": copy.deepcopy(event.get("effects") or {}),
            }
            for event in MANT_STATIC_FIXED_EVENTS
        ],
    }
    summary = {
        "schema": SUMMARY_SCHEMA,
        "career_id": career_log_path.stem,
        "source_log": str(career_log_path),
        "runtime_instance": _runtime_instance_from_path(career_log_path),
        "status": report.get("status") or "",
        "preset_name": report.get("preset_name") or "",
        "record_count": len(records),
        "counts": dict(counts),
        "training_snapshot_count": counts.get("training_snapshot", 0),
        "race_result_count": counts.get("race_result", 0),
        "shop_item_phase_count": counts.get("shop_item_phase", 0),
        "skill_purchase_count": counts.get("skill_purchase", 0),
        "event_choice_count": counts.get("event_choice", 0),
        "event_resolution_count": counts.get("event_resolution", 0),
        "inspiration_event_count": counts.get("inspiration_event", 0),
        "event_summary": event_summary_serial,
        "final": final,
    }
    return records, summary


def write_sim_observation_export(
    career_log_path: str | Path,
    *,
    runtime_root: str | Path | None = None,
    output_dir: str | Path | None = None,
) -> dict[str, Any]:
    career_log_path = Path(career_log_path)
    records, summary = build_sim_observation_records(career_log_path)
    root = Path(runtime_root) if runtime_root else _runtime_root_from_career_log(career_log_path)
    out_dir = Path(output_dir) if output_dir else root / "sim_observations"
    out_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = out_dir / f"{career_log_path.stem}.jsonl"
    summary_path = out_dir / f"{career_log_path.stem}_summary.json"
    text = "".join(
        json.dumps(record, ensure_ascii=False, sort_keys=True, default=_json_default, separators=(",", ":")) + "\n"
        for record in records
    )
    _atomic_write_text(jsonl_path, text)
    summary = dict(summary)
    summary.update({
        "generated_at": int(time.time()),
        "jsonl_path": str(jsonl_path),
        "summary_path": str(summary_path),
    })
    _atomic_write_text(summary_path, json.dumps(summary, ensure_ascii=False, indent=2, default=_json_default) + "\n")
    try:
        shutil.copyfile(jsonl_path, out_dir / "latest.jsonl")
        shutil.copyfile(summary_path, out_dir / "latest_summary.json")
    except Exception:
        pass
    return summary


def _iter_observation_files(project_root: str | Path | None, preferred_instance: str = ""):
    preferred = str(preferred_instance or "").strip().lower()
    files = []
    for runtime_root in _runtime_roots(project_root):
        instance_root = runtime_root / "instances"
        if instance_root.exists():
            for path in instance_root.glob("*/sim_observations/career_log_*.jsonl"):
                if path.name.lower().startswith("latest"):
                    continue
                instance = _runtime_instance_from_path(path)
                priority = 0 if preferred and instance.lower() == preferred else 1
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    mtime = 0
                files.append((priority, -mtime, path))
        for path in runtime_root.glob("sim_observations/career_log_*.jsonl"):
            if path.name.lower().startswith("latest"):
                continue
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = 0
            files.append((1, -mtime, path))
    files.sort()
    for _priority, _mtime, path in files:
        yield path


def _observation_file_list(project_root: str | Path | None, preferred_instance: str = "") -> list[Path]:
    return list(_iter_observation_files(project_root, preferred_instance))


def _observation_cache_key(kind: str, files: list[Path], max_records: int) -> tuple[Any, ...]:
    signature = []
    for path in files:
        try:
            stat = path.stat()
            signature.append((str(path), int(stat.st_mtime_ns), int(stat.st_size)))
        except OSError:
            signature.append((str(path), 0, 0))
    return (kind, int(max_records or 0), tuple(signature))


def _preferred_instance_from_context(run_context: dict[str, Any] | None) -> str:
    run_context = run_context or {}
    for value in (
        run_context.get("runtime_instance"),
        os.environ.get("SWEEPY_SIM_INSTANCE_NAME"),
        os.environ.get("SWEEPY_INSTANCE_NAME"),
    ):
        text = str(value or "").strip()
        if text:
            return text
    return ""


def load_runtime_training_snapshots(
    project_root: str | Path | None = None,
    *,
    run_context: dict[str, Any] | None = None,
    max_records: int = 8000,
    copy_result: bool = True,
) -> list[dict[str, Any]]:
    """Load training snapshots exported by recent real bot runs."""

    snapshots: list[dict[str, Any]] = []
    seen = set()
    preferred = _preferred_instance_from_context(run_context)
    files = _observation_file_list(project_root, preferred)
    cache_key = _observation_cache_key("training", files, max_records)
    if cache_key in _OBSERVATION_CACHE:
        cached = _OBSERVATION_CACHE[cache_key]
        return copy.deepcopy(cached) if copy_result else cached
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("record_type") != "training_snapshot":
                continue
            snapshot = record.get("snapshot") if isinstance(record.get("snapshot"), dict) else None
            if not snapshot or not snapshot.get("commands"):
                continue
            source = str(snapshot.get("source") or record.get("source_log") or path)
            key = (source, _as_int(snapshot.get("turn")))
            if key in seen:
                continue
            seen.add(key)
            snapshot = dict(snapshot)
            snapshot["source_observation"] = str(path)
            snapshots.append(snapshot)
            if max_records and len(snapshots) >= max_records:
                _OBSERVATION_CACHE[cache_key] = copy.deepcopy(snapshots) if copy_result else snapshots
                return snapshots
    _OBSERVATION_CACHE[cache_key] = copy.deepcopy(snapshots) if copy_result else snapshots
    return snapshots


def load_runtime_event_observations(
    project_root: str | Path | None = None,
    *,
    run_context: dict[str, Any] | None = None,
    max_records: int = 12000,
    copy_result: bool = True,
) -> dict[str, Any]:
    """Load normalized event observations exported by recent real bot runs."""

    preferred = _preferred_instance_from_context(run_context)
    files = _observation_file_list(project_root, preferred)
    cache_key = _observation_cache_key("events", files, max_records)
    if cache_key in _OBSERVATION_CACHE:
        cached = _OBSERVATION_CACHE[cache_key]
        return copy.deepcopy(cached) if copy_result else cached

    records: list[dict[str, Any]] = []
    by_source = Counter()
    by_kind = Counter()
    recurring = Counter()
    story_counts = Counter()
    choice_count = 0
    resolution_count = 0
    inspiration_count = 0
    parent_setup_count = 0
    career_ids = set()

    for path in files:
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            record_type = record.get("record_type")
            if record_type not in {"event_choice", "event_resolution", "inspiration_event", "parent_inspiration_setup"}:
                continue
            compact = {
                "source_observation": str(path),
                "career_id": record.get("career_id"),
                "runtime_instance": record.get("runtime_instance"),
                "record_type": record_type,
                "turn": _as_int(record.get("turn")),
                "turn_label": record.get("turn_label") or career_turn_label(_as_int(record.get("turn"))),
                "turn_calendar": copy.deepcopy(record.get("turn_calendar") or career_turn_calendar(_as_int(record.get("turn")))),
                "event_id": _as_int(record.get("event_id")),
                "story_id": str(record.get("story_id") or ""),
                "choice_index": _as_int(record.get("choice_index")),
                "available_choices": _as_int(record.get("available_choices")),
                "available_choice_options": copy.deepcopy(record.get("available_choice_options") or []),
                "event_metadata": copy.deepcopy(record.get("event_metadata") or {}),
                "event_effect_delta": copy.deepcopy(record.get("event_effect_delta") or {}),
                "effect_flags": copy.deepcopy((record.get("event_metadata") or {}).get("effect_flags") or {}),
                "event_effected_factor_array": copy.deepcopy(record.get("event_effected_factor_array") or []),
            }
            if compact.get("career_id"):
                career_ids.add(str(compact.get("career_id")))
            if record_type == "parent_inspiration_setup":
                compact["parents"] = copy.deepcopy(record.get("parents") or {})
                compact["desired_parent_sparks"] = copy.deepcopy(record.get("desired_parent_sparks") or {})
                parent_setup_count += 1
            metadata = compact["event_metadata"]
            if metadata:
                by_source[str(metadata.get("source") or "unknown")] += 1 if record_type == "event_choice" else 0
                by_kind[str(metadata.get("event_kind") or "unknown")] += 1 if record_type == "event_choice" else 0
                story_id = str(metadata.get("story_id") or compact.get("story_id") or "")
                if story_id and record_type == "event_choice":
                    story_counts[story_id] += 1
                    if metadata.get("known_recurring") or metadata.get("is_repeat_in_career"):
                        recurring[story_id] += 1
                if metadata.get("is_inspiration") and record_type in {"event_choice", "event_resolution"}:
                    inspiration_count += 1
            if record_type == "event_choice":
                choice_count += 1
            elif record_type == "event_resolution":
                resolution_count += 1
            elif record_type == "inspiration_event":
                inspiration_count += 1
            records.append(compact)
            if max_records and len(records) >= max_records:
                profiles = _event_profiles_from_records(records, career_count=len(career_ids))
                result = {
                    "event_count": len(records),
                    "career_count": len(career_ids),
                    "choice_count": choice_count,
                    "resolution_count": resolution_count,
                    "inspiration_count": inspiration_count,
                    "parent_setup_count": parent_setup_count,
                    "by_source": dict(by_source),
                    "by_kind": dict(by_kind),
                    "recurring_stories": dict(recurring),
                    "unique_story_count": len(story_counts),
                    "event_profiles": profiles.get("profiles") or [],
                    "fixed_turn_events": profiles.get("fixed_turn_events") or [],
                    "events": records,
                }
                _OBSERVATION_CACHE[cache_key] = copy.deepcopy(result) if copy_result else result
                return result

    profiles = _event_profiles_from_records(records, career_count=len(career_ids))
    result = {
        "event_count": len(records),
        "career_count": len(career_ids),
        "choice_count": choice_count,
        "resolution_count": resolution_count,
        "inspiration_count": inspiration_count,
        "parent_setup_count": parent_setup_count,
        "by_source": dict(by_source),
        "by_kind": dict(by_kind),
        "recurring_stories": dict(recurring),
        "unique_story_count": len(story_counts),
        "event_profiles": profiles.get("profiles") or [],
        "fixed_turn_events": profiles.get("fixed_turn_events") or [],
        "events": records,
    }
    _OBSERVATION_CACHE[cache_key] = copy.deepcopy(result) if copy_result else result
    return result


def _iter_shop_records(
    project_root: str | Path | None = None,
    *,
    run_context: dict[str, Any] | None = None,
    max_records: int = 12000,
):
    preferred = _preferred_instance_from_context(run_context)
    yielded = 0
    for path in _iter_observation_files(project_root, preferred):
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("record_type") != "shop_item_phase":
                continue
            yielded += 1
            yield record
            if max_records and yielded >= max_records:
                return


def _selected_items(record: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = [row for row in record.get(key) or [] if isinstance(row, dict)]
    for snapshot in record.get("shop_snapshots") or []:
        if not isinstance(snapshot, dict):
            continue
        source_key = "selected_buy" if key == "buy_selected" else "selected_use"
        rows.extend(row for row in snapshot.get(source_key) or [] if isinstance(row, dict))
    return rows


def load_runtime_shop_summary(
    project_root: str | Path | None = None,
    *,
    run_context: dict[str, Any] | None = None,
    max_records: int = 12000,
    copy_result: bool = True,
) -> dict[str, Any]:
    """Summarize observed shop/item use rows exported by real bot runs."""

    shop_seen = Counter()
    bought = Counter()
    used = Counter()
    active = Counter()
    rival = Counter()
    bought_by_turn_bucket: dict[str, Counter] = defaultdict(Counter)
    used_by_turn_bucket: dict[str, Counter] = defaultdict(Counter)
    snapshot_count = 0
    preferred = _preferred_instance_from_context(run_context)
    files = _observation_file_list(project_root, preferred)
    cache_key = _observation_cache_key("shop", files, max_records)
    if cache_key in _OBSERVATION_CACHE:
        cached = _OBSERVATION_CACHE[cache_key]
        return copy.deepcopy(cached) if copy_result else cached

    def consume_record(record: dict[str, Any]) -> None:
        nonlocal snapshot_count
        snapshot_count += 1
        turn = _as_int(record.get("turn"))
        bucket = _bucket_for_turn(turn)
        shop_rows = []
        for snapshot in record.get("shop_snapshots") or []:
            if isinstance(snapshot, dict):
                shop_rows.extend(row for row in snapshot.get("shop_rows") or [] if isinstance(row, dict))
                for pid in snapshot.get("rival_program_ids") or []:
                    if _as_int(pid):
                        rival[str(_as_int(pid))] += 1
        shop_rows.extend(row for row in record.get("buy_candidates") or [] if isinstance(row, dict))
        for row in shop_rows:
            item_id = _as_int(row.get("item_id"))
            if item_id:
                shop_seen[str(item_id)] += 1
        for row in _selected_items(record, "buy_selected"):
            item_id = _as_int(row.get("item_id"))
            if item_id:
                bought[str(item_id)] += 1
                bought_by_turn_bucket[bucket][str(item_id)] += 1
        for row in _selected_items(record, "use_selected"):
            item_id = _as_int(row.get("item_id"))
            if item_id:
                used[str(item_id)] += 1
                used_by_turn_bucket[bucket][str(item_id)] += 1
        for row in record.get("active_item_effects") or []:
            if isinstance(row, dict) and _as_int(row.get("item_id")):
                active[str(_as_int(row.get("item_id")))] += 1

    yielded = 0
    stop = False
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8-sig").splitlines()
        except OSError:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("record_type") != "shop_item_phase":
                continue
            yielded += 1
            if max_records and yielded > max_records:
                stop = True
                break
            consume_record(record)
            if max_records and yielded >= max_records:
                stop = True
                break
        if stop:
            break
    result = {
        "snapshot_count": snapshot_count,
        "summary": {
            "snapshots": snapshot_count,
            "item_summary": {
                item_id: {
                    "shop_seen": shop_seen[item_id],
                    "bought": bought[item_id],
                    "used": used[item_id],
                    "active_seen": active[item_id],
                }
                for item_id in sorted(set(shop_seen) | set(bought) | set(used) | set(active), key=_as_int)
            },
            "bought_by_turn_bucket": {
                bucket: dict(counter)
                for bucket, counter in bought_by_turn_bucket.items()
            },
            "used_by_turn_bucket": {
                bucket: dict(counter)
                for bucket, counter in used_by_turn_bucket.items()
            },
            "rival_programs": dict(rival),
        },
    }
    _OBSERVATION_CACHE[cache_key] = copy.deepcopy(result) if copy_result else result
    return result



def _merge_count_dict(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = {str(key): _as_float(value) for key, value in (base or {}).items()}
    for key, value in (extra or {}).items():
        out[str(key)] = out.get(str(key), 0.0) + _as_float(value)
    return out


def merge_shop_summaries(base: dict[str, Any] | None, extra: dict[str, Any] | None) -> dict[str, Any]:
    """Merge static data/real_shop_snapshots with runtime observations."""

    base = dict(base or {})
    extra = extra or {}
    if not extra:
        return base
    merged = dict(base)
    merged["snapshots"] = _as_int(base.get("snapshots")) + _as_int(extra.get("snapshots"))
    item_summary = dict(base.get("item_summary") or {})
    for item_id, row in (extra.get("item_summary") or {}).items():
        current = dict(item_summary.get(str(item_id)) or {})
        current["shop_seen"] = _as_int(current.get("shop_seen")) + _as_int(row.get("shop_seen"))
        current["bought"] = _as_int(current.get("bought")) + _as_int(row.get("bought"))
        current["used"] = _as_int(current.get("used")) + _as_int(row.get("used"))
        current["active_seen"] = _as_int(current.get("active_seen")) + _as_int(row.get("active_seen"))
        if row.get("name") and not current.get("name"):
            current["name"] = row.get("name")
        item_summary[str(item_id)] = current
    merged["item_summary"] = item_summary
    for key in ("bought_by_turn_bucket", "used_by_turn_bucket"):
        buckets = {str(bucket): dict(counter) for bucket, counter in (base.get(key) or {}).items()}
        for bucket, counter in (extra.get(key) or {}).items():
            buckets[str(bucket)] = _merge_count_dict(buckets.get(str(bucket), {}), counter or {})
        merged[key] = buckets
    merged["rival_programs"] = _merge_count_dict(base.get("rival_programs") or {}, extra.get("rival_programs") or {})
    return merged
