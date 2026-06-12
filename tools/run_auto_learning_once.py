"""Run one auto-learning pass in an isolated subprocess.

Spawned by the runner after each career (see
CareerRunner._schedule_post_run_outputs). Running learning out-of-process
means every pass executes the CURRENT code on disk — in-process learning
inside a long-lived server only ever runs whatever was imported at server
start, so fixes stay dormant until an operator restart (observed live
2026-06-12: the adaptive score floor shipped mid-day was inert while the
09:23 server kept skipping every career). A crash here also can no longer
take the career loop's worker thread down with it.

Outcome rows are appended to <runtime>/learning/auto_learning_outcomes.jsonl
by this process; the runner adds an "error" row only if the subprocess
itself dies.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


def _record_outcome(outcomes_path: Path, outcome: dict) -> None:
    try:
        outcomes_path.parent.mkdir(parents=True, exist_ok=True)
        outcome = dict(outcome or {})
        outcome.setdefault("ts", time.strftime("%Y-%m-%dT%H:%M:%S"))
        with open(outcomes_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(outcome, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset-snapshot", required=True,
                    help="Path to the serialized active-preset snapshot JSON")
    ap.add_argument("--career-log", required=True)
    ap.add_argument("--status", default="")
    ap.add_argument("--outcomes-path", required=True,
                    help="auto_learning_outcomes.jsonl to append the result row to")
    args = ap.parse_args()

    outcomes_path = Path(args.outcomes_path)
    try:
        preset_snapshot = json.loads(Path(args.preset_snapshot).read_text(encoding="utf-8-sig"))
    except Exception as exc:
        _record_outcome(outcomes_path, {
            "outcome": "error",
            "career_log": args.career_log,
            "error": f"snapshot unreadable: {exc}",
            "error_type": type(exc).__name__,
            "mode": "subprocess",
        })
        return 2

    from career_bot.auto_learning import run_auto_learning

    try:
        result = run_auto_learning(
            PROJECT_ROOT,
            preset_snapshot,
            career_log=args.career_log,
            status=args.status or preset_snapshot.get("_report_status") or None,
        )
    except Exception as exc:
        _record_outcome(outcomes_path, {
            "outcome": "error",
            "career_log": args.career_log,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "mode": "subprocess",
        })
        print(f"auto learning failed: {exc}", flush=True)
        return 1

    _record_outcome(outcomes_path, {
        "outcome": "applied" if result.get("success") else "skipped",
        "career_log": args.career_log,
        "skipped": result.get("skipped"),
        "status": result.get("status"),
        "apply_scope": result.get("apply_scope"),
        "usable_sample_count": result.get("usable_sample_count"),
        "sample_count": result.get("sample_count"),
        "preset_path": result.get("preset_path"),
        "report_path": result.get("report_path"),
        "mode": "subprocess",
    })
    if result.get("success"):
        print(f"auto learning applied: {result.get('usable_sample_count', 0)} usable samples "
              f"-> {result.get('preset_path')}", flush=True)
    else:
        print(f"auto learning skipped: {result.get('skipped')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
