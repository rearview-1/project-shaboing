"""Tests for Stat Priority Architecture: Speed Priority + Checkpoint Pressure.

Two complementary bonuses that bias the training scorer:
1. `_speed_priority_bonus` — unconditional Speed bias scaled by year phase.
2. `_checkpoint_pressure_bonus` — per-stat pressure when behind year-pace.

Note: `_current_stat` reads the in-game chara key `wiz` for stat index 4
(Wit). Tests use `wiz` to match the production data shape.
"""

from career_bot.scenarios.mant import MantStrategy


def _command(*stat_gains):
    """Build a command with given stat gains.

    stat_gains: iterable of (target_type, value) tuples.
    target_type mapping: 1=Speed, 2=Stamina, 3=Power, 4=Guts, 5=Wit, 10=energy
    """
    return {
        "params_inc_dec_info_array": [
            {"target_type": t, "value": v} for t, v in stat_gains
        ]
    }


# ============================================================
# Speed Priority Tests
# ============================================================


def test_speed_bonus_fires_when_speed_low_in_classic():
    """Speed at 600 in Classic should produce significant bonus."""
    s = MantStrategy(None)
    bonus = s._speed_priority_bonus(_command((1, 10)), {"speed": 600}, {}, turn=30)
    # Mid (0.16) * full decay (1.0) + deficit boost (~0.10 * 0.33) = ~0.193
    assert bonus >= 0.16


def test_speed_bonus_decays_above_target():
    """Speed at 1200 should produce minimal bonus (decay to 0.1x)."""
    s = MantStrategy(None)
    bonus = s._speed_priority_bonus(_command((1, 10)), {"speed": 1200}, {}, turn=30)
    # No deficit boost (above 900), decay 0.1 * 0.16 = 0.016
    assert bonus < 0.03


def test_no_speed_bonus_for_pure_wit():
    """A pure Wit training gets no Speed bonus."""
    s = MantStrategy(None)
    bonus = s._speed_priority_bonus(_command((5, 10)), {"speed": 700}, {}, turn=30)
    assert bonus == 0.0


def test_secondary_speed_gain_triggers_bonus():
    """A Power training with secondary Speed gain still gets bonus."""
    s = MantStrategy(None)
    cmd = _command((3, 10), (1, 3))  # Power +10, Speed +3 secondary
    bonus = s._speed_priority_bonus(cmd, {"speed": 700}, {}, turn=30)
    assert bonus > 0.0


def test_deficit_boost_when_critical():
    """Speed below 900 in Classic should get the deficit boost."""
    s = MantStrategy(None)
    cmd = _command((1, 10))
    # Speed=300 → deficit_boost = 0.10 * (1 - 300/900) = ~0.067
    bonus_critical = s._speed_priority_bonus(cmd, {"speed": 300}, {}, turn=30)
    bonus_above = s._speed_priority_bonus(cmd, {"speed": 950}, {}, turn=30)
    assert bonus_critical > bonus_above + 0.05


def test_speed_bonus_smaller_in_junior():
    """Junior Speed bonus (0.06) should be smaller than Classic (0.16)."""
    s = MantStrategy(None)
    cmd = _command((1, 10))
    junior_bonus = s._speed_priority_bonus(cmd, {"speed": 200}, {}, turn=10)
    classic_bonus = s._speed_priority_bonus(cmd, {"speed": 200}, {}, turn=30)
    # Junior is pre-end-of-junior so no deficit boost
    assert junior_bonus < classic_bonus


def test_speed_bonus_zero_when_disabled_via_preset():
    """Setting stat_priority_architecture_enabled=False kills the bonus."""
    s = MantStrategy(None)
    cmd = _command((1, 10))
    preset_off = {"stat_priority_architecture_enabled": False}
    bonus = s._speed_priority_bonus(cmd, {"speed": 500}, preset_off, turn=30)
    assert bonus == 0.0


# ============================================================
# Checkpoint Pressure Tests
# ============================================================


def test_checkpoint_no_bonus_when_on_pace():
    """A stat at expected pace gets no bonus."""
    s = MantStrategy(None)
    # Turn 30 mid-Classic. Stamina expected on the current high-stat curve:
    # 240 + (540-240) * (30-24)/(48-24) = 315.
    chara = {"speed": 500, "stamina": 330, "power": 480, "guts": 250, "wiz": 320}
    cmd = _command((2, 10))
    bonus = s._checkpoint_pressure_bonus(cmd, chara, {}, turn=30)
    assert bonus < 0.01


def test_checkpoint_bonus_when_behind_pace():
    """A stat significantly behind expected pace gets a meaningful bonus."""
    s = MantStrategy(None)
    # Turn 40 mid-Classic. Stamina expected: 200 + (450-200) * (40-24)/(48-24) = 367
    chara = {"speed": 500, "stamina": 250, "power": 480, "guts": 250, "wiz": 320}
    cmd = _command((2, 12))
    bonus = s._checkpoint_pressure_bonus(cmd, chara, {}, turn=40)
    assert bonus >= 0.03


def test_checkpoint_critical_deficit_triggers_extra_boost():
    """A stat far below pace gets the critical boost."""
    s = MantStrategy(None)
    # Turn 40 Stamina expected ~367; setting to 200 means deficit ~0.46 (above 0.25 critical)
    chara = {"speed": 500, "stamina": 200, "power": 480, "guts": 250, "wiz": 320}
    cmd = _command((2, 12))
    bonus = s._checkpoint_pressure_bonus(cmd, chara, {}, turn=40)
    # base 0.10 (full scaling since deficit_ratio*2 >= 1) + critical 0.06 = 0.16, * gain_weight 1.0 = 0.16
    assert bonus >= 0.10


def test_checkpoint_no_bonus_when_ahead_of_pace():
    """A stat ahead of pace gets no bonus."""
    s = MantStrategy(None)
    chara = {"speed": 500, "stamina": 280, "power": 480, "guts": 250, "wiz": 500}
    cmd = _command((5, 12))
    bonus = s._checkpoint_pressure_bonus(cmd, chara, {}, turn=30)
    assert bonus == 0.0


def test_checkpoint_deck_scaling_raises_target():
    """A deck with 2 Stamina cards has higher Stamina target."""
    s = MantStrategy(None)
    chara = {"speed": 500, "stamina": 380, "power": 480, "guts": 250, "wiz": 320}
    cmd = _command((2, 12))

    no_card_bonus = s._checkpoint_pressure_bonus(
        cmd, chara, {"_deck_type_counts": [2, 0, 2, 0, 2]}, turn=40
    )
    two_card_bonus = s._checkpoint_pressure_bonus(
        cmd, chara, {"_deck_type_counts": [2, 2, 0, 0, 2]}, turn=40
    )
    assert two_card_bonus > no_card_bonus


def test_checkpoint_multi_stat_bonus_capped():
    """A training with gains on multiple deficit stats is capped at MAX_BONUS."""
    s = MantStrategy(None)
    chara = {"speed": 100, "stamina": 100, "power": 100, "guts": 100, "wiz": 100}
    cmd = _command((1, 8), (2, 4), (3, 4))
    bonus = s._checkpoint_pressure_bonus(cmd, chara, {}, turn=30)
    assert bonus <= 0.20  # MAX_BONUS cap


def test_checkpoint_zero_when_disabled_via_preset():
    """Setting stat_priority_architecture_enabled=False kills the bonus."""
    s = MantStrategy(None)
    chara = {"speed": 100, "stamina": 100, "power": 100, "guts": 100, "wiz": 100}
    cmd = _command((2, 12))
    preset_off = {"stat_priority_architecture_enabled": False}
    bonus = s._checkpoint_pressure_bonus(cmd, chara, preset_off, turn=40)
    assert bonus == 0.0


def test_checkpoint_junior_vs_classic_targets():
    """Junior uses junior end-targets, Classic uses classic end-targets."""
    s = MantStrategy(None)
    # Same Speed value but different turn windows should produce different expected_pace
    chara = {"speed": 250, "stamina": 200, "power": 250, "guts": 150, "wiz": 250}
    cmd = _command((1, 12))
    # Turn 20 (Junior): Speed expected ~100 + (330-100) * (20-1)/(24-1) ≈ 290
    # 250 vs 290 = mild deficit
    junior_bonus = s._checkpoint_pressure_bonus(cmd, chara, {}, turn=20)
    # Turn 36 (Classic): Speed expected ~330 + (650-330) * (36-24)/(48-24) = 490
    # 250 vs 490 = severe deficit (above critical)
    classic_bonus = s._checkpoint_pressure_bonus(cmd, chara, {}, turn=36)
    assert classic_bonus > junior_bonus


def test_checkpoint_senior_window():
    """Senior (turn 60-78) uses senior targets."""
    s = MantStrategy(None)
    # Turn 60 mid-Senior. Speed expected: 650 + (1000-650) * (60-48)/(78-48) = 790
    # Speed at 600 = deficit ratio ~0.24 (just under critical 0.25)
    chara = {"speed": 600, "stamina": 500, "power": 700, "guts": 350, "wiz": 700}
    cmd = _command((1, 12))
    bonus = s._checkpoint_pressure_bonus(cmd, chara, {}, turn=60)
    assert bonus > 0.0


# ============================================================
# Composition Tests
# ============================================================


def test_speed_and_checkpoint_compose_additively():
    """Both bonuses apply to the same Speed training when Speed is behind pace."""
    s = MantStrategy(None)
    # Turn 30. Speed expected: 330 + (650-330) * (30-24)/(48-24) = 410. Speed at 350 is behind.
    chara = {"speed": 350, "stamina": 250, "power": 460, "guts": 250, "wiz": 320}
    cmd = _command((1, 10))
    speed_b = s._speed_priority_bonus(cmd, chara, {}, turn=30)
    checkpoint_b = s._checkpoint_pressure_bonus(cmd, chara, {}, turn=30)
    assert speed_b > 0.10
    assert checkpoint_b > 0.0
    combined = speed_b + checkpoint_b
    assert combined > speed_b


def test_preset_flag_disables_both_bonuses():
    """The feature flag disables both bonuses simultaneously."""
    s = MantStrategy(None)
    chara = {"speed": 350, "stamina": 250, "power": 460, "guts": 250, "wiz": 320}
    cmd = _command((1, 10))
    preset_off = {"stat_priority_architecture_enabled": False}
    assert s._speed_priority_bonus(cmd, chara, preset_off, turn=30) == 0.0
    assert s._checkpoint_pressure_bonus(cmd, chara, preset_off, turn=30) == 0.0


def test_constants_match_handoff_spec():
    """Sanity check the constants against the handoff doc's behavioral targets."""
    from career_bot.scenarios import mant

    assert mant._CHECKPOINT_TARGETS_END_JUNIOR == [360, 240, 380, 200, 360]
    assert mant._CHECKPOINT_TARGETS_END_CLASSIC == [680, 540, 700, 360, 700]
    assert mant._CHECKPOINT_TARGETS_END_SENIOR == [1050, 720, 950, 500, 1050]
    assert mant._CHECKPOINT_TURN_END_JUNIOR == 24
    assert mant._CHECKPOINT_TURN_END_CLASSIC == 48
    assert mant._CHECKPOINT_TURN_END_SENIOR == 78
    assert mant._SPEED_PRIORITY_BONUS_MID == 0.16
    assert mant._CHECKPOINT_DECK_CARD_SCALE[0] == 1.00
    assert mant._CHECKPOINT_DECK_CARD_SCALE[2] == 1.15
