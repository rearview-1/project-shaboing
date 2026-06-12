"""Extract public Umamusume game data into simulator-ready JSON files.

Sources:
  - GameTora public data manifest:
    https://gametora.com/data/manifests/umamusume.json
  - GameTora URA scenario page for base training values.

The output schemas are intentionally stable because career_simulator.py and
skills.py consume these files directly.
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
GAMETORA_BASE = "https://gametora.com"
MANIFEST_URL = f"{GAMETORA_BASE}/data/manifests/umamusume.json"

STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")
APTITUDE_KEYS = (
    "turf",
    "dirt",
    "sprint",
    "mile",
    "medium",
    "long",
    "front",
    "pace",
    "late",
    "end",
)

SUPPORT_EFFECT_KEYS = {
    1: "friendship_bonus",
    2: "mood_effect",
    3: "speed_bonus",
    4: "stamina_bonus",
    5: "power_bonus",
    6: "guts_bonus",
    7: "wit_bonus",
    8: "training_effectiveness",
    9: "initial_speed",
    10: "initial_stamina",
    11: "initial_power",
    12: "initial_guts",
    13: "initial_wit",
    14: "initial_friendship",
    15: "race_bonus",
    16: "fan_bonus",
    17: "hint_levels",
    18: "hint_freq",
    19: "specialty_priority",
    20: "max_speed",
    21: "max_stamina",
    22: "max_power",
    23: "max_guts",
    24: "max_wit",
    25: "event_recovery",
    26: "event_effectiveness",
    27: "failure_protection",
    28: "energy_cost_reduction",
    29: "minigame_effectiveness",
    30: "skill_pt_bonus",
    31: "wit_friendship_recovery",
    33: "hint_quantity_bonus",
}

EFFECT_TYPE_KEYS = {
    1: "speed_stat_up",
    2: "stamina_stat_up",
    3: "power_stat_up",
    4: "guts_stat_up",
    5: "wit_stat_up",
    6: "change_strategy",
    8: "field_of_view",
    9: "stamina_recovery",
    10: "start_reaction",
    13: "rush_time",
    14: "start_delay",
    21: "current_speed",
    22: "current_speed",
    27: "target_speed",
    28: "lane_movement",
    29: "rush_chance",
    31: "acceleration",
    32: "all_stats",
    35: "lane_change",
    37: "random_rare_skill",
    38: "debuff_immunity",
    48: "zenkai_spurt_acceleration",
    501: "carnival_points",
    502: "carnival_stat",
    503: "carnival_motivation",
}

SUPPORT_LEVELS = (1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50)
MAX_LEVEL_BY_RARITY = {
    1: [20, 25, 30, 35, 40],  # R
    2: [25, 30, 35, 40, 45],  # SR
    3: [30, 35, 40, 45, 50],  # SSR
}
RARITY_NAME = {1: "R", 2: "SR", 3: "SSR"}


def _get_json(url: str) -> Any:
    response = requests.get(url, headers={"User-Agent": "SweepyDataExtractor/1.0"}, timeout=60)
    response.raise_for_status()
    return response.json()


def _load_gametora_key(manifest: dict[str, str], key: str) -> Any:
    digest = manifest[key]
    return _get_json(f"{GAMETORA_BASE}/data/umamusume/{key}.{digest}.json")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _load_existing_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}


def _backup_existing(path: Path, backup_root: Path, timestamp: str) -> Path | None:
    if not path.exists():
        return None
    backup_root.mkdir(parents=True, exist_ok=True)
    dest = backup_root / f"{path.name}.{timestamp}.bak"
    shutil.copy2(path, dest)
    return dest


def _diff_top_level_keys(old: Any, new: Any) -> tuple[list[str], list[str]]:
    if not isinstance(old, dict) or not isinstance(new, dict):
        return [], []
    old_keys = {str(key) for key in old}
    new_keys = {str(key) for key in new}
    return sorted(new_keys - old_keys), sorted(old_keys - new_keys)


def _slug_name(name: str) -> str:
    return " ".join(str(name or "").split())


def _support_name(card: dict[str, Any]) -> str:
    return _slug_name(card.get("char_name") or card.get("name_en") or card.get("name_jp") or "")


def _chara_name(card: dict[str, Any]) -> str:
    return _slug_name(card.get("name_en") or card.get("name_jp") or "")


def _current_effects(effect_rows: list[list[int]], max_level: int) -> dict[str, int]:
    out: dict[str, int] = {key: 0 for key in SUPPORT_EFFECT_KEYS.values()}
    for row in effect_rows or []:
        if not row:
            continue
        effect_id = int(row[0] or 0)
        key = SUPPORT_EFFECT_KEYS.get(effect_id)
        if not key:
            continue
        current = 0
        for level, value in zip(SUPPORT_LEVELS, row[1:]):
            if level > max_level:
                break
            if value is not None and int(value) >= 0:
                current = int(value)
        out[key] = current
    return out


def _apply_unique_effects(base: dict[str, int], unique: dict[str, Any], max_level: int) -> tuple[dict[str, int], list[dict[str, Any]]]:
    effects = dict(base)
    unique_rows = []
    if not isinstance(unique, dict):
        return effects, unique_rows
    unlock_level = int(unique.get("level") or 0)
    for raw in unique.get("effects") or []:
        if not isinstance(raw, dict):
            continue
        effect_id = int(raw.get("type") or 0)
        value = int(raw.get("value") or 0)
        key = SUPPORT_EFFECT_KEYS.get(effect_id, f"effect_{effect_id}")
        row = {"type": effect_id, "key": key, "value": value, "unlock_level": unlock_level}
        unique_rows.append(row)
        if unlock_level and max_level >= unlock_level and key in effects:
            effects[key] = int(effects.get(key) or 0) + value
    return effects, unique_rows


def build_support_card_bonuses(support_cards: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for card in sorted(support_cards, key=lambda item: int(item.get("support_id") or 0)):
        support_id = int(card.get("support_id") or 0)
        if not support_id:
            continue
        rarity = int(card.get("rarity") or 0)
        max_levels = MAX_LEVEL_BY_RARITY.get(rarity, MAX_LEVEL_BY_RARITY[3])
        unique = card.get("unique") if isinstance(card.get("unique"), dict) else {}
        lb_levels = []
        for lb, max_level in enumerate(max_levels):
            raw_effects = _current_effects(card.get("effects") or [], max_level)
            effects, unique_rows = _apply_unique_effects(raw_effects, unique, max_level)
            lb_levels.append({"lb": lb, "max_level": max_level, **effects})
        out[str(support_id)] = {
            "support_card_id": support_id,
            "name": card.get("char_name") or card.get("name_en") or card.get("name_jp") or "",
            "title": card.get("title_en") or card.get("title_ja") or "",
            "type": str(card.get("type") or "").title(),
            "rarity": RARITY_NAME.get(rarity, str(rarity)),
            "lb_levels": lb_levels,
            "event_skills": [int(x) for x in card.get("event_skills") or [] if x],
            "hint_skills": [int(x) for x in (card.get("hints") or {}).get("hint_skills") or [] if x],
            "unique_effects": unique_rows if unique else [],
            "source_url": f"{GAMETORA_BASE}/umamusume/supports/{card.get('url_name')}",
        }
    return out


def build_support_list(support_cards: list[dict[str, Any]]) -> dict[str, Any]:
    """Build the lightweight support index used by UI/search code.

    `support_card_bonuses.json` carries the full simulator data, but several
    app paths use `support_list.json` for fast card names/types. Keep both
    generated from the same upstream payload so newly released cards appear
    everywhere after one update command.
    """
    out: dict[str, Any] = {}
    for card in sorted(support_cards, key=lambda item: int(item.get("support_id") or 0)):
        support_id = int(card.get("support_id") or 0)
        if not support_id:
            continue
        rarity = int(card.get("rarity") or 0)
        out[str(support_id)] = {
            "name": _support_name(card),
            "rarity": RARITY_NAME.get(rarity, str(rarity)),
            "type": str(card.get("type") or "").title(),
        }
    return out


def build_chara_growth_rates(character_cards: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for card in sorted(character_cards, key=lambda item: int(item.get("card_id") or 0)):
        card_id = int(card.get("card_id") or 0)
        if not card_id:
            continue
        growth = {stat: int(value or 0) for stat, value in zip(STAT_KEYS, card.get("stat_bonus") or [])}
        stats = {stat: int(value or 0) for stat, value in zip(STAT_KEYS, card.get("base_stats") or [])}
        aptitudes = {key: str(value or "") for key, value in zip(APTITUDE_KEYS, card.get("aptitude") or [])}
        out[str(card_id)] = {
            "name": _slug_name(card.get("name_en") or card.get("name_jp") or ""),
            "title": card.get("title_en_gl") or card.get("title") or "",
            "growth_rates": growth,
            "base_aptitudes": aptitudes,
            "initial_stats": stats,
            "skills_unique": [int(x) for x in card.get("skills_unique") or [] if x],
            "skills_innate": [int(x) for x in card.get("skills_innate") or [] if x],
            "skills_awakening": [int(x) for x in card.get("skills_awakening") or [] if x],
            "source_url": f"{GAMETORA_BASE}/umamusume/characters/{card.get('url_name')}",
        }
    return out


def build_chara_list(character_cards: list[dict[str, Any]]) -> dict[str, str]:
    """Build the lightweight trainee index used by UI/search code."""
    out: dict[str, str] = {}
    for card in sorted(character_cards, key=lambda item: int(item.get("card_id") or 0)):
        card_id = int(card.get("card_id") or 0)
        if not card_id:
            continue
        out[str(card_id)] = _chara_name(card)
    return out


def build_master_map(skills: list[dict[str, Any]], existing: dict[str, Any] | None = None) -> dict[str, Any]:
    """Refresh skill names while preserving hand-maintained race/scenario maps."""
    out = dict(existing or {})
    out["skill"] = {
        str(int(skill.get("id") or 0)): skill.get("name_en") or skill.get("enname") or skill.get("jpname") or ""
        for skill in sorted(skills, key=lambda item: int(item.get("id") or 0))
        if int(skill.get("id") or 0)
    }
    return out


def _skill_color(rarity: int) -> str:
    if rarity == 2:
        return "gold"
    if rarity in (3, 4, 5):
        return "unique"
    if rarity == 6:
        return "evolution"
    return "white"


def _effect_summary(condition_groups: list[dict[str, Any]]) -> tuple[str, float, int | None, str]:
    best_type = "none"
    best_value = 0
    base_time = None
    category = "passive"
    for group in condition_groups or []:
        if base_time is None and group.get("base_time") is not None:
            base_time = int(group.get("base_time") or 0)
        for effect in group.get("effects") or []:
            effect_id = int(effect.get("type") or 0)
            value = int(effect.get("value") or 0)
            effect_type = EFFECT_TYPE_KEYS.get(effect_id, f"effect_{effect_id}")
            if abs(value) > abs(best_value):
                best_type = effect_type
                best_value = value
    if best_type in {"target_speed", "current_speed"}:
        category = "speed"
    elif best_type == "acceleration":
        category = "acceleration"
    elif best_type == "stamina_recovery":
        category = "recovery" if best_value >= 0 else "debuff"
    elif best_type.endswith("_stat_up") or best_type == "all_stats":
        category = "passive"
    elif best_value < 0:
        category = "debuff"
    return best_type, round(best_value / 10000, 4), base_time, category


def build_skill_activation_data(skills: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for skill in sorted(skills, key=lambda item: int(item.get("id") or 0)):
        skill_id = int(skill.get("id") or 0)
        if not skill_id:
            continue
        groups = skill.get("condition_groups") or []
        conditions = []
        for group in groups:
            parts = []
            if group.get("precondition"):
                parts.append(str(group.get("precondition")))
            if group.get("condition"):
                parts.append(str(group.get("condition")))
            if parts:
                conditions.append(" AND ".join(parts))
        effect_type, magnitude, base_time, category = _effect_summary(groups)
        out[str(skill_id)] = {
            "skill_id": skill_id,
            "name": skill.get("name_en") or skill.get("enname") or skill.get("jpname") or "",
            "jp_name": skill.get("jpname") or "",
            "color": _skill_color(int(skill.get("rarity") or 0)),
            "category": category,
            "condition": " OR ".join(f"({item})" for item in conditions) if conditions else "always",
            "effect_type": effect_type,
            "effect_magnitude": magnitude,
            "duration_meters": None,
            "base_time_ms": base_time,
            "cost": int(skill.get("cost") or 0),
            "activation": int(skill.get("activation") or 0),
            "tags": list(skill.get("type") or []),
            "condition_groups": groups,
            "raw_effects": [
                effect
                for group in groups
                for effect in group.get("effects") or []
            ],
            "source": "GameTora public data manifest",
        }
    return out


def build_training_facility_curves() -> dict[str, Any]:
    # Trackblazer/Make a New Track has lower base facility gains than URA.
    # Values are stored directly instead of deriving from multipliers because
    # the game table has per-level rounding and energy changes.
    facilities = {
        "speed": {
            "1": {"speed": 8, "power": 4, "skill_pt": 2, "energy": -19},
            "2": {"speed": 9, "power": 4, "skill_pt": 2, "energy": -20},
            "3": {"speed": 10, "power": 4, "skill_pt": 2, "energy": -21},
            "4": {"speed": 11, "power": 5, "skill_pt": 2, "energy": -23},
            "5": {"speed": 12, "power": 6, "skill_pt": 2, "energy": -25},
        },
        "stamina": {
            "1": {"stamina": 7, "guts": 3, "skill_pt": 2, "energy": -17},
            "2": {"stamina": 8, "guts": 3, "skill_pt": 2, "energy": -18},
            "3": {"stamina": 9, "guts": 3, "skill_pt": 2, "energy": -19},
            "4": {"stamina": 10, "guts": 4, "skill_pt": 2, "energy": -21},
            "5": {"stamina": 11, "guts": 5, "skill_pt": 2, "energy": -23},
        },
        "power": {
            "1": {"stamina": 4, "power": 6, "skill_pt": 2, "energy": -18},
            "2": {"stamina": 4, "power": 7, "skill_pt": 2, "energy": -19},
            "3": {"stamina": 4, "power": 8, "skill_pt": 2, "energy": -20},
            "4": {"stamina": 5, "power": 9, "skill_pt": 2, "energy": -22},
            "5": {"stamina": 6, "power": 10, "skill_pt": 2, "energy": -24},
        },
        "guts": {
            "1": {"speed": 3, "power": 3, "guts": 6, "skill_pt": 2, "energy": -20},
            "2": {"speed": 3, "power": 3, "guts": 7, "skill_pt": 2, "energy": -21},
            "3": {"speed": 3, "power": 3, "guts": 8, "skill_pt": 2, "energy": -22},
            "4": {"speed": 4, "power": 3, "guts": 9, "skill_pt": 2, "energy": -24},
            "5": {"speed": 4, "power": 4, "guts": 10, "skill_pt": 2, "energy": -26},
        },
        "wit": {
            "1": {"speed": 2, "wit": 6, "skill_pt": 3, "energy": 5},
            "2": {"speed": 2, "wit": 7, "skill_pt": 3, "energy": 5},
            "3": {"speed": 2, "wit": 8, "skill_pt": 3, "energy": 5},
            "4": {"speed": 3, "wit": 9, "skill_pt": 3, "energy": 5},
            "5": {"speed": 4, "wit": 10, "skill_pt": 3, "energy": 5},
        },
    }
    return {
        "source": "Trackblazer/Make a New Track facility table",
        "level_up_every_uses": 4,
        "level_multipliers": {str(level): 1.0 for level in range(1, 6)},
        "facilities": facilities,
        "partner_count_distribution": {
            "preferred_support_base_chance": 0.42,
            "nonpreferred_support_base_chance": 0.10,
            "specialty_priority_divisor": 500.0,
            "min_partners_per_tile": 1,
        },
    }


def build_race_distance_demands() -> dict[str, Any]:
    base_weights = {
        "sprint": {"speed": 0.95, "stamina": 0.35, "power": 0.90, "guts": 0.35, "wit": 0.45},
        "mile": {"speed": 0.90, "stamina": 0.55, "power": 0.85, "guts": 0.40, "wit": 0.55},
        "medium": {"speed": 0.85, "stamina": 0.90, "power": 0.80, "guts": 0.50, "wit": 0.50},
        "long": {"speed": 0.75, "stamina": 1.35, "power": 0.75, "guts": 0.65, "wit": 0.45},
    }
    style_adjust = {
        "front": {"stamina": 0.12, "power": 0.03, "wit": 0.05},
        "pace": {"stamina": 0.10, "power": 0.05, "wit": 0.03},
        "late": {"stamina": -0.05, "power": 0.12, "guts": 0.08},
        "end": {"stamina": -0.08, "power": 0.15, "guts": 0.10},
    }
    base_thresholds = {
        "junior": {"speed": 280, "stamina": 220, "power": 260, "guts": 180, "wit": 240},
        "classic": {"speed": 520, "stamina": 420, "power": 500, "guts": 320, "wit": 440},
        "senior": {"speed": 760, "stamina": 620, "power": 720, "guts": 460, "wit": 620},
    }
    out: dict[str, Any] = {
        "source": "Heuristic fallback calibrated from public mechanics guidance; manual_race_data overrides this when available.",
        "entries": {},
    }
    for distance, weights in base_weights.items():
        for style in ("front", "pace", "late", "end"):
            merged = dict(weights)
            for stat, delta in style_adjust[style].items():
                merged[stat] = round(max(0.1, merged[stat] + delta), 3)
            thresholds = {}
            for era, era_base in base_thresholds.items():
                era_threshold = {}
                for stat, value in era_base.items():
                    era_threshold[stat] = int(round(value * merged[stat]))
                thresholds[era] = era_threshold
            out["entries"][f"{distance}_{style}"] = {
                **merged,
                "thresholds": thresholds,
            }
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(DATA_DIR), help="Output data directory")
    parser.add_argument("--backup", action="store_true", help="Back up overwritten JSON files under data/backups/game_data_updates")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and diff data, but do not write files")
    args = parser.parse_args()

    out_dir = Path(args.out)
    existing_master = _load_existing_json(out_dir / "master_map.json")
    manifest = _get_json(MANIFEST_URL)
    support_cards = _load_gametora_key(manifest, "support-cards")
    character_cards = _load_gametora_key(manifest, "character-cards")
    skills = _load_gametora_key(manifest, "skills")

    outputs = {
        "support_list.json": build_support_list(support_cards),
        "support_card_bonuses.json": build_support_card_bonuses(support_cards),
        "chara_list.json": build_chara_list(character_cards),
        "chara_growth_rates.json": build_chara_growth_rates(character_cards),
        "master_map.json": build_master_map(skills, existing_master if isinstance(existing_master, dict) else {}),
        "skill_activation_data.json": build_skill_activation_data(skills),
        "training_facility_curves.json": build_training_facility_curves(),
        "race_distance_demands.json": build_race_distance_demands(),
    }
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_root = out_dir / "backups" / "game_data_updates"
    for name, payload in outputs.items():
        path = out_dir / name
        existing = _load_existing_json(path)
        added, removed = _diff_top_level_keys(existing, payload)
        if args.backup and not args.dry_run:
            backup_path = _backup_existing(path, backup_root, timestamp)
            if backup_path:
                print(f"backup {name} -> {backup_path}")
        if not args.dry_run:
            _write_json(path, payload)
        count = len(payload.get("entries", payload)) if isinstance(payload, dict) else len(payload)
        action = "would write" if args.dry_run else "wrote"
        print(f"{action} {path} ({count} records; +{len(added)} / -{len(removed)} ids)")
        if added:
            print("  new ids:", ", ".join(added[:20]) + (" ..." if len(added) > 20 else ""))
        if removed:
            print("  removed ids:", ", ".join(removed[:20]) + (" ..." if len(removed) > 20 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
