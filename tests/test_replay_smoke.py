import unittest
from pathlib import Path

import main
from career_bot.replay import RecordedClient, ReplayMismatchError, load_career_report


ROOT = Path(__file__).resolve().parent.parent
FIXTURE = ROOT / "tests" / "fixtures" / "api_trace_minimal.jsonl"
RUNTIME_LOG = ROOT.parent / "uma_runtime" / "bot_logs" / "career_log_20260511_002747.json"


class ReplaySmokeTests(unittest.TestCase):
    def setUp(self):
        self.saved = {
            "active_client": main.active_client,
            "active_account": main.active_account,
            "active_dashboard_data": main.active_dashboard_data,
            "active_start_state": dict(main.active_start_state),
            "active_start_debug": dict(main.active_start_debug),
            "active_parent_cards": dict(main.active_parent_cards),
            "active_parent_rank_points": dict(main.active_parent_rank_points),
            "active_selection": dict(main.active_selection),
        }
        main.active_client = None
        main.active_account = None
        main.active_dashboard_data = None
        main.active_start_state = {}
        main.active_start_debug = {}
        main.active_parent_cards = {}
        main.active_parent_rank_points = {}

    def tearDown(self):
        main.active_client = self.saved["active_client"]
        main.active_account = self.saved["active_account"]
        main.active_dashboard_data = self.saved["active_dashboard_data"]
        main.active_start_state = self.saved["active_start_state"]
        main.active_start_debug = self.saved["active_start_debug"]
        main.active_parent_cards = self.saved["active_parent_cards"]
        main.active_parent_rank_points = self.saved["active_parent_rank_points"]
        main.active_selection = self.saved["active_selection"]

    def test_recorded_trace_replays_dashboard_refresh(self):
        client = RecordedClient.from_jsonl(FIXTURE)
        main.active_client = client

        result = main.refresh_live_start_state()

        self.assertTrue(result["success"])
        self.assertFalse(result["career_active"])
        dashboard = result["dashboard"]
        self.assertEqual(len(dashboard["decks"]), 1)
        self.assertEqual(len(dashboard["decks"][0]["cards"]), 5)
        self.assertEqual(len(dashboard["parents"]), 2)
        self.assertEqual(main.active_start_state["tp_info"]["current_tp"], 30)

    def test_recorded_trace_detects_endpoint_desync(self):
        client = RecordedClient.from_jsonl(FIXTURE)

        with self.assertRaises(ReplayMismatchError):
            client.call("pre_single_mode/index", {})

    def test_runtime_career_report_is_replay_parseable_when_present(self):
        if not RUNTIME_LOG.exists():
            self.skipTest(f"runtime career report not present: {RUNTIME_LOG}")

        summary = load_career_report(RUNTIME_LOG)

        self.assertGreaterEqual(summary["turn_count"], 1)
        self.assertGreaterEqual(summary["final_turn"], summary["last_turn"])
        self.assertGreaterEqual(summary["decision_count"], 1)
        self.assertEqual(summary["scenario_id"], 4)


if __name__ == "__main__":
    unittest.main()
