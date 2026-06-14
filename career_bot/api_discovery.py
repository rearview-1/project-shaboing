"""Structured API capture and diff helpers for unknown game features.

The low-level client trace already records sanitized request/response rows.
This module adds a higher-level, labeled workflow around those rows so a
single manual action can be promoted into a repeatable API contract without
copying packets by hand.
"""

from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "sweepy_api_discovery_v1"

COMMON_REQUEST_KEYS = {
    "adid",
    "auth_key",
    "button_info",
    "carrier",
    "device",
    "device_id",
    "device_name",
    "dmm_onetime_token",
    "dmm_viewer_id",
    "graphics_device_name",
    "ip_address",
    "keychain",
    "locale",
    "platform_os_version",
    "steam_id",
    "steam_session_ticket",
    "viewer_id",
}

SUSPICIOUS_KEY_PATTERNS = (
    "boost",
    "campaign",
    "difficulty",
    "event",
    "friend",
    "group",
    "legend",
    "race",
    "rental",
    "select",
    "showtime",
    "story",
    "succession",
)


def discovery_root(runtime_dir: str | Path) -> Path:
    root = Path(runtime_dir) / "api_discovery"
    root.mkdir(parents=True, exist_ok=True)
    return root


def slug_label(value: str, fallback: str = "capture") -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9._ -]+", "", text)
    text = re.sub(r"\s+", "_", text).strip("._-")
    return text or fallback


def capture_dir(runtime_dir: str | Path, label: str) -> Path:
    path = discovery_root(runtime_dir) / slug_label(label)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _json_default(value: Any) -> str:
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def _safe_read_json(path: Path, fallback: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")


def _value_preview(value: Any, max_len: int = 180) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True, default=_json_default)
        except Exception:
            text = str(value)
    if isinstance(text, str) and len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def extract_payload(row: dict[str, Any]) -> dict[str, Any]:
    data = row.get("data") if isinstance(row, dict) else {}
    if isinstance(data, dict) and isinstance(data.get("payload"), dict):
        payload = dict(data.get("payload") or {})
    elif isinstance(data, dict):
        payload = dict(data)
    else:
        payload = {}
    for key in list(payload.keys()):
        if key in COMMON_REQUEST_KEYS:
            payload.pop(key, None)
    return payload


def flatten_paths(value: Any, prefix: str = "", *, max_depth: int = 10, max_items: int = 2000) -> dict[str, Any]:
    out: dict[str, Any] = {}

    def walk(obj: Any, path: str, depth: int) -> None:
        if len(out) >= max_items:
            return
        if depth > max_depth:
            out[path or "$"] = "<max_depth>"
            return
        if isinstance(obj, dict):
            if not obj:
                out[path or "$"] = {}
            for key in sorted(obj.keys(), key=str):
                child = f"{path}.{key}" if path else str(key)
                walk(obj.get(key), child, depth + 1)
            return
        if isinstance(obj, list):
            if not obj:
                out[path or "$"] = []
                return
            for idx, item in enumerate(obj[:30]):
                walk(item, f"{path}[{idx}]", depth + 1)
            if len(obj) > 30:
                out[f"{path}[...]"] = f"{len(obj) - 30} more"
            return
        out[path or "$"] = _value_preview(obj)

    walk(value, prefix, 0)
    return out


def shape_summary(value: Any, *, max_depth: int = 4) -> Any:
    if max_depth < 0:
        return type(value).__name__
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in sorted(value.keys(), key=str)[:80]:
            child = value.get(key)
            if isinstance(child, list):
                result[str(key)] = f"list[{len(child)}]"
            elif isinstance(child, dict):
                result[str(key)] = shape_summary(child, max_depth=max_depth - 1)
            else:
                result[str(key)] = type(child).__name__
        if len(value) > 80:
            result["..."] = f"{len(value) - 80} more keys"
        return result
    if isinstance(value, list):
        if not value:
            return "list[0]"
        return {"list": len(value), "sample": shape_summary(value[0], max_depth=max_depth - 1)}
    return type(value).__name__


def find_suspicious_paths(value: Any) -> list[dict[str, Any]]:
    flat = flatten_paths(value, max_depth=12, max_items=5000)
    rows = []
    for path, val in flat.items():
        lower = path.lower()
        if any(pattern in lower for pattern in SUSPICIOUS_KEY_PATTERNS):
            rows.append({"path": path, "value": val})
    return rows[:300]


def load_capture_entries(runtime_dir: str | Path, label: str) -> list[dict[str, Any]]:
    path = capture_dir(runtime_dir, label) / "events.jsonl"
    if not path.exists():
        return []
    entries = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except Exception:
                continue
    return entries


def build_contract(entries: list[dict[str, Any]], *, label: str = "") -> dict[str, Any]:
    endpoint_counts: Counter[str] = Counter()
    direction_counts: Counter[str] = Counter()
    endpoint_direction_counts: Counter[str] = Counter()
    request_examples: dict[str, Any] = {}
    response_shapes: dict[str, Any] = {}
    suspicious: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in entries:
        endpoint = str(row.get("endpoint") or "")
        direction = str(row.get("direction") or "")
        if not endpoint:
            continue
        endpoint_counts[endpoint] += 1
        direction_counts[direction] += 1
        endpoint_direction_counts[f"{direction} {endpoint}".strip()] += 1
        data = row.get("data")
        if direction == "REQ" and endpoint not in request_examples:
            request_examples[endpoint] = extract_payload(row)
        if direction in {"RES", "ERR"} and endpoint not in response_shapes:
            response_shapes[endpoint] = shape_summary(data)
        for hit in find_suspicious_paths(data):
            bucket = suspicious[endpoint]
            if len(bucket) < 80:
                bucket.append(hit)

    return {
        "schema": SCHEMA_VERSION,
        "label": label,
        "entry_count": len(entries),
        "endpoint_counts": dict(endpoint_counts.most_common()),
        "direction_counts": dict(direction_counts.most_common()),
        "endpoint_direction_counts": dict(endpoint_direction_counts.most_common()),
        "request_examples": request_examples,
        "response_shapes": response_shapes,
        "suspicious_paths": dict(suspicious),
    }


def write_contract(runtime_dir: str | Path, label: str, entries: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    entries = entries if entries is not None else load_capture_entries(runtime_dir, label)
    contract = build_contract(entries, label=slug_label(label))
    _write_json(capture_dir(runtime_dir, label) / "contract.json", contract)
    return contract


def compare_payloads(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_flat = flatten_paths(left)
    right_flat = flatten_paths(right)
    left_keys = set(left_flat)
    right_keys = set(right_flat)
    changed = []
    for key in sorted(left_keys & right_keys):
        if left_flat[key] != right_flat[key]:
            changed.append({"path": key, "left": left_flat[key], "right": right_flat[key]})
    return {
        "changed": changed[:500],
        "only_left": [{"path": key, "value": left_flat[key]} for key in sorted(left_keys - right_keys)[:500]],
        "only_right": [{"path": key, "value": right_flat[key]} for key in sorted(right_keys - left_keys)[:500]],
    }


def _matching_rows(entries: list[dict[str, Any]], endpoint: str = "", direction: str = "REQ") -> list[dict[str, Any]]:
    rows = []
    for row in entries:
        if direction and str(row.get("direction") or "") != direction:
            continue
        if endpoint and str(row.get("endpoint") or "") != endpoint:
            continue
        rows.append(row)
    return rows


def compare_captures(
    runtime_dir: str | Path,
    left_label: str,
    right_label: str,
    *,
    endpoint: str = "",
    direction: str = "REQ",
) -> dict[str, Any]:
    left_entries = load_capture_entries(runtime_dir, left_label)
    right_entries = load_capture_entries(runtime_dir, right_label)
    left_rows = _matching_rows(left_entries, endpoint=endpoint, direction=direction)
    right_rows = _matching_rows(right_entries, endpoint=endpoint, direction=direction)
    left_row = left_rows[-1] if left_rows else {}
    right_row = right_rows[-1] if right_rows else {}
    left_payload = extract_payload(left_row) if left_row else {}
    right_payload = extract_payload(right_row) if right_row else {}
    inferred_endpoint = endpoint or str(left_row.get("endpoint") or right_row.get("endpoint") or "")
    return {
        "schema": SCHEMA_VERSION,
        "left_label": slug_label(left_label),
        "right_label": slug_label(right_label),
        "endpoint": inferred_endpoint,
        "direction": direction,
        "left_match_count": len(left_rows),
        "right_match_count": len(right_rows),
        "left_req_id": left_row.get("req_id") if left_row else "",
        "right_req_id": right_row.get("req_id") if right_row else "",
        "diff": compare_payloads(left_payload, right_payload),
        "left_payload": left_payload,
        "right_payload": right_payload,
    }


def list_capture_summaries(runtime_dir: str | Path) -> list[dict[str, Any]]:
    root = discovery_root(runtime_dir)
    rows = []
    for path in sorted([p for p in root.iterdir() if p.is_dir()], key=lambda p: p.stat().st_mtime, reverse=True):
        metadata = _safe_read_json(path / "capture.json", {}) or {}
        contract = _safe_read_json(path / "contract.json", {}) or {}
        events_path = path / "events.jsonl"
        rows.append({
            "label": path.name,
            "path": str(path),
            "status": metadata.get("status") or "unknown",
            "note": metadata.get("note") or "",
            "started_at": metadata.get("started_at"),
            "stopped_at": metadata.get("stopped_at"),
            "event_count": metadata.get("event_count") or contract.get("entry_count") or 0,
            "endpoint_counts": contract.get("endpoint_counts") or metadata.get("endpoint_counts") or {},
            "events_file": str(events_path) if events_path.exists() else "",
            "contract_file": str(path / "contract.json") if (path / "contract.json").exists() else "",
        })
    return rows


class ApiDiscoverySession:
    def __init__(
        self,
        runtime_dir: str | Path,
        label: str,
        *,
        note: str = "",
        endpoints: list[str] | None = None,
    ) -> None:
        self.runtime_dir = Path(runtime_dir)
        self.label = slug_label(label)
        self.note = str(note or "")
        self.endpoints = {str(ep).strip() for ep in (endpoints or []) if str(ep).strip()}
        self.started_at = time.time()
        self.event_count = 0
        self.endpoint_counts: Counter[str] = Counter()
        self.path = capture_dir(self.runtime_dir, self.label)
        self.events_file = self.path / "events.jsonl"
        self.metadata_file = self.path / "capture.json"
        self._write_metadata(status="active")

    def _write_metadata(self, *, status: str, stopped_at: float | None = None) -> None:
        data = {
            "schema": SCHEMA_VERSION,
            "label": self.label,
            "status": status,
            "note": self.note,
            "endpoints": sorted(self.endpoints),
            "started_at": self.started_at,
            "stopped_at": stopped_at,
            "event_count": self.event_count,
            "endpoint_counts": dict(self.endpoint_counts.most_common()),
            "events_file": str(self.events_file),
        }
        _write_json(self.metadata_file, data)

    def on_api_log(self, direction: str, endpoint: str, data: Any, req_id: str | None = None) -> None:
        endpoint = str(endpoint or "")
        if self.endpoints and endpoint not in self.endpoints:
            return
        row = {
            "schema": SCHEMA_VERSION,
            "ts": time.time(),
            "direction": str(direction or ""),
            "endpoint": endpoint,
            "req_id": req_id or "",
            "data": data,
        }
        with self.events_file.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False, default=_json_default) + "\n")
        self.event_count += 1
        self.endpoint_counts[endpoint] += 1
        if self.event_count == 1 or self.event_count % 10 == 0:
            self._write_metadata(status="active")

    def status(self) -> dict[str, Any]:
        return {
            "active": True,
            "label": self.label,
            "note": self.note,
            "started_at": self.started_at,
            "event_count": self.event_count,
            "endpoint_counts": dict(self.endpoint_counts.most_common()),
            "events_file": str(self.events_file),
        }

    def stop(self) -> dict[str, Any]:
        stopped_at = time.time()
        entries = load_capture_entries(self.runtime_dir, self.label)
        self.event_count = len(entries)
        self.endpoint_counts = Counter(str(row.get("endpoint") or "") for row in entries if row.get("endpoint"))
        self._write_metadata(status="stopped", stopped_at=stopped_at)
        contract = write_contract(self.runtime_dir, self.label, entries)
        return {
            "active": False,
            "label": self.label,
            "event_count": self.event_count,
            "events_file": str(self.events_file),
            "contract_file": str(self.path / "contract.json"),
            "contract": contract,
        }
