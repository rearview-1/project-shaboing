"""Cross-career race attempt ledger + diagnosis integration.

The ledger feeds the diagnosis layer's `chronic` flag — races with
multiple attempts and majority losses get classified more aggressively
than one-off bad-RNG losses. It does NOT gate race entry (user
explicitly rejected the skip-on-chronic-loss mechanism)."""

import json
import tempfile
import unittest
from pathlib import Path

from career_bot.postmortem_feedback import attach_diagnoses, diagnose_loss_pattern
from career_bot.race_attempt_history import (
    HISTORY_FILE_NAME,
    attempt_summary,
    chronic_loss_streak,
    load_history,
    record_race_attempt,
)


class RecordAttemptTests(unittest.TestCase):
    def test_first_win_initializes_entry(self):
        with tempfile.TemporaryDirectory() as tmp:
            record_race_attempt(tmp, program_id=11017, race_name="NHK Mile Cup", finish_rank=1, turn=35, is_g1=True)
            history = load_history(tmp)
            self.assertIn("11017", history)
            self.assertEqual(history["11017"]["attempts"], 1)
            self.assertEqual(history["11017"]["wins"], 1)
            self.assertEqual(history["11017"]["losses"], 0)
            self.assertTrue(history["11017"]["is_g1"])

    def test_subsequent_loss_increments_loss_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            record_race_attempt(tmp, 11017, "NHK Mile Cup", finish_rank=1, turn=35)
            record_race_attempt(tmp, 11017, "NHK Mile Cup", finish_rank=3, turn=35)
            record_race_attempt(tmp, 11017, "NHK Mile Cup", finish_rank=5, turn=35)
            history = load_history(tmp)
            entry = history["11017"]
            self.assertEqual(entry["attempts"], 3)
            self.assertEqual(entry["wins"], 1)
            self.assertEqual(entry["losses"], 2)
            self.assertEqual(len(entry["recent_results"]), 3)

    def test_recent_results_truncate_at_limit(self):
        from career_bot.race_attempt_history import RECENT_RESULTS_LIMIT
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(RECENT_RESULTS_LIMIT + 5):
                record_race_attempt(tmp, 11017, "NHK Mile Cup", finish_rank=2)
            history = load_history(tmp)
            self.assertEqual(len(history["11017"]["recent_results"]), RECENT_RESULTS_LIMIT)
            self.assertEqual(history["11017"]["attempts"], RECENT_RESULTS_LIMIT + 5)

    def test_file_written_to_history_file_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            record_race_attempt(tmp, 11017, "NHK Mile Cup", finish_rank=1)
            self.assertTrue((Path(tmp) / HISTORY_FILE_NAME).exists())

    def test_invalid_program_id_is_a_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            record_race_attempt(tmp, program_id=0, race_name="bogus", finish_rank=1)
            record_race_attempt(tmp, program_id="not-int", race_name="bogus", finish_rank=1)
            self.assertEqual(load_history(tmp), {})


class ChronicLossDetectionTests(unittest.TestCase):
    def test_streak_counts_consecutive_losses_from_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            # Sequence: win, loss, loss, loss → streak = 3
            record_race_attempt(tmp, 11017, "NHK", finish_rank=1)
            record_race_attempt(tmp, 11017, "NHK", finish_rank=2)
            record_race_attempt(tmp, 11017, "NHK", finish_rank=4)
            record_race_attempt(tmp, 11017, "NHK", finish_rank=3)
            history = load_history(tmp)
            self.assertEqual(chronic_loss_streak(history, 11017), 3)

    def test_streak_zero_when_latest_attempt_was_a_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            record_race_attempt(tmp, 11017, "NHK", finish_rank=2)
            record_race_attempt(tmp, 11017, "NHK", finish_rank=2)
            record_race_attempt(tmp, 11017, "NHK", finish_rank=1)
            history = load_history(tmp)
            self.assertEqual(chronic_loss_streak(history, 11017), 0)

    def test_below_min_attempts_returns_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            record_race_attempt(tmp, 11017, "NHK", finish_rank=2)
            history = load_history(tmp)
            # Default min_attempts=3, one attempt → streak=0
            self.assertEqual(chronic_loss_streak(history, 11017), 0)


class DiagnosisIntegrationTests(unittest.TestCase):
    """The diagnosis classifies the dominant loss cause and flags
    chronic races. Non-skip use case: the dashboard surfaces "you've
    lost this 6/8 times, primary cause = style_mismatch."""

    def test_stat_gap_is_dominant_when_gap_is_large(self):
        hint = {
            "worst_stat": "power",
            "worst_stat_gap": 250,
            "style_mismatch_suggested": False,
            "common_opponent_skills": [],
        }
        result = diagnose_loss_pattern(hint)
        self.assertEqual(result["primary"], "stat_gap_power")
        self.assertIn("250", result["summary"])

    def test_stat_gap_beats_style_mismatch_when_gap_is_meaningful(self):
        """Operator rule: don't switch styles, modify training. Even a
        modest 100-pt stat gap takes primary over a style mismatch — the
        bot's response should be more training on that stat, not a style
        change. style_mismatch is retained as a SECONDARY signal only."""
        hint = {
            "worst_stat": "power",
            "worst_stat_gap": 100,
            "style_mismatch_suggested": True,
            "player_style_used": "front_runner",
            "field_style_dominant": "pace_chaser",
            "common_opponent_skills": [],
        }
        result = diagnose_loss_pattern(hint)
        self.assertEqual(result["primary"], "stat_gap_power")
        self.assertIn("style_mismatch", result["secondary"])
        # style_advice is always None now — postmortem never recommends
        # a style switch.
        self.assertIsNone(result["style_advice"])

    def test_stat_gap_beats_skill_gap_when_gap_is_meaningful(self):
        """Same principle as above: a real stat deficit is the
        training-actionable cause; skill_gap takes secondary slot."""
        hint = {
            "worst_stat": "speed",
            "worst_stat_gap": 50,
            "style_mismatch_suggested": False,
            "common_opponent_skills": [{"skill_id": 200391, "field_count": 8}],
        }
        result = diagnose_loss_pattern(hint)
        self.assertEqual(result["primary"], "stat_gap_speed")
        self.assertIn("skill_gap", result["secondary"])
        self.assertIn(200391, result["missing_skill_ids"])

    def test_style_mismatch_never_emits_style_advice(self):
        """When stat gaps are below the 30-pt threshold and style_mismatch
        IS the primary signal, the diagnosis still returns
        style_advice=None per the no-style-switch rule."""
        hint = {
            "worst_stat": "power",
            "worst_stat_gap": 5,  # below 30 threshold → no stat_gap candidate
            "style_mismatch_suggested": True,
            "player_style_used": "front_runner",
            "field_style_dominant": "pace_chaser",
            "common_opponent_skills": [],
        }
        result = diagnose_loss_pattern(hint)
        self.assertEqual(result["primary"], "style_mismatch")
        self.assertIsNone(result["style_advice"])

    def test_chronic_flag_set_when_history_shows_majority_losses(self):
        hint = {
            "worst_stat": None,
            "worst_stat_gap": 0,
            "style_mismatch_suggested": False,
            "common_opponent_skills": [],
        }
        history_entry = {"attempts": 5, "wins": 1, "losses": 4}
        result = diagnose_loss_pattern(hint, history_entry=history_entry)
        self.assertTrue(result["chronic"])
        # Low-signal hint + chronic history → low_confidence verdict.
        self.assertEqual(result["primary"], "low_confidence")

    def test_attach_diagnoses_writes_diagnosis_onto_each_hint(self):
        hints = {
            11017: {
                "worst_stat": "power",
                "worst_stat_gap": 220,
                "style_mismatch_suggested": False,
                "common_opponent_skills": [],
            },
            11034: {
                "worst_stat": "guts",
                "worst_stat_gap": 280,
                "style_mismatch_suggested": False,
                "common_opponent_skills": [],
            },
        }
        history = {"11017": {"attempts": 4, "wins": 0, "losses": 4}}
        attach_diagnoses(hints, history)
        self.assertIn("diagnosis", hints[11017])
        self.assertIn("diagnosis", hints[11034])
        self.assertTrue(hints[11017]["diagnosis"]["chronic"])
        # 11034 has no history → not chronic.
        self.assertFalse(hints[11034]["diagnosis"]["chronic"])


class AttemptSummaryTests(unittest.TestCase):
    def test_summary_returns_win_rate(self):
        with tempfile.TemporaryDirectory() as tmp:
            record_race_attempt(tmp, 11017, "NHK", finish_rank=1)
            record_race_attempt(tmp, 11017, "NHK", finish_rank=2)
            record_race_attempt(tmp, 11017, "NHK", finish_rank=3)
            history = load_history(tmp)
            summary = attempt_summary(history, 11017)
            self.assertEqual(summary["attempts"], 3)
            self.assertEqual(summary["wins"], 1)
            self.assertEqual(summary["losses"], 2)
            self.assertAlmostEqual(summary["win_rate"], 1 / 3, places=3)

    def test_summary_none_when_not_tracked(self):
        self.assertIsNone(attempt_summary({}, 11017))


if __name__ == "__main__":
    unittest.main()
