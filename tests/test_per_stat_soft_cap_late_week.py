"""Tests for the late-week cap clamp on _per_stat_soft_cap.

Operator policy (2026-06-09): the per-stat soft cap is high (1200 for
main rating stats, 1000 for support stats) throughout most of the
career — letting the bot push freely — but **in the final training
stretch (late Oct senior, T >= 70 by default)** the cap snaps to a
firm 1100. Past 1100 the displayed-stat-value rating curve has
flattened, so further training is wasted; SP / skill / race-buffer
time matters more.

The clamp must win over expected_target, deck-card protections, and
tuned overrides — when the late-week window opens, 1100 is final.
"""
from career_bot.scenarios.mant import MantStrategy


def _make_scenario():
    """Build a minimal MantStrategy for unit testing the cap function."""
    return MantStrategy()


def _preset(**overrides):
    """Bare-bones preset, no learned overrides unless requested."""
    base = {
        "name": "test",
        "scenario_id": 4,
        "_deck_type_counts": [0, 0, 0, 0, 0],
    }
    base.update(overrides)
    return base


# Indices: 0=speed, 1=stamina, 2=power, 3=guts, 4=wit


def test_early_career_uses_raised_high_cap_default():
    """Before the late-week trigger, speed/power/wit get the new
    higher default of 1200 (was 1100)."""
    s = _make_scenario()
    p = _preset()
    # Turn 10 = junior year, well before the clamp
    cap_speed = s._per_stat_soft_cap(0, p, turn=10)
    cap_wit = s._per_stat_soft_cap(4, p, turn=10)
    assert cap_speed >= 1200.0, f"speed cap too low: {cap_speed}"
    assert cap_wit >= 1200.0, f"wit cap too low: {cap_wit}"


def test_early_career_uses_raised_low_cap_default():
    """Stamina/guts get the bumped default of 1000 (was 800) when not
    in spark stats."""
    s = _make_scenario()
    p = _preset()
    cap_stamina = s._per_stat_soft_cap(1, p, turn=10)
    cap_guts = s._per_stat_soft_cap(3, p, turn=10)
    assert cap_stamina >= 1000.0, f"stamina cap too low: {cap_stamina}"
    assert cap_guts >= 1000.0, f"guts cap too low: {cap_guts}"


def test_late_week_clamps_to_1100_for_all_stats():
    """T >= 70 → ALL stat caps snap to 1100 regardless of stat."""
    s = _make_scenario()
    p = _preset()
    for stat_idx in range(5):
        cap = s._per_stat_soft_cap(stat_idx, p, turn=70)
        assert cap == 1100.0, (
            f"stat {stat_idx} cap at T70 should be 1100, got {cap}"
        )


def test_late_week_clamp_overrides_expected_target():
    """If user has expect_attribute=[1200,...], the clamp should
    still force 1100 in the late window. Operator policy is final."""
    s = _make_scenario()
    p = _preset(expect_attribute=[1200, 1100, 1200, 1200, 1200])
    cap = s._per_stat_soft_cap(0, p, turn=72)
    assert cap == 1100.0, (
        f"late-week clamp must override expect_attribute=1200, got {cap}"
    )


def test_late_week_clamp_overrides_deck_count_protection():
    """A 2-Speed deck normally gets a 1200 floor (`tuned = max(tuned, 1200)`).
    Late-week clamp must still win — 1100 hard."""
    s = _make_scenario()
    p = _preset(_deck_type_counts=[2, 0, 0, 0, 0])  # 2 speed cards
    cap = s._per_stat_soft_cap(0, p, turn=70)
    assert cap == 1100.0, (
        f"late-week clamp must override deck-count protection, got {cap}"
    )


def test_late_week_clamp_overrides_tuned_value():
    """Auto-tuner might set wit_soft_cap=1175. Late-week clamp wins."""
    s = _make_scenario()
    p = _preset(learned_hyperparameters={"wit_soft_cap": 1175})
    cap = s._per_stat_soft_cap(4, p, turn=71)
    assert cap == 1100.0, (
        f"late-week clamp must override learned wit_soft_cap=1175, got {cap}"
    )


def test_clamp_trigger_is_configurable():
    """Operator can move the late-week trigger via the preset."""
    s = _make_scenario()
    # Move the trigger to T65
    p = _preset(learned_hyperparameters={"late_week_cap_turn": 65})
    # T64 → still in regular regime
    assert s._per_stat_soft_cap(0, p, turn=64) >= 1200.0
    # T65 → clamp activates
    assert s._per_stat_soft_cap(0, p, turn=65) == 1100.0


def test_clamp_value_is_configurable():
    """Operator can change the clamp value too."""
    s = _make_scenario()
    p = _preset(learned_hyperparameters={"late_week_hard_cap": 1150})
    cap = s._per_stat_soft_cap(0, p, turn=70)
    assert cap == 1150.0


def test_turn_none_means_no_clamp():
    """If caller doesn't pass turn (None), the clamp is skipped — keeps
    backwards-compat with any code path that hasn't been updated yet."""
    s = _make_scenario()
    p = _preset()
    cap = s._per_stat_soft_cap(0, p, turn=None)
    # No clamp → returns the regular high cap
    assert cap >= 1200.0


def test_just_before_clamp_window_still_uses_high_cap():
    """Boundary: T = trigger - 1 still gets the high cap, only at
    trigger turn does the clamp engage."""
    s = _make_scenario()
    p = _preset()
    # default trigger is 70
    cap_before = s._per_stat_soft_cap(0, p, turn=69)
    cap_at = s._per_stat_soft_cap(0, p, turn=70)
    assert cap_before >= 1200.0
    assert cap_at == 1100.0
