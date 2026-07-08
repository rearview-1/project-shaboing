import copy
import gzip
import hashlib
import json
import math
import os
import statistics
from collections import Counter
from datetime import datetime
from pathlib import Path

from career_bot.items import ITEM_NAMES
from career_bot.career_trajectory_prediction import (
    aggregate_trajectory_centroids,
    stat_curve_from_turns,
)
from career_bot.event_choice_learning import aggregate_event_choices
from career_bot.hp_curve_learning import hp_curve_from_turns, learned_hp_targets
from career_bot.motivation_curve_learning import (
    learned_motivation_thresholds,
    motivation_curve_from_turns,
)
from career_bot.postmortem_feedback import attach_diagnoses, merge_global_signal, race_stat_hints
from career_bot.race_attempt_history import load_history as load_race_attempt_history
from career_bot.race_continue_learning import aggregate_continue_outcomes
from career_bot.race_learning_filters import (
    off_aptitude_dimensions_for_learning,
    sample_chara_aptitudes,
)
from career_bot.race_success_feedback import aggregate_success_by_race, merge_global_success_signal
from career_bot.presets import (
    PresetStore,
    expect_attribute_profile_lookup_keys,
    normalize_preset,
    slugify,
    split_preset_layers,
    support_type_signature,
)
from career_bot.spark_rates import WHITE_STAR_RATES_BY_RANK_SCORE
from career_bot.training_policy import _action_features, _sample_objective_bucket, build_training_policy_model


STAT_KEYS = ["speed", "stamina", "power", "guts", "wit"]
ALL_STAT_KEYS = STAT_KEYS + ["skill_point"]
TRAINING_COMMANDS = {101: 0, 105: 1, 102: 2, 103: 3, 106: 4, 601: 0, 602: 1, 603: 2, 604: 3, 605: 4}
TRAINING_NAMES = ["Speed", "Stamina", "Power", "Guts", "Wit"]
TARGET_TO_STAT = {1: "speed", 2: "stamina", 3: "power", 4: "guts", 5: "wit", 30: "skill_point", 10: "hp"}
SUMMER_CAMP_TURNS = {36, 37, 38, 39, 40, 60, 61, 62, 63, 64}
PROJECT_ROOT = Path(__file__).resolve().parents[1]
SUPPORTED_CAREER_LOG_SCHEMAS = {
    "sweepy_career_log_v0",  # legacy logs without an explicit schema field
    "sweepy_career_log_v1",
}
PREFERRED_STAT_FACTORS = {
    "Speed": 1.05,
    "Stamina": 1.15,
    "Power": 1.25,
    "Guts": 0.75,
    "Wit": 1.00,
}
PREFERRED_APTITUDE_FACTORS = {
    "Turf": 1.10,
    "Mile": 1.10,
    "Medium": 1.15,
    "Long": 1.00,
    "Front Runner": 1.10,
    "Pace Chaser": 0.85,
    "Late Surger": 0.85,
    "End Closer": 0.65,
}
_REFERENCE_CACHE = None
LEARNING_OBJECTIVE_VERSION = "parent_farming_v17"
# Score threshold below which a "top" sample is rejected entirely. Without
# this, the top-25%-of-anything logic happily promotes a 9,000-score
# mediocre career to "top" whenever the rest of the pool is worse, and the
# training-policy model learns to amplify mediocrity.
#
# Default 16,000 is a learning floor, not an acceptance floor. It excludes
# A+/low-S mediocrity but still lets the model learn from high-S/S+ careers
# while a changed deck is climbing toward SS. A 17,500-only filter starves
# new deck/parent/trainee contexts of positive samples, so the policy cannot
# adapt until it has already solved the route.
DEFAULT_TOP_SCORE_FLOOR = 16000
DEFAULT_POLICY_MIN_RANK_SCORE = 15000
DEFAULT_POLICY_MIN_INTERNAL_SCORE = DEFAULT_TOP_SCORE_FLOOR
DEFAULT_POLICY_MIN_STAT_TOTAL = 3300
DEFAULT_POLICY_MIN_ACTIONS = 20
DEFAULT_POLICY_MIN_RACE_TOTAL_FOR_CLEAN_RECORD = 8
DECK_AWARE_TOP_SCORE_FLOORS = {
    3: 17500,  # premium_ssr_heavy: prefer true SS+ samples when available
    2: 17500,  # mixed_ssr_sr:      do not treat non-SS parent outcomes as top samples
    1: 16000,  # sr_heavy:          no A+ "top" samples
    0: 16000,  # r_heavy_baseline:  no A+ "top" samples
}
# Absolute lower bound for the adaptive floor fallback. This is a junk
# filter (aborted/degenerate careers), not a quality bar — the account's
# own score distribution provides the quality bar. Worst FINISHED live
# career observed on 2026-06-12 scored 3.9k; broken ones score near 0.
ADAPTIVE_SCORE_FLOOR_MINIMUM = 4000.0


def adapt_score_floors_to_account(behavior_samples, score_floor, score_floors_by_deck,
                                  *, enabled=True, recent=24, min_bot_samples=8):
    """Lower unreachable score floors to the account's own best quartile.

    The static/empirical deck-aware floors only ever ratchet UP, so an
    account whose careers score below its bucket's bar can never produce
    a top sample — auto-learning then skips on
    `no_top_samples_above_score_floor` for every career, forever
    (observed live 2026-06-12: best bot career 14.3k vs a 17.5k+ floor;
    eight straight careers skipped). Keeping the bar absolute starves
    the loop of exactly the data it needs to climb.

    When NO bot career clears its bucket floor and we have enough bot
    history to judge, fall back to "learn from this account's own best
    work": the 75th percentile of recent finished bot career scores,
    clamped to [R-deck minimum, configured floor]. The philosophy of the
    original gate (train on the best, not mediocre echoes) is preserved —
    the bar is just relative to what this account demonstrably produces.

    Returns (score_floor, score_floors_by_deck, adaptation_report).
    """
    report = {"applied": False, "reason": ""}
    if not enabled:
        report["reason"] = "disabled"
        return score_floor, score_floors_by_deck, report
    bot_rows = []
    for sample in behavior_samples or []:
        if str((sample or {}).get("source") or "").lower() != "bot":
            continue
        if not is_full_career_sample(sample):
            continue
        score = as_float(sample.get("score"))
        if score <= 0:
            continue
        bucket = as_int(sample.get("deck_quality_bucket"), 2)
        details = _sample_observed_details(sample)
        bot_rows.append((as_float((details or {}).get("timestamp"), -1.0), score, bucket))
    if len(bot_rows) < max(1, int(min_bot_samples)):
        report["reason"] = f"insufficient_bot_samples ({len(bot_rows)})"
        return score_floor, score_floors_by_deck, report
    any_clears = any(
        score >= float(score_floors_by_deck.get(int(bucket), score_floor))
        for _ts, score, bucket in bot_rows
    )
    if any_clears:
        report["reason"] = "configured_floor_reachable"
        return score_floor, score_floors_by_deck, report
    bot_rows.sort(key=lambda row: row[0])
    recent_scores = sorted(score for _ts, score, _bucket in bot_rows[-max(1, int(recent)):])
    idx = max(0, int(round(0.75 * (len(recent_scores) - 1))))
    p75 = float(recent_scores[idx])
    # Absolute junk filter, NOT tied to the deck floor table (that table is
    # the unreachable bar we're adapting away from). Full finished careers
    # score well above this; aborted/broken ones don't.
    sanity_min = float(ADAPTIVE_SCORE_FLOOR_MINIMUM)
    adapted = {}
    for bucket, configured in score_floors_by_deck.items():
        adapted[int(bucket)] = round(min(float(configured), max(sanity_min, p75)), 2)
    adapted_floor = round(min(float(score_floor), max(sanity_min, p75)), 2)
    report.update({
        "applied": True,
        "reason": "no_bot_sample_cleared_configured_floor",
        "bot_sample_count": len(bot_rows),
        "recent_p75_score": round(p75, 2),
        "configured_floors": {int(k): float(v) for k, v in score_floors_by_deck.items()},
        "adapted_floors": dict(adapted),
    })
    return adapted_floor, adapted, report


def compute_empirical_score_floors(parent_library_samples, minimum=DEFAULT_TOP_SCORE_FLOOR):
    """Use parent-library outcomes to calibrate deck-aware top-sample floors.

    Parent-library rows do not contain turn decisions, so they should not train
    the policy model directly. They can still answer a simpler question: what
    score has this account actually produced with each deck bucket?
    """
    by_bucket = {}
    for sample in parent_library_samples or []:
        source = str((sample or {}).get("source") or "").lower()
        if "parent_library" not in source:
            continue
        score = as_float((sample or {}).get("rank_score") or (sample or {}).get("score"))
        if score < minimum:
            continue
        bucket = as_int((sample or {}).get("deck_quality_bucket"), 2)
        by_bucket.setdefault(bucket, []).append(score)
    floors = {}
    diagnostics = {}
    for bucket, scores in sorted(by_bucket.items()):
        scores = sorted(scores)
        if not scores:
            continue
        median = statistics.median(scores)
        bucket_minimum = max(float(minimum), float(DECK_AWARE_TOP_SCORE_FLOORS.get(int(bucket), minimum)))
        floor = max(bucket_minimum, median * 0.90)
        floors[int(bucket)] = round(floor, 2)
        diagnostics[str(bucket)] = {
            "sample_count": len(scores),
            "median_score": round(median, 2),
            "floor": floors[int(bucket)],
        }
    return floors, diagnostics
RANK_LABELS = {
    1: "G",
    2: "F",
    3: "E",
    4: "D",
    5: "C",
    6: "B",
    7: "B+",
    8: "A",
    9: "A+",
    10: "S",
    11: "S+",
    12: "SS",
    13: "SS+",
    14: "UG",
    15: "UF",
    16: "UE",
    17: "UD",
    18: "UC",
    19: "UB",
}
RANK_ORDER = {label: value for value, label in RANK_LABELS.items()}
WHITE_FACTOR_CATEGORIES = {"race", "skill", "scenario"}
DEFAULT_AUTO_LEARNING_RECENCY_BIAS = 0.55
DEFAULT_AUTO_LEARNING_RECENCY_HALF_LIFE = 12
DEFAULT_AUTO_LEARNING_RECENT_FAILURE_BIAS = 0.35
DEFAULT_AUTO_LEARNING_REGRESSION_BIAS = 0.7
DEFAULT_AUTO_LEARNING_REGRESSION_WINDOW = 5
DEFAULT_AUTO_LEARNING_REGRESSION_FLOOR = 0.92
DEFAULT_AUTO_LEARNING_PROGRESSION_BIAS = 0.35
DEFAULT_AUTO_LEARNING_PROGRESSION_WINDOW = 5
DEFAULT_AUTO_LEARNING_PROGRESSION_DELTA = 500
LONG_HORIZON_WINDOWS = (2, 4, 8)
FULL_CAREER_STATUSES = {"finished", "rolled_over", "complete", "completed"}
MIN_FULL_CAREER_OBSERVED_TURNS = 70
FUTURE_EFFECT_KEYS = ("hp", "speed", "stamina", "power", "guts", "wit", "skill_point")
FUTURE_EFFECT_STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")
FUTURE_EFFECT_MIN_SAMPLES = 6
FUTURE_EFFECT_HP_MIN_MEDIAN = 20.0
FUTURE_EFFECT_SKILL_POINT_MIN_MEDIAN = 25.0
FUTURE_EFFECT_STAT_MIN_MEDIAN = 8.0
FUTURE_EFFECT_MIN_POSITIVE_RATE = 0.6


def clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def as_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def as_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_iso_timestamp(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _sample_path_for_stat(sample):
    raw = str((sample or {}).get("path") or "").strip()
    if not raw:
        return None
    if "#" in raw:
        raw = raw.split("#", 1)[0]
    try:
        path = Path(raw)
    except Exception:
        return None
    return path if path.exists() else None


def _sample_observed_details(sample):
    cached = sample.get("_observed_details")
    if isinstance(cached, dict):
        return cached
    for key in ("ended_at", "started_at", "created_at"):
        text = str(sample.get(key) or "").strip()
        ts = _parse_iso_timestamp(text)
        if ts is not None:
            details = {
                "timestamp": ts,
                "source": key,
                "observed_at": text,
            }
            sample["_observed_details"] = details
            return details
    path = _sample_path_for_stat(sample)
    if path is not None:
        try:
            ts = path.stat().st_mtime
            details = {
                "timestamp": ts,
                "source": "path_mtime",
                "observed_at": datetime.fromtimestamp(ts).isoformat(timespec="seconds"),
            }
            sample["_observed_details"] = details
            return details
        except Exception:
            pass
    parent_instance_id = as_int(sample.get("parent_instance_id"))
    if parent_instance_id > 0:
        details = {
            "timestamp": float(parent_instance_id),
            "source": "parent_instance_id",
            "observed_at": None,
        }
        sample["_observed_details"] = details
        return details
    details = {
        "timestamp": -1.0,
        "source": "unknown",
        "observed_at": None,
    }
    sample["_observed_details"] = details
    return details


def auto_learning_recency_config(preset):
    preset = dict(preset or {})
    return {
        "enabled": bool(preset.get("auto_learning_recency_enabled", True)),
        "bias": clamp(
            as_float(
                preset.get("auto_learning_recency_bias"),
                DEFAULT_AUTO_LEARNING_RECENCY_BIAS,
            ),
            0.0,
            2.0,
        ),
        "half_life": max(
            1,
            as_int(
                preset.get("auto_learning_recency_half_life"),
                DEFAULT_AUTO_LEARNING_RECENCY_HALF_LIFE,
            ),
        ),
        "recent_failure_bias": clamp(
            as_float(
                preset.get("auto_learning_recent_failure_bias"),
                DEFAULT_AUTO_LEARNING_RECENT_FAILURE_BIAS,
            ),
            0.0,
            2.0,
        ),
        "regression_enabled": bool(preset.get("auto_learning_regression_enabled", True)),
        "regression_bias": clamp(
            as_float(
                preset.get("auto_learning_regression_bias"),
                DEFAULT_AUTO_LEARNING_REGRESSION_BIAS,
            ),
            0.0,
            2.0,
        ),
        "regression_window": max(
            2,
            as_int(
                preset.get("auto_learning_regression_window"),
                DEFAULT_AUTO_LEARNING_REGRESSION_WINDOW,
            ),
        ),
        "regression_floor": clamp(
            as_float(
                preset.get("auto_learning_regression_floor"),
                DEFAULT_AUTO_LEARNING_REGRESSION_FLOOR,
            ),
            0.4,
            0.99,
        ),
        "progression_enabled": bool(preset.get("auto_learning_progression_enabled", True)),
        "progression_bias": clamp(
            as_float(
                preset.get("auto_learning_progression_bias"),
                DEFAULT_AUTO_LEARNING_PROGRESSION_BIAS,
            ),
            0.0,
            2.0,
        ),
        "progression_window": max(
            2,
            as_int(
                preset.get("auto_learning_progression_window"),
                DEFAULT_AUTO_LEARNING_PROGRESSION_WINDOW,
            ),
        ),
        "progression_delta": max(
            50,
            as_int(
                preset.get("auto_learning_progression_delta"),
                DEFAULT_AUTO_LEARNING_PROGRESSION_DELTA,
            ),
        ),
    }


def _recent_failure_scale(overall):
    overall = str(overall or "").strip().lower()
    if overall == "run_failure":
        return 1.0
    if overall == "partial_success":
        return 0.7
    if overall in {"acceptable_drift", "ace_drift"}:
        return 0.35
    return 0.0


def _annotate_score_regressions(ordered_samples, regression_enabled, regression_window, regression_floor):
    summary = {
        "enabled": regression_enabled,
        "window": regression_window,
        "floor": round(regression_floor, 4),
        "count": 0,
        "max_severity": 0.0,
        "largest": None,
    }
    if not ordered_samples:
        return summary

    history_scores = []
    chronological = sorted(ordered_samples, key=lambda item: (item[0], item[1], item[2]))
    for _, score_value, _, sample, _details in chronological:
        meta = sample.get("learning_metadata") or {}
        regression = {
            "enabled": regression_enabled,
            "window": regression_window,
            "floor": round(regression_floor, 4),
            "window_count": 0,
            "triggered": False,
            "baseline_score": None,
            "score_ratio": None,
            "score_delta": None,
            "severity": 0.0,
            "effective_bonus": 0.0,
        }
        if regression_enabled and len(history_scores) >= 2:
            baseline_window = history_scores[-regression_window:]
            baseline = statistics.median(baseline_window)
            if baseline > 0:
                ratio = as_float(score_value, 0.0) / baseline
                severity = clamp((regression_floor - ratio) / regression_floor, 0.0, 1.0)
                regression["window_count"] = len(baseline_window)
                regression["baseline_score"] = round(baseline, 2)
                regression["score_ratio"] = round(ratio, 4)
                regression["score_delta"] = round(as_float(score_value, 0.0) - baseline, 2)
                regression["severity"] = round(severity, 6)
                if ratio < regression_floor:
                    regression["triggered"] = True
                    summary["count"] += 1
                    summary["max_severity"] = round(max(summary["max_severity"], severity), 6)
                    if summary["largest"] is None or severity > as_float(summary["largest"].get("severity"), 0.0):
                        summary["largest"] = {
                            "path": sample.get("path"),
                            "source": sample.get("source"),
                            "score": round(as_float(score_value, 0.0), 2),
                            "baseline_score": round(baseline, 2),
                            "score_ratio": round(ratio, 4),
                            "severity": round(severity, 6),
                        }
        meta["performance_regression"] = regression
        sample["learning_metadata"] = meta
        if score_value > 0:
            history_scores.append(score_value)
    return summary


def _annotate_score_progressions(ordered_samples, progression_enabled, progression_window, progression_delta):
    summary = {
        "enabled": progression_enabled,
        "window": progression_window,
        "delta": progression_delta,
        "count": 0,
        "max_severity": 0.0,
        "largest": None,
    }
    if not ordered_samples:
        return summary

    history_scores = []
    chronological = sorted(ordered_samples, key=lambda item: (item[0], item[1], item[2]))
    for _, score_value, _, sample, _details in chronological:
        meta = sample.get("learning_metadata") or {}
        progression = {
            "enabled": progression_enabled,
            "window": progression_window,
            "delta": progression_delta,
            "window_count": 0,
            "triggered": False,
            "baseline_score": None,
            "score_delta": None,
            "score_ratio": None,
            "severity": 0.0,
            "effective_bonus": 0.0,
        }
        if progression_enabled and len(history_scores) >= 2:
            baseline_window = history_scores[-progression_window:]
            baseline = statistics.median(baseline_window)
            if baseline > 0:
                delta = as_float(score_value, 0.0) - baseline
                severity = clamp(delta / max(1.0, float(progression_delta)), 0.0, 1.0)
                progression["window_count"] = len(baseline_window)
                progression["baseline_score"] = round(baseline, 2)
                progression["score_delta"] = round(delta, 2)
                progression["score_ratio"] = round(as_float(score_value, 0.0) / baseline, 4)
                progression["severity"] = round(severity, 6)
                if delta >= progression_delta:
                    progression["triggered"] = True
                    summary["count"] += 1
                    summary["max_severity"] = round(max(summary["max_severity"], severity), 6)
                    if summary["largest"] is None or severity > as_float(summary["largest"].get("severity"), 0.0):
                        summary["largest"] = {
                            "path": sample.get("path"),
                            "source": sample.get("source"),
                            "score": round(as_float(score_value, 0.0), 2),
                            "baseline_score": round(baseline, 2),
                            "score_delta": round(delta, 2),
                            "score_ratio": round(as_float(score_value, 0.0) / baseline, 4),
                            "severity": round(severity, 6),
                        }
        meta["performance_progression"] = progression
        sample["learning_metadata"] = meta
        if score_value > 0:
            history_scores.append(score_value)
    return summary


def apply_recency_weights(samples, recency_config=None):
    config = dict(recency_config or {})
    enabled = bool(config.get("enabled", True))
    bias = clamp(as_float(config.get("bias"), DEFAULT_AUTO_LEARNING_RECENCY_BIAS), 0.0, 2.0)
    half_life = max(1, as_int(config.get("half_life"), DEFAULT_AUTO_LEARNING_RECENCY_HALF_LIFE))
    recent_failure_bias = clamp(
        as_float(
            config.get("recent_failure_bias"),
            DEFAULT_AUTO_LEARNING_RECENT_FAILURE_BIAS,
        ),
        0.0,
        2.0,
    )
    regression_enabled = bool(config.get("regression_enabled", True))
    regression_bias = clamp(
        as_float(
            config.get("regression_bias"),
            DEFAULT_AUTO_LEARNING_REGRESSION_BIAS,
        ),
        0.0,
        2.0,
    )
    regression_window = max(
        2,
        as_int(
            config.get("regression_window"),
            DEFAULT_AUTO_LEARNING_REGRESSION_WINDOW,
        ),
    )
    regression_floor = clamp(
        as_float(
            config.get("regression_floor"),
            DEFAULT_AUTO_LEARNING_REGRESSION_FLOOR,
        ),
        0.4,
        0.99,
    )
    progression_enabled = bool(config.get("progression_enabled", True))
    progression_bias = clamp(
        as_float(
            config.get("progression_bias"),
            DEFAULT_AUTO_LEARNING_PROGRESSION_BIAS,
        ),
        0.0,
        2.0,
    )
    progression_window = max(
        2,
        as_int(
            config.get("progression_window"),
            DEFAULT_AUTO_LEARNING_PROGRESSION_WINDOW,
        ),
    )
    progression_delta = max(
        50,
        as_int(
            config.get("progression_delta"),
            DEFAULT_AUTO_LEARNING_PROGRESSION_DELTA,
        ),
    )
    summary = {
        "enabled": enabled,
        "bias": round(bias, 4),
        "half_life": half_life,
        "recent_failure_bias": round(recent_failure_bias, 4),
        "regression_enabled": regression_enabled,
        "regression_bias": round(regression_bias, 4),
        "regression_window": regression_window,
        "regression_floor": round(regression_floor, 4),
        "progression_enabled": progression_enabled,
        "progression_bias": round(progression_bias, 4),
        "progression_window": progression_window,
        "progression_delta": progression_delta,
        "sample_count": len(samples or []),
        "average_multiplier": 1.0,
        "max_multiplier": 1.0,
        "min_multiplier": 1.0,
        "recent_failure_count": 0,
        "regression_count": 0,
        "max_regression_severity": 0.0,
        "average_regression_bonus": 0.0,
        "largest_regression": None,
        "progression_count": 0,
        "max_progression_severity": 0.0,
        "average_progression_bonus": 0.0,
        "largest_progression": None,
        "diagnostic_only_count": 0,
        "by_source": {},
        "newest_sample": None,
    }
    if not samples:
        return summary

    ordered = []
    for sample in samples:
        details = _sample_observed_details(sample)
        ordered.append(
            (
                as_float(details.get("timestamp"), -1.0),
                as_float(sample.get("score"), 0.0),
                str(sample.get("path") or ""),
                sample,
                details,
            )
        )
    ordered.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    summary["newest_sample"] = {
        "source": ordered[0][3].get("source"),
        "path": ordered[0][3].get("path"),
        "observed_at": ordered[0][4].get("observed_at"),
        "observed_at_source": ordered[0][4].get("source"),
    }
    regression_summary = _annotate_score_regressions(
        ordered,
        regression_enabled=regression_enabled,
        regression_window=regression_window,
        regression_floor=regression_floor,
    )
    summary["regression_count"] = regression_summary.get("count", 0)
    summary["max_regression_severity"] = regression_summary.get("max_severity", 0.0)
    summary["largest_regression"] = regression_summary.get("largest")
    progression_summary = _annotate_score_progressions(
        ordered,
        progression_enabled=progression_enabled,
        progression_window=progression_window,
        progression_delta=progression_delta,
    )
    summary["progression_count"] = progression_summary.get("count", 0)
    summary["max_progression_severity"] = progression_summary.get("max_severity", 0.0)
    summary["largest_progression"] = progression_summary.get("largest")

    multiplier_values = []
    regression_bonus_values = []
    progression_bonus_values = []
    for rank, (_, _, _, sample, details) in enumerate(ordered):
        base_weight = as_float(
            sample.get("_pre_recency_sample_weight"),
            as_float(sample.get("sample_weight"), 1.0),
        )
        sample["_pre_recency_sample_weight"] = base_weight
        rank_strength = math.exp(-float(rank) / float(half_life))
        recency_strength = rank_strength if enabled else 0.0
        regression_strength = rank_strength if regression_enabled else 0.0
        base_bonus = bias * recency_strength if enabled else 0.0
        meta = sample.get("learning_metadata") or {}
        gate = meta.get("policy_steering_gate") or {}
        outcome = (meta.get("outcome_assessment") or {}).get("overall")
        diagnostic_only = bool(gate.get("diagnostic_only")) or str(outcome or "").strip().lower() in {
            "run_failure",
            "partial_success",
        }
        regression = meta.get("performance_regression") or {}
        progression = meta.get("performance_progression") or {}
        regression_severity = as_float(regression.get("severity"), 0.0)
        progression_severity = as_float(progression.get("severity"), 0.0)
        failure_bonus = recent_failure_bias * _recent_failure_scale(outcome) * recency_strength if enabled else 0.0
        regression_bonus = (
            regression_bias * regression_severity * regression_strength
            if regression_enabled and regression.get("triggered")
            else 0.0
        )
        progression_bonus = (
            progression_bias * progression_severity * recency_strength
            if progression_enabled and progression.get("triggered")
            else 0.0
        )
        if diagnostic_only:
            # Failed/low-output runs must not become louder just because they
            # are recent. They remain available as bottom/diagnostic evidence,
            # but never get positive recency, failure, regression, or
            # progression amplification.
            base_bonus = 0.0
            failure_bonus = 0.0
            regression_bonus = 0.0
            progression_bonus = 0.0
            summary["diagnostic_only_count"] += 1
        multiplier = 1.0 + base_bonus + failure_bonus + regression_bonus + progression_bonus
        sample["sample_weight"] = round(base_weight * multiplier, 6)
        if isinstance(regression, dict):
            regression["effective_bonus"] = round(regression_bonus, 6)
            meta["performance_regression"] = regression
        if isinstance(progression, dict):
            progression["effective_bonus"] = round(progression_bonus, 6)
            meta["performance_progression"] = progression
        meta["recency"] = {
            "enabled": enabled,
            "rank": rank,
            "sample_count": len(ordered),
            "strength": round(rank_strength, 6),
            "multiplier": round(multiplier, 6),
            "base_bonus": round(base_bonus, 6),
            "failure_bonus": round(failure_bonus, 6),
            "regression_bonus": round(regression_bonus, 6),
            "progression_bonus": round(progression_bonus, 6),
            "diagnostic_only": diagnostic_only,
            "observed_at": details.get("observed_at"),
            "observed_at_source": details.get("source"),
        }
        sample["learning_metadata"] = meta
        multiplier_values.append(multiplier)
        regression_bonus_values.append(regression_bonus)
        progression_bonus_values.append(progression_bonus)
        if failure_bonus > 0:
            summary["recent_failure_count"] += 1
        source = sample.get("source") or "unknown"
        bucket = summary["by_source"].setdefault(
            source,
            {
                "count": 0,
                "average_multiplier": 0.0,
                "average_regression_bonus": 0.0,
                "average_progression_bonus": 0.0,
            },
        )
        bucket["count"] += 1
        bucket["average_multiplier"] += multiplier
        bucket["average_regression_bonus"] += regression_bonus
        bucket["average_progression_bonus"] += progression_bonus

    if multiplier_values:
        summary["average_multiplier"] = round(sum(multiplier_values) / len(multiplier_values), 4)
        summary["max_multiplier"] = round(max(multiplier_values), 4)
        summary["min_multiplier"] = round(min(multiplier_values), 4)
    if regression_bonus_values:
        summary["average_regression_bonus"] = round(sum(regression_bonus_values) / len(regression_bonus_values), 4)
    if progression_bonus_values:
        summary["average_progression_bonus"] = round(sum(progression_bonus_values) / len(progression_bonus_values), 4)
    for bucket in summary["by_source"].values():
        if bucket["count"]:
            bucket["average_multiplier"] = round(bucket["average_multiplier"] / bucket["count"], 4)
            bucket["average_regression_bonus"] = round(
                bucket["average_regression_bonus"] / bucket["count"],
                4,
            )
            bucket["average_progression_bonus"] = round(
                bucket["average_progression_bonus"] / bucket["count"],
                4,
            )
    return summary


def rank_label(value):
    rank = as_int(value)
    if rank <= 0:
        return "unknown"
    return RANK_LABELS.get(rank, f"rank_{rank}")


def safe_items(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        items = value.get("$items")
        if isinstance(items, list):
            return items
    return []


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def read_project_json(*parts):
    return read_json(PROJECT_ROOT.joinpath(*parts)) or {}


def supported_career_log(data):
    if not isinstance(data, dict):
        return False
    schema = str(data.get("schema") or "sweepy_career_log_v0")
    return schema in SUPPORTED_CAREER_LOG_SCHEMAS


def learning_references():
    global _REFERENCE_CACHE
    if _REFERENCE_CACHE is not None:
        return _REFERENCE_CACHE

    factor_map = read_project_json("data", "factor_map.json")
    race_map = read_project_json("data", "race_map.json")
    affinity_meta = read_project_json("public", "assets", "data", "affinity_race_meta.json")
    master_map = read_project_json("data", "master_map.json")
    parent_knowledge = read_project_json("data", "parent_farming_knowledge.json")

    race_meta_by_program = {}
    race_meta_by_race_id = {}
    race_meta_by_instance_id = {}
    for key, value in (race_map.get("meta") or {}).items():
        if not isinstance(value, dict):
            continue
        row = dict(value)
        row.setdefault("race_id", as_int(key))
        program_id = as_int(row.get("program_id"))
        race_id = as_int(row.get("race_id"))
        race_instance_id = as_int(row.get("race_instance_id"))
        if program_id and program_id not in race_meta_by_program:
            race_meta_by_program[program_id] = row
        if race_id:
            race_meta_by_race_id[race_id] = row
        if race_instance_id:
            race_meta_by_instance_id[race_instance_id] = row

    skill_names = {}
    for raw_id, row in (master_map.get("skill") or {}).items():
        if isinstance(row, dict):
            name = row.get("name") or row.get("text")
        else:
            name = row
        if name:
            skill_names[as_int(raw_id)] = str(name)

    grade_by_race_id = {
        as_int(key): str(value)
        for key, value in (affinity_meta.get("grade_by_race_id") or {}).items()
        if as_int(key)
    }
    legacy_overlap_race_ids = {
        as_int(value) for value in affinity_meta.get("legacy_overlap_race_ids") or [] if as_int(value)
    }
    modern_overlap_race_ids = {
        as_int(value) for value in affinity_meta.get("modern_overlap_race_ids") or [] if as_int(value)
    }
    overlap_race_ids = set()
    overlap_race_ids.update(legacy_overlap_race_ids)
    overlap_race_ids.update(modern_overlap_race_ids)
    epithet_sets = []
    for row in affinity_meta.get("legacy_epithet_sets") or []:
        if not isinstance(row, dict):
            continue
        race_ids = {as_int(value) for value in row.get("race_ids") or [] if as_int(value)}
        if race_ids:
            epithet_sets.append({"name": row.get("name") or "", "race_ids": race_ids})

    _REFERENCE_CACHE = {
        "factor_map": factor_map,
        "race_map": race_map,
        "affinity_meta": affinity_meta,
        "race_meta_by_program": race_meta_by_program,
        "race_meta_by_race_id": race_meta_by_race_id,
        "race_meta_by_instance_id": race_meta_by_instance_id,
        "grade_by_race_id": grade_by_race_id,
        "legacy_overlap_race_ids": legacy_overlap_race_ids,
        "modern_overlap_race_ids": modern_overlap_race_ids,
        "overlap_race_ids": overlap_race_ids,
        "epithet_sets": epithet_sets,
        "skill_names": skill_names,
        "parent_knowledge": parent_knowledge,
    }
    return _REFERENCE_CACHE


def read_jsonl(path):
    """Read a stream of concatenated JSON objects.

    Tolerates two formats so the same loader can handle both the bot's
    own line-per-row JSONL and the hachimi sweepy_capture add-on, which
    sometimes writes pretty-printed multi-line JSON objects appended to
    the same file. Strategy: read the whole file, then use raw_decode to
    consume one JSON object at a time, advancing past whitespace between
    them.
    """
    try:
        path = Path(path)
        if path.suffix.lower() == ".gz":
            with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
                text = f.read()
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rows = []
    decoder = json.JSONDecoder()
    text_len = len(text)
    pos = 0
    while pos < text_len:
        while pos < text_len and text[pos].isspace():
            pos += 1
        if pos >= text_len:
            break
        try:
            obj, end = decoder.raw_decode(text, pos)
            rows.append(obj)
            pos = end
        except json.JSONDecodeError:
            next_brace = text.find("{", pos + 1)
            next_bracket = text.find("[", pos + 1)
            candidates = [c for c in (next_brace, next_bracket) if c >= 0]
            if not candidates:
                break
            pos = min(candidates)
    return rows


def runtime_roots(base_dir, extra_roots=None):
    base = Path(base_dir).expanduser().resolve()
    roots = []
    def add_root(candidate):
        if not candidate:
            return
        try:
            path = Path(candidate).expanduser().resolve()
        except Exception:
            return
        if path.exists() and path not in roots:
            roots.append(path)

    def iter_runtime_path_values(value):
        if not value:
            return []
        if isinstance(value, (str, Path)):
            tokens = str(value).replace("\r", "\n")
            for splitter in ("\n", ","):
                tokens = tokens.replace(splitter, os.pathsep)
            return [part.strip() for part in tokens.split(os.pathsep) if part.strip()]
        result = []
        for item in value:
            result.extend(iter_runtime_path_values(item))
        return result

    explicit_runtime = False
    before = len(roots)
    add_root(os.environ.get("UMA_RUNTIME_DIR"))
    explicit_runtime = explicit_runtime or len(roots) > before
    for root in iter_runtime_path_values(extra_roots):
        before = len(roots)
        add_root(root)
        explicit_runtime = explicit_runtime or len(roots) > before
    for root in iter_runtime_path_values(os.environ.get("SWEEPY_SHARED_RUNTIME_PATHS")):
        before = len(roots)
        add_root(root)
        explicit_runtime = explicit_runtime or len(roots) > before
    if explicit_runtime:
        return roots
    for root in [base.parent / "uma_runtime", base / "uma_runtime"]:
        add_root(root)
    if not roots:
        roots.append(base.parent / "uma_runtime")
    return roots


def primary_runtime_root(base_dir, extra_roots=None):
    roots = runtime_roots(base_dir, extra_roots)
    return Path(roots[0]) if roots else None


def _normalized_runtime_root(value):
    if not value:
        return ""
    try:
        return str(Path(value).expanduser().resolve())
    except Exception:
        return str(value or "")


def _instance_local_learning_scope_enabled():
    scope = str(os.environ.get("SWEEPY_AUTO_LEARNING_SCOPE") or "").strip().lower()
    if scope in {"instance", "local", "instance_local"}:
        return True
    if scope in {"shared", "shared_preset", "shared_overlay", "shared_runtime", "shared_learning", "global"}:
        return False
    # Dual runtimes should share the learning pool by default. Instance-local
    # learning remains available, but it must be explicitly requested.
    return False


def resolve_runtime_learning_pools(samples, primary_root=None, *, instance_local=False, min_local_samples=3):
    pool = [sample for sample in (samples or []) if isinstance(sample, dict)]
    primary = _normalized_runtime_root(primary_root)
    local = []
    for sample in pool:
        sample_root = _normalized_runtime_root(sample.get("runtime_root"))
        if primary and sample_root == primary:
            local.append(sample)
    use_local = bool(instance_local and len(local) >= max(1, as_int(min_local_samples, 3)))
    manual_behavior = []
    if use_local:
        seen = set()
        for sample in local:
            key = str(sample.get("path") or id(sample))
            seen.add(key)
        for sample in pool:
            key = str(sample.get("path") or id(sample))
            if key in seen:
                continue
            if _is_manual_sample(sample) and _is_behavior_learning_sample(sample):
                manual_behavior.append(sample)
                seen.add(key)
    behavior = (local + manual_behavior) if use_local else pool
    if use_local:
        mode = "instance_local"
    elif instance_local and primary:
        mode = "shared_fallback"
    else:
        mode = "shared"
    return {
        "mode": mode,
        "primary_root": primary,
        "local_samples": local,
        "all_samples": pool,
        "behavior_samples": behavior,
        "local_sample_count": len(local),
        "shared_sample_count": len(pool),
        "manual_behavior_sample_count": len(manual_behavior),
        "behavior_sample_count": len(behavior),
    }


def preferred_postmortem_runtime_root(base_dir, extra_roots=None):
    roots = runtime_roots(base_dir, extra_roots)
    for root in roots:
        if (Path(root) / "postmortems").exists():
            return Path(root)
    return Path(roots[0]) if roots else None


def period_index(turn):
    turn = as_int(turn)
    if turn <= 24:
        return 0
    if turn <= 48:
        return 1
    if turn <= 60:
        return 2
    if turn <= 72:
        return 3
    return 4


def extra_phase_index(turn):
    turn = as_int(turn)
    if turn <= 24:
        return 0
    if turn <= 48:
        return 1
    if turn in SUMMER_CAMP_TURNS:
        return 3
    return 2


def empty_action_stats():
    return {
        "count": 0.0,
        "weighted_gain": 0.0,
        "failure_rate": 0.0,
        "rainbow_count": 0.0,
        "hint_count": 0.0,
        "partner_count": 0.0,
        "deck_partner_count": 0.0,
        "high_bond_count": 0.0,
        "hp": 0.0,
        "skill_point": 0.0,
    }


def add_action_stats(target, action, weight=1.0):
    target["count"] += weight
    for key in [
        "weighted_gain",
        "failure_rate",
        "rainbow_count",
        "hint_count",
        "partner_count",
        "deck_partner_count",
        "high_bond_count",
        "hp",
        "skill_point",
    ]:
        target[key] += as_float(action.get(key), 0.0) * weight


def average_action_stats(stats):
    count = stats.get("count") or 0.0
    if count <= 0:
        return dict(stats)
    return {key: (value / count if key != "count" else value) for key, value in stats.items()}


def weighted_percentile(values, percentile):
    rows = [(as_float(value), as_float(weight, 1.0)) for value, weight in values if as_float(weight, 0.0) > 0]
    if not rows:
        return None
    rows.sort(key=lambda row: row[0])
    total_weight = sum(weight for _, weight in rows)
    if total_weight <= 0:
        return None
    target = total_weight * clamp(percentile, 0.0, 1.0)
    running = 0.0
    for value, weight in rows:
        running += weight
        if running >= target:
            return value
    return rows[-1][0]


def final_stats_from_turn(turn):
    stats = dict(turn.get("stats") or {})
    return {
        "speed": as_int(stats.get("speed")),
        "stamina": as_int(stats.get("stamina")),
        "power": as_int(stats.get("power")),
        "guts": as_int(stats.get("guts")),
        "wit": as_int(stats.get("wit") if "wit" in stats else stats.get("wiz")),
        "skill_point": as_int(stats.get("skill_point")),
        "hp": as_int(stats.get("hp") if "hp" in stats else stats.get("vital")),
        "fans": as_int(stats.get("fans") or turn.get("fans")),
    }


def final_stats_from_summary(summary):
    current = summary.get("current") or {}
    return {
        "speed": as_int(current.get("speed")),
        "stamina": as_int(current.get("stamina")),
        "power": as_int(current.get("power")),
        "guts": as_int(current.get("guts")),
        "wit": as_int(current.get("wit") if "wit" in current else current.get("wiz")),
        "skill_point": as_int(current.get("skill_point")),
        "hp": as_int(current.get("vital") if "vital" in current else current.get("hp")),
        "fans": as_int(current.get("fans")),
    }


def _observed_turn_numbers(turns):
    numbers = sorted({as_int((turn or {}).get("turn")) for turn in (turns or []) if as_int((turn or {}).get("turn")) > 0})
    return numbers


def full_career_capture_details(turns, status=None):
    observed = _observed_turn_numbers(turns)
    first_turn = observed[0] if observed else 0
    last_turn = observed[-1] if observed else 0
    has_turn_one = 1 in observed
    has_turn_78 = 78 in observed
    observed_turn_count = len(observed)
    coverage_ratio = (observed_turn_count / 78.0) if observed_turn_count else 0.0
    status_text = str(status or "").strip().lower()
    full = (
        bool(observed)
        and status_text in FULL_CAREER_STATUSES
        and has_turn_one
        and has_turn_78
        and last_turn >= 78
        and observed_turn_count >= MIN_FULL_CAREER_OBSERVED_TURNS
    )
    return {
        "first_turn": first_turn,
        "last_turn": last_turn,
        "has_turn_one": has_turn_one,
        "has_turn_78": has_turn_78,
        "observed_turn_count": observed_turn_count,
        "coverage_ratio": round(coverage_ratio, 4),
        "full": full,
    }


def is_full_career_sample(sample, require_turn_data=False):
    sample = sample or {}
    source = str(sample.get("source") or "").strip().lower()
    status = str(sample.get("status") or "").strip().lower()
    if source.endswith("_parent_library"):
        return (not require_turn_data) and status == "parent_library" and as_int(sample.get("final_turn")) >= 78
    if require_turn_data and not bool(sample.get("has_turn_data")):
        return False
    if "full_career_capture" in sample:
        return bool(sample.get("full_career_capture"))
    first_turn = as_int(sample.get("first_turn"))
    final_turn = as_int(sample.get("final_turn"))
    has_turn_one = bool(sample.get("has_turn_one")) or first_turn == 1
    has_turn_78 = bool(sample.get("has_turn_78")) or final_turn >= 78
    observed_turn_count = as_int(sample.get("observed_turn_count"), as_int(sample.get("turn_count")))
    return (
        status in FULL_CAREER_STATUSES
        and has_turn_one
        and has_turn_78
        and final_turn >= 78
        and observed_turn_count >= MIN_FULL_CAREER_OBSERVED_TURNS
    )


def race_counts_from_turns(turns):
    races = race_entries_from_turns(turns)
    if races:
        wins = sum(1 for race in races if race.get("won"))
        losses = sum(1 for race in races if not race.get("won") and as_int(race.get("result_rank")) > 1)
        return wins, losses

    history_seen = {}
    for turn in turns or []:
        for race in turn.get("race_history") or []:
            program_id = race.get("program_id")
            if program_id is not None:
                key = (as_int(race.get("turn")), as_int(program_id))
                if key not in history_seen:
                    history_seen[key] = as_int(race.get("result_rank"), 0)
    if history_seen:
        wins = 0
        losses = 0
        for rank in history_seen.values():
            if rank == 1:
                wins += 1
            elif rank > 1:
                losses += 1
        return wins, losses

    wins = 0
    losses = 0
    event_seen = set()
    for turn in turns or []:
        for event in turn.get("events") or []:
            if not isinstance(event, dict):
                continue
            if event.get("event") != "race_result":
                continue
            key = (as_int(event.get("turn") or turn.get("turn")), as_int(event.get("program_id")))
            if key in event_seen:
                continue
            event_seen.add(key)
            if event.get("won") is True:
                wins += 1
                continue
            if event.get("won") is False:
                losses += 1
                continue
            rank = as_int(event.get("finish_rank") or event.get("rank") or event.get("result_rank"), 0)
            if rank == 1:
                wins += 1
            elif rank > 1:
                losses += 1
    return wins, losses


def race_counts_from_summary(summary):
    races = race_entries_from_summary(summary)
    if races:
        wins = sum(1 for race in races if race.get("won"))
        losses = sum(1 for race in races if not race.get("won") and as_int(race.get("result_rank")) > 1)
        return wins, losses

    history = safe_items((summary.get("races") or {}).get("history"))
    wins = 0
    losses = 0
    for race in history:
        rank = as_int(race.get("result_rank"), 0)
        if rank == 1:
            wins += 1
        elif rank > 1:
            losses += 1
    return wins, losses


STAT_CAP = 1200
STAT_KEYS_FOR_CAP = ("speed", "stamina", "power", "guts", "wit")
STAT_WEIGHTS_FOR_CAP = {
    "speed": 1.20,
    "stamina": 1.08,
    "power": 1.18,
    "guts": 0.82,
    "wit": 1.16,
}


def _stat_value(stats, key):
    """Stat value used for rating purposes, with the visible game cap
    applied. Points past STAT_CAP (1200) don't contribute additional
    linear reward — they're overtraining the bot shouldn't be praised
    for. The threshold bonus and multi-cap bonus give the credit for
    actually hitting the cap."""
    return min(as_float(stats.get(key, 0)), STAT_CAP)


def estimate_score(
    stats,
    wins=0,
    losses=0,
    status="finished",
    factor_score=0,
    race_quality=None,
    factor_quality=None,
    skill_quality=None,
    parent_goals=None,
):
    race_quality = race_quality or {}
    factor_quality = factor_quality or {}
    skill_quality = skill_quality or {}
    skill_point = as_int(stats.get("skill_point"))
    # Race-record + stat-distribution weights are tuned for parent
    # farming. The thesis: best parent = clean record + most G1 wins +
    # cap on the target stat + cap on as many other stats as possible
    # + high affinity overlap. The formula has to reflect that the
    # gradient between OK and great is large.
    #
    # Current key weights (see project_estimate_score_parent_weighting
    # memory):
    #   - G1 wins ×220, losses ×-260, regular wins ×50
    #   - G1 losses: non-linear (1=-350, +500 per additional)
    #   - Race-win skill parsimony: cleaner wins with fewer mid-career
    #     skills rate higher than wins that required a large skill stack
    #   - Stat reward capped at 1200/stat (no overtrain credit)
    #   - Target-stat threshold ladder (+400 at 1100, +800 more at cap)
    #   - Multi-stat-at-cap compounding bonus (up to +5000 at 5/5)
    #   - G1 milestone ladder (+800/+1800/+3500 at 10/15/20 G1 wins)
    #   - Perfect-record-at-scale ladder (up to +7000 at 40+ races)
    g1_wins = as_int(race_quality.get("g1_wins"))
    g1_losses = as_int(race_quality.get("g1_losses"))
    # G1 losses compound: the first one is recoverable, additional ones
    # are career-killers. 1 = -350, 2 = -850, 3 = -1350.
    g1_loss_penalty = 0.0
    if g1_losses > 0:
        g1_loss_penalty = 350.0 + max(0, g1_losses - 1) * 500.0
    rating = (
        _stat_value(stats, "speed") * 1.20
        + _stat_value(stats, "stamina") * 1.08
        + _stat_value(stats, "power") * 1.18
        + _stat_value(stats, "guts") * 0.82
        + _stat_value(stats, "wit") * 1.16
        + min(skill_point, 160) * 0.035
        - max(0, skill_point - 160) * 0.16
        + stats.get("fans", 0) * 0.0015
        + wins * 50.0
        - losses * 260.0
        + factor_score * 2.0
        + as_float(factor_quality.get("score")) * 1.0
        + as_float(skill_quality.get("spend_score")) * 1.0
        + g1_wins * 220.0
        - g1_loss_penalty
        + as_float(race_quality.get("skill_parsimony_bonus")) * 1.0
        + as_float(race_quality.get("affinity_overlap_wins")) * 34.0
        + as_float(race_quality.get("affinity_overlap_g1_wins")) * 34.0
        + as_float(race_quality.get("global_legacy_overlap_points")) * 12.0
        + as_float(race_quality.get("epithet_sets_completed")) * 120.0
        + as_float(race_quality.get("distance_variety")) * 24.0
        + as_float(race_quality.get("venue_variety")) * 12.0
    )
    # Target-stat threshold ladder. The bot gets credit for putting a
    # target stat into the high-rate spark band (1100+) and for capping
    # it (1200). This is the "right play, bad RNG" fix at the rating
    # layer: spark generation is stochastic, but strategic positioning
    # is determined by where the stat ends up.
    target_blue = []
    if isinstance(parent_goals, dict):
        target_blue = [str(name).strip().lower() for name in (parent_goals.get("blue") or []) if str(name).strip()]
    if target_blue:
        # Map stat-name strings ("Speed", "Power", "Wit"…) to the keys
        # `stats` uses ("speed", "power", "wit"). Both share the same
        # lowercase root.
        for stat_name in target_blue:
            if stat_name not in STAT_KEYS_FOR_CAP:
                continue
            value = as_float(stats.get(stat_name, 0))
            if value >= 1100:
                rating += 400.0
            if value >= STAT_CAP:
                rating += 800.0  # additional bonus, so capped target = +1200 total
    # Multi-stat-at-cap bonus. Compounds: capping 3 stats is worth more
    # than 3× capping 1 stat. The slope steepens because reaching all 5
    # caps is essentially impossible — when it happens, it should be
    # rewarded hugely.
    capped_count = sum(1 for key in STAT_KEYS_FOR_CAP if as_float(stats.get(key, 0)) >= STAT_CAP)
    if capped_count >= 5:
        rating += 5000.0
    elif capped_count == 4:
        rating += 2500.0
    elif capped_count == 3:
        rating += 1200.0
    elif capped_count == 2:
        rating += 500.0
    # G1 win milestone ladder. The per-G1 weight (×220) is linear; the
    # milestones add a structural reward for sustained G1 dominance.
    if g1_wins >= 20:
        rating += 3500.0
    elif g1_wins >= 15:
        rating += 1800.0
    elif g1_wins >= 10:
        rating += 800.0
    race_total = as_int(race_quality.get("race_total"))
    # Perfect-record-at-scale ladder. A clean 22-race career is great;
    # a clean 40-race career is once-in-a-thousand. The ladder makes
    # sure the rating reflects how rare each scale tier is.
    if losses == 0 and race_total >= 40:
        rating += 7000.0
    elif losses == 0 and race_total >= 30:
        rating += 4500.0
    elif losses == 0 and race_total >= 20:
        rating += 2500.0
    elif losses == 0 and race_total >= 15:
        rating += 1500.0
    elif losses == 0 and race_total >= 10:
        rating += 800.0
    elif losses == 0 and race_total >= 5:
        rating += 200.0
    # Deferred-skill-buying bonus: the optimal parent-farming play is to
    # save SP all career (maximize stat training time, no SP detours)
    # and dump it on skills at the end_skill_purchase phase when full
    # information is available. Reward this only when paired with a
    # clean record at scale — otherwise the bot might learn to skip
    # skills as a shortcut even when buying them mid-career would have
    # saved a race.
    end_purchase_count = as_int((skill_quality or {}).get("end_purchase_count"))
    learned_skill_count = as_int((skill_quality or {}).get("learned_skill_count"))
    if (
        losses == 0
        and race_total >= 15
        and learned_skill_count >= 5
        and end_purchase_count >= int(learned_skill_count * 0.8)
    ):
        rating += 1000.0
    if race_total and race_total < 8 and status in {"finished", "rolled_over", "complete", "completed"}:
        rating -= 900.0
    elif race_total and race_total < 20 and status in {"finished", "rolled_over", "complete", "completed"}:
        rating -= (20 - race_total) * 28.0
    if status in {"finished", "rolled_over", "complete", "completed"}:
        rating += 400.0
    elif status == "error":
        rating -= 3000.0
    elif status == "stopped":
        rating -= 1800.0
    elif status == "partial":
        rating -= 700.0
    return round(rating, 3)


def factor_score_from_any(value, depth=0):
    if depth > 8:
        return 0
    if isinstance(value, list):
        return sum(factor_score_from_any(item, depth + 1) for item in value)
    if not isinstance(value, dict):
        return 0
    score = 0
    if "factor_id" in value:
        level = as_int(value.get("level"), 0)
        factor_id = as_int(value.get("factor_id"), 0)
        stars = factor_id % 10 if factor_id > 1000 else level
        score += clamp(stars, 0, 3)
    for item in value.values():
        score += factor_score_from_any(item, depth + 1)
    return score


def normalize_grade(value):
    if value is None:
        return ""
    text = str(value).strip().upper()
    if text in {"1", "G1", "GI"}:
        return "G1"
    if text in {"2", "G2", "GII"}:
        return "G2"
    if text in {"3", "G3", "GIII"}:
        return "G3"
    if text in {"OP", "OPEN"}:
        return "OP"
    return text


def normalize_race_entry(raw):
    if not isinstance(raw, dict):
        return None
    refs = learning_references()
    nested = raw.get("race") if isinstance(raw.get("race"), dict) else {}
    program_id = as_int(raw.get("program_id") or nested.get("program_id"))
    race_id = as_int(raw.get("race_id") or nested.get("race_id"))
    race_instance_id = as_int(raw.get("race_instance_id") or nested.get("race_instance_id"))

    meta = None
    if race_instance_id:
        meta = refs["race_meta_by_instance_id"].get(race_instance_id)
    if meta is None and race_id:
        meta = refs["race_meta_by_race_id"].get(race_id)
    if meta is None and program_id:
        meta = refs["race_meta_by_program"].get(program_id)
    if meta:
        program_id = program_id or as_int(meta.get("program_id"))
        race_id = race_id or as_int(meta.get("race_id"))
        race_instance_id = race_instance_id or as_int(meta.get("race_instance_id"))

    overlap_race_id = race_instance_id or race_id
    grade = normalize_grade(raw.get("grade") or nested.get("grade"))
    if not grade and overlap_race_id:
        grade = normalize_grade(refs["grade_by_race_id"].get(overlap_race_id))
    if not grade and meta:
        grade = normalize_grade(meta.get("grade") or meta.get("race_grade"))

    rank = as_int(raw.get("result_rank") or raw.get("finish_rank") or raw.get("rank"), 0)
    won = raw.get("won")
    if won is None:
        won = rank == 1 if rank else None

    return {
        "turn": as_int(raw.get("turn")),
        "program_id": program_id,
        "race_id": race_id,
        "race_instance_id": race_instance_id,
        "overlap_race_id": overlap_race_id,
        "name": raw.get("name") or nested.get("name") or (meta or {}).get("name") or "",
        "grade": grade,
        "terrain": raw.get("terrain") or nested.get("terrain") or (meta or {}).get("terrain") or "",
        "distance": raw.get("distance") or nested.get("distance") or (meta or {}).get("distance") or "",
        "venue": raw.get("venue") or nested.get("venue") or (meta or {}).get("venue") or "",
        "style": raw.get("style") or nested.get("style") or "",
        "running_style": as_int(raw.get("running_style") or nested.get("running_style")),
        "result_rank": rank,
        "won": bool(won) if won is not None else False,
        "skill_count_at_race": raw.get("skill_count_at_race"),
        "stats_at_race": dict(raw.get("stats_at_race") or {}) if isinstance(raw.get("stats_at_race"), dict) else {},
    }


def dedupe_races(races):
    merged = {}
    for race in races:
        if not race:
            continue
        key = (
            race.get("turn"),
            race.get("program_id"),
            race.get("overlap_race_id") or race.get("race_id"),
            race.get("result_rank"),
        )
        existing = merged.get(key)
        if existing is None:
            merged[key] = dict(race)
            continue
        combined = dict(existing)
        for field, value in (race or {}).items():
            if field == "stats_at_race":
                if isinstance(value, dict) and value:
                    merged_stats = dict(combined.get("stats_at_race") or {})
                    for stat_key, stat_value in value.items():
                        if stat_key not in merged_stats and stat_value is not None:
                            merged_stats[stat_key] = stat_value
                    if merged_stats:
                        combined["stats_at_race"] = merged_stats
                continue
            if field == "skill_count_at_race":
                if combined.get(field) is None and value is not None:
                    combined[field] = value
                continue
            if combined.get(field) in (None, "", {}, []) and value not in (None, "", {}, []):
                combined[field] = value
        merged[key] = combined
    return list(merged.values())


def race_entries_from_turns(turns):
    races = []
    for turn in turns or []:
        turn_num = as_int(turn.get("turn"))
        for row in turn.get("race_history") or []:
            if isinstance(row, dict):
                raw = dict(row)
                raw.setdefault("turn", turn_num)
                races.append(normalize_race_entry(raw))
        for event in turn.get("events") or []:
            if not isinstance(event, dict) or event.get("event") != "race_result":
                continue
            raw = dict(event)
            raw.setdefault("turn", turn_num)
            races.append(normalize_race_entry(raw))
    return dedupe_races(races)


def race_entries_from_summary(summary):
    races = []
    history = safe_items((summary.get("races") or {}).get("history"))
    for row in history:
        races.append(normalize_race_entry(row))
    return dedupe_races(races)


def global_legacy_compatibility_rules():
    knowledge = learning_references().get("parent_knowledge") or {}
    rules = knowledge.get("compatibility_rules") if isinstance(knowledge, dict) else {}
    if not isinstance(rules, dict):
        rules = {}
    server = str(knowledge.get("server") or "global").strip().lower()
    system = str(knowledge.get("compatibility_system") or "legacy").strip().lower()
    grades = {normalize_grade(grade) for grade in rules.get("overlap_win_grades") or ["G1", "G2", "G3"]}
    return {
        "server": server or "global",
        "compatibility_system": system or "legacy",
        "overlap_win_grades": {grade for grade in grades if grade},
        "same_race_duplicate_bonus": bool(rules.get("same_race_duplicate_bonus", False)),
        "title_epithet_bonus": bool(rules.get("title_epithet_bonus", True)),
    }


def race_quality_metrics(races, sample=None, chara_aptitudes=None):
    refs = learning_references()
    compat_rules = global_legacy_compatibility_rules()
    overlap_ids = refs["legacy_overlap_race_ids"] if compat_rules["compatibility_system"] == "legacy" else refs["modern_overlap_race_ids"]
    if not overlap_ids:
        overlap_ids = refs["overlap_race_ids"]
    allowed_grades = compat_rules["overlap_win_grades"] or {"G1", "G2", "G3"}
    aptitudes = chara_aptitudes if isinstance(chara_aptitudes, dict) else sample_chara_aptitudes(sample)
    ignored_off_aptitude = []
    considered_races = []
    for race in races or []:
        dims = off_aptitude_dimensions_for_learning(race, aptitudes)
        if dims:
            ignored_off_aptitude.append((race, dims))
            continue
        considered_races.append(race)
    wins = [race for race in considered_races if race.get("won")]
    losses = [race for race in considered_races if not race.get("won") and as_int(race.get("result_rank")) > 1]
    won_overlap_ids = {as_int(race.get("overlap_race_id")) for race in wins if as_int(race.get("overlap_race_id"))}
    overlap_wins = [
        race for race in wins
        if as_int(race.get("overlap_race_id")) in overlap_ids
        and normalize_grade(race.get("grade")) in allowed_grades
    ]
    g1_wins = [race for race in wins if normalize_grade(race.get("grade")) == "G1"]
    g1_losses = [race for race in losses if normalize_grade(race.get("grade")) == "G1"]
    skill_parsimony_bonus = 0.0
    known_win_skill_counts = []
    for race in wins:
        if race.get("skill_count_at_race") is None:
            continue
        skill_count = max(0, as_int(race.get("skill_count_at_race")))
        grade = normalize_grade(race.get("grade"))
        grade_weight = {"G1": 1.0, "G2": 0.7, "G3": 0.55, "OP": 0.4}.get(grade, 0.3)
        base = 45.0 - min(skill_count, 6) * 12.0
        if skill_count > 6:
            base -= (skill_count - 6) * 8.0
        skill_parsimony_bonus += base * grade_weight
        known_win_skill_counts.append(skill_count)
    completed_sets = [
        row.get("name") for row in refs["epithet_sets"]
        if row.get("race_ids") and row["race_ids"].issubset(won_overlap_ids)
    ]
    legacy_overlap_points = len({as_int(race.get("overlap_race_id")) for race in overlap_wins if as_int(race.get("overlap_race_id"))})
    if compat_rules["same_race_duplicate_bonus"]:
        legacy_overlap_points = len(overlap_wins)
    if compat_rules["title_epithet_bonus"]:
        legacy_overlap_points += len(completed_sets)
    return {
        "race_total": len(considered_races),
        "race_wins": len(wins),
        "race_losses": len(losses),
        "g1_wins": len(g1_wins),
        "g1_losses": len(g1_losses),
        "g2_wins": sum(1 for race in wins if normalize_grade(race.get("grade")) == "G2"),
        "g3_wins": sum(1 for race in wins if normalize_grade(race.get("grade")) == "G3"),
        "affinity_overlap_wins": len(overlap_wins),
        "affinity_overlap_g1_wins": sum(1 for race in overlap_wins if normalize_grade(race.get("grade")) == "G1"),
        "global_legacy_overlap_points": legacy_overlap_points,
        "global_legacy_overlap_grades": sorted(allowed_grades),
        "epithet_sets_completed": len(completed_sets),
        "epithet_set_names": completed_sets[:12],
        "distance_variety": len({str(race.get("distance")) for race in wins if race.get("distance")}),
        "venue_variety": len({str(race.get("venue")) for race in wins if race.get("venue")}),
        "unique_win_race_ids": len(won_overlap_ids),
        "skill_parsimony_bonus": round(skill_parsimony_bonus, 3),
        "known_win_skill_count_samples": len(known_win_skill_counts),
        "avg_win_skill_count": round(sum(known_win_skill_counts) / len(known_win_skill_counts), 3) if known_win_skill_counts else None,
        "ignored_off_aptitude_races": len(ignored_off_aptitude),
        "ignored_off_aptitude_wins": sum(1 for race, _ in ignored_off_aptitude if race.get("won")),
        "ignored_off_aptitude_losses": sum(
            1 for race, _ in ignored_off_aptitude
            if not race.get("won") and as_int(race.get("result_rank")) > 1
        ),
        "ignored_off_aptitude_dimensions": [
            {
                "program_id": as_int(race.get("program_id")),
                "turn": as_int(race.get("turn")),
                "dimensions": dims,
            }
            for race, dims in ignored_off_aptitude[:24]
        ],
    }


def collect_factor_ids(value, depth=0, in_factor_context=False):
    if depth > 10:
        return []
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(collect_factor_ids(item, depth + 1, in_factor_context))
        return result
    if not isinstance(value, dict):
        return []

    result = []
    if "factor_id" in value:
        factor_id = as_int(value.get("factor_id"))
        if factor_id:
            result.append(factor_id)
    elif in_factor_context and "id" in value:
        factor_id = as_int(value.get("id"))
        if factor_id:
            result.append(factor_id)
    for key, item in value.items():
        key_text = str(key)
        child_factor_context = in_factor_context or key_text in {
            "factor_id_array",
            "factor_info_array",
            "effected_factor_array",
            "succession",
            "factors",
            "factor",
            "sparks",
        }
        if key_text == "factor_id_array":
            result.extend(as_int(raw) for raw in safe_items(item) if as_int(raw))
            continue
        if child_factor_context or isinstance(item, dict):
            result.extend(collect_factor_ids(item, depth + 1, child_factor_context))
    return result


def classify_factor(factor_id):
    refs = learning_references()
    row = refs["factor_map"].get(str(factor_id)) or {}
    name = row.get("name") or row.get("factor_name") or ""
    category = str(row.get("category") or row.get("type") or "").lower()
    stars = as_int(row.get("stars") or row.get("star") or row.get("level"))
    if stars <= 0 and factor_id > 1000:
        stars = factor_id % 100
        if stars > 3:
            stars = factor_id % 10
    stars = clamp(stars, 1 if factor_id else 0, 3)

    if not category:
        base = factor_id // 100 if factor_id > 1000 else factor_id
        if base in {101, 102, 103, 104, 105, 1, 2, 3, 4, 5}:
            category = "stat"
        elif 200 <= base < 600:
            category = "aptitude"
        elif 100000 <= factor_id < 2000000:
            category = "race"
        elif 2000000 <= factor_id < 3000000:
            category = "skill"
        elif factor_id >= 9000000:
            category = "scenario"
        else:
            category = "other"

    if "stat" in category or category in {"blue", "basic"}:
        normalized = "stat"
    elif "aptitude" in category or "red" in category:
        normalized = "aptitude"
    elif "unique" in category or "green" in category:
        normalized = "unique"
    elif "race" in category:
        normalized = "race"
    elif "skill" in category or "white" in category:
        normalized = "skill"
    elif "scenario" in category:
        normalized = "scenario"
    else:
        normalized = "other"

    return {"factor_id": factor_id, "name": str(name), "category": normalized, "stars": stars}


def normalize_parent_goals(value):
    if not isinstance(value, dict):
        return {"blue": [], "pink": [], "green": [], "white": []}
    aliases = {
        "red": "pink",
        "aptitude": "pink",
        "stat": "blue",
        "unique": "green",
        "skill": "white",
        "race": "white",
        "scenario": "white",
    }
    goals = {"blue": [], "pink": [], "green": [], "white": []}
    for raw_key, raw_value in value.items():
        key = aliases.get(str(raw_key or "").strip().lower(), str(raw_key or "").strip().lower())
        if key not in goals:
            continue
        if isinstance(raw_value, list):
            parts = raw_value
        else:
            parts = str(raw_value or "").replace(",", "\n").splitlines()
        seen = set()
        for part in parts:
            text = str(part or "").strip()
            folded = text.lower()
            if not text or folded in seen:
                continue
            seen.add(folded)
            goals[key].append(text)
    return goals


def goal_bucket_for_factor(category):
    if category == "stat":
        return "blue"
    if category == "aptitude":
        return "pink"
    if category == "unique":
        return "green"
    if category in {"skill", "race", "scenario"}:
        return "white"
    return ""


def factor_matches_goal(entry, terms):
    if not terms:
        return False
    name = str(entry.get("name") or "").lower()
    factor_id = str(entry.get("factor_id") or "")
    for term in terms:
        folded = str(term or "").strip().lower()
        if not folded:
            continue
        if folded in {"*", "any"}:
            return True
        if folded == factor_id or folded in name or name in folded:
            return True
    return False


def factor_quality_metrics(value, parent_goals=None):
    parent_goals = normalize_parent_goals(parent_goals)
    factor_ids = collect_factor_ids(value)
    seen = Counter(factor_ids)
    entries = [classify_factor(factor_id) for factor_id in factor_ids]
    star_totals = Counter()
    white_by_category = Counter()
    score = 0.0
    blue_3 = 0
    aptitude_3 = 0
    white_count = 0
    white_3 = 0
    white_star_total = 0
    desired_hits = Counter()
    desired_three_star_hits = Counter()
    for entry in entries:
        stars = as_int(entry.get("stars"))
        category = entry.get("category")
        name = entry.get("name") or ""
        star_totals[category] += stars
        if category in WHITE_FACTOR_CATEGORIES:
            white_count += 1
            white_star_total += stars
            white_by_category[category] += 1
            if stars >= 3:
                white_3 += 1
        if category == "stat":
            score += stars * 22.0 * PREFERRED_STAT_FACTORS.get(name, 1.0)
            if stars >= 3:
                blue_3 += 1
                score += 35.0
        elif category == "aptitude":
            score += stars * 16.0 * PREFERRED_APTITUDE_FACTORS.get(name, 1.0)
            if stars >= 3:
                aptitude_3 += 1
                score += 20.0
        elif category == "unique":
            score += stars * 14.0
        elif category == "race":
            score += stars * 8.0
        elif category == "scenario":
            score += stars * 10.0
        elif category == "skill":
            score += stars * 6.0
        else:
            score += stars * 2.0
        bucket = goal_bucket_for_factor(category)
        if bucket and factor_matches_goal(entry, parent_goals.get(bucket) or []):
            desired_hits[bucket] += 1
            score += 40.0 + stars * 16.0
            if stars >= 3:
                desired_three_star_hits[bucket] += 1
                score += 70.0
    return {
        "factor_count": len(entries),
        "unique_factor_count": len(seen),
        "star_totals": dict(star_totals),
        "blue_3_count": blue_3,
        "aptitude_3_count": aptitude_3,
        "white_count": white_count,
        "white_3_count": white_3,
        "white_star_total": white_star_total,
        "white_by_category": dict(white_by_category),
        "desired_hits": dict(desired_hits),
        "desired_three_star_hits": dict(desired_three_star_hits),
        "score": round(score, 3),
    }


def white_factor_metrics(value):
    factor_ids = collect_factor_ids(value)
    entries = [classify_factor(factor_id) for factor_id in factor_ids]
    whites = [entry for entry in entries if entry.get("category") in WHITE_FACTOR_CATEGORIES]
    by_category = Counter(entry.get("category") for entry in whites)
    by_star = Counter(as_int(entry.get("stars")) for entry in whites)
    unique_ids = {as_int(entry.get("factor_id")) for entry in whites if as_int(entry.get("factor_id"))}
    return {
        "white_count": len(whites),
        "white_unique_count": len(unique_ids),
        "white_3_count": sum(1 for entry in whites if as_int(entry.get("stars")) >= 3),
        "white_star_total": sum(as_int(entry.get("stars")) for entry in whites),
        "white_by_category": dict(by_category),
        "white_by_star": {str(key): value for key, value in sorted(by_star.items()) if key},
    }


def estimate_skill_cost(skill_id, name=""):
    skill_id = as_int(skill_id)
    if skill_id <= 0:
        return 0
    # Character uniques and inherited uniques are not normally paid with SP.
    if skill_id < 200000:
        return 0
    text = str(name or "")
    if "◎" in text:
        return 130
    if "○" in text:
        return 110
    if text and any(word in text.lower() for word in ["professor", "maestro", "arc", "star", "miracle"]):
        return 170
    if skill_id % 10 == 2:
        return 180
    return 120


def skill_rows_from_turns(turns):
    if not turns:
        return []
    final = turns[-1] or {}
    rows = []
    for row in final.get("owned_skills") or []:
        if not isinstance(row, dict):
            continue
        rows.append({"skill_id": as_int(row.get("skill_id")), "name": row.get("name") or ""})
    for row in final.get("server_owned_skill_raw") or []:
        if not isinstance(row, dict):
            continue
        skill_id = as_int(row.get("skill_id"))
        if skill_id and skill_id not in {existing.get("skill_id") for existing in rows}:
            rows.append({"skill_id": skill_id, "name": learning_references()["skill_names"].get(skill_id, "")})
    return rows


def skill_rows_from_summary(summary):
    rows = []
    purchase = summary.get("end_skill_purchase") if isinstance(summary.get("end_skill_purchase"), dict) else {}
    bought_rows = safe_items(purchase.get("bought_skill_array")) or safe_items((summary.get("skills") or {}).get("bought"))
    for row in bought_rows:
        if not isinstance(row, dict):
            continue
        skill_id = as_int(row.get("skill_id"))
        rows.append({"skill_id": skill_id, "name": learning_references()["skill_names"].get(skill_id, "")})
    return rows


def skill_purchase_from_summary(summary):
    if not isinstance(summary, dict):
        return {}
    purchase = summary.get("end_skill_purchase") if isinstance(summary.get("end_skill_purchase"), dict) else {}
    skills = summary.get("skills") or {}
    current = summary.get("current") or {}
    bought = safe_items(purchase.get("bought_skill_array")) or safe_items(skills.get("bought"))
    tips = safe_items(purchase.get("available_skill_tips_array")) or safe_items(skills.get("tips"))
    disabled = safe_items(purchase.get("disabled_skill_id_array")) or safe_items(skills.get("disabled"))
    bought_ids = sorted({as_int(row.get("skill_id")) for row in bought if isinstance(row, dict) and as_int(row.get("skill_id"))})
    bought_groups = {skill_id if skill_id < 100000 else skill_id // 10 for skill_id in bought_ids}
    tip_rows = []
    for row in tips:
        if not isinstance(row, dict):
            continue
        group_id = as_int(row.get("group_id"))
        if not group_id:
            continue
        tip_rows.append({
            "group_id": group_id,
            "rarity": as_int(row.get("rarity")),
            "hint_level": as_int(row.get("level")),
            "bought_group": group_id in bought_groups,
        })
    unbought = [row for row in tip_rows if not row.get("bought_group")]
    return {
        "skill_point_budget": as_int(purchase.get("skill_point_budget") if purchase else current.get("skill_point")),
        "capture_phase": purchase.get("capture_phase") if purchase else "",
        "bought_skill_ids": bought_ids,
        "bought_skill_count": len(bought_ids),
        "available_hint_count": len(tip_rows),
        "unbought_hint_count": len(unbought),
        "max_hint_level": max([as_int(row.get("hint_level")) for row in tip_rows] or [0]),
        "avg_hint_level": round(sum(as_int(row.get("hint_level")) for row in tip_rows) / len(tip_rows), 3) if tip_rows else 0.0,
        "disabled_skill_id_count": len([value for value in disabled if as_int(value)]),
        "available_hint_rows": tip_rows,
    }


def skill_quality_metrics(skill_rows, final_sp, purchase_snapshot=None):
    unique = {}
    for row in skill_rows or []:
        skill_id = as_int(row.get("skill_id"))
        if skill_id:
            unique[skill_id] = row
    estimated_spent = sum(estimate_skill_cost(skill_id, row.get("name")) for skill_id, row in unique.items())
    final_sp = as_int(final_sp)
    unspent_penalty = max(0, final_sp - 160) * 0.24
    purchase_snapshot = purchase_snapshot or {}
    # end_skill_purchase_count tells us how many skills were bought at the
    # career's final skill-purchase phase (i.e., after all races/training).
    # Used by estimate_score to reward the "save SP all career, dump at end"
    # parent-farming flow.
    end_purchase_count = as_int(purchase_snapshot.get("bought_skill_count"))
    return {
        "learned_skill_count": len(unique),
        "estimated_skill_spent": estimated_spent,
        "final_skill_point": final_sp,
        "available_hint_count": as_int(purchase_snapshot.get("available_hint_count")),
        "unbought_hint_count": as_int(purchase_snapshot.get("unbought_hint_count")),
        "max_hint_level": as_int(purchase_snapshot.get("max_hint_level")),
        "avg_hint_level": as_float(purchase_snapshot.get("avg_hint_level")),
        "skill_point_budget": as_int(purchase_snapshot.get("skill_point_budget"), final_sp),
        "end_purchase_count": end_purchase_count,
        "spend_score": round(min(estimated_spent, 2600) * 0.08 - unspent_penalty, 3),
    }


def item_phase_label(turn):
    turn = as_int(turn)
    if turn <= 24:
        return "early"
    if turn <= 48:
        return "mid"
    if turn <= 64:
        return "late"
    return "climax"


def _item_name_from_turn(turn, row):
    if isinstance(row, dict):
        item_id = as_int(row.get("item_id"))
        if item_id:
            return ITEM_NAMES.get(item_id, "")
        name = str(row.get("name") or "").strip()
        if name:
            return name
        shop_item_id = as_int(row.get("shop_item_id"))
        if shop_item_id:
            for source in [
                (turn or {}).get("shop_rows_enriched") or [],
                (turn or {}).get("server_shop_rows_raw") or [],
                (row.get("payload_shop_rows") if isinstance(row.get("payload_shop_rows"), list) else []),
            ]:
                for shop_row in source:
                    if not isinstance(shop_row, dict):
                        continue
                    if as_int(shop_row.get("shop_item_id")) == shop_item_id:
                        item_id = as_int(shop_row.get("item_id"))
                        if item_id:
                            return ITEM_NAMES.get(item_id, "")
    return ""


def extract_item_decisions_from_turns(turns):
    rows = []
    for turn in turns or []:
        turn_num = as_int(turn.get("turn"))
        phase = item_phase_label(turn_num)
        for attempt in turn.get("item_buy_attempts") or []:
            if not isinstance(attempt, dict):
                continue
            result = attempt.get("result") or {}
            selected_rows = attempt.get("selected") or attempt.get("items") or attempt.get("attempt") or attempt.get("payload") or []
            for row in selected_rows:
                if not isinstance(row, dict):
                    continue
                item_id = as_int(row.get("item_id"))
                name = _item_name_from_turn(turn, row)
                if not item_id and name:
                    for known_id, known_name in ITEM_NAMES.items():
                        if known_name == name:
                            item_id = known_id
                            break
                if item_id <= 0 and not name:
                    continue
                rows.append({
                    "kind": "buy",
                    "turn": turn_num,
                    "phase": phase,
                    "item_id": item_id,
                    "name": name or ITEM_NAMES.get(item_id, ""),
                    "cost": as_int(row.get("cost") or row.get("coin_num")),
                    "current_num": as_int(row.get("current_num")),
                    "result_ok": bool(result.get("ok", result.get("result") == "ok")),
                })
        for attempt in turn.get("item_usage_attempts") or []:
            if not isinstance(attempt, dict):
                continue
            result = attempt.get("result") or {}
            selected_rows = attempt.get("selected") or attempt.get("items") or attempt.get("attempt") or attempt.get("payload") or []
            for row in selected_rows:
                if not isinstance(row, dict):
                    continue
                item_id = as_int(row.get("item_id"))
                name = str(row.get("name") or ITEM_NAMES.get(item_id, "")).strip()
                if item_id <= 0 and not name:
                    continue
                rows.append({
                    "kind": "use",
                    "turn": turn_num,
                    "phase": phase,
                    "item_id": item_id,
                    "name": name,
                    "use_num": as_int(row.get("use_num") or row.get("num") or row.get("item_num"), 1),
                    "result_ok": bool(result.get("ok", result.get("result") == "ok")),
                })
    return rows


def training_feature_from_option(option, stats=None):
    command_id = as_int(option.get("command_id"))
    idx = TRAINING_COMMANDS.get(command_id)
    if idx is None:
        return None
    stat_gain = dict(option.get("stat_gain") or {})
    if not stat_gain:
        for item in safe_items(option.get("params_inc_dec_info_array")):
            stat = TARGET_TO_STAT.get(as_int(item.get("target_type")))
            if stat:
                stat_gain[stat] = stat_gain.get(stat, 0) + as_float(item.get("value"))
    partners = option.get("partners")
    if partners is None:
        partners = safe_items(option.get("training_partner_array"))
    hints = option.get("tips_event_partner_array")
    hint_ids = set(safe_items(hints)) if hints is not None else set()
    partner_rows = []
    if isinstance(partners, list) and partners and isinstance(partners[0], dict):
        partner_count = len(partners)
        deck_partner_count = sum(1 for row in partners if row.get("deck_partner"))
        rainbow_count = sum(1 for row in partners if row.get("rainbow"))
        hint_count = sum(1 for row in partners if row.get("hint"))
        high_bond_count = sum(1 for row in partners if as_int(row.get("bond")) >= 80)
        partner_rows = [dict(row) for row in partners if isinstance(row, dict)]
    else:
        partner_ids = [as_int(pid) for pid in partners or []]
        partner_count = len(partner_ids)
        deck_partner_count = sum(1 for pid in partner_ids if 1 <= pid <= 6)
        rainbow_count = 0
        hint_count = sum(1 for pid in partner_ids if pid in hint_ids)
        high_bond_count = 0
        partner_rows = [{"target_id": pid, "hint": pid in hint_ids} for pid in partner_ids if pid > 0]
    weighted_gain = option.get("weighted_total_gain")
    if weighted_gain is None:
        weighted_gain = (
            max(0.0, as_float(stat_gain.get("speed"))) * 1.0
            + max(0.0, as_float(stat_gain.get("stamina"))) * 1.0
            + max(0.0, as_float(stat_gain.get("power"))) * 1.0
            + max(0.0, as_float(stat_gain.get("guts"))) * 0.85
            + max(0.0, as_float(stat_gain.get("wit"))) * 1.0
            + max(0.0, as_float(stat_gain.get("skill_point"))) * 0.5
        )
    return {
        "command_id": command_id,
        "command_group_id": as_int(option.get("command_group_id")),
        "idx": idx,
        "name": option.get("name") or TRAINING_NAMES[idx],
        "failure_rate": as_float(option.get("failure_rate")),
        "stat_gain": stat_gain,
        "weighted_gain": as_float(weighted_gain),
        "weighted_total_gain": as_float(weighted_gain),
        "partner_count": as_float(option.get("partner_count"), partner_count),
        "deck_partner_count": as_float(option.get("deck_partner_count"), deck_partner_count),
        "rainbow_count": as_float(option.get("rainbow_count"), rainbow_count),
        "hint_count": as_float(option.get("hint_count"), hint_count),
        "high_bond_count": as_float(option.get("high_bond_count"), high_bond_count),
        "skill_point_gain": as_float(stat_gain.get("skill_point")),
        "energy_delta": as_float(stat_gain.get("hp")),
        "hp": as_float((stats or {}).get("hp") if isinstance(stats, dict) else 0),
        "skill_point": as_float((stats or {}).get("skill_point") if isinstance(stats, dict) else 0),
        "facility_level": as_int(option.get("facility_level"), as_int(option.get("level"))),
        "facility_progress": as_int(option.get("facility_progress")),
        "facility_until_next_level": as_int(option.get("facility_until_next_level"), -1),
        "partners": partner_rows,
        "selected_partner_ids": [as_int(row.get("target_id")) for row in partner_rows if as_int(row.get("target_id")) > 0],
    }


def _snapshot_for_turn(turn):
    snapshot = turn.get("training_snapshot") if isinstance(turn, dict) else None
    if not isinstance(snapshot, dict):
        return None
    stats = turn.get("stats") or snapshot.get("stats") or {}
    rows = []
    for option in snapshot.get("trainings") or []:
        feature = training_feature_from_option(option, stats)
        if feature:
            rows.append(feature)
    if not rows:
        return None
    best = max(
        rows,
        key=lambda row: (
            as_float(row.get("weighted_gain")),
            as_float(row.get("rainbow_count")),
            as_float(row.get("hint_count")),
            -as_float(row.get("failure_rate")),
        ),
        default=None,
    )
    return {
        "turn": as_int(turn.get("turn")),
        "stats": stats,
        "trainings": rows,
        "best_training": {
            "command_id": as_int(best.get("command_id")),
            "name": best.get("name"),
            "weighted_gain": as_float(best.get("weighted_gain")),
        } if best else None,
    }


def _support_bond_map(turn):
    raw = (turn or {}).get("support_bonds")
    if isinstance(raw, dict):
        result = {}
        for key, value in raw.items():
            target_id = as_int(key)
            if target_id > 0:
                result[target_id] = as_int(value)
        if result:
            return result
    result = {}
    for row in (turn or {}).get("evaluation_info_array") or []:
        if not isinstance(row, dict):
            continue
        target_id = as_int(row.get("target_id"))
        if target_id > 0:
            result[target_id] = as_int(row.get("evaluation"))
    return result


def _future_rows_in_window(turns, start_index, lookahead=4):
    if not isinstance(turns, list) or start_index < 0 or start_index >= len(turns):
        return []
    current_turn = as_int((turns[start_index] or {}).get("turn"))
    rows = []
    for row in turns[start_index + 1:]:
        row_turn = as_int((row or {}).get("turn"))
        if row_turn <= current_turn:
            continue
        delta = row_turn - current_turn
        if delta > max(1, lookahead):
            break
        rows.append((delta, row))
    return rows


def _best_training_row(turn):
    snapshot = _snapshot_for_turn(turn)
    if not isinstance(snapshot, dict):
        return None
    trainings = snapshot.get("trainings") or []
    if not trainings:
        return None
    return max(
        trainings,
        key=lambda row: (
            as_float(row.get("weighted_gain")),
            as_float(row.get("rainbow_count")),
            as_float(row.get("hint_count")),
            -as_float(row.get("failure_rate")),
        ),
        default=None,
    )


def _future_progress_metrics(turns, start_index, partner_ids=None, lookahead=4):
    future_rows = _future_rows_in_window(turns, start_index, lookahead=lookahead)
    if not future_rows:
        return {}
    current_turn = turns[start_index] or {}
    current_stats = current_turn.get("stats") or {}
    window_turns, target_turn = future_rows[-1]
    future_stats = target_turn.get("stats") or {}
    stat_delta = {}
    total_gain = 0.0
    for key in ALL_STAT_KEYS:
        value = max(0.0, as_float(future_stats.get(key)) - as_float(current_stats.get(key)))
        if value > 0:
            stat_delta[key] = round(value, 4)
            total_gain += value
    current_bonds = _support_bond_map(current_turn)
    future_bonds = _support_bond_map(target_turn)
    partner_bond_gain = 0.0
    rainbow_unlocks = 0
    for partner_id in partner_ids or []:
        pid = as_int(partner_id)
        if pid <= 0:
            continue
        before = as_int(current_bonds.get(pid))
        after = as_int(future_bonds.get(pid))
        if after > before:
            partner_bond_gain += (after - before)
        if before < 80 <= after:
            rainbow_unlocks += 1
    current_best = _best_training_row(current_turn)
    best_future = None
    best_future_turn = 0
    best_future_gain = 0.0
    selected_partner_reuse = 0
    selected_partner_best_turn = 0
    partner_ids = [as_int(pid) for pid in (partner_ids or []) if as_int(pid) > 0]
    for delta, row in future_rows:
        best_row = _best_training_row(row)
        if not isinstance(best_row, dict):
            continue
        gain = as_float(best_row.get("weighted_gain"))
        if gain > best_future_gain:
            best_future = best_row
            best_future_turn = delta
            best_future_gain = gain
        if partner_ids:
            reuse = len({as_int(pid) for pid in (best_row.get("selected_partner_ids") or []) if as_int(pid) > 0} & set(partner_ids))
            if reuse > selected_partner_reuse:
                selected_partner_reuse = reuse
                selected_partner_best_turn = delta
    return {
        "future_window_turns": int(window_turns or 0),
        "future_stat_delta": stat_delta,
        "future_total_gain": round(total_gain, 4),
        "future_partner_bond_gain": round(partner_bond_gain, 4),
        "future_rainbow_unlocks": int(rainbow_unlocks),
        "future_best_training_turns": int(best_future_turn or 0),
        "future_best_training_gain": round(best_future_gain, 4),
        "future_best_training_gain_delta": round(max(0.0, best_future_gain - as_float((current_best or {}).get("weighted_gain"))), 4),
        "future_best_training_name": (best_future or {}).get("name"),
        "future_selected_partner_reuse": int(selected_partner_reuse),
        "future_selected_partner_reuse_turns": int(selected_partner_best_turn or 0),
    }


def _long_horizon_metrics(turns, start_index, partner_ids=None, windows=None):
    metrics = {}
    aggregate = {
        "future_window_turns": 0,
        "future_total_gain": 0.0,
        "future_partner_bond_gain": 0.0,
        "future_rainbow_unlocks": 0,
        "future_best_training_gain": 0.0,
        "future_best_training_gain_delta": 0.0,
        "future_selected_partner_reuse": 0,
    }
    windows = tuple(windows or LONG_HORIZON_WINDOWS)
    for lookahead in windows:
        row = _future_progress_metrics(turns, start_index, partner_ids=partner_ids, lookahead=lookahead)
        if not row:
            continue
        metrics[str(lookahead)] = {
            "window_turns": int(row.get("future_window_turns") or 0),
            "stat_delta": dict(row.get("future_stat_delta") or {}),
            "total_gain": round(as_float(row.get("future_total_gain")), 4),
            "partner_bond_gain": round(as_float(row.get("future_partner_bond_gain")), 4),
            "rainbow_unlocks": int(row.get("future_rainbow_unlocks") or 0),
            "best_training_turns": int(row.get("future_best_training_turns") or 0),
            "best_training_gain": round(as_float(row.get("future_best_training_gain")), 4),
            "best_training_gain_delta": round(as_float(row.get("future_best_training_gain_delta")), 4),
            "best_training_name": row.get("future_best_training_name"),
            "selected_partner_best_training_reuse": int(row.get("future_selected_partner_reuse") or 0),
            "selected_partner_reuse_turns": int(row.get("future_selected_partner_reuse_turns") or 0),
        }
    preferred = metrics.get("4") or metrics.get("2") or metrics.get("8")
    if preferred:
        aggregate["future_window_turns"] = int(preferred.get("window_turns") or 0)
        aggregate["future_total_gain"] = round(as_float(preferred.get("total_gain")), 4)
        aggregate["future_partner_bond_gain"] = round(as_float(preferred.get("partner_bond_gain")), 4)
        aggregate["future_rainbow_unlocks"] = int(preferred.get("rainbow_unlocks") or 0)
        aggregate["future_best_training_gain"] = round(as_float(preferred.get("best_training_gain")), 4)
        aggregate["future_best_training_gain_delta"] = round(as_float(preferred.get("best_training_gain_delta")), 4)
        aggregate["future_selected_partner_reuse"] = int(preferred.get("selected_partner_best_training_reuse") or 0)
    if metrics:
        aggregate["future_window_metrics"] = metrics
    return aggregate


def selected_training_action(turn):
    selected = str(turn.get("selected_action") or "").lower()
    command = turn.get("current_command") or {}
    command_id = as_int(command.get("command_id"))
    if command_id not in TRAINING_COMMANDS:
        return None
    if selected not in {"command", "train", "training"}:
        # Manual captures use selected_action=train; older bot reports use command.
        if "training" not in str(turn.get("decision_reason") or "").lower():
            return None
    trainings = ((turn.get("training_snapshot") or {}).get("trainings") or [])
    option = None
    for row in trainings:
        if as_int(row.get("command_id")) == command_id:
            option = row
            break
    if option is None:
        option = {"command_id": command_id}
    action = training_feature_from_option(option, turn.get("stats") or {})
    if not action:
        return None
    action["turn"] = as_int(turn.get("turn"))
    action["period"] = period_index(action["turn"])
    action["extra_phase"] = extra_phase_index(action["turn"])
    snapshot = _snapshot_for_turn(turn)
    if snapshot:
        action["training_snapshot"] = snapshot
    understanding = turn.get("decision_understanding")
    if isinstance(understanding, dict) and understanding:
        action["decision_understanding"] = dict(understanding)
        signals = understanding.get("signals") or {}
        if isinstance(signals, dict):
            for source_key, target_key in (
                ("facility_level", "facility_level"),
                ("facility_progress", "facility_progress"),
                ("facility_until_next_level", "facility_until_next_level"),
            ):
                current_value = action.get(target_key)
                missing = current_value is None or current_value == 0 or (target_key == "facility_until_next_level" and current_value == -1)
                if signals.get(source_key) is not None and missing:
                    action[target_key] = as_int(signals.get(source_key))
    return action


def extract_actions_from_turns(turns):
    actions = []
    ordered_turns = sorted(turns or [], key=lambda row: as_int((row or {}).get("turn")))
    for idx, turn in enumerate(ordered_turns):
        action = selected_training_action(turn)
        if action:
            action.update(_long_horizon_metrics(
                ordered_turns,
                idx,
                partner_ids=action.get("selected_partner_ids") or [],
            ))
            actions.append(action)
    return actions


def selected_turn_kind(turn):
    if not isinstance(turn, dict):
        return ""
    understanding = turn.get("decision_understanding") or {}
    selected = str(
        turn.get("selected_action")
        or (understanding.get("action") if isinstance(understanding, dict) else "")
        or turn.get("current_action_taken")
        or ""
    ).strip().lower()
    if selected == "command":
        command = turn.get("current_command") or {}
        command_type = as_int(command.get("command_type"))
        if command_type == 7:
            return "rest"
        if command_type == 3:
            return "recreation"
        if command_type == 8:
            return "medic"
        return "training"
    if selected in {"rest", "recreation", "medic", "race", "finish", "event"}:
        return selected
    return selected


def selected_support_action(turn):
    if not isinstance(turn, dict):
        return None
    understanding = turn.get("decision_understanding") or {}
    signals = understanding.get("signals") if isinstance(understanding, dict) else {}
    selected = selected_turn_kind(turn)
    if selected not in {"rest", "recreation", "medic", "race"}:
        return None
    stats = turn.get("stats") or {}
    hp = as_float(
        stats.get("hp"),
        as_float(
            turn.get("current_vital"),
            as_float((turn.get("current_command") or {}).get("current_vital")),
        ),
    )
    row = {
        "kind": selected,
        "turn": as_int(turn.get("turn")),
        "period": period_index(as_int(turn.get("turn"))),
        "extra_phase": extra_phase_index(as_int(turn.get("turn"))),
        "hp": hp,
        "motivation": as_int(stats.get("motivation"), as_int(turn.get("motivation"))),
        "decision_understanding": dict(understanding) if isinstance(understanding, dict) and understanding else {},
    }
    if isinstance(signals, dict):
        row["optional_race"] = bool(signals.get("optional"))
        row["forced_race"] = bool(signals.get("forced"))
        row["program_id"] = as_int(signals.get("program_id"))
    if not row.get("program_id") and selected == "race":
        row["program_id"] = as_int((turn.get("current_command") or {}).get("program_id"))
    return row


def extract_support_actions_from_turns(turns):
    actions = []
    for turn in sorted(turns or [], key=lambda row: as_int((row or {}).get("turn"))):
        action = selected_support_action(turn)
        if action:
            actions.append(action)
    return actions


def future_effect_curve_from_turns(turns):
    rows = sorted(turns or [], key=lambda row: as_int((row or {}).get("turn")))
    out = []
    for current, nxt in zip(rows, rows[1:]):
        if not isinstance(current, dict) or not isinstance(nxt, dict):
            continue
        turn = as_int(current.get("turn"))
        next_turn = as_int(nxt.get("turn"))
        if turn <= 0 or next_turn != turn + 1:
            continue
        current_stats = current.get("stats") or {}
        next_stats = nxt.get("stats") or {}
        if not current_stats or not next_stats:
            continue
        delta = {}
        usable = False
        for key in FUTURE_EFFECT_KEYS:
            value = as_float(next_stats.get(key)) - as_float(current_stats.get(key))
            delta[key] = round(value, 4)
            if value:
                usable = True
        if not usable:
            continue
        kind = selected_turn_kind(current) or "unknown"
        row = {
            "turn": turn,
            "next_turn": next_turn,
            "kind": kind,
            "delta": delta,
        }
        if kind == "race":
            support_action = selected_support_action(current) or {}
            program_id = as_int(support_action.get("program_id"))
            if not program_id:
                program_id = as_int((current.get("current_command") or {}).get("program_id"))
            if program_id > 0:
                row["program_id"] = program_id
        out.append(row)
    return out


def infer_manual_actions_from_summaries(summaries):
    actions = []
    ordered = sorted(summaries, key=lambda row: (as_int(row.get("index")), as_int((row.get("current") or {}).get("turn"))))
    for prev, nxt in zip(ordered, ordered[1:]):
        prev_cur = prev.get("current") or {}
        next_cur = nxt.get("current") or {}
        prev_turn = as_int(prev_cur.get("turn"))
        next_turn = as_int(next_cur.get("turn"))
        if next_turn <= prev_turn:
            continue
        if next_turn - prev_turn > 2:
            continue
        commands = safe_items((prev.get("home") or {}).get("commands"))
        options = []
        for command in commands:
            if as_int(command.get("command_type")) != 1:
                continue
            feature = training_feature_from_option(command, {
                "hp": as_float(prev_cur.get("vital")),
                "skill_point": as_float(prev_cur.get("skill_point")),
            })
            if feature:
                options.append((command, feature))
        if not options:
            continue
        stat_delta = {}
        for key in ALL_STAT_KEYS:
            stat_delta[key] = as_float(next_cur.get(key)) - as_float(prev_cur.get(key))
        stat_delta["hp"] = as_float(next_cur.get("vital")) - as_float(prev_cur.get("vital"))
        best = None
        best_error = None
        for command, feature in options:
            gain = feature.get("stat_gain") or {}
            error = 0.0
            observed_total = 0.0
            expected_total = 0.0
            for key in ALL_STAT_KEYS + ["hp"]:
                observed = stat_delta.get(key, 0.0)
                expected = as_float(gain.get(key))
                if key == "hp" and expected == 0:
                    continue
                observed_total += abs(observed)
                expected_total += abs(expected)
                error += abs(observed - expected)
            if best_error is None or error < best_error:
                best_error = error
                best = feature
        if not best:
            continue
        # Event chains can mutate stats after a command. Keep only clear training-like deltas.
        if best_error is not None and best_error > max(35.0, best.get("weighted_gain", 0.0) * 1.8):
            continue
        best = dict(best)
        best["training_snapshot"] = {"turn": prev_turn, "trainings": [row for _, row in options]}
        best["turn"] = prev_turn
        best["period"] = period_index(prev_turn)
        best["extra_phase"] = extra_phase_index(prev_turn)
        best["inferred"] = True
        metrics = {}
        for lookahead in LONG_HORIZON_WINDOWS:
            future_target = None
            for later in ordered:
                later_turn = as_int((later.get("current") or {}).get("turn"))
                if later_turn <= prev_turn:
                    continue
                if later_turn - prev_turn > lookahead:
                    break
                future_target = later
            if not future_target:
                continue
            future_cur = future_target.get("current") or {}
            future_delta = {}
            future_total_gain = 0.0
            for key in ALL_STAT_KEYS:
                value = max(0.0, as_float(future_cur.get(key)) - as_float(prev_cur.get(key)))
                if value > 0:
                    future_delta[key] = round(value, 4)
                    future_total_gain += value
            metrics[str(lookahead)] = {
                "window_turns": max(0, as_int(future_cur.get("turn")) - prev_turn),
                "stat_delta": future_delta,
                "total_gain": round(future_total_gain, 4),
                "partner_bond_gain": 0.0,
                "rainbow_unlocks": 0,
                "best_training_gain": round(as_float(best.get("weighted_gain")), 4),
                "best_training_gain_delta": 0.0,
                "selected_partner_best_training_reuse": 0,
            }
        if metrics:
            preferred = metrics.get("4") or metrics.get("2") or metrics.get("8")
            best["future_window_metrics"] = metrics
            best["future_window_turns"] = int(preferred.get("window_turns") or 0)
            best["future_stat_delta"] = dict(preferred.get("stat_delta") or {})
            best["future_total_gain"] = round(as_float(preferred.get("total_gain")), 4)
            best["future_partner_bond_gain"] = 0.0
            best["future_rainbow_unlocks"] = 0
        actions.append(best)
    return actions


def normalize_bot_like_log(path, data, source, parent_goals=None):
    turns = data.get("turns") or []
    if not isinstance(turns, list):
        return None
    last_turn = turns[-1] if turns else {}
    capture = full_career_capture_details(turns, status=data.get("status"))
    final_stats = final_stats_from_turn(last_turn)
    races = race_entries_from_turns(turns)
    run_context = data.get("run_context") or {}
    race_quality = race_quality_metrics(races, sample=run_context)
    wins = as_int(race_quality.get("race_wins"))
    losses = as_int(race_quality.get("race_losses"))
    factor_quality = factor_quality_metrics(data, parent_goals=parent_goals)
    factor_score = factor_score_from_any(data)
    skill_quality = skill_quality_metrics(skill_rows_from_turns(turns), final_stats.get("skill_point"))
    status = str(data.get("status") or "unknown")
    score = estimate_score(
        final_stats,
        wins=wins,
        losses=losses,
        status=status,
        factor_score=factor_score,
        race_quality=race_quality,
        factor_quality=factor_quality,
        skill_quality=skill_quality,
        parent_goals=parent_goals,
    )
    actions = extract_actions_from_turns(turns)
    support_actions = extract_support_actions_from_turns(turns)
    item_decisions = extract_item_decisions_from_turns(turns)
    event_choices = _extract_event_choices_from_turns(turns, parent_goals=parent_goals)
    race_results = _extract_race_results_from_turns(turns)
    motivation_curve = motivation_curve_from_turns(turns)
    hp_curve = hp_curve_from_turns(turns)
    stat_curve = stat_curve_from_turns(turns)
    future_effect_curve = future_effect_curve_from_turns(turns)
    return {
        "source": source,
        "path": str(path),
        "created_at": data.get("created_at"),
        "started_at": data.get("started_at"),
        "ended_at": data.get("ended_at"),
        "preset_name": data.get("preset_name"),
        "run_context": run_context,
        "rank_score": as_int(data.get("rank_score")) if data.get("rank_score") is not None else None,
        "rank": as_int(data.get("rank")) if data.get("rank") is not None else None,
        "rank_label": str(data.get("rank_label") or "").strip(),
        "desired_parent_sparks": run_context.get("desired_parent_sparks") or data.get("desired_parent_sparks") or {},
        "status": status,
        "has_turn_data": True,
        "first_turn": capture["first_turn"],
        "has_turn_one": capture["has_turn_one"],
        "has_turn_78": capture["has_turn_78"],
        "observed_turn_count": capture.get("observed_turn_count"),
        "coverage_ratio": capture.get("coverage_ratio"),
        "full_career_capture": capture["full"],
        "final_turn": as_int(data.get("final_turn") or (last_turn.get("turn") if last_turn else 0)),
        "turn_count": len(turns),
        "final_stats": final_stats,
        "race_wins": wins,
        "race_losses": losses,
        "factor_score": factor_score,
        "race_quality": race_quality,
        "factor_quality": factor_quality,
        "skill_quality": skill_quality,
        "score": score,
        "actions": actions,
        "support_actions": support_actions,
        "item_decisions": item_decisions,
        "event_choices": event_choices,
        "race_results": race_results,
        "motivation_curve": motivation_curve,
        "hp_curve": hp_curve,
        "stat_curve": stat_curve,
        "future_effect_curve": future_effect_curve,
        "sample_weight": 1.35 if source.startswith("manual") else 1.0,
    }


def _extract_event_choices_from_turns(turns, parent_goals=None):
    """Pull `event_choice` rows out of a career log's per-turn events
    arrays. Keeps just the fields the learner needs (story_id +
    choice_index) so samples don't grow with the full event payload.
    Returns [] when no event-choice records exist (older logs)."""
    primary_blue = ""
    normalized_goals = normalize_parent_goals(parent_goals)
    if isinstance(normalized_goals, dict):
        blue = normalized_goals.get("blue") or []
        if blue:
            primary_blue = str(blue[0] or "").strip().lower()
    out = []
    for turn in turns or []:
        if not isinstance(turn, dict):
            continue
        turn_num = as_int(turn.get("turn"))
        for row in turn.get("events") or []:
            if not isinstance(row, dict):
                continue
            if row.get("event") != "event_choice":
                continue
            story_id = str(row.get("story_id") or "").strip()
            choice_index = row.get("choice_index")
            if not story_id or choice_index is None:
                continue
            try:
                choice_index = int(choice_index)
            except (TypeError, ValueError):
                continue
            out.append({
                "story_id": story_id,
                "choice_index": choice_index,
                "turn": turn_num,
                "phase": item_phase_label(turn_num),
                "blue_target": primary_blue,
            })
    return out


def _extract_race_results_from_turns(turns):
    """Pull `race_result` rows out of a career log's per-turn events
    so the race-continue learner can aggregate recovery rates by
    program_id without re-reading the full career_log JSON.

    This also preserves just enough race-time context for the
    race-success learner:
    - visible stats at the turn the race resolved
    - running style used
    - learned skill count at race time

    We intentionally store only counts/bands here, not specific owned
    skill ids, so wins do not teach "buy these exact skills to win"
    cargo cult behavior.
    """
    def _skill_count_for_turn(turn_row):
        if not isinstance(turn_row, dict):
            return None
        found = False
        owned = set()
        for key in ("owned_skills", "server_owned_skill_raw"):
            rows = turn_row.get(key)
            if not isinstance(rows, list):
                continue
            found = True
            for row in rows:
                if isinstance(row, dict):
                    skill_id = as_int(row.get("skill_id"))
                else:
                    skill_id = as_int(row)
                if skill_id:
                    owned.add(skill_id)
        if not found:
            return None
        return len(owned)

    def _stats_for_turn(turn_row):
        stats = (turn_row or {}).get("stats")
        if not isinstance(stats, dict):
            return {}
        result = {}
        for key in ("speed", "stamina", "power", "guts", "wit", "skill_point"):
            if key in stats:
                result[key] = as_int(stats.get(key))
        return result

    def _running_style_for_turn(turn_row, program_id):
        for history_row in reversed((turn_row or {}).get("race_history") or []):
            if not isinstance(history_row, dict):
                continue
            if program_id and as_int(history_row.get("program_id")) != as_int(program_id):
                continue
            style = as_int(history_row.get("running_style"))
            if style:
                return style
        return 0

    out = []
    for turn in turns or []:
        if not isinstance(turn, dict):
            continue
        for row in turn.get("events") or []:
            if not isinstance(row, dict):
                continue
            if row.get("event") != "race_result":
                continue
            program_id = row.get("program_id")
            slim = {
                "turn": as_int(row.get("turn") or turn.get("turn")),
                "program_id": program_id,
                "won": bool(row.get("won")),
                "continued": bool(row.get("continued")),
                "finish_rank": as_int(row.get("finish_rank") or row.get("result_rank")),
                "status": row.get("status"),
                "is_g1": bool(row.get("is_g1")),
                "race": dict(row.get("race") or {}) if isinstance(row.get("race"), dict) else {},
            }
            running_style = as_int(row.get("running_style")) or _running_style_for_turn(turn, program_id)
            if running_style:
                slim["running_style"] = running_style
            skill_count = _skill_count_for_turn(turn)
            if skill_count is not None:
                slim["skill_count_at_race"] = skill_count
            stats_at_race = _stats_for_turn(turn)
            if stats_at_race:
                slim["stats_at_race"] = stats_at_race
            for key in ("continue_resources", "continue_attempts", "continue_resource", "continue_failed_ranks"):
                if key in row:
                    slim[key] = row[key]
            out.append(slim)
    return out


def load_bot_logs(runtime_root, recent=None, parent_goals=None):
    samples = []
    bot_dir = runtime_root / "bot_logs"
    if not bot_dir.exists():
        return samples
    files = sorted(bot_dir.glob("career_log_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if recent:
        files = files[:recent]
    for path in files:
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        if not supported_career_log(data):
            print(f"unsupported career log schema {data.get('schema')!r}; skipping {path}", flush=True)
            continue
        sample = normalize_bot_like_log(path, data, "bot", parent_goals=parent_goals)
        if sample:
            samples.append(sample)
    return samples


def load_manual_legacy_logs(runtime_root, recent=None, parent_goals=None):
    samples = []
    manual_dir = runtime_root / "manual_career_logs"
    if not manual_dir.exists():
        return samples
    files = sorted(manual_dir.glob("career_log_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    latest = manual_dir / "latest_career_log.json"
    if latest.exists():
        files.insert(0, latest)
    seen = set()
    unique = []
    for path in files:
        if path.resolve() in seen:
            continue
        seen.add(path.resolve())
        unique.append(path)
    if recent:
        unique = unique[:recent]
    for path in unique:
        data = read_json(path)
        if not isinstance(data, dict):
            continue
        if not supported_career_log(data):
            print(f"unsupported career log schema {data.get('schema')!r}; skipping {path}", flush=True)
            continue
        if not isinstance(data.get("turns"), list):
            continue
        sample = normalize_bot_like_log(path, data, "manual_trace", parent_goals=parent_goals)
        if sample:
            samples.append(sample)
    return samples


def _hachimi_capture_career_dirs():
    """Locate hachimi sweepy_capture's career output folder if installed.

    The sweepy_capture.dll add-on writes manual career data to
    `<steam_install>/UmamusumePrettyDerby/hachimi/Career turn data/`. The
    folder layout matches what `load_manual_hachimi_careers` already parses
    (manifest.json + summary_events.jsonl per career), so once discovered
    the careers feed the learner with no format conversion.

    Steam install paths vary, so we probe the common ones plus an env
    override `SWEEPY_HACHIMI_CAREER_DIR`. Returns a list of Path objects
    pointing at the "Career turn data" directory (not the careers inside).

    Auto-disables under unittest/pytest so tests that scan tempdirs don't
    accidentally pick up real user captures from disk.

    KNOWN LIMITATION — multi-account: hachimi captures do NOT include
    `viewer_id` anywhere in the per-career data, so the loader cannot tell
    which game account a given capture came from. If you switch accounts
    on the same Steam install, captures from both accounts will mix into
    the learner. Mitigation: set `learning_allowed_chara_ids` in the
    preset to a list of chara_ids (or single_mode_chara_ids) from the
    account you want to learn from; anything else gets skipped at load
    time. If you switch accounts entirely, also delete or move the
    `Career turn data` folder.
    """
    import os as _os
    import sys as _sys
    if "unittest" in _sys.modules or "pytest" in _sys.modules:
        return []

    candidates = []
    env_override = _os.environ.get("SWEEPY_HACHIMI_CAREER_DIR")
    if env_override:
        candidates.append(Path(env_override))
    candidates.extend([
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\UmamusumePrettyDerby\hachimi\Career turn data"),
        Path(r"C:\Program Files\Steam\steamapps\common\UmamusumePrettyDerby\hachimi\Career turn data"),
        Path.home() / "AppData" / "Local" / "Steam" / "steamapps" / "common" / "UmamusumePrettyDerby" / "hachimi" / "Career turn data",
    ])
    return [path for path in candidates if path.exists()]


STAT_CAREER_SUBDIRS = ("SPD", "STAM", "PWR", "GUTS", "WIT", "BALANCED", "UNKNOWN", "Unlabelled runs")


def load_manual_hachimi_careers(runtime_root, recent=None, parent_goals=None, allowed_chara_ids=None):
    samples = []
    # Project-local careers (legacy + recorder output).
    careers_dirs = [runtime_root / "manual_career_logs" / "careers"]
    # External hachimi capture folder — same layout, different parent path.
    # Added so the sweepy_capture.dll add-on's "Career turn data" folder
    # feeds the learner without the user manually copying files.
    careers_dirs.extend(_hachimi_capture_career_dirs())
    event_files = []
    for careers_dir in careers_dirs:
        if not careers_dir.exists():
            continue
        # Legacy flat layout: Career turn data / <career> / summary_events.jsonl
        event_files.extend(careers_dir.glob("*/summary_events.jsonl"))
        event_files.extend(careers_dir.glob("*/summary_events.jsonl.gz"))
        # New stat-typed layout: Career turn data / <STAT> / <career> /
        # summary_events.jsonl. Only descend into known stat subdirs to avoid
        # picking up unrelated nested files.
        for stat_dir_name in STAT_CAREER_SUBDIRS:
            stat_dir = careers_dir / stat_dir_name
            if stat_dir.exists():
                event_files.extend(stat_dir.glob("*/summary_events.jsonl"))
                event_files.extend(stat_dir.glob("*/summary_events.jsonl.gz"))
    if not event_files:
        return samples
    event_files = sorted(event_files, key=lambda p: p.stat().st_mtime, reverse=True)
    if recent:
        event_files = event_files[:recent]
    # Optional chara_id whitelist for multi-account safety. Captured hachimi
    # data doesn't include viewer_id, so this is the only signal we have to
    # reject captures from a different game account that happens to share
    # the same Steam install.
    chara_allowlist = None
    if allowed_chara_ids:
        chara_allowlist = {as_int(value) for value in allowed_chara_ids if as_int(value)}
    from career_bot.manual_recorder import build_report_from_hachimi_summaries
    for path in event_files:
        rows = [row for row in read_jsonl(path) if isinstance(row, dict)]
        summaries = [row for row in rows if row.get("current")]
        if not summaries:
            continue
        if chara_allowlist:
            chara_id_match = False
            for row in summaries:
                cur = row.get("current") or {}
                cid = as_int(cur.get("single_mode_chara_id")) or as_int(cur.get("card_id"))
                if cid and cid in chara_allowlist:
                    chara_id_match = True
                    break
            if not chara_id_match:
                continue
        # Path B sidecar: if the SessionSidecarWatcher (or a prior bot run)
        # dropped a learning_session.json into this career folder, attach
        # it as `learning_session` so `_attach_learning_metadata_to_samples`
        # picks it up downstream. The career folder is the parent of the
        # summary_events.jsonl path.
        sidecar_session = None
        try:
            from career_bot.session_sidecar import read_career_sidecar
            sidecar_session = read_career_sidecar(path.parent)
        except Exception:
            sidecar_session = None

        sample = None
        try:
            report = build_report_from_hachimi_summaries(path, PROJECT_ROOT, output_dir=runtime_root / "manual_career_logs", persist=False)
            sample = normalize_bot_like_log(path, report, "manual_hachimi", parent_goals=parent_goals)
        except Exception:
            sample = None
        if not sample:
            last = summaries[-1]
            summary_turns = [{"turn": as_int((row.get("current") or {}).get("turn"))} for row in summaries]
            capture = full_career_capture_details(summary_turns, status="finished" if as_int((last.get("current") or {}).get("turn")) >= 78 else "partial")
            final_stats = final_stats_from_summary(last)
            races = race_entries_from_summary(last)
            race_quality = race_quality_metrics(races, sample=last.get("current") or {})
            wins = as_int(race_quality.get("race_wins"))
            losses = as_int(race_quality.get("race_losses"))
            factor_quality = factor_quality_metrics(last, parent_goals=parent_goals)
            factor_score = factor_score_from_any(last)
            skill_quality = skill_quality_metrics(
                skill_rows_from_summary(last),
                final_stats.get("skill_point"),
                purchase_snapshot=skill_purchase_from_summary(last),
            )
            actions = infer_manual_actions_from_summaries(summaries)
            status = "finished" if as_int((last.get("current") or {}).get("turn")) >= 78 else "partial"
            score = estimate_score(
                final_stats,
                wins=wins,
                losses=losses,
                status=status,
                factor_score=factor_score,
                race_quality=race_quality,
                factor_quality=factor_quality,
                skill_quality=skill_quality,
                parent_goals=parent_goals,
            )
            sample = {
                "source": "manual_hachimi",
                "path": str(path),
                "created_at": None,
                "preset_name": "manual-hachimi",
                "status": status,
                "has_turn_data": True,
                "first_turn": capture["first_turn"],
                "has_turn_one": capture["has_turn_one"],
                "has_turn_78": capture["has_turn_78"],
                "full_career_capture": capture["full"],
                "final_turn": as_int((last.get("current") or {}).get("turn")),
                "turn_count": len(summaries),
                "final_stats": final_stats,
                "race_wins": wins,
                "race_losses": losses,
                "factor_score": factor_score,
                "race_quality": race_quality,
                "factor_quality": factor_quality,
                "skill_quality": skill_quality,
                "score": score,
                "actions": actions,
                "support_actions": extract_support_actions_from_turns(summaries),
                "item_decisions": [],
                "sample_weight": 1.45,
            }
        sample["sample_weight"] = 1.45
        if isinstance(sidecar_session, dict):
            sample["learning_session"] = sidecar_session
        samples.append(sample)
    return samples


def load_latest_manual_summary(runtime_root, parent_goals=None):
    path = runtime_root / "manual_career_logs" / "latest_manual_career_summary.json"
    data = read_json(path)
    if not isinstance(data, dict) or not data.get("current"):
        return []
    final_stats = final_stats_from_summary(data)
    races = race_entries_from_summary(data)
    race_quality = race_quality_metrics(races, sample=data.get("current") or {})
    wins = as_int(race_quality.get("race_wins"))
    losses = as_int(race_quality.get("race_losses"))
    factor_quality = factor_quality_metrics(data, parent_goals=parent_goals)
    factor_score = factor_score_from_any(data)
    skill_quality = skill_quality_metrics(
        skill_rows_from_summary(data),
        final_stats.get("skill_point"),
        purchase_snapshot=skill_purchase_from_summary(data),
    )
    status = "partial"
    score = estimate_score(
        final_stats,
        wins=wins,
        losses=losses,
        status=status,
        factor_score=factor_score,
        race_quality=race_quality,
        factor_quality=factor_quality,
        skill_quality=skill_quality,
        parent_goals=parent_goals,
    )
    return [{
        "source": "manual_latest",
        "path": str(path),
        "created_at": data.get("created_at"),
        "started_at": data.get("started_at"),
        "ended_at": data.get("ended_at"),
        "preset_name": "manual-latest",
        "status": status,
        "has_turn_data": True,
        "first_turn": as_int((data.get("current") or {}).get("turn")),
        "has_turn_one": as_int((data.get("current") or {}).get("turn")) == 1,
        "has_turn_78": as_int((data.get("current") or {}).get("turn")) >= 78,
        "full_career_capture": False,
        "final_turn": as_int((data.get("current") or {}).get("turn")),
        "turn_count": 1,
        "final_stats": final_stats,
        "race_wins": wins,
        "race_losses": losses,
        "factor_score": factor_score,
        "race_quality": race_quality,
        "factor_quality": factor_quality,
        "skill_quality": skill_quality,
        "score": score,
        "actions": [],
        "support_actions": [],
        "sample_weight": 0.45,
    }]


def final_stats_from_parent(parent):
    stats = parent.get("stats") or {}
    return {
        "speed": as_int(stats.get("speed")),
        "stamina": as_int(stats.get("stamina")),
        "power": as_int(stats.get("power")),
        "guts": as_int(stats.get("guts")),
        "wit": as_int(stats.get("wit") if "wit" in stats else stats.get("wiz")),
        "skill_point": as_int(stats.get("skill_point")),
        "hp": 0,
        "fans": 0,
    }


def race_entries_from_parent(parent):
    self_node = ((parent.get("tree") or {}).get("self") or {})
    races = []
    for row in self_node.get("race_history") or []:
        if isinstance(row, dict):
            races.append(normalize_race_entry(row))
    return dedupe_races(races)


def skill_rows_from_parent(parent):
    rows = []
    for row in parent.get("skills") or parent.get("skill_array") or []:
        if not isinstance(row, dict):
            continue
        skill_id = as_int(row.get("skill_id"))
        if skill_id:
            rows.append({"skill_id": skill_id, "name": row.get("name") or learning_references()["skill_names"].get(skill_id, "")})
    return rows


def normalize_parent_library_entry(path, parent, parent_goals=None):
    if not isinstance(parent, dict):
        return None
    final_stats = final_stats_from_parent(parent)
    has_final_stats = any(final_stats.get(key) for key in STAT_KEYS)
    races = race_entries_from_parent(parent)
    race_quality = race_quality_metrics(races, sample=parent)
    wins = as_int(race_quality.get("race_wins"))
    losses = as_int(race_quality.get("race_losses"))
    factor_quality = factor_quality_metrics(parent, parent_goals=parent_goals)
    white_metrics = white_factor_metrics(parent)
    if not has_final_stats and not as_int(factor_quality.get("factor_count")):
        return None
    skill_quality = skill_quality_metrics(skill_rows_from_parent(parent), final_stats.get("skill_point"))
    status = "parent_library" if has_final_stats else "parent_library_factor_only"
    score = estimate_score(
        final_stats,
        wins=wins,
        losses=losses,
        status="finished",
        factor_score=as_float(parent.get("score")),
        race_quality=race_quality,
        factor_quality=factor_quality,
        skill_quality=skill_quality,
        parent_goals=parent_goals,
    )
    source = "bot_parent_library" if parent.get("made_by_bot") else "user_parent_library"
    return {
        "source": source,
        "path": f"{path}#{parent.get('instance_id') or parent.get('card_id')}",
        "created_at": parent.get("created_at"),
        "started_at": parent.get("started_at"),
        "ended_at": parent.get("ended_at"),
        "preset_name": ((parent.get("bot_parent_info") or {}).get("preset_name") if parent.get("made_by_bot") else "owned-parent-library"),
        "desired_parent_sparks": ((parent.get("bot_parent_info") or {}).get("desired_parent_sparks") if parent.get("made_by_bot") else {}),
        "status": status,
        "has_turn_data": False,
        "first_turn": 1 if has_final_stats else 0,
        "has_turn_one": bool(has_final_stats),
        "has_turn_78": bool(has_final_stats),
        "full_career_capture": bool(has_final_stats),
        "final_turn": 78 if has_final_stats else 0,
        "turn_count": 0,
        "final_stats": final_stats,
        "race_wins": wins,
        "race_losses": losses,
        "rank": as_int(parent.get("rank")),
        "rank_label": rank_label(parent.get("rank")),
        "rank_score": as_int(parent.get("score")),
        "factor_score": as_float(parent.get("score")),
        "race_quality": race_quality,
        "factor_quality": factor_quality,
        "white_metrics": white_metrics,
        "skill_quality": skill_quality,
        "score": score,
        "actions": [],
        "support_actions": [],
        "sample_weight": (0.95 if parent.get("made_by_bot") else 0.75) if has_final_stats else 0.0,
        "parent_instance_id": parent.get("instance_id"),
        "made_by_bot": bool(parent.get("made_by_bot")),
    }


def load_parent_library_samples(runtime_root, parent_goals=None, recent=None):
    path = Path(runtime_root) / "parent_memory" / "parent_library.json"
    library = read_json(path) or {}
    parents = library.get("parents") if isinstance(library, dict) else []
    if not isinstance(parents, list):
        return []
    rows = sorted(
        parents,
        key=lambda parent: (
            bool(parent.get("made_by_bot")),
            as_int(parent.get("score")),
            as_int(parent.get("instance_id")),
        ),
        reverse=True,
    )
    if recent:
        rows = rows[:recent]
    samples = []
    for parent in rows:
        sample = normalize_parent_library_entry(path, parent, parent_goals=parent_goals)
        if sample:
            samples.append(sample)
    return samples


def collect_samples(base_dir, runtime_paths=None, recent=None, parent_goals=None, allowed_chara_ids=None):
    samples = []
    seen_paths = set()
    for root in runtime_roots(base_dir, runtime_paths):
        root_text = _normalized_runtime_root(root)
        for loader in [load_bot_logs, load_manual_legacy_logs, load_manual_hachimi_careers]:
            if loader is load_manual_hachimi_careers:
                loader_samples = loader(root, recent=recent, parent_goals=parent_goals, allowed_chara_ids=allowed_chara_ids)
            else:
                loader_samples = loader(root, recent=recent, parent_goals=parent_goals)
            for sample in loader_samples:
                if isinstance(sample, dict) and root_text:
                    sample.setdefault("runtime_root", root_text)
                path = sample.get("path")
                if path in seen_paths:
                    continue
                seen_paths.add(path)
                samples.append(sample)
        for sample in load_latest_manual_summary(root, parent_goals=parent_goals):
            if isinstance(sample, dict) and root_text:
                sample.setdefault("runtime_root", root_text)
            path = sample.get("path")
            if path not in seen_paths:
                seen_paths.add(path)
                samples.append(sample)
        for sample in load_parent_library_samples(root, parent_goals=parent_goals, recent=recent):
            if isinstance(sample, dict) and root_text:
                sample.setdefault("runtime_root", root_text)
            path = sample.get("path")
            if path not in seen_paths:
                seen_paths.add(path)
                samples.append(sample)
    samples = dedupe_samples(samples)
    samples.sort(key=lambda item: item.get("score", 0), reverse=True)
    # Annotate every sample's actions with decision_quality so downstream
    # consumers (weighted_action_distribution, future per-decision tuners,
    # reporting) all see the same per-action quality scores. Idempotent.
    try:
        from career_bot.decision_quality import annotate_actions_with_quality
        for sample in samples:
            annotate_actions_with_quality(sample)
    except Exception:
        pass
    # Attach objective-aware learning_metadata. Replaces the capture-tool
    # manifest embed described in Part 2 of the design doc — we re-derive
    # the metadata at load time so old logs (no manifest embed) and new
    # logs (with embed) both work, and the bot doesn't depend on a DLL
    # rebuild to get objective-aware tuning.
    try:
        _attach_learning_metadata_to_samples(base_dir, samples)
    except Exception:
        pass
    return samples


def _load_current_session_for_metadata(base_dir):
    """Best-effort read of the active learning session for metadata attachment.

    The session file lives at data/learning_sessions/current_session.json and
    is updated via the /api/learning_session/* endpoints. If the file is
    missing or unparseable, returns None — `session_from_career_log` will
    fall back to defaults.
    """
    path = Path(base_dir) / "data" / "learning_sessions" / "current_session.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _derive_learning_session_from_sample(base_dir, sample, preset_store=None):
    """Best-effort parent-farming session from sample objective context.

    Prefers the run's own recorded desired sparks so learning reflects what
    the bot was actually told to do when the run happened. Falls back to the
    named preset only when the sample itself does not carry that context.
    """
    try:
        from career_bot.objectives import session_from_parent_farming_targets
    except Exception:
        return None

    run_context = sample.get("run_context") or {}
    desired_parent_sparks = (
        run_context.get("desired_parent_sparks")
        or sample.get("desired_parent_sparks")
        or {}
    )
    style_target = (
        run_context.get("skill_profile_style")
        or run_context.get("style_target")
        or sample.get("skill_profile_style")
        or sample.get("style_target")
        or ""
    )
    preset_name = str(
        run_context.get("preset_name")
        or sample.get("preset_name")
        or ""
    ).strip()

    if preset_name and (not desired_parent_sparks or not style_target):
        try:
            store = preset_store or PresetStore(base_dir)
            preset = store.read_one(preset_name) or {}
        except Exception:
            preset = {}
        if preset:
            if not desired_parent_sparks:
                desired_parent_sparks = preset.get("desired_parent_sparks") or {}
            if not style_target:
                style_target = preset.get("skill_profile_style") or ""

    if not desired_parent_sparks:
        return None
    session_id = None
    if preset_name:
        session_id = f"preset_{slugify(preset_name)}"
    return session_from_parent_farming_targets(
        desired_parent_sparks=desired_parent_sparks,
        style_target=style_target,
        session_id=session_id,
    )


def _attach_learning_metadata_to_samples(base_dir, samples):
    """Walk loaded samples and inject `learning_metadata` per the design doc.

    Idempotent. Errors are isolated per-sample so one malformed log can't
    block metadata for the rest. Also applies `intent_aware_score` to
    each sample's `sample_weight` so the auto-tuner's existing weighted
    paths pick up condition-based scoring without further wiring.
    """
    try:
        from career_bot.affinity import (
            compute_career_affinity,
            compute_lineage_counts_for_sparks,
        )
        from career_bot.deck_quality import (
            compute_deck_quality_bucket,
            deck_from_career_log,
        )
        from career_bot.objectives import (
            classify_outcome,
            intent_aware_score,
            session_from_career_log,
        )
        from career_bot.spark_rates import rank_score_band
    except Exception:
        return

    current_session = _load_current_session_for_metadata(base_dir)
    preset_store = PresetStore(base_dir)
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        if sample.get("learning_metadata"):
            # Already annotated — make sure intent_aware_score has been applied.
            try:
                outcome = sample["learning_metadata"].get("outcome_assessment") or {}
                if not sample.get("_intent_weight_applied"):
                    sample["sample_weight"] = intent_aware_score(
                        absolute_score=as_float(sample.get("score")),
                        outcome_assessment=outcome,
                        base_weight=as_float(sample.get("sample_weight"), 1.0),
                    )
                    sample["_intent_weight_applied"] = True
            except Exception:
                pass
            continue
        try:
            # session lookup priority: in-log session > current session file > defaults
            session = sample.get("learning_session") or current_session
            if session:
                session = session_from_career_log({"learning_session": session})
            else:
                session = _derive_learning_session_from_sample(
                    base_dir,
                    sample,
                    preset_store=preset_store,
                )
                if not session:
                    session = session_from_career_log(sample)
            deck = deck_from_career_log(sample)
            deck_bucket = compute_deck_quality_bucket(deck)
            affinity = compute_career_affinity(sample)
            rank_score_value = as_float(
                sample.get("rank_score")
                or sample.get("score")
                or 0
            )
            lineage_counts = compute_lineage_counts_for_sparks(
                final_sparks=sample.get("final_sparks") or [],
                lineage_data=sample.get("lineage_data") or {},
            )
            outcome = classify_outcome(
                final_stats=sample.get("final_stats") or {},
                final_sparks=sample.get("final_sparks") or [],
                race_results=sample.get("race_results") or [],
                rank_score=rank_score_value,
                session=session,
            )
            sample["learning_metadata"] = {
                "session": session,
                "deck_quality_bucket": deck_bucket,
                "affinity": affinity,
                "lineage_spark_counts": lineage_counts,
                "rank_score_band": rank_score_band(rank_score_value),
                "outcome_assessment": outcome,
                "runtime_root": sample.get("runtime_root"),
            }
            sample["sample_weight"] = intent_aware_score(
                absolute_score=as_float(sample.get("score")),
                outcome_assessment=outcome,
                base_weight=as_float(sample.get("sample_weight"), 1.0),
            )
            sample["_intent_weight_applied"] = True
        except Exception:
            continue


def dedupe_samples(samples):
    unique = {}
    for sample in samples:
        stats = sample.get("final_stats") or {}
        key = (
            sample.get("source"),
            sample.get("started_at") or "",
            sample.get("preset_name") or "",
            sample.get("status"),
            sample.get("final_turn"),
            tuple(stats.get(stat, 0) for stat in ALL_STAT_KEYS),
            sample.get("race_wins"),
            sample.get("race_losses"),
            sample.get("parent_instance_id") or sample.get("path"),
        )
        existing = unique.get(key)
        if not existing:
            unique[key] = sample
            continue
        existing_actions = len(existing.get("actions") or [])
        new_actions = len(sample.get("actions") or [])
        if new_actions > existing_actions:
            unique[key] = sample
    return list(unique.values())


def sample_signature(samples, parent_goals=None, recency_config=None, active_context=None):
    rows = []
    for sample in sorted(samples, key=lambda row: str(row.get("path") or "")):
        stats = sample.get("final_stats") or {}
        observed = _sample_observed_details(sample)
        rows.append({
            "source": sample.get("source"),
            "path": sample.get("path"),
            "status": sample.get("status"),
            "final_turn": sample.get("final_turn"),
            "turn_count": sample.get("turn_count"),
            "observed_at_source": observed.get("source"),
            "observed_at": observed.get("observed_at"),
            "stats": {key: stats.get(key) for key in ALL_STAT_KEYS},
            "race_wins": sample.get("race_wins"),
            "race_losses": sample.get("race_losses"),
            "action_count": len(sample.get("actions") or []),
            "parent_instance_id": sample.get("parent_instance_id"),
        })
    payload = {
        "schema": LEARNING_OBJECTIVE_VERSION,
        "parent_goals": normalize_parent_goals(parent_goals),
        "active_context": active_context or {},
        "recency_config": {
            "enabled": bool((recency_config or {}).get("enabled", True)),
            "bias": round(
                as_float(
                    (recency_config or {}).get("bias"),
                    DEFAULT_AUTO_LEARNING_RECENCY_BIAS,
                ),
                4,
            ),
            "half_life": max(
                1,
                as_int(
                    (recency_config or {}).get("half_life"),
                    DEFAULT_AUTO_LEARNING_RECENCY_HALF_LIFE,
                ),
            ),
            "recent_failure_bias": round(
                as_float(
                    (recency_config or {}).get("recent_failure_bias"),
                    DEFAULT_AUTO_LEARNING_RECENT_FAILURE_BIAS,
                ),
                4,
            ),
            "regression_enabled": bool((recency_config or {}).get("regression_enabled", True)),
            "regression_bias": round(
                as_float(
                    (recency_config or {}).get("regression_bias"),
                    DEFAULT_AUTO_LEARNING_REGRESSION_BIAS,
                ),
                4,
            ),
            "regression_window": max(
                2,
                as_int(
                    (recency_config or {}).get("regression_window"),
                    DEFAULT_AUTO_LEARNING_REGRESSION_WINDOW,
                ),
            ),
            "regression_floor": round(
                as_float(
                    (recency_config or {}).get("regression_floor"),
                    DEFAULT_AUTO_LEARNING_REGRESSION_FLOOR,
                ),
                4,
            ),
            "progression_enabled": bool((recency_config or {}).get("progression_enabled", True)),
            "progression_bias": round(
                as_float(
                    (recency_config or {}).get("progression_bias"),
                    DEFAULT_AUTO_LEARNING_PROGRESSION_BIAS,
                ),
                4,
            ),
            "progression_window": max(
                2,
                as_int(
                    (recency_config or {}).get("progression_window"),
                    DEFAULT_AUTO_LEARNING_PROGRESSION_WINDOW,
                ),
            ),
            "progression_delta": max(
                50,
                as_int(
                    (recency_config or {}).get("progression_delta"),
                    DEFAULT_AUTO_LEARNING_PROGRESSION_DELTA,
                ),
            ),
        },
        "parent_knowledge": learning_references().get("parent_knowledge") or {},
        "samples": rows,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def average(values):
    rows = [as_float(value) for value in values if value is not None]
    if not rows:
        return 0.0
    return sum(rows) / len(rows)


def pearson_correlation(xs, ys):
    if len(xs) < 2 or len(xs) != len(ys):
        return None
    x_mean = average(xs)
    y_mean = average(ys)
    x_var = sum((x - x_mean) ** 2 for x in xs)
    y_var = sum((y - y_mean) ** 2 for y in ys)
    if x_var <= 0 or y_var <= 0:
        return None
    cov = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    return cov / math.sqrt(x_var * y_var)


def white_star_rate_band(score=None, rank=None):
    knowledge = learning_references().get("parent_knowledge") or {}
    factor_rules = knowledge.get("factor_generation_rules") if isinstance(knowledge, dict) else {}
    white_rules = (factor_rules or {}).get("white") if isinstance(factor_rules, dict) else {}
    bands = white_rules.get("star_rate_by_rank_score_band") if isinstance(white_rules, dict) else []
    if not isinstance(bands, list):
        return None

    rank_value = as_int(rank)
    if rank_value >= RANK_ORDER.get("UE", 16):
        for band in bands:
            if not isinstance(band, dict):
                continue
            minimum_rank = band.get("rank_min")
            if minimum_rank and rank_value >= RANK_ORDER.get(str(minimum_rank), 999):
                return {
                    "band": band.get("band"),
                    "1_star": band.get("1_star"),
                    "2_star": band.get("2_star"),
                    "3_star": band.get("3_star"),
                }

    score_value = as_float(score)
    if score_value <= 0:
        return None
    for band in bands:
        if not isinstance(band, dict):
            continue
        minimum = band.get("score_min")
        maximum = band.get("score_max_exclusive")
        if minimum is not None and score_value < as_float(minimum):
            continue
        if maximum is not None and score_value >= as_float(maximum):
            continue
        return {
            "band": band.get("band"),
            "1_star": band.get("1_star"),
            "2_star": band.get("2_star"),
            "3_star": band.get("3_star"),
        }
    return None


def white_spark_rank_diagnostic(samples):
    groups = {}
    skipped_missing_rank = 0
    skipped_missing_factor_payload = 0
    for sample in samples or []:
        source = str(sample.get("source") or "")
        if "parent_library" not in source and not sample.get("rank"):
            continue
        rank = as_int(sample.get("rank"))
        if rank <= 0:
            skipped_missing_rank += 1
            continue
        factor_quality = sample.get("factor_quality") or {}
        white_metrics = sample.get("white_metrics") or {}
        has_factor_payload = bool(white_metrics) or as_int(factor_quality.get("factor_count")) > 0
        if not has_factor_payload:
            skipped_missing_factor_payload += 1
            continue
        white_count = as_float(
            white_metrics.get("white_count") if "white_count" in white_metrics else factor_quality.get("white_count"),
            0.0,
        )
        white_3_count = as_float(
            white_metrics.get("white_3_count") if "white_3_count" in white_metrics else factor_quality.get("white_3_count"),
            0.0,
        )
        white_star_total = as_float(
            white_metrics.get("white_star_total") if "white_star_total" in white_metrics else factor_quality.get("white_star_total"),
            0.0,
        )
        rank_score = as_float(sample.get("rank_score") or sample.get("factor_score") or sample.get("score"))
        row = groups.setdefault(rank, {
            "rank": rank,
            "rank_label": rank_label(rank),
            "scores": [],
            "white_counts": [],
            "white_3_counts": [],
            "white_star_totals": [],
            "bot_count": 0,
            "user_count": 0,
        })
        row["scores"].append(rank_score)
        row["white_counts"].append(white_count)
        row["white_3_counts"].append(white_3_count)
        row["white_star_totals"].append(white_star_total)
        if sample.get("made_by_bot") or source == "bot_parent_library":
            row["bot_count"] += 1
        else:
            row["user_count"] += 1

    group_rows = []
    rank_points = []
    white_points = []
    white_3_points = []
    for rank in sorted(groups):
        row = groups[rank]
        sample_count = len(row["white_counts"])
        white_total = sum(row["white_counts"])
        avg_score = average(row["scores"])
        avg_white_count = average(row["white_counts"])
        avg_white_3_count = average(row["white_3_counts"])
        rank_points.extend([rank] * sample_count)
        white_points.extend(row["white_counts"])
        white_3_points.extend(row["white_3_counts"])
        group_rows.append({
            "rank": rank,
            "rank_label": row["rank_label"],
            "sample_count": sample_count,
            "bot_sample_count": row["bot_count"],
            "user_sample_count": row["user_count"],
            "avg_score": round(avg_score, 3),
            "avg_white_count": round(avg_white_count, 3),
            "avg_3_star_white_count": round(avg_white_3_count, 3),
            "avg_white_star_total": round(average(row["white_star_totals"]), 3),
            "max_white_count": max(row["white_counts"]) if row["white_counts"] else 0,
            "white_3_share": round(sum(row["white_3_counts"]) / white_total, 4) if white_total > 0 else 0.0,
            "guide_expected_star_band": white_star_rate_band(score=avg_score, rank=rank),
        })

    best_avg_white = max(group_rows, key=lambda row: (row["avg_white_count"], row["sample_count"]), default=None)
    best_avg_white_3 = max(group_rows, key=lambda row: (row["avg_3_star_white_count"], row["sample_count"]), default=None)
    rank_white_corr = pearson_correlation(rank_points, white_points)
    rank_white_3_corr = pearson_correlation(rank_points, white_3_points)
    low_sample_groups = [row["rank_label"] for row in group_rows if row["sample_count"] < 3]

    if len(group_rows) < 2:
        conclusion = "Not enough rank-separated parent data yet to compare white spark output by rank."
    elif low_sample_groups:
        conclusion = "Observed rank differences exist, but several rank groups have fewer than 3 samples, so treat this as directional rather than proven."
    elif rank_white_corr is not None and rank_white_corr > 0.25:
        conclusion = "Observed data trends upward: higher ranks currently correlate with more white sparks in the local parent library."
    elif rank_white_3_corr is not None and rank_white_3_corr > 0.25:
        conclusion = "Observed data trends upward for 3-star whites: higher ranks currently correlate with better white spark rarity in the local parent library."
    else:
        conclusion = "Observed data does not yet show a strong monotonic rank effect on white spark count; guide priors still favor SS/UE+ for better white rarity."

    return {
        "schema": "sweepy_white_spark_rank_diagnostic_v1",
        "source": "parent_library_samples",
        "sample_count": sum(row["sample_count"] for row in group_rows),
        "rank_group_count": len(group_rows),
        "groups": group_rows,
        "best_avg_white_count": (
            {"rank": best_avg_white["rank"], "rank_label": best_avg_white["rank_label"], "avg_white_count": best_avg_white["avg_white_count"]}
            if best_avg_white else None
        ),
        "best_avg_3_star_white_count": (
            {
                "rank": best_avg_white_3["rank"],
                "rank_label": best_avg_white_3["rank_label"],
                "avg_3_star_white_count": best_avg_white_3["avg_3_star_white_count"],
            }
            if best_avg_white_3 else None
        ),
        "rank_white_count_correlation": round(rank_white_corr, 4) if rank_white_corr is not None else None,
        "rank_3_star_white_count_correlation": round(rank_white_3_corr, 4) if rank_white_3_corr is not None else None,
        "low_sample_rank_groups": low_sample_groups,
        "skipped_missing_rank": skipped_missing_rank,
        "skipped_missing_factor_payload": skipped_missing_factor_payload,
        "guide_prior": "Guide rules say white 3-star rate improves at roughly SS/17500+ score and improves again at UE+; observed data can confirm or contradict this locally.",
        "conclusion": conclusion,
    }


def score_model_on_samples(model, samples):
    """Compute the mean policy-bonus that `model` would give to actions in
    `samples`. Higher = the model "agrees" more with these samples' behavior.

    Used for hold-out validation: comparing the NEW model and the previously-
    applied model on the SAME current top samples. If the new model scores
    lower than the old on the same data, the new model is degrading and we
    keep the old model instead of overwriting it with mediocre weights.
    """
    if not isinstance(model, dict) or not model.get("enabled"):
        return None
    feature_weights = model.get("feature_weights") or {}
    command_bias = model.get("command_bias") or {}
    period_command_bias = model.get("period_command_bias") or {}
    total = 0.0
    count = 0
    for sample in samples or []:
        for action in sample.get("actions") or []:
            row = _action_features(action)
            idx = row.get("_idx", -1)
            if idx is None or idx < 0:
                continue
            score = 0.0
            for name, weight in feature_weights.items():
                score += as_float(weight) * as_float(row.get(name))
            score += as_float(command_bias.get(str(idx)))
            period = row.get("_period")
            period_bias = period_command_bias.get(str(period)) or {}
            score += as_float(period_bias.get(str(idx)))
            total += score
            count += 1
    if count == 0:
        return None
    return total / count


def recent_validation_samples(samples, limit=8, min_actions=10):
    rows = []
    for sample in samples or []:
        if len(sample.get("actions") or []) < min_actions:
            continue
        details = _sample_observed_details(sample)
        stamp = as_float((details or {}).get("timestamp"), -1.0)
        rows.append((stamp, sample))
    rows.sort(key=lambda item: item[0], reverse=True)
    return [sample for _, sample in rows[:max(0, int(limit or 0))]]


def _support_card_ids_from_context(run_context):
    run_context = run_context if isinstance(run_context, dict) else {}
    ids = []
    for value in run_context.get("support_card_ids") or []:
        card_id = as_int(value)
        if card_id:
            ids.append(card_id)
    if not ids:
        for card in run_context.get("support_cards") or []:
            if not isinstance(card, dict):
                continue
            card_id = as_int(card.get("support_card_id") or card.get("id") or card.get("card_id"))
            if card_id:
                ids.append(card_id)
    return tuple(ids)


def _support_lb_signature(run_context):
    run_context = run_context if isinstance(run_context, dict) else {}
    lb_lookup = run_context.get("support_card_lb_levels") or {}
    rows = []
    if isinstance(lb_lookup, dict):
        for card_id, row in lb_lookup.items():
            if isinstance(row, dict):
                lb = as_int(row.get("lb") if row.get("lb") is not None else row.get("limit_break_count"))
            else:
                lb = as_int(row)
            cid = as_int(card_id)
            if cid:
                rows.append((cid, lb))
    if not rows:
        for card in run_context.get("support_cards") or []:
            if not isinstance(card, dict):
                continue
            cid = as_int(card.get("support_card_id") or card.get("id") or card.get("card_id"))
            if not cid:
                continue
            rows.append((cid, as_int(card.get("lb_level") if card.get("lb_level") is not None else card.get("limit_break_count"))))
    return tuple(sorted(rows))


def _program_id_from_schedule_row(row):
    if isinstance(row, dict):
        for key in ("program_id", "race_program_id", "race_id", "id"):
            value = as_int(row.get(key))
            if value:
                return value
    return as_int(row)


def _schedule_program_ids_from_context_or_sample(run_context=None, sample=None, preset=None):
    run_context = run_context if isinstance(run_context, dict) else {}
    sample = sample if isinstance(sample, dict) else {}
    preset = preset if isinstance(preset, dict) else {}
    for source in (
        run_context.get("custom_race_schedule"),
        sample.get("custom_race_schedule"),
        preset.get("custom_race_schedule"),
        sample.get("race_results"),
    ):
        rows = []
        for row in source or []:
            program_id = _program_id_from_schedule_row(row)
            if program_id:
                rows.append(program_id)
        if rows:
            return tuple(rows)
    return ()


def _parent_ids_from_context(run_context):
    run_context = run_context if isinstance(run_context, dict) else {}
    rows = []
    for key in ("parent_id_1", "parent_id_2"):
        value = as_int(run_context.get(key))
        if value:
            rows.append(value)
    return tuple(rows)


def _parent_card_ids_from_context(run_context):
    run_context = run_context if isinstance(run_context, dict) else {}
    parents = run_context.get("parents") or {}
    rows = []
    if isinstance(parents, dict):
        for key in ("parent_1", "parent_2"):
            parent = parents.get(key) or {}
            if isinstance(parent, dict):
                card_id = as_int(parent.get("card_id") or parent.get("chara_id") or parent.get("trained_chara_id"))
                if card_id:
                    rows.append(card_id)
    return tuple(rows)


def _hash_tuple(values):
    values = tuple(values or ())
    if not values:
        return ""
    payload = json.dumps(values, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:12]


def _sample_validation_context(sample):
    sample = sample if isinstance(sample, dict) else {}
    meta = sample.get("learning_metadata") or {}
    session = meta.get("session") or {}
    run_context = sample.get("run_context") or {}
    primary_stat = str(((session.get("primary_stat_target") or {}).get("stat")) or "").strip().lower()
    style = str(session.get("style_target") or run_context.get("skill_profile_style") or "").strip().lower()
    preset_name = slugify(sample.get("preset_name") or run_context.get("preset_name") or "")
    deck_bucket = meta.get("deck_quality_bucket")
    if deck_bucket is None:
        deck_bucket = sample.get("deck_quality_bucket")
    deck_bucket = as_int(deck_bucket, 2)
    support_card_ids = _support_card_ids_from_context(run_context)
    support_card_id_set = tuple(sorted(set(support_card_ids)))
    friend_card_id = as_int(run_context.get("friend_card_id"))
    support_lb_signature_value = _support_lb_signature(run_context)
    exact_deck_signature = (
        _hash_tuple((support_card_ids, friend_card_id, support_lb_signature_value))
        if support_card_ids or friend_card_id or support_lb_signature_value
        else ""
    )
    schedule_program_ids = _schedule_program_ids_from_context_or_sample(run_context, sample=sample)
    parent_ids = _parent_ids_from_context(run_context)
    parent_card_ids = _parent_card_ids_from_context(run_context)
    parent_signature = _hash_tuple((parent_ids, parent_card_ids)) if parent_ids or parent_card_ids else ""
    trainee_card_id = as_int(
        run_context.get("trainee_card_id")
        or sample.get("trainee_card_id")
        or run_context.get("chara_id")
        or sample.get("chara_id")
        or sample.get("trained_chara_id"),
        0,
    )
    objective_keys = tuple(
        expect_attribute_profile_lookup_keys(
            {},
            session=session,
            run_context=run_context,
            desired_parent_sparks=(
                sample.get("desired_parent_sparks")
                or run_context.get("desired_parent_sparks")
            ),
            style=style or None,
            distance=run_context.get("skill_profile_distance"),
            deck_quality_bucket=deck_bucket,
        )
    )
    return {
        "preset_name": preset_name,
        "trainee_card_id": trainee_card_id,
        "deck_quality_bucket": deck_bucket,
        "deck_signature": support_type_signature(run_context.get("support_cards") or []),
        "support_card_ids": support_card_ids,
        "support_card_id_set": support_card_id_set,
        "support_lb_signature": support_lb_signature_value,
        "friend_card_id": friend_card_id,
        "exact_deck_signature": exact_deck_signature,
        "schedule_program_ids": schedule_program_ids,
        "schedule_signature": _hash_tuple(schedule_program_ids),
        "race_count": len(schedule_program_ids),
        "parent_ids": parent_ids,
        "parent_card_ids": parent_card_ids,
        "parent_signature": parent_signature,
        "primary_stat": primary_stat,
        "style": style,
        "distance": str(run_context.get("skill_profile_distance") or sample.get("skill_profile_distance") or "").strip().lower(),
        "objective_keys": objective_keys,
    }


def _preset_validation_context(preset):
    preset = preset if isinstance(preset, dict) else {}
    run_context = copy.deepcopy(preset.get("_run_context") or {})
    if preset.get("custom_race_schedule") and not run_context.get("custom_race_schedule"):
        run_context["custom_race_schedule"] = copy.deepcopy(preset.get("custom_race_schedule") or [])
    if preset.get("skill_profile_style") and not run_context.get("skill_profile_style"):
        run_context["skill_profile_style"] = preset.get("skill_profile_style")
    if preset.get("skill_profile_distance") and not run_context.get("skill_profile_distance"):
        run_context["skill_profile_distance"] = preset.get("skill_profile_distance")
    if preset.get("desired_parent_sparks") and not run_context.get("desired_parent_sparks"):
        run_context["desired_parent_sparks"] = copy.deepcopy(preset.get("desired_parent_sparks") or {})
    return _sample_validation_context({
        "preset_name": preset.get("name") or run_context.get("preset_name") or "",
        "run_context": run_context,
        "desired_parent_sparks": preset.get("desired_parent_sparks") or run_context.get("desired_parent_sparks") or {},
        "deck_quality_bucket": run_context.get("deck_quality_bucket"),
    })


def _validation_context_has_strong_anchor(context):
    context = context if isinstance(context, dict) else {}
    return bool(
        context.get("trainee_card_id")
        or context.get("exact_deck_signature")
        or context.get("support_card_ids")
        or context.get("friend_card_id")
        or context.get("schedule_signature")
        or context.get("parent_signature")
    )


def _overlap_ratio(left, right):
    left_set = set(left or [])
    right_set = set(right or [])
    if not left_set or not right_set:
        return 0.0
    return len(left_set.intersection(right_set)) / max(1, len(left_set.union(right_set)))


def _sample_validation_match_score(anchor_context, sample):
    anchor_context = anchor_context if isinstance(anchor_context, dict) else {}
    if not anchor_context:
        return 0
    sample_context = _sample_validation_context(sample)
    score = 0
    if (
        anchor_context.get("trainee_card_id")
        and sample_context.get("trainee_card_id") == anchor_context.get("trainee_card_id")
    ):
        score += 8
    if (
        anchor_context.get("exact_deck_signature")
        and sample_context.get("exact_deck_signature") == anchor_context.get("exact_deck_signature")
    ):
        score += 9
    else:
        support_overlap = _overlap_ratio(anchor_context.get("support_card_id_set"), sample_context.get("support_card_id_set"))
        if support_overlap:
            score += int(round(5 * support_overlap))
        if (
            anchor_context.get("friend_card_id")
            and sample_context.get("friend_card_id") == anchor_context.get("friend_card_id")
        ):
            score += 3
        if (
            anchor_context.get("deck_signature")
            and anchor_context.get("deck_signature") != "any"
            and sample_context.get("deck_signature") == anchor_context.get("deck_signature")
        ):
            score += 3
        elif sample_context.get("deck_quality_bucket") == anchor_context.get("deck_quality_bucket"):
            score += 2
    if (
        anchor_context.get("schedule_signature")
        and sample_context.get("schedule_signature") == anchor_context.get("schedule_signature")
    ):
        score += 9
    else:
        schedule_overlap = _overlap_ratio(anchor_context.get("schedule_program_ids"), sample_context.get("schedule_program_ids"))
        if schedule_overlap:
            score += int(round(6 * schedule_overlap))
        if (
            anchor_context.get("race_count")
            and sample_context.get("race_count")
            and abs(int(sample_context.get("race_count")) - int(anchor_context.get("race_count"))) <= 2
        ):
            score += 1
        if not anchor_context.get("schedule_program_ids") or not sample_context.get("schedule_program_ids"):
            if sample_context.get("deck_quality_bucket") == anchor_context.get("deck_quality_bucket"):
                # Backward-compatible fallback for old samples without race history.
                score += 1
    if (
        anchor_context.get("parent_signature")
        and sample_context.get("parent_signature") == anchor_context.get("parent_signature")
    ):
        score += 4
    else:
        score += int(round(2 * _overlap_ratio(anchor_context.get("parent_card_ids"), sample_context.get("parent_card_ids"))))
    # Target resolution intentionally falls back through `balanced_any`, but
    # validation-context matching should not treat that generic fallback as a
    # real objective match. Otherwise Power and Wit samples can look related
    # solely because both have `balanced_any` in their fallback chains.
    anchor_keys = {
        key for key in (anchor_context.get("objective_keys") or [])
        if not str(key).startswith("balanced_any")
    }
    sample_keys = {
        key for key in (sample_context.get("objective_keys") or [])
        if not str(key).startswith("balanced_any")
    }
    if anchor_keys and sample_keys and anchor_keys.intersection(sample_keys):
        score += 4
    else:
        if anchor_context.get("primary_stat") and sample_context.get("primary_stat") == anchor_context.get("primary_stat"):
            score += 2
        if anchor_context.get("style") and sample_context.get("style") == anchor_context.get("style"):
            score += 2
        if anchor_context.get("distance") and sample_context.get("distance") == anchor_context.get("distance"):
            score += 2
    if anchor_context.get("preset_name") and sample_context.get("preset_name") == anchor_context.get("preset_name"):
        score += 1
    return score


def context_fingerprint_from_validation_context(context):
    context = context if isinstance(context, dict) else {}
    payload = {
        "preset_name": context.get("preset_name") or "",
        "trainee_card_id": as_int(context.get("trainee_card_id")),
        "exact_deck_signature": context.get("exact_deck_signature") or "",
        "deck_signature": context.get("deck_signature") or "",
        "deck_quality_bucket": as_int(context.get("deck_quality_bucket"), 2),
        "friend_card_id": as_int(context.get("friend_card_id")),
        "schedule_signature": context.get("schedule_signature") or "",
        "race_count": as_int(context.get("race_count")),
        "parent_signature": context.get("parent_signature") or "",
        "primary_stat": context.get("primary_stat") or "",
        "style": context.get("style") or "",
        "distance": context.get("distance") or "",
    }
    payload["fingerprint"] = _hash_tuple(tuple(sorted(payload.items())))
    return payload


def select_context_adaptive_samples(samples, preset=None):
    samples = list(samples or [])
    preset = preset if isinstance(preset, dict) else {}
    enabled = bool(preset.get("learning_context_adaptation_enabled", True))
    anchor_context = _preset_validation_context(preset)
    fingerprint = context_fingerprint_from_validation_context(anchor_context)
    if not enabled or not samples:
        return {
            "samples": samples,
            "enabled": enabled,
            "mode": "disabled" if not enabled else "empty",
            "anchor": fingerprint,
            "sample_count": len(samples),
            "exact_count": 0,
            "similar_count": 0,
            "global_count": len(samples),
        }
    if not _validation_context_has_strong_anchor(anchor_context):
        return {
            "samples": samples,
            "enabled": True,
            "mode": "no_context_anchor",
            "anchor": fingerprint,
            "sample_count": len(samples),
            "exact_count": 0,
            "similar_count": 0,
            "global_count": len(samples),
            "selected_count": len(samples),
        }
    exact_threshold = as_int(preset.get("learning_context_exact_match_score"), 28)
    similar_threshold = as_int(preset.get("learning_context_similar_match_score"), 14)
    min_exact = max(1, as_int(preset.get("learning_context_min_exact_samples"), 4))
    min_similar = max(min_exact, as_int(preset.get("learning_context_min_similar_samples"), 8))
    soft_min_similar = max(1, as_int(preset.get("learning_context_soft_min_similar_samples"), 3))
    global_fallback_enabled = bool(preset.get("learning_context_global_fallback_enabled", False))
    scored = []
    for sample in samples:
        score = _sample_validation_match_score(anchor_context, sample)
        scored.append((score, sample))
    exact = [sample for score, sample in scored if score >= exact_threshold]
    similar = [sample for score, sample in scored if score >= similar_threshold]
    selected = []
    mode = "context_cold_start_no_global"
    if len(exact) >= min_exact:
        selected = exact
        mode = "exact_context"
    elif len(similar) >= min_similar:
        selected = similar
        mode = "similar_context"
    elif len(similar) >= soft_min_similar:
        # New deck/trainee/parent bundles often have only a handful of local
        # careers at first. Learning from those weak-but-relevant runs is safer
        # than copying unrelated global/manual top samples from a different
        # context, which was the main source of post-swap regression.
        selected = similar
        mode = "similar_context_low_sample"
    elif global_fallback_enabled:
        selected = samples
        mode = "global_fallback"
    max_score = max((score for score, _sample in scored), default=0)
    return {
        "samples": selected,
        "enabled": True,
        "mode": mode,
        "anchor": fingerprint,
        "sample_count": len(samples),
        "selected_count": len(selected),
        "exact_count": len(exact),
        "similar_count": len(similar),
        "global_count": len(samples),
        "max_match_score": max_score,
        "exact_threshold": exact_threshold,
        "similar_threshold": similar_threshold,
        "min_exact_samples": min_exact,
        "min_similar_samples": min_similar,
        "soft_min_similar_samples": soft_min_similar,
        "global_fallback_enabled": global_fallback_enabled,
    }


def select_context_validation_samples(samples, anchor_sample=None, *, limit=24, min_actions=10, min_match_count=6):
    limit = max(1, as_int(limit, 24))
    min_actions = max(1, as_int(min_actions, 10))
    min_match_count = max(1, as_int(min_match_count, 6))
    pool = [sample for sample in (samples or []) if len(sample.get("actions") or []) >= min_actions]
    if not pool:
        return {
            "samples": [],
            "mode": "empty",
            "match_count": 0,
            "anchor": {},
        }

    if anchor_sample is None:
        recent = recent_validation_samples(pool, limit=1, min_actions=min_actions)
        anchor_sample = recent[0] if recent else None
    if not isinstance(anchor_sample, dict):
        return {
            "samples": recent_validation_samples(pool, limit=limit, min_actions=min_actions),
            "mode": "recent_only",
            "match_count": 0,
            "anchor": {},
        }

    anchor_context = _sample_validation_context(anchor_sample)
    matched_rows = []
    for sample in pool:
        match_score = _sample_validation_match_score(anchor_context, sample)
        if match_score <= 0:
            continue
        details = _sample_observed_details(sample)
        stamp = as_float((details or {}).get("timestamp"), -1.0)
        matched_rows.append((match_score, stamp, sample))
    matched_rows.sort(key=lambda item: (item[0], item[1]), reverse=True)
    contextual_samples = [sample for _, _, sample in matched_rows[:limit]]
    if len(contextual_samples) >= min_match_count:
        return {
            "samples": contextual_samples,
            "mode": "contextual",
            "match_count": len(matched_rows),
            "anchor": anchor_context,
        }

    recent_samples = recent_validation_samples(pool, limit=limit, min_actions=min_actions)
    merged = []
    seen_ids = set()
    for sample in contextual_samples + recent_samples:
        marker = id(sample)
        if marker in seen_ids:
            continue
        seen_ids.add(marker)
        merged.append(sample)
        if len(merged) >= limit:
            break
    return {
        "samples": merged,
        "mode": "recent_fallback" if contextual_samples else "recent_only",
        "match_count": len(matched_rows),
        "anchor": anchor_context,
    }


def _policy_model_fingerprint(model):
    if not isinstance(model, dict) or not model.get("enabled"):
        return ""
    payload = {
        "feature_weights": model.get("feature_weights") or {},
        "command_bias": model.get("command_bias") or {},
        "period_command_bias": model.get("period_command_bias") or {},
    }
    try:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    except Exception:
        raw = repr(payload)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def _shadow_challenger_update(
    preset,
    old_model,
    new_model,
    old_score,
    new_score,
    old_holdout_score,
    new_holdout_score,
    validation_tolerance,
    recent_holdout_count=None,
):
    challenger_enabled = bool((preset or {}).get("training_policy_challenger_enabled", True))
    promotion_passes = max(1, as_int((preset or {}).get("training_policy_challenger_promotion_passes"), 2))
    min_margin = max(0.0, as_float((preset or {}).get("training_policy_challenger_min_margin"), 0.01))
    min_holdout_count = max(1, as_int((preset or {}).get("training_policy_challenger_min_holdout_count"), 3))
    holdout_count = None if recent_holdout_count is None else max(0, as_int(recent_holdout_count))
    low_confidence_holdout = holdout_count is not None and holdout_count < min_holdout_count
    existing = (preset or {}).get("training_policy_challenger") or {}
    existing_fp = str(existing.get("fingerprint") or "")
    active_fp = _policy_model_fingerprint(old_model)
    existing_active_fp = str(existing.get("against_active_fingerprint") or "")
    if not existing_active_fp and existing and active_fp:
        # Older staged challengers predate `against_active_fingerprint`.
        # Treat them as having challenged the current active model so a
        # qualifying next pass can continue the streak instead of
        # getting stuck at pass 1/2 forever after the migration.
        existing_active_fp = active_fp

    decision = {
        "active_model": old_model,
        "challenger": {},
        "decision": "accepted",
        "reason": "no_prior_model" if old_score is None else "improved_or_unchanged",
        "validation_confidence": {
            "recent_holdout_count": holdout_count,
            "min_holdout_count": min_holdout_count,
            "low_confidence_holdout": bool(low_confidence_holdout),
        },
    }
    if old_score is None or not challenger_enabled or not isinstance(old_model, dict) or not old_model.get("enabled"):
        decision["active_model"] = new_model
        return decision

    rejection_reasons = []
    if (
        old_score is not None
        and new_score is not None
        and old_score > 0
        and new_score < old_score * validation_tolerance
    ):
        rejection_reasons.append(
            f"new model scores {new_score:.4f} on current top samples, "
            f"below {validation_tolerance:.0%} of old model's {old_score:.4f}"
        )
    if (
        old_holdout_score is not None
        and new_holdout_score is not None
        and old_holdout_score > 0
        and new_holdout_score < old_holdout_score * validation_tolerance
        and not low_confidence_holdout
    ):
        rejection_reasons.append(
            f"recent holdout regressed: {new_holdout_score:.4f} vs old {old_holdout_score:.4f}"
        )
    if rejection_reasons:
        decision["decision"] = "rejected_keep_old"
        decision["reason"] = "; ".join(rejection_reasons)
        return decision

    current_margin = 0.0
    holdout_margin = 0.0
    if old_score and new_score is not None:
        current_margin = (new_score - old_score) / max(abs(old_score), 1e-9)
    if old_holdout_score and new_holdout_score is not None:
        holdout_margin = (new_holdout_score - old_holdout_score) / max(abs(old_holdout_score), 1e-9)
    elif new_holdout_score is not None and old_holdout_score is None:
        holdout_margin = current_margin
    elif old_holdout_score is None and new_holdout_score is None:
        holdout_margin = current_margin
    if low_confidence_holdout:
        holdout_margin = current_margin

    if current_margin < min_margin or holdout_margin < (min_margin * 0.5):
        decision["decision"] = "accepted_keep_old_stable"
        decision["reason"] = (
            f"new model improvement ({current_margin:.2%} current / {holdout_margin:.2%} holdout) "
            f"did not clear challenger margin {min_margin:.2%}"
        )
        if low_confidence_holdout:
            decision["reason"] += f"; low_confidence_holdout count={holdout_count}/{min_holdout_count}"
        return decision

    fingerprint = _policy_model_fingerprint(new_model)
    streak = 1
    if active_fp and existing_active_fp == active_fp:
        streak = max(1, as_int(existing.get("streak"), 0) + 1)
    elif fingerprint and existing_fp == fingerprint:
        streak = max(1, as_int(existing.get("streak"), 0) + 1)
    challenger = {
        "schema": "sweepy_training_policy_challenger_v1",
        "fingerprint": fingerprint,
        "against_active_fingerprint": active_fp,
        "streak": streak,
        "promotion_passes": promotion_passes,
        "current_margin": round(current_margin, 5),
        "holdout_margin": round(holdout_margin, 5),
        "model": copy.deepcopy(new_model),
    }
    if low_confidence_holdout:
        challenger["low_confidence_holdout"] = True
    if streak >= promotion_passes:
        decision["active_model"] = new_model
        decision["challenger"] = {}
        decision["decision"] = "challenger_promoted"
        decision["reason"] = (
            f"challenger cleared margins for {streak} consecutive learning passes "
            f"({current_margin:.2%} current / {holdout_margin:.2%} holdout)"
        )
        return decision

    decision["decision"] = "challenger_staged"
    decision["reason"] = (
        f"staged challenger pass {streak}/{promotion_passes} "
        f"({current_margin:.2%} current / {holdout_margin:.2%} holdout)"
    )
    decision["challenger"] = challenger
    return decision


def _avg_score(samples):
    rows = [as_float(sample.get("score")) for sample in samples or [] if as_float(sample.get("score")) > 0]
    if not rows:
        return 0.0
    return sum(rows) / len(rows)


def _support_action_counts(samples):
    counts = Counter()
    for sample in samples or []:
        seen_optional = 0
        for action in sample.get("support_actions") or []:
            kind = str((action or {}).get("kind") or "")
            if not kind:
                continue
            counts[kind] += 1
            if kind == "race" and bool((action or {}).get("optional_race")):
                seen_optional += 1
        if seen_optional:
            counts["optional_race"] += seen_optional
    return counts


def _sample_comparison_score(sample):
    sample = sample if isinstance(sample, dict) else {}
    rank_score = as_float(sample.get("rank_score"), 0.0)
    if rank_score > 0:
        return rank_score, "rank_score"
    return as_float(sample.get("score"), 0.0), "estimated_score"


def _preset_bool(preset, key, default=True):
    if not isinstance(preset, dict) or preset.get(key) is None:
        return bool(default)
    value = preset.get(key)
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return bool(default)


def monotonic_apply_gate(preset, samples):
    """Decide whether a learned candidate can become the active preset.

    Training-policy validation only protects the classifier. This gate protects
    the entire learned preset by requiring the latest comparable bot career to
    clear the previously accepted score baseline before any broad learned
    changes are applied.
    """
    preset = preset if isinstance(preset, dict) else {}
    enabled = _preset_bool(preset, "auto_learning_monotonic_apply_enabled", True)
    corrective_apply_enabled = _preset_bool(preset, "auto_learning_corrective_apply_enabled", True)
    previous_state = ((preset.get("learning_metadata") or {}).get("monotonic_apply_gate") or {})
    gate = {
        "schema": "sweepy_monotonic_apply_gate_v1",
        "enabled": enabled,
        "corrective_apply_enabled": corrective_apply_enabled,
        "allowed": True,
        "reason": "disabled" if not enabled else "pending",
        "min_improvement": as_float(preset.get("auto_learning_monotonic_min_improvement"), 1.0),
        "allowed_drop": as_float(preset.get("auto_learning_monotonic_allowed_drop"), 0.0),
        "previous_accepted_score": as_float(previous_state.get("accepted_score")),
        "previous_accepted_score_source": previous_state.get("accepted_score_source") or "",
    }
    if not enabled:
        return gate

    rows = []
    for sample in samples or []:
        if str((sample or {}).get("source") or "").lower() != "bot":
            continue
        if not is_full_career_sample(sample):
            continue
        score, score_source = _sample_comparison_score(sample)
        if score <= 0:
            continue
        details = _sample_observed_details(sample)
        rows.append((
            as_float((details or {}).get("timestamp"), -1.0),
            str(sample.get("path") or ""),
            score,
            score_source,
            sample,
            details,
        ))
    rows.sort(key=lambda item: (item[0], item[1]))
    gate["bot_finished_sample_count"] = len(rows)
    if not rows:
        gate["allowed"] = True
        gate["reason"] = "no_finished_bot_history"
        return gate

    _latest_stamp, latest_path, latest_score, latest_score_source, _latest_sample, latest_details = rows[-1]
    gate.update({
        "latest_score": round(latest_score, 3),
        "latest_score_source": latest_score_source,
        "latest_path": latest_path,
        "latest_observed_at": latest_details.get("observed_at"),
        "latest_observed_at_source": latest_details.get("source"),
    })

    previous_score = None
    previous_score_source = ""
    previous_path = ""
    if len(rows) >= 2:
        _stamp, previous_path, previous_score, previous_score_source, _sample, _details = rows[-2]
    best_prior_score = None
    best_prior_score_source = ""
    best_prior_path = ""
    if len(rows) >= 2:
        _best_stamp, best_prior_path, best_prior_score, best_prior_score_source, _best_sample, _best_details = max(
            rows[:-1],
            key=lambda item: (as_float(item[2]), as_float(item[0]), str(item[1])),
        )
    accepted_score = as_float(previous_state.get("accepted_score"), 0.0)
    accepted_source = previous_state.get("accepted_score_source") or ""
    baseline_candidates = []
    if accepted_score > 0:
        baseline_candidates.append((accepted_score, "previous_accepted", accepted_source, ""))
    if as_float(best_prior_score, 0.0) > 0:
        baseline_candidates.append((as_float(best_prior_score), "best_prior_bot_run", best_prior_score_source, best_prior_path))
    if baseline_candidates:
        baseline_score, baseline_source, baseline_score_source, baseline_path = max(
            baseline_candidates,
            key=lambda item: item[0],
        )
    else:
        baseline_score = 0.0
        baseline_source = ""
        baseline_score_source = ""
        baseline_path = ""

    gate.update({
        "previous_score": None if previous_score is None else round(previous_score, 3),
        "previous_score_source": previous_score_source,
        "previous_path": previous_path,
        "best_prior_score": None if best_prior_score is None else round(best_prior_score, 3),
        "best_prior_score_source": best_prior_score_source,
        "best_prior_path": best_prior_path,
        "baseline_score": round(baseline_score, 3) if baseline_score > 0 else None,
        "baseline_source": baseline_source,
        "baseline_score_source": baseline_score_source,
        "baseline_path": baseline_path,
        "accepted_score_source": latest_score_source,
    })
    if baseline_score <= 0:
        gate["allowed"] = True
        gate["reason"] = "first_comparable_bot_run"
        gate["accepted_score"] = round(latest_score, 3)
        return gate

    delta = latest_score - baseline_score
    required = gate["min_improvement"] - gate["allowed_drop"]
    gate["delta_vs_baseline"] = round(delta, 3)
    gate["required_delta"] = round(required, 3)
    if delta >= required:
        gate["allowed"] = True
        gate["reason"] = "latest_run_cleared_monotonic_baseline"
        gate["accepted_score"] = round(latest_score, 3)
        return gate

    gate["allowed"] = False
    gate["reason"] = (
        f"latest bot run score {latest_score:.1f} did not clear monotonic baseline "
        f"{baseline_score:.1f} by required delta {required:.1f}"
    )
    # A rejected low run cannot lower the bar for the next active update.
    if accepted_score > 0:
        gate["accepted_score"] = round(accepted_score, 3)
        gate["accepted_score_source"] = accepted_source
    if corrective_apply_enabled:
        gate["allowed"] = True
        gate["corrective_apply"] = True
        gate["baseline_preserved"] = True
        gate["reason"] = "corrective_apply_after_latest_regression"
        # Apply the learned corrective policy, but keep the high-water
        # accepted baseline intact so a poor run cannot become the new bar.
        if accepted_score > 0 and accepted_score >= baseline_score:
            preserved_score = accepted_score
            preserved_source = accepted_source
        else:
            preserved_score = baseline_score
            preserved_source = baseline_score_source
        if preserved_score > 0:
            gate["accepted_score"] = round(preserved_score, 3)
            gate["accepted_score_source"] = preserved_source
        return gate
    return gate


def _avg_support_actions_per_career(samples, key):
    rows = [sample for sample in samples or [] if sample.get("support_actions")]
    if not rows:
        return 0.0
    total = 0.0
    for sample in rows:
        total += sum(
            1
            for action in sample.get("support_actions") or []
            if str((action or {}).get("kind") or "") == key
            or (
                key == "optional_race"
                and str((action or {}).get("kind") or "") == "race"
                and bool((action or {}).get("optional_race"))
            )
        )
    return total / len(rows)


def learn_run_mode_policy(top_samples, all_samples):
    completed = completed_samples(all_samples)
    top_completed = completed_samples(top_samples) or top_samples
    if not completed or not top_completed:
        return {}
    top_losses = avg_race_metric(top_completed, "race_losses")
    all_losses = avg_race_metric(completed, "race_losses")
    top_score = _avg_score(top_completed)
    all_score = _avg_score(completed)
    top_optional = _avg_support_actions_per_career(top_completed, "optional_race")
    all_optional = _avg_support_actions_per_career(completed, "optional_race")
    preserve_rest_bonus = 3 if top_losses + 0.2 < all_losses else 2
    preserve_optional_penalty = 0.05 if top_losses + 0.25 < all_losses else 0.03
    preserve_training_penalty = 0.03 if top_score >= all_score + 1200 else 0.02
    push_optional_bonus = 0.03 if top_optional >= all_optional + 0.35 and top_losses <= all_losses + 0.15 else 0.02
    push_training_bonus = 0.025 if top_optional >= all_optional + 0.35 else 0.015
    push_rest_penalty = 2 if top_score >= all_score + 800 else 1
    return {
        "schema": "sweepy_run_mode_policy_v1",
        "enabled": True,
        "preserve_confidence": 0.62,
        "push_confidence": 0.45,
        "preserve_rest_bonus": preserve_rest_bonus,
        "push_rest_penalty": push_rest_penalty,
        "preserve_optional_race_penalty": round(preserve_optional_penalty, 4),
        "preserve_training_score_penalty": round(preserve_training_penalty, 4),
        "push_optional_race_bonus": round(push_optional_bonus, 4),
        "push_training_score_bonus": round(push_training_bonus, 4),
        "top_optional_races_per_career": round(top_optional, 4),
        "all_optional_races_per_career": round(all_optional, 4),
    }


def learn_race_style_overrides(per_race_hints, race_success_hints):
    overrides = {
        "schema": "sweepy_race_style_overrides_v2",
        "global": {},
        "by_chara": {},
    }
    for program_id, hint in (race_success_hints or {}).items():
        if not isinstance(hint, dict):
            continue
        for chara_key, row in ((hint.get("preferred_running_style_by_chara") or {}).items()):
            if not isinstance(row, dict):
                continue
            style = str(row.get("style") or "").strip()
            if not style:
                continue
            share = as_float(row.get("share"))
            wins = as_int(row.get("wins"))
            confidence = as_float(hint.get("confidence"))
            if share >= 0.55 and wins >= 2 and confidence >= 0.35:
                by_chara = overrides["by_chara"].setdefault(str(chara_key), {})
                by_chara[str(program_id)] = style
        style = str(hint.get("preferred_running_style") or "").strip()
        if not style:
            continue
        share = as_float(hint.get("preferred_running_style_share"))
        confidence = as_float(hint.get("confidence"))
        win_rate = as_float(hint.get("win_rate"))
        if share >= 0.70 and confidence >= 0.60 and win_rate >= 0.60:
            overrides["global"][str(program_id)] = style
    for program_id, hint in (per_race_hints or {}).items():
        if str(program_id) in overrides["global"]:
            continue
        diagnosis = (hint or {}).get("diagnosis") or {}
        style = str(diagnosis.get("style_advice") or "").strip()
        if not style:
            continue
        if bool(diagnosis.get("chronic")) or as_int((hint or {}).get("loss_count")) >= 5:
            overrides["global"][str(program_id)] = style
    if not overrides["global"] and not overrides["by_chara"]:
        return {}
    return overrides


def build_postmortem_feedback_refresh(base_dir, preset_name, current_preset=None, runtime_paths=None):
    """Rebuild only the race-loss feedback fields from recent G1 postmortems.

    This is used for interrupted / stopped careers that should NOT feed the
    turn-level learner, while still allowing their G1 losses to update the
    race-specific loss memory immediately.
    """
    source_name = str(preset_name or (current_preset or {}).get("name") or "").strip()
    if not source_name:
        return None, {"skipped": "missing_preset_name"}

    store = PresetStore(base_dir)
    base_preset = store.read_one(source_name) or {}
    effective = current_preset or base_preset
    if not isinstance(effective, dict) or not effective:
        return None, {"skipped": "missing_preset"}

    learned = normalize_preset(copy.deepcopy(effective))
    learned["name"] = source_name

    resolved_runtime_roots = [str(root) for root in runtime_roots(base_dir, runtime_paths)]
    postmortem_root = preferred_postmortem_runtime_root(base_dir, runtime_paths)
    if postmortem_root is None:
        return None, {
            "skipped": "missing_runtime_root",
            "source_preset": source_name,
            "runtime_roots_used": resolved_runtime_roots,
        }

    from career_bot.postmortem_feedback import POSTMORTEM_FEEDBACK_SCHEMA

    per_race_hints = race_stat_hints(postmortem_root)
    attempt_history = load_race_attempt_history(postmortem_root)
    per_race_hints = attach_diagnoses(per_race_hints, attempt_history)
    global_hint = merge_global_signal(per_race_hints)
    # Hard per-race stat targets rebuild every refresh — see comment in
    # learn_preset's hint block. Cheap to recompute and the bot reads
    # from the file directly, not from the preset.
    try:
        from career_bot.race_thresholds import build_and_write_race_thresholds
        build_and_write_race_thresholds(postmortem_root)
    except Exception as exc:  # noqa: BLE001
        print(f"race_thresholds build skipped: {exc}")
    if not per_race_hints and not global_hint:
        return None, {
            "skipped": "no_postmortem_hints",
            "source_preset": source_name,
            "runtime_roots_used": resolved_runtime_roots,
            "hint_count": 0,
        }
    race_success_hints = copy.deepcopy((learned.get("race_specific_success_hints") or {}))
    # Learned race_style_overrides is OFF by default. User explicitly
    # opted out: "I don't want it changing styles if that's what I have
    # set for it." The bot respects the user's skill_profile_style +
    # any per-race user-set overrides; it does NOT override them based
    # on postmortem-derived style hints. Flip
    # `race_style_overrides_learned_enabled = true` on the preset to
    # re-enable learned style overrides.
    learn_styles_enabled = bool((effective or {}).get("race_style_overrides_learned_enabled", False))
    if learn_styles_enabled:
        learned_race_style_overrides = learn_race_style_overrides(per_race_hints, race_success_hints)
    else:
        learned_race_style_overrides = {}

    learned["postmortem_feedback_schema"] = POSTMORTEM_FEEDBACK_SCHEMA
    learned["race_specific_stat_hints"] = per_race_hints
    learned["postmortem_global_hint"] = global_hint
    if race_success_hints:
        learned["race_specific_success_hints"] = race_success_hints
    if learned_race_style_overrides or learned.get("race_style_overrides"):
        learned["race_style_overrides"] = learned_race_style_overrides

    meta = dict(learned.get("learning_metadata") or {})
    meta["last_postmortem_refresh_at"] = datetime.now().isoformat(timespec="seconds")
    meta["last_postmortem_refresh_reason"] = "status_not_enabled"
    meta["last_postmortem_hint_count"] = len(per_race_hints)
    learned["learning_metadata"] = meta

    report = {
        "schema": "sweepy_postmortem_refresh_report_v1",
        "created_at": meta["last_postmortem_refresh_at"],
        "source_preset": source_name,
        "learned_preset": source_name,
        "mode": "postmortem_only",
        "postmortem_feedback_schema": POSTMORTEM_FEEDBACK_SCHEMA,
        "runtime_roots_used": resolved_runtime_roots,
        "race_specific_stat_hints": per_race_hints,
        "postmortem_global_hint": global_hint,
        "race_style_overrides": learned_race_style_overrides,
        "hint_count": len(per_race_hints),
    }
    return learned, report


def split_action_classifier_groups(samples, min_actions_per_sample=20, min_per_action_gain=0.0, preset=None):
    """Pick top/bottom samples specifically for the per-action linear classifier.

    Different objective than `split_reference_groups`: the action classifier
    needs real turn choices, but it must not call a losing/low-output career
    "top" just because its per-turn gain proxy looked efficient. Positive
    samples must pass `policy_steering_gate`; failed runs stay available only
    as bottom/diagnostic evidence.

    Selection criteria:
      - Require a real action sequence (>= min_actions_per_sample actions).
      - Rank by average weighted_gain per action — the bot's own per-turn
        efficiency proxy. Higher = better choices.
      - Top 25% / bottom 25%, drop samples with no positive efficiency.

    Returns (top, bottom) lists. Empty top means the model fit will be skipped
    (caller's responsibility) rather than fitting on noise.
    """
    candidates = []
    positives = []
    negatives = []
    for sample in samples:
        actions = sample.get("actions") or []
        if len(actions) < min_actions_per_sample:
            continue
        total = 0.0
        count = 0
        for action in actions:
            value = as_float(action.get("weighted_gain"))
            if value <= 0:
                continue
            total += value
            count += 1
        if count == 0:
            continue
        per_action = total / count
        if per_action <= min_per_action_gain:
            continue
        gate = policy_steering_gate(
            sample,
            preset=preset,
            require_actions=True,
            min_actions=min_actions_per_sample,
        )
        meta = sample.get("learning_metadata") or {}
        meta["policy_steering_gate"] = gate
        sample["learning_metadata"] = meta
        severity = len(gate.get("reasons") or [])
        severity += as_int(gate.get("g1_losses")) * 2
        severity += as_int(gate.get("race_losses"))
        row = (per_action, as_float(sample.get("rank_score") or sample.get("score")), severity, sample)
        candidates.append(row)
        if gate.get("steering_allowed"):
            positives.append(row)
        else:
            negatives.append(row)
    if len(candidates) < 4:
        return [], []
    count = max(1, math.ceil(len(candidates) * 0.25))
    if not positives:
        negatives.sort(key=lambda item: (item[2], item[0], item[1]), reverse=True)
        return [], [sample for _, _, _, sample in negatives[:count]]
    positives.sort(key=lambda item: (item[0], item[1]), reverse=True)
    negatives.sort(key=lambda item: (item[2], item[0], item[1]), reverse=True)
    top = [sample for _, _, _, sample in positives[:min(len(positives), count)]]
    bottom_rows = negatives[:count]
    if len(bottom_rows) < count:
        bottom_rows.extend(list(reversed(positives[-(count - len(bottom_rows)):])) )
    bottom = [sample for _, _, _, sample in bottom_rows]
    return top, bottom


def stratified_top_bottom_split(samples, top_fraction=0.25, min_bucket_size=4):
    """Stratify samples by (objective_bucket, deck_quality_bucket) before
    picking top/bottom. Prevents the tuner from "learning" that good plays
    look like premium SSR deck plays — instead each (objective, deck) cell
    gets its own local top/bottom comparison.

    Returns (top, bottom, bucket_stats) where bucket_stats is a dict that
    can be persisted in the learning report for visibility.

    Small buckets fall back to a coarser (objective-only) split so we still
    get signal when a (objective, deck) cell has only 1-2 careers.
    """
    from collections import defaultdict as _defaultdict

    try:
        from career_bot.objectives import objective_bucket_key
    except Exception:
        objective_bucket_key = lambda _session: "balanced_any"

    def bucket_key(sample):
        meta = sample.get("learning_metadata") or {}
        obj_key = objective_bucket_key(meta.get("session") or {})
        deck_q = meta.get("deck_quality_bucket", 2)
        return (obj_key, deck_q)

    buckets = _defaultdict(list)
    for sample in samples:
        # `learn_preset` passes behavior-filtered samples here, but this helper
        # is also used directly by tests/tools with synthetic rows that only
        # contain score + objective metadata. Keep the hard exclusion for
        # parent-library snapshots without requiring every caller to build a
        # full career sample.
        source = str((sample or {}).get("source") or "").strip().lower()
        if source.endswith("_parent_library"):
            continue
        buckets[bucket_key(sample)].append(sample)

    top_samples = []
    bottom_samples = []
    bucket_stats = {}
    fallback_samples = []

    for key, bucket_samples in buckets.items():
        bucket_label = f"{key[0]}|deck_q={key[1]}"
        if len(bucket_samples) < min_bucket_size:
            fallback_samples.extend(bucket_samples)
            bucket_stats[f"{bucket_label}_skipped_small"] = len(bucket_samples)
            continue
        sorted_bucket = sorted(
            bucket_samples, key=lambda s: as_float(s.get("score"), 0.0), reverse=True
        )
        n = len(sorted_bucket)
        top_n = max(1, int(n * top_fraction))
        top_samples.extend(sorted_bucket[:top_n])
        bottom_samples.extend(sorted_bucket[-top_n:])
        bucket_stats[bucket_label] = {
            "total": n,
            "top_count": top_n,
            "bottom_count": top_n,
            "top_score_range": [
                round(as_float(sorted_bucket[top_n - 1].get("score"), 0.0), 2),
                round(as_float(sorted_bucket[0].get("score"), 0.0), 2),
            ],
        }

    if fallback_samples:
        obj_buckets = _defaultdict(list)
        for sample in fallback_samples:
            meta = sample.get("learning_metadata") or {}
            obj_key = objective_bucket_key(meta.get("session") or {})
            obj_buckets[obj_key].append(sample)
        for obj_key, obj_samples in obj_buckets.items():
            if len(obj_samples) < min_bucket_size:
                bucket_stats[f"{obj_key}_fallback_too_small"] = len(obj_samples)
                continue
            sorted_obj = sorted(
                obj_samples, key=lambda s: as_float(s.get("score"), 0.0), reverse=True
            )
            n = len(sorted_obj)
            top_n = max(1, int(n * top_fraction))
            top_samples.extend(sorted_obj[:top_n])
            bottom_samples.extend(sorted_obj[-top_n:])
            bucket_stats[f"{obj_key}_fallback"] = {"total": n, "top_count": top_n}

    return top_samples, bottom_samples, bucket_stats


def _floor_for_sample(sample, score_floor, score_floors_by_deck):
    """Resolve the score floor that applies to a single sample.

    Precedence:
      1. If a per-deck-bucket map is provided, look up the sample's
         deck_quality_bucket. Missing bucket -> bucket 2 (mixed).
      2. Else fall back to the single absolute floor.
      3. None -> no floor filter.
    """
    if score_floors_by_deck:
        bucket = sample.get("deck_quality_bucket")
        if bucket is None:
            bucket = 2
        try:
            bucket = int(bucket)
        except (TypeError, ValueError):
            bucket = 2
        if bucket in score_floors_by_deck:
            return float(score_floors_by_deck[bucket])
        # Fall through to legacy single floor as last resort.
    if score_floor is not None:
        return float(score_floor)
    return None


def _rank_score_floor_for_target_band(target_band):
    band = str(target_band or "").strip().lower()
    if band == "high":
        return as_float(WHITE_STAR_RATES_BY_RANK_SCORE["mid"]["threshold"])
    if band == "mid":
        return as_float(WHITE_STAR_RATES_BY_RANK_SCORE["low"]["threshold"])
    return None


def _rank_score_floor_for_sample(sample):
    rank_score = as_float((sample or {}).get("rank_score"), 0.0)
    if rank_score <= 0:
        return None
    meta = (sample or {}).get("learning_metadata") or {}
    session = meta.get("session") or {}
    if not isinstance(session, dict):
        return None
    white_intent = session.get("white_spark_intent") or {}
    if not isinstance(white_intent, dict):
        return None
    return _rank_score_floor_for_target_band(white_intent.get("target_rank_score_band"))


def _sample_clears_top_reference_floor(sample, score_floor=None, score_floors_by_deck=None, preset=None):
    floor = _floor_for_sample(sample, score_floor, score_floors_by_deck)
    if floor is not None and as_float(sample.get("score")) < floor:
        return False
    rank_floor = _rank_score_floor_for_sample(sample)
    if rank_floor is not None and as_float(sample.get("rank_score")) < rank_floor:
        return False
    gate = policy_steering_gate(sample, preset=preset, require_actions=False)
    if gate.get("diagnostic_only"):
        meta = sample.get("learning_metadata") or {}
        meta["policy_steering_gate"] = gate
        sample["learning_metadata"] = meta
        return False
    return True


def split_reference_groups(samples, score_floor=None, score_floors_by_deck=None, preset=None):
    """Split samples into top + bottom reference groups.

    score_floor: absolute minimum score for the "top" group. Legacy
    single-value form. Applies to every sample regardless of deck.

    score_floors_by_deck: dict {deck_bucket: floor}. Preferred form when
    the sample pool mixes deck qualities. Each sample is filtered against
    its own deck-bucket floor — so SR-heavy runs can qualify as "top"
    relative to the SR floor, even when their absolute score would never
    cross the SSR-tier floor. Without per-deck floors, low-deck accounts
    never produce a top sample and the model gets no positive signal
    from them.

    Bottom group keeps everything — the bottom of even a bad pool still
    anchors "what not to do". Only the top must be elite for the model
    to learn anything useful.
    """
    representative = []
    for sample in samples:
        if not _is_behavior_learning_sample(sample):
            continue
        action_count = len(sample.get("actions") or [])
        race_total = as_int((sample.get("race_quality") or {}).get("race_total"))
        has_real_parent_score = as_int(sample.get("rank_score")) > 1000
        if has_real_parent_score or action_count >= 20 or race_total >= 8:
            representative.append(sample)
    usable = representative
    if not usable:
        return [], []
    count = max(1, math.ceil(len(usable) * 0.25))
    top = usable[:count]
    bottom = usable[-count:] if len(usable) > count else usable
    if score_floor is not None or score_floors_by_deck:
        qualified = []
        for s in top:
            if _sample_clears_top_reference_floor(s, score_floor=score_floor, score_floors_by_deck=score_floors_by_deck, preset=preset):
                qualified.append(s)
        top = qualified
    else:
        top = [
            s for s in top
            if _sample_clears_top_reference_floor(s, score_floor=score_floor, score_floors_by_deck=score_floors_by_deck, preset=preset)
        ]
    return top, bottom


def action_distribution(samples):
    by_extra = [[0.0 for _ in range(5)] for _ in range(4)]
    by_period = [[empty_action_stats() for _ in range(5)] for _ in range(5)]
    overall = [empty_action_stats() for _ in range(5)]
    total_actions = 0.0
    for sample in samples:
        sample_weight = as_float(sample.get("sample_weight"), 1.0)
        score_weight = clamp(as_float(sample.get("score")) / 9000.0, 0.55, 1.85)
        weight = sample_weight * score_weight
        for action in sample.get("actions") or []:
            idx = as_int(action.get("idx"), -1)
            if idx < 0 or idx >= 5:
                continue
            extra = clamp(as_int(action.get("extra_phase")), 0, 3)
            period = clamp(as_int(action.get("period")), 0, 4)
            by_extra[extra][idx] += weight
            add_action_stats(by_period[period][idx], action, weight)
            add_action_stats(overall[idx], action, weight)
            total_actions += weight
    return {"by_extra": by_extra, "by_period": by_period, "overall": overall, "total_actions": total_actions}


def weighted_action_distribution(samples):
    """Same shape as `action_distribution` but each action's accumulated
    weight is driven by its per-decision quality.

    The career-level weight (sample_weight × score_weight) still applies —
    a bad career's actions still carry less influence than a good career's.
    But within a single career, high-quality decisions (rainbow training,
    low failure, high stat gain) now contribute more weight per action than
    low-quality ones, where the existing `action_distribution` treated all
    actions in a sample equally.

    Composition is non-multiplicative: action weight is the greater of the
    decision-quality multiplier and half the career-level weight. This keeps
    high-quality actions from being erased just because the overall career was
    mediocre.

    Effectively turns each career from "one data point" into "as many
    data points as it has training actions, weighted by quality". The
    biggest single lever for per-decision learning in this codebase.
    """
    from career_bot.decision_quality import combined_decision_quality, quality_multiplier, score_action_followthrough

    by_extra = [[0.0 for _ in range(5)] for _ in range(4)]
    by_period = [[empty_action_stats() for _ in range(5)] for _ in range(5)]
    overall = [empty_action_stats() for _ in range(5)]
    total_actions = 0.0
    raw_quality_sum = 0.0
    raw_quality_count = 0
    raw_followthrough_sum = 0.0
    for sample in samples:
        if not isinstance(sample, dict):
            continue
        sample_weight = as_float(sample.get("sample_weight"), 1.0)
        score_weight = clamp(as_float(sample.get("score")) / 9000.0, 0.55, 1.85)
        career_weight = sample_weight * score_weight
        actions = sample.get("actions")
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict):
                continue
            idx = as_int(action.get("idx"), -1)
            if idx < 0 or idx >= 5:
                continue
            quality = as_float(action.get("decision_quality"))
            # NaN check: as_float can return float('nan') if the JSON had NaN
            # in it. NaN poisons every downstream comparison.
            if quality != quality:
                quality = 0.0
            if quality <= 0:
                # Fallback path for samples that weren't annotated upstream
                # (e.g. older logs loaded before this code shipped).
                quality = combined_decision_quality(action, action.get("training_snapshot"))
            raw_quality_sum += quality
            raw_quality_count += 1
            raw_followthrough_sum += score_action_followthrough(action)
            decision_weight = quality_multiplier(quality)
            weight = max(decision_weight, career_weight * 0.5)
            extra = clamp(as_int(action.get("extra_phase")), 0, 3)
            period = clamp(as_int(action.get("period")), 0, 4)
            by_extra[extra][idx] += weight
            add_action_stats(by_period[period][idx], action, weight)
            add_action_stats(overall[idx], action, weight)
            total_actions += weight
    avg_quality = raw_quality_sum / raw_quality_count if raw_quality_count else 0.0
    avg_followthrough = raw_followthrough_sum / raw_quality_count if raw_quality_count else 0.0
    return {
        "by_extra": by_extra,
        "by_period": by_period,
        "overall": overall,
        "total_actions": total_actions,
        "average_quality": round(avg_quality, 3),
        "average_followthrough": round(avg_followthrough, 3),
        "action_count": raw_quality_count,
    }


def row_rates(counts):
    total = sum(counts)
    if total <= 0:
        return [0.0 for _ in counts]
    return [value / total for value in counts]


def ensure_matrix(value, rows, cols, default=0.0):
    result = []
    for row_idx in range(rows):
        source = value[row_idx] if isinstance(value, list) and row_idx < len(value) and isinstance(value[row_idx], list) else []
        row = []
        for col_idx in range(cols):
            row.append(as_float(source[col_idx], default) if col_idx < len(source) else default)
        result.append(row)
    return result


def ensure_vector(value, length, default=0.0):
    return [as_float(value[idx], default) if isinstance(value, list) and idx < len(value) else default for idx in range(length)]


def completed_samples(samples):
    return [sample for sample in samples if is_full_career_sample(sample)]


def aggregate_future_turn_effects(samples):
    usable = [
        sample for sample in completed_samples(samples)
        if as_int(sample.get("observed_turn_count"), as_int(sample.get("turn_count"))) >= MIN_FULL_CAREER_OBSERVED_TURNS
    ]
    if len(usable) < 3:
        return {}

    by_turn = {}
    for sample in usable:
        curve = sample.get("future_effect_curve") or []
        if not isinstance(curve, list):
            continue
        seen_turns = set()
        for row in curve:
            if not isinstance(row, dict):
                continue
            turn = as_int(row.get("turn"))
            if turn <= 0 or turn in seen_turns:
                continue
            seen_turns.add(turn)
            bucket = by_turn.setdefault(turn, {
                "rows": [],
                "kind_counts": Counter(),
                "program_ids": Counter(),
            })
            bucket["rows"].append(row)
            kind = str(row.get("kind") or "unknown").strip().lower() or "unknown"
            bucket["kind_counts"][kind] += 1
            program_id = as_int(row.get("program_id"))
            if program_id > 0:
                bucket["program_ids"][program_id] += 1

    turns_out = {}
    for turn, bucket in sorted(by_turn.items()):
        rows = bucket.get("rows") or []
        sample_count = len(rows)
        if sample_count < FUTURE_EFFECT_MIN_SAMPLES:
            continue
        kind_counts = bucket.get("kind_counts") or Counter()
        dominant_kind, dominant_kind_count = kind_counts.most_common(1)[0] if kind_counts else ("unknown", 0)
        dominant_kind_rate = dominant_kind_count / max(1, sample_count)
        effects = {}
        consistency = {}
        for key in FUTURE_EFFECT_KEYS:
            values = [as_float((row.get("delta") or {}).get(key)) for row in rows]
            if not values:
                continue
            median = statistics.median(values)
            if median <= 0:
                continue
            if key == "hp":
                threshold = FUTURE_EFFECT_HP_MIN_MEDIAN
            elif key == "skill_point":
                threshold = FUTURE_EFFECT_SKILL_POINT_MIN_MEDIAN
            else:
                threshold = FUTURE_EFFECT_STAT_MIN_MEDIAN
            positive_rate = sum(1 for value in values if value >= max(1.0, threshold * 0.5)) / max(1, len(values))
            if median < threshold or positive_rate < FUTURE_EFFECT_MIN_POSITIVE_RATE:
                continue
            effects[key] = round(median, 4)
            consistency[key] = round(positive_rate, 4)
        if not effects:
            continue
        entry = {
            "kind": dominant_kind,
            "sample_count": sample_count,
            "dominant_kind_rate": round(dominant_kind_rate, 4),
            "effects": effects,
            "consistency": consistency,
        }
        if dominant_kind == "race" and bucket.get("program_ids"):
            program_id, _ = bucket["program_ids"].most_common(1)[0]
            if program_id > 0:
                entry["program_id"] = program_id
        turns_out[str(turn)] = entry

    if not turns_out:
        return {}
    return {
        "schema": "sweepy_future_turn_effects_v1",
        "turns": turns_out,
        "min_sample_count": FUTURE_EFFECT_MIN_SAMPLES,
        "full_career_min_turns": MIN_FULL_CAREER_OBSERVED_TURNS,
    }


class LearnedPresetInvariantError(ValueError):
    """Raised when a tuner produces a preset value outside the expected
    schema/bounds. The auto-tuner has internal clamps, but those clamps can
    be wrong (off-by-one, sign flip, refactor bug, etc.) and a silently
    wrong preset will degrade hundreds of careers before the regression
    is noticed. Better to raise loudly and keep the old preset than to
    overwrite with bad math."""


def assert_learned_preset_invariants(learned):
    """Defensive contract for tuner outputs. Each tune_* function has its
    own internal clamp/range; this function re-verifies those clamps
    actually did their job by the time `learn_preset` is about to return.

    Catches regressions where a refactor accidentally widens a bound, flips
    a sign, double-counts a bucket, or produces NaN/None where a number
    was expected. Cheap to call (microseconds), catches silent regressions
    that would otherwise compound over many careers.
    """
    if not isinstance(learned, dict):
        raise LearnedPresetInvariantError(f"learned preset is not a dict: {type(learned).__name__}")

    targets = learned.get("expect_attribute") or []
    if not isinstance(targets, list) or len(targets) != 5:
        raise LearnedPresetInvariantError(f"expect_attribute must be a 5-element list, got {targets!r}")
    for idx, value in enumerate(targets):
        if not isinstance(value, (int, float)) or not (300 <= value <= 1600):
            raise LearnedPresetInvariantError(
                f"expect_attribute[{idx}] = {value!r} is out of plausible stat range [300, 1600]"
            )
    profiles = learned.get("expect_attribute_profiles") or {}
    if profiles and not isinstance(profiles, dict):
        raise LearnedPresetInvariantError(
            f"expect_attribute_profiles must be a dict, got {type(profiles).__name__}"
        )
    for key, entry in profiles.items():
        profile_targets = entry.get("expect_attribute") if isinstance(entry, dict) else entry
        if not isinstance(profile_targets, list) or len(profile_targets) != 5:
            raise LearnedPresetInvariantError(
                f"expect_attribute_profiles[{key!r}] must hold a 5-element list, got {profile_targets!r}"
            )
        for idx, value in enumerate(profile_targets):
            if not isinstance(value, (int, float)) or not (300 <= value <= 1600):
                raise LearnedPresetInvariantError(
                    f"expect_attribute_profiles[{key!r}][{idx}] = {value!r} is out of plausible stat range [300, 1600]"
                )

    extra_weight = learned.get("extra_weight") or []
    if not isinstance(extra_weight, list) or len(extra_weight) != 4:
        raise LearnedPresetInvariantError(f"extra_weight must be a 4x5 matrix, got rows={len(extra_weight)}")
    for row_idx, row in enumerate(extra_weight):
        if not isinstance(row, list) or len(row) != 5:
            raise LearnedPresetInvariantError(
                f"extra_weight[{row_idx}] must be a 5-element list, got {row!r}"
            )
        for col_idx, value in enumerate(row):
            if not isinstance(value, (int, float)) or not (-0.12 <= value <= 0.25):
                raise LearnedPresetInvariantError(
                    f"extra_weight[{row_idx}][{col_idx}] = {value!r} outside [-0.12, 0.25]"
                )

    base_score = learned.get("base_score") or []
    if not isinstance(base_score, list) or len(base_score) != 5:
        raise LearnedPresetInvariantError(f"base_score must be a 5-element list, got {base_score!r}")
    for idx, value in enumerate(base_score):
        if not isinstance(value, (int, float)) or not (-0.08 <= value <= 0.12):
            raise LearnedPresetInvariantError(
                f"base_score[{idx}] = {value!r} outside [-0.08, 0.12]"
            )

    rest_threshold = learned.get("rest_threshold")
    if not isinstance(rest_threshold, int) or not (30 <= rest_threshold <= 75):
        raise LearnedPresetInvariantError(
            f"rest_threshold = {rest_threshold!r} outside plausible [30, 75]"
        )

    skill_threshold = learned.get("learn_skill_threshold")
    if not isinstance(skill_threshold, int) or not (50 <= skill_threshold <= 1000):
        raise LearnedPresetInvariantError(
            f"learn_skill_threshold = {skill_threshold!r} outside plausible [50, 1000]"
        )

    or_max = learned.get("optional_race_max_training_score")
    if or_max is not None and not (0.0 <= as_float(or_max) <= 1.0):
        raise LearnedPresetInvariantError(
            f"optional_race_max_training_score = {or_max!r} outside [0.0, 1.0]"
        )

    or_min = learned.get("optional_race_min_value")
    if or_min is not None and not (0.0 <= as_float(or_min) <= 1.5):
        raise LearnedPresetInvariantError(
            f"optional_race_min_value = {or_min!r} outside [0.0, 1.5]"
        )

    score_value = learned.get("score_value") or []
    if score_value:
        if not isinstance(score_value, list) or len(score_value) != 5:
            raise LearnedPresetInvariantError(f"score_value must be a 5x4 matrix, got rows={len(score_value)}")
        # Column-specific clamps: cols 0/1 ride to 0.22, col 3 to 0.18, col 2
        # (energy weight) is intentionally TINY in the tuner (cap 0.010). A
        # uniform [-0.05, 0.30] invariant would silently allow a refactor to
        # widen the energy column 30× its real ceiling without raising.
        col_max = {0: 0.18, 1: 0.18, 2: 0.010, 3: 0.18}
        for row_idx, row in enumerate(score_value):
            if not isinstance(row, list) or len(row) != 4:
                raise LearnedPresetInvariantError(
                    f"score_value[{row_idx}] must be a 4-element list, got {row!r}"
                )
            for col_idx, value in enumerate(row):
                ceiling = col_max.get(col_idx, 0.30)
                if not isinstance(value, (int, float)) or not (-0.05 <= value <= ceiling):
                    raise LearnedPresetInvariantError(
                        f"score_value[{row_idx}][{col_idx}] = {value!r} outside [-0.05, {ceiling}]"
                    )

    stat_mult = learned.get("stat_value_multiplier")
    if stat_mult is not None:
        if not isinstance(stat_mult, list) or len(stat_mult) < 5:
            raise LearnedPresetInvariantError(
                f"stat_value_multiplier must be a list of at least 5 floats, got {stat_mult!r}"
            )
        # Tuner clamps stat slots [0..4] to [0.004, 0.050] and SP slot [5] to [0.002, 0.010].
        for idx, value in enumerate(stat_mult[:6]):
            ceiling = 0.050 if idx < 5 else 0.010
            if not isinstance(value, (int, float)) or not (0.0 <= value <= ceiling):
                raise LearnedPresetInvariantError(
                    f"stat_value_multiplier[{idx}] = {value!r} outside [0.0, {ceiling}]"
                )

    for key in ("optional_race_epithet_bonus", "optional_race_rival_bonus"):
        value = learned.get(key)
        if value is not None and not (0.0 <= as_float(value) <= 0.60):
            raise LearnedPresetInvariantError(
                f"{key} = {value!r} outside [0.0, 0.60]"
            )


def learning_rate_scale(top_count, action_count, baseline_top=8, baseline_actions=200):
    """Scale tune_* damping factors based on how much data backs the current
    decision. With few samples, we want bigger moves to converge fast. With
    many samples, smaller moves to avoid jittering around a local optimum.

    Returns a scalar in [0.25, 1.5]:
      - >1.0 when sample count is well below baseline (early-phase)
      - 1.0 around baseline (8 top samples / 200 actions)
      - <1.0 as sample count grows past baseline
      - clamped at 0.25 so updates never freeze entirely

    Without this scale, the fixed damping factors (e.g. 0.55 in
    tune_extra_weight) keep nudging the preset by the same magnitude
    regardless of whether we have 8 top samples or 80 — late-phase updates
    end up chasing sample noise instead of refining toward a stable point.
    """
    top_count = max(1, int(top_count or 0))
    action_count = max(1, int(action_count or 0))
    top_ratio = baseline_top / top_count
    action_ratio = baseline_actions / action_count
    raw = math.sqrt(top_ratio * action_ratio)
    return clamp(raw, 0.25, 1.5)


def tune_expect_attribute(preset, top_samples, all_samples):
    old_targets = ensure_vector(preset.get("expect_attribute"), 5, 1166)
    minimum_targets = ensure_vector(
        (preset or {}).get("expect_attribute_minimum")
        or (preset or {}).get("expect_attribute_floor"),
        5,
        0,
    )
    reference = completed_samples(top_samples) or completed_samples(all_samples) or top_samples
    result = list(old_targets)
    learning_rate = clamp(as_float((preset or {}).get("expect_attribute_learning_rate"), 0.25), 0.0, 1.0)
    sharp_up_rate = clamp(as_float((preset or {}).get("expect_attribute_sharp_up_rate"), 0.50), learning_rate, 1.0)
    sharp_up_threshold = max(0.0, as_float((preset or {}).get("expect_attribute_sharp_up_threshold"), 50.0))
    cushion = as_float((preset or {}).get("expect_attribute_cushion"), 25.0)
    for idx, key in enumerate(STAT_KEYS):
        values = []
        for sample in reference:
            value = (sample.get("final_stats") or {}).get(key)
            if value:
                values.append((value, sample.get("sample_weight", 1.0)))
        pct = weighted_percentile(values, 0.80)
        if pct is None:
            continue
        observed_target = pct + cushion
        old_target = old_targets[idx]
        rate = sharp_up_rate if observed_target > old_target + sharp_up_threshold else learning_rate
        adjusted = old_target + (observed_target - old_target) * rate
        result[idx] = int(max(minimum_targets[idx], clamp(adjusted, 500, 1200)))
    return result


def _sample_expect_attribute_profile_lookup_keys(sample):
    meta = (sample or {}).get("learning_metadata") or {}
    run_context = (sample or {}).get("run_context") or {}
    return expect_attribute_profile_lookup_keys(
        session=meta.get("session") or {},
        run_context=run_context,
        desired_parent_sparks=(sample or {}).get("desired_parent_sparks") or run_context.get("desired_parent_sparks"),
        style=(sample or {}).get("skill_profile_style"),
        distance=(sample or {}).get("skill_profile_distance"),
        deck_quality_bucket=(
            meta.get("deck_quality_bucket")
            if meta.get("deck_quality_bucket") is not None
            else (sample or {}).get("deck_quality_bucket")
        ),
    )


def tune_expect_attribute_profile(top_samples, all_samples, default_targets=None, minimum_targets=None):
    result = ensure_vector(default_targets, 5, 1166)
    floors = ensure_vector(minimum_targets, 5, 0)
    reference = completed_samples(top_samples) or completed_samples(all_samples) or top_samples
    for idx, key in enumerate(STAT_KEYS):
        values = []
        for sample in reference:
            value = (sample.get("final_stats") or {}).get(key)
            if value:
                values.append((value, sample.get("sample_weight", 1.0)))
        pct = weighted_percentile(values, 0.80)
        if pct is None:
            continue
        result[idx] = int(max(floors[idx], clamp(pct + 25, 500, 1200)))
    return result


def learn_expect_attribute_profiles(preset, top_samples, all_samples, default_targets=None, min_bucket_size=4):
    completed_all = completed_samples(all_samples)
    completed_top = completed_samples(top_samples) or completed_all
    if not completed_all:
        return {}
    minimum_targets = (
        (preset or {}).get("expect_attribute_minimum")
        or (preset or {}).get("expect_attribute_floor")
    )
    top_groups = {}
    all_groups = {}
    for sample in completed_all:
        for key in _sample_expect_attribute_profile_lookup_keys(sample):
            all_groups.setdefault(key, []).append(sample)
    for sample in completed_top:
        for key in _sample_expect_attribute_profile_lookup_keys(sample):
            top_groups.setdefault(key, []).append(sample)
    profiles = {}
    for key, bucket_all in sorted(all_groups.items()):
        if len(bucket_all) < max(1, int(min_bucket_size or 0)):
            continue
        bucket_top = top_groups.get(key) or bucket_all
        targets = tune_expect_attribute_profile(
            bucket_top,
            bucket_all,
            default_targets=default_targets,
            minimum_targets=minimum_targets,
        )
        profiles[key] = {
            "expect_attribute": targets,
            "sample_count": len(bucket_all),
            "top_sample_count": len(bucket_top),
        }
    return profiles


def tune_stat_value_multiplier(preset, top_samples, all_samples, targets):
    old = ensure_vector(preset.get("stat_value_multiplier"), 6, 0.01)
    floors = ensure_vector(
        (preset or {}).get("stat_value_multiplier_minimum")
        or (preset or {}).get("stat_value_multiplier_floor"),
        6,
        0.0,
    )
    result = list(old)
    completed = completed_samples(all_samples)
    for idx, key in enumerate(STAT_KEYS):
        values = [(sample.get("final_stats") or {}).get(key, 0) for sample in completed if (sample.get("final_stats") or {}).get(key, 0)]
        if not values:
            continue
        median = statistics.median(values)
        target = targets[idx]
        gap = clamp((target - median) / max(target, 1), -0.25, 0.35)
        tuned = round(clamp(old[idx] * (1.0 + gap * 0.75), 0.004, 0.050), 5)
        result[idx] = round(max(floors[idx], tuned), 5)
    # Skill points are valuable but should not dominate stat training.
    sp_values = [(sample.get("final_stats") or {}).get("skill_point", 0) for sample in completed if (sample.get("final_stats") or {}).get("skill_point", 0)]
    if sp_values:
        sp_median = statistics.median(sp_values)
        if sp_median > 1200:
            result[5] = round(max(floors[5], clamp(old[5] * 0.92, 0.002, 0.010)), 5)
        elif sp_median < 450:
            result[5] = round(max(floors[5], clamp(old[5] * 1.08, 0.002, 0.010)), 5)
    result = [round(max(floors[idx], value), 5) for idx, value in enumerate(result)]
    return result


def tune_extra_weight(preset, top_dist, bottom_dist, lr_scale=1.0):
    old = ensure_matrix(preset.get("extra_weight"), 4, 5, 0.0)
    result = copy.deepcopy(old)
    base_step = 0.55 * float(lr_scale or 1.0)
    threshold = 0.012 * max(0.5, float(lr_scale or 1.0))
    for row_idx in range(4):
        top_rates = row_rates(top_dist["by_extra"][row_idx])
        bottom_rates = row_rates(bottom_dist["by_extra"][row_idx])
        for idx in range(5):
            delta = (top_rates[idx] - bottom_rates[idx]) * base_step
            if abs(delta) < threshold:
                continue
            result[row_idx][idx] = round(clamp(old[row_idx][idx] + delta, -0.12, 0.25), 4)
    return result


def tune_base_score(preset, top_dist, bottom_dist, lr_scale=1.0):
    old = ensure_vector(preset.get("base_score"), 5, 0.0)
    floors = ensure_vector(
        (preset or {}).get("base_score_minimum")
        or (preset or {}).get("base_score_floor"),
        5,
        -0.08,
    )
    result = list(old)
    base_step = 0.10 * float(lr_scale or 1.0)
    threshold = 0.006 * max(0.5, float(lr_scale or 1.0))
    top_rates = row_rates([row["count"] for row in top_dist["overall"]])
    bottom_rates = row_rates([row["count"] for row in bottom_dist["overall"]])
    for idx in range(5):
        delta = (top_rates[idx] - bottom_rates[idx]) * base_step
        if abs(delta) < threshold:
            continue
        tuned = round(clamp(old[idx] + delta, -0.08, 0.12), 4)
        result[idx] = round(max(floors[idx], tuned), 4)
    result = [round(max(floors[idx], value), 4) for idx, value in enumerate(result)]
    return result


def tune_score_value(preset, top_dist, bottom_dist):
    old = ensure_matrix(preset.get("score_value"), 5, 4, 0.0)
    result = copy.deepcopy(old)
    for period in range(5):
        top_period = top_dist["by_period"][period]
        bottom_period = bottom_dist["by_period"][period]
        top_count = sum(row["count"] for row in top_period)
        bottom_count = sum(row["count"] for row in bottom_period)
        if top_count <= 0:
            continue
        top_avg = average_action_stats(sum_action_stats(top_period))
        bottom_avg = average_action_stats(sum_action_stats(bottom_period)) if bottom_count > 0 else empty_action_stats()
        partner_edge = top_avg.get("deck_partner_count", 0.0) - bottom_avg.get("deck_partner_count", 0.0)
        rainbow_edge = top_avg.get("rainbow_count", 0.0) - bottom_avg.get("rainbow_count", 0.0)
        hint_edge = top_avg.get("hint_count", 0.0) - bottom_avg.get("hint_count", 0.0)
        failure_edge = top_avg.get("failure_rate", 0.0) - bottom_avg.get("failure_rate", 0.0)
        result[period][0] = round(clamp(old[period][0] + partner_edge * 0.012 + rainbow_edge * 0.018, 0.0, 0.18), 4)
        result[period][1] = round(clamp(old[period][1] + partner_edge * 0.010 + rainbow_edge * 0.016, 0.0, 0.18), 4)
        result[period][3] = round(clamp(old[period][3] + hint_edge * 0.018, 0.0, 0.18), 4)
        # If the better runs accepted higher failure, energy was probably under-valued.
        if failure_edge < -3.0:
            result[period][2] = round(clamp(old[period][2] + 0.0004, 0.001, 0.010), 5)
        elif failure_edge > 5.0:
            result[period][2] = round(clamp(old[period][2] - 0.0003, 0.001, 0.010), 5)
        else:
            result[period][2] = round(clamp(old[period][2], 0.001, 0.010), 5)
    return result


def sum_action_stats(rows):
    total = empty_action_stats()
    for row in rows:
        for key, value in row.items():
            total[key] += value
    return total


def tune_rest_threshold(preset, samples, top_samples=None, run_mode_policy=None):
    old = as_int(preset.get("rest_threshold"), 48)
    target = old
    top_recovery_hps = [
        as_float(action.get("hp"))
        for sample in completed_samples(top_samples or [])
        for action in sample.get("support_actions") or []
        if str((action or {}).get("kind") or "") in {"rest", "recreation", "medic"}
        and as_float(action.get("hp")) > 0
    ]
    if len(top_recovery_hps) >= 4:
        target = int(
            clamp(
                round((old * 0.6) + (statistics.median(top_recovery_hps) * 0.4)),
                35,
                70,
            )
        )
    poor = [sample for sample in samples if sample.get("status") in {"error", "stopped"} or sample.get("final_turn", 0) < 72]
    if poor:
        failure_actions = []
        for sample in poor:
            failure_actions.extend(sample.get("actions") or [])
        if failure_actions:
            high_failure = [action for action in failure_actions if as_float(action.get("failure_rate")) >= 25]
            low_hp = [action for action in failure_actions if 0 < as_float(action.get("hp")) <= target]
            if len(high_failure) >= max(3, len(failure_actions) * 0.18) or len(low_hp) >= max(3, len(failure_actions) * 0.22):
                target = int(clamp(max(target, old + 3), 35, 70))
    if isinstance(run_mode_policy, dict) and top_recovery_hps:
        target = int(clamp(target + as_int(run_mode_policy.get("preserve_rest_bonus")) - 1, 35, 70))
    return target


def tune_learn_skill_threshold(preset, samples):
    old = as_int(preset.get("learn_skill_threshold"), 888)
    completed = completed_samples(samples)
    if not completed:
        return old
    sp_values = [(sample.get("final_stats") or {}).get("skill_point", 0) for sample in completed if (sample.get("final_stats") or {}).get("skill_point", 0) > 0]
    if not sp_values:
        return old
    median = statistics.median(sp_values)
    if median > 1000:
        return int(clamp(old - 80, 350, 950))
    if median > 700:
        return int(clamp(old - 40, 350, 950))
    if median < 250:
        return int(clamp(old + 40, 350, 950))
    return old


def tune_mant_config(preset, top_samples, all_samples):
    mant = copy.deepcopy(preset.get("mant_config") or {})
    completed = completed_samples(all_samples)
    if not completed:
        return mant
    # Conservative item-policy nudges only. Avoid changing item tiers from a small sample.
    stat_medians = {}
    for key in STAT_KEYS:
        values = [(sample.get("final_stats") or {}).get(key, 0) for sample in completed if (sample.get("final_stats") or {}).get(key, 0)]
        if values:
            stat_medians[key] = statistics.median(values)
    if stat_medians.get("stamina", 9999) < 650:
        mant["summer_energy_entry_threshold"] = int(clamp(as_int(mant.get("summer_energy_entry_threshold"), 80) + 3, 70, 95))
        mant["summer_energy_recovery_threshold"] = int(clamp(as_int(mant.get("summer_energy_recovery_threshold"), 80) + 3, 70, 95))
    if stat_medians.get("wit", 0) > 1000 and stat_medians.get("stamina", 9999) < 700:
        item_tiers = copy.deepcopy(mant.get("item_tiers") or {})
        if item_tiers:
            item_tiers["stamina_training_application"] = min(as_int(item_tiers.get("stamina_training_application"), 7), 6)
            item_tiers["stamina_ankle_weights"] = min(as_int(item_tiers.get("stamina_ankle_weights"), 7), 6)
            mant["item_tiers"] = item_tiers
    return mant


def avg_race_metric(samples, key):
    rows = [sample for sample in samples if sample.get("race_quality")]
    if not rows:
        return 0.0
    return sum(as_float((sample.get("race_quality") or {}).get(key)) for sample in rows) / len(rows)


def tune_optional_race_policy(preset, top_samples, all_samples):
    completed = completed_samples(all_samples)
    top_completed = completed_samples(top_samples) or top_samples
    if not completed or not top_completed:
        return {}

    result = {}
    top_g23 = avg_race_metric(top_completed, "g2_wins") + avg_race_metric(top_completed, "g3_wins")
    all_g23 = avg_race_metric(completed, "g2_wins") + avg_race_metric(completed, "g3_wins")
    top_losses = avg_race_metric(top_completed, "race_losses")
    all_losses = avg_race_metric(completed, "race_losses")
    top_optional = _avg_support_actions_per_career(top_completed, "optional_race")
    all_optional = _avg_support_actions_per_career(completed, "optional_race")
    max_training_score = as_float(preset.get("optional_race_max_training_score"), 0.34)
    min_value = as_float(preset.get("optional_race_min_value"), 0.75)
    if top_g23 > all_g23 + 0.75 and top_losses <= all_losses + 0.2:
        result["optional_race_max_training_score"] = round(clamp(max_training_score + 0.02, 0.26, 0.42), 4)
        result["optional_race_min_value"] = round(clamp(min_value - 0.03, 0.55, 1.05), 4)
    elif top_losses > all_losses + 0.35:
        result["optional_race_max_training_score"] = round(clamp(max_training_score - 0.025, 0.26, 0.42), 4)
        result["optional_race_min_value"] = round(clamp(min_value + 0.04, 0.55, 1.05), 4)

    top_epithets = avg_race_metric(top_completed, "epithet_sets_completed")
    all_epithets = avg_race_metric(completed, "epithet_sets_completed")
    epithet_bonus = as_float(preset.get("optional_race_epithet_bonus"), 0.25)
    if top_epithets > all_epithets + 0.2:
        result["optional_race_epithet_bonus"] = round(clamp(epithet_bonus + 0.03, 0.10, 0.45), 4)
    elif top_losses > all_losses + 0.35 and top_epithets <= all_epithets:
        result["optional_race_epithet_bonus"] = round(clamp(epithet_bonus - 0.02, 0.10, 0.45), 4)

    top_overlap = avg_race_metric(top_completed, "affinity_overlap_wins")
    all_overlap = avg_race_metric(completed, "affinity_overlap_wins")
    rival_bonus = as_float(preset.get("optional_race_rival_bonus"), 0.25)
    if top_overlap > all_overlap + 0.6 and top_losses <= all_losses + 0.2:
        result["optional_race_rival_bonus"] = round(clamp(rival_bonus + 0.03, 0.10, 0.45), 4)

    if top_optional >= all_optional + 0.35 and top_losses <= all_losses + 0.15:
        result["optional_race_max_training_score"] = round(
            clamp(
                max(
                    as_float(result.get("optional_race_max_training_score"), max_training_score),
                    max_training_score + 0.015,
                ),
                0.26,
                0.42,
            ),
            4,
        )
        result["optional_race_min_value"] = round(
            clamp(
                min(
                    as_float(result.get("optional_race_min_value"), min_value),
                    min_value - 0.02,
                ),
                0.55,
                1.05,
            ),
            4,
        )
    elif top_optional + 0.35 < all_optional and top_losses + 0.15 < all_losses:
        result["optional_race_max_training_score"] = round(
            clamp(
                min(
                    as_float(result.get("optional_race_max_training_score"), max_training_score),
                    max_training_score - 0.02,
                ),
                0.26,
                0.42,
            ),
            4,
        )
        result["optional_race_min_value"] = round(
            clamp(
                max(
                    as_float(result.get("optional_race_min_value"), min_value),
                    min_value + 0.03,
                ),
                0.55,
                1.05,
            ),
            4,
        )

    all_g1_losses = avg_race_metric(completed, "g1_losses")
    if all_losses > 2.0 or all_g1_losses > 0.75:
        result["optional_race_max_training_score"] = round(
            clamp(
                min(as_float(result.get("optional_race_max_training_score"), max_training_score), max_training_score - 0.03),
                0.26,
                0.42,
            ),
            4,
        )
        result["optional_race_min_value"] = round(
            clamp(
                max(as_float(result.get("optional_race_min_value"), min_value), min_value + 0.05),
                0.55,
                1.05,
            ),
            4,
        )
        result["optional_race_skip_if_stamina_low"] = True
    return result


def change_summary(old, new, keys):
    changes = {}
    for key in keys:
        if old.get(key) != new.get(key):
            changes[key] = {"old": old.get(key), "new": new.get(key)}
    return changes


def top_sample_summary(samples, limit=8):
    rows = []
    for sample in samples[:limit]:
        recency = (sample.get("learning_metadata") or {}).get("recency") or {}
        regression = (sample.get("learning_metadata") or {}).get("performance_regression") or {}
        rows.append({
            "source": sample.get("source"),
            "score": sample.get("score"),
            "status": sample.get("status"),
            "final_turn": sample.get("final_turn"),
            "rank": sample.get("rank"),
            "rank_label": sample.get("rank_label"),
            "rank_score": sample.get("rank_score"),
            "race_wins": sample.get("race_wins"),
            "race_losses": sample.get("race_losses"),
            "g1_wins": (sample.get("race_quality") or {}).get("g1_wins"),
            "g1_losses": (sample.get("race_quality") or {}).get("g1_losses"),
            "affinity_overlap_wins": (sample.get("race_quality") or {}).get("affinity_overlap_wins"),
            "global_legacy_overlap_points": (sample.get("race_quality") or {}).get("global_legacy_overlap_points"),
            "epithet_sets_completed": (sample.get("race_quality") or {}).get("epithet_sets_completed"),
            "factor_quality": sample.get("factor_quality"),
            "white_metrics": sample.get("white_metrics"),
            "skill_quality": sample.get("skill_quality"),
            "stats": sample.get("final_stats"),
            "action_count": len(sample.get("actions") or []),
            "sample_weight": round(as_float(sample.get("sample_weight"), 1.0), 4),
            "base_sample_weight": round(
                as_float(
                    sample.get("_pre_recency_sample_weight"),
                    as_float(sample.get("sample_weight"), 1.0),
                ),
                4,
            ),
            "recency_multiplier": recency.get("multiplier"),
            "recency_rank": recency.get("rank"),
            "regression_triggered": regression.get("triggered"),
            "regression_score_ratio": regression.get("score_ratio"),
            "regression_baseline_score": regression.get("baseline_score"),
            "regression_severity": regression.get("severity"),
            "regression_bonus": regression.get("effective_bonus"),
            "observed_at": recency.get("observed_at"),
            "observed_at_source": recency.get("observed_at_source"),
            "path": sample.get("path"),
        })
    return rows


def _is_manual_sample(sample):
    """Manual-source samples have `source` like 'manual_hachimi', 'manual_legacy',
    or the older 'manual_*' prefixes. Bot careers use 'bot' and parent-library
    imports use '*_parent_library'."""
    source = str((sample or {}).get("source") or "").lower()
    return source.startswith("manual")


def _is_behavior_learning_sample(sample):
    """Samples eligible to shape live behavior.

    Parent-library rows are useful for parent-quality diagnostics, but they are
    not decision traces. Letting them into top/bottom reference groups pollutes
    the behavior learner with high-score snapshots that contributed no turn
    choices."""
    sample = sample or {}
    source = str(sample.get("source") or "").strip().lower()
    if source.endswith("_parent_library"):
        return False
    return is_full_career_sample(sample)


def _stat_total_for_gate(sample):
    stats = (sample or {}).get("final_stats") or {}
    if not isinstance(stats, dict):
        return 0.0, False
    present = [key for key in STAT_KEYS if stats.get(key) is not None]
    if len(present) < 3:
        return 0.0, False
    return sum(as_float(stats.get(key), 0.0) for key in STAT_KEYS), True


def _race_quality_counts_for_gate(sample):
    sample = sample or {}
    race_quality = sample.get("race_quality") or {}
    if not isinstance(race_quality, dict):
        race_quality = {}
    race_total = as_int(
        race_quality.get("race_total"),
        as_int(sample.get("race_wins")) + as_int(sample.get("race_losses")),
    )
    race_losses = max(
        as_int(sample.get("race_losses")),
        as_int(race_quality.get("race_losses")),
    )
    g1_losses = as_int(race_quality.get("g1_losses"))
    g1_wins = as_int(race_quality.get("g1_wins"))
    return race_total, race_losses, g1_losses, g1_wins


def policy_steering_gate(sample, preset=None, require_actions=True, min_actions=None):
    """Classify whether a career is allowed to become positive ML signal.

    Bad careers are still useful as diagnostics and negative examples. They are
    not allowed to teach the bot "this is what good looks like" unless they
    clear explicit output gates: full capture, enough action data, clean race
    record, adequate in-game/internal score, and adequate final stat output.
    """
    preset = preset if isinstance(preset, dict) else {}
    sample = sample if isinstance(sample, dict) else {}
    enabled = bool(preset.get("learning_policy_objective_gate_enabled", True))
    min_actions = (
        as_int(min_actions, DEFAULT_POLICY_MIN_ACTIONS)
        if min_actions is not None
        else as_int(preset.get("learning_policy_min_actions"), DEFAULT_POLICY_MIN_ACTIONS)
    )
    min_rank_score = as_float(
        preset.get("learning_policy_min_rank_score"),
        DEFAULT_POLICY_MIN_RANK_SCORE,
    )
    min_internal_score = as_float(
        preset.get("learning_policy_min_internal_score"),
        DEFAULT_POLICY_MIN_INTERNAL_SCORE,
    )
    min_stat_total = as_float(
        preset.get("learning_policy_min_stat_total"),
        DEFAULT_POLICY_MIN_STAT_TOTAL,
    )
    max_race_losses = as_int(preset.get("learning_policy_max_race_losses"), 0)
    max_g1_losses = as_int(preset.get("learning_policy_max_g1_losses"), 0)
    clean_record_min_races = as_int(
        preset.get("learning_policy_min_race_total_for_clean_record"),
        DEFAULT_POLICY_MIN_RACE_TOTAL_FOR_CLEAN_RECORD,
    )
    reasons = []
    action_count = len(sample.get("actions") or [])
    race_total, race_losses, g1_losses, g1_wins = _race_quality_counts_for_gate(sample)
    rank_score = as_float(sample.get("rank_score"), 0.0)
    internal_score = as_float(sample.get("score"), 0.0)
    stat_total, has_stat_total = _stat_total_for_gate(sample)

    if not enabled:
        return {
            "schema": "sweepy_policy_steering_gate_v1",
            "enabled": False,
            "steering_allowed": True,
            "diagnostic_only": False,
            "reasons": [],
            "action_count": action_count,
            "race_total": race_total,
            "race_losses": race_losses,
            "g1_losses": g1_losses,
            "g1_wins": g1_wins,
            "rank_score": round(rank_score, 3) if rank_score > 0 else None,
            "internal_score": round(internal_score, 3),
            "stat_total": round(stat_total, 3) if has_stat_total else None,
        }

    if not is_full_career_sample(sample, require_turn_data=True):
        reasons.append("not_full_turn_capture")
    if require_actions and action_count < min_actions:
        reasons.append("not_enough_actions")
    if g1_losses > max_g1_losses:
        reasons.append("g1_losses")
    if race_total >= clean_record_min_races and race_losses > max_race_losses:
        reasons.append("race_losses")
    if rank_score > 0:
        if min_rank_score > 0 and rank_score < min_rank_score:
            reasons.append("rank_score_below_floor")
    elif min_internal_score > 0 and internal_score < min_internal_score:
        reasons.append("internal_score_below_floor")
    if has_stat_total and min_stat_total > 0 and stat_total < min_stat_total:
        reasons.append("stat_total_below_floor")

    allowed = not reasons
    return {
        "schema": "sweepy_policy_steering_gate_v1",
        "enabled": True,
        "steering_allowed": allowed,
        "diagnostic_only": not allowed,
        "reasons": reasons,
        "action_count": action_count,
        "min_actions": min_actions if require_actions else 0,
        "race_total": race_total,
        "race_losses": race_losses,
        "g1_losses": g1_losses,
        "g1_wins": g1_wins,
        "max_race_losses": max_race_losses,
        "max_g1_losses": max_g1_losses,
        "clean_record_min_races": clean_record_min_races,
        "rank_score": round(rank_score, 3) if rank_score > 0 else None,
        "min_rank_score": round(min_rank_score, 3),
        "internal_score": round(internal_score, 3),
        "min_internal_score": round(min_internal_score, 3),
        "stat_total": round(stat_total, 3) if has_stat_total else None,
        "min_stat_total": round(min_stat_total, 3) if has_stat_total else None,
    }


def annotate_policy_steering_gates(samples, preset=None, require_actions=True, min_actions=None):
    summary = {
        "schema": "sweepy_policy_steering_gate_summary_v1",
        "enabled": bool((preset or {}).get("learning_policy_objective_gate_enabled", True)),
        "sample_count": len(samples or []),
        "positive_sample_count": 0,
        "diagnostic_only_count": 0,
        "reasons": {},
    }
    for sample in samples or []:
        if not isinstance(sample, dict):
            continue
        gate = policy_steering_gate(
            sample,
            preset=preset,
            require_actions=require_actions,
            min_actions=min_actions,
        )
        meta = sample.get("learning_metadata") or {}
        meta["policy_steering_gate"] = gate
        sample["learning_metadata"] = meta
        if gate.get("steering_allowed"):
            summary["positive_sample_count"] += 1
        else:
            summary["diagnostic_only_count"] += 1
            for reason in gate.get("reasons") or []:
                summary["reasons"][reason] = summary["reasons"].get(reason, 0) + 1
    return summary


def _sample_learning_weight(sample):
    return as_float(sample.get("sample_weight"), 1.0) * clamp(as_float(sample.get("score")) / 9000.0, 0.55, 1.85)


def _friendship_progress_snapshot(sample, target_turn=35):
    best = None
    for action in sorted(sample.get("actions") or [], key=lambda row: as_int((row or {}).get("turn"))):
        turn = as_int(action.get("turn"))
        if turn <= 0 or turn > target_turn:
            continue
        understanding = action.get("decision_understanding") or {}
        signals = understanding.get("signals") if isinstance(understanding, dict) else {}
        if not isinstance(signals, dict):
            continue
        current = signals.get("current_rainbow_unlocked_count")
        target = signals.get("target_rainbow_unlocked_count")
        if current is None or target is None:
            continue
        row = {
            "turn": turn,
            "current_unlocked": as_int(current),
            "target_unlocked": as_int(target),
        }
        if best is None or turn >= best.get("turn", 0):
            best = row
    return best


def first_summer_friendship_diagnostic(samples, top_samples=None, bottom_samples=None, target_turn=35):
    def _summarize(group):
        rows = []
        for sample in group or []:
            progress = _friendship_progress_snapshot(sample, target_turn=target_turn)
            if not progress:
                continue
            current = as_int(progress.get("current_unlocked"))
            target = as_int(progress.get("target_unlocked"))
            rows.append({
                "source": sample.get("source"),
                "current": current,
                "target": target,
                "gap": max(0, target - current),
                "hit": current >= target and target > 0,
            })
        if not rows:
            return {
                "sample_count": 0,
                "samples_with_signal": 0,
                "hit_rate": None,
                "average_unlocked": None,
                "average_gap": None,
            }
        sample_count = len(rows)
        bot_rows = [row for row in rows if str(row.get("source") or "").lower() == "bot"]
        manual_rows = [row for row in rows if _is_manual_sample({"source": row.get("source")})]
        def _rate(bucket):
            if not bucket:
                return None
            return round(sum(1 for row in bucket if row.get("hit")) / len(bucket), 4)
        return {
            "sample_count": sample_count,
            "samples_with_signal": sample_count,
            "hit_rate": round(sum(1 for row in rows if row.get("hit")) / sample_count, 4),
            "average_unlocked": round(sum(row.get("current", 0) for row in rows) / sample_count, 4),
            "average_gap": round(sum(row.get("gap", 0) for row in rows) / sample_count, 4),
            "bot_hit_rate": _rate(bot_rows),
            "manual_hit_rate": _rate(manual_rows),
        }

    return {
        "target_turn": target_turn,
        "overall": _summarize(samples),
        "top": _summarize(top_samples),
        "bottom": _summarize(bottom_samples),
    }


def select_reference_groups(samples, score_floor=None, score_floors_by_deck=None, prefer_stratified=True, preset=None):
    legacy_top, legacy_bottom = split_reference_groups(
        samples,
        score_floor=score_floor,
        score_floors_by_deck=score_floors_by_deck,
        preset=preset,
    )
    stratified_stats = {}
    stratified_top = []
    stratified_bottom = []
    if prefer_stratified:
        try:
            raw_top, raw_bottom, stratified_stats = stratified_top_bottom_split(samples)
            stratified_top = []
            for sample in raw_top:
                if _sample_clears_top_reference_floor(sample, score_floor=score_floor, score_floors_by_deck=score_floors_by_deck, preset=preset):
                    stratified_top.append(sample)
            stratified_bottom = list(raw_bottom)
        except Exception:
            stratified_top = []
            stratified_bottom = []
            stratified_stats = {}
    use_stratified = (
        prefer_stratified
        and len(stratified_top) >= max(1, min(len(legacy_top), 2))
        and len(stratified_bottom) >= max(1, min(len(legacy_bottom), 2))
    )
    return (
        stratified_top if use_stratified else legacy_top,
        stratified_bottom if use_stratified else legacy_bottom,
        stratified_stats,
        "stratified" if use_stratified else "legacy",
    )


def _training_total_gain(row):
    if not isinstance(row, dict):
        return 0.0
    weighted = as_float(row.get("weighted_gain") if row.get("weighted_gain") is not None else row.get("weighted_total_gain"))
    if weighted > 0:
        return weighted
    gains = row.get("stat_gain") or {}
    if not isinstance(gains, dict):
        return 0.0
    total = 0.0
    for key, value in gains.items():
        if str(key) == "hp":
            continue
        factor = 0.5 if str(key) == "skill_point" else 1.0
        total += max(0.0, as_float(value)) * factor
    return total


def _manual_actual_training_value(row):
    if not isinstance(row, dict):
        return 0.0
    # Manual captures often choose a lower immediate-gain tile to unlock
    # friendship or preserve a future high-value tile. Fold a small amount of
    # observed follow-through into the correction signal so these choices are
    # not discarded as "bad" just because their same-turn stat gain is lower.
    return (
        _training_total_gain(row)
        + as_float(row.get("future_total_gain")) * 0.20
        + as_float(row.get("future_partner_bond_gain")) * 0.35
        + as_float(row.get("future_rainbow_unlocks")) * 12.0
        + as_float(row.get("future_best_training_gain_delta")) * 0.15
    )


def _snapshot_training_by_command(turn, command_id):
    snapshot = _snapshot_for_turn(turn)
    if not isinstance(snapshot, dict):
        return None
    for row in snapshot.get("trainings") or []:
        if as_int(row.get("command_id")) == as_int(command_id):
            return row
    return None


def _command_id_from_bot_recommendation(recommendation):
    if not isinstance(recommendation, dict):
        return 0
    for key in (
        "command_id",
        "recommended_command_id",
        "selected_command_id",
        "best_command_id",
        "training_command_id",
    ):
        value = as_int(recommendation.get(key))
        if value in TRAINING_COMMANDS:
            return value
    command = recommendation.get("command")
    if isinstance(command, dict):
        value = as_int(command.get("command_id") or command.get("id"))
        if value in TRAINING_COMMANDS:
            return value
    return 0


def _bot_reference_training_row(turn):
    snapshot = _snapshot_for_turn(turn)
    if not isinstance(snapshot, dict):
        return None
    command_id = _command_id_from_bot_recommendation((turn or {}).get("bot_recommendation"))
    if command_id:
        matched = _snapshot_training_by_command(turn, command_id)
        if matched:
            return matched
    return _best_training_row(turn)


def _selected_training_row(turn):
    action = selected_training_action(turn)
    if action:
        return action
    selected = (turn or {}).get("selected_training")
    if isinstance(selected, dict):
        action = training_feature_from_option(selected, (turn or {}).get("stats") or {})
        if action:
            action["turn"] = as_int((turn or {}).get("turn"))
            action["period"] = period_index(action["turn"])
            action["extra_phase"] = extra_phase_index(action["turn"])
            snapshot = _snapshot_for_turn(turn)
            if snapshot:
                action["training_snapshot"] = snapshot
            return action
    return None


def _synthesized_deviation_row(path, sample, ordered_turns, idx, turn):
    if not isinstance(turn, dict):
        return None
    human = _selected_training_row(turn)
    bot = _bot_reference_training_row(turn)
    if not human or not bot:
        return None
    human.update(_long_horizon_metrics(
        ordered_turns,
        idx,
        partner_ids=human.get("selected_partner_ids") or [],
    ))
    snapshot = _snapshot_for_turn(turn)
    scores = sorted(
        (_training_total_gain(row) for row in (snapshot or {}).get("trainings") or []),
        reverse=True,
    )
    bot_score = _training_total_gain(bot)
    human_score = _training_total_gain(human)
    second_best = scores[1] if len(scores) > 1 else 0.0
    return {
        "career_path": str(path),
        "career_score": as_float(sample.get("score")),
        "turn": as_int(turn.get("turn")),
        "agreed": as_int(bot.get("command_id")) == as_int(human.get("command_id")),
        "bot_training_idx": as_int(bot.get("idx"), -1),
        "human_training_idx": as_int(human.get("idx"), -1),
        "bot_score": bot_score,
        "bot_second_best_score": second_best,
        "bot_score_margin": max(0.0, bot_score - second_best),
        "human_choice_bot_score": human_score,
        "bot_predicted_total_gain": bot_score,
        "human_predicted_total_gain": human_score,
        "actual_total_gain": _manual_actual_training_value(human),
        "bot_parity_at_capture": 0.0,
        "source": "manual_hachimi_synthetic",
    }


def load_deviation_signals(runtime_root, recent=None, min_career_score=15000):
    rows = []
    manual_dir = Path(runtime_root) / "manual_career_logs"
    if not manual_dir.exists():
        return rows
    files = sorted(manual_dir.glob("career_log_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for latest_name in ("latest_career_log.json", "latest_manual_career_log.json"):
        latest = manual_dir / latest_name
        if latest.exists():
            files.insert(0, latest)
    seen = set()
    unique = []
    for path in files:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(path)
    if recent:
        unique = unique[:recent]
    for path in unique:
        data = read_json(path)
        if not isinstance(data, dict) or not isinstance(data.get("turns"), list):
            continue
        sample = normalize_bot_like_log(path, data, "manual_legacy")
        if not sample or as_float(sample.get("score")) < min_career_score:
            continue
        ordered_turns = sorted(data.get("turns") or [], key=lambda row: as_int((row or {}).get("turn")))
        for idx, turn in enumerate(ordered_turns):
            if not isinstance(turn, dict):
                continue
            dev = turn.get("deviation") or {}
            if isinstance(dev, dict) and dev:
                actual = dev.get("actual_stat_gain") or {}
                bot_pred = dev.get("bot_predicted_stat_gain") or {}
                human_pred = dev.get("human_predicted_stat_gain") or {}
                rows.append({
                    "career_path": str(path),
                    "career_score": as_float(sample.get("score")),
                    "turn": as_int(turn.get("turn")),
                    "agreed": bool(dev.get("agreed")),
                    "bot_training_idx": as_int(dev.get("bot_training_idx"), -1),
                    "human_training_idx": as_int(dev.get("human_training_idx"), -1),
                    "bot_score": as_float(dev.get("bot_score")),
                    "bot_second_best_score": as_float(dev.get("bot_second_best_score")),
                    "bot_score_margin": as_float(dev.get("bot_score_margin")),
                    "human_choice_bot_score": as_float(dev.get("human_choice_bot_score")),
                    "bot_predicted_total_gain": sum(max(0.0, as_float(value)) for key, value in bot_pred.items() if str(key) != "hp"),
                    "human_predicted_total_gain": sum(max(0.0, as_float(value)) for key, value in human_pred.items() if str(key) != "hp"),
                    "actual_total_gain": sum(max(0.0, as_float(value)) for key, value in actual.items() if str(key) != "hp"),
                    "bot_parity_at_capture": as_float(dev.get("bot_parity_at_capture")),
                })
                continue
            synthesized = _synthesized_deviation_row(path, sample, ordered_turns, idx, turn)
            if synthesized:
                rows.append(synthesized)
    return rows


def _deviation_outperformed_prediction(row):
    actual = as_float((row or {}).get("actual_total_gain"))
    predicted = as_float((row or {}).get("bot_predicted_total_gain"))
    human_predicted = as_float((row or {}).get("human_predicted_total_gain"))
    margin = as_float((row or {}).get("bot_score_margin"))
    if actual > 0 and predicted > 0:
        return actual >= predicted * 1.08
    if human_predicted > 0 and predicted > 0:
        return human_predicted >= predicted * 0.98 and margin <= 6.0
    return margin <= 3.0


def tune_deviation_bias(learned, deviation_rows, min_career_score=15000):
    summary = {
        "total_rows": len(deviation_rows or []),
        "disagreed_rows": 0,
        "used_rows": 0,
        "fade_multiplier": 0.0,
        "min_career_score": as_float(min_career_score, 15000),
        "bot_parity": 0.0,
        "avg_override_advantage": 0.0,
        "outperformed_rows": 0,
    }
    if not deviation_rows:
        return learned, summary

    parity_values = [
        clamp(as_float(row.get("bot_parity_at_capture")), 0.0, 1.0)
        for row in deviation_rows
        if as_float(row.get("bot_parity_at_capture")) > 0
    ]
    bot_parity = sum(parity_values) / len(parity_values) if parity_values else 0.0
    summary["bot_parity"] = round(bot_parity, 4)
    fade_multiplier = max(0.0, 1.0 - bot_parity)
    if bot_parity >= 0.85:
        fade_multiplier *= 0.15
    elif bot_parity >= 0.7:
        fade_multiplier *= 0.45
    summary["fade_multiplier"] = round(fade_multiplier, 4)

    by_human = Counter()
    by_bot = Counter()
    advantage_values = []
    for row in deviation_rows:
        if bool(row.get("agreed")):
            continue
        summary["disagreed_rows"] += 1
        if not _deviation_outperformed_prediction(row):
            continue
        summary["outperformed_rows"] += 1
        period = period_index(as_int(row.get("turn")))
        human_idx = as_int(row.get("human_training_idx"), -1)
        bot_idx = as_int(row.get("bot_training_idx"), -1)
        if human_idx < 0 or bot_idx < 0:
            continue
        predicted = max(1.0, as_float(row.get("bot_predicted_total_gain")))
        human_predicted = as_float(row.get("human_predicted_total_gain"))
        actual = as_float(row.get("actual_total_gain"))
        advantage = max(human_predicted - predicted, actual - predicted, 0.0) / predicted
        advantage_values.append(advantage)
        evidence = clamp(as_float(row.get("career_score")) / 18000.0, 0.75, 1.4)
        confidence_penalty = clamp(1.0 - (as_float(row.get("bot_score_margin")) / 30.0), 0.35, 1.0)
        weight = evidence * confidence_penalty * max(0.10, fade_multiplier or 1.0)
        if len(deviation_rows) < 5:
            weight *= 0.55
        if advantage < 0.04:
            weight *= 0.65
        by_human[(period, human_idx)] += weight
        by_bot[(period, bot_idx)] += weight
        summary["used_rows"] += 1

    if advantage_values:
        summary["avg_override_advantage"] = round(sum(advantage_values) / len(advantage_values), 4)
    if summary["used_rows"] < 3:
        fade_multiplier = min(fade_multiplier, 0.35)
    if summary["avg_override_advantage"] and summary["avg_override_advantage"] < 0.04:
        fade_multiplier *= 0.5
    summary["fade_multiplier"] = round(fade_multiplier, 4)

    if not by_human and not by_bot:
        return learned, summary

    extra = ensure_matrix(learned.get("extra_weight"), 4, 5)
    for (period, idx), weight in by_human.items():
        if period >= len(extra) or idx >= len(extra[period]):
            continue
        bias = clamp(weight * 0.012, 0.0, 0.04)
        extra[period][idx] = round(clamp(extra[period][idx] + bias, -0.12, 0.25), 4)
    for (period, idx), weight in by_bot.items():
        if period >= len(extra) or idx >= len(extra[period]):
            continue
        if by_human.get((period, idx), 0.0) > 0:
            continue
        penalty = clamp(weight * 0.006, 0.0, 0.02)
        extra[period][idx] = round(clamp(extra[period][idx] - penalty, -0.12, 0.25), 4)
    learned["extra_weight"] = extra
    return learned, summary


def learn_item_policy(samples):
    decision_samples = [sample for sample in samples if sample.get("item_decisions")]
    if not decision_samples:
        return {}, {"decision_samples": 0, "buy_rows": 0}
    baseline_weight = sum(_sample_learning_weight(sample) for sample in decision_samples) or 1.0
    baseline_score = sum(as_float(sample.get("score")) * _sample_learning_weight(sample) for sample in decision_samples) / baseline_weight
    stats = {}
    total_buy_rows = 0
    for sample in decision_samples:
        decisions = sorted(sample.get("item_decisions") or [], key=lambda row: (as_int(row.get("turn")), row.get("kind") or ""))
        if not decisions:
            continue
        weight = _sample_learning_weight(sample)
        race_turns = sorted(
            as_int(row.get("turn"))
            for row in sample.get("race_results") or []
            if isinstance(row, dict) and as_int(row.get("turn")) > 0
        )
        use_rows = {}
        for row in decisions:
            if row.get("kind") != "use" or not row.get("name"):
                continue
            use_rows.setdefault(row["name"], []).append(as_int(row.get("turn")))
        use_index = {name: 0 for name in use_rows}
        for row in decisions:
            if row.get("kind") != "buy" or not row.get("name"):
                continue
            total_buy_rows += 1
            name = row["name"]
            phase = row.get("phase") or item_phase_label(row.get("turn"))
            key = (name, phase)
            bucket = stats.setdefault(key, {
                "count": 0,
                "used_count": 0,
                "unused_count": 0,
                "gap_sum": 0.0,
                "score_weight_sum": 0.0,
                "score_sum": 0.0,
                "fast_used_count": 0,
                "medium_used_count": 0,
                "race_window_use_count": 0,
            })
            bucket["count"] += 1
            bucket["score_weight_sum"] += weight
            bucket["score_sum"] += as_float(sample.get("score")) * weight
            turns_for_name = use_rows.get(name) or []
            idx = use_index.get(name, 0)
            matched_turn = None
            while idx < len(turns_for_name):
                candidate_turn = as_int(turns_for_name[idx])
                idx += 1
                if candidate_turn >= as_int(row.get("turn")):
                    matched_turn = candidate_turn
                    break
            use_index[name] = idx
            if matched_turn is None:
                bucket["unused_count"] += 1
                continue
            bucket["used_count"] += 1
            gap = max(0, matched_turn - as_int(row.get("turn")))
            bucket["gap_sum"] += gap
            if gap <= 3:
                bucket["fast_used_count"] += 1
            if gap <= 7:
                bucket["medium_used_count"] += 1
            if any(0 <= race_turn - matched_turn <= 1 for race_turn in race_turns):
                bucket["race_window_use_count"] += 1

    items = {}
    for (name, phase), bucket in stats.items():
        count = int(bucket.get("count") or 0)
        if count <= 0:
            continue
        used = int(bucket.get("used_count") or 0)
        unused = int(bucket.get("unused_count") or 0)
        avg_gap = round(bucket["gap_sum"] / used, 4) if used else None
        avg_score = (bucket["score_sum"] / bucket["score_weight_sum"]) if bucket["score_weight_sum"] else 0.0
        score_ratio = round(avg_score / max(1.0, baseline_score), 4)
        unused_rate = round(unused / count, 4)
        fast_use_rate = round((bucket.get("fast_used_count") or 0) / max(1, used), 4) if used else 0.0
        medium_use_rate = round((bucket.get("medium_used_count") or 0) / max(1, used), 4) if used else 0.0
        race_window_use_rate = round((bucket.get("race_window_use_count") or 0) / max(1, used), 4) if used else 0.0
        tier_adjustment = 0
        if count >= 3:
            if unused_rate >= 0.75:
                tier_adjustment += 2
            elif unused_rate >= 0.5:
                tier_adjustment += 1
            if avg_gap is not None and avg_gap >= 10:
                tier_adjustment += 1
            if score_ratio >= 1.05 and unused_rate <= 0.25 and (avg_gap is None or avg_gap <= 4):
                tier_adjustment -= 1
        item_bucket = items.setdefault(name, {
            "phase_adjustments": {},
            "timing_adjustments": {},
            "phase_stats": {},
        })
        item_bucket["phase_adjustments"][phase] = int(clamp(tier_adjustment, -1, 3))
        timing_adjustment = 0
        if count >= 3 and used > 0:
            if fast_use_rate >= 0.6 and score_ratio >= 1.02:
                timing_adjustment += 1
            if race_window_use_rate >= 0.4 and score_ratio >= 1.0:
                timing_adjustment += 1
            if avg_gap is not None and avg_gap >= 8:
                timing_adjustment -= 1
        item_bucket["timing_adjustments"][phase] = int(clamp(timing_adjustment, -1, 2))
        item_bucket["phase_stats"][phase] = {
            "count": count,
            "used_count": used,
            "unused_count": unused,
            "unused_rate": unused_rate,
            "avg_use_gap": avg_gap,
            "fast_use_rate": fast_use_rate,
            "medium_use_rate": medium_use_rate,
            "race_window_use_rate": race_window_use_rate,
            "avg_score": round(avg_score, 3),
            "score_ratio": score_ratio,
        }
    policy = {
        "schema": "sweepy_item_policy_v2",
        "baseline_score": round(baseline_score, 3),
        "decision_samples": len(decision_samples),
        "buy_rows": total_buy_rows,
        "items": items,
    } if items else {}
    summary = {
        "decision_samples": len(decision_samples),
        "buy_rows": total_buy_rows,
        "learned_items": len(items),
        "baseline_score": round(baseline_score, 3),
    }
    return policy, summary


def learn_preset(
    base_dir,
    preset_name,
    output_name=None,
    runtime_paths=None,
    recent=None,
    min_samples=3,
    manual_only=False,
    source_preset_override=None,
):
    store = PresetStore(base_dir)
    if isinstance(source_preset_override, dict) and source_preset_override:
        preset = normalize_preset(copy.deepcopy(source_preset_override))
        if not preset.get("name"):
            preset["name"] = str(preset_name or "").strip()
    else:
        preset = store.read_one(preset_name)
    if not preset:
        raise ValueError(f"Preset not found: {preset_name}")
    parent_goals = normalize_parent_goals(preset.get("desired_parent_sparks"))
    allowed_chara_ids = preset.get("learning_allowed_chara_ids") or None
    resolved_runtime_roots = [str(root) for root in runtime_roots(base_dir, runtime_paths)]
    primary_root = primary_runtime_root(base_dir, runtime_paths)
    samples = collect_samples(
        base_dir,
        runtime_paths=runtime_paths,
        recent=recent,
        parent_goals=parent_goals,
        allowed_chara_ids=allowed_chara_ids,
    )
    if manual_only:
        # When the caller wants tuning to learn ONLY from deliberate manual
        # play (e.g. you just recorded 10 careers and want them to dominate),
        # filter out bot careers and parent-library imports entirely. Without
        # this, a backlog of mediocre bot careers can drown out a small batch
        # of high-quality manual signal even with the 1.45× weight bias.
        samples = [s for s in samples if _is_manual_sample(s)]
    usable = [sample for sample in samples if is_full_career_sample(sample)]
    if len(usable) < min_samples:
        raise ValueError(f"Need at least {min_samples} usable career samples, found {len(usable)}")
    runtime_pooling = resolve_runtime_learning_pools(
        usable,
        primary_root,
        instance_local=_instance_local_learning_scope_enabled(),
        min_local_samples=min_samples,
    )
    behavior_usable = [
        sample for sample in (runtime_pooling.get("behavior_samples") or usable)
        if _is_behavior_learning_sample(sample)
    ]
    if len(behavior_usable) < min_samples:
        shared_behavior = [sample for sample in usable if _is_behavior_learning_sample(sample)]
        if len(shared_behavior) >= min_samples:
            behavior_usable = shared_behavior
    behavior_pool_sample_count_before_context = len(behavior_usable)
    context_adaptation_result = select_context_adaptive_samples(behavior_usable, preset=preset)
    selected_context_samples = context_adaptation_result.get("samples")
    if selected_context_samples is None:
        selected_context_samples = behavior_usable
    context_adaptation = {
        key: value for key, value in context_adaptation_result.items()
        if key != "samples"
    }
    if len(selected_context_samples) >= min_samples:
        behavior_usable = selected_context_samples
    else:
        context_adaptation = dict(context_adaptation)
        if bool(preset.get("learning_context_global_fallback_enabled", False)):
            context_adaptation["mode"] = "global_fallback_min_samples"
            context_adaptation["selected_count"] = len(behavior_usable)
        else:
            behavior_usable = selected_context_samples
            context_adaptation["mode"] = "context_insufficient_no_global"
            context_adaptation["selected_count"] = len(behavior_usable)
    policy_gate_summary = annotate_policy_steering_gates(
        behavior_usable,
        preset=preset,
        require_actions=True,
        min_actions=as_int(preset.get("learning_policy_min_actions"), DEFAULT_POLICY_MIN_ACTIONS),
    )
    recency_config = auto_learning_recency_config(preset)
    recency_summary = apply_recency_weights(behavior_usable, recency_config=recency_config)
    white_rank_diagnostic = white_spark_rank_diagnostic(samples)
    signature = sample_signature(
        behavior_usable,
        parent_goals=parent_goals,
        recency_config=recency_config,
        active_context=context_adaptation.get("anchor") or {},
    )
    previous_metadata = preset.get("learning_metadata") or {}
    reference_rules = learning_references().get("parent_knowledge") or {}
    score_floor = as_float(preset.get("learning_top_score_floor"), DEFAULT_TOP_SCORE_FLOOR)
    # Deck-aware floors: each deck bucket gets its own bar so low-deck
    # accounts (SR/R heavy) can still produce top samples relative to
    # what their deck can actually achieve. Override the defaults via
    # `learning_top_score_floors_by_deck` on the preset.
    preset_floors_by_deck = preset.get("learning_top_score_floors_by_deck")
    if isinstance(preset_floors_by_deck, dict) and preset_floors_by_deck:
        score_floors_by_deck = {}
        for k, v in preset_floors_by_deck.items():
            try:
                score_floors_by_deck[int(k)] = float(v)
            except (TypeError, ValueError):
                continue
    else:
        score_floors_by_deck = dict(DECK_AWARE_TOP_SCORE_FLOORS)
    empirical_score_floors, empirical_score_floor_diagnostic = compute_empirical_score_floors(samples)
    if not (isinstance(preset_floors_by_deck, dict) and preset_floors_by_deck):
        for bucket, floor in empirical_score_floors.items():
            score_floors_by_deck[int(bucket)] = max(
                float(score_floors_by_deck.get(int(bucket), DEFAULT_TOP_SCORE_FLOOR)),
                float(floor),
            )
    # Adaptive fallback: if the configured floors are unreachable for this
    # account's bot careers, lower the bar to the account's own best
    # quartile so the loop can learn from its best work instead of
    # skipping forever. Disable via learning_adaptive_score_floor=false.
    score_floor, score_floors_by_deck, score_floor_adaptation = adapt_score_floors_to_account(
        behavior_usable,
        score_floor,
        score_floors_by_deck,
        enabled=bool(preset.get("learning_adaptive_score_floor", True)),
    )
    if previous_metadata.get("sample_signature") == signature and previous_metadata.get("objective") == LEARNING_OBJECTIVE_VERSION:
        learned = normalize_preset(copy.deepcopy(preset))
        if reference_rules:
            learned["parent_farming_rules"] = reference_rules
        top_preview = behavior_usable[:max(1, math.ceil(len(behavior_usable) * 0.25))]
        top_preview = [
            sample for sample in top_preview
            if ((sample.get("learning_metadata") or {}).get("policy_steering_gate") or {}).get("steering_allowed")
        ] or top_preview[:1]
        friendship_diag = first_summer_friendship_diagnostic(behavior_usable, top_samples=top_preview, bottom_samples=None)
        report = {
            "schema": "sweepy_learning_report_v1",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_preset": preset.get("name"),
            "learned_preset": learned.get("name"),
            "sample_count": len(samples),
            "usable_sample_count": len(usable),
            "behavior_usable_sample_count": len(behavior_usable),
            "local_usable_sample_count": runtime_pooling.get("local_sample_count", 0),
            "manual_behavior_sample_count": runtime_pooling.get("manual_behavior_sample_count", 0),
            "behavior_pool_sample_count": runtime_pooling.get("behavior_sample_count", len(behavior_usable)),
            "behavior_pool_sample_count_before_context": behavior_pool_sample_count_before_context,
            "context_adaptation": context_adaptation,
            "learning_pool_mode": runtime_pooling.get("mode"),
            "source_counts": dict(Counter(sample.get("source") for sample in usable)),
            "top_samples": [],
            "bottom_samples": [],
            "changes": {},
            "warnings": learning_warnings(behavior_usable, top_preview),
            "skipped": "sample_set_unchanged",
            "sample_signature": signature,
            "objective": LEARNING_OBJECTIVE_VERSION,
            "desired_parent_sparks": parent_goals,
            "runtime_roots_used": resolved_runtime_roots,
            "primary_runtime_root": _normalized_runtime_root(primary_root),
            "parent_farming_rules": learned.get("parent_farming_rules") or reference_rules,
            "white_spark_rank_diagnostic": white_rank_diagnostic,
            "first_summer_friendship_diagnostic": friendship_diag,
            "recency_weighting": recency_summary,
            "policy_steering_gate": policy_gate_summary,
            "empirical_score_floors": empirical_score_floor_diagnostic,
        }
        return learned, report
    prefer_stratified = bool(preset.get("learning_use_stratified_reference_groups", True))
    top, bottom, sample_stratification, reference_group_strategy = select_reference_groups(
        behavior_usable,
        score_floor=score_floor,
        score_floors_by_deck=score_floors_by_deck,
        prefer_stratified=prefer_stratified,
        preset=preset,
    )

    # Outcome distribution + intent-weight summary across the whole corpus.
    outcome_distribution = {}
    intent_weight_by_source = {}
    for _sample in behavior_usable:
        meta = _sample.get("learning_metadata") or {}
        overall = (meta.get("outcome_assessment") or {}).get("overall", "unknown")
        outcome_distribution[overall] = outcome_distribution.get(overall, 0) + 1
        src = _sample.get("source") or "unknown"
        bucket = intent_weight_by_source.setdefault(src, {"count": 0, "weight_sum": 0.0})
        bucket["count"] += 1
        bucket["weight_sum"] += as_float(_sample.get("sample_weight"), 1.0)
    intent_weight_summary = {
        src: {
            "count": data["count"],
            "average_weight": round(data["weight_sum"] / data["count"], 4) if data["count"] else None,
        }
        for src, data in intent_weight_by_source.items()
    }

    # Even when we're going to skip fitting, compute the per-decision quality
    # summary against ALL usable samples so the report still surfaces the
    # signal. Tells the user "the per-decision pipeline is alive, here's the
    # average quality across your corpus" even on skipped runs.
    skipped_quality_preview = weighted_action_distribution(usable)
    friendship_diag = first_summer_friendship_diagnostic(behavior_usable, top_samples=top, bottom_samples=bottom)
    friendship_warnings = []
    overall_friendship_hit_rate = (friendship_diag.get("overall") or {}).get("hit_rate")
    if overall_friendship_hit_rate is not None and overall_friendship_hit_rate < 0.5:
        friendship_warnings.append(
            "First-summer friendship setup is weak in the current corpus; many runs are reaching classic below the 4-unlocked-support floor."
        )

    # If no sample passes the absolute score floor, refuse to fit a new model.
    # The previously-applied model stays in place — better to keep last good
    # weights than to train on mediocre echoes that will degrade decisions.
    if not top:
        learned = normalize_preset(copy.deepcopy(preset))
        if reference_rules:
            learned["parent_farming_rules"] = reference_rules
        skipped_report = {
            "schema": "sweepy_learning_report_v1",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "source_preset": preset.get("name"),
            "learned_preset": learned.get("name"),
            "sample_count": len(samples),
            "usable_sample_count": len(usable),
            "behavior_usable_sample_count": len(behavior_usable),
            "behavior_pool_sample_count_before_context": behavior_pool_sample_count_before_context,
            "context_adaptation": context_adaptation,
            "source_counts": dict(Counter(sample.get("source") for sample in usable)),
            "sample_signature": signature,
            "objective": LEARNING_OBJECTIVE_VERSION,
            "desired_parent_sparks": parent_goals,
            "runtime_roots_used": resolved_runtime_roots,
            "parent_farming_rules": learned.get("parent_farming_rules") or reference_rules,
            "white_spark_rank_diagnostic": white_rank_diagnostic,
            "first_summer_friendship_diagnostic": friendship_diag,
            "top_samples": [],
            "bottom_samples": top_sample_summary(list(reversed(bottom))) if bottom else [],
            "changes": {},
            "skipped": "no_top_samples_above_score_floor",
            "score_floor": score_floor,
            "score_floor_adaptation": score_floor_adaptation,
            "score_floors_by_deck": score_floors_by_deck,
            "empirical_score_floors": empirical_score_floor_diagnostic,
            "best_score": max((as_float(s.get("score")) for s in usable), default=0),
            "warnings": [
                f"No samples scored at or above their deck-aware floor "
                f"(SSR={score_floors_by_deck.get(3, score_floor):.0f}, "
                f"mixed={score_floors_by_deck.get(2, score_floor):.0f}, "
                f"SR={score_floors_by_deck.get(1, score_floor):.0f}, "
                f"R={score_floors_by_deck.get(0, score_floor):.0f}). "
                "Skipping model fit so the previously-applied preset isn't overwritten with mediocre patterns. "
                "Run higher-quality careers (or add a manual sample) to unlock learning.",
            ] + learning_warnings(usable, []) + friendship_warnings,
            "decision_quality_summary": {
                "per_decision_enabled": True,
                "skipped": True,
                "corpus_average_quality": skipped_quality_preview.get("average_quality"),
                "corpus_average_followthrough": skipped_quality_preview.get("average_followthrough"),
                "corpus_action_count": skipped_quality_preview.get("action_count"),
            },
            "recency_weighting": recency_summary,
            "policy_steering_gate": policy_gate_summary,
            "reference_group_strategy": reference_group_strategy,
            "sample_stratification": sample_stratification,
            "outcome_distribution": outcome_distribution,
            "intent_weight_summary": intent_weight_summary,
        }
        return learned, skipped_report

    # Per-decision learning: weighted_action_distribution weights each action
    # by its own decision quality, not just its career's overall score. This
    # is the big shift — instead of each career contributing equally per
    # action, high-quality decisions within a career carry more weight, and
    # low-quality decisions carry less. The fallback to the unweighted
    # distribution kicks in only if the preset explicitly disables it.
    use_per_decision = bool(preset.get("learning_per_decision_enabled", True))
    if use_per_decision:
        top_dist = weighted_action_distribution(top)
        bottom_dist = weighted_action_distribution(bottom)
    else:
        top_dist = action_distribution(top)
        bottom_dist = action_distribution(bottom)

    # Adaptive learning rate: scale tune_* updates by how much data backs the
    # current pass. Early careers (few top samples / few actions) get larger
    # moves to converge fast; late careers shrink the moves to avoid chasing
    # sample noise. The fixed damping factors that have lived inside tune_*
    # for ages were calibrated for an early-phase pool — now that the sample
    # count is in the hundreds, the same fixed factors over-react.
    top_action_count = sum(len(sample.get("actions") or []) for sample in top)
    lr_scale = learning_rate_scale(top_count=len(top), action_count=top_action_count)

    learned = normalize_preset(copy.deepcopy(preset))
    learned["name"] = output_name or f"{preset['name']} learned"
    # `desired_parent_sparks` is operator intent, not learned state. Keep it
    # in reports/metadata for traceability, but never make the learner the
    # owner of the active blue/pink/green/white farming targets.
    learned.pop("desired_parent_sparks", None)
    if reference_rules:
        learned["parent_farming_rules"] = reference_rules
    learned_targets = tune_expect_attribute(learned, top, usable)
    learned["expect_attribute"] = learned_targets
    learned["expect_attribute_profiles"] = learn_expect_attribute_profiles(
        learned,
        top,
        usable,
        default_targets=learned_targets,
        min_bucket_size=4,
    )
    learned["stat_value_multiplier"] = tune_stat_value_multiplier(learned, top, usable, learned_targets)
    learned["extra_weight"] = tune_extra_weight(learned, top_dist, bottom_dist, lr_scale=lr_scale)
    deviation_summary = {
        "enabled": bool(preset.get("learning_use_deviation_signal", True)),
        "total_rows": 0,
        "disagreed_rows": 0,
        "used_rows": 0,
        "fade_multiplier": 0.0,
        "min_career_score": as_float(preset.get("learning_deviation_min_career_score"), 12000),
    }
    if deviation_summary["enabled"]:
        deviation_rows = []
        # Deviation/manual correction evidence should remain shared in dual
        # runtime mode. Account-local bot runs keep their own deck context via
        # behavior_usable above, but deliberate manual play is global teaching
        # signal and must not disappear just because a runtime has enough local
        # loop samples.
        deviation_runtime_roots = runtime_roots(base_dir, runtime_paths)
        for root in deviation_runtime_roots:
            deviation_rows.extend(load_deviation_signals(
                root,
                recent=recent,
                min_career_score=deviation_summary["min_career_score"],
            ))
        learned, tuned_summary = tune_deviation_bias(
            learned,
            deviation_rows,
            min_career_score=deviation_summary["min_career_score"],
        )
        deviation_summary.update(tuned_summary)
    learned["base_score"] = tune_base_score(learned, top_dist, bottom_dist, lr_scale=lr_scale)
    learned["score_value"] = tune_score_value(learned, top_dist, bottom_dist)
    run_mode_policy = learn_run_mode_policy(top, behavior_usable)
    if run_mode_policy:
        learned["run_mode_policy"] = run_mode_policy
    learned["rest_threshold"] = tune_rest_threshold(learned, behavior_usable, top_samples=top, run_mode_policy=run_mode_policy)
    learned["learn_skill_threshold"] = tune_learn_skill_threshold(learned, behavior_usable)
    learned["mant_config"] = tune_mant_config(learned, top, behavior_usable)
    learned_item_policy, item_learning_summary = learn_item_policy(behavior_usable)
    if learned_item_policy:
        learned["item_learning_policy"] = learned_item_policy
    learned.update(tune_optional_race_policy(learned, top, behavior_usable))
    min_policy_actions = as_int(learned.get("training_policy_min_actions"), 12)
    # Action classifier uses a different sample selection than the auto-tuner —
    # it needs careers with REAL action sequences ranked by per-turn efficiency,
    # not parent-library imports ranked by absolute final score. Falls back to
    # the auto-tuner's groups when not enough action-rich samples are available
    # (e.g. fresh installs).
    action_top, action_bottom = split_action_classifier_groups(behavior_usable, preset=learned)
    action_ratio_health = policy_action_ratio_health(action_top, action_bottom)
    new_policy_model = build_training_policy_model(action_top, action_bottom, behavior_usable, min_actions=min_policy_actions)

    # Hold-out validation: score BOTH the previously-applied model and the
    # newly-fitted model on the SAME current top samples. If the new model
    # scores LOWER (i.e. would push the bot away from top-sample patterns
    # it currently rewards), reject it and keep the old model. This stops
    # successive bot-only runs from drifting into self-amplifying mediocre
    # weights — the only way to overwrite a good model is to fit a NEW one
    # that demonstrably matches top-sample behavior at least as well.
    old_policy_model = preset.get("training_policy_model") or {}
    old_model_disqualified_reason = ""
    if isinstance(old_policy_model, dict) and old_policy_model.get("enabled"):
        old_objective = previous_metadata.get("objective")
        old_gate = previous_metadata.get("policy_steering_gate") or {}
        if old_objective != LEARNING_OBJECTIVE_VERSION:
            old_model_disqualified_reason = f"prior_model_objective_{old_objective or 'missing'}"
            old_policy_model = {}
        elif isinstance(old_gate, dict) and as_int(old_gate.get("positive_sample_count")) <= 0:
            old_model_disqualified_reason = "prior_model_missing_positive_policy_gate"
            old_policy_model = {}
    validation_anchor_rows = recent_validation_samples(action_top or usable, limit=1, min_actions=min_policy_actions)
    validation_anchor = validation_anchor_rows[0] if validation_anchor_rows else None
    validation_selection = select_context_validation_samples(
        action_top or top,
        validation_anchor,
        limit=max(8, as_int(preset.get("training_policy_validation_context_limit"), 24)),
        min_actions=min_policy_actions,
        min_match_count=max(4, as_int(preset.get("training_policy_validation_context_min_samples"), 6)),
    )
    validation_samples = validation_selection.get("samples") or action_top or top
    recent_holdout = recent_validation_samples(
        validation_samples,
        limit=max(4, as_int(preset.get("training_policy_validation_recent_limit"), 12)),
        min_actions=min_policy_actions,
    )
    old_score = score_model_on_samples(old_policy_model, validation_samples)
    new_score = score_model_on_samples(new_policy_model, validation_samples)
    old_holdout_score = score_model_on_samples(old_policy_model, recent_holdout)
    new_holdout_score = score_model_on_samples(new_policy_model, recent_holdout)
    # Default loosened from 0.985 → 0.96 (allow up to 4% regression on
    # either holdout). The tighter default was rejecting nearly every
    # new model fit even when the bot had clearly drifted away from
    # historical winners. This is a safe loosening — it only gives the
    # validator more headroom to accept a marginally-different model;
    # large regressions still reject. NO force-promote escape valve:
    # promoting a model fit to all-losses data would just teach the
    # bot to repeat the losing pattern. The right fix for stuck-loss
    # cycles is `race_style_overrides` + aptitude gate + postmortem
    # feedback, not bypassing validation.
    validation_tolerance = clamp(
        as_float(preset.get("training_policy_validation_tolerance"), 0.96),
        0.9,
        1.0,
    )
    challenger_decision = _shadow_challenger_update(
        preset,
        old_policy_model,
        new_policy_model,
        old_score,
        new_score,
        old_holdout_score,
        new_holdout_score,
        validation_tolerance,
        recent_holdout_count=len(recent_holdout),
    )
    policy_validation = {
        "old_model_score": None if old_score is None else round(old_score, 5),
        "new_model_score": None if new_score is None else round(new_score, 5),
        "validation_sample_count": len(validation_samples),
        "recent_holdout_count": len(recent_holdout),
        "action_top_sample_count": len(action_top),
        "action_bottom_sample_count": len(action_bottom),
        "action_top_bottom_health": action_ratio_health,
        "objective_positive_sample_count": policy_gate_summary.get("positive_sample_count"),
        "diagnostic_only_sample_count": policy_gate_summary.get("diagnostic_only_count"),
        "diagnostic_reasons": policy_gate_summary.get("reasons") or {},
        "old_model_disqualified_reason": old_model_disqualified_reason,
        "old_recent_holdout_score": None if old_holdout_score is None else round(old_holdout_score, 5),
        "new_recent_holdout_score": None if new_holdout_score is None else round(new_holdout_score, 5),
        "tolerance": validation_tolerance,
        "validation_mode": validation_selection.get("mode") or "recent_only",
        "context_match_count": as_int(validation_selection.get("match_count"), 0),
        "decision": challenger_decision.get("decision"),
        "reason": challenger_decision.get("reason"),
        "validation_confidence": challenger_decision.get("validation_confidence") or {},
        "challenger_enabled": bool(preset.get("training_policy_challenger_enabled", True)),
    }
    validation_anchor_context = validation_selection.get("anchor") or {}
    if validation_anchor_context:
        policy_validation["anchor_context"] = {
            "preset_name": validation_anchor_context.get("preset_name"),
            "trainee_card_id": validation_anchor_context.get("trainee_card_id"),
            "deck_quality_bucket": validation_anchor_context.get("deck_quality_bucket"),
            "deck_signature": validation_anchor_context.get("deck_signature"),
            "primary_stat": validation_anchor_context.get("primary_stat"),
            "style": validation_anchor_context.get("style"),
        }
    # Re-apply Hygiene 1 clamps at the persistence boundary. Without this,
    # an OLD model (preserved when challenger is staged but not yet
    # promoted) keeps its pre-clamp violating weights for every cycle
    # until promotion completes — which can take many careers.
    from career_bot.training_policy import enforce_model_floors
    active_model = challenger_decision.get("active_model") or old_policy_model or {}
    enforce_model_floors(active_model)
    learned["training_policy_model"] = active_model
    # Also clamp the staged challenger's stored model so promotion to
    # active never re-introduces violations.
    staged_challenger = challenger_decision.get("challenger") or {}
    if isinstance(staged_challenger, dict) and isinstance(staged_challenger.get("model"), dict):
        enforce_model_floors(staged_challenger["model"])
    challenger_state = staged_challenger
    if challenger_state:
        learned["training_policy_challenger"] = challenger_state
        policy_validation["challenger"] = {
            "fingerprint": challenger_state.get("fingerprint"),
            "streak": challenger_state.get("streak"),
            "promotion_passes": challenger_state.get("promotion_passes"),
            "current_margin": challenger_state.get("current_margin"),
            "holdout_margin": challenger_state.get("holdout_margin"),
        }
    else:
        learned["training_policy_challenger"] = {}
    learned["training_policy_validation"] = policy_validation
    learned["training_policy_model_enabled"] = bool(learned.get("training_policy_model_enabled", True))
    learned["training_policy_model_weight"] = round(
        clamp(as_float(learned.get("training_policy_model_weight"), 0.55), 0.0, 0.75),
        4,
    )
    learned["training_policy_model_max_bonus"] = round(
        clamp(as_float(learned.get("training_policy_model_max_bonus"), 0.08), 0.0, 0.08),
        4,
    )
    learned["training_policy_model_runtime_cap"] = round(
        clamp(as_float(learned.get("training_policy_model_runtime_cap"), 0.08), 0.0, 0.08),
        4,
    )
    learned["training_policy_disable_on_untrusted_metadata"] = bool(
        learned.get("training_policy_disable_on_untrusted_metadata", True)
    )
    learned["training_policy_max_trusted_score"] = int(
        clamp(as_float(learned.get("training_policy_max_trusted_score"), 25000), 15000, 30000)
    )
    policy_model = learned.get("training_policy_model") or {}
    if (
        policy_model.get("enabled")
        and as_float(policy_model.get("confidence")) >= 0.75
        and as_int(policy_model.get("action_count")) >= 250
    ):
        learned["training_policy_model_max_bonus"] = round(
            clamp(max(as_float(learned.get("training_policy_model_max_bonus"), 0.08), 0.08), 0.0, 0.08),
            4,
        )
    # Postmortem feedback: aggregate recent G1 losses by race so the bot
    # can adjust per-race rather than the legacy global "always train
    # more Guts" signal. Empty when no postmortems exist or none meet
    # the filter (no losses recorded yet).
    postmortem_root = preferred_postmortem_runtime_root(base_dir, runtime_paths)
    if postmortem_root is not None:
        per_race_hints = race_stat_hints(postmortem_root)
        # Cross-career race attempt history pairs with the postmortem
        # aggregation: hints get a `diagnosis` field that classifies the
        # dominant loss cause (stat_gap_X / style_mismatch / skill_gap)
        # AND flags races as `chronic` when the bot has attempted them
        # multiple times with majority losses. Used for dashboard
        # visibility — NOT for race-entry gating (user explicitly
        # rejected the skip-on-chronic-loss mechanism; existing optional
        # race policy decides race vs train).
        attempt_history = load_race_attempt_history(postmortem_root)
        per_race_hints = attach_diagnoses(per_race_hints, attempt_history)
    else:
        per_race_hints = {}
    from career_bot.postmortem_feedback import POSTMORTEM_FEEDBACK_SCHEMA

    global_hint = merge_global_signal(per_race_hints)
    if per_race_hints:
        # Stored on the learned preset for the bot to consult at runtime
        # (training-policy bias). Keys are program_ids (ints).
        learned["postmortem_feedback_schema"] = POSTMORTEM_FEEDBACK_SCHEMA
        learned["race_specific_stat_hints"] = per_race_hints
        learned["postmortem_global_hint"] = global_hint
    # Hard per-race stat targets: the "no more losses" rail. Soft hints
    # bias training a bit; thresholds set the floor that training-policy
    # bias and force-train escalation use to drive deficit-targeted
    # training. Built off the same postmortem corpus.
    if postmortem_root is not None:
        try:
            from career_bot.race_thresholds import build_and_write_race_thresholds
            build_and_write_race_thresholds(postmortem_root)
        except Exception as exc:  # noqa: BLE001 — defensive: never fail learning over threshold-write
            print(f"race_thresholds build skipped: {exc}")
    race_success_hints = aggregate_success_by_race(usable)
    race_success_global_hint = merge_global_success_signal(race_success_hints)
    if race_success_hints:
        # Success-side mirror of the loss postmortem path. Uses only
        # race-time stat bands / style / skill-count dependence and
        # explicitly avoids promoting specific skill ids as "winning
        # skills".
        learned["race_specific_success_hints"] = race_success_hints
    # OFF by default — see comment above in the earlier learn_preset
    # branch. User does not want learned style overrides applied.
    if bool((preset or {}).get("race_style_overrides_learned_enabled", False)):
        learned_race_style_overrides = learn_race_style_overrides(per_race_hints, race_success_hints)
    else:
        learned_race_style_overrides = {}
    if learned_race_style_overrides:
        learned["race_style_overrides"] = learned_race_style_overrides

    # Event-choice learning: scan all usable samples for `event_choice`
    # rows logged by the runner, correlate (story_id, choice_index) with
    # career score, and emit a learned stats dict. The picker at
    # MantStrategy.choose_from_event consults this to override the
    # static EventManager choice when a clear better option exists in
    # the bot's own career data.
    event_choice_stats = aggregate_event_choices(usable, preset_fallback=learned)
    if event_choice_stats:
        learned["event_choice_stats"] = event_choice_stats

    # Race-continue learning: per-(program_id, resource_type) recovery
    # rates from past race continues. Runner uses this to skip burning
    # alarm-clock/carat retries on races that historically never
    # recover (saving resources for races where continues actually
    # work). NOT a race-skip mechanism — only fires AFTER a loss, when
    # deciding whether to spend a continue.
    race_continue_stats = aggregate_continue_outcomes(usable)
    if race_continue_stats:
        learned["race_continue_stats"] = race_continue_stats

    # Motivation curve learning: derive `motivation_threshold_year{1,2,3}`
    # from the per-phase median motivation top samples actually
    # maintained. If top careers averaged motivation 5 in mid-game,
    # the bot should aim to keep it that high (threshold ≥ 5 → recreate
    # whenever below max). Only overrides when there's enough data; otherwise
    # the preset's existing thresholds stay in place.
    motivation_overrides = learned_motivation_thresholds(top)
    for key, value in motivation_overrides.items():
        learned[key] = value

    # HP curve learning: derive `target_hp_year{1,2,3}` from per-phase
    # median HP top samples maintained. The bot's rest decision can
    # consult these as soft floors (rest when HP < target) instead of
    # relying solely on the static `rest_threshold` default.
    hp_target_overrides = learned_hp_targets(top)
    for key, value in hp_target_overrides.items():
        learned[key] = value

    # Career trajectory prediction: build per-checkpoint centroids from
    # top vs bottom samples so the runner can classify a live career as
    # tracking_top/tracking_bottom/ambiguous at fixed turn checkpoints.
    # Stored on the preset for the runner to consult; predictions are
    # logged informationally — no decision branches read this yet.
    trajectory_centroids = aggregate_trajectory_centroids(top, bottom)
    if trajectory_centroids:
        learned["trajectory_centroids"] = trajectory_centroids
    future_turn_effects = aggregate_future_turn_effects(usable)
    if future_turn_effects:
        learned["future_turn_effects"] = future_turn_effects
    apply_gate = monotonic_apply_gate(preset, behavior_usable)

    learned["learning_metadata"] = {
        "schema": "sweepy_learning_v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_preset": preset.get("name"),
        "usable_samples": len(usable),
        "behavior_usable_samples": len(behavior_usable),
        "behavior_pool_samples_before_context": behavior_pool_sample_count_before_context,
        "context_adaptation": context_adaptation,
        "local_usable_samples": runtime_pooling.get("local_sample_count", 0),
        "total_samples": len(samples),
        "top_count": len(top),
        "bottom_count": len(bottom),
        "top_score_range": [top[-1].get("score") if top else None, top[0].get("score") if top else None],
        "bottom_score_range": [bottom[-1].get("score") if bottom else None, bottom[0].get("score") if bottom else None],
        "sample_signature": signature,
        "objective": LEARNING_OBJECTIVE_VERSION,
        "desired_parent_sparks": parent_goals,
        "runtime_roots_used": resolved_runtime_roots,
        "primary_runtime_root": _normalized_runtime_root(primary_root),
        "learning_pool_mode": runtime_pooling.get("mode"),
        "parent_farming_rules": learned.get("parent_farming_rules") or {},
        "white_spark_rank_diagnostic": white_rank_diagnostic,
        "first_summer_friendship_diagnostic": friendship_diag,
        "recency_weighting": recency_summary,
        "reference_group_strategy": reference_group_strategy,
        "sample_stratification": sample_stratification,
        "deviation_signal": deviation_summary,
        "monotonic_apply_gate": apply_gate,
        "item_learning_summary": item_learning_summary,
        "run_mode_policy": run_mode_policy,
        "support_action_summary": dict(_support_action_counts(usable)),
        "training_policy_challenger": learned.get("training_policy_challenger") or {},
        "policy_steering_gate": policy_gate_summary,
        "postmortem_feedback_schema": POSTMORTEM_FEEDBACK_SCHEMA,
        "race_specific_stat_hints": per_race_hints,
        "postmortem_global_hint": global_hint,
        "race_specific_success_hints": race_success_hints,
        "race_success_global_hint": race_success_global_hint,
        "race_style_overrides": learned_race_style_overrides,
        "future_turn_effects": future_turn_effects,
        "expect_attribute_profiles": learned.get("expect_attribute_profiles") or {},
        "note": "Generated from local career logs. Re-run after new manual or bot careers to update the preset.",
    }

    tracked_keys = [
        "expect_attribute",
        "expect_attribute_profiles",
        "stat_value_multiplier",
        "extra_weight",
        "base_score",
        "score_value",
        "rest_threshold",
        "learn_skill_threshold",
        "mant_config",
        "optional_race_max_training_score",
        "optional_race_min_value",
        "optional_race_epithet_bonus",
        "optional_race_rival_bonus",
        "optional_race_skip_if_stamina_low",
        "item_learning_policy",
        "run_mode_policy",
        "training_policy_model",
        "training_policy_challenger",
        "training_policy_model_enabled",
        "training_policy_model_weight",
        "training_policy_model_max_bonus",
        "training_policy_model_runtime_cap",
        "training_policy_validation",
        "race_style_overrides",
        "future_turn_effects",
    ]
    report = {
        "schema": "sweepy_learning_report_v1",
        "created_at": learned["learning_metadata"]["created_at"],
        "source_preset": preset.get("name"),
        "learned_preset": learned["name"],
        "sample_count": len(samples),
        "usable_sample_count": len(usable),
        "behavior_usable_sample_count": len(behavior_usable),
        "local_usable_sample_count": runtime_pooling.get("local_sample_count", 0),
        "manual_behavior_sample_count": runtime_pooling.get("manual_behavior_sample_count", 0),
        "behavior_pool_sample_count": runtime_pooling.get("behavior_sample_count", len(behavior_usable)),
        "behavior_pool_sample_count_before_context": behavior_pool_sample_count_before_context,
        "context_adaptation": context_adaptation,
        "learning_pool_mode": runtime_pooling.get("mode"),
        "source_counts": dict(Counter(sample.get("source") for sample in usable)),
        "sample_signature": signature,
        "objective": LEARNING_OBJECTIVE_VERSION,
        "desired_parent_sparks": parent_goals,
        "runtime_roots_used": resolved_runtime_roots,
        "primary_runtime_root": _normalized_runtime_root(primary_root),
        "parent_farming_rules": learned.get("parent_farming_rules") or {},
        "white_spark_rank_diagnostic": white_rank_diagnostic,
        "postmortem_feedback_schema": POSTMORTEM_FEEDBACK_SCHEMA,
        "race_specific_stat_hints": per_race_hints,
        "postmortem_global_hint": global_hint,
        "race_specific_success_hints": race_success_hints,
        "race_success_global_hint": race_success_global_hint,
        "race_style_overrides": learned_race_style_overrides,
        "future_turn_effects": future_turn_effects,
        "expect_attribute_profiles": learned.get("expect_attribute_profiles") or {},
        "top_samples": top_sample_summary(top),
        "bottom_samples": top_sample_summary(list(reversed(bottom))),
        "changes": change_summary(preset, learned, tracked_keys),
        "top_action_rates": {
            TRAINING_NAMES[idx]: round(row_rates([row["count"] for row in top_dist["overall"]])[idx], 4)
            for idx in range(5)
        },
        "bottom_action_rates": {
            TRAINING_NAMES[idx]: round(row_rates([row["count"] for row in bottom_dist["overall"]])[idx], 4)
            for idx in range(5)
        },
        "warnings": learning_warnings(usable, top) + friendship_warnings + (action_ratio_health.get("warnings") or []),
        "training_policy_model": learned.get("training_policy_model") or {},
        "training_policy_validation": policy_validation,
        "score_floor": score_floor,
        "score_floor_adaptation": score_floor_adaptation,
        "score_floors_by_deck": score_floors_by_deck,
        "empirical_score_floors": empirical_score_floor_diagnostic,
        "reference_group_strategy": reference_group_strategy,
        "decision_quality_summary": {
            "per_decision_enabled": use_per_decision,
            "top_average_quality": top_dist.get("average_quality"),
            "bottom_average_quality": bottom_dist.get("average_quality"),
            "top_average_followthrough": top_dist.get("average_followthrough"),
            "bottom_average_followthrough": bottom_dist.get("average_followthrough"),
            "top_action_count": top_dist.get("action_count"),
            "bottom_action_count": bottom_dist.get("action_count"),
            "learning_rate_scale": round(lr_scale, 4),
        },
        "recency_weighting": recency_summary,
        "sample_stratification": sample_stratification,
        "outcome_distribution": outcome_distribution,
        "intent_weight_summary": intent_weight_summary,
        "deviation_signal": deviation_summary,
        "monotonic_apply_gate": apply_gate,
        "item_learning_summary": item_learning_summary,
        "run_mode_policy": run_mode_policy,
        "support_action_summary": dict(_support_action_counts(usable)),
        "training_policy_challenger": learned.get("training_policy_challenger") or {},
        "policy_steering_gate": policy_gate_summary,
        "first_summer_friendship_diagnostic": friendship_diag,
    }
    # Final defensive check: every tune_* has an internal clamp, but a refactor
    # bug (sign flip, wrong index, off-by-one) could produce an out-of-range
    # value the clamp doesn't catch. Raising here keeps the old preset
    # untouched on disk — far better than silently overwriting with bad math.
    assert_learned_preset_invariants(learned)
    return learned, report


def learning_warnings(samples, top):
    warnings = []
    manual_count = sum(1 for sample in samples if str(sample.get("source", "")).startswith("manual"))
    if manual_count == 0:
        warnings.append("No manual-player samples were found; learned weights are based only on bot careers.")
    full_count = sum(1 for sample in samples if is_full_career_sample(sample))
    if full_count < 5:
        warnings.append("Fewer than five full careers were available; changes are conservative.")
    if not any(as_float((sample.get("factor_quality") or {}).get("score")) > 0 for sample in top):
        warnings.append("No reliable final factor/spark payload was found in top samples, so spark quality is optimized indirectly through stats/races/skills.")
    if not any(as_int((sample.get("race_quality") or {}).get("affinity_overlap_wins")) > 0 for sample in top):
        warnings.append("No affinity-overlap race metadata was detected in top samples; parent affinity is optimized from available race wins only.")
    if any(as_int((sample.get("skill_quality") or {}).get("final_skill_point")) > 600 for sample in top):
        warnings.append("Some top samples still ended with high unspent SP; skill-drain behavior should be verified in new completed bot careers.")
    return warnings


def policy_action_ratio_health(top_samples, bottom_samples, warn_ratio=4.0):
    buckets = {}
    for label, samples in (("top", top_samples or []), ("bottom", bottom_samples or [])):
        for sample in samples:
            key = _sample_objective_bucket(sample)
            bucket = buckets.setdefault(key, {"top_actions": 0, "bottom_actions": 0, "top_samples": 0, "bottom_samples": 0})
            actions = len((sample or {}).get("actions") or [])
            bucket[f"{label}_actions"] += actions
            bucket[f"{label}_samples"] += 1
    warnings = []
    for key, bucket in sorted(buckets.items()):
        top_actions = as_int(bucket.get("top_actions"))
        bottom_actions = as_int(bucket.get("bottom_actions"))
        if top_actions <= 0 and bottom_actions > 0:
            bucket["bottom_to_top_action_ratio"] = None
            warnings.append(f"corpus_skewed_bucket_{key}_ratio_0:{bottom_actions}")
            continue
        if top_actions > 0:
            ratio = bottom_actions / max(1, top_actions)
            bucket["bottom_to_top_action_ratio"] = round(ratio, 4)
            if ratio > warn_ratio:
                warnings.append(f"corpus_skewed_bucket_{key}_ratio_1:{ratio:.2f}")
    return {"buckets": buckets, "warnings": warnings}


def _atomic_write_json(path, payload):
    """Write JSON to `path` atomically — same pattern parent_memory uses.
    Prevents the case where a crash mid-write leaves a half-truncated
    preset file on disk that the next career run would then read as
    invalid JSON. Writes to a sibling `.tmp` then renames in one step.

    Windows-specific resilience: `os.replace` can fail with PermissionError
    if the destination file is open in another process (text editor, dev
    tool, etc.). When that happens, retry with a short backoff. If we still
    can't rename after a few tries, fall back to direct write — at least
    the data lands, even if the brief non-atomic window opens.
    """
    import os as _os
    import time as _time
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(serialized, encoding="utf-8")
    last_exc = None
    for attempt in range(3):
        try:
            _os.replace(tmp, path)
            return
        except PermissionError as exc:
            last_exc = exc
            _time.sleep(0.15 * (attempt + 1))
    # Fallback: direct write so the data isn't lost. Best-effort cleanup of
    # the .tmp file. The atomic guarantee weakens for this one call but
    # data integrity is preserved — far better than failing the save.
    try:
        path.write_text(serialized, encoding="utf-8")
    finally:
        try:
            tmp.unlink()
        except Exception:
            pass
    if last_exc is not None:
        import sys as _sys
        print(
            f"[learning] _atomic_write_json: os.replace failed after retries ({last_exc!r}); "
            f"wrote {path} directly. The preset is intact but the write was not atomic.",
            file=_sys.stderr,
            flush=True,
        )


OPERATOR_OWNED_PRESET_KEYS = {
    # Skill plan / parent intent are edited directly in the UI and must not be
    # overwritten by a stale auto-learning job that started before the edit.
    "skill_buy_on_sight",
    "skill_profile_style",
    "skill_profile_distance",
    "skill_blacklist_custom",
    "learn_skill_blacklist",
    "learn_skill_list",
    "learn_skill_only_user_provided",
    "learn_skill_append_defaults",
    "manual_purchase_at_end",
    "calendar_race_prebuy_enabled",
    "calendar_race_prebuy_grades",
    "calendar_race_prebuy_all_scheduled",
    "scheduled_race_clean_record_mode",
    "calendar_race_clean_prebuy_min_sp",
    "calendar_race_clean_prebuy_budget",
    "calendar_race_clean_prebuy_keep_sp",
    "calendar_race_clean_prebuy_max_skills",
    "calendar_race_clean_prebuy_target_probability",
    "scheduled_race_safety_training_lookahead_turns",
    "scheduled_race_safety_requirement_scale",
    "scheduled_race_safety_bonus_cap",
    "scheduled_race_projected_gain_per_turn",
    "scheduled_race_force_calendar",
    "scheduled_race_safety_enabled",
    "scheduled_race_respect_training",
    "scheduled_race_skip_if_stamina_low",
    "scheduled_race_skip_off_aptitude",
    "calendar_race_prebuy_min_sp",
    "calendar_race_prebuy_budget",
    "calendar_race_prebuy_keep_sp",
    "calendar_race_prebuy_max_skills",
    "desired_parent_sparks",
    "skill_optimizer_enabled",
    "skill_point_drain_floor",
    "final_skill_drain_max_passes",
    # Race routing and explicit resource choices are also operator-owned.
    "race_plan_text",
    "custom_race_schedule",
    "extra_race_list",
    "race_list",
    "race_style_overrides",
    "race_exploration_enabled",
    "race_exploration_rate",
    "race_exploration_min_confidence",
    "race_exploration_max_relative_deficit",
    "race_exploration_min_static_stamina_ratio",
    "race_exploration_min_stat_coverage",
    "race_empirical_success_tolerance",
    "allow_recover_tp",
    "tp_recovery_mode",
    "alarm_clock_mode",
    "clock_use_limit",
    "alarm_clock_use_limit",
    "clock_allow_carats",
    "clock_allow_direct_carat_continue",
    "clock_consecutive_limit",
    "clock_free_continue_type",
    "clock_continue_type",
    "clock_carat_continue_type",
    "clock_carat_exchange_id",
    "clock_carat_cost",
    "clock_retry_delay_seconds",
    "race_continue_delay_seconds",
    "clock_pre_race_end_probe_seconds",
    "clock_pre_race_end_probe_interval",
    "clock_pre_race_end_continue_probe",
    "clock_pre_race_end_retry_205",
    # Auto-learning toggles are controls, not model outputs.
    "auto_learning_enabled",
    "auto_learning_apply",
    "auto_learning_min_samples",
    "auto_learning_recent",
    "auto_learning_recency_enabled",
    "auto_learning_recency_bias",
    "auto_learning_recency_half_life",
    "auto_learning_recent_failure_bias",
    "auto_learning_regression_enabled",
    "auto_learning_regression_bias",
    "auto_learning_regression_window",
    "auto_learning_regression_floor",
    "learning_use_stratified_reference_groups",
    "learning_use_deviation_signal",
    "auto_learning_statuses",
    "auto_learning_corrective_apply_enabled",
    "auto_learning_learn_from_complete_logs",
    "auto_learning_runtime_paths",
    "auto_learning_output_name",
    "auto_learning_apply_scope",
    "auto_learning_manual_only",
    "auto_learning_min_tier",
    "auto_learning_monotonic_apply_enabled",
    "auto_learning_monotonic_min_improvement",
    "auto_learning_monotonic_allowed_drop",
    "learning_policy_objective_gate_enabled",
    "learning_policy_min_rank_score",
    "learning_policy_min_internal_score",
    "learning_policy_min_stat_total",
    "learning_policy_min_actions",
    "learning_policy_max_race_losses",
    "learning_policy_max_g1_losses",
    "learning_policy_min_race_total_for_clean_record",
}


def _preserve_operator_owned_fields(learned, current_source):
    merged = copy.deepcopy(learned or {})
    preserved = []
    if not isinstance(current_source, dict):
        return merged, preserved
    for key in sorted(OPERATOR_OWNED_PRESET_KEYS):
        if key in current_source:
            if key == "race_style_overrides":
                learned_overrides = merged.get(key)
                current_overrides = current_source.get(key)
                if isinstance(learned_overrides, dict) and isinstance(current_overrides, dict):
                    # Deep-merge for the v2 nested format AND shallow-
                    # merge for the legacy flat format. The previous
                    # `dict.update` was overwriting the whole `global`
                    # sub-dict with the source's empty one, silently
                    # discarding every learned per-race override — the
                    # symptom was `change_running_style` never firing
                    # for chronic style-mismatch races (Yasuda Kinen,
                    # Champions Cup, etc.) even though the learner
                    # correctly identified the right style.
                    cur_global = current_overrides.get("global") if isinstance(current_overrides.get("global"), dict) else None
                    cur_by_chara = current_overrides.get("by_chara") if isinstance(current_overrides.get("by_chara"), dict) else None
                    cur_flat = {k: v for k, v in current_overrides.items() if k not in {"schema", "global", "by_chara"}}
                    has_meaningful_current = bool(cur_global) or bool(cur_by_chara) or bool(cur_flat)
                    if has_meaningful_current:
                        learned_is_v2 = (
                            "global" in learned_overrides
                            or "by_chara" in learned_overrides
                            or "schema" in learned_overrides
                        )
                        combined = copy.deepcopy(learned_overrides)
                        if learned_is_v2:
                            # Learned is v2; promote user's flat overrides
                            # (if any) INTO the v2 `global` sub-dict at
                            # higher priority than learned entries. Real
                            # bug we hit: `_style_for_entry` ignores
                            # top-level flat keys whenever the v2
                            # `global` is present, so flat user overrides
                            # were getting silently dropped.
                            existing_global = combined.get("global") if isinstance(combined.get("global"), dict) else {}
                            if cur_global:
                                existing_global.update(copy.deepcopy(cur_global))
                            if cur_flat:
                                for k, v in cur_flat.items():
                                    existing_global[str(k)] = copy.deepcopy(v)
                            if existing_global or "global" in combined:
                                combined["global"] = existing_global
                            if cur_by_chara:
                                existing_by_chara = combined.get("by_chara") if isinstance(combined.get("by_chara"), dict) else {}
                                for chara_key, chara_overrides in cur_by_chara.items():
                                    if not isinstance(chara_overrides, dict):
                                        continue
                                    slot = existing_by_chara.get(chara_key) if isinstance(existing_by_chara.get(chara_key), dict) else {}
                                    slot.update(copy.deepcopy(chara_overrides))
                                    existing_by_chara[chara_key] = slot
                                combined["by_chara"] = existing_by_chara
                            if "schema" in current_overrides:
                                combined["schema"] = current_overrides["schema"]
                        else:
                            # Both learned and current use the legacy
                            # flat-only format. Plain shallow merge —
                            # don't introduce a `global` sub-dict here,
                            # that would silently flip the schema and
                            # change downstream lookup semantics.
                            if cur_flat:
                                combined.update(copy.deepcopy(cur_flat))
                            if cur_global:
                                # Edge case: user added a v2-style
                                # `global` to a flat-learned dict.
                                # Mirror entries up to top-level so
                                # `_style_for_entry` sees them.
                                for k, v in cur_global.items():
                                    combined[str(k)] = copy.deepcopy(v)
                            if cur_by_chara:
                                combined["by_chara"] = copy.deepcopy(cur_by_chara)
                            if "schema" in current_overrides:
                                combined["schema"] = current_overrides["schema"]
                        merged[key] = combined
                        preserved.append(key)
                    # else: current is empty / no-op → keep learned as-is,
                    # don't mark `preserved` (matches the legacy test that
                    # asserted preserved didn't include the key in this case).
                    continue
            merged[key] = copy.deepcopy(current_source[key])
            preserved.append(key)
    return merged, preserved


def save_learning_outputs(base_dir, learned, report, apply=False):
    base = Path(base_dir)
    runtime = runtime_roots(base)[0]
    report_dir = runtime / "learning"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"learning_report_{timestamp}.json"
    _atomic_write_json(report_path, report)

    store = PresetStore(base_dir)
    store.ensure()
    if report.get("skipped"):
        source_name = report.get("source_preset") or learned.get("name")
        return store.saved_path(source_name), report_path

    learned_path = store.learned_path(learned["name"])
    if apply:
        source_name = report.get("source_preset") or learned.get("learning_metadata", {}).get("source_preset") or learned["name"]
        source_path = store.saved_path(source_name)
        backup_path = None
        current_source = store.read_one(source_name) or None
        if source_path.exists():
            backup_path = store.backup_dir / f"{source_path.stem}_{timestamp}.json"
            source_text = source_path.read_text(encoding="utf-8")
            backup_path.write_text(source_text, encoding="utf-8")
            try:
                current_source = json.loads(source_text)
            except Exception:
                current_source = None
        learned = copy.deepcopy(learned)
        learned["name"] = source_name
        learned, preserved_keys = _preserve_operator_owned_fields(learned, current_source)
        learned["name"] = source_name
        learned_path = source_path
        if backup_path:
            report["backup_path"] = str(backup_path)
        if preserved_keys:
            report["preserved_operator_fields"] = preserved_keys
        if backup_path or preserved_keys:
            _atomic_write_json(report_path, report)
        if store.config_path(source_name).exists():
            layers = split_preset_layers(learned)
            store.save_policy_model(layers["family"], layers["model"])
            if layers["runtime"]:
                store.save_runtime_state("", source_name, layers["runtime"])
            report["policy_model_path"] = str(store.policy_model_path(layers["family"]))
            _atomic_write_json(report_path, report)
    _atomic_write_json(learned_path, normalize_preset(learned))
    return learned_path, report_path


def save_learning_report_only(base_dir, report):
    base = Path(base_dir)
    runtime = runtime_roots(base)[0]
    report_dir = runtime / "learning"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"learning_report_{timestamp}.json"
    _atomic_write_json(report_path, report)
    return report_path


def save_instance_learning_outputs(base_dir, learned, report):
    from career_bot.presets import instance_learning_override_path, split_preset_layers

    base = Path(base_dir)
    runtime = runtime_roots(base)[0]
    report_dir = runtime / "learning"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"learning_report_{timestamp}.json"

    source_name = report.get("source_preset") or learned.get("learning_metadata", {}).get("source_preset") or learned.get("name") or "preset"
    store = PresetStore(base_dir)
    current_source = store.read_one(source_name) or {}

    learned = copy.deepcopy(learned)
    learned["name"] = source_name
    learned["instance_learning_source_preset"] = source_name
    learned, preserved_keys = _preserve_operator_owned_fields(learned, current_source)
    learned["name"] = source_name
    learned["instance_learning_source_preset"] = source_name

    instance_name = str(os.environ.get("SWEEPY_INSTANCE_NAME") or "").strip() or runtime.name
    report = copy.deepcopy(report)
    report["apply_scope"] = "instance_local"
    report["instance_name"] = instance_name
    if preserved_keys:
        report["preserved_operator_fields"] = preserved_keys

    learned_path = instance_learning_override_path(base_dir, source_name)
    _atomic_write_json(learned_path, normalize_preset(learned))
    if store.config_path(source_name).exists():
        layers = split_preset_layers(learned, instance_override=True)
        store.save_policy_overrides(instance_name, layers["family"], layers["overrides"])
        if layers["runtime"]:
            store.save_runtime_state(instance_name, source_name, layers["runtime"])
        report["policy_overrides_path"] = str(store.policy_overrides_path(instance_name, layers["family"]))
    report["instance_preset_path"] = str(learned_path)
    _atomic_write_json(report_path, report)
    return learned_path, report_path


def save_shared_learning_outputs(base_dir, learned, report):
    from career_bot.presets import shared_learning_override_path, split_preset_layers

    base = Path(base_dir)
    runtime = runtime_roots(base)[0]
    report_dir = runtime / "learning"
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"learning_report_{timestamp}.json"

    source_name = report.get("source_preset") or learned.get("learning_metadata", {}).get("source_preset") or learned.get("name") or "preset"
    store = PresetStore(base_dir)
    current_source = store.read_one(source_name) or {}

    learned = copy.deepcopy(learned)
    learned["name"] = source_name
    learned["shared_learning_source_preset"] = source_name
    learned, preserved_keys = _preserve_operator_owned_fields(learned, current_source)
    learned["name"] = source_name
    learned["shared_learning_source_preset"] = source_name

    report = copy.deepcopy(report)
    report["apply_scope"] = "shared_overlay"
    if preserved_keys:
        report["preserved_operator_fields"] = preserved_keys

    learned_path = shared_learning_override_path(base_dir, source_name)
    _atomic_write_json(learned_path, normalize_preset(learned))
    if store.config_path(source_name).exists():
        layers = split_preset_layers(learned, instance_override=True)
        store.save_policy_model(layers["family"], layers["model"])
        if layers["runtime"]:
            store.save_runtime_state("", source_name, layers["runtime"])
        report["policy_model_path"] = str(store.policy_model_path(layers["family"]))
    report["shared_preset_path"] = str(learned_path)
    _atomic_write_json(report_path, report)
    return learned_path, report_path
