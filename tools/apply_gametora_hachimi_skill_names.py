"""Apply Sweepy/GameTora skill names to a Hachimi translation cache.

Hachimi translation updates can overwrite local edits in text_data_dict.json.
This script is intentionally idempotent: run it after any Hachimi translation
update and it will re-apply the GameTora-backed names from data/master_map.json
plus data/gametora_skill_overrides.json.

Name tables are patched from GameTora/Sweepy names. Skill descriptions in
category 48 are patched from the local Hachimi mechanics repo when available,
with GameTora condition data used only as a fallback for JP-only skills that
the local mechanics repo does not know yet.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path
from typing import Any


DEFAULT_JP_HACHIMI_DIR = Path(
    r"C:\Program Files (x86)\Steam\steamapps\common\UmamusumePrettyDerby_Jpn\hachimi"
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=4) + "\n", encoding="utf-8")


def discover_text_data_files(hachimi_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    for child in sorted(hachimi_dir.iterdir() if hachimi_dir.exists() else []):
        if not child.is_dir():
            continue
        if child.name != "localized_data" and not child.name.startswith("localized_data_"):
            continue
        path = child / "text_data_dict.json"
        if path.exists():
            candidates.append(path)
    return candidates


def load_skill_overrides(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = load_json(path)
    except Exception:
        return {}
    skills = data.get("skills") if isinstance(data, dict) else None
    return skills if isinstance(skills, dict) else {}


def load_mechanics_descriptions(hachimi_dir: Path, source_dir_name: str) -> dict[str, str]:
    path = hachimi_dir / source_dir_name / "text_data_dict.json"
    if not path.exists():
        return {}
    try:
        data = load_json(path)
    except Exception:
        return {}
    descriptions = data.get("48") if isinstance(data, dict) else None
    if not isinstance(descriptions, dict):
        return {}
    return {str(key): str(value) for key, value in descriptions.items() if isinstance(value, str)}


def build_skill_names(master_skill_names: dict[str, Any], overrides: dict[str, dict[str, Any]]) -> dict[str, str]:
    names = {str(key): str(value) for key, value in master_skill_names.items() if isinstance(value, str) and value}
    for skill_id, row in overrides.items():
        if not isinstance(row, dict):
            continue
        name = row.get("name")
        if isinstance(name, str) and name.strip():
            names[str(skill_id)] = name.strip()
    return names


def build_skill_factor_names(skill_names: dict[str, str]) -> dict[str, str]:
    """Build category-147 skill-factor names from full skill IDs.

    The game stores inherited skill-hint traits/sparks as:
        factor_id = floor(skill_id / 10) * 100 + stars

    Example:
        200592 Position Pilfer -> 2005901 / 2005902 / 2005903

    Hachimi can have the direct skill name in category 47 while still missing
    these derived category-147 factor rows. Newer JP skills then fall back to
    the original Japanese trait text in screens such as Preferred Trait
    Selection. Generate only normal skill ranges to avoid collisions with race
    and unique factor IDs.
    """

    grouped: dict[int, tuple[int, str]] = {}
    for raw_skill_id, name in skill_names.items():
        if not isinstance(name, str) or not name.strip():
            continue
        try:
            skill_id = int(raw_skill_id)
        except (TypeError, ValueError):
            continue
        if not 200000 <= skill_id < 500000:
            continue
        base = (skill_id // 10) * 100
        current = grouped.get(base)
        # In observed JP data the inherited trait uses the highest skill ID in
        # a shared base group: e.g. 210372 Rest and Rise -> 2103701..3, not
        # 210371 Miracle of Recreation.
        if current is None or skill_id > current[0]:
            grouped[base] = (skill_id, name.strip())

    factor_names: dict[str, str] = {}
    for base, (_skill_id, name) in grouped.items():
        for stars in (1, 2, 3):
            factor_names[str(base + stars)] = name
    return factor_names


def build_skill_descriptions(
    mechanics_descriptions: dict[str, str],
    overrides: dict[str, dict[str, Any]],
    known_master_skill_ids: set[str],
) -> dict[str, str]:
    descriptions = dict(mechanics_descriptions)
    for skill_id, row in overrides.items():
        skill_id = str(skill_id)
        if not isinstance(row, dict):
            continue
        text = row.get("mechanics_description") or row.get("plain_description")
        if isinstance(text, str) and text.strip():
            # Preserve Hachimi's richer mechanics text for skills it already
            # knows, but let GameTora fill/update newer skills missing from the
            # local master map.
            if skill_id not in descriptions or skill_id not in known_master_skill_ids:
                descriptions[skill_id] = text.strip()
    return descriptions


def patch_text_data(
    path: Path,
    skill_names: dict[str, str],
    skill_descriptions: dict[str, str],
    skill_factor_names: dict[str, str],
    *,
    backup: bool,
) -> dict[str, Any]:
    data = load_json(path)
    skills = data.get("47")
    if not isinstance(skills, dict):
        return {
            "path": str(path),
            "changed": False,
            "reason": "missing_skill_category_47",
            "skill_id_names": 0,
            "hint_names": 0,
            "skill_descriptions": 0,
        }
    descriptions = data.get("48")
    if not isinstance(descriptions, dict):
        descriptions = {}
        data["48"] = descriptions

    replacements: dict[str, str] = {}
    skill_id_updates = 0
    for raw_skill_id, game_tora_name in skill_names.items():
        skill_id = str(raw_skill_id)
        if not isinstance(game_tora_name, str) or not game_tora_name:
            continue
        old_name = skills.get(skill_id)
        if old_name == game_tora_name:
            continue
        skills[skill_id] = game_tora_name
        if isinstance(old_name, str) and old_name.strip():
            replacements[old_name] = game_tora_name
        skill_id_updates += 1

    hint_name_updates = 0
    # Category 147 is a name-only skill-hint/factor table using keys like
    # 2015401/2015402/2015403. Patch exact full-string values only; do not
    # rewrite descriptions or condition text.
    hint_names = data.get("147")
    if isinstance(hint_names, dict) and replacements:
        for key, value in list(hint_names.items()):
            if isinstance(value, str) and value in replacements:
                hint_names[key] = replacements[value]
                hint_name_updates += 1
    generated_factor_updates = 0
    if isinstance(hint_names, dict):
        for key, name in skill_factor_names.items():
            if not name:
                continue
            value = hint_names.get(key)
            if value == name:
                continue
            if value is None:
                hint_names[key] = name
                generated_factor_updates += 1
            elif isinstance(value, str) and value in replacements:
                hint_names[key] = replacements[value]
                generated_factor_updates += 1
    derived_updates = hint_name_updates + generated_factor_updates

    description_updates = 0
    for skill_id, description in skill_descriptions.items():
        if not description:
            continue
        if descriptions.get(skill_id) == description:
            continue
        descriptions[skill_id] = description
        description_updates += 1

    changed = bool(skill_id_updates or derived_updates or description_updates)
    backup_path = ""
    if changed:
        if backup:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            backup_file = path.with_suffix(path.suffix + f".bak_gametora_{stamp}")
            shutil.copy2(path, backup_file)
            backup_path = str(backup_file)
        write_json(path, data)

    return {
        "path": str(path),
        "changed": changed,
        "backup": backup_path,
        "skill_id_names": skill_id_updates,
        "hint_names": derived_updates,
        "generated_factor_names": generated_factor_updates,
        "skill_descriptions": description_updates,
        "sample_200491": (data.get("47") or {}).get("200491"),
        "sample_414011": (data.get("47") or {}).get("414011"),
        "sample_factor_2103701": (data.get("147") or {}).get("2103701"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-apply Sweepy/GameTora skill names to JP Hachimi text_data_dict.json files."
    )
    parser.add_argument(
        "--hachimi-dir",
        default=os.environ.get("SWEEPY_JP_HACHIMI_DIR") or str(DEFAULT_JP_HACHIMI_DIR),
        help="Path to the JP Hachimi directory. Defaults to the Steam JP install path.",
    )
    parser.add_argument(
        "--master-map",
        default=str(project_root() / "data" / "master_map.json"),
        help="Path to Sweepy's master_map.json.",
    )
    parser.add_argument(
        "--gametora-overrides",
        default=str(project_root() / "data" / "gametora_skill_overrides.json"),
        help="Optional GameTora skill override JSON generated by tools/extract_gametora_skill_overrides.py.",
    )
    parser.add_argument(
        "--mechanics-source-dir",
        default=os.environ.get("SWEEPY_HACHIMI_MECHANICS_SOURCE_DIR") or "localized_data",
        help="Hachimi localized_data directory to use as the mechanics-description source.",
    )
    parser.add_argument("--no-backup", action="store_true", help="Do not create .bak files before writing.")
    args = parser.parse_args()

    hachimi_dir = Path(args.hachimi_dir)
    master_map_path = Path(args.master_map)
    if not hachimi_dir.exists():
        print(f"ERROR: Hachimi dir not found: {hachimi_dir}")
        return 2
    if not master_map_path.exists():
        print(f"ERROR: master_map.json not found: {master_map_path}")
        return 2

    master_map = load_json(master_map_path)
    skill_names = master_map.get("skill") if isinstance(master_map, dict) else None
    if not isinstance(skill_names, dict) or not skill_names:
        print(f"ERROR: {master_map_path} does not contain a non-empty 'skill' map")
        return 2
    overrides = load_skill_overrides(Path(args.gametora_overrides))
    merged_skill_names = build_skill_names(skill_names, overrides)
    skill_factor_names = build_skill_factor_names(merged_skill_names)
    skill_descriptions = build_skill_descriptions(
        load_mechanics_descriptions(hachimi_dir, str(args.mechanics_source_dir)),
        overrides,
        {str(skill_id) for skill_id in skill_names},
    )

    files = discover_text_data_files(hachimi_dir)
    if not files:
        print(f"ERROR: no localized_data*/text_data_dict.json files found under {hachimi_dir}")
        return 2

    print(f"Using master map: {master_map_path}")
    print(f"Using GameTora overrides: {Path(args.gametora_overrides)} ({len(overrides)} skills)")
    print(f"Using mechanics source: {hachimi_dir / str(args.mechanics_source_dir) / 'text_data_dict.json'}")
    print(f"Using Hachimi dir: {hachimi_dir}")
    total_skill_updates = 0
    total_hint_name_updates = 0
    total_generated_factor_updates = 0
    total_description_updates = 0
    for path in files:
        result = patch_text_data(
            path,
            merged_skill_names,
            skill_descriptions,
            skill_factor_names,
            backup=not args.no_backup,
        )
        total_skill_updates += int(result.get("skill_id_names") or 0)
        total_hint_name_updates += int(result.get("hint_names") or 0)
        total_generated_factor_updates += int(result.get("generated_factor_names") or 0)
        total_description_updates += int(result.get("skill_descriptions") or 0)
        status = "changed" if result.get("changed") else "already current"
        print(f"{status}: {result['path']}")
        if result.get("backup"):
            print(f"  backup: {result['backup']}")
        if result.get("reason"):
            print(f"  reason: {result['reason']}")
        print(f"  skill names: {result.get('skill_id_names', 0)}")
        print(f"  hint names: {result.get('hint_names', 0)}")
        print(f"  generated factor names: {result.get('generated_factor_names', 0)}")
        print(f"  skill descriptions: {result.get('skill_descriptions', 0)}")
        print(f"  200491: {result.get('sample_200491')}")
        print(f"  414011: {result.get('sample_414011')}")
        print(f"  2103701: {result.get('sample_factor_2103701')}")

    print(
        "Done. "
        f"skill names updated={total_skill_updates}; "
        f"hint names updated={total_hint_name_updates}; "
        f"generated factor names updated={total_generated_factor_updates}; "
        f"skill descriptions updated={total_description_updates}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
