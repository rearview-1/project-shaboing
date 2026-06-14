"""Inspect labeled API discovery captures from the command line."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from career_bot.api_discovery import compare_captures, list_capture_summaries, load_capture_entries, write_contract
from career_bot.runner import runtime_output_root


def default_runtime_dir() -> Path:
    return runtime_output_root(PROJECT_ROOT)


def main() -> int:
    parser = argparse.ArgumentParser(description="Diff or summarize Sweepy API discovery captures.")
    parser.add_argument("--runtime-dir", default="", help="Runtime directory. Defaults to this project's uma_runtime.")
    parser.add_argument("--left", default="", help="Left capture label for diff.")
    parser.add_argument("--right", default="", help="Right capture label for diff.")
    parser.add_argument("--endpoint", default="", help="Endpoint to diff, e.g. single_mode_free/start.")
    parser.add_argument("--direction", default="REQ", help="Trace direction to diff. Defaults to REQ.")
    parser.add_argument("--contract", default="", help="Write/print a contract for this capture label.")
    parser.add_argument("--list", action="store_true", help="List available captures.")
    parser.add_argument("--json", action="store_true", help="Print full JSON instead of a compact summary.")
    args = parser.parse_args()

    runtime_dir = Path(args.runtime_dir).expanduser() if args.runtime_dir else default_runtime_dir()

    if args.list:
        rows = list_capture_summaries(runtime_dir)
        if args.json:
            print(json.dumps({"captures": rows}, ensure_ascii=False, indent=2))
        else:
            for row in rows:
                endpoints = ", ".join(list((row.get("endpoint_counts") or {}).keys())[:4])
                print(f"{row.get('label')} | {row.get('status')} | {row.get('event_count')} rows | {endpoints}")
        return 0

    if args.contract:
        entries = load_capture_entries(runtime_dir, args.contract)
        if not entries:
            print(f"No entries found for capture '{args.contract}'", file=sys.stderr)
            return 2
        contract = write_contract(runtime_dir, args.contract, entries)
        print(json.dumps(contract, ensure_ascii=False, indent=2))
        return 0

    if not args.left or not args.right:
        parser.error("--left and --right are required for diff mode")

    result = compare_captures(
        runtime_dir,
        args.left,
        args.right,
        endpoint=args.endpoint,
        direction=args.direction or "REQ",
    )
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"{result['left_label']} -> {result['right_label']} | {result.get('endpoint') or '<any endpoint>'}")
    print(f"matches: left={result['left_match_count']} right={result['right_match_count']}")
    diff = result.get("diff") or {}
    for section in ("changed", "only_left", "only_right"):
        rows = diff.get(section) or []
        print(f"\n{section}: {len(rows)}")
        for row in rows[:80]:
            if section == "changed":
                print(f"  {row['path']}: {row['left']} -> {row['right']}")
            else:
                print(f"  {row['path']}: {row['value']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
