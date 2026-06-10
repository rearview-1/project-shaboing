import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tools.export_hakuraku_races import export_races, runtime_output_root


def export_all(project_root, limit=0, archive=False):
    project_root = Path(project_root).resolve()
    runtime_root = runtime_output_root(project_root)
    log_dir = runtime_root / "bot_logs"
    out_root = runtime_root / "hakuraku_races"
    logs = sorted(log_dir.glob("career_log_*.json"), key=lambda path: path.stat().st_mtime)
    if limit:
        logs = logs[-int(limit):]

    results = []
    latest_success = None
    latest_success_dir = None
    with tempfile.TemporaryDirectory(prefix="sweepy_hakuraku_scan_") as temp_root:
        temp_root = Path(temp_root)
        for log in logs:
            scan_dir = temp_root / log.stem
            try:
                manifest = export_races(
                    project_root=project_root,
                    career_log=log,
                    output_dir=scan_dir,
                    preserve_existing_on_empty=False,
                )
                row = {
                    "career_log": str(log),
                    "total_exported": int(manifest.get("total_exported") or 0),
                    "g1_losses": len(manifest.get("g1_losses") or []),
                }
                if row["total_exported"] > 0:
                    latest_success = dict(row)
                    latest_success_dir = scan_dir
                    if archive:
                        archive_dir = out_root / "archive" / log.stem
                        if archive_dir.exists():
                            shutil.rmtree(archive_dir)
                        shutil.copytree(scan_dir, archive_dir)
                        row["archive_dir"] = str(archive_dir)
            except Exception as exc:
                row = {
                    "career_log": str(log),
                    "error": str(exc),
                }
            results.append(row)

        if latest_success_dir:
            latest_dir = out_root / "latest_career_log"
            if latest_dir.exists():
                shutil.rmtree(latest_dir)
            shutil.copytree(latest_success_dir, latest_dir)
            latest_success["output_dir"] = str(latest_dir)

    summary = {
        "runtime_root": str(runtime_root),
        "count": len(results),
        "successful_exports": sum(1 for row in results if row.get("total_exported", 0) > 0),
        "latest_success": latest_success,
        "results": results,
    }
    (out_root / "export_all_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Backfill Hakuraku/HorseACT race JSON exports for saved Sweepy career logs.")
    parser.add_argument("--project-root", default=PROJECT_ROOT)
    parser.add_argument("--limit", type=int, default=0, help="Only export the latest N career logs.")
    parser.add_argument("--archive", action="store_true", help="Also keep per-career exports under hakuraku_races/archive.")
    args = parser.parse_args()
    print(json.dumps(export_all(args.project_root, args.limit, archive=args.archive), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
