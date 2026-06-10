"""Tests for `_race_hard_stat_floor_bonus`.

Hard-floor enforcement on critical races. Kikuka Sho and Tenno Sho
(Spring) ship with narrow default stamina floors because repeated live
career losses showed soft race-prep pressure was not enough for those
long-distance traps. Tests can still pass `race_hard_floors` to exercise
operator overrides.
"""

from career_bot.scenarios.mant import MantStrategy

# Reusable preset that opts back into the Kikuka Sho stamina floor for
# testing purposes. Mirrors the older default the codebase used to ship.
KIKUKA_FLOOR_PRESET = {"race_hard_floors": {"168": {"stamina": 380}}}


class _MockRacePlanner:
    def __init__(self, scheduled):
        self.base_dir = "/tmp"
        self._scheduled = scheduled

    def scheduled_entries(self, preset):
        return self._scheduled


def test_zero_when_no_floor_race_scheduled():
    s = MantStrategy(_MockRacePlanner([
        {"turn": 30, "program_id": 73, "name": "Yasuda Kinen"},  # not in floor map
    ]))
    chara = {"turn": 25, "stamina": 100, "speed": 200, "power": 200, "guts": 100, "wiz": 200}
    assert s._race_hard_stat_floor_bonus(1, chara, KIKUKA_FLOOR_PRESET) == 0.0


def test_fires_when_stamina_far_below_kikuka_floor():
    """T28, Kikuka at T44, stamina 100 → projected ~177 (100 + 16*8*0.6)
    well below 380 → large bonus should fire (when preset opts in)."""
    s = MantStrategy(_MockRacePlanner([
        {"turn": 44, "program_id": 168, "name": "Kikuka Sho"},
    ]))
    chara = {"turn": 28, "stamina": 100, "speed": 200, "power": 200, "guts": 100, "wiz": 200}
    bonus = s._race_hard_stat_floor_bonus(1, chara, KIKUKA_FLOOR_PRESET)  # idx 1 = stamina
    assert bonus > 0.30  # bigger than soft demand cap
    assert bonus <= 0.80  # respects hard cap


def test_default_floor_map_fires_for_kikuka():
    """Kikuka has a default stamina floor because repeated live careers
    were entering it under-prepared and losing the scheduled G1."""
    s = MantStrategy(_MockRacePlanner([
        {"turn": 44, "program_id": 168, "name": "Kikuka Sho"},
    ]))
    chara = {"turn": 28, "stamina": 100, "speed": 200, "power": 200, "guts": 100, "wiz": 200}
    bonus = s._race_hard_stat_floor_bonus(1, chara, {})
    assert bonus > 0.30


def test_zero_when_stamina_already_above_floor():
    """T30, Kikuka at T44, stamina 400 → already above 380 → no bonus."""
    s = MantStrategy(_MockRacePlanner([
        {"turn": 44, "program_id": 168, "name": "Kikuka Sho"},
    ]))
    chara = {"turn": 30, "stamina": 400, "speed": 500, "power": 500, "guts": 200, "wiz": 400}
    assert s._race_hard_stat_floor_bonus(1, chara, KIKUKA_FLOOR_PRESET) == 0.0


def test_dense_route_keeps_pressure_when_projection_is_still_short():
    """T28, stamina 320 → projected = 320 + 16*8*0.6 = 396 ≥ 380 → no bonus."""
    s = MantStrategy(_MockRacePlanner([
        {"turn": 44, "program_id": 168, "name": "Kikuka Sho"},
    ]))
    chara = {"turn": 28, "stamina": 320, "speed": 400, "power": 400, "guts": 200, "wiz": 400}
    bonus = s._race_hard_stat_floor_bonus(1, chara, KIKUKA_FLOOR_PRESET)
    assert bonus > 0.0


def test_does_not_fire_for_non_stamina_idx():
    """Even with a Kikuka floor on stamina, training Speed shouldn't trigger it."""
    s = MantStrategy(_MockRacePlanner([
        {"turn": 44, "program_id": 168, "name": "Kikuka Sho"},
    ]))
    chara = {"turn": 28, "stamina": 100, "speed": 200, "power": 200, "guts": 100, "wiz": 200}
    assert s._race_hard_stat_floor_bonus(0, chara, KIKUKA_FLOOR_PRESET) == 0.0  # idx 0 = Speed
    assert s._race_hard_stat_floor_bonus(2, chara, KIKUKA_FLOOR_PRESET) == 0.0  # idx 2 = Power


def test_urgency_scaling_closer_race_bigger_bonus():
    """Closer race → urgency factor higher → bigger bonus for same deficit."""
    chara = {"turn": 38, "stamina": 150, "speed": 200, "power": 200, "guts": 100, "wiz": 200}
    s_close = MantStrategy(_MockRacePlanner([
        {"turn": 40, "program_id": 168, "name": "Kikuka Sho"},  # 2 turns out
    ]))
    s_far = MantStrategy(_MockRacePlanner([
        {"turn": 55, "program_id": 168, "name": "Kikuka Sho"},  # 17 turns out
    ]))
    close = s_close._race_hard_stat_floor_bonus(1, chara, KIKUKA_FLOOR_PRESET)
    far = s_far._race_hard_stat_floor_bonus(1, dict(chara, turn=23), KIKUKA_FLOOR_PRESET)
    assert close > far


def test_zero_when_race_outside_lookahead_window():
    """Race 25 turns out: outside the 20-turn lookahead window → no bonus."""
    s = MantStrategy(_MockRacePlanner([
        {"turn": 55, "program_id": 168, "name": "Kikuka Sho"},
    ]))
    chara = {"turn": 25, "stamina": 100, "speed": 200, "power": 200, "guts": 100, "wiz": 200}
    bonus = s._race_hard_stat_floor_bonus(1, chara, KIKUKA_FLOOR_PRESET)
    # 30 turns out > 20-turn lookahead → no bonus
    assert bonus == 0.0


def test_zero_when_race_already_past():
    """Race in past doesn't fire."""
    s = MantStrategy(_MockRacePlanner([
        {"turn": 20, "program_id": 168, "name": "Kikuka Sho"},
    ]))
    chara = {"turn": 30, "stamina": 100, "speed": 200, "power": 200, "guts": 100, "wiz": 200}
    assert s._race_hard_stat_floor_bonus(1, chara, KIKUKA_FLOOR_PRESET) == 0.0


def test_preset_can_add_custom_hard_floors():
    """Operator can extend the floor map via preset (the preset-only path
    is now the only way to opt in)."""
    s = MantStrategy(_MockRacePlanner([
        {"turn": 56, "program_id": 4, "name": "Tenno Sho (Spring)"},
    ]))
    chara = {"turn": 38, "stamina": 100, "speed": 200, "power": 200, "guts": 100, "wiz": 200}
    preset = {"race_hard_floors": {"4": {"stamina": 550}}}
    bonus = s._race_hard_stat_floor_bonus(1, chara, preset)
    assert bonus > 0


def test_bypasses_deck_realism_throttle():
    """Even with 0 stamina cards in the deck (deck_realism would be 0.3
    for the soft demand bonus), the hard floor still fires at full
    magnitude — this is the whole point."""
    s = MantStrategy(_MockRacePlanner([
        {"turn": 44, "program_id": 168, "name": "Kikuka Sho"},
    ]))
    chara = {"turn": 28, "stamina": 100, "speed": 200, "power": 200, "guts": 100, "wiz": 200}
    preset = dict(KIKUKA_FLOOR_PRESET)
    preset["_run_context"] = {"support_cards": [
        {"type": "Speed", "name": "X"}, {"type": "Speed", "name": "Y"},
        {"type": "Power", "name": "Z"},
    ]}
    bonus = s._race_hard_stat_floor_bonus(1, chara, preset)
    # If deck-realism were applied, bonus would be tiny. We expect full strength.
    assert bonus > 0.30


def test_zero_before_cap_pursuit_start_turn():
    """Bonus dormant in very early Junior."""
    s = MantStrategy(_MockRacePlanner([
        {"turn": 44, "program_id": 168, "name": "Kikuka Sho"},
    ]))
    chara = {"turn": 5, "stamina": 80, "speed": 100, "power": 100, "guts": 80, "wiz": 100}
    assert s._race_hard_stat_floor_bonus(1, chara, KIKUKA_FLOOR_PRESET) == 0.0
