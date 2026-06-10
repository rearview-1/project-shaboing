import json
import tempfile
from datetime import datetime
from pathlib import Path

from career_bot.learning import as_int, normalize_bot_like_log
from career_bot.manual_recorder import build_report_from_hachimi_summaries
from career_bot.runner import TRAINING_LABELS


ACTION_ALIASES = {
    "race_progress": "race",
    "race_result": "race",
    "race_entry": "race",
    "race_start": "race",
    "race_end": "race",
    "race_out": "race",
}

TRAINING_NAME_BY_COMMAND_ID = {
    101: "Speed",
    601: "Speed",
    105: "Stamina",
    602: "Stamina",
    102: "Power",
    603: "Power",
    103: "Guts",
    604: "Guts",
    106: "Wit",
    605: "Wit",
}


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _summary_items(value):
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        items = value.get("$items")
        if isinstance(items, list):
            return items
    return []


def _load_summary_row(path):
    path = Path(path)
    if not path.exists():
        return {}
    data = _read_json(path)
    if isinstance(data, dict):
        return data
    try:
        decoder = json.JSONDecoder()
        text = path.read_text(encoding="utf-8", errors="replace")
        row, _ = decoder.raw_decode(text.lstrip())
        if isinstance(row, dict):
            return row
    except Exception:
        return {}
    return {}


def _support_context_from_rows(rows):
    player_support_ids = []
    player_support_cards = []
    support_card_lb_levels = {}
    friend_card_id = 0
    friend_viewer_id = 0
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        support_card_id = as_int(row.get("support_card_id"))
        if support_card_id <= 0:
            continue
        lb_level = as_int(row.get("limit_break_count"))
        exp = as_int(row.get("exp"))
        owner_viewer_id = as_int(row.get("owner_viewer_id"))
        support_card_lb_levels[str(support_card_id)] = {"lb": lb_level, "exp": exp}
        if owner_viewer_id > 0:
            if not friend_card_id:
                friend_card_id = support_card_id
                friend_viewer_id = owner_viewer_id
            continue
        player_support_ids.append(support_card_id)
        player_support_cards.append({
            "id": support_card_id,
            "support_card_id": support_card_id,
            "lb_level": lb_level,
            "exp": exp,
        })
    return {
        "support_card_ids": player_support_ids[:5],
        "support_cards": player_support_cards[:5],
        "support_card_lb_levels": support_card_lb_levels,
        "friend_card_id": friend_card_id,
        "friend_viewer_id": friend_viewer_id,
    }


def _race_quality_from_summary_row(summary_row):
    summary_row = summary_row if isinstance(summary_row, dict) else {}
    history = _summary_items(((summary_row.get("races") or {}).get("history")))
    if not history:
        return {}
    race_total = 0
    race_wins = 0
    race_losses = 0
    for row in history:
        if not isinstance(row, dict):
            continue
        rank = as_int(row.get("result_rank"))
        if rank <= 0:
            continue
        race_total += 1
        if rank == 1:
            race_wins += 1
        else:
            race_losses += 1
    if race_total <= 0:
        return {}
    return {
        "race_total": race_total,
        "race_wins": race_wins,
        "race_losses": race_losses,
    }


def run_context_from_hachimi_summary(summary_row):
    summary_row = summary_row if isinstance(summary_row, dict) else {}
    current = summary_row.get("current") or {}
    supports = (summary_row.get("supports") or {}).get("cards")
    support_context = _support_context_from_rows(_summary_items(supports))
    run_context = {
        "trainee_card_id": as_int(current.get("card_id")),
        "chara_id": as_int(current.get("single_mode_chara_id")),
        "scenario_id": as_int(current.get("scenario_id")),
        "route_id": as_int(current.get("route_id")),
        "race_running_style": as_int(current.get("race_running_style")),
    }
    for key in ("succession_trained_chara_id_1", "succession_trained_chara_id_2"):
        value = as_int(current.get(key))
        if value:
            run_context[key] = value
    for key, value in support_context.items():
        if value:
            run_context[key] = value
    return {key: value for key, value in run_context.items() if value or isinstance(value, list) or isinstance(value, dict)}


def latest_hachimi_career_summary_events_path(latest_summary_path):
    latest_summary_path = Path(latest_summary_path)
    summary_row = _load_summary_row(latest_summary_path)
    career_key = str(summary_row.get("career_key") or "").strip()
    if not career_key:
        return None
    roots = []
    parent = latest_summary_path.parent
    if parent.name == "_latest":
        roots.append(parent.parent)
    roots.append(parent)
    seen = set()
    for root in roots:
        root = Path(root)
        if not root.exists():
            continue
        resolved = str(root.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        for candidate in root.rglob("summary_events.jsonl"):
            if candidate.parent.name == career_key:
                return candidate
    return None


def _merge_context(target, source):
    target = target if isinstance(target, dict) else {}
    source = source if isinstance(source, dict) else {}
    for key, value in source.items():
        if value or isinstance(value, (list, dict)):
            target[key] = value
    return target


def load_manual_reference(base_dir, manual_log_path=None, manual_summary_path=None):
    manual_log_path = Path(manual_log_path) if manual_log_path else None
    manual_summary_path = Path(manual_summary_path) if manual_summary_path else None
    source_summary_row = _load_summary_row(manual_summary_path) if manual_summary_path else {}
    source_context = run_context_from_hachimi_summary(source_summary_row) if source_summary_row else {}
    source_event_path = latest_hachimi_career_summary_events_path(manual_summary_path) if manual_summary_path else None

    report = None
    report_path = None
    report_source = "manual_log"
    if source_event_path and source_event_path.exists():
        with tempfile.TemporaryDirectory() as tmp:
            report = build_report_from_hachimi_summaries(source_event_path, base_dir, output_dir=tmp)
        report_path = source_event_path
        report_source = "summary_events"
    elif manual_log_path and manual_log_path.exists():
        report = _read_json(manual_log_path)
        report_path = manual_log_path
    if not isinstance(report, dict):
        return None

    run_context = _merge_context(report.get("run_context") or {}, source_context)
    report["run_context"] = run_context
    sample = normalize_bot_like_log(report_path or manual_log_path or "manual", report, "manual_compare")
    if not isinstance(sample, dict):
        return None
    sample["run_context"] = _merge_context(sample.get("run_context") or {}, run_context)
    if run_context.get("trainee_card_id"):
        sample["trainee_card_id"] = as_int(run_context.get("trainee_card_id"))
    if run_context.get("chara_id"):
        sample["chara_id"] = as_int(run_context.get("chara_id"))
    return {
        "report": report,
        "sample": sample,
        "source": report_source,
        "path": str(report_path or manual_log_path or ""),
        "summary_path": str(manual_summary_path or ""),
        "summary_row": source_summary_row,
    }


def _normalize_action_label(value):
    value = str(value or "").strip().lower()
    if not value:
        return ""
    return ACTION_ALIASES.get(value, value)


def _training_name_from_turn(turn_row):
    selected_training = (turn_row or {}).get("selected_training") or {}
    name = str(selected_training.get("name") or "").strip()
    if name:
        return name
    current_command = (turn_row or {}).get("current_command") or {}
    command_id = as_int(current_command.get("command_id"))
    if command_id:
        return TRAINING_NAME_BY_COMMAND_ID.get(command_id) or TRAINING_LABELS.get(command_id, str(command_id))
    return ""


def _turn_action_signature(turn_row):
    action = _normalize_action_label((turn_row or {}).get("selected_action") or (turn_row or {}).get("current_action_taken"))
    current_command = (turn_row or {}).get("current_command") or {}
    command_id = as_int(current_command.get("command_id"))
    if not command_id:
        command_id = as_int(((turn_row or {}).get("selected_training") or {}).get("command_id"))
    return action, command_id


def _selected_action_turns(report):
    turns = {}
    for row in (report.get("turns") or []):
        if not isinstance(row, dict):
            continue
        turn_number = as_int(row.get("turn"))
        if turn_number <= 0:
            continue
        action = _normalize_action_label(row.get("selected_action") or row.get("current_action_taken"))
        if not action:
            continue
        turns[turn_number] = row
    return turns


def summarize_action_counts(report, sample=None):
    sample = sample if isinstance(sample, dict) else {}
    counts = {
        "train": 0,
        "race": 0,
        "rest": 0,
        "recreation": 0,
        "outing": 0,
        "medic": 0,
        "other": 0,
    }
    training_counts = {"speed": 0, "stamina": 0, "power": 0, "guts": 0, "wit": 0}
    selected_action_turns = 0
    for row in (report.get("turns") or []):
        if not isinstance(row, dict):
            continue
        action = _normalize_action_label(row.get("selected_action") or row.get("current_action_taken"))
        if not action:
            continue
        selected_action_turns += 1
        if action == "train":
            counts["train"] += 1
            training_name = _training_name_from_turn(row).strip().lower()
            if training_name in training_counts:
                training_counts[training_name] += 1
        elif action in counts:
            counts[action] += 1
        else:
            counts["other"] += 1
    race_total = as_int(((sample.get("race_quality") or {}).get("race_total")), 0)
    if race_total:
        counts["race"] = race_total
    return {
        "action_counts": counts,
        "training_counts": training_counts,
        "selected_action_turns": selected_action_turns,
    }


def _manual_bot_match_score(manual_sample, bot_sample):
    manual_context = manual_sample.get("run_context") or {}
    bot_context = bot_sample.get("run_context") or {}
    score = 0
    reasons = []

    manual_trainee = as_int(manual_context.get("trainee_card_id") or manual_context.get("card_id"))
    bot_trainee = as_int(bot_context.get("trainee_card_id") or bot_sample.get("trainee_card_id"))
    if manual_trainee and not bot_trainee:
        return 0, []
    if manual_trainee and bot_trainee and bot_trainee != manual_trainee:
        return 0, []
    if manual_trainee and bot_trainee == manual_trainee:
        score += 100
        reasons.append("same trainee")

    manual_support_ids = tuple(as_int(value) for value in (manual_context.get("support_card_ids") or []) if as_int(value))
    bot_support_ids = tuple(as_int(value) for value in (bot_context.get("support_card_ids") or []) if as_int(value))
    if manual_support_ids and bot_support_ids:
        overlap = len(set(manual_support_ids).intersection(bot_support_ids))
        if overlap:
            score += overlap * 8
            reasons.append(f"{overlap}/5 player support overlap")
        if manual_support_ids == bot_support_ids:
            score += 40
            reasons.append("same player support deck")
        elif set(manual_support_ids) == set(bot_support_ids):
            score += 28
            reasons.append("same player support deck (order-insensitive)")

    manual_friend = as_int(manual_context.get("friend_card_id"))
    bot_friend = as_int(bot_context.get("friend_card_id"))
    if manual_friend and bot_friend == manual_friend:
        score += 12
        reasons.append("same friend support")

    if bot_sample.get("status") == "finished" and as_int(bot_sample.get("final_turn")) >= 78:
        score += 5
    if bot_sample.get("full_career_capture"):
        score += 3

    return score, reasons


def load_bot_candidates(runtime_root, recent=160):
    runtime_root = Path(runtime_root)
    bot_dir = runtime_root / "bot_logs"
    rows = []
    if not bot_dir.exists():
        return rows
    files = sorted(bot_dir.glob("career_log_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if recent:
        files = files[:recent]
    for path in files:
        report = _read_json(path)
        if not isinstance(report, dict):
            continue
        sample = normalize_bot_like_log(path, report, "bot_compare")
        if not isinstance(sample, dict):
            continue
        rows.append({
            "path": str(path),
            "report": report,
            "sample": sample,
            "mtime": path.stat().st_mtime,
        })
    return rows


def select_best_bot_match(manual_sample, bot_candidates):
    best = None
    for row in bot_candidates or []:
        sample = row.get("sample") or {}
        if sample.get("status") != "finished" or as_int(sample.get("final_turn")) < 78:
            continue
        match_score, reasons = _manual_bot_match_score(manual_sample, sample)
        if match_score <= 0:
            continue
        candidate = dict(row)
        candidate["match_score"] = match_score
        candidate["match_reasons"] = reasons
        if best is None:
            best = candidate
            continue
        if match_score > best.get("match_score", 0):
            best = candidate
            continue
        if match_score == best.get("match_score", 0) and row.get("mtime", 0) > best.get("mtime", 0):
            best = candidate
    return best


def build_turn_decision_diffs(manual_report, bot_report, limit=24):
    manual_turns = _selected_action_turns(manual_report)
    bot_turns = _selected_action_turns(bot_report)
    rows = []
    overlap = sorted(set(manual_turns).intersection(bot_turns))
    for turn_number in overlap:
        manual_turn = manual_turns[turn_number]
        bot_turn = bot_turns[turn_number]
        manual_sig = _turn_action_signature(manual_turn)
        bot_sig = _turn_action_signature(bot_turn)
        if manual_sig == bot_sig:
            continue
        manual_stats = {
            key: as_int(((manual_turn.get("stats") or {}).get(key)))
            for key in ("speed", "stamina", "power", "guts", "wit", "skill_point")
            if key in (manual_turn.get("stats") or {})
        }
        bot_stats = {
            key: as_int(((bot_turn.get("stats") or {}).get(key)))
            for key in ("speed", "stamina", "power", "guts", "wit", "skill_point")
            if key in (bot_turn.get("stats") or {})
        }
        bot_reason = (
            bot_turn.get("decision_understanding_summary")
            or ((bot_turn.get("decision_understanding") or {}).get("summary"))
            or bot_turn.get("decision_reason")
            or ""
        )
        rows.append({
            "turn": turn_number,
            "manual_action": manual_sig[0],
            "manual_command_id": manual_sig[1],
            "manual_training": _training_name_from_turn(manual_turn),
            "manual_stats": manual_stats,
            "bot_action": bot_sig[0],
            "bot_command_id": bot_sig[1],
            "bot_training": _training_name_from_turn(bot_turn),
            "bot_stats": bot_stats,
            "bot_reason": str(bot_reason or ""),
        })
        if len(rows) >= max(1, as_int(limit, 24)):
            break
    return {
        "turn_overlap_count": len(overlap),
        "different_turn_count": len(rows),
        "decision_diffs": rows,
    }


def _stat_delta(manual_stats, bot_stats):
    delta = {}
    for key in ("speed", "stamina", "power", "guts", "wit", "skill_point"):
        delta[key] = as_int((manual_stats or {}).get(key)) - as_int((bot_stats or {}).get(key))
    return delta


def _delta_dict(left, right):
    keys = set((left or {}).keys()).union(right or {})
    return {key: as_int((left or {}).get(key)) - as_int((right or {}).get(key)) for key in sorted(keys)}


def _comparison_summary(manual_block, bot_block, comparison):
    lines = []
    stat_delta = comparison.get("stat_delta_manual_minus_bot") or {}
    ordered_stats = sorted(
        ((key, value) for key, value in stat_delta.items() if key != "skill_point"),
        key=lambda item: abs(item[1]),
        reverse=True,
    )
    positive = [f"{key}+{value}" for key, value in ordered_stats if value > 0][:3]
    negative = [f"{key}{value}" for key, value in ordered_stats if value < 0][:3]
    if positive:
        lines.append("Manual ended stronger in " + ", ".join(positive) + ".")
    if negative:
        lines.append("Bot ended stronger in " + ", ".join(negative) + ".")
    action_delta = comparison.get("action_delta_manual_minus_bot") or {}
    training_delta = comparison.get("training_delta_manual_minus_bot") or {}
    support_notes = []
    if as_int(training_delta.get("speed")):
        support_notes.append(f"Speed trains {as_int(training_delta.get('speed')):+d}")
    if as_int(training_delta.get("stamina")):
        support_notes.append(f"Stamina trains {as_int(training_delta.get('stamina')):+d}")
    if as_int(training_delta.get("wit")):
        support_notes.append(f"Wit trains {as_int(training_delta.get('wit')):+d}")
    if as_int(action_delta.get("rest")):
        support_notes.append(f"Rest {as_int(action_delta.get('rest')):+d}")
    if as_int(action_delta.get("recreation")):
        support_notes.append(f"Recreation {as_int(action_delta.get('recreation')):+d}")
    if support_notes:
        lines.append("Manual minus bot action mix: " + ", ".join(support_notes) + ".")
    manual_g1_losses = as_int(((manual_block.get("race_quality") or {}).get("g1_losses")))
    bot_g1_losses = as_int(((bot_block.get("race_quality") or {}).get("g1_losses")))
    if manual_g1_losses != bot_g1_losses:
        lines.append(f"G1 losses manual {manual_g1_losses} vs bot {bot_g1_losses}.")
    if not lines:
        lines.append("The two runs ended in a similar shape; inspect turn-level diffs for the sharper separation.")
    return lines


def build_manual_vs_bot_report(base_dir, runtime_root, manual_log_path=None, manual_summary_path=None, bot_recent=160):
    manual_ref = load_manual_reference(base_dir, manual_log_path=manual_log_path, manual_summary_path=manual_summary_path)
    if not isinstance(manual_ref, dict):
        return None
    manual_report = manual_ref.get("report") or {}
    manual_sample = manual_ref.get("sample") or {}
    manual_summary_quality = _race_quality_from_summary_row(manual_ref.get("summary_row"))
    manual_race_quality = dict(manual_sample.get("race_quality") or {})
    manual_race_quality.update({k: v for k, v in manual_summary_quality.items() if v or v == 0})
    bot_candidates = load_bot_candidates(runtime_root, recent=bot_recent)
    bot_match = select_best_bot_match(manual_sample, bot_candidates)
    if not isinstance(bot_match, dict):
        return {
            "schema": "sweepy_manual_vs_bot_comparison_v1",
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "manual": {
                "path": manual_ref.get("path"),
                "source": manual_ref.get("source"),
                "status": manual_sample.get("status"),
                "run_context": manual_sample.get("run_context") or {},
                "final_stats": manual_sample.get("final_stats") or {},
                "race_quality": manual_race_quality,
                **summarize_action_counts(manual_report, manual_sample),
            },
            "bot": None,
            "comparison": {
                "summary": ["No finished bot run matched the manual run strongly enough to compare against."],
            },
        }

    bot_report = bot_match.get("report") or {}
    bot_sample = bot_match.get("sample") or {}
    manual_counts = summarize_action_counts(manual_report, manual_sample)
    bot_counts = summarize_action_counts(bot_report, bot_sample)
    turn_diffs = build_turn_decision_diffs(manual_report, bot_report)
    comparison = {
        "stat_delta_manual_minus_bot": _stat_delta(manual_sample.get("final_stats") or {}, bot_sample.get("final_stats") or {}),
        "action_delta_manual_minus_bot": _delta_dict(manual_counts.get("action_counts") or {}, bot_counts.get("action_counts") or {}),
        "training_delta_manual_minus_bot": _delta_dict(manual_counts.get("training_counts") or {}, bot_counts.get("training_counts") or {}),
        "race_delta_manual_minus_bot": {
            "race_wins": as_int(manual_race_quality.get("race_wins")) - as_int(bot_sample.get("race_wins")),
            "race_losses": as_int(manual_race_quality.get("race_losses")) - as_int(bot_sample.get("race_losses")),
            "g1_wins": as_int(manual_race_quality.get("g1_wins")) - as_int(((bot_sample.get("race_quality") or {}).get("g1_wins"))),
            "g1_losses": as_int(manual_race_quality.get("g1_losses")) - as_int(((bot_sample.get("race_quality") or {}).get("g1_losses"))),
        },
        **turn_diffs,
    }

    manual_block = {
        "path": manual_ref.get("path"),
        "source": manual_ref.get("source"),
        "status": manual_sample.get("status"),
        "full_career_capture": bool(manual_sample.get("full_career_capture")),
        "turn_count": as_int(manual_sample.get("turn_count")),
        "run_context": manual_sample.get("run_context") or {},
        "final_stats": manual_sample.get("final_stats") or {},
        "race_quality": manual_race_quality,
        **manual_counts,
    }
    bot_block = {
        "path": bot_match.get("path"),
        "status": bot_sample.get("status"),
        "full_career_capture": bool(bot_sample.get("full_career_capture")),
        "turn_count": as_int(bot_sample.get("turn_count")),
        "run_context": bot_sample.get("run_context") or {},
        "final_stats": bot_sample.get("final_stats") or {},
        "race_quality": bot_sample.get("race_quality") or {},
        "match_score": as_int(bot_match.get("match_score")),
        "match_reasons": list(bot_match.get("match_reasons") or []),
        **bot_counts,
    }
    comparison["summary"] = _comparison_summary(manual_block, bot_block, comparison)

    return {
        "schema": "sweepy_manual_vs_bot_comparison_v1",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "manual": manual_block,
        "bot": bot_block,
        "comparison": comparison,
    }


def write_comparison_report(runtime_root, report):
    if not isinstance(report, dict):
        return {}
    runtime_root = Path(runtime_root)
    out_dir = runtime_root / "manual_career_logs" / "comparisons"
    out_dir.mkdir(parents=True, exist_ok=True)
    latest_path = out_dir / "latest_manual_vs_bot_comparison.json"
    latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stamped_path = out_dir / f"manual_vs_bot_{stamp}.json"
    stamped_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "latest": str(latest_path),
        "stamped": str(stamped_path),
    }
