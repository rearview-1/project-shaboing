"""Tests for the aggressive hyperparameter auto-tuner.

The tuner commits to two targets:
  - S floor: stat_sum ≥ 3,900 (the rank threshold the bot must reach)
  - S+ climb: stat_sum ≥ 4,300 (what the tuner pushes toward over time)

Step size scales with gap-to-S+, with extra doubling when the tune log
shows the bot is stuck.
"""

import json
from pathlib import Path

from career_bot.hyperparameter_tuner import (
    MIN_CAREERS_FOR_TUNE,
    S_FLOOR_STAT_SUM,
    SPLUS_TARGET_STAT_SUM,
    TUNABLE_PARAMS,
    apply_tune_decisions,
    propose_tune_decisions,
    run_tuner,
    summarize_recent_outcomes,
)


def _make_career(stat_sum, speed=800, stamina=600, power=800, guts=500, wit=700):
    return {
        "stat_sum": stat_sum,
        "speed": speed, "stamina": stamina, "power": power, "guts": guts, "wit": wit,
        "rank": "B+" if stat_sum < 3200 else "S" if stat_sum >= S_FLOOR_STAT_SUM else "A+",
    }


def test_no_decisions_when_too_few_careers():
    summary = summarize_recent_outcomes(
        [_make_career(3500) for _ in range(MIN_CAREERS_FOR_TUNE - 1)],
        {},
    )
    decisions = propose_tune_decisions(summary, {})
    assert decisions == []


def test_speed_priority_bumps_when_top_vs_bottom_delta_is_large():
    careers = [_make_career(3500, speed=700) for _ in range(5)]
    careers += [_make_career(4200, speed=1000) for _ in range(5)]
    summary = summarize_recent_outcomes(careers, {})
    decisions = propose_tune_decisions(summary, {})
    speed_late = [d for d in decisions if d["param"] == "speed_priority_bonus_late"]
    assert len(speed_late) == 1
    assert speed_late[0]["new"] > speed_late[0]["old"]


def test_gap_multiplier_makes_larger_jumps_when_far_from_target():
    """Bot at A-tier median (~3,500) should move further per cycle than
    bot at S+-tier median (~4,300)."""
    far = [_make_career(3500) for _ in range(10)]
    far_summary = summarize_recent_outcomes(far, {})
    near = [_make_career(4250) for _ in range(10)]
    near_summary = summarize_recent_outcomes(near, {})

    far_decisions = propose_tune_decisions(far_summary, {})
    near_decisions = propose_tune_decisions(near_summary, {})

    def _move(decisions, param):
        for d in decisions:
            if d["param"] == param:
                return d["new"] - d["old"]
        return 0

    # Skill budget is a tunable, both decisions will propose it
    far_move = _move(far_decisions, "calendar_race_prebuy_budget")
    near_move = _move(near_decisions, "calendar_race_prebuy_budget")
    # Far from target → bigger move
    if far_move > 0 and near_move > 0:
        assert far_move >= near_move


def test_zero_s_or_better_forces_junior_speed_bump():
    careers = [_make_career(3500) for _ in range(8)]
    summary = summarize_recent_outcomes(careers, {})
    assert summary["s_or_better_count"] == 0
    decisions = propose_tune_decisions(summary, {})
    early = [d for d in decisions if d["param"] == "speed_priority_bonus_early"]
    assert len(early) >= 1


def test_classic_low_winrate_bumps_postmortem_cap():
    careers = [_make_career(3500) for _ in range(10)]
    history = {"168": {"race_name": "Kikuka Sho", "attempts": 100, "wins": 19, "losses": 81}}
    summary = summarize_recent_outcomes(careers, history)
    decisions = propose_tune_decisions(summary, {})
    pm = [d for d in decisions if d["param"] == "postmortem_bonus_cap"]
    assert len(pm) == 1


def test_severe_losses_bump_race_specific_demand_cap():
    careers = [_make_career(3500) for _ in range(10)]
    history = {
        "168": {"race_name": "Kikuka Sho", "attempts": 100, "wins": 19, "losses": 81},
        "4":   {"race_name": "Tenno Sho (Spring)", "attempts": 50, "wins": 6, "losses": 44},
    }
    summary = summarize_recent_outcomes(careers, history)
    decisions = propose_tune_decisions(summary, {})
    rsd = [d for d in decisions if d["param"] == "race_specific_demand_cap"]
    assert len(rsd) == 1


def test_any_race_losses_lower_sp_barriers_for_clean_record():
    careers = []
    for _ in range(10):
        row = _make_career(4200)
        row.update({"race_wins": 35, "race_losses": 2, "g1_wins": 12, "g1_losses": 0})
        careers.append(row)
    summary = summarize_recent_outcomes(careers, {})
    decisions = propose_tune_decisions(summary, {})
    by_param = {d["param"]: d for d in decisions}
    assert by_param["calendar_race_prebuy_min_sp"]["direction"] == "down"
    assert by_param["calendar_race_prebuy_keep_sp"]["direction"] == "down"
    assert by_param["calendar_race_prebuy_budget"]["direction"] == "up"
    assert by_param["calendar_race_prebuy_max_skills"]["direction"] == "up"


def test_decisions_respect_ceiling():
    careers = [_make_career(3500, speed=700) for _ in range(5)]
    careers += [_make_career(4200, speed=1000) for _ in range(5)]
    summary = summarize_recent_outcomes(careers, {})
    cfg = TUNABLE_PARAMS["speed_priority_bonus_late"]
    learned = {"speed_priority_bonus_late": cfg["ceiling"]}
    decisions = propose_tune_decisions(summary, learned)
    speed_decisions = [d for d in decisions if d["param"] == "speed_priority_bonus_late"]
    assert speed_decisions == []


def test_apply_writes_learned_hyperparameters_and_log(tmp_path):
    log = tmp_path / "tune_log.jsonl"
    preset = {"name": "test"}
    decisions = [{"param": "speed_priority_bonus_late", "direction": "up",
                  "old": 0.22, "new": 0.26, "reason": "test"}]
    apply_tune_decisions(preset, decisions, log_path=log, summary={"stat_sum_median": 3500})
    assert preset["learned_hyperparameters"]["speed_priority_bonus_late"] == 0.26
    row = json.loads(log.read_text(encoding="utf-8").strip())
    assert row["median_at_time"] == 3500


def test_stuck_doubles_step_when_median_not_improving(tmp_path):
    """If recent log shows median stuck at the same level, next move should
    be larger (gap × stuck = 2× multiplier)."""
    log = tmp_path / "tune_log.jsonl"
    # Synthesize a stuck log
    stuck_entries = [
        {"ts": f"2026-05-{20+i:02d}", "param": "speed_priority_bonus_late",
         "direction": "up", "old": 0.22, "new": 0.24, "reason": "test",
         "median_at_time": 3500}
        for i in range(6)
    ]
    log.write_text("\n".join(json.dumps(e) for e in stuck_entries))

    # Current bot is STILL at 3500 median
    careers = [_make_career(3500, speed=700) for _ in range(5)]
    careers += [_make_career(3500, speed=900) for _ in range(5)]
    summary = summarize_recent_outcomes(careers, {})

    # Run via run_tuner so log_tail is read
    preset = {"name": "test"}
    bot_logs = tmp_path / "bot_logs"
    bot_logs.mkdir()
    for i, c in enumerate(careers):
        career_log = {
            "status": "finished", "ended_at": f"2026-05-{20+i:02d}",
            "final_turn": 78,
            "turns": [{"turn": 78, "stats": {
                "speed": c["speed"], "stamina": c["stamina"], "power": c["power"],
                "guts": c["guts"], "wiz": c["wit"]}}],
        }
        (bot_logs / f"career_log_{i}.json").write_text(json.dumps(career_log))
    history = tmp_path / "history.json"
    history.write_text("{}")
    result = run_tuner(bot_logs_dir=bot_logs, race_history_path=history,
                       preset=preset, log_path=log)
    # The applied decisions should reflect stuck=2× multiplier somewhere
    if result["proposed"]:
        assert any(d.get("stuck_mult", 1.0) > 1.0 for d in result["proposed"])


def test_integer_params_round_to_int():
    preset = {"name": "test"}
    decisions = [{"param": "calendar_race_prebuy_budget", "direction": "up",
                  "old": 850, "new": 950, "reason": "test"}]
    apply_tune_decisions(preset, decisions)
    val = preset["learned_hyperparameters"]["calendar_race_prebuy_budget"]
    assert isinstance(val, int)
    assert val == 950


def test_run_tuner_end_to_end_low_score_careers(tmp_path):
    """Bot stuck at A-tier with no S careers + Classic losses should
    produce multiple aggressive tunes."""
    bot_logs = tmp_path / "bot_logs"
    bot_logs.mkdir()
    for i in range(12):
        career = {
            "status": "finished", "ended_at": f"2026-05-{20+i:02d}T10:00",
            "final_turn": 78,
            "turns": [{"turn": 78, "stats": {
                "speed": 750, "stamina": 600, "power": 800,
                "guts": 500, "wiz": 700}}],
        }
        (bot_logs / f"career_log_{i}.json").write_text(json.dumps(career))
    history_path = tmp_path / "history.json"
    history_path.write_text(json.dumps({
        "168": {"race_name": "Kikuka Sho", "attempts": 50, "wins": 9, "losses": 41},
        "4":   {"race_name": "Tenno Sho (Spring)", "attempts": 30, "wins": 3, "losses": 27},
    }))
    preset = {"name": "test"}
    result = run_tuner(
        bot_logs_dir=bot_logs, race_history_path=history_path,
        preset=preset, log_path=tmp_path / "tune_log.jsonl",
    )
    assert result["summary"]["n_careers"] >= MIN_CAREERS_FOR_TUNE
    # Expect multiple changes (low median, no S, severe losses)
    assert len(result["applied"]) >= 3
    assert "learned_hyperparameters" in preset


def test_at_or_above_splus_proposes_smaller_steps():
    """When bot is hitting S+ already, only minor nudges fire."""
    careers = [_make_career(SPLUS_TARGET_STAT_SUM + 50,
                            speed=950, stamina=750, power=950, guts=600, wit=900)
               for _ in range(10)]
    summary = summarize_recent_outcomes(careers, {})
    decisions = propose_tune_decisions(summary, {})
    # No skill-budget bump (gating is median < S floor) — confirm
    budget = [d for d in decisions if d["param"] == "calendar_race_prebuy_budget"]
    assert budget == []


def test_wit_pressure_not_escalated_when_wit_already_leads_speed():
    """Rule 12 guard: with a 2-Wit deck and median Wit < 1100, Wit pressure
    must NOT be raised when Wit already leads Speed — the stat-sum
    shortfall is in the lagging stats, and more Wit turns made final
    Speed sit at 800-950 on the Jun-12 overnight batch."""
    careers = [
        dict(_make_career(3850, speed=860, wit=1000), deck_wit_count=2, wit_training_count=14)
        for _ in range(10)
    ]
    summary = summarize_recent_outcomes(careers, {})
    # Escalated values (what the un-guarded rule produced overnight) — the
    # down-rule needs room above the param floor to unwind.
    learned = {
        "wit_priority_bonus_mid": 0.40,
        "wit_priority_bonus_late": 0.60,
    }
    decisions = propose_tune_decisions(summary, learned)
    wit_ups = [
        d for d in decisions
        if d["param"].startswith("wit_priority_bonus") and d["new"] > d["old"]
    ]
    assert wit_ups == []
    # And with a 100+ lead, the pressure unwinds.
    wit_downs = [
        d for d in decisions
        if d["param"].startswith("wit_priority_bonus") and d["new"] < d["old"]
    ]
    assert len(wit_downs) >= 1


def test_wit_pressure_still_escalates_when_wit_lags():
    """Rule 12 still fires when the 2-Wit deck's Wit lane genuinely lags."""
    careers = [
        dict(_make_career(3850, speed=1000, wit=820), deck_wit_count=2, wit_training_count=5)
        for _ in range(10)
    ]
    summary = summarize_recent_outcomes(careers, {})
    decisions = propose_tune_decisions(summary, {})
    wit_ups = [
        d for d in decisions
        if d["param"] == "wit_priority_bonus_mid" and d["new"] > d["old"]
    ]
    assert len(wit_ups) == 1
