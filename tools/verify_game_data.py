"""Verify extracted simulator game-data JSON files.

Usage:
    python -m tools.verify_game_data
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RUNTIME_DIR = PROJECT_ROOT / "uma_runtime"


def load_json(path: Path, default: Any):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def find_runtime_skill_failures():
    ids = set()
    for path in sorted(RUNTIME_DIR.rglob("skill_failures.json")) if RUNTIME_DIR.exists() else []:
        data = load_json(path, {})
        for key in (data.get("skills") or {}):
            try:
                ids.add(int(key))
            except (TypeError, ValueError):
                continue
    return ids


def main():
    support = load_json(DATA_DIR / "support_card_bonuses.json", {})
    growth = load_json(DATA_DIR / "chara_growth_rates.json", {})
    skills = load_json(DATA_DIR / "skill_activation_data.json", {})
    training = load_json(DATA_DIR / "training_facility_curves.json", {})
    demands = load_json(DATA_DIR / "race_distance_demands.json", {})
    real_training = load_json(DATA_DIR / "real_training_snapshots.json", {})
    real_race = load_json(DATA_DIR / "real_race_snapshots.json", {})
    real_shop = load_json(DATA_DIR / "real_shop_snapshots.json", {})
    support_list = load_json(DATA_DIR / "support_list.json", {})
    chara_list = load_json(DATA_DIR / "chara_list.json", {})
    master_map = load_json(DATA_DIR / "master_map.json", {})

    missing_support = sorted(str(key) for key in support_list if str(key) not in support)
    missing_chara = sorted(str(key) for key in chara_list if str(key) not in growth)
    master_skill_ids = set()
    for key in (master_map.get("skill") or {}):
        try:
            master_skill_ids.add(int(key))
        except (TypeError, ValueError):
            continue
    activation_skill_ids = {int(key) for key in skills if str(key).isdigit()}
    missing_master_skills = sorted(master_skill_ids - activation_skill_ids)
    runtime_skill_failures = find_runtime_skill_failures()
    missing_failed_skills = sorted(runtime_skill_failures - activation_skill_ids)

    facilities = (training.get("facilities") or {})
    demand_entries = (demands.get("entries") or {})
    real_snapshots = real_training.get("snapshots") or []
    real_commands = sum(len(snapshot.get("commands") or []) for snapshot in real_snapshots)
    real_race_results = real_race.get("result_samples") or []
    real_race_fields = real_race.get("field_samples") or []
    real_shop_summary = real_shop.get("summary") or {}

    print("=== Extracted Game Data ===")
    print(f"support_card_bonuses:    {len(support):5d} records")
    print(f"chara_growth_rates:      {len(growth):5d} records")
    print(f"skill_activation_data:   {len(skills):5d} records")
    print(f"training_facility_curves:{len(facilities):5d} facilities")
    print(f"race_distance_demands:   {len(demand_entries):5d} profiles")
    print(f"real_training_snapshots: {len(real_snapshots):5d} snapshots / {real_commands} commands")
    print(f"real_race_snapshots:     {len(real_race_results):5d} results / {len(real_race_fields)} fields")
    print(
        "real_shop_snapshots:     "
        f"{int(real_shop_summary.get('snapshots') or 0):5d} snapshots / "
        f"{int(real_shop_summary.get('buy_events') or 0)} buys / "
        f"{int(real_shop_summary.get('use_events') or 0)} uses / "
        f"{len(real_shop_summary.get('rival_programs') or {})} rival ids"
    )
    print()
    print(f"support_list missing bonuses:        {len(missing_support)}")
    print(f"chara_list missing growth records:   {len(missing_chara)}")
    print(f"master_map skills missing activation:{len(missing_master_skills)}")
    print(f"runtime failed skills missing data:  {len(missing_failed_skills)}")

    if missing_support:
        print("first missing support ids:", ", ".join(missing_support[:20]))
    if missing_chara:
        print("first missing chara ids:", ", ".join(missing_chara[:20]))
    if missing_master_skills:
        print("first missing master skill ids:", ", ".join(str(x) for x in missing_master_skills[:20]))
    if missing_failed_skills:
        print("first missing failed skill ids:", ", ".join(str(x) for x in missing_failed_skills[:20]))

    required_facilities = {"speed", "stamina", "power", "guts", "wit"}
    missing_facilities = required_facilities - set(facilities)
    if missing_facilities:
        raise SystemExit(f"missing training facilities: {sorted(missing_facilities)}")
    if not demand_entries:
        raise SystemExit("race_distance_demands has no entries")
    if real_race and not real_race_results:
        raise SystemExit("real_race_snapshots has no result samples")
    if real_shop and not real_shop_summary.get("buy_events"):
        raise SystemExit("real_shop_snapshots has no buy events")
    if missing_support or missing_chara:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
