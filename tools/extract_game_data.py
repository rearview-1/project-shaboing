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
import math
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


def _slug_name(name: str) -> str:
    return " ".join(str(name or "").split())


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


def _scaled_gains(base: dict[str, int], multiplier: float) -> dict[str, int]:
    out = {}
    for key, value in base.items():
        if key == "energy":
            out[key] = value
        else:
            out[key] = int(math.floor(value * multiplier))
    return out


def build_training_facility_curves() -> dict[str, Any]:
    # Current URA/global base values from GameTora's URA Finale page. MANT uses
    # the same training stat-gain formula; scenario-specific shop/items are
    # modeled separately in the simulator.
    base_level_1 = {
        "speed": {"speed": 11, "power": 6, "skill_pt": 4, "energy": -21},
        "stamina": {"stamina": 10, "guts": 6, "skill_pt": 4, "energy": -19},
        "power": {"stamina": 6, "power": 9, "skill_pt": 4, "energy": -20},
        "guts": {"speed": 5, "power": 5, "guts": 8, "skill_pt": 4, "energy": -22},
        "wit": {"speed": 2, "wit": 10, "skill_pt": 5, "energy": 5},
    }
    multipliers = {1: 1.00, 2: 1.25, 3: 1.50, 4: 1.75, 5: 2.00}
    facilities = {
        stat: {
            str(level): _scaled_gains(base, mult)
            for level, mult in multipliers.items()
        }
        for stat, base in base_level_1.items()
    }
    return {
        "source": "GameTora URA Finale base values + public training-level multipliers",
        "level_up_every_uses": 4,
        "level_multipliers": {str(k): v for k, v in multipliers.items()},
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
    args = parser.parse_args()

    out_dir = Path(args.out)
    manifest = _get_json(MANIFEST_URL)
    support_cards = _load_gametora_key(manifest, "support-cards")
    character_cards = _load_gametora_key(manifest, "character-cards")
    skills = _load_gametora_key(manifest, "skills")

    outputs = {
        "support_card_bonuses.json": build_support_card_bonuses(support_cards),
        "chara_growth_rates.json": build_chara_growth_rates(character_cards),
        "skill_activation_data.json": build_skill_activation_data(skills),
        "training_facility_curves.json": build_training_facility_curves(),
        "race_distance_demands.json": build_race_distance_demands(),
    }
    for name, payload in outputs.items():
        _write_json(out_dir / name, payload)
        count = len(payload.get("entries", payload)) if isinstance(payload, dict) else len(payload)
        print(f"wrote {out_dir / name} ({count} records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
