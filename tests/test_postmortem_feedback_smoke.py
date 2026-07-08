"""Smoke + behavior tests for the race-postmortem feedback aggregation.

The legacy global "worst_stat" summary biased every race-loss feedback
toward the same stat (often Guts) regardless of which race actually
needed which stat. The feedback module aggregates by program_id so a
loss at NHK Mile Cup (which needs Speed/Power) doesn't contaminate
the feedback for Kikuka Sho (which needs Stamina/Guts).
"""

import json
import tempfile
import unittest
from pathlib import Path

from career_bot.postmortem_feedback import (
    aggregate_by_race,
    load_recent_postmortems,
    merge_global_signal,
    race_stat_hints,
    upcoming_race_stat_demand,
)


def _postmortem(losses):
    """Build a postmortem dict matching the on-disk schema."""
    return {
        "trace_file": "fake.jsonl",
        "career_log": "fake.json",
        "g1_losses": list(losses),
        "summary": {},
    }


def _loss(
    program_id, race_name, gaps, turn=60,
    player_running_style=None, opponent_style_counts=None,
    common_opponent_skills=None,
):
    loss = {
        "turn": turn,
        "program_id": program_id,
        "race_name": race_name,
        "grade": "G1",
        "field_max_gap_over_player": dict(gaps),
    }
    if player_running_style is not None:
        loss["player_running_style"] = player_running_style
    if opponent_style_counts is not None:
        loss["opponent_style_counts"] = dict(opponent_style_counts)
    if common_opponent_skills is not None:
        loss["common_opponent_skills"] = list(common_opponent_skills)
    return loss


class AggregationTests(unittest.TestCase):
    def test_losses_grouped_by_race_id_not_globally(self):
        """Race-specific hints must not collapse into a global Guts bias."""
        pms = [
            _postmortem([
                _loss(11017, "NHK Mile Cup", {"speed": 80, "stamina": -50, "power": 120, "guts": -30, "wit": -10}),
            ]),
            _postmortem([
                _loss(11034, "Kikuka Sho", {"speed": -40, "stamina": 180, "power": -20, "guts": 200, "wit": 60}),
            ]),
        ]
        agg = aggregate_by_race(pms)
        self.assertEqual(len(agg), 2)
        nhk = agg[11017]
        kikuka = agg[11034]

        self.assertEqual(nhk["worst_stat"], "power")
        self.assertEqual(nhk["avg_gap"]["power"], 120.0)
        self.assertEqual(kikuka["worst_stat"], "stamina")
        self.assertEqual(kikuka["avg_gap"]["guts"], 200.0)
        self.assertEqual(kikuka["avg_gap"]["stamina"], 180.0)

    def test_multiple_losses_same_race_average_correctly(self):
        """If the bot loses NHK Mile Cup 3 times, each with its own
        gap, the hint should be the average of those gaps and the
        loss_count should be 3."""
        pms = [
            _postmortem([_loss(11017, "NHK Mile Cup", {"speed": 0, "stamina": 0, "power": 100, "guts": 0, "wit": 0})]),
            _postmortem([_loss(11017, "NHK Mile Cup", {"speed": 0, "stamina": 0, "power": 140, "guts": 0, "wit": 0})]),
            _postmortem([_loss(11017, "NHK Mile Cup", {"speed": 0, "stamina": 0, "power": 120, "guts": 0, "wit": 0})]),
        ]
        agg = aggregate_by_race(pms)
        self.assertEqual(len(agg), 1)
        nhk = agg[11017]
        self.assertEqual(nhk["loss_count"], 3)
        self.assertEqual(nhk["avg_gap"]["power"], 120.0)
        self.assertEqual(nhk["worst_stat"], "power")

    def test_race_where_bot_was_ahead_on_all_stats_has_no_worst_stat(self):
        """If the bot lost despite being ahead on every stat (negative
        gaps everywhere), stat-bumping won't help — the loss was due
        to style mismatch, aptitude, or RNG. worst_stat=None signals
        "don't try to fix this with more stats."""
        pms = [
            _postmortem([_loss(99999, "Mystery G1", {"speed": -50, "stamina": -30, "power": -20, "guts": -10, "wit": -5})]),
        ]
        agg = aggregate_by_race(pms)
        self.assertIsNone(agg[99999]["worst_stat"])
        self.assertEqual(agg[99999]["worst_stat_gap"], 0.0)

    def test_min_losses_filter_excludes_rare_races(self):
        """When `min_losses=2` is passed via race_stat_hints, races
        with only one recorded loss are filtered out — useful for
        ignoring one-off bad-RNG losses when tuning the preset."""
        pms = [
            _postmortem([
                _loss(11017, "NHK Mile Cup", {"power": 120}),
                _loss(11034, "Kikuka Sho", {"guts": 200}),
            ]),
            _postmortem([
                _loss(11017, "NHK Mile Cup", {"power": 140}),
            ]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            postmortem_dir = Path(tmp) / "postmortems"
            postmortem_dir.mkdir()
            for idx, pm in enumerate(pms):
                (postmortem_dir / f"postmortem_2026{idx:02d}.json").write_text(
                    json.dumps(pm), encoding="utf-8",
                )
            hints = race_stat_hints(tmp, min_losses=2)
        # Only NHK Mile Cup has >=2 losses.
        self.assertIn(11017, hints)
        self.assertNotIn(11034, hints)

    def test_off_aptitude_postmortem_losses_are_ignored(self):
        """If a G1 loss came from an off-aptitude race, it should not
        feed the race-loss feedback layer."""
        pms = [
            _postmortem([{
                "turn": 44,
                "program_id": 12001,
                "race_name": "Accidental Dirt G1",
                "grade": "G1",
                "race_distance": "Mile",
                "race_terrain": "Dirt",
                "player_running_style": 3,
                "player_aptitude": {
                    "ground_turf": 7,
                    "ground_dirt": 1,
                    "distance_short": 2,
                    "distance_mile": 5,
                    "distance_medium": 7,
                    "distance_long": 7,
                    "running_style_front": 2,
                    "running_style_pace": 7,
                    "running_style_late": 7,
                    "running_style_end": 4,
                },
                "field_max_gap_over_player": {"speed": 100, "stamina": 20, "power": 140, "guts": 0, "wit": 0},
            }]),
        ]
        agg = aggregate_by_race(pms)
        self.assertNotIn(12001, agg)


class GlobalSignalTests(unittest.TestCase):
    """The global summary is still useful as a fallback when the bot
    doesn't have race-specific schedule info. It's weighted by loss
    count so a 3-time-lost race dominates a 1-time-lost race."""

    def test_global_weighted_by_loss_count(self):
        per_race = {
            11017: {"loss_count": 3, "avg_gap": {"speed": 0, "stamina": 0, "power": 120, "guts": 0, "wit": 0}, "worst_stat": "power"},
            11034: {"loss_count": 1, "avg_gap": {"speed": 0, "stamina": 0, "power": 0, "guts": 300, "wit": 0}, "worst_stat": "guts"},
        }
        global_hint = merge_global_signal(per_race)
        # 3 losses at +120 power = 360 weighted, 1 loss at +300 guts = 300 weighted
        # Over 4 total losses: power=90, guts=75 → power wins as global worst stat.
        self.assertEqual(global_hint["worst_stat"], "power")
        self.assertEqual(global_hint["total_losses"], 4)

    def test_empty_input_returns_empty_global_signal(self):
        result = merge_global_signal({})
        self.assertEqual(result["total_losses"], 0)
        self.assertIsNone(result["worst_stat"])


class RichSignalTests(unittest.TestCase):
    """The richer postmortem capture (running_style, opponent skills)
    flows into per-race hints as style_mismatch_suggested and
    common_opponent_skills so the bot can act on more than raw stats."""

    def test_style_mismatch_surfaces_when_field_runs_different_style(self):
        """Bot ran Front Runner (style=1) but the lost race's field was
        80% Pace Chaser (style=2). The hint should flag the mismatch."""
        pms = [
            _postmortem([
                _loss(
                    11017, "NHK Mile Cup",
                    {"speed": -20, "stamina": 0, "power": 100, "guts": 0, "wit": 0},
                    player_running_style=1,  # bot used Front Runner
                    opponent_style_counts={2: 8, 1: 2},  # field mostly Pace Chasers
                ),
            ]),
        ]
        agg = aggregate_by_race(pms)
        nhk = agg[11017]
        self.assertEqual(nhk["player_style_used"], "front_runner")
        self.assertEqual(nhk["field_style_dominant"], "pace_chaser")
        self.assertTrue(nhk["style_mismatch_suggested"])

    def test_no_style_mismatch_when_bot_and_field_align(self):
        """Bot also ran Pace Chaser; no mismatch flag — the loss wasn't
        a style problem."""
        pms = [
            _postmortem([
                _loss(
                    11017, "NHK Mile Cup",
                    {"power": 100},
                    player_running_style=2,
                    opponent_style_counts={2: 9, 1: 1},
                ),
            ]),
        ]
        agg = aggregate_by_race(pms)
        self.assertFalse(agg[11017]["style_mismatch_suggested"])

    def test_common_opponent_skills_aggregate_across_losses(self):
        """Two losses at the same race, opponents had Speed Star and
        Lightning Foot — both surface in the per-race hint with
        cumulative counts."""
        pms = [
            _postmortem([
                _loss(
                    11017, "NHK Mile Cup",
                    {"power": 100},
                    common_opponent_skills=[
                        {"skill_id": 200391, "count": 5},  # Speed Star
                        {"skill_id": 200471, "count": 3},  # Lightning Foot
                    ],
                ),
            ]),
            _postmortem([
                _loss(
                    11017, "NHK Mile Cup",
                    {"power": 80},
                    common_opponent_skills=[
                        {"skill_id": 200391, "count": 4},
                    ],
                ),
            ]),
        ]
        agg = aggregate_by_race(pms)
        nhk = agg[11017]
        top_skills = nhk["common_opponent_skills"]
        # Speed Star (200391) should have count 5+4=9. Lightning Foot (200471) should have 3.
        skill_counts = {s["skill_id"]: s["field_count"] for s in top_skills}
        self.assertEqual(skill_counts.get(200391), 9)
        self.assertEqual(skill_counts.get(200471), 3)


class UpcomingDemandTests(unittest.TestCase):
    """Phase 2: scheduled races + per-race hints → per-stat demand
    that the training-policy bias consumes."""

    def test_upcoming_race_with_power_hint_drives_power_demand(self):
        per_race_hints = {
            11017: {
                "program_id": 11017, "loss_count": 3,
                "avg_gap": {"speed": 0, "stamina": 0, "power": 150, "guts": 0, "wit": 0},
                "worst_stat": "power", "worst_stat_gap": 150,
            },
        }
        scheduled = [{"turn": 35, "program_id": 11017}]
        demand = upcoming_race_stat_demand(per_race_hints, scheduled, current_turn=33)
        # Power should be the only stat with positive demand. Race is
        # 2 turns out (offset=2, lookahead=8) → urgency = 1 - 2/8 = 0.75.
        self.assertIn("power", demand)
        self.assertGreater(demand["power"], 0)
        self.assertNotIn("guts", demand)

    def test_races_outside_lookahead_window_are_ignored(self):
        per_race_hints = {
            11017: {
                "program_id": 11017, "loss_count": 3,
                "avg_gap": {"power": 150, "speed": 0, "stamina": 0, "guts": 0, "wit": 0},
                "worst_stat": "power", "worst_stat_gap": 150,
            },
        }
        scheduled = [{"turn": 60, "program_id": 11017}]
        demand = upcoming_race_stat_demand(per_race_hints, scheduled, current_turn=20, lookahead=8)
        # Race is 40 turns out — way outside the 8-turn lookahead.
        self.assertEqual(demand, {})

    def test_demand_compounds_when_multiple_upcoming_races_need_same_stat(self):
        per_race_hints = {
            11017: {
                "program_id": 11017,
                "avg_gap": {"power": 150, "speed": 0, "stamina": 0, "guts": 0, "wit": 0},
                "worst_stat": "power", "worst_stat_gap": 150,
            },
            11018: {
                "program_id": 11018,
                "avg_gap": {"power": 100, "speed": 0, "stamina": 0, "guts": 0, "wit": 0},
                "worst_stat": "power", "worst_stat_gap": 100,
            },
        }
        scheduled = [
            {"turn": 35, "program_id": 11017},
            {"turn": 38, "program_id": 11018},
        ]
        single_demand = upcoming_race_stat_demand(
            {11017: per_race_hints[11017]}, [scheduled[0]], current_turn=33,
        )
        both_demand = upcoming_race_stat_demand(per_race_hints, scheduled, current_turn=33)
        # Both upcoming races needing Power → demand is higher than just one.
        self.assertGreater(both_demand["power"], single_demand["power"])


class LoadRecentTests(unittest.TestCase):
    def test_missing_directory_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_recent_postmortems(tmp), [])

    def test_load_returns_most_recent_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            postmortem_dir = Path(tmp) / "postmortems"
            postmortem_dir.mkdir()
            paths = []
            for idx in range(5):
                path = postmortem_dir / f"postmortem_2026{idx:02d}.json"
                path.write_text(json.dumps({"id": idx, "g1_losses": []}), encoding="utf-8")
                paths.append(path)
            # Touch them in known order so mtime ordering is deterministic.
            import time
            for path in paths:
                time.sleep(0.01)
                path.touch()
            results = load_recent_postmortems(tmp)
        self.assertEqual(len(results), 5)
        # Most-recently-touched should come first.
        self.assertEqual(results[0]["id"], 4)

    def test_malformed_postmortem_is_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            postmortem_dir = Path(tmp) / "postmortems"
            postmortem_dir.mkdir()
            (postmortem_dir / "postmortem_good.json").write_text(
                json.dumps({"g1_losses": []}), encoding="utf-8",
            )
            (postmortem_dir / "postmortem_bad.json").write_text("{ not valid json", encoding="utf-8")
            results = load_recent_postmortems(tmp)
        self.assertEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
