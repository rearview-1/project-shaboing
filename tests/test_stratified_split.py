import unittest

from career_bot.learning import stratified_top_bottom_split


def _sample(score, primary="wit", blue_pref="wit", deck_q=2):
    return {
        "score": score,
        "learning_metadata": {
            "session": {
                "primary_stat_target": {"stat": primary},
                "blue_spark_intent": {"preferred_color": blue_pref},
            },
            "deck_quality_bucket": deck_q,
        },
    }


class StratifiedSplitTests(unittest.TestCase):
    def test_separates_top_and_bottom_within_bucket(self):
        samples = [_sample(score=s, deck_q=3) for s in [1000, 2000, 3000, 4000, 5000, 6000, 7000, 8000]]
        top, bottom, stats = stratified_top_bottom_split(samples, top_fraction=0.25)
        self.assertTrue(top and bottom)
        top_scores = [s["score"] for s in top]
        bottom_scores = [s["score"] for s in bottom]
        self.assertGreater(min(top_scores), max(bottom_scores))

    def test_separate_buckets_dont_cross_pollinate(self):
        wit_samples = [_sample(score=s, primary="wit", deck_q=3) for s in [1000, 2000, 3000, 4000, 5000]]
        speed_samples = [_sample(score=s, primary="speed", deck_q=3) for s in [10000, 20000, 30000, 40000, 50000]]
        all_samples = wit_samples + speed_samples
        top, bottom, stats = stratified_top_bottom_split(all_samples)
        # Each bucket should have at least one top and one bottom
        bucket_labels = [k for k in stats.keys() if "skipped" not in k and "fallback" not in k]
        self.assertEqual(len(bucket_labels), 2)
        # A top from the WIT bucket can be lower-score than a bottom from the SPEED bucket
        # — that's the whole point of stratifying
        wit_top = [s for s in top if (s["learning_metadata"]["session"]["primary_stat_target"]["stat"] == "wit")]
        speed_bottom = [s for s in bottom if (s["learning_metadata"]["session"]["primary_stat_target"]["stat"] == "speed")]
        if wit_top and speed_bottom:
            self.assertLess(wit_top[0]["score"], speed_bottom[0]["score"])

    def test_small_buckets_fall_back_to_objective_only(self):
        # Two cells of 2 samples each, same objective: too small to split per-cell,
        # but the fallback objective-only bucket has 4 — enough to split.
        samples = [
            _sample(score=1000, primary="wit", deck_q=2),
            _sample(score=2000, primary="wit", deck_q=2),
            _sample(score=3000, primary="wit", deck_q=3),
            _sample(score=4000, primary="wit", deck_q=3),
        ]
        top, bottom, stats = stratified_top_bottom_split(samples, min_bucket_size=4)
        self.assertTrue(top and bottom)
        # All four samples fell into "skipped_small" cells, then re-bucketed by
        # objective only into a fallback group of 4.
        self.assertTrue(any("fallback" in k for k in stats.keys()))

    def test_returns_empty_when_no_samples_qualify(self):
        top, bottom, stats = stratified_top_bottom_split([], min_bucket_size=4)
        self.assertEqual(top, [])
        self.assertEqual(bottom, [])


if __name__ == "__main__":
    unittest.main()
