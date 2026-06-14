import unittest
import time
from unittest.mock import patch

import main
from uma_api.client import ApiCallError, UmaClient


def make_start_request(**overrides):
    data = {
        "card_id": 100101,
        "support_card_ids": [30101, 30102, 30103, 30104, 30107],
        "friend_viewer_id": 123456789,
        "friend_card_id": 30106,
        "parent_id_1": 9001,
        "parent_id_2": 9002,
        "scenario_id": 4,
        "deck_id": 1,
        "use_tp": 30,
        "allow_recover_tp": 0,
    }
    data.update(overrides)
    return main.StartCareerRequest(**data)


class FakeCareerClient:
    def __init__(self):
        self.calls = []

    def pre_single_mode(self, exclude_viewer_ids=None):
        self.calls.append({
            "endpoint": "pre_single_mode/index",
            "exclude_viewer_ids": exclude_viewer_ids or [],
        })
        return {"data": {}}

    def use_recovery_item(self, item_id=0, current_num=0):
        self.calls.append({
            "endpoint": "item/use_recovery_item",
            "item_id": item_id,
            "current_num": current_num,
        })
        tp_info = {"current_tp": 30, "max_tp": 100, "max_recovery_time": 0}
        main.active_start_state["tp_info"] = tp_info
        return {"data": {"tp_info": tp_info}}

    def recover_trainer_point(self, count=1, client_own_num=0):
        self.calls.append({
            "endpoint": "user/recovery_trainer_point",
            "count": count,
            "client_own_num": client_own_num,
        })
        tp_info = {"current_tp": 30, "max_tp": 100, "max_recovery_time": 0}
        main.active_start_state["tp_info"] = tp_info
        return {"data": {"tp_info": tp_info}}

    def start_career(self, **kwargs):
        self.calls.append(kwargs)
        return {"data": {"chara_info": {"card_id": kwargs["card_id"], "turn": 1}}}


def make_live_start_load_data(deck_ids=None):
    deck_ids = deck_ids if deck_ids is not None else [30101, 30102, 30103, 30104, 30107]
    return {
        "tp_info": {"current_tp": 30, "max_tp": 100, "max_recovery_time": 0},
        "coin_info": {"fcoin": 100, "coin": 0},
        "item_list": [{"item_id": 59, "number": 10}, {"item_id": 32, "number": 20}, {"item_id": 75, "number": 20}],
        "card_list": [{"card_id": 100101}],
        "support_card_list": [{"support_card_id": sid} for sid in [30101, 30102, 30103, 30104, 30107]],
        "support_card_deck_array": [
            {"deck_id": 1, "name": "Proof Deck", "support_card_id_array": deck_ids}
        ],
        "trained_chara": [
            {
                "trained_chara_id": 9001,
                "card_id": 100201,
                "rank": 10,
                "rank_score": 1000,
                "factor_id_array": [],
                "win_saddle_id_array": [],
                "succession_chara_array": [],
            },
            {
                "trained_chara_id": 9002,
                "card_id": 100301,
                "rank": 10,
                "rank_score": 1000,
                "factor_id_array": [],
                "win_saddle_id_array": [],
                "succession_chara_array": [],
            },
        ],
    }


def make_showtime_load_data(item_num=0, open_difficulty_index=4, story_event_id=1015):
    data = make_live_start_load_data()
    data.update({
        "story_event_id": story_event_id,
        "single_mode_difficulty_info_array": [
            {
                "difficulty_id": 1003,
                "open_difficulty_index": open_difficulty_index,
                "item_num": item_num,
                "box_id": 4,
                "box_item_num": 52,
            }
        ],
    })
    return data


class TpRecoverySmokeTests(unittest.TestCase):
    def setUp(self):
        self.saved_state = {
            "active_client": main.active_client,
            "active_account": main.active_account,
            "active_dashboard_data": main.active_dashboard_data,
            "active_start_state": dict(main.active_start_state),
            "active_start_debug": dict(main.active_start_debug),
            "active_parent_cards": dict(main.active_parent_cards),
            "active_parent_rank_points": dict(main.active_parent_rank_points),
        }
        main.active_account = None
        main.active_dashboard_data = None
        main.active_start_state = {}
        main.active_start_debug = {}
        main.active_parent_cards = {}
        main.active_parent_rank_points = {}

    def tearDown(self):
        main.active_client = self.saved_state["active_client"]
        main.active_account = self.saved_state["active_account"]
        main.active_dashboard_data = self.saved_state["active_dashboard_data"]
        main.active_start_state = self.saved_state["active_start_state"]
        main.active_start_debug = self.saved_state["active_start_debug"]
        main.active_parent_cards = self.saved_state["active_parent_cards"]
        main.active_parent_rank_points = self.saved_state["active_parent_rank_points"]

    def set_low_tp_start_state(self):
        main.active_start_state = {
            "tp_info": {"current_tp": 0, "max_tp": 100, "max_recovery_time": 0},
            "coin_info": {"fcoin": 100, "coin": 0},
            "item_list": [{"item_id": 59, "number": 12345}, {"item_id": 32, "number": 20}],
            "current_money": 12345,
            "succession_rank_point": 0,
        }

    def test_start_blocks_low_tp_without_recovery_mode(self):
        client = FakeCareerClient()
        main.active_client = client
        self.set_low_tp_start_state()

        result = main.start_career_from_request(make_start_request())

        self.assertFalse(result["success"])
        self.assertIn("Not enough TP", result["detail"])
        self.assertEqual(client.calls, [])

    def test_start_preflight_blocks_missing_required_parent_before_api(self):
        client = FakeCareerClient()
        main.active_client = client
        self.set_low_tp_start_state()
        main.active_start_state["tp_info"]["current_tp"] = 30

        result = main.start_career_from_request(make_start_request(parent_id_1=0, parent_id_2=0))

        self.assertFalse(result["success"])
        self.assertIn("Parent 1 is required", result["detail"])
        self.assertIn("Parent 2 is required", result["detail"])
        self.assertEqual(client.calls, [])

    def test_start_allows_low_tp_with_carats_recovery_mode(self):
        client = FakeCareerClient()
        main.active_client = client
        self.set_low_tp_start_state()

        result = main.start_career_from_request(make_start_request(allow_recover_tp=1))

        self.assertTrue(result["success"])
        self.assertEqual(client.calls[0]["endpoint"], "user/recovery_trainer_point")
        self.assertEqual(client.calls[0]["count"], 1)
        self.assertEqual(client.calls[0]["client_own_num"], 100)
        self.assertEqual(client.calls[1]["allow_recover_tp"], 0)
        self.assertEqual(client.calls[1]["tp_info"]["current_tp"], 30)

    def test_carats_recovery_uses_total_held_carats_not_free_only(self):
        client = FakeCareerClient()
        main.active_client = client
        self.set_low_tp_start_state()
        main.active_start_state["coin_info"] = {"fcoin": 5, "coin": 5}

        result = main.start_career_from_request(make_start_request(allow_recover_tp=1))

        self.assertTrue(result["success"])
        self.assertEqual(client.calls[0]["endpoint"], "user/recovery_trainer_point")
        self.assertEqual(client.calls[0]["client_own_num"], 10)
        self.assertEqual(main.active_start_debug["tp_recovery_attempt"]["attempts"][0]["client_own_num"], 10)

    def test_observed_carats_recovery_response_updates_tp_and_carats(self):
        max_recovery_time = int(time.time()) + (52 * main.TP_RECOVERY_SECONDS_PER_POINT)
        main.active_start_state = {
            "tp_info": {"current_tp": 18, "max_tp": 100, "max_recovery_time": 0},
            "coin_info": {"fcoin": 2255, "coin": 40},
        }
        response = {
            "response_code": 1,
            "data": {
                "coin_info": {"fcoin": 2245, "coin": 40},
                "tp_info": {"current_tp": 48, "max_tp": 100, "max_recovery_time": max_recovery_time},
            },
        }

        main.update_start_state_from_api_response(response)

        self.assertEqual(main.current_start_tp(), 48)
        self.assertEqual(main.tp_recovery_resource_status(1)["carats_total"], 2285)
        self.assertEqual(main.tp_recovery_resource_status(1)["carats_client_own_num"], 2285)

    def test_tp_timer_derives_live_current_tp_and_next_tick(self):
        now = 1000
        max_recovery_time = now + (52 * main.TP_RECOVERY_SECONDS_PER_POINT)

        initial = main.derive_tp_info(
            {"current_tp": 48, "max_tp": 100, "max_recovery_time": max_recovery_time},
            now=now,
        )
        after_one_tick = main.derive_tp_info(
            {"current_tp": 48, "max_tp": 100, "max_recovery_time": max_recovery_time},
            now=now + main.TP_RECOVERY_SECONDS_PER_POINT + 1,
        )

        self.assertEqual(initial["current_tp"], 48)
        self.assertEqual(initial["seconds_to_next"], main.TP_RECOVERY_SECONDS_PER_POINT)
        self.assertEqual(after_one_tick["current_tp"], 49)
        self.assertEqual(after_one_tick["seconds_to_next"], main.TP_RECOVERY_SECONDS_PER_POINT - 1)

    def test_resource_response_sync_updates_account_without_clearing_career(self):
        main.active_start_state = {
            "tp_info": {"current_tp": 48, "max_tp": 100, "max_recovery_time": 0},
            "coin_info": {"fcoin": 2235, "coin": 40},
            "item_list": [],
        }
        main.active_account = {
            "tp": {"current": 48, "max": 100},
            "carrots": {"free": 2235, "paid": 40, "total": 2275},
            "career": {"active": True, "turn": 14, "deck_id": 7},
        }
        main.active_dashboard_data = {"account": dict(main.active_account)}

        account = main.sync_game_data_from_api_response("item/exchange", {
            "response_code": 1,
            "data": {
                "coin_info": {"fcoin": 2225, "coin": 40},
                "reward_summary_info": {"add_item_list": [{"item_id": 95, "number": 1}]},
            },
        })

        self.assertEqual(account["carrots"]["total"], 2265)
        self.assertEqual(main.get_item_count(main.active_start_state["item_list"], 95), 1)
        self.assertEqual(account["career"]["turn"], 14)
        self.assertEqual(main.active_dashboard_data["account"]["carrots"]["free"], 2225)

    def test_career_response_sync_updates_turn_without_losing_resources(self):
        main.active_start_state = {
            "tp_info": {"current_tp": 72, "max_tp": 100, "max_recovery_time": 0},
            "coin_info": {"fcoin": 1500, "coin": 40},
            "item_list": [{"item_id": 59, "number": 12345}],
            "current_money": 12345,
        }
        main.active_account = {
            "tp": {"current": 72, "max": 100},
            "carrots": {"free": 1500, "paid": 40, "total": 1540},
            "gold": 12345,
            "career": {"active": True, "turn": 20, "deck_id": 9},
        }

        account = main.sync_game_data_from_api_response("single_mode_free/check_event", {
            "response_code": 1,
            "data": {
                "chara_info": {
                    "card_id": 100101,
                    "turn": 21,
                    "scenario_id": 4,
                    "fans": 5000,
                    "vital": 50,
                    "max_vital": 100,
                    "support_card_array": [],
                }
            },
        })

        self.assertEqual(account["career"]["turn"], 21)
        self.assertEqual(account["career"]["deck_id"], 9)
        self.assertEqual(account["carrots"]["total"], 1540)
        self.assertEqual(account["gold"], 12345)

    def test_start_allows_low_tp_with_toughness_recovery_mode(self):
        client = FakeCareerClient()
        main.active_client = client
        self.set_low_tp_start_state()

        result = main.start_career_from_request(make_start_request(allow_recover_tp=2))

        self.assertTrue(result["success"])
        self.assertEqual(client.calls[0]["endpoint"], "item/use_recovery_item")
        self.assertEqual(client.calls[0]["item_id"], 32)
        self.assertEqual(client.calls[0]["current_num"], 20)
        self.assertEqual(client.calls[1]["allow_recover_tp"], 0)
        self.assertEqual(client.calls[1]["tp_info"]["current_tp"], 30)

    def test_start_both_recovery_uses_toughness_first(self):
        client = FakeCareerClient()
        main.active_client = client
        self.set_low_tp_start_state()

        result = main.start_career_from_request(make_start_request(allow_recover_tp=3))

        self.assertTrue(result["success"])
        self.assertEqual(client.calls[0]["endpoint"], "item/use_recovery_item")
        self.assertEqual(client.calls[1]["allow_recover_tp"], 0)
        self.assertEqual(main.active_start_debug["tp_recovery_attempt"]["used"], "toughness")

    def test_start_clamps_oversize_mode_to_both(self):
        client = FakeCareerClient()
        main.active_client = client
        self.set_low_tp_start_state()

        result = main.start_career_from_request(make_start_request(allow_recover_tp=99))

        self.assertTrue(result["success"])
        self.assertEqual(client.calls[0]["endpoint"], "item/use_recovery_item")
        self.assertEqual(client.calls[1]["allow_recover_tp"], 0)

    def test_start_blocks_low_tp_when_no_recovery_resources(self):
        client = FakeCareerClient()
        main.active_client = client
        main.active_start_state = {
            "tp_info": {"current_tp": 0, "max_tp": 100, "max_recovery_time": 0},
            "coin_info": {"fcoin": 0, "coin": 0},
            "item_list": [{"item_id": 59, "number": 12345}],
            "current_money": 12345,
            "succession_rank_point": 0,
        }

        result = main.start_career_from_request(make_start_request(allow_recover_tp=3))

        self.assertFalse(result["success"])
        self.assertIn("has no usable resources", result["detail"])
        self.assertEqual(client.calls, [])

    def test_start_both_falls_back_to_carats_when_toughness_fails(self):
        class ToughnessFailsClient(FakeCareerClient):
            def use_recovery_item(self, item_id=0, current_num=0):
                self.calls.append({
                    "endpoint": "item/use_recovery_item",
                    "item_id": item_id,
                    "current_num": current_num,
                })
                raise Exception("API error 102 on item/use_recovery_item")

        client = ToughnessFailsClient()
        main.active_client = client
        self.set_low_tp_start_state()

        result = main.start_career_from_request(make_start_request(allow_recover_tp=3))

        self.assertTrue(result["success"])
        self.assertEqual(client.calls[0]["endpoint"], "item/use_recovery_item")
        self.assertEqual(client.calls[1]["endpoint"], "user/recovery_trainer_point")
        self.assertEqual(client.calls[2]["allow_recover_tp"], 0)
        self.assertEqual(main.active_start_debug["tp_recovery_attempt"]["used"], "carats")

    def test_start_state_does_not_treat_g1_sashes_as_succession_rank_points(self):
        main.active_start_state = {"succession_rank_point": 999}

        main.update_start_state({
            "tp_info": {"current_tp": 30, "max_tp": 100, "max_recovery_time": 0},
            "item_list": [{"item_id": 59, "number": 12345}, {"item_id": 75, "number": 51}],
        })

        self.assertNotIn("succession_rank_point", main.active_start_state)

    def test_start_preflight_blocks_when_server_already_has_active_career(self):
        class ActiveCareerClient(FakeCareerClient):
            def call(self, endpoint, args=None):
                self.calls.append({"endpoint": endpoint, "args": args})
                return {
                    "data": {
                        "tp_info": {"current_tp": 30, "max_tp": 100, "max_recovery_time": 0},
                        "item_list": [{"item_id": 59, "number": 10}, {"item_id": 75, "number": 20}],
                        "single_mode_chara_light": {
                            "card_id": 100101,
                            "turn": 1,
                            "scenario_id": 4,
                            "support_card_array": [],
                        },
                        "card_list": [{"card_id": 100101}],
                        "support_card_list": [],
                        "support_card_deck_array": [],
                        "trained_chara": [],
                    }
                }

            def load_career(self):
                return {
                    "data": {
                        "chara_info": {
                            "card_id": 100101,
                            "turn": 1,
                            "scenario_id": 4,
                            "support_card_array": [],
                        }
                    }
                }

        client = ActiveCareerClient()
        main.active_client = client
        self.set_low_tp_start_state()

        result = main.start_career_from_request(make_start_request())

        self.assertFalse(result["success"])
        self.assertIn("active career already exists", result["detail"])
        self.assertFalse(any("card_id" in call for call in client.calls))

    def test_start_preflight_blocks_when_only_direct_career_probe_finds_active_career(self):
        class HiddenActiveCareerClient(FakeCareerClient):
            def call(self, endpoint, args=None):
                self.calls.append({"endpoint": endpoint, "args": args})
                return {
                    "data": {
                        "tp_info": {"current_tp": 30, "max_tp": 100, "max_recovery_time": 0},
                        "item_list": [{"item_id": 59, "number": 10}, {"item_id": 75, "number": 20}],
                        "card_list": [{"card_id": 100101}],
                        "support_card_list": [],
                        "support_card_deck_array": [],
                        "trained_chara": [],
                    }
                }

            def load_career(self):
                return {
                    "data": {
                        "chara_info": {
                            "card_id": 100101,
                            "turn": 2,
                            "scenario_id": 4,
                            "support_card_array": [],
                        }
                    }
                }

        client = HiddenActiveCareerClient()
        main.active_client = client
        self.set_low_tp_start_state()

        result = main.start_career_from_request(make_start_request())

        self.assertFalse(result["success"])
        self.assertIn("active career already exists", result["detail"])
        self.assertFalse(any("card_id" in call for call in client.calls))

    def test_start_preflight_treats_direct_probe_102_as_no_active_career(self):
        class NoActiveCareerClient(FakeCareerClient):
            def call(self, endpoint, args=None):
                self.calls.append({"endpoint": endpoint, "args": args})
                return {"data": make_live_start_load_data()}

            def load_career(self):
                raise Exception("API error 102 on single_mode_free/load")

        client = NoActiveCareerClient()
        main.active_client = client
        self.set_low_tp_start_state()

        result = main.start_career_from_request(make_start_request())

        self.assertTrue(result["success"])
        self.assertTrue(any(call.get("card_id") == 100101 for call in client.calls))

    def test_start_records_debug_when_server_rejects_1052(self):
        class RejectingStartClient(FakeCareerClient):
            def call(self, endpoint, args=None):
                self.calls.append({"endpoint": endpoint, "args": args})
                return {"data": make_live_start_load_data()}

            def load_career(self):
                raise Exception("API error 102 on single_mode_free/load")

            def start_career(self, **kwargs):
                self.calls.append(kwargs)
                raise Exception("API error 1052 on single_mode_free/start")

        client = RejectingStartClient()
        main.active_client = client
        self.set_low_tp_start_state()

        result = main.start_career_from_request(make_start_request())

        self.assertFalse(result["success"])
        self.assertIn("1052", result["detail"])
        self.assertIn("1052", main.active_start_debug["error"])
        self.assertEqual(main.active_start_debug["request"]["support_count"], 5)
        self.assertTrue(any(call.get("card_id") == 100101 for call in client.calls))

    def test_start_records_debug_when_server_rejects_102(self):
        class RejectingStartClient(FakeCareerClient):
            def call(self, endpoint, args=None):
                self.calls.append({"endpoint": endpoint, "args": args})
                return {"data": make_live_start_load_data()}

            def load_career(self):
                raise Exception("API error 102 on single_mode_free/load")

            def start_career(self, **kwargs):
                self.calls.append(kwargs)
                raise Exception("API error 102 on single_mode_free/start")

        client = RejectingStartClient()
        main.active_client = client
        self.set_low_tp_start_state()
        main.active_start_state["tp_info"]["current_tp"] = 30

        with patch.object(main, "write_start_error_snapshot", return_value="snapshot.json"):
            result = main.start_career_from_request(make_start_request())

        self.assertFalse(result["success"])
        self.assertIn("102", result["detail"])
        self.assertEqual(result["debug_snapshot"], "snapshot.json")
        self.assertIn("102", main.active_start_debug["error"])
        self.assertTrue(any(call.get("card_id") == 100101 for call in client.calls))

    def test_start_preflight_proves_payload_without_starting_career(self):
        class ProofClient(FakeCareerClient):
            def call(self, endpoint, args=None):
                self.calls.append({"endpoint": endpoint, "args": args})
                return {"data": make_live_start_load_data()}

            def load_career(self):
                raise Exception("API error 102 on single_mode_free/load")

            def start_career(self, **kwargs):
                raise AssertionError("preflight must not start a career")

        client = ProofClient()
        main.active_client = client

        result = main.preflight_career_run_request(make_start_request(allow_recover_tp=1))

        self.assertTrue(result["success"])
        self.assertTrue(result["proof"]["ok"])
        self.assertEqual(result["payload"]["start_chara"]["select_deck_id"], 1)
        self.assertEqual(result["payload"]["start_chara"]["support_card_ids"], [30101, 30102, 30103, 30104, 30107])
        self.assertIs(result["payload"]["allow_recover_tp"], True)
        self.assertTrue(result["proof"]["tp_recovery"]["can_recover"])
        self.assertFalse(any(call.get("card_id") == 100101 for call in client.calls))

    def test_start_preflight_catches_partial_synced_deck(self):
        class PartialDeckClient(FakeCareerClient):
            def call(self, endpoint, args=None):
                self.calls.append({"endpoint": endpoint, "args": args})
                return {"data": make_live_start_load_data(deck_ids=[30101, 30102, 30103])}

            def load_career(self):
                raise Exception("API error 102 on single_mode_free/load")

        client = PartialDeckClient()
        main.active_client = client

        result = main.preflight_career_run_request(make_start_request(support_card_ids=[30101, 30102, 30103]))

        self.assertFalse(result["success"])
        self.assertIn("exactly 5", result["detail"])
        self.assertIn("3/5", result["detail"])

    def test_client_payload_omits_recovery_mode_when_disabled(self):
        client = object.__new__(UmaClient)
        captured = {}

        def fake_call(endpoint, payload, **kwargs):
            captured["endpoint"] = endpoint
            captured["payload"] = payload
            return {"ok": True}

        client.call = fake_call
        client.start_career(
            card_id=100101,
            support_card_ids=[30101, 30102, 30103, 30104, 30107],
            friend_viewer_id=123456789,
            friend_card_id=30106,
            parent_id_1=9001,
            parent_id_2=9002,
            tp_info={"current_tp": 30, "max_tp": 100, "max_recovery_time": 0},
            allow_recover_tp=0,
        )

        self.assertEqual(captured["endpoint"], "single_mode_free/start")
        self.assertNotIn("allow_recover_tp", captured["payload"])

    def test_client_payload_sends_recovery_mode_when_enabled(self):
        client = object.__new__(UmaClient)
        captured = {}

        def fake_call(endpoint, payload, **kwargs):
            captured["endpoint"] = endpoint
            captured["payload"] = payload
            return {"ok": True}

        client.call = fake_call
        client.start_career(
            card_id=100101,
            support_card_ids=[30101, 30102, 30103, 30104, 30107],
            friend_viewer_id=123456789,
            friend_card_id=30106,
            parent_id_1=9001,
            parent_id_2=9002,
            tp_info={"current_tp": 0, "max_tp": 100, "max_recovery_time": 0},
            allow_recover_tp=2,
        )

        self.assertEqual(captured["endpoint"], "single_mode_free/start")
        self.assertIs(captured["payload"]["allow_recover_tp"], True)
        self.assertEqual(captured["payload"]["use_tp"], 30)

    def test_client_start_payload_omits_empty_showtime_fields_for_normal_career(self):
        payload = UmaClient.build_start_payload(
            card_id=100101,
            support_card_ids=[30101, 30102, 30103, 30104, 30107],
            friend_viewer_id=123456789,
            friend_card_id=30106,
            parent_id_1=9001,
            parent_id_2=9002,
            tp_info={"current_tp": 30, "max_tp": 100, "max_recovery_time": 0},
        )

        start_chara = payload["start_chara"]
        self.assertNotIn("selected_difficulty_info", start_chara)
        self.assertNotIn("boost_story_event_id", start_chara)
        self.assertNotIn("rental_succession_trained_chara", start_chara)

    def test_client_start_payload_keeps_showtime_fields_when_selected(self):
        payload = UmaClient.build_start_payload(
            card_id=100101,
            support_card_ids=[30101, 30102, 30103, 30104, 30107],
            friend_viewer_id=123456789,
            friend_card_id=30106,
            parent_id_1=9001,
            parent_id_2=9002,
            tp_info={"current_tp": 30, "max_tp": 100, "max_recovery_time": 0},
            difficulty_id=1003,
            difficulty=3,
            is_boost=1,
            boost_story_event_id=1015,
        )

        start_chara = payload["start_chara"]
        self.assertEqual(
            start_chara["selected_difficulty_info"],
            {"difficulty_id": 1003, "difficulty": 3, "is_boost": 1},
        )
        self.assertEqual(start_chara["boost_story_event_id"], 1015)

    def test_client_start_payload_keeps_showtime_difficulty_without_boost(self):
        payload = UmaClient.build_start_payload(
            card_id=100101,
            support_card_ids=[30101, 30102, 30103, 30104, 30107],
            friend_viewer_id=123456789,
            friend_card_id=30106,
            parent_id_1=9001,
            parent_id_2=9002,
            tp_info={"current_tp": 30, "max_tp": 100, "max_recovery_time": 0},
            difficulty_id=1003,
            difficulty=2,
            is_boost=0,
            boost_story_event_id=0,
        )

        start_chara = payload["start_chara"]
        self.assertEqual(
            start_chara["selected_difficulty_info"],
            {"difficulty_id": 1003, "difficulty": 2, "is_boost": 0},
        )
        self.assertNotIn("boost_story_event_id", start_chara)

    def test_sanitize_showtime_keeps_difficulty_but_strips_unavailable_boost(self):
        req = make_start_request(
            difficulty_id=1003,
            difficulty=2,
            is_boost=1,
            boost_story_event_id=1015,
        )

        warnings = main.sanitize_showtime_start_fields(req, make_showtime_load_data(item_num=0))

        self.assertEqual(req.difficulty_id, 1003)
        self.assertEqual(req.difficulty, 2)
        self.assertEqual(req.is_boost, 0)
        self.assertEqual(req.boost_story_event_id, 0)
        self.assertTrue(any("without boost" in warning for warning in warnings))

    def test_showtime_start_candidates_include_selected_adjacent_and_open(self):
        req = make_start_request(
            difficulty_id=1003,
            difficulty=2,
            is_boost=0,
            boost_story_event_id=0,
        )
        main.sanitize_showtime_start_fields(req, make_showtime_load_data(item_num=0, open_difficulty_index=4))

        candidates = main.build_showtime_start_candidates(
            req,
            make_showtime_load_data(item_num=0, open_difficulty_index=4),
        )

        self.assertEqual(
            [(row["difficulty_id"], row["difficulty"], row["is_boost"]) for row in candidates],
            [(1003, 2, 0), (1003, 1, 0), (1003, 3, 0), (1003, 4, 0)],
        )

    def test_sanitize_showtime_keeps_available_explicit_boost(self):
        req = make_start_request(
            difficulty_id=1003,
            difficulty=4,
            is_boost=1,
            boost_story_event_id=0,
        )

        warnings = main.sanitize_showtime_start_fields(req, make_showtime_load_data(item_num=2, story_event_id=1015))

        self.assertEqual(warnings, [])
        self.assertEqual(req.difficulty_id, 1003)
        self.assertEqual(req.difficulty, 4)
        self.assertEqual(req.is_boost, 1)
        self.assertEqual(req.boost_story_event_id, 1015)

    def test_sanitize_showtime_drops_stale_difficulty(self):
        req = make_start_request(
            difficulty_id=9999,
            difficulty=2,
            is_boost=1,
            boost_story_event_id=1015,
        )

        warnings = main.sanitize_showtime_start_fields(req, make_showtime_load_data(item_num=2))

        self.assertEqual(req.difficulty_id, 0)
        self.assertEqual(req.difficulty, 0)
        self.assertEqual(req.is_boost, 0)
        self.assertEqual(req.boost_story_event_id, 0)
        self.assertTrue(any("Dropped stale Showtime" in warning for warning in warnings))

    def test_client_start_102_retries_showtime_without_boost_item(self):
        client = object.__new__(UmaClient)
        calls = []

        def fake_call(endpoint, payload, **kwargs):
            calls.append((endpoint, payload, kwargs))
            if len(calls) == 1:
                raise ApiCallError(
                    "API error 102 on single_mode_free/start",
                    endpoint=endpoint,
                    result_code=102,
                    response_code=102,
                )
            return {"ok": True}

        client.call = fake_call

        result = client.start_career(
            card_id=100101,
            support_card_ids=[30101, 30102, 30103, 30104, 30107],
            friend_viewer_id=123456789,
            friend_card_id=30106,
            parent_id_1=9001,
            parent_id_2=9002,
            tp_info={"current_tp": 30, "max_tp": 100, "max_recovery_time": 0},
            difficulty_id=1003,
            difficulty=2,
            is_boost=1,
            boost_story_event_id=1015,
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 2)
        first = calls[0][1]["start_chara"]
        second = calls[1][1]["start_chara"]
        self.assertEqual(first["selected_difficulty_info"], {"difficulty_id": 1003, "difficulty": 2, "is_boost": 1})
        self.assertEqual(first["boost_story_event_id"], 1015)
        self.assertEqual(second["selected_difficulty_info"], {"difficulty_id": 1003, "difficulty": 2, "is_boost": 0})
        self.assertNotIn("boost_story_event_id", second)

    def test_client_start_205_retries_with_legacy_optional_blocks(self):
        client = object.__new__(UmaClient)
        calls = []

        def fake_call(endpoint, payload, **kwargs):
            calls.append((endpoint, payload, kwargs))
            if len(calls) == 1:
                raise ApiCallError(
                    "API error 205 on single_mode_free/start",
                    endpoint=endpoint,
                    result_code=205,
                    response_code=205,
                )
            return {"ok": True}

        client.call = fake_call

        result = client.start_career(
            card_id=100101,
            support_card_ids=[30101, 30102, 30103, 30104, 30107],
            friend_viewer_id=123456789,
            friend_card_id=30106,
            parent_id_1=9001,
            parent_id_2=9002,
            tp_info={"current_tp": 30, "max_tp": 100, "max_recovery_time": 0},
        )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 2)
        self.assertNotIn("selected_difficulty_info", calls[0][1]["start_chara"])
        self.assertIn("selected_difficulty_info", calls[1][1]["start_chara"])
        self.assertIn("rental_succession_trained_chara", calls[1][1]["start_chara"])

    def test_client_start_retries_showtime_candidate_levels_before_normal_fallback(self):
        client = object.__new__(UmaClient)
        calls = []

        def fake_call(endpoint, payload, **kwargs):
            calls.append((endpoint, payload, kwargs))
            selected = (payload["start_chara"].get("selected_difficulty_info") or {})
            if selected.get("difficulty_id") == 1003 and selected.get("difficulty") in {2, 1}:
                raise ApiCallError(
                    "API error 205 on single_mode_free/start",
                    endpoint=endpoint,
                    result_code=205,
                    response_code=205,
                )
            return {"ok": True, "selected": selected}

        client.call = fake_call

        result = client.start_career(
            card_id=100101,
            support_card_ids=[30101, 30102, 30103, 30104, 30107],
            friend_viewer_id=123456789,
            friend_card_id=30106,
            parent_id_1=9001,
            parent_id_2=9002,
            tp_info={"current_tp": 30, "max_tp": 100, "max_recovery_time": 0},
            difficulty_id=1003,
            difficulty=2,
            is_boost=0,
            boost_story_event_id=0,
            difficulty_candidates=[
                {"difficulty_id": 1003, "difficulty": 2, "is_boost": 0, "boost_story_event_id": 0},
                {"difficulty_id": 1003, "difficulty": 1, "is_boost": 0, "boost_story_event_id": 0},
                {"difficulty_id": 1003, "difficulty": 3, "is_boost": 0, "boost_story_event_id": 0},
                {"difficulty_id": 1003, "difficulty": 4, "is_boost": 0, "boost_story_event_id": 0},
            ],
        )

        self.assertEqual(result["selected"], {"difficulty_id": 1003, "difficulty": 3, "is_boost": 0})
        self.assertEqual(
            [
                call[1]["start_chara"]["selected_difficulty_info"]["difficulty"]
                for call in calls
                if "selected_difficulty_info" in call[1]["start_chara"]
            ],
            [2, 1, 3],
        )

    def test_client_recovery_item_payload_uses_flat_client_own_num(self):
        client = object.__new__(UmaClient)
        captured = {}

        def fake_call(endpoint, payload):
            captured["endpoint"] = endpoint
            captured["payload"] = payload
            return {"ok": True}

        client.call = fake_call

        client.use_recovery_item(item_id=32, current_num=20)

        self.assertEqual(captured["endpoint"], "item/use_recovery_item")
        self.assertNotIn("use_item_info", captured["payload"])
        self.assertEqual(captured["payload"]["item_id"], 32)
        self.assertEqual(captured["payload"]["item_num"], 1)
        self.assertEqual(captured["payload"]["client_own_num"], 20)

    def test_client_carats_recovery_payload_uses_count_and_client_own_num(self):
        client = object.__new__(UmaClient)
        client.item_map = {}
        captured = {}

        def fake_call(endpoint, payload):
            captured["endpoint"] = endpoint
            captured["payload"] = payload
            return {
                "data": {
                    "coin_info": {"fcoin": 2245, "coin": 40},
                    "tp_info": {"current_tp": 48, "max_tp": 100},
                }
            }

        client.call = fake_call

        client.recover_trainer_point(count=1, client_own_num=2295)

        self.assertEqual(captured["endpoint"], "user/recovery_trainer_point")
        self.assertEqual(captured["payload"], {"count": 1, "client_own_num": 2295})
        self.assertEqual(client.coin_info, {"fcoin": 2245, "coin": 40})
        self.assertEqual(client.tp_info, {"current_tp": 48, "max_tp": 100})

    def test_client_carats_recovery_default_uses_total_carats(self):
        client = object.__new__(UmaClient)
        client.coin_info = {"fcoin": 1505, "coin": 40}
        client.item_map = {}
        captured = {}

        def fake_call(endpoint, payload):
            captured["endpoint"] = endpoint
            captured["payload"] = payload
            return {"ok": True}

        client.call = fake_call

        client.recover_trainer_point(count=1)

        self.assertEqual(captured["endpoint"], "user/recovery_trainer_point")
        self.assertEqual(captured["payload"], {"count": 1, "client_own_num": 1545})

    def test_client_alarm_clock_exchange_payload_matches_live_trace(self):
        client = object.__new__(UmaClient)
        client.coin_info = {"fcoin": 2235, "coin": 40}
        client.item_map = {}
        captured = {}

        def fake_call(endpoint, payload):
            captured["endpoint"] = endpoint
            captured["payload"] = payload
            return {
                "data": {
                    "coin_info": {"fcoin": 2225, "coin": 40},
                    "reward_summary_info": {"add_item_list": [{"item_id": 95, "number": 1}]},
                }
            }

        client.call = fake_call

        client.exchange_item(exchange_id=9001, count=1, current_num=2275, get_list_time="")

        self.assertEqual(captured["endpoint"], "item/exchange")
        self.assertEqual(captured["payload"], {
            "exchange_id": 9001,
            "count": 1,
            "current_num": 2275,
            "get_list_time": "",
        })
        self.assertEqual(client.coin_info, {"fcoin": 2225, "coin": 40})
        self.assertEqual(client.item_map[95], 1)


if __name__ == "__main__":
    unittest.main()
