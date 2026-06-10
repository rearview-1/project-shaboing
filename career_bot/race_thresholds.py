"""Hard per-race stat targets derived from postmortem losses.

Companion to the soft `race_specific_stat_hints` postmortem feedback.
Hints say "bias guts a bit higher next time." Thresholds say "to win
Tenno Sho (Spring) you need effective_stamina >= 1034." Used by the
training-policy bias layer to drive deficit-targeted training and to
escalate force-training when stats project below threshold for an
upcoming required race.

Rule: when a race is lost, find which stats had a positive gap (the
field had more than the player). Raise the target for those stats by
`gap + cushion`. Stats the player was already ahead on stay at the
observed losing value (no upward pressure — we already had enough).
Across multiple losses, the per-stat target is the maximum across
samples. Stricter careers gradually tighten the bar.

NOTE: style overrides are NOT a lever this module emits. Per user
feedback, mid-career style changes forfeit race skill rewards and are
forbidden except for the two stamina-suicide races (Tenno Sho Spring,
Kikuka Sho) — those are handled elsewhere.
"""

import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from career_bot.postmortem_feedback import (
    STAT_KEYS,
    load_recent_postmortems,
)


DEFAULT_CUSHION = 50
RECENT_POSTMORTEM_LIMIT = 30
THRESHOLDS_FILENAME = "race_thresholds.json"
SCHEMA = "sweepy_race_thresholds_v1"


def _coerce_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _per_loss_target(loss, cushion):
    """For one loss, compute the per-stat target we should have hit.

    For each stat the player led on (gap <= 0): the observed effective
    value is the floor — we already had enough, no upward pressure.
    For each stat the field led on (gap > 0): target = effective + gap
    + cushion. That's the value that closes the gap with margin to
    spare.

    Returns dict {stat: int target}. Stats not present in the loss
    record are omitted.
    """
    effective = loss.get("effective_player_stats") or {}
    gaps = loss.get("field_max_gap_over_player") or {}
    target = {}
    for stat in STAT_KEYS:
        eff = _coerce_int(effective.get(stat))
        if eff <= 0:
            continue
        gap = _coerce_int(gaps.get(stat))
        if gap > 0:
            target[stat] = eff + gap + cushion
        else:
            target[stat] = eff
    return target


def build_race_thresholds(postmortems, cushion=DEFAULT_CUSHION):
    """Aggregate loss postmortems into per-race target stat dicts.

    Returns dict keyed by program_id (int):
      {
        program_id: {
          "race_name": str,
          "loss_count": int,
          "target_effective": {stat: int},
          "max_losing_effective": {stat: int},
          "primary_gap_stat_history": {stat: count},
          "no_stat_gap_loss_count": int,  # losses where all gaps were <=0
          "last_loss_career_log": str,
        }
      }

    `target_effective` is the load-bearing field: the bot should aim
    to hit at least these effective stats next time it runs the race.
    `no_stat_gap_loss_count` flags races where we lost despite leading
    on every stat — stat targets won't help, escalate via other levers.
    """
    by_race = defaultdict(lambda: {
        "race_name": "",
        "loss_count": 0,
        "target_effective": defaultdict(int),
        "max_losing_effective": defaultdict(int),
        "primary_gap_stat_history": defaultdict(int),
        "no_stat_gap_loss_count": 0,
        "last_loss_career_log": "",
    })
    for postmortem in postmortems or []:
        career_log = postmortem.get("career_log") or ""
        for loss in postmortem.get("g1_losses") or []:
            program_id = _coerce_int(loss.get("program_id"))
            if not program_id:
                continue
            entry = by_race[program_id]
            entry["race_name"] = loss.get("race_name") or entry["race_name"]
            entry["loss_count"] += 1
            entry["last_loss_career_log"] = career_log or entry["last_loss_career_log"]
            effective = loss.get("effective_player_stats") or {}
            for stat in STAT_KEYS:
                value = _coerce_int(effective.get(stat))
                if value > entry["max_losing_effective"][stat]:
                    entry["max_losing_effective"][stat] = value
            per_loss = _per_loss_target(loss, cushion)
            for stat, value in per_loss.items():
                if value > entry["target_effective"][stat]:
                    entry["target_effective"][stat] = value
            primary = loss.get("primary_gap_stat") or ""
            if primary in STAT_KEYS:
                entry["primary_gap_stat_history"][primary] += 1
            gaps = loss.get("field_max_gap_over_player") or {}
            positive_gaps = [stat for stat in STAT_KEYS if _coerce_int(gaps.get(stat)) > 0]
            if not positive_gaps:
                entry["no_stat_gap_loss_count"] += 1
    result = {}
    for program_id, entry in by_race.items():
        result[program_id] = {
            "race_name": entry["race_name"],
            "loss_count": entry["loss_count"],
            "target_effective": dict(entry["target_effective"]),
            "max_losing_effective": dict(entry["max_losing_effective"]),
            "primary_gap_stat_history": dict(entry["primary_gap_stat_history"]),
            "no_stat_gap_loss_count": entry["no_stat_gap_loss_count"],
            "last_loss_career_log": entry["last_loss_career_log"],
        }
    return result


def write_race_thresholds(runtime_root, thresholds, cushion=DEFAULT_CUSHION):
    runtime_root = Path(runtime_root)
    runtime_root.mkdir(parents=True, exist_ok=True)
    path = runtime_root / THRESHOLDS_FILENAME
    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cushion": cushion,
        "thresholds": {str(pid): data for pid, data in sorted(thresholds.items())},
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_race_thresholds(runtime_root):
    """Return {program_id (int): threshold_dict} or empty dict if missing/malformed."""
    path = Path(runtime_root) / THRESHOLDS_FILENAME
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    raw = payload.get("thresholds") or {}
    out = {}
    for key, value in raw.items():
        program_id = _coerce_int(key)
        if program_id and isinstance(value, dict):
            out[program_id] = value
    return out


def build_and_write_race_thresholds(runtime_root, limit=RECENT_POSTMORTEM_LIMIT, cushion=DEFAULT_CUSHION):
    postmortems = load_recent_postmortems(runtime_root, limit=limit)
    thresholds = build_race_thresholds(postmortems, cushion=cushion)
    path = write_race_thresholds(runtime_root, thresholds, cushion=cushion)
    return path, thresholds


# Career-end stat projection. The bot trains turn-by-turn; we need to
# answer "if I keep training at my current rate, will I hit X by turn Y?"
# Approximation: project linearly from current stats × (career_end / turn).
# Add the MANT scenario's +400 invisible career bonus to get effective
# stats. This is intentionally simple — accuracy isn't critical, the
# direction (am I under-target or comfortable?) is what drives training.

CAREER_END_TURN = 78
CAREER_INVISIBLE_STAT_BONUS = 400


def project_effective_stats_at_turn(current_stats, current_turn, target_turn):
    """Linear-scale projection of current stats to a future turn.

    current_stats: dict {stat_name: int raw value}
    current_turn: current turn (>=1)
    target_turn: turn we're projecting to (>= current_turn)

    Returns dict {stat_name: int projected effective value}, with the
    +400 career bonus added. If current_turn <= 0 or target_turn <
    current_turn, returns the input plus career bonus (no projection).
    """
    out = {}
    current_turn = max(1, int(current_turn or 0))
    target_turn = max(current_turn, int(target_turn or current_turn))
    scale = target_turn / current_turn
    for stat, value in (current_stats or {}).items():
        try:
            raw = float(value)
        except (TypeError, ValueError):
            raw = 0.0
        projected_raw = raw * scale
        out[stat] = int(projected_raw + CAREER_INVISIBLE_STAT_BONUS)
    return out


def compute_race_deficits(thresholds, scheduled_entries, current_stats, current_turn):
    """For each upcoming race, compute per-stat deficit vs threshold.

    thresholds: {program_id: threshold_dict} from load_race_thresholds.
    scheduled_entries: list of dicts with `program_id` and `turn` (the
        bot's planned race schedule).
    current_stats: dict {stat_name: int raw}.
    current_turn: int.

    Returns list of per-race deficit reports:
      [{
        "program_id": int,
        "race_name": str,
        "turn": int,
        "turns_until": int,
        "deficit": {stat: int (>=0)},
        "deficit_total": int,
      }]

    Only races with a known threshold AND in the future are included.
    """
    if not thresholds:
        return []
    try:
        current_turn = int(current_turn or 0)
    except (TypeError, ValueError):
        current_turn = 0
    out = []
    for entry in scheduled_entries or []:
        if not isinstance(entry, dict):
            continue
        program_id = _coerce_int(entry.get("program_id"))
        if not program_id:
            continue
        threshold = thresholds.get(program_id)
        if not threshold:
            continue
        target = (threshold or {}).get("target_effective") or {}
        if not target:
            continue
        race_turn = _coerce_int(entry.get("turn"))
        if race_turn <= 0 or race_turn < current_turn:
            continue
        projected = project_effective_stats_at_turn(current_stats, current_turn, race_turn)
        deficit = {}
        deficit_total = 0
        for stat, target_value in target.items():
            target_int = _coerce_int(target_value)
            projected_int = _coerce_int(projected.get(stat))
            gap = max(0, target_int - projected_int)
            if gap > 0:
                deficit[stat] = gap
                deficit_total += gap
        if deficit_total > 0:
            out.append({
                "program_id": program_id,
                "race_name": threshold.get("race_name") or "",
                "turn": race_turn,
                "turns_until": race_turn - current_turn,
                "deficit": deficit,
                "deficit_total": deficit_total,
            })
    return out


def aggregate_stat_deficit(deficits, max_lookahead_turns=20):
    """Roll per-race deficits into a single per-stat pressure value.

    Closer races weight more heavily — a deficit 4 turns out is 5× the
    pressure of a deficit 20 turns out, since the bot has less runway
    to close it. Beyond `max_lookahead_turns` the race is ignored
    (assume it will be closed naturally by then).

    Returns dict {stat_name: float pressure value}. Pressure is on
    same scale as raw point deficit so it plugs into existing
    `_POSTMORTEM_DEMAND_FULL_BONUS_AT`-style scaling.
    """
    out = {}
    for race in deficits or []:
        turns_until = max(1, _coerce_int(race.get("turns_until")))
        if turns_until > max_lookahead_turns:
            continue
        weight = max(0.2, 1.0 - (turns_until - 1) / max_lookahead_turns)
        for stat, gap in (race.get("deficit") or {}).items():
            out[stat] = out.get(stat, 0.0) + float(gap) * weight
    return out
