import unittest

import main


class QuickDeclareHelperTests(unittest.TestCase):
    def test_normalize_stat_accepts_aliases(self):
        self.assertEqual(main._normalize_stat("speed"), "speed")
        self.assertEqual(main._normalize_stat("SPD"), "speed")
        self.assertEqual(main._normalize_stat("STAM"), "stamina")
        self.assertEqual(main._normalize_stat("Pwr"), "power")
        self.assertEqual(main._normalize_stat("guts"), "guts")
        self.assertEqual(main._normalize_stat("wiz"), "wit")
        self.assertIsNone(main._normalize_stat("nonsense"))
        self.assertIsNone(main._normalize_stat(""))
        self.assertIsNone(main._normalize_stat(None))

    def test_normalize_style_accepts_aliases(self):
        self.assertEqual(main._normalize_style("front_runner"), "front_runner")
        self.assertEqual(main._normalize_style("front"), "front_runner")
        self.assertEqual(main._normalize_style("nige"), "front_runner")
        self.assertEqual(main._normalize_style("pace"), "pace_chaser")
        self.assertEqual(main._normalize_style("late"), "late_surger")
        self.assertEqual(main._normalize_style("end"), "end_closer")
        self.assertEqual(main._normalize_style("closer"), "end_closer")
        self.assertIsNone(main._normalize_style("running"))

    def test_build_session_from_quick_sets_primary_stat_threshold(self):
        session = main._build_session_from_quick("wit", "front_runner")
        self.assertEqual(session["primary_stat_target"]["stat"], "wit")
        # Primary stat target should equal the empirical 3-star threshold
        self.assertEqual(session["primary_stat_target"]["target_value"], 1100)
        # Stat minimum for the primary stat should equal the target so the
        # outcome classifier doesn't mark the run as failing minimums when
        # the primary stat just barely clears the threshold.
        self.assertEqual(session["stat_minimums"]["wit"], 1100)

    def test_build_session_preserves_style(self):
        session = main._build_session_from_quick("speed", "late_surger")
        self.assertEqual(session["style_target"], "late_surger")
        self.assertEqual(session["blue_spark_intent"]["preferred_color"], "speed")
        # Acceptable colors should be everything except the primary
        self.assertNotIn("speed", session["blue_spark_intent"]["acceptable_colors"])
        self.assertIn("stamina", session["blue_spark_intent"]["acceptable_colors"])

    def test_build_session_assigns_high_score_band_target(self):
        session = main._build_session_from_quick("guts", "end_closer")
        self.assertEqual(session["white_spark_intent"]["target_rank_score_band"], "high")

    def test_build_session_includes_acceptable_drift_for_color_rng(self):
        # The "right play, bad RNG" path needs to be allowed by default so a
        # career that hits all conditions but rolls wrong blue color still
        # gets the 1.45 multiplier in intent_aware_score.
        session = main._build_session_from_quick("power", "pace_chaser")
        self.assertIn("balanced_parent_with_wrong_blue", session["acceptable_drift"])


if __name__ == "__main__":
    unittest.main()
