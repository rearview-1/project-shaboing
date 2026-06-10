"""Tests for settle_state decisions carrying decision-understanding detail.

Before the fix, settle_state Decisions were constructed without an
`understanding` argument, so the turn detail in the career log ended
up with an empty `decision_understanding` and no signals. The payload
also stuffed the entire `chara_info` dict into `current_command`,
polluting the log. Both are addressed by surfacing a structured
understanding payload and trimming the action payload.
"""

from career_bot.scenarios.base import Decision
from career_bot.scenarios.mant import MantStrategy


def _strategy():
    return MantStrategy(None)


def test_understanding_helper_returns_signals_dict():
    s = _strategy()
    chara = {"turn": 24, "playing_state": 5, "state": 2, "race_program_id": 0, "vital": 29}
    u = s._settle_state_understanding(chara, "post-action state without active race", "post_action_no_race")
    assert u["action"] == "settle_state"
    assert u["primary_intent"] == "state_reconcile"
    assert "state_reconcile" in u["intent_tags"]
    assert "post_action_no_race" in u["intent_tags"]
    assert u["summary"] == "post-action state without active race"
    sig = u["signals"]
    assert sig["turn"] == 24
    assert sig["playing_state"] == 5
    assert sig["chara_state"] == 2
    assert sig["race_program_id"] == 0
    assert sig["vital"] == 29
    assert sig["kind"] == "post_action_no_race"


def test_settle_state_decision_carries_understanding():
    """Wire the post-action-no-race branch end-to-end and verify the
    returned Decision has a populated understanding dict (was empty
    before the fix)."""
    s = _strategy()
    # Build a state that drives the strategy down the post-action-
    # without-active-race branch: playing_state=5, state=2 (not finish),
    # no race, no events, no actionable home commands.
    state = {
        "data": {
            "chara_info": {
                "turn": 24,
                "playing_state": 5,
                "state": 2,
                "race_program_id": 0,
                "vital": 29,
                "motivation": 5,
            },
            "unchecked_event_array": [],
        }
    }
    preset = {"complete_career_min_turn": 70}
    decision = s.next_decision(state, preset)
    assert decision.action == "settle_state"
    assert decision.reason == "post-action state without active race"
    # The payload should no longer carry the chara_info dump.
    assert "chara_info" not in decision.payload
    assert decision.payload.get("current_turn") == 24
    # The understanding dict should be populated.
    u = decision.understanding
    assert u, "decision.understanding must not be empty for settle_state"
    assert u["action"] == "settle_state"
    assert u["signals"]["turn"] == 24
    assert u["signals"]["playing_state"] == 5
    assert u["signals"]["kind"] == "post_action_no_race"


def test_settle_state_payload_no_longer_dumps_chara_info():
    """Regression: the settle_state payload used to include the full
    chara_info dict, which polluted `current_command` in the log."""
    s = _strategy()
    chara = {"turn": 24, "playing_state": 5, "state": 2, "race_program_id": 0, "vital": 29}
    u = s._settle_state_understanding(chara, "x", "y")
    # Sanity: helper returns plain dict, not the chara reference.
    assert u is not chara
