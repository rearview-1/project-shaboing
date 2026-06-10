import json
from pathlib import Path


COMMON_PAYLOAD_KEYS = {
    "viewer_id",
    "device",
    "device_id",
    "device_name",
    "graphics_device_name",
    "ip_address",
    "platform_os_version",
    "carrier",
    "keychain",
    "locale",
    "button_info",
    "dmm_viewer_id",
    "dmm_onetime_token",
    "steam_id",
    "steam_session_ticket",
}


class ReplayMismatchError(AssertionError):
    pass


def _load_jsonl(path):
    rows = []
    with open(path, "r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no}: invalid JSONL row: {exc}") from exc
    return rows


def sanitized_payload(payload):
    return {
        key: value
        for key, value in dict(payload or {}).items()
        if key not in COMMON_PAYLOAD_KEYS
    }


class RecordedApiTrace:
    def __init__(self, interactions):
        self.interactions = interactions

    @classmethod
    def from_jsonl(cls, path):
        events = _load_jsonl(path)
        pending = {}
        interactions = []
        for event in events:
            direction = event.get("direction")
            endpoint = event.get("endpoint")
            req_id = event.get("req_id") or f"{endpoint}:{len(interactions)}"
            if direction == "REQ":
                pending[req_id] = {
                    "endpoint": endpoint,
                    "request": event.get("data") or {},
                    "response": None,
                    "error": None,
                }
            elif direction in {"RES", "ERR"}:
                item = pending.pop(req_id, None) or {
                    "endpoint": endpoint,
                    "request": {},
                    "response": None,
                    "error": None,
                }
                if item["endpoint"] != endpoint:
                    raise ReplayMismatchError(f"Trace req_id {req_id} endpoint changed: {item['endpoint']} -> {endpoint}")
                if direction == "RES":
                    item["response"] = event.get("data") or {}
                else:
                    item["error"] = (event.get("data") or {}).get("error") or json.dumps(event.get("data") or {})
                interactions.append(item)
        for req_id, item in pending.items():
            raise ReplayMismatchError(f"Trace request {req_id} for {item['endpoint']} has no RES/ERR row")
        return cls(interactions)


class RecordedClient:
    def __init__(self, trace, strict_payload=True):
        self.trace = trace
        self.strict_payload = strict_payload
        self.index = 0
        self.cached_load_data = {}
        self.calls = []

    @classmethod
    def from_jsonl(cls, path, strict_payload=True):
        return cls(RecordedApiTrace.from_jsonl(path), strict_payload=strict_payload)

    def call(self, endpoint, args=None, **_kwargs):
        if self.index >= len(self.trace.interactions):
            raise ReplayMismatchError(f"No recorded interaction left for {endpoint}")
        item = self.trace.interactions[self.index]
        self.index += 1
        self.calls.append({"endpoint": endpoint, "args": dict(args or {})})
        expected_endpoint = item.get("endpoint")
        if expected_endpoint != endpoint:
            raise ReplayMismatchError(f"Replay endpoint mismatch: expected {expected_endpoint}, got {endpoint}")

        expected_payload = sanitized_payload((item.get("request") or {}).get("payload") or {})
        actual_payload = sanitized_payload(args or {})
        if self.strict_payload:
            for key, value in actual_payload.items():
                if expected_payload.get(key) != value:
                    raise ReplayMismatchError(
                        f"Replay payload mismatch on {endpoint}.{key}: expected {expected_payload.get(key)!r}, got {value!r}"
                    )

        if item.get("error"):
            raise Exception(item["error"])
        response = item.get("response") or {}
        data = response.get("data") or {}
        if endpoint == "load/index":
            self.refresh_cached_account_state(data)
        return response

    def load_career(self, quiet_no_career=False):
        return self.call("single_mode_free/load", {})

    def pre_single_mode(self, exclude_viewer_ids=None):
        payload = {}
        if exclude_viewer_ids:
            payload["exclude_viewer_id_array"] = exclude_viewer_ids
        return self.call("pre_single_mode/index", payload)

    def refresh_cached_account_state(self, data):
        self.cached_load_data = data or {}


def load_career_report(path):
    with open(path, "r", encoding="utf-8") as handle:
        report = json.load(handle)
    turns = report.get("turns") or []
    last_turn = 0
    decisions = 0
    api_calls = 0
    for row in turns:
        turn = int(row.get("turn") or 0)
        if turn < last_turn:
            raise ReplayMismatchError(f"Career report turns are not sorted: {turn} after {last_turn}")
        last_turn = turn
        if row.get("selected_action"):
            decisions += 1
        api_calls += len(row.get("api_calls") or [])
    return {
        "path": str(Path(path)),
        "status": report.get("status"),
        "preset_name": report.get("preset_name", ""),
        "scenario_id": int(report.get("scenario_id") or 0),
        "final_turn": int(report.get("final_turn") or last_turn or 0),
        "turn_count": len(turns),
        "decision_count": decisions,
        "api_call_count": api_calls,
        "first_turn": int(turns[0].get("turn") or 0) if turns else 0,
        "last_turn": last_turn,
    }
