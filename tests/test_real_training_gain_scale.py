"""Tests for the real-training-gain scale calibration.

The constant `REAL_TRAINING_GAIN_SCALE_DEFAULT` multiplies the per-tile
stat values that come from real-bot training snapshots. It was originally
1.28, calibrated to match old-bot data when real careers landed around
A/A+. The bot has improved substantially (real distribution: 9 SS, 55 S+,
60 S, 15 A+, 1 UG across 140 finished careers) so the previous scale
under-shot by ~2,200 rating per career.

These tests lock the new calibration at 1.85 — chosen because a 10-sim
sweep showed:
  - 1.65 → mean 15,464 (0% SS, 10% S+, 80% S)  — too conservative
  - 1.85 → mean 16,347 (0% SS, 70% S+, 30% S)  — matches real S+ centroid
  - 2.00 → mean 16,391 (10% SS, 60% S+, 30% S) — slightly over

If real-career distribution shifts again, update the constant and these
tests together — don't silently mismatch the calibration.
"""
from career_bot.career_simulator import (
    REAL_TRAINING_GAIN_SCALE_DEFAULT,
    REAL_TRAINING_GAIN_SCALE_MAX_DECK_BONUS,
    REAL_TRAINING_GAIN_SCALE_DECK_QUALITY_STEP,
)


def test_real_training_gain_scale_default_matches_current_bot():
    """1.85 matches the bot's current S+ centroid in real careers.

    If this fails because the bot improved further (e.g., consistently
    hitting SS), raise to a higher value AND update the test. If it
    fails because someone tried to revert to old 1.28 calibration,
    that's a regression — block the revert."""
    assert REAL_TRAINING_GAIN_SCALE_DEFAULT == 1.85, (
        "Expected 1.85 to match real-bot S+ centroid (mean ~16,500). "
        "Old 1.28 produced ~14,100 mean which under-shot reality by ~2,200 "
        "rating per career."
    )


def test_deck_quality_bonus_enabled():
    """The deck-quality bonus was off (0.0) in the old calibration to
    avoid over-prediction. With improved bot performance and the lifted
    base scale, a small positive bonus is appropriate so high-deck users
    aren't artificially capped."""
    assert REAL_TRAINING_GAIN_SCALE_MAX_DECK_BONUS > 0, (
        "Deck-quality bonus disabled — re-enable so high-quality decks "
        "aren't predicted to perform identically to baseline decks."
    )
    assert REAL_TRAINING_GAIN_SCALE_MAX_DECK_BONUS <= 0.25, (
        "Deck-quality bonus too high — risks over-predicting SS for "
        "high-deck users."
    )


def test_deck_quality_step_is_modest():
    """Per-quality-tier step shouldn't explode the scale even with max
    quality. With baseline=3.0 and step=0.08, a fully maxed deck (quality
    ~5.0) adds (5.0-3.0)*0.08 = 0.16 to the scale on top of the base —
    capped at MAX_DECK_BONUS=0.10."""
    assert REAL_TRAINING_GAIN_SCALE_DECK_QUALITY_STEP <= 0.16, (
        "Step too aggressive — would push high-quality decks past the cap."
    )
