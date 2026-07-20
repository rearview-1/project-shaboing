from tools.apply_gametora_hachimi_skill_names import build_skill_factor_names


def test_skill_factor_names_generate_rest_and_rise_hint_traits():
    factor_names = build_skill_factor_names(
        {
            "210371": "Miracle of Recreation",
            "210372": "Rest and Rise",
        }
    )

    assert factor_names["2103701"] == "Rest and Rise"
    assert factor_names["2103702"] == "Rest and Rise"
    assert factor_names["2103703"] == "Rest and Rise"


def test_skill_factor_names_do_not_generate_race_factor_collisions():
    factor_names = build_skill_factor_names(
        {
            "100011": "Shooting Star",
            "200592": "Position Pilfer",
        }
    )

    assert "1000101" not in factor_names
    assert factor_names["2005901"] == "Position Pilfer"
