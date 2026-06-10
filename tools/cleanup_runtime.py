"""Storage triage per claude-code-handoff-deep-audit-continuation Phase 1.

Mechanical cleanup of stale runtime artifacts. Safe to run repeatedly.
By default DRY RUN — pass --apply to actually delete.

Handles:
  1.1 Stale DUMP files (uma_runtime/bot_logs/*_DUMP_*.json older than 7 days)
  1.3 Preset backups (data/presets/backups/*.json, keep newest 10 per preset name)
  1.4 Error snapshots (uma_runtime/instances/*/error_snapshots/*, keep newest 5 per category)
"""

import argparse
import re
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


def _human_size(bytes_count):
    for unit in ("B", "KB", "MB", "GB"):
        if bytes_count < 1024:
            return f"{bytes_count:.1f} {unit}"
        bytes_count /= 1024
    return f"{bytes_count:.1f} TB"


def cleanup_stale_dumps(runtime_root, age_days=7, apply=False):
    """Delete *_DUMP_*.json files in uma_runtime/bot_logs/ older than age_days."""
    dumps_dir = runtime_root / "bot_logs"
    if not dumps_dir.exists():
        return [], 0
    cutoff = datetime.now() - timedelta(days=age_days)
    cutoff_ts = cutoff.timestamp()
    candidates = []
    total_bytes = 0
    for path in dumps_dir.glob("*_DUMP_*.json"):
        if path.stat().st_mtime < cutoff_ts:
            candidates.append(path)
            total_bytes += path.stat().st_size
    if apply:
        for path in candidates:
            try:
                path.unlink()
            except OSError:
                pass
    return candidates, total_bytes


def rotate_preset_backups(presets_dir, keep_per_name=10, apply=False):
    """Keep only the newest `keep_per_name` backups per preset name."""
    backups_dir = presets_dir / "backups"
    if not backups_dir.exists():
        return [], 0
    # Group by preset name (strip trailing _<timestamp> from filename)
    by_name = defaultdict(list)
    name_pattern = re.compile(r"^(.+?)_\d{4}-?\d{2}-?\d{2}[_T]\d{2}-?\d{2}-?\d{2}\.json$")
    for path in backups_dir.glob("*.json"):
        match = name_pattern.match(path.name)
        if match:
            by_name[match.group(1)].append(path)
        else:
            # Files that don't match the pattern get grouped by stem prefix.
            stem = path.stem.rsplit("_", 1)[0] if "_" in path.stem else path.stem
            by_name[stem].append(path)
    candidates = []
    total_bytes = 0
    for name, files in by_name.items():
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        stale = files[keep_per_name:]
        for path in stale:
            candidates.append(path)
            total_bytes += path.stat().st_size
    if apply:
        for path in candidates:
            try:
                path.unlink()
            except OSError:
                pass
    return candidates, total_bytes


def cleanup_error_snapshots(instance_root, keep_per_category=5, apply=False):
    """For each error category dir in instance_root/error_snapshots/, keep
    only the newest `keep_per_category` snapshot files."""
    snapshots_dir = instance_root / "error_snapshots"
    if not snapshots_dir.exists():
        return [], 0
    candidates = []
    total_bytes = 0
    for category_dir in snapshots_dir.iterdir():
        if not category_dir.is_dir():
            continue
        files = list(category_dir.glob("*.json"))
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        for path in files[keep_per_category:]:
            candidates.append(path)
            total_bytes += path.stat().st_size
    if apply:
        for path in candidates:
            try:
                path.unlink()
            except OSError:
                pass
    return candidates, total_bytes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--apply", action="store_true", help="Actually delete (default: dry run)")
    parser.add_argument("--dump-age-days", type=int, default=7)
    parser.add_argument("--keep-backups-per-name", type=int, default=10)
    parser.add_argument("--keep-snapshots-per-category", type=int, default=5)
    args = parser.parse_args()

    root = Path(args.root).resolve()
    runtime_root = root / "uma_runtime"
    presets_dir = root / "data" / "presets"
    instances_root = runtime_root / "instances"

    print(f"Mode: {'APPLY' if args.apply else 'DRY RUN'}")
    print()

    # 1.1: stale dumps in the shared runtime root + per-instance bot_logs
    total_dump_count = 0
    total_dump_bytes = 0
    for target in [runtime_root, *([d for d in instances_root.iterdir() if d.is_dir()] if instances_root.exists() else [])]:
        candidates, bytes_count = cleanup_stale_dumps(target, age_days=args.dump_age_days, apply=args.apply)
        if candidates:
            print(f"[1.1] {target.relative_to(root)}/bot_logs/ - {len(candidates)} stale DUMP file(s), {_human_size(bytes_count)}")
            total_dump_count += len(candidates)
            total_dump_bytes += bytes_count
    if total_dump_count == 0:
        print("[1.1] No stale DUMP files to clean.")

    # 1.3: preset backups
    backup_candidates, backup_bytes = rotate_preset_backups(presets_dir, keep_per_name=args.keep_backups_per_name, apply=args.apply)
    if backup_candidates:
        print(f"[1.3] {presets_dir.relative_to(root)}/backups/ - {len(backup_candidates)} stale backup(s), {_human_size(backup_bytes)}")
    else:
        print("[1.3] No stale preset backups to rotate.")

    # 1.4: error snapshots per instance
    total_snap_count = 0
    total_snap_bytes = 0
    if instances_root.exists():
        for instance_dir in instances_root.iterdir():
            if not instance_dir.is_dir():
                continue
            candidates, bytes_count = cleanup_error_snapshots(instance_dir, keep_per_category=args.keep_snapshots_per_category, apply=args.apply)
            if candidates:
                print(f"[1.4] {instance_dir.relative_to(root)}/error_snapshots/ - {len(candidates)} stale snapshot(s), {_human_size(bytes_count)}")
                total_snap_count += len(candidates)
                total_snap_bytes += bytes_count
    if total_snap_count == 0:
        print("[1.4] No stale error snapshots to clean.")

    total_bytes = total_dump_bytes + backup_bytes + total_snap_bytes
    print()
    print(f"Total reclaimed: {_human_size(total_bytes)}")
    if not args.apply:
        print("(dry run - rerun with --apply to actually delete)")


if __name__ == "__main__":
    main()
