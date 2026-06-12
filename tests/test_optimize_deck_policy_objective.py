"""Objective-function contract for the sim policy optimizer."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.optimize_deck_policy import _objective_score


class _Result:
    def __init__(self, rating, losses, wins=5):
        self.rating_score = rating
        self.races_run = [{"won": True}] * wins + [{"won": False}] * losses


class CleanRateObjectiveTests(unittest.TestCase):
    def test_clean_rate_primary_term(self):
        half_clean = [_Result(15000, 0), _Result(15000, 2)]
        no_clean = [_Result(17000, 1), _Result(17000, 1)]
        self.assertGreater(
            _objective_score(half_clean, "clean_rate"),
            _objective_score(no_clean, "clean_rate"),
        )

    def test_loss_count_gradient_when_no_career_is_clean(self):
        """With a 0/N clean field, fewer mean losses must still win —
        otherwise the production cadence cannot rank candidates at all
        while clean careers are rare."""
        fewer_losses = [_Result(14000, 1), _Result(14000, 2)]
        more_losses = [_Result(16000, 4), _Result(16000, 5)]
        self.assertGreater(
            _objective_score(fewer_losses, "clean_rate"),
            _objective_score(more_losses, "clean_rate"),
        )

    def test_rating_breaks_exact_ties(self):
        low = [_Result(14000, 1)]
        high = [_Result(16000, 1)]
        self.assertGreater(
            _objective_score(high, "clean_rate"),
            _objective_score(low, "clean_rate"),
        )

    def test_clean_rate_step_dominates_loss_term(self):
        """A candidate with one clean career out of 8 must outrank a
        zero-clean candidate even if the latter averages fewer losses."""
        one_clean = [_Result(15000, 0)] + [_Result(15000, 3)] * 7
        zero_clean = [_Result(15000, 1)] * 8
        self.assertGreater(
            _objective_score(one_clean, "clean_rate"),
            _objective_score(zero_clean, "clean_rate"),
        )


if __name__ == "__main__":
    unittest.main()
