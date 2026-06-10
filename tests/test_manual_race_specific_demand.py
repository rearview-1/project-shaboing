"""Tests for per-race manual data lookup + bonus.

Two pieces:
1. `aggregate_race_specific_targets`: per-program_id stat target lookup
   (exact card → cross-trainee fallback).
2. `_manual_race_specific_demand_bonus`: walks upcoming scheduled races
   and pressures training toward stats the user historically had when
   winning that specific race.
"""

from career_bot.manual_race_data import aggregate_race_specific_targets


def _make_data():
    """Minimal manual data fixture covering Kikuka Sho (pid 168) for 3 cards
    and a Mile race (pid 73 Yasuda Kinen) for one. Use this to verify the
    aggregation function preserves per-race signal."""
    return {
        "100601": {
            "168": {
                "wins": 2, "losses": 0,
                "median_winning_stats": {
                    "speed": 639, "stamina": 384, "power": 568,
                    "guts": 344, "wit": 479,
                },
                "median_winning_turn": 44,
                "winning_running_styles": {"1": 2},
            },
            "73": {
                "wins": 2, "losses": 1,
                "median_winning_stats": {
                    "speed": 800, "stamina": 250, "power": 600,
                    "guts": 300, "wit": 450,
                },
                "median_winning_turn": 35,
                "winning_running_styles": {"1": 2},
            },
        },
        "106102": {
            "168": {
                "wins": 5, "losses": 0,
                "median_winning_stats": {
                    "speed": 526, "stamina": 377, "power": 608,
                    "guts": 408, "wit": 525,
                },
                "median_winning_turn": 44,
                "winning_running_styles": {"1": 5},
            },
        },
        "102001": {
            "168": {
                "wins": 1, "losses": 0,
                "median_winning_stats": {
                    "speed": 624, "stamina": 388, "power": 444,
                    "guts": 306, "wit": 878,
                },
                "median_winning_turn": 44,
                "winning_running_styles": {"3": 1},  # late surger
            },
        },
    }


# ============================================================
# aggregate_race_specific_targets tests
# ============================================================


def test_exact_card_match_returns_that_trainees_data():
    data = _make_data()
    result = aggregate_race_specific_targets(
        data, 168, current_trainee_card_id=100601
    )
    assert result["_source"] == "exact"
    assert result["stamina"] == 384  # this trainee's median
    assert result["_win_count"] == 2


def test_cross_trainee_aggregation_when_no_exact_match():
    data = _make_data()
    # Card 99999 has no data — should fall back to cross-trainee
    result = aggregate_race_specific_targets(
        data, 168, current_trainee_card_id=99999
    )
    assert result["_source"] == "cross_trainee"
    # 2 wins at 384 + 5 wins at 377 + 1 win at 388 = 8 wins, median ~377
    assert 370 <= result["stamina"] <= 400
    assert result["_win_count"] == 8


def test_per_race_signal_not_diluted_by_other_races():
    """Verify Kikuka Sho's 380 stamina target isn't mixed with Yasuda Kinen's
    250 stamina target — the aggregation must filter by program_id."""
    data = _make_data()
    kikuka = aggregate_race_specific_targets(data, 168, current_trainee_card_id=99999)
    yasuda = aggregate_race_specific_targets(data, 73, current_trainee_card_id=99999)
    # Only card 100601 has Yasuda data — but we excluded the exact match, so
    # actually 100601 IS the source (we pass 99999 which doesn't equal 100601).
    # Both should be reachable.
    assert kikuka["stamina"] > yasuda["stamina"]


def test_self_excluded_from_cross_trainee_aggregation():
    """When falling back to cross-trainee, the current trainee's own data is
    excluded — otherwise exact-match would already have fired.

    To force the fallback path while still wanting self-exclusion to matter,
    build a trainee that has the race in their data but with 0 wins."""
    data = _make_data()
    # Add a "current trainee" 555555 with 0 wins on Kikuka — no exact match,
    # forcing cross-trainee.
    data["555555"] = {"168": {"wins": 0, "losses": 5,
                              "median_winning_stats": {},
                              "winning_running_styles": {}}}
    result = aggregate_race_specific_targets(
        data, 168, current_trainee_card_id=555555
    )
    # All 3 other cards contribute: 2 + 5 + 1 = 8 wins
    assert result["_source"] == "cross_trainee"
    assert result["_win_count"] == 8


def test_style_filter_restricts_cross_trainee_matches():
    """When current style is late_surger (3), only late_surger wins count.

    With default min_wins=2 and only 1 late_surger win available, the
    aggregation returns empty. Lower min_wins to 1 to verify the filter
    itself works."""
    data = _make_data()
    result = aggregate_race_specific_targets(
        data, 168,
        current_trainee_card_id=99999,
        style="late_surger",
        min_wins=1,
    )
    # Only card 102001 won with late_surger — 1 win, stamina 388
    assert result.get("_source") == "cross_trainee"
    assert result.get("_win_count") == 1
    assert result.get("stamina") == 388

    # And with default min_wins=2, that 1 win isn't enough
    empty = aggregate_race_specific_targets(
        data, 168, current_trainee_card_id=99999, style="late_surger",
    )
    assert empty == {}


def test_below_min_wins_returns_empty():
    data = _make_data()
    # Require min_wins=20, only 8 total wins on Kikuka Sho cross-trainee
    result = aggregate_race_specific_targets(
        data, 168, current_trainee_card_id=99999, min_wins=20
    )
    assert result == {}


def test_recovery_unique_stamina_excluded_when_current_lacks_unique():
    """If a source card has stamina-recovery unique but current trainee
    doesn't, that source's stamina target should be dropped from the
    median (but other stats kept)."""
    data = {
        "104501": {  # Super Creek - in STAMINA_RECOVERY_UNIQUE_CARDS
            "168": {
                "wins": 3, "losses": 0,
                "median_winning_stats": {
                    "speed": 500, "stamina": 200, "power": 600,
                    "guts": 300, "wit": 500,
                },
                "median_winning_turn": 44,
                "winning_running_styles": {"1": 3},
            },
        },
        "100601": {
            "168": {
                "wins": 2, "losses": 0,
                "median_winning_stats": {
                    "speed": 600, "stamina": 400, "power": 500,
                    "guts": 300, "wit": 500,
                },
                "median_winning_turn": 44,
                "winning_running_styles": {"1": 2},
            },
        },
    }
    result = aggregate_race_specific_targets(
        data, 168,
        current_trainee_card_id=99999,
        current_trainee_has_recovery_unique=False,
    )
    # Super Creek's stamina=200 should be excluded
    # Only 100601 contributes: 2 wins at stamina=400
    assert result["stamina"] == 400
    # Other stats should include Super Creek's contribution
    assert result["speed"] != 600  # weighted, not just 100601's value


def test_empty_data_returns_empty():
    assert aggregate_race_specific_targets({}, 168, current_trainee_card_id=100601) == {}
    assert aggregate_race_specific_targets(None, 168) == {}


def test_zero_program_id_returns_empty():
    data = _make_data()
    assert aggregate_race_specific_targets(data, 0, current_trainee_card_id=100601) == {}


# ============================================================
# _manual_race_specific_demand_bonus integration tests
# ============================================================


class _MockRacePlanner:
    def __init__(self, base_dir, scheduled):
        self.base_dir = base_dir
        self._scheduled = scheduled

    def scheduled_entries(self, preset):
        return self._scheduled


def test_demand_bonus_zero_when_no_race_planner(tmp_path):
    from career_bot.scenarios.mant import MantStrategy
    s = MantStrategy(None)
    bonus = s._manual_race_specific_demand_bonus(
        1,  # stamina
        {"turn": 35, "stamina": 200},
        {},
    )
    assert bonus == 0.0


def test_demand_bonus_zero_before_start_turn():
    from career_bot.scenarios.mant import MantStrategy, _CAP_PURSUIT_START_TURN
    s = MantStrategy(_MockRacePlanner("/tmp", []))
    bonus = s._manual_race_specific_demand_bonus(
        1,
        {"turn": _CAP_PURSUIT_START_TURN - 1, "stamina": 100},
        {},
    )
    assert bonus == 0.0


def test_demand_bonus_fires_when_stamina_below_kikuka_target(tmp_path, monkeypatch):
    """End-to-end: bot at T35, Kikuka Sho scheduled at T44, current stamina
    180 vs user's 380 target → meaningful bonus should fire on stamina."""
    import json
    from career_bot.scenarios.mant import MantStrategy

    # Set up manual_race_data on disk that the mant.py code can load
    instance_dir = tmp_path / "uma_runtime" / "instances" / "test_account"
    instance_dir.mkdir(parents=True)
    (instance_dir / "manual_race_data.json").write_text(
        json.dumps({"data": _make_data()}), encoding="utf-8"
    )
    base_dir = tmp_path / "tools"
    base_dir.mkdir()

    planner = _MockRacePlanner(
        str(base_dir),
        [{"turn": 44, "program_id": 168, "name": "Kikuka Sho"}],
    )
    s = MantStrategy(planner)
    chara = {
        "turn": 35, "card_id": 99999,
        "speed": 350, "stamina": 180, "power": 400, "guts": 200, "wiz": 400,
    }
    preset = {
        "_runtime_root": str(tmp_path / "uma_runtime" / "instances" / "test_account"),
        "_run_context": {"trainee_card_id": 99999},
    }
    bonus = s._manual_race_specific_demand_bonus(1, chara, preset)  # idx 1 = stamina
    assert bonus > 0.0, "expected stamina bonus when bot is far below race target"


def test_demand_bonus_zero_for_stat_above_target(tmp_path):
    import json
    from career_bot.scenarios.mant import MantStrategy

    instance_dir = tmp_path / "uma_runtime" / "instances" / "test_account"
    instance_dir.mkdir(parents=True)
    (instance_dir / "manual_race_data.json").write_text(
        json.dumps({"data": _make_data()}), encoding="utf-8"
    )
    planner = _MockRacePlanner(
        str(tmp_path / "tools"),
        [{"turn": 44, "program_id": 168}],
    )
    (tmp_path / "tools").mkdir()
    s = MantStrategy(planner)
    chara = {
        "turn": 35, "card_id": 99999,
        "speed": 350, "stamina": 500, "power": 400, "guts": 200, "wiz": 400,
    }
    preset = {
        "_runtime_root": str(tmp_path / "uma_runtime" / "instances" / "test_account"),
        "_run_context": {"trainee_card_id": 99999},
    }
    bonus = s._manual_race_specific_demand_bonus(1, chara, preset)
    # Stamina at 500 > target 377 → no bonus
    assert bonus == 0.0


def test_demand_bonus_zero_when_race_too_far_out(tmp_path):
    """Race more than 12 turns out doesn't trigger pressure yet."""
    import json
    from career_bot.scenarios.mant import MantStrategy

    instance_dir = tmp_path / "uma_runtime" / "instances" / "test_account"
    instance_dir.mkdir(parents=True)
    (instance_dir / "manual_race_data.json").write_text(
        json.dumps({"data": _make_data()}), encoding="utf-8"
    )
    planner = _MockRacePlanner(
        str(tmp_path / "tools"),
        [{"turn": 60, "program_id": 168}],  # 25 turns out
    )
    (tmp_path / "tools").mkdir()
    s = MantStrategy(planner)
    chara = {
        "turn": 35, "card_id": 99999,
        "speed": 350, "stamina": 100, "power": 400, "guts": 200, "wiz": 400,
    }
    preset = {
        "_runtime_root": str(tmp_path / "uma_runtime" / "instances" / "test_account"),
        "_run_context": {"trainee_card_id": 99999},
    }
    bonus = s._manual_race_specific_demand_bonus(1, chara, preset)
    assert bonus == 0.0


def test_demand_bonus_proximity_scaling(tmp_path):
    """Closer race produces stronger bonus than farther race for same deficit."""
    import json
    from career_bot.scenarios.mant import MantStrategy

    instance_dir = tmp_path / "uma_runtime" / "instances" / "test_account"
    instance_dir.mkdir(parents=True)
    (instance_dir / "manual_race_data.json").write_text(
        json.dumps({"data": _make_data()}), encoding="utf-8"
    )
    (tmp_path / "tools").mkdir()

    # Race 2 turns away
    planner_close = _MockRacePlanner(
        str(tmp_path / "tools"),
        [{"turn": 37, "program_id": 168}],
    )
    # Race 11 turns away
    planner_far = _MockRacePlanner(
        str(tmp_path / "tools"),
        [{"turn": 46, "program_id": 168}],
    )
    chara = {
        "turn": 35, "card_id": 99999,
        "speed": 350, "stamina": 100, "power": 400, "guts": 200, "wiz": 400,
    }
    preset = {
        "_runtime_root": str(tmp_path / "uma_runtime" / "instances" / "test_account"),
        "_run_context": {"trainee_card_id": 99999},
    }

    s_close = MantStrategy(planner_close)
    s_far = MantStrategy(planner_far)
    bonus_close = s_close._manual_race_specific_demand_bonus(1, chara, preset)
    bonus_far = s_far._manual_race_specific_demand_bonus(1, chara, preset)
    assert bonus_close > bonus_far
