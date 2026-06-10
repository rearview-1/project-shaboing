"""Golden-file tests for the auto-tuner.

Locks the tuner's output for known fixture inputs. A refactor of any tune_*
function that silently changes its output for the same inputs will trigger
a test failure here, surfacing the regression immediately instead of
letting it drift into the bot's careers unnoticed.

How to add a new fixture:
  1. Drop a career-log JSON or a synthetic sample dict into
     `tests/fixtures/tuner_inputs/<name>.json`.
  2. Add a corresponding expected output to
     `tests/fixtures/tuner_outputs/<name>.json`.
  3. Add a test method here that loads the fixture and asserts the
     tune_* output matches.

How to update a golden after a deliberate behavior change:
  1. Run `python tests/test_tuner_goldens.py --regenerate` to refresh
     the expected outputs from current code.
  2. Inspect the diff. If it matches the change you meant to make, commit.
  3. If it doesn't, you have an unintended regression — investigate.

This isn't a hermetic full-career test (that needs lots of data). It's a
small-fixture test that pins the math of individual tune_* functions
against representative inputs.
"""

import json
import sys
import unittest
from pathlib import Path

from career_bot.learning import (
    action_distribution,
    tune_base_score,
    tune_extra_weight,
    weighted_action_distribution,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "tuner_goldens"
FIXTURE_DIR.mkdir(parents=True, exist_ok=True)


def _make_synthetic_action(idx, period, extra_phase, weighted_gain=20.0, rainbow=0):
    return {
        "idx": idx,
        "period": period,
        "extra_phase": extra_phase,
        "turn": period * 16 + 4,
        "weighted_gain": weighted_gain,
        "rainbow_count": rainbow,
        "hint_count": 0,
        "partner_count": 3,
        "deck_partner_count": 3,
        "failure_rate": 5,
        "hp": 80.0,
        "stat_gain": {"speed": weighted_gain * 0.4},
        "skill_point": weighted_gain * 0.1,
    }


def _stable_top_samples():
    """Synthetic high-quality top samples — Speed-focused with rainbows in
    each period. Deterministic so the golden output never drifts from
    fixture noise."""
    return [
        {
            "source": "manual_hachimi",
            "score": 20000,
            "sample_weight": 1.45,
            "actions": [
                _make_synthetic_action(idx=0, period=p, extra_phase=p % 4, weighted_gain=40, rainbow=2)
                for p in range(5)
            ] + [
                _make_synthetic_action(idx=2, period=p, extra_phase=p % 4, weighted_gain=20, rainbow=0)
                for p in range(5)
            ],
        }
    ]


def _stable_bottom_samples():
    """Synthetic low-quality bottom samples — uniform weak training across
    all five command types, no rainbows."""
    return [
        {
            "source": "bot",
            "score": 7000,
            "sample_weight": 1.0,
            "actions": [
                _make_synthetic_action(idx=idx, period=p, extra_phase=p % 4, weighted_gain=8, rainbow=0)
                for idx in range(5) for p in range(5)
            ],
        }
    ]


def _load_or_record(name, regenerate=False):
    path = FIXTURE_DIR / f"{name}.json"
    if regenerate or not path.exists():
        return None, path
    return json.loads(path.read_text(encoding="utf-8")), path


def _save_golden(value, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


class TunerGoldenTests(unittest.TestCase):
    def _check_or_record(self, name, value):
        import os
        regenerate = bool(os.environ.get("TUNER_GOLDENS_REGENERATE"))
        golden, path = _load_or_record(name, regenerate=regenerate)
        if regenerate or golden is None:
            _save_golden(value, path)
            self.skipTest(f"recorded golden {path}")
        # Use a string comparison for stable diffs in CI output.
        actual = json.dumps(value, indent=2, sort_keys=True)
        expected = json.dumps(golden, indent=2, sort_keys=True)
        if actual != expected:
            self.fail(
                f"Golden mismatch for {name}.\n"
                f"Expected (from {path}):\n{expected}\n\n"
                f"Got:\n{actual}\n\n"
                f"If this is intentional, re-run with --regenerate to update."
            )

    def test_tune_extra_weight_synthetic_speed_focused(self):
        top_dist = action_distribution(_stable_top_samples())
        bottom_dist = action_distribution(_stable_bottom_samples())
        preset = {"extra_weight": [[0.0] * 5 for _ in range(4)]}
        result = tune_extra_weight(preset, top_dist, bottom_dist)
        self._check_or_record("tune_extra_weight_synthetic_speed_focused", result)

    def test_tune_base_score_synthetic_speed_focused(self):
        top_dist = action_distribution(_stable_top_samples())
        bottom_dist = action_distribution(_stable_bottom_samples())
        preset = {"base_score": [0.0] * 5}
        result = tune_base_score(preset, top_dist, bottom_dist)
        self._check_or_record("tune_base_score_synthetic_speed_focused", result)

    def test_weighted_distribution_action_count_stable(self):
        # Locks the action count emitted by weighted_action_distribution
        # against the synthetic top fixture. A bug that double-counts or
        # zero-counts actions would show here as a stable-number mismatch.
        from career_bot.decision_quality import annotate_actions_with_quality

        samples = _stable_top_samples()
        for s in samples:
            annotate_actions_with_quality(s)
        dist = weighted_action_distribution(samples)
        result = {
            "action_count": dist["action_count"],
            "average_quality": dist["average_quality"],
        }
        self._check_or_record("weighted_distribution_action_count_stable", result)


if __name__ == "__main__":
    # Pop --regenerate before unittest's argument parser sees it.
    if "--regenerate" in sys.argv:
        import os
        os.environ["TUNER_GOLDENS_REGENERATE"] = "1"
        sys.argv = [arg for arg in sys.argv if arg != "--regenerate"]
    unittest.main()
