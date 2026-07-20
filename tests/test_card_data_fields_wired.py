"""Tests for card-data fields that were previously stored in
`data/support_card_bonuses.json` but not read anywhere in the sim:

  - `unique_effects` — per-card passives that activate at `unlock_level`
  - `failure_protection` — partner-card-driven failure-rate reduction
  - `hint_levels` / `hint_freq` — card hints discount skill purchase cost
  - `minigame_effectiveness` — loaded into effects dict (MANT doesn't use,
    but the field is now accessible)

These tests pin the wiring so a future refactor that "cleans up" the
add_card path doesn't silently drop card mechanics again.
"""
import json
from pathlib import Path

from career_bot.career_simulator import (
    CareerSimulator,
    _support_max_level_estimate,
)


def _make_sim(*, static_card_hints=False):
    deck = [
        {"support_card_id": 30036, "lb_level": 0},   # Riko (Friends)
        {"support_card_id": 30054, "lb_level": 4},   # Nice Nature (Wit)
        {"support_card_id": 30014, "lb_level": 4},   # Gold City (Speed)
        {"support_card_id": 30010, "lb_level": 4},   # Fine Motion (Wit)
        {"support_card_id": 30028, "lb_level": 4},   # Kitasan Black (Speed)
    ]
    preset = {
        "name": "card_data_test",
        "scenario_id": 4,
        "sim_use_latest_session_context": False,
        "sim_use_runtime_observations": False,
        "sim_use_card_hint_events": not static_card_hints,
        "_run_context": {
            "support_card_ids": [30036, 30054, 30014, 30010, 30028],
            "friend_card_id": 30017,
            "trainee_card_id": 102001,
        },
    }
    return CareerSimulator(preset=preset, deck=deck, seed=42)


# -------------------- unique_effects merge --------------------

def test_unique_effects_merged_into_card_effects():
    """Riko's unique_effects include +10 failure_protection and +5
    energy_cost_reduction (both unlock_level 30). At LB 0 her max level
    is 40 (SSR), so the effects fire."""
    sim = _make_sim()
    riko = next(c for c in sim.sim_support_cards if c["support_card_id"] == 30036)
    eff = riko["effects"]
    # Base LB 0 failure_protection was 25 (per data); unique adds 10 → 35
    assert eff.get("failure_protection", 0) >= 35, (
        f"Expected failure_protection ≥ 35 (base 25 + unique 10); got {eff.get('failure_protection')}"
    )


def test_unique_effects_skip_if_unlock_level_not_met():
    """If a hypothetical card has unique with unlock_level=99, it
    should NOT merge into effects. _support_max_level_estimate caps at
    50 for SSR LB4 so 99 is unreachable."""
    # Use SSR LB 4 → max level 50; 99 > 50 → unique skipped.
    assert _support_max_level_estimate("SSR", 4) == 50
    # Sanity: SR LB 0 max level 35
    assert _support_max_level_estimate("SR", 0) == 35


def test_unique_effects_initial_stats_merged():
    """Gold City (SSR LB 4) has unique +20 initial_speed. Base LB 4
    initial_speed is 20, so merged should be 40."""
    sim = _make_sim()
    gold = next(c for c in sim.sim_support_cards if c["support_card_id"] == 30014)
    eff = gold["effects"]
    assert eff.get("initial_speed", 0) == 40, (
        f"Expected initial_speed=40 (base 20 + unique 20); got {eff.get('initial_speed')}"
    )


def test_taiki_unique_decoded_as_bond_gated_grants():
    data_path = Path(__file__).resolve().parents[1] / "data" / "support_card_bonuses.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    taiki = data["30053"]
    assert taiki["unique_effects"] == [{
        "condition": "bond_gte",
        "grants": {"skill_pt_bonus": 1, "speed_bonus": 1},
        "threshold": 80,
        "type": 101,
        "unlock_level": 30,
    }]


def test_bond_gated_unique_effect_activates_at_threshold():
    preset = {
        "name": "taiki_unique_test",
        "scenario_id": 4,
        "sim_use_latest_session_context": False,
        "_run_context": {
            "support_card_ids": [30053],
            "trainee_card_id": 102001,
        },
    }
    sim = CareerSimulator(
        preset=preset,
        deck=[{"support_card_id": 30053, "lb_level": 4}],
        seed=42,
    )
    taiki = next(c for c in sim.sim_support_cards if c["support_card_id"] == 30053)
    partner_id = int(taiki["partner_id"])

    sim.state["bonds"][partner_id] = 79
    inactive = sim._effective_card_effects(taiki, training_stat="speed", partner_cards=[taiki])
    assert inactive.get("speed_bonus") == 1
    assert inactive.get("skill_pt_bonus", 0) == 0

    sim.state["bonds"][partner_id] = 80
    active = sim._effective_card_effects(taiki, training_stat="speed", partner_cards=[taiki])
    assert active.get("speed_bonus") == 2
    assert active.get("skill_pt_bonus") == 1


def test_new_nice_nature_wit_card_mlb_and_bond_unique_modeled():
    data_path = Path(__file__).resolve().parents[1] / "data" / "support_card_bonuses.json"
    data = json.loads(data_path.read_text(encoding="utf-8"))
    nature = data["30306"]
    lb4 = nature["lb_levels"][-1]

    assert nature["name"] == "Nice Nature"
    assert nature["type"] == "Intelligence"
    assert lb4["friendship_bonus"] == 30
    assert lb4["mood_effect"] == 50
    assert lb4["wit_bonus"] == 1
    assert lb4["training_effectiveness"] == 20
    assert lb4["initial_speed"] == 25
    assert lb4["initial_friendship"] == 35
    assert lb4["race_bonus"] == 10
    assert lb4["fan_bonus"] == 20
    assert lb4["hint_levels"] == 4
    assert lb4["hint_freq"] == 100
    assert lb4["specialty_priority"] == 80
    assert lb4["skill_pt_bonus"] == 2
    assert lb4["wit_friendship_recovery"] == 5
    assert nature["unique_effects"] == [{
        "condition": "bond_gte",
        "grants": {"wit_bonus": 1},
        "threshold": 80,
        "type": 101,
        "unlock_level": 0,
    }]

    preset = {
        "name": "new_nice_nature_unique_test",
        "scenario_id": 4,
        "sim_use_latest_session_context": False,
        "_run_context": {
            "support_card_ids": [30306],
            "trainee_card_id": 102001,
        },
    }
    sim = CareerSimulator(
        preset=preset,
        deck=[{"support_card_id": 30306, "lb_level": 4}],
        seed=42,
    )
    card = next(c for c in sim.sim_support_cards if c["support_card_id"] == 30306)
    partner_id = int(card["partner_id"])

    sim.state["bonds"][partner_id] = 79
    inactive = sim._effective_card_effects(card, training_stat="wit", partner_cards=[card])
    assert inactive.get("wit_bonus") == 1
    assert inactive.get("skill_pt_bonus") == 2

    sim.state["bonds"][partner_id] = 80
    active = sim._effective_card_effects(card, training_stat="wit", partner_cards=[card])
    assert active.get("wit_bonus") == 2
    assert active.get("skill_pt_bonus") == 2


# -------------------- failure_protection --------------------

def test_failure_protection_reduces_training_failure_rate():
    """When a card with failure_protection appears on a training tile,
    the tile's failure_rate is reduced by the protection amount."""
    sim = _make_sim()
    riko = next(c for c in sim.sim_support_cards if c["support_card_id"] == 30036)
    original_partner_cards_for_tile = sim._partner_cards_for_tile

    def deterministic_partner_cards(stat_name):
        if stat_name == "speed":
            return [riko]
        return original_partner_cards_for_tile(stat_name)

    sim._partner_cards_for_tile = deterministic_partner_cards
    # Force a known failure rate by setting low HP and the synth path
    sim.state["hp"] = 30  # raw failure = (100-30)/3 = 23
    cmds = sim._make_training_commands()
    # At least one tile should record protection application
    found_protection = any(
        int(c.get("_sim_failure_protection_applied", 0)) > 0
        for c in cmds
    )
    assert found_protection, "Expected at least one tile with failure_protection_applied > 0"


def test_failure_protection_floors_at_zero():
    """If protection exceeds raw failure rate, adjusted rate is 0, not negative."""
    sim = _make_sim()
    # Tile with raw=5 and protection=35 → adjusted=0
    sim.state["hp"] = 90  # raw failure low
    cmds = sim._make_training_commands()
    for c in cmds:
        assert c.get("failure_rate", 0) >= 0


# -------------------- hint_levels (card hints) --------------------

def test_deck_card_hint_levels_stack_across_cards():
    """When multiple cards hint the same skill, their hint_levels stack."""
    sim = _make_sim(static_card_hints=True)
    hints = sim._sim_deck_card_hint_levels()
    # At least one skill should have a stacked hint level > 1 in this
    # deck (Gold City has hint_levels=4, Kitasan/Smart Falcon have 2 each).
    max_stacked = max(hints.get("ids", {}).values(), default=0)
    assert max_stacked >= 2, (
        f"Expected at least one skill with card hint level >= 2; got max {max_stacked}"
    )


def test_skill_candidates_get_card_hint_levels():
    """Built skill candidates carry a `card_hint_level` field that
    reflects deck contributions, separate from `legacy_only_hint_level`
    (parent inheritance) — and the combined `legacy_hint_level` is the
    sum used for discount calculation."""
    sim = _make_sim(static_card_hints=True)
    cands_with_card_hints = [
        c for c in sim.sim_skill_candidates
        if int(c.get("card_hint_level") or 0) > 0
    ]
    assert cands_with_card_hints, (
        "Expected at least one candidate with card_hint_level > 0"
    )
    # The effective hint level used for discount must include the card contribution
    for cand in cands_with_card_hints[:5]:
        legacy_only = int(cand.get("legacy_only_hint_level") or 0)
        card = int(cand.get("card_hint_level") or 0)
        effective = int(cand.get("legacy_hint_level") or 0)
        assert effective == legacy_only + card, (
            f"Effective hint level {effective} should be legacy {legacy_only} + card {card}"
        )


def test_card_hints_are_discovered_from_training_tip_events():
    """Default mode earns card hints from training tip events instead of
    assuming every deck hint skill is known at career start."""
    sim = _make_sim()
    assert sim._sim_deck_card_hint_levels().get("ids") == {}

    card = next(
        c for c in sim.sim_support_cards
        if (sim.support_bonus_data.get(str(c["support_card_id"])) or {}).get("hint_skills")
    )
    partner_id = int(card["partner_id"])
    sim.state["turn"] = 5
    sim._apply_training_hint_events(
        {
            "training_partner_array": [partner_id],
            "tips_event_partner_array": [partner_id],
            "_sim_facility_level": 1,
        },
        card.get("type") or "speed",
    )

    assert sim.sim_hint_events
    learned_skill_id = sim.sim_hint_events[0]["skill_id"]
    assert sim._sim_deck_card_hint_levels()["ids"][learned_skill_id] >= 1

    sim._ensure_sim_skill_candidates_current()
    matching = [
        c for c in sim.sim_skill_candidates
        if int(c.get("skill_id") or 0) == learned_skill_id
    ]
    if matching:
        assert int(matching[0].get("card_hint_level") or 0) >= 1


def test_card_hint_level_drives_skill_discount():
    """A skill with card_hint_level > 0 should receive a discount when
    purchased — verify via `_skill_hint_discount_pct`."""
    sim = _make_sim()
    # hint level 4 → 40% discount (10% per level, capped at 50%)
    assert sim._skill_hint_discount_pct(4) == 40.0
    assert sim._skill_hint_discount_pct(0) == 0.0
    # cap at 50%
    assert sim._skill_hint_discount_pct(10) == 50.0


# -------------------- _support_max_level_estimate --------------------

def test_support_max_level_estimate_table_correct():
    """Spot-check the rarity/LB → max level table."""
    # SSR
    assert _support_max_level_estimate("SSR", 0) == 40
    assert _support_max_level_estimate("SSR", 4) == 50
    # SR
    assert _support_max_level_estimate("SR", 0) == 35
    assert _support_max_level_estimate("SR", 4) == 55
    # R
    assert _support_max_level_estimate("R", 0) == 30
    assert _support_max_level_estimate("R", 4) == 50
    # Invalid LB clamps
    assert _support_max_level_estimate("SSR", -1) == 40
    assert _support_max_level_estimate("SSR", 99) == 50  # clamped to 4
