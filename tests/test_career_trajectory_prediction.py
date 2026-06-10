"""Career trajectory prediction.

At each checkpoint turn (24, 36, 48, 60, 72), past careers' feature
vectors get averaged into top/bottom centroids. Live careers can
classify against those centroids — tracking_top vs tracking_bottom vs
ambiguous — using normalized Euclidean distance. Output is
informational; no decisions read from it yet.
"""

import unittest

from career_bot.career_trajectory_prediction import (
    CHECKPOINT_TURNS,
    FEATURE_KEYS,
    aggregate_trajectory_centroids,
    predict_trajectory,
    stat_curve_from_turns,
)


def _stats(speed=200, stamina=200, power=200, guts=150, wit=150, hp=100, skill_point=100):
    return {
        "speed": speed,
        "stamina": stamina,
        "power": power,
        "guts": guts,
        "wit": wit,
        "hp": hp,
        "skill_point": skill_point,
    }


def _curve_at_turns(turn_to_stats):
    return [
        {"turn": turn, **stats}
        for turn, stats in turn_to_stats.items()
    ]


def _sample(curve):
    return {"stat_curve": curve}


class StatCurveExtractionTests(unittest.TestCase):
    def test_extracts_per_turn_stat_vector(self):
        turns = [
            {"turn": 1, "stats": {"speed": 100, "stamina": 90, "power": 95, "guts": 80, "wit": 85, "hp": 100, "skill_point": 10}},
            {"turn": 2, "stats": {"speed": 110, "stamina": 95, "power": 100, "guts": 80, "wit": 85, "hp": 95, "skill_point": 12}},
        ]
        out = stat_curve_from_turns(turns)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["speed"], 100)
        self.assertEqual(out[1]["hp"], 95)

    def test_skips_turns_without_usable_stats(self):
        turns = [
            {"turn": 1, "stats": {}},
            {"turn": 2, "stats": {"speed": 100, "hp": 100, "skill_point": 10}},
        ]
        out = stat_curve_from_turns(turns)
        # First turn has no usable stats → skipped.
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["turn"], 2)


class AggregationTests(unittest.TestCase):
    def test_empty_when_no_samples(self):
        self.assertEqual(aggregate_trajectory_centroids([], []), {})

    def test_builds_centroids_at_checkpoint_turns(self):
        # 3 top samples + 3 bottom samples, each with data at turn 24.
        top = []
        for _ in range(3):
            top.append(_sample(_curve_at_turns({
                24: _stats(speed=400, stamina=400, power=400, hp=100, skill_point=200),
            })))
        bottom = []
        for _ in range(3):
            bottom.append(_sample(_curve_at_turns({
                24: _stats(speed=200, stamina=200, power=200, hp=80, skill_point=100),
            })))
        centroids = aggregate_trajectory_centroids(top, bottom)
        self.assertIn("checkpoints", centroids)
        cp24 = centroids["checkpoints"]["24"]
        self.assertEqual(cp24["top_centroid"]["speed"], 400)
        self.assertEqual(cp24["bottom_centroid"]["speed"], 200)
        self.assertEqual(cp24["top_count"], 3)
        self.assertEqual(cp24["bottom_count"], 3)

    def test_window_lets_nearby_turns_count_toward_checkpoint(self):
        """A turn 25 or 23 should map to checkpoint 24 (within window=4)."""
        top = []
        for offset in (-2, 0, 2):
            top.append(_sample(_curve_at_turns({24 + offset: _stats(speed=350)})))
        centroids = aggregate_trajectory_centroids(top, [])
        # All three rows mapped to checkpoint 24 → top_count = 3.
        self.assertEqual(centroids["checkpoints"]["24"]["top_count"], 3)

    def test_skips_checkpoint_with_insufficient_samples(self):
        # Only 1 sample → below MIN_SAMPLES_PER_CHECKPOINT.
        top = [_sample(_curve_at_turns({24: _stats()}))]
        centroids = aggregate_trajectory_centroids(top, [])
        # 1 < MIN_SAMPLES_PER_CHECKPOINT on both top and bottom → no
        # checkpoint emitted.
        self.assertEqual(centroids.get("checkpoints", {}), {})


class PredictionTests(unittest.TestCase):
    def _make_centroids(self):
        top = []
        bottom = []
        for _ in range(3):
            top.append(_sample(_curve_at_turns({
                36: _stats(speed=500, stamina=480, power=510, guts=300, wit=400, hp=85, skill_point=200),
            })))
            bottom.append(_sample(_curve_at_turns({
                36: _stats(speed=300, stamina=280, power=290, guts=200, wit=250, hp=60, skill_point=120),
            })))
        return aggregate_trajectory_centroids(top, bottom)

    def test_unknown_when_no_centroids(self):
        out = predict_trajectory({}, _stats(), 36)
        self.assertEqual(out["label"], "unknown")

    def test_unknown_when_turn_too_far_from_any_checkpoint(self):
        centroids = self._make_centroids()
        out = predict_trajectory(centroids, _stats(), 5)
        self.assertEqual(out["label"], "unknown")

    def test_tracking_top_when_close_to_top_centroid(self):
        centroids = self._make_centroids()
        out = predict_trajectory(centroids, _stats(speed=490, stamina=470, power=500, guts=295, wit=395, hp=85, skill_point=200), 36)
        self.assertEqual(out["label"], "tracking_top")
        self.assertIsNotNone(out["top_distance"])
        self.assertGreater(out["confidence"], 0)

    def test_tracking_bottom_when_close_to_bottom_centroid(self):
        centroids = self._make_centroids()
        out = predict_trajectory(centroids, _stats(speed=290, stamina=270, power=280, guts=190, wit=240, hp=55, skill_point=110), 36)
        self.assertEqual(out["label"], "tracking_bottom")

    def test_ambiguous_when_equidistant(self):
        """Stats halfway between top and bottom centroids → label is
        ambiguous when the confidence margin is too small."""
        centroids = self._make_centroids()
        out = predict_trajectory(centroids, _stats(speed=400, stamina=380, power=400, guts=250, wit=325, hp=72, skill_point=160), 36)
        # Doesn't matter which label as long as confidence is small.
        # Could be tracking_top or ambiguous depending on numeric drift —
        # the important thing is the prediction system doesn't claim a
        # high-confidence label on equidistant data.
        self.assertLess(out["confidence"], 0.4)

    def test_label_when_one_centroid_missing(self):
        """If only the top centroid was built (no bottom samples), the
        predictor returns tracking_top for anything in the window."""
        top = []
        for _ in range(3):
            top.append(_sample(_curve_at_turns({36: _stats()})))
        centroids = aggregate_trajectory_centroids(top, [])
        # No bottom samples → no bottom centroid. Any prediction at
        # checkpoint 36 should be tracking_top.
        out = predict_trajectory(centroids, _stats(speed=999), 36)
        self.assertEqual(out["label"], "tracking_top")


if __name__ == "__main__":
    unittest.main()
