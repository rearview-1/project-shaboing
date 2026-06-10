import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path


SCHEMA = "sweepy_parent_memory_v1"
STAT_KEYS = ("speed", "stamina", "power", "guts", "wit", "skill_point")

# Serializes load-modify-save sequences against parent_library / registry.
# Without this, FastAPI handling two requests concurrently (or the runner
# emitting a save while a request handler also touches the registry) can
# race: both readers see the same starting state, both write back, and the
# later writer silently overwrites the earlier writer's mutations.
# Acquired in `remember_bot_career`, `reconcile_pending_bot_parents`, and
# `update_parent_library` so every RMW path is serialized.
_PARENT_MEMORY_LOCK = threading.RLock()


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def runtime_root(base_dir):
    override = os.environ.get("UMA_RUNTIME_DIR")
    if override:
        return Path(override).expanduser().resolve()
    base = Path(base_dir).resolve()
    for candidate in (base, *base.parents):
        if candidate.name == "uma_runtime":
            return candidate
    return base.parent / "uma_runtime"


def memory_dir(base_dir):
    path = runtime_root(base_dir) / "parent_memory"
    path.mkdir(parents=True, exist_ok=True)
    return path


def registry_path(base_dir):
    return memory_dir(base_dir) / "bot_parent_registry.json"


def library_path(base_dir):
    return memory_dir(base_dir) / "parent_library.json"


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Per-process .tmp path so two writers can't clobber the same .tmp file
    # mid-serialize. os.replace is atomic per-target on both POSIX and
    # Windows, so the worst-case is a "last writer wins" outcome — which is
    # acceptable when paired with the in-process lock acquired by the
    # higher-level RMW callers.
    serialized = json.dumps(data, ensure_ascii=False, indent=2)
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
        # Fallback: direct write so the data isn't lost. Atomicity weakens
        # for this one call but the file lands intact rather than failing.
        path.write_text(serialized, encoding="utf-8")
        try:
            tmp.unlink()
        except Exception:
            pass


def load_registry(base_dir):
    data = read_json(registry_path(base_dir), {})
    if not isinstance(data, dict):
        data = {}
    data.setdefault("schema", SCHEMA)
    data.setdefault("bot_parents", [])
    data.setdefault("pending_bot_careers", [])
    return data


def save_registry(base_dir, data):
    data = dict(data or {})
    data["schema"] = SCHEMA
    data["updated_at"] = now_iso()
    data.setdefault("bot_parents", [])
    data.setdefault("pending_bot_careers", [])
    write_json(registry_path(base_dir), data)


def safe_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def safe_stat(stats, key):
    stats = stats or {}
    if key == "wit":
        return safe_int(stats.get("wit", stats.get("wiz")))
    return safe_int(stats.get(key))


def final_turn_from_report(report):
    turns = report.get("turns") or []
    if not isinstance(turns, list) or not turns:
        return {}
    return max(
        (turn for turn in turns if isinstance(turn, dict)),
        key=lambda turn: safe_int(turn.get("turn")),
        default={},
    )


def final_stats_from_report(report):
    turn = final_turn_from_report(report)
    stats = dict(turn.get("stats") or {})
    if not stats:
        return {}
    result = {}
    for key in STAT_KEYS:
        value = safe_stat(stats, key)
        if value:
            result[key] = value
    if "skill_point" not in result and turn.get("skill_point") is not None:
        result["skill_point"] = safe_int(turn.get("skill_point"))
    return result


def compact_node(node):
    node = node or {}
    return {
        "card_id": safe_int(node.get("card_id")),
        "name": node.get("name") or "",
        "factors": node.get("factors") or [],
        "wins": node.get("wins") or {},
        "win_saddle_ids": node.get("win_saddle_ids") or [],
        "win_race_ids": node.get("win_race_ids") or [],
        "race_history": node.get("race_history") or [],
    }


def compact_parent(parent):
    parent = dict(parent or {})
    tree = parent.get("tree") or {}
    compact = {
        "instance_id": safe_int(parent.get("instance_id")),
        "card_id": safe_int(parent.get("card_id")),
        "name": parent.get("name") or "",
        "rank": parent.get("rank"),
        "score": parent.get("score"),
        "stats": parent.get("stats") or {},
        "skills": parent.get("skills") or [],
        "estimated_skill_points": parent.get("estimated_skill_points") or 0,
        "tree": {key: compact_node(tree.get(key)) for key in ("self", "p1", "p2", "gp1", "gp2", "gp3", "gp4")},
        "made_by_bot": bool(parent.get("made_by_bot")),
        "source_kind": parent.get("source_kind") or ("bot" if parent.get("made_by_bot") else "user"),
        "source_tags": parent.get("source_tags") or (["BOT"] if parent.get("made_by_bot") else ["USER"]),
    }
    if parent.get("bot_parent_info"):
        compact["bot_parent_info"] = parent.get("bot_parent_info")
    if parent.get("is_new"):
        compact["is_new"] = True
    return compact


def compact_run_context(run_context):
    ctx = dict(run_context or {})
    allowed = {
        "preset_name",
        "deck_id",
        "deck_name",
        "trainee_card_id",
        "support_card_ids",
        "friend_viewer_id",
        "friend_card_id",
        "parent_id_1",
        "parent_id_2",
        "rental_viewer_id",
        "rental_trained_chara_id",
        "borrow_fallback_id",
        "desired_parent_sparks",
        "parent_farming_rules",
        "started_from_active_career",
    }
    return {key: ctx.get(key) for key in allowed if key in ctx}


def remember_bot_career(base_dir, report, career_log=None):
    report = report or {}
    status = str(report.get("status") or "")
    final_turn = safe_int(report.get("final_turn"))
    if status != "finished" or final_turn < 78:
        return {"success": False, "skipped": "not_a_completed_parent"}

    run_context = compact_run_context(report.get("run_context") or {})
    final_stats = final_stats_from_report(report)
    card_id = safe_int(run_context.get("trainee_card_id"))
    if not card_id:
        last_turn = final_turn_from_report(report)
        card_id = safe_int(last_turn.get("card_id") or report.get("card_id"))

    career_log = str(career_log or "")
    entry = {
        "entry_id": f"{report.get('started_at') or now_iso()}::{career_log}",
        "created_at": now_iso(),
        "started_at": report.get("started_at"),
        "ended_at": report.get("ended_at"),
        "career_log": career_log,
        "preset_name": report.get("preset_name") or run_context.get("preset_name") or "",
        "card_id": card_id,
        "final_turn": final_turn,
        "final_stats": final_stats,
        "run_context": run_context,
    }

    # Serialize the load-modify-save sequence so concurrent callers (e.g.
    # two web requests, or the runner finalizing one career while another
    # request handler touches the registry) don't race on bot_parents /
    # pending_bot_careers. Without the lock the later writer silently
    # overwrites the earlier writer's append.
    with _PARENT_MEMORY_LOCK:
        registry = load_registry(base_dir)
        known_logs = {row.get("career_log") for row in registry.get("bot_parents", [])}
        known_logs.update(row.get("career_log") for row in registry.get("pending_bot_careers", []))
        if career_log and career_log in known_logs:
            return {"success": True, "skipped": "already_recorded"}
        registry.setdefault("pending_bot_careers", []).append(entry)
        registry["pending_bot_careers"] = registry["pending_bot_careers"][-50:]
        save_registry(base_dir, registry)
    return {"success": True, "pending": True, "entry": entry}


def stat_match_score(parent, pending):
    parent_stats = parent.get("stats") or {}
    final_stats = pending.get("final_stats") or {}
    if not final_stats:
        return 0
    score = 0
    compared = 0
    for key in ("speed", "stamina", "power", "guts", "wit"):
        expected = safe_stat(final_stats, key)
        actual = safe_stat(parent_stats, key)
        if not expected or not actual:
            continue
        compared += 1
        delta = abs(expected - actual)
        if delta <= 2:
            score += 14
        elif delta <= 8:
            score += 8
        elif delta <= 25:
            score += 3
    if compared >= 3:
        score += 8
    return score


def match_pending_to_parent(parent, pending):
    score = 0
    pending_card = safe_int(pending.get("card_id"))
    parent_card = safe_int(parent.get("card_id"))
    if pending_card and parent_card:
        if pending_card != parent_card:
            return 0
        score += 35
    if parent.get("is_new"):
        score += 25
    score += stat_match_score(parent, pending)
    return score


def reconcile_pending_bot_parents(base_dir, parents):
    # Serialize the load-modify-save sequence — another caller hitting
    # remember_bot_career between our load_registry and save_registry would
    # have its append silently dropped when we write back our copy.
    with _PARENT_MEMORY_LOCK:
        registry = load_registry(base_dir)
        pending = list(registry.get("pending_bot_careers") or [])
        if not pending:
            return registry

        existing_ids = {safe_int(row.get("instance_id")) for row in registry.get("bot_parents", [])}
        matched_ids = set()
        for pending_row in pending:
            best_parent = None
            best_score = 0
            for parent in parents or []:
                instance_id = safe_int(parent.get("instance_id"))
                if not instance_id or instance_id in existing_ids or instance_id in matched_ids:
                    continue
                score = match_pending_to_parent(parent, pending_row)
                if score > best_score:
                    best_score = score
                    best_parent = parent
            if not best_parent or best_score < 68:
                continue
            instance_id = safe_int(best_parent.get("instance_id"))
            matched_ids.add(instance_id)
            existing_ids.add(instance_id)
            registry.setdefault("bot_parents", []).append({
                "instance_id": instance_id,
                "card_id": safe_int(best_parent.get("card_id")) or safe_int(pending_row.get("card_id")),
                "name": best_parent.get("name") or "",
                "registered_at": now_iso(),
                "match_score": best_score,
                "career_log": pending_row.get("career_log") or "",
                "preset_name": pending_row.get("preset_name") or "",
                "final_turn": pending_row.get("final_turn") or 0,
                "final_stats": pending_row.get("final_stats") or {},
                "run_context": pending_row.get("run_context") or {},
            })

        if matched_ids:
            matched_logs = {row.get("career_log") for row in registry.get("bot_parents", [])}
            registry["pending_bot_careers"] = [
                row for row in pending
                if not row.get("career_log") or row.get("career_log") not in matched_logs
            ]
            save_registry(base_dir, registry)
        return registry


def annotate_parents(base_dir, parents):
    parents = list(parents or [])
    registry = reconcile_pending_bot_parents(base_dir, parents)
    by_id = {safe_int(row.get("instance_id")): row for row in registry.get("bot_parents", [])}
    for parent in parents:
        instance_id = safe_int(parent.get("instance_id"))
        info = by_id.get(instance_id)
        tags = list(parent.get("source_tags") or [])
        if info:
            parent["made_by_bot"] = True
            parent["source_kind"] = "bot"
            if "BOT" not in tags:
                tags.insert(0, "BOT")
            parent["bot_parent_info"] = {
                "registered_at": info.get("registered_at"),
                "career_log": info.get("career_log"),
                "preset_name": info.get("preset_name"),
                "deck_id": (info.get("run_context") or {}).get("deck_id"),
                "deck_name": (info.get("run_context") or {}).get("deck_name"),
                "parent_id_1": (info.get("run_context") or {}).get("parent_id_1"),
                "parent_id_2": (info.get("run_context") or {}).get("parent_id_2"),
                "desired_parent_sparks": (info.get("run_context") or {}).get("desired_parent_sparks"),
                "match_score": info.get("match_score"),
            }
            _enrich_bot_parent_race_history(parent, info)
        else:
            parent.setdefault("made_by_bot", False)
            parent.setdefault("source_kind", "user")
            if "USER" not in tags:
                tags.append("USER")
        parent["source_tags"] = tags
    return parents


def _read_json_file(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _event_race_history_from_career_log(report):
    rows = []
    turns = report.get("turns") or []
    if not isinstance(turns, list):
        return rows
    for turn_index, turn in enumerate(turns):
        if not isinstance(turn, dict):
            continue
        turn_number = safe_int(turn.get("turn"))
        for event_index, event in enumerate(turn.get("events") or []):
            if not isinstance(event, dict) or event.get("event") != "race_result":
                continue
            race = event.get("race") or {}
            result_rank = safe_int(event.get("finish_rank") or event.get("result_rank"))
            if not result_rank:
                continue
            program_id = safe_int(event.get("program_id") or race.get("program_id"))
            race_id = safe_int(race.get("race_id") or event.get("race_id"))
            race_instance_id = safe_int(race.get("race_instance_id") or event.get("race_instance_id") or race_id)
            row = {
                "_order": len(rows),
                "turn": turn_number,
                "program_id": program_id,
                "race_id": race_id,
                "race_instance_id": race_instance_id,
                "name": race.get("name") or event.get("name") or (f"Program {program_id}" if program_id else "Unknown race"),
                "grade": race.get("grade") or event.get("grade") or "",
                "date": race.get("date") or event.get("date") or "",
                "result_rank": result_rank,
                "result": "won" if result_rank == 1 else "lost",
                "won": result_rank == 1,
                "source": "career_log.race_result",
                "style": safe_int(event.get("running_style") or event.get("style") or race.get("running_style") or race.get("style")),
                "running_style": safe_int(event.get("running_style") or event.get("style") or race.get("running_style") or race.get("style")),
            }
            desired_style = str(event.get("desired_running_style") or "").strip()
            if desired_style:
                row["desired_running_style"] = desired_style
            style_change = event.get("style_change")
            if isinstance(style_change, dict) and style_change:
                row["style_change"] = dict(style_change)
            rows.append((turn_number, turn_index, event_index, row))
    rows.sort(key=lambda item: (item[0], item[1], item[2], safe_int(item[3].get("program_id"))))
    return [row for _, _, _, row in rows]


def _win_summary_from_history(history, existing=None):
    summary = dict(existing or {})
    summary.setdefault("g1", 0)
    summary.setdefault("g2", 0)
    summary.setdefault("g3", 0)
    summary.setdefault("titles", 0)
    summary["losses"] = 0
    wins = {"g1": 0, "g2": 0, "g3": 0, "titles": 0}
    for row in history or []:
        rank = safe_int((row or {}).get("result_rank"))
        if rank > 1:
            summary["losses"] += 1
            continue
        if rank != 1:
            continue
        grade = str((row or {}).get("grade") or "").strip().upper()
        if grade == "G1":
            wins["g1"] += 1
        elif grade == "G2":
            wins["g2"] += 1
        elif grade == "G3":
            wins["g3"] += 1
        else:
            wins["titles"] += 1
    for key, value in wins.items():
        summary[key] = value
    summary["total"] = sum(wins.values())
    return summary


def _win_race_ids_from_history(history):
    result = []
    seen = set()
    for row in history or []:
        if safe_int((row or {}).get("result_rank")) != 1:
            continue
        race_id = safe_int((row or {}).get("race_instance_id") or (row or {}).get("race_id"))
        if not race_id or race_id in seen:
            continue
        seen.add(race_id)
        result.append(race_id)
    return result


def _enrich_bot_parent_race_history(parent, info):
    if not isinstance(parent, dict) or not isinstance(info, dict):
        return
    career_log = str(info.get("career_log") or "").strip()
    if not career_log:
        return
    report = _read_json_file(career_log)
    if not isinstance(report, dict):
        return
    history = _event_race_history_from_career_log(report)
    if not history:
        return
    tree = parent.setdefault("tree", {})
    self_node = tree.setdefault("self", {})
    self_node["race_history"] = history
    self_node["win_race_ids"] = _win_race_ids_from_history(history)
    self_node["wins"] = _win_summary_from_history(history, self_node.get("wins"))


def write_parent_library_snapshot(base_dir, parents):
    snapshot = {
        "schema": SCHEMA,
        "updated_at": now_iso(),
        "parents": [compact_parent(parent) for parent in parents or []],
    }
    write_json(library_path(base_dir), snapshot)
    return snapshot


def load_parent_library(base_dir):
    data = read_json(library_path(base_dir), {})
    if not isinstance(data, dict):
        return {"schema": SCHEMA, "parents": []}
    data.setdefault("schema", SCHEMA)
    data.setdefault("parents", [])
    return data
