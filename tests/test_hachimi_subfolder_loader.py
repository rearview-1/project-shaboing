"""The DLL routes new careers under stat-typed subdirs
(Career turn data / SPD|STAM|PWR|GUTS|WIT|BALANCED / <career>). The loader
must scan both the new layout AND the legacy flat layout so existing
captures keep loading after the DLL update."""

import json
import tempfile
import unittest
from pathlib import Path

from career_bot.learning import load_manual_hachimi_careers


def _write_minimal_career(career_dir, turn=10):
    """Write a summary_events.jsonl that the loader will accept."""
    career_dir.mkdir(parents=True, exist_ok=True)
    row = {
        "label": "free_load",
        "current": {
            "turn": turn,
            "speed": 500,
            "stamina": 500,
            "power": 500,
            "guts": 400,
            "wit": 500,
            "skill_point": 100,
            "fans": 1000,
        },
    }
    (career_dir / "summary_events.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )


class LoaderLayoutTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self.tmp.name)
        # The loader scans `runtime_root / "manual_career_logs" / "careers"`.
        # We can put both flat and stat-typed layouts under that dir.
        self.careers_root = self.runtime_root / "manual_career_logs" / "careers"
        self.careers_root.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def test_legacy_flat_layout_loads(self):
        _write_minimal_career(self.careers_root / "Legacy_2026")
        samples = load_manual_hachimi_careers(self.runtime_root)
        self.assertEqual(len(samples), 1)

    def test_stat_typed_layout_loads(self):
        _write_minimal_career(self.careers_root / "WIT" / "Mihono_wit")
        samples = load_manual_hachimi_careers(self.runtime_root)
        self.assertEqual(len(samples), 1)

    def test_mixed_layouts_both_load(self):
        _write_minimal_career(self.careers_root / "Legacy_career")
        _write_minimal_career(self.careers_root / "SPD" / "Speed_run_1")
        _write_minimal_career(self.careers_root / "STAM" / "Stamina_run_1")
        _write_minimal_career(self.careers_root / "PWR" / "Power_run_1")
        _write_minimal_career(self.careers_root / "GUTS" / "Guts_run_1")
        _write_minimal_career(self.careers_root / "WIT" / "Wit_run_1")
        _write_minimal_career(self.careers_root / "BALANCED" / "Balanced_run_1")
        _write_minimal_career(self.careers_root / "UNKNOWN" / "Unknown_run_1")
        samples = load_manual_hachimi_careers(self.runtime_root)
        self.assertEqual(len(samples), 8)

    def test_unrelated_subfolders_are_not_treated_as_careers(self):
        # An arbitrary directory that isn't one of the stat names should
        # not be descended into — we only recognize the canonical 7.
        bogus = self.careers_root / "RandomFolder" / "career"
        _write_minimal_career(bogus)
        # The top-level glob "*/summary_events.jsonl" finds RandomFolder
        # but it has no summary_events.jsonl at that level, so 0 careers
        # should load. The inner career gets ignored because RandomFolder
        # isn't in STAT_CAREER_SUBDIRS.
        samples = load_manual_hachimi_careers(self.runtime_root)
        self.assertEqual(len(samples), 0)


if __name__ == "__main__":
    unittest.main()
