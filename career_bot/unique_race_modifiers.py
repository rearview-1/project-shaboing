CAREER_INVISIBLE_STAT_BONUS = 400


_STYLE_ALIASES = {
    "front": "front_runner",
    "front runner": "front_runner",
    "front_runner": "front_runner",
    "nige": "front_runner",
    "pace": "pace_chaser",
    "pace chaser": "pace_chaser",
    "pace_chaser": "pace_chaser",
    "senko": "pace_chaser",
    "late": "late_surger",
    "late surger": "late_surger",
    "late_surger": "late_surger",
    "sashi": "late_surger",
    "closer": "end_closer",
    "end closer": "end_closer",
    "end_closer": "end_closer",
    "end": "end_closer",
    "oikomi": "end_closer",
}


def _safe_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def _normalize_style(value):
    text = " ".join(str(value or "").strip().lower().replace("_", " ").split())
    return _STYLE_ALIASES.get(text, "")


def _normalize_distance(value):
    text = str(value or "").strip().lower()
    aliases = {
        "short": "sprint",
        "sprint": "sprint",
        "mile": "mile",
        "middle": "medium",
        "medium": "medium",
        "long": "long",
    }
    return aliases.get(text, "")


def card_id_from_chara(chara):
    for key in ("card_id", "chara_id"):
        value = _safe_int((chara or {}).get(key))
        if value:
            return value
    return 0


_UNIQUE_RACE_PROFILES = {
    # Agnes Tachyon's unique ("U=ma2" / "Introduction to Physiology")
    # includes stamina recovery when it activates in the second half while
    # racing from behind. Model it as a style-gated partial-to-full recovery
    # skill equivalent so race checks can be meaningfully more lenient than a
    # generic medium/long trainee.
    103201: {
        "name": "Agnes Tachyon",
        "recovery": {
            "distance_keys": {"medium", "long"},
            "skill_equivalent_by_style": {
                "pace_chaser": 1.00,
                "late_surger": 0.85,
            },
            "source": "stamina_recovery_unique",
        },
    },
    # Super Creek variants have stable recovery uniques that the bot had
    # already been special-casing in skill-buy logic. Keep them here as the
    # canonical source of truth.
    104501: {
        "name": "Super Creek",
        "recovery": {
            "distance_keys": {"medium", "long"},
            "skill_equivalent": 1.00,
            "source": "reliable_stamina_recovery_unique",
        },
    },
    104502: {
        "name": "Super Creek",
        "recovery": {
            "distance_keys": {"medium", "long"},
            "skill_equivalent": 1.00,
            "source": "reliable_stamina_recovery_unique",
        },
    },
    104503: {
        "name": "Super Creek",
        "recovery": {
            "distance_keys": {"medium", "long"},
            "skill_equivalent": 1.00,
            "source": "reliable_stamina_recovery_unique",
        },
    },
    # Summer Special Week's recovery unique is weaker / more conditional than
    # the always-on cases above, so it stays opt-in via preset.
    100102: {
        "name": "Special Week (Summer)",
        "recovery": {
            "distance_keys": {"medium", "long"},
            "skill_equivalent": 0.75,
            "requires_flag": "count_conditional_recovery_uniques",
            "source": "conditional_stamina_recovery_unique",
        },
    },
    101102: {
        "name": "Grass Wonder (Fantasy)",
        "recovery": {
            "distance_keys": {"medium", "long"},
            "skill_equivalent": 0.85,
            "source": "stamina_recovery_unique",
        },
    },
    102301: {
        "name": "Biwa Hayahide",
        "recovery": {
            "distance_keys": {"medium", "long"},
            "skill_equivalent": 0.85,
            "source": "stamina_recovery_unique",
        },
    },
    102302: {
        "name": "Biwa Hayahide (Christmas)",
        "recovery": {
            "distance_keys": {"medium", "long"},
            "skill_equivalent": 0.85,
            "source": "stamina_recovery_unique",
        },
    },
    102303: {
        "name": "Biwa Hayahide (Mecha)",
        "recovery": {
            "distance_keys": {"medium", "long"},
            "skill_equivalent": 0.85,
            "source": "stamina_recovery_unique",
        },
    },
    102402: {
        "name": "Mayano Top Gun (Wedding)",
        "recovery": {
            "distance_keys": {"medium", "long"},
            "skill_equivalent": 0.50,
            "source": "stamina_pressure_unique",
        },
    },
    107401: {
        "name": "Mejiro Bright",
        "recovery": {
            "distance_keys": {"long"},
            "skill_equivalent": 0.75,
            "source": "long_distance_stamina_unique",
        },
    },
    107402: {
        "name": "Mejiro Bright (Christmas)",
        "recovery": {
            "distance_keys": {"long"},
            "skill_equivalent": 0.75,
            "source": "long_distance_stamina_unique",
        },
    },
}


def race_unique_recovery_profile(chara, distance="", style="", *, count_conditional=False):
    card_id = card_id_from_chara(chara)
    profile = _UNIQUE_RACE_PROFILES.get(card_id) or {}
    recovery = profile.get("recovery") or {}
    if not recovery:
        return {}

    distance_key = _normalize_distance(distance)
    style_key = _normalize_style(style)

    allowed_distances = set(recovery.get("distance_keys") or [])
    if allowed_distances and distance_key not in allowed_distances:
        return {}

    required_flag = str(recovery.get("requires_flag") or "").strip()
    if required_flag and not count_conditional:
        return {}

    skill_equivalent = 0.0
    by_style = recovery.get("skill_equivalent_by_style") or {}
    if by_style:
        skill_equivalent = float(by_style.get(style_key) or 0.0)
    else:
        skill_equivalent = float(recovery.get("skill_equivalent") or 0.0)
    if skill_equivalent <= 0.0:
        return {}

    return {
        "card_id": card_id,
        "name": str(profile.get("name") or f"Card {card_id}"),
        "distance": distance_key,
        "style": style_key,
        "skill_equivalent": round(skill_equivalent, 4),
        "source": str(recovery.get("source") or "unique_recovery"),
        "requires_flag": required_flag,
    }
