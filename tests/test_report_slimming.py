import json
import tempfile
import unittest
from pathlib import Path

from career_bot.learning import load_bot_logs
from career_bot.report import new_report, write_report


class ReportSlimmingTests(unittest.TestCase):
    def test_write_report_drops_raw_fields_and_unused_enriched_rows(self):
        report = {
            "started_at": "2026-05-21T00:00:00",
            "status": "finished",
            "turns": [
                {
                    "turn": 1,
                    "server_shop_rows_raw": [{"item_id": 1}],
                    "server_skill_tips_raw": [{"skill_id": 2}],
                    "shop_rows_enriched": [{"item_id": 1}],
                    "skill_rows_enriched": [{"skill_id": 2}],
                    "bot_skill_candidates": [],
                    "bot_shop_candidates": [],
                },
                {
                    "turn": 2,
                    "skill_rows_enriched": [{"skill_id": 3}],
                    "bot_skill_candidates": [{"skill_id": 3}],
                    "shop_rows_enriched": [{"item_id": 4}],
                    "bot_shop_attempt": [{"item_id": 4}],
                },
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = write_report(report, Path(tmp))
            written = json.loads(path.read_text(encoding="utf-8"))

        turn1, turn2 = written["turns"]
        self.assertNotIn("server_shop_rows_raw", turn1)
        self.assertNotIn("server_skill_tips_raw", turn1)
        self.assertNotIn("shop_rows_enriched", turn1)
        self.assertNotIn("skill_rows_enriched", turn1)
        self.assertIn("skill_rows_enriched", turn2)
        self.assertIn("shop_rows_enriched", turn2)

    def test_new_reports_are_schema_tagged(self):
        self.assertEqual(new_report()["schema"], "sweepy_career_log_v1")

    def test_learning_loader_skips_unknown_career_log_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            bot_dir = Path(tmp) / "bot_logs"
            bot_dir.mkdir()
            (bot_dir / "career_log_1.json").write_text(
                json.dumps({"schema": "future_schema", "turns": []}),
                encoding="utf-8",
            )

            self.assertEqual(load_bot_logs(Path(tmp)), [])


if __name__ == "__main__":
    unittest.main()
