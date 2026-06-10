import threading
import time
import json
import os
import sys
import traceback
import copy
from datetime import datetime
from pathlib import Path

from career_bot.scenarios.mant import MantStrategy
from career_bot.races import RacePlanner
from career_bot.race_schedule import TACTIC_TO_STYLE, STYLE_TO_TACTIC
from career_bot.skills import SkillBuyer
from career_bot.items import MantItemManager, ITEM_NAMES, SHOP_ITEM_COSTS, DISPLAY_TO_ID, display_to_slug
from career_bot.mant_fixed_events import career_turn_calendar, career_turn_label, static_mant_event_for_story


from career_bot.report import new_report, add_event, add_decision, finish_report, write_report, set_error


STRATEGIES = {
    4: MantStrategy,
}

# Continue type 1 is the daily free retry. Type 2 consumes an available alarm
# clock retry, including clocks obtained through the client-side carat exchange.
# Type 3 is a legacy direct-carat hypothesis and is disabled unless explicitly
# enabled because live traces show carats use /item/exchange followed by type 2.
DEFAULT_FREE_CONTINUE_TYPE = 1
DEFAULT_CLOCK_CONTINUE_TYPE = 2
DEFAULT_CARAT_CONTINUE_TYPE = 3
DEFAULT_ALARM_CLOCK_EXCHANGE_ID = 9001
DEFAULT_ALARM_CLOCK_ITEM_ID = 95
DEFAULT_ALARM_CLOCK_CARAT_COST = 10


def runtime_output_root(base_dir):
    override = os.environ.get("UMA_RUNTIME_DIR")
    if override:
        return Path(override).expanduser().resolve()

    base = Path(base_dir).resolve()
    for candidate in (base, *base.parents):
        if (candidate / ".git").exists():
            return candidate / "uma_runtime"
    return base.parent / "uma_runtime"

TRAINING_LABELS = {
    101: "Speed",
    102: "Power",
    103: "Guts",
    105: "Stamina",
    106: "Wit",
    601: "Speed",
    602: "Stamina",
    603: "Power",
    604: "Guts",
    605: "Wit",
}

TRAINING_COMMANDS = {101: 0, 105: 1, 102: 2, 103: 3, 106: 4, 601: 0, 602: 1, 603: 2, 604: 3, 605: 4}

DECK_PARTNER_IDS = {1, 2, 3, 4, 5, 6}

STAT_TARGET_NAMES = {
    1: "speed",
    2: "stamina",
    3: "power",
    4: "guts",
    5: "wit",
    6: "skill_point",
    10: "hp",
    30: "skill_point",
}

STAT_FALLBACK_FIELDS = {
    "speed": ("speed",),
    "stamina": ("stamina",),
    "power": ("power",),
    "guts": ("guts",),
    "wit": ("wiz", "wit"),
    "skill_point": ("skill_point", "lp"),
}


class CareerRunner:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.report = None
        self.lock = threading.Lock()
        self.thread = None
        self.stop_requested = False
        self.race_planner = RacePlanner(base_dir)
        self.skill_buyer = SkillBuyer(base_dir)
        self.item_manager = MantItemManager()
        self.stamina_rescue_attempts = set()
        self.kikuka_front_guard_attempts = set()
        self.calendar_prebuy_attempts = set()
        self.race_style_context = {}
        self.status = {
            "running": False,
            "preset": "",
            "scenario_id": 0,
            "loop_mode": False,
            "turn": 0,
            "current_card_id": 0,
            "current_stats": {},
            "steps": 0,
            "last_action": "",
            "last_error": "",
            "finished": False,
            "final_fans": 0,
            "post_run_processing": False,
            "post_run_stage": "",
            "skills_bought": 0,
            "items_bought": 0,
            "items_used": 0,
            "race_retries": 0,
            "free_race_retries": 0,
            "alarm_clocks_used": 0,
            "carat_race_retries": 0,
            "disabled_continue_resources": [],
            "log": [],
            "action_history": [],
        }

    def _init_debug_log(self, preset=None, scenario_id=4):
        self.report = new_report(preset, scenario_id)

    def _debug(self, event, state=None, data=None):
        row = {
            "event": event,
        }
        if state:
            d = state.get("data") or {}
            chara = d.get("chara_info") or {}
            free = d.get("free_data_set") or {}
            row["turn"] = int(chara.get("turn") or 0)
            row["skill_point"] = int(chara.get("skill_point") or 0)
            row["mant_coin"] = int(free.get("coin_num") if free.get("coin_num") is not None else free.get("gained_coin_num") or 0)
            row["motivation"] = int(chara.get("motivation") or 0)
            row["stats"] = self._turn_stats(chara)
        if data:
            row.update(data)
        if self.report:
            add_event(self.report, row)

    def start(self, client, preset, initial_result, max_steps=2500):
        with self.lock:
            if self.status["running"]:
                raise RuntimeError("Career runner already active")
            scenario_id = int(preset.get("scenario_id") or 4)
            strategy_cls = STRATEGIES.get(scenario_id)
            if not strategy_cls:
                raise RuntimeError(f"No runner for scenario {scenario_id}")
            self.stop_requested = False
            self.status = {
                "running": True,
                "preset": preset.get("name", ""),
                "scenario_id": scenario_id,
                "loop_mode": bool(preset.get("_loop_mode")),
                "turn": 0,
                "current_card_id": 0,
                "current_stats": {},
                "steps": 0,
                "last_action": "started",
                "last_error": "",
                "finished": False,
                "final_fans": 0,
                "post_run_processing": False,
                "post_run_stage": "",
                "skills_bought": 0,
                "items_bought": 0,
                "items_used": 0,
                "race_retries": 0,
                "free_race_retries": 0,
                "alarm_clocks_used": 0,
                "carat_race_retries": 0,
                "disabled_continue_resources": [],
                "log": [],
                "action_history": [],
            }
            self.report = new_report(preset, scenario_id)
            if client:
                client.report = self.report
            if hasattr(self.race_planner, "rejected"):
                self.race_planner.rejected.clear()
            self.stamina_rescue_attempts.clear()
            self.kikuka_front_guard_attempts.clear()
            self.calendar_prebuy_attempts.clear()
            # Reset career-scoped fail-tracking on the skill buyer so a previous
            # career's "permanent" 205-rejected skills don't carry over and
            # silently get skipped in the new career.
            if hasattr(self.skill_buyer, 'reset_career_scoped_failures'):
                self.skill_buyer.reset_career_scoped_failures()
            if hasattr(self.item_manager, 'reset_career_scoped_failures'):
                # Wipe persistent_failed_exchange_item_ids so a prior career's
                # rejected shop items don't get carried over and silently
                # skipped this career.
                self.item_manager.reset_career_scoped_failures()
            self._log_locked("started", 0, f"preset {preset.get('name', '')}")
            # Save a reference to the active preset dict so the preset-file
            # hot-reloader can mutate it in place while the runner is mid-career
            self._active_preset = preset
            self._active_preset_name = str(preset.get('name') or '').strip().lower()
            self.thread = threading.Thread(target=self._run, args=(client, preset, initial_result, strategy_cls(self.race_planner), max_steps), daemon=True)
            self.thread.start()

    def update_active_preset(self, preset_name, new_preset_dict):
        """Hot-replace the active preset's contents while the runner is alive.
        Returns True if the runner was using this preset and got updated."""
        if not isinstance(new_preset_dict, dict):
            return False
        with self.lock:
            if not self.status.get("running"):
                return False
            wanted = str(preset_name or '').strip().lower()
            current = getattr(self, '_active_preset_name', '')
            if wanted != current:
                return False
            active = getattr(self, '_active_preset', None)
            if not isinstance(active, dict):
                return False
            transient = {
                key: value
                for key, value in active.items()
                if str(key).startswith("_") and key not in new_preset_dict
            }
            # Mutate in place so the runner thread + strategy keep the same
            # object reference but see the new values immediately.
            active.clear()
            active.update(new_preset_dict)
            active.update(transient)
            self.status["loop_mode"] = bool(
                self.status.get("loop_mode")
                or active.get("_loop_mode")
            )
            return True

    def stop(self):
        with self.lock:
            self.stop_requested = True

    def snapshot(self):
        with self.lock:
            return dict(self.status)

    def _loop_mode_active(self, preset=None):
        if isinstance(preset, dict) and preset.get("_loop_mode"):
            return True
        with self.lock:
            if self.status.get("loop_mode"):
                return True
        active = getattr(self, "_active_preset", None)
        return bool(isinstance(active, dict) and active.get("_loop_mode"))

    def _run(self, client, preset, result, strategy, max_steps):

        state = result or {}
        last_turn = -1
        # Watchdog: if the strategy keeps returning settle_state on the
        # same turn, the game is wedged and `_settle_state` may not be
        # tripping its stop condition (fresh state oscillates between
        # "post-action no race" and "looks fine but no actionable
        # commands"). Force-release after 5 consecutive settle_states
        # on the same turn so the loop can move to the next career.
        consecutive_settle = 0
        consecutive_settle_turn = -1
        try:
            for i in range(max_steps):
                if self._should_stop():
                    break
                data = state.get("data") or {}
                chara = data.get("chara_info") or {}
                turn = int(chara.get("turn") or 0)

                if turn != last_turn:
                    if hasattr(client, "wait_turn_delay"):
                        client.wait_turn_delay()
                    last_turn = turn
                
                self._mark(
                    turn=turn,
                    current_card_id=self._safe_int(chara.get("card_id")),
                    current_stats=self._turn_stats(chara),
                )
                self._track_turn_scores(state)

                if turn == 77 and not self._loop_mode_active(preset):
                    print("Turn 77 reached terminating", flush=True)
                    self.stop()
                    break
                
                # Reset transient results before each turn loop to prevent log contamination
                self.skill_buyer.last_attempt = []
                self.skill_buyer.last_result = {}
                self.item_manager.last_buy_attempt = []
                self.item_manager.last_buy_result = {}
                self.item_manager.last_use_attempt = []
                self.item_manager.last_use_result = {}
                self.item_manager.last_use_decision_rationale = {}
                self.skill_buyer.attempt_events = []
                self.item_manager.buy_attempt_events = []
                self.item_manager.use_attempt_events = []

                if data.get("unchecked_event_array"):

                    state = self._drain_events(client, strategy, state)
                    data = state.get("data") or {}
                    chara = data.get("chara_info") or {}
                    self._track_turn_scores(state)
                
                if self._blocked_playing_state(chara):

                    state = self._recover_blocked_state(client, strategy, state)
                    data = state.get("data") or {}
                    chara = data.get("chara_info") or {}
                    if self._blocked_playing_state(chara):

                        self._mark(last_action=f"blocked state {chara.get('playing_state')}")
                        break

                state = self._maybe_buy_upcoming_stamina_skill(client, state, preset, strategy)
                data = state.get("data") or {}
                chara = data.get("chara_info") or {}
                
                self._debug_turn(state, preset)
                decision = strategy.next_decision(state, preset)

                
                if self.report:
                    add_decision(self.report, state, decision)
                
                if decision.action == "command":

                    state = self._handle_items(client, state, preset, self._command_from_decision(state, decision))
                    data = state.get("data") or {}
                    if data.get("unchecked_event_array"):

                        state = self._drain_events(client, strategy, state)
                    data = state.get("data") or {}
                    chara = data.get("chara_info") or {}
                    self._mark(
                        turn=chara.get("turn", 0),
                        current_card_id=self._safe_int(chara.get("card_id")),
                        current_stats=self._turn_stats(chara),
                    )
                    decision = strategy.next_decision(state, preset)

                    if self.report:
                        add_decision(self.report, state, decision)
                
                self._log(decision.action, chara.get("turn", 0), decision.reason)
                if decision.action == "idle":
                    self._mark(last_action=decision.reason)
                    break
                if decision.action == "done":
                    self._mark(last_action=decision.reason, finished=True)
                    break
                
                if decision.action == "settle_state":
                    current_settle_turn = int(chara.get("turn") or 0)
                    if current_settle_turn == consecutive_settle_turn:
                        consecutive_settle += 1
                    else:
                        consecutive_settle = 1
                        consecutive_settle_turn = current_settle_turn
                    if consecutive_settle >= 5:
                        detail = f"settle_state watchdog tripped after {consecutive_settle} attempts on turn {current_settle_turn}"
                        if self._loop_mode_active():
                            self._force_release_stuck_career(client, current_settle_turn, detail)
                        self._stop_for_state_block(current_settle_turn, detail)
                        break
                else:
                    consecutive_settle = 0
                    consecutive_settle_turn = -1

                if decision.action == "event":
                    state = self._event(client, strategy, decision.payload)
                elif decision.action == "settle_state":
                    state = self._settle_state(client, strategy, state, decision.payload)
                elif decision.action == "command":
                    self._log("command_exec", decision.payload.get("current_turn", 0), f"{decision.payload.get('command_type')}:{decision.payload.get('command_id')}:{decision.payload.get('command_group_id')}")
                    self._record_action(decision, chara)
                    state, command_executed = self._exec_command_with_recovery(
                        client,
                        strategy,
                        state,
                        decision.payload,
                        chara,
                    )
                    data = state.get("data") or {}
                    chara = data.get("chara_info") or {}
                    if self._blocked_playing_state(chara):
                        self._mark(last_action=f"blocked state {chara.get('playing_state')}")
                        break
                    if not command_executed:
                        continue
                    data = state.get("data") or {}
                    if data.get("unchecked_event_array"):
                        state = self._drain_events(client, strategy, state)
                elif decision.action == "race":

                    self._record_action(decision, chara)
                    state = self._race(client, state, preset, decision.payload)
                elif decision.action == "race_progress":

                    self._record_action(decision, chara)
                    state = self._race_progress(client, decision.payload, preset, strategy)
                elif decision.action == "finish":

                    self._record_action(decision, chara)
                    state = self._finish_career(client, state, preset, strategy, decision.payload.get("current_turn", 78))
                    break
                else:

                    self._mark(last_action=decision.action)
                    break

                if self.status.get("finished"):
                    break
                if self._should_stop():
                    break
                
                if decision.action not in {"finish"}:
                    # Buy skills during normal loop
                    state = self._buy_skills(client, state, preset, False)
                
                self._advance(decision.action)
                time.sleep(0.6)
        except Exception as exc:
            import traceback
            trace_str = traceback.format_exc()
            traceback.print_exc()
            print(f"RUNNER CRASH: {exc}")
            
            crash_log_path = runtime_output_root(self.base_dir) / "crash_trace.txt"
            try:
                crash_log_path.parent.mkdir(parents=True, exist_ok=True)
                with open(crash_log_path, "a", encoding="utf-8") as f:
                    f.write(f"--- CRASH AT {time.strftime('%Y-%m-%d %H:%M:%S')} ---\n")
                    f.write(trace_str)
                    f.write("\n\n")
            except Exception:
                pass

            self._log("error", self.snapshot().get("turn", 0), str(exc))
            self._mark(last_error=str(exc))
            if self.report:
                set_error(self.report, exc)
        finally:
            if self._should_stop():
                self._log("stop", self.snapshot().get("turn", 0), "stop requested")
                if self.report:
                    finish_report(self.report, "stopped")
            else:
                if self.report:
                    finish_report(self.report, "finished" if self.status["finished"] else "error")
            if self.report:
                runtime_root = None
                out = None
                released_for_next_run = False
                try:
                    self._mark_post_run_stage("writing career report")
                    report_snapshot = copy.deepcopy(self.report)
                    active_preset_snapshot = copy.deepcopy(getattr(self, "_active_preset", None) or {})
                    runtime_root = runtime_output_root(self.base_dir)
                    root_trace_dir = runtime_root / "bot_logs"
                    out = write_report(report_snapshot, root_trace_dir)
                    print(f"career report written: {out}", flush=True)
                    self._mark(running=False, post_run_processing=False, post_run_stage="")
                    released_for_next_run = True
                    self._schedule_post_run_outputs(
                        report_snapshot,
                        active_preset_snapshot,
                        runtime_root,
                        out,
                    )
                except Exception as e:
                    print(f"failed to write report: {e}", flush=True)
                finally:
                    if not released_for_next_run:
                        self._mark(running=False, post_run_processing=False, post_run_stage="")
            else:
                self._mark(running=False, post_run_processing=False, post_run_stage="")

    def _should_stop(self):
        with self.lock:
            return self.stop_requested

    def _advance(self, action):
        with self.lock:
            self.status["steps"] += 1
            self.status["last_action"] = action

    def _mark(self, **values):
        with self.lock:
            self.status.update(values)

    def _mark_post_run_stage(self, stage, *, processing=True):
        self._mark(
            post_run_processing=bool(processing),
            post_run_stage=str(stage or ""),
            last_action=str(stage or self.status.get("last_action") or ""),
        )

    def _rebuild_imitation_archive(self, runtime_root, active_preset_snapshot):
        """Rebuild the imitation prior archive after each finished career.

        Picks up newly produced peak careers (e.g., a 17-win run) as
        candidates that the strategy's imitation bonus can replay on
        future careers. The archive is small (top 25) and the build is
        fast (<1s on 300 careers), so running this every career is fine.
        """
        if not runtime_root or not active_preset_snapshot:
            return
        if not bool(active_preset_snapshot.get("imitation_enabled", False)):
            return
        try:
            from career_bot.imitation import build_archive
        except ImportError:
            return
        from pathlib import Path as _P
        runtime_root = _P(runtime_root)
        bot_logs_dir = runtime_root / "bot_logs"
        archive_path = runtime_root / "imitation" / "sweep_archive.json"
        postmortems_dir = runtime_root / "postmortems"
        race_attempt_history_path = runtime_root / "race_attempt_history.json"
        if not bot_logs_dir.exists():
            return

        # Estimate scheduled G1 count from the current preset for win attribution.
        try:
            sched = active_preset_snapshot.get("custom_race_schedule") or []
            ra_path = race_attempt_history_path if race_attempt_history_path.exists() else None
            g1_pids = set()
            if ra_path:
                import json as _json
                ra = _json.loads(ra_path.read_text(encoding="utf-8"))
                g1_pids = {int(pid) for pid, info in ra.items() if info.get("is_g1")}
            fallback_g1 = sum(1 for e in sched if int((e or {}).get("program_id") or 0) in g1_pids) if g1_pids else None
        except Exception:
            fallback_g1 = None

        try:
            result = build_archive(
                bot_logs_dir,
                archive_path,
                top_n=25,
                min_stat_sum=3000,
                postmortems_dir=postmortems_dir if postmortems_dir.exists() else None,
                race_attempt_history_path=str(race_attempt_history_path) if race_attempt_history_path.exists() else None,
                fallback_scheduled_g1=fallback_g1,
            )
            print(
                "imitation archive rebuilt: "
                f"{result.get('candidate_count', 0)} priors "
                f"(pool={result.get('source_pool_count', 0)})",
                flush=True,
            )
        except Exception as exc:
            print(f"imitation archive rebuild error: {exc}", flush=True)

    def _run_hyperparameter_tuner(self, runtime_root, active_preset_snapshot):
        """Run the hyperparameter auto-tuner against recent careers and
        persist any tune decisions to the INSTANCE preset (the file the
        bot actually loads at career start). The earlier version wrote
        to the master preset via PresetStore, but the bot reads the
        instance-learned preset from `uma_runtime/instances/<acc>/
        instance_learning/presets/<name>.json`, so master-only writes
        never reached the bot. Now writes to both.
        """
        if not runtime_root:
            return
        try:
            from career_bot.hyperparameter_tuner import run_tuner
        except ImportError:
            return
        preset_name = (active_preset_snapshot or {}).get("name", "")
        if not preset_name:
            return
        runtime_root = Path(runtime_root)
        bot_logs_dir = runtime_root / "bot_logs"
        history_path = runtime_root / "race_attempt_history.json"
        log_path = runtime_root / "learning" / "tune_log.jsonl"

        # Instance preset is the one the bot actually loads each career.
        # Read it directly so existing learned_hyperparameters from
        # previous cycles don't get reset to defaults.
        instance_preset_path = (
            runtime_root / "instance_learning" / "presets" / f"{preset_name}.json"
        )
        live_preset = None
        if instance_preset_path.exists():
            try:
                live_preset = json.loads(instance_preset_path.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, OSError) as exc:
                print(f"hyperparameter tuner: failed reading instance preset: {exc}", flush=True)
                return
        if live_preset is None:
            live_preset = dict(active_preset_snapshot or {})

        result = run_tuner(
            bot_logs_dir=bot_logs_dir,
            race_history_path=history_path,
            preset=live_preset,
            log_path=log_path,
        )
        applied = result.get("applied") or []
        if applied:
            try:
                instance_preset_path.parent.mkdir(parents=True, exist_ok=True)
                instance_preset_path.write_text(
                    json.dumps(live_preset, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError as exc:
                print(f"hyperparameter tuner: failed writing instance preset: {exc}", flush=True)
                return
            summary_lines = [
                f"{d['param']}: {d['old']} -> {d['new']} ({d['reason']})"
                for d in applied
            ]
            print(
                f"hyperparameter tuner applied {len(applied)} change(s) to {instance_preset_path.name}:\n  "
                + "\n  ".join(summary_lines),
                flush=True,
            )
        else:
            n_careers = (result.get("summary") or {}).get("n_careers", 0)
            print(f"hyperparameter tuner ran (no changes); n_careers={n_careers}", flush=True)

    def _export_hakuraku_races_async(self, runtime_root, career_log_path):
        def _worker():
            if not career_log_path or not Path(career_log_path).exists():
                return
            try:
                from tools.export_hakuraku_races import export_races

                manifest = export_races(
                    project_root=self.base_dir,
                    career_log=career_log_path,
                    output_dir=runtime_root / "hakuraku_races" / "latest_career_log",
                    preserve_existing_on_empty=True,
                    # Pass the instance-specific runtime so the export
                    # finds per-account trace files (which live at
                    # uma_runtime/instances/<account>/trace_logs), not
                    # the project-root-level uma_runtime/trace_logs.
                    trace_root=runtime_root,
                )
                print(
                    "hakuraku race export written: "
                    f"{manifest.get('total_exported', 0)} races -> {manifest.get('all_races_dir')}",
                    flush=True,
                )
            except Exception as e:
                print(f"failed to export hakuraku races: {e}", flush=True)

        threading.Thread(
            target=_worker,
            name="sweepy-hakuraku-export",
            daemon=True,
        ).start()

    def _schedule_post_run_outputs(self, report_snapshot, active_preset_snapshot, runtime_root, career_log_path):
        """Run non-game post-career work off the loop critical path.

        Final skill buying and the game finish call are already complete before
        this is scheduled. The only synchronous post-run requirement is writing
        the career log. Parent memory, postmortem analysis, auto-learning, and
        Hakuraku export can safely lag behind the next loop start.
        """
        if not runtime_root or not career_log_path:
            return
        report_snapshot = copy.deepcopy(report_snapshot or {})
        active_preset_snapshot = copy.deepcopy(active_preset_snapshot or {})
        runtime_root = Path(runtime_root)
        career_log_path = Path(career_log_path)

        def _worker():
            try:
                try:
                    from career_bot.sim_observations import write_sim_observation_export

                    sim_summary = write_sim_observation_export(
                        career_log_path,
                        runtime_root=runtime_root,
                    )
                    print(
                        "sim observations written: "
                        f"{sim_summary.get('record_count', 0)} records "
                        f"({sim_summary.get('training_snapshot_count', 0)} training, "
                        f"{sim_summary.get('race_result_count', 0)} races, "
                        f"{sim_summary.get('shop_item_phase_count', 0)} shop) -> "
                        f"{sim_summary.get('jsonl_path')}",
                        flush=True,
                    )
                except Exception as e:
                    print(f"failed to write sim observations: {e}", flush=True)

                try:
                    from career_bot.parent_memory import remember_bot_career

                    memory_result = remember_bot_career(self.base_dir, report_snapshot, career_log=career_log_path)
                    if memory_result.get("pending"):
                        print("bot parent queued for BOT tagging on next game-data sync", flush=True)
                except Exception as e:
                    print(f"bot parent memory update failed: {e}", flush=True)

                try:
                    from career_bot.race_postmortem import (
                        analyze_trace,
                        newest_trace_for_career,
                        summarize_losses,
                    )
                    import json as _json

                    trace_path = newest_trace_for_career(runtime_root, career_log_path)
                    if trace_path:
                        race_program_map = {}
                        try:
                            race_map_path = self.base_dir / "data" / "race_map.json"
                            race_map_raw = _json.loads(race_map_path.read_text(encoding="utf-8"))
                            raw_program = race_map_raw.get("program") or {}
                            race_program_map = {
                                int(key): value
                                for key, value in raw_program.items()
                                if str(key).isdigit() and isinstance(value, dict)
                            }
                        except Exception:
                            race_program_map = {}
                        career_started_at = None
                        career_ended_at = None
                        try:
                            career_log_doc = _json.loads(career_log_path.read_text(encoding="utf-8"))
                            career_started_at = career_log_doc.get("started_at")
                            career_ended_at = career_log_doc.get("ended_at")
                        except Exception:
                            pass
                        losses = analyze_trace(
                            trace_path,
                            race_program_map,
                            started_at=career_started_at,
                            ended_at=career_ended_at,
                        )
                        summary = summarize_losses(losses)
                        postmortem_dir = runtime_root / "postmortems"
                        postmortem_dir.mkdir(parents=True, exist_ok=True)
                        postmortem_path = postmortem_dir / (
                            career_log_path.stem.replace("career_log_", "postmortem_") + ".json"
                        )
                        postmortem_path.write_text(
                            _json.dumps(
                                {
                                    "trace_file": str(trace_path),
                                    "career_log": str(career_log_path),
                                    "g1_losses": losses,
                                    "summary": summary,
                                },
                                indent=2,
                            ),
                            encoding="utf-8",
                        )
                        print(
                            "race postmortem written: "
                            f"{summary.get('count', 0)} G1 losses -> {postmortem_path}",
                            flush=True,
                        )
                except Exception as e:
                    print(f"failed to write race postmortem: {e}", flush=True)

                try:
                    from career_bot.auto_learning import run_auto_learning

                    learning_result = run_auto_learning(
                        self.base_dir,
                        active_preset_snapshot,
                        career_log=career_log_path,
                        status=report_snapshot.get("status"),
                    )
                    if learning_result.get("success"):
                        print(
                            "auto learning applied: "
                            f"{learning_result.get('usable_sample_count', 0)} usable samples -> "
                            f"{learning_result.get('preset_path')}",
                            flush=True,
                        )
                    elif learning_result.get("skipped"):
                        skipped = str(learning_result.get("skipped") or "")
                        if skipped == "status_not_enabled":
                            allowed_statuses = active_preset_snapshot.get("auto_learning_statuses") or ["finished"]
                            refresh = learning_result.get("postmortem_refresh") or {}
                            refresh_suffix = ""
                            if refresh.get("applied"):
                                refresh_suffix = f"; g1_loss_feedback_updated={refresh.get('hint_count', 0)}"
                            print(
                                "auto learning skipped: "
                                f"{skipped} "
                                f"(status={learning_result.get('status')}, enabled={allowed_statuses}{refresh_suffix})",
                                flush=True,
                            )
                        else:
                            print(f"auto learning skipped: {skipped}", flush=True)
                except Exception as e:
                    print(f"auto learning failed: {e}", flush=True)

                try:
                    self._export_hakuraku_races_async(runtime_root, career_log_path)
                except Exception as e:
                    print(f"failed to schedule hakuraku races export: {e}", flush=True)

                # Hyperparameter auto-tuner: inspects recent careers, proposes
                # bounded adjustments to scoring constants, persists them to
                # preset["learned_hyperparameters"], logs decisions.
                try:
                    self._run_hyperparameter_tuner(runtime_root, active_preset_snapshot)
                except Exception as e:
                    print(f"hyperparameter tuner failed: {e}", flush=True)

                # Imitation archive auto-rebuild: refreshes the per-deck
                # prior used by the strategy's imitation bonus so newly
                # finished high-win careers become candidate replay
                # templates. Cheap (<1s on 300 careers) and idempotent —
                # safe to fail silently.
                try:
                    self._rebuild_imitation_archive(runtime_root, active_preset_snapshot)
                except Exception as e:
                    print(f"imitation archive rebuild failed: {e}", flush=True)
            finally:
                pass

        threading.Thread(
            target=_worker,
            name="sweepy-post-run-outputs",
            daemon=True,
        ).start()

    def _log_locked(self, action, turn, detail):
        items = self.status.setdefault("log", [])
        items.append({
            "id": len(items) + 1,
            "action": action,
            "turn": int(turn or 0),
            "detail": str(detail or ""),
            "time": time.strftime("%H:%M:%S"),
        })
        if len(items) > 120:
            del items[:len(items) - 120]

    def _log(self, action, turn, detail):
        with self.lock:
            self._log_locked(action, turn, detail)

    def _record_action(self, decision, chara=None):
        payload = decision.payload or {}
        understanding = getattr(decision, "understanding", {}) or {}
        action = decision.action
        turn = int(payload.get("current_turn") or 0)
        stats = self._turn_stats(chara or {})
        detail = self._format_turn_stats(stats) or str(decision.reason or "")
        facility = ""
        program_id = 0
        if action == "command":
            command_type = int(payload.get("command_type") or 0)
            command_id = int(payload.get("command_id") or 0)
            command_group_id = int(payload.get("command_group_id") or 0)
            if command_type == 1:
                action = "train"
                facility = TRAINING_LABELS.get(command_id, str(command_id))
            elif command_type == 8:
                action = "medic"
            elif command_type == 7:
                action = "rest"
                facility = str(command_group_id or command_id)
            elif command_type == 3:
                action = "recreation"
                facility = str(command_group_id or command_id)
            else:
                action = f"command {command_type}"
                facility = str(command_id or command_group_id)
        elif action in {"race", "race_progress"}:
            action = "race"
            program_id = int(payload.get("program_id") or 0)
            if not program_id:
                race_start_info = payload.get("race_start_info") or {}
                program_id = int(race_start_info.get("program_id") or 0)
            if program_id and self.race_planner:
                facility = self.race_planner.label(program_id)
            else:
                facility = str(program_id or "")
        elif action == "finish":
            action = "finish"
        row = {
            "turn": turn,
            "action": action,
            "facility": facility,
            "detail": detail,
            "understanding_summary": str(understanding.get("summary") or ""),
            "stats": stats,
            "time": time.strftime("%H:%M:%S"),
        }
        if understanding:
            row["understanding"] = understanding
        if action == "race" and program_id:
            row["program_id"] = program_id
        with self.lock:
            history = self.status.setdefault("action_history", [])
            if history and history[-1].get("turn") == row["turn"] and history[-1].get("action") == row["action"] and history[-1].get("facility") == row["facility"]:
                history[-1] = row
            else:
                history.append(row)

    def _safe_int(self, value, default=0):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return default

    def _race_result_from_response(self, response, current_turn=0, program_id=0):
        data = (response or {}).get("data") or {}
        if not data:
            return {}

        rank = 0
        source = ""
        reward = data.get("race_reward_info") or {}
        if isinstance(reward, dict):
            rank = self._safe_int(reward.get("result_rank"))
            if rank:
                source = "race_reward_info.result_rank"

        race_program_id = self._safe_int(program_id)
        race_turn = self._safe_int(current_turn)
        for row in reversed(data.get("race_history") or []):
            row_program_id = self._safe_int(row.get("program_id"))
            row_turn = self._safe_int(row.get("turn"))
            if race_program_id and row_program_id and row_program_id != race_program_id:
                continue
            if race_turn and row_turn and row_turn != race_turn:
                continue
            row_rank = self._safe_int(row.get("result_rank"))
            if row_rank:
                rank = rank or row_rank
                source = source or "race_history.result_rank"
                race_program_id = race_program_id or row_program_id
                race_turn = race_turn or row_turn
                break

        if not rank:
            return {}
        result = {
            "finish_rank": rank,
            "result_rank": rank,
            "won": rank == 1,
            "status": "won" if rank == 1 else "lost",
            "source": source,
        }
        if race_program_id:
            result["program_id"] = race_program_id
        if race_turn:
            result["turn"] = race_turn
        if isinstance(reward, dict):
            gained_fans = self._safe_int(reward.get("gained_fans"))
            if gained_fans:
                result["gained_fans"] = gained_fans
        return result

    def _race_result_label(self, result):
        if not result:
            return ""
        rank = self._safe_int(result.get("finish_rank") or result.get("result_rank"))
        if not rank:
            return ""
        prefix = "WON" if rank == 1 else "LOST"
        label = f"{prefix} #{rank}"
        if result.get("gained_fans"):
            label += f" / fans +{result.get('gained_fans')}"
        continues = self._safe_int(result.get("continue_attempts"))
        if continues:
            resources = result.get("continue_resources") or []
            if resources and all(resource == "free_retry" for resource in resources):
                resource_label = "free retry" if continues == 1 else "free retries"
            elif resources and all(resource == "alarm_clock" for resource in resources):
                resource_label = "alarm clock" if continues == 1 else "alarm clocks"
            elif resources and all(resource == "carat_alarm_clock" for resource in resources):
                resource_label = "carat alarm clock" if continues == 1 else "carat alarm clocks"
            elif resources and all(resource == "carats" for resource in resources):
                resource_label = "carat retry" if continues == 1 else "carat retries"
            else:
                resource_label = "race continue" if continues == 1 else "race continues"
            label += f" after {continues} {resource_label}"
            failed_ranks = [
                self._safe_int(rank)
                for rank in (result.get("continue_failed_ranks") or [])
                if self._safe_int(rank)
            ]
            if failed_ranks:
                previous = ", ".join(f"#{rank}" for rank in failed_ranks)
                label += f" (previous {previous})"
        return label

    def _config_enabled(self, value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        if isinstance(value, (int, float)):
            return int(value) != 0
        return str(value).strip().lower() in {"1", "true", "yes", "on", "enabled"}

    def _preset_value(self, preset, *keys, default=None):
        preset = preset or {}
        for key in keys:
            if key in preset and preset.get(key) is not None:
                return preset.get(key)
        return default

    def _race_continue_config(self, preset):
        limit = self._safe_int(self._preset_value(
            preset,
            "clock_use_limit",
            "race_continue_limit",
            "race_retry_limit",
            default=0,
        ))
        free_type = self._safe_int(self._preset_value(
            preset,
            "clock_free_continue_type",
            "race_continue_free_type",
            default=DEFAULT_FREE_CONTINUE_TYPE,
        ), DEFAULT_FREE_CONTINUE_TYPE)
        alarm_type = self._safe_int(self._preset_value(
            preset,
            "clock_continue_type",
            "race_continue_alarm_type",
            default=DEFAULT_CLOCK_CONTINUE_TYPE,
        ), DEFAULT_CLOCK_CONTINUE_TYPE)
        carat_type = self._safe_int(self._preset_value(
            preset,
            "clock_carat_continue_type",
            "race_continue_carat_type",
            default=DEFAULT_CARAT_CONTINUE_TYPE,
        ), DEFAULT_CARAT_CONTINUE_TYPE)
        carat_exchange_id = self._safe_int(self._preset_value(
            preset,
            "clock_carat_exchange_id",
            "race_continue_carat_exchange_id",
            default=DEFAULT_ALARM_CLOCK_EXCHANGE_ID,
        ), DEFAULT_ALARM_CLOCK_EXCHANGE_ID)
        carat_exchange_cost = self._safe_int(self._preset_value(
            preset,
            "clock_carat_cost",
            "race_continue_carat_cost",
            default=DEFAULT_ALARM_CLOCK_CARAT_COST,
        ), DEFAULT_ALARM_CLOCK_CARAT_COST)
        allow_carats = self._config_enabled(self._preset_value(
            preset,
            "clock_allow_carats",
            "race_continue_allow_carats",
            "allow_race_continue_carats",
            default=False,
        ))
        allow_direct_carats = self._config_enabled(self._preset_value(
            preset,
            "clock_allow_direct_carat_continue",
            "race_continue_allow_direct_carats",
            "allow_direct_race_continue_carats",
            default=False,
        ))
        consecutive_limit = self._safe_int(self._preset_value(
            preset,
            "clock_consecutive_limit",
            "race_continue_consecutive_limit",
            "race_retry_consecutive_limit",
            default=3,
        ), 3)
        # Hard per-career cap on alarm-clock USES, regardless of payment path.
        # Covers free retries, free-item alarm clocks, AND carat-bought alarm
        # clocks under the same counter — they're all "alarm clock uses" from
        # the user's perspective and should share one budget. Direct
        # `carats`-only continues (which are NOT alarm clocks) aren't counted
        # against this cap; gate those with `clock_use_limit` instead. Default
        # 0 = unlimited (preserves prior behavior). Older alias names kept so
        # existing presets keep working.
        alarm_use_limit = self._safe_int(self._preset_value(
            preset,
            "alarm_clock_use_limit",
            "clock_carat_use_limit",
            "carat_alarm_clock_limit",
            "clock_max_carat_uses",
            default=0,
        ), 0)
        try:
            delay_seconds = float(self._preset_value(
                preset,
                "clock_retry_delay_seconds",
                "race_continue_delay_seconds",
                "race_retry_delay_seconds",
                default=1.4,
            ) or 0)
        except (TypeError, ValueError):
            delay_seconds = 1.4
        try:
            pre_end_probe_seconds = float(self._preset_value(
                preset,
                "clock_pre_race_end_probe_seconds",
                "race_continue_pre_end_probe_seconds",
                "race_retry_pre_end_probe_seconds",
                default=9.5,
            ) or 0)
        except (TypeError, ValueError):
            pre_end_probe_seconds = 9.5
        try:
            pre_end_probe_interval = float(self._preset_value(
                preset,
                "clock_pre_race_end_probe_interval",
                "race_continue_pre_end_probe_interval",
                "race_retry_pre_end_probe_interval",
                default=0.6,
            ) or 0.6)
        except (TypeError, ValueError):
            pre_end_probe_interval = 0.6
        pre_end_continue_probe = self._config_enabled(self._preset_value(
            preset,
            "clock_pre_race_end_continue_probe",
            "race_continue_pre_end_continue_probe",
            "race_retry_pre_end_continue_probe",
            default=True,
        ))
        pre_end_retry_205 = self._config_enabled(self._preset_value(
            preset,
            "clock_pre_race_end_retry_205",
            "race_continue_pre_end_retry_205",
            "race_retry_pre_end_retry_205",
            default=False,
        ))
        return {
            # The game only allows five race continues across one career run.
            "limit": min(5, max(0, limit)),
            "consecutive_limit": min(5, max(0, consecutive_limit)),
            "alarm_use_limit": max(0, alarm_use_limit),
            "free_type": free_type or DEFAULT_FREE_CONTINUE_TYPE,
            "alarm_type": alarm_type or DEFAULT_CLOCK_CONTINUE_TYPE,
            "carat_type": carat_type or DEFAULT_CARAT_CONTINUE_TYPE,
            "carat_exchange_id": carat_exchange_id or DEFAULT_ALARM_CLOCK_EXCHANGE_ID,
            "carat_exchange_cost": max(0, carat_exchange_cost or DEFAULT_ALARM_CLOCK_CARAT_COST),
            "allow_carats": allow_carats,
            "allow_direct_carats": allow_direct_carats,
            # Try Again is a UI/result-screen action. Immediate calls after
            # race_end have been observed returning result_code 500.
            "delay_seconds": min(5.0, max(0.0, delay_seconds)),
            # The real client uses /continue from the Try Again state before
            # accepting the result with race_end. Live traces show successful
            # alarm-clock clicks around 9-10s after race_start; probing around
            # 7-8s consistently returns 205 even on races that later lose.
            "pre_end_probe_seconds": min(15.0, max(0.0, pre_end_probe_seconds)),
            "pre_end_probe_interval": min(2.0, max(0.1, pre_end_probe_interval)),
            # Keep one Try Again probe enabled by default because successful
            # live traces show /continue is accepted before race_end. Do not
            # retry 205s by default; most races are wins and will reject here.
            "pre_end_continue_probe": pre_end_continue_probe,
            "pre_end_retry_205": pre_end_retry_205,
        }

    def _wait_before_race_continue(self, preset):
        delay_seconds = self._race_continue_config(preset).get("delay_seconds", 0)
        if delay_seconds:
            time.sleep(delay_seconds)

    def _race_continue_remaining(self, preset):
        cfg = self._race_continue_config(preset)
        used = self._safe_int(self.status.get("race_retries"))
        return max(0, cfg["limit"] - used)

    def _race_continue_info(self, response):
        data = (response or {}).get("data") or {}
        home = data.get("home_info") or {}
        chara = data.get("chara_info") or {}
        keys = (
            "available_continue_num",
            "available_free_continue_num",
            "free_continue_num",
            "free_continue_time",
        )
        info = {key: self._safe_int(home.get(key)) for key in keys if key in home}
        info["playing_state"] = self._safe_int(chara.get("playing_state"))
        info["state"] = self._safe_int(chara.get("state"))
        return info

    def _load_pre_race_end_state(self, client, current_turn, program_id, preset):
        cfg = self._race_continue_config(preset)
        deadline = time.time() + (cfg["pre_end_probe_seconds"] if cfg["limit"] > 0 else 0)
        last_state = None
        last_result = {}
        probes = 0

        while True:
            fresh = client.load_career()
            probes += 1
            last_state = fresh
            state_val = self._safe_int(((fresh.get("data") or {}).get("chara_info") or {}).get("playing_state"))
            last_result = self._race_result_from_response(fresh, current_turn, program_id)
            if last_result or state_val in {1}:
                if probes > 1:
                    self._log("race_pre_end_probe", current_turn, f"ready after {probes} load checks")
                return fresh, last_result
            if time.time() >= deadline:
                if probes > 1:
                    self._log("race_pre_end_probe", current_turn, f"no pre-end result after {probes} load checks")
                return last_state, last_result
            time.sleep(cfg["pre_end_probe_interval"])

    def _race_continue_attempt_types(self, preset, info=None, allow_carat_spend=True, program_id=None):
        cfg = self._race_continue_config(preset)
        attempts = []
        seen = set()
        info = info or {}
        # Per-career circuit breaker. Only terminal resource errors should land
        # here; generic 500s are usually timing/state rejects and must not poison
        # alarm clocks for the rest of the run.
        disabled = set(self.status.get("disabled_continue_resources") or [])
        # Per-career alarm-clock cap: bundles free retries + item-alarm-clocks +
        # carat-bought alarm clocks under one counter. Once the user-set cap
        # is hit, the three alarm-clock resources are dropped from the attempt
        # list for the rest of the run. Direct `carats`-only continues are
        # NOT alarm clocks and continue under the `clock_use_limit` umbrella.
        alarm_uses = (
            self._safe_int(self.status.get("free_race_retries"))
            + self._safe_int(self.status.get("alarm_clocks_used"))
        )
        alarm_limit = cfg.get("alarm_use_limit") or 0
        alarm_budget_exhausted = bool(alarm_limit) and alarm_uses >= alarm_limit
        if (
            info.get("available_free_continue_num", 0) > 0
            and "free_retry" not in disabled
            and not alarm_budget_exhausted
        ):
            if cfg["free_type"] not in seen:
                attempts.append((cfg["free_type"], "free_retry"))
                seen.add(cfg["free_type"])
        if cfg["alarm_type"] not in seen and "alarm_clock" not in disabled and not alarm_budget_exhausted:
            attempts.append((cfg["alarm_type"], "alarm_clock"))
            seen.add(cfg["alarm_type"])
        # Carat-spending resources are gated on `allow_carat_spend`. The
        # speculative pre-race-end probe (where the race result isn't yet
        # known) sets this False to avoid buying an alarm clock with carats
        # for a race that might have actually been a win — confirmed-loss
        # paths keep the original behavior by leaving the default True.
        if (
            cfg["allow_carats"]
            and "carat_alarm_clock" not in disabled
            and not alarm_budget_exhausted
            and allow_carat_spend
        ):
            attempts.append((cfg["alarm_type"], "carat_alarm_clock"))
        if (
            cfg["allow_carats"]
            and cfg["allow_direct_carats"]
            and cfg["carat_type"] not in seen
            and "carats" not in disabled
            and allow_carat_spend
        ):
            attempts.append((cfg["carat_type"], "carats"))
        # Race-continue learning: filter out resources that historically
        # never recover at THIS program_id. Saving an alarm clock for a
        # race that's already been lost three times running is the
        # correct parent-farming play. Only fires AFTER a loss (this
        # function only runs after race_end); does NOT gate race entry.
        if program_id and isinstance(preset, dict):
            stats = preset.get("race_continue_stats")
            if stats:
                from career_bot.race_continue_learning import should_attempt_continue
                filtered = []
                for continue_type, resource in attempts:
                    verdict = should_attempt_continue(stats, program_id, resource)
                    if verdict is False:
                        self._log(
                            "race_continue_skip_resource",
                            self._safe_int((self.status or {}).get("current_turn")) or 0,
                            f"{resource} at race {program_id}: low historical recovery rate",
                        )
                        continue
                    filtered.append((continue_type, resource))
                attempts = filtered
        return attempts

    def _client_carats_total(self, client):
        coin_info = getattr(client, "coin_info", {}) or {}
        return self._safe_int(coin_info.get("fcoin")) + self._safe_int(coin_info.get("coin"))

    def _prepare_race_continue_resource(self, client, preset, resource, current_turn, program_id, info=None, phase=""):
        if resource != "carat_alarm_clock":
            return None
        cfg = self._race_continue_config(preset)
        exchange_id = self._safe_int(cfg.get("carat_exchange_id"), DEFAULT_ALARM_CLOCK_EXCHANGE_ID)
        cost = self._safe_int(cfg.get("carat_exchange_cost"), DEFAULT_ALARM_CLOCK_CARAT_COST)
        current_num = self._client_carats_total(client)
        if cost > 0 and current_num < cost:
            raise RuntimeError(f"not enough carats for alarm clock exchange: have {current_num}, need {cost}")
        if not hasattr(client, "exchange_item"):
            raise RuntimeError("client does not support item/exchange for carat alarm clocks")
        self._log("race_continue_exchange", current_turn, f"buying alarm clock exchange_id={exchange_id} carats={current_num}")
        self._add_race_continue_event(
            "race_continue_exchange_attempt",
            current_turn,
            program_id,
            resource=resource,
            exchange_id=exchange_id,
            count=1,
            current_num=current_num,
            continue_info=info or {},
            phase=phase,
        )
        response = client.exchange_item(
            exchange_id=exchange_id,
            count=1,
            current_num=current_num,
            get_list_time="",
        )
        data = (response or {}).get("data") or {}
        coin_info = data.get("coin_info") or getattr(client, "coin_info", {}) or {}
        new_carats = self._safe_int(coin_info.get("fcoin")) + self._safe_int(coin_info.get("coin"))
        rewards = ((data.get("reward_summary_info") or {}).get("add_item_list") or [])
        added_clock = any(self._safe_int(item.get("item_id")) == DEFAULT_ALARM_CLOCK_ITEM_ID for item in rewards if isinstance(item, dict))
        self._add_race_continue_event(
            "race_continue_exchange_used",
            current_turn,
            program_id,
            resource=resource,
            exchange_id=exchange_id,
            previous_carats=current_num,
            current_carats=new_carats,
            added_alarm_clock=added_clock,
            phase=phase,
        )
        return response

    def _add_race_continue_event(self, event, current_turn, program_id, **data):
        if not self.report:
            return
        row = {
            "event": event,
            "turn": self._safe_int(current_turn),
            "program_id": self._safe_int(program_id),
            "race": self._race_info_for_program(program_id),
        }
        row.update(data)
        add_event(self.report, row)

    def _event_choice_options_for_log(self, event):
        choices = ((event.get("event_contents_info") or {}).get("choice_array") or [])
        rows = []
        for index, choice in enumerate(choices):
            if not isinstance(choice, dict):
                continue
            rows.append({
                "index": index,
                "select_index": self._safe_int(choice.get("select_index"), index + 1),
                "choice_number": self._safe_int(choice.get("choice_number"), index + 1),
                "text": (
                    choice.get("text")
                    or choice.get("choice_text")
                    or choice.get("message")
                    or choice.get("name")
                    or ""
                ),
                "raw_choice": copy.deepcopy(choice),
            })
        return rows

    def _event_payload_for_log(self, event):
        if not isinstance(event, dict):
            return {}
        contents = event.get("event_contents_info") or {}
        return {
            "event_id": self._safe_int(event.get("event_id")),
            "story_id": str(event.get("story_id") or "").strip(),
            "chara_id": self._safe_int(event.get("chara_id")),
            "support_card_id": self._safe_int(event.get("support_card_id")),
            "event_contents_id": self._safe_int(contents.get("event_contents_id")),
            "event_title": contents.get("title") or contents.get("event_title") or contents.get("name") or "",
            "choice_options": self._event_choice_options_for_log(event),
            "raw_event": copy.deepcopy(event),
        }

    def _event_tracking_metadata_for_log(self, event, current_turn):
        turn = self._safe_int(current_turn)
        story_id = ""
        if isinstance(event, dict):
            story_id = str(event.get("story_id") or "").strip()
        static_event = static_mant_event_for_story(story_id)
        metadata = {
            "turn_label": career_turn_label(turn),
            "turn_calendar": career_turn_calendar(turn),
        }
        if static_event:
            expected_turn = self._safe_int(static_event.get("turn"))
            metadata["static_mant_fixed_event"] = {
                "story_id": story_id,
                "event_id": self._safe_int(static_event.get("event_id")),
                "expected_turn": expected_turn,
                "expected_turn_label": career_turn_label(expected_turn),
                "turn_match": bool(expected_turn and expected_turn == turn),
                "expected_effects": copy.deepcopy(static_event.get("effects") or {}),
            }
        return metadata

    def _event_state_snapshot(self, state):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        free = data.get("free_data_set") or {}
        response_status = data.get("response_status") or data.get("responseStatus") or {}
        event_effected_factors = (
            data.get("event_effected_factor_array")
            or response_status.get("event_effected_factor_array")
            or response_status.get("event_effected_factors")
            or []
        )
        return {
            "turn": self._safe_int(chara.get("turn")),
            "skill_point": self._safe_int(chara.get("skill_point")),
            "mant_coin": self._safe_int(
                free.get("coin_num") if free.get("coin_num") is not None else free.get("gained_coin_num")
            ),
            "motivation": self._safe_int(chara.get("motivation")),
            "stats": self._turn_stats(chara),
            "unchecked_event_count": len(data.get("unchecked_event_array") or []),
            "unchecked_event_ids": [
                self._safe_int(row.get("event_id"))
                for row in data.get("unchecked_event_array") or []
                if isinstance(row, dict) and self._safe_int(row.get("event_id"))
            ],
            "event_effected_factor_array": copy.deepcopy(event_effected_factors),
            "skill_tips_array": copy.deepcopy(chara.get("skill_tips_array") or data.get("skill_tips_array") or []),
            "guest_outing_info_array": copy.deepcopy(chara.get("guest_outing_info_array") or data.get("guest_outing_info_array") or []),
        }

    def _record_event_choice(self, event, choice, current_turn, state_before=None):
        """Append a structured event_choice row to the career log for
        the event-choice learner to mine later. Only fires on
        multi-choice events — single-choice resolutions have no
        decision signal and are filtered out by the learner anyway.

        Choice is the 1-based select_index that was sent to the API
        (matches API convention). The learner stringifies this when
        keying into the stats dict, so 1-vs-int doesn't matter for
        lookups."""
        if not self.report or not event or choice is None:
            return
        try:
            choice_int = int(choice)
        except (TypeError, ValueError):
            return
        choices = ((event.get("event_contents_info") or {}).get("choice_array") or [])
        row = {
            "event": "event_choice",
            "turn": self._safe_int(current_turn),
            "turn_label": career_turn_label(self._safe_int(current_turn)),
            "turn_calendar": career_turn_calendar(self._safe_int(current_turn)),
            "event_id": self._safe_int(event.get("event_id")),
            "story_id": str(event.get("story_id") or "").strip(),
            "choice_index": choice_int,
            "available_choices": len(choices),
            "available_choice_options": self._event_choice_options_for_log(event),
            "event_payload": self._event_payload_for_log(event),
        }
        row.update(self._event_tracking_metadata_for_log(event, current_turn))
        if state_before:
            row["state_before"] = state_before
        add_event(self.report, row)

    def _record_event_resolution(self, event, choice, current_turn, response=None, error=None, state_before=None):
        if not self.report or not event:
            return
        row = {
            "event": "event_resolution",
            "turn": self._safe_int(current_turn),
            "turn_label": career_turn_label(self._safe_int(current_turn)),
            "turn_calendar": career_turn_calendar(self._safe_int(current_turn)),
            "event_id": self._safe_int(event.get("event_id")),
            "story_id": str(event.get("story_id") or "").strip(),
            "choice_index": self._safe_int(choice),
            "event_payload": self._event_payload_for_log(event),
            "success": error is None,
        }
        row.update(self._event_tracking_metadata_for_log(event, current_turn))
        if state_before:
            row["state_before"] = state_before
        if response:
            row["state_after"] = self._event_state_snapshot(response)
        if error is not None:
            row["error"] = {
                "type": type(error).__name__,
                "message": str(error),
            }
        add_event(self.report, row)

    def _annotate_race_continue_result(self, result, resources, failed_ranks=None):
        if not result or not resources:
            return result
        result["continued"] = True
        result["continue_attempts"] = len(resources)
        result["continue_resources"] = list(resources)
        result["continue_resource"] = resources[-1]
        if failed_ranks:
            result["continue_failed_ranks"] = list(failed_ranks)
        return result

    def _record_race_attempt_result(self, current_turn, program_id, result, attempt, continued_with=None, continue_type=None, continue_attempt=None):
        if not result:
            return
        rank = self._safe_int(result.get("finish_rank") or result.get("result_rank"))
        label = self._race_result_label(result)
        if continued_with:
            label = f"{label} -> retried with {continued_with.replace('_', ' ')}"
        self._log("race_attempt_result", current_turn, f"attempt {attempt}: {label}")
        self._add_race_continue_event(
            "race_attempt_result",
            current_turn,
            program_id,
            attempt=self._safe_int(attempt),
            continue_attempt=self._safe_int(continue_attempt),
            continue_type=continue_type,
            continued_with=continued_with,
            finish_rank=rank,
            won=rank == 1,
            status="won" if rank == 1 else "lost",
            label=label,
            result=dict(result),
            is_g1=self._is_g1_program(program_id),
        )
        with self.lock:
            history = self.status.setdefault("action_history", [])
            for row in reversed(history):
                if row.get("action") != "race":
                    continue
                if current_turn and self._safe_int(row.get("turn")) != self._safe_int(current_turn):
                    continue
                row_program_id = self._safe_int(row.get("program_id"))
                if program_id and row_program_id and row_program_id != self._safe_int(program_id):
                    continue
                row.setdefault("race_attempts", []).append({
                    "attempt": self._safe_int(attempt),
                    "finish_rank": rank,
                    "won": rank == 1,
                    "continued_with": continued_with,
                    "continue_type": continue_type,
                    "continue_attempt": self._safe_int(continue_attempt),
                    "label": label,
                })
                break

    def _run_continued_race(self, client, state, current_turn, program_id, strategy=None, race_start_info=None):
        current = state or {}
        if strategy and (current.get("data") or {}).get("unchecked_event_array"):
            current = self._drain_events(client, strategy, current)

        data = current.get("data") or {}
        if data.get("race_reward_info"):
            return current

        chara = data.get("chara_info") or {}
        playing_state = self._safe_int(chara.get("playing_state"))
        if playing_state not in {3, 4, 5}:
            start_info = data.get("race_start_info") or race_start_info or {}
            is_short = 1 if (start_info.get("is_short") or chara.get("is_short_race")) else 0
            try:
                client.race_start(is_short=is_short, current_turn=current_turn)
                self._log("race_restart", current_turn, f"short {is_short}")
            except Exception as exc:
                if not any(code in str(exc) for code in ("102", "2502")):
                    raise
                self._log("race_restart_reconciled", current_turn, f"race_start rejected during replay: {exc}")
                fresh = self._fresh_career_state(client, strategy)
                fresh_data = fresh.get("data") or {}
                if fresh_data.get("race_reward_info"):
                    return fresh
                if self._same_active_race_state(fresh, current_turn, program_id, playing_states={3, 4, 5}):
                    current = fresh
                elif self._same_active_race_state(fresh, current_turn, program_id, playing_states={2}):
                    return fresh
                else:
                    raise

        try:
            return client.race_end(current_turn=current_turn)
        except Exception as exc:
            if not any(code in str(exc) for code in ("102", "2502")):
                raise
            self._log("race_end_reconciled", current_turn, f"race_end rejected during replay: {exc}")
            fresh = self._fresh_career_state(client, strategy)
            fresh_data = fresh.get("data") or {}
            if fresh_data.get("race_reward_info") or self._same_active_race_state(fresh, current_turn, program_id, playing_states={4, 5}):
                return fresh
            if self._same_active_race_state(fresh, current_turn, program_id, playing_states={2, 3}):
                return fresh
            raise

    def _try_continues_pre_race_end(self, client, load_state, race_result, current_turn, program_id, preset, strategy=None, race_start_info=None):
        """Run /continue before /race_end when a current loss is already known.

        Normal bot traces usually learn the current result from /race_end.
        This pre-end path is kept for resume/reconciliation states that already
        contain a current-turn loss before /race_end has been accepted.
        """
        cfg = self._race_continue_config(preset)
        if cfg["limit"] <= 0:
            return load_state, race_result
        if self._race_continue_remaining(preset) <= 0:
            return load_state, race_result

        resources_used = []
        failed_ranks = []
        race_attempt_index = 1

        while (
            self._race_continue_remaining(preset) > 0
            and len(resources_used) < cfg["consecutive_limit"]
            and race_result
            and not race_result.get("won")
        ):
            info = self._race_continue_info(load_state)
            if "available_continue_num" in info and info["available_continue_num"] <= 0:
                self._log("race_continue_skip", current_turn, "server reports no retries left (pre-race-end)")
                break

            attempt_no = self._safe_int(self.status.get("race_retries")) + 1
            failed_rank = self._safe_int(race_result.get("finish_rank") or race_result.get("result_rank"))
            continued = None
            used_resource = None
            used_continue_type = None
            last_error = None

            for continue_type, resource in self._race_continue_attempt_types(preset, info, program_id=program_id):
                try:
                    self._log("race_continue", current_turn, f"{resource} attempt {attempt_no} after #{failed_rank} (pre-race-end)")
                    self._add_race_continue_event(
                        "race_continue_attempt",
                        current_turn,
                        program_id,
                        attempt=attempt_no,
                        continue_type=continue_type,
                        resource=resource,
                        continue_info=info,
                        failed_result=dict(race_result),
                        phase="pre_race_end",
                    )
                    self._prepare_race_continue_resource(
                        client,
                        preset,
                        resource,
                        current_turn,
                        program_id,
                        info,
                        phase="pre_race_end",
                    )
                    self._wait_before_race_continue(preset)
                    continued = client.race_continue(current_turn=current_turn, continue_type=continue_type)
                    used_resource = resource
                    used_continue_type = continue_type
                    break
                except Exception as exc:
                    last_error = str(exc)
                    err_str = str(exc)
                    self._log("race_continue_failed", current_turn, f"{resource}/{continue_type} (pre-end): {exc}")
                    self._add_race_continue_event(
                        "race_continue_failed",
                        current_turn,
                        program_id,
                        attempt=attempt_no,
                        continue_type=continue_type,
                        resource=resource,
                        error=str(exc),
                        continue_info=info,
                        failed_result=dict(race_result),
                        phase="pre_race_end",
                    )
                    # A 500 on the bare `alarm_clock` resource almost always
                    # means the player has zero alarm clocks in inventory — the
                    # server rejects continue_type=2 because there's no clock
                    # to consume. The NEXT resource in the attempt list
                    # (`carat_alarm_clock`) handles exactly this case: buys a
                    # clock with carats via /item/exchange, then retries
                    # continue_type=2. So when alarm_clock 500s we MUST fall
                    # through and try carat_alarm_clock. Same for free_retry —
                    # a 500 there shouldn't stop us trying alarm-clock paths.
                    # Only break the inner for-loop when the resource that
                    # failed was the LAST one (carat_alarm_clock or carats),
                    # or when the failure was a hard rejection (1801/1802).
                    if "API error 500" in err_str:
                        self._add_race_continue_event(
                            "race_continue_rejected",
                            current_turn,
                            program_id,
                            attempt=attempt_no,
                            continue_type=continue_type,
                            resource=resource,
                            reason="server_rejected_continue_without_disabling_resource",
                            phase="pre_race_end",
                        )
                        # Fall through to next resource (e.g. alarm_clock → carat_alarm_clock).
                        # Only the FINAL resource type (carat_alarm_clock / carats) should bail.
                        if resource in ("carat_alarm_clock", "carats"):
                            break
                        continue
                    if "API error 1801" in err_str or "API error 1802" in err_str:
                        disabled = self.status.setdefault("disabled_continue_resources", [])
                        if resource not in disabled:
                            disabled.append(resource)
                            self._log("race_continue_disabled", current_turn, f"{resource} disabled (pre-end {err_str[:80]})")

            if continued is None:
                self._log("race_continue_abort", current_turn, last_error or "no continue path succeeded (pre-race-end)")
                break

            # Successful /continue. Server has replayed the race. Track stats.
            with self.lock:
                self.status["race_retries"] = self._safe_int(self.status.get("race_retries")) + 1
                if used_resource == "free_retry":
                    self.status["free_race_retries"] = self._safe_int(self.status.get("free_race_retries")) + 1
                elif used_resource == "carats":
                    self.status["carat_race_retries"] = self._safe_int(self.status.get("carat_race_retries")) + 1
                elif used_resource == "carat_alarm_clock":
                    self.status["carat_race_retries"] = self._safe_int(self.status.get("carat_race_retries")) + 1
                    self.status["alarm_clocks_used"] = self._safe_int(self.status.get("alarm_clocks_used")) + 1
                elif used_resource == "alarm_clock":
                    self.status["alarm_clocks_used"] = self._safe_int(self.status.get("alarm_clocks_used")) + 1
            resources_used.append(used_resource)
            failed_ranks.append(failed_rank)
            self._log("race_continue_used", current_turn, f"{used_resource} #{attempt_no} after #{failed_rank} (pre-race-end)")
            self._add_race_continue_event(
                "race_continue_used",
                current_turn,
                program_id,
                attempt=race_attempt_index,
                continue_attempt=attempt_no,
                continue_type=used_continue_type,
                resource=used_resource,
                failed_rank=failed_rank,
                phase="pre_race_end",
            )

            try:
                load_state = self._run_continued_race(
                    client,
                    continued,
                    current_turn,
                    program_id,
                    strategy=strategy,
                    race_start_info=race_start_info,
                )
            except Exception as replay_exc:
                self._log("race_continue_abort", current_turn, f"post-continue replay failed: {replay_exc}")
                break

            new_result = self._race_result_from_response(load_state, current_turn, program_id)
            race_result = new_result or race_result
            race_result = self._annotate_race_continue_result(race_result, resources_used, failed_ranks)
            race_attempt_index += 1

        return load_state, race_result

    def _try_unknown_continue_pre_race_end(self, client, race_state, current_turn, program_id, preset, strategy=None, race_start_info=None):
        """Probe /continue before race_end while the race is still active.

        The normal API path does not expose result_rank until race_end, but
        manual client traces show alarm-clock Try Again is posted before that.
        If the server accepts this call, the hidden race result was retryable.
        If it rejects with 500, keep the resource enabled and accept race_end.
        """
        cfg = self._race_continue_config(preset)
        if not cfg["pre_end_continue_probe"] or cfg["limit"] <= 0:
            return None, None, False
        if self._race_continue_remaining(preset) <= 0:
            return None, None, False
        if not self._same_active_race_state(race_state, current_turn, program_id, playing_states={3}):
            return None, None, False

        attempted = False
        current_state = race_state
        resources_used = []
        probe_deadline = time.time() + max(0.0, float(cfg.get("pre_end_probe_seconds") or 0))
        probe_interval = max(0.05, float(cfg.get("pre_end_probe_interval") or 0.0))

        while self._race_continue_remaining(preset) > 0 and len(resources_used) < cfg["consecutive_limit"]:
            if not self._same_active_race_state(current_state, current_turn, program_id, playing_states={3}):
                data = (current_state or {}).get("data") or {}
                chara = data.get("chara_info") or {}
                playing_state = self._safe_int(chara.get("playing_state"))
                if playing_state in {4, 5}:
                    break
                if self._safe_int(chara.get("race_program_id")) != self._safe_int(program_id):
                    break
                start_info = data.get("race_start_info") or race_start_info or {}
                is_short = 1 if (start_info.get("is_short") or chara.get("is_short_race")) else 0
                try:
                    client.race_start(is_short=is_short, current_turn=current_turn)
                    self._log("race_restart", current_turn, f"pre-end continue retry short {is_short}")
                except Exception as exc:
                    if not any(code in str(exc) for code in ("102", "2502")):
                        raise
                    self._log("race_restart_reconciled", current_turn, f"pre-end replay race_start rejected: {exc}")
                    fresh = self._fresh_career_state(client, strategy)
                    fresh_data = fresh.get("data") or {}
                    if fresh_data.get("race_reward_info") or self._same_active_race_state(fresh, current_turn, program_id, playing_states={4, 5}):
                        current_state = fresh
                        break
                    if not self._same_active_race_state(fresh, current_turn, program_id, playing_states={3}):
                        current_state = fresh
                        break
                    current_state = fresh
                else:
                    current_state, pre_result = self._load_pre_race_end_state(client, current_turn, program_id, preset)
                    if pre_result:
                        break

            if not self._same_active_race_state(current_state, current_turn, program_id, playing_states={3}):
                break

            info = self._race_continue_info(current_state)
            if "available_continue_num" in info and info["available_continue_num"] <= 0:
                self._log("race_continue_skip", current_turn, "server reports no retries left (pre-race-end probe)")
                self._add_race_continue_event(
                    "race_continue_skip",
                    current_turn,
                    program_id,
                    reason="no_retries_left_pre_race_end_probe",
                    continue_info=info,
                )
                break

            attempt_no = self._safe_int(self.status.get("race_retries")) + 1
            continued = None
            used_resource = None
            used_continue_type = None
            stop_attempts = False

            # Speculative probe: race result is not yet confirmed. Carat-spend
            # paths are excluded so a race that turns out to be a win doesn't
            # cost carats for a clock we never needed.
            for continue_type, resource in self._race_continue_attempt_types(preset, info, allow_carat_spend=False, program_id=program_id):
                while True:
                    attempted = True
                    try:
                        self._log("race_continue_probe", current_turn, f"{resource} attempt {attempt_no} before race_end")
                        self._add_race_continue_event(
                            "race_continue_attempt",
                            current_turn,
                            program_id,
                            attempt=attempt_no,
                            continue_type=continue_type,
                            resource=resource,
                            continue_info=info,
                            phase="pre_race_end_probe",
                            reason="unknown_result_probe_before_race_end",
                        )
                        self._prepare_race_continue_resource(
                            client,
                            preset,
                            resource,
                            current_turn,
                            program_id,
                            info,
                            phase="pre_race_end_probe",
                        )
                        self._wait_before_race_continue(preset)
                        continued = client.race_continue(current_turn=current_turn, continue_type=continue_type)
                        used_resource = resource
                        used_continue_type = continue_type
                        break
                    except Exception as exc:
                        err_str = str(exc)
                        if cfg.get("pre_end_retry_205") and "API error 205" in err_str and time.time() < probe_deadline:
                            # 205 can mean the hidden result is not retryable, but logs also show
                            # losses producing 205 when probed too early. Keep polling briefly while
                            # the race is still in the pre-race_end state.
                            self._log("race_continue_probe_wait", current_turn, f"{resource}/{continue_type}: 205 before race_end; polling")
                            self._add_race_continue_event(
                                "race_continue_pending",
                                current_turn,
                                program_id,
                                attempt=attempt_no,
                                continue_type=continue_type,
                                resource=resource,
                                error=str(exc),
                                continue_info=info,
                                phase="pre_race_end_probe",
                                reason="try_again_not_ready_pre_race_end_probe",
                            )
                            time.sleep(probe_interval)
                            try:
                                fresh = self._fresh_career_state(client, strategy)
                            except Exception as refresh_exc:
                                self._log("race_continue_probe_wait", current_turn, f"refresh failed after 205: {refresh_exc}")
                                continue
                            if not self._same_active_race_state(fresh, current_turn, program_id, playing_states={3}):
                                current_state = fresh
                                stop_attempts = True
                                break
                            current_state = fresh
                            info = self._race_continue_info(current_state)
                            continue

                        self._log("race_continue_probe_rejected", current_turn, f"{resource}/{continue_type}: {exc}")
                        self._add_race_continue_event(
                            "race_continue_rejected",
                            current_turn,
                            program_id,
                            attempt=attempt_no,
                            continue_type=continue_type,
                            resource=resource,
                            error=str(exc),
                            continue_info=info,
                            phase="pre_race_end_probe",
                            reason="server_rejected_pre_race_end_probe",
                        )
                        if "API error 1801" in err_str or "API error 1802" in err_str:
                            disabled = self.status.setdefault("disabled_continue_resources", [])
                            if resource not in disabled:
                                disabled.append(resource)
                                self._log("race_continue_disabled", current_turn, f"{resource} disabled (pre-end probe {err_str[:80]})")
                            break
                        # 500 on a non-final resource (e.g. alarm_clock when
                        # the player has 0 clocks) — fall through to the next
                        # resource in the attempt list (carat_alarm_clock will
                        # buy a clock with carats then retry). Only set
                        # stop_attempts when the resource that failed was the
                        # last fallback in the chain.
                        if resource in ("carat_alarm_clock", "carats"):
                            stop_attempts = True
                        break
                    break
                if continued or stop_attempts:
                    break

            if not continued:
                break

            with self.lock:
                self.status["race_retries"] = self._safe_int(self.status.get("race_retries")) + 1
                if used_resource == "free_retry":
                    self.status["free_race_retries"] = self._safe_int(self.status.get("free_race_retries")) + 1
                elif used_resource == "carats":
                    self.status["carat_race_retries"] = self._safe_int(self.status.get("carat_race_retries")) + 1
                elif used_resource == "carat_alarm_clock":
                    self.status["carat_race_retries"] = self._safe_int(self.status.get("carat_race_retries")) + 1
                    self.status["alarm_clocks_used"] = self._safe_int(self.status.get("alarm_clocks_used")) + 1
                elif used_resource == "alarm_clock":
                    self.status["alarm_clocks_used"] = self._safe_int(self.status.get("alarm_clocks_used")) + 1

            resources_used.append(used_resource)
            self._log("race_continue_used", current_turn, f"{used_resource} #{attempt_no} before race_end")
            self._add_race_continue_event(
                "race_continue_used",
                current_turn,
                program_id,
                attempt=attempt_no,
                continue_attempt=attempt_no,
                continue_type=used_continue_type,
                resource=used_resource,
                phase="pre_race_end_probe",
            )
            current_state = continued

        if not resources_used:
            return None, None, attempted

        try:
            end_result = self._run_continued_race(
                client,
                current_state,
                current_turn,
                program_id,
                strategy=strategy,
                race_start_info=race_start_info,
            )
        except Exception as exc:
            self._log("race_continue_abort", current_turn, f"pre-end probe replay failed: {exc}")
            self._add_race_continue_event(
                "race_continue_abort",
                current_turn,
                program_id,
                attempt=self._safe_int(self.status.get("race_retries")),
                resource=resources_used[-1] if resources_used else None,
                error=str(exc),
                phase="pre_race_end_probe",
            )
            try:
                fresh = self._fresh_career_state(client, strategy)
                return fresh, self._race_result_from_response(fresh, current_turn, program_id), attempted
            except Exception:
                return current_state, self._race_result_from_response(current_state, current_turn, program_id), attempted

        race_result = self._race_result_from_response(end_result, current_turn, program_id)
        race_result = self._annotate_race_continue_result(race_result, resources_used, [])
        if race_result and not race_result.get("won") and len(resources_used) >= cfg["consecutive_limit"]:
            self._log("race_continue_skip", current_turn, "race consecutive retry limit reached (pre-race-end probe)")
            self._add_race_continue_event(
                "race_continue_skip",
                current_turn,
                program_id,
                reason="race_consecutive_retry_limit_reached",
                limit=cfg["consecutive_limit"],
                failed_result=dict(race_result),
                phase="pre_race_end_probe",
            )
        return end_result, race_result, attempted

    def _resolve_race_end_with_retries(self, client, end_result, current_turn, program_id, preset, strategy=None, race_start_info=None):
        race_result = self._race_result_from_response(end_result, current_turn, program_id)
        if not race_result or race_result.get("won"):
            return end_result, race_result

        cfg = self._race_continue_config(preset)
        if cfg["limit"] <= 0:
            return end_result, race_result
        if self._race_continue_remaining(preset) <= 0:
            self._log("race_continue_skip", current_turn, "career retry limit reached")
            self._add_race_continue_event(
                "race_continue_skip",
                current_turn,
                program_id,
                reason="career_retry_limit_reached",
                limit=cfg["limit"],
                failed_result=dict(race_result),
            )
            return end_result, race_result

        race_attempt_index = 1
        resources_used = []
        failed_ranks = []
        while (
            self._race_continue_remaining(preset) > 0
            and len(resources_used) < cfg["consecutive_limit"]
            and race_result
            and not race_result.get("won")
        ):
            info = self._race_continue_info(end_result)
            if "available_continue_num" in info and info["available_continue_num"] <= 0:
                self._log("race_continue_skip", current_turn, "server reports no retries left")
                self._add_race_continue_event(
                    "race_continue_skip",
                    current_turn,
                    program_id,
                    reason="no_retries_left",
                    continue_info=info,
                    failed_result=dict(race_result),
                )
                break

            attempt_no = self._safe_int(self.status.get("race_retries")) + 1
            failed_rank = self._safe_int(race_result.get("finish_rank") or race_result.get("result_rank"))
            continued = None
            used_resource = None
            used_continue_type = None
            last_error = None

            for continue_type, resource in self._race_continue_attempt_types(preset, info, program_id=program_id):
                try:
                    self._log("race_continue", current_turn, f"{resource} attempt {attempt_no} after #{failed_rank}")
                    self._add_race_continue_event(
                        "race_continue_attempt",
                        current_turn,
                        program_id,
                        attempt=attempt_no,
                        continue_type=continue_type,
                        resource=resource,
                        continue_info=info,
                        failed_result=dict(race_result),
                    )
                    self._prepare_race_continue_resource(
                        client,
                        preset,
                        resource,
                        current_turn,
                        program_id,
                        info,
                    )
                    self._wait_before_race_continue(preset)
                    continued = client.race_continue(current_turn=current_turn, continue_type=continue_type)
                    used_resource = resource
                    used_continue_type = continue_type
                    break
                except Exception as exc:
                    last_error = str(exc)
                    err_str = str(exc)
                    # Pull a fresh load_career response so we can log what the
                    # game thinks is true RIGHT NOW (item counts, retry quota,
                    # playing_state) — the existing `info` is from the original
                    # race_end which may be stale by the time we 500.
                    diagnostic = {}
                    try:
                        fresh = client.load_career()
                        fdata = (fresh or {}).get("data") or {}
                        fhome = fdata.get("home_info") or {}
                        fchara = fdata.get("chara_info") or {}
                        fitems = fdata.get("item_list") or []
                        diagnostic = {
                            "available_continue_num":      self._safe_int(fhome.get("available_continue_num")),
                            "available_free_continue_num": self._safe_int(fhome.get("available_free_continue_num")),
                            "free_continue_num":           self._safe_int(fhome.get("free_continue_num")),
                            "free_continue_time":          self._safe_int(fhome.get("free_continue_time")),
                            "playing_state":               self._safe_int(fchara.get("playing_state")),
                            "state":                       self._safe_int(fchara.get("state")),
                            "current_turn":                self._safe_int(fchara.get("turn")),
                            "race_program_id":             self._safe_int(fchara.get("race_program_id")),
                            "inventory_size":              len(fitems) if isinstance(fitems, list) else 0,
                        }
                    except Exception as diag_exc:
                        diagnostic = {"diagnostic_fetch_error": str(diag_exc)[:120]}

                    self._log(
                        "race_continue_failed",
                        current_turn,
                        f"{resource}/{continue_type}: {exc} | game_state={diagnostic}",
                    )
                    self._add_race_continue_event(
                        "race_continue_failed",
                        current_turn,
                        program_id,
                        attempt=attempt_no,
                        continue_type=continue_type,
                        resource=resource,
                        error=str(exc),
                        continue_info=info,
                        diagnostic=diagnostic,
                        failed_result=dict(race_result),
                    )

                    if "API error 500" in err_str:
                        # A 500 here means the server rejected /continue in the
                        # current state. In real traces this happens after the
                        # bot has already accepted race_end, not because alarm
                        # clocks are permanently unavailable. Keep resources
                        # enabled for later races and stop only this retry path.
                        self._add_race_continue_event(
                            "race_continue_rejected",
                            current_turn,
                            program_id,
                            attempt=attempt_no,
                            continue_type=continue_type,
                            resource=resource,
                            reason="server_rejected_continue_after_race_end",
                            continue_info=info,
                            diagnostic=diagnostic,
                            failed_result=dict(race_result),
                        )
                        self._log(
                            "race_continue_rejected",
                            current_turn,
                            f"{resource}/{continue_type}: server rejected continue in current race state; resource remains enabled",
                        )
                        break

                    # Blacklist only terminal resource/state errors. These mean
                    # this resource type cannot currently be used; generic 500s
                    # are handled above as timing/state rejects for this race.
                    if "API error 1801" in err_str or "API error 1802" in err_str:
                        disabled = self.status.setdefault("disabled_continue_resources", [])
                        if resource not in disabled:
                            disabled.append(resource)
                            self._log(
                                "race_continue_disabled",
                                current_turn,
                                f"{resource} disabled for this career after server error ({err_str[:80]})",
                            )
                        # If the diagnostic says the server reports zero retries
                        # remaining, abort the inner loop too — no point trying
                        # the next resource type.
                        if isinstance(diagnostic, dict) and diagnostic.get("available_continue_num") == 0:
                            self._log(
                                "race_continue_abort",
                                current_turn,
                                "fresh game-state shows available_continue_num=0; bailing out",
                            )
                            break

            if continued is None:
                detail = last_error or "continue endpoint returned no state"
                self._log("race_continue_abort", current_turn, detail)
                break

            self._record_race_attempt_result(
                current_turn,
                program_id,
                race_result,
                race_attempt_index,
                continued_with=used_resource,
                continue_type=used_continue_type,
                continue_attempt=attempt_no,
            )
            self._log("race_continue_used", current_turn, f"{used_resource} #{attempt_no} after #{failed_rank}")
            self._add_race_continue_event(
                "race_continue_used",
                current_turn,
                program_id,
                attempt=race_attempt_index,
                continue_attempt=attempt_no,
                continue_type=used_continue_type,
                resource=used_resource,
                failed_rank=failed_rank,
            )
            failed_ranks.append(failed_rank)
            with self.lock:
                self.status["race_retries"] = self._safe_int(self.status.get("race_retries")) + 1
                if used_resource == "free_retry":
                    self.status["free_race_retries"] = self._safe_int(self.status.get("free_race_retries")) + 1
                elif used_resource == "carats":
                    self.status["carat_race_retries"] = self._safe_int(self.status.get("carat_race_retries")) + 1
                elif used_resource == "carat_alarm_clock":
                    self.status["carat_race_retries"] = self._safe_int(self.status.get("carat_race_retries")) + 1
                    self.status["alarm_clocks_used"] = self._safe_int(self.status.get("alarm_clocks_used")) + 1
                elif used_resource == "alarm_clock":
                    self.status["alarm_clocks_used"] = self._safe_int(self.status.get("alarm_clocks_used")) + 1
            resources_used.append(used_resource)
            race_attempt_index += 1

            try:
                end_result = self._run_continued_race(
                    client,
                    continued,
                    current_turn,
                    program_id,
                    strategy=strategy,
                    race_start_info=race_start_info or ((end_result.get("data") or {}).get("race_start_info") or {}),
                )
            except Exception as exc:
                self._log("race_continue_abort", current_turn, f"retry race failed: {exc}")
                self._add_race_continue_event(
                    "race_continue_abort",
                    current_turn,
                    program_id,
                    attempt=attempt_no,
                    resource=used_resource,
                    error=str(exc),
                )
                break

            race_result = self._race_result_from_response(end_result, current_turn, program_id)
            race_result = self._annotate_race_continue_result(race_result, resources_used, failed_ranks)
            label = self._race_result_label(race_result)
            self._log("race_retry_result", current_turn, f"attempt {attempt_no}: {label or 'unknown'}")
            self._add_race_continue_event(
                "race_retry_result",
                current_turn,
                program_id,
                attempt=attempt_no,
                resource=used_resource,
                result=dict(race_result or {}),
                label=label,
            )
            if not race_result:
                break

        if race_result and not race_result.get("won") and len(resources_used) >= cfg["consecutive_limit"]:
            self._log("race_continue_skip", current_turn, "race consecutive retry limit reached")
            self._add_race_continue_event(
                "race_continue_skip",
                current_turn,
                program_id,
                reason="race_consecutive_retry_limit_reached",
                limit=cfg["consecutive_limit"],
                failed_result=dict(race_result),
            )

        race_result = self._annotate_race_continue_result(race_result, resources_used, failed_ranks)
        return end_result, race_result

    def _record_race_result(self, turn, program_id, result):
        if not result:
            return
        turn = self._safe_int(result.get("turn") or turn)
        program_id = self._safe_int(result.get("program_id") or program_id)
        style_context = self._race_style_context_for(turn, program_id)
        if style_context:
            result = dict(result)
            result.setdefault("desired_running_style", style_context.get("desired_style") or "")
            result.setdefault("running_style", self._safe_int(style_context.get("applied_running_style")))
            result.setdefault("style_change", dict(style_context))
        # Always populate a short, UI-friendly style label so the operator
        # can see at a glance which strat each race used in the turn data.
        # Priority: applied numeric (from style_context) → desired style
        # name → result's own running_style code → last-seen turn vision's
        # race_running_style (so races where the bot didn't issue a style
        # change still get a label).
        from career_bot.race_schedule import running_style_label as _running_style_label
        result = dict(result)
        style_label = ""
        for candidate in (
            (style_context or {}).get("applied_running_style"),
            (style_context or {}).get("desired_style"),
            result.get("running_style"),
            result.get("desired_running_style"),
            self._latest_vision_running_style(turn),
        ):
            style_label = _running_style_label(candidate)
            if style_label:
                break
        if style_label:
            result["running_style_label"] = style_label
        label = self._race_result_label(result)
        already_recorded = False
        with self.lock:
            history = self.status.setdefault("action_history", [])
            for row in reversed(history):
                if row.get("action") != "race":
                    continue
                if turn and self._safe_int(row.get("turn")) != turn:
                    continue
                row_program_id = self._safe_int(row.get("program_id"))
                if program_id and row_program_id and row_program_id != program_id:
                    continue
                previous_rank = self._safe_int(row.get("result_rank"))
                if previous_rank and previous_rank == self._safe_int(result.get("finish_rank") or result.get("result_rank")):
                    already_recorded = True
                    break
                row["race_result"] = dict(result)
                row["result_rank"] = result.get("finish_rank") or result.get("result_rank")
                row["won"] = bool(result.get("won"))
                row["detail"] = label or row.get("detail", "")
                if style_context:
                    row["running_style"] = self._safe_int(style_context.get("applied_running_style"))
                    row["desired_running_style"] = style_context.get("desired_style") or ""
                    row["style_change"] = dict(style_context)
                # Always promote the friendly label onto the row so the
                # turn-data viewer shows "Front" / "Pace" / "Late" / "End"
                # next to every race, even when no style change fired.
                if result.get("running_style_label"):
                    row["running_style_label"] = result["running_style_label"]
                break
        if already_recorded:
            return
        self._log("race_result", turn, label)
        # Append to the cross-career race attempt ledger. Best-effort —
        # failures here mustn't kill a career. The ledger is read by
        # learning.py to attach `diagnosis` fields to per-race hints
        # and to flag chronic-loss races as `chronic=true` for the
        # dashboard.
        try:
            from career_bot.race_attempt_history import record_race_attempt
            runtime_root = runtime_output_root(self.base_dir)
            race_info_for_history = self._race_info_for_program(program_id)
            record_race_attempt(
                runtime_root,
                program_id=program_id,
                race_name=race_info_for_history.get("name") or "",
                finish_rank=self._safe_int(result.get("finish_rank") or result.get("result_rank")),
                turn=turn,
                career_started_at=(self.report or {}).get("started_at") if isinstance(self.report, dict) else None,
                is_g1=str(race_info_for_history.get("grade") or "").upper() == "G1",
            )
        except Exception:
            pass
        if self.report:
            race_info = self._race_info_for_program(program_id)
            is_g1 = str(race_info.get("grade") or "").upper() == "G1"
            row = {
                "event": "race_result",
                "turn": turn,
                "program_id": program_id,
                "race": race_info,
                "is_g1": is_g1,
                "finish_rank": result.get("finish_rank") or result.get("result_rank"),
                "won": bool(result.get("won")),
                "status": result.get("status"),
                "label": label,
                "source": result.get("source"),
            }
            if style_context:
                row["running_style"] = self._safe_int(style_context.get("applied_running_style"))
                row["desired_running_style"] = style_context.get("desired_style") or ""
                row["style_change"] = dict(style_context)
            # Same UI label for the report event so downstream consumers
            # (turn-data viewer, g1_result rollups, analytics) get the
            # readable strat without decoding the numeric tactic code.
            if result.get("running_style_label"):
                row["running_style_label"] = result["running_style_label"]
            for key in ("continued", "continue_attempts", "continue_resources", "continue_resource", "continue_failed_ranks"):
                if key in result:
                    row[key] = result.get(key)
            add_event(self.report, row)
            if is_g1:
                g1_row = dict(row)
                g1_row["event"] = "g1_result"
                add_event(self.report, g1_row)

    def _turn_stats(self, chara):
        if not chara:
            return {}
        return {
            "hp": int(chara.get("vital") or 0),
            "max_hp": int(chara.get("max_vital") or 100),
            "motivation": int(chara.get("motivation") or 0),
            "speed": int(chara.get("speed") or 0),
            "stamina": int(chara.get("stamina") or 0),
            "power": int(chara.get("power") or 0),
            "guts": int(chara.get("guts") or 0),
            "wit": int(chara.get("wiz") or 0),
            "skill_point": int(chara.get("skill_point") or 0),
        }

    def _format_turn_stats(self, stats):
        if not stats:
            return ""
        return (
            f"HP {stats['hp']}/{stats['max_hp']} | "
            f"MOOD {stats['motivation']} | "
            f"SPD {stats['speed']} STA {stats['stamina']} PWR {stats['power']} "
            f"GUT {stats['guts']} WIT {stats['wit']} SP {stats['skill_point']}"
        )

    def _partner_bonds(self, chara):
        result = {}
        for row in (chara or {}).get("evaluation_info_array") or []:
            partner_id = self._safe_int(row.get("target_id"))
            if partner_id:
                result[partner_id] = self._safe_int(row.get("evaluation"))
        return result

    def _command_stat_deltas(self, command):
        gains = {key: 0 for key in STAT_FALLBACK_FIELDS}
        gains["hp"] = 0
        for item in (command or {}).get("params_inc_dec_info_array") or []:
            key = STAT_TARGET_NAMES.get(self._safe_int(item.get("target_type")))
            if key:
                gains[key] = gains.get(key, 0) + self._safe_int(item.get("value"))

        for key, fields in STAT_FALLBACK_FIELDS.items():
            if gains.get(key):
                continue
            for field in fields:
                value = self._safe_int((command or {}).get(field))
                if value:
                    gains[key] += value
                    break
        return {key: value for key, value in gains.items() if value}

    def _active_item_effects(self, state):
        data = (state or {}).get("data") or {}
        free = data.get("free_data_set") or {}
        effects = []
        for eff in free.get("item_effect_array") or []:
            item_id = self._safe_int(eff.get("item_id") or eff.get("effect_item_id"))
            row = {
                "item_id": item_id,
                "name": ITEM_NAMES.get(item_id, ""),
            }
            for key in (
                "item_effect_id",
                "effect_type",
                "target_type",
                "value",
                "effect_value",
                "turn",
                "remain_turn",
                "remaining_turn",
                "left_turn",
                "limit_turn",
                "end_turn",
            ):
                if key in eff:
                    row[key] = eff.get(key)
            effects.append(row)
        return effects

    def _training_facility_info(self, chara, command):
        command_id = self._safe_int((command or {}).get("command_id"))
        if not command_id:
            return (0, 0, -1)
        command_idx = TRAINING_COMMANDS.get(command_id)
        matched = None
        for position, row in enumerate((chara or {}).get("training_level_info_array") or []):
            row_command_id = self._safe_int((row or {}).get("command_id"))
            row_idx = TRAINING_COMMANDS.get(row_command_id)
            if row_command_id == command_id:
                matched = row
                break
            if command_idx is not None and row_idx == command_idx:
                matched = row
                break
            if command_idx is not None and not row_command_id and position == command_idx:
                matched = row
                break
        if not isinstance(matched, dict):
            level = self._safe_int((command or {}).get("level"))
            return (level, 0, max(0, 4) if 0 < level < 5 else -1)
        level = max(1, min(5, self._safe_int(matched.get("level") or matched.get("facility_level") or (command or {}).get("level") or 1)))
        progress = 0
        for key in ("progress", "facility_progress", "training_progress", "count"):
            if matched.get(key) is not None:
                progress = max(0, min(3, self._safe_int(matched.get(key))))
                break
        else:
            for key in ("training_count", "failure_num", "total_training_count"):
                if matched.get(key) is not None:
                    progress = max(0, self._safe_int(matched.get(key)) % 4)
                    break
        until_next = max(0, 4 - progress) if level < 5 else -1
        return (level, progress, until_next)

    def _training_snapshot(self, state, preset):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        home = data.get("home_info") or {}
        bonds = self._partner_bonds(chara)
        trainings = []
        for command in home.get("command_info_array") or []:
            if self._safe_int(command.get("command_type")) != 1:
                continue
            command_id = self._safe_int(command.get("command_id"))
            if command_id not in TRAINING_LABELS:
                continue
            hints = {self._safe_int(value) for value in command.get("tips_event_partner_array") or []}
            partners = []
            for raw_partner_id in command.get("training_partner_array") or []:
                partner_id = self._safe_int(raw_partner_id)
                if not partner_id:
                    continue
                bond = bonds.get(partner_id, 0)
                deck_partner = partner_id in DECK_PARTNER_IDS
                partners.append({
                    "target_id": partner_id,
                    "bond": bond,
                    "deck_partner": deck_partner,
                    "rainbow": deck_partner and bond >= 80,
                    "hint": partner_id in hints,
                })

            stat_gain = self._command_stat_deltas(command)
            total_gain = self.item_manager._command_stat_gain(command, sp_weight=0.5)
            enabled_value = command.get("is_enable")
            facility_level, facility_progress, facility_until_next = self._training_facility_info(chara, command)
            row = {
                "command_id": command_id,
                "command_group_id": self._safe_int(command.get("command_group_id")),
                "name": TRAINING_LABELS.get(command_id, str(command_id)),
                "level": self._safe_int(command.get("level")),
                "facility_level": facility_level,
                "facility_progress": facility_progress,
                "facility_until_next_level": facility_until_next,
                "enabled": True if enabled_value is None else bool(self._safe_int(enabled_value)),
                "failure_rate": self._safe_int(command.get("failure_rate")),
                "stat_gain": stat_gain,
                "weighted_total_gain": total_gain,
                "partners": partners,
                "partner_count": len(partners),
                "deck_partner_count": sum(1 for partner in partners if partner.get("deck_partner")),
                "rainbow_count": sum(1 for partner in partners if partner.get("rainbow")),
                "hint_count": sum(1 for partner in partners if partner.get("hint")),
                "high_bond_count": sum(1 for partner in partners if self._safe_int(partner.get("bond")) >= 80),
            }
            trainings.append(row)

        enabled = [row for row in trainings if row.get("enabled")]
        best = max(
            enabled,
            key=lambda row: (
                float(row.get("weighted_total_gain") or 0),
                self._safe_int(row.get("rainbow_count")),
                self._safe_int(row.get("hint_count")),
                -self._safe_int(row.get("failure_rate")),
            ),
            default=None,
        )
        best_training = None
        if best:
            best_training = {
                "command_id": best.get("command_id"),
                "name": best.get("name"),
                "failure_rate": best.get("failure_rate"),
                "weighted_total_gain": best.get("weighted_total_gain"),
                "rainbow_count": best.get("rainbow_count"),
                "hint_count": best.get("hint_count"),
            }
        return {
            "turn": self._safe_int(chara.get("turn")),
            "stats": self._turn_stats(chara),
            "active_item_effects": self._active_item_effects(state),
            "trainings": trainings,
            "best_training": best_training,
        }

    def _race_info_for_program(self, program_id):
        program_id = self._safe_int(program_id)
        if not program_id or not self.race_planner:
            return {"program_id": program_id}
        race = dict(self.race_planner.catalog.by_program_id.get(program_id) or {})
        program = dict((self.race_planner.program or {}).get(program_id) or {})
        race_instance_id = self._safe_int(race.get("race_instance_id") or program.get("race_instance_id"))
        grade = race.get("type") or program.get("type") or ""
        if not grade and race_instance_id:
            first_digit = str(race_instance_id)[0]
            grade = {"1": "G1", "2": "G2", "3": "G3", "4": "OP"}.get(first_digit, "")
        return {
            "program_id": program_id,
            "race_id": self._safe_int(race.get("id") or program.get("race_id")),
            "race_instance_id": race_instance_id,
            "name": race.get("name") or program.get("name") or "",
            "date": race.get("date") or "",
            "turn": self._safe_int(race.get("turn") or program.get("turn")),
            "grade": grade,
            "terrain": race.get("terrain") or program.get("terrain") or "",
            "distance": race.get("distance") or program.get("distance") or "",
            "venue": race.get("venue") or program.get("venue") or "",
        }

    def _is_g1_program(self, program_id):
        info = self._race_info_for_program(program_id)
        return str(info.get("grade") or "").upper() == "G1"

    def _is_final_career_race(self, current_turn=0, program_id=0, race_start_info=None):
        current_turn = self._safe_int(current_turn)
        program_id = self._safe_int(program_id)
        race_start_info = race_start_info or {}
        info = self._race_info_for_program(program_id)
        name = str(info.get("name") or race_start_info.get("race_name") or "").lower()
        race_instance_id = self._safe_int(
            info.get("race_instance_id")
            or race_start_info.get("race_instance_id")
            or race_start_info.get("race_id")
        )
        # MANT/Trackblazer finishes after Twinkle Star Climax Race 3 on turn 78.
        # Some load states keep stale race metadata after the server already accepted
        # the result, so this helper lets reconciliation move into finish instead of
        # stopping forever on a harmless race_out 102.
        return (
            current_turn >= 78
            or program_id == 2509
            or race_instance_id == 920091
            or "twinkle star climax race 3" in name
        )

    def _finish_after_final_race_if_ready(self, client, state, preset, strategy, current_turn, program_id, race_start_info=None, reason="final race reconciled"):
        if not self._is_final_career_race(current_turn, program_id, race_start_info):
            return None
        race_result = self._race_result_from_response(state, current_turn, program_id)
        if race_result:
            self._record_race_result(current_turn, program_id, race_result)
        if not self._is_career_finish_state(state) and not (race_result and race_result.get("won")):
            return None
        self._log("finish_detected", current_turn, reason)
        return self._finish_career(client, state, preset or {}, strategy, current_turn)

    def _race_snapshot(self, state, preset, program_id, current_turn, phase, item_context=None, result=None):
        race_info = self._race_info_for_program(program_id)
        entry = self.race_planner.entry_for_program(preset, current_turn, program_id) if self.race_planner else None
        stamina_check = None
        if self.race_planner:
            previous = self.race_planner.last_stamina_check
            try:
                stamina_check = self.race_planner.stamina_for_program(state, preset, program_id, entry or {})
            except Exception as exc:
                stamina_check = {"error": str(exc)}
            finally:
                self.race_planner.last_stamina_check = previous
        snapshot = {
            "phase": phase,
            "race": race_info,
            "entry": entry or {},
            "stats": self._turn_stats(((state or {}).get("data") or {}).get("chara_info") or {}),
            "active_item_effects": self._active_item_effects(state),
            "stamina_check": stamina_check or {},
        }
        if item_context:
            snapshot["item_context"] = item_context
        if result:
            snapshot["result"] = dict(result)
        return snapshot

    def _blocked_playing_state(self, chara):
        playing_state = int((chara or {}).get("playing_state") or 1)
        return playing_state not in {1, 2, 3, 4, 5}

    def _recover_blocked_state(self, client, strategy, state):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        if int(chara.get("playing_state") or 0) == 6:
            turn = chara.get("turn", 1)
            if hasattr(client, "minigame_end"):
                state = client.minigame_end(current_turn=turn)
            else:
                state = client.call("single_mode_free/minigame_end", {
                    "result": {
                        "result_state": 1,
                        "result_value": 0,
                        "result_detail_array": None,
                    },
                    "current_turn": turn,
                })
            data = state.get("data") or {}
            if data.get("unchecked_event_array"):
                state = self._drain_events(client, strategy, state)
            return state
        try:
            if hasattr(client, "hard_reset"):
                state = client.hard_reset()
            else:
                state = self._fresh_career_state(client, strategy)
        except Exception as e:
            print(f"Blocked State Recovery Failure: {e}")
            return state
        return state

    def _debug_turn(self, state, preset):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        free = data.get("free_data_set") or {}
        self.skill_buyer.preview(state, preset)
        self._debug("turn", state, {
            "training_snapshot": self._training_snapshot(state, preset),
            "bot_race_skip_reason": getattr(self.race_planner, "last_skip_reason", None),
            "active_item_effects": self._active_item_effects(state),
            "owned_skills": self._debug_owned_skills(state),
            "inventory": self._debug_inventory(state),
            "server_skill_tips_raw": chara.get("skill_tips_array") or [],
            "server_owned_skill_raw": chara.get("skill_array") or [],
            "skill_rows_enriched": self._debug_skill_options(state, preset),
            "bot_skill_candidates": list(self.skill_buyer.last_candidates),
            "bot_skill_selected": list(self.skill_buyer.last_selected),
            "bot_skill_attempt": list(self.skill_buyer.last_attempt),
            "bot_skill_result": dict(self.skill_buyer.last_result),
            "server_shop_rows_raw": free.get("pick_up_item_info_array") or [],
            "shop_rows_enriched": self._debug_item_buy_options(state, preset),
            "bot_shop_candidates": list(self.item_manager.last_buy_options),
            "bot_shop_selected": list(self.item_manager.last_buy_selected),
            "bot_shop_attempt": list(self.item_manager.last_buy_attempt),
            "bot_shop_result": dict(self.item_manager.last_buy_result),
            "decision_item_use_rows": list(self.item_manager.last_use_options),
            "bot_item_use_selected": list(self.item_manager.last_use_selected),
            "bot_item_use_attempt": list(self.item_manager.last_use_attempt),
            "bot_item_use_result": dict(self.item_manager.last_use_result),
            "bot_item_use_decision_rationale": dict(getattr(self.item_manager, "last_use_decision_rationale", {}) or {}),
            # Career trajectory prediction — informational only. Reads
            # the trajectory_centroids that learn_preset built from
            # past careers and classifies the current career as
            # tracking_top / tracking_bottom / ambiguous / unknown.
            # Not consulted for any decision yet; surfaces in the log
            # so the user can validate whether the classifier matches
            # their gut feeling about how a career is going.
            "trajectory_prediction": self._predict_trajectory(chara, preset),
        })

    def _predict_trajectory(self, chara, preset):
        """Return a trajectory prediction dict for the current turn.

        Pulls centroids off the preset and the current career's stats
        off chara_info. Returns {"label": "unknown"} when there are no
        centroids or no usable stats — never raises so the per-turn log
        always succeeds.
        """
        if not isinstance(preset, dict):
            return {"label": "unknown"}
        centroids = preset.get("trajectory_centroids")
        if not centroids:
            return {"label": "unknown"}
        try:
            from career_bot.career_trajectory_prediction import predict_trajectory
        except Exception:
            return {"label": "unknown"}
        current_turn = self._safe_int(chara.get("turn"))
        if current_turn <= 0:
            return {"label": "unknown"}
        current_stats = {
            "speed": self._safe_int(chara.get("speed")),
            "stamina": self._safe_int(chara.get("stamina")),
            "power": self._safe_int(chara.get("power")),
            "guts": self._safe_int(chara.get("guts")),
            "wit": self._safe_int(chara.get("wiz") or chara.get("wit")),
            "hp": self._safe_int(chara.get("vital")),
            "skill_point": self._safe_int(chara.get("skill_point")),
        }
        try:
            return predict_trajectory(centroids, current_stats, current_turn)
        except Exception:
            return {"label": "unknown"}

    def _debug_skill_options(self, state, preset):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        points = int(chara.get("skill_point") or 0)
        owned = {int(item.get("skill_id") or 0) for item in chara.get("skill_array") or []}
        owned_groups = {self.skill_buyer.skill_to_group_id.get(skill_id, skill_id // 10) for skill_id in owned}
        priority = self.skill_buyer._priority_context(preset)
        blacklist = self.skill_buyer._blacklist(preset)
        preview_candidates = {
            int(item.get("skill_id") or 0): item
            for item in self.skill_buyer._candidates_with_fallback(chara, preset)
            if int(item.get("skill_id") or 0) > 0
        }
        exact_selected = {
            int(item.get("skill_id") or 0): item
            for item in list(getattr(self.skill_buyer, "last_selected", []) or [])
            if int(item.get("skill_id") or 0) > 0
        }
        exact_attempted = {
            int(item.get("skill_id") or 0): item
            for item in list(getattr(self.skill_buyer, "last_attempt", []) or [])
            if int(item.get("skill_id") or 0) > 0
        }
        selected_by_group = {}
        attempted_by_group = {}
        for row in exact_selected.values():
            group_id = int(row.get("group_id") or self.skill_buyer._candidate_group_id(row) or 0)
            if group_id > 0 and group_id not in selected_by_group:
                selected_by_group[group_id] = row
        for row in exact_attempted.values():
            group_id = int(row.get("group_id") or self.skill_buyer._candidate_group_id(row) or 0)
            if group_id > 0 and group_id not in attempted_by_group:
                attempted_by_group[group_id] = row
        result = []
        for tip in chara.get("skill_tips_array") or []:
            resolved = self.skill_buyer.resolve_skill_tip(tip, owned, owned_groups, priority, blacklist, preset)
            skill_id = int((resolved or {}).get("resolved_skill_id") or 0)
            group_id = int((resolved or {}).get("group_id") or tip.get("group_id") or 0)
            cost = int((resolved or {}).get("cost") or 0)
            preview_flag = skill_id in preview_candidates
            selected_flag = skill_id in exact_selected
            attempted_flag = skill_id in exact_attempted
            group_selected = selected_by_group.get(group_id)
            group_attempted = attempted_by_group.get(group_id)
            skip_reason = (resolved or {}).get("skip_reason")
            if not skip_reason and cost > points:
                skip_reason = "unaffordable"
            elif not skip_reason and not preview_flag:
                skip_reason = "rule_rejected"
            result.append({
                "skill_id": skill_id,
                "group_id": group_id,
                "tip_rarity": int((resolved or {}).get("tip_rarity") or tip.get("rarity") or 0),
                "hint_level": int((resolved or {}).get("hint_level") or tip.get("level") or 0),
                "candidate_skill_ids": (resolved or {}).get("candidate_skill_ids") or [],
                "name": (resolved or {}).get("resolved_name") or "",
                "default_resolved_skill_id": int((resolved or {}).get("default_resolved_skill_id") or 0),
                "default_resolved_name": (resolved or {}).get("default_resolved_name") or "",
                "priority_selected_skill_id": int((resolved or {}).get("priority_selected_skill_id") or 0),
                "priority_selected_name": (resolved or {}).get("priority_selected_name") or "",
                "priority_override_blocked": bool((resolved or {}).get("priority_override_blocked")),
                "cost": cost,
                "affordable": cost <= points,
                "owned_group": (resolved or {}).get("skip_reason") == "owned_group",
                "known": bool((resolved or {}).get("master_exists")),
                "failed_scope": (resolved or {}).get("failed_scope"),
                "preview_candidate": preview_flag,
                "selected": selected_flag,
                "attempted": attempted_flag,
                "group_selected": bool(group_selected),
                "group_attempted": bool(group_attempted),
                "selected_skill_id_in_group": int((group_selected or {}).get("skill_id") or 0),
                "selected_name_in_group": (group_selected or {}).get("name") or "",
                "attempted_skill_id_in_group": int((group_attempted or {}).get("skill_id") or 0),
                "attempted_name_in_group": (group_attempted or {}).get("name") or "",
                "resolution_reason": (resolved or {}).get("resolution_reason") or "",
                "skip_reason": skip_reason,
            })
        return result

    def _debug_owned_skills(self, state):
        chara = (state.get("data") or {}).get("chara_info") or {}
        result = []
        for row in chara.get("skill_array") or []:
            skill_id = int(row.get("skill_id") or 0)
            result.append({
                "skill_id": skill_id,
                "group_id": self.skill_buyer.skill_to_group_id.get(skill_id, skill_id // 10),
                "name": self.skill_buyer.skill_names.get(skill_id, ""),
            })
        return result

    def _debug_inventory(self, state):
        free = (state.get("data") or {}).get("free_data_set") or {}
        result = []
        for name, count in sorted(self.item_manager._owned_map(free).items()):
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id:
                continue
            result.append({
                "name": name,
                "item_id": item_id,
                "current_num": int(count),
                "failed_scope": "this_turn" if item_id in self.item_manager.failed_use_this_turn else None,
            })
        return result

    def _debug_item_buy_options(self, state, preset):
        data = state.get("data") or {}
        free = data.get("free_data_set") or {}
        current_turn = int((data.get("chara_info") or {}).get("turn") or 0)
        coin_val = free.get("coin_num")
        if coin_val is None:
            coin_val = free.get("gained_coin_num")
        budget = int(coin_val or 0)
        owned = self.item_manager._owned_map(free)
        result = []
        for row in free.get("pick_up_item_info_array") or []:
            shop_item_id = int(row.get("shop_item_id") or 0)
            item_id = int(row.get("item_id") or 0)
            name = ITEM_NAMES.get(item_id)
            if not name:
                continue
            limit_turn = int(row.get("limit_turn") or 0)
            cost = int(row.get("coin_num") or 0)
            original_cost = int(row.get("original_coin_num") or cost)
            bought = int(row.get("item_buy_num") or 0)
            limit = int(row.get("limit_buy_count") or 1)
            expired = limit_turn > 0 and current_turn > limit_turn
            rejected = shop_item_id in self.item_manager.failed_exchange_this_snapshot
            skip_buy = self.item_manager._skip_buy(name, owned, preset)
            skip_reason = None
            if expired:
                skip_reason = "expired"
            elif bought >= limit:
                skip_reason = "limit_reached"
            elif rejected:
                skip_reason = "rejected"
            elif skip_buy:
                skip_reason = "skip_buy"
            elif cost > budget:
                skip_reason = "unaffordable"
            result.append({
                "shop_item_id": shop_item_id,
                "item_id": item_id,
                "name": name,
                "cost": cost,
                "original_cost": original_cost,
                "mant_coin": budget,
                "affordable": cost <= budget,
                "current_num": bought,
                "limit": limit,
                "absolute_limit_turn": limit_turn,
                "server_turn_delta": (limit_turn - current_turn) if limit_turn > 0 else None,
                "ui_turns_left": None,
                "limit_reached": bought >= limit,
                "expired": expired,
                "rejected": rejected,
                "skip_buy": skip_buy,
                "selected": False,
                "skip_reason": skip_reason,
            })
        cfg = self.item_manager._mant_cfg(preset)
        tiers = cfg.get("item_tiers") or {}
        tier_count = int(cfg.get("tier_count") or 8)
        remaining_budget = budget
        for tier in range(1, tier_count + 1):
            tier_rows = [
                row for row in result
                if row.get("skip_reason") is None
                and not row.get("selected")
                and int(tiers.get(display_to_slug(row.get("name")), 999)) == tier
            ]
            tier_rows.sort(key=lambda row: (int(row.get("absolute_limit_turn") or 99), int(row.get("cost") or 9999)))
            for row in tier_rows:
                cost = int(row.get("cost") or 0)
                remaining = remaining_budget - cost
                if remaining < 0:
                    row["skip_reason"] = "unaffordable"
                    continue
                threshold = 0
                thresholds = cfg.get("tier_thresholds") or {}
                if tier > 1 and current_turn <= 64:
                    threshold = int(thresholds.get(str(tier), thresholds.get(tier, (tier - 1) * 50)) or 0)
                if threshold > 0 and remaining < threshold:
                    row["skip_reason"] = "rule_rejected"
                    continue
                row["selected"] = True
                remaining_budget = remaining
        return result

    def _error_snapshot_dir(self, category):
        return runtime_output_root(self.base_dir) / "error_snapshots" / str(category or "general")

    def _error_snapshot_default(self, value):
        if isinstance(value, bytes):
            return value.hex()
        if isinstance(value, set):
            return sorted(value)
        if isinstance(value, Path):
            return str(value)
        return str(value)

    def _safe_error_snapshot_section(self, name, builder, fallback):
        try:
            return builder()
        except Exception as exc:
            if isinstance(fallback, list):
                return [{"error": str(exc), "_inspector": name}]
            row = dict(fallback or {})
            row["error"] = str(exc)
            row["_inspector"] = name
            return row

    def _error_snapshot_slug(self, value):
        text = "".join(ch.lower() if str(ch).isalnum() else "_" for ch in str(value or ""))
        text = text.strip("_")
        return text[:64] or "unnamed"

    def _skill_buyer_debug_state(self):
        failed_by_turn = {}
        for turn, skill_ids in (getattr(self.skill_buyer, "failed_this_turn", {}) or {}).items():
            try:
                failed_by_turn[str(int(turn))] = sorted(int(skill_id) for skill_id in (skill_ids or set()))
            except Exception:
                failed_by_turn[str(turn)] = sorted(str(skill_id) for skill_id in (skill_ids or set()))
        return {
            "current_turn": getattr(self.skill_buyer, "current_turn", None),
            "failed_this_turn": failed_by_turn,
            "permanent_failed_skills": sorted(int(skill_id) for skill_id in (getattr(self.skill_buyer, "permanent_failed_skills", set()) or set())),
            "cross_career_failed_skills": {
                str(int(skill_id)): int(count)
                for skill_id, count in sorted((getattr(self.skill_buyer, "cross_career_failed_skills", {}) or {}).items())
            },
            "known_bought_skill_ids": sorted(int(skill_id) for skill_id in (getattr(self.skill_buyer, "known_bought_skill_ids", set()) or set())),
            "known_bought_group_ids": sorted(int(group_id) for group_id in (getattr(self.skill_buyer, "known_bought_group_ids", set()) or set())),
        }

    def _item_manager_debug_state(self):
        return {
            "current_turn": getattr(self.item_manager, "current_turn", None),
            "failed_exchange_this_snapshot": sorted(
                int(shop_item_id) for shop_item_id in (getattr(self.item_manager, "failed_exchange_this_snapshot", set()) or set())
            ),
            "persistent_failed_exchange_item_ids": {
                str(int(item_id)): int(count)
                for item_id, count in sorted((getattr(self.item_manager, "persistent_failed_exchange_item_ids", {}) or {}).items())
            },
            "failed_use_this_turn": sorted(
                int(item_id) for item_id in (getattr(self.item_manager, "failed_use_this_turn", set()) or set())
            ),
            "used_buffs": sorted(str(name) for name in (getattr(self.item_manager, "used_buffs", set()) or set())),
            "shop_snapshot_key": list(getattr(self.item_manager, "shop_snapshot_key", ()) or ()),
            "recover_after_exchange_error": bool(getattr(self.item_manager, "recover_after_exchange_error", False)),
            "recover_after_use_error": bool(getattr(self.item_manager, "recover_after_use_error", False)),
        }

    def _extract_error_codes(self, value):
        text = str(value or "")
        codes = []
        seen = set()
        for token in text.replace(":", " ").replace(",", " ").split():
            if not token.isdigit():
                continue
            code = int(token)
            if code in seen:
                continue
            seen.add(code)
            codes.append(code)
        return codes

    def _recent_report_turn(self, turn):
        report = self.report if isinstance(self.report, dict) else {}
        for row in report.get("turns") or []:
            if self._safe_int((row or {}).get("turn")) == self._safe_int(turn):
                return row
        return {}

    def _skill_snapshot_context(self, state, preset, skill_rows_enriched):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        points = int(chara.get("skill_point") or 0)
        priority_context = dict(self.skill_buyer._priority_context(preset or {}))
        blacklist = sorted(self.skill_buyer._blacklist(preset or {}))
        configured_priority_keys = sorted(self.skill_buyer._configured_priority_keys(preset or {}))
        owned_groups = sorted(int(group_id) for group_id in self.skill_buyer._owned_groups(chara))
        failed_groups = sorted(
            int(skill_id)
            for skill_id in (self.skill_buyer._failed_for_turn(int(chara.get("turn") or 0)) or set())
            if str(skill_id).lstrip("-").isdigit()
        )
        selected = list(getattr(self.skill_buyer, "last_selected", []) or [])
        attempted = list(getattr(self.skill_buyer, "last_attempt", []) or [])
        candidates = list(getattr(self.skill_buyer, "last_candidates", []) or [])
        rows_by_skill_id = {
            int(row.get("skill_id") or 0): row
            for row in skill_rows_enriched or []
            if int((row or {}).get("skill_id") or 0) > 0
        }
        rows_by_group_id = {}
        for row in skill_rows_enriched or []:
            group_id = int((row or {}).get("group_id") or 0)
            if group_id > 0:
                rows_by_group_id.setdefault(group_id, []).append(row)
        preflight_rejections = []
        attempted_ids = {int(row.get("skill_id") or 0) for row in attempted}
        for row in selected:
            skill_id = int(row.get("skill_id") or 0)
            if skill_id in attempted_ids:
                continue
            group_id = int(row.get("group_id") or self.skill_buyer._candidate_group_id(row) or 0)
            resolved = rows_by_skill_id.get(skill_id, {})
            resolved_group_rows = rows_by_group_id.get(group_id, [])
            preflight_rejections.append({
                "skill_id": skill_id,
                "group_id": group_id,
                "name": row.get("name") or "",
                "cost": int(row.get("cost") or 0),
                "candidate_reason": row.get("preflight_error") or row.get("skip_reason") or "",
                "resolver_reason": resolved.get("skip_reason") or resolved.get("resolution_reason") or "",
                "resolver_row": resolved,
                "resolver_group_rows": resolved_group_rows,
                "selected_matches_live_resolved_row": bool(resolved) and int(resolved.get("skill_id") or 0) == skill_id,
                "owned_group": group_id in owned_groups,
            })
        selected_variants = []
        variant_source = selected or candidates
        for row in variant_source:
            try:
                variants = self.skill_buyer._final_candidate_variants(row, points)
            except Exception as exc:
                variants = [{"error": str(exc), "_inspector": "final_candidate_variants"}]
            selected_variants.append({
                "skill_id": int(row.get("skill_id") or 0),
                "group_id": int(row.get("group_id") or self.skill_buyer._candidate_group_id(row) or 0),
                "name": row.get("name") or "",
                "budget": points,
                "variants": variants,
            })
        variant_mismatches = []
        for source_name, source_rows in (("selected", selected), ("attempted", attempted)):
            for row in source_rows:
                skill_id = int(row.get("skill_id") or 0)
                group_id = int(row.get("group_id") or self.skill_buyer._candidate_group_id(row) or 0)
                resolved_group_rows = rows_by_group_id.get(group_id, [])
                resolved_ids = [
                    int(resolved_row.get("skill_id") or 0)
                    for resolved_row in resolved_group_rows
                    if int((resolved_row or {}).get("skill_id") or 0) > 0
                ]
                if resolved_ids and skill_id not in resolved_ids:
                    variant_mismatches.append({
                        "source": source_name,
                        "group_id": group_id,
                        "skill_id": skill_id,
                        "name": row.get("name") or "",
                        "resolved_skill_ids": resolved_ids,
                        "resolved_rows": resolved_group_rows,
                        "candidate_row": row,
                    })
        tip_group_summary = []
        tip_rows = chara.get("skill_tips_array") or []
        for tip in tip_rows:
            group_id = int(tip.get("group_id") or 0)
            tip_group_summary.append({
                "group_id": group_id,
                "rarity": int(tip.get("rarity") or 0),
                "hint_level": int(tip.get("level") or 0),
                "resolved_rows": rows_by_group_id.get(group_id, []),
            })
        return {
            "skill_point": points,
            "learn_skill_threshold": int((preset or {}).get("learn_skill_threshold") or 444),
            "manual_purchase_at_end": bool((preset or {}).get("manual_purchase_at_end")),
            "priority_context": priority_context,
            "configured_priority_keys": configured_priority_keys,
            "blacklist": blacklist,
            "owned_groups": owned_groups,
            "failed_groups_or_skills_this_turn": failed_groups,
            "tip_group_summary": tip_group_summary,
            "selected_variants_under_current_budget": selected_variants,
            "preflight_rejections": preflight_rejections,
            "selected_or_attempted_group_variant_mismatches": variant_mismatches,
            "selected_skill_ids": sorted(int(row.get("skill_id") or 0) for row in selected if int(row.get("skill_id") or 0) > 0),
            "attempted_skill_ids": sorted(int(row.get("skill_id") or 0) for row in attempted if int(row.get("skill_id") or 0) > 0),
            "rejected_skill_rows": [row for row in (skill_rows_enriched or []) if row.get("skip_reason")],
        }

    def _item_snapshot_context(self, state, preset, shop_rows_enriched):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        free = data.get("free_data_set") or {}
        current_turn = int(chara.get("turn") or 0)
        owned_map = dict(self.item_manager._owned_map(free))
        raw_shop_rows = free.get("pick_up_item_info_array") or []
        raw_shop_by_sid = {int(row.get("shop_item_id") or 0): row for row in raw_shop_rows}
        budget = int(free.get("coin_num") if free.get("coin_num") is not None else free.get("gained_coin_num") or 0)
        buy_attempts = []
        for attempt in list(getattr(self.item_manager, "last_buy_attempt", []) or []):
            shop_item_id = int(attempt.get("shop_item_id") or 0)
            shop_row = raw_shop_by_sid.get(shop_item_id, {})
            item_id = int(shop_row.get("item_id") or self.item_manager._resolve_item_id_for_shop_item(shop_item_id) or 0)
            name = ITEM_NAMES.get(item_id, "")
            inventory_count = int(owned_map.get(name, 0)) if name else 0
            shop_buy_count = int(shop_row.get("item_buy_num") or 0)
            buy_attempts.append({
                "attempt": attempt,
                "shop_row": shop_row,
                "item_id": item_id,
                "name": name,
                "inventory_count": inventory_count,
                "shop_buy_count": shop_buy_count,
                "current_num_matches_inventory_count": int(attempt.get("current_num") or 0) == inventory_count,
                "current_num_matches_shop_buy_count": int(attempt.get("current_num") or 0) == shop_buy_count,
                "limit_buy_count": int(shop_row.get("limit_buy_count") or 0),
                "limit_turn": int(shop_row.get("limit_turn") or 0),
                "expired": int(shop_row.get("limit_turn") or 0) > 0 and int(shop_row.get("limit_turn") or 0) < current_turn,
                "affordable_at_snapshot": int(shop_row.get("coin_num") or 0) <= budget,
            })
        use_attempts = []
        inventory_rows = {int(row.get("item_id") or 0): row for row in free.get("user_item_info_array") or []}
        for attempt in list(getattr(self.item_manager, "last_use_attempt", []) or []) + list(getattr(self.item_manager, "last_pre_race_use_attempt", []) or []):
            item_id = int(attempt.get("item_id") or 0)
            inventory_row = inventory_rows.get(item_id, {})
            use_attempts.append({
                "attempt": attempt,
                "name": ITEM_NAMES.get(item_id, ""),
                "inventory_row": inventory_row,
                "available_at_snapshot": int(inventory_row.get("num") or inventory_row.get("current_num") or inventory_row.get("item_num") or 0),
                "requested_use_num": int(attempt.get("use_num") or 0),
                "current_num_matches_inventory_count": int(attempt.get("current_num") or 0) == int(inventory_row.get("num") or inventory_row.get("current_num") or inventory_row.get("item_num") or 0),
            })
        cfg = self.item_manager._mant_cfg(preset or {})
        last_buy_options = list(getattr(self.item_manager, "last_buy_options", []) or [])
        last_buy_selected = list(getattr(self.item_manager, "last_buy_selected", []) or [])
        last_buy_attempt = list(getattr(self.item_manager, "last_buy_attempt", []) or [])
        last_buy_result = dict(getattr(self.item_manager, "last_buy_result", {}) or {})
        buy_events = list(getattr(self.item_manager, "buy_attempt_events", []) or [])
        last_buy_event = dict((buy_events or [{}])[-1] or {})
        refresh_retry_error = dict(last_buy_event.get("refresh_retry_error") or {})
        buy_request_payload = dict(last_buy_result.get("request_payload") or last_buy_event.get("request_payload") or {})
        buy_payload_shop_rows = list(last_buy_result.get("payload_shop_rows") or last_buy_event.get("payload_shop_rows") or [])
        buy_payload_inventory_rows = list(last_buy_result.get("payload_inventory_rows") or last_buy_event.get("payload_inventory_rows") or [])
        buy_payload_item_details = list(last_buy_result.get("payload_item_details") or last_buy_event.get("payload_item_details") or [])
        source_state_turn = self._safe_int(
            last_buy_result.get("source_state_turn")
            if last_buy_result.get("source_state_turn") is not None
            else last_buy_event.get("source_state_turn")
        )
        request_current_turn = self._safe_int(
            last_buy_result.get("request_current_turn")
            if last_buy_result.get("request_current_turn") is not None
            else last_buy_event.get("request_current_turn")
        ) or current_turn
        turn_drift = bool(
            last_buy_result.get("turn_drift")
            if "turn_drift" in last_buy_result
            else last_buy_event.get("turn_drift")
        )
        if not turn_drift and source_state_turn and request_current_turn:
            turn_drift = source_state_turn != request_current_turn
        return {
            "current_turn": current_turn,
            "mant_coin": budget,
            "owned_map": owned_map,
            "active_bad_statuses": self.item_manager._active_bad_statuses(data),
            "mant_config": cfg,
            "source_state_turn": source_state_turn,
            "request_current_turn": request_current_turn,
            "turn_drift": turn_drift,
            "buy_attempt_diagnostics": buy_attempts,
            "use_attempt_diagnostics": use_attempts,
            "last_buy_options": last_buy_options,
            "last_buy_selected": last_buy_selected,
            "last_buy_attempt": last_buy_attempt,
            "last_buy_result": last_buy_result,
            "last_buy_event": last_buy_event,
            "failing_endpoint": last_buy_result.get("endpoint") or last_buy_event.get("endpoint") or "",
            "failing_endpoint_payload": buy_request_payload,
            "failing_payload_shop_rows": buy_payload_shop_rows,
            "failing_payload_inventory_rows": buy_payload_inventory_rows,
            "failing_payload_item_details": buy_payload_item_details,
            "failing_response_body_verbatim": (
                last_buy_result.get("response_body_verbatim")
                or (last_buy_result.get("error_details") or {}).get("response_body")
                or (last_buy_result.get("error_details") or {}).get("response_text")
            ),
            "refresh_retry_error": refresh_retry_error,
            "refresh_retry_payload": dict(refresh_retry_error.get("request_payload") or {}),
            "refresh_retry_payload_shop_rows": list(refresh_retry_error.get("payload_shop_rows") or []),
            "refresh_retry_payload_inventory_rows": list(refresh_retry_error.get("payload_inventory_rows") or []),
            "refresh_retry_payload_item_details": list(refresh_retry_error.get("payload_item_details") or []),
            "refresh_retry_response_body_verbatim": (
                refresh_retry_error.get("response_body_verbatim")
                or (refresh_retry_error.get("error_details") or {}).get("response_body")
                or (refresh_retry_error.get("error_details") or {}).get("response_text")
            ),
            "selected_buy_rows_without_attempt": [
                row for row in last_buy_selected
                if int(row.get("shop_item_id") or 0) not in {int(item.get("shop_item_id") or 0) for item in last_buy_attempt}
            ],
            "selected_use_rows_without_attempt": [
                row for row in list(getattr(self.item_manager, "last_use_selected", []) or [])
                if int(row.get("item_id") or 0) not in {int(item.get("item_id") or 0) for item in (getattr(self.item_manager, "last_use_attempt", []) or [])}
            ],
        }

    def _api_trace_dir(self):
        return runtime_output_root(self.base_dir) / "trace_logs" / "api_payloads"

    def _api_trace_row(self, path, lineno, row):
        return {
            "file": str(path),
            "line": int(lineno),
            "endpoint": row.get("endpoint") or "",
            "direction": row.get("direction") or "",
            "req_id": row.get("req_id") or "",
            "ts": row.get("ts"),
            "data": row.get("data"),
        }

    def _matching_api_trace_rows(self, *, req_ids=None, endpoint="", current_turn=0, program_id=0, limit=12, max_files=6):
        trace_dir = self._api_trace_dir()
        if not trace_dir.exists():
            return []
        req_ids = {str(req_id) for req_id in (req_ids or []) if str(req_id or "").strip()}
        endpoint = str(endpoint or "").strip()
        current_turn = self._safe_int(current_turn)
        program_id = self._safe_int(program_id)
        matches = []
        seen = set()
        try:
            files = sorted(trace_dir.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)[:max_files]
        except Exception:
            files = []
        for path in files:
            try:
                with path.open("r", encoding="utf-8", errors="ignore") as handle:
                    for lineno, raw_line in enumerate(handle, 1):
                        line = raw_line.strip()
                        if not line:
                            continue
                        if req_ids and not any(f'"req_id": "{req_id}"' in line for req_id in req_ids):
                            if not (endpoint and f'"endpoint": "{endpoint}"' in line):
                                continue
                        elif not req_ids and endpoint and f'"endpoint": "{endpoint}"' not in line:
                            continue
                        try:
                            row = json.loads(line)
                        except Exception:
                            continue
                        row_req_id = str(row.get("req_id") or "")
                        matched = False
                        if req_ids and row_req_id in req_ids:
                            matched = True
                        elif endpoint and str(row.get("endpoint") or "") == endpoint:
                            payload = ((row.get("data") or {}).get("payload") or {})
                            if current_turn and self._safe_int(payload.get("current_turn")) != current_turn:
                                continue
                            if program_id and self._safe_int(payload.get("program_id")) != program_id:
                                continue
                            matched = True
                        if not matched:
                            continue
                        key = (str(path), int(lineno))
                        if key in seen:
                            continue
                        seen.add(key)
                        matches.append(self._api_trace_row(path, lineno, row))
                        if len(matches) >= limit:
                            return matches
            except Exception:
                continue
        return matches

    def _api_error_details(self, exc):
        if exc is None:
            return {}
        request_payload = getattr(exc, "request_payload", None)
        response_body = getattr(exc, "response_body", None)
        response_text = getattr(exc, "response_text", None)
        details = {
            "type": exc.__class__.__name__,
            "message": str(exc),
            "endpoint": str(getattr(exc, "endpoint", "") or ""),
            "request_payload": dict(request_payload or {}) if isinstance(request_payload, dict) else request_payload,
            "response_body": response_body,
            "response_text": response_text,
            "http_status": getattr(exc, "http_status", None),
            "result_code": getattr(exc, "result_code", None),
            "response_code": getattr(exc, "response_code", None),
            "req_id": str(getattr(exc, "req_id", "") or ""),
            "traceback": traceback.format_exception(type(exc), exc, exc.__traceback__),
        }
        return details

    def _api_error_response_viewer_id(self, exc):
        response_body = getattr(exc, "response_body", None)
        headers = (response_body or {}).get("data_headers") or {}
        return self._safe_int(headers.get("viewer_id"))

    def _race_program_available(self, state, program_id):
        program_id = self._safe_int(program_id)
        if not program_id:
            return False
        data = (state or {}).get("data") or {}
        for row in data.get("race_condition_array") or []:
            if self._safe_int((row or {}).get("program_id")) == program_id:
                return True
        return False

    def _race_snapshot_context(self, state, preset, extra=None):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        home = data.get("home_info") or {}
        requested_turn = self._safe_int((extra or {}).get("current_turn"))
        requested_program_id = self._safe_int((extra or {}).get("program_id"))
        available_rows = list(data.get("race_condition_array") or [])
        available_programs = [
            self._safe_int(row.get("program_id"))
            for row in available_rows
            if self._safe_int((row or {}).get("program_id")) > 0
        ]
        entry = {}
        if self.race_planner and requested_program_id:
            entry = self.race_planner.entry_for_program(preset or {}, requested_turn, requested_program_id) or {}
        context = {
            "current_turn": self._safe_int(chara.get("turn")),
            "playing_state": self._safe_int(chara.get("playing_state")),
            "state": self._safe_int(chara.get("state")),
            "active_race_program_id": self._active_race_program_id(data),
            "race_entry_restriction": self._safe_int(home.get("race_entry_restriction")),
            "requested_turn": requested_turn,
            "requested_program_id": requested_program_id,
            "turn_drift": bool(requested_turn and self._safe_int(chara.get("turn")) and requested_turn != self._safe_int(chara.get("turn"))),
            "requested_program_available": requested_program_id in available_programs if requested_program_id else False,
            "requested_program_condition_rows": [
                row for row in available_rows
                if self._safe_int((row or {}).get("program_id")) == requested_program_id
            ],
            "available_race_program_ids": available_programs,
            "available_race_count": len(available_programs),
            "scheduled_entry": entry,
            "race_info": self._race_info_for_program(requested_program_id),
            "last_skip_reason": getattr(self.race_planner, "last_skip_reason", None),
        }
        if isinstance(extra, dict):
            context.update(extra)
        return context

    def _snapshot_summary(self, category, skill_context, item_context, race_context):
        flags = []
        likely_causes = []
        code_set = set()
        for result in (
            getattr(self.skill_buyer, "last_result", {}) or {},
            getattr(self.item_manager, "last_buy_result", {}) or {},
            getattr(self.item_manager, "last_use_result", {}) or {},
            getattr(self.item_manager, "last_pre_race_use_result", {}) or {},
        ):
            code_set.update(self._extract_error_codes(result.get("error") or ""))
            for code in result.get("error_codes") or []:
                code_set.add(int(code))
        for details in (
            (race_context or {}).get("error_details") or {},
            (race_context or {}).get("retry_after_refresh_error_details") or {},
        ):
            code_set.update(self._extract_error_codes(details.get("message") or ""))
            for key in ("result_code", "response_code"):
                value = details.get(key)
                if str(value).lstrip("-").isdigit():
                    code_set.add(int(value))

        if category.startswith("skill"):
            if skill_context.get("preflight_rejections"):
                flags.append("selected_skills_dropped_before_api_call")
                likely_causes.append("preflight rejected one or more selected skills before gain_skills was sent")
            if 205 in code_set or 208 in code_set:
                flags.append("skill_api_sync_or_rejection_code")
                likely_causes.append("server returned 205/208 during gain_skills; compare selected vs attempted skill rows and owned groups")
            if any(row.get("owned_group") for row in skill_context.get("preflight_rejections") or []):
                flags.append("selected_skill_group_already_owned")
                likely_causes.append("a selected skill group appears already owned in the snapshot, suggesting stale skill_array or known-bought desync")
        if "item" in category:
            if item_context.get("selected_buy_rows_without_attempt"):
                flags.append("selected_shop_rows_dropped_before_exchange")
                likely_causes.append("one or more shop targets were selected but not attempted after preflight or refresh")
            if item_context.get("turn_drift"):
                flags.append("item_turn_drift_detected")
                likely_causes.append("the request current_turn differed from chara_info.turn when the item payload was prepared")
            if any(not row.get("current_num_matches_inventory_count") for row in item_context.get("buy_attempt_diagnostics") or []):
                flags.append("shop_current_num_mismatch_with_inventory")
                likely_causes.append("exchange payload current_num does not match owned inventory for at least one attempted item")
            if 205 in code_set or 208 in code_set:
                flags.append("item_api_sync_or_rejection_code")
                likely_causes.append("server returned 205/208 during item exchange/use; inspect buy_attempt_diagnostics and failed probe details")
        if category.startswith("race"):
            if race_context.get("turn_drift"):
                flags.append("race_turn_drift_detected")
                likely_causes.append("the requested race turn did not match the state turn captured in the snapshot")
            if race_context.get("requested_program_id") and not race_context.get("requested_program_available"):
                flags.append("requested_race_missing_from_server_race_conditions")
                likely_causes.append("the scheduled race program was not present in race_condition_array when the snapshot was captured")
            if race_context.get("response_viewer_id_mismatch"):
                flags.append("race_error_response_viewer_id_mismatch")
                likely_causes.append("the race_entry error response reported a different viewer_id than the active client, suggesting stale auth/session state")
            if race_context.get("recovery_attempted_after_refresh") and race_context.get("retry_after_refresh_error_details"):
                flags.append("race_reject_persisted_after_refresh_retry")
                likely_causes.append("race_entry still rejected after a clean load/relogin refresh and one post-refresh retry")
            if 205 in code_set or 208 in code_set:
                flags.append("race_api_sync_or_rejection_code")
                likely_causes.append("server returned 205/208 during race_entry; inspect request payload, available race conditions, viewer mismatch, and trace rows")

        return {
            "error_codes": sorted(code_set),
            "flags": flags,
            "likely_causes": likely_causes,
        }

    def _build_error_snapshot_payload(self, state, preset, category, extra=None):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        free = data.get("free_data_set") or {}
        stats = self._turn_stats(chara)
        snapshot_preset = dict(preset or {})
        stripped_large_fields = {"preset": {}}
        for key in ("extra_race_list", "race_list", "learn_skill_list"):
            value = snapshot_preset.get(key)
            if isinstance(value, list) and value:
                stripped_large_fields["preset"][key] = len(value)
                snapshot_preset.pop(key, None)
        training_snapshot = self._safe_error_snapshot_section(
            "training_snapshot",
            lambda: self._training_snapshot(state, preset or {}),
            {},
        )
        active_item_effects = self._safe_error_snapshot_section(
            "active_item_effects",
            lambda: self._active_item_effects(state),
            [],
        )
        owned_skills = self._safe_error_snapshot_section(
            "owned_skills",
            lambda: self._debug_owned_skills(state),
            [],
        )
        inventory = self._safe_error_snapshot_section(
            "inventory",
            lambda: self._debug_inventory(state),
            [],
        )
        skill_rows_enriched = self._safe_error_snapshot_section(
            "skill_rows_enriched",
            lambda: self._debug_skill_options(state, preset or {}),
            [],
        )
        shop_rows_enriched = self._safe_error_snapshot_section(
            "shop_rows_enriched",
            lambda: self._debug_item_buy_options(state, preset or {}),
            [],
        )
        runner_status = self.snapshot()
        skill_context = self._skill_snapshot_context(state, preset, skill_rows_enriched)
        item_context = self._item_snapshot_context(state, preset, shop_rows_enriched)
        race_context = self._race_snapshot_context(state, preset, extra if isinstance(extra, dict) else {})
        summary = self._snapshot_summary(str(category or "general"), skill_context, item_context, race_context)
        return {
            "schema": "sweepy_error_snapshot_v2",
            "captured_at": datetime.now().isoformat(timespec="seconds"),
            "category": str(category or "general"),
            "turn": self._safe_int(chara.get("turn")),
            "preset_name": str((preset or {}).get("name") or ""),
            "preset": snapshot_preset,
            "_stripped_large_fields": stripped_large_fields if stripped_large_fields.get("preset") else {},
            "runner_status": runner_status,
            "summary": summary,
            "context": dict(extra or {}),
            "environment": {
                "pid": os.getpid(),
                "cwd": os.getcwd(),
                "python_version": sys.version,
                "os_name": os.name,
                "project_root": str(self.base_dir),
                "runtime_root": str(runtime_output_root(self.base_dir)),
            },
            "writer_call_stack": traceback.format_stack(limit=40),
            "report_turn_excerpt": self._recent_report_turn(self._safe_int(chara.get("turn"))),
            "state_data": data,
            "bot_vision": {
                "stats": stats,
                "detail": self._format_turn_stats(stats),
                "race_running_style": self._safe_int(chara.get("race_running_style")),
                "playing_state": self._safe_int(chara.get("playing_state")),
                "state": self._safe_int(chara.get("state")),
                "current_command_info_array": ((data.get("home_info") or {}).get("command_info_array") or []),
                "unchecked_event_array": data.get("unchecked_event_array") or [],
                "race_start_info": data.get("race_start_info") or {},
                "active_item_effects": active_item_effects,
                "training_snapshot": training_snapshot,
                "owned_skills": owned_skills,
                "inventory": inventory,
                "skill_rows_enriched": skill_rows_enriched,
                "shop_rows_enriched": shop_rows_enriched,
                "server_skill_tips_raw": chara.get("skill_tips_array") or [],
                "server_owned_skill_raw": chara.get("skill_array") or [],
                "server_shop_rows_raw": free.get("pick_up_item_info_array") or [],
                "server_inventory_raw": free.get("user_item_info_array") or [],
                "server_item_effect_array_raw": free.get("item_effect_array") or [],
                "server_support_card_array_raw": chara.get("support_card_array") or [],
                "server_evaluation_info_array_raw": chara.get("evaluation_info_array") or [],
                "bot_skill_candidates": list(getattr(self.skill_buyer, "last_candidates", []) or []),
                "bot_skill_selected": list(getattr(self.skill_buyer, "last_selected", []) or []),
                "bot_skill_attempt": list(getattr(self.skill_buyer, "last_attempt", []) or []),
                "bot_skill_result": dict(getattr(self.skill_buyer, "last_result", {}) or {}),
                "bot_skill_attempt_events": list(getattr(self.skill_buyer, "attempt_events", []) or []),
                "skill_buyer_state": self._skill_buyer_debug_state(),
                "bot_shop_candidates": list(getattr(self.item_manager, "last_buy_options", []) or []),
                "bot_shop_selected": list(getattr(self.item_manager, "last_buy_selected", []) or []),
                "bot_shop_attempt": list(getattr(self.item_manager, "last_buy_attempt", []) or []),
                "bot_shop_result": dict(getattr(self.item_manager, "last_buy_result", {}) or {}),
                "bot_shop_attempt_events": list(getattr(self.item_manager, "buy_attempt_events", []) or []),
                "bot_item_use_rows": list(getattr(self.item_manager, "last_use_options", []) or []),
                "bot_item_use_selected": list(getattr(self.item_manager, "last_use_selected", []) or []),
                "bot_item_use_attempt": list(getattr(self.item_manager, "last_use_attempt", []) or []),
                "bot_item_use_result": dict(getattr(self.item_manager, "last_use_result", {}) or {}),
                "bot_item_use_attempt_events": list(getattr(self.item_manager, "use_attempt_events", []) or []),
                "bot_pre_race_item_use_selected": list(getattr(self.item_manager, "last_pre_race_use_selected", []) or []),
                "bot_pre_race_item_use_attempt": list(getattr(self.item_manager, "last_pre_race_use_attempt", []) or []),
                "bot_pre_race_item_use_result": dict(getattr(self.item_manager, "last_pre_race_use_result", {}) or {}),
                "item_manager_state": self._item_manager_debug_state(),
            },
            "diagnostics": {
                "runner_log_tail": list((runner_status.get("log") or [])[-40:]),
                "runner_action_history_tail": list((runner_status.get("action_history") or [])[-40:]),
                "skill_context": skill_context,
                "item_context": item_context,
                "race_context": race_context,
            },
        }

    def _write_error_snapshot(self, state, preset, category, extra=None):
        snapshot = self._build_error_snapshot_payload(state, preset, category, extra=extra)
        directory = self._error_snapshot_dir(category)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        turn = self._safe_int(snapshot.get("turn"))
        preset_slug = self._error_snapshot_slug(snapshot.get("preset_name"))
        path = directory / f"{stamp}_turn_{turn:02d}_{preset_slug}.json"
        latest = directory / f"latest_{self._error_snapshot_slug(category)}.json"
        serialized = json.dumps(snapshot, ensure_ascii=False, indent=2, default=self._error_snapshot_default)
        tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
        try:
            tmp.write_text(serialized, encoding="utf-8")
            os.replace(tmp, path)
        except Exception:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
            path.write_text(serialized, encoding="utf-8")
        latest.write_text(serialized, encoding="utf-8")
        try:
            from career_bot.storage_cleanup import cap_error_snapshots
            cap_error_snapshots(self.base_dir)
        except Exception:
            pass
        print(f"{category} diagnostic snapshot written: {path}", flush=True)
        return path

    def _skill_error_snapshot_needed(self):
        result = dict(getattr(self.skill_buyer, "last_result", {}) or {})
        if getattr(self.skill_buyer, "recover_after_error", False):
            return True
        if result.get("error"):
            return True
        if result.get("result") in {"failed", "ok_partial"}:
            return True
        skip = str(result.get("skip") or "")
        return skip in {"preflight_failed", "all_failed_this_turn", "stale_turn_detected"} and bool(
            getattr(self.skill_buyer, "last_candidates", [])
            or getattr(self.skill_buyer, "last_selected", [])
            or getattr(self.skill_buyer, "last_attempt", [])
            or getattr(self.skill_buyer, "attempt_events", [])
        )

    def _item_error_snapshot_needed(self, result=None, recover_flag=False):
        result = dict(result or {})
        if recover_flag or result.get("error"):
            return True
        if result.get("result") in {"failed", "ok_after_refresh", "per_item_fallback"}:
            return True
        skip = str(result.get("skip") or "")
        return skip in {"stale_turn_detected", "preflight_failed", "all_items_missing_after_refresh"} and bool(
            getattr(self.item_manager, "last_buy_selected", [])
            or getattr(self.item_manager, "last_buy_attempt", [])
            or getattr(self.item_manager, "last_use_selected", [])
            or getattr(self.item_manager, "last_use_attempt", [])
        )

    def _maybe_write_skill_error_snapshot(self, state, preset, category, extra=None):
        if not self._skill_error_snapshot_needed():
            return None
        return self._write_error_snapshot(state, preset, category, extra=extra)

    def _maybe_write_item_error_snapshot(self, state, preset, category, result=None, recover_flag=False, extra=None):
        if not self._item_error_snapshot_needed(result=result, recover_flag=recover_flag):
            return None
        return self._write_error_snapshot(state, preset, category, extra=extra)

    def _api_result(self, result):
        result = dict(result or {})
        error = str(result.get("error") or "")
        code = None
        for token in error.replace(":", " ").replace(",", " ").split():
            if token.isdigit():
                value = int(token)
                if value in {201, 202, 205, 208, 394, 709}:
                    code = value
                    break
        if result.get("result") in {"ok", "ok_partial"}:
            code = 1
        return {
            "ok": result.get("result") in {"ok", "ok_partial"},
            "result_code": code,
            "error": error or None,
        }

    def _sum_cost(self, rows):
        return sum(int((row or {}).get("cost") or 0) for row in rows or [])

    def _shop_attempt_cost(self, attempt, selected):
        costs = {int(row.get("shop_item_id") or 0): int(row.get("cost") or 0) for row in selected or []}
        return sum(costs.get(int(row.get("shop_item_id") or 0), 0) for row in attempt or [])

    def _fresh_career_state(self, client, strategy=None, force_relogin=False):
        errors = []
        # Forced relogin is usually correct for 394/501/709, but live logs show
        # relogin can fail while the existing single_mode_free/load session is
        # still salvageable. Try both before declaring the runner dead.
        relogin_attempts = (True, False) if force_relogin else (False, True)
        for relogin in relogin_attempts:
            try:
                if relogin:
                    if not hasattr(client, "login"):
                        break
                    client.login()
                if hasattr(client, "load_career"):
                    state = client.load_career()
                else:
                    state = client.call("single_mode_free/load", {})
                if strategy and (state.get("data") or {}).get("unchecked_event_array"):
                    state = self._drain_events(client, strategy, state)
                if hasattr(self.skill_buyer, "enrich_state_with_known_bought"):
                    state = self.skill_buyer.enrich_state_with_known_bought(state)
                self.skill_buyer.reset_scoped_failures()
                self.item_manager.reset_scoped_failures()
                return state
            except Exception as exc:
                errors.append(str(exc))
        raise RuntimeError("career recovery failed: " + " | ".join(errors))

    def _api_error_code(self, exc):
        http_status = self._safe_int(getattr(exc, "http_status", 0))
        if http_status:
            return http_status
        for attr in ("result_code", "response_code"):
            code = self._safe_int(getattr(exc, attr, 0))
            if code:
                return code
        body = getattr(exc, "response_body", None)
        if isinstance(body, dict):
            for source in (body.get("data_headers"), body):
                if not isinstance(source, dict):
                    continue
                code = self._safe_int(source.get("result_code") or source.get("response_code"))
                if code:
                    return code
        text = str(exc)
        for code in (391, 394, 501, 709, 208, 205, 202, 102, 408, 425, 500, 502, 503, 504):
            if f"API error {code}" in text or f"HTTP {code}" in text or f"{code} on" in text:
                return code
        return 0

    def _recoverable_command_error(self, exc):
        code = self._api_error_code(exc)
        if code in {391, 394, 501, 709, 208, 205, 202, 408, 425, 500, 502, 503, 504}:
            endpoint = str(getattr(exc, "endpoint", "") or "")
            return not endpoint or endpoint == "single_mode_free/exec_command" or "exec_command" in str(exc)
        return False

    def _recoverable_event_error(self, exc):
        code = self._api_error_code(exc)
        if code in {391, 394, 501, 709, 208, 205, 202, 408, 425, 500, 502, 503, 504}:
            endpoint = str(getattr(exc, "endpoint", "") or "")
            return not endpoint or endpoint == "single_mode_free/check_event" or "check_event" in str(exc)
        return False

    def _exec_command_with_recovery(self, client, strategy, state, payload, chara):
        try:
            return client.exec_command(**payload), True
        except Exception as exc:
            turn = self._safe_int((chara or {}).get("turn") or payload.get("current_turn"))
            print(f"Command Error at turn {turn}: {exc}")
            code = self._api_error_code(exc)
            if code == 102:
                command_type = self._safe_int((payload or {}).get("command_type"))
                if command_type == 3:
                    self._log("command_recover", turn, "outing/recreation API 102; refreshing career state")
                    fresh = self._fresh_career_state(client, strategy, force_relogin=False)
                    fresh_data = fresh.get("data") or {}
                    if fresh_data.get("unchecked_event_array"):
                        fresh = self._drain_events(client, strategy, fresh)
                    return fresh, False
                return self._recover_blocked_state(client, strategy, state), False
            if code == 205 and self._safe_int((payload or {}).get("command_type")) == 3:
                self._log("command_recover", turn, "recreation API 205; refreshing career state and falling back")
                fresh = self._fresh_career_state(client, strategy, force_relogin=False)
                fresh_data = fresh.get("data") or {}
                if fresh_data.get("unchecked_event_array"):
                    fresh = self._drain_events(client, strategy, fresh)
                return fresh, False
            if not self._recoverable_command_error(exc):
                raise

            self._log("command_recover", turn, f"exec_command API {code}; refreshing career state")
            force_relogin = code in {394, 501, 709, 202}
            fresh = self._fresh_career_state(client, strategy, force_relogin=force_relogin)
            fresh_data = fresh.get("data") or {}
            fresh_chara = fresh_data.get("chara_info") or {}
            fresh_turn = self._safe_int(fresh_chara.get("turn"))

            if fresh_data.get("unchecked_event_array"):
                fresh = self._drain_events(client, strategy, fresh)
                fresh_data = fresh.get("data") or {}
                fresh_chara = fresh_data.get("chara_info") or {}
                fresh_turn = self._safe_int(fresh_chara.get("turn"))

            if (
                fresh_turn
                and fresh_turn != self._safe_int(payload.get("current_turn"))
            ) or self._is_complete_career_prompt(fresh) or self._blocked_playing_state(fresh_chara):
                self._log("command_recover", fresh_turn or turn, "state changed during command recovery; continuing from refreshed state")
                return fresh, False

            retry_payload = dict(payload or {})
            retry_payload["current_turn"] = fresh_turn or self._safe_int(payload.get("current_turn"))
            fresh_vital = fresh_chara.get("vital")
            retry_payload["current_vital"] = (
                self._safe_int(fresh_vital)
                if fresh_vital is not None
                else self._safe_int(payload.get("current_vital"))
            )
            self._log(
                "command_retry",
                retry_payload.get("current_turn", turn),
                f"{retry_payload.get('command_type')}:{retry_payload.get('command_id')} after API {code}",
            )
            try:
                return client.exec_command(**retry_payload), True
            except Exception as retry_exc:
                retry_code = self._api_error_code(retry_exc)
                if not self._recoverable_command_error(retry_exc):
                    raise
                print(f"Command retry failed at turn {retry_payload.get('current_turn', turn)}: {retry_exc}")
                self._log("command_recover", retry_payload.get("current_turn", turn), f"retry API {retry_code}; continuing from refreshed state")
                return self._fresh_career_state(
                    client,
                    strategy,
                    force_relogin=retry_code in {394, 501, 709, 202},
                ), False

    def _active_race_program_id(self, data):
        data = data or {}
        chara = data.get("chara_info") or {}
        race_start_info = data.get("race_start_info") or {}
        return self._safe_int(race_start_info.get("program_id") or chara.get("race_program_id"))

    def _has_actionable_home_commands(self, data):
        commands = ((data or {}).get("home_info") or {}).get("command_info_array") or []
        for command in commands:
            enabled_value = command.get("is_enable")
            enabled = True if enabled_value is None else bool(self._safe_int(enabled_value))
            if enabled:
                return True
        return False

    def _is_complete_career_prompt(self, state):
        data = (state or {}).get("data") or {}
        if "single_mode_finish_common" in data:
            return True
        chara = data.get("chara_info") or {}
        playing_state = self._safe_int(chara.get("playing_state"))
        chara_state = self._safe_int(chara.get("state"))
        if playing_state != 5:
            return False
        if chara_state == 3:
            return True
        if self._active_race_program_id(data) or data.get("race_start_info"):
            return False
        if chara_state == 2 and self._has_actionable_home_commands(data):
            return True
        return False

    def _is_post_action_without_active_race(self, state):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        return (
            not self._is_complete_career_prompt(state)
            and
            self._safe_int(chara.get("playing_state")) == 5
            and not self._active_race_program_id(data)
            and not data.get("race_start_info")
            and not self._has_actionable_home_commands(data)
        )

    def _is_career_finish_state(self, state):
        return self._is_complete_career_prompt(state)

    def _same_active_race_state(self, state, current_turn, program_id, playing_states=None):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        state_turn = self._safe_int(chara.get("turn"))
        state_program_id = self._active_race_program_id(data)
        playing_state = self._safe_int(chara.get("playing_state"))
        if playing_states is not None and playing_state not in set(playing_states):
            return False
        if current_turn and state_turn and state_turn != self._safe_int(current_turn):
            return False
        return bool(program_id and state_program_id == self._safe_int(program_id))

    def _has_stale_race_metadata(self, state):
        if self._is_career_finish_state(state):
            return False
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        playing_state = self._safe_int(chara.get("playing_state"))
        if playing_state not in {2, 3, 4, 5}:
            return False
        if not self._active_race_program_id(data):
            return False
        return self._safe_int(chara.get("state")) != 0

    def _stop_for_state_block(self, turn, detail):
        self._log("state_blocked", turn, detail)
        self._mark(last_action=detail)
        self.stop()

    def _settle_state(self, client, strategy, state, payload=None):
        payload = payload or {}
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        current_turn = payload.get("current_turn") or chara.get("turn", 0)
        if data.get("unchecked_event_array"):
            return self._drain_events(client, strategy, state)
        try:
            fresh = self._fresh_career_state(client, strategy)
        except Exception as exc:
            self._stop_for_state_block(current_turn, f"state refresh failed: {exc}")
            return state
        if not self._is_post_action_without_active_race(fresh):
            if self._has_stale_race_metadata(fresh):
                chara = (fresh.get("data") or {}).get("chara_info") or {}
                detail = f"stale race metadata state {chara.get('playing_state')}/{chara.get('state')}; not safe to call race_end"
                self._stop_for_state_block(current_turn, detail)
            return fresh
        detail = "post-action state without active race; not safe to start another command/race"
        # In loop mode the stuck career persists server-side across runner
        # restarts — each new loop iteration sees the same broken state and
        # exits the same way, accumulating consecutive failures until the
        # loop quits. Force-delete the career server-side so the next
        # iteration starts clean. Observed after 18 successful careers when
        # a T24 event left playing_state=5 with no home commands.
        if self._loop_mode_active():
            self._force_release_stuck_career(client, current_turn, detail)
        self._stop_for_state_block(current_turn, detail)
        return fresh

    def _force_release_stuck_career(self, client, current_turn, detail):
        """Server-side abandon a wedged career so the next loop run is clean."""
        try:
            client.finish_career(current_turn=int(current_turn or 0), is_force_delete=True)
            self._log("stuck_career_force_released", current_turn, detail)
        except Exception as exc:
            self._log("stuck_career_force_release_failed", current_turn, f"{detail} | {exc}")

    def _event(self, client, strategy, payload):
        data = dict(payload)
        event = data.pop("_event", None)
        current_turn = data.pop("_current_turn", data.get("current_turn", 0))
        state_before = data.pop("_state_before", None)
        if event:
            choice = data.get("choice_number")
            if choice is None:
                choice = strategy.choose_from_event(event, current_turn)
            self._log("event_choice", current_turn, f"{data.get('event_id')} -> {choice}")
            self._record_event_choice(event, choice, current_turn, state_before=state_before)
            try:
                response = client.check_event(
                    event_id=data["event_id"],
                    chara_id=event.get("chara_id", 0),
                    choice_number=choice,
                    current_turn=current_turn
                )
            except Exception as exc:
                self._record_event_resolution(event, choice, current_turn, error=exc, state_before=state_before)
                raise
            self._record_event_resolution(event, choice, current_turn, response=response, state_before=state_before)
            return response
        if "event_id" not in data:
            self._log("recover", current_turn, "event requested without event_id, forcing state refresh")
            return self._fresh_career_state(client, strategy)
        return client.check_event(**data)

    def _drain_events(self, client, strategy, state, limit=20):
        current = state
        recoveries = 0
        for _ in range(limit):
            data = current.get("data") or {}
            events = data.get("unchecked_event_array") or []
            if not events:
                return current
            event = events[0] or {}
            choice = strategy._choice(event)
            state_before = self._event_state_snapshot(current)
            payload = {
                "event_id": event.get("event_id"),
                "chara_id": event.get("chara_id", 0),
                "choice_number": choice,
                "current_turn": (data.get("chara_info") or {}).get("turn", 1),
                "_event": event,
                "_current_turn": (data.get("chara_info") or {}).get("turn", 1),
                "_state_before": state_before,
            }
            if choice is None:
                payload = {
                    "event_id": event.get("event_id"),
                    "_event": event,
                    "_current_turn": (data.get("chara_info") or {}).get("turn", 1),
                    "_state_before": state_before,
                }
            try:
                current = self._event(client, strategy, payload)
            except Exception as exc:
                if not self._recoverable_event_error(exc):
                    raise
                recoveries += 1
                code = self._api_error_code(exc)
                turn = self._safe_int(payload.get("current_turn") or payload.get("_current_turn"))
                self._log("event_recover", turn, f"check_event API {code}; refreshing career state")
                fresh = self._fresh_career_state(
                    client,
                    None,
                    force_relogin=code in {394, 501, 709, 202},
                )
                current = fresh
                fresh_events = ((fresh.get("data") or {}).get("unchecked_event_array") or [])
                if not fresh_events:
                    return fresh
                if recoveries >= 3:
                    self._log("event_recover", turn, f"persistent check_event API {code}; continuing from refreshed state")
                    return fresh
        return current

    def _finish_career(self, client, state, preset, strategy, current_turn):
        current_turn = int(current_turn or ((state.get("data") or {}).get("chara_info") or {}).get("turn") or 78)
        if current_turn < 70 and not self._is_career_finish_state(state):
            detail = f"blocked suspicious early finish request at turn {current_turn} without confirmed finish screen"
            self._log("finish_blocked", current_turn, detail)
            self._mark(last_action=detail)
            self.stop()
            return state

        # Spend ALL points at the end screen before completing the career.
        print("!!! Career Finish Action: Attempting final skill purchase...")
        state = self._buy_skills(client, state, preset, True)
        if self.skill_buyer.attempt_events and not self.skill_buyer.recover_after_error:
            # gain_skills can return a stale chara snapshot at the finish screen. Reload
            # once so the "SP still high" retry does not re-submit already bought groups.
            try:
                state = self._fresh_career_state(client, strategy)
                self._debug_turn(state, preset)
            except Exception as e:
                print(f"Final skill post-buy reload failure: {e}")

        data = state.get("data") or {}
        if data.get("race_start_info") and not self._is_career_finish_state(state):
            self._log("race_out", current_turn, "clearing active race")
            try:
                state = client.race_out(current_turn=current_turn)
            except Exception as e:
                if any(err in str(e) for err in ("102", "201", "StateRecoveryError")):
                    self._log("race_out_reconciled", current_turn, f"graceful exit: {e}")
                else:
                    raise
        state = self._drain_events(client, strategy, state, limit=50)

        # Drain remaining SP until we hit the configured floor or a retry pass
        # makes no progress. End-career buying can use fallback skills, so a
        # static 200-SP cutoff leaves cheap white skills unbought.
        prev_sp = None
        try:
            drain_floor = max(0, int((preset or {}).get("skill_point_drain_floor", 60)))
        except (TypeError, ValueError):
            drain_floor = 60
        try:
            max_skill_passes = max(1, int((preset or {}).get("final_skill_drain_max_passes", 5)))
        except (TypeError, ValueError):
            max_skill_passes = 5
        last_retryable_skill_failure = False
        for pass_idx in range(max_skill_passes):
            chara = (state.get("data") or {}).get("chara_info") or {}
            sp_now = int(chara.get("skill_point") or 0)
            if sp_now <= drain_floor:
                break
            if prev_sp is not None and sp_now >= prev_sp:
                if last_retryable_skill_failure:
                    print(f"SP unchanged at {sp_now}; retrying with rejected skills excluded (pass {pass_idx + 1}/{max_skill_passes})...")
                else:
                    # No SP drop on the previous pass and there was no rejected
                    # batch to prune. The buyer cannot find anything else valid.
                    print(f"SP retry stuck at {sp_now} (no drop from {prev_sp}); giving up")
                    break
            prev_sp = sp_now
            print(f"SP still high ({sp_now}), retrying final purchase (pass {pass_idx + 1}/{max_skill_passes}, floor {drain_floor})...")
            state = self._buy_skills(client, state, preset, True)
            last_result = getattr(self.skill_buyer, "last_result", {}) or {}
            last_retryable_skill_failure = bool(
                last_result.get("result") == "failed"
                or last_result.get("skip") in {"preflight_failed", "all_failed_this_turn"}
                or getattr(self.skill_buyer, "recover_after_error", False)
            )
            if not self.skill_buyer.attempt_events:
                print(f"Final skill drain no buyable candidates at SP {sp_now}: {self.skill_buyer.last_result}")
                break
            if self.skill_buyer.attempt_events and not self.skill_buyer.recover_after_error:
                try:
                    state = self._fresh_career_state(client, strategy)
                    self._debug_turn(state, preset)
                except Exception as e:
                    print(f"Final skill retry reload failure: {e}")
            chara = (state.get("data") or {}).get("chara_info") or chara

        chara = (state.get("data") or {}).get("chara_info") or chara
        final_sp = self._safe_int(chara.get("skill_point"))
        if final_sp <= drain_floor:
            print(f"Final skill drain complete: SP {final_sp} <= floor {drain_floor}")
        else:
            print(f"Final skill drain stopped: SP {final_sp} > floor {drain_floor}")

        final_fans = self._safe_int(chara.get("fans"))
        try:
            state = client.finish_career(current_turn=current_turn, is_force_delete=False)
        except Exception as e:
            if any(err in str(e) for err in ("102", "201", "StateRecoveryError")):
                self._log("finish_reconciled", current_turn, f"graceful exit: {e}")
            else:
                raise
        if not self._loop_mode_active(preset):
            try:
                if hasattr(client, "call"):
                    client.call("load/index", {"adid": ""})
                if hasattr(client, "read_info"):
                    client.read_info()
            except Exception as exc:
                self._log("post_finish_refresh", current_turn, f"home refresh failed: {exc}")
        self._mark(last_action="finish", finished=True, final_fans=final_fans)
        return state

    def _race(self, client, state, preset, payload):
        program_id = payload.get("program_id")
        current_turn = payload.get("current_turn") or 1
        strategy = payload.get("_strategy")
        state = self._maybe_buy_kikuka_front_runner_recovery(client, state, preset, program_id, current_turn, strategy)
        state = self._maybe_buy_calendar_race_skills(client, state, preset, program_id, current_turn, strategy)
        if int((preset or {}).get("scenario_id") or (preset or {}).get("scenario") or 4) == 4:
            self.item_manager.recover_after_use_error = False
            snapshot_state = state
            state, used = self.item_manager.handle_pre_race(client, state, preset, payload, self.status, self.race_planner)
            for event in self.item_manager.use_attempt_events:
                self._debug("items_use_attempt", state, {
                    "selected": event.get("selected") or [],
                    "attempt": event.get("attempt") or [],
                    "payload": event.get("payload") or [],
                    "result": self._api_result(event.get("result") or {}),
                })
            self._maybe_write_item_error_snapshot(snapshot_state, preset, "pre_race_item_buy", result=self.item_manager.last_buy_result, recover_flag=self.item_manager.recover_after_exchange_error, extra={
                "phase": "pre_race",
                "program_id": int(program_id or 0),
                "current_turn": int(current_turn or 0),
            })
            self._maybe_write_item_error_snapshot(snapshot_state, preset, "pre_race_item_use", result=self.item_manager.last_pre_race_use_result, recover_flag=self.item_manager.recover_after_use_error, extra={
                "phase": "pre_race",
                "program_id": int(program_id or 0),
                "current_turn": int(current_turn or 0),
                "used": int(used or 0),
            })
            if self.item_manager.recover_after_use_error or self.item_manager.use_attempt_events:
                state = self._fresh_career_state(client, payload.get("_strategy"))
                self._debug_turn(state, preset)
                if self.item_manager.recover_after_use_error:
                    return state
            if used > 0:
                with self.lock:
                    self.status["items_used"] += used
                    self._log_locked("items_use", payload.get("current_turn") or 1, f"pre-race {used}")
                # Trust the state from reload or successful action
                try:
                    fresh_state = client.load_career() if hasattr(client, "load_career") else client.call("single_mode_free/load", {})
                    state = fresh_state
                except Exception:
                    pass

        if self._is_g1_program(program_id):
            self._debug("g1_pre_race", state, self._race_snapshot(
                state,
                preset,
                program_id,
                current_turn,
                "pre_race",
                item_context={
                    "selected": list(self.item_manager.last_pre_race_use_selected),
                    "attempt": list(self.item_manager.last_pre_race_use_attempt),
                    "result": self._api_result(dict(self.item_manager.last_pre_race_use_result or {})),
                },
            ))
        try:
            entry = client.race_entry(program_id=program_id, current_turn=current_turn)
        except Exception as exc:
            print(f"Race Entry Error at turn {current_turn}: {exc}")
            exc_str = str(exc)
            if "205" not in exc_str and "208" not in exc_str:
                raise
            race_error_details = self._api_error_details(exc)
            response_viewer_id = self._api_error_response_viewer_id(exc)
            client_viewer_id = self._safe_int(getattr(client, "viewer_id", 0))
            response_viewer_id_mismatch = bool(
                response_viewer_id
                and client_viewer_id
                and response_viewer_id != client_viewer_id
            )
            relogin_refresh_attempted = False
            relogin_refresh_error = {}
            fresh = self._fresh_career_state(client, strategy)
            if response_viewer_id_mismatch and hasattr(client, "login"):
                try:
                    relogin_refresh_attempted = True
                    fresh = self._fresh_career_state(client, strategy, force_relogin=True)
                except Exception as relogin_exc:
                    relogin_refresh_error = self._api_error_details(relogin_exc)
            recovery_attempted_after_refresh = False
            retry_after_refresh_error_details = {}
            if self._same_active_race_state(fresh, current_turn, program_id, playing_states={2, 3, 4, 5}):
                self._log("race_entry_reconciled", current_turn, f"load showed active race {program_id} after 205/208")
                entry = fresh
            elif self._race_program_available(fresh, program_id) and self._safe_int(((fresh.get("data") or {}).get("chara_info") or {}).get("turn")) == self._safe_int(current_turn):
                try:
                    recovery_attempted_after_refresh = True
                    entry = client.race_entry(program_id=program_id, current_turn=current_turn)
                    self._log("race_entry_retry_after_refresh", current_turn, program_id)
                except Exception as retry_exc:
                    retry_after_refresh_error_details = self._api_error_details(retry_exc)
                    entry = None
            else:
                entry = None
            if entry is None:
                api_trace_rows = self._matching_api_trace_rows(
                    req_ids=[
                        race_error_details.get("req_id"),
                        retry_after_refresh_error_details.get("req_id"),
                    ],
                    endpoint="single_mode_free/race_entry",
                    current_turn=current_turn,
                    program_id=program_id,
                    limit=12,
                )
                self._write_error_snapshot(
                    fresh or state,
                    preset,
                    "race_entry",
                    extra={
                        "phase": "race_entry",
                        "program_id": self._safe_int(program_id),
                        "current_turn": self._safe_int(current_turn),
                        "request_payload": {
                            "program_id": self._safe_int(program_id),
                            "current_turn": self._safe_int(current_turn),
                        },
                        "error_details": race_error_details,
                        "retry_after_refresh_error_details": retry_after_refresh_error_details,
                        "recovery_attempted_after_refresh": recovery_attempted_after_refresh,
                        "relogin_refresh_attempted": relogin_refresh_attempted,
                        "relogin_refresh_error": relogin_refresh_error,
                        "response_viewer_id": response_viewer_id,
                        "client_viewer_id": client_viewer_id,
                        "response_viewer_id_mismatch": response_viewer_id_mismatch,
                        "api_trace_rows": api_trace_rows,
                        "fresh_turn": self._safe_int(((fresh.get("data") or {}).get("chara_info") or {}).get("turn")),
                        "fresh_playing_state": self._safe_int(((fresh.get("data") or {}).get("chara_info") or {}).get("playing_state")),
                        "fresh_state": self._safe_int(((fresh.get("data") or {}).get("chara_info") or {}).get("state")),
                        "fresh_active_race_program_id": self._active_race_program_id((fresh or {}).get("data") or {}),
                    },
                )
                if self.race_planner and not self.race_planner.fan_eligible(
                    fresh,
                    preset,
                    program_id,
                    self.race_planner.entry_for_program(preset, current_turn, program_id) or {},
                ):
                    reason = getattr(self.race_planner, "last_skip_reason", {}) or {}
                    detail = (
                        f"{reason.get('race_name') or program_id}: fans "
                        f"{reason.get('fans', 0)}/{reason.get('required_fans', 0)}"
                    )
                    self._log("race_reject_fans", current_turn, detail)
                else:
                    self._log("race_reject", current_turn, program_id)
                if self.race_planner:
                    self.race_planner.reject(current_turn, program_id)
                return fresh
        self._log("race_entry", current_turn, program_id)
        if strategy:
            entry_data = entry.get("data") or {}
            if entry_data.get("unchecked_event_array"):
                entry = self._drain_events(client, strategy, entry)
        if self._is_career_finish_state(entry):
            self._log("finish_detected", current_turn, "race entry returned career finish screen")
            return self._finish_career(client, entry, preset, strategy, current_turn)
        if not self._same_active_race_state(entry, current_turn, program_id, playing_states={2, 3, 4, 5}):
            entry_chara = (entry.get("data") or {}).get("chara_info") or {}
            detail = (
                f"event drain returned non-race state "
                f"turn={entry_chara.get('turn')} playing_state={entry_chara.get('playing_state')}; continuing"
            )
            self._log("race_entry_reconciled", current_turn, detail)
            return entry
        if self._has_stale_race_metadata(entry):
            entry_chara = (entry.get("data") or {}).get("chara_info") or {}
            detail = f"race_entry returned stale race metadata state {entry_chara.get('playing_state')}/{entry_chara.get('state')}; stopping before race_start"
            self._log("race_progress_blocked", current_turn, detail)
            self._mark(last_action=detail)
            self.stop()
            return entry
        self._maybe_change_running_style(client, entry, preset, program_id, current_turn)
        entry_chara = (entry.get("data") or {}).get("chara_info") or {}
        race_start_info = (entry.get("data") or {}).get("race_start_info") or {}
        is_short = 1 if (race_start_info.get("is_short") or entry_chara.get("is_short_race")) else 0
        try:
            client.race_start(is_short=is_short, current_turn=current_turn)
            self._log("race_start", current_turn, f"short {is_short}")
        except Exception as exc:
            if not any(code in str(exc) for code in ("102", "2502")):
                raise
            self._log("race_start_reconciled", current_turn, f"race_start rejected (server already advanced): {exc}")

        # Check state before race_end to avoid 102
        race_end_failed_102 = False
        end_result = None
        race_result = None
        try:
            fresh, pre_end_result = self._load_pre_race_end_state(client, current_turn, program_id, preset)
            state_val = (fresh.get("data", {}).get("chara_info", {})).get("playing_state")
            if state_val in {1}:
                self._log("race_end_skip", current_turn, f"already home (state={state_val})")
            else:
                pre_end_probe_attempted = False
                # If a resume/reconciliation state already contains a current
                # loss before race_end, retry there. This is the same window
                # the real client uses for alarm-clock Try Again.
                if pre_end_result and not pre_end_result.get("won"):
                    fresh, pre_end_result = self._try_continues_pre_race_end(
                        client, fresh, pre_end_result, current_turn, program_id, preset,
                        strategy=strategy, race_start_info=race_start_info,
                    )
                    race_result = pre_end_result
                    if self._race_result_from_response(fresh, current_turn, program_id):
                        end_result = fresh
                elif not pre_end_result and self._safe_int(state_val) == 3:
                    end_result, race_result, pre_end_probe_attempted = self._try_unknown_continue_pre_race_end(
                        client, fresh, current_turn, program_id, preset,
                        strategy=strategy, race_start_info=race_start_info,
                    )
                try:
                    if end_result is None:
                        end_result = client.race_end(current_turn=current_turn)
                        end_result, race_result = self._resolve_race_end_with_retries(
                            client,
                            end_result,
                            current_turn,
                            program_id,
                            preset,
                            strategy=strategy,
                            race_start_info=race_start_info,
                        )
                    if not race_result:
                        race_result = self._race_result_from_response(end_result, current_turn, program_id)
                    self._record_race_result(current_turn, program_id, race_result)
                    self._log("race_end", current_turn, self._race_result_label(race_result))
                except Exception as e:
                    err_str = str(e)
                    if "102" in err_str or "1503" in err_str:
                        code = "1503" if "1503" in err_str else "102"
                        self._log("race_end_reconciled", current_turn, f"server already done ({code})")
                        race_end_failed_102 = True
                    else:
                        raise
        except Exception as e:
            err_str = str(e)
            if "102" in err_str or "1503" in err_str:
                code = "1503" if "1503" in err_str else "102"
                self._log("race_end_reconciled", current_turn, f"server already done ({code})")
                race_end_failed_102 = True
            else:
                try:
                    end_result = client.race_end(current_turn=current_turn)
                    end_result, race_result = self._resolve_race_end_with_retries(
                        client,
                        end_result,
                        current_turn,
                        program_id,
                        preset,
                        strategy=strategy,
                        race_start_info=race_start_info,
                    )
                    if not race_result:
                        race_result = self._race_result_from_response(end_result, current_turn, program_id)
                    self._record_race_result(current_turn, program_id, race_result)
                    self._log("race_end", current_turn, self._race_result_label(race_result) or "fallback")
                except Exception as ee:
                    ee_str = str(ee)
                    if "102" in ee_str or "1503" in ee_str:
                        code = "1503" if "1503" in ee_str else "102"
                        self._log("race_end_reconciled", current_turn, f"server already done ({code})")
                        race_end_failed_102 = True
                    else:
                        raise
        if race_end_failed_102:
            fresh_state = self._fresh_career_state(client, strategy)
            if self._same_active_race_state(fresh_state, current_turn, program_id, playing_states={3}):
                detail = f"race_end returned 102/1503 and server still reports active race {program_id}; stopping to avoid retry loop"
                self._log("race_progress_blocked", current_turn, detail)
                self._mark(last_action=detail)
                self.stop()
                return fresh_state
            fresh_data = fresh_state.get("data") or {}
            if not (fresh_data.get("race_reward_info") or self._same_active_race_state(fresh_state, current_turn, program_id, playing_states={4, 5})):
                return fresh_state
            end_result, race_result = self._resolve_race_end_with_retries(
                client,
                fresh_state,
                current_turn,
                program_id,
                preset,
                strategy=strategy,
                race_start_info=race_start_info,
            )
            if not race_result:
                race_result = self._race_result_from_response(end_result, current_turn, program_id)
            self._record_race_result(current_turn, program_id, race_result)
            self._log("race_end", current_turn, self._race_result_label(race_result) or "reconciled")
        if not race_result and end_result and self._same_active_race_state(end_result, current_turn, program_id, playing_states={2, 3}):
            self._log("race_progress_deferred", current_turn, "race continue returned replay state; deferring race_end/race_out")
            return end_result
        
        try:
            out = client.race_out(current_turn=current_turn)
        except Exception as e:
            if any(err in str(e) for err in ("102", "201", "StateRecoveryError")):
                self._log("race_out_reconciled", current_turn, f"graceful exit: {e}")
                fresh_state = self._fresh_career_state(client, strategy)
                finished_state = self._finish_after_final_race_if_ready(
                    client, fresh_state, preset, strategy, current_turn, program_id, race_start_info,
                    reason="final race_out reconciled"
                )
                if finished_state is not None:
                    return finished_state
                if self._same_active_race_state(fresh_state, current_turn, program_id, playing_states={3, 4, 5}):
                    detail = f"race_out failed and server still reports active race {program_id}; stopping to avoid retry loop"
                    self._log("race_progress_blocked", current_turn, detail)
                    self._mark(last_action=detail)
                    self.stop()
                    return fresh_state
                race_result = self._race_result_from_response(fresh_state, current_turn, program_id)
                self._record_race_result(current_turn, program_id, race_result)
                return fresh_state
            raise
        race_result = self._race_result_from_response(out, current_turn, program_id)
        self._record_race_result(current_turn, program_id, race_result)
        if strategy:
            out_data = out.get("data") or {}
            if out_data.get("unchecked_event_array"):
                out = self._drain_events(client, strategy, out)
        return out

    def _race_progress(self, client, payload, preset=None, strategy=None):
        current_turn = payload.get("current_turn") or 1
        phase = payload.get("phase")
        chara = (payload.get("chara_info") or {})
        playing_state = self._safe_int(chara.get("playing_state"))
        if playing_state in {2, 3} and self._safe_int(chara.get("state")) != 0:
            detail = f"stale race metadata state {playing_state}/{chara.get('state')}; not safe to call race_end"
            self._log("race_progress_blocked", current_turn, detail)
            self._mark(last_action=detail)
            self.stop()
            return {"data": {"chara_info": chara, "race_start_info": payload.get("race_start_info") or {}}}
        if playing_state not in {2, 3, 4, 5}:
            self._log("race_skip", current_turn, f"not in race (state={playing_state})")
            return payload
        race_start_info = payload.get("race_start_info") or {}
        program_id = self._safe_int(race_start_info.get("program_id") or payload.get("program_id") or chara.get("race_program_id"))
        if playing_state in {3, 5} and not program_id and not race_start_info:
            self._log("race_state_stale", current_turn, f"state={playing_state} without active race metadata")
            try:
                return self._fresh_career_state(client, strategy)
            except Exception:
                return {"data": {"chara_info": chara}}

        if not phase:
            if playing_state == 2:
                phase = "start"
            elif playing_state == 3:
                phase = "end"
            else:
                phase = "out"
        
        if phase == "end":
            if playing_state in {1}:
                self._log("race_end_skip", current_turn, "resume already home")
            else:
                try:
                    end_result = None
                    race_result = None
                    pre_end_probe_attempted = False
                    if playing_state == 3:
                        probe_state = {"data": {"chara_info": chara, "race_start_info": race_start_info}}
                        end_result, race_result, pre_end_probe_attempted = self._try_unknown_continue_pre_race_end(
                            client,
                            probe_state,
                            current_turn,
                            program_id,
                            preset,
                            strategy=strategy,
                            race_start_info=race_start_info,
                        )
                    if end_result is None:
                        end_result = client.race_end(current_turn=current_turn)
                        end_result, race_result = self._resolve_race_end_with_retries(
                            client,
                            end_result,
                            current_turn,
                            program_id,
                            preset,
                            strategy=strategy,
                            race_start_info=race_start_info,
                        )
                    if not race_result:
                        race_result = self._race_result_from_response(end_result, current_turn, program_id)
                    self._record_race_result(current_turn, program_id, race_result)
                    self._log("race_end", current_turn, self._race_result_label(race_result) or "resume")
                    if not race_result and end_result and self._same_active_race_state(end_result, current_turn, program_id, playing_states={2, 3}):
                        self._log("race_progress_deferred", current_turn, "race continue returned replay state; deferring race_end/race_out")
                        return end_result
                except Exception as e:
                    err_str = str(e)
                    if "102" in err_str or "1503" in err_str:
                        code = "1503" if "1503" in err_str else "102"
                        self._log("race_end_reconciled", current_turn, f"resume already done ({code})")
                        try:
                            fresh_state = self._fresh_career_state(client, strategy)
                        except Exception:
                            return {"data": {"chara_info": chara, "race_start_info": race_start_info}}
                        if self._same_active_race_state(fresh_state, current_turn, program_id, playing_states={3}):
                            detail = f"race_end returned 102 and server still reports active race {program_id}; stopping to avoid retry loop"
                            self._log("race_progress_blocked", current_turn, detail)
                            self._mark(last_action=detail)
                            self.stop()
                            return fresh_state
                        fresh_data = fresh_state.get("data") or {}
                        if fresh_data.get("race_reward_info") or self._same_active_race_state(fresh_state, current_turn, program_id, playing_states={4, 5}):
                            fresh_state, race_result = self._resolve_race_end_with_retries(
                                client,
                                fresh_state,
                                current_turn,
                                program_id,
                                preset,
                                strategy=strategy,
                                race_start_info=fresh_data.get("race_start_info") or race_start_info,
                            )
                            fresh_data = fresh_state.get("data") or {}
                            if not race_result:
                                race_result = self._race_result_from_response(fresh_state, current_turn, program_id)
                            self._record_race_result(current_turn, program_id, race_result)
                            self._log("race_end", current_turn, self._race_result_label(race_result) or "resume reconciled")
                            return self._race_progress(client, {
                                "current_turn": current_turn,
                                "phase": "out",
                                "program_id": program_id,
                                "race_start_info": fresh_data.get("race_start_info") or race_start_info,
                                "chara_info": fresh_data.get("chara_info") or chara,
                            }, preset, strategy)
                        return fresh_state
                    else:
                        raise
            try:
                out = client.race_out(current_turn=current_turn)
                race_result = self._race_result_from_response(out, current_turn, program_id)
                self._record_race_result(current_turn, program_id, race_result)
                return out
            except Exception as e:
                if any(err in str(e) for err in ("102", "201", "StateRecoveryError")):
                    self._log("race_out_reconciled", current_turn, f"graceful exit: {e}")
                    fresh_state = self._fresh_career_state(client, strategy)
                    finished_state = self._finish_after_final_race_if_ready(
                        client, fresh_state, preset, strategy, current_turn, program_id, race_start_info,
                        reason="final race_out reconciled"
                    )
                    if finished_state is not None:
                        return finished_state
                    if self._same_active_race_state(fresh_state, current_turn, program_id, playing_states={3, 4, 5}):
                        detail = f"race_out failed and server still reports active race {program_id}; stopping to avoid retry loop"
                        self._log("race_progress_blocked", current_turn, detail)
                        self._mark(last_action=detail)
                        self.stop()
                        return fresh_state
                    race_result = self._race_result_from_response(fresh_state, current_turn, program_id)
                    self._record_race_result(current_turn, program_id, race_result)
                    return fresh_state
                raise
        if phase == "out":
            self._log("race_out", current_turn, "resume")
            try:
                out = client.race_out(current_turn=current_turn)
                race_result = self._race_result_from_response(out, current_turn, program_id)
                self._record_race_result(current_turn, program_id, race_result)
                return out
            except Exception as e:
                if any(err in str(e) for err in ("102", "201", "StateRecoveryError")):
                    self._log("race_out_reconciled", current_turn, f"graceful exit: {e}")
                    fresh_state = self._fresh_career_state(client, strategy)
                    finished_state = self._finish_after_final_race_if_ready(
                        client, fresh_state, preset, strategy, current_turn, program_id, race_start_info,
                        reason="final race_out reconciled"
                    )
                    if finished_state is not None:
                        return finished_state
                    if self._same_active_race_state(fresh_state, current_turn, program_id, playing_states={3, 4, 5}):
                        detail = f"race_out failed and server still reports active race {program_id}; stopping to avoid retry loop"
                        self._log("race_progress_blocked", current_turn, detail)
                        self._mark(last_action=detail)
                        self.stop()
                        return fresh_state
                    race_result = self._race_result_from_response(fresh_state, current_turn, program_id)
                    self._record_race_result(current_turn, program_id, race_result)
                    return fresh_state
                raise
        is_short = 1 if (race_start_info.get("is_short") or chara.get("is_short_race")) else 0
        try:
            client.race_start(is_short=is_short, current_turn=current_turn)
            self._log("race_start", current_turn, f"resume short {is_short}")
        except Exception as exc:
            if not any(code in str(exc) for code in ("102", "2502")):
                raise
            self._log("race_start_reconciled", current_turn, f"resume race_start rejected (server already advanced): {exc}")
        try:
            fresh_state = self._fresh_career_state(client, strategy)
            fresh_data = fresh_state.get("data") or {}
            fresh_chara = fresh_data.get("chara_info") or {}
            if self._same_active_race_state(fresh_state, current_turn, program_id, playing_states={3}):
                return self._race_progress(client, {
                    "current_turn": current_turn,
                    "phase": "end",
                    "program_id": program_id,
                    "race_start_info": fresh_data.get("race_start_info") or race_start_info,
                    "chara_info": fresh_chara,
                }, preset, strategy)
            return fresh_state
        except Exception:
            pass
        if playing_state in {1}:
            self._log("race_end_skip", current_turn, "resume already home")
        else:
            try:
                end_result = client.race_end(current_turn=current_turn)
                end_result, race_result = self._resolve_race_end_with_retries(
                    client,
                    end_result,
                    current_turn,
                    program_id,
                    preset,
                    strategy=strategy,
                    race_start_info=race_start_info,
                )
                if not race_result:
                    race_result = self._race_result_from_response(end_result, current_turn, program_id)
                self._record_race_result(current_turn, program_id, race_result)
                self._log("race_end", current_turn, self._race_result_label(race_result) or "resume")
            except Exception as e:
                err_str = str(e)
                if "102" in err_str or "1503" in err_str:
                    code = "1503" if "1503" in err_str else "102"
                    self._log("race_end_reconciled", current_turn, f"resume already done ({code})")
                else:
                    raise
        try:
            out = client.race_out(current_turn=current_turn)
            race_result = self._race_result_from_response(out, current_turn, program_id)
            self._record_race_result(current_turn, program_id, race_result)
            return out
        except Exception as e:
            if any(err in str(e) for err in ("102", "201", "StateRecoveryError")):
                self._log("race_out_reconciled", current_turn, f"graceful exit: {e}")
                fresh_state = self._fresh_career_state(client, strategy)
                finished_state = self._finish_after_final_race_if_ready(
                    client, fresh_state, preset, strategy, current_turn, program_id, race_start_info,
                    reason="final race_out reconciled"
                )
                if finished_state is not None:
                    return finished_state
                if self._same_active_race_state(fresh_state, current_turn, program_id, playing_states={3, 4, 5}):
                    detail = f"race_out failed and server still reports active race {program_id}; stopping to avoid retry loop"
                    self._log("race_progress_blocked", current_turn, detail)
                    self._mark(last_action=detail)
                    self.stop()
                    return fresh_state
                race_result = self._race_result_from_response(fresh_state, current_turn, program_id)
                self._record_race_result(current_turn, program_id, race_result)
                return fresh_state
            raise

    def _buy_skills(self, client, state, preset, force):
        snapshot_state = state
        state, bought = self.skill_buyer.buy(client, state, preset, force)
        if hasattr(self.skill_buyer, "enrich_state_with_known_bought"):
            state = self.skill_buyer.enrich_state_with_known_bought(state)
        for event in self.skill_buyer.attempt_events:
            self._debug("skills_attempt", state, {
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "selected_total_cost": self._sum_cost(event.get("selected") or []),
                "attempt_total_cost": self._sum_cost(event.get("attempt") or []),
                "payload": event.get("payload") or [],
                "recovery_cap_skipped": event.get("recovery_cap_skipped") or [],
                "result": self._api_result(event.get("result") or {}),
            })
        self._maybe_write_skill_error_snapshot(snapshot_state, preset, "skill_buy", {
            "force": bool(force),
            "phase": "turn_skill_buy",
        })
        # Only reload on a recoverable error. On success, gain_skills already returned
        # the updated state with fresh skill_point; re-loading is a wasted sensitive call
        # that pushes the bot closer to the server's rate limit on long sessions.
        if self.skill_buyer.recover_after_error:
            try:
                state = self._fresh_career_state(client)
                self._debug_turn(state, preset)
            except Exception as e:
                print(f"Skill phase reload failure: {e}")
                pass
        if bought:
            with self.lock:
                self.status["skills_bought"] += bought
                self.status["last_action"] = f"skills {bought}"
                self._log_locked("skills", (state.get("data") or {}).get("chara_info", {}).get("turn", 0), bought)
        return state

    def _maybe_buy_upcoming_stamina_skill(self, client, state, preset, strategy=None):
        if not self.race_planner:
            return state
        entry, check = self.race_planner.stamina_rescue_entry(state, preset)
        if not entry or not check:
            return state
        key = (int(entry.get("turn") or 0), int(entry.get("program_id") or 0))
        if key in self.stamina_rescue_attempts:
            return state
        current_turn = int(((state.get("data") or {}).get("chara_info") or {}).get("turn") or 0)
        required = (check.get("requirements") or {}).get("stamina")
        current = (check.get("stats") or {}).get("stamina")
        detail = f"{check.get('race_name')} in {int(entry.get('turn') or 0) - current_turn} turns"
        if required and current is not None:
            detail += f" (stamina {current}/{required})"
        self._log("race_stamina_watch", current_turn, detail)
        state = self._buy_stamina_skill_for_race(
            client,
            state,
            preset,
            int(entry.get("program_id") or 0),
            strategy,
            entry=entry,
            stamina_check=check,
            reason="scheduled stamina rescue",
        )
        result = dict(getattr(self.skill_buyer, "last_result", {}) or {})
        # If the bot checked too early, keep trying on later turns. SP and tips
        # can change from races/events before the mandatory G1 actually fires.
        retryable_skip = str(result.get("skip") or "") in {
            "no_skill_points_for_stamina_skill",
            "no_affordable_stamina_skill",
            "no_usable_stamina_skill_for_race",
        }
        if not retryable_skip:
            self.stamina_rescue_attempts.add(key)
        return state

    def _maybe_buy_kikuka_front_runner_recovery(self, client, state, preset, program_id, current_turn, strategy=None):
        if not self.race_planner:
            return state
        try:
            entry = self.race_planner.entry_for_program(preset, current_turn, program_id) or {}
            check = self.race_planner.kikuka_front_runner_guard_check(state, preset, program_id, entry)
        except Exception as exc:
            self._log("kikuka_stamina_guard_failed", current_turn, str(exc))
            return state
        if not check or not check.get("kikuka_front_runner_guard"):
            return state

        try:
            required_usable = int((preset or {}).get("kikuka_front_runner_min_usable_skills") or 0)
        except (TypeError, ValueError):
            required_usable = 0
        if required_usable > 0:
            chara = ((state.get("data") or {}).get("chara_info") or {})
            usable = self.skill_buyer.race_profile_safety_skill_count(chara, preset, check)
            safety_key = ("safety", int(check.get("program_id") or program_id or 0))
            if usable < required_usable and safety_key not in self.kikuka_front_guard_attempts:
                self.kikuka_front_guard_attempts.add(safety_key)
                self._log(
                    "kikuka_skill_guard",
                    current_turn,
                    f"buy usable style/generic skills {usable}/{required_usable}",
                )
                state = self._buy_profile_safety_skill_for_race(
                    client,
                    state,
                    preset,
                    int(program_id or 0),
                    strategy,
                    entry=entry,
                    stamina_check=check,
                    reason="Kikuka skill guard",
                )
                try:
                    check = self.race_planner.kikuka_front_runner_guard_check(state, preset, program_id, entry)
                except Exception:
                    pass

        if not check:
            return state
        if not check.get("stamina_low"):
            return state
        key = ("recovery", int(check.get("program_id") or program_id or 0))
        if key in self.kikuka_front_guard_attempts:
            return state
        chara = ((state.get("data") or {}).get("chara_info") or {})
        usable_count = self.skill_buyer.usable_stamina_recovery_skill_count(chara, check)
        if usable_count > 0:
            self._log(
                "kikuka_stamina_guard",
                current_turn,
                f"usable recovery already owned; stamina {check.get('raw_stats', {}).get('stamina')}/{check.get('kikuka_front_runner_min_stamina')}",
            )
            return state
        self.kikuka_front_guard_attempts.add(key)
        self._log(
            "kikuka_stamina_guard",
            current_turn,
            f"buy usable recovery; stamina {check.get('raw_stats', {}).get('stamina')}/{check.get('kikuka_front_runner_min_stamina')}",
        )
        return self._buy_stamina_skill_for_race(
            client,
            state,
            preset,
            int(program_id or 0),
            strategy,
            entry=entry,
            stamina_check=check,
            reason="Kikuka front guard",
        )

    def _maybe_buy_calendar_race_skills(self, client, state, preset, program_id, current_turn, strategy=None):
        if not self.race_planner or not bool((preset or {}).get("calendar_race_prebuy_enabled", True)):
            return state
        key = (self._safe_int(current_turn), self._safe_int(program_id))
        if key in self.calendar_prebuy_attempts:
            return state
        entry = self.race_planner.entry_for_program(preset, current_turn, program_id)
        if not entry:
            return state
        race_info = self._race_info_for_program(program_id)
        grade = str(race_info.get("grade") or entry.get("type") or "").strip().upper()
        raw_grades = (preset or {}).get("calendar_race_prebuy_grades", ["G1"])
        if isinstance(raw_grades, str):
            allowed_grades = {part.strip().upper() for part in raw_grades.split(",") if part.strip()}
        else:
            allowed_grades = {str(part or "").strip().upper() for part in (raw_grades or []) if str(part or "").strip()}
        all_scheduled_prebuy = bool((preset or {}).get("calendar_race_prebuy_all_scheduled", True))
        if allowed_grades and grade not in allowed_grades and not all_scheduled_prebuy:
            return state

        self.calendar_prebuy_attempts.add(key)
        try:
            stamina_check = self.race_planner.stamina_for_program(state, preset, program_id, entry)
        except Exception as exc:
            self._log("calendar_prebuy_check_failed", current_turn, str(exc))
            stamina_check = {
                "program_id": int(program_id or 0),
                "race_name": race_info.get("name") or entry.get("name") or str(program_id),
                "grade": grade,
                "style": entry.get("style") or (preset or {}).get("skill_profile_style") or "",
                "distance": entry.get("distance") or race_info.get("distance") or "",
            }
        stamina_check.setdefault("race_name", race_info.get("name") or entry.get("name") or str(program_id))
        stamina_check.setdefault("grade", grade)

        if stamina_check.get("stamina_low") or stamina_check.get("static_stamina_low"):
            state = self._buy_stamina_skill_for_race(
                client,
                state,
                preset,
                int(program_id or 0),
                strategy,
                entry=entry,
                stamina_check=stamina_check,
                reason="calendar pre-race stamina",
            )
            try:
                stamina_check = self.race_planner.stamina_for_program(state, preset, program_id, entry)
            except Exception:
                pass
            stamina_result = dict(getattr(self.skill_buyer, "last_result", {}) or {})
            stamina_still_low = bool(stamina_check.get("stamina_low")) or bool(stamina_check.get("static_stamina_low"))
            recovery_not_ready = str(stamina_result.get("skip") or "") in {
                "no_skill_points_for_stamina_skill",
                "no_affordable_stamina_skill",
            }
            if (
                stamina_still_low
                and recovery_not_ready
                and str(stamina_check.get("distance") or "").lower() == "long"
                and str(grade).upper() in {"G1", "G2", ""}
            ):
                self._log(
                    "calendar_prebuy_hold_for_recovery",
                    current_turn,
                    f"{stamina_check.get('race_name')} needs recovery; preserving SP ({stamina_result.get('points')})",
                )
                return state

        # The hyperparameter tuner can override these via
        # preset["learned_hyperparameters"]. Resolve learned > preset > default.
        _learned_hp = (preset or {}).get("learned_hyperparameters") or {}
        def _hp(name, fallback):
            if name in _learned_hp:
                try: return int(_learned_hp[name])
                except (TypeError, ValueError): pass
            v = (preset or {}).get(name)
            if v is not None:
                try: return int(v)
                except (TypeError, ValueError): pass
            return fallback
        def _coverage(check):
            try:
                if self.race_planner and hasattr(self.race_planner, "_static_race_core_coverage"):
                    return self.race_planner._static_race_core_coverage(check)
            except Exception:
                pass
            return {"coverage": 1.0, "speed_ratio": 1.0, "min_ratio": 1.0}
        try:
            max_skills = _hp("calendar_race_prebuy_max_skills", 4)
        except (TypeError, ValueError):
            max_skills = 4
        try:
            budget = _hp("calendar_race_prebuy_budget", 850)
        except (TypeError, ValueError):
            budget = 850
        try:
            reserve = _hp("calendar_race_prebuy_keep_sp", 100)
        except (TypeError, ValueError):
            reserve = 100
        try:
            min_sp = _hp("calendar_race_prebuy_min_sp", 280)
        except (TypeError, ValueError):
            min_sp = 280

        clean_record_mode = bool((preset or {}).get("scheduled_race_clean_record_mode", True))
        coverage = _coverage(stamina_check)
        try:
            min_static_coverage = float((preset or {}).get("scheduled_race_min_static_core_coverage") or 0.84)
        except (TypeError, ValueError):
            min_static_coverage = 0.84
        try:
            min_static_speed_ratio = float((preset or {}).get("scheduled_race_min_static_speed_ratio") or 0.82)
        except (TypeError, ValueError):
            min_static_speed_ratio = 0.82
        dangerous = (
            bool(stamina_check.get("stamina_low"))
            or bool(stamina_check.get("static_stamina_low"))
            or float(coverage.get("coverage") or 1.0) < min_static_coverage
            or float(coverage.get("speed_ratio") or 1.0) < min_static_speed_ratio
            or str(grade).upper() in {"G1", "G2"}
        )
        if clean_record_mode:
            try:
                clean_min_sp = int((preset or {}).get("calendar_race_clean_prebuy_min_sp") or 120)
            except (TypeError, ValueError):
                clean_min_sp = 120
            try:
                clean_reserve = int((preset or {}).get("calendar_race_clean_prebuy_keep_sp") or 0)
            except (TypeError, ValueError):
                clean_reserve = 0
            try:
                clean_budget = int((preset or {}).get("calendar_race_clean_prebuy_budget") or max(1000, budget))
            except (TypeError, ValueError):
                clean_budget = max(1000, budget)
            try:
                clean_max = int((preset or {}).get("calendar_race_clean_prebuy_max_skills") or max(8, max_skills))
            except (TypeError, ValueError):
                clean_max = max(8, max_skills)
            if dangerous:
                min_sp = min(min_sp, clean_min_sp)
                reserve = min(reserve, clean_reserve)
                budget = max(budget, clean_budget)
                if str(grade).upper() == "G1" or bool(stamina_check.get("stamina_low")):
                    max_skills = max(max_skills, min(clean_max, 5))
                else:
                    max_skills = max(max_skills, min(clean_max, 2))
            elif all_scheduled_prebuy and str(grade).upper() not in {"G1", "G2"}:
                # Keep end-buy intact on low-risk scheduled fillers.
                max_skills = min(max_skills, 1)

        snapshot_state = state
        state, bought = self.skill_buyer.buy_limited_for_race(
            client,
            state,
            preset,
            stamina_check,
            max_skills=max_skills,
            budget=budget,
            reserve=reserve,
            min_sp=min_sp,
        )
        for event in self.skill_buyer.attempt_events:
            self._debug("pre_race_calendar_skill_attempt", state, {
                "stamina_check": stamina_check,
                "clean_record_mode": clean_record_mode,
                "prebuy_limits": {
                    "grade": grade,
                    "dangerous": dangerous,
                    "coverage": coverage,
                    "min_sp": min_sp,
                    "budget": budget,
                    "reserve": reserve,
                    "max_skills": max_skills,
                },
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "selected_total_cost": self._sum_cost(event.get("selected") or []),
                "attempt_total_cost": self._sum_cost(event.get("attempt") or []),
                "payload": event.get("payload") or [],
                "result": self._api_result(event.get("result") or {}),
            })
        self._maybe_write_skill_error_snapshot(snapshot_state, preset, "pre_race_calendar_skill_buy", {
            "reason": "mandatory calendar race prebuy",
            "program_id": int(program_id or 0),
            "stamina_check": stamina_check,
        })
        if self.skill_buyer.attempt_events or self.skill_buyer.recover_after_error:
            try:
                state = self._fresh_career_state(client, strategy)
                self._debug_turn(state, preset)
            except Exception as e:
                print(f"Pre-race calendar skill reload failure: {e}")
        if bought:
            with self.lock:
                self.status["skills_bought"] += bought
                self.status["last_action"] = f"calendar pre-race skill {bought}"
                self._log_locked("skills", current_turn, f"calendar pre-race {bought}")
        return state

    def _buy_profile_safety_skill_for_race(self, client, state, preset, program_id, strategy=None, entry=None, stamina_check=None, reason="pre-race profile safety"):
        try:
            stamina_check = stamina_check or self.race_planner.stamina_for_program(state, preset, program_id, entry)
        except Exception as exc:
            print(f"Pre-race profile skill check failed: {exc}")
            return state
        snapshot_state = state
        state, bought = self.skill_buyer.buy_profile_safety_for_race(client, state, preset, stamina_check)
        for event in self.skill_buyer.attempt_events:
            self._debug("pre_race_profile_skill_attempt", state, {
                "stamina_check": stamina_check,
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "selected_total_cost": self._sum_cost(event.get("selected") or []),
                "attempt_total_cost": self._sum_cost(event.get("attempt") or []),
                "payload": event.get("payload") or [],
                "result": self._api_result(event.get("result") or {}),
            })
        self._maybe_write_skill_error_snapshot(snapshot_state, preset, "pre_race_profile_skill_buy", {
            "reason": reason,
            "program_id": int(program_id or 0),
            "stamina_check": stamina_check,
        })
        if self.skill_buyer.attempt_events or self.skill_buyer.recover_after_error:
            try:
                state = self._fresh_career_state(client, strategy)
                self._debug_turn(state, preset)
            except Exception as e:
                print(f"Pre-race profile skill reload failure: {e}")
        if bought:
            with self.lock:
                self.status["skills_bought"] += bought
                self.status["last_action"] = f"{reason} skill {bought}"
                self._log_locked("skills", (state.get("data") or {}).get("chara_info", {}).get("turn", 0), f"{reason} {bought}")
        return state

    def _maybe_change_running_style(self, client, state, preset, program_id, current_turn):
        scheduled_entry = None
        if self.race_planner:
            scheduled_entry = self.race_planner.entry_for_program(preset, current_turn, program_id) or {}
        resolution = {}
        desired_style = ""
        if self.race_planner:
            resolution = self.race_planner.style_resolution_for_entry(
                scheduled_entry or {"program_id": program_id},
                preset,
                program_id,
            ) or {}
            desired_style = str(resolution.get("style") or "").strip()
        if not desired_style:
            desired_style = str((scheduled_entry or {}).get("style") or (preset or {}).get("skill_profile_style") or "").strip()
        if not desired_style:
            return
        desired_value = STYLE_TO_TACTIC.get(desired_style)
        if not desired_value:
            return
        chara = (state.get("data") or {}).get("chara_info") or {}
        current_value = self._safe_int(chara.get("race_running_style"))
        if current_value == desired_value:
            self._set_race_style_context(current_turn, program_id, {
                "desired_style": desired_style,
                "desired_running_style": desired_value,
                "style_source": str(resolution.get("source") or ""),
                "current_style": TACTIC_TO_STYLE.get(current_value, str(current_value or "?")),
                "current_running_style": current_value,
                "attempted": False,
                "succeeded": True,
                "changed": False,
                "applied_style": desired_style,
                "applied_running_style": desired_value,
            })
            return
        current_style = TACTIC_TO_STYLE.get(current_value, str(current_value or "?"))
        try:
            client.change_running_style(program_id=program_id, running_style=desired_value, current_turn=current_turn)
            self._log("change_running_style", current_turn, f"{current_style} -> {desired_style}")
            self._set_race_style_context(current_turn, program_id, {
                "desired_style": desired_style,
                "desired_running_style": desired_value,
                "style_source": str(resolution.get("source") or ""),
                "current_style": current_style,
                "current_running_style": current_value,
                "attempted": True,
                "succeeded": True,
                "changed": True,
                "applied_style": desired_style,
                "applied_running_style": desired_value,
            })
        except Exception as exc:
            self._log("change_running_style_failed", current_turn, f"{current_style} -> {desired_style}: {exc}")
            self._set_race_style_context(current_turn, program_id, {
                "desired_style": desired_style,
                "desired_running_style": desired_value,
                "style_source": str(resolution.get("source") or ""),
                "current_style": current_style,
                "current_running_style": current_value,
                "attempted": True,
                "succeeded": False,
                "changed": False,
                "applied_style": current_style,
                "applied_running_style": current_value,
                "error": str(exc),
            })

    def _set_race_style_context(self, current_turn, program_id, context):
        key = (self._safe_int(current_turn), self._safe_int(program_id))
        if key == (0, 0):
            return
        self.race_style_context[key] = dict(context or {})

    def _latest_vision_running_style(self, turn):
        """Return the numeric race_running_style from the most recently
        recorded bot_vision for `turn` (or the closest earlier turn).

        Fallback source for the running-style label when a race fires
        without the bot issuing a style change (so race_style_context
        is empty). Reads from self.report's events trail."""
        if not self.report:
            return 0
        events = (self.report or {}).get("events") if isinstance(self.report, dict) else None
        if not isinstance(events, list):
            return 0
        target = self._safe_int(turn)
        best_turn = -1
        best_value = 0
        for ev in events:
            if not isinstance(ev, dict):
                continue
            row_turn = self._safe_int(ev.get("turn"))
            if target and row_turn > target:
                continue
            vision = ev.get("bot_vision") or {}
            if not isinstance(vision, dict):
                continue
            value = self._safe_int(vision.get("race_running_style"))
            if value and row_turn >= best_turn:
                best_turn = row_turn
                best_value = value
        return best_value

    def _race_style_context_for(self, current_turn, program_id):
        key = (self._safe_int(current_turn), self._safe_int(program_id))
        if key in self.race_style_context:
            return dict(self.race_style_context.get(key) or {})
        for fallback in (
            (self._safe_int(current_turn), 0),
            (0, self._safe_int(program_id)),
        ):
            if fallback in self.race_style_context:
                return dict(self.race_style_context.get(fallback) or {})
        return {}

    def _buy_stamina_skill_for_race(self, client, state, preset, program_id, strategy=None, entry=None, stamina_check=None, reason="pre-race stamina"):
        try:
            stamina_check = stamina_check or self.race_planner.stamina_for_program(state, preset, program_id, entry)
        except Exception as exc:
            print(f"Pre-race stamina check failed: {exc}")
            return state
        snapshot_state = state
        state, bought = self.skill_buyer.buy_stamina_for_race(client, state, preset, stamina_check)
        for event in self.skill_buyer.attempt_events:
            self._debug("pre_race_stamina_skill_attempt", state, {
                "stamina_check": stamina_check,
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "selected_total_cost": self._sum_cost(event.get("selected") or []),
                "attempt_total_cost": self._sum_cost(event.get("attempt") or []),
                "payload": event.get("payload") or [],
                "result": self._api_result(event.get("result") or {}),
            })
        if not self.skill_buyer.attempt_events:
            self._debug("pre_race_stamina_skill_skip", state, {
                "stamina_check": stamina_check,
                "result": dict(self.skill_buyer.last_result or {}),
            })
        self._maybe_write_skill_error_snapshot(snapshot_state, preset, "pre_race_stamina_skill_buy", {
            "reason": reason,
            "program_id": int(program_id or 0),
            "stamina_check": stamina_check,
        })
        if self.skill_buyer.attempt_events or self.skill_buyer.recover_after_error:
            try:
                state = self._fresh_career_state(client, strategy)
                self._debug_turn(state, preset)
            except Exception as e:
                print(f"Pre-race stamina skill reload failure: {e}")
        if bought:
            with self.lock:
                self.status["skills_bought"] += bought
                self.status["last_action"] = f"{reason} skill {bought}"
                self._log_locked("skills", (state.get("data") or {}).get("chara_info", {}).get("turn", 0), f"{reason} {bought}")
        return state

    def _handle_items(self, client, state, preset, best_command):
        if int((preset or {}).get("scenario_id") or (preset or {}).get("scenario") or 4) != 4:
            return state
        self.item_manager.recover_after_exchange_error = False
        self.item_manager.recover_after_use_error = False
        snapshot_state = state
        state, bought, used = self.item_manager.handle(client, state, preset, best_command, self.status, self.race_planner)
        for event in self.item_manager.buy_attempt_events:
            self._debug("items_buy_attempt", state, {
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "selected_total_cost": self._sum_cost(event.get("selected") or []),
                "attempt_total_cost": self._shop_attempt_cost(event.get("attempt") or [], event.get("selected") or []),
                "payload": event.get("payload") or [],
                "result": self._api_result(event.get("result") or {}),
            })
        for event in self.item_manager.use_attempt_events:
            self._debug("items_use_attempt", state, {
                "selected": event.get("selected") or [],
                "attempt": event.get("attempt") or [],
                "payload": event.get("payload") or [],
                "result": self._api_result(event.get("result") or {}),
            })
        self._maybe_write_item_error_snapshot(snapshot_state, preset, "item_buy", result=self.item_manager.last_buy_result, recover_flag=self.item_manager.recover_after_exchange_error, extra={
            "phase": "turn_items",
            "best_command": best_command or {},
            "bought": int(bought or 0),
        })
        self._maybe_write_item_error_snapshot(snapshot_state, preset, "item_use", result=self.item_manager.last_use_result, recover_flag=self.item_manager.recover_after_use_error, extra={
            "phase": "turn_items",
            "best_command": best_command or {},
            "used": int(used or 0),
        })
        if self.item_manager.recover_after_exchange_error or self.item_manager.recover_after_use_error or self.item_manager.buy_attempt_events or self.item_manager.use_attempt_events:
            try:
                state = self._fresh_career_state(client)
                self._debug_turn(state, preset)
            except Exception as e:
                print(f"Item phase reload failure: {e}")
                pass
        if bought or used:
            turn = (state.get("data") or {}).get("chara_info", {}).get("turn", 0)
            with self.lock:
                self.status["items_bought"] += bought
                self.status["items_used"] += used
                if bought:
                    self._log_locked("items_buy", turn, bought)
                if used:
                    self._log_locked("items_use", turn, used)
            # Fresh state is already handled by handle() or recovery logic
        return state

    def _merge_state(self, old_state, new_state):
        if not old_state:
            return new_state
        merged = dict(old_state)
        merged["data"] = dict(old_state.get("data") or {})
        for k, v in (new_state.get("data") or {}).items():
            if isinstance(v, dict) and k in merged["data"] and isinstance(merged["data"][k], dict):
                merged_sub = dict(merged["data"][k])
                for sub_k, sub_v in v.items():
                    if sub_v is not None:
                        merged_sub[sub_k] = sub_v
                merged["data"][k] = merged_sub
            else:
                merged["data"][k] = v
        return merged

    def _command_from_decision(self, state, decision):
        payload = decision.payload or {}
        command_type = int(payload.get("command_type") or 0)
        command_id = int(payload.get("command_id") or 0)
        command_group_id = int(payload.get("command_group_id") or 0)
        for cmd in ((state.get("data") or {}).get("home_info") or {}).get("command_info_array") or []:
            if int(cmd.get("command_type") or 0) != command_type:
                continue
            if command_type == 3 and int(cmd.get("command_id") or 0) == command_group_id:
                return cmd
            if int(cmd.get("command_id") or 0) == command_id:
                return cmd
        return payload

    def _track_turn_scores(self, state):
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        max_score = 0
        has_training = False
        for cmd in commands:
            if int(cmd.get("command_type") or 0) == 1:
                has_training = True
                score = self.item_manager._command_stat_gain(cmd)
                if score > max_score:
                    max_score = score
        if has_training:
            with self.lock:
                dh = self.status.setdefault("date_history", [])
                sh = self.status.setdefault("score_history", [])
                if not dh or dh[-1] != turn:
                    dh.append(turn)
                    sh.append(max_score)
                    if len(dh) > 48:
                        dh.pop(0)
                        sh.pop(0)
