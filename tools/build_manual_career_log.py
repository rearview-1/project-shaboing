import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from career_bot.manual_recorder import build_report_from_trace
from career_bot.report import write_report
from career_bot.runner import runtime_output_root


def latest_trace(runtime_dir):
    trace_dir = Path(runtime_dir) / "trace_logs" / "api_payloads"
    if not trace_dir.exists():
        return None
    files = sorted(trace_dir.glob("*_payloads.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    return files[0] if files else None


def main():
    parser = argparse.ArgumentParser(description="Build a bot-comparable manual career log from Sweepy API traces.")
    parser.add_argument("--trace", help="Path to a *_payloads.jsonl trace. Defaults to newest trace.")
    parser.add_argument("--output-dir", help="Output directory. Defaults to uma_runtime/manual_career_logs.")
    parser.add_argument("--summary", action="store_true", help="Print compact summary JSON after writing.")
    args = parser.parse_args()

    runtime_dir = runtime_output_root(ROOT)
    trace = Path(args.trace) if args.trace else latest_trace(runtime_dir)
    if not trace or not trace.exists():
        raise SystemExit("No trace file found. Enable SWEEPY_TRACE_API and capture a career first.")

    output_dir = Path(args.output_dir) if args.output_dir else runtime_dir / "manual_career_logs"
    report = build_report_from_trace(trace, ROOT, output_dir=output_dir)
    path = write_report(report, output_dir)

    if args.summary:
        turns = report.get("turns") or []
        action_counts = {}
        for turn in turns:
            action = turn.get("selected_action") or ""
            if action:
                action_counts[action] = action_counts.get(action, 0) + 1
        print(json.dumps({
            "written": str(path),
            "trace": str(trace),
            "turns": len(turns),
            "final_turn": report.get("final_turn"),
            "actions": action_counts,
        }, ensure_ascii=False, indent=2))
    else:
        print(f"manual career report written: {path}")


if __name__ == "__main__":
    main()
