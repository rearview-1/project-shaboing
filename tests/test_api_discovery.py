import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from career_bot.api_discovery import ApiDiscoverySession, compare_captures, load_capture_entries


class ApiDiscoveryModuleTests(unittest.TestCase):
    def test_capture_contract_and_diff_strip_common_auth_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            normal = ApiDiscoverySession(tmp, "normal start")
            normal.on_api_log(
                "REQ",
                "single_mode_free/start",
                {"payload": {"viewer_id": 111, "device": 4, "card_id": 1001, "difficulty_id": 0}},
                "a1",
            )
            normal.stop()

            fuji = ApiDiscoverySession(tmp, "fuji start")
            fuji.on_api_log(
                "REQ",
                "single_mode_free/start",
                {"payload": {"viewer_id": 222, "device": 4, "card_id": 1001, "difficulty_id": 4, "boost_story_event_id": 9001}},
                "b1",
            )
            stopped = fuji.stop()

            self.assertEqual(stopped["event_count"], 1)
            self.assertEqual(stopped["contract"]["endpoint_counts"]["single_mode_free/start"], 1)

            diff = compare_captures(tmp, "normal start", "fuji start", endpoint="single_mode_free/start")
            changed_paths = {row["path"] for row in diff["diff"]["changed"]}
            added_paths = {row["path"] for row in diff["diff"]["only_right"]}
            self.assertIn("difficulty_id", changed_paths)
            self.assertIn("boost_story_event_id", added_paths)
            self.assertNotIn("viewer_id", changed_paths)
            self.assertNotIn("device", changed_paths)

    def test_endpoint_filter_keeps_capture_focused(self):
        with tempfile.TemporaryDirectory() as tmp:
            session = ApiDiscoverySession(tmp, "filtered", endpoints=["single_mode_free/start"])
            session.on_api_log("REQ", "load/index", {"payload": {"adid": ""}}, "x")
            session.on_api_log("REQ", "single_mode_free/start", {"payload": {"card_id": 1001}}, "y")
            session.stop()

            entries = load_capture_entries(tmp, "filtered")
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0]["endpoint"], "single_mode_free/start")


class ApiDiscoveryEndpointTests(unittest.TestCase):
    def setUp(self):
        self.saved_client = main.active_client
        self.saved_session = main.active_api_discovery_session

    def tearDown(self):
        main.active_client = self.saved_client
        main.active_api_discovery_session = self.saved_session

    def test_start_and_stop_endpoint_write_contract(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake_client = SimpleNamespace(on_api_log=None)
            main.active_client = fake_client
            with patch.object(main, "dev_runtime_dir", return_value=Path(tmp)):
                started = asyncio.run(main.api_discovery_start(main.ApiDiscoveryCaptureRequest(
                    label="fuji endpoint",
                    endpoints=["single_mode_free/start"],
                )))
                self.assertTrue(started["success"])
                self.assertTrue(callable(fake_client.on_api_log))

                fake_client.on_api_log(
                    "REQ",
                    "single_mode_free/start",
                    {"payload": {"viewer_id": 1, "card_id": 1001, "difficulty_id": 5}},
                    "req1",
                )
                stopped = asyncio.run(main.api_discovery_stop())

            self.assertTrue(stopped["success"])
            self.assertEqual(stopped["event_count"], 1)
            self.assertIn("single_mode_free/start", stopped["contract"]["endpoint_counts"])
            self.assertIsNone(fake_client.on_api_log)


if __name__ == "__main__":
    unittest.main()
