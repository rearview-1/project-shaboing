"""Tests for the MANT +400 invisible all-stats bonus at race-evaluation
time.

Real-game mechanic: MANT (Trackblazer) scenario grants +400 to every
stat AT RACE CALCULATION TIME. The bonus is invisible to the operator,
doesn't show on the chara sheet, and doesn't affect rating/rank — it
ONLY adjusts the stats the race outcome engine uses for win-probability
math.

Bug fixed 2026-06-10: `_current_race_stats` was returning displayed
stats, and the 3 race-outcome paths (_estimate_race_from_results,
_estimate_race_from_fields, _race_threshold_score) called it directly.
So the sim compared the bot's 750 displayed stamina against opponent
fields calibrated to 1150 effective stamina — making the bot lose
chronic Senior G1s (Takarazuka, Mile Championship, etc) that the live
bot wins fine. After fix, `_effective_race_stats()` adds +400 and the
race-outcome paths use that.

These tests pin the contract so a refactor that "simplifies" one of the
race paths back to `_current_race_stats()` is caught immediately.
"""
import copy

from career_bot.career_simulator import (
    CAREER_INVISIBLE_STAT_BONUS,
    CareerSimulator,
)


def _make_sim():
    """Minimal sim with known stats for unit testing the bonus."""
    preset = {
        "name": "test_invisible_bonus",
        "scenario_id": 4,
        "sim_use_latest_session_context": False,
        "_run_context": {
            "support_card_ids": [30036, 30054, 30014, 30010, 30028],
            "friend_card_id": 30017,
            "trainee_card_id": 102001,
        },
    }
    deck = [{"support_card_id": c, "lb_level": 4}
            for c in [30036, 30054, 30014, 30010, 30028]]
    return CareerSimulator(preset=preset, deck=deck, seed=42)


def test_constant_is_400():
    """Spot-check the named constant. If the game itself changes this
    (extremely unlikely without a scenario rework), the test catches it
    and forces the change to be made deliberately."""
    assert CAREER_INVISIBLE_STAT_BONUS == 400


def test_current_race_stats_returns_displayed_values():
    """`_current_race_stats` is for UI / logging / pre-race records.
    Must NOT include the +400 — that would silently inflate the values
    shown to the operator."""
    sim = _make_sim()
    sim.state.update({"speed": 1000, "stamina": 750, "power": 800,
                       "guts": 500, "wiz": 950})
    out = sim._current_race_stats()
    assert out["speed"] == 1000
    assert out["stamina"] == 750
    assert out["power"] == 800
    assert out["guts"] == 500
    assert out["wit"] == 950   # NB: wit maps from `wiz` state key


def test_effective_race_stats_adds_400_to_every_stat():
    """`_effective_race_stats` adds the +400 invisible bonus to every
    one of the 5 stats. Used by race outcome math (NOT rating/rank)."""
    sim = _make_sim()
    sim.state.update({"speed": 1000, "stamina": 750, "power": 800,
                       "guts": 500, "wiz": 950})
    out = sim._effective_race_stats()
    assert out["speed"] == 1400
    assert out["stamina"] == 1150
    assert out["power"] == 1200
    assert out["guts"] == 900
    assert out["wit"] == 1350


def test_effective_race_stats_uncapped_above_displayed_ceiling():
    """Existing precedent in the sim (line 6356 area:
    `effective_current_stamina = current['stamina'] + CAREER_INVISIBLE_STAT_BONUS`)
    does not cap at 1200. So the sim treats race math as uncapped after
    the +400 bonus stacks. If the game cap turns out to differ, change
    BOTH the threshold check AND this method together so they stay
    consistent."""
    sim = _make_sim()
    sim.state.update({"speed": 1200, "stamina": 1200, "power": 1200,
                       "guts": 1200, "wiz": 1200})
    out = sim._effective_race_stats()
    # 1200 + 400 = 1600 — not capped at 1200 here
    for k in ("speed", "stamina", "power", "guts", "wit"):
        assert out[k] == 1600, (
            f"Expected uncapped effective stat for {k}, got {out[k]}"
        )


def test_effective_handles_zero_stats():
    """Edge: very early career when stats are still at base. Bonus
    applies even at low displayed stats."""
    sim = _make_sim()
    sim.state.update({"speed": 0, "stamina": 0, "power": 0,
                       "guts": 0, "wiz": 0})
    out = sim._effective_race_stats()
    for k in ("speed", "stamina", "power", "guts", "wit"):
        assert out[k] == 400


def test_race_outcome_paths_use_effective_not_displayed():
    """The 3 race outcome paths must all call `_effective_race_stats()`,
    not `_current_race_stats()`. Source-level grep verifies the call
    sites haven't drifted back. Pins the contract concretely."""
    from pathlib import Path
    sim_path = (
        Path(__file__).resolve().parent.parent
        / "career_bot" / "career_simulator.py"
    )
    text = sim_path.read_text(encoding="utf-8")

    # `_race_effort_score(self._current_race_stats(), ...)` is the
    # buggy pattern. There should be NO race-outcome path doing this.
    # `_simulate_race`'s `pre_race_stats = dict(self._current_race_stats())`
    # is OK — that's the logged-displayed value, not a race-outcome calc.
    lines = text.splitlines()
    for i, line in enumerate(lines):
        if "_race_effort_score(" in line:
            # Check the NEXT line for the stats arg
            if i + 1 < len(lines):
                arg_line = lines[i + 1]
                if "_current_race_stats" in arg_line:
                    raise AssertionError(
                        f"line {i+2}: _race_effort_score called with "
                        f"_current_race_stats (displayed) instead of "
                        f"_effective_race_stats (with +400). This is the "
                        f"chronic-loss bug — please use the effective "
                        f"variant for race math."
                    )

    # Also verify the threshold-ratio path uses effective stats
    for i, line in enumerate(lines):
        if "def ratio(stat):" in line:
            # Look back 5 lines for `current = self._current_race_stats()`
            for j in range(max(0, i - 8), i):
                if "current = self._current_race_stats()" in lines[j]:
                    raise AssertionError(
                        f"line {j+1}: race-threshold ratio() uses "
                        f"displayed stats (_current_race_stats). Switch to "
                        f"_effective_race_stats so the +400 bonus applies."
                    )
