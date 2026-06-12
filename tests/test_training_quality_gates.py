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


def test_visible_tile_quality_guard_lifts_clear_rainbow_tile():
    s = MantStrategy(None)
    chara = {
        "turn": 50,
        "vital": 100,
        "max_vital": 100,
        "evaluation_info_array": [
            {"target_id": 1, "evaluation": 90},
            {"target_id": 2, "evaluation": 90},
        ],
    }
    weak_speed = _training_command(101, partners=(), stat_value=12, target_type=1)
    rainbow_wit = _training_command(106, partners=(1, 2), stat_value=28, target_type=5)
    rainbow_wit["params_inc_dec_info_array"].append({"target_type": 30, "value": 5})

    adjusted = s._apply_visible_tile_quality_guard(
        [(1.80, weak_speed), (1.65, rainbow_wit)],
        chara,
        {"visible_tile_quality_guard_enabled": True},
        50,
    )

    by_command = {cmd["command_id"]: score for score, cmd in adjusted}
    assert by_command[106] > by_command[101]
    assert rainbow_wit["_visible_tile_quality_delta"] > 0
    assert weak_speed["_visible_tile_quality_delta"] < 0


def test_best_command_uses_visible_tile_quality_for_obvious_rainbow():
    s = MantStrategy(None)
    chara = {
        "turn": 50,
        "vital": 100,
        "max_vital": 100,
        "speed": 700,
        "stamina": 500,
        "power": 650,
        "guts": 450,
        "wiz": 700,
        "evaluation_info_array": [
            {"target_id": 1, "evaluation": 90},
            {"target_id": 2, "evaluation": 90},
        ],
    }
    weak_speed = _training_command(101, partners=(), stat_value=12, target_type=1)
    rainbow_wit = _training_command(106, partners=(1, 2), stat_value=30, target_type=5)
    rainbow_wit["params_inc_dec_info_array"].append({"target_type": 30, "value": 5})
    data = {"home_info": {"command_info_array": [weak_speed, rainbow_wit]}}

    chosen = s._best_command(data, chara, {"visible_tile_quality_guard_enabled": True})

    assert chosen["command_id"] == 106
    assert chosen.get("_visible_tile_quality_delta", 0) > 0


def test_race_heavy_core_floor_has_bounded_guts_pressure():
    s = MantStrategy(None)
    preset = {
        "custom_race_schedule": [{"turn": turn, "program_id": 1000 + turn} for turn in range(1, 38)]
    }
    low_guts = {
        "turn": 44,
        "speed": 720,
        "stamina": 520,
        "power": 690,
        "guts": 260,
        "wiz": 620,
    }
    safe_guts = dict(low_guts, guts=390)

    assert s._race_heavy_core_floor_adjustment(3, low_guts, preset, 44) > 0
    assert s._race_heavy_core_floor_adjustment(3, safe_guts, preset, 44) == 0.0
