import hashlib
import json
from pathlib import Path

from career_bot.race_learning_filters import (
    APTITUDE_RANKS,
    aptitude_rank,
    normalize_distance_key,
    normalize_surface_key,
    off_aptitude_dimensions_for_learning,
    sample_chara_aptitudes,
)
from career_bot.career_trajectory_prediction import predict_trajectory
from career_bot.race_schedule import RaceCatalog, RaceStaminaEstimator, TACTIC_TO_STYLE, normalize_style
from career_bot.race_success_feedback import empirical_success_viability


DEFAULT_FAN_REQUIREMENTS = {
    "G1": 5000,
    "G2": 1900,
    "G3": 1000,
    "OP": 350,
    "PRE-OP": 0,
}

JUNIOR_FAN_REQUIREMENTS = {
    "G1": 1000,
    "G2": 1000,
    "G3": 350,
    "OP": 0,
    "PRE-OP": 0,
}

OPTIONAL_RACE_GP_BY_GRADE = {
    "G2": 5300,
    "G3": 3800,
    "OP": 1300,
}

OPTIONAL_RACE_SCORE_BY_GRADE = {
    "G2": 1.05,
    "G3": 0.85,
    "OP": 0.35,
}

DEFAULT_EPITHET_THRESHOLDS = [50000, 100000, 200000, 400000]


class RacePlanner:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.meta = {}
        self.program = {}
        self.instance = {}
        self.rejected = set()
        self.catalog = RaceCatalog(base_dir)
        self.stamina_estimator = RaceStaminaEstimator()
        self.last_stamina_check = None
        self.last_skip_reason = None
        self.affinity_meta = self._load_affinity_meta()
        self._load()

    def _load(self):
        path = self.base_dir / "data" / "race_map.json"
        if not path.exists():
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        self.meta = {int(k): v for k, v in (data.get("meta") or {}).items()}
        self.program = {int(k): v for k, v in (data.get("program") or {}).items()}
        self.instance = {int(k): [int(item) for item in v] for k, v in (data.get("instance") or {}).items()}

    def _load_affinity_meta(self):
        path = self.base_dir / "public" / "assets" / "data" / "affinity_race_meta.json"
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def wanted_programs(self, preset):
        result = set()
        for item in preset.get("custom_race_schedule") or []:
            pid = int(item.get("program_id") or 0)
            if pid:
                result.add(pid)
        for value in preset.get("extra_race_list") or []:
            try:
                race_id = int(value)
            except (TypeError, ValueError):
                continue
            if race_id in self.meta:
                info = self.meta[race_id]
                pid = info.get("program_id")
                if pid:
                    result.add(pid)
                continue
            if race_id in self.program:
                result.add(race_id)
                continue
            for program_id in self.instance.get(race_id, []):
                result.add(program_id)
        return result

    def scheduled_entries(self, preset):
        entries = []
        for item in preset.get("custom_race_schedule") or []:
            try:
                turn = int(item.get("turn") or 0)
                program_id = int(item.get("program_id") or 0)
            except (TypeError, ValueError):
                continue
            if turn and program_id:
                entries.append(dict(item))
        if entries:
            return sorted(entries, key=lambda item: (int(item.get("turn") or 0), int(item.get("race_id") or 0)))

        for value in preset.get("extra_race_list") or []:
            try:
                race_id = int(value)
            except (TypeError, ValueError):
                continue
            race = self.catalog.by_id.get(race_id) or {}
            info = self.meta.get(race_id) or {}
            program_id = int(race.get("program_id") or info.get("program_id") or 0)
            turn = int(race.get("turn") or info.get("turn") or 0)
            if not program_id or not turn:
                continue
            entries.append({
                "race_id": race_id,
                "program_id": program_id,
                "turn": turn,
                "name": race.get("name") or info.get("name", ""),
                "date": race.get("date", ""),
                "type": race.get("type", ""),
                "terrain": race.get("terrain", ""),
                "distance": race.get("distance", ""),
                "venue": race.get("venue", ""),
                "style": "",
                })
        return sorted(entries, key=lambda item: (int(item.get("turn") or 0), int(item.get("race_id") or 0)))

    def scheduled_entries_for_turn(self, preset, turn):
        try:
            turn = int(turn or 0)
        except (TypeError, ValueError):
            turn = 0
        if not turn:
            return []
        return [
            entry
            for entry in self.scheduled_entries(preset)
            if int(entry.get("turn") or 0) == turn
        ]

    def available_programs(self, state):
        data = state.get("data") or {}
        rca = data.get("race_condition_array") or []
        available = set()
        for item in rca:
            pid = int(item.get("program_id") or 0)
            if pid:
                available.add(pid)
        return available

    def _career_race_history(self, state):
        data = (state or {}).get("data") or {}
        history = data.get("race_history") or []
        if isinstance(history, dict):
            return [history]
        if isinstance(history, list):
            return [row for row in history if isinstance(row, dict)]
        return []

    def _has_career_race_win(self, state):
        for row in self._career_race_history(state):
            try:
                if int(row.get("result_rank") or 0) == 1:
                    return True
            except (TypeError, ValueError):
                continue
        return False

    def _needs_debut_recovery_race(self, state, preset):
        if not bool((preset or {}).get("debut_loss_recovery_race_enabled", True)):
            return False
        history = self._career_race_history(state)
        if not history:
            return False
        return not self._has_career_race_win(state)

    def _program_name(self, program_id):
        program_id = int(program_id or 0)
        race = self.catalog.by_program_id.get(program_id) or {}
        program = self.program.get(program_id) or {}
        return str(race.get("name") or program.get("name") or program_id)

    def _entry_from_program(self, program_id, turn):
        program_id = int(program_id or 0)
        race = self.catalog.by_program_id.get(program_id) or {}
        program = self.program.get(program_id) or {}
        return {
            "race_id": race.get("id", 0),
            "program_id": program_id,
            "turn": int(turn or 0),
            "name": race.get("name") or program.get("name") or str(program_id),
            "terrain": race.get("terrain", ""),
            "distance": race.get("distance", ""),
            "style": "",
        }

    def _is_debut_recovery_program(self, program_id):
        program_id = int(program_id or 0)
        race = self.catalog.by_program_id.get(program_id) or {}
        program = self.program.get(program_id) or {}
        name = str(race.get("name") or program.get("name") or "").lower()
        race_instance_id = str(race.get("race_instance_id") or program.get("race_instance_id") or "")
        grade = self.race_grade(program_id, race)
        return (
            "maiden" in name
            or race_instance_id.startswith("9")
            or grade in {"", "PRE-OP", "OP"}
        )

    def debut_recovery_program(self, state, preset, available=None, turn=None):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        if turn is None:
            turn = self._safe_int(chara.get("turn"), 0)
        available = set(available or self.available_programs(state))
        candidates = []
        for program_id in sorted(available):
            if (turn, program_id) in self.rejected:
                continue
            if not self._is_debut_recovery_program(program_id):
                continue
            entry = self._entry_from_program(program_id, turn)
            if not self.fan_eligible(state, preset, program_id, entry):
                continue
            if not self.aptitude_eligible(state, preset, program_id, entry):
                continue
            name = self._program_name(program_id).lower()
            race = self.catalog.by_program_id.get(program_id) or {}
            program = self.program.get(program_id) or {}
            race_instance_id = str(race.get("race_instance_id") or program.get("race_instance_id") or "")
            priority = 0
            if "maiden" in name:
                priority -= 100
            if race_instance_id.startswith("9"):
                priority -= 20
            candidates.append((priority, program_id))
        if not candidates:
            return 0
        return min(candidates)[1]

    def forced_program(self, state):
        data = state.get("data") or {}
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        race_enabled = any(cmd.get("command_type") == 4 and cmd.get("command_id") == 401 and cmd.get("is_enable", 0) for cmd in commands)
        other_enabled = any(cmd.get("command_type") != 4 and cmd.get("is_enable", 0) for cmd in commands)
        if not race_enabled or other_enabled:
            return 0
        for item in data.get("race_condition_array") or []:
            pid = int(item.get("program_id") or 0)
            if pid:
                return pid
        race = data.get("race_start_info") or {}
        return int(race.get("program_id") or 0)

    def choose(self, state, preset, training_context=None):
        self.last_stamina_check = None
        self.last_skip_reason = None
        training_context = training_context or {}
        data = state.get("data") or {}
        turn = int((data.get("chara_info") or {}).get("turn") or 0)
        force_calendar = bool((preset or {}).get("scheduled_race_force_calendar", True))
        scheduled = self.scheduled_entries(preset)
        candidates = [entry for entry in scheduled if int(entry.get("turn") or 0) == turn]
        
        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        race_enabled = any(cmd.get("command_type") == 4 and cmd.get("command_id") == 401 and cmd.get("is_enable", 0) for cmd in commands)
        if not race_enabled:
            if candidates:
                self.last_skip_reason = {
                    "reason": "scheduled_race_button_unavailable",
                    "turn": turn,
                    "scheduled": [
                        {
                            "program_id": int(entry.get("program_id") or 0),
                            "name": entry.get("name", ""),
                        }
                        for entry in candidates
                    ],
                }
            return 0

        available = self.available_programs(state)
        if not available:
            if candidates:
                self.last_skip_reason = {
                    "reason": "scheduled_race_not_available",
                    "turn": turn,
                    "scheduled": [
                        {
                            "program_id": int(entry.get("program_id") or 0),
                            "name": entry.get("name", ""),
                        }
                        for entry in candidates
                    ],
                }
            return 0

        if candidates and self._needs_debut_recovery_race(state, preset):
            recovery_program_id = self.debut_recovery_program(state, preset, available, turn)
            scheduled = [
                {
                    "program_id": int(entry.get("program_id") or 0),
                    "name": entry.get("name", ""),
                }
                for entry in candidates
            ]
            if recovery_program_id:
                self.last_skip_reason = {
                    "reason": "debut_loss_recovery_race_selected",
                    "turn": turn,
                    "program_id": recovery_program_id,
                    "race_name": self._program_name(recovery_program_id),
                    "scheduled_deferred": scheduled,
                }
                return recovery_program_id
            self.last_skip_reason = {
                "reason": "debut_loss_recovery_needed_no_available_race",
                "turn": turn,
                "scheduled_deferred": scheduled,
            }
            return 0

        if candidates:
            skipped = []
            for entry in candidates:
                program_id = int(entry.get("program_id") or 0)
                if program_id not in available or (turn, program_id) in self.rejected:
                    skipped.append({"program_id": program_id, "reason": "unavailable_or_rejected"})
                    continue
                if not self.fan_eligible(state, preset, program_id, entry):
                    skipped.append({"program_id": program_id, "reason": "insufficient_fans"})
                    continue
                # NOTE: aptitude gate does NOT apply to user-scheduled
                # races. If the user put it on the calendar they chose
                # to run it; we don't second-guess. The gate only fires
                # for `choose_optional` (bot's own auto-picks).
                if force_calendar:
                    self.last_skip_reason = None
                    return program_id
                if self._strong_training_context(preset, training_context) and bool((preset or {}).get("scheduled_race_respect_training", False)):
                    skipped.append({
                        "program_id": program_id,
                        "reason": "training_too_good_for_scheduled_race",
                        "training_score": training_context.get("score"),
                        "stat_gain": training_context.get("stat_gain"),
                        "rainbow_count": training_context.get("rainbow_count"),
                    })
                    continue
                allowed, reason, check = self._scheduled_race_safety_gate(state, preset, program_id, entry)
                if not allowed:
                    skipped.append({
                        "program_id": program_id,
                        "reason": reason.get("reason") or "scheduled_race_unsafe",
                        "detail": reason,
                    })
                    continue
                self.last_skip_reason = None
                self.last_stamina_check = check
                return program_id
            if skipped:
                self.last_skip_reason = {"reason": "no_scheduled_race_selected", "turn": turn, "skipped": skipped[:8]}
            return 0
        if scheduled:
            return 0

        wanted = self.wanted_programs(preset)
        skipped = []
        for program_id in sorted(wanted):
            if program_id in available and (turn, program_id) not in self.rejected:
                race = self.catalog.by_program_id.get(program_id) or {}
                entry = {
                    "race_id": race.get("id", 0),
                    "program_id": program_id,
                    "turn": turn,
                    "name": race.get("name", ""),
                    "terrain": race.get("terrain", ""),
                    "distance": race.get("distance", ""),
                    "style": "",
                }
                if not self.fan_eligible(state, preset, program_id, entry):
                    skipped.append({"program_id": program_id, "reason": "insufficient_fans"})
                    continue
                # User-wanted races bypass the aptitude gate too — same
                # rationale as scheduled candidates above. Only
                # choose_optional applies the gate to auto-picks.
                if force_calendar:
                    self.last_skip_reason = None
                    return program_id
                if self._strong_training_context(preset, training_context) and bool((preset or {}).get("scheduled_race_respect_training", False)):
                    skipped.append({
                        "program_id": program_id,
                        "reason": "training_too_good_for_scheduled_race",
                        "training_score": training_context.get("score"),
                        "stat_gain": training_context.get("stat_gain"),
                        "rainbow_count": training_context.get("rainbow_count"),
                    })
                    continue
                allowed, reason, check = self._scheduled_race_safety_gate(state, preset, program_id, entry)
                if not allowed:
                    skipped.append({
                        "program_id": program_id,
                        "reason": reason.get("reason") or "scheduled_race_unsafe",
                        "detail": reason,
                    })
                    continue
                self.last_skip_reason = None
                self.last_stamina_check = check
                return program_id
        if skipped:
            self.last_skip_reason = {"reason": "no_wanted_race_selected", "turn": turn, "skipped": skipped[:8]}
        return 0

    def choose_optional(self, state, preset, training_context=None):
        self.last_stamina_check = None
        self.last_skip_reason = None
        training_context = training_context or {}
        if not bool((preset or {}).get("optional_race_leniency_enabled", True)):
            self.last_skip_reason = {"reason": "optional_race_disabled"}
            return 0

        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = self._safe_int(chara.get("turn"), 0)
        max_turn = self._safe_int((preset or {}).get("optional_race_max_turn"), 72)
        if turn <= 0 or (max_turn and turn > max_turn):
            self.last_skip_reason = {"reason": "optional_race_outside_turn_window", "turn": turn, "max_turn": max_turn}
            return 0

        if bool(training_context.get("is_climax_turn")):
            self.last_skip_reason = {"reason": "twinkle_star_climax_window", "turn": turn}
            return 0

        consecutive = self._safe_int(training_context.get("consecutive_race_count"), 0)
        consecutive_limit = self._safe_int((preset or {}).get("optional_race_consecutive_limit"), 2)
        if consecutive_limit and consecutive >= consecutive_limit:
            self.last_skip_reason = {
                "reason": "consecutive_race_fatigue_guard",
                "turn": turn,
                "consecutive_race_count": consecutive,
                "consecutive_race_limit": consecutive_limit,
            }
            return 0

        if self._strong_training_context(preset, training_context):
            self.last_skip_reason = {
                "reason": "training_too_good_for_optional_race",
                "turn": turn,
                "training_score": training_context.get("score"),
                "stat_gain": training_context.get("stat_gain"),
                "rainbow_count": training_context.get("rainbow_count"),
            }
            return 0

        home = data.get("home_info") or {}
        commands = home.get("command_info_array") or []
        race_enabled = any(cmd.get("command_type") == 4 and cmd.get("command_id") == 401 and cmd.get("is_enable", 0) for cmd in commands)
        if not race_enabled:
            self.last_skip_reason = {"reason": "race_command_disabled"}
            return 0

        available = self.available_programs(state)
        if not available:
            self.last_skip_reason = {"reason": "no_available_optional_races"}
            return 0

        allowed_grades = self._optional_allowed_grades(preset)
        rival_program_ids = self._rival_program_ids(data)
        min_value = self._safe_float((preset or {}).get("optional_race_min_value"), 0.75)
        training_score = self._safe_float(training_context.get("score"), 999.0)
        stat_lag_factor = self._safe_float(training_context.get("stat_lag_factor"), 1.0)
        run_mode, prediction = self._current_run_mode(state, preset)
        run_mode_policy = (preset or {}).get("run_mode_policy") or {}
        training_score_adjustment = 0.0
        if run_mode == "preserve":
            min_value += self._safe_float(run_mode_policy.get("preserve_optional_race_penalty"), 0.03)
            training_score_adjustment -= self._safe_float(run_mode_policy.get("preserve_training_score_penalty"), 0.02)
        elif run_mode == "push":
            min_value -= self._safe_float(run_mode_policy.get("push_optional_race_bonus"), 0.02)
            training_score_adjustment += self._safe_float(run_mode_policy.get("push_training_score_bonus"), 0.015)
        if stat_lag_factor <= 0:
            stat_lag_factor = 1.0
        candidates = []
        skipped = []
        for program_id in sorted(available):
            if (turn, program_id) in self.rejected:
                skipped.append({"program_id": program_id, "reason": "rejected"})
                continue
            race = self.catalog.by_program_id.get(program_id) or {}
            entry = self._entry_from_race(program_id, race, turn)
            grade = self.race_grade(program_id, entry)
            is_rival = program_id in rival_program_ids
            if grade == "G1":
                skipped.append({"program_id": program_id, "reason": "g1_not_allowed"})
                continue
            if grade not in allowed_grades and not is_rival:
                skipped.append({"program_id": program_id, "reason": "grade_not_allowed", "grade": grade})
                continue
            if not self.fan_eligible(state, preset, program_id, entry):
                skipped.append({"program_id": program_id, "reason": "insufficient_fans"})
                continue
            if not self.aptitude_eligible(state, preset, program_id, entry):
                skipped.append({
                    "program_id": program_id,
                    "reason": "off_aptitude",
                    "detail": dict(self.last_skip_reason or {}),
                })
                continue

            check = self.kikuka_front_runner_guard_check(state, preset, program_id, entry) or self.stamina_for_program(state, preset, program_id, entry)
            if bool((preset or {}).get("optional_race_skip_if_stamina_low", True)) and check.get("stamina_low"):
                skipped.append({"program_id": program_id, "reason": "stamina_low", "grade": grade})
                continue

            value_info = self._optional_race_value(data, preset, program_id, entry, grade, is_rival)
            max_training_score = self._optional_training_threshold(preset, value_info)
            max_training_score = max(0.20, max_training_score + training_score_adjustment)
            adjusted_max_training_score = max_training_score * stat_lag_factor
            if training_score > adjusted_max_training_score:
                skipped.append({
                    "program_id": program_id,
                    "reason": "training_score_too_high",
                    "grade": grade,
                    "training_score": training_score,
                    "max_training_score": adjusted_max_training_score,
                    "base_max_training_score": max_training_score,
                    "stat_lag_factor": stat_lag_factor,
                })
                continue
            if value_info["score"] < min_value:
                skipped.append({"program_id": program_id, "reason": "race_value_too_low", "grade": grade, "score": value_info["score"]})
                continue
            candidates.append((value_info["score"], -program_id, program_id, entry, value_info, check))

        if not candidates:
            self.last_stamina_check = None
            self.last_skip_reason = {"reason": "no_optional_race_selected", "turn": turn, "skipped": skipped[:8]}
            return 0

        _, _, program_id, entry, value_info, check = max(candidates, key=lambda row: row[0:2])
        self.last_stamina_check = check
        self.last_skip_reason = {
            "reason": "optional_race_selected",
            "turn": turn,
            "program_id": program_id,
            "race_name": entry.get("name") or str(program_id),
            "grade": value_info.get("grade"),
            "score": value_info.get("score"),
            "rival": value_info.get("rival"),
            "crosses_epithet": value_info.get("crosses_epithet"),
            "training_score": training_score,
            "run_mode": run_mode,
            "trajectory_label": prediction.get("label"),
            "trajectory_confidence": prediction.get("confidence"),
        }
        return program_id

    def current_fans(self, state):
        chara = ((state or {}).get("data") or {}).get("chara_info") or {}
        try:
            return int(chara.get("fans") or 0)
        except (TypeError, ValueError):
            return 0

    def race_grade(self, program_id, entry=None):
        entry = entry or {}
        race = dict(self.catalog.by_program_id.get(int(program_id or 0)) or {})
        race.update({k: v for k, v in entry.items() if v not in (None, "")})
        grade = str(race.get("type") or race.get("grade") or "").upper()
        if grade:
            return grade
        program = self.program.get(int(program_id or 0)) or {}
        race_instance_id = str(race.get("race_instance_id") or program.get("race_instance_id") or "")
        if race_instance_id:
            return {"1": "G1", "2": "G2", "3": "G3", "4": "OP"}.get(race_instance_id[0], "")
        return ""

    def required_fans_for_program(self, program_id, preset=None, entry=None):
        grade = self.race_grade(program_id, entry)
        if not grade:
            return 0
        race = self.catalog.by_program_id.get(int(program_id or 0)) or {}
        program = self.program.get(int(program_id or 0)) or {}
        try:
            turn = int((entry or {}).get("turn") or race.get("turn") or program.get("turn") or 0)
        except (TypeError, ValueError):
            turn = 0
        defaults = JUNIOR_FAN_REQUIREMENTS if 0 < turn <= 24 else DEFAULT_FAN_REQUIREMENTS
        required = defaults.get(grade, 0)
        overrides = (preset or {}).get("race_fan_requirements") or {}
        if isinstance(overrides, dict):
            for key in (str(program_id), grade):
                if key in overrides:
                    try:
                        required = max(0, int(overrides[key] or 0))
                    except (TypeError, ValueError):
                        pass
        return required

    def fan_eligible(self, state, preset, program_id, entry=None):
        if bool((preset or {}).get("override_insufficient_fans_forced_races")):
            return True
        required = self.required_fans_for_program(program_id, preset, entry)
        fans = self.current_fans(state)
        if required and fans < required:
            race = self.catalog.by_program_id.get(int(program_id or 0)) or {}
            name = (entry or {}).get("name") or race.get("name") or str(program_id)
            self.last_skip_reason = {
                "reason": "insufficient_fans",
                "program_id": int(program_id or 0),
                "race_name": name,
                "fans": fans,
                "required_fans": required,
                "grade": self.race_grade(program_id, entry),
            }
            return False
        return True

    def aptitude_eligible(self, state, preset, program_id, entry=None):
        """Refuse races where the trainee's distance OR surface aptitude
        is at or below the configured threshold (default: C).

        Style aptitude is intentionally excluded — a trainee with a low
        style rank for one race might run a different style for it (e.g.
        a Front Runner stamina-runs Kikuka Sho as Late Surger). The user
        opted in for this exclusion explicitly: style is race-tactical,
        but distance/surface are fixed limitations on race viability.

        Forced races (race_condition_array-mandated) bypass this gate by
        going through `forced_program`; this check only runs for the
        scheduled / wanted / optional candidate paths.
        """
        if not bool((preset or {}).get("race_aptitude_gate_enabled", True)):
            return True
        if bool((preset or {}).get("override_off_aptitude_forced_races")):
            return True
        threshold_raw = (preset or {}).get("race_aptitude_gate_threshold", "C")
        if isinstance(threshold_raw, str):
            threshold_rank = APTITUDE_RANKS.get(threshold_raw.upper(), APTITUDE_RANKS["C"])
        else:
            try:
                threshold_rank = int(threshold_raw or APTITUDE_RANKS["C"])
            except (TypeError, ValueError):
                threshold_rank = APTITUDE_RANKS["C"]

        chara = (state.get("data") or {}).get("chara_info") or {}
        race = self.catalog.by_program_id.get(int(program_id or 0)) or {}
        distance_text = (
            (entry or {}).get("distance")
            or race.get("distance")
            or ""
        )
        surface_text = (
            (entry or {}).get("terrain")
            or race.get("terrain")
            or ""
        )
        distance_key = normalize_distance_key(distance_text)
        surface_key = normalize_surface_key(surface_text)

        chara_aptitude_by_key = {
            "sprint": chara.get("proper_distance_short"),
            "mile": chara.get("proper_distance_mile"),
            "medium": chara.get("proper_distance_middle"),
            "long": chara.get("proper_distance_long"),
            "turf": chara.get("proper_ground_turf"),
            "dirt": chara.get("proper_ground_dirt"),
        }
        failed_axes = []
        if distance_key:
            rank = aptitude_rank(chara_aptitude_by_key.get(distance_key))
            if 0 < rank <= threshold_rank:
                failed_axes.append({"axis": "distance", "key": distance_key, "rank": rank})
        if surface_key:
            rank = aptitude_rank(chara_aptitude_by_key.get(surface_key))
            if 0 < rank <= threshold_rank:
                failed_axes.append({"axis": "surface", "key": surface_key, "rank": rank})
        if failed_axes:
            name = (entry or {}).get("name") or race.get("name") or str(program_id)
            self.last_skip_reason = {
                "reason": "off_aptitude",
                "program_id": int(program_id or 0),
                "race_name": name,
                "threshold_rank": threshold_rank,
                "failed_axes": failed_axes,
            }
            return False
        return True

    def stamina_rescue_entry(self, state, preset, lookahead=None):
        if not bool((preset or {}).get("auto_buy_stamina_skill_for_race", True)):
            return None, None
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        turn = int(chara.get("turn") or 0)
        lookahead = self._stamina_rescue_lookahead(preset, lookahead)
        if turn <= 0 or lookahead <= 0:
            return None, None
        for entry in self.scheduled_entries(preset):
            race_turn = int(entry.get("turn") or 0)
            turns_until_race = race_turn - turn
            if turns_until_race < 0 or turns_until_race > lookahead:
                continue
            program_id = int(entry.get("program_id") or 0)
            if not program_id:
                continue
            check = self.kikuka_front_runner_guard_check(state, preset, program_id, entry)
            if not check:
                check = self.stamina_for_program(state, preset, program_id, entry)
            if self._can_attempt_stamina_rescue(preset, check):
                return entry, check
        return None, None

    def entry_for_program(self, preset, turn, program_id):
        turn = int(turn or 0)
        program_id = int(program_id or 0)
        if not program_id:
            return None
        for entry in self.scheduled_entries(preset):
            entry_program = int(entry.get("program_id") or 0)
            entry_turn = int(entry.get("turn") or 0)
            if entry_program != program_id:
                continue
            if turn and entry_turn and entry_turn != turn:
                continue
            return dict(entry)
        return None

    def _success_hint_for_program(self, preset, program_id):
        hints = (preset or {}).get("race_specific_success_hints") or {}
        if not isinstance(hints, dict):
            return {}
        normalized = self._safe_int(program_id, 0)
        for key in (normalized, str(normalized)):
            value = hints.get(key)
            if isinstance(value, dict):
                return dict(value)
        return {}

    def _current_visible_stats(self, chara):
        chara = chara or {}
        return {
            "speed": self._safe_float(chara.get("speed"), 0.0),
            "stamina": self._safe_float(chara.get("stamina"), 0.0),
            "power": self._safe_float(chara.get("power"), 0.0),
            "guts": self._safe_float(chara.get("guts"), 0.0),
            "wit": self._safe_float(chara.get("wiz") or chara.get("wit"), 0.0),
        }

    def _current_chara_aptitudes(self, state, preset):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        run_context = dict((preset or {}).get("_run_context") or {})
        for key in ("card_id", "single_mode_chara_id", "trained_chara_id"):
            value = self._safe_int(chara.get(key), 0)
            if value > 0 and not run_context.get(key):
                run_context[key] = value
        sample_like = {"run_context": run_context}
        sample_like.update(run_context)
        return sample_chara_aptitudes(sample_like)

    def _baseline_coverage(self, baseline, current_stats):
        total_target = 0.0
        total_current = 0.0
        max_relative_deficit = 0.0
        keys_used = 0
        for key, raw_target in (baseline or {}).items():
            target = self._safe_float(raw_target, 0.0)
            if target <= 0:
                continue
            current = self._safe_float((current_stats or {}).get(key), 0.0)
            total_target += target
            total_current += min(current, target)
            if current < target:
                max_relative_deficit = max(max_relative_deficit, (target - current) / max(1.0, target))
            keys_used += 1
        coverage = (total_current / total_target) if total_target > 0 else 0.0
        return {
            "coverage": coverage,
            "max_relative_deficit": max_relative_deficit,
            "keys_used": keys_used,
        }

    def _static_race_core_coverage(self, check):
        requirements = (check or {}).get("requirements") or {}
        raw_stats = (check or {}).get("raw_stats") or (check or {}).get("stats") or {}
        distance = str((check or {}).get("distance") or "")
        core_keys = ["speed", "power"]
        if distance in {"Medium", "Long"}:
            core_keys.append("stamina")
        ratios = {}
        for key in core_keys:
            required = self._safe_float(requirements.get(key), 0.0)
            current = self._safe_float(raw_stats.get(key), 0.0)
            ratios[key] = (current / required) if required > 0 else 1.0
        if not ratios:
            return {"coverage": 1.0, "min_ratio": 1.0, "speed_ratio": 1.0}
        coverage = sum(ratios.values()) / float(len(ratios))
        return {
            "coverage": coverage,
            "min_ratio": min(ratios.values()),
            "speed_ratio": ratios.get("speed", 1.0),
        }

    def _scheduled_race_safety_gate(self, state, preset, program_id, entry):
        if not bool((preset or {}).get("scheduled_race_safety_enabled", True)):
            check = self.kikuka_front_runner_guard_check(state, preset, program_id, entry) or self.stamina_for_program(state, preset, program_id, entry)
            return True, {}, check
        check = self.kikuka_front_runner_guard_check(state, preset, program_id, entry) or self.stamina_for_program(state, preset, program_id, entry)
        if bool((preset or {}).get("scheduled_race_skip_off_aptitude", True)):
            aptitudes = self._current_chara_aptitudes(state, preset)
            running_style = self._style_for_entry(entry, preset, program_id)
            dims = off_aptitude_dimensions_for_learning(
                {
                    "terrain": (entry or {}).get("terrain"),
                    "distance": (entry or {}).get("distance"),
                    "style": running_style,
                },
                aptitudes,
            )
            if dims:
                return False, {
                    "reason": "scheduled_race_off_aptitude",
                    "program_id": self._safe_int(program_id, 0),
                    "race_name": (entry or {}).get("name") or str(program_id),
                    "off_aptitude_dimensions": dims,
                }, check
        if bool((preset or {}).get("scheduled_race_skip_if_stamina_low", True)) and bool(check.get("stamina_low")):
            return False, {
                "reason": "scheduled_race_stamina_low",
                "program_id": self._safe_int(program_id, 0),
                "race_name": (entry or {}).get("name") or str(program_id),
                "stamina_ratio": round(self._safe_float(check.get("stamina_ratio"), 0.0), 4),
                "min_stamina_ratio": round(self._safe_float(check.get("min_stamina_ratio"), 0.0), 4),
            }, check
        hint = self._success_hint_for_program(preset, program_id)
        current_stats = self._current_visible_stats(((state or {}).get("data") or {}).get("chara_info") or {})
        if isinstance(hint, dict) and hint:
            viability = (check or {}).get("empirical_success_viability") or {}
            if not bool(viability.get("viable")) and not bool(((check or {}).get("race_exploration_trial") or {}).get("allow")):
                baseline = hint.get("winning_stat_baseline") or {}
                coverage = self._baseline_coverage(baseline, current_stats)
                min_coverage = self._safe_float((preset or {}).get("scheduled_race_min_success_coverage"), 0.90)
                max_deficit = self._safe_float((preset or {}).get("scheduled_race_max_success_relative_deficit"), 0.18)
                if coverage["keys_used"] > 0 and (
                    coverage["coverage"] < min_coverage
                    or coverage["max_relative_deficit"] > max_deficit
                ):
                    return False, {
                        "reason": "scheduled_race_below_success_profile",
                        "program_id": self._safe_int(program_id, 0),
                        "race_name": (entry or {}).get("name") or str(program_id),
                        "coverage": round(coverage["coverage"], 4),
                        "max_relative_deficit": round(coverage["max_relative_deficit"], 4),
                        "min_success_coverage": round(min_coverage, 4),
                        "max_success_relative_deficit": round(max_deficit, 4),
                    }, check
        static_coverage = self._static_race_core_coverage(check)
        min_static_coverage = self._safe_float((preset or {}).get("scheduled_race_min_static_core_coverage"), 0.84)
        min_static_speed_ratio = self._safe_float((preset or {}).get("scheduled_race_min_static_speed_ratio"), 0.82)
        if (
            static_coverage["coverage"] < min_static_coverage
            or static_coverage["speed_ratio"] < min_static_speed_ratio
        ):
            return False, {
                "reason": "scheduled_race_static_stats_too_low",
                "program_id": self._safe_int(program_id, 0),
                "race_name": (entry or {}).get("name") or str(program_id),
                "static_core_coverage": round(static_coverage["coverage"], 4),
                "static_speed_ratio": round(static_coverage["speed_ratio"], 4),
                "min_static_core_coverage": round(min_static_coverage, 4),
                "min_static_speed_ratio": round(min_static_speed_ratio, 4),
            }, check
        return True, {}, check

    def _stable_roll(self, *parts):
        text = "|".join(str(part or "") for part in parts)
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
        return int(digest[:8], 16) / 0xFFFFFFFF

    def _current_run_mode(self, state, preset):
        policy = (preset or {}).get("run_mode_policy") or {}
        if not bool(policy.get("enabled", True)):
            return "neutral", {}
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        centroids = (preset or {}).get("trajectory_centroids") or {}
        if not centroids:
            return "neutral", {}
        current_stats = dict(self._current_visible_stats(chara))
        current_stats["hp"] = self._safe_float(chara.get("vital"), 0.0)
        current_stats["skill_point"] = self._safe_float(chara.get("skill_point"), 0.0)
        try:
            prediction = predict_trajectory(centroids, current_stats, self._safe_int(chara.get("turn"), 0)) or {}
        except Exception:
            prediction = {}
        label = str(prediction.get("label") or "")
        confidence = self._safe_float(prediction.get("confidence"), 0.0)
        if label == "tracking_top" and confidence >= self._safe_float(policy.get("preserve_confidence"), 0.62):
            return "preserve", prediction
        if label == "tracking_bottom" and confidence >= self._safe_float(policy.get("push_confidence"), 0.45):
            return "push", prediction
        return "neutral", prediction

    def _race_exploration_trial(self, preset, hint, chara, check, running_style, viability):
        if not bool((preset or {}).get("race_exploration_enabled", True)):
            return {"allow": False}
        attempts = self._safe_int((hint or {}).get("attempts"), 0)
        confidence = self._safe_float((hint or {}).get("confidence"), 0.0)
        if attempts <= 0:
            return {"allow": False}
        min_confidence = self._safe_float((preset or {}).get("race_exploration_min_confidence"), 0.45)
        if attempts >= 4 and confidence >= min_confidence:
            return {"allow": False}
        baseline = (hint or {}).get("winning_stat_baseline") or {}
        if not isinstance(baseline, dict) or not baseline:
            return {"allow": False}
        current_stats = self._current_visible_stats(chara)
        baseline_total = sum(self._safe_float(value, 0.0) for value in baseline.values() if self._safe_float(value, 0.0) > 0)
        current_total = sum(self._safe_float(current_stats.get(key), 0.0) for key in baseline.keys())
        if baseline_total <= 0:
            return {"allow": False}
        stat_coverage = current_total / baseline_total
        max_relative_deficit = self._safe_float((viability or {}).get("max_relative_deficit"), 1.0)
        stamina_ratio = self._safe_float((check or {}).get("stamina_ratio"), 0.0)
        if stamina_ratio < self._safe_float((preset or {}).get("race_exploration_min_static_stamina_ratio"), 0.74):
            return {"allow": False}
        if stat_coverage < self._safe_float((preset or {}).get("race_exploration_min_stat_coverage"), 0.93):
            return {"allow": False}
        if max_relative_deficit > self._safe_float((preset or {}).get("race_exploration_max_relative_deficit"), 0.18):
            return {"allow": False}
        base_rate = self._safe_float((preset or {}).get("race_exploration_rate"), 0.08)
        effective_rate = max(0.0, min(0.35, base_rate * max(0.2, 1.0 - confidence) * (1.0 if attempts < 4 else 0.6)))
        program_id = self._safe_int((check or {}).get("program_id"), 0)
        turn = self._safe_int((chara or {}).get("turn"), 0)
        roll = self._stable_roll(program_id, turn, running_style, current_stats)
        return {
            "allow": roll < effective_rate,
            "effective_rate": round(effective_rate, 4),
            "roll": round(roll, 4),
            "attempts": attempts,
            "confidence": round(confidence, 4),
            "stat_coverage": round(stat_coverage, 4),
            "max_relative_deficit": round(max_relative_deficit, 4),
            "running_style": running_style,
            "reason": "controlled_exploration_borderline_race_profile",
        }

    def style_resolution_for_entry(self, entry, preset, program_id=None):
        overrides_enabled = self._race_style_overrides_enabled(preset)
        overrides = (preset or {}).get("race_style_overrides") or {}
        if not overrides_enabled:
            overrides = {}
        if not isinstance(overrides, dict):
            overrides = {}
        global_overrides = overrides
        chara_overrides = {}
        if "global" in overrides or "by_chara" in overrides:
            global_overrides = overrides.get("global") if isinstance(overrides.get("global"), dict) else {}
            by_chara = overrides.get("by_chara") if isinstance(overrides.get("by_chara"), dict) else {}
            run_context = (preset or {}).get("_run_context") or {}
            chara_key = ""
            for raw in (
                run_context.get("single_mode_chara_id"),
                run_context.get("trainee_card_id"),
                run_context.get("card_id"),
            ):
                candidate = self._safe_int(raw, 0)
                if candidate > 0:
                    chara_key = str(candidate)
                    break
            chara_overrides = by_chara.get(chara_key) if chara_key and isinstance(by_chara.get(chara_key), dict) else {}
        override_style = ""
        entry_program_id = self._safe_int((entry or {}).get("program_id"), 0)
        lookup_keys = (
            self._safe_int(program_id, 0),
            entry_program_id,
            str(self._safe_int(program_id, 0)),
            str(entry_program_id),
        )
        for mapping in (chara_overrides, global_overrides):
            for key in lookup_keys:
                raw_override = mapping.get(key) if isinstance(mapping, dict) else None
                override_style = normalize_style(raw_override)
                if override_style:
                    break
            if override_style:
                break
        for raw, source in (
            ((entry or {}).get("style"), "scheduled_entry"),
            (override_style, "race_style_overrides"),
            ((preset or {}).get("skill_profile_style"), "skill_profile_style"),
        ):
            style = normalize_style(raw)
            if style:
                return {"style": style, "source": source}
        try:
            tactic = int((preset or {}).get("race_tactic_1") or 0)
        except (TypeError, ValueError):
            tactic = 0
        style = TACTIC_TO_STYLE.get(tactic, "")
        if style:
            return {"style": style, "source": "race_tactic_1"}
        return {"style": "", "source": ""}

    def _race_style_overrides_enabled(self, preset):
        """Treat existing override maps as learned/runtime policy.

        The UI/config flag was already used to block newly learned style
        overrides, but old override maps could still be present in saved
        presets and silently force the bot off the profile style.  Explicit
        styles on calendar entries are still respected by style_resolution_for_entry.
        """
        preset = preset or {}
        if "race_style_overrides_enabled" in preset:
            return bool(preset.get("race_style_overrides_enabled"))
        if "race_style_overrides_learned_enabled" in preset:
            return bool(preset.get("race_style_overrides_learned_enabled"))
        return True

    def _style_for_entry(self, entry, preset, program_id=None):
        return str((self.style_resolution_for_entry(entry, preset, program_id) or {}).get("style") or "")

    def _can_attempt_stamina_rescue(self, preset, check):
        if not bool((preset or {}).get("auto_buy_stamina_skill_for_race", True)):
            return False
        if check.get("distance") not in {"Medium", "Long"}:
            return False
        if bool(((check or {}).get("race_exploration_trial") or {}).get("allow")):
            return False
        return bool(check.get("stamina_low"))

    def _entry_from_race(self, program_id, race, turn):
        return {
            "race_id": (race or {}).get("id", 0),
            "race_instance_id": (race or {}).get("race_instance_id", 0),
            "program_id": int(program_id or 0),
            "turn": int((race or {}).get("turn") or turn or 0),
            "name": (race or {}).get("name", ""),
            "date": (race or {}).get("date", ""),
            "type": (race or {}).get("type", ""),
            "terrain": (race or {}).get("terrain", ""),
            "distance": (race or {}).get("distance", ""),
            "venue": (race or {}).get("venue", ""),
            "style": "",
        }

    def _optional_allowed_grades(self, preset):
        raw = (preset or {}).get("optional_race_allowed_grades", ["G2", "G3"])
        if isinstance(raw, str):
            raw = [part.strip() for part in raw.split(",")]
        result = {str(item or "").strip().upper() for item in (raw or []) if str(item or "").strip()}
        result.discard("G1")
        return result or {"G2", "G3"}

    def _rival_program_ids(self, data):
        free_data = (data or {}).get("free_data_set") or {}
        result = set()
        for row in free_data.get("rival_race_info_array") or []:
            program_id = self._safe_int(row.get("program_id"), 0)
            if program_id:
                result.add(program_id)
        return result

    def _strong_training_context(self, preset, context):
        if not context:
            return False
        score = self._safe_float(context.get("score"), 0.0)
        hard_score = self._safe_float((preset or {}).get("optional_race_hard_skip_training_score"), 0.50)
        if score >= hard_score:
            return True
        rainbow_count = self._safe_int(context.get("rainbow_count"), 0)
        stat_gain = self._safe_float(context.get("stat_gain"), 0.0)
        min_rainbows = self._safe_int((preset or {}).get("optional_race_skip_rainbow_count"), 2)
        min_stat_gain = self._safe_float((preset or {}).get("optional_race_skip_stat_gain"), 40.0)
        return min_rainbows > 0 and rainbow_count >= min_rainbows and stat_gain >= min_stat_gain

    def _optional_race_value(self, data, preset, program_id, entry, grade, is_rival):
        grade = str(grade or "").upper()
        score = OPTIONAL_RACE_SCORE_BY_GRADE.get(grade, 0.25 if is_rival else 0.0)
        free_data = (data or {}).get("free_data_set") or {}
        current_gp = self._safe_int(free_data.get("win_points"), 0)
        gain_gp = self._safe_int((preset or {}).get(f"optional_race_{grade.lower()}_gp"), OPTIONAL_RACE_GP_BY_GRADE.get(grade, 0))
        thresholds = self._optional_epithet_thresholds(preset)
        next_threshold = next((value for value in thresholds if current_gp < value), 0)
        crosses_epithet = bool(next_threshold and current_gp + gain_gp >= next_threshold)
        if is_rival:
            score = max(score, self._safe_float((preset or {}).get("optional_race_rival_base_score"), 0.70))
            score += self._safe_float((preset or {}).get("optional_race_rival_bonus"), 0.25)
        if crosses_epithet:
            score += self._safe_float((preset or {}).get("optional_race_epithet_bonus"), 0.25)
        elif next_threshold and next_threshold - current_gp <= self._safe_int((preset or {}).get("optional_race_epithet_window"), 12000):
            score += self._safe_float((preset or {}).get("optional_race_epithet_near_bonus"), 0.10)
        overlap_id = self._race_overlap_id(entry)
        affinity_overlap = self._is_affinity_overlap(overlap_id)
        if affinity_overlap:
            score += self._safe_float((preset or {}).get("optional_race_affinity_bonus"), 0.10)
        completes_set = self._completes_affinity_epithet_set(data, overlap_id)
        if completes_set:
            score += self._safe_float((preset or {}).get("optional_race_affinity_epithet_bonus"), 0.20)
        return {
            "program_id": int(program_id or 0),
            "race_name": (entry or {}).get("name") or str(program_id),
            "grade": grade,
            "score": round(score, 4),
            "rival": bool(is_rival),
            "current_gp": current_gp,
            "gain_gp": gain_gp,
            "next_epithet": next_threshold,
            "crosses_epithet": crosses_epithet,
            "affinity_overlap": affinity_overlap,
            "completes_affinity_epithet_set": completes_set,
        }

    def _optional_training_threshold(self, preset, value_info):
        threshold = self._safe_float((preset or {}).get("optional_race_max_training_score"), 0.34)
        if value_info.get("rival"):
            threshold += self._safe_float((preset or {}).get("optional_race_rival_training_bonus"), 0.05)
        if value_info.get("crosses_epithet"):
            threshold += self._safe_float((preset or {}).get("optional_race_epithet_training_bonus"), 0.04)
        hard_cap = self._safe_float((preset or {}).get("optional_race_max_training_score_cap"), 0.44)
        return min(threshold, hard_cap)

    def _optional_epithet_thresholds(self, preset):
        raw = (preset or {}).get("optional_race_epithet_thresholds", DEFAULT_EPITHET_THRESHOLDS)
        if isinstance(raw, str):
            raw = [part.strip() for part in raw.split(",")]
        result = []
        for value in raw or []:
            parsed = self._safe_int(value, 0)
            if parsed > 0:
                result.append(parsed)
        return sorted(set(result)) or list(DEFAULT_EPITHET_THRESHOLDS)

    def _safe_int(self, value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _safe_float(self, value, default=0.0):
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _race_overlap_id(self, entry):
        return self._safe_int((entry or {}).get("race_instance_id") or (entry or {}).get("race_id"), 0)

    def _is_affinity_overlap(self, overlap_id):
        if not overlap_id:
            return False
        overlap_ids = set()
        for key in ("legacy_overlap_race_ids", "modern_overlap_race_ids"):
            overlap_ids.update(self._safe_int(value, 0) for value in (self.affinity_meta.get(key) or []))
        return overlap_id in overlap_ids

    def _completes_affinity_epithet_set(self, data, candidate_overlap_id):
        if not candidate_overlap_id:
            return False
        won_ids = self._won_overlap_ids(data)
        if candidate_overlap_id in won_ids:
            return False
        for raw_set in self.affinity_meta.get("legacy_epithet_sets") or []:
            race_ids = self._epithet_set_race_ids(raw_set)
            if candidate_overlap_id not in race_ids:
                continue
            missing = race_ids - won_ids
            if missing == {candidate_overlap_id}:
                return True
        return False

    def _epithet_set_race_ids(self, raw_set):
        if isinstance(raw_set, dict):
            raw_values = raw_set.get("race_ids") or raw_set.get("races") or []
        else:
            raw_values = raw_set
        return {self._safe_int(value, 0) for value in (raw_values or []) if self._safe_int(value, 0)}

    def _won_overlap_ids(self, data):
        result = set()
        for race in (data or {}).get("race_history") or []:
            if self._safe_int(race.get("result_rank"), 0) != 1:
                continue
            overlap_id = self._safe_int(race.get("race_instance_id") or race.get("race_id"), 0)
            program_id = self._safe_int(race.get("program_id"), 0)
            if not overlap_id and program_id:
                meta = self.catalog.by_program_id.get(program_id) or {}
                overlap_id = self._safe_int(meta.get("race_instance_id") or meta.get("id"), 0)
            if overlap_id:
                result.add(overlap_id)
        return result

    def _stamina_rescue_lookahead(self, preset, lookahead=None):
        if lookahead is not None:
            value = lookahead
        else:
            value = (preset or {}).get("race_stamina_rescue_lookahead_turns", 5)
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 5

    def stamina_for_program(self, state, preset, program_id, entry=None):
        entry = entry or {}
        race = dict(self.catalog.by_program_id.get(int(program_id or 0)) or {})
        race.update({k: v for k, v in entry.items() if v not in (None, "")})
        race.setdefault("program_id", int(program_id or 0))
        chara = (state.get("data") or {}).get("chara_info") or {}
        running_style = self._style_for_entry(entry, preset, race.get("program_id"))
        check = self.stamina_estimator.estimate(
            chara,
            race,
            running_style,
            min_ratio=float((preset or {}).get("race_stamina_skill_min_ratio") or 0.96),
        )
        check["static_stamina_low"] = bool(check.get("stamina_low"))
        hint = self._success_hint_for_program(preset, race.get("program_id"))
        if hint and check.get("distance") in {"Medium", "Long"}:
            viability = empirical_success_viability(
                hint,
                self._current_visible_stats(chara),
                running_style=running_style,
                tolerance=self._safe_float((preset or {}).get("race_empirical_success_tolerance"), 0.94),
            )
            check["empirical_success_viability"] = viability
            if viability.get("viable"):
                check["stamina_low"] = False
                warnings = [warning for warning in list(check.get("warnings") or []) if warning != "stamina low"]
                warnings.append("empirical success profile satisfied")
                check["warnings"] = warnings
            elif check.get("stamina_low"):
                exploration = self._race_exploration_trial(preset, hint, chara, check, running_style, viability)
                if exploration.get("allow"):
                    check["stamina_low"] = False
                    check["race_exploration_trial"] = exploration
                    warnings = [warning for warning in list(check.get("warnings") or []) if warning != "stamina low"]
                    warnings.append("controlled exploration allowed")
                    check["warnings"] = warnings
        self.last_stamina_check = check
        return check

    def kikuka_front_runner_guard_check(self, state, preset, program_id, entry=None):
        if not bool((preset or {}).get("kikuka_front_runner_stamina_guard", True)):
            return None
        entry = entry or {}
        race = dict(self.catalog.by_program_id.get(int(program_id or 0)) or {})
        race.update({k: v for k, v in entry.items() if v not in (None, "")})
        race.setdefault("program_id", int(program_id or 0))
        name_key = "".join(ch for ch in str(race.get("name") or "").lower() if ch.isalnum())
        if name_key != "kikukasho":
            return None
        style = self._style_for_entry(entry, preset, program_id)
        if style != "front_runner":
            return None
        try:
            min_stamina = int((preset or {}).get("kikuka_front_runner_min_stamina") or 380)
        except (TypeError, ValueError):
            min_stamina = 380
        chara = (state.get("data") or {}).get("chara_info") or {}
        current_stamina = int(chara.get("stamina") or 0)
        check = self.stamina_for_program(state, preset, program_id, entry)
        check["style"] = style
        check["kikuka_front_runner_guard"] = True
        check["kikuka_front_runner_min_stamina"] = min_stamina
        check.setdefault("raw_stats", {})["stamina"] = current_stamina
        check.setdefault("stats", {})["stamina"] = current_stamina
        check.setdefault("requirements", {})["stamina"] = min_stamina
        check["stamina_ratio"] = (current_stamina / min_stamina) if min_stamina else 1.0
        check["min_stamina_ratio"] = 1.0
        check["stamina_low"] = current_stamina < min_stamina
        warnings = [warning for warning in list(check.get("warnings") or []) if warning != "stamina low"]
        if check["stamina_low"]:
            warnings.append(f"kikuka front stamina below {min_stamina}")
        check["warnings"] = warnings
        self.last_stamina_check = check
        return check

    def reject(self, turn, program_id):
        self.rejected.add((int(turn or 0), int(program_id or 0)))

    def label(self, program_id):
        info = self.program.get(int(program_id or 0)) or {}
        name = info.get("name") or ""
        race_instance_id = info.get("race_instance_id") or ""
        label = f"{program_id} {race_instance_id} {name}".strip()
        if self.last_stamina_check and int(self.last_stamina_check.get("program_id") or 0) == int(program_id or 0):
            check = self.last_stamina_check
            required = (check.get("requirements") or {}).get("stamina")
            current = (check.get("stats") or {}).get("stamina")
            if check.get("stamina_low") and required and current is not None:
                label = f"{label} [stamina low {current}/{required}]"
        return label
