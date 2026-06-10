from career_bot.scenarios.mant import MantStrategy
from career_bot.training_policy import command_features


def _preset():
    return {
        "expect_attribute": [1200, 1166, 1166, 1166, 1166],
        "expect_attribute_profiles": {
            "balanced_any": {
                "sample_count": 1,
                "expect_attribute": [1200, 627, 1003, 564, 891],
            },
            "balanced_any|style=front_runner|distance=long|deck_q=2": {
                "sample_count": 296,
                "expect_attribute": [1135, 848, 1043, 656, 1013],
            },
        },
        "skill_profile_style": "front_runner",
        "skill_profile_distance": "long",
        "_deck_quality_bucket": 2,
        "desired_parent_sparks": {"blue": [], "pink": [], "green": [], "white": []},
    }


def _chara():
    return {
        "turn": 40,
        "speed": 900,
        "stamina": 700,
        "power": 900,
        "guts": 500,
        "wiz": 800,
        "vital": 80,
        "max_vital": 100,
        "evaluation_info_array": [],
    }


def _stamina_command():
    return {
        "command_type": 1,
        "command_id": 105,
        "failure_rate": 0,
        "training_partner_array": [],
        "tips_event_partner_array": [],
        "params_inc_dec_info_array": [
            {"target_type": 2, "value": 20},
        ],
    }


def test_mant_training_understanding_uses_specific_expect_attribute_profile():
    strategy = MantStrategy()

    understanding = strategy._training_decision_understanding(_stamina_command(), _chara(), _preset())

    assert understanding["signals"]["target_cap"] == 848
    assert understanding["signals"]["target_ratio"] == round(700 / 848, 4)


def test_training_policy_features_use_specific_expect_attribute_profile():
    features = command_features(_stamina_command(), _chara(), _preset())

    assert features["under_target"] > 0.15
    assert features["over_target"] == 0.0


def test_mant_target_lookup_falls_back_to_schedule_distance_context():
    preset = _preset()
    preset.pop("skill_profile_distance")
    preset["custom_race_schedule"] = [
        {"turn": 47, "program_id": 1, "distance": "Long"},
        {"turn": 55, "program_id": 2, "distance": "Long"},
        {"turn": 63, "program_id": 3, "distance": "Medium"},
    ]
    strategy = MantStrategy()

    assert strategy._expect_attribute_targets(preset, _chara())[1] == 848
