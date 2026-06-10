from career_bot.scenarios.mant import MantStrategy


class _MockRacePlanner:
    base_dir = "/tmp"

    def __init__(self, scheduled, requirements):
        self._scheduled = scheduled
        self._requirements = requirements

    def scheduled_entries(self, preset):
        return self._scheduled

    def stamina_for_program(self, state, preset, program_id, entry=None):
        return {
            "program_id": program_id,
            "grade": (entry or {}).get("type", ""),
            "requirements": dict(self._requirements),
        }


def test_scheduled_race_safety_pushes_underprepared_speed():
    strategy = MantStrategy(_MockRacePlanner(
        [{"turn": 17, "program_id": 629, "name": "Niigata Junior Stakes", "type": "G3"}],
        {"speed": 420, "stamina": 230, "power": 350, "guts": 200, "wit": 190},
    ))
    chara = {"turn": 12, "speed": 150, "stamina": 120, "power": 150, "guts": 100, "wiz": 120}
    bonus = strategy._scheduled_race_safety_training_bonus(
        0,
        chara,
        {"scheduled_race_clean_record_mode": True},
    )
    assert bonus > 0.10


def test_scheduled_race_safety_dormant_when_projection_is_safe():
    strategy = MantStrategy(_MockRacePlanner(
        [{"turn": 17, "program_id": 629, "name": "Niigata Junior Stakes", "type": "G3"}],
        {"speed": 420, "stamina": 230, "power": 350, "guts": 200, "wit": 190},
    ))
    chara = {"turn": 12, "speed": 410, "stamina": 230, "power": 350, "guts": 200, "wiz": 190}
    bonus = strategy._scheduled_race_safety_training_bonus(
        0,
        chara,
        {"scheduled_race_clean_record_mode": True},
    )
    assert bonus == 0.0


def test_scheduled_race_safety_can_be_disabled():
    strategy = MantStrategy(_MockRacePlanner(
        [{"turn": 17, "program_id": 629, "name": "Niigata Junior Stakes", "type": "G3"}],
        {"speed": 420, "stamina": 230, "power": 350, "guts": 200, "wit": 190},
    ))
    chara = {"turn": 12, "speed": 150, "stamina": 120, "power": 150, "guts": 100, "wiz": 120}
    bonus = strategy._scheduled_race_safety_training_bonus(
        0,
        chara,
        {"scheduled_race_clean_record_mode": False},
    )
    assert bonus == 0.0
