import unittest
from unittest.mock import patch
import json
import tempfile
from pathlib import Path

import main


def make_load_data(parent_ids):
    return {
        "tp_info": {"current_tp": 30, "max_tp": 100, "max_recovery_time": 0},
        "item_list": [{"item_id": 59, "number": 10}, {"item_id": 75, "number": 20}],
        "card_list": [{"card_id": 100101}, {"card_id": 101001}],
        "support_card_list": [{"support_card_id": 30101}],
        "support_card_deck_array": [
            {"deck_id": 1, "name": "Test Deck", "support_card_id_array": [30101]}
        ],
        "trained_chara": [
            {
                "trained_chara_id": parent_id,
                "card_id": 100101 + idx,
                "rank": 10,
                "rank_score": 1000 + idx,
                "factor_id_array": [],
                "win_saddle_id_array": [],
                "succession_chara_array": [],
            }
            for idx, parent_id in enumerate(parent_ids)
        ],
    }


class DashboardSyncSmokeTests(unittest.TestCase):
    def setUp(self):
        self.saved = {
            "active_account": main.active_account,
            "active_dashboard_data": main.active_dashboard_data,
            "active_start_state": dict(main.active_start_state),
            "active_parent_cards": dict(main.active_parent_cards),
            "active_parent_rank_points": dict(main.active_parent_rank_points),
            "active_selection": dict(main.active_selection),
        }

    def tearDown(self):
        main.active_account = self.saved["active_account"]
        main.active_dashboard_data = self.saved["active_dashboard_data"]
        main.active_start_state = self.saved["active_start_state"]
        main.active_parent_cards = self.saved["active_parent_cards"]
        main.active_parent_rank_points = self.saved["active_parent_rank_points"]
        main.active_selection = self.saved["active_selection"]

    def test_build_dashboard_data_rebuilds_parent_cache_from_latest_load(self):
        first = main.build_dashboard_data(make_load_data([9001]), preserve_friends=False)
        self.assertEqual([p["instance_id"] for p in first["parents"]], [9001])
        self.assertIn(9001, main.active_parent_cards)

        refreshed = main.build_dashboard_data(make_load_data([9002, 9003]), preserve_friends=False)
        self.assertEqual([p["instance_id"] for p in refreshed["parents"]], [9002, 9003])
        self.assertNotIn(9001, main.active_parent_cards)
        self.assertIn(9002, main.active_parent_cards)
        self.assertIn(9003, main.active_parent_cards)

    def test_build_dashboard_data_finds_nested_deck_arrays(self):
        data = make_load_data([9001])
        data.pop("support_card_deck_array")
        data["single_mode_top"] = {
            "support_card_deck_data_array": [
                {"support_card_deck_id": 1, "deck_name": "normal", "support_card_id_array": [30101]},
                {"support_card_deck_id": 2, "deck_name": "mile", "support_card_id_array": [30102, 30103]},
            ]
        }

        dashboard = main.build_dashboard_data(data, preserve_friends=False)

        self.assertEqual([deck["id"] for deck in dashboard["decks"]], [1, 2])
        self.assertEqual(dashboard["decks"][1]["name"], "mile")
        self.assertGreaterEqual(dashboard["deckDebug"]["deduped"], 2)

    def test_win_saddle_ids_use_legacy_race_win_title_map(self):
        data = main.get_win_data([1, 10, 42, 95])

        self.assertEqual([row["name"] for row in data["history"]], [
            "Classic Triple Crown",
            "Arima Kinen",
            "American JCC",
            "Flower C.",
        ])
        self.assertEqual([row["grade"] for row in data["history"]], ["TITLE", "G1", "G2", "G3"])
        self.assertEqual(data["summary"]["total"], 4)
        self.assertEqual(data["summary"]["titles"], 1)

    def test_race_record_data_preserves_losses_and_turn_order(self):
        data = main.get_race_record_data({
            "win_saddle_id_array": [85],
            "race_result_array": [
                {"turn": 17, "program_id": 630, "running_style": 2, "result_rank": 2},
                {"turn": 19, "program_id": 632, "running_style": 1, "result_rank": 1},
                {"turn": 16, "program_id": 629, "running_style": 2, "result_rank": 1},
            ],
        })

        self.assertEqual([row["turn"] for row in data["history"]], [16, 17, 19])
        self.assertEqual([row["result_rank"] for row in data["history"]], [1, 2, 1])
        self.assertEqual(data["history"][1]["result"], "lost")
        self.assertEqual(data["history"][1]["running_style"], 2)
        self.assertEqual(data["summary"]["losses"], 1)
        self.assertEqual(data["summary"]["g3"], 2)

    def test_build_dashboard_data_uses_full_parent_race_result_history(self):
        data = make_load_data([9001])
        data["trained_chara"][0]["race_result_array"] = [
            {"turn": 17, "program_id": 630, "running_style": 2, "result_rank": 2},
            {"turn": 16, "program_id": 629, "running_style": 1, "result_rank": 1},
        ]
        data["trained_chara"][0]["win_saddle_id_array"] = [85]

        dashboard = main.build_dashboard_data(data, preserve_friends=False)
        history = dashboard["parents"][0]["tree"]["self"]["race_history"]

        self.assertEqual([row["turn"] for row in history], [16, 17])
        self.assertEqual([row["result_rank"] for row in history], [1, 2])
        self.assertEqual(history[1]["result"], "lost")
        self.assertEqual(history[1]["source"], "race_result_array")

    def test_build_dashboard_data_enriches_bot_parent_history_from_career_log_losses(self):
        data = make_load_data([9001])
        data["trained_chara"][0]["win_saddle_id_array"] = [85]
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            career_log = base / "career_log_20260519_000000.json"
            career_log.write_text(json.dumps({
                "status": "finished",
                "final_turn": 78,
                "turns": [
                    {
                        "turn": 16,
                        "events": [
                            {
                                "event": "race_result",
                                "program_id": 629,
                                "race": {
                                    "program_id": 629,
                                    "race_id": 2009,
                                    "race_instance_id": 304901,
                                    "name": "Niigata Junior Stakes",
                                    "grade": "G3",
                                    "date": "Junior Year Late Aug",
                                },
                                "finish_rank": 1,
                                "won": True,
                                "running_style": 3,
                                "desired_running_style": "late_surger",
                                "style_change": {"style_source": "scheduled_entry", "succeeded": True},
                            }
                        ],
                    },
                    {
                        "turn": 17,
                        "events": [
                            {
                                "event": "race_result",
                                "program_id": 630,
                                "race": {
                                    "program_id": 630,
                                    "race_id": 2013,
                                    "race_instance_id": 305101,
                                    "name": "Sapporo Junior Stakes",
                                    "grade": "G3",
                                    "date": "Junior Year Early Sep",
                                },
                                "finish_rank": 3,
                                "won": False,
                                "running_style": 3,
                                "desired_running_style": "late_surger",
                                "style_change": {"style_source": "scheduled_entry", "succeeded": True},
                            }
                        ],
                    },
                ],
            }), encoding="utf-8")
            registry_dir = base / "parent_memory"
            registry_dir.mkdir(parents=True, exist_ok=True)
            (registry_dir / "bot_parent_registry.json").write_text(json.dumps({
                "schema": "sweepy_parent_memory_v1",
                "bot_parents": [
                    {
                        "instance_id": 9001,
                        "career_log": str(career_log),
                        "registered_at": "2026-05-19T00:00:00",
                        "run_context": {},
                    }
                ],
                "pending_bot_careers": [],
            }), encoding="utf-8")

            with patch.object(main, "DIR", base), patch.dict("os.environ", {"UMA_RUNTIME_DIR": str(base)}):
                dashboard = main.build_dashboard_data(data, preserve_friends=False)

        parent = dashboard["parents"][0]
        history = parent["tree"]["self"]["race_history"]
        self.assertTrue(parent["made_by_bot"])
        self.assertEqual([row["turn"] for row in history], [16, 17])
        self.assertEqual([row["result_rank"] for row in history], [1, 3])
        self.assertEqual(history[1]["result"], "lost")
        self.assertEqual(history[1]["source"], "career_log.race_result")
        self.assertEqual(history[1]["running_style"], 3)
        self.assertEqual(history[1]["desired_running_style"], "late_surger")
        self.assertEqual(history[1]["style_change"]["style_source"], "scheduled_entry")
        self.assertEqual(parent["tree"]["self"]["wins"]["losses"], 1)

    def test_race_history_source_is_preserved_when_result_array_missing(self):
        data = main.get_race_record_data({
            "race_history": [
                {"turn": 17, "program_id": 630, "running_style": 2, "result_rank": 2},
            ],
        })

        self.assertEqual(data["history"][0]["source"], "race_history")
        self.assertEqual(data["history"][0]["result"], "lost")

    def test_placeholder_race_names_are_resolved_from_race_map(self):
        data = main.get_race_record_data({
            "race_history": [
                {
                    "program_id": 14,
                    "race_id": 201201,
                    "name": "Race 201201",
                    "grade": "RACE",
                    "result_rank": 1,
                },
            ],
        })
        row = data["history"][0]

        self.assertEqual(row["name"], "Hanshin Umamusume Stakes")
        self.assertEqual(row["grade"], "G2")
        self.assertEqual(row["turn"], 55)
        self.assertEqual(row["month"], 4)
        self.assertEqual(row["half"], 1)
        self.assertEqual(row["race_instance_id"], 201201)

    def test_race_history_can_resolve_by_instance_id_without_program_id(self):
        data = main.get_race_record_data({
            "race_history": [
                {"race_id": 401001, "name": "Race 401001", "grade": "RACE", "result_rank": 1},
            ],
        })
        row = data["history"][0]

        self.assertEqual(row["program_id"], 42)
        self.assertEqual(row["name"], "Carbuncle Stakes")
        self.assertEqual(row["grade"], "OP")
        self.assertEqual(row["turn"], 49)
        self.assertEqual(row["race_instance_id"], 401001)

    def test_skill_rows_include_estimated_costs(self):
        rows = main.get_skill_rows([
            {"skill_id": 200352, "level": 1},  # Corner Recovery circle
            {"skill_id": 201601, "level": 1},  # Groundwork
            {"skill_id": 900111, "level": 1},  # Unique
        ])
        by_id = {row["skill_id"]: row for row in rows}

        self.assertEqual(by_id[200352]["estimated_cost"], 110)
        self.assertEqual(by_id[201601]["estimated_cost"], 120)
        self.assertEqual(by_id[900111]["estimated_cost"], 200)
        self.assertEqual(main.get_estimated_skill_points(rows), 430)

    def test_character_unique_skills_do_not_count_as_paid_sp(self):
        rows = main.get_skill_rows([
            {"skill_id": 100671, "level": 5},  # Character unique
            {"skill_id": 200542, "level": 1},  # Paid skill
        ])
        by_id = {row["skill_id"]: row for row in rows}

        self.assertEqual(by_id[100671]["estimated_cost"], 0)
        self.assertEqual(by_id[200542]["estimated_cost"], 180)
        self.assertEqual(main.get_estimated_skill_points(rows), 180)

    def test_factor_rows_include_inheritance_effect_summaries(self):
        rows = main.get_factors([3000303, 1000703], owner_card_id=100601)
        by_name = {row["name"]: row for row in rows}

        self.assertEqual(
            by_name["TS Climax Scenario"]["effect_summary"],
            "Inheritance effect: Stamina + Guts",
        )
        self.assertEqual(
            by_name["NHK Mile C."]["effect_summary"],
            "Inheritance effect: Speed + Power",
        )

    def test_build_dashboard_data_adds_parent_estimated_skill_points(self):
        data = make_load_data([9001])
        data["trained_chara"][0]["skill_array"] = [
            {"skill_id": 200352, "level": 1},
            {"skill_id": 201601, "level": 1},
        ]

        dashboard = main.build_dashboard_data(data, preserve_friends=False)
        parent = dashboard["parents"][0]

        self.assertEqual(parent["estimated_skill_points"], 230)
        self.assertEqual(parent["stats"]["estimated_skill_points"], 230)
        self.assertEqual(
            [row["estimated_cost"] for row in parent["skills"]],
            [110, 120],
        )

    def test_borrow_uma_score_uses_rank_score(self):
        data = {
            "succession_trained_chara_data": {
                "summary_user_info_array": [
                    {
                        "viewer_id": 111,
                        "name": "Guest Trainer",
                        "user_trained_chara": {
                            "trained_chara_id": 222,
                            "card_id": 100101,
                            "rank_score": 17620,
                        },
                    }
                ],
                "succession_trained_chara_array": [
                    {
                        "viewer_id": 111,
                        "trained_chara_id": 222,
                        "card_id": 100101,
                        "rank_score": 17620,
                    }
                ],
            }
        }

        rows = main.normalize_friend_umas(data)

        self.assertEqual(rows[0]["rank_score"], 17620)
        self.assertEqual(rows[0]["score"], 17620)

    def test_borrow_uma_preserves_real_rank_separately_from_chara_grade(self):
        data = {
            "succession_trained_chara_data": {
                "summary_user_info_array": [
                    {
                        "viewer_id": 111,
                        "name": "Guest Trainer",
                        "user_trained_chara": {
                            "trained_chara_id": 222,
                            "card_id": 100101,
                            "rank": 17,
                            "chara_grade": 10,
                        },
                    }
                ],
                "succession_trained_chara_array": [
                    {
                        "viewer_id": 111,
                        "trained_chara_id": 222,
                        "card_id": 100101,
                        "rank": 17,
                        "chara_grade": 10,
                    }
                ],
            }
        }

        rows = main.normalize_friend_umas(data)

        self.assertEqual(rows[0]["rank"], 17)
        self.assertEqual(rows[0]["chara_grade"], 10)

    def test_borrow_uma_preserves_date_fields_when_present(self):
        data = {
            "succession_trained_chara_data": {
                "summary_user_info_array": [
                    {
                        "viewer_id": 111,
                        "name": "Guest Trainer",
                        "user_trained_chara": {
                            "trained_chara_id": 222,
                            "card_id": 100101,
                            "created_at": "2026-05-15T12:34:56",
                            "updated_at": "2026-05-15T13:00:00",
                        },
                    }
                ],
                "succession_trained_chara_array": [
                    {
                        "viewer_id": 111,
                        "trained_chara_id": 222,
                        "card_id": 100101,
                    }
                ],
            }
        }

        rows = main.normalize_friend_umas(data)

        self.assertEqual(rows[0]["created_at"], "2026-05-15T12:34:56")
        self.assertEqual(rows[0]["updated_at"], "2026-05-15T13:00:00")

    def test_find_deck_rows_collects_slot_fields_and_merges_partials(self):
        data = {
            "deck_data": [
                {
                    "deck_id": 2,
                    "deck_name": "partial",
                    "support_card_id_array": [30101, 30102, 30103],
                    "support_card_id_4": 30104,
                    "support_card_5_id": 30105,
                },
                {
                    "deck_id": 2,
                    "deck_name": "partial",
                    "support_card_id_array": [30103, 30106],
                },
                {
                    "deck_id": 3,
                    "deck_name": "third",
                    "support_card_id_1": 30111,
                    "support_card_id_2": 30112,
                    "support_card_id_3": 30113,
                    "support_card_id_4": 30114,
                    "support_card_id_5": 30115,
                },
            ]
        }

        rows, debug = main.find_deck_rows(data, "test")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["deck_id"], 2)
        self.assertEqual(rows[0]["support_card_id_array"], [30101, 30102, 30103, 30104, 30105, 30106])
        self.assertEqual(rows[1]["deck_id"], 3)
        self.assertEqual(len(rows[1]["support_card_id_array"]), 5)
        self.assertEqual(debug["deduped"], 2)

    def test_reconcile_active_selection_drops_removed_parents(self):
        main.build_dashboard_data(make_load_data([9002]), preserve_friends=False)
        main.active_selection = {
            "deck": None,
            "friend": None,
            "trainee": None,
            "veterans": [{"instance_id": 9001}, {"instance_id": 9002}],
        }

        selection = main.reconcile_active_selection()

        self.assertEqual([p["instance_id"] for p in selection["veterans"]], [9002])

    def test_load_index_with_session_recovery_restarts_on_394(self):
        class FakeClient:
            def __init__(self):
                self.calls = 0
                self.logins = 0

            def call(self, endpoint, args=None):
                self.calls += 1
                raise Exception("API error 394 on load/index")

            def has_captured_auth(self):
                return True

            def login(self, max_retries=3):
                self.logins += 1
                return {"data": make_load_data([9004])}

        client = FakeClient()

        result = main.load_index_with_session_recovery(client)

        self.assertEqual(client.calls, 1)
        self.assertEqual(client.logins, 1)
        self.assertEqual(result["data"]["trained_chara"][0]["trained_chara_id"], 9004)

    def test_load_index_with_session_recovery_explains_stale_auth_without_relogin(self):
        class FakeClient:
            def call(self, endpoint, args=None):
                raise Exception('API error 394 on load/index: {"data_headers":{"sid":"secret"}}')

            def has_captured_auth(self):
                return False

        with self.assertRaises(RuntimeError) as cm:
            main.load_index_with_session_recovery(FakeClient())

        self.assertIn("API session/auth is stale", str(cm.exception))
        self.assertIn("<redacted>", str(cm.exception))

    def test_load_index_with_session_recovery_auto_refreshes_reusable_auth_after_failed_relogin(self):
        class FakeSession:
            def close(self):
                return None

        class FakeClient:
            def __init__(self):
                self.calls = 0
                self.logins = 0
                self.viewer_id = 444
                self.udid_str = "12345678-1234-1234-1234-1234567890ab"
                self.auth_key_hex = "ab" * 48
                self.steam_id = "steam-444"
                self.steam_ticket = "ticket-444"
                self.session = FakeSession()
                self._sweepy_auth_config = {
                    "steam_id": "steam-444",
                    "steam_session_ticket": "ticket-444",
                    "steam_password_seed": "",
                }

            def call(self, endpoint, args=None):
                self.calls += 1
                raise Exception("API error 394 on load/index")

            def has_captured_auth(self):
                return True

            def login(self, max_retries=3):
                self.logins += 1
                raise Exception("API error 394 on load/index")

        stale_client = FakeClient()
        refreshed_client = object()

        saved_active_client = main.active_client
        main.active_client = stale_client
        try:
            with patch.object(
                main,
                "rebuild_reusable_auth_from_cached_ticket",
                return_value=(
                    {"steam_id": "steam-444", "viewer_id": 555},
                    refreshed_client,
                    {"data": make_load_data([9010])},
                ),
            ) as rebuild, patch.object(main, "save_reusable_auth_profile", return_value=True) as save_profile:
                result = main.load_index_with_session_recovery(stale_client)
        finally:
            main.active_client = saved_active_client

        self.assertEqual(stale_client.calls, 1)
        self.assertEqual(stale_client.logins, 1)
        rebuild.assert_called_once()
        save_profile.assert_called_once()
        self.assertIs(main.active_client, saved_active_client)
        self.assertEqual(result["data"]["trained_chara"][0]["trained_chara_id"], 9010)

    def test_load_index_with_session_recovery_auto_refreshes_reusable_auth_after_501(self):
        class FakeSession:
            def close(self):
                return None

        class FakeClient:
            def __init__(self):
                self.calls = 0
                self.logins = 0
                self.viewer_id = 444
                self.udid_str = "12345678-1234-1234-1234-1234567890ab"
                self.auth_key_hex = "ab" * 48
                self.steam_id = "steam-444"
                self.steam_ticket = "ticket-444"
                self.session = FakeSession()
                self._sweepy_auth_config = {
                    "steam_id": "steam-444",
                    "steam_session_ticket": "ticket-444",
                    "steam_password_seed": "",
                }

            def call(self, endpoint, args=None):
                self.calls += 1
                raise Exception("API error 501 on load/index")

            def has_captured_auth(self):
                return True

            def login(self, max_retries=3):
                self.logins += 1
                raise Exception("API error 501 on tool/start_session")

        stale_client = FakeClient()
        refreshed_client = object()

        saved_active_client = main.active_client
        main.active_client = stale_client
        try:
            with patch.object(
                main,
                "rebuild_reusable_auth_from_cached_ticket",
                return_value=(
                    {"steam_id": "steam-444", "viewer_id": 555},
                    refreshed_client,
                    {"data": make_load_data([9011])},
                ),
            ) as rebuild, patch.object(main, "save_reusable_auth_profile", return_value=True) as save_profile:
                result = main.load_index_with_session_recovery(stale_client)
        finally:
            main.active_client = saved_active_client

        self.assertEqual(stale_client.calls, 1)
        self.assertEqual(stale_client.logins, 1)
        rebuild.assert_called_once()
        save_profile.assert_called_once()
        self.assertIs(main.active_client, saved_active_client)
        self.assertEqual(result["data"]["trained_chara"][0]["trained_chara_id"], 9011)


class LoginReadInfoToleranceTests(unittest.TestCase):
    def test_login_does_not_abort_on_read_info_state_code(self):
        # read_info/index is the last, auxiliary step of login() (home-screen
        # data, result unused). A 201 there must not kill an otherwise good
        # login — that logged the user out on dev session restore.
        import requests
        from uma_api.client import UmaClient, ApiCallError

        client = UmaClient.__new__(UmaClient)
        client.session = requests.Session()
        client.has_captured_auth = lambda: True
        client.regen_sid = lambda: None
        client.refresh_cached_account_state = lambda data: None

        load_res = {"data": {"account": "ok"}}
        calls = []

        def fake_call(ep, args=None, **kwargs):
            calls.append(ep)
            if "read_info" in ep:
                raise ApiCallError(
                    "API error 201 on read_info/index: {'result_code': 201}",
                    endpoint=ep,
                    result_code=201,
                )
            if "load" in ep:
                return load_res
            return {"data": {}}

        client.call = fake_call

        res = client.login(max_retries=0)

        # Returns the load/index result; the read_info 201 is swallowed.
        self.assertEqual(res, load_res)
        self.assertTrue(any("read_info" in ep for ep in calls))


if __name__ == "__main__":
    unittest.main()
