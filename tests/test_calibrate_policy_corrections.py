"""Tests for calibrate's policy-correction pass.

Operator framing: "the bot/sim is there to make those edits so it does
hit SS and higher." The user shouldn't have to manually fix stale
learned_hyperparameters when the auto-tuner has pinned a cap below the
operator's policy floor.

`_apply_policy_floor_corrections` runs at the start of every
calibrate, inspects the baseline preset's learned values for cap/floor
knobs, and resets any that violate the operator policy to the policy
default. This guarantees the sim's strategy actually MATCHES policy
before any sweep work begins.
"""
from tools.calibrate_deck import (
    POLICY_FLOORS,
    _apply_policy_floor_corrections,
)


def test_correction_resets_stamina_soft_cap_below_floor():
    """The exact failure mode the user hit: stamina_soft_cap=775 is below
    the operator policy floor of 1000. Calibrate must reset it to the
    policy default (1200) before running sims."""
    preset = {"learned_hyperparameters": {"stamina_soft_cap": 775}}
    corrections = _apply_policy_floor_corrections(preset)
    assert len(corrections) == 1
    name, old, new = corrections[0]
    assert name == "stamina_soft_cap"
    assert old == 775.0
    assert new == 1200.0
    assert preset["learned_hyperparameters"]["stamina_soft_cap"] == 1200


def test_correction_leaves_policy_compliant_values_alone():
    """A preset already matching policy should produce zero corrections."""
    preset = {"learned_hyperparameters": {
        "speed_soft_cap": 1200,
        "wit_soft_cap": 1200,
        "power_soft_cap": 1200,
        "stamina_soft_cap": 1200,
        "guts_soft_cap": 1200,
    }}
    corrections = _apply_policy_floor_corrections(preset)
    assert corrections == []


def test_correction_handles_missing_learned_hyperparameters():
    """Preset with no learned_hyperparameters block: no crash, no
    corrections."""
    preset = {"name": "minimal"}
    corrections = _apply_policy_floor_corrections(preset)
    assert corrections == []


def test_correction_skips_keys_not_in_policy():
    """Only cap/floor keys defined in POLICY_FLOORS are checked. Other
    learned values stay untouched."""
    preset = {"learned_hyperparameters": {
        "speed_priority_bonus_late": 0.32,  # not a cap/floor
        "calendar_race_prebuy_budget": 1800,  # not a cap/floor
        "stamina_soft_cap": 700,  # below floor → corrected
    }}
    corrections = _apply_policy_floor_corrections(preset)
    assert len(corrections) == 1
    assert corrections[0][0] == "stamina_soft_cap"
    # Other values untouched
    assert preset["learned_hyperparameters"]["speed_priority_bonus_late"] == 0.32
    assert preset["learned_hyperparameters"]["calendar_race_prebuy_budget"] == 1800


def test_correction_resets_all_violations_in_one_pass():
    """All policy-floor violations in the preset are corrected in a
    single call — calibrate shouldn't need multiple passes."""
    preset = {"learned_hyperparameters": {
        "stamina_soft_cap": 775,
        "guts_soft_cap": 625,
        "stamina_floor_target": 750,
        "power_floor_target": 950,
    }}
    corrections = _apply_policy_floor_corrections(preset)
    assert len(corrections) == 4
    lhp = preset["learned_hyperparameters"]
    assert lhp["stamina_soft_cap"] == 1200
    assert lhp["guts_soft_cap"] == 1200
    assert lhp["stamina_floor_target"] == 1000
    assert lhp["power_floor_target"] == 1100


def test_correction_handles_non_numeric_values_gracefully():
    """A junk value (string, None) is skipped — no raise, no correction.
    Production safety: never let a single bad value crash calibrate."""
    preset = {"learned_hyperparameters": {
        "stamina_soft_cap": "not a number",
        "guts_soft_cap": None,
        "power_soft_cap": 1200,  # this one's fine
    }}
    corrections = _apply_policy_floor_corrections(preset)
    # Only stat-typed values count; bad types skipped
    assert all(name != "stamina_soft_cap" and name != "guts_soft_cap"
                for name, _, _ in corrections)


def test_policy_floors_match_operator_intent():
    """Spot-check the constants directly: operator wants 1200 caps
    across all 5 stats and meaningful floor targets."""
    for stat in ("speed", "wit", "power", "stamina", "guts"):
        key = f"{stat}_soft_cap"
        rule = POLICY_FLOORS.get(key)
        assert rule is not None, f"{key} must be in POLICY_FLOORS"
        assert rule["policy_default"] == 1200, (
            f"{key} policy default must match the 1200 ceiling"
        )
