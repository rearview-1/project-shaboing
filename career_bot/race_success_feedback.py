"""Aggregate race wins into per-race success hints.

The loss-side postmortem pipeline already answers "why do we keep
losing this race?" What was missing was the symmetric question:
"when we DO win this race, what does that usually look like?"

This module learns from *all* recorded race results across the corpus.
It deliberately avoids promoting specific skill ids as "winning
skills." Instead it only tracks race-time skill dependence counts, so
the bot can prefer cleaner wins that required fewer mid-career skills.
"""

from collections import Counter, defaultdict

from career_bot.race_learning_filters import (
    off_aptitude_dimensions_for_learning,
    sample_chara_aptitudes,
)


STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")
RUNNING_STYLE_NAMES = {
    1: "front_runner",
    2: "pace_chaser",
    3: "late_surger",
    4: "end_closer",
}


def _sample_chara_key(sample):
    run_context = (sample or {}).get("run_context") or {}
    for value in (
        run_context.get("single_mode_chara_id"),
        run_context.get("trainee_card_id"),
        run_context.get("card_id"),
        (sample or {}).get("single_mode_chara_id"),
        (sample or {}).get("card_id"),
    ):
        chara_id = _safe_int(value)
        if chara_id > 0:
            return str(chara_id)
    return ""


def aggregate_success_by_race(samples, min_attempts=2, min_wins=1):
    """Build per-race win summaries from the normalized sample corpus."""
    by_race = {}
    for sample in samples or []:
        chara_key = _sample_chara_key(sample)
        chara_aptitudes = sample_chara_aptitudes(sample)
        for row in _iter_race_results(sample):
            if off_aptitude_dimensions_for_learning(row, chara_aptitudes):
                continue
            program_id = _safe_int(row.get("program_id"))
            if not program_id:
                continue
            race_meta = row.get("race") or {}
            entry = by_race.setdefault(program_id, {
                "program_id": program_id,
                "race_name": race_meta.get("name") or row.get("race_name") or "",
                "attempts": 0,
                "wins": 0,
                "losses": 0,
                "_style_counts": Counter(),
                "_win_skill_counts": [],
                "_skill_count_buckets": Counter(),
                "_stat_totals": {key: 0.0 for key in STAT_KEYS},
                "_stat_samples": 0,
                "_g1_attempts": 0,
                "_g1_wins": 0,
                "_best_effort_win": None,
                "_best_effort_wins_by_style": {},
                "_style_counts_by_chara": defaultdict(Counter),
                "_wins_by_chara": Counter(),
            })
            entry["attempts"] += 1
            entry["race_name"] = race_meta.get("name") or entry["race_name"]
            is_g1 = bool(row.get("is_g1")) or str((race_meta or {}).get("grade") or "").upper() == "G1"
            if is_g1:
                entry["_g1_attempts"] += 1
            if not row.get("won"):
                entry["losses"] += 1
                continue
            entry["wins"] += 1
            if is_g1:
                entry["_g1_wins"] += 1
            style = _safe_int(row.get("running_style"))
            if style:
                entry["_style_counts"][style] += 1
                if chara_key:
                    entry["_style_counts_by_chara"][chara_key][style] += 1
            if chara_key:
                entry["_wins_by_chara"][chara_key] += 1
            if row.get("skill_count_at_race") is not None:
                skill_count = max(0, _safe_int(row.get("skill_count_at_race")))
                entry["_win_skill_counts"].append(skill_count)
                bucket = str(min(skill_count, 6))
                entry["_skill_count_buckets"][bucket] += 1
            stats = row.get("stats_at_race") or {}
            if isinstance(stats, dict):
                found_stat = False
                for key in STAT_KEYS:
                    if key not in stats:
                        continue
                    entry["_stat_totals"][key] += _safe_float(stats.get(key))
                    found_stat = True
                if found_stat:
                    entry["_stat_samples"] += 1
                    effort = _race_effort_score(stats, row.get("skill_count_at_race"))
                    profile = {
                        "running_style": RUNNING_STYLE_NAMES.get(style, str(style)) if style else None,
                        "skill_count_at_race": max(0, _safe_int(row.get("skill_count_at_race"))),
                        "stats_at_race": {
                            key: round(_safe_float(stats.get(key)), 1)
                            for key in STAT_KEYS
                            if _safe_float(stats.get(key)) > 0
                        },
                        "effort_score": round(effort, 1),
                    }
                    if not entry["_best_effort_win"] or effort < entry["_best_effort_win"]["effort_score"]:
                        entry["_best_effort_win"] = dict(profile)
                    style_key = profile.get("running_style")
                    if style_key:
                        previous = entry["_best_effort_wins_by_style"].get(style_key)
                        if not previous or effort < previous["effort_score"]:
                            entry["_best_effort_wins_by_style"][style_key] = dict(profile)
    result = {}
    for program_id, entry in by_race.items():
        attempts = max(1, entry["attempts"])
        wins = entry["wins"]
        if entry["attempts"] < min_attempts or wins < min_wins:
            continue
        win_rate = wins / attempts
        preferred_style = None
        preferred_style_share = 0.0
        if entry["_style_counts"]:
            style_id, count = entry["_style_counts"].most_common(1)[0]
            preferred_style = RUNNING_STYLE_NAMES.get(style_id, str(style_id))
            preferred_style_share = count / max(1, wins)
        preferred_style_by_chara = {}
        for chara_key, counts in (entry["_style_counts_by_chara"] or {}).items():
            if not counts:
                continue
            chara_wins = _safe_int(entry["_wins_by_chara"].get(chara_key))
            if chara_wins <= 0:
                continue
            style_id, count = counts.most_common(1)[0]
            preferred_style_by_chara[str(chara_key)] = {
                "style": RUNNING_STYLE_NAMES.get(style_id, str(style_id)),
                "share": round(count / max(1, chara_wins), 3),
                "wins": chara_wins,
            }
        win_skill_counts = entry["_win_skill_counts"]
        winning_stat_baseline = {}
        if entry["_stat_samples"] > 0:
            for key in STAT_KEYS:
                winning_stat_baseline[key] = round(entry["_stat_totals"][key] / entry["_stat_samples"], 1)
        confidence = min(
            1.0,
            (wins / max(2.0, float(min_attempts))) * 0.45
            + win_rate * 0.35
            + (1.0 if entry["_stat_samples"] > 0 else 0.0) * 0.10
            + (1.0 if win_skill_counts else 0.0) * 0.10,
        )
        result[program_id] = {
            "program_id": program_id,
            "race_name": entry["race_name"],
            "attempts": entry["attempts"],
            "wins": wins,
            "losses": entry["losses"],
            "win_rate": round(win_rate, 3),
            "g1_attempts": entry["_g1_attempts"],
            "g1_wins": entry["_g1_wins"],
            "preferred_running_style": preferred_style,
            "preferred_running_style_share": round(preferred_style_share, 3),
            "preferred_running_style_by_chara": preferred_style_by_chara,
            "winning_stat_baseline": winning_stat_baseline,
            "winning_stat_sample_count": entry["_stat_samples"],
            "avg_win_skill_count": round(sum(win_skill_counts) / len(win_skill_counts), 3) if win_skill_counts else None,
            "min_win_skill_count": min(win_skill_counts) if win_skill_counts else None,
            "max_win_skill_count": max(win_skill_counts) if win_skill_counts else None,
            "wins_without_skills": entry["_skill_count_buckets"].get("0", 0),
            "win_skill_count_buckets": dict(sorted(entry["_skill_count_buckets"].items(), key=lambda item: int(item[0]))),
            "parsimony_score": round(1.0 / (1.0 + (sum(win_skill_counts) / len(win_skill_counts))), 4) if win_skill_counts else None,
            "confidence": round(confidence, 3),
            "efficient_win_profile": dict(entry["_best_effort_win"] or {}),
            "efficient_win_profiles_by_style": {
                str(style_key): dict(profile)
                for style_key, profile in sorted((entry["_best_effort_wins_by_style"] or {}).items())
            },
        }
    return result


def merge_global_success_signal(per_race):
    """Weighted fallback summary across all successful race hints."""
    if not per_race:
        return {
            "attempts": 0,
            "wins": 0,
            "avg_win_skill_count": None,
            "preferred_running_style": None,
            "winning_stat_baseline": {},
        }
    total_attempts = 0
    total_wins = 0
    style_counts = Counter()
    skill_count_weight = 0
    skill_count_total = 0.0
    stat_totals = defaultdict(float)
    stat_weight = 0
    for hint in per_race.values():
        wins = max(0, _safe_int(hint.get("wins")))
        total_attempts += _safe_int(hint.get("attempts"))
        total_wins += wins
        style = str(hint.get("preferred_running_style") or "").strip()
        if style and wins:
            style_counts[style] += wins
        avg_skill_count = hint.get("avg_win_skill_count")
        if avg_skill_count is not None and wins:
            skill_count_total += _safe_float(avg_skill_count) * wins
            skill_count_weight += wins
        baseline = hint.get("winning_stat_baseline") or {}
        if isinstance(baseline, dict) and wins:
            for key in STAT_KEYS:
                if key in baseline:
                    stat_totals[key] += _safe_float(baseline.get(key)) * wins
            stat_weight += wins
    preferred_style = style_counts.most_common(1)[0][0] if style_counts else None
    winning_stat_baseline = {}
    if stat_weight > 0:
        for key in STAT_KEYS:
            winning_stat_baseline[key] = round(stat_totals[key] / stat_weight, 1)
    return {
        "attempts": total_attempts,
        "wins": total_wins,
        "avg_win_skill_count": round(skill_count_total / skill_count_weight, 3) if skill_count_weight else None,
        "preferred_running_style": preferred_style,
        "winning_stat_baseline": winning_stat_baseline,
    }


def upcoming_race_success_demand(per_race_hints, scheduled, current_turn, current_stats, lookahead=8):
    """Return stat demand implied by historically successful races.

    Unlike loss hints, this is not "the field beat us by X." It is:
    "when we historically won this race, we were usually around these
    visible stat bands by then." Only positive deficits contribute.
    """
    demand = defaultdict(float)
    normalized = {}
    for key, value in (per_race_hints or {}).items():
        try:
            normalized[int(key)] = value
        except (TypeError, ValueError):
            continue
    current_turn = _safe_int(current_turn)
    current_stats = current_stats or {}
    lookahead = max(1, _safe_int(lookahead, 8))
    for row in scheduled or []:
        if not isinstance(row, dict):
            continue
        turn = _safe_int(row.get("turn"))
        program_id = _safe_int(row.get("program_id"))
        if not turn or not program_id:
            continue
        offset = turn - current_turn
        if offset < 0 or offset > lookahead:
            continue
        hint = normalized.get(program_id)
        if not isinstance(hint, dict):
            continue
        baseline = hint.get("winning_stat_baseline") or {}
        if not isinstance(baseline, dict):
            continue
        urgency = 1.0 - (offset / float(max(1, lookahead)))
        confidence = max(0.25, min(1.0, _safe_float(hint.get("confidence"), 0.5)))
        win_rate = max(0.35, min(1.0, _safe_float(hint.get("win_rate"), 0.0)))
        for key in STAT_KEYS:
            target = _safe_float(baseline.get(key))
            if target <= 0:
                continue
            deficit = target - _safe_float(current_stats.get(key))
            if deficit <= 0:
                continue
            demand[key] += deficit * urgency * confidence * win_rate
    return dict(demand)


def empirical_success_viability(hint, current_stats, running_style=None, tolerance=0.94):
    """Return whether `current_stats` satisfy a historically successful low-cost
    win profile for this race.

    This is the key bridge from "the bot won once with a weird but valid stat
    shape" to "the bot should remember that this profile is viable next time".
    If a race has been won before with a cheaper profile, the runtime can stop
    forcing conservative rescue behavior just because the static estimator is
    nervous.
    """
    if not isinstance(hint, dict):
        return {"viable": False}
    profiles = hint.get("efficient_win_profiles_by_style") or {}
    style_key = str(running_style or "").strip()
    profile = None
    if style_key and style_key in profiles:
        profile = profiles.get(style_key)
    if not profile:
        profile = hint.get("efficient_win_profile") or {}
    if not isinstance(profile, dict):
        return {"viable": False}
    profile_stats = profile.get("stats_at_race") or {}
    if not isinstance(profile_stats, dict) or not profile_stats:
        return {"viable": False}
    deficits = {}
    max_ratio = 0.0
    for key, required in profile_stats.items():
        required_value = _safe_float(required)
        if required_value <= 0:
            continue
        current_value = _safe_float((current_stats or {}).get(key))
        allowed_min = required_value * max(0.80, min(1.0, tolerance))
        deficit = max(0.0, allowed_min - current_value)
        if deficit > 0:
            deficits[key] = round(deficit, 2)
            max_ratio = max(max_ratio, deficit / max(1.0, required_value))
    return {
        "viable": not deficits,
        "profile": dict(profile),
        "deficits": deficits,
        "max_relative_deficit": round(max_ratio, 4),
    }


def _race_effort_score(stats, skill_count_at_race):
    total_stats = sum(max(0.0, _safe_float((stats or {}).get(key))) for key in STAT_KEYS)
    skill_cost = max(0, _safe_int(skill_count_at_race)) * 120.0
    return total_stats + skill_cost


def _iter_race_results(sample):
    for row in sample.get("race_results") or []:
        if isinstance(row, dict):
            yield row
    turns = sample.get("turns") or []
    if isinstance(turns, list):
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            for row in turn.get("events") or []:
                if isinstance(row, dict) and row.get("event") == "race_result":
                    yield row


def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default
