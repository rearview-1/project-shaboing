from career_bot.rating import (
    estimate_rating_score,
    rank_for_rating_score,
    stat_rating_score,
    total_stat_rating_score,
    unique_rating_bonus,
)


def test_stat_rating_curve_matches_umatools_boundaries():
    assert stat_rating_score(0) == 0
    assert stat_rating_score(1200) == 3841
    assert stat_rating_score(2000) == 14280
    assert stat_rating_score(2500) == 23905


def test_rating_badge_thresholds_match_game_rank_score():
    assert rank_for_rating_score(17499) == "S+"
    assert rank_for_rating_score(17500) == "SS"
    assert rank_for_rating_score(19199) == "SS"
    assert rank_for_rating_score(19200) == "SS+"
    assert rank_for_rating_score(19599) == "SS+"
    assert rank_for_rating_score(19600) == "UG"


def test_rating_breakdown_uses_stats_unique_and_skills():
    stats = {"speed": 767, "stamina": 672, "power": 620, "guts": 578, "wit": 1142}
    assert total_stat_rating_score(stats) == 8791
    assert unique_rating_bonus(star_level=3, unique_level=5) == 850
    breakdown = estimate_rating_score(stats, skill_score=3479, star_level=3, unique_level=5)
    assert breakdown["total"] == 13120
    assert breakdown["rank"] == "A+"
