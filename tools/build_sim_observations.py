"""Backfill simulator observation JSONL from existing career logs.

New bot runs write these automatically. This tool converts old
uma_runtime/**/bot_logs/career_log_*.json files so the simulator can use them
immediately.

Usage:
    python -m tools.build_sim_observations --instance account_b --limit 20
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable

from career_bot.sim_observations import write_sim_observation_export


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _runtime_roots(project_root: Path) -> list[Path]:
    roots = []
    for candidate in (project_root / "uma_runtime", project_root.parent / "uma_runtime"):
        if candidate.exists() and candidate not in roots:
            roots.append(candidate)
    return roots


def iter_career_logs(project_root: Path, instance: str = "", include_legacy: bool = True) -> Iterable[Path]:
    wanted = str(instance or "").strip().lower()
    for runtime_root in _runtime_roots(project_root):
        if runtime_root == project_root.parent / "uma_runtime" and not include_legacy:
            continue
        instance_root = runtime_root / "instances"
        if instance_root.exists():
            for instance_dir in instance_root.glob("*"):
                if not instance_dir.is_dir():
                    continue
                if wanted and instance_dir.name.lower() != wanted:
                    continue
                yield from instance_dir.glob("bot_logs/career_log_*.json")
        if not wanted:
            yield from runtime_root.glob("bot_logs/career_log_*.json")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", default=str(PROJECT_ROOT))
    parser.add_argument("--instance", default="", help="Optional runtime instance, e.g. account_a/account_b")
    parser.add_argument("--limit", type=int, default=0, help="Newest N logs to convert. 0 means all.")
    parser.add_argument("--no-legacy", dest="include_legacy", action="store_false", default=True)
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    logs = sorted(
        iter_career_logs(project_root, args.instance, include_legacy=args.include_legacy),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if args.limit:
        logs = logs[: max(0, int(args.limit))]

    summaries = []
    # Each export updates latest.jsonl/latest_summary.json. Write oldest first
    # so the final latest pointer remains the newest selected career.
    for log_path in reversed(logs):
        runtime_root = log_path.parent.parent if log_path.parent.name.lower() == "bot_logs" else None
        summary = write_sim_observation_export(log_path, runtime_root=runtime_root)
        summaries.append({
            "career_log": str(log_path),
            "_mtime": log_path.stat().st_mtime,
            "jsonl_path": summary.get("jsonl_path"),
            "record_count": summary.get("record_count", 0),
            "training_snapshot_count": summary.get("training_snapshot_count", 0),
            "race_result_count": summary.get("race_result_count", 0),
            "shop_item_phase_count": summary.get("shop_item_phase_count", 0),
        })
    summaries.sort(key=lambda row: row.get("_mtime", 0), reverse=True)
    for row in summaries:
        row.pop("_mtime", None)

    output = {
        "converted": len(summaries),
        "training_snapshots": sum(row["training_snapshot_count"] for row in summaries),
        "race_results": sum(row["race_result_count"] for row in summaries),
        "shop_item_phases": sum(row["shop_item_phase_count"] for row in summaries),
        "files": summaries,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
