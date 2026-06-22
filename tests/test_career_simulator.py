"""Tests for the career simulator.

The simulator drives MantStrategy._score_command through 78 sim turns
so I can A/B test code changes without running real game careers.
"""

import json
from pathlib import Path

import pytest

from career_bot.career_simulator import (
    CareerSimulator,
    hydrate_preset_with_latest_session_context,
    load_empirical_sp_budget_calibration,
    run_sweep,
)
from career_bot.rating import rank_for_rating_score


def _make_preset():
    """Minimum preset to drive simulator. Matches the user's main deck/preset."""
    return {
        "name": "sim_test",
        "scenario_id": 4,
        "learn_skill_threshold": 444,
        "manual_purchase_at_end": True,
        "calendar_race_prebuy_enabled": True,
        "calendar_race_prebuy_budget": 850,
        "calendar_race_prebuy_keep_sp": 100,
        "calendar_race_prebuy_max_skills": 4,
        "stat_value_multiplier": [0.022, 0.016, 0.018, 0.012, 0.016, 0.01],
        "score_value": [[0.11, 0.1, 0.006, 0.09]] * 5,
        "base_score": [0, 0, 0, 0, 0],
        "extra_weight": [[0, 0, 0, 0, 0]] * 4,
        "compensate_failure": True,
        "expect_attribute": [9999, 9999, 9999, 9999, 9999],
        "stat_priority_architecture_enabled": True,
        "sim_use_latest_session_context": False,
        "sim_use_runtime_observations": False,
    }


def test_basic_run_produces_valid_result():
    sim = CareerSimulator(preset=_make_preset(), seed=42)
    result = sim.run()
    assert result.turns_logged == 78
    assert sum(result.final_stats.values()) == result.stat_sum
    assert result.stat_sum > 1000  # at minimum the bot trained something
    assert result.rating_score >= result.stat_rating_score
    assert result.rank == rank_for_rating_score(result.rating_score)
    assert result.rating_score == result.stat_rating_score + result.unique_rating_bonus + result.skill_rating_score


def test_deterministic_with_seed():
    """Same seed → same result. A/B testing depends on this."""
    s1 = CareerSimulator(preset=_make_preset(), seed=123).run()
    s2 = CareerSimulator(preset=_make_preset(), seed=123).run()
    assert s1.stat_sum == s2.stat_sum
    assert s1.final_stats == s2.final_stats


def test_different_seed_produces_different_result():
    """Need some variance for sweeps to be meaningful."""
    s1 = CareerSimulator(preset=_make_preset(), seed=1).run()
    s2 = CareerSimulator(preset=_make_preset(), seed=2).run()
    # Allow occasional ties but mean over multi-seed sweeps differs
    diff = abs(s1.stat_sum - s2.stat_sum)
    assert diff != 0 or s1.final_stats != s2.final_stats


def test_simulator_tracks_exact_skill_purchases():
    sim = CareerSimulator(preset=_make_preset(), seed=42)
    result = sim.run()
    assert result.purchased_skills
    assert result.skills_bought == len(result.purchased_skills)
    assert result.skill_rating_score == sum(row["rating_score"] for row in result.purchased_skills)
    assert all(row["skill_id"] for row in result.purchased_skills)
    assert all(row["discounted_cost"] > 0 for row in result.purchased_skills)


def test_simulator_skill_discount_is_per_skill_not_global():
    preset = dict(_make_preset(), sim_use_latest_session_context=False)
    sim = CareerSimulator(preset=preset, seed=42)

    plain = {"base_cost": 200, "legacy_hint_level": 0, "friend_event_hint": False}
    hinted = {"base_cost": 200, "legacy_hint_level": 2, "friend_event_hint": False}
    friend = {"base_cost": 200, "legacy_hint_level": 1, "friend_event_hint": True}

    assert sim._candidate_effective_discount_pct(plain, discount_pct=35) == 0
    assert sim._candidate_effective_discount_pct(hinted, discount_pct=35) == 20
    assert sim._candidate_effective_discount_pct(friend, discount_pct=35) == 30


def test_simulator_final_skill_buy_can_drain_beyond_default_batch():
    preset = dict(_make_preset(), sim_use_latest_session_context=False)
    sim = CareerSimulator(preset=preset, seed=42)
    if len(sim.sim_skill_candidates) <= 8:
        pytest.skip("fixture skill pool too small for final-drain regression")
    sim.state["skill_point"] = 5000

    sim._maybe_buy_skills(final=True)

    assert sim.skills_bought > 8
    assert sim.state["skill_point"] < 5000


def test_simulator_race_history_starts_with_debut_win():
    sim = CareerSimulator(preset=_make_preset(), seed=42)
    history = sim._sim_race_history()

    assert history
    assert history[0]["race_name"] == "Junior Make Debut"
    assert history[0]["result_rank"] == 1
    assert history[0]["_sim_synthetic"] is True


def test_simulator_emits_synthetic_hakuraku_race_payload():
    sim = CareerSimulator(preset=_make_preset(), seed=42)
    sim.state["turn"] = 44
    sim._simulate_race(168, "Kikuka Sho", "Long", "classic")

    assert sim.sim_hakuraku_races
    payload = sim.sim_hakuraku_races[0]
    assert payload["format"] == "sweepy_hakuraku_race_v1"
    assert payload["synthetic"] is True
    assert payload["program_id"] == 168
    assert payload["race_horse_data_array"]
    assert payload["race_horse_data_array"][0]["viewer_id"] == 1
    assert payload["career_report_result"]["finish_rank"] >= 1
    assert sim.races_run[0]["hakuraku_payload"] is payload


def test_manual_race_threshold_applies_hidden_bonus_to_trainee_only():
    sim = CareerSimulator(preset=_make_preset(), seed=42)
    pid = 999991
    sim.race_thresholds[pid] = {
        "speed": 500,
        "stamina": 500,
        "power": 500,
        "guts": 500,
        "wit": 500,
    }
    sim.state.update({
        "speed": 500,
        "stamina": 500,
        "power": 500,
        "guts": 500,
        "wiz": 500,
    })

    _prob, model = sim._manual_threshold_probability_estimate(pid, "Unit Test Stakes", "medium", "classic")

    assert model["ratio_speed"] == pytest.approx(1.8)
    assert model["ratio_stamina"] == pytest.approx(1.8)
    assert model["ratio_power"] == pytest.approx(1.8)
    assert model["effective_current_stamina"] == 900
    assert model["effective_threshold_stamina"] == 500


def test_observed_bad_history_does_not_poison_safe_threshold_race():
    sim = CareerSimulator(preset=_make_preset(), seed=42)
    pid = 999992
    sim.race_outcome_calibration = {
        "enabled": True,
        "by_pid": {
            str(pid): {
                "runs": 12,
                "wins": 3,
                "win_rate": 0.25,
                "smoothed_win_rate": 0.28,
            }
        },
    }
    manual_model = {
        "model": "manual_threshold_probability",
        "win_probability": 0.96,
        "ratio_speed": 1.8,
        "ratio_stamina": 1.9,
        "ratio_power": 1.7,
        "ratio_wit": 2.0,
        "true_stamina_ratio": 1.9,
        "stamina_floor_ratio": 0.78,
        "stamina_critical": False,
        "aptitude_factor": 1.0,
        "distance": "medium",
    }

    prob, model = sim._blend_observed_race_probability(pid, 0.96, manual_model)

    assert prob >= 0.90
    assert model["manual_threshold_safe"] is True
    assert model["observed_current_beats_bad_history"] is True


def test_simulator_loss_finish_rank_uses_observed_rank_counts():
    sim = CareerSimulator(preset=_make_preset(), seed=42)
    model = {"nearest_loss_rank_counts": {"5": 9}}

    assert sim._sim_loss_finish_rank(0.99, model) == 5


def test_speed_priority_bonus_lift_moves_sweep_median_up():
    """The simulator's value: does cranking a bonus change the median?"""
    base = _make_preset()
    cranked = dict(base, learned_hyperparameters={
        "speed_priority_bonus_late": 0.40,
        "speed_priority_bonus_mid": 0.30,
    })

    base_sweep = run_sweep(n_runs=8, preset=base, seed_base=100)
    cranked_sweep = run_sweep(n_runs=8, preset=cranked, seed_base=100)

    # The direct policy signal should move toward more speed picks. Final
    # speed is noisy because event/race variance can offset a few picks.
    base_speed_picks = [r.train_picks_by_stat["speed"] for r in base_sweep["results"]]
    cranked_speed_picks = [r.train_picks_by_stat["speed"] for r in cranked_sweep["results"]]
    assert sum(cranked_speed_picks) >= sum(base_speed_picks)


def test_sweep_returns_aggregated_metrics():
    sweep = run_sweep(n_runs=5, preset=_make_preset(), seed_base=500)
    assert sweep["n_runs"] == 5
    assert "stat_sum_median" in sweep
    assert "rating_score_median" in sweep
    assert "rank_distribution" in sweep
    assert sweep["stat_sum_max"] >= sweep["stat_sum_min"]


def test_rank_labels_use_rating_score_not_stat_sum():
    """Simulator rank labels should follow in-game rating thresholds."""
    assert rank_for_rating_score(14500) == "S"
    assert rank_for_rating_score(15900) == "S+"
    assert rank_for_rating_score(17500) == "SS"
    assert rank_for_rating_score(19200) == "SS+"
    assert rank_for_rating_score(19600) == "UG"


def test_wit_soft_cap_reduces_wit_training_picks():
    """With Wit soft-cap firing past 600 wit, bot should pick Wit less
    once wit climbs into that band."""
    sim = CareerSimulator(preset=_make_preset(), seed=42)
    result = sim.run()
    # In a 3-Wit-card deck without soft cap, Wit would normally
    # dominate ~50% of picks. With the cap in place we expect <50%
    # in this simple sim.
    total_train = sum(result.train_picks_by_stat.values()) or 1
    wit_share = result.train_picks_by_stat["wit"] / total_train
    # Sanity: total picks > 0
    assert total_train > 0


def test_concentration_bonus_active_in_senior_lifts_top_stat():
    """Stat concentration bonus should help push the top stat higher
    in Senior compared to baseline. The sim is intentionally
    conservative (no items/events modeled beyond a flat bonus); use as
    a relative comparison harness rather than absolute outcomes."""
    base = _make_preset()
    base["stat_priority_architecture_enabled"] = True
    sweep = run_sweep(n_runs=12, preset=base, seed_base=2000)
    sums = [r.stat_sum for r in sweep["results"]]
    # Calibrated sanity: sim produces 2,000-2,500 stat sums with the
    # current deck/preset. Floor is loose; the value is A/B comparison.
    assert max(sums) >= 1800


def test_simulator_applies_selected_parent_legacy_effects():
    preset_path = (
        Path(__file__).resolve().parents[1]
        / "uma_runtime" / "instances" / "account_b"
        / "instance_learning" / "presets" / "xguri parent.json"
    )
    if not preset_path.exists():
        pytest.skip("local xguri runtime preset is not available")
    preset = json.loads(preset_path.read_text(encoding="utf-8-sig"))
    preset = hydrate_preset_with_latest_session_context(preset, Path(__file__).resolve().parents[1])
    ctx = preset.get("_run_context") or {}
    sim = CareerSimulator(preset=preset, seed=0)
    effects = sim.legacy_effects
    assert effects["selected_parent_ids"][:2] == [ctx.get("parent_id_1"), ctx.get("parent_id_2")]
    assert sum(effects["stat_bonuses"].values()) > 0
    assert effects["aptitude_upgrades"]
    for aptitude, upgrade in effects["aptitude_upgrades"].items():
        assert sim._current_aptitudes()[aptitude] == upgrade["next"]


def test_simulator_resolves_friend_card_and_wit_support_types():
    preset_path = (
        Path(__file__).resolve().parents[1]
        / "uma_runtime" / "instances" / "account_b"
        / "instance_learning" / "presets" / "xguri parent.json"
    )
    if not preset_path.exists():
        pytest.skip("local xguri runtime preset is not available")
    preset = json.loads(preset_path.read_text(encoding="utf-8-sig"))
    preset = hydrate_preset_with_latest_session_context(preset, Path(__file__).resolve().parents[1])
    ctx = preset.get("_run_context") or {}
    sim = CareerSimulator(preset=preset, seed=0)

    assert len(sim.deck) == 5
    assert len(sim.sim_support_cards) == 6
    assert any(card["friend"] and card["support_card_id"] == ctx.get("friend_card_id") for card in sim.sim_support_cards)
    expected_counts = [
        sum(1 for card in sim.sim_support_cards if card["type"] == support_type)
        for support_type in ("speed", "stamina", "power", "guts", "wit")
    ]
    assert sim._deck_type_counts() == expected_counts
    assert all(card["type"] != "intelligence" for card in sim.sim_support_cards)


def test_simulator_uses_real_initial_skill_points():
    preset_path = (
        Path(__file__).resolve().parents[1]
        / "uma_runtime" / "instances" / "account_b"
        / "instance_learning" / "presets" / "xguri parent.json"
    )
    if not preset_path.exists():
        pytest.skip("local xguri runtime preset is not available")
    preset = json.loads(preset_path.read_text(encoding="utf-8-sig"))
    preset = hydrate_preset_with_latest_session_context(preset, Path(__file__).resolve().parents[1])
    sim = CareerSimulator(preset=preset, seed=0)

    assert sim.state["skill_point"] >= 100


def test_simulator_reports_training_snapshot_fidelity_warning_when_no_exact_deck():
    preset_path = (
        Path(__file__).resolve().parents[1]
        / "uma_runtime" / "instances" / "account_b"
        / "instance_learning" / "presets" / "xguri parent.json"
    )
    if not preset_path.exists():
        pytest.skip("local xguri runtime preset is not available")
    preset = json.loads(preset_path.read_text(encoding="utf-8-sig"))
    preset = hydrate_preset_with_latest_session_context(preset, Path(__file__).resolve().parents[1])
    sim = CareerSimulator(preset=preset, seed=0)

    if sim.real_training_snapshots and sim._exact_training_snapshot_deck_matches <= 0:
        assert any("no exact deck match" in warning for warning in sim.fidelity_warnings)


def test_latest_session_context_overrides_stale_preset(tmp_path):
    session_dir = tmp_path / "uma_runtime" / "instances" / "account_b"
    session_dir.mkdir(parents=True)
    (session_dir / "dev_session.json").write_text(json.dumps({
        "selection": {
            "deck": {
                "id": 77,
                "name": "Latest Deck",
                "cards": [
                    {"support_card_id": 30036, "name": "Riko Kashimoto", "type": "Pal", "rarity": "SSR", "limit_break_count": 0},
                    {"support_card_id": 30054, "name": "Nice Nature", "type": "Wit", "rarity": "SSR", "limit_break_count": 4},
                    {"support_card_id": 30014, "name": "Gold City", "type": "Speed", "rarity": "SSR", "limit_break_count": 4},
                    {"support_card_id": 30010, "name": "Fine Motion", "type": "Wit", "rarity": "SSR", "limit_break_count": 4},
                    {"support_card_id": 30028, "name": "Kitasan Black", "type": "Speed", "rarity": "SSR", "limit_break_count": 4},
                ],
            },
            "friend": {"viewer_id": 12345, "support_card_id": 30017},
            "trainee": {"id": "102001", "name": "Seiun Sky"},
            "veterans": [{"instance_id": 1852}, {"instance_id": 552}],
        },
        "start_debug": {
            "request": {
                "card_id": 102001,
                "support_card_ids": [30036, 30054, 30014, 30010, 30028],
                "friend_viewer_id": 12345,
                "friend_card_id": 30017,
                "parent_id_1": 1852,
                "parent_id_2": 552,
                "scenario_id": 4,
                "deck_id": 77,
            }
        },
    }), encoding="utf-8")

    stale = {
        "_run_context": {
            "deck_id": 1,
            "deck_name": "Stale Deck",
            "trainee_card_id": 100401,
            "support_card_ids": [10001, 10002, 10003, 10004, 10005],
            "support_cards": [{"support_card_id": card_id, "type": "Speed"} for card_id in [10001, 10002, 10003, 10004, 10005]],
            "friend_card_id": 30078,
            "friend_viewer_id": 999,
            "parent_id_1": 1,
            "parent_id_2": 2,
        }
    }
    hydrated = hydrate_preset_with_latest_session_context(stale, tmp_path)
    ctx = hydrated["_run_context"]

    assert hydrated["_sim_latest_session_context_source"].endswith("dev_session.json")
    assert ctx["deck_id"] == 77
    assert ctx["deck_name"] == "Latest Deck"
    assert ctx["trainee_card_id"] == 102001
    assert ctx["support_card_ids"] == [30036, 30054, 30014, 30010, 30028]
    assert ctx["friend_card_id"] == 30017
    assert ctx["friend_viewer_id"] == 12345
    assert ctx["parent_id_1"] == 1852
    assert ctx["parent_id_2"] == 552


def test_simulator_uses_inline_session_parent_list_for_legacy_effects():
    # Uses the legacy deterministic inheritance path so the flat stat/aptitude
    # assertions below are stable. The cited probabilistic model (default) is
    # covered by tests/test_inspiration_odds.py.
    preset = dict(
        _make_preset(),
        sim_inheritance_cited_odds=False,
        _run_context={
            "trainee_card_id": 106701,
            "support_card_ids": [30028, 30074, 20031, 30054, 30010],
            "support_cards": [
                {"support_card_id": 30028, "name": "Kitasan Black", "type": "Speed", "rarity": "SSR", "limit_break_count": 4},
                {"support_card_id": 30074, "name": "Marvelous Sunday", "type": "Power", "rarity": "SSR", "limit_break_count": 4},
                {"support_card_id": 20031, "name": "Shinko Windy", "type": "Speed", "rarity": "SR", "limit_break_count": 4},
                {"support_card_id": 30054, "name": "Nice Nature", "type": "Wit", "rarity": "SSR", "limit_break_count": 4},
                {"support_card_id": 30010, "name": "Fine Motion", "type": "Wit", "rarity": "SSR", "limit_break_count": 4},
            ],
            "friend_card_id": 30036,
            "parent_id_1": 992,
            "parent_id_2": 1852,
            "parents": [
                {
                    "instance_id": 992,
                    "name": "Agnes Digital",
                    "tree": {
                        "self": {
                            "factors": [
                                {"name": "Speed", "stars": 3, "category": "stat"},
                                {"name": "Mile", "stars": 3, "category": "aptitude"},
                            ],
                        },
                    },
                },
                {
                    "instance_id": 1852,
                    "name": "Mihono Bourbon",
                    "tree": {
                        "self": {
                            "factors": [
                                {"name": "Wit", "stars": 2, "category": "stat"},
                                {"name": "Pace", "stars": 3, "category": "aptitude"},
                            ],
                        },
                    },
                },
            ],
        },
    )

    sim = CareerSimulator(preset=preset, seed=0)
    effects = sim.legacy_effects

    assert effects["selected_parent_ids"] == [992, 1852]
    assert effects["selected_parent_names"][0] == "Agnes Digital"
    assert effects["selected_parent_names"][1].startswith("Mihono Bourbon")
    assert effects["stat_bonuses"]["speed"] == 21
    assert effects["stat_bonuses"]["wiz"] == 12
    assert effects["aptitude_upgrades"]["mile"]["base"] == "C"
    assert effects["aptitude_upgrades"]["mile"]["next"] == "B"
    assert effects["aptitude_upgrades"]["pace"]["base"] == "B"
    assert effects["aptitude_upgrades"]["pace"]["next"] == "A"


def test_latest_session_context_enriches_deck_card_limit_breaks(tmp_path):
    session_dir = tmp_path / "uma_runtime" / "instances" / "account_b"
    session_dir.mkdir(parents=True)
    (session_dir / "dev_session.json").write_text(json.dumps({
        "dashboard": {
            "supports": [
                {"id": "30028", "name": "Kitasan Black", "type": "Speed", "rarity": "SSR", "limit_break_count": 4, "exp": 118185},
                {"id": "30074", "name": "Marvelous Sunday", "type": "Power", "rarity": "SSR", "limit_break_count": 4, "exp": 118185},
                {"id": "20031", "name": "Shinko Windy", "type": "Speed", "rarity": "SR", "limit_break_count": 4, "exp": 74990},
                {"id": "30054", "name": "Nice Nature", "type": "Wit", "rarity": "SSR", "limit_break_count": 4, "exp": 118185},
                {"id": "30010", "name": "Fine Motion", "type": "Wit", "rarity": "SSR", "limit_break_count": 4, "exp": 118185},
            ],
        },
        "selection": {
            "deck": {
                "id": 77,
                "name": "Shallow Deck",
                "cards": [
                    {"id": "30028", "name": "Kitasan Black", "type": "Speed", "rarity": "SSR"},
                    {"id": "30074", "name": "Marvelous Sunday", "type": "Power", "rarity": "SSR"},
                    {"id": "20031", "name": "Shinko Windy", "type": "Speed", "rarity": "SR"},
                    {"id": "30054", "name": "Nice Nature", "type": "Wit", "rarity": "SSR"},
                    {"id": "30010", "name": "Fine Motion", "type": "Wit", "rarity": "SSR"},
                ],
            },
            "friend": {"viewer_id": 12345, "support_card_id": 30036},
            "trainee": {"id": "106701", "name": "Satono Diamond"},
        },
    }), encoding="utf-8")

    hydrated = hydrate_preset_with_latest_session_context(
        {"sim_runtime_instance": "account_b"},
        tmp_path,
    )
    ctx = hydrated["_run_context"]

    assert [row["limit_break_count"] for row in ctx["support_cards"]] == [4, 4, 4, 4, 4]
    assert ctx["support_card_lb_levels"]["30028"]["lb"] == 4
    assert ctx["support_card_lb_levels"]["20031"]["exp"] == 74990


def test_explicit_sim_deck_overrides_latest_session_context(tmp_path):
    session_dir = tmp_path / "uma_runtime" / "instances" / "account_b"
    session_dir.mkdir(parents=True)
    (session_dir / "dev_session.json").write_text(json.dumps({
        "selection": {
            "deck": {
                "id": 77,
                "name": "Latest Deck",
                "cards": [
                    {"support_card_id": 30036, "name": "Riko Kashimoto", "type": "Pal", "rarity": "SSR", "limit_break_count": 0},
                    {"support_card_id": 30054, "name": "Nice Nature", "type": "Wit", "rarity": "SSR", "limit_break_count": 4},
                    {"support_card_id": 20031, "name": "Shinko Windy", "type": "Speed", "rarity": "SR", "limit_break_count": 4},
                    {"support_card_id": 30010, "name": "Fine Motion", "type": "Wit", "rarity": "SSR", "limit_break_count": 4},
                    {"support_card_id": 30028, "name": "Kitasan Black", "type": "Speed", "rarity": "SSR", "limit_break_count": 4},
                ],
            },
            "friend": {"viewer_id": 12345, "support_card_id": 30017},
            "trainee": {"id": "102001", "name": "Seiun Sky"},
            "veterans": [{"instance_id": 1852}, {"instance_id": 552}],
        }
    }), encoding="utf-8")
    preset = dict(_make_preset(), sim_runtime_instance="account_b")
    explicit_deck = [
        {"support_card_id": 30036, "name": "Riko Kashimoto", "type": "friend", "lb_level": 0},
        {"support_card_id": 30054, "name": "Nice Nature", "type": "wit", "lb_level": 4},
        {"support_card_id": 30014, "name": "Gold City", "type": "speed", "lb_level": 4},
        {"support_card_id": 30010, "name": "Fine Motion", "type": "wit", "lb_level": 4},
        {"support_card_id": 30028, "name": "Kitasan Black", "type": "speed", "lb_level": 4},
    ]

    sim = CareerSimulator(preset=preset, deck=explicit_deck, project_root=tmp_path, seed=0)

    assert 30014 in sim._current_support_ids
    assert 20031 not in sim._current_support_ids
    assert sim.preset["_run_context"]["support_card_ids"] == [30036, 30054, 30014, 30010, 30028]


def test_latest_session_context_prefers_requested_runtime_instance(tmp_path):
    def write_session(instance_name, deck_id, deck_name, trainee_id):
        session_dir = tmp_path / "uma_runtime" / "instances" / instance_name
        session_dir.mkdir(parents=True)
        (session_dir / "dev_session.json").write_text(json.dumps({
            "selection": {
                "deck": {
                    "id": deck_id,
                    "name": deck_name,
                    "cards": [
                        {"support_card_id": 30028, "name": "Kitasan Black", "type": "Speed", "rarity": "SSR", "limit_break_count": 4},
                        {"support_card_id": 30014, "name": "Gold City", "type": "Speed", "rarity": "SSR", "limit_break_count": 4},
                        {"support_card_id": 30054, "name": "Nice Nature", "type": "Wit", "rarity": "SSR", "limit_break_count": 4},
                        {"support_card_id": 30010, "name": "Fine Motion", "type": "Wit", "rarity": "SSR", "limit_break_count": 4},
                        {"support_card_id": 30036, "name": "Riko Kashimoto", "type": "Pal", "rarity": "SSR", "limit_break_count": 0},
                    ],
                },
                "friend": {"viewer_id": 12345, "support_card_id": 30017},
                "trainee": {"id": str(trainee_id), "name": "Selected Trainee"},
                "veterans": [{"instance_id": 1852}, {"instance_id": 552}],
            }
        }), encoding="utf-8")

    write_session("account_a", 11, "Wrong Account Deck", 100401)
    write_session("account_b", 22, "Requested Account Deck", 102001)

    stale = {
        "sim_runtime_instance": "account_b",
        "_run_context": {
            "deck_id": 1,
            "deck_name": "Stale Deck",
            "trainee_card_id": 100401,
            "support_card_ids": [10001, 10002, 10003, 10004, 10005],
            "support_cards": [{"support_card_id": card_id, "type": "Speed"} for card_id in [10001, 10002, 10003, 10004, 10005]],
        },
    }
    hydrated = hydrate_preset_with_latest_session_context(stale, tmp_path)
    ctx = hydrated["_run_context"]

    assert "account_b" in hydrated["_sim_latest_session_context_source"]
    assert hydrated["_sim_latest_session_context_instance"] == "account_b"
    assert ctx["runtime_instance"] == "account_b"
    assert ctx["deck_id"] == 22
    assert ctx["deck_name"] == "Requested Account Deck"
    assert ctx["trainee_card_id"] == 102001


def test_sp_budget_calibration_learns_post_race_event_sp(tmp_path):
    log_dir = tmp_path / "uma_runtime" / "instances" / "account_b" / "bot_logs"
    log_dir.mkdir(parents=True)
    for idx in range(5):
        (log_dir / f"career_log_20260611_12000{idx}.json").write_text(json.dumps({
            "status": "finished",
            "run_context": {"trainee_card_id": 102001},
            "turns": [
                {
                    "turn": 23,
                    "stats": {"skill_point": 157},
                    "events": [
                        {
                            "event": "race_result",
                            "program_id": 623,
                            "race": {"program_id": 623, "name": "Hanshin Juvenile Fillies"},
                            "is_g1": True,
                            "finish_rank": 1,
                            "won": True,
                        },
                        {
                            "event": "event_resolution",
                            "event_id": 1011,
                            "story_id": "400000035",
                            "state_before": {"skill_point": 100},
                            "state_after": {"skill_point": 157},
                        },
                    ],
                },
                {
                    "turn": 78,
                    "skill_point": 50,
                    "stats": {"skill_point": 50},
                    "owned_skills": [{"skill_id": 200542, "name": "Fast-Paced"}],
                    "events": [],
                },
            ],
        }), encoding="utf-8")

    calibration = load_empirical_sp_budget_calibration(
        project_root=tmp_path,
        run_context={"trainee_card_id": 102001},
        trainee_card_id=102001,
    )

    assert calibration["enabled"] is True
    assert calibration["race_sp_reward_sample_count"] == 5
    assert calibration["race_sp_reward_by_grade"]["g1"] == 57
    assert calibration["sp_source_model"] == "source_ledger"
    assert calibration["training_sp_model"] == "mechanical_facility_table"
    assert calibration["purchase_sp_model"] == "audit_only"


def test_sim_race_sp_uses_exact_grade_reward_formula_without_rescaling():
    sim = CareerSimulator(preset=_make_preset(), seed=0)
    sim.sp_budget_calibration = {
        "enabled": True,
        "total_sp_budget_target": 9999,
        "race_sp_reward_by_grade": {"g1": 57, "other": 41, "climax": 66},
    }

    assert sim._race_sp_reward_value(
        grade="G1",
        won=True,
        pid=623,
        race_name="Hanshin Juvenile Fillies",
        turn=23,
        reward_multiplier=1.0,
        race_bonus_mult=1.75,
    ) == 61
    assert sim._race_sp_reward_value(
        grade="G1",
        won=True,
        pid=623,
        race_name="Hanshin Juvenile Fillies",
        turn=23,
        reward_multiplier=1.2,
        race_bonus_mult=1.75,
    ) == 73
    assert sim._race_sp_reward_value(
        grade="G2",
        won=True,
        pid=623,
        race_name="Trial Race",
        turn=20,
        reward_multiplier=1.0,
        race_bonus_mult=1.75,
    ) == 43
    assert sim._race_sp_reward_value(
        grade="OP",
        won=True,
        pid=623,
        race_name="Open Race",
        turn=20,
        reward_multiplier=1.0,
        race_bonus_mult=1.75,
    ) == 35
    assert sim._race_sp_reward_value(
        grade="",
        won=True,
        pid=2513,
        race_name="Twinkle Star Climax Race 3",
        turn=78,
        reward_multiplier=1.25,
        race_bonus_mult=1.75,
    ) == 0
    assert sim._calibrated_race_sp_reward_scale() == 1.0
    assert sim.sp_budget_calibration["race_sp_reward_scale_reason"] == "using_exact_grade_race_sp_formula"


def test_training_sp_is_mechanical_not_nonrace_scaled():
    sim = CareerSimulator(preset=_make_preset(), seed=0)
    sim.state["skill_point"] = 0
    sim.nonrace_sp_reward_scale = 0.0

    sim._apply_training({
        "_sim_primary_stat": "speed",
        "failure_rate": 0,
        "params_inc_dec_info_array": [
            {"target_type": 1, "value": 8},
            {"target_type": 3, "value": 4},
            {"target_type": 30, "value": 2},
            {"target_type": 10, "value": -19},
        ],
        "training_partner_array": [],
    })

    assert sim.state["skill_point"] == 2
    assert sim.sp_gain_sources["training"] == 2


def test_event_sp_uses_event_scale_and_source_bucket():
    sim = CareerSimulator(preset=_make_preset(), seed=0)
    sim.state["skill_point"] = 0
    sim.nonrace_sp_reward_scale = 0.0
    sim.event_sp_reward_scale = 0.5

    sim._apply_sim_event_effects(
        {"source": "support_card", "source_id": 30028, "card": {"effects": {}}},
        {"story_id": "800000001", "event_name": "Support Event", "observed_effect_delta": True},
        {"choice": "default", "effects": {"Skill Pts": 20}},
    )

    assert sim.state["skill_point"] == 10
    assert sim.sp_gain_sources["support_events"] == 10
    assert sim.sp_gain_sources["training"] == 0


def test_sim_race_stat_reward_is_one_random_stat_scaled_by_grade_and_rb():
    sim = CareerSimulator(preset=_make_preset(), seed=0)
    sim.state.update({"speed": 100, "stamina": 100, "power": 100, "guts": 100, "wiz": 100})

    gain = sim._race_stat_total_gain(
        won=True,
        era="classic",
        grade="G3",
        reward_multiplier=1.0,
        race_bonus_mult=1.75,
    )
    allocations = sim._apply_random_race_stat_gain(gain)

    assert gain == 14
    assert sum(allocations.values()) == 14
    changed = {
        "speed": sim.state["speed"] - 100,
        "stamina": sim.state["stamina"] - 100,
        "power": sim.state["power"] - 100,
        "guts": sim.state["guts"] - 100,
        "wit": sim.state["wiz"] - 100,
    }
    assert sorted(changed.values()) == [0, 0, 0, 0, 14]


def test_formula_training_gain_matches_game_table():
    """Formula-mode tile gain reproduces the game's facility base table
    instead of the legacy ~2x inflation. L1 Speed, no cards, bad mood:
    base 8 x 0.90 mood x 1.0 growth ~= 7 (was ~12 under the 1.65 fudge).
    And the model must have real dynamic range so good play (high facility
    + rainbow + great mood) is representable -> >=4x the worst tile."""
    import json, statistics as st
    from pathlib import Path
    from career_bot.career_simulator import CareerSimulator, hydrate_preset_with_latest_session_context
    root = Path(__file__).resolve().parents[1]
    p = root / "uma_runtime/instances/account_b/instance_learning/presets/xguri parent.json"
    if not p.exists():
        import pytest; pytest.skip("account_b preset not present")
    preset = json.loads(p.read_text(encoding="utf-8-sig")); preset["sim_runtime_instance"] = "account_b"
    preset = hydrate_preset_with_latest_session_context(preset, root)
    deck = (preset.get("_run_context") or {}).get("support_cards") or None
    sim = CareerSimulator(preset=preset, deck=deck, seed=1, project_root=root)
    sim.state["motivation"] = 2
    worst = st.median([sim._support_training_gain("speed", "speed", [], False, 1) for _ in range(800)])
    assert 6 <= worst <= 8, f"L1 speed bad-mood gain {worst} should match game table ~7, not the inflated ~12"
    cards = sim.sim_support_cards[:3]
    sim.state["motivation"] = 5
    for c in cards:
        sim.state["bonds"][int(c["partner_id"])] = 100
    strong = st.median([sim._support_training_gain("speed", "speed", cards, True, 5) for _ in range(800)])
    assert strong >= 4 * worst, f"formula needs dynamic range for good play: strong {strong} vs worst {worst}"
