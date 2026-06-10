"""Hard per-race stat targets derived from postmortem losses.

The contract: when a race is lost, the next career's target for each
gap stat = effective_player_stats + gap + cushion. Stats the player
already led on stay at the observed level. Across multiple losses,
per-stat target = max across losses (stricter careers tighten the bar).
"""

import json
import unittest
from pathlib import Path
import tempfile

from career_bot.race_thresholds import (
    DEFAULT_CUSHION,
    build_race_thresholds,
    build_and_write_race_thresholds,
    load_race_thresholds,
    write_race_thresholds,
)


def _loss(program_id, effective, gaps, race_name="Test G1", primary=None):
    return {
        "program_id": program_id,
        "race_name": race_name,
        "effective_player_stats": effective,
        "field_max_gap_over_player": gaps,
        "primary_gap_stat": primary or max(gaps, key=gaps.get) if gaps else None,
    }


def _postmortem(losses, career_log="logs/career_a.json"):
    return {"career_log": career_log, "g1_losses": losses}


class BuildRaceThresholdsTests(unittest.TestCase):
    def test_single_loss_raises_target_on_gap_stat_only(self):
        """Lost Tenno Sho with effective stamina=984, gap=+22 stamina.
        Target stamina must be 984 + 22 + cushion. Other stats had
        negative gaps (player led) — they stay at observed effective."""
        loss = _loss(
            program_id=4,
            effective={"speed": 1046, "stamina": 984, "power": 1090, "guts": 861, "wit": 855},
            gaps={"speed": -239, "stamina": 22, "power": -190, "guts": -20, "wit": -5},
            race_name="Tenno Sho (Spring)",
        )
        thresholds = build_race_thresholds([_postmortem([loss])])
        self.assertIn(4, thresholds)
        entry = thresholds[4]
        self.assertEqual(entry["loss_count"], 1)
        self.assertEqual(entry["race_name"], "Tenno Sho (Spring)")
        target = entry["target_effective"]
        # Stamina was the gap — raise it by gap + cushion.
        self.assertEqual(target["stamina"], 984 + 22 + DEFAULT_CUSHION)
        # Player led on the rest — keep observed effective as floor.
        self.assertEqual(target["speed"], 1046)
        self.assertEqual(target["power"], 1090)
        self.assertEqual(target["guts"], 861)
        self.assertEqual(target["wit"], 855)

    def test_multiple_losses_take_max_target_per_stat(self):
        """Two losses on the same race with different stat profiles.
        Per-stat target = max across losses."""
        loss_1 = _loss(
            program_id=10,
            effective={"speed": 900, "stamina": 600, "power": 700, "guts": 600, "wit": 600},
            gaps={"speed": 0, "stamina": 50, "power": 0, "guts": 0, "wit": 0},
        )
        loss_2 = _loss(
            program_id=10,
            effective={"speed": 800, "stamina": 700, "power": 700, "guts": 600, "wit": 600},
            gaps={"speed": 100, "stamina": 0, "power": 0, "guts": 0, "wit": 0},
        )
        thresholds = build_race_thresholds([_postmortem([loss_1, loss_2])])
        entry = thresholds[10]
        self.assertEqual(entry["loss_count"], 2)
        # Stamina: loss 1 → 600 + 50 + cushion. Loss 2 → 700 (no gap).
        # Max → loss 1's gap-adjusted target.
        self.assertEqual(entry["target_effective"]["stamina"], 600 + 50 + DEFAULT_CUSHION)
        # Speed: loss 1 → 900 (no gap), loss 2 → 800 + 100 + cushion.
        # Max → 900 (the loss-1 floor is higher than loss-2's bumped value
        # because the player was at 900 effective on loss 1).
        # 800 + 100 + 50 = 950, vs 900 → 950 wins.
        self.assertEqual(entry["target_effective"]["speed"], 800 + 100 + DEFAULT_CUSHION)

    def test_loss_with_no_positive_gaps_flags_non_stat_cause(self):
        """If we lost while leading on every stat, stat-bumping won't
        help. Threshold targets equal the observed effective (no upward
        pressure), and `no_stat_gap_loss_count` increments so other
        levers can pick up the escalation."""
        loss = _loss(
            program_id=5,
            effective={"speed": 1000, "stamina": 1000, "power": 1000, "guts": 1000, "wit": 1000},
            gaps={"speed": -50, "stamina": -50, "power": -50, "guts": -50, "wit": -50},
            primary="speed",
        )
        thresholds = build_race_thresholds([_postmortem([loss])])
        entry = thresholds[5]
        self.assertEqual(entry["no_stat_gap_loss_count"], 1)
        for stat in ("speed", "stamina", "power", "guts", "wit"):
            self.assertEqual(entry["target_effective"][stat], 1000)

    def test_persists_and_loads_round_trip(self):
        loss = _loss(
            program_id=42,
            effective={"speed": 800, "stamina": 700, "power": 600, "guts": 500, "wit": 400},
            gaps={"speed": 100, "stamina": 0, "power": 0, "guts": 0, "wit": 0},
        )
        with tempfile.TemporaryDirectory() as tmp:
            thresholds = build_race_thresholds([_postmortem([loss])])
            path = write_race_thresholds(tmp, thresholds)
            self.assertTrue(path.exists())
            loaded = load_race_thresholds(tmp)
            self.assertIn(42, loaded)
            self.assertEqual(loaded[42]["target_effective"]["speed"], 800 + 100 + DEFAULT_CUSHION)

    def test_load_returns_empty_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_race_thresholds(tmp), {})

    def test_load_returns_empty_when_file_malformed(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "race_thresholds.json").write_text("not json", encoding="utf-8")
            self.assertEqual(load_race_thresholds(tmp), {})

    def test_no_program_id_loss_is_skipped(self):
        loss = _loss(
            program_id=0,
            effective={"speed": 800, "stamina": 700, "power": 600, "guts": 500, "wit": 400},
            gaps={"speed": 100, "stamina": 0, "power": 0, "guts": 0, "wit": 0},
        )
        thresholds = build_race_thresholds([_postmortem([loss])])
        self.assertEqual(thresholds, {})

    def test_build_and_write_reads_from_postmortems_dir(self):
        """The orchestration helper should walk the postmortems
        directory and produce a usable thresholds file."""
        with tempfile.TemporaryDirectory() as tmp:
            postmortem_dir = Path(tmp) / "postmortems"
            postmortem_dir.mkdir()
            loss = _loss(
                program_id=4,
                effective={"speed": 1000, "stamina": 900, "power": 800, "guts": 700, "wit": 600},
                gaps={"speed": 0, "stamina": 80, "power": 0, "guts": 0, "wit": 0},
                race_name="Tenno Sho (Spring)",
            )
            (postmortem_dir / "postmortem_20260519_160807.json").write_text(
                json.dumps({"g1_losses": [loss]}), encoding="utf-8"
            )
            path, thresholds = build_and_write_race_thresholds(tmp)
            self.assertTrue(path.exists())
            self.assertIn(4, thresholds)
            self.assertEqual(thresholds[4]["target_effective"]["stamina"], 900 + 80 + DEFAULT_CUSHION)


class StatProjectionTests(unittest.TestCase):
    def test_projects_linearly_with_career_end_bonus(self):
        """At turn 39 with speed=500, projected at turn 78 = 500*2 + 400 = 1400."""
        from career_bot.race_thresholds import project_effective_stats_at_turn
        projected = project_effective_stats_at_turn(
            {"speed": 500, "stamina": 400}, current_turn=39, target_turn=78
        )
        self.assertEqual(projected["speed"], 1400)
        self.assertEqual(projected["stamina"], 1200)

    def test_projects_to_same_turn_returns_value_plus_bonus(self):
        from career_bot.race_thresholds import project_effective_stats_at_turn
        projected = project_effective_stats_at_turn(
            {"speed": 600}, current_turn=50, target_turn=50
        )
        self.assertEqual(projected["speed"], 1000)


class RaceDeficitTests(unittest.TestCase):
    def test_deficit_only_includes_races_with_threshold(self):
        from career_bot.race_thresholds import compute_race_deficits
        thresholds = {
            4: {
                "race_name": "Tenno Sho (Spring)",
                "target_effective": {"speed": 1066, "stamina": 1112, "power": 1090, "guts": 971, "wit": 974},
            }
        }
        scheduled = [
            {"program_id": 4, "turn": 50},
            {"program_id": 999, "turn": 60},  # no threshold for this race
        ]
        deficits = compute_race_deficits(
            thresholds,
            scheduled,
            current_stats={"speed": 500, "stamina": 400, "power": 500, "guts": 400, "wit": 400},
            current_turn=40,
        )
        self.assertEqual(len(deficits), 1)
        self.assertEqual(deficits[0]["program_id"], 4)

    def test_deficit_zero_when_projected_above_threshold(self):
        """If projected stats already exceed the threshold, no deficit."""
        from career_bot.race_thresholds import compute_race_deficits
        thresholds = {
            4: {
                "target_effective": {"speed": 800, "stamina": 800},
            }
        }
        scheduled = [{"program_id": 4, "turn": 50}]
        # At turn 40, speed 500 → projects to 500 * (50/40) + 400 = 1025 > 800.
        deficits = compute_race_deficits(
            thresholds, scheduled,
            current_stats={"speed": 500, "stamina": 500},
            current_turn=40,
        )
        self.assertEqual(deficits, [])

    def test_deficit_flags_undershoot(self):
        from career_bot.race_thresholds import compute_race_deficits
        thresholds = {
            4: {
                "race_name": "Tenno Sho (Spring)",
                "target_effective": {"speed": 1500, "stamina": 1500},
            }
        }
        scheduled = [{"program_id": 4, "turn": 50}]
        # At turn 40, speed 500 → projects to 1025 < 1500 → deficit 475.
        deficits = compute_race_deficits(
            thresholds, scheduled,
            current_stats={"speed": 500, "stamina": 500},
            current_turn=40,
        )
        self.assertEqual(len(deficits), 1)
        self.assertEqual(deficits[0]["deficit"]["speed"], 475)
        self.assertEqual(deficits[0]["turns_until"], 10)

    def test_past_races_excluded(self):
        """A race whose turn is < current_turn doesn't generate deficit."""
        from career_bot.race_thresholds import compute_race_deficits
        thresholds = {4: {"target_effective": {"speed": 5000}}}
        scheduled = [{"program_id": 4, "turn": 30}]
        deficits = compute_race_deficits(
            thresholds, scheduled,
            current_stats={"speed": 100},
            current_turn=50,
        )
        self.assertEqual(deficits, [])


class AggregateDeficitTests(unittest.TestCase):
    def test_closer_races_weight_more(self):
        """Two equal deficits — one 3 turns out, one 18 turns out. The
        closer race should produce higher pressure."""
        from career_bot.race_thresholds import aggregate_stat_deficit
        close_only = aggregate_stat_deficit(
            [{"turns_until": 3, "deficit": {"speed": 100}}],
            max_lookahead_turns=20,
        )
        far_only = aggregate_stat_deficit(
            [{"turns_until": 18, "deficit": {"speed": 100}}],
            max_lookahead_turns=20,
        )
        self.assertGreater(close_only["speed"], far_only["speed"])
        # And the close race should be at least 4× the pressure.
        self.assertGreater(close_only["speed"], far_only["speed"] * 4)

    def test_beyond_lookahead_ignored(self):
        from career_bot.race_thresholds import aggregate_stat_deficit
        deficits = [{"turns_until": 50, "deficit": {"speed": 100}}]
        self.assertEqual(aggregate_stat_deficit(deficits, max_lookahead_turns=20), {})


if __name__ == "__main__":
    unittest.main()
