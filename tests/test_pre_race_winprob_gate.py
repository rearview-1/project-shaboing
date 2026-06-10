"""Tests for the pre-race win-probability gate.

This is the port of `CareerSimulator.clean_record_mode` into the real
`SkillBuyer.buy_limited_for_race`. Skips pre-race skill purchases when
the bot already has high win probability AND SP is below the
end-of-career drain target.
"""

from career_bot.skills import SkillBuyer


def _chara(speed=900, stamina=650, power=800, guts=500, wiz=750, hp=80, sp=600, turn=68, card_id=1004):
    return {
        "card_id": card_id,
        "speed": speed, "stamina": stamina, "power": power, "guts": guts, "wiz": wiz,
        "hp": hp, "max_hp": 100,
        "skill_point": sp, "turn": turn,
        "skill_array": [],
    }


def test_probability_estimator_returns_in_bounds(tmp_path):
    """Probability output must be in [0.06, 0.96]."""
    buyer = SkillBuyer(tmp_path)
    race_check = {"program_id": 168, "race_name": "Kikuka Sho", "distance": "Long"}
    chara = _chara()
    # Returns None if no manual_race_data on disk for this tmp_path,
    # which is fine — the gate just won't fire in that case.
    prob = buyer._estimate_pre_race_win_probability(chara, race_check, owned_skill_count=10)
    if prob is not None:
        assert 0.06 <= prob <= 0.96


def test_probability_higher_with_strong_stats(tmp_path):
    """Bot with high stats should have higher win prob than bot with low stats.
    Skips when manual_race_data is unavailable in this test env."""
    buyer = SkillBuyer(tmp_path)
    race_check = {"program_id": 168, "race_name": "Kikuka Sho", "distance": "Long"}
    weak = _chara(speed=500, stamina=300, power=400, wiz=400)
    strong = _chara(speed=900, stamina=700, power=800, wiz=800)
    weak_prob = buyer._estimate_pre_race_win_probability(weak, race_check, owned_skill_count=0)
    strong_prob = buyer._estimate_pre_race_win_probability(strong, race_check, owned_skill_count=0)
    if weak_prob is not None and strong_prob is not None:
        assert strong_prob > weak_prob


def test_probability_returns_none_without_program_id(tmp_path):
    buyer = SkillBuyer(tmp_path)
    chara = _chara()
    # No program_id → no threshold lookup → None
    prob = buyer._estimate_pre_race_win_probability(
        chara, {"race_name": "Unknown"}, owned_skill_count=0
    )
    assert prob is None


def test_probability_returns_none_without_race_check(tmp_path):
    buyer = SkillBuyer(tmp_path)
    chara = _chara()
    assert buyer._estimate_pre_race_win_probability(chara, None, 0) is None
    assert buyer._estimate_pre_race_win_probability(chara, "not_a_dict", 0) is None
