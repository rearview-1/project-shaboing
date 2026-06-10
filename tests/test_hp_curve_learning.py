"""HP curve learning — per-phase HP targets from top-scoring careers.

Mirrors motivation_curve_learning. The bot's rest decision uses a
static `rest_threshold`; this learner derives `target_hp_year{1,2,3}`
from what top samples actually maintained so the bot can aim for the
right HP level per phase instead of one global threshold.
"""

import unittest

from career_bot.hp_curve_learning import (
    MIN_TOP_CAREERS,
    MIN_TURNS_PER_PHASE,
    aggregate_hp_curves,
    hp_curve_from_turns,
    learned_hp_targets,
)


def _curve(pairs):
    return [{"turn": t, "hp": v} for t, v in pairs]


def _sample(curve):
    return {"hp_curve": curve}


class CurveExtractionTests(unittest.TestCase):
    def test_extracts_vital_from_turn_row(self):
        turns = [
            {"turn": 1, "vital": 100},
            {"turn": 2, "vital": 85},
        ]
        self.assertEqual(
            hp_curve_from_turns(turns),
            [{"turn": 1, "hp": 100}, {"turn": 2, "hp": 85}],
        )

    def test_falls_back_to_chara_info_vital(self):
        turns = [{"turn": 5, "chara_info": {"vital": 70}}]
        self.assertEqual(hp_curve_from_turns(turns), [{"turn": 5, "hp": 70}])

    def test_skips_rows_missing_data(self):
        turns = [
            {"turn": 1, "vital": 100},
            {"turn": 2},                         # missing vital
            {"vital": 80},                       # missing turn
            {"turn": 3, "vital": 0},             # invalid hp
            {"turn": 0, "vital": 90},            # invalid turn
        ]
        self.assertEqual(hp_curve_from_turns(turns), [{"turn": 1, "hp": 100}])


class AggregationTests(unittest.TestCase):
    def test_returns_empty_below_min_top_careers(self):
        samples = [_sample(_curve([(1, 80), (10, 80), (20, 80)]))]
        self.assertEqual(aggregate_hp_curves(samples), {})

    def test_skips_phases_with_too_few_turns(self):
        samples = [
            _sample(_curve([(1, 80)])),
            _sample(_curve([(2, 80)])),
            _sample(_curve([(3, 80)])),
        ]
        result = aggregate_hp_curves(samples)
        # 3 year1 turns < MIN_TURNS_PER_PHASE (8) → skip.
        self.assertNotIn("year1", result)

    def test_computes_median_per_phase(self):
        samples = []
        for _ in range(MIN_TOP_CAREERS):
            curve = _curve(
                [(t, 85) for t in range(1, 12)]
                + [(t, 75) for t in range(37, 48)]
                + [(t, 65) for t in range(61, 72)]
            )
            samples.append(_sample(curve))
        result = aggregate_hp_curves(samples)
        self.assertEqual(result["year1"], 85)
        self.assertEqual(result["year2"], 75)
        self.assertEqual(result["year3"], 65)

    def test_buckets_turns_into_correct_phase(self):
        samples = []
        for _ in range(MIN_TOP_CAREERS):
            curve = _curve([(36, 70)] * 5 + [(37, 80)] * 5 + [(70, 60)] * 5)
            samples.append(_sample(curve))
        result = aggregate_hp_curves(samples)
        self.assertIn("year1", result)
        self.assertIn("year2", result)
        self.assertIn("year3", result)
        self.assertEqual(result["year2"], 80)
        self.assertEqual(result["year3"], 60)


class LearnedTargetTests(unittest.TestCase):
    def test_returns_empty_when_no_data(self):
        self.assertEqual(learned_hp_targets([]), {})

    def test_emits_target_hp_keys(self):
        samples = []
        for _ in range(MIN_TOP_CAREERS):
            curve = _curve(
                [(t, 85) for t in range(1, 12)]
                + [(t, 75) for t in range(37, 48)]
                + [(t, 65) for t in range(61, 72)]
            )
            samples.append(_sample(curve))
        out = learned_hp_targets(samples)
        self.assertEqual(out["target_hp_year1"], 85)
        self.assertEqual(out["target_hp_year2"], 75)
        self.assertEqual(out["target_hp_year3"], 65)

    def test_target_clamped_to_valid_range(self):
        """Median HP below MIN_TARGET (30) should be clamped up; above
        MAX_TARGET (95) clamped down."""
        # All HP at 25 → clamp to 30.
        samples = []
        for _ in range(MIN_TOP_CAREERS):
            samples.append(_sample(_curve([(t, 25) for t in range(1, 12)])))
        out = learned_hp_targets(samples)
        self.assertEqual(out["target_hp_year1"], 30)
        # All HP at 100 → clamp to 95.
        samples = []
        for _ in range(MIN_TOP_CAREERS):
            samples.append(_sample(_curve([(t, 100) for t in range(1, 12)])))
        out = learned_hp_targets(samples)
        self.assertEqual(out["target_hp_year1"], 95)


if __name__ == "__main__":
    unittest.main()
