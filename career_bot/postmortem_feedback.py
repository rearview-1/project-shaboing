"""Aggregate race postmortems into per-race actionable hints.

`career_bot/race_postmortem.py` writes detailed per-career analysis of
lost G1s — opponent stats, per-stat gap vs the player, aptitude rankings
— but those files were dead-end forensic logs that nothing downstream
consumed. The bot would lose the same races for the same reasons in
career after career.

This module reads recent postmortems and aggregates losses **by
race_id**, not globally. The output: "you've lost NHK Mile Cup 3 times
in the last 10 careers, average gap was -120 Power" — race-specific,
actionable. Replaces the previous global "worst_stat: guts" summary
that bias-bumped Guts for every race regardless of whether Guts
mattered for that course (which was the symptom of the Kikuka-vs-NHK
problem: Kikuka rewards stamina/guts, NHK rewards speed/power, but
the global summary couldn't tell them apart).
"""

import json
from collections import Counter
from pathlib import Path

from career_bot.race_learning_filters import (
    off_aptitude_dimensions_for_learning,
    postmortem_player_aptitudes,
)


POSTMORTEM_DIR_NAME = "postmortems"
RECENT_POSTMORTEM_LIMIT = 20

STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")
# Map stat name → command index used by training_policy / mant.py. Used
# when biasing training scores: if upcoming-race hint says "needs Power",
# the bonus targets command index 2.
STAT_TO_COMMAND_IDX = {"speed": 0, "stamina": 1, "power": 2, "guts": 3, "wit": 4}
# Running style ids per the game's internal encoding. Used to translate
# opponent_style_counts into human-readable advice for the dashboard.
RUNNING_STYLE_NAMES = {
    1: "front_runner",   # nige
    2: "pace_chaser",    # senko
    3: "late_surger",    # sashi
    4: "end_closer",     # oikomi
}


def load_recent_postmortems(runtime_root, limit=RECENT_POSTMORTEM_LIMIT):
    """Read the N most recently-written postmortem files.

    Skips malformed files silently — a single bad postmortem shouldn't
    block aggregation across the rest of the corpus.
    """
    runtime_root = Path(runtime_root)
    postmortem_dir = runtime_root / POSTMORTEM_DIR_NAME
    if not postmortem_dir.exists():
        return []
    files = sorted(
        postmortem_dir.glob("postmortem_*.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    recent = files[:limit]
    out = []
    for path in recent:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict):
            data["_source_path"] = str(path)
            out.append(data)
    return out


def aggregate_by_race(postmortems):
    """Group lost-G1 entries by program_id and compute mean stat gap.

    Returns dict {program_id: {race_name, loss_count, avg_gap: {stat: pts},
    worst_stat, worst_stat_gap}}.

    Gap convention: POSITIVE gap = opponents had MORE of that stat than
    the bot (i.e., a stat the bot needs more of to win). Negative gap
    means the bot was ahead. So `worst_stat` is the stat with the
    largest positive average gap — the one the bot most needs to grow
    for this specific race.

    If all gaps are negative (bot was ahead on every stat) we leave
    `worst_stat=None` — that race was lost for non-stat reasons (style
    mismatch, aptitude rank, RNG) and stat-bumping won't help.
    """
    by_race = {}
    for postmortem in postmortems or []:
        for loss in postmortem.get("g1_losses") or []:
            loss_context = {
                "distance": loss.get("race_distance") or loss.get("distance"),
                "terrain": loss.get("race_terrain") or loss.get("terrain"),
                "player_running_style": loss.get("player_running_style"),
            }
            if off_aptitude_dimensions_for_learning(loss_context, postmortem_player_aptitudes(loss)):
                continue
            program_id = loss.get("program_id")
            if not program_id:
                continue
            try:
                program_id = int(program_id)
            except (TypeError, ValueError):
                continue
            entry = by_race.setdefault(program_id, {
                "program_id": program_id,
                "race_name": loss.get("race_name") or "",
                "loss_count": 0,
                "_gap_totals": {key: 0.0 for key in STAT_KEYS},
                "_player_style_counts": Counter(),
                "_field_style_counts": Counter(),
                "_field_skill_counts": Counter(),
            })
            entry["loss_count"] += 1
            entry["race_name"] = loss.get("race_name") or entry["race_name"]
            gaps = loss.get("field_max_gap_over_player") or {}
            for key in STAT_KEYS:
                try:
                    entry["_gap_totals"][key] += float(gaps.get(key, 0) or 0)
                except (TypeError, ValueError):
                    continue
            # Roll up the richer fields. Older postmortems missing these
            # just contribute 0s — backward compat.
            player_style = int(loss.get("player_running_style") or 0)
            if player_style:
                entry["_player_style_counts"][player_style] += 1
            for style_id, count in (loss.get("opponent_style_counts") or {}).items():
                try:
                    entry["_field_style_counts"][int(style_id)] += int(count)
                except (TypeError, ValueError):
                    continue
            for skill in loss.get("common_opponent_skills") or []:
                try:
                    entry["_field_skill_counts"][int(skill["skill_id"])] += int(skill.get("count", 1))
                except (TypeError, ValueError, KeyError):
                    continue
    result = {}
    for program_id, entry in by_race.items():
        count = max(1, entry["loss_count"])
        avg_gap = {key: round(entry["_gap_totals"][key] / count, 1) for key in STAT_KEYS}
        worst_stat, worst_gap = max(avg_gap.items(), key=lambda kv: kv[1])
        if worst_gap <= 0:
            worst_stat = None
            worst_gap = 0.0
        # Style advice: if the field consistently runs a particular style
        # and the bot was running a different one in the lost races, the
        # advice flags the dominant field style as worth trying.
        field_style_dominant = None
        field_style_share = 0.0
        if entry["_field_style_counts"]:
            top_style, top_count = entry["_field_style_counts"].most_common(1)[0]
            total_field = sum(entry["_field_style_counts"].values())
            field_style_share = round(top_count / max(1, total_field), 3)
            if field_style_share >= 0.35:
                field_style_dominant = RUNNING_STYLE_NAMES.get(top_style, str(top_style))
        player_style_used = None
        if entry["_player_style_counts"]:
            ps, _ = entry["_player_style_counts"].most_common(1)[0]
            player_style_used = RUNNING_STYLE_NAMES.get(ps, str(ps))
        style_mismatch = (
            field_style_dominant is not None
            and player_style_used is not None
            and field_style_dominant != player_style_used
        )
        # Top opponent skills: identify what skills the field commonly
        # has that the bot might benefit from copying.
        top_skills = [
            {"skill_id": sid, "field_count": count}
            for sid, count in entry["_field_skill_counts"].most_common(8)
        ]
        result[program_id] = {
            "program_id": program_id,
            "race_name": entry["race_name"],
            "loss_count": entry["loss_count"],
            "avg_gap": avg_gap,
            "worst_stat": worst_stat,
            "worst_stat_gap": worst_gap,
            "player_style_used": player_style_used,
            "field_style_dominant": field_style_dominant,
            "field_style_share": field_style_share,
            "style_mismatch_suggested": style_mismatch,
            "common_opponent_skills": top_skills,
        }
    return result


def race_stat_hints(runtime_root, limit=RECENT_POSTMORTEM_LIMIT, min_losses=1):
    """Convenience: load recent postmortems and aggregate by race.

    Args:
        runtime_root: Path to uma_runtime/.
        limit: Number of most-recent postmortem files to consider.
        min_losses: Filter out races with fewer than N recorded losses.
            Default 1 surfaces every race that's ever been lost; raise
            to 2-3 to only surface chronic problem races.

    Returns:
        Dict of {program_id: race_hint_dict}. Empty when no postmortems
        exist or none meet the filter.
    """
    postmortems = load_recent_postmortems(runtime_root, limit=limit)
    aggregated = aggregate_by_race(postmortems)
    if min_losses > 1:
        aggregated = {
            pid: data for pid, data in aggregated.items()
            if data["loss_count"] >= min_losses
        }
    return aggregated


def diagnose_loss_pattern(hint, history_entry=None):
    """Multi-dimensional diagnosis of why a race keeps being lost.

    The hint dict from `aggregate_by_race` already carries the raw
    per-dimension signals (`worst_stat_gap`, `style_mismatch_suggested`,
    `common_opponent_skills`). This function synthesizes them into a
    single "what is the dominant cause" classification plus an
    ordered list of secondary contributing factors so the dashboard
    and bot decision layers can act on more than the worst-stat
    heuristic alone.

    Args:
        hint: per-race hint dict produced by `aggregate_by_race`.
        history_entry: optional entry from `race_attempt_history.load_history()`
            for this program_id. When present, chronic-loss streaks
            elevate the diagnosis confidence and add a `chronic` flag.

    Returns:
        {
          "primary": "stat_gap_power" | "style_mismatch" |
                     "skill_gap" | "low_confidence" | "no_clear_cause",
          "secondary": ["stat_gap_speed", "skill_gap", ...],
          "stat_gap_pts": float,
          "style_advice": str | None,
          "missing_skill_ids": list[int],
          "chronic": bool,
          "summary": str,
        }
    """
    primary = "no_clear_cause"
    secondary = []
    stat_gap_pts = float(hint.get("worst_stat_gap") or 0)
    worst_stat = hint.get("worst_stat")
    style_mismatch = bool(hint.get("style_mismatch_suggested"))
    field_style = hint.get("field_style_dominant")
    player_style = hint.get("player_style_used")
    common_skills = hint.get("common_opponent_skills") or []

    # Threshold: a 30+ point gap is treated as a real stat deficit worth
    # acting on. Was 150 (G1-tier gap) but that left most losses
    # mislabeled as "style_mismatch" when the operator's rule is to
    # never switch styles — losses should always feed back as training
    # adjustments, not style changes.
    stat_significant = stat_gap_pts >= 30.0

    candidates = []
    if stat_significant and worst_stat:
        # Boost stat-gap weight by 200 so it always beats style_mismatch
        # (weighted 50 below). This pins the diagnosis to a trainable
        # stat whenever the postmortem shows any meaningful gap, which
        # matches the operator rule: modify training, don't switch
        # styles.
        candidates.append((stat_gap_pts + 200.0, f"stat_gap_{worst_stat}"))
    if style_mismatch:
        # Style mismatch retained only as a SECONDARY signal — never
        # primary. The operator rule is "don't switch styles, modify
        # training." Weight 50 means it surfaces in `secondary` for
        # diagnostics but won't override a real stat gap.
        candidates.append((50.0, "style_mismatch"))
    # If multiple opponents shared a high-impact skill the bot lacks,
    # flag a skill gap. "Multiple" = >=3 occurrences in field (across
    # all postmortems summed). Threshold is heuristic; tune as we
    # accumulate data.
    high_count_skill = next((s for s in common_skills if int(s.get("field_count") or 0) >= 3), None)
    if high_count_skill:
        candidates.append((180.0, "skill_gap"))

    candidates.sort(reverse=True, key=lambda kv: kv[0])
    if candidates:
        primary = candidates[0][1]
        secondary = [name for _, name in candidates[1:]]

    chronic = False
    if isinstance(history_entry, dict):
        attempts = int(history_entry.get("attempts", 0) or 0)
        losses = int(history_entry.get("losses", 0) or 0)
        if attempts >= 3 and losses >= max(3, int(attempts * 0.6)):
            chronic = True
            # Chronic-loss races deserve a more confident verdict than
            # one-off losses; if everything is low-signal, at least flag
            # the race as a problem.
            if primary == "no_clear_cause":
                primary = "low_confidence"

    if primary.startswith("stat_gap_"):
        stat_name = primary.split("_", 2)[2]
        summary = f"Need ~{int(stat_gap_pts)} more {stat_name.capitalize()} to match this race's field."
    elif primary == "style_mismatch":
        # Should only land here if no stat gap met the 30-pt threshold —
        # i.e., losses are marginal across the board. Frame the summary
        # as a generic close-loss signal rather than a style-switch
        # recommendation. The operator rule is "don't switch styles."
        summary = (
            "Marginal loss with no single dominant stat deficit — likely a "
            "mix of small gaps. Continue current style; bot will keep "
            "biasing training toward whichever stat gap grows."
        )
    elif primary == "skill_gap":
        skill_id = int(high_count_skill["skill_id"]) if high_count_skill else 0
        summary = (
            f"Opponents commonly equip skill_id={skill_id}; bot lacks it. "
            "Bot would benefit from copying or denying this skill."
        )
    elif primary == "low_confidence":
        summary = (
            "Chronic loss with no single dominant cause — likely a combination of "
            "marginal stat gaps, RNG, or aptitude. Inspect raw postmortems."
        )
    else:
        summary = "No strong loss signal yet (low sample or marginal gaps)."

    return {
        "primary": primary,
        "secondary": secondary,
        "stat_gap_pts": round(stat_gap_pts, 1),
        # Operator rule: never switch styles based on postmortem. Keep
        # this field for schema stability but always emit None so no
        # downstream path can pull a "switch to <style>" directive out
        # of postmortem feedback. Mismatch is still reported in
        # `secondary` for human inspection.
        "style_advice": None,
        "missing_skill_ids": [int(s["skill_id"]) for s in common_skills if int(s.get("field_count") or 0) >= 3],
        "chronic": chronic,
        "summary": summary,
    }


def attach_diagnoses(per_race_hints, history):
    """Add a `diagnosis` field to each per-race hint using
    `diagnose_loss_pattern`. Mutates and returns the dict so callers
    can chain. `history` is the dict from `race_attempt_history.load_history()`."""
    if not per_race_hints:
        return per_race_hints
    history = history or {}
    for program_id, hint in per_race_hints.items():
        entry = history.get(str(program_id))
        hint["diagnosis"] = diagnose_loss_pattern(hint, history_entry=entry)
    return per_race_hints


def upcoming_race_stat_demand(per_race_hints, scheduled_entries, current_turn, lookahead=8):
    """Compute per-stat demand for races coming up in the next N turns.

    Combines `race_specific_stat_hints` (from postmortem aggregation)
    with the bot's scheduled race entries (from race_planner) to answer
    "what stats does the bot most need to grow right now?"

    Each upcoming race contributes its `worst_stat_gap` to the matching
    stat. Races further out contribute less (linear decay over the
    lookahead window) — a race in 6 turns is closer than one in 12, but
    not as urgent as one this turn.

    Args:
        per_race_hints: dict {program_id: hint_dict} from aggregate_by_race.
        scheduled_entries: list from race_planner.scheduled_entries(preset);
            each entry has at least `turn` and `program_id`.
        current_turn: the bot's current career turn.
        lookahead: window in turns (default 8).

    Returns:
        dict {stat: demand_pts}. Empty when no upcoming race has hints.
        `demand_pts` are in the same units as `worst_stat_gap` so a
        demand of 200 means "you need ~200 more of this stat to be
        competitive in the upcoming race(s)."
    """
    if not per_race_hints or not scheduled_entries:
        return {}
    demand = {key: 0.0 for key in STAT_KEYS}
    for entry in scheduled_entries:
        try:
            entry_turn = int(entry.get("turn") or 0)
            program_id = int(entry.get("program_id") or 0)
        except (TypeError, ValueError):
            continue
        if not program_id or entry_turn <= 0:
            continue
        offset = entry_turn - current_turn
        if offset < 0 or offset > lookahead:
            continue
        hint = per_race_hints.get(program_id)
        if not hint:
            continue
        worst_stat = hint.get("worst_stat")
        if not worst_stat:
            continue
        gap = float(hint.get("worst_stat_gap") or 0)
        if gap <= 0:
            continue
        # Linear urgency decay: race this turn = 1.0, race at end of
        # window = small. Min 0.2 so a race 8 turns out still registers.
        urgency = max(0.2, 1.0 - (offset / max(1, lookahead)))
        demand[worst_stat] = demand.get(worst_stat, 0.0) + gap * urgency
    return {k: round(v, 1) for k, v in demand.items() if v > 0}


def merge_global_signal(per_race_hints):
    """Roll the per-race hints up into a global "what to focus on" hint.

    Used as a soft hint for general training when the bot has no
    upcoming race-specific schedule. Weighted by loss count so chronic
    problem races dominate over one-off losses. Returns the same shape
    as the legacy summary (worst_stat, avg_gap) so callers can drop it
    in where the old global summary was used.
    """
    if not per_race_hints:
        return {"worst_stat": None, "worst_stat_gap": 0.0, "avg_gap": {key: 0.0 for key in STAT_KEYS}, "total_losses": 0}
    weighted_totals = {key: 0.0 for key in STAT_KEYS}
    total_losses = 0
    for hint in per_race_hints.values():
        count = max(1, int(hint.get("loss_count") or 1))
        total_losses += count
        for key in STAT_KEYS:
            weighted_totals[key] += float(hint["avg_gap"].get(key, 0)) * count
    avg_gap = {key: round(weighted_totals[key] / max(1, total_losses), 1) for key in STAT_KEYS}
    worst_stat, worst_gap = max(avg_gap.items(), key=lambda kv: kv[1])
    if worst_gap <= 0:
        return {"worst_stat": None, "worst_stat_gap": 0.0, "avg_gap": avg_gap, "total_losses": total_losses}
    return {
        "worst_stat": worst_stat,
        "worst_stat_gap": worst_gap,
        "avg_gap": avg_gap,
        "total_losses": total_losses,
    }
