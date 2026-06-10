"""Session objective interpretation and outcome classification.

Centers on a single design principle: REWARD CONDITIONS, NOT OUTCOMES.

Spark color and star RNG within a band are uncontrollable. The bot can't
make a 3-star Wit blue appear by playing better — it can only set up the
conditions (stat value >= 1100, lineage matches, rank score band) that
make a 3-star Wit blue *possible*. Scoring careers on outcomes within
those bands would just teach the bot to chase luck, which is unteachable.

So this module's classification and intent_aware_score reward hitting
the empirical thresholds documented in spark_rates.py — getting to the
20/70/10 star band for blue, the 17500+ score band for whites, the
1.1^lineage_count generation rate — and treat "all conditions met but
RNG was unkind" as still-strong training signal (the 1.45 multiplier).
"""

from career_bot.spark_rates import (
    expected_blue_star_distribution,
    expected_white_generation_rate,
    expected_white_star_distribution,
    rank_score_band,
    stat_value_band,
)


STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")
_STAT_ALIASES = {
    "speed": "speed",
    "spd": "speed",
    "stamina": "stamina",
    "stam": "stamina",
    "sta": "stamina",
    "power": "power",
    "pwr": "power",
    "pow": "power",
    "guts": "guts",
    "gut": "guts",
    "wit": "wit",
    "wis": "wit",
    "wiz": "wit",
}
_STYLE_ALIASES = {
    "front_runner": "front_runner",
    "front": "front_runner",
    "nige": "front_runner",
    "pace_chaser": "pace_chaser",
    "pace": "pace_chaser",
    "senko": "pace_chaser",
    "late_surger": "late_surger",
    "late": "late_surger",
    "sashi": "late_surger",
    "end_closer": "end_closer",
    "end": "end_closer",
    "closer": "end_closer",
    "oikomi": "end_closer",
}
_SPARK_GOAL_ALIASES = {
    "red": "pink",
    "aptitude": "pink",
    "stat": "blue",
    "unique": "green",
    "skill": "white",
    "race": "white",
    "scenario": "white",
}


DEFAULT_SESSION = {
    "session_id": "default_balanced",
    "primary_stat_target": {"stat": None, "target_value": None, "ideal_value": None},
    "blue_spark_intent": {
        "preferred_color": None,
        "acceptable_colors": list(STAT_KEYS),
        "minimum_star_level": 1,
    },
    "white_spark_intent": {
        "minimum_count": 0,
        "high_value_targets": [],
        "preferred_targets_from_schedule": [],
        "target_rank_score_band": "mid",
    },
    "stat_minimums": {stat: 0 for stat in STAT_KEYS},
    "race_intent": {
        "treat_wins_as_negative": False,
        "require_clean_record": False,
        "expected_losses": [],
        "must_win": [],
    },
    "lineage_intent": {
        "target_affinity_tier": "any",
        "lineage_overlap_targets": [],
    },
    "acceptable_drift": [],
    "deck_id": None,
    # Style being optimized for (front_runner / pace_chaser / late_surger /
    # end_closer). Used by the loader's stat-folder routing and by future
    # style-aware skill-priority adjustments. Optional — None means
    # "no explicit style preference for this run".
    "style_target": None,
    # Operator notes for free-form context. Survives normalization so the
    # quick_declare endpoint can attach a comment without losing it.
    "operator_notes": "",
}


def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_parent_goals(value):
    if not isinstance(value, dict):
        return {"blue": [], "pink": [], "green": [], "white": []}
    goals = {"blue": [], "pink": [], "green": [], "white": []}
    for raw_key, raw_value in value.items():
        key = _SPARK_GOAL_ALIASES.get(
            str(raw_key or "").strip().lower(),
            str(raw_key or "").strip().lower(),
        )
        if key not in goals:
            continue
        parts = raw_value if isinstance(raw_value, list) else str(raw_value or "").replace(",", "\n").splitlines()
        seen = set()
        for part in parts:
            text = str(part or "").strip()
            folded = text.lower()
            if not text or folded in seen:
                continue
            seen.add(folded)
            goals[key].append(text)
    return goals


def _normalize_stat_name(raw):
    return _STAT_ALIASES.get(str(raw or "").strip().lower())


def _normalize_style_name(raw):
    return _STYLE_ALIASES.get(str(raw or "").strip().lower())


def normalize_session(session):
    """Fill in defaults for missing fields. Idempotent."""
    if not isinstance(session, dict):
        return _deepcopy_default()
    out = _deepcopy_default()
    for key, default_value in DEFAULT_SESSION.items():
        provided = session.get(key)
        if isinstance(default_value, dict) and isinstance(provided, dict):
            merged = dict(default_value)
            merged.update(provided)
            out[key] = merged
        elif provided is not None:
            out[key] = provided
    out["session_id"] = session.get("session_id") or "default_balanced"
    return out


def _deepcopy_default():
    return {
        "session_id": DEFAULT_SESSION["session_id"],
        "primary_stat_target": dict(DEFAULT_SESSION["primary_stat_target"]),
        "blue_spark_intent": dict(DEFAULT_SESSION["blue_spark_intent"]),
        "white_spark_intent": dict(DEFAULT_SESSION["white_spark_intent"]),
        "stat_minimums": dict(DEFAULT_SESSION["stat_minimums"]),
        "race_intent": dict(DEFAULT_SESSION["race_intent"]),
        "lineage_intent": dict(DEFAULT_SESSION["lineage_intent"]),
        "acceptable_drift": list(DEFAULT_SESSION["acceptable_drift"]),
        "deck_id": DEFAULT_SESSION["deck_id"],
        "style_target": DEFAULT_SESSION["style_target"],
        "operator_notes": DEFAULT_SESSION["operator_notes"],
    }


def session_from_career_log(career_log):
    """Extract the learning_session object from a career log or manifest.

    Looks in three places, in order:
      1. career_log["learning_metadata"]["session"] (attached at load time)
      2. career_log["manifest"]["learning_session"] (hachimi capture embed)
      3. career_log["learning_session"] (top-level fallback)
    Falls back to the default balanced session if nothing is found.
    """
    if not isinstance(career_log, dict):
        return _deepcopy_default()
    meta = career_log.get("learning_metadata") or {}
    if meta.get("session"):
        return normalize_session(meta["session"])
    manifest = career_log.get("manifest") or {}
    session = manifest.get("learning_session") or career_log.get("learning_session")
    return normalize_session(session)


def session_from_parent_farming_targets(
    desired_parent_sparks=None,
    style_target=None,
    session_id=None,
    notes=None,
    white_rank_score_band="high",
):
    """Build a normalized parent-farming session from preset/run spark goals.

    Returns None when the input does not declare a valid blue stat target.
    The first recognized blue goal becomes the primary stat target; any
    desired white spark names are carried into `high_value_targets`.
    """
    goals = _normalize_parent_goals(desired_parent_sparks)
    normalized_blue_targets = []
    seen_stats = set()
    for raw in goals.get("blue") or []:
        stat = _normalize_stat_name(raw)
        if not stat or stat in seen_stats:
            continue
        seen_stats.add(stat)
        normalized_blue_targets.append(stat)
    if not normalized_blue_targets:
        return None

    preferred_stat = normalized_blue_targets[0]
    acceptable_colors = list(normalized_blue_targets[1:])
    for stat in STAT_KEYS:
        if stat == preferred_stat or stat in acceptable_colors:
            continue
        acceptable_colors.append(stat)

    style = _normalize_style_name(style_target)
    target_rank_band = str(white_rank_score_band or "high").strip().lower() or "high"
    if target_rank_band not in {"low", "mid", "high"}:
        target_rank_band = "high"
    if not session_id:
        style_slug = style or "any"
        session_id = f"preset_parent_{preferred_stat}_{style_slug}"

    session = {
        "session_id": session_id,
        "operator_notes": notes or "",
        "primary_stat_target": {
            "stat": preferred_stat,
            "target_value": 1100,
            "ideal_value": 1180,
        },
        "blue_spark_intent": {
            "preferred_color": preferred_stat,
            "acceptable_colors": acceptable_colors,
            "minimum_star_level": 2,
        },
        "white_spark_intent": {
            "minimum_count": 6,
            "high_value_targets": list(goals.get("white") or []),
            "preferred_targets_from_schedule": [],
            "target_rank_score_band": target_rank_band,
        },
        "stat_minimums": {
            "speed": 600,
            "stamina": 500,
            "power": 600,
            "guts": 400,
            "wit": 500,
        },
        "race_intent": {
            "treat_wins_as_negative": False,
            "require_clean_record": True,
            "expected_losses": [],
            "must_win": [],
        },
        "lineage_intent": {
            "target_affinity_tier": "high",
            "lineage_overlap_targets": [],
        },
        "acceptable_drift": ["balanced_parent_with_wrong_blue"],
        "deck_id": None,
        "style_target": style,
    }
    session["stat_minimums"][preferred_stat] = 1100
    return normalize_session(session)


def classify_outcome(final_stats, final_sparks, race_results, rank_score, session):
    """Multi-dimensional outcome classification.

    Returns a dict with per-dimension assessment AND an overall label.
    Assessment is CONDITION-BASED — did the run achieve the prerequisites
    that the empirical tables show drive good outcomes — rather than
    outcome-based, because color/star RNG within a band is uncontrollable.

    final_stats: dict of stat_key -> int
    final_sparks: list of {type, name, star_level} dicts
                  (type in {"blue", "pink", "green", "white"})
    race_results: list of {race_id, result, turn} dicts
    rank_score: int, the career's final rank score
    session: dict (will be normalized)
    """
    session = normalize_session(session)
    final_stats = final_stats or {}
    final_sparks = final_sparks or []
    race_results = race_results or []

    assessment = {
        "primary_stat_value_band": None,
        "primary_stat_hit_target": False,
        "primary_stat_hit_ideal": False,
        "blue_color_intent_hit": False,
        "blue_color_alternative_hit": False,
        "blue_star_actual": 0,
        "white_count_actual": 0,
        "white_count_hit_min": False,
        "white_high_value_count": 0,
        "rank_score_band": rank_score_band(rank_score),
        "rank_score_band_matches_intent": False,
        "stat_minimums_hit": True,
        "race_intent_aligned": True,
        "race_loss_count": 0,
        "overall": "unknown",
    }

    primary = session["primary_stat_target"]
    primary_stat = primary.get("stat")
    if primary_stat:
        actual_value = _safe_int(final_stats.get(primary_stat), 0)
        assessment["primary_stat_value_band"] = stat_value_band(actual_value)
        target_value = primary.get("target_value")
        if target_value and actual_value >= _safe_int(target_value):
            assessment["primary_stat_hit_target"] = True
        ideal_value = primary.get("ideal_value")
        if ideal_value and actual_value >= _safe_int(ideal_value):
            assessment["primary_stat_hit_ideal"] = True

    blue_intent = session["blue_spark_intent"]
    blue_sparks = [s for s in final_sparks if isinstance(s, dict) and s.get("type") == "blue"]
    if blue_sparks:
        best_blue = max(blue_sparks, key=lambda s: _safe_int(s.get("star_level"), 0))
        assessment["blue_star_actual"] = _safe_int(best_blue.get("star_level"), 0)
        spark_color = str(best_blue.get("name") or "").lower()
        preferred = str(blue_intent.get("preferred_color") or "").lower()
        alternatives = [str(a or "").lower() for a in blue_intent.get("acceptable_colors", [])]
        if preferred and spark_color == preferred:
            assessment["blue_color_intent_hit"] = True
        elif spark_color in alternatives:
            assessment["blue_color_alternative_hit"] = True

    white_intent = session["white_spark_intent"]
    white_sparks = [s for s in final_sparks if isinstance(s, dict) and s.get("type") == "white"]
    assessment["white_count_actual"] = len(white_sparks)
    assessment["white_count_hit_min"] = (
        len(white_sparks) >= _safe_int(white_intent.get("minimum_count"), 0)
    )
    high_value_targets = {str(t or "").lower() for t in white_intent.get("high_value_targets", [])}
    assessment["white_high_value_count"] = sum(
        1 for s in white_sparks
        if str(s.get("name") or "").lower() in high_value_targets
    )
    target_band = str(white_intent.get("target_rank_score_band") or "mid").lower()
    actual_band = assessment["rank_score_band"]
    assessment["rank_score_band_matches_intent"] = (
        actual_band == target_band
        or (target_band == "mid" and actual_band in ("mid", "high"))
        or (target_band == "high" and actual_band == "high")
    )

    stat_minimums = session["stat_minimums"]
    for stat, min_value in stat_minimums.items():
        if _safe_int(final_stats.get(stat), 0) < _safe_int(min_value, 0):
            assessment["stat_minimums_hit"] = False
            break

    race_intent = session["race_intent"]
    race_loss_count = 0
    for race in race_results:
        if not isinstance(race, dict):
            continue
        if race.get("won") is False:
            race_loss_count += 1
            continue
        if str(race.get("result") or "").strip().lower() not in {"", "win"}:
            race_loss_count += 1
            continue
        rank = _safe_int(
            race.get("finish_rank")
            or race.get("rank")
            or race.get("result_rank"),
            0,
        )
        if rank > 1:
            race_loss_count += 1
    assessment["race_loss_count"] = race_loss_count
    if race_intent.get("require_clean_record") and race_loss_count > 0:
        assessment["race_intent_aligned"] = False
    if race_intent.get("treat_wins_as_negative"):
        must_win = {str(r) for r in race_intent.get("must_win", [])}
        missed_must_wins = 0
        for race in race_results:
            if isinstance(race, dict) and str(race.get("race_id") or "") in must_win:
                if race.get("result") != "win":
                    missed_must_wins += 1
        if missed_must_wins > 0:
            assessment["race_intent_aligned"] = False

    primary_ok = assessment["primary_stat_hit_target"]
    minimums_ok = assessment["stat_minimums_hit"]
    races_ok = assessment["race_intent_aligned"]
    score_band_ok = assessment["rank_score_band_matches_intent"]
    in_high_star_band = (assessment["primary_stat_value_band"] == "high")
    drift = {str(d or "").lower() for d in session.get("acceptable_drift", [])}

    if primary_ok and minimums_ok and races_ok and score_band_ok and in_high_star_band:
        if assessment["blue_color_intent_hit"]:
            assessment["overall"] = "objective_success"
        elif assessment["blue_color_alternative_hit"]:
            assessment["overall"] = "alternative_success"
        else:
            if "balanced_parent_with_wrong_blue" in drift:
                assessment["overall"] = "conditions_met_color_whiffed"
            else:
                assessment["overall"] = "partial_success"
    elif primary_ok and minimums_ok and races_ok:
        assessment["overall"] = "partial_success"
    elif minimums_ok and not primary_ok:
        if "ace" in drift:
            assessment["overall"] = "ace_drift"
        else:
            assessment["overall"] = "partial_success"
    else:
        assessment["overall"] = "run_failure"

    return assessment


def objective_bucket_key(session):
    """Bucket key for stratified sampling. (primary_stat, preferred_blue) pair."""
    session = normalize_session(session)
    primary = str(session["primary_stat_target"].get("stat") or "balanced").lower()
    blue_pref = str(session["blue_spark_intent"].get("preferred_color") or "any").lower()
    return f"{primary}_{blue_pref}"


def intent_aware_score(absolute_score, outcome_assessment, base_weight=1.0):
    """Adjust a career's effective weight by conditions achieved, not outcomes.

    The 1.45 multiplier for `conditions_met_color_whiffed` is the load-bearing
    design choice: it says "the bot did everything right, RNG was unkind".
    That's still strong training signal — the conditions are the lever the
    bot controls; the dice are noise. Rewarding conditions teaches the bot
    to be set up for good outcomes. Penalizing color RNG would teach it to
    chase luck.
    """
    outcome_assessment = outcome_assessment or {}
    overall = outcome_assessment.get("overall", "unknown")
    high_value_whites = _safe_int(outcome_assessment.get("white_high_value_count"), 0)
    in_high_blue_band = (outcome_assessment.get("primary_stat_value_band") == "high")
    in_high_score_band = (outcome_assessment.get("rank_score_band") == "high")

    multiplier = 1.0
    if overall == "objective_success":
        multiplier = 1.6
    elif overall == "alternative_success":
        multiplier = 1.5
    elif overall == "conditions_met_color_whiffed":
        multiplier = 1.45
    elif overall in ("acceptable_drift", "ace_drift"):
        multiplier = 1.1
    elif overall == "partial_success":
        multiplier = 0.85
    elif overall == "run_failure":
        multiplier = 0.4

    if in_high_blue_band:
        multiplier *= 1.05
    if in_high_score_band:
        multiplier *= 1.05
    if high_value_whites >= 3:
        multiplier *= 1.15

    base = base_weight if isinstance(base_weight, (int, float)) else 1.0
    return max(0.3, min(2.0, multiplier * base))


__all__ = [
    "DEFAULT_SESSION",
    "STAT_KEYS",
    "classify_outcome",
    "intent_aware_score",
    "normalize_session",
    "objective_bucket_key",
    "session_from_career_log",
    "session_from_parent_farming_targets",
]
