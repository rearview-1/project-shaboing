"""Ingest public profile/team career data from captured API traces.

Usage:
    python tools/ingest_public_profile_traces.py --recent-files 10 --stat wit --min-value 1200
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from career_bot.profile_dataset import ingest_trace_dataset, summarize_dataset
from career_bot.runner import runtime_output_root


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--runtime-root", default="")
    parser.add_argument("--instance", default="", help="Runtime instance name, e.g. account_a or account_b.")
    parser.add_argument("--recent-files", type=int, default=5)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--include-self", action="store_true", help="Also ingest owned load/index trained_chara records.")
    parser.add_argument("--stat", default="", help="Optional stat summary filter, e.g. wit.")
    parser.add_argument("--min-value", type=int, default=0, help="Optional stat minimum for summary filtering.")
    parser.add_argument("--summary-limit", type=int, default=20)
    parser.add_argument("--watch", action="store_true", help="Keep ingesting as trace files appear or grow.")
    parser.add_argument("--interval", type=float, default=5.0, help="Watch polling interval in seconds.")
    parser.add_argument("--loops", type=int, default=0, help="Watch loop count; 0 means run until stopped.")
    return parser.parse_args()


def resolve_runtime_root(args: argparse.Namespace, project_root: Path) -> Path:
    if args.runtime_root:
        return Path(args.runtime_root).resolve()
    runtime_root = runtime_output_root(project_root)
    if args.instance:
        instance = str(args.instance).strip()
        local_instance = project_root / "uma_runtime" / "instances" / instance
        return local_instance if local_instance.exists() else runtime_root / "instances" / instance
    return runtime_root


def run_once(args: argparse.Namespace, project_root: Path, runtime_root: Path) -> dict:
    result = ingest_trace_dataset(
        project_root,
        runtime_root,
        recent_files=args.recent_files,
        limit=args.limit,
        include_self=args.include_self,
    )
    payload = {"ingest": result}
    if args.stat or args.min_value:
        payload["summary"] = summarize_dataset(
            project_root,
            runtime_root,
            stat=args.stat,
            min_value=args.min_value,
            limit=args.summary_limit,
        )
    return payload


def trace_signature(runtime_root: Path, recent_files: int) -> tuple:
    trace_dir = runtime_root / "trace_logs" / "api_payloads"
    if not trace_dir.exists():
        return ()
    files = sorted(
        [path for path in trace_dir.glob("*_payloads.jsonl") if path.is_file()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )[: max(1, int(recent_files or 1))]
    return tuple((path.name, path.stat().st_size, int(path.stat().st_mtime)) for path in files)


def main() -> int:
    args = parse_args()
    project_root = Path(args.project_root).resolve()
    runtime_root = resolve_runtime_root(args, project_root)
    if not args.watch:
        print(json.dumps(run_once(args, project_root, runtime_root), ensure_ascii=False, indent=2))
        return 0

    last_signature = None
    loops = 0
    interval = max(1.0, float(args.interval or 5.0))
    print(json.dumps({
        "watch": "started",
        "runtime_root": str(runtime_root),
        "recent_files": args.recent_files,
        "interval": interval,
    }, ensure_ascii=False), flush=True)
    while True:
        signature = trace_signature(runtime_root, args.recent_files)
        if signature != last_signature:
            payload = run_once(args, project_root, runtime_root)
            payload["watch"] = {"signature_changed": signature != last_signature, "loop": loops + 1}
            print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)
            last_signature = signature
        loops += 1
        if args.loops and loops >= args.loops:
            break
        time.sleep(interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
