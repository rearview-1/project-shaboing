"""Tests for the two training-quality gates added after the S+ 16,116
audit:

  1. Solo (0-partner) training tiles get a fixed score penalty so any
     tile with at least 1 partner beats a base-output solo tile.
  2. Non-Wit training tiles (Speed/Stamina/Power/Guts) are not picked
     above the `non_wit_training_max_failure` cap (default 15%). Wit
     can still go up to 25% via the wit-as-rest substitution path —
     this cap is for the main training pick only.
"""

from career_bot.scenarios.mant import MantStrategy, TRAINING_COMMANDS


def _training_command(command_id, partners=(), failure=0, stat_value=10, target_type=1):
    cmd = {
        "command_type": 1,
        "command_id": command_id,
        "training_partner_array": list(partners),
        "tips_event_partner_array": [],
        "failure_rate": failure,
        "params_inc_dec_info_array": [{"target_type": target_type, "value": stat_value}],
    }
    return cmd


def test_solo_training_takes_penalty():
    """A 0-partner training tile scores below an otherwise-equal 1-partner tile."""
    s = MantStrategy(None)
    chara = {"speed": 800, "stamina": 600, "power": 700, "guts": 400, "wiz": 500, "turn": 30, "vital": 100, "max_vital": 100}
    preset = {}
    solo = _training_command(101, partners=(), stat_value=10)  # Speed solo
    paired = _training_command(101, partners=(1,), stat_value=10)  # Speed +1 partner
    s_solo = s._score_command(solo, {}, chara, preset)
    s_paired = s._score_command(paired, {}, chara, preset)
    assert s_paired > s_solo
    assert solo.get("_solo_training_penalty") == 0.20
    assert "_solo_training_penalty" not in paired


def test_solo_penalty_tunable():
    s = MantStrategy(None)
    chara = {"speed": 800, "stamina": 600, "power": 700, "guts": 400, "wiz": 500, "turn": 30, "vital": 100, "max_vital": 100}
    preset = {"learned_hyperparameters": {"solo_training_penalty": 0.30}}
    solo = _training_command(101, partners=(), stat_value=10)
    s._score_command(solo, {}, chara, preset)
    assert solo.get("_solo_training_penalty") == 0.30


def test_non_wit_failure_cap_default_value():
    """Default non-Wit max failure is 15%."""
    from career_bot.scenarios.mant import _tuned_value
    assert int(_tuned_value({}, "non_wit_training_max_failure", 15)) == 15


def test_non_wit_failure_cap_overrides_via_preset():
    from career_bot.scenarios.mant import _tuned_value
    preset = {"learned_hyperparameters": {"non_wit_training_max_failure": 12}}
    assert int(_tuned_value(preset, "non_wit_training_max_failure", 15)) == 12


def test_wit_command_id_recognized():
    """The non-Wit cap is keyed on TRAINING_COMMANDS lookup — Wit is idx 4."""
    assert TRAINING_COMMANDS.get(106) == 4
    assert TRAINING_COMMANDS.get(101) == 0  # Speed
    assert TRAINING_COMMANDS.get(105) == 1  # Stamina
    assert TRAINING_COMMANDS.get(102) == 2  # Power
    assert TRAINING_COMMANDS.get(103) == 3  # Guts
