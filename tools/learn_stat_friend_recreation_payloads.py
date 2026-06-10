"""Learn verified stat-friend recreation payloads from API traces.

The bot must not guess later pal/friend outing request shapes. This script
pairs successful single_mode_free/exec_command responses with their matching
requests and writes the exact command fields needed for Riko/Tazuna-style
recreation chains.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "stat_friend_recreation_payloads.json"
DEFAULT_TRACE_ROOTS = [
    PROJECT_ROOT / "uma_runtime" / "instances",
    PROJECT_ROOT.parent / "uma_runtime" / "instances",
]

STAT_FRIEND_STORIES = {
    "809006005": {"card_id": 30036, "name": "Riko Kashimoto", "chain_num": 1},
    "809006006": {"card_id": 30036, "name": "Riko Kashimoto", "chain_num": 2},
    "809006007": {"card_id": 30036, "name": "Riko Kashimoto", "chain_num": 3},
    "809006008": {"card_id": 30036, "name": "Riko Kashimoto", "chain_num": 4},
    "830036001": {"card_id": 30036, "name": "Riko Kashimoto", "chain_num": 5},
}

COMMAND_KEYS = ("command_type", "command_id", "command_group_id", "select_id")


def _as_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _load_json(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _response_code(entry: dict[str, Any]) -> int:
    for source in (
        entry,
        entry.get("data") if isinstance(entry.get("data"), dict) else {},
        (entry.get("data") or {}).get("data_headers") if isinstance(entry.get("data"), dict) else {},
    ):
        if not isinstance(source, dict):
            continue
        code = _as_int(source.get("response_code") or source.get("result_code"))
        if code:
            return code
    return 0


def _response_data(entry: dict[str, Any]) -> dict[str, Any]:
    data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
    nested = data.get("data")
    if isinstance(nested, dict):
        return nested
    return data


def _request_payload(entry: dict[str, Any]) -> dict[str, Any]:
    data = entry.get("data") if isinstance(entry.get("data"), dict) else {}
    payload = data.get("payload") if isinstance(data.get("payload"), dict) else data
    return payload if isinstance(payload, dict) else {}


def _riko_events(response: dict[str, Any]) -> list[dict[str, Any]]:
    events = []
    for event in response.get("unchecked_event_array") or []:
        if not isinstance(event, dict):
            continue
        story_id = str(event.get("story_id") or "")
        meta = STAT_FRIEND_STORIES.get(story_id)
        if not meta:
            continue
        contents = event.get("event_contents_info") if isinstance(event.get("event_contents_info"), dict) else {}
        card_id = _as_int(contents.get("support_card_id") or event.get("support_card_id") or meta["card_id"])
        events.append({
            "story_id": story_id,
            "card_id": card_id,
            "name": meta["name"],
            "chain_num": meta["chain_num"],
        })
    return events


def _limit_recent(files: list[Path], recent: int) -> list[Path]:
    unique = sorted(set(files), key=lambda p: p.stat().st_mtime, reverse=True)
    if recent > 0:
        unique = unique[:recent]
    return list(reversed(unique))


def _iter_trace_files(paths: list[Path], recent: int) -> list[Path]:
    files: list[Path] = []
    if paths:
        for path in paths:
            if path.is_file() and path.suffix.lower() == ".jsonl":
                files.append(path)
            elif path.is_dir():
                files.extend(path.rglob("*_payloads.jsonl"))
        return _limit_recent(files, recent)

    for root in DEFAULT_TRACE_ROOTS:
        if root.is_dir():
            files.extend(root.rglob("*_payloads.jsonl"))
    return _limit_recent(files, recent)


def _learn_from_trace(path: Path) -> list[dict[str, Any]]:
    requests: dict[str, dict[str, Any]] = {}
    learned: list[dict[str, Any]] = []
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return learned
    for line in lines:
        try:
            entry = json.loads(line)
        except Exception:
            continue
        # Old packet-sniffer probe history format:
        # {"kind":"training_exec","path":"/umamusume/.../exec_command",
        #  "request_decoded": {...}, "decoded": {...}}
        if (
            entry.get("kind") == "training_exec"
            and "exec_command" in str(entry.get("path") or "")
            and isinstance(entry.get("request_decoded"), dict)
            and isinstance(entry.get("decoded"), dict)
        ):
            response = entry.get("decoded") or {}
            data = response.get("data") if isinstance(response.get("data"), dict) else response
            events = _riko_events(data)
            if not events:
                continue
            request = entry.get("request_decoded") or {}
            req_data = request.get("data") if isinstance(request.get("data"), dict) else request
            command_payload = {key: _as_int(req_data.get(key)) for key in COMMAND_KEYS}
            for event in events:
                learned.append({
                    **event,
                    **command_payload,
                    "source": str(path),
                    "req_id": f"old_probe:{int(float(entry.get('captured_at') or 0))}",
                })
            continue
        if entry.get("endpoint") != "single_mode_free/exec_command":
            continue
        req_id = str(entry.get("req_id") or "")
        direction = str(entry.get("direction") or "").upper()
        if direction == "REQ":
            payload = _request_payload(entry)
            if req_id and payload:
                requests[req_id] = payload
            continue
        if direction != "RES" or not req_id:
            continue
        code = _response_code(entry)
        if code not in {1, 200}:
            continue
        response = _response_data(entry)
        events = _riko_events(response)
        if not events:
            continue
        request = requests.get(req_id)
        if not request:
            continue
        command_payload = {key: _as_int(request.get(key)) for key in COMMAND_KEYS}
        for event in events:
            learned.append({
                **event,
                **command_payload,
                "source": str(path),
                "req_id": req_id,
            })
    return learned


def _merge_payloads(output: Path, learned: list[dict[str, Any]]) -> dict[str, Any]:
    current = _load_json(output)
    if not current:
        current = {"schema": "sweepy_stat_friend_recreation_payloads_v1", "cards": {}}
    current.setdefault("schema", "sweepy_stat_friend_recreation_payloads_v1")
    cards = current.setdefault("cards", {})
    if not isinstance(cards, dict):
        cards = {}
        current["cards"] = cards

    for row in learned:
        card_id = str(row["card_id"])
        card = cards.setdefault(card_id, {"name": row.get("name") or card_id})
        card.setdefault("name", row.get("name") or card_id)
        template = {
            key: int(row.get(key) or 0)
            for key in COMMAND_KEYS
        }
        template.update({
            "story_id": int(row["story_id"]),
            "source": row["source"],
            "learned_at": int(time.time()),
        })
        chain_num = int(row.get("chain_num") or 0)
        if chain_num <= 1:
            card["initial"] = template
        else:
            stages = card.setdefault("stages", {})
            if isinstance(stages, dict):
                stages[str(chain_num)] = template
            # The later Riko chain uses the same recreation action once the
            # chain is unlocked. Keep a generic fallback until we capture every
            # individual stage.
            card["started"] = template
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return current


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path, help="Trace files or directories. Defaults to uma_runtime instance traces.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Payload JSON to update.")
    parser.add_argument("--recent", type=int, default=80, help="Only scan the N most recent trace files. Use 0 for all.")
    args = parser.parse_args()

    files = _iter_trace_files(args.paths, args.recent)
    learned: list[dict[str, Any]] = []
    for path in files:
        learned.extend(_learn_from_trace(path))

    merged = _merge_payloads(args.output, learned) if learned else _load_json(args.output)
    cards = (merged.get("cards") or {}) if isinstance(merged, dict) else {}
    print(f"scanned_files={len(files)} learned_payloads={len(learned)} output={args.output}")
    for card_id, card in sorted(cards.items()):
        if not isinstance(card, dict):
            continue
        stages = card.get("stages") if isinstance(card.get("stages"), dict) else {}
        print(
            f"card={card_id} name={card.get('name', '')} "
            f"initial={bool(card.get('initial'))} started={bool(card.get('started'))} "
            f"stages={','.join(sorted(stages.keys())) if stages else '-'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
