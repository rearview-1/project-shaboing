import unittest

from career_bot.objectives import (
    DEFAULT_SESSION,
    classify_outcome,
    intent_aware_score,
    normalize_session,
    objective_bucket_key,
    session_from_parent_farming_targets,
)


def _wit_session(drift=None):
    return {
        "session_id": "wit_run",
        "primary_stat_target": {"stat": "wit", "target_value": 1100, "ideal_value": 1180},
        "blue_spark_intent": {
            "preferred_color": "wit",
            "acceptable_colors": ["stamina", "power"],
            "minimum_star_level": 2,
        },
        "white_spark_intent": {
            "minimum_count": 6,
            "high_value_targets": ["nimble_navigator"],
            "preferred_targets_from_schedule": [],
            "target_rank_score_band": "high",
        },
        "stat_minimums": {"speed": 700, "stamina": 600, "power": 700, "guts": 400, "wit": 1100},
        "race_intent": {"treat_wins_as_negative": False, "expected_losses": [], "must_win": []},
        "lineage_intent": {"target_affinity_tier": "high", "lineage_overlap_targets": []},
        "acceptable_drift": drift or [],
        "deck_id": "wit_premium",
    }


def _good_stats():
    return {"speed": 950, "stamina": 700, "power": 800, "guts": 500, "wit": 1180}


class NormalizeSessionTests(unittest.TestCase):
    def test_none_returns_default(self):
        result = normalize_session(None)
        self.assertEqual(result["session_id"], "default_balanced")

    def test_partial_input_fills_defaults(self):
        result = normalize_session({"session_id": "x"})
        self.assertEqual(result["session_id"], "x")
        self.assertEqual(result["primary_stat_target"]["stat"], None)
        self.assertEqual(result["acceptable_drift"], [])

    def test_idempotent(self):
        once = normalize_session(_wit_session())
        twice = normalize_session(once)
        self.assertEqual(once, twice)

    def test_parent_farming_session_requires_clean_record(self):
        session = session_from_parent_farming_targets(
            desired_parent_sparks={"blue": ["Power"], "white": ["NHK Mile C."]},
            style_target="late_surger",
        )
        self.assertEqual(session["primary_stat_target"]["stat"], "power")
        self.assertTrue(session["race_intent"]["require_clean_record"])
        self.assertEqual(session["white_spark_intent"]["target_rank_score_band"], "high")


class ClassifyOutcomeTests(unittest.TestCase):
    def test_objective_success_when_all_conditions_and_color_hit(self):
        session = _wit_session()
        sparks = [{"type": "blue", "name": "wit", "star_level": 3}]
        result = classify_outcome(_good_stats(), sparks, [], 20000, session)
        self.assertEqual(result["overall"], "objective_success")

    def test_alternative_success_when_acceptable_color_hits(self):
        session = _wit_session()
        sparks = [{"type": "blue", "name": "stamina", "star_level": 2}]
        result = classify_outcome(_good_stats(), sparks, [], 20000, session)
        self.assertEqual(result["overall"], "alternative_success")

    def test_conditions_met_color_whiffed_when_drift_allows(self):
        session = _wit_session(drift=["balanced_parent_with_wrong_blue"])
        sparks = [{"type": "blue", "name": "guts", "star_level": 1}]
        result = classify_outcome(_good_stats(), sparks, [], 20000, session)
        self.assertEqual(result["overall"], "conditions_met_color_whiffed")

    def test_partial_success_when_score_band_misses(self):
        session = _wit_session()
        sparks = [{"type": "blue", "name": "wit", "star_level": 2}]
        # Score 10000 lands in "mid" band; session asks for "high"
        result = classify_outcome(_good_stats(), sparks, [], 10000, session)
        self.assertIn(result["overall"], {"partial_success"})

    def test_run_failure_when_minimums_missed(self):
        session = _wit_session()
        bad_stats = {"speed": 100, "stamina": 100, "power": 100, "guts": 100, "wit": 100}
        result = classify_outcome(bad_stats, [], [], 1000, session)
        self.assertEqual(result["overall"], "run_failure")

    def test_parent_farming_session_marks_race_loss_as_failure(self):
        session = session_from_parent_farming_targets(
            desired_parent_sparks={"blue": ["Wit"]},
            style_target="late_surger",
        )
        sparks = [{"type": "blue", "name": "wit", "star_level": 3}]
        race_results = [{"program_id": 123, "won": False}]
        result = classify_outcome(_good_stats(), sparks, race_results, 20000, session)
        self.assertEqual(result["race_loss_count"], 1)
        self.assertFalse(result["race_intent_aligned"])
        self.assertEqual(result["overall"], "run_failure")


class IntentAwareScoreTests(unittest.TestCase):
    def test_conditions_met_color_whiffed_uses_1_45_multiplier(self):
        outcome = {
            "overall": "conditions_met_color_whiffed",
            "primary_stat_value_band": "high",
            "rank_score_band": "high",
            "white_high_value_count": 0,
        }
        # 1.45 × 1.05 × 1.05 ≈ 1.598
        result = intent_aware_score(20000, outcome, base_weight=1.0)
        self.assertGreater(result, 1.55)
        self.assertLess(result, 1.65)

    def test_run_failure_drops_to_0_4(self):
        outcome = {
            "overall": "run_failure",
            "primary_stat_value_band": "low",
            "rank_score_band": "low",
            "white_high_value_count": 0,
        }
        result = intent_aware_score(2000, outcome, base_weight=1.0)
        self.assertAlmostEqual(result, 0.4, places=3)

    def test_clamped_to_max_2(self):
        outcome = {
            "overall": "objective_success",
            "primary_stat_value_band": "high",
            "rank_score_band": "high",
            "white_high_value_count": 10,
        }
        result = intent_aware_score(50000, outcome, base_weight=2.0)
        self.assertLessEqual(result, 2.0)

    def test_clamped_to_min_0_3(self):
        outcome = {
            "overall": "run_failure",
            "primary_stat_value_band": "low",
            "rank_score_band": "low",
            "white_high_value_count": 0,
        }
        result = intent_aware_score(0, outcome, base_weight=0.1)
        self.assertGreaterEqual(result, 0.3)


class ObjectiveBucketKeyTests(unittest.TestCase):
    def test_separates_by_primary_and_blue_preference(self):
        a = objective_bucket_key(_wit_session())
        speed_session = _wit_session()
        speed_session["primary_stat_target"]["stat"] = "speed"
        speed_session["blue_spark_intent"]["preferred_color"] = "speed"
        b = objective_bucket_key(speed_session)
        self.assertNotEqual(a, b)
        self.assertEqual(a, "wit_wit")
        self.assertEqual(b, "speed_speed")

    def test_default_session_yields_balanced_any(self):
        key = objective_bucket_key(DEFAULT_SESSION)
        self.assertEqual(key, "balanced_any")


if __name__ == "__main__":
    unittest.main()
