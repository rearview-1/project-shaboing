import unittest

from career_bot.race_success_feedback import (
    aggregate_success_by_race,
    empirical_success_viability,
    merge_global_success_signal,
    upcoming_race_success_demand,
)
from career_bot.scenarios.mant import MantStrategy


class _FakePlanner:
    def __init__(self, entries):
        self._entries = list(entries)
        self.base_dir = None

    def scheduled_entries(self, preset):
        return list(self._entries)


class RaceSuccessFeedbackTests(unittest.TestCase):
    def test_aggregates_winning_stat_bands_and_skill_parsimony(self):
        samples = [{
            "race_results": [
                {
                    "program_id": 11017,
                    "won": True,
                    "is_g1": True,
                    "race": {"name": "NHK Mile Cup", "grade": "G1"},
                    "running_style": 2,
                    "skill_count_at_race": 0,
                    "stats_at_race": {"speed": 820, "stamina": 540, "power": 760, "guts": 420, "wit": 690},
                },
                {
                    "program_id": 11017,
                    "won": True,
                    "is_g1": True,
                    "race": {"name": "NHK Mile Cup", "grade": "G1"},
                    "running_style": 2,
                    "skill_count_at_race": 1,
                    "stats_at_race": {"speed": 840, "stamina": 560, "power": 780, "guts": 430, "wit": 710},
                },
                {
                    "program_id": 11017,
                    "won": False,
                    "is_g1": True,
                    "race": {"name": "NHK Mile Cup", "grade": "G1"},
                    "running_style": 1,
                    "skill_count_at_race": 3,
                    "stats_at_race": {"speed": 760, "stamina": 500, "power": 690, "guts": 390, "wit": 640},
                },
            ],
        }]
        hints = aggregate_success_by_race(samples)
        nhk = hints[11017]
        self.assertEqual(nhk["race_name"], "NHK Mile Cup")
        self.assertEqual(nhk["attempts"], 3)
        self.assertEqual(nhk["wins"], 2)
        self.assertEqual(nhk["losses"], 1)
        self.assertEqual(nhk["preferred_running_style"], "pace_chaser")
        self.assertEqual(nhk["wins_without_skills"], 1)
        self.assertAlmostEqual(nhk["avg_win_skill_count"], 0.5, places=3)
        self.assertEqual(nhk["winning_stat_baseline"]["speed"], 830.0)
        self.assertEqual(nhk["winning_stat_baseline"]["power"], 770.0)
        self.assertGreater(nhk["confidence"], 0.0)

    def test_ignores_off_aptitude_races_when_building_success_hints(self):
        samples = [{
            "run_context": {"trainee_card_id": 100101},
            "race_results": [
                {
                    "program_id": 22001,
                    "won": True,
                    "is_g1": True,
                    "terrain": "Turf",
                    "distance": "Medium",
                    "running_style": 2,
                    "race": {"name": "Valid Medium G1", "grade": "G1"},
                    "stats_at_race": {"speed": 900, "stamina": 700, "power": 820, "guts": 450, "wit": 720},
                },
                {
                    "program_id": 22002,
                    "won": False,
                    "is_g1": True,
                    "terrain": "Turf",
                    "distance": "Mile",
                    "running_style": 3,
                    "race": {"name": "Off Apt Mile G1", "grade": "G1"},
                    "stats_at_race": {"speed": 760, "stamina": 580, "power": 690, "guts": 410, "wit": 640},
                },
            ],
        }]
        hints = aggregate_success_by_race(samples, min_attempts=1, min_wins=1)
        self.assertIn(22001, hints)
        self.assertNotIn(22002, hints)

    def test_global_success_signal_merges_weighted_means(self):
        merged = merge_global_success_signal({
            11017: {
                "attempts": 3,
                "wins": 2,
                "avg_win_skill_count": 0.5,
                "preferred_running_style": "pace_chaser",
                "winning_stat_baseline": {"speed": 830, "power": 770},
            },
            11034: {
                "attempts": 2,
                "wins": 1,
                "avg_win_skill_count": 2.0,
                "preferred_running_style": "front_runner",
                "winning_stat_baseline": {"speed": 780, "power": 710},
            },
        })
        self.assertEqual(merged["wins"], 3)
        self.assertEqual(merged["preferred_running_style"], "pace_chaser")
        self.assertAlmostEqual(merged["avg_win_skill_count"], 1.0, places=3)
        self.assertEqual(merged["winning_stat_baseline"]["speed"], 813.3)

    def test_upcoming_race_success_demand_only_counts_positive_deficits(self):
        hints = {
            11017: {
                "program_id": 11017,
                "winning_stat_baseline": {"speed": 830, "stamina": 540, "power": 770, "guts": 425, "wit": 700},
                "win_rate": 0.667,
                "confidence": 0.8,
            }
        }
        demand = upcoming_race_success_demand(
            hints,
            scheduled=[{"turn": 35, "program_id": 11017}],
            current_turn=33,
            current_stats={"speed": 760, "stamina": 600, "power": 700, "guts": 500, "wit": 680},
        )
        self.assertGreater(demand["speed"], 0.0)
        self.assertGreater(demand["power"], 0.0)
        self.assertGreater(demand["wit"], 0.0)
        self.assertNotIn("stamina", demand)
        self.assertNotIn("guts", demand)

    def test_empirical_success_viability_accepts_matching_efficient_profile(self):
        hint = {
            "efficient_win_profile": {
                "running_style": "late_surger",
                "skill_count_at_race": 0,
                "stats_at_race": {"speed": 820, "stamina": 340, "power": 760, "guts": 300, "wit": 680},
                "effort_score": 2900,
            }
        }

        viability = empirical_success_viability(
            hint,
            current_stats={"speed": 840, "stamina": 345, "power": 780, "guts": 315, "wit": 700},
            running_style="late_surger",
        )

        self.assertTrue(viability["viable"])
        self.assertEqual(viability["deficits"], {})


class RaceSuccessTrainingBonusTests(unittest.TestCase):
    def setUp(self):
        self.preset = {
            "expect_attribute": [1200, 1200, 1200, 1200, 1200],
            "race_specific_success_hints": {
                11017: {
                    "program_id": 11017,
                    "winning_stat_baseline": {"speed": 830, "stamina": 540, "power": 770, "guts": 425, "wit": 700},
                    "win_rate": 0.667,
                    "confidence": 0.8,
                },
            },
        }

    def test_bonus_is_positive_when_current_stats_lag_success_band(self):
        strategy = MantStrategy(race_planner=_FakePlanner([{"turn": 35, "program_id": 11017}]))
        chara = {"turn": 33, "speed": 760, "stamina": 520, "power": 700, "guts": 400, "wiz": 660}
        self.assertGreater(strategy._race_success_training_bonus(0, chara, self.preset), 0.0)
        self.assertGreater(strategy._race_success_training_bonus(2, chara, self.preset), 0.0)
        self.assertGreater(strategy._race_success_training_bonus(4, chara, self.preset), 0.0)

    def test_bonus_is_zero_when_already_above_success_band(self):
        strategy = MantStrategy(race_planner=_FakePlanner([{"turn": 35, "program_id": 11017}]))
        chara = {"turn": 33, "speed": 900, "stamina": 600, "power": 820, "guts": 500, "wiz": 760}
        self.assertEqual(strategy._race_success_training_bonus(0, chara, self.preset), 0.0)
        self.assertEqual(strategy._race_success_training_bonus(2, chara, self.preset), 0.0)


if __name__ == "__main__":
    unittest.main()
