import json
import tempfile
import unittest
from pathlib import Path

from tools.export_hakuraku_races import BACKING, export_races, extract_races, horseact_race_record


BASE_DIR = Path(__file__).resolve().parents[1]


def horse_rows():
    return [
        {
            "viewer_id": 1,
            "card_id": 100101,
            "chara_id": 1001,
            "frame_order": 1,
            "speed": 500,
            "stamina": 500,
            "pow": 500,
            "guts": 500,
            "wiz": 500,
            "motivation": 5,
            "proper_distance_long": 7,
            "proper_ground_turf": 7,
            "race_result_array": [],
            "win_saddle_id_array": [],
        },
        {
            "viewer_id": 0,
            "card_id": 100201,
            "chara_id": 1002,
            "frame_order": 2,
            "speed": 450,
            "stamina": 450,
            "pow": 450,
            "guts": 450,
            "wiz": 450,
            "motivation": 5,
            "proper_distance_long": 7,
            "proper_ground_turf": 7,
            "race_result_array": [],
            "win_saddle_id_array": [],
        },
    ]


def trace_row(endpoint, direction, req_id, payload=None, data=None, ts=1.0):
    body = {}
    if payload is not None:
        body["payload"] = payload
    if data is not None:
        body["data"] = data
    return {
        "ts": ts,
        "endpoint": endpoint,
        "direction": direction,
        "req_id": req_id,
        "data": body,
    }


def race_start_info():
    return {
        "program_id": 168,
        "is_short": True,
        "random_seed": 123,
        "season": 1,
        "weather": 1,
        "ground_condition": 1,
        "race_horse_data": horse_rows(),
    }


class HakurakuExportSmokeTests(unittest.TestCase):
    def test_horseact_race_record_uses_race_instance_ids_not_program_ids(self):
        record = horseact_race_record({
            "race_result_array": [
                {"program_id": 168, "result_rank": 1},
                {"program_id": 630, "result_rank": 2},
            ],
            "win_saddle_id_array": [10],
        })

        self.assertFalse(record[BACKING("IsUndefeated")])
        self.assertEqual(record[BACKING("WinRaceInstanceIdList")], [10])
        self.assertEqual(record["_raceInstanceIdList"], [101501, 305101])

    def test_empty_horseact_race_record_is_not_marked_undefeated(self):
        record = horseact_race_record({"race_result_array": [], "win_saddle_id_array": []})

        self.assertFalse(record[BACKING("IsUndefeated")])

    def test_alarm_clock_retry_exports_failed_and_retried_attempts(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            trace_path = tmp / "payloads.jsonl"
            career_log = tmp / "career.json"
            out_dir = tmp / "out"
            rows = [
                trace_row("single_mode_free/race_entry", "REQ", "1", {"current_turn": 24, "program_id": 168}),
                trace_row("single_mode_free/race_entry", "RES", "1", data={"race_start_info": race_start_info()}),
                trace_row("single_mode_free/race_start", "REQ", "2", {"current_turn": 24}),
                trace_row("single_mode_free/race_start", "RES", "2", data={"race_start_info": race_start_info(), "race_scenario": "FIRST_ATTEMPT"}),
                trace_row("single_mode_free/race_end", "REQ", "3", {"current_turn": 24}),
                trace_row(
                    "single_mode_free/race_end",
                    "RES",
                    "3",
                    data={
                        "race_reward_info": {"result_rank": 2},
                        "race_history": [{"turn": 24, "program_id": 168, "result_rank": 2}],
                    },
                ),
                trace_row("single_mode_free/continue", "REQ", "4", {"current_turn": 24, "continue_type": 1}),
                trace_row("single_mode_free/continue", "RES", "4", data={"race_start_info": race_start_info()}),
                trace_row("single_mode_free/race_start", "REQ", "5", {"current_turn": 24}),
                trace_row("single_mode_free/race_start", "RES", "5", data={"race_start_info": race_start_info(), "race_scenario": "SECOND_ATTEMPT"}),
                trace_row("single_mode_free/race_end", "REQ", "6", {"current_turn": 24}),
                trace_row(
                    "single_mode_free/race_end",
                    "RES",
                    "6",
                    data={
                        "race_reward_info": {"result_rank": 1},
                        "race_history": [{"turn": 24, "program_id": 168, "result_rank": 1}],
                    },
                ),
            ]
            trace_path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")
            career_log.write_text(json.dumps({
                "started_at": None,
                "ended_at": None,
                "turns": [
                    {
                        "turn": 24,
                        "events": [
                            {
                                "event": "race_attempt_result",
                                "turn": 24,
                                "program_id": 168,
                                "attempt": 1,
                                "continue_attempt": 1,
                                "continue_type": 1,
                                "continued_with": "alarm_clock",
                                "finish_rank": 2,
                                "won": False,
                                "status": "lost",
                                "is_g1": True,
                                "label": "LOST #2 -> retried with alarm clock",
                            },
                            {
                                "event": "race_result",
                                "turn": 24,
                                "program_id": 168,
                                "finish_rank": 1,
                                "won": True,
                                "status": "won",
                                "is_g1": True,
                                "continued": True,
                                "continue_attempts": 1,
                                "continue_resources": ["alarm_clock"],
                                "continue_failed_ranks": [2],
                                "label": "WON #1 after 1 alarm clock",
                            },
                        ],
                    }
                ],
            }), encoding="utf-8")

            extracted = extract_races(trace_path)
            self.assertEqual([row["race_attempt_index"] for row in extracted], [1, 2])
            self.assertEqual([row["finish_rank"] for row in extracted], [2, 1])

            manifest = export_races(BASE_DIR, career_log=career_log, trace_path=trace_path, output_dir=out_dir)

            self.assertEqual(manifest["total_exported"], 2)
            self.assertEqual([row["attempt"] for row in manifest["races"]], [1, 2])
            self.assertEqual([row["finish_rank"] for row in manifest["races"]], [2, 1])
            self.assertEqual(manifest["races"][0]["continued_with"], "alarm_clock")
            self.assertEqual(manifest["races"][1]["continue_failed_ranks"], [2])
            self.assertEqual(len(manifest["g1_losses"]), 1)
            files = sorted((out_dir / "all").glob("*.json"))
            self.assertEqual(len(files), 2)
            self.assertTrue(any("attempt1" in path.name and "lost_rank2" in path.name for path in files))
            self.assertTrue(any("attempt2" in path.name and "won_rank1" in path.name for path in files))


if __name__ == "__main__":
    unittest.main()
