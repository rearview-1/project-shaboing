import json
import tempfile
import unittest
from pathlib import Path

from career_bot.race_postmortem import analyze_trace, summarize_losses


def _row(endpoint, direction, data, ts=None):
    row = {"endpoint": endpoint, "direction": direction, "data": {"data": data}}
    if ts is not None:
        row["ts"] = ts
    return row


def _horse(viewer_id, speed, stamina, power, guts, wiz, running_style=1, frame_order=1):
    return {
        "viewer_id": viewer_id,
        "speed": speed,
        "stamina": stamina,
        "pow": power,
        "guts": guts,
        "wiz": wiz,
        "running_style": running_style,
        "frame_order": frame_order,
        "proper_distance_mile": 6,
        "proper_distance_middle": 6,
        "proper_distance_long": 5,
        "proper_ground_turf": 7,
        "race_result_array": [],
    }


def _write_trace(rows):
    fh = tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False, encoding="utf-8")
    for row in rows:
        fh.write(json.dumps(row) + "\n")
    fh.close()
    return Path(fh.name)


class AnalyzeTraceTests(unittest.TestCase):
    def test_g1_loss_emits_field_max_gap_signal(self):
        program_map = {170: {"race_instance_id": 110001, "name": "Test G1"}}
        player = _horse(viewer_id=999, speed=500, stamina=400, power=500, guts=400, wiz=600)
        weak_npc = _horse(viewer_id=0, speed=200, stamina=200, power=200, guts=200, wiz=200, frame_order=2)
        strong_npc = _horse(viewer_id=0, speed=300, stamina=600, power=350, guts=420, wiz=300, frame_order=3)
        rows = [
            _row("single_mode_free/race_start", "RES", {
                "race_start_info": {"program_id": 170, "race_horse_data": [player, weak_npc, strong_npc]},
            }),
            _row("single_mode_free/race_end", "RES", {
                "race_reward_info": {"result_rank": 3},
                "race_history": [{"turn": 34, "program_id": 170, "result_rank": 3}],
            }),
        ]
        trace = _write_trace(rows)
        try:
            losses = analyze_trace(trace, program_map)
        finally:
            trace.unlink()
        self.assertEqual(len(losses), 1)
        loss = losses[0]
        self.assertEqual(loss["grade"], "G1")
        self.assertEqual(loss["player_finish_rank"], 3)
        self.assertEqual(loss["turn"], 34)
        self.assertEqual(loss["field_max_stats"]["stamina"], 600)
        self.assertEqual(loss["field_max_gap_over_player"]["stamina"], 200)
        self.assertEqual(loss["primary_gap_stat"], "stamina")
        self.assertEqual(loss["opponents_above_player_per_stat"]["stamina"], 1)

    def test_g1_win_is_skipped(self):
        program_map = {170: {"race_instance_id": 110001, "name": "Test G1"}}
        player = _horse(viewer_id=999, speed=500, stamina=400, power=500, guts=400, wiz=600)
        weak_npc = _horse(viewer_id=0, speed=200, stamina=200, power=200, guts=200, wiz=200)
        rows = [
            _row("single_mode_free/race_start", "RES", {
                "race_start_info": {"program_id": 170, "race_horse_data": [player, weak_npc]},
            }),
            _row("single_mode_free/race_end", "RES", {
                "race_reward_info": {"result_rank": 1},
                "race_history": [{"turn": 34, "program_id": 170, "result_rank": 1}],
            }),
        ]
        trace = _write_trace(rows)
        try:
            losses = analyze_trace(trace, program_map)
        finally:
            trace.unlink()
        self.assertEqual(losses, [])

    def test_started_at_filters_out_earlier_career_losses(self):
        program_map = {170: {"race_instance_id": 110001, "name": "Test G1"}}
        player = _horse(viewer_id=999, speed=500, stamina=400, power=500, guts=400, wiz=600)
        npc = _horse(viewer_id=0, speed=200, stamina=600, power=200, guts=200, wiz=200, frame_order=2)
        rows = [
            _row("single_mode_free/race_start", "RES", {
                "race_start_info": {"program_id": 170, "race_horse_data": [player, npc]},
            }, ts=1000.0),
            _row("single_mode_free/race_end", "RES", {
                "race_reward_info": {"result_rank": 3},
                "race_history": [{"turn": 34, "program_id": 170, "result_rank": 3}],
            }, ts=1010.0),
            _row("single_mode_free/race_start", "RES", {
                "race_start_info": {"program_id": 170, "race_horse_data": [player, npc]},
            }, ts=2000.0),
            _row("single_mode_free/race_end", "RES", {
                "race_reward_info": {"result_rank": 2},
                "race_history": [{"turn": 40, "program_id": 170, "result_rank": 2}],
            }, ts=2010.0),
        ]
        trace = _write_trace(rows)
        try:
            cumulative = analyze_trace(trace, program_map)
            second_career_only = analyze_trace(trace, program_map, started_at=1500.0, ended_at=2500.0)
        finally:
            trace.unlink()
        self.assertEqual(len(cumulative), 2)
        self.assertEqual(len(second_career_only), 1)
        self.assertEqual(second_career_only[0]["turn"], 40)

    def test_non_g1_loss_is_skipped(self):
        program_map = {171: {"race_instance_id": 210001, "name": "Test G2"}}
        player = _horse(viewer_id=999, speed=500, stamina=400, power=500, guts=400, wiz=600)
        npc = _horse(viewer_id=0, speed=600, stamina=500, power=550, guts=420, wiz=300)
        rows = [
            _row("single_mode_free/race_start", "RES", {
                "race_start_info": {"program_id": 171, "race_horse_data": [player, npc]},
            }),
            _row("single_mode_free/race_end", "RES", {
                "race_reward_info": {"result_rank": 2},
                "race_history": [{"turn": 30, "program_id": 171, "result_rank": 2}],
            }),
        ]
        trace = _write_trace(rows)
        try:
            losses = analyze_trace(trace, program_map)
        finally:
            trace.unlink()
        self.assertEqual(losses, [])


class SummarizeLossesTests(unittest.TestCase):
    def test_empty_returns_zero_summary(self):
        summary = summarize_losses([])
        self.assertEqual(summary["count"], 0)
        self.assertIsNone(summary["worst_stat"])

    def test_aggregates_field_max_gaps(self):
        losses = [
            {"field_max_gap_over_player": {"speed": 50, "stamina": 200, "power": -10, "guts": 0, "wit": -20}},
            {"field_max_gap_over_player": {"speed": 10, "stamina": 100, "power": -50, "guts": 5, "wit": 10}},
        ]
        summary = summarize_losses(losses)
        self.assertEqual(summary["count"], 2)
        self.assertEqual(summary["worst_stat"], "stamina")
        self.assertEqual(summary["average_field_max_gap"]["stamina"], 150)


if __name__ == "__main__":
    unittest.main()
