"""Hygiene 1 weight-floor clamps must hold at the persistence boundary.

The pre-existing in-build clamp (inside `_build_policy_model_from_rows`)
only ran when a NEW model was built from row deltas. During challenger
staging, `learn_preset` re-saved the OLD `active_model` without re-running
the clamp — so any model that predated the clamp added by Codex (or any
model whose weights drifted out of bounds in some other code path) kept
its violations indefinitely, until the staged challenger promoted.

These tests pin the new public API (`apply_weight_floor_clamps`,
`enforce_model_floors`) and the in-build path so future refactors can't
re-introduce the leak.
"""

import unittest

from career_bot.training_policy import (
    WEIGHT_CEILING_CLAMPS,
    WEIGHT_FLOOR_CLAMPS,
    apply_weight_floor_clamps,
    enforce_model_floors,
)


class WeightFloorClampTests(unittest.TestCase):
    def test_negative_zero_floor_features_get_lifted_to_zero(self):
        weights = {
            "lagging_stat_alignment": -0.05,
            "rainbow_count": -0.11,
            "high_bond_count": -0.06,
            "race_demand_pressure": -0.005,
            "rainbow_setup_pressure": -0.008,
        }
        apply_weight_floor_clamps(weights)
        for name in (
            "lagging_stat_alignment", "rainbow_count", "high_bond_count",
            "race_demand_pressure", "rainbow_setup_pressure",
        ):
            self.assertGreaterEqual(weights[name], 0.0, msg=f"{name} below 0.0 floor")

    def test_positive_floor_features_get_lifted_when_below(self):
        weights = {
            "first_summer_friendship_pressure": -0.01,
            "friendship_unlocked_gap": 0.005,
        }
        apply_weight_floor_clamps(weights)
        self.assertGreaterEqual(weights["first_summer_friendship_pressure"], 0.02)
        self.assertGreaterEqual(weights["friendship_unlocked_gap"], 0.02)

    def test_positive_floor_features_get_inserted_when_missing(self):
        """If a feature with a positive floor isn't in the model at all,
        the clamp pass should insert it at the floor value."""
        weights = {}
        reasons = {}
        apply_weight_floor_clamps(weights, reasons=reasons)
        self.assertIn("first_summer_friendship_pressure", weights)
        self.assertIn("friendship_unlocked_gap", weights)
        self.assertEqual(reasons.get("first_summer_friendship_pressure"), "floor_clamp")
        self.assertEqual(reasons.get("friendship_unlocked_gap"), "floor_clamp")

    def test_weights_above_floor_are_preserved(self):
        weights = {
            "lagging_stat_alignment": 0.15,
            "rainbow_count": 0.08,
            "first_summer_friendship_pressure": 0.05,
        }
        apply_weight_floor_clamps(weights)
        self.assertAlmostEqual(weights["lagging_stat_alignment"], 0.15, places=5)
        self.assertAlmostEqual(weights["rainbow_count"], 0.08, places=5)
        self.assertAlmostEqual(weights["first_summer_friendship_pressure"], 0.05, places=5)

    def test_non_dict_input_is_returned_unchanged(self):
        self.assertIsNone(apply_weight_floor_clamps(None))
        self.assertEqual(apply_weight_floor_clamps("not a dict"), "not a dict")


class EnforceModelFloorsTests(unittest.TestCase):
    """`enforce_model_floors` is the persistence-boundary guardrail.

    Called from `learn_preset` before saving `training_policy_model`,
    even when the model is a stale `active_model` preserved by a
    challenger-staging decision. Re-applies the clamps to feature_weights
    so no save path can leak a violation.
    """

    def test_full_model_with_violations_gets_clamped(self):
        model = {
            "schema": "sweepy_training_policy_v1",
            "enabled": True,
            "feature_weights": {
                "lagging_stat_alignment": -0.04566,
                "rainbow_count": -0.1107,
                "high_bond_count": -0.0583,
                "first_summer_friendship_pressure": -0.01039,
                "friendship_unlocked_gap": -0.00509,
                "weighted_gain": 0.019,
            },
        }
        enforce_model_floors(model)
        fw = model["feature_weights"]
        self.assertGreaterEqual(fw["lagging_stat_alignment"], 0.0)
        self.assertGreaterEqual(fw["rainbow_count"], 0.0)
        self.assertGreaterEqual(fw["high_bond_count"], 0.0)
        self.assertGreaterEqual(fw["first_summer_friendship_pressure"], 0.02)
        self.assertGreaterEqual(fw["friendship_unlocked_gap"], 0.02)
        # Non-clamped features unchanged.
        self.assertAlmostEqual(fw["weighted_gain"], 0.019, places=5)

    def test_empty_model_is_returned_unchanged(self):
        # No feature_weights → nothing to clamp.
        self.assertEqual(enforce_model_floors({}), {})
        self.assertEqual(enforce_model_floors({"enabled": False}), {"enabled": False})

    def test_none_model_is_returned_unchanged(self):
        self.assertIsNone(enforce_model_floors(None))

    def test_model_with_dict_reasons_gets_floor_clamp_annotated(self):
        model = {
            "feature_weights": {},
            "feature_include_reasons": {},
        }
        enforce_model_floors(model)
        reasons = model["feature_include_reasons"]
        # Positive-floor features should have been inserted with a reason.
        self.assertEqual(reasons.get("first_summer_friendship_pressure"), "floor_clamp")
        self.assertEqual(reasons.get("friendship_unlocked_gap"), "floor_clamp")

    def test_real_world_violating_model_matches_documented_pattern(self):
        """Snapshot of the actual account_b violating model that prompted
        this fix. Verifies all 7 documented violations are healed."""
        # From learning_report_20260522_030759.json feature_weights:
        model = {
            "feature_weights": {
                "rainbow_count": -0.1107,
                "high_bond_count": -0.0583,
                "lagging_stat_alignment": -0.04566,
                "race_demand_pressure": -0.00664,
                "rainbow_setup_pressure": -0.00758,
                "first_summer_friendship_pressure": -0.01039,
                "friendship_unlocked_gap": -0.00509,
            }
        }
        enforce_model_floors(model)
        fw = model["feature_weights"]
        # All Hygiene 1 floors now hold.
        for name, floor in WEIGHT_FLOOR_CLAMPS.items():
            if name in fw:
                self.assertGreaterEqual(
                    float(fw[name]), float(floor),
                    msg=f"{name} = {fw[name]} did not clear floor {floor}",
                )


class WeightCeilingClampTests(unittest.TestCase):
    """Negative-domain features must never go positive.

    `failure_rate` going positive in the policy model would teach the
    bot that more training failure correlates with better outcomes —
    domain-nonsense. Same for `low_hp` and `facility_is_max_level`.
    These get a ceiling at 0.0.
    """

    def test_failure_rate_positive_value_gets_clamped_to_zero(self):
        weights = {"failure_rate": 0.013}
        apply_weight_floor_clamps(weights)
        self.assertLessEqual(weights["failure_rate"], 0.0)

    def test_low_hp_positive_value_gets_clamped_to_zero(self):
        weights = {"low_hp": 0.025}
        apply_weight_floor_clamps(weights)
        self.assertLessEqual(weights["low_hp"], 0.0)

    def test_negative_values_below_ceiling_are_preserved(self):
        weights = {"failure_rate": -0.05, "low_hp": -0.02}
        apply_weight_floor_clamps(weights)
        self.assertAlmostEqual(weights["failure_rate"], -0.05, places=5)
        self.assertAlmostEqual(weights["low_hp"], -0.02, places=5)

    def test_extended_positive_floor_features_get_clamped(self):
        """Post-Wave-0 audit added 11 more positive-domain features.
        Each must clamp upward when negative."""
        weights = {
            "near_rainbow_count": -0.04,
            "near_rainbow_deck_count": -0.02,
            "hint_count": -0.008,
            "partner_count": -0.015,
            "deck_partner_count": -0.014,
            "weighted_gain": -0.007,
            "stat_gain": -0.008,
            "skill_point_gain": -0.005,
            "hp_ratio": -0.025,
            "facility_levelup_next_train": -0.01,
            "facility_level": -0.058,
        }
        apply_weight_floor_clamps(weights)
        for name in weights:
            self.assertGreaterEqual(weights[name], 0.0, msg=f"{name} did not clamp to floor 0")

    def test_real_world_post_wave0_violations_all_resolve(self):
        """The 8 wrong-signed features observed AFTER Wave 0's clean
        rebuild. After extended clamps, all 8 must be correctly signed."""
        # Snapshot from account_b's first post-Wave-0 model:
        weights = {
            "hint_count": -0.00819,
            "partner_count": -0.01491,
            "deck_partner_count": -0.01379,
            "weighted_gain": -0.00738,
            "stat_gain": -0.00805,
            "hp_ratio": -0.02461,
            "facility_level": -0.05838,
            "facility_is_max_level": -0.03122,
            "failure_rate": 0.01309,
            "low_hp": 0.02487,
        }
        apply_weight_floor_clamps(weights)
        # All positive-domain features at or above 0
        for name in ("hint_count", "partner_count", "deck_partner_count",
                     "weighted_gain", "stat_gain", "hp_ratio", "facility_level"):
            self.assertGreaterEqual(weights[name], 0.0, msg=f"{name} = {weights[name]}")
        # All negative-domain features at or below 0
        for name in ("failure_rate", "low_hp", "facility_is_max_level"):
            self.assertLessEqual(weights[name], 0.0, msg=f"{name} = {weights[name]}")


class ClampCoverageTests(unittest.TestCase):
    """Floor + ceiling lists shouldn't overlap (a feature can't both
    have a floor and a ceiling) and together should cover every feature
    with a documented domain sign."""

    def test_floor_and_ceiling_clamps_dont_overlap(self):
        overlap = set(WEIGHT_FLOOR_CLAMPS.keys()) & set(WEIGHT_CEILING_CLAMPS.keys())
        self.assertEqual(overlap, set(), msg=f"Features in both: {overlap}")


if __name__ == "__main__":
    unittest.main()
