"""
Sweepy packet sniffer — self-contained mitmproxy addon that decrypts the real
game client's Umamusume API traffic (AES-256-CBC + msgpack), so the bot no
longer depends on the external trial-project sniffer.

WHY this exists: some client-side selections (a borrowed parent, the Fuji/
Showtime difficulty) send NO packet when clicked — the choice is held in the
client and only appears inside the `single_mode_free/start` REQUEST body. The
bot is a direct API client, so it can only see its own (failing) calls. This
proxy sits between the real game client and the server and captures what the
*client* actually sends, which is the only way to recover the true encoding.

Crypto is a verbatim port of the trial-project sniffer (itself reimplementing
umazing-musumengine in pure Python). Only msgpack + pycryptodome are needed and
both are already in sweepy's requirements; the one extra dependency is
mitmproxy (see requirements-sniffer.txt — install only if you use this).

Setup (one time):
  1. pip install -r requirements-sniffer.txt        (mitmproxy==11.0.2)
  2. Trust the mitmproxy CA cert (~/.mitmproxy/mitmproxy-ca-cert). If you have
     run the trial-project sniffer before, it is already trusted.
  3. Point your game client / emulator proxy at  127.0.0.1:8877  (the default —
     the SAME port the old sniffer used, so stop that one first; you cannot run
     two interceptors on the same client at once).

Run (standalone, independent of the FastAPI backend so backend restarts never
drop the game's connection):
  python -m uma_api.packet_sniffer

Captures land in  uma_runtime/packet_captures/<endpoint>_latest.json  (+ a
_history.jsonl), each holding the decoded REQUEST and RESPONSE. For the Fuji
difficulty, read:
  uma_runtime/packet_captures/single_mode_free_start_latest.json
      -> request.start_chara.selected_difficulty_info   (the real encoding)
"""

import asyncio
import base64
import json
import logging
import os
import struct
import threading
import time
from collections import OrderedDict
from pathlib import Path

import msgpack
from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

log = logging.getLogger("sweepy.packet_sniffer")

# -- Config -------------------------------------------------------------------

GAME_API_HOSTS = (
    "api.games.umamusume.com",
    "games.umamusume.com",
    "api-pf-umamusume",
    "umamusume",
)
PROXY_PORT = int(os.getenv("SWEEPY_SNIFFER_PORT", "8877"))
CAPTURE_DIR = Path(
    os.getenv("SWEEPY_SNIFFER_OUT")
    or (Path(__file__).resolve().parent.parent / "uma_runtime" / "packet_captures")
)
_REQUEST_CACHE_MAX = max(32, int(os.getenv("SWEEPY_SNIFFER_REQUEST_CACHE_MAX", "128")))
_REQUEST_CACHE_TTL_S = max(5.0, float(os.getenv("SWEEPY_SNIFFER_REQUEST_CACHE_TTL_S", "15.0")))

# -- Crypto constants (umazing-musumengine, via trial-project) -----------------

SESSION_ID_BYTES = 16
UDID_RAW_BYTES = 16
RESPONSE_KEY_BYTES = 32
AUTH_KEY_BYTES = 48

# -- Pure Python decrypt (verbatim port; must match the wire format exactly) ---

def _maybe_decode_transport_blob(raw: bytes) -> bytes:
    if not isinstance(raw, (bytes, bytearray)):
        return raw
    data = bytes(raw).strip()
    if len(data) < 16:
        return bytes(raw)
    sample = data[: min(len(data), 256)]
    if all((48 <= b <= 57) or (65 <= b <= 90) or (97 <= b <= 122) or b in (43, 47, 61, 45, 95, 10, 13) for b in sample):
        compact = b"".join(data.split())
        if compact:
            pad = (-len(compact)) % 4
            if pad:
                compact += b"=" * pad
            try:
                decoded = base64.b64decode(compact, validate=False)
                if decoded and decoded != data:
                    return decoded
            except Exception:
                pass
    return bytes(raw)


def _udid_raw_to_string(udid_raw: bytes) -> str:
    h = udid_raw.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


def _derive_iv(udid_string: str) -> bytes:
    clean = udid_string.replace("-", "").lower()[:16]
    if len(clean) != 16:
        raise ValueError(f"UDID too short for IV: {len(clean)} chars")
    return clean.encode("utf-8")


def _parse_request(raw: bytes) -> dict:
    """Wire format: [4B LE blob1_len][blob1][blob2]
    blob1 tail: [session_id(16)][udid_raw(16)][response_key(32)][auth_key(0|48)]
    blob2: [AES ciphertext][encryption_key(32)]
    """
    raw = _maybe_decode_transport_blob(raw)
    if len(raw) < 4:
        raise ValueError("Request too short: missing 4-byte length prefix")
    blob1_len = struct.unpack_from("<I", raw, 0)[0]
    if len(raw) < 4 + blob1_len:
        raise ValueError(f"Request too short for blob1: need {4 + blob1_len}, got {len(raw)}")
    blob1 = raw[4:4 + blob1_len]
    blob2 = raw[4 + blob1_len:]

    fixed_no_auth = SESSION_ID_BYTES + UDID_RAW_BYTES + RESPONSE_KEY_BYTES
    fixed_with_auth = fixed_no_auth + AUTH_KEY_BYTES
    has_auth = len(blob1) >= fixed_with_auth
    fixed = fixed_with_auth if has_auth else fixed_no_auth

    tail = blob1[len(blob1) - fixed:]
    offset = 0
    session_id = tail[offset:offset + SESSION_ID_BYTES]; offset += SESSION_ID_BYTES
    udid_raw = tail[offset:offset + UDID_RAW_BYTES]; offset += UDID_RAW_BYTES
    response_key = tail[offset:offset + RESPONSE_KEY_BYTES]; offset += RESPONSE_KEY_BYTES

    udid_string = _udid_raw_to_string(udid_raw)
    iv = _derive_iv(udid_string)
    return {
        "udid_string": udid_string,
        "iv": iv,
        "session_id": session_id,
        "response_key": response_key,
        "blob2": blob2,
    }


def _decrypt_blob2(blob2: bytes, iv: bytes) -> bytes:
    if len(blob2) < 32:
        raise ValueError(f"blob2 too short: need >=32 bytes, got {len(blob2)}")
    key = blob2[-32:]
    ciphertext = blob2[:-32]
    cipher = AES.new(key, AES.MODE_CBC, iv=iv)
    return unpad(cipher.decrypt(ciphertext), AES.block_size)


def _normalize_response(data: object) -> object:
    if isinstance(data, dict) and "data_headers" in data and "data" in data:
        return data
    if isinstance(data, dict) and "data" in data:
        headers = {k: v for k, v in data.items() if k != "data"}
        return {"data_headers": headers, "data": data["data"]}
    return data


def _unpack_msgpack(plaintext: bytes) -> object:
    if len(plaintext) >= 4:
        try:
            payload_len = struct.unpack_from("<I", plaintext, 0)[0]
            if 0 < payload_len <= len(plaintext) - 4:
                result = msgpack.unpackb(plaintext[4:4 + payload_len], raw=False, strict_map_key=False)
                return _normalize_response(result)
        except Exception:
            pass
    try:
        result = msgpack.unpackb(plaintext, raw=False, strict_map_key=False)
        return _normalize_response(result)
    except Exception:
        pass
    scan_range = min(256, len(plaintext))
    for off in range(scan_range):
        marker = plaintext[off]
        if (0x80 <= marker <= 0x8f) or marker in (0xde, 0xdf):
            try:
                result = msgpack.unpackb(plaintext[off:], raw=False, strict_map_key=False)
                if isinstance(result, dict) and len(result) >= 2:
                    return _normalize_response(result)
            except Exception:
                continue
    return {"_unparsed": True, "_raw_hex": plaintext[:200].hex()}


def decrypt_response(request_raw: bytes, response_raw: bytes) -> dict | None:
    try:
        req = _parse_request(request_raw)
        plaintext = _decrypt_blob2(_maybe_decode_transport_blob(response_raw), req["iv"])
        payload = _unpack_msgpack(plaintext)
        return payload if isinstance(payload, dict) else {"_payload": payload}
    except Exception as e:
        log.debug(f"[sniffer] response decrypt failed: {e}")
        return None


def decrypt_request(request_raw: bytes) -> dict | None:
    """Decode the OUTBOUND request body — where selected_difficulty_info /
    rental_succession_trained_chara live for single_mode_free/start."""
    try:
        req = _parse_request(request_raw)
        plaintext = _decrypt_blob2(req["blob2"], req["iv"])
        payload = _unpack_msgpack(plaintext)
        return payload if isinstance(payload, dict) else {"_payload": payload}
    except Exception as e:
        log.debug(f"[sniffer] request decrypt failed: {e}")
        return None


# -- Capture ------------------------------------------------------------------

def _slug(path: str) -> str:
    tail = (path or "").split("?", 1)[0].strip("/")
    tail = tail.split("/umamusume/", 1)[-1] if "/umamusume/" in (path or "") else tail
    return "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in tail) or "unknown"


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _capture(path: str, request_decoded, response_decoded, status: int) -> None:
    slug = _slug(path)
    captured_at = time.time()
    record = {
        "path": path,
        "status": status,
        "captured_at": captured_at,
        "request": request_decoded or None,
        "response": response_decoded or None,
        "response_top_level_keys": sorted(response_decoded.keys()) if isinstance(response_decoded, dict) else None,
    }
    try:
        _write_json(CAPTURE_DIR / f"{slug}_latest.json", record)
        _append_jsonl(CAPTURE_DIR / f"{slug}_history.jsonl", {
            "path": path, "status": status, "captured_at": captured_at,
            "has_request": request_decoded is not None,
        })
        log.info(f"[sniffer] captured {slug} -> {CAPTURE_DIR / (slug + '_latest.json')}")
    except Exception as exc:
        log.debug(f"[sniffer] capture write failed for {path}: {exc}")


# -- mitmproxy addon ----------------------------------------------------------

class UmamusumeAddon:
    """Captures + decrypts Umamusume API traffic flowing through the proxy."""

    def __init__(self):
        self._request_cache: "OrderedDict[int, dict]" = OrderedDict()

    def _is_game_host(self, host: str) -> bool:
        return any(h in host for h in GAME_API_HOSTS)

    def _prune(self, now: float) -> None:
        while self._request_cache:
            k = next(iter(self._request_cache))
            ts = float(self._request_cache[k].get("timestamp") or 0.0)
            if (now - ts) <= _REQUEST_CACHE_TTL_S and len(self._request_cache) <= _REQUEST_CACHE_MAX:
                break
            self._request_cache.pop(k, None)

    def request(self, flow) -> None:
        host = flow.request.pretty_host
        if not self._is_game_host(host):
            return
        raw = flow.request.raw_content
        if not raw:
            return
        now = time.time()
        self._prune(now)
        try:
            req = _parse_request(raw)
        except Exception:
            return
        self._request_cache[id(flow)] = {
            "timestamp": now,
            "iv": req.get("iv"),
            "request_raw": bytes(raw),
            "request_decoded": decrypt_request(raw),
            "path": flow.request.path,
        }

    def response(self, flow) -> None:
        host = flow.request.pretty_host
        if not self._is_game_host(host):
            return
        path = flow.request.path
        status = flow.response.status_code
        self._prune(time.time())
        req_ctx = self._request_cache.pop(id(flow), None)
        resp_raw = flow.response.raw_content
        if not req_ctx or not resp_raw:
            return
        log.info(f"[sniffer] {flow.request.method} {host}{path} -> {status} ({len(resp_raw)}B)")
        threading.Thread(target=self._process, args=(path, req_ctx, resp_raw, status), daemon=True).start()

    def _process(self, path: str, req_ctx: dict, resp_raw: bytes, status: int) -> None:
        response_decoded = None
        try:
            iv = req_ctx.get("iv")
            if iv:
                response_decoded = _unpack_msgpack(_decrypt_blob2(_maybe_decode_transport_blob(resp_raw), iv))
        except Exception as e:
            log.debug(f"[sniffer] response decrypt failed for {path}: {e}")
        _capture(path, req_ctx.get("request_decoded"), response_decoded, status)


# -- Launcher -----------------------------------------------------------------

_sniffer_thread = None
_sniffer_master = None
_running = threading.Event()


def _allow_host_patterns() -> list:
    # Only intercept Umamusume hosts; everything else tunnels through untouched.
    return [r"(^|\.)umamusume\.", r"umamusume"]


def _run_mitmproxy(port: int) -> None:
    global _sniffer_master
    loop = None
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        from mitmproxy.tools import dump
        from mitmproxy import options

        opts = options.Options(listen_host="0.0.0.0", listen_port=port)
        try:
            opts.allow_hosts = _allow_host_patterns()
        except Exception as e:
            log.debug(f"[sniffer] allow_hosts unsupported: {e}")
        _sniffer_master = dump.DumpMaster(opts, loop=loop, with_termlog=False, with_dumper=False)
        try:
            _sniffer_master.options.update(stream_large_bodies="256k", body_size_limit="8m")
        except Exception as e:
            log.debug(f"[sniffer] body limits not set: {e}")
        _sniffer_master.addons.add(UmamusumeAddon())
        log.info(f"[sniffer] mitmproxy listening on 0.0.0.0:{port} -> captures in {CAPTURE_DIR}")
        loop.run_until_complete(_sniffer_master.run())
    except Exception as e:
        log.error(f"[sniffer] mitmproxy failed: {e}")
    finally:
        _sniffer_master = None
        if loop is not None:
            try:
                loop.stop()
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass


def start_sniffer(port: int = PROXY_PORT) -> None:
    """Start the proxy in a background thread (for embedding)."""
    global _sniffer_thread
    if _sniffer_thread and _sniffer_thread.is_alive():
        log.info("[sniffer] already running")
        return
    _running.set()
    _sniffer_thread = threading.Thread(target=_run_mitmproxy, args=(port,), daemon=True, name="sweepy-packet-sniffer")
    _sniffer_thread.start()
    log.info(f"[sniffer] proxy started on port {port}")


def stop_sniffer() -> None:
    global _sniffer_master
    _running.clear()
    if _sniffer_master:
        try:
            _sniffer_master.shutdown()
        except Exception:
            pass
    log.info("[sniffer] stop requested")


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", stream=sys.stdout)
    print("=" * 64)
    print("  Sweepy Packet Sniffer (pure-Python decrypt)")
    print(f"  proxy : 127.0.0.1:{PROXY_PORT}   (point your game client here)")
    print(f"  out   : {CAPTURE_DIR}")
    print("  Fuji difficulty -> single_mode_free_start_latest.json")
    print("                     request.start_chara.selected_difficulty_info")
    print("=" * 64)
    try:
        from mitmproxy.tools import dump  # noqa: F401
    except Exception:
        print("\nmitmproxy is not installed. Run:  pip install -r requirements-sniffer.txt\n")
        sys.exit(1)
    start_sniffer(PROXY_PORT)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        stop_sniffer()
        print("\n[sniffer] stopped.")
