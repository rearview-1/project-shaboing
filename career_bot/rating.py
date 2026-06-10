"""Umamusume career rating calculation.

This mirrors DaftYuda/UmaTools' rating engine:
  total rating = stat score + unique bonus + skill score

The stat curve is generated per displayed stat value, not by raw stat-sum
thresholds. Keep simulator rank labels tied to this module, not stat_sum.
"""

from __future__ import annotations


MAX_RATING_STAT = 2500

_R1 = [
    5, 8, 10, 13, 16, 18, 21, 24, 26, 28, 29, 30, 31, 33, 34, 35, 39,
    41, 42, 43, 52, 55, 66, 68, 68,
]

_R2 = [
    79, 80, 81, 83, 84, 85, 86, 88, 89, 90, 92, 93, 94, 96, 97, 98,
    100, 101, 102, 103, 105, 106, 107, 109, 110, 111, 113, 114, 115,
    117, 118, 119, 121, 122, 123, 124, 126, 127, 128, 130, 131, 132,
    134, 135, 136, 138, 139, 140, 141, 143, 144, 145, 147, 148, 149,
    151, 152, 153, 155, 156, 157, 159, 160, 161, 162, 164, 165, 166,
    168, 169, 170, 172, 173, 174, 176, 177, 178, 179, 181, 182, 182,
]

RATING_BADGE_MINIMA = [
    (0, "G"),
    (300, "G+"),
    (600, "F"),
    (900, "F+"),
    (1300, "E"),
    (1800, "E+"),
    (2300, "D"),
    (2900, "D+"),
    (3500, "C"),
    (4900, "C+"),
    (6500, "B"),
    (8200, "B+"),
    (10000, "A"),
    (12100, "A+"),
    (14500, "S"),
    (15900, "S+"),
    (17500, "SS"),
    (19200, "SS+"),
    (19600, "UG"),
    (20000, "UG1"),
    (20400, "UG2"),
    (20800, "UG3"),
    (21200, "UG4"),
    (21600, "UG5"),
    (22100, "UG6"),
    (22500, "UG7"),
    (23000, "UG8"),
    (23400, "UG9"),
    (23900, "UF"),
    (24300, "UF1"),
    (24800, "UF2"),
    (25300, "UF3"),
    (25800, "UF4"),
    (26300, "UF5"),
    (26800, "UF6"),
    (27300, "UF7"),
    (27800, "UF8"),
    (28300, "UF9"),
    (28800, "UE"),
    (29400, "UE1"),
    (29900, "UE2"),
    (30400, "UE3"),
    (31000, "UE4"),
    (31500, "UE5"),
    (32100, "UE6"),
    (32700, "UE7"),
    (33200, "UE8"),
    (33800, "UE9"),
    (34400, "UD"),
    (35000, "UD1"),
    (35600, "UD2"),
    (36200, "UD3"),
    (36800, "UD4"),
    (37500, "UD5"),
    (38100, "UD6"),
    (38700, "UD7"),
    (39400, "UD8"),
    (40000, "UD9"),
    (40700, "UC"),
    (41300, "UC1"),
    (42000, "UC2"),
    (42700, "UC3"),
    (43400, "UC4"),
    (44000, "UC5"),
    (44700, "UC6"),
    (45400, "UC7"),
    (46200, "UC8"),
    (46900, "UC9"),
    (47600, "UB"),
    (48300, "UB1"),
    (49000, "UB2"),
    (49800, "UB3"),
    (50500, "UB4"),
    (51300, "UB5"),
    (52000, "UB6"),
    (52800, "UB7"),
    (53600, "UB8"),
    (54400, "UB9"),
    (55200, "UA"),
    (55900, "UA1"),
    (56700, "UA2"),
    (57500, "UA3"),
    (58400, "UA4"),
    (59200, "UA5"),
    (60000, "UA6"),
    (60800, "UA7"),
    (61700, "UA8"),
    (62500, "UA9"),
    (63400, "US"),
    (64200, "US1"),
    (65100, "US2"),
    (66400, "US3"),
    (67700, "US4"),
    (69000, "US5"),
    (70300, "US6"),
    (71600, "US7"),
    (72900, "US8"),
    (74400, "US9"),
]


def _clamp_int(value, low=0, high=MAX_RATING_STAT):
    try:
        numeric = int(value)
    except (TypeError, ValueError):
        numeric = 0
    return max(low, min(high, numeric))


def _build_stat_scores():
    scores = [0] * (MAX_RATING_STAT + 1)
    raw = 0
    idx = 0
    for current in range(1, 1201):
        if current <= 49:
            idx = 0
        elif current <= 99:
            idx = 1
        elif current % 50 == 0:
            idx += 1
        raw += _R1[idx]
        scores[current] = round(raw / 10)

    raw = 38413
    idx = 0
    for current in range(1201, 2001):
        if current <= 1209:
            idx = 0
        elif current <= 1219:
            idx = 1
        elif current % 10 == 0:
            idx += 1
        raw += _R2[idx]
        scores[current] = round(raw / 10)

    raw = 142796
    idx = 0
    rate = 183
    for current in range(2001, MAX_RATING_STAT + 1):
        if idx >= 25:
            rate += 1
            idx = 0
        raw += rate
        idx += 1
        scores[current] = round(raw / 10)
    return scores


STAT_SCORES = _build_stat_scores()


def stat_rating_score(value):
    """Return rating contribution for one displayed stat value."""
    return STAT_SCORES[_clamp_int(value)]


def total_stat_rating_score(stats):
    """Return total stat rating for a stats mapping."""
    stats = stats or {}
    return sum(
        stat_rating_score(stats.get(key))
        for key in ("speed", "stamina", "power", "guts", "wit")
    )


def unique_rating_bonus(star_level=3, unique_level=5):
    """Return unique-skill rating bonus."""
    try:
        star = int(star_level)
    except (TypeError, ValueError):
        star = 3
    try:
        level = int(unique_level)
    except (TypeError, ValueError):
        level = 0
    if level <= 0:
        return 0
    return level * (120 if star in (1, 2) else 170)


def rank_for_rating_score(score):
    """Return the highest badge label whose threshold is <= score."""
    try:
        value = int(score)
    except (TypeError, ValueError):
        value = 0
    label = RATING_BADGE_MINIMA[0][1]
    for minimum, candidate in RATING_BADGE_MINIMA:
        if value < minimum:
            break
        label = candidate
    return label


def next_rank_progress(score):
    """Return current/next badge progress metadata for UI or logs."""
    try:
        value = int(score)
    except (TypeError, ValueError):
        value = 0
    current_index = 0
    for index, (minimum, _label) in enumerate(RATING_BADGE_MINIMA):
        if value < minimum:
            break
        current_index = index
    current_min, current_label = RATING_BADGE_MINIMA[current_index]
    next_row = RATING_BADGE_MINIMA[current_index + 1] if current_index + 1 < len(RATING_BADGE_MINIMA) else None
    if not next_row:
        return {
            "rank": current_label,
            "score": value,
            "current_min": current_min,
            "next_rank": None,
            "next_min": None,
            "needed": 0,
            "progress": 1.0,
        }
    next_min, next_label = next_row
    span = max(1, next_min - current_min)
    return {
        "rank": current_label,
        "score": value,
        "current_min": current_min,
        "next_rank": next_label,
        "next_min": next_min,
        "needed": max(0, next_min - value),
        "progress": max(0.0, min(1.0, (value - current_min) / span)),
    }


def estimate_rating_score(stats, *, skill_score=0, star_level=3, unique_level=5):
    """Return a full estimated rating breakdown."""
    stat_score = total_stat_rating_score(stats)
    unique_bonus = unique_rating_bonus(star_level, unique_level)
    try:
        skill_score_int = int(round(float(skill_score or 0)))
    except (TypeError, ValueError):
        skill_score_int = 0
    total = stat_score + unique_bonus + max(0, skill_score_int)
    return {
        "stat_score": stat_score,
        "unique_bonus": unique_bonus,
        "skill_score": max(0, skill_score_int),
        "total": total,
        "rank": rank_for_rating_score(total),
        "progress": next_rank_progress(total),
    }
