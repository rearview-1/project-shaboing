"""Event-choice learning aggregator + picker.

Career events with multiple choices are the largest under-explored
adaptive surface (30-50 per career). The bot used to pick the same
choice every time per event; the learning module aggregates per
(story_id, choice_index) and lets the picker override with the
learner's preference when one choice has clearly outperformed
alternatives in the bot's own data.
"""

import random
import unittest

from career_bot.event_choice_learning import (
    MIN_PICKS_PER_CHOICE,
    aggregate_event_choices,
    pick_learned_choice,
)


def _sample(score, event_choices):
    """Build a minimal sample dict matching the shape `aggregate_event_choices`
    expects (uses the flat `event_choices` field that `normalize_bot_like_log`
    extracts from per-turn events)."""
    return {
        "score": score,
        "event_choices": [
            {"story_id": str(sid), "choice_index": int(idx)}
            for sid, idx in event_choices
        ],
    }


def _context_sample(score, story_id, choice_index, phase, blue_target):
    return {
        "score": score,
        "event_choices": [{
            "story_id": str(story_id),
            "choice_index": int(choice_index),
            "phase": phase,
            "blue_target": blue_target,
        }],
    }


def _run_context_spark_sample(score, story_id, choice_index, blue_target):
    return {
        "score": score,
        "run_context": {
            "desired_parent_sparks": {"blue": [blue_target], "pink": [], "green": [], "white": []},
        },
        "event_choices": [{
            "story_id": str(story_id),
            "choice_index": int(choice_index),
            "phase": "early",
        }],
    }


class AggregateTests(unittest.TestCase):
    def test_returns_empty_when_no_samples(self):
        self.assertEqual(aggregate_event_choices([]), {})

    def test_returns_empty_when_below_total_pick_threshold(self):
        """A single sample isn't enough — the learner waits for at
        least MIN_TOTAL_PICKS picks across a story_id before
        producing a learned stats entry."""
        samples = [_sample(15000, [("100", 0)])]
        result = aggregate_event_choices(samples)
        self.assertEqual(result, {})

    def test_aggregates_choices_across_samples_for_same_story(self):
        # 5 careers, all picking choice 1 → enough samples but only one choice.
        samples = []
        for i in range(5):
            samples.append(_sample(10000 + i * 100, [("100", 0)]))
        result = aggregate_event_choices(samples)
        self.assertIn("100", result)
        entry = result["100"]
        self.assertEqual(entry["sample_count"], 5)
        self.assertEqual(entry["best_choice"], "0")

    def test_picks_higher_avg_choice_when_two_compared(self):
        samples = []
        # Choice 1: 5 careers, avg 16000
        for i in range(5):
            samples.append(_sample(15000 + i * 500, [("200", 0)]))
        # Choice 2: 5 careers, avg 10000
        for i in range(5):
            samples.append(_sample(9000 + i * 500, [("200", 1)]))
        result = aggregate_event_choices(samples)
        self.assertEqual(result["200"]["best_choice"], "0")
        # Confidence should be high (large lift)
        self.assertGreater(result["200"]["confidence"], 0.5)

    def test_low_confidence_when_scores_are_close(self):
        samples = []
        for i in range(MIN_PICKS_PER_CHOICE):
            samples.append(_sample(15000, [("300", 0)]))
        for i in range(MIN_PICKS_PER_CHOICE):
            samples.append(_sample(15100, [("300", 1)]))
        result = aggregate_event_choices(samples)
        # Choices are basically tied → confidence near zero.
        self.assertLess(result["300"]["confidence"], 0.2)

    def test_ignores_choices_below_min_picks(self):
        """A choice with only 1 sample shouldn't be considered as
        'best' even if it had the highest score — too thin a signal
        to outweigh a well-sampled alternative."""
        samples = []
        # Choice 1: 5 careers at avg 13000
        for i in range(5):
            samples.append(_sample(13000, [("400", 0)]))
        # Choice 2: 1 lucky career at 25000
        samples.append(_sample(25000, [("400", 1)]))
        result = aggregate_event_choices(samples)
        # Choice 2 is ineligible (only 1 sample, below MIN_PICKS_PER_CHOICE).
        self.assertEqual(result["400"]["best_choice"], "0")

    def test_ignores_samples_with_zero_score(self):
        # Score 0 samples are excluded (crashed/incomplete careers).
        samples = [_sample(0, [("100", 0)]) for _ in range(10)]
        result = aggregate_event_choices(samples)
        self.assertEqual(result, {})

    def test_records_contextual_choice_stats(self):
        samples = []
        for _ in range(5):
            samples.append(_context_sample(16000, "700", 0, "early", "power"))
            samples.append(_context_sample(12000, "700", 1, "early", "power"))
        for _ in range(5):
            samples.append(_context_sample(12000, "700", 0, "late", "stamina"))
            samples.append(_context_sample(16500, "700", 1, "late", "stamina"))
        result = aggregate_event_choices(samples)
        self.assertIn("700", result)
        self.assertIn("contexts", result["700"])
        self.assertEqual(result["700"]["contexts"]["phase=early|blue=power"]["best_choice"], "0")
        self.assertEqual(result["700"]["contexts"]["phase=late|blue=stamina"]["best_choice"], "1")

    def test_context_uses_sample_spark_goal_not_current_preset_goal(self):
        samples = []
        for _ in range(5):
            samples.append(_run_context_spark_sample(16500, "701", 0, "Power"))
            samples.append(_run_context_spark_sample(12000, "701", 1, "Power"))
        for _ in range(5):
            samples.append(_run_context_spark_sample(12000, "701", 0, "Speed"))
            samples.append(_run_context_spark_sample(16600, "701", 1, "Speed"))

        result = aggregate_event_choices(
            samples,
            preset_fallback={"desired_parent_sparks": {"blue": ["Stamina"]}},
        )

        self.assertEqual(result["701"]["contexts"]["phase=early|blue=power"]["best_choice"], "0")
        self.assertEqual(result["701"]["contexts"]["phase=early|blue=speed"]["best_choice"], "1")


def _choice(select_index):
    return {"select_index": select_index}


class PickerTests(unittest.TestCase):
    def setUp(self):
        self.stats = {
            "100": {
                "story_id": "100",
                "choices": {
                    "0": {"count": 10, "avg_score": 16000, "best_score": 20000},
                    "1": {"count": 8,  "avg_score": 12000, "best_score": 14000},
                },
                "best_choice": "0",
                "confidence": 1.0,
                "sample_count": 18,
            },
        }
        self.choices = [_choice(1), _choice(2)]

    def test_returns_none_when_no_stats_for_story(self):
        self.assertIsNone(pick_learned_choice(self.stats, "99999", self.choices))

    def test_returns_none_when_stats_empty(self):
        self.assertIsNone(pick_learned_choice({}, "100", self.choices))

    def test_high_confidence_picks_best_every_time(self):
        rng = random.Random(0)
        picks = [pick_learned_choice(self.stats, "100", self.choices, rng=rng) for _ in range(20)]
        # At confidence=1.0, exploration is zero — always pick the best (idx 0).
        self.assertTrue(all(p == 0 for p in picks))

    def test_moderate_confidence_explores_occasionally(self):
        stats = dict(self.stats)
        stats["100"] = dict(stats["100"])
        stats["100"]["confidence"] = 0.3  # not-yet-confident
        # Add an under-sampled alternative so exploration has somewhere to go.
        stats["100"]["choices"] = {
            "0": {"count": 10, "avg_score": 16000, "best_score": 20000},
            "1": {"count": 1,  "avg_score": 9000,  "best_score": 9000},
        }
        rng = random.Random(0)
        picks = [pick_learned_choice(stats, "100", self.choices, rng=rng) for _ in range(200)]
        # Most picks should still be the best (idx 0).
        best_picks = sum(1 for p in picks if p == 0)
        explore_picks = sum(1 for p in picks if p == 1)
        self.assertGreater(best_picks, explore_picks * 3)
        # But there should be at least some exploration.
        self.assertGreater(explore_picks, 0)

    def test_returns_none_if_best_choice_not_in_provided_choices(self):
        """If the API offered fewer choices than the historical stats,
        defer instead of forcing an out-of-range branch."""
        new_choices = [_choice(1)]
        self.assertIsNone(pick_learned_choice(
            {
                "100": {
                    "story_id": "100",
                    "choices": {"2": {"count": 5, "avg_score": 16000, "best_score": 16000}},
                    "best_choice": "2",
                    "confidence": 1.0,
                    "sample_count": 5,
                }
            },
            "100",
            new_choices,
        ))

    def test_prefers_matching_context_when_available(self):
        stats = {
            "700": {
                "story_id": "700",
                "choices": {
                    "0": {"count": 10, "avg_score": 15000, "best_score": 18000},
                    "1": {"count": 10, "avg_score": 14900, "best_score": 18100},
                },
                "best_choice": "0",
                "confidence": 0.1,
                "sample_count": 20,
                "contexts": {
                    "phase=late|blue=stamina": {
                        "context_key": "phase=late|blue=stamina",
                        "choices": {
                            "0": {"count": 5, "avg_score": 13000, "best_score": 15000},
                            "1": {"count": 5, "avg_score": 16500, "best_score": 18000},
                        },
                        "best_choice": "1",
                        "confidence": 1.0,
                        "sample_count": 10,
                    },
                },
            },
        }
        pick = pick_learned_choice(
            stats,
            "700",
            self.choices,
            current_turn=62,
            preset={"desired_parent_sparks": {"blue": ["Stamina"]}},
        )
        self.assertEqual(pick, 1)


class MantStrategyEventPickerTests(unittest.TestCase):
    """choose_from_event reads learned stats off self.preset (cached
    by next_decision) and falls back to the curated EventManager / a
    static default when no learned signal is available."""

    def _event(self, story_id, select_indices):
        return {
            "event_id": 9999,
            "story_id": str(story_id),
            "chara_id": 1,
            "event_contents_info": {
                "choice_array": [{"select_index": idx} for idx in select_indices],
            },
        }

    def test_learner_overrides_default_when_stats_exist(self):
        from career_bot.scenarios.mant import MantStrategy
        strategy = MantStrategy()
        strategy.preset = {
            "event_choice_stats": {
                "500": {
                    "story_id": "500",
                    "choices": {
                        "0": {"count": 10, "avg_score": 16000, "best_score": 20000},
                        "1": {"count": 8,  "avg_score": 12000, "best_score": 14000},
                    },
                    "best_choice": "0",
                    "confidence": 1.0,
                    "sample_count": 18,
                },
            },
        }
        event = self._event("500", [1, 2])
        # Returns the select_index that maps to the best choice — 1.
        self.assertEqual(strategy.choose_from_event(event, current_turn=10), 0)

    def test_falls_back_to_default_when_no_learner_signal(self):
        from career_bot.scenarios.mant import MantStrategy
        strategy = MantStrategy()
        strategy.preset = {}
        # No event_manager either → falls all the way to default (1).
        event = self._event("99999", [1, 2])
        self.assertEqual(strategy.choose_from_event(event, current_turn=10), 1)

    def test_falls_back_when_no_preset_cached_yet(self):
        from career_bot.scenarios.mant import MantStrategy
        strategy = MantStrategy()
        # preset=None (e.g., very first event of a career before
        # next_decision ran). Must not crash.
        self.assertEqual(strategy.choose_from_event(self._event("100", [1, 2]), current_turn=1), 1)

    def test_riko_unlock_uses_middle_choice_even_with_duplicate_select_indices(self):
        from career_bot.scenarios.mant import MantStrategy
        strategy = MantStrategy()
        strategy.preset = {}
        event = self._event("809006004", [2, 1, 1])
        # Live GLB captures expose duplicate select_index values here; the
        # reliable choice is the displayed middle branch, not select_index=2.
        self.assertEqual(strategy.choose_from_event(event, current_turn=11), 1)

    def test_riko_normal_outing_keeps_middle_choice(self):
        from career_bot.scenarios.mant import MantStrategy
        strategy = MantStrategy()
        strategy.preset = {}
        event = self._event("809006007", [1, 2, 3])
        self.assertEqual(strategy.choose_from_event(event, current_turn=32), 1)


if __name__ == "__main__":
    unittest.main()
