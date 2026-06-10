import tempfile
import unittest
from pathlib import Path

from career_bot.manual_recorder import (
    ManualCareerRecorder,
    build_report_from_hachimi_summaries,
    build_report_from_trace,
)
from career_bot.learning import load_manual_hachimi_careers


BASE_DIR = Path(__file__).resolve().parents[1]


def response_for_turn(turn, speed=100, skill_point=50):
    return {
        "response_code": 1,
        "data_headers": {"result_code": 1},
        "data": {
            "chara_info": {
                "single_mode_chara_id": 123,
                "card_id": 100101,
                "scenario_id": 4,
                "start_time": "2026-05-14 10:00:00",
                "turn": turn,
                "vital": 80,
                "max_vital": 100,
                "motivation": 5,
                "speed": speed,
                "stamina": 90,
                "power": 80,
                "guts": 70,
                "wiz": 60,
                "skill_point": skill_point,
                "skill_array": [{"skill_id": 110261, "level": 3}],
                "skill_tips_array": [{"group_id": 20037, "rarity": 1, "level": 1}],
                "evaluation_info_array": [{"target_id": 1, "evaluation": 90}],
                "support_card_array": [{"position": 1, "support_card_id": 30086, "limit_break_count": 4}],
            },
            "home_info": {
                "command_info_array": [
                    {
                        "command_type": 1,
                        "command_id": 101,
                        "is_enable": 1,
                        "failure_rate": 0,
                        "level": 5,
                        "training_partner_array": [1],
                        "tips_event_partner_array": [],
                        "params_inc_dec_info_array": [
                            {"target_type": 1, "value": 30},
                            {"target_type": 3, "value": 10},
                            {"target_type": 30, "value": 5},
                            {"target_type": 10, "value": -21},
                        ],
                    }
                ]
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
            },
            "race_history": [
                {"turn": 12, "program_id": 624, "running_style": 1, "result_rank": 1}
            ],
        },
    }


def summary_row_for_turn(
    turn,
    speed=100,
    skill_point=50,
    label="free_check_event",
    index=0,
    inventory=None,
    shop_items=None,
    item_effects=None,
    rank_score=None,
    rank=None,
    rank_label=None,
):
    payload = response_for_turn(turn, speed=speed, skill_point=skill_point)["data"]
    chara = dict(payload["chara_info"])
    if rank_score is not None:
        chara["rank_score"] = rank_score
    if rank is not None:
        chara["rank"] = rank
    if rank_label is not None:
        chara["rank_label"] = rank_label
    home = payload.get("home_info") or {}
    races = payload.get("race_history") or []
    return {
        "schema": "sweepy_hachimi_manual_career_summary_v1",
        "ts_ms": 1000 + turn,
        "label": label,
        "index": index,
        "career_key": "test-career",
        "current": {
            "single_mode_chara_id": chara.get("single_mode_chara_id"),
            "card_id": chara.get("card_id"),
            "scenario_id": chara.get("scenario_id"),
            "start_time": chara.get("start_time"),
            "turn": chara.get("turn"),
            "vital": chara.get("vital"),
            "max_vital": chara.get("max_vital"),
            "motivation": chara.get("motivation"),
            "speed": chara.get("speed"),
            "stamina": chara.get("stamina"),
            "power": chara.get("power"),
            "guts": chara.get("guts"),
            "wit": chara.get("wiz"),
            "skill_point": chara.get("skill_point"),
            "rank_score": chara.get("rank_score"),
            "rank": chara.get("rank"),
            "rank_label": chara.get("rank_label"),
        },
        "skills": {
            "bought": chara.get("skill_array") or [],
            "tips": chara.get("skill_tips_array") or [],
            "disabled": [],
        },
        "supports": {
            "cards": chara.get("support_card_array") or [],
            "bonds": chara.get("evaluation_info_array") or [],
            "training_levels": chara.get("training_level_info_array") or [],
            "guest_outings": [],
        },
        "home": {
            "commands": home.get("command_info_array") or [],
            "disabled_command_ids": home.get("disable_command_id_array") or [],
            "available_continue_num": home.get("available_continue_num"),
            "available_free_continue_num": home.get("available_free_continue_num"),
            "free_continue_num": home.get("free_continue_num"),
            "free_continue_time": home.get("free_continue_time"),
            "race_entry_restriction": home.get("race_entry_restriction"),
        },
        "races": {
            "history": races,
            "conditions": [],
            "start_info": None,
        },
        "response_status": {
            "unchecked_events": [],
        },
        "free_scenario": {
            "coin_num": 120,
            "gained_coin_num": 0,
            "shop_id": 10,
            "sale_value": 0,
            "inventory": inventory,
            "shop_items": shop_items,
            "item_effects": item_effects,
            "commands": [],
        },
    }


class ManualRecorderSmokeTests(unittest.TestCase):
    def test_manual_recorder_captures_training_snapshot_and_action(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = ManualCareerRecorder(BASE_DIR, output_dir=tmp)
            recorder.process_response("single_mode_free/load", response_for_turn(1), {})
            recorder.process_response(
                "single_mode_free/exec_command",
                response_for_turn(2, speed=130, skill_point=55),
                {
                    "current_turn": 1,
                    "current_vital": 80,
                    "command_type": 1,
                    "command_id": 101,
                    "command_group_id": 101,
                },
            )

            turns = recorder.report["turns"]
            self.assertEqual(len(turns), 2)
            self.assertEqual(turns[0]["training_snapshot"]["best_training"]["name"], "Speed")
            self.assertEqual(turns[0]["facility_levels"]["101"]["level"], 5)
            self.assertEqual(turns[0]["support_bonds"]["1"], 90)
            self.assertEqual(turns[0]["server_inventory_raw"][0]["item_id"], 10001)
            self.assertEqual(turns[0]["race_history"][0]["result_rank"], 1)
            self.assertEqual(turns[0]["selected_action"], "train")
            self.assertEqual(turns[0]["current_command"]["command_id"], 101)
            self.assertTrue(turns[0]["selected_friendship_training"])
            self.assertEqual(turns[0]["selected_training"]["name"], "Speed")
            self.assertEqual(turns[0]["bot_recommendation"]["command_id"], 101)
            self.assertTrue(turns[0]["deviation"]["agreed"])
            self.assertEqual(turns[0]["deviation"]["human_training_idx"], 0)

    def test_trace_replay_pairs_requests_and_responses(self):
        with tempfile.TemporaryDirectory() as tmp:
            trace = Path(tmp) / "trace.jsonl"
            trace.write_text(
                "\n".join([
                    '{"direction":"REQ","endpoint":"single_mode_free/exec_command","req_id":"abc","data":{"payload":{"current_turn":1,"current_vital":80,"command_type":1,"command_id":101}}}',
                    '{"direction":"RES","endpoint":"single_mode_free/exec_command","req_id":"abc","data":' + __import__("json").dumps(response_for_turn(2), ensure_ascii=False) + "}",
                ]),
                encoding="utf-8",
            )
            report = build_report_from_trace(trace, BASE_DIR, output_dir=tmp)
            self.assertEqual(report["turns"][0]["selected_action"], "train")
            self.assertEqual(report["turns"][0]["current_command"]["command_id"], 101)

    def test_state_only_capture_can_infer_friendship_training_from_delta(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = ManualCareerRecorder(BASE_DIR, output_dir=tmp)
            recorder.process_response("horseact/WorkSingleModeScenarioFree.Apply", response_for_turn(1), {})
            recorder.process_response("horseact/WorkSingleModeScenarioFree.Apply", response_for_turn(2, speed=130, skill_point=55), {})

            first_turn = recorder.report["turns"][0]
            self.assertEqual(first_turn["selected_action"], "train")
            self.assertEqual(first_turn["selected_training_inference"], "state_delta")
            self.assertTrue(first_turn["selected_friendship_training"])

    def test_process_response_does_not_finish_report_on_midcareer_state_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            recorder = ManualCareerRecorder(BASE_DIR, output_dir=tmp)
            recorder.process_response(
                "single_mode_free/load",
                {
                    "data": {
                        "chara_info": {
                            "single_mode_chara_id": 123,
                            "card_id": 100101,
                            "scenario_id": 4,
                            "start_time": "2026-05-14 10:00:00",
                            "turn": 24,
                            "state": 2,
                            "playing_state": 5,
                            "vital": 80,
                            "max_vital": 100,
                            "motivation": 5,
                            "speed": 500,
                            "stamina": 400,
                            "power": 350,
                            "guts": 300,
                            "wiz": 420,
                            "skill_point": 250,
                        },
                        "home_info": {"command_info_array": []},
                    }
                },
                {},
            )

            self.assertNotEqual(recorder.report.get("status"), "finished")

    def test_hachimi_summary_replay_rebuilds_turn_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            summary_path = Path(tmp) / "summary_events.jsonl"
            rows = [
                summary_row_for_turn(
                    1,
                    speed=100,
                    skill_point=50,
                    label="free_start",
                    index=0,
                    inventory=[],
                    shop_items=[{"shop_item_id": 1, "item_id": 10001, "coin_num": 70}],
                ),
                summary_row_for_turn(
                    1,
                    speed=100,
                    skill_point=50,
                    label="free_item_exchange",
                    index=1,
                    inventory=[{"item_id": 10001, "num": 1}],
                    shop_items=[{"shop_item_id": 1, "item_id": 10001, "coin_num": 70}],
                ),
                summary_row_for_turn(
                    2,
                    speed=130,
                    skill_point=55,
                    label="free_check_event",
                    index=2,
                    inventory=[],
                ),
                summary_row_for_turn(
                    78,
                    speed=800,
                    skill_point=900,
                    label="free_check_event",
                    index=3,
                    inventory=[],
                    rank_score=18194,
                    rank=12,
                ),
            ]
            summary_path.write_text(
                "\n".join(__import__("json").dumps(row, ensure_ascii=False) for row in rows),
                encoding="utf-8",
            )

            report = build_report_from_hachimi_summaries(summary_path, BASE_DIR, output_dir=tmp)

            self.assertEqual(report["status"], "finished")
            self.assertEqual(report["final_turn"], 78)
            self.assertGreaterEqual(len(report["turns"]), 2)
            self.assertEqual(report["turns"][0]["turn"], 1)
            self.assertEqual(report["turns"][0]["selected_action"], "train")
            self.assertEqual(report["turns"][0]["selected_training_inference"], "hachimi_summary_delta")
            self.assertEqual(report["run_context"]["trainee_card_id"], 100101)
            self.assertEqual(report["run_context"]["chara_id"], 123)
            self.assertEqual(report["run_context"]["support_card_ids"], [30086])
            self.assertEqual(report["rank_score"], 18194)
            self.assertEqual(report["rank"], 12)
            self.assertEqual(report["rank_label"], "SS")
            self.assertEqual(report["turns"][0]["server_shop_rows_raw"][0]["item_id"], 10001)
            self.assertEqual(report["turns"][0]["server_inventory_raw"][0]["item_id"], 10001)
            self.assertEqual(report["turns"][0]["item_buy_attempts"][0]["selected"][0]["item_id"], 10001)
            self.assertEqual(report["turns"][1]["item_usage_attempts"][0]["selected"][0]["item_id"], 10001)

    def test_hachimi_learning_loader_uses_rebuilt_report_for_items_and_rank(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            career_dir = runtime_root / "manual_career_logs" / "careers" / "TestCareer"
            career_dir.mkdir(parents=True, exist_ok=True)
            summary_path = career_dir / "summary_events.jsonl"
            rows = [
                summary_row_for_turn(
                    1,
                    speed=100,
                    skill_point=50,
                    label="free_start",
                    index=0,
                    inventory=[],
                    shop_items=[{"shop_item_id": 1, "item_id": 10001, "coin_num": 70}],
                ),
                summary_row_for_turn(
                    1,
                    speed=100,
                    skill_point=50,
                    label="free_item_exchange",
                    index=1,
                    inventory=[{"item_id": 10001, "num": 1}],
                    shop_items=[{"shop_item_id": 1, "item_id": 10001, "coin_num": 70}],
                ),
                summary_row_for_turn(
                    2,
                    speed=130,
                    skill_point=55,
                    label="free_check_event",
                    index=2,
                    inventory=[],
                ),
                summary_row_for_turn(
                    78,
                    speed=800,
                    skill_point=900,
                    label="free_check_event",
                    index=3,
                    inventory=[],
                    rank_score=18194,
                    rank=12,
                ),
            ]
            summary_path.write_text(
                "\n".join(__import__("json").dumps(row, ensure_ascii=False) for row in rows),
                encoding="utf-8",
            )

            samples = load_manual_hachimi_careers(runtime_root, parent_goals=None)

            self.assertEqual(len(samples), 1)
            sample = samples[0]
            self.assertEqual(sample["source"], "manual_hachimi")
            self.assertEqual(sample["rank_score"], 18194)
            self.assertEqual(sample["rank"], 12)
            self.assertEqual(sample["rank_label"], "SS")
            self.assertGreaterEqual(len(sample["actions"]), 1)
            self.assertGreaterEqual(len(sample["item_decisions"]), 2)
            item_ids = {int(row.get("item_id") or 0) for row in sample["item_decisions"]}
            self.assertIn(10001, item_ids)


if __name__ == "__main__":
    unittest.main()
