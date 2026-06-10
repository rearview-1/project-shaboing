import gzip
import json
import zlib
from datetime import datetime
from pathlib import Path

from career_bot.items import ITEM_NAMES
from career_bot.report import add_event, finish_report, get_turn, merge_turn, new_report, write_report
from career_bot.runner import CareerRunner, STRATEGIES, TRAINING_LABELS, runtime_output_root


ACTION_ENDPOINTS = {
    "single_mode_free/exec_command",
    "single_mode_free/multi_item_exchange",
    "single_mode_free/multi_item_use",
    "single_mode_free/gain_skills",
    "single_mode_free/race_entry",
    "single_mode_free/race_start",
    "single_mode_free/race_end",
    "single_mode_free/race_out",
    "single_mode_free/continue",
    "single_mode_free/change_running_style",
    "single_mode_free/check_event",
}

TRAINING_COMMANDS = {101: 0, 105: 1, 102: 2, 103: 3, 106: 4, 601: 0, 602: 1, 603: 2, 604: 3, 605: 4}


def safe_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def normalize_endpoint(endpoint):
    ep = str(endpoint or "").strip().lstrip("/")
    if ep.startswith("umamusume/"):
        ep = ep[len("umamusume/"):]
    return ep


def extract_response_data(payload):
    """Return the game response data object from known wrapper shapes."""
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    if isinstance(data, dict) and (
        "chara_info" in data
        or "home_info" in data
        or "race_history" in data
        or "free_data_set" in data
        or "single_mode_finish_common" in data
    ):
        return data
    if "chara_info" in payload or "home_info" in payload:
        return payload
    for key in ("response", "payload", "body"):
        inner = payload.get(key)
        if isinstance(inner, dict):
            extracted = extract_response_data(inner)
            if extracted:
                return extracted
    return {}


def decode_horseact_body(raw, encoding=""):
    body = raw or b""
    enc = str(encoding or "").lower()
    if "gzip" in enc:
        body = gzip.decompress(body)
    elif "deflate" in enc:
        try:
            body = zlib.decompress(body)
        except zlib.error:
            body = zlib.decompress(body, -zlib.MAX_WBITS)
    if not body:
        return {}
    text = body.decode("utf-8-sig")
    return json.loads(text)


def _json_default(value):
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def _summary_items(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        items = value.get("$items")
        if isinstance(items, list):
            return items
    return []


def _read_concatenated_json(path):
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    rows = []
    decoder = json.JSONDecoder()
    text_len = len(text)
    pos = 0
    while pos < text_len:
        while pos < text_len and text[pos].isspace():
            pos += 1
        if pos >= text_len:
            break
        try:
            obj, end = decoder.raw_decode(text, pos)
            rows.append(obj)
            pos = end
        except json.JSONDecodeError:
            next_brace = text.find("{", pos + 1)
            next_bracket = text.find("[", pos + 1)
            candidates = [candidate for candidate in (next_brace, next_bracket) if candidate >= 0]
            if not candidates:
                break
            pos = min(candidates)
    return rows


def _summary_section(summary_row, *keys):
    if not isinstance(summary_row, dict):
        return {}
    for key in keys:
        value = summary_row.get(key)
        if isinstance(value, dict):
            return value
    return {}


def _summary_turn(summary_row):
    return safe_int(((summary_row or {}).get("current") or {}).get("turn"))


def _extract_summary_rank_info(summary_row):
    if not isinstance(summary_row, dict):
        return {}
    candidates = [
        summary_row.get("current"),
        summary_row.get("single_mode_finish_common"),
        (summary_row.get("data") or {}).get("single_mode_finish_common") if isinstance(summary_row.get("data"), dict) else None,
        summary_row.get("data"),
        summary_row,
    ]
    result = {}
    for source in candidates:
        if not isinstance(source, dict):
            continue
        score = safe_int(source.get("rank_score"))
        rank = safe_int(source.get("rank"))
        label = str(source.get("rank_label") or "").strip()
        if score > 0 and not result.get("rank_score"):
            result["rank_score"] = score
        if rank > 0 and not result.get("rank"):
            result["rank"] = rank
        if label and not result.get("rank_label"):
            result["rank_label"] = label
    if result.get("rank") and not result.get("rank_label"):
        try:
            from career_bot.learning import rank_label as _rank_label
            result["rank_label"] = _rank_label(result.get("rank"))
        except Exception:
            pass
    return result


def _summary_item_count_map(value):
    counts = {}
    for row in _summary_items(value):
        if not isinstance(row, dict):
            continue
        item_id = safe_int(row.get("item_id"))
        if item_id <= 0:
            continue
        num = safe_int(row.get("num") or row.get("item_num") or row.get("current_num"))
        counts[item_id] = counts.get(item_id, 0) + num
    return counts


def _summary_item_effect_ids(value):
    result = set()
    for row in _summary_items(value):
        if not isinstance(row, dict):
            continue
        item_id = safe_int(row.get("item_id"))
        if item_id > 0:
            result.add(item_id)
    return result


def _turn_has_item_attempt(turn_row, key, item_id):
    for attempt in (turn_row or {}).get(key) or []:
        if not isinstance(attempt, dict):
            continue
        selected_rows = attempt.get("selected") or attempt.get("items") or attempt.get("attempt") or attempt.get("payload") or []
        for row in selected_rows:
            if safe_int((row or {}).get("item_id")) == item_id:
                return True
    return False


def _add_inferred_item_attempt(report, kind, turn_number, item_id, amount, source, before_num=0, after_num=0):
    turn_number = safe_int(turn_number)
    item_id = safe_int(item_id)
    amount = safe_int(amount)
    if turn_number <= 0 or item_id <= 0 or amount <= 0:
        return
    turn_row = get_turn(report, turn_number)
    key = "item_buy_attempts" if kind == "buy" else "item_usage_attempts"
    if _turn_has_item_attempt(turn_row, key, item_id):
        return
    row = {
        "event": "items_buy_attempt" if kind == "buy" else "items_use_attempt",
        "turn": turn_number,
        "source": "manual_capture",
        "inference": source,
        "result": {"ok": True, "result": "ok", "source": source},
        "selected": [{
            "item_id": item_id,
            "name": ITEM_NAMES.get(item_id, ""),
            "num": amount,
            "use_num": amount if kind == "use" else 0,
            "item_num": amount,
            "current_num": before_num,
            "new_num": after_num,
        }],
    }
    add_event(report, row)


def _infer_summary_item_attempts(report, summary_rows):
    previous_row = None
    for current_row in summary_rows or []:
        if not isinstance(current_row, dict):
            continue
        if previous_row is None:
            previous_row = current_row
            continue
        prev_free = _summary_section(previous_row, "free_scenario", "items")
        curr_free = _summary_section(current_row, "free_scenario", "items")
        prev_counts = _summary_item_count_map(prev_free.get("inventory") or prev_free.get("owned"))
        curr_counts = _summary_item_count_map(curr_free.get("inventory") or curr_free.get("owned"))
        event_turn = _summary_turn(current_row) or _summary_turn(previous_row)
        for item_id in sorted(set(prev_counts) | set(curr_counts)):
            before_num = prev_counts.get(item_id, 0)
            after_num = curr_counts.get(item_id, 0)
            delta = after_num - before_num
            if delta > 0:
                _add_inferred_item_attempt(
                    report,
                    "buy",
                    event_turn,
                    item_id,
                    delta,
                    "summary_inventory_delta",
                    before_num=before_num,
                    after_num=after_num,
                )
            elif delta < 0:
                _add_inferred_item_attempt(
                    report,
                    "use",
                    event_turn,
                    item_id,
                    abs(delta),
                    "summary_inventory_delta",
                    before_num=before_num,
                    after_num=after_num,
                )
        prev_effect_ids = _summary_item_effect_ids(prev_free.get("item_effects") or prev_free.get("active_effects"))
        curr_effect_ids = _summary_item_effect_ids(curr_free.get("item_effects") or curr_free.get("active_effects"))
        for item_id in sorted(curr_effect_ids - prev_effect_ids):
            _add_inferred_item_attempt(
                report,
                "use",
                event_turn,
                item_id,
                1,
                "summary_effect_start",
                before_num=prev_counts.get(item_id, 0),
                after_num=curr_counts.get(item_id, 0),
            )
        previous_row = current_row


def _apply_summary_finish_metadata(report, summary_rows):
    if not isinstance(report, dict):
        return
    for row in reversed(summary_rows or []):
        info = _extract_summary_rank_info(row)
        if not info:
            continue
        if info.get("rank_score"):
            report["rank_score"] = info.get("rank_score")
        if info.get("rank"):
            report["rank"] = info.get("rank")
        if info.get("rank_label"):
            report["rank_label"] = info.get("rank_label")
        return


def summary_row_to_response_payload(summary_row):
    if not isinstance(summary_row, dict):
        return {}
    current = dict(summary_row.get("current") or {})
    if "wit" in current and "wiz" not in current:
        current["wiz"] = current.get("wit")
    skills = summary_row.get("skills") or {}
    supports = summary_row.get("supports") or {}
    home = summary_row.get("home") or {}
    races = summary_row.get("races") or {}
    free = _summary_section(summary_row, "free_scenario", "items")
    response_status = summary_row.get("response_status") or {}
    chara_status = summary_row.get("chara_status") or {}
    current.update({
        "skill_array": _summary_items(skills.get("bought")),
        "disable_skill_id_array": _summary_items(skills.get("disabled")),
        "skill_tips_array": _summary_items(skills.get("tips")),
        "support_card_array": _summary_items(supports.get("cards")),
        "evaluation_info_array": _summary_items(supports.get("bonds")),
        "training_level_info_array": _summary_items(supports.get("training_levels")),
        "guest_outing_info_array": _summary_items(supports.get("guest_outings")),
        "chara_effect_id_array": _summary_items(chara_status.get("chara_effects")),
        "nickname_id_array": _summary_items(chara_status.get("nicknames")),
        "route_race_id_array": _summary_items(chara_status.get("route_races")),
    })
    payload = {
        "chara_info": current,
        "home_info": {
            "command_info_array": _summary_items(home.get("commands")),
            "disable_command_id_array": _summary_items(home.get("disabled_command_ids")),
            "available_continue_num": safe_int(home.get("available_continue_num")),
            "available_free_continue_num": safe_int(home.get("available_free_continue_num")),
            "free_continue_num": safe_int(home.get("free_continue_num")),
            "free_continue_time": safe_int(home.get("free_continue_time")),
            "race_entry_restriction": safe_int(home.get("race_entry_restriction")),
        },
        "free_data_set": {
            "coin_num": safe_int((free.get("wallet") or {}).get("coin_num") or free.get("coin_num")),
            "gained_coin_num": safe_int((free.get("wallet") or {}).get("gained_coin_num") or free.get("gained_coin_num")),
            "shop_id": free.get("shop_id"),
            "sale_value": free.get("sale_value"),
            "user_item_info_array": _summary_items(free.get("inventory") or free.get("owned")),
            "pick_up_item_info_array": _summary_items(free.get("shop_items") or free.get("shop_rows")),
            "item_effect_array": _summary_items(free.get("item_effects") or free.get("active_effects")),
            "twinkle_race_npc_info_array": _summary_items(free.get("twinkle_race_npcs")),
            "twinkle_race_npc_result_array": _summary_items(free.get("twinkle_race_results")),
            "rival_race_info_array": _summary_items(free.get("rivals")),
            "command_info_array": _summary_items(free.get("commands") or free.get("free_commands")),
        },
        "race_history": _summary_items(races.get("history")),
        "race_condition_array": _summary_items(races.get("conditions")),
        "race_start_info": races.get("start_info"),
        "unchecked_event_array": _summary_items(response_status.get("unchecked_events")),
        "event_effected_factor_array": _summary_items(response_status.get("event_effected_factors")),
        "not_up_parameter_info": response_status.get("not_up_parameter_info"),
        "not_down_parameter_info": response_status.get("not_down_parameter_info"),
    }
    end_purchase = summary_row.get("end_skill_purchase")
    if isinstance(end_purchase, dict):
        payload["end_skill_purchase"] = end_purchase
    return payload


class ManualCareerRecorder:
    """Build bot-comparable career reports from passive manual-run telemetry."""

    def __init__(self, base_dir, output_dir=None, preset=None):
        self.base_dir = Path(base_dir)
        self.output_dir = Path(output_dir) if output_dir else runtime_output_root(self.base_dir) / "manual_career_logs"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.raw_ingest_dir = runtime_output_root(self.base_dir) / "horseact_ingest"
        self.raw_ingest_dir.mkdir(parents=True, exist_ok=True)
        self.preset = dict(preset or {"name": "manual-capture", "scenario_id": 4})
        self.runner = CareerRunner(self.base_dir)
        self.report = None
        self.career_key = None
        self.last_written_path = None
        self._rotated_hook_key = None

    def reset(self):
        self.report = None
        self.career_key = None
        self.last_written_path = None
        self._rotated_hook_key = None

    def _rotate_exact_hooks_for_career(self, key):
        if self._rotated_hook_key == key:
            return
        try:
            from career_bot.storage_cleanup import rotate_hachimi_exact_hooks
            rotate_hachimi_exact_hooks(self.output_dir)
            self._rotated_hook_key = key
        except Exception:
            pass

    def _new_report(self, data=None):
        scenario_id = safe_int(((data or {}).get("chara_info") or {}).get("scenario_id"), 4)
        report = new_report(self.preset, scenario_id=scenario_id or 4)
        report["source"] = "manual_capture"
        report["capture"] = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "mode": "passive",
        }
        return report

    def _key_for_data(self, data):
        chara = (data or {}).get("chara_info") or {}
        return (
            safe_int(chara.get("single_mode_chara_id")),
            str(chara.get("start_time") or ""),
            safe_int(chara.get("card_id")),
        )

    def _ensure_report(self, data):
        key = self._key_for_data(data)
        if not self.report:
            self._rotate_exact_hooks_for_career(key)
            self.report = self._new_report(data)
            self.career_key = key
            return
        old_chara_id, old_start_time, old_card = self.career_key or (0, "", 0)
        new_chara_id, new_start_time, new_card = key
        if not new_chara_id:
            return
        same_chara = old_chara_id == new_chara_id and old_card == new_card
        same_start = not old_start_time or not new_start_time or old_start_time == new_start_time
        if same_chara and same_start:
            return
        if self.report.get("turns"):
            finish_report(self.report, status="rolled_over")
            self._write_timestamped()
        self._rotate_exact_hooks_for_career(key)
        self.report = self._new_report(data)
        self.career_key = key

    def _merge_run_context_from_data(self, data):
        if not self.report or not isinstance(data, dict):
            return
        chara = (data.get("chara_info") or {})
        if not isinstance(chara, dict):
            return
        run_context = self.report.setdefault("run_context", {})
        trainee_card_id = safe_int(chara.get("card_id"))
        if trainee_card_id:
            run_context["trainee_card_id"] = trainee_card_id
        chara_id = safe_int(chara.get("single_mode_chara_id"))
        if chara_id:
            run_context["chara_id"] = chara_id
        scenario_id = safe_int(chara.get("scenario_id"))
        if scenario_id:
            run_context["scenario_id"] = scenario_id
        route_id = safe_int(chara.get("route_id"))
        if route_id:
            run_context["route_id"] = route_id
        race_running_style = safe_int(chara.get("race_running_style"))
        if race_running_style:
            run_context["race_running_style"] = race_running_style
        for key in ("succession_trained_chara_id_1", "succession_trained_chara_id_2"):
            value = safe_int(chara.get(key))
            if value:
                run_context[key] = value

        support_cards = []
        support_card_ids = []
        support_card_lb_levels = {}
        friend_card_id = 0
        friend_viewer_id = 0
        for row in chara.get("support_card_array") or []:
            if not isinstance(row, dict):
                continue
            support_card_id = safe_int(row.get("support_card_id"))
            if support_card_id <= 0:
                continue
            lb_level = safe_int(row.get("limit_break_count"))
            exp = safe_int(row.get("exp"))
            owner_viewer_id = safe_int(row.get("owner_viewer_id"))
            support_card_lb_levels[str(support_card_id)] = {
                "lb": lb_level,
                "exp": exp,
            }
            if owner_viewer_id > 0:
                if not friend_card_id:
                    friend_card_id = support_card_id
                    friend_viewer_id = owner_viewer_id
                continue
            support_cards.append({
                "id": support_card_id,
                "support_card_id": support_card_id,
                "lb_level": lb_level,
                "exp": exp,
            })
            support_card_ids.append(support_card_id)
        if support_cards:
            run_context["support_cards"] = support_cards[:5]
        if support_card_ids:
            run_context["support_card_ids"] = support_card_ids[:5]
        if support_card_lb_levels:
            run_context["support_card_lb_levels"] = support_card_lb_levels
        if friend_card_id:
            run_context["friend_card_id"] = friend_card_id
        if friend_viewer_id:
            run_context["friend_viewer_id"] = friend_viewer_id

    def _state_from_data(self, data):
        return {"data": data or {}}

    def _safe_debug_rows(self, state):
        # Every inspector wraps its result so a crash surfaces as
        # {"error": "..."} rather than as an indistinguishable empty list.
        # Critical because downstream learning logic treats an empty owned-skill
        # list as "trainee had no skills" — silently wrong if the inspector
        # actually crashed mid-snapshot.
        try:
            self.runner.skill_buyer.preview(state, self.preset)
        except Exception as exc:
            self._log_inspector_error("skill_buyer.preview", exc)
        try:
            training_snapshot = self.runner._training_snapshot(state, self.preset)
        except Exception as exc:
            training_snapshot = {"error": str(exc)}
        try:
            bot_recommendation = self._compute_bot_recommendation(state, training_snapshot=training_snapshot)
        except Exception as exc:
            bot_recommendation = {"error": str(exc)}
        try:
            active_item_effects = self.runner._active_item_effects(state)
        except Exception as exc:
            active_item_effects = [{"error": str(exc), "_inspector": "active_item_effects"}]
        try:
            owned_skills = self.runner._debug_owned_skills(state)
        except Exception as exc:
            owned_skills = [{"error": str(exc), "_inspector": "owned_skills"}]
        try:
            inventory = self.runner._debug_inventory(state)
        except Exception as exc:
            inventory = [{"error": str(exc), "_inspector": "inventory"}]
        try:
            skill_rows = self.runner._debug_skill_options(state, self.preset)
        except Exception as exc:
            skill_rows = [{"error": str(exc)}]
        try:
            shop_rows = self.runner._debug_item_buy_options(state, self.preset)
        except Exception as exc:
            shop_rows = [{"error": str(exc)}]
        return {
            "training_snapshot": training_snapshot,
            "bot_recommendation": bot_recommendation,
            "active_item_effects": active_item_effects,
            "owned_skills": owned_skills,
            "inventory": inventory,
            "skill_rows_enriched": skill_rows,
            "shop_rows_enriched": shop_rows,
        }

    def _compute_bot_recommendation(self, state, training_snapshot=None):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        scenario_id = safe_int(chara.get("scenario_id") or self.preset.get("scenario_id"), 4)
        strategy_cls = STRATEGIES.get(scenario_id)
        if not strategy_cls:
            return {}
        strategy = strategy_cls(self.runner.race_planner)
        decision = strategy.next_decision(state, self.preset)
        payload = dict(getattr(decision, "payload", {}) or {})
        result = {
            "action": getattr(decision, "action", ""),
            "reason": getattr(decision, "reason", ""),
            "understanding": dict(getattr(decision, "understanding", {}) or {}),
            "understanding_summary": str(((getattr(decision, "understanding", {}) or {}).get("summary") or "")),
            "command_type": safe_int(payload.get("command_type")),
            "command_id": safe_int(payload.get("command_id")),
            "command_group_id": safe_int(payload.get("command_group_id")),
            "current_turn": safe_int(payload.get("current_turn") or chara.get("turn")),
        }
        if result["action"] != "command" or result["command_type"] != 1:
            return result
        snapshot = training_snapshot if isinstance(training_snapshot, dict) else self.runner._training_snapshot(state, self.preset)
        trainings = (snapshot or {}).get("trainings") or []
        selected = None
        scores = sorted(
            (float(row.get("weighted_total_gain") or 0) for row in trainings if isinstance(row, dict)),
            reverse=True,
        )
        for row in trainings:
            if safe_int(row.get("command_id")) == result["command_id"]:
                selected = row
                break
        if not isinstance(selected, dict):
            return result
        score = float(selected.get("weighted_total_gain") or 0)
        second_best = scores[1] if len(scores) > 1 else 0.0
        result.update({
            "training_idx": TRAINING_COMMANDS.get(result["command_id"], -1),
            "training_name": selected.get("name") or TRAINING_LABELS.get(result["command_id"], str(result["command_id"])),
            "score": round(score, 4),
            "second_best_score": round(second_best, 4),
            "score_margin": round(score - second_best, 4),
            "predicted_stat_gain": dict(selected.get("stat_gain") or {}),
        })
        return result

    def _log_inspector_error(self, name, exc):
        """Soft logger so a crashed inspector is still visible in stderr
        without corrupting the per-turn structured log."""
        try:
            import sys as _sys
            print(f"[manual_recorder] inspector {name} failed: {exc}", file=_sys.stderr, flush=True)
        except Exception:
            pass

    def _turn_row(self, endpoint, response_payload, request_payload, trace_row):
        data = extract_response_data(response_payload)
        chara = data.get("chara_info") or {}
        turn = safe_int(chara.get("turn") or (request_payload or {}).get("current_turn"))
        state = self._state_from_data(data)
        free = data.get("free_data_set") or {}
        debug_rows = self._safe_debug_rows(state)
        row = {
            "event": "turn",
            "turn": turn,
            "source": "manual_capture",
            "endpoint": endpoint,
            "stats": self.runner._turn_stats(chara),
            "detail": self.runner._format_turn_stats(self.runner._turn_stats(chara)),
            "mant_coin": safe_int(free.get("coin_num") if free.get("coin_num") is not None else free.get("gained_coin_num")),
            "race_running_style": safe_int(chara.get("race_running_style")),
            "playing_state": safe_int(chara.get("playing_state")),
            "state": safe_int(chara.get("state")),
            "status_effect_ids": chara.get("chara_effect_id_array") or [],
            "training_level_info_array": chara.get("training_level_info_array") or [],
            "facility_levels": self._facility_levels(data),
            "support_bonds": self._support_bonds(chara),
            "evaluation_info_array": chara.get("evaluation_info_array") or [],
            "server_inventory_raw": free.get("user_item_info_array") or [],
            "server_skill_tips_raw": chara.get("skill_tips_array") or [],
            "server_owned_skill_raw": chara.get("skill_array") or [],
            "server_shop_rows_raw": free.get("pick_up_item_info_array") or [],
            "shop_id": free.get("shop_id"),
            "shop_sale_value": free.get("sale_value"),
            "race_history": self._race_history_rows(data),
            "race_conditions": data.get("race_condition_array") or [],
            "support_card_array": chara.get("support_card_array") or [],
            "request_payload": self._compact_request(request_payload),
            "trace_ts": (trace_row or {}).get("ts"),
        }
        row.update(debug_rows)
        return row

    def _facility_levels(self, data):
        chara = (data or {}).get("chara_info") or {}
        result = {}
        for row in chara.get("training_level_info_array") or []:
            command_id = safe_int(row.get("command_id"))
            if command_id:
                result[str(command_id)] = {
                    "command_id": command_id,
                    "name": TRAINING_LABELS.get(command_id, str(command_id)),
                    "level": safe_int(row.get("level")),
                    "source": "training_level_info_array",
                }
        home = (data or {}).get("home_info") or {}
        for command in home.get("command_info_array") or []:
            if safe_int(command.get("command_type")) != 1:
                continue
            command_id = safe_int(command.get("command_id"))
            if not command_id:
                continue
            result.setdefault(str(command_id), {
                "command_id": command_id,
                "name": TRAINING_LABELS.get(command_id, str(command_id)),
                "level": safe_int(command.get("level")),
                "source": "home_info.command_info_array",
            })
        return result

    def _support_bonds(self, chara):
        bonds = self.runner._partner_bonds(chara)
        return {str(key): value for key, value in sorted(bonds.items())}

    def _race_history_rows(self, data):
        rows = []
        for race in (data or {}).get("race_history") or []:
            program_id = safe_int(race.get("program_id"))
            info = self.runner._race_info_for_program(program_id)
            rows.append({
                "turn": safe_int(race.get("turn")),
                "program_id": program_id,
                "race_info": info,
                "result_rank": safe_int(race.get("result_rank")),
                "running_style": safe_int(race.get("running_style")),
                "weather": safe_int(race.get("weather")),
                "ground_condition": safe_int(race.get("ground_condition")),
                "frame_order": safe_int(race.get("frame_order")),
            })
        return rows

    def _compact_request(self, request_payload):
        if not isinstance(request_payload, dict):
            return {}
        keep = (
            "current_turn",
            "current_vital",
            "command_type",
            "command_id",
            "command_group_id",
            "select_id",
            "exchange_item_info_array",
            "use_item_info_array",
            "gain_skill_info_array",
            "program_id",
            "running_style",
            "is_short",
            "continue_type",
            "event_id",
            "choice_number",
        )
        return {key: request_payload.get(key) for key in keep if key in request_payload}

    def _action_label(self, request_payload):
        req = request_payload or {}
        command_type = safe_int(req.get("command_type"))
        command_id = safe_int(req.get("command_id"))
        if command_type == 1:
            return "train", TRAINING_LABELS.get(command_id, str(command_id))
        if command_type == 3:
            return "recreation", str(command_id or "")
        if command_type == 4:
            return "outing", str(command_id or "")
        if command_type == 7:
            return "rest", str(command_id or "")
        if command_type == 8:
            return "medic", str(command_id or "")
        return "command", str(command_id or command_type or "")

    def _add_action_event(self, endpoint, response_payload, request_payload, trace_row):
        req = request_payload or {}
        turn = safe_int(req.get("current_turn") or ((extract_response_data(response_payload).get("chara_info") or {}).get("turn")))
        if endpoint == "single_mode_free/exec_command":
            action, facility = self._action_label(req)
            selected_training = self._selected_training_fields(turn, req)
            turn_row = get_turn(self.report, turn)
            deviation = self._deviation_fields(turn_row, req, response_payload=response_payload, selected_training_fields=selected_training)
            event = {
                "event": "manual_action",
                "turn": turn,
                "source": "manual_capture",
                "selected_action": action,
                "facility": facility,
                "current_command": self._compact_request(req),
                "decision_reason": "manual player action captured from API trace",
                "deviation": deviation,
            }
            event.update(selected_training)
            add_event(self.report, event)
            target = get_turn(self.report, turn)
            target["current_command"] = event["current_command"]
            target["selected_action"] = action
            target["current_action_taken"] = action
            target["decision_reason"] = event["decision_reason"]
            target.update(selected_training)
            target["deviation"] = deviation
            return
        if endpoint == "single_mode_free/multi_item_exchange":
            add_event(self.report, {
                "event": "items_buy_attempt",
                "turn": turn,
                "source": "manual_capture",
                "payload": req.get("exchange_item_info_array") or [],
                "request_payload": self._compact_request(req),
                "result": self._api_result(response_payload),
            })
            return
        if endpoint == "single_mode_free/multi_item_use":
            add_event(self.report, {
                "event": "items_use_attempt",
                "turn": turn,
                "source": "manual_capture",
                "payload": req.get("use_item_info_array") or [],
                "items": self._item_rows_from_use(req.get("use_item_info_array") or []),
                "request_payload": self._compact_request(req),
                "result": self._api_result(response_payload),
            })
            return
        if endpoint == "single_mode_free/gain_skills":
            add_event(self.report, {
                "event": "skills_attempt",
                "turn": turn,
                "source": "manual_capture",
                "payload": req.get("gain_skill_info_array") or [],
                "request_payload": self._compact_request(req),
                "result": self._api_result(response_payload),
            })
            return
        if endpoint == "single_mode_free/continue":
            add_event(self.report, {
                "event": "race_continue_attempt",
                "turn": turn,
                "source": "manual_capture",
                "continue_type": safe_int(req.get("continue_type")),
                "request_payload": self._compact_request(req),
                "result": self._api_result(response_payload),
            })
            return
        if endpoint in {"single_mode_free/race_entry", "single_mode_free/race_start", "single_mode_free/race_end", "single_mode_free/race_out", "single_mode_free/change_running_style"}:
            add_event(self.report, {
                "event": endpoint.rsplit("/", 1)[-1],
                "turn": turn,
                "source": "manual_capture",
                "request_payload": self._compact_request(req),
                "result": self._api_result(response_payload),
            })

    def _selected_training_fields(self, turn, request_payload):
        req = request_payload or {}
        if safe_int(req.get("command_type")) != 1:
            return {}
        command_id = safe_int(req.get("command_id"))
        turn_row = get_turn(self.report, turn)
        selected = None
        for row in ((turn_row.get("training_snapshot") or {}).get("trainings") or []):
            if safe_int(row.get("command_id")) == command_id:
                selected = row
                break
        if not selected:
            return {
                "selected_training": {"command_id": command_id, "name": TRAINING_LABELS.get(command_id, str(command_id))},
                "selected_friendship_training": None,
                "selected_training_inference": "request_only",
            }
        rainbow_count = safe_int(selected.get("rainbow_count"))
        return {
            "selected_training": selected,
            "selected_friendship_training": rainbow_count > 0,
            "selected_training_rainbow_count": rainbow_count,
            "selected_training_partner_count": safe_int(selected.get("partner_count")),
            "selected_training_failure_rate": safe_int(selected.get("failure_rate")),
            "selected_training_stat_gain": selected.get("stat_gain") or {},
            "selected_training_inference": "request_and_pre_turn_snapshot",
        }

    def _actual_stat_gain(self, turn_row, response_payload):
        before = (turn_row or {}).get("stats") or {}
        after = self.runner._turn_stats((extract_response_data(response_payload).get("chara_info") or {}))
        gains = {}
        for key in ("speed", "stamina", "power", "guts", "wit", "skill_point", "hp"):
            delta = safe_int(after.get(key)) - safe_int(before.get(key))
            if delta:
                gains[key] = delta
        return gains

    def _deviation_fields(self, turn_row, request_payload, response_payload=None, selected_training_fields=None):
        req = request_payload or {}
        bot = (turn_row or {}).get("bot_recommendation") or {}
        human_command_type = safe_int(req.get("command_type"))
        human_command_id = safe_int(req.get("command_id"))
        bot_command_type = safe_int(bot.get("command_type"))
        bot_command_id = safe_int(bot.get("command_id"))
        selected = {}
        if isinstance(selected_training_fields, dict):
            selected = selected_training_fields.get("selected_training") or {}
        human_score = 0.0
        if isinstance(selected, dict):
            human_score = float(selected.get("weighted_total_gain") or 0)
        if not human_score and human_command_type == 1:
            for row in ((turn_row or {}).get("training_snapshot") or {}).get("trainings") or []:
                if safe_int((row or {}).get("command_id")) == human_command_id:
                    human_score = float((row or {}).get("weighted_total_gain") or 0)
                    selected = row
                    break
        deviation = {
            "agreed": human_command_type == bot_command_type and human_command_id == bot_command_id,
            "bot_action": bot.get("action"),
            "bot_command_type": bot_command_type,
            "bot_command_id": bot_command_id,
            "human_command_type": human_command_type,
            "human_command_id": human_command_id,
            "bot_training_idx": TRAINING_COMMANDS.get(bot_command_id, -1),
            "human_training_idx": TRAINING_COMMANDS.get(human_command_id, -1),
            "bot_score": bot.get("score"),
            "bot_second_best_score": bot.get("second_best_score"),
            "bot_score_margin": bot.get("score_margin"),
            "bot_predicted_stat_gain": bot.get("predicted_stat_gain") or {},
            "human_choice_bot_score": round(human_score, 4) if human_score else None,
            "human_predicted_stat_gain": dict(selected.get("stat_gain") or {}) if isinstance(selected, dict) else {},
            "bot_parity_at_capture": None,
        }
        if response_payload:
            deviation["actual_stat_gain"] = self._actual_stat_gain(turn_row, response_payload)
        return deviation

    def _infer_selected_training_from_transition(self, new_data):
        if not self.report:
            return
        chara = (new_data or {}).get("chara_info") or {}
        new_turn = safe_int(chara.get("turn"))
        if new_turn <= 1:
            return
        previous_turns = [
            row for row in self.report.get("turns") or []
            if safe_int(row.get("turn")) < new_turn
        ]
        if not previous_turns:
            return
        prev = max(previous_turns, key=lambda row: safe_int(row.get("turn")))
        prev_turn = safe_int(prev.get("turn"))
        if new_turn - prev_turn != 1 or prev.get("selected_action"):
            return
        trainings = ((prev.get("training_snapshot") or {}).get("trainings") or [])
        if not trainings:
            return
        prev_stats = prev.get("stats") or {}
        new_stats = self.runner._turn_stats(chara)
        deltas = {
            key: safe_int(new_stats.get(key)) - safe_int(prev_stats.get(key))
            for key in ("speed", "stamina", "power", "guts", "wit", "skill_point")
        }
        best = None
        best_score = 0
        for training in trainings:
            gains = training.get("stat_gain") or {}
            score = 0
            for key, gain in gains.items():
                if key == "hp":
                    continue
                gain = safe_int(gain)
                if gain <= 0:
                    continue
                delta = max(0, safe_int(deltas.get(key)))
                score += min(delta, gain)
            if score > best_score:
                best = training
                best_score = score
        if not best or best_score <= 0:
            return
        selected = {
            "command_type": 1,
            "command_id": safe_int(best.get("command_id")),
            "command_group_id": safe_int(best.get("command_group_id")),
            "current_turn": prev_turn,
        }
        fields = self._selected_training_fields(prev_turn, selected)
        fields["selected_training_inference"] = "state_delta"
        fields["selected_training_inference_score"] = best_score
        prev["current_command"] = self._compact_request(selected)
        prev["selected_action"] = "train"
        prev["current_action_taken"] = "train"
        prev["decision_reason"] = "manual training inferred from next-turn stat delta"
        prev.update(fields)
        prev["deviation"] = self._deviation_fields(prev, selected, response_payload={"data": new_data}, selected_training_fields=fields)
        add_event(self.report, {
            "event": "manual_action_inferred",
            "turn": prev_turn,
            "source": "manual_capture",
            "selected_action": "train",
            "facility": best.get("name"),
            "decision_reason": prev["decision_reason"],
            "deviation": prev.get("deviation"),
            **fields,
        })

    def _item_rows_from_use(self, rows):
        result = []
        for row in rows or []:
            item_id = safe_int(row.get("item_id"))
            result.append({
                "item_id": item_id,
                "name": ITEM_NAMES.get(item_id, ""),
                "num": safe_int(row.get("num") or row.get("item_num")),
            })
        return result

    def _api_result(self, response_payload):
        payload = response_payload or {}
        headers = payload.get("data_headers") if isinstance(payload, dict) else {}
        result_code = safe_int((headers or {}).get("result_code") or payload.get("response_code") if isinstance(payload, dict) else 0)
        return {
            "ok": result_code == 1,
            "result_code": result_code,
            "response_code": safe_int(payload.get("response_code")) if isinstance(payload, dict) else 0,
        }

    def _add_race_result_event(self, endpoint, response_payload, request_payload):
        if endpoint not in {"single_mode_free/race_end", "single_mode_free/race_out", "single_mode_free/continue", "single_mode_free/load"}:
            return
        data = extract_response_data(response_payload)
        current_turn = safe_int((request_payload or {}).get("current_turn") or ((data.get("chara_info") or {}).get("turn")))
        program_id = safe_int((request_payload or {}).get("program_id") or ((data.get("race_start_info") or {}).get("program_id")))
        result = self.runner._race_result_from_response(response_payload, current_turn, program_id)
        if not result:
            return
        info = self.runner._race_info_for_program(result.get("program_id") or program_id)
        add_event(self.report, {
            "event": "race_result",
            "turn": safe_int(result.get("turn") or current_turn),
            "source": "manual_capture",
            "program_id": safe_int(result.get("program_id") or program_id),
            "race_info": info,
            "finish_rank": safe_int(result.get("finish_rank")),
            "result_rank": safe_int(result.get("result_rank")),
            "won": bool(result.get("won")),
            "status": result.get("status"),
            "label": self.runner._race_result_label(result),
            "result_source": result.get("source"),
        })

    def process_response(self, endpoint, response_payload, request_payload=None, trace_row=None, write_latest=True):
        endpoint = normalize_endpoint(endpoint)
        data = extract_response_data(response_payload)
        if data:
            self._ensure_report(data)
            self._merge_run_context_from_data(data)
        elif not self.report:
            self.report = self._new_report()
        self.runner.report = self.report

        if data and data.get("chara_info"):
            if endpoint.startswith("horseact/"):
                self._infer_selected_training_from_transition(data)
            row = self._turn_row(endpoint, response_payload, request_payload, trace_row)
            merge_turn(self.report, row)
        if endpoint in ACTION_ENDPOINTS:
            self._add_action_event(endpoint, response_payload, request_payload, trace_row)
        self._add_race_result_event(endpoint, response_payload, request_payload)

        if data and data.get("single_mode_finish_common"):
            finish_report(self.report, status="finished")

        if write_latest:
            self.write_latest()
        return self.report

    def process_horseact_payload(self, hook_name, payload, write_latest=True):
        endpoint = self._endpoint_from_horseact_payload(hook_name, payload)
        return self.process_response(endpoint, payload, request_payload=None, trace_row={"source": hook_name}, write_latest=write_latest)

    def _endpoint_from_horseact_payload(self, hook_name, payload):
        if isinstance(payload, dict):
            explicit = payload.get("endpoint") or payload.get("name")
            if explicit:
                return normalize_endpoint(explicit)
        name = str(hook_name or "")
        if "/" in name:
            return normalize_endpoint(name)
        return "horseact/" + name

    def append_raw_horseact(self, endpoint_name, payload):
        stamp = datetime.now().strftime("%Y%m%d")
        path = self.raw_ingest_dir / f"horseact_ingest_{stamp}.jsonl"
        row = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "endpoint": endpoint_name,
            "payload": payload,
        }
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")
        return path

    def write_latest(self):
        if not self.report:
            return None
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / "latest_manual_career_log.json"
        # Atomic write — the bot's learning loader consumes this file via
        # `load_latest_manual_summary`. A partial write (crash mid-dump)
        # leaves invalid JSON that propagates through the entire learning
        # pipeline. Windows-specific resilience: os.replace can raise
        # PermissionError if the destination is open in another process
        # (UI viewer, AV scanner, hakuraku tool). Retry briefly before
        # falling back to a direct write so transient locks don't lose
        # the atomic guarantee on the common path.
        import os
        import time
        serialized = json.dumps(self.report, ensure_ascii=False, indent=2, default=_json_default)
        # Per-process .tmp path so two writers can't clobber each other.
        tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
        tmp.write_text(serialized, encoding="utf-8")
        last_exc = None
        for attempt in range(3):
            try:
                os.replace(tmp, path)
                last_exc = None
                break
            except PermissionError as exc:
                last_exc = exc
                time.sleep(0.15 * (attempt + 1))
        if last_exc is not None:
            path.write_text(serialized, encoding="utf-8")
            try:
                tmp.unlink()
            except Exception:
                pass
        self.last_written_path = path
        return path

    def _write_timestamped(self):
        if not self.report:
            return None
        path = write_report(self.report, self.output_dir)
        self.last_written_path = path
        return path

    def finalize(self, status=None, write_timestamped=True):
        if not self.report:
            self.report = self._new_report()
        finish_report(self.report, status=status)
        return self._write_timestamped() if write_timestamped else self.write_latest()


def build_report_from_trace(trace_path, base_dir, output_dir=None, preset=None):
    recorder = ManualCareerRecorder(base_dir, output_dir=output_dir, preset=preset)
    pending = {}
    trace_path = Path(trace_path)
    with open(trace_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            endpoint = normalize_endpoint(row.get("endpoint"))
            direction = str(row.get("direction") or "").upper()
            req_id = row.get("req_id") or ""
            if direction == "REQ":
                payload = ((row.get("data") or {}).get("payload") or {})
                if req_id:
                    pending[req_id] = payload
                continue
            if direction != "RES":
                continue
            req_payload = pending.get(req_id, {})
            recorder.process_response(endpoint, row.get("data") or {}, req_payload, trace_row=row, write_latest=False)
    recorder.finalize(status="finished", write_timestamped=False)
    recorder.write_latest()
    return recorder.report


def build_report_from_hachimi_summaries(summary_events_path, base_dir, output_dir=None, preset=None, persist=True):
    recorder = ManualCareerRecorder(base_dir, output_dir=output_dir, preset=preset)
    summary_events_path = Path(summary_events_path)
    last_turn = 0
    summary_rows = _read_concatenated_json(summary_events_path)
    for row in summary_rows:
        if not isinstance(row, dict):
            continue
        payload = summary_row_to_response_payload(row)
        if not payload:
            continue
        last_turn = max(last_turn, safe_int((payload.get("chara_info") or {}).get("turn")))
        label = str(row.get("label") or "summary")
        recorder.process_response(
            "horseact/" + label,
            payload,
            request_payload=None,
            trace_row={"source": "hachimi_summary", "ts": row.get("ts_ms"), "label": label},
            write_latest=False,
        )
    if recorder.report:
        try:
            from career_bot.learning import infer_manual_actions_from_summaries
            for action in infer_manual_actions_from_summaries(summary_rows):
                turn_number = safe_int(action.get("turn"))
                if turn_number <= 0:
                    continue
                turn_row = get_turn(recorder.report, turn_number)
                command_id = safe_int(action.get("command_id"))
                selected = None
                trainings = ((action.get("training_snapshot") or {}).get("trainings") or [])
                for row in trainings:
                    if safe_int((row or {}).get("command_id")) == command_id:
                        selected = row
                        break
                turn_row["selected_action"] = "train"
                turn_row["current_action_taken"] = "train"
                turn_row["decision_reason"] = "manual training inferred from hachimi summary deltas"
                turn_row["current_command"] = {
                    "command_type": 1,
                    "command_id": command_id,
                    "command_group_id": safe_int(action.get("command_group_id")),
                    "current_turn": turn_number,
                }
                turn_row["training_snapshot"] = action.get("training_snapshot") or turn_row.get("training_snapshot") or {}
                if isinstance(selected, dict):
                    turn_row["selected_training"] = selected
                    turn_row["selected_friendship_training"] = safe_int(selected.get("rainbow_count")) > 0
                    turn_row["selected_training_rainbow_count"] = safe_int(selected.get("rainbow_count"))
                    turn_row["selected_training_partner_count"] = safe_int(selected.get("partner_count"))
                    turn_row["selected_training_failure_rate"] = safe_int(selected.get("failure_rate"))
                    turn_row["selected_training_stat_gain"] = dict(selected.get("stat_gain") or {})
                    turn_row["selected_training_inference"] = "hachimi_summary_delta"
                    turn_row["future_metrics"] = action.get("future_metrics") or {}
        except Exception:
            pass
        _infer_summary_item_attempts(recorder.report, summary_rows)
        _apply_summary_finish_metadata(recorder.report, summary_rows)
    if not recorder.report:
        recorder.report = recorder._new_report()
    finish_report(recorder.report, status="finished" if last_turn >= 78 else "partial")
    if persist:
        recorder.write_latest()
    return recorder.report
