import unittest

from career_bot.presets import expect_attribute_profile_lookup_keys
from career_bot.scenarios.mant import MantStrategy


def make_training_command(command_id, stat_target_type, stat_gain, skill_point_gain=0):
    rows = [
        {"target_type": stat_target_type, "value": stat_gain},
        {"target_type": 10, "value": -18},
    ]
    if skill_point_gain:
        rows.append({"target_type": 30, "value": skill_point_gain})
    return {
        "command_type": 1,
        "command_id": command_id,
        "is_enable": 1,
        "failure_rate": 0,
        "training_partner_array": [1, 2],
        "tips_event_partner_array": [],
        "params_inc_dec_info_array": rows,
    }


class StatLagFactorTests(unittest.TestCase):
    def setUp(self):
        self.strategy = MantStrategy()
        self.preset = {"expect_attribute": [1200, 1166, 1166, 1166, 1166]}

    def test_on_pace_stats_return_unity(self):
        chara = {"turn": 39, "speed": 600, "stamina": 590, "power": 590, "guts": 200, "wiz": 200}
        factor = self.strategy._stat_lag_factor(chara, self.preset)
        self.assertGreaterEqual(factor, 0.95)
        self.assertLessEqual(factor, 1.10)

    def test_lagging_primary_stats_pull_factor_down(self):
        chara = {"turn": 39, "speed": 250, "stamina": 240, "power": 230, "guts": 200, "wiz": 200}
        factor = self.strategy._stat_lag_factor(chara, self.preset)
        self.assertLess(factor, 0.55)
        self.assertGreaterEqual(factor, 0.45)

    def test_guts_and_wit_are_ignored_for_pacing(self):
        chara = {"turn": 39, "speed": 600, "stamina": 590, "power": 590, "guts": 50, "wiz": 50}
        factor = self.strategy._stat_lag_factor(chara, self.preset)
        self.assertGreaterEqual(factor, 0.95)

    def test_contextual_expect_profile_relaxes_matching_deck_target(self):
        preset = {
            "expect_attribute": [1200, 1166, 1166, 1166, 1166],
            "desired_parent_sparks": {"blue": ["Power"], "pink": [], "green": [], "white": []},
            "skill_profile_style": "late_surger",
            "skill_profile_distance": "medium",
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
            keys[0]: [1200, 760, 1100, 680, 780],
        }
        chara = {"turn": 39, "speed": 600, "stamina": 430, "power": 590, "guts": 200, "wiz": 200}

        baseline = self.strategy._stat_lag_factor(chara, {"expect_attribute": [1200, 1166, 1166, 1166, 1166]})
        contextual = self.strategy._stat_lag_factor(chara, preset)

        self.assertGreater(contextual, baseline)


class ConsecutiveRaceCountTests(unittest.TestCase):
    def setUp(self):
        self.strategy = MantStrategy()

    def test_no_history_returns_zero(self):
        self.assertEqual(self.strategy._consecutive_race_count({}, {"turn": 10}), 0)

    def test_counts_back_to_back_races(self):
        data = {"race_history": [{"turn": 8}, {"turn": 9}]}
        self.assertEqual(self.strategy._consecutive_race_count(data, {"turn": 10}), 2)

    def test_gap_breaks_the_chain(self):
        data = {"race_history": [{"turn": 6}, {"turn": 8}, {"turn": 9}]}
        self.assertEqual(self.strategy._consecutive_race_count(data, {"turn": 10}), 2)

    def test_only_counts_strictly_prior_turns(self):
        data = {"race_history": [{"turn": 10}, {"turn": 11}]}
        self.assertEqual(self.strategy._consecutive_race_count(data, {"turn": 10}), 0)


class KnowledgeMultiplierTests(unittest.TestCase):
    def setUp(self):
        self.strategy = MantStrategy()
        self.targets = [1200, 1166, 1166, 1166, 1166]

    def test_guts_under_distance_floor_gets_boost(self):
        chara = {"speed": 0, "stamina": 0, "power": 0, "guts": 150, "wiz": 0}
        preset = {"skill_profile_distance": "medium"}
        mult = self.strategy._knowledge_multiplier(3, chara, preset, self.targets, turn=30)
        self.assertGreater(mult, 1.0)

    def test_guts_over_distance_floor_is_deprioritized(self):
        chara = {"speed": 0, "stamina": 0, "power": 0, "guts": 700, "wiz": 0}
        preset = {"skill_profile_distance": "medium"}
        mult = self.strategy._knowledge_multiplier(3, chara, preset, self.targets, turn=30)
        self.assertLess(mult, 1.0)

    def test_wit_past_500_gets_penalty(self):
        chara = {"speed": 0, "stamina": 0, "power": 0, "guts": 0, "wiz": 600}
        mult = self.strategy._knowledge_multiplier(4, chara, {}, self.targets, turn=40)
        self.assertLess(mult, 1.0)

    def test_speed_under_pace_gets_boost_mid_career(self):
        chara = {"speed": 350, "stamina": 0, "power": 0, "guts": 0, "wiz": 0}
        mult = self.strategy._knowledge_multiplier(0, chara, {}, self.targets, turn=30)
        self.assertGreater(mult, 1.0)

    def test_stamina_career_floor_unbiased_for_medium_front(self):
        chara = {"speed": 0, "stamina": 360, "power": 0, "guts": 0, "wiz": 0}
        preset = {"skill_profile_distance": "medium", "skill_profile_style": "front_runner"}
        mult = self.strategy._knowledge_multiplier(1, chara, preset, self.targets, turn=30)
        self.assertEqual(mult, 1.0)

    def test_stamina_career_floor_boost_under_medium_front(self):
        chara = {"speed": 0, "stamina": 300, "power": 0, "guts": 0, "wiz": 0}
        preset = {"skill_profile_distance": "medium", "skill_profile_style": "front_runner"}
        mult = self.strategy._knowledge_multiplier(1, chara, preset, self.targets, turn=30)
        self.assertGreater(mult, 1.0)

    def test_stamina_near_cap_gets_heavy_penalty(self):
        chara = {"speed": 0, "stamina": 1150, "power": 0, "guts": 0, "wiz": 0}
        preset = {"skill_profile_distance": "long", "skill_profile_style": "front_runner"}
        mult = self.strategy._knowledge_multiplier(1, chara, preset, self.targets, turn=70)
        self.assertLess(mult, 0.7)

    def test_desired_blue_parent_goal_boosts_matching_stat_training(self):
        chara = {"speed": 420, "stamina": 0, "power": 0, "guts": 0, "wiz": 0}
        baseline = self.strategy._knowledge_multiplier(0, chara, {}, self.targets, turn=35)
        boosted = self.strategy._knowledge_multiplier(
            0,
            chara,
            {"desired_parent_sparks": {"blue": ["Speed"], "pink": [], "green": [], "white": []}},
            self.targets,
            turn=35,
        )
        self.assertGreater(boosted, baseline)

    def test_desired_blue_parent_goal_does_not_boost_other_stats(self):
        chara = {"speed": 420, "stamina": 0, "power": 0, "guts": 0, "wiz": 0}
        baseline = self.strategy._knowledge_multiplier(0, chara, {}, self.targets, turn=35)
        boosted = self.strategy._knowledge_multiplier(
            0,
            chara,
            {"desired_parent_sparks": {"blue": ["Power"], "pink": [], "green": [], "white": []}},
            self.targets,
            turn=35,
        )
        self.assertEqual(boosted, baseline)

    def test_desired_white_goal_adds_late_career_training_pressure(self):
        chara = {"turn": 70, "speed": 700, "stamina": 650, "power": 650, "guts": 300, "wiz": 400}
        preset = {
            "desired_parent_sparks": {"blue": [], "pink": [], "green": [], "white": ["Firm Conditions"]},
            "expect_attribute": self.targets,
            "score_value": [[0.11, 0.10, 0.006, 0.09]] * 4,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
        }
        speed_cmd = make_training_command(101, 1, 12, skill_point_gain=3)
        boosted = self.strategy._score_command(speed_cmd, {}, chara, preset)
        baseline = self.strategy._score_command(dict(speed_cmd), {}, chara, {**preset, "desired_parent_sparks": {}})
        self.assertGreater(boosted, baseline)

    def test_desired_blue_goal_boosts_secondary_power_gain_on_mixed_training(self):
        chara = {"turn": 40, "speed": 650, "stamina": 500, "power": 420, "guts": 220, "wiz": 260}
        cmd = {
            "command_type": 1,
            "command_id": 101,
            "is_enable": 1,
            "failure_rate": 0,
            "training_partner_array": [1, 2],
            "tips_event_partner_array": [],
            "params_inc_dec_info_array": [
                {"target_type": 1, "value": 18},
                {"target_type": 3, "value": 8},
                {"target_type": 10, "value": -18},
            ],
        }
        preset = {
            "desired_parent_sparks": {"blue": ["Power"], "pink": [], "green": [], "white": []},
            "expect_attribute": self.targets,
            "score_value": [[0.11, 0.10, 0.006, 0.09]] * 4,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
        }
        boosted = self.strategy._score_command(cmd, {}, chara, preset)
        baseline = self.strategy._score_command(dict(cmd), {}, chara, {**preset, "desired_parent_sparks": {}})
        self.assertGreater(boosted, baseline)

    def test_projected_overcap_penalizes_power_by_turn_60(self):
        chara = {"speed": 700, "stamina": 500, "power": 1000, "guts": 250, "wiz": 300}
        baseline = self.strategy._knowledge_multiplier(2, chara, {}, self.targets, turn=30)
        penalized = self.strategy._knowledge_multiplier(2, chara, {}, self.targets, turn=60)
        self.assertLess(penalized, baseline)
        self.assertLess(penalized, 0.9)

    def test_future_guaranteed_blue_gain_reduces_blue_pressure(self):
        chara = {"turn": 68, "speed": 1060, "stamina": 0, "power": 0, "guts": 0, "wiz": 0}
        preset = {"desired_parent_sparks": {"blue": ["Speed"]}}
        relieved_preset = {
            "desired_parent_sparks": {"blue": ["Speed"]},
            "future_turn_effects": {
                "schema": "sweepy_future_turn_effects_v1",
                "turns": {
                    "68": {"kind": "training", "effects": {"speed": 60}},
                },
            },
        }

        baseline = self.strategy._desired_blue_spark_multiplier(0, chara, preset, turn=68)
        relieved = self.strategy._desired_blue_spark_multiplier(0, chara, relieved_preset, turn=68)

        self.assertGreater(baseline, relieved)
        self.assertLess(relieved, 1.0)

    def test_future_guaranteed_gain_increases_overcap_penalty(self):
        chara = {"turn": 60, "speed": 700, "stamina": 500, "power": 940, "guts": 250, "wiz": 300}
        baseline = self.strategy._projected_overcap_multiplier(2, chara, {}, self.targets, turn=60)
        relieved_preset = {
            "future_turn_effects": {
                "schema": "sweepy_future_turn_effects_v1",
                "turns": {
                    "60": {"kind": "training", "effects": {"power": 80}},
                },
            },
        }
        penalized = self.strategy._projected_overcap_multiplier(2, chara, relieved_preset, self.targets, turn=60)

        self.assertLess(penalized, baseline)


class RaceHeavyRouteBiasTests(unittest.TestCase):
    def setUp(self):
        self.strategy = MantStrategy()
        self.targets = [1200, 1166, 1166, 1166, 1166]
        self.race_heavy_preset = {
            "expect_attribute": self.targets,
            "score_value": [[0.11, 0.10, 0.006, 0.09]] * 4,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
            "compensate_failure": True,
            "custom_race_schedule": [{"turn": idx + 1, "program_id": 1000 + idx} for idx in range(32)],
        }

    def test_race_heavy_route_boosts_core_speed_over_wit_when_core_stats_are_behind(self):
        chara = {"turn": 42, "speed": 420, "stamina": 360, "power": 350, "guts": 220, "wiz": 420}
        speed_cmd = {
            "command_type": 1,
            "command_id": 101,
            "is_enable": 1,
            "failure_rate": 2,
            "training_partner_array": [1, 2],
            "tips_event_partner_array": [],
            "params_inc_dec_info_array": [
                {"target_type": 1, "value": 18},
                {"target_type": 3, "value": 6},
                {"target_type": 10, "value": -18},
            ],
        }
        wit_cmd = {
            "command_type": 1,
            "command_id": 106,
            "is_enable": 1,
            "failure_rate": 0,
            "training_partner_array": [1, 2],
            "tips_event_partner_array": [],
            "params_inc_dec_info_array": [
                {"target_type": 5, "value": 15},
                {"target_type": 1, "value": 3},
                {"target_type": 10, "value": 5},
            ],
        }

        speed_score = self.strategy._score_command(speed_cmd, {}, chara, self.race_heavy_preset)
        wit_score = self.strategy._score_command(wit_cmd, {}, chara, self.race_heavy_preset)

        self.assertGreater(speed_score, wit_score)

    def test_race_heavy_route_rewards_high_output_rainbow_training(self):
        chara = {
            "turn": 52,
            "speed": 610,
            "stamina": 470,
            "power": 540,
            "guts": 300,
            "wiz": 420,
            "evaluation_info_array": [
                {"target_id": 1, "evaluation": 100},
                {"target_id": 2, "evaluation": 100},
                {"target_id": 3, "evaluation": 100},
                {"target_id": 4, "evaluation": 100},
            ],
        }
        strong = {
            "command_type": 1,
            "command_id": 102,
            "is_enable": 1,
            "failure_rate": 0,
            "training_partner_array": [1, 2, 3],
            "tips_event_partner_array": [],
            "params_inc_dec_info_array": [
                {"target_type": 2, "value": 13},
                {"target_type": 3, "value": 22},
                {"target_type": 30, "value": 6},
                {"target_type": 10, "value": -18},
            ],
        }
        weak = {
            "command_type": 1,
            "command_id": 101,
            "is_enable": 1,
            "failure_rate": 0,
            "training_partner_array": [],
            "tips_event_partner_array": [],
            "params_inc_dec_info_array": [
                {"target_type": 1, "value": 12},
                {"target_type": 3, "value": 5},
                {"target_type": 30, "value": 2},
                {"target_type": 10, "value": -18},
            ],
        }

        strong_bonus = self.strategy._race_heavy_training_efficiency_adjustment(strong, chara, self.race_heavy_preset, 52)
        weak_bonus = self.strategy._race_heavy_training_efficiency_adjustment(weak, chara, self.race_heavy_preset, 52)

        self.assertGreater(strong_bonus, 0.12)
        self.assertLess(weak_bonus, 0.0)

    def test_race_heavy_route_recreation_is_more_conservative(self):
        recreation = {"command_type": 3, "command_id": 301}
        baseline = self.strategy._should_recreate(recreation, {}, 41, motivation=3, vital=80, best_score=0.24)
        race_heavy = self.strategy._should_recreate(recreation, self.race_heavy_preset, 41, motivation=3, vital=80, best_score=0.24)

        self.assertTrue(baseline)
        self.assertFalse(race_heavy)

    def test_riko_presence_does_not_unlock_stat_recreation_bias(self):
        preset = {"_run_context": {"friend_card_id": 30036}}
        chara = {"evaluation_info_array": [{"target_id": 6, "evaluation": 70, "is_outing": 0}]}
        recreation = {"command_type": 3, "command_id": 0, "command_group_id": 301}

        should_recreate = self.strategy._should_recreate(
            recreation,
            preset,
            41,
            motivation=5,
            vital=70,
            best_score=0.34,
            chara=chara,
        )

        self.assertFalse(should_recreate)

    def test_riko_presence_does_not_unlock_390_without_outing_ready(self):
        preset = {"_run_context": {"friend_card_id": 30036}}
        chara = {"evaluation_info_array": [{"target_id": 6, "evaluation": 70, "is_outing": 0}]}
        recreation = {"command_type": 3, "command_id": 0, "command_group_id": 390}

        should_recreate = self.strategy._should_recreate(
            recreation,
            preset,
            41,
            motivation=5,
            vital=35,
            best_score=0.10,
            chara=chara,
        )

        self.assertFalse(should_recreate)

    def test_riko_stat_recreation_bias_does_not_trust_bare_301(self):
        preset = {"_run_context": {"friend_card_id": 30036}}
        chara = {"evaluation_info_array": [{"target_id": 6, "evaluation": 70, "is_outing": 1}]}
        recreation = {"command_type": 3, "command_id": 0, "command_group_id": 301}

        should_recreate = self.strategy._should_recreate(
            recreation,
            preset,
            41,
            motivation=5,
            vital=70,
            best_score=0.34,
            chara=chara,
        )

        self.assertFalse(should_recreate)

    def test_deck_riko_bare_301_does_not_replace_rest_when_ready(self):
        preset = {"_run_context": {"support_card_ids": [30036, 20031, 30054, 30014, 30010], "friend_card_id": 30017}}
        chara = {"evaluation_info_array": [{"target_id": 1, "evaluation": 91, "is_outing": 1}]}
        recreation = {"command_type": 3, "command_id": 301}

        should_recreate = self.strategy._should_recreate(
            recreation,
            preset,
            41,
            motivation=5,
            vital=35,
            best_score=0.34,
            chara=chara,
        )

        self.assertFalse(should_recreate)

    def test_ready_deck_riko_does_not_use_unverified_390_outing_command(self):
        preset = {
            "stat_friend_recreation_payloads": {"cards": {}},
            "_run_context": {
                "support_card_ids": [30036, 20031, 30054, 30014, 30010],
                "friend_card_id": 30017,
            },
        }
        chara = {
            "turn": 52,
            "vital": 70,
            "motivation": 5,
            "speed": 600,
            "stamina": 520,
            "power": 480,
            "guts": 300,
            "wiz": 700,
            "evaluation_info_array": [{"target_id": 1, "evaluation": 100, "is_outing": 1}],
        }
        data = {
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 102,
                        "is_enable": 1,
                        "failure_rate": 0,
                        "training_partner_array": [1, 2, 3],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 3, "value": 40},
                            {"target_type": 1, "value": 14},
                            {"target_type": 30, "value": 8},
                            {"target_type": 10, "value": -18},
                        ],
                    },
                    {"command_type": 3, "command_id": 390, "is_enable": 1},
                    {"command_type": 3, "command_id": 0, "command_group_id": 301, "is_enable": 1},
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ],
            },
        }

        command = self.strategy._best_command(data, chara, preset)

        self.assertFalse(
            command.get("command_type") == 3
            and self.strategy._effective_command_id(command) == 390
        )

    def test_initial_riko_decision_uses_verified_outing_payload(self):
        preset = {
            "stat_friend_recreation_payloads": {
                "cards": {
                    "30036": {
                        "initial": {
                            "verified": True,
                            "command_type": 3,
                            "command_id": 0,
                            "command_group_id": 390,
                            "select_id": 9006,
                        },
                    },
                },
            },
            "_run_context": {
                "support_card_ids": [30036, 20031, 30054, 30014, 30010],
                "friend_card_id": 30017,
            },
        }
        state = {
            "data": {
                "chara_info": {
                    "turn": 25,
                    "vital": 40,
                    "motivation": 5,
                    "speed": 300,
                    "stamina": 260,
                    "power": 280,
                    "guts": 180,
                    "wiz": 320,
                    "evaluation_info_array": [
                        {"target_id": 1, "evaluation": 79, "is_outing": 1, "story_step": 0}
                    ],
                },
                "home_info": {
                    "command_info_array": [
                        {
                            "command_type": 1,
                            "command_id": 102,
                            "is_enable": 1,
                            "failure_rate": 0,
                            "training_partner_array": [2, 3],
                            "tips_event_partner_array": [],
                            "params_inc_dec_info_array": [
                                {"target_type": 3, "value": 38},
                                {"target_type": 1, "value": 12},
                                {"target_type": 30, "value": 8},
                                {"target_type": 10, "value": -18},
                            ],
                        },
                        {"command_type": 3, "command_id": 390, "is_enable": 1},
                        {"command_type": 7, "command_id": 701, "is_enable": 1},
                    ],
                },
            }
        }

        decision = self.strategy.next_decision(state, preset)

        self.assertEqual(decision.action, "command")
        self.assertEqual(decision.payload.get("command_type"), 3)
        self.assertEqual(decision.payload.get("command_id"), 0)
        self.assertEqual(decision.payload.get("command_group_id"), 390)
        self.assertEqual(decision.payload.get("select_id"), 9006)

    def test_default_riko_payload_uses_captured_select_id(self):
        preset = {
            "_run_context": {
                "support_card_ids": [30036, 20031, 30054, 30014, 30010],
                "friend_card_id": 30017,
            },
        }
        state = {
            "data": {
                "chara_info": {
                    "turn": 26,
                    "vital": 55,
                    "motivation": 5,
                    "speed": 300,
                    "stamina": 260,
                    "power": 280,
                    "guts": 180,
                    "wiz": 320,
                    "evaluation_info_array": [
                        {"target_id": 1, "evaluation": 84, "is_outing": 1, "story_step": 1}
                    ],
                },
                "home_info": {
                    "command_info_array": [
                        {
                            "command_type": 1,
                            "command_id": 102,
                            "is_enable": 1,
                            "failure_rate": 0,
                            "training_partner_array": [2, 3],
                            "tips_event_partner_array": [],
                            "params_inc_dec_info_array": [
                                {"target_type": 3, "value": 38},
                                {"target_type": 1, "value": 12},
                                {"target_type": 30, "value": 8},
                                {"target_type": 10, "value": -18},
                            ],
                        },
                        {"command_type": 3, "command_id": 390, "is_enable": 1},
                        {"command_type": 7, "command_id": 701, "is_enable": 1},
                    ],
                },
            },
        }

        decision = self.strategy.next_decision(state, preset)

        self.assertEqual(decision.action, "command")
        self.assertEqual(decision.payload.get("command_type"), 3)
        self.assertEqual(decision.payload.get("command_id"), 0)
        self.assertEqual(decision.payload.get("command_group_id"), 390)
        self.assertEqual(decision.payload.get("select_id"), 9006)

    def test_exhausted_riko_chain_does_not_keep_using_390(self):
        preset = {
            "_run_context": {
                "support_card_ids": [30036, 20031, 30054, 30014, 30010],
                "friend_card_id": 30017,
            },
        }
        chara = {
            "turn": 52,
            "vital": 34,
            "motivation": 5,
            "speed": 545,
            "stamina": 427,
            "power": 464,
            "guts": 457,
            "wiz": 530,
            "evaluation_info_array": [
                {"target_id": 1, "evaluation": 100, "is_outing": 1, "story_step": 5}
            ],
        }
        state = {
            "data": {
                "chara_info": chara,
                "home_info": {
                    "command_info_array": [
                        {
                            "command_type": 1,
                            "command_id": 101,
                            "is_enable": 1,
                            "failure_rate": 0,
                            "training_partner_array": [2, 3],
                            "tips_event_partner_array": [],
                            "params_inc_dec_info_array": [
                                {"target_type": 1, "value": 20},
                                {"target_type": 3, "value": 6},
                                {"target_type": 30, "value": 4},
                                {"target_type": 10, "value": -18},
                            ],
                        },
                        {"command_type": 3, "command_id": 390, "is_enable": 1},
                        {"command_type": 7, "command_id": 701, "is_enable": 1},
                    ],
                },
            },
        }

        summary = self.strategy._outing_summary_for_signals(chara, preset)
        decision = self.strategy.next_decision(state, preset)

        self.assertEqual((summary or {}).get("total_remaining"), 0)
        self.assertFalse((summary or {}).get("any_ready"))
        self.assertFalse(
            decision.payload.get("command_type") == 3
            and self.strategy._effective_command_id(decision.payload) == 390
        )

    def test_started_deck_riko_does_not_use_unverified_390_outing_command_by_default(self):
        preset = {
            "stat_friend_recreation_payloads": {"cards": {}},
            "_run_context": {
                "support_card_ids": [30036, 20031, 30054, 30014, 30010],
                "friend_card_id": 30017,
            },
        }
        chara = {
            "turn": 26,
            "vital": 55,
            "motivation": 5,
            "speed": 300,
            "stamina": 260,
            "power": 280,
            "guts": 180,
            "wiz": 320,
            "evaluation_info_array": [
                {
                    "target_id": 1,
                    "training_partner_id": 1,
                    "evaluation": 84,
                    "is_outing": 1,
                    "story_step": 1,
                }
            ],
        }
        data = {
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 102,
                        "is_enable": 1,
                        "failure_rate": 0,
                        "training_partner_array": [2, 3],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 3, "value": 38},
                            {"target_type": 1, "value": 12},
                            {"target_type": 30, "value": 8},
                            {"target_type": 10, "value": -18},
                        ],
                    },
                    {"command_type": 3, "command_id": 301, "is_enable": 1},
                    {"command_type": 3, "command_id": 390, "is_enable": 1},
                    {"command_type": 4, "command_id": 401, "is_enable": 1},
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ],
            },
        }

        command = self.strategy._best_command(data, chara, preset)

        self.assertFalse(
            command.get("command_type") == 3
            and self.strategy._effective_command_id(command) == 390
        )

    def test_started_deck_riko_ignores_unverified_target_select_id_probe_flag(self):
        preset = {
            "stat_friend_started_recreation_api_enabled": True,
            "stat_friend_recreation_payloads": {"cards": {}},
            "_run_context": {
                "support_card_ids": [30036, 20031, 30054, 30014, 30010],
                "friend_card_id": 30017,
            },
        }
        chara = {
            "turn": 26,
            "vital": 55,
            "motivation": 5,
            "speed": 300,
            "stamina": 260,
            "power": 280,
            "guts": 180,
            "wiz": 320,
            "evaluation_info_array": [
                {
                    "target_id": 1,
                    "training_partner_id": 1,
                    "evaluation": 84,
                    "is_outing": 1,
                    "story_step": 1,
                }
            ],
        }
        data = {
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 102,
                        "is_enable": 1,
                        "failure_rate": 0,
                        "training_partner_array": [2, 3],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 3, "value": 38},
                            {"target_type": 1, "value": 12},
                            {"target_type": 30, "value": 8},
                            {"target_type": 10, "value": -18},
                        ],
                    },
                    {"command_type": 3, "command_id": 301, "is_enable": 1},
                    {"command_type": 3, "command_id": 390, "is_enable": 1},
                    {"command_type": 4, "command_id": 401, "is_enable": 1},
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ],
            },
        }

        command = self.strategy._best_command(data, chara, preset)

        self.assertFalse(
            command.get("command_type") == 3
            and self.strategy._effective_command_id(command) == 390
        )

    def test_started_deck_riko_uses_learned_payload_without_probe_flag(self):
        preset = {
            "stat_friend_recreation_payloads": {
                "cards": {
                    "30036": {
                        "started": {
                            "verified": True,
                            "command_type": 3,
                            "command_id": 0,
                            "command_group_id": 777,
                            "select_id": "partner_id",
                        },
                    },
                },
            },
            "_run_context": {
                "support_card_ids": [30036, 20031, 30054, 30014, 30010],
                "friend_card_id": 30017,
            },
        }
        state = {
            "data": {
                "chara_info": {
                    "turn": 26,
                    "vital": 55,
                    "motivation": 5,
                    "speed": 300,
                    "stamina": 260,
                    "power": 280,
                    "guts": 180,
                    "wiz": 320,
                    "evaluation_info_array": [
                        {"target_id": 1, "evaluation": 84, "is_outing": 1, "story_step": 1}
                    ],
                },
                "home_info": {
                    "command_info_array": [
                        {
                            "command_type": 1,
                            "command_id": 102,
                            "is_enable": 1,
                            "failure_rate": 0,
                            "training_partner_array": [2, 3],
                            "tips_event_partner_array": [],
                            "params_inc_dec_info_array": [
                                {"target_type": 3, "value": 38},
                                {"target_type": 1, "value": 12},
                                {"target_type": 30, "value": 8},
                                {"target_type": 10, "value": -18},
                            ],
                        },
                        {"command_type": 3, "command_id": 390, "is_enable": 1},
                        {"command_type": 7, "command_id": 701, "is_enable": 1},
                    ],
                },
            }
        }

        decision = self.strategy.next_decision(state, preset)

        self.assertEqual(decision.action, "command")
        self.assertEqual(decision.payload.get("command_type"), 3)
        self.assertEqual(decision.payload.get("command_id"), 0)
        self.assertEqual(decision.payload.get("command_group_id"), 777)
        self.assertEqual(decision.payload.get("select_id"), 1)

    def test_started_riko_payload_does_not_use_unverified_390_by_default(self):
        preset = {
            "stat_friend_recreation_payloads": {"cards": {}},
            "_run_context": {
                "support_card_ids": [30036, 20031, 30054, 30014, 30010],
                "friend_card_id": 30017,
            },
        }
        state = {
            "data": {
                "chara_info": {
                    "turn": 26,
                    "vital": 55,
                    "motivation": 5,
                    "playing_state": 1,
                    "speed": 300,
                    "stamina": 260,
                    "power": 280,
                    "guts": 180,
                    "wiz": 320,
                    "evaluation_info_array": [
                        {"target_id": 1, "evaluation": 84, "is_outing": 1, "story_step": 1}
                    ],
                },
                "home_info": {
                    "command_info_array": [
                        {
                            "command_type": 1,
                            "command_id": 102,
                            "is_enable": 1,
                            "failure_rate": 0,
                            "training_partner_array": [2, 3],
                            "tips_event_partner_array": [],
                            "params_inc_dec_info_array": [
                                {"target_type": 3, "value": 38},
                                {"target_type": 1, "value": 12},
                                {"target_type": 30, "value": 8},
                                {"target_type": 10, "value": -18},
                            ],
                        },
                        {"command_type": 3, "command_id": 390, "is_enable": 1},
                        {"command_type": 4, "command_id": 401, "is_enable": 1},
                        {"command_type": 7, "command_id": 701, "is_enable": 1},
                    ],
                },
            },
        }

        decision = self.strategy.next_decision(state, preset)

        self.assertEqual(decision.action, "command")
        self.assertFalse(
            decision.payload.get("command_type") == 3
            and self.strategy._effective_command_id(decision.payload) == 390
        )

    def test_started_riko_unverified_390_does_not_replace_low_hp_rest(self):
        preset = {
            "stat_friend_recreation_payloads": {"cards": {}},
            "_run_context": {
                "support_card_ids": [30036, 20031, 30054, 30014, 30010],
                "friend_card_id": 30017,
            },
        }
        state = {
            "data": {
                "chara_info": {
                    "turn": 26,
                    "vital": 25,
                    "motivation": 5,
                    "playing_state": 1,
                    "speed": 300,
                    "stamina": 260,
                    "power": 280,
                    "guts": 180,
                    "wiz": 320,
                    "evaluation_info_array": [
                        {"target_id": 1, "evaluation": 84, "is_outing": 1, "story_step": 1}
                    ],
                },
                "home_info": {
                    "command_info_array": [
                        {
                            "command_type": 1,
                            "command_id": 102,
                            "is_enable": 1,
                            "failure_rate": 30,
                            "training_partner_array": [2],
                            "tips_event_partner_array": [],
                            "params_inc_dec_info_array": [
                                {"target_type": 3, "value": 15},
                                {"target_type": 10, "value": -18},
                            ],
                        },
                        {"command_type": 3, "command_id": 390, "is_enable": 1},
                        {"command_type": 7, "command_id": 701, "is_enable": 1},
                    ],
                },
            },
        }

        decision = self.strategy.next_decision(state, preset)

        self.assertEqual(decision.action, "command")
        self.assertEqual(decision.payload.get("command_type"), 7)
        self.assertEqual(decision.payload.get("command_id"), 701)

    def test_ready_deck_riko_bare_301_does_not_override_summer_training(self):
        preset = {
            "_run_context": {
                "support_card_ids": [30036, 20031, 30054, 30014, 30010],
                "friend_card_id": 30017,
            },
        }
        chara = {
            "turn": 61,
            "vital": 10,
            "motivation": 5,
            "speed": 700,
            "stamina": 560,
            "power": 520,
            "guts": 330,
            "wiz": 760,
            "evaluation_info_array": [{"target_id": 1, "evaluation": 100, "is_outing": 1}],
        }
        data = {
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 603,
                        "is_enable": 1,
                        "failure_rate": 0,
                        "training_partner_array": [1, 2, 3, 4],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 3, "value": 70},
                            {"target_type": 2, "value": 16},
                            {"target_type": 30, "value": 10},
                            {"target_type": 10, "value": -18},
                        ],
                    },
                    {"command_type": 3, "command_id": 0, "command_group_id": 301, "is_enable": 1},
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ],
            },
        }

        command = self.strategy._best_command(data, chara, preset)

        self.assertNotEqual(command.get("command_type"), 3)

    def test_ready_deck_riko_390_does_not_override_at_ceiling(self):
        preset = {
            "_run_context": {
                "support_card_ids": [30036, 20031, 30054, 30014, 30010],
                "friend_card_id": 30017,
            },
        }
        chara = {
            "turn": 52,
            "vital": 80,
            "motivation": 5,
            "speed": 600,
            "stamina": 520,
            "power": 480,
            "guts": 300,
            "wiz": 700,
            "evaluation_info_array": [{"target_id": 1, "evaluation": 100, "is_outing": 1}],
        }
        data = {
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 102,
                        "is_enable": 1,
                        "failure_rate": 0,
                        "training_partner_array": [1, 2, 3],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 3, "value": 40},
                            {"target_type": 1, "value": 14},
                            {"target_type": 30, "value": 8},
                            {"target_type": 10, "value": -18},
                        ],
                    },
                    {"command_type": 3, "command_id": 390, "is_enable": 1},
                    {"command_type": 3, "command_id": 0, "command_group_id": 301, "is_enable": 1},
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ],
            },
        }

        command = self.strategy._best_command(data, chara, preset)

        self.assertNotEqual(command.get("command_type"), 3)

    def test_deck_riko_ready_does_not_unlock_uncaptured_390_recreation(self):
        preset = {
            "stat_friend_recreation_payloads": {"cards": {}},
            "_run_context": {"support_card_ids": [30036, 20031, 30054, 30014, 30010], "friend_card_id": 30017},
        }
        chara = {"evaluation_info_array": [{"target_id": 1, "evaluation": 91, "is_outing": 1}]}
        recreation = {"command_type": 3, "command_id": 390}

        should_recreate = self.strategy._should_recreate(
            recreation,
            preset,
            41,
            motivation=5,
            vital=35,
            best_score=0.34,
            chara=chara,
        )

        self.assertFalse(should_recreate)

    def test_recreation_payload_preserves_existing_command_group_id(self):
        state = {
            "data": {
                "chara_info": {"turn": 41, "vital": 35, "motivation": 5, "playing_state": 1},
                "home_info": {
                    "command_info_array": [
                        {"command_type": 3, "command_id": 0, "command_group_id": 301, "is_enable": 1},
                    ],
                },
            },
        }

        decision = self.strategy.next_decision(state, {})

        self.assertEqual(decision.action, "command")
        self.assertEqual(decision.payload.get("command_type"), 3)
        self.assertEqual(decision.payload.get("command_id"), 0)
        self.assertEqual(decision.payload.get("command_group_id"), 301)

    def test_riko_stat_recreation_bias_requires_verified_390_payload(self):
        preset = {
            "stat_friend_recreation_payloads": {"cards": {}},
            "_run_context": {"friend_card_id": 30036},
        }
        chara = {"evaluation_info_array": [{"target_id": 6, "evaluation": 70, "is_outing": 1}]}
        recreation = {"command_type": 3, "command_id": 0, "command_group_id": 390}

        should_recreate = self.strategy._should_recreate(
            recreation,
            preset,
            41,
            motivation=5,
            vital=70,
            best_score=0.34,
            chara=chara,
        )

        self.assertFalse(should_recreate)

    def test_trajectory_bonus_pushes_lagging_stat_toward_top_centroid(self):
        chara = {"turn": 36, "speed": 320, "stamina": 420, "power": 420, "guts": 250, "wiz": 320, "vital": 72}
        preset = {
            "expect_attribute": self.targets,
            "score_value": [[0.11, 0.10, 0.006, 0.09]] * 4,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
            "compensate_failure": True,
            "trajectory_centroids": {
                "schema": "sweepy_trajectory_centroids_v1",
                "feature_scales": {"speed": 900, "stamina": 900, "power": 900, "guts": 600, "wit": 700, "hp": 100, "skill_point": 400},
                "checkpoints": {
                    "36": {
                        "top_count": 5,
                        "bottom_count": 5,
                        "top_centroid": {"speed": 520, "stamina": 430, "power": 430, "guts": 260, "wit": 330, "hp": 75, "skill_point": 180},
                        "bottom_centroid": {"speed": 300, "stamina": 410, "power": 410, "guts": 240, "wit": 310, "hp": 70, "skill_point": 150},
                    }
                },
            },
        }
        speed_cmd = make_training_command(101, 1, 14)
        stamina_cmd = make_training_command(105, 2, 14)

        speed_score = self.strategy._score_command(speed_cmd, {}, chara, preset)
        stamina_score = self.strategy._score_command(stamina_cmd, {}, chara, preset)

        self.assertGreater(speed_score, stamina_score)
        self.assertGreater(float(speed_cmd.get("_trajectory_training_bonus") or 0.0), 0.0)


class ClimaxTurnTests(unittest.TestCase):
    def setUp(self):
        self.strategy = MantStrategy()

    def test_pre_climax_returns_false(self):
        self.assertFalse(self.strategy._is_climax_turn({"turn": 72}))

    def test_climax_window_returns_true(self):
        self.assertTrue(self.strategy._is_climax_turn({"turn": 73}))
        self.assertTrue(self.strategy._is_climax_turn({"turn": 78}))


class FutureEffectDecisionTests(unittest.TestCase):
    def setUp(self):
        self.strategy = MantStrategy()

    def test_upcoming_guaranteed_hp_relief_can_avoid_unneeded_rest(self):
        data = {
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 101,
                        "is_enable": 1,
                        "failure_rate": 0,
                        "training_partner_array": [1],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 1, "value": 15},
                            {"target_type": 10, "value": -18},
                        ],
                    },
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ]
            }
        }
        chara = {"turn": 71, "vital": 44, "max_vital": 100, "motivation": 4, "speed": 520, "stamina": 480, "power": 460, "guts": 220, "wiz": 260}
        base_preset = {
            "expect_attribute": [1200, 1100, 1100, 800, 700],
            "score_value": [[0.11, 0.10, 0.006, 0.09]] * 4,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
            "compensate_failure": True,
            "rest_threshold": 48,
        }
        forecast_preset = {
            **base_preset,
            "future_turn_effects": {
                "schema": "sweepy_future_turn_effects_v1",
                "turns": {
                    "71": {"kind": "training", "effects": {"hp": 50}},
                },
            },
        }

        baseline = self.strategy._best_command(data, chara, base_preset)
        forecasted = self.strategy._best_command(data, chara, forecast_preset)

        self.assertEqual((baseline or {}).get("command_type"), 7)
        self.assertEqual((forecasted or {}).get("command_type"), 1)

    def test_first_summer_friendship_gap_pushes_training_instead_of_safe_rest(self):
        data = {
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 101,
                        "is_enable": 1,
                        "failure_rate": 8,
                        "training_partner_array": [1, 2],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 1, "value": 16},
                            {"target_type": 10, "value": -18},
                        ],
                    },
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ]
            }
        }
        chara = {
            "turn": 20,
            "vital": 27,
            "max_vital": 100,
            "motivation": 4,
            "speed": 280,
            "stamina": 250,
            "power": 235,
            "guts": 140,
            "wiz": 180,
            "evaluation_info_array": [
                {"target_id": 1, "evaluation": 45},
                {"target_id": 2, "evaluation": 52},
                {"target_id": 3, "evaluation": 38},
                {"target_id": 4, "evaluation": 30},
                {"target_id": 5, "evaluation": 22},
                {"target_id": 6, "evaluation": 25},
            ],
        }
        preset = {
            "expect_attribute": [1200, 900, 900, 700, 700],
            "score_value": [[0.11, 0.10, 0.006, 0.09]] * 4,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
            "compensate_failure": True,
            "rest_threshold": 48,
            "first_summer_friendship_enabled": True,
            "first_summer_friendship_target_turn": 35,
            "first_summer_friendship_target_rainbows": 4,
        }

        chosen = self.strategy._best_command(data, chara, preset)

        self.assertEqual((chosen or {}).get("command_type"), 1)

    def test_low_hp_safe_wit_training_beats_rest(self):
        data = {
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 106,
                        "is_enable": 1,
                        "failure_rate": 14,
                        "training_partner_array": [1, 2],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 5, "value": 28},
                            {"target_type": 1, "value": 6},
                            {"target_type": 10, "value": 5},
                        ],
                    },
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ]
            }
        }
        chara = {
            "turn": 58,
            "vital": 25,
            "max_vital": 100,
            "motivation": 5,
            "speed": 355,
            "stamina": 370,
            "power": 574,
            "guts": 312,
            "wiz": 534,
            "evaluation_info_array": [
                {"target_id": 1, "evaluation": 100},
                {"target_id": 2, "evaluation": 100},
            ],
        }
        preset = {
            "expect_attribute": [1200, 900, 900, 700, 900],
            "score_value": [[0.11, 0.10, 0.006, 0.09]] * 4,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
            "compensate_failure": True,
            "rest_threshold": 48,
        }

        chosen = self.strategy._best_command(data, chara, preset)

        self.assertEqual((chosen or {}).get("command_id"), 106)

    def test_low_hp_safe_wit_training_substitutes_for_risky_best_tile(self):
        data = {
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 101,
                        "is_enable": 1,
                        "failure_rate": 24,
                        "training_partner_array": [1, 2, 3, 4],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 1, "value": 11},
                            {"target_type": 3, "value": 5},
                            {"target_type": 30, "value": 2},
                            {"target_type": 10, "value": -17},
                        ],
                    },
                    {
                        "command_type": 1,
                        "command_id": 106,
                        "is_enable": 1,
                        "failure_rate": 0,
                        "training_partner_array": [1, 2],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 1, "value": 2},
                            {"target_type": 5, "value": 8},
                            {"target_type": 30, "value": 4},
                            {"target_type": 10, "value": 5},
                        ],
                    },
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ]
            }
        }
        chara = {
            "turn": 6,
            "vital": 36,
            "max_vital": 100,
            "motivation": 3,
            "speed": 187,
            "stamina": 177,
            "power": 223,
            "guts": 138,
            "wiz": 177,
            "evaluation_info_array": [
                {"target_id": 1, "evaluation": 35},
                {"target_id": 2, "evaluation": 35},
                {"target_id": 3, "evaluation": 35},
                {"target_id": 4, "evaluation": 35},
            ],
        }
        preset = {
            "expect_attribute": [1200, 900, 900, 700, 900],
            "score_value": [[0.11, 0.10, 0.006, 0.09]] * 4,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
            "compensate_failure": True,
            "rest_threshold": 48,
        }

        chosen = self.strategy._best_command(data, chara, preset)

        self.assertEqual((chosen or {}).get("command_id"), 106)

    def test_low_hp_hard_failure_prefers_safe_summer_wit_even_when_low_score(self):
        data = {
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 603,
                        "is_enable": 1,
                        "failure_rate": 32,
                        "training_partner_array": [4],
                        "tips_event_partner_array": [4],
                        "params_inc_dec_info_array": [
                            {"target_type": 2, "value": 6},
                            {"target_type": 3, "value": 10},
                            {"target_type": 30, "value": 2},
                            {"target_type": 10, "value": -24},
                        ],
                    },
                    {
                        "command_type": 1,
                        "command_id": 605,
                        "is_enable": 1,
                        "failure_rate": 2,
                        "training_partner_array": [],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 1, "value": 3},
                            {"target_type": 5, "value": 10},
                            {"target_type": 30, "value": 2},
                            {"target_type": 10, "value": 5},
                        ],
                    },
                ]
            }
        }
        chara = {
            "turn": 40,
            "vital": 35,
            "max_vital": 100,
            "motivation": 2,
            "speed": 406,
            "stamina": 278,
            "power": 367,
            "guts": 292,
            "wiz": 515,
            "evaluation_info_array": [
                {"target_id": 1, "evaluation": 80},
                {"target_id": 2, "evaluation": 80},
                {"target_id": 3, "evaluation": 80},
                {"target_id": 4, "evaluation": 80},
            ],
        }
        preset = {
            "expect_attribute": [1200, 900, 950, 700, 1200],
            "score_value": [[0.11, 0.10, 0.006, 0.09]] * 4,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
            "compensate_failure": True,
            "rest_threshold": 30,
            "low_hp_wit_training_substitute_min_score": 999,
            "hard_failure_safe_wit_threshold": 28,
            "hard_failure_safe_wit_vital_ceiling": 60,
        }

        chosen = self.strategy._best_command(data, chara, preset)

        self.assertEqual((chosen or {}).get("command_id"), 605)

    def test_low_hp_wit_substitution_rejects_high_failure_wit(self):
        data = {
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 101,
                        "is_enable": 1,
                        "failure_rate": 35,
                        "training_partner_array": [1],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 1, "value": 12},
                            {"target_type": 10, "value": -20},
                        ],
                    },
                    {
                        "command_type": 1,
                        "command_id": 106,
                        "is_enable": 1,
                        "failure_rate": 42,
                        "training_partner_array": [1, 2, 3],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 5, "value": 18},
                            {"target_type": 10, "value": 5},
                        ],
                    },
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ]
            }
        }
        chara = {
            "turn": 40,
            "vital": 11,
            "max_vital": 100,
            "motivation": 5,
            "speed": 448,
            "stamina": 375,
            "power": 459,
            "guts": 287,
            "wiz": 313,
            "evaluation_info_array": [
                {"target_id": 1, "evaluation": 100},
                {"target_id": 2, "evaluation": 100},
                {"target_id": 3, "evaluation": 100},
            ],
        }
        preset = {
            "expect_attribute": [1200, 900, 900, 700, 900],
            "score_value": [[0.11, 0.10, 0.006, 0.09]] * 4,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
            "compensate_failure": True,
            "rest_threshold": 48,
        }

        chosen = self.strategy._best_command(data, chara, preset)

        self.assertNotEqual((chosen or {}).get("command_id"), 106)
        self.assertIn((chosen or {}).get("command_type"), {3, 7})

    def test_first_summer_friendship_gap_does_not_force_high_failure_training(self):
        data = {
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 101,
                        "is_enable": 1,
                        "failure_rate": 27,
                        "training_partner_array": [1, 2],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 1, "value": 16},
                            {"target_type": 10, "value": -18},
                        ],
                    },
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ]
            }
        }
        chara = {
            "turn": 20,
            "vital": 27,
            "max_vital": 100,
            "motivation": 4,
            "speed": 280,
            "stamina": 250,
            "power": 235,
            "guts": 140,
            "wiz": 180,
            "evaluation_info_array": [
                {"target_id": 1, "evaluation": 45},
                {"target_id": 2, "evaluation": 52},
                {"target_id": 3, "evaluation": 38},
                {"target_id": 4, "evaluation": 30},
                {"target_id": 5, "evaluation": 22},
                {"target_id": 6, "evaluation": 25},
            ],
        }
        preset = {
            "expect_attribute": [1200, 900, 900, 700, 700],
            "score_value": [[0.11, 0.10, 0.006, 0.09]] * 4,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
            "compensate_failure": True,
            "rest_threshold": 48,
            "first_summer_friendship_enabled": True,
            "first_summer_friendship_target_turn": 35,
            "first_summer_friendship_target_rainbows": 4,
        }

        chosen = self.strategy._best_command(data, chara, preset)

        self.assertEqual((chosen or {}).get("command_type"), 7)

    def test_first_summer_friendship_gap_makes_recreation_more_emergency_only(self):
        recreation = {"command_type": 3, "command_id": 301}
        should_recreate = self.strategy._should_recreate(
            recreation,
            {"first_summer_friendship_target_turn": 35},
            20,
            motivation=2,
            vital=50,
            best_score=0.05,
            friendship_gap=2,
        )

        self.assertFalse(should_recreate)


class BondEquityGateTests(unittest.TestCase):
    def setUp(self):
        self.strategy = MantStrategy()
        self.preset = {
            "expect_attribute": [1200, 900, 900, 700, 700],
            "score_value": [[0.11, 0.10, 0.006, 0.09]] * 4,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
            "compensate_failure": True,
            "rest_threshold": 48,
        }

    def _cmd(self, command_id, target_type, gain, partners, failure=0):
        return {
            "command_type": 1,
            "command_id": command_id,
            "is_enable": 1,
            "failure_rate": failure,
            "training_partner_array": list(partners),
            "tips_event_partner_array": [],
            "params_inc_dec_info_array": [
                {"target_type": target_type, "value": gain},
                {"target_type": 10, "value": -18},
            ],
        }

    def _chara(self, turn=20, vital=80):
        return {
            "turn": turn,
            "vital": vital,
            "max_vital": 100,
            "motivation": 5,
            "speed": 300,
            "stamina": 260,
            "power": 260,
            "guts": 160,
            "wiz": 180,
            "evaluation_info_array": [
                {"target_id": 1, "evaluation": 70},
                {"target_id": 2, "evaluation": 68},
                {"target_id": 3, "evaluation": 66},
                {"target_id": 4, "evaluation": 64},
                {"target_id": 5, "evaluation": 30},
                {"target_id": 6, "evaluation": 62},
            ],
        }

    def test_bond_equity_filters_to_lagging_card_training(self):
        data = {
            "home_info": {
                "command_info_array": [
                    self._cmd(101, 1, 24, [1, 2]),
                    self._cmd(105, 2, 10, [5]),
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ]
            }
        }

        chosen = self.strategy._best_command(data, self._chara(), self.preset)

        self.assertEqual((chosen or {}).get("command_id"), 105)
        self.assertTrue(((chosen or {}).get("_bond_equity_gate") or {}).get("active"))

    def test_bond_equity_allows_high_value_multi_partner_tile(self):
        data = {
            "home_info": {
                "command_info_array": [
                    self._cmd(101, 1, 46, [1, 2]),
                    self._cmd(105, 2, 10, [5]),
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ]
            }
        }

        chosen = self.strategy._best_command(data, self._chara(), self.preset)

        self.assertEqual((chosen or {}).get("command_id"), 101)
        self.assertEqual(((chosen or {}).get("_bond_equity_gate") or {}).get("override"), "high_value_training")

    def test_bond_equity_does_not_force_high_failure_training(self):
        data = {
            "home_info": {
                "command_info_array": [
                    self._cmd(101, 1, 24, [1, 2]),
                    self._cmd(105, 2, 10, [5], failure=42),
                    {"command_type": 7, "command_id": 701, "is_enable": 1},
                ]
            }
        }

        chosen = self.strategy._best_command(data, self._chara(vital=18), self.preset)

        self.assertEqual((chosen or {}).get("command_type"), 7)


class DecisionUnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.strategy = MantStrategy()

    def test_training_decision_carries_structured_understanding(self):
        state = {
            "data": {
                "chara_info": {
                    "turn": 40,
                    "playing_state": 1,
                    "vital": 72,
                    "max_vital": 100,
                    "speed": 420,
                    "stamina": 520,
                    "power": 360,
                    "guts": 220,
                    "wiz": 300,
                    "evaluation_info_array": [
                        {"target_id": 1, "evaluation": 70},
                        {"target_id": 2, "evaluation": 68},
                    ],
                },
                "home_info": {
                    "command_info_array": [
                        {
                            "command_type": 1,
                            "command_id": 101,
                            "is_enable": 1,
                            "failure_rate": 0,
                            "training_partner_array": [1, 2],
                            "tips_event_partner_array": [],
                            "params_inc_dec_info_array": [
                                {"target_type": 1, "value": 18},
                                {"target_type": 10, "value": -18},
                            ],
                        }
                    ]
                },
            }
        }
        preset = {
            "desired_parent_sparks": {"blue": ["Speed"], "pink": [], "green": [], "white": []},
            "expect_attribute": [1200, 1100, 1100, 800, 700],
            "score_value": [[0.11, 0.10, 0.006, 0.09]] * 4,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
            "compensate_failure": True,
        }

        decision = self.strategy.next_decision(state, preset)

        self.assertEqual(decision.action, "command")
        self.assertEqual(decision.understanding.get("primary_intent"), "blue_target_progress")
        self.assertIn("rainbow_setup", decision.understanding.get("intent_tags") or [])
        self.assertTrue((decision.understanding.get("signals") or {}).get("blue_target_match"))
        self.assertIn("blue spark", str(decision.understanding.get("summary") or "").lower())


class CapPursuitBonusTests(unittest.TestCase):
    """Cap-pursuit lever: fires ONLY for stats the user explicitly
    listed in `desired_parent_sparks.blue`. Target is 1100 (the ★★
    blue-spark threshold). No firing on `expect_attribute` — per user
    feedback, that field is the old "predestined stats" model and the
    bot must instead follow the deck's natural flow unless the user
    has explicitly named a spark stat.
    """

    def setUp(self):
        self.strategy = MantStrategy()

    def _chara(self, turn, speed=600, stamina=500, power=500, guts=300, wit=500):
        return {
            "turn": turn,
            "speed": speed, "stamina": stamina, "power": power,
            "guts": guts, "wiz": wit,
        }

    def _preset_blue(self, *stats):
        return {
            "desired_parent_sparks": {"blue": list(stats), "pink": [], "green": [], "white": []},
        }

    def test_no_bonus_when_blue_sparks_empty(self):
        """No blue spark set = no cap-pursuit. The bot follows the
        deck's natural flow via partner-count scoring."""
        chara = self._chara(turn=40, power=200)
        preset = self._preset_blue()  # empty list
        bonus = self.strategy._cap_pursuit_bonus(2, chara, preset)
        self.assertEqual(bonus, 0.0)

    def test_no_bonus_when_expect_attribute_is_set_but_no_blue_spark(self):
        """The user's preset may have legacy expect_attribute values
        from before this refactor — ignore them. Only blue-spark
        listing counts as an explicit cap-pursuit signal."""
        chara = self._chara(turn=40, power=200)
        preset = {
            "expect_attribute": [1200, 1166, 1200, 1166, 1177],
            "desired_parent_sparks": {"blue": [], "pink": [], "green": [], "white": []},
        }
        bonus = self.strategy._cap_pursuit_bonus(2, chara, preset)
        self.assertEqual(bonus, 0.0)

    def test_no_bonus_before_start_turn(self):
        """Junior year is bond-building. Cap-pursuit doesn't fire
        before turn 12 even when blue spark is set."""
        chara = self._chara(turn=8, power=200)
        preset = self._preset_blue("Power")
        bonus = self.strategy._cap_pursuit_bonus(2, chara, preset)
        self.assertEqual(bonus, 0.0)

    def test_bonus_fires_for_named_stat_at_target_1100(self):
        """When user lists Power as a blue spark, training Power
        below 1100 gets the bonus."""
        chara = self._chara(turn=40, power=500)
        preset = self._preset_blue("Power")
        bonus = self.strategy._cap_pursuit_bonus(2, chara, preset)
        self.assertGreater(bonus, 0.0)

    def test_no_bonus_when_stat_at_or_above_1100(self):
        """Once the stat reaches the ★★ threshold, cap-pursuit stops
        — anything beyond is bonus territory from the deck flow."""
        chara = self._chara(turn=60, power=1100)
        preset = self._preset_blue("Power")
        bonus = self.strategy._cap_pursuit_bonus(2, chara, preset)
        self.assertEqual(bonus, 0.0)

    def test_default_free_stat_budget_stops_cap_pursuit_at_950(self):
        chara = self._chara(turn=60, power=960)
        preset = self._preset_blue("Power")
        bonus = self.strategy._cap_pursuit_bonus(2, chara, preset)
        self.assertEqual(bonus, 0.0)

    def test_cap_pursuit_free_stat_budget_can_be_disabled(self):
        chara = self._chara(turn=60, power=960)
        preset = {
            "desired_parent_sparks": {"blue": ["Power"], "pink": [], "green": [], "white": []},
            "cap_pursuit_free_stats_budget_per_stat": 0,
        }
        bonus = self.strategy._cap_pursuit_bonus(2, chara, preset)
        self.assertGreater(bonus, 0.0)

    def test_bonus_does_not_fire_on_other_stats(self):
        """If the user lists Power as the blue spark, Wit training
        gets no cap-pursuit bonus — even if Wit is below 1100. The
        whole point is to NOT push training on stats the user didn't
        ask for."""
        chara = self._chara(turn=40, power=500, wit=200)
        preset = self._preset_blue("Power")
        power_bonus = self.strategy._cap_pursuit_bonus(2, chara, preset)
        wit_bonus = self.strategy._cap_pursuit_bonus(4, chara, preset)
        self.assertGreater(power_bonus, 0.0)
        self.assertEqual(wit_bonus, 0.0)

    def test_late_career_bonus_is_larger_than_early_career(self):
        """Escalation: at turn 70 the bonus is meaningfully larger
        than at turn 20 for the same stat ratio. This is the 'must
        hit 1100 by career end' guarantee."""
        preset = self._preset_blue("Power")
        early = self.strategy._cap_pursuit_bonus(2, self._chara(turn=20, power=500), preset)
        late = self.strategy._cap_pursuit_bonus(2, self._chara(turn=70, power=500), preset)
        self.assertGreater(late, early)

    def test_blue_spark_power_outranks_wit_in_command_pick(self):
        """When user names Power as the blue spark and Power is 500
        with Wit at 1100, Power training should rank above Wit
        training even if Wit has more partners."""
        chara = self._chara(turn=60, power=500, wit=1100)
        preset = {
            "desired_parent_sparks": {"blue": ["Power"], "pink": [], "green": [], "white": []},
            "score_value": [[0.11, 0.10, 0.006, 0.09]] * 4,
            "base_score": [0, 0, 0, 0, 0],
            "stat_value_multiplier": [0.01, 0.01, 0.01, 0.01, 0.01, 0.005],
            "extra_weight": [[0, 0, 0, 0, 0]] * 4,
        }
        power_cmd = make_training_command(102, 3, 12)   # target_type=3 → power
        wit_cmd = make_training_command(105, 5, 12)     # target_type=5 → wit
        power_score = self.strategy._score_command(power_cmd, {}, chara, preset)
        wit_score = self.strategy._score_command(wit_cmd, {}, chara, preset)
        self.assertGreater(power_score, wit_score)


if __name__ == "__main__":
    unittest.main()
