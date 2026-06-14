import os
import json
import re
import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel, Field
from pathlib import Path
import random
import subprocess
import time
import sys
import threading
import inspect
import traceback
import shutil
from types import SimpleNamespace
import frida
OPTIONAL_IMPORT_ERRORS = {}
try:
    from career_bot.deck_advice import build_deck_advice
except ModuleNotFoundError as exc:
    if exc.name != "career_bot.deck_advice":
        raise
    build_deck_advice = None
    OPTIONAL_IMPORT_ERRORS["career_bot.deck_advice"] = str(exc)
from career_bot.observed_profiles import append_team_observations, load_observation_samples, summarize_observation_samples
from career_bot.presets import PresetStore, instance_learning_override_path, read_instance_learning_override, slugify
from career_bot.manual_recorder import (
    ManualCareerRecorder,
    build_report_from_hachimi_summaries,
    build_report_from_trace,
    decode_horseact_body,
)
from career_bot.career_compare import build_manual_vs_bot_report, write_comparison_report
from career_bot.daily_tasks import (
    DailyAutomationConfig,
    action_config_error,
    normalize_action_steps,
    normalize_style_id,
    render_template_value,
    showtime_difficulty_options,
    summarize_daily_event_status,
)
from career_bot.api_discovery import (
    ApiDiscoverySession,
    compare_captures,
    list_capture_summaries,
    load_capture_entries,
    write_contract,
)
from career_bot.parent_memory import annotate_parents, write_parent_library_snapshot
from career_bot.profile_dataset import (
    extract_profile_records_from_response,
    ingest_trace_dataset,
    load_name_maps,
    list_dataset_records as list_profile_dataset_records,
    normalize_trained_chara_record,
    summarize_dataset as summarize_profile_dataset,
)
from career_bot.race_schedule import RaceCatalog, normalize_style as normalize_race_style
from career_bot.rating import rank_for_rating_score
from career_bot.runner import CareerRunner, runtime_output_root
from career_bot.skill_profiles import build_skill_priority_rows, normalize_distance as normalize_skill_distance, normalize_style as normalize_skill_style, sanitize_blacklist, split_skill_text
from career_bot.team_trials_dataset import RANK_LABELS, deck_race_bonus_summary, load_team_trials_dataset
from uma_api.client import UmaClient, read_client_version_cache

GLB_STEAM_APP_ID = "3224770"
JP_STEAM_APP_ID = "3564400"
PROCESS_NAME = os.environ.get("SWEEPY_GAME_PROCESS_NAME", "UmamusumePrettyDerby.exe").strip() or "UmamusumePrettyDerby.exe"
APP_ID = os.environ.get("SWEEPY_STEAM_APP_ID", GLB_STEAM_APP_ID).strip() or GLB_STEAM_APP_ID
TP_RECOVERY_NONE = 0
TP_RECOVERY_CARATS = 1
TP_RECOVERY_TOUGHNESS = 2
TP_RECOVERY_BOTH = 3
TP_RECOVERY_CARAT_COST = 10
TP_RECOVERY_ITEM_IDS = (32,)
TP_RECOVERY_SECONDS_PER_POINT = 300

JS_CODE = r'''
'use strict';
(function() {
    var buffers = {};
    var attached = {};
    function hex2(n) { return ('0' + (n & 255).toString(16)).slice(-2); }
    function uuidFromHex(h) {
        return h.substring(0, 8) + '-' + h.substring(8, 12) + '-' + h.substring(12, 16) + '-' + h.substring(16, 20) + '-' + h.substring(20);
    }
    function b64(s) {
        var chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
        var out = [];
        var buffer = 0;
        var bits = 0;
        for (var i = 0; i < s.length; i++) {
            var c = s.charAt(i);
            if (c === '=') break;
            var idx = chars.indexOf(c);
            if (idx < 0) continue;
            buffer = (buffer << 6) | idx;
            bits += 6;
            if (bits >= 8) {
                bits -= 8;
                out.push((buffer >> bits) & 255);
            }
        }
        return out;
    }
    function parseWire(endpoint, viewerId, body, appVer, resVer) {
        var decoded = b64(body);
        if (decoded.length < 140) return;
        var headerLen = decoded[0] | (decoded[1] << 8) | (decoded[2] << 16) | (decoded[3] << 24);
        var blob1End = 4 + headerLen;
        if (headerLen < 120 || headerLen > 2048 || decoded.length < blob1End) return;
        
        var udidHex = '';
        for (var i = blob1End - 96; i < blob1End - 80; i++) udidHex += hex2(decoded[i]);
        var authHex = '';
        for (var j = blob1End - 48; j < blob1End; j++) authHex += hex2(decoded[j]);
        
        if (!viewerId || !authHex || authHex.length < 64 || udidHex.length !== 32) return;
        
        send({
            type: 'creds',
            endpoint: endpoint,
            viewer_id: parseInt(viewerId, 10),
            udid: uuidFromHex(udidHex),
            auth_key: authHex,
            auth_key_len: authHex.length / 2,
            app_ver: appVer,
            res_ver: resVer
        });
    }
    function parseHttp(text) {
        if (text.indexOf('/umamusume/') < 0) return;
        var em = text.match(/POST\s+\/umamusume\/([^\s]+)\s+HTTP/i);
        var vm = text.match(/(?:^|\r\n)(?:ViewerID|ViewerId):\s*(\d+)/i);
        var appVer = text.match(/(?:^|\r\n)APP-VER:\s*([^\r\n]+)/i);
        var resVer = text.match(/(?:^|\r\n)RES-VER:\s*([^\r\n]+)/i);
        var idx = text.indexOf('\r\n\r\n');
        if (!em || !vm || idx < 0) return;
        parseWire(em[1], vm[1], text.substring(idx + 4), appVer ? appVer[1].trim() : '', resVer ? resVer[1].trim() : '');
    }
    function parseChunk(key, chunk) {
        var buf = (buffers[key] || '') + chunk;
        if (buf.length > 2097152) buf = buf.substring(buf.length - 1048576);
        var start = buf.indexOf('POST ');
        if (start < 0) {
            buffers[key] = buf.slice(-4096);
            return;
        }
        if (start > 0) buf = buf.substring(start);
        var headerEnd = buf.indexOf('\r\n\r\n');
        if (headerEnd < 0) {
            buffers[key] = buf;
            return;
        }
        var headers = buf.substring(0, headerEnd);
        var lm = headers.match(/Content-Length:\s*(\d+)/i);
        var length = lm ? parseInt(lm[1], 10) : 0;
        var total = headerEnd + 4 + length;
        if (length > 0 && buf.length < total) {
            buffers[key] = buf;
            return;
        }
        parseHttp(length > 0 ? buf.substring(0, total) : buf);
        buffers[key] = buf.length > total ? buf.substring(total) : '';
    }
    function hookTls() {
        var ga = Process.findModuleByName('GameAssembly.dll');
        if (!ga) return false;
        var installFn = ga.findExportByName('il2cpp_unity_install_unitytls_interface');
        if (!installFn) return false;
        var rb = new Uint8Array(installFn.readByteArray(16));
        var realFn = installFn;
        if (rb[0] === 0xe9) {
            var off = rb[1] | (rb[2] << 8) | (rb[3] << 16) | (rb[4] << 24);
            if (off > 0x7fffffff) off -= 0x100000000;
            realFn = installFn.add(5 + off);
            rb = new Uint8Array(realFn.readByteArray(16));
        }
        var globalPtr = null;
        if (rb[0] === 0x48 && rb[1] === 0x89 && rb[2] === 0x0d) {
            var disp = rb[3] | (rb[4] << 8) | (rb[5] << 16) | (rb[6] << 24);
            if (disp > 0x7fffffff) disp -= 0x100000000;
            globalPtr = realFn.add(7 + disp);
        }
        if (!globalPtr) return false;
        var iface = globalPtr.readPointer();
        if (!iface || iface.isNull()) return false;
        var hookedTls = 0;
        [0xd0, 0xd8, 0xe0, 0xe8].forEach(function(off) {
            var addr = iface.add(off).readPointer();
            if (!addr || addr.isNull()) return;
            var key = 'tls_' + addr.toString();
            if (attached[key]) return;
            try {
                Interceptor.attach(addr, {
                    onEnter: function(args) {
                        var len = args[2].toInt32();
                        if (len <= 0 || len > 1048576 || args[1].isNull()) return;
                        try {
                            var bytes = args[1].readByteArray(len);
                            var u8 = new Uint8Array(bytes);
                            var s = '';
                            for (var i = 0; i < u8.length; i++) s += String.fromCharCode(u8[i]);
                            parseChunk(args[0].toString(), s);
                        } catch (e) {}
                    }
                });
                attached[key] = true;
                hookedTls++;
            } catch (e) {}
        });
        return hookedTls > 0;
    }
    var tlsDone = false;
    var timer = setInterval(function() {
        try {
            if (!tlsDone) tlsDone = hookTls();
            if (tlsDone) clearInterval(timer);
        } catch (e) {}
    }, 1000);
})();
'''


DIR = os.path.dirname(os.path.abspath(__file__))

_session_sidecar_watcher = None


@asynccontextmanager
async def _app_lifespan(app):
    """Startup/shutdown via FastAPI's lifespan API.

    Replaces the deprecated ``@app.on_event("startup")`` hook, which printed
    a ``DeprecationWarning`` on every boot — visible on the console after each
    backend refresh. Startup work: launch the hachimi session sidecar watcher
    (Path B from docs/capture-tool-clarification.md — drops a
    learning_session.json sidecar into each new career so the bot loader can
    pair it with the active session without a DLL rebuild), run storage
    cleanup, and sync the latest manual capture. The sidecar watcher
    auto-disables under unittest/pytest via the same
    `_hachimi_capture_career_dirs` guard the loader uses. No shutdown work is
    required."""
    global _session_sidecar_watcher
    try:
        from career_bot.session_sidecar import SessionSidecarWatcher
        _session_sidecar_watcher = SessionSidecarWatcher(Path(DIR))
        _session_sidecar_watcher.start()
    except Exception as exc:
        print(f"[main] failed to start SessionSidecarWatcher: {exc}", flush=True)
    try:
        from career_bot.storage_cleanup import run_startup_cleanup
        cleanup_result = run_startup_cleanup(DIR)
        counts = {
            key: value.get("removed_count", 0)
            for key, value in cleanup_result.items()
            if isinstance(value, dict)
        }
        if any(counts.values()):
            print(f"[main] startup cleanup removed files: {counts}", flush=True)
    except Exception as exc:
        print(f"[main] startup cleanup failed: {exc}", flush=True)
    try:
        sync_latest_manual_capture_to_runtime()
    except Exception as exc:
        print(f"[main] failed to sync latest manual capture: {exc}", flush=True)
    yield


app = FastAPI(lifespan=_app_lifespan)
SERVER_START_TIME = time.time()
SERVER_VERSION_TOKEN = f"{int(SERVER_START_TIME * 1000)}-{os.getpid()}"

chara_map = {}
support_map = {}
active_client = None
active_account = None
active_dashboard_data = None
active_start_state = {}
active_start_debug = {}
active_parent_cards = {}
active_parent_rank_points = {}
active_deck_debug = {}
deck_advice_cache = {
    "key": None,
    "advice": None,
}
seen_trained_chara_ids = None
most_recent_trained_chara_id = 0
pending_game_auth_config = {}
raw_load_index_response = None
active_selection = {
    "deck": None,
    "friend": None,
    "trainee": None,
    "veterans": []
}
active_api_discovery_session = None
loop_lock = threading.Lock()
state_sync_lock = threading.RLock()
loop_thread = None
active_loop = {
    "active": False,
    "stop_requested": False,
    "mode": "forever",
    "requested": 0,
    "career_limit": 0,
    "fan_limit": 0,
    "fans": 0,
    "completed": 0,
    "current": 0,
    "waiting_for_tp": False,
    "tp_current": 0,
    "tp_required": 0,
    "last_error": "",
    "last_message": ""
}
dev_reloader_state = {
    "thread": None,
    "pending_restart": False,
    "last_change": "",
    "restart_requested": False,
    "pending_restart_gate": "",
    "pending_restart_release": "",
}
git_auto_update_state = {
    "thread": None,
    "enabled": False,
    "running": False,
    "last_check": "",
    "last_update": "",
    "status": "idle",
    "detail": "",
    "remote": "",
    "branch": "",
    "local_rev": "",
    "remote_rev": "",
    "dirty": False,
    "behind": False,
    "ahead_or_diverged": False,
    "restart_queued": False,
}
git_auto_update_lock = threading.RLock()
turn_delay_min_sec = 3.0
turn_delay_max_sec = 5.0
turn_delay_restore_min_sec = 3.0
turn_delay_restore_max_sec = 5.0
turn_delay_disabled = False
preset_store = PresetStore(DIR)
career_runner = CareerRunner(DIR)
manual_career_recorder = ManualCareerRecorder(DIR)
race_catalog = RaceCatalog(DIR)

base_dir = Path(__file__).parent.absolute()
chara_path = base_dir / 'data' / 'chara_list.json'
support_path = base_dir / 'data' / 'support_list.json'
images_dir = base_dir / 'data' / 'images'


def env_flag(name, default=True):
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def sweepy_instance_name():
    value = str(os.environ.get("SWEEPY_INSTANCE_NAME") or "").strip()
    if value:
        return value
    override = str(os.environ.get("UMA_RUNTIME_DIR") or "").strip()
    if override:
        try:
            return Path(override).expanduser().resolve().name
        except Exception:
            return Path(override).name or "default"
    return "default"


def sweepy_bind_host():
    value = str(os.environ.get("SWEEPY_HOST") or "127.0.0.1").strip()
    return value or "127.0.0.1"


def sweepy_bind_port():
    try:
        port = int(os.environ.get("SWEEPY_PORT") or 1616)
    except (TypeError, ValueError):
        port = 1616
    return max(1, min(65535, port))


def sweepy_kill_existing_listener_enabled():
    return env_flag("SWEEPY_KILL_EXISTING_LISTENER", True)


def dual_instance_mode_enabled():
    return bool(os.environ.get("SWEEPY_SHARED_RUNTIME_PATHS") and os.environ.get("SWEEPY_INSTANCE_NAME"))


def auth_capture_kill_game_enabled():
    return env_flag("SWEEPY_AUTH_CAPTURE_KILL_GAME", not dual_instance_mode_enabled())


def dev_runtime_dir():
    path = runtime_output_root(DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _manual_capture_file_set(root):
    root = Path(root)
    return {
        "root": root,
        "log": root / "latest_manual_career_log.json",
        "summary": root / "latest_manual_career_summary.json",
        "raw": root / "latest_manual_career_raw.json",
    }


def _manual_capture_latest_mtime(file_set):
    latest = 0.0
    for key in ("log", "summary", "raw"):
        path = file_set.get(key)
        if path and path.exists():
            latest = max(latest, path.stat().st_mtime)
    return latest


def _manual_capture_log_has_turns(log_path):
    data = _read_json_file(log_path)
    return isinstance(data, dict) and isinstance(data.get("turns"), list)


def _copy_if_newer(src, dst):
    src = Path(src)
    dst = Path(dst)
    if not src.exists():
        return False
    if dst.exists():
        src_stat = src.stat()
        dst_stat = dst.stat()
        if dst_stat.st_mtime >= src_stat.st_mtime and dst_stat.st_size == src_stat.st_size:
            return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _read_json_file(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _latest_hachimi_career_artifacts(source):
    source_root = Path((source or {}).get("root") or "")
    if source_root.name != "_latest":
        return {}
    career_data_root = source_root.parent
    summary = _read_json_file(source.get("summary"))
    career_key = ""
    if isinstance(summary, dict):
        career_key = str(summary.get("career_key") or "").strip()
    career_dir = None
    if career_key:
        matches = [path for path in career_data_root.rglob(career_key) if path.is_dir()]
        if matches:
            matches.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            career_dir = matches[0]
    if not career_dir:
        candidates = [
            path for path in career_data_root.rglob("summary_events.jsonl")
            if path.parent.name not in {"_latest", "_debug"}
        ]
        if candidates:
            candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
            career_dir = candidates[0].parent
    if not career_dir:
        return {}
    return {
        "career_dir": career_dir,
        "summary_events": career_dir / "summary_events.jsonl",
        "turn_events": career_dir / "turn_events.jsonl",
        "raw_events": career_dir / "raw_events.jsonl",
        "event_events": career_dir / "event_events.jsonl",
        "manifest": career_dir / "manifest.json",
        "latest_summary": career_dir / "latest_summary.json",
        "latest_raw": career_dir / "latest_raw.json",
        "latest_event_audit": career_dir / "latest_event_audit.json",
        "exact_hooks": career_data_root / "_debug" / "hachimi_exact_hooks.jsonl",
    }


def latest_manual_capture_source():
    """Return the newest available manual-capture file set.

    Newer Hachimi installs write the freshest `_latest/*.json` files under
    `.../hachimi/Career turn data/_latest/`, while older Sweepy flows still
    mirror into `uma_runtime/manual_career_logs/`. When the runtime mirror goes
    stale but Hachimi `_latest` is current, prefer the Hachimi copy.
    """
    candidates = []
    runtime_set = _manual_capture_file_set(manual_career_recorder.output_dir)
    candidates.append(runtime_set)
    try:
        from career_bot.learning import _hachimi_capture_career_dirs
        for career_dir in _hachimi_capture_career_dirs():
            latest_dir = Path(career_dir) / "_latest"
            candidates.append(_manual_capture_file_set(latest_dir))
    except Exception:
        pass

    best = None
    best_mtime = 0.0
    for file_set in candidates:
        log_path = file_set["log"]
        if not log_path.exists():
            continue
        candidate_mtime = _manual_capture_latest_mtime(file_set)
        prefer_candidate = False
        if best is not None and abs(candidate_mtime - best_mtime) < 1e-6:
            best_is_runtime = best["root"].resolve() == runtime_set["root"].resolve()
            candidate_is_hachimi_latest = Path(file_set["root"]).name == "_latest"
            if best_is_runtime and candidate_is_hachimi_latest and not _manual_capture_log_has_turns(best["log"]):
                prefer_candidate = True
        if best is None or candidate_mtime > best_mtime:
            best = file_set
            best_mtime = candidate_mtime
        elif prefer_candidate:
            best = file_set
            best_mtime = candidate_mtime
    return best


def sync_latest_manual_capture_to_runtime():
    """Mirror the freshest manual-capture files back into runtime output.

    This keeps `uma_runtime/manual_career_logs/latest_manual_career_*.json`
    visible even when the active capture flow only writes to Hachimi's `_latest`
    directory.
    """
    source = latest_manual_capture_source()
    if not source:
        return None
    runtime_set = _manual_capture_file_set(manual_career_recorder.output_dir)
    if source["root"].resolve() == runtime_set["root"].resolve():
        return runtime_set

    runtime_set["root"].mkdir(parents=True, exist_ok=True)
    artifacts = _latest_hachimi_career_artifacts(source)
    rebuilt_log = False
    summary_events = artifacts.get("summary_events")
    if summary_events and summary_events.exists():
        try:
            build_report_from_hachimi_summaries(summary_events, DIR, output_dir=runtime_set["root"])
            rebuilt_log = True
        except Exception as exc:
            print(f"[main] failed to rebuild latest manual log from hachimi summaries: {exc}", flush=True)
    for key in ("summary", "raw"):
        src = source.get(key)
        dst = runtime_set.get(key)
        if src and src.exists():
            shutil.copy2(src, dst)
        elif dst.exists():
            dst.unlink()
    if not rebuilt_log:
        src = source.get("log")
        dst = runtime_set.get("log")
        if src and src.exists():
            shutil.copy2(src, dst)
        elif dst.exists():
            dst.unlink()
    for artifact_key, runtime_name in (
        ("summary_events", "summary_events.jsonl"),
        ("turn_events", "turn_events.jsonl"),
        ("raw_events", "raw_events.jsonl"),
        ("event_events", "event_events.jsonl"),
        ("manifest", "manifest.json"),
        ("latest_summary", "career_latest_summary.json"),
        ("latest_raw", "career_latest_raw.json"),
        ("latest_event_audit", "latest_event_audit.json"),
        ("exact_hooks", "hachimi_exact_hooks.jsonl"),
    ):
        src = artifacts.get(artifact_key)
        if src and src.exists():
            _copy_if_newer(src, runtime_set["root"] / runtime_name)
    return runtime_set


def dev_session_cache_path():
    return dev_runtime_dir() / "dev_session.json"


def reusable_auth_profiles_path():
    return dev_runtime_dir() / "reusable_auth_profiles.json"


def dev_session_cache_enabled():
    return env_flag("SWEEPY_DEV_SESSION_CACHE", True)


def backend_dev_reload_enabled():
    return env_flag("SWEEPY_DEV_RELOAD", True)


def backend_dev_reload_during_run_enabled():
    return env_flag("SWEEPY_DEV_RELOAD_DURING_RUN", False)


def git_auto_update_enabled():
    return env_flag("SWEEPY_AUTO_GIT_UPDATE", True)


def git_auto_update_interval_sec():
    raw = os.environ.get("SWEEPY_AUTO_GIT_UPDATE_INTERVAL_SEC", "300")
    try:
        value = int(float(raw))
    except (TypeError, ValueError):
        value = 300
    return max(30, min(3600, value))


def git_auto_update_initial_delay_sec():
    raw = os.environ.get("SWEEPY_AUTO_GIT_UPDATE_INITIAL_DELAY_SEC", "8")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 8.0
    return max(0.0, min(300.0, value))


def git_auto_update_snapshot():
    with git_auto_update_lock:
        return {
            key: value
            for key, value in git_auto_update_state.items()
            if key != "thread"
        }


def set_git_auto_update_state(**values):
    with git_auto_update_lock:
        git_auto_update_state.update(values)
        return git_auto_update_snapshot()


def run_git_command(args, timeout=30):
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(base_dir),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except FileNotFoundError:
        return SimpleNamespace(returncode=127, stdout="", stderr="git executable not found")
    except subprocess.TimeoutExpired as exc:
        return SimpleNamespace(returncode=124, stdout=exc.stdout or "", stderr=f"git command timed out: {' '.join(args)}")


def choose_git_auto_update_remote():
    configured = str(os.environ.get("SWEEPY_AUTO_GIT_UPDATE_REMOTE") or "").strip()
    result = run_git_command(["remote"], timeout=10)
    if result.returncode != 0:
        return configured, result.stderr.strip() or result.stdout.strip()
    remotes = [line.strip() for line in (result.stdout or "").splitlines() if line.strip()]
    if configured:
        return configured, "" if configured in remotes else f"configured remote '{configured}' is not present"
    if "shaboing" in remotes:
        return "shaboing", ""
    if "origin" in remotes:
        return "origin", ""
    return (remotes[0], "") if remotes else ("", "no git remotes configured")


def choose_git_auto_update_branch():
    configured = str(os.environ.get("SWEEPY_AUTO_GIT_UPDATE_BRANCH") or "").strip()
    if configured:
        return configured, ""
    result = run_git_command(["branch", "--show-current"], timeout=10)
    if result.returncode != 0:
        return "", result.stderr.strip() or result.stdout.strip()
    branch = str(result.stdout or "").strip()
    return branch, "" if branch else "repository is detached; no current branch"


def git_worktree_dirty():
    result = run_git_command(["status", "--porcelain"], timeout=15)
    if result.returncode != 0:
        return True, result.stderr.strip() or result.stdout.strip() or "git status failed"
    return bool(str(result.stdout or "").strip()), ""


def git_rev_parse(ref):
    result = run_git_command(["rev-parse", ref], timeout=10)
    if result.returncode != 0:
        return "", result.stderr.strip() or result.stdout.strip()
    return str(result.stdout or "").strip(), ""


def git_is_ancestor(older_ref, newer_ref):
    result = run_git_command(["merge-base", "--is-ancestor", older_ref, newer_ref], timeout=15)
    return result.returncode == 0


def git_auto_update_process_lock_dir():
    return Path(DIR) / "uma_runtime" / "git_auto_update.lock"


def acquire_git_auto_update_process_lock(stale_after_sec=600):
    lock_dir = git_auto_update_process_lock_dir()
    try:
        lock_dir.parent.mkdir(parents=True, exist_ok=True)
        os.mkdir(lock_dir)
        try:
            (lock_dir / "owner.json").write_text(
                json.dumps({"pid": os.getpid(), "created_at": time.time()}, ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception:
            pass
        return True, ""
    except FileExistsError:
        try:
            age = time.time() - lock_dir.stat().st_mtime
        except OSError:
            age = 0
        if age > stale_after_sec:
            try:
                shutil.rmtree(lock_dir)
                os.mkdir(lock_dir)
                return True, "cleared stale git auto-update lock"
            except Exception as exc:
                return False, f"git auto-update lock is stale but could not be cleared: {exc}"
        return False, "another Sweepy instance is already checking for git updates"
    except Exception as exc:
        return False, f"could not create git auto-update lock: {exc}"


def release_git_auto_update_process_lock():
    try:
        shutil.rmtree(git_auto_update_process_lock_dir())
    except FileNotFoundError:
        pass
    except Exception as exc:
        print(f"git auto-update lock release failed: {exc}", flush=True)


def perform_git_auto_update(manual=False):
    auto_enabled = git_auto_update_enabled()
    with git_auto_update_lock:
        if git_auto_update_state.get("running"):
            return {
                "success": False,
                "status": git_auto_update_state.get("status") or "running",
                "detail": "Git auto-update check is already running",
                "state": git_auto_update_snapshot(),
            }
        git_auto_update_state["running"] = True
        git_auto_update_state["enabled"] = auto_enabled or bool(manual)
        git_auto_update_state["last_check"] = time.strftime("%Y-%m-%d %H:%M:%S")
        git_auto_update_state["status"] = "checking"
        git_auto_update_state["detail"] = ""
    process_lock_acquired = False
    try:
        if not auto_enabled and not manual:
            state = set_git_auto_update_state(enabled=False, status="disabled", detail="disabled by SWEEPY_AUTO_GIT_UPDATE")
            return {"success": True, "status": "disabled", "detail": state["detail"], "state": state}
        if not (base_dir / ".git").exists():
            state = set_git_auto_update_state(status="not_git_repo", detail="no .git directory found")
            return {"success": False, "status": "not_git_repo", "detail": state["detail"], "state": state}
        process_lock_acquired, process_lock_detail = acquire_git_auto_update_process_lock()
        if not process_lock_acquired:
            state = set_git_auto_update_state(status="locked", detail=process_lock_detail)
            return {"success": True, "status": "locked", "detail": process_lock_detail, "state": state}
        if process_lock_detail:
            print(f"git auto-update: {process_lock_detail}", flush=True)

        remote, remote_error = choose_git_auto_update_remote()
        branch, branch_error = choose_git_auto_update_branch()
        set_git_auto_update_state(remote=remote, branch=branch)
        if remote_error:
            state = set_git_auto_update_state(status="remote_error", detail=remote_error)
            return {"success": False, "status": "remote_error", "detail": remote_error, "state": state}
        if branch_error:
            state = set_git_auto_update_state(status="branch_error", detail=branch_error)
            return {"success": False, "status": "branch_error", "detail": branch_error, "state": state}

        fetch = run_git_command(["fetch", "--quiet", remote, branch], timeout=60)
        if fetch.returncode != 0:
            detail = (fetch.stderr or fetch.stdout or "git fetch failed").strip()
            state = set_git_auto_update_state(status="fetch_error", detail=detail)
            return {"success": False, "status": "fetch_error", "detail": detail, "state": state}

        local_ref = "HEAD"
        remote_ref = f"{remote}/{branch}"
        local_rev, local_error = git_rev_parse(local_ref)
        remote_rev, remote_rev_error = git_rev_parse(remote_ref)
        set_git_auto_update_state(local_rev=local_rev, remote_rev=remote_rev)
        if local_error or remote_rev_error:
            detail = local_error or remote_rev_error
            state = set_git_auto_update_state(status="rev_error", detail=detail)
            return {"success": False, "status": "rev_error", "detail": detail, "state": state}

        dirty, dirty_error = git_worktree_dirty()
        set_git_auto_update_state(dirty=dirty)
        if dirty_error:
            state = set_git_auto_update_state(status="dirty_check_error", detail=dirty_error)
            return {"success": False, "status": "dirty_check_error", "detail": dirty_error, "state": state}

        if local_rev == remote_rev:
            state = set_git_auto_update_state(
                status="up_to_date",
                detail=f"{branch} is up to date with {remote_ref}",
                behind=False,
                ahead_or_diverged=False,
                restart_queued=False,
            )
            return {"success": True, "status": "up_to_date", "detail": state["detail"], "state": state}

        fast_forward_possible = git_is_ancestor("HEAD", remote_ref)
        ahead_or_diverged = not fast_forward_possible
        set_git_auto_update_state(behind=fast_forward_possible, ahead_or_diverged=ahead_or_diverged)
        if ahead_or_diverged:
            detail = f"local {branch} is ahead of or diverged from {remote_ref}; auto-update only supports fast-forward pulls"
            state = set_git_auto_update_state(status="diverged", detail=detail)
            return {"success": False, "status": "diverged", "detail": detail, "state": state}
        if dirty:
            detail = "local working tree has uncommitted changes; auto-update will wait"
            state = set_git_auto_update_state(status="dirty_waiting", detail=detail)
            return {"success": False, "status": "dirty_waiting", "detail": detail, "state": state}
        if runner_is_active():
            detail = f"update available from {remote_ref}; waiting for runner to become idle"
            state = set_git_auto_update_state(status="waiting_for_idle", detail=detail)
            return {"success": True, "status": "waiting_for_idle", "detail": detail, "state": state}

        pull = run_git_command(["pull", "--ff-only", remote, branch], timeout=120)
        if pull.returncode != 0:
            detail = (pull.stderr or pull.stdout or "git pull --ff-only failed").strip()
            state = set_git_auto_update_state(status="pull_error", detail=detail)
            return {"success": False, "status": "pull_error", "detail": detail, "state": state}

        new_local_rev, _ = git_rev_parse("HEAD")
        detail = f"updated {branch} from {local_rev[:12]} to {new_local_rev[:12]}"
        restart_queued = False
        if runner_is_active():
            defer_backend_restart_until_manual_stop()
            detail += "; backend restart deferred until runner stops"
        elif not dev_reloader_state.get("restart_requested"):
            restart_queued = schedule_backend_restart("git_auto_update", delay_sec=0.75)
            detail += "; backend restart queued" if restart_queued else "; backend restart already pending"
        else:
            restart_queued = True
            detail += "; backend restart already pending"
        state = set_git_auto_update_state(
            status="updated",
            detail=detail,
            local_rev=new_local_rev,
            last_update=time.strftime("%Y-%m-%d %H:%M:%S"),
            behind=False,
            ahead_or_diverged=False,
            restart_queued=restart_queued,
        )
        print(f"git auto-update: {detail}", flush=True)
        return {"success": True, "status": "updated", "detail": detail, "state": state, "output": pull.stdout}
    except Exception as exc:
        detail = f"{type(exc).__name__}: {exc}"
        state = set_git_auto_update_state(status="error", detail=detail)
        print(f"git auto-update error: {detail}", flush=True)
        return {"success": False, "status": "error", "detail": detail, "state": state}
    finally:
        if process_lock_acquired:
            release_git_auto_update_process_lock()
        with git_auto_update_lock:
            git_auto_update_state["running"] = False


def git_auto_update_loop():
    delay = git_auto_update_initial_delay_sec()
    if delay:
        time.sleep(delay)
    while True:
        try:
            perform_git_auto_update()
        except Exception as exc:
            print(f"git auto-update loop error: {exc}", flush=True)
        time.sleep(git_auto_update_interval_sec())


def start_git_auto_updater():
    if not git_auto_update_enabled():
        set_git_auto_update_state(enabled=False, status="disabled", detail="disabled by SWEEPY_AUTO_GIT_UPDATE")
        print("git auto-update disabled via SWEEPY_AUTO_GIT_UPDATE", flush=True)
        return
    if git_auto_update_state.get("thread"):
        return
    set_git_auto_update_state(enabled=True, status="idle", detail="")
    thread = threading.Thread(target=git_auto_update_loop, name="sweepy-git-auto-updater", daemon=True)
    git_auto_update_state["thread"] = thread
    thread.start()
    print(f"git auto-update enabled; polling every {git_auto_update_interval_sec()}s", flush=True)


def empty_selection():
    return {
        "deck": None,
        "friend": None,
        "trainee": None,
        "veterans": []
    }


def client_dev_session_config(client):
    if not client:
        return None
    stored = getattr(client, "_sweepy_auth_config", None)
    cfg = dict(stored) if isinstance(stored, dict) else {}
    cfg.update({
        "viewer_id": getattr(client, "viewer_id", 0),
        "udid": getattr(client, "udid_str", ""),
        "auth_key": getattr(client, "auth_key_hex", ""),
        "auth_key_len": len(str(getattr(client, "auth_key_hex", "") or "")) // 2,
        "steam_id": getattr(client, "steam_id", ""),
        "steam_session_ticket": getattr(client, "steam_ticket", ""),
        "steam_app_id": getattr(client, "steam_app_id", APP_ID),
        "steam_username_seed": cfg.get("steam_username_seed", ""),
        "steam_password_seed": cfg.get("steam_password_seed", ""),
        "device_id": getattr(client, "device_id", ""),
        "device_identity_mode": getattr(client, "device_identity_mode", ""),
        "device_identity_instance": getattr(client, "device_identity_instance", ""),
        "device_name": getattr(client, "device_name", ""),
        "graphics_device_name": getattr(client, "graphics_device", ""),
        "ip_address": getattr(client, "ip_address", ""),
        "platform_os_version": getattr(client, "platform_os", ""),
        "locale": getattr(client, "locale", "JPN"),
        "unity_ver": getattr(client, "unity_ver", ""),
        "app_ver": getattr(client, "app_ver", ""),
        "res_ver": getattr(client, "res_ver", ""),
    })
    return cfg


def json_cache_default(value):
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, set):
        return sorted(value)
    return str(value)


def persist_dev_session_cache(reason="update"):
    if not dev_session_cache_enabled() or not active_client:
        return False
    try:
        apply_tp_timer_to_cached_state()
    except NameError:
        pass
    cfg = client_dev_session_config(active_client)
    if not cfg:
        return False
    if not has_fresh_auth_config(cfg) or not cfg.get("steam_id") or not cfg.get("steam_session_ticket"):
        return False
    path = dev_session_cache_path()
    payload = {
        "version": 1,
        "saved_at": time.time(),
        "reason": reason,
        "server": {
            "pid": os.getpid(),
            "started_at": SERVER_START_TIME,
            "version_token": SERVER_VERSION_TOKEN,
            "instance": sweepy_instance_name(),
            "host": sweepy_bind_host(),
            "port": sweepy_bind_port(),
        },
        "client_config": cfg,
        "dashboard": active_dashboard_data,
        "account": active_account,
        "selection": active_selection,
        "start_state": active_start_state,
        "start_debug": active_start_debug,
    }
    last_exc = None
    for attempt in range(3):
        tmp_path = path.with_name(
            f"{path.stem}.{os.getpid()}.{threading.get_ident()}.{int(time.time() * 1000)}.{random.randint(1000, 9999)}.tmp"
        )
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, default=json_cache_default)
            os.replace(tmp_path, path)
            return True
        except Exception as exc:
            last_exc = exc
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            if isinstance(exc, PermissionError) and attempt < 2:
                time.sleep(0.05 * (attempt + 1))
                continue
            break
    print(f"dev session cache write failed: {last_exc}", flush=True)
    return False


def clear_dev_session_cache():
    try:
        path = dev_session_cache_path()
        if path.exists():
            path.unlink()
    except Exception as exc:
        print(f"dev session cache clear failed: {exc}", flush=True)


def reusable_auth_profile_from_config(cfg):
    cfg = dict(cfg or {})
    steam_id = str(cfg.get("steam_id") or "").strip()
    if not steam_id or not has_fresh_auth_config(cfg):
        return None
    profile = {
        "steam_id": steam_id,
        "viewer_id": cfg.get("viewer_id"),
        "udid": cfg.get("udid"),
        "auth_key": cfg.get("auth_key"),
        "auth_key_len": cfg.get("auth_key_len"),
        "device_id": cfg.get("device_id"),
        "device_identity_mode": cfg.get("device_identity_mode"),
        "device_identity_instance": cfg.get("device_identity_instance"),
        "device_name": cfg.get("device_name"),
        "graphics_device_name": cfg.get("graphics_device_name"),
        "ip_address": cfg.get("ip_address"),
        "platform_os_version": cfg.get("platform_os_version"),
        "locale": cfg.get("locale"),
        "unity_ver": cfg.get("unity_ver"),
        "app_ver": cfg.get("app_ver"),
        "res_ver": cfg.get("res_ver"),
        "steam_app_id": cfg.get("steam_app_id") or APP_ID,
    }
    if not has_fresh_auth_config(profile):
        return None
    return profile


def has_basic_auth_identity(cfg):
    cfg = dict(cfg or {})
    viewer_id = cfg.get("viewer_id")
    udid = str(cfg.get("udid") or "").strip()
    auth_key = str(cfg.get("auth_key") or "").strip().lower()
    if not viewer_id or not udid or not auth_key:
        return False
    if not re.fullmatch(r"[0-9a-f]+", auth_key):
        return False
    if len(auth_key) < 32 or len(auth_key) % 2:
        return False
    if len(udid) != 36 or udid.count("-") != 4:
        return False
    return True


def load_reusable_auth_profiles():
    path = reusable_auth_profiles_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"reusable auth profile read failed: {exc}", flush=True)
        return {}
    if isinstance(payload, dict) and isinstance(payload.get("profiles"), dict):
        return payload.get("profiles") or {}
    if isinstance(payload, dict):
        return payload
    return {}


def save_reusable_auth_profile(cfg, reason="update"):
    profile = reusable_auth_profile_from_config(cfg)
    if not profile:
        return False
    steam_id = profile["steam_id"]
    path = reusable_auth_profiles_path()
    existing = load_reusable_auth_profiles()
    existing[steam_id] = {
        "saved_at": time.time(),
        "reason": reason,
        "config": profile,
    }
    payload = {
        "version": 1,
        "profiles": existing,
    }
    last_exc = None
    for attempt in range(3):
        tmp_path = path.with_name(
            f"{path.stem}.{os.getpid()}.{threading.get_ident()}.{int(time.time() * 1000)}.{random.randint(1000, 9999)}.tmp"
        )
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, default=json_cache_default)
            os.replace(tmp_path, path)
            return True
        except Exception as exc:
            last_exc = exc
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            if isinstance(exc, PermissionError) and attempt < 2:
                time.sleep(0.05 * (attempt + 1))
                continue
            break
    print(f"reusable auth profile write failed: {last_exc}", flush=True)
    return False


def remove_reusable_auth_profile(steam_id):
    steam_id = str(steam_id or "").strip()
    if not steam_id:
        return False
    profiles = load_reusable_auth_profiles()
    if steam_id not in profiles:
        return False
    profiles.pop(steam_id, None)
    path = reusable_auth_profiles_path()
    payload = {
        "version": 1,
        "profiles": profiles,
    }
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, default=json_cache_default)
        return True
    except Exception as exc:
        print(f"reusable auth profile removal failed: {exc}", flush=True)
        return False


def invalidate_reusable_auth_profile(steam_id, reason=""):
    steam_id = str(steam_id or "").strip()
    if not steam_id:
        return False
    removed = remove_reusable_auth_profile(steam_id)
    if removed:
        suffix = f": {reason}" if reason else ""
        print(f"invalidated reusable auth profile for Steam account {steam_id}{suffix}", flush=True)
    return removed


def reusable_auth_config_for_steam_id(steam_id, *, require_fresh=True):
    steam_id = str(steam_id or "").strip()
    if not steam_id:
        return None
    candidates = []
    active_cfg = client_dev_session_config(active_client) if active_client else None
    if active_cfg:
        candidates.append(active_cfg)

    profiles = load_reusable_auth_profiles()
    entry = profiles.get(steam_id)
    if isinstance(entry, dict):
        cached_cfg = entry.get("config") if isinstance(entry.get("config"), dict) else entry
        if isinstance(cached_cfg, dict):
            candidates.append(cached_cfg)

    try:
        path = dev_session_cache_path()
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            cached = payload.get("client_config") if isinstance(payload, dict) else None
            if isinstance(cached, dict):
                candidates.append(cached)
    except Exception:
        pass

    for candidate in candidates:
        candidate = dict(candidate or {})
        if str(candidate.get("steam_id") or "").strip() != steam_id:
            continue
        if (has_fresh_auth_config(candidate) if require_fresh else has_basic_auth_identity(candidate)):
            return candidate
    return None


def best_known_headless_auth_seed(steam_id=""):
    """Best-effort version metadata for clientless auth bootstrap.

    A fresh reusable auth profile is still best, but when one does not exist we
    can usually bootstrap by combining a Steam session ticket with locally known
    APP-VER / RES-VER / locale / unity values.
    """
    candidates = []
    cached_version = read_client_version_cache(APP_ID)
    if isinstance(cached_version, dict) and cached_version.get("app_ver") and cached_version.get("res_ver"):
        candidates.append({
            "app_ver": cached_version.get("app_ver"),
            "res_ver": cached_version.get("res_ver"),
            "unity_ver": cached_version.get("unity_ver") or "",
            "locale": cached_version.get("locale") or "",
        })
    active_cfg = client_dev_session_config(active_client) if active_client else None
    if isinstance(active_cfg, dict):
        candidates.append(active_cfg)

    profiles = load_reusable_auth_profiles()
    steam_id = str(steam_id or "").strip()
    if steam_id:
        entry = profiles.get(steam_id)
        if isinstance(entry, dict):
            same_cfg = entry.get("config") if isinstance(entry.get("config"), dict) else entry
            if isinstance(same_cfg, dict):
                candidates.append(same_cfg)

    profile_rows = []
    for entry in profiles.values():
        if not isinstance(entry, dict):
            continue
        cfg = entry.get("config") if isinstance(entry.get("config"), dict) else entry
        if isinstance(cfg, dict):
            profile_rows.append((float(entry.get("saved_at") or 0), cfg))
    profile_rows.sort(key=lambda item: item[0], reverse=True)
    candidates.extend(cfg for _, cfg in profile_rows)

    try:
        path = dev_session_cache_path()
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            cached = payload.get("client_config") if isinstance(payload, dict) else None
            if isinstance(cached, dict):
                candidates.append(cached)
    except Exception:
        pass

    # Sentinel values written to dev_session.json by the bot's session-restore
    # placeholder path. They look like real config but always 204 — so when we
    # see them, we MUST ignore the cached candidate and fall through to the
    # baked-in defaults below.
    PLACEHOLDER_APP_VERS = {"", "1.0.0", "0.0.0"}
    PLACEHOLDER_RES_VERS = {"", "0", "1", "2"}
    PLACEHOLDER_STEAM_IDS = {"", "steam-restore"}
    PLACEHOLDER_TICKETS = {"", "ticket-restore"}
    PLACEHOLDER_VIEWER_IDS = {0, 123456}

    def _looks_like_placeholder(cfg):
        if not isinstance(cfg, dict):
            return False
        if "steam_id" in cfg and str(cfg.get("steam_id") or "").strip() in PLACEHOLDER_STEAM_IDS:
            return True
        if "steam_session_ticket" in cfg and str(cfg.get("steam_session_ticket") or "").strip() in PLACEHOLDER_TICKETS:
            return True
        if "viewer_id" in cfg:
            try:
                vid = int(cfg.get("viewer_id") or 0)
            except (TypeError, ValueError):
                vid = 0
            if vid in PLACEHOLDER_VIEWER_IDS:
                return True
        if "app_ver" in cfg and str(cfg.get("app_ver") or "").strip() in PLACEHOLDER_APP_VERS:
            return True
        if "res_ver" in cfg and str(cfg.get("res_ver") or "").strip() in PLACEHOLDER_RES_VERS:
            return True
        return False

    seed = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if _looks_like_placeholder(candidate):
            # Skip the whole candidate — its values are all sentinels and
            # would 204 immediately. Better to fall through to the live
            # defaults than seed with garbage.
            continue
        if not seed.get("app_ver"):
            app_ver = str(candidate.get("app_ver") or "").strip()
            if app_ver and app_ver not in PLACEHOLDER_APP_VERS:
                seed["app_ver"] = app_ver
        if not seed.get("res_ver"):
            res_ver = str(candidate.get("res_ver") or "").strip()
            if res_ver and res_ver not in PLACEHOLDER_RES_VERS:
                seed["res_ver"] = res_ver
        if not seed.get("locale"):
            locale = str(candidate.get("locale") or "").strip()
            if locale:
                seed["locale"] = locale
        if not seed.get("unity_ver"):
            unity_ver = str(candidate.get("unity_ver") or "").strip()
            if unity_ver:
                seed["unity_ver"] = unity_ver
        if seed.get("app_ver") and seed.get("res_ver") and seed.get("locale") and seed.get("unity_ver"):
            break

    default_app_ver = os.environ.get("SWEEPY_DEFAULT_APP_VER", "1.22.0")
    default_res_ver = os.environ.get("SWEEPY_DEFAULT_RES_VER", "10006300")

    # If the seeded value is OLDER than the baked-in default, prefer the
    # default. This handles the common case where a user updates the bot
    # (newer defaults) but their cached dev_session.json still has the
    # old version — without this, the stale cache wins and you 204 forever.
    def _version_tuple(v):
        try:
            return tuple(int(p) for p in str(v or "").split("."))
        except (TypeError, ValueError):
            return ()

    seeded_app = seed.get("app_ver")
    if seeded_app and _version_tuple(seeded_app) < _version_tuple(default_app_ver):
        print(
            f"VERSION SEED: cached app_ver={seeded_app} is older than default "
            f"{default_app_ver}; using default.",
            flush=True,
        )
        seed["app_ver"] = default_app_ver

    seeded_res = seed.get("res_ver")
    try:
        if seeded_res and int(seeded_res) < int(default_res_ver):
            print(
                f"VERSION SEED: cached res_ver={seeded_res} is older than default "
                f"{default_res_ver}; using default.",
                flush=True,
            )
            seed["res_ver"] = default_res_ver
    except (TypeError, ValueError):
        pass

    if not seed.get("app_ver"):
        seed["app_ver"] = default_app_ver
    if not seed.get("res_ver"):
        seed["res_ver"] = default_res_ver
    if not seed.get("locale"):
        seed["locale"] = os.environ.get("SWEEPY_DEFAULT_LOCALE", "JPN")
    if not seed.get("unity_ver"):
        seed["unity_ver"] = os.environ.get("SWEEPY_DEFAULT_UNITY_VER", "2022.3.62f2")
    return seed


def refresh_reusable_auth_headlessly(req):
    """Rebuild a reusable auth profile from Steam credentials without opening the game client."""
    from uma_api.client import UmaClient, get_ticket

    global pending_game_auth_config

    has_form_creds = bool(req and req.username and req.password)
    steam_app_id = str(getattr(req, "steam_app_id", "") or APP_ID).strip() or APP_ID
    if has_form_creds:
        sid, tkt = get_ticket(req.username, req.password, getattr(req, "code", ""), appid=steam_app_id)
    elif req and req.steam_id and req.steam_session_ticket:
        sid = str(req.steam_id or "").strip()
        tkt = str(req.steam_session_ticket or "").strip()
    else:
        raise Exception("Steam username/password is required for clientless auth refresh.")

    trace_api = os.environ.get("SWEEPY_TRACE_API", "1").strip().lower() not in {"0", "false", "no"}
    username_seed = getattr(req, "username", "")
    password_seed = getattr(req, "password", "")
    seed = best_known_headless_auth_seed(sid)
    existing_cfg = reusable_auth_config_for_steam_id(sid, require_fresh=False)
    req_seed_cfg = getattr(req, "reusable_seed_config", None)
    if not existing_cfg and isinstance(req_seed_cfg, dict) and has_fresh_auth_config(req_seed_cfg):
        existing_cfg = dict(req_seed_cfg)
    attempt_errors = []

    def _run(cfg, reason):
        client = attach_turn_delay(UmaClient(cfg, trace_enabled=trace_api))
        client._sweepy_auth_config = dict(cfg)
        try:
            res = client.login()
            if not res:
                raise Exception(f"{reason} auth refresh failed")
            resolved_cfg = client_dev_session_config(client) or dict(cfg)
            resolved_cfg["steam_username_seed"] = username_seed
            resolved_cfg["steam_password_seed"] = password_seed
            client._sweepy_auth_config = dict(resolved_cfg)
            pending_game_auth_config = dict(resolved_cfg)
            save_reusable_auth_profile(resolved_cfg, reason)
            return resolved_cfg
        finally:
            try:
                session = getattr(client, "session", None)
                if session is not None:
                    session.close()
            except Exception:
                pass

    if existing_cfg:
        cfg = dict(existing_cfg)
        cfg.update(seed)
        cfg.update({
            "steam_id": sid,
            "steam_session_ticket": tkt,
            "steam_app_id": steam_app_id,
            "steam_username_seed": username_seed,
            "steam_password_seed": password_seed,
        })
        try:
            return _run(cfg, "headless_refresh_existing")
        except Exception as exc:
            if is_client_version_stale_error(exc):
                raise RuntimeError(client_version_stale_detail(exc)) from exc
            attempt_errors.append(exc)
            if os.environ.get("SWEEPY_AUTH_ALLOW_SIGNUP_AFTER_EXISTING_FAILURE", "").strip().lower() not in {"1", "true", "yes"}:
                if "501" in str(exc) or "394" in str(exc):
                    invalidate_reusable_auth_profile(sid, "server rejected cached game auth during headless refresh")
                raise Exception(
                    "Headless auth refresh failed. The cached reusable auth for this Steam account was rejected by the game server. "
                    "Sweepy invalidated that cached reusable auth profile so future attempts will not replay the same rejected identity. "
                    "Sweepy will not call tool/signup for an existing game profile because that path is expected to return 394 and cannot repair stale auth. "
                    "Refresh auth once from the current game client, then retry. "
                    f"Existing auth retry error: {redact_sensitive_error_text(exc)}"
                )

    cfg = dict(seed)
    cfg.update({
        "steam_id": sid,
        "steam_session_ticket": tkt,
        "steam_app_id": steam_app_id,
        "steam_username_seed": username_seed,
        "steam_password_seed": password_seed,
    })
    if not has_form_creds:
        raise Exception(
            "Headless auth refresh cannot bootstrap this account from only a cached Steam ticket because no reusable game auth identity is cached. "
            "Open the current game client once and use Refresh Auth so Sweepy can cache viewer_id/auth_key/udid for this Steam account."
        )
    if not str(cfg.get("app_ver") or "").strip() or not str(cfg.get("res_ver") or "").strip():
        raise Exception(
            "No locally cached APP-VER / RES-VER is available for headless auth refresh. "
            "Set SWEEPY_DEFAULT_APP_VER and SWEEPY_DEFAULT_RES_VER, or use the old game-client capture fallback once."
        )
    try:
        return _run(cfg, "headless_refresh_signup")
    except Exception as exc:
        if is_client_version_stale_error(exc):
            raise RuntimeError(client_version_stale_detail(exc)) from exc
        msg = str(exc)
        if "394 on tool/signup" in msg or "API error 394 on tool/signup" in msg:
            if existing_cfg:
                prior = f" Existing auth retry also failed: {attempt_errors[-1]}" if attempt_errors else ""
                raise Exception(
                    "Headless auth refresh failed. The account-specific retry did not recover the session, and signup fallback was rejected with 394."
                    + prior
                )
            raise Exception(
                "Headless auth refresh could not bootstrap this Steam account from scratch because tool/signup returned 394. "
                "That usually means the Steam account already has a game profile but Sweepy has no reusable auth cached for it yet, "
                "so one game-client capture is still required once."
            )
        if attempt_errors:
            raise Exception(f"Headless auth refresh failed. Existing auth retry error: {attempt_errors[-1]}. Signup fallback error: {exc}")
        raise


def _headless_refresh_request_from_cfg(cfg):
    cfg = dict(cfg or {})
    steam_id = str(cfg.get("steam_id") or "").strip()
    steam_ticket = str(cfg.get("steam_session_ticket") or cfg.get("steam_ticket") or "").strip()
    if not steam_id or not steam_ticket:
        return None
    return SimpleNamespace(
        steam_id=steam_id,
        steam_session_ticket=steam_ticket,
        username=str(cfg.get("steam_username_seed") or cfg.get("username") or "").strip(),
        password=str(cfg.get("steam_password_seed") or "").strip(),
        code="",
        steam_app_id=str(cfg.get("steam_app_id") or APP_ID).strip(),
        reusable_seed_config=cfg,
    )


def _authenticated_client_from_cfg(cfg, *, max_retries=3):
    trace_api = os.environ.get("SWEEPY_TRACE_API", "1").strip().lower() not in {"0", "false", "no"}
    client = attach_turn_delay(UmaClient(cfg, trace_enabled=trace_api))
    client._sweepy_auth_config = dict(cfg)
    result = client.login(max_retries=max_retries)
    return client, result


def rebuild_reusable_auth_from_cached_ticket(cfg):
    req = _headless_refresh_request_from_cfg(cfg)
    if not req:
        raise Exception("No cached Steam ticket is available for automatic reusable-auth rebuild.")
    refreshed_cfg = refresh_reusable_auth_headlessly(req)
    client, result = _authenticated_client_from_cfg(refreshed_cfg, max_retries=1)
    return refreshed_cfg, client, result


def restore_dev_session_cache():
    global active_client, active_account, active_dashboard_data, active_start_state, active_start_debug, active_parent_cards, active_parent_rank_points, active_selection, raw_load_index_response, pending_game_auth_config, seen_trained_chara_ids, most_recent_trained_chara_id
    if not dev_session_cache_enabled():
        return False
    path = dev_session_cache_path()
    if not path.exists():
        return False
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as exc:
        print(f"dev session cache read failed: {exc}", flush=True)
        return False

    saved_at = float(payload.get("saved_at") or 0)
    ttl = int(os.environ.get("SWEEPY_DEV_SESSION_TTL_SEC", str(24 * 3600)))
    if ttl > 0 and saved_at and time.time() - saved_at > ttl:
        print("dev session cache expired; fresh auth capture required", flush=True)
        clear_dev_session_cache()
        return False

    cfg = dict(payload.get("client_config") or {})
    if not has_fresh_auth_config(cfg) or not cfg.get("steam_id") or not cfg.get("steam_session_ticket"):
        print("dev session cache is missing reusable auth; fresh auth capture required", flush=True)
        clear_dev_session_cache()
        return False

    try:
        reset_loop_state()
        active_client = None
        active_account = None
        active_dashboard_data = payload.get("dashboard") if isinstance(payload.get("dashboard"), dict) else None
        active_start_state = payload.get("start_state") if isinstance(payload.get("start_state"), dict) else {}
        active_start_debug = payload.get("start_debug") if isinstance(payload.get("start_debug"), dict) else {}
        active_parent_cards = {}
        active_parent_rank_points = {}
        active_selection = payload.get("selection") if isinstance(payload.get("selection"), dict) else empty_selection()
        raw_load_index_response = None
        pending_game_auth_config = {}
        seen_trained_chara_ids = None
        most_recent_trained_chara_id = 0

        trace_api = os.environ.get("SWEEPY_TRACE_API", "1").strip().lower() not in {"0", "false", "no"}
        client = attach_turn_delay(UmaClient(cfg, trace_enabled=trace_api))
        client._sweepy_auth_config = dict(cfg)
        res = client.login(max_retries=1)
        active_client = client

        load_data = res.get("data", {})
        career_data = None
        if load_data.get("single_mode_chara_light") or load_data.get("single_mode_chara"):
            try:
                career_res = client.load_career()
                career_data = career_res.get("data")
            except Exception:
                pass
        dashboard = build_dashboard_data(load_data, career_data, preserve_friends=bool(active_dashboard_data))
        dashboard["selection"] = reconcile_active_selection()
        dashboard["loop"] = loop_snapshot()
        dashboard["success"] = True
        active_dashboard_data = dashboard
        save_reusable_auth_profile(cfg, "restore")
        persist_dev_session_cache("restore")
        print("restored backend session from dev cache", flush=True)
        return True
    except Exception as exc:
        print(f"dev session restore failed: {exc}", flush=True)
        if is_client_version_stale_error(exc):
            # Terminal: no session retry will fix a client-version mismatch.
            # Surface the actionable detail and bail instead of looping the
            # auth-refresh path that fed the observed retry storm.
            print(client_version_stale_detail(exc), flush=True)
            active_client = None
            active_account = None
            active_dashboard_data = None
            active_start_state = {}
            active_start_debug = {}
            active_parent_cards = {}
            active_parent_rank_points = {}
            active_selection = empty_selection()
            return False
        if is_recoverable_session_error(exc):
            try:
                refreshed_cfg, refreshed_client, res = rebuild_reusable_auth_from_cached_ticket(cfg)
                active_client = refreshed_client
                load_data = res.get("data", {})
                career_data = None
                if load_data.get("single_mode_chara_light") or load_data.get("single_mode_chara"):
                    try:
                        career_res = refreshed_client.load_career()
                        career_data = career_res.get("data")
                    except Exception:
                        pass
                dashboard = build_dashboard_data(load_data, career_data, preserve_friends=bool(active_dashboard_data))
                dashboard["selection"] = reconcile_active_selection()
                dashboard["loop"] = loop_snapshot()
                dashboard["success"] = True
                active_dashboard_data = dashboard
                save_reusable_auth_profile(refreshed_cfg, "restore_auto_refresh")
                persist_dev_session_cache("restore_auto_refresh")
                print("restored backend session after automatic reusable-auth refresh", flush=True)
                return True
            except Exception as refresh_exc:
                print(f"dev session auto-refresh failed: {refresh_exc}", flush=True)
                clear_dev_session_cache()
                print("dev session cache was rejected by the game server; cleared stale cached auth", flush=True)
        active_client = None
        active_account = None
        active_dashboard_data = None
        active_start_state = {}
        active_start_debug = {}
        active_parent_cards = {}
        active_parent_rank_points = {}
        active_selection = empty_selection()
        return False


def iter_backend_code_files():
    roots = [
        base_dir / "main.py",
        base_dir / "career_bot",
        base_dir / "uma_api",
    ]
    skip_dirs = {"__pycache__", ".git", "node_modules", "uma_runtime"}
    for root in roots:
        if root.is_file():
            yield root
            continue
        if not root.exists():
            continue
        for path in root.rglob("*.py"):
            if any(part in skip_dirs for part in path.parts):
                continue
            yield path


def backend_code_signature():
    signature = {}
    for path in iter_backend_code_files():
        try:
            stat = path.stat()
            signature[str(path)] = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            continue
    return signature


def iter_preset_files():
    for path in preset_store.source_files():
        yield path


def preset_files_signature():
    signature = {}
    for path in iter_preset_files():
        try:
            stat = path.stat()
            signature[str(path)] = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            continue
    return signature


def hot_reload_presets():
    """Re-read every preset file from disk. If a preset's name matches the
    currently-running career, mutate its in-memory dict so the runner picks
    up the new values without restarting."""
    updated = []
    for normalized in preset_store.read_all():
        name = normalized.get("name") or ""
        effective = resolve_effective_preset(name, base_preset=normalized) or normalized
        if career_runner.update_active_preset(name, effective):
            updated.append(name)
    if updated:
        print(f"preset hot-reloaded into running career: {', '.join(updated)}", flush=True)
    return updated


def _restart_python_executable():
    candidates = [
        os.environ.get("SWEEPY_RESTART_PYTHON", ""),
        sys.executable,
        str(base_dir / ".venv" / "Scripts" / "python.exe"),
        str(base_dir / ".venv" / "bin" / "python"),
        shutil.which("python"),
        shutil.which("py"),
    ]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            path = Path(str(candidate).strip().strip('"'))
            if path.is_file():
                return str(path.resolve())
        except OSError:
            pass
        resolved = shutil.which(str(candidate).strip().strip('"'))
        if resolved:
            try:
                path = Path(resolved)
                if path.is_file():
                    return str(path.resolve())
            except OSError:
                continue
    return sys.executable or "python"


def _explicit_restart_script():
    configured = str(os.environ.get("SWEEPY_RESTART_SCRIPT") or "").strip().strip('"')
    if not configured:
        return ""
    path = Path(configured)
    if path.suffix.lower() != ".py":
        return ""
    if not path.is_absolute():
        path = base_dir / path
    try:
        if path.exists():
            return str(path.resolve())
    except OSError:
        return ""
    return ""


def _restart_script_path():
    """Absolute path to the main.py that should be relaunched on restart.

    The whole point is that the server must find ITSELF on any machine,
    regardless of how the download was extracted. Earlier logic scanned
    sys.argv and could hand os.execv a *directory* (e.g. a double-nested
    ``project-shaboing-main\\project-shaboing-main`` ZIP layout), producing
    ``can't find '__main__' module in '<dir>'``. We avoid that entirely by
    trusting the running module's own location.

    Resolution order, most authoritative first:
      1. SWEEPY_RESTART_SCRIPT, only if it points at an existing ``.py``
         file (explicit operator/launcher override).
      2. ``__file__`` — the path to THIS running main.py. Immune to folder
         renames, ZIP nesting, the process CWD, and directory-as-argv.
      3. ``base_dir / "main.py"`` as a final fallback.
    Every branch is validated to be an existing ``.py`` file before use,
    so os.execv never receives a directory or a phantom path.
    """
    candidates = []
    explicit = _explicit_restart_script()
    if explicit:
        candidates.append(Path(explicit))
    try:
        candidates.append(Path(__file__).resolve())
    except (NameError, OSError):
        pass
    candidates.append(base_dir / "main.py")

    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except OSError:
            continue
        if resolved.is_file() and resolved.suffix.lower() == ".py":
            return str(resolved)
    return None


def build_exec_args():
    python_exe = _restart_python_executable()
    script = _restart_script_path()
    if not script:
        raise FileNotFoundError(
            "backend restart cannot locate a main.py to relaunch "
            f"(checked SWEEPY_RESTART_SCRIPT, __file__, and {base_dir / 'main.py'})"
        )
    return [python_exe, script]


# Exit code a supervised process uses to ask its launcher to relaunch it.
# The .bat launchers (and any supervisor) loop while the process exits with
# this code. Chosen to avoid clashing with common codes (0 success, 1/2
# errors, 130 SIGINT, etc.).
RESTART_EXIT_CODE = 73


def _supervised_restart_enabled():
    """True when a launcher supervises this process and relaunches it on
    RESTART_EXIT_CODE. Set by run_sweepy.bat / setup_and_run_sweepy.bat via
    SWEEPY_SUPERVISED=1. When supervised we exit with the sentinel code for a
    clean single-console restart instead of the Windows os.execv spawn+exit,
    which orphaned the new server and made the launcher fall through to its
    tail 'pause' ('Press any key to continue')."""
    return str(os.environ.get("SWEEPY_SUPERVISED") or "").strip().lower() in {"1", "true", "yes", "on"}


def _execv_argv(args):
    """Quote argv entries containing spaces for the Windows os.execv path.

    The Windows C runtime's exec/spawn family joins the argv list into a
    single command-line string and does NOT quote the pieces, so an
    argument containing a space — e.g. a script path under
    ``project-shaboing-main (1)`` — gets split and the relaunched python
    receives a truncated path, producing ``can't find '__main__' module
    in '<prefix-before-the-space>'``. Wrapping space-containing arguments
    in double quotes makes the CRT pass them as one argument; the child's
    CommandLineToArgvW strips the quotes again. POSIX execv takes a real
    argv array (no shell re-parsing), so it is left untouched. Every path
    we pass is a validated ``.py`` file (never ends in a backslash), so a
    plain double-quote wrap is safe — no trailing-backslash escaping edge
    case to worry about.
    """
    if os.name != "nt":
        return list(args)
    quoted = []
    for arg in args:
        text = str(arg)
        if " " in text and not (text.startswith('"') and text.endswith('"')):
            quoted.append(f'"{text}"')
        else:
            quoted.append(text)
    return quoted


def restart_backend_process(reason):
    persist_dev_session_cache(reason)
    print(f"backend dev reload: restarting process ({reason})", flush=True)
    time.sleep(0.25)
    if _supervised_restart_enabled():
        # The launcher relaunches us on RESTART_EXIT_CODE. Exit cleanly in
        # place — same console, no orphaned process, and no spurious launcher
        # 'pause'. This is the preferred path on Windows, where os.execv is
        # not a true in-place replace (it spawns a new process and exits the
        # original, which is what made run_sweepy.bat hit 'Press any key').
        print(
            f"backend restart: exiting with code {RESTART_EXIT_CODE} for launcher to relaunch with updated code",
            flush=True,
        )
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(RESTART_EXIT_CODE)
    try:
        args = build_exec_args()
    except FileNotFoundError as exc:
        dev_reloader_state["restart_requested"] = False
        print(f"backend restart aborted: {exc}", flush=True)
        return
    # os.execv inherits the current working directory. Force it to the
    # project root so the relaunched interpreter and every relative path
    # the app uses resolve correctly regardless of where the server was
    # originally started from.
    try:
        os.chdir(base_dir)
    except OSError as exc:
        print(f"backend restart: could not chdir to {base_dir}: {exc}", flush=True)
    program = args[0]
    exec_argv = _execv_argv(args)
    # Plain (non-repr) print so backslashes show as single \ and the real
    # quoted command is visible.
    print(f"backend restart exec: python={program} script={args[1] if len(args) > 1 else ''}", flush=True)
    try:
        os.execv(program, exec_argv)
    except OSError as exc:
        # execv only returns on failure. Surface a clear message and clear
        # the in-flight flag so the operator can retry instead of being
        # stuck with a server that thinks a restart is already queued.
        dev_reloader_state["restart_requested"] = False
        print(
            f"backend restart failed to exec {program!r} with {exec_argv}: {exc}. "
            f"Server left running on old code; click REFRESH BACKEND to retry.",
            flush=True,
        )


def schedule_backend_restart(reason, delay_sec=0.35):
    if dev_reloader_state.get("restart_requested"):
        return False
    dev_reloader_state["restart_requested"] = True
    dev_reloader_state["pending_restart"] = False
    dev_reloader_state["pending_restart_gate"] = ""
    dev_reloader_state["pending_restart_release"] = ""

    def _restart():
        try:
            time.sleep(max(0.0, float(delay_sec or 0.0)))
            restart_backend_process(reason)
        except Exception as exc:
            dev_reloader_state["restart_requested"] = False
            print(f"backend manual restart failed: {exc}", flush=True)

    thread = threading.Thread(target=_restart, name="sweepy-manual-restart", daemon=True)
    thread.start()
    return True


def defer_backend_restart_until_manual_stop():
    dev_reloader_state["pending_restart"] = True
    dev_reloader_state["pending_restart_gate"] = "manual_stop_only"
    dev_reloader_state["pending_restart_release"] = ""


def clear_deferred_backend_restart_release():
    if not dev_reloader_state.get("pending_restart"):
        dev_reloader_state["pending_restart_gate"] = ""
    dev_reloader_state["pending_restart_release"] = ""


def release_deferred_backend_restart_on_manual_stop():
    if dev_reloader_state.get("pending_restart") and dev_reloader_state.get("pending_restart_gate") == "manual_stop_only":
        dev_reloader_state["pending_restart_release"] = "manual_stop"


def deferred_backend_restart_release_reason():
    if not dev_reloader_state.get("pending_restart"):
        return ""
    released = str(dev_reloader_state.get("pending_restart_release") or "").strip()
    if released:
        return released
    return ""


def runner_is_active():
    try:
        return bool(career_runner.snapshot().get("running") or loop_snapshot().get("active"))
    except Exception:
        return False


def backend_dev_reloader_loop():
    signature = backend_code_signature()
    preset_signature = preset_files_signature()
    while True:
        time.sleep(1.5)
        try:
            # 1) Preset JSON changes — hot-reload into the running career
            #    without a process restart. Mutates the runner's in-memory
            #    preset dict in place so the strategy picks up new values.
            current_presets = preset_files_signature()
            if current_presets != preset_signature:
                preset_signature = current_presets
                try:
                    hot_reload_presets()
                except Exception as exc:
                    print(f"preset hot-reload error: {exc}", flush=True)

            # 2) Python code changes — NEVER auto-restart. Mark a pending
            #    backend refresh and wait for explicit user intent:
            #    - STOP button during/after a run
            #    - REFRESH BACKEND button
            current = backend_code_signature()
            if current != signature:
                signature = current
                dev_reloader_state["last_change"] = time.strftime("%Y-%m-%d %H:%M:%S")
                if not dev_reloader_state.get("pending_restart"):
                    print("backend code changed; refresh is pending until you explicitly stop the runner or click REFRESH BACKEND", flush=True)
                defer_backend_restart_until_manual_stop()
                persist_dev_session_cache("backend_reload_deferred")
                continue

            if dev_reloader_state.get("pending_restart") and not runner_is_active():
                release_reason = deferred_backend_restart_release_reason()
                if release_reason:
                    dev_reloader_state["pending_restart"] = False
                    dev_reloader_state["pending_restart_gate"] = ""
                    dev_reloader_state["pending_restart_release"] = ""
                    restart_backend_process(f"deferred_backend_code_changed_{release_reason}")
        except Exception as exc:
            print(f"backend dev reloader error: {exc}", flush=True)


def start_backend_dev_reloader():
    if not backend_dev_reload_enabled():
        print("backend dev reload disabled via SWEEPY_DEV_RELOAD", flush=True)
        return
    if dev_reloader_state.get("thread"):
        return
    thread = threading.Thread(target=backend_dev_reloader_loop, name="sweepy-dev-reloader", daemon=True)
    dev_reloader_state["thread"] = thread
    thread.start()
    print("backend dev reload enabled; watching Python files", flush=True)


if chara_path.exists():
    with open(chara_path, 'r', encoding='utf-8') as f:
        chara_map = json.load(f)
if support_path.exists():
    with open(support_path, 'r', encoding='utf-8') as f:
        support_map = json.load(f)

def display_support_type(value):
    return {
        "Friends": "Pal",
        "Wisdom": "Wit"
    }.get(value, value)


def normalize_turn_delay(min_value, max_value, disabled=False):
    left = max(0.0, float(min_value or 0.0))
    right = max(0.0, float(max_value or 0.0))
    if left > right:
        right = left
    if disabled:
        left = 0.0
        right = 0.0
    return left, right, bool(disabled)

def set_turn_delay(min_value, max_value, disabled=False):
    global turn_delay_min_sec, turn_delay_max_sec, turn_delay_restore_min_sec, turn_delay_restore_max_sec, turn_delay_disabled
    next_min, next_max, next_disabled = normalize_turn_delay(min_value, max_value, disabled)
    if not next_disabled:
        turn_delay_restore_min_sec = next_min
        turn_delay_restore_max_sec = next_max
    turn_delay_min_sec = next_min
    turn_delay_max_sec = next_max
    turn_delay_disabled = next_disabled
    return get_turn_delay()

def get_turn_delay():
    return {
        "success": True,
        "min": turn_delay_min_sec,
        "max": turn_delay_max_sec,
        "restore_min": turn_delay_restore_min_sec,
        "restore_max": turn_delay_restore_max_sec,
        "disabled": turn_delay_disabled
    }

def wait_for_game_turn_delay(delay_type="turn"):
    roll = random.uniform(turn_delay_min_sec, turn_delay_max_sec)
    
    if delay_type == "api":
        multiplier = 0.2
        label = "API"
    elif delay_type == "complex":
        multiplier = 2.0
        label = "COMPLEX"
    else:
        multiplier = 1.0
        label = "TURN"
        
    seconds = roll * multiplier
    if seconds <= 0:
        return
        
    print(f"{label}: {seconds:.3f}s", flush=True)
    time.sleep(seconds)

def attach_turn_delay(client):
    if getattr(client, "_turn_delay_wrapped", False):
        return client
    original_call = client.call
    def delayed_call(ep, args=None, **kwargs):
        wait_for_game_turn_delay(delay_type="api")
        result = original_call(ep, args, **kwargs)
        try:
            stored_cfg = getattr(client, "_sweepy_auth_config", None)
            if isinstance(stored_cfg, dict):
                current_app_ver = str(getattr(client, "app_ver", "") or "").strip()
                current_res_ver = str(getattr(client, "res_ver", "") or "").strip()
                current_steam_app_id = str(getattr(client, "steam_app_id", "") or APP_ID).strip() or APP_ID
                changed = False
                if current_app_ver and current_app_ver != str(stored_cfg.get("app_ver") or "").strip():
                    stored_cfg["app_ver"] = current_app_ver
                    changed = True
                if current_res_ver and current_res_ver != str(stored_cfg.get("res_ver") or "").strip():
                    stored_cfg["res_ver"] = current_res_ver
                    changed = True
                if current_steam_app_id and current_steam_app_id != str(stored_cfg.get("steam_app_id") or "").strip():
                    stored_cfg["steam_app_id"] = current_steam_app_id
                    changed = True
                if changed:
                    client._sweepy_auth_config = dict(stored_cfg)
                    save_reusable_auth_profile(client_dev_session_config(client), "version_metadata_refresh")
                    persist_dev_session_cache("version_metadata_refresh")
        except Exception as exc:
            print(f"version metadata persist ignored for {ep}: {redact_sensitive_error_text(exc)}", flush=True)
        try:
            sync_game_data_from_api_response(ep, result, source="client.call")
        except Exception as exc:
            print(f"state sync ignored for {ep}: {redact_sensitive_error_text(exc)}", flush=True)
        return result
    client.call = delayed_call
    client.wait_turn_delay = lambda: wait_for_game_turn_delay(delay_type="turn")
    client.wait_complex_delay = lambda: wait_for_game_turn_delay(delay_type="complex")
    client._turn_delay_wrapped = True
    return client



def update_start_state(data):
    global active_start_state
    if not data:
        return
    with state_sync_lock:
        if data.get('tp_info'):
            tp_info = dict(data.get('tp_info'))
            tp_info['_synced_at'] = int(time.time())
            tp_info['server_current_tp'] = int(tp_info.get('current_tp') or tp_info.get('current') or 0)
            active_start_state['tp_info'] = tp_info
        if isinstance(data.get('coin_info'), dict):
            active_start_state['coin_info'] = dict(data.get('coin_info') or {})
        item_list = data.get('item_list') or data.get('user_item_array')
        if isinstance(item_list, list) and item_list:
            active_start_state['item_list'] = [dict(item) for item in item_list if isinstance(item, dict)]
            active_start_state['current_money'] = get_item_count(item_list, 59)
        if isinstance(data.get('reward_summary_info'), dict):
            apply_reward_summary_to_start_state(data.get('reward_summary_info'))
        if isinstance(data.get('use_item_info'), (dict, list)):
            apply_use_item_info_to_start_state(data.get('use_item_info'))
        succession_rank_point = data.get('succession_rank_point', data.get('current_succession_rank_point'))
        if succession_rank_point is not None:
            active_start_state['succession_rank_point'] = int(succession_rank_point or 0)
        elif isinstance(item_list, list):
            active_start_state.pop('succession_rank_point', None)


def normalize_friend_cards(data):
    source = 'refresh'
    friend_data = data.get('friend_support_card_data')
    if friend_data:
        source = 'initial'
        summaries = friend_data.get('summary_user_info_array', [])
        support_cards = friend_data.get('support_card_data_array', [])
    else:
        summaries = data.get('summary_user_info_array', [])
        support_cards = data.get('support_card_data_array', [])

    support_by_key = {}
    for sc in support_cards or []:
        key = (sc.get('viewer_id'), sc.get('support_card_id'))
        support_by_key[key] = sc

    friends = []
    exclude_viewer_ids = []
    seen = set()
    for info in summaries or []:
        viewer_id = info.get('viewer_id')
        support_card_id = info.get('support_card_id')
        if not viewer_id or not support_card_id:
            continue
        key = (viewer_id, support_card_id)
        if key in seen:
            continue
        seen.add(key)
        exclude_viewer_ids.append(viewer_id)
        card_data = support_by_key.get(key) or info.get('user_support_card') or {}
        support_info = support_map.get(str(support_card_id), {})
        friends.append({
            'viewer_id': viewer_id,
            'name': info.get('name', ''),
            'support_card_id': support_card_id,
            'support_name': support_info.get('name', f"Unknown ({support_card_id})"),
            'rarity': support_info.get('rarity', '?'),
            'type': display_support_type(support_info.get('type', 'Unknown')),
            'exp': card_data.get('exp', info.get('user_support_card', {}).get('exp')),
            'limit_break_count': card_data.get('limit_break_count', info.get('user_support_card', {}).get('limit_break_count')),
            'favorite_flag': card_data.get('favorite_flag', 0),
            'friend_state': info.get('friend_state', 0)
        })
    return friends, exclude_viewer_ids, source


def normalize_friend_search_profile(data, target_viewer_id=0):
    target_viewer_id = int(target_viewer_id or 0)
    rows = []
    summary = data.get("user_info_summary")
    if isinstance(summary, dict):
        rows.append(summary)
    for key in (
        "user_info_summary_list",
        "search_user_info_summary_list",
        "summary_user_info_array",
        "follower_info_summary_list",
    ):
        values = data.get(key)
        if isinstance(values, list):
            rows.extend([row for row in values if isinstance(row, dict)])

    chosen = None
    if target_viewer_id:
        for row in rows:
            if int(row.get("viewer_id") or row.get("friend_viewer_id") or 0) == target_viewer_id:
                chosen = row
                break
    if chosen is None and rows:
        chosen = rows[0]
    if not chosen:
        return None

    viewer_id = int(chosen.get("viewer_id") or chosen.get("friend_viewer_id") or 0)
    support_card_id = int(chosen.get("support_card_id") or chosen.get("user_support_card", {}).get("support_card_id") or 0)
    support_card = chosen.get("user_support_card") or {}
    support_info = support_map.get(str(support_card_id), {})
    leader = chosen.get("user_trained_chara") or {}
    circle_info = chosen.get("circle_info") or {}
    return {
        "viewer_id": viewer_id,
        "name": chosen.get("name", ""),
        "comment": chosen.get("comment", ""),
        "support_card_id": support_card_id,
        "support_name": support_info.get("name", f"Unknown ({support_card_id})") if support_card_id else "",
        "support_type": display_support_type(support_info.get("type", "Unknown")) if support_card_id else "",
        "support_rarity": support_info.get("rarity", "?") if support_card_id else "?",
        "limit_break_count": support_card.get("limit_break_count"),
        "friend_state": int(chosen.get("friend_state") or 0),
        "fan": int(chosen.get("fan") or 0),
        "rank_score": int(chosen.get("rank_score") or 0),
        "team_evaluation_point": int(chosen.get("team_evaluation_point") or 0),
        "team_stadium_win_count": int(chosen.get("team_stadium_win_count") or 0),
        "single_mode_play_count": int(chosen.get("single_mode_play_count") or 0),
        "last_login_time": chosen.get("last_login_time", ""),
        "leader_card_id": int(leader.get("card_id") or chosen.get("leader_chara_dress_id") or 0),
        "leader_name": chara_map.get(str(leader.get("card_id") or chosen.get("leader_chara_dress_id") or 0), ""),
        "leader_rank_score": int(leader.get("rank_score") or 0),
        "leader_rank": int(leader.get("rank") or 0),
        "circle_name": circle_info.get("name", ""),
        "circle_id": int(circle_info.get("circle_id") or 0),
    }


def _int_or_default(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return int(default or 0)


def compute_follow_quota(client, following_count=None):
    cached = getattr(client, "cached_load_data", None) or {}
    common = cached.get("common_define") or {}
    base = _int_or_default(common.get("max_follow_num"), 20)
    bonus = max(0, _int_or_default(cached.get("bonus_follow_num", common.get("bonus_follow_num")), 0))
    maximum = max(1, base + bonus)
    used = max(0, _int_or_default(following_count, 0))
    return {
        "used": used,
        "max": maximum,
        "remaining": max(0, maximum - used),
    }


def normalize_following_friend_list(data, support_rows=None):
    data = data or {}
    support_rows = support_rows or []
    support_lookup = {
        (str(row.get("viewer_id") or ""), str(row.get("support_card_id") or "")): row
        for row in support_rows
        if row
    }
    follow_lookup = {}
    for row in data.get("friend_list") or []:
        if not isinstance(row, dict):
            continue
        viewer_id = _int_or_default(row.get("friend_viewer_id", row.get("viewer_id")))
        if viewer_id <= 0:
            continue
        state = _int_or_default(row.get("state", row.get("friend_state")))
        if state > 0:
            follow_lookup[viewer_id] = row

    summaries = [row for row in (data.get("user_info_summary_list") or []) if isinstance(row, dict)]
    result = []
    seen = set()
    for summary in summaries:
        viewer_id = _int_or_default(summary.get("viewer_id", summary.get("friend_viewer_id")))
        if viewer_id <= 0 or viewer_id in seen:
            continue
        if follow_lookup and viewer_id not in follow_lookup:
            continue
        if not follow_lookup and _int_or_default(summary.get("friend_state")) <= 0:
            continue
        seen.add(viewer_id)
        follow_meta = follow_lookup.get(viewer_id) or {}
        support_card = summary.get("user_support_card") or {}
        support_card_id = _int_or_default(summary.get("support_card_id", support_card.get("support_card_id")))
        support_info = support_map.get(str(support_card_id), {})
        selected_support = support_lookup.get((str(viewer_id), str(support_card_id))) or {}
        leader = summary.get("user_trained_chara") or {}
        circle_info = summary.get("circle_info") or {}
        circle_user = summary.get("circle_user") or {}
        leader_card_id = _int_or_default(leader.get("card_id", summary.get("leader_chara_dress_id")))
        result.append({
            "viewer_id": viewer_id,
            "name": summary.get("name", ""),
            "honor_id": _int_or_default(summary.get("honor_id")),
            "comment": summary.get("comment", ""),
            "last_login_time": summary.get("last_login_time", ""),
            "follow_time": follow_meta.get("follow_time", ""),
            "friend_state": _int_or_default(summary.get("friend_state", follow_meta.get("state"))),
            "support_card_id": support_card_id,
            "support_name": support_info.get("name", f"Unknown ({support_card_id})") if support_card_id else "",
            "support_type": display_support_type(support_info.get("type", "Unknown")) if support_card_id else "",
            "support_rarity": support_info.get("rarity", "?") if support_card_id else "?",
            "limit_break_count": selected_support.get("limit_break_count", support_card.get("limit_break_count")),
            "exp": selected_support.get("exp", support_card.get("exp")),
            "fan": _int_or_default(summary.get("fan")),
            "rank_score": _int_or_default(summary.get("rank_score")),
            "team_stadium_win_count": _int_or_default(summary.get("team_stadium_win_count")),
            "single_mode_play_count": _int_or_default(summary.get("single_mode_play_count")),
            "team_evaluation_point": _int_or_default(summary.get("team_evaluation_point")),
            "leader_card_id": leader_card_id,
            "leader_name": chara_map.get(str(leader_card_id), f"Unknown ({leader_card_id})") if leader_card_id else "",
            "leader_rank_score": _int_or_default(leader.get("rank_score")),
            "leader_rank": _int_or_default(leader.get("rank")),
            "leader_registered_at": leader.get("register_time", ""),
            "circle_name": circle_info.get("name", ""),
            "circle_id": _int_or_default(circle_info.get("circle_id")),
            "circle_membership": _int_or_default(circle_user.get("membership")),
            "circle_join_time": circle_user.get("join_time", ""),
            "available_support": bool(selected_support),
        })

    return result


def normalize_friend_umas(data):
    """Extract borrowable umas (guest legacies) from a pre_single_mode/index response.
    Mirrors normalize_friend_cards but pulls from succession_trained_chara_data instead
    of friend_support_card_data. Each output row carries the viewer_id and
    trained_chara_id needed to populate `rental_succession_trained_chara` in start_career.
    """
    sct_data = data.get('succession_trained_chara_data') or {}
    summaries = sct_data.get('summary_user_info_array') or []
    chara_array = sct_data.get('succession_trained_chara_array') or []
    chara_by_key = {}
    for entry in chara_array:
        key = (entry.get('viewer_id'), entry.get('trained_chara_id'))
        chara_by_key[key] = entry
    umas = []
    seen = set()
    for info in summaries:
        viewer_id = info.get('viewer_id')
        utc = info.get('user_trained_chara') or {}
        trained_chara_id = utc.get('trained_chara_id') or info.get('partner_chara_id')
        if not viewer_id or not trained_chara_id:
            continue
        key = (viewer_id, trained_chara_id)
        if key in seen:
            continue
        seen.add(key)
        chara_entry = chara_by_key.get(key) or utc or {}
        card_id = chara_entry.get('card_id') or utc.get('card_id')
        chara_name = chara_map.get(str(card_id), f"Unknown ({card_id})")
        skill_rows = get_skill_rows(chara_entry.get('skill_array') or [])
        estimated_skill_points = get_estimated_skill_points(skill_rows)
        stats = get_trained_chara_stats(chara_entry)
        stats["estimated_skill_points"] = estimated_skill_points
        umas.append({
            'viewer_id': viewer_id,
            'trained_chara_id': trained_chara_id,
            'trainer_name': info.get('name', ''),
            'trainer_comment': info.get('comment', ''),
            'card_id': card_id,
            'chara_name': chara_name,
            'rarity': chara_entry.get('rarity'),
            'talent_level': chara_entry.get('talent_level'),
            'rank': chara_entry.get('rank') or utc.get('rank'),
            'chara_grade': chara_entry.get('chara_grade'),
            'rank_score': chara_entry.get('rank_score'),
            'score': chara_entry.get('rank_score') or utc.get('rank_score'),
            'fans': chara_entry.get('fans'),
            'wins': chara_entry.get('wins'),
            'succession_num': chara_entry.get('succession_num'),
            'stats': stats,
            'skills': skill_rows,
            'skill_array': chara_entry.get('skill_array') or [],
            'estimated_skill_points': estimated_skill_points,
            'speed': chara_entry.get('speed'),
            'stamina': chara_entry.get('stamina'),
            'power': chara_entry.get('power'),
            'guts': chara_entry.get('guts'),
            'wit': chara_entry.get('wiz'),
            'running_style': chara_entry.get('running_style'),
            'proper_ground_turf': chara_entry.get('proper_ground_turf'),
            'proper_ground_dirt': chara_entry.get('proper_ground_dirt'),
            'proper_distance_short': chara_entry.get('proper_distance_short'),
            'proper_distance_mile': chara_entry.get('proper_distance_mile'),
            'proper_distance_middle': chara_entry.get('proper_distance_middle'),
            'proper_distance_long': chara_entry.get('proper_distance_long'),
            'proper_running_style_nige': chara_entry.get('proper_running_style_nige'),
            'proper_running_style_senko': chara_entry.get('proper_running_style_senko'),
            'proper_running_style_sashi': chara_entry.get('proper_running_style_sashi'),
            'proper_running_style_oikomi': chara_entry.get('proper_running_style_oikomi'),
            'factor_id_array': utc.get('factor_id_array') or chara_entry.get('factor_id_array') or [],
            'factors': get_factors(utc.get('factor_id_array') or chara_entry.get('factor_id_array') or [], chara_entry.get('card_id') or utc.get('card_id')),
            'tree': _build_borrow_uma_tree(chara_entry),
            # Preserve any explicit trained/created timestamps the live API exposes.
            # Not every payload includes one, so the UI still falls back to
            # trained_chara_id ordering when date fields are absent.
            'created_at': (
                chara_entry.get('created_at')
                or utc.get('created_at')
                or chara_entry.get('trained_at')
                or utc.get('trained_at')
                or chara_entry.get('created_time')
                or utc.get('created_time')
                or chara_entry.get('register_time')
                or utc.get('register_time')
            ),
            'updated_at': chara_entry.get('updated_at') or utc.get('updated_at'),
        })
    return umas


def refresh_friend_library(exclude_viewer_ids=None, *, cache_reason="friends"):
    global active_dashboard_data
    if not active_client:
        raise RuntimeError("Not logged in")

    result = client_method_with_session_recovery("pre_single_mode", exclude_viewer_ids or [])
    data = result.get('data', {})
    update_start_state(data)
    friends, next_exclude_viewer_ids, source = normalize_friend_cards(data)
    borrow_umas = normalize_friend_umas(data)
    borrow_quota = compute_borrow_quota(active_client)
    following_list = []
    follow_quota = compute_follow_quota(active_client, 0)
    friend_index_source = "unavailable"
    try:
        friend_index_result = client_method_with_session_recovery("friend_index")
        friend_index_data = (friend_index_result or {}).get("data") or {}
        following_list = normalize_following_friend_list(friend_index_data, friends)
        follow_quota = compute_follow_quota(active_client, len(following_list))
        friend_index_source = "live"
    except Exception:
        following_list = []
        follow_quota = compute_follow_quota(active_client, 0)
    deck_rows, deck_debug = find_deck_rows(data, "pre_single_mode")
    decks = apply_deck_overrides(deck_view_rows(deck_rows), (active_dashboard_data or {}).get("supports") if isinstance(active_dashboard_data, dict) else [])

    if active_dashboard_data is not None:
        active_dashboard_data["friends"] = friends
        active_dashboard_data["friendsList"] = following_list
        active_dashboard_data["friendFollowQuota"] = follow_quota
        active_dashboard_data["borrow_umas"] = borrow_umas
        active_dashboard_data["borrow_quota"] = borrow_quota
        active_dashboard_data["friendExcludeIds"] = next_exclude_viewer_ids
        active_dashboard_data["friendsLoaded"] = True
        if decks and len(decks) >= len(active_dashboard_data.get("decks", [])):
            merge_dashboard_decks(deck_rows, deck_debug)
        persist_dev_session_cache(cache_reason)

    return {
        "success": True,
        "friends": friends,
        "friends_list": following_list,
        "follow_quota": follow_quota,
        "borrow_umas": borrow_umas,
        "borrow_quota": borrow_quota,
        "exclude_viewer_ids": next_exclude_viewer_ids,
        "source": source,
        "friend_index_source": friend_index_source,
        "decks": (active_dashboard_data or {}).get("decks", decks),
        "deckDebug": active_deck_debug,
    }


def compute_borrow_quota(client):
    """Pull daily-borrow stats from the client's cached load/index response.
    The game caps daily guest-parent borrows at common_define.single_mode_trained_chara_rental_max_num (5),
    tracks used count in single_mode_rental_succession_num, and (when applicable) carries a free-borrow
    refresh timestamp in single_mode_succession_free_rental_time."""
    cached = getattr(client, "cached_load_data", None) or {}
    common = cached.get("common_define") or {}
    max_num = int(common.get("new_single_mode_trained_chara_rental_max_num") or common.get("single_mode_trained_chara_rental_max_num") or 5)
    used = int(cached.get("single_mode_rental_succession_num") or 0)
    remaining = max(0, max_num - used)
    return {
        "max": max_num,
        "used": used,
        "remaining": remaining,
        "free_rental_time": int(cached.get("single_mode_succession_free_rental_time") or 0),
    }


def _build_borrow_uma_tree(chara_entry):
    """Build the same 7-node tree shape used for owned parents (self/p1/p2/gp1-4)
    from a borrowable uma record. The succession_chara_array on borrow entries
    mirrors what owned parents carry, so the same position_id → key mapping works."""
    self_cid = chara_entry.get('card_id') or 0
    self_cid_str = str(self_cid) if self_cid else ''
    self_win_data = get_race_record_data(chara_entry)
    tree = {
        "self": {"card_id": self_cid, "name": chara_map.get(self_cid_str, f"Unknown ({self_cid})"), "factors": [], "wins": self_win_data["summary"], "win_saddle_ids": self_win_data["saddle_ids"], "win_race_ids": self_win_data["race_ids"], "race_history": self_win_data["history"]},
        "p1":   {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([]), "win_saddle_ids": [], "win_race_ids": [], "race_history": []},
        "p2":   {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([]), "win_saddle_ids": [], "win_race_ids": [], "race_history": []},
        "gp1":  {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([]), "win_saddle_ids": [], "win_race_ids": [], "race_history": []},
        "gp2":  {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([]), "win_saddle_ids": [], "win_race_ids": [], "race_history": []},
        "gp3":  {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([]), "win_saddle_ids": [], "win_race_ids": [], "race_history": []},
        "gp4":  {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([]), "win_saddle_ids": [], "win_race_ids": [], "race_history": []},
    }
    tree["self"]["factors"] = get_factors(chara_entry.get('factor_id_array') or [], self_cid)
    position_to_key = {10: 'p1', 20: 'p2', 11: 'gp1', 12: 'gp2', 21: 'gp3', 22: 'gp4'}
    for sc in chara_entry.get('succession_chara_array') or []:
        key = position_to_key.get(sc.get('position_id'))
        if not key:
            continue
        sc_cid = sc.get('card_id') or 0
        win_data = get_race_record_data(sc)
        tree[key]["card_id"] = sc_cid
        tree[key]["name"] = chara_map.get(str(sc_cid), f"Unknown ({sc_cid})")
        tree[key]["factors"] = get_factors(sc.get('factor_id_array') or [], sc_cid)
        tree[key]["wins"] = win_data["summary"]
        tree[key]["win_saddle_ids"] = win_data["saddle_ids"]
        tree[key]["win_race_ids"] = win_data["race_ids"]
        tree[key]["race_history"] = win_data["history"]
    return tree


def normalize_card_name(name):
    return re.sub(r'[^a-z0-9]+', '', re.sub(r'\([^)]*\)', '', str(name or '').lower()))


def validate_start_selection(req):
    support_ids = [int(card_id) for card_id in req.support_card_ids]
    friend_card_id = int(req.friend_card_id)
    if friend_card_id in support_ids:
        return "Friend support card is already in selected deck"

    friend_info = support_map.get(str(friend_card_id), {})
    friend_name = normalize_card_name(friend_info.get('name'))

    trainee_name = normalize_card_name(chara_map.get(str(req.card_id), ''))

    if friend_name:
        for support_id in support_ids:
            support_name = normalize_card_name(support_map.get(str(support_id), {}).get('name'))
            if support_name and support_name == friend_name:
                return "Friend support card has same character as selected deck"

        if trainee_name and trainee_name == friend_name:
            return "Friend support card has same character as trainee"

    # The game forbids the trainee's character from also appearing as one of the deck's
    # support cards (Oguri Cap trainee + Oguri Cap support card is rejected). Parents
    # are exempt — same character as a deck card is fine as a parent.
    if trainee_name:
        for support_id in support_ids:
            support_name = normalize_card_name(support_map.get(str(support_id), {}).get('name'))
            if support_name and support_name == trainee_name:
                return "Deck contains a support card of the same character as the trainee"

    # Guest cannot be the same character as the trainee. The guest's card_id lives in the
    # cached borrow pool keyed by (viewer_id, trained_chara_id).
    rental_v = int(getattr(req, "rental_viewer_id", 0) or 0)
    rental_t = int(getattr(req, "rental_trained_chara_id", 0) or 0)
    if rental_v and rental_t and trainee_name and active_dashboard_data:
        for entry in (active_dashboard_data.get("borrow_umas") or []):
            if int(entry.get("viewer_id") or 0) == rental_v and int(entry.get("trained_chara_id") or 0) == rental_t:
                guest_name = normalize_card_name(chara_map.get(str(entry.get("card_id") or 0), ''))
                if guest_name and guest_name == trainee_name:
                    return "Guest parent has same character as the trainee"
                break

    parent1_cards = active_parent_cards.get(int(req.parent_id_1), [])
    parent2_cards = active_parent_cards.get(int(req.parent_id_2), [])
    if parent1_cards and parent2_cards and int(req.card_id) in (parent1_cards[0], parent2_cards[0]):
        return "Selected direct parent is same character as trainee"

    # The game forbids both inheritance slots from being the same character — even when
    # one slot is a borrowed guest. We compare the chara names of: parent_id_1, parent_id_2,
    # and the guest (looked up by rental_viewer_id + rental_trained_chara_id).
    p1_card_id = parent1_cards[0] if parent1_cards else 0
    p2_card_id = parent2_cards[0] if parent2_cards else 0
    p1_chara = normalize_card_name(chara_map.get(str(p1_card_id), '')) if p1_card_id else ''
    p2_chara = normalize_card_name(chara_map.get(str(p2_card_id), '')) if p2_card_id else ''
    guest_card_id = 0
    if rental_v and rental_t and active_dashboard_data:
        for entry in (active_dashboard_data.get("borrow_umas") or []):
            if int(entry.get("viewer_id") or 0) == rental_v and int(entry.get("trained_chara_id") or 0) == rental_t:
                guest_card_id = int(entry.get("card_id") or 0)
                break
    g_chara = normalize_card_name(chara_map.get(str(guest_card_id), '')) if guest_card_id else ''
    if p1_chara and p2_chara and p1_chara == p2_chara:
        return "Both direct parents are the same character"
    if p1_chara and g_chara and p1_chara == g_chara:
        return "Parent 1 and the borrowed guest are the same character"
    if p2_chara and g_chara and p2_chara == g_chara:
        return "Parent 2 (fallback) and the borrowed guest are the same character"

    return None


def borrow_fallback_start_error(req, quota=None):
    rental_v = int(getattr(req, "rental_viewer_id", 0) or 0)
    rental_t = int(getattr(req, "rental_trained_chara_id", 0) or 0)
    if not (rental_v and rental_t):
        return None
    quota = quota or compute_borrow_quota(active_client)
    if int((quota or {}).get("remaining", 0) or 0) > 0:
        return None
    fallback_id = int(getattr(req, "borrow_fallback_id", 0) or 0)
    parent2_id = int(getattr(req, "parent_id_2", 0) or 0)
    parent1_id = int(getattr(req, "parent_id_1", 0) or 0)
    effective_parent2_id = fallback_id or parent2_id
    if not effective_parent2_id or effective_parent2_id == parent1_id:
        return (
            "Daily borrows are exhausted and no valid fallback Parent 2 is configured. "
            "Set 'Fallback when out of borrows' to one of your own parents, or the loop will stop once borrows run out."
        )
    if active_dashboard_data:
        parent_ids = {int(parent.get("instance_id") or 0) for parent in (active_dashboard_data.get("parents") or [])}
        if parent_ids and effective_parent2_id not in parent_ids:
            return (
                "Daily borrows are exhausted and the configured fallback Parent 2 is not present in owned parent data. "
                "Re-select the fallback parent before looping again."
            )
    return None


def deck_type_counts_from_ids(support_ids, friend_card_id=0):
    counts = [0] * 5
    type_aliases = {
        "speed": 0,
        "stamina": 1,
        "power": 2,
        "guts": 3,
        "wisdom": 4,
        "wit": 4,
        "int": 4,
        "intelligence": 4,
    }
    for sid_int in list(support_ids or []) + ([friend_card_id] if friend_card_id else []):
        info = support_map.get(str(sid_int))
        if not info:
            continue
        idx = type_aliases.get(str(info.get("type") or "").strip().lower())
        if idx is not None:
            counts[idx] += 1
    return counts


def deck_type_counts_from_chara(chara_info):
    ids = []
    for card in (chara_info or {}).get('support_card_array') or []:
        sid = int(card.get('support_card_id') or 0)
        if sid:
            ids.append(sid)
    return deck_type_counts_from_ids(ids)


def apply_deck_type_counts(preset, req=None, chara_info=None):
    counts = None
    source = ""
    if req and (req.support_card_ids or req.friend_card_id):
        counts = deck_type_counts_from_ids(req.support_card_ids, req.friend_card_id)
        source = "request"
    elif chara_info:
        counts = deck_type_counts_from_chara(chara_info)
        source = "career"
    if counts is not None and any(counts):
        preset["_deck_type_counts"] = counts
        preset["_deck_type_counts_source"] = source
        scale_table = [0.0, 0.02, 0.05, 0.09, 0.14, 0.20]
        preset["_deck_multipliers"] = [1.0 + scale_table[min(5, c)] for c in counts]


def parent_rank_point(parent_id):
    parent = active_parent_rank_points.get(int(parent_id))
    if not parent:
        return 0
    rank = int(parent.get('rank') or 0)
    if rank == 13:
        return 62
    return int(parent.get('rank_point') or 0)


def selected_succession_rank_point(req):
    selected_total = parent_rank_point(req.parent_id_1) + parent_rank_point(req.parent_id_2)
    if selected_total:
        return selected_total
    return active_start_state.get('succession_rank_point', 0)

master_map = {}
master_map_path = base_dir / 'data' / 'master_map.json'
if master_map_path.exists():
    with open(master_map_path, 'r', encoding='utf-8') as f:
        master_map = json.load(f)

unique_map = {}
unique_map_path = base_dir / 'data' / 'unique_map.json'
if unique_map_path.exists():
    with open(unique_map_path, 'r', encoding='utf-8') as f:
        unique_map = json.load(f)

factor_map = {}
factor_map_path = base_dir / 'data' / 'factor_map.json'
if factor_map_path.exists():
    with open(factor_map_path, 'r', encoding='utf-8') as f:
        factor_map = json.load(f)

SCENARIO_FACTOR_EFFECTS = {
    "URA Finale": ("Speed", "Stamina"),
    "Unity Cup": ("Power", "Wit"),
    "TS Climax Scenario": ("Stamina", "Guts"),
}

RACE_FACTOR_EFFECTS = {
    "Asahi Hai Futurity Stakes": ("Speed", "Guts"),
    "Hanshin Juvenile Fillies": ("Speed", "Power"),
    "Hopeful Stakes": ("Speed", "Stamina"),
    "Oka Sho": ("Hanshin Racecourse hint", "Guts"),
    "Satsuki Sho": ("Nakayama Racecourse hint", "Power"),
    "NHK Mile C.": ("Speed", "Power"),
    "Victoria Mile": ("Speed", "Power"),
    "Japanese Oaks": ("Tokyo Racecourse hint", "Stamina"),
    "Tokyo Yushun (Japanese Derby)": ("Tokyo Racecourse hint", "Guts"),
    "Yasuda Kinen": ("Tokyo Racecourse hint", "Speed"),
    "Takarazuka Kinen": ("Summer Runner hint", "Guts"),
    "Japan Dirt Derby": ("Oi Racecourse hint", "Power"),
    "Sprinters S.": ("Standard Distance hint", "Speed"),
    "Kikuka Sho": ("Kyoto Racecourse hint", "Stamina"),
    "Shuka Sho": ("Kyoto Racecourse hint", "Wit"),
    "Tenno Sho (Autumn)": ("Fall Runner hint", "Speed"),
    "JBC Classic": ("Stamina", "Guts"),
    "JBC L. Classic": ("Speed", "Guts"),
    "JBC Sprint": ("Power", "Guts"),
    "Queen Elizabeth II Cup": ("Non-Standard Distance hint", "Stamina"),
    "Japan C.": ("Tokyo Racecourse hint", "Stamina"),
    "Mile Ch.": ("Standard Distance hint", "Speed"),
    "Champions C.": ("Chukyo Racecourse hint", "Power"),
    "Arima Kinen": ("Nakayama Racecourse hint", "Guts"),
    "Tokyo Daishoten": ("Oi Racecourse hint", "Power"),
    "February S.": ("Winter Runner hint", "Power"),
    "Osaka Hai": ("Standard Distance hint", "Guts"),
    "Takamatsunomiya Kinen": ("Chukyo Racecourse hint", "Speed"),
    "Tenno Sho (Spring)": ("Spring Runner hint", "Stamina"),
    "Teio Sho": ("Oi Racecourse hint", "Power"),
}

race_map = {}
race_map_path = base_dir / 'data' / 'race_map.json'
if race_map_path.exists():
    with open(race_map_path, 'r', encoding='utf-8') as f:
        race_map = json.load(f)

affinity_race_meta = {}
affinity_race_meta_path = base_dir / 'public' / 'assets' / 'data' / 'affinity_race_meta.json'
if affinity_race_meta_path.exists():
    with open(affinity_race_meta_path, 'r', encoding='utf-8') as f:
        affinity_race_meta = json.load(f)


def safe_int(value, default=0):
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _legacy_win_grade(saddle_id):
    """win_saddle_id_array uses legacy race-win title IDs, not race program IDs."""
    if 10 <= saddle_id <= 39:
        return "G1"
    if 40 <= saddle_id <= 73:
        return "G2"
    if 74 <= saddle_id <= 143:
        return "G3"
    return "TITLE"


def _grade_for_race_instance_id(race_instance_id):
    grade_map = affinity_race_meta.get("grade_by_race_id") or {}
    return str(grade_map.get(str(safe_int(race_instance_id))) or "").upper()


def _race_meta_from_row(raw_race_id, row):
    row = dict(row or {})
    race_instance_id = safe_int(row.get("race_instance_id"))
    program_id = safe_int(row.get("program_id"))
    program = dict((race_map.get("program") or {}).get(str(program_id)) or {})
    grade = _grade_for_race_instance_id(race_instance_id) or str(row.get("grade") or program.get("grade") or "").upper()
    return {
        "program_id": program_id,
        "race_id": safe_int(raw_race_id),
        "race_instance_id": race_instance_id,
        "name": row.get("name") or program.get("name") or f"Program {program_id}",
        "grade": grade,
        "turn": safe_int(row.get("turn") or program.get("turn")),
        "month": safe_int(row.get("month") or program.get("month")),
        "half": safe_int(row.get("half") or program.get("half")),
    }


def _race_meta_for_program(program_id):
    program_id = safe_int(program_id)
    if not program_id:
        return {}
    program = dict((race_map.get("program") or {}).get(str(program_id)) or {})
    meta = {}
    for raw_race_id, row in (race_map.get("meta") or {}).items():
        if safe_int((row or {}).get("program_id")) == program_id:
            meta = _race_meta_from_row(raw_race_id, row)
            break
    if meta:
        return meta
    race_instance_id = safe_int(program.get("race_instance_id"))
    grade = _grade_for_race_instance_id(race_instance_id) or str(program.get("grade") or "").upper()
    return {
        "program_id": program_id,
        "race_id": 0,
        "race_instance_id": race_instance_id,
        "name": program.get("name") or f"Program {program_id}",
        "grade": grade,
        "turn": safe_int(program.get("turn")),
        "month": safe_int(program.get("month")),
        "half": safe_int(program.get("half")),
    }


def _race_meta_for_instance(race_instance_id):
    race_instance_id = safe_int(race_instance_id)
    if not race_instance_id:
        return {}
    for raw_race_id, row in (race_map.get("meta") or {}).items():
        if safe_int((row or {}).get("race_instance_id")) == race_instance_id:
            return _race_meta_from_row(raw_race_id, row)
    program_ids = (race_map.get("instance") or {}).get(str(race_instance_id)) or []
    if program_ids:
        return _race_meta_for_program(program_ids[0])
    return {}


def _is_placeholder_race_name(name):
    text = str(name or "").strip()
    if not text:
        return True
    return bool(re.match(r"^(?:race|program|unknown race|race win)\s*\d*$", text, flags=re.IGNORECASE))


def _normalized_race_grade(raw_grade, meta_grade):
    grade = str(raw_grade or "").strip().upper()
    if grade in ("", "RACE", "UNKNOWN", "TITLE"):
        return str(meta_grade or "").strip().upper()
    return grade


def get_race_result_history(races, source="race_result_array"):
    history = []
    for index, race in enumerate(races or []):
        if not isinstance(race, dict):
            continue
        program_id = safe_int(race.get("program_id"))
        raw_race_id = safe_int(race.get("race_id") or race.get("id"))
        race_instance_id = safe_int(race.get("race_instance_id"))
        if not race_instance_id and raw_race_id and str(raw_race_id) in (race_map.get("instance") or {}):
            race_instance_id = raw_race_id
        meta = _race_meta_for_program(program_id)
        instance_meta = _race_meta_for_instance(race_instance_id)
        if instance_meta:
            merged = dict(meta)
            merged.update({key: value for key, value in instance_meta.items() if value not in (None, "", 0)})
            meta = merged
        if not program_id:
            program_id = safe_int(meta.get("program_id"))
        rank = safe_int(race.get("result_rank") or race.get("finish_rank") or race.get("rank"))
        turn = safe_int(race.get("turn") or meta.get("turn"))
        race_instance_id = race_instance_id or safe_int(meta.get("race_instance_id"))
        race_id = raw_race_id or safe_int(meta.get("race_id"))
        name = race.get("name")
        if _is_placeholder_race_name(name) and meta.get("name"):
            name = meta.get("name")
        grade = _normalized_race_grade(race.get("grade"), meta.get("grade"))
        history.append({
            "_order": index,
            "turn": turn,
            "program_id": program_id,
            "race_id": race_id,
            "race_instance_id": race_instance_id,
            "name": name or meta.get("name") or f"Program {program_id}",
            "grade": grade,
            "month": safe_int(race.get("month") or meta.get("month")),
            "half": safe_int(race.get("half") or meta.get("half")),
            "style": safe_int(race.get("running_style") or race.get("style") or race.get("strategy")),
            "running_style": safe_int(race.get("running_style") or race.get("style") or race.get("strategy")),
            "style_source": source,
            "source": source,
            "result_rank": rank,
            "result": "won" if rank == 1 else "lost" if rank > 1 else "unknown",
            "won": rank == 1 if rank else False,
            "weather": safe_int(race.get("weather")),
            "ground_condition": safe_int(race.get("ground_condition")),
            "frame_order": safe_int(race.get("frame_order")),
        })
    return sorted(history, key=lambda row: (safe_int(row.get("turn")), safe_int(row.get("_order")), safe_int(row.get("program_id"))))


def get_race_record_data(chara):
    chara = chara or {}
    if chara.get("race_result_array"):
        raw_history = chara.get("race_result_array") or []
        source = "race_result_array"
    else:
        raw_history = chara.get("race_history") or []
        source = "race_history"
    history = get_race_result_history(raw_history, source=source)
    if not history:
        return get_win_data(chara.get("win_saddle_id_array") or [])

    summary = {
        "g1": 0,
        "g2": 0,
        "g3": 0,
        "titles": 0,
        "losses": 0,
    }
    race_ids = []
    seen_race_ids = set()
    for row in history:
        rank = safe_int(row.get("result_rank"))
        if rank and rank != 1:
            summary["losses"] += 1
        if rank != 1:
            continue
        grade = str(row.get("grade") or "").upper()
        if grade == "G1":
            summary["g1"] += 1
        elif grade == "G2":
            summary["g2"] += 1
        elif grade == "G3":
            summary["g3"] += 1
        else:
            summary["titles"] += 1
        race_id = safe_int(row.get("race_instance_id") or row.get("race_id"))
        if race_id and race_id not in seen_race_ids:
            seen_race_ids.add(race_id)
            race_ids.append(race_id)
    summary["total"] = sum(summary[key] for key in ("g1", "g2", "g3", "titles"))
    return {
        "summary": summary,
        "saddle_ids": [safe_int(value) for value in (chara.get("win_saddle_id_array") or []) if safe_int(value)],
        "race_ids": race_ids,
        "history": history,
    }


def get_win_data(win_saddle_ids):
    summary = {
        "g1": 0,
        "g2": 0,
        "g3": 0,
        "titles": 0,
    }
    saddle_ids = []
    race_ids = []
    history = []
    seen_race_ids = set()
    race_win_titles = master_map.get('race', {}) if isinstance(master_map, dict) else {}

    for saddle_id in win_saddle_ids or []:
        try:
            sid = int(saddle_id)
        except (TypeError, ValueError):
            continue
        saddle_ids.append(sid)
        race_id = 20000 + sid
        if race_id and race_id not in seen_race_ids:
            seen_race_ids.add(race_id)
            race_ids.append(race_id)
        race_name = race_win_titles.get(str(race_id)) or f"Race Win {sid}"
        grade = _legacy_win_grade(sid)
        if grade == "G1":
            summary["g1"] += 1
        elif grade == "G2":
            summary["g2"] += 1
        elif grade == "G3":
            summary["g3"] += 1
        else:
            summary["titles"] += 1
        history.append({
            "saddle_id": sid,
            "program_id": 0,
            "race_id": race_id,
            "name": race_name,
            "grade": grade,
            "turn": 0,
            "month": 0,
            "half": 0,
            "style": "",
            "style_source": "",
            "source": "win_saddle_id_array",
            "result_rank": 1,
            "result": "won",
        })

    summary["total"] = len(saddle_ids)
    return {
        "summary": summary,
        "saddle_ids": saddle_ids,
        "race_ids": race_ids,
        "history": history,
    }


def get_win_summary(win_saddle_ids):
    return get_win_data(win_saddle_ids)["summary"]

def get_trained_chara_stats(chara):
    chara = chara or {}
    return {
        "speed": int(chara.get("speed") or 0),
        "stamina": int(chara.get("stamina") or 0),
        "power": int(chara.get("power") or chara.get("pow") or 0),
        "guts": int(chara.get("guts") or 0),
        "wit": int(chara.get("wiz") or chara.get("wit") or 0),
        "skill_point": int(chara.get("skill_point") or chara.get("skill_pt") or 0),
        "max_speed": int(chara.get("max_speed") or 1200),
        "max_stamina": int(chara.get("max_stamina") or 1200),
        "max_power": int(chara.get("max_power") or 1200),
        "max_guts": int(chara.get("max_guts") or 1200),
        "max_wit": int(chara.get("max_wiz") or chara.get("max_wit") or 1200),
    }

def estimate_skill_point_cost(skill_id, name="", hint_level=0):
    """Estimate learned skill SP cost when the veteran payload lacks purchase history."""
    try:
        skill_id = int(skill_id or 0)
    except (TypeError, ValueError):
        skill_id = 0
    try:
        hint_level = int(hint_level or 0)
    except (TypeError, ValueError):
        hint_level = 0
    name = str(name or "")
    # Character unique skills are upgraded by career events, not purchased
    # with SP. Counting them made parent/run SP estimates drift into impossible
    # 4k+ ranges.
    if 0 < skill_id < 200000:
        return 0
    circle_markers = ("\u25cb", "\u25ef", "â—‹", "â—¯")
    if any(marker in name for marker in circle_markers):
        base = 110
    elif skill_id >= 900000:
        base = 200
    elif skill_id % 10 >= 2:
        base = 180
    else:
        base = 120
    return max(1, int(base * (100 - min(max(hint_level, 0), 5) * 10) / 100))

def get_skill_rows(skill_array):
    rows = []
    for raw in skill_array or []:
        try:
            skill_id = int(raw.get("skill_id") or 0)
        except (TypeError, ValueError):
            skill_id = 0
        if not skill_id:
            continue
        level = raw.get("level")
        try:
            level = int(level or 1)
        except (TypeError, ValueError):
            level = 1
        name = master_map.get("skill", {}).get(str(skill_id), f"Skill {skill_id}")
        rows.append({
            "skill_id": skill_id,
            "group_id": skill_id if skill_id < 100000 else skill_id // 10,
            "level": level,
            "name": name,
            "estimated_cost": estimate_skill_point_cost(skill_id, name),
        })
    rows.sort(key=lambda row: (str(row.get("name") or "").lower(), row.get("skill_id") or 0))
    return rows

def get_estimated_skill_points(skill_rows):
    total = 0
    for row in skill_rows or []:
        try:
            current_estimate = estimate_skill_point_cost(
                row.get("skill_id"),
                row.get("name") or "",
                row.get("hint_level") or 0,
            )
            stored_estimate = int(row.get("estimated_cost") or 0)
            # Recompute from the current estimator so old cached parent rows
            # do not keep stale costs for free character unique skills.
            total += current_estimate if current_estimate != stored_estimate else stored_estimate
        except (TypeError, ValueError):
            continue
    return total

def clean_factor_name(name, base_id=None, category=None):
    if not isinstance(name, str):
        return name

    if category == "skill" and "?" in name and base_id is not None:
        skill_name = master_map.get('skill', {}).get(f"{base_id}2")
        if skill_name:
            return skill_name
    return name.replace(" ?", " ○")

def factor_effect_summary(name, category):
    name = str(name or "").strip()
    category = str(category or "").strip().lower()
    if not name:
        return ""
    if category == "stat":
        return f"Inheritance effect: +{name}"
    if category == "aptitude":
        return f"Inheritance effect: improves {name} aptitude"
    if category == "unique":
        return "Inheritance effect: unique skill hint"
    if category == "skill":
        return f"Inheritance effect: {name} hint"
    effects = ()
    if category == "scenario":
        effects = SCENARIO_FACTOR_EFFECTS.get(name, ())
    elif category == "race":
        effects = RACE_FACTOR_EFFECTS.get(name, ())
    if effects:
        return "Inheritance effect: " + " + ".join(str(effect) for effect in effects if effect)
    return ""


def get_factors(fid_array, owner_card_id=None):
    results = []
    category_order = {
        "stat": 0,
        "aptitude": 1,
        "unique": 2,
        "race": 3,
        "skill": 4,
        "scenario": 5,
        "other": 6
    }
    stat_map = {
        1: 'Speed', 2: 'Stamina', 3: 'Power', 4: 'Guts', 5: 'Wit',
        11: 'Turf', 12: 'Dirt',
        21: 'Short', 22: 'Mile', 23: 'Medium', 24: 'Long',
        31: 'Front Runner', 32: 'Pace Chaser', 33: 'Late Surger', 34: 'End Closer'
    }
    
    owner_cid_str = str(owner_card_id) if owner_card_id else ""
    if len(owner_cid_str) > 4: owner_cid_str = owner_cid_str[:4]

    for fid in fid_array:
        if not fid or fid <= 0: continue

        fid_str = str(fid)
        factor_info = factor_map.get(fid_str)
        if factor_info:
            base_id = fid // 100
            category = factor_info.get("category", "other")
            name = clean_factor_name(factor_info.get("name", f"Unknown({fid})"), base_id, category)
            stars = factor_info.get("stars", fid % 100)
            results.append({
                "name": name,
                "stars": stars,
                "id": fid,
                "category": category,
                "effect_summary": factor_effect_summary(name, category),
            })
            continue

        base_id = fid // 100
        stars = fid % 100
        bid_str = str(base_id)
        name = f"Unknown({base_id})"
        category = "other"
        
        if base_id <= 34:
            category = "stat" if base_id <= 5 else "aptitude"
            name = stat_map.get(base_id, name)
        
        elif 30000 <= base_id < 40000:
            category = "scenario"
            name = master_map.get('scenario', {}).get(bid_str, f"Scenario({base_id})")
        
        elif bid_str == owner_cid_str or (len(bid_str) >= 4 and bid_str[:4] == owner_cid_str):
            category = "unique"
            name = unique_map.get(bid_str[:4], f"Unique({bid_str})")

        elif bid_str in master_map.get('race', {}):
            category = "race"
            name = master_map['race'][bid_str]
    
        elif bid_str in master_map.get('skill', {}):
            category = "skill"
            name = master_map['skill'][bid_str]

        elif len(bid_str) >= 4 and bid_str[:4] in unique_map:
            category = "unique"
            name = unique_map[bid_str[:4]]
            
        results.append({
            "name": name,
            "stars": stars,
            "id": base_id,
            "category": category,
            "effect_summary": factor_effect_summary(name, category),
        })

    return [
        factor for _, factor in sorted(
            enumerate(results),
            key=lambda item: (category_order.get(item[1]["category"], 99), item[0])
        )
    ]


def get_chara_factor_ids(chara):
    """Prefer the trained character spark array; factor_info_array can describe other factor metadata."""
    factor_ids = chara.get('factor_id_array')
    if isinstance(factor_ids, list) and factor_ids:
        return factor_ids
    return [f.get('factor_id', 0) for f in chara.get('factor_info_array', [])]


def get_item_count(item_list, item_id):
    for item in item_list or []:
        try:
            current_item_id = int(item.get('item_id') or 0)
        except (TypeError, ValueError):
            current_item_id = 0
        if current_item_id == int(item_id):
            return int(item.get('number') or item.get('num') or item.get('count') or 0)
    return 0

def int_or_zero(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0

def derive_tp_info(tp_info, now=None):
    info = dict(tp_info or {})
    if not info:
        return {}
    now = int(time.time() if now is None else now)
    current = int_or_zero(info.get('current_tp', info.get('current', 0)))
    max_tp = int_or_zero(info.get('max_tp', info.get('max', current)))
    max_recovery_time = int_or_zero(info.get('max_recovery_time'))
    derived_current = current
    next_recovery_time = 0
    seconds_to_next = 0

    if max_tp > 0 and max_recovery_time:
        if current >= max_tp or max_recovery_time <= now:
            derived_current = max_tp
        else:
            remaining = max(0, max_recovery_time - now)
            missing = (remaining + TP_RECOVERY_SECONDS_PER_POINT - 1) // TP_RECOVERY_SECONDS_PER_POINT
            derived_current = max(current, max(0, min(max_tp, max_tp - missing)))
            if derived_current < max_tp:
                missing_after_current = max_tp - derived_current
                next_recovery_time = max_recovery_time - ((missing_after_current - 1) * TP_RECOVERY_SECONDS_PER_POINT)
                seconds_to_next = max(0, next_recovery_time - now)

    info['current_tp'] = max(0, min(derived_current, max_tp if max_tp > 0 else derived_current))
    info['max_tp'] = max_tp
    info['server_current_tp'] = int_or_zero(info.get('server_current_tp', current))
    info['max_recovery_time'] = max_recovery_time
    info['next_recovery_time'] = next_recovery_time
    info['seconds_to_next'] = seconds_to_next
    info['recovery_seconds_per_point'] = TP_RECOVERY_SECONDS_PER_POINT
    info['estimated'] = info['current_tp'] != info['server_current_tp']
    return info

def tp_account_view(tp_info):
    info = derive_tp_info(tp_info)
    return {
        "current": info.get('current_tp', 0),
        "max": info.get('max_tp', 0),
        "max_recovery_time": info.get('max_recovery_time', 0),
        "next_recovery_time": info.get('next_recovery_time', 0),
        "seconds_to_next": info.get('seconds_to_next', 0),
        "recovery_seconds_per_point": info.get('recovery_seconds_per_point', TP_RECOVERY_SECONDS_PER_POINT),
    }

def set_start_state_item_count(item_id, count):
    item_id = int_or_zero(item_id)
    if not item_id:
        return
    count = max(0, int_or_zero(count))
    item_list = active_start_state.setdefault('item_list', [])
    for item in item_list:
        if int_or_zero(item.get('item_id')) == item_id:
            item['number'] = count
            break
    else:
        item_list.append({'item_id': item_id, 'number': count})
    if item_id == 59:
        active_start_state['current_money'] = count

def add_start_state_item_count(item_id, delta):
    item_id = int_or_zero(item_id)
    if not item_id:
        return
    current = get_item_count(active_start_state.get('item_list') or [], item_id)
    set_start_state_item_count(item_id, current + int_or_zero(delta))

def apply_reward_summary_to_start_state(reward_summary):
    for item in (reward_summary or {}).get('add_item_list') or []:
        if not isinstance(item, dict):
            continue
        item_id = int_or_zero(item.get('item_id'))
        number = int_or_zero(item.get('number', item.get('num', item.get('count', 0))))
        if item_id and number:
            add_start_state_item_count(item_id, number)

def apply_use_item_info_to_start_state(use_item_info):
    entries = use_item_info if isinstance(use_item_info, list) else [use_item_info]
    for item in entries:
        if not isinstance(item, dict):
            continue
        item_id = int_or_zero(item.get('item_id'))
        if not item_id:
            continue
        remaining = item.get('remaining_num')
        if remaining is None:
            remaining = item.get('remain_num')
        if remaining is None and 'current_num' in item:
            remaining = item.get('current_num')
        if remaining is not None:
            set_start_state_item_count(item_id, remaining)
            continue
        used = int_or_zero(item.get('use_num', item.get('item_num', item.get('count', 0))))
        if used:
            add_start_state_item_count(item_id, -used)

def apply_tp_timer_to_cached_state(now=None):
    global active_account, active_dashboard_data
    with state_sync_lock:
        tp_info = active_start_state.get('tp_info')
        if not isinstance(tp_info, dict) or not tp_info:
            return {}
        derived = derive_tp_info(tp_info, now=now)
        active_start_state['tp_info'] = derived
        account_targets = []
        if isinstance(active_account, dict):
            account_targets.append(active_account)
        if isinstance(active_dashboard_data, dict) and isinstance(active_dashboard_data.get('account'), dict):
            account_targets.append(active_dashboard_data['account'])
        for account in account_targets:
            account['tp'] = tp_account_view(derived)
        return derived

def get_recovery_mode_name(mode):
    names = {
        TP_RECOVERY_NONE: "none",
        TP_RECOVERY_CARATS: "carats",
        TP_RECOVERY_TOUGHNESS: "toughness",
        TP_RECOVERY_BOTH: "both",
    }
    return names.get(int(mode or 0), "unknown")

def get_carats_total_from_coin_info(coin_info):
    coin_info = coin_info or {}
    return int(coin_info.get("fcoin") or 0) + int(coin_info.get("coin") or 0)

def get_carats_client_own_num_from_coin_info(coin_info):
    # The game sends total held carats in client_own_num. A sniffed successful
    # request used client_own_num=2295 and returned fcoin=2245, coin=40:
    # total 2285, matching the in-game 10-carats-for-30-TP cost.
    return get_carats_total_from_coin_info(coin_info)

def tp_recovery_resource_status(mode, state=None):
    mode = max(0, min(int(mode or 0), TP_RECOVERY_BOTH))
    state = state if state is not None else active_start_state
    coin_info = state.get("coin_info") or {}
    item_list = state.get("item_list") or []
    carats_total = get_carats_total_from_coin_info(coin_info)
    carats_client_own_num = get_carats_client_own_num_from_coin_info(coin_info)
    item_counts = {
        str(item_id): int(get_item_count(item_list, item_id) or 0)
        for item_id in TP_RECOVERY_ITEM_IDS
    }
    toughness_count = sum(item_counts.values())
    carats_available = carats_total >= TP_RECOVERY_CARAT_COST
    toughness_available = toughness_count > 0
    can_use_carats = mode in (TP_RECOVERY_CARATS, TP_RECOVERY_BOTH) and carats_available
    can_use_toughness = mode in (TP_RECOVERY_TOUGHNESS, TP_RECOVERY_BOTH) and toughness_available
    return {
        "mode": mode,
        "mode_name": get_recovery_mode_name(mode),
        "api_allow_recover_tp": bool(mode),
        "carats_total": carats_total,
        "carats_client_own_num": carats_client_own_num,
        "carats_cost": TP_RECOVERY_CARAT_COST,
        "carats_available": carats_available,
        "toughness_item_ids": item_counts,
        "toughness_count": toughness_count,
        "toughness_available": toughness_available,
        "can_recover": bool(can_use_carats or can_use_toughness),
    }

def tp_recovery_unavailable_detail(status):
    return (
        f"selected TP recovery mode {status.get('mode_name')} has no usable resources "
        f"(carats {status.get('carats_total', 0)}/{status.get('carats_cost', TP_RECOVERY_CARAT_COST)}, "
        f"toughness items {status.get('toughness_count', 0)})"
    )

def selected_toughness_recovery_item(status):
    counts = status.get("toughness_item_ids") or {}
    for item_id in TP_RECOVERY_ITEM_IDS:
        count = int(counts.get(str(item_id)) or counts.get(item_id) or 0)
        if count > 0:
            return int(item_id), count
    return 0, 0

def current_start_tp():
    tp_info = apply_tp_timer_to_cached_state() or active_start_state.get("tp_info") or {}
    return int(tp_info.get("current_tp") or 0)

def update_start_state_from_api_response(response):
    data = (response or {}).get("data") or {}
    if data:
        sync_game_data_from_api_response("", response, source="manual")
    return data

def refresh_start_state_after_recovery():
    global active_account, active_dashboard_data
    if not active_client or not hasattr(active_client, "call"):
        return {"success": True, "skipped": True}
    load_result = load_index_with_session_recovery(active_client)
    load_data = load_result.get("data") or {}
    sync_game_data_from_api_response("load/index", load_result, source="recovery_refresh")
    if hasattr(active_client, "refresh_cached_account_state"):
        active_client.refresh_cached_account_state(load_data)
    # Recovery consumed real resources on the server (carats or toughness items).
    # Push the post-recovery account into the cached dashboard so the UI strip
    # reflects what was actually spent, not the pre-recovery cached snapshot.
    account = active_account or get_account_status(load_data)
    active_account = account
    if active_dashboard_data is not None:
        active_dashboard_data["account"] = account
    return {"success": True, "tp_current": current_start_tp()}

def attempt_tp_recovery_before_start(req, mode, required_tp):
    mode = max(0, min(int(mode or 0), TP_RECOVERY_BOTH))
    result = {
        "attempted": False,
        "success": False,
        "mode": mode,
        "mode_name": get_recovery_mode_name(mode),
        "tp_before": current_start_tp(),
        "tp_after": current_start_tp(),
        "attempts": [],
        "errors": [],
    }
    if required_tp <= 0 or current_start_tp() >= required_tp or mode == TP_RECOVERY_NONE:
        result["success"] = current_start_tp() >= required_tp
        return result

    status = tp_recovery_resource_status(mode)
    attempts = []
    if mode in (TP_RECOVERY_TOUGHNESS, TP_RECOVERY_BOTH) and status.get("toughness_available"):
        attempts.append("toughness")
    if mode in (TP_RECOVERY_CARATS, TP_RECOVERY_BOTH) and status.get("carats_available"):
        attempts.append("carats")

    if not attempts:
        result["errors"].append(tp_recovery_unavailable_detail(status))
        return result

    for attempt_name in attempts:
        if current_start_tp() >= required_tp:
            break
        result["attempted"] = True

        if attempt_name == "toughness":
            item_id, current_num = selected_toughness_recovery_item(status)
            attempt = {
                "type": "toughness",
                "tp_before": current_start_tp(),
                "endpoint": "item/use_recovery_item",
                "item_id": item_id,
                "client_own_num": current_num,
            }
            try:
                response = active_client.use_recovery_item(item_id=item_id, current_num=current_num)
                update_start_state_from_api_response(response)
                attempt["response_tp"] = current_start_tp()
                try:
                    refresh = refresh_start_state_after_recovery()
                    attempt["refresh"] = refresh
                except Exception as refresh_exc:
                    attempt["refresh_error"] = redact_sensitive_error_text(refresh_exc)
                attempt["tp_after"] = current_start_tp()
                result["attempts"].append(attempt)
                if current_start_tp() >= required_tp:
                    result["success"] = True
                    result["used"] = "toughness"
                    result["tp_after"] = current_start_tp()
                    return result
            except Exception as exc:
                attempt["error"] = redact_sensitive_error_text(exc)
                attempt["tp_after"] = current_start_tp()
                result["attempts"].append(attempt)
                result["errors"].append(f"toughness: {redact_sensitive_error_text(exc)}")
            continue

        attempt = {
            "type": "carats",
            "tp_before": current_start_tp(),
            "endpoint": "user/recovery_trainer_point",
            "count": 1,
            "client_own_num": int(status.get("carats_client_own_num") or 0),
        }
        try:
            response = active_client.recover_trainer_point(
                count=attempt["count"],
                client_own_num=attempt["client_own_num"],
            )
            update_start_state_from_api_response(response)
            attempt["response_tp"] = current_start_tp()
            try:
                refresh = refresh_start_state_after_recovery()
                attempt["refresh"] = refresh
            except Exception as refresh_exc:
                attempt["refresh_error"] = redact_sensitive_error_text(refresh_exc)
            attempt["tp_after"] = current_start_tp()
            result["attempts"].append(attempt)
            if current_start_tp() >= required_tp:
                result["success"] = True
                result["used"] = "carats"
                result["tp_after"] = current_start_tp()
                return result
        except Exception as exc:
            attempt["error"] = redact_sensitive_error_text(exc)
            attempt["tp_after"] = current_start_tp()
            result["attempts"].append(attempt)
            result["errors"].append(f"carats: {redact_sensitive_error_text(exc)}")

    result["tp_after"] = current_start_tp()
    if not result["errors"] and result["attempted"]:
        result["errors"].append(f"TP recovery did not raise TP enough: {result['tp_after']}/{required_tp}")
    return result

def append_support_id(ids, value):
    try:
        sid = int(value or 0)
    except (TypeError, ValueError):
        sid = 0
    if sid >= 1000 and sid not in ids:
        ids.append(sid)

def debug_scalar(value):
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, str):
        return value[:120]
    return str(value)[:120]

def debug_deck_fields(row):
    if not isinstance(row, dict):
        return {}
    result = {}
    for key, value in row.items():
        key_text = str(key)
        key_lower = key_text.lower()
        include = (
            "deck" in key_lower
            or "card" in key_lower
            or key_lower in {"id", "name", "label", "slot_id"}
            or re.fullmatch(r'.*_id_[1-9]\d*', key_lower)
            or re.fullmatch(r'.*_[1-9]\d*_id', key_lower)
        )
        if not include:
            continue
        if isinstance(value, list):
            result[key_text] = {
                "type": "list",
                "len": len(value),
                "preview": [debug_scalar(item) if not isinstance(item, dict) else {
                    sub_key: debug_scalar(sub_val)
                    for sub_key, sub_val in item.items()
                    if "card" in str(sub_key).lower() or str(sub_key).lower() in {"id", "name"}
                } for item in value[:8]],
            }
        elif isinstance(value, dict):
            result[key_text] = {
                sub_key: debug_scalar(sub_val)
                for sub_key, sub_val in value.items()
                if "card" in str(sub_key).lower() or str(sub_key).lower() in {"id", "name"}
            }
        else:
            result[key_text] = debug_scalar(value)
    return result

def collect_support_ids_from_value(ids, value):
    if isinstance(value, dict):
        append_support_id(ids, value.get('support_card_id') or value.get('card_id') or value.get('id'))
        return
    if isinstance(value, list):
        for item in value:
            collect_support_ids_from_value(ids, item)
        return
    append_support_id(ids, value)

def deck_card_ids(row):
    if not isinstance(row, dict):
        return []
    ids = []
    array_keys = {
        'support_card_id_array', 'support_card_ids', 'support_card_id_list',
        'card_id_array', 'card_ids', 'support_card_array', 'support_cards',
        'cards', 'deck_card_array', 'deck_cards',
    }
    for key in array_keys:
        if key in row:
            collect_support_ids_from_value(ids, row.get(key))
    for key, value in row.items():
        key_text = str(key).lower()
        if key_text in {'deck_id', 'support_card_deck_id', 'select_deck_id'}:
            continue
        if re.fullmatch(r'(support_)?card_id_[1-9]\d*', key_text) or re.fullmatch(r'support_card_id[1-9]\d*', key_text):
            append_support_id(ids, value)
        elif re.fullmatch(r'support_card_[1-9]\d*_id', key_text):
            append_support_id(ids, value)
    return ids

def normalize_deck_row(row, fallback_id=0, source=""):
    cards = deck_card_ids(row)
    if not cards:
        return None
    has_deck_identity = any(key in row for key in ('deck_id', 'support_card_deck_id', 'deck_name', 'name', 'label'))
    if not has_deck_identity and "deck" not in str(source).lower() and len(cards) < 3:
        return None
    deck_id = row.get('deck_id') or row.get('support_card_deck_id') or row.get('id') or row.get('slot_id') or fallback_id
    try:
        deck_id = int(deck_id or fallback_id or 0)
    except (TypeError, ValueError):
        deck_id = fallback_id or 0
    name = row.get('name') or row.get('deck_name') or row.get('label') or f'Deck {deck_id or fallback_id}'
    return {
        "deck_id": deck_id,
        "name": str(name or f"Deck {deck_id or fallback_id}"),
        "support_card_id_array": cards,
        "_source": source,
        "_raw_fields": debug_deck_fields(row),
    }

def debug_deck_summary(deck):
    return {
        "deck_id": deck.get("deck_id"),
        "name": deck.get("name"),
        "source": deck.get("_source", ""),
        "card_count": len(deck.get("support_card_id_array") or []),
        "card_ids": deck.get("support_card_id_array") or [],
        "raw_fields": deck.get("_raw_fields") or {},
    }

def find_deck_rows(data, source_name="root"):
    rows = []
    sources = []
    candidates = []
    seen_objects = set()

    def visit(obj, path):
        marker = id(obj)
        if marker in seen_objects:
            return
        seen_objects.add(marker)
        if isinstance(obj, dict):
            direct = normalize_deck_row(obj, len(rows) + 1, path)
            if direct:
                rows.append(direct)
                candidates.append(debug_deck_summary(direct))
                sources.append({"path": path, "count": 1})
                return
            for key, value in obj.items():
                child_path = f"{path}.{key}" if path else str(key)
                if isinstance(value, list):
                    found = []
                    for index, item in enumerate(value):
                        deck = normalize_deck_row(item, len(rows) + len(found) + 1, f"{child_path}[{index}]")
                        if deck:
                            found.append(deck)
                    if found:
                        rows.extend(found)
                        candidates.extend(debug_deck_summary(deck) for deck in found)
                        sources.append({"path": child_path, "count": len(found)})
                        continue
                if isinstance(value, (dict, list)):
                    visit(value, child_path)
        elif isinstance(obj, list):
            for index, item in enumerate(obj):
                if isinstance(item, (dict, list)):
                    visit(item, f"{path}[{index}]")

    visit(data or {}, source_name)
    deduped = merge_deck_candidate_rows(rows)
    return deduped, {
        "sources": sources,
        "raw_candidates": len(rows),
        "deduped": len(deduped),
        "candidates": candidates,
        "merged": [debug_deck_summary(row) for row in deduped],
    }

def merge_deck_candidate_rows(rows):
    merged = {}
    order = []
    for row in rows or []:
        key = row.get("deck_id") or f"name:{row.get('name')}"
        if key not in merged:
            merged[key] = dict(row)
            merged[key]["support_card_id_array"] = list(row.get("support_card_id_array") or [])
            merged[key]["_source"] = row.get("_source", "")
            merged[key]["_raw_fields"] = dict(row.get("_raw_fields") or {})
            order.append(key)
            continue
        existing = merged[key]
        for sid in row.get("support_card_id_array") or []:
            if sid not in existing["support_card_id_array"]:
                existing["support_card_id_array"].append(sid)
        if row.get("_source") and row.get("_source") not in existing.get("_source", ""):
            existing["_source"] = f"{existing.get('_source', '')}; {row.get('_source')}".strip("; ")
        for raw_key, raw_value in (row.get("_raw_fields") or {}).items():
            existing.setdefault("_raw_fields", {}).setdefault(raw_key, raw_value)
    return [merged[key] for key in order]

def deck_view_rows(deck_rows):
    decks = []
    for deck in deck_rows:
        cards = []
        for cid in deck.get('support_card_id_array', []):
            sid = str(cid)
            info = support_map.get(sid)
            if info:
                cards.append({
                    'id': sid,
                    'name': info['name'],
                    'rarity': info['rarity'],
                    'type': display_support_type(info['type'])
                })
            else:
                cards.append({'id': sid, 'name': f'Unknown ({sid})', 'rarity': '?', 'type': '?'})
        decks.append({
            'id': deck.get('deck_id'),
            'name': deck.get('name', f'Deck {deck.get("deck_id")}'),
            'cards': cards,
            'support_card_ids': [card.get('id') for card in cards if card.get('id')],
            'source': deck.get('_source', '')
        })
    return decks

def deck_overrides_path():
    return dev_runtime_dir() / "deck_overrides.json"

def load_deck_overrides():
    path = deck_overrides_path()
    if not path.exists():
        return {"decks": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"decks": {}}
        decks = data.get("decks")
        if not isinstance(decks, dict):
            data["decks"] = {}
        return data
    except Exception:
        return {"decks": {}}

def save_deck_overrides(data):
    path = deck_overrides_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(data or {})
    payload.setdefault("version", 1)
    payload["updated_at"] = time.time()
    payload.setdefault("instance", sweepy_instance_name())
    payload.setdefault("decks", {})
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{threading.get_ident()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

def _support_view_from_card_id(card_id, support_lookup=None):
    sid = safe_int(card_id)
    if sid <= 0:
        return None
    support_lookup = support_lookup or {}
    owned = support_lookup.get(str(sid)) or support_lookup.get(sid) or {}
    info = support_map.get(str(sid), {})
    return {
        "id": sid,
        "support_card_id": sid,
        "name": owned.get("name") or info.get("name") or f"Unknown ({sid})",
        "rarity": owned.get("rarity") or info.get("rarity") or "?",
        "type": owned.get("type") or display_support_type(info.get("type", "Unknown")),
        "limit_break_count": safe_int(owned.get("limit_break_count")),
        "support_card_level": safe_int(owned.get("support_card_level") or owned.get("level")),
        "stock": safe_int(owned.get("stock")),
    }

def apply_deck_overrides(decks, supports=None):
    overrides = (load_deck_overrides().get("decks") or {})
    if not overrides:
        return decks or []
    support_lookup = {}
    for row in supports or ((active_dashboard_data or {}).get("supports") if isinstance(active_dashboard_data, dict) else []) or []:
        if isinstance(row, dict):
            sid = safe_int(row.get("id") or row.get("support_card_id"))
            if sid:
                support_lookup[str(sid)] = row
    merged = []
    seen = set()
    for deck in decks or []:
        deck_id = safe_int(deck.get("id") or deck.get("deck_id"))
        seen.add(str(deck_id))
        override = overrides.get(str(deck_id))
        if not isinstance(override, dict):
            merged.append(deck)
            continue
        card_ids = clean_int_list(override.get("support_card_ids") or [])
        cards = [
            card
            for card in (_support_view_from_card_id(card_id, support_lookup) for card_id in card_ids)
            if card
        ]
        updated = dict(deck)
        updated["name"] = str(override.get("name") or deck.get("name") or f"Deck {deck_id}")
        updated["cards"] = cards
        updated["support_card_ids"] = card_ids
        updated["edited"] = True
        if "synced_support_card_ids" in override:
            updated["synced_support_card_ids"] = clean_int_list(override.get("synced_support_card_ids") or [])
        if override.get("synced_name"):
            updated["synced_name"] = str(override.get("synced_name") or "")
        updated["source"] = f"{deck.get('source', '')} local_edit".strip()
        merged.append(updated)
    for key, override in overrides.items():
        if key in seen or not isinstance(override, dict):
            continue
        deck_id = safe_int(override.get("deck_id") or key)
        if not deck_id:
            continue
        card_ids = clean_int_list(override.get("support_card_ids") or [])
        cards = [
            card
            for card in (_support_view_from_card_id(card_id, support_lookup) for card_id in card_ids)
            if card
        ]
        merged.append({
            "id": deck_id,
            "name": str(override.get("name") or f"Deck {deck_id}"),
            "cards": cards,
            "support_card_ids": card_ids,
            "synced_support_card_ids": clean_int_list(override.get("synced_support_card_ids") or []),
            "synced_name": str(override.get("synced_name") or ""),
            "edited": True,
            "source": "local_edit",
        })
    return merged

def merge_dashboard_decks(deck_rows, debug=None):
    global active_dashboard_data, active_deck_debug
    supports = (active_dashboard_data or {}).get("supports") if isinstance(active_dashboard_data, dict) else []
    decks = apply_deck_overrides(deck_view_rows(deck_rows), supports)
    if debug is not None:
        active_deck_debug = debug
    if active_dashboard_data is not None and decks:
        active_dashboard_data["decks"] = decks
        active_dashboard_data["deckDebug"] = active_deck_debug
    return decks


def get_account_status(data, career_data=None):
    tp_info = data.get('tp_info') or {}
    coin_info = data.get('coin_info') or {}
    item_list = data.get('item_list') or data.get('user_item_array') or []
    career = data.get('single_mode_chara_light') or None
    
    if career_data and career_data.get('chara_info'):
        career = career_data.get('chara_info')

    status = {
        "tp": tp_account_view(tp_info),
        "carrots": {
            "free": coin_info.get('fcoin', 0) or 0,
            "paid": coin_info.get('coin', 0) or 0,
            "total": (coin_info.get('fcoin', 0) or 0) + (coin_info.get('coin', 0) or 0)
        },
        "gold": get_item_count(item_list, 59),
        "toughness": get_item_count(item_list, 32),
        "career": None
    }

    if career:
        card_id = str(career.get('card_id', ''))
        
        p1 = career.get('succession_trained_chara_id_1')
        p2 = career.get('succession_trained_chara_id_2')

        friend_viewer_id = None
        friend_card_id = None
        current_deck_cards = []
        
        support_array = career.get('support_card_array') or []
        for sc in support_array:
            pos = sc.get('position')
            if pos == 6:
                friend_viewer_id = sc.get('owner_viewer_id')
                friend_card_id = sc.get('support_card_id')
            elif 1 <= pos <= 5:
                current_deck_cards.append(sc.get('support_card_id'))

        matched_deck_id = None
        user_decks = data.get('support_card_deck_array') or []
        if current_deck_cards:
            current_deck_set = set(current_deck_cards)
            for deck in user_decks:
                deck_cards = deck.get('support_card_id_array') or []
                if set(deck_cards) == current_deck_set:
                    matched_deck_id = deck.get('deck_id')
                    break

        status["career"] = {
            "active": True,
            "card_id": card_id,
            "name": chara_map.get(card_id, f"Unknown ({card_id})"),
            "turn": career.get('turn', 0),
            "scenario_id": career.get('scenario_id', 0),
            "fans": career.get('fans', 0),
            "vital": career.get('vital', 0),
            "max_vital": career.get('max_vital', 0),
            "motivation": career.get('motivation', 0),
            "speed": career.get('speed', 0),
            "stamina": career.get('stamina', 0),
            "power": career.get('power', 0),
            "guts": career.get('guts', 0),
            "wit": career.get('wiz', 0),
            "skill_point": career.get('skill_point', 0),
            "deck_id": matched_deck_id,
            "friend_viewer_id": friend_viewer_id,
            "friend_card_id": friend_card_id,
            "parent_id_1": p1,
            "parent_id_2": p2,
        }

    return status

def preserve_missing_career_fields(account, prior_account):
    career = (account or {}).get("career")
    prior = (prior_account or {}).get("career") or {}
    if not isinstance(career, dict) or not isinstance(prior, dict):
        return account
    for key in ("deck_id", "friend_viewer_id", "friend_card_id", "parent_id_1", "parent_id_2"):
        if career.get(key) in (None, "", 0) and prior.get(key) not in (None, "", 0):
            career[key] = prior.get(key)
    return account

def endpoint_clears_active_career(endpoint, data):
    endpoint = (endpoint or "").lstrip("/")
    if endpoint == "load/index":
        return not (data or {}).get('single_mode_chara_light') and not (data or {}).get('single_mode_chara')
    return endpoint in {
        "single_mode_free/finish",
        "single_mode/finish",
        "single_mode_team/finish",
        "single_mode_free/delete",
    }

def sync_game_data_from_api_response(endpoint, response, source="api"):
    global active_account, active_dashboard_data
    if not isinstance(response, dict):
        return None
    response_code = response.get("response_code")
    result_code = (response.get("data_headers") or {}).get("result_code")
    if response_code is not None and int_or_zero(response_code) not in (0, 1):
        return None
    if result_code is not None and int_or_zero(result_code) not in (0, 1):
        return None
    data = response.get("data") or {}
    if not isinstance(data, dict):
        return None

    with state_sync_lock:
        if active_client and hasattr(active_client, "refresh_resource_state_from_response"):
            active_client.refresh_resource_state_from_response(response)
        update_start_state(data)
        apply_tp_timer_to_cached_state()

        prior_account = active_account or ((active_dashboard_data or {}).get("account") if active_dashboard_data else None) or {}
        account_source = dict(active_start_state)
        if data.get("single_mode_chara_light"):
            account_source["single_mode_chara_light"] = data.get("single_mode_chara_light")
        if data.get("support_card_deck_array"):
            account_source["support_card_deck_array"] = data.get("support_card_deck_array")

        career_data = data if data.get("chara_info") else None
        account = get_account_status(account_source, career_data)
        if career_data:
            account = preserve_missing_career_fields(account, prior_account)
        elif endpoint_clears_active_career(endpoint, data):
            account["career"] = None
        elif prior_account.get("career"):
            account["career"] = prior_account.get("career")

        active_account = account
        if active_dashboard_data is not None:
            active_dashboard_data["account"] = account
        return account


def build_dashboard_data(load_data, career_data=None, preserve_friends=True):
    global active_account, active_dashboard_data, active_parent_cards, active_parent_rank_points, active_deck_debug
    account = get_account_status(load_data, career_data)
    active_account = account
    update_start_state(load_data)
    apply_tp_timer_to_cached_state()

    umas = []
    for card in load_data.get('card_list', []):
        cid = str(card.get('card_id', card.get('id', '')))
        umas.append({
            'id': cid,
            'name': chara_map.get(cid, f"Unknown ({cid})")
        })

    supports = support_rows_from_load_data(load_data)

    deck_rows, deck_debug = find_deck_rows(load_data, "load_index")
    active_deck_debug = deck_debug
    decks = apply_deck_overrides(deck_view_rows(deck_rows), supports)

    global seen_trained_chara_ids, most_recent_trained_chara_id
    active_parent_cards = {}
    active_parent_rank_points = {}
    parents = []
    current_trained_ids = set()
    for chara in load_data.get('trained_chara', []):
        raw_id = str(chara.get('card_id', ''))
        if '{' in raw_id or '-' in raw_id or not raw_id.isdigit():
            found = False
            for value in chara.values():
                val_str = str(value)
                if val_str.isdigit() and len(val_str) >= 4:
                    raw_id = val_str
                    found = True
                    break
            if not found:
                continue

        cid = raw_id
        self_win_data = get_race_record_data(chara)
        tree = {
            "self": {"card_id": cid, "name": chara_map.get(cid, f"Unknown ({cid})"), "factors": [], "wins": self_win_data["summary"], "win_saddle_ids": self_win_data["saddle_ids"], "win_race_ids": self_win_data["race_ids"], "race_history": self_win_data["history"]},
            "p1": {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([]), "win_saddle_ids": [], "win_race_ids": [], "race_history": []},
            "p2": {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([]), "win_saddle_ids": [], "win_race_ids": [], "race_history": []},
            "gp1": {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([]), "win_saddle_ids": [], "win_race_ids": [], "race_history": []},
            "gp2": {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([]), "win_saddle_ids": [], "win_race_ids": [], "race_history": []},
            "gp3": {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([]), "win_saddle_ids": [], "win_race_ids": [], "race_history": []},
            "gp4": {"card_id": 0, "name": "", "factors": [], "wins": get_win_summary([]), "win_saddle_ids": [], "win_race_ids": [], "race_history": []}
        }
        tree["self"]["factors"] = get_factors(get_chara_factor_ids(chara), cid)

        for sc in chara.get('succession_chara_array', []):
            pos = sc.get('position_id')
            key = ""
            if pos == 10:
                key = "p1"
            elif pos == 20:
                key = "p2"
            elif pos == 11:
                key = "gp1"
            elif pos == 12:
                key = "gp2"
            elif pos == 21:
                key = "gp3"
            elif pos == 22:
                key = "gp4"

            if key:
                sc_cid = sc.get('card_id', 0)
                win_data = get_race_record_data(sc)
                tree[key]["card_id"] = sc_cid
                tree[key]["name"] = chara_map.get(str(sc_cid), f"Unknown ({sc_cid})")
                tree[key]["factors"] = get_factors(sc.get('factor_id_array', []), sc_cid)
                tree[key]["wins"] = win_data["summary"]
                tree[key]["win_saddle_ids"] = win_data["saddle_ids"]
                tree[key]["win_race_ids"] = win_data["race_ids"]
                tree[key]["race_history"] = win_data["history"]

        instance_id = int(chara.get('trained_chara_id') or 0)
        if instance_id:
            current_trained_ids.add(instance_id)
        skill_rows = get_skill_rows(chara.get('skill_array') or [])
        estimated_skill_points = get_estimated_skill_points(skill_rows)
        stats = get_trained_chara_stats(chara)
        stats["estimated_skill_points"] = estimated_skill_points
        parents.append({
            'instance_id': instance_id,
            'card_id': cid,
            'name': chara_map.get(cid, f"Unknown ({cid})"),
            'rank': chara.get('rank', 0),
            'score': chara.get('rank_score', 0),
            'stats': stats,
            'skills': skill_rows,
            'skill_array': chara.get('skill_array') or [],
            'estimated_skill_points': estimated_skill_points,
            'tree': tree
        })
        lineage_cards = [int(cid)]
        for sc in chara.get('succession_chara_array', []) or []:
            sc_cid = sc.get('card_id', 0)
            if sc_cid:
                lineage_cards.append(int(sc_cid))
        if instance_id:
            active_parent_cards[instance_id] = lineage_cards
            active_parent_rank_points[instance_id] = {
                'rank': chara.get('rank', 0),
                'rank_score': chara.get('rank_score', 0)
            }

    if seen_trained_chara_ids is None:
        seen_trained_chara_ids = set(current_trained_ids)
    else:
        new_ids = current_trained_ids - seen_trained_chara_ids
        if new_ids:
            most_recent_trained_chara_id = max(new_ids)
            seen_trained_chara_ids = set(current_trained_ids)
    if most_recent_trained_chara_id:
        for parent in parents:
            if parent.get('instance_id') == most_recent_trained_chara_id:
                parent['is_new'] = True
                break

    try:
        parents = annotate_parents(DIR, parents)
        write_parent_library_snapshot(DIR, parents)
    except Exception as exc:
        print(f"parent memory update failed: {exc}", flush=True)

    cached = active_dashboard_data if preserve_friends and active_dashboard_data else {}
    daily_event_status = summarize_daily_event_status(load_data)
    try:
        daily_cfg = DailyAutomationConfig.load(base_dir / "data" / "daily_automation_endpoints.json")
        daily_event_status.setdefault("shops", {}).setdefault("configured_shop_count", daily_cfg.configured_shop_count())
        daily_event_status["configured_actions"] = sorted(
            name
            for name, cfg in ((daily_cfg.data.get("actions") or {}).items())
            if isinstance(cfg, dict) and cfg and name != "daily_shops"
        )
    except Exception:
        pass

    dashboard = {
        "success": True,
        "account": account,
        "umas": umas,
        "supports": supports,
        "decks": decks,
        "deckDebug": active_deck_debug,
        "parents": parents,
        "borrow_quota": compute_borrow_quota(active_client) if active_client else None,
        "dailyEvents": daily_event_status,
    }
    for key in ("friends", "friendsList", "friendFollowQuota", "friendExcludeIds", "friendsLoaded", "borrow_umas"):
        if key in cached:
            dashboard[key] = cached[key]
    active_dashboard_data = dashboard
    return dashboard


def support_rows_from_load_data(load_data):
    supports = []
    for s in load_data.get('support_card_list', []):
        sid = str(s.get('support_card_id', s.get('id', '')))
        info = support_map.get(sid)
        if info:
            supports.append({
                'id': sid,
                'name': info['name'],
                'type': display_support_type(info['type']),
                'rarity': info['rarity'],
                'exp': int(s.get('exp') or 0),
                'limit_break_count': int(s.get('limit_break_count') or 0),
                'stock': int(s.get('stock') or 0),
                'support_card_level': int(s.get('level') or s.get('support_card_level') or 0),
            })
        else:
            supports.append({
                'id': sid,
                'name': f"Unknown ({sid})",
                'type': 'Unknown',
                'rarity': '?',
                'exp': int(s.get('exp') or 0),
                'limit_break_count': int(s.get('limit_break_count') or 0),
                'stock': int(s.get('stock') or 0),
                'support_card_level': int(s.get('level') or s.get('support_card_level') or 0),
            })
    return supports


def support_limit_break_plan_from_load_data(load_data):
    plan = []
    for raw in (load_data or {}).get("support_card_list", []) or []:
        support_card_id = safe_int(raw.get("support_card_id") or raw.get("id") or 0)
        if support_card_id <= 0:
            continue
        current_lb = max(0, min(4, safe_int(raw.get("limit_break_count") or 0)))
        stock = max(0, safe_int(raw.get("stock") or 0))
        available_steps = max(0, min(stock, 4 - current_lb))
        if available_steps <= 0:
            continue
        info = support_map.get(str(support_card_id), {}) or {}
        plan.append({
            "support_card_id": support_card_id,
            "name": info.get("name") or f"Card {support_card_id}",
            "rarity": info.get("rarity") or "?",
            "type": display_support_type(info.get("type") or "Unknown"),
            "current_limit_break_count": current_lb,
            "stock": stock,
            "available_steps": available_steps,
        })
    plan.sort(key=lambda row: (safe_int(row.get("support_card_id")), row.get("name") or ""))
    return plan


def reconcile_active_selection():
    global active_selection
    data = active_dashboard_data or {}
    deck_ids = {str(deck.get("id")) for deck in data.get("decks", [])}
    uma_ids = {str(uma.get("id")) for uma in data.get("umas", [])}
    parent_ids = {str(parent.get("instance_id")) for parent in data.get("parents", [])}
    friend_keys = {
        (str(friend.get("viewer_id")), str(friend.get("support_card_id")))
        for friend in data.get("friends", [])
    }
    selection = dict(active_selection or {})
    if selection.get("deck") and str(selection["deck"].get("id")) not in deck_ids:
        selection["deck"] = None
    if selection.get("trainee") and str(selection["trainee"].get("id")) not in uma_ids:
        selection["trainee"] = None
    selection["veterans"] = [
        parent for parent in selection.get("veterans", [])
        if str(parent.get("instance_id")) in parent_ids
    ]
    friend = selection.get("friend")
    if friend and friend_keys and (str(friend.get("viewer_id")), str(friend.get("support_card_id"))) not in friend_keys:
        selection["friend"] = None
    # Reconcile guestParent: drop only if borrow_umas is loaded AND the saved guest
    # is no longer in the borrow pool (server may rotate the daily lineup).
    borrow_umas = data.get("borrow_umas") or []
    if borrow_umas:
        borrow_keys = {(str(u.get("viewer_id")), str(u.get("trained_chara_id"))) for u in borrow_umas}
        guest = selection.get("guestParent")
        if guest and (str(guest.get("viewer_id")), str(guest.get("trained_chara_id"))) not in borrow_keys:
            selection["guestParent"] = None
    active_selection = selection
    return active_selection



class LoginRequest(BaseModel):
    username: str = ""
    password: str = ""
    code: str = ""
    steam_id: str = ""
    steam_session_ticket: str = ""
    steam_app_id: str = ""

class ReusableAuthLoginRequest(BaseModel):
    steam_id: str = ""

class DeleteCareerRequest(BaseModel):
    current_turn: int = 0

class StartCareerRequest(BaseModel):
    card_id: int
    support_card_ids: list[int]
    friend_viewer_id: int
    friend_card_id: int
    parent_id_1: int
    parent_id_2: int
    scenario_id: int = 4
    deck_id: int = 1
    use_tp: int = 30
    difficulty_id: int = 0
    difficulty: int = 0
    is_boost: int = 0
    boost_story_event_id: int = 0
    allow_recover_tp: int = 0
    rental_viewer_id: int = 0
    rental_trained_chara_id: int = 0
    borrow_fallback_id: int = 0

class RunCareerRequest(BaseModel):
    card_id: int = 0
    support_card_ids: list[int] = []
    friend_viewer_id: int = 0
    friend_card_id: int = 0
    parent_id_1: int = 0
    parent_id_2: int = 0
    scenario_id: int = 4
    deck_id: int = 1
    use_tp: int = 30
    difficulty_id: int = 0
    difficulty: int = 0
    is_boost: int = 0
    boost_story_event_id: int = 0
    allow_recover_tp: int = 0
    rental_viewer_id: int = 0
    rental_trained_chara_id: int = 0
    borrow_fallback_id: int = 0
    preset_name: str = ""
    max_steps: int = 2500
    loop_enabled: bool = False
    loop_count: int = 1
    loop_mode: str = "forever"
    loop_career_limit: int = 0
    loop_fan_limit: int = 0

class DailyAutomationRequest(BaseModel):
    run_team_trials_once: bool = False
    run_daily_race: bool = False
    run_legend_race: bool = False
    run_daily_legend_race: bool = False
    drain_daily_shops: bool = False
    legend_race_id: int = 0
    daily_race_id: int = 0
    daily_legend_race_id: int = 0
    trained_chara_id: int = 0
    running_style: int | str = 0
    difficulty_id: int = 0
    difficulty: int = 0
    is_boost: int = 0
    assignments: dict = Field(default_factory=dict)

class SaveDeckRequest(BaseModel):
    deck_id: int
    support_card_ids: list[int] = []
    name: str = ""
    clear_override: bool = False

class SaveRacesRequest(BaseModel):
    preset_name: str = ""
    races: list[int]
    styles: dict[str, str] = {}

class SaveRacePlanTextRequest(BaseModel):
    preset_name: str = ""
    text: str = ""
    styles: dict[str, str] = {}

class SaveSkillPlanRequest(BaseModel):
    preset_name: str = ""
    buy_on_sight: list[str] | str = []
    blacklist: list[str] | str = []
    style: str = ""
    distance: str = ""
    buy_timing: str = "end_of_career"
    desired_sparks: dict = {}
    alarm_clock_mode: str = ""
    alarm_clock_limit: int | None = None

class SaveRaceContinueRequest(BaseModel):
    preset_name: str = ""
    mode: str = "normal"
    limit: int = 5

class SavePlannerProfileRequest(BaseModel):
    preset_name: str = ""
    profile_name: str = ""
    profile: dict = {}

class LoadPlannerProfileRequest(BaseModel):
    preset_name: str = ""
    profile_name: str = ""
    profile: dict = {}

class SavePresetRequest(BaseModel):
    preset: dict

class DeletePresetByNameRequest(BaseModel):
    name: str

class SaveTeamBundlePresetRequest(BaseModel):
    name: str = ""
    preset: dict = {}

class DeleteTeamBundlePresetRequest(BaseModel):
    name: str = ""

class CareerActionRequest(BaseModel):
    command_type: int
    command_id: int
    current_turn: int
    current_vital: int
    command_group_id: int = 0
    select_id: int = 0

class FriendListRequest(BaseModel):
    exclude_viewer_ids: list[int] = []
    force_refresh: bool = False


class FriendIdRequest(BaseModel):
    viewer_id: int

class ApiDelayRequest(BaseModel):
    min: float = 1.6
    max: float = 4.0
    disabled: bool = False

class ProfileDatasetIngestRequest(BaseModel):
    recent_files: int = 5
    limit: int = 1000
    include_self: bool = False
    instance_name: str = ""

class ProfileDatasetProbeRequest(BaseModel):
    viewer_ids: list[int] = []
    exclude_viewer_ids: list[int] = []
    include_pre_single_mode: bool = True
    include_friend_index: bool = True
    max_viewer_ids: int = 5


class ApiDiscoveryCaptureRequest(BaseModel):
    label: str = ""
    note: str = ""
    endpoints: list[str] = []


class ApiDiscoveryProbeRequest(BaseModel):
    label: str = "probe"
    endpoints: list[str] = []
    note: str = ""

@app.get("/api/settings/turn-delay")
async def get_turn_delay_settings():
    return get_turn_delay()

@app.post("/api/settings/turn-delay")
async def set_turn_delay_settings(req: ApiDelayRequest):
    return set_turn_delay(req.min, req.max, req.disabled)


# --- Learning session endpoints --------------------------------------------
# Backend storage for the per-session objective declarations described in
# docs/objective-aware-learning-v2.md. The capture tool reads from
# `data/learning_sessions/current_session.json`; this set of endpoints lets
# the dashboard read/write it without touching disk directly. Presets live
# alongside as named JSON files in the same directory.

def _learning_sessions_dir():
    path = base_dir / "data" / "learning_sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _learning_session_current_path():
    return _learning_sessions_dir() / "current_session.json"


def _learning_session_preset_path(name):
    safe_name = "".join(ch for ch in str(name) if ch.isalnum() or ch in "-_") or "preset"
    return _learning_sessions_dir() / f"preset_{safe_name}.json"


def _learning_session_popup_path():
    return _learning_sessions_dir() / "popup_setting.json"


def _read_popup_enabled():
    """Default: popup enabled. File is `{"enabled": false}` when the user
    has dismissed via the modal checkbox."""
    import json as _json
    path = _learning_session_popup_path()
    if not path.exists():
        return True
    try:
        data = _json.loads(path.read_text(encoding="utf-8"))
        return bool(data.get("enabled", True))
    except Exception:
        return True


def _write_learning_session_file(path, data):
    """Atomic write with per-process .tmp + retry, same pattern as parent_memory."""
    import json as _json
    import os as _os
    import time as _time
    serialized = _json.dumps(data or {}, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(f"{path.suffix}.{_os.getpid()}.tmp")
    tmp.write_text(serialized, encoding="utf-8")
    last_exc = None
    for attempt in range(3):
        try:
            _os.replace(tmp, path)
            last_exc = None
            break
        except PermissionError as exc:
            last_exc = exc
            _time.sleep(0.15 * (attempt + 1))
    if last_exc is not None:
        path.write_text(serialized, encoding="utf-8")
        try:
            tmp.unlink()
        except Exception:
            pass


def _mirror_session_to_hachimi(data):
    """Copy the declared session into every discoverable hachimi folder.

    The DLL auto-detects `<hachimi_dir>/current_session.json` when no
    explicit `learning_session_path` is set in `sweepy_capture_config.json`,
    so writing here is what makes the drag-and-drop install zero-config.
    Silent on errors — the project-local current_session.json is still the
    primary source; the hachimi mirror is a convenience copy.
    """
    try:
        from career_bot.learning import _hachimi_capture_career_dirs
        career_dirs = _hachimi_capture_career_dirs()
    except Exception:
        return
    for career_dir in career_dirs:
        hachimi_root = Path(career_dir).parent  # parent of "Career turn data"
        try:
            hachimi_root.mkdir(parents=True, exist_ok=True)
            _write_learning_session_file(hachimi_root / "current_session.json", data)
        except Exception:
            continue


@app.get("/api/learning_session/current")
async def get_current_learning_session():
    import json as _json
    path = _learning_session_current_path()
    if not path.exists():
        return {"session": None}
    try:
        return {"session": _json.loads(path.read_text(encoding="utf-8"))}
    except Exception as exc:
        return {"session": None, "error": str(exc)}


@app.post("/api/learning_session/declare")
async def declare_learning_session(req: dict):
    from career_bot.objectives import normalize_session
    session = normalize_session(req or {})
    _write_learning_session_file(_learning_session_current_path(), session)
    _mirror_session_to_hachimi(session)
    return {"success": True, "session": session}


@app.post("/api/learning_session/clear")
async def clear_learning_session():
    path = _learning_session_current_path()
    if path.exists():
        try:
            path.unlink()
        except Exception as exc:
            return {"success": False, "detail": str(exc)}
    # Mirror clear: remove the hachimi-side copy too so the DLL doesn't keep
    # applying a stale session to new careers.
    try:
        from career_bot.learning import _hachimi_capture_career_dirs
        for career_dir in _hachimi_capture_career_dirs():
            mirror = Path(career_dir).parent / "current_session.json"
            if mirror.exists():
                try:
                    mirror.unlink()
                except Exception:
                    pass
    except Exception:
        pass
    return {"success": True}


@app.get("/api/learning_session/popup_setting")
async def get_learning_session_popup_setting():
    return {"enabled": _read_popup_enabled()}


@app.post("/api/learning_session/popup_setting")
async def set_learning_session_popup_setting(req: dict):
    """Persist the popup-enabled flag. When disabled, also clear the active
    session so the DLL routes subsequent careers to 'Unlabelled runs'."""
    enabled = bool((req or {}).get("enabled", True))
    _write_learning_session_file(_learning_session_popup_path(), {"enabled": enabled})
    if not enabled:
        # Clear current session + the hachimi mirrors so the DLL sees no
        # session and routes new careers to the Unlabelled runs subfolder.
        path = _learning_session_current_path()
        if path.exists():
            try:
                path.unlink()
            except Exception:
                pass
        try:
            from career_bot.learning import _hachimi_capture_career_dirs
            for career_dir in _hachimi_capture_career_dirs():
                mirror = Path(career_dir).parent / "current_session.json"
                if mirror.exists():
                    try:
                        mirror.unlink()
                    except Exception:
                        pass
        except Exception:
            pass
    return {"success": True, "enabled": enabled}


@app.get("/api/learning_session/pending_intent")
async def get_pending_run_intent():
    """Tells the dashboard whether a fresh career folder has appeared
    without an attached session, so it can show the run-intent modal.
    Returns {needs_intent: bool, career_name: str|None, folder: str|None}.
    Watcher applies the popup-disabled and session-declared filters."""
    global _session_sidecar_watcher
    if _session_sidecar_watcher is None:
        return {"needs_intent": False, "career_name": None, "folder": None}
    try:
        return _session_sidecar_watcher.pending_intent()
    except Exception:
        return {"needs_intent": False, "career_name": None, "folder": None}


@app.get("/api/learning_session/presets")
async def list_learning_session_presets():
    import json as _json
    presets = []
    for path in sorted(_learning_sessions_dir().glob("preset_*.json")):
        try:
            data = _json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        presets.append({
            "name": path.stem.removeprefix("preset_"),
            "session_id": (data or {}).get("session_id"),
            "session": data,
        })
    return {"presets": presets}


@app.post("/api/learning_session/presets")
async def save_learning_session_preset(req: dict):
    from career_bot.objectives import normalize_session
    name = str((req or {}).get("name") or "").strip()
    if not name:
        return {"success": False, "detail": "name required"}
    session = normalize_session((req or {}).get("session") or {})
    _write_learning_session_file(_learning_session_preset_path(name), session)
    return {"success": True, "name": name, "session": session}


# Quick-declare: the minimal "what's this run for" prompt. Just stat + style.
# The full objective JSON gets filled out with sensible defaults derived from
# the empirical spark-rate thresholds, so the user doesn't have to touch the
# big session JSON shape unless they want fine control.
_STAT_LABELS = {
    "speed": "speed",
    "spd": "speed",
    "stamina": "stamina",
    "stam": "stamina",
    "sta": "stamina",
    "power": "power",
    "pwr": "power",
    "pow": "power",
    "guts": "guts",
    "gut": "guts",
    "wit": "wit",
    "wis": "wit",
    "wiz": "wit",
}

_STYLE_LABELS = {
    "front_runner": "front_runner",
    "front": "front_runner",
    "nige": "front_runner",
    "pace_chaser": "pace_chaser",
    "pace": "pace_chaser",
    "senko": "pace_chaser",
    "late_surger": "late_surger",
    "late": "late_surger",
    "sashi": "late_surger",
    "end_closer": "end_closer",
    "end": "end_closer",
    "closer": "end_closer",
    "oikomi": "end_closer",
}


def _normalize_stat(raw):
    return _STAT_LABELS.get(str(raw or "").strip().lower())


def _normalize_style(raw):
    return _STYLE_LABELS.get(str(raw or "").strip().lower())


def _build_session_from_quick(stat, style, session_id=None, notes=None):
    """Expand the minimal stat+style prompt into a full session object using
    the empirical thresholds (1100+ stat enters the 20/70/10 blue star band,
    17500+ rank score enters the 20/70/10 white band)."""
    from career_bot.objectives import normalize_session

    stat = _normalize_stat(stat) or "wit"
    style = _normalize_style(style) or "front_runner"
    if not session_id:
        from datetime import datetime as _dt
        session_id = f"quick_{stat}_{style}_{_dt.now().strftime('%Y%m%d_%H%M')}"
    session = {
        "session_id": session_id,
        "operator_notes": notes or "",
        "primary_stat_target": {
            "stat": stat,
            "target_value": 1100,
            "ideal_value": 1180,
        },
        "blue_spark_intent": {
            "preferred_color": stat,
            "acceptable_colors": [s for s in ("speed", "stamina", "power", "guts", "wit") if s != stat],
            "minimum_star_level": 2,
        },
        "white_spark_intent": {
            "minimum_count": 6,
            "high_value_targets": [],
            "preferred_targets_from_schedule": [],
            "target_rank_score_band": "high",
        },
        "stat_minimums": {
            "speed": 600,
            "stamina": 500,
            "power": 600,
            "guts": 400,
            "wit": 500,
        },
        "race_intent": {
            "treat_wins_as_negative": False,
            "expected_losses": [],
            "must_win": [],
        },
        "lineage_intent": {
            "target_affinity_tier": "high",
            "lineage_overlap_targets": [],
        },
        "acceptable_drift": ["balanced_parent_with_wrong_blue"],
        "deck_id": None,
        "style_target": style,
    }
    # Bump the primary stat minimum to match the target band.
    session["stat_minimums"][stat] = 1100
    return normalize_session(session)


@app.post("/api/learning_session/quick_declare")
async def quick_declare_learning_session(req: dict):
    """Minimal prompt: { stat, style, session_id?, notes? }. Builds the full
    session object from defaults and saves it. This is the endpoint the
    manual-run popup should hit, not the full /declare endpoint."""
    req = req or {}
    stat = _normalize_stat(req.get("stat"))
    style = _normalize_style(req.get("style"))
    if not stat:
        return {"success": False, "detail": f"stat must be one of speed/stamina/power/guts/wit (got {req.get('stat')!r})"}
    if not style:
        return {"success": False, "detail": f"style must be one of front_runner/pace_chaser/late_surger/end_closer (got {req.get('style')!r})"}
    session = _build_session_from_quick(stat, style, session_id=req.get("session_id"), notes=req.get("notes"))
    _write_learning_session_file(_learning_session_current_path(), session)
    _mirror_session_to_hachimi(session)
    return {"success": True, "session": session}



def clamp_percent(value, default=0):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = int(default or 0)
    return max(0, min(parsed, 100))


def sanitize_desired_parent_sparks(value):
    value = value or {}
    if not isinstance(value, dict):
        value = {}
    aliases = {
        "red": "pink",
        "aptitude": "pink",
        "stat": "blue",
        "unique": "green",
        "skill": "white",
        "race": "white",
        "scenario": "white",
    }
    result = {"blue": [], "pink": [], "green": [], "white": []}
    for raw_key, raw_value in value.items():
        key = aliases.get(str(raw_key or "").strip().lower(), str(raw_key or "").strip().lower())
        if key not in result:
            continue
        rows = split_skill_text(raw_value)
        cleaned = []
        seen = set()
        for row in rows:
            text = str(row or "").strip()
            folded = text.lower()
            if not text or folded in seen:
                continue
            seen.add(folded)
            cleaned.append(text)
        result[key] = cleaned
    return result


def planner_profiles_dir():
    path = Path(DIR) / "data" / "planner_profiles"
    path.mkdir(parents=True, exist_ok=True)
    return path


def planner_profile_path(name):
    safe_name = slugify(name or "planner_profile")
    return planner_profiles_dir() / f"{safe_name}.json"


def planner_profile_skill_section(raw):
    if isinstance(raw, dict) and isinstance(raw.get("skill_plan"), dict):
        return raw.get("skill_plan") or {}
    return raw if isinstance(raw, dict) else {}


def planner_profile_race_section(raw):
    if isinstance(raw, dict) and isinstance(raw.get("race_scheduler"), dict):
        return raw.get("race_scheduler") or {}
    return raw if isinstance(raw, dict) else {}


def planner_profile_alarm_limit(raw_skill, raw_root):
    try:
        raw_limit = raw_skill.get(
            "alarm_clock_limit",
            raw_root.get("alarm_clock_use_limit", raw_root.get("clock_use_limit", 0)),
        )
        limit = max(0, min(int(raw_limit or 0), 5))
    except (TypeError, ValueError):
        limit = 0
    return limit


def normalize_planner_profile_race_entries(entries):
    normalized = []
    if not isinstance(entries, list):
        return normalized
    entries_by_turn = {}
    for raw_entry in entries:
        if not isinstance(raw_entry, dict):
            continue
        try:
            race_id = int(
                raw_entry.get("race_id", raw_entry.get("id", raw_entry.get("raceId", 0))) or 0
            )
        except (TypeError, ValueError):
            race_id = 0
        if race_id <= 0:
            continue
        race = race_catalog.by_id.get(race_id)
        if not race:
            continue
        raw_style = raw_entry.get("style", raw_entry.get("selectedStyle", raw_entry.get("tactic", raw_entry.get("strategy", ""))))
        entry = race_catalog.entry_from_race(
            race,
            normalize_race_style(raw_style),
            "planner_profile",
        )
        turn = int(entry.get("turn") or 0)
        if turn:
            entries_by_turn[turn] = entry
    normalized = sorted(
        entries_by_turn.values(),
        key=lambda item: (int(item.get("turn") or 0), int(item.get("race_id") or 0)),
    )
    return normalized


def planner_profile_entries_from_race_ids(race_ids, styles=None):
    styles = styles if isinstance(styles, dict) else {}
    entries = []
    seen_turns = {}
    for raw_race_id in race_ids or []:
        try:
            race_id = int(raw_race_id)
        except (TypeError, ValueError):
            continue
        race = race_catalog.by_id.get(race_id)
        if not race:
            continue
        raw_style = styles.get(str(race_id), styles.get(race_id, ""))
        entry = race_catalog.entry_from_race(race, normalize_race_style(raw_style), "planner_profile")
        turn = int(entry.get("turn") or 0)
        if turn:
            seen_turns[turn] = entry
    entries = sorted(
        seen_turns.values(),
        key=lambda item: (int(item.get("turn") or 0), int(item.get("race_id") or 0)),
    )
    return entries


def normalize_planner_profile(raw_profile=None, profile_name="", source_preset_name=""):
    raw_profile = raw_profile if isinstance(raw_profile, dict) else {}
    raw_skill = planner_profile_skill_section(raw_profile)
    raw_races = planner_profile_race_section(raw_profile)
    buy_on_sight = split_skill_text(
        raw_skill.get("final_priorities", raw_skill.get("buy_on_sight", raw_profile.get("skill_buy_on_sight", [])))
    )
    blacklist = sanitize_blacklist(
        raw_skill.get(
            "blacklist",
            raw_profile.get("skill_blacklist_custom", raw_profile.get("learn_skill_blacklist", [])),
        )
    )
    style = normalize_skill_style(
        raw_skill.get("style", raw_profile.get("skill_profile_style", ""))
    )
    distance = normalize_skill_distance(
        raw_skill.get("distance", raw_profile.get("skill_profile_distance", ""))
    )
    buy_timing = str(
        raw_skill.get(
            "buy_timing",
            "throughout" if raw_profile.get("manual_purchase_at_end") is False else "end_of_career",
        )
        or "end_of_career"
    ).strip().lower()
    if buy_timing != "throughout":
        buy_timing = "end_of_career"
    desired_sparks = sanitize_desired_parent_sparks(
        raw_skill.get("desired_sparks", raw_profile.get("desired_parent_sparks"))
    )
    alarm_clock_mode = normalize_alarm_clock_mode(
        raw_skill.get("alarm_clock_mode", raw_profile.get("alarm_clock_mode", ""))
    )
    alarm_clock_limit = planner_profile_alarm_limit(raw_skill, raw_profile)
    if alarm_clock_mode == "none" or alarm_clock_limit <= 0:
        alarm_clock_mode = "none"
        alarm_clock_limit = 0

    custom_schedule = normalize_planner_profile_race_entries(
        raw_races.get("custom_race_schedule", raw_profile.get("custom_race_schedule"))
    )
    race_plan_text = str(raw_races.get("race_plan_text", raw_profile.get("race_plan_text", "")) or "")
    if not custom_schedule:
        custom_schedule = planner_profile_entries_from_race_ids(
            raw_races.get(
                "selected_race_ids",
                raw_races.get("race_ids", raw_profile.get("extra_race_list", raw_profile.get("race_list", [])))),
            raw_races.get("race_styles", raw_races.get("styles", {})),
        )
    if not custom_schedule and race_plan_text:
        try:
            parsed = race_catalog.parse_plan_input(race_plan_text)
        except Exception:
            parsed = {}
        if not parsed.get("errors"):
            custom_schedule = normalize_planner_profile_race_entries(parsed.get("entries", []))
    race_ids = [int(entry.get("race_id") or 0) for entry in custom_schedule if int(entry.get("race_id") or 0) > 0]
    race_styles = {}
    for entry in custom_schedule:
        style_value = normalize_race_style(entry.get("style", entry.get("tactic", entry.get("strategy", ""))))
        if style_value:
            race_styles[str(int(entry.get("race_id") or 0))] = style_value
    source_name = str(
        source_preset_name
        or raw_profile.get("source_preset_name")
        or raw_profile.get("preset_name")
        or ""
    ).strip()
    saved_at = str(raw_profile.get("saved_at") or "").strip() or time.strftime("%Y-%m-%dT%H:%M:%S%z")
    profile_title = str(
        profile_name
        or raw_profile.get("name")
        or source_name
        or "planner_profile"
    ).strip()
    return {
        "schema": "sweepy_planner_profile_v1",
        "name": profile_title or "planner_profile",
        "saved_at": saved_at,
        "source_preset_name": source_name,
        "skill_plan": {
            "style": style,
            "distance": distance,
            "buy_timing": buy_timing,
            "alarm_clock_mode": alarm_clock_mode,
            "alarm_clock_limit": alarm_clock_limit,
            "final_priorities": buy_on_sight,
            "blacklist": blacklist,
            "desired_sparks": desired_sparks,
        },
        "race_scheduler": {
            "race_plan_text": race_plan_text,
            "selected_race_ids": race_ids,
            "race_styles": race_styles,
            "custom_race_schedule": custom_schedule,
        },
    }


def planner_profile_from_preset(preset, profile_name=""):
    preset = dict(preset or {})
    return normalize_planner_profile(
        {
            "name": profile_name or preset.get("name") or "planner_profile",
            "source_preset_name": preset.get("name") or "",
            "skill_profile_style": preset.get("skill_profile_style", ""),
            "skill_profile_distance": preset.get("skill_profile_distance", ""),
            "manual_purchase_at_end": preset.get("manual_purchase_at_end", True),
            "skill_buy_on_sight": preset.get("skill_buy_on_sight", []),
            "skill_blacklist_custom": preset.get(
                "skill_blacklist_custom",
                preset.get("learn_skill_blacklist", []),
            ),
            "desired_parent_sparks": preset.get("desired_parent_sparks", {}),
            "alarm_clock_mode": preset.get("alarm_clock_mode", ""),
            "alarm_clock_use_limit": preset.get(
                "alarm_clock_use_limit",
                preset.get("clock_use_limit", 0),
            ),
            "clock_use_limit": preset.get("clock_use_limit", 0),
            "custom_race_schedule": preset.get("custom_race_schedule", []),
            "extra_race_list": preset.get("extra_race_list", preset.get("race_list", [])),
            "race_plan_text": preset.get("race_plan_text", ""),
        },
        profile_name=profile_name or preset.get("name") or "planner_profile",
        source_preset_name=preset.get("name") or "",
    )


def write_planner_profile(name, profile):
    normalized = normalize_planner_profile(profile, profile_name=name)
    path = planner_profile_path(normalized.get("name") or name)
    path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2), encoding="utf-8")
    return normalized


def read_planner_profile(name):
    path = planner_profile_path(name)
    if not path.exists():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return normalize_planner_profile(loaded, profile_name=name)


def list_planner_profiles():
    profiles = []
    for path in planner_profiles_dir().glob("*.json"):
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            profile = normalize_planner_profile(loaded, profile_name=path.stem)
        except Exception:
            continue
        profiles.append(
            {
                "name": profile.get("name") or path.stem,
                "saved_at": profile.get("saved_at") or "",
                "source_preset_name": profile.get("source_preset_name") or "",
            }
        )
    profiles.sort(key=lambda item: ((item.get("name") or "").lower(), item.get("saved_at") or ""))
    return profiles


def apply_planner_profile_to_preset(preset, raw_profile):
    preset = dict(preset or {})
    profile = normalize_planner_profile(raw_profile)
    skill = profile.get("skill_plan") or {}
    races = profile.get("race_scheduler") or {}
    buy_on_sight = split_skill_text(skill.get("final_priorities", []))
    blacklist = sanitize_blacklist(skill.get("blacklist", []))
    style = normalize_skill_style(skill.get("style", ""))
    distance = normalize_skill_distance(skill.get("distance", ""))
    preset["skill_buy_on_sight"] = buy_on_sight
    preset["skill_profile_style"] = style
    preset["skill_profile_distance"] = distance
    preset["skill_blacklist_custom"] = blacklist
    preset["learn_skill_blacklist"] = blacklist
    preset["learn_skill_list"] = build_skill_priority_rows(buy_on_sight, style, distance)
    preset["learn_skill_only_user_provided"] = False
    preset["learn_skill_append_defaults"] = True
    preset["manual_purchase_at_end"] = (str(skill.get("buy_timing") or "end_of_career").strip().lower() != "throughout")
    preset["desired_parent_sparks"] = sanitize_desired_parent_sparks(skill.get("desired_sparks"))
    mode = normalize_alarm_clock_mode(skill.get("alarm_clock_mode"))
    try:
        limit = max(0, min(int(skill.get("alarm_clock_limit") or 0), 5))
    except (TypeError, ValueError):
        limit = 0
    if mode == "none" or limit <= 0:
        mode = "none"
        limit = 0
    preset["alarm_clock_mode"] = mode
    preset["clock_use_limit"] = limit
    preset["alarm_clock_use_limit"] = limit
    preset["clock_allow_carats"] = (mode == "carats")
    preset["race_plan_text"] = str(races.get("race_plan_text") or "")
    entries = normalize_planner_profile_race_entries(races.get("custom_race_schedule", []))
    if not entries:
        entries = planner_profile_entries_from_race_ids(
            races.get("selected_race_ids", []),
            races.get("race_styles", {}),
        )
    race_ids = [int(entry.get("race_id") or 0) for entry in entries if int(entry.get("race_id") or 0) > 0]
    preset["race_list"] = race_ids
    preset["extra_race_list"] = race_ids
    if entries:
        preset["custom_race_schedule"] = entries
    else:
        preset.pop("custom_race_schedule", None)
    return preset, profile

LEGACY_DEFAULT_RUN_PRESET_NAME = "xguri parent"


def default_run_preset_name():
    preferred = str(os.environ.get("SWEEPY_DEFAULT_RUN_PRESET") or "").strip()
    chosen = ""
    default_name_fn = getattr(preset_store, "default_name", None)
    if callable(default_name_fn):
        chosen = str(default_name_fn(preferred=preferred) or "").strip()
    else:
        if preferred and callable(getattr(preset_store, "read_one", None)):
            preset = preset_store.read_one(preferred)
            if isinstance(preset, dict) and preset.get("name"):
                chosen = str(preset.get("name") or "").strip()
        if not chosen and callable(getattr(preset_store, "read_all", None)):
            presets = list(preset_store.read_all() or [])
            if presets:
                chosen = str((presets[0] or {}).get("name") or "").strip()
    if chosen:
        return chosen
    return preferred or LEGACY_DEFAULT_RUN_PRESET_NAME


def requested_preset_name(req=None):
    name = str(getattr(req, "preset_name", "") or "").strip()
    return name or default_run_preset_name()


def instance_local_learning_enabled():
    scope = str(os.environ.get("SWEEPY_AUTO_LEARNING_SCOPE") or "").strip().lower()
    if scope in {"instance", "local", "instance_local"}:
        return True
    if scope in {"shared", "shared_preset", "global"}:
        return False
    return bool(os.environ.get("SWEEPY_SHARED_RUNTIME_PATHS") and os.environ.get("SWEEPY_INSTANCE_NAME"))


OPERATOR_OWNED_FALLBACK_KEYS = {
    "skill_buy_on_sight",
    "skill_profile_style",
    "skill_profile_distance",
    "skill_blacklist_custom",
    "learn_skill_blacklist",
    "learn_skill_list",
    "learn_skill_only_user_provided",
    "learn_skill_append_defaults",
    "manual_purchase_at_end",
    "desired_parent_sparks",
    "race_plan_text",
    "custom_race_schedule",
    "extra_race_list",
    "race_list",
    "calendar_race_prebuy_enabled",
    "calendar_race_prebuy_grades",
    "calendar_race_prebuy_all_scheduled",
    "scheduled_race_clean_record_mode",
    "alarm_clock_mode",
    "clock_use_limit",
    "alarm_clock_use_limit",
    "clock_allow_carats",
}

SKILL_PLAN_OPERATOR_KEYS = {
    "skill_buy_on_sight",
    "skill_profile_style",
    "skill_profile_distance",
    "skill_blacklist_custom",
    "learn_skill_blacklist",
    "learn_skill_list",
    "learn_skill_only_user_provided",
    "learn_skill_append_defaults",
    "manual_purchase_at_end",
    "desired_parent_sparks",
    "alarm_clock_mode",
    "clock_use_limit",
    "alarm_clock_use_limit",
    "clock_allow_carats",
}

RACE_PLAN_OPERATOR_KEYS = {
    "race_plan_text",
    "custom_race_schedule",
    "extra_race_list",
    "race_list",
}


def _scrub_instance_learning_override_keys(preset_name, keys, *, reason="operator_save"):
    """Remove stale operator-owned config from account-local learning overlays.

    The base preset is the source of truth for UI-selected strategy/race plans.
    Account-local learning may still own learned numeric policy fields, but it
    must not keep an old `skill_profile_style` and later force Front Runner
    after the UI saved Late Surger.
    """
    if not instance_local_learning_enabled():
        return []
    preset_name = str(preset_name or "").strip()
    if not preset_name:
        return []
    try:
        path = instance_learning_override_path(DIR, preset_name)
    except Exception:
        return []
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    if not isinstance(raw, dict):
        return []
    removed = []
    for key in sorted(set(keys or [])):
        if key in raw:
            raw.pop(key, None)
            removed.append(key)
    if not removed:
        return []
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(raw, ensure_ascii=False, indent=2, default=json_cache_default), encoding="utf-8")
    os.replace(tmp, path)
    print(
        f"[INSTANCE_LEARNING_SCRUB] preset={preset_name!r} reason={reason} removed={removed}",
        flush=True,
    )
    return removed


def _hot_patch_active_runner_preset(preset, keys, *, reason="operator_save"):
    """Patch the currently-running preset after an operator save.

    The file watcher also hot-reloads presets, but it polls and performs a full
    replacement. Save buttons need immediate, narrow updates so the next race
    uses the new strategy/distance/skill plan without disturbing runtime-only
    deck context or cached policy values.
    """
    if not isinstance(preset, dict):
        return False
    name = str(preset.get("name") or "").strip()
    if not name:
        return False
    fields = {key: preset[key] for key in keys or [] if key in preset}
    if not fields:
        return False
    try:
        updated = career_runner.update_active_preset_fields(name, fields, reason=reason)
    except AttributeError:
        updated = False
    if updated:
        print(
            f"active runner preset hot-patched from {reason}: {name} ({', '.join(sorted(fields))})",
            flush=True,
        )
    return bool(updated)


def resolve_effective_preset(name, base_preset=None):
    preset = dict(base_preset or {})
    if not preset:
        preset = preset_store.read_one(name) or {}
    if not preset:
        return None
    if not instance_local_learning_enabled():
        return preset
    override = read_instance_learning_override(DIR, name)
    if not isinstance(override, dict):
        return preset
    try:
        from career_bot.learning import _preserve_operator_owned_fields
    except Exception:
        merged = dict(preset)
        merged.update(override)
        for key in OPERATOR_OWNED_FALLBACK_KEYS:
            if key in preset:
                merged[key] = preset[key]
        merged["name"] = preset.get("name") or name
        return merged
    merged = dict(preset)
    merged.update(override)
    merged, _ = _preserve_operator_owned_fields(merged, preset)
    merged["name"] = preset.get("name") or name
    return merged


def read_requested_base_preset(req=None):
    name = requested_preset_name(req)
    preset = preset_store.read_one(name)
    if preset:
        return preset, None
    return None, f"{name} preset missing"


def read_requested_preset(req=None):
    name = requested_preset_name(req)
    preset = resolve_effective_preset(name)
    if preset:
        return preset, None
    return None, f"{name} preset missing"


def normalize_alarm_clock_mode(value):
    mode = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "off": "none",
        "disabled": "none",
        "disable": "none",
        "no": "none",
        "normal": "normal",
        "clock": "normal",
        "clocks": "normal",
        "alarm": "normal",
        "alarm_clock": "normal",
        "alarm_clocks": "normal",
        "with_carats": "carats",
        "carat": "carats",
        "carat_alarm": "carats",
        "carat_alarm_clock": "carats",
        "clock_carats": "carats",
        "clocks_carats": "carats",
    }
    return aliases.get(mode, mode if mode in {"none", "normal", "carats"} else "normal")


@app.post("/api/presets/save_races")
async def save_races(req: SaveRacesRequest):
    preset, detail = read_requested_base_preset(req)
    if not preset:
        return {"success": False, "detail": detail}
    preset.pop("race_plan_text", None)
    styles = req.styles or {}
    entries_by_turn = {}
    for raw_race_id in req.races:
        try:
            race_id = int(raw_race_id)
        except (TypeError, ValueError):
            continue
        race = race_catalog.by_id.get(race_id)
        if not race:
            continue
        raw_style = styles.get(str(race_id), styles.get(race_id, ""))
        entry = race_catalog.entry_from_race(race, normalize_race_style(raw_style), "manual_picker")
        turn = int(entry.get("turn") or 0)
        if turn:
            # Only one race can actually be entered on a half-month turn. If the UI
            # or an old preset sends multiple races for the same date, keep the last
            # explicit choice instead of letting the runner pick an arbitrary first one.
            entries_by_turn[turn] = entry
    entries = sorted(entries_by_turn.values(), key=lambda item: (int(item.get("turn") or 0), int(item.get("race_id") or 0)))
    race_ids = [entry["race_id"] for entry in entries]
    preset["race_list"] = race_ids
    preset["extra_race_list"] = race_ids
    if entries:
        preset["custom_race_schedule"] = entries
    else:
        preset.pop("custom_race_schedule", None)
    saved = preset_store.write(preset)
    _scrub_instance_learning_override_keys(preset.get("name") or req.preset_name, RACE_PLAN_OPERATOR_KEYS, reason="save_races")
    hot_reloaded = _hot_patch_active_runner_preset(saved, RACE_PLAN_OPERATOR_KEYS, reason="save_races")
    return {"success": True, "entries": entries, "race_ids": race_ids, "hot_reloaded": hot_reloaded}

@app.post("/api/presets/save_race_plan")
async def save_race_plan(req: SaveRacePlanTextRequest):
    preset, detail = read_requested_base_preset(req)
    if not preset:
        return {"success": False, "detail": detail}
    parsed = race_catalog.parse_plan_input(req.text)
    if parsed.get("errors"):
        return {"success": False, "errors": parsed["errors"], "entries": parsed.get("entries", [])}
    entries = parsed.get("entries") or []
    preset["race_plan_text"] = req.text
    preset["custom_race_schedule"] = entries
    preset["extra_race_list"] = [entry["race_id"] for entry in entries]
    # Don't touch manual_purchase_at_end here — it's controlled by the Skill Plan
    # save endpoint (BUY TIMING dropdown). Forcing True here used to silently undo
    # the user's choice every time they saved a race plan.
    saved = preset_store.write(preset)
    _scrub_instance_learning_override_keys(preset.get("name") or req.preset_name, RACE_PLAN_OPERATOR_KEYS, reason="save_race_plan")
    hot_reloaded = _hot_patch_active_runner_preset(saved, RACE_PLAN_OPERATOR_KEYS, reason="save_race_plan")
    return {"success": True, "entries": entries, "race_ids": preset["extra_race_list"], "hot_reloaded": hot_reloaded}

@app.post("/api/presets/save_skill_plan")
async def save_skill_plan(req: SaveSkillPlanRequest):
    preset, detail = read_requested_base_preset(req)
    if not preset:
        return {"success": False, "detail": detail}
    buy_on_sight = split_skill_text(req.buy_on_sight)
    # sanitize_blacklist removes:
    #   1. style/distance/common skills that the priority list wants to buy
    #      (so the user can't accidentally blacklist their own priority targets)
    #   2. comma-split fragments via the now-newline-only parser
    #   3. duplicates
    blacklist = sanitize_blacklist(req.blacklist)
    style = normalize_skill_style(req.style)
    distance = normalize_skill_distance(req.distance)
    # Verbose log so the user can see exactly what landed on the server
    # when debugging "I clicked Pace but bot ran Front" situations.
    print(
        f"[SAVE_SKILL_PLAN] preset={req.preset_name!r}  "
        f"style_in={req.style!r} → style_saved={style!r}  "
        f"distance_in={req.distance!r} → distance_saved={distance!r}  "
        f"buy_on_sight={len(buy_on_sight)} skills  "
        f"blacklist={len(blacklist)} skills",
        flush=True,
    )
    preset["skill_buy_on_sight"] = buy_on_sight
    preset["skill_profile_style"] = style
    preset["skill_profile_distance"] = distance
    preset["skill_blacklist_custom"] = blacklist
    preset["learn_skill_blacklist"] = blacklist
    preset["learn_skill_list"] = build_skill_priority_rows(buy_on_sight, style, distance)
    preset["learn_skill_only_user_provided"] = False
    preset["learn_skill_append_defaults"] = True
    preset["manual_purchase_at_end"] = (str(req.buy_timing or "end_of_career").strip().lower() != "throughout")
    preset["desired_parent_sparks"] = sanitize_desired_parent_sparks(req.desired_sparks)
    if req.alarm_clock_mode or req.alarm_clock_limit is not None:
        mode = normalize_alarm_clock_mode(req.alarm_clock_mode)
        try:
            current_limit = preset.get("alarm_clock_use_limit", preset.get("clock_use_limit", 0))
            limit = max(0, min(int(req.alarm_clock_limit if req.alarm_clock_limit is not None else current_limit), 5))
        except (TypeError, ValueError):
            limit = 0
        if mode == "none" or limit <= 0:
            mode = "none"
            limit = 0
        preset["alarm_clock_mode"] = mode
        preset["clock_use_limit"] = limit
        preset["alarm_clock_use_limit"] = limit
        preset["clock_allow_carats"] = (mode == "carats")
    saved = preset_store.write(preset)
    _scrub_instance_learning_override_keys(
        saved.get("name") or preset.get("name") or req.preset_name,
        SKILL_PLAN_OPERATOR_KEYS,
        reason="save_skill_plan",
    )
    hot_reloaded = _hot_patch_active_runner_preset(saved, SKILL_PLAN_OPERATOR_KEYS, reason="save_skill_plan")
    return {"success": True, "preset": saved, "rows": saved.get("learn_skill_list", []), "hot_reloaded": hot_reloaded}

@app.post("/api/presets/save_race_continue")
async def save_race_continue(req: SaveRaceContinueRequest):
    preset, detail = read_requested_base_preset(req)
    if not preset:
        return {"success": False, "detail": detail}
    mode = normalize_alarm_clock_mode(req.mode)
    try:
        limit = max(0, min(int(req.limit or 0), 5))
    except (TypeError, ValueError):
        limit = 0
    if mode == "none" or limit <= 0:
        mode = "none"
        limit = 0
    preset["alarm_clock_mode"] = mode
    preset["clock_use_limit"] = limit
    preset["alarm_clock_use_limit"] = limit
    preset["clock_allow_carats"] = (mode == "carats")
    saved = preset_store.write(preset)
    _scrub_instance_learning_override_keys(
        saved.get("name") or preset.get("name") or req.preset_name,
        {"alarm_clock_mode", "clock_use_limit", "alarm_clock_use_limit", "clock_allow_carats"},
        reason="save_race_continue",
    )
    hot_reloaded = _hot_patch_active_runner_preset(
        saved,
        {"alarm_clock_mode", "clock_use_limit", "alarm_clock_use_limit", "clock_allow_carats"},
        reason="save_race_continue",
    )
    return {
        "success": True,
        "preset": saved,
        "mode": mode,
        "limit": limit,
        "hot_reloaded": hot_reloaded,
    }

@app.get("/api/presets")
async def get_presets():
    presets = preset_store.read_all()
    return {
        "success": True,
        "presets": presets,
        "default_preset_name": (presets[0]["name"] if presets else default_run_preset_name()),
    }


# In-memory state for the Calibrate button — tracks whether a calibrate
# job is currently running so the UI can disable the button + tail the
# report file when it lands.
_calibrate_state = {
    "running": False,
    "started_at": 0.0,
    "report_path": "",
    "last_report": None,
}


@app.get("/api/calibrate/status")
async def get_calibrate_status():
    """Poll-friendly status endpoint for the Calibrate UI button.

    Returns:
      running: whether a calibrate job is in flight
      started_at: epoch seconds when it started (0 if idle)
      report_path: path to the JSON report being written
      last_report: parsed contents of the latest report (when complete)
    """
    state = dict(_calibrate_state)
    # If we have a report path and the file exists, surface its parsed contents
    rp = state.get("report_path") or ""
    if rp:
        try:
            from pathlib import Path as _P
            p = _P(rp)
            if p.exists():
                try:
                    state["last_report"] = json.loads(p.read_text(encoding="utf-8"))
                    # If the report has been written, the job is no longer in flight
                    state["running"] = False
                    _calibrate_state["running"] = False
                except (OSError, json.JSONDecodeError):
                    pass
        except Exception:
            pass
    return {"success": True, "state": state}


@app.post("/api/calibrate")
async def start_calibrate(req: dict = None):
    """Kick off a fast deck calibration in a new console window.

    Reads optional knobs from the JSON body:
      - time_budget_sec (default 1800)
      - target_ss_rate (default 0.95)
      - target_mean (default 17500)
      - min_rating (default 14500; no A+ outcomes)
      - ss_threshold (default 17500)
      - sims_per_candidate (default 2)
      - baseline_sims (default 2)
      - validation_sims (default 4)

    Spawns `tools/calibrate_deck.py` in a NEW console window so the user
    can watch the probe progress live. The script writes a structured
    report JSON; the UI polls `/api/calibrate/status` to see when it's
    done and what it found.
    """
    body = req if isinstance(req, dict) else {}
    if _calibrate_state.get("running"):
        return {
            "success": False,
            "error": "A calibration is already running. Wait for it to finish "
                     "(or close its console window) before starting another.",
        }

    # Build report path under the runtime dir so multiple runs don't clobber
    runtime_root = runtime_output_root(DIR)
    report_dir = runtime_root / "calibrate_reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"calibrate_{int(time.time())}.json"

    # Compose the subprocess command. On Windows, `start "title" cmd /k`
    # launches a NEW console window that stays open after exit so the
    # user can read the final report.
    py_exe = sys.executable or "python"
    script_path = base_dir / "tools" / "calibrate_deck.py"
    cmd_args = [
        py_exe,
        str(script_path),
        "--time-budget-sec", str(float(body.get("time_budget_sec") or 1800.0)),
        "--target-ss-rate", str(float(body.get("target_ss_rate") or 0.95)),
        "--target-mean", str(int(body.get("target_mean") or 17500)),
        "--min-rating", str(int(body.get("min_rating") or 14500)),
        "--ss-threshold", str(int(body.get("ss_threshold") or 17500)),
        "--target-win-rate", str(float(body.get("target_win_rate") or 0.95)),
        "--max-epithet-losses", str(int(body.get("max_epithet_losses") or 0)),
        "--sims-per-candidate", str(int(body.get("sims_per_candidate") or 2)),
        "--baseline-sims", str(int(body.get("baseline_sims") or 2)),
        "--validation-sims", str(int(body.get("validation_sims") or 4)),
        "--report-out", str(report_path),
    ]
    # If running on Windows, spawn in a new console window so the user
    # can watch progress. On other platforms, just use Popen detached.
    try:
        if os.name == "nt":
            # CREATE_NEW_CONSOLE = 0x00000010
            subprocess.Popen(
                cmd_args,
                creationflags=0x00000010,
                cwd=str(base_dir),
            )
        else:
            subprocess.Popen(
                cmd_args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(base_dir),
            )
    except (OSError, FileNotFoundError) as exc:
        return {
            "success": False,
            "error": f"Failed to launch calibrate subprocess: {exc!r}",
        }

    _calibrate_state["running"] = True
    _calibrate_state["started_at"] = time.time()
    _calibrate_state["report_path"] = str(report_path)
    _calibrate_state["last_report"] = None
    return {
        "success": True,
        "message": "Calibration started in a new console window.",
        "report_path": str(report_path),
    }


@app.get("/api/planner_profiles")
async def get_planner_profiles():
    return {"success": True, "profiles": list_planner_profiles()}


@app.post("/api/planner_profiles/save")
async def save_planner_profile(req: SavePlannerProfileRequest):
    profile_name = str(req.profile_name or "").strip()
    if isinstance(req.profile, dict) and req.profile:
        raw_profile = dict(req.profile)
        profile_name = profile_name or str(raw_profile.get("name") or "").strip()
        source_preset_name = requested_preset_name(req)
    else:
        preset, detail = read_requested_base_preset(req)
        if not preset:
            return {"success": False, "detail": detail}
        source_preset_name = preset.get("name") or requested_preset_name(req)
        raw_profile = planner_profile_from_preset(preset, profile_name=profile_name or source_preset_name)
    if not profile_name:
        profile_name = str(raw_profile.get("name") or source_preset_name or "planner_profile").strip()
    normalized = normalize_planner_profile(raw_profile, profile_name=profile_name, source_preset_name=source_preset_name)
    saved_profile = write_planner_profile(profile_name, normalized)
    return {"success": True, "profile": saved_profile, "profiles": list_planner_profiles()}


@app.post("/api/planner_profiles/load")
async def load_planner_profile(req: LoadPlannerProfileRequest):
    preset, detail = read_requested_base_preset(req)
    if not preset:
        return {"success": False, "detail": detail}
    raw_profile = dict(req.profile) if isinstance(req.profile, dict) and req.profile else None
    if not raw_profile:
        profile_name = str(req.profile_name or "").strip()
        if not profile_name:
            return {"success": False, "detail": "profile_name is required"}
        raw_profile = read_planner_profile(profile_name)
        if not raw_profile:
            return {"success": False, "detail": f"planner profile {profile_name} missing"}
    updated, normalized = apply_planner_profile_to_preset(preset, raw_profile)
    saved = preset_store.write(updated)
    _scrub_instance_learning_override_keys(saved.get("name") or req.preset_name, OPERATOR_OWNED_FALLBACK_KEYS, reason="load_planner_profile")
    hot_reloaded = _hot_patch_active_runner_preset(saved, OPERATOR_OWNED_FALLBACK_KEYS, reason="load_planner_profile")
    return {"success": True, "preset": saved, "profile": normalized, "hot_reloaded": hot_reloaded}


@app.get("/api/decks/advice")
async def get_deck_advice(preset_name: str = "", deck_id: int = 0):
    if build_deck_advice is None:
        return {
            "success": False,
            "detail": (
                "Deck Advice module is missing from this project copy. "
                "Rebuild/copy the full project and ensure career_bot/deck_advice.py is present."
            ),
            "missing_module": "career_bot.deck_advice",
            "import_error": OPTIONAL_IMPORT_ERRORS.get("career_bot.deck_advice", ""),
        }
    decks = list((active_dashboard_data or {}).get("decks") or [])
    if not decks:
        return {"success": False, "detail": "Sync dashboard decks first"}

    requested_name = str(preset_name or "").strip() or default_run_preset_name()
    preset = resolve_effective_preset(requested_name) or {}
    parent_goals = sanitize_desired_parent_sparks(preset.get("desired_parent_sparks"))
    style_context = normalize_skill_style(preset.get("skill_profile_style") or "")
    distance_context = normalize_skill_distance(preset.get("skill_profile_distance") or "")
    selected_deck_id = int(deck_id or ((active_selection.get("deck") or {}).get("id") or 0) or 0)
    current_deck = next(
        (deck for deck in decks if int(deck.get("id") or deck.get("deck_id") or 0) == selected_deck_id),
        None,
    ) or (active_selection.get("deck") or {})
    available_supports = list((active_dashboard_data or {}).get("supports") or [])
    cache_key = json.dumps(
        {
            "preset_name": preset.get("name") or requested_name,
            "parent_goals": parent_goals,
            "style_context": style_context,
            "distance_context": distance_context,
            "selected_deck_id": selected_deck_id,
            "current_deck": {
                "id": int(current_deck.get("id") or current_deck.get("deck_id") or 0),
                "cards": [
                    int(card.get("id") or card.get("support_card_id") or card.get("card_id") or 0)
                    for card in (current_deck.get("cards") or [])
                ],
            },
            "decks": [
                {
                    "id": int(deck.get("id") or deck.get("deck_id") or 0),
                    "cards": [
                        int(card.get("id") or card.get("support_card_id") or card.get("card_id") or 0)
                        for card in (deck.get("cards") or [])
                    ],
                }
                for deck in decks
            ],
            "supports": [
                (
                    int(row.get("id") or row.get("support_card_id") or 0),
                    int(row.get("limit_break_count") or 0),
                    int(row.get("support_card_level") or row.get("level") or 0),
                    int(row.get("exp") or 0),
                )
                for row in available_supports
            ],
            "trainee": {
                "id": int((active_selection.get("trainee") or {}).get("id") or 0),
                "name": str((active_selection.get("trainee") or {}).get("name") or ""),
            },
            "friend": {
                "support_card_id": int((active_selection.get("friend") or {}).get("support_card_id") or 0),
                "name": str(
                    (active_selection.get("friend") or {}).get("support_name")
                    or (active_selection.get("friend") or {}).get("name")
                    or ""
                ),
            },
        },
        sort_keys=True,
    )
    if deck_advice_cache.get("key") == cache_key and isinstance(deck_advice_cache.get("advice"), dict):
        advice = dict(deck_advice_cache["advice"])
        advice["preset_name"] = preset.get("name") or requested_name
        return {"success": True, "advice": advice}
    advice = build_deck_advice(
        DIR,
        decks,
        current_deck_id=selected_deck_id,
        parent_goals=parent_goals,
        support_catalog=_support_catalog_snapshot(),
        available_supports=available_supports,
        current_deck=current_deck,
        trainee=active_selection.get("trainee") or {},
        friend=active_selection.get("friend") or {},
        style=style_context,
        distance=distance_context,
    )
    advice["preset_name"] = preset.get("name") or requested_name
    deck_advice_cache["key"] = cache_key
    deck_advice_cache["advice"] = dict(advice)
    return {"success": True, "advice": advice}

@app.post("/api/decks/save")
async def save_deck(req: SaveDeckRequest):
    global active_dashboard_data, active_selection, deck_advice_cache
    if not active_dashboard_data:
        if active_client:
            try:
                active_dashboard_data = reload_dashboard_state_from_server(preserve_friends=True)
            except Exception:
                active_dashboard_data = None
    if not active_dashboard_data:
        return {"success": False, "detail": "Sync or log in before editing decks"}
    deck_id = safe_int(req.deck_id)
    if deck_id <= 0:
        return {"success": False, "detail": "deck_id is required"}

    overrides = load_deck_overrides()
    override_decks = overrides.setdefault("decks", {})
    existing = next(
        (
            deck for deck in (active_dashboard_data.get("decks") or [])
            if safe_int(deck.get("id") or deck.get("deck_id")) == deck_id
        ),
        None,
    )
    prior_override = override_decks.get(str(deck_id)) if isinstance(override_decks.get(str(deck_id)), dict) else {}
    def _deck_support_ids(deck):
        if not isinstance(deck, dict):
            return []
        explicit = clean_int_list(deck.get("support_card_ids") or deck.get("synced_support_card_ids") or [])
        if explicit:
            return explicit
        return clean_int_list([card.get("id") or card.get("support_card_id") for card in (deck.get("cards") or []) if isinstance(card, dict)])

    if req.clear_override:
        prior_override = override_decks.pop(str(deck_id), None) if isinstance(override_decks, dict) else {}
        save_deck_overrides(overrides)
        reloaded = False
        if active_client and not career_runner.snapshot().get("running") and not loop_snapshot().get("active"):
            try:
                dashboard = reload_dashboard_state_from_server(preserve_friends=True)
                reloaded = True
            except Exception:
                dashboard = active_dashboard_data
        else:
            dashboard = active_dashboard_data
        if not reloaded and isinstance(prior_override, dict):
            synced_ids = clean_int_list(
                prior_override.get("synced_support_card_ids")
                or (existing or {}).get("synced_support_card_ids")
                or []
            )
            if synced_ids:
                support_lookup = {
                    str(card.get("id") or card.get("support_card_id")): card
                    for card in ((active_dashboard_data or {}).get("supports") or [])
                    if safe_int(card.get("id") or card.get("support_card_id"))
                }
                restored_cards = [
                    card
                    for card in (_support_view_from_card_id(card_id, support_lookup) for card_id in synced_ids)
                    if card
                ]
                restored_deck = dict(existing or {"id": deck_id})
                restored_deck.update({
                    "id": deck_id,
                    "name": str(prior_override.get("synced_name") or (existing or {}).get("synced_name") or (existing or {}).get("name") or f"Deck {deck_id}"),
                    "cards": restored_cards,
                    "support_card_ids": synced_ids,
                    "edited": False,
                    "source": str((existing or {}).get("source") or "").replace("local_edit", "").strip(),
                })
                restored_deck.pop("synced_support_card_ids", None)
                restored_deck.pop("synced_name", None)
                decks = list((active_dashboard_data or {}).get("decks") or [])
                for idx, deck in enumerate(decks):
                    if safe_int(deck.get("id") or deck.get("deck_id")) == deck_id:
                        decks[idx] = restored_deck
                        break
                else:
                    decks.append(restored_deck)
                if active_dashboard_data is not None:
                    active_dashboard_data["decks"] = decks
                    dashboard = active_dashboard_data
                if safe_int((active_selection.get("deck") or {}).get("id") or (active_selection.get("deck") or {}).get("deck_id")) == deck_id:
                    active_selection["deck"] = restored_deck
        deck_advice_cache["key"] = None
        deck_advice_cache["advice"] = None
        deck = next(
            (
                item for item in ((dashboard or {}).get("decks") or [])
                if safe_int(item.get("id") or item.get("deck_id")) == deck_id
            ),
            None,
        )
        return {"success": True, "deck": deck, "dashboard": dashboard}

    support_ids = clean_int_list(req.support_card_ids or [])
    if len(support_ids) > 5:
        return {"success": False, "detail": "A deck can contain at most 5 support cards"}
    if len(set(support_ids)) != len(support_ids):
        return {"success": False, "detail": "Deck contains duplicate support card ids"}
    owned_support_ids = {
        str(card.get("id") or card.get("support_card_id"))
        for card in (active_dashboard_data.get("supports") or [])
        if safe_int(card.get("id") or card.get("support_card_id"))
    }
    if owned_support_ids:
        missing = [sid for sid in support_ids if str(sid) not in owned_support_ids]
        if missing:
            return {"success": False, "detail": f"Support cards are not in owned inventory: {missing}"}

    name = str(req.name or (existing or {}).get("name") or f"Deck {deck_id}").strip() or f"Deck {deck_id}"
    synced_support_ids = clean_int_list(
        (prior_override or {}).get("synced_support_card_ids")
        or (existing or {}).get("synced_support_card_ids")
        or ([] if (existing or {}).get("edited") else _deck_support_ids(existing))
    )
    synced_name = str(
        (prior_override or {}).get("synced_name")
        or (existing or {}).get("synced_name")
        or ("" if (existing or {}).get("edited") else (existing or {}).get("name"))
        or f"Deck {deck_id}"
    )
    override_decks[str(deck_id)] = {
        "deck_id": deck_id,
        "name": name,
        "support_card_ids": support_ids,
        "synced_name": synced_name,
        "synced_support_card_ids": synced_support_ids,
        "updated_at": time.time(),
    }
    save_deck_overrides(overrides)

    support_lookup = {
        str(card.get("id") or card.get("support_card_id")): card
        for card in (active_dashboard_data.get("supports") or [])
        if safe_int(card.get("id") or card.get("support_card_id"))
    }
    cards = [
        card
        for card in (_support_view_from_card_id(card_id, support_lookup) for card_id in support_ids)
        if card
    ]
    updated_deck = dict(existing or {"id": deck_id, "source": "local_edit"})
    updated_deck.update({
        "id": deck_id,
        "name": name,
        "cards": cards,
        "support_card_ids": support_ids,
        "synced_name": synced_name,
        "synced_support_card_ids": synced_support_ids,
        "edited": True,
        "source": f"{updated_deck.get('source', '')} local_edit".strip(),
    })

    decks = list(active_dashboard_data.get("decks") or [])
    replaced = False
    for idx, deck in enumerate(decks):
        if safe_int(deck.get("id") or deck.get("deck_id")) == deck_id:
            decks[idx] = updated_deck
            replaced = True
            break
    if not replaced:
        decks.append(updated_deck)
    active_dashboard_data["decks"] = decks
    active_dashboard_data["deckDebug"] = active_deck_debug
    if safe_int((active_selection.get("deck") or {}).get("id") or (active_selection.get("deck") or {}).get("deck_id")) == deck_id:
        active_selection["deck"] = updated_deck
    deck_advice_cache["key"] = None
    deck_advice_cache["advice"] = None
    persist_dev_session_cache("deck_edit")
    return {"success": True, "deck": updated_deck, "dashboard": active_dashboard_data}


@app.post("/api/presets")
async def save_preset(req: SavePresetRequest):
    saved = preset_store.write(req.preset)
    _scrub_instance_learning_override_keys(saved.get("name") or (req.preset or {}).get("name"), OPERATOR_OWNED_FALLBACK_KEYS, reason="save_preset")
    hot_reloaded = _hot_patch_active_runner_preset(saved, OPERATOR_OWNED_FALLBACK_KEYS, reason="save_preset")
    return {"success": True, "preset": saved, "hot_reloaded": hot_reloaded}

@app.post("/api/presets/delete")
async def delete_preset(req: DeletePresetByNameRequest):
    return {"success": preset_store.delete(req.name)}


def team_bundle_presets_path():
    return Path(DIR) / "data" / "team_bundle_presets.json"


def normalize_team_bundle_preset_name(name):
    return str(name or "").strip()[:64]


def normalize_team_bundle_selection(raw):
    selection = raw if isinstance(raw, dict) else {}
    veterans = selection.get("veterans") if isinstance(selection.get("veterans"), list) else []
    return {
        "deck": selection.get("deck") if isinstance(selection.get("deck"), dict) else None,
        "friend": selection.get("friend") if isinstance(selection.get("friend"), dict) else None,
        "trainee": selection.get("trainee") if isinstance(selection.get("trainee"), dict) else None,
        "veterans": [row for row in veterans[:2] if isinstance(row, dict)],
        "guestParent": selection.get("guestParent") if isinstance(selection.get("guestParent"), dict) else None,
    }


def normalize_team_bundle_preset(raw, fallback_name=""):
    data = dict(raw or {})
    name = normalize_team_bundle_preset_name(data.get("name") or fallback_name)
    if not name:
        return None
    return {
        "name": name,
        "selection": normalize_team_bundle_selection(data.get("selection") or {}),
        "saved_at": float(data.get("saved_at") or time.time()),
    }


def read_team_bundle_presets():
    path = team_bundle_presets_path()
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(raw, dict):
        rows = raw.get("presets") if isinstance(raw.get("presets"), list) else list(raw.values())
    elif isinstance(raw, list):
        rows = raw
    else:
        rows = []
    loaded = {}
    for row in rows:
        preset = normalize_team_bundle_preset(row)
        if preset:
            loaded[preset["name"].lower()] = preset
    return sorted(loaded.values(), key=lambda item: item["name"].lower())


def write_team_bundle_presets(presets):
    path = team_bundle_presets_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"presets": read_team_bundle_presets() if presets is None else presets}
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_cache_default), encoding="utf-8")
    os.replace(tmp, path)
    return payload["presets"]


@app.get("/api/team_bundle/presets")
async def list_team_bundle_presets():
    return {"success": True, "presets": read_team_bundle_presets()}


@app.post("/api/team_bundle/presets")
async def save_team_bundle_preset(req: SaveTeamBundlePresetRequest):
    preset = normalize_team_bundle_preset(req.preset, req.name)
    if not preset:
        return {"success": False, "detail": "Team bundle preset name required"}
    presets = {row["name"].lower(): row for row in read_team_bundle_presets()}
    presets[preset["name"].lower()] = preset
    saved = write_team_bundle_presets(sorted(presets.values(), key=lambda item: item["name"].lower()))
    return {"success": True, "preset": preset, "presets": saved}


@app.post("/api/team_bundle/presets/delete")
async def delete_team_bundle_preset(req: DeleteTeamBundlePresetRequest):
    name = normalize_team_bundle_preset_name(req.name)
    if not name:
        return {"success": False, "detail": "Team bundle preset name required"}
    presets = [row for row in read_team_bundle_presets() if row["name"].lower() != name.lower()]
    saved = write_team_bundle_presets(presets)
    return {"success": True, "presets": saved}


def _admin_account_runtime(account_id):
    account = str(account_id or "").strip()
    root = dev_runtime_dir()
    if account and account not in {"default", "shared", "global"}:
        candidate = root / "instances" / account
        if candidate.exists():
            return candidate
    return root


def _percentiles(values):
    rows = sorted(int(value) for value in values if int(value or 0) > 0)
    if not rows:
        return {}

    def pick(pct):
        if len(rows) == 1:
            return rows[0]
        idx = int(round((len(rows) - 1) * pct))
        return rows[max(0, min(idx, len(rows) - 1))]

    return {
        "min": rows[0],
        "p25": pick(0.25),
        "p50": pick(0.50),
        "p75": pick(0.75),
        "max": rows[-1],
    }


def _parent_library_health(runtime_root):
    path = Path(runtime_root) / "parent_memory" / "parent_library.json"
    payload = _read_json_file(path)
    rows = []
    if isinstance(payload, dict):
        raw_rows = payload.get("parents") or payload.get("items") or payload.get("library") or []
        if isinstance(raw_rows, dict):
            raw_rows = list(raw_rows.values())
        if isinstance(raw_rows, list):
            rows = [row for row in raw_rows if isinstance(row, dict)]
    scores = []
    ss_dates = []
    for row in rows:
        score = int(row.get("score") or row.get("rank_score") or row.get("assessment_point") or 0)
        if score > 0:
            scores.append(score)
        if score >= 17500:
            ts = row.get("created_at") or row.get("captured_at") or row.get("updated_at") or ""
            if ts:
                ss_dates.append(str(ts))
    return {
        "path": str(path),
        "exists": path.exists(),
        "total": len(rows),
        "ss_rank_count": sum(1 for score in scores if score >= 17500),
        "score_distribution": _percentiles(scores),
        "last_ss_timestamp": max(ss_dates) if ss_dates else "",
    }


def _recent_run_row(path):
    data = _read_json_file(path)
    if not isinstance(data, dict):
        return {"path": str(path), "error": "invalid_json"}
    turns = data.get("turns") if isinstance(data.get("turns"), list) else []
    final_turn = int(data.get("final_turn") or (max((int((turn or {}).get("turn") or 0) for turn in turns), default=0)))
    final_stats = {}
    for turn in reversed(turns):
        stats = (turn or {}).get("stats")
        if isinstance(stats, dict) and stats:
            final_stats = stats
            break
    races = []
    for turn in turns:
        for event in (turn or {}).get("events") or []:
            if isinstance(event, dict) and event.get("event") == "race_result":
                races.append(event)
    finish = data.get("finish") if isinstance(data.get("finish"), dict) else {}
    score = int(data.get("rank_score") or data.get("score") or data.get("final_score") or finish.get("rank_score") or finish.get("score") or 0)
    return {
        "path": str(path),
        "created_at": data.get("started_at") or "",
        "ended_at": data.get("ended_at") or "",
        "preset_name": data.get("preset_name") or "",
        "status": data.get("status") or "",
        "score": score,
        "rank_label": data.get("rank_label") or finish.get("rank_label") or "",
        "final_turn": final_turn,
        "stats": final_stats,
        "race_count": len(races),
        "race_losses": sum(1 for race in races if not bool(race.get("won"))),
        "g1_wins": sum(1 for race in races if bool(race.get("won")) and str(((race.get("race_info") or {}).get("grade") or "")).upper() == "G1"),
    }


def _recent_runs_payload(account_id, n=10):
    runtime_root = _admin_account_runtime(account_id)
    bot_logs = runtime_root / "bot_logs"
    files = sorted(bot_logs.glob("career_log_*.json"), key=lambda path: path.stat().st_mtime, reverse=True) if bot_logs.exists() else []
    limit = max(1, min(int(n or 10), 100))
    return {
        "account_id": str(account_id or "default"),
        "runtime_root": str(runtime_root),
        "runs": [_recent_run_row(path) for path in files[:limit]],
    }


@app.get("/admin/recent_runs/{account_id}")
async def admin_recent_runs(account_id: str, n: int = 10):
    return _recent_runs_payload(account_id, n=n)


@app.get("/admin/corpus_health/{account_id}")
async def admin_corpus_health(account_id: str):
    runtime_root = _admin_account_runtime(account_id)
    preset = resolve_effective_preset(default_run_preset_name()) or {}
    model = preset.get("training_policy_model") if isinstance(preset.get("training_policy_model"), dict) else {}
    validation = preset.get("training_policy_validation") if isinstance(preset.get("training_policy_validation"), dict) else {}
    warnings = []
    bucket_count = len((model or {}).get("bucket_models") or {}) if isinstance(model, dict) else 0
    if model and not bucket_count:
        warnings.append("policy_model_has_zero_bucket_specific_models")
    action_health = validation.get("action_top_bottom_health") if isinstance(validation, dict) else {}
    for warning in (action_health or {}).get("warnings") or []:
        warnings.append(str(warning))
    parent_library = _parent_library_health(runtime_root)
    if parent_library.get("ss_rank_count", 0) <= 0:
        warnings.append("parent_library_has_no_ss_rank_samples")
    recent = _recent_runs_payload(account_id, n=10)
    return {
        "account_id": account_id,
        "runtime_root": str(runtime_root),
        "parent_library": parent_library,
        "policy_model": {
            "enabled": bool((model or {}).get("enabled")),
            "feature_weights": (model or {}).get("feature_weights") or {},
            "bucket_count": bucket_count,
            "available_objective_buckets": (model or {}).get("available_objective_buckets") or [],
            "validation": validation,
        },
        "recent_runs": recent.get("runs") or [],
        "warnings": warnings,
    }


def redact_sensitive_error_text(text):
    text = str(text or "")
    for key in ("sid", "auth_key", "steam_session_ticket", "udid", "device_id"):
        pattern = rf'("{key}"\s*:\s*")[^"]*(")'
        text = re.sub(pattern, lambda m: f'{m.group(1)}<redacted>{m.group(2)}', text, flags=re.IGNORECASE)
    return text

def is_api_error(exc, codes, endpoint=None):
    text = str(exc).lower()
    endpoint_text = str(endpoint).lower() if endpoint else None
    for code in codes:
        if f"api error {code}" in text or f"{code} on" in text:
            if endpoint_text is None or endpoint_text in text:
                return True
    return False

def api_error_code(exc):
    for attr in ("result_code", "response_code"):
        try:
            value = int(getattr(exc, attr, 0) or 0)
        except (TypeError, ValueError):
            value = 0
        if value:
            return value
    match = re.search(r"api error\s+(\d+)", str(exc or ""), flags=re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            pass
    match = re.search(r"\b(\d{3,4})\s+on\s+", str(exc or ""), flags=re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            pass
    return 0

def is_no_active_career_load_error(exc):
    return is_api_error(exc, (102, 201), "single_mode_free/load")

def accepts_kwarg(fn, name):
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False
    return name in params or any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())

def load_career_for_probe(client):
    if hasattr(client, "load_career"):
        if accepts_kwarg(client.load_career, "quiet_no_career"):
            return client.load_career(quiet_no_career=True)
        return client.load_career()
    if accepts_kwarg(client.call, "quiet_result_codes"):
        return client.call("single_mode_free/load", {}, quiet_result_codes={102, 201})
    return client.call("single_mode_free/load", {})

def session_stale_detail(exc):
    detail = redact_sensitive_error_text(exc)
    return (
        "API session/auth is stale; sync cannot refresh live game data with the current captured auth. "
        "Restart the bot capture/login flow against the current in-game account, then sync again. "
        f"Original error: {detail}"
    )

def career_debug_view(career):
    if not career:
        return None
    return {
        "active": bool(career.get("active")),
        "card_id": career.get("card_id"),
        "turn": career.get("turn"),
        "scenario_id": career.get("scenario_id"),
        "deck_id": career.get("deck_id"),
        "friend_viewer_id": career.get("friend_viewer_id"),
        "friend_card_id": career.get("friend_card_id"),
        "parent_id_1": career.get("parent_id_1"),
        "parent_id_2": career.get("parent_id_2"),
    }

def clean_int_list(values):
    ids = []
    for value in values or []:
        try:
            item = int(value or 0)
        except (TypeError, ValueError):
            item = 0
        if item:
            ids.append(item)
    return ids

def sanitize_showtime_start_fields(req, load_data=None):
    """Normalize Fuji/Showtime start fields against fresh load/index data.

    Difficulty selection is valid for a new career start, but event boost is a
    separate consumable. Do not auto-enable boost just because a difficulty was
    selected; doing that with zero boost items makes the server reject
    single_mode_free/start with 102/205.
    """

    warnings = []
    requested_difficulty_id = safe_int(getattr(req, "difficulty_id", 0))
    requested_difficulty = safe_int(getattr(req, "difficulty", 0))
    requested_boost = safe_int(getattr(req, "is_boost", 0))
    requested_boost_event = safe_int(getattr(req, "boost_story_event_id", 0))
    if requested_difficulty_id <= 0 and requested_difficulty <= 0:
        if requested_boost or requested_boost_event:
            setattr(req, "is_boost", 0)
            setattr(req, "boost_story_event_id", 0)
            warnings.append("Ignored Showtime boost because no Showtime difficulty is selected.")
        return warnings

    options = showtime_difficulty_options(load_data or {})
    selected = next(
        (
            row for row in options
            if safe_int(row.get("difficulty_id")) == requested_difficulty_id
            and safe_int(row.get("difficulty")) == requested_difficulty
        ),
        None,
    )
    if not selected:
        setattr(req, "difficulty_id", 0)
        setattr(req, "difficulty", 0)
        setattr(req, "is_boost", 0)
        setattr(req, "boost_story_event_id", 0)
        warnings.append(
            f"Dropped stale Showtime selection {requested_difficulty_id}:{requested_difficulty}; "
            "fresh game data does not list it as open."
        )
        return warnings

    setattr(req, "difficulty_id", safe_int(selected.get("difficulty_id")))
    setattr(req, "difficulty", safe_int(selected.get("difficulty")))
    boost_items = safe_int(selected.get("item_num"))
    if requested_boost and boost_items > 0:
        setattr(req, "is_boost", 1)
        setattr(req, "boost_story_event_id", requested_boost_event or safe_int((load_data or {}).get("story_event_id")))
    else:
        if requested_boost or requested_boost_event:
            warnings.append(
                "Showtime difficulty will be used without boost; no boost item is available from fresh game data."
            )
        setattr(req, "is_boost", 0)
        setattr(req, "boost_story_event_id", 0)
    return warnings

def build_showtime_start_candidates(req, load_data=None):
    """Build bounded alternate encodings for Showtime career start.

    Live captures show the event row exposes one difficulty_id plus an
    open_difficulty_index, while the server has rejected at least one obvious
    selected level payload with 102/205. Keep the user's selected level first,
    then try adjacent/open-index encodings before the client falls back to a
    normal career start.
    """

    requested_difficulty_id = safe_int(getattr(req, "difficulty_id", 0))
    requested_difficulty = safe_int(getattr(req, "difficulty", 0))
    if requested_difficulty_id <= 0 or requested_difficulty <= 0:
        return []
    options = showtime_difficulty_options(load_data or {})
    selected = next(
        (
            row for row in options
            if safe_int(row.get("difficulty_id")) == requested_difficulty_id
            and safe_int(row.get("difficulty")) == requested_difficulty
        ),
        None,
    )
    if not selected:
        return []
    open_index = max(requested_difficulty, safe_int(selected.get("open_difficulty_index")))
    ordered_values = []

    def add(value):
        value = safe_int(value)
        if value <= 0 or value > open_index or value in ordered_values:
            return
        ordered_values.append(value)

    add(requested_difficulty)
    add(requested_difficulty - 1)
    add(requested_difficulty + 1)
    add(open_index)
    for value in range(open_index, 0, -1):
        add(value)

    is_boost = 1 if safe_int(getattr(req, "is_boost", 0)) > 0 else 0
    boost_story_event_id = safe_int(getattr(req, "boost_story_event_id", 0)) if is_boost else 0
    return [
        {
            "difficulty_id": requested_difficulty_id,
            "difficulty": value,
            "is_boost": is_boost,
            "boost_story_event_id": boost_story_event_id,
            "source": "selected" if value == requested_difficulty else "fallback",
            "selected_difficulty": requested_difficulty,
            "open_difficulty_index": open_index,
        }
        for value in ordered_values
    ]

def build_start_payload_preview(req, tp_info=None, current_money=None, succession_rank_point=None, allow_recover_tp=None):
    tp_info = tp_info if tp_info is not None else (apply_tp_timer_to_cached_state() or active_start_state.get("tp_info"))
    current_money = active_start_state.get("current_money", 0) if current_money is None else current_money
    succession_rank_point = selected_succession_rank_point(req) if succession_rank_point is None else succession_rank_point
    allow_recover_tp = (
        max(0, min(int(getattr(req, "allow_recover_tp", 0) or 0), TP_RECOVERY_BOTH))
        if allow_recover_tp is None
        else allow_recover_tp
    )
    return UmaClient.build_start_payload(
        card_id=getattr(req, "card_id", 0),
        support_card_ids=clean_int_list(getattr(req, "support_card_ids", []) or []),
        friend_viewer_id=getattr(req, "friend_viewer_id", 0),
        friend_card_id=getattr(req, "friend_card_id", 0),
        parent_id_1=getattr(req, "parent_id_1", 0),
        parent_id_2=getattr(req, "parent_id_2", 0),
        scenario_id=getattr(req, "scenario_id", 4),
        deck_id=getattr(req, "deck_id", 1),
        use_tp=getattr(req, "use_tp", 30),
        tp_info=tp_info,
        current_money=current_money,
        succession_rank_point=succession_rank_point,
        rental_viewer_id=getattr(req, "rental_viewer_id", 0) or 0,
        rental_trained_chara_id=getattr(req, "rental_trained_chara_id", 0) or 0,
        difficulty_id=getattr(req, "difficulty_id", 0),
        difficulty=getattr(req, "difficulty", 0),
        is_boost=getattr(req, "is_boost", 0),
        boost_story_event_id=getattr(req, "boost_story_event_id", 0),
        allow_recover_tp=allow_recover_tp,
    )

def start_proof_checks(req, preflight=None):
    errors = []
    warnings = []
    support_ids = clean_int_list(getattr(req, "support_card_ids", []) or [])
    allow_recover_tp = max(0, min(int(getattr(req, "allow_recover_tp", 0) or 0), TP_RECOVERY_BOTH))
    card_id = safe_int(getattr(req, "card_id", 0))
    friend_viewer_id = safe_int(getattr(req, "friend_viewer_id", 0))
    friend_card_id = safe_int(getattr(req, "friend_card_id", 0))
    parent_id_1 = safe_int(getattr(req, "parent_id_1", 0))
    parent_id_2 = safe_int(getattr(req, "parent_id_2", 0))
    rental_v = safe_int(getattr(req, "rental_viewer_id", 0))
    rental_t = safe_int(getattr(req, "rental_trained_chara_id", 0))
    deck_id = safe_int(getattr(req, "deck_id", 0))
    scenario_id = safe_int(getattr(req, "scenario_id", 0))
    if card_id <= 0:
        errors.append("Trainee is required before starting a career")
    if scenario_id <= 0:
        errors.append("Career scenario is required before starting a career")
    if deck_id <= 0:
        errors.append("Deck slot is required before starting a career")
    if friend_viewer_id <= 0 or friend_card_id <= 0:
        errors.append("Friend support card is required before starting a career")
    if parent_id_1 <= 0:
        errors.append("Parent 1 is required before starting a career")
    if bool(rental_v) != bool(rental_t):
        errors.append("Borrowed guest parent is incomplete; both rental viewer id and trained chara id are required")
    if parent_id_2 <= 0 and not (rental_v and rental_t):
        errors.append("Parent 2 is required unless a borrowed guest parent is selected")
    if len(support_ids) != 5:
        errors.append(f"Deck must contain exactly 5 support cards; selected payload has {len(support_ids)}")
    if len(set(support_ids)) != len(support_ids):
        errors.append("Selected deck contains duplicate support card ids")

    selection_error = validate_start_selection(req)
    if selection_error:
        errors.append(selection_error)
    fallback_error = borrow_fallback_start_error(req)
    if fallback_error:
        errors.append(fallback_error)

    tp_info = apply_tp_timer_to_cached_state() or active_start_state.get("tp_info") or {}
    if not tp_info:
        errors.append("Missing live TP state; login again before starting career")
    if "current_money" not in active_start_state:
        errors.append("Missing live item state; login again before starting career")
    current_tp = int(tp_info.get("current_tp") or 0)
    use_tp = int(getattr(req, "use_tp", 0) or 0)
    tp_recovery_status = tp_recovery_resource_status(allow_recover_tp)
    if use_tp and current_tp < use_tp:
        if not allow_recover_tp:
            errors.append(f"Not enough TP: {current_tp}/{use_tp}")
        elif not tp_recovery_status.get("can_recover"):
            errors.append(f"Not enough TP: {current_tp}/{use_tp}; {tp_recovery_unavailable_detail(tp_recovery_status)}")
        else:
            warnings.append(
                f"Low TP {current_tp}/{use_tp}; bot will recover TP before start via {tp_recovery_status.get('mode_name')}"
            )

    dashboard = (preflight or {}).get("dashboard") or {}
    if dashboard:
        deck = next((item for item in dashboard.get("decks", []) if str(item.get("id")) == str(getattr(req, "deck_id", ""))), None)
        if not deck:
            errors.append(f"Selected deck slot {getattr(req, 'deck_id', 0)} was not found in synced game data")
        else:
            deck_ids = clean_int_list([card.get("id") for card in deck.get("cards", [])])
            if len(deck_ids) != 5:
                errors.append(f"Synced deck slot {deck.get('id')} has {len(deck_ids)}/5 support cards")
            if deck_ids and deck_ids != support_ids:
                errors.append("Selected support card payload does not match the synced deck slot")

        uma_ids = {str(uma.get("id")) for uma in dashboard.get("umas", [])}
        if uma_ids and str(getattr(req, "card_id", "")) not in uma_ids:
            errors.append("Selected trainee was not found in synced owned trainee data")

        parent_ids = {str(parent.get("instance_id")) for parent in dashboard.get("parents", [])}
        # When a rental guest is selected, parent_id_2 is allowed to be 0 — the guest
        # fills slot 2 instead. parent_id_1 must always be set to a real own veteran.
        has_rental = bool(getattr(req, "rental_viewer_id", 0)) and bool(getattr(req, "rental_trained_chara_id", 0))
        parent_checks = [("Parent 1", getattr(req, "parent_id_1", 0))]
        p2 = getattr(req, "parent_id_2", 0)
        if p2 or not has_rental:
            parent_checks.append(("Parent 2", p2))
        for label, parent_id in parent_checks:
            if parent_ids and str(parent_id) not in parent_ids:
                errors.append(f"{label} was not found in synced parent data")

        owned_support_ids = {str(card.get("id")) for card in dashboard.get("supports", [])}
        if owned_support_ids:
            missing_supports = [sid for sid in support_ids if str(sid) not in owned_support_ids]
            if missing_supports:
                errors.append(f"Selected deck contains support cards not found in owned support data: {missing_supports}")

        friend_keys = {
            (str(friend.get("viewer_id")), str(friend.get("support_card_id")))
            for friend in dashboard.get("friends", [])
        }
        if friend_keys and (str(getattr(req, "friend_viewer_id", "")), str(getattr(req, "friend_card_id", ""))) not in friend_keys:
            errors.append("Selected friend support was not found in loaded friend data")
        if not friend_keys:
            warnings.append("Friend list was not loaded in dashboard data; friend support can only be verified by start")

    payload_preview = None
    showtime_candidates = []
    if tp_info and "current_money" in active_start_state:
        payload_preview = build_start_payload_preview(
            req,
            tp_info=tp_info,
            current_money=active_start_state.get("current_money", 0),
            succession_rank_point=selected_succession_rank_point(req),
            allow_recover_tp=allow_recover_tp,
        )
        showtime_candidates = build_showtime_start_candidates(req, (preflight or {}).get("load_data") or {})

    return {
        "ok": not errors,
        "errors": errors,
        "warnings": warnings,
        "payload": payload_preview,
        "showtime_candidates": showtime_candidates,
        "support_count": len(support_ids),
        "tp_current": current_tp,
        "tp_required": use_tp,
        "allow_recover_tp": allow_recover_tp,
        "tp_recovery": tp_recovery_status,
        "career_active": bool((preflight or {}).get("career_active")),
        "borrow_quota": compute_borrow_quota(active_client) if active_client else None,
    }

def start_debug_summary(req, preflight=None, error=None, proof=None, recovery=None):
    apply_tp_timer_to_cached_state()
    support_ids = list(getattr(req, "support_card_ids", []) or [])
    tp_info = active_start_state.get("tp_info") or {}
    allow_recover_tp = max(0, min(int(getattr(req, "allow_recover_tp", 0) or 0), TP_RECOVERY_BOTH))
    tp_recovery_status = tp_recovery_resource_status(allow_recover_tp)
    preflight_summary = None
    if preflight is not None:
        preflight_account = ((preflight.get("dashboard") or {}).get("account") or {})
        preflight_summary = {
            "success": bool(preflight.get("success")),
            "career_active": bool(preflight.get("career_active")),
            "detail": redact_sensitive_error_text(preflight.get("detail", "")),
            "account_career": career_debug_view(preflight_account.get("career")),
        }
    try:
        succession_rank_point = selected_succession_rank_point(req)
    except Exception:
        succession_rank_point = active_start_state.get("succession_rank_point", 0)
    summary = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "request": {
            "card_id": getattr(req, "card_id", 0),
            "support_card_ids": support_ids,
            "support_count": len([sid for sid in support_ids if sid]),
            "friend_viewer_id": getattr(req, "friend_viewer_id", 0),
            "friend_card_id": getattr(req, "friend_card_id", 0),
            "parent_id_1": getattr(req, "parent_id_1", 0),
            "parent_id_2": getattr(req, "parent_id_2", 0),
            "scenario_id": getattr(req, "scenario_id", 0),
            "deck_id": getattr(req, "deck_id", 0),
            "use_tp": getattr(req, "use_tp", 0),
            "allow_recover_tp": allow_recover_tp,
            "difficulty_id": getattr(req, "difficulty_id", 0),
            "difficulty": getattr(req, "difficulty", 0),
        },
        "state": {
            "tp_current": tp_info.get("current_tp"),
            "tp_max": tp_info.get("max_tp"),
            "tp_recovery": tp_recovery_status,
            "current_money_present": "current_money" in active_start_state,
            "current_money": active_start_state.get("current_money"),
            "succession_rank_point": succession_rank_point,
            "start_state_keys": sorted(active_start_state.keys()),
            "account_career": career_debug_view((active_account or {}).get("career")),
        },
        "preflight": preflight_summary,
    }
    if error:
        summary["error"] = redact_sensitive_error_text(error)
    if proof is not None:
        summary["proof"] = proof
    if recovery is not None:
        summary["tp_recovery_attempt"] = recovery
    return summary

def record_start_debug(req, preflight=None, error=None, proof=None, recovery=None):
    global active_start_debug
    active_start_debug = start_debug_summary(req, preflight=preflight, error=error, proof=proof, recovery=recovery)
    return active_start_debug

def write_start_error_snapshot(debug):
    try:
        root = dev_runtime_dir() / "error_snapshots" / "career_start"
        root.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        micros = int((time.time() % 1) * 1_000_000)
        path = root / f"{stamp}_{micros:06d}_career_start.json"
        payload = json.loads(redact_sensitive_error_text(json.dumps(debug or {}, ensure_ascii=False, default=str)))
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        latest = root / "latest_career_start.json"
        latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
    except Exception:
        return ""

def start_rejection_detail(code, proof=None):
    code_text = str(code or "unknown")
    errors = list((proof or {}).get("errors") or [])
    warnings = list((proof or {}).get("warnings") or [])
    if errors:
        return f"Server rejected career start ({code_text}); local preflight now reports: " + "; ".join(errors)
    detail = (
        f"Server rejected career start ({code_text}). Fresh game data did not expose a local payload error, "
        "so the selected deck/friend/parents may be stale or invalid on the server."
    )
    if warnings:
        detail += " Warnings: " + "; ".join(warnings)
    detail += " Check /api/debug/start or uma_runtime/error_snapshots/career_start/latest_career_start.json."
    return detail

def refresh_live_start_state():
    global active_dashboard_data
    if not active_client or not hasattr(active_client, "call"):
        return {"success": True, "skipped": True}
    try:
        load_result = load_index_with_session_recovery(active_client)
        load_data = load_result.get('data', {})
        sync_game_data_from_api_response("load/index", load_result, source="live_start_state")
        if hasattr(active_client, "refresh_cached_account_state"):
            active_client.refresh_cached_account_state(load_data)
        career_res = None
        career_data = None
        try:
            career_res = load_career_for_probe(active_client)
            sync_game_data_from_api_response("single_mode_free/load", career_res, source="live_start_state")
            if (career_res.get("data") or {}).get("chara_info"):
                career_data = career_res.get("data")
        except Exception as career_exc:
            if is_no_active_career_load_error(career_exc):
                print("start preflight career probe: no active career", flush=True)
            else:
                print(f"start preflight career probe ignored: {career_exc}", flush=True)
        dashboard = build_dashboard_data(load_data, career_data, preserve_friends=True)
        dashboard["selection"] = reconcile_active_selection()
        dashboard["loop"] = loop_snapshot()
        dashboard["success"] = True
        active_dashboard_data = dashboard
        persist_dev_session_cache("live_start_state")
        career = (dashboard.get("account") or {}).get("career") or {}
        return {
            "success": True,
            "dashboard": dashboard,
            "career_active": bool(career.get("active")),
            "load_data": load_data,
            "career_result": career_res,
        }
    except Exception as exc:
        return {"success": False, "detail": redact_sensitive_error_text(exc)}

def start_career_from_request(req):
    global active_start_debug
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if not req.friend_viewer_id or not req.friend_card_id:
        return {"success": False, "detail": "Friend support card is required"}
    preflight = refresh_live_start_state()
    showtime_warnings = []
    showtime_candidates = []
    if preflight.get("success") and not preflight.get("career_active"):
        showtime_warnings = sanitize_showtime_start_fields(req, preflight.get("load_data") or {})
        showtime_candidates = build_showtime_start_candidates(req, preflight.get("load_data") or {})
    proof = start_proof_checks(req, preflight=preflight) if preflight.get("success") and not preflight.get("career_active") else None
    if proof is not None and showtime_warnings:
        proof.setdefault("warnings", []).extend(showtime_warnings)
    record_start_debug(req, preflight=preflight, proof=proof)
    if not preflight.get("success"):
        return {"success": False, "detail": f"Could not refresh live state before start: {preflight.get('detail')}"}
    if preflight.get("career_active"):
        return {
            "success": False,
            "detail": "An active career already exists on the server. Sync game data, then resume or delete the existing career before starting a new one.",
            "account": ((preflight.get("dashboard") or {}).get("account") or {}),
        }
    if proof and proof.get("errors"):
        return {"success": False, "detail": "; ".join(proof["errors"]), "proof": proof}
    selection_error = validate_start_selection(req)
    if selection_error:
        return {"success": False, "detail": selection_error}
    if not active_start_state.get('tp_info'):
        return {"success": False, "detail": "Missing live TP state; login again before starting career"}
    if 'current_money' not in active_start_state:
        return {"success": False, "detail": "Missing live item state; login again before starting career"}

    tp_info = apply_tp_timer_to_cached_state() or active_start_state['tp_info']
    current_tp = int(tp_info.get('current_tp') or 0)
    allow_recover_tp = max(0, min(int(getattr(req, "allow_recover_tp", 0) or 0), 3))
    tp_recovery_status = tp_recovery_resource_status(allow_recover_tp)
    recovery_result = None
    if req.use_tp and current_tp < req.use_tp:
        if not allow_recover_tp:
            return {"success": False, "detail": f"Not enough TP: {current_tp}/{req.use_tp}"}
        if not tp_recovery_status.get("can_recover"):
            return {
                "success": False,
                "detail": f"Not enough TP: {current_tp}/{req.use_tp}; {tp_recovery_unavailable_detail(tp_recovery_status)}",
            }
        recovery_result = attempt_tp_recovery_before_start(req, allow_recover_tp, int(req.use_tp or 0))
        record_start_debug(req, preflight=preflight, proof=proof, recovery=recovery_result)
        tp_info = active_start_state.get('tp_info') or tp_info
        current_tp = int(tp_info.get('current_tp') or 0)
        if current_tp < req.use_tp:
            recovery_errors = "; ".join(recovery_result.get("errors") or [])
            if not recovery_errors:
                recovery_errors = f"TP remained {current_tp}/{req.use_tp}"
            return {
                "success": False,
                "detail": f"Could not recover TP before career start: {recovery_errors}",
                "tp_recovery_attempt": recovery_result,
            }
    current_money = active_start_state['current_money']
    succession_rank_point = selected_succession_rank_point(req)
    start_allow_recover_tp = allow_recover_tp if req.use_tp and current_tp < req.use_tp else 0
    # Per-iteration guest-vs-fallback decision. refresh_live_start_state() above just
    # called load/index and refreshed client.cached_load_data, so compute_borrow_quota
    # now reads the latest single_mode_rental_succession_num — critical for loop iterations
    # where the rental count climbs as previous runs consumed borrows.
    rental_v = int(getattr(req, "rental_viewer_id", 0) or 0)
    rental_t = int(getattr(req, "rental_trained_chara_id", 0) or 0)
    fallback_id = int(getattr(req, "borrow_fallback_id", 0) or 0)
    effective_parent_id_2 = req.parent_id_2
    quota = None
    if rental_v and rental_t:
        quota = compute_borrow_quota(active_client)
        if quota.get("remaining", 0) <= 0:
            rental_v = 0
            rental_t = 0
            if fallback_id and fallback_id != req.parent_id_1:
                effective_parent_id_2 = fallback_id
    if rental_v == 0 and rental_t == 0 and int(effective_parent_id_2 or 0) == 0:
        fallback_error = borrow_fallback_start_error(req, quota=quota)
        if fallback_error:
            fallback_proof = start_proof_checks(req, preflight=preflight)
            if showtime_warnings:
                fallback_proof.setdefault("warnings", []).extend(showtime_warnings)
            record_start_debug(req, preflight=preflight, proof=fallback_proof, recovery=recovery_result, error=fallback_error)
            return {
                "success": False,
                "detail": fallback_error,
                "proof": fallback_proof,
                "account": ((preflight.get("dashboard") or {}).get("account") or {}),
            }
    try:
        result = active_client.start_career(
            card_id=req.card_id,
            support_card_ids=req.support_card_ids,
            friend_viewer_id=req.friend_viewer_id,
            friend_card_id=req.friend_card_id,
            parent_id_1=req.parent_id_1,
            parent_id_2=effective_parent_id_2,
            scenario_id=req.scenario_id,
            deck_id=req.deck_id,
            use_tp=req.use_tp,
            tp_info=tp_info,
            current_money=current_money,
            succession_rank_point=succession_rank_point,
            rental_viewer_id=rental_v,
            rental_trained_chara_id=rental_t,
            difficulty_id=req.difficulty_id,
            difficulty=req.difficulty,
            is_boost=req.is_boost,
            boost_story_event_id=req.boost_story_event_id,
            allow_recover_tp=start_allow_recover_tp,
            difficulty_candidates=showtime_candidates,
        )
    except Exception as exc:
        if is_api_error(exc, (102, 205, 2511, 1052), "single_mode_free/start"):
            post_check = refresh_live_start_state()
            post_warnings = []
            if post_check.get("success") and not post_check.get("career_active"):
                post_warnings = sanitize_showtime_start_fields(req, post_check.get("load_data") or {})
            post_proof = start_proof_checks(req, preflight=post_check) if post_check.get("success") and not post_check.get("career_active") else proof
            if post_proof is not None and post_warnings:
                post_proof.setdefault("warnings", []).extend(post_warnings)
            active_start_debug = start_debug_summary(req, preflight=post_check, error=exc, proof=post_proof, recovery=recovery_result)
            snapshot_path = write_start_error_snapshot(active_start_debug)
            code = api_error_code(exc)
            detail = start_rejection_detail(code, post_proof)
            if req.use_tp and current_tp < req.use_tp and allow_recover_tp:
                detail = (
                    f"Server rejected career start ({code or 'unknown'}) while TP was still below the start cost. "
                    "Check Bot View or /api/debug/start for the TP recovery attempt, selected resources, "
                    "and sanitized start payload."
                )
            return {
                "success": False,
                "detail": detail,
                "proof": post_proof,
                "debug_snapshot": snapshot_path,
                "account": (((post_check.get("dashboard") or {}).get("account") or {}) if post_check.get("success") else None),
            }
        record_start_debug(req, preflight=preflight, error=exc, proof=proof, recovery=recovery_result)
        raise
    # Optimistic borrow-count decrement. The server increments single_mode_rental_succession_num
    # when a rental is consumed, but cached_load_data only refreshes via load/index — so without
    # this bump the UI would still display the pre-call count until the next iteration's
    # refresh_live_start_state. Mirrors what the server is about to record.
    if rental_v and rental_t:
        cached = getattr(active_client, "cached_load_data", None)
        if isinstance(cached, dict):
            cached["single_mode_rental_succession_num"] = int(cached.get("single_mode_rental_succession_num") or 0) + 1
    record_start_debug(req, preflight=preflight, proof=proof, recovery=recovery_result)
    return {
        "success": True,
        "result": result,
        "run_context": build_run_context(
            req,
            {},
            started_from_active_career=False,
            effective_parent_id_2=effective_parent_id_2,
            rental_viewer_id=rental_v,
            rental_trained_chara_id=rental_t,
        ),
    }

def preflight_career_run_request(req):
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if career_runner.snapshot().get("running") or loop_snapshot().get("active"):
        return {"success": False, "detail": "Career runner already active"}

    preflight = refresh_live_start_state()
    if not preflight.get("success"):
        record_start_debug(req, preflight=preflight)
        return {"success": False, "detail": f"Could not refresh live state before proof: {preflight.get('detail')}"}
    if preflight.get("career_active"):
        proof = {
            "ok": True,
            "mode": "resume_existing_career",
            "errors": [],
            "warnings": [],
            "career_active": True,
        }
        record_start_debug(req, preflight=preflight, proof=proof)
        return {
            "success": True,
            "detail": "Active career exists; RUN CAREER would resume the existing career instead of starting a new one.",
            "proof": proof,
            "account": ((preflight.get("dashboard") or {}).get("account") or {}),
        }

    showtime_warnings = sanitize_showtime_start_fields(req, preflight.get("load_data") or {})
    if not getattr(req, "friend_viewer_id", 0) or not getattr(req, "friend_card_id", 0):
        proof = {"ok": False, "errors": ["Friend support card is required"], "warnings": []}
        if showtime_warnings:
            proof.setdefault("warnings", []).extend(showtime_warnings)
        record_start_debug(req, preflight=preflight, proof=proof)
        return {"success": False, "detail": "Friend support card is required", "proof": proof}

    proof = start_proof_checks(req, preflight=preflight)
    if showtime_warnings:
        proof.setdefault("warnings", []).extend(showtime_warnings)
    record_start_debug(req, preflight=preflight, proof=proof)
    if proof.get("errors"):
        return {"success": False, "detail": "; ".join(proof["errors"]), "proof": proof}
    return {
        "success": True,
        "detail": "Start proof passed. This did not start a career.",
        "proof": proof,
        "payload": proof.get("payload"),
    }

def apply_career_result(result):
    global active_account, active_dashboard_data
    result_data = result.get('data', {})
    prior_account = active_account or (active_dashboard_data.get("account") if active_dashboard_data else None) or {}
    account = sync_game_data_from_api_response("single_mode_free/start", result, source="career_result")
    if account is None:
        update_start_state(result_data)
        account = get_account_status(dict(active_start_state), result_data if result_data.get('chara_info') else None)
    # The single_mode_free/start response carries the new chara_info but does not
    # include root-level coin_info / item_list. Without this guard, get_account_status
    # would zero out the cached home-screen carrots / toughness / gold the instant a
    # new career starts. Preserve the values from the prior cached account when the
    # career-start response doesn't carry them.
    if not result_data.get("coin_info") and prior_account.get("carrots"):
        account["carrots"] = prior_account.get("carrots")
    if not result_data.get("item_list") and not result_data.get("user_item_array"):
        if prior_account.get("gold") is not None:
            account["gold"] = prior_account.get("gold")
        if prior_account.get("toughness") is not None:
            account["toughness"] = prior_account.get("toughness")
    chara_info = result_data.get('chara_info') or {}
    if chara_info:
        card_id = str(chara_info.get('card_id', ''))
        account["career"] = {
            "active": True,
            "card_id": card_id,
            "name": chara_map.get(card_id, f"Unknown ({card_id})"),
            "turn": chara_info.get('turn', 0),
            "scenario_id": chara_info.get('scenario_id', 0),
            "fans": chara_info.get('fans', 0),
            "vital": chara_info.get('vital', 0),
            "max_vital": chara_info.get('max_vital', 0)
        }
    active_account = account
    if active_dashboard_data:
        active_dashboard_data["account"] = account
    persist_dev_session_cache("career_result")
    return account, chara_info

def loop_snapshot():
    with loop_lock:
        return dict(active_loop)

def update_loop_state(**values):
    with loop_lock:
        active_loop.update(values)
        return dict(active_loop)

def reset_loop_state():
    return update_loop_state(
        active=False,
        stop_requested=False,
        mode="forever",
        requested=0,
        career_limit=0,
        fan_limit=0,
        fans=0,
        completed=0,
        current=0,
        waiting_for_tp=False,
        tp_current=0,
        tp_required=0,
        last_error="",
        last_message=""
    )

def request_loop_stop():
    release_deferred_backend_restart_on_manual_stop()
    update_loop_state(stop_requested=True, last_message="stop requested")

def loop_should_stop():
    with loop_lock:
        return bool(active_loop.get("stop_requested"))

def refresh_account_state():
    global active_account, active_dashboard_data
    if not active_client:
        raise RuntimeError("Not logged in")
    index_result = load_index_with_session_recovery(active_client)
    load_data = index_result.get('data', {})
    account = sync_game_data_from_api_response("load/index", index_result, source="account_refresh")
    if account is None:
        update_start_state(load_data)
        account = get_account_status(load_data)
    active_account = account
    if active_dashboard_data:
        active_dashboard_data["account"] = account
    return account

def is_client_version_stale_error(exc):
    """204 from `tool/start_session` with a `store_url` in the response
    is this game's "client version too old, go update via this URL"
    signal. It is TERMINAL — no session refresh path will fix it.
    The user must update SWEEPY_DEFAULT_APP_VER / SWEEPY_DEFAULT_RES_VER
    (or re-capture auth from a current game build).
    """
    text = str(exc)
    if "204 on tool/start_session" not in text and "API error 204" not in text:
        return False
    return "store_url" in text


def client_version_stale_detail(exc):
    detail = redact_sensitive_error_text(exc)
    return (
        "Game client version is too old for the current server build. "
        "The server returned 204 with a store_url pointing to an updated client. "
        "Sweepy attempted automatic APP-VER/RES-VER discovery first. If this message remains, "
        "update the installed game client or re-capture auth once from the current build so the "
        "live version metadata can be cached. SWEEPY_DEFAULT_APP_VER and SWEEPY_DEFAULT_RES_VER "
        "are still available as manual overrides. Retrying will not help while the same stale metadata is used; "
        "retrying the same cached metadata will not fix this. "
        f"Original error: {detail}"
    )


def is_recoverable_session_error(exc):
    # 204 with store_url is NOT recoverable — it's a client-version
    # mismatch that no retry will fix. Surface it as terminal instead
    # of feeding it back into the session-refresh loop, which was
    # observed hammering the server every few seconds without progress.
    if is_client_version_stale_error(exc):
        return False
    text = str(exc).lower()
    return any(
        token in text
        for token in (
            "api error 394",
            "api error 501",
            "api error 709",
            "api error 202",
            "394 on",
            "501 on",
            "709 on",
        )
    )

def load_index_with_session_recovery(client, _retry_201=3):
    global active_client
    try:
        return client.call('load/index', {'adid': ''})
    except Exception as exc:
        # Client-version-stale: raise immediately with the actionable
        # detail. is_recoverable_session_error already returns False
        # for this case, but we want the caller to see the helpful
        # message rather than the raw API-error text.
        if is_client_version_stale_error(exc):
            raise RuntimeError(client_version_stale_detail(exc)) from exc
        # 201 on load/index is a TRANSIENT server-state code (the account
        # index isn't ready yet — typically right after a viewer-id remap).
        # It is not a stale-session error, so the auth-refresh path can't
        # help, and it clears on its own after a moment. Retry a few times
        # with a short backoff before surfacing it.
        if is_api_error(exc, (201,), "load/index") and _retry_201 > 0:
            print(
                f"201 on load/index (transient state); retrying in 1.5s ({_retry_201} left)",
                flush=True,
            )
            time.sleep(1.5)
            return load_index_with_session_recovery(client, _retry_201=_retry_201 - 1)
        if not is_recoverable_session_error(exc):
            raise
        can_relogin = hasattr(client, "login") and (
            not hasattr(client, "has_captured_auth") or client.has_captured_auth()
        )
        if not can_relogin:
            raise RuntimeError(session_stale_detail(exc)) from exc
        print(f"load/index session stale ({exc}); restarting API session", flush=True)
        try:
            return client.login(max_retries=3)
        except Exception as relog_exc:
            if is_recoverable_session_error(relog_exc):
                cfg = client_dev_session_config(client) or getattr(client, "_sweepy_auth_config", None) or {}
                try:
                    refreshed_cfg, refreshed_client, refreshed_res = rebuild_reusable_auth_from_cached_ticket(cfg)
                    if client is active_client:
                        try:
                            old_session = getattr(client, "session", None)
                            if old_session is not None:
                                old_session.close()
                        except Exception:
                            pass
                        active_client = refreshed_client
                    save_reusable_auth_profile(refreshed_cfg, "load_index_auto_refresh")
                    persist_dev_session_cache("load_index_auto_refresh")
                    print("load/index recovered after automatic reusable-auth refresh", flush=True)
                    return refreshed_res
                except Exception as refresh_exc:
                    raise RuntimeError(session_stale_detail(f"{relog_exc}; automatic auth refresh failed: {refresh_exc}")) from relog_exc
            raise


def game_api_call_with_session_recovery(endpoint, payload=None, *, client=None, **call_kwargs):
    """Call a read/profile endpoint and recover stale auth once if needed.

    Several UI features hit endpoints outside `load/index` (friend borrow,
    Team Trials profiles, deck probes). Those used to surface 394/501/709 as
    "no access" even though `load/index` could have refreshed the session.
    """
    global active_client
    client = client or active_client
    if not client:
        raise RuntimeError("Not logged in")
    payload = payload or {}
    try:
        return client.call(endpoint, payload, **call_kwargs)
    except Exception as exc:
        if is_client_version_stale_error(exc):
            raise RuntimeError(client_version_stale_detail(exc)) from exc
        if not is_recoverable_session_error(exc):
            raise
        load_index_with_session_recovery(client)
        client = active_client or client
        return client.call(endpoint, payload, **call_kwargs)


def client_method_with_session_recovery(method_name, *args, client=None, **kwargs):
    global active_client
    client = client or active_client
    if not client:
        raise RuntimeError("Not logged in")
    try:
        return getattr(client, method_name)(*args, **kwargs)
    except Exception as exc:
        if is_client_version_stale_error(exc):
            raise RuntimeError(client_version_stale_detail(exc)) from exc
        if not is_recoverable_session_error(exc):
            raise
        load_index_with_session_recovery(client)
        client = active_client or client
        return getattr(client, method_name)(*args, **kwargs)

def current_tp_amount(account=None):
    if account is None:
        apply_tp_timer_to_cached_state()
        account = active_account or {}
    tp = account.get("tp") or {}
    return int(tp.get("current") or 0)

def wait_for_loop_tp(req):
    required = max(0, int(req.use_tp or 0))
    recovery_mode = max(0, min(int(getattr(req, "allow_recover_tp", 0) or 0), TP_RECOVERY_BOTH))
    if required <= 0:
        update_loop_state(waiting_for_tp=False, tp_current=0, tp_required=0)
        return True

    while not loop_should_stop():
        account = refresh_account_state()
        current_tp = current_tp_amount(account)
        recovery_status = tp_recovery_resource_status(recovery_mode)
        if current_tp >= required:
            update_loop_state(
                waiting_for_tp=False,
                tp_current=current_tp,
                tp_required=required,
                last_message="TP ready"
            )
            return True
        if recovery_mode and recovery_status.get("can_recover"):
            update_loop_state(
                waiting_for_tp=False,
                tp_current=current_tp,
                tp_required=required,
                last_message=f"TP recovery resource ready via {recovery_status.get('mode_name')}"
            )
            return True
        wait_message = f"waiting for TP {current_tp}/{required}"
        if recovery_mode:
            wait_message = f"waiting for TP or recovery resource {current_tp}/{required}"
        update_loop_state(
            waiting_for_tp=True,
            tp_current=current_tp,
            tp_required=required,
            last_message=wait_message
        )
        for _ in range(60):
            if loop_should_stop():
                return False
            time.sleep(1)
    return False

def run_request_payload(req):
    if hasattr(req, "model_dump"):
        return req.model_dump()
    return req.dict()

def normalize_loop_config(req):
    mode = str(getattr(req, "loop_mode", "") or "forever").strip().lower()
    aliases = {
        "infinite": "forever",
        "continuous": "forever",
        "career": "careers",
        "runs": "careers",
        "run_limit": "careers",
        "fan": "fans",
        "fan_goal": "fans",
    }
    mode = aliases.get(mode, mode)
    if mode not in {"forever", "careers", "fans"}:
        mode = "forever"
    legacy_count = max(0, min(int(getattr(req, "loop_count", 0) or 0), 999))
    career_limit = max(0, min(int(getattr(req, "loop_career_limit", 0) or 0), 999))
    fan_limit = max(0, min(int(getattr(req, "loop_fan_limit", 0) or 0), 999_999_999))
    if mode == "careers" and not career_limit:
        career_limit = legacy_count or 1
    if mode != "careers":
        career_limit = 0
    if mode != "fans":
        fan_limit = 0
    return {
        "mode": mode,
        "career_limit": career_limit,
        "fan_limit": fan_limit,
        "requested": career_limit if mode == "careers" else 0,
    }


def _compact_selected_parent(parent_id):
    parent_id = int(parent_id or 0)
    if not parent_id or not active_dashboard_data:
        return None
    for parent in active_dashboard_data.get("parents") or []:
        if int(parent.get("instance_id") or 0) == parent_id:
            return {
                "instance_id": parent_id,
                "card_id": int(parent.get("card_id") or 0),
                "name": parent.get("name") or "",
                "rank": parent.get("rank"),
                "score": parent.get("score"),
                "made_by_bot": bool(parent.get("made_by_bot")),
                "source_kind": parent.get("source_kind") or "user",
            }
    return {"instance_id": parent_id}


def _compact_selected_deck(deck_id):
    deck_id = int(deck_id or 0)
    if not deck_id or not active_dashboard_data:
        return None
    for deck in active_dashboard_data.get("decks") or []:
        if int(deck.get("id") or deck.get("deck_id") or 0) == deck_id:
            return {
                "deck_id": deck_id,
                "deck_name": deck.get("name") or deck.get("deck_name") or "",
                "support_card_ids": deck.get("support_card_ids") or deck.get("support_card_id_array") or [],
            }
    return {"deck_id": deck_id}


def _resolve_support_card_lb_levels(card_ids):
    """Look up each support card's limit_break_count from the cached load data.

    Returns a dict keyed by support_card_id (str) → {"lb": int, "exp": int}.
    Missing entries are skipped — they show up as absent in the result rather
    than as a zero, so downstream learners can tell "card not on the account"
    from "card present at 0 LB".
    """
    cached = getattr(active_client, "cached_load_data", None) or {}
    cards = cached.get("support_card_list") or []
    by_id = {}
    for row in cards:
        try:
            sid = int(row.get("support_card_id") or row.get("id") or 0)
        except (TypeError, ValueError):
            continue
        if not sid:
            continue
        by_id[sid] = {
            "lb": int(row.get("limit_break_count") or 0),
            "exp": int(row.get("exp") or 0),
        }
    result = {}
    for cid in card_ids or []:
        try:
            sid = int(cid or 0)
        except (TypeError, ValueError):
            continue
        if sid and sid in by_id:
            result[str(sid)] = by_id[sid]
    return result


def _support_catalog_snapshot():
    catalog = {}
    for raw_id, info in (support_map or {}).items():
        card_id = safe_int(raw_id)
        if not card_id or not isinstance(info, dict):
            continue
        catalog[str(card_id)] = {
            "id": card_id,
            "name": info.get("name") or f"Card {card_id}",
            "rarity": info.get("rarity") or "?",
            "type": display_support_type(info.get("type") or "Unknown"),
        }
    return catalog


def _resolve_support_card_details(card_ids):
    lb_by_id = _resolve_support_card_lb_levels(card_ids)
    catalog = _support_catalog_snapshot()
    cards = []
    for raw_id in card_ids or []:
        card_id = safe_int(raw_id)
        if not card_id:
            continue
        info = catalog.get(str(card_id), {})
        lb_info = lb_by_id.get(str(card_id), {})
        cards.append({
            "id": card_id,
            "support_card_id": card_id,
            "name": info.get("name") or f"Card {card_id}",
            "rarity": info.get("rarity") or "?",
            "type": info.get("type") or "Unknown",
            "lb_level": safe_int(lb_info.get("lb")),
            "exp": safe_int(lb_info.get("exp")),
        })
    return cards


def build_run_context(req, preset, *, started_from_active_career=False, effective_parent_id_2=None, rental_viewer_id=None, rental_trained_chara_id=None):
    preset = preset or {}
    deck = _compact_selected_deck(getattr(req, "deck_id", 0)) or {}
    parent_id_2 = effective_parent_id_2 if effective_parent_id_2 is not None else getattr(req, "parent_id_2", 0)
    support_card_ids = list(getattr(req, "support_card_ids", []) or deck.get("support_card_ids") or [])
    friend_card_id = int(getattr(req, "friend_card_id", 0) or 0)
    # All six deck cards (5 supports + 1 friend) at career start. LB levels
    # are looked up against the player's collection so the learning system
    # can correlate outcomes with actual card power, not just card identity.
    deck_card_lookup_ids = list(support_card_ids) + ([friend_card_id] if friend_card_id else [])
    support_cards = _resolve_support_card_details(support_card_ids)
    deck_quality_bucket = 2
    try:
        from career_bot.deck_quality import compute_deck_quality_bucket
        deck_quality_bucket = compute_deck_quality_bucket(support_cards)
    except Exception:
        pass
    context = {
        "preset_name": preset.get("name") or getattr(req, "preset_name", "") or default_run_preset_name(),
        "deck_id": int(getattr(req, "deck_id", 0) or 0),
        "deck_name": deck.get("deck_name") or "",
        "trainee_card_id": int(getattr(req, "card_id", 0) or 0),
        "support_card_ids": support_card_ids,
        "support_cards": support_cards,
        "support_card_lb_levels": _resolve_support_card_lb_levels(deck_card_lookup_ids),
        "deck_quality_bucket": int(deck_quality_bucket or 0),
        "friend_viewer_id": int(getattr(req, "friend_viewer_id", 0) or 0),
        "friend_card_id": friend_card_id,
        "parent_id_1": int(getattr(req, "parent_id_1", 0) or 0),
        "parent_id_2": int(parent_id_2 or 0),
        "rental_viewer_id": int(rental_viewer_id if rental_viewer_id is not None else getattr(req, "rental_viewer_id", 0) or 0),
        "rental_trained_chara_id": int(rental_trained_chara_id if rental_trained_chara_id is not None else getattr(req, "rental_trained_chara_id", 0) or 0),
        "borrow_fallback_id": int(getattr(req, "borrow_fallback_id", 0) or 0),
        "desired_parent_sparks": sanitize_desired_parent_sparks(preset.get("desired_parent_sparks")),
        "parent_farming_rules": preset.get("parent_farming_rules") or {},
        "started_from_active_career": bool(started_from_active_career),
    }
    context["parents"] = {
        "parent_1": _compact_selected_parent(context["parent_id_1"]),
        "parent_2": _compact_selected_parent(context["parent_id_2"]),
    }
    return context


def start_career_runner_once(req, loop_mode=False):
    global active_account
    clear_deferred_backend_restart_release()
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if career_runner.snapshot().get("running"):
        return {"success": False, "detail": "Career runner already active"}

    preset, detail = read_requested_preset(req)
    if not preset:
        return {"success": False, "detail": detail}
    preset = dict(preset)
    preset["_loop_mode"] = bool(loop_mode)
    req.scenario_id = int(preset.get("scenario_id") or 4)

    preflight = refresh_live_start_state()
    if not preflight.get("success"):
        return {"success": False, "detail": f"Could not refresh live state before run: {preflight.get('detail')}"}

    account = ((preflight.get("dashboard") or {}).get("account") or active_account or {})
    career = account.get("career") or {}
    run_context = None
    if career.get("active"):
        # Reuse the load/index + single_mode_free/load responses from refresh_live_start_state
        # above. A previous version re-fetched both here, which doubled the API call rate on
        # every loop iteration and contributed to server-side rate-limiting (208 storms on
        # subsequent race_entry calls).
        load_data = preflight.get("load_data") or {}
        career_result = preflight.get("career_result") or {}
        career_data = career_result.get('data') or {}
        sync_game_data_from_api_response("load/index", {"data": load_data}, source="runner_start")
        if career_data:
            sync_game_data_from_api_response("single_mode_free/load", career_result, source="runner_start")

        account = active_account or get_account_status(load_data, career_data)
        active_account = account
        chara_info = career_data.get('chara_info') or {}
        apply_deck_type_counts(preset, chara_info=chara_info)
        if not preset.get("_deck_type_counts"):
            apply_deck_type_counts(preset, req=req)
        if active_dashboard_data:
            active_dashboard_data["account"] = account
        result = career_result
        run_context = build_run_context(req, preset, started_from_active_career=True)
    else:
        apply_deck_type_counts(preset, req=req)
        started = start_career_from_request(req)
        if not started.get("success"):
            return started
        result = started["result"]
        account, chara_info = apply_career_result(result)
        if not preset.get("_deck_type_counts"):
            apply_deck_type_counts(preset, chara_info=chara_info)
        started_context = started.get("run_context") or {}
        run_context = build_run_context(
            req,
            preset,
            effective_parent_id_2=started_context.get("parent_id_2"),
            rental_viewer_id=started_context.get("rental_viewer_id"),
            rental_trained_chara_id=started_context.get("rental_trained_chara_id"),
        )

    preset["_run_context"] = run_context or build_run_context(req, preset)
    _apply_cached_deck_policy(preset)
    career_runner.start(active_client, preset, result, max(1, min(int(req.max_steps or 2500), 3000)))
    return {"success": True, "account": account, "chara_info": chara_info, "runner": career_runner.snapshot()}


def _apply_cached_deck_policy(preset: dict):
    """Hydrate `preset.learned_hyperparameters` from a per-deck cached
    policy if one exists for this trainee/deck/scenario combo.

    The cache is built offline by `tools/optimize_deck_policy.py` /
    `tools/calibrate_deck.py`. Deck-specific optimizer values win over stale
    auto-learned execution knobs for the same deck signature.
    """
    try:
        from career_bot.deck_policy_cache import (
            apply_policy_to_preset,
            deck_signature,
            load_cache,
            lookup_policy,
        )
    except Exception as exc:
        print(f"deck policy cache import failed: {exc}", flush=True)
        return
    run_context = preset.get("_run_context") or {}
    trainee_card_id = int(run_context.get("trainee_card_id") or 0)
    support_card_ids = list(run_context.get("support_card_ids") or [])
    friend_card_id = int(run_context.get("friend_card_id") or 0)
    scenario_id = int(preset.get("scenario_id") or 4)
    if not trainee_card_id or not support_card_ids:
        return
    try:
        instance = current_instance_name() if "current_instance_name" in globals() else "account_b"
    except Exception:
        instance = "account_b"
    try:
        cache = load_cache(base_dir, instance)
    except Exception as exc:
        print(f"deck policy cache load failed: {exc}", flush=True)
        return
    signature = deck_signature(
        trainee_card_id=trainee_card_id,
        support_card_ids=support_card_ids,
        scenario_id=scenario_id,
        friend_card_id=friend_card_id,
    )
    policy = lookup_policy(cache, signature)
    if not policy:
        print(f"deck policy: no cached entry for signature {signature} "
              f"(trainee={trainee_card_id}, scenario={scenario_id}, "
              f"deck={sorted(support_card_ids)})", flush=True)
        return
    before = dict(preset.get("learned_hyperparameters") or {})
    apply_policy_to_preset(preset, policy)
    after = dict(preset.get("learned_hyperparameters") or {})
    added = {k: v for k, v in after.items() if k not in before}
    changed = {k: v for k, v in after.items() if k in before and before.get(k) != v}
    print(f"deck policy: applied cached entry {signature} "
          f"(added {len(added)}, updated {len(changed)} hyperparameter keys)",
          flush=True)

def career_loop_worker(req_payload):
    completed = 0
    fan_total = 0
    req_for_limits = RunCareerRequest(**req_payload)
    loop_config = normalize_loop_config(req_for_limits)
    mode = loop_config["mode"]
    career_limit = loop_config["career_limit"]
    fan_limit = loop_config["fan_limit"]
    try:
        while True:
            while career_runner.snapshot().get("running"):
                runner_snapshot = career_runner.snapshot()
                if runner_snapshot.get("post_run_processing"):
                    stage = str(runner_snapshot.get("post_run_stage") or "post-run processing")
                    update_loop_state(last_message=stage)
                if loop_should_stop():
                    career_runner.stop()
                time.sleep(0.25)

            snapshot = career_runner.snapshot()
            finished = bool(snapshot.get("finished"))
            if finished:
                completed += 1
                fan_total += max(0, int(snapshot.get("final_fans") or 0))
                update_loop_state(completed=completed, fans=fan_total)

            if loop_should_stop():
                update_loop_state(last_message="loop stopped")
                break

            # Forever mode is resilient: a single career hitting a transient
            # error or stopping mid-game (network hiccup, 1503 finish race,
            # game-state desync) used to kill the entire loop. Now in
            # forever mode we log the issue and try the next career; the
            # loop only exits on explicit stop or repeated consecutive
            # failures.
            had_error = bool(snapshot.get("last_error"))
            run_succeeded = finished and not had_error
            if mode != "forever":
                if had_error:
                    update_loop_state(last_error=snapshot.get("last_error"), last_message="loop stopped on error")
                    break
                if not finished:
                    update_loop_state(last_message="runner stopped before career finish")
                    break
            else:
                if not run_succeeded:
                    # Track consecutive failures; bail only if persistent.
                    consecutive_failures = int(active_loop.get("consecutive_failures") or 0) + 1
                    update_loop_state(
                        consecutive_failures=consecutive_failures,
                        last_error=str(snapshot.get("last_error") or "career did not finish"),
                        last_message=f"career {consecutive_failures} did not finish; continuing forever-loop",
                    )
                    if consecutive_failures >= 5:
                        update_loop_state(last_message="loop stopped after 5 consecutive failed careers")
                        break
                else:
                    if active_loop.get("consecutive_failures"):
                        update_loop_state(consecutive_failures=0)

            if mode == "careers" and career_limit > 0 and completed >= career_limit:
                update_loop_state(last_message=f"career limit reached {completed}/{career_limit}")
                break
            if mode == "fans" and fan_limit > 0 and fan_total >= fan_limit:
                update_loop_state(last_message=f"fan goal reached {fan_total}/{fan_limit}")
                break

            try:
                req = RunCareerRequest(**req_payload)
                if not wait_for_loop_tp(req):
                    update_loop_state(last_message="loop stopped")
                    break
                result = start_career_runner_once(req, loop_mode=True)
                if not result.get("success"):
                    if mode == "forever":
                        # Failed to start: wait briefly and try again
                        consecutive_start_failures = int(active_loop.get("consecutive_start_failures") or 0) + 1
                        update_loop_state(
                            consecutive_start_failures=consecutive_start_failures,
                            last_error=result.get("detail") or "failed to start next loop",
                            last_message=f"start failure {consecutive_start_failures}; retrying",
                        )
                        if consecutive_start_failures >= 5:
                            update_loop_state(last_message="loop stopped after 5 start failures")
                            break
                        time.sleep(5.0)
                        continue
                    update_loop_state(last_error=result.get("detail") or "failed to start next loop", last_message="loop stopped")
                    break
                # Reset start-failure counter on successful start
                if active_loop.get("consecutive_start_failures"):
                    update_loop_state(consecutive_start_failures=0)
                active_run = completed + 1
                update_loop_state(
                    current=active_run,
                    waiting_for_tp=False,
                    tp_current=0,
                    tp_required=0,
                    last_message=f"started loop {active_run}",
                    last_error=""
                )
            except Exception as exc:
                if mode == "forever":
                    consecutive_exceptions = int(active_loop.get("consecutive_exceptions") or 0) + 1
                    update_loop_state(
                        consecutive_exceptions=consecutive_exceptions,
                        last_error=str(exc),
                        last_message=f"loop iteration exception {consecutive_exceptions}",
                    )
                    if consecutive_exceptions >= 5:
                        update_loop_state(last_message="loop stopped after 5 exceptions")
                        break
                    time.sleep(5.0)
                    continue
                update_loop_state(last_error=str(exc), last_message="loop stopped on error")
                break
    finally:
        update_loop_state(active=False)

@app.post("/api/login")
async def login(req: LoginRequest):
    from uma_api.client import UmaClient, get_ticket
    global active_client, active_account, active_dashboard_data, active_start_state, active_start_debug, active_parent_cards, active_parent_rank_points, pending_game_auth_config, raw_load_index_response, active_selection, seen_trained_chara_ids, most_recent_trained_chara_id
    cfg = {}
    used_cached_reusable_auth = False
    used_headless_bootstrap = False
    steam_id_for_cleanup = ""
    try:
        has_form_creds = bool(req.username and req.password)
        steam_app_id = str(req.steam_app_id or APP_ID).strip() or APP_ID
        if req.steam_id and req.steam_session_ticket:
            sid = str(req.steam_id)
            tkt = str(req.steam_session_ticket)
            print('Using provided Steam ticket')
        elif has_form_creds:
            sid, tkt = get_ticket(req.username, req.password, req.code, appid=steam_app_id)
        else:
            raise Exception('Steam credentials required')

        steam_id_for_cleanup = sid
        fresh_capture_cfg = dict(pending_game_auth_config)
        pending_game_auth_config = {}
        cfg = dict(fresh_capture_cfg)
        if not has_fresh_auth_config(cfg):
            cached_cfg = reusable_auth_config_for_steam_id(sid)
            if cached_cfg:
                cfg = dict(cached_cfg)
                used_cached_reusable_auth = True
                print(f"Using cached reusable auth for Steam account {sid}", flush=True)

        reset_loop_state()
        seen_trained_chara_ids = None
        most_recent_trained_chara_id = 0

        active_client = None
        active_account = None
        active_dashboard_data = None
        active_start_state = {}
        active_start_debug = {}
        active_parent_cards = {}
        active_parent_rank_points = {}
        raw_load_index_response = None
        active_selection = {
            "deck": None,
            "friend": None,
            "trainee": None,
            "veterans": []
        }

        cfg.update({
            'steam_id': sid,
            'steam_session_ticket': tkt,
            'steam_app_id': steam_app_id,
            'steam_username_seed': req.username,
            'steam_password_seed': req.password
        })
        if not has_fresh_auth_config(cfg):
            used_headless_bootstrap = True
            cfg.update(best_known_headless_auth_seed(sid))
        if not str(cfg.get("app_ver") or "").strip() or not str(cfg.get("res_ver") or "").strip():
            raise Exception(
                "No locally cached APP-VER / RES-VER is available for headless auth bootstrap. "
                "Set SWEEPY_DEFAULT_APP_VER and SWEEPY_DEFAULT_RES_VER, or capture auth once."
            )

        trace_api = os.environ.get("SWEEPY_TRACE_API", "1").strip().lower() not in {"0", "false", "no"}
        c = attach_turn_delay(UmaClient(cfg, trace_enabled=trace_api))
        c._sweepy_auth_config = dict(cfg)
        res = c.login()
        if not res:
            raise HTTPException(status_code=401, detail="Game login failed")
        active_client = c

        d = res.get('data', {})
        career_data = None
        if d.get('single_mode_chara_light') or d.get('single_mode_chara'):
            try:
                career_res = c.load_career()
                career_data = career_res.get('data')
            except Exception:
                pass

        active_start_state = {}
        dashboard = build_dashboard_data(d, career_data, preserve_friends=False)
        active_dashboard_data = dashboard
        resolved_cfg = client_dev_session_config(c) or dict(cfg)
        resolved_cfg["steam_username_seed"] = req.username
        resolved_cfg["steam_password_seed"] = req.password
        c._sweepy_auth_config = dict(resolved_cfg)
        save_reusable_auth_profile(resolved_cfg, "login")
        persist_dev_session_cache("login")
        return active_dashboard_data
    except Exception as e:
        msg = str(e)
        if "STEAM_GUARD_REQUIRED" in msg:
             pending_game_auth_config = cfg
             return {"success": False, "needs_2fa": True}
        if is_client_version_stale_error(e):
            return {
                "success": False,
                "detail": client_version_stale_detail(e),
                "needs_auth_refresh": True,
            }
        # 501 on tool/start_session / load/index typically means the cached in-game auth
        # (viewer_id / auth_key / udid) was captured against a different Steam account
        # than the ticket we're now logging in with. Tell the UI to offer a re-capture.
        # Same for "Fresh in-game auth capture required" raised by the pre-login check.
        needs_refresh = (
            "501 on tool/start_session" in msg
            or "501 on load/index" in msg
            or "API error 501" in msg
            or "394 on load/index" in msg
            or "API error 394" in msg
            or "API session/auth is stale" in msg
            or "Fresh in-game auth capture required" in msg
        )
        detail = msg
        if needs_refresh:
            if steam_id_for_cleanup:
                invalidate_reusable_auth_profile(steam_id_for_cleanup, "server rejected cached game auth during login")
            if used_headless_bootstrap and not used_cached_reusable_auth:
                detail = (
                    "Headless auth bootstrap failed. Local game version metadata may be stale for the current server build. "
                    "Update SWEEPY_DEFAULT_APP_VER / SWEEPY_DEFAULT_RES_VER, or capture auth once as a fallback."
                )
            else:
                detail = (
                    "Reusable auth is stale for this Steam account. "
                    "Click REFRESH AUTH to rebuild it from your Steam credentials, "
                    "without reopening the game client."
                )
        return {"success": False, "detail": detail, "needs_auth_refresh": needs_refresh}

@app.get("/api/session")
async def session_status():
    global active_client, active_dashboard_data, active_account, active_selection
    if not active_client or not active_dashboard_data:
        return {"success": False}
    apply_tp_timer_to_cached_state()
    
    data = dict(active_dashboard_data)
    if active_account:
        data["account"] = active_account
    data["selection"] = active_selection
    data["loop"] = loop_snapshot()
    data["success"] = True
    return data


@app.post("/api/auth/login_reusable")
async def login_with_reusable_auth(req: ReusableAuthLoginRequest):
    global active_client, active_account, active_dashboard_data, active_start_state, active_start_debug, active_parent_cards, active_parent_rank_points, pending_game_auth_config, raw_load_index_response, active_selection, seen_trained_chara_ids, most_recent_trained_chara_id
    requested_steam_id = ""
    selected_steam_id = ""
    try:
        requested_steam_id = str(req.steam_id or "").strip()
        profiles = load_reusable_auth_profiles()
        candidates = []
        for steam_id, entry in profiles.items():
            cfg = (entry or {}).get("config") if isinstance(entry, dict) else None
            if not isinstance(cfg, dict):
                continue
            if requested_steam_id and str(steam_id) != requested_steam_id:
                continue
            if has_fresh_auth_config(cfg):
                candidates.append((float((entry or {}).get("saved_at") or 0), str(steam_id), dict(cfg)))
        if not candidates:
            return {
                "success": False,
                "detail": "No reusable auth profile is cached for this instance. Refresh auth first.",
                "needs_auth_refresh": True,
            }
        candidates.sort(key=lambda row: row[0], reverse=True)
        _, steam_id, cfg = candidates[0]
        selected_steam_id = steam_id

        reset_loop_state()
        seen_trained_chara_ids = None
        most_recent_trained_chara_id = 0
        active_client = None
        active_account = None
        active_dashboard_data = None
        active_start_state = {}
        active_start_debug = {}
        active_parent_cards = {}
        active_parent_rank_points = {}
        raw_load_index_response = None
        pending_game_auth_config = {}
        active_selection = empty_selection()

        client, res = _authenticated_client_from_cfg(cfg, max_retries=1)
        active_client = client
        load_data = res.get("data", {})
        career_data = None
        if load_data.get("single_mode_chara_light") or load_data.get("single_mode_chara"):
            try:
                career_res = client.load_career()
                career_data = career_res.get("data")
            except Exception:
                pass
        dashboard = build_dashboard_data(load_data, career_data, preserve_friends=False)
        dashboard["selection"] = reconcile_active_selection()
        dashboard["loop"] = loop_snapshot()
        dashboard["success"] = True
        active_dashboard_data = dashboard
        resolved_cfg = client_dev_session_config(client) or dict(cfg)
        client._sweepy_auth_config = dict(resolved_cfg)
        save_reusable_auth_profile(resolved_cfg, "login_reusable")
        persist_dev_session_cache("login_reusable")
        return active_dashboard_data
    except Exception as exc:
        stale_steam_id = selected_steam_id or requested_steam_id
        if stale_steam_id and is_recoverable_session_error(exc):
            invalidate_reusable_auth_profile(stale_steam_id, "server rejected cached game auth during reusable login")
        return {
            "success": False,
            "detail": str(exc),
            "needs_auth_refresh": is_recoverable_session_error(exc) or "394" in str(exc) or "501" in str(exc),
        }


def reload_dashboard_state_from_server(*, preserve_friends=True):
    global active_client, active_dashboard_data
    load_result = load_index_with_session_recovery(active_client)
    load_data = load_result.get('data', {})
    sync_game_data_from_api_response("load/index", load_result, source="dashboard_refresh")
    if hasattr(active_client, "refresh_cached_account_state"):
        active_client.refresh_cached_account_state(load_data)
    career_data = None
    if load_data.get('single_mode_chara_light') or load_data.get('single_mode_chara'):
        try:
            career_res = active_client.load_career()
            sync_game_data_from_api_response("single_mode_free/load", career_res, source="dashboard_refresh")
            career_data = career_res.get('data')
        except Exception:
            pass
    data = build_dashboard_data(load_data, career_data, preserve_friends=preserve_friends)
    data["selection"] = reconcile_active_selection()
    data["loop"] = loop_snapshot()
    data["success"] = True
    active_dashboard_data = data
    persist_dev_session_cache("dashboard_refresh")
    return data

@app.post("/api/dashboard/refresh")
async def refresh_dashboard():
    global active_client, active_dashboard_data
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    try:
        return reload_dashboard_state_from_server(preserve_friends=True)
    except Exception as e:
        return {"success": False, "detail": str(e)}

def current_daily_event_status(*, refresh=False):
    if not active_client:
        raise RuntimeError("Not logged in")
    if refresh or not getattr(active_client, "cached_load_data", None):
        reload_dashboard_state_from_server(preserve_friends=True)
    load_data = getattr(active_client, "cached_load_data", None) or {}
    status = summarize_daily_event_status(load_data)
    cfg = DailyAutomationConfig.load(base_dir / "data" / "daily_automation_endpoints.json")
    status.setdefault("shops", {})["configured_shop_count"] = cfg.configured_shop_count()
    status["configured_actions"] = sorted(
        name
        for name, action in ((cfg.data.get("actions") or {}).items())
        if isinstance(action, dict) and action and name != "daily_shops"
    )
    return status

@app.get("/api/dailies/status")
async def dailies_status(refresh: int = 0):
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    try:
        return current_daily_event_status(refresh=bool(refresh))
    except Exception as exc:
        return {"success": False, "detail": str(exc)}


def _first_daily_record_id(status_section, key):
    for row in (status_section or {}).get("records") or []:
        if not safe_int(row.get("is_played")):
            value = safe_int(row.get(key))
            if value:
                return value
    return 0


def _assignment_for_action(req, action_name):
    assignments = getattr(req, "assignments", {}) or {}
    if not isinstance(assignments, dict):
        assignments = {}
    raw = assignments.get(action_name) or assignments.get("all") or {}
    return raw if isinstance(raw, dict) else {}


def _daily_action_context(req, status, action_name=""):
    daily = (status or {}).get("daily_race") or {}
    legend = (status or {}).get("legend_race") or {}
    daily_legend = (status or {}).get("daily_legend_race") or {}
    coin_info = getattr(active_client, "coin_info", {}) or {}
    current_num = safe_int(coin_info.get("fcoin")) + safe_int(coin_info.get("coin"))
    assignment = _assignment_for_action(req, action_name)
    trained_chara_id = safe_int(assignment.get("trained_chara_id")) or safe_int(req.trained_chara_id)
    running_style = normalize_style_id(assignment.get("running_style") or req.running_style)
    return {
        "trained_chara_id": trained_chara_id,
        "running_style": running_style,
        "daily_race_id": safe_int(req.daily_race_id) or safe_int(daily.get("next_daily_race_id")) or _first_daily_record_id(daily, "daily_race_id"),
        "legend_race_id": safe_int(req.legend_race_id) or safe_int(legend.get("next_legend_race_id")) or _first_daily_record_id(legend, "legend_race_id"),
        "daily_legend_race_id": safe_int(req.daily_legend_race_id) or safe_int(daily_legend.get("next_legend_race_id")) or _first_daily_record_id(daily_legend, "legend_race_id"),
        "legend_group_id": safe_int(legend.get("group_id")),
        "difficulty_id": safe_int(req.difficulty_id),
        "difficulty": safe_int(req.difficulty),
        "is_boost": safe_int(req.is_boost),
        "current_num": current_num,
        "get_list_time": "",
        "status": status,
    }


def _daily_skip_reason(action_name, status):
    if action_name == "team_trials_once":
        team = (status or {}).get("team_trials") or {}
        if not team.get("can_race_once"):
            return "Team Trials is not currently runnable: no RP or incomplete lineup."
    if action_name == "daily_race":
        daily = (status or {}).get("daily_race") or {}
        if safe_int(daily.get("unplayed_count")) <= 0:
            return "Daily races are already played."
    if action_name == "legend_race":
        legend = (status or {}).get("legend_race") or {}
        if safe_int(legend.get("unplayed_count")) <= 0:
            return "Legend races are already played or unavailable."
    if action_name == "daily_legend_race":
        daily_legend = (status or {}).get("daily_legend_race") or {}
        if safe_int(daily_legend.get("unplayed_count")) <= 0:
            return "Daily legend races are already played or unavailable."
    if action_name == "daily_shops":
        shop = ((status or {}).get("shops") or {}).get("limited_shop") or {}
        if not shop.get("available"):
            return "Limited/daily shop is not currently open."
    return ""


def _execute_daily_action_template(action_name, action_cfg, context):
    steps = normalize_action_steps(action_cfg)
    results = []
    if not steps:
        return [{"action": action_name, "ok": False, "blocked": True, "detail": action_config_error(action_name)}]
    for idx, step in enumerate(steps, 1):
        endpoint = str(step.get("endpoint") or "").strip().strip("/")
        if not endpoint:
            results.append({"action": action_name, "step": idx, "ok": False, "blocked": True, "detail": action_config_error(action_name)})
            continue
        payload = render_template_value(step.get("payload") or {}, context)
        try:
            quiet_raw = step.get("quiet_result_codes")
            if quiet_raw is None:
                quiet_codes = set()
            elif isinstance(quiet_raw, (list, tuple, set)):
                quiet_codes = set(quiet_raw)
            else:
                quiet_codes = {quiet_raw}
            response = game_api_call_with_session_recovery(endpoint, payload, quiet_result_codes=quiet_codes)
            headers = (response or {}).get("data_headers") or {}
            results.append(
                {
                    "action": action_name,
                    "step": idx,
                    "endpoint": endpoint,
                    "ok": True,
                    "result_code": safe_int(headers.get("result_code")),
                    "response_keys": list(((response or {}).get("data") or {}).keys()),
                }
            )
        except Exception as exc:
            results.append({"action": action_name, "step": idx, "endpoint": endpoint, "ok": False, "detail": str(exc)})
            break
    return results


@app.post("/api/dailies/run")
async def run_dailies(req: DailyAutomationRequest):
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if career_runner.snapshot().get("running") or loop_snapshot().get("active"):
        return {"success": False, "detail": "Stop the career runner before running dailies/events"}

    status = current_daily_event_status(refresh=True)
    cfg = DailyAutomationConfig.load(base_dir / "data" / "daily_automation_endpoints.json")
    requested = []
    if req.run_team_trials_once:
        requested.append("team_trials_once")
    if req.run_daily_race:
        requested.append("daily_race")
    if req.run_legend_race:
        requested.append("legend_race")
    if req.run_daily_legend_race:
        requested.append("daily_legend_race")
    if req.drain_daily_shops:
        requested.append("daily_shops")

    operations = []
    base_context = _daily_action_context(req, status)
    for action_name in requested:
        skip_reason = _daily_skip_reason(action_name, status)
        if skip_reason:
            operations.append({"action": action_name, "ok": True, "skipped": True, "detail": skip_reason})
            continue
        context = _daily_action_context(req, status, action_name=action_name)
        action_cfg = cfg.action(action_name)
        if action_name == "daily_shops":
            if not action_cfg.get("shops"):
                operations.append({"action": action_name, "ok": False, "blocked": True, "detail": action_config_error(action_name)})
                continue
            shop_results = []
            for idx, shop_cfg in enumerate(action_cfg.get("shops") or [], 1):
                for result in _execute_daily_action_template(f"{action_name}:{idx}", shop_cfg, context):
                    shop_results.append(result)
                    operations.append(result)
                if any(not row.get("ok") for row in shop_results):
                    break
            continue
        elif not action_cfg.get("endpoint"):
            operations.append({"action": action_name, "ok": False, "blocked": True, "detail": action_config_error(action_name)})
            continue
        operations.extend(_execute_daily_action_template(action_name, action_cfg, context))

    if not requested:
        return {"success": False, "detail": "Select at least one daily/event action", "status": status, "operations": operations}
    if any(row.get("blocked") for row in operations):
        return {
            "success": False,
            "detail": "One or more requested actions need captured endpoint templates before they can run safely.",
            "status": status,
            "operations": operations,
            "request": {
                "trained_chara_id": safe_int(req.trained_chara_id),
                "running_style": normalize_style_id(req.running_style),
                "legend_race_id": safe_int(base_context.get("legend_race_id")),
                "daily_race_id": safe_int(base_context.get("daily_race_id")),
                "daily_legend_race_id": safe_int(base_context.get("daily_legend_race_id")),
                "assignments": getattr(req, "assignments", {}) or {},
                "difficulty_id": safe_int(req.difficulty_id),
                "difficulty": safe_int(req.difficulty),
                "is_boost": safe_int(req.is_boost),
            },
        }
    if any(not row.get("ok") for row in operations):
        return {"success": False, "detail": "One or more daily/event actions failed.", "status": current_daily_event_status(refresh=True), "operations": operations}
    return {"success": True, "detail": "Daily/event actions completed", "status": current_daily_event_status(refresh=True), "operations": operations}

@app.post("/api/supports/limit_break_all")
async def limit_break_all_supports():
    global active_client
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if career_runner.snapshot().get("running") or loop_snapshot().get("active"):
        return {"success": False, "detail": "Stop the career runner before uncapping support cards"}

    try:
        reload_dashboard_state_from_server(preserve_friends=True)
        cached_load = getattr(active_client, "cached_load_data", {}) or {}

        plan = support_limit_break_plan_from_load_data(cached_load)
        if not plan:
            dashboard = reload_dashboard_state_from_server(preserve_friends=True)
            return {
                "success": True,
                "detail": "No owned support cards have duplicate stock available for live uncapping.",
                "cards_updated": 0,
                "total_steps_applied": 0,
                "operations": [],
                "dashboard": dashboard,
            }

        operations = []
        total_steps_applied = 0
        for row in plan:
            support_card_id = safe_int(row.get("support_card_id"))
            available_steps = max(0, safe_int(row.get("available_steps")))
            if support_card_id <= 0 or available_steps <= 0:
                continue
            applied_steps = 0
            for _ in range(available_steps):
                active_client.limit_break_support_card(
                    support_card_id=support_card_id,
                    material_support_card_num=1,
                )
                applied_steps += 1
            if applied_steps:
                total_steps_applied += applied_steps
                operations.append({
                    **row,
                    "applied_steps": applied_steps,
                    "new_limit_break_count": min(4, safe_int(row.get("current_limit_break_count")) + applied_steps),
                    "remaining_stock": max(0, safe_int(row.get("stock")) - applied_steps),
                })

        dashboard = reload_dashboard_state_from_server(preserve_friends=True)
        return {
            "success": True,
            "detail": f"Applied {total_steps_applied} duplicate support uncaps across {len(operations)} card(s).",
            "cards_updated": len(operations),
            "total_steps_applied": total_steps_applied,
            "operations": operations,
            "dashboard": dashboard,
        }
    except Exception as exc:
        detail = str(exc)
        refreshed = None
        try:
            refreshed = reload_dashboard_state_from_server(preserve_friends=True)
        except Exception:
            refreshed = None
        return {
            "success": False,
            "detail": detail,
            "dashboard": refreshed,
        }

class UISelectionRequest(BaseModel):
    selection: dict

@app.post("/api/selection")
async def update_selection(req: UISelectionRequest):
    global active_selection
    active_selection = req.selection
    persist_dev_session_cache("selection")
    return {"success": True}

@app.post("/api/auth/refresh")
async def auth_refresh(req: LoginRequest | None = None):
    """Refresh reusable auth from Steam credentials when available.

    Falls back to the old game-client capture flow only when no credentials are supplied.
    """
    try:
        clear_dev_session_cache()
        has_form_creds = bool(req and req.username and req.password)
        has_ticket = bool(req and req.steam_id and req.steam_session_ticket)
        if has_form_creds or has_ticket:
            refresh_reusable_auth_headlessly(req)
            return {
                "success": True,
                "mode": "headless",
                "detail": "Reusable auth refreshed from Steam credentials. You can log in now.",
            }
        ok = refresh_auth_before_serving()
        if not ok:
            return {
                "success": False,
                "detail": "Auth capture failed. Make sure Steam is signed into the target account, then try again.",
            }
        return {"success": True, "mode": "capture", "detail": "Fresh in-game auth captured. You can log in now."}
    except Exception as exc:
        return {"success": False, "detail": str(exc)}


@app.post("/api/logout")
async def logout():
    global active_client, active_account, active_dashboard_data, active_start_state, active_start_debug, active_parent_cards, active_parent_rank_points, raw_load_index_response, pending_game_auth_config, active_selection
    request_loop_stop()
    career_runner.stop()
    active_client = None
    active_account = None
    active_dashboard_data = None
    active_start_state = {}
    active_start_debug = {}
    active_parent_cards = {}
    active_parent_rank_points = {}
    raw_load_index_response = None
    pending_game_auth_config = {}
    active_selection = {
        "deck": None,
        "friend": None,
        "trainee": None,
        "veterans": []
    }
    clear_dev_session_cache()
    return {"success": True}

@app.post("/api/career/start")
async def start_career(req: StartCareerRequest):
    try:
        started = start_career_from_request(req)
        if not started.get("success"):
            return started
        account, chara_info = apply_career_result(started["result"])
        persist_dev_session_cache("career_start")
        return {"success": True, "account": account, "chara_info": chara_info}
    except Exception as e:
        return {"success": False, "detail": str(e)}

@app.post("/api/career/run/preflight")
async def run_career_preflight(req: RunCareerRequest):
    try:
        return preflight_career_run_request(req)
    except Exception as e:
        return {"success": False, "detail": redact_sensitive_error_text(e)}

@app.post("/api/career/run")
async def run_career(req: RunCareerRequest):
    global loop_thread
    if career_runner.snapshot().get("running") or loop_snapshot().get("active"):
        return {"success": False, "detail": "Career runner already active"}
    try:
        loop_requested = bool(req.loop_enabled)
        result = start_career_runner_once(req, loop_mode=loop_requested)
        if not result.get("success"):
            return result

        reset_loop_state()
        if loop_requested:
            loop_config = normalize_loop_config(req)
            update_loop_state(
                active=True,
                mode=loop_config["mode"],
                requested=loop_config["requested"],
                career_limit=loop_config["career_limit"],
                fan_limit=loop_config["fan_limit"],
                fans=0,
                completed=0,
                current=1,
                last_message="started loop 1"
            )
            loop_thread = threading.Thread(
                target=career_loop_worker,
                args=(run_request_payload(req),),
                daemon=True
            )
            loop_thread.start()
        result["loop"] = loop_snapshot()
        return result
    except Exception as e:
        return {"success": False, "detail": str(e)}

@app.get("/api/career/runner")
async def career_runner_status():
    apply_tp_timer_to_cached_state()
    account = None
    parents = None
    if active_dashboard_data:
        account = active_dashboard_data.get("account")
        parents = active_dashboard_data.get("parents")
    if account is None:
        account = active_account
    return {
        "success": True,
        "runner": career_runner.snapshot(),
        "loop": loop_snapshot(),
        "account": account,
        "parents": parents,
        "borrow_quota": compute_borrow_quota(active_client) if active_client else None,
    }

@app.post("/api/career/runner/stop")
async def stop_career_runner():
    request_loop_stop()
    career_runner.stop()
    return {"success": True, "runner": career_runner.snapshot(), "loop": loop_snapshot()}


@app.get("/api/debug/pre_single_mode_dump")
async def debug_pre_single_mode_dump():
    """One-shot diagnostic: dumps the full pre_single_mode/index response (and friend/index)
    to uma_runtime/bot_logs/ so we can inspect the schema for borrowable umas. Remove after use."""
    global active_client
    if not active_client:
        return {"success": False, "detail": "Not logged in — log in via the normal web UI first."}
    import json as _json
    import time as _time
    out_dir = Path(__file__).resolve().parent / "uma_runtime" / "bot_logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = _time.strftime("%Y%m%d_%H%M%S")
    written = []
    errors = []
    try:
        psm = active_client.pre_single_mode([])
        psm_data = (psm or {}).get("data") or {}
        psm_path = out_dir / f"pre_single_mode_DUMP_{stamp}.json"
        psm_path.write_text(_json.dumps({
            "endpoint": "pre_single_mode/index",
            "top_level_keys": sorted(list(psm_data.keys())),
            "data": psm_data,
        }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        written.append(str(psm_path))
    except Exception as e:
        errors.append(f"pre_single_mode: {e}")
    try:
        fi = active_client.call("friend/index", {})
        fi_data = (fi or {}).get("data") or {}
        fi_path = out_dir / f"friend_index_DUMP_{stamp}.json"
        fi_path.write_text(_json.dumps({
            "endpoint": "friend/index",
            "top_level_keys": sorted(list(fi_data.keys())),
            "data": fi_data,
        }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        written.append(str(fi_path))
    except Exception as e:
        errors.append(f"friend/index: {e}")
    try:
        li = active_client.call("load/index", {})
        li_data = (li or {}).get("data") or {}
        li_path = out_dir / f"load_index_DUMP_{stamp}.json"
        li_path.write_text(_json.dumps({
            "endpoint": "load/index",
            "top_level_keys": sorted(list(li_data.keys())),
            "data": li_data,
        }, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        written.append(str(li_path))
    except Exception as e:
        errors.append(f"load/index: {e}")
    return {"success": bool(written), "written": written, "errors": errors}


def latest_api_payload_trace_file():
    trace_dir = dev_runtime_dir() / "trace_logs" / "api_payloads"
    if not trace_dir.exists():
        return None
    files = api_payload_trace_files(trace_dir)
    return files[0] if files else None


def api_payload_trace_files(trace_dir=None):
    trace_dir = trace_dir or (dev_runtime_dir() / "trace_logs" / "api_payloads")
    if not trace_dir.exists():
        return []
    return sorted(
        [path for path in trace_dir.glob("*_payloads.jsonl") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def recent_api_trace_entries(endpoint="", req_id="", limit=20, recent_files=3):
    endpoint = str(endpoint or "").strip()
    req_id = str(req_id or "").strip()
    try:
        limit = max(1, min(int(limit or 20), 200))
    except (TypeError, ValueError):
        limit = 20
    try:
        recent_files = max(1, min(int(recent_files or 3), 20))
    except (TypeError, ValueError):
        recent_files = 3
    entries = []
    scanned = []
    for path in api_payload_trace_files()[:recent_files]:
        scanned.append(str(path))
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if endpoint and str(row.get("endpoint") or "") != endpoint:
                continue
            if req_id and str(row.get("req_id") or "") != req_id:
                continue
            row["_trace_file"] = path.name
            entries.append(row)
            if len(entries) >= limit:
                break
        if len(entries) >= limit:
            break
    entries.reverse()
    return {"files": scanned, "entries": entries}


def _api_discovery_status_payload():
    active = active_api_discovery_session.status() if active_api_discovery_session else None
    return {
        "success": True,
        "active": bool(active_api_discovery_session),
        "session": active,
        "captures": list_capture_summaries(dev_runtime_dir())[:20],
    }


def _clear_api_discovery_hook():
    global active_api_discovery_session
    if active_client is not None:
        try:
            active_client.on_api_log = None
        except Exception:
            pass
    active_api_discovery_session = None


def _install_api_discovery_session(session):
    global active_api_discovery_session
    active_api_discovery_session = session
    if active_client is not None:
        active_client.on_api_log = session.on_api_log


SAFE_API_DISCOVERY_PROBES = {
    "load/index",
    "pre_single_mode/index",
    "friend/index",
    "single_mode_free/load",
}


def _api_discovery_probe_endpoint(endpoint):
    endpoint = str(endpoint or "").strip()
    if endpoint == "load/index":
        return game_api_call_with_session_recovery("load/index", {"adid": ""})
    if endpoint == "pre_single_mode/index":
        return active_client.pre_single_mode([])
    if endpoint == "friend/index":
        return active_client.friend_index()
    if endpoint == "single_mode_free/load":
        return active_client.load_career()
    raise ValueError(f"Unsupported discovery probe endpoint: {endpoint}")


@app.post("/api/api_discovery/start")
async def api_discovery_start(req: ApiDiscoveryCaptureRequest):
    global active_api_discovery_session
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if active_api_discovery_session:
        return {
            "success": False,
            "detail": "API discovery capture is already active. Stop it before starting another.",
            "status": _api_discovery_status_payload(),
        }
    label = req.label or f"capture_{int(time.time())}"
    session = ApiDiscoverySession(
        dev_runtime_dir(),
        label,
        note=req.note,
        endpoints=[str(ep).strip() for ep in (req.endpoints or []) if str(ep).strip()],
    )
    _install_api_discovery_session(session)
    return {"success": True, "session": session.status()}


@app.post("/api/api_discovery/stop")
async def api_discovery_stop():
    global active_api_discovery_session
    if not active_api_discovery_session:
        return {"success": False, "detail": "No API discovery capture is active"}
    session = active_api_discovery_session
    try:
        result = session.stop()
        return {"success": True, **result}
    finally:
        _clear_api_discovery_hook()


@app.get("/api/api_discovery/status")
async def api_discovery_status():
    return _api_discovery_status_payload()


@app.get("/api/api_discovery/captures")
async def api_discovery_captures():
    return {"success": True, "captures": list_capture_summaries(dev_runtime_dir())}


@app.get("/api/api_discovery/captures/{label}")
async def api_discovery_capture(label: str):
    entries = load_capture_entries(dev_runtime_dir(), label)
    if not entries:
        return {"success": False, "detail": f"No capture entries found for {label}"}
    contract = write_contract(dev_runtime_dir(), label, entries)
    return {
        "success": True,
        "label": label,
        "entry_count": len(entries),
        "entries": entries[-200:],
        "contract": contract,
    }


@app.get("/api/api_discovery/diff")
async def api_discovery_diff(left: str, right: str, endpoint: str = "", direction: str = "REQ"):
    result = compare_captures(
        dev_runtime_dir(),
        left,
        right,
        endpoint=str(endpoint or "").strip(),
        direction=str(direction or "REQ").strip() or "REQ",
    )
    return {"success": True, **result}


@app.post("/api/api_discovery/probe")
async def api_discovery_probe(req: ApiDiscoveryProbeRequest):
    global active_api_discovery_session
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if runner_is_active():
        return {"success": False, "detail": "Stop the career runner before probing API contracts"}

    requested = [str(ep).strip() for ep in (req.endpoints or []) if str(ep).strip()]
    endpoints = requested or ["load/index", "pre_single_mode/index", "friend/index"]
    unsupported = [ep for ep in endpoints if ep not in SAFE_API_DISCOVERY_PROBES]
    if unsupported:
        return {
            "success": False,
            "detail": "Unsupported probe endpoint(s); use a labeled capture for mutating endpoints.",
            "unsupported": unsupported,
            "allowed": sorted(SAFE_API_DISCOVERY_PROBES),
        }

    started_here = False
    if not active_api_discovery_session:
        session = ApiDiscoverySession(
            dev_runtime_dir(),
            req.label or f"probe_{int(time.time())}",
            note=req.note or "safe endpoint probe",
            endpoints=endpoints,
        )
        _install_api_discovery_session(session)
        started_here = True

    operations = []
    try:
        for endpoint in endpoints:
            try:
                result = _api_discovery_probe_endpoint(endpoint)
                data = (result or {}).get("data") if isinstance(result, dict) else {}
                operations.append({
                    "endpoint": endpoint,
                    "success": True,
                    "data_keys": sorted(list((data or {}).keys()))[:80] if isinstance(data, dict) else [],
                })
            except Exception as exc:
                operations.append({"endpoint": endpoint, "success": False, "detail": str(exc)})
    finally:
        if started_here and active_api_discovery_session:
            session = active_api_discovery_session
            stopped = session.stop()
            _clear_api_discovery_hook()
        else:
            stopped = None

    return {
        "success": True,
        "operations": operations,
        "capture": stopped,
        "status": _api_discovery_status_payload(),
    }

def profile_dataset_runtime_dir(instance_name=""):
    name = slugify(instance_name or "")
    if name:
        local_instance = base_dir / "uma_runtime" / "instances" / name
        if local_instance.exists():
            return local_instance
        return runtime_output_root(base_dir) / "instances" / name
    return dev_runtime_dir()


@app.post("/api/profile_dataset/ingest_traces")
async def profile_dataset_ingest_traces(req: ProfileDatasetIngestRequest):
    try:
        result = ingest_trace_dataset(
            base_dir,
            profile_dataset_runtime_dir(req.instance_name),
            recent_files=req.recent_files,
            limit=req.limit,
            include_self=req.include_self,
        )
        return {"success": True, **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"profile dataset ingest failed: {exc}")


@app.post("/api/profile_dataset/probe")
async def profile_dataset_probe(req: ProfileDatasetProbeRequest):
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    if career_runner.snapshot().get("running") or loop_snapshot().get("active"):
        return {"success": False, "detail": "Stop the career runner before probing public profile data"}

    operations = []
    errors = []
    try:
        if req.include_pre_single_mode:
            try:
                exclude = [int(value) for value in (req.exclude_viewer_ids or []) if int(value or 0) > 0]
                result = active_client.pre_single_mode(exclude)
                data = (result or {}).get("data") or {}
                operations.append({
                    "endpoint": "pre_single_mode/index",
                    "ok": True,
                    "summary_user_info_count": len(((data.get("friend_support_card_data") or {}).get("summary_user_info_array") or [])),
                    "borrow_uma_count": len(((data.get("succession_trained_chara_data") or {}).get("succession_trained_chara_array") or [])),
                })
            except Exception as exc:
                errors.append({"endpoint": "pre_single_mode/index", "error": str(exc)})

        if req.include_friend_index:
            try:
                result = active_client.friend_index()
                data = (result or {}).get("data") or {}
                operations.append({
                    "endpoint": "friend/index",
                    "ok": True,
                    "friend_count": len(data.get("friend_list") or []),
                    "summary_user_info_count": len(((data.get("friend_support_card_data") or {}).get("summary_user_info_array") or [])),
                })
            except Exception as exc:
                errors.append({"endpoint": "friend/index", "error": str(exc)})

        viewer_ids = []
        for value in req.viewer_ids or []:
            vid = safe_int(value)
            if vid > 0 and vid not in viewer_ids:
                viewer_ids.append(vid)
            if len(viewer_ids) >= max(1, min(safe_int(req.max_viewer_ids, 5), 20)):
                break
        for viewer_id in viewer_ids:
            try:
                result = active_client.friend_search(viewer_id)
                data = (result or {}).get("data") or {}
                profile = normalize_friend_search_profile(data, viewer_id)
                operations.append({
                    "endpoint": "friend/search",
                    "viewer_id": viewer_id,
                    "ok": True,
                    "profile": profile,
                    "summary_user_info_count": len(((data.get("friend_support_card_data") or {}).get("summary_user_info_array") or [])),
                })
            except Exception as exc:
                errors.append({"endpoint": "friend/search", "viewer_id": viewer_id, "error": str(exc)})

        ingest = ingest_trace_dataset(
            base_dir,
            dev_runtime_dir(),
            recent_files=3,
            limit=1000,
            include_self=False,
        )
        summary = summarize_profile_dataset(
            base_dir,
            dev_runtime_dir(),
            stat="",
            min_value=0,
            limit=20,
        )
        return {
            "success": True,
            "operations": operations,
            "errors": errors,
            "ingest": ingest,
            "summary": summary,
        }
    except Exception as exc:
        return {"success": False, "detail": str(exc), "operations": operations, "errors": errors}


@app.get("/api/profile_dataset/summary")
async def profile_dataset_summary(stat: str = "", min_value: int = 0, limit: int = 20, instance_name: str = ""):
    try:
        result = summarize_profile_dataset(
            base_dir,
            profile_dataset_runtime_dir(instance_name),
            stat=stat,
            min_value=min_value,
            limit=limit,
        )
        return {"success": True, **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"profile dataset summary failed: {exc}")


@app.get("/api/profile_dataset/records")
async def profile_dataset_records(stat: str = "", min_value: int = 0, limit: int = 100, instance_name: str = ""):
    try:
        result = list_profile_dataset_records(
            profile_dataset_runtime_dir(instance_name),
            stat=stat,
            min_value=min_value,
            limit=limit,
        )
        return {"success": True, **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"profile dataset records failed: {exc}")


@app.get("/api/team_trials/data")
async def team_trials_data(
    query: str = "",
    limit: int = 100,
    refresh: bool = True,
    instance_name: str = "",
):
    try:
        result = load_team_trials_dataset(
            base_dir,
            profile_dataset_runtime_dir(instance_name or sweepy_instance_name()),
            refresh=refresh,
            query=query,
            limit=limit,
        )
        return {"success": True, **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"team trials dataset load failed: {exc}")


TEAM_TRIALS_LIVE_DISTANCES = ("sprint", "mile", "medium", "long", "dirt")
TEAM_TRIALS_DISTANCE_TYPE_MAP = {
    1: "sprint",
    2: "mile",
    3: "medium",
    4: "long",
    5: "dirt",
}
TEAM_TRIALS_STYLE_MAP = {
    1: "Front",
    2: "Pace",
    3: "Late",
    4: "End",
}


def _team_trials_support_bonus_catalog():
    path = base_dir / "data" / "support_card_bonuses.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _unwrap_game_data(result):
    data = result.get("data") if isinstance(result, dict) else {}
    if isinstance(data, dict) and isinstance(data.get("data"), dict):
        return data.get("data") or {}
    return data if isinstance(data, dict) else {}


def _shape_summary(obj, max_depth=2):
    if max_depth < 0:
        return type(obj).__name__
    if isinstance(obj, dict):
        summary = {}
        for key, value in list(obj.items())[:20]:
            if isinstance(value, list):
                summary[key] = f"list[{len(value)}]"
            elif isinstance(value, dict):
                summary[key] = _shape_summary(value, max_depth - 1)
            else:
                summary[key] = type(value).__name__
        return summary
    if isinstance(obj, list):
        return f"list[{len(obj)}]"
    return type(obj).__name__


def _team_trials_leaderboard_candidates(limit=100):
    limit = max(1, min(safe_int(limit, 100), 100))
    candidates = [
        ("team_stadium/ranking", {"ranking_type": ranking_type, "page": 1, "limit": limit})
        # ranking_type=2 is the in-game Class 6 top leaderboard. ranking_type=3
        # is a smaller nearby/current-account slice and should not drive "top 100".
        for ranking_type in (2, 3, 1, 6, 5, 4)
    ]
    candidates.extend([
        ("team_stadium/ranking", {"team_class": 6, "page": 1, "limit": limit}),
        ("team_stadium/ranking", {"team_stadium_class": 6, "page": 1, "limit": limit}),
        ("team_stadium/ranking_info", {"page": 1, "limit": limit}),
        ("team_stadium/ranking_list", {"page": 1, "limit": limit}),
        ("team_stadium/top", {"page": 1, "limit": limit}),
        ("team_stadium/index", {}),
        ("team_stadium/team_ranking", {"page": 1, "limit": limit}),
        ("team_race/ranking", {"page": 1, "limit": limit}),
        ("team_race/ranking_list", {"page": 1, "limit": limit}),
    ])
    return candidates


def _team_trials_profile_candidates(viewer_id, *, team_class=0, rank=0, ranking_type=0, term_id=0):
    viewer_id = safe_int(viewer_id)
    team_class = safe_int(team_class)
    rank = safe_int(rank)
    ranking_type = safe_int(ranking_type)
    term_id = safe_int(term_id)
    context = {key: value for key, value in {
        "viewer_id": viewer_id,
        "team_class": team_class,
        "rank": rank,
        "ranking_type": ranking_type,
        "term_id": term_id,
    }.items() if value}
    candidates = []
    seen = set()

    def add(endpoint, payload):
        payload = {key: value for key, value in (payload or {}).items() if value}
        key = (endpoint, tuple(sorted(payload.items())))
        if payload and key not in seen:
            seen.add(key)
            candidates.append((endpoint, payload))

    # This is the real client route for opening another trainer's Team
    # Stadium lineup. Metadata exposes show_trainer_id/team_stadium_id on the
    # request, while older client strings sometimes appear as action/controller.
    team_data_payloads = [
        {"show_trainer_id": viewer_id},
        {"friend_viewer_id": viewer_id},
        {"target_viewer_id": viewer_id},
        {"trainer_id": viewer_id},
        {**context, "show_trainer_id": viewer_id},
        {**context, "friend_viewer_id": viewer_id},
        {**context, "target_viewer_id": viewer_id},
        {**context, "trainer_id": viewer_id},
    ]
    for stadium_id in range(1, 6):
        team_data_payloads.extend([
            {"show_trainer_id": viewer_id, "team_stadium_id": stadium_id},
            {"friend_viewer_id": viewer_id, "team_stadium_id": stadium_id},
            {"target_viewer_id": viewer_id, "team_stadium_id": stadium_id},
            {"trainer_id": viewer_id, "team_stadium_id": stadium_id},
        ])
    for payload in (
        {"target_viewer_id": viewer_id},
        {"friend_viewer_id": viewer_id},
        {"show_trainer_id": viewer_id},
        {"trainer_id": viewer_id},
        context,
        {**context, "target_viewer_id": viewer_id},
        {**context, "friend_viewer_id": viewer_id},
        {**context, "show_trainer_id": viewer_id},
        {**context, "trainer_id": viewer_id},
    ):
        add("team_stadium/user_detail", payload)
    for endpoint in ("friend/get_team_stadium_team_data", "get_team_stadium_team_data/friend"):
        for payload in team_data_payloads:
            add(endpoint, payload)
    for payload in (
        {"target_viewer_id": viewer_id},
        {"friend_viewer_id": viewer_id},
        {"show_trainer_id": viewer_id},
        {"trainer_id": viewer_id},
        context,
        {**context, "target_viewer_id": viewer_id},
        {**context, "friend_viewer_id": viewer_id},
        {**context, "show_trainer_id": viewer_id},
        {**context, "trainer_id": viewer_id},
    ):
        add("team_stadium/user_detail", payload)

    base_variants = [
        {"viewer_id": viewer_id},
        {"target_viewer_id": viewer_id},
        {"trainer_id": viewer_id},
        {"opponent_viewer_id": viewer_id},
        context,
        {**context, "target_viewer_id": viewer_id},
        {**context, "opponent_viewer_id": viewer_id},
    ]
    endpoints = [
        "team_stadium/profile",
        "team_stadium/team_profile",
        "team_stadium/detail",
        "team_stadium/ranking_detail",
        "team_stadium/team_detail",
        "team_stadium/opponent",
        "team_stadium/opponent_info",
        "team_stadium/user_info",
        "team_stadium/member",
        "team_race/profile",
        "user/profile",
    ]
    for endpoint in endpoints:
        for payload in base_variants:
            add(endpoint, payload)
    return candidates


def _team_trials_score(row):
    for key in ("best_point", "team_rank_rating", "team_evaluation_point", "evaluation_point", "score", "rank_score", "rating"):
        value = safe_int(row.get(key))
        if value:
            return value
    return 0


def _team_trials_class(row):
    for key in ("team_class", "class", "rank_class", "team_stadium_class"):
        value = safe_int(row.get(key))
        if value:
            return value
    return 0


def _find_leaderboard_rows(payload):
    rows = []
    seen = set()

    def walk(obj):
        if isinstance(obj, dict):
            viewer_id = safe_int(
                obj.get("viewer_id")
                or obj.get("trainer_id")
                or obj.get("owner_viewer_id")
                or obj.get("user_id")
            )
            name = str(obj.get("name") or obj.get("trainer_name") or obj.get("owner_trainer_name") or "").strip()
            score = _team_trials_score(obj)
            team_class = _team_trials_class(obj)
            ranking = safe_int(obj.get("ranking") or obj.get("rank") or obj.get("order") or obj.get("rank_order"))
            if viewer_id and name and (score or team_class or ranking):
                key = (viewer_id, name.lower(), score, team_class)
                if key not in seen:
                    seen.add(key)
                    rows.append(obj)
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for value in obj:
                walk(value)

    walk(payload)
    return rows


def _team_trials_leaderboard_rows(payload):
    if not isinstance(payload, dict):
        return []
    ranking_rows = payload.get("ranking_array") if isinstance(payload.get("ranking_array"), list) else []
    summary_rows = payload.get("summary_user_info_array") if isinstance(payload.get("summary_user_info_array"), list) else []
    if ranking_rows and summary_rows:
        summary_by_viewer = {
            safe_int(row.get("viewer_id")): row
            for row in summary_rows
            if isinstance(row, dict) and safe_int(row.get("viewer_id"))
        }
        merged = []
        for ranking in ranking_rows:
            if not isinstance(ranking, dict):
                continue
            viewer_id = safe_int(ranking.get("viewer_id"))
            summary = summary_by_viewer.get(viewer_id, {})
            row = dict(summary)
            row.update(ranking)
            if summary.get("user_trained_chara") and not row.get("leader_user_trained_chara"):
                row["leader_user_trained_chara"] = summary.get("user_trained_chara")
            row["team_evaluation_point"] = safe_int(summary.get("team_evaluation_point"))
            row["team_rank_rating"] = safe_int(ranking.get("best_point"))
            row["ranking"] = safe_int(ranking.get("rank"))
            row["name"] = summary.get("name") or row.get("name")
            merged.append(row)
        return merged
    return _find_leaderboard_rows(payload)


def _normalize_live_leaderboard_row(row, index, endpoint):
    viewer_id = safe_int(row.get("viewer_id") or row.get("trainer_id") or row.get("owner_viewer_id") or row.get("user_id"))
    name = str(row.get("name") or row.get("trainer_name") or row.get("owner_trainer_name") or f"Trainer {viewer_id}").strip()
    ranking = safe_int(row.get("ranking") or row.get("rank_order") or row.get("order")) or index
    score = safe_int(row.get("team_rank_rating") or row.get("best_point")) or _team_trials_score(row)
    team_evaluation_point = safe_int(row.get("team_evaluation_point"))
    team_class = _team_trials_class(row)
    leader = row.get("leader_user_trained_chara") if isinstance(row.get("leader_user_trained_chara"), dict) else {}
    leader_card_id = safe_int(
        leader.get("card_id")
        or leader.get("chara_card_id")
        or row.get("leader_card_id")
        or row.get("leader_chara_card_id")
        or row.get("leader_chara_dress_id")
    )
    return {
        "key": f"live:{viewer_id}:{ranking}:{name.lower()}",
        "source_kind": "in_game_leaderboard",
        "source_endpoint": endpoint,
        "source_payload": dict(row.get("_source_payload") or {}),
        "display_rank": ranking,
        "trainer_name": name,
        "trainer_id": viewer_id,
        "trainer_id_label": str(viewer_id) if viewer_id else "ID unavailable",
        "team_class": team_class,
        "class_label": str(team_class) if team_class else "--",
        "term_id": safe_int(row.get("term_id")),
        "team_rank_rating": score,
        "team_evaluation_point": team_evaluation_point,
        "score_label": f"{score:,} pts" if score else "Score unavailable",
        "leader_card_id": leader_card_id,
        "leader_name": str(row.get("leader_name") or ""),
        "member_count": 0,
        "members": [],
        "members_by_distance": {distance: [] for distance in TEAM_TRIALS_LIVE_DISTANCES},
        "profile_loaded": False,
        "profile_error": "",
        "raw_available_fields": sorted(str(key) for key in row.keys())[:80],
    }


def _team_trials_factor_summary(chara, maps):
    factor_map = (maps or {}).get("factor") or {}
    rows = []
    seen = set()
    raw_values = []
    for key in ("factor_info_array", "factor_info_list", "factors"):
        values = chara.get(key) if isinstance(chara, dict) else None
        if isinstance(values, list):
            raw_values.extend(values)
    for key in ("factor_id_array", "factor_id_list", "factor_ids"):
        values = chara.get(key) if isinstance(chara, dict) else None
        if isinstance(values, list):
            raw_values.extend(values)
    for raw in raw_values:
        if isinstance(raw, dict):
            factor_id = safe_int(raw.get("factor_id") or raw.get("id"))
            level = safe_int(raw.get("level"))
        else:
            factor_id = safe_int(raw)
            level = 0
        if not factor_id or factor_id in seen:
            continue
        seen.add(factor_id)
        info = factor_map.get(str(factor_id)) or {}
        if not isinstance(info, dict):
            info = {}
        stars = safe_int(info.get("stars") or level)
        if not stars:
            suffix = abs(factor_id) % 10
            stars = suffix if 1 <= suffix <= 3 else 0
        rows.append({
            "factor_id": factor_id,
            "name": str(info.get("name") or f"Factor {factor_id}"),
            "category": str(info.get("category") or ""),
            "level": level,
            "stars": stars,
        })
    return rows


def _team_trials_parent_summary(parent, maps):
    if not isinstance(parent, dict):
        return None
    chara_map = (maps or {}).get("chara") or {}
    card_id = safe_int(parent.get("card_id") or parent.get("chara_card_id"))
    if not card_id:
        return None
    rank = safe_int(parent.get("rank"))
    rank_score = safe_int(parent.get("rank_score") or parent.get("score") or parent.get("rating"))
    return {
        "trained_chara_id": safe_int(parent.get("trained_chara_id") or parent.get("single_mode_chara_id")),
        "single_mode_chara_id": safe_int(parent.get("single_mode_chara_id")),
        "card_id": card_id,
        "name": str(chara_map.get(str(card_id)) or f"Chara {card_id}"),
        "rank": rank,
        "rank_label": rank_for_rating_score(rank_score) if rank_score else RANK_LABELS.get(rank, str(rank) if rank else ""),
        "rank_score": rank_score,
        "rarity": safe_int(parent.get("rarity")),
        "talent_level": safe_int(parent.get("talent_level")),
        "factors": _team_trials_factor_summary(parent, maps),
    }


def _team_trials_owner_from_payload(data, viewer_id, fallback_name=""):
    data = data if isinstance(data, dict) else {}
    owner = {
        "viewer_id": safe_int(viewer_id),
        "trainer_name": str(fallback_name or ""),
        "team_evaluation_point": safe_int(data.get("team_evaluation_point")),
    }
    for key in (
        "user_info",
        "trainer_info",
        "summary_user_info",
        "profile",
        "user_data",
        "trainer_data",
    ):
        value = data.get(key)
        if isinstance(value, dict):
            owner["viewer_id"] = safe_int(value.get("viewer_id") or value.get("trainer_id") or owner.get("viewer_id"))
            owner["trainer_name"] = str(value.get("name") or value.get("trainer_name") or owner.get("trainer_name") or "")
            owner["team_evaluation_point"] = safe_int(
                value.get("team_evaluation_point")
                or value.get("team_rank_rating")
                or owner.get("team_evaluation_point")
            )
            break
    return owner


def _team_trials_chara_list(data):
    if not isinstance(data, dict):
        return []
    for key in (
        "trained_chara_array",
        "trained_chara_list",
        "user_trained_chara_array",
        "user_trained_chara_list",
        "team_trained_chara_array",
        "team_trained_chara_list",
    ):
        value = data.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    return []


def _team_trials_user_detail_records(data, endpoint, viewer_id, maps, owner=None):
    if not isinstance(data, dict):
        return []
    team_data = data.get("team_data_array") or data.get("team_data_list") or data.get("team_member_array") or []
    if not isinstance(team_data, list):
        return []
    chara_rows = _team_trials_chara_list(data)
    full_by_trained_id = {}
    for chara in chara_rows:
        trained_id = safe_int(chara.get("trained_chara_id") or chara.get("single_mode_chara_id"))
        if trained_id:
            full_by_trained_id[trained_id] = chara
    if not full_by_trained_id:
        return []

    records = []
    owner = owner or _team_trials_owner_from_payload(data, viewer_id)
    sorted_slots = sorted(
        [slot for slot in team_data if isinstance(slot, dict)],
        key=lambda slot: (
            safe_int(slot.get("distance_type"), 99),
            safe_int(slot.get("member_id"), 99),
            safe_int(slot.get("order"), 99),
        ),
    )
    for slot_index, slot in enumerate(sorted_slots):
        trained_id = safe_int(slot.get("trained_chara_id") or slot.get("single_mode_chara_id"))
        full_chara = full_by_trained_id.get(trained_id)
        if not full_chara:
            continue
        source = {
            "endpoint": endpoint,
            "viewer_id": safe_int(viewer_id),
            "path": "data.trained_chara_array",
            "kind": "team_stadium_user_detail",
        }
        record = normalize_trained_chara_record(
            full_chara,
            root_data=full_chara,
            owner=owner,
            source=source,
            maps=maps,
        )
        if not record:
            continue
        distance_type = safe_int(slot.get("distance_type"))
        member_id = safe_int(slot.get("member_id"))
        running_style = safe_int(slot.get("running_style") or slot.get("race_running_style"))
        record["_team_trials_distance_type"] = distance_type
        record["_team_trials_distance"] = TEAM_TRIALS_DISTANCE_TYPE_MAP.get(distance_type, "")
        record["_team_trials_member_id"] = member_id
        record["_team_trials_slot_index"] = slot_index
        record["_team_trials_running_style_id"] = running_style
        record["_team_trials_style"] = TEAM_TRIALS_STYLE_MAP.get(running_style, "")
        parents = []
        for key in (
            "succession_chara_array",
            "succession_chara_list",
            "succession_trained_chara_array",
            "succession_trained_chara_list",
        ):
            for parent in full_chara.get(key) or []:
                summary = _team_trials_parent_summary(parent, maps)
                if summary:
                    parents.append(summary)
        record["parents_detail"] = parents
        records.append(record)
    return records


def _live_member_from_record(record, index, support_bonus_catalog):
    distance = record.get("_team_trials_distance") or TEAM_TRIALS_LIVE_DISTANCES[min(index // 3, len(TEAM_TRIALS_LIVE_DISTANCES) - 1)]
    member_id = safe_int(record.get("_team_trials_member_id"))
    running_style = safe_int(record.get("_team_trials_running_style_id"))
    style = record.get("_team_trials_style") or ""
    supports = record.get("support_cards") or []
    deck_rb = deck_race_bonus_summary(supports, support_bonus_catalog)
    races = record.get("races") if isinstance(record.get("races"), dict) else {"history": []}
    wins = sum(1 for race in races.get("history") or [] if safe_int(race.get("result_rank")) == 1)
    rank_score = safe_int(record.get("rank_score"))
    stats = record.get("stats") or {}
    return {
        "key": f"live:{record.get('viewer_id') or 0}:{record.get('trained_chara_id') or 0}:{index}",
        "source_file": record.get("source", {}).get("endpoint") or "team_stadium/profile",
        "source_kind": "in_game_profile",
        "round": (index // 3) + 1,
        "distance": distance,
        "distance_type": safe_int(record.get("_team_trials_distance_type")),
        "team_member_id": member_id,
        "is_ace": member_id == 1 if member_id else index % 3 == 0,
        "trainer_name": record.get("trainer_name") or "",
        "trainer_id": safe_int(record.get("viewer_id")),
        "trained_chara_id": safe_int(record.get("trained_chara_id")),
        "single_mode_chara_id": safe_int(record.get("single_mode_chara_id")),
        "card_id": safe_int(record.get("card_id")),
        "name": record.get("chara_name") or f"Chara {record.get('card_id') or ''}",
        "rank": safe_int(record.get("rank")),
        "rank_label": rank_for_rating_score(rank_score) if rank_score else RANK_LABELS.get(safe_int(record.get("rank")), str(record.get("rank") or "")),
        "rank_score": rank_score,
        "rarity": safe_int(record.get("rarity")),
        "talent_level": safe_int(record.get("talent_level")),
        "stats": stats,
        "stat_sum": sum(safe_int(stats.get(key)) for key in ("speed", "stamina", "power", "guts", "wit")),
        "aptitudes": record.get("aptitudes") or {},
        "running_style": running_style,
        "style": style,
        "skills": record.get("skills") or [],
        "support_cards": supports,
        "parents": record.get("parents_detail") or [],
        "races": races,
        "career_wins": wins,
        "win_saddle_ids": (races.get("win_saddle_ids") or []),
        **deck_rb,
        "has_detail_record": True,
        "detail_available": {
            "support_cards": bool(supports),
            "parents": bool(record.get("parents_detail")),
            "career_races": bool(races.get("history")),
        },
    }


def _finish_live_profile_team(summary, records, endpoint):
    support_bonus_catalog = _team_trials_support_bonus_catalog()
    members = [_live_member_from_record(record, idx, support_bonus_catalog) for idx, record in enumerate(records[:15])]
    groups = {distance: [] for distance in TEAM_TRIALS_LIVE_DISTANCES}
    for member in members:
        groups.setdefault(member.get("distance") or "unknown", []).append(member)
    team = dict(summary or {})
    team.update({
        "source_kind": "in_game_profile",
        "source_endpoint": endpoint,
        "profile_loaded": True,
        "profile_error": "",
        "members": members,
        "members_by_distance": groups,
        "member_count": len(members),
        "max_rank": max([safe_int(row.get("rank")) for row in members] or [0]),
        "best_stat_sum": max([safe_int(row.get("stat_sum")) for row in members] or [0]),
        "total_career_wins": sum(safe_int(row.get("career_wins")) for row in members),
    })
    team["max_rank_label"] = RANK_LABELS.get(team["max_rank"], str(team["max_rank"]) if team["max_rank"] else "")
    leader = members[0] if members else {}
    team["leader"] = leader
    team["leader_card_id"] = safe_int(team.get("leader_card_id") or leader.get("card_id"))
    team["leader_name"] = team.get("leader_name") or leader.get("name") or ""
    return team


def _live_probe_blocked():
    if not active_client:
        return "Not logged in"
    return ""


@app.get("/api/team_trials/live_probe")
async def team_trials_live_probe(limit: int = 100):
    blocked = _live_probe_blocked()
    if blocked:
        return {"success": False, "detail": blocked, "operations": []}
    operations = []
    for endpoint, payload in _team_trials_leaderboard_candidates(limit):
        try:
            result = game_api_call_with_session_recovery(
                endpoint,
                payload,
                retry_208=0,
                retry_205=0,
                retry_http_403=0,
                retry_394=0,
                quiet_result_codes={102, 201, 205, 391, 394, 500, 1801, 1802, 2502},
            )
            data = _unwrap_game_data(result or {})
            rows = _team_trials_leaderboard_rows(data)
            operations.append({
                "endpoint": endpoint,
                "payload": payload,
                "ok": True,
                "candidate_players": len(rows),
                "shape": _shape_summary(data),
            })
        except Exception as exc:
            operations.append({
                "endpoint": endpoint,
                "payload": payload,
                "ok": False,
                "error": str(exc)[:500],
                "result_code": getattr(exc, "result_code", None),
                "http_status": getattr(exc, "http_status", None),
            })
    found = [row for row in operations if row.get("ok") and row.get("candidate_players")]
    return {"success": bool(found), "operations": operations, "detail": "" if found else "No readable Team Trials leaderboard endpoint found from current candidates"}


@app.get("/api/team_trials/live")
async def team_trials_live(limit: int = 100):
    blocked = _live_probe_blocked()
    if blocked:
        return {"success": False, "detail": blocked, "teams": [], "operations": []}
    operations = []
    for endpoint, payload in _team_trials_leaderboard_candidates(limit):
        try:
            result = game_api_call_with_session_recovery(
                endpoint,
                payload,
                retry_208=0,
                retry_205=0,
                retry_http_403=0,
                retry_394=0,
                quiet_result_codes={102, 201, 205, 391, 394, 500, 1801, 1802, 2502},
            )
            data = _unwrap_game_data(result or {})
            rows = _team_trials_leaderboard_rows(data)
            operations.append({"endpoint": endpoint, "payload": payload, "ok": True, "candidate_players": len(rows)})
            if rows:
                for row in rows:
                    if isinstance(row, dict):
                        row["_source_payload"] = payload
                teams = [_normalize_live_leaderboard_row(row, idx, endpoint) for idx, row in enumerate(rows[: max(1, min(safe_int(limit, 100), 100))], start=1)]
                return {
                    "success": True,
                    "schema": "sweepy_team_trials_live_v1",
                    "source_kind": "in_game_leaderboard",
                    "source_endpoint": endpoint,
                    "source_payload": payload,
                    "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "team_count": len(teams),
                    "player_count": len(teams),
                    "filtered_count": len(teams),
                    "teams": teams,
                    "operations": operations,
                }
        except Exception as exc:
            operations.append({
                "endpoint": endpoint,
                "payload": payload,
                "ok": False,
                "error": str(exc)[:500],
                "result_code": getattr(exc, "result_code", None),
                "http_status": getattr(exc, "http_status", None),
            })
    return {
        "success": False,
        "detail": "No readable Team Trials leaderboard endpoint found from current candidates",
        "teams": [],
        "operations": operations,
    }


@app.get("/api/team_trials/live_profile")
async def team_trials_live_profile(
    viewer_id: int,
    team_class: int = 0,
    rank: int = 0,
    ranking_type: int = 0,
    term_id: int = 0,
    team_rank_rating: int = 0,
    trainer_name: str = "",
):
    blocked = _live_probe_blocked()
    if blocked:
        return {"success": False, "detail": blocked}
    viewer_id = safe_int(viewer_id)
    if viewer_id <= 0:
        return {"success": False, "detail": "viewer_id is required"}
    maps = load_name_maps(base_dir)
    summary = {
        "key": f"live:{viewer_id}",
        "trainer_id": viewer_id,
        "trainer_id_label": str(viewer_id),
        "trainer_name": str(trainer_name or "").strip() or f"Trainer {viewer_id}",
        "display_rank": safe_int(rank),
        "team_class": safe_int(team_class),
        "team_rank_rating": safe_int(team_rank_rating),
        "class_label": str(team_class) if safe_int(team_class) else "--",
        "term_id": safe_int(term_id),
        "members_by_distance": {distance: [] for distance in TEAM_TRIALS_LIVE_DISTANCES},
    }
    attempts = []
    for endpoint, payload in _team_trials_profile_candidates(
        viewer_id,
        team_class=team_class,
        rank=rank,
        ranking_type=ranking_type,
        term_id=term_id,
    ):
        try:
            result = game_api_call_with_session_recovery(
                endpoint,
                payload,
                retry_208=0,
                retry_205=0,
                retry_http_403=0,
                retry_394=0,
                quiet_result_codes={102, 201, 205, 391, 394, 500, 1801, 1802, 2502},
            )
            data = _unwrap_game_data(result or {})
            owner = _team_trials_owner_from_payload(
                data,
                viewer_id,
                fallback_name=summary.get("trainer_name") or "",
            )
            records = _team_trials_user_detail_records(
                data,
                endpoint,
                viewer_id,
                maps,
                owner=owner,
            )
            parser = "team_stadium_user_detail"
            if not records:
                records = extract_profile_records_from_response(
                    endpoint,
                    data,
                    source={"endpoint": endpoint, "viewer_id": viewer_id, "kind": "team_trials_live_profile"},
                    include_self=True,
                    maps=maps,
                )
                parser = "generic_profile_walk"
            attempts.append({
                "endpoint": endpoint,
                "payload": payload,
                "ok": True,
                "records": len(records),
                "parser": parser,
                "shape": _shape_summary(data),
            })
            if records:
                owner = owner or records[0].get("owner") or {}
                summary["trainer_name"] = owner.get("trainer_name") or records[0].get("trainer_name") or summary["trainer_name"]
                summary["team_rank_rating"] = safe_int(owner.get("team_evaluation_point") or summary.get("team_rank_rating"))
                team = _finish_live_profile_team(summary, records, endpoint)
                observation_result = {}
                try:
                    observation_result = append_team_observations(
                        profile_dataset_runtime_dir(sweepy_instance_name()),
                        team,
                        source={"endpoint": endpoint, "payload": payload, "viewer_id": viewer_id},
                    )
                except Exception as obs_exc:
                    observation_result = {"error": str(obs_exc)[:300]}
                if safe_int((observation_result or {}).get("written_count")) > 0:
                    deck_advice_cache["key"] = None
                    deck_advice_cache["advice"] = None
                team["observation_learning"] = observation_result
                return {"success": True, "team": team, "attempts": attempts}
        except Exception as exc:
            attempts.append({
                "endpoint": endpoint,
                "payload": payload,
                "ok": False,
                "error": str(exc)[:500],
                "result_code": getattr(exc, "result_code", None),
                "http_status": getattr(exc, "http_status", None),
            })
    return {"success": False, "detail": "No readable Team Trials profile endpoint found for this viewer ID", "attempts": attempts}


@app.get("/api/team_trials/observations")
async def team_trials_observations(style: str = "", distance: str = "", limit: int = 100, instance_name: str = ""):
    runtime = profile_dataset_runtime_dir(instance_name or sweepy_instance_name())
    samples = load_observation_samples(
        runtime,
        recent=max(1, min(safe_int(limit, 100), 1000)),
        style=style,
        distance=distance,
    )
    fallback_runtime = None
    if not samples and not instance_name:
        fallback_runtime = dev_runtime_dir()
        samples = load_observation_samples(
            fallback_runtime,
            recent=max(1, min(safe_int(limit, 100), 1000)),
            style=style,
            distance=distance,
        )
    return {
        "success": True,
        "runtime_root": str(runtime),
        "fallback_runtime_root": str(fallback_runtime) if fallback_runtime else "",
        "samples": samples,
        "summary": summarize_observation_samples(samples),
    }


def friend_error_details(exc):
    request_payload = getattr(exc, "request_payload", None)
    response_body = getattr(exc, "response_body", None)
    details = {
        "type": type(exc).__name__,
        "message": str(exc),
        "endpoint": getattr(exc, "endpoint", ""),
        "result_code": getattr(exc, "result_code", None),
        "response_code": getattr(exc, "response_code", None),
        "http_status": getattr(exc, "http_status", None),
        "req_id": getattr(exc, "req_id", None),
        "request_payload": request_payload,
        "response_body": response_body,
        "response_text": getattr(exc, "response_text", None),
        "traceback": traceback.format_exc(),
    }
    if isinstance(request_payload, dict):
        details["variant_attempts"] = request_payload.get("variant_attempts") or []
        details["payload_variants"] = request_payload.get("payload_variants") or []
    else:
        details["variant_attempts"] = []
        details["payload_variants"] = []
    if not details["variant_attempts"] and isinstance(response_body, dict):
        details["variant_attempts"] = response_body.get("variant_attempts") or []
    return details


def write_friend_error_snapshot(category, requested_viewer_id, *, stage="", profile=None, search_result=None, follow_result=None, unfollow_result=None, error=None):
    category = slugify(category or "friend_error") or "friend_error"
    snapshot_root = dev_runtime_dir() / "error_snapshots" / category
    snapshot_root.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    micros = int((time.time() % 1) * 1_000_000)
    filename = f"{timestamp}_{micros:06d}_{category}_{int(requested_viewer_id or 0)}.json"
    target = snapshot_root / filename
    latest = snapshot_root / f"latest_{category}.json"

    details = friend_error_details(error) if error else {}
    endpoint = details.get("endpoint") or {
        "search": "friend/search",
        "follow": "friend/follow",
        "unfollow": "friend/un_follow",
    }.get(stage, "")
    req_id = details.get("req_id") or ""
    trace = recent_api_trace_entries(endpoint=endpoint, req_id=req_id, limit=20, recent_files=4)
    if not trace.get("entries") and endpoint:
        trace = recent_api_trace_entries(endpoint=endpoint, req_id="", limit=20, recent_files=4)

    quota = None
    try:
        following_count = len((active_dashboard_data or {}).get("friendsList", []))
        quota = compute_follow_quota(active_client, following_count) if active_client else None
    except Exception:
        quota = None

    payload = {
        "schema": "sweepy_friend_error_snapshot_v1",
        "category": category,
        "stage": stage,
        "written_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "server": {
            "pid": os.getpid(),
            "instance": sweepy_instance_name(),
            "host": sweepy_bind_host(),
            "port": sweepy_bind_port(),
            "version_token": SERVER_VERSION_TOKEN,
        },
        "request": {
            "requested_viewer_id": int(requested_viewer_id or 0),
        },
        "account_context": {
            "active_viewer_id": int(getattr(active_client, "viewer_id", 0) or 0) if active_client else 0,
            "friend_follow_quota": quota,
            "following_count": len((active_dashboard_data or {}).get("friendsList", [])),
            "friend_support_count": len((active_dashboard_data or {}).get("friends", [])),
            "borrow_count": len((active_dashboard_data or {}).get("borrow_umas", [])),
        },
        "search_result": search_result,
        "follow_result": follow_result,
        "unfollow_result": unfollow_result,
        "resolved_profile": profile,
        "error": details,
        "recent_api_trace": trace,
    }

    with open(target, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=json_cache_default)
    try:
        with open(latest, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2, default=json_cache_default)
    except Exception:
        pass
    return str(target)


@app.get("/api/debug/api_payloads")
async def debug_api_payloads(endpoint: str = "", limit: int = 120, recent_files: int = 1):
    """Return recent sanitized API payload trace rows, optionally filtered by endpoint."""
    files = api_payload_trace_files()
    if not files:
        return {
            "success": False,
            "detail": "No API payload trace file found. Ensure SWEEPY_TRACE_API is enabled and make at least one game API call.",
        }
    endpoint_filter = str(endpoint or "").strip()
    try:
        limit = max(1, min(int(limit or 120), 500))
    except (TypeError, ValueError):
        limit = 120
    try:
        recent_files = max(1, min(int(recent_files or 1), 25))
    except (TypeError, ValueError):
        recent_files = 1
    entries = []
    scanned_files = files[:recent_files]
    for path in scanned_files:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if endpoint_filter and endpoint_filter not in str(row.get("endpoint") or ""):
                continue
            row["_trace_file"] = path.name
            entries.append(row)
            if len(entries) >= limit:
                break
        if len(entries) >= limit:
            break
    entries.reverse()
    return {
        "success": True,
        "file": str(scanned_files[0]) if scanned_files else "",
        "files": [str(path) for path in scanned_files],
        "endpoint_filter": endpoint_filter,
        "recent_files": recent_files,
        "count": len(entries),
        "entries": entries,
    }


@app.get("/api/debug/api_payloads/latest")
async def debug_api_payloads_latest_file():
    """Download the latest sanitized API payload JSONL trace file."""
    path = latest_api_payload_trace_file()
    if not path:
        raise HTTPException(status_code=404, detail="No API payload trace file found")
    return FileResponse(str(path), media_type="application/x-ndjson", filename=path.name)


def horseact_config_payload():
    hook_name = os.environ.get("SWEEPY_HORSEACT_HOOK", "CommonResponse").strip()
    if not hook_name:
        hook_name = "CommonResponse"
    sensitive_fields = [
        "_ownerViewerId",
        "_viewerId",
        "owner_viewer_id",
        "viewer_id",
        "sid",
        "steam_session_ticket",
        "succession_history_array",
        "<SimData>k__BackingField",
        "<SimReader>k__BackingField",
    ]
    # HorseACT expects endpoint config rows with name/fields/sensitiveFields.
    # `name` is the IL2CPP parameter type to scan for, not a method name; its
    # log reports 55 methods taking CommonResponse in the current client.
    # Empty fields means "capture the hook payload"; fieldBlacklist still applies
    # in horseACTConfig.json and the server keeps the raw ingest local only.
    return [
        {
            "name": hook_name,
            "fields": [],
            "sensitiveFields": sensitive_fields,
        }
    ]


async def receive_horseact_ingest(endpoint_name: str, request: Request):
    raw = await request.body()
    try:
        payload = decode_horseact_body(raw, request.headers.get("content-encoding", ""))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Invalid HorseACT JSON payload: {exc}")
    raw_path = manual_career_recorder.append_raw_horseact(endpoint_name, payload)
    report = manual_career_recorder.process_horseact_payload(endpoint_name, payload)
    turns = report.get("turns") or []
    latest_turn = turns[-1] if turns else {}
    return {
        "success": True,
        "endpoint": endpoint_name,
        "raw_log": str(raw_path),
        "latest_report": str(manual_career_recorder.last_written_path or ""),
        "turn_count": len(turns),
        "final_turn": report.get("final_turn"),
        "latest_turn": latest_turn.get("turn"),
    }


@app.get("/api/horseact/config")
async def horseact_config_api():
    return horseact_config_payload()


@app.get("/config")
async def horseact_config_root():
    return horseact_config_payload()


@app.post("/api/horseact/ingest/{endpoint_name:path}")
async def horseact_ingest_api(endpoint_name: str, request: Request):
    return await receive_horseact_ingest(endpoint_name, request)


@app.post("/ingest/{endpoint_name:path}")
async def horseact_ingest_root(endpoint_name: str, request: Request):
    return await receive_horseact_ingest(endpoint_name, request)


@app.post("/api/manual-capture/replay-latest")
async def manual_capture_replay_latest():
    path = latest_api_payload_trace_file()
    if not path:
        raise HTTPException(status_code=404, detail="No API payload trace file found")
    output_dir = dev_runtime_dir() / "manual_career_logs"
    report = build_report_from_trace(path, DIR, output_dir=output_dir)
    written = output_dir / "latest_manual_career_log.json"
    turns = report.get("turns") or []
    return {
        "success": True,
        "trace": str(path),
        "latest_report": str(written),
        "turn_count": len(turns),
        "final_turn": report.get("final_turn"),
    }


@app.get("/api/manual-capture/latest")
async def manual_capture_latest():
    synced = sync_latest_manual_capture_to_runtime()
    path = (synced or _manual_capture_file_set(manual_career_recorder.output_dir)).get("log")
    if not path.exists():
        raise HTTPException(status_code=404, detail="No manual career capture exists yet")
    return FileResponse(str(path), media_type="application/json", filename=path.name)


@app.get("/api/manual-capture/compare-latest")
async def manual_capture_compare_latest():
    synced = sync_latest_manual_capture_to_runtime()
    source = latest_manual_capture_source() or {}
    runtime_set = _manual_capture_file_set(manual_career_recorder.output_dir)
    manual_log_path = (synced or runtime_set).get("log")
    manual_summary_path = source.get("summary") or (synced or runtime_set).get("summary")
    report = build_manual_vs_bot_report(
        DIR,
        dev_runtime_dir(),
        manual_log_path=manual_log_path,
        manual_summary_path=manual_summary_path,
    )
    if not isinstance(report, dict):
        raise HTTPException(status_code=404, detail="No comparable manual run exists yet")
    written = write_comparison_report(dev_runtime_dir(), report)
    return {
        "success": True,
        "comparison": report,
        "written": written,
        "manual_log_path": str(manual_log_path or ""),
        "manual_summary_path": str(manual_summary_path or ""),
    }


@app.post("/api/career/friends")
async def get_friend_list(req: FriendListRequest):
    global active_client, active_dashboard_data
    if not active_client:
        return {"success": False, "detail": "Not logged in"}

    if (
        not req.force_refresh
        and not req.exclude_viewer_ids
        and active_dashboard_data is not None
        and "friends" in active_dashboard_data
        and "borrow_umas" in active_dashboard_data
    ):
        return {
            "success": True,
            "friends": active_dashboard_data["friends"],
            "friends_list": active_dashboard_data.get("friendsList", []),
            "follow_quota": active_dashboard_data.get("friendFollowQuota") or compute_follow_quota(active_client, len(active_dashboard_data.get("friendsList", []))),
            "borrow_umas": active_dashboard_data.get("borrow_umas", []),
            "borrow_quota": active_dashboard_data.get("borrow_quota") or compute_borrow_quota(active_client),
            "exclude_viewer_ids": active_dashboard_data.get("friendExcludeIds", []),
            "source": "cache",
            "friend_index_source": "cache",
            "decks": active_dashboard_data.get("decks", []),
            "deckDebug": active_deck_debug,
        }

    try:
        return refresh_friend_library(req.exclude_viewer_ids, cache_reason="friends")
    except Exception as e:
        return {"success": False, "detail": str(e)}


@app.post("/api/friends/add")
async def add_friend_by_id(req: FriendIdRequest):
    global active_client
    if not active_client:
        return {"success": False, "detail": "Not logged in"}

    viewer_id = int(req.viewer_id or 0)
    if viewer_id <= 0:
        return {"success": False, "detail": "Trainer ID must be a positive number"}
    if viewer_id == int(getattr(active_client, "viewer_id", 0) or 0):
        return {"success": False, "detail": "You cannot follow your own trainer ID"}

    search_result = None
    follow_result = None
    profile = None
    already_followed = None
    try:
        search_result = client_method_with_session_recovery("friend_search", viewer_id)
        search_data = search_result.get("data") or {}
        profile = normalize_friend_search_profile(search_data, viewer_id)
        if not profile:
            return {"success": False, "detail": f"Trainer ID {viewer_id} was not found"}

        already_followed = int(profile.get("friend_state") or 0) > 0
        if not already_followed:
            follow_result = client_method_with_session_recovery("friend_follow", profile["viewer_id"])

        refreshed = refresh_friend_library([], cache_reason="friend_add")
        refreshed["profile"] = profile
        refreshed["already_followed"] = already_followed
        refreshed["search_variant_attempts"] = (search_result.get("_sweepy_variant_attempts") or []) if isinstance(search_result, dict) else []
        refreshed["detail"] = (
            f"Already following {profile.get('name') or profile['viewer_id']}; refreshed support and borrow lists."
            if already_followed
            else f"Followed {profile.get('name') or profile['viewer_id']} by trainer ID and refreshed support and borrow lists."
        )
        if isinstance(search_result, dict):
            refreshed["search_payload_variant"] = search_result.get("_sweepy_payload_variant") or {}
        if isinstance(follow_result, dict):
            refreshed["follow_payload_variant"] = follow_result.get("_sweepy_payload_variant") or {}
        return refreshed
    except Exception as e:
        if not search_result:
            stage = "search"
        elif profile and already_followed is False and not follow_result:
            stage = "follow"
        else:
            stage = "add_refresh"
        snapshot = write_friend_error_snapshot(
            f"friend_{stage}",
            viewer_id,
            stage=stage,
            profile=profile,
            search_result=search_result,
            follow_result=follow_result,
            error=e,
        )
        print(f"friend {stage} diagnostic snapshot written: {snapshot}", flush=True)
        return {"success": False, "detail": str(e), "snapshot": snapshot}


@app.post("/api/friends/unfollow")
async def unfollow_friend_by_id(req: FriendIdRequest):
    global active_client
    if not active_client:
        return {"success": False, "detail": "Not logged in"}

    viewer_id = int(req.viewer_id or 0)
    if viewer_id <= 0:
        return {"success": False, "detail": "Trainer ID must be a positive number"}

    try:
        unfollow_result = client_method_with_session_recovery("friend_unfollow", viewer_id)
        refreshed = refresh_friend_library([], cache_reason="friend_unfollow")
        refreshed["detail"] = f"Unfollowed trainer ID {viewer_id} and refreshed the following list."
        if isinstance(unfollow_result, dict):
            refreshed["unfollow_payload_variant"] = unfollow_result.get("_sweepy_payload_variant") or {}
        refreshed["unfollowed_viewer_id"] = viewer_id
        return refreshed
    except Exception as e:
        snapshot = write_friend_error_snapshot(
            "friend_unfollow",
            viewer_id,
            stage="unfollow",
            unfollow_result=unfollow_result if 'unfollow_result' in locals() else None,
            error=e,
        )
        print(f"friend unfollow diagnostic snapshot written: {snapshot}", flush=True)
        return {"success": False, "detail": str(e), "snapshot": snapshot}

@app.post("/api/career/action")
async def career_action(req: CareerActionRequest):
    global active_client, active_account
    if not active_client:
        return {"success": False, "detail": "Not logged in"}
    
    try:
        result = active_client.exec_command(
            command_type=req.command_type,
            command_id=req.command_id,
            current_turn=req.current_turn,
            current_vital=req.current_vital,
            command_group_id=req.command_group_id,
            select_id=req.select_id
        )
        
        data = result.get('data', {})
        return {
            "success": True,
            "chara_info": data.get('chara_info', {}),
            "command_result": data.get('command_result', {})
        }
    except Exception as e:
        return {"success": False, "detail": str(e)}

@app.post("/api/career/delete")
async def delete_career(req: DeleteCareerRequest):
    return await _delete_active_career(req.current_turn or 0, stop_runner_first=False)


def _sync_account_from_load_index():
    global active_account, active_dashboard_data
    load_result = active_client.call('load/index')
    account = sync_game_data_from_api_response('load/index', load_result, source='career_end_verify')
    if account is None:
        load_data = load_result.get('data', {}) if isinstance(load_result, dict) else {}
        update_start_state(load_data)
        account = get_account_status(load_data)
        active_account = account
        if active_dashboard_data is not None:
            active_dashboard_data["account"] = account
    return account or {}


def _clear_cached_career(account=None):
    global active_account, active_dashboard_data
    account = dict(account or active_account or {})
    account["career"] = None
    active_account = account
    if active_dashboard_data is not None:
        active_dashboard_data["account"] = account
    return account


async def _delete_active_career(current_turn: int = 0, *, stop_runner_first: bool = False):
    global active_client, active_account, active_dashboard_data
    if not active_client:
        return {"success": False, "detail": "Not logged in"}

    try:
        if stop_runner_first:
            request_loop_stop()
            career_runner.stop()
            for _ in range(30):
                if not career_runner.snapshot().get("running") and not loop_snapshot().get("active"):
                    break
                await asyncio.sleep(0.1)
        account = active_account or {}
        career = account.get("career") or {}
        if not career.get("active"):
            account = _sync_account_from_load_index()
            career = account.get("career") or {}
        resolved_turn = current_turn or career.get("turn", 0) or 1
        if not career.get("active") and not current_turn:
            return {"success": False, "detail": "No active career"}

        finish_result = active_client.finish_career(current_turn=resolved_turn, is_force_delete=True)
        sync_game_data_from_api_response('single_mode_free/finish', finish_result, source='career_end_finish')

        account = _sync_account_from_load_index()
        career = account.get("career") or {}
        if career.get("active") and hasattr(active_client, "delete_career"):
            delete_result = active_client.delete_career(current_turn=resolved_turn)
            sync_game_data_from_api_response('single_mode_free/delete', delete_result, source='career_end_delete')
            account = _sync_account_from_load_index()
            career = account.get("career") or {}

        if career.get("active"):
            return {
                "success": False,
                "detail": "End career request was sent, but the game still reports an active career.",
                "account": account,
            }

        account = _clear_cached_career(account)
        return {"success": True, "account": account}
    except Exception as e:
        return {"success": False, "detail": str(e)}


@app.post("/api/career/end")
async def end_career(req: DeleteCareerRequest):
    result = await _delete_active_career(req.current_turn or 0, stop_runner_first=True)
    if result.get("success"):
        result["runner"] = career_runner.snapshot()
        result["loop"] = loop_snapshot()
        result["detail"] = "Career ended"
    return result

@app.get("/api/debug/start_state")
async def get_start_state():
    apply_tp_timer_to_cached_state()
    return active_start_state

@app.get("/api/debug/start")
async def debug_start():
    return {
        "success": True,
        "debug": active_start_debug,
        "start_state_keys": sorted(active_start_state.keys()),
        "account_career": career_debug_view((active_account or {}).get("career")),
    }

@app.get("/api/debug/decks")
async def debug_decks():
    return {
        "success": True,
        "deck_count": len((active_dashboard_data or {}).get("decks", [])),
        "selection": active_selection,
        "dashboard_counts": {
            "umas": len((active_dashboard_data or {}).get("umas", [])),
            "supports": len((active_dashboard_data or {}).get("supports", [])),
            "parents": len((active_dashboard_data or {}).get("parents", [])),
            "friends": len((active_dashboard_data or {}).get("friends", [])),
        },
        "decks": [
            {
                "id": deck.get("id"),
                "name": deck.get("name"),
                "card_count": len(deck.get("cards") or []),
                "source": deck.get("source", ""),
                "card_ids": [card.get("id") for card in deck.get("cards", [])],
                "raw_fields": next(
                    (
                        item.get("raw_fields")
                        for item in (active_deck_debug or {}).get("merged", [])
                        if str(item.get("deck_id")) == str(deck.get("id"))
                    ),
                    {},
                ),
            }
            for deck in (active_dashboard_data or {}).get("decks", [])
        ],
        "debug": active_deck_debug,
    }

@app.post("/api/debug/decks/probe")
async def probe_decks():
    global active_client, active_deck_debug
    if not active_client:
        return {"success": False, "detail": "Not logged in"}

    all_rows = []
    scans = {}

    try:
        load_result = load_index_with_session_recovery(active_client)
        load_data = load_result.get("data", {})
        rows, debug = find_deck_rows(load_data, "probe_load_index")
        scans["load_index"] = debug
        all_rows.extend(rows)
    except Exception as exc:
        scans["load_index_error"] = str(exc)

    try:
        pre_result = game_api_call_with_session_recovery("pre_single_mode/index", {})
        pre_data = pre_result.get("data", {})
        rows, debug = find_deck_rows(pre_data, "probe_pre_single_mode")
        scans["pre_single_mode"] = debug
        all_rows.extend(rows)
    except Exception as exc:
        scans["pre_single_mode_error"] = str(exc)

    merged = merge_deck_candidate_rows(all_rows)
    active_deck_debug = {
        "probe": scans,
        "raw_candidates": len(all_rows),
        "deduped": len(merged),
        "merged": [debug_deck_summary(row) for row in merged],
    }
    if merged:
        merge_dashboard_decks(merged, active_deck_debug)
    return await debug_decks()

@app.get("/api/debug/raw_load")
async def get_raw_load():
    return {"error": "raw load/index response storage disabled"}

@app.get("/api/images/{image_name}")
async def get_image(image_name: str):
    name_no_ext = image_name.split('?')[0].replace('.png', '')
    
    exact_path = images_dir / f"{name_no_ext}.png"
    if exact_path.exists():
        return FileResponse(exact_path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    
    for fallback_id in ['100101', '10010', '10001']:
        fb_path = images_dir / f"{fallback_id}.png"
        if fb_path.exists():
            return FileResponse(fb_path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    
    raise HTTPException(status_code=404, detail="Image not found")


@app.get("/api/dev/version")
async def dev_version():
    return {
        "success": True,
        "pid": os.getpid(),
        "started_at": SERVER_START_TIME,
        "version": SERVER_VERSION_TOKEN,
        "instance": {
            "name": sweepy_instance_name(),
            "host": sweepy_bind_host(),
            "port": sweepy_bind_port(),
            "runtime_dir": str(dev_runtime_dir()),
            "dual_mode": dual_instance_mode_enabled(),
            "auto_learning_scope": "instance_local" if instance_local_learning_enabled() else "shared_preset",
            "auth_capture_kill_game": auth_capture_kill_game_enabled(),
            "instance_device_identity": env_flag("SWEEPY_INSTANCE_DEVICE_IDENTITY", False),
        },
        "backend_reload": {
            "enabled": backend_dev_reload_enabled(),
            "pending": bool(dev_reloader_state.get("pending_restart")),
            "last_change": dev_reloader_state.get("last_change") or "",
            "restart_requested": bool(dev_reloader_state.get("restart_requested")),
            "pending_gate": dev_reloader_state.get("pending_restart_gate") or "",
            "pending_release": dev_reloader_state.get("pending_restart_release") or "",
        },
        "git_auto_update": git_auto_update_snapshot(),
    }


@app.head("/api/dev/version")
async def dev_version_head():
    return Response(headers={
        "Cache-Control": "no-cache",
        "ETag": f'"{SERVER_VERSION_TOKEN}"',
        "X-Sweepy-Backend-Version": SERVER_VERSION_TOKEN,
    })


@app.post("/api/dev/reload")
async def dev_reload():
    if runner_is_active():
        return {"success": False, "detail": "Stop the career runner before refreshing the backend"}
    git_result = perform_git_auto_update(manual=True)
    git_status = str((git_result or {}).get("status") or "")
    git_detail = str((git_result or {}).get("detail") or "").strip()
    if git_result and git_result.get("success") and git_status == "updated":
        return {
            "success": True,
            "detail": git_detail or "Git update applied. Page will reconnect automatically.",
            "git_auto_update": git_result,
        }
    if dev_reloader_state.get("restart_requested"):
        detail = "Backend refresh already queued. Page will reconnect automatically."
        if git_detail:
            detail = f"{detail} Git check: {git_detail}"
        return {"success": True, "detail": detail, "git_auto_update": git_result}
    scheduled = schedule_backend_restart("manual_backend_refresh")
    if not scheduled:
        return {
            "success": False,
            "detail": "Backend refresh is already in progress",
            "git_auto_update": git_result,
        }
    detail = "Backend refresh queued. Page will reconnect automatically."
    if git_detail:
        detail = f"{detail} Git check: {git_detail}"
    return {"success": True, "detail": detail, "git_auto_update": git_result}


@app.post("/api/dev/update")
async def dev_update():
    result = perform_git_auto_update(manual=True)
    return result


@app.get("/styles.css")
async def styles_css():
    path = base_dir / "public" / "styles.css"
    if path.exists():
        return FileResponse(path, media_type="text/css", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="styles.css not found")

@app.get("/app.js")
async def app_js():
    path = base_dir / "public" / "app.js"
    if path.exists():
        return FileResponse(path, media_type="application/javascript", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="app.js not found")


@app.get("/sweep.png")
async def sweep_png():
    path = base_dir / "public" / "sweep.png"
    if path.exists():
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="sweep.png not found")

@app.get("/broom.png")
async def broom_png():
    path = base_dir / "public" / "broom.png"
    if path.exists():
        return FileResponse(path, media_type="image/png", headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="broom.png not found")

@app.get("/assets/data/{file_name}")
async def get_asset_data(file_name: str):
    path = base_dir / 'public' / 'assets' / 'data' / file_name
    if path.exists():
        return FileResponse(path, headers={"Cache-Control": "no-cache"})
    raise HTTPException(status_code=404, detail="File not found")

@app.get("/races/{file_name}")
async def get_race_image(file_name: str):
    path = base_dir / "public" / "races" / file_name
    if path.exists():
        return FileResponse(path, headers={"Cache-Control": "max-age=31536000"})
    raise HTTPException(status_code=404, detail="Race image not found")

@app.get("/", response_class=HTMLResponse)
async def root():
    index_path = base_dir / "public" / "index.html"
    if index_path.exists():
        return FileResponse(index_path, media_type="text/html", headers={"Cache-Control": "no-cache"})
    return "index.html not found"

def set_console_topmost():
    if os.name != 'nt':
        return
    try:
        import ctypes
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if not hwnd:
            return
        ctypes.windll.user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)
    except Exception:
        pass

def kill_process_by_name(name):
    if os.name != 'nt':
        return
    try:
        subprocess.run(['taskkill', '/IM', name, '/F'], capture_output=True, text=True, timeout=10)
    except Exception:
        pass

def kill_listeners_on_port(port):
    if os.name != 'nt':
        return
    try:
        proc = subprocess.run(
            ['netstat', '-ano'],
            capture_output=True,
            text=True,
            timeout=5
        )
    except Exception:
        return

    current_pid = os.getpid()
    pids = set()
    marker = f':{port}'
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        local_addr = parts[1]
        state = parts[3].upper() if len(parts) >= 5 else ''
        pid_text = parts[-1]
        if marker not in local_addr or state != 'LISTENING':
            continue
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid and pid != current_pid:
            pids.add(pid)

    if not pids:
        return
    print(f"Port {port} already in use; killing listener PID(s): {', '.join(map(str, sorted(pids)))}", flush=True)
    for pid in sorted(pids):
        try:
            subprocess.run(['taskkill', '/PID', str(pid), '/F'], capture_output=True, text=True, timeout=5)
        except Exception:
            pass
    time.sleep(0.5)

def has_fresh_auth_config(cfg):
    app_ver = str(cfg.get('app_ver') or '').strip()
    res_ver = str(cfg.get('res_ver') or '').strip()
    if not app_ver or not res_ver:
        return False
    if int(cfg.get('auth_key_len') or 0) != 48:
        return False
    viewer_id = cfg.get('viewer_id')
    udid = str(cfg.get('udid') or '').strip()
    auth_key = str(cfg.get('auth_key') or '').strip().lower()
    if not viewer_id or not udid or not auth_key:
        return False
    if not re.fullmatch(r'[0-9a-f]+', auth_key):
        return False
    if len(auth_key) < 32 or len(auth_key) % 2:
        return False
    if len(udid) != 36 or udid.count('-') != 4:
        return False
    return True

def launch_game():
    if os.name != 'nt':
        print('Auth refresh needs Windows Steam launch.')
        return False
    try:
        os.startfile(f'steam://rungameid/{APP_ID}')
        return True
    except Exception as e:
        print(f'Failed to launch Umamusume through Steam: {e}')
        return False

def refresh_auth_before_serving(timeout_sec=None):
    global pending_game_auth_config
    timeout_sec = timeout_sec or int(os.environ.get('SWEEPY_AUTH_CAPTURE_TIMEOUT_SEC', '180'))
    started_at = time.time()
    deadline = started_at + timeout_sec

    print('[NEED TO CAPTURE AUTH]', flush=True)
    if not launch_game():
        return False
    
    print(f'Waiting up to {timeout_sec}s for user to enter game menu', flush=True)

    session = None
    captured_data = {}
    done = {'ok': False}

    def on_message(message, data):
        if message.get('type') == 'error':
            print(f"Frida Error: {message.get('description')}", flush=True)
            return
        payload = message.get('payload') or {}
        if payload.get('type') == 'creds':
            if payload.get('app_ver') and payload.get('res_ver'):
                captured_data.update(payload)
                done['ok'] = True

    while time.time() < deadline:
        try:
            session = frida.attach(PROCESS_NAME)
            break
        except Exception:
            time.sleep(1)
    
    if not session:
        print(f'Error: {PROCESS_NAME} not found within timeout.', flush=True)
        return False

    try:
        script = session.create_script(JS_CODE)
        script.on('message', on_message)
        script.load()

        while time.time() < deadline:
            if done['ok']:
                if has_fresh_auth_config(captured_data):
                    pending_game_auth_config = dict(captured_data)
                    if auth_capture_kill_game_enabled():
                        time.sleep(random.uniform(2, 4))
                        kill_process_by_name(PROCESS_NAME)
                    else:
                        print("Auth captured; leaving game process running for dual-instance setup.", flush=True)
                    return True
            time.sleep(0.5)
    except Exception as e:
        print(f'Frida injection failed: {e}', flush=True)
    finally:
        if session:
            try:
                session.detach()
            except Exception:
                pass

    print('Auth refresh failed: no fresh credentials captured before timeout.', flush=True)
    return False


if __name__ == "__main__":
    import sys
    import uvicorn
    host = sweepy_bind_host()
    port = sweepy_bind_port()
    instance_name = sweepy_instance_name()
    set_console_topmost()
    if sweepy_kill_existing_listener_enabled():
        kill_listeners_on_port(port)
    restored = False
    if env_flag("SWEEPY_RESTORE_BEFORE_SERVE", False):
        restored = restore_dev_session_cache()
    elif dev_session_cache_enabled():
        def restore_dev_session_cache_background():
            try:
                restore_dev_session_cache()
            except Exception as exc:
                print(f"background dev session restore failed: {exc}", flush=True)
        threading.Thread(target=restore_dev_session_cache_background, daemon=True).start()
    if not restored:
        if env_flag("SWEEPY_AUTH_BEFORE_SERVE", False):
            if not refresh_auth_before_serving():
                print("Auth refresh failed; serving UI and passive capture endpoints without an active game session.", flush=True)
        else:
            print("No backend session restored; serving UI and passive capture endpoints without pre-auth.", flush=True)
    start_backend_dev_reloader()
    start_git_auto_updater()
    print(f"Sweepy instance '{instance_name}' runtime: {dev_runtime_dir()}", flush=True)
    print(f"Access the Web UI at: http://{host}:{port}", flush=True)
    uvicorn.run(app, host=host, port=port, log_level="error")
