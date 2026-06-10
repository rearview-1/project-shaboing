import gzip
import json
import tempfile
import time
import unittest
from pathlib import Path

from career_bot.learning import read_jsonl
from career_bot.storage_cleanup import (
    cap_error_snapshots,
    cleanup_stale_dumps,
    rotate_hachimi_exact_hooks,
    rotate_preset_backups,
)


class StorageCleanupTests(unittest.TestCase):
    def test_cleanup_stale_dumps_removes_only_old_dump_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "project"
            bot_logs = base / "uma_runtime" / "bot_logs"
            bot_logs.mkdir(parents=True)
            old_dump = bot_logs / "load_index_DUMP_old.json"
            fresh_dump = bot_logs / "load_index_DUMP_fresh.json"
            normal_log = bot_logs / "career_log_1.json"
            for path in (old_dump, fresh_dump, normal_log):
                path.write_text("{}", encoding="utf-8")
            old_time = time.time() - 9 * 24 * 60 * 60
            old_dump.touch()
            fresh_dump.touch()
            normal_log.touch()
            import os
            os.utime(old_dump, (old_time, old_time))

            result = cleanup_stale_dumps(base, older_than_days=7)

            self.assertEqual(result["removed_count"], 1)
            self.assertFalse(old_dump.exists())
            self.assertTrue(fresh_dump.exists())
            self.assertTrue(normal_log.exists())

    def test_rotate_preset_backups_keeps_newest_per_preset(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            backup_dir = base / "data" / "presets" / "backups"
            backup_dir.mkdir(parents=True)
            for idx in range(12):
                path = backup_dir / f"xguri parent_20260521_1200{idx:02d}.json"
                path.write_text("{}", encoding="utf-8")
                ts = time.time() + idx
                import os
                os.utime(path, (ts, ts))

            result = rotate_preset_backups(base, keep=10)

            self.assertEqual(result["removed_count"], 2)
            self.assertEqual(len(list(backup_dir.glob("xguri parent_*.json"))), 10)

    def test_rotate_hachimi_exact_hooks_gzips_live_file_and_loader_reads_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            manual_dir = Path(tmp)
            live = manual_dir / "hachimi_exact_hooks.jsonl"
            live.write_text('{"turn":1}\n{"turn":2}\n', encoding="utf-8")

            result = rotate_hachimi_exact_hooks(manual_dir)

            self.assertTrue(result["rotated"])
            self.assertEqual(live.read_text(encoding="utf-8"), "")
            archive = Path(result["archive"])
            self.assertTrue(archive.exists())
            with gzip.open(archive, "rt", encoding="utf-8") as fh:
                self.assertIn('"turn":1', fh.read())
            self.assertEqual([row["turn"] for row in read_jsonl(archive)], [1, 2])

    def test_cap_error_snapshots_strips_large_preset_fields_and_keeps_newest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "project"
            category = base / "uma_runtime" / "error_snapshots" / "skill_buy"
            category.mkdir(parents=True)
            for idx in range(7):
                path = category / f"20260521_1200{idx:02d}_turn_01_test.json"
                path.write_text(
                    json.dumps({
                        "preset": {
                            "name": "test",
                            "extra_race_list": [1, 2, 3],
                            "race_list": [1],
                            "learn_skill_list": [{"name": "A"}],
                        }
                    }),
                    encoding="utf-8",
                )
                ts = time.time() + idx
                import os
                os.utime(path, (ts, ts))

            result = cap_error_snapshots(base, keep=5)

            self.assertEqual(result["removed_count"], 2)
            remaining = sorted(category.glob("*.json"))
            self.assertEqual(len(remaining), 5)
            payload = json.loads(remaining[-1].read_text(encoding="utf-8"))
            self.assertNotIn("extra_race_list", payload["preset"])
            self.assertEqual(payload["_stripped_large_fields"]["preset"]["extra_race_list"], 3)


if __name__ == "__main__":
    unittest.main()
