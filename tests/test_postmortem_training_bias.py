"""Phase 2 integration: postmortem hints actually steer training picks.

Verifies the `_postmortem_training_bonus` method on MantStrategy
returns the expected bias when scheduled races have hints, and zero
otherwise. The bias is what closes the loop — without it, the
postmortem aggregation was forensic-only.
"""

import unittest

from career_bot.postmortem_feedback import POSTMORTEM_FEEDBACK_SCHEMA
from career_bot.scenarios.mant import MantStrategy


class _FakePlanner:
    """Minimal race_planner stub matching the surface mant.py uses for
    the postmortem training bias. `scheduled_entries(preset)` is the
    method that actually matters; `base_dir=None` short-circuits the
    EventManager wiring in MantStrategy.__init__."""

    def __init__(self, entries):
        self._entries = list(entries)
        self.base_dir = None

    def scheduled_entries(self, preset):
        return list(self._entries)


class PostmortemTrainingBonusTests(unittest.TestCase):
    def setUp(self):
        self.preset_no_hints = {"expect_attribute": [1200, 1200, 1200, 1200, 1200]}
        self.preset_with_hints = {
            "expect_attribute": [1200, 1200, 1200, 1200, 1200],
            "postmortem_feedback_schema": POSTMORTEM_FEEDBACK_SCHEMA,
            "race_specific_stat_hints": {
                11017: {
                    "program_id": 11017, "loss_count": 3,
                    "avg_gap": {"power": 250, "speed": 0, "stamina": 0, "guts": 0, "wit": 0},
                    "worst_stat": "power", "worst_stat_gap": 250,
                },
            },
        }
        self.chara_turn_33 = {"turn": 33}

    def test_legacy_unversioned_hints_are_ignored(self):
        preset = dict(self.preset_with_hints)
        preset.pop("postmortem_feedback_schema", None)
        planner = _FakePlanner([{"turn": 35, "program_id": 11017}])
        strategy = MantStrategy(race_planner=planner)
        bonus = strategy._postmortem_training_bonus(2, self.chara_turn_33, preset)
        self.assertEqual(bonus, 0.0)

    def test_returns_zero_when_no_planner(self):
        strategy = MantStrategy(race_planner=None)
        self.assertEqual(
            strategy._postmortem_training_bonus(2, self.chara_turn_33, self.preset_with_hints),
            0.0,
        )

    def test_returns_zero_when_no_hints_on_preset(self):
        planner = _FakePlanner([{"turn": 35, "program_id": 11017}])
        strategy = MantStrategy(race_planner=planner)
        self.assertEqual(
            strategy._postmortem_training_bonus(2, self.chara_turn_33, self.preset_no_hints),
            0.0,
        )

    def test_returns_zero_when_no_scheduled_races_in_window(self):
        planner = _FakePlanner([{"turn": 60, "program_id": 11017}])  # 27 turns out
        strategy = MantStrategy(race_planner=planner)
        bonus = strategy._postmortem_training_bonus(2, self.chara_turn_33, self.preset_with_hints)
        self.assertEqual(bonus, 0.0)

    def test_returns_positive_bonus_when_upcoming_race_needs_this_stat(self):
        planner = _FakePlanner([{"turn": 35, "program_id": 11017}])
        strategy = MantStrategy(race_planner=planner)
        # Power training (idx=2) when upcoming race wants Power.
        bonus = strategy._postmortem_training_bonus(2, self.chara_turn_33, self.preset_with_hints)
        self.assertGreater(bonus, 0.0)
        self.assertLessEqual(bonus, 0.20)  # Capped at _POSTMORTEM_BONUS_CAP (bumped to 0.20).

    def test_returns_zero_for_other_stats_when_only_power_in_demand(self):
        planner = _FakePlanner([{"turn": 35, "program_id": 11017}])
        strategy = MantStrategy(race_planner=planner)
        # Speed training (idx=0): not what the upcoming race demands.
        bonus = strategy._postmortem_training_bonus(0, self.chara_turn_33, self.preset_with_hints)
        self.assertEqual(bonus, 0.0)

    def test_full_bonus_at_high_demand(self):
        """Demand ≥ _POSTMORTEM_DEMAND_FULL_BONUS_AT (180) should
        produce the full capped bonus (0.20 — was 0.10 before the
        ship-everything aggression bump)."""
        planner = _FakePlanner([{"turn": 33, "program_id": 11017}])  # same-turn → urgency=1.0
        strategy = MantStrategy(race_planner=planner)
        bonus = strategy._postmortem_training_bonus(2, self.chara_turn_33, self.preset_with_hints)
        # demand = 250 * 1.0 = 250 → demand/180 capped at 1.0 → bonus = 0.20.
        self.assertAlmostEqual(bonus, 0.20, places=4)

    def test_string_program_ids_in_hints_dict_still_resolve(self):
        """JSON roundtripping turns int program_ids into strings; the
        bonus must still work when the preset's stat_hints dict was
        deserialized that way."""
        preset = dict(self.preset_with_hints)
        preset["race_specific_stat_hints"] = {
            "11017": self.preset_with_hints["race_specific_stat_hints"][11017],
        }
        planner = _FakePlanner([{"turn": 35, "program_id": 11017}])
        strategy = MantStrategy(race_planner=planner)
        bonus = strategy._postmortem_training_bonus(2, self.chara_turn_33, preset)
        self.assertGreater(bonus, 0.0)


if __name__ == "__main__":
    unittest.main()
