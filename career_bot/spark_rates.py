"""Empirical spark generation rates from hakuraku.moe/notes/spark_generation.

These are observation-derived rates (n=107,159+ for blue/pink, n=460,910+
for white sparks), NOT in-game-formula rates. They are the best current
empirical model and should be updated if new community data contradicts
them. The objectives module uses these to translate raw stat / score
values into the bands that actually drive 1/2/3-star spark outcomes —
which lets the bot's learning target *conditions* (controllable) rather
than *outcomes* (RNG within a condition band).
"""


BLUE_STAR_RATES_BY_STAT_VALUE = {
    "low":  {"threshold": 600,  "rates": {1: 0.90, 2: 0.10, 3: 0.00}},
    "mid":  {"threshold": 1100, "rates": {1: 0.495, 2: 0.45, 3: 0.05}},
    "high": {"threshold": None, "rates": {1: 0.20, 2: 0.70, 3: 0.10}},
}

PINK_STAR_RATES = {1: 0.20, 2: 0.70, 3: 0.10}

WHITE_STAR_RATES_BY_RANK_SCORE = {
    "low":  {"threshold": 6500,  "rates": {1: 0.90, 2: 0.10, 3: 0.00}},
    "mid":  {"threshold": 17500, "rates": {1: 0.50, 2: 0.45, 3: 0.05}},
    "high": {"threshold": None,  "rates": {1: 0.20, 2: 0.70, 3: 0.10}},
}

UNIQUE_STAR_RATES_BY_RANK_SCORE = WHITE_STAR_RATES_BY_RANK_SCORE

# White spark generation rates: P(spark generated) = base_rate * 1.1^lineage_count
# where lineage_count is the number of times the spark appears in the
# immediate lineage (parents + grandparents). Each lineage match adds
# ~10% relative chance.
WHITE_GENERATION_BASE_RATES = {
    "white_circle":  0.20,
    "double_circle": 0.25,
    "gold":          0.40,
}
WHITE_GENERATION_LINEAGE_MULTIPLIER = 1.1


def _safe_number(value, default=0):
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def stat_value_band(value):
    """Return 'low' | 'mid' | 'high' for a stat value's effect on blue spark stars.

    Below 600: 3-star impossible (90/10/0 distribution).
    600-1099: 5% chance of 3-star.
    1100+: 10% chance of 3-star, 70% chance of 2-star — the lever every
    serious parent run should be hitting.
    """
    value = _safe_number(value, 0)
    if value < BLUE_STAR_RATES_BY_STAT_VALUE["low"]["threshold"]:
        return "low"
    if value < BLUE_STAR_RATES_BY_STAT_VALUE["mid"]["threshold"]:
        return "mid"
    return "high"


def rank_score_band(score):
    """Return 'low' | 'mid' | 'high' for a rank score's effect on white spark stars."""
    score = _safe_number(score, 0)
    if score < WHITE_STAR_RATES_BY_RANK_SCORE["low"]["threshold"]:
        return "low"
    if score < WHITE_STAR_RATES_BY_RANK_SCORE["mid"]["threshold"]:
        return "mid"
    return "high"


def expected_blue_star_distribution(stat_value):
    """Return the empirical 1*/2*/3* rate dict for a given stat value."""
    band = stat_value_band(stat_value)
    return BLUE_STAR_RATES_BY_STAT_VALUE[band]["rates"]


def expected_white_star_distribution(rank_score):
    """Return the empirical 1*/2*/3* rate dict for a given rank score."""
    band = rank_score_band(rank_score)
    return WHITE_STAR_RATES_BY_RANK_SCORE[band]["rates"]


def expected_unique_star_distribution(rank_score):
    """Unique factor stars follow the same rank-score-band distribution as whites."""
    return expected_white_star_distribution(rank_score)


def expected_white_generation_rate(base_type, lineage_count):
    """Return the probability a white spark of `base_type` is generated given
    `lineage_count` matches in the immediate lineage.

    base_type: 'white_circle' | 'double_circle' | 'gold'
    lineage_count: int (0+), capped at the rate ceiling of 1.0
    """
    base = WHITE_GENERATION_BASE_RATES.get(base_type, 0.20)
    try:
        lineage_count = max(0, int(lineage_count or 0))
    except (TypeError, ValueError):
        lineage_count = 0
    return min(1.0, base * (WHITE_GENERATION_LINEAGE_MULTIPLIER ** lineage_count))


def p_target_blue_color(stat_distribution):
    """Estimate P(blue color = stat X) given the career's stat distribution.

    Empirical data shows blue color is approximately uniform (~20% each) with
    weak proportional bias toward stronger stats. Use this as a probabilistic
    estimator, not a deterministic predictor — color is mostly RNG.

    stat_distribution: dict like {"speed": 800, "stamina": 1100, ...}
    """
    stats = ("speed", "stamina", "power", "guts", "wit")
    distribution = stat_distribution or {}
    total = sum(_safe_number(distribution.get(s)) for s in stats) or 1
    uniform_weight = 0.85
    return {
        s: uniform_weight * 0.20 + (1 - uniform_weight) * (_safe_number(distribution.get(s)) / total)
        for s in stats
    }
