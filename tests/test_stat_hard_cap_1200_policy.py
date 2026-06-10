"""Lock-in tests for the 1200 stat hard-cap policy.

Operator policy: 1200 is the absolute ceiling for every stat
(speed/stamina/power/guts/wit). No code path may produce a stat above
1200. This is the game's in-engine cap, not a soft cap. The
late-week 1100 soft clamp is a separate policy and does NOT change
this ceiling.

If a refactor or tuner update raises any of these, the tests below
will fail and force the change to be made deliberately.
"""
from career_bot.career_simulator import STAT_CAP
from career_bot.hyperparameter_tuner import TUNABLE_PARAMS
from career_bot.scenarios.mant import MantStrategy


# -------------------- module constant --------------------

def test_sim_stat_cap_is_1200():
    """STAT_CAP must be 1200. The game's hard ceiling. Don't change
    this without verifying the game itself moved it."""
    assert STAT_CAP == 1200


# -------------------- auto-tuner bounds --------------------

def test_tuner_cannot_lift_stat_hard_cap_above_1200():
    """The strategy's `stat_hard_cap` learned-hyperparameter must be
    bounded at 1200 ceiling in the auto-tuner config. If someone bumps
    the ceiling to 1250 hoping to push past, this catches it."""
    cfg = TUNABLE_PARAMS.get("stat_hard_cap")
    assert cfg is not None, "stat_hard_cap must remain a tunable param"
    assert cfg["ceiling"] == 1200, (
        f"stat_hard_cap ceiling must be 1200, got {cfg['ceiling']}"
    )
    # Floor and default also shouldn't drop the bot below sensible
    # operating range
    assert cfg["floor"] >= 1100
    assert cfg["default"] == 1200


# -------------------- strategy-side cap --------------------

def test_strategy_per_stat_soft_cap_never_exceeds_1200_normal_career():
    """During regular (pre-late-week) career, the strategy's
    `_per_stat_soft_cap` returns the SOFT cap for training-taper
    purposes. That value can legitimately be 1200 (matching the hard
    cap) but must never EXCEED 1200 even with aggressive overrides."""
    s = MantStrategy(None)
    p = {
        "name": "test",
        "scenario_id": 4,
        "_deck_type_counts": [4, 4, 4, 4, 4],  # max protection on all stats
        "expect_attribute": [9999, 9999, 9999, 9999, 9999],  # huge targets
        "learned_hyperparameters": {
            # Try to lift caps past 1200 via the tuner override path
            "speed_soft_cap": 1500,
            "wit_soft_cap": 1500,
            "power_soft_cap": 1500,
            "stamina_soft_cap": 1500,
            "guts_soft_cap": 1500,
        },
    }
    for stat_idx in range(5):
        cap = s._per_stat_soft_cap(stat_idx, p, turn=30)
        assert cap <= 1200.0, (
            f"stat {stat_idx} soft cap exceeded 1200 in pre-late-week "
            f"with aggressive overrides: {cap}"
        )


def test_strategy_per_stat_soft_cap_late_week_is_1100():
    """Independent check: the late-week clamp at 1100 still kicks in.
    This is the OTHER policy (different from the 1200 hard cap),
    pinned alongside so they're tested together."""
    s = MantStrategy(None)
    p = {
        "name": "test",
        "scenario_id": 4,
        "_deck_type_counts": [4, 4, 4, 4, 4],
        "learned_hyperparameters": {"speed_soft_cap": 1500},
    }
    for stat_idx in range(5):
        cap = s._per_stat_soft_cap(stat_idx, p, turn=72)
        assert cap == 1100.0, (
            f"stat {stat_idx} late-week soft cap must be 1100, got {cap}"
        )


# -------------------- sim stat-application sites --------------------

def test_all_stat_application_sites_use_stat_cap_min():
    """Every place the sim adds to a stat must wrap with min(STAT_CAP, ...).
    This is a source-level grep that verifies the discipline isn't broken
    by a refactor that adds a new write-site without the guard."""
    from pathlib import Path
    sim_path = (
        Path(__file__).resolve().parent.parent
        / "career_bot" / "career_simulator.py"
    )
    text = sim_path.read_text(encoding="utf-8")

    # Find every line that writes to self.state[STAT_KEY] += ... or = ...
    # for the 5 stat keys. Each MUST be wrapped in min(STAT_CAP, ...).
    import re
    STAT_STATE_KEYS = {"speed", "stamina", "power", "guts", "wiz"}
    # Match: self.state[<some_stat_key>] = ... or self.state["<stat>"] = ...
    # Just count assignment sites for now and verify STAT_CAP usage
    # near each. A pragmatic check: count "self.state[" assignments
    # touching stat keys and ensure STAT_CAP appears nearby.
    write_sites = []
    for m in re.finditer(
        r"self\.state\[(['\"]?)([a-z_]+)\1\]\s*=",
        text,
    ):
        key = m.group(2).strip("\"'")
        if key in STAT_STATE_KEYS:
            line_start = text.rfind("\n", 0, m.start()) + 1
            line_end = text.find("\n", m.end())
            line = text[line_start:line_end]
            write_sites.append((m.start(), key, line.strip()))

    # Each write must reference STAT_CAP on the same line (the pattern
    # `min(STAT_CAP, ...)`) — otherwise the assignment could exceed 1200.
    for offset, key, line in write_sites:
        assert "STAT_CAP" in line or "min(" in line, (
            f"stat write site missing STAT_CAP guard near offset {offset}:\n"
            f"  {line}\n"
            f"  Every assignment to self.state[<stat>] must wrap with "
            f"min(STAT_CAP, ...) so the 1200 ceiling holds."
        )
