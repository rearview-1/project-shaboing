"""Post-mortem analysis of lost G1 races from career trace files.

Career runs persist raw API trace data in `uma_runtime/trace_logs/api_payloads/`.
Each `single_mode_free/race_start` response carries `race_horse_data` with
trainer-screen stats for every horse in the field, including all NPC
opponents. Pairing that with the `race_end` finish rank lets us see, for any
lost G1, exactly which stats the trainee was behind on versus the winner.

This is intentionally read-only and post-career — it doesn't influence
in-flight decisions. The output flows into the learning report so the next
preset-tune cycle has concrete gap signal beyond bot-vs-bot score deltas.
"""

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from career_bot.postmortem_feedback import _worst_stat_with_dominance_guard


STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")
GRADE_BY_FIRST_DIGIT = {"1": "G1", "2": "G2", "3": "G3", "4": "OP"}
# Maximum number of opponent skill ids to record per loss. Postmortem files
# bloat fast if we dump every opponent's whole skill_array — we only need
# the most-common ones across the field to identify "this race wants
# Speed Star" style hints.
MAX_OPPONENT_SKILLS_PER_LOSS = 15
# Career mode applies a hidden +400 to every stat in-race. We surface BOTH the
# trainer-screen values (what the user sees) and the +400-adjusted "effective"
# race values, since the latter are what actually determine winner gaps.
CAREER_INVISIBLE_STAT_BONUS = 400


# NOTE on gap basis: gaps compare NPC listed stats against the player's RAW
# trainer-screen stats, NOT the +400 effective values. Whether NPC opponents
# receive their own in-race bonus is unverified, but race outcomes settle the
# practical question: fields whose listed stats sit hundreds of points below
# the player's effective values still win these races regularly, so the raw
# comparison tracks relative strength far better than (field - player - 400),
# which would zero out every observed deficit. Do not switch the basis to
# effective without a cited source on NPC stat bonuses.


def _safe_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _parse_iso_timestamp(value):
    """Best-effort parse of a career_log timestamp into a Unix epoch float.

    Career logs write ISO-8601 strings like '2026-05-14T22:59:22' (no tz).
    We treat naive timestamps as local time so the comparison against the
    trace file's `ts` field (also Unix-epoch) lines up with how those rows
    were written by the live capture."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.timestamp()
    return parsed.astimezone(timezone.utc).timestamp()


def _trace_rows(path, started_ts=None, ended_ts=None):
    """Iterate trace rows, optionally filtering by Unix-epoch time window.

    The trace file is append-only across many careers, so reading the whole
    file produces cumulative output. Pass the career_log's started_at /
    ended_at (converted to Unix epoch) to scope to just one career."""
    # Pad start by 2s and end by 60s so race_start/race_end pairs that bracket
    # the exact career boundaries aren't truncated by clock skew.
    start_cutoff = (started_ts - 2.0) if started_ts is not None else None
    end_cutoff = (ended_ts + 60.0) if ended_ts is not None else None
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = row.get("ts")
            if ts is not None:
                try:
                    ts_value = float(ts)
                except (TypeError, ValueError):
                    ts_value = None
                if ts_value is not None:
                    if start_cutoff is not None and ts_value < start_cutoff:
                        continue
                    if end_cutoff is not None and ts_value > end_cutoff:
                        continue
            yield row


def _horse_stats(horse):
    if not horse:
        return {key: 0 for key in STAT_KEYS}
    return {
        "speed": _safe_int(horse.get("speed")),
        "stamina": _safe_int(horse.get("stamina")),
        "power": _safe_int(horse.get("pow") or horse.get("power")),
        "guts": _safe_int(horse.get("guts")),
        "wit": _safe_int(horse.get("wiz") or horse.get("wit")),
    }


def _grade_from_race_instance_id(race_instance_id):
    text = str(race_instance_id or "")
    return GRADE_BY_FIRST_DIGIT.get(text[:1], "")


def _is_player(horse):
    return _safe_int(horse.get("viewer_id")) > 0


def _resolve_program_meta(program_id, race_program_map):
    if not race_program_map:
        return {}
    return race_program_map.get(program_id) or race_program_map.get(str(program_id)) or {}


def _latest_race_history_row(data, program_id):
    rows = data.get("race_history") or []
    for row in reversed(rows):
        if _safe_int(row.get("program_id")) == program_id:
            return row
    return rows[-1] if rows else {}


def _opponents(horses):
    return [horse for horse in horses or [] if not _is_player(horse)]


def _opponent_stat_summary(opponents):
    """The server only tells us the player's finish rank, not NPC order. To get
    meaningful gap signal we compare player stats to the best NPC in each stat
    dimension and to the field median — both are stable proxies for "what
    stat advantage did the field have over you" when the exact winner is
    unknowable from the response alone."""
    if not opponents:
        return {key: {"max": 0, "median": 0, "count_above_player": 0} for key in STAT_KEYS}
    summary = {}
    for key in STAT_KEYS:
        values = sorted(_horse_stats(horse).get(key, 0) for horse in opponents)
        summary[key] = {
            "max": values[-1] if values else 0,
            "median": values[len(values) // 2] if values else 0,
        }
    return summary


def _aptitude_summary(horse):
    if not horse:
        return {}
    return {
        "distance_short": _safe_int(horse.get("proper_distance_short")),
        "distance_mile": _safe_int(horse.get("proper_distance_mile")),
        "distance_medium": _safe_int(horse.get("proper_distance_middle")),
        "distance_long": _safe_int(horse.get("proper_distance_long")),
        "ground_turf": _safe_int(horse.get("proper_ground_turf")),
        "ground_dirt": _safe_int(horse.get("proper_ground_dirt")),
        "running_style_front": _safe_int(horse.get("proper_running_style_nige")),
        "running_style_pace": _safe_int(horse.get("proper_running_style_senko")),
        "running_style_late": _safe_int(horse.get("proper_running_style_sashi")),
        "running_style_end": _safe_int(horse.get("proper_running_style_oikomi")),
        "running_style": _safe_int(horse.get("running_style")),
    }


def analyze_trace(trace_path, race_program_map=None, started_at=None, ended_at=None):
    """Walk a trace file and emit one entry per lost G1.

    `started_at` / `ended_at` (ISO-8601 strings or Unix epoch floats) scope
    the analysis to a single career — without them, the trace's cumulative
    history will produce monotonically growing loss counts across runs.

    Each entry has trainer-screen stats, +400-adjusted "effective" race stats,
    the gap vs the winner, the largest single gap, and aptitude/style metadata.
    Won G1s and non-G1 races are skipped so the output stays focused.
    """
    race_program_map = race_program_map or {}
    started_ts = _parse_iso_timestamp(started_at)
    ended_ts = _parse_iso_timestamp(ended_at)
    pending_start = None
    losses = []
    for row in _trace_rows(trace_path, started_ts=started_ts, ended_ts=ended_ts):
        endpoint = row.get("endpoint") or ""
        direction = row.get("direction") or ""
        if endpoint == "single_mode_free/race_start" and direction == "RES":
            data = (row.get("data") or {}).get("data") or {}
            start_info = data.get("race_start_info") or {}
            program_id = _safe_int(start_info.get("program_id"))
            horses = start_info.get("race_horse_data") or start_info.get("race_horse_data_array") or []
            if program_id and horses:
                pending_start = {
                    "program_id": program_id,
                    "horses": list(horses),
                    "weather": _safe_int(start_info.get("weather")),
                    "ground_condition": _safe_int(start_info.get("ground_condition")),
                }
            continue
        if endpoint == "single_mode_free/race_end" and direction == "RES":
            data = (row.get("data") or {}).get("data") or {}
            reward = data.get("race_reward_info") or {}
            player_rank = _safe_int(reward.get("result_rank"))
            if not pending_start or not player_rank:
                pending_start = None
                continue
            program_id = pending_start["program_id"]
            history_row = _latest_race_history_row(data, program_id)
            turn = _safe_int(history_row.get("turn"))
            meta = _resolve_program_meta(program_id, race_program_map)
            race_instance_id = meta.get("race_instance_id") or program_id
            grade = _grade_from_race_instance_id(race_instance_id)
            if grade != "G1" or player_rank <= 1:
                pending_start = None
                continue
            horses = pending_start["horses"]
            player = next((horse for horse in horses if _is_player(horse)), None)
            if not player:
                pending_start = None
                continue
            opponents = _opponents(horses)
            player_stats = _horse_stats(player)
            opponent_summary = _opponent_stat_summary(opponents)
            effective_player = {key: player_stats[key] + CAREER_INVISIBLE_STAT_BONUS for key in STAT_KEYS}
            field_max_gaps = {
                key: opponent_summary[key]["max"] - player_stats.get(key, 0) for key in STAT_KEYS
            }
            count_above_player = {
                key: sum(1 for horse in opponents if _horse_stats(horse).get(key, 0) > player_stats.get(key, 0))
                for key in STAT_KEYS
            }
            raw_primary_stat, raw_primary_gap = max(field_max_gaps.items(), key=lambda item: item[1]) if field_max_gaps else (None, 0)
            if raw_primary_stat is not None and raw_primary_gap <= 0:
                raw_primary_stat, raw_primary_gap = None, 0
            primary_stat, primary_gap = _worst_stat_with_dominance_guard({
                key: float(value or 0)
                for key, value in field_max_gaps.items()
            })
            # Richer capture (added 2026-05): style, skills, finish time,
            # environment. The legacy stats-only postmortem misses cases
            # like "lost NHK Mile Cup to a field full of Pace Chasers
            # while running Front Runner" — pure stat gap can't surface
            # style mismatch as the actual cause.
            player_skills = [_safe_int(sid) for sid in (player.get("skill_array") or []) if _safe_int(sid) > 0]
            opponent_style_counts = Counter(_safe_int(h.get("running_style")) for h in opponents if _safe_int(h.get("running_style")) > 0)
            opponent_skill_counter = Counter()
            for horse in opponents:
                for sid in horse.get("skill_array") or []:
                    sid_int = _safe_int(sid)
                    if sid_int > 0:
                        opponent_skill_counter[sid_int] += 1
            # Trim to top-N for file-size reasons. We need "common across
            # the field" signal, not every NPC's full skill list.
            top_opponent_skills = [
                {"skill_id": sid, "count": count}
                for sid, count in opponent_skill_counter.most_common(MAX_OPPONENT_SKILLS_PER_LOSS)
            ]
            losses.append({
                "turn": turn,
                "program_id": program_id,
                "race_name": meta.get("name") or "",
                "race_distance": history_row.get("distance") or meta.get("distance") or "",
                "race_terrain": history_row.get("terrain") or meta.get("terrain") or "",
                "grade": grade,
                "player_finish_rank": player_rank,
                "field_size": len(horses),
                "player_stats": player_stats,
                "effective_player_stats": effective_player,
                "field_max_stats": {key: opponent_summary[key]["max"] for key in STAT_KEYS},
                "field_median_stats": {key: opponent_summary[key]["median"] for key in STAT_KEYS},
                "field_max_gap_over_player": field_max_gaps,
                "opponents_above_player_per_stat": count_above_player,
                "raw_primary_gap_stat": raw_primary_stat,
                "raw_primary_gap_value": raw_primary_gap if raw_primary_stat else 0,
                "primary_gap_stat": primary_stat,
                "primary_gap_value": primary_gap if primary_stat else 0,
                "primary_gap_method": "causal_weighted_gap",
                "player_aptitude": _aptitude_summary(player),
                # Richer capture:
                "player_running_style": _safe_int(player.get("running_style")),
                "player_skill_array": player_skills,
                "player_result_time": _safe_int(reward.get("result_time")),
                "opponent_style_counts": dict(opponent_style_counts),
                "common_opponent_skills": top_opponent_skills,
                "weather": pending_start.get("weather", 0),
                "ground_condition": pending_start.get("ground_condition", 0),
            })
            pending_start = None
    return losses


def summarize_losses(losses):
    """Aggregate gap signal across multiple lost G1s.

    Returns the count, the average gap per stat, and which stat had the
    largest average gap. Useful for preset-tuning hints like "raise stamina
    target — losing winners had 180 more stamina on average".
    """
    if not losses:
        return {
            "count": 0,
            "average_gap": {key: 0 for key in STAT_KEYS},
            "worst_stat": None,
            "worst_stat_average_gap": 0,
        }
    totals = {key: 0 for key in STAT_KEYS}
    for loss in losses:
        for key in STAT_KEYS:
            totals[key] += (loss.get("field_max_gap_over_player") or {}).get(key, 0)
    averages = {key: round(totals[key] / len(losses), 1) for key in STAT_KEYS}
    worst_stat, worst_value = _worst_stat_with_dominance_guard(averages)
    return {
        "count": len(losses),
        "average_field_max_gap": averages,
        "worst_stat": worst_stat,
        "worst_stat_average_gap": worst_value if worst_stat else 0,
        "worst_stat_method": "causal_weighted_gap",
    }


def newest_trace_for_career(runtime_root, career_log_path=None):
    runtime_root = Path(runtime_root)
    trace_dir = runtime_root / "trace_logs" / "api_payloads"
    if not trace_dir.exists():
        return None
    traces = sorted(trace_dir.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not traces:
        return None
    if not career_log_path:
        return traces[0]
    try:
        career_mtime = Path(career_log_path).stat().st_mtime
    except OSError:
        return traces[0]
    for path in traces:
        if path.stat().st_mtime <= career_mtime + 600:
            return path
    return traces[0]
