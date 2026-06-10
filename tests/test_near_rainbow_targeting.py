"""Near-rainbow bond targeting.

Training a partner whose bond is in [60, 79] is high-value beyond the
immediate stat gain because it advances them toward 80 — the rainbow
threshold that unlocks the rainbow multiplier on EVERY subsequent
training with that partner. The bot gets a small direct bonus in the
mant scorer so it can act on this immediately, plus a new feature in
the training_policy_model so the learned weights pick it up too."""

import unittest

from career_bot.scenarios.mant import MantStrategy
from career_bot.training_policy import command_features, _action_features


def _chara(turn=20, bonds=None, vital=100, max_vital=100):
    return {
        "turn": turn,
        "vital": vital,
        "max_vital": max_vital,
        "evaluation_info_array": [
            {"target_id": pid, "evaluation": bond}
            for pid, bond in (bonds or {}).items()
        ],
    }


def _command(partner_ids, hint_ids=None, stat_gain=15, command_id=101):
    return {
        "command_id": command_id,
        "command_type": 1,
        "training_partner_array": list(partner_ids),
        "tips_event_partner_array": list(hint_ids or []),
        "failure_rate": 0,
        "params_inc_dec_info_array": [{"target_type": 1, "value": stat_gain}],
    }


class NearRainbowFeatureTests(unittest.TestCase):
    def test_feature_counts_partners_in_60_79_band(self):
        chara = _chara(bonds={1: 65, 2: 78, 3: 79, 4: 80, 5: 59, 6: 30})
        command = _command(partner_ids=[1, 2, 3, 4, 5, 6])
        feats = command_features(command, chara)
        # Partners 1, 2, 3 are in [60, 79). Partner 4 is exactly 80 (rainbow,
        # not near-rainbow). Partner 5 is 59 (just below). Partner 6 is 30.
        self.assertEqual(feats["near_rainbow_count"], 3 / 3.0)  # clamped/scaled

    def test_feature_separates_deck_partners(self):
        # Partners 1-6 are deck; bond=70 for some, others above 80.
        chara = _chara(bonds={1: 70, 2: 70, 7: 70})  # 1, 2 deck; 7 non-deck
        command = _command(partner_ids=[1, 2, 7])
        feats = command_features(command, chara)
        # 3 partners total in near-rainbow band; 2 of them are deck partners.
        self.assertEqual(feats["near_rainbow_count"], 3 / 3.0)
        self.assertEqual(feats["near_rainbow_deck_count"], 2 / 3.0)

    def test_zero_partners_in_band_returns_zero(self):
        chara = _chara(bonds={1: 95, 2: 100, 3: 50})
        command = _command(partner_ids=[1, 2, 3])
        feats = command_features(command, chara)
        self.assertEqual(feats["near_rainbow_count"], 0.0)


class NearRainbowDirectBonusTests(unittest.TestCase):
    """The direct mant.py bonus fires regardless of whether the
    training_policy_model has converged on a weight for the feature."""

    def setUp(self):
        self.strategy = MantStrategy()

    def test_bonus_fires_with_partners_in_band(self):
        chara = _chara(turn=20, bonds={1: 65, 2: 75, 3: 70})
        command = _command(partner_ids=[1, 2, 3])
        bonus = self.strategy._near_rainbow_training_bonus(command, chara, turn=20)
        # 3 partners in band, 0.04 per → 0.12 (at the cap).
        self.assertAlmostEqual(bonus, 0.12, places=4)

    def test_bonus_zero_when_no_partners_in_band(self):
        chara = _chara(turn=20, bonds={1: 85, 2: 100})
        command = _command(partner_ids=[1, 2])
        bonus = self.strategy._near_rainbow_training_bonus(command, chara, turn=20)
        self.assertEqual(bonus, 0.0)

    def test_bonus_zero_when_no_partners_at_all(self):
        chara = _chara(turn=20)
        command = _command(partner_ids=[])
        bonus = self.strategy._near_rainbow_training_bonus(command, chara, turn=20)
        self.assertEqual(bonus, 0.0)

    def test_bonus_tapers_in_senior_year(self):
        chara_early = _chara(turn=20, bonds={1: 70, 2: 70})
        chara_late = _chara(turn=65, bonds={1: 70, 2: 70})
        command = _command(partner_ids=[1, 2])
        early = self.strategy._near_rainbow_training_bonus(command, chara_early, turn=20)
        late = self.strategy._near_rainbow_training_bonus(command, chara_late, turn=65)
        # Late-phase bonus should be ~35% of early-phase.
        self.assertGreater(early, late)
        self.assertAlmostEqual(late / early, 0.35, places=2)

    def test_bonus_capped_when_many_partners_in_band(self):
        chara = _chara(turn=20, bonds={1: 65, 2: 70, 3: 75, 4: 78, 5: 79, 6: 60})
        command = _command(partner_ids=[1, 2, 3, 4, 5, 6])
        bonus = self.strategy._near_rainbow_training_bonus(command, chara, turn=20)
        # 6 * 0.04 = 0.24, but capped at 0.12.
        self.assertAlmostEqual(bonus, 0.12, places=4)


class FirstSummerFriendshipBonusTests(unittest.TestCase):
    def setUp(self):
        self.strategy = MantStrategy()
        self.preset = {}

    def test_default_classic_entry_target_is_four_friendships(self):
        self.assertEqual(self.strategy._first_summer_friendship_target(35), 4)

    def test_bonus_rewards_mid_bond_deck_partners_before_first_summer(self):
        chara = _chara(turn=22, bonds={1: 45, 2: 55, 3: 78, 4: 82})
        command = _command(partner_ids=[1, 2, 3, 4])
        bonus = self.strategy._first_summer_friendship_bonus(command, chara, turn=22, preset=self.preset)
        self.assertGreater(bonus, 0.0)

    def test_bonus_grows_when_current_rainbows_are_behind_target(self):
        behind = _chara(turn=30, bonds={1: 45, 2: 65, 3: 72, 4: 50})
        ahead = _chara(turn=30, bonds={1: 45, 2: 65, 3: 72, 4: 82, 5: 88})
        command = _command(partner_ids=[1, 2, 3, 4])
        preset = {"first_summer_friendship_bonus_cap": 1.0}
        behind_bonus = self.strategy._first_summer_friendship_bonus(command, behind, turn=30, preset=preset)
        ahead_bonus = self.strategy._first_summer_friendship_bonus(command, ahead, turn=30, preset=preset)
        self.assertGreater(behind_bonus, ahead_bonus)

    def test_bonus_turns_off_after_first_summer_target_window(self):
        chara = _chara(turn=40, bonds={1: 45, 2: 65, 3: 72})
        command = _command(partner_ids=[1, 2, 3])
        bonus = self.strategy._first_summer_friendship_bonus(command, chara, turn=40, preset=self.preset)
        self.assertEqual(bonus, 0.0)

    def test_command_features_expose_friendship_pressure(self):
        chara = _chara(turn=30, bonds={1: 45, 2: 65, 3: 72, 4: 50})
        command = _command(partner_ids=[1, 2, 3, 4])
        command["_first_summer_friendship_bonus"] = 0.22
        feats = command_features(command, chara, preset={"first_summer_friendship_target_rainbows": 4})
        self.assertGreater(feats["first_summer_friendship_pressure"], 0.0)
        self.assertGreater(feats["friendship_unlocked_gap"], 0.0)

    def test_action_features_read_friendship_pressure_from_understanding(self):
        action = {
            "turn": 30,
            "weighted_gain": 20.0,
            "partner_count": 3,
            "deck_partner_count": 3,
            "rainbow_count": 0,
            "high_bond_count": 0,
            "decision_understanding": {
                "signals": {
                    "first_summer_friendship_bonus": 0.20,
                    "current_rainbow_unlocked_count": 0,
                    "target_rainbow_unlocked_count": 4,
                }
            },
        }
        feats = _action_features(action)
        self.assertGreater(feats["first_summer_friendship_pressure"], 0.0)
        self.assertGreater(feats["friendship_unlocked_gap"], 0.0)


if __name__ == "__main__":
    unittest.main()
