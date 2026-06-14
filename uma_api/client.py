import base64
import copy
import json
import os
import time
import uuid
import requests
import hashlib
import random
import re
import struct
import msgpack
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import subprocess
import platform
import socket
import shutil
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

class StateRecoveryError(Exception):
    pass


class ApiCallError(Exception):
    def __init__(
        self,
        message,
        *,
        endpoint="",
        request_payload=None,
        response_body=None,
        response_text=None,
        http_status=None,
        result_code=None,
        response_code=None,
        req_id=None,
    ):
        super().__init__(message)
        self.endpoint = endpoint
        self.request_payload = request_payload
        self.response_body = response_body
        self.response_text = response_text
        self.http_status = http_status
        self.result_code = result_code
        self.response_code = response_code
        self.req_id = req_id

def api_error_response_viewer_id(exc):
    body = getattr(exc, "response_body", None)
    if isinstance(body, dict):
        headers = body.get("data_headers") or {}
        try:
            return int(headers.get("viewer_id") or 0)
        except (TypeError, ValueError):
            return 0
    match = re.search(r'"viewer_id"\s*:\s*(\d+)', str(exc or ""), flags=re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except (TypeError, ValueError):
            return 0
    return 0

def api_error_result_code(exc):
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
            return 0
    return 0

def api_error_endpoint(exc):
    endpoint = str(getattr(exc, "endpoint", "") or "").strip()
    if endpoint:
        return endpoint
    match = re.search(r"\bon\s+([a-z0-9_/-]+)", str(exc or ""), flags=re.IGNORECASE)
    return match.group(1) if match else ""

def is_terminal_start_session_auth_error(exc):
    return api_error_endpoint(exc) == "tool/start_session" and api_error_result_code(exc) in {394, 501}

BASE_URL = 'https://api.games.umamusume.com/umamusume/'
DIR = str(Path(__file__).resolve().parent.parent)
LAST_TICKET_GEN_RESULT = None
LAST_SAVED_CONFIG = None


def runtime_output_root():
    override = os.environ.get("UMA_RUNTIME_DIR")
    if override:
        return Path(override).expanduser().resolve()

    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".git").exists():
            return candidate / "uma_runtime"
    return here.parent.parent.parent / "uma_runtime"


TRACE_DIR = runtime_output_root() / "trace_logs"
CLIENT_VERSION_CACHE_PATH = runtime_output_root() / "client_version_cache.json"


def env_flag(name, default=True):
    value = os.environ.get(name)
    if value is None:
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _version_tuple(value):
    try:
        parts = [int(p) for p in str(value or "").strip().split(".")]
    except (TypeError, ValueError):
        return ()
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


def _res_version_int(value):
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return -1


def _version_candidate_sort_key(pair):
    app, res = pair
    return (_version_tuple(app), _res_version_int(res))


def read_client_version_cache(steam_app_id=None):
    """Read the last accepted live APP-VER / RES-VER pair.

    This cache is deliberately separate from reusable auth profiles. Auth
    profiles can become stale account-by-account; the live client version is
    global for the Steam app and should survive auth refresh failures.
    """
    path = CLIENT_VERSION_CACHE_PATH
    try:
        if not path.exists():
            return {}
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    wanted_app_id = str(steam_app_id or "").strip()
    by_app = payload.get("by_steam_app_id")
    if wanted_app_id and isinstance(by_app, dict):
        entry = by_app.get(wanted_app_id)
        if isinstance(entry, dict) and entry.get("app_ver") and entry.get("res_ver"):
            out = dict(entry)
            out.setdefault("steam_app_id", wanted_app_id)
            return out
    if payload.get("app_ver") and payload.get("res_ver"):
        return dict(payload)
    return {}


def write_client_version_cache(app_ver, res_ver, *, unity_ver="", steam_app_id="", source="", store_url=""):
    app_ver = str(app_ver or "").strip()
    res_ver = str(res_ver or "").strip()
    if not app_ver or not res_ver:
        return False
    steam_app_id = str(steam_app_id or "").strip() or "default"
    path = CLIENT_VERSION_CACHE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        payload = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    by_app = payload.get("by_steam_app_id")
    if not isinstance(by_app, dict):
        by_app = {}
    entry = {
        "app_ver": app_ver,
        "res_ver": res_ver,
        "unity_ver": str(unity_ver or "").strip(),
        "steam_app_id": steam_app_id,
        "source": str(source or "").strip(),
        "store_url": str(store_url or "").strip(),
        "saved_at": time.time(),
    }
    by_app[steam_app_id] = entry
    payload.update({
        "version": 1,
        "app_ver": app_ver,
        "res_ver": res_ver,
        "unity_ver": entry["unity_ver"],
        "steam_app_id": steam_app_id,
        "source": entry["source"],
        "store_url": entry["store_url"],
        "saved_at": entry["saved_at"],
        "by_steam_app_id": by_app,
    })
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{int(time.time() * 1000)}.tmp")
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return True
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False


def extract_version_candidates_from_text(text):
    """Extract plausible APP-VER / RES-VER pairs from HTML/JS/JSON text."""
    text = str(text or "")
    if not text:
        return []

    app_versions = []
    res_versions = []

    def add_app(value):
        value = str(value or "").strip()
        if value and value not in app_versions:
            app_versions.append(value)

    def add_res(value):
        value = str(value or "").strip()
        if value and value not in res_versions:
            res_versions.append(value)

    app_key_pattern = re.compile(
        r"(?i)(?:app[_-]?ver(?:sion)?|appVersion|APP-VER|client[_-]?version|versionName)"
        r"[^0-9]{0,40}([0-9]+\.[0-9]+(?:\.[0-9]+)?)"
    )
    res_key_pattern = re.compile(
        r"(?i)(?:res[_-]?ver(?:sion)?|resource[_-]?version|resourceVersion|RES-VER)"
        r"[^0-9]{0,40}([0-9]{7,10})"
    )
    for match in app_key_pattern.finditer(text):
        add_app(match.group(1))
    for match in res_key_pattern.finditer(text):
        add_res(match.group(1))

    # Some generated launcher pages only expose compact key/value literals.
    for match in re.finditer(r"(?i)['\"]APP-VER['\"]\s*[:=]\s*['\"]([0-9]+\.[0-9]+(?:\.[0-9]+)?)['\"]", text):
        add_app(match.group(1))
    for match in re.finditer(r"(?i)['\"]RES-VER['\"]\s*[:=]\s*['\"]([0-9]{7,10})['\"]", text):
        add_res(match.group(1))

    # Fallback: if there is exactly one semver-like value and one resource-like
    # value in the document, pair them. Avoid broad cartesian matches when the
    # document contains many unrelated versions.
    if not app_versions:
        found = sorted(set(re.findall(r"\b([0-9]+\.[0-9]+\.[0-9]+)\b", text)), key=_version_tuple, reverse=True)
        if len(found) <= 4:
            for value in found:
                add_app(value)
    if not res_versions:
        found = sorted(set(re.findall(r"\b(10[0-9]{6,8})\b", text)), key=_res_version_int, reverse=True)
        if len(found) <= 6:
            for value in found:
                add_res(value)

    out = []
    seen = set()
    for app in app_versions:
        for res in res_versions:
            key = (app, res)
            if key in seen:
                continue
            seen.add(key)
            out.append(key)
    return out


def discover_version_candidates_from_store_url(store_url, max_fetches=None):
    """Best-effort scrape of the server-provided update page.

    The 204 response's store_url is public launcher/update content. When it
    contains APP-VER/RES-VER metadata, exact candidates should beat blind
    guesses. Failures are silent so auth can continue to the generated probes.
    """
    store_url = str(store_url or "").strip()
    if not store_url.startswith(("http://", "https://")):
        return []
    try:
        max_fetches = int(max_fetches or os.environ.get("SWEEPY_VERSION_STORE_URL_MAX_FETCHES", "6"))
    except (TypeError, ValueError):
        max_fetches = 6
    max_fetches = max(1, min(max_fetches, 12))
    timeout = 8.0
    headers = {
        "User-Agent": "Mozilla/5.0 SweepyVersionProbe/1.0",
        "Accept": "text/html,application/javascript,application/json,text/plain,*/*",
    }
    queue = [store_url]
    fetched = set()
    out = []
    seen = set()
    while queue and len(fetched) < max_fetches:
        url = queue.pop(0)
        if url in fetched:
            continue
        fetched.add(url)
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            if resp.status_code >= 400:
                continue
            text = resp.text or ""
        except Exception:
            continue
        for pair in extract_version_candidates_from_text(text):
            if pair not in seen:
                seen.add(pair)
                out.append(pair)
        if len(fetched) >= max_fetches:
            continue
        for match in re.finditer(r"""(?i)(?:src|href)\s*=\s*["']([^"']+\.(?:js|json|html?)(?:\?[^"']*)?)["']""", text):
            child = urljoin(url, match.group(1))
            if child not in fetched and child not in queue:
                queue.append(child)
    return out


def sweepy_instance_name():
    value = str(os.environ.get("SWEEPY_INSTANCE_NAME") or "").strip()
    return value or "default"


def dual_instance_device_identity_enabled():
    return bool(sweepy_instance_name() and env_flag("SWEEPY_INSTANCE_DEVICE_IDENTITY", False))


def resolve_device_id(base_device_id, *, stored_mode="", stored_instance_name=""):
    base = str(base_device_id or "").strip()
    if not base:
        return "", ""
    if not dual_instance_device_identity_enabled():
        return base, ""
    instance_name = sweepy_instance_name()
    if stored_mode == "instance_local" and stored_instance_name == instance_name:
        return base, stored_mode
    scoped = hashlib.sha1(f"{base}:{instance_name}".encode()).hexdigest()
    return scoped, "instance_local"

TICKET_GEN_JS = """const SteamUser = require("steam-user");

const args = process.argv.slice(2);
let username = "";
let password = "";
let appid = 3224770;
let code = "";

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--username") username = args[++i];
  else if (args[i] === "--password") password = args[++i];
  else if (args[i] === "--appid") appid = parseInt(args[++i]);
  else if (args[i] === "--code") code = args[++i];
}

if (!username || !password) {
  process.stderr.write(
    "Usage: node ticket_gen.js --username X --password Y [--code Z]\\n"
  );
  process.exit(1);
}

const client = new SteamUser();

const loginOpts = {
  accountName: username,
  password: password,
};

if (code) {
  loginOpts.twoFactorCode = code;
}

client.logOn(loginOpts);

client.on("steamGuard", (domain, callback) => {
  process.stderr.write(
    "NEED_GUARD:" + (domain || "2fa") + "\\n"
  );
  process.exit(2);
});

client.on("error", (err) => {
  process.stderr.write("ERROR:" + err.message + "\\n");
  process.exit(1);
});

client.on("loggedOn", () => {
  process.stderr.write(
    "Logged in as " + client.steamID.getSteamID64() + "\\n"
  );
  client.createAuthSessionTicket(appid, (err, sessionTicket) => {
    if (err) {
      process.stderr.write("Ticket error: " + err.message + "\\n");
      process.exit(1);
    }
    const buf = Buffer.isBuffer(sessionTicket) ? sessionTicket : sessionTicket.sessionTicket || sessionTicket;
    const result = {
      steam_id: client.steamID.getSteamID64(),
      session_ticket: Buffer.from(buf).toString("hex").toUpperCase(),
    };
    process.stdout.write(JSON.stringify(result) + "\\n");
    process.stderr.write(
      "Ticket generated (" + Buffer.from(buf).length + " bytes)\\n"
    );
    setTimeout(() => process.exit(0), 500);
  });
});
"""

SALT = b'co!=Y;(UQCGxJ_n82'
HEAD = bytes.fromhex('6b20e2ab6c311330f761d737ce3f3025750850665eea58b6372f8d2f57501eb344bdb7270a9067f5b63cd61f152cfb986cbfbf7a')
SENSITIVE_ERROR_KEYS = {"auth_key", "steam_session_ticket", "sid", "udid", "device_id"}
FULL_TRACE_STRING_KEYS = {"race_scenario"}


def redact_for_console(value, key=""):
    if key in SENSITIVE_ERROR_KEYS:
        return "<redacted>"
    if isinstance(value, dict):
        return {k: redact_for_console(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_for_console(item, key) for item in value[:20]]
    if isinstance(value, str) and len(value) > 160 and key not in FULL_TRACE_STRING_KEYS:
        return value[:160] + "...<truncated>"
    return value


def format_api_error(ep, rc, res):
    details = {
        "endpoint": ep,
        "response_code": res.get("response_code"),
        "result_code": rc,
        "data_headers": redact_for_console(res.get("data_headers") or {}),
    }
    data = res.get("data")
    if isinstance(data, dict):
        interesting = {}
        for key in (
            "error_code",
            "error_message",
            "message",
            "result_code",
            "viewer_id",
            "current_turn",
            "chara_info",
            "single_mode_chara_light",
        ):
            if key in data:
                interesting[key] = data[key]
        if interesting:
            details["data"] = redact_for_console(interesting)
    elif data is not None:
        details["data"] = redact_for_console(data)
    return json.dumps(details, ensure_ascii=False, default=str)


def is_client_version_stale_response(ep, rc, res):
    """tool/start_session 204 with store_url is an update-required response.

    It is not recoverable by auth refresh, viewer-id remap, or retry of the
    SAME version. But the client *can* probe likely successor versions
    automatically — see `generate_version_candidates` and the 204 handler
    in `UmaClient.call` for the auto-discovery pass.
    """
    try:
        code = int(rc or 0)
    except (TypeError, ValueError):
        code = 0
    if ep != "tool/start_session" or code != 204:
        return False
    headers = (res or {}).get("data_headers") or {}
    return bool(str(headers.get("store_url") or "").strip())


def generate_version_candidates(current_app_ver, current_res_ver, max_candidates=None, *, store_url="", steam_app_id=""):
    """Generate plausible (app_ver, res_ver) pairs to try after a 204+store_url.

    Cygames bumps `res_ver` more often than `app_ver`. Empirical pattern
    observed in this codebase's history: `res_ver` moves in 100-step
    increments (10006100 → 10006200 → 10006300), occasionally jumps
    1000 or 10000 across larger feature drops. `app_ver` moves in semver
    patch (1.21.1 → 1.22.0 → 1.22.1) or minor bumps, occasionally a
    minor jump (1.22 → 1.25) across major content events. So we order
    candidates by likelihood (most-likely first):

      1. Same app_ver, res_ver +100…+10000 (most common)
      2. app_ver patch bump (1.22.0 → 1.22.1/+2/+3), res_ver unchanged or bumped
      3. app_ver minor bump (1.22.0 → 1.23.0/+2/+3/+5), res_ver bumped

    Caller is expected to try them in order and stop on first success.

    `max_candidates` caps the probe budget. Defaults to the value of the
    `SWEEPY_VERSION_AUTODISCOVERY_MAX_CANDIDATES` env var, or 80 if not
    set. The probe budget governs how far past the current version the
    bot will reach before falling back to the actionable error.
    """
    import os as _os
    if max_candidates is None:
        try:
            max_candidates = int(_os.environ.get(
                "SWEEPY_VERSION_AUTODISCOVERY_MAX_CANDIDATES", "80",
            ))
        except (TypeError, ValueError):
            max_candidates = 80
    max_candidates = max(1, int(max_candidates))

    candidates = []
    seen = set()

    def push(app, res):
        key = (str(app), str(res))
        if key in seen:
            return
        if not key[0].strip() or not key[1].strip():
            return
        seen.add(key)
        candidates.append((str(app), str(res)))

    # Tier -2: last accepted live version. This is independent of reusable
    # auth profiles, so stale account caches cannot override it.
    cached = read_client_version_cache(steam_app_id)
    if cached:
        push(cached.get("app_ver"), cached.get("res_ver"))

    # Tier -1: exact metadata scraped from the server-provided update page.
    # This makes 204+store_url self-healing when the launcher page exposes the
    # live app/resource values.
    for app, res in discover_version_candidates_from_store_url(store_url):
        push(app, res)

    # Tier 0: bot's hardcoded defaults / env-var overrides. These are the
    # "known-good" values someone shipping the bot believes work right
    # now. Try them FIRST — they're more likely to succeed than blind
    # increment guesses. Common pattern: user updates main.py defaults
    # to current live versions but stale dev_session.json keeps the old
    # ones; auto-discovery should immediately try the defaults.
    default_app_ver = os.environ.get("SWEEPY_DEFAULT_APP_VER", "1.22.0")
    default_res_ver = os.environ.get("SWEEPY_DEFAULT_RES_VER", "10006300")
    if str(default_app_ver) != str(current_app_ver) or str(default_res_ver) != str(current_res_ver):
        push(default_app_ver, default_res_ver)
        # Pair the default app_ver with current res_ver + bumps in case the
        # default is right on one axis but stale on the other.
        try:
            def_res_int = int(str(default_res_ver).strip())
            for delta in (0, 100, 200, 500, 1000):
                push(default_app_ver, def_res_int + delta)
        except (TypeError, ValueError):
            pass

    # Parse current res_ver
    try:
        cur_res = int(str(current_res_ver).strip())
    except (TypeError, ValueError):
        cur_res = None

    # Parse current app_ver into [major, minor, patch]
    try:
        parts = [int(p) for p in str(current_app_ver).strip().split('.')]
        while len(parts) < 3:
            parts.append(0)
        major, minor, patch = parts[0], parts[1], parts[2]
    except (TypeError, ValueError, AttributeError):
        major, minor, patch = None, None, None

    # Tier 1: res_ver bump only from current. Widened range covers large
    # content-drop jumps. Steps tuned to hit common 100-multiples that
    # match the bot's hardcoded defaults (10006300, 10006400, etc).
    if cur_res is not None:
        # First, round-down current to nearest 100 and step up from there,
        # so we hit canonical 100-multiples (10006200, 10006300, ...) even
        # when current is off (e.g. cached 10006120 → probe 10006300 too).
        rounded = (cur_res // 100) * 100
        for delta in (100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1200, 1500, 2000, 2500, 3000, 4000, 5000):
            push(current_app_ver, rounded + delta)
        # Then literal current + deltas (covers off-100 increments)
        for delta in (100, 200, 300, 400, 500, 700, 1000, 1500, 2000, 3000, 5000, 7500, 10000, 15000):
            push(current_app_ver, cur_res + delta)

    # Tier 2: app_ver patch bump (1.22.0 → 1.22.1/+2/+3) at current or bumped res_ver
    if major is not None:
        for pp in (patch + 1, patch + 2, patch + 3, patch + 4, patch + 5):
            cand_app = f"{major}.{minor}.{pp}"
            push(cand_app, current_res_ver)
            if cur_res is not None:
                for delta in (100, 300, 500, 1000, 2000, 5000):
                    push(cand_app, cur_res + delta)

    # Tier 3: app_ver minor bump (1.22.0 → 1.23/24/25/27.0) with bumped res_ver
    if major is not None:
        for mm in (minor + 1, minor + 2, minor + 3, minor + 4, minor + 5, minor + 6, minor + 8):
            for pp in (0, 1):
                cand_app = f"{major}.{mm}.{pp}"
                push(cand_app, current_res_ver)
                if cur_res is not None:
                    for delta in (100, 300, 500, 1000, 2000, 5000, 10000):
                        push(cand_app, cur_res + delta)

    return candidates[:max_candidates]


def client_version_stale_api_message(ep, rc, res, app_ver="", res_ver=""):
    headers = (res or {}).get("data_headers") or {}
    store_url = str(headers.get("store_url") or "").strip()
    detail = format_api_error(ep, rc, res)
    return (
        f"API error 204 on {ep}: game client version metadata is stale. "
        f"Sent APP-VER={app_ver or '<empty>'} RES-VER={res_ver or '<empty>'}. "
        "The server returned store_url, so retrying the same cached metadata will not fix this. "
        "Sweepy attempted automatic version discovery first; if this message remains, update the installed game client "
        "or capture auth once from the updated client so the live APP-VER/RES-VER can be cached. "
        "SWEEPY_DEFAULT_APP_VER and SWEEPY_DEFAULT_RES_VER remain available as manual overrides. "
        f"store_url={store_url}. "
        f"Original response: {detail}"
    )


def sm5(data):
    h = hashlib.md5()
    h.update(data)
    h.update(SALT)
    return h.digest()

def make_sid(vid, udid):
    return sm5((str(vid) + udid).encode())

def next_sid(sid):
    return sm5(sid.encode())

def gen_key():
    out = b''
    while len(out) < 32:
        out += format(random.randint(0, 65535), 'x').encode()
    return out[:32]

def get_iv(udid):
    return udid.replace('-', '').lower()[:16].encode()

def get_raw_udid(udid):
    return bytes.fromhex(udid.replace('-', '').lower())

def pack(sid, udid_raw, auth, payload, udid):
    key = gen_key()
    p = msgpack.packb(payload, use_bin_type=True)
    body = AES.new(key, AES.MODE_CBC, get_iv(udid)).encrypt(pad(struct.pack('<I', len(p)) + p, 16)) + key
    h = HEAD + sid + udid_raw + os.urandom(32)
    if auth: h += auth
    return base64.b64encode(struct.pack('<I', len(h)) + h + body)

def unpack(text, udid):
    raw = base64.b64decode(text)
    key, cipher = raw[-32:], raw[:-32]
    p = unpad(AES.new(key, AES.MODE_CBC, get_iv(udid)).decrypt(cipher), 16)
    return msgpack.unpackb(p[4:4+struct.unpack('<I', p[:4])[0]], raw=False, strict_map_key=False)

def get_gpu():
    if platform.system() != "Windows":
        raise RuntimeError(f"Unsupported OS: {platform.system()}. Only Windows is supported for PC info consistency.")

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Video") as video_key:
            for i in range(winreg.QueryInfoKey(video_key)[0]):
                adapter_guid = winreg.EnumKey(video_key, i)
                adapter_path = rf"SYSTEM\CurrentControlSet\Control\Video\{adapter_guid}\0000"
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, adapter_path) as adapter_key:
                        value, _ = winreg.QueryValueEx(adapter_key, "HardwareInformation.AdapterString")
                        if isinstance(value, bytes):
                            value = value.decode("utf-16-le", errors="ignore")
                        gpu_name = str(value).replace("\x00", "").strip()
                        if gpu_name:
                            return gpu_name
                except OSError:
                    continue
    except Exception as e:
        raise RuntimeError(f"Failed to fetch GPU info: {e}") from e

    raise RuntimeError("Failed to fetch GPU info: display adapter registry value empty")

def get_os():
    return f"Windows 11  ({platform.version()}) 64bit"

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip

def get_hwid(seed_string="default"):
    guid = str(uuid.uuid4()).lower()
    
    node = uuid.getnode()
    if not node:
        raise RuntimeError("Failed to retrieve stable hardware identity (MAC). Refusing to start.")
    device_id = hashlib.sha1(f"uma_{node}".encode()).hexdigest()

    if platform.system() != "Windows":
        raise RuntimeError(f"Unsupported OS: {platform.system()}. Only Windows is supported for HWID consistency.")
    
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as bios_key:
            device_name, _ = winreg.QueryValueEx(bios_key, "SystemProductName")
            device_name = str(device_name).strip()
        if not device_name:
            raise RuntimeError("System product name returned empty. Refusing to start.")
    except Exception as e:
        raise RuntimeError(f"Failed to fetch system product name: {e}. Refusing to start.")

    return {
        'device_name': device_name,
        'graphics_device_name': get_gpu(),
        'platform_os_version': get_os(),
        'ip_address': get_ip(),
        'udid': guid,
        'device_id': device_id
    }

def check_deps():
    if not shutil.which('node'):
        raise Exception(
            "node is not on PATH. Install Node.js 18+ from "
            "https://nodejs.org/ (or `winget install -e --id OpenJS.NodeJS`) "
            "and re-launch the bot from a fresh terminal."
        )
    if not os.path.exists(os.path.join(DIR, 'node_modules')):
        # On Windows, `npm` is a .cmd shim and subprocess.run(['npm', ...])
        # fails with WinError 2 because the loader looks for an .exe named
        # 'npm'. Use shutil.which() to get the resolved path, OR fall back
        # to shell=True so cmd.exe handles the .cmd extension.
        npm_path = shutil.which('npm')
        if not npm_path:
            raise Exception(
                "npm is not on PATH but Node is — your Node install is "
                "incomplete. Reinstall Node from https://nodejs.org/ "
                "(the standard installer includes npm). Or run "
                "`npm install` manually in this folder once."
            )
        try:
            subprocess.run(
                [npm_path, 'install', '--silent'],
                check=True,
                cwd=DIR,
            )
        except FileNotFoundError:
            # Last-ditch: try via the shell so cmd.exe resolves npm.cmd
            subprocess.run(
                'npm install --silent',
                check=True,
                cwd=DIR,
                shell=True,
            )

def configured_steam_app_id(value=None):
    raw = str(value or os.environ.get("SWEEPY_STEAM_APP_ID") or "3224770").strip()
    try:
        appid = int(raw)
    except (TypeError, ValueError):
        appid = 3224770
    return appid


def get_ticket(u, p, c='', appid=None):
    global LAST_TICKET_GEN_RESULT
    check_deps()
    steam_app_id = configured_steam_app_id(appid)
    try:
        timeout_sec = int(os.environ.get("SWEEPY_STEAM_TICKET_TIMEOUT_SEC") or 60)
    except (TypeError, ValueError):
        timeout_sec = 60
    timeout_sec = max(15, min(300, timeout_sec))
    cmd = [
        'node',
        '-e',
        TICKET_GEN_JS,
        '--',
        '--dummy',
        '--username',
        u,
        '--password',
        p,
        '--appid',
        str(steam_app_id),
    ]
    if c: cmd += ['--code', c]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_sec, cwd=DIR)
    except subprocess.TimeoutExpired as exc:
        LAST_TICKET_GEN_RESULT = {
            'stdout': exc.stdout or '',
            'stderr': exc.stderr or '',
            'returncode': None,
            'timeout_sec': timeout_sec,
            'appid': steam_app_id,
        }
        raise Exception(
            f"Steam ticket generation timed out after {timeout_sec}s for appid {steam_app_id}. "
            "Restart Steam or provide a cached Steam ticket; retrying the same hung helper will not help until Steam responds."
        ) from exc
    LAST_TICKET_GEN_RESULT = {
        'stdout': proc.stdout,
        'stderr': proc.stderr,
        'returncode': proc.returncode,
        'appid': steam_app_id,
    }
    if proc.returncode == 2:
        raise Exception('STEAM_GUARD_REQUIRED')
        
    out = proc.stdout.strip()
    if not out or proc.returncode != 0:
        error_msg = proc.stderr.strip() or 'fail'
        raise Exception(error_msg)
        
    line = out.split('\n')[-1]
    try:
        d = json.loads(line)
        return d['steam_id'], d['session_ticket']
    except Exception:
        raise Exception('bad json')

class UmaClient:

    def __init__(self, cfg, trace_enabled=True):
        profile = get_hwid(cfg.get('steam_password_seed', 'default'))

        self.viewer_id = cfg.get('viewer_id', 0)
        self.udid_str = cfg.get('udid') or profile['udid']
        self.auth_key_hex = cfg.get('auth_key', '')
        self.steam_id = str(cfg.get('steam_id', ''))
        self.steam_ticket = cfg.get('steam_session_ticket', '')
        self.steam_app_id = str(cfg.get('steam_app_id') or configured_steam_app_id())
        
        self.device_identity_instance = sweepy_instance_name() if dual_instance_device_identity_enabled() else ""
        self.device_id, self.device_identity_mode = resolve_device_id(
            cfg.get('device_id') or profile['device_id'],
            stored_mode=str(cfg.get('device_identity_mode') or '').strip(),
            stored_instance_name=str(cfg.get('device_identity_instance') or '').strip(),
        )
        self.device_name = cfg.get('device_name') or profile['device_name']
        self.graphics_device = cfg.get('graphics_device_name') or profile['graphics_device_name']
        self.ip_address = cfg.get('ip_address') or profile['ip_address']
        self.platform_os = cfg.get('platform_os_version') or profile['platform_os_version']
        self.locale = cfg.get('locale', 'JPN')
        
        self.unity_ver = cfg.get('unity_ver', '2022.3.62f2')
        self.app_ver = cfg.get('app_ver', '')
        self.res_ver = cfg.get('res_ver', '')

        if not self.app_ver or not self.res_ver:
             pass

        self.sid = bytes(16)
        self.cached_load_data = {}
        self.tp_info = {}
        self.coin_info = {}
        self.item_map = {}
        self.session = requests.Session()
        self._api_call_lock = threading.RLock()
        self._api_call_owner_thread = None
        self.update_headers()

        self.on_api_log = None
        self.trace_file = None
        if trace_enabled:
            self._init_trace_log()

    def _init_trace_log(self):
        try:
            log_dir = TRACE_DIR / "api_payloads"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            suffix = uuid.uuid4().hex[:6]
            self.trace_file = log_dir / f"{ts}_{suffix}_payloads.jsonl"
        except Exception as e:
            print(f"Error initializing trace log: {e}")
            self.trace_file = None

    def api_log(self, direction, ep, data, req_id=None):
        safe_data = redact_for_console(data)
        log_entry = {
            "ts": time.time(),
            "direction": direction,
            "endpoint": ep,
            "data": safe_data
        }
        if req_id:
            log_entry["req_id"] = req_id
            
        if callable(self.on_api_log):
            try:
                self.on_api_log(direction, ep, safe_data, req_id)
            except Exception:
                pass
        
        if self.trace_file:
            try:
                def _json_default(obj):
                    if isinstance(obj, bytes):
                        return obj.hex()
                    return str(obj)

                with open(self.trace_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False, default=_json_default) + "\n")
            except Exception as e:
                print(f"Error writing to log: {e}")

    def api_payload_summary(self, ep, payload):
        payload = payload or {}
        summary = {"current_turn": payload.get("current_turn")}
        if ep == "single_mode_free/gain_skills":
            summary["gain_skill_info_array"] = payload.get("gain_skill_info_array") or []
        elif ep == "single_mode_free/multi_item_exchange":
            summary["exchange_item_info_array"] = payload.get("exchange_item_info_array") or []
        elif ep == "item/exchange":
            summary["exchange_id"] = payload.get("exchange_id")
            summary["count"] = payload.get("count")
            summary["current_num"] = payload.get("current_num")
        elif ep == "single_mode_free/multi_item_use":
            summary["use_item_info_array"] = payload.get("use_item_info_array") or []
        return summary

    def safe_payload(self, payload):
        return dict(payload or {})

    def response_summary(self, res):
        data = res.get("data") or {}
        headers = res.get("data_headers") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        home = data.get("home_info") or {}
        events = data.get("unchecked_event_array") or []
        race = data.get("race_start_info") or {}
        summary = {
            "result_code": headers.get("result_code"),
            "keys": list(data.keys()),
        }
        if chara:
            summary["chara"] = {
                "turn": chara.get("turn"),
                "vital": chara.get("vital"),
                "max_vital": chara.get("max_vital"),
                "skill_point": chara.get("skill_point"),
                "fans": chara.get("fans"),
                "playing_state": chara.get("playing_state"),
            }
        if home:
            summary["commands"] = [
                {
                    "type": item.get("command_type"),
                    "id": item.get("command_id"),
                    "group": item.get("command_group_id"),
                    "enable": item.get("is_enable"),
                    "fail": item.get("failure_rate"),
                }
                for item in home.get("command_info_array") or []
            ]
        if events:
            summary["events"] = [
                {
                    "event_id": item.get("event_id"),
                    "chara_id": item.get("chara_id"),
                    "choices": len(((item.get("event_contents_info") or {}).get("choice_array") or [])),
                }
                for item in events
            ]
        if race:
            summary["race_start_info"] = {
                "program_id": race.get("program_id"),
                "race_instance_id": race.get("race_instance_id"),
                "is_short": race.get("is_short"),
            }
        return summary

    def auth_bytes(self):
        if not self.auth_key_hex or self.auth_key_hex == 'YOUR_AUTH_KEY_HERE':
            return b''
        return bytes.fromhex(self.auth_key_hex)

    def has_captured_auth(self):
        try:
            int(self.viewer_id)
            bytes.fromhex(str(self.auth_key_hex))
        except (TypeError, ValueError):
            return False
        return bool(
            self.viewer_id
            and self.udid_str
            and self.auth_key_hex
            and self.auth_key_hex != 'YOUR_AUTH_KEY_HERE'
            and self.steam_id
            and self.steam_ticket
        )

    def refresh_cached_account_state(self, data):
        self.cached_load_data = data or {}
        self.tp_info = self.cached_load_data.get('tp_info') or {}
        self.coin_info = self.cached_load_data.get('coin_info') or {}
        self.item_map = {}
        for item in self.cached_load_data.get('item_list', []) or []:
            self.item_map[item.get('item_id', 0)] = item.get('number', 0)

    def refresh_resource_state_from_response(self, res):
        data = (res or {}).get("data") or {}
        if isinstance(data.get("tp_info"), dict):
            self.tp_info = dict(data.get("tp_info") or {})
        if isinstance(data.get("coin_info"), dict):
            self.coin_info = dict(data.get("coin_info") or {})
        rewards = (data.get("reward_summary_info") or {}).get("add_item_list") or []
        for item in rewards:
            try:
                item_id = int(item.get("item_id") or 0)
                number = int(item.get("number") or item.get("num") or item.get("count") or 0)
            except Exception:
                continue
            if item_id and number:
                self.item_map[item_id] = int(self.item_map.get(item_id, 0) or 0) + number
        return res

    def regen_sid(self):
        self.sid = make_sid(self.viewer_id, self.udid_str)

    def common(self):
        return {
            'viewer_id': self.viewer_id, 'device': 4, 'device_id': self.device_id,
            'device_name': self.device_name, 'graphics_device_name': self.graphics_device,
            'ip_address': self.ip_address, 'platform_os_version': self.platform_os,
            'carrier': '', 'keychain': 0, 'locale': self.locale,
            'button_info': '', 'dmm_viewer_id': None, 'dmm_onetime_token': None,
            'steam_id': self.steam_id,
            'steam_session_ticket': self.steam_ticket
        }

    def update_headers(self):
        self.session.headers.update({
            'User-Agent': f'UnityPlayer/{self.unity_ver} (UnityWebRequest/1.0, libcurl/8.10.1-DEV)',
            'Accept': '*/*', 'Accept-Encoding': 'deflate, gzip',
            'Content-Type': 'application/x-msgpack', 'X-Unity-Version': self.unity_ver
        })

    def call(self, ep, args=None, retry_208=6, retry_205=3, quiet_result_codes=None, retry_http_403=None, retry_394=1, retry_viewer_remap=1):
        lock = getattr(self, "_api_call_lock", None)
        owner = getattr(self, "_api_call_owner_thread", None)
        ident = threading.get_ident()
        if lock is not None and owner != ident:
            with lock:
                previous_owner = getattr(self, "_api_call_owner_thread", None)
                self._api_call_owner_thread = ident
                try:
                    return self.call(
                        ep,
                        args,
                        retry_208=retry_208,
                        retry_205=retry_205,
                        quiet_result_codes=quiet_result_codes,
                        retry_http_403=retry_http_403,
                        retry_394=retry_394,
                        retry_viewer_remap=retry_viewer_remap,
                    )
                finally:
                    self._api_call_owner_thread = previous_owner

        quiet_result_codes = {int(code) for code in (quiet_result_codes or set())}
        sensitive_endpoints = {
            'single_mode_free/exec_command',
            'single_mode_free/gain_skills',
            'single_mode_free/multi_item_use',
            'single_mode_free/multi_item_exchange',
            'single_mode_free/race_entry',
            'single_mode_free/race_start',
            'single_mode_free/race_end',
            'single_mode_free/race_out',
            'single_mode_free/continue',
            'single_mode_free/change_running_style',
            'single_mode_free/check_event',
            'single_mode_free/load',
            'item/exchange',
            'item/use_recovery_item',
            'user/recovery_trainer_point',
            'support_card/limit_break',
            'support_card/limit_break_item',
        }
        sensitive_min_gaps = {
            'single_mode_free/gain_skills': 0.9,
            'single_mode_free/multi_item_exchange': 1.2,
            'single_mode_free/multi_item_use': 0.9,
            'single_mode_free/continue': 1.2,
            'single_mode_free/finish': 2.5,
            'single_mode_free/race_entry': 0.6,
            'single_mode_free/race_start': 0.6,
            'single_mode_free/race_end': 0.6,
            'single_mode_free/race_out': 0.6,
            'item/exchange': 0.6,
            'support_card/limit_break': 0.6,
            'support_card/limit_break_item': 0.6,
        }
        if retry_http_403 is None:
            retry_http_403 = 2 if ep == 'single_mode_free/finish' else (1 if ep in sensitive_endpoints else 0)

        if ep in sensitive_endpoints:
            if not hasattr(self, '_last_sensitive_call_ts'):
                self._last_sensitive_call_ts = 0
            if not hasattr(self, '_last_endpoint_call_ts'):
                self._last_endpoint_call_ts = {}
            now = time.time()
            general_gap = 0.35
            endpoint_gap = sensitive_min_gaps.get(ep, general_gap)
            elapsed_general = now - self._last_sensitive_call_ts
            elapsed_endpoint = now - float(self._last_endpoint_call_ts.get(ep, 0) or 0)
            wait_for = max(general_gap - elapsed_general, endpoint_gap - elapsed_endpoint, 0)
            if wait_for > 0:
                time.sleep(wait_for)
            stamp = time.time()
            self._last_sensitive_call_ts = stamp
            self._last_endpoint_call_ts[ep] = stamp

        req_id = str(uuid.uuid4())[:8]
        request_payload = copy.deepcopy(args or {})
        payload = copy.deepcopy(args or {})
        payload.update(self.common())
        body = pack(self.sid, get_raw_udid(self.udid_str), self.auth_bytes(), payload, self.udid_str)
        headers = {
            'SID': self.sid.hex(), 'Device': '4', 'ViewerID': str(self.viewer_id),
            'APP-VER': self.app_ver, 'RES-VER': self.res_ver,
        }
        

        self.api_log("REQ", ep, {
            "payload": payload,
        }, req_id)
        
        max_retries = 3
        transient_http_statuses = {408, 425, 500, 502, 503, 504}
        for attempt in range(max_retries):
            try:
                resp = self.session.post(BASE_URL + ep, data=body, headers=headers, timeout=30)
                if resp.status_code in transient_http_statuses and attempt < max_retries - 1:
                    body_preview = resp.text[:500] if resp.text else ""
                    self.api_log("ERR", ep, {"http_status": resp.status_code, "body": body_preview, "retry": attempt + 1}, req_id)
                    cooldown = 0.8 + (attempt * 1.2)
                    print(f"HTTP {resp.status_code} on {ep}; retrying in {cooldown:.1f}s ({attempt+1}/{max_retries})")
                    time.sleep(cooldown)
                    continue
                break
            except Exception as e:
                print(f"[API] Request failed (attempt {attempt+1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(1.0)
                    continue
                self.api_log("ERR", ep, {"error": str(e)}, req_id)
                raise ApiCallError(
                    f'Network error on {ep}: {e}',
                    endpoint=ep,
                    request_payload=request_payload,
                    req_id=req_id,
                )

        if resp.status_code != 200:
            body_preview = resp.text[:500] if resp.text else ""
            self.api_log("ERR", ep, {"http_status": resp.status_code, "body": body_preview}, req_id)
            print(f"HTTP error on {ep}: status={resp.status_code} body={body_preview}")
            if resp.status_code in {403, 429} and retry_http_403 > 0 and ep in sensitive_endpoints:
                cooldown = random.uniform(8.0, 14.0)
                print(f"HTTP {resp.status_code} on {ep}; cooling down {cooldown:.1f}s and retrying ({retry_http_403} left)")
                time.sleep(cooldown)
                return self.call(
                    ep,
                    args,
                    retry_208=retry_208,
                    retry_205=retry_205,
                    quiet_result_codes=quiet_result_codes,
                    retry_http_403=retry_http_403 - 1,
                    retry_394=retry_394,
                    retry_viewer_remap=retry_viewer_remap,
                )
            raise ApiCallError(
                f'HTTP {resp.status_code} on {ep}: {body_preview}',
                endpoint=ep,
                request_payload=request_payload,
                response_text=resp.text,
                http_status=resp.status_code,
                req_id=req_id,
            )
            
        res = unpack(resp.text.strip(), self.udid_str)
        dh = res.get('data_headers', {})
        rc = dh.get('result_code', 0)
        
        self.api_log("RES", ep, res, req_id)
        if is_client_version_stale_response(ep, rc, res):
            # Try to auto-discover the new live versions by probing plausible
            # successors (res_ver + 100/+200/etc, app_ver patch/minor bumps).
            # Only attempt once per client instance to avoid recursion blowup.
            # On success, `attach_turn_delay` (in main.py) auto-persists the
            # discovered versions to dev_session.json for next startup.
            if not getattr(self, "_attempted_version_autodiscovery", False):
                self._attempted_version_autodiscovery = True
                original_app_ver = self.app_ver
                original_res_ver = self.res_ver
                store_url = str(((res or {}).get("data_headers") or {}).get("store_url") or "").strip()
                candidates = generate_version_candidates(
                    self.app_ver,
                    self.res_ver,
                    store_url=store_url,
                    steam_app_id=self.steam_app_id,
                )
                print(
                    f"VERSION AUTO-DISCOVERY: 204+store_url on {ep} with "
                    f"APP-VER={original_app_ver} RES-VER={original_res_ver}. "
                    f"Probing {len(candidates)} candidate(s).",
                    flush=True,
                )
                for idx, (cand_app, cand_res) in enumerate(candidates, 1):
                    self.app_ver = cand_app
                    self.res_ver = cand_res
                    self.update_headers()
                    print(
                        f"  [{idx}/{len(candidates)}] trying APP-VER={cand_app} "
                        f"RES-VER={cand_res}",
                        flush=True,
                    )
                    try:
                        # Small spacing between probes to avoid rate-limiting
                        time.sleep(1.0)
                        retry_res = self.call(
                            ep,
                            args,
                            retry_208=retry_208,
                            retry_205=retry_205,
                            quiet_result_codes=tuple(set(quiet_result_codes) | {204}),
                            retry_http_403=retry_http_403,
                            retry_394=retry_394,
                        )
                    except ApiCallError as inner:
                        # If the retry also got 204+store_url (or any other
                        # client-stale signal), keep probing. Other errors
                        # (auth, network) — abort discovery, the version
                        # likely isn't the actual issue.
                        if "API error 204" in str(inner) and "store_url" in str(inner):
                            continue
                        # Non-stale failure: revert and break
                        self.app_ver = original_app_ver
                        self.res_ver = original_res_ver
                        self.update_headers()
                        break
                    except Exception:
                        self.app_ver = original_app_ver
                        self.res_ver = original_res_ver
                        self.update_headers()
                        break
                    retry_dh = retry_res.get("data_headers") or {}
                    retry_rc = int(retry_dh.get("result_code") or 0)
                    if not is_client_version_stale_response(ep, retry_rc, retry_res):
                        accepted_app = str(getattr(self, "app_ver", cand_app) or cand_app)
                        accepted_res = str(
                            retry_dh.get("resource_version")
                            or getattr(self, "res_ver", cand_res)
                            or cand_res
                        )
                        self.app_ver = accepted_app
                        self.res_ver = accepted_res
                        self.update_headers()
                        print(
                            f"VERSION AUTO-DISCOVERY: success — APP-VER={accepted_app} "
                            f"RES-VER={accepted_res} accepted. "
                            f"Persisting for future login attempts.",
                            flush=True,
                        )
                        try:
                            write_client_version_cache(
                                accepted_app,
                                accepted_res,
                                unity_ver=self.unity_ver,
                                steam_app_id=self.steam_app_id,
                                source=f"auto_discovery:{ep}",
                                store_url=store_url,
                            )
                        except Exception:
                            pass
                        try:
                            cfg = getattr(self, "_sweepy_auth_config", None)
                            if isinstance(cfg, dict):
                                cfg["app_ver"] = accepted_app
                                cfg["res_ver"] = accepted_res
                                cfg["unity_ver"] = self.unity_ver
                                cfg["steam_app_id"] = self.steam_app_id
                                self._sweepy_auth_config = dict(cfg)
                        except Exception:
                            pass
                        return retry_res
                # Exhausted — restore original versions and surface error.
                self.app_ver = original_app_ver
                self.res_ver = original_res_ver
                self.update_headers()
                print(
                    "VERSION AUTO-DISCOVERY: no candidate worked. Falling "
                    "back to actionable error.",
                    flush=True,
                )
            err_msg = client_version_stale_api_message(ep, rc, res, self.app_ver, self.res_ver)
            if int(rc or 0) not in quiet_result_codes:
                print(err_msg)
            raise ApiCallError(
                err_msg,
                endpoint=ep,
                request_payload=request_payload,
                response_body=res,
                result_code=rc,
                response_code=res.get('response_code'),
                req_id=req_id,
            )

        # Viewer-id remapping is only safe on account/index endpoints. Rewriting
        # viewer_id in the middle of a career leaves auth_key/udid/ticket bound to
        # the old account and turns the next single_mode_free call into a 501/394
        # stale-session loop.
        safe_viewer_remap_endpoints = {
            'load/index',
            'read_info/index',
        }
        try:
            response_viewer_id = int((dh.get('viewer_id') or 0))
        except (TypeError, ValueError):
            response_viewer_id = 0
        try:
            current_viewer_id = int(self.viewer_id or 0)
        except (TypeError, ValueError):
            current_viewer_id = 0
        viewer_id_mismatch = bool(
            response_viewer_id
            and current_viewer_id
            and response_viewer_id != current_viewer_id
        )

        start_endpoint = 'single_mode_free/start'
        if viewer_id_mismatch and rc == 1 and (ep in safe_viewer_remap_endpoints or ep == start_endpoint):
            print(f"VIEWER ID UPDATED on {ep}: {current_viewer_id} -> {response_viewer_id}")
            self.viewer_id = response_viewer_id
            self.regen_sid()

        if rc == 709:
            new_vid = dh.get('viewer_id') or res.get('data', {}).get('viewer_id')
            if new_vid and new_vid != self.viewer_id:
                print(f"VIEWER ID MISMATCH on 709: {self.viewer_id} -> {new_vid}")
                self.viewer_id = new_vid
                self.regen_sid()
            raise ApiCallError(
                f'709 on {ep}',
                endpoint=ep,
                request_payload=request_payload,
                response_body=res,
                result_code=709,
                response_code=res.get('response_code'),
                req_id=req_id,
            )
        if rc == 214:
            # Server is rejecting the request because RES-VER is stale. The response's
            # data_headers carry the resource_version the server expects ("10006000"
            # style). Pick it up and retry once — the next call's RES-VER header is
            # built from self.res_ver, so updating it is enough.
            server_res_ver = str(dh.get('resource_version') or '').strip()
            if server_res_ver and server_res_ver != self.res_ver:
                print(f"RES-VER MISMATCH on 214: {self.res_ver} -> {server_res_ver} (server-provided), retrying")
                self.res_ver = server_res_ver
                try:
                    write_client_version_cache(
                        self.app_ver,
                        self.res_ver,
                        unity_ver=self.unity_ver,
                        steam_app_id=self.steam_app_id,
                        source=f"server_214:{ep}",
                    )
                except Exception:
                    pass
                return self.call(
                    ep,
                    args,
                    retry_208=retry_208,
                    retry_205=retry_205,
                    quiet_result_codes=quiet_result_codes,
                    retry_http_403=retry_http_403,
                    retry_394=retry_394,
                )
            # If the server didn't tell us a usable version, fall through to the normal
            # error path so it surfaces in the UI instead of looping silently.
        if rc == 394 and ep == 'load/index' and retry_394 > 0:
            new_vid = dh.get('viewer_id') or res.get('data', {}).get('viewer_id')
            try:
                new_vid = int(new_vid or 0)
            except (TypeError, ValueError):
                new_vid = 0
            try:
                current_vid = int(self.viewer_id or 0)
            except (TypeError, ValueError):
                current_vid = 0
            if new_vid and new_vid != current_vid:
                print(f"VIEWER ID MISMATCH on 394 load/index: {current_vid} -> {new_vid}; retrying with server-provided viewer_id")
                self.viewer_id = new_vid
                self.regen_sid()
                return self.call(
                    ep,
                    args,
                    retry_208=retry_208,
                    retry_205=retry_205,
                    quiet_result_codes=quiet_result_codes,
                    retry_http_403=retry_http_403,
                    retry_394=retry_394 - 1,
                    retry_viewer_remap=retry_viewer_remap,
                )
        viewer_remap_retry_codes = {391, 394}
        if viewer_id_mismatch and ep in safe_viewer_remap_endpoints and rc in viewer_remap_retry_codes and retry_viewer_remap > 0:
            print(f"VIEWER ID MISMATCH on {rc} {ep}: {current_viewer_id} -> {response_viewer_id}; retrying with server-provided viewer_id")
            self.viewer_id = response_viewer_id
            self.regen_sid()
            return self.call(
                ep,
                args,
                retry_208=retry_208,
                retry_205=retry_205,
                quiet_result_codes=quiet_result_codes,
                retry_http_403=retry_http_403,
                retry_394=retry_394,
                retry_viewer_remap=retry_viewer_remap - 1,
            )
        # single_mode_free/start may adopt a server-provided viewer_id, but ONLY
        # for genuine "wrong viewer, use this one" codes — NOT for stale-session
        # codes. Per the safe_viewer_remap_endpoints comment above, remapping
        # viewer_id on a career endpoint without re-binding auth_key/udid/ticket
        # turns the next start into a 501/394 stale-session LOOP. Observed
        # 2026-06-13: a 102/501 on start triggered a remap-and-retry that then
        # 501-looped until a full auth refresh recovered. So 102/394/501 are
        # excluded here; a session mismatch on those falls through to the
        # recoverable-session-error path (which does a full reusable-auth
        # refresh — the recovery that actually re-binds auth to the right viewer).
        if viewer_id_mismatch and ep == start_endpoint and rc != 1:
            print(
                f"VIEWER ID MISMATCH on {rc} {ep}: {current_viewer_id} -> {response_viewer_id}; "
                "not remapping a career-start request; full session recovery is required",
                flush=True,
            )
        if rc != 1:
            if rc == 205 and retry_205 > 0:
                print(f"205 on {ep}, retrying in 0.5s... ({retry_205} left)")
                time.sleep(0.5)
                return self.call(
                    ep,
                    args,
                    retry_208=retry_208,
                    retry_205=retry_205 - 1,
                    quiet_result_codes=quiet_result_codes,
                    retry_http_403=retry_http_403,
                    retry_394=retry_394,
                    retry_viewer_remap=retry_viewer_remap,
                )

            if rc == 208 and retry_208 > 0:
                if retry_208 < 6:
                    print(f"API error 208 (DOUBLE_CLICK_ERROR) on {ep}, sleeping and retrying... (attempts left: {retry_208-1})")
                time.sleep(random.uniform(0.5, 1.0))
                return self.call(
                    ep,
                    args,
                    retry_208=retry_208 - 1,
                    retry_205=retry_205,
                    quiet_result_codes=quiet_result_codes,
                    retry_http_403=retry_http_403,
                    retry_394=retry_394,
                    retry_viewer_remap=retry_viewer_remap,
                )

            err_detail = format_api_error(ep, rc, res)
            err_msg = f'API error {rc} on {ep}: {err_detail}'
            if int(rc or 0) not in quiet_result_codes:
                print(err_msg)
            raise ApiCallError(
                err_msg,
                endpoint=ep,
                request_payload=request_payload,
                response_body=res,
                result_code=rc,
                response_code=res.get('response_code'),
                req_id=req_id,
            )
        if dh.get('sid') and isinstance(dh['sid'], str) and dh['sid'].strip():
            self.sid = next_sid(dh['sid'])
        
        return res

    def hard_reset(self):
        print("!!! Executing HARD RESET...")
        self.sid = bytes(16)
        self.regen_sid()
        self.session.close()
        self.session = requests.Session()
        self.update_headers()
        try:
            self.call('tool/start_session', {'attestation_type': 0, 'device_token': None})
            res = self.call('load/index', {
                'adid': ''
            })
            data = res.get('data', {})
            self.refresh_cached_account_state(data)
            # Optional home-screen fetch — a transient state code (e.g. 201)
            # must not abort the hard reset; the chara check below is what
            # actually validates recovery.
            try:
                self.read_info()
            except Exception as read_info_exc:
                print(f"read_info/index skipped during hard reset (non-fatal): {read_info_exc}", flush=True)

            try:
                sm_res = self.call('single_mode_free/load', {})
                chara = sm_res.get('data', {}).get('chara_info')
                if not chara:
                    raise StateRecoveryError("No chara_info returned in single_mode_free/load after hard reset.")
            except Exception as e:
                if isinstance(e, StateRecoveryError):
                    raise
                if "API error 201" in str(e) or "API error 102" in str(e):
                    raise StateRecoveryError(f"Cannot recover training state: {e}")
                print(f"single_mode_free/load during hard_reset failed: {e}")

            return res
        except StateRecoveryError:
            raise
        except Exception as e:
            print(f"Hard Reset Failure: {e}")
            raise

    def signup(self):
        self.regen_sid()
        pre = self.call('tool/pre_signup')
        time.sleep(1)
        self.regen_sid()
        country = 'Canada'
        try:
            country_rows = ((pre or {}).get('data') or {}).get('country_list') or []
            preferred = next((row for row in country_rows if int(row.get('country_type') or 0) == 2 and row.get('country')), None)
            if preferred:
                country = str(preferred.get('country') or country)
            elif country_rows and country_rows[0].get('country'):
                country = str(country_rows[0].get('country') or country)
        except Exception:
            pass
        res = self.call('tool/signup', {
            'error_code': 0, 'error_message': '', 'attestation_type': 0, 
            'optin_user_birth': 199801, 'dma_state': 0, 'country': country, 'credential': ''
        })
        d = res.get('data', {})
        if d.get('viewer_id'): 
            self.viewer_id = d['viewer_id']
        if d.get('auth_key'): self.auth_key_hex = base64.b64decode(d['auth_key']).hex()
        self.save_config()
        return res

    def login(self, max_retries=3):
        using_existing_auth = self.has_captured_auth()
        if not using_existing_auth:
            self.signup()
            using_existing_auth = self.has_captured_auth()

        old_h = dict(self.session.headers)
        self.session.close()
        self.session = requests.Session()
        self.session.headers.update(old_h)

        for attempt in range(max_retries + 1):
            try:
                self.regen_sid()
                self.call(
                    'tool/start_session',
                    {'attestation_type': 0, 'device_token': None},
                    quiet_result_codes={394, 501},
                )
                res = self.call('load/index', {'adid': ''})
                data = res.get('data', {})
                self.refresh_cached_account_state(data)
                # read_info/index only fetches optional home-screen data
                # (stories/episodes/posters/tutorial) and its result is unused
                # — the session is already established by load/index above. A
                # transient state code here (e.g. 201) must NOT abort an
                # otherwise successful login; that previously logged the user
                # out on dev session restore. Genuine auth failures would have
                # surfaced on tool/start_session or load/index already.
                try:
                    self.read_info()
                except Exception as read_info_exc:
                    print(f"read_info/index skipped (non-fatal; session already established): {read_info_exc}", flush=True)
                return res
            except Exception as e:
                err = str(e)
                if is_terminal_start_session_auth_error(e):
                    raise
                if '709' in err and attempt < max_retries:
                    time.sleep(1)
                    continue
                if '394' in err and attempt < max_retries:
                    time.sleep(3)
                    continue
                if '202' in err and attempt < max_retries:
                    time.sleep(5)
                    continue
                if '501' in err and attempt < max_retries:
                    time.sleep(3)
                    continue
                raise

    def read_info(self):
        # 102/201 here mean the optional home-screen payload isn't available
        # right now; quiet them so the console doesn't show a scary
        # "API error 201 on read_info/index" line. (quiet_result_codes only
        # suppresses the print — the call still raises — so callers that must
        # not abort on this still need to guard the call; see login().)
        return self.call('read_info/index', {
            'add_home_story_data_array': [],
            'add_short_episode_data_array': [],
            'add_home_poster_data_array': [],
            'add_tutorial_guide_data_array': [],
            'add_released_episode_data_array': [],
        }, quiet_result_codes={102, 201})

    def finish_career(self, current_turn=0, is_force_delete=False):
        return self.call('single_mode_free/finish', {
            'is_force_delete': is_force_delete,
            'current_turn': current_turn
        })

    def delete_career(self, current_turn=0):
        return self.call('single_mode_free/delete', {
            'is_force_delete': True,
            'current_turn': current_turn
        })

    def load_career(self, quiet_no_career=False):
        quiet_codes = {102, 201} if quiet_no_career else None
        return self.call('single_mode_free/load', {}, quiet_result_codes=quiet_codes)

    def minigame_end(self, current_turn, result_state=1, result_value=0, result_detail_array=None):
        return self.call('single_mode_free/minigame_end', {
            'result': {
                'result_state': result_state,
                'result_value': result_value,
                'result_detail_array': result_detail_array,
            },
            'current_turn': current_turn,
        })
    
    def save_config(self, cfg_path=None):
        global LAST_SAVED_CONFIG
        LAST_SAVED_CONFIG = {
            "viewer_id": self.viewer_id,
            "udid": self.udid_str,
            "auth_key": self.auth_key_hex,
            "steam_id": self.steam_id,
            "steam_session_ticket": self.steam_ticket,
            "steam_app_id": self.steam_app_id,
            "device_id": self.device_id,
            "device_identity_mode": self.device_identity_mode,
            "device_identity_instance": self.device_identity_instance,
            "device_name": self.device_name,
            "graphics_device_name": self.graphics_device,
            "ip_address": self.ip_address,
            "platform_os_version": self.platform_os,
            "locale": self.locale,
            "unity_ver": self.unity_ver,
            "app_ver": self.app_ver,
            "res_ver": self.res_ver,
        }

    def pre_single_mode(self, exclude_viewer_ids=None):
        payload = {}
        if exclude_viewer_ids:
            payload['exclude_viewer_id_array'] = exclude_viewer_ids
        return self.call('pre_single_mode/index', payload)

    def friend_index(self):
        return self.call('friend/index', {})

    def _call_payload_variants(self, endpoint, payload_variants, *, quiet_result_codes=()):
        errors = []
        variant_attempts = []
        last_api_error = None
        for payload in payload_variants:
            try:
                result = self.call(endpoint, payload, quiet_result_codes=quiet_result_codes)
                if isinstance(result, dict):
                    result = dict(result)
                    result["_sweepy_payload_variant"] = copy.deepcopy(payload)
                    result["_sweepy_variant_attempts"] = copy.deepcopy(variant_attempts)
                return result
            except ApiCallError as exc:
                last_api_error = exc
                variant_attempts.append({
                    "payload": copy.deepcopy(payload),
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                    "endpoint": getattr(exc, "endpoint", endpoint),
                    "result_code": getattr(exc, "result_code", None),
                    "response_code": getattr(exc, "response_code", None),
                    "http_status": getattr(exc, "http_status", None),
                    "req_id": getattr(exc, "req_id", None),
                    "request_payload": copy.deepcopy(getattr(exc, "request_payload", None)),
                    "response_body": copy.deepcopy(getattr(exc, "response_body", None)),
                    "response_text": getattr(exc, "response_text", None),
                })
                errors.append(f"{payload}: {exc}")
            except Exception as exc:
                variant_attempts.append({
                    "payload": copy.deepcopy(payload),
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                })
                errors.append(f"{payload}: {exc}")
        if last_api_error:
            raise ApiCallError(
                f"{endpoint} failed for all known payload variants: {' | '.join(errors)}",
                endpoint=endpoint,
                request_payload={
                    "payload_variants": copy.deepcopy(payload_variants),
                    "variant_attempts": copy.deepcopy(variant_attempts),
                },
                response_body={
                    "variant_attempts": copy.deepcopy(variant_attempts),
                    "last_response_body": copy.deepcopy(getattr(last_api_error, "response_body", None)),
                },
                response_text=getattr(last_api_error, "response_text", None),
                http_status=getattr(last_api_error, "http_status", None),
                result_code=getattr(last_api_error, "result_code", None),
                response_code=getattr(last_api_error, "response_code", None),
                req_id=getattr(last_api_error, "req_id", None),
            )
        raise Exception(f"{endpoint} failed for all known payload variants: {' | '.join(errors)}")

    def friend_search(self, trainer_id):
        trainer_id = int(trainer_id or 0)
        if trainer_id <= 0:
            raise ValueError("trainer_id must be a positive integer")
        return self._call_payload_variants("friend/search", [
            {"trainer_id": trainer_id},
            {"friend_viewer_id": trainer_id},
        ], quiet_result_codes={102})

    def friend_follow(self, friend_viewer_id):
        friend_viewer_id = int(friend_viewer_id or 0)
        if friend_viewer_id <= 0:
            raise ValueError("friend_viewer_id must be a positive integer")
        return self._call_payload_variants("friend/follow", [
            {"friend_viewer_id": friend_viewer_id},
            {"trainer_id": friend_viewer_id},
        ])

    def friend_unfollow(self, friend_viewer_id):
        friend_viewer_id = int(friend_viewer_id or 0)
        if friend_viewer_id <= 0:
            raise ValueError("friend_viewer_id must be a positive integer")
        return self._call_payload_variants("friend/un_follow", [
            {"friend_viewer_id": friend_viewer_id},
            {"trainer_id": friend_viewer_id},
        ])

    @staticmethod
    def build_start_payload(card_id, support_card_ids, friend_viewer_id, friend_card_id,
                            parent_id_1, parent_id_2, scenario_id=4, deck_id=1, use_tp=30,
                            tp_info=None, current_money=0, succession_rank_point=0,
                            rental_viewer_id=0, rental_trained_chara_id=0,
                            difficulty_id=0, difficulty=0, is_boost=0,
                            boost_story_event_id=0, allow_recover_tp=0,
                            include_empty_optional_blocks=False):
        if not tp_info:
            tp_info = {'current_tp': 100, 'max_tp': 100, 'max_recovery_time': 0}
        try:
            difficulty_id_int = int(difficulty_id or 0)
        except (TypeError, ValueError):
            difficulty_id_int = 0
        try:
            difficulty_int = int(difficulty or 0)
        except (TypeError, ValueError):
            difficulty_int = 0
        try:
            is_boost_int = int(is_boost or 0)
        except (TypeError, ValueError):
            is_boost_int = 0
        try:
            boost_story_event_id_int = int(boost_story_event_id or 0)
        except (TypeError, ValueError):
            boost_story_event_id_int = 0
        try:
            rental_viewer_id_int = int(rental_viewer_id or 0)
        except (TypeError, ValueError):
            rental_viewer_id_int = 0
        try:
            rental_trained_chara_id_int = int(rental_trained_chara_id or 0)
        except (TypeError, ValueError):
            rental_trained_chara_id_int = 0
        start_chara = {
            'card_id': card_id,
            'support_card_ids': support_card_ids,
            'friend_support_card_info': {
                'viewer_id': friend_viewer_id,
                'support_card_id': friend_card_id
            },
            'succession_trained_chara_id_1': parent_id_1,
            'succession_trained_chara_id_2': parent_id_2,
            'scenario_id': scenario_id,
            'select_deck_id': deck_id,
            'is_play_training_challenge': False
        }
        if include_empty_optional_blocks or (rental_viewer_id_int > 0 and rental_trained_chara_id_int > 0):
            start_chara['rental_succession_trained_chara'] = {
                'viewer_id': rental_viewer_id_int,
                'trained_chara_id': rental_trained_chara_id_int,
                'is_circle_member': False,
                'is_event_rental': False
            }
        if include_empty_optional_blocks or difficulty_id_int > 0 or difficulty_int > 0 or is_boost_int > 0:
            start_chara['selected_difficulty_info'] = {
                'difficulty_id': difficulty_id_int,
                'difficulty': difficulty_int,
                'is_boost': is_boost_int
            }
        if include_empty_optional_blocks or boost_story_event_id_int > 0:
            start_chara['boost_story_event_id'] = boost_story_event_id_int
        start_payload = {
            'start_chara': start_chara,
            'tp_info': tp_info,
            'current_money': current_money,
            'use_tp': use_tp,
            'current_succession_rank_point': succession_rank_point
        }
        if int(allow_recover_tp or 0) > 0:
            start_payload['allow_recover_tp'] = True
        return start_payload

    @staticmethod
    def _start_payload_has_showtime_boost(payload):
        start_chara = (payload or {}).get('start_chara') or {}
        selected = start_chara.get('selected_difficulty_info') or {}
        try:
            is_boost = int(selected.get('is_boost') or 0)
        except (TypeError, ValueError):
            is_boost = 0
        try:
            boost_story_event_id = int(start_chara.get('boost_story_event_id') or 0)
        except (TypeError, ValueError):
            boost_story_event_id = 0
        return is_boost > 0 or boost_story_event_id > 0

    def _api_error_viewer_mismatch(self, exc):
        response_viewer_id = api_error_response_viewer_id(exc)
        try:
            current_viewer_id = int(getattr(self, "viewer_id", 0) or 0)
        except (TypeError, ValueError):
            current_viewer_id = 0
        return bool(response_viewer_id and current_viewer_id and response_viewer_id != current_viewer_id)

    def start_career(self, card_id, support_card_ids, friend_viewer_id, friend_card_id,
                     parent_id_1, parent_id_2, scenario_id=4, deck_id=1, use_tp=30,
                     tp_info=None, current_money=0, succession_rank_point=0,
                     rental_viewer_id=0, rental_trained_chara_id=0,
                     difficulty_id=0, difficulty=0, is_boost=0,
                     boost_story_event_id=0, allow_recover_tp=0,
                     difficulty_candidates=None):
        def make_payload(diff_id, diff, boost, boost_event, *, include_empty_optional_blocks=False):
            return self.build_start_payload(
                card_id=card_id,
                support_card_ids=support_card_ids,
                friend_viewer_id=friend_viewer_id,
                friend_card_id=friend_card_id,
                parent_id_1=parent_id_1,
                parent_id_2=parent_id_2,
                scenario_id=scenario_id,
                deck_id=deck_id,
                use_tp=use_tp,
                tp_info=tp_info,
                current_money=current_money,
                succession_rank_point=succession_rank_point,
                rental_viewer_id=rental_viewer_id,
                rental_trained_chara_id=rental_trained_chara_id,
                difficulty_id=diff_id,
                difficulty=diff,
                is_boost=boost,
                boost_story_event_id=boost_event,
                allow_recover_tp=allow_recover_tp,
                include_empty_optional_blocks=include_empty_optional_blocks,
            )

        attempts = []
        seen = set()

        def append_attempt(payload):
            key = json.dumps(payload, sort_keys=True, default=str)
            if key in seen:
                return
            seen.add(key)
            attempts.append(payload)

        candidate_rows = list(difficulty_candidates or [])
        if candidate_rows:
            for row in candidate_rows:
                try:
                    candidate_id = int((row or {}).get("difficulty_id") or 0)
                    candidate_difficulty = int((row or {}).get("difficulty") or 0)
                    candidate_boost = int((row or {}).get("is_boost") or 0)
                    candidate_boost_event = int((row or {}).get("boost_story_event_id") or 0)
                except (TypeError, ValueError):
                    continue
                append_attempt(make_payload(
                    candidate_id,
                    candidate_difficulty,
                    candidate_boost,
                    candidate_boost_event,
                ))
                if candidate_boost > 0 or candidate_boost_event > 0:
                    append_attempt(make_payload(candidate_id, candidate_difficulty, 0, 0))

        start_payload = make_payload(difficulty_id, difficulty, is_boost, boost_story_event_id)
        append_attempt(start_payload)
        if self._start_payload_has_showtime_boost(start_payload):
            # Fuji/Showtime difficulty selection is independent from event boost
            # item usage. Some accounts have the difficulty open but no boost
            # item; sending is_boost=1 then makes start reject with 102/205.
            append_attempt(make_payload(difficulty_id, difficulty, 0, 0))

        fallback_payload = make_payload(
            difficulty_id,
            difficulty,
            0 if self._start_payload_has_showtime_boost(start_payload) else is_boost,
            0 if self._start_payload_has_showtime_boost(start_payload) else boost_story_event_id,
            include_empty_optional_blocks=True,
        )
        append_attempt(fallback_payload)
        if int(difficulty_id or 0) > 0 or int(difficulty or 0) > 0:
            append_attempt(make_payload(0, 0, 0, 0))
            append_attempt(make_payload(0, 0, 0, 0, include_empty_optional_blocks=True))

        last_exc = None
        for index, payload in enumerate(attempts):
            try:
                return self.call(
                    'single_mode_free/start',
                    payload,
                    retry_205=0,
                    quiet_result_codes={102, 205},
                )
            except ApiCallError as exc:
                last_exc = exc
                if self._api_error_viewer_mismatch(exc):
                    raise
                code = int(getattr(exc, "result_code", 0) or getattr(exc, "response_code", 0) or 0)
                if code not in {102, 205} or index >= len(attempts) - 1:
                    raise
                if self._start_payload_has_showtime_boost(payload):
                    print("single_mode_free/start rejected Showtime boost; retrying difficulty without boost item", flush=True)
                elif (payload.get("start_chara") or {}).get("selected_difficulty_info", {}).get("difficulty_id"):
                    selected = (payload.get("start_chara") or {}).get("selected_difficulty_info") or {}
                    print(
                        f"{code} on single_mode_free/start for Showtime "
                        f"{selected.get('difficulty_id')}:{selected.get('difficulty')}; retrying alternate start payload",
                        flush=True,
                    )
                elif int(difficulty_id or 0) > 0 or int(difficulty or 0) > 0:
                    print(
                        f"{code} on single_mode_free/start; all Showtime variants may be invalid, retrying normal career payload",
                        flush=True,
                    )
                else:
                    print(f"{code} on single_mode_free/start; retrying alternate start payload", flush=True)
        if last_exc:
            raise last_exc
        raise RuntimeError("single_mode_free/start did not execute")

    def exec_command(self, command_type, command_id, current_turn, current_vital, command_group_id=0, select_id=0):
        return self.call('single_mode_free/exec_command', {
            'command_type': command_type,
            'command_id': command_id,
            'command_group_id': command_group_id,
            'select_id': select_id,
            'current_turn': current_turn,
            'current_vital': current_vital
        })

    def check_event(self, event_id, chara_id=0, choice_number=0, current_turn=0):
        payload = {
            'event_id': event_id,
            'chara_id': chara_id or 0,
            'choice_number': choice_number if choice_number is not None else 0,
            'current_turn': current_turn
        }
        return self.call('single_mode_free/check_event', payload)

    def use_items(self, use_item_info_array, current_turn):
        return self.call('single_mode_free/multi_item_use', {
            'use_item_info_array': use_item_info_array,
            'current_turn': current_turn
        })

    def use_recovery_item(self, item_id=0, current_num=0):
        """Refill the home-screen Trainer Point gauge by consuming an inventory item
        (e.g. Toughness 30, item_id 32 → +30 TP). Payload shape was reverse-engineered
        from live game traffic: fields are flat, and the inventory count field is
        `client_own_num` (not `current_num`). Success response has result_code 1."""
        payload = {
            'item_id': int(item_id or 0),
            'item_num': 1,
            'client_own_num': int(current_num or 0),
        }
        return self.refresh_resource_state_from_response(self.call('item/use_recovery_item', payload))

    def recover_trainer_point(self, count=1, client_own_num=None):
        """Spend carats to refill the pre-career-start Trainer Point gauge.

        Live client traffic sends the number of refills plus the current total
        held carat count. An empty payload is accepted by the wrapper but
        rejected by the game server with result_code 102.
        """
        if client_own_num is None:
            coin_info = getattr(self, "coin_info", {}) or {}
            free_carats = int(coin_info.get("fcoin") or 0)
            paid_carats = int(coin_info.get("coin") or 0)
            client_own_num = free_carats + paid_carats
        return self.refresh_resource_state_from_response(self.call('user/recovery_trainer_point', {
            'count': int(count or 1),
            'client_own_num': int(client_own_num or 0),
        }))

    def limit_break_support_card(self, support_card_id, material_support_card_num=1):
        """Consume duplicate support-card stock for a live limit break.

        Reverse-engineered from game metadata:
        `support_card/limit_break` takes the target `support_card_id` and a
        `material_support_card_num` count for duplicate-card consumption.
        """
        return self.call('support_card/limit_break', {
            'support_card_id': int(support_card_id or 0),
            'material_support_card_num': int(material_support_card_num or 1),
        })

    def limit_break_support_card_with_item(self, support_card_id, limit_break_item_id, limit_break_count=1):
        """Consume explicit limit-break items (rainbow/gold) for a support card."""
        return self.call('support_card/limit_break_item', {
            'support_card_id': int(support_card_id or 0),
            'limit_break_item_id': int(limit_break_item_id or 0),
            'limit_break_count': int(limit_break_count or 1),
        })

    def exchange_item(self, exchange_id, count=1, current_num=None, get_list_time=""):
        """Exchange shop/currency resources outside a career shop.

        Live alarm-clock carat exchange traffic uses exchange_id=9001, count=1,
        current_num=<current total carats>, get_list_time=""; the response adds
        item_id 95 and returns updated coin_info.
        """
        if current_num is None:
            coin_info = getattr(self, "coin_info", {}) or {}
            current_num = int(coin_info.get("fcoin") or 0) + int(coin_info.get("coin") or 0)
        return self.refresh_resource_state_from_response(self.call('item/exchange', {
            'exchange_id': int(exchange_id or 0),
            'count': int(count or 1),
            'current_num': int(current_num or 0),
            'get_list_time': get_list_time or "",
        }))

    def change_running_style(self, program_id, running_style, current_turn):
        """Set the chara's race tactic for an upcoming race. running_style integers:
        1=front_runner, 2=pace_chaser, 3=late_surger, 4=end_closer (matches the
        TACTIC_TO_STYLE map in career_bot/race_schedule.py)."""
        return self.call('single_mode_free/change_running_style', {
            'program_id': int(program_id or 0),
            'running_style': int(running_style or 0),
            'current_turn': int(current_turn or 0),
        })

    def exchange_items(self, exchange_item_info_array, current_turn, **call_kwargs):
        return self.call('single_mode_free/multi_item_exchange', {
            'exchange_item_info_array': exchange_item_info_array,
            'current_turn': current_turn
        }, **call_kwargs)

    def gain_skills(self, gain_skill_info_array, current_turn, **call_kwargs):
        gain_skill_info_array = [
            {
                "skill_id": item.get("skill_id"),
                "level": item.get("level", item.get("skill_level", 1)),
            }
            for item in gain_skill_info_array
        ]
        return self.call('single_mode_free/gain_skills', {
            'gain_skill_info_array': gain_skill_info_array,
            'current_turn': current_turn
        }, **call_kwargs)

    def race_entry(self, program_id, current_turn):
        # Tight retry budget: retrying a 208 (DOUBLE_CLICK_ERROR) immediately is what the
        # server is complaining about — better to fail once and let the runner reject the
        # race cleanly. One 205 retry covers genuine transient sync errors.
        return self.call('single_mode_free/race_entry', {
            'program_id': program_id,
            'current_turn': current_turn
        }, retry_208=0, retry_205=1)

    def race_start(self, is_short, current_turn):
        return self.call('single_mode_free/race_start', {
            'is_short': is_short,
            'current_turn': current_turn
        }, quiet_result_codes={2502})

    def race_end(self, current_turn):
        return self.call('single_mode_free/race_end', {
            'current_turn': current_turn
        }, quiet_result_codes={2502})

    def race_out(self, current_turn):
        return self.call('single_mode_free/race_out', {
            'current_turn': current_turn
        })

    def race_continue(self, current_turn, continue_type):
        # The runner logs continue rejects with race context. Suppress raw
        # client prints for expected probe/state failures so the terminal is
        # not flooded when winning races reject speculative pre-end probes.
        return self.call('single_mode_free/continue', {
            'current_turn': current_turn,
            'continue_type': continue_type
        }, retry_208=0, retry_205=0, quiet_result_codes={205, 500, 1801, 1802})

    def reserve_race(self, current_turn, add_race_array=None, cancel_race_array=None):
        return self.call('single_mode_free/reserve_race', {
            'current_turn': current_turn,
            'add_race_array': add_race_array or [],
            'cancel_race_array': cancel_race_array or []
        })
