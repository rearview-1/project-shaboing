import json
import tempfile
import unittest
from pathlib import Path

from career_bot.team_trials_dataset import load_team_trials_dataset


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TeamTrialsDatasetTests(unittest.TestCase):
    def test_saved_team_trials_exports_normalize_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Saved races" / "Team trials"
            source.mkdir(parents=True)
            runtime = root / "runtime"

            (source.parent / "veterans.json").write_text(json.dumps([
                {
                    "trained_chara_id": 9001,
                    "card_id": 100101,
                    "rank": 15,
                    "rank_score": 15123,
                    "speed": 1000,
                    "stamina": 700,
                    "power": 900,
                    "guts": 500,
                    "wiz": 800,
                    "support_card_list": [
                        {"position": 1, "support_card_id": 30028, "limit_break_count": 4, "level": 50}
                    ],
                    "succession_chara_array": [
                        {"position_id": 10, "card_id": 100201, "rank": 13, "factor_info_array": []}
                    ],
                    "race_result_list": [
                        {"turn": 12, "program_id": 829, "running_style": 2, "result_rank": 1}
                    ],
                }
            ]), encoding="utf-8")

            payload = {
                "support_card_bonus": 1438,
                "race_start_params_array": [
                    {
                        "round": 1,
                        "race_instance_id": 610152,
                        "race_horse_data_array": [
                            {
                                "trainer_name": "Alice@TTA",
                                "team_id": 2,
                                "team_member_id": 1,
                                "card_id": 100101,
                                "chara_id": 1001,
                                "trained_chara_id": 9001,
                                "single_mode_chara_id": 9001,
                                "final_grade": 17,
                                "running_style": 2,
                                "speed": 1190,
                                "stamina": 800,
                                "pow": 1110,
                                "guts": 600,
                                "wiz": 1150,
                                "skill_array": [{"skill_id": 200242, "level": 1}],
                                "single_mode_win_count": 39,
                                "win_saddle_id_array": [1, 2, 3],
                            },
                            {
                                "trainer_name": "",
                                "team_id": 0,
                                "team_member_id": 0,
                                "card_id": 0,
                            },
                        ],
                    }
                ],
            }
            (source / "TT-20260602_200341_578.json").write_text(json.dumps(payload), encoding="utf-8")

            result = load_team_trials_dataset(PROJECT_ROOT, runtime, source_dir=source, refresh=True)

            self.assertTrue(result["success"] if "success" in result else True)
            self.assertEqual(result["team_count"], 1)
            self.assertEqual(result["player_count"], 1)
            self.assertEqual(len(result["teams"]), 1)
            team = result["teams"][0]
            self.assertEqual(team["trainer_name"], "Alice@TTA")
            self.assertEqual(team["saved_match_bonus_pct"], 14.38)
            self.assertEqual(team["support_card_bonus_pct"], 14.38)
            member = team["members_by_distance"]["sprint"][0]
            self.assertEqual(member["name"], "Special Week")
            self.assertEqual(member["rank_label"], "SS")
            self.assertEqual(member["style"], "pace")
            self.assertEqual(member["saved_match_bonus_pct"], 14.38)
            self.assertTrue(member["deck_race_bonus_available"])
            self.assertEqual(member["deck_race_bonus_pct"], 5)
            self.assertTrue(member["detail_available"]["support_cards"])
            self.assertTrue(member["detail_available"]["parents"])
            self.assertTrue(member["detail_available"]["career_races"])
            self.assertFalse((source / "team_trials_records.json").exists())
            self.assertTrue((runtime / "team_trials_dataset" / "team_trials_records.json").exists())

    def test_team_trials_query_matches_member_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "Saved races" / "Team trials"
            source.mkdir(parents=True)
            runtime = root / "runtime"
            (source / "TT-20260602_200341_578.json").write_text(json.dumps({
                "support_card_bonus": 0,
                "race_start_params_array": [
                    {
                        "round": 2,
                        "race_instance_id": 610107,
                        "race_horse_data_array": [
                            {
                                "trainer_name": "Needle",
                                "team_id": 2,
                                "team_member_id": 1,
                                "card_id": 101401,
                                "trained_chara_id": 3133,
                                "final_grade": 19,
                                "running_style": 3,
                                "speed": 1200,
                                "stamina": 700,
                                "pow": 1000,
                                "guts": 600,
                                "wiz": 1200,
                                "skill_array": [],
                            }
                        ],
                    }
                ],
            }), encoding="utf-8")

            result = load_team_trials_dataset(PROJECT_ROOT, runtime, source_dir=source, refresh=True, query="ug")

            self.assertEqual(result["filtered_count"], 1)
            self.assertEqual(result["teams"][0]["members_by_distance"]["mile"][0]["rank_label"], "UG")


if __name__ == "__main__":
    unittest.main()
