import unittest

from career_bot.presets import normalize_preset


class PresetNormalizationSmokeTests(unittest.TestCase):
    def test_null_skill_optimizer_enabled_defaults_to_enabled(self):
        preset = normalize_preset({
            "name": "test",
            "skill_optimizer_enabled": None,
        })

        self.assertIs(preset["skill_optimizer_enabled"], True)

    def test_auto_learning_recency_defaults_are_present(self):
        preset = normalize_preset({
            "name": "test",
        })

        self.assertIs(preset["auto_learning_recency_enabled"], True)
        self.assertEqual(preset["auto_learning_recency_bias"], 0.55)
        self.assertEqual(preset["auto_learning_recency_half_life"], 12)
        self.assertEqual(preset["auto_learning_recent_failure_bias"], 0.35)
        self.assertIs(preset["auto_learning_regression_enabled"], True)
        self.assertEqual(preset["auto_learning_regression_bias"], 0.7)
        self.assertEqual(preset["auto_learning_regression_window"], 5)
        self.assertEqual(preset["auto_learning_regression_floor"], 0.92)
        self.assertIs(preset["auto_learning_progression_enabled"], True)
        self.assertEqual(preset["auto_learning_progression_bias"], 0.35)
        self.assertEqual(preset["auto_learning_progression_window"], 5)
        self.assertEqual(preset["auto_learning_progression_delta"], 500)
        self.assertEqual(preset["auto_learning_apply_scope"], "")
        self.assertIs(preset["auto_learning_monotonic_apply_enabled"], True)
        self.assertIs(preset["auto_learning_corrective_apply_enabled"], True)
        self.assertIs(preset["auto_learning_learn_from_complete_logs"], True)
        self.assertEqual(preset["auto_learning_monotonic_min_improvement"], 1.0)
        self.assertEqual(preset["auto_learning_monotonic_allowed_drop"], 0.0)
        self.assertIs(preset["calendar_race_prebuy_enabled"], True)
        self.assertEqual(preset["calendar_race_prebuy_grades"], ["G1", "G2", "G3", "OP", "PRE-OP"])
        self.assertIs(preset["calendar_race_prebuy_all_scheduled"], True)
        self.assertIs(preset["scheduled_race_clean_record_mode"], True)
        self.assertEqual(preset["calendar_race_clean_prebuy_min_sp"], 120)
        self.assertEqual(preset["calendar_race_clean_prebuy_budget"], 1000)
        self.assertEqual(preset["calendar_race_clean_prebuy_keep_sp"], 0)
        self.assertEqual(preset["calendar_race_clean_prebuy_max_skills"], 8)
        self.assertEqual(preset["calendar_race_clean_prebuy_target_probability"], 0.93)
        self.assertEqual(preset["scheduled_race_safety_training_lookahead_turns"], 18)
        self.assertEqual(preset["scheduled_race_safety_requirement_scale"], 0.94)
        self.assertEqual(preset["scheduled_race_safety_bonus_cap"], 0.75)
        self.assertIs(preset["scheduled_race_force_calendar"], True)
        self.assertIs(preset["scheduled_race_respect_training"], False)
        self.assertIs(preset["scheduled_race_skip_if_stamina_low"], False)
        self.assertIs(preset["scheduled_race_skip_off_aptitude"], False)
        # Aggressive defaults (ship-everything mode): bot front-loads
        # SP into mid-career G1s instead of hoarding for end-of-career.
        self.assertEqual(preset["calendar_race_prebuy_min_sp"], 280)
        self.assertEqual(preset["calendar_race_prebuy_budget"], 850)
        self.assertEqual(preset["calendar_race_prebuy_keep_sp"], 100)
        self.assertEqual(preset["calendar_race_prebuy_max_skills"], 4)
        self.assertIs(preset["calendar_optional_fillers_enabled"], False)
        self.assertEqual(preset["training_policy_model_weight"], 0.35)

    def test_null_auto_learning_corrective_flags_default_to_enabled(self):
        preset = normalize_preset({
            "name": "test",
            "auto_learning_corrective_apply_enabled": None,
            "auto_learning_learn_from_complete_logs": None,
        })

        self.assertIs(preset["auto_learning_corrective_apply_enabled"], True)
        self.assertIs(preset["auto_learning_learn_from_complete_logs"], True)
        self.assertEqual(preset["training_policy_model_max_bonus"], 0.05)
        self.assertEqual(preset["training_policy_model_runtime_cap"], 0.05)
        self.assertIs(preset["training_policy_disable_on_untrusted_metadata"], True)
        self.assertEqual(preset["training_policy_max_trusted_score"], 25000)
        self.assertIs(preset["learning_policy_objective_gate_enabled"], True)
        self.assertEqual(preset["learning_policy_min_rank_score"], 15000)
        self.assertEqual(preset["learning_policy_min_internal_score"], 17500)
        self.assertEqual(preset["learning_policy_min_stat_total"], 3300)
        self.assertEqual(preset["learning_policy_min_actions"], 20)
        self.assertEqual(preset["learning_policy_max_race_losses"], 0)
        self.assertEqual(preset["learning_policy_max_g1_losses"], 0)
        self.assertEqual(preset["learning_policy_min_race_total_for_clean_record"], 8)
        self.assertIs(preset["training_policy_challenger_enabled"], True)
        self.assertEqual(preset["training_policy_challenger_promotion_passes"], 2)
        self.assertEqual(preset["training_policy_challenger_min_margin"], 0.01)
        self.assertEqual(preset["training_policy_challenger"], {})
        self.assertEqual(preset["run_mode_policy"], {})
        self.assertIs(preset["low_hp_wit_training_override_enabled"], True)
        self.assertEqual(preset["low_hp_wit_training_max_failure"], 25)
        self.assertEqual(preset["low_hp_wit_training_min_score"], 0.08)
        self.assertEqual(preset["low_hp_wit_training_substitute_min_score"], 0.01)
        self.assertEqual(preset["non_wit_high_value_training_max_failure"], 24)

    def test_learned_training_weights_are_clamped_to_safe_runtime_bounds(self):
        preset = normalize_preset({
            "name": "test",
            "extra_weight": [[0.9, -0.9, 0.4, -0.4, 0.0] for _ in range(4)],
            "base_score": [0.5, -0.5, 0.0, 0.0, 0.0],
            "stat_value_multiplier": [0.5, 0.5, 0.5, 0.5, 0.5, 0.5],
            "score_value": [[0.5, 0.5, 0.5, 0.5] for _ in range(5)],
        })

        self.assertEqual(preset["extra_weight"][0], [0.25, -0.12, 0.25, -0.12, 0.0])
        self.assertEqual(preset["base_score"][:2], [0.12, -0.08])
        # Upper clamp widened to 0.050 so SS-push profiles can prioritize
        # high-gain training tiles over low-output heuristics.
        self.assertEqual(preset["stat_value_multiplier"], [0.05, 0.05, 0.05, 0.05, 0.05, 0.01])
        self.assertEqual(preset["score_value"][0], [0.18, 0.18, 0.01, 0.18])

    def test_deck_adaptability_hygiene_blocks_poisoned_learned_policy(self):
        preset = normalize_preset({
            "name": "test",
            "_deck_type_counts": [2, 0, 1, 0, 2],
            "score_value": [[0.0, 0.0, 0.0, 0.0] for _ in range(5)],
            "stat_value_multiplier": [0.002, 0.002, 0.002, 0.002, 0.002, 0.01],
            "extra_weight": [[-0.12, -0.12, -0.12, -0.12, -0.12] for _ in range(4)],
            "base_score": [-0.08, -0.08, -0.08, -0.08, -0.08],
            "expect_attribute": [1200, 1200, 1200, 1200, 1200],
        })

        self.assertEqual(preset["score_value"][0][:2], [0.055, 0.06])
        self.assertEqual(preset["stat_value_multiplier"][:5], [0.035, 0.002, 0.03, 0.002, 0.035])
        self.assertEqual(preset["extra_weight"][0], [-0.02, -0.12, -0.02, -0.12, -0.02])
        self.assertEqual(preset["base_score"], [-0.02, -0.08, -0.02, -0.08, -0.02])
        self.assertEqual(preset["expect_attribute"], [1200, 900, 1200, 800, 1200])


if __name__ == "__main__":
    unittest.main()
