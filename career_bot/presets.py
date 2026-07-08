import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path


EXCLUDED_KEYS = {
    "facility_period_configs",
    "facility_ratios",
}

RENAMES = {
    "race_list": "extra_race_list",
    "skill_priority_list": "learn_skill_list",
    "skill_blacklist": "learn_skill_blacklist",
    "blacklistedSkills": "learn_skill_blacklist",
    "extraWeight": "extra_weight",
    "scoreValue": "score_value",
    "baseScore": "base_score",
    "statValueMultiplier": "stat_value_multiplier",
    "witSpecialMultiplier": "wit_special_multiplier",
    "cureAsapConditions": "cure_asap_conditions",
}

MANT_SCENARIO_ID = 4
EXPECT_ATTRIBUTE_DEFAULT = [1100, 700, 950, 600, 800]
CONFIG_ONLY_KEYS = {
    # Operator intent. Learning/model/instance override layers may observe
    # these values, but must not own them or stale overrides can silently
    # erase the user's active farming goal.
    "skill_buy_on_sight",
    "skill_profile_style",
    "skill_profile_distance",
    "skill_blacklist_custom",
    "learn_skill_blacklist",
    "learn_skill_list",
    "learn_skill_only_user_provided",
    "learn_skill_append_defaults",
    "manual_purchase_at_end",
    "desired_parent_sparks",
    # Race agenda is explicit user routing. Account-local learning/tuning
    # layers are allowed to learn from the route, but must never replace the
    # currently-loaded calendar with an older one.
    "race_plan_text",
    "custom_race_schedule",
    "extra_race_list",
    "race_list",
}
BLUE_SPARK_STAT_ALIASES = {
    "speed": "speed",
    "stamina": "stamina",
    "power": "power",
    "guts": "guts",
    "wit": "wit",
    "wisdom": "wit",
    "wiz": "wit",
    "intelligence": "wit",
}
SUPPORT_TYPE_ALIASES = {
    "speed": "speed",
    "stamina": "stamina",
    "power": "power",
    "guts": "guts",
    "wit": "wit",
    "wisdom": "wit",
    "wiz": "wit",
    "int": "wit",
    "intelligence": "wit",
    "pal": "pal",
    "friend": "pal",
    "friends": "pal",
    "group": "group",
}
SUPPORT_TYPE_ORDER = ("speed", "stamina", "power", "guts", "wit", "pal", "group")
POLICY_MODEL_KEYS = {
    "training_policy_model",
    "training_policy_challenger",
    "training_policy_validation",
}
RUNTIME_STATE_KEYS = {
    "_run_context",
    "_deck_multipliers",
    "_deck_type_counts",
    "_deck_type_counts_source",
    "_loop_mode",
}


def default_parent_farming_rules():
    return {
        "server": "global",
        "compatibility_system": "legacy",
        "compatibility_rules": {
            "overlap_win_grades": ["G1", "G2", "G3"],
            "same_race_duplicate_bonus": False,
            "title_epithet_bonus": True,
            "lineage_depth_limit": "parents_and_grandparents",
        },
    }


def slugify(value):
    text = re.sub(r"[^a-zA-Z0-9._ -]+", "", str(value or "").strip())
    text = re.sub(r"\s+", " ", text).strip()
    return text or "preset"


def preset_family_for(preset_or_name):
    if isinstance(preset_or_name, dict):
        family = str(preset_or_name.get("preset_family") or "").strip()
        if family:
            return slugify(family)
        name = preset_or_name.get("name")
    else:
        name = preset_or_name
    return slugify(name)


def split_preset_layers(preset, *, instance_override=False):
    """Split a legacy all-in-one preset into Phase 7 concern layers.

    The split is intentionally conservative: user-facing keys stay in config;
    transient underscore/runtime keys leave the config; policy-model keys leave
    the config. Instance overrides keep non-config learned values in the
    override layer so account-specific learning can still win at merge time.
    """
    data = dict(preset or {})
    name = str(data.get("name") or "").strip() or "preset"
    family = preset_family_for(data)
    config = {"name": name, "preset_family": family}
    runtime = {}
    model = {}
    overrides = {}
    for key, value in data.items():
        if key in POLICY_MODEL_KEYS:
            model[key] = value
            if instance_override:
                overrides[key] = value
            continue
        if key in RUNTIME_STATE_KEYS or str(key).startswith("_"):
            runtime[key] = value
            continue
        if instance_override and key not in {"name", "preset_family"}:
            if key in CONFIG_ONLY_KEYS:
                continue
            overrides[key] = value
            continue
        config[key] = value
    config["name"] = name
    config["preset_family"] = family
    return {
        "config": config,
        "runtime": runtime,
        "model": model,
        "overrides": overrides,
        "family": family,
    }


def merge_preset_layers(config=None, runtime=None, model=None, overrides=None):
    merged = dict(config or {})
    for layer in (runtime or {}, model or {}, overrides or {}):
        if isinstance(layer, dict):
            merged.update(layer)
    return merged


def _safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _norm_slug(value, default="any"):
    text = str(value or "").strip().lower()
    if not text:
        return default
    return "".join(ch if ch.isalnum() else "_" for ch in text).strip("_") or default


def normalize_expect_attribute_vector(value, default=None):
    fallback = list(default or EXPECT_ATTRIBUTE_DEFAULT)
    if len(fallback) < 5:
        fallback.extend([EXPECT_ATTRIBUTE_DEFAULT[idx] for idx in range(len(fallback), 5)])
    result = []
    rows = value if isinstance(value, list) else []
    for idx in range(5):
        base = fallback[idx] if idx < len(fallback) else EXPECT_ATTRIBUTE_DEFAULT[idx]
        try:
            result.append(int(round(float(rows[idx]))))
        except (TypeError, ValueError, IndexError):
            result.append(int(base))
    return result


def normalize_expect_attribute_profiles(value):
    profiles = {}
    if not isinstance(value, dict):
        return profiles
    for raw_key, raw_entry in value.items():
        key = str(raw_key or "").strip()
        if not key:
            continue
        vector = None
        entry = {}
        if isinstance(raw_entry, dict):
            vector = raw_entry.get("expect_attribute")
            sample_count = raw_entry.get("sample_count")
            top_sample_count = raw_entry.get("top_sample_count")
            if sample_count is not None:
                entry["sample_count"] = _safe_int(sample_count)
            if top_sample_count is not None:
                entry["top_sample_count"] = _safe_int(top_sample_count)
        elif isinstance(raw_entry, list):
            vector = raw_entry
        if not isinstance(vector, list) or len(vector) != 5:
            continue
        entry["expect_attribute"] = normalize_expect_attribute_vector(vector)
        profiles[key] = entry
    return profiles


def _primary_expect_objective(session=None, desired_parent_sparks=None):
    if isinstance(session, dict):
        try:
            from career_bot.objectives import objective_bucket_key

            objective = str(objective_bucket_key(session) or "").strip()
        except Exception:
            objective = ""
        if objective:
            return objective
    desired = ((desired_parent_sparks or {}).get("blue") or []) if isinstance(desired_parent_sparks, dict) else []
    if isinstance(desired, str):
        desired = desired.replace(",", "\n").splitlines()
    primary = BLUE_SPARK_STAT_ALIASES.get(str(desired[0] or "").strip().lower()) if desired else ""
    if primary:
        return f"{primary}_{primary}"
    return "balanced_any"


def support_type_signature(cards):
    counts = {}
    for row in cards or []:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("type") or row.get("support_type") or "").strip().lower()
        key = SUPPORT_TYPE_ALIASES.get(raw, _norm_slug(raw, default="unknown"))
        if not key:
            continue
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return "any"
    parts = []
    for key in SUPPORT_TYPE_ORDER:
        count = counts.pop(key, 0)
        if count:
            parts.append(f"{key}{count}")
    for key in sorted(counts):
        parts.append(f"{key}{counts[key]}")
    return "_".join(parts) or "any"


def _support_type_counts_from_preset(preset):
    counts = dict.fromkeys(("speed", "stamina", "power", "guts", "wit", "pal", "group"), 0)

    raw_counts = (preset or {}).get("_deck_type_counts")
    if isinstance(raw_counts, list):
        for idx, key in enumerate(("speed", "stamina", "power", "guts", "wit")):
            try:
                counts[key] = max(0, int(raw_counts[idx] if idx < len(raw_counts) else 0))
            except (TypeError, ValueError):
                counts[key] = 0

    run_context = (preset or {}).get("_run_context") if isinstance((preset or {}).get("_run_context"), dict) else {}
    cards = []
    cards.extend((preset or {}).get("support_cards") or [])
    cards.extend(run_context.get("support_cards") or [])
    for row in cards:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("type") or row.get("support_type") or "").strip().lower()
        key = SUPPORT_TYPE_ALIASES.get(raw, _norm_slug(raw, default="unknown"))
        if key in counts:
            counts[key] = counts.get(key, 0) + 1

    # If both `_deck_type_counts` and full card rows exist, the latter may
    # double-count. Prefer the explicit numeric counts for the five training
    # stats whenever they were present.
    if isinstance(raw_counts, list):
        for idx, key in enumerate(("speed", "stamina", "power", "guts", "wit")):
            try:
                counts[key] = max(0, int(raw_counts[idx] if idx < len(raw_counts) else 0))
            except (TypeError, ValueError):
                pass
    return counts


def _desired_blue_stat_names(preset):
    goals = (preset or {}).get("desired_parent_sparks") or {}
    raw = goals.get("blue") if isinstance(goals, dict) else []
    if isinstance(raw, str):
        raw = raw.replace(",", "\n").splitlines()
    result = set()
    for item in raw or []:
        key = BLUE_SPARK_STAT_ALIASES.get(str(item or "").strip().lower())
        if key:
            result.add(key)
    return result


def _apply_adaptive_policy_hygiene(normalized):
    """Keep learned policy layers from disabling core deck fundamentals.

    Auto-learning should tune within sane bounds, not learn "support cards are
    worth zero" from a small or stale sample set. Those zero/negative learned
    values are especially toxic after a deck swap because the new deck needs
    bond/rainbow setup before it can produce high ranks.
    """
    counts = _support_type_counts_from_preset(normalized)
    blue_stats = _desired_blue_stat_names(normalized)

    # Support/bond valuation floors. Applies even without deck metadata
    # because every real deck needs bond and rainbow setup.
    for row in normalized.get("score_value") or []:
        if not isinstance(row, list) or len(row) < 4:
            continue
        row[0] = round(max(float(row[0] or 0.0), 0.055), 4)
        row[1] = round(max(float(row[1] or 0.0), 0.060), 4)
        row[3] = round(max(float(row[3] or 0.0), 0.035), 4)

    stat_order = ("speed", "stamina", "power", "guts", "wit")
    stat_mult_floors = {
        "speed": 0.035 if counts.get("speed", 0) >= 2 else 0.026,
        "power": 0.030 if counts.get("power", 0) >= 1 else 0.020,
        "wit": 0.035 if counts.get("wit", 0) >= 2 else 0.022,
    }
    for stat in blue_stats:
        stat_mult_floors[stat] = max(stat_mult_floors.get(stat, 0.0), 0.030)
    mult = normalized.get("stat_value_multiplier") or []
    for idx, stat in enumerate(stat_order):
        floor = stat_mult_floors.get(stat)
        if floor is not None and idx < len(mult):
            mult[idx] = round(max(float(mult[idx] or 0.0), floor), 5)

    # Don't let stale learned matrices penalize the lanes the current deck is
    # explicitly built around.
    protected_stats = set(blue_stats)
    protected_stats.add("speed")
    if counts.get("speed", 0) >= 2:
        protected_stats.add("speed")
    if counts.get("wit", 0) >= 2:
        protected_stats.add("wit")
    if counts.get("power", 0) >= 1:
        protected_stats.add("power")
    protected_indices = {idx for idx, stat in enumerate(stat_order) if stat in protected_stats}
    for row in normalized.get("extra_weight") or []:
        if not isinstance(row, list):
            continue
        for idx in protected_indices:
            if idx < len(row):
                row[idx] = round(max(float(row[idx] or 0.0), -0.02), 4)

    base = normalized.get("base_score") or []
    for idx in protected_indices:
        if idx < len(base):
            base[idx] = round(max(float(base[idx] or 0.0), -0.02), 4)

    # Learned profile targets can overfit to a previous deck. If the current
    # deck has no support for a stat and the user did not ask for that blue
    # spark, don't let that stat become a fake 1100+ target.
    expect = normalized.get("expect_attribute") or []
    unsupported_caps = {"stamina": 900, "guts": 800}
    for idx, stat in enumerate(stat_order):
        if idx >= len(expect) or stat in blue_stats:
            continue
        if counts.get(stat, 0) <= 0 and stat in unsupported_caps:
            try:
                expect[idx] = min(int(expect[idx]), unsupported_caps[stat])
            except (TypeError, ValueError):
                pass
    return normalized


def _expect_attribute_profile_context(
    preset=None,
    *,
    session=None,
    run_context=None,
    desired_parent_sparks=None,
    style=None,
    distance=None,
    deck_quality_bucket=None,
):
    preset = preset or {}
    run_context = run_context if isinstance(run_context, dict) else {}
    goals = desired_parent_sparks if isinstance(desired_parent_sparks, dict) else (preset.get("desired_parent_sparks") or {})
    style_value = (
        style
        or (session or {}).get("style_target")
        or run_context.get("skill_profile_style")
        or preset.get("skill_profile_style")
        or ""
    )
    distance_value = (
        distance
        or run_context.get("skill_profile_distance")
        or preset.get("skill_profile_distance")
        or ""
    )
    deck_bucket = deck_quality_bucket
    if deck_bucket is None:
        deck_bucket = run_context.get("deck_quality_bucket")
    cards = run_context.get("support_cards") or []
    return {
        "objective": _primary_expect_objective(session=session, desired_parent_sparks=goals),
        "style": _norm_slug(style_value),
        "distance": _norm_slug(distance_value),
        "deck_quality_bucket": _safe_int(deck_bucket, 2),
        "deck_signature": support_type_signature(cards),
    }


def expect_attribute_profile_primary_key(
    preset=None,
    *,
    session=None,
    run_context=None,
    desired_parent_sparks=None,
    style=None,
    distance=None,
    deck_quality_bucket=None,
):
    ctx = _expect_attribute_profile_context(
        preset,
        session=session,
        run_context=run_context,
        desired_parent_sparks=desired_parent_sparks,
        style=style,
        distance=distance,
        deck_quality_bucket=deck_quality_bucket,
    )
    return "|".join(
        [
            ctx["objective"],
            f"style={ctx['style']}",
            f"distance={ctx['distance']}",
            f"deck={ctx['deck_signature']}",
        ]
    )


def expect_attribute_profile_lookup_keys(
    preset=None,
    *,
    session=None,
    run_context=None,
    desired_parent_sparks=None,
    style=None,
    distance=None,
    deck_quality_bucket=None,
):
    ctx = _expect_attribute_profile_context(
        preset,
        session=session,
        run_context=run_context,
        desired_parent_sparks=desired_parent_sparks,
        style=style,
        distance=distance,
        deck_quality_bucket=deck_quality_bucket,
    )
    style_part = f"style={ctx['style']}"
    distance_part = f"distance={ctx['distance']}"
    any_style_part = "style=any"
    any_distance_part = "distance=any"
    objective = ctx["objective"]
    deck_signature = ctx["deck_signature"]
    deck_bucket = ctx["deck_quality_bucket"]
    keys = []
    for sp, dp in (
        (style_part, distance_part),
        (style_part, any_distance_part),
        (any_style_part, distance_part),
        (any_style_part, any_distance_part),
    ):
        keys.extend(
            [
                f"{objective}|{sp}|{dp}|deck={deck_signature}",
                f"{objective}|{sp}|{dp}|deck_q={deck_bucket}",
                f"{objective}|{sp}|{dp}|deck=any",
                f"{objective}|{sp}|{dp}",
            ]
        )
    keys.append(objective)
    if objective != "balanced_any":
        for sp, dp in (
            (style_part, distance_part),
            (style_part, any_distance_part),
            (any_style_part, distance_part),
            (any_style_part, any_distance_part),
        ):
            keys.extend(
                [
                    f"balanced_any|{sp}|{dp}|deck={deck_signature}",
                    f"balanced_any|{sp}|{dp}|deck_q={deck_bucket}",
                    f"balanced_any|{sp}|{dp}|deck=any",
                    f"balanced_any|{sp}|{dp}",
                ]
            )
        keys.append("balanced_any")
    deduped = []
    seen = set()
    for key in keys:
        if key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def resolve_expect_attribute(
    preset,
    *,
    default=None,
    session=None,
    run_context=None,
    desired_parent_sparks=None,
    style=None,
    distance=None,
    deck_quality_bucket=None,
):
    preset = preset or {}
    base = normalize_expect_attribute_vector(
        preset.get("expect_attribute"),
        default=default or EXPECT_ATTRIBUTE_DEFAULT,
    )
    profiles = normalize_expect_attribute_profiles(preset.get("expect_attribute_profiles"))
    for key in expect_attribute_profile_lookup_keys(
        preset,
        session=session,
        run_context=run_context,
        desired_parent_sparks=desired_parent_sparks,
        style=style,
        distance=distance,
        deck_quality_bucket=deck_quality_bucket,
    ):
        entry = profiles.get(key)
        if isinstance(entry, dict) and isinstance(entry.get("expect_attribute"), list):
            return normalize_expect_attribute_vector(entry.get("expect_attribute"), default=base)
    return base


def instance_learning_override_dir(base_dir):
    from career_bot.runner import runtime_output_root

    path = runtime_output_root(base_dir) / "instance_learning" / "presets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def instance_learning_override_path(base_dir, preset_name):
    return instance_learning_override_dir(base_dir) / f"{slugify(preset_name)}.json"


def shared_learning_override_dir(base_dir):
    path = Path(base_dir) / "uma_runtime" / "shared_learning" / "presets"
    path.mkdir(parents=True, exist_ok=True)
    return path


def shared_learning_override_path(base_dir, preset_name):
    return shared_learning_override_dir(base_dir) / f"{slugify(preset_name)}.json"


def read_instance_learning_override(base_dir, preset_name):
    path = instance_learning_override_path(base_dir, preset_name)
    if not path.exists():
        return None
    try:
        data = normalize_preset(json.loads(path.read_text(encoding="utf-8-sig")))
        return {k: v for k, v in data.items() if k not in CONFIG_ONLY_KEYS}
    except Exception:
        return None


def read_shared_learning_override(base_dir, preset_name):
    path = shared_learning_override_path(base_dir, preset_name)
    if not path.exists():
        return None
    try:
        data = normalize_preset(json.loads(path.read_text(encoding="utf-8-sig")))
        return {k: v for k, v in data.items() if k not in CONFIG_ONLY_KEYS}
    except Exception:
        return None


def write_instance_learning_override(base_dir, preset_name, preset):
    data = {k: v for k, v in normalize_preset(preset).items() if k not in CONFIG_ONLY_KEYS}
    path = instance_learning_override_path(base_dir, preset_name)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def write_shared_learning_override(base_dir, preset_name, preset):
    data = {k: v for k, v in normalize_preset(preset).items() if k not in CONFIG_ONLY_KEYS}
    path = shared_learning_override_path(base_dir, preset_name)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def split_csv(value):
    if isinstance(value, list):
        return value
    return [part.strip() for part in str(value or "").split(",") if part.strip()]


def normalize_skill_list(value):
    rows = value if isinstance(value, list) else []
    result = []
    for row in rows:
        if isinstance(row, list):
            parts = []
            for item in row:
                parts.extend(split_csv(item))
        else:
            parts = split_csv(row)
        if parts:
            result.append(parts)
    return result


def _clamp_float(value, minimum, maximum, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    return max(float(minimum), min(float(maximum), number))


def _normalize_vector(value, length, default, minimum, maximum):
    raw = value if isinstance(value, list) else []
    result = []
    for index in range(length):
        fallback = default[index] if isinstance(default, list) and index < len(default) else default
        raw_value = raw[index] if index < len(raw) else fallback
        result.append(_clamp_float(raw_value, minimum, maximum, fallback))
    return result


def _normalize_matrix(value, rows, cols, default, minimum, maximum):
    raw_rows = value if isinstance(value, list) else []
    result = []
    for row_index in range(rows):
        fallback_row = default[row_index] if isinstance(default, list) and row_index < len(default) else default
        raw_row = raw_rows[row_index] if row_index < len(raw_rows) and isinstance(raw_rows[row_index], list) else []
        result.append(_normalize_vector(raw_row, cols, fallback_row, minimum, maximum))
    return result


def normalize_preset(raw):
    data = dict(raw or {})
    normalized = {}
    for key, value in data.items():
        if key in EXCLUDED_KEYS:
            continue
        normalized[RENAMES.get(key, key)] = value
    normalized["name"] = slugify(normalized.get("name") or data.get("name"))
    normalized["scenario_id"] = MANT_SCENARIO_ID
    normalized["scenario"] = MANT_SCENARIO_ID
    normalized["learn_skill_list"] = normalize_skill_list(normalized.get("learn_skill_list"))
    blacklist = []
    blacklist.extend(split_csv(data.get("blacklistedSkills")))
    blacklist.extend(split_csv(data.get("skill_blacklist")))
    blacklist.extend(split_csv(data.get("learn_skill_blacklist")))
    normalized["learn_skill_blacklist"] = list(dict.fromkeys(blacklist))
    normalized["cure_asap_conditions"] = split_csv(normalized.get("cure_asap_conditions"))
    if not normalized["cure_asap_conditions"]:
        normalized["cure_asap_conditions"] = ["Migraine", "Night Owl", "Skin Outbreak", "Slacker", "Slow Metabolism", "(Practice poor isn't worth a turn to cure)"]
    normalized["expect_attribute"] = normalize_expect_attribute_vector(normalized.get("expect_attribute"))
    normalized["expect_attribute_profiles"] = normalize_expect_attribute_profiles(
        normalized.get("expect_attribute_profiles")
    )
    default_score_value = [[0.11, 0.1, 0.006, 0.09], [0.11, 0.1, 0.006, 0.09], [0.11, 0.1, 0.006, 0.09], [0.03, 0.05, 0.006, 0.09], [0, 0, 0.006, 0]]
    default_base_score = [0, 0, 0, 0, 0]
    # Per Stat Priority Architecture: Speed gets the highest baseline weight,
    # Guts the lowest, others arrayed by race-impact contribution. The structural
    # Speed bias is enforced in _speed_priority_bonus; this multiplier adds
    # per-stat-point value differentiation on top.
    # Order: [Speed, Stamina, Power, Guts, Wit, SkillPoint]
    default_stat_value_multiplier = [0.022, 0.016, 0.018, 0.012, 0.016, 0.01]
    default_extra_weight = [[0, 0, 0, 0, 0] for _ in range(4)]
    normalized["score_value"] = _normalize_matrix(normalized.get("score_value"), 5, 4, default_score_value, 0.0, 0.18)
    for row in normalized["score_value"]:
        row[2] = _clamp_float(row[2], 0.001, 0.010, 0.006)
    normalized["base_score"] = _normalize_vector(normalized.get("base_score"), 5, default_base_score, -0.08, 0.12)
    # SS-push profiles need raw high-gain training tiles to beat low-output
    # bond/race-safety heuristics. 0.025 made +50 stat tiles only worth 1.25
    # before modifiers, which was too low for race-heavy parent farming.
    normalized["stat_value_multiplier"] = _normalize_vector(normalized.get("stat_value_multiplier"), 6, default_stat_value_multiplier, 0.002, 0.050)
    normalized["stat_value_multiplier"][5] = _clamp_float(normalized["stat_value_multiplier"][5], 0.002, 0.010, 0.005)
    normalized["extra_weight"] = _normalize_matrix(normalized.get("extra_weight"), 4, 5, default_extra_weight, -0.12, 0.25)
    normalized = _apply_adaptive_policy_hygiene(normalized)
    normalized.setdefault("npc_score_value", [[0.05, 0.05, 0.05], [0.05, 0.05, 0.05], [0.05, 0.05, 0.05], [0.03, 0.05, 0.05], [0, 0, 0.05]])
    normalized.setdefault("special_training", [0.095, 0.095, 0.095, 0.095, 0])
    normalized.setdefault("spirit_explosion", [[0.16, 0.16, 0.16, 0.06, 0.11]] * 5)
    normalized.setdefault("wit_special_multiplier", [1.57, 1.37])
    normalized.setdefault("compensate_failure", True)
    normalized.setdefault("summer_score_threshold", 0.34)
    normalized.setdefault("motivation_threshold_year1", 3)
    normalized.setdefault("motivation_threshold_year2", 4)
    normalized.setdefault("motivation_threshold_year3", 4)
    normalized.setdefault("prioritize_recreation", False)
    normalized.setdefault("pal_thresholds", [])
    normalized.setdefault("pal_friendship_score", [0.08, 0.057, 0.018])
    normalized.setdefault("pal_card_multiplier", 0.1)
    normalized.setdefault("rest_threshold", 48)
    normalized.setdefault("learn_skill_threshold", 888)
    normalized.setdefault("skill_point_drain_floor", 60)
    normalized.setdefault("final_skill_drain_max_passes", 5)
    normalized.setdefault("auto_learning_enabled", True)
    normalized.setdefault("auto_learning_apply", True)
    normalized.setdefault("auto_learning_min_samples", 3)
    normalized.setdefault("auto_learning_recent", 80)
    normalized.setdefault("auto_learning_recency_enabled", True)
    normalized.setdefault("auto_learning_recency_bias", 0.55)
    normalized.setdefault("auto_learning_recency_half_life", 12)
    normalized.setdefault("auto_learning_recent_failure_bias", 0.35)
    normalized.setdefault("auto_learning_regression_enabled", True)
    normalized.setdefault("auto_learning_regression_bias", 0.7)
    normalized.setdefault("auto_learning_regression_window", 5)
    normalized.setdefault("auto_learning_regression_floor", 0.92)
    normalized.setdefault("auto_learning_progression_enabled", True)
    normalized.setdefault("auto_learning_progression_bias", 0.35)
    normalized.setdefault("auto_learning_progression_window", 5)
    normalized.setdefault("auto_learning_progression_delta", 500)
    normalized.setdefault("learning_use_stratified_reference_groups", True)
    normalized.setdefault("learning_use_deviation_signal", True)
    normalized.setdefault("learning_context_adaptation_enabled", True)
    normalized.setdefault("learning_context_exact_match_score", 28)
    normalized.setdefault("learning_context_similar_match_score", 14)
    normalized.setdefault("learning_context_min_exact_samples", 4)
    normalized.setdefault("learning_context_min_similar_samples", 8)
    normalized.setdefault("learning_context_soft_min_similar_samples", 3)
    normalized.setdefault("learning_context_global_fallback_enabled", False)
    normalized.setdefault("auto_learning_statuses", ["finished"])
    normalized.setdefault("auto_learning_runtime_paths", [])
    normalized.setdefault("auto_learning_output_name", "")
    normalized.setdefault("auto_learning_apply_scope", "")
    normalized.setdefault("auto_learning_monotonic_apply_enabled", True)
    normalized.setdefault("auto_learning_corrective_apply_enabled", True)
    normalized.setdefault("auto_learning_learn_from_complete_logs", True)
    if normalized.get("auto_learning_corrective_apply_enabled") is None:
        normalized["auto_learning_corrective_apply_enabled"] = True
    if normalized.get("auto_learning_learn_from_complete_logs") is None:
        normalized["auto_learning_learn_from_complete_logs"] = True
    normalized.setdefault("auto_learning_monotonic_min_improvement", 1.0)
    normalized.setdefault("auto_learning_monotonic_allowed_drop", 0.0)
    normalized.setdefault("learning_policy_objective_gate_enabled", True)
    normalized.setdefault("learning_policy_min_rank_score", 15000)
    normalized.setdefault("learning_policy_min_internal_score", 17500)
    normalized.setdefault("learning_policy_min_stat_total", 3300)
    normalized.setdefault("learning_policy_min_actions", 20)
    normalized.setdefault("learning_policy_max_race_losses", 0)
    normalized.setdefault("learning_policy_max_g1_losses", 0)
    normalized.setdefault("learning_policy_min_race_total_for_clean_record", 8)
    normalized.setdefault("training_policy_model_enabled", True)
    normalized.setdefault("training_policy_model_weight", 0.35)
    normalized.setdefault("training_policy_model_max_bonus", 0.05)
    normalized.setdefault("training_policy_model_runtime_cap", 0.05)
    normalized.setdefault("training_policy_disable_on_untrusted_metadata", True)
    normalized.setdefault("training_policy_max_trusted_score", 25000)
    normalized.setdefault("training_policy_min_actions", 12)
    normalized.setdefault("training_policy_validation_tolerance", 0.985)
    normalized.setdefault("training_policy_validation_context_limit", 24)
    normalized.setdefault("training_policy_validation_context_min_samples", 6)
    normalized.setdefault("training_policy_validation_recent_limit", 12)
    normalized.setdefault("training_policy_model", {})
    normalized.setdefault("training_policy_challenger_enabled", True)
    normalized.setdefault("training_policy_challenger_promotion_passes", 2)
    normalized.setdefault("training_policy_challenger_min_margin", 0.01)
    normalized.setdefault("training_policy_challenger", {})
    normalized.setdefault("visible_tile_quality_guard_enabled", True)
    normalized.setdefault("visible_tile_quality_clear_gap", 7.0)
    normalized.setdefault("visible_tile_quality_bonus_cap", 0.28)
    normalized.setdefault("visible_tile_quality_penalty_cap", 0.34)
    normalized.setdefault("item_learning_policy", {})
    normalized.setdefault("run_mode_policy", {})
    normalized.setdefault("future_turn_effects", {})
    normalized.setdefault("manual_purchase_at_end", True)
    normalized.setdefault("auto_buy_stamina_skill_for_race", True)
    normalized.setdefault("race_stamina_rescue_lookahead_turns", 5)
    normalized.setdefault("race_stamina_skill_min_ratio", 0.96)
    normalized.setdefault("race_stamina_skill_max_count", 1)
    normalized.setdefault("calendar_race_prebuy_enabled", True)
    normalized.setdefault("calendar_race_prebuy_grades", ["G1", "G2", "G3", "OP", "PRE-OP"])
    normalized.setdefault("calendar_race_prebuy_all_scheduled", True)
    normalized.setdefault("scheduled_race_clean_record_mode", True)
    normalized.setdefault("calendar_race_clean_prebuy_min_sp", 120)
    normalized.setdefault("calendar_race_clean_prebuy_budget", 1400)
    normalized.setdefault("calendar_race_clean_prebuy_keep_sp", 0)
    normalized.setdefault("calendar_race_clean_prebuy_max_skills", 10)
    normalized.setdefault("calendar_race_clean_prebuy_target_probability", 0.985)
    normalized.setdefault("calendar_race_prebuy_allow_midcareer_with_end_buy", False)
    normalized.setdefault("g1_race_continue_enabled", True)
    normalized.setdefault("g1_race_continue_min_limit", 5)
    normalized.setdefault("scheduled_race_safety_training_lookahead_turns", 18)
    normalized.setdefault("scheduled_race_safety_requirement_scale", 0.94)
    normalized.setdefault("scheduled_race_safety_bonus_cap", 0.75)
    # Pre-race skill purchase: aggressive defaults to maximize G1 win
    # rate. Old defaults (520/350/2) left bots dumping 600+ SP at career
    # end on cheap drain-mode buys while losing Senior G1s mid-career
    # because budget after reserve was too small to afford useful skills.
    # New defaults front-load skill investment into the races themselves.
    normalized.setdefault("calendar_race_prebuy_min_sp", 280)   # fire earlier (was 450)
    normalized.setdefault("calendar_race_prebuy_budget", 850)   # spend more per race (was 520)
    normalized.setdefault("calendar_race_prebuy_keep_sp", 100)  # smaller reserve (was 350)
    normalized.setdefault("calendar_race_prebuy_max_skills", 4) # more skills per race (was 2)
    normalized.setdefault("race_empirical_success_tolerance", 0.94)
    normalized.setdefault("race_exploration_enabled", True)
    normalized.setdefault("race_exploration_rate", 0.08)
    normalized.setdefault("race_exploration_min_confidence", 0.45)
    normalized.setdefault("race_exploration_max_relative_deficit", 0.18)
    normalized.setdefault("race_exploration_min_static_stamina_ratio", 0.74)
    normalized.setdefault("race_exploration_min_stat_coverage", 0.93)
    normalized.setdefault("kikuka_front_runner_stamina_guard", True)
    normalized.setdefault("kikuka_front_runner_min_stamina", 380)
    normalized.setdefault("scheduled_race_force_calendar", True)
    normalized.setdefault("scheduled_race_safety_enabled", True)
    normalized.setdefault("scheduled_race_respect_training", False)
    normalized.setdefault("scheduled_race_skip_if_stamina_low", False)
    normalized.setdefault("scheduled_race_skip_off_aptitude", False)
    if bool(normalized.get("scheduled_race_force_calendar", True)):
        # User calendar races are hard commitments. Safety checks should
        # shape training and pre-race skill buys, not silently skip a slot.
        normalized["scheduled_race_respect_training"] = False
        normalized["scheduled_race_skip_if_stamina_low"] = False
        normalized["scheduled_race_skip_off_aptitude"] = False
    normalized.setdefault("debut_loss_recovery_race_enabled", True)
    normalized.setdefault("calendar_optional_fillers_enabled", False)
    normalized.setdefault("scheduled_race_min_success_coverage", 0.90)
    normalized.setdefault("scheduled_race_max_success_relative_deficit", 0.18)
    normalized.setdefault("scheduled_race_min_static_core_coverage", 0.84)
    normalized.setdefault("scheduled_race_min_static_speed_ratio", 0.82)
    normalized.setdefault("first_summer_friendship_enabled", True)
    normalized.setdefault("first_summer_friendship_target_turn", 35)
    normalized.setdefault("first_summer_friendship_target_rainbows", 4)
    normalized.setdefault("first_summer_friendship_bonus_20_39", 0.035)
    normalized.setdefault("first_summer_friendship_bonus_40_59", 0.065)
    normalized.setdefault("first_summer_friendship_bonus_60_79", 0.10)
    normalized.setdefault("first_summer_friendship_urgency_per_deficit", 0.75)
    normalized.setdefault("first_summer_friendship_bonus_cap", 0.45)
    normalized.setdefault("first_summer_friendship_rest_threshold_penalty_per_gap", 10)
    normalized.setdefault("first_summer_friendship_early_rest_threshold_penalty", 6)
    normalized.setdefault("first_summer_friendship_min_push_vital", 18)
    normalized.setdefault("first_summer_friendship_max_push_failure", 16)
    normalized.setdefault("first_summer_friendship_min_push_score", 0.06)
    normalized.setdefault("first_summer_friendship_recreation_max_training_score", 0.06)
    normalized.setdefault("first_summer_friendship_recreation_max_vital", 35)
    normalized.setdefault("low_hp_wit_training_override_enabled", True)
    normalized.setdefault("low_hp_wit_training_max_failure", 25)
    normalized.setdefault("low_hp_wit_training_min_score", 0.08)
    normalized.setdefault("low_hp_wit_training_substitute_min_score", 0.01)
    normalized.setdefault("hard_failure_safe_wit_threshold", 28)
    normalized.setdefault("hard_failure_safe_wit_vital_ceiling", 60)
    normalized.setdefault("non_wit_high_value_training_max_failure", 24)
    normalized.setdefault("race_heavy_route_min_races", 32)
    normalized.setdefault("race_heavy_rest_threshold_penalty", 4)
    normalized.setdefault("race_heavy_recreation_max_training_score", 0.18)
    normalized.setdefault("stat_friend_recreation_target_bond", 60)
    normalized.setdefault("stat_friend_recreation_max_vital", 80)
    normalized.setdefault("stat_friend_recreation_force_vital", 50)
    normalized.setdefault("stat_friend_recreation_emergency_vital", 28)
    normalized.setdefault("stat_friend_recreation_early_limit_turn", 25)
    normalized.setdefault("stat_friend_recreation_early_max_uses", 2)
    normalized.setdefault("stat_friend_recreation_junior_use_cap", 1)
    normalized.setdefault("stat_friend_recreation_early_classic_use_cap", 3)
    normalized.setdefault("stat_friend_recreation_classic_use_cap", 4)
    normalized.setdefault("stat_friend_recreation_max_training_score", 0.75)
    normalized.setdefault("stat_friend_recreation_score_cap_bonus", 0.18)
    normalized.setdefault("critical_mood_recreation_threshold", 2)
    normalized.setdefault("critical_mood_recreation_score_cap", 1.15)
    normalized.setdefault("critical_mood_recreation_vital_ceiling", 90)
    normalized.setdefault("race_heavy_speed_deficit_scale_ceiling", 0.82)
    normalized.setdefault("race_heavy_lane_balance_start_turn", 18)
    normalized.setdefault("race_heavy_lane_balance_max_bonus", 0.42)
    normalized.setdefault("race_heavy_lane_balance_gap", 90)
    normalized.setdefault("race_heavy_power_support_gap", 140)
    normalized.setdefault("race_heavy_power_floor_target", 950)
    normalized.setdefault("race_heavy_power_priority_multiplier", 1.35)
    normalized.setdefault("race_heavy_priority_lead_damp_gap", 120)
    normalized.setdefault("race_heavy_priority_lead_damp_multiplier", 0.58)
    normalized.setdefault("wit_closeout_critical_speed_floor", 1000)
    normalized.setdefault("wit_closeout_critical_stamina_floor", 620)
    normalized.setdefault("wit_closeout_critical_power_floor", 820)
    normalized.setdefault("wit_closeout_damping_when_core_behind", 0.28)
    normalized.setdefault("wit_closeout_damping_when_speed_behind", 0.45)
    normalized.setdefault("wit_closeout_damping_min_wit", 1000)
    normalized.setdefault("wit_closeout_damping_lead_over_speed", 80)
    normalized.setdefault("count_conditional_recovery_uniques", False)
    normalized.setdefault("skill_buy_on_sight", [])
    normalized.setdefault("skill_profile_style", "")
    normalized.setdefault("skill_profile_distance", "")
    normalized.setdefault("skill_optimizer_enabled", True)
    if normalized.get("skill_optimizer_enabled") is None:
        normalized["skill_optimizer_enabled"] = True
    if not normalized.get("alarm_clock_mode"):
        try:
            clock_limit = int(normalized.get("clock_use_limit") or 0)
        except (TypeError, ValueError):
            clock_limit = 0
        allow_clock_carats = str(normalized.get("clock_allow_carats") or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}
        normalized["alarm_clock_mode"] = "none" if clock_limit <= 0 else ("carats" if allow_clock_carats else "normal")
    if not isinstance(normalized.get("desired_parent_sparks"), dict):
        normalized["desired_parent_sparks"] = {"blue": [], "pink": [], "green": [], "white": []}
    if not isinstance(normalized.get("parent_farming_rules"), dict) or not normalized.get("parent_farming_rules"):
        normalized["parent_farming_rules"] = default_parent_farming_rules()
    normalized.setdefault("optional_race_leniency_enabled", True)
    normalized.setdefault("optional_race_allowed_grades", ["G2", "G3"])
    normalized.setdefault("optional_race_max_turn", 72)
    normalized.setdefault("optional_race_max_training_score", 0.34)
    normalized.setdefault("optional_race_max_training_score_cap", 0.44)
    normalized.setdefault("optional_race_hard_skip_training_score", 0.50)
    normalized.setdefault("optional_race_skip_rainbow_count", 2)
    normalized.setdefault("optional_race_skip_stat_gain", 40)
    normalized.setdefault("optional_race_min_value", 0.75)
    normalized.setdefault("optional_race_skip_if_stamina_low", True)
    normalized.setdefault("optional_race_rival_base_score", 0.70)
    normalized.setdefault("optional_race_rival_bonus", 0.25)
    normalized.setdefault("optional_race_rival_training_bonus", 0.05)
    normalized.setdefault("optional_race_epithet_bonus", 0.25)
    normalized.setdefault("optional_race_epithet_near_bonus", 0.10)
    normalized.setdefault("optional_race_epithet_training_bonus", 0.04)
    normalized.setdefault("optional_race_epithet_window", 12000)
    normalized.setdefault("optional_race_epithet_thresholds", [50000, 100000, 200000, 400000])
    normalized.setdefault("optional_race_affinity_bonus", 0.10)
    normalized.setdefault("optional_race_affinity_epithet_bonus", 0.20)
    normalized.setdefault("race_style_overrides", {})
    normalized.setdefault("skill_blacklist_custom", normalized.get("learn_skill_blacklist", []))
    normalized.setdefault("learn_skill_append_defaults", False)
    normalized.setdefault("mant_config", {})
    return normalized


class PresetStore:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.preset_dir = self.base_dir / "data" / "presets"
        self.saved_dir = self.preset_dir / "saved"
        self.learned_dir = self.preset_dir / "learned"
        self.starter_dir = self.preset_dir / "starter"
        self.backup_dir = self.preset_dir / "backups"
        self.policy_model_dir = self.base_dir / "uma_runtime" / "policy_models"

    def ensure(self):
        self.preset_dir.mkdir(parents=True, exist_ok=True)
        self.saved_dir.mkdir(parents=True, exist_ok=True)
        self.learned_dir.mkdir(parents=True, exist_ok=True)
        self.starter_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        self.policy_model_dir.mkdir(parents=True, exist_ok=True)

    def read_all(self):
        self.ensure()
        loaded = {}
        for path in self._split_config_files():
            name = path.name.removesuffix(".config.json")
            try:
                data = self.load_active_preset("", name)
            except Exception:
                continue
            if data["name"] not in loaded:
                loaded[data["name"]] = data
        for _layer, path in self._source_records():
            try:
                data = normalize_preset(json.loads(path.read_text(encoding="utf-8-sig")))
            except Exception:
                continue
            if data["name"] not in loaded:
                loaded[data["name"]] = data
        return sorted(loaded.values(), key=lambda item: item["name"].lower())

    def read_one(self, name):
        wanted = str(name or "").strip().lower()
        for preset in self.read_all():
            if preset["name"].lower() == wanted:
                return preset
        return None

    def default_name(self, preferred=None):
        presets = self.read_all()
        wanted = str(preferred or "").strip().lower()
        if wanted:
            for preset in presets:
                if preset["name"].lower() == wanted:
                    return preset["name"]
        if presets:
            return presets[0]["name"]
        return str(preferred or "").strip()

    def write(self, preset, *, target="saved"):
        self.ensure()
        data = normalize_preset(preset)
        if self.config_path(data["name"]).exists():
            return self.save_user_config(data["name"], data)
        path = self._path_for_name(data["name"], target=target)
        if path.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = self.backup_dir / f"{slugify(data['name'])}_{stamp}.json"
            suffix = 1
            while backup.exists():
                backup = self.backup_dir / f"{slugify(data['name'])}_{stamp}_{suffix}.json"
                suffix += 1
            try:
                shutil.copy2(path, backup)
            except OSError:
                pass
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        try:
            from career_bot.storage_cleanup import rotate_preset_backups
            rotate_preset_backups(self.base_dir)
        except Exception:
            pass
        return data

    def config_path(self, name):
        self.ensure()
        return self.preset_dir / f"{slugify(name)}.config.json"

    def runtime_state_path(self, account_id, preset_name):
        from career_bot.runner import runtime_output_root

        account = str(account_id or os.environ.get("SWEEPY_INSTANCE_NAME") or "").strip() or "default"
        path = runtime_output_root(self.base_dir) / "instances" / account / "state"
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{slugify(preset_name)}.runtime.json"

    def policy_model_path(self, family):
        self.policy_model_dir.mkdir(parents=True, exist_ok=True)
        return self.policy_model_dir / f"{slugify(family)}.policy_model.json"

    def policy_model_history_dir(self, family):
        path = self.policy_model_dir / f"{slugify(family)}.policy_model.history"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def policy_overrides_path(self, account_id, family):
        from career_bot.runner import runtime_output_root

        account = str(account_id or os.environ.get("SWEEPY_INSTANCE_NAME") or "").strip() or "default"
        path = runtime_output_root(self.base_dir) / "instances" / account / "policy_overrides"
        path.mkdir(parents=True, exist_ok=True)
        return path / f"{slugify(family)}.json"

    def _read_layer(self, path):
        try:
            if Path(path).exists():
                data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        return {}

    def _write_layer(self, path, payload):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload or {}, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_active_preset(self, account_id, preset_name):
        config = self._read_layer(self.config_path(preset_name))
        if not config:
            legacy = self.read_legacy_unified(preset_name)
            return normalize_preset(legacy) if legacy else None
        name = str(config.get("name") or preset_name or "").strip()
        family = preset_family_for(config)
        runtime = self._read_layer(self.runtime_state_path(account_id, name))
        model = self._read_layer(self.policy_model_path(family))
        overrides = self._read_layer(self.policy_overrides_path(account_id, family))
        model = {k: v for k, v in model.items() if k not in CONFIG_ONLY_KEYS}
        overrides = {k: v for k, v in overrides.items() if k not in CONFIG_ONLY_KEYS}
        merged = merge_preset_layers(config, runtime, model, overrides)
        merged["name"] = name
        merged["preset_family"] = family
        return normalize_preset(merged)

    def save_user_config(self, preset_name, preset):
        layers = split_preset_layers(preset)
        config = layers["config"]
        path = self.config_path(preset_name)
        if path.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = self.backup_dir / f"{slugify(preset_name)}.config_{stamp}.json"
            try:
                shutil.copy2(path, backup)
            except OSError:
                pass
        self._write_layer(path, config)
        try:
            from career_bot.storage_cleanup import rotate_preset_backups
            rotate_preset_backups(self.base_dir)
        except Exception:
            pass
        return self.load_active_preset("", config["name"]) or normalize_preset(config)

    def save_runtime_state(self, account_id, preset_name, state):
        return self._write_layer(self.runtime_state_path(account_id, preset_name), dict(state or {}))

    def save_policy_model(self, family, model_layer):
        path = self.policy_model_path(family)
        if path.exists():
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            history = self.policy_model_history_dir(family) / f"policy_model_{stamp}.json"
            try:
                shutil.copy2(path, history)
            except OSError:
                pass
        payload = {k: v for k, v in dict(model_layer or {}).items() if k not in CONFIG_ONLY_KEYS}
        return self._write_layer(path, payload)

    def save_policy_overrides(self, account_id, family, overrides):
        payload = {k: v for k, v in dict(overrides or {}).items() if k not in CONFIG_ONLY_KEYS}
        return self._write_layer(self.policy_overrides_path(account_id, family), payload)

    def delete(self, name):
        slug = f"{slugify(name)}.json"
        for folder in (self.saved_dir, self.learned_dir, self.preset_dir):
            path = folder / slug
            if path.exists():
                path.unlink()
                return True
        return False

    def _source_files(self):
        return [*self._split_config_files(), *[path for _, path in self._source_records()]]

    def source_files(self):
        return list(self._source_files())

    def saved_path(self, name):
        self.ensure()
        return self.saved_dir / f"{slugify(name)}.json"

    def learned_path(self, name):
        self.ensure()
        return self.learned_dir / f"{slugify(name)}.json"

    def locate(self, name):
        wanted = str(name or "").strip().lower()
        if not wanted:
            return None, None, None
        split = self.load_active_preset("", name)
        if split and split["name"].lower() == wanted and self.config_path(name).exists():
            return "split", self.config_path(name), split
        for layer, path in self._source_records():
            try:
                data = normalize_preset(json.loads(path.read_text(encoding="utf-8-sig")))
            except Exception:
                continue
            if data["name"].lower() == wanted:
                return layer, path, data
        return None, None, None

    def _path_for_name(self, name, *, target="saved"):
        if str(target or "").strip().lower() == "learned":
            return self.learned_path(name)
        return self.saved_path(name)

    def _iter_json_files(self, folder):
        if folder.exists():
            for path in sorted(folder.glob("*.json")):
                if path.name.endswith(".config.json"):
                    continue
                yield path

    def _split_config_files(self):
        self.ensure()
        return sorted(self.preset_dir.glob("*.config.json"))

    def _source_records(self):
        self.ensure()
        layers = [
            ("saved", self.saved_dir),
            ("learned", self.learned_dir),
            ("legacy", self.preset_dir),
            ("starter", self.starter_dir),
        ]
        for layer, folder in layers:
            for path in self._iter_json_files(folder):
                yield layer, path

    def read_legacy_unified(self, name):
        wanted = str(name or "").strip().lower()
        if not wanted:
            return None
        for layer, path in self._source_records():
            try:
                data = normalize_preset(json.loads(path.read_text(encoding="utf-8-sig")))
            except Exception:
                continue
            if data["name"].lower() == wanted:
                return data
        return None
