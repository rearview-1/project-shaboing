"""Style + distance stamina demand lookups for MANT scoring."""

import re


STAMINA_REQUIREMENTS = {
    ("sprint", 0): {"front_runner": 570, "pace_chaser": 540, "late_surger": 500, "end_closer": 510},
    ("mile", 0): {"front_runner": 800, "pace_chaser": 770, "late_surger": 720, "end_closer": 740},
    ("mile", 1): {"front_runner": 640, "pace_chaser": 600, "late_surger": 560, "end_closer": 580},
    ("medium", 1): {"front_runner": 910, "pace_chaser": 930, "late_surger": 870, "end_closer": 900},
    ("medium", 2): {"front_runner": 710, "pace_chaser": 720, "late_surger": 680, "end_closer": 700},
    ("long", 1): {"front_runner": 1130, "pace_chaser": 1110, "late_surger": 1030, "end_closer": 1060},
    ("long", 2): {"front_runner": 900, "pace_chaser": 870, "late_surger": 820, "end_closer": 850},
    ("long_3200", 2): {"front_runner": 1080, "pace_chaser": 1060, "late_surger": 990, "end_closer": 1020},
    ("long_3200", 3): {"front_runner": 830, "pace_chaser": 800, "late_surger": 750, "end_closer": 780},
}

BASELINE_EFFECTIVE_STAMINA = 800.0

STAMINA_RECOVERY_SKILL_NAMES = {
    "swingingmaestro", "cornerrecovery", "breathoffreshair", "straightawayrecovery",
    "cooldown", "deepbreaths", "relax", "asmallbreather", "hydrate", "secondwind",
    "staminatospare", "rosyoutlook", "triple7s", "calmandcollected", "ofcalmmind",
    "superiorheal", "unrestrained", "finalpush", "calminacrowd", "unruffled",
    "gourmand", "trackblazer", "moxie", "reignition", "freespirited",
}


def normalize_skill_name(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def stamina_demand_multiplier(style, distance_category, recovery_count=1):
    """Return a stamina training multiplier from expected race demand.

    Values are normalized against effective stamina because race checks also
    receive the single-mode invisible stat bonus.
    """
    style_key = str(style or "").strip().lower() or "pace_chaser"
    distance_key = str(distance_category or "").strip().lower() or "medium"
    try:
        recovery = max(0, int(recovery_count or 0))
    except (TypeError, ValueError):
        recovery = 1
    key = (distance_key, recovery)
    if key not in STAMINA_REQUIREMENTS:
        candidates = [
            (dist, rec)
            for (dist, rec) in STAMINA_REQUIREMENTS
            if dist == distance_key and rec <= recovery
        ]
        key = max(candidates, key=lambda item: item[1]) if candidates else None
    if key is None:
        return 1.0
    demand = float(STAMINA_REQUIREMENTS[key].get(style_key) or STAMINA_REQUIREMENTS[key].get("pace_chaser") or BASELINE_EFFECTIVE_STAMINA)
    return round(max(0.80, min(1.60, demand / BASELINE_EFFECTIVE_STAMINA)), 3)
