import unittest

from career_bot.spark_rates import (
    expected_blue_star_distribution,
    expected_white_generation_rate,
    expected_white_star_distribution,
    p_target_blue_color,
    rank_score_band,
    stat_value_band,
)


class StatValueBandTests(unittest.TestCase):
    def test_low_below_600(self):
        self.assertEqual(stat_value_band(0), "low")
        self.assertEqual(stat_value_band(599), "low")

    def test_mid_600_to_1099(self):
        self.assertEqual(stat_value_band(600), "mid")
        self.assertEqual(stat_value_band(1099), "mid")

    def test_high_at_or_above_1100(self):
        self.assertEqual(stat_value_band(1100), "high")
        self.assertEqual(stat_value_band(1500), "high")

    def test_garbage_input_falls_to_low(self):
        self.assertEqual(stat_value_band(None), "low")
        self.assertEqual(stat_value_band("not-a-number"), "low")


class RankScoreBandTests(unittest.TestCase):
    def test_band_thresholds(self):
        self.assertEqual(rank_score_band(0), "low")
        self.assertEqual(rank_score_band(6499), "low")
        self.assertEqual(rank_score_band(6500), "mid")
        self.assertEqual(rank_score_band(17499), "mid")
        self.assertEqual(rank_score_band(17500), "high")
        self.assertEqual(rank_score_band(50000), "high")


class StarDistributionTests(unittest.TestCase):
    def test_blue_distributions_per_band(self):
        low = expected_blue_star_distribution(100)
        self.assertEqual(low[3], 0.0)
        self.assertGreater(low[1], 0.85)
        mid = expected_blue_star_distribution(800)
        self.assertGreater(mid[3], 0.0)
        self.assertLess(mid[3], 0.10)
        high = expected_blue_star_distribution(1200)
        self.assertGreaterEqual(high[3], 0.10)

    def test_white_distributions_per_band(self):
        low = expected_white_star_distribution(2000)
        self.assertEqual(low[3], 0.0)
        high = expected_white_star_distribution(20000)
        self.assertGreaterEqual(high[3], 0.10)


class WhiteGenerationRateTests(unittest.TestCase):
    def test_gold_with_lineage_count_4_matches_formula(self):
        # 0.40 * 1.1^4 ≈ 0.5856
        result = expected_white_generation_rate("gold", 4)
        self.assertAlmostEqual(result, 0.40 * (1.1 ** 4), places=4)

    def test_white_circle_with_lineage_3_matches_formula(self):
        # 0.20 * 1.1^3 ≈ 0.2662
        result = expected_white_generation_rate("white_circle", 3)
        self.assertAlmostEqual(result, 0.20 * (1.1 ** 3), places=4)

    def test_rate_capped_at_one(self):
        self.assertLessEqual(expected_white_generation_rate("gold", 50), 1.0)

    def test_unknown_type_falls_back_to_white_circle_base(self):
        result = expected_white_generation_rate("bogus", 0)
        self.assertAlmostEqual(result, 0.20, places=4)


class BlueColorEstimatorTests(unittest.TestCase):
    def test_returns_approximately_uniform(self):
        stats = {"speed": 800, "stamina": 800, "power": 800, "guts": 800, "wit": 800}
        probs = p_target_blue_color(stats)
        for value in probs.values():
            self.assertAlmostEqual(value, 0.20, places=3)

    def test_stronger_stat_skews_slightly_higher(self):
        stats = {"speed": 100, "stamina": 100, "power": 100, "guts": 100, "wit": 1200}
        probs = p_target_blue_color(stats)
        self.assertGreater(probs["wit"], probs["speed"])
        # The skew is gentle; nowhere near 100% for the dominant stat.
        self.assertLess(probs["wit"], 0.45)


if __name__ == "__main__":
    unittest.main()
