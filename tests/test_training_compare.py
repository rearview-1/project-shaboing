from career_bot.training_compare import TrainingTileCalculator, rank_candidate_cards, tile_gain


def test_tile_gain_reuses_uma_guide_anchor():
    gains = tile_gain([(20031, 4), (30028, 4)], "speed", facility_level=5, mood=0.2)
    assert gains["speed"] == 38
    assert gains["power"] == 20


def test_rank_candidate_cards_reports_delta_vs_baseline():
    rows = rank_candidate_cards(
        baseline_deck=[(30028, 4)],
        candidates=[20031, 30078],
        training_stat="speed",
        facility_level=5,
        mood=0.2,
        weights={"speed": 1, "power": 1, "sp": 0.5},
    )
    ids = {row.support_card_id for row in rows}
    assert ids == {20031, 30078}
    assert all(row.weighted_score > 0 for row in rows)
    assert all("speed" in row.delta_vs_baseline for row in rows)


def test_scenario_effects_are_opt_in_and_modify_tile():
    effects = {
        "scenarios": {
            "test": {
                "aliases": ["test_scenario"],
                "effects": [
                    {
                        "id": "speed_push",
                        "conditions": {"training": ["speed"], "facility_level_min": 5},
                        "apply": {
                            "base_add": {"speed": 1},
                            "stat_bonus": {"speed": 2},
                            "training_effectiveness": 10,
                            "final_add": {"sp": 2},
                        },
                    }
                ],
            }
        }
    }
    inactive = TrainingTileCalculator(
        scenario_key="test_scenario",
        scenario_effects=effects,
        active_scenario_effects=[],
    ).tile_gain([(30028, 4)], "speed")
    active = TrainingTileCalculator(
        scenario_key="test_scenario",
        scenario_effects=effects,
        active_scenario_effects=["speed_push"],
    ).tile_gain([(30028, 4)], "speed")

    assert active["speed"] > inactive["speed"]
    assert active["sp"] >= inactive["sp"] + 2


def test_scenario_friendship_multiplier_requires_friendship_tile():
    effect = {
        "id": "friendship_push",
        "apply": {"friendship_multiplier": 1.50},
    }
    calc = TrainingTileCalculator()

    no_card_base = calc.tile_gain([], "speed", facility_level=5, mood=0.2, bonded=True)
    no_card_with_friendship = calc.tile_gain(
        [],
        "speed",
        facility_level=5,
        mood=0.2,
        bonded=True,
        scenario_effects=[effect],
    )
    assert no_card_with_friendship == no_card_base

    card_base = calc.tile_gain([(30028, 4)], "speed", facility_level=5, mood=0.2, bonded=True)
    card_with_friendship = calc.tile_gain(
        [(30028, 4)],
        "speed",
        facility_level=5,
        mood=0.2,
        bonded=True,
        scenario_effects=[effect],
    )
    assert card_with_friendship["speed"] > card_base["speed"]


def test_training_sim_gimmicks_do_not_attach_region_effects_to_gamewith_order_14():
    import main

    assert main._training_sim_scenario_gimmicks("mant_base") == ["items"]
    assert main._training_sim_scenario_gimmicks("1") == ["year_effects"]
    assert main._training_sim_scenario_gimmicks("14") == []
