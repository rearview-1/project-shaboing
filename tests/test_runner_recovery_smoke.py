import json
import os
import threading
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from career_bot.runner import CareerRunner
from career_bot.report import new_report
from career_bot.scenarios.mant import MantStrategy
from uma_api.client import ApiCallError


BASE_DIR = Path(__file__).resolve().parents[1]


class StaminaRetryPlanner:
    def __init__(self):
        self.calls = 0

    def stamina_rescue_entry(self, state, preset):
        self.calls += 1
        return (
            {"turn": 44, "program_id": 168},
            {
                "race_name": "Kikuka Sho",
                "distance": "Long",
                "style": "front_runner",
                "requirements": {"stamina": 612},
                "stats": {"stamina": 320},
                "stamina_low": True,
            },
        )


class StaminaRetrySkillBuyer:
    def __init__(self, skip):
        self.skip = skip
        self.calls = 0
        self.last_result = {}
        self.attempt_events = []
        self.recover_after_error = False

    def buy_stamina_for_race(self, client, state, preset, stamina_check):
        self.calls += 1
        self.last_result = {"skip": self.skip}
        return state, 0


class CalendarPrebuyPlanner:
    def __init__(self, stamina_low=False):
        self.stamina_low = stamina_low
        self.catalog = SimpleNamespace(by_program_id={
            168: {
                "id": 2171,
                "name": "Kikuka Sho",
                "date": "Classic Year Late Oct",
                "type": "G1",
                "terrain": "Turf",
                "distance": "Long",
                "venue": "Kyoto",
                "turn": 44,
                "program_id": 168,
                "race_instance_id": 101501,
            }
        })
        self.program = {}

    def entry_for_program(self, preset, current_turn, program_id):
        return {
            "program_id": int(program_id or 0),
            "turn": int(current_turn or 0),
            "name": "Kikuka Sho",
            "type": "G1",
            "distance": "Long",
            "style": "",
        }

    def style_resolution_for_entry(self, entry, preset, program_id=None):
        return {"style": "late_surger", "source": "skill_profile_style"}

    def stamina_for_program(self, state, preset, program_id, entry=None):
        return {
            "program_id": int(program_id or 0),
            "race_name": "Kikuka Sho",
            "grade": "G1",
            "distance": "Long",
            "style": (entry or {}).get("style") or "",
            "stamina_low": bool(self.stamina_low),
            "static_stamina_low": bool(self.stamina_low),
            "requirements": {"stamina": 600},
            "stats": {"stamina": 320},
            "raw_stats": {"stamina": 320},
        }


class CalendarPrebuySkillBuyer:
    def __init__(self):
        self.generic_calls = 0
        self.stamina_calls = 0
        self.last_check = None
        self.last_result = {}
        self.attempt_events = []
        self.recover_after_error = False

    def buy_limited_for_race(self, client, state, preset, stamina_check, **_kwargs):
        self.generic_calls += 1
        self.last_check = dict(stamina_check or {})
        self.last_result = {"result": "ok"}
        return state, 1

    def buy_stamina_for_race(self, client, state, preset, stamina_check):
        self.stamina_calls += 1
        self.last_check = dict(stamina_check or {})
        self.last_result = {"result": "ok"}
        return state, 1


class RaceProgressRecoveryClient:
    def __init__(self):
        self.calls = []

    def race_end(self, current_turn):
        self.calls.append(("race_end", current_turn))
        raise Exception("API error 102 on single_mode_free/race_end")

    def race_out(self, current_turn):
        self.calls.append(("race_out", current_turn))
        raise Exception("API error 102 on single_mode_free/race_out")

    def load_career(self):
        self.calls.append(("load_career", 0))
        return {
            "data": {
                "chara_info": {
                    "turn": 25,
                    "playing_state": 1,
                    "skill_point": 330,
                }
            }
        }


class StuckActiveRaceClient(RaceProgressRecoveryClient):
    def load_career(self):
        self.calls.append(("load_career", 0))
        return {
            "data": {
                "chara_info": {
                    "turn": 24,
                    "playing_state": 3,
                    "race_program_id": 168,
                    "skill_point": 330,
                },
                "race_start_info": {"program_id": 168},
            }
        }


class FinalRaceOut102Client(RaceProgressRecoveryClient):
    def load_career(self):
        self.calls.append(("load_career", 0))
        return {
            "data": {
                "chara_info": {
                    "turn": 78,
                    "playing_state": 5,
                    "state": 0,
                    "race_program_id": 2509,
                    "skill_point": 0,
                    "fans": 847925,
                },
                "race_start_info": {"program_id": 2509, "race_instance_id": 920091},
                "race_history": [{"turn": 78, "program_id": 2509, "result_rank": 1}],
            }
        }

    def finish_career(self, current_turn=0, is_force_delete=False):
        self.calls.append(("finish_career", current_turn, is_force_delete))
        return {"data": {"single_mode_finish_common": {}, "chara_info": {"turn": current_turn}}}


class StaleRaceEntryClient:
    def __init__(self):
        self.calls = []

    def race_entry(self, program_id, current_turn):
        self.calls.append(("race_entry", program_id, current_turn))
        return {
            "data": {
                "chara_info": {
                    "turn": current_turn,
                    "playing_state": 2,
                    "state": 2,
                    "race_program_id": program_id,
                    "skill_point": 0,
                },
                "race_start_info": {"program_id": program_id},
            }
        }

    def race_start(self, is_short, current_turn):
        self.calls.append(("race_start", is_short, current_turn))
        raise AssertionError("race_start should not be called for career finish screen")

    def race_out(self, current_turn):
        self.calls.append(("race_out", current_turn))
        raise AssertionError("race_out should not be called for career finish screen")

    def finish_career(self, current_turn=0, is_force_delete=False):
        self.calls.append(("finish_career", current_turn, is_force_delete))
        return {"data": {"single_mode_finish_common": {}, "chara_info": {"turn": current_turn}}}


class RefreshRetryRaceEntryClient:
    def __init__(self):
        self.calls = []
        self.entry_attempts = 0

    def race_entry(self, program_id, current_turn):
        self.calls.append(("race_entry", program_id, current_turn))
        self.entry_attempts += 1
        if self.entry_attempts == 1:
            raise ApiCallError(
                "API error 205 on single_mode_free/race_entry",
                endpoint="single_mode_free/race_entry",
                request_payload={"program_id": program_id, "current_turn": current_turn},
                response_body={"data_headers": {"viewer_id": 162337796827, "result_code": 205}},
                result_code=205,
                response_code=205,
                req_id="refresh-retry-first",
            )
        return {
            "data": {
                "single_mode_finish_common": {},
                "chara_info": {
                    "turn": current_turn,
                    "playing_state": 5,
                    "state": 2,
                    "race_program_id": program_id,
                },
            }
        }

    def load_career(self):
        self.calls.append(("load_career",))
        return {
            "data": {
                "chara_info": {
                    "turn": 16,
                    "playing_state": 1,
                    "state": 0,
                    "fans": 565,
                    "skill_point": 0,
                },
                "home_info": {"race_entry_restriction": 0},
                "race_condition_array": [{"program_id": 629}],
            }
        }

    def finish_career(self, current_turn=0, is_force_delete=False):
        self.calls.append(("finish_career", current_turn, is_force_delete))
        return {"data": {"single_mode_finish_common": {}, "chara_info": {"turn": current_turn}}}


class ExecCommand391ThenRefreshClient:
    error_code = 391

    def __init__(self):
        self.calls = []
        self.exec_attempts = 0

    def exec_command(self, **payload):
        self.calls.append(("exec_command", dict(payload)))
        self.exec_attempts += 1
        if self.exec_attempts == 1:
            raise ApiCallError(
                f"API error {self.error_code} on single_mode_free/exec_command",
                endpoint="single_mode_free/exec_command",
                request_payload=dict(payload),
                response_body={"data_headers": {"viewer_id": 4665295244463, "result_code": self.error_code}},
                result_code=self.error_code,
                response_code=self.error_code,
                req_id=f"exec-{self.error_code}",
            )
        return {
            "data": {
                "chara_info": {
                    "turn": int(payload.get("current_turn") or 0) + 1,
                    "vital": 24,
                    "playing_state": 1,
                    "state": 0,
                },
                "home_info": {"command_info_array": _actionable_home_commands()},
            }
        }

    def load_career(self):
        self.calls.append(("load_career",))
        return {
            "data": {
                "chara_info": {
                    "turn": 52,
                    "vital": 39,
                    "playing_state": 1,
                    "state": 0,
                },
                "home_info": {"command_info_array": _actionable_home_commands()},
            }
        }


class ExecCommand205ThenRefreshClient(ExecCommand391ThenRefreshClient):
    error_code = 205


class CheckEvent205ThenHomeClient:
    def __init__(self):
        self.calls = []

    def check_event(self, **payload):
        self.calls.append(("check_event", dict(payload)))
        raise ApiCallError(
            "API error 205 on single_mode_free/check_event",
            endpoint="single_mode_free/check_event",
            request_payload=dict(payload),
            response_body={"data_headers": {"viewer_id": 4665295244463, "result_code": 205}},
            result_code=205,
            response_code=205,
            req_id="check-event-205",
        )

    def load_career(self):
        self.calls.append(("load_career",))
        return {
            "data": {
                "chara_info": {
                    "turn": 58,
                    "playing_state": 1,
                    "state": 0,
                    "skill_point": 230,
                },
                "home_info": {"command_info_array": _actionable_home_commands()},
            }
        }


class RaceEntryEvent205ThenHomeClient(CheckEvent205ThenHomeClient):
    def race_entry(self, program_id, current_turn):
        self.calls.append(("race_entry", program_id, current_turn))
        return {
            "data": {
                "chara_info": {
                    "turn": current_turn,
                    "playing_state": 2,
                    "state": 0,
                    "race_program_id": program_id,
                    "skill_point": 230,
                },
                "race_start_info": {"program_id": program_id, "is_short": True},
                "unchecked_event_array": [{"event_id": 9001, "chara_id": 1}],
            }
        }

    def race_start(self, is_short, current_turn):
        self.calls.append(("race_start", is_short, current_turn))
        raise AssertionError("race_start should not run after event recovery returns home")


def _actionable_home_commands():
    return [
        {
            "command_type": 1,
            "command_id": 101,
            "command_group_id": 101,
            "is_enable": 1,
            "training_partner_array": [],
            "tips_event_partner_array": [],
            "params_inc_dec_info_array": [
                {"target_type": 1, "value": 12},
                {"target_type": 10, "value": -18},
            ],
            "failure_rate": 0,
            "level": 3,
        },
        {
            "command_type": 7,
            "command_id": 701,
            "command_group_id": 701,
            "is_enable": 1,
            "training_partner_array": [],
            "tips_event_partner_array": [],
            "params_inc_dec_info_array": [],
            "failure_rate": 0,
            "level": 0,
        },
    ]


class ActionableHomeTransitionClient:
    def __init__(self):
        self.calls = []

    def load_career(self):
        self.calls.append(("load_career", 0))
        return {
            "data": {
                "chara_info": {
                    "turn": 48,
                    "playing_state": 5,
                    "state": 2,
                    "race_program_id": 0,
                    "vital": 26,
                    "max_vital": 104,
                    "motivation": 5,
                    "fans": 34054,
                    "speed": 594,
                    "stamina": 486,
                    "power": 651,
                    "guts": 240,
                    "wiz": 376,
                    "skill_point": 580,
                },
                "race_start_info": None,
                "home_info": {
                    "command_info_array": _actionable_home_commands(),
                },
            }
        }


class RunnerLoopModeStateTests(unittest.TestCase):
    def test_calendar_prebuy_skips_generic_buys_when_end_buy_is_active(self):
        runner = CareerRunner(BASE_DIR)
        runner.report = new_report({"name": "test"}, scenario_id=4)
        runner.race_planner = CalendarPrebuyPlanner(stamina_low=False)
        runner.skill_buyer = CalendarPrebuySkillBuyer()

        state = {"data": {"chara_info": {"turn": 44, "skill_point": 1200, "stamina": 500}}}
        preset = {
            "manual_purchase_at_end": True,
            "calendar_race_prebuy_enabled": True,
            "calendar_race_prebuy_min_sp": 80,
            "calendar_race_prebuy_budget": 1800,
            "calendar_race_prebuy_keep_sp": 0,
            "calendar_race_prebuy_max_skills": 10,
            "skill_profile_style": "late_surger",
        }

        runner._maybe_buy_calendar_race_skills(None, state, preset, program_id=168, current_turn=44)

        self.assertEqual(runner.skill_buyer.generic_calls, 0)
        rows = [
            event
            for turn in runner.report.get("turns") or []
            for event in (turn.get("events") or [])
            if event.get("event") == "pre_race_calendar_skill_skip"
        ]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["reason"], "manual_purchase_at_end")
        self.assertEqual(rows[0]["style"], "late_surger")

    def test_calendar_prebuy_can_be_explicitly_allowed_with_end_buy(self):
        runner = CareerRunner(BASE_DIR)
        runner.race_planner = CalendarPrebuyPlanner(stamina_low=False)
        runner.skill_buyer = CalendarPrebuySkillBuyer()

        state = {"data": {"chara_info": {"turn": 44, "skill_point": 1200, "stamina": 500}}}
        preset = {
            "manual_purchase_at_end": True,
            "calendar_race_prebuy_allow_midcareer_with_end_buy": True,
            "calendar_race_prebuy_enabled": True,
            "skill_profile_style": "late_surger",
        }

        runner._maybe_buy_calendar_race_skills(None, state, preset, program_id=168, current_turn=44)

        self.assertEqual(runner.skill_buyer.generic_calls, 1)
        self.assertEqual(runner.skill_buyer.last_check["style"], "late_surger")

    def test_calendar_prebuy_end_buy_still_allows_stamina_rescue_only(self):
        runner = CareerRunner(BASE_DIR)
        runner.report = new_report({"name": "test"}, scenario_id=4)
        runner.race_planner = CalendarPrebuyPlanner(stamina_low=True)
        runner.skill_buyer = CalendarPrebuySkillBuyer()

        state = {"data": {"chara_info": {"turn": 44, "skill_point": 1200, "stamina": 320}}}
        preset = {
            "manual_purchase_at_end": True,
            "calendar_race_prebuy_enabled": True,
            "auto_buy_stamina_skill_for_race": True,
            "skill_profile_style": "late_surger",
        }

        runner._maybe_buy_calendar_race_skills(None, state, preset, program_id=168, current_turn=44)

        self.assertEqual(runner.skill_buyer.stamina_calls, 1)
        self.assertEqual(runner.skill_buyer.generic_calls, 0)
        self.assertEqual(runner.skill_buyer.last_check["style"], "late_surger")

    def test_hot_reload_preserves_transient_loop_mode_flag(self):
        runner = CareerRunner(BASE_DIR)
        runner.status["running"] = True
        runner.status["loop_mode"] = True
        runner._active_preset_name = "xguri parent"
        runner._active_preset = {
            "name": "xguri parent",
            "_loop_mode": True,
            "_run_context": {"started_from_active_career": False},
            "rest_threshold": 48,
        }

        updated = runner.update_active_preset(
            "xguri parent",
            {
                "name": "xguri parent",
                "rest_threshold": 52,
            },
        )

        self.assertTrue(updated)
        self.assertTrue(runner._active_preset.get("_loop_mode"))
        self.assertTrue(runner._loop_mode_active())
        self.assertEqual(runner._active_preset.get("rest_threshold"), 52)

    def test_hot_patch_active_preset_fields_preserves_runtime_context(self):
        runner = CareerRunner(BASE_DIR)
        runner.status["running"] = True
        runner.status["turn"] = 41
        runner._active_preset_name = "xguri parent"
        runner._active_preset = {
            "name": "xguri parent",
            "_run_context": {"support_cards": [1, 2, 3], "friend_card_id": 30036},
            "learned_hyperparameters": {"train_bias": 1.25},
            "skill_profile_style": "front_runner",
            "skill_profile_distance": "mile",
        }

        updated = runner.update_active_preset_fields(
            "xguri parent",
            {
                "skill_profile_style": "late_surger",
                "skill_profile_distance": "medium",
                "learn_skill_list": [{"name": "Groundwork"}],
            },
            reason="save_skill_plan",
        )

        self.assertTrue(updated)
        self.assertEqual(runner._active_preset["skill_profile_style"], "late_surger")
        self.assertEqual(runner._active_preset["skill_profile_distance"], "medium")
        self.assertEqual(runner._active_preset["_run_context"]["friend_card_id"], 30036)
        self.assertEqual(runner._active_preset["learned_hyperparameters"]["train_bias"], 1.25)
        self.assertIn("save_skill_plan", runner.status["last_action"])
        self.assertEqual(runner.status["log"][-1]["action"], "preset_hot_reload")

    def test_loop_mode_active_uses_runner_status_even_if_preset_flag_was_lost(self):
        runner = CareerRunner(BASE_DIR)
        runner.status["loop_mode"] = True

        self.assertTrue(runner._loop_mode_active({}))

    def test_runner_releases_loop_before_async_auto_learning_finishes(self):
        runner = CareerRunner(BASE_DIR)
        preset = {"name": "xguri parent", "scenario_id": 4}
        runner.report = new_report(preset, 4)
        runner.status["running"] = True
        runner._active_preset = preset
        runner._active_preset_name = "xguri parent"
        state = {"data": {"chara_info": {"turn": 78, "skill_point": 0}}}

        class FinishStrategy:
            def next_decision(self, *_args, **_kwargs):
                return SimpleNamespace(action="finish", payload={"current_turn": 78}, reason="done", understanding={})

        learning_running_flag = {"value": None}
        learning_called = threading.Event()

        def fake_finish(_client, current_state, _preset, _strategy, _turn):
            runner._mark(last_action="finish", finished=True, final_fans=123)
            return current_state

        def fake_learning(*_args, **_kwargs):
            learning_running_flag["value"] = runner.snapshot().get("running")
            learning_called.set()
            return {"success": False, "skipped": "missing_samples"}

        with patch.object(runner, "_finish_career", side_effect=fake_finish), patch(
            "career_bot.runner.write_report",
            return_value=str(BASE_DIR / "uma_runtime" / "bot_logs" / "career_log_test.json"),
        ), patch(
            "career_bot.parent_memory.remember_bot_career",
            return_value={},
        ), patch(
            "career_bot.race_postmortem.newest_trace_for_career",
            return_value=None,
        ), patch(
            "career_bot.auto_learning.run_auto_learning",
            side_effect=fake_learning,
        ):
            runner._run(None, preset, state, FinishStrategy(), 1)

        self.assertFalse(runner.snapshot().get("running"))
        self.assertTrue(learning_called.wait(2.0))
        self.assertFalse(learning_running_flag["value"])


def race_end_state(turn, program_id, rank, available_continue_num=5, available_free_continue_num=0):
    return {
        "data": {
            "chara_info": {
                "turn": turn,
                "playing_state": 4,
                "state": 0,
                "race_program_id": program_id,
            },
            "home_info": {
                "available_continue_num": available_continue_num,
                "available_free_continue_num": available_free_continue_num,
            },
            "race_start_info": {"program_id": program_id, "is_short": True},
            "race_reward_info": {"result_rank": rank},
            "race_history": [{"turn": turn, "program_id": program_id, "result_rank": rank}],
        }
    }


class RaceContinueWinClient:
    def __init__(self):
        self.calls = []

    def race_continue(self, current_turn, continue_type):
        self.calls.append(("race_continue", current_turn, continue_type))
        return {
            "data": {
                "chara_info": {"turn": current_turn, "playing_state": 2, "state": 0},
                "race_start_info": {"program_id": 168, "is_short": True},
            }
        }

    def race_start(self, is_short, current_turn):
        self.calls.append(("race_start", is_short, current_turn))
        return {"data": {}}

    def race_end(self, current_turn):
        self.calls.append(("race_end", current_turn))
        return race_end_state(current_turn, 168, rank=1)


class RaceContinueNeverWinClient(RaceContinueWinClient):
    def race_end(self, current_turn):
        self.calls.append(("race_end", current_turn))
        return race_end_state(current_turn, 168, rank=2, available_continue_num=5)


class RaceContinueCaratFallbackClient(RaceContinueWinClient):
    def race_continue(self, current_turn, continue_type):
        self.calls.append(("race_continue", current_turn, continue_type))
        if continue_type == 2:
            raise Exception("no alarm clocks")
        return {
            "data": {
                "chara_info": {"turn": current_turn, "playing_state": 2, "state": 0},
                "race_start_info": {"program_id": 168, "is_short": True},
            }
        }


class RaceContinueCaratExchangeClient(RaceContinueWinClient):
    def __init__(self):
        super().__init__()
        self.coin_info = {"fcoin": 2225, "coin": 40}
        self.item_map = {}
        self.exchanged = False

    def exchange_item(self, exchange_id, count=1, current_num=None, get_list_time=""):
        self.calls.append(("exchange_item", exchange_id, count, current_num, get_list_time))
        self.exchanged = True
        self.coin_info = {"fcoin": 2215, "coin": 40}
        self.item_map[95] = self.item_map.get(95, 0) + 1
        return {
            "data": {
                "coin_info": dict(self.coin_info),
                "reward_summary_info": {"add_item_list": [{"item_id": 95, "number": 1}]},
            }
        }

    def race_continue(self, current_turn, continue_type):
        self.calls.append(("race_continue", current_turn, continue_type))
        if continue_type == 2 and not self.exchanged:
            raise Exception("API error 1801 on single_mode_free/continue")
        return {
            "data": {
                "chara_info": {"turn": current_turn, "playing_state": 2, "state": 0},
                "race_start_info": {"program_id": 168, "is_short": True},
            }
        }


class RaceContinuePostRaceEndRejectClient(RaceContinueWinClient):
    def race_continue(self, current_turn, continue_type):
        self.calls.append(("race_continue", current_turn, continue_type))
        raise Exception("API error 500 on single_mode_free/continue")

    def load_career(self):
        self.calls.append(("load_career",))
        return race_end_state(24, 168, rank=2, available_continue_num=5)


class RaceContinuePreEndProbeClient(RaceContinueWinClient):
    def __init__(self):
        super().__init__()
        self.continue_count = 0

    def race_continue(self, current_turn, continue_type):
        self.calls.append(("race_continue", current_turn, continue_type))
        self.continue_count += 1
        if self.continue_count > 1:
            raise Exception("API error 205 on single_mode_free/continue")
        return {
            "data": {
                "chara_info": {"turn": current_turn, "playing_state": 2, "state": 0, "race_program_id": 168},
                "race_start_info": {"program_id": 168, "is_short": True},
            }
        }

    def load_career(self):
        self.calls.append(("load_career",))
        return {
            "data": {
                "chara_info": {"turn": 24, "playing_state": 3, "state": 0, "race_program_id": 168},
                "race_start_info": {"program_id": 168, "is_short": True},
                "home_info": {"available_continue_num": 4, "available_free_continue_num": 0},
            }
        }

    def race_out(self, current_turn):
        self.calls.append(("race_out", current_turn))
        return {"data": {"chara_info": {"turn": current_turn + 1, "playing_state": 1, "state": 0}}}


class RaceContinuePreEndProbeRejectClient(RaceContinuePreEndProbeClient):
    def race_continue(self, current_turn, continue_type):
        self.calls.append(("race_continue", current_turn, continue_type))
        raise Exception("API error 500 on single_mode_free/continue")

    def race_end(self, current_turn):
        self.calls.append(("race_end", current_turn))
        return race_end_state(current_turn, 168, rank=2, available_continue_num=5)


class RaceContinuePreEndProbeDelayedReadyClient(RaceContinuePreEndProbeClient):
    def race_continue(self, current_turn, continue_type):
        self.calls.append(("race_continue", current_turn, continue_type))
        self.continue_count += 1
        if self.continue_count <= 2:
            raise Exception("API error 205 on single_mode_free/continue")
        if self.continue_count > 3:
            raise Exception("API error 205 on single_mode_free/continue")
        return {
            "data": {
                "chara_info": {"turn": current_turn, "playing_state": 2, "state": 0, "race_program_id": 168},
                "race_start_info": {"program_id": 168, "is_short": True},
            }
        }


class RaceContinuePreEndProbeAlwaysLoseClient(RaceContinuePreEndProbeClient):
    def race_continue(self, current_turn, continue_type):
        self.calls.append(("race_continue", current_turn, continue_type))
        self.continue_count += 1
        return {
            "data": {
                "chara_info": {"turn": current_turn, "playing_state": 2, "state": 0, "race_program_id": 168},
                "race_start_info": {"program_id": 168, "is_short": True},
            }
        }

    def race_end(self, current_turn):
        self.calls.append(("race_end", current_turn))
        return race_end_state(current_turn, 168, rank=2, available_continue_num=2)


class RaceContinueReplayStartRejectedClient(RaceContinuePreEndProbeClient):
    def race_start(self, is_short, current_turn):
        self.calls.append(("race_start", is_short, current_turn))
        raise Exception("API error 2502 on single_mode_free/race_start")

    def load_career(self):
        self.calls.append(("load_career",))
        return {
            "data": {
                "chara_info": {"turn": 24, "playing_state": 2, "state": 0, "race_program_id": 168},
                "race_start_info": {"program_id": 168, "is_short": True},
                "home_info": {"available_continue_num": 4, "available_free_continue_num": 0},
            }
        }

    def race_end(self, current_turn):
        self.calls.append(("race_end", current_turn))
        raise AssertionError("race_end should not be called after replay race_start 2502")

    def race_out(self, current_turn):
        self.calls.append(("race_out", current_turn))
        raise AssertionError("race_out should not be called without a race result")


class RaceProgressTryAgainClient(RaceContinueWinClient):
    def __init__(self):
        super().__init__()
        self.race_end_count = 0

    def race_end(self, current_turn):
        self.calls.append(("race_end", current_turn))
        self.race_end_count += 1
        if self.race_end_count == 1:
            return race_end_state(current_turn, 168, rank=2, available_continue_num=5)
        return race_end_state(current_turn, 168, rank=1)

    def race_out(self, current_turn):
        self.calls.append(("race_out", current_turn))
        return {"data": {"chara_info": {"turn": current_turn + 1, "playing_state": 1, "state": 0}}}


class StaleFinalSkillClient:
    def __init__(self):
        self.calls = []

    def gain_skills(self, payload, turn, **kwargs):
        self.calls.append(("gain_skills", tuple(row["skill_id"] for row in payload), turn))
        # Simulate the server accepting the purchase but returning the stale finish-screen
        # chara payload. The runner should reload before deciding whether to retry.
        return {
            "data": {
                "single_mode_finish_common": {},
                "chara_info": {
                    "turn": turn,
                    "state": 3,
                    "playing_state": 5,
                    "skill_point": 1000,
                    "skill_array": [],
                    "skill_tips_array": [{"group_id": 20160, "rarity": 1, "level": 0}],
                },
            }
        }

    def load_career(self):
        self.calls.append(("load_career",))
        return {
            "data": {
                "single_mode_finish_common": {},
                "chara_info": {
                    "turn": 78,
                    "state": 3,
                    "playing_state": 5,
                    "skill_point": 840,
                    "skill_array": [{"skill_id": 201601, "level": 1}],
                    "skill_tips_array": [],
                },
            }
        }

    def finish_career(self, current_turn=0, is_force_delete=False):
        self.calls.append(("finish_career", current_turn, is_force_delete))
        return {"data": {"single_mode_finish_common": {}, "chara_info": {"turn": current_turn}}}


class StaleFinalSkillTruncatedReloadClient(StaleFinalSkillClient):
    def load_career(self):
        self.calls.append(("load_career",))
        return {
            "data": {
                "single_mode_finish_common": {},
                "chara_info": {
                    "turn": 78,
                    "state": 3,
                    "playing_state": 5,
                    "skill_point": 840,
                    "skill_array": [],
                    "skill_tips_array": [{"group_id": 20160, "rarity": 1, "level": 0}],
                },
            }
        }


class EarlyCompleteCareerClient:
    def __init__(self):
        self.calls = []

    def finish_career(self, current_turn=0, is_force_delete=False):
        self.calls.append(("finish_career", current_turn, is_force_delete))
        return {"data": {"single_mode_finish_common": {}, "chara_info": {"turn": current_turn}}}

    def call(self, endpoint, payload=None, **kwargs):
        self.calls.append(("call", endpoint, dict(payload or {})))
        return {"data": {}}

    def read_info(self):
        self.calls.append(("read_info",))
        return {"data": {}}


class RunnerRecoverySmokeTests(unittest.TestCase):
    def test_exec_command_391_refreshes_state_and_retries_instead_of_crashing(self):
        runner = CareerRunner(BASE_DIR)
        client = ExecCommand391ThenRefreshClient()
        payload = {
            "command_type": 1,
            "command_id": 105,
            "command_group_id": 0,
            "select_id": 0,
            "current_turn": 52,
            "current_vital": 41,
        }
        state = {
            "data": {
                "chara_info": {"turn": 52, "vital": 41, "playing_state": 1, "state": 0},
                "home_info": {"command_info_array": _actionable_home_commands()},
            }
        }

        result, executed = runner._exec_command_with_recovery(
            client,
            MantStrategy(),
            state,
            payload,
            (state.get("data") or {}).get("chara_info") or {},
        )

        self.assertTrue(executed)
        self.assertEqual((result.get("data") or {}).get("chara_info", {}).get("turn"), 53)
        self.assertEqual(client.calls[0][0], "exec_command")
        self.assertEqual(client.calls[1], ("load_career",))
        self.assertEqual(client.calls[2][0], "exec_command")
        self.assertEqual(client.calls[2][1]["current_turn"], 52)
        self.assertEqual(client.calls[2][1]["current_vital"], 39)

    def test_exec_command_205_refreshes_state_and_retries_instead_of_crashing(self):
        runner = CareerRunner(BASE_DIR)
        client = ExecCommand205ThenRefreshClient()
        payload = {
            "command_type": 1,
            "command_id": 105,
            "command_group_id": 0,
            "select_id": 0,
            "current_turn": 52,
            "current_vital": 41,
        }
        state = {
            "data": {
                "chara_info": {"turn": 52, "vital": 41, "playing_state": 1, "state": 0},
                "home_info": {"command_info_array": _actionable_home_commands()},
            }
        }

        result, executed = runner._exec_command_with_recovery(
            client,
            MantStrategy(),
            state,
            payload,
            (state.get("data") or {}).get("chara_info") or {},
        )

        self.assertTrue(executed)
        self.assertEqual((result.get("data") or {}).get("chara_info", {}).get("turn"), 53)
        self.assertEqual(client.calls[1], ("load_career",))
        self.assertEqual(client.calls[2][0], "exec_command")
        self.assertEqual(client.calls[2][1]["current_vital"], 39)

    def test_check_event_205_refreshes_state_instead_of_crashing(self):
        runner = CareerRunner(BASE_DIR)
        client = CheckEvent205ThenHomeClient()
        state = {
            "data": {
                "chara_info": {"turn": 57, "playing_state": 2, "state": 0},
                "unchecked_event_array": [{"event_id": 9001, "chara_id": 1}],
            }
        }

        result = runner._drain_events(client, MantStrategy(), state)

        self.assertEqual((result.get("data") or {}).get("chara_info", {}).get("turn"), 58)
        self.assertEqual((result.get("data") or {}).get("chara_info", {}).get("playing_state"), 1)
        self.assertEqual(client.calls[0][0], "check_event")
        self.assertEqual(client.calls[1], ("load_career",))

    def test_race_entry_check_event_205_home_recovery_does_not_start_race(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceEntryEvent205ThenHomeClient()

        result = runner._race(
            client,
            {"data": {"chara_info": {"turn": 57, "playing_state": 1, "state": 0}}},
            {"scenario_id": 1},
            {"program_id": 168, "current_turn": 57, "_strategy": MantStrategy()},
        )

        self.assertEqual((result.get("data") or {}).get("chara_info", {}).get("playing_state"), 1)
        self.assertEqual(
            client.calls,
            [
                ("race_entry", 168, 57),
                ("check_event", {"event_id": 9001, "chara_id": 1, "choice_number": 0, "current_turn": 57}),
                ("load_career",),
            ],
        )

    def test_strategy_settles_midcareer_playing_state_five_even_when_home_board_exists(self):
        strategy = MantStrategy()
        decision = strategy.next_decision(
            {
                "data": {
                    "chara_info": {
                        "turn": 48,
                        "playing_state": 5,
                        "state": 2,
                        "race_program_id": 0,
                        "vital": 75,
                        "max_vital": 100,
                        "motivation": 5,
                        "speed": 633,
                        "stamina": 453,
                        "power": 320,
                        "guts": 296,
                        "wiz": 472,
                    },
                    "race_start_info": None,
                    "home_info": {
                        "command_info_array": [
                            {
                                "command_type": 1,
                                "command_id": 101,
                                "is_enable": 1,
                                "training_partner_array": [],
                                "tips_event_partner_array": [],
                                "params_inc_dec_info_array": [
                                    {"target_type": 1, "value": 17},
                                    {"target_type": 10, "value": -20},
                                ],
                                "failure_rate": 0,
                                "level": 2,
                            },
                            {
                                "command_type": 7,
                                "command_id": 701,
                                "is_enable": 1,
                                "training_partner_array": [],
                                "tips_event_partner_array": [],
                                "params_inc_dec_info_array": [],
                                "failure_rate": 0,
                                "level": 0,
                            },
                        ]
                    },
                    "race_condition_array": [{"program_id": 168}],
                }
            },
            {},
        )

        self.assertEqual(decision.action, "settle_state")
        self.assertEqual(decision.reason, "post-action state without active race")

    def test_strategy_treats_late_post_action_state_as_complete_career_when_home_board_exists(self):
        strategy = MantStrategy()
        decision = strategy.next_decision(
            {
                "data": {
                    "chara_info": {
                        "turn": 78,
                        "playing_state": 5,
                        "state": 2,
                        "race_program_id": 0,
                        "vital": 75,
                        "max_vital": 100,
                        "motivation": 5,
                        "speed": 633,
                        "stamina": 453,
                        "power": 320,
                        "guts": 296,
                        "wiz": 472,
                    },
                    "race_start_info": None,
                    "home_info": {"command_info_array": _actionable_home_commands()},
                }
            },
            {},
        )

        self.assertEqual(decision.action, "finish")
        self.assertEqual(decision.reason, "Complete Career screen")

    def test_strategy_maps_active_race_states_to_correct_resume_phase(self):
        strategy = MantStrategy()
        base = {
            "data": {
                "race_start_info": {"program_id": 168},
                "chara_info": {"turn": 24, "race_program_id": 168},
            }
        }

        for playing_state, phase in ((2, "start"), (3, "end"), (4, "end"), (5, "end")):
            base["data"]["chara_info"]["playing_state"] = playing_state
            decision = strategy.next_decision(base, {})
            self.assertEqual(decision.action, "race_progress")
            self.assertEqual(decision.payload["phase"], phase)

    def test_strategy_settles_midcareer_transition_state_with_race_metadata(self):
        strategy = MantStrategy()
        decision = strategy.next_decision(
            {
                "data": {
                    "race_start_info": {"program_id": 81},
                    "chara_info": {
                        "turn": 48,
                        "playing_state": 3,
                        "state": 2,
                        "race_program_id": 81,
                    },
                }
            },
            {},
        )

        self.assertEqual(decision.action, "settle_state")
        self.assertIn("stale race metadata state", decision.reason)

    def test_strategy_settles_midcareer_transition_state_without_race_metadata(self):
        strategy = MantStrategy()
        decision = strategy.next_decision(
            {
                "data": {
                    "race_start_info": None,
                    "chara_info": {
                        "turn": 48,
                        "playing_state": 5,
                        "state": 2,
                        "race_program_id": 0,
                    },
                }
            },
            {},
        )

        self.assertEqual(decision.action, "settle_state")
        self.assertEqual(decision.reason, "post-action state without active race")

    def test_upcoming_stamina_rescue_retries_affordability_failures(self):
        runner = CareerRunner(BASE_DIR)
        runner.race_planner = StaminaRetryPlanner()
        runner.skill_buyer = StaminaRetrySkillBuyer("no_affordable_stamina_skill")
        state = {"data": {"chara_info": {"turn": 42, "skill_point": 120}}}

        runner._maybe_buy_upcoming_stamina_skill(None, state, {}, None)
        runner._maybe_buy_upcoming_stamina_skill(None, state, {}, None)

        self.assertEqual(runner.skill_buyer.calls, 2)
        self.assertNotIn((44, 168), runner.stamina_rescue_attempts)

    def test_upcoming_stamina_rescue_does_not_retry_terminal_skips(self):
        runner = CareerRunner(BASE_DIR)
        runner.race_planner = StaminaRetryPlanner()
        runner.skill_buyer = StaminaRetrySkillBuyer("already_has_usable_stamina_recovery_skill")
        state = {"data": {"chara_info": {"turn": 42, "skill_point": 120}}}

        runner._maybe_buy_upcoming_stamina_skill(None, state, {}, None)
        runner._maybe_buy_upcoming_stamina_skill(None, state, {}, None)

        self.assertEqual(runner.skill_buyer.calls, 1)
        self.assertIn((44, 168), runner.stamina_rescue_attempts)

    def test_strategy_settles_midcareer_transition_with_home_commands(self):
        strategy = MantStrategy()
        decision = strategy.next_decision(
            {
                "data": {
                    "race_start_info": None,
                    "chara_info": {
                        "turn": 48,
                        "playing_state": 5,
                        "state": 2,
                        "race_program_id": 0,
                        "vital": 26,
                        "max_vital": 104,
                        "motivation": 5,
                        "fans": 34054,
                        "speed": 594,
                        "stamina": 486,
                        "power": 651,
                        "guts": 240,
                        "wiz": 376,
                        "skill_point": 580,
                    },
                    "home_info": {"command_info_array": _actionable_home_commands()},
                }
            },
            {},
        )

        self.assertEqual(decision.action, "settle_state")
        self.assertEqual(decision.reason, "post-action state without active race")

    def test_race_progress_reloads_state_after_reconciled_102s(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceProgressRecoveryClient()

        state = runner._race_progress(
            client,
            {
                "current_turn": 24,
                "phase": "end",
                "program_id": 168,
                "chara_info": {"turn": 24, "playing_state": 5},
            },
        )

        self.assertEqual((state["data"]["chara_info"])["turn"], 25)
        self.assertEqual((state["data"]["chara_info"])["playing_state"], 1)
        self.assertEqual(
            client.calls,
            [("race_end", 24), ("load_career", 0)],
        )

    def test_race_progress_stops_when_102_leaves_same_active_race_state(self):
        runner = CareerRunner(BASE_DIR)
        client = StuckActiveRaceClient()

        state = runner._race_progress(
            client,
            {
                "current_turn": 24,
                "phase": "end",
                "program_id": 168,
                "race_start_info": {"program_id": 168},
                "chara_info": {"turn": 24, "playing_state": 3, "race_program_id": 168},
            },
        )

        self.assertEqual((state["data"]["chara_info"])["playing_state"], 3)
        self.assertEqual(client.calls, [("race_end", 24), ("load_career", 0)])
        self.assertTrue(runner.stop_requested)
        self.assertIn("stopping to avoid retry loop", runner.status["last_action"])

    def test_final_race_out_102_finishes_instead_of_stopping_on_stale_metadata(self):
        runner = CareerRunner(BASE_DIR)
        client = FinalRaceOut102Client()

        state = runner._race_progress(
            client,
            {
                "current_turn": 78,
                "phase": "end",
                "program_id": 2509,
                "race_start_info": {"program_id": 2509, "race_instance_id": 920091},
                "chara_info": {"turn": 78, "playing_state": 5, "race_program_id": 2509},
            },
            preset={},
            strategy=MantStrategy(),
        )

        self.assertIn("single_mode_finish_common", state["data"])
        self.assertFalse(runner.stop_requested)
        self.assertTrue(runner.status["finished"])
        self.assertEqual(client.calls[-1], ("finish_career", 78, False))

    def test_race_progress_blocks_stale_consumed_turn_state_before_race_end(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceProgressRecoveryClient()

        state = runner._race_progress(
            client,
            {
                "current_turn": 48,
                "phase": "end",
                "program_id": 81,
                "race_start_info": {"program_id": 81},
                "chara_info": {
                    "turn": 48,
                    "playing_state": 3,
                    "state": 2,
                    "race_program_id": 81,
                },
            },
        )

        self.assertEqual((state["data"]["chara_info"])["state"], 2)
        self.assertEqual(client.calls, [])
        self.assertTrue(runner.stop_requested)
        self.assertIn("not safe to call race_end", runner.status["last_action"])

    def test_race_entry_does_not_finish_when_server_returns_midcareer_state_two(self):
        runner = CareerRunner(BASE_DIR)
        client = StaleRaceEntryClient()

        state = runner._race(
            client,
            {"data": {"chara_info": {"turn": 48}}},
            {},
            {"program_id": 81, "current_turn": 48},
        )

        self.assertEqual((state["data"]["chara_info"])["state"], 2)
        self.assertEqual((state["data"]["chara_info"])["playing_state"], 2)
        self.assertEqual(client.calls, [("race_entry", 81, 48)])
        self.assertTrue(runner.stop_requested)
        self.assertFalse(runner.status["finished"])
        self.assertIn("stale race metadata", runner.status["last_action"])

    def test_race_entry_205_retries_after_refresh_before_rejecting_route(self):
        runner = CareerRunner(BASE_DIR)
        client = RefreshRetryRaceEntryClient()

        state = runner._race(
            client,
            {"data": {"chara_info": {"turn": 16, "playing_state": 1, "state": 0}}},
            {"scenario_id": 1},
            {"program_id": 629, "current_turn": 16},
        )

        self.assertIn("single_mode_finish_common", state["data"])
        self.assertEqual(
            client.calls,
            [
                ("race_entry", 629, 16),
                ("load_career",),
                ("race_entry", 629, 16),
                ("finish_career", 16, False),
            ],
        )
        self.assertFalse(runner.stop_requested)

    def test_finish_career_reloads_after_successful_final_skill_buy_before_retry(self):
        runner = CareerRunner(BASE_DIR)
        client = StaleFinalSkillClient()
        state = {
            "data": {
                "single_mode_finish_common": {},
                "chara_info": {
                    "turn": 78,
                    "state": 3,
                    "playing_state": 5,
                    "skill_point": 1000,
                    "skill_array": [],
                    "skill_tips_array": [{"group_id": 20160, "rarity": 1, "level": 0}],
                },
            }
        }
        preset = {
            "learn_skill_list": [["Groundwork"]],
            "learn_skill_only_user_provided": False,
            "learn_skill_append_defaults": False,
        }

        runner._finish_career(client, state, preset, MantStrategy(), 78)

        gain_calls = [call for call in client.calls if call[0] == "gain_skills"]
        self.assertEqual(gain_calls, [("gain_skills", (201601,), 78)])
        self.assertIn(("load_career",), client.calls)
        self.assertEqual(client.calls[-1], ("finish_career", 78, False))
        self.assertTrue(runner.status["finished"])

    def test_finish_career_does_not_rebuy_when_reload_omits_accepted_skill(self):
        runner = CareerRunner(BASE_DIR)
        client = StaleFinalSkillTruncatedReloadClient()
        state = {
            "data": {
                "single_mode_finish_common": {},
                "chara_info": {
                    "turn": 78,
                    "state": 3,
                    "playing_state": 5,
                    "skill_point": 1000,
                    "skill_array": [],
                    "skill_tips_array": [{"group_id": 20160, "rarity": 1, "level": 0}],
                },
            }
        }
        preset = {
            "learn_skill_list": [["Groundwork"]],
            "learn_skill_only_user_provided": False,
            "learn_skill_append_defaults": False,
        }

        runner._finish_career(client, state, preset, MantStrategy(), 78)

        gain_calls = [call for call in client.calls if call[0] == "gain_skills"]
        self.assertEqual(gain_calls, [("gain_skills", (201601,), 78)])
        self.assertIn(("load_career",), client.calls)
        self.assertEqual(client.calls[-1], ("finish_career", 78, False))
        self.assertTrue(runner.status["finished"])

    def test_finish_career_blocks_suspicious_early_finish_without_confirmed_finish_state(self):
        runner = CareerRunner(BASE_DIR)

        class NoopFinishClient:
            def __init__(self):
                self.calls = []

            def finish_career(self, current_turn=0, is_force_delete=False):
                self.calls.append(("finish_career", current_turn, is_force_delete))
                return {"data": {"single_mode_finish_common": {}, "chara_info": {"turn": current_turn}}}

        client = NoopFinishClient()
        state = {
            "data": {
                "chara_info": {
                    "turn": 24,
                    "state": 2,
                    "playing_state": 5,
                    "skill_point": 250,
                    "skill_array": [],
                    "skill_tips_array": [],
                },
                "race_start_info": None,
            }
        }

        result = runner._finish_career(client, state, {}, MantStrategy(), 24)

        self.assertIs(result, state)
        self.assertEqual(client.calls, [])
        self.assertTrue(runner.stop_requested)
        self.assertFalse(runner.status.get("finished"))
        self.assertIn("blocked suspicious early finish request", runner.status.get("last_action") or "")

    def test_finish_career_allows_early_complete_career_prompt_and_refreshes_home_when_loop_off(self):
        runner = CareerRunner(BASE_DIR)
        client = EarlyCompleteCareerClient()
        state = {
            "data": {
                "chara_info": {
                    "turn": 48,
                    "state": 2,
                    "playing_state": 5,
                    "race_program_id": 0,
                    "fans": 34054,
                    "skill_point": 0,
                    "skill_array": [],
                    "skill_tips_array": [],
                },
                "race_start_info": None,
                "home_info": {
                    "command_info_array": _actionable_home_commands(),
                },
            }
        }

        result = runner._finish_career(client, state, {}, MantStrategy(), 48)

        self.assertIn("single_mode_finish_common", result["data"])
        self.assertEqual(
            client.calls,
            [
                ("finish_career", 48, False),
                ("call", "load/index", {"adid": ""}),
                ("read_info",),
            ],
        )
        self.assertTrue(runner.status.get("finished"))

    def test_race_progress_reloads_stale_state_without_hammering_race_endpoints(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceProgressRecoveryClient()

        state = runner._race_progress(
            client,
            {
                "current_turn": 48,
                "phase": "end",
                "chara_info": {"turn": 48, "playing_state": 5, "race_program_id": 0},
            },
        )

        self.assertEqual((state["data"]["chara_info"])["turn"], 25)
        self.assertEqual(client.calls, [("load_career", 0)])

    def test_complete_career_prompt_is_not_treated_as_post_action_without_active_race(self):
        runner = CareerRunner(BASE_DIR)
        client = ActionableHomeTransitionClient()
        initial = {
            "data": {
                "chara_info": {
                    "turn": 48,
                    "playing_state": 5,
                    "state": 2,
                    "race_program_id": 0,
                },
                "race_start_info": None,
            }
        }

        state = runner._settle_state(client, MantStrategy(), initial, {"current_turn": 48})

        self.assertEqual(client.calls, [("load_career", 0)])
        self.assertEqual((state["data"]["chara_info"])["turn"], 48)
        self.assertFalse(runner.stop_requested)
        self.assertFalse(runner._is_post_action_without_active_race(state))
        self.assertTrue(runner._is_career_finish_state(state))

    def test_race_result_updates_action_history_as_win(self):
        runner = CareerRunner(BASE_DIR)
        decision = type("Decision", (), {
            "action": "race",
            "payload": {"program_id": 846, "current_turn": 12},
            "reason": "846 Junior Make Debut",
        })()

        runner._record_action(decision, {"turn": 12, "vital": 80, "max_vital": 100, "speed": 250})
        result = runner._race_result_from_response({
            "data": {
                "race_reward_info": {
                    "result_rank": 1,
                    "gained_fans": 1454,
                },
                "race_history": [
                    {"turn": 12, "program_id": 846, "result_rank": 1},
                ],
            }
        }, current_turn=12, program_id=846)
        runner._record_race_result(12, 846, result)

        row = runner.status["action_history"][-1]
        self.assertTrue(row["won"])
        self.assertEqual(row["result_rank"], 1)
        self.assertEqual(row["race_result"]["status"], "won")
        self.assertIn("WON #1", row["detail"])

    def test_race_result_uses_history_fallback_for_loss(self):
        runner = CareerRunner(BASE_DIR)
        result = runner._race_result_from_response({
            "data": {
                "race_history": [
                    {"turn": 43, "program_id": 88, "result_rank": 4},
                ],
            }
        }, current_turn=43, program_id=88)

        self.assertFalse(result["won"])
        self.assertEqual(result["finish_rank"], 4)
        self.assertEqual(result["status"], "lost")

    def test_race_continue_retries_loss_before_recording_final_result(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceContinueWinClient()
        end_state, result = runner._resolve_race_end_with_retries(
            client,
            race_end_state(24, 168, rank=2),
            current_turn=24,
            program_id=168,
            preset={"clock_use_limit": 99, "race_continue_delay_seconds": 0},
            race_start_info={"program_id": 168, "is_short": True},
        )

        self.assertTrue(result["won"])
        self.assertEqual(result["finish_rank"], 1)
        self.assertEqual((end_state["data"]["race_reward_info"])["result_rank"], 1)
        self.assertEqual(client.calls, [("race_continue", 24, 2), ("race_start", 1, 24), ("race_end", 24)])
        self.assertEqual(runner.status["race_retries"], 1)
        self.assertEqual(runner.status["alarm_clocks_used"], 1)
        self.assertIn("after 1 alarm clock", runner._race_result_label(result))
        self.assertIn("previous #2", runner._race_result_label(result))

    def test_default_pre_end_probe_matches_live_alarm_clock_timing(self):
        runner = CareerRunner(BASE_DIR)
        cfg = runner._race_continue_config({"clock_use_limit": 5})

        # Successful manual traces click Try Again roughly 9-10s after race_start.
        # Earlier probes around 7-8s returned 205 even when race_end later lost.
        self.assertGreaterEqual(cfg["pre_end_probe_seconds"], 9.0)
        self.assertLessEqual(cfg["pre_end_probe_seconds"], 15.0)

    def test_race_continue_uses_daily_free_retry_when_available(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceContinueWinClient()
        _, result = runner._resolve_race_end_with_retries(
            client,
            race_end_state(24, 168, rank=2, available_free_continue_num=1),
            current_turn=24,
            program_id=168,
            preset={"clock_use_limit": 5, "race_continue_delay_seconds": 0, "clock_pre_race_end_probe_seconds": 0},
            race_start_info={"program_id": 168, "is_short": True},
        )

        self.assertTrue(result["won"])
        self.assertEqual(client.calls[0], ("race_continue", 24, 1))
        self.assertEqual(runner.status["race_retries"], 1)
        self.assertEqual(runner.status["free_race_retries"], 1)
        self.assertEqual(runner.status["alarm_clocks_used"], 0)
        self.assertEqual(runner.status["carat_race_retries"], 0)
        self.assertIn("after 1 free retry", runner._race_result_label(result))

    def test_race_continue_caps_at_five_uses_per_career(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceContinueNeverWinClient()
        _, result = runner._resolve_race_end_with_retries(
            client,
            race_end_state(24, 168, rank=2),
            current_turn=24,
            program_id=168,
            preset={"clock_use_limit": 99, "clock_consecutive_limit": 99, "race_continue_delay_seconds": 0},
            race_start_info={"program_id": 168, "is_short": True},
        )

        continue_calls = [call for call in client.calls if call[0] == "race_continue"]
        self.assertEqual(len(continue_calls), 5)
        self.assertFalse(result["won"])
        self.assertEqual(runner.status["race_retries"], 5)

    def test_race_continue_caps_at_three_consecutive_uses_per_race_by_default(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceContinueNeverWinClient()
        _, result = runner._resolve_race_end_with_retries(
            client,
            race_end_state(24, 168, rank=2),
            current_turn=24,
            program_id=168,
            preset={"clock_use_limit": 5, "race_continue_delay_seconds": 0, "clock_pre_race_end_probe_seconds": 0},
            race_start_info={"program_id": 168, "is_short": True},
        )

        continue_calls = [call for call in client.calls if call[0] == "race_continue"]
        self.assertEqual(len(continue_calls), 3)
        self.assertFalse(result["won"])
        self.assertEqual(runner.status["race_retries"], 3)
        self.assertEqual(runner.status["alarm_clocks_used"], 3)

    def test_race_continue_direct_carat_type_requires_legacy_opt_in(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceContinueCaratFallbackClient()

        _, disabled_result = runner._resolve_race_end_with_retries(
            client,
            race_end_state(24, 168, rank=2),
            current_turn=24,
            program_id=168,
            preset={"clock_use_limit": 1, "race_continue_delay_seconds": 0},
            race_start_info={"program_id": 168, "is_short": True},
        )

        self.assertFalse(disabled_result["won"])
        self.assertEqual(client.calls, [("race_continue", 24, 2)])
        self.assertEqual(runner.status["race_retries"], 0)

        runner = CareerRunner(BASE_DIR)
        client = RaceContinueCaratFallbackClient()
        _, still_disabled_result = runner._resolve_race_end_with_retries(
            client,
            race_end_state(24, 168, rank=2),
            current_turn=24,
            program_id=168,
            preset={"clock_use_limit": 1, "clock_allow_carats": True, "race_continue_delay_seconds": 0},
            race_start_info={"program_id": 168, "is_short": True},
        )

        self.assertFalse(still_disabled_result["won"])
        self.assertEqual(client.calls, [("race_continue", 24, 2)])
        self.assertEqual(runner.status["race_retries"], 0)

        runner = CareerRunner(BASE_DIR)
        client = RaceContinueCaratFallbackClient()
        _, result = runner._resolve_race_end_with_retries(
            client,
            race_end_state(24, 168, rank=2),
            current_turn=24,
            program_id=168,
            preset={
                "clock_use_limit": 1,
                "clock_allow_carats": True,
                "clock_allow_direct_carat_continue": True,
                "race_continue_delay_seconds": 0,
            },
            race_start_info={"program_id": 168, "is_short": True},
        )

        self.assertTrue(result["won"])
        self.assertEqual(client.calls[0], ("race_continue", 24, 2))
        self.assertEqual(client.calls[1], ("race_continue", 24, 3))
        self.assertEqual(runner.status["carat_race_retries"], 1)

    def test_race_continue_buys_alarm_clock_with_carats_then_uses_type_2(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceContinueCaratExchangeClient()

        _, result = runner._resolve_race_end_with_retries(
            client,
            race_end_state(24, 168, rank=2),
            current_turn=24,
            program_id=168,
            preset={"clock_use_limit": 1, "clock_allow_carats": True, "race_continue_delay_seconds": 0},
            race_start_info={"program_id": 168, "is_short": True},
        )

        self.assertTrue(result["won"])
        self.assertEqual(
            client.calls[:3],
            [
                ("race_continue", 24, 2),
                ("exchange_item", 9001, 1, 2265, ""),
                ("race_continue", 24, 2),
            ],
        )
        self.assertEqual(runner.status["race_retries"], 1)
        self.assertEqual(runner.status["alarm_clocks_used"], 1)
        self.assertEqual(runner.status["carat_race_retries"], 1)
        self.assertIn("after 1 carat alarm clock", runner._race_result_label(result))

    def test_race_continue_500_does_not_disable_alarm_clock_for_career(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceContinuePostRaceEndRejectClient()

        _, result = runner._resolve_race_end_with_retries(
            client,
            race_end_state(24, 168, rank=2),
            current_turn=24,
            program_id=168,
            preset={"clock_use_limit": 5, "clock_allow_carats": True, "race_continue_delay_seconds": 0},
            race_start_info={"program_id": 168, "is_short": True},
        )

        self.assertFalse(result["won"])
        self.assertEqual(client.calls, [("race_continue", 24, 2), ("load_career",)])
        self.assertEqual(runner.status["disabled_continue_resources"], [])
        self.assertIn((2, "alarm_clock"), runner._race_continue_attempt_types({}, {}))

    def test_race_progress_probes_continue_before_race_end_for_active_race(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceContinuePreEndProbeClient()

        result = runner._race_progress(
            client,
            {
                "current_turn": 24,
                "phase": "end",
                "program_id": 168,
                "race_start_info": {"program_id": 168, "is_short": True},
                "chara_info": {"turn": 24, "playing_state": 3, "state": 0, "race_program_id": 168},
            },
            preset={
                "clock_use_limit": 5,
                "race_continue_delay_seconds": 0,
                "clock_pre_race_end_probe_seconds": 0,
                "clock_pre_race_end_continue_probe": True,
            },
        )

        self.assertEqual(
            client.calls[:5],
            [
                ("race_continue", 24, 2),
                ("race_start", 1, 24),
                ("load_career",),
                ("race_continue", 24, 2),
                ("race_end", 24),
            ],
        )
        self.assertEqual(client.calls[-1], ("race_out", 24))
        self.assertEqual(runner.status["alarm_clocks_used"], 1)
        self.assertEqual((result.get("data") or {}).get("chara_info", {}).get("playing_state"), 1)

    def test_pre_end_continue_probe_retries_early_205_until_ready(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceContinuePreEndProbeDelayedReadyClient()

        result = runner._race_progress(
            client,
            {
                "current_turn": 24,
                "phase": "end",
                "program_id": 168,
                "race_start_info": {"program_id": 168, "is_short": True},
                "chara_info": {"turn": 24, "playing_state": 3, "state": 0, "race_program_id": 168},
            },
            preset={
                "clock_use_limit": 5,
                "race_continue_delay_seconds": 0,
                "clock_pre_race_end_probe_seconds": 1,
                "clock_pre_race_end_probe_interval": 0.05,
                "clock_pre_race_end_continue_probe": True,
                "clock_pre_race_end_retry_205": True,
            },
        )

        continue_calls = [call for call in client.calls if call[0] == "race_continue"]
        self.assertEqual(continue_calls[:3], [("race_continue", 24, 2)] * 3)
        self.assertEqual(runner.status["alarm_clocks_used"], 1)
        self.assertEqual((result.get("data") or {}).get("chara_info", {}).get("playing_state"), 1)

    def test_pre_end_continue_probe_caps_at_three_consecutive_clocks(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceContinuePreEndProbeAlwaysLoseClient()

        result = runner._race_progress(
            client,
            {
                "current_turn": 24,
                "phase": "end",
                "program_id": 168,
                "race_start_info": {"program_id": 168, "is_short": True},
                "chara_info": {"turn": 24, "playing_state": 3, "state": 0, "race_program_id": 168},
            },
            preset={
                "clock_use_limit": 5,
                "race_continue_delay_seconds": 0,
                "clock_pre_race_end_probe_seconds": 0,
                "clock_pre_race_end_continue_probe": True,
            },
        )

        continue_calls = [call for call in client.calls if call[0] == "race_continue"]
        self.assertEqual(len(continue_calls), 3)
        self.assertEqual(runner.status["alarm_clocks_used"], 3)
        self.assertEqual(runner.status["race_retries"], 3)
        self.assertEqual(len([call for call in client.calls if call[0] == "race_end"]), 1)
        self.assertEqual((result.get("data") or {}).get("chara_info", {}).get("playing_state"), 1)

    def test_pre_end_continue_replay_start_2502_defers_to_replay_state(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceContinueReplayStartRejectedClient()

        result = runner._race_progress(
            client,
            {
                "current_turn": 24,
                "phase": "end",
                "program_id": 168,
                "race_start_info": {"program_id": 168, "is_short": True},
                "chara_info": {"turn": 24, "playing_state": 3, "state": 0, "race_program_id": 168},
            },
            preset={
                "clock_use_limit": 5,
                "race_continue_delay_seconds": 0,
                "clock_pre_race_end_probe_seconds": 0,
                "clock_pre_race_end_continue_probe": True,
            },
        )

        self.assertEqual([call for call in client.calls if call[0] == "race_continue"], [("race_continue", 24, 2)])
        self.assertIn(("race_start", 1, 24), client.calls)
        self.assertEqual(runner.status["alarm_clocks_used"], 1)
        self.assertEqual((result.get("data") or {}).get("chara_info", {}).get("playing_state"), 2)

    def test_pre_end_continue_probe_500_does_not_block_after_race_end_fallback(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceContinuePreEndProbeRejectClient()

        runner._race_progress(
            client,
            {
                "current_turn": 24,
                "phase": "end",
                "program_id": 168,
                "race_start_info": {"program_id": 168, "is_short": True},
                "chara_info": {"turn": 24, "playing_state": 3, "state": 0, "race_program_id": 168},
            },
            preset={
                "clock_use_limit": 5,
                "clock_allow_carats": True,
                "race_continue_delay_seconds": 0,
                "clock_pre_race_end_continue_probe": True,
            },
        )

        self.assertEqual([call for call in client.calls if call[0] == "race_continue"], [("race_continue", 24, 2), ("race_continue", 24, 2)])
        self.assertEqual(runner.status["alarm_clocks_used"], 0)
        self.assertEqual(runner.status["disabled_continue_resources"], [])

    def test_race_progress_try_again_state_uses_alarm_clock_before_race_out(self):
        runner = CareerRunner(BASE_DIR)
        client = RaceProgressTryAgainClient()

        runner._race_progress(
            client,
            {
                "current_turn": 24,
                "phase": "end",
                "program_id": 168,
                "race_start_info": {"program_id": 168, "is_short": True},
                "chara_info": {"turn": 24, "playing_state": 5, "state": 3, "race_program_id": 168},
            },
            preset={"clock_use_limit": 5, "race_continue_delay_seconds": 0},
        )

        self.assertIn(("race_continue", 24, 2), client.calls)
        self.assertEqual(runner.status["alarm_clocks_used"], 1)
        self.assertEqual(client.calls[-1], ("race_out", 24))

    def test_mant_strategy_routes_race_result_state_to_end_not_settle(self):
        strategy = MantStrategy()

        decision = strategy.next_decision(
            {
                "data": {
                    "chara_info": {"turn": 24, "playing_state": 5, "state": 3, "race_program_id": 168},
                    "race_start_info": {"program_id": 168, "is_short": True},
                }
            },
            {},
        )

        self.assertEqual(decision.action, "race_progress")
        self.assertEqual(decision.payload.get("phase"), "end")

    def test_maybe_change_running_style_fires_when_preset_differs_from_chara(self):
        runner = CareerRunner(BASE_DIR)

        class StyleClient:
            def __init__(self):
                self.calls = []

            def change_running_style(self, program_id, running_style, current_turn):
                self.calls.append({
                    "endpoint": "single_mode_free/change_running_style",
                    "program_id": program_id,
                    "running_style": running_style,
                    "current_turn": current_turn,
                })
                return {"data": {}}

        client = StyleClient()
        state = {"data": {"chara_info": {"race_running_style": 2}}}
        preset = {"skill_profile_style": "late_surger"}

        runner._maybe_change_running_style(client, state, preset, program_id=846, current_turn=12)

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["running_style"], 3)
        self.assertEqual(client.calls[0]["program_id"], 846)
        self.assertEqual(client.calls[0]["current_turn"], 12)

    def test_maybe_change_running_style_uses_correct_api_value_for_end_closer(self):
        runner = CareerRunner(BASE_DIR)

        class StyleClient:
            def __init__(self):
                self.calls = []

            def change_running_style(self, program_id, running_style, current_turn):
                self.calls.append({"running_style": running_style})
                return {"data": {}}

        client = StyleClient()
        state = {"data": {"chara_info": {"race_running_style": 2}}}
        preset = {"skill_profile_style": "end_closer"}

        runner._maybe_change_running_style(client, state, preset, program_id=846, current_turn=12)

        self.assertEqual(client.calls[0]["running_style"], 4)

    def test_maybe_change_running_style_uses_race_specific_override(self):
        runner = CareerRunner(BASE_DIR)

        class StyleClient:
            def __init__(self):
                self.calls = []

            def change_running_style(self, program_id, running_style, current_turn):
                self.calls.append({
                    "program_id": program_id,
                    "running_style": running_style,
                    "current_turn": current_turn,
                })
                return {"data": {}}

        client = StyleClient()
        state = {"data": {"chara_info": {"race_running_style": 2}}}
        preset = {"race_style_overrides": {"846": "end_closer"}}

        runner._maybe_change_running_style(client, state, preset, program_id=846, current_turn=12)

        self.assertEqual(len(client.calls), 1)
        self.assertEqual(client.calls[0]["running_style"], 4)

    def test_race_result_records_style_context_from_calendar_override(self):
        runner = CareerRunner(BASE_DIR)
        runner.report = new_report({"name": "test"}, scenario_id=4)

        class StyleClient:
            def __init__(self):
                self.calls = []

            def change_running_style(self, program_id, running_style, current_turn):
                self.calls.append({
                    "program_id": program_id,
                    "running_style": running_style,
                    "current_turn": current_turn,
                })
                return {"data": {}}

        race = runner.race_planner.catalog.by_id[2171]
        preset = {
            "custom_race_schedule": [
                runner.race_planner.catalog.entry_from_race(
                    race,
                    "late_surger",
                    "Classic Year Late Oct @ Kikuka Sho",
                )
            ]
        }
        state = {"data": {"chara_info": {"race_running_style": 2, "vital": 80, "max_vital": 100, "speed": 500}}}
        client = StyleClient()
        decision = type("Decision", (), {
            "action": "race",
            "payload": {"program_id": 168, "current_turn": 44},
            "reason": "168 Kikuka Sho",
        })()

        runner._record_action(decision, {"turn": 44, "vital": 80, "max_vital": 100, "speed": 500})
        runner._maybe_change_running_style(client, state, preset, program_id=168, current_turn=44)
        runner._record_race_result(44, 168, {
            "turn": 44,
            "program_id": 168,
            "finish_rank": 3,
            "result_rank": 3,
            "won": False,
            "status": "lost",
            "source": "race_reward_info.result_rank",
        })

        row = runner.status["action_history"][-1]
        self.assertEqual(row["running_style"], 3)
        self.assertEqual(row["running_style_label"], "Late")
        self.assertEqual(row["desired_running_style"], "late_surger")
        self.assertEqual(row["style_change"]["style_source"], "scheduled_entry")
        self.assertTrue(row["style_change"]["succeeded"])

        race_rows = [
            event
            for turn in runner.report.get("turns") or []
            for event in (turn.get("events") or [])
            if event.get("event") == "race_result"
        ]
        self.assertEqual(len(race_rows), 1)
        self.assertEqual(race_rows[0]["running_style"], 3)
        self.assertEqual(race_rows[0]["running_style_label"], "Late")
        self.assertEqual(race_rows[0]["desired_running_style"], "late_surger")
        self.assertEqual(race_rows[0]["style_change"]["style_source"], "scheduled_entry")

    def test_maybe_change_running_style_skips_when_preset_style_empty(self):
        runner = CareerRunner(BASE_DIR)

        class StyleClient:
            def __init__(self):
                self.calls = []

            def change_running_style(self, **kwargs):
                self.calls.append(kwargs)

        client = StyleClient()
        state = {"data": {"chara_info": {"race_running_style": 2}}}

        runner._maybe_change_running_style(client, state, {"skill_profile_style": ""}, program_id=846, current_turn=12)
        runner._maybe_change_running_style(client, state, {}, program_id=846, current_turn=12)

        self.assertEqual(client.calls, [])

    def test_maybe_change_running_style_skips_when_chara_already_matches(self):
        runner = CareerRunner(BASE_DIR)

        class StyleClient:
            def __init__(self):
                self.calls = []

            def change_running_style(self, **kwargs):
                self.calls.append(kwargs)

        client = StyleClient()
        state = {"data": {"chara_info": {"race_running_style": 3}}}
        preset = {"skill_profile_style": "late_surger"}

        runner._maybe_change_running_style(client, state, preset, program_id=846, current_turn=12)

        self.assertEqual(client.calls, [])

    def test_is_career_finish_state_recognizes_complete_screen_despite_stale_race_info(self):
        runner = CareerRunner(BASE_DIR)
        # Complete Career screen leaves the last race's race_start_info lingering. The bot
        # must still classify state==3 + playing_state==5 as a finish state, otherwise
        # _finish_career fires race_out on a long-completed race and the server returns 102.
        state = {
            "data": {
                "chara_info": {
                    "turn": 78,
                    "state": 3,
                    "playing_state": 5,
                    "race_program_id": 81,
                },
                "race_start_info": {"program_id": 81},
            }
        }
        self.assertTrue(runner._is_career_finish_state(state))

    def test_race_entry_208_terminal_error_is_rejected_not_raised(self):
        runner = CareerRunner(BASE_DIR)

        class DoubleClickClient:
            def __init__(self):
                self.calls = []

            def race_entry(self, program_id, current_turn):
                self.calls.append(("race_entry", program_id, current_turn))
                raise Exception("API error 208 on single_mode_free/race_entry")

            def call(self, endpoint, args=None):
                self.calls.append(("call", endpoint))
                return {
                    "data": {
                        "tp_info": {"current_tp": 30, "max_tp": 100},
                        "chara_info": {"turn": 16, "playing_state": 1, "state": 0},
                    }
                }

            def load_career(self):
                return {"data": {"chara_info": {"turn": 16, "playing_state": 1, "state": 0}}}

        client = DoubleClickClient()
        result = runner._race(
            client,
            {"data": {"chara_info": {"turn": 16}}},
            {},
            {"program_id": 846, "current_turn": 16},
        )

        self.assertFalse(runner.stop_requested)
        self.assertTrue(any(call[0] == "race_entry" for call in client.calls))
        self.assertIsNotNone(result)


class AlarmClockBudgetCapTests(unittest.TestCase):
    """A career-wide budget cap on alarm-clock USES, regardless of payment
    path. Free retries, free-item alarm clocks, and carat-bought alarm clocks
    all count toward the same `alarm_clock_use_limit` counter. Once the cap
    is hit, those three resources are dropped from the attempt list. Direct
    `carats`-only continues (which aren't alarm clocks) remain available."""

    def setUp(self):
        self.runner = CareerRunner(BASE_DIR)

    def _preset(self):
        return {
            "clock_use_limit": 5,
            "clock_allow_carats": True,
            "clock_allow_direct_carat_continue": True,
            "alarm_clock_use_limit": 2,
        }

    def test_alarm_resources_present_before_limit_hit(self):
        self.runner.status["free_race_retries"] = 0
        self.runner.status["alarm_clocks_used"] = 0
        attempts = self.runner._race_continue_attempt_types(self._preset(), {"available_free_continue_num": 1})
        names = [name for _, name in attempts]
        self.assertIn("free_retry", names)
        self.assertIn("alarm_clock", names)
        self.assertIn("carat_alarm_clock", names)

    def test_all_alarm_paths_dropped_after_limit_hit_via_free(self):
        # 2 free retries already used; alarm_clock_use_limit is 2.
        self.runner.status["free_race_retries"] = 2
        self.runner.status["alarm_clocks_used"] = 0
        attempts = self.runner._race_continue_attempt_types(self._preset(), {"available_free_continue_num": 1})
        names = [name for _, name in attempts]
        self.assertNotIn("free_retry", names)
        self.assertNotIn("alarm_clock", names)
        self.assertNotIn("carat_alarm_clock", names)

    def test_all_alarm_paths_dropped_after_limit_hit_via_mixed(self):
        # 1 free + 1 alarm item = 2 total alarm-clock uses; should hit cap.
        self.runner.status["free_race_retries"] = 1
        self.runner.status["alarm_clocks_used"] = 1
        attempts = self.runner._race_continue_attempt_types(self._preset(), {"available_free_continue_num": 1})
        names = [name for _, name in attempts]
        self.assertNotIn("free_retry", names)
        self.assertNotIn("alarm_clock", names)
        self.assertNotIn("carat_alarm_clock", names)

    def test_direct_carat_continue_still_offered_after_alarm_cap(self):
        # Direct `carats` continue isn't an alarm clock, so the cap doesn't gate it.
        self.runner.status["free_race_retries"] = 0
        self.runner.status["alarm_clocks_used"] = 5
        attempts = self.runner._race_continue_attempt_types(self._preset(), {"available_free_continue_num": 0})
        names = [name for _, name in attempts]
        self.assertIn("carats", names)
        self.assertNotIn("alarm_clock", names)
        self.assertNotIn("carat_alarm_clock", names)

    def test_unlimited_when_alarm_use_limit_zero(self):
        self.runner.status["free_race_retries"] = 50
        self.runner.status["alarm_clocks_used"] = 50
        preset = self._preset()
        preset["alarm_clock_use_limit"] = 0
        attempts = self.runner._race_continue_attempt_types(preset, {"available_free_continue_num": 1})
        names = [name for _, name in attempts]
        self.assertIn("free_retry", names)
        self.assertIn("alarm_clock", names)
        self.assertIn("carat_alarm_clock", names)

    def test_legacy_clock_carat_use_limit_alias_still_works(self):
        # Older preset keys should keep working.
        self.runner.status["free_race_retries"] = 2
        self.runner.status["alarm_clocks_used"] = 0
        preset = self._preset()
        del preset["alarm_clock_use_limit"]
        preset["clock_carat_use_limit"] = 2
        attempts = self.runner._race_continue_attempt_types(preset, {"available_free_continue_num": 1})
        names = [name for _, name in attempts]
        self.assertNotIn("free_retry", names)
        self.assertNotIn("alarm_clock", names)
        self.assertNotIn("carat_alarm_clock", names)


if __name__ == "__main__":
    unittest.main()
