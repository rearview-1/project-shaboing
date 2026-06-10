import unittest

from career_bot.decision_quality import (
    annotate_actions_with_quality,
    combined_decision_quality,
    quality_multiplier,
    score_action,
    score_action_against_alternatives,
)
from career_bot.learning import weighted_action_distribution


def _action(weighted_gain=10.0, rainbow_count=0, hint_count=0, failure_rate=0, energy_delta=0, idx=0, period=2, extra_phase=2):
    return {
        "weighted_gain": weighted_gain,
        "rainbow_count": rainbow_count,
        "hint_count": hint_count,
        "failure_rate": failure_rate,
        "energy_delta": energy_delta,
        "idx": idx,
        "period": period,
        "extra_phase": extra_phase,
    }


class ScoreActionTests(unittest.TestCase):
    def test_dominant_term_is_weighted_gain(self):
        a = score_action(_action(weighted_gain=30))
        b = score_action(_action(weighted_gain=10))
        self.assertGreater(a, b)
        self.assertGreater(a, 25)

    def test_rainbow_adds_measurable_quality(self):
        plain = score_action(_action(weighted_gain=10, rainbow_count=0))
        rainbow = score_action(_action(weighted_gain=10, rainbow_count=2))
        self.assertGreater(rainbow, plain + 12)

    def test_high_failure_penalises(self):
        safe = score_action(_action(weighted_gain=20, failure_rate=0))
        risky = score_action(_action(weighted_gain=20, failure_rate=40))
        self.assertGreater(safe, risky)

    def test_negative_energy_penalises(self):
        balanced = score_action(_action(weighted_gain=20, energy_delta=0))
        drained = score_action(_action(weighted_gain=20, energy_delta=-25))
        self.assertGreater(balanced, drained)

    def test_positive_energy_does_not_penalise(self):
        plain = score_action(_action(weighted_gain=20, energy_delta=0))
        gain = score_action(_action(weighted_gain=20, energy_delta=15))
        self.assertEqual(plain, gain)

    def test_score_is_non_negative(self):
        terrible = _action(weighted_gain=0, failure_rate=99, energy_delta=-50)
        self.assertGreaterEqual(score_action(terrible), 0)


class SignalBTests(unittest.TestCase):
    def test_returns_zero_without_snapshot(self):
        self.assertEqual(score_action_against_alternatives(_action()), 0.0)

    def test_positive_when_chosen_beats_second_best(self):
        action = _action(weighted_gain=30)
        snapshot = {"trainings": [{"weighted_gain": 30}, {"weighted_gain": 18}, {"weighted_gain": 10}]}
        self.assertGreater(score_action_against_alternatives(action, snapshot), 10)

    def test_negative_when_better_alternative_existed(self):
        action = _action(weighted_gain=12)
        snapshot = {"trainings": [{"weighted_gain": 30}, {"weighted_gain": 22}, {"weighted_gain": 12}]}
        self.assertLess(score_action_against_alternatives(action, snapshot), 0)

    def test_forward_followthrough_improves_combined_quality(self):
        base = _action(weighted_gain=20)
        boosted = _action(weighted_gain=20)
        boosted["future_window_metrics"] = {
            "2": {"total_gain": 30, "partner_bond_gain": 8, "rainbow_unlocks": 1, "best_training_gain_delta": 18, "selected_partner_best_training_reuse": 1},
            "4": {"total_gain": 70, "partner_bond_gain": 12, "rainbow_unlocks": 1, "best_training_gain_delta": 28, "selected_partner_best_training_reuse": 1},
            "8": {"total_gain": 110, "partner_bond_gain": 16, "rainbow_unlocks": 1, "best_training_gain_delta": 32, "selected_partner_best_training_reuse": 1},
        }

        self.assertGreater(combined_decision_quality(boosted), combined_decision_quality(base))


class AnnotateTests(unittest.TestCase):
    def test_annotation_is_idempotent_and_attaches_field(self):
        sample = {"actions": [_action(weighted_gain=15, rainbow_count=1)]}
        annotate_actions_with_quality(sample)
        first = sample["actions"][0]["decision_quality"]
        annotate_actions_with_quality(sample)
        second = sample["actions"][0]["decision_quality"]
        self.assertEqual(first, second)
        self.assertGreater(first, 0)

    def test_handles_missing_actions_gracefully(self):
        sample = {}
        annotate_actions_with_quality(sample)  # should not raise


class QualityMultiplierTests(unittest.TestCase):
    def test_clamped_below_floor(self):
        self.assertEqual(quality_multiplier(1.0, baseline=20.0, floor=0.3), 0.3)

    def test_clamped_above_ceiling(self):
        self.assertEqual(quality_multiplier(100.0, baseline=20.0, ceiling=2.0), 2.0)

    def test_linear_in_normal_range(self):
        self.assertAlmostEqual(quality_multiplier(20.0, baseline=20.0), 1.0)


class WeightedActionDistributionTests(unittest.TestCase):
    def test_high_quality_actions_carry_more_weight_than_low(self):
        good_sample = {
            "sample_weight": 1.0,
            "score": 20000,
            "actions": [
                _action(weighted_gain=40, rainbow_count=2, idx=0, period=2),
                _action(weighted_gain=40, rainbow_count=2, idx=0, period=2),
            ],
        }
        bad_sample = {
            "sample_weight": 1.0,
            "score": 20000,
            "actions": [
                _action(weighted_gain=8, rainbow_count=0, failure_rate=20, idx=1, period=2),
                _action(weighted_gain=8, rainbow_count=0, failure_rate=20, idx=1, period=2),
            ],
        }
        annotate_actions_with_quality(good_sample)
        annotate_actions_with_quality(bad_sample)
        dist = weighted_action_distribution([good_sample, bad_sample])
        period = dist["by_period"][2]
        # idx 0 (high-quality) should outweigh idx 1 (low-quality)
        self.assertGreater(period[0]["count"], period[1]["count"] * 1.5)

    def test_reports_average_quality(self):
        sample = {
            "sample_weight": 1.0,
            "score": 12000,
            "actions": [_action(weighted_gain=20, idx=0, period=2) for _ in range(3)],
        }
        annotate_actions_with_quality(sample)
        dist = weighted_action_distribution([sample])
        self.assertGreater(dist["average_quality"], 0)
        self.assertEqual(dist["action_count"], 3)

    def test_great_decision_in_mediocre_career_is_not_silenced(self):
        good_career_mediocre_decision = {
            "sample_weight": 0.8,
            "score": 17000,
            "actions": [_action(weighted_gain=6, idx=0, period=2)],
        }
        mediocre_career_great_decision = {
            "sample_weight": 0.3,
            "score": 14000,
            "actions": [_action(weighted_gain=40, rainbow_count=2, idx=1, period=2)],
        }
        annotate_actions_with_quality(good_career_mediocre_decision)
        annotate_actions_with_quality(mediocre_career_great_decision)

        dist = weighted_action_distribution([good_career_mediocre_decision, mediocre_career_great_decision])
        period = dist["by_period"][2]

        self.assertGreaterEqual(period[1]["count"], period[0]["count"])


if __name__ == "__main__":
    unittest.main()
