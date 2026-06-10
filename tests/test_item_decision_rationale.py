"""Tests for the per-turn item-decision rationale capture added so the
next career-log audit can show *why* each item category did/didn't
fire, instead of a vague "not_useful_now" reason.

The rationale dict is published as
`MantItemManager.last_use_decision_rationale` and surfaced in the
career log under `bot_item_use_decision_rationale` per turn.
"""

from career_bot.items import MantItemManager


def _state(hp=50, max_hp=100, motivation=3, turn=10, command_id=101, owned_items=None):
    return {
        "data": {
            "chara_info": {
                "vital": hp,
                "max_vital": max_hp,
                "motivation": motivation,
                "turn": turn,
                "evaluation_info_array": [],
            },
            "free_data_set": {
                "user_item_info_array": owned_items or [],
                "item_effect_array": [],
                "coin_num": 100,
            },
        }
    }


def test_rationale_initialized_empty():
    m = MantItemManager()
    assert m.last_use_decision_rationale == {}


def test_rationale_captures_skip_reason_when_no_items_owned():
    m = MantItemManager()
    state = _state(hp=20, motivation=3, turn=15)
    best_command = {"command_type": 1, "command_id": 101, "failure_rate": 5}

    class _Client:
        def use_items(self, payload, current_turn):
            return state

    m.use_items(_Client(), state, {}, best_command=best_command)

    r = m.last_use_decision_rationale
    assert r.get("skip") == "no_owned_items"
    assert r["inputs"]["hp"] == 20
    assert r["inputs"]["turn"] == 15


def test_rationale_populated_with_owned_items():
    """When the bot has items in inventory, the full per-category
    rationale is captured."""
    m = MantItemManager()
    # Vita 20 = item_id 2001
    owned = [{"item_id": 2001, "num": 3}]
    state = _state(hp=25, motivation=3, turn=15, owned_items=owned)
    best_command = {"command_type": 1, "command_id": 101, "failure_rate": 5}

    class _Client:
        def use_items(self, payload, current_turn):
            return state

    m.use_items(_Client(), state, {}, best_command=best_command)

    r = m.last_use_decision_rationale
    assert "inputs" in r
    assert r["inputs"]["hp"] == 25
    assert r["inputs"]["motivation"] == 3
    assert r["inputs"]["turn"] == 15
    assert r["inputs"]["best_command_id"] == 101
    for cat in ("energy", "mood", "ailment", "megaphone", "anklet", "charm", "whistle", "kale_pair"):
        assert cat in r, f"category {cat} missing from rationale"
        assert "fired" in r[cat]


def test_rationale_captures_thresholds():
    m = MantItemManager()
    owned = [{"item_id": 2001, "num": 1}]
    state = _state(hp=80, motivation=5, turn=10, owned_items=owned)
    best_command = {"command_type": 1, "command_id": 101, "failure_rate": 5}

    class _Client:
        def use_items(self, payload, current_turn):
            return state

    m.use_items(_Client(), state, {}, best_command=best_command)
    r = m.last_use_decision_rationale
    assert r["megaphone"]["small_threshold"] > 0
    assert r["megaphone"]["medium_threshold"] > r["megaphone"]["small_threshold"]
    assert r["megaphone"]["large_threshold"] > r["megaphone"]["medium_threshold"]
    assert r["energy"]["threshold_used"] > 0


def test_rationale_energy_fires_when_hp_low_and_vita_owned():
    m = MantItemManager()
    owned = [{"item_id": 2001, "num": 3}]  # Vita 20
    state = _state(hp=20, motivation=3, turn=15, owned_items=owned)
    best_command = {"command_type": 1, "command_id": 101, "failure_rate": 5}

    class _Client:
        def use_items(self, payload, current_turn):
            return state

    m.use_items(_Client(), state, {}, best_command=best_command)
    r = m.last_use_decision_rationale
    # HP 20 ≤ threshold 30 → energy should fire
    assert r["energy"]["fired"] is True
    assert any(t["name"] == "Vita 20" for t in r["energy"]["targets_picked"])


def test_rationale_energy_does_not_fire_when_hp_high():
    m = MantItemManager()
    owned = [{"item_id": 2001, "num": 3}]
    state = _state(hp=90, motivation=3, turn=15, owned_items=owned)
    best_command = {"command_type": 1, "command_id": 101, "failure_rate": 5}

    class _Client:
        def use_items(self, payload, current_turn):
            return state

    m.use_items(_Client(), state, {}, best_command=best_command)
    r = m.last_use_decision_rationale
    assert r["energy"]["fired"] is False
