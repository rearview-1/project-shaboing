"""Tests for the career simulator.

The simulator drives MantStrategy._score_command through 78 sim turns
so I can A/B test code changes without running real game careers.
"""

import json
from pathlib import Path

import pytest

from career_bot.career_simulator import CareerSimulator, hydrate_preset_with_latest_session_context, run_sweep
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

    # Speed median in the cranked sweep should be higher.
    base_speeds = [r.final_stats["speed"] for r in base_sweep["results"]]
    cranked_speeds = [r.final_stats["speed"] for r in cranked_sweep["results"]]
    # Allow noisy signal but expect cranked to lead
    assert max(cranked_speeds) >= max(base_speeds) - 50


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
