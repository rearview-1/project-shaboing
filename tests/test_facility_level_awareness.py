import unittest

from career_bot.learning import selected_training_action, training_feature_from_option
from career_bot.scenarios.mant import MantStrategy
from career_bot.scenarios.mant_stamina import stamina_demand_multiplier
from career_bot.training_policy import _action_features, command_features


def _command(command_id=101, stat_gain=20):
    return {
        "command_id": command_id,
        "command_type": 1,
        "failure_rate": 0,
        "training_partner_array": [1, 2],
        "tips_event_partner_array": [],
        "params_inc_dec_info_array": [{"target_type": 1, "value": stat_gain}],
    }


def _chara(turn=12, level=3, progress=3):
    return {
        "turn": turn,
        "vital": 90,
        "max_vital": 100,
        "training_level_info_array": [
            {"command_id": 101, "level": level, "progress": progress}
        ],
        "evaluation_info_array": [],
    }


class FacilityLevelBonusTests(unittest.TestCase):
    def setUp(self):
        self.strategy = MantStrategy()

    def test_levelup_triggering_training_gets_bonus_early_career(self):
        bonus = self.strategy._facility_level_training_bonus(_command(), _chara(turn=12, level=3, progress=3), {}, 12)

        self.assertGreater(bonus, 0.18)
        self.assertLess(bonus, 0.30)

    def test_levelup_triggering_training_is_ignored_too_late(self):
        bonus = self.strategy._facility_level_training_bonus(_command(), _chara(turn=70, level=3, progress=3), {}, 70)

        self.assertEqual(bonus, 0.0)

    def test_no_bonus_when_at_max_level(self):
        bonus = self.strategy._facility_level_training_bonus(_command(), _chara(turn=20, level=5, progress=0), {}, 20)

        self.assertEqual(bonus, 0.0)

    def test_no_bonus_when_data_missing(self):
        bonus = self.strategy._facility_level_training_bonus(_command(), {"turn": 20}, {}, 20)

        self.assertEqual(bonus, 0.0)

    def test_training_understanding_surfaces_facility_state(self):
        command = _command()
        command["_facility_level_bonus"] = 0.20
        understanding = self.strategy._training_decision_understanding(command, _chara(turn=12, level=3, progress=3), {})
        signals = understanding["signals"]

        self.assertEqual(signals["facility_level"], 3)
        self.assertEqual(signals["facility_progress"], 3)
        self.assertEqual(signals["facility_until_next_level"], 1)
        self.assertTrue(signals["facility_triggers_level_up"])
        self.assertIn("facility_levelup", understanding["intent_tags"])


class FacilityPolicyFeatureTests(unittest.TestCase):
    def test_command_features_include_facility_level_state(self):
        feats = command_features(_command(), _chara(turn=18, level=4, progress=3))

        self.assertEqual(feats["facility_level"], 4 / 5.0)
        self.assertEqual(feats["facility_progress"], 3 / 4.0)
        self.assertEqual(feats["facility_levelup_next_train"], 1.0)
        self.assertEqual(feats["facility_is_max_level"], 0.0)

    def test_action_features_read_facility_state_from_action_or_understanding(self):
        action = {
            "turn": 18,
            "weighted_gain": 20,
            "failure_rate": 0,
            "partner_count": 2,
            "deck_partner_count": 2,
            "rainbow_count": 0,
            "hint_count": 0,
            "high_bond_count": 0,
            "hp": 90,
            "stat_gain": {"speed": 20},
            "decision_understanding": {
                "signals": {
                    "facility_level": 4,
                    "facility_progress": 3,
                    "facility_until_next_level": 1,
                }
            },
        }

        feats = _action_features(action)

        self.assertEqual(feats["facility_level"], 4 / 5.0)
        self.assertEqual(feats["facility_progress"], 3 / 4.0)
        self.assertEqual(feats["facility_levelup_next_train"], 1.0)

    def test_training_feature_from_option_preserves_facility_fields(self):
        feature = training_feature_from_option({
            "command_id": 101,
            "stat_gain": {"speed": 20},
            "facility_level": 4,
            "facility_progress": 3,
            "facility_until_next_level": 1,
        })

        self.assertEqual(feature["facility_level"], 4)
        self.assertEqual(feature["facility_progress"], 3)
        self.assertEqual(feature["facility_until_next_level"], 1)

    def test_selected_training_action_uses_understanding_facility_fields_without_snapshot(self):
        action = selected_training_action({
            "turn": 18,
            "selected_action": "train",
            "current_command": {"command_id": 101},
            "decision_understanding": {
                "signals": {
                    "facility_level": 3,
                    "facility_progress": 3,
                    "facility_until_next_level": 1,
                }
            },
        })

        self.assertEqual(action["facility_level"], 3)
        self.assertEqual(action["facility_progress"], 3)
        self.assertEqual(action["facility_until_next_level"], 1)


class StaminaDemandTests(unittest.TestCase):
    def test_long_front_runner_demands_more_stamina_than_sprint_front_runner(self):
        sprint = stamina_demand_multiplier("front_runner", "sprint", recovery_count=0)
        long = stamina_demand_multiplier("front_runner", "long", recovery_count=1)

        self.assertGreater(long, sprint)
        self.assertEqual(sprint, 0.8)

    def test_more_planned_recovery_reduces_long_stamina_multiplier(self):
        one_recovery = stamina_demand_multiplier("late_surger", "long", recovery_count=1)
        two_recovery = stamina_demand_multiplier("late_surger", "long", recovery_count=2)

        self.assertLess(two_recovery, one_recovery)


if __name__ == "__main__":
    unittest.main()
