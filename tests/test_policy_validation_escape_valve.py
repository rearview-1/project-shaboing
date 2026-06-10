"""Training-policy validation tolerance.

Default tolerance was loosened from 0.985 → 0.96 so the validator has
more headroom to accept a marginally-different model without rejecting
every new fit. Large regressions still reject — the loosening only
helps with normal model drift between learning passes.

There is intentionally NO force-promote escape valve: promoting a
model fit to all-losses data would just teach the bot to repeat the
losing pattern. The right fix for stuck-loss cycles lives in
race_style_overrides + aptitude gate + postmortem feedback, not in
bypassing validation.
"""

import unittest

from career_bot.learning import _shadow_challenger_update


def _model(enabled=True, weights=None):
    return {
        "enabled": enabled,
        "feature_weights": weights or {"stat_gain": 0.02},
        "command_bias": {},
        "period_command_bias": {},
    }


class ValidationToleranceTests(unittest.TestCase):
    def test_minor_drop_within_loosened_tolerance_passes_to_margin_check(self):
        """At default tolerance 0.96, a 2% drop on top samples is no
        longer auto-rejected. It falls through to the margin/staging
        logic instead of `rejected_keep_old`."""
        old = _model()
        new = _model(weights={"stat_gain": 0.022})
        decision = _shadow_challenger_update(
            preset={"training_policy_challenger_enabled": True},
            old_model=old,
            new_model=new,
            old_score=0.10,
            new_score=0.098,        # 2% drop
            old_holdout_score=0.10,
            new_holdout_score=0.099,  # 1% drop
            validation_tolerance=0.96,
        )
        self.assertNotEqual(decision["decision"], "rejected_keep_old")

    def test_large_drop_still_rejects(self):
        """Even with the loosened default, a large regression (>4%)
        still rejects. The looser tolerance is meant to accept drift,
        not to wave through models that legitimately regressed."""
        old = _model()
        new = _model(weights={"stat_gain": 0.022})
        decision = _shadow_challenger_update(
            preset={},
            old_model=old,
            new_model=new,
            old_score=0.10,
            new_score=0.080,        # 20% drop on top
            old_holdout_score=0.10,
            new_holdout_score=0.099,
            validation_tolerance=0.96,
        )
        self.assertEqual(decision["decision"], "rejected_keep_old")

    def test_holdout_regression_still_rejects(self):
        """If recent-careers holdout regresses past tolerance, still
        reject even if top-samples score holds."""
        old = _model()
        new = _model(weights={"stat_gain": 0.022})
        decision = _shadow_challenger_update(
            preset={},
            old_model=old,
            new_model=new,
            old_score=0.10,
            new_score=0.099,        # 1% drop on top — within tolerance
            old_holdout_score=0.10,
            new_holdout_score=0.085,  # 15% drop on recent — beyond tolerance
            validation_tolerance=0.96,
        )
        self.assertEqual(decision["decision"], "rejected_keep_old")

    def test_low_confidence_holdout_does_not_reject_by_itself(self):
        old = _model()
        new = _model(weights={"stat_gain": 0.023})
        decision = _shadow_challenger_update(
            preset={},
            old_model=old,
            new_model=new,
            old_score=0.10,
            new_score=0.105,
            old_holdout_score=0.10,
            new_holdout_score=0.080,
            validation_tolerance=0.96,
            recent_holdout_count=1,
        )

        self.assertNotEqual(decision["decision"], "rejected_keep_old")
        self.assertTrue(decision["validation_confidence"]["low_confidence_holdout"])


if __name__ == "__main__":
    unittest.main()
