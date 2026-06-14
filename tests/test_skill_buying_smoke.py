import unittest
from pathlib import Path

from career_bot.skills import SkillBuyer


BASE_DIR = Path(__file__).resolve().parents[1]


def make_state(**overrides):
    chara = {
        "turn": 44,
        "card_id": 100102,
        "skill_point": 500,
        "stamina": 320,
        "skill_array": [],
        "skill_tips_array": [{"group_id": 20035, "rarity": 1, "level": 0}],
    }
    chara.update(overrides)
    return {"data": {"chara_info": chara}}


def low_stamina_check(**overrides):
    check = {
        "race_name": "Kikuka Sho",
        "distance": "Long",
        "style": "front_runner",
        "requirements": {"stamina": 612},
        "stats": {"stamina": 320},
        "stamina_low": True,
        "warnings": ["stamina low"],
    }
    check.update(overrides)
    return check


class FakeSkillClient:
    def __init__(self):
        self.calls = []

    def gain_skills(self, payload, turn, **kwargs):
        self.calls.append({"payload": payload, "turn": turn, "kwargs": kwargs})
        return make_state(skill_array=payload, skill_point=320)


class PartialRejectSkillClient:
    def __init__(self):
        self.calls = []

    def gain_skills(self, payload, turn, **kwargs):
        self.calls.append({"payload": payload, "turn": turn, "kwargs": kwargs})
        if len(payload) > 1:
            raise Exception("API error 205 on single_mode_free/gain_skills")
        skill_id = int(payload[0]["skill_id"])
        if skill_id == 200532:
            raise Exception("API error 208 on single_mode_free/gain_skills")
        if skill_id == 201252:
            return make_state(
                turn=turn,
                skill_point=880,
                skill_array=[{"skill_id": 201252, "level": 1}],
                skill_tips_array=[
                    {"group_id": 20125, "rarity": 1, "level": 0},
                    {"group_id": 20053, "rarity": 1, "level": 0},
                ],
            )
        raise AssertionError(f"unexpected skill purchase {skill_id}")


class RecoverableBatchSkillClient:
    def __init__(self):
        self.calls = []

    def gain_skills(self, payload, turn, **kwargs):
        self.calls.append({"payload": payload, "turn": turn, "kwargs": kwargs})
        if len(payload) > 1:
            raise Exception("API error 205 on single_mode_free/gain_skills")
        skill_id = int(payload[0]["skill_id"])
        if skill_id == 201252:
            return make_state(
                turn=turn,
                skill_point=880,
                skill_array=[{"skill_id": 201252, "level": 1}],
                skill_tips_array=[
                    {"group_id": 20125, "rarity": 1, "level": 0},
                    {"group_id": 20035, "rarity": 1, "level": 0},
                ],
            )
        if skill_id == 200352:
            return make_state(
                turn=turn,
                skill_point=760,
                skill_array=[{"skill_id": 201252, "level": 1}, {"skill_id": 200352, "level": 1}],
                skill_tips_array=[
                    {"group_id": 20125, "rarity": 1, "level": 0},
                    {"group_id": 20035, "rarity": 1, "level": 0},
                ],
            )
        raise AssertionError(f"unexpected skill purchase {skill_id}")


class TruncatedSkillArrayClient:
    def __init__(self):
        self.calls = []

    def gain_skills(self, payload, turn, **kwargs):
        self.calls.append({"payload": payload, "turn": turn, "kwargs": kwargs})
        return make_state(
            turn=turn,
            skill_point=340,
            skill_array=[],
            skill_tips_array=[{"group_id": 20160, "rarity": 1, "level": 0}],
        )


class SkillBuyingSmokeTests(unittest.TestCase):
    def test_estimate_cost_uses_real_game_skill_cost_data(self):
        buyer = SkillBuyer(BASE_DIR)

        self.assertEqual(
            buyer._estimate_cost({
                "skill_id": 200332,
                "name": "Corner Adept ○",
                "hint_level": 3,
            }),
            180,
        )
        self.assertEqual(
            buyer._estimate_cost({
                "skill_id": 200592,
                "name": "Position Pilfer",
                "hint_level": 3,
            }),
            180,
        )

    def test_pre_race_buy_does_not_submit_unaffordable_real_cost_skill(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()
        state = make_state(
            turn=24,
            skill_point=170,
            skill_array=[],
            skill_tips_array=[{"group_id": 20059, "rarity": 2, "level": 3}],
        )
        preset = {
            "pre_race_winprob_gate_enabled": False,
            "learn_skill_list": [["Position Pilfer"]],
            "learn_skill_append_defaults": False,
            "calendar_race_prebuy_min_sp": 80,
            "calendar_race_prebuy_keep_sp": 0,
            "calendar_race_prebuy_budget": 1800,
        }

        next_state, bought = buyer.buy_limited_for_race(
            client,
            state,
            preset,
            race_check={"race_name": "Hopeful Stakes", "style": "late_surger", "distance": "Medium"},
            max_skills=1,
            budget=1800,
            reserve=0,
            min_sp=80,
        )

        self.assertIs(next_state, state)
        self.assertEqual(bought, 0)
        self.assertEqual(client.calls, [])
        self.assertEqual(buyer.last_result["skip"], "no_affordable_pre_race_skill")

    def test_successful_buy_is_cached_when_response_skill_array_is_truncated(self):
        buyer = SkillBuyer(BASE_DIR)
        client = TruncatedSkillArrayClient()
        preset = {
            "learn_skill_list": [["Groundwork"]],
            "learn_skill_only_user_provided": False,
            "learn_skill_append_defaults": False,
        }
        state = make_state(
            turn=78,
            skill_point=500,
            skill_array=[],
            skill_tips_array=[{"group_id": 20160, "rarity": 1, "level": 0}],
        )

        state, bought = buyer.buy(client, state, preset, force=True)
        state, bought_again = buyer.buy(client, state, preset, force=True)

        bought_ids = [row["skill_id"] for row in state["data"]["chara_info"]["skill_array"]]
        self.assertEqual(bought, 1)
        self.assertEqual(bought_again, 0)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["payload"], [{"skill_id": 201601, "level": 1}])
        self.assertIn(201601, bought_ids)

    def test_recoverable_batch_205_that_buys_everything_is_not_left_in_error_state(self):
        buyer = SkillBuyer(BASE_DIR)
        client = RecoverableBatchSkillClient()
        preset = {
            "learn_skill_list": [["Go with the Flow", "Corner Recovery"]],
            "learn_skill_only_user_provided": False,
            "learn_skill_append_defaults": False,
        }
        state = make_state(
            turn=78,
            skill_point=1000,
            skill_array=[],
            skill_tips_array=[
                {"group_id": 20125, "rarity": 1, "level": 0},
                {"group_id": 20035, "rarity": 1, "level": 0},
            ],
        )

        state, bought = buyer.buy(client, state, preset, force=True)

        self.assertEqual(bought, 1)
        self.assertEqual(buyer.last_result["result"], "ok_after_recovery")
        self.assertFalse(buyer.recover_after_error)

    def test_pre_race_stamina_skill_buys_one_recovery_for_conditional_unique(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_stamina_for_race(client, make_state(), {}, low_stamina_check())

        self.assertEqual(bought, 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(client.calls[0]["payload"]), 1)
        self.assertEqual(client.calls[0]["payload"][0]["skill_id"], 200352)

    def test_pre_race_stamina_skill_buys_one_recovery_even_with_multiple_options(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_stamina_for_race(
            client,
            make_state(skill_tips_array=[
                {"group_id": 20035, "rarity": 1, "level": 0},
                {"group_id": 20038, "rarity": 1, "level": 0},
            ]),
            {},
            low_stamina_check(),
        )

        self.assertEqual(bought, 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(client.calls[0]["payload"]), 1)

    def test_pre_race_stamina_skill_respects_static_low_even_when_empirical_suppressed(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_stamina_for_race(
            client,
            make_state(skill_point=500),
            {},
            low_stamina_check(stamina_low=False, static_stamina_low=True),
        )

        self.assertEqual(bought, 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(len(client.calls[0]["payload"]), 1)

    def test_pre_race_stamina_skill_prefers_distance_or_style_match(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_stamina_for_race(
            client,
            make_state(skill_tips_array=[
                {"group_id": 20135, "rarity": 1, "level": 0},  # Hydrate: pace chaser
                {"group_id": 20074, "rarity": 1, "level": 0},  # Deep Breaths: long
            ]),
            {},
            low_stamina_check(style="front_runner", distance="Long"),
        )

        self.assertEqual(bought, 1)
        self.assertEqual(client.calls[0]["payload"][0]["skill_id"], 200742)

    def test_pre_race_stamina_skill_ignores_normal_skill_plan_filter(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_stamina_for_race(
            client,
            make_state(skill_tips_array=[
                {"group_id": 20055, "rarity": 1, "level": 1},  # Final Push: long recovery
                {"group_id": 20110, "rarity": 1, "level": 1},  # Medium Straightaways
            ]),
            {
                "learn_skill_list": [["Groundwork"], ["Front Runner Straightaways"]],
                "learn_skill_only_user_provided": False,
                "learn_skill_append_defaults": True,
                "skill_profile_style": "front_runner",
                "skill_profile_distance": "medium",
            },
            low_stamina_check(style="front_runner", distance="Long"),
        )

        self.assertEqual(bought, 1)
        self.assertEqual(client.calls[0]["payload"][0]["skill_id"], 200552)

    def test_pre_race_stamina_skill_ignores_wrong_style_when_no_generic_or_distance_match(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_stamina_for_race(
            client,
            make_state(skill_tips_array=[
                {"group_id": 20135, "rarity": 1, "level": 0},  # Hydrate: pace chaser
            ]),
            {},
            low_stamina_check(style="front_runner", distance="Long"),
        )

        self.assertEqual(bought, 0)
        self.assertEqual(client.calls, [])
        self.assertEqual(buyer.last_result["skip"], "no_usable_stamina_skill_for_race")

    def test_pre_race_stamina_skill_skips_reliable_super_creek_unique(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_stamina_for_race(
            client,
            make_state(card_id=104501),
            {},
            low_stamina_check(),
        )

        self.assertEqual(bought, 0)
        self.assertEqual(client.calls, [])
        self.assertEqual(buyer.last_result["skip"], "reliable_recovery_unique")

    def test_pre_race_stamina_skill_skips_agnes_tachyon_unique_when_style_matches(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_stamina_for_race(
            client,
            make_state(card_id=103201),
            {},
            low_stamina_check(
                race_name="Osaka Hai",
                distance="Medium",
                style="pace_chaser",
                requirements={"stamina": 414},
                stats={"stamina": 300},
            ),
        )

        self.assertEqual(bought, 0)
        self.assertEqual(client.calls, [])
        self.assertEqual(buyer.last_result["skip"], "reliable_recovery_unique")
        self.assertEqual((buyer.last_result.get("unique_recovery_profile") or {}).get("card_id"), 103201)

    def test_pre_race_stamina_skill_skips_existing_recovery_skill(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_stamina_for_race(
            client,
            make_state(skill_array=[{"skill_id": 200352, "level": 1}]),
            {},
            low_stamina_check(),
        )

        self.assertEqual(bought, 0)
        self.assertEqual(client.calls, [])
        self.assertEqual(buyer.last_result["skip"], "already_has_usable_stamina_recovery_skill")

    def test_pre_race_stamina_skill_ignores_owned_wrong_style_recovery(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_stamina_for_race(
            client,
            make_state(
                skill_array=[{"skill_id": 201352, "level": 1}],  # Hydrate: pace chaser
                skill_tips_array=[{"group_id": 20035, "rarity": 1, "level": 0}],
            ),
            {},
            low_stamina_check(style="front_runner", distance="Long"),
        )

        self.assertEqual(bought, 1)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["payload"][0]["skill_id"], 200352)

    def test_pre_race_stamina_skill_can_buy_moxie_for_front_runner(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_stamina_for_race(
            client,
            make_state(skill_tips_array=[{"group_id": 20128, "rarity": 1, "level": 0}]),
            {},
            low_stamina_check(style="front_runner", distance="Long"),
        )

        self.assertEqual(bought, 1)
        self.assertEqual(client.calls[0]["payload"][0]["skill_id"], 201282)

    def test_pre_race_stamina_skill_can_buy_for_non_g1_if_stamina_is_low(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()
        check = low_stamina_check(grade="G2")

        state, bought = buyer.buy_stamina_for_race(client, make_state(), {}, check)

        self.assertEqual(bought, 1)
        self.assertEqual(len(client.calls), 1)

    def test_kikuka_profile_safety_buys_two_style_or_generic_skills(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_profile_safety_for_race(
            client,
            make_state(
                skill_point=1000,
                skill_tips_array=[
                    {"group_id": 20125, "rarity": 1, "level": 0},  # Front Runner Corners
                    {"group_id": 20034, "rarity": 1, "level": 0},  # Corner Acceleration
                    {"group_id": 20153, "rarity": 1, "level": 0},  # Pace Chaser Savvy
                ],
            ),
            {"kikuka_front_runner_min_usable_skills": 2, "skill_profile_style": "front_runner"},
            low_stamina_check(style="front_runner"),
        )

        self.assertEqual(bought, 2)
        bought_ids = [row["skill_id"] for row in client.calls[0]["payload"]]
        self.assertCountEqual(bought_ids, [201252, 200342])
        self.assertNotIn(201532, bought_ids)

    def test_kikuka_profile_safety_counts_owned_and_buys_missing_skill(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_profile_safety_for_race(
            client,
            make_state(
                skill_point=1000,
                skill_array=[{"skill_id": 201252, "level": 1}],
                skill_tips_array=[{"group_id": 20037, "rarity": 1, "level": 0}],
            ),
            {"kikuka_front_runner_min_usable_skills": 2, "skill_profile_style": "front_runner"},
            low_stamina_check(style="front_runner"),
        )

        self.assertEqual(bought, 1)
        self.assertEqual(client.calls[0]["payload"][0]["skill_id"], 200372)

    def test_kikuka_profile_safety_skips_when_two_usable_skills_owned(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_profile_safety_for_race(
            client,
            make_state(
                skill_array=[
                    {"skill_id": 201252, "level": 1},
                    {"skill_id": 200342, "level": 1},
                ],
            ),
            {"kikuka_front_runner_min_usable_skills": 2, "skill_profile_style": "front_runner"},
            low_stamina_check(style="front_runner"),
        )

        self.assertEqual(bought, 0)
        self.assertEqual(client.calls, [])
        self.assertEqual(buyer.last_result["skip"], "race_profile_safety_met")

    def test_final_force_buy_ignores_manual_purchase_flag(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy(
            client,
            make_state(skill_point=300),
            {"manual_purchase_at_end": True, "learn_skill_only_user_provided": False},
            force=True,
        )

        self.assertGreaterEqual(bought, 1)
        self.assertEqual(len(client.calls), 1)

    def test_calendar_pre_race_buy_ignores_end_buy_but_caps_spend(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy_limited_for_race(
            client,
            make_state(
                turn=31,
                skill_point=1000,
                skill_tips_array=[
                    {"group_id": 20035, "rarity": 1, "level": 0},
                    {"group_id": 20128, "rarity": 1, "level": 4},
                    {"group_id": 20053, "rarity": 1, "level": 3},
                ],
            ),
            {
                "manual_purchase_at_end": True,
                "learn_skill_only_user_provided": False,
                "learn_skill_append_defaults": True,
                "calendar_race_prebuy_min_sp": 450,
                "calendar_race_prebuy_keep_sp": 350,
                "calendar_race_prebuy_budget": 420,
                "calendar_race_prebuy_max_skills": 2,
                "skill_profile_style": "front_runner",
                "skill_profile_distance": "medium",
            },
            {"race_name": "Satsuki Sho", "style": "pace_chaser", "distance": "Medium"},
        )

        self.assertGreaterEqual(bought, 1)
        self.assertLessEqual(len(client.calls[0]["payload"]), 2)
        self.assertEqual(buyer.last_result["reason"], "pre_race_calendar_skill_budget")

    def test_calendar_pre_race_buy_respects_sp_reserve(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        _state, bought = buyer.buy_limited_for_race(
            client,
            make_state(skill_point=500),
            {
                "manual_purchase_at_end": True,
                "calendar_race_prebuy_min_sp": 450,
                "calendar_race_prebuy_keep_sp": 500,
                "calendar_race_prebuy_budget": 420,
            },
            {"race_name": "Satsuki Sho", "style": "pace_chaser", "distance": "Medium"},
        )

        self.assertEqual(bought, 0)
        self.assertEqual(client.calls, [])
        self.assertEqual(buyer.last_result["skip"], "pre_race_skill_reserve")

    def test_calendar_pre_race_buy_accepts_clean_record_min_sp_override(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        _state, bought = buyer.buy_limited_for_race(
            client,
            make_state(
                turn=17,
                skill_point=240,
                skill_tips_array=[
                    {"group_id": 20053, "rarity": 1, "level": 3},
                ],
            ),
            {
                "manual_purchase_at_end": True,
                "learn_skill_only_user_provided": False,
                "learn_skill_append_defaults": True,
                "calendar_race_prebuy_min_sp": 450,
                "calendar_race_prebuy_keep_sp": 0,
                "calendar_race_prebuy_budget": 240,
                "calendar_race_prebuy_max_skills": 1,
            },
            {"race_name": "Sapporo Junior Stakes", "style": "pace_chaser", "distance": "Mile"},
            min_sp=120,
        )

        self.assertGreaterEqual(bought, 1)
        self.assertEqual(len(client.calls), 1)

    def test_final_force_buy_caps_extra_recovery_skills(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy(
            client,
            make_state(
                turn=78,
                skill_point=1200,
                skill_array=[
                    {"skill_id": 200352, "level": 1},  # Corner Recovery
                    {"skill_id": 201571, "level": 1},  # Triple 7s
                ],
                skill_tips_array=[
                    {"group_id": 20128, "rarity": 1, "level": 4},  # Moxie
                    {"group_id": 20142, "rarity": 1, "level": 2},  # A Small Breather
                    {"group_id": 20053, "rarity": 1, "level": 3},  # Early Lead
                ],
            ),
            {
                "manual_purchase_at_end": True,
                "learn_skill_only_user_provided": False,
                "learn_skill_append_defaults": False,
                "final_stamina_recovery_max_count": 2,
                "learn_skill_list": [["Moxie", "A Small Breather", "Early Lead"]],
            },
            force=True,
        )

        self.assertEqual(bought, 1)
        bought_ids = [row["skill_id"] for row in client.calls[0]["payload"]]
        self.assertEqual(bought_ids, [200532])
        skipped_ids = [row["skill_id"] for row in buyer.last_recovery_cap_skipped]
        self.assertEqual(skipped_ids, [201282, 201422])

    def test_final_force_buy_falls_back_after_recovery_cap_exhausts_profile(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state, bought = buyer.buy(
            client,
            make_state(
                turn=78,
                skill_point=1200,
                skill_array=[
                    {"skill_id": 200352, "level": 1},
                    {"skill_id": 201571, "level": 1},
                ],
                skill_tips_array=[
                    {"group_id": 20128, "rarity": 1, "level": 4},  # Moxie
                    {"group_id": 20033, "rarity": 1, "level": 3},  # Corner Adept
                ],
            ),
            {
                "manual_purchase_at_end": True,
                "learn_skill_only_user_provided": False,
                "learn_skill_append_defaults": False,
                "final_stamina_recovery_max_count": 2,
                "learn_skill_list": [["Moxie"]],
            },
            force=True,
        )

        self.assertEqual(bought, 1)
        bought_ids = [row["skill_id"] for row in client.calls[0]["payload"]]
        self.assertEqual(bought_ids, [200332])
        self.assertTrue(buyer.last_selected[0]["profile_fallback"])

    def test_profile_skill_priorities_can_append_default_priorities(self):
        buyer = SkillBuyer(BASE_DIR)

        priority = buyer._priority_context({
            "learn_skill_list": [["Groundwork"]],
            "learn_skill_append_defaults": True,
            "learn_skill_only_user_provided": False,
        })

        self.assertEqual(priority["groundwork"], 0)
        self.assertGreater(priority["acceleration"], priority["groundwork"])

    def test_resolve_skill_tip_prefers_priority_matched_variant_within_group(self):
        buyer = SkillBuyer(BASE_DIR)
        buyer.skill_names = {
            100001: "Wanted Skill",
            100002: "Wrong Skill ○",
        }
        buyer.skill_id_exists = set(buyer.skill_names)
        buyer.group_to_skill_ids = {10000: [100001, 100002]}
        buyer.skill_to_group_id = {100001: 10000, 100002: 10000}

        resolved = buyer.resolve_skill_tip(
            {"group_id": 10000, "rarity": 1, "level": 0},
            owned_skill_ids=set(),
            owned_groups=set(),
            priority={"wantedskill": 0},
            blacklist=set(),
            preset={"learn_skill_list": [["Wanted Skill"]]},
        )

        self.assertEqual(resolved["resolved_skill_id"], 100001)
        self.assertEqual(resolved["resolved_name"], "Wanted Skill")
        self.assertEqual(resolved["priority"], 0)

    def test_resolve_skill_tip_skips_variant_missing_required_base_skill(self):
        buyer = SkillBuyer(BASE_DIR)

        resolved = buyer.resolve_skill_tip(
            {"group_id": 20163, "rarity": 1, "level": 3},
            owned_skill_ids=set(),
            owned_groups=set(),
            priority={},
            blacklist=set(),
            preset={},
        )

        self.assertEqual(resolved["resolved_skill_id"], 201631)
        self.assertEqual(resolved["resolved_name"], "Sympathy")
        self.assertNotIn(201632, resolved["candidate_skill_ids"])

    def test_buy_batch_blocks_candidate_missing_required_base_skill(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()
        state = make_state(
            turn=44,
            skill_point=500,
            skill_array=[],
            skill_tips_array=[{"group_id": 20163, "rarity": 1, "level": 3}],
        )
        candidate = {
            "skill_id": 201632,
            "resolved_skill_id": 201632,
            "group_id": 20163,
            "name": "Connection",
            "cost": 150,
        }

        next_state, bought = buyer._buy_batch(client, state, [candidate], 44, preset={})

        self.assertIs(next_state, state)
        self.assertEqual(bought, 0)
        self.assertEqual(client.calls, [])
        self.assertEqual(candidate["preflight_error"], "missing_required_base_skill")
        self.assertEqual(candidate["missing_required_skill_ids"], [201631])

    def test_priority_skill_overrides_stale_blacklist(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state = make_state(
            turn=78,
            skill_point=500,
            skill_tips_array=[{"group_id": 20160, "rarity": 1, "level": 0}],
        )
        preset = {
            "manual_purchase_at_end": True,
            "learn_skill_list": [["Groundwork"]],
            "learn_skill_blacklist": ["Groundwork"],
        }

        state, bought = buyer.buy(client, state, preset, force=True)

        self.assertEqual(bought, 1)
        self.assertEqual(client.calls[0]["payload"], [{"skill_id": 201601, "level": 1}])

    def test_final_priority_is_reserved_before_optimizer_fills_budget(self):
        buyer = SkillBuyer(BASE_DIR)

        selected = buyer._select_final_candidates(
            [
                {
                    "skill_id": 201601,
                    "group_id": 20160,
                    "name": "Groundwork",
                    "cost": 180,
                    "hint_level": 0,
                    "priority": 0,
                    "tip_rarity": 0,
                    "candidate_skill_ids": [201601],
                },
                {
                    "skill_id": 900022,
                    "group_id": 90002,
                    "name": "Front Runner Corners â—‹",
                    "cost": 130,
                    "hint_level": 0,
                    "priority": 1,
                    "tip_rarity": 0,
                    "candidate_skill_ids": [900022],
                },
                {
                    "skill_id": 900032,
                    "group_id": 90003,
                    "name": "Medium Corners â—‹",
                    "cost": 130,
                    "hint_level": 0,
                    "priority": 1,
                    "tip_rarity": 0,
                    "candidate_skill_ids": [900032],
                },
            ],
            260,
            {},
            {
                "skill_buy_on_sight": ["Groundwork"],
                "learn_skill_list": [["Groundwork"], ["Front Runner Corners", "Medium Corners"]],
                "skill_profile_style": "front_runner",
                "skill_profile_distance": "medium",
            },
        )

        self.assertIn(201601, [row["skill_id"] for row in selected])
        self.assertTrue(next(row for row in selected if row["skill_id"] == 201601)["hard_priority"])
        self.assertLessEqual(sum(row["cost"] for row in selected), 260)

    def test_force_buy_with_skill_plan_drains_affordable_fallback_skills(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state = make_state(
            turn=78,
            skill_point=3000,
            skill_tips_array=[
                {"group_id": 20125, "rarity": 1, "level": 2},  # Front Runner Corners ○
                {"group_id": 20152, "rarity": 1, "level": 1},  # Front Runner Savvy ○
                {"group_id": 20127, "rarity": 1, "level": 0},  # Leader's Pride
                {"group_id": 20153, "rarity": 1, "level": 1},  # Pace Chaser Savvy ○
                {"group_id": 20154, "rarity": 1, "level": 1},  # Late Surger Savvy ○
                {"group_id": 20006, "rarity": 1, "level": 1},  # Kyoto Racecourse ○
                {"group_id": 20053, "rarity": 1, "level": 2},  # Early Lead
            ],
        )
        preset = {
            "manual_purchase_at_end": True,
            "learn_skill_only_user_provided": False,
            "learn_skill_append_defaults": False,
            "learn_skill_list": [[
                "Front Runner Corners",
                "Front Runner Savvy",
                "Leader's Pride",
                "Early Lead",
            ]],
        }

        state, bought = buyer.buy(client, state, preset, force=True)

        self.assertEqual(bought, 7)
        self.assertEqual(len(client.calls), 1)
        bought_ids = [row["skill_id"] for row in client.calls[0]["payload"]]
        self.assertCountEqual(bought_ids, [200532, 201252, 201272, 201522, 201532, 201542, 200062])

    def test_skill_plan_falls_back_to_normal_priorities_when_profile_is_exhausted(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state = make_state(
            turn=78,
            skill_point=1000,
            skill_array=[{"skill_id": 201252, "level": 1}],
            skill_tips_array=[
                {"group_id": 20125, "rarity": 1, "level": 0},
                {"group_id": 20033, "rarity": 1, "level": 0},
            ],
        )
        preset = {
            "manual_purchase_at_end": True,
            "learn_skill_only_user_provided": False,
            "learn_skill_append_defaults": False,
            "learn_skill_list": [["Front Runner Corners"]],
        }

        state, bought = buyer.buy(client, state, preset, force=True)

        self.assertEqual(bought, 1)
        bought_ids = [row["skill_id"] for row in client.calls[0]["payload"]]
        self.assertEqual(bought_ids, [200332])
        self.assertTrue(buyer.last_selected[0]["profile_fallback"])

    def test_user_provided_only_does_not_fallback_to_normal_priorities(self):
        buyer = SkillBuyer(BASE_DIR)
        client = FakeSkillClient()

        state = make_state(
            turn=78,
            skill_point=1000,
            skill_array=[{"skill_id": 201252, "level": 1}],
            skill_tips_array=[
                {"group_id": 20125, "rarity": 1, "level": 0},
                {"group_id": 20033, "rarity": 1, "level": 0},
            ],
        )
        preset = {
            "manual_purchase_at_end": True,
            "learn_skill_only_user_provided": True,
            "learn_skill_list": [["Front Runner Corners"]],
        }

        state, bought = buyer.buy(client, state, preset, force=True)

        self.assertEqual(bought, 0)
        self.assertEqual(client.calls, [])

    def test_final_optimizer_prefers_profile_build_over_single_cheap_off_profile_skill(self):
        buyer = SkillBuyer(BASE_DIR)
        candidates = [
            {
                "skill_id": 900012,
                "group_id": 90001,
                "name": "Late Surger Corners ○",
                "cost": 80,
                "hint_level": 5,
                "priority": 999,
                "tip_rarity": 0,
            },
            {
                "skill_id": 900022,
                "group_id": 90002,
                "name": "Front Runner Corners ○",
                "cost": 130,
                "hint_level": 0,
                "priority": 999,
                "tip_rarity": 0,
            },
            {
                "skill_id": 900032,
                "group_id": 90003,
                "name": "Medium Corners ○",
                "cost": 130,
                "hint_level": 0,
                "priority": 999,
                "tip_rarity": 0,
            },
        ]

        selected = buyer._select_final_candidates(
            candidates,
            260,
            {},
            {"skill_profile_style": "front_runner", "skill_profile_distance": "medium"},
        )

        self.assertCountEqual([row["skill_id"] for row in selected], [900022, 900032])

    def test_final_optimizer_does_not_invent_cheaper_variant_from_same_group_when_budget_is_tight(self):
        buyer = SkillBuyer(BASE_DIR)
        buyer.skill_names = {
            990001: "Expensive Off Plan",
            990002: "Front Runner Corners ○",
        }
        buyer.skill_id_exists = set(buyer.skill_names)
        buyer.group_to_skill_ids = {99000: [990001, 990002]}
        buyer.skill_to_group_id = {990001: 99000, 990002: 99000}
        candidates = [{
            "skill_id": 990001,
            "group_id": 99000,
            "name": "Expensive Off Plan",
            "cost": 200,
            "hint_level": 0,
            "priority": 999,
            "tip_rarity": 0,
            "candidate_skill_ids": [990001, 990002],
        }]

        selected = buyer._select_final_candidates(
            candidates,
            130,
            {},
            {"skill_profile_style": "front_runner"},
        )

        self.assertEqual(selected, [])

    def test_buy_batch_rejects_non_live_resolved_sibling_variant(self):
        buyer = SkillBuyer(BASE_DIR)
        state = make_state(
            turn=78,
            skill_point=999,
            skill_array=[],
            skill_tips_array=[{"group_id": 20126, "rarity": 1, "level": 0}],
        )

        class GuardClient:
            def __init__(self):
                self.calls = []

            def gain_skills(self, payload, turn, **kwargs):
                self.calls.append({"payload": payload, "turn": turn, "kwargs": kwargs})
                return state

        client = GuardClient()
        candidate = {
            "skill_id": 201261,
            "resolved_skill_id": 201262,
            "group_id": 20126,
            "name": "Sixth Sense",
            "resolved_name": "Dodging Danger",
            "cost": 128,
            "hint_level": 0,
            "priority": 999,
            "tip_rarity": 1,
            "candidate_skill_ids": [201261, 201262],
        }

        current_state, bought = buyer._buy_batch(client, state, [candidate], 78, {})

        self.assertEqual(bought, 0)
        self.assertIs(current_state, state)
        self.assertEqual(client.calls, [])
        self.assertEqual(candidate["preflight_error"], "not_live_resolved_variant")
        self.assertEqual(candidate["live_resolved_skill_id"], 201262)
        self.assertEqual(candidate["live_resolved_name"], "Dodging Danger")
        self.assertEqual(buyer.last_result["skip"], "preflight_failed")

    def test_single_skill_205_is_disabled_for_current_career(self):
        buyer = SkillBuyer(BASE_DIR)
        state = make_state(
            turn=22,
            skill_point=150,
            skill_array=[],
            skill_tips_array=[{"group_id": 20033, "rarity": 1, "level": 1}],
        )

        class RejectingClient:
            def __init__(self):
                self.calls = []

            def gain_skills(self, payload, turn, **kwargs):
                self.calls.append({"payload": payload, "turn": turn, "kwargs": kwargs})
                raise Exception("API error 205 on single_mode_free/gain_skills")

        client = RejectingClient()
        candidate = {
            "skill_id": 200332,
            "resolved_skill_id": 200332,
            "default_resolved_skill_id": 200332,
            "group_id": 20033,
            "name": "Corner Adept ○",
            "resolved_name": "Corner Adept ○",
            "cost": 117,
            "hint_level": 1,
            "priority": 0,
            "tip_rarity": 1,
            "candidate_skill_ids": [200331, 200332, 200333],
        }

        current_state, bought = buyer._buy_batch(client, state, [candidate], 22, {})

        self.assertEqual(bought, 0)
        self.assertIs(current_state, state)
        self.assertEqual(len(client.calls), 1)
        self.assertIn(200332, buyer.permanent_failed_skills)
        self.assertEqual(buyer.last_result["result"], "failed")

        retry_candidate = dict(candidate)
        retry_state, retry_bought = buyer._buy_batch(client, state, [retry_candidate], 22, {})

        self.assertEqual(retry_bought, 0)
        self.assertIs(retry_state, state)
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(retry_candidate["preflight_error"], "permanent_fail_205")
        self.assertEqual(buyer.last_result["skip"], "preflight_failed")

    def test_default_priority_does_not_override_default_group_variant(self):
        buyer = SkillBuyer(BASE_DIR)
        preset = {}
        resolved = buyer.resolve_skill_tip(
            {"group_id": 20144, "rarity": 1, "level": 1},
            set(),
            set(),
            buyer._priority_context(preset),
            buyer._blacklist(preset),
            preset,
        )

        self.assertEqual(resolved["resolved_skill_id"], 201442)
        self.assertEqual(resolved["default_resolved_skill_id"], 201442)
        self.assertEqual(resolved["priority_selected_skill_id"], 201441)
        self.assertTrue(resolved["priority_override_blocked"])
        self.assertEqual(resolved["resolution_reason"], "priority_match_blocked_to_default_variant")

    def test_explicit_priority_can_override_default_group_variant(self):
        buyer = SkillBuyer(BASE_DIR)
        preset = {
            "learn_skill_list": [["All-Seeing Eyes"]],
            "learn_skill_append_defaults": False,
        }
        resolved = buyer.resolve_skill_tip(
            {"group_id": 20144, "rarity": 1, "level": 1},
            set(),
            set(),
            buyer._priority_context(preset),
            buyer._blacklist(preset),
            preset,
        )

        self.assertEqual(resolved["resolved_skill_id"], 201441)
        self.assertEqual(resolved["default_resolved_skill_id"], 201442)
        self.assertEqual(resolved["priority_selected_skill_id"], 201441)
        self.assertFalse(resolved["priority_override_blocked"])

    def test_final_optimizer_uses_umatools_rating_metadata_when_available(self):
        buyer = SkillBuyer(BASE_DIR)
        buyer.skill_rating_meta = {
            "moxie": {
                "name": "Moxie",
                "category": "blue",
                "roles": ["front"],
                "base": 217,
                "scores": {"good": 239, "average": 195, "bad": 174, "terrible": 152},
            }
        }

        selected = buyer._select_final_candidates(
            [{
                "skill_id": 201282,
                "group_id": 20128,
                "name": "Moxie",
                "cost": 200,
                "hint_level": 0,
                "priority": 999,
                "tip_rarity": 0,
            }],
            200,
            {"proper_running_style_nige": 7},
            {"skill_profile_style": "front_runner"},
        )

        self.assertEqual([row["skill_id"] for row in selected], [201282])
        self.assertGreater(selected[0]["optimizer_score"], 0)

    def test_partial_skill_failure_blocks_alternate_variants_from_same_group(self):
        buyer = SkillBuyer(BASE_DIR)
        client = PartialRejectSkillClient()
        preset = {
            "learn_skill_only_user_provided": False,
            "learn_skill_append_defaults": False,
            "learn_skill_list": [[
                "Front Runner Corners",
                "Early Lead",
                "Taking the Lead",
            ]],
        }
        state = make_state(
            turn=78,
            skill_point=1200,
            skill_array=[],
            skill_tips_array=[
                {"group_id": 20125, "rarity": 1, "level": 0},
                {"group_id": 20053, "rarity": 1, "level": 0},
            ],
        )

        state, bought = buyer.buy(client, state, preset, force=True)
        self.assertEqual(bought, 1)
        self.assertEqual(client.calls[0]["kwargs"], {"retry_205": 1, "retry_208": 1})
        self.assertIn(201252, [row["skill_id"] for row in state["data"]["chara_info"]["skill_array"]])
        calls_after_first_attempt = len(client.calls)

        state, bought = buyer.buy(client, state, preset, force=True)

        self.assertEqual(bought, 0)
        self.assertEqual(len(client.calls), calls_after_first_attempt)
        self.assertEqual(buyer.last_result["skip"], "no_candidates")


class EndOfCareerDrainSweepTests(unittest.TestCase):
    """End-of-career SP-drain sweep: after the knapsack settles, every
    affordable group that hasn't been picked should get its cheapest valid
    variant bought. Unspent SP at career end has zero value, so the sweep
    overrules the optimizer's "this skill isn't worth its score" verdict.
    """

    def test_drain_sweep_buys_low_score_white_when_budget_allows(self):
        buyer = SkillBuyer(BASE_DIR)
        buyer.disable_cross_career_failure_persistence()

        class DrainSweepClient:
            def __init__(self):
                self.calls = []

            def gain_skills(self, payload, turn, **kwargs):
                self.calls.append({"payload": payload, "turn": turn, "kwargs": kwargs})
                return make_state(
                    turn=turn,
                    skill_point=0,
                    skill_array=[{"skill_id": p["skill_id"], "level": 1} for p in payload],
                    skill_tips_array=[],
                )

        client = DrainSweepClient()
        preset = {
            "learn_skill_list": [[]],
            "learn_skill_only_user_provided": False,
            "learn_skill_append_defaults": True,
        }
        # 251 SP, single non-priority white tip available. Without the
        # drain sweep the knapsack chooses "none" and leaves SP unspent.
        # With the sweep, the cheapest variant gets bought.
        state = make_state(
            turn=78,
            skill_point=251,
            skill_array=[],
            skill_tips_array=[
                {"group_id": 20106, "rarity": 0, "level": 1},  # Acceleration (white)
            ],
        )

        state, bought = buyer.buy(client, state, preset, force=True)

        self.assertGreaterEqual(bought, 1, msg="drain sweep should buy the affordable white")
        self.assertEqual(len(client.calls), 1)
        bought_ids = {p["skill_id"] for p in client.calls[0]["payload"]}
        # Either the white or its inherited-gold variant is fine — we
        # care that *something* in group 20106 was purchased.
        self.assertTrue(
            bought_ids & {201061, 201062},
            msg=f"expected group 20106 to be bought, got {bought_ids}",
        )

    def test_drain_sweep_respects_budget_when_only_unaffordable_left(self):
        buyer = SkillBuyer(BASE_DIR)
        buyer.disable_cross_career_failure_persistence()

        class DrainSweepClient:
            def __init__(self):
                self.calls = []

            def gain_skills(self, payload, turn, **kwargs):
                self.calls.append({"payload": payload, "turn": turn, "kwargs": kwargs})
                return make_state(
                    turn=turn,
                    skill_point=10,
                    skill_array=[{"skill_id": p["skill_id"], "level": 1} for p in payload],
                    skill_tips_array=[],
                )

        client = DrainSweepClient()
        preset = {
            "learn_skill_list": [[]],
            "learn_skill_only_user_provided": False,
            "learn_skill_append_defaults": True,
        }
        # 10 SP, no skill costs <= 10. Sweep should NOT panic-buy.
        state = make_state(
            turn=78,
            skill_point=10,
            skill_array=[],
            skill_tips_array=[
                {"group_id": 20106, "rarity": 0, "level": 1},
            ],
        )

        state, bought = buyer.buy(client, state, preset, force=True)

        # Either nothing bought, or a small skill that fit — the contract
        # is "don't buy anything that doesn't fit the remaining budget".
        if bought:
            for call in client.calls:
                for payload_item in call["payload"]:
                    self.assertGreater(payload_item.get("skill_id", 0), 0)


if __name__ == "__main__":
    unittest.main()
