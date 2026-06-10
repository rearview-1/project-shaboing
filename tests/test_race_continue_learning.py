"""Race-continue / carat-retry learning.

Aggregates per-(program_id, resource_type) recovery rates from past
career race-continue chains, exposes a decision the runner consults
before spending another continue resource at the same race. NOT a
race-skip mechanism — only fires AFTER a race has already been lost,
deciding whether the continue is worth burning."""

import unittest

from career_bot.race_continue_learning import (
    MIN_ATTEMPTS_FOR_DECISION,
    MIN_RECOVERY_RATE_FOR_CONTINUE,
    aggregate_continue_outcomes,
    should_attempt_continue,
)


def _race_result(program_id, won, continued=True, resources=None):
    return {
        "event": "race_result",
        "program_id": program_id,
        "won": won,
        "continued": continued,
        "continue_resources": list(resources or []),
    }


def _sample_with_race_results(rows):
    """Newer sample shape: race_results pulled into a flat field by
    `_extract_race_results_from_turns`."""
    return {"race_results": list(rows)}


def _sample_with_turns(rows):
    """Older shape: race_result rows nested inside per-turn events."""
    return {"turns": [{"events": list(rows)}]}


class AggregationTests(unittest.TestCase):
    def test_skips_races_without_continued_flag(self):
        samples = [_sample_with_race_results([
            _race_result(11017, won=True, continued=False),
        ])]
        self.assertEqual(aggregate_continue_outcomes(samples), {})

    def test_counts_attempts_and_recoveries_by_resource(self):
        # 3 continued races at program 11017 using carat_alarm_clock,
        # 2 of which won.
        samples = []
        samples.append(_sample_with_race_results([
            _race_result(11017, won=True,  resources=["carat_alarm_clock"]),
        ]))
        samples.append(_sample_with_race_results([
            _race_result(11017, won=True,  resources=["carat_alarm_clock"]),
        ]))
        samples.append(_sample_with_race_results([
            _race_result(11017, won=False, resources=["carat_alarm_clock"]),
        ]))
        stats = aggregate_continue_outcomes(samples)
        entry = stats["11017"]["carat_alarm_clock"]
        self.assertEqual(entry["attempts"], 3)
        self.assertEqual(entry["recoveries"], 2)
        self.assertAlmostEqual(entry["recovery_rate"], 0.667, places=3)

    def test_credits_only_the_last_resource_in_a_chain(self):
        """If the bot used [free_retry, alarm_clock] and won, only
        alarm_clock gets the recovery credit. free_retry attempted
        and failed (else there wouldn't have been a follow-up)."""
        samples = [_sample_with_race_results([
            _race_result(11017, won=True, resources=["free_retry", "alarm_clock"]),
        ])]
        stats = aggregate_continue_outcomes(samples)
        self.assertIn("alarm_clock", stats["11017"])
        self.assertNotIn("free_retry", stats["11017"])

    def test_works_with_legacy_turns_nested_event_shape(self):
        """Older career logs nested race_result rows inside per-turn
        events; aggregator must read both shapes."""
        samples = [_sample_with_turns([
            _race_result(11017, won=True, resources=["alarm_clock"]),
        ])]
        stats = aggregate_continue_outcomes(samples)
        self.assertEqual(stats["11017"]["alarm_clock"]["attempts"], 1)
        self.assertEqual(stats["11017"]["alarm_clock"]["recoveries"], 1)


class DecisionTests(unittest.TestCase):
    def test_defers_when_stats_empty(self):
        self.assertIsNone(should_attempt_continue({}, 11017, "alarm_clock"))

    def test_defers_when_program_unknown(self):
        stats = {"11017": {"alarm_clock": {"attempts": 5, "recoveries": 4, "recovery_rate": 0.8}}}
        self.assertIsNone(should_attempt_continue(stats, 99999, "alarm_clock"))

    def test_defers_when_resource_unknown(self):
        stats = {"11017": {"alarm_clock": {"attempts": 5, "recoveries": 4, "recovery_rate": 0.8}}}
        self.assertIsNone(should_attempt_continue(stats, 11017, "carats"))

    def test_defers_below_min_attempts(self):
        """With only 2 attempts (below MIN_ATTEMPTS_FOR_DECISION),
        sample size is too thin to skip the continue."""
        stats = {"11017": {"alarm_clock": {"attempts": 2, "recoveries": 0, "recovery_rate": 0.0}}}
        self.assertIsNone(should_attempt_continue(stats, 11017, "alarm_clock"))

    def test_rejects_low_recovery_rate(self):
        """5 attempts, 0 recoveries (or below MIN_RECOVERY_RATE_FOR_CONTINUE)
        → bot should stop burning this resource here."""
        stats = {"11017": {"carat_alarm_clock": {
            "attempts": 5, "recoveries": 0, "recovery_rate": 0.0,
        }}}
        self.assertFalse(should_attempt_continue(stats, 11017, "carat_alarm_clock"))

    def test_recommends_continue_when_recovery_rate_healthy(self):
        stats = {"11017": {"alarm_clock": {"attempts": 8, "recoveries": 5, "recovery_rate": 0.625}}}
        self.assertTrue(should_attempt_continue(stats, 11017, "alarm_clock"))

    def test_marginal_recovery_rate_above_threshold_still_allows(self):
        rate = MIN_RECOVERY_RATE_FOR_CONTINUE + 0.05
        stats = {"11017": {"alarm_clock": {"attempts": MIN_ATTEMPTS_FOR_DECISION, "recoveries": 1, "recovery_rate": rate}}}
        self.assertTrue(should_attempt_continue(stats, 11017, "alarm_clock"))


if __name__ == "__main__":
    unittest.main()
