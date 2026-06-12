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


class CandidatePoolTests(unittest.TestCase):
    def test_incumbent_seeds_pool_verbatim_and_local(self):
        import random
        from tools.optimize_deck_policy import PARAM_SPACE, _build_candidate_pool
        incumbent = {name: low for name, low, _high in PARAM_SPACE}
        pool = _build_candidate_pool(random.Random(1), 10, incumbent)
        self.assertEqual(len(pool), 10)
        self.assertEqual(pool[0], incumbent)
        bounds = {name: (low, high) for name, low, high in PARAM_SPACE}
        for cand in pool:
            for name, value in cand.items():
                low, high = bounds[name]
                self.assertGreaterEqual(value, low, name)
                self.assertLessEqual(value, high, name)

    def test_no_incumbent_means_all_random(self):
        import random
        from tools.optimize_deck_policy import _build_candidate_pool
        pool = _build_candidate_pool(random.Random(2), 6, None)
        self.assertEqual(len(pool), 6)

    def test_perturbation_stays_in_bounds_and_near_base(self):
        import random
        from tools.optimize_deck_policy import PARAM_SPACE, _perturb_candidate
        base = {name: (low + high) / 2 for name, low, high in PARAM_SPACE}
        rng = random.Random(3)
        for _ in range(50):
            cand = _perturb_candidate(base, rng)
            for name, low, high in PARAM_SPACE:
                self.assertGreaterEqual(cand[name], low)
                self.assertLessEqual(cand[name], high)


if __name__ == "__main__":
    unittest.main()
