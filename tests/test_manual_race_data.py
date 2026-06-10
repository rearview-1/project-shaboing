"""Per-(trainee, race) lookup built from manual hachimi captures.

The bot now has a `manual_race_data.json` lookup it can consult to
inform training and skill decisions for the current trainee + race.
These tests pin the extraction shape and the runtime accessors.
"""

import json
import tempfile
import unittest
from pathlib import Path

from career_bot.manual_race_data import (
    _extract_card_id_from_dirname,
    extract_manual_race_data,
    load_manual_race_data,
    lookup_race,
    write_manual_race_data,
)


def _make_capture(tmp_root, name, race_history, turn_snapshots):
    """Create a minimal hachimi capture skeleton at tmp_root/name/."""
    career_dir = tmp_root / name
    career_dir.mkdir(parents=True, exist_ok=True)
    # Top-level summary with race history
    summary = {
        "races": {
            "history": {"$items": race_history},
        },
    }
    (career_dir / "latest_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    # Per-turn snapshots
    turns_dir = career_dir / "turns"
    turns_dir.mkdir(exist_ok=True)
    for turn, snapshot in turn_snapshots.items():
        turn_dir = turns_dir / f"turn_{int(turn):02d}"
        turn_dir.mkdir(exist_ok=True)
        (turn_dir / "latest_summary.json").write_text(json.dumps(snapshot), encoding="utf-8")
    return career_dir


class CardIdExtractionTests(unittest.TestCase):
    def test_extracts_card_id_from_standard_dirname(self):
        name = "Sakura_Bakushin_O_used_at_2026-05-22_04_51_53_card104101_chara861"
        self.assertEqual(_extract_card_id_from_dirname(name), 104101)

    def test_returns_none_for_unrecognized_dirname(self):
        self.assertIsNone(_extract_card_id_from_dirname("random_folder_no_card"))


class ExtractionTests(unittest.TestCase):
    def test_full_career_with_wins_produces_aggregates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            race_history = [
                {"turn": 12, "program_id": 100, "result_rank": 1, "running_style": 2},
                {"turn": 24, "program_id": 100, "result_rank": 1, "running_style": 2},
                {"turn": 36, "program_id": 100, "result_rank": 1, "running_style": 2},
            ]
            turn_snapshots = {
                12: {
                    "current": {"speed": 400, "stamina": 200, "power": 350, "guts": 250, "wit": 300, "skill_point": 500},
                    "skills": {"bought": {"$items": [{"skill_id": 100411, "level": 4}]}},
                },
                24: {
                    "current": {"speed": 600, "stamina": 250, "power": 500, "guts": 350, "wit": 400, "skill_point": 800},
                    "skills": {"bought": {"$items": [{"skill_id": 100411, "level": 4}]}},
                },
                36: {
                    "current": {"speed": 900, "stamina": 300, "power": 700, "guts": 600, "wit": 600, "skill_point": 1200},
                    "skills": {"bought": {"$items": [{"skill_id": 100411, "level": 4}]}},
                },
            }
            _make_capture(root, "Bakushin_O_card104101_chara1", race_history, turn_snapshots)
            data = extract_manual_race_data(root)
            self.assertIn("104101", data)
            self.assertIn("100", data["104101"])
            entry = data["104101"]["100"]
            self.assertEqual(entry["wins"], 3)
            self.assertEqual(entry["losses"], 0)
            # Median winning speed across the 3 wins (400, 600, 900) = 600
            self.assertEqual(entry["median_winning_stats"]["speed"], 600)
            # Style 2 always
            self.assertEqual(entry["winning_running_styles"], {2: 3})
            # 1 skill in every winning attempt
            self.assertEqual(entry["median_winning_skill_count"], 1)
            # Top winning skill is the unique (100411)
            self.assertEqual(entry["top_winning_skills"][0]["skill_id"], 100411)
            self.assertEqual(entry["top_winning_skills"][0]["win_count"], 3)

    def test_losses_dont_pollute_winning_aggregates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            race_history = [
                {"turn": 12, "program_id": 200, "result_rank": 1, "running_style": 1},
                {"turn": 24, "program_id": 200, "result_rank": 5, "running_style": 1},  # loss
            ]
            turn_snapshots = {
                12: {"current": {"speed": 800, "stamina": 400}, "skills": {"bought": {"$items": []}}},
                24: {"current": {"speed": 300, "stamina": 100}, "skills": {"bought": {"$items": []}}},
            }
            _make_capture(root, "Test_card999999_chara1", race_history, turn_snapshots)
            data = extract_manual_race_data(root)
            entry = data["999999"]["200"]
            self.assertEqual(entry["wins"], 1)
            self.assertEqual(entry["losses"], 1)
            # Only the winning stat (800) feeds the median
            self.assertEqual(entry["median_winning_stats"]["speed"], 800)

    def test_partial_capture_still_produces_useful_data(self):
        """A capture with only 2 race turns and no late-career data should
        still emit aggregates for those 2 races. Partial captures are
        valuable per-race even if the career didn't finish."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            race_history = [
                {"turn": 12, "program_id": 100, "result_rank": 1, "running_style": 2},
            ]
            turn_snapshots = {
                12: {"current": {"speed": 400, "stamina": 200}, "skills": {"bought": {"$items": []}}},
            }
            _make_capture(root, "Partial_card104101_chara99", race_history, turn_snapshots)
            data = extract_manual_race_data(root)
            self.assertIn("104101", data)
            self.assertEqual(data["104101"]["100"]["wins"], 1)


class PersistenceTests(unittest.TestCase):
    def test_round_trip_write_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            sample_data = {
                "104101": {
                    "100": {
                        "race_name": "Test Race",
                        "wins": 3, "losses": 0,
                        "median_winning_stats": {"speed": 800, "stamina": 200},
                        "median_winning_skill_count": 1,
                        "top_winning_skills": [{"skill_id": 100411, "win_count": 3}],
                        "winning_running_styles": {"2": 3},
                        "win_attempts": [],
                    },
                },
            }
            write_manual_race_data(tmp, sample_data)
            loaded = load_manual_race_data(tmp)
            self.assertEqual(loaded, sample_data)

    def test_load_missing_file_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_manual_race_data(tmp), {})


class LookupTests(unittest.TestCase):
    def test_lookup_finds_entry(self):
        data = {
            "104101": {"100": {"race_name": "Test", "wins": 1, "losses": 0}},
        }
        result = lookup_race(data, 104101, 100)
        self.assertIsNotNone(result)
        self.assertEqual(result["wins"], 1)

    def test_lookup_returns_none_when_card_missing(self):
        self.assertIsNone(lookup_race({}, 104101, 100))

    def test_lookup_handles_string_or_int_keys(self):
        data = {"104101": {"100": {"race_name": "X"}}}
        self.assertIsNotNone(lookup_race(data, 104101, 100))
        self.assertIsNotNone(lookup_race(data, "104101", "100"))


class CrossTraineeAttributeAggregationTests(unittest.TestCase):
    """When the current trainee has no manual data, the bot should fall
    back to aggregating across trainees that match by attributes (running
    style at minimum). Recovery-unique source trainees must be excluded
    from stamina aggregation when the current trainee lacks the unique."""

    def _build_data(self):
        # Three trainees: two non-recovery-unique, one with recovery unique.
        return {
            "200000": {  # Non-recovery trainee A, Front Runner wins
                "100": {
                    "wins": 5, "losses": 0,
                    "median_winning_stats": {"speed": 1000, "stamina": 500, "power": 800, "guts": 400, "wit": 700},
                    "winning_running_styles": {"1": 5},
                    "race_name": "X",
                },
            },
            "200001": {  # Non-recovery trainee B, Front Runner wins
                "100": {
                    "wins": 3, "losses": 0,
                    "median_winning_stats": {"speed": 1100, "stamina": 600, "power": 900, "guts": 450, "wit": 750},
                    "winning_running_styles": {"1": 3},
                    "race_name": "X",
                },
            },
            # Super Creek (has recovery unique) — should be excluded for stamina
            "104501": {
                "200": {
                    "wins": 4, "losses": 0,
                    "median_winning_stats": {"speed": 900, "stamina": 1200, "power": 700, "guts": 350, "wit": 650},
                    "winning_running_styles": {"1": 4},
                    "race_name": "Y",
                },
            },
        }

    def test_cross_trainee_aggregates_matching_style(self):
        from career_bot.manual_race_data import aggregate_user_targets_by_attributes
        data = self._build_data()
        # New trainee (no manual data), Front Runner — should aggregate from cards 200000+200001
        targets = aggregate_user_targets_by_attributes(
            data, style="front_runner", current_trainee_card_id=999999,
            current_trainee_has_recovery_unique=False, min_wins=3,
        )
        # Should have non-empty result with speed/power/wit medians from 200000 + 200001 + 104501
        self.assertGreater(len(targets), 0)
        self.assertIn("speed", targets)

    def test_recovery_unique_source_excluded_for_stamina(self):
        """A Super Creek win at stamina 1200 should NOT push another
        trainee's stamina target up — Super Creek's unique substitutes
        for raw stamina."""
        from career_bot.manual_race_data import aggregate_user_targets_by_attributes
        data = self._build_data()
        # New non-recovery trainee, Front Runner
        targets = aggregate_user_targets_by_attributes(
            data, style="front_runner", current_trainee_card_id=999999,
            current_trainee_has_recovery_unique=False, min_wins=3,
        )
        # Stamina median should come from 200000 (500) and 200001 (600), NOT include 104501 (1200)
        # Median of [500x5, 600x3] = 500 (since 500 dominates)
        self.assertLess(targets["stamina"], 700,
                        msg=f"stamina target {targets['stamina']} is too high — Super Creek wins should have been excluded")

    def test_recovery_unique_source_included_when_current_also_has_unique(self):
        """When current trainee ALSO has a stamina-recovery unique, the
        Super Creek wins should be included in stamina aggregation —
        verify by comparing aggregation WITH vs WITHOUT the flag."""
        from career_bot.manual_race_data import aggregate_user_targets_by_attributes
        data = self._build_data()
        without_unique = aggregate_user_targets_by_attributes(
            data, style="front_runner", current_trainee_card_id=999999,
            current_trainee_has_recovery_unique=False, min_wins=3,
        )
        with_unique = aggregate_user_targets_by_attributes(
            data, style="front_runner", current_trainee_card_id=999999,
            current_trainee_has_recovery_unique=True, min_wins=3,
        )
        # When including recovery-unique source wins, stamina median should
        # be at least as high as when excluding (104501 had stamina 1200)
        self.assertGreaterEqual(
            with_unique["stamina"], without_unique["stamina"],
            msg=f"with_unique stamina ({with_unique['stamina']}) should be >= without_unique ({without_unique['stamina']})"
        )

    def test_style_filter_excludes_non_matching_winning_styles(self):
        """A trainee whose wins were all Late Surger shouldn't contribute
        to a Front Runner trainee's aggregation."""
        from career_bot.manual_race_data import aggregate_user_targets_by_attributes
        data = {
            "200000": {
                "100": {
                    "wins": 5, "losses": 0,
                    "median_winning_stats": {"speed": 1000},
                    "winning_running_styles": {"3": 5},  # all Late Surger wins
                    "race_name": "X",
                },
            },
        }
        # Looking for Front Runner targets
        targets = aggregate_user_targets_by_attributes(
            data, style="front_runner", current_trainee_card_id=999999, min_wins=3,
        )
        self.assertEqual(targets, {})

    def test_returns_empty_when_under_min_wins(self):
        from career_bot.manual_race_data import aggregate_user_targets_by_attributes
        data = {
            "200000": {
                "100": {
                    "wins": 1, "losses": 0,
                    "median_winning_stats": {"speed": 1000},
                    "winning_running_styles": {"1": 1},
                    "race_name": "X",
                },
            },
        }
        targets = aggregate_user_targets_by_attributes(
            data, style="front_runner", min_wins=5,
        )
        self.assertEqual(targets, {})


class StaminaRecoveryUniqueListTests(unittest.TestCase):
    def test_known_recovery_uniques_are_listed(self):
        from career_bot.manual_race_data import STAMINA_RECOVERY_UNIQUE_CARDS
        # Spot-check a few canonical entries.
        self.assertIn(104501, STAMINA_RECOVERY_UNIQUE_CARDS)  # Super Creek
        self.assertIn(103201, STAMINA_RECOVERY_UNIQUE_CARDS)  # Agnes Tachyon
        self.assertIn(107401, STAMINA_RECOVERY_UNIQUE_CARDS)  # Mejiro Bright
        # Mihono Bourbon Valentine (102602) is NOT recovery
        self.assertNotIn(102602, STAMINA_RECOVERY_UNIQUE_CARDS)


if __name__ == "__main__":
    unittest.main()
