import gzip
import json
import os
import re
import shutil
import time
from pathlib import Path

from career_bot.runner import runtime_output_root


SECONDS_PER_DAY = 24 * 60 * 60
DEFAULT_DUMP_RETENTION_DAYS = 7
DEFAULT_PRESET_BACKUPS_PER_NAME = 10
DEFAULT_ERROR_SNAPSHOTS_PER_CATEGORY = 5
DEFAULT_HACHIMI_ARCHIVES_PER_DIR = 5


def _safe_unlink(path):
    try:
        Path(path).unlink()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        return False


def _runtime_roots(base_dir):
    base = Path(base_dir).resolve()
    roots = []
    for candidate in (
        runtime_output_root(base),
        base / "uma_runtime",
        base.parent / "uma_runtime",
    ):
        try:
            resolved = Path(candidate).resolve()
        except OSError:
            continue
        if resolved not in roots:
            roots.append(resolved)
    return roots


def cleanup_stale_dumps(base_dir, older_than_days=DEFAULT_DUMP_RETENTION_DAYS):
    cutoff = time.time() - max(0, int(older_than_days)) * SECONDS_PER_DAY
    removed = []
    for runtime_root in _runtime_roots(base_dir):
        bot_logs = runtime_root / "bot_logs"
        if not bot_logs.exists():
            continue
        for path in bot_logs.glob("*_DUMP_*.json"):
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
            except OSError:
                continue
            if _safe_unlink(path):
                removed.append(str(path))
    return {"removed": removed, "removed_count": len(removed)}


_PRESET_BACKUP_RE = re.compile(r"^(?P<name>.+)_\d{8}_\d{6}(?:_\d+)?\.json$", re.IGNORECASE)


def _preset_backup_group(path):
    match = _PRESET_BACKUP_RE.match(Path(path).name)
    if match:
        return match.group("name").strip().lower()
    return Path(path).stem.strip().lower()


def rotate_preset_backups(base_dir, keep=DEFAULT_PRESET_BACKUPS_PER_NAME):
    backup_dir = Path(base_dir) / "data" / "presets" / "backups"
    if not backup_dir.exists():
        return {"removed": [], "removed_count": 0, "groups": {}}
    keep = max(1, int(keep))
    groups = {}
    for path in backup_dir.glob("*.json"):
        groups.setdefault(_preset_backup_group(path), []).append(path)
    removed = []
    kept_counts = {}
    for group, paths in groups.items():
        paths.sort(key=lambda p: (p.stat().st_mtime if p.exists() else 0.0, p.name), reverse=True)
        kept_counts[group] = min(len(paths), keep)
        for path in paths[keep:]:
            if _safe_unlink(path):
                removed.append(str(path))
    return {"removed": removed, "removed_count": len(removed), "groups": kept_counts}


def prune_hachimi_hook_archives(directory, keep=DEFAULT_HACHIMI_ARCHIVES_PER_DIR):
    root = Path(directory)
    keep = max(1, int(keep))
    archives = sorted(
        root.glob("hachimi_exact_hooks_*.jsonl.gz"),
        key=lambda p: (p.stat().st_mtime if p.exists() else 0.0, p.name),
        reverse=True,
    )
    removed = []
    for path in archives[keep:]:
        if _safe_unlink(path):
            removed.append(str(path))
    return removed


def rotate_hachimi_exact_hooks(directory, keep=DEFAULT_HACHIMI_ARCHIVES_PER_DIR, min_bytes=1):
    root = Path(directory)
    live = root / "hachimi_exact_hooks.jsonl"
    if not live.exists():
        return {"rotated": False, "archive": "", "removed": prune_hachimi_hook_archives(root, keep=keep)}
    try:
        if live.stat().st_size < int(min_bytes):
            return {"rotated": False, "archive": "", "removed": prune_hachimi_hook_archives(root, keep=keep)}
    except OSError:
        return {"rotated": False, "archive": "", "removed": []}

    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(live.stat().st_mtime))
    archive = root / f"hachimi_exact_hooks_{stamp}.jsonl.gz"
    suffix = 1
    while archive.exists():
        archive = root / f"hachimi_exact_hooks_{stamp}_{suffix}.jsonl.gz"
        suffix += 1
    tmp = archive.with_suffix(f"{archive.suffix}.{os.getpid()}.tmp")
    try:
        with open(live, "rb") as src, gzip.open(tmp, "wb", compresslevel=6) as dst:
            shutil.copyfileobj(src, dst)
        os.replace(tmp, archive)
        live.write_text("", encoding="utf-8")
    except Exception:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return {"rotated": False, "archive": "", "removed": []}
    removed = prune_hachimi_hook_archives(root, keep=keep)
    return {"rotated": True, "archive": str(archive), "removed": removed}


def _sanitize_snapshot_payload(payload):
    if not isinstance(payload, dict):
        return payload, False
    changed = False
    preset = payload.get("preset")
    if isinstance(preset, dict):
        stripped = payload.setdefault("_stripped_large_fields", {})
        preset_stripped = stripped.setdefault("preset", {})
        for key in ("extra_race_list", "race_list", "learn_skill_list"):
            value = preset.get(key)
            if isinstance(value, list) and value:
                preset_stripped[key] = len(value)
                preset.pop(key, None)
                changed = True
    return payload, changed


def sanitize_error_snapshot_file(path):
    path = Path(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return False
    payload, changed = _sanitize_snapshot_payload(payload)
    if not changed:
        return False
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return True
    except OSError:
        return False


def _error_snapshot_category_dirs(runtime_root):
    root = Path(runtime_root)
    candidates = []
    direct = root / "error_snapshots"
    if direct.exists():
        candidates.extend(path for path in direct.iterdir() if path.is_dir())
    instances = root / "instances"
    if instances.exists():
        for account_dir in instances.iterdir():
            snap_root = account_dir / "error_snapshots"
            if snap_root.exists():
                candidates.extend(path for path in snap_root.iterdir() if path.is_dir())
    return candidates


def cap_error_snapshots(base_dir, keep=DEFAULT_ERROR_SNAPSHOTS_PER_CATEGORY, strip_large_fields=True):
    keep = max(1, int(keep))
    removed = []
    sanitized = []
    categories = {}
    for runtime_root in _runtime_roots(base_dir):
        for category_dir in _error_snapshot_category_dirs(runtime_root):
            files = sorted(
                [
                    path for path in category_dir.glob("*.json")
                    if not path.name.startswith("latest_")
                ],
                key=lambda p: (p.stat().st_mtime if p.exists() else 0.0, p.name),
                reverse=True,
            )
            categories[str(category_dir)] = min(len(files), keep)
            if strip_large_fields:
                for path in files[:keep]:
                    if sanitize_error_snapshot_file(path):
                        sanitized.append(str(path))
            for path in files[keep:]:
                if _safe_unlink(path):
                    removed.append(str(path))
    return {
        "removed": removed,
        "removed_count": len(removed),
        "sanitized": sanitized,
        "sanitized_count": len(sanitized),
        "categories": categories,
    }


def run_startup_cleanup(base_dir):
    return {
        "stale_dumps": cleanup_stale_dumps(base_dir),
        "preset_backups": rotate_preset_backups(base_dir),
        "error_snapshots": cap_error_snapshots(base_dir),
    }
