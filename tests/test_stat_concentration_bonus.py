"""Tests for `_stat_concentration_bonus`.

Operator policy: "stat capped or slightly below cap, not overcapped."
The bonus pushes each stat toward its per-stat soft cap (1100 for
speed/power/wit, 800 for stamina/guts, overridable per-preset) and
falls to zero once the stat reaches that cap.
"""

from career_bot.scenarios.mant import MantStrategy


def _command(*stat_gains):
    return {
        "params_inc_dec_info_array": [
            {"target_type": t, "value": v} for t, v in stat_gains
        ]
    }


def test_dormant_before_senior():
    s = MantStrategy(None)
    chara = {"speed": 900, "stamina": 600, "power": 700, "guts": 400, "wiz": 500}
    bonus = s._stat_concentration_bonus(_command((1, 10)), chara, {}, turn=30)
    assert bonus == 0.0


def test_dormant_below_ramp_start():
    """Stat below 55% of its soft cap → no bonus (not ready to push)."""
    s = MantStrategy(None)
    # Speed at 500 / soft_cap 1100 = 0.45, under ramp_start 0.55
    chara = {"speed": 500, "stamina": 300, "power": 700, "guts": 400, "wiz": 500}
    bonus = s._stat_concentration_bonus(_command((1, 10)), chara, {}, turn=60)
    assert bonus == 0.0


def test_zero_at_soft_cap():
    """Stat at its soft cap → 0 bonus (don't push past).

    Updated 2026-06-09: defaults raised from 1100→1200 for main rating
    stats. Test now uses 1200 to land exactly on the cap."""
    s = MantStrategy(None)
    # Speed at 1200 / cap 1200 = 1.0
    chara = {"speed": 1200, "stamina": 600, "power": 700, "guts": 400, "wiz": 500}
    bonus = s._stat_concentration_bonus(_command((1, 10)), chara, {}, turn=60)
    assert bonus == 0.0


def test_zero_above_soft_cap():
    """Stat over soft cap → 0 bonus (operator policy: not overcapped)."""
    s = MantStrategy(None)
    chara = {"speed": 1200, "stamina": 600, "power": 700, "guts": 400, "wiz": 500}
    bonus = s._stat_concentration_bonus(_command((1, 10)), chara, {}, turn=60)
    assert bonus == 0.0


def test_zero_when_stamina_over_low_cap():
    """Stamina over its low-cap default → 0 bonus.

    Updated 2026-06-09: low-cap default raised from 800→1000. Test now
    uses 1050 to land above the cap."""
    s = MantStrategy(None)
    chara = {"speed": 700, "stamina": 1050, "power": 700, "guts": 400, "wiz": 500}
    bonus = s._stat_concentration_bonus(_command((2, 10)), chara, {}, turn=60)
    assert bonus == 0.0


def test_ramp_under_cap():
    """Mid-ramp stat gets a partial bonus that grows with ratio."""
    s = MantStrategy(None)
    # Speed at 770 / 1100 = 0.70 (mid-ramp)
    chara_low = {"speed": 770, "stamina": 600, "power": 700, "guts": 400, "wiz": 500}
    # Speed at 990 / 1100 = 0.90 (closer to peak)
    chara_hi = {"speed": 990, "stamina": 600, "power": 700, "guts": 400, "wiz": 500}
    b_low = s._stat_concentration_bonus(_command((1, 10)), chara_low, {}, turn=60)
    b_hi = s._stat_concentration_bonus(_command((1, 10)), chara_hi, {}, turn=60)
    assert 0.0 < b_low < b_hi


def test_peak_band_near_cap():
    """Stat in the 0.95-1.00 of soft_cap band → peak bonus."""
    s = MantStrategy(None)
    chara = {"speed": 1080, "stamina": 600, "power": 700, "guts": 400, "wiz": 500}
    bonus = s._stat_concentration_bonus(_command((1, 10)), chara, {}, turn=60)
    assert bonus >= 0.20


def test_fires_for_under_cap_power_even_when_not_top_two():
    """Power below its cap with deck support gets a pull, even if it
    isn't top-2 by current value (was the regression that left Power
    stranded in the S+ 16,116 career)."""
    s = MantStrategy(None)
    # Speed 1050 (top), Wit 1000 (2nd), Power 880 (3rd — would have been
    # excluded under the old top-2 logic). Power at 880/1100 = 0.80 →
    # ramp band → should fire.
    chara = {"speed": 1050, "stamina": 600, "power": 880, "guts": 400, "wiz": 1000}
    bonus = s._stat_concentration_bonus(_command((3, 10)), chara, {}, turn=60)
    assert bonus > 0.05


def test_picks_command_primary_target():
    """Mixed-gain command is judged on its primary (largest) target."""
    s = MantStrategy(None)
    chara = {"speed": 1000, "stamina": 600, "power": 880, "guts": 400, "wiz": 500}
    # primary = power (12 > 3): power at 880/1100 = 0.80 → ramp fires
    cmd = _command((3, 12), (1, 3))
    assert s._stat_concentration_bonus(cmd, chara, {}, turn=60) > 0.05
    # primary = speed (12 > 3): speed at 1000/1100 = 0.91 → bigger pull
    cmd_speed_primary = _command((1, 12), (3, 3))
    assert s._stat_concentration_bonus(cmd_speed_primary, chara, {}, turn=60) > 0.10


def test_late_senior_still_fires():
    """Bonus active through end of career."""
    s = MantStrategy(None)
    chara = {"speed": 1080, "stamina": 600, "power": 880, "guts": 400, "wiz": 500}
    bonus = s._stat_concentration_bonus(_command((1, 10)), chara, {}, turn=77)
    assert bonus >= 0.20


def test_low_cap_stats_get_capped_curve():
    """Stamina/guts use the low-cap default, so their ramp tops out
    earlier than speed/power/wit.

    Updated 2026-06-09: low-cap default raised from 800→1000. Peak-band
    test now uses guts at 950 (ratio 0.95 of 1000) and over-cap test
    uses guts at 1050."""
    s = MantStrategy(None)
    # Guts at 950 / 1000 = 0.95 → peak band
    chara = {"speed": 700, "stamina": 500, "power": 700, "guts": 950, "wiz": 500}
    bonus = s._stat_concentration_bonus(_command((4, 10)), chara, {}, turn=60)
    assert bonus >= 0.20
    # Guts at 1050 (over 1000 cap) → 0
    chara2 = {"speed": 700, "stamina": 500, "power": 700, "guts": 1050, "wiz": 500}
    assert s._stat_concentration_bonus(_command((4, 10)), chara2, {}, turn=60) == 0.0
