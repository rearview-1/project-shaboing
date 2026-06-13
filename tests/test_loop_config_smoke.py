import unittest
import asyncio
import tempfile
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import main
from uma_api import client as uma_client


class LoopConfigSmokeTests(unittest.TestCase):
    def setUp(self):
        self.saved_client = main.active_client
        self.saved_account = main.active_account
        self.saved_dashboard = main.active_dashboard_data
        self.saved_start_state = dict(main.active_start_state)
        self.saved_selection = dict(main.active_selection)
        self.saved_pending_game_auth_config = dict(main.pending_game_auth_config)
        self.saved_loop = main.loop_snapshot()
        self.saved_preset_store = main.preset_store
        self.saved_dev_reloader_state = dict(main.dev_reloader_state)
        self.saved_git_auto_update_state = dict(main.git_auto_update_state)
        self.saved_manual_career_recorder = main.manual_career_recorder

    def tearDown(self):
        main.active_client = self.saved_client
        main.active_account = self.saved_account
        main.active_dashboard_data = self.saved_dashboard
        main.active_start_state = self.saved_start_state
        main.active_selection = self.saved_selection
        main.pending_game_auth_config = self.saved_pending_game_auth_config
        main.preset_store = self.saved_preset_store
        main.manual_career_recorder = self.saved_manual_career_recorder
        main.dev_reloader_state.clear()
        main.dev_reloader_state.update(self.saved_dev_reloader_state)
        main.git_auto_update_state.clear()
        main.git_auto_update_state.update(self.saved_git_auto_update_state)
        with main.loop_lock:
            main.active_loop.clear()
            main.active_loop.update(self.saved_loop)

    def test_forever_loop_has_no_terminal_limit(self):
        req = main.RunCareerRequest(loop_enabled=True, loop_mode="forever", loop_count=5, loop_career_limit=5)

        config = main.normalize_loop_config(req)

        self.assertEqual(config["mode"], "forever")
        self.assertEqual(config["requested"], 0)
        self.assertEqual(config["career_limit"], 0)
        self.assertEqual(config["fan_limit"], 0)

    def test_career_limit_uses_explicit_limit(self):
        req = main.RunCareerRequest(loop_enabled=True, loop_mode="careers", loop_count=2, loop_career_limit=10)

        config = main.normalize_loop_config(req)

        self.assertEqual(config["mode"], "careers")
        self.assertEqual(config["requested"], 10)
        self.assertEqual(config["career_limit"], 10)

    def test_career_limit_accepts_legacy_loop_count(self):
        req = main.RunCareerRequest(loop_enabled=True, loop_mode="careers", loop_count=7, loop_career_limit=0)

        config = main.normalize_loop_config(req)

        self.assertEqual(config["mode"], "careers")
        self.assertEqual(config["requested"], 7)
        self.assertEqual(config["career_limit"], 7)

    def test_daily_action_context_uses_action_specific_assignment(self):
        main.active_client = SimpleNamespace(coin_info={"fcoin": 3, "coin": 4})
        status = {
            "daily_race": {"next_daily_race_id": 11, "records": [{"daily_race_id": 11}]},
            "legend_race": {"next_legend_race_id": 22, "group_id": 333, "records": [{"legend_race_id": 22}]},
            "daily_legend_race": {"next_legend_race_id": 44, "records": [{"legend_race_id": 44}]},
        }
        req = main.DailyAutomationRequest(
            trained_chara_id=1001,
            running_style=2,
            assignments={
                "legend_race": {"trained_chara_id": 2002, "running_style": 3},
                "daily_legend_race": {"trained_chara_id": 3003, "running_style": 4},
            },
        )

        daily_ctx = main._daily_action_context(req, status, action_name="daily_race")
        legend_ctx = main._daily_action_context(req, status, action_name="legend_race")
        daily_legend_ctx = main._daily_action_context(req, status, action_name="daily_legend_race")

        self.assertEqual(daily_ctx["trained_chara_id"], 1001)
        self.assertEqual(daily_ctx["running_style"], 2)
        self.assertEqual(legend_ctx["trained_chara_id"], 2002)
        self.assertEqual(legend_ctx["running_style"], 3)
        self.assertEqual(daily_legend_ctx["trained_chara_id"], 3003)
        self.assertEqual(daily_legend_ctx["running_style"], 4)
        self.assertEqual(legend_ctx["current_num"], 7)

    def test_calibrate_endpoint_uses_project_runtime_root(self):
        saved_calibrate_state = dict(main._calibrate_state)
        try:
            main._calibrate_state.update({
                "running": False,
                "started_at": 0,
                "report_path": "",
                "last_report": None,
            })
            with tempfile.TemporaryDirectory() as tmp:
                runtime_root = Path(tmp) / "uma_runtime"
                with patch.object(main, "runtime_output_root", return_value=runtime_root) as runtime_root_mock, \
                     patch.object(main.subprocess, "Popen") as popen_mock:
                    result = asyncio.run(main.start_calibrate({
                        "time_budget_sec": 1,
                        "baseline_sims": 1,
                        "sims_per_candidate": 1,
                        "validation_sims": 1,
                    }))

            self.assertTrue(result["success"])
            runtime_root_mock.assert_called_once_with(main.DIR)
            popen_mock.assert_called_once()
            self.assertIn("calibrate_reports", result["report_path"])
        finally:
            main._calibrate_state.clear()
            main._calibrate_state.update(saved_calibrate_state)

    def test_fan_limit_tracks_only_fan_goal(self):
        req = main.RunCareerRequest(loop_enabled=True, loop_mode="fans", loop_fan_limit=100_000_000, loop_career_limit=10)

        config = main.normalize_loop_config(req)

        self.assertEqual(config["mode"], "fans")
        self.assertEqual(config["requested"], 0)
        self.assertEqual(config["career_limit"], 0)
        self.assertEqual(config["fan_limit"], 100_000_000)

    def test_loop_tp_wait_returns_when_recovery_resource_is_ready(self):
        class Client:
            def call(self, endpoint, args=None):
                return {
                    "data": {
                        "tp_info": {"current_tp": 0, "max_tp": 100, "max_recovery_time": 0},
                        "coin_info": {"fcoin": 20, "coin": 0},
                        "item_list": [{"item_id": 32, "number": 1}],
                    }
                }

        main.active_client = Client()
        main.active_dashboard_data = {}
        main.reset_loop_state()

        result = main.wait_for_loop_tp(main.RunCareerRequest(use_tp=30, allow_recover_tp=1))

        self.assertTrue(result)
        self.assertIn("TP recovery resource ready", main.loop_snapshot()["last_message"])

    def test_requested_preset_name_is_not_forced_to_default(self):
        req = main.RunCareerRequest(preset_name="custom parent preset")

        self.assertEqual(main.requested_preset_name(req), "custom parent preset")

    def test_requested_preset_name_uses_first_available_preset_when_unspecified(self):
        class Store:
            def read_all(self):
                return [
                    {"name": "Alpha preset"},
                    {"name": "zeta preset"},
                ]

            def default_name(self, preferred=None):
                return "Alpha preset"

        main.preset_store = Store()

        self.assertEqual(main.requested_preset_name(main.RunCareerRequest()), "Alpha preset")

    def test_alarm_clock_settings_save_targets_requested_preset(self):
        class Store:
            def __init__(self):
                self.requested = None
                self.written = None

            def read_one(self, name):
                self.requested = name
                return {"name": name}

            def write(self, preset):
                self.written = dict(preset)
                return self.written

        store = Store()
        main.preset_store = store

        result = asyncio.run(main.save_race_continue(
            main.SaveRaceContinueRequest(preset_name="custom parent preset", mode="carats", limit=4)
        ))

        self.assertTrue(result["success"])
        self.assertEqual(store.requested, "custom parent preset")
        self.assertEqual(store.written["clock_use_limit"], 4)
        self.assertEqual(store.written["alarm_clock_use_limit"], 4)
        self.assertTrue(store.written["clock_allow_carats"])

    def test_manual_capture_sync_prefers_newer_hachimi_latest_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_dir = root / "runtime_manual"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            stale_runtime = runtime_dir / "latest_manual_career_log.json"
            stale_runtime.write_text('{"source":"runtime","ts":1}', encoding="utf-8")
            (runtime_dir / "latest_manual_career_summary.json").write_text('{"summary":"runtime"}', encoding="utf-8")
            (runtime_dir / "latest_manual_career_raw.json").write_text('{"raw":"runtime"}', encoding="utf-8")

            hachimi_career_dir = root / "hachimi" / "Career turn data"
            latest_dir = hachimi_career_dir / "_latest"
            debug_dir = hachimi_career_dir / "_debug"
            career_dir = hachimi_career_dir / "Unlabelled runs" / "test-career"
            latest_dir.mkdir(parents=True, exist_ok=True)
            debug_dir.mkdir(parents=True, exist_ok=True)
            career_dir.mkdir(parents=True, exist_ok=True)
            fresh_log = latest_dir / "latest_manual_career_log.json"
            fresh_log.write_text('{"source":"hachimi","ts":2}', encoding="utf-8")
            (latest_dir / "latest_manual_career_summary.json").write_text('{"summary":"hachimi","career_key":"test-career"}', encoding="utf-8")
            (latest_dir / "latest_manual_career_raw.json").write_text('{"raw":"hachimi"}', encoding="utf-8")
            (career_dir / "summary_events.jsonl").write_text(
                "\n".join([
                    '{"schema":"sweepy_hachimi_manual_career_summary_v1","ts_ms":1,"label":"free_start","index":0,"career_key":"test-career","current":{"single_mode_chara_id":123,"card_id":100101,"scenario_id":4,"start_time":"2026-05-17 10:00:00","turn":1,"vital":80,"max_vital":100,"motivation":5,"speed":100,"stamina":90,"power":80,"guts":70,"wit":60,"skill_point":50},"skills":{"bought":[{"skill_id":110261,"level":3}],"tips":[{"group_id":20037,"rarity":1,"level":1}],"disabled":[]},"supports":{"cards":[{"position":1,"support_card_id":30086,"limit_break_count":4}],"bonds":[{"target_id":1,"evaluation":90}],"training_levels":[{"command_id":101,"level":5}],"guest_outings":[]},"home":{"commands":[{"command_type":1,"command_id":101,"is_enable":1,"failure_rate":0,"level":5,"training_partner_array":[1],"tips_event_partner_array":[],"params_inc_dec_info_array":[{"target_type":1,"value":30},{"target_type":3,"value":10},{"target_type":30,"value":5},{"target_type":10,"value":-21}]}],"disabled_command_ids":[],"available_continue_num":5,"available_free_continue_num":0,"free_continue_num":1,"free_continue_time":0,"race_entry_restriction":0},"races":{"history":[{"turn":12,"program_id":624,"running_style":1,"result_rank":1}],"conditions":[],"start_info":null},"response_status":{"unchecked_events":[]}}',
                    '{"schema":"sweepy_hachimi_manual_career_summary_v1","ts_ms":2,"label":"free_check_event","index":1,"career_key":"test-career","current":{"single_mode_chara_id":123,"card_id":100101,"scenario_id":4,"start_time":"2026-05-17 10:00:00","turn":2,"vital":80,"max_vital":100,"motivation":5,"speed":130,"stamina":90,"power":80,"guts":70,"wit":60,"skill_point":55},"skills":{"bought":[{"skill_id":110261,"level":3}],"tips":[{"group_id":20037,"rarity":1,"level":1}],"disabled":[]},"supports":{"cards":[{"position":1,"support_card_id":30086,"limit_break_count":4}],"bonds":[{"target_id":1,"evaluation":90}],"training_levels":[{"command_id":101,"level":5}],"guest_outings":[]},"home":{"commands":[{"command_type":1,"command_id":101,"is_enable":1,"failure_rate":0,"level":5,"training_partner_array":[1],"tips_event_partner_array":[],"params_inc_dec_info_array":[{"target_type":1,"value":30},{"target_type":3,"value":10},{"target_type":30,"value":5},{"target_type":10,"value":-21}]}],"disabled_command_ids":[],"available_continue_num":5,"available_free_continue_num":0,"free_continue_num":1,"free_continue_time":0,"race_entry_restriction":0},"races":{"history":[{"turn":12,"program_id":624,"running_style":1,"result_rank":1}],"conditions":[],"start_info":null},"response_status":{"unchecked_events":[]}}',
                    '{"schema":"sweepy_hachimi_manual_career_summary_v1","ts_ms":3,"label":"free_check_event","index":2,"career_key":"test-career","current":{"single_mode_chara_id":123,"card_id":100101,"scenario_id":4,"start_time":"2026-05-17 10:00:00","turn":78,"vital":80,"max_vital":100,"motivation":5,"speed":800,"stamina":500,"power":600,"guts":400,"wit":300,"skill_point":900},"skills":{"bought":[{"skill_id":110261,"level":3}],"tips":[{"group_id":20037,"rarity":1,"level":1}],"disabled":[]},"supports":{"cards":[{"position":1,"support_card_id":30086,"limit_break_count":4}],"bonds":[{"target_id":1,"evaluation":90}],"training_levels":[{"command_id":101,"level":5}],"guest_outings":[]},"home":{"commands":[{"command_type":1,"command_id":101,"is_enable":1,"failure_rate":0,"level":5,"training_partner_array":[1],"tips_event_partner_array":[],"params_inc_dec_info_array":[{"target_type":1,"value":30},{"target_type":3,"value":10},{"target_type":30,"value":5},{"target_type":10,"value":-21}]}],"disabled_command_ids":[],"available_continue_num":5,"available_free_continue_num":0,"free_continue_num":1,"free_continue_time":0,"race_entry_restriction":0},"races":{"history":[{"turn":12,"program_id":624,"running_style":1,"result_rank":1}],"conditions":[],"start_info":null},"response_status":{"unchecked_events":[]}}'
                ]),
                encoding="utf-8",
            )
            (debug_dir / "hachimi_exact_hooks.jsonl").write_text('{"debug":"hook"}', encoding="utf-8")

            # Make sure the Hachimi copy wins the mtime comparison.
            now = time.time()
            os.utime(stale_runtime, (now - 60, now - 60))
            os.utime(fresh_log, (now, now))

            class Recorder:
                output_dir = runtime_dir

            main.manual_career_recorder = Recorder()

            with patch("career_bot.learning._hachimi_capture_career_dirs", return_value=[hachimi_career_dir]):
                source = main.latest_manual_capture_source()
                synced = main.sync_latest_manual_capture_to_runtime()

            self.assertEqual(source["log"], fresh_log)
            rebuilt = json.loads(synced["log"].read_text(encoding="utf-8"))
            self.assertEqual(rebuilt["status"], "finished")
            self.assertEqual(rebuilt["final_turn"], 78)
            self.assertEqual(rebuilt["turns"][0]["selected_action"], "train")
            self.assertEqual((runtime_dir / "latest_manual_career_summary.json").read_text(encoding="utf-8"), '{"summary":"hachimi","career_key":"test-career"}')
            self.assertEqual((runtime_dir / "latest_manual_career_raw.json").read_text(encoding="utf-8"), '{"raw":"hachimi"}')
            self.assertEqual((runtime_dir / "hachimi_exact_hooks.jsonl").read_text(encoding="utf-8"), '{"debug":"hook"}')

    def test_manual_capture_source_prefers_hachimi_latest_over_summary_only_runtime_tie(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_dir = root / "runtime_manual"
            runtime_dir.mkdir(parents=True, exist_ok=True)
            (runtime_dir / "latest_manual_career_log.json").write_text('{"schema":"sweepy_hachimi_manual_career_summary_v1"}', encoding="utf-8")
            (runtime_dir / "latest_manual_career_summary.json").write_text('{"summary":"runtime"}', encoding="utf-8")
            (runtime_dir / "latest_manual_career_raw.json").write_text('{"raw":"runtime"}', encoding="utf-8")

            hachimi_career_dir = root / "hachimi" / "Career turn data"
            latest_dir = hachimi_career_dir / "_latest"
            latest_dir.mkdir(parents=True, exist_ok=True)
            fresh_log = latest_dir / "latest_manual_career_log.json"
            fresh_log.write_text('{"source":"hachimi"}', encoding="utf-8")
            (latest_dir / "latest_manual_career_summary.json").write_text('{"summary":"hachimi"}', encoding="utf-8")
            (latest_dir / "latest_manual_career_raw.json").write_text('{"raw":"hachimi"}', encoding="utf-8")

            now = time.time()
            for path in (
                runtime_dir / "latest_manual_career_log.json",
                runtime_dir / "latest_manual_career_summary.json",
                runtime_dir / "latest_manual_career_raw.json",
                fresh_log,
                latest_dir / "latest_manual_career_summary.json",
                latest_dir / "latest_manual_career_raw.json",
            ):
                os.utime(path, (now, now))

            class Recorder:
                output_dir = runtime_dir

            main.manual_career_recorder = Recorder()

            with patch("career_bot.learning._hachimi_capture_career_dirs", return_value=[hachimi_career_dir]):
                source = main.latest_manual_capture_source()

            self.assertEqual(source["log"], fresh_log)

    def test_login_reuses_cached_reusable_auth_profile_without_game_client_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp)
            auth_cfg = {
                "steam_id": "steam-123",
                "viewer_id": 456789,
                "udid": "12345678-1234-1234-1234-1234567890ab",
                "auth_key": "ab" * 48,
                "auth_key_len": 48,
                "app_ver": "1.0.0",
                "res_ver": "2",
                "device_id": "device-a",
                "device_name": "pc",
                "graphics_device_name": "gpu",
                "ip_address": "127.0.0.1",
                "platform_os_version": "windows",
                "locale": "JPN",
                "unity_ver": "2022.3.62f2",
            }
            created_cfgs = []

            class FakeClient:
                def __init__(self, cfg, trace_enabled=True):
                    created_cfgs.append(dict(cfg))
                    self.viewer_id = cfg.get("viewer_id")
                    self.udid_str = cfg.get("udid")
                    self.auth_key_hex = cfg.get("auth_key")
                    self.steam_id = str(cfg.get("steam_id") or "")
                    self.steam_ticket = cfg.get("steam_session_ticket")
                    self.device_id = cfg.get("device_id", "")
                    self.device_identity_mode = cfg.get("device_identity_mode", "")
                    self.device_identity_instance = cfg.get("device_identity_instance", "")
                    self.device_name = cfg.get("device_name", "")
                    self.graphics_device = cfg.get("graphics_device_name", "")
                    self.ip_address = cfg.get("ip_address", "")
                    self.platform_os = cfg.get("platform_os_version", "")
                    self.locale = cfg.get("locale", "JPN")
                    self.unity_ver = cfg.get("unity_ver", "")
                    self.app_ver = cfg.get("app_ver", "")
                    self.res_ver = cfg.get("res_ver", "")

                def login(self, max_retries=3):
                    return {"data": {}}

            with patch.object(main, "dev_runtime_dir", return_value=runtime_root):
                self.assertTrue(main.save_reusable_auth_profile(auth_cfg, "test"))
                main.pending_game_auth_config = {}

                with patch("uma_api.client.get_ticket", return_value=("steam-123", "fresh-ticket")), \
                     patch("uma_api.client.UmaClient", FakeClient), \
                     patch.object(main, "attach_turn_delay", side_effect=lambda client: client), \
                     patch.object(main, "build_dashboard_data", return_value={"success": True}), \
                     patch.object(main, "persist_dev_session_cache", return_value=True):
                    result = asyncio.run(main.login(main.LoginRequest(username="user", password="pass")))

            self.assertTrue(result["success"])
            self.assertEqual(len(created_cfgs), 1)
            self.assertEqual(created_cfgs[0]["viewer_id"], auth_cfg["viewer_id"])
            self.assertEqual(created_cfgs[0]["udid"], auth_cfg["udid"])
            self.assertEqual(created_cfgs[0]["auth_key"], auth_cfg["auth_key"])
            self.assertEqual(created_cfgs[0]["steam_id"], "steam-123")
            self.assertEqual(created_cfgs[0]["steam_session_ticket"], "fresh-ticket")

    def test_login_without_cached_reusable_auth_uses_headless_bootstrap_seed(self):
        created_cfgs = []

        class FakeClient:
            def __init__(self, cfg, trace_enabled=True):
                created_cfgs.append(dict(cfg))
                self.viewer_id = 456789
                self.udid_str = cfg.get("udid") or "12345678-1234-1234-1234-1234567890ab"
                self.auth_key_hex = "ab" * 48
                self.steam_id = str(cfg.get("steam_id") or "")
                self.steam_ticket = cfg.get("steam_session_ticket")
                self.device_id = cfg.get("device_id", "device")
                self.device_identity_mode = cfg.get("device_identity_mode", "")
                self.device_identity_instance = cfg.get("device_identity_instance", "")
                self.device_name = cfg.get("device_name", "System Product Name")
                self.graphics_device = cfg.get("graphics_device_name", "GPU")
                self.ip_address = cfg.get("ip_address", "127.0.0.1")
                self.platform_os = cfg.get("platform_os_version", "Windows")
                self.locale = cfg.get("locale", "JPN")
                self.unity_ver = cfg.get("unity_ver", "2022.3.62f2")
                self.app_ver = cfg.get("app_ver", "")
                self.res_ver = cfg.get("res_ver", "")

            def login(self, max_retries=3):
                return {"data": {}}

        with patch("uma_api.client.get_ticket", return_value=("steam-999", "fresh-ticket")), \
             patch.object(main, "reusable_auth_config_for_steam_id", return_value=None), \
             patch("uma_api.client.UmaClient", FakeClient), \
             patch.object(main, "attach_turn_delay", side_effect=lambda client: client), \
             patch.object(main, "build_dashboard_data", return_value={"success": True}), \
             patch.object(main, "persist_dev_session_cache", return_value=True), \
             patch.object(main, "save_reusable_auth_profile", return_value=True) as save_profile:
            result = asyncio.run(main.login(main.LoginRequest(username="user", password="pass")))

        self.assertTrue(result["success"])
        self.assertEqual(len(created_cfgs), 1)
        self.assertEqual(created_cfgs[0]["steam_id"], "steam-999")
        self.assertEqual(created_cfgs[0]["steam_session_ticket"], "fresh-ticket")
        self.assertTrue(created_cfgs[0]["app_ver"])
        self.assertTrue(created_cfgs[0]["res_ver"])
        self.assertEqual(created_cfgs[0]["locale"], "JPN")
        self.assertEqual(created_cfgs[0]["unity_ver"], "2022.3.62f2")
        save_profile.assert_called_once()

    def test_auth_refresh_uses_headless_reusable_auth_path_when_credentials_are_supplied(self):
        refreshed_cfg = {
            "steam_id": "steam-321",
            "viewer_id": 987654,
            "udid": "12345678-1234-1234-1234-1234567890ab",
            "auth_key": "cd" * 48,
            "app_ver": "1.0.0",
            "res_ver": "2",
        }

        with patch.object(main, "clear_dev_session_cache", return_value=None) as clear_cache, \
             patch.object(main, "refresh_reusable_auth_headlessly", return_value=refreshed_cfg) as headless_refresh, \
             patch.object(main, "refresh_auth_before_serving", return_value=True) as capture_refresh:
            result = asyncio.run(main.auth_refresh(main.LoginRequest(username="user", password="pass")))

        self.assertTrue(result["success"])
        self.assertEqual(result["mode"], "headless")
        clear_cache.assert_called_once()
        headless_refresh.assert_called_once()
        capture_refresh.assert_not_called()

    def test_restore_dev_session_cache_auto_refreshes_after_394(self):
        stale_cfg = {
            "steam_id": "steam-restore",
            "steam_session_ticket": "ticket-restore",
            "steam_password_seed": "",
            "viewer_id": 123456,
            "udid": "12345678-1234-1234-1234-1234567890ab",
            "auth_key": "ab" * 48,
            "auth_key_len": 48,
            "app_ver": "1.0.0",
            "res_ver": "2",
            "locale": "JPN",
            "unity_ver": "2022.3.62f2",
        }

        class FailingClient:
            def __init__(self, cfg, trace_enabled=True):
                self._sweepy_auth_config = dict(cfg)

            def login(self, max_retries=1):
                raise Exception("API error 394 on load/index")

        refreshed_client = SimpleNamespace(_sweepy_auth_config=dict(stale_cfg))

        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"SWEEPY_RUNTIME_DIR": tmp}, clear=False):
            cache_path = main.dev_session_cache_path()
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "saved_at": time.time(),
                        "client_config": stale_cfg,
                        "dashboard": {},
                        "selection": {"deck": None, "friend": None, "trainee": None, "veterans": []},
                    }
                ),
                encoding="utf-8",
            )

            with patch.object(main, "UmaClient", FailingClient), \
                 patch.object(main, "attach_turn_delay", side_effect=lambda client: client), \
                 patch.object(
                     main,
                     "rebuild_reusable_auth_from_cached_ticket",
                     return_value=(
                         dict(stale_cfg),
                         refreshed_client,
                         {"data": {}},
                     ),
                 ) as rebuild, \
                 patch.object(main, "build_dashboard_data", return_value={"account": {}, "parents": [], "decks": []}) as build_dashboard, \
                 patch.object(main, "persist_dev_session_cache", return_value=True) as persist_cache, \
                 patch.object(main, "save_reusable_auth_profile", return_value=True) as save_profile:
                restored = main.restore_dev_session_cache()

        self.assertTrue(restored)
        rebuild.assert_called_once()
        build_dashboard.assert_called_once()
        persist_cache.assert_called()
        save_profile.assert_called()

    def test_end_career_stops_runner_and_force_deletes_active_career(self):
        client = SimpleNamespace(
            finish_career=MagicMock(return_value={"response_code": 1, "data_headers": {"result_code": 1}, "data": {}}),
            call=MagicMock(return_value={"response_code": 1, "data_headers": {"result_code": 1}, "data": {}}),
        )
        main.active_client = client
        main.active_account = {"career": {"active": True, "turn": 42}}
        main.active_dashboard_data = {"account": dict(main.active_account)}

        with patch.object(main, "request_loop_stop") as stop_loop, \
             patch.object(main.career_runner, "stop") as stop_runner, \
             patch.object(main.career_runner, "snapshot", return_value={"running": False}), \
             patch.object(main, "loop_snapshot", return_value={"active": False}):
            result = asyncio.run(main.end_career(main.DeleteCareerRequest()))

        self.assertTrue(result["success"])
        stop_loop.assert_called_once()
        stop_runner.assert_called_once()
        client.finish_career.assert_called_once_with(current_turn=42, is_force_delete=True)
        client.call.assert_called_with('load/index')
        self.assertIsNone(main.active_account["career"])

    def test_end_career_falls_back_to_delete_when_finish_does_not_clear_server_state(self):
        client = SimpleNamespace(
            finish_career=MagicMock(return_value={"response_code": 1, "data_headers": {"result_code": 1}, "data": {}}),
            delete_career=MagicMock(return_value={"response_code": 1, "data_headers": {"result_code": 1}, "data": {}}),
            call=MagicMock(return_value={"response_code": 1, "data_headers": {"result_code": 1}, "data": {}}),
        )
        main.active_client = client
        main.active_account = {"career": {"active": True, "turn": 52}}
        main.active_dashboard_data = {"account": dict(main.active_account)}

        refreshed_accounts = [
            {"career": {"active": True, "turn": 52}},
            {"career": None},
        ]

        with patch.object(main, "request_loop_stop"), \
             patch.object(main.career_runner, "stop"), \
             patch.object(main.career_runner, "snapshot", return_value={"running": False}), \
             patch.object(main, "loop_snapshot", return_value={"active": False}), \
             patch.object(main, "_sync_account_from_load_index", side_effect=refreshed_accounts):
            result = asyncio.run(main.end_career(main.DeleteCareerRequest(current_turn=52)))

        self.assertTrue(result["success"])
        client.finish_career.assert_called_once_with(current_turn=52, is_force_delete=True)
        client.delete_career.assert_called_once_with(current_turn=52)
        self.assertIsNone(main.active_account["career"])

    def test_headless_auth_refresh_reuses_existing_account_identity_before_signup_fallback(self):
        created_cfgs = []
        existing_cfg = {
            "steam_id": "steam-555",
            "viewer_id": 162337796827,
            "udid": "12345678-1234-1234-1234-1234567890ab",
            "auth_key": "ab" * 48,
            "auth_key_len": 48,
            "device_id": "device-a",
            "device_name": "pc",
            "graphics_device_name": "gpu",
            "ip_address": "127.0.0.1",
            "platform_os_version": "windows",
            "locale": "JPN",
            "unity_ver": "2022.3.62f2",
            "app_ver": "1.0.0",
            "res_ver": "2",
        }

        class FakeSession:
            def close(self):
                return None

        class FakeClient:
            def __init__(self, cfg, trace_enabled=True):
                created_cfgs.append(dict(cfg))
                self.viewer_id = cfg.get("viewer_id")
                self.udid_str = cfg.get("udid")
                self.auth_key_hex = cfg.get("auth_key")
                self.steam_id = str(cfg.get("steam_id") or "")
                self.steam_ticket = cfg.get("steam_session_ticket")
                self.device_id = cfg.get("device_id", "")
                self.device_identity_mode = cfg.get("device_identity_mode", "")
                self.device_identity_instance = cfg.get("device_identity_instance", "")
                self.device_name = cfg.get("device_name", "System Product Name")
                self.graphics_device = cfg.get("graphics_device_name", "GPU")
                self.ip_address = cfg.get("ip_address", "127.0.0.1")
                self.platform_os = cfg.get("platform_os_version", "Windows")
                self.locale = cfg.get("locale", "JPN")
                self.unity_ver = cfg.get("unity_ver", "2022.3.62f2")
                self.app_ver = cfg.get("app_ver", "")
                self.res_ver = cfg.get("res_ver", "")
                self.session = FakeSession()

            def login(self, max_retries=3):
                return {"data": {}}

        with patch("uma_api.client.get_ticket", return_value=("steam-555", "fresh-ticket")), \
             patch.object(main, "reusable_auth_config_for_steam_id", side_effect=lambda sid, require_fresh=True: existing_cfg if not require_fresh else None), \
             patch("uma_api.client.UmaClient", FakeClient), \
             patch.object(main, "attach_turn_delay", side_effect=lambda client: client), \
             patch.object(main, "save_reusable_auth_profile", return_value=True):
            result = main.refresh_reusable_auth_headlessly(main.LoginRequest(username="user", password="pass"))

        self.assertEqual(result["viewer_id"], existing_cfg["viewer_id"])
        self.assertEqual(created_cfgs[0]["viewer_id"], existing_cfg["viewer_id"])
        self.assertEqual(created_cfgs[0]["auth_key"], existing_cfg["auth_key"])
        self.assertEqual(created_cfgs[0]["steam_session_ticket"], "fresh-ticket")

    def test_headless_auth_refresh_204_store_url_stops_before_signup_fallback(self):
        created_cfgs = []
        existing_cfg = {
            "steam_id": "steam-555",
            "viewer_id": 162337796827,
            "udid": "12345678-1234-1234-1234-1234567890ab",
            "auth_key": "ab" * 48,
            "auth_key_len": 48,
            "device_id": "device-a",
            "device_name": "pc",
            "graphics_device_name": "gpu",
            "ip_address": "127.0.0.1",
            "platform_os_version": "windows",
            "locale": "JPN",
            "unity_ver": "2022.3.62f2",
            "app_ver": "1.21.1",
            "res_ver": "10006200",
        }

        class FakeSession:
            def close(self):
                return None

        class FakeClient:
            def __init__(self, cfg, trace_enabled=True):
                created_cfgs.append(dict(cfg))
                self.session = FakeSession()

            def login(self, max_retries=3):
                raise Exception(
                    'API error 204 on tool/start_session: '
                    '{"endpoint": "tool/start_session", "response_code": 204, '
                    '"result_code": 204, "data_headers": {"viewer_id": 1, '
                    '"sid": "<redacted>", "servertime": 1, "result_code": 204, '
                    '"store_url": "https://example.com/update.html"}}'
                )

        with patch("uma_api.client.get_ticket", return_value=("steam-555", "fresh-ticket")), \
             patch.object(main, "reusable_auth_config_for_steam_id", side_effect=lambda sid, require_fresh=True: existing_cfg if not require_fresh else None), \
             patch("uma_api.client.UmaClient", FakeClient), \
             patch.object(main, "attach_turn_delay", side_effect=lambda client: client):
            with self.assertRaises(RuntimeError) as caught:
                main.refresh_reusable_auth_headlessly(main.LoginRequest(username="user", password="pass"))

        self.assertIn("Game client version is too old", str(caught.exception))
        self.assertIn("Retrying will not help", str(caught.exception))
        self.assertEqual(len(created_cfgs), 1)
        self.assertEqual(created_cfgs[0]["viewer_id"], existing_cfg["viewer_id"])

    def test_headless_auth_refresh_existing_501_does_not_signup_fallback(self):
        created_cfgs = []
        existing_cfg = {
            "steam_id": "steam-555",
            "viewer_id": 162337796827,
            "udid": "12345678-1234-1234-1234-1234567890ab",
            "auth_key": "ab" * 48,
            "auth_key_len": 48,
            "device_id": "device-a",
            "device_name": "pc",
            "graphics_device_name": "gpu",
            "ip_address": "127.0.0.1",
            "platform_os_version": "windows",
            "locale": "JPN",
            "unity_ver": "2022.3.62f2",
            "app_ver": "1.22.1",
            "res_ver": "10006400",
        }

        class FakeSession:
            def close(self):
                return None

        class FakeClient:
            def __init__(self, cfg, trace_enabled=True):
                created_cfgs.append(dict(cfg))
                self.session = FakeSession()

            def login(self, max_retries=3):
                raise Exception(
                    'API error 501 on tool/start_session: '
                    '{"endpoint": "tool/start_session", "response_code": 501, '
                    '"result_code": 501, "data_headers": {"viewer_id": 162337796827, '
                    '"sid": "<redacted>", "servertime": 1, "result_code": 501}}'
                )

        with patch("uma_api.client.get_ticket", return_value=("steam-555", "fresh-ticket")), \
             patch.object(main, "reusable_auth_config_for_steam_id", side_effect=lambda sid, require_fresh=True: existing_cfg if not require_fresh else None), \
             patch("uma_api.client.UmaClient", FakeClient), \
             patch.object(main, "attach_turn_delay", side_effect=lambda client: client):
            with self.assertRaises(Exception) as caught:
                main.refresh_reusable_auth_headlessly(main.LoginRequest(username="user", password="pass"))

        message = str(caught.exception)
        self.assertIn("will not call tool/signup", message)
        self.assertIn("Existing auth retry error", message)
        self.assertEqual(len(created_cfgs), 1)
        self.assertEqual(created_cfgs[0]["viewer_id"], existing_cfg["viewer_id"])

    def test_headless_auth_refresh_cached_ticket_without_identity_stops_before_signup(self):
        with patch.object(main, "reusable_auth_config_for_steam_id", return_value=None), \
             patch("uma_api.client.UmaClient") as fake_client:
            with self.assertRaises(Exception) as caught:
                main.refresh_reusable_auth_headlessly(SimpleNamespace(
                    steam_id="steam-555",
                    steam_session_ticket="ticket",
                    username="",
                    password="",
                    code="",
                    steam_app_id=main.APP_ID,
                ))

        self.assertIn("cannot bootstrap this account from only a cached Steam ticket", str(caught.exception))
        fake_client.assert_not_called()

    def test_signup_uses_server_preferred_country_instead_of_hardcoded_canada(self):
        client = object.__new__(uma_client.UmaClient)
        calls = []
        client.viewer_id = 0
        client.auth_key_hex = ""
        client.regen_sid = lambda: None
        client.save_config = lambda *args, **kwargs: None

        def fake_call(endpoint, payload=None):
            calls.append((endpoint, payload))
            if endpoint == "tool/pre_signup":
                return {
                    "data": {
                        "country_list": [
                            {"country": "United States", "country_type": 2},
                            {"country": "Canada", "country_type": 0},
                        ]
                    }
                }
            if endpoint == "tool/signup":
                return {"data": {}}
            return {"data": {}}

        client.call = fake_call
        client.signup()
        signup_payload = next(payload for endpoint, payload in calls if endpoint == "tool/signup")
        self.assertEqual(signup_payload["country"], "United States")

    def test_load_index_394_retries_with_server_provided_viewer_id(self):
        client = object.__new__(uma_client.UmaClient)
        client.viewer_id = 162337796827
        client.udid_str = "12345678-1234-1234-1234-1234567890ab"
        client.auth_key_hex = ""
        client.steam_id = "76561199499333399"
        client.steam_ticket = "ticket"
        client.device_id = "device-id"
        client.device_name = "System Product Name"
        client.graphics_device = "GPU"
        client.ip_address = "127.0.0.1"
        client.platform_os = "Windows"
        client.locale = "JPN"
        client.app_ver = "1.21.1"
        client.res_ver = "10006100"
        client.sid = bytes(16)
        client.api_log = lambda *args, **kwargs: None
        client.auth_bytes = lambda: b""
        client.regen_sid = MagicMock()
        client.common = lambda: {
            "viewer_id": client.viewer_id,
            "device": 4,
            "device_id": client.device_id,
            "device_name": client.device_name,
            "graphics_device_name": client.graphics_device,
            "ip_address": client.ip_address,
            "platform_os_version": client.platform_os,
            "carrier": "",
            "keychain": 0,
            "locale": client.locale,
            "button_info": "",
            "dmm_viewer_id": None,
            "dmm_onetime_token": None,
            "steam_id": client.steam_id,
            "steam_session_ticket": client.steam_ticket,
        }

        viewer_headers = []

        class FakeResponse:
            def __init__(self):
                self.status_code = 200
                self.text = "packed"

        class FakeSession:
            def post(self, url, data=None, headers=None, timeout=None):
                viewer_headers.append(str((headers or {}).get("ViewerID") or ""))
                return FakeResponse()

        client.session = FakeSession()

        unpack_responses = [
            {
                "response_code": 394,
                "data_headers": {
                    "viewer_id": 3080576358491,
                    "result_code": 394,
                },
            },
            {
                "response_code": 1,
                "data_headers": {
                    "viewer_id": 3080576358491,
                    "result_code": 1,
                },
                "data": {},
            },
        ]

        with patch.object(uma_client, "pack", return_value=b"body"), \
             patch.object(uma_client, "get_raw_udid", return_value=b"udid"), \
             patch.object(uma_client, "unpack", side_effect=unpack_responses):
            result = uma_client.UmaClient.call(client, "load/index", {"adid": ""})

        self.assertEqual(result["response_code"], 1)
        self.assertEqual(client.viewer_id, 3080576358491)
        self.assertEqual(viewer_headers, ["162337796827", "3080576358491"])
        client.regen_sid.assert_called_once()

    def test_single_mode_free_load_391_does_not_remap_viewer_id(self):
        client = object.__new__(uma_client.UmaClient)
        client.viewer_id = 162337796827
        client.udid_str = "12345678-1234-1234-1234-1234567890ab"
        client.auth_key_hex = ""
        client.steam_id = "76561199499333399"
        client.steam_ticket = "ticket"
        client.device_id = "device-id"
        client.device_name = "System Product Name"
        client.graphics_device = "GPU"
        client.ip_address = "127.0.0.1"
        client.platform_os = "Windows"
        client.locale = "JPN"
        client.app_ver = "1.21.1"
        client.res_ver = "10006100"
        client.sid = bytes(16)
        client.api_log = lambda *args, **kwargs: None
        client.auth_bytes = lambda: b""
        client.regen_sid = MagicMock()
        client.common = lambda: {
            "viewer_id": client.viewer_id,
            "device": 4,
            "device_id": client.device_id,
            "device_name": client.device_name,
            "graphics_device_name": client.graphics_device,
            "ip_address": client.ip_address,
            "platform_os_version": client.platform_os,
            "carrier": "",
            "keychain": 0,
            "locale": client.locale,
            "button_info": "",
            "dmm_viewer_id": None,
            "dmm_onetime_token": None,
            "steam_id": client.steam_id,
            "steam_session_ticket": client.steam_ticket,
        }

        viewer_headers = []

        class FakeResponse:
            def __init__(self):
                self.status_code = 200
                self.text = "packed"

        class FakeSession:
            def post(self, url, data=None, headers=None, timeout=None):
                viewer_headers.append(str((headers or {}).get("ViewerID") or ""))
                return FakeResponse()

        client.session = FakeSession()

        unpack_responses = [
            {
                "response_code": 391,
                "data_headers": {
                    "viewer_id": 3080576358491,
                    "result_code": 391,
                },
            },
        ]

        with patch.object(uma_client, "pack", return_value=b"body"), \
             patch.object(uma_client, "get_raw_udid", return_value=b"udid"), \
             patch.object(uma_client, "unpack", side_effect=unpack_responses):
            with self.assertRaises(uma_client.ApiCallError):
                uma_client.UmaClient.call(client, "single_mode_free/load", {})

        self.assertEqual(client.viewer_id, 162337796827)
        self.assertEqual(viewer_headers, ["162337796827"])
        client.regen_sid.assert_not_called()

    def test_race_end_391_does_not_remap_viewer_id(self):
        client = object.__new__(uma_client.UmaClient)
        client.viewer_id = 162337796827
        client.udid_str = "12345678-1234-1234-1234-1234567890ab"
        client.auth_key_hex = ""
        client.steam_id = "76561199499333399"
        client.steam_ticket = "ticket"
        client.device_id = "device-id"
        client.device_name = "System Product Name"
        client.graphics_device = "GPU"
        client.ip_address = "127.0.0.1"
        client.platform_os = "Windows"
        client.locale = "JPN"
        client.app_ver = "1.21.1"
        client.res_ver = "10006100"
        client.sid = bytes(16)
        client.api_log = lambda *args, **kwargs: None
        client.auth_bytes = lambda: b""
        client.regen_sid = MagicMock()
        client.common = lambda: {
            "viewer_id": client.viewer_id,
            "device": 4,
            "device_id": client.device_id,
            "device_name": client.device_name,
            "graphics_device_name": client.graphics_device,
            "ip_address": client.ip_address,
            "platform_os_version": client.platform_os,
            "carrier": "",
            "keychain": 0,
            "locale": client.locale,
            "button_info": "",
            "dmm_viewer_id": None,
            "dmm_onetime_token": None,
            "steam_id": client.steam_id,
            "steam_session_ticket": client.steam_ticket,
        }

        viewer_headers = []

        class FakeResponse:
            def __init__(self):
                self.status_code = 200
                self.text = "packed"

        class FakeSession:
            def post(self, url, data=None, headers=None, timeout=None):
                viewer_headers.append(str((headers or {}).get("ViewerID") or ""))
                return FakeResponse()

        client.session = FakeSession()

        unpack_responses = [
            {
                "response_code": 391,
                "data_headers": {
                    "viewer_id": 3080576358491,
                    "result_code": 391,
                },
            },
        ]

        with patch.object(uma_client, "pack", return_value=b"body"), \
             patch.object(uma_client, "get_raw_udid", return_value=b"udid"), \
             patch.object(uma_client, "unpack", side_effect=unpack_responses):
            with self.assertRaises(uma_client.ApiCallError):
                uma_client.UmaClient.call(client, "single_mode_free/race_end", {"current_turn": 67})

        self.assertEqual(client.viewer_id, 162337796827)
        self.assertEqual(viewer_headers, ["162337796827"])
        client.regen_sid.assert_not_called()

    def test_exec_command_391_does_not_remap_viewer_id(self):
        client = object.__new__(uma_client.UmaClient)
        client.viewer_id = 162337796827
        client.udid_str = "12345678-1234-1234-1234-1234567890ab"
        client.auth_key_hex = ""
        client.steam_id = "76561199499333399"
        client.steam_ticket = "ticket"
        client.device_id = "device-id"
        client.device_name = "System Product Name"
        client.graphics_device = "GPU"
        client.ip_address = "127.0.0.1"
        client.platform_os = "Windows"
        client.locale = "JPN"
        client.app_ver = "1.21.1"
        client.res_ver = "10006100"
        client.sid = bytes(16)
        client.api_log = lambda *args, **kwargs: None
        client.auth_bytes = lambda: b""
        client.regen_sid = MagicMock()
        client.common = lambda: {
            "viewer_id": client.viewer_id,
            "device": 4,
            "device_id": client.device_id,
            "device_name": client.device_name,
            "graphics_device_name": client.graphics_device,
            "ip_address": client.ip_address,
            "platform_os_version": client.platform_os,
            "carrier": "",
            "keychain": 0,
            "locale": client.locale,
            "button_info": "",
            "dmm_viewer_id": None,
            "dmm_onetime_token": None,
            "steam_id": client.steam_id,
            "steam_session_ticket": client.steam_ticket,
        }

        viewer_headers = []

        class FakeResponse:
            def __init__(self):
                self.status_code = 200
                self.text = "packed"

        class FakeSession:
            def post(self, url, data=None, headers=None, timeout=None):
                viewer_headers.append(str((headers or {}).get("ViewerID") or ""))
                return FakeResponse()

        client.session = FakeSession()

        unpack_responses = [
            {
                "response_code": 391,
                "data_headers": {
                    "viewer_id": 3080576358491,
                    "result_code": 391,
                },
            },
        ]

        with patch.object(uma_client, "pack", return_value=b"body"), \
             patch.object(uma_client, "get_raw_udid", return_value=b"udid"), \
             patch.object(uma_client, "unpack", side_effect=unpack_responses):
            with self.assertRaises(uma_client.ApiCallError):
                uma_client.UmaClient.call(
                    client,
                    "single_mode_free/exec_command",
                    {
                        "command_type": 1,
                        "command_id": 105,
                        "command_group_id": 0,
                        "select_id": 0,
                        "current_turn": 52,
                        "current_vital": 41,
                    },
                )

        self.assertEqual(client.viewer_id, 162337796827)
        self.assertEqual(viewer_headers, ["162337796827"])
        client.regen_sid.assert_not_called()

    def test_borrow_fallback_error_when_borrows_exhausted_without_owned_parent_two(self):
        req = main.RunCareerRequest(
            parent_id_1=116,
            parent_id_2=0,
            rental_viewer_id=598816938787,
            rental_trained_chara_id=4246,
            borrow_fallback_id=0,
        )

        with patch.object(main, "compute_borrow_quota", return_value={"remaining": 0, "max": 5}):
            error = main.borrow_fallback_start_error(req)

        self.assertIn("Daily borrows are exhausted", error)
        self.assertIn("Fallback when out of borrows", error)

    def test_start_career_from_request_stops_before_api_when_borrows_exhausted_without_fallback(self):
        req = main.RunCareerRequest(
            card_id=100601,
            support_card_ids=[20031, 20008, 20012, 20020, 20015],
            friend_viewer_id=122893181280,
            friend_card_id=30078,
            parent_id_1=116,
            parent_id_2=0,
            rental_viewer_id=598816938787,
            rental_trained_chara_id=4246,
            borrow_fallback_id=0,
            scenario_id=4,
            deck_id=6,
            use_tp=30,
        )

        client = SimpleNamespace(start_career=MagicMock())
        main.active_client = client
        main.active_start_state = {"tp_info": {"current_tp": 54, "max_tp": 100}, "current_money": 767540}
        main.active_dashboard_data = {
            "decks": [{
                "id": 6,
                "cards": [{"id": 20031}, {"id": 20008}, {"id": 20012}, {"id": 20020}, {"id": 20015}],
            }],
            "umas": [{"id": 100601}],
            "parents": [{"instance_id": 116}],
            "supports": [{"id": 20031}, {"id": 20008}, {"id": 20012}, {"id": 20020}, {"id": 20015}],
            "friends": [{"viewer_id": 122893181280, "support_card_id": 30078}],
        }

        with patch.object(main, "refresh_live_start_state", return_value={"success": True, "career_active": False, "dashboard": main.active_dashboard_data}), \
             patch.object(main, "compute_borrow_quota", return_value={"remaining": 0, "max": 5}), \
             patch.object(main, "apply_tp_timer_to_cached_state", return_value={"current_tp": 54, "max_tp": 100}), \
             patch.object(main, "selected_succession_rank_point", return_value=62), \
             patch.object(main, "build_start_payload_preview", return_value={"preview": True}):
            result = main.start_career_from_request(req)

        self.assertFalse(result["success"])
        self.assertIn("Daily borrows are exhausted", result["detail"])
        client.start_career.assert_not_called()

    def test_loop_tp_wait_returns_when_toughness_resource_is_ready(self):
        class Client:
            def call(self, endpoint, args=None):
                return {
                    "data": {
                        "tp_info": {"current_tp": 0, "max_tp": 100, "max_recovery_time": 0},
                        "coin_info": {"fcoin": 0, "coin": 0},
                        "item_list": [{"item_id": 32, "number": 1}],
                    }
                }

        main.active_client = Client()
        main.active_dashboard_data = {}
        main.reset_loop_state()

        result = main.wait_for_loop_tp(main.RunCareerRequest(use_tp=30, allow_recover_tp=2))

        self.assertTrue(result)
        self.assertIn("TP recovery resource ready", main.loop_snapshot()["last_message"])

    def test_dev_reload_endpoint_rejects_active_runner(self):
        with patch.object(main, "runner_is_active", return_value=True):
            result = asyncio.run(main.dev_reload())

        self.assertFalse(result["success"])
        self.assertIn("Stop the career runner", result["detail"])

    def test_dev_reload_endpoint_schedules_restart_when_idle(self):
        main.dev_reloader_state["restart_requested"] = False

        with patch.object(main, "runner_is_active", return_value=False), patch.object(main, "schedule_backend_restart", return_value=True) as schedule:
            result = asyncio.run(main.dev_reload())

        self.assertTrue(result["success"])
        self.assertIn("Page will reconnect automatically", result["detail"])
        schedule.assert_called_once_with("manual_backend_refresh")

    def test_git_auto_update_waits_for_idle_before_pull(self):
        main.git_auto_update_state["running"] = False
        with patch.object(main, "git_auto_update_enabled", return_value=True), \
             patch.object(main, "choose_git_auto_update_remote", return_value=("origin", "")), \
             patch.object(main, "choose_git_auto_update_branch", return_value=("main", "")), \
             patch.object(main, "run_git_command", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as git_cmd, \
             patch.object(main, "git_rev_parse", side_effect=[("aaa111", ""), ("bbb222", "")]), \
             patch.object(main, "git_worktree_dirty", return_value=(False, "")), \
             patch.object(main, "git_is_ancestor", return_value=True), \
             patch.object(main, "runner_is_active", return_value=True):
            result = main.perform_git_auto_update(manual=True)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "waiting_for_idle")
        self.assertTrue(main.git_auto_update_state["behind"])
        self.assertFalse(any(call.args[0][0] == "pull" for call in git_cmd.call_args_list))

    def test_git_auto_update_refuses_dirty_worktree(self):
        main.git_auto_update_state["running"] = False
        with patch.object(main, "git_auto_update_enabled", return_value=True), \
             patch.object(main, "choose_git_auto_update_remote", return_value=("origin", "")), \
             patch.object(main, "choose_git_auto_update_branch", return_value=("main", "")), \
             patch.object(main, "run_git_command", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as git_cmd, \
             patch.object(main, "git_rev_parse", side_effect=[("aaa111", ""), ("bbb222", "")]), \
             patch.object(main, "git_worktree_dirty", return_value=(True, "")), \
             patch.object(main, "git_is_ancestor", return_value=True):
            result = main.perform_git_auto_update(manual=True)

        self.assertFalse(result["success"])
        self.assertEqual(result["status"], "dirty_waiting")
        self.assertTrue(main.git_auto_update_state["dirty"])
        self.assertFalse(any(call.args[0][0] == "pull" for call in git_cmd.call_args_list))

    def test_git_auto_update_fast_forward_pulls_and_restarts_when_idle(self):
        main.git_auto_update_state["running"] = False
        main.dev_reloader_state["restart_requested"] = False
        with patch.object(main, "git_auto_update_enabled", return_value=True), \
             patch.object(main, "choose_git_auto_update_remote", return_value=("origin", "")), \
             patch.object(main, "choose_git_auto_update_branch", return_value=("main", "")), \
             patch.object(main, "run_git_command", return_value=SimpleNamespace(returncode=0, stdout="pulled", stderr="")) as git_cmd, \
             patch.object(main, "git_rev_parse", side_effect=[("aaa111", ""), ("bbb222", ""), ("bbb222", "")]), \
             patch.object(main, "git_worktree_dirty", return_value=(False, "")), \
             patch.object(main, "git_is_ancestor", return_value=True), \
             patch.object(main, "runner_is_active", return_value=False), \
             patch.object(main, "schedule_backend_restart", return_value=True) as schedule:
            result = main.perform_git_auto_update(manual=True)

        self.assertTrue(result["success"])
        self.assertEqual(result["status"], "updated")
        self.assertIn("backend restart queued", result["detail"])
        self.assertTrue(any(call.args[0][0] == "pull" for call in git_cmd.call_args_list))
        schedule.assert_called_once_with("git_auto_update", delay_sec=0.75)

    def test_manual_stop_releases_deferred_backend_restart(self):
        main.defer_backend_restart_until_manual_stop()

        main.request_loop_stop()

        self.assertEqual(main.dev_reloader_state["pending_restart_gate"], "manual_stop_only")
        self.assertEqual(main.dev_reloader_state["pending_restart_release"], "manual_stop")
        self.assertEqual(main.deferred_backend_restart_release_reason(), "manual_stop")

    def test_runner_error_does_not_release_deferred_backend_restart(self):
        main.defer_backend_restart_until_manual_stop()

        with patch.object(main.career_runner, "snapshot", return_value={"last_error": "boom"}):
            self.assertEqual(main.deferred_backend_restart_release_reason(), "")

        self.assertEqual(main.dev_reloader_state["pending_restart_release"], "")

    def test_starting_new_run_clears_manual_restart_release(self):
        main.defer_backend_restart_until_manual_stop()
        main.release_deferred_backend_restart_on_manual_stop()
        main.active_client = None

        result = main.start_career_runner_once(main.RunCareerRequest())

        self.assertFalse(result["success"])
        self.assertEqual(main.dev_reloader_state["pending_restart_gate"], "manual_stop_only")
        self.assertEqual(main.dev_reloader_state["pending_restart_release"], "")

    def test_deck_advice_endpoint_scores_synced_decks(self):
        main.deck_advice_cache["key"] = None
        main.deck_advice_cache["advice"] = None
        main.active_dashboard_data = {
            "decks": [
                {
                    "id": 5,
                    "name": "Mihono",
                    "cards": [
                        {"id": "20031", "name": "Power SR", "rarity": "SR", "type": "Power"},
                        {"id": "20007", "name": "Wit SR", "rarity": "SR", "type": "Wit"},
                        {"id": "20003", "name": "Speed SR", "rarity": "SR", "type": "Speed"},
                    ],
                }
            ],
            "supports": [
                {"id": "20031", "name": "Power SR", "rarity": "SR", "type": "Power", "limit_break_count": 4, "support_card_level": 45, "exp": 32000},
                {"id": "20007", "name": "Wit SR", "rarity": "SR", "type": "Wit", "limit_break_count": 3, "support_card_level": 40, "exp": 25000},
            ],
        }
        selection = {
            "deck": {"id": 5},
            "trainee": {"id": 900501, "name": "Oguri Cap"},
            "friend": {"support_card_id": 30123, "support_name": "Nice Nature"},
        }
        with patch.object(main, "active_selection", selection), patch.object(main, "build_deck_advice", return_value={"status": "optimal", "best_deck": {"deck_id": 5}}) as advice:
            result = asyncio.run(main.get_deck_advice(preset_name="xguri parent", deck_id=5))

        self.assertTrue(result["success"])
        self.assertEqual(result["advice"]["status"], "optimal")
        advice.assert_called_once()
        kwargs = advice.call_args.kwargs
        self.assertEqual(kwargs["available_supports"], main.active_dashboard_data["supports"])
        self.assertEqual(kwargs["current_deck"]["id"], 5)
        self.assertEqual(kwargs["trainee"]["name"], "Oguri Cap")
        self.assertEqual(kwargs["friend"]["support_name"], "Nice Nature")

    def test_deck_advice_endpoint_reuses_cached_result_for_same_request(self):
        main.deck_advice_cache["key"] = None
        main.deck_advice_cache["advice"] = None
        main.active_dashboard_data = {
            "decks": [
                {
                    "id": 5,
                    "name": "Mihono",
                    "cards": [
                        {"id": "20031", "name": "Power SR", "rarity": "SR", "type": "Power"},
                        {"id": "20007", "name": "Wit SR", "rarity": "SR", "type": "Wit"},
                        {"id": "20003", "name": "Speed SR", "rarity": "SR", "type": "Speed"},
                    ],
                }
            ],
            "supports": [
                {"id": "20031", "name": "Power SR", "rarity": "SR", "type": "Power", "limit_break_count": 4, "support_card_level": 45, "exp": 32000},
                {"id": "20007", "name": "Wit SR", "rarity": "SR", "type": "Wit", "limit_break_count": 3, "support_card_level": 40, "exp": 25000},
            ],
        }
        selection = {
            "deck": {"id": 5},
            "trainee": {"id": 900501, "name": "Oguri Cap"},
            "friend": {"support_card_id": 30123, "support_name": "Nice Nature"},
        }
        with patch.object(main, "active_selection", selection), patch.object(main, "build_deck_advice", return_value={"status": "optimal", "best_deck": {"deck_id": 5}}) as advice:
            first = asyncio.run(main.get_deck_advice(preset_name="xguri parent", deck_id=5))
            second = asyncio.run(main.get_deck_advice(preset_name="xguri parent", deck_id=5))

        self.assertTrue(first["success"])
        self.assertTrue(second["success"])
        self.assertEqual(first["advice"]["status"], "optimal")
        self.assertEqual(second["advice"]["status"], "optimal")
        advice.assert_called_once()

    def test_limit_break_all_supports_endpoint_uses_duplicate_stock(self):
        client = SimpleNamespace(
            cached_load_data={
                "support_card_list": [
                    {"support_card_id": 20031, "limit_break_count": 1, "stock": 2},
                    {"support_card_id": 20007, "limit_break_count": 4, "stock": 3},
                    {"support_card_id": 20009, "limit_break_count": 0, "stock": 0},
                ]
            },
            limit_break_support_card=MagicMock(),
        )
        main.active_client = client

        with patch.dict(main.support_map, {
                "20031": {"name": "Power SR", "rarity": "SR", "type": "Power"},
                "20007": {"name": "Wit SR", "rarity": "SR", "type": "Wit"},
                "20009": {"name": "Speed SR", "rarity": "SR", "type": "Speed"},
            }, clear=False), \
             patch.object(main.career_runner, "snapshot", return_value={"running": False}), \
             patch.object(main, "loop_snapshot", return_value={"active": False}), \
             patch.object(main, "reload_dashboard_state_from_server", return_value={"success": True, "supports": []}) as refresh:
            result = asyncio.run(main.limit_break_all_supports())

        self.assertTrue(result["success"])
        self.assertEqual(result["cards_updated"], 1)
        self.assertEqual(result["total_steps_applied"], 2)
        self.assertEqual(
            client.limit_break_support_card.call_args_list,
            [
                unittest.mock.call(support_card_id=20031, material_support_card_num=1),
                unittest.mock.call(support_card_id=20031, material_support_card_num=1),
            ],
        )
        self.assertEqual(refresh.call_count, 2)

    def test_instance_bind_helpers_use_env_overrides(self):
        with patch.dict(
            "os.environ",
            {
                "SWEEPY_INSTANCE_NAME": "account_b",
                "SWEEPY_HOST": "127.0.0.1",
                "SWEEPY_PORT": "1717",
            },
            clear=False,
        ):
            self.assertEqual(main.sweepy_instance_name(), "account_b")
            self.assertEqual(main.sweepy_bind_host(), "127.0.0.1")
            self.assertEqual(main.sweepy_bind_port(), 1717)

    def test_dev_version_exposes_instance_metadata(self):
        with patch.dict(
            "os.environ",
            {
                "SWEEPY_INSTANCE_NAME": "account_a",
                "SWEEPY_PORT": "1616",
                "SWEEPY_SHARED_RUNTIME_PATHS": r"C:\tmp\a;C:\tmp\b",
                "SWEEPY_INSTANCE_DEVICE_IDENTITY": "1",
                "SWEEPY_AUTH_CAPTURE_KILL_GAME": "0",
            },
            clear=True,
        ):
            result = asyncio.run(main.dev_version())

        self.assertTrue(result["success"])
        self.assertEqual(result["instance"]["name"], "account_a")
        self.assertEqual(result["instance"]["port"], 1616)
        self.assertIn("runtime_dir", result["instance"])
        self.assertTrue(result["instance"]["dual_mode"])
        self.assertFalse(result["instance"]["auth_capture_kill_game"])
        self.assertTrue(result["instance"]["instance_device_identity"])

    def test_auth_capture_leaves_game_running_by_default_in_dual_mode(self):
        with patch.dict(
            "os.environ",
            {
                "SWEEPY_INSTANCE_NAME": "account_a",
                "SWEEPY_SHARED_RUNTIME_PATHS": r"C:\tmp\a;C:\tmp\b",
            },
            clear=True,
        ):
            self.assertFalse(main.auth_capture_kill_game_enabled())

    def test_dual_instance_device_identity_is_stable_and_scoped(self):
        with patch.dict(
            "os.environ",
            {
                "SWEEPY_INSTANCE_NAME": "account_b",
                "SWEEPY_INSTANCE_DEVICE_IDENTITY": "1",
            },
            clear=True,
        ):
            first, mode_a = uma_client.resolve_device_id("base-device-id")
            second, mode_b = uma_client.resolve_device_id("base-device-id")

        self.assertEqual(mode_a, "instance_local")
        self.assertEqual(mode_b, "instance_local")
        self.assertEqual(first, second)
        self.assertNotEqual(first, "base-device-id")

    def test_dual_instance_device_identity_does_not_rehash_cached_value(self):
        with patch.dict(
            "os.environ",
            {
                "SWEEPY_INSTANCE_NAME": "account_b",
                "SWEEPY_INSTANCE_DEVICE_IDENTITY": "1",
            },
            clear=True,
        ):
            resolved, mode = uma_client.resolve_device_id(
                "cached-derived-id",
                stored_mode="instance_local",
                stored_instance_name="account_b",
            )

        self.assertEqual(resolved, "cached-derived-id")
        self.assertEqual(mode, "instance_local")

    def test_add_friend_by_id_follows_and_refreshes_lists(self):
        class Client:
            viewer_id = 111
            cached_load_data = {"common_define": {"max_follow_num": 20}, "bonus_follow_num": 1}

            def friend_search(self, viewer_id):
                return {
                    "data": {
                        "user_info_summary_list": [
                            {
                                "viewer_id": viewer_id,
                                "name": "Borrow Friend",
                                "support_card_id": 30078,
                                "friend_state": 0,
                                "user_support_card": {
                                    "support_card_id": 30078,
                                    "limit_break_count": 4,
                                    "exp": 118185,
                                },
                            }
                        ]
                    },
                    "_sweepy_payload_variant": {"trainer_id": viewer_id},
                }

            def friend_follow(self, viewer_id):
                return {
                    "data": {"friend_viewer_id": viewer_id},
                    "_sweepy_payload_variant": {"friend_viewer_id": viewer_id},
                }

            def friend_index(self):
                return {
                    "data": {
                        "friend_list": [
                            {
                                "friend_viewer_id": 999,
                                "state": 1,
                                "follow_time": "2026-05-16 02:03:04",
                            }
                        ],
                        "user_info_summary_list": [
                            {
                                "viewer_id": 999,
                                "name": "Borrow Friend",
                                "comment": "Borrow-ready",
                                "friend_state": 1,
                                "support_card_id": 30078,
                                "last_login_time": "2026-05-16 05:30:00",
                                "user_support_card": {
                                    "support_card_id": 30078,
                                    "limit_break_count": 4,
                                    "exp": 118185,
                                },
                            }
                        ],
                    }
                }

            def pre_single_mode(self, exclude_viewer_ids=None):
                return {
                    "data": {
                        "friend_support_card_data": {
                            "summary_user_info_array": [
                                {
                                    "viewer_id": 999,
                                    "name": "Borrow Friend",
                                    "support_card_id": 30078,
                                    "friend_state": 1,
                                    "user_support_card": {
                                        "support_card_id": 30078,
                                        "limit_break_count": 4,
                                        "exp": 118185,
                                    },
                                }
                            ],
                            "support_card_data_array": [
                                {
                                    "viewer_id": 999,
                                    "support_card_id": 30078,
                                    "exp": 118185,
                                    "limit_break_count": 4,
                                }
                            ],
                        }
                    }
                }

        main.active_client = Client()
        main.active_dashboard_data = {"decks": []}

        with patch.object(main, "compute_borrow_quota", return_value={"remaining": 5, "max": 5}), patch.object(main, "find_deck_rows", return_value=([], {})), patch.object(main, "deck_view_rows", return_value=[]):
            result = asyncio.run(main.add_friend_by_id(main.FriendIdRequest(viewer_id=999)))

        self.assertTrue(result["success"])
        self.assertFalse(result["already_followed"])
        self.assertEqual(result["profile"]["viewer_id"], 999)
        self.assertEqual(result["profile"]["name"], "Borrow Friend")
        self.assertEqual(result["search_payload_variant"], {"trainer_id": 999})
        self.assertEqual(result["follow_payload_variant"], {"friend_viewer_id": 999})
        self.assertEqual(len(result["friends"]), 1)
        self.assertEqual(len(result["friends_list"]), 1)
        self.assertEqual(result["friends"][0]["viewer_id"], 999)
        self.assertEqual(result["friends_list"][0]["viewer_id"], 999)
        self.assertEqual(result["follow_quota"], {"used": 1, "max": 21, "remaining": 20})
        self.assertIn("Followed Borrow Friend", result["detail"])
        self.assertEqual(len(result["search_variant_attempts"]), 0)

    def test_friend_search_falls_back_to_friend_viewer_id_variant_after_102(self):
        client = object.__new__(uma_client.UmaClient)
        calls = []

        def fake_call(endpoint, payload=None, quiet_result_codes=(), **kwargs):
            calls.append((endpoint, dict(payload or {}), tuple(quiet_result_codes)))
            if payload == {"trainer_id": 999}:
                raise uma_client.ApiCallError(
                    "API error 102 on friend/search",
                    endpoint="friend/search",
                    request_payload=dict(payload),
                    response_body={"response_code": 102, "data_headers": {"result_code": 102}},
                    result_code=102,
                    response_code=102,
                    req_id="req102",
                )
            return {"data": {"viewer_id": 999}}

        client.call = fake_call

        result = uma_client.UmaClient.friend_search(client, 999)

        self.assertEqual(calls[0], ("friend/search", {"trainer_id": 999}, (102,)))
        self.assertEqual(calls[1], ("friend/search", {"friend_viewer_id": 999}, (102,)))
        self.assertEqual(result["_sweepy_payload_variant"], {"friend_viewer_id": 999})
        self.assertEqual(len(result["_sweepy_variant_attempts"]), 1)
        self.assertEqual(result["_sweepy_variant_attempts"][0]["result_code"], 102)
        self.assertEqual(result["_sweepy_variant_attempts"][0]["payload"], {"trainer_id": 999})

    def test_unfollow_friend_by_id_refreshes_following_list_and_quota(self):
        class Client:
            cached_load_data = {"common_define": {"max_follow_num": 20}}

            def friend_unfollow(self, viewer_id):
                return {
                    "data": {"friend_viewer_id": viewer_id},
                    "_sweepy_payload_variant": {"friend_viewer_id": viewer_id},
                }

            def friend_index(self):
                return {"data": {"friend_list": [], "user_info_summary_list": []}}

            def pre_single_mode(self, exclude_viewer_ids=None):
                return {"data": {"friend_support_card_data": {}}}

        main.active_client = Client()
        main.active_dashboard_data = {"decks": []}

        with patch.object(main, "compute_borrow_quota", return_value={"remaining": 5, "max": 5}), patch.object(main, "find_deck_rows", return_value=([], {})), patch.object(main, "deck_view_rows", return_value=[]):
            result = asyncio.run(main.unfollow_friend_by_id(main.FriendIdRequest(viewer_id=999)))

        self.assertTrue(result["success"])
        self.assertEqual(result["unfollow_payload_variant"], {"friend_viewer_id": 999})
        self.assertEqual(result["friends_list"], [])
        self.assertEqual(result["follow_quota"], {"used": 0, "max": 20, "remaining": 20})
        self.assertEqual(result["unfollowed_viewer_id"], 999)
        self.assertIn("Unfollowed trainer ID 999", result["detail"])

    def test_friend_force_refresh_bypasses_cached_borrows(self):
        class Client:
            cached_load_data = {"common_define": {"max_follow_num": 20}}

            def __init__(self):
                self.pre_single_calls = 0

            def pre_single_mode(self, exclude_viewer_ids=None):
                self.pre_single_calls += 1
                return {
                    "data": {
                        "friend_support_card_data": {
                            "summary_user_info_array": [
                                {
                                    "viewer_id": 999,
                                    "name": "Fresh Borrow",
                                    "support_card_id": 30078,
                                    "friend_state": 1,
                                    "user_support_card": {
                                        "support_card_id": 30078,
                                        "limit_break_count": 4,
                                    },
                                }
                            ],
                            "support_card_data_array": [
                                {
                                    "viewer_id": 999,
                                    "support_card_id": 30078,
                                    "limit_break_count": 4,
                                }
                            ],
                        }
                    }
                }

            def friend_index(self):
                return {"data": {"friend_list": [], "user_info_summary_list": []}}

        client = Client()
        main.active_client = client
        main.active_dashboard_data = {"friends": [], "borrow_umas": [], "decks": []}

        with patch.object(main, "compute_borrow_quota", return_value={"remaining": 5, "max": 5}), \
             patch.object(main, "find_deck_rows", return_value=([], {})), \
             patch.object(main, "deck_view_rows", return_value=[]):
            cached = asyncio.run(main.get_friend_list(main.FriendListRequest()))
            refreshed = asyncio.run(main.get_friend_list(main.FriendListRequest(force_refresh=True)))

        self.assertTrue(cached["success"])
        self.assertEqual(cached["source"], "cache")
        self.assertEqual(client.pre_single_calls, 1)
        self.assertTrue(refreshed["success"])
        self.assertEqual(refreshed["friends"][0]["name"], "Fresh Borrow")

    def test_team_trials_live_probe_not_blocked_by_running_loop(self):
        main.active_client = object()
        with patch.object(main.career_runner, "snapshot", return_value={"running": True}), \
             patch.object(main, "loop_snapshot", return_value={"active": True}):
            self.assertEqual(main._live_probe_blocked(), "")

    def test_save_deck_refreshes_dashboard_when_missing(self):
        main.active_client = object()
        main.active_dashboard_data = None
        dashboard = {
            "supports": [{"id": 30078, "support_card_id": 30078, "name": "Borrowable Speed", "type": "Speed", "rarity": "SSR"}],
            "decks": [],
        }
        with patch.object(main, "reload_dashboard_state_from_server", return_value=dashboard) as reload_dashboard, \
             patch.object(main, "load_deck_overrides", return_value={"decks": {}}), \
             patch.object(main, "save_deck_overrides", return_value=None), \
             patch.object(main, "persist_dev_session_cache", return_value=None):
            result = asyncio.run(main.save_deck(main.SaveDeckRequest(deck_id=1, support_card_ids=[30078], name="Edited")))

        self.assertTrue(result["success"])
        reload_dashboard.assert_called_once()
        self.assertEqual(result["deck"]["name"], "Edited")
        self.assertEqual(result["deck"]["support_card_ids"], [30078])

    def test_add_friend_search_failure_writes_diagnostic_snapshot(self):
        class Client:
            viewer_id = 111
            cached_load_data = {"common_define": {"max_follow_num": 20}}

            def friend_search(self, viewer_id):
                raise uma_client.ApiCallError(
                    "API error 102 on friend/search",
                    endpoint="friend/search",
                    request_payload={
                        "payload_variants": [{"trainer_id": viewer_id}, {"friend_viewer_id": viewer_id}],
                        "variant_attempts": [
                            {
                                "payload": {"trainer_id": viewer_id},
                                "result_code": 102,
                                "response_code": 102,
                                "message": "API error 102 on friend/search",
                            }
                        ],
                    },
                    response_body={"response_code": 102, "data_headers": {"result_code": 102}},
                    result_code=102,
                    response_code=102,
                    req_id="friend102",
                )

        main.active_client = Client()
        main.active_dashboard_data = {"friendsList": [], "friends": [], "borrow_umas": []}

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            "os.environ",
            {"UMA_RUNTIME_DIR": tmp},
            clear=False,
        ):
            result = asyncio.run(main.add_friend_by_id(main.FriendIdRequest(viewer_id=999)))
            self.assertFalse(result["success"])
            self.assertIn("snapshot", result)
            snapshot_path = Path(result["snapshot"])
            self.assertTrue(snapshot_path.exists())
            payload = json.loads(snapshot_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["category"], "friend_search")
        self.assertEqual(payload["request"]["requested_viewer_id"], 999)
        self.assertEqual(payload["error"]["result_code"], 102)
        self.assertEqual(payload["error"]["variant_attempts"][0]["payload"], {"trainer_id": 999})

    def test_read_requested_preset_merges_instance_local_learning_overlay(self):
        from career_bot.presets import write_instance_learning_override

        class Store:
            def read_one(self, name):
                return {
                    "name": name,
                    "rest_threshold": 48,
                    "skill_profile_style": "late_surger",
                    "skill_profile_distance": "medium",
                    "learn_skill_blacklist": ["BaseOnly"],
                    "desired_parent_sparks": {"blue": ["Power"], "pink": [], "green": [], "white": []},
                }

        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "preset_store", Store()), patch.dict(
            "os.environ",
            {
                "SWEEPY_AUTO_LEARNING_SCOPE": "instance_local",
                "UMA_RUNTIME_DIR": tmp,
            },
            clear=False,
        ):
            write_instance_learning_override(
                main.DIR,
                "xguri parent",
                {
                    "name": "xguri parent",
                    "rest_threshold": 72,
                    "skill_profile_style": "front_runner",
                    "skill_profile_distance": "mile",
                    "learn_skill_blacklist": ["OverlayShouldNotWin"],
                    "desired_parent_sparks": {"blue": ["Wit"], "pink": [], "green": [], "white": []},
                },
            )
            preset, detail = main.read_requested_preset(main.RunCareerRequest(preset_name="xguri parent"))

        self.assertIsNone(detail)
        self.assertEqual(preset["rest_threshold"], 72)
        self.assertEqual(preset["skill_profile_style"], "late_surger")
        self.assertEqual(preset["skill_profile_distance"], "medium")
        self.assertEqual(preset["learn_skill_blacklist"], ["BaseOnly"])
        self.assertEqual(preset["desired_parent_sparks"]["blue"], ["Power"])

    def test_planner_profile_save_and_load_round_trip(self):
        class Store:
            def __init__(self):
                self.requested = None
                self.written = None

            def read_one(self, name):
                self.requested = name
                return {"name": name, "skill_profile_style": "", "extra_race_list": []}

            def write(self, preset):
                self.written = dict(preset)
                return self.written

        race_id = next(iter(sorted(main.race_catalog.by_id.keys())))
        store = Store()
        profile_name = "SR Power Parent Farm"
        raw_profile = {
            "name": profile_name,
            "skill_plan": {
                "style": "pace chaser",
                "distance": "mile",
                "buy_timing": "throughout",
                "alarm_clock_mode": "carats",
                "alarm_clock_limit": 3,
                "final_priorities": ["Groundwork", "Corner Adept"],
                "blacklist": ["Nonstop Girl"],
                "desired_sparks": {
                    "blue": ["Power"],
                    "pink": ["Mile"],
                    "green": ["Victory Shot!"],
                    "white": ["NHK Mile C."],
                },
            },
            "race_scheduler": {
                "race_plan_text": "Classic Year Late Oct @ Kikuka Sho | late surger",
                "selected_race_ids": [race_id],
                "race_styles": {str(race_id): "late_surger"},
            },
        }

        with tempfile.TemporaryDirectory() as tmp, patch.object(main, "preset_store", store), patch.object(
            main,
            "planner_profiles_dir",
            return_value=Path(tmp),
        ):
            saved = asyncio.run(
                main.save_planner_profile(
                    main.SavePlannerProfileRequest(
                        preset_name="custom parent preset",
                        profile_name=profile_name,
                        profile=raw_profile,
                    )
                )
            )
            loaded = asyncio.run(
                main.load_planner_profile(
                    main.LoadPlannerProfileRequest(
                        preset_name="custom parent preset",
                        profile_name=profile_name,
                    )
                )
            )

        self.assertTrue(saved["success"])
        self.assertTrue(loaded["success"])
        self.assertEqual(store.requested, "custom parent preset")
        self.assertEqual(store.written["skill_profile_style"], "pace_chaser")
        self.assertEqual(store.written["skill_profile_distance"], "mile")
        self.assertFalse(store.written["manual_purchase_at_end"])
        self.assertEqual(store.written["alarm_clock_mode"], "carats")
        self.assertEqual(store.written["alarm_clock_use_limit"], 3)
        self.assertEqual(store.written["desired_parent_sparks"]["blue"], ["Power"])
        self.assertEqual(store.written["race_plan_text"], "Classic Year Late Oct @ Kikuka Sho | late surger")
        self.assertIn(race_id, store.written["extra_race_list"])
        self.assertEqual(store.written["custom_race_schedule"][0]["style"], "late_surger")


if __name__ == "__main__":
    unittest.main()
