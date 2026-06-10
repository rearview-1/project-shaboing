import math
from collections import Counter

from career_bot.decision_quality import combined_decision_quality, quality_multiplier
from career_bot.objectives import objective_bucket_key
from career_bot.presets import resolve_expect_attribute


TRAINING_COMMANDS = {101: 0, 105: 1, 102: 2, 103: 3, 106: 4, 601: 0, 602: 1, 603: 2, 604: 3, 605: 4}
STAT_TARGETS = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 30: 5}
SUMMER_CAMP_TURNS = {36, 37, 38, 39, 40, 60, 61, 62, 63, 64}
DECK_PARTNERS = {1, 2, 3, 4, 5, 6}
STAT_KEYS = ["speed", "stamina", "power", "guts", "wiz"]

FEATURE_NAMES = [
    "turn_progress",
    "early_phase",
    "mid_phase",
    "late_phase",
    "summer_phase",
    "weighted_gain",
    "stat_gain",
    "skill_point_gain",
    "energy_delta",
    "failure_rate",
    "partner_count",
    "deck_partner_count",
    "rainbow_count",
    "near_rainbow_count",
    "near_rainbow_deck_count",
    "hint_count",
    "high_bond_count",
    "hp_ratio",
    "low_hp",
    "under_target",
    "over_target",
    "blue_goal_training",
    "race_demand_pressure",
    "rainbow_setup_pressure",
    "first_summer_friendship_pressure",
    "facility_level",
    "facility_progress",
    "facility_levelup_next_train",
    "facility_is_max_level",
    "friendship_unlocked_gap",
    "lagging_stat_alignment",
    "late_white_pressure",
]

ALWAYS_INCLUDED_FEATURES = {
    "first_summer_friendship_pressure",
    "friendship_unlocked_gap",
    "lagging_stat_alignment",
    "blue_goal_training",
    "facility_levelup_next_train",
}

PERSISTENT_SIGNAL_FEATURES = {
    "first_summer_friendship_pressure",
    "friendship_unlocked_gap",
    "lagging_stat_alignment",
    "blue_goal_training",
    "facility_levelup_next_train",
}

WEIGHT_FLOOR_CLAMPS = {
    # Hygiene 1 (per claude-code-handoff-ss-rank-redesign.md):
    "lagging_stat_alignment": 0.0,
    "blue_goal_training": 0.0,
    "race_demand_pressure": 0.0,
    "rainbow_setup_pressure": 0.0,
    "first_summer_friendship_pressure": 0.02,
    "friendship_unlocked_gap": 0.02,
    "high_bond_count": 0.0,
    "rainbow_count": 0.0,
    # Extended (post-Wave-0 audit found these also drift wrong-signed
    # from corpus skew). All represent positive game-state signals —
    # more partners, more stat gain, more HP = strictly better state.
    # Negative weights would teach the bot to AVOID partners / stats /
    # HP, which is domain-nonsense.
    "near_rainbow_count": 0.0,
    "near_rainbow_deck_count": 0.0,
    "hint_count": 0.0,
    "partner_count": 0.0,
    "deck_partner_count": 0.0,
    "weighted_gain": 0.0,
    "stat_gain": 0.0,
    "skill_point_gain": 0.0,
    "hp_ratio": 0.0,
    "facility_levelup_next_train": 0.0,
    "facility_level": 0.0,
}

# Companion to WEIGHT_FLOOR_CLAMPS: features that should never go
# POSITIVE. failure_rate going positive means the model learned
# "more failure = better outcome" which is nonsense. low_hp positive
# means "lower HP = better" — same. These are the negative-domain
# features that represent strictly bad game state.
WEIGHT_CEILING_CLAMPS = {
    "failure_rate": 0.0,
    "low_hp": 0.0,
    "facility_is_max_level": 0.0,  # at-max means no more growth — neutral at best
}

BLUE_SPARK_STAT_ALIASES = {
    "speed": 0,
    "stamina": 1,
    "power": 2,
    "guts": 3,
    "wit": 4,
    "wisdom": 4,
    "wiz": 4,
    "intelligence": 4,
}


def _safe_float(value, default=0.0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _clamp(value, minimum, maximum):
    return max(minimum, min(maximum, value))


def _policy_metadata_is_trusted(preset):
    """Reject learned steering when its score corpus is clearly mixed/poisoned."""
    if not isinstance(preset, dict):
        return True
    if not bool(preset.get("training_policy_disable_on_untrusted_metadata", True)):
        return True
    max_score = _safe_float(preset.get("training_policy_max_trusted_score"), 25000.0)
    if max_score <= 0:
        return True
    metadata = preset.get("learning_metadata") or {}
    if not isinstance(metadata, dict):
        return True
    if metadata.get("objective") == "parent_farming_v16":
        gate = metadata.get("policy_steering_gate") or {}
        if isinstance(gate, dict):
            positive = _safe_int(gate.get("positive_sample_count"), 0)
            diagnostic = _safe_int(gate.get("diagnostic_only_count"), 0)
            if positive <= 0 and diagnostic > 0:
                return False
            if positive > 0:
                return True
    for key in ("top_score_range", "bottom_score_range"):
        value = metadata.get(key)
        if not isinstance(value, (list, tuple)):
            continue
        for raw_score in value:
            if _safe_float(raw_score, 0.0) > max_score:
                return False
    return True


def _period_index(turn):
    turn = _safe_int(turn)
    if turn <= 24:
        return 0
    if turn <= 48:
        return 1
    if turn <= 60:
        return 2
    if turn <= 72:
        return 3
    return 4


def _extra_phase_index(turn):
    turn = _safe_int(turn)
    if turn <= 24:
        return 0
    if turn <= 48:
        return 1
    if turn in SUMMER_CAMP_TURNS:
        return 3
    return 2


def _first_summer_target_for_turn(turn, preset=None):
    turn = _safe_int(turn)
    final_target = _safe_int((preset or {}).get("first_summer_friendship_target_rainbows"), 4)
    if turn <= 12:
        return max(0, min(final_target, 1))
    if turn <= 24:
        return max(0, min(final_target, 2))
    if turn <= _safe_int((preset or {}).get("first_summer_friendship_target_turn"), 35):
        return max(0, final_target)
    return 0


def _weighted_average(rows, weights, feature):
    total = sum(weights)
    if total <= 0:
        return 0.0
    return sum(row.get(feature, 0.0) * weight for row, weight in zip(rows, weights)) / total


def _row_weight(sample):
    score_weight = _clamp(_safe_float(sample.get("score")) / 9000.0, 0.55, 1.85)
    return _safe_float(sample.get("sample_weight"), 1.0) * score_weight


def _policy_source_multiplier(sample, action):
    """Bias training-policy fitting toward strong manual corrections,
    especially in the first-summer setup window.

    Without this, a large backlog of mediocre bot careers can dominate
    the action corpus and teach the policy model to smooth the bot's own
    mistakes instead of correcting them."""
    source = str((sample or {}).get("source") or "").lower()
    score = _safe_float((sample or {}).get("score"))
    turn = _safe_int((action or {}).get("turn"))
    outcome = str((((sample or {}).get("learning_metadata") or {}).get("outcome_assessment") or {}).get("overall") or "").lower()
    multiplier = 1.0
    if source.startswith("manual"):
        multiplier *= 1.12
        if turn <= 35:
            multiplier *= 1.28
        if score >= 15000:
            multiplier *= 1.18
        if outcome in {"objective_success", "great_success"}:
            multiplier *= 1.08
    elif source == "bot":
        if turn <= 35:
            multiplier *= 0.92
            if score < 14000:
                multiplier *= 0.84
        if outcome in {"run_failure", "partial_success"} and score < 15000:
            multiplier *= 0.90
    return _clamp(multiplier, 0.55, 2.5)


def _action_weight(sample, action):
    base = _row_weight(sample)
    quality = _safe_float((action or {}).get("decision_quality"))
    if quality <= 0:
        quality = combined_decision_quality(action or {}, (action or {}).get("training_snapshot"))
    return base * quality_multiplier(quality) * _policy_source_multiplier(sample, action)


def _norm_slug(value, default="any"):
    text = str(value or "").strip().lower()
    if not text:
        return default
    return "".join(ch if ch.isalnum() else "_" for ch in text).strip("_") or default


def _sample_objective_bucket(sample):
    meta = (sample or {}).get("learning_metadata") or {}
    session = meta.get("session") or {}
    objective = objective_bucket_key(session)
    run_context = (sample or {}).get("run_context") or {}
    style = (
        session.get("style_target")
        or run_context.get("skill_profile_style")
        or (sample or {}).get("skill_profile_style")
        or ""
    )
    distance = (
        run_context.get("skill_profile_distance")
        or (sample or {}).get("skill_profile_distance")
        or ""
    )
    deck_bucket = (
        meta.get("deck_quality_bucket")
        if meta.get("deck_quality_bucket") is not None
        else (sample or {}).get("deck_quality_bucket")
    )
    chara_id = (
        run_context.get("single_mode_chara_id")
        or run_context.get("card_id")
        or (sample or {}).get("single_mode_chara_id")
        or (sample or {}).get("card_id")
        or ""
    )
    return "|".join([
        objective,
        f"style={_norm_slug(style)}",
        f"distance={_norm_slug(distance)}",
        f"deck_q={_safe_int(deck_bucket, 2)}",
        f"chara={_norm_slug(chara_id)}",
    ])


def _preset_objective_bucket(preset):
    meta = (preset or {}).get("learning_metadata") or {}
    explicit = meta.get("objective_bucket")
    if explicit:
        return str(explicit)
    desired = ((preset or {}).get("desired_parent_sparks") or {}).get("blue") or []
    primary = str(desired[0] or "").strip().lower() if desired else "balanced"
    primary = {"wisdom": "wit", "wiz": "wit", "intelligence": "wit"}.get(primary, primary or "balanced")
    if primary in STAT_KEYS:
        objective = f"{primary}_{primary}"
    else:
        objective = "balanced_any"
    style = (preset or {}).get("skill_profile_style") or ""
    distance = (preset or {}).get("skill_profile_distance") or ""
    run_context = (preset or {}).get("_run_context") or {}
    deck_bucket = run_context.get("deck_quality_bucket", 2)
    chara_id = run_context.get("single_mode_chara_id") or run_context.get("card_id") or ""
    return "|".join([
        objective,
        f"style={_norm_slug(style)}",
        f"distance={_norm_slug(distance)}",
        f"deck_q={_safe_int(deck_bucket, 2)}",
        f"chara={_norm_slug(chara_id)}",
    ])


def _resolve_context_targets(preset, default=None):
    run_context = (preset or {}).get("_run_context") or {}
    if not isinstance(run_context, dict):
        run_context = {}
    deck_bucket = (
        (preset or {}).get("_deck_quality_bucket")
        if (preset or {}).get("_deck_quality_bucket") is not None
        else run_context.get("deck_quality_bucket")
    )
    return resolve_expect_attribute(
        preset,
        default=default,
        run_context=run_context,
        style=(preset or {}).get("skill_profile_style") or run_context.get("skill_profile_style") or "any",
        distance=(preset or {}).get("skill_profile_distance") or run_context.get("skill_profile_distance") or "any",
        deck_quality_bucket=_safe_int(deck_bucket, 2),
        desired_parent_sparks=(preset or {}).get("desired_parent_sparks") or run_context.get("desired_parent_sparks"),
    )


def _facility_progress_value(row):
    if not isinstance(row, dict):
        return 0
    for key in ("progress", "facility_progress", "training_progress", "count"):
        if row.get(key) is None:
            continue
        return max(0, min(3, _safe_int(row.get(key))))
    for key in ("training_count", "failure_num", "total_training_count"):
        if row.get(key) is None:
            continue
        return max(0, _safe_int(row.get(key)) % 4)
    return 0


def _facility_level_info(command, chara):
    if not isinstance(command, dict) or not isinstance(chara, dict):
        return (None, None, None)
    command_id = _safe_int(command.get("command_id"))
    if not command_id:
        return (None, None, None)
    command_idx = TRAINING_COMMANDS.get(command_id)
    matched = None
    for position, row in enumerate(chara.get("training_level_info_array") or []):
        if not isinstance(row, dict):
            continue
        row_command_id = _safe_int(row.get("command_id"))
        row_idx = TRAINING_COMMANDS.get(row_command_id)
        if row_command_id == command_id:
            matched = row
            break
        if command_idx is not None and row_idx == command_idx:
            matched = row
            break
        if command_idx is not None and not row_command_id and position == command_idx:
            matched = row
            break
    if not matched:
        level = _safe_int(command.get("facility_level"), _safe_int(command.get("level"), 0))
        if level <= 0:
            return (None, None, None)
        progress = _safe_int(command.get("facility_progress"), 0)
        until_next = _safe_int(command.get("facility_until_next_level"), max(0, 4 - progress) if level < 5 else -1)
        return (max(1, min(5, level)), max(0, min(3, progress)), until_next if level < 5 else None)
    level = max(1, min(5, _safe_int(matched.get("level"), _safe_int(matched.get("facility_level"), _safe_int(command.get("level"), 1)))))
    progress = _facility_progress_value(matched)
    until_next = max(0, 4 - progress) if level < 5 else None
    return (level, progress, until_next)


def _weighted_counts(rows, row_weights, key):
    counts = Counter()
    total = 0.0
    for row, weight in zip(rows, row_weights):
        counts[row.get(key)] += weight
        total += weight
    if total <= 0:
        return {}
    return {str(k): v / total for k, v in counts.items() if k is not None}


def _nonzero_rate(rows, feature):
    rows = list(rows or [])
    if not rows:
        return 0.0
    active = sum(1 for row in rows if _safe_float((row or {}).get(feature)) > 0.0)
    return active / max(1, len(rows))


def _feature_include_reason(name, delta, top_rows, bottom_rows):
    if name in ALWAYS_INCLUDED_FEATURES:
        return "always_included"
    if abs(delta) >= 0.015:
        return "delta_threshold"
    if name in PERSISTENT_SIGNAL_FEATURES and _nonzero_rate(top_rows, name) >= 0.75:
        return "persistent_top_signal"
    return ""


def _desired_blue_indices(preset):
    desired = ((preset or {}).get("desired_parent_sparks") or {}).get("blue") or []
    if isinstance(desired, str):
        desired = desired.replace(",", "\n").splitlines()
    indices = []
    seen = set()
    for raw in desired:
        idx = BLUE_SPARK_STAT_ALIASES.get(str(raw or "").strip().lower())
        if idx is None or idx in seen:
            continue
        seen.add(idx)
        indices.append(idx)
    return indices


def _understanding_signal(action, key, default=0.0):
    understanding = (action or {}).get("decision_understanding") or {}
    if not isinstance(understanding, dict):
        return default
    signals = understanding.get("signals") or {}
    if not isinstance(signals, dict):
        return default
    return signals.get(key, default)


def _pairwise_deltas_for_action(action, preset=None):
    if not isinstance(action, dict):
        return []
    snapshot = action.get("training_snapshot") or {}
    if not isinstance(snapshot, dict):
        return []
    rows = snapshot.get("trainings") or []
    if not isinstance(rows, list) or len(rows) < 2:
        return []
    chosen_idx = _safe_int(action.get("idx"), -1)
    chosen_command_id = _safe_int(action.get("command_id"))
    chosen_row = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if _safe_int(row.get("_idx"), _safe_int(row.get("idx"), -1)) == chosen_idx and chosen_idx >= 0:
            chosen_row = row
            break
        if chosen_command_id and _safe_int(row.get("command_id")) == chosen_command_id:
            chosen_row = row
            break
    if not isinstance(chosen_row, dict):
        return []
    chosen_features = _action_features(chosen_row, preset=preset)
    if chosen_features.get("_idx", -1) < 0:
        chosen_features = _action_features(action, preset=preset)
    deltas = []
    for row in rows:
        if not isinstance(row, dict) or row is chosen_row:
            continue
        alt_features = _action_features(row, preset=preset)
        if alt_features.get("_idx", -1) < 0:
            continue
        delta_row = {}
        for name in FEATURE_NAMES:
            delta_row[name] = _safe_float(chosen_features.get(name)) - _safe_float(alt_features.get(name))
        delta_row["_idx"] = chosen_features.get("_idx", -1)
        delta_row["_period"] = chosen_features.get("_period", _safe_int(action.get("period"), 0))
        deltas.append(delta_row)
    return deltas


def apply_weight_floor_clamps(weights, *, reasons=None):
    """Apply WEIGHT_FLOOR_CLAMPS (lower bounds) and WEIGHT_CEILING_CLAMPS
    (upper bounds) to a feature_weights dict in place.

    Extracted from `_build_policy_model_from_rows` so the same clamp pass
    can be re-applied to *stale* models that get re-persisted during
    challenger staging. Without this, an old model with violating signs
    survives every learning cycle until a challenger finishes promoting,
    because `learn_preset` re-saves `active_model = old_model` during
    staging and never re-runs the clamps.

    Args:
        weights: dict mapping feature_name → numeric weight. Mutated.
        reasons: optional dict mapping feature_name → include_reason
                 string. When a clamp introduces a new feature (positive
                 floor), reasons gets "floor_clamp" recorded.

    Returns the same `weights` dict for chaining.
    """
    if not isinstance(weights, dict):
        return weights
    for name, floor in WEIGHT_FLOOR_CLAMPS.items():
        if name in weights:
            try:
                current = float(weights[name])
            except (TypeError, ValueError):
                current = 0.0
            weights[name] = round(max(float(floor), current), 5)
        elif floor > 0:
            weights[name] = round(float(floor), 5)
            if isinstance(reasons, dict):
                reasons.setdefault(name, "floor_clamp")
    for name, ceiling in WEIGHT_CEILING_CLAMPS.items():
        if name in weights:
            try:
                current = float(weights[name])
            except (TypeError, ValueError):
                current = 0.0
            weights[name] = round(min(float(ceiling), current), 5)
        elif ceiling < 0:
            weights[name] = round(float(ceiling), 5)
            if isinstance(reasons, dict):
                reasons.setdefault(name, "ceiling_clamp")
    return weights


def enforce_model_floors(model):
    """Re-apply weight clamps to a full policy_model dict.

    Defensive guardrail for the persistence boundary. Call this on any
    model before saving it back to the preset — including the OLD model
    that survives challenger staging. Ensures the clamp invariants hold
    no matter how the model object was assembled.

    Args:
        model: the full training_policy_model dict (or empty/None).

    Returns the same dict with `feature_weights` clamped in place.
    """
    if not isinstance(model, dict):
        return model
    weights = model.get("feature_weights")
    if not isinstance(weights, dict):
        return model
    reasons = model.get("feature_include_reasons")
    apply_weight_floor_clamps(weights, reasons=reasons if isinstance(reasons, dict) else None)
    return model


def _build_policy_model_from_rows(top_rows, top_weights, bottom_rows, bottom_weights, sample_count, total_action_count, min_actions=12, top_pairwise=None, top_pairwise_weights=None, bottom_pairwise=None, bottom_pairwise_weights=None):
    if total_action_count < min_actions or not top_rows or not bottom_rows:
        return {
            "schema": "sweepy_training_policy_v1",
            "enabled": False,
            "reason": "not_enough_action_samples",
            "sample_count": sample_count,
            "action_count": total_action_count,
            "min_actions": min_actions,
        }

    weights = {}
    feature_include_reasons = {}
    for name in FEATURE_NAMES:
        delta = _weighted_average(top_rows, top_weights, name) - _weighted_average(bottom_rows, bottom_weights, name)
        if top_pairwise and bottom_pairwise:
            pairwise_delta = _weighted_average(top_pairwise, top_pairwise_weights or [], name) - _weighted_average(bottom_pairwise, bottom_pairwise_weights or [], name)
            delta += pairwise_delta * 0.65
        include_reason = _feature_include_reason(name, delta, top_rows, bottom_rows)
        if include_reason:
            weights[name] = round(_clamp(delta * 0.18, -0.16, 0.16), 5)
            feature_include_reasons[name] = include_reason
    apply_weight_floor_clamps(weights, reasons=feature_include_reasons)

    top_cmd = _weighted_counts(top_rows, top_weights, "_idx")
    bottom_cmd = _weighted_counts(bottom_rows, bottom_weights, "_idx")
    command_bias = {}
    for idx in range(5):
        delta = top_cmd.get(str(idx), 0.0) - bottom_cmd.get(str(idx), 0.0)
        if abs(delta) >= 0.02:
            command_bias[str(idx)] = round(_clamp(delta * 0.16, -0.10, 0.10), 5)

    period_command_bias = {}
    for period in range(5):
        top_period_rows = [row for row in top_rows if row.get("_period") == period]
        bottom_period_rows = [row for row in bottom_rows if row.get("_period") == period]
        if len(top_period_rows) + len(bottom_period_rows) < 4:
            continue
        top_period_counts = Counter(row.get("_idx") for row in top_period_rows)
        bottom_period_counts = Counter(row.get("_idx") for row in bottom_period_rows)
        top_total = sum(top_period_counts.values()) or 1
        bottom_total = sum(bottom_period_counts.values()) or 1
        row = {}
        for idx in range(5):
            delta = (top_period_counts[idx] / top_total) - (bottom_period_counts[idx] / bottom_total)
            if abs(delta) >= 0.08:
                row[str(idx)] = round(_clamp(delta * 0.08, -0.06, 0.06), 5)
        if row:
            period_command_bias[str(period)] = row

    confidence = _clamp(math.sqrt(total_action_count / 200.0), 0.15, 1.0)
    return {
        "schema": "sweepy_training_policy_v1",
        "enabled": True,
        "sample_count": sample_count,
        "action_count": total_action_count,
        "pairwise_preference_count": len(top_pairwise or []) + len(bottom_pairwise or []),
        "top_action_count": len(top_rows),
        "bottom_action_count": len(bottom_rows),
        "confidence": round(confidence, 4),
        "max_abs_bonus": round(0.06 + confidence * 0.08, 4),
        "feature_weights": weights,
        "feature_include_reasons": feature_include_reasons,
        "command_bias": command_bias,
        "period_command_bias": period_command_bias,
    }


def _action_features(action, preset=None):
    turn = _safe_int(action.get("turn"))
    period = _period_index(turn)
    extra_phase = _extra_phase_index(turn)
    weighted_gain = _safe_float(action.get("weighted_gain"))
    stat_gain = sum(
        max(0.0, _safe_float(value))
        for key, value in (action.get("stat_gain") or {}).items()
        if str(key) not in {"hp", "skill_point"}
    )
    if stat_gain <= 0:
        stat_gain = weighted_gain
    skill_point = _safe_float(action.get("skill_point"))
    hp = _safe_float(action.get("hp"))
    blue_goal_training = 1.0 if _understanding_signal(action, "blue_target_match", False) else 0.0
    race_demand_pressure = _clamp(_safe_float(_understanding_signal(action, "race_pressure_bonus")) / 0.12, 0.0, 2.0)
    rainbow_setup_pressure = _clamp(
        max(
            _safe_float(_understanding_signal(action, "near_rainbow_count")) / 3.0,
            _safe_float(_understanding_signal(action, "near_rainbow_bonus")) / 0.12,
        ),
        0.0,
        2.0,
    )
    current_unlocked = _safe_float(_understanding_signal(action, "current_rainbow_unlocked_count"))
    target_unlocked = _safe_float(_understanding_signal(action, "target_rainbow_unlocked_count"))
    friendship_unlocked_gap = _clamp(max(0.0, target_unlocked - current_unlocked) / 4.0, 0.0, 2.0)
    first_summer_friendship_pressure = _clamp(
        max(
            _safe_float(_understanding_signal(action, "first_summer_friendship_bonus")) / 0.24,
            friendship_unlocked_gap,
        ),
        0.0,
        2.0,
    )
    lagging_stat_alignment = 1.0 if _understanding_signal(action, "lagging_for_selected_stat", False) else 0.0
    late_white_pressure = _clamp(
        max(0.0, _safe_float(_understanding_signal(action, "late_white_pressure_multiplier"), 1.0) - 1.0) / 0.08,
        0.0,
        2.0,
    )
    facility_level = _safe_float(action.get("facility_level"), _safe_float(_understanding_signal(action, "facility_level")))
    facility_progress = _safe_float(action.get("facility_progress"), _safe_float(_understanding_signal(action, "facility_progress")))
    facility_until_next = _safe_int(
        action.get("facility_until_next_level"),
        _safe_int(_understanding_signal(action, "facility_until_next_level"), -1),
    )
    return {
        "turn_progress": _clamp(turn / 78.0, 0.0, 1.0),
        "early_phase": 1.0 if period <= 1 else 0.0,
        "mid_phase": 1.0 if period == 2 else 0.0,
        "late_phase": 1.0 if period >= 3 else 0.0,
        "summer_phase": 1.0 if extra_phase == 3 else 0.0,
        "weighted_gain": _clamp(weighted_gain / 80.0, 0.0, 2.0),
        "stat_gain": _clamp(stat_gain / 80.0, 0.0, 2.0),
        "skill_point_gain": 0.0,
        "energy_delta": 0.0,
        "failure_rate": _clamp(_safe_float(action.get("failure_rate")) / 100.0, 0.0, 1.0),
        "partner_count": _clamp(_safe_float(action.get("partner_count")) / 6.0, 0.0, 2.0),
        "deck_partner_count": _clamp(_safe_float(action.get("deck_partner_count")) / 6.0, 0.0, 2.0),
        "rainbow_count": _clamp(_safe_float(action.get("rainbow_count")) / 3.0, 0.0, 2.0),
        "hint_count": _clamp(_safe_float(action.get("hint_count")) / 3.0, 0.0, 2.0),
        "high_bond_count": _clamp(_safe_float(action.get("high_bond_count")) / 6.0, 0.0, 2.0),
        "hp_ratio": _clamp(hp / 100.0, 0.0, 1.5),
        "low_hp": _clamp((50.0 - hp) / 50.0, 0.0, 1.0),
        "under_target": 0.0,
        "over_target": 0.0,
        "blue_goal_training": blue_goal_training,
        "race_demand_pressure": race_demand_pressure,
        "rainbow_setup_pressure": rainbow_setup_pressure,
        "first_summer_friendship_pressure": first_summer_friendship_pressure,
        "facility_level": _clamp(facility_level / 5.0, 0.0, 1.0),
        "facility_progress": _clamp(facility_progress / 4.0, 0.0, 1.0),
        "facility_levelup_next_train": 1.0 if facility_until_next == 1 else 0.0,
        "facility_is_max_level": 1.0 if facility_level >= 5 else 0.0,
        "friendship_unlocked_gap": friendship_unlocked_gap,
        "lagging_stat_alignment": lagging_stat_alignment,
        "late_white_pressure": late_white_pressure,
        "_idx": _safe_int(action.get("idx"), -1),
        "_period": period,
    }


def command_features(command, chara, preset=None):
    preset = preset or {}
    turn = _safe_int(chara.get("turn"))
    period = _period_index(turn)
    extra_phase = _extra_phase_index(turn)
    idx = TRAINING_COMMANDS.get(command.get("command_id"), -1)
    vital = _safe_float(chara.get("vital"))
    max_vital = max(1.0, _safe_float(chara.get("max_vital"), 100.0))
    bonds = {row.get("target_id", 0): _safe_int(row.get("evaluation")) for row in chara.get("evaluation_info_array") or []}
    partners = list(command.get("training_partner_array") or [])
    hints = set(command.get("tips_event_partner_array") or [])
    stat_gain = 0.0
    skill_point_gain = 0.0
    energy_delta = 0.0
    weighted_gain = 0.0
    main_target = idx
    stat_gain_by_idx = {}
    for item in command.get("params_inc_dec_info_array") or []:
        value = _safe_float(item.get("value"))
        target_type = item.get("target_type")
        if target_type == 10:
            energy_delta += value
            weighted_gain += value * 0.15
            continue
        target = STAT_TARGETS.get(target_type)
        if target is None:
            continue
        if target == 5:
            skill_point_gain += max(0.0, value)
            weighted_gain += max(0.0, value) * 0.5
        elif 0 <= target < 5:
            stat_gain += max(0.0, value)
            weighted_gain += max(0.0, value)
            stat_gain_by_idx[target] = stat_gain_by_idx.get(target, 0.0) + max(0.0, value)
            main_target = target
    targets = _resolve_context_targets(preset, default=[0, 0, 0, 0, 0])
    target_cap = _safe_float(targets[main_target] if 0 <= main_target < len(targets) else 0.0)
    current = _safe_float(chara.get(STAT_KEYS[main_target] if 0 <= main_target < len(STAT_KEYS) else ""))
    if target_cap > 0:
        under_target = _clamp((target_cap - current) / target_cap, 0.0, 1.0)
        over_target = _clamp((current - target_cap) / target_cap, 0.0, 1.0)
    else:
        under_target = 0.0
        over_target = 0.0
    high_bond_count = sum(1 for partner_id in partners if bonds.get(partner_id, 0) >= 80)
    # Pre-rainbow partners: bond in [60, 79]. Training them now is
    # high-value not just for this turn's stat gain but because they're
    # one or two trainings away from crossing 80 bond, at which point
    # ALL future trainings with them benefit from the rainbow bonus.
    # The learner will assign this feature its own weight; mant.py also
    # applies a direct bonus so the bot benefits immediately without
    # waiting for the model to re-converge.
    near_rainbow_count = sum(
        1 for partner_id in partners
        if 60 <= bonds.get(partner_id, 0) < 80
    )
    near_rainbow_deck_count = sum(
        1 for partner_id in partners
        if partner_id in DECK_PARTNERS and 60 <= bonds.get(partner_id, 0) < 80
    )
    blue_goal_training = 0.0
    desired_blue = _desired_blue_indices(preset)
    if desired_blue:
        blue_gain = max((_safe_float(stat_gain_by_idx.get(target)) for target in desired_blue), default=0.0)
        blue_goal_training = _clamp(blue_gain / 18.0, 0.0, 2.0) if blue_gain > 0 else 0.0
    race_demand_pressure = _clamp(
        (_safe_float(command.get("_postmortem_training_bonus")) + _safe_float(command.get("_race_success_training_bonus"))) / 0.12,
        0.0,
        2.0,
    )
    rainbow_setup_pressure = _clamp(
        max(
            near_rainbow_count / 3.0,
            _safe_float(command.get("_near_rainbow_bonus")) / 0.12,
        ),
        0.0,
        2.0,
    )
    current_unlocked = sum(1 for partner_id in DECK_PARTNERS if bonds.get(partner_id, 0) >= 80)
    target_unlocked = _first_summer_target_for_turn(turn, preset)
    friendship_unlocked_gap = _clamp(max(0.0, target_unlocked - current_unlocked) / 4.0, 0.0, 2.0)
    first_summer_friendship_pressure = _clamp(
        max(
            _safe_float(command.get("_first_summer_friendship_bonus")) / 0.24,
            friendship_unlocked_gap,
        ),
        0.0,
        2.0,
    )
    if target_cap > 0:
        progress = _clamp(turn / 78.0, 0.25, 1.0)
        expected_now = target_cap * progress
        lagging_stat_alignment = _clamp((expected_now - current) / max(1.0, expected_now), 0.0, 1.0)
    else:
        lagging_stat_alignment = 0.0
    late_white_pressure = _clamp(
        max(0.0, _safe_float(command.get("_desired_parent_spark_training_multiplier"), 1.0) - 1.0) / 0.08,
        0.0,
        2.0,
    )
    facility_level, facility_progress, facility_until_next = _facility_level_info(command, chara)
    facility_level_value = _safe_float(facility_level)
    facility_progress_value = _safe_float(facility_progress)
    return {
        "turn_progress": _clamp(turn / 78.0, 0.0, 1.0),
        "early_phase": 1.0 if period <= 1 else 0.0,
        "mid_phase": 1.0 if period == 2 else 0.0,
        "late_phase": 1.0 if period >= 3 else 0.0,
        "summer_phase": 1.0 if extra_phase == 3 else 0.0,
        "weighted_gain": _clamp(weighted_gain / 80.0, 0.0, 2.0),
        "stat_gain": _clamp(stat_gain / 80.0, 0.0, 2.0),
        "skill_point_gain": _clamp(skill_point_gain / 30.0, 0.0, 2.0),
        "energy_delta": _clamp(energy_delta / 30.0, -2.0, 2.0),
        "failure_rate": _clamp(_safe_float(command.get("failure_rate")) / 100.0, 0.0, 1.0),
        "partner_count": _clamp(len(partners) / 6.0, 0.0, 2.0),
        "deck_partner_count": _clamp(sum(1 for partner_id in partners if partner_id in DECK_PARTNERS) / 6.0, 0.0, 2.0),
        "rainbow_count": _clamp(sum(1 for partner_id in partners if partner_id in DECK_PARTNERS and bonds.get(partner_id, 0) >= 80) / 3.0, 0.0, 2.0),
        "near_rainbow_count": _clamp(near_rainbow_count / 3.0, 0.0, 2.0),
        "near_rainbow_deck_count": _clamp(near_rainbow_deck_count / 3.0, 0.0, 2.0),
        "hint_count": _clamp(sum(1 for partner_id in partners if partner_id in hints) / 3.0, 0.0, 2.0),
        "high_bond_count": _clamp(high_bond_count / 6.0, 0.0, 2.0),
        "hp_ratio": _clamp(vital / max_vital, 0.0, 1.5),
        "low_hp": _clamp((50.0 - vital) / 50.0, 0.0, 1.0),
        "under_target": under_target,
        "over_target": over_target,
        "blue_goal_training": blue_goal_training,
        "race_demand_pressure": race_demand_pressure,
        "rainbow_setup_pressure": rainbow_setup_pressure,
        "first_summer_friendship_pressure": first_summer_friendship_pressure,
        "facility_level": _clamp(facility_level_value / 5.0, 0.0, 1.0),
        "facility_progress": _clamp(facility_progress_value / 4.0, 0.0, 1.0),
        "facility_levelup_next_train": 1.0 if facility_until_next == 1 else 0.0,
        "facility_is_max_level": 1.0 if facility_level_value >= 5 else 0.0,
        "friendship_unlocked_gap": friendship_unlocked_gap,
        "lagging_stat_alignment": lagging_stat_alignment,
        "late_white_pressure": late_white_pressure,
        "_idx": idx,
        "_period": period,
    }


def build_training_policy_model(top_samples, bottom_samples, all_samples, min_actions=12):
    top_rows = []
    top_weights = []
    bottom_rows = []
    bottom_weights = []
    top_pairwise = []
    top_pairwise_weights = []
    bottom_pairwise = []
    bottom_pairwise_weights = []
    bucket_rows = {}
    all_action_count = 0
    for sample, target_rows, target_weights in [
        *[(sample, top_rows, top_weights) for sample in top_samples or []],
        *[(sample, bottom_rows, bottom_weights) for sample in bottom_samples or []],
    ]:
        bucket_key = _sample_objective_bucket(sample)
        for action in sample.get("actions") or []:
            row = _action_features(action)
            if row.get("_idx", -1) < 0:
                continue
            weight = _action_weight(sample, action)
            target_rows.append(row)
            target_weights.append(weight)
            pairwise_rows = _pairwise_deltas_for_action(action)
            pairwise_target_rows = top_pairwise if target_rows is top_rows else bottom_pairwise
            pairwise_target_weights = top_pairwise_weights if target_rows is top_rows else bottom_pairwise_weights
            for pairwise_row in pairwise_rows:
                pairwise_target_rows.append(pairwise_row)
                pairwise_target_weights.append(weight)
            bucket = bucket_rows.setdefault(
                bucket_key,
                {
                    "top_rows": [],
                    "top_weights": [],
                    "bottom_rows": [],
                    "bottom_weights": [],
                    "top_pairwise": [],
                    "top_pairwise_weights": [],
                    "bottom_pairwise": [],
                    "bottom_pairwise_weights": [],
                    "sample_count": 0,
                },
            )
            if target_rows is top_rows:
                bucket["top_rows"].append(row)
                bucket["top_weights"].append(weight)
                for pairwise_row in pairwise_rows:
                    bucket["top_pairwise"].append(pairwise_row)
                    bucket["top_pairwise_weights"].append(weight)
            else:
                bucket["bottom_rows"].append(row)
                bucket["bottom_weights"].append(weight)
                for pairwise_row in pairwise_rows:
                    bucket["bottom_pairwise"].append(pairwise_row)
                    bucket["bottom_pairwise_weights"].append(weight)
            bucket["sample_count"] += 1
            all_action_count += 1
    total_action_count = sum(len(sample.get("actions") or []) for sample in all_samples or [])
    model = _build_policy_model_from_rows(
        top_rows,
        top_weights,
        bottom_rows,
        bottom_weights,
        sample_count=len(all_samples or []),
        total_action_count=total_action_count,
        min_actions=min_actions,
        top_pairwise=top_pairwise,
        top_pairwise_weights=top_pairwise_weights,
        bottom_pairwise=bottom_pairwise,
        bottom_pairwise_weights=bottom_pairwise_weights,
    )
    if not model.get("enabled"):
        return model
    bucket_models = {}
    for bucket_key, bucket in bucket_rows.items():
        bucket_model = _build_policy_model_from_rows(
            bucket.get("top_rows") or [],
            bucket.get("top_weights") or [],
            bucket.get("bottom_rows") or [],
            bucket.get("bottom_weights") or [],
            sample_count=int(bucket.get("sample_count") or 0),
            total_action_count=len(bucket.get("top_rows") or []) + len(bucket.get("bottom_rows") or []),
            min_actions=max(8, min_actions // 2),
            top_pairwise=bucket.get("top_pairwise") or [],
            top_pairwise_weights=bucket.get("top_pairwise_weights") or [],
            bottom_pairwise=bucket.get("bottom_pairwise") or [],
            bottom_pairwise_weights=bucket.get("bottom_pairwise_weights") or [],
        )
        if bucket_model.get("enabled"):
            bucket_models[bucket_key] = bucket_model
    if bucket_models:
        model["bucket_models"] = bucket_models
        model["available_objective_buckets"] = sorted(bucket_models)
    return model


def score_training_policy_bonus(command, data, chara, preset):
    if not preset or not preset.get("training_policy_model_enabled", False):
        return 0.0
    if not _policy_metadata_is_trusted(preset):
        return 0.0
    model = preset.get("training_policy_model") or {}
    if not isinstance(model, dict) or not model.get("enabled"):
        return 0.0
    bucket_models = model.get("bucket_models") or {}
    if isinstance(bucket_models, dict):
        bucket_model = bucket_models.get(_preset_objective_bucket(preset))
        if isinstance(bucket_model, dict) and bucket_model.get("enabled"):
            model = bucket_model
        elif bucket_models:
            # Do not apply a global model from another deck/objective bucket.
            # That makes deck swaps brittle: a model trained on old top samples
            # can override the current deck before it has produced its own
            # positives. Wait for the current bucket to earn a trusted model.
            return 0.0
    idx = TRAINING_COMMANDS.get(command.get("command_id"), -1)
    if idx < 0:
        return 0.0
    features = command_features(command, chara, preset)
    score = 0.0
    for name, weight in (model.get("feature_weights") or {}).items():
        score += _safe_float(weight) * _safe_float(features.get(name))
    score += _safe_float((model.get("command_bias") or {}).get(str(idx)))
    period_bias = (model.get("period_command_bias") or {}).get(str(features.get("_period"))) or {}
    score += _safe_float(period_bias.get(str(idx)))
    model_cap = _safe_float(model.get("max_abs_bonus"), 0.12)
    preset_cap = _safe_float(preset.get("training_policy_model_max_bonus"), model_cap)
    runtime_cap = _safe_float(preset.get("training_policy_model_runtime_cap"), 0.05)
    cap = _clamp(min(model_cap, preset_cap, runtime_cap), 0.0, 0.08)
    weight = _safe_float(preset.get("training_policy_model_weight"), 0.35)
    return round(_clamp(score, -cap, cap) * _clamp(weight, 0.0, 0.75), 5)
