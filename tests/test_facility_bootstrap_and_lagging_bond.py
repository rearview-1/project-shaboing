"""Tests for the two bond/facility-balance fixes wired after the
S+ 16,116 audit revealed:
  (a) Wit/Wisdom facility stuck at lv2 through Senior summer while
      Speed climbed to lv4.
  (b) Fine Motion (one of two Wisdom cards) stuck at bond 72 the entire
      career while Nice Nature (the other) hit 94.

Fixes:
  C — `_stat_facility_should_bootstrap` + `_FACILITY_BOOTSTRAP_BONUS`:
      pushes facility-leveling for deck-supported stats (and Wit).
  D — `_lagging_bond_partner_bonus`: rewards tiles where the
      lowest-bonded deck partner appears.
"""

from career_bot.scenarios.mant import MantStrategy, DECK_PARTNERS


def _strategy_with_preset(preset):
    s = MantStrategy(None)
    s.preset = preset or {}
    return s


def _chara_with_bonds(bonds_by_partner):
    return {
        "evaluation_info_array": [
            {"target_id": pid, "evaluation": bond}
            for pid, bond in bonds_by_partner.items()
        ],
        "speed": 700,
        "stamina": 500,
        "power": 600,
        "guts": 400,
        "wiz": 600,
        "vital": 80,
        "turn": 20,
    }


# --- Fix C: facility bootstrap ---

def test_wit_always_qualifies_for_bootstrap():
    s = MantStrategy(None)
    # Even with no deck info, Wit should bootstrap per operator policy.
    cmd_wit = {"command_id": 106}
    assert s._stat_facility_should_bootstrap(cmd_wit, {}) is True


def test_guts_does_not_qualify_without_deck_support():
    s = MantStrategy(None)
    cmd_guts = {"command_id": 103}
    # No deck info, no Guts support → no bootstrap.
    assert s._stat_facility_should_bootstrap(cmd_guts, {}) is False


def test_deck_supported_stat_qualifies_for_bootstrap(monkeypatch):
    s = MantStrategy(None)
    # Pretend the deck supports Speed (mock cap_pursuit set).
    monkeypatch.setattr(
        s,
        "_cap_pursuit_deck_derived_stats",
        lambda preset: {"speed"},
    )
    cmd_speed = {"command_id": 101}
    cmd_power = {"command_id": 102}
    assert s._stat_facility_should_bootstrap(cmd_speed, {}) is True
    assert s._stat_facility_should_bootstrap(cmd_power, {}) is False


def test_bootstrap_fires_when_facility_low_and_stat_supported(monkeypatch):
    s = MantStrategy(None)
    monkeypatch.setattr(s, "_cap_pursuit_deck_derived_stats", lambda preset: {"speed"})
    # Force the helper to report lv 1, until_next=4 (no other bonus path
    # would fire). turn=12 is mid-Junior, well under the end turn.
    monkeypatch.setattr(s, "_facility_level_info", lambda command, chara: (1, 0, 4))
    cmd_speed = {"command_id": 101}
    bonus = s._facility_level_training_bonus(cmd_speed, {}, {}, 12)
    assert bonus > 0.10  # bootstrap should dominate other small terms


def test_bootstrap_does_not_fire_for_unsupported_stat(monkeypatch):
    s = MantStrategy(None)
    monkeypatch.setattr(s, "_cap_pursuit_deck_derived_stats", lambda preset: {"speed"})
    monkeypatch.setattr(s, "_facility_level_info", lambda command, chara: (1, 0, 4))
    cmd_guts = {"command_id": 103}
    bonus = s._facility_level_training_bonus(cmd_guts, {}, {}, 12)
    assert bonus == 0.0


def test_bootstrap_stops_after_end_turn(monkeypatch):
    s = MantStrategy(None)
    monkeypatch.setattr(s, "_cap_pursuit_deck_derived_stats", lambda preset: {"speed"})
    monkeypatch.setattr(s, "_facility_level_info", lambda command, chara: (1, 0, 4))
    # Turn 70 is past _FACILITY_BOOTSTRAP_END_TURN (56) — too late.
    bonus = s._facility_level_training_bonus({"command_id": 101}, {}, {}, 70)
    assert bonus == 0.0


def test_bootstrap_stops_after_facility_lv3(monkeypatch):
    s = MantStrategy(None)
    monkeypatch.setattr(s, "_cap_pursuit_deck_derived_stats", lambda preset: {"speed"})
    monkeypatch.setattr(s, "_facility_level_info", lambda command, chara: (3, 0, 4))
    # Bootstrap only fires for level <= 2. At lv3, only the existing
    # reinforcement should fire, not the bootstrap.
    bonus = s._facility_level_training_bonus({"command_id": 101}, {"vital": 50, "max_vital": 100}, {}, 12)
    # Bonus should be only the reinforcement portion, NOT the +0.20 bootstrap.
    assert bonus < 0.20


# --- Fix D: lagging-bond targeting ---

def test_lagging_bond_fires_when_one_deck_partner_is_far_behind():
    s = MantStrategy(None)
    # Deck partners 1-6: partner 4 at bond 50, others at 80.
    bonds = {1: 80, 2: 80, 3: 80, 4: 50, 5: 80, 6: 80}
    chara = _chara_with_bonds(bonds)
    # Command where partner 4 (the lagging one) appears.
    cmd = {"command_id": 106, "training_partner_array": [4, 5]}
    bonus = s._lagging_bond_partner_bonus(cmd, chara, {}, 30)
    assert bonus > 0


def test_lagging_bond_does_not_fire_if_lagging_partner_not_on_tile():
    s = MantStrategy(None)
    bonds = {1: 80, 2: 80, 3: 80, 4: 50, 5: 80, 6: 80}
    chara = _chara_with_bonds(bonds)
    # Lagging partner is 4, but only 5 appears on this tile.
    cmd = {"command_id": 106, "training_partner_array": [5]}
    bonus = s._lagging_bond_partner_bonus(cmd, chara, {}, 30)
    assert bonus == 0.0


def test_lagging_bond_does_not_fire_if_all_partners_above_threshold():
    s = MantStrategy(None)
    bonds = {1: 80, 2: 80, 3: 80, 4: 75, 5: 80, 6: 80}
    chara = _chara_with_bonds(bonds)
    # Lagging partner 4 at 75 — above the 70 threshold.
    cmd = {"command_id": 106, "training_partner_array": [4]}
    bonus = s._lagging_bond_partner_bonus(cmd, chara, {}, 30)
    assert bonus == 0.0


def test_lagging_bond_disabled_in_senior():
    s = MantStrategy(None)
    bonds = {1: 80, 2: 80, 3: 80, 4: 50, 5: 80, 6: 80}
    chara = _chara_with_bonds(bonds)
    cmd = {"command_id": 106, "training_partner_array": [4]}
    # Past the late-turn threshold (60).
    bonus = s._lagging_bond_partner_bonus(cmd, chara, {}, 65)
    assert bonus == 0.0


def test_lagging_bond_scales_with_gap():
    s = MantStrategy(None)
    chara_50 = _chara_with_bonds({1: 80, 2: 80, 3: 80, 4: 50, 5: 80, 6: 80})
    chara_65 = _chara_with_bonds({1: 80, 2: 80, 3: 80, 4: 65, 5: 80, 6: 80})
    cmd_with_4 = {"command_id": 106, "training_partner_array": [4]}
    b_far = s._lagging_bond_partner_bonus(cmd_with_4, chara_50, {}, 30)
    b_close = s._lagging_bond_partner_bonus(cmd_with_4, chara_65, {}, 30)
    assert b_far > b_close
