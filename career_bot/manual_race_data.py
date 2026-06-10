"""Per-(trainee, race) lookup built from manual hachimi captures.

The existing learning pipeline uses manual captures to derive
feature-weight policies (e.g., "training X with Y partners tends to
score higher"). But it does NOT build a per-race lookup — for a given
trainee + race, what stats / skills / style did the user have when
they won?

This module fills that gap. It walks every per-turn snapshot in every
hachimi capture (including partials — they have valid per-race state
even if the career didn't finish) and emits:

  {
    "<card_id>": {
      "<program_id>": {
        "race_name": str,
        "wins": int,
        "losses": int,
        "win_attempts": [
          {
            "career_key": str,
            "turn": int,
            "running_style": int,
            "raw_stats": {speed, stamina, power, guts, wit, skill_point},
            "skill_count": int,
            "skill_ids": [int, ...],
          }
        ],
        "median_winning_stats": {stat: int},
        "median_winning_skill_count": int,
        "skill_id_frequency": {skill_id: count_in_wins},
        "winning_running_styles": {style: count},
      }
    }
  }

Used by the runtime to inform pre-race prebuy decisions
("for Mihono at Kikuka Sho, user's wins had skills X/Y/Z") and
cap-pursuit targets ("for trainee N, user's wins averaged speed=1200").
"""

import json
import re
from collections import defaultdict
from pathlib import Path
from statistics import median


CARD_ID_PATTERN = re.compile(r"card(\d+)")
SUMMARY_FILENAME = "latest_summary.json"
SCHEMA = "sweepy_manual_race_data_v1"


def _safe_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _extract_card_id_from_dirname(name):
    """Parse `card102602` out of `Mihono_Bourbon_Valentine_used_at_..._card102602_chara778`."""
    match = CARD_ID_PATTERN.search(name)
    if match:
        return int(match.group(1))
    return None


def _list_items(field):
    """Hachimi capture's typed array helper. Returns the `$items` list
    or the field itself if it's already a list/empty."""
    if isinstance(field, list):
        return field
    if isinstance(field, dict):
        items = field.get("$items")
        if isinstance(items, list):
            return items
    return []


def _race_history_for_career(career_dir):
    """Read the top-level latest_summary.json's race history."""
    summary_path = career_dir / SUMMARY_FILENAME
    if not summary_path.exists():
        return []
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    races = data.get("races") or {}
    history = races.get("history") or {}
    items = _list_items(history)
    return [r for r in items if isinstance(r, dict)]


def _per_turn_snapshot(career_dir, turn):
    """Read the per-turn snapshot at `turn`. Returns the chara/skill state at that turn."""
    turn_dir = career_dir / "turns" / f"turn_{int(turn):02d}"
    summary_path = turn_dir / SUMMARY_FILENAME
    if not summary_path.exists():
        return None
    try:
        return json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _career_final_score(career_dir):
    """Approximate final career score from the latest_summary's stats.

    Hachimi captures don't include rank/score in latest_summary. As a
    proxy, we use total of effective stats (raw + 400 single mode bonus)
    capped at 1200 per stat. This roughly correlates with the in-game
    rank score for parent-farming purposes.

    Returns (proxy_score, final_turn) or (0, 0) if data missing.
    """
    summary_path = career_dir / SUMMARY_FILENAME
    if not summary_path.exists():
        return 0, 0
    try:
        data = json.loads(summary_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0, 0
    cur = data.get("current") or {}
    final_turn = _safe_int(cur.get("turn"))
    # Stat-based proxy score: sum of effective stats capped at 1200.
    total = 0
    for stat in ("speed", "stamina", "power", "guts", "wit"):
        raw = _safe_int(cur.get(stat))
        effective = min(raw + 400, 1200) if raw > 0 else 0
        total += effective
    # SP-spent proxy adds modest bonus
    sp = _safe_int(cur.get("skill_point"))
    # Roughly: skill_point at end suggests SP spent if low
    return total, final_turn


def _race_meta_lookup(base_dir):
    """Build a program_id → race_name lookup from data/race_map.json,
    matching the format learning_references() uses."""
    path = Path(base_dir) / "data" / "race_map.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    by_pid = {}
    meta = data.get("meta") if isinstance(data, dict) else None
    if isinstance(meta, dict):
        for key, entry in meta.items():
            if not isinstance(entry, dict):
                continue
            pid = _safe_int(entry.get("program_id"))
            if pid and pid not in by_pid:
                by_pid[pid] = entry.get("name") or ""
    return by_pid


def extract_manual_race_data(hachimi_root, base_dir=None):
    """Walk every hachimi capture and emit per-(card_id, program_id) lookups.

    Args:
        hachimi_root: Path to "Career turn data/" directory.
        base_dir: Optional project root for race name lookups.

    Returns: dict matching the module docstring schema.
    """
    root = Path(hachimi_root)
    if not root.exists():
        return {}

    race_names = _race_meta_lookup(base_dir or Path(".")) if base_dir else {}

    # Find all career dirs (top-level OR under known subdirs).
    SUBDIRS = ("SPD", "STAM", "PWR", "GUTS", "WIT", "BALANCED", "UNKNOWN", "Unlabelled runs")
    career_dirs = []
    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        if entry.name in SUBDIRS:
            for sub in entry.iterdir():
                if sub.is_dir():
                    career_dirs.append(sub)
        else:
            # Top-level career
            if (entry / SUMMARY_FILENAME).exists():
                career_dirs.append(entry)

    by_card = defaultdict(lambda: defaultdict(lambda: {
        "race_name": "",
        "wins": 0,
        "losses": 0,
        "win_attempts": [],
        "loss_attempts": [],
        "winning_running_styles": defaultdict(int),
        "_skill_id_frequency": defaultdict(int),
        "_winning_stats": defaultdict(list),
        "_winning_skill_counts": [],
    }))

    for career_dir in career_dirs:
        card_id = _extract_card_id_from_dirname(career_dir.name)
        if not card_id:
            continue
        # Compute career-final stat-sum (proxy for rank/score)
        career_score, career_final_turn = _career_final_score(career_dir)
        race_history = _race_history_for_career(career_dir)
        for race in race_history:
            pid = _safe_int(race.get("program_id"))
            if not pid:
                continue
            turn = _safe_int(race.get("turn"))
            rank = _safe_int(race.get("result_rank"), 0)
            style = _safe_int(race.get("running_style"))

            # Snapshot at the race's turn to read stats + skills
            snapshot = _per_turn_snapshot(career_dir, turn) if turn > 0 else None
            stats = {}
            skill_ids = []
            if isinstance(snapshot, dict):
                cur = snapshot.get("current") or {}
                stats = {k: _safe_int(cur.get(k)) for k in ("speed", "stamina", "power", "guts", "wit", "skill_point")}
                skills = snapshot.get("skills") or {}
                bought = skills.get("bought") or {}
                skill_items = _list_items(bought)
                for item in skill_items:
                    if isinstance(item, dict):
                        sid = _safe_int(item.get("skill_id"))
                        if sid:
                            skill_ids.append(sid)

            entry = by_card[card_id][pid]
            if not entry["race_name"] and pid in race_names:
                entry["race_name"] = race_names[pid]

            attempt = {
                "career_key": career_dir.name,
                "turn": turn,
                "running_style": style,
                "raw_stats": stats,
                "skill_count": len(skill_ids),
                "skill_ids": skill_ids,
                # Career-level stat-sum (proxy for final rank). Lets
                # downstream aggregation filter to high-quality wins.
                "career_stat_sum": career_score,
                "career_final_turn": career_final_turn,
            }

            if rank == 1:
                entry["wins"] += 1
                entry["win_attempts"].append(attempt)
                entry["winning_running_styles"][style] += 1
                for sid in skill_ids:
                    entry["_skill_id_frequency"][sid] += 1
                for stat, value in stats.items():
                    if value > 0:
                        entry["_winning_stats"][stat].append(value)
                entry["_winning_skill_counts"].append(len(skill_ids))
            elif rank > 1:
                entry["losses"] += 1
                entry["loss_attempts"].append(attempt)

    # Materialize aggregates.
    # Record the median TURN of winning attempts per race so downstream
    # aggregation can weight late-career races more heavily — a Senior
    # G1 (turn 70+) is a much better stat-target signal than a Junior
    # debut race (turn 14).
    result = {}
    for card_id, races in by_card.items():
        result[str(card_id)] = {}
        for pid, entry in races.items():
            median_stats = {}
            for stat, values in entry["_winning_stats"].items():
                if values:
                    median_stats[stat] = int(median(values))
            median_skill_count = int(median(entry["_winning_skill_counts"])) if entry["_winning_skill_counts"] else 0
            # Median turn across winning attempts — used for late-career filtering downstream
            win_turns = [a.get("turn", 0) for a in entry["win_attempts"] if a.get("turn", 0) > 0]
            median_win_turn = int(median(win_turns)) if win_turns else 0
            # Top skill_ids by frequency
            sorted_skills = sorted(entry["_skill_id_frequency"].items(), key=lambda x: -x[1])
            top_skills = [
                {"skill_id": sid, "win_count": count}
                for sid, count in sorted_skills[:15]
            ]
            result[str(card_id)][str(pid)] = {
                "race_name": entry["race_name"],
                "wins": entry["wins"],
                "losses": entry["losses"],
                "win_attempts": entry["win_attempts"][-10:],  # last 10 wins (keeps file size manageable)
                "median_winning_stats": median_stats,
                "median_winning_skill_count": median_skill_count,
                "median_winning_turn": median_win_turn,
                "top_winning_skills": top_skills,
                "winning_running_styles": dict(entry["winning_running_styles"]),
            }
    return result


def write_manual_race_data(runtime_root, data):
    """Persist the extracted lookup to disk."""
    from datetime import datetime, timezone
    path = Path(runtime_root) / "manual_race_data.json"
    payload = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "card_count": len(data),
        "race_count": sum(len(races) for races in data.values()),
        "data": data,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def load_manual_race_data(runtime_root):
    """Return the cached lookup or {} if missing."""
    path = Path(runtime_root) / "manual_race_data.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload.get("data") or {}


def lookup_race(manual_race_data, card_id, program_id):
    """Return the per-race lookup entry or None."""
    card_section = (manual_race_data or {}).get(str(card_id))
    if not isinstance(card_section, dict):
        return None
    return card_section.get(str(program_id))


# Set of trainee card_ids whose unique skills provide stamina recovery.
# When aggregating stamina targets across trainees, wins by these
# trainees should be excluded for trainees that LACK the same unique —
# their stamina ceiling is artificially low because the unique
# substitutes for raw stamina.
#
# Sourced from career_bot/unique_race_modifiers.py:_UNIQUE_RACE_PROFILES.
# Listed inline to avoid circular import.
STAMINA_RECOVERY_UNIQUE_CARDS = frozenset({
    103201,  # Agnes Tachyon
    104501, 104502, 104503,  # Super Creek (all variants)
    100102,  # Special Week (Summer)
    101102,  # Grass Wonder (Fantasy)
    102301, 102302, 102303,  # Biwa Hayahide (all variants)
    102402,  # Mayano Top Gun (Wedding) - stamina pressure
    107401, 107402,  # Mejiro Bright (all variants)
})


def _turn_weight(turn):
    """Weight a race's contribution to stat-target aggregation by its
    turn in the career. Early races (turn < 30) get weight 0.2,
    mid-career (30-50) gets 0.6, late career (50+) gets weight 1.0
    or higher. The 'what stats win' signal lives in the late races —
    early races have low absolute stats and dilute the median if
    weighted equally.
    """
    t = int(turn or 0)
    if t < 20:
        return 0.1
    if t < 40:
        return 0.3
    if t < 55:
        return 0.6
    if t < 70:
        return 1.0
    return 1.4  # Senior G1s and finals: dominant weight


HIGH_QUALITY_CAREER_STAT_SUM_FLOOR = 4400  # ~SS rank stat total proxy


def aggregate_user_targets_for_trainee(manual_race_data, card_id, *, min_wins=3, high_quality_only=True):
    """Aggregate winning stats across races for one trainee, weighted
    by race turn AND by career quality.

    When `high_quality_only=True`, we use the `win_attempts` raw stats
    (which include career_stat_sum) and filter to wins whose career
    landed at SS+/UG-tier stat totals (≥ HIGH_QUALITY_CAREER_STAT_SUM_FLOOR).
    This stops the bot from regressing toward average-career stats.

    Returns dict {stat: target_value} or {}.
    """
    section = (manual_race_data or {}).get(str(card_id))
    if not isinstance(section, dict):
        return {}
    from collections import defaultdict
    from statistics import median as _median

    stat_buckets = defaultdict(list)
    total_qualified_wins = 0

    if high_quality_only:
        # Walk the per-attempt list (last 10 per race) and filter by
        # career_stat_sum. The attempt's raw_stats reflect the user's
        # stats at race time.
        for race_entry in section.values():
            if not isinstance(race_entry, dict):
                continue
            for attempt in race_entry.get("win_attempts") or []:
                if not isinstance(attempt, dict):
                    continue
                career_sum = int(attempt.get("career_stat_sum") or 0)
                if career_sum < HIGH_QUALITY_CAREER_STAT_SUM_FLOOR:
                    continue
                turn = int(attempt.get("turn") or 0)
                weight = max(1, int(round(_turn_weight(turn) * 10)))
                stats = attempt.get("raw_stats") or {}
                contributed = False
                for stat in ("speed", "stamina", "power", "guts", "wit"):
                    v = stats.get(stat)
                    if v:
                        stat_buckets[stat].extend([int(v)] * weight)
                        contributed = True
                if contributed:
                    total_qualified_wins += 1
        if total_qualified_wins >= min_wins:
            return {stat: int(_median(vals)) for stat, vals in stat_buckets.items() if vals}
        # Fall back to all-wins aggregation when high-quality data is sparse.

    # Fallback / non-filtered: use per-race medians weighted by turn.
    total_wins = 0
    for race_entry in section.values():
        if not isinstance(race_entry, dict):
            continue
        wins = int(race_entry.get("wins") or 0)
        if wins <= 0:
            continue
        total_wins += wins
        medians = race_entry.get("median_winning_stats") or {}
        median_turn = int(race_entry.get("median_winning_turn") or 0)
        weight = max(1, int(round(_turn_weight(median_turn) * wins * 10)))
        for stat in ("speed", "stamina", "power", "guts", "wit"):
            v = medians.get(stat)
            if v:
                stat_buckets[stat].extend([int(v)] * weight)
    if total_wins < min_wins:
        return {}
    return {stat: int(_median(vals)) for stat, vals in stat_buckets.items() if vals}


def aggregate_user_targets_by_attributes(
    manual_race_data,
    *,
    style=None,
    distance_focus=None,
    current_trainee_card_id=None,
    current_trainee_has_recovery_unique=False,
    min_wins=3,
    high_quality_only=True,
):
    """Aggregate winning stats across ALL trainees that match the given
    style/distance attributes. Used as fallback when the current trainee
    has no/few manual wins.

    Args:
        manual_race_data: data dict from load_manual_race_data.
        style: numeric running style (1=front, 2=pace, 3=late, 4=end)
            OR string ("front_runner", etc.). Matches winning style.
        distance_focus: optional string ("sprint", "mile", "medium", "long").
            Currently used as soft signal — matches race attributes.
        current_trainee_card_id: ID of trainee we're computing targets for.
        current_trainee_has_recovery_unique: if True, INCLUDE wins from
            other recovery-unique trainees (they're equivalent). If False,
            EXCLUDE those wins from stamina aggregation (stamina target
            would be artificially low otherwise).
        min_wins: minimum total winning attempts before returning targets.

    Returns dict {stat: median_winning_value} or {} on insufficient data.
    """
    if not manual_race_data:
        return {}

    # Normalize style to numeric
    style_aliases = {
        "front_runner": 1, "front": 1, "nige": 1,
        "pace_chaser": 2, "pace": 2, "senko": 2,
        "late_surger": 3, "late": 3, "sashi": 3,
        "end_closer": 4, "end": 4, "oikomi": 4,
    }
    target_style_int = None
    if isinstance(style, int):
        target_style_int = style
    elif isinstance(style, str):
        target_style_int = style_aliases.get(style.strip().lower())

    from collections import defaultdict
    from statistics import median as _median

    stat_buckets = defaultdict(list)
    total_wins = 0

    if high_quality_only:
        # Walk per-attempt list, filter by career_stat_sum, style, recovery-unique.
        for card_id_str, races in manual_race_data.items():
            if not isinstance(races, dict):
                continue
            try:
                card_id = int(card_id_str)
            except (TypeError, ValueError):
                continue
            if current_trainee_card_id and card_id == int(current_trainee_card_id):
                continue
            source_has_recovery_unique = card_id in STAMINA_RECOVERY_UNIQUE_CARDS
            for race_entry in races.values():
                if not isinstance(race_entry, dict):
                    continue
                for attempt in race_entry.get("win_attempts") or []:
                    if not isinstance(attempt, dict):
                        continue
                    career_sum = int(attempt.get("career_stat_sum") or 0)
                    if career_sum < HIGH_QUALITY_CAREER_STAT_SUM_FLOOR:
                        continue
                    # Style filter
                    if target_style_int is not None:
                        if int(attempt.get("running_style") or 0) != target_style_int:
                            continue
                    turn = int(attempt.get("turn") or 0)
                    weight = max(1, int(round(_turn_weight(turn) * 10)))
                    stats = attempt.get("raw_stats") or {}
                    contributed = False
                    for stat in ("speed", "stamina", "power", "guts", "wit"):
                        v = stats.get(stat)
                        if not v:
                            continue
                        if (
                            stat == "stamina"
                            and source_has_recovery_unique
                            and not current_trainee_has_recovery_unique
                        ):
                            continue
                        stat_buckets[stat].extend([int(v)] * weight)
                        contributed = True
                    if contributed:
                        total_wins += 1
        if total_wins >= min_wins:
            return {stat: int(_median(vals)) for stat, vals in stat_buckets.items() if vals}
        # Fall back to non-filtered when high-quality data is too sparse.
        stat_buckets = defaultdict(list)
        total_wins = 0

    # Non-filtered fallback: per-race medians weighted by turn.
    for card_id_str, races in manual_race_data.items():
        if not isinstance(races, dict):
            continue
        try:
            card_id = int(card_id_str)
        except (TypeError, ValueError):
            continue
        if current_trainee_card_id and card_id == int(current_trainee_card_id):
            continue

        source_has_recovery_unique = card_id in STAMINA_RECOVERY_UNIQUE_CARDS

        for race_entry in races.values():
            if not isinstance(race_entry, dict):
                continue
            wins = int(race_entry.get("wins") or 0)
            if wins <= 0:
                continue

            # Style filter: if target style specified, only include races
            # where the source trainee won with the SAME running style.
            if target_style_int is not None:
                styles = race_entry.get("winning_running_styles") or {}
                style_match_count = 0
                for k, v in styles.items():
                    try:
                        if int(k) == target_style_int:
                            style_match_count += int(v)
                    except (TypeError, ValueError):
                        continue
                if style_match_count <= 0:
                    continue
                effective_wins = style_match_count
            else:
                effective_wins = wins

            total_wins += effective_wins
            medians = race_entry.get("median_winning_stats") or {}
            median_turn = int(race_entry.get("median_winning_turn") or 0)
            weight = max(1, int(round(_turn_weight(median_turn) * effective_wins * 10)))
            for stat in ("speed", "stamina", "power", "guts", "wit"):
                v = medians.get(stat)
                if not v:
                    continue
                if (
                    stat == "stamina"
                    and source_has_recovery_unique
                    and not current_trainee_has_recovery_unique
                ):
                    continue
                stat_buckets[stat].extend([int(v)] * weight)

    if total_wins < min_wins:
        return {}
    return {stat: int(_median(vals)) for stat, vals in stat_buckets.items() if vals}


def aggregate_race_specific_targets(
    manual_race_data,
    program_id,
    *,
    current_trainee_card_id=None,
    current_trainee_has_recovery_unique=False,
    style=None,
    min_wins=2,
):
    """Aggregate median winning stats for ONE specific race (program_id)
    across all user trainees that won that race.

    This is the per-race counterpart to `aggregate_user_targets_by_attributes`.
    Where the latter collapses winning stats across all of a trainee's races,
    this preserves the race-specific signal — Kikuka Sho's stamina target
    won't get diluted by Mile race stat profiles.

    Resolution order:
    1. Exact card_id match: if the current trainee has wins on this race,
       return their median directly.
    2. Cross-trainee aggregation for this program_id, optionally filtered
       by running style. Wins by stamina-recovery-unique trainees are
       excluded from the stamina aggregation when the current trainee
       lacks the same unique.

    Returns dict {stat: median_winning_value} with optional
    `_source` ("exact" or "cross_trainee") and `_win_count` keys,
    or {} on insufficient data.
    """
    if not manual_race_data or not program_id:
        return {}

    pid_str = str(program_id)
    from collections import defaultdict
    from statistics import median as _median

    # Tier 1: exact card_id match for this specific race
    if current_trainee_card_id is not None:
        card_section = manual_race_data.get(str(current_trainee_card_id))
        if isinstance(card_section, dict):
            race_entry = card_section.get(pid_str)
            if isinstance(race_entry, dict):
                wins = int(race_entry.get("wins") or 0)
                medians = race_entry.get("median_winning_stats") or {}
                if wins > 0 and medians:
                    result = {
                        stat: int(medians[stat])
                        for stat in ("speed", "stamina", "power", "guts", "wit")
                        if medians.get(stat)
                    }
                    if result:
                        result["_source"] = "exact"
                        result["_win_count"] = wins
                        return result

    # Tier 2: cross-trainee aggregation for this program_id
    style_aliases = {
        "front_runner": 1, "front": 1, "nige": 1,
        "pace_chaser": 2, "pace": 2, "senko": 2,
        "late_surger": 3, "late": 3, "sashi": 3,
        "end_closer": 4, "end": 4, "oikomi": 4,
    }
    target_style_int = None
    if isinstance(style, int):
        target_style_int = style
    elif isinstance(style, str):
        target_style_int = style_aliases.get(style.strip().lower())

    stat_buckets = defaultdict(list)
    total_wins = 0
    for card_id_str, races in manual_race_data.items():
        if not isinstance(races, dict):
            continue
        try:
            source_card_id = int(card_id_str)
        except (TypeError, ValueError):
            continue
        if current_trainee_card_id and source_card_id == int(current_trainee_card_id):
            continue
        race_entry = races.get(pid_str)
        if not isinstance(race_entry, dict):
            continue
        wins = int(race_entry.get("wins") or 0)
        if wins <= 0:
            continue

        if target_style_int is not None:
            styles = race_entry.get("winning_running_styles") or {}
            style_match = 0
            for k, v in styles.items():
                try:
                    if int(k) == target_style_int:
                        style_match += int(v)
                except (TypeError, ValueError):
                    continue
            if style_match <= 0:
                continue
            effective_wins = style_match
        else:
            effective_wins = wins

        source_has_recovery_unique = source_card_id in STAMINA_RECOVERY_UNIQUE_CARDS
        medians = race_entry.get("median_winning_stats") or {}
        weight = max(1, effective_wins)
        contributed = False
        for stat in ("speed", "stamina", "power", "guts", "wit"):
            v = medians.get(stat)
            if not v:
                continue
            if (
                stat == "stamina"
                and source_has_recovery_unique
                and not current_trainee_has_recovery_unique
            ):
                continue
            stat_buckets[stat].extend([int(v)] * weight)
            contributed = True
        if contributed:
            total_wins += effective_wins

    if total_wins < min_wins:
        return {}
    result = {stat: int(_median(vals)) for stat, vals in stat_buckets.items() if vals}
    if result:
        result["_source"] = "cross_trainee"
        result["_win_count"] = total_wins
    return result
