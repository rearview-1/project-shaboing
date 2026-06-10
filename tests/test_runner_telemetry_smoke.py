import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from career_bot.runner import CareerRunner
from uma_api.client import ApiCallError


BASE_DIR = Path(__file__).resolve().parents[1]


class RunnerTelemetrySmokeTests(unittest.TestCase):
    def _snapshot_state(self):
        return {
            "data": {
                "chara_info": {
                    "turn": 21,
                    "card_id": 100102,
                    "vital": 82,
                    "max_vital": 100,
                    "motivation": 5,
                    "speed": 301,
                    "stamina": 240,
                    "power": 220,
                    "guts": 155,
                    "wiz": 288,
                    "skill_point": 121,
                    "evaluation_info_array": [
                        {"target_id": 1, "evaluation": 80},
                        {"target_id": 2, "evaluation": 79},
                        {"target_id": 9, "evaluation": 95},
                    ],
                    "skill_array": [],
                    "skill_tips_array": [{"group_id": 20160, "rarity": 1, "level": 0}],
                },
                "free_data_set": {
                    "coin_num": 120,
                    "user_item_info_array": [{"item_id": 10001, "num": 1}],
                    "pick_up_item_info_array": [
                        {
                            "shop_item_id": 1,
                            "item_id": 8003,
                            "coin_num": 70,
                            "original_coin_num": 70,
                            "item_buy_num": 0,
                            "limit_buy_count": 1,
                            "limit_turn": 0,
                        }
                    ],
                    "item_effect_array": [
                        {"item_id": 8002, "remain_turn": 2},
                    ],
                },
                "home_info": {
                    "command_info_array": [
                        {
                            "command_type": 1,
                            "command_id": 101,
                            "command_group_id": 101,
                            "is_enable": 1,
                            "failure_rate": 7,
                            "level": 3,
                            "training_partner_array": [1, 2, 9],
                            "tips_event_partner_array": [2],
                            "params_inc_dec_info_array": [
                                {"target_type": 1, "value": 20},
                                {"target_type": 3, "value": 4},
                                {"target_type": 30, "value": 6},
                                {"target_type": 10, "value": -21},
                            ],
                        }
                    ]
                },
            }
        }

    def test_training_snapshot_captures_items_partners_rainbows_and_gains(self):
        runner = CareerRunner(BASE_DIR)
        state = {
            "data": {
                "chara_info": {
                    "turn": 21,
                    "vital": 82,
                    "max_vital": 100,
                    "motivation": 5,
                    "speed": 301,
                    "stamina": 240,
                    "power": 220,
                    "guts": 155,
                    "wiz": 288,
                    "skill_point": 121,
                    "evaluation_info_array": [
                        {"target_id": 1, "evaluation": 80},
                        {"target_id": 2, "evaluation": 79},
                        {"target_id": 9, "evaluation": 95},
                    ],
                },
                "free_data_set": {
                    "item_effect_array": [
                        {"item_id": 8002, "remain_turn": 2},
                    ]
                },
                "home_info": {
                    "command_info_array": [
                        {
                            "command_type": 1,
                            "command_id": 101,
                            "command_group_id": 101,
                            "is_enable": 1,
                            "failure_rate": 7,
                            "level": 3,
                            "training_partner_array": [1, 2, 9],
                            "tips_event_partner_array": [2],
                            "params_inc_dec_info_array": [
                                {"target_type": 1, "value": 20},
                                {"target_type": 3, "value": 4},
                                {"target_type": 30, "value": 6},
                                {"target_type": 10, "value": -21},
                            ],
                        },
                        {
                            "command_type": 1,
                            "command_id": 106,
                            "command_group_id": 106,
                            "is_enable": 1,
                            "failure_rate": 0,
                            "training_partner_array": [],
                            "tips_event_partner_array": [],
                            "params_inc_dec_info_array": [
                                {"target_type": 5, "value": 9},
                            ],
                        },
                    ]
                },
            }
        }

        snapshot = runner._training_snapshot(state, {})
        speed = snapshot["trainings"][0]

        self.assertEqual(snapshot["active_item_effects"][0]["name"], "Motivating Megaphone")
        self.assertEqual(speed["name"], "Speed")
        self.assertEqual(speed["stat_gain"]["speed"], 20)
        self.assertEqual(speed["stat_gain"]["power"], 4)
        self.assertEqual(speed["stat_gain"]["skill_point"], 6)
        self.assertEqual(speed["stat_gain"]["hp"], -21)
        self.assertEqual(speed["deck_partner_count"], 2)
        self.assertEqual(speed["rainbow_count"], 1)
        self.assertEqual(speed["hint_count"], 1)
        self.assertEqual(speed["high_bond_count"], 2)
        self.assertEqual(snapshot["best_training"]["name"], "Speed")

    def test_race_info_marks_catalog_g1_programs(self):
        runner = CareerRunner(BASE_DIR)
        race = next(
            row for row in runner.race_planner.catalog.races
            if row.get("type") == "G1" and row.get("program_id")
        )

        info = runner._race_info_for_program(race["program_id"])

        self.assertEqual(info["grade"], "G1")
        self.assertTrue(runner._is_g1_program(race["program_id"]))

    def test_skill_error_snapshot_writes_runtime_json(self):
        runner = CareerRunner(BASE_DIR)
        state = self._snapshot_state()
        runner.skill_buyer.last_candidates = [{"skill_id": 201601, "name": "Groundwork", "cost": 180}]
        runner.skill_buyer.last_selected = [{"skill_id": 201601, "name": "Groundwork", "cost": 180}]
        runner.skill_buyer.last_attempt = [{"skill_id": 201601, "name": "Groundwork", "cost": 180}]
        runner.skill_buyer.last_result = {
            "result": "failed",
            "turn": 21,
            "error": "API error 205 on single_mode_free/gain_skills",
            "payload": [{"skill_id": 201601, "level": 1}],
        }
        runner.skill_buyer.attempt_events = [{
            "turn": 21,
            "selected": list(runner.skill_buyer.last_selected),
            "attempt": list(runner.skill_buyer.last_attempt),
            "payload": [{"skill_id": 201601, "level": 1}],
            "result": dict(runner.skill_buyer.last_result),
        }]

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"UMA_RUNTIME_DIR": tmp}, clear=False):
            path = runner._maybe_write_skill_error_snapshot(
                state,
                {"name": "snapshot preset"},
                "skill_buy",
                {"phase": "unit_test"},
            )

            self.assertIsNotNone(path)
            self.assertTrue(path.exists())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["category"], "skill_buy")
            self.assertEqual(payload["schema"], "sweepy_error_snapshot_v2")
            self.assertEqual(payload["context"]["phase"], "unit_test")
            self.assertEqual(payload["bot_vision"]["bot_skill_result"]["result"], "failed")
            self.assertEqual(payload["bot_vision"]["training_snapshot"]["best_training"]["name"], "Speed")
            self.assertIn("skill_context", payload["diagnostics"])
            self.assertIn("writer_call_stack", payload)
            latest = Path(tmp) / "error_snapshots" / "skill_buy" / "latest_skill_buy.json"
            self.assertTrue(latest.exists())

    def test_skill_debug_rows_separate_live_resolved_variant_from_same_group_attempt(self):
        runner = CareerRunner(BASE_DIR)
        state = self._snapshot_state()
        state["data"]["chara_info"]["skill_point"] = 999
        state["data"]["chara_info"]["skill_tips_array"] = [{"group_id": 20126, "rarity": 1, "level": 0}]
        runner.skill_buyer.last_selected = [{
            "skill_id": 201261,
            "resolved_skill_id": 201262,
            "group_id": 20126,
            "name": "Sixth Sense",
            "resolved_name": "Dodging Danger",
            "cost": 128,
        }]
        runner.skill_buyer.last_attempt = [{
            "skill_id": 201261,
            "resolved_skill_id": 201262,
            "group_id": 20126,
            "name": "Sixth Sense",
            "resolved_name": "Dodging Danger",
            "cost": 128,
            "preflight_error": "not_live_resolved_variant",
        }]

        skill_rows = runner._debug_skill_options(state, {})
        row = next(item for item in skill_rows if item["group_id"] == 20126)
        context = runner._skill_snapshot_context(state, {}, skill_rows)
        mismatch = context["selected_or_attempted_group_variant_mismatches"][0]

        self.assertEqual(row["skill_id"], 201262)
        self.assertEqual(row["name"], "Dodging Danger")
        self.assertFalse(row["selected"])
        self.assertFalse(row["attempted"])
        self.assertTrue(row["group_selected"])
        self.assertTrue(row["group_attempted"])
        self.assertEqual(row["selected_skill_id_in_group"], 201261)
        self.assertEqual(row["attempted_skill_id_in_group"], 201261)
        self.assertEqual(mismatch["source"], "selected")
        self.assertEqual(mismatch["skill_id"], 201261)
        self.assertEqual(mismatch["resolved_skill_ids"], [201262])

    def test_skill_debug_rows_show_blocked_default_priority_override(self):
        runner = CareerRunner(BASE_DIR)
        state = self._snapshot_state()
        state["data"]["chara_info"]["skill_point"] = 999
        state["data"]["chara_info"]["skill_tips_array"] = [{"group_id": 20144, "rarity": 1, "level": 1}]

        skill_rows = runner._debug_skill_options(state, {})
        row = next(item for item in skill_rows if item["group_id"] == 20144)

        self.assertEqual(row["skill_id"], 201442)
        self.assertEqual(row["default_resolved_skill_id"], 201442)
        self.assertEqual(row["priority_selected_skill_id"], 201441)
        self.assertEqual(row["priority_selected_name"], "All-Seeing Eyes")
        self.assertTrue(row["priority_override_blocked"])

    def test_item_error_snapshot_writes_runtime_json(self):
        runner = CareerRunner(BASE_DIR)
        state = self._snapshot_state()
        state["data"]["free_data_set"]["user_item_info_array"].append({"item_id": 8003, "num": 2})
        shop_row = dict(state["data"]["free_data_set"]["pick_up_item_info_array"][0])
        inventory_row = {"item_id": 8003, "num": 2}
        request_payload = {
            "exchange_item_info_array": [{"shop_item_id": 1, "current_num": 2}],
            "current_turn": 21,
        }
        runner.item_manager.current_turn = 21
        runner.item_manager.failed_exchange_this_snapshot = {1}
        runner.item_manager.persistent_failed_exchange_item_ids = {8003: 2}
        runner.item_manager.recover_after_exchange_error = True
        runner.item_manager.last_buy_options = [{"name": "Empowering Megaphone", "item_id": 8003, "shop_item_id": 1, "cost": 70}]
        runner.item_manager.last_buy_selected = [{"name": "Empowering Megaphone", "item_id": 8003, "shop_item_id": 1, "cost": 70}]
        runner.item_manager.last_buy_attempt = [{"shop_item_id": 1, "current_num": 2}]
        runner.item_manager.last_buy_result = {
            "result": "per_item_fallback",
            "turn": 21,
            "endpoint": "single_mode_free/multi_item_exchange",
            "payload": [{"shop_item_id": 1, "current_num": 2}],
            "request_payload": request_payload,
            "payload_shop_rows": [shop_row],
            "payload_inventory_rows": [inventory_row],
            "payload_item_details": [{
                "payload_row": {"shop_item_id": 1, "current_num": 2},
                "item_id": 8003,
                "item_name": "Empowering Megaphone",
                "shop_row": shop_row,
                "inventory_row": inventory_row,
                "inventory_count": 2,
            }],
            "source_state_turn": 20,
            "request_current_turn": 21,
            "turn_drift": True,
            "response_body_verbatim": {"data_headers": {"result_code": 205}},
            "original_error": "API error 205 on single_mode_free/multi_item_exchange",
        }
        runner.item_manager.buy_attempt_events = [{
            "turn": 21,
            "source_state_turn": 20,
            "request_current_turn": 21,
            "turn_drift": True,
            "endpoint": "single_mode_free/multi_item_exchange",
            "selected": list(runner.item_manager.last_buy_selected),
            "attempt": [{"shop_item_id": 1, "cost": 70, "current_num": 0}],
            "payload": list(runner.item_manager.last_buy_attempt),
            "request_payload": request_payload,
            "payload_shop_rows": [shop_row],
            "payload_inventory_rows": [inventory_row],
            "payload_item_details": [{
                "payload_row": {"shop_item_id": 1, "current_num": 2},
                "item_id": 8003,
                "item_name": "Empowering Megaphone",
                "shop_row": shop_row,
                "inventory_row": inventory_row,
                "inventory_count": 2,
            }],
            "refresh_retry_error": {
                "request_payload": request_payload,
                "payload_shop_rows": [shop_row],
                "payload_inventory_rows": [inventory_row],
                "response_body_verbatim": {"data_headers": {"result_code": 205}},
            },
            "result": dict(runner.item_manager.last_buy_result),
        }]

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"UMA_RUNTIME_DIR": tmp}, clear=False):
            path = runner._maybe_write_item_error_snapshot(
                state,
                {"name": "snapshot preset"},
                "item_buy",
                result=runner.item_manager.last_buy_result,
                recover_flag=True,
                extra={"phase": "unit_test"},
            )

            self.assertIsNotNone(path)
            self.assertTrue(path.exists())
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["category"], "item_buy")
            self.assertEqual(payload["schema"], "sweepy_error_snapshot_v2")
            self.assertEqual(payload["context"]["phase"], "unit_test")
            self.assertEqual(payload["bot_vision"]["bot_shop_result"]["result"], "per_item_fallback")
            self.assertEqual(payload["bot_vision"]["shop_rows_enriched"][0]["name"], "Empowering Megaphone")
            self.assertTrue(payload["bot_vision"]["item_manager_state"]["recover_after_exchange_error"])
            self.assertIn("item_context", payload["diagnostics"])
            self.assertEqual(payload["diagnostics"]["item_context"]["source_state_turn"], 20)
            self.assertEqual(payload["diagnostics"]["item_context"]["request_current_turn"], 21)
            self.assertTrue(payload["diagnostics"]["item_context"]["turn_drift"])
            self.assertEqual(payload["diagnostics"]["item_context"]["failing_endpoint"], "single_mode_free/multi_item_exchange")
            self.assertEqual(payload["diagnostics"]["item_context"]["failing_endpoint_payload"]["exchange_item_info_array"][0]["current_num"], 2)
            self.assertEqual(payload["diagnostics"]["item_context"]["failing_payload_shop_rows"][0]["item_id"], 8003)
            self.assertEqual(payload["diagnostics"]["item_context"]["failing_payload_inventory_rows"][0]["item_id"], 8003)
            self.assertEqual(payload["diagnostics"]["item_context"]["last_buy_options"][0]["item_id"], 8003)
            self.assertEqual(payload["diagnostics"]["item_context"]["failing_response_body_verbatim"]["data_headers"]["result_code"], 205)
            self.assertEqual(payload["diagnostics"]["item_context"]["refresh_retry_payload"]["exchange_item_info_array"][0]["shop_item_id"], 1)
            latest = Path(tmp) / "error_snapshots" / "item_buy" / "latest_item_buy.json"
            self.assertTrue(latest.exists())

    def test_race_entry_error_snapshot_writes_runtime_json_with_trace_rows(self):
        runner = CareerRunner(BASE_DIR)
        state = self._snapshot_state()
        state["data"]["chara_info"]["turn"] = 16
        state["data"]["chara_info"]["fans"] = 565
        state["data"]["chara_info"]["playing_state"] = 1
        state["data"]["chara_info"]["state"] = 0
        state["data"]["race_condition_array"] = [{"program_id": 629, "weather": 2, "ground_condition": 1}]
        state["data"]["home_info"]["race_entry_restriction"] = 0

        class FailingRaceEntryClient:
            viewer_id = 162337796827

            def __init__(self):
                self.calls = []
                self.entry_attempts = 0

            def race_entry(self, program_id, current_turn):
                self.calls.append(("race_entry", program_id, current_turn))
                self.entry_attempts += 1
                req_id = "race-entry-a" if self.entry_attempts == 1 else "race-entry-b"
                raise ApiCallError(
                    "API error 205 on single_mode_free/race_entry",
                    endpoint="single_mode_free/race_entry",
                    request_payload={"program_id": program_id, "current_turn": current_turn},
                    response_body={"data_headers": {"viewer_id": 3080576358491, "result_code": 205}},
                    result_code=205,
                    response_code=205,
                    req_id=req_id,
                )

            def load_career(self):
                self.calls.append(("load_career",))
                return {
                    "data": {
                        "chara_info": {
                            "turn": 16,
                            "playing_state": 1,
                            "state": 0,
                            "fans": 565,
                            "skill_point": 121,
                        },
                        "home_info": {"race_entry_restriction": 0},
                        "race_condition_array": [{"program_id": 629, "weather": 2, "ground_condition": 1}],
                    }
                }

            def login(self):
                self.calls.append(("login",))

        client = FailingRaceEntryClient()

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"UMA_RUNTIME_DIR": tmp}, clear=False):
            trace_dir = Path(tmp) / "trace_logs" / "api_payloads"
            trace_dir.mkdir(parents=True, exist_ok=True)
            trace_rows = [
                {
                    "ts": 1.0,
                    "direction": "REQ",
                    "endpoint": "single_mode_free/race_entry",
                    "data": {"payload": {"program_id": 629, "current_turn": 16}},
                    "req_id": "race-entry-a",
                },
                {
                    "ts": 1.1,
                    "direction": "RES",
                    "endpoint": "single_mode_free/race_entry",
                    "data": {"response_code": 205, "data_headers": {"viewer_id": 3080576358491, "result_code": 205}},
                    "req_id": "race-entry-a",
                },
                {
                    "ts": 1.2,
                    "direction": "REQ",
                    "endpoint": "single_mode_free/race_entry",
                    "data": {"payload": {"program_id": 629, "current_turn": 16}},
                    "req_id": "race-entry-b",
                },
                {
                    "ts": 1.3,
                    "direction": "RES",
                    "endpoint": "single_mode_free/race_entry",
                    "data": {"response_code": 205, "data_headers": {"viewer_id": 3080576358491, "result_code": 205}},
                    "req_id": "race-entry-b",
                },
            ]
            trace_file = trace_dir / "test_race_entry_payloads.jsonl"
            trace_file.write_text(
                "\n".join(json.dumps(row) for row in trace_rows) + "\n",
                encoding="utf-8",
            )

            result = runner._race(
                client,
                state,
                {"name": "snapshot preset", "scenario_id": 1},
                {"program_id": 629, "current_turn": 16},
            )

            self.assertEqual((result["data"]["chara_info"])["turn"], 16)
            latest = Path(tmp) / "error_snapshots" / "race_entry" / "latest_race_entry.json"
            self.assertTrue(latest.exists())
            payload = json.loads(latest.read_text(encoding="utf-8"))
            self.assertEqual(payload["category"], "race_entry")
            self.assertEqual(payload["schema"], "sweepy_error_snapshot_v2")
            ctx = payload["diagnostics"]["race_context"]
            self.assertEqual(ctx["requested_program_id"], 629)
            self.assertTrue(ctx["requested_program_available"])
            self.assertTrue(ctx["recovery_attempted_after_refresh"])
            self.assertTrue(ctx["response_viewer_id_mismatch"])
            self.assertEqual(len(ctx["api_trace_rows"]), 4)
            self.assertEqual(ctx["api_trace_rows"][0]["endpoint"], "single_mode_free/race_entry")


if __name__ == "__main__":
    unittest.main()
