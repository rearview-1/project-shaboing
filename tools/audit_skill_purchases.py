"""Skill purchase audit across all career logs.

Walks every career log, lists every (skill_id, recorded_name) pair the bot
tried to buy, and cross-references against `data/master_map.json` (the
canonical name table). Any mismatch between the recorded name and the
master-map name is flagged — that's the signature of bugs like the
"asked for Trackblazer (200711), got Rosy Outlook (200712)" case where
the bot's name → id resolution is incorrect.

Run:
  python tools/audit_skill_purchases.py
  python tools/audit_skill_purchases.py --since 2026-05-14
  python tools/audit_skill_purchases.py --json > audit.json

Output columns:
  - skill_id       — the ID actually used in the purchase call
  - recorded_name  — the name stored alongside that ID in the log
  - canonical_name — what master_map.json says that ID resolves to
  - count          — how many career logs contained this (id, name) pair
  - status         — "OK" if names match, "MISMATCH" if not, "UNKNOWN" if
                     the ID isn't in master_map at all (potentially stale)
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _normalize_name(value):
    if value is None:
        return ""
    return str(value).strip().lower()


def _load_canonical_skill_names(master_map_path):
    raw = json.loads(master_map_path.read_text(encoding="utf-8"))
    skills = raw.get("skill") or {}
    canonical = {}
    for key, value in skills.items():
        try:
            sid = int(key)
        except (TypeError, ValueError):
            continue
        if isinstance(value, dict):
            name = value.get("name") or value.get("text") or ""
        else:
            name = str(value)
        canonical[sid] = name
    return canonical


def _iter_career_logs(runtime_root, since_dt=None):
    bot_dir = runtime_root / "bot_logs"
    if not bot_dir.exists():
        return
    for path in sorted(bot_dir.glob("career_log_*.json"), key=lambda p: p.stat().st_mtime):
        if since_dt is not None:
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime)
            except OSError:
                continue
            if mtime < since_dt:
                continue
        yield path


def _iter_skill_attempts(career_log):
    try:
        data = json.loads(Path(career_log).read_text(encoding="utf-8"))
    except Exception:
        return
    for turn in data.get("turns") or []:
        for attempt in turn.get("skill_buy_attempts") or []:
            if not isinstance(attempt, dict):
                continue
            for entry in attempt.get("selected") or []:
                if isinstance(entry, dict):
                    yield entry
            for entry in attempt.get("attempt") or []:
                if isinstance(entry, dict):
                    yield entry


def audit(runtime_root, master_map_path, since_dt=None):
    canonical = _load_canonical_skill_names(master_map_path)
    pair_count = Counter()
    pair_career_files = defaultdict(set)
    skill_logs_seen = 0
    for log_path in _iter_career_logs(runtime_root, since_dt=since_dt):
        skill_logs_seen += 1
        seen_in_log = set()
        for entry in _iter_skill_attempts(log_path):
            try:
                sid = int(entry.get("skill_id") or 0)
            except (TypeError, ValueError):
                continue
            if not sid:
                continue
            name = entry.get("name") or ""
            seen_in_log.add((sid, name))
        for pair in seen_in_log:
            pair_count[pair] += 1
            pair_career_files[pair].add(log_path.name)

    rows = []
    for (sid, recorded_name), count in pair_count.most_common():
        canonical_name = canonical.get(sid)
        if canonical_name is None:
            status = "UNKNOWN"
        elif _normalize_name(canonical_name) == _normalize_name(recorded_name):
            status = "OK"
        else:
            status = "MISMATCH"
        rows.append({
            "skill_id": sid,
            "recorded_name": recorded_name,
            "canonical_name": canonical_name or "<not in master_map>",
            "count": count,
            "status": status,
        })

    return {
        "careers_scanned": skill_logs_seen,
        "distinct_pairs": len(rows),
        "rows": rows,
    }


def print_report(result):
    print(f"Scanned {result['careers_scanned']} career logs, {result['distinct_pairs']} distinct (skill_id, name) pairs.")
    mismatches = [row for row in result["rows"] if row["status"] != "OK"]
    if not mismatches:
        print()
        print("All pairs match master_map.json. No bugs of the Trackblazer/Rosy variety detected.")
        return
    print()
    print(f"=== {len(mismatches)} flagged pair(s) ===")
    print(f"{'skill_id':>8}  {'status':<8}  {'count':>5}  {'recorded':<32}  canonical")
    print("-" * 100)
    for row in mismatches:
        print(
            f"{row['skill_id']:>8}  {row['status']:<8}  {row['count']:>5}  "
            f"{row['recorded_name'][:30]:<32}  {row['canonical_name']}"
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--runtime", default=str(ROOT.parent / "uma_runtime"), help="uma_runtime root to scan")
    parser.add_argument("--master-map", default=str(ROOT / "data" / "master_map.json"), help="master_map.json path")
    parser.add_argument("--since", default=None, help="Only audit career logs modified after this date (YYYY-MM-DD)")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of a human-readable report")
    args = parser.parse_args()

    since_dt = None
    if args.since:
        since_dt = datetime.strptime(args.since, "%Y-%m-%d")

    result = audit(Path(args.runtime), Path(args.master_map), since_dt=since_dt)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0
    print_report(result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
