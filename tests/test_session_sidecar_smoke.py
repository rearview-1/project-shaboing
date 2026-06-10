import json
import tempfile
import unittest
from pathlib import Path

from career_bot.session_sidecar import (
    SIDECAR_NAME,
    SessionSidecarWatcher,
    pair_session_into_career_folder,
    read_career_sidecar,
)


class PairSessionTests(unittest.TestCase):
    def test_writes_sidecar_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            career = Path(tmp) / "career_001"
            career.mkdir()
            session = {"session_id": "wit_test", "primary_stat_target": {"stat": "wit"}}
            wrote = pair_session_into_career_folder(career, session)
            self.assertTrue(wrote)
            self.assertTrue((career / SIDECAR_NAME).exists())
            self.assertEqual(read_career_sidecar(career)["session_id"], "wit_test")

    def test_does_not_overwrite_existing_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            career = Path(tmp) / "career_001"
            career.mkdir()
            original = {"session_id": "original"}
            pair_session_into_career_folder(career, original)
            replacement = {"session_id": "replacement"}
            wrote = pair_session_into_career_folder(career, replacement)
            self.assertFalse(wrote)
            self.assertEqual(read_career_sidecar(career)["session_id"], "original")

    def test_skips_non_dict_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            career = Path(tmp) / "career_001"
            career.mkdir()
            self.assertFalse(pair_session_into_career_folder(career, None))
            self.assertFalse(pair_session_into_career_folder(career, "not-a-dict"))
            self.assertFalse((career / SIDECAR_NAME).exists())

    def test_read_returns_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(read_career_sidecar(Path(tmp)))


class WatcherProcessOnceTests(unittest.TestCase):
    """The watcher itself runs as a daemon thread in production — we exercise
    `_process_once` directly so the test is deterministic."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.hachimi_dir = self.root / "Career turn data"
        self.hachimi_dir.mkdir()
        self.session_path = self.root / "current_session.json"
        self.session_path.write_text(
            json.dumps({"session_id": "wit_test", "primary_stat_target": {"stat": "wit"}}),
            encoding="utf-8",
        )
        self.watcher = SessionSidecarWatcher(
            base_dir=self.root,
            hachimi_dirs=[self.hachimi_dir],
            session_path=self.session_path,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_processes_new_career_folder(self):
        career = self.hachimi_dir / "Mihono_2026"
        career.mkdir()
        written = self.watcher._process_once()
        self.assertEqual(written, 1)
        self.assertTrue((career / SIDECAR_NAME).exists())

    def test_skips_underscore_bookkeeping_folders(self):
        for name in ("_latest", "_debug"):
            (self.hachimi_dir / name).mkdir()
        self.watcher._process_once()
        for name in ("_latest", "_debug"):
            self.assertFalse((self.hachimi_dir / name / SIDECAR_NAME).exists())

    def test_no_session_file_writes_nothing(self):
        self.session_path.unlink()
        (self.hachimi_dir / "Career_X").mkdir()
        written = self.watcher._process_once()
        self.assertEqual(written, 0)

    def test_already_seen_career_not_reprocessed(self):
        career = self.hachimi_dir / "Mihono_2026"
        career.mkdir()
        self.watcher._process_once()
        # Delete the sidecar to confirm we don't write it again — the seen
        # set should keep us from reprocessing.
        (career / SIDECAR_NAME).unlink()
        written = self.watcher._process_once()
        self.assertEqual(written, 0)


class WatcherStatSubdirLayoutTests(unittest.TestCase):
    """The DLL now routes careers under stat-typed subdirs. The watcher
    must descend one level into SPD/STAM/PWR/GUTS/WIT/BALANCED/UNKNOWN to
    drop the sidecar inside the actual career folder rather than at the
    stat-parent level."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.hachimi_dir = self.root / "Career turn data"
        self.hachimi_dir.mkdir()
        self.session_path = self.root / "current_session.json"
        self.session_path.write_text(
            json.dumps({"session_id": "test", "primary_stat_target": {"stat": "wit"}}),
            encoding="utf-8",
        )
        self.watcher = SessionSidecarWatcher(
            base_dir=self.root,
            hachimi_dirs=[self.hachimi_dir],
            session_path=self.session_path,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_descends_into_stat_subdirs(self):
        wit_dir = self.hachimi_dir / "WIT"
        wit_dir.mkdir()
        career = wit_dir / "Mihono_wit_run"
        career.mkdir()
        written = self.watcher._process_once()
        self.assertEqual(written, 1)
        # Sidecar must land in the CAREER folder, not in the stat parent
        self.assertTrue((career / SIDECAR_NAME).exists())
        self.assertFalse((wit_dir / SIDECAR_NAME).exists())

    def test_handles_legacy_flat_alongside_stat_layout(self):
        # Legacy career at the top level
        legacy = self.hachimi_dir / "Legacy_career"
        legacy.mkdir()
        # New career under SPD/
        spd_dir = self.hachimi_dir / "SPD"
        spd_dir.mkdir()
        new_career = spd_dir / "Speed_2026"
        new_career.mkdir()
        written = self.watcher._process_once()
        self.assertEqual(written, 2)
        self.assertTrue((legacy / SIDECAR_NAME).exists())
        self.assertTrue((new_career / SIDECAR_NAME).exists())

    def test_underscore_folders_inside_stat_subdir_are_skipped(self):
        balanced = self.hachimi_dir / "BALANCED"
        balanced.mkdir()
        (balanced / "_workdir").mkdir()
        (balanced / "ActualCareer").mkdir()
        self.watcher._process_once()
        self.assertFalse((balanced / "_workdir" / SIDECAR_NAME).exists())
        self.assertTrue((balanced / "ActualCareer" / SIDECAR_NAME).exists())


class PendingIntentTests(unittest.TestCase):
    """The dashboard polls pending_intent() to decide when to show the
    run-intent modal. Returns needs_intent=True only when:
      - popup setting is enabled (default True),
      - no session is currently declared,
      - and there's at least one career folder on disk without a sidecar
        and without an embedded learning_session in its manifest.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.hachimi_dir = self.root / "Career turn data"
        self.hachimi_dir.mkdir()
        self.session_path = self.root / "current_session.json"
        # No session declared by default — most tests want needs_intent=True.
        self.watcher = SessionSidecarWatcher(
            base_dir=self.root,
            hachimi_dirs=[self.hachimi_dir],
            session_path=self.session_path,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_career_folders_means_no_intent_needed(self):
        result = self.watcher.pending_intent()
        self.assertFalse(result["needs_intent"])

    def test_career_without_sidecar_or_manifest_triggers_intent(self):
        career = self.hachimi_dir / "WIT" / "Wit_run"
        career.mkdir(parents=True)
        result = self.watcher.pending_intent()
        self.assertTrue(result["needs_intent"])
        self.assertEqual(result["career_name"], "Wit_run")

    def test_existing_sidecar_suppresses_intent(self):
        career = self.hachimi_dir / "WIT" / "Wit_run"
        career.mkdir(parents=True)
        (career / SIDECAR_NAME).write_text("{}", encoding="utf-8")
        result = self.watcher.pending_intent()
        self.assertFalse(result["needs_intent"])

    def test_embedded_manifest_session_suppresses_intent(self):
        career = self.hachimi_dir / "WIT" / "Wit_run"
        career.mkdir(parents=True)
        (career / "manifest.json").write_text(
            '{"learning_session": {"session_id": "x"}}',
            encoding="utf-8",
        )
        result = self.watcher.pending_intent()
        self.assertFalse(result["needs_intent"])

    def test_null_embedded_session_does_not_suppress_intent(self):
        career = self.hachimi_dir / "WIT" / "Wit_run"
        career.mkdir(parents=True)
        # DLL writes `"learning_session": null` when none is available — that
        # should NOT count as a real attached session.
        (career / "manifest.json").write_text(
            '{"learning_session": null}',
            encoding="utf-8",
        )
        result = self.watcher.pending_intent()
        self.assertTrue(result["needs_intent"])

    def test_session_already_declared_suppresses_intent(self):
        career = self.hachimi_dir / "WIT" / "Wit_run"
        career.mkdir(parents=True)
        self.session_path.write_text(
            json.dumps({"session_id": "active"}),
            encoding="utf-8",
        )
        result = self.watcher.pending_intent()
        self.assertFalse(result["needs_intent"])

    def test_popup_disabled_suppresses_intent(self):
        # Build a watcher rooted at a base_dir where popup_setting.json says
        # disabled — even with a fresh career, no popup should show.
        setting_dir = self.root / "data" / "learning_sessions"
        setting_dir.mkdir(parents=True)
        (setting_dir / "popup_setting.json").write_text(
            json.dumps({"enabled": False}),
            encoding="utf-8",
        )
        career = self.hachimi_dir / "WIT" / "Wit_run"
        career.mkdir(parents=True)
        result = self.watcher.pending_intent()
        self.assertFalse(result["needs_intent"])


if __name__ == "__main__":
    unittest.main()
