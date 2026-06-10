import json
import tempfile
import unittest
from pathlib import Path

from career_bot.career_compare import build_manual_vs_bot_report


BASE_DIR = Path(__file__).resolve().parents[1]


def summary_row(turn, *, speed, stamina, power, guts, wit, skill_point, career_key):
    return {
        "schema": "sweepy_hachimi_manual_career_summary_v1",
        "ts_ms": 1000 + turn,
        "label": "free_check_event",
        "index": turn,
        "career_key": career_key,
        "current": {
            "single_mode_chara_id": 123,
            "card_id": 100101,
            "scenario_id": 4,
            "start_time": "2026-05-19 18:00:00",
            "turn": turn,
            "vital": 80,
            "max_vital": 100,
            "motivation": 5,
            "speed": speed,
            "stamina": stamina,
            "power": power,
            "guts": guts,
            "wit": wit,
            "skill_point": skill_point,
            "race_running_style": 1,
            "succession_trained_chara_id_1": 222,
            "succession_trained_chara_id_2": 333,
        },
        "skills": {
            "bought": [],
            "tips": [],
            "disabled": [],
        },
        "supports": {
            "cards": [
                {"position": 1, "support_card_id": 30086, "limit_break_count": 4, "exp": 118185, "owner_viewer_id": 0},
                {"position": 2, "support_card_id": 20003, "limit_break_count": 4, "exp": 74990, "owner_viewer_id": 0},
                {"position": 6, "support_card_id": 30025, "limit_break_count": 4, "exp": 118185, "owner_viewer_id": 999999},
            ],
            "bonds": [{"target_id": 1, "evaluation": 90}],
            "training_levels": [],
            "guest_outings": [],
        },
        "home": {
            "commands": [
                {
                    "command_type": 1,
                    "command_id": 101,
                    "is_enable": 1,
                    "failure_rate": 0,
                    "training_partner_array": [1],
                    "tips_event_partner_array": [],
                    "params_inc_dec_info_array": [
                        {"target_type": 1, "value": 30},
                        {"target_type": 3, "value": 10},
                        {"target_type": 30, "value": 5},
                        {"target_type": 10, "value": -21},
                    ],
                }
            ],
            "disabled_command_ids": [],
        },
        "races": {
            "history": {"$items": [{"turn": 12, "program_id": 624, "running_style": 1, "result_rank": 1}]},
            "conditions": [],
            "start_info": None,
        },
        "response_status": {
            "unchecked_events": [],
        },
    }


class CareerCompareSmokeTests(unittest.TestCase):
    def test_compare_latest_manual_run_to_matching_bot_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runtime_root = tmp_path / "runtime"
            bot_dir = runtime_root / "bot_logs"
            bot_dir.mkdir(parents=True, exist_ok=True)

            bot_report = {
                "started_at": "2026-05-19T18:00:00",
                "ended_at": "2026-05-19T18:10:00",
                "preset_name": "test",
                "scenario_id": 4,
                "status": "finished",
                "final_turn": 78,
                "run_context": {
                    "trainee_card_id": 100101,
                    "support_card_ids": [30086, 20003],
                    "support_cards": [
                        {"support_card_id": 30086},
                        {"support_card_id": 20003},
                    ],
                    "friend_card_id": 30025,
                    "friend_viewer_id": 999999,
                },
                "turns": [
                    {
                        "turn": 1,
                        "stats": {"speed": 100, "stamina": 90, "power": 80, "guts": 70, "wit": 60, "skill_point": 50},
                        "selected_action": "train",
                        "current_command": {"command_type": 1, "command_id": 106},
                        "decision_understanding_summary": "preferred wit over speed on this board",
                    },
                    {
                        "turn": 2,
                        "stats": {"speed": 110, "stamina": 92, "power": 82, "guts": 72, "wit": 78, "skill_point": 54},
                        "selected_action": "rest",
                        "current_command": {"command_type": 7, "command_id": 701},
                    },
                    {
                        "turn": 78,
                        "stats": {"speed": 780, "stamina": 640, "power": 600, "guts": 500, "wit": 810, "skill_point": 2200},
                        "race_history": [{"turn": 12, "program_id": 624, "running_style": 1, "result_rank": 1}],
                    },
                ],
            }
            (bot_dir / "career_log_20260519_180000.json").write_text(json.dumps(bot_report), encoding="utf-8")

            source_root = tmp_path / "source"
            latest_dir = source_root / "_latest"
            career_key = "Compare_Manual_Run_card100101_chara123"
            career_dir = source_root / "Unlabelled runs" / career_key
            latest_dir.mkdir(parents=True, exist_ok=True)
            career_dir.mkdir(parents=True, exist_ok=True)

            latest_summary = summary_row(
                78,
                speed=860,
                stamina=700,
                power=640,
                guts=520,
                wit=780,
                skill_point=2400,
                career_key=career_key,
            )
            (latest_dir / "latest_manual_career_summary.json").write_text(json.dumps(latest_summary), encoding="utf-8")
            summary_rows = [
                summary_row(1, speed=100, stamina=90, power=80, guts=70, wit=60, skill_point=50, career_key=career_key),
                summary_row(2, speed=130, stamina=95, power=90, guts=72, wit=63, skill_point=55, career_key=career_key),
                summary_row(78, speed=860, stamina=700, power=640, guts=520, wit=780, skill_point=2400, career_key=career_key),
            ]
            (career_dir / "summary_events.jsonl").write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in summary_rows),
                encoding="utf-8",
            )

            report = build_manual_vs_bot_report(
                BASE_DIR,
                runtime_root,
                manual_log_path=runtime_root / "manual_career_logs" / "latest_manual_career_log.json",
                manual_summary_path=latest_dir / "latest_manual_career_summary.json",
            )

            self.assertIsInstance(report, dict)
            self.assertEqual(report["manual"]["run_context"]["trainee_card_id"], 100101)
            self.assertEqual(report["bot"]["run_context"]["trainee_card_id"], 100101)
            self.assertGreater(report["bot"]["match_score"], 100)
            self.assertEqual(report["comparison"]["stat_delta_manual_minus_bot"]["speed"], 80)
            self.assertGreaterEqual(report["comparison"]["different_turn_count"], 1)
            self.assertTrue(report["comparison"]["summary"])
            self.assertEqual(report["manual"]["race_quality"]["race_total"], 1)
            self.assertEqual(report["manual"]["race_quality"]["race_wins"], 1)
            self.assertEqual(report["manual"]["race_quality"]["race_losses"], 0)

    def test_compare_rejects_generic_bot_run_without_same_trainee_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            runtime_root = tmp_path / "runtime"
            bot_dir = runtime_root / "bot_logs"
            bot_dir.mkdir(parents=True, exist_ok=True)

            bot_report = {
                "started_at": "2026-05-19T18:00:00",
                "ended_at": "2026-05-19T18:10:00",
                "preset_name": "test",
                "scenario_id": 4,
                "status": "finished",
                "final_turn": 78,
                "run_context": {},
                "turns": [
                    {
                        "turn": 1,
                        "stats": {"speed": 100, "stamina": 90, "power": 80, "guts": 70, "wit": 60, "skill_point": 50},
                        "selected_action": "train",
                        "current_command": {"command_type": 1, "command_id": 106},
                    },
                    {
                        "turn": 78,
                        "stats": {"speed": 780, "stamina": 640, "power": 600, "guts": 500, "wit": 810, "skill_point": 2200},
                    },
                ],
            }
            (bot_dir / "career_log_20260519_180000.json").write_text(json.dumps(bot_report), encoding="utf-8")

            source_root = tmp_path / "source"
            latest_dir = source_root / "_latest"
            career_key = "Compare_Manual_Run_card100101_chara123"
            career_dir = source_root / "Unlabelled runs" / career_key
            latest_dir.mkdir(parents=True, exist_ok=True)
            career_dir.mkdir(parents=True, exist_ok=True)

            latest_summary = summary_row(
                78,
                speed=860,
                stamina=700,
                power=640,
                guts=520,
                wit=780,
                skill_point=2400,
                career_key=career_key,
            )
            (latest_dir / "latest_manual_career_summary.json").write_text(json.dumps(latest_summary), encoding="utf-8")
            summary_rows = [
                summary_row(1, speed=100, stamina=90, power=80, guts=70, wit=60, skill_point=50, career_key=career_key),
                summary_row(78, speed=860, stamina=700, power=640, guts=520, wit=780, skill_point=2400, career_key=career_key),
            ]
            (career_dir / "summary_events.jsonl").write_text(
                "\n".join(json.dumps(row, ensure_ascii=False) for row in summary_rows),
                encoding="utf-8",
            )

            report = build_manual_vs_bot_report(
                BASE_DIR,
                runtime_root,
                manual_log_path=runtime_root / "manual_career_logs" / "latest_manual_career_log.json",
                manual_summary_path=latest_dir / "latest_manual_career_summary.json",
            )

            self.assertIsInstance(report, dict)
            self.assertIsNone(report["bot"])
            self.assertIn("No finished bot run matched", report["comparison"]["summary"][0])
            self.assertEqual(report["manual"]["race_quality"]["race_total"], 1)


if __name__ == "__main__":
    unittest.main()
