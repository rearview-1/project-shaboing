import json
import unittest
from pathlib import Path

from career_bot.race_schedule import RaceCatalog, RaceStaminaEstimator
from career_bot.races import RacePlanner
from career_bot.scenarios.mant import MantStrategy


BASE_DIR = Path(__file__).resolve().parents[1]


class RaceScheduleSmokeTests(unittest.TestCase):
    def setUp(self):
        self.catalog = RaceCatalog(BASE_DIR)

    def test_scheduler_json_resolves_named_races_to_programs(self):
        plan = [
            {"raceName": "Niigata Junior Stakes", "year": "First Year", "turn": "08_02"},
            {"raceName": "Kikuka Sho", "year": "Second Year", "turn": "10_02", "style": "late surger"},
        ]

        parsed = self.catalog.parse_plan_input(json.dumps(plan))

        self.assertEqual(parsed["errors"], [])
        self.assertEqual([entry["race_id"] for entry in parsed["entries"]], [2009, 2171])
        self.assertEqual([entry["program_id"] for entry in parsed["entries"]], [629, 168])
        self.assertEqual([entry["turn"] for entry in parsed["entries"]], [16, 44])
        self.assertEqual(parsed["entries"][1]["style"], "late_surger")

    def test_scheduler_text_resolves_named_race_and_date(self):
        parsed = self.catalog.parse_plan_input("Classic Year Late Oct @ Kikuka Sho | late surger")

        self.assertEqual(parsed["errors"], [])
        self.assertEqual(parsed["entries"][0]["race_id"], 2171)
        self.assertEqual(parsed["entries"][0]["program_id"], 168)
        self.assertEqual(parsed["entries"][0]["style"], "late_surger")

    def test_scheduler_json_rejects_two_races_in_same_turn(self):
        plan = [
            {"raceName": "Niigata Junior Stakes", "year": "First Year", "turn": "08_02"},
            {"raceName": "Clover Sho", "year": "First Year", "turn": "08_02"},
        ]

        parsed = self.catalog.parse_plan_input(json.dumps(plan))

        self.assertEqual(len(parsed["entries"]), 1)
        self.assertEqual(len(parsed["errors"]), 1)
        self.assertIn("already has", parsed["errors"][0]["error"])

    def test_stamina_estimator_flags_low_stamina_long_g1(self):
        race, error = self.catalog.resolve("Kikuka Sho", "Classic Year Late Oct")
        self.assertFalse(error)

        check = RaceStaminaEstimator().estimate(
            {"speed": 600, "stamina": 320, "power": 450, "guts": 300, "wiz": 300},
            race,
            "late_surger",
        )

        self.assertTrue(check["stamina_low"])
        self.assertIn("stamina low", check["warnings"])

    def test_stamina_estimator_counts_owned_stamina_recovery_for_long_races(self):
        race, error = self.catalog.resolve("Kikuka Sho", "Classic Year Late Oct")
        self.assertFalse(error)

        check = RaceStaminaEstimator().estimate(
            {
                "speed": 600,
                "stamina": 320,
                "power": 450,
                "guts": 300,
                "wiz": 300,
                "skill_array": [{"skill_id": 200352}],
            },
            race,
            "late_surger",
        )

        self.assertGreater(check["stats"]["stamina"], check["raw_stats"]["stamina"])
        self.assertFalse(check["stamina_low"])
        self.assertIn("stamina recovery skill counted", check["warnings"])

    def test_stamina_estimator_counts_agnes_tachyon_unique_recovery_for_medium_races(self):
        race, error = self.catalog.resolve("Osaka Hai", "Senior Year Late Mar")
        self.assertFalse(error)

        check = RaceStaminaEstimator().estimate(
            {
                "card_id": 103201,
                "speed": 620,
                "stamina": 300,
                "power": 500,
                "guts": 340,
                "wiz": 420,
            },
            race,
            "pace_chaser",
        )

        self.assertFalse(check["stamina_low"])
        self.assertEqual((check.get("unique_recovery_profile") or {}).get("card_id"), 103201)
        self.assertIn("unique stamina recovery counted (Agnes Tachyon)", check["warnings"])

    def test_stamina_estimator_does_not_give_dober_tachyon_unique_leniency(self):
        race, error = self.catalog.resolve("Osaka Hai", "Senior Year Late Mar")
        self.assertFalse(error)

        check = RaceStaminaEstimator().estimate(
            {
                "card_id": 105901,
                "speed": 620,
                "stamina": 300,
                "power": 500,
                "guts": 340,
                "wiz": 420,
            },
            race,
            "late_surger",
        )

        self.assertTrue(check["stamina_low"])
        self.assertEqual(check.get("unique_recovery_profile"), {})

    def test_race_planner_prefers_chara_specific_style_override_over_global(self):
        planner = RacePlanner(BASE_DIR)
        style = planner._style_for_entry(
            {"program_id": 168},
            {
                "skill_profile_style": "late_surger",
                "_run_context": {"trainee_card_id": 103201},
                "race_style_overrides": {
                    "schema": "sweepy_race_style_overrides_v2",
                    "global": {"168": "late_surger"},
                    "by_chara": {"103201": {"168": "pace_chaser"}},
                },
            },
            program_id=168,
        )
        self.assertEqual(style, "pace_chaser")

    def test_race_style_overrides_disabled_falls_back_to_profile_style(self):
        planner = RacePlanner(BASE_DIR)
        style = planner._style_for_entry(
            {"program_id": 168},
            {
                "skill_profile_style": "front_runner",
                "race_style_overrides_learned_enabled": False,
                "race_style_overrides": {"168": "late_surger"},
            },
            program_id=168,
        )
        self.assertEqual(style, "front_runner")

    def test_calendar_entry_style_still_wins_when_overrides_disabled(self):
        planner = RacePlanner(BASE_DIR)
        style = planner._style_for_entry(
            {"program_id": 168, "style": "late_surger"},
            {
                "skill_profile_style": "front_runner",
                "race_style_overrides_learned_enabled": False,
                "race_style_overrides": {"168": "pace_chaser"},
            },
            program_id=168,
        )
        self.assertEqual(style, "late_surger")

    def test_planner_skips_scheduled_race_when_stamina_is_too_low(self):
        planner = RacePlanner(BASE_DIR)
        preset = {
            "scheduled_race_force_calendar": False,
            "custom_race_schedule": [
                self.catalog.entry_from_race(
                    self.catalog.by_id[2171],
                    "late_surger",
                    "Classic Year Late Oct @ Kikuka Sho",
                )
            ],
            "auto_buy_stamina_skill_for_race": False,
        }
        state = {
            "data": {
                "chara_info": {"turn": 44, "fans": 10000, "speed": 600, "stamina": 320, "power": 450, "guts": 300, "wiz": 300},
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_condition_array": [{"program_id": 168}],
            }
        }

        self.assertEqual(planner.choose(state, preset), 0)
        self.assertEqual(planner.last_skip_reason["reason"], "no_scheduled_race_selected")
        self.assertEqual(planner.last_skip_reason["skipped"][0]["reason"], "scheduled_race_stamina_low")
        self.assertTrue(planner.last_stamina_check["stamina_low"])

    def test_planner_skips_scheduled_race_when_training_is_clearly_better(self):
        planner = RacePlanner(BASE_DIR)
        preset = {
            "scheduled_race_force_calendar": False,
            "scheduled_race_respect_training": True,
            "custom_race_schedule": [
                self.catalog.entry_from_race(
                    self.catalog.by_id[2009],
                    "",
                    "Junior Year Late Aug @ Niigata Junior Stakes",
                )
            ],
        }
        state = {
            "data": {
                "chara_info": {"turn": 16, "fans": 5000, "speed": 420, "stamina": 300, "power": 360, "guts": 240, "wiz": 320},
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_condition_array": [{"program_id": 629}],
            }
        }

        selected = planner.choose(
            state,
            preset,
            {"command_type": 1, "command_id": 101, "score": 0.55, "stat_gain": 46, "rainbow_count": 2},
        )

        self.assertEqual(selected, 0)
        self.assertEqual(planner.last_skip_reason["reason"], "no_scheduled_race_selected")
        self.assertEqual(planner.last_skip_reason["skipped"][0]["reason"], "training_too_good_for_scheduled_race")

    def test_planner_follows_scheduled_race_by_default_even_when_training_is_better(self):
        planner = RacePlanner(BASE_DIR)
        preset = {
            "custom_race_schedule": [
                self.catalog.entry_from_race(
                    self.catalog.by_id[2009],
                    "",
                    "Junior Year Late Aug @ Niigata Junior Stakes",
                )
            ],
        }
        state = {
            "data": {
                "chara_info": {"turn": 16, "fans": 5000, "speed": 420, "stamina": 300, "power": 360, "guts": 240, "wiz": 320},
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_condition_array": [{"program_id": 629}],
            }
        }

        selected = planner.choose(
            state,
            preset,
            {"command_type": 1, "command_id": 101, "score": 0.55, "stat_gain": 46, "rainbow_count": 2},
        )

        self.assertEqual(selected, 629)
        self.assertIsNone(planner.last_skip_reason)

    def test_planner_runs_maiden_recovery_after_debut_loss_before_calendar_g3(self):
        planner = RacePlanner(BASE_DIR)
        preset = {
            "custom_race_schedule": [
                self.catalog.entry_from_race(
                    self.catalog.by_id[2009],
                    "",
                    "Junior Year Late Aug @ Niigata Junior Stakes",
                )
            ],
        }
        state = {
            "data": {
                "chara_info": {"turn": 16, "fans": 372, "speed": 260, "stamina": 208, "power": 219, "guts": 154, "wiz": 182},
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_history": [
                    {"turn": 12, "program_id": 1067, "result_rank": 3},
                ],
                "race_condition_array": [
                    {"program_id": 315},
                    {"program_id": 316},
                    {"program_id": 629},
                ],
            }
        }

        selected = planner.choose(state, preset)

        self.assertEqual(selected, 315)
        self.assertEqual(planner.last_skip_reason["reason"], "debut_loss_recovery_race_selected")
        self.assertEqual(planner.last_skip_reason["scheduled_deferred"][0]["program_id"], 629)

    def test_planner_resumes_calendar_after_any_career_win(self):
        planner = RacePlanner(BASE_DIR)
        preset = {
            "custom_race_schedule": [
                self.catalog.entry_from_race(
                    self.catalog.by_id[2009],
                    "",
                    "Junior Year Late Aug @ Niigata Junior Stakes",
                )
            ],
        }
        state = {
            "data": {
                "chara_info": {"turn": 16, "fans": 700, "speed": 420, "stamina": 300, "power": 360, "guts": 240, "wiz": 320},
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_history": [
                    {"turn": 12, "program_id": 1067, "result_rank": 1},
                ],
                "race_condition_array": [
                    {"program_id": 315},
                    {"program_id": 629},
                ],
            }
        }

        selected = planner.choose(state, preset)

        self.assertEqual(selected, 629)
        self.assertIsNone(planner.last_skip_reason)

    def test_planner_skips_scheduled_race_when_style_is_off_aptitude(self):
        planner = RacePlanner(BASE_DIR)
        race, error = self.catalog.resolve("American JCC", "Senior Year Late Jan")
        self.assertFalse(error)
        preset = {
            "scheduled_race_force_calendar": False,
            "_run_context": {"trainee_card_id": 106801},
            "custom_race_schedule": [
                self.catalog.entry_from_race(
                    race,
                    "late_surger",
                    "Senior Year Early Jan @ American JCC",
                )
            ],
        }
        state = {
            "data": {
                "chara_info": {"turn": race["turn"], "fans": 100000, "card_id": 106801, "speed": 620, "stamina": 620, "power": 430, "guts": 360, "wiz": 620},
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_condition_array": [{"program_id": race["program_id"]}],
            }
        }

        selected = planner.choose(state, preset, {"command_type": 1, "command_id": 101, "score": 0.18, "stat_gain": 18, "rainbow_count": 0})

        self.assertEqual(selected, 0)
        self.assertEqual(planner.last_skip_reason["reason"], "no_scheduled_race_selected")
        self.assertEqual(planner.last_skip_reason["skipped"][0]["reason"], "scheduled_race_off_aptitude")

    def test_planner_forces_scheduled_race_even_when_safety_gate_would_skip(self):
        planner = RacePlanner(BASE_DIR)
        preset = {
            "custom_race_schedule": [
                self.catalog.entry_from_race(
                    self.catalog.by_id[2171],
                    "late_surger",
                    "Classic Year Late Oct @ Kikuka Sho",
                )
            ],
            "auto_buy_stamina_skill_for_race": False,
        }
        state = {
            "data": {
                "chara_info": {"turn": 44, "fans": 10000, "speed": 600, "stamina": 320, "power": 450, "guts": 300, "wiz": 300},
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_condition_array": [{"program_id": 168}],
            }
        }

        self.assertEqual(planner.choose(state, preset), 168)
        self.assertIsNone(planner.last_skip_reason)

    def test_planner_skips_scheduled_race_when_fans_are_too_low(self):
        planner = RacePlanner(BASE_DIR)
        preset = {
            "custom_race_schedule": [
                self.catalog.entry_from_race(
                    self.catalog.by_id[2009],
                    "",
                    "Junior Year Late Aug @ Niigata Junior Stakes",
                )
            ],
        }
        state = {
            "data": {
                "chara_info": {"turn": 16, "fans": 98, "speed": 420, "stamina": 280, "power": 360, "guts": 240, "wiz": 300},
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_condition_array": [{"program_id": 629}],
            }
        }

        self.assertEqual(planner.choose(state, preset), 0)
        self.assertEqual(planner.last_skip_reason["reason"], "no_scheduled_race_selected")
        self.assertEqual(planner.last_skip_reason["skipped"][0]["reason"], "insufficient_fans")

        state["data"]["chara_info"]["fans"] = 700
        self.assertEqual(planner.choose(state, preset), 629)

    def test_planner_can_override_fan_gate_when_explicitly_enabled(self):
        planner = RacePlanner(BASE_DIR)
        preset = {
            "override_insufficient_fans_forced_races": True,
            "custom_race_schedule": [
                self.catalog.entry_from_race(
                    self.catalog.by_id[2009],
                    "",
                    "Junior Year Late Aug @ Niigata Junior Stakes",
                )
            ],
        }
        state = {
            "data": {
                "chara_info": {"turn": 16, "fans": 98, "speed": 420, "stamina": 280, "power": 360, "guts": 240, "wiz": 300},
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_condition_array": [{"program_id": 629}],
            }
        }

        self.assertEqual(planner.choose(state, preset), 629)

    def test_planner_can_take_optional_g3_when_training_is_weak(self):
        planner = RacePlanner(BASE_DIR)
        state = {
            "data": {
                "chara_info": {
                    "turn": 16,
                    "fans": 1000,
                    "speed": 400,
                    "stamina": 300,
                    "power": 350,
                    "guts": 250,
                    "wiz": 300,
                },
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_condition_array": [{"program_id": 629}],
                "free_data_set": {
                    "win_points": 48000,
                    "rival_race_info_array": [{"program_id": 629}],
                },
            }
        }

        selected = planner.choose_optional(state, {}, {"score": 0.2, "stat_gain": 20, "rainbow_count": 0})

        self.assertEqual(selected, 629)
        self.assertEqual(planner.last_skip_reason["reason"], "optional_race_selected")
        self.assertTrue(planner.last_skip_reason["rival"])
        self.assertTrue(planner.last_skip_reason["crosses_epithet"])

    def test_planner_never_takes_optional_g1(self):
        planner = RacePlanner(BASE_DIR)
        state = {
            "data": {
                "chara_info": {
                    "turn": 44,
                    "fans": 10000,
                    "speed": 800,
                    "stamina": 600,
                    "power": 750,
                    "guts": 450,
                    "wiz": 650,
                },
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_condition_array": [{"program_id": 168}],
                "free_data_set": {"win_points": 95000},
            }
        }

        self.assertEqual(planner.choose_optional(state, {}, {"score": 0.1, "stat_gain": 5, "rainbow_count": 0}), 0)
        self.assertEqual(planner.last_skip_reason["skipped"][0]["reason"], "g1_not_allowed")

    def test_planner_can_take_non_g1_rival_race(self):
        planner = RacePlanner(BASE_DIR)
        state = {
            "data": {
                "chara_info": {
                    "turn": 16,
                    "fans": 1000,
                    "speed": 400,
                    "stamina": 300,
                    "power": 350,
                    "guts": 250,
                    "wiz": 300,
                },
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_condition_array": [{"program_id": 641}],
                "free_data_set": {
                    "win_points": 10000,
                    "rival_race_info_array": [{"program_id": 641}],
                },
            }
        }

        self.assertEqual(planner.choose_optional(state, {}, {"score": 0.2, "stat_gain": 12, "rainbow_count": 0}), 641)
        self.assertEqual(planner.last_skip_reason["grade"], "OP")
        self.assertTrue(planner.last_skip_reason["rival"])

    def test_planner_preserve_mode_can_skip_low_value_optional_race(self):
        planner = RacePlanner(BASE_DIR)
        preset = {
            "optional_race_min_value": 0.35,
            "run_mode_policy": {
                "enabled": True,
                "preserve_confidence": 0.6,
                "push_confidence": 0.45,
                "preserve_optional_race_penalty": 0.03,
                "preserve_training_score_penalty": 0.02,
            },
            "trajectory_centroids": {
                "schema": "sweepy_trajectory_centroids_v1",
                "feature_scales": {"speed": 900, "stamina": 900, "power": 900, "guts": 600, "wit": 700, "hp": 100, "skill_point": 400},
                "checkpoints": {
                    "16": {
                        "top_count": 5,
                        "bottom_count": 5,
                        "top_centroid": {"speed": 410, "stamina": 300, "power": 360, "guts": 250, "wit": 300, "hp": 80, "skill_point": 120},
                        "bottom_centroid": {"speed": 250, "stamina": 200, "power": 220, "guts": 150, "wit": 180, "hp": 55, "skill_point": 60},
                    }
                },
            },
        }
        state = {
            "data": {
                "chara_info": {
                    "turn": 16,
                    "fans": 1000,
                    "speed": 408,
                    "stamina": 298,
                    "power": 358,
                    "guts": 248,
                    "wiz": 298,
                    "vital": 82,
                    "skill_point": 120,
                },
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_condition_array": [{"program_id": 641}],
                "free_data_set": {"win_points": 10000},
            }
        }

        self.assertEqual(planner.choose_optional(state, preset, {"score": 0.2, "stat_gain": 12, "rainbow_count": 0}), 0)
        self.assertEqual(planner.last_skip_reason["reason"], "no_optional_race_selected")

    def test_planner_skips_optional_race_for_strong_rainbow_training(self):
        planner = RacePlanner(BASE_DIR)
        state = {
            "data": {
                "chara_info": {
                    "turn": 16,
                    "fans": 1000,
                    "speed": 400,
                    "stamina": 300,
                    "power": 350,
                    "guts": 250,
                    "wiz": 300,
                },
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_condition_array": [{"program_id": 629}],
                "free_data_set": {"win_points": 48000},
            }
        }

        selected = planner.choose_optional(state, {}, {"score": 0.43, "stat_gain": 43, "rainbow_count": 2})

        self.assertEqual(selected, 0)
        self.assertEqual(planner.last_skip_reason["reason"], "training_too_good_for_optional_race")

    def test_mant_strategy_checks_optional_race_after_training_score(self):
        planner = RacePlanner(BASE_DIR)
        strategy = MantStrategy(planner)
        state = {
            "data": {
                "chara_info": {
                    "turn": 16,
                    "fans": 1000,
                    "speed": 400,
                    "stamina": 300,
                    "power": 350,
                    "guts": 250,
                    "wiz": 300,
                    "vital": 90,
                    "motivation": 4,
                    "evaluation_info_array": [],
                },
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {
                            "command_type": 1,
                            "command_id": 101,
                            "is_enable": 1,
                            "params_inc_dec_info_array": [
                                {"target_type": 1, "value": 5},
                                {"target_type": 10, "value": -20},
                            ],
                            "training_partner_array": [],
                            "tips_event_partner_array": [],
                            "failure_rate": 0,
                        },
                    ]
                },
                "race_condition_array": [{"program_id": 629}],
                "free_data_set": {"win_points": 48000},
            }
        }

        decision = strategy.next_decision(state, {})

        self.assertEqual(decision.action, "race")
        self.assertEqual(decision.payload["program_id"], 629)

    def test_mant_strategy_does_not_replace_scheduled_miss_with_optional_race(self):
        planner = RacePlanner(BASE_DIR)
        strategy = MantStrategy(planner)
        scheduled = self.catalog.entry_from_race(
            self.catalog.by_id[2020],
            "",
            "Junior Year Late Nov @ Daily Hai Junior Stakes",
        )
        state = {
            "data": {
                "chara_info": {
                    "turn": scheduled["turn"],
                    "fans": 5000,
                    "speed": 400,
                    "stamina": 300,
                    "power": 350,
                    "guts": 250,
                    "wiz": 300,
                    "vital": 90,
                    "motivation": 4,
                    "evaluation_info_array": [],
                },
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {
                            "command_type": 1,
                            "command_id": 101,
                            "is_enable": 1,
                            "params_inc_dec_info_array": [
                                {"target_type": 1, "value": 5},
                                {"target_type": 10, "value": -20},
                            ],
                            "training_partner_array": [],
                            "tips_event_partner_array": [],
                            "failure_rate": 0,
                        },
                    ]
                },
                # Scheduled Daily Hai is not available; an optional G3 is.
                # Strict calendar mode must not substitute the optional race.
                "race_condition_array": [{"program_id": 633}],
                "free_data_set": {
                    "win_points": 48000,
                    "rival_race_info_array": [{"program_id": 633}],
                },
            }
        }

        decision = strategy.next_decision(state, {"custom_race_schedule": [scheduled]})

        self.assertEqual(decision.action, "command")
        self.assertEqual(planner.last_skip_reason["reason"], "no_scheduled_race_selected")
        self.assertEqual(planner.last_skip_reason["skipped"][0]["reason"], "unavailable_or_rejected")

    def test_mant_strategy_blocks_optional_fillers_between_calendar_races_by_default(self):
        planner = RacePlanner(BASE_DIR)
        strategy = MantStrategy(planner)
        scheduled = self.catalog.entry_from_race(
            self.catalog.by_id[2009],
            "",
            "Junior Year Late Aug @ Niigata Junior Stakes",
        )
        state = {
            "data": {
                "chara_info": {
                    "turn": 20,
                    "fans": 5000,
                    "speed": 400,
                    "stamina": 300,
                    "power": 350,
                    "guts": 250,
                    "wiz": 300,
                    "vital": 90,
                    "motivation": 4,
                    "evaluation_info_array": [],
                },
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {
                            "command_type": 1,
                            "command_id": 101,
                            "is_enable": 1,
                            "params_inc_dec_info_array": [
                                {"target_type": 1, "value": 5},
                                {"target_type": 10, "value": -20},
                            ],
                            "training_partner_array": [],
                            "tips_event_partner_array": [],
                            "failure_rate": 0,
                        },
                    ]
                },
                "race_condition_array": [{"program_id": 633}],
                "free_data_set": {
                    "win_points": 48000,
                    "rival_race_info_array": [{"program_id": 633}],
                },
            }
        }

        decision = strategy.next_decision(state, {"custom_race_schedule": [scheduled]})

        self.assertEqual(decision.action, "command")

    def test_mant_strategy_allows_calendar_optional_fillers_when_explicitly_enabled(self):
        planner = RacePlanner(BASE_DIR)
        strategy = MantStrategy(planner)
        scheduled = self.catalog.entry_from_race(
            self.catalog.by_id[2009],
            "",
            "Junior Year Late Aug @ Niigata Junior Stakes",
        )
        state = {
            "data": {
                "chara_info": {
                    "turn": 20,
                    "fans": 5000,
                    "speed": 400,
                    "stamina": 300,
                    "power": 350,
                    "guts": 250,
                    "wiz": 300,
                    "vital": 90,
                    "motivation": 4,
                    "evaluation_info_array": [],
                },
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {
                            "command_type": 1,
                            "command_id": 101,
                            "is_enable": 1,
                            "params_inc_dec_info_array": [
                                {"target_type": 1, "value": 5},
                                {"target_type": 10, "value": -20},
                            ],
                            "training_partner_array": [],
                            "tips_event_partner_array": [],
                            "failure_rate": 0,
                        },
                    ]
                },
                "race_condition_array": [{"program_id": 633}],
                "free_data_set": {
                    "win_points": 48000,
                    "rival_race_info_array": [{"program_id": 633}],
                },
            }
        }

        decision = strategy.next_decision(
            state,
            {
                "custom_race_schedule": [scheduled],
                "calendar_optional_fillers_enabled": True,
            },
        )

        self.assertEqual(decision.action, "race")
        self.assertEqual(decision.payload["program_id"], 633)

    def test_planner_flags_stamina_rescue_five_turns_before_race(self):
        planner = RacePlanner(BASE_DIR)
        preset = {
            "custom_race_schedule": [
                self.catalog.entry_from_race(
                    self.catalog.by_id[2171],
                    "late_surger",
                    "Classic Year Late Oct @ Kikuka Sho",
                )
            ],
            "auto_buy_stamina_skill_for_race": True,
        }
        state = {
            "data": {
                "chara_info": {"turn": 39, "speed": 600, "stamina": 320, "power": 450, "guts": 300, "wiz": 300},
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_condition_array": [{"program_id": 168}],
            }
        }

        entry, check = planner.stamina_rescue_entry(state, preset)

        self.assertEqual(entry["program_id"], 168)
        self.assertTrue(check["stamina_low"])
        self.assertIn("stamina low", check["warnings"])

    def test_planner_keeps_flagging_stamina_rescue_inside_lookahead_window(self):
        planner = RacePlanner(BASE_DIR)
        preset = {
            "custom_race_schedule": [
                self.catalog.entry_from_race(
                    self.catalog.by_id[2171],
                    "late_surger",
                    "Classic Year Late Oct @ Kikuka Sho",
                )
            ],
            "auto_buy_stamina_skill_for_race": True,
        }
        state = {
            "data": {
                "chara_info": {"turn": 42, "speed": 600, "stamina": 320, "power": 450, "guts": 300, "wiz": 300},
            }
        }

        entry, check = planner.stamina_rescue_entry(state, preset)

        self.assertEqual(entry["program_id"], 168)
        self.assertTrue(check["stamina_low"])

    def test_kikuka_front_runner_guard_uses_380_threshold(self):
        planner = RacePlanner(BASE_DIR)
        entry = self.catalog.entry_from_race(
            self.catalog.by_id[2171],
            "",
            "Classic Year Late Oct @ Kikuka Sho",
        )
        preset = {
            "custom_race_schedule": [entry],
            "auto_buy_stamina_skill_for_race": True,
            "skill_profile_style": "front_runner",
        }
        state = {
            "data": {
                "chara_info": {"turn": 39, "speed": 600, "stamina": 400, "power": 450, "guts": 300, "wiz": 300},
            }
        }

        rescue_entry, check = planner.stamina_rescue_entry(state, preset)

        self.assertIsNone(rescue_entry)
        self.assertIsNone(check)

        state["data"]["chara_info"]["stamina"] = 370
        rescue_entry, check = planner.stamina_rescue_entry(state, preset)

        self.assertEqual(rescue_entry["program_id"], 168)
        self.assertEqual(check["requirements"]["stamina"], 380)
        self.assertTrue(check["stamina_low"])
        self.assertIn("kikuka front stamina below 380", check["warnings"])

    def test_empirical_success_profile_can_suppress_conservative_stamina_rescue(self):
        planner = RacePlanner(BASE_DIR)
        entry = self.catalog.entry_from_race(
            self.catalog.by_id[2171],
            "late_surger",
            "Classic Year Late Oct @ Kikuka Sho",
        )
        preset = {
            "custom_race_schedule": [entry],
            "auto_buy_stamina_skill_for_race": True,
            "race_specific_success_hints": {
                "168": {
                    "program_id": 168,
                    "attempts": 2,
                    "wins": 1,
                    "confidence": 0.35,
                    "efficient_win_profile": {
                        "running_style": "late_surger",
                        "skill_count_at_race": 0,
                        "stats_at_race": {"speed": 620, "stamina": 340, "power": 470, "guts": 300, "wit": 300},
                        "effort_score": 2030,
                    },
                }
            },
        }
        state = {
            "data": {
                "chara_info": {"turn": 39, "speed": 630, "stamina": 345, "power": 480, "guts": 310, "wiz": 305},
                "home_info": {
                    "command_info_array": [
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 1, "command_id": 101, "is_enable": 1},
                    ]
                },
                "race_condition_array": [{"program_id": 168}],
            }
        }

        check = planner.stamina_for_program(state, preset, 168, entry)
        rescue_entry, rescue_check = planner.stamina_rescue_entry(state, preset)

        self.assertFalse(check["stamina_low"])
        self.assertTrue((check.get("empirical_success_viability") or {}).get("viable"))
        self.assertIsNone(rescue_entry)
        self.assertIsNone(rescue_check)


if __name__ == "__main__":
    unittest.main()
