import tempfile
import unittest
from pathlib import Path

from career_bot.daily_tasks import (
    DailyAutomationConfig,
    action_config_error,
    normalize_action_steps,
    normalize_style_id,
    render_template_value,
    summarize_daily_event_status,
)


class DailyTaskStatusTests(unittest.TestCase):
    def test_status_parses_showtime_daily_legend_team_and_shop_state(self):
        load_data = {
            "common_define": {
                "daily_race_ticket_max_num": 6,
                "legend_race_ticket_max_num": 3,
                "daily_legend_race_ticket_max_num": 1,
            },
            "single_mode_difficulty_info_array": [
                {"difficulty_id": 1003, "open_difficulty_index": 3, "box_id": 4, "item_num": 2, "box_item_num": 55}
            ],
            "story_event_id": 1015,
            "story_event_roulette_coin_num": 7,
            "story_event_mission_list": [
                {"mission_id": 1, "mission_status": 0},
                {"mission_id": 2, "mission_status": 1},
                {"mission_id": 3, "mission_status": 2},
            ],
            "daily_race_playing_info": {
                "state": 0,
                "daily_race_record_array": [
                    {"daily_race_id": 1, "is_played": 1, "is_cleared": 1},
                    {"daily_race_id": 2, "is_played": 0, "is_cleared": 0, "race_name": "Moonlight Prize", "surface": 1, "distance": 1200, "distance_type": 1, "rotation": 1, "track_kind": 2, "season": 3, "weather": 1, "ground_condition": 1},
                ],
            },
            "legend_race_playing_info": {
                "state": 0,
                "group_id": 105806,
                "legend_race_record_array": [{"legend_race_id": 49, "is_played": 0, "is_cleared": 0}],
            },
            "daily_legend_race_playing_info": {
                "state": 0,
                "new_flag": 1,
                "daily_legend_race_record": [
                    {"legend_race_id": 50, "is_played": 0, "race_name": "El Condor Pasa", "surface": 1, "distance": 2400, "distance_type": 3, "rotation": 1, "track_kind": 2, "season": 3, "weather": 1, "ground_condition": 1}
                ],
            },
            "rp_info": {"current_rp": 5, "max_rp": 5},
            "team_stadium_user": {"team_class": 6, "best_point": 123456},
            "team_stadium_race_status": 0,
            "team_data_array": [
                {"trained_chara_id": i + 100, "distance_type": (i // 3) + 1, "member_id": (i % 3) + 1, "running_style": 2}
                for i in range(15)
            ],
            "limited_shop_info": {"limited_exchange_id": 3, "open_flag": 1, "appear_flag": 1, "open_count": 2},
            "menu_badge_info": {"mission_num": 1, "legend_mission_num": 2, "view_limited_mission_num": 3},
        }

        status = summarize_daily_event_status(load_data)

        self.assertTrue(status["showtime"]["available"])
        self.assertEqual([(row["difficulty_id"], row["difficulty"]) for row in status["showtime"]["difficulty_options"]], [(1003, 1), (1003, 2), (1003, 3)])
        self.assertEqual(status["showtime"]["missions_pending"], 2)
        self.assertEqual(status["showtime"]["missions_claimable"], 1)
        self.assertEqual(status["daily_race"]["unplayed_count"], 1)
        self.assertEqual(status["daily_race"]["next_daily_race_id"], 2)
        self.assertEqual(status["daily_race"]["label"], "Daily Race")
        self.assertEqual(status["daily_race"]["records"][1]["label"], "Moonlight Prize")
        self.assertIn("1200m", status["daily_race"]["records"][1]["course_summary"])
        self.assertIn("Firm", status["daily_race"]["records"][1]["course_summary"])
        self.assertEqual(status["legend_race"]["unplayed_count"], 1)
        self.assertEqual(status["legend_race"]["next_legend_race_id"], 49)
        self.assertEqual(status["legend_race"]["label"], "Legend Race")
        self.assertEqual(status["daily_legend_race"]["unplayed_count"], 1)
        self.assertEqual(status["daily_legend_race"]["next_legend_race_id"], 50)
        self.assertEqual(status["daily_legend_race"]["label"], "Daily Legend Race")
        self.assertEqual(status["daily_legend_race"]["records"][0]["label"], "El Condor Pasa")
        self.assertIn("2400m", status["daily_legend_race"]["records"][0]["course_summary"])
        self.assertIn("Medium", status["daily_legend_race"]["records"][0]["course_summary"])
        self.assertTrue(status["team_trials"]["can_race_once"])
        self.assertEqual(status["team_trials"]["lineup"][0]["style_label"], "Pace")
        self.assertTrue(status["shops"]["limited_shop"]["available"])
        self.assertEqual(status["missions"]["limited_badge_count"], 3)

    def test_style_normalization_accepts_labels_and_ids(self):
        self.assertEqual(normalize_style_id("late_surger"), 3)
        self.assertEqual(normalize_style_id("4"), 4)
        self.assertEqual(normalize_style_id("unknown"), 0)

    def test_empty_config_blocks_actions_instead_of_guessing_payloads(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "daily_automation_endpoints.json"
            cfg = DailyAutomationConfig.load(path)
            self.assertEqual(cfg.configured_shop_count(), 0)
            self.assertFalse(cfg.action("team_trials_once"))
            self.assertIn("not configured", action_config_error("team_trials_once"))

    def test_action_template_rendering_preserves_exact_value_types(self):
        rendered = render_template_value(
            {
                "trained_chara_id": "{trained_chara_id}",
                "label": "legend-{legend_race_id}",
                "nested": [{"style": "{running_style}"}],
            },
            {"trained_chara_id": 1234, "legend_race_id": 49, "running_style": 3},
        )
        self.assertEqual(rendered["trained_chara_id"], 1234)
        self.assertEqual(rendered["label"], "legend-49")
        self.assertEqual(rendered["nested"][0]["style"], 3)

    def test_normalize_action_steps_accepts_single_or_multi_step(self):
        self.assertEqual(len(normalize_action_steps({"endpoint": "x/y", "payload": {}})), 1)
        self.assertEqual(len(normalize_action_steps({"steps": [{"endpoint": "a"}, {"endpoint": "b"}]})), 2)
        self.assertEqual(normalize_action_steps({}), [])


if __name__ == "__main__":
    unittest.main()
