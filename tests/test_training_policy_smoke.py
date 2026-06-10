import unittest

from career_bot.presets import expect_attribute_profile_lookup_keys
from career_bot.scenarios.mant import MantStrategy
from career_bot.training_policy import _action_weight, build_training_policy_model, command_features, score_training_policy_bonus


def action(idx, turn=20, score=40, understanding=None):
    row = {
        "idx": idx,
        "turn": turn,
        "weighted_gain": score,
        "failure_rate": 0,
        "partner_count": 2,
        "deck_partner_count": 2,
        "rainbow_count": 1 if idx == 1 else 0,
        "hint_count": 0,
        "high_bond_count": 1,
        "hp": 70,
        "stat_gain": {"stamina" if idx == 1 else "speed": score},
    }
    if understanding:
        row["decision_understanding"] = understanding
    return row


def action_with_alternatives(chosen_idx, turn=20):
    rows = [
        {
            "_idx": 0,
            "idx": 0,
            "turn": turn,
            "weighted_gain": 18,
            "failure_rate": 0,
            "partner_count": 1,
            "deck_partner_count": 1,
            "rainbow_count": 0,
            "hint_count": 0,
            "high_bond_count": 1,
            "hp": 70,
            "stat_gain": {"speed": 18},
            "command_id": 101,
        },
        {
            "_idx": 1,
            "idx": 1,
            "turn": turn,
            "weighted_gain": 26,
            "failure_rate": 0,
            "partner_count": 2,
            "deck_partner_count": 2,
            "rainbow_count": 1,
            "hint_count": 0,
            "high_bond_count": 2,
            "hp": 70,
            "stat_gain": {"stamina": 26},
            "command_id": 105,
        },
    ]
    chosen = rows[chosen_idx]
    return {
        "idx": chosen_idx,
        "command_id": chosen["command_id"],
        "turn": turn,
        "weighted_gain": chosen["weighted_gain"],
        "failure_rate": chosen["failure_rate"],
        "partner_count": chosen["partner_count"],
        "deck_partner_count": chosen["deck_partner_count"],
        "rainbow_count": chosen["rainbow_count"],
        "hint_count": chosen["hint_count"],
        "high_bond_count": chosen["high_bond_count"],
        "hp": chosen["hp"],
        "stat_gain": chosen["stat_gain"],
        "training_snapshot": {"trainings": rows},
    }


def training_command(command_id):
    return {
        "command_type": 1,
        "command_id": command_id,
        "is_enable": 1,
        "failure_rate": 0,
        "training_partner_array": [1, 2],
        "tips_event_partner_array": [],
        "params_inc_dec_info_array": [
            {"target_type": 2 if command_id == 105 else 1, "value": 20},
            {"target_type": 10, "value": -18},
        ],
    }


class TrainingPolicySmokeTests(unittest.TestCase):
    def test_policy_weighting_boosts_strong_manual_early_actions_over_weak_bot_ones(self):
        manual_sample = {
            "source": "manual_hachimi",
            "score": 18194,
            "sample_weight": 1.45,
            "learning_metadata": {"outcome_assessment": {"overall": "objective_success"}},
        }
        weak_bot_sample = {
            "source": "bot",
            "score": 11000,
            "sample_weight": 1.0,
            "learning_metadata": {"outcome_assessment": {"overall": "partial_success"}},
        }
        early_action = {"turn": 20, "decision_quality": 1.0}

        self.assertGreater(
            _action_weight(manual_sample, early_action),
            _action_weight(weak_bot_sample, early_action),
        )

    def test_policy_model_learns_top_action_bias(self):
        top = [{"score": 12000, "sample_weight": 1.0, "actions": [action(1) for _ in range(8)]}]
        bottom = [{"score": 6000, "sample_weight": 1.0, "actions": [action(0) for _ in range(8)]}]

        model = build_training_policy_model(top, bottom, top + bottom, min_actions=4)

        self.assertTrue(model["enabled"])
        self.assertGreater(model["command_bias"]["1"], 0)
        self.assertLess(model["command_bias"]["0"], 0)

    def test_live_mant_score_uses_bounded_policy_bonus(self):
        top = [{"score": 12000, "sample_weight": 1.0, "actions": [action(1) for _ in range(8)]}]
        bottom = [{"score": 6000, "sample_weight": 1.0, "actions": [action(0) for _ in range(8)]}]
        model = build_training_policy_model(top, bottom, top + bottom, min_actions=4)
        preset = {
            "training_policy_model": model,
            "training_policy_model_enabled": True,
            "training_policy_model_weight": 1.0,
            "training_policy_model_max_bonus": 0.12,
            "expect_attribute": [1200, 1200, 1200, 1200, 1200],
            "score_value": [[0, 0, 0, 0]] * 5,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0, 0, 0, 0, 0, 0],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
            "compensate_failure": True,
            # Disable Stat Priority Architecture so this test isolates the
            # learned policy bonus signal — otherwise the structural Speed
            # bias overrides the learned Stamina preference by design.
            "stat_priority_architecture_enabled": False,
        }
        chara = {
            "turn": 20,
            "vital": 70,
            "max_vital": 100,
            "speed": 200,
            "stamina": 200,
            "power": 200,
            "guts": 200,
            "wiz": 200,
            "evaluation_info_array": [{"target_id": 1, "evaluation": 90}, {"target_id": 2, "evaluation": 90}],
        }

        stamina_bonus = score_training_policy_bonus(training_command(105), {}, chara, preset)
        speed_bonus = score_training_policy_bonus(training_command(101), {}, chara, preset)
        self.assertGreater(stamina_bonus, speed_bonus)

        strategy = MantStrategy()
        stamina_score = strategy._score_command(training_command(105), {}, chara, preset)
        speed_score = strategy._score_command(training_command(101), {}, chara, preset)
        self.assertGreater(stamina_score, speed_score)

    def test_live_policy_ignores_poisoned_score_ranges(self):
        top = [{"score": 12000, "sample_weight": 1.0, "actions": [action(1) for _ in range(8)]}]
        bottom = [{"score": 6000, "sample_weight": 1.0, "actions": [action(0) for _ in range(8)]}]
        model = build_training_policy_model(top, bottom, top + bottom, min_actions=4)
        preset = {
            "training_policy_model": model,
            "training_policy_model_enabled": True,
            "training_policy_model_weight": 1.0,
            "training_policy_model_max_bonus": 0.16,
            "learning_metadata": {
                "top_score_range": [18000, 61654],
                "bottom_score_range": [2000, 34586],
            },
        }

        bonus = score_training_policy_bonus(training_command(105), {}, {"turn": 20, "vital": 70}, preset)

        self.assertEqual(bonus, 0.0)

    def test_live_policy_runtime_cap_limits_promoted_models(self):
        model = {
            "enabled": True,
            "max_abs_bonus": 0.16,
            "feature_weights": {"weighted_gain": 10.0},
            "command_bias": {},
        }
        preset = {
            "training_policy_model": model,
            "training_policy_model_enabled": True,
            "training_policy_model_weight": 1.0,
            "training_policy_model_max_bonus": 0.16,
            "training_policy_model_runtime_cap": 0.04,
        }

        bonus = score_training_policy_bonus(training_command(105), {}, {"turn": 20, "vital": 70}, preset)

        self.assertLessEqual(abs(bonus), 0.03)

    def test_model_emits_objective_bucket_submodel(self):
        top = [{
            "score": 12000,
            "sample_weight": 1.0,
            "actions": [action(1) for _ in range(8)],
            "learning_metadata": {
                "session": {
                    "primary_stat_target": {"stat": "stamina"},
                    "blue_spark_intent": {"preferred_color": "stamina"},
                }
            },
        }]
        bottom = [{
            "score": 6000,
            "sample_weight": 1.0,
            "actions": [action(0) for _ in range(8)],
            "learning_metadata": {
                "session": {
                    "primary_stat_target": {"stat": "stamina"},
                    "blue_spark_intent": {"preferred_color": "stamina"},
                }
            },
        }]

        model = build_training_policy_model(top, bottom, top + bottom, min_actions=4)

        self.assertIn("bucket_models", model)
        self.assertTrue(any(key.startswith("stamina_stamina|") for key in model["bucket_models"]))

    def test_model_tracks_pairwise_preference_examples(self):
        top = [{"score": 12000, "sample_weight": 1.0, "actions": [action_with_alternatives(1) for _ in range(8)]}]
        bottom = [{"score": 6000, "sample_weight": 1.0, "actions": [action_with_alternatives(0) for _ in range(8)]}]

        model = build_training_policy_model(top, bottom, top + bottom, min_actions=4)

        self.assertTrue(model["enabled"])
        self.assertGreater(model.get("pairwise_preference_count", 0), 0)

    def test_model_can_learn_from_understanding_signals(self):
        blue_understanding = {
            "signals": {
                "blue_target_match": True,
                "late_white_pressure_multiplier": 1.0,
                "race_pressure_bonus": 0.0,
                "near_rainbow_count": 0,
                "near_rainbow_bonus": 0.0,
                "lagging_for_selected_stat": True,
            }
        }
        neutral_understanding = {
            "signals": {
                "blue_target_match": False,
                "late_white_pressure_multiplier": 1.0,
                "race_pressure_bonus": 0.0,
                "near_rainbow_count": 0,
                "near_rainbow_bonus": 0.0,
                "lagging_for_selected_stat": False,
            }
        }
        top = [{"score": 12000, "sample_weight": 1.0, "actions": [action(1, understanding=blue_understanding) for _ in range(8)]}]
        bottom = [{"score": 6000, "sample_weight": 1.0, "actions": [action(1, understanding=neutral_understanding) for _ in range(8)]}]

        model = build_training_policy_model(top, bottom, top + bottom, min_actions=4)

        self.assertTrue(model["enabled"])
        self.assertGreater(model["feature_weights"].get("blue_goal_training", 0.0), 0.0)

    def test_model_clamps_known_good_features_non_negative(self):
        bad_understanding = {
            "signals": {
                "blue_target_match": True,
                "race_pressure_bonus": 0.12,
                "near_rainbow_count": 2,
                "near_rainbow_bonus": 0.12,
                "lagging_for_selected_stat": True,
            }
        }
        neutral_understanding = {
            "signals": {
                "blue_target_match": False,
                "race_pressure_bonus": 0.0,
                "near_rainbow_count": 0,
                "near_rainbow_bonus": 0.0,
                "lagging_for_selected_stat": False,
            }
        }
        top = [{"score": 12000, "sample_weight": 1.0, "actions": [action(1, understanding=neutral_understanding) for _ in range(8)]}]
        bottom = [{"score": 6000, "sample_weight": 1.0, "actions": [action(1, understanding=bad_understanding) for _ in range(8)]}]

        model = build_training_policy_model(top, bottom, top + bottom, min_actions=4)
        weights = model["feature_weights"]

        self.assertEqual(weights.get("blue_goal_training"), 0.0)
        self.assertEqual(weights.get("lagging_stat_alignment"), 0.0)
        self.assertGreaterEqual(weights.get("race_demand_pressure"), 0.0)
        self.assertGreaterEqual(weights.get("rainbow_setup_pressure"), 0.0)
        self.assertGreaterEqual(weights.get("first_summer_friendship_pressure"), 0.02)
        self.assertGreaterEqual(weights.get("friendship_unlocked_gap"), 0.02)

    def test_model_keeps_friendship_features_even_below_delta_threshold(self):
        top = [{"score": 12000, "sample_weight": 1.0, "actions": [action(1) for _ in range(8)]}]
        bottom = [{"score": 6000, "sample_weight": 1.0, "actions": [action(1) for _ in range(8)]}]

        model = build_training_policy_model(top, bottom, top + bottom, min_actions=4)

        self.assertIn("first_summer_friendship_pressure", model["feature_weights"])
        self.assertIn("friendship_unlocked_gap", model["feature_weights"])

    def test_command_features_use_contextual_expect_attribute_profile(self):
        preset = {
            "expect_attribute": [1200, 1200, 1200, 1200, 1200],
            "desired_parent_sparks": {"blue": ["Speed"], "pink": [], "green": [], "white": []},
            "skill_profile_style": "late_surger",
            "skill_profile_distance": "mile",
            "_run_context": {
                "support_cards": [
                    {"type": "Speed"},
                    {"type": "Speed"},
                    {"type": "Speed"},
                    {"type": "Stamina"},
                    {"type": "Wit"},
                ],
                "deck_quality_bucket": 2,
            },
        }
        keys = expect_attribute_profile_lookup_keys(preset)
        preset["expect_attribute_profiles"] = {
            keys[0]: [700, 800, 900, 650, 750],
        }
        chara = {
            "turn": 20,
            "vital": 70,
            "max_vital": 100,
            "speed": 650,
            "stamina": 200,
            "power": 200,
            "guts": 200,
            "wiz": 200,
            "evaluation_info_array": [],
        }

        global_features = command_features(training_command(101), chara, {"expect_attribute": [1200, 1200, 1200, 1200, 1200]})
        contextual_features = command_features(training_command(101), chara, preset)

        self.assertLess(contextual_features["under_target"], global_features["under_target"])


if __name__ == "__main__":
    unittest.main()
