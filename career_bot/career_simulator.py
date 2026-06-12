"""Career simulator for relentless testing of bot decisions.

Drives the real MANT training scorer through a synthetic career
(78 turns) so I can verify that a code change actually lifts the bot's
outcomes without waiting for real game runs.

DESIGN GOALS:
  - Use the REAL training scoring path (`MantStrategy._score_command`,
    `_speed_priority_bonus`, `_checkpoint_pressure_bonus`, etc.) so
    changes to those functions reflect immediately in sim outcomes.
  - Synthetic training-tile generator that matches the deck composition
    (more cards on a stat → more partners on that tile + better
    rainbow odds).
  - Race outcome model uses the user's `manual_race_data.json` median
    winning stats as the win threshold — a realistic stat-vs-race
    check.
  - HP / mood / SP dynamics modeled at a level faithful enough that
    bot's recovery decisions matter.
  - NOT modeled: server RNG, exact hidden race sim, exact support/event
    trigger order, or action packet validation. Treat output as a calibrated
    game-data proxy, not a byte-perfect game replay.

USAGE:
    sim = CareerSimulator(preset=<dict>, deck=<list[dict]>, trainee_card_id=1004)
    result = sim.run()
    # result.final_stats, result.rating_score, result.rank, result.g1_wins, ...

The simulator returns deterministic results when seeded, so I can A/B
test code changes by running with the same seed before and after.
"""

import csv
import copy
import json
import os
import random
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from statistics import median
from typing import Any

from career_bot.items import (
    DISPLAY_TO_ID,
    ENERGY_ITEMS,
    ITEM_NAMES,
    MEGAPHONE_TIERS,
    SERVER_ITEM_INVENTORY_CAP,
    SHOP_ITEM_COSTS,
    SUMMER_CAMP_TURNS,
)
from career_bot.mant_fixed_events import MANT_STATIC_FIXED_EVENTS
from career_bot.rating import RATING_BADGE_MINIMA, estimate_rating_score

try:
    from career_bot.sim_observations import (
        load_runtime_event_observations,
        load_runtime_shop_summary,
        load_runtime_training_snapshots,
        merge_shop_summaries,
    )
except Exception:  # pragma: no cover - simulator can still run from static data
    load_runtime_event_observations = None
    load_runtime_shop_summary = None
    load_runtime_training_snapshots = None
    merge_shop_summaries = None


# In-game maximum stat value — HARD CEILING, applies to all 5 stats
# (speed/stamina/power/guts/wit). No code path in the sim or strategy
# may produce a stat > 1200. Every state-application site uses
# `min(STAT_CAP, ...)` and the strategy's `stat_hard_cap` is bounded
# by the auto-tuner to [1100, 1200]. The 1100 late-week soft clamp is
# a separate, less-strict policy and does NOT change this ceiling.
# Pinned by `tests/test_stat_hard_cap_1200_policy.py`.
STAT_CAP = 1200
TURN_FINISH = 78
CAREER_INVISIBLE_STAT_BONUS = 400
EXACT_CONTEXT_MIN_RACE_SAMPLES = 250
RACE_GRADE_REWARDS = {
    # In-game race clear rewards before support-card race bonus.
    # The stat reward is applied to one random stat, not spread across all 5.
    "PRE-OP": {"stat": 5, "skill_point": 20},
    "OP": {"stat": 5, "skill_point": 20},
    "G3": {"stat": 8, "skill_point": 25},
    "G2": {"stat": 8, "skill_point": 25},
    "G1": {"stat": 10, "skill_point": 35},
}

# Approximate per-turn training-gain ranges by stat type and rainbow
# state. Calibrated against user's actual career_log data — real bot
# careers end with stat_sum ~3500-3900 across 78 turns.
TRAINING_GAIN_BANDS = {
    # (no_rainbow_low, no_rainbow_high, rainbow_low, rainbow_high)
    "speed":    (12, 20, 26, 40),
    "stamina":  (12, 20, 26, 40),
    "power":    (12, 20, 26, 40),
    "guts":     (14, 22, 28, 42),
    "wit":      (10, 18, 22, 34),
}

# Per-stat motivation multiplier (mood 5/Great = 1.2; mood 4/Good = 1.1;
# mood 3/Normal = 1.0; mood 2/Bad = 0.9; mood 1/Awful = 0.8).
MOOD_MULTIPLIERS = {5: 1.2, 4: 1.1, 3: 1.0, 2: 0.9, 1: 0.8}
MOOD_BASE_EFFECT = {5: 0.20, 4: 0.10, 3: 0.0, 2: -0.10, 1: -0.20}

# HP cost per training, by stat. Wit recovers some HP. Calibrated lower
# than initial guess — real bot rarely rests more than 3-4 times in
# 78 turns, so per-training drain should be modest.
HP_COSTS = {"speed": 10, "stamina": 13, "power": 11, "guts": 11, "wit": -10}

STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")
STAT_TO_STATE_KEY = {"speed": "speed", "stamina": "stamina", "power": "power", "guts": "guts", "wit": "wiz"}
STATE_TO_STAT_KEY = {"speed": "speed", "stamina": "stamina", "power": "power", "guts": "guts", "wiz": "wit"}
COMMAND_ID_TO_STAT = {
    101: "speed",
    601: "speed",
    105: "stamina",
    602: "stamina",
    102: "power",
    603: "power",
    103: "guts",
    604: "guts",
    106: "wit",
    605: "wit",
}
STAT_TO_COMMAND_ID = {"speed": 101, "stamina": 105, "power": 102, "guts": 103, "wit": 106}
TARGET_TYPE_TO_STATE_KEY = {1: "speed", 2: "stamina", 3: "power", 4: "guts", 5: "wiz"}
STATE_KEY_TO_TARGET_TYPE = {value: key for key, value in TARGET_TYPE_TO_STATE_KEY.items()}
SUPPORT_TYPE_ALIASES = {
    "speed": "speed",
    "stamina": "stamina",
    "power": "power",
    "guts": "guts",
    "wit": "wit",
    "wisdom": "wit",
    "int": "wit",
    "intelligence": "wit",
    "friend": "friend",
    "friends": "friend",
    "pal": "friend",
    "group": "group",
}
ITEM_ID_TO_NAME = {int(item_id): name for item_id, name in ITEM_NAMES.items()}
ITEM_NAME_TO_ID = {name: int(item_id) for item_id, name in ITEM_NAMES.items()}
ITEM_COST_BY_ID = {int(DISPLAY_TO_ID[name]): int(cost) for name, cost in SHOP_ITEM_COSTS.items() if name in DISPLAY_TO_ID}
ENERGY_ITEM_IDS = {int(DISPLAY_TO_ID[name]): int(value) for name, value in ENERGY_ITEMS.items() if name in DISPLAY_TO_ID}
MEGAPHONE_ITEM_IDS = {int(DISPLAY_TO_ID[name]): tuple(value) for name, value in MEGAPHONE_TIERS.items() if name in DISPLAY_TO_ID}
# Multiplier applied to gain values from real-bot training snapshots.
# Original calibration of 1.28 was matched to old-bot data when real runs
# landed around A/A+. The bot has since improved substantially (real
# distribution: 9 SS / 55 S+ / 60 S / 15 A+ / 1 UG out of 140 finished),
# so the previous scale undershoots by ~2,200 rating per career.
# 10-sim sweep across scales 1.65 / 1.85 / 2.00 against the user's
# production preset:
#   1.65 → mean 15,464 (0% SS, 10% S+, 80% S)  — too conservative
#   1.85 → mean 16,347 (0% SS, 70% S+, 30% S)  — matches real S+ centroid
#   2.00 → mean 16,391 (10% SS, 60% S+)         — slight over-shoot of S+
# Picked 1.85 to match real-bot S+ centroid without inflating SS rate.
# Overridable via `sim_real_training_gain_scale`.
REAL_TRAINING_GAIN_SCALE_DEFAULT = 1.85
# Real training snapshots already include deck/support-card quality from
# actual command payloads. Adding another deck-quality multiplier was off
# previously to keep the sim from predicting SS/UG while reality was
# A/A+. With the bot's improved real distribution, a small deck-quality
# bonus is appropriate again — capped low so high-deck users don't get
# over-predicted vs their actual outcomes.
REAL_TRAINING_GAIN_SCALE_MAX_DECK_BONUS = 0.10
REAL_TRAINING_GAIN_SCALE_DECK_QUALITY_BASELINE = 3.0
REAL_TRAINING_GAIN_SCALE_DECK_QUALITY_STEP = 0.08
SIM_SKILL_RATING_SCALE_DEFAULT = 0.75
SIM_TOTAL_SKILL_PURCHASE_MAX_DEFAULT = 21
SIM_SKILL_RATING_SCORE_CAP_DEFAULT = 4200
SIM_EVENT_TARGET_COUNT = 34

# Main race reward events observed in live career logs. These are the rows
# that apply the actual race stat/SP reward after `race_result`; later same-turn
# event rows can be epithets or scenario/chara events and are modeled elsewhere.
RACE_REWARD_EVENT_IDS = {1011, 7004, 7005, 7006}
RACE_REWARD_STORY_IDS = {"400000035", "501020509", "501020708", "501020709"}
CLIMAX_RACE_REWARD_BY_TURN = {
    74: ("400004051", 203102),
    76: ("400004061", 203104),
    78: ("400004071", 203106),
}
CLIMAX_RACE_REWARD_STORY_IDS = {story_id for story_id, _event_id in CLIMAX_RACE_REWARD_BY_TURN.values()}
CLIMAX_RACE_REWARD_EVENT_IDS = {event_id for _story_id, event_id in CLIMAX_RACE_REWARD_BY_TURN.values()}
CLIMAX_RACE_REWARD_ITEM_MULTIPLIERS = {
    11001: 1.20,  # Artisan Cleat Hammer
    11002: 1.35,  # Master Cleat Hammer
    11003: 1.10,
}

EVENT_STAT_KEY_MAP = {
    "Speed": "speed",
    "Stamina": "stamina",
    "Power": "power",
    "Guts": "guts",
    "Wisdom": "wiz",
}
OBSERVED_DELTA_TO_EVENT_EFFECT_KEY = {
    "speed": "Speed",
    "stamina": "Stamina",
    "power": "Power",
    "guts": "Guts",
    "wit": "Wisdom",
    "skill_point": "Skill Pts",
    "hp": "HP",
    "motivation": "Mood",
}

SCENARIO_EVENT_TURN_WINDOWS = {
    1, 2, 25, 26, 37, 38, 49, 50, 61, 62, 73, 74, 78,
}

SIM_SKIP_OBSERVED_EVENT_NAMES = {
    "victory",
    "solidshowing",
    "defeat",
}

FRIEND_RECREATION_STORY_PREFIXES = ("809",)
FRIEND_RECREATION_DEFAULT_MAX_USES = 5
SIM_STAT_RECREATION_FRIEND_CARDS = {
    30021,  # Tazuna Hayakawa
    30036,  # Riko Kashimoto
    30052,  # Light Hello
    30160,  # Mei Satake
    30257,  # Tucker Bryne
    30276,  # Kiyoko Hoshina
}

STAT_ITEM_GAINS = {
    1001: ("speed", 3), 1002: ("stamina", 3), 1003: ("power", 3), 1004: ("guts", 3), 1005: ("wiz", 3),
    1101: ("speed", 7), 1102: ("stamina", 7), 1103: ("power", 7), 1104: ("guts", 7), 1105: ("wiz", 7),
    1201: ("speed", 15), 1202: ("stamina", 15), 1203: ("power", 15), 1204: ("guts", 15), 1205: ("wiz", 15),
}
TRAINING_APP_ITEMS = {
    5001: "speed",
    5002: "stamina",
    5003: "power",
    5004: "guts",
    5005: "wit",
}
TARGET_STAT_ITEM_IDS = {
    "speed": (1201, 1101, 1001),
    "stamina": (1202, 1102, 1002),
    "power": (1203, 1103, 1003),
    "guts": (1204, 1104, 1004),
    "wit": (1205, 1105, 1005),
}
TARGET_STAT_APP_IDS = {
    "speed": 5001,
    "stamina": 5002,
    "power": 5003,
    "guts": 5004,
    "wit": 5005,
}
ANKLE_WEIGHT_ITEMS = {
    9001: "speed",
    9002: "stamina",
    9003: "power",
    9004: "guts",
}
MOOD_ITEM_GAINS = {
    2301: 1, 2302: 2, 3001: 1, 3101: 2, 4001: 1, 4004: 1,
}
RACE_REWARD_BUFF_ITEMS = {11001: 1.12, 11002: 1.25, 11003: 1.08}
LEGACY_NODES = ("self", "p1", "p2")
LEGACY_BLUE_STAT_BONUS = {1: 5, 2: 12, 3: 21}
LEGACY_STAT_NAME_TO_STATE_KEY = {
    "speed": "speed",
    "stamina": "stamina",
    "power": "power",
    "guts": "guts",
    "wit": "wiz",
    "int": "wiz",
    "wisdom": "wiz",
}
LEGACY_APTITUDE_NAME_TO_KEY = {
    "turf": "turf",
    "grass": "turf",
    "dirt": "dirt",
    "short": "sprint",
    "sprint": "sprint",
    "mile": "mile",
    "medium": "medium",
    "middle": "medium",
    "long": "long",
    "front": "front",
    "front runner": "front",
    "pace": "pace",
    "pace chaser": "pace",
    "late": "late",
    "late surger": "late",
    "end": "end",
    "end closer": "end",
}
APTITUDE_RANK_VALUE = {"G": 0, "F": 1, "E": 2, "D": 3, "C": 4, "B": 5, "A": 6, "S": 7}
APTITUDE_VALUE_RANK = {value: key for key, value in APTITUDE_RANK_VALUE.items()}
LINEAGE_NODE_WEIGHTS = {"self": 0.30, "p1": 0.22, "p2": 0.22}

STYLE_NUM_TO_KEY = {1: "front", 2: "pace", 3: "late", 4: "end"}
STYLE_KEY_TO_NUM = {value: key for key, value in STYLE_NUM_TO_KEY.items()}
APTITUDE_MULTIPLIERS = {
    "S": 1.06,
    "A": 1.00,
    "B": 0.94,
    "C": 0.86,
    "D": 0.76,
    "E": 0.64,
    "F": 0.50,
    "G": 0.35,
    8: 1.06,
    7: 1.00,
    6: 0.94,
    5: 0.86,
    4: 0.76,
    3: 0.64,
    2: 0.50,
    1: 0.35,
}
RACE_WEIGHT_PROFILES = {
    "sprint": {"speed": 1.25, "power": 1.00, "wit": 0.55, "stamina": 0.42, "guts": 0.35},
    "mile": {"speed": 1.15, "power": 0.92, "wit": 0.62, "stamina": 0.62, "guts": 0.38},
    "medium": {"speed": 1.05, "stamina": 0.90, "power": 0.86, "wit": 0.55, "guts": 0.45},
    "long": {"stamina": 1.25, "speed": 0.95, "power": 0.76, "guts": 0.58, "wit": 0.48},
    "": {"speed": 1.00, "stamina": 0.80, "power": 0.80, "wit": 0.50, "guts": 0.40},
}

# G1 calendar — loaded from the real RaceCatalog at simulator init,
# not hardcoded. See `_load_g1_calendar()`. The constant below is a
# fallback in case the catalog isn't available (test environments).
_FALLBACK_G1_CALENDAR = [
    (23, 623, "Hanshin Juvenile Fillies", "mile", "junior"),
    (24, 625, "Hopeful Stakes", "medium", "junior"),
    (31, 163, "Satsuki Sho", "medium", "classic"),
    (33, 164, "NHK Mile Cup", "mile", "classic"),
    (34, 166, "Tokyo Yushun (Japanese Derby)", "medium", "classic"),
    (44, 168, "Kikuka Sho", "long", "classic"),
    (45, 77, "Queen Elizabeth II Cup", "medium", "classic"),
    (46, 78, "Mile Championship", "mile", "classic"),
    (48, 81, "Arima Kinen", "long", "classic"),
    (54, 3, "Osaka Hai", "medium", "senior"),
    (56, 4, "Tenno Sho (Spring)", "long", "senior"),
    (57, 5, "Victoria Mile", "mile", "senior"),
    (59, 73, "Yasuda Kinen", "mile", "senior"),
    (60, 74, "Takarazuka Kinen", "medium", "senior"),
    (68, 76, "Tenno Sho (Autumn)", "medium", "senior"),
    (69, 77, "Queen Elizabeth II Cup", "medium", "senior"),
    (70, 79, "Japan Cup", "medium", "senior"),
    (72, 81, "Arima Kinen", "long", "senior"),
]


_JSON_DATA_CACHE = {}
_SIM_CALIBRATION_CACHE = {}


def _load_json_data(filename, default):
    path = Path(__file__).resolve().parents[1] / "data" / filename
    cache_key = str(path)
    if cache_key in _JSON_DATA_CACHE:
        return _JSON_DATA_CACHE[cache_key]
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    _JSON_DATA_CACHE[cache_key] = data
    return data


def _load_event_effect_templates(project_root):
    """Load local event effect templates.

    The available local database is keyed by localized event name rather than
    support/chara IDs. It still gives real choice-level stat/SP/bond/HP shapes,
    which is better than applying one end-of-career stat lump.
    """
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
    candidates = []
    env_path = os.environ.get("SWEEPY_EVENT_DATA_PATH", "").strip()
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend([
        root / "data" / "event_data.json",
        root / "data" / "event_effects.json",
        root.parent / "data" / "event_data.json",
        root.parent / "resource" / "umamusume" / "data" / "event_data.json",
    ])
    source = next((path for path in candidates if path.exists()), None)
    if not source:
        return [], None
    cache_key = str(source)
    if cache_key in _JSON_DATA_CACHE:
        return _JSON_DATA_CACHE[cache_key], source
    try:
        raw = json.loads(source.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return [], None
    templates = []
    if isinstance(raw, dict):
        for event_name, row in raw.items():
            if not isinstance(row, dict):
                continue
            stats_by_choice = row.get("stats") or {}
            choices = row.get("choices") or {}
            parsed_choices = []
            if not isinstance(stats_by_choice, dict):
                continue
            for choice_key, stats in stats_by_choice.items():
                if not isinstance(stats, dict):
                    continue
                parsed = {}
                malformed = False
                for stat_name, value in stats.items():
                    try:
                        numeric = float(value or 0)
                    except (TypeError, ValueError):
                        continue
                    # The old project export contains tutorial/sentinel rows
                    # with values like 111110. Those are UI training examples,
                    # not real career event effects.
                    if abs(numeric) > 200:
                        malformed = True
                        break
                    if numeric:
                        parsed[str(stat_name)] = numeric
                if parsed and not malformed:
                    parsed_choices.append({
                        "choice": str(choice_key),
                        "label": choices.get(str(choice_key)) if isinstance(choices, dict) else "",
                        "effects": parsed,
                    })
            if parsed_choices:
                templates.append({"event_name": str(event_name), "choices": parsed_choices})
    _JSON_DATA_CACHE[cache_key] = templates
    return templates, source


_LATEST_SESSION_CONTEXT_FIELDS = (
    "preset_name",
    "deck_id",
    "deck_name",
    "trainee_card_id",
    "chara_id",
    "support_card_ids",
    "support_cards",
    "support_card_lb_levels",
    "deck_quality_bucket",
    "runtime_instance",
    "friend_viewer_id",
    "friend_card_id",
    "parent_id_1",
    "parent_id_2",
    "rental_viewer_id",
    "rental_trained_chara_id",
    "borrow_fallback_id",
    "desired_parent_sparks",
    "parent_farming_rules",
    "parents",
    "skill_profile_style",
    "skill_profile_distance",
    "style",
    "running_style",
    "custom_race_schedule",
    "initial_skill_point",
    "scenario_id",
)


def _load_json_file(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def _path_key(path):
    try:
        return str(Path(path).resolve())
    except OSError:
        return str(Path(path))


def _runtime_instance_from_path(path):
    parts = Path(path).parts
    for idx, part in enumerate(parts):
        if part.lower() == "instances" and idx + 1 < len(parts):
            return parts[idx + 1]
    return ""


def _runtime_root_from_path(path):
    path = Path(path)
    if path.name.lower() in {"account_a", "account_b"} and path.parent.name.lower() == "instances":
        return path.parent.parent
    if path.name.lower() == "instances":
        return path.parent
    return path


def _runtime_roots(project_root):
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
    roots = []
    env_runtime = os.environ.get("UMA_RUNTIME_DIR")
    candidates = []
    if env_runtime:
        candidates.append(_runtime_root_from_path(env_runtime))
    candidates.extend([root / "uma_runtime", root.parent / "uma_runtime"])
    seen = set()
    for candidate in candidates:
        candidate = Path(candidate)
        key = _path_key(candidate)
        if candidate.exists() and key not in seen:
            roots.append(candidate)
            seen.add(key)
    return roots


def _preferred_runtime_instance(preset=None):
    preset = preset or {}
    run_context = preset.get("_run_context") if isinstance(preset, dict) else {}
    candidates = [
        preset.get("sim_runtime_instance") if isinstance(preset, dict) else None,
        (run_context or {}).get("runtime_instance") if isinstance(run_context, dict) else None,
        os.environ.get("SWEEPY_SIM_INSTANCE_NAME"),
        os.environ.get("SWEEPY_INSTANCE_NAME"),
    ]
    env_runtime = os.environ.get("UMA_RUNTIME_DIR")
    if env_runtime:
        env_instance = _runtime_instance_from_path(env_runtime)
        if env_instance:
            candidates.append(env_instance)
    for value in candidates:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _support_catalog_row(support_id):
    support_id = _as_int(support_id)
    if not support_id:
        return {}
    bonuses = _load_json_data("support_card_bonuses.json", {})
    row = bonuses.get(str(support_id)) or bonuses.get(support_id) or {}
    if row:
        return row
    support_list = _load_json_data("support_list.json", {})
    return support_list.get(str(support_id)) or support_list.get(support_id) or {}


def _support_card_context_row(raw, *, position=None):
    if not isinstance(raw, dict):
        raw = {"support_card_id": raw}
    support_id = _as_int(raw.get("support_card_id") or raw.get("id") or raw.get("card_id"))
    if not support_id:
        return None
    catalog = _support_catalog_row(support_id)
    lb = raw.get("lb_level")
    if lb is None:
        lb = raw.get("limit_break_count")
    if lb is None:
        lb = raw.get("lb")
    level = raw.get("support_card_level")
    if level is None:
        level = raw.get("level")
    row = {
        "id": support_id,
        "support_card_id": support_id,
        "name": raw.get("name") or catalog.get("name") or f"Support {support_id}",
        "rarity": raw.get("rarity") or catalog.get("rarity") or "",
        "type": raw.get("type") or catalog.get("type") or "",
        "lb_level": _as_int(lb, 0),
        "limit_break_count": _as_int(lb, 0),
        "support_card_level": _as_int(level, 0),
        "exp": _as_int(raw.get("exp"), 0),
    }
    if position is not None:
        row["position"] = position
    return row


def _support_lb_lookup(cards):
    out = {}
    for card in cards or []:
        if not isinstance(card, dict):
            continue
        support_id = _as_int(card.get("support_card_id") or card.get("id") or card.get("card_id"))
        if not support_id:
            continue
        lb = card.get("lb_level")
        if lb is None:
            lb = card.get("limit_break_count")
        if lb is None:
            lb = card.get("lb")
        out[str(support_id)] = {
            "lb": _as_int(lb, 0),
            "limit_break_count": _as_int(lb, 0),
            "level": _as_int(card.get("support_card_level") or card.get("level"), 0),
            "exp": _as_int(card.get("exp"), 0),
        }
    return out


def _merge_context_field(target, key, value):
    if value is None:
        return
    if isinstance(value, str) and not value.strip():
        return
    if isinstance(value, (list, dict)) and not value:
        return
    target[key] = copy.deepcopy(value)


def _extract_session_run_context(session):
    """Extract the latest UI/start selections from dev_session.json."""
    if not isinstance(session, dict):
        return {}
    selection = session.get("selection") or {}
    start_debug = session.get("start_debug") or {}
    request = start_debug.get("request") or {}
    proof_payload = ((start_debug.get("proof") or {}).get("payload") or {}).get("start_chara") or {}
    dashboard = session.get("dashboard") or {}
    dashboard_career = ((dashboard or {}).get("account") or {}).get("career") or {}
    owned_support_by_id = {}
    for row in (dashboard.get("supports") if isinstance(dashboard, dict) else []) or []:
        if not isinstance(row, dict):
            continue
        support_id = _as_int(row.get("support_card_id") or row.get("id") or row.get("card_id"))
        if support_id and support_id not in owned_support_by_id:
            owned_support_by_id[support_id] = row

    def _enriched_support_raw(raw):
        raw_row = raw if isinstance(raw, dict) else {"support_card_id": raw}
        support_id = _as_int(raw_row.get("support_card_id") or raw_row.get("id") or raw_row.get("card_id"))
        owned = owned_support_by_id.get(support_id) or {}
        if not owned:
            return raw_row
        merged = dict(raw_row)
        for key in ("limit_break_count", "lb_level", "lb", "support_card_level", "level", "exp"):
            if merged.get(key) is None and owned.get(key) is not None:
                merged[key] = owned.get(key)
        return merged

    ctx = {}
    deck = selection.get("deck") or {}
    if isinstance(deck, dict):
        _merge_context_field(ctx, "deck_id", deck.get("id") or request.get("deck_id") or proof_payload.get("select_deck_id"))
        _merge_context_field(ctx, "deck_name", deck.get("name"))
        cards = []
        for idx, raw in enumerate(deck.get("cards") or [], start=1):
            row = _support_card_context_row(_enriched_support_raw(raw), position=idx)
            if row:
                cards.append(row)
        if not cards:
            for idx, support_id in enumerate(request.get("support_card_ids") or proof_payload.get("support_card_ids") or [], start=1):
                row = _support_card_context_row(_enriched_support_raw({"support_card_id": support_id}), position=idx)
                if row:
                    cards.append(row)
        if cards:
            ctx["support_cards"] = cards[:5]
            ctx["support_card_ids"] = [
                _as_int(card.get("support_card_id"))
                for card in cards[:5]
                if _as_int(card.get("support_card_id"))
            ]
            ctx["support_card_lb_levels"] = _support_lb_lookup(cards[:5])
    elif request.get("support_card_ids") or proof_payload.get("support_card_ids"):
        cards = []
        for idx, support_id in enumerate(request.get("support_card_ids") or proof_payload.get("support_card_ids") or [], start=1):
            row = _support_card_context_row(_enriched_support_raw({"support_card_id": support_id}), position=idx)
            if row:
                cards.append(row)
        if cards:
            ctx["support_cards"] = cards[:5]
            ctx["support_card_ids"] = [
                _as_int(card.get("support_card_id"))
                for card in cards[:5]
                if _as_int(card.get("support_card_id"))
            ]
            ctx["support_card_lb_levels"] = _support_lb_lookup(cards[:5])

    trainee = selection.get("trainee") or {}
    trainee_card_id = (
        request.get("card_id")
        or proof_payload.get("card_id")
        or trainee.get("id")
        or dashboard_career.get("card_id")
    )
    _merge_context_field(ctx, "trainee_card_id", _as_int(trainee_card_id))

    friend = selection.get("friend") or {}
    friend_info = proof_payload.get("friend_support_card_info") or {}
    _merge_context_field(
        ctx,
        "friend_viewer_id",
        request.get("friend_viewer_id") or friend_info.get("viewer_id") or friend.get("viewer_id") or dashboard_career.get("friend_viewer_id"),
    )
    _merge_context_field(
        ctx,
        "friend_card_id",
        request.get("friend_card_id") or friend_info.get("support_card_id") or friend.get("support_card_id") or dashboard_career.get("friend_card_id"),
    )

    parent_id_1 = (
        request.get("parent_id_1")
        or proof_payload.get("succession_trained_chara_id_1")
        or dashboard_career.get("parent_id_1")
    )
    parent_id_2 = (
        request.get("parent_id_2")
        or proof_payload.get("succession_trained_chara_id_2")
        or dashboard_career.get("parent_id_2")
    )
    veterans = selection.get("veterans") or []
    if not parent_id_1 and len(veterans) >= 1:
        parent_id_1 = veterans[0].get("instance_id") if isinstance(veterans[0], dict) else None
    if not parent_id_2 and len(veterans) >= 2:
        parent_id_2 = veterans[1].get("instance_id") if isinstance(veterans[1], dict) else None
    _merge_context_field(ctx, "parent_id_1", _as_int(parent_id_1))
    _merge_context_field(ctx, "parent_id_2", _as_int(parent_id_2))
    if isinstance(veterans, list) and veterans:
        ctx["parents"] = copy.deepcopy(veterans[:2])

    rental = proof_payload.get("rental_succession_trained_chara") or {}
    _merge_context_field(ctx, "rental_viewer_id", rental.get("viewer_id"))
    _merge_context_field(ctx, "rental_trained_chara_id", rental.get("trained_chara_id"))
    _merge_context_field(ctx, "scenario_id", request.get("scenario_id") or proof_payload.get("scenario_id") or dashboard_career.get("scenario_id"))
    return {key: value for key, value in ctx.items() if value or isinstance(value, (list, dict))}


def _extract_log_run_context(report):
    if not isinstance(report, dict):
        return {}
    candidates = [
        report.get("run_context"),
        report.get("_run_context"),
        (report.get("preset") or {}).get("_run_context") if isinstance(report.get("preset"), dict) else None,
    ]
    for ctx in candidates:
        if isinstance(ctx, dict) and _run_context_is_usable(ctx):
            return {key: copy.deepcopy(value) for key, value in ctx.items() if key in _LATEST_SESSION_CONTEXT_FIELDS}
    return {}


def _run_context_is_usable(ctx):
    if not isinstance(ctx, dict):
        return False
    cards = ctx.get("support_cards") or []
    card_ids = ctx.get("support_card_ids") or []
    has_deck = len(cards) >= 5 or len(card_ids) >= 5
    return bool(has_deck and _as_int(ctx.get("trainee_card_id")))


def _latest_session_context(project_root, preferred_instance=""):
    """Return (context, source_path) for the newest usable session/log setup."""
    sources = []
    for root in _runtime_roots(project_root):
        instance_root = root / "instances"
        if instance_root.exists():
            for instance_dir in instance_root.glob("*"):
                if not instance_dir.is_dir():
                    continue
                instance_name = instance_dir.name
                for path in [instance_dir / "dev_session.json"]:
                    if path.exists():
                        sources.append(("session", path, instance_name))
                bot_log_dir = instance_dir / "bot_logs"
                for path in (bot_log_dir.glob("career_log_*.json") if bot_log_dir.exists() else []):
                    sources.append(("career_log", path, instance_name))
        for path in root.glob("bot_logs/career_log_*.json"):
            sources.append(("career_log", path, _runtime_instance_from_path(path)))
    preferred = str(preferred_instance or "").strip().lower()

    def sort_key(item):
        _kind, path, instance_name = item
        priority = 0 if preferred and str(instance_name or "").lower() == preferred else 1
        mtime = path.stat().st_mtime if path.exists() else 0
        return (priority, -mtime)

    sources.sort(key=sort_key)
    seen = set()
    for kind, path, instance_name in sources:
        key = _path_key(path)
        if key in seen:
            continue
        seen.add(key)
        data = _load_json_file(path)
        ctx = _extract_session_run_context(data) if kind == "session" else _extract_log_run_context(data)
        if _run_context_is_usable(ctx):
            if instance_name:
                ctx["runtime_instance"] = instance_name
            return ctx, path
    return {}, None


def hydrate_preset_with_latest_session_context(preset, project_root=None):
    """Merge the latest deck/friend/trainee/parents into a sim preset.

    This is intentionally read-only against runtime data. It lets simulator
    entry points use the same setup the UI/bot most recently selected instead
    of stale `_run_context` embedded in an old preset JSON.
    """
    hydrated = copy.deepcopy(preset or {})
    if hydrated.get("sim_use_latest_session_context") is False:
        return hydrated
    preferred_instance = _preferred_runtime_instance(hydrated)
    ctx, source = _latest_session_context(project_root, preferred_instance=preferred_instance)
    if not ctx:
        hydrated.pop("_sim_latest_session_context_source", None)
        return hydrated
    run_context = copy.deepcopy(hydrated.get("_run_context") or {})
    for key, value in ctx.items():
        _merge_context_field(run_context, key, value)
    if run_context.get("support_cards") and not run_context.get("support_card_ids"):
        run_context["support_card_ids"] = [
            _as_int(card.get("support_card_id") or card.get("id") or card.get("card_id"))
            for card in run_context["support_cards"]
            if isinstance(card, dict) and _as_int(card.get("support_card_id") or card.get("id") or card.get("card_id"))
        ]
    if run_context.get("support_cards") and not run_context.get("support_card_lb_levels"):
        run_context["support_card_lb_levels"] = _support_lb_lookup(run_context.get("support_cards") or [])
    hydrated["_run_context"] = run_context
    if run_context.get("scenario_id"):
        hydrated["scenario_id"] = _as_int(run_context.get("scenario_id"), hydrated.get("scenario_id") or 4)
    hydrated["_sim_latest_session_context_source"] = str(source) if source else ""
    if run_context.get("runtime_instance"):
        hydrated["_sim_latest_session_context_instance"] = run_context.get("runtime_instance")
    return hydrated


def _weighted_percentile(rows, value_key, pct, weight_key="weight", default=0.0):
    pairs = []
    for row in rows or []:
        try:
            value = float(row.get(value_key))
            weight = float(row.get(weight_key) or 1.0)
        except (TypeError, ValueError):
            continue
        if weight <= 0:
            continue
        pairs.append((value, weight))
    if not pairs:
        return default
    pairs.sort(key=lambda item: item[0])
    total = sum(weight for _value, weight in pairs)
    target = max(0.0, min(1.0, float(pct))) * total
    running = 0.0
    for value, weight in pairs:
        running += weight
        if running >= target:
            return value
    return pairs[-1][0]


def _load_bot_parent_registry_contexts(project_root):
    registry = {}
    for root in _runtime_roots(project_root):
        instance_root = root / "instances"
        if not instance_root.exists():
            continue
        for path in instance_root.glob("*/parent_memory/bot_parent_registry.json"):
            data = _load_json_file(path)
            if not isinstance(data, dict):
                continue
            for row in data.get("bot_parents") or []:
                if not isinstance(row, dict):
                    continue
                instance_id = _as_int(row.get("instance_id"))
                if not instance_id:
                    continue
                registry[instance_id] = {
                    "run_context": copy.deepcopy(row.get("run_context") or {}),
                    "career_log": row.get("career_log") or "",
                    "preset_name": row.get("preset_name") or "",
                    "registered_at": row.get("registered_at") or "",
                }
    return registry


def _skill_count(parent):
    skills = parent.get("skills") or []
    return len(skills) if isinstance(skills, list) else 0


def _parent_final_stats(parent):
    stats = parent.get("stats") or {}
    if not isinstance(stats, dict):
        return {}
    out = {}
    for key in STAT_KEYS:
        value = _as_int(stats.get(key))
        if value:
            out[key] = value
    return out


def _parent_skill_rating_residual(parent):
    score = _as_int(parent.get("score"))
    stats = _parent_final_stats(parent)
    if score <= 0 or len(stats) != len(STAT_KEYS):
        return 0
    stat_only = estimate_rating_score(stats, skill_score=0, star_level=3, unique_level=5)
    return max(0, score - int(stat_only.get("stat_score") or 0) - int(stat_only.get("unique_bonus") or 0))


def _deck_overlap_score(a, b):
    a = {_as_int(value) for value in (a or []) if _as_int(value)}
    b = {_as_int(value) for value in (b or []) if _as_int(value)}
    if not a or not b:
        return 0.0
    return len(a & b) / max(1, min(len(a), len(b)))


def _calibration_context_key(project_root, run_context, trainee_card_id):
    ctx = run_context or {}
    return (
        _path_key(project_root or Path(__file__).resolve().parents[1]),
        _preferred_runtime_instance({"_run_context": ctx}),
        _as_int(trainee_card_id),
        _as_int(ctx.get("deck_id")),
        _as_int(ctx.get("friend_card_id")),
        tuple(_as_int(value) for value in (ctx.get("support_card_ids") or []) if _as_int(value)),
    )


def _skill_calibration_sample_weight(sample_context, target_context, trainee_card_id, made_by_bot):
    weight = 0.35
    if made_by_bot:
        weight += 2.0
    sample_trainee = _as_int((sample_context or {}).get("trainee_card_id"))
    if sample_trainee and sample_trainee == _as_int(trainee_card_id):
        weight += 4.0
    target_friend = _as_int((target_context or {}).get("friend_card_id"))
    sample_friend = _as_int((sample_context or {}).get("friend_card_id"))
    if target_friend and sample_friend == target_friend:
        weight += 1.25
    overlap = _deck_overlap_score(
        (sample_context or {}).get("support_card_ids"),
        (target_context or {}).get("support_card_ids"),
    )
    weight += overlap * 4.0
    return weight


def _skill_point_spent_from_career_report(report):
    turns = (report or {}).get("turns") or []
    if not isinstance(turns, list):
        return 0
    snapshots = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        stats = turn.get("stats") or {}
        raw = stats.get("skill_point", turn.get("skill_point"))
        if raw is None:
            continue
        snapshots.append((_as_int(turn.get("turn")), _as_int(raw)))
    if len(snapshots) < 2:
        return 0
    snapshots.sort(key=lambda row: row[0])
    spent = 0
    previous = snapshots[0][1]
    for _turn, current in snapshots[1:]:
        delta = current - previous
        if delta < 0:
            spent += -delta
        previous = current
    return max(0, int(spent))


def _event_state_skill_point(raw_state):
    state = raw_state or {}
    if not isinstance(state, dict):
        return None
    stats = state.get("stats") if isinstance(state.get("stats"), dict) else {}
    value = state.get("skill_point")
    if value is None:
        value = stats.get("skill_point")
    if value is None:
        return None
    return _as_int(value)


def _selected_training_snapshot_skill_point(turn):
    if not isinstance(turn, dict):
        return 0
    command = turn.get("current_command") or turn.get("command") or {}
    if not isinstance(command, dict) or _as_int(command.get("command_type")) != 1:
        return 0
    command_id = _as_int(command.get("command_id"))
    command_group_id = _as_int(command.get("command_group_id"))
    snapshot = turn.get("training_snapshot") or {}
    trainings = snapshot.get("trainings") or snapshot.get("command_info_array") or snapshot.get("commands") or []
    for row in trainings:
        if not isinstance(row, dict):
            continue
        if command_id and _as_int(row.get("command_id")) != command_id:
            continue
        if command_group_id and _as_int(row.get("command_group_id")) != command_group_id:
            continue
        stat_gain = row.get("stat_gain") or {}
        if isinstance(stat_gain, dict):
            return max(0, _as_int(stat_gain.get("skill_point") or stat_gain.get("skill_pt")))
        for item in row.get("params_inc_dec_info_array") or []:
            if isinstance(item, dict) and _as_int(item.get("target_type")) == 30:
                return max(0, _as_int(item.get("value")))
    return 0


def _sp_event_source_bucket(event, turn_no=0, after_race=False):
    story_id = str((event or {}).get("story_id") or "")
    event_id = _as_int((event or {}).get("event_id"))
    if event_id in CLIMAX_RACE_REWARD_EVENT_IDS or story_id in CLIMAX_RACE_REWARD_STORY_IDS:
        return "climax"
    if event_id in RACE_REWARD_EVENT_IDS or story_id in RACE_REWARD_STORY_IDS:
        return "races"
    if _as_int(turn_no) <= 1 and story_id.startswith("501"):
        return "initial"
    if story_id.startswith(("8", "83")):
        return "support_events"
    if story_id.startswith("4"):
        return "fixed_events"
    return "general_events"


def _career_sp_source_ledger(report):
    """Split observed SP gains by the source the bot can actually model.

    This intentionally does not estimate SP from final SP plus skill spend.
    Training SP is read from the selected training snapshot when present;
    event SP is read from event_resolution deltas; race SP is kept as a
    separate bucket so exact grade/RB/hammer formulas can be compared.
    """
    ledger = defaultdict(int)
    turns = (report or {}).get("turns") or []
    if not isinstance(turns, list):
        return {}
    for turn in turns:
        if not isinstance(turn, dict):
            continue
        turn_no = _as_int(turn.get("turn"))
        training_sp = _selected_training_snapshot_skill_point(turn)
        if training_sp > 0:
            ledger["training"] += training_sp
        after_race = False
        for event in turn.get("events") or []:
            if not isinstance(event, dict):
                continue
            if event.get("event") == "race_result":
                after_race = True
                continue
            if event.get("event") != "event_resolution":
                continue
            before_sp = _event_state_skill_point(event.get("state_before"))
            after_sp = _event_state_skill_point(event.get("state_after"))
            if before_sp is None or after_sp is None:
                continue
            delta = after_sp - before_sp
            if delta <= 0:
                continue
            bucket = _sp_event_source_bucket(event, turn_no=turn_no, after_race=after_race)
            ledger[bucket] += delta
    return dict(ledger)


def _skill_point_spent_from_career_log_path(path):
    raw = str(path or "").strip()
    if not raw:
        return 0
    report = _load_json_file(Path(raw))
    if not isinstance(report, dict):
        return 0
    return _skill_point_spent_from_career_report(report)


def load_empirical_skill_rating_calibration(project_root=None, run_context=None, trainee_card_id=None):
    """Build a real-data skill-rating model from synced parent records.

    Parent memory stores actual in-game score plus final stats/skills. The
    residual after stat score + unique bonus is the observed skill-rating
    contribution. That lets sims avoid pretending raw datamine skill values are
    exact for local bot outcomes.
    """
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
    target_context = run_context or {}
    cache_key = ("skill_rating_calibration", _calibration_context_key(root, target_context, trainee_card_id))
    if cache_key in _SIM_CALIBRATION_CACHE:
        return copy.deepcopy(_SIM_CALIBRATION_CACHE[cache_key])

    def finish(result):
        _SIM_CALIBRATION_CACHE[cache_key] = copy.deepcopy(result)
        return result

    registry = _load_bot_parent_registry_contexts(root)
    samples = []
    sources = []
    for runtime_root in _runtime_roots(root):
        instance_root = runtime_root / "instances"
        if not instance_root.exists():
            continue
        for path in instance_root.glob("*/parent_memory/parent_library.json"):
            data = _load_json_file(path)
            if not isinstance(data, dict):
                continue
            sources.append(str(path))
            for parent in data.get("parents") or []:
                if not isinstance(parent, dict):
                    continue
                residual = _parent_skill_rating_residual(parent)
                count = _skill_count(parent)
                score = _as_int(parent.get("score"))
                if residual <= 0 or count <= 0 or score <= 0:
                    continue
                instance_id = _as_int(parent.get("instance_id"))
                registry_row = registry.get(instance_id) or {}
                sample_context = registry_row.get("run_context") or {}
                made_by_bot = bool(parent.get("made_by_bot") or str(parent.get("source_kind") or "").lower() == "bot")
                weight = _skill_calibration_sample_weight(sample_context, target_context, trainee_card_id, made_by_bot)
                if made_by_bot:
                    weight *= 1.8
                skill_rows = [
                    {
                        "skill_id": _as_int(skill.get("skill_id")),
                        "name": skill.get("name") or "",
                        "hint_level": skill.get("hint_level") or 0,
                    }
                    for skill in (parent.get("skills") or [])
                    if isinstance(skill, dict)
                ]
                recomputed_estimated_sp = sum(
                    _estimated_sim_skill_point_cost(row.get("skill_id"), row.get("name") or "", row.get("hint_level") or 0)
                    for row in skill_rows
                    if _as_int(row.get("skill_id"))
                )
                stored_estimated_sp = _as_int((parent.get("stats") or {}).get("estimated_skill_points") or parent.get("estimated_skill_points"))
                career_log = (
                    (parent.get("bot_parent_info") or {}).get("career_log")
                    or registry_row.get("career_log")
                    or ""
                )
                actual_sp_spent = _skill_point_spent_from_career_log_path(career_log) if made_by_bot else 0
                estimated_sp = actual_sp_spent or (recomputed_estimated_sp if skill_rows else stored_estimated_sp)
                samples.append({
                    "instance_id": instance_id,
                    "made_by_bot": made_by_bot,
                    "card_id": _as_int(parent.get("card_id")),
                    "score": score,
                    "stat_sum": sum(_parent_final_stats(parent).values()),
                    "skill_count": count,
                    "skill_rating_residual": residual,
                    "estimated_skill_points": estimated_sp,
                    "weight": weight,
                    "context_match": weight,
                    "skills": skill_rows,
                })
    bot_samples = [row for row in samples if row["made_by_bot"]]
    model_samples = bot_samples if len(bot_samples) >= 8 else samples
    if len(model_samples) < 5:
        return finish({
            "enabled": False,
            "sample_count": len(model_samples),
            "source_paths": sources,
            "reason": "not_enough_parent_memory_samples",
        })
    skill_count_target = int(round(_weighted_percentile(model_samples, "skill_count", 0.50, default=SIM_TOTAL_SKILL_PURCHASE_MAX_DEFAULT)))
    skill_count_p85 = int(round(_weighted_percentile(model_samples, "skill_count", 0.85, default=skill_count_target)))
    residual_target = int(round(_weighted_percentile(model_samples, "skill_rating_residual", 0.50, default=SIM_SKILL_RATING_SCORE_CAP_DEFAULT)))
    residual_p85 = int(round(_weighted_percentile(model_samples, "skill_rating_residual", 0.85, default=residual_target)))
    residual_p95 = int(round(_weighted_percentile(model_samples, "skill_rating_residual", 0.95, default=residual_p85)))
    spend_samples = []
    for sample in model_samples:
        estimated_sp = _as_int(sample.get("estimated_skill_points"))
        count = _as_int(sample.get("skill_count"))
        if estimated_sp > 0 and count > 0:
            row = dict(sample)
            row["skill_cost_per_skill"] = estimated_sp / count
            spend_samples.append(row)
    spend_target = int(round(_weighted_percentile(spend_samples, "estimated_skill_points", 0.50, default=0))) if spend_samples else 0
    spend_p85 = int(round(_weighted_percentile(spend_samples, "estimated_skill_points", 0.85, default=spend_target))) if spend_samples else 0
    cost_per_skill_target = float(_weighted_percentile(spend_samples, "skill_cost_per_skill", 0.50, default=0.0)) if spend_samples else 0.0
    return finish({
        "enabled": True,
        "sample_count": len(model_samples),
        "bot_sample_count": len(bot_samples),
        "source_paths": sources,
        "uses_bot_samples": len(bot_samples) >= 8,
        "skill_count_target": max(1, skill_count_target),
        "skill_count_p85": max(1, skill_count_p85),
        "skill_rating_target": max(0, residual_target),
        "skill_rating_p85": max(0, residual_p85),
        "skill_rating_p95": max(0, residual_p95),
        "skill_spend_target": max(0, spend_target),
        "skill_spend_p85": max(0, spend_p85),
        "skill_cost_per_skill_target": max(0.0, cost_per_skill_target),
        "skill_spend_sample_count": len(spend_samples),
        "samples": model_samples[:400],
    })


def load_empirical_sp_budget_calibration(project_root=None, run_context=None, trainee_card_id=None):
    """Build an observed SP source ledger from finished career logs.

    SP is modeled by source: training snapshots, event_resolution deltas, and
    exact race reward formulas. Final SP plus inferred skill spend is kept only
    as an audit field because it is not a reliable source generator.
    """
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
    target_context = run_context or {}
    cache_key = ("sp_budget_calibration", _calibration_context_key(root, target_context, trainee_card_id))
    if cache_key in _SIM_CALIBRATION_CACHE:
        return copy.deepcopy(_SIM_CALIBRATION_CACHE[cache_key])

    def finish(result):
        _SIM_CALIBRATION_CACHE[cache_key] = copy.deepcopy(result)
        return result

    samples = []
    sources = []
    for runtime_root in _runtime_roots(root):
        instance_root = runtime_root / "instances"
        if not instance_root.exists():
            continue
        for path in instance_root.glob("*/bot_logs/career_log_*.json"):
            data = _load_json_file(path)
            if not isinstance(data, dict) or data.get("status") != "finished":
                continue
            turns = [turn for turn in data.get("turns") or [] if isinstance(turn, dict) and turn.get("stats")]
            if not turns:
                continue
            last = max(turns, key=lambda turn: _as_int(turn.get("turn")))
            final_sp = _as_int(last.get("skill_point") or (last.get("stats") or {}).get("skill_point"))
            sp_ledger = _career_sp_source_ledger(data)
            source_sp_budget = sum(max(0, _as_int(value)) for value in sp_ledger.values())
            owned = last.get("owned_skills") or []
            skill_spend = 0
            skill_count = 0
            for row in owned:
                if not isinstance(row, dict):
                    continue
                skill_id = _as_int(row.get("skill_id"))
                if not skill_id:
                    continue
                skill_count += 1
                skill_spend += _estimated_sim_skill_point_cost(skill_id, row.get("name") or "", row.get("hint_level") or 0)
            actual_sp_spent = _skill_point_spent_from_career_report(data)
            if actual_sp_spent > 0:
                skill_spend = actual_sp_spent
            if skill_spend <= 0 and source_sp_budget <= 0:
                continue
            sample_context = data.get("run_context") or {}
            weight = _skill_calibration_sample_weight(sample_context, target_context, trainee_card_id, True)
            race_count = 0
            race_wins = 0
            race_sp_samples = []
            for turn in turns:
                events = [event for event in (turn.get("events") or []) if isinstance(event, dict)]
                for idx, event in enumerate(events):
                    if not isinstance(event, dict) or event.get("event") != "race_result":
                        continue
                    race_count += 1
                    if event.get("won") or event.get("finish_rank") == 1 or event.get("status") == "won":
                        race_wins += 1
                    post_race_sp = 0
                    for follow in events[idx + 1:]:
                        if follow.get("event") == "race_result":
                            break
                        if follow.get("event") != "event_resolution":
                            continue
                        bucket = _sp_event_source_bucket(follow, turn_no=_as_int(turn.get("turn")), after_race=True)
                        if bucket not in {"races", "climax"}:
                            continue
                        before_sp = _event_state_skill_point(follow.get("state_before"))
                        after_sp = _event_state_skill_point(follow.get("state_after"))
                        if before_sp is None or after_sp is None:
                            continue
                        delta = after_sp - before_sp
                        if delta > 0:
                            post_race_sp += delta
                    if post_race_sp > 0:
                        race = event.get("race") or {}
                        race_name = str(race.get("name") or event.get("race_name") or "")
                        program_id = _as_int(event.get("program_id") or race.get("program_id"))
                        turn_no = _as_int(turn.get("turn"))
                        if "twinkle star climax" in race_name.lower() or program_id in {2315, 2410, 2412, 2513} or turn_no >= 74:
                            grade_key = "climax"
                        elif bool(event.get("is_g1")):
                            grade_key = "g1"
                        else:
                            grade_key = "other"
                        race_sp_samples.append({
                            "grade": grade_key,
                            "sp": post_race_sp,
                            "weight": weight,
                        })
            samples.append({
                "path": str(path),
                "final_sp": final_sp,
                "skill_spend": skill_spend,
                "skill_count": skill_count,
                "total_sp_budget": source_sp_budget,
                "source_sp_budget": source_sp_budget,
                "final_plus_spend_budget": final_sp + skill_spend,
                "sp_source_ledger": sp_ledger,
                "race_count": race_count,
                "race_wins": race_wins,
                "race_win_rate": (race_wins / race_count) if race_count else 0.0,
                "race_sp_samples": race_sp_samples,
                "weight": weight,
            })
            sources.append(str(path))
    if len(samples) < 5:
        return finish({
            "enabled": False,
            "sample_count": len(samples),
            "source_paths": sources,
            "reason": "not_enough_finished_career_logs",
            "training_sp_model": "mechanical_facility_table",
            "event_sp_model": "observed_event_resolution_deltas",
            "race_sp_model": "exact_grade_race_bonus_hammer_formula",
            "purchase_sp_model": "audit_only",
        })
    total_target = int(round(_weighted_percentile(samples, "source_sp_budget", 0.50, default=0)))
    final_sp_target = int(round(_weighted_percentile(samples, "final_sp", 0.50, default=100)))
    skill_spend_target = int(round(_weighted_percentile(samples, "skill_spend", 0.50, default=0)))
    final_sp_p85 = int(round(_weighted_percentile(samples, "final_sp", 0.85, default=final_sp_target)))
    total_p85 = int(round(_weighted_percentile(samples, "source_sp_budget", 0.85, default=total_target)))
    final_plus_spend_target = int(round(_weighted_percentile(samples, "final_plus_spend_budget", 0.50, default=0)))
    race_count_target = int(round(_weighted_percentile(samples, "race_count", 0.50, default=0)))
    race_win_rate_target = float(_weighted_percentile(samples, "race_win_rate", 0.50, default=0.85))
    race_sp_rows = []
    for sample in samples:
        for row in sample.get("race_sp_samples") or []:
            if isinstance(row, dict) and _as_int(row.get("sp")) > 0:
                race_sp_rows.append(row)
    race_sp_by_grade = {}
    for grade_key, default in (("other", 41), ("g1", 57), ("climax", 66)):
        rows = [row for row in race_sp_rows if row.get("grade") == grade_key]
        race_sp_by_grade[grade_key] = int(round(_weighted_percentile(rows, "sp", 0.50, default=default)))
    source_keys = sorted({
        key
        for sample in samples
        for key in (sample.get("sp_source_ledger") or {})
    })
    source_sp_budget_by_source = {}
    for key in source_keys:
        rows = []
        for sample in samples:
            ledger = sample.get("sp_source_ledger") or {}
            rows.append({
                "value": _as_int(ledger.get(key)),
                "weight": sample.get("weight", 1.0),
            })
        source_sp_budget_by_source[key] = int(round(_weighted_percentile(rows, "value", 0.50, default=0)))
    return finish({
        "enabled": True,
        "sample_count": len(samples),
        "source_paths": sources,
        "total_sp_budget_target": max(0, total_target),
        "total_sp_budget_p85": max(0, total_p85),
        "source_sp_budget_target": max(0, total_target),
        "source_sp_budget_p85": max(0, total_p85),
        "source_sp_budget_by_source": source_sp_budget_by_source,
        "final_plus_spend_budget_target": max(0, final_plus_spend_target),
        "final_sp_target": max(0, final_sp_target),
        "final_sp_p85": max(0, final_sp_p85),
        "skill_spend_target": max(0, skill_spend_target),
        "race_count_target": max(0, race_count_target),
        "race_win_rate_target": max(0.0, min(1.0, race_win_rate_target)),
        "race_sp_reward_by_grade": race_sp_by_grade,
        "race_sp_reward_sample_count": len(race_sp_rows),
        "training_sp_model": "mechanical_facility_table",
        "event_sp_model": "observed_event_resolution_deltas",
        "race_sp_model": "exact_grade_race_bonus_hammer_formula",
        "purchase_sp_model": "audit_only",
        "sp_source_model": "source_ledger",
    })


def load_empirical_race_stat_gain_calibration(project_root=None, run_context=None, trainee_card_id=None):
    """Learn how race turns distribute stat gains from finished bot logs.

    The sim's old race reward path pushed all race stat reward into the most
    trained stat. Actual career logs show race/scenario turns spread smaller
    gains across stats. This calibration uses same-deck/same-trainee logs when
    available, but still falls back to weighted broader data.
    """
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
    target_context = run_context or {}
    cache_key = ("race_stat_gain_calibration", _calibration_context_key(root, target_context, trainee_card_id))
    if cache_key in _SIM_CALIBRATION_CACHE:
        return copy.deepcopy(_SIM_CALIBRATION_CACHE[cache_key])

    def finish(result):
        _SIM_CALIBRATION_CACHE[cache_key] = copy.deepcopy(result)
        return result

    rows = []
    event_rows = []
    sources = []
    exact_rows = []
    exact_event_rows = []
    target_ids = {_as_int(value) for value in (target_context.get("support_card_ids") or []) if _as_int(value)}
    target_friend = _as_int(target_context.get("friend_card_id"))
    target_trainee = _as_int(trainee_card_id or target_context.get("trainee_card_id"))
    for runtime_root in _runtime_roots(root):
        instance_root = runtime_root / "instances"
        if not instance_root.exists():
            continue
        for path in instance_root.glob("*/bot_logs/career_log_*.json"):
            data = _load_json_file(path)
            if not isinstance(data, dict) or data.get("status") != "finished":
                continue
            sample_context = data.get("run_context") or {}
            weight = _skill_calibration_sample_weight(sample_context, target_context, trainee_card_id, True)
            sample_ids = {_as_int(value) for value in (sample_context.get("support_card_ids") or []) if _as_int(value)}
            exact_match = bool(
                target_trainee
                and _as_int(sample_context.get("trainee_card_id")) == target_trainee
                and target_ids
                and sample_ids == target_ids
                and (not target_friend or _as_int(sample_context.get("friend_card_id")) == target_friend)
            )
            turns = [turn for turn in data.get("turns") or [] if isinstance(turn, dict)]
            turns_by_number = {_as_int(turn.get("turn")): turn for turn in turns}
            for turn in turns:
                events = [event for event in turn.get("events") or [] if isinstance(event, dict)]
                race_seen = False
                race_won = True
                race_program_id = 0
                turn_number = _as_int(turn.get("turn"))
                deltas = {stat: 0 for stat in STAT_KEYS}
                for event in events:
                    if event.get("event") == "race_result":
                        race_seen = True
                        race_won = bool(event.get("won") or event.get("finish_rank") == 1 or event.get("status") == "won")
                        race = event.get("race") or {}
                        race_program_id = _as_int(event.get("program_id") or race.get("program_id"))
                        continue
                    if not race_seen or event.get("event") != "event_resolution":
                        continue
                    event_id = _as_int(event.get("event_id"))
                    story_id = str(event.get("story_id") or "")
                    if event_id not in RACE_REWARD_EVENT_IDS and story_id not in RACE_REWARD_STORY_IDS:
                        continue
                    before = (event.get("state_before") or {}).get("stats") or {}
                    after = (event.get("state_after") or {}).get("stats") or {}
                    for stat in STAT_KEYS:
                        value = max(0, _as_int(after.get(stat)) - _as_int(before.get(stat)))
                        deltas[stat] += value

                total = sum(deltas.values())
                if not race_seen:
                    continue

                appended_adjacent = False
                prev_turn = turns_by_number.get(turn_number - 1)
                prev_stats = (prev_turn or {}).get("stats") or {}
                cur_stats = turn.get("stats") or {}
                if prev_stats and cur_stats:
                    adjacent_deltas = {
                        stat: max(0, _as_int(cur_stats.get(stat)) - _as_int(prev_stats.get(stat)))
                        for stat in STAT_KEYS
                    }
                    adjacent_total = sum(adjacent_deltas.values())
                    if adjacent_total > 0:
                        row = {
                            "turn": turn_number,
                            "era": _era_for_turn(turn_number),
                            "program_id": race_program_id,
                            "won": race_won,
                            "total": adjacent_total,
                            "deltas": adjacent_deltas,
                            "weight": weight,
                            "exact_match": exact_match,
                            "source": str(path),
                            "source_kind": "adjacent_race_turn",
                        }
                        rows.append(row)
                        if exact_match:
                            exact_rows.append(row)
                        appended_adjacent = True

                if total > 0:
                    row = {
                        "turn": turn_number,
                        "era": _era_for_turn(turn_number),
                        "program_id": race_program_id,
                        "won": race_won,
                        "total": total,
                        "deltas": deltas,
                        "weight": weight,
                        "exact_match": exact_match,
                        "source": str(path),
                        "source_kind": "race_reward_event",
                    }
                    event_rows.append(row)
                    if exact_match:
                        exact_event_rows.append(row)
                    if not appended_adjacent:
                        rows.append(row)
                        if exact_match:
                            exact_rows.append(row)
            sources.append(str(path))

    use_exact_context = len(exact_rows) >= EXACT_CONTEXT_MIN_RACE_SAMPLES
    model_rows = exact_rows if use_exact_context else rows
    if len(model_rows) < 20:
        fallback_rows = exact_event_rows if len(exact_event_rows) >= 20 else event_rows
        if len(fallback_rows) >= len(model_rows):
            model_rows = fallback_rows
    if len(model_rows) < 20:
        return finish({
            "enabled": False,
            "sample_count": len(model_rows),
            "source_paths": sources,
            "reason": "not_enough_race_turn_samples",
        })

    def distribution_for(sample_rows):
        weighted = {stat: 0.0 for stat in STAT_KEYS}
        total_weighted_gain = 0.0
        weighted_totals = []
        for row in sample_rows:
            row_weight = max(0.05, float(row.get("weight") or 1.0))
            weighted_totals.append({"total": row["total"], "weight": row_weight})
            for stat in STAT_KEYS:
                gain = float((row.get("deltas") or {}).get(stat) or 0)
                weighted[stat] += gain * row_weight
                total_weighted_gain += gain * row_weight
        if total_weighted_gain <= 0:
            return {stat: 1.0 / len(STAT_KEYS) for stat in STAT_KEYS}, 0
        return (
            {stat: weighted[stat] / total_weighted_gain for stat in STAT_KEYS},
            int(round(_weighted_percentile(weighted_totals, "total", 0.50, default=0))),
        )

    distribution, median_total = distribution_for(model_rows)
    by_era = {}
    for era in ("junior", "classic", "senior"):
        era_rows = [row for row in model_rows if row.get("era") == era]
        if len(era_rows) >= 10:
            era_distribution, era_total = distribution_for(era_rows)
            by_era[era] = {
                "distribution": era_distribution,
                "median_total_gain": era_total,
                "sample_count": len(era_rows),
            }
    climax_rows = [row for row in model_rows if _as_int(row.get("turn")) >= 73]
    if len(climax_rows) >= 5:
        climax_distribution, climax_total = distribution_for(climax_rows)
        by_era["climax"] = {
            "distribution": climax_distribution,
            "median_total_gain": climax_total,
            "sample_count": len(climax_rows),
        }
    return finish({
        "enabled": True,
        "sample_count": len(model_rows),
        "total_sample_count": len(rows),
        "exact_sample_count": len(exact_rows),
        "event_sample_count": len(event_rows),
        "exact_event_sample_count": len(exact_event_rows),
        "used_exact_context": use_exact_context,
        "source_paths": sources,
        "distribution": distribution,
        "median_total_gain": median_total,
        "by_era": by_era,
    })


def load_empirical_race_outcome_calibration(project_root=None, run_context=None, trainee_card_id=None):
    """Load observed race win rates from finished bot careers.

    The simulator has stat-threshold and field models, but exact same setup
    logs are more authoritative for "is this scheduled race normally safe?".
    This calibration fixes low-confidence G2/G3 odds without making known
    problem races, such as Kikuka Sho/Tenno Spring, magically safe.
    """
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
    target_context = run_context or {}
    cache_key = ("race_outcome_calibration", _calibration_context_key(root, target_context, trainee_card_id))
    if cache_key in _SIM_CALIBRATION_CACHE:
        return copy.deepcopy(_SIM_CALIBRATION_CACHE[cache_key])

    def finish(result):
        _SIM_CALIBRATION_CACHE[cache_key] = copy.deepcopy(result)
        return result

    target_ids = {_as_int(value) for value in (target_context.get("support_card_ids") or []) if _as_int(value)}
    target_friend = _as_int(target_context.get("friend_card_id"))
    target_trainee = _as_int(trainee_card_id or target_context.get("trainee_card_id"))
    by_pid = defaultdict(lambda: {"wins": 0, "runs": 0, "losses": 0})
    exact_by_pid = defaultdict(lambda: {"wins": 0, "runs": 0, "losses": 0})
    sources = []

    for runtime_root in _runtime_roots(root):
        instance_root = runtime_root / "instances"
        if not instance_root.exists():
            continue
        for path in instance_root.glob("*/bot_logs/career_log_*.json"):
            data = _load_json_file(path)
            if not isinstance(data, dict) or data.get("status") != "finished":
                continue
            sample_context = data.get("run_context") or {}
            sample_ids = {_as_int(value) for value in (sample_context.get("support_card_ids") or []) if _as_int(value)}
            exact_match = bool(
                target_trainee
                and _as_int(sample_context.get("trainee_card_id")) == target_trainee
                and target_ids
                and sample_ids == target_ids
                and (not target_friend or _as_int(sample_context.get("friend_card_id")) == target_friend)
            )
            usable_context = exact_match or (
                target_trainee and _as_int(sample_context.get("trainee_card_id")) == target_trainee
            )
            if not usable_context:
                continue
            for turn in data.get("turns") or []:
                if not isinstance(turn, dict):
                    continue
                for event in turn.get("events") or []:
                    if not isinstance(event, dict) or event.get("event") != "race_result":
                        continue
                    race = event.get("race") or {}
                    pid = _as_int(event.get("program_id") or race.get("program_id"))
                    if not pid:
                        continue
                    won = bool(event.get("won") or event.get("finish_rank") == 1 or event.get("status") == "won")
                    for bucket in (by_pid, exact_by_pid if exact_match else None):
                        if bucket is None:
                            continue
                        row = bucket[pid]
                        row["runs"] += 1
                        row["wins"] += 1 if won else 0
                        row["losses"] += 0 if won else 1
                        row["race_name"] = race.get("name") or row.get("race_name") or ""
                        row["grade"] = race.get("grade") or row.get("grade") or ""
                        row["distance"] = race.get("distance") or row.get("distance") or ""
            sources.append(str(path))

    use_exact = sum(row["runs"] for row in exact_by_pid.values()) >= EXACT_CONTEXT_MIN_RACE_SAMPLES
    chosen = exact_by_pid if use_exact else by_pid
    if not chosen:
        return finish({
            "enabled": False,
            "sample_count": 0,
            "source_paths": sources,
            "reason": "not_enough_observed_race_results",
        })

    by_pid_out = {}
    for pid, row in chosen.items():
        runs = int(row.get("runs") or 0)
        if runs <= 0:
            continue
        wins = int(row.get("wins") or 0)
        # Bayesian smoothing keeps 1/1 samples from becoming certainty, but
        # lets 7/7 samples become a strong safety signal.
        smoothed = (wins + 1.5) / (runs + 3.0)
        by_pid_out[str(pid)] = {
            "wins": wins,
            "runs": runs,
            "losses": int(row.get("losses") or 0),
            "win_rate": wins / runs,
            "smoothed_win_rate": smoothed,
            "race_name": row.get("race_name") or "",
            "grade": row.get("grade") or "",
            "distance": row.get("distance") or "",
        }
    return finish({
        "enabled": True,
        "used_exact_context": use_exact,
        "sample_count": sum(row["runs"] for row in chosen.values()),
        "race_count": len(by_pid_out),
        "source_paths": sources,
        "by_pid": by_pid_out,
    })


def _normalize_support_type(value):
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    return SUPPORT_TYPE_ALIASES.get(raw, raw)


def _support_max_level_estimate(rarity, lb):
    """Max trainable level for a support card by rarity + LB.

    Used to gate `unique_effects` whose `unlock_level` requirement must
    be ≤ the card's max level. Per game data: R 30/35/40/45/50,
    SR 35/40/45/50/55, SSR 40/45/50/50/50 across LB 0–4.
    """
    try:
        lb = max(0, min(4, int(lb or 0)))
    except (TypeError, ValueError):
        lb = 0
    r = str(rarity or "").upper()
    if r == "SSR":
        return [40, 45, 50, 50, 50][lb]
    if r == "SR":
        return [35, 40, 45, 50, 55][lb]
    return [30, 35, 40, 45, 50][lb]


def _skill_norm(text):
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _sim_skill_group_id(skill_id):
    try:
        skill_id = int(skill_id or 0)
    except (TypeError, ValueError):
        return 0
    if skill_id <= 0:
        return 0
    return skill_id if skill_id < 100000 else skill_id // 10


def _estimated_sim_skill_point_cost(skill_id, name="", hint_level=0):
    """Mirror the app-side owned-skill cost estimate used for parent memory.

    The activation datamine carries useful metadata, but several local rows have
    lower costs than the app's final-owned-skill estimator. Using this as a
    floor keeps simulator SP spending tied to the same real-data path used by
    observed parent records.
    """
    try:
        skill_id = int(skill_id or 0)
    except (TypeError, ValueError):
        skill_id = 0
    try:
        hint_level = int(hint_level or 0)
    except (TypeError, ValueError):
        hint_level = 0
    name = str(name or "")
    # Character unique skills are granted/leveled by career events and are not
    # bought with SP. Counting them as paid skills inflated parent SP estimates.
    if 0 < skill_id < 200000:
        return 0
    circle_markers = ("○", "◯", "◎", "\u25cb", "\u25ef", "Ã¢â€”â€¹", "Ã¢â€”Â¯")
    if any(marker in name for marker in circle_markers):
        base = 110
    elif skill_id >= 900000:
        base = 200
    elif skill_id % 10 >= 2:
        base = 180
    else:
        base = 120
    return max(1, int(base * (100 - min(max(hint_level, 0), 5) * 10) / 100))


def _event_name_norm(text):
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _parse_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _load_skill_rating_metadata(project_root):
    """Load DaftYuda/UmaTools skill rating metadata keyed by normalized name."""
    root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
    paths = [
        root / "data" / "uma_skills.csv",
        root / "uma_runtime" / "skill_rating" / "uma_skills.csv",
    ]
    source = next((path for path in paths if path.exists()), None)
    if not source:
        return {}
    meta = {}
    try:
        with source.open("r", encoding="utf-8-sig", newline="") as fh:
            for row in csv.DictReader(fh):
                name = str(row.get("name") or "").strip()
                if not name:
                    continue
                aliases = []
                for field in ("name", "alias_name", "localized_name"):
                    raw = str(row.get(field) or "")
                    for part in raw.replace("|", "\n").splitlines():
                        text = part.strip()
                        if text:
                            aliases.append(text)
                roles = []
                for raw_role in str(row.get("affinity_role") or "").replace(",", "/").split("/"):
                    role = _normalize_skill_role(raw_role)
                    if role and role not in roles:
                        roles.append(role)
                entry = {
                    "name": name,
                    "category": str(row.get("skill_type") or "").strip().lower(),
                    "roles": roles,
                    "base": _parse_float(row.get("base_value")),
                    "scores": {
                        "good": _parse_float(row.get("S_A"), None),
                        "average": _parse_float(row.get("B_C"), None),
                        "bad": _parse_float(row.get("D_E_F"), None),
                        "terrible": _parse_float(row.get("G"), None),
                    },
                }
                for alias in aliases:
                    key = _skill_norm(alias)
                    if key:
                        meta.setdefault(key, entry)
    except OSError:
        return {}
    return meta


def _normalize_skill_role(value):
    text = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    aliases = {
        "front runner": "front",
        "nige": "front",
        "pace chaser": "pace",
        "senko": "pace",
        "late surger": "late",
        "sashi": "late",
        "end closer": "end",
        "oikomi": "end",
        "middle": "medium",
        "mid": "medium",
        "short": "sprint",
        "grass": "turf",
    }
    text = aliases.get(text, text)
    return text if text in LEGACY_APTITUDE_NAME_TO_KEY.values() else ""


def _style_key(value):
    if isinstance(value, int):
        return STYLE_NUM_TO_KEY.get(value, "pace")
    text = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
    if text in {"front", "front runner", "runner", "nige"}:
        return "front"
    if text in {"pace", "pace chaser", "leader", "senko"}:
        return "pace"
    if text in {"late", "late surger", "betweener", "sashi"}:
        return "late"
    if text in {"end", "end closer", "chaser", "oikomi"}:
        return "end"
    return "pace"


def _distance_key(value):
    text = str(value or "").strip().lower()
    if text in {"short", "sprint"}:
        return "sprint"
    if text in {"mile", "miles"}:
        return "mile"
    if text in {"middle", "medium", "mid"}:
        return "medium"
    if text == "long":
        return "long"
    return text


def _surface_key(value):
    text = str(value or "").strip().lower()
    if text in {"turf", "grass"}:
        return "turf"
    if text == "dirt":
        return "dirt"
    return text


def _aptitude_multiplier(value, default=1.0):
    if isinstance(value, str):
        return APTITUDE_MULTIPLIERS.get(value.strip().upper(), default)
    try:
        return APTITUDE_MULTIPLIERS.get(int(value), default)
    except (TypeError, ValueError):
        return default


def _percentile(values, pct):
    values = sorted(float(value) for value in values if value is not None)
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    idx = int(round((max(0.0, min(100.0, float(pct))) / 100.0) * (len(values) - 1)))
    return values[max(0, min(len(values) - 1, idx))]


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _factor_category(category, factor=None):
    raw = str(category or (factor or {}).get("category") or "").strip().lower()
    fid = _as_int((factor or {}).get("id"))
    base_id = fid // 100 if fid > 0 else 0
    if raw == "blue":
        return "stat"
    if raw == "pink":
        return "aptitude"
    if raw in {"green", "chara", "character"}:
        return "unique"
    if raw == "white":
        return "skill"
    if raw in {"stat", "aptitude", "race", "skill", "scenario", "unique"}:
        return raw
    if 100000 <= base_id < 200000:
        return "unique"
    if 30000 <= base_id < 40000:
        return "scenario"
    if 20000 <= base_id < 30000:
        return "skill"
    if 10000 <= base_id < 20000:
        return "race"
    if 1 <= base_id <= 5:
        return "stat"
    if 11 <= base_id <= 34:
        return "aptitude"
    return raw or "other"


def _legacy_aptitude_delta(total_stars):
    total_stars = max(0, int(total_stars or 0))
    if total_stars < 1:
        return 0
    return min(4, ((total_stars - 1) // 3) + 1)


def _load_g1_calendar(project_root=None):
    """Load the G1 race calendar from the real `RaceCatalog`.

    Returns a list of (turn, program_id, race_name, distance_category, era).
    Distance maps Sprint/Mile/Medium/Long. Era is junior (T<=24) /
    classic (T<=48) / senior.
    """
    try:
        from career_bot.race_schedule import RaceCatalog
        from career_bot.runner import runtime_output_root  # for project root
    except ImportError:
        return list(_FALLBACK_G1_CALENDAR)
    if project_root is None:
        project_root = Path(__file__).resolve().parents[1]
    try:
        cat = RaceCatalog(str(project_root))
    except Exception:
        return list(_FALLBACK_G1_CALENDAR)
    out = []
    for rid, race in (cat.by_id or {}).items():
        grade = str(race.get("type") or "").upper()
        if grade != "G1":
            continue
        turn = int(race.get("turn") or 0)
        if not (12 <= turn <= 72):
            continue
        pid = int(race.get("program_id") or 0)
        name = race.get("name") or ""
        dist = str(race.get("distance") or "").lower() or "medium"
        era = "junior" if turn <= 24 else "classic" if turn <= 48 else "senior"
        out.append((turn, pid, name, dist, era))
    out.sort()
    return out or list(_FALLBACK_G1_CALENDAR)


def _era_for_turn(turn):
    turn = int(turn or 0)
    if turn <= 24:
        return "junior"
    if turn <= 48:
        return "classic"
    return "senior"


def _load_preset_race_calendar(preset, project_root=None):
    rows = (preset or {}).get("custom_race_schedule") or []
    if not isinstance(rows, list) or not rows:
        return []
    catalog = None
    try:
        from career_bot.race_schedule import RaceCatalog
        root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
        catalog = RaceCatalog(root)
    except Exception:
        catalog = None

    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        turn = int(row.get("turn") or 0)
        pid = int(row.get("program_id") or 0)
        if not turn or not pid:
            continue
        race = (catalog.by_program_id.get(pid) if catalog else None) or {}
        name = row.get("name") or race.get("name") or f"Race {pid}"
        distance = _distance_key(row.get("distance") or race.get("distance"))
        era = _era_for_turn(turn)
        raw_style = row.get("style") or row.get("tactic") or row.get("strategy") or ""
        style = _style_key(raw_style) if raw_style else ""
        out.append((turn, pid, name, distance or "medium", era, style, bool(row.get("rival"))))
    out.sort(key=lambda item: (item[0], item[1]))
    return out


def _manual_race_data_candidates(project_root=None, preset=None):
    preferred = _preferred_runtime_instance(preset)
    candidates = []
    env_runtime = os.environ.get("UMA_RUNTIME_DIR")
    if env_runtime:
        env_path = Path(env_runtime)
        if env_path.name.lower() in {"account_a", "account_b"}:
            candidates.append(env_path / "manual_race_data.json")
        elif preferred:
            candidates.append(_runtime_root_from_path(env_path) / "instances" / preferred / "manual_race_data.json")

    for root in _runtime_roots(project_root):
        if preferred:
            candidates.append(root / "instances" / preferred / "manual_race_data.json")
        for instance_name in ("account_b", "account_a"):
            candidates.append(root / "instances" / instance_name / "manual_race_data.json")
        candidates.append(root / "manual_race_data.json")

    out = []
    seen = set()
    for candidate in candidates:
        key = _path_key(candidate)
        if key not in seen:
            out.append(Path(candidate))
            seen.add(key)
    return out


def _race_threshold_json_candidates(project_root=None, preset=None):
    preferred = _preferred_runtime_instance(preset)
    candidates = []
    runtime_paths = (preset or {}).get("auto_learning_runtime_paths") or []
    if isinstance(runtime_paths, str):
        runtime_paths = [runtime_paths]
    for raw in runtime_paths:
        if raw:
            candidates.append(Path(raw) / "race_thresholds.json")
    env_runtime = os.environ.get("UMA_RUNTIME_DIR")
    if env_runtime:
        env_path = Path(env_runtime)
        if env_path.name.lower() in {"account_a", "account_b"}:
            candidates.append(env_path / "race_thresholds.json")
        elif preferred:
            candidates.append(_runtime_root_from_path(env_path) / "instances" / preferred / "race_thresholds.json")
    for root in _runtime_roots(project_root):
        if preferred:
            candidates.append(root / "instances" / preferred / "race_thresholds.json")
        for instance_name in ("account_b", "account_a"):
            candidates.append(root / "instances" / instance_name / "race_thresholds.json")
        candidates.append(root / "race_thresholds.json")
    out = []
    seen = set()
    for candidate in candidates:
        key = _path_key(candidate)
        if key not in seen:
            out.append(Path(candidate))
            seen.add(key)
    return out


def _default_manual_race_data_path(project_root=None, preset=None):
    candidates = _manual_race_data_candidates(project_root, preset)
    for path in candidates:
        if path.exists():
            return path
    return candidates[0] if candidates else (
        Path(__file__).resolve().parents[1]
        / "uma_runtime" / "instances" / "account_b" / "manual_race_data.json"
    )


def _load_race_thresholds_from_manual_data(manual_race_data_path=None, project_root=None, preset=None):
    """Load per-race winning stat thresholds from the user's
    `manual_race_data.json`. Aggregates the median winning stats for
    each program_id across all trainees that won that race.
    """
    if manual_race_data_path is None:
        manual_race_data_path = _default_manual_race_data_path(project_root, preset)
    manual_race_data_path = Path(manual_race_data_path)
    if not manual_race_data_path.exists():
        return {}
    try:
        mrd = json.loads(manual_race_data_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    data = mrd.get("data") or {}
    from collections import defaultdict
    by_pid = defaultdict(list)
    by_pid_name = {}
    for card_id, races in data.items():
        if not isinstance(races, dict):
            continue
        for pid_str, race in races.items():
            if not isinstance(race, dict):
                continue
            wins = int(race.get("wins") or 0)
            if wins <= 0:
                continue
            mws = race.get("median_winning_stats") or {}
            if not mws:
                continue
            try:
                pid = int(pid_str)
            except (TypeError, ValueError):
                continue
            for _ in range(wins):
                by_pid[pid].append(mws)
            by_pid_name[pid] = race.get("race_name") or ""

    thresholds = {}
    for pid, win_list in by_pid.items():
        agg = {}
        for stat in ("speed", "stamina", "power", "guts", "wit"):
            vals = [int(w.get(stat) or 0) for w in win_list if w.get(stat)]
            if vals:
                agg[stat] = int(median(vals))
        if agg:
            # Index by both pid and race_name for downstream lookup convenience.
            thresholds[pid] = agg
            name = by_pid_name.get(pid) or ""
            if name:
                thresholds[name] = agg
    return thresholds


@dataclass
class SimResult:
    final_stats: dict
    stat_sum: int
    rank: str
    rating_score: int
    stat_rating_score: int
    unique_rating_bonus: int
    skill_rating_score: int
    g1_wins: int
    g1_losses: int
    skills_bought: int
    final_sp: int
    final_hp: int
    final_mood: int
    turns_logged: int
    races_run: list
    train_picks_by_stat: dict
    bonus_fires: dict
    purchased_skills: list = field(default_factory=list)
    shop_items_bought: int = 0
    shop_items_used: int = 0
    rival_races_run: int = 0
    race_continues_used: int = 0
    events_fired: list = field(default_factory=list)
    recreations_used: int = 0
    epithets_completed: list = field(default_factory=list)
    climax_bonus_races: int = 0
    sp_gain_sources: dict = field(default_factory=dict)
    fidelity_warnings: list = field(default_factory=list)
    training_decisions: list = field(default_factory=list)
    sim_hakuraku_races: list = field(default_factory=list)


# MANT epithet routes (uma.guide/trackblazer). Each entry maps a set name
# to the race names required and the +stat bonus granted on completion.
# +10 to 2 random stats for base epithets, +15 for chained ones.
MANT_EPITHET_SETS = [
    {"name": "Lady", "races": {"Oka Sho", "Japanese Oaks", "Shuka Sho"}, "bonus": 10},
    {"name": "Heroine", "races": {"Oka Sho", "Japanese Oaks", "Shuka Sho", "Queen Elizabeth II Cup"}, "bonus": 10},
    {"name": "Goddess", "races": {"Oka Sho", "Japanese Oaks", "Shuka Sho", "Victoria Mile", "Hanshin Juvenile Fillies", "Queen Elizabeth II Cup"}, "bonus": 15},
    {"name": "Stunning", "races": {"Satsuki Sho", "Tokyo Yushun (Japanese Derby)", "Kikuka Sho"}, "bonus": 10},
    {"name": "Incredible Classic JC", "races": {"Satsuki Sho", "Tokyo Yushun (Japanese Derby)", "Kikuka Sho", "Japan Cup"}, "bonus": 15},
    {"name": "Incredible Classic Arima", "races": {"Satsuki Sho", "Tokyo Yushun (Japanese Derby)", "Kikuka Sho", "Arima Kinen"}, "bonus": 15},
    {"name": "Breakneck Miler", "races": {"NHK Mile Cup", "Yasuda Kinen", "Mile Championship"}, "bonus": 15},
    {"name": "Sprint Go-Getter", "races": {"Takamatsunomiya Kinen", "Sprinters Stakes"}, "bonus": 15},
    # Phenomenal — per uma.guide/trackblazer: "Stunning + 2 of five major
    # races → +15". `prereq` (must all be matched, like the standard
    # `races`) plus `races` + `min_match` (at least K-of-N must be matched).
    # The five majors used here are Senior G1s outside Stunning itself.
    {
        "name": "Phenomenal",
        "prereq": {"Satsuki Sho", "Tokyo Yushun (Japanese Derby)", "Kikuka Sho"},
        "races": {"Tenno Sho (Spring)", "Tenno Sho (Autumn)",
                  "Takarazuka Kinen", "Japan Cup", "Arima Kinen"},
        "min_match": 2,
        "bonus": 15,
    },
    # Sprint Speedster — "four sprint/mile races → +15". The pool is the
    # five sprint/mile G1s; any four trigger the epithet.
    {
        "name": "Sprint Speedster",
        "races": {"Takamatsunomiya Kinen", "Sprinters Stakes",
                  "NHK Mile Cup", "Yasuda Kinen", "Mile Championship"},
        "min_match": 4,
        "bonus": 15,
    },
]

EPITHET_STAT_KEYS = ("speed", "stamina", "power", "guts", "wiz")


def _rank_for_stat_sum(stat_sum):
    """Deprecated compatibility helper.

    Do not use this for simulator rank output. In-game rank comes from
    `career_bot.rating`, not raw stat sum.
    """
    if stat_sum >= 4865: return "UG"
    if stat_sum >= 4635: return "SS"
    if stat_sum >= 4480: return "S+"
    if stat_sum >= 4075: return "S"
    if stat_sum >= 3700: return "A+"
    if stat_sum >= 3400: return "A"
    return "B+"


RANK_ORDER_VALUE = {label: index for index, (_minimum, label) in enumerate(RATING_BADGE_MINIMA)}


class CareerSimulator:
    def __init__(
        self,
        *,
        preset,
        deck=None,
        trainee_card_id=1004,
        race_thresholds=None,
        seed=None,
        scheduled_g1s=None,
        project_root=None,
        manual_race_data_path=None,
    ):
        """
        Args:
            preset: full preset dict (will be mutated for `_run_context`).
            deck: list of {type: "Speed"/"Stamina"/etc, name: str}.
                Defaults to the user's `[2, 0, 1, 0, 3]` deck.
            trainee_card_id: chara card_id (used for manual_race_data lookups).
            race_thresholds: optional override for per-race winning stat
                thresholds. If None, loaded from user's manual_race_data.json
                (real winning-stat medians per program_id).
            seed: RNG seed for deterministic replay.
            scheduled_g1s: optional list of (turn, pid, name, distance, era).
                If None, loaded from the real `RaceCatalog` (380 races).
            project_root: optional override for project root (used to find
                RaceCatalog data + manual_race_data). Defaults to inferring
                from this module's location.
            manual_race_data_path: optional override for the path to
                manual_race_data.json. Defaults to account_b's instance.
        """
        from career_bot.races import RacePlanner
        from career_bot.scenarios.mant import MantStrategy

        self.project_root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
        self.preset = hydrate_preset_with_latest_session_context(preset, self.project_root)
        self.preset.setdefault("name", "sim_preset")
        self.preset.setdefault("learn_skill_threshold", 444)
        self.preset.setdefault("manual_purchase_at_end", True)
        self.preset.setdefault("scenario_id", 4)
        self.preset.setdefault("calendar_race_prebuy_enabled", True)
        self.preset.setdefault("calendar_race_prebuy_all_scheduled", True)
        self.preset.setdefault("scheduled_race_clean_record_mode", True)
        self.preset.setdefault("calendar_race_clean_prebuy_min_sp", 120)
        self.preset.setdefault("calendar_race_clean_prebuy_budget", 1000)
        self.preset.setdefault("calendar_race_clean_prebuy_keep_sp", 0)
        self.preset.setdefault("calendar_race_clean_prebuy_max_skills", 8)
        # Wire stat_value_multiplier defaults so scoring works
        self.preset.setdefault("stat_value_multiplier", [0.022, 0.016, 0.018, 0.012, 0.016, 0.01])
        self.preset.setdefault("score_value", [[0.11, 0.1, 0.006, 0.09]] * 5)
        self.preset.setdefault("base_score", [0, 0, 0, 0, 0])
        self.preset.setdefault("extra_weight", [[0, 0, 0, 0, 0]] * 4)
        self.preset.setdefault("compensate_failure", True)
        self.preset.setdefault("expect_attribute", [9999, 9999, 9999, 9999, 9999])
        self.latest_session_context_source = self.preset.get("_sim_latest_session_context_source") or ""

        run_context_deck = (self.preset.get("_run_context") or {}).get("support_cards") or []
        # Default sims should follow the latest live session, but explicit
        # deck arguments must remain authoritative for A/B deck experiments.
        self.deck = deck or run_context_deck or [
            {"type": "Speed", "name": "Kitasan Black"},
            {"type": "Speed", "name": "Silence Suzuka"},
            {"type": "Power", "name": "Marvelous Sunday"},
            {"type": "Wit",   "name": "Mihono Bourbon"},
            {"type": "Wit",   "name": "Nice Nature"},
        ]
        self.support_bonus_data = _load_json_data("support_card_bonuses.json", {})
        self.chara_growth_data = _load_json_data("chara_growth_rates.json", {})
        self.training_curves = _load_json_data("training_facility_curves.json", {})
        self.race_demands = _load_json_data("race_distance_demands.json", {}).get("entries", {})
        self.real_training_snapshots = _load_json_data("real_training_snapshots.json", {}).get("snapshots", [])
        self.runtime_training_observation_count = 0
        if (
            load_runtime_training_snapshots
            and bool(self.preset.get("sim_use_runtime_observations", True))
        ):
            runtime_training_limit = int(self.preset.get("sim_runtime_training_snapshot_limit") or 12000)
            runtime_training_snapshots = load_runtime_training_snapshots(
                self.project_root,
                run_context=self.preset.get("_run_context") or {},
                max_records=runtime_training_limit,
            )
            if runtime_training_snapshots:
                self.real_training_snapshots = list(self.real_training_snapshots or []) + runtime_training_snapshots
                self.runtime_training_observation_count = len(runtime_training_snapshots)
        self.real_race_data = _load_json_data("real_race_snapshots.json", {})
        self.real_race_result_samples = self.real_race_data.get("result_samples", []) or []
        self.real_race_field_samples = self.real_race_data.get("field_samples", []) or []
        self.real_shop_data = _load_json_data("real_shop_snapshots.json", {})
        self.real_shop_summary = self.real_shop_data.get("summary", {}) or {}
        self.runtime_shop_observation_count = 0
        if (
            load_runtime_shop_summary
            and merge_shop_summaries
            and bool(self.preset.get("sim_use_runtime_observations", True))
        ):
            runtime_shop_limit = int(self.preset.get("sim_runtime_shop_snapshot_limit") or 50000)
            runtime_shop = load_runtime_shop_summary(
                self.project_root,
                run_context=self.preset.get("_run_context") or {},
                max_records=runtime_shop_limit,
            )
            runtime_shop_summary = runtime_shop.get("summary") if isinstance(runtime_shop, dict) else {}
            if runtime_shop_summary:
                self.real_shop_summary = merge_shop_summaries(self.real_shop_summary, runtime_shop_summary)
                self.runtime_shop_observation_count = int(runtime_shop.get("snapshot_count") or 0)
        self.runtime_event_observations = []
        self.runtime_event_summary = {}
        self.runtime_event_observation_count = 0
        if (
            load_runtime_event_observations
            and bool(self.preset.get("sim_use_runtime_observations", True))
        ):
            runtime_event_limit = int(self.preset.get("sim_runtime_event_observation_limit") or 50000)
            runtime_events = load_runtime_event_observations(
                self.project_root,
                run_context=self.preset.get("_run_context") or {},
                max_records=runtime_event_limit,
            )
            if isinstance(runtime_events, dict):
                self.runtime_event_observations = runtime_events.get("events") or []
                self.runtime_event_summary = {
                    key: value
                    for key, value in runtime_events.items()
                    if key != "events"
                }
                self.runtime_event_observation_count = int(runtime_events.get("event_count") or 0)
        self.event_effect_templates, self.event_effect_source_path = _load_event_effect_templates(self.project_root)
        self.event_id_index = _load_json_data("event_id_index.json", {})
        self.event_templates_by_name = self._build_event_template_name_index()
        self.fidelity_warnings = []
        if self.runtime_training_observation_count:
            self.fidelity_warnings.append(
                f"runtime sim observations: {self.runtime_training_observation_count} training snapshots loaded"
            )
        if self.runtime_shop_observation_count:
            self.fidelity_warnings.append(
                f"runtime sim observations: {self.runtime_shop_observation_count} shop snapshots loaded"
            )
        if self.runtime_event_observation_count:
            self.fidelity_warnings.append(
                f"runtime sim observations: {self.runtime_event_observation_count} event records loaded"
            )
        if self.latest_session_context_source:
            self.fidelity_warnings.append(
                f"using latest session context: {self.latest_session_context_source}"
            )
        elif self.preset.get("sim_use_latest_session_context") is not False:
            self.fidelity_warnings.append(
                "no usable latest session context found; using preset/default sim context"
            )
        run_context = self.preset.get("_run_context") or {}
        self.trainee_card_id = int(
            run_context.get("trainee_card_id")
            or self.preset.get("trainee_card_id")
            or trainee_card_id
            or 0
        )
        self.default_style = _style_key(
            self.preset.get("skill_profile_style")
            or (self.preset.get("_run_context") or {}).get("style")
            or (self.preset.get("_run_context") or {}).get("running_style")
        )
        self._active_race_style = self.default_style
        self.sim_support_cards = self._resolve_support_cards(self.deck)
        self.friend_event_skill_ids = self._friend_event_skill_ids()
        self._current_support_ids = {
            int(card.get("support_card_id") or 0)
            for card in self.sim_support_cards
            if int(card.get("support_card_id") or 0)
        }
        self._current_support_type_counts = self._support_type_count_map(self.sim_support_cards)
        self._snapshot_commands_cache = {}
        self._snapshot_support_ids_cache = {}
        self._snapshot_support_type_counts_cache = {}
        (
            self.real_training_snapshots_by_turn,
            self.real_training_snapshots_by_scenario_turn,
            self.real_training_snapshots_by_scenario,
        ) = self._index_real_training_snapshots()
        self._exact_training_snapshot_deck_matches = self._count_exact_training_snapshot_deck_matches()
        self._min_exact_training_snapshot_matches = int(self.preset.get("sim_min_exact_training_snapshot_matches") or 30)
        if bool(self.preset.get("sim_use_real_training_snapshots", True)) and self.real_training_snapshots:
            if self._exact_training_snapshot_deck_matches <= 0:
                self.fidelity_warnings.append(
                    "real_training_snapshots has no exact deck match; using nearest deck/type/state snapshots"
                )
            elif self._exact_training_snapshot_deck_matches < self._min_exact_training_snapshot_matches:
                self.fidelity_warnings.append(
                    "real_training_snapshots exact deck coverage is sparse "
                    f"({self._exact_training_snapshot_deck_matches}); downweighting exact-deck match"
                )
        self.preset.setdefault("_run_context", {})
        self.preset["_run_context"]["support_cards"] = [
            {
                "partner_id": int(card.get("partner_id") or 0),
                "support_card_id": int(card.get("support_card_id") or 0),
                "name": card.get("name") or "",
                "type": card.get("type") or "",
                "lb_level": int(card.get("lb") or 0),
            }
            for card in self.sim_support_cards
            if not card.get("friend")
        ] or self.deck
        self.preset["_run_context"]["support_card_ids"] = [
            int(card.get("support_card_id") or 0)
            for card in self.sim_support_cards
            if not card.get("friend") and int(card.get("support_card_id") or 0)
        ]
        self.preset["_run_context"]["trainee_card_id"] = self.trainee_card_id
        self.preset["_run_context"]["deck_type_counts"] = self._deck_type_counts()
        # Some downstream code reads this from preset directly.
        self.preset["_deck_type_counts"] = self._deck_type_counts()

        # Load real per-race winning thresholds from manual_race_data
        # (or use the caller's override). Falls back to a small hardcoded
        # set if the user's data isn't on disk (e.g., in CI tests).
        self.manual_race_data_path = Path(manual_race_data_path) if manual_race_data_path else _default_manual_race_data_path(self.project_root, self.preset)
        loaded_thresholds = _load_race_thresholds_from_manual_data(self.manual_race_data_path, self.project_root, self.preset)
        if loaded_thresholds:
            self.fidelity_warnings.append(f"manual race thresholds: {self.manual_race_data_path}")
        else:
            self.fidelity_warnings.append("manual race thresholds unavailable; using fallback race thresholds")
        self.race_thresholds = dict(loaded_thresholds) if loaded_thresholds else {
            # Minimal fallback for CI/tests where manual_race_data.json isn't present
            "Tokyo Yushun (Japanese Derby)": {"speed": 405, "stamina": 317, "power": 443, "guts": 327, "wit": 404},
            "Kikuka Sho":                    {"speed": 631, "stamina": 380, "power": 569, "guts": 408, "wit": 525},
            "Japan Cup":                     {"speed": 683, "stamina": 477, "power": 623, "guts": 403, "wit": 614},
            "Arima Kinen":                   {"speed": 844, "stamina": 458, "power": 691, "guts": 456, "wit": 625},
            "Tenno Sho (Spring)":            {"speed": 751, "stamina": 533, "power": 723, "guts": 434, "wit": 765},
        }
        if race_thresholds:
            self.race_thresholds.update(race_thresholds)
        # Prefer the preset's real race calendar. Fall back to the G1 catalog
        # when tests or ad-hoc sims do not provide a custom schedule.
        preset_calendar = _load_preset_race_calendar(self.preset, project_root)
        self.scheduled_g1s = list(scheduled_g1s or preset_calendar or _load_g1_calendar(project_root))
        self.race_catalog_by_program_id = self._load_race_catalog_by_program_id(project_root)
        self.race_samples_by_pid, self.race_fields_by_pid, self.race_samples_by_profile = self._index_real_race_data()
        self.rival_program_ids = {
            int(pid) for pid in (self.real_shop_summary.get("rival_programs") or {})
            if str(pid).isdigit()
        }
        self.parent_library = self._load_parent_library()
        self.selected_parent_ids = self._selected_parent_ids()
        self.selected_parents = self._resolve_selected_parents()
        self.legacy_effects = self._compute_legacy_effects()
        self.rng = random.Random(seed)
        # State
        self.state = self._initial_state()
        # Tracking
        self.train_picks = {"speed": 0, "stamina": 0, "power": 0, "guts": 0, "wit": 0}
        self.bonus_fires = defaultdict(int)
        self.training_decisions = []
        self.races_run = []
        self.sim_hakuraku_races = []
        self.skills_bought = 0
        self.skill_sp_spent = 0
        self.skill_rating_score = 0
        self.purchased_skills = []
        self._purchased_skill_ids = set()
        self.sp_gain_sources = defaultdict(int)
        if int(self.state.get("skill_point") or 0) > 0:
            self.sp_gain_sources["initial"] += int(self.state.get("skill_point") or 0)
        self.skill_rating_meta = _load_skill_rating_metadata(self.project_root)
        self.skill_rating_calibration = load_empirical_skill_rating_calibration(
            self.project_root,
            run_context=self.preset.get("_run_context") or {},
            trainee_card_id=self.trainee_card_id,
        )
        self.skill_rating_calibration = self._finalize_empirical_skill_rating_calibration()
        if self.skill_rating_calibration.get("enabled"):
            self.fidelity_warnings.append(
                "empirical skill-rating calibration: "
                f"{self.skill_rating_calibration.get('sample_count')} parent samples, "
                f"target skills={self.skill_rating_calibration.get('skill_count_target')}, "
                f"target skill score={self.skill_rating_calibration.get('skill_rating_target')}, "
                f"raw scale={self.skill_rating_calibration.get('raw_skill_rating_scale', 'n/a')}"
            )
        else:
            self.fidelity_warnings.append(
                "empirical skill-rating calibration unavailable; using fallback skill rating defaults"
            )
        self.sim_skill_candidates = self._build_sim_skill_candidates()
        self.skill_rating_calibration = self._finalize_empirical_skill_cost_calibration()
        if self.skill_rating_calibration.get("skill_cost_scale"):
            self.fidelity_warnings.append(
                "empirical skill-cost calibration: "
                f"target spend={self.skill_rating_calibration.get('skill_spend_target')}, "
                f"target avg cost={self.skill_rating_calibration.get('skill_cost_per_skill_target'):.1f}, "
                f"cost scale={self.skill_rating_calibration.get('skill_cost_scale'):.3f}"
            )
        self.sp_budget_calibration = load_empirical_sp_budget_calibration(
            self.project_root,
            run_context=self.preset.get("_run_context") or {},
            trainee_card_id=self.trainee_card_id,
        )
        self.race_sp_reward_scale = 1.0
        self.nonrace_sp_reward_scale = 1.0
        self.event_sp_reward_scale = 1.0
        if self.sp_budget_calibration.get("enabled"):
            self.fidelity_warnings.append(
                "empirical SP source calibration: "
                f"{self.sp_budget_calibration.get('sample_count')} finished careers, "
                f"source SP={self.sp_budget_calibration.get('source_sp_budget_target')}, "
                f"target final SP={self.sp_budget_calibration.get('final_sp_target')}, "
                f"race win-rate={float(self.sp_budget_calibration.get('race_win_rate_target') or 0):.3f}"
            )
        else:
            self.fidelity_warnings.append(
                "empirical SP source calibration unavailable; using mechanical training SP and unscaled event/race SP"
            )
        self.race_stat_gain_calibration = load_empirical_race_stat_gain_calibration(
            self.project_root,
            run_context=self.preset.get("_run_context") or {},
            trainee_card_id=self.trainee_card_id,
        )
        if self.race_stat_gain_calibration.get("enabled"):
            dist = self.race_stat_gain_calibration.get("distribution") or {}
            self.fidelity_warnings.append(
                "empirical race-stat distribution: "
                f"{self.race_stat_gain_calibration.get('sample_count')} race-turn samples, "
                f"exact={self.race_stat_gain_calibration.get('used_exact_context')}, "
                f"median total={self.race_stat_gain_calibration.get('median_total_gain')}, "
                f"spd={float(dist.get('speed') or 0):.2f}, "
                f"sta={float(dist.get('stamina') or 0):.2f}, "
                f"pwr={float(dist.get('power') or 0):.2f}, "
                f"gut={float(dist.get('guts') or 0):.2f}, "
                f"wit={float(dist.get('wit') or 0):.2f}"
            )
        else:
            self.fidelity_warnings.append(
                "empirical race-stat distribution unavailable; using balanced race stat distribution"
            )
        self.race_outcome_calibration = load_empirical_race_outcome_calibration(
            self.project_root,
            run_context=self.preset.get("_run_context") or {},
            trainee_card_id=self.trainee_card_id,
        )
        if self.race_outcome_calibration.get("enabled"):
            self.fidelity_warnings.append(
                "empirical race-outcome calibration: "
                f"{self.race_outcome_calibration.get('sample_count')} observed race results, "
                f"races={self.race_outcome_calibration.get('race_count')}, "
                f"exact={self.race_outcome_calibration.get('used_exact_context')}"
            )
        else:
            self.fidelity_warnings.append(
                "empirical race-outcome calibration unavailable; using stat/field race models only"
            )
        self.shop_items_bought = 0
        self.shop_items_used = 0
        self._last_race_reward_item_id = None
        self.rival_races_run = 0
        self.race_continues_used = 0
        self.events_fired = []
        self._seen_event_story_ids = set()
        self._observed_fixed_events_by_turn = self._build_observed_fixed_event_schedule()
        self._fired_observed_fixed_events = set()
        observed_fixed_count = sum(len(rows) for rows in self._observed_fixed_events_by_turn.values())
        if observed_fixed_count:
            self.fidelity_warnings.append(
                f"observed fixed event schedule: {observed_fixed_count} events across "
                f"{len(self._observed_fixed_events_by_turn)} turns"
            )
        self.recreations_used = 0
        self.stat_recreation_steps = {}
        self.race_names_won = set()
        self.epithets_completed = []
        self.climax_bonus_races = 0
        # Twinkle Star Climax final sequence. These are mandatory scenario
        # races in live MANT careers, not the user's planner calendar.
        self._final_climax_races = {
            74: (2315, "Twinkle Star Climax Race 1", "Mile", "climax"),
            76: (2412, "Twinkle Star Climax Race 2", "Mile", "climax"),
            78: (2513, "Twinkle Star Climax Race 3", "Mile", "climax"),
        }
        self._climax_turn_set = set(self._final_climax_races)
        self.race_sp_reward_scale = self._calibrated_race_sp_reward_scale()
        self.event_sp_reward_scale = self._calibrated_event_sp_reward_scale()
        self.nonrace_sp_reward_scale = 1.0
        self.fidelity_warnings.append(
            "SP reward model: "
            f"training=mechanical facility table, race={self.race_sp_reward_scale:.3f}, "
            f"event={self.event_sp_reward_scale:.3f}"
        )
        self._ensure_calendar_in_preset()

        # Use the same race planner + next_decision path as real careers.
        self.strategy = MantStrategy(race_planner=RacePlanner(str(self.project_root)))
        self.strategy.preset = self.preset

    def _ensure_calendar_in_preset(self):
        if isinstance(self.preset.get("custom_race_schedule"), list) and self.preset.get("custom_race_schedule"):
            return
        rows = []
        for row in self.scheduled_g1s or []:
            turn, pid, name, distance, era = row[:5]
            style = row[5] if len(row) > 5 else ""
            rival = bool(row[6]) if len(row) > 6 else False
            catalog = self.race_catalog_by_program_id.get(int(pid or 0)) or {}
            rows.append({
                "turn": int(turn or 0),
                "program_id": int(pid or 0),
                "name": name or catalog.get("name") or f"Race {pid}",
                "distance": (distance or catalog.get("distance") or "").title(),
                "type": catalog.get("type") or catalog.get("grade") or "",
                "terrain": catalog.get("terrain") or "",
                "venue": catalog.get("venue") or "",
                "style": style,
                "rival": rival,
                "_sim_fallback_calendar": True,
            })
        self.preset["custom_race_schedule"] = rows

    def _build_event_template_name_index(self):
        by_name = {}
        for template in self.event_effect_templates or []:
            if not isinstance(template, dict):
                continue
            key = _event_name_norm(template.get("event_name"))
            if key and key not in by_name:
                by_name[key] = template
        return by_name

    def _load_parent_library(self):
        candidates = []
        runtime_paths = self.preset.get("auto_learning_runtime_paths")
        if isinstance(runtime_paths, list):
            for raw in runtime_paths:
                if raw:
                    candidates.append(Path(raw) / "parent_memory" / "parent_library.json")
        candidates.extend([
            self.project_root / "uma_runtime" / "instances" / "account_a" / "parent_memory" / "parent_library.json",
            self.project_root / "uma_runtime" / "instances" / "account_b" / "parent_memory" / "parent_library.json",
            self.project_root / "uma_runtime" / "parent_memory" / "parent_library.json",
            self.project_root.parent / "uma_runtime" / "instances" / "account_a" / "parent_memory" / "parent_library.json",
            self.project_root.parent / "uma_runtime" / "instances" / "account_b" / "parent_memory" / "parent_library.json",
            self.project_root.parent / "uma_runtime" / "parent_memory" / "parent_library.json",
        ])
        parents = []
        seen = set()
        for path in candidates:
            try:
                data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            for parent in data.get("parents") or data.get("items") or data.get("library") or []:
                if not isinstance(parent, dict):
                    continue
                key = int(parent.get("instance_id") or parent.get("trained_chara_id") or parent.get("id") or 0)
                source_key = (key, int(parent.get("card_id") or 0), str(parent.get("name") or ""))
                if source_key in seen:
                    continue
                seen.add(source_key)
                parents.append(parent)
        return {"parents": parents}

    def _selected_parent_ids(self):
        ids = []
        ctx = self.preset.get("_run_context") or {}
        for key in ("parent_id_1", "parent_id_2", "borrow_fallback_id"):
            value = _as_int(ctx.get(key))
            if value:
                ids.append(value)
        parents = ctx.get("parents") or self.preset.get("parents") or {}
        if isinstance(parents, dict):
            for key in ("parent_1", "parent_2", "guest", "borrow"):
                row = parents.get(key)
                if isinstance(row, dict):
                    value = _as_int(row.get("instance_id") or row.get("trained_chara_id") or row.get("id"))
                    if value:
                        ids.append(value)
        elif isinstance(parents, list):
            for row in parents:
                if not isinstance(row, dict):
                    continue
                value = _as_int(row.get("instance_id") or row.get("trained_chara_id") or row.get("id"))
                if value:
                    ids.append(value)
        out = []
        for value in ids:
            if value not in out:
                out.append(value)
        return out[:2]

    def _resolve_selected_parents(self):
        def row_id(row):
            return _as_int(row.get("instance_id") or row.get("trained_chara_id") or row.get("id")) if isinstance(row, dict) else 0

        ctx = self.preset.get("_run_context") or {}
        inline = ctx.get("parents") or self.preset.get("parents") or {}
        inline_by_id = {}
        if isinstance(inline, dict):
            for key in ("parent_1", "parent_2", "guest", "borrow"):
                row = inline.get(key)
                rid = row_id(row)
                if rid and isinstance(row, dict):
                    inline_by_id.setdefault(rid, row)
        elif isinstance(inline, list):
            for row in inline:
                rid = row_id(row)
                if rid and isinstance(row, dict):
                    inline_by_id.setdefault(rid, row)

        parents = self.parent_library.get("parents") if isinstance(self.parent_library, dict) else []
        library_by_id = {}
        for parent in parents or []:
            if not isinstance(parent, dict):
                continue
            rid = row_id(parent)
            if rid and rid not in library_by_id:
                library_by_id[rid] = parent

        resolved = []
        for pid in self.selected_parent_ids:
            row = inline_by_id.get(pid)
            if isinstance(row, dict) and row.get("tree"):
                resolved.append(row)
                continue
            row = library_by_id.get(pid)
            if isinstance(row, dict):
                resolved.append(row)
                continue
            row = inline_by_id.get(pid)
            if isinstance(row, dict):
                resolved.append(row)

        if len(resolved) >= 2:
            return resolved[:2]

        # Last fallback: use any inline rich parent record not already selected.
        for row in inline_by_id.values():
            if not isinstance(row, dict) or not row.get("tree"):
                continue
            rid = row_id(row)
            if not rid:
                continue
            if all(row_id(parent) != rid for parent in resolved):
                resolved.append(row)
            if len(resolved) >= 2:
                break

        if len(resolved) < 2:
            for row in library_by_id.values():
                if not isinstance(row, dict):
                    continue
                rid = row_id(row)
                if not rid:
                    continue
                if all(row_id(parent) != rid for parent in resolved):
                    resolved.append(row)
                if len(resolved) >= 2:
                    break
        return resolved[:2]

    def _legacy_factor_entries(self, parents=None, nodes=LEGACY_NODES):
        entries = []
        for parent in parents if parents is not None else self.selected_parents:
            tree = parent.get("tree") if isinstance(parent, dict) else {}
            if not isinstance(tree, dict):
                continue
            for node_id in nodes:
                node = tree.get(node_id) or {}
                for factor in node.get("factors") or []:
                    if not isinstance(factor, dict):
                        continue
                    category = _factor_category(factor.get("category"), factor)
                    if category == "stat":
                        group = "stat"
                    elif category == "aptitude":
                        group = "aptitude"
                    elif category in {"scenario", "unique"}:
                        group = "green"
                    elif category in {"skill", "race"}:
                        group = "white"
                    else:
                        group = ""
                    entries.append({
                        "node": node_id,
                        "category": category,
                        "group": group,
                        "name": str(factor.get("name") or ""),
                        "stars": max(0, min(3, _as_int(factor.get("stars")))),
                        "id": factor.get("id"),
                        "effect_summary": str(factor.get("effect_summary") or ""),
                    })
        return entries

    def _compute_legacy_effects(self):
        stat_bonuses = {"speed": 0, "stamina": 0, "power": 0, "guts": 0, "wiz": 0}
        aptitude_stars = {key: 0 for key in LEGACY_APTITUDE_NAME_TO_KEY.values()}
        white_hints = []
        green_hints = []
        race_factor_stat_bonus = {"speed": 0, "stamina": 0, "power": 0, "guts": 0, "wiz": 0}
        inheritance_event_factors = []

        for entry in self._legacy_factor_entries():
            name_key = " ".join(str(entry.get("name") or "").strip().lower().replace("○", "").replace("◎", "").split())
            stars = _as_int(entry.get("stars"))
            if entry.get("group") == "stat":
                stat_key = LEGACY_STAT_NAME_TO_STATE_KEY.get(name_key)
                if stat_key:
                    stat_bonuses[stat_key] += LEGACY_BLUE_STAT_BONUS.get(max(0, min(3, stars)), 0)
            elif entry.get("group") == "aptitude":
                apt_key = LEGACY_APTITUDE_NAME_TO_KEY.get(name_key)
                if apt_key:
                    aptitude_stars[apt_key] += stars
            elif entry.get("category") == "race":
                white_hints.append(entry)
                summary = str(entry.get("effect_summary") or "").lower()
                stat_effects = {}
                for token, stat_key in LEGACY_STAT_NAME_TO_STATE_KEY.items():
                    if token and token in summary and stat_key in race_factor_stat_bonus:
                        race_factor_stat_bonus[stat_key] += max(1, stars) * 2
                        stat_effects[stat_key] = max(1, stars)
                if stat_effects:
                    inheritance_event_factors.append({
                        "category": "race",
                        "stars": stars,
                        "stat_effects": stat_effects,
                        "name": entry.get("name") or "",
                    })
            elif entry.get("group") == "white":
                white_hints.append(entry)
            elif entry.get("group") == "green":
                green_hints.append(entry)
                if entry.get("category") == "scenario":
                    summary = str(entry.get("effect_summary") or "").lower()
                    stat_effects = {}
                    for token, stat_key in LEGACY_STAT_NAME_TO_STATE_KEY.items():
                        if token and token in summary and stat_key in race_factor_stat_bonus:
                            race_factor_stat_bonus[stat_key] += max(1, stars) * 3
                            stat_effects[stat_key] = max(1, stars)
                    if stat_effects:
                        inheritance_event_factors.append({
                            "category": "scenario",
                            "stars": stars,
                            "stat_effects": stat_effects,
                            "name": entry.get("name") or "",
                        })

        base_aptitudes = dict((self.chara_growth_data.get(str(self.trainee_card_id)) or {}).get("base_aptitudes") or {})
        aptitude_upgrades = {}
        effective_aptitudes = dict(base_aptitudes)
        for apt_key, stars in aptitude_stars.items():
            delta = _legacy_aptitude_delta(stars)
            if delta <= 0:
                continue
            base = str(base_aptitudes.get(apt_key) or "").upper()
            if base not in APTITUDE_RANK_VALUE:
                continue
            next_value = min(APTITUDE_RANK_VALUE["A"], APTITUDE_RANK_VALUE[base] + delta)
            if next_value > APTITUDE_RANK_VALUE[base]:
                next_rank = APTITUDE_VALUE_RANK[next_value]
                effective_aptitudes[apt_key] = next_rank
                aptitude_upgrades[apt_key] = {
                    "base": base,
                    "next": next_rank,
                    "stars": stars,
                    "delta": next_value - APTITUDE_RANK_VALUE[base],
                }

        inherited_skill_hint_count = len(white_hints) + len(green_hints)
        inherited_unique_hint_count = len(green_hints)
        recovery_hint_count = 0
        stamina_hint_count = 0
        for hint in white_hints + green_hints:
            text = f"{hint.get('name') or ''} {hint.get('effect_summary') or ''}".lower()
            if any(token in text for token in ("recovery", "heal", "stamina", "endurance", "corner recovery", "straightaway recovery")):
                recovery_hint_count += 1
            if "stamina" in text or "long" in text:
                stamina_hint_count += 1

        return {
            "stat_bonuses": stat_bonuses,
            "race_factor_stat_bonus": race_factor_stat_bonus,
            "aptitude_stars": aptitude_stars,
            "aptitude_upgrades": aptitude_upgrades,
            "effective_aptitudes": effective_aptitudes,
            "inherited_skill_hint_count": inherited_skill_hint_count,
            "inherited_unique_hint_count": inherited_unique_hint_count,
            "recovery_hint_count": recovery_hint_count,
            "stamina_hint_count": stamina_hint_count,
            "legacy_skill_hints": [dict(row) for row in white_hints + green_hints],
            "inheritance_event_factors": inheritance_event_factors,
            "selected_parent_ids": list(self.selected_parent_ids),
            "selected_parent_names": [str(parent.get("name") or "") for parent in self.selected_parents],
        }

    def _load_race_catalog_by_program_id(self, project_root=None):
        try:
            from career_bot.race_schedule import RaceCatalog
            root = Path(project_root) if project_root else Path(__file__).resolve().parents[1]
            return dict(RaceCatalog(root).by_program_id or {})
        except Exception:
            return {}

    def _index_real_race_data(self):
        by_pid = defaultdict(list)
        by_profile = defaultdict(list)
        for sample in self.real_race_result_samples:
            if not isinstance(sample, dict):
                continue
            pid = int(sample.get("program_id") or 0)
            race = sample.get("race") or {}
            distance = _distance_key(race.get("distance"))
            grade = str(race.get("grade") or race.get("type") or "").upper()
            if pid and sample.get("raw_stats"):
                by_pid[pid].append(sample)
            if distance and sample.get("raw_stats"):
                by_profile[(distance, grade)].append(sample)
                by_profile[(distance, "")].append(sample)

        fields_by_pid = defaultdict(list)
        for sample in self.real_race_field_samples:
            if not isinstance(sample, dict):
                continue
            pid = int(sample.get("program_id") or 0)
            if pid and sample.get("opponents"):
                fields_by_pid[pid].append(sample)
        return by_pid, fields_by_pid, by_profile

    def _index_real_training_snapshots(self):
        by_turn = defaultdict(list)
        by_scenario_turn = defaultdict(list)
        by_scenario = defaultdict(list)
        for snapshot in self.real_training_snapshots or []:
            if not isinstance(snapshot, dict):
                continue
            turn = _as_int(snapshot.get("turn"))
            scenario_id = _as_int(snapshot.get("scenario_id"))
            if turn:
                by_turn[turn].append(snapshot)
            if scenario_id:
                by_scenario[scenario_id].append(snapshot)
                if turn:
                    by_scenario_turn[(scenario_id, turn)].append(snapshot)
        return by_turn, by_scenario_turn, by_scenario

    def _snapshot_support_ids(self, snapshot):
        cache = getattr(self, "_snapshot_support_ids_cache", None)
        cache_key = id(snapshot)
        if isinstance(cache, dict) and cache_key in cache:
            return cache[cache_key]
        ids = set()
        for row in (snapshot or {}).get("support_cards") or []:
            try:
                support_id = int(row.get("support_card_id") or 0)
            except (TypeError, ValueError):
                support_id = 0
            if support_id:
                ids.add(support_id)
        if isinstance(cache, dict):
            cache[cache_key] = ids
        return ids

    def _support_type_count_map(self, cards):
        counts = {key: 0 for key in ("speed", "stamina", "power", "guts", "wit", "friend", "group")}
        for card in cards or []:
            support_type = _normalize_support_type(card.get("type"))
            if support_type in counts:
                counts[support_type] += 1
        return counts

    def _snapshot_support_type_counts(self, snapshot):
        cache = getattr(self, "_snapshot_support_type_counts_cache", None)
        cache_key = id(snapshot)
        if isinstance(cache, dict) and cache_key in cache:
            return cache[cache_key]
        cards = []
        for row in (snapshot or {}).get("support_cards") or []:
            support_id = int(row.get("support_card_id") or 0)
            record = self.support_bonus_data.get(str(support_id)) or {}
            cards.append({"type": record.get("type") or row.get("type") or ""})
        counts = self._support_type_count_map(cards)
        if isinstance(cache, dict):
            cache[cache_key] = counts
        return counts

    def _count_exact_training_snapshot_deck_matches(self):
        current = getattr(self, "_current_support_ids", set()) or set()
        if not current:
            return 0
        matches = 0
        for snapshot in self.real_training_snapshots or []:
            if self._snapshot_support_ids(snapshot) == current:
                matches += 1
        return matches

    def _deck_type_counts(self):
        order = ["speed", "stamina", "power", "guts", "wit"]
        cards = getattr(self, "sim_support_cards", None) or self.deck
        return [sum(1 for c in cards if _normalize_support_type(c.get("type")) == t) for t in order]

    def _resolve_support_cards(self, deck):
        cards = []
        lb_lookup = (self.preset.get("_run_context") or {}).get("support_card_lb_levels") or {}

        def add_card(raw, *, friend=False):
            support_id = int(raw.get("support_card_id") or raw.get("id") or raw.get("card_id") or 0)
            if not support_id or any(card["support_card_id"] == support_id for card in cards):
                return
            record = self.support_bonus_data.get(str(support_id)) or {}
            raw_lb = raw.get("lb_level")
            if raw_lb is None:
                raw_lb = (lb_lookup.get(str(support_id)) or {}).get("lb")
            if raw_lb is None:
                raw_lb = 4 if friend else 0
            lb = max(0, min(4, int(raw_lb or 0)))
            lb_rows = record.get("lb_levels") or []
            effects = next((row for row in lb_rows if int(row.get("lb") or 0) == lb), None)
            if effects is None and lb_rows:
                effects = lb_rows[min(lb, len(lb_rows) - 1)]
            effects = dict(effects or {})
            # Merge only unconditional unique_effects into the LB effect dict. Each entry has
            # `key` (the field to add to), `value` (the amount), and
            # `unlock_level` (card level required to unlock). At LB 4 a
            # max-leveled card unlocks at level 50; LB 0 unlocks at 30.
            # Sim assumes cards are at their max level for their LB, so an
            # unlock_level <= max_level_for_lb fires. Max-level-per-LB
            # approximation: R 30/35/40/45/50, SR 35/40/45/50/55,
            # SSR 40/45/50/50/50. Treating as 50 for SSR LB4 and roughly
            # 5-per-LB lower otherwise — close enough for unlock_level
            # checks (most cards use 25/30).
            unique_effects = record.get("unique_effects") or []
            conditional_unique_effects = []
            max_level = _support_max_level_estimate(record.get("rarity"), lb)
            for ue in unique_effects:
                if not isinstance(ue, dict):
                    continue
                try:
                    unlock = int(ue.get("unlock_level") or 0)
                except (TypeError, ValueError):
                    unlock = 0
                if unlock and unlock > max_level:
                    continue
                if ue.get("condition") or ue.get("grants") or ue.get("grants_per_unit"):
                    conditional_unique_effects.append(dict(ue))
                    continue
                key = str(ue.get("key") or "").strip()
                if not key:
                    continue
                try:
                    value = float(ue.get("value") or 0)
                except (TypeError, ValueError):
                    value = 0.0
                if value == 0:
                    continue
                # Additive merge — unique effects stack on top of LB effects
                try:
                    existing = float(effects.get(key) or 0)
                except (TypeError, ValueError):
                    existing = 0.0
                merged = existing + value
                # Preserve integer-ness when the original was an int
                if isinstance(effects.get(key), int) and merged == int(merged):
                    effects[key] = int(merged)
                else:
                    effects[key] = merged
            cards.append({
                "partner_id": len(cards) + 1,
                "support_card_id": support_id,
                "name": record.get("name") or raw.get("name") or f"Support {support_id}",
                "type": _normalize_support_type(record.get("type") or raw.get("type")),
                "rarity": record.get("rarity") or raw.get("rarity") or "",
                "lb": lb,
                "effects": effects,
                "conditional_unique_effects": conditional_unique_effects,
                "friend": friend,
            })

        for raw in deck or []:
            if isinstance(raw, dict):
                add_card(raw)

        friend_card_id = int((self.preset.get("_run_context") or {}).get("friend_card_id") or 0)
        if friend_card_id:
            add_card({"support_card_id": friend_card_id, "lb_level": 4}, friend=True)
        return cards

    @staticmethod
    def _merge_effect_values(effects, grants, *, scale=1.0, max_grant=None):
        if not isinstance(grants, dict):
            return
        for key, raw_value in grants.items():
            if not key:
                continue
            try:
                value = float(raw_value or 0) * float(scale or 0)
            except (TypeError, ValueError):
                continue
            if max_grant is not None:
                try:
                    cap = abs(float(max_grant))
                    value = max(-cap, min(cap, value))
                except (TypeError, ValueError):
                    pass
            if value == 0:
                continue
            try:
                existing = float(effects.get(key) or 0)
            except (TypeError, ValueError):
                existing = 0.0
            merged = existing + value
            effects[key] = int(merged) if merged == int(merged) else merged

    def _card_bond(self, card):
        try:
            partner_id = int((card or {}).get("partner_id") or 0)
            return int((self.state.get("bonds") or {}).get(partner_id, 0))
        except Exception:
            return 0

    @staticmethod
    def _card_in_partners(card, partner_cards):
        partner_id = int((card or {}).get("partner_id") or 0)
        return any(int((row or {}).get("partner_id") or 0) == partner_id for row in (partner_cards or []))

    def _deck_distinct_support_type_count(self):
        return len({
            str(card.get("type") or "").lower()
            for card in (self.sim_support_cards or [])
            if str(card.get("type") or "").strip()
        })

    def _unique_effect_active(self, unique, card, *, training_stat=None, partner_cards=None, is_rainbow=False):
        condition = str((unique or {}).get("condition") or "").strip()
        if not condition:
            return True
        if condition == "bond_gte":
            return self._card_bond(card) >= int(unique.get("threshold") or 0)
        if condition == "bond_gte_off_type_training":
            return (
                self._card_bond(card) >= int(unique.get("threshold") or 0)
                and bool(training_stat)
                and str(card.get("type") or "") != str(training_stat)
            )
        if condition == "deck_distinct_support_types_gte":
            return self._deck_distinct_support_type_count() >= int(unique.get("threshold") or 0)
        if condition == "same_training_facility_support_count":
            return self._card_in_partners(card, partner_cards)
        if condition == "training_facility_level":
            return bool(training_stat)
        if condition in {"fans_scaled", "total_bond_scaled", "max_hp_scaled", "hp_scaled", "low_hp_scaled", "combined_facility_level_scaled"}:
            return True
        if condition == "friendship_training":
            return bool(is_rainbow) and str(card.get("type") or "") == str(training_stat) and self._card_bond(card) >= 80
        if condition in {"all_supports_initial_bonus", "deck_type_initial_stats"}:
            return True
        if condition == "bond_gte_all_supports_specialty_priority":
            return self._card_bond(card) >= int(unique.get("threshold") or 0)
        if condition == "owned_skill_category_count":
            return True
        return True

    def _unique_effect_scale(self, unique, card, *, training_stat=None, partner_cards=None, facility_level=None):
        condition = str((unique or {}).get("condition") or "").strip()
        if condition == "same_training_facility_support_count":
            return len(partner_cards or [])
        if condition == "training_facility_level":
            try:
                return int(facility_level or self._facility_level(training_stat))
            except Exception:
                return 1
        if condition == "fans_scaled":
            try:
                fans = int(self.state.get("fans") or 0)
                fans_per_step = max(1, int(unique.get("fans_per_step") or 1))
                max_grant = int(unique.get("max_grant") or 0)
                return max(0, min(max_grant, fans // fans_per_step))
            except Exception:
                return 0
        if condition == "total_bond_scaled":
            bonds = list((self.state.get("bonds") or {}).values())
            if not bonds:
                return 0
            max_grant = float(unique.get("max_grant") or 0)
            return max(0.0, min(max_grant, (sum(float(x or 0) for x in bonds) / max(1.0, len(bonds) * 100.0)) * max_grant))
        if condition == "max_hp_scaled":
            max_hp = int(self.state.get("max_hp") or 100)
            floor = int(unique.get("hp_floor") or 0)
            per_step = max(1, int(unique.get("hp_per_step") or 1))
            max_grant = int(unique.get("max_grant") or 0)
            return max(0, min(max_grant, (max_hp - floor) // per_step))
        if condition == "hp_scaled":
            hp = int(self.state.get("hp") or 0)
            per_step = max(1, int(unique.get("value_per_step") or 1))
            max_grant = int(unique.get("max_grant") or 0)
            return max(0, min(max_grant, hp // per_step))
        if condition == "low_hp_scaled":
            hp = int(self.state.get("hp") or 0)
            floor = int(unique.get("hp_floor") or 0)
            per_step = max(1, int(unique.get("hp_per_step") or 1))
            max_grant = int(unique.get("max_grant") or 0)
            return max(0, min(max_grant, (100 - max(floor, hp)) // per_step))
        if condition == "combined_facility_level_scaled":
            per_step = max(1, int(unique.get("level_per_step") or 1))
            max_grant = int(unique.get("max_grant") or 0)
            total = sum(int(self._facility_level(stat) or 1) for stat in STAT_KEYS)
            return max(0, min(max_grant, total // per_step))
        if condition == "owned_skill_category_count":
            max_count = int(unique.get("max_count") or 0)
            return max(0, min(max_count, int(self.skills_bought or 0)))
        return 1

    def _effective_card_effects(self, card, *, training_stat=None, partner_cards=None, is_rainbow=False, facility_level=None):
        effects = dict((card or {}).get("effects") or {})
        for source_card in self.sim_support_cards or []:
            for unique in source_card.get("conditional_unique_effects") or []:
                condition = str(unique.get("condition") or "")
                applies_to_all = condition in {
                    "all_supports_initial_bonus",
                    "bond_gte_all_supports_specialty_priority",
                }
                if source_card is not card and not applies_to_all:
                    continue
                if not self._unique_effect_active(
                    unique,
                    source_card,
                    training_stat=training_stat,
                    partner_cards=partner_cards,
                    is_rainbow=is_rainbow,
                ):
                    continue
                self._merge_effect_values(effects, unique.get("grants"))
                scale = self._unique_effect_scale(
                    unique,
                    source_card,
                    training_stat=training_stat,
                    partner_cards=partner_cards,
                    facility_level=facility_level,
                )
                self._merge_effect_values(
                    effects,
                    unique.get("grants_per_unit"),
                    scale=scale,
                    max_grant=unique.get("max_grant"),
                )
        return effects

    def _initial_card_effects(self, card):
        effects = dict((card or {}).get("effects") or {})
        for source_card in self.sim_support_cards or []:
            for unique in source_card.get("conditional_unique_effects") or []:
                condition = str(unique.get("condition") or "")
                if condition == "all_supports_initial_bonus":
                    self._merge_effect_values(effects, unique.get("grants"))
                elif source_card is card and condition == "deck_type_initial_stats":
                    same_type = int(unique.get("same_type_initial_stat") or 0)
                    friend_group = int(unique.get("friend_group_all_stats") or 0)
                    grants = {}
                    stat_by_type = {
                        "speed": "initial_speed",
                        "stamina": "initial_stamina",
                        "power": "initial_power",
                        "guts": "initial_guts",
                        "wit": "initial_wit",
                    }
                    for deck_card in self.sim_support_cards or []:
                        deck_type = str(deck_card.get("type") or "")
                        stat_key = stat_by_type.get(deck_type)
                        if stat_key:
                            grants[stat_key] = grants.get(stat_key, 0) + same_type
                        elif deck_type in {"friend", "group"}:
                            for key in stat_by_type.values():
                                grants[key] = grants.get(key, 0) + friend_group
                    self._merge_effect_values(effects, grants)
        return effects

    def _sum_partner_effect(self, partner_ids, effect_key):
        """Sum an effect key (e.g. 'failure_protection') across the cards
        whose partner_id appears in `partner_ids`. Friend cards count.
        """
        if not partner_ids:
            return 0.0
        wanted = {int(p) for p in partner_ids if isinstance(p, int) or str(p).isdigit()}
        total = 0.0
        for card in self.sim_support_cards or []:
            if int(card.get("partner_id") or 0) in wanted:
                try:
                    total += float(self._effective_card_effects(card).get(effect_key) or 0)
                except (TypeError, ValueError):
                    continue
        return total

    def _friend_support_card(self):
        for card in self.sim_support_cards or []:
            if card.get("friend") and card.get("type") == "friend":
                return card
        return None

    def _friend_event_skill_ids(self):
        card = self._friend_support_card()
        if not card:
            return set()
        support_id = int(card.get("support_card_id") or 0)
        row = self.support_bonus_data.get(str(support_id)) or self.support_bonus_data.get(support_id) or {}
        ids = set()
        for skill_id in row.get("event_skills") or []:
            try:
                ids.add(int(skill_id))
            except (TypeError, ValueError):
                continue
        return ids

    def _initial_skill_point(self):
        raw = self.preset.get("sim_initial_skill_point")
        if raw is None:
            raw = (self.preset.get("_run_context") or {}).get("initial_skill_point")
        if raw is not None:
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                pass

        values = []
        for snapshot in self.real_training_snapshots or []:
            try:
                turn = int(snapshot.get("turn") or 0)
                sp = int(snapshot.get("skill_point") or 0)
            except (TypeError, ValueError):
                continue
            if turn == 1 and sp > 0:
                values.append(sp)
        if values:
            return int(median(values))
        return 120

    def _initial_state(self):
        chara = self.chara_growth_data.get(str(self.trainee_card_id)) or {}
        initial = chara.get("initial_stats") or {}
        legacy_stats = (self.legacy_effects or {}).get("stat_bonuses") or {}
        bonds = {}
        # Support cards grant initial_<stat> bonuses (e.g. Riko Kashimoto SSR
        # MLB gives +30 initial_stamina). Sum across deck + friend slot.
        card_initial = {"speed": 0, "stamina": 0, "power": 0, "guts": 0, "wiz": 0}
        for card in self.sim_support_cards:
            effects = self._initial_card_effects(card)
            # Empirical (2026-06-12, 19 live account_b careers): starting
            # bonds cluster at 15-20 for cards without an initial_friendship
            # effect ({15: 35, 20: 38, 30: 15, 35: 19} across deck slots).
            # The old fallback of 30 made the sim's bond curve start ~12
            # points too high while its per-training gain ran too low.
            bonds[int(card["partner_id"])] = int(effects.get("initial_friendship") or 20)
            for stat_key, src_key in (
                ("speed", "initial_speed"), ("stamina", "initial_stamina"),
                ("power", "initial_power"), ("guts", "initial_guts"),
                ("wiz", "initial_wit"),
            ):
                card_initial[stat_key] += int(effects.get(src_key) or 0)
        return {
            "speed": int(initial.get("speed") or 90) + int(legacy_stats.get("speed") or 0) + card_initial["speed"],
            "stamina": int(initial.get("stamina") or 80) + int(legacy_stats.get("stamina") or 0) + card_initial["stamina"],
            "power": int(initial.get("power") or 80) + int(legacy_stats.get("power") or 0) + card_initial["power"],
            "guts": int(initial.get("guts") or 80) + int(legacy_stats.get("guts") or 0) + card_initial["guts"],
            "wiz": int(initial.get("wit") or 95) + int(legacy_stats.get("wiz") or 0) + card_initial["wiz"],
            "hp": 100, "max_hp": 100, "motivation": 4,
            "skill_point": self._initial_skill_point(),
            # Turn 1 is post-debut in this simulator. Start with enough fans
            # for the real RacePlanner's junior scheduled-race gate unless a
            # preset explicitly overrides it.
            "fans": int(self.preset.get("sim_initial_fans") or 1000),
            "turn": 1,
            "bonds": bonds or {1: 30, 2: 30, 3: 30, 4: 30, 5: 30, 6: 30},
            "mant_coin": 0,
            "inventory": {},
            "active_item_effects": [],
            "facility_item_boosts": {stat: 0 for stat in STAT_KEYS},
        }

    def _chara(self):
        # Return chara_info-shaped dict for use by MantStrategy
        evaluation_rows = []
        target_bond = int(self.preset.get("stat_friend_recreation_target_bond") or 60)
        for card in self.sim_support_cards:
            partner_id = int(card.get("partner_id") or 0)
            if not partner_id:
                continue
            support_id = int(card.get("support_card_id") or 0)
            bond = int(self.state["bonds"].get(partner_id, 0))
            row = {"target_id": partner_id, "evaluation": bond}
            if support_id in SIM_STAT_RECREATION_FRIEND_CARDS:
                max_uses = FRIEND_RECREATION_DEFAULT_MAX_USES
                taken = int((getattr(self, "stat_recreation_steps", {}) or {}).get(partner_id, 0))
                ready = (bond >= target_bond or self._sim_stat_recreation_story_unlocked(support_id, bond)) and taken < max_uses
                row.update({
                    "story_step": max(0, min(max_uses, taken)),
                    "is_outing": 1 if ready else 0,
                })
            evaluation_rows.append(row)
        return {
            "speed": self.state["speed"], "stamina": self.state["stamina"],
            "power": self.state["power"], "guts": self.state["guts"],
            "wiz": self.state["wiz"],
            "hp": self.state["hp"], "max_hp": self.state["max_hp"],
            "vital": self.state["hp"],  # alias used in some scoring code
            "motivation": self.state["motivation"],
            "skill_point": self.state["skill_point"],
            "fans": self.state.get("fans", 0),
            "turn": self.state["turn"],
            "playing_state": 1,
            "state": 1,
            "card_id": self.preset["_run_context"].get("trainee_card_id"),
            "succession_trained_chara_id_1": self.selected_parent_ids[0] if len(self.selected_parent_ids) > 0 else 0,
            "succession_trained_chara_id_2": self.selected_parent_ids[1] if len(self.selected_parent_ids) > 1 else 0,
            "evaluation_info_array": evaluation_rows,
        }

    def _sim_stat_recreation_story_unlocked(self, support_id, bond):
        """Simulator-only approximation for pal outing unlock events.

        Live code never uses this; it only trusts the game's `is_outing` row.
        The sim does not model Riko's invite event well enough yet, while live
        logs show Riko outings can be available around turn 9. Let the sim
        expose the outing row after that point so Riko pacing is testable.
        """
        try:
            support_id = int(support_id or 0)
            bond = int(bond or 0)
            turn = int(self.state.get("turn") or 0)
        except (TypeError, ValueError):
            return False
        if support_id != 30036:
            return False
        try:
            unlock_turn = int(self.preset.get("sim_riko_recreation_unlock_turn") or 9)
        except (TypeError, ValueError):
            unlock_turn = 9
        try:
            min_bond = int(self.preset.get("sim_riko_recreation_unlock_min_bond") or 25)
        except (TypeError, ValueError):
            min_bond = 25
        return turn >= unlock_turn and bond >= min_bond

    def _facility_level(self, stat_name):
        picks = int((self.train_picks or {}).get(stat_name, 0))
        boost = int((self.state.get("facility_item_boosts") or {}).get(stat_name, 0))
        return max(1, min(5, 1 + picks // 4 + boost))

    def _partner_cards_for_tile(self, stat_name):
        if not self.sim_support_cards:
            return []
        placement_cfg = (self.training_curves or {}).get("partner_placement") or {}
        preferred = float(placement_cfg.get("preferred_type_chance") or 0.42)
        off_type = float(placement_cfg.get("off_type_chance") or 0.10)
        friend_bonus = float(placement_cfg.get("friend_bonus_chance") or 0.05)
        specialty_scale = float(placement_cfg.get("specialty_priority_scale") or 500.0)
        max_specialty_bonus = float(placement_cfg.get("max_specialty_bonus") or 0.25)
        partners = []
        for card in self.sim_support_cards:
            effects = self._effective_card_effects(
                card,
                training_stat=stat_name,
                facility_level=self._facility_level(stat_name),
            )
            chance = preferred if card.get("type") == stat_name else off_type
            chance += min(max_specialty_bonus, float(effects.get("specialty_priority") or 0) / max(1.0, specialty_scale))
            if card.get("friend"):
                chance += friend_bonus
            if self.rng.random() < min(0.92, max(0.02, chance)):
                partners.append(card)
        if not partners:
            partners = [self.rng.choice(self.sim_support_cards)]
        return partners

    def _support_training_gain(self, training_stat, gain_stat, partner_cards, is_rainbow, facility_level):
        facilities = (self.training_curves or {}).get("facilities") or {}
        base_curve = ((facilities.get(training_stat) or {}).get(str(facility_level)) or {})
        base = float(base_curve.get(gain_stat) or 0)
        if base <= 0:
            return 0

        chara = self.chara_growth_data.get(str(self.trainee_card_id)) or {}
        growth = float((chara.get("growth_rates") or {}).get(gain_stat) or 0) / 100.0
        mood_value = int(self.state.get("motivation") or 3)
        mood = MOOD_BASE_EFFECT.get(mood_value, 0.0)

        stat_bonus = 0.0
        training_eff = 0.0
        mood_eff = 0.0
        friendship_eff = 0.0
        matching_bonded = 0
        for card in partner_cards:
            effects = self._effective_card_effects(
                card,
                training_stat=training_stat,
                partner_cards=partner_cards,
                is_rainbow=is_rainbow,
                facility_level=facility_level,
            )
            stat_bonus += float(effects.get(f"{gain_stat}_bonus") or 0)
            training_eff += float(effects.get("training_effectiveness") or 0)
            mood_eff += float(effects.get("mood_effect") or 0)
            if card.get("type") == training_stat and int(self.state["bonds"].get(int(card["partner_id"]), 0)) >= 80:
                matching_bonded += 1
                friendship_eff += float(effects.get("friendship_bonus") or 0)

        partner_mult = 1.0 + min(0.35, len(partner_cards) * 0.045)
        mood_mult = 1.0 + mood + (mood_eff / 100.0 * max(0.0, mood))
        training_mult = 1.0 + training_eff / 100.0
        friendship_mult = 1.0 + (friendship_eff / 100.0 if is_rainbow else 0.0)
        rainbow_mult = 1.0 + (0.12 * matching_bonded if is_rainbow else 0.0)
        variance = self.rng.uniform(0.92, 1.10)

        value = (base + stat_bonus) * (1.0 + growth) * mood_mult * training_mult
        value *= friendship_mult * rainbow_mult * partner_mult * variance
        # Empirical: 2.35 scale produced ~127 speed/training and capped most
        # sims at 1200 speed (real bot averages ~100 speed/training and lands
        # at ~890). Lower to 1.65 to match real-bot stat distributions.
        value *= float(self.preset.get("sim_training_gain_scale") or 1.65)
        return max(0, int(value))

    def _support_skill_point_gain(self, training_stat, partner_cards, is_rainbow, facility_level):
        facilities = (self.training_curves or {}).get("facilities") or {}
        base_curve = ((facilities.get(training_stat) or {}).get(str(facility_level)) or {})
        base = float(base_curve.get("skill_pt") or 0)
        active_effects = [
            self._effective_card_effects(
                card,
                training_stat=training_stat,
                partner_cards=partner_cards,
                is_rainbow=is_rainbow,
                facility_level=facility_level,
            )
            for card in partner_cards
        ]
        bonus = sum(float(effects.get("skill_pt_bonus") or 0) for effects in active_effects)
        training_eff = sum(float(effects.get("training_effectiveness") or 0) for effects in active_effects)
        mood = MOOD_BASE_EFFECT.get(int(self.state.get("motivation") or 3), 0.0)
        value = (base + bonus) * (1.0 + max(0.0, mood)) * (1.0 + training_eff / 100.0)
        value *= 1.0 + min(0.25, len(partner_cards) * 0.035)
        if is_rainbow:
            value *= 1.12
        return max(1, int(round(value)))

    def _support_energy_delta(self, training_stat, partner_cards, is_rainbow, facility_level):
        facilities = (self.training_curves or {}).get("facilities") or {}
        base_curve = ((facilities.get(training_stat) or {}).get(str(facility_level)) or {})
        if "energy" not in base_curve:
            return -HP_COSTS.get(training_stat, 10)
        energy = float(base_curve.get("energy") or 0)
        active_effects = [
            self._effective_card_effects(
                card,
                training_stat=training_stat,
                partner_cards=partner_cards,
                is_rainbow=is_rainbow,
                facility_level=facility_level,
            )
            for card in partner_cards
        ]
        reduction = sum(float(effects.get("energy_cost_reduction") or 0) for effects in active_effects)
        if energy < 0:
            # The simulator does not execute shop recovery items, so raw
            # game-side energy costs would force unrealistic rest spam.
            energy *= 0.55
            if reduction > 0:
                energy *= max(0.65, 1.0 - reduction / 100.0)
        if training_stat == "wit" and is_rainbow:
            recovery = sum(float(effects.get("wit_friendship_recovery") or 0) for effects in active_effects)
            energy += recovery
        return int(round(energy))

    def _real_snapshot_commands_by_stat(self, snapshot):
        cache = getattr(self, "_snapshot_commands_cache", None)
        cache_key = id(snapshot)
        if isinstance(cache, dict) and cache_key in cache:
            return cache[cache_key]
        result = {}
        for command in (snapshot or {}).get("commands") or []:
            stat = command.get("stat") or COMMAND_ID_TO_STAT.get(int(command.get("command_id") or 0))
            if stat in STAT_KEYS:
                result.setdefault(stat, []).append(command)
        if isinstance(cache, dict):
            cache[cache_key] = result
        return result

    def _real_snapshot_score(self, snapshot):
        if not snapshot:
            return 999999.0
        scenario_id = int(self.preset.get("scenario_id") or 0)
        snap_scenario = int(snapshot.get("scenario_id") or 0)
        if scenario_id and snap_scenario and scenario_id != snap_scenario:
            return 999999.0
        commands_by_stat = self._real_snapshot_commands_by_stat(snapshot)
        if not all(stat in commands_by_stat for stat in STAT_KEYS):
            return 999999.0
        level_penalty = 0
        for stat in STAT_KEYS:
            target_level = self._facility_level(stat)
            level_penalty += min(
                abs(int(command.get("level") or 1) - target_level)
                for command in commands_by_stat.get(stat) or [{"level": 1}]
            )
        current_ids = getattr(self, "_current_support_ids", set()) or set()
        snapshot_ids = self._snapshot_support_ids(snapshot)
        use_card_identity_match = (
            int(getattr(self, "_exact_training_snapshot_deck_matches", 0) or 0)
            >= int(getattr(self, "_min_exact_training_snapshot_matches", 30) or 30)
        )
        if use_card_identity_match:
            missing_current_cards = len(current_ids - snapshot_ids) if current_ids and snapshot_ids else len(current_ids)
            extra_snapshot_cards = len(snapshot_ids - current_ids) if current_ids and snapshot_ids else 0
        else:
            # A handful of exact-deck captures, especially all from one late
            # turn, are worse than nearest turn/state/type tiles. Use deck type
            # and state matching until exact coverage is broad enough.
            missing_current_cards = 0
            extra_snapshot_cards = 0

        current_type_counts = getattr(self, "_current_support_type_counts", {}) or {}
        snapshot_type_counts = self._snapshot_support_type_counts(snapshot)
        type_distance = sum(
            abs(int(current_type_counts.get(key) or 0) - int(snapshot_type_counts.get(key) or 0))
            for key in ("speed", "stamina", "power", "guts", "wit", "friend", "group")
        )

        stat_distance = 0.0
        snap_stats = snapshot.get("stats") or {}
        for key in ("speed", "stamina", "power", "guts", "wit"):
            state_key = "wiz" if key == "wit" else key
            stat_distance += abs(int(snap_stats.get(key) or 0) - int(self.state.get(state_key) or 0)) * 0.012

        sp_distance = abs(int(snapshot.get("skill_point") or 0) - int(self.state.get("skill_point") or 0)) * 0.006

        bond_distance = 0.0
        snap_bonds = snapshot.get("bonds") or {}
        for card in self.sim_support_cards or []:
            pid = int(card.get("partner_id") or 0)
            if not pid:
                continue
            try:
                snap_bond = int(snap_bonds.get(str(pid), snap_bonds.get(pid, 30)) or 0)
            except (TypeError, ValueError):
                snap_bond = 30
            bond_distance += abs(snap_bond - int((self.state.get("bonds") or {}).get(pid, 30))) * 0.055

        try:
            snap_card_id = int(snapshot.get("card_id") or 0)
        except (TypeError, ValueError):
            snap_card_id = 0
        trainee_penalty = 0.0 if snap_card_id == int(self.trainee_card_id or 0) else 4.0

        return (
            abs(int(snapshot.get("turn") or 0) - int(self.state.get("turn") or 0)) * 0.09
            + abs(int(snapshot.get("vital") or 0) - int(self.state.get("hp") or 0)) * 0.12
            + abs(int(snapshot.get("motivation") or 3) - int(self.state.get("motivation") or 3)) * 4.0
            + level_penalty * 5.5
            + missing_current_cards * 7.5
            + extra_snapshot_cards * 2.5
            + type_distance * 5.0
            + stat_distance
            + sp_distance
            + bond_distance
            + trainee_penalty
        )

    def _choose_real_training_snapshot(self):
        if not bool(self.preset.get("sim_use_real_training_snapshots", True)):
            return None
        if not self.real_training_snapshots:
            return None
        candidate_snapshots = self._real_training_snapshot_candidates()
        scored = [
            (self._real_snapshot_score(snapshot), snapshot)
            for snapshot in candidate_snapshots
        ]
        scored = [(score, snapshot) for score, snapshot in scored if score < 999999.0]
        if not scored:
            return None
        scored.sort(key=lambda item: item[0])
        pool_size = min(40, max(8, len(scored) // 20))
        return self.rng.choice([snapshot for _, snapshot in scored[:pool_size]])

    def _real_training_snapshot_candidates(self):
        """Return a nearby-turn subset of real snapshots before expensive scoring."""
        turn = _as_int(self.state.get("turn"))
        scenario_id = _as_int(self.preset.get("scenario_id"))
        min_candidates = max(40, _as_int(self.preset.get("sim_real_training_snapshot_min_candidates"), 140))
        max_radius = max(0, _as_int(self.preset.get("sim_real_training_snapshot_turn_radius"), 5))
        max_candidates = max(min_candidates, _as_int(self.preset.get("sim_real_training_snapshot_max_candidates"), 700))
        candidates = []
        seen = set()

        def add_many(rows):
            for row in rows or []:
                key = id(row)
                if key not in seen:
                    candidates.append(row)
                    seen.add(key)

        for radius in range(max_radius + 1):
            turns = [turn] if radius == 0 else [turn - radius, turn + radius]
            for candidate_turn in turns:
                if candidate_turn <= 0:
                    continue
                if scenario_id:
                    add_many(self.real_training_snapshots_by_scenario_turn.get((scenario_id, candidate_turn)))
                else:
                    add_many(self.real_training_snapshots_by_turn.get(candidate_turn))
            if len(candidates) >= min_candidates:
                break

        if not candidates and scenario_id:
            add_many(self.real_training_snapshots_by_scenario.get(scenario_id))
        if not candidates:
            add_many(self.real_training_snapshots)
        if len(candidates) > max_candidates:
            return self.rng.sample(candidates, max_candidates)
        return candidates

    def _make_real_training_commands(self):
        snapshot = self._choose_real_training_snapshot()
        if not snapshot:
            return []
        commands_by_stat = self._real_snapshot_commands_by_stat(snapshot)
        output = []
        for idx, stat_name in enumerate(["speed", "stamina", "power", "guts", "wit"]):
            target_level = self._facility_level(stat_name)
            candidates = commands_by_stat.get(stat_name) or []
            if not candidates:
                return []
            source = min(candidates, key=lambda command: abs(int(command.get("level") or 1) - target_level))
            gain_scale = self._real_training_gain_scale()
            params = []
            for item in source.get("params_inc_dec_info_array") or []:
                param = dict(item)
                if int(param.get("target_type") or 0) in {1, 2, 3, 4, 5} and int(param.get("value") or 0) > 0:
                    param["value"] = int(round(float(param.get("value") or 0) * gain_scale))
                params.append(param)
            raw_failure_rate = max(0, min(100, int(source.get("failure_rate") or 0)))
            # Apply failure_protection from any partner card on this tile.
            # Each unit of failure_protection reduces the percentage by 1
            # (game-mechanic approximation). Stacked additively.
            partner_ids_for_fp = list(source.get("training_partner_array") or [])
            partner_cards_for_fp = [
                card for card in self.sim_support_cards or []
                if int(card.get("partner_id") or 0) in {int(p) for p in partner_ids_for_fp if str(p).isdigit()}
            ]
            failure_protection_total = sum(
                float(self._effective_card_effects(
                    card,
                    training_stat=stat_name,
                    partner_cards=partner_cards_for_fp,
                    facility_level=target_level,
                ).get("failure_protection") or 0)
                for card in partner_cards_for_fp
            )
            adjusted_failure_rate = max(0, raw_failure_rate - int(round(failure_protection_total)))
            command = {
                "command_id": int(source.get("command_id") or STAT_TO_COMMAND_ID[stat_name]),
                "command_type": 1,
                "command_group_id": 0,
                "select_id": 0,
                "current_turn": self.state["turn"],
                "current_vital": self.state["hp"],
                "training_partner_array": list(source.get("training_partner_array") or []),
                "tips_event_partner_array": list(source.get("tips_event_partner_array") or []),
                "params_inc_dec_info_array": params,
                "failure_rate": adjusted_failure_rate,
                "is_enable": int(source.get("is_enable") or 1),
                "_sim_primary_stat": stat_name,
                "_sim_partner_count": int(source.get("partner_count") or len(source.get("training_partner_array") or [])),
                "_sim_facility_level": int(source.get("level") or target_level),
                "_sim_real_snapshot": True,
                "_sim_raw_failure_rate": raw_failure_rate,
                "_sim_failure_protection_applied": int(round(failure_protection_total)),
            }
            matching_bonded = 0
            for partner_id in command["training_partner_array"]:
                card = next((card for card in self.sim_support_cards if int(card.get("partner_id") or 0) == int(partner_id)), None)
                if card and card.get("type") == stat_name and self.state["bonds"].get(int(partner_id), 0) >= 80:
                    matching_bonded += 1
            command["_sim_is_rainbow"] = matching_bonded >= 1
            output.append(command)
        return output

    def _real_training_gain_scale(self):
        raw = self.preset.get("sim_real_training_gain_scale")
        if raw is not None:
            try:
                return float(raw)
            except (TypeError, ValueError):
                pass
        quality = 0.0
        for card in self.sim_support_cards or []:
            rarity = str(card.get("rarity") or "").upper()
            if rarity == "SSR":
                quality += 0.55 + (0.45 * max(0, min(4, int(card.get("lb") or 0))) / 4.0)
            elif rarity == "SR":
                quality += 0.45 + (0.25 * max(0, min(4, int(card.get("lb") or 0))) / 4.0)
            else:
                quality += 0.25
        deck_bonus = max(0.0, quality - REAL_TRAINING_GAIN_SCALE_DECK_QUALITY_BASELINE)
        deck_bonus *= REAL_TRAINING_GAIN_SCALE_DECK_QUALITY_STEP
        deck_bonus = min(REAL_TRAINING_GAIN_SCALE_MAX_DECK_BONUS, deck_bonus)
        return REAL_TRAINING_GAIN_SCALE_DEFAULT + deck_bonus

    def _make_training_commands(self):
        """Generate training tiles from facility level, support cards, mood, and growth."""
        real_commands = self._make_real_training_commands()
        if real_commands:
            return real_commands
        training_command_ids = {0: 101, 1: 105, 2: 102, 3: 103, 4: 106}
        target_types = {"speed": 1, "stamina": 2, "power": 3, "guts": 4, "wit": 5}
        stat_names = ["speed", "stamina", "power", "guts", "wit"]
        commands = []
        facilities = (self.training_curves or {}).get("facilities") or {}

        for idx, stat_name in enumerate(stat_names):
            facility_level = self._facility_level(stat_name)
            partner_cards = self._partner_cards_for_tile(stat_name)
            partners = [int(card["partner_id"]) for card in partner_cards]
            matching_bonded = sum(
                1 for card in partner_cards
                if card.get("type") == stat_name
                and int(self.state["bonds"].get(int(card["partner_id"]), 0)) >= 80
            )
            is_rainbow = matching_bonded >= 1
            params = []

            if stat_name in facilities:
                for gain_stat in STAT_KEYS:
                    gain = self._support_training_gain(stat_name, gain_stat, partner_cards, is_rainbow, facility_level)
                    if gain > 0:
                        params.append({"target_type": target_types[gain_stat], "value": gain})
                params.append({
                    "target_type": 30,
                    "value": self._support_skill_point_gain(stat_name, partner_cards, is_rainbow, facility_level),
                })
                params.append({
                    "target_type": 10,
                    "value": self._support_energy_delta(stat_name, partner_cards, is_rainbow, facility_level),
                })
            else:
                band = TRAINING_GAIN_BANDS[stat_name]
                gain = self.rng.randint(band[2], band[3]) if is_rainbow else self.rng.randint(band[0], band[1])
                gain = int(gain * MOOD_MULTIPLIERS.get(self.state["motivation"], 1.0))
                params = [
                    {"target_type": target_types[stat_name], "value": gain},
                    {"target_type": 30, "value": self.rng.randint(10, 18) + (3 if is_rainbow else 0)},
                    {"target_type": 10, "value": -HP_COSTS[stat_name]},
                ]

            raw_failure_rate = max(0, min(30, (100 - self.state["hp"]) // 3))
            # Apply failure_protection from partner cards
            failure_protection_total = sum(
                float(self._effective_card_effects(
                    card,
                    training_stat=stat_name,
                    partner_cards=partner_cards,
                    is_rainbow=is_rainbow,
                    facility_level=facility_level,
                ).get("failure_protection") or 0)
                for card in partner_cards
            )
            failure_rate = max(0, raw_failure_rate - int(round(failure_protection_total)))
            commands.append({
                "command_id": training_command_ids[idx],
                "command_type": 1,
                "command_group_id": 0,
                "select_id": 0,
                "current_turn": self.state["turn"],
                "current_vital": self.state["hp"],
                "training_partner_array": partners,
                "tips_event_partner_array": partners[:1] if partner_cards else [],
                "params_inc_dec_info_array": params,
                "failure_rate": failure_rate,
                "_sim_is_rainbow": is_rainbow,
                "_sim_primary_stat": stat_name,
                "_sim_partner_count": len(partner_cards),
                "_sim_raw_failure_rate": raw_failure_rate,
                "_sim_failure_protection_applied": int(round(failure_protection_total)),
                "_sim_facility_level": facility_level,
            })
        return commands

    def _race_entries_for_turn(self, turn=None):
        turn = int(turn or self.state.get("turn") or 0)
        entries = []
        for row in self.scheduled_g1s or []:
            t, pid, name, dist, era = row[:5]
            style = row[5] if len(row) > 5 else ""
            rival = bool(row[6]) if len(row) > 6 else False
            if int(t or 0) != turn:
                continue
            catalog = self.race_catalog_by_program_id.get(int(pid or 0)) or {}
            entries.append({
                "turn": int(t or 0),
                "program_id": int(pid or 0),
                "name": name or catalog.get("name") or f"Race {pid}",
                "distance": (dist or catalog.get("distance") or "").title(),
                "type": catalog.get("type") or catalog.get("grade") or "",
                "terrain": catalog.get("terrain") or "",
                "venue": catalog.get("venue") or "",
                "style": style,
                "rival": rival,
            })
        return entries

    def _race_entry_for_program(self, program_id):
        program_id = int(program_id or 0)
        for row in self.scheduled_g1s or []:
            t, pid, name, dist, era = row[:5]
            style = row[5] if len(row) > 5 else ""
            rival = bool(row[6]) if len(row) > 6 else False
            if int(pid or 0) == program_id:
                catalog = self.race_catalog_by_program_id.get(program_id) or {}
                return {
                    "turn": int(t or 0),
                    "program_id": program_id,
                    "name": name or catalog.get("name") or f"Race {program_id}",
                    "distance": (dist or catalog.get("distance") or "").title(),
                    "era": era,
                    "type": catalog.get("type") or catalog.get("grade") or "",
                    "terrain": catalog.get("terrain") or "",
                    "venue": catalog.get("venue") or "",
                    "style": style,
                    "rival": rival,
                }
        catalog = self.race_catalog_by_program_id.get(program_id) or {}
        turn = int(catalog.get("turn") or self.state.get("turn") or 0)
        return {
            "turn": turn,
            "program_id": program_id,
            "name": catalog.get("name") or f"Race {program_id}",
            "distance": (catalog.get("distance") or "Medium").title(),
            "era": _era_for_turn(turn),
            "type": catalog.get("type") or catalog.get("grade") or "",
            "terrain": catalog.get("terrain") or "",
            "venue": catalog.get("venue") or "",
            "style": "",
            "rival": self._is_rival_race(program_id),
        }

    def _stat_recreation_ready(self):
        target_bond = int(self.preset.get("stat_friend_recreation_target_bond") or 60)
        for card in self.sim_support_cards or []:
            support_id = int(card.get("support_card_id") or 0)
            if support_id not in SIM_STAT_RECREATION_FRIEND_CARDS:
                continue
            partner_id = int(card.get("partner_id") or 0)
            taken = int((self.stat_recreation_steps or {}).get(partner_id, 0))
            bond = int((self.state.get("bonds") or {}).get(partner_id, 0))
            if (
                partner_id
                and taken < FRIEND_RECREATION_DEFAULT_MAX_USES
                and (bond >= target_bond or self._sim_stat_recreation_story_unlocked(support_id, bond))
            ):
                return True
        return False

    def _make_home_commands(self, training_commands):
        commands = [dict(command) for command in (training_commands or [])]
        turn = int(self.state.get("turn") or 0)
        commands.append({
            "command_type": 7,
            "command_id": 701,
            "command_group_id": 0,
            "select_id": 0,
            "is_enable": 1,
            "current_turn": turn,
            "current_vital": self.state.get("hp", 0),
        })
        commands.append({
            "command_type": 3,
            "command_id": 301,
            "command_group_id": 301,
            "select_id": 0,
            "is_enable": 1,
            "current_turn": turn,
            "current_vital": self.state.get("hp", 0),
        })
        if self._stat_recreation_ready():
            commands.append({
                "command_type": 3,
                "command_id": 390,
                "command_group_id": 390,
                "select_id": 0,
                "is_enable": 1,
                "current_turn": turn,
                "current_vital": self.state.get("hp", 0),
            })
        commands.append({
            "command_type": 4,
            "command_id": 401,
            "command_group_id": 0,
            "select_id": 0,
            "is_enable": 1,
            "current_turn": turn,
            "current_vital": self.state.get("hp", 0),
        })
        return commands

    def _sim_race_history(self):
        history = []
        if bool(self.preset.get("sim_include_debut_history", True)):
            history.append({
                "turn": 1,
                "program_id": int(self.preset.get("sim_debut_program_id") or 0),
                "race_name": "Junior Make Debut",
                "result_rank": 1,
                "_sim_synthetic": True,
            })
        for race in self.races_run:
            history.append({
                "turn": race.get("turn"),
                "program_id": race.get("pid"),
                "race_name": race.get("name"),
                "result_rank": int(race.get("finish_rank") or (1 if race.get("won") else 2)),
            })
        return history

    def _sim_state(self, commands):
        race_conditions = self._race_entries_for_turn()
        return {
            "data": {
                "chara_info": self._chara(),
                "home_info": {"command_info_array": commands or []},
                "command_info_array": commands or [],
                "race_condition_array": race_conditions,
                "race_history": self._sim_race_history(),
                "unchecked_event_array": [],
            }
        }

    def _command_from_decision(self, commands, decision):
        payload = (decision or {}).payload if hasattr(decision, "payload") else {}
        command_type = int(payload.get("command_type") or 0)
        command_id = int(payload.get("command_id") or 0)
        command_group_id = int(payload.get("command_group_id") or 0)
        effective = command_group_id if command_type == 3 and command_group_id else command_id
        for command in commands or []:
            try:
                row_type = int(command.get("command_type") or 0)
                row_id = int(command.get("command_id") or 0)
                row_group = int(command.get("command_group_id") or 0)
            except (TypeError, ValueError):
                continue
            row_effective = row_group if row_type == 3 and row_group else row_id
            if row_type == command_type and row_effective == effective:
                return command
            if row_type == command_type and command_type == 1 and row_id == command_id:
                return command
        return {
            "command_type": command_type,
            "command_id": command_id,
            "command_group_id": command_group_id,
            "select_id": int(payload.get("select_id") or 0),
            "current_turn": self.state.get("turn", 1),
            "current_vital": self.state.get("hp", 0),
        }

    def _score_all_commands(self, commands):
        """Score every training command using the real MantStrategy scorer."""
        chara = self._chara()
        data = {"chara_info": chara}
        scored = []
        for cmd in commands:
            try:
                score = self.strategy._score_command(cmd, data, chara, self.preset)
            except Exception:
                score = 0.0
            cmd["_strategy_score"] = round(score, 4)
            scored.append((score, cmd))
        # Track bonus fires for diagnostics
        return sorted(scored, key=lambda kv: -kv[0])

    def _selected_command_bonus_values(self, cmd):
        bonuses = {}
        for key, value in (cmd or {}).items():
            if not (isinstance(key, str) and key.startswith("_") and key.endswith("_bonus")):
                continue
            try:
                numeric = float(value or 0.0)
            except (TypeError, ValueError):
                continue
            if numeric > 0:
                bonuses[key[1:]] = round(numeric, 4)
        return bonuses

    def _training_stat_gain_map(self, cmd):
        gains = {stat: 0 for stat in STAT_KEYS}
        for item in (cmd or {}).get("params_inc_dec_info_array") or []:
            target = int(item.get("target_type") or 0)
            stat = TARGET_TYPE_TO_STATE_KEY.get(target)
            if stat == "wiz":
                stat = "wit"
            if stat not in gains:
                continue
            try:
                value = int(item.get("value") or 0)
            except (TypeError, ValueError):
                value = 0
            if value > 0:
                gains[stat] += value
        return {stat: value for stat, value in gains.items() if value > 0}

    def _record_training_decision(self, cmd):
        if not cmd:
            return
        bonuses = self._selected_command_bonus_values(cmd)
        for key in bonuses:
            self.bonus_fires[key] += 1
        self.training_decisions.append({
            "turn": int(self.state.get("turn") or 0),
            "stat": cmd.get("_sim_primary_stat") or COMMAND_ID_TO_STAT.get(int(cmd.get("command_id") or 0), ""),
            "score": float(cmd.get("_strategy_score") or 0.0),
            "rank": int(cmd.get("_strategy_rank") or 0),
            "margin": float(cmd.get("_strategy_score_margin") or 0.0),
            "failure_rate": int(cmd.get("failure_rate") or 0),
            "hp": int(self.state.get("hp") or 0),
            "partners": len(cmd.get("training_partner_array") or []),
            "rainbow": bool(cmd.get("_sim_is_rainbow")),
            "gains": self._training_stat_gain_map(cmd),
            "bonuses": bonuses,
        })

    def _shop_bucket(self, turn=None):
        turn = int(turn or self.state.get("turn") or 1)
        return str(((turn - 1) // 12) * 12 + 1)

    def _inventory_count(self, item_id):
        return int((self.state.get("inventory") or {}).get(int(item_id), 0))

    def _add_item(self, item_id, count=1):
        item_id = int(item_id)
        inventory = self.state.setdefault("inventory", {})
        inventory[item_id] = min(SERVER_ITEM_INVENTORY_CAP, int(inventory.get(item_id, 0)) + int(count or 1))

    def _consume_item(self, item_id, count=1):
        item_id = int(item_id)
        inventory = self.state.setdefault("inventory", {})
        have = int(inventory.get(item_id, 0))
        if have < int(count or 1):
            return False
        remaining = have - int(count or 1)
        if remaining:
            inventory[item_id] = remaining
        else:
            inventory.pop(item_id, None)
        return True

    def _observed_item_counts(self, key):
        buckets = self.real_shop_summary.get(key) or {}
        bucket_counts = buckets.get(self._shop_bucket()) or {}
        if bucket_counts:
            return bucket_counts
        summary = self.real_shop_summary.get("item_summary") or {}
        if key.startswith("bought"):
            return {item_id: row.get("bought") or 0 for item_id, row in summary.items()}
        return {item_id: row.get("used") or 0 for item_id, row in summary.items()}

    def _sample_item_id(self, counts):
        rows = []
        for raw_id, count in (counts or {}).items():
            item_id = int(raw_id) if str(raw_id).isdigit() else 0
            weight = int(count or 0)
            if item_id and weight > 0:
                rows.append((item_id, weight))
        if not rows:
            return 0
        total = sum(weight for _, weight in rows)
        pick = self.rng.randint(1, total)
        seen = 0
        for item_id, weight in rows:
            seen += weight
            if pick <= seen:
                return item_id
        return rows[-1][0]

    def _item_cost(self, item_id):
        item_id = int(item_id)
        return int(ITEM_COST_BY_ID.get(item_id) or SHOP_ITEM_COSTS.get(ITEM_ID_TO_NAME.get(item_id, ""), 50) or 50)

    def _skip_shop_item(self, item_id):
        # The simulator has no ailments/manual bad-condition model. Buying
        # cures or Practice DVD would fake value that cannot be used.
        return int(item_id) in {4002, 4003, 4101, 4102, 4103, 4104, 4105, 4106, 4201, 2202}

    def _mant_cfg(self):
        cfg = dict((self.preset or {}).get("mant_config") or {})
        cfg.setdefault("race_heavy_route_min_races", 32)
        cfg.setdefault("race_heavy_energy_reserve_target", 140)
        cfg.setdefault("race_heavy_energy_recovery_threshold", 76)
        cfg.setdefault("race_heavy_pre_race_energy_threshold", 25)
        return cfg

    def _is_race_heavy_route(self):
        schedule = (self.preset or {}).get("custom_race_schedule") or []
        if not isinstance(schedule, list):
            return False
        try:
            target = int(self._mant_cfg().get("race_heavy_route_min_races") or 32)
        except (TypeError, ValueError):
            target = 32
        return len(schedule) >= target

    def _energy_reserve_value(self):
        return sum(
            int(self._inventory_count(item_id)) * int(value or 0)
            for item_id, value in ENERGY_ITEM_IDS.items()
        )

    def _buy_race_heavy_energy_if_needed(self):
        if not self._is_race_heavy_route() or int(self.state.get("turn") or 0) > 72:
            return False
        cfg = self._mant_cfg()
        try:
            target = int(cfg.get("race_heavy_energy_reserve_target") or 80)
        except (TypeError, ValueError):
            target = 160
        if self._energy_reserve_value() >= target:
            return False

        budget = int(self.state.get("mant_coin") or 0)
        preferred = ["Vita 65", "Vita 40", "Energy Drink MAX", "Vita 20"]
        affordable = []
        for name in preferred:
            item_id = int(DISPLAY_TO_ID.get(name) or 0)
            if not item_id or self._inventory_count(item_id) >= SERVER_ITEM_INVENTORY_CAP:
                continue
            cost = self._item_cost(item_id)
            if cost <= budget:
                affordable.append((ENERGY_ITEMS.get(name, 0), -cost, item_id, cost))
        if not affordable:
            return False
        _, _, item_id, cost = max(affordable)
        self.state["mant_coin"] = max(0, budget - cost)
        self._add_item(item_id)
        self.shop_items_bought += 1
        return True

    def _target_stat_goals(self):
        goals = {}
        for key in ("expect_attribute", "expect_attribute_minimum"):
            values = (self.preset or {}).get(key) or []
            if not isinstance(values, (list, tuple)):
                continue
            for idx, stat in enumerate(STAT_KEYS):
                if idx >= len(values):
                    continue
                try:
                    value = int(values[idx] or 0)
                except (TypeError, ValueError):
                    value = 0
                if value > goals.get(stat, 0):
                    goals[stat] = value
        return goals

    def _current_stat_value(self, stat):
        state_key = "wiz" if stat == "wit" else stat
        try:
            return int(self.state.get(state_key) or 0)
        except (TypeError, ValueError):
            return 0

    def _target_shop_item_seen_weight(self, item_id):
        summary = self.real_shop_summary.get("item_summary") or {}
        row = summary.get(str(int(item_id))) or summary.get(int(item_id)) or {}
        try:
            seen = float(row.get("shop_seen") or 0)
        except (TypeError, ValueError):
            seen = 0.0
        if seen <= 0:
            return 0.25
        # Convert "common in observed shops" into a bounded probability lift.
        return max(0.35, min(1.0, seen / 520.0))

    def _deck_count_for_stat(self, stat):
        order = list(STAT_KEYS)
        try:
            idx = order.index(stat)
        except ValueError:
            return 0
        counts = self.preset.get("_deck_type_counts") or self._deck_type_counts()
        try:
            return int(counts[idx] or 0)
        except (TypeError, ValueError, IndexError):
            return 0

    def _target_stat_shop_candidates(self):
        goals = self._target_stat_goals()
        turn = int(self.state.get("turn") or 1)
        budget = int(self.state.get("mant_coin") or 0)
        candidates = []
        if budget <= 0:
            return candidates
        priority = {"speed": 1.20, "wit": 1.20, "power": 1.05, "stamina": 0.95, "guts": 0.30}
        for stat, target in goals.items():
            if int(target or 0) < 700:
                continue
            current = self._current_stat_value(stat)
            gap = int(target) - current
            if gap <= 20:
                continue
            pressure = max(0.0, min(1.0, gap / max(1.0, float(target))))
            if stat in {"speed", "wit"} and target >= 1100:
                pressure = max(pressure, 0.25 if current < target - 70 else pressure)
            if stat == "stamina" and turn <= 56 and current < 650:
                pressure = max(pressure, 0.65)

            app_id = TARGET_STAT_APP_IDS.get(stat)
            if (
                app_id
                and turn <= int(self.preset.get("sim_target_stat_app_latest_turn") or 70)
                and self._deck_count_for_stat(stat) > 0
                and self._inventory_count(app_id) < SERVER_ITEM_INVENTORY_CAP
            ):
                boosts = self.state.get("facility_item_boosts") or {}
                if int(boosts.get(stat) or 0) < 2:
                    cost = self._item_cost(app_id)
                    if cost <= budget and (
                        (stat in {"speed", "wit"} and target >= 1100 and current < target * 0.94)
                        or (stat == "power" and target >= 900 and current < target * 0.88)
                    ):
                        score = (3.0 + pressure * 5.0) * priority.get(stat, 0.5) * self._target_shop_item_seen_weight(app_id)
                        candidates.append((score, app_id, cost, stat))

            for item_id in TARGET_STAT_ITEM_IDS.get(stat, ()):
                if self._inventory_count(item_id) >= SERVER_ITEM_INVENTORY_CAP:
                    continue
                cost = self._item_cost(item_id)
                if cost > budget:
                    continue
                _, gain = STAT_ITEM_GAINS.get(item_id, (stat, 0))
                if gain <= 0:
                    continue
                score = ((gain / max(1.0, cost)) * 10.0 + pressure * 2.0) * priority.get(stat, 0.5)
                if stat == "stamina" and turn <= 56 and current < 650:
                    score += 3.25
                elif stat == "power" and turn <= 56 and current < 650:
                    score += 0.65
                elif stat in {"speed", "wit"} and turn >= 57 and target >= 1100 and current < target:
                    score += 2.75
                score *= self._target_shop_item_seen_weight(item_id)
                if item_id in {1201, 1205} and stat in {"speed", "wit"}:
                    score += 0.35
                candidates.append((score, item_id, cost, stat))
        return sorted(candidates, key=lambda row: row[0], reverse=True)

    def _buy_target_stat_item_if_needed(self):
        if not bool(self.preset.get("sim_target_stat_shop_policy", True)):
            return False
        turn = int(self.state.get("turn") or 1)
        if turn < 13:
            return False
        base_chance = float(self.preset.get("sim_target_stat_shop_chance") or 0.72)
        if turn >= 49:
            base_chance += 0.10
        if turn in SUMMER_CAMP_TURNS:
            base_chance += 0.08
        if self.rng.random() > min(0.95, base_chance):
            return False
        try:
            max_buys = max(1, int(self.preset.get("sim_target_stat_shop_max_buys") or 2))
        except (TypeError, ValueError):
            max_buys = 2
        bought = 0
        bought_item_ids = set()
        for _ in range(max_buys):
            candidates = [
                row for row in self._target_stat_shop_candidates()
                if int(row[1] or 0) not in bought_item_ids
            ]
            if not candidates:
                break
            _, item_id, cost, _stat = candidates[0]
            item_id = int(item_id or 0)
            if cost > int(self.state.get("mant_coin") or 0):
                break
            self.state["mant_coin"] = max(0, int(self.state.get("mant_coin") or 0) - cost)
            self._add_item(item_id)
            self.shop_items_bought += 1
            bought += 1
            bought_item_ids.add(item_id)
            if item_id in STAT_ITEM_GAINS or item_id in TRAINING_APP_ITEMS:
                self._use_item(item_id)
        return bought > 0

    def _maybe_buy_shop_items(self):
        if not bool(self.preset.get("sim_use_shop_items", True)):
            return
        turn = int(self.state.get("turn") or 1)
        if turn < 13 or int(self.state.get("mant_coin") or 0) < 10:
            return
        bought = 0
        if self._buy_race_heavy_energy_if_needed():
            bought += 1
        if self._buy_target_stat_item_if_needed():
            bought += 1
        chance = float(self.preset.get("sim_shop_buy_chance") or 0.42)
        if turn in SUMMER_CAMP_TURNS:
            chance += 0.18
        if turn >= 49:
            chance += 0.08
        max_buys = 2 if (turn in SUMMER_CAMP_TURNS or turn >= 49) else 1
        counts = self._observed_item_counts("bought_by_turn_bucket")
        for _ in range(max_buys):
            if self.rng.random() > chance:
                continue
            item_id = 0
            for _attempt in range(20):
                candidate = self._sample_item_id(counts)
                if not candidate or self._skip_shop_item(candidate):
                    continue
                if self._inventory_count(candidate) >= SERVER_ITEM_INVENTORY_CAP:
                    continue
                cost = self._item_cost(candidate)
                if cost <= int(self.state.get("mant_coin") or 0):
                    item_id = candidate
                    break
            if not item_id:
                continue
            self.state["mant_coin"] = max(0, int(self.state.get("mant_coin") or 0) - self._item_cost(item_id))
            self._add_item(item_id)
            self.shop_items_bought += 1
            bought += 1
            if item_id in STAT_ITEM_GAINS or item_id in TRAINING_APP_ITEMS:
                self._use_item(item_id)
            elif item_id in MOOD_ITEM_GAINS and int(self.state.get("motivation") or 3) < 5:
                self._use_item(item_id)
        return bought

    def _use_item(self, item_id, *, target_stat=None):
        item_id = int(item_id)
        if not self._consume_item(item_id):
            return False
        turn = int(self.state.get("turn") or 1)
        if item_id in STAT_ITEM_GAINS:
            state_key, value = STAT_ITEM_GAINS[item_id]
            scale = float(self.preset.get("sim_shop_stat_item_scale") or 1.0)
            self.state[state_key] = min(STAT_CAP, int(self.state.get(state_key) or 0) + int(round(value * scale)))
        elif item_id in TRAINING_APP_ITEMS:
            stat = TRAINING_APP_ITEMS[item_id]
            boosts = self.state.setdefault("facility_item_boosts", {s: 0 for s in STAT_KEYS})
            boosts[stat] = min(2, int(boosts.get(stat, 0)) + 1)
        elif item_id in ENERGY_ITEM_IDS:
            self.state["hp"] = min(int(self.state.get("max_hp") or 100), int(self.state.get("hp") or 0) + ENERGY_ITEM_IDS[item_id])
        elif item_id in MOOD_ITEM_GAINS:
            self.state["motivation"] = min(5, int(self.state.get("motivation") or 3) + MOOD_ITEM_GAINS[item_id])
        elif item_id in MEGAPHONE_ITEM_IDS:
            tier, duration = MEGAPHONE_ITEM_IDS[item_id]
            multiplier = {1: 1.15, 2: 1.30, 3: 1.45}.get(int(tier), 1.20)
            self.state.setdefault("active_item_effects", []).append({
                "item_id": item_id,
                "kind": "training_mult",
                "multiplier": multiplier,
                "end_turn": turn + max(1, int(duration)) - 1,
            })
        elif item_id in ANKLE_WEIGHT_ITEMS:
            self.state.setdefault("active_item_effects", []).append({
                "item_id": item_id,
                "kind": "ankle",
                "stat": target_stat or ANKLE_WEIGHT_ITEMS[item_id],
                "flat": 14,
                "hp_cost": 5,
                "end_turn": turn,
            })
        elif item_id == 10001:
            self.state.setdefault("active_item_effects", []).append({
                "item_id": item_id,
                "kind": "good_luck",
                "end_turn": turn,
            })
        else:
            # Hammers/glow sticks are consumed by race reward logic.
            self._add_item(item_id)
            return False
        self.shop_items_used += 1
        return True

    def _expire_item_effects(self):
        turn = int(self.state.get("turn") or 1)
        effects = []
        for effect in self.state.get("active_item_effects") or []:
            if int(effect.get("end_turn") or 0) >= turn:
                effects.append(effect)
        self.state["active_item_effects"] = effects

    def _active_training_multiplier(self):
        mult = 1.0
        for effect in self.state.get("active_item_effects") or []:
            if effect.get("kind") == "training_mult":
                mult = max(mult, float(effect.get("multiplier") or 1.0))
        return mult

    def _active_training_flat_bonus(self, state_key):
        stat = STATE_TO_STAT_KEY.get(state_key, state_key)
        total = 0
        for effect in self.state.get("active_item_effects") or []:
            if effect.get("kind") == "ankle" and effect.get("stat") == stat:
                total += int(effect.get("flat") or 0)
        return total

    def _active_training_extra_hp_cost(self):
        return sum(
            int(effect.get("hp_cost") or 0)
            for effect in self.state.get("active_item_effects") or []
            if effect.get("kind") == "ankle"
        )

    def _maybe_use_recovery_items(self):
        if not bool(self.preset.get("sim_use_shop_items", True)):
            return
        hp = int(self.state.get("hp") or 0)
        threshold = 45
        if self._is_race_heavy_route():
            try:
                threshold = max(threshold, int(self._mant_cfg().get("race_heavy_energy_recovery_threshold") or threshold))
            except (TypeError, ValueError):
                threshold = max(threshold, 76)
        if hp <= threshold:
            options = [
                (abs((int(self.state.get("max_hp") or 100) - hp) - value), item_id, value)
                for item_id, value in ENERGY_ITEM_IDS.items()
                if self._inventory_count(item_id) > 0
            ]
            if options:
                _, item_id, _ = min(options)
                self._use_item(item_id)
        if int(self.state.get("motivation") or 3) <= 3:
            options = [
                (MOOD_ITEM_GAINS[item_id], item_id)
                for item_id in MOOD_ITEM_GAINS
                if self._inventory_count(item_id) > 0
            ]
            if options:
                _, item_id = max(options)
                self._use_item(item_id)

    def _maybe_use_pre_race_energy(self):
        if not bool(self.preset.get("sim_use_shop_items", True)) or not self._is_race_heavy_route():
            return
        try:
            threshold = int(self._mant_cfg().get("race_heavy_pre_race_energy_threshold") or 25)
        except (TypeError, ValueError):
            threshold = 25
        if int(self.state.get("hp") or 0) > threshold:
            return
        options = [
            (value, item_id)
            for item_id, value in ENERGY_ITEM_IDS.items()
            if self._inventory_count(item_id) > 0
        ]
        if not options:
            return
        _, item_id = max(options)
        self._use_item(item_id)

    def _maybe_use_training_items(self, cmd, score):
        if not bool(self.preset.get("sim_use_shop_items", True)) or not cmd:
            return
        turn = int(self.state.get("turn") or 1)
        stat = cmd.get("_sim_primary_stat") or COMMAND_ID_TO_STAT.get(int(cmd.get("command_id") or 0), "")
        strong_tile = (
            bool(cmd.get("_sim_is_rainbow"))
            or int(cmd.get("_sim_partner_count") or 0) >= 2
            or turn in SUMMER_CAMP_TURNS
            or float(score or 0.0) >= 1.0
        )
        has_training_mult = any(effect.get("kind") == "training_mult" for effect in self.state.get("active_item_effects") or [])
        if strong_tile and not has_training_mult:
            available = [
                (MEGAPHONE_ITEM_IDS[item_id][0], item_id)
                for item_id in MEGAPHONE_ITEM_IDS
                if self._inventory_count(item_id) > 0
            ]
            if available:
                if turn in SUMMER_CAMP_TURNS or turn >= 61:
                    _, item_id = max(available)
                else:
                    _, item_id = min(available, key=lambda row: abs(row[0] - 2))
                self._use_item(item_id)
        if strong_tile and stat in ANKLE_WEIGHT_ITEMS.values():
            item_id = next((iid for iid, s in ANKLE_WEIGHT_ITEMS.items() if s == stat and self._inventory_count(iid) > 0), 0)
            if item_id:
                self._use_item(item_id, target_stat=stat)
        if int(cmd.get("failure_rate") or 0) >= 9 and self._inventory_count(10001) > 0:
            self._use_item(10001)

    def _consume_good_luck_if_needed(self, failure_rate):
        if int(failure_rate or 0) < 5:
            return False
        for effect in list(self.state.get("active_item_effects") or []):
            if effect.get("kind") == "good_luck":
                self.state["active_item_effects"].remove(effect)
                return True
        return False

    def _is_rival_race(self, pid, explicit=False):
        return bool(explicit) or int(pid or 0) in self.rival_program_ids

    def _deck_race_bonus_multiplier(self):
        deck_race_bonus = sum(
            float(self._effective_card_effects(card).get("race_bonus") or 0)
            for card in (self.sim_support_cards or [])
        )
        return 1.0 + deck_race_bonus / 100.0

    def _training_command_sp_value(self, cmd):
        total = 0
        for row in (cmd or {}).get("params_inc_dec_info_array") or []:
            try:
                target_type = int(row.get("target_type") or 0)
                value = int(row.get("value") or 0)
            except (TypeError, ValueError):
                continue
            if target_type == 30 and value > 0:
                total += value
        return total

    def _expected_training_sp_per_action(self):
        values = []
        exact_values = []
        current_ids = set(getattr(self, "_current_support_ids", set()) or set())
        for snapshot in self.real_training_snapshots or []:
            snap_values = [
                self._training_command_sp_value(cmd)
                for cmd in snapshot.get("commands") or []
                if isinstance(cmd, dict) and int(cmd.get("is_enable", 1) or 0)
            ]
            snap_values = [value for value in snap_values if value > 0]
            values.extend(snap_values)
            if current_ids and self._snapshot_support_ids(snapshot) == current_ids:
                exact_values.extend(snap_values)
        source_values = exact_values if len(exact_values) >= 30 else values
        if source_values:
            return float(median(source_values))
        return 3.0

    def _expected_event_sp_per_fire(self):
        values = []
        for template in self.event_effect_templates or []:
            best = 0.0
            for choice in template.get("choices") or []:
                try:
                    best = max(best, float((choice.get("effects") or {}).get("Skill Pts") or 0))
                except (TypeError, ValueError):
                    continue
            values.append(best)
        if values:
            return sum(values) / max(1, len(values))
        return 0.0

    def _expected_event_fire_count(self):
        override = self.preset.get("sim_expected_event_fire_count")
        if override is not None:
            try:
                return max(0.0, float(override))
            except (TypeError, ValueError):
                pass
        total = 0.0
        for turn in range(1, TURN_FINISH + 1):
            if turn <= 24:
                probability = 0.86
            elif turn <= 48:
                probability = 0.78
            elif turn <= 72:
                probability = 0.68
            else:
                probability = 0.58
            total += probability
        return max(0.0, min(float(TURN_FINISH), total))

    def _expected_nonrace_sp_budget(self):
        override = self.preset.get("sim_expected_nonrace_sp_budget")
        if override is not None:
            try:
                return max(0.0, float(override))
            except (TypeError, ValueError):
                pass

        initial_sp = float(self.state.get("skill_point") or 0)
        race_count = len(self.scheduled_g1s or [])
        try:
            nonrace_actions = int(self.preset.get("sim_expected_nonrace_action_count") or (TURN_FINISH - race_count))
        except (TypeError, ValueError):
            nonrace_actions = TURN_FINISH - race_count
        nonrace_actions = max(0, nonrace_actions)
        training_sp = self._expected_training_sp_per_action() * nonrace_actions

        event_sp = 0.0
        if bool(self.preset.get("sim_use_turn_events", True)):
            event_count = self._expected_event_fire_count()
            event_sp = self._expected_event_sp_per_fire() * max(0.0, event_count)

        # Parent inheritance usually contributes a tiny amount of SP compared
        # with races/events. Keep it explicit so the SP budget is auditable.
        inheritance_sp = 4.0 if bool(self.preset.get("sim_use_parent_inheritance", True)) else 0.0
        climax_sp = self._expected_climax_sp_budget()
        return max(0.0, initial_sp + training_sp + event_sp + inheritance_sp + climax_sp)

    def _race_sp_grade_key(self, pid=0, race_name="", grade="", turn=None):
        try:
            pid = int(pid or 0)
        except (TypeError, ValueError):
            pid = 0
        turn = int(turn if turn is not None else (self.state.get("turn") or 0) or 0)
        name = str(race_name or "").lower()
        if "twinkle star climax" in name or pid in {2315, 2410, 2412, 2513} or turn in getattr(self, "_climax_turn_set", set()):
            return "climax"
        return "g1" if str(grade or "").upper() == "G1" else "other"

    def _race_reward_grade_key(self, grade):
        grade_key = str(grade or "").upper().replace("_", "-").strip()
        if grade_key in {"PREOP", "PRE-OP", "PRE OP"}:
            return "PRE-OP"
        if grade_key in {"OP", "OPEN"}:
            return "OP"
        if grade_key in {"G3", "GIII"}:
            return "G3"
        if grade_key in {"G2", "GII"}:
            return "G2"
        if grade_key in {"G1", "GI"}:
            return "G1"
        return grade_key

    def _race_base_reward(self, grade):
        return RACE_GRADE_REWARDS.get(self._race_reward_grade_key(grade), {})

    def _empirical_race_sp_reward_by_grade(self):
        calibration = getattr(self, "sp_budget_calibration", {}) or {}
        rewards = calibration.get("race_sp_reward_by_grade") or {}
        if not calibration.get("enabled") or not isinstance(rewards, dict):
            return {}
        return rewards

    def _race_sp_reward_value(self, *, grade, won, pid=0, race_name="", turn=None, rival=False, reward_multiplier=1.0, race_bonus_mult=1.0):
        """Return in-game race SP: grade base reward scaled by race bonus."""
        grade_key = self._race_sp_grade_key(pid=pid, race_name=race_name, grade=grade, turn=turn)
        if grade_key == "climax":
            # Climax SP is handled by _apply_climax_race_reward so that the
            # event entry remains visible and scales with the active hammer.
            return 0

        base = _as_int((self._race_base_reward(grade) or {}).get("skill_point"))
        if base <= 0:
            return 0
        if not won:
            base = int(base * 0.45)
        value = float(base) * max(0.0, float(race_bonus_mult or 1.0))
        if float(reward_multiplier or 1.0) > 1.0:
            value *= max(1.0, float(reward_multiplier or 1.0))
        return max(0, int(value))

    def _expected_race_reward_multiplier_for_budget(self, *, grade, turn=0, rival=False, race_name="", pid=0):
        if not bool(self.preset.get("sim_use_shop_items", True)):
            return 1.0
        grade_key = self._race_sp_grade_key(pid=pid, race_name=race_name, grade=grade, turn=turn)
        if grade_key == "climax":
            return 1.25
        if int(turn or 0) >= 60 or str(grade or "").upper() == "G1":
            return 1.05
        if rival:
            return 1.03
        return 1.0

    def _expected_climax_sp_budget(self):
        if not getattr(self, "_final_climax_races", None):
            return 0.0
        race_bonus_mult = self._deck_race_bonus_multiplier()
        return sum(
            int(30 * max(0.0, float(race_bonus_mult or 1.0)) * self._expected_race_reward_multiplier_for_budget(
                grade="",
                turn=turn,
                race_name=race[1],
                pid=race[0],
            ))
            for turn, race in self._final_climax_races.items()
        )

    def _expected_unscaled_race_sp_budget(self):
        rows = list(self.scheduled_g1s or [])
        if not rows:
            return 0.0
        calibration = getattr(self, "sp_budget_calibration", {}) or {}
        try:
            win_rate = float(calibration.get("race_win_rate_target") if calibration.get("race_win_rate_target") is not None else 0.85)
        except (TypeError, ValueError):
            win_rate = 0.85
        win_rate = max(0.0, min(1.0, win_rate))
        race_bonus_mult = self._deck_race_bonus_multiplier()
        total = 0.0
        for row in rows:
            try:
                pid = int(row[1] or 0)
            except (TypeError, ValueError, IndexError):
                pid = 0
            rival = bool(row[6]) if len(row) > 6 else False
            if pid:
                rival = self._is_rival_race(pid, explicit=rival)
            name = row[2] if len(row) > 2 else ""
            distance = row[3] if len(row) > 3 else ""
            turn = _as_int(row[0] if row else 0)
            catalog = self.race_catalog_by_program_id.get(pid) or {}
            grade = catalog.get("type") or catalog.get("grade") or "G1"
            reward_multiplier = self._expected_race_reward_multiplier_for_budget(
                grade=grade,
                turn=turn,
                rival=rival,
                race_name=name,
                pid=pid,
            )
            reward_win = self._race_sp_reward_value(
                grade=grade,
                won=True,
                pid=pid,
                race_name=name or distance,
                turn=turn,
                rival=rival,
                reward_multiplier=reward_multiplier,
                race_bonus_mult=race_bonus_mult,
            )
            reward_loss = self._race_sp_reward_value(
                grade=grade,
                won=False,
                pid=pid,
                race_name=name or distance,
                turn=turn,
                rival=rival,
                reward_multiplier=reward_multiplier,
                race_bonus_mult=race_bonus_mult,
            )
            reward = (float(reward_win) * win_rate) + (float(reward_loss) * (1.0 - win_rate))
            total += reward
        return max(0.0, total)

    def _calibrated_race_sp_reward_scale(self):
        override = self.preset.get("sim_race_sp_reward_scale")
        if override is not None:
            try:
                return max(0.0, float(override))
            except (TypeError, ValueError):
                pass
        calibration = getattr(self, "sp_budget_calibration", {}) or {}
        if not calibration.get("enabled"):
            return 1.0
        target_total = float(calibration.get("total_sp_budget_target") or 0)
        expected_nonrace = self._expected_nonrace_sp_budget()
        expected_race = self._expected_unscaled_race_sp_budget()
        calibration["expected_nonrace_sp_budget"] = int(round(expected_nonrace))
        calibration["expected_unscaled_race_sp_budget"] = int(round(expected_race))
        calibration["race_sp_reward_scale_reason"] = "using_exact_grade_race_sp_formula"
        calibration["target_race_sp_budget"] = int(round(max(0.0, target_total - expected_nonrace)))
        calibration["raw_race_sp_reward_scale"] = 1.0
        calibration["race_sp_reward_scale"] = 1.0
        return 1.0

    def _expected_raw_training_sp_budget(self):
        race_count = len(self.scheduled_g1s or [])
        try:
            nonrace_actions = int(self.preset.get("sim_expected_nonrace_action_count") or (TURN_FINISH - race_count))
        except (TypeError, ValueError):
            nonrace_actions = TURN_FINISH - race_count
        return self._expected_training_sp_per_action() * max(0, nonrace_actions)

    def _expected_raw_event_sp_budget(self):
        if not bool(self.preset.get("sim_use_turn_events", True)):
            return 0.0
        return self._expected_event_sp_per_fire() * max(0.0, self._expected_event_fire_count())

    def _calibrated_nonrace_sp_reward_scale(self):
        return 1.0

    def _calibrated_event_sp_reward_scale(self):
        override = self.preset.get("sim_event_sp_reward_scale")
        if override is not None:
            try:
                return max(0.0, float(override))
            except (TypeError, ValueError):
                pass
        override = self.preset.get("sim_nonrace_sp_reward_scale")
        if override is not None:
            try:
                scale = max(0.0, float(override))
                calibration = getattr(self, "sp_budget_calibration", {}) or {}
                calibration["event_sp_reward_scale"] = round(scale, 4)
                calibration["event_sp_reward_scale_reason"] = "legacy_sim_nonrace_sp_reward_scale_applies_to_events_only"
                return scale
            except (TypeError, ValueError):
                pass
        calibration = getattr(self, "sp_budget_calibration", {}) or {}
        initial_sp = float(self.state.get("skill_point") or 0)
        inheritance_sp = 4.0 if bool(self.preset.get("sim_use_parent_inheritance", True)) else 0.0
        expected_climax = self._expected_climax_sp_budget()
        raw_events = self._expected_raw_event_sp_budget()
        calibration["expected_initial_sp_budget"] = int(round(initial_sp))
        calibration["expected_climax_sp_budget"] = int(round(expected_climax))
        calibration["expected_raw_training_sp_budget"] = int(round(self._expected_raw_training_sp_budget()))
        calibration["expected_raw_event_sp_budget"] = int(round(raw_events))
        calibration["event_sp_reward_scale"] = 1.0
        calibration["event_sp_reward_scale_reason"] = "event_sp_uses_observed_event_deltas_training_sp_uses_facility_table"
        calibration["nonrace_sp_reward_scale"] = 1.0
        return 1.0

    def _apply_epithet_bonuses_if_completed(self, reward_multiplier):
        """Grant +10/+15 to 2 random stats when a MANT epithet set completes.

        Per uma.guide/trackblazer: epithet routes (Lady/Stunning/etc) grant
        +10 to 2 random stats; chained routes (Heroine/Goddess/Incredible/
        Phenomenal/Breakneck Miler/Sprint Speedster/Sprint Go-Getter) grant
        +15 to 2 random stats. The race-bonus multiplier from shop items
        does NOT apply to epithet rewards (it only applies to race stat
        rewards); the bonus is a fixed scenario event.
        """
        completed_names = {e["name"] for e in self.epithets_completed}
        for ep in MANT_EPITHET_SETS:
            if ep["name"] in completed_names:
                continue
            # `prereq` (optional): a base race set that must all be matched
            # before considering the `races` set. Used by Phenomenal which
            # needs Stunning completed AND 2 of 5 majors.
            prereq = ep.get("prereq")
            if prereq and not prereq.issubset(self.race_names_won):
                continue
            # `min_match` (optional): when present, fire when at least
            # min_match of `races` are matched (the "any K of N" model
            # used by Phenomenal and Sprint Speedster). Without min_match,
            # behavior is the original `issubset` (all races must match).
            min_match = ep.get("min_match")
            if min_match is None:
                if not ep["races"].issubset(self.race_names_won):
                    continue
            else:
                if len(ep["races"] & self.race_names_won) < int(min_match):
                    continue
            # Roll 2 distinct random stats and grant the bonus.
            gain = int(ep["bonus"])
            stats = list(EPITHET_STAT_KEYS)
            self.rng.shuffle(stats)
            picked = stats[:2]
            for stat_key in picked:
                self.state[stat_key] = min(STAT_CAP, int(self.state.get(stat_key) or 0) + gain)
            self.epithets_completed.append({
                "name": ep["name"],
                "bonus": gain,
                "stats": list(picked),
                "turn": int(self.state.get("turn") or 0),
            })

    def _race_reward_multiplier(self, grade, rival=False):
        self._last_race_reward_item_id = None
        if not bool(self.preset.get("sim_use_shop_items", True)):
            return 1.0
        grade = str(grade or "").upper()
        priority = []
        if grade == "G1" or int(self.state.get("turn") or 0) >= 60:
            priority = [11002, 11001, 11003]
        elif rival:
            priority = [11001, 11003]
        else:
            priority = [11003]
        for item_id in priority:
            if self._inventory_count(item_id) > 0 and self._consume_item(item_id):
                self.shop_items_used += 1
                self._last_race_reward_item_id = int(item_id)
                return float(RACE_REWARD_BUFF_ITEMS.get(item_id, 1.0))
        return 1.0

    def _apply_climax_race_reward(self, turn):
        row = CLIMAX_RACE_REWARD_BY_TURN.get(int(turn or 0))
        if not row:
            return None
        story_id, event_id = row
        if story_id in self._seen_event_story_ids:
            return None

        support_scaled_stat = int(10 * max(0.0, float(self._deck_race_bonus_multiplier() or 1.0)))
        support_scaled_sp = int(30 * max(0.0, float(self._deck_race_bonus_multiplier() or 1.0)))
        item_id = int(getattr(self, "_last_race_reward_item_id", None) or 0)
        item_multiplier = float(CLIMAX_RACE_REWARD_ITEM_MULTIPLIERS.get(item_id, 1.0))
        stat_gain = max(0, int(support_scaled_stat * item_multiplier))
        sp_gain = max(0, int(support_scaled_sp * item_multiplier))

        for stat_key in EPITHET_STAT_KEYS:
            self.state[stat_key] = min(STAT_CAP, int(self.state.get(stat_key) or 0) + stat_gain)
        self.state["skill_point"] += sp_gain
        self.sp_gain_sources["climax"] += sp_gain
        self.climax_bonus_races += 1
        self._seen_event_story_ids.add(story_id)

        record = {
            "turn": int(turn or 0),
            "source": "scenario",
            "source_id": 4,
            "story_id": story_id,
            "event_id": event_id,
            "event_name": f"Twinkle Star Climax Race {1 + max(0, (int(turn or 0) - 74) // 2)} Reward",
            "source_exact": True,
            "action": "climax_race_reward",
            "choice": "race_bonus_scaled",
            "observed_effect_delta": False,
            "stat_gain": stat_gain * len(EPITHET_STAT_KEYS),
            "sp_gain": sp_gain,
            "bond_gain": 0,
            "motivation_gain": 0,
            "hp_gain": 0,
            "max_hp_gain": 0,
            "skill_hint_gain": 0,
            "race_bonus_multiplier": round(float(self._deck_race_bonus_multiplier() or 1.0), 4),
            "race_reward_item_id": item_id or None,
            "item_multiplier": round(item_multiplier, 4),
        }
        self.events_fired.append(record)
        return record

    def _race_coin_reward(self, grade, won, rival=False, reward_multiplier=1.0):
        grade = str(grade or "").upper()
        base = {"G1": 95, "G2": 75, "G3": 60, "OP": 45, "PRE-OP": 35}.get(grade, 50)
        if not won:
            base = int(round(base * 0.45))
        if rival:
            base += 30 if won else 15
        return max(0, int(round(base * max(0.8, float(reward_multiplier or 1.0)))))

    def _race_fan_reward(self, grade, won):
        grade = str(grade or "").upper()
        base = {"G1": 10000, "G2": 5200, "G3": 3200, "OP": 1200, "PRE-OP": 500}.get(grade, 1000)
        if not won:
            base = int(round(base * 0.35))
        deck_fan_bonus = sum(
            float(self._effective_card_effects(card).get("fan_bonus") or 0)
            for card in (self.sim_support_cards or [])
        )
        return int(round(base * (1.0 + deck_fan_bonus / 100.0)))

    def _race_stat_distribution(self, era):
        calibration = getattr(self, "race_stat_gain_calibration", {}) or {}
        if calibration.get("enabled"):
            by_era = calibration.get("by_era") or {}
            era_key = str(era or "").lower()
            if int(self.state.get("turn") or 0) >= 73 and by_era.get("climax"):
                return by_era["climax"].get("distribution") or calibration.get("distribution") or {}
            if by_era.get(era_key):
                return by_era[era_key].get("distribution") or calibration.get("distribution") or {}
            return calibration.get("distribution") or {}
        return {stat: 1.0 / len(STAT_KEYS) for stat in STAT_KEYS}

    def _race_stat_total_gain(self, *, won, era, grade="", reward_multiplier=1.0, race_bonus_mult=1.0, rival=False):
        if not won:
            return 0
        if int(self.state.get("turn") or 0) in getattr(self, "_climax_turn_set", set()):
            return 0
        base = _as_int((self._race_base_reward(grade) or {}).get("stat"))
        if base <= 0:
            return 0
        value = float(base) * max(0.0, float(race_bonus_mult or 1.0))
        if float(reward_multiplier or 1.0) > 1.0:
            value *= max(1.0, float(reward_multiplier or 1.0))
        return max(0, int(round(value)))

    def _apply_random_race_stat_gain(self, stat_gain):
        stat_gain = max(0, int(stat_gain or 0))
        if stat_gain <= 0:
            return {}
        stat = self.rng.choice(STAT_KEYS)
        state_key = "wiz" if stat == "wit" else stat
        self.state[state_key] = min(STAT_CAP, int(self.state.get(state_key) or 0) + stat_gain)
        return {stat: stat_gain}

    def _apply_distributed_race_stat_gain(self, total_gain, era):
        total_gain = max(0, int(total_gain or 0))
        if total_gain <= 0:
            return {}
        raw_dist = self._race_stat_distribution(era)
        weights = {}
        total_weight = 0.0
        for stat in STAT_KEYS:
            weight = max(0.0, float((raw_dist or {}).get(stat) or 0.0))
            weights[stat] = weight
            total_weight += weight
        if total_weight <= 0:
            weights = {stat: 1.0 for stat in STAT_KEYS}
            total_weight = float(len(STAT_KEYS))

        allocations = {}
        remainders = []
        allocated = 0
        for stat in STAT_KEYS:
            exact = total_gain * (weights[stat] / total_weight)
            value = int(exact)
            allocations[stat] = value
            allocated += value
            remainders.append((exact - value, stat))
        for _remainder, stat in sorted(remainders, reverse=True)[:max(0, total_gain - allocated)]:
            allocations[stat] += 1

        for stat, value in allocations.items():
            state_key = "wiz" if stat == "wit" else stat
            self.state[state_key] = min(STAT_CAP, int(self.state.get(state_key) or 0) + int(value or 0))
        return allocations

    def _apply_inheritance_event(self):
        if not bool(self.preset.get("sim_use_parent_inheritance", True)):
            return
        factors = (self.legacy_effects or {}).get("inheritance_event_factors") or []
        if not factors:
            return
        # The local knowledge file stores baseline per-factor proc rates.
        # Compatibility is unknown in the simulator, so use a conservative
        # double-circle-ish multiplier without making every white deterministic.
        compat_mult = float(self.preset.get("sim_inheritance_compat_mult") or 1.35)
        applied = 0
        for factor in factors:
            stars = max(1, min(3, int(factor.get("stars") or 1)))
            category = str(factor.get("category") or "")
            if category == "scenario":
                base_rate = {1: 0.03, 2: 0.06, 3: 0.09}[stars]
                stat_unit = 6
            else:
                base_rate = {1: 0.01, 2: 0.02, 3: 0.03}[stars]
                stat_unit = 4
            if self.rng.random() > min(0.45, base_rate * compat_mult):
                continue
            for stat_key, weight in (factor.get("stat_effects") or {}).items():
                if stat_key in self.state:
                    self.state[stat_key] = min(STAT_CAP, int(self.state.get(stat_key) or 0) + stat_unit * int(weight or 1))
            applied += 1
        if applied:
            sp_gain = applied * 2
            self.state["skill_point"] += sp_gain
            self.sp_gain_sources["inheritance"] += sp_gain

    def _observed_effect_delta_to_choice_effects(self, delta):
        effects = {}
        for raw_key, effect_key in OBSERVED_DELTA_TO_EVENT_EFFECT_KEY.items():
            try:
                value = float((delta or {}).get(raw_key) or 0)
            except (TypeError, ValueError):
                continue
            if value:
                effects[effect_key] = value
        return effects

    def _observed_event_profile_matches_context(self, profile):
        source = str((profile or {}).get("source") or "")
        source_id = int((profile or {}).get("source_id") or 0)
        if source == "scenario":
            expected = int(self.preset.get("scenario_id") or 4)
            return source_id in {0, expected}
        if source == "chara":
            return source_id in {0, int(self.trainee_card_id or 0)}
        if source == "support_card":
            support_id = int((profile or {}).get("support_card_id") or source_id or 0)
            return bool(support_id and support_id in (self._current_support_ids or set()))
        return False

    def _build_observed_fixed_event_schedule(self):
        if not bool(self.preset.get("sim_use_observed_fixed_events", True)):
            return self._build_static_mant_fixed_event_schedule({})
        rows = []
        if isinstance(self.runtime_event_summary, dict):
            rows = list(self.runtime_event_summary.get("fixed_turn_events") or [])
        if not rows:
            return self._build_static_mant_fixed_event_schedule({})
        allowed_raw = self.preset.get("sim_observed_fixed_event_sources")
        if allowed_raw is None:
            allowed = {"scenario", "chara"}
        elif isinstance(allowed_raw, str):
            allowed = {part.strip() for part in allowed_raw.split(",") if part.strip()}
        else:
            allowed = {str(part).strip() for part in allowed_raw or [] if str(part).strip()}

        by_turn = defaultdict(list)
        for profile in rows:
            if not isinstance(profile, dict):
                continue
            source = str(profile.get("source") or "")
            if source not in allowed:
                continue
            if not self._observed_event_profile_matches_context(profile):
                continue
            turn = int(profile.get("top_turn") or 0)
            if turn <= 0 or turn > TURN_FINISH:
                continue
            kind = str(profile.get("event_kind") or "")
            if kind in {"race_win_recurring", "race_loss_or_place_recurring", "inheritance_inspiration", "guest_event", "unknown"}:
                continue
            effects = self._observed_effect_delta_to_choice_effects(profile.get("effect_medians") or {})
            if turn == 1 and set(effects) == {"Skill Pts"}:
                # The simulator starts from the post-start observed SP pool;
                # replaying the turn-1 startup skill-point event would double
                # count the same initial grant.
                continue
            template = {
                "event_name": profile.get("event_name") or "",
                "story_id": str(profile.get("story_id") or ""),
                "source_exact": True,
                "observed_effect_delta": True,
                "choices": [{
                    "choice": "observed_median",
                    "label": "observed median effect",
                    "effects": effects,
                }],
            }
            source_info = {
                "source": source or "scenario",
                "source_id": int(profile.get("source_id") or 0),
                "action": "fixed_observed_event",
                "observed_profile": {
                    "count": int(profile.get("count") or 0),
                    "top_turn_share": float(profile.get("top_turn_share") or 0.0),
                    "event_kind": kind,
                },
            }
            if source == "support_card":
                support_id = int(profile.get("support_card_id") or profile.get("source_id") or 0)
                card = next((card for card in self.sim_support_cards if int(card.get("support_card_id") or 0) == support_id), {})
                source_info["card"] = card
            by_turn[turn].append({
                "profile": profile,
                "template": template,
                "choice": template["choices"][0],
                "source_info": source_info,
            })
        for turn in by_turn:
            by_turn[turn].sort(key=lambda row: (row["source_info"].get("source") or "", (row["template"].get("story_id") or "")))
        return self._build_static_mant_fixed_event_schedule(dict(by_turn))

    def _build_static_mant_fixed_event_schedule(self, by_turn):
        if not bool(self.preset.get("sim_use_static_mant_fixed_events", True)):
            return dict(by_turn or {})
        scenario_id = (
            self.preset.get("scenario_id")
            or (self.preset.get("_run_context") or {}).get("scenario_id")
            or 4
        )
        try:
            scenario_id = int(scenario_id or 0)
        except (TypeError, ValueError):
            scenario_id = 4
        if scenario_id != 4:
            return dict(by_turn or {})

        merged = {int(turn): list(rows or []) for turn, rows in (by_turn or {}).items()}
        seen_story_ids = {
            str((row.get("template") or {}).get("story_id") or "")
            for rows in merged.values()
            for row in rows
        }
        for event in MANT_STATIC_FIXED_EVENTS:
            story_id = str(event.get("story_id") or "")
            if story_id and story_id in seen_story_ids:
                continue
            turn = int(event.get("turn") or 0)
            if turn <= 0 or turn > TURN_FINISH:
                continue
            effects = dict(event.get("effects") or {})
            template = {
                "event_name": event.get("event_name") or "",
                "story_id": story_id,
                "source_exact": True,
                "static_mant_event": True,
                "choices": [{
                    "choice": "static_mant",
                    "label": "static MANT fixed effect",
                    "effects": effects,
                }],
            }
            source_info = {
                "source": "scenario",
                "source_id": 4,
                "action": "fixed_mant_event",
                "static_mant_event": True,
                "observed_profile": {
                    "count": 0,
                    "top_turn_share": 1.0,
                    "event_kind": "scenario_event",
                },
            }
            merged.setdefault(turn, []).append({
                "profile": {
                    "story_id": story_id,
                    "event_id": int(event.get("event_id") or 0),
                    "source": "scenario",
                    "source_id": "4",
                    "event_kind": "scenario_event",
                    "effect_medians": effects,
                },
                "template": template,
                "choice": template["choices"][0],
                "source_info": source_info,
            })
            if story_id:
                seen_story_ids.add(story_id)
        for turn in merged:
            merged[turn].sort(key=lambda row: (
                row["source_info"].get("source") or "",
                row["template"].get("story_id") or "",
            ))
        return dict(merged)

    def _simulate_observed_fixed_events_for_turn(self):
        turn = int(self.state.get("turn") or 0)
        rows = self._observed_fixed_events_by_turn.get(turn) or []
        fired = []
        for row in rows:
            story_id = str((row.get("template") or {}).get("story_id") or "")
            if story_id in CLIMAX_RACE_REWARD_STORY_IDS:
                # These fire after the Climax race and scale with race bonus /
                # hammer effects. Applying them at turn-start would lock them
                # to one observed deck and miss the active race reward item.
                continue
            key = (turn, story_id or str(id(row)))
            if key in self._fired_observed_fixed_events:
                continue
            if story_id and story_id in self._seen_event_story_ids:
                continue
            self._fired_observed_fixed_events.add(key)
            record = self._apply_sim_event_effects(
                row.get("source_info") or {},
                row.get("template") or {},
                row.get("choice") or {},
            )
            if record:
                fired.append(record)
        return fired

    def _observed_event_template_from_profile(self, profile):
        if not isinstance(profile, dict):
            return None
        effects = self._observed_effect_delta_to_choice_effects(profile.get("effect_medians") or {})
        # A no-op observed event still matters for event count/timing, but it
        # should not displace real random event effects in the stochastic pool.
        if not effects and str(profile.get("event_kind") or "") != "scenario_event":
            return None
        return {
            "event_name": profile.get("event_name") or "",
            "story_id": str(profile.get("story_id") or ""),
            "source_exact": True,
            "observed_effect_delta": True,
            "choices": [{
                "choice": "observed_median",
                "label": "observed median effect",
                "effects": effects,
            }],
        }

    def _runtime_event_templates_for_source(self, source, source_id):
        if not bool(self.preset.get("sim_use_observed_event_effects", True)):
            return []
        profiles = []
        if isinstance(self.runtime_event_summary, dict):
            profiles = list(self.runtime_event_summary.get("event_profiles") or [])
        if not profiles:
            return []
        source = str(source or "")
        try:
            source_id_int = int(source_id or 0)
        except (TypeError, ValueError):
            source_id_int = 0
        weighted = []
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            if str(profile.get("source") or "") != source:
                continue
            if source == "support_card":
                expected = int(profile.get("support_card_id") or profile.get("source_id") or 0)
                if source_id_int and expected and expected != source_id_int:
                    continue
            elif source_id_int and int(profile.get("source_id") or 0) not in {0, source_id_int}:
                continue
            if not self._observed_event_profile_matches_context(profile):
                continue
            kind = str(profile.get("event_kind") or "")
            if kind in {"race_win_recurring", "race_loss_or_place_recurring", "inheritance_inspiration", "unknown"}:
                continue
            story_id = str(profile.get("story_id") or "")
            if story_id and story_id in self._seen_event_story_ids:
                continue
            template = self._observed_event_template_from_profile(profile)
            if not template:
                continue
            weight = max(1.0, float(profile.get("count") or 1.0))
            # Events with a stable turn already get deterministic handling.
            # Keep them in the random pool only lightly in case their fixed
            # turn was skipped by context filtering.
            if float(profile.get("top_turn_share") or 0.0) >= 0.80:
                weight *= 0.25
            weighted.append((template, weight))
        return weighted

    def _event_fire_probability(self):
        turn = int(self.state.get("turn") or 1)
        if turn <= 24:
            probability = 0.86
        elif turn <= 48:
            probability = 0.78
        elif turn <= 72:
            probability = 0.68
        else:
            probability = 0.58
        target_count = float(self.preset.get("sim_event_target_count") or SIM_EVENT_TARGET_COUNT)
        if getattr(self, "_observed_fixed_events_by_turn", None):
            # Fixed observed events already consume much of the event budget.
            # Without this cap, the sim double-counts deterministic scenario
            # events plus the old synthetic random-event rate.
            future_fixed = sum(
                len(rows)
                for fixed_turn, rows in self._observed_fixed_events_by_turn.items()
                if int(fixed_turn or 0) >= turn
            )
            remaining_events = max(0.0, target_count - float(len(self.events_fired)) - float(future_fixed))
            remaining_turns = max(1.0, float(TURN_FINISH - turn + 1))
            if remaining_events <= 0:
                return 0.04
            probability = min(probability, (remaining_events / remaining_turns) * 1.35)
        expected = (min(turn, TURN_FINISH) / TURN_FINISH) * target_count
        if len(self.events_fired) + 1 < expected:
            probability += 0.16
        return max(0.0, min(0.96, probability))

    def _choose_weighted(self, weighted_rows):
        rows = [(row, max(0.0, float(weight or 0))) for row, weight in weighted_rows if weight and weight > 0]
        total = sum(weight for _row, weight in rows)
        if total <= 0:
            return None
        cursor = self.rng.random() * total
        for row, weight in rows:
            cursor -= weight
            if cursor <= 0:
                return row
        return rows[-1][0] if rows else None

    def _pick_event_source(self):
        turn = int(self.state.get("turn") or 1)
        if turn in SCENARIO_EVENT_TURN_WINDOWS and self.rng.random() < 0.72:
            return {"source": "scenario", "source_id": int(self.preset.get("scenario_id") or 4)}
        if self.rng.random() < float(self.preset.get("sim_guest_event_probability") or 0.07):
            return {"source": "guest", "source_id": 0}

        support_rows = []
        for card in self.sim_support_cards or []:
            bond = int((self.state.get("bonds") or {}).get(int(card.get("partner_id") or 0), 0))
            weight = 1.0
            if turn <= 48 and bond < 80:
                weight += (80 - bond) / 45.0
            if card.get("friend"):
                weight += 0.35
            support_rows.append((card, weight))

        source_rows = []
        support_total = sum(weight for _card, weight in support_rows)
        if support_total > 0:
            source_rows.append(("support_card", support_total * (1.28 if turn <= 48 else 0.95)))
        source_rows.append(("chara", 1.25 if turn <= 48 else 1.0))
        source_rows.append(("scenario", 0.72 if turn <= 48 else 0.95))
        kind = self._choose_weighted(source_rows) or "chara"

        if kind == "support_card":
            card = self._choose_weighted(support_rows) or (self.sim_support_cards or [{}])[0]
            return {
                "source": "support_card",
                "source_id": int(card.get("support_card_id") or 0),
                "card": card,
            }
        if kind == "scenario":
            return {"source": "scenario", "source_id": int(self.preset.get("scenario_id") or 4)}
        return {"source": "chara", "source_id": int(self.trainee_card_id or 0)}

    def _event_index_entries(self, source, source_id):
        index = self.event_id_index if isinstance(self.event_id_index, dict) else {}
        observed = index.get("observed") if isinstance(index.get("observed"), dict) else {}
        try:
            source_key = str(int(source_id or 0)) if str(source_id or "").strip() else "0"
        except (TypeError, ValueError):
            source_key = str(source_id or "0")
        rows = []

        if source == "support_card":
            rows.extend((index.get("support_card_events") or {}).get(source_key, []) or [])
            rows.extend((observed.get("support_card_events") or {}).get(source_key, []) or [])
        elif source == "chara":
            rows.extend((index.get("chara_events") or {}).get(source_key, []) or [])
            rows.extend((observed.get("chara_events") or {}).get(source_key, []) or [])
        elif source == "scenario":
            rows.extend((index.get("scenario_events") or {}).get(source_key, []) or [])
            rows.extend((observed.get("scenario_events") or {}).get(source_key, []) or [])
        else:
            rows.extend((index.get("guest_events") or {}).get(source_key, []) or [])
            rows.extend((observed.get("guest_events") or {}).get(source_key, []) or [])

        deduped = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            event_name = row.get("event_name") or ""
            if _event_name_norm(event_name) in SIM_SKIP_OBSERVED_EVENT_NAMES:
                continue
            story_id = str(row.get("story_id") or event_name or len(deduped))
            previous = deduped.get(story_id)
            # Prefer rows that carry parsed effects over observed-only rows.
            if previous is None or (row.get("choices") and not previous.get("choices")):
                deduped[story_id] = row
        return list(deduped.values())

    def _template_from_event_index_entry(self, entry):
        if not isinstance(entry, dict):
            return None
        event_name = str(entry.get("event_name") or "")
        story_id = str(entry.get("story_id") or "")
        choices = []
        for choice in entry.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            effects = {}
            for key, value in (choice.get("effects") or {}).items():
                try:
                    numeric = float(value or 0)
                except (TypeError, ValueError):
                    continue
                if numeric:
                    effects[str(key)] = numeric
            if effects:
                choices.append({
                    "choice": str(choice.get("choice") if choice.get("choice") is not None else len(choices)),
                    "label": choice.get("label") or "",
                    "effects": effects,
                })
        if choices:
            return {
                "event_name": event_name,
                "story_id": story_id,
                "source_exact": True,
                "choices": choices,
            }

        base = self.event_templates_by_name.get(_event_name_norm(event_name))
        if not base:
            return None
        copied_choices = []
        for choice in base.get("choices") or []:
            copied_choices.append({
                "choice": str(choice.get("choice") if choice.get("choice") is not None else len(copied_choices)),
                "label": choice.get("label") or "",
                "effects": dict(choice.get("effects") or {}),
            })
        if not copied_choices:
            return None
        return {
            "event_name": event_name or base.get("event_name") or "",
            "story_id": story_id,
            "source_exact": False,
            "choices": copied_choices,
        }

    def _indexed_event_templates_for_source(self, source, source_id):
        weighted = list(self._runtime_event_templates_for_source(source, source_id))
        for entry in self._event_index_entries(source, source_id):
            story_id = str(entry.get("story_id") or "")
            if story_id and story_id in self._seen_event_story_ids:
                continue
            template = self._template_from_event_index_entry(entry)
            if not template:
                continue
            try:
                weight = max(1.0, float(entry.get("count") or 1.0))
            except (TypeError, ValueError):
                weight = 1.0
            if int(entry.get("chain_max") or 0) > 0:
                weight *= 1.15
            weighted.append((template, weight))
        return weighted

    def _choice_event_score(self, effects, source):
        turn = int(self.state.get("turn") or 1)
        weights = {
            "Speed": 10.0,
            "Stamina": 10.0,
            "Power": 10.0,
            "Guts": 8.0,
            "Wisdom": 9.0,
            "Skill Pts": 8.0,
            "Skill Hint": 45.0,
            "Skill": 30.0,
            "Friendship": 34.0 if turn <= 32 else (18.0 if turn <= 48 else 2.0),
            "Max Energy": 45.0 if turn <= 48 else 8.0,
            "HP": 30.0 if int(self.state.get("hp") or 0) <= 55 else 6.0,
            "Mood": 120.0 if int(self.state.get("motivation") or 3) < 5 else 0.0,
        }
        if source == "scenario":
            weights["Skill Pts"] += 4.0
            weights["HP"] += 4.0
        if source == "support_card" and turn <= 48:
            weights["Friendship"] += 12.0
        return sum(float(effects.get(key) or 0) * weight for key, weight in weights.items())

    def _pick_event_template(self, source, source_id=None):
        indexed = self._indexed_event_templates_for_source(source, source_id)
        if indexed:
            return self._choose_weighted(indexed)

        templates = self.event_effect_templates or []
        if not templates:
            return None
        if source == "support_card":
            support_like = [
                row for row in templates
                if any((choice.get("effects") or {}).get("Friendship") for choice in row.get("choices") or [])
            ]
            templates = support_like or templates
        elif source == "scenario":
            scenario_like = [
                row for row in templates
                if any(
                    (choice.get("effects") or {}).get("Skill Pts")
                    or (choice.get("effects") or {}).get("Mood")
                    or (choice.get("effects") or {}).get("Max Energy")
                    for choice in row.get("choices") or []
                )
            ]
            templates = scenario_like or templates
        return self.rng.choice(templates)

    def _pick_event_choice(self, template, source):
        choices = list((template or {}).get("choices") or [])
        if not choices:
            return None
        story_id = str((template or {}).get("story_id") or "")
        if story_id.startswith(("809006", "830036")):
            return choices[min(len(choices) - 1, len(choices) // 2)]
        scored = [
            (self._choice_event_score(choice.get("effects") or {}, source), self.rng.random(), choice)
            for choice in choices
        ]
        scored.sort(key=lambda row: (-row[0], row[1]))
        return scored[0][2]

    def _sim_event_sp_bucket(self, source_info, template):
        source = (source_info or {}).get("source") or "guest"
        action = (source_info or {}).get("action") or "event"
        if action == "recreation":
            return "recreation_events"
        if (template or {}).get("static_mant_event"):
            return "fixed_events"
        observed_profile = (template or {}).get("observed_profile") or {}
        if float(observed_profile.get("top_turn_share") or 0.0) >= 0.8:
            return "fixed_events"
        if source == "support_card":
            return "support_events"
        if source == "scenario":
            return "fixed_events"
        if source in {"chara", "guest"}:
            return "general_events"
        return "events"

    def _apply_sim_event_effects(self, source_info, template, choice):
        effects = dict((choice or {}).get("effects") or {})
        source = source_info.get("source") or "guest"
        action = source_info.get("action") or "event"
        card = source_info.get("card") or {}
        card_effects = self._effective_card_effects(card) if card else {}
        observed_delta = bool((template or {}).get("observed_effect_delta"))
        event_effectiveness = 0.0 if observed_delta else (
            float(card_effects.get("event_effectiveness") or 0) / 100.0 if source == "support_card" else 0.0
        )
        event_recovery = 0.0 if observed_delta else (
            float(card_effects.get("event_recovery") or 0) / 100.0 if source == "support_card" else 0.0
        )
        recreation_stat_scale = 1.0
        if action == "recreation":
            recreation_stat_scale = max(1.0, float(self.preset.get("sim_friend_recreation_stat_scale") or 2.50))
        stat_gain = {}
        sp_gain = 0
        hp_gain = 0
        max_hp_gain = 0
        motivation_gain = 0
        bond_gain = 0
        skill_hint_gain = 0

        for raw_key, raw_value in effects.items():
            value = float(raw_value or 0)
            if raw_key in EVENT_STAT_KEY_MAP:
                value = max(-100.0, min(150.0, value)) if observed_delta else max(-30.0, min(35.0, value))
                state_key = EVENT_STAT_KEY_MAP[raw_key]
                scale = recreation_stat_scale if value > 0 else 1.0
                gain = int(round(value * (1.0 + event_effectiveness) * scale))
                if gain:
                    self.state[state_key] = min(STAT_CAP, int(self.state.get(state_key) or 0) + gain)
                    out_key = "wit" if state_key == "wiz" else state_key
                    stat_gain[out_key] = stat_gain.get(out_key, 0) + gain
            elif raw_key == "Skill Pts":
                value = max(-300.0, min(300.0, value)) if observed_delta else max(-60.0, min(60.0, value))
                gain = int(round(value * (1.0 + event_effectiveness)))
                if gain:
                    gain = int(round(gain * float(getattr(self, "event_sp_reward_scale", 1.0) or 0.0)))
                if gain:
                    self.state["skill_point"] = max(0, int(self.state.get("skill_point") or 0) + gain)
                    sp_gain += gain
                    if gain > 0:
                        self.sp_gain_sources[self._sim_event_sp_bucket(source_info, template)] += gain
            elif raw_key == "HP":
                value = max(-100.0, min(100.0, value)) if observed_delta else max(-35.0, min(35.0, value))
                gain = int(round(value * (1.0 + (event_recovery if value > 0 else 0.0))))
                if gain:
                    self.state["hp"] = max(0, min(int(self.state.get("max_hp") or 100), int(self.state.get("hp") or 0) + gain))
                    hp_gain += gain
            elif raw_key == "Max Energy":
                value = max(-8.0, min(8.0, value))
                gain = int(round(value))
                if gain:
                    self.state["max_hp"] = max(1, int(self.state.get("max_hp") or 100) + gain)
                    self.state["hp"] = min(int(self.state.get("max_hp") or 100), int(self.state.get("hp") or 0) + max(0, gain))
                    max_hp_gain += gain
            elif raw_key == "Mood":
                value = max(-5.0, min(5.0, value)) if observed_delta else max(-1.0, min(1.0, value))
                gain = int(round(value))
                if gain:
                    self.state["motivation"] = max(1, min(5, int(self.state.get("motivation") or 3) + gain))
                    motivation_gain += gain
            elif raw_key == "Friendship" and source == "support_card":
                value = max(-10.0, min(10.0, value))
                gain = int(round(value))
                partner_id = int(card.get("partner_id") or 0)
                if partner_id and gain:
                    bonds = self.state.setdefault("bonds", {})
                    bonds[partner_id] = max(0, min(100, int(bonds.get(partner_id) or 0) + gain))
                    bond_gain += gain
            elif raw_key in {"Skill", "Skill Hint"}:
                skill_hint_gain += int(round(value))

        record = {
            "turn": int(self.state.get("turn") or 0),
            "source": source,
            "source_id": int(source_info.get("source_id") or 0),
            "story_id": (template or {}).get("story_id") or "",
            "event_name": (template or {}).get("event_name") or "",
            "source_exact": bool((template or {}).get("source_exact")),
            "action": source_info.get("action") or "event",
            "choice": (choice or {}).get("choice") or "",
            "observed_effect_delta": observed_delta,
            "stat_gain": stat_gain,
            "sp_gain": sp_gain,
            "bond_gain": bond_gain,
            "motivation_gain": motivation_gain,
            "hp_gain": hp_gain,
            "max_hp_gain": max_hp_gain,
            "skill_hint_gain": skill_hint_gain,
        }
        if record["story_id"]:
            self._seen_event_story_ids.add(str(record["story_id"]))
        self.events_fired.append(record)
        return record

    def _simulate_turn_event(self):
        if not bool(self.preset.get("sim_use_turn_events", True)):
            return None
        if not self.event_effect_templates:
            return None
        if self.rng.random() > self._event_fire_probability():
            return None
        source_info = self._pick_event_source()
        template = self._pick_event_template(source_info.get("source"), source_info.get("source_id"))
        choice = self._pick_event_choice(template, source_info.get("source"))
        if not template or not choice:
            return None
        return self._apply_sim_event_effects(source_info, template, choice)

    def _apply_training(self, cmd):
        stat_name = cmd["_sim_primary_stat"]
        # If failure: bot loses HP but no stat gain
        fail = self.rng.randint(1, 100) <= cmd.get("failure_rate", 0)
        if fail and self._consume_good_luck_if_needed(cmd.get("failure_rate", 0)):
            fail = False
        if fail:
            self.state["hp"] = max(0, self.state["hp"] - 10)
            return
        # Apply stat gain
        training_mult = self._active_training_multiplier()
        extra_hp_cost = self._active_training_extra_hp_cost()
        for item in cmd.get("params_inc_dec_info_array") or []:
            tt = item.get("target_type")
            v = item.get("value", 0)
            if tt in TARGET_TYPE_TO_STATE_KEY and v > 0:
                state_key = TARGET_TYPE_TO_STATE_KEY[tt]
                v = int(round(v * training_mult)) + self._active_training_flat_bonus(state_key)
            if tt == 1: self.state["speed"] = min(STAT_CAP, self.state["speed"] + v)
            elif tt == 2: self.state["stamina"] = min(STAT_CAP, self.state["stamina"] + v)
            elif tt == 3: self.state["power"] = min(STAT_CAP, self.state["power"] + v)
            elif tt == 4: self.state["guts"] = min(STAT_CAP, self.state["guts"] + v)
            elif tt == 5: self.state["wiz"] = min(STAT_CAP, self.state["wiz"] + v)
            elif tt == 10:  # energy/HP
                self.state["hp"] = max(0, min(self.state["max_hp"], self.state["hp"] + v - extra_hp_cost))
            elif tt == 30:  # skill point
                v = int(v or 0)
                self.state["skill_point"] = max(0, int(self.state.get("skill_point") or 0) + v)
                if v > 0:
                    self.sp_gain_sources["training"] += v
        # Bond gain per co-trained partner. Empirical (2026-06-12, 603
        # observed single-turn deltas across 19 live account_b careers):
        # +7 is the dominant gain (404/603), +9 when the partner is the
        # tile's hint/tips partner (80/603); mean 7.33. The old flat +5
        # starved the sim of rainbows (bonds hit 80 a full year later
        # than live careers), which made the sim undervalue bond-building
        # and rainbow-priority policies.
        tips_partners = set(cmd.get("tips_event_partner_array") or [])
        for p in cmd.get("training_partner_array") or []:
            gain = 9 if p in tips_partners else 7
            self.state["bonds"][p] = min(100, self.state["bonds"].get(p, 0) + gain)
        self.train_picks[stat_name] += 1

    def _apply_rest(self):
        self.state["hp"] = min(self.state["max_hp"], self.state["hp"] + 35)
        # Slight motivation recovery
        if self.rng.random() < 0.3:
            self.state["motivation"] = min(5, self.state["motivation"] + 1)

    def _apply_recreation(self):
        self.state["motivation"] = min(5, self.state["motivation"] + 1)
        self.state["hp"] = min(self.state["max_hp"], self.state["hp"] + 15)

    def _friend_recreation_templates(self, friend_card):
        if not friend_card:
            return []
        support_id = int(friend_card.get("support_card_id") or 0)
        weighted = []
        for entry in self._event_index_entries("support_card", support_id):
            story_id = str(entry.get("story_id") or "")
            if story_id and story_id in self._seen_event_story_ids:
                continue
            if not story_id.startswith(FRIEND_RECREATION_STORY_PREFIXES):
                # Friend support cards also have random/support-chain events.
                # Recreation should prefer the outing/recreation story block.
                continue
            template = self._template_from_event_index_entry(entry)
            if not template:
                continue
            try:
                weight = max(1.0, float(entry.get("count") or 1.0))
            except (TypeError, ValueError):
                weight = 1.0
            weighted.append((template, weight))
        return weighted

    def _best_friend_recreation_command(self):
        if not bool(self.preset.get("sim_use_friend_recreation", True)):
            return None
        friend_card = self._friend_support_card()
        if not friend_card:
            return None
        max_uses = int(self.preset.get("sim_friend_recreation_max_uses") or FRIEND_RECREATION_DEFAULT_MAX_USES)
        if self.recreations_used >= max(0, max_uses):
            return None
        partner_id = int(friend_card.get("partner_id") or 0)
        bond = int((self.state.get("bonds") or {}).get(partner_id, 0))
        hp = int(self.state.get("hp") or 0)
        motivation = int(self.state.get("motivation") or 3)
        if bond >= 80 and hp >= 50 and motivation >= 4:
            return None
        templates = self._friend_recreation_templates(friend_card)
        if not templates:
            return None
        scored = []
        for template, weight in templates:
            choice = self._pick_event_choice(template, "support_card")
            if not choice:
                continue
            effects = choice.get("effects") or {}
            score = self._choice_event_score(effects, "support_card")
            score += max(0, 80 - bond) * 18.0
            if hp < 50:
                score += (50 - hp) * 32.0
            if motivation < 4:
                score += (4 - motivation) * 260.0
            score += float(effects.get("Stamina") or 0) * 42.0
            scored.append((score * max(1.0, float(weight or 1.0)), template, choice))
        if not scored:
            return None
        scored.sort(key=lambda row: (-row[0], self.rng.random()))
        score, template, choice = scored[0]
        return {
            "command_type": 3,
            "command_id": 3,
            "command_group_id": 0,
            "select_id": int(friend_card.get("partner_id") or 0),
            "current_turn": self.state["turn"],
            "current_vital": self.state["hp"],
            "_sim_primary_stat": "recreation",
            "_sim_friend_card": friend_card,
            "_sim_event_template": template,
            "_sim_event_choice": choice,
            "_sim_recreation_score": round(score, 4),
            "_sim_recreation_bond": bond,
            "_sim_recreation_hp": hp,
            "_sim_recreation_motivation": motivation,
        }

    def _should_take_recreation(self, recreation_cmd, best_cmd, best_score):
        if not recreation_cmd:
            return False
        turn = int(self.state.get("turn") or 1)
        bond = int(recreation_cmd.get("_sim_recreation_bond") or 0)
        hp = int(recreation_cmd.get("_sim_recreation_hp") or 0)
        motivation = int(recreation_cmd.get("_sim_recreation_motivation") or 3)
        target_uses = int(self.preset.get("sim_friend_recreation_target_uses") or 5)

        if hp < 35 or motivation <= 2:
            return True
        if self.recreations_used < target_uses and turn <= 48 and bond < 80:
            if not (best_cmd.get("_sim_is_rainbow") and hp >= 55 and motivation >= 4 and self.recreations_used >= 2):
                return True
        if hp < 50 and int(best_cmd.get("failure_rate") or 0) >= 12:
            return True
        recreation_score = float(recreation_cmd.get("_sim_recreation_score") or 0.0)
        return recreation_score >= max(1000.0, float(best_score or 0.0) * 0.92)

    def _apply_friend_recreation(self, recreation_cmd):
        friend_card = recreation_cmd.get("_sim_friend_card") or {}
        template = recreation_cmd.get("_sim_event_template") or {}
        choice = recreation_cmd.get("_sim_event_choice") or {}
        if not template or not choice:
            self._apply_recreation()
            self.recreations_used += 1
            return None
        source_info = {
            "source": "support_card",
            "source_id": int(friend_card.get("support_card_id") or 0),
            "card": friend_card,
            "action": "recreation",
        }
        record = self._apply_sim_event_effects(source_info, template, choice)
        self.recreations_used += 1
        return record

    def _ready_stat_recreation_card(self):
        target_bond = int(self.preset.get("stat_friend_recreation_target_bond") or 60)
        candidates = []
        for card in self.sim_support_cards or []:
            support_id = int(card.get("support_card_id") or 0)
            if support_id not in SIM_STAT_RECREATION_FRIEND_CARDS:
                continue
            partner_id = int(card.get("partner_id") or 0)
            taken = int((self.stat_recreation_steps or {}).get(partner_id, 0))
            bond = int((self.state.get("bonds") or {}).get(partner_id, 0))
            if (
                partner_id
                and taken < FRIEND_RECREATION_DEFAULT_MAX_USES
                and (bond >= target_bond or self._sim_stat_recreation_story_unlocked(support_id, bond))
            ):
                candidates.append((taken, -bond, card))
        if not candidates:
            return None
        candidates.sort()
        return candidates[0][2]

    def _apply_stat_friend_recreation(self):
        card = self._ready_stat_recreation_card()
        if not card:
            self._apply_recreation()
            return None
        partner_id = int(card.get("partner_id") or 0)
        templates = self._friend_recreation_templates(card)
        template = None
        choice = None
        if templates:
            templates = sorted(templates, key=lambda row: str((row[0] or {}).get("story_id") or ""))
            index = min(
                int((self.stat_recreation_steps or {}).get(partner_id, 0)),
                len(templates) - 1,
            )
            template = templates[index][0]
            choice = self._pick_event_choice(template, "support_card")
        if not template or not choice:
            self._apply_recreation()
            record = None
        else:
            record = self._apply_sim_event_effects(
                {
                    "source": "support_card",
                    "source_id": int(card.get("support_card_id") or 0),
                    "card": card,
                    "action": "stat_friend_recreation",
                },
                template,
                choice,
            )
        self.recreations_used += 1
        self.stat_recreation_steps[partner_id] = int((self.stat_recreation_steps or {}).get(partner_id, 0)) + 1
        return record

    def _current_race_stats(self):
        """Displayed stats — what the operator sees on the career screen.

        Used for logging, pre-race records, and anything UI-facing. For
        race outcome math, use `_effective_race_stats()` so the MANT
        scenario's +400 invisible all-stats bonus is applied.
        """
        return {
            "speed": int(self.state.get("speed") or 0),
            "stamina": int(self.state.get("stamina") or 0),
            "power": int(self.state.get("power") or 0),
            "guts": int(self.state.get("guts") or 0),
            "wit": int(self.state.get("wiz") or 0),
        }

    def _effective_race_stats(self):
        """Race-math effective stats: displayed + CAREER_INVISIBLE_STAT_BONUS.

        The MANT (Trackblazer) scenario grants +400 to every stat at
        race-evaluation time. This bonus is INVISIBLE — it does not
        show on the chara sheet, doesn't affect rating/rank calc, and
        is dropped from training-tile scoring — but the race outcome
        engine sees it. Without applying it here, the sim was scoring
        races as if the bot were 400 stats weaker than the real game,
        which is exactly why Late-strat decks were losing chronic G1s
        (Takarazuka, Tenno Sho, Mile Championship) even with stamina
        750+. Matches the bonus that the stamina-threshold check at
        `_estimate_race_threshold_score` already applies (line 6353
        area) — that one was applied, but the race outcome scorer
        wasn't, which is the gap this method closes.

        No cap applied — the bonus stacks on top of the in-game 1200
        ceiling for race math purposes (existing precedent at
        `effective_current_stamina = current['stamina'] + CAREER_INVISIBLE_STAT_BONUS`
        in `_estimate_race_threshold_score`).
        """
        base = self._current_race_stats()
        return {k: v + CAREER_INVISIBLE_STAT_BONUS for k, v in base.items()}

    def _current_aptitudes(self):
        effective = (self.legacy_effects or {}).get("effective_aptitudes")
        if effective:
            return dict(effective)
        chara = self.chara_growth_data.get(str(self.trainee_card_id)) or {}
        return dict(chara.get("base_aptitudes") or {})

    def _target_skill_roles(self):
        roles = set()
        distance = _distance_key(self.preset.get("skill_profile_distance") or self.preset.get("target_distance"))
        style = _style_key(self.preset.get("skill_profile_style") or self.preset.get("target_style") or self.default_style)
        surface = _surface_key(self.preset.get("skill_profile_surface") or self.preset.get("target_surface"))
        for value in (distance, style, surface):
            if value in LEGACY_APTITUDE_NAME_TO_KEY.values():
                roles.add(value)
        return roles

    def _role_aptitude_bucket(self, role):
        grade = str((self._current_aptitudes() or {}).get(role) or "").upper()
        if grade in {"S", "A"}:
            return "good"
        if grade in {"B", "C"}:
            return "average"
        if grade in {"D", "E", "F"}:
            return "bad"
        return "terrible"

    def _skill_rating_score_for_meta(self, meta):
        if not meta:
            return 0
        roles = meta.get("roles") or []
        base = float(meta.get("base") or 0)
        scores = meta.get("scores") or {}
        if not roles:
            return int(round(base))
        target_roles = self._target_skill_roles()
        if target_roles and any(role in target_roles for role in roles):
            bucket = "good"
        else:
            bucket_rank = {"good": 0, "average": 1, "bad": 2, "terrible": 3}
            buckets = [self._role_aptitude_bucket(role) for role in roles]
            bucket = min(buckets, key=lambda item: bucket_rank.get(item, 9)) if buckets else "average"
            if target_roles and any(role in LEGACY_APTITUDE_NAME_TO_KEY.values() for role in roles):
                role_categories = {
                    "surface" if role in {"turf", "dirt"}
                    else "distance" if role in {"sprint", "mile", "medium", "long"}
                    else "style" if role in {"front", "pace", "late", "end"}
                    else role
                    for role in roles
                }
                target_categories = {
                    "surface" if role in {"turf", "dirt"}
                    else "distance" if role in {"sprint", "mile", "medium", "long"}
                    else "style" if role in {"front", "pace", "late", "end"}
                    else role
                    for role in target_roles
                }
                if role_categories & target_categories and not any(role in target_roles for role in roles):
                    bucket = "bad"
        score = scores.get(bucket)
        return int(round(float(score if score is not None else base)))

    def _heuristic_skill_rating_score(self, skill):
        name = str(skill.get("name") or "")
        skill_id = int(skill.get("skill_id") or 0)
        clean = _skill_norm(name)
        if skill_id < 100000 or skill_id >= 900000:
            base = 180
        elif name.endswith("◎"):
            base = 262
        elif name.endswith(("○", "◯")):
            base = 217
        elif skill_id % 10 == 1:
            base = 508
        else:
            base = 217
        if any(token in clean for token in ("corner", "straightaway", "focus", "position")):
            base += 40
        return base

    def _raw_skill_rating_for_name_id(self, name, skill_id):
        key = _skill_norm(name)
        meta = self.skill_rating_meta.get(key)
        rating_score = self._skill_rating_score_for_meta(meta)
        if rating_score <= 0:
            rating_score = self._heuristic_skill_rating_score({"name": name, "skill_id": skill_id})
        return max(0, int(rating_score or 0))

    def _finalize_empirical_skill_rating_calibration(self):
        calibration = getattr(self, "skill_rating_calibration", {}) or {}
        if not calibration.get("enabled"):
            return calibration
        rows = []
        for sample in calibration.get("samples") or []:
            if not isinstance(sample, dict):
                continue
            raw_total = 0
            for skill in sample.get("skills") or []:
                if not isinstance(skill, dict):
                    continue
                raw_total += self._raw_skill_rating_for_name_id(skill.get("name") or "", _as_int(skill.get("skill_id")))
            residual = _as_int(sample.get("skill_rating_residual"))
            if raw_total <= 0 or residual <= 0:
                continue
            row = dict(sample)
            row["raw_skill_rating_total"] = raw_total
            row["raw_to_real_ratio"] = residual / raw_total
            rows.append(row)
        if len(rows) < 5:
            calibration["raw_scale_enabled"] = False
            calibration["raw_scale_reason"] = "not_enough_skill_list_samples"
            return calibration
        raw_scale = _weighted_percentile(rows, "raw_to_real_ratio", 0.50, default=1.0)
        calibration["raw_scale_enabled"] = True
        calibration["raw_sample_count"] = len(rows)
        calibration["raw_skill_rating_scale"] = max(0.1, min(1.5, float(raw_scale or 1.0)))
        calibration["raw_skill_rating_total_median"] = int(round(_weighted_percentile(rows, "raw_skill_rating_total", 0.50, default=0)))
        calibration["raw_skill_rating_total_p85"] = int(round(_weighted_percentile(rows, "raw_skill_rating_total", 0.85, default=0)))
        return calibration

    def _sim_legacy_skill_hint_levels(self):
        ids = {}
        groups = {}
        names = {}
        for hint in (self.legacy_effects or {}).get("legacy_skill_hints") or []:
            if not isinstance(hint, dict) or hint.get("category") not in {"skill", "unique"}:
                continue
            try:
                stars = max(1, min(5, int(hint.get("stars") or 1)))
            except (TypeError, ValueError):
                stars = 1
            hint_id = _as_int(hint.get("skill_id") or hint.get("id"))
            if hint_id:
                ids[hint_id] = max(ids.get(hint_id, 0), stars)
                group_id = _sim_skill_group_id(hint_id)
                if group_id:
                    groups[group_id] = max(groups.get(group_id, 0), stars)
            name_key = _skill_norm(hint.get("name"))
            if name_key:
                names[name_key] = max(names.get(name_key, 0), stars)
        return {"ids": ids, "groups": groups, "names": names}

    def _candidate_legacy_hint_level(self, skill_id, name, legacy_hints=None):
        legacy_hints = legacy_hints or self._sim_legacy_skill_hint_levels()
        name_key = _skill_norm(name)
        group_id = _sim_skill_group_id(skill_id)
        return max(
            int((legacy_hints.get("ids") or {}).get(int(skill_id or 0), 0) or 0),
            int((legacy_hints.get("groups") or {}).get(group_id, 0) or 0),
            int((legacy_hints.get("names") or {}).get(name_key, 0) or 0),
        )

    def _sim_deck_card_hint_levels(self):
        """Build a {skill_id: hint_level} map from cards in the deck.

        Each card's `hint_levels` (effective tier) applies to every skill in
        the card's `hint_skills` list. Stacks additively when multiple deck
        cards hint the same skill. Cached on first call.
        """
        cached = getattr(self, "_sim_deck_card_hint_levels_cache", None)
        if cached is not None:
            return cached
        result = {"ids": {}}
        for card in (self.sim_support_cards or []):
            try:
                hint_level = int(self._effective_card_effects(card).get("hint_levels") or 0)
            except (TypeError, ValueError):
                hint_level = 0
            if hint_level <= 0:
                continue
            support_id = int(card.get("support_card_id") or 0)
            record = self.support_bonus_data.get(str(support_id)) or {}
            for skill_id in record.get("hint_skills") or []:
                try:
                    sid = int(skill_id)
                except (TypeError, ValueError):
                    continue
                result["ids"][sid] = int(result["ids"].get(sid, 0)) + hint_level
        self._sim_deck_card_hint_levels_cache = result
        return result

    def _candidate_card_hint_level(self, skill_id, deck_hints=None):
        """Hint level contributed by deck cards for this skill_id."""
        deck_hints = deck_hints or self._sim_deck_card_hint_levels()
        return int((deck_hints.get("ids") or {}).get(int(skill_id or 0), 0) or 0)

    def _skill_hint_discount_pct(self, hint_level):
        try:
            hint_level = int(hint_level or 0)
        except (TypeError, ValueError):
            hint_level = 0
        if hint_level <= 0:
            return 0.0
        per_level = float(self.preset.get("sim_skill_hint_discount_per_level_pct") or 10.0)
        cap = float(self.preset.get("sim_skill_hint_discount_cap_pct") or 50.0)
        return max(0.0, min(cap, hint_level * per_level))

    def _candidate_effective_discount_pct(self, candidate, discount_pct=0):
        # Real hint discounts are attached to specific hinted skills. The old
        # simulator used inherited_skill_hint_count as a global discount, which
        # made every support/event skill 35% cheaper and left fake end-career SP
        # piles. Keep a global override only for explicit experiments.
        effective_discount = 0.0
        if bool(self.preset.get("sim_apply_global_inheritance_discount", False)):
            effective_discount = max(effective_discount, float(discount_pct or 0))
        effective_discount = max(
            effective_discount,
            self._skill_hint_discount_pct(candidate.get("legacy_hint_level") or 0),
        )
        if candidate.get("friend_event_hint"):
            effective_discount = max(
                effective_discount,
                float(self.preset.get("sim_friend_event_skill_discount_pct") or 30),
            )
        return max(0.0, min(50.0, effective_discount))

    def _build_sim_skill_candidates(self):
        activation_data = _load_json_data("skill_activation_data.json", {})
        available_ids, available_names = self._sim_available_skill_keys()
        legacy_hints = self._sim_legacy_skill_hint_levels()
        # Card-level hints: deck cards with `hint_levels > 0` apply that
        # tier to every skill in their `hint_skills` list (stacks across
        # multiple deck cards).
        deck_card_hints = self._sim_deck_card_hint_levels()
        candidates = []
        seen = set()
        for raw_key, raw in (activation_data or {}).items():
            if not isinstance(raw, dict):
                continue
            try:
                skill_id = int(raw.get("skill_id") or raw_key)
                datamine_cost = int(raw.get("cost") or 0)
            except (TypeError, ValueError):
                continue
            name = str(raw.get("name") or "").strip()
            if not skill_id or not name or datamine_cost <= 0 or skill_id in seen:
                continue
            name_key = _skill_norm(name)
            if skill_id not in available_ids and name_key not in available_names:
                continue
            if self._is_bad_sim_skill_name(name):
                continue
            group_id = _sim_skill_group_id(skill_id)
            legacy_hint_level = self._candidate_legacy_hint_level(skill_id, name, legacy_hints)
            # Add card-derived hint level for this skill_id (stacks with
            # legacy/parent hints). `_skill_hint_discount_pct` already
            # caps the total discount, so over-stacking is safe.
            card_hint_level = self._candidate_card_hint_level(skill_id, deck_card_hints)
            effective_hint_level = legacy_hint_level + card_hint_level
            estimated_cost_floor = _estimated_sim_skill_point_cost(skill_id, name, 0)
            cost = max(datamine_cost, estimated_cost_floor)
            seen.add(skill_id)
            meta = self.skill_rating_meta.get(name_key)
            rating_score = self._skill_rating_score_for_meta(meta)
            rating_source = "umatools" if rating_score > 0 else "heuristic"
            if rating_score <= 0:
                rating_score = self._heuristic_skill_rating_score(raw)
            category = str(raw.get("category") or (meta or {}).get("category") or "").lower()
            if category == "debuff":
                continue
            roles = list((meta or {}).get("roles") or [])
            candidates.append({
                "skill_id": skill_id,
                "group_id": group_id,
                "name": name,
                "base_cost": cost,
                "datamine_cost": datamine_cost,
                "estimated_cost_floor": estimated_cost_floor,
                "legacy_hint_level": effective_hint_level,
                "card_hint_level": card_hint_level,
                "legacy_only_hint_level": legacy_hint_level,
                "friend_event_hint": skill_id in self.friend_event_skill_ids,
                "rating_score": int(rating_score),
                "rating_source": rating_source,
                "category": category,
                "effect_type": str(raw.get("effect_type") or ""),
                "condition": str(raw.get("condition") or ""),
                "roles": roles,
            })
        candidates.sort(key=lambda item: (-int(item.get("rating_score") or 0), int(item.get("base_cost") or 9999), item["skill_id"]))
        return candidates

    def _sim_available_skill_keys(self):
        ids = set()
        names = set()
        for card in getattr(self, "sim_support_cards", None) or self.deck or []:
            support_id = card.get("support_card_id") or card.get("id")
            try:
                support_id = int(support_id or 0)
            except (TypeError, ValueError):
                support_id = 0
            row = self.support_bonus_data.get(str(support_id)) or self.support_bonus_data.get(support_id) or {}
            for field in ("event_skills", "hint_skills"):
                for skill_id in row.get(field) or []:
                    try:
                        ids.add(int(skill_id))
                    except (TypeError, ValueError):
                        continue
        for hint in (self.legacy_effects or {}).get("legacy_skill_hints") or []:
            if hint.get("category") not in {"skill", "unique"}:
                continue
            name = _skill_norm(hint.get("name"))
            if name:
                names.add(name)
        # These are common enough to appear from random events or universal
        # hints. Keep the fallback small so the sim does not pretend it can buy
        # the entire datamine table.
        for name in (
            "Focus",
            "Corner Recovery ○",
            "Straightaway Recovery",
            "Corner Adept ○",
            "Corner Acceleration ○",
            "Straightaway Acceleration",
            "Preferred Position",
            "Ramp Up",
            "Slipstream",
        ):
            names.add(_skill_norm(name))
        return ids, names

    def _is_bad_sim_skill_name(self, name):
        text = str(name or "").lower()
        clean = _skill_norm(name)
        if "×" in text or text.endswith(" x"):
            return True
        bad_tokens = (
            "averseness",
            "fright",
            "defeatist",
            "wallflower",
            "hesitant",
            "panic",
            "slacker",
        )
        return any(token in clean for token in bad_tokens)

    def _discounted_skill_cost(self, candidate, discount_pct):
        cost = self._raw_discounted_skill_cost(candidate, discount_pct)
        scale = self._sim_skill_cost_scale()
        if scale and scale != 1.0:
            cost = int(round(cost * scale))
        return max(1, int(cost))

    def _raw_discounted_skill_cost(self, candidate, discount_pct):
        try:
            base_cost = int(candidate.get("base_cost") or 0)
        except (TypeError, ValueError):
            base_cost = 0
        try:
            discount = float(discount_pct or 0)
        except (TypeError, ValueError):
            discount = 0.0
        discount = max(0.0, min(50.0, discount))
        return max(1, int(base_cost * max(0.0, 1.0 - discount / 100.0)))

    def _sim_skill_cost_scale(self):
        raw = self.preset.get("sim_skill_cost_scale")
        if raw is not None:
            try:
                return max(0.25, min(2.5, float(raw)))
            except (TypeError, ValueError):
                pass
        calibration = getattr(self, "skill_rating_calibration", {}) or {}
        if calibration.get("enabled") and calibration.get("skill_cost_scale"):
            return max(0.25, min(2.5, float(calibration.get("skill_cost_scale") or 1.0)))
        return 1.0

    def _finalize_empirical_skill_cost_calibration(self):
        calibration = getattr(self, "skill_rating_calibration", {}) or {}
        if not calibration.get("enabled"):
            return calibration
        target_avg = float(calibration.get("skill_cost_per_skill_target") or 0.0)
        if target_avg <= 0 or not self.sim_skill_candidates:
            calibration["skill_cost_scale"] = 1.0
            calibration["skill_cost_scale_reason"] = "missing_empirical_skill_cost_target"
            return calibration
        target_count = max(1, int(calibration.get("skill_count_target") or SIM_TOTAL_SKILL_PURCHASE_MAX_DEFAULT))
        candidates = []
        for candidate in self.sim_skill_candidates:
            discount = self._candidate_effective_discount_pct(candidate, 0)
            row = dict(candidate)
            row["_raw_discounted_cost"] = self._raw_discounted_skill_cost(candidate, discount)
            row["discounted_cost"] = row["_raw_discounted_cost"]
            candidates.append(row)
        candidates.sort(key=lambda item: (
            -self._skill_purchase_priority(item, phase="final"),
            -int(item.get("rating_score") or 0),
            int(item.get("_raw_discounted_cost") or 9999),
            int(item.get("skill_id") or 0),
        ))
        sample = candidates[:target_count]
        if not sample:
            calibration["skill_cost_scale"] = 1.0
            calibration["skill_cost_scale_reason"] = "no_sim_skill_candidates"
            return calibration
        priority_avg = sum(int(row.get("_raw_discounted_cost") or 0) for row in sample) / max(1, len(sample))
        efficiency_rows = sorted(candidates, key=lambda item: (
            -(float(item.get("rating_score") or 0.0) / max(1.0, float(item.get("_raw_discounted_cost") or 1))),
            -int(item.get("rating_score") or 0),
            int(item.get("_raw_discounted_cost") or 9999),
            int(item.get("skill_id") or 0),
        ))[:target_count]
        efficiency_avg = (
            sum(int(row.get("_raw_discounted_cost") or 0) for row in efficiency_rows) / max(1, len(efficiency_rows))
            if efficiency_rows else priority_avg
        )
        sim_avg = min(priority_avg, efficiency_avg)
        if sim_avg <= 0:
            calibration["skill_cost_scale"] = 1.0
            calibration["skill_cost_scale_reason"] = "zero_sim_candidate_cost"
            return calibration
        scale = target_avg / sim_avg
        calibration["skill_cost_scale"] = max(0.80, min(1.35, float(scale)))
        calibration["skill_cost_raw_candidate_avg"] = round(sim_avg, 3)
        calibration["skill_cost_priority_candidate_avg"] = round(priority_avg, 3)
        calibration["skill_cost_efficiency_candidate_avg"] = round(efficiency_avg, 3)
        return calibration

    def _available_skill_candidates(self, discount_pct, budget=None):
        rows = []
        for candidate in self.sim_skill_candidates:
            skill_id = int(candidate.get("skill_id") or 0)
            if skill_id in self._purchased_skill_ids:
                continue
            effective_discount = self._candidate_effective_discount_pct(candidate, discount_pct)
            cost = self._discounted_skill_cost(candidate, effective_discount)
            if budget is not None and cost > budget:
                continue
            row = dict(candidate)
            row["discounted_cost"] = cost
            row["effective_discount_pct"] = max(0.0, min(50.0, effective_discount))
            rows.append(row)
        return rows

    def _sim_skill_cost_floor(self, discount_pct):
        rows = self._available_skill_candidates(discount_pct)
        if not rows:
            return None
        return min(int(row.get("discounted_cost") or 9999) for row in rows)

    def _sim_skill_rating_scale(self):
        raw = self.preset.get("sim_skill_rating_scale")
        if raw is not None:
            try:
                return max(0.0, min(1.0, float(raw)))
            except (TypeError, ValueError):
                pass
        return SIM_SKILL_RATING_SCALE_DEFAULT

    def _sim_total_skill_purchase_max(self):
        raw = self.preset.get("sim_total_skill_purchase_max")
        if raw is not None:
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                pass
        calibration = getattr(self, "skill_rating_calibration", {}) or {}
        if calibration.get("enabled"):
            # Parent memory often undercounts final skill purchases because
            # old runs hoarded SP or the synced parent row only exposed a
            # subset of final skills. Treat empirical counts as a guide, not a
            # ceiling that prevents end-buy sims from spending thousands of SP.
            return max(
                SIM_TOTAL_SKILL_PURCHASE_MAX_DEFAULT,
                int(calibration.get("skill_count_target") or 0),
                int(calibration.get("skill_count_p85") or 0),
            )
        return SIM_TOTAL_SKILL_PURCHASE_MAX_DEFAULT

    def _sim_skill_rating_score_cap(self):
        raw = self.preset.get("sim_skill_rating_score_cap")
        if raw is not None:
            try:
                return max(0, int(raw))
            except (TypeError, ValueError):
                pass
        calibration = getattr(self, "skill_rating_calibration", {}) or {}
        if calibration.get("enabled"):
            return max(
                SIM_SKILL_RATING_SCORE_CAP_DEFAULT,
                int(calibration.get("skill_rating_target") or 0),
                int(calibration.get("skill_rating_p85") or 0),
                int(calibration.get("skill_rating_p95") or 0),
            )
        return SIM_SKILL_RATING_SCORE_CAP_DEFAULT

    def _empirical_skill_rating_for_count(self, count):
        calibration = getattr(self, "skill_rating_calibration", {}) or {}
        if not calibration.get("enabled"):
            return None
        target_count = max(1, int(calibration.get("skill_count_target") or SIM_TOTAL_SKILL_PURCHASE_MAX_DEFAULT))
        target_score = max(0, int(calibration.get("skill_rating_target") or 0))
        p85_score = max(target_score, int(calibration.get("skill_rating_p85") or target_score))
        count = max(0, int(count or 0))
        if count <= target_count:
            return int(round(target_score * (count / target_count)))
        extra_room = max(1, int(calibration.get("skill_count_p85") or target_count) - target_count)
        extra_progress = min(1.0, (count - target_count) / extra_room)
        return int(round(target_score + (p85_score - target_score) * extra_progress))

    def _sim_effective_skill_rating_delta(self, raw_rating_score):
        calibration = getattr(self, "skill_rating_calibration", {}) or {}
        if calibration.get("enabled") and calibration.get("raw_scale_enabled"):
            effective_rating_score = int(round(int(raw_rating_score or 0) * float(calibration.get("raw_skill_rating_scale") or 1.0)))
            rating_cap = self._sim_skill_rating_score_cap()
            if rating_cap:
                effective_rating_score = max(0, min(effective_rating_score, rating_cap - int(self.skill_rating_score or 0)))
            return effective_rating_score
        empirical_before = self._empirical_skill_rating_for_count(self.skills_bought)
        empirical_after = self._empirical_skill_rating_for_count(self.skills_bought + 1)
        if empirical_before is not None and empirical_after is not None:
            return max(0, int(empirical_after) - int(empirical_before))
        effective_rating_score = int(round(int(raw_rating_score or 0) * self._sim_skill_rating_scale()))
        rating_cap = self._sim_skill_rating_score_cap()
        if rating_cap:
            effective_rating_score = max(0, min(effective_rating_score, rating_cap - int(self.skill_rating_score or 0)))
        return effective_rating_score

    def _skill_purchase_priority(self, candidate, *, phase, race_name=None, race_context=None):
        cost = max(1, int(candidate.get("discounted_cost") or candidate.get("base_cost") or 1))
        rating = float(candidate.get("rating_score") or 0)
        priority = rating / cost
        roles = set(candidate.get("roles") or [])
        target_roles = self._target_skill_roles()
        if roles & target_roles:
            priority += 2.0
        elif roles and any(
            role in {"sprint", "mile", "medium", "long", "front", "pace", "late", "end"}
            for role in roles
        ):
            priority -= 1.25
        category = str(candidate.get("category") or "").lower()
        effect = str(candidate.get("effect_type") or "").lower()
        if category == "debuff":
            priority -= 4.0
        if phase == "pre_race":
            distance = _distance_key((race_context or {}).get("distance"))
            if distance == "long" and (category == "recovery" or "heal" in effect or "recovery" in effect):
                priority += 8.0
            if race_name and any(token in str(race_name) for token in ("Kikuka", "Tenno Sho (Spring)")):
                if category == "recovery" or "stamina" in effect or "heal" in effect:
                    priority += 5.0
        return priority

    def _buy_simulated_skills(self, *, budget, max_count=None, phase="final", race_name=None, race_context=None, discount_pct=0):
        bought = []
        remaining = int(max(0, budget or 0))
        while remaining > 0 and (max_count is None or len(bought) < max_count):
            total_cap = self._sim_total_skill_purchase_max()
            if total_cap and self.skills_bought >= total_cap:
                break
            rating_cap = self._sim_skill_rating_score_cap()
            raw_scale_enabled = bool((getattr(self, "skill_rating_calibration", {}) or {}).get("raw_scale_enabled"))
            if rating_cap and self.skill_rating_score >= rating_cap and not raw_scale_enabled:
                break
            candidates = self._available_skill_candidates(discount_pct, budget=remaining)
            if not candidates:
                break
            candidates.sort(key=lambda item: (
                -self._skill_purchase_priority(item, phase=phase, race_name=race_name, race_context=race_context),
                -int(item.get("rating_score") or 0),
                int(item.get("discounted_cost") or 9999),
                int(item.get("skill_id") or 0),
            ))
            chosen = candidates[0]
            cost = int(chosen.get("discounted_cost") or 0)
            if cost <= 0 or cost > remaining:
                break
            skill_id = int(chosen.get("skill_id") or 0)
            raw_rating_score = int(chosen.get("rating_score") or 0)
            effective_rating_score = self._sim_effective_skill_rating_delta(raw_rating_score)
            self._purchased_skill_ids.add(skill_id)
            remaining -= cost
            self.state["skill_point"] = max(0, int(self.state.get("skill_point") or 0) - cost)
            self.skills_bought += 1
            self.skill_sp_spent += cost
            self.skill_rating_score += effective_rating_score
            record = {
                "turn": int(self.state.get("turn") or 0),
                "phase": phase,
                "race_name": race_name or "",
                "skill_id": skill_id,
                "name": chosen.get("name") or "",
                "base_cost": int(chosen.get("base_cost") or 0),
                "datamine_cost": int(chosen.get("datamine_cost") or 0),
                "estimated_cost_floor": int(chosen.get("estimated_cost_floor") or 0),
                "legacy_hint_level": int(chosen.get("legacy_hint_level") or 0),
                "discounted_cost": cost,
                "effective_discount_pct": chosen.get("effective_discount_pct") or 0,
                "friend_event_hint": bool(chosen.get("friend_event_hint")),
                "rating_score": effective_rating_score,
                "raw_rating_score": raw_rating_score,
                "rating_scale": self._sim_skill_rating_scale(),
                "rating_calibration": "empirical_parent_memory"
                    if (getattr(self, "skill_rating_calibration", {}) or {}).get("enabled")
                    else "raw_scaled",
                "rating_source": chosen.get("rating_source") or "",
                "category": chosen.get("category") or "",
                "effect_type": chosen.get("effect_type") or "",
                "roles": list(chosen.get("roles") or []),
            }
            self.purchased_skills.append(record)
            bought.append(record)
        return bought

    def _race_style(self):
        return _style_key(getattr(self, "_active_race_style", None) or self.default_style)

    def _race_effort_score(
        self,
        stats,
        *,
        distance,
        style=None,
        skill_count=0,
        recovery_skill_count=0,
        motivation=3,
        aptitudes=None,
        terrain=None,
    ):
        distance = _distance_key(distance)
        style = _style_key(style)
        weights = RACE_WEIGHT_PROFILES.get(distance) or RACE_WEIGHT_PROFILES[""]
        score = 0.0
        for stat, weight in weights.items():
            score += float((stats or {}).get(stat) or 0) * weight

        # Skills are not full race simulation here, but observed logs show
        # bought skills materially improve race stability. Cap their value so
        # hoarded SP is not treated as already spent power.
        score += min(420.0, max(0, int(skill_count or 0)) * 18.0)
        legacy = getattr(self, "legacy_effects", {}) or {}
        hint_count = int(legacy.get("inherited_skill_hint_count") or 0)
        if hint_count:
            # Inheritance does not auto-learn every skill, but it raises the
            # practical skill pool and hint-discount quality. Model that as a
            # small capped race power bonus so parent choice affects odds.
            score += min(130.0, hint_count * 3.5)
        if distance == "long":
            recovery_hints = int(legacy.get("recovery_hint_count") or 0)
            stamina_hints = int(legacy.get("stamina_hint_count") or 0)
            score += min(180.0, recovery_hints * 28.0 + stamina_hints * 12.0)
            score += min(260.0, int(recovery_skill_count or 0) * 95.0)
        if style:
            style_text = str(style or "").lower()
            style_hint_hits = 0
            for parent in getattr(self, "selected_parents", []) or []:
                for skill in parent.get("skills") or []:
                    name = str(skill.get("name") or "").lower()
                    if style_text in name or (style_text == "front" and "front runner" in name) or (style_text == "pace" and "pace chaser" in name) or (style_text == "late" and "late surger" in name) or (style_text == "end" and "end closer" in name):
                        style_hint_hits += 1
            score += min(80.0, style_hint_hits * 10.0)

        mood_mult = {5: 1.04, 4: 1.02, 3: 1.00, 2: 0.97, 1: 0.93}.get(int(motivation or 3), 1.0)
        score *= mood_mult

        aptitudes = aptitudes or {}
        if aptitudes:
            terrain_mult = _aptitude_multiplier(aptitudes.get(_surface_key(terrain)), 1.0) if terrain else 1.0
            distance_mult = _aptitude_multiplier(aptitudes.get(distance), 1.0) if distance else 1.0
            style_mult = _aptitude_multiplier(aptitudes.get(style), 1.0) if style else 1.0
            # Distance/style/surface aptitudes hurt race outcome heavily, but
            # not every stat contribution is direct speed. Blend the penalty
            # instead of multiplying the whole score to zero.
            apt_mult = 0.35 + 0.65 * (terrain_mult * distance_mult * style_mult)
            score *= max(0.30, min(1.08, apt_mult))
        return score

    def _sample_race_score(self, sample, distance, style):
        race = sample.get("race") or {}
        # Real-game MANT race math applies +400 invisible bonus to the trainee.
        # uma in the race — bot AND opponents. The samples store the
        # observed bot's DISPLAYED stats at race time (no +400). Add +400
        # for player-side comparisons only; opponent field rows stay raw.
        # Correction: only the trainee/player side gets the hidden +400.
        raw = sample.get("raw_stats") or {}
        effective = {k: int(v or 0) + CAREER_INVISIBLE_STAT_BONUS for k, v in raw.items()}
        return self._race_effort_score(
            effective,
            distance=distance or race.get("distance"),
            style=style or sample.get("running_style"),
            skill_count=sample.get("skill_count") or 0,
            recovery_skill_count=0,
            motivation=sample.get("motivation") or 3,
        )

    def _sample_effective_race_stats(self, sample):
        raw = (sample or {}).get("raw_stats") or {}
        return {
            "speed": _as_int(raw.get("speed")) + CAREER_INVISIBLE_STAT_BONUS,
            "stamina": _as_int(raw.get("stamina")) + CAREER_INVISIBLE_STAT_BONUS,
            "power": _as_int(raw.get("power")) + CAREER_INVISIBLE_STAT_BONUS,
            "guts": _as_int(raw.get("guts")) + CAREER_INVISIBLE_STAT_BONUS,
            "wit": _as_int(raw.get("wit")) + CAREER_INVISIBLE_STAT_BONUS,
        }

    def _race_result_sample_distance(self, sample, *, current_stats, current_score, distance, style, terrain):
        """Distance between current race state and an observed race result.

        Scalar race score alone can hide a bad stamina/power shape. This keeps
        nearest-neighbor calibration local to both total race strength and the
        actual stat vector that produced the observed win/loss.
        """
        sample_stats = self._sample_effective_race_stats(sample)
        weights = RACE_WEIGHT_PROFILES.get(_distance_key(distance)) or RACE_WEIGHT_PROFILES[""]
        weight_total = sum(float(v or 0.0) for v in weights.values()) or 1.0
        stat_distance = 0.0
        for stat, weight in weights.items():
            current = float((current_stats or {}).get(stat) or 0.0)
            observed = float(sample_stats.get(stat) or 0.0)
            denom = max(220.0, current, observed)
            stat_distance += float(weight or 0.0) * abs(current - observed) / denom
        stat_distance /= weight_total

        sample_score = self._sample_race_score(sample, distance, style)
        score_distance = abs(float(sample_score or 0.0) - float(current_score or 0.0)) / max(
            180.0,
            float(sample_score or 0.0),
            float(current_score or 0.0),
        )

        style_penalty = 0.0
        sample_style = sample.get("running_style")
        if sample_style and _style_key(sample_style) != _style_key(style):
            style_penalty = 0.10
        race = sample.get("race") or {}
        terrain_penalty = 0.0
        if terrain and race.get("terrain") and _surface_key(race.get("terrain")) != _surface_key(terrain):
            terrain_penalty = 0.05
        return (stat_distance * 0.70) + (score_distance * 0.30) + style_penalty + terrain_penalty

    def _purchased_recovery_skill_count(self):
        count = 0
        for row in self.purchased_skills or []:
            text = " ".join([
                str(row.get("name") or ""),
                str(row.get("effect_type") or ""),
                str(row.get("category") or ""),
            ]).lower()
            if "recovery" in text or "stamina" in text:
                count += 1
        return count

    def _candidate_race_result_samples(self, pid, distance, grade, style):
        exact = list(self.race_samples_by_pid.get(int(pid or 0), []))
        if exact:
            style = _style_key(style)
            style_matches = [sample for sample in exact if not sample.get("running_style") or _style_key(sample.get("running_style")) == style]
            if len(style_matches) >= 30:
                return style_matches, "real_result_exact_style"
            if len(exact) >= 20:
                return exact, "real_result_exact"

        distance = _distance_key(distance)
        grade = str(grade or "").upper()
        profile = list(self.race_samples_by_profile.get((distance, grade), []))
        if len(profile) < 60 and grade == "G1":
            profile = list(self.race_samples_by_profile.get((distance, ""), []))
        if len(profile) >= 60:
            return profile, "real_result_distance_profile"
        return [], ""

    def _estimate_race_from_results(self, pid, race_name, distance, era, grade="", terrain="", *, skill_count=None, sample=True):
        race_style = self._race_style()
        samples, source = self._candidate_race_result_samples(pid, distance, grade, race_style)
        if not samples:
            return None
        effective_skill_count = self.skills_bought if skill_count is None else int(skill_count or 0)
        current_score = self._race_effort_score(
            self._effective_race_stats(),  # +400 invisible MANT bonus
            distance=distance,
            style=race_style,
            skill_count=effective_skill_count,
            recovery_skill_count=self._purchased_recovery_skill_count(),
            motivation=self.state.get("motivation") or 3,
            aptitudes=self._current_aptitudes(),
            terrain=terrain,
        )
        current_stats = self._effective_race_stats()
        scored = [
            (
                self._race_result_sample_distance(
                    sample,
                    current_stats=current_stats,
                    current_score=current_score,
                    distance=distance,
                    style=race_style,
                    terrain=terrain,
                ),
                abs(self._sample_race_score(sample, distance, race_style) - current_score),
                sample,
            )
            for sample in samples
        ]
        scored.sort(key=lambda item: item[0])
        k = min(max(45, len(scored) // 4), 160, len(scored))
        nearest_scored = scored[:k]
        nearest = [sample for _, _, sample in nearest_scored]
        if not nearest:
            return None

        total_wins = sum(1 for sample in samples if sample.get("won"))
        base_rate = total_wins / max(1, len(samples))
        near_wins = sum(1 for sample in nearest if sample.get("won"))
        nearest_probability = (near_wins + base_rate * 8.0) / (len(nearest) + 8.0)

        bandwidth = max(0.035, _percentile([row[0] for row in scored[:max(k, min(len(scored), 220))]], 60))
        weighted_total = 0.0
        weighted_wins = 0.0
        for distance_value, _score_delta, sample in scored[:max(k, min(len(scored), 220))]:
            scaled = float(distance_value or 0.0) / bandwidth
            weight = 1.0 / (1.0 + scaled * scaled)
            weighted_total += weight
            if sample.get("won"):
                weighted_wins += weight
        kernel_probability = (weighted_wins + base_rate * 5.0) / max(1e-6, weighted_total + 5.0)
        win_probability = (kernel_probability * 0.65) + (nearest_probability * 0.35)

        all_scores = [self._sample_race_score(sample, distance, race_style) for sample in samples]
        win_scores = [self._sample_race_score(sample, distance, race_style) for sample in samples if sample.get("won")]
        loss_scores = [self._sample_race_score(sample, distance, race_style) for sample in samples if not sample.get("won")]
        if win_scores:
            win_p25 = _percentile(win_scores, 25)
            win_p50 = _percentile(win_scores, 50)
            win_p75 = _percentile(win_scores, 75)
            loss_p75 = _percentile(loss_scores, 75) if loss_scores else win_p50
            spread = max(120.0, max(win_p75, loss_p75) - win_p25)
            score_prob = 0.12 + ((current_score - win_p25) / spread) * 0.72
            score_prob = max(0.08, min(0.94, score_prob))
            win_probability = (win_probability * 0.78) + (score_prob * 0.22)
            if loss_scores and current_score >= loss_p75 and current_score >= win_p50:
                win_probability = max(win_probability, 0.82)
            if current_score >= win_p75:
                win_probability = max(win_probability, 0.88)
        if win_scores and current_score >= _percentile(win_scores, 85):
            win_probability = max(win_probability, 0.82)
        if all_scores and current_score >= _percentile(all_scores, 92):
            win_probability = max(win_probability, 0.90)
        if loss_scores and current_score <= _percentile(loss_scores, 30):
            win_probability = min(win_probability, 0.38)
        if win_scores and current_score <= _percentile(win_scores, 10):
            win_probability = min(win_probability, 0.32)

        win_probability = max(0.05, min(0.97, win_probability))
        won = (self.rng.random() <= win_probability) if sample else None
        loss_rank_counts = defaultdict(int)
        rank_counts = defaultdict(int)
        for near in nearest:
            rank = _as_int(near.get("result_rank"))
            if rank > 0:
                rank_counts[rank] += 1
                if rank > 1:
                    loss_rank_counts[rank] += 1
        return {
            "won": won,
            "model": source,
            "win_probability": round(win_probability, 4),
            "current_score": round(current_score, 2),
            "nearest_samples": len(nearest),
            "samples": len(samples),
            "base_win_rate": round(base_rate, 4),
            "nearest_win_rate": round(near_wins / max(1, len(nearest)), 4),
            "kernel_win_rate": round(kernel_probability, 4),
            "nearest_bandwidth": round(bandwidth, 5),
            "nearest_rank_counts": {str(k): int(v) for k, v in sorted(rank_counts.items())},
            "nearest_loss_rank_counts": {str(k): int(v) for k, v in sorted(loss_rank_counts.items())},
            "score_p50_win": round(_percentile(win_scores, 50), 2),
            "score_p75_loss": round(_percentile(loss_scores, 75), 2),
        }

    def _field_sample_threshold(self, sample, distance, style, terrain):
        opponents = sample.get("opponents") or []
        scores = []
        for opponent in opponents:
            scores.append(self._race_effort_score(
                opponent.get("stats") or {},
                distance=distance or (sample.get("race") or {}).get("distance"),
                style=STYLE_NUM_TO_KEY.get(int(opponent.get("running_style") or 0), style),
                skill_count=opponent.get("skill_count") or 0,
                motivation=opponent.get("motivation") or 3,
                aptitudes=opponent.get("aptitudes") or {},
                terrain=terrain or (sample.get("race") or {}).get("terrain"),
            ))
        if not scores:
            return 0.0
        # The player does not need to exceed the strongest NPC every time,
        # because the game has positional RNG and opponent variance. The 80th
        # percentile is a practical win-risk threshold.
        return max(_percentile(scores, 80), _percentile(scores, 95) * 0.92)

    def _estimate_race_from_fields(self, pid, distance, terrain, *, skill_count=None, sample=True):
        fields = list(self.race_fields_by_pid.get(int(pid or 0), []))
        if not fields:
            return None
        race_style = self._race_style()
        effective_skill_count = self.skills_bought if skill_count is None else int(skill_count or 0)
        current_score = self._race_effort_score(
            self._effective_race_stats(),  # +400 invisible MANT bonus
            distance=distance,
            style=race_style,
            skill_count=effective_skill_count,
            recovery_skill_count=self._purchased_recovery_skill_count(),
            motivation=self.state.get("motivation") or 3,
            aptitudes=self._current_aptitudes(),
            terrain=terrain,
        )
        thresholds = [
            self._field_sample_threshold(sample, distance, race_style, terrain)
            for sample in fields
        ]
        thresholds = [threshold for threshold in thresholds if threshold > 0]
        if not thresholds:
            return None
        threshold = _percentile(thresholds, 50)
        ratio = current_score / max(1.0, threshold)
        win_probability = max(0.06, min(0.95, 0.12 + (ratio - 0.82) / 0.38 * 0.83))
        won = (self.rng.random() <= win_probability) if sample else None
        return {
            "won": won,
            "model": "real_field_strength",
            "win_probability": round(win_probability, 4),
            "current_score": round(current_score, 2),
            "field_threshold": round(threshold, 2),
            "field_samples": len(fields),
        }

    def _empirical_race_outcome(self, pid, race_name, distance, era, *, skill_count=None, sample=True):
        if not bool(self.preset.get("sim_use_real_race_snapshots", True)):
            return None
        race_meta = None
        for row in self.scheduled_g1s:
            _, sched_pid, sched_name, sched_distance, sched_era = row[:5]
            if int(sched_pid or 0) == int(pid or 0):
                race_meta = {"name": sched_name, "distance": sched_distance, "era": sched_era}
                break
        grade = "G1"
        terrain = ""
        row = self.race_catalog_by_program_id.get(int(pid or 0)) or {}
        grade = row.get("type") or grade
        terrain = row.get("terrain") or terrain
        distance = distance or _distance_key(row.get("distance"))
        estimate = self._estimate_race_from_results(
            pid,
            race_name,
            distance,
            era,
            grade=grade,
            terrain=terrain,
            skill_count=skill_count,
            sample=sample,
        )
        if estimate:
            return estimate
        return self._estimate_race_from_fields(pid, distance, terrain, skill_count=skill_count, sample=sample)

    def _race_probability_estimate(self, pid, race_name, distance, era, *, skill_count=None):
        model = self._empirical_race_outcome(
            pid,
            race_name,
            distance,
            era,
            skill_count=skill_count,
            sample=False,
        )
        manual = self._manual_threshold_probability_estimate(
            pid,
            race_name,
            distance,
            era,
            skill_count=skill_count,
        )
        if model and model.get("win_probability") is not None:
            empirical_prob = float(model.get("win_probability") or 0.0)
            if manual:
                manual_prob, manual_model = manual
                manual_safe = self._manual_race_model_is_safe(manual_prob, manual_model)
                # Manual threshold's stamina floor is authoritative: if it
                # says the trainee is critically under-stamina, the empirical
                # model is wrong about this trainee. Do not treat a merely
                # moderate stamina shortage as critical; older code used
                # manual_prob < 0.10 and ignored real result data too often.
                # Don't let empirical wins paper over a stamina shortage.
                stamina_critical = bool((manual_model or {}).get("stamina_critical"))
                if stamina_critical:
                    blended = dict(model)
                    blended["model"] = "manual_stamina_floor"
                    blended["empirical_model"] = model.get("model")
                    blended["empirical_win_probability"] = round(empirical_prob, 4)
                    blended["manual_win_probability"] = round(manual_prob, 4)
                    blended["manual_model"] = manual_model
                    blended["win_probability"] = round(manual_prob, 4)
                    return self._blend_observed_race_probability(pid, manual_prob, blended)
                empirical_model = str((model or {}).get("model") or "")
                empirical_weight = 0.72 if "exact" in empirical_model else 0.58
                if manual_safe and empirical_prob < float(manual_prob or 0.0):
                    # Exact observed samples are mostly the bot's own old
                    # careers. They are useful for marginal cases, but they
                    # must not make a currently-safe statline look unsafe just
                    # because previous runs entered the same race underbuilt.
                    blended = dict(model)
                    blended["model"] = "manual_safe_threshold_override"
                    blended["empirical_model"] = model.get("model")
                    blended["empirical_win_probability"] = round(empirical_prob, 4)
                    blended["manual_win_probability"] = round(manual_prob, 4)
                    blended["manual_threshold_safe"] = True
                    blended["manual_model"] = manual_model
                    blended_prob = max(empirical_prob, float(manual_prob or 0.0) - 0.04)
                    blended["win_probability"] = round(blended_prob, 4)
                    return self._blend_observed_race_probability(pid, blended_prob, blended)
                if abs(float(manual_prob or 0.0) - empirical_prob) >= 0.08:
                    blended_prob = (empirical_prob * empirical_weight) + (float(manual_prob or 0.0) * (1.0 - empirical_weight))
                    blended = dict(model)
                    blended["model"] = "manual_empirical_weighted"
                    blended["empirical_model"] = model.get("model")
                    blended["empirical_weight"] = round(empirical_weight, 4)
                    blended["empirical_win_probability"] = round(empirical_prob, 4)
                    blended["manual_win_probability"] = round(manual_prob, 4)
                    blended["manual_model"] = manual_model
                    blended["win_probability"] = round(blended_prob, 4)
                    return self._blend_observed_race_probability(pid, blended_prob, blended)
                with_manual = dict(model)
                with_manual["manual_win_probability"] = round(float(manual_prob or 0.0), 4)
                with_manual["manual_threshold_safe"] = bool(manual_safe)
                with_manual["manual_model"] = manual_model
                return self._blend_observed_race_probability(pid, empirical_prob, with_manual)
            return self._blend_observed_race_probability(pid, empirical_prob, model)
        if manual:
            manual_prob, manual_model = manual
            return self._blend_observed_race_probability(pid, manual_prob, manual_model)
        prob = 0.90 if self.state.get("speed", 0) > 600 else 0.20
        return self._blend_observed_race_probability(
            pid,
            prob,
            {"model": "fallback_speed_probability", "win_probability": prob},
        )

    def _manual_race_model_is_safe(self, manual_prob, manual_model):
        """Return true when the threshold model says current race stats are safely above requirements.

        Historical observed race samples are generated by this bot, so they can
        contain underbuilt losses from old policies. Use them to calibrate
        marginal race risk, not to override a statline that clears the current
        race thresholds with healthy margins.
        """
        if not isinstance(manual_model, dict):
            return False
        try:
            prob = float(manual_prob if manual_prob is not None else manual_model.get("win_probability") or 0.0)
            stamina_ratio = float(manual_model.get("true_stamina_ratio") or manual_model.get("ratio_stamina") or 0.0)
            stamina_floor = float(manual_model.get("stamina_floor_ratio") or 0.0)
            speed_ratio = float(manual_model.get("ratio_speed") or 0.0)
            power_ratio = float(manual_model.get("ratio_power") or 0.0)
            wit_ratio = float(manual_model.get("ratio_wit") or 0.0)
            aptitude_factor = float(manual_model.get("aptitude_factor") or 1.0)
        except (TypeError, ValueError):
            return False
        if bool(manual_model.get("stamina_critical")):
            return False
        distance = str(manual_model.get("distance") or "").lower()
        stamina_margin = 0.15 if distance != "long" else 0.18
        required_secondary = 1.08 if distance in {"long", "medium"} else 1.05
        return (
            prob >= 0.92
            and stamina_ratio >= max(stamina_floor + stamina_margin, 1.0)
            and speed_ratio >= required_secondary
            and power_ratio >= required_secondary
            and wit_ratio >= 1.05
            and aptitude_factor >= 0.90
        )

    def _observed_race_probability(self, pid):
        calibration = getattr(self, "race_outcome_calibration", {}) or {}
        if not calibration.get("enabled"):
            return None
        row = (calibration.get("by_pid") or {}).get(str(_as_int(pid)))
        if not row:
            return None
        runs = _as_int(row.get("runs"))
        if runs < 3:
            return None
        return max(0.02, min(0.98, float(row.get("smoothed_win_rate") or row.get("win_rate") or 0.0))), row

    def _blend_observed_race_probability(self, pid, base_prob, model):
        observed = self._observed_race_probability(pid)
        if not observed:
            return base_prob, model
        obs_prob, row = observed
        runs = _as_int(row.get("runs"))
        raw_win_rate = max(0.0, min(1.0, float(row.get("win_rate") or 0.0)))
        confidence = min(0.82, 0.30 + runs * 0.055)
        base_prob = max(0.0, min(1.0, float(base_prob or 0.0)))
        try:
            current_score = float((model or {}).get("current_score") or 0.0)
            score_p50_win = float((model or {}).get("score_p50_win") or 0.0)
            score_p75_loss = float((model or {}).get("score_p75_loss") or 0.0)
        except (TypeError, ValueError):
            current_score = score_p50_win = score_p75_loss = 0.0
        current_beats_bad_history = False
        if current_score > 0 and score_p50_win > 0 and current_score >= score_p50_win:
            confidence *= 0.45
            current_beats_bad_history = True
        if current_score > 0 and score_p75_loss > 0 and current_score >= score_p75_loss:
            confidence *= 0.70
            current_beats_bad_history = True
        manual_model = (model or {}).get("manual_model")
        if not isinstance(manual_model, dict) and str((model or {}).get("model") or "") == "manual_threshold_probability":
            manual_model = model
        manual_prob = (model or {}).get("manual_win_probability")
        if manual_prob is None and isinstance(manual_model, dict):
            manual_prob = manual_model.get("win_probability")
        manual_safe = bool((model or {}).get("manual_threshold_safe")) or self._manual_race_model_is_safe(manual_prob, manual_model)
        if manual_safe:
            confidence *= 0.15
            current_beats_bad_history = True
            base_prob = max(base_prob, min(0.96, float(manual_prob or 0.0) - 0.03 if manual_prob is not None else base_prob))
        blended_prob = (base_prob * (1.0 - confidence)) + (obs_prob * confidence)
        # When exact observed logs say a race is consistently safe, do not let
        # a weak manual threshold model push it into coin-flip territory.
        if runs >= 5 and raw_win_rate >= 0.999:
            blended_prob = max(blended_prob, 0.935)
        elif runs >= 6 and raw_win_rate >= 0.90:
            blended_prob = max(blended_prob, 0.90)
        elif runs >= 6 and raw_win_rate >= 0.80:
            blended_prob = max(blended_prob, 0.84)
        elif runs >= 6 and obs_prob >= 0.78:
            blended_prob = max(blended_prob, obs_prob)
        # Conversely, known problem races should stay risky even if the current
        # stat model is optimistic.
        if runs >= 6 and raw_win_rate <= 0.45 and not current_beats_bad_history:
            blended_prob = min(blended_prob, obs_prob + 0.08)
        if manual_safe:
            blended_prob = max(blended_prob, min(0.93, base_prob))
        blended = dict(model or {})
        blended["observed_model"] = True
        blended["observed_runs"] = runs
        blended["observed_current_beats_bad_history"] = bool(current_beats_bad_history)
        blended["manual_threshold_safe"] = bool(manual_safe)
        blended["observed_wins"] = _as_int(row.get("wins"))
        blended["observed_win_rate"] = round(raw_win_rate, 4)
        blended["observed_smoothed_win_rate"] = round(obs_prob, 4)
        blended["observed_blend_confidence"] = round(confidence, 4)
        blended["pre_observed_win_probability"] = round(base_prob, 4)
        blended["win_probability"] = round(max(0.02, min(0.98, blended_prob)), 4)
        blended["model"] = f"{(model or {}).get('model') or 'race_model'}+observed_context"
        return float(blended["win_probability"]), blended

    def _load_race_thresholds_json_targets(self):
        """Lazy-load the operator-side race_thresholds.json `target_raw` map.

        This file is populated by the postmortem pipeline with field_max
        effective stats per program_id (raw + 400 invisible bonus stripped).
        These are the ACTUAL opponent stat targets the bot has to clear.
        The sim's `self.race_thresholds` (from manual_race_data) is a much
        lower fallback; the audit showed the probability model was using
        those lower fallbacks and overestimating win chances.
        """
        cached = getattr(self, "_rt_json_targets_cache", None)
        if cached is not None:
            return cached
        from career_bot.projection import _load_race_thresholds as _proj_load
        from pathlib import Path as _P
        result = {}
        for p in _race_threshold_json_candidates(self.project_root, self.preset):
            if p.exists():
                result = _proj_load(_P(p)) or {}
                if result:
                    break
        self._rt_json_targets_cache = result
        return result

    def _manual_threshold_probability_estimate(self, pid, race_name, distance, era, *, skill_count=None):
        # Prefer the postmortem-derived `target_raw` from race_thresholds.json
        # (actual observed opponent strength) over the static manual_race_data
        # fallback. This fixes the long-standing over-confidence on sprint
        # and long races (probability model previously thought Sprinters
        # Stakes was a 96% win when it's actually 7%).
        threshold = None
        try:
            rt_targets = self._load_race_thresholds_json_targets()
        except Exception:
            rt_targets = {}
        if rt_targets and pid is not None:
            try:
                pid_int = int(pid)
            except (TypeError, ValueError):
                pid_int = 0
            entry = rt_targets.get(pid_int) or rt_targets.get(str(pid_int))
            if entry and entry.get("target_raw"):
                threshold = entry["target_raw"]
        if not threshold:
            threshold = self.race_thresholds.get(pid) or self.race_thresholds.get(race_name)
        if not threshold:
            threshold = self._fallback_race_threshold(distance, era)
        if not threshold:
            return None
        # Stat-weight model per uma.guide/race-hp + race-stats. Stamina drives
        # HP burn; below the race's threshold the trainee runs out of fuel
        # mid-race and finishes mid-pack regardless of speed. The earlier
        # weighting (speed 0.45 / power 0.35 / wit 0.20, stamina ignored on
        # medium) let bots with 460 stamina win Japan Cup and Tenno Sho
        # Spring — both impossible in the real game.
        distance_key = str(distance or "").lower()
        # +400 invisible MANT bonus — race math compares against opponent
        # field which is calibrated to effective stats too
        current_effective = self._effective_race_stats()
        skill_bonus = min(0.22, max(0, int((skill_count if skill_count is not None else self.skills_bought) or 0)) * 0.012)
        recovery_skills = self._purchased_recovery_skill_count()

        def ratio(stat):
            return current_effective[stat] / max(1, int(threshold.get(stat) or 1))

        r_speed   = ratio("speed")
        r_stamina = ratio("stamina")
        r_power   = ratio("power")
        r_guts    = ratio("guts")
        r_wit     = ratio("wit")

        # Raw stamina ratio is preserved for the hard-floor check — recovery
        # skills DO help in-race but cannot substitute for being half the
        # required stamina. The bot can't recover what it doesn't have.
        r_stamina_raw = r_stamina

        if distance_key == "long":
            # Long races (≥2400m): stamina dominates. Recovery skills add
            # effective stamina via mid-race HP refills.
            recovery_bonus = min(0.22, recovery_skills * 0.09)
            r_stamina += recovery_bonus
            coverage = (r_stamina * 0.42) + (r_speed * 0.22) + (r_power * 0.18) + (r_wit * 0.10) + (r_guts * 0.08)
        elif distance_key == "medium":
            # Medium races (1800-2400m): speed primary, but stamina is the
            # HP floor — below ~0.85 ratio the trainee burns out late.
            recovery_bonus = min(0.12, recovery_skills * 0.05)
            r_stamina += recovery_bonus
            coverage = (r_speed * 0.34) + (r_stamina * 0.26) + (r_power * 0.22) + (r_wit * 0.12) + (r_guts * 0.06)
        elif distance_key in {"mile", "sprint", "short"}:
            # Mile/sprint: power for acceleration, speed for top speed,
            # stamina barely matters but still a floor (HP only).
            coverage = (r_speed * 0.38) + (r_power * 0.30) + (r_wit * 0.14) + (r_stamina * 0.12) + (r_guts * 0.06)
            recovery_bonus = 0.0
        else:
            # Unknown distance — fall back to old balanced weighting.
            recovery_bonus = min(0.12, recovery_skills * 0.06)
            r_stamina += recovery_bonus
            coverage = (r_speed * 0.30) + (r_stamina * 0.26) + (r_power * 0.22) + (r_wit * 0.14) + (r_guts * 0.08)

        prob = 0.10 + (coverage - 0.78) * 1.25 + skill_bonus

        # Hard stamina floor — applied to RAW stamina (before recovery
        # bonus). Recovery skills shield against partial deficits via the
        # coverage term, but they don't override a fundamental shortfall.
        # In-game: at stamina 240 vs Kikuka's 380 requirement, the trainee
        # runs dry by the 4th corner regardless of how many recoveries
        # are stacked — and uma.guide's Kikuka guide says you need ~600.
        # Use the higher of the threshold and the uma.guide reference.
        kikuka_grade_stamina = {
            "long": 600,    # uma.guide: 600+ for Kikuka/Tenno Spring/Arima
            "medium": 380,  # penalize low stamina without hard-flooring every medium G1
            "mile": 300,
            "sprint": 200,
            "short": 200,
        }
        threshold_stamina_raw = int(threshold.get("stamina") or 0)
        effective_threshold_stamina = max(
            threshold_stamina_raw,
            kikuka_grade_stamina.get(distance_key, 0),
        )
        effective_current_stamina = current_effective["stamina"]
        true_stamina_ratio = effective_current_stamina / max(1, effective_threshold_stamina)
        stamina_floor_ratio = 0.90 if distance_key == "long" else 0.78 if distance_key == "medium" else 0.55
        if true_stamina_ratio < stamina_floor_ratio:
            shortfall = stamina_floor_ratio - true_stamina_ratio
            # Stronger penalty: each 0.10 shortfall multiplies by ~0.30 — at
            # raw stamina 240 vs needed 600 (ratio 0.40, shortfall 0.50)
            # the probability multiplier collapses to ~0.005, which after
            # the 0.06 floor clamp would still allow some wins. So when
            # the trainee is critically under-stamina (>0.25 shortfall),
            # also lower the minimum probability floor.
            prob *= max(0.005, 1.0 - shortfall * 7.0)

        # Stamina-critical races (>0.25 raw shortfall) bypass the normal
        # 0.06 minimum floor — the in-game outcome is near-certain loss.
        min_prob = 0.06
        critical_shortfall = 0.25 if distance_key == "long" else 0.40 if distance_key == "medium" else 0.55
        stamina_critical = true_stamina_ratio < stamina_floor_ratio - critical_shortfall
        if stamina_critical:
            min_prob = 0.005
        aptitudes = self._current_aptitudes()
        terrain = (self.race_catalog_by_program_id.get(int(pid or 0)) or {}).get("terrain") or ""
        terrain_mult = _aptitude_multiplier(aptitudes.get(_surface_key(terrain)), 1.0) if terrain else 1.0
        distance_mult = _aptitude_multiplier(aptitudes.get(distance_key), 1.0) if distance_key else 1.0
        style_mult = _aptitude_multiplier(aptitudes.get(self._race_style()), 1.0)
        aptitude_factor = max(0.30, min(1.08, 0.35 + 0.65 * (terrain_mult * distance_mult * style_mult)))
        prob *= aptitude_factor
        prob = max(min_prob, min(0.96, prob))
        return prob, {
            "model": "manual_threshold_probability",
            "win_probability": round(prob, 4),
            "ratio_primary": round(r_speed if distance_key != "long" else r_stamina, 4),
            "ratio_stamina": round(r_stamina, 4),
            "ratio_speed": round(r_speed, 4),
            "ratio_power": round(r_power, 4),
            "ratio_wit": round(r_wit, 4),
            "recovery_ratio_bonus": round(recovery_bonus, 4),
            "stamina_floor_ratio": stamina_floor_ratio,
            "true_stamina_ratio": round(true_stamina_ratio, 4),
            "effective_current_stamina": effective_current_stamina,
            "effective_threshold_stamina": effective_threshold_stamina,
            "stamina_critical": stamina_critical,
            "aptitude_factor": round(aptitude_factor, 4),
            "terrain_aptitude_multiplier": round(terrain_mult, 4),
            "distance_aptitude_multiplier": round(distance_mult, 4),
            "style_aptitude_multiplier": round(style_mult, 4),
            "distance": distance_key,
        }

    def _fallback_race_threshold(self, distance, era):
        distance_key = str(distance or "").strip().lower()
        entry = self.race_demands.get(f"{distance_key}_{self._race_style()}")
        if not entry:
            entry = self.race_demands.get(f"{distance_key}_pace")
        thresholds = (entry or {}).get("thresholds") or {}
        return thresholds.get(str(era or "").lower()) or thresholds.get("classic") or {}

    def _sim_race_meta(self, pid, race_name, distance, grade=None):
        catalog = self.race_catalog_by_program_id.get(int(pid or 0)) or {}
        race_instance_id = _as_int(catalog.get("race_instance_id"))
        race_id = _as_int(catalog.get("id"))
        if not race_id and race_instance_id:
            race_id = race_instance_id // 100
        return {
            "program_id": _as_int(pid),
            "race_id": race_id,
            "race_instance_id": race_instance_id,
            "name": race_name or catalog.get("name") or f"Race {pid}",
            "grade": grade or catalog.get("type") or catalog.get("grade") or "G1",
            "type": grade or catalog.get("type") or catalog.get("grade") or "G1",
            "terrain": catalog.get("terrain") or "Turf",
            "distance": (distance or catalog.get("distance") or "Medium").title(),
            "venue": catalog.get("venue") or "",
            "turn": _as_int(catalog.get("turn") or self.state.get("turn")),
            "synthetic": True,
        }

    def _aptitude_payload_value(self, key):
        rank = str((self._current_aptitudes() or {}).get(key) or "A").upper()
        return int(APTITUDE_RANK_VALUE.get(rank, APTITUDE_RANK_VALUE["A"]) + 1)

    def _sim_loss_finish_rank(self, probability, model=None):
        counts = (model or {}).get("nearest_loss_rank_counts") or {}
        weighted = []
        for rank, count in counts.items():
            rank = _as_int(rank)
            count = _as_int(count)
            if rank > 1 and count > 0:
                weighted.append((rank, count))
        if weighted:
            total = sum(count for _rank, count in weighted)
            roll = self.rng.randint(1, max(1, total))
            seen = 0
            for rank, count in weighted:
                seen += count
                if roll <= seen:
                    return rank
        try:
            prob = max(0.0, min(1.0, float(probability or 0.0)))
        except (TypeError, ValueError):
            prob = 0.5
        # Close losses are usually 2nd/3rd; bad probability losses can fall
        # lower. This is synthetic, but gives downstream race analysis a real
        # placement instead of flattening every loss to #2.
        base = 2 + int((1.0 - prob) * 5.0)
        jitter = self.rng.randint(0, 2)
        return max(2, min(18, base + jitter))

    def _sim_race_threshold_stats(self, pid, race_name, distance, era):
        threshold = None
        try:
            targets = self._load_race_thresholds_json_targets()
        except Exception:
            targets = {}
        if targets:
            entry = targets.get(_as_int(pid)) or targets.get(str(_as_int(pid)))
            if isinstance(entry, dict) and isinstance(entry.get("target_raw"), dict):
                threshold = entry.get("target_raw")
        if not threshold:
            threshold = self.race_thresholds.get(pid) or self.race_thresholds.get(race_name)
        if not threshold:
            threshold = self._fallback_race_threshold(distance, era)
        if not threshold:
            current = self._current_race_stats()
            threshold = {key: max(1, int(value * 0.92)) for key, value in current.items()}
        return {
            "speed": _as_int(threshold.get("speed"), 600),
            "stamina": _as_int(threshold.get("stamina"), 500),
            "power": _as_int(threshold.get("power"), 600),
            "guts": _as_int(threshold.get("guts"), 450),
            "wit": _as_int(threshold.get("wit"), 500),
        }

    def _sim_skill_array_for_payload(self, skill_ids):
        result = []
        for skill_id in skill_ids or []:
            skill_id = _as_int(skill_id)
            if skill_id:
                result.append({"skill_id": skill_id, "level": 1})
        return result

    def _synthetic_race_horse_row(
        self,
        *,
        index,
        stats,
        running_style,
        finish_rank,
        player=False,
        skill_ids=None,
        popularity=1,
    ):
        card_id = _as_int(self.trainee_card_id) if player else 0
        chara_id = card_id // 100 if card_id else 9000 + int(index)
        style_num = STYLE_KEY_TO_NUM.get(_style_key(running_style), 2)
        return {
            "viewer_id": 1 if player else 0,
            "trainer_name": "SIM_PLAYER" if player else f"SIM_OPP_{index}",
            "owner_trainer_name": "SWEEPY_SIM" if player else "SIM",
            "single_mode_chara_id": chara_id,
            "trained_chara_id": card_id,
            "card_id": card_id,
            "chara_id": chara_id,
            "rarity": 3,
            "talent_level": 5 if player else 3,
            "frame_order": index + 1,
            "skill_array": self._sim_skill_array_for_payload(skill_ids),
            "speed": _as_int(stats.get("speed")),
            "stamina": _as_int(stats.get("stamina")),
            "pow": _as_int(stats.get("power") or stats.get("pow")),
            "guts": _as_int(stats.get("guts")),
            "wiz": _as_int(stats.get("wit") or stats.get("wiz")),
            "running_style": style_num,
            "race_dress_id": card_id,
            "chara_color_type": 0,
            "npc_type": 0 if player else 1,
            "final_grade": 0,
            "popularity": max(1, int(popularity or 1)),
            "popularity_mark_rank_array": [0, max(1, int(popularity or 1)), 0],
            "proper_distance_short": self._aptitude_payload_value("sprint"),
            "proper_distance_mile": self._aptitude_payload_value("mile"),
            "proper_distance_middle": self._aptitude_payload_value("medium"),
            "proper_distance_long": self._aptitude_payload_value("long"),
            "proper_running_style_nige": self._aptitude_payload_value("front"),
            "proper_running_style_senko": self._aptitude_payload_value("pace"),
            "proper_running_style_sashi": self._aptitude_payload_value("late"),
            "proper_running_style_oikomi": self._aptitude_payload_value("end"),
            "proper_ground_turf": self._aptitude_payload_value("turf"),
            "proper_ground_dirt": self._aptitude_payload_value("dirt"),
            "motivation": _as_int(self.state.get("motivation"), 3) if player else 3,
            "mob_id": 0 if player else 100000 + int(index),
            "win_saddle_id_array": [],
            "race_result_array": [{"program_id": 0, "result_rank": int(finish_rank or 1)}],
            "simulated": True,
        }

    def _payload_opponent_row_from_sample(self, opponent, *, index, finish_rank):
        stats = opponent.get("stats") or {}
        aptitudes = opponent.get("aptitudes") or {}
        skill_ids = opponent.get("skill_ids") or [
            row.get("skill_id") for row in (opponent.get("skill_array") or []) if isinstance(row, dict)
        ]

        def aptitude(key, default=7):
            return _as_int(aptitudes.get(key), default)

        running_style = _as_int(opponent.get("running_style"), 2)
        card_id = _as_int(opponent.get("card_id"))
        chara_id = _as_int(opponent.get("chara_id") or opponent.get("single_mode_chara_id"), 9000 + int(index))
        return {
            "viewer_id": 0,
            "trainer_name": f"SIM_FIELD_{index}",
            "owner_trainer_name": "SIM_FIELD",
            "single_mode_chara_id": _as_int(opponent.get("single_mode_chara_id"), chara_id),
            "trained_chara_id": _as_int(opponent.get("trained_chara_id")),
            "card_id": card_id,
            "chara_id": chara_id,
            "rarity": _as_int(opponent.get("rarity"), 3),
            "talent_level": _as_int(opponent.get("talent_level"), 3),
            "frame_order": _as_int(opponent.get("frame_order"), index + 1),
            "skill_array": self._sim_skill_array_for_payload(skill_ids),
            "speed": _as_int(stats.get("speed")),
            "stamina": _as_int(stats.get("stamina")),
            "pow": _as_int(stats.get("power") or stats.get("pow")),
            "guts": _as_int(stats.get("guts")),
            "wiz": _as_int(stats.get("wit") or stats.get("wiz")),
            "running_style": running_style,
            "race_dress_id": card_id,
            "chara_color_type": _as_int(opponent.get("chara_color_type")),
            "npc_type": _as_int(opponent.get("npc_type"), 1),
            "final_grade": _as_int(opponent.get("final_grade")),
            "popularity": _as_int(opponent.get("popularity"), index + 1),
            "popularity_mark_rank_array": opponent.get("popularity_mark_rank_array") or [0, _as_int(opponent.get("popularity"), index + 1), 0],
            "proper_distance_short": aptitude("sprint"),
            "proper_distance_mile": aptitude("mile"),
            "proper_distance_middle": aptitude("medium"),
            "proper_distance_long": aptitude("long"),
            "proper_running_style_nige": aptitude("front"),
            "proper_running_style_senko": aptitude("pace"),
            "proper_running_style_sashi": aptitude("late"),
            "proper_running_style_oikomi": aptitude("end"),
            "proper_ground_turf": aptitude("turf"),
            "proper_ground_dirt": aptitude("dirt"),
            "motivation": _as_int(opponent.get("motivation"), 3),
            "mob_id": _as_int(opponent.get("mob_id"), 100000 + int(index)),
            "win_saddle_id_array": opponent.get("win_saddle_id_array") or [],
            "race_result_array": [{"program_id": 0, "result_rank": int(finish_rank or 1)}],
            "simulated": True,
            "synthetic_source": "observed_field_sample",
        }

    def _observed_opponent_rows_for_payload(self, *, program_id, player_rank):
        fields = list(self.race_fields_by_pid.get(int(program_id or 0), []))
        if not fields:
            return []
        sample = self.rng.choice(fields)
        opponents = list((sample or {}).get("opponents") or [])
        if not opponents:
            return []
        used_ranks = {int(player_rank or 1)}
        next_rank = 1
        rows = []
        for index, opponent in enumerate(opponents[:17], start=1):
            while next_rank in used_ranks:
                next_rank += 1
            used_ranks.add(next_rank)
            rows.append(self._payload_opponent_row_from_sample(
                opponent,
                index=index,
                finish_rank=next_rank,
            ))
            next_rank += 1
        return rows

    def _synthetic_opponent_rows(self, *, threshold, player_rank, race_style, program_id=None):
        observed = self._observed_opponent_rows_for_payload(
            program_id=program_id,
            player_rank=player_rank,
        )
        if observed:
            return observed
        opponents = []
        used_ranks = {int(player_rank or 1)}
        next_rank = 1
        for idx in range(1, 9):
            while next_rank in used_ranks:
                next_rank += 1
            used_ranks.add(next_rank)
            multiplier = 0.90 + (idx % 4) * 0.035 + self.rng.uniform(-0.045, 0.055)
            stats = {
                "speed": max(1, int(threshold["speed"] * multiplier)),
                "stamina": max(1, int(threshold["stamina"] * multiplier)),
                "power": max(1, int(threshold["power"] * multiplier)),
                "guts": max(1, int(threshold["guts"] * multiplier)),
                "wit": max(1, int(threshold["wit"] * multiplier)),
            }
            style_num = 1 + ((idx - 1) % 4)
            opponents.append(self._synthetic_race_horse_row(
                index=idx,
                stats=stats,
                running_style=STYLE_NUM_TO_KEY.get(style_num, race_style),
                finish_rank=next_rank,
                player=False,
                skill_ids=[],
                popularity=idx + 1,
            ))
            next_rank += 1
        return opponents

    def _synthetic_hakuraku_race_payload(self, race_entry, *, threshold, finish_rank):
        meta = race_entry.get("race") or {}
        player_stats = race_entry.get("pre_race_stats") or self._current_race_stats()
        skill_ids = race_entry.get("pre_race_skill_ids") or []
        style = race_entry.get("running_style") or self._race_style()
        player = self._synthetic_race_horse_row(
            index=0,
            stats=player_stats,
            running_style=style,
            finish_rank=finish_rank,
            player=True,
            skill_ids=skill_ids,
            popularity=1,
        )
        horses = [player] + self._synthetic_opponent_rows(
            threshold=threshold,
            player_rank=finish_rank,
            race_style=style,
            program_id=race_entry.get("pid"),
        )
        current_turn = _as_int(race_entry.get("turn") or self.state.get("turn"))
        race_history = list(self._sim_race_history())
        race_history.append({
            "turn": current_turn,
            "program_id": _as_int(race_entry.get("pid")),
            "race_name": race_entry.get("name"),
            "result_rank": int(finish_rank or 1),
            "running_style": STYLE_KEY_TO_NUM.get(_style_key(style), 2),
            "source": "simulated_race",
        })
        start_info = {
            "random_seed": self.rng.randrange(1, 2_147_483_647),
            "season": 1 + ((max(1, current_turn) - 1) // 12) % 4,
            "weather": 1,
            "ground_condition": 1,
            "continue_num": _as_int(race_entry.get("continue_attempts")),
        }
        reward_info = {
            "result_rank": int(finish_rank or 1),
            "gained_fans": self._race_fan_reward(meta.get("grade"), bool(race_entry.get("won"))),
            "skill_point": _as_int(race_entry.get("sp_reward")),
        }
        return {
            "format": "sweepy_hakuraku_race_v1",
            "horseACT_version": "sweepy-sim",
            "race_type": "Single",
            "synthetic": True,
            "simulation": {
                "model": race_entry.get("model"),
                "win_probability": race_entry.get("win_probability"),
                "race_score": race_entry.get("race_score"),
                "manual_race_model": race_entry.get("manual_race_model") or {},
            },
            "program_id": _as_int(race_entry.get("pid")),
            "current_turn": current_turn,
            "race": meta,
            "race_name": race_entry.get("name"),
            "race_instance_id": meta.get("race_instance_id"),
            "random_seed": start_info["random_seed"],
            "season": start_info["season"],
            "weather": start_info["weather"],
            "ground_condition": start_info["ground_condition"],
            "race_scenario": None,
            "race_horse_data_array": horses,
            "race_start_info": start_info,
            "race_reward_info": reward_info,
            "race_history": race_history,
            "career_report_result": {
                "turn": current_turn,
                "program_id": _as_int(race_entry.get("pid")),
                "finish_rank": int(finish_rank or 1),
                "won": bool(race_entry.get("won")),
                "status": "won" if race_entry.get("won") else "lost",
                "label": f"{'WON' if race_entry.get('won') else 'LOST'} #{int(finish_rank or 1)}",
                "is_g1": str(meta.get("grade") or "").upper() == "G1",
                "race": meta,
            },
        }

    def _simulate_race(self, pid, race_name, distance, era, rival=False):
        """Simulate a race outcome using observed game data when available."""
        pre_race_stats = dict(self._current_race_stats())
        pre_race_sp = int(self.state.get("skill_point") or 0)
        pre_race_skills = int(self.skills_bought or 0)
        prob, estimate = self._race_probability_estimate(
            pid,
            race_name,
            distance,
            era,
            skill_count=self.skills_bought,
        )
        race_model = dict(estimate or {})
        race_model.setdefault("model", "manual_threshold_probability")
        race_model["win_probability"] = round(float(prob or 0.0), 4)
        manual_probe = self._manual_threshold_probability_estimate(
            pid,
            race_name,
            distance,
            era,
            skill_count=self.skills_bought,
        )
        manual_model = dict(manual_probe[1]) if manual_probe else {}
        catalog_row = self.race_catalog_by_program_id.get(int(pid or 0)) or {}
        grade = catalog_row.get("type") or "G1"
        clean_lift_allowed = True
        clean_lift_block_reasons = []
        observed_runs = _as_int(race_model.get("observed_runs"))
        observed_win_rate = 1.0
        try:
            observed_win_rate = float(race_model.get("observed_win_rate") or 1.0)
        except (TypeError, ValueError):
            observed_win_rate = 1.0
        manual_threshold_safe = bool(race_model.get("manual_threshold_safe"))
        observed_min_runs = int(self.preset.get("sim_clean_record_observed_min_runs") or 6)
        observed_safe_rate = float(self.preset.get("sim_clean_record_min_observed_win_rate") or 0.88)
        if observed_runs >= observed_min_runs and observed_win_rate < observed_safe_rate and not manual_threshold_safe:
            clean_lift_allowed = False
            clean_lift_block_reasons.append(
                f"observed_win_rate {observed_win_rate:.3f} < {observed_safe_rate:.3f}"
            )
        if manual_model.get("stamina_critical"):
            clean_lift_allowed = False
            clean_lift_block_reasons.append("manual stamina critical")
        distance_key = _distance_key(distance)
        if distance_key == "long":
            try:
                true_stamina_ratio = float(manual_model.get("true_stamina_ratio") or 0.0)
                stamina_floor_ratio = float(manual_model.get("stamina_floor_ratio") or 0.0)
            except (TypeError, ValueError):
                true_stamina_ratio = stamina_floor_ratio = 0.0
            long_safe_ratio = max(
                stamina_floor_ratio,
                float(self.preset.get("sim_clean_record_long_stamina_safe_ratio") or 0.95),
            )
            if true_stamina_ratio > 0.0 and true_stamina_ratio < long_safe_ratio:
                clean_lift_allowed = False
                clean_lift_block_reasons.append(
                    f"long stamina ratio {true_stamina_ratio:.3f} < {long_safe_ratio:.3f}"
                )
        if (
            bool(self.preset.get("scheduled_race_clean_record_mode", True))
            and clean_lift_allowed
            and (
                bool(self.preset.get("sim_clean_record_all_scheduled", True))
                or str(grade or "").upper() == "G1"
                or int(self.state.get("turn") or 0) >= 60
            )
            and float(prob or 0.0) >= float(self.preset.get("sim_clean_record_safe_probability_threshold") or 0.63)
        ):
            lifted = max(
                float(prob or 0.0),
                float(self.preset.get("sim_clean_record_safe_win_probability") or 0.985),
            )
            if lifted > float(prob or 0.0):
                race_model["clean_record_probability_lift"] = True
                race_model["pre_lift_win_probability"] = round(float(prob or 0.0), 4)
                prob = lifted
                race_model["win_probability"] = round(float(prob or 0.0), 4)
        elif clean_lift_block_reasons:
            race_model["clean_record_probability_lift_blocked"] = clean_lift_block_reasons
        won = self.rng.random() <= float(prob or 0.0)

        continues_used = 0
        if (
            not won
            and bool(self.preset.get("sim_scheduled_race_continue_enabled", False))
            and bool(self.preset.get("scheduled_race_clean_record_mode", True))
        ):
            try:
                continue_limit = int(
                    self.preset.get("sim_scheduled_race_continue_limit")
                    or self.preset.get("clock_use_limit")
                    or self.preset.get("race_continue_limit")
                    or self.preset.get("alarm_clock_use_limit")
                    or 0
                )
            except (TypeError, ValueError):
                continue_limit = 0
            while not won and self.race_continues_used < continue_limit:
                retry_prob, retry_model = self._race_probability_estimate(
                    pid,
                    race_name,
                    distance,
                    era,
                    skill_count=self.skills_bought,
                )
                retry_model = dict(retry_model or {})
                self.race_continues_used += 1
                continues_used += 1
                race_model = retry_model
                prob = retry_prob
                won = self.rng.random() <= float(retry_prob or 0.0)

        finish_rank = 1 if won else self._sim_loss_finish_rank(prob, race_model)
        rival = self._is_rival_race(pid, explicit=rival)
        reward_multiplier = self._race_reward_multiplier(grade, rival=rival)
        # Support card race_bonus % stacks additively across the deck + friend
        # slot. Riko Kashimoto SSR MLB = 10, Smart Falcon SSR Power MLB = 10,
        # most Power/Stamina SSRs = 5-10. Per Erzzy's doc: "Race Bonus increases
        # the amount of stats and skill points you gain from finishing a race.
        # No rounding, 34% RB is the threshold for +1 all stats on mandatory."
        race_bonus_mult = self._deck_race_bonus_multiplier()
        sp_reward = self._race_sp_reward_value(
            grade=grade,
            won=won,
            pid=pid,
            race_name=race_name,
            turn=int(self.state.get("turn") or 0),
            rival=rival,
            reward_multiplier=reward_multiplier,
            race_bonus_mult=race_bonus_mult,
        )
        if rival:
            self.rival_races_run += 1
        sp_reward_unscaled = int(sp_reward)
        sp_scale = float(getattr(self, "race_sp_reward_scale", 1.0) or 1.0)
        sp_reward = max(1, int(round(sp_reward_unscaled * sp_scale))) if sp_reward_unscaled > 0 else 0
        self.state["mant_coin"] = int(self.state.get("mant_coin") or 0) + self._race_coin_reward(
            grade,
            won,
            rival=rival,
            reward_multiplier=reward_multiplier,
        )
        self.state["fans"] = int(self.state.get("fans") or 0) + self._race_fan_reward(grade, won)
        stat_allocations = {}
        if won:
            race_stat_gain = self._race_stat_total_gain(
                won=won,
                era=era,
                grade=grade,
                reward_multiplier=reward_multiplier,
                race_bonus_mult=race_bonus_mult,
                rival=rival,
            )
            stat_allocations = self._apply_random_race_stat_gain(race_stat_gain)
            self.race_names_won.add(str(race_name or "").strip())
            self._apply_epithet_bonuses_if_completed(reward_multiplier)
        # Twinkle Star Climax rewards fire after the race and scale with
        # support-card race bonus plus the active race-reward hammer.
        cur_turn = int(self.state.get("turn") or 0)
        if cur_turn in self._climax_turn_set:
            self._apply_climax_race_reward(cur_turn)
        self.state["skill_point"] += sp_reward
        self.sp_gain_sources["races"] += sp_reward
        self.state["hp"] = max(0, self.state["hp"] - 20)
        # Record the strat (running style) used for this race so the
        # calibrate output and any sim-vs-real diff analyzer can see what
        # style the bot's policy resolved to. Mirrors the live-bot turn-
        # data field `running_style_label`.
        from career_bot.race_schedule import running_style_label as _running_style_label
        _race_style_value = self._race_style()
        race_style_label = _running_style_label(_race_style_value)
        meta = self._sim_race_meta(pid, race_name, distance, grade=grade)
        threshold = self._sim_race_threshold_stats(pid, race_name, distance, era)
        race_entry = {
            "turn": self.state["turn"],
            "pid": pid,
            "name": race_name,
            "grade": grade,
            "race": meta,
            "finish_rank": finish_rank,
            "rival": rival,
            "won": won,
            "running_style": _race_style_value,
            "running_style_label": race_style_label,
            "model": (race_model or {}).get("model"),
            "win_probability": (race_model or {}).get("win_probability"),
            "race_score": (race_model or {}).get("current_score"),
            "race_model_details": race_model,
            "manual_race_model": manual_model,
            "reward_multiplier": round(reward_multiplier, 3),
            "pre_race_stats": pre_race_stats,
            "pre_race_sp": pre_race_sp,
            "sp_reward": sp_reward,
            "sp_reward_unscaled": sp_reward_unscaled,
            "sp_reward_scale": round(sp_scale, 4),
            "stat_allocations": dict(stat_allocations),
            "pre_race_skills_bought": pre_race_skills,
            "pre_race_skill_ids": [row.get("skill_id") for row in self.purchased_skills],
            "continued": continues_used > 0,
            "continue_attempts": continues_used,
        }
        race_entry["hakuraku_payload"] = self._synthetic_hakuraku_race_payload(
            race_entry,
            threshold=threshold,
            finish_rank=finish_rank,
        )
        self.races_run.append(race_entry)
        self.sim_hakuraku_races.append(race_entry["hakuraku_payload"])
        return won, sp_reward

    def _scheduled_race_at(self, turn):
        for row in self.scheduled_g1s:
            t, pid, name, dist, era = row[:5]
            style = row[5] if len(row) > 5 else ""
            rival = bool(row[6]) if len(row) > 6 else False
            if t == turn:
                return (pid, name, dist, era, style, rival)
        return None

    def _maybe_buy_skills(self, *, final=False, race_name=None, race_context=None):
        # Diagnostic mode: race the whole career with zero purchased skills
        # so race outcomes reflect raw stats/HP/pacing without skill margins
        # masking deficits. Used by the optimizer's --no-skills flag.
        if bool(self.preset.get("sim_disable_skill_purchases")):
            return
        sp = self.state["skill_point"]
        legacy = self.legacy_effects or {}
        hint_count = int(legacy.get("inherited_skill_hint_count") or 0)
        discount = min(35, hint_count * 2)
        if final:
            # Match real bot's `skill_point_drain_floor` (default 60 in
            # presets.py / runner.py) rather than the previous calibration
            # of 170. With keep_sp=170 the sim was leaving SP=197 unspent
            # while 45 affordable candidates sat in the pool (cheapest
            # ~120) — purely because 197-170=27 < 120. Lowering the
            # reserve to 60 lets the sim spend down to the same floor
            # the real bot tries to hit. `sim_final_skill_buy_max`
            # raised from 4 → 8 so the drain can actually clear the
            # remaining SP when several affordable skills exist.
            explicit_max_final = self.preset.get("sim_final_skill_buy_max")
            if explicit_max_final is not None:
                max_final = int(explicit_max_final or 0)
            else:
                max_final = max(8, self._sim_total_skill_purchase_max() - int(self.skills_bought or 0))
            keep_sp = int(self.preset.get("sim_final_skill_keep_sp") or 60)
            spendable = max(0, sp - keep_sp)
            if spendable <= 0 or max_final <= 0:
                return
            self._buy_simulated_skills(
                budget=spendable,
                max_count=max_final,
                phase="final",
                discount_pct=discount,
            )
            return
        # Pre-race buy. Real bot averages ~20 owned skills total across a
        # career — the sim's earlier defaults (4 pre-race × ~10 races = 40)
        # were ~2× too high. Lower defaults to 2 pre-race skills/race; the
        # auto-tuner can still raise via learned_hyperparameters.
        budget = self.preset.get("calendar_race_prebuy_budget", 520)
        learned = self.preset.get("learned_hyperparameters") or {}
        budget = int(learned.get("calendar_race_prebuy_budget", budget))
        reserve = int(learned.get("calendar_race_prebuy_keep_sp",
                                  self.preset.get("calendar_race_prebuy_keep_sp", 200)))
        max_skills = int(learned.get("calendar_race_prebuy_max_skills",
                                     self.preset.get("calendar_race_prebuy_max_skills", 2)))
        min_sp = int(self.preset.get("calendar_race_prebuy_min_sp", 280))
        if hint_count >= 8:
            max_skills += 1
        clean_record_mode = bool(self.preset.get("scheduled_race_clean_record_mode", True))
        race_grade = ""
        if clean_record_mode and race_context:
            pid = int((race_context or {}).get("pid") or 0)
            race_grade = str((self.race_catalog_by_program_id.get(pid) or {}).get("type") or "").upper()
            turn = int(self.state.get("turn") or 0)
            prob, _model = self._race_probability_estimate(
                pid,
                race_name,
                (race_context or {}).get("distance"),
                (race_context or {}).get("era"),
                skill_count=self.skills_bought,
            )
            danger = prob < float(self.preset.get("calendar_race_clean_prebuy_target_probability", 0.93))
            if danger or race_grade in {"G1", "G2"}:
                min_sp = min(min_sp, int(self.preset.get("calendar_race_clean_prebuy_min_sp", 120)))
                reserve = min(reserve, int(self.preset.get("calendar_race_clean_prebuy_keep_sp", 0)))
                budget = max(budget, int(self.preset.get("calendar_race_clean_prebuy_budget", 1000)))
                clean_max = int(self.preset.get("calendar_race_clean_prebuy_max_skills", 8))
                if race_grade == "G1" or danger:
                    max_skills = max(max_skills, min(clean_max, 5))
                else:
                    max_skills = max(max_skills, min(clean_max, 2))
        if sp < min_sp:
            return
        spendable = max(0, sp - reserve)
        actual_budget = min(spendable, budget)
        skill_cost = self._sim_skill_cost_floor(discount) or max(70, 100 - discount)
        max_affordable = min(max_skills, actual_budget // skill_cost)
        skills = max_affordable
        if clean_record_mode and race_context and actual_budget >= skill_cost:
            target = float(self.preset.get("calendar_race_clean_prebuy_target_probability", 0.93))
            pid = int((race_context or {}).get("pid") or 0)
            base_prob, _base_model = self._race_probability_estimate(
                pid,
                race_name,
                (race_context or {}).get("distance"),
                (race_context or {}).get("era"),
                skill_count=self.skills_bought,
            )
            min_required = 1 if race_grade in {"G1", "G2"} and base_prob < target else 0
            skills = 0
            while skills < max_affordable:
                prob, _model = self._race_probability_estimate(
                    pid,
                    race_name,
                    (race_context or {}).get("distance"),
                    (race_context or {}).get("era"),
                    skill_count=self.skills_bought + skills,
                )
                if prob >= target and skills >= min_required:
                    break
                skills += 1
        if race_name and "Kikuka" in str(race_name) and int(legacy.get("recovery_hint_count") or 0) > 0 and actual_budget >= skill_cost:
            skills = max(1, skills)
        if race_name and "Tenno Sho (Spring)" in str(race_name) and int(legacy.get("recovery_hint_count") or 0) > 0 and actual_budget >= skill_cost:
            skills = max(1, skills)
        if skills > 0:
            self._buy_simulated_skills(
                budget=actual_budget,
                max_count=skills,
                phase="pre_race",
                race_name=race_name,
                race_context=race_context,
                discount_pct=discount,
            )

    def _estimated_skill_rating_score(self):
        """Return exact simulated skill rating from purchased skill records."""
        return int(self.skill_rating_score or 0)

    def run(self):
        """Run a full 78-turn career and return a SimResult."""
        for turn in range(1, TURN_FINISH + 1):
            self.state["turn"] = turn
            if turn in {1, 31, 55}:
                self._apply_inheritance_event()
            self._simulate_observed_fixed_events_for_turn()
            self._expire_item_effects()
            self._maybe_buy_shop_items()
            final_climax = self._final_climax_races.get(turn)
            if final_climax:
                program_id, race_name, distance, era = final_climax
                previous_style = self._active_race_style
                self._active_race_style = self.default_style
                try:
                    self._maybe_use_pre_race_energy()
                    self._simulate_race(program_id, race_name, _distance_key(distance), era, rival=False)
                    self._simulate_turn_event()
                finally:
                    self._active_race_style = previous_style
                continue
            training_cmds = self._make_training_commands()
            commands = self._make_home_commands(training_cmds)
            self._score_all_commands(commands)
            sim_state = self._sim_state(commands)
            decision = self.strategy.next_decision(sim_state, self.preset)

            # Mirror the live runner's "items before command execution" pass:
            # inspect the chosen command, apply simulated item effects, then
            # ask the same strategy for the final command decision again.
            if decision.action == "command":
                chosen = self._command_from_decision(commands, decision)
                self._maybe_use_recovery_items()
                if int(chosen.get("command_type") or 0) == 1:
                    self._maybe_use_training_items(chosen, chosen.get("_strategy_score", 0.0))
                self._score_all_commands(commands)
                sim_state = self._sim_state(commands)
                decision = self.strategy.next_decision(sim_state, self.preset)

            if decision.action == "race":
                program_id = int((decision.payload or {}).get("program_id") or 0)
                entry = self._race_entry_for_program(program_id)
                previous_style = self._active_race_style
                self._active_race_style = _style_key(entry.get("style")) if entry.get("style") else self.default_style
                try:
                    self._maybe_use_pre_race_energy()
                    self._maybe_buy_skills(
                        race_name=entry.get("name"),
                        race_context={
                            "pid": program_id,
                            "distance": _distance_key(entry.get("distance")),
                            "era": entry.get("era") or _era_for_turn(turn),
                            "style": entry.get("style"),
                        },
                    )
                    self._simulate_race(
                        program_id,
                        entry.get("name"),
                        _distance_key(entry.get("distance")),
                        entry.get("era") or _era_for_turn(turn),
                        rival=bool(entry.get("rival")),
                    )
                    self._simulate_turn_event()
                finally:
                    self._active_race_style = previous_style
                continue

            if decision.action == "command":
                cmd = self._command_from_decision(commands, decision)
                command_type = int(cmd.get("command_type") or 0)
                command_id = int(cmd.get("command_id") or 0)
                command_group_id = int(cmd.get("command_group_id") or 0)
                effective_id = command_group_id if command_type == 3 and command_group_id else command_id
                if command_type == 1 and command_id in COMMAND_ID_TO_STAT:
                    self._simulate_turn_event()
                    self._record_training_decision(cmd)
                    self._apply_training(cmd)
                elif command_type == 7 and command_id == 701:
                    self._apply_rest()
                elif command_type == 3 and effective_id == 390:
                    self._apply_stat_friend_recreation()
                elif command_type == 3:
                    self._apply_recreation()
                else:
                    self._apply_rest()
                continue

            if decision.action in {"finish", "done"}:
                break

            # Events/race_progress/settle_state are API-state actions. The sim
            # does not synthesize those screens, so do a neutral recovery action
            # instead of inventing an API transition.
            self._apply_rest()

        # End-of-career skill drain
        self._maybe_buy_skills(final=True)

        final_stats = {
            "speed": self.state["speed"], "stamina": self.state["stamina"],
            "power": self.state["power"], "guts": self.state["guts"],
            "wit": self.state["wiz"],
        }
        stat_sum = sum(final_stats.values())
        rating = estimate_rating_score(
            final_stats,
            skill_score=self._estimated_skill_rating_score(),
            star_level=self.preset.get("sim_rating_star_level", 3),
            unique_level=self.preset.get("sim_rating_unique_level", 5),
        )
        return SimResult(
            final_stats=final_stats,
            stat_sum=stat_sum,
            rank=rating["rank"],
            rating_score=rating["total"],
            stat_rating_score=rating["stat_score"],
            unique_rating_bonus=rating["unique_bonus"],
            skill_rating_score=rating["skill_score"],
            g1_wins=sum(1 for r in self.races_run if str(r.get("grade") or "G1").upper() == "G1" and r["won"]),
            g1_losses=sum(1 for r in self.races_run if str(r.get("grade") or "G1").upper() == "G1" and not r["won"]),
            skills_bought=self.skills_bought,
            final_sp=self.state["skill_point"],
            final_hp=self.state["hp"],
            final_mood=self.state["motivation"],
            turns_logged=TURN_FINISH,
            races_run=list(self.races_run),
            train_picks_by_stat=dict(self.train_picks),
            bonus_fires=dict(self.bonus_fires),
            purchased_skills=list(self.purchased_skills),
            shop_items_bought=self.shop_items_bought,
            shop_items_used=self.shop_items_used,
            rival_races_run=self.rival_races_run,
            race_continues_used=self.race_continues_used,
            events_fired=list(self.events_fired),
            recreations_used=self.recreations_used,
            epithets_completed=list(self.epithets_completed),
            climax_bonus_races=self.climax_bonus_races,
            sp_gain_sources=dict(self.sp_gain_sources),
            fidelity_warnings=list(self.fidelity_warnings),
            training_decisions=list(self.training_decisions),
            sim_hakuraku_races=list(self.sim_hakuraku_races),
        )


def run_sweep(*, n_runs=20, preset, deck=None, seed_base=0, **kwargs):
    """Run N simulated careers and return aggregated stats."""
    project_root = kwargs.get("project_root") or Path(__file__).resolve().parents[1]
    preset = hydrate_preset_with_latest_session_context(preset, project_root)
    if deck is None and (preset.get("_sim_latest_session_context_source") and (preset.get("_run_context") or {}).get("support_cards")):
        deck = (preset.get("_run_context") or {}).get("support_cards")
    results = []
    for i in range(n_runs):
        sim = CareerSimulator(preset=copy.deepcopy(preset), deck=deck, seed=seed_base + i, **kwargs)
        results.append(sim.run())
    sums = [r.stat_sum for r in results]
    ratings = [r.rating_score for r in results]
    g1_wins = [r.g1_wins for r in results]
    ranks = [r.rank for r in results]
    from collections import Counter
    rank_dist = Counter(ranks)
    return {
        "n_runs": n_runs,
        "stat_sum_max": max(sums),
        "stat_sum_min": min(sums),
        "stat_sum_median": int(median(sums)),
        "stat_sum_mean": int(sum(sums)/len(sums)),
        "rating_score_max": max(ratings),
        "rating_score_min": min(ratings),
        "rating_score_median": int(median(ratings)),
        "rating_score_mean": int(sum(ratings)/len(ratings)),
        "g1_wins_median": int(median(g1_wins)),
        "rank_distribution": dict(rank_dist),
        "s_or_better_count": sum(
            count
            for rank, count in rank_dist.items()
            if RANK_ORDER_VALUE.get(rank, 0) >= RANK_ORDER_VALUE["S"]
        ),
        "results": results,
    }
