"""Support-card training tile comparison utilities.

This module intentionally models a *single training click* instead of a whole
career. It is for answering questions like:

    "On this scenario's Speed Lv5 tile, is a 100% mood card better than a
    2-speed-bonus card for my deck?"

It reuses the simulator's uma.guide-derived card effect resolver so card
uniques, friendship folding, mood effect, training effect, stat bonuses, SP
bonus, growth, and item add-ons stay consistent with the career simulator.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from career_bot.career_simulator import _normalize_support_type, _uma_card_effect, _uma_el_level


STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")
GAIN_KEYS = (*STAT_KEYS, "sp", "energy")
FX_TO_BONUS_KEY = {
    1: "friendship_bonus",
    2: "mood_effect",
    3: "speed_bonus",
    4: "stamina_bonus",
    5: "power_bonus",
    6: "guts_bonus",
    7: "wit_bonus",
    8: "training_effectiveness",
    28: "energy_cost_reduction",
    30: "skill_pt_bonus",
}

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data"


@dataclass(frozen=True)
class TileComparisonResult:
    support_card_id: int
    name: str
    support_type: str
    rarity: str
    lb: int
    gains: dict[str, int]
    stat_sum: int
    weighted_score: float
    delta_vs_baseline: dict[str, int]
    score_delta_vs_baseline: float


class TrainingTileCalculator:
    """Lightweight one-tile calculator.

    This intentionally avoids constructing ``CareerSimulator`` so card ranking
    remains fast enough for interactive use.
    """

    def __init__(
        self,
        *,
        data_dir: Path = DEFAULT_DATA_DIR,
        training_curves: dict[str, Any] | None = None,
        scenario_key: str | None = None,
        scenario_effects: dict[str, Any] | None = None,
        active_scenario_effects: Iterable[str] | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.training_curves = training_curves or _load_json(data_dir / "training_facility_curves.json", {})
        self.support_bonus_data = _load_json(data_dir / "support_card_bonuses.json", {})
        self.support_train_data = _load_json(data_dir / "support_card_training_effects.json", {})
        self.scenario_key = str(scenario_key or "").strip()
        self.scenario_effects = resolve_scenario_effects(
            scenario_effects or _load_json(data_dir / "scenario_training_effects.json", {}),
            self.scenario_key,
            active_scenario_effects,
        )

    def tile_gain(
        self,
        deck: Iterable[int | tuple[int, int] | dict[str, Any]],
        training_stat: str,
        *,
        facility_level: int = 5,
        mood: float = 0.2,
        growth: dict[str, Any] | None = None,
        item_train_pct: float = 0,
        item_energy_pct: float = 0,
        npc: int = 0,
        bonded: bool = True,
        default_lb: int = 4,
        scenario_effects: Iterable[dict[str, Any]] | None = None,
    ) -> dict[str, int]:
        """Single tile gain using the same formula pinned by simulator tests."""
        import math

        growth = _coerce_growth(growth)
        training_key = _canonical_stat(training_stat)
        active_effects = [
            effect
            for effect in (scenario_effects if scenario_effects is not None else self.scenario_effects)
            if _scenario_effect_applies(
                effect,
                training_stat=training_key,
                facility_level=int(facility_level),
                mood=float(mood),
                bonded=bool(bonded),
            )
        ]
        facilities = (self.training_curves or {}).get("facilities") or {}
        base = dict((facilities.get(training_key) or {}).get(str(facility_level)) or {})
        _apply_base_scenario_effects(base, active_effects)
        friendship = 1.0
        mood_eff = train_eff = energy_red = wit_recovery = 0.0
        bonuses = {"speed": 0.0, "stamina": 0.0, "power": 0.0, "guts": 0.0, "wit": 0.0, "sp": 0.0}
        stat_fx = {"speed": 3, "stamina": 4, "power": 5, "guts": 6, "wit": 7, "sp": 30}
        normalized_deck = _normalize_deck(deck, default_lb)
        # Per-card friendship opt-out (uma.guide-style FB chip): dict rows may
        # carry fb=False to exclude that card from the friendship fold while
        # keeping its stat/mood/training-eff contributions.
        fb_off = {
            int(row.get("support_card_id") or row.get("card_id") or row.get("id") or 0)
            for row in (deck or [])
            if isinstance(row, dict) and row.get("fb") is False
        }
        bond_off = {
            int(row.get("support_card_id") or row.get("card_id") or row.get("id") or 0)
            for row in (deck or [])
            if isinstance(row, dict) and row.get("bond") is False
        }
        has_friendship_training = False
        for support_id, lb in normalized_deck:
            record = self.support_train_data.get(str(support_id))
            bonus_record = self.support_bonus_data.get(str(support_id)) or {}
            if not record and not bonus_record:
                continue
            card_bonded = bool(bonded) and support_id not in bond_off
            ctype = _normalize_support_type(bonus_record.get("type"))
            if record:
                level = _uma_el_level(lb, record.get("r"))
                matching = (int(record.get("t") or 0) == 3) or (ctype == training_key)
                card_effect = lambda fx: _uma_card_effect(record, fx, level, matching, bonded=card_bonded)
            else:
                matching = ctype == training_key or ctype in {"friend", "group"}
                card_effect = lambda fx: _bonus_record_effect(bonus_record, lb, FX_TO_BONUS_KEY.get(fx, ""), bonded=card_bonded)
            for stat, fx in stat_fx.items():
                bonuses[stat] += card_effect(fx)
            mood_eff += card_effect(2)
            train_eff += card_effect(8)
            energy_red += card_effect(28)
            if matching and card_bonded and support_id not in fb_off:
                has_friendship_training = True
                if training_key == "wit":
                    wit_recovery += _bonus_record_effect(
                        bonus_record,
                        lb,
                        "wit_friendship_recovery",
                        bonded=card_bonded,
                    )
                friend_val = card_effect(1)
                if friend_val > 0:
                    friendship *= 1.0 + friend_val / 100.0
        stat_bonus_effects, scalar_effects = _scenario_bonus_effects(active_effects)
        for stat, value in stat_bonus_effects.items():
            if stat in bonuses:
                bonuses[stat] += float(value)
        mood_eff += float(scalar_effects.get("mood_effect") or 0)
        train_eff += float(scalar_effects.get("training_effectiveness") or 0)
        energy_red += float(scalar_effects.get("energy_cost_reduction") or 0)
        # Scenario friendship bonuses slot into the friendship-training term.
        # They must not inflate a plain/no-card tile just because the UI's
        # global "bonded" toggle is on; the tile needs at least one matching
        # bonded support card to be a friendship training.
        if has_friendship_training:
            friendship *= float(scalar_effects.get("friendship_multiplier") or 1.0)
        count = len(normalized_deck) + int(npc)
        count += int(scalar_effects.get("support_count_add") or 0)
        mood_mult = 1.0 + float(mood) * (1.0 + mood_eff / 100.0)
        train_mult = 1.0 + train_eff / 100.0
        count_mult = 1.0 + 0.05 * count
        out: dict[str, int] = {}
        for stat in ("speed", "stamina", "power", "guts", "wit", "sp"):
            base_key = "skill_pt" if stat == "sp" else stat
            base_val = float(base.get(base_key) or 0)
            if base_val == 0:
                out[stat] = 0
                continue
            growth_mult = 1.0 if stat == "sp" else (1.0 + float(growth.get(stat, 0)) / 100.0)
            pre = math.floor((base_val + bonuses[stat]) * friendship * mood_mult * train_mult * count_mult * growth_mult)
            out[stat] = int(pre + math.floor(pre * float(item_train_pct) / 100.0))
        _apply_final_scenario_effects(out, active_effects)
        energy = float(base.get("energy") or 0)
        energy *= float(scalar_effects.get("energy_multiplier") or 1.0)
        energy += float(scalar_effects.get("energy_add") or 0)
        if training_key == "wit" and has_friendship_training:
            energy += wit_recovery
        w = energy * (1.0 - energy_red / 100.0) if energy < 0 else energy
        out["energy"] = int(math.floor(w - math.floor(abs(w) * float(item_energy_pct) / 100.0)) if w < 0 else int(w))
        return out


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _canonical_stat(value: str) -> str:
    key = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "spd": "speed",
        "sta": "stamina",
        "stam": "stamina",
        "pwr": "power",
        "gut": "guts",
        "int": "wit",
        "wiz": "wit",
        "wisdom": "wit",
        "skill_pt": "sp",
        "skill_points": "sp",
        "pt": "sp",
        "スピード": "speed",
        "スタミナ": "stamina",
        "パワー": "power",
        "根性": "guts",
        "賢さ": "wit",
        "スキルpt": "sp",
        "スキルPt": "sp",
    }
    return aliases.get(key, key)


def _canonical_gain_key(value: str) -> str:
    key = _canonical_stat(value)
    if key == "skill_pt":
        return "sp"
    return key


def _normalize_gain_map(raw: dict[str, Any] | None) -> dict[str, float]:
    out: dict[str, float] = {}
    for key, value in (raw or {}).items():
        canon = _canonical_gain_key(key)
        try:
            out[canon] = out.get(canon, 0.0) + float(value or 0)
        except (TypeError, ValueError):
            continue
    return out


def _scenario_record_matches(record: dict[str, Any], scenario_key: str) -> bool:
    if not scenario_key:
        return False
    target = str(scenario_key).strip().lower()
    names = [
        record.get("id"),
        record.get("scenario_id"),
        record.get("source_order_newest_first"),
        record.get("name"),
        *(record.get("aliases") or []),
    ]
    for name in names:
        if name is None:
            continue
        text = str(name).strip().lower()
        if text == target or (target and target in text):
            return True
    return False


def _iter_scenario_effect_records(data: dict[str, Any], scenario_key: str) -> list[dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    scenarios = data.get("scenarios") or {}
    records: list[dict[str, Any]] = []
    if isinstance(scenarios, dict):
        for key, record in scenarios.items():
            if isinstance(record, list):
                record = {"id": key, "effects": record}
            elif isinstance(record, dict):
                record = {"id": key, **record}
            else:
                continue
            if _scenario_record_matches(record, scenario_key):
                records.append(record)
    elif isinstance(scenarios, list):
        for record in scenarios:
            if isinstance(record, dict) and _scenario_record_matches(record, scenario_key):
                records.append(record)
    global_effects = data.get("global_effects") or data.get("effects")
    if global_effects:
        records.append({"id": "global", "effects": global_effects})
    return records


def resolve_scenario_effects(
    data: dict[str, Any],
    scenario_key: str | None,
    active_effect_ids: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Return active effect dicts for a scenario.

    Effects are opt-in by ID unless ``enabled_by_default`` is true. Passing
    ``all`` in active_effect_ids enables every effect for the matched scenario.
    """
    active_ids = {str(item).strip().lower() for item in (active_effect_ids or []) if str(item).strip()}
    enable_all = "all" in active_ids or "*" in active_ids
    effects: list[dict[str, Any]] = []
    for record in _iter_scenario_effect_records(data, str(scenario_key or "")):
        for effect in _as_list(record.get("effects")):
            if not isinstance(effect, dict):
                continue
            effect_id = str(effect.get("id") or effect.get("name") or "").strip()
            enabled_default = bool(effect.get("enabled_by_default"))
            if enable_all or enabled_default or (effect_id and effect_id.lower() in active_ids):
                effects.append(effect)
    return effects


def _scenario_effect_applies(
    effect: dict[str, Any],
    *,
    training_stat: str,
    facility_level: int,
    mood: float,
    bonded: bool,
) -> bool:
    conditions = effect.get("conditions") or effect.get("condition") or {}
    if not isinstance(conditions, dict):
        return True
    trainings = conditions.get("training") or conditions.get("trainings")
    if trainings:
        allowed = {_canonical_stat(str(item)) for item in _as_list(trainings)}
        if training_stat not in allowed and "all" not in allowed:
            return False
    min_level = conditions.get("facility_level_min", conditions.get("level_min"))
    max_level = conditions.get("facility_level_max", conditions.get("level_max"))
    exact_level = conditions.get("facility_level", conditions.get("level"))
    if exact_level is not None and int(facility_level) != int(exact_level):
        return False
    if min_level is not None and int(facility_level) < int(min_level):
        return False
    if max_level is not None and int(facility_level) > int(max_level):
        return False
    if conditions.get("bonded") is not None and bool(conditions.get("bonded")) != bool(bonded):
        return False
    if conditions.get("mood_min") is not None and float(mood) < float(conditions.get("mood_min")):
        return False
    if conditions.get("mood_max") is not None and float(mood) > float(conditions.get("mood_max")):
        return False
    return True


def _effect_apply(effect: dict[str, Any]) -> dict[str, Any]:
    apply = effect.get("apply") or {}
    return apply if isinstance(apply, dict) else {}


def _apply_base_scenario_effects(base: dict[str, Any], effects: Iterable[dict[str, Any]]) -> None:
    for effect in effects:
        apply = _effect_apply(effect)
        for stat, value in _normalize_gain_map(apply.get("base_add")).items():
            key = "skill_pt" if stat == "sp" else stat
            base[key] = float(base.get(key) or 0) + value
        multipliers = _normalize_gain_map(apply.get("base_multiplier"))
        all_mult = float((apply.get("base_multiplier") or {}).get("all") or 1.0) if isinstance(apply.get("base_multiplier"), dict) else 1.0
        for key in list(base.keys()):
            canon = _canonical_gain_key(key)
            mult = float(multipliers.get(canon, all_mult))
            if mult != 1.0:
                base[key] = float(base.get(key) or 0) * mult


def _scenario_bonus_effects(effects: Iterable[dict[str, Any]]) -> tuple[dict[str, float], dict[str, float]]:
    bonuses: dict[str, float] = {}
    scalars: dict[str, float] = {
        "mood_effect": 0.0,
        "training_effectiveness": 0.0,
        "energy_cost_reduction": 0.0,
        "energy_multiplier": 1.0,
        "energy_add": 0.0,
        "friendship_multiplier": 1.0,
        "support_count_add": 0.0,
    }
    for effect in effects:
        apply = _effect_apply(effect)
        stat_bonus = _normalize_gain_map(apply.get("stat_bonus"))
        for stat, value in stat_bonus.items():
            bonuses[stat] = bonuses.get(stat, 0.0) + value
        if "skill_pt_bonus" in apply:
            bonuses["sp"] = bonuses.get("sp", 0.0) + float(apply.get("skill_pt_bonus") or 0)
        for key in ("mood_effect", "training_effectiveness", "energy_cost_reduction", "energy_add", "support_count_add"):
            if key in apply:
                scalars[key] += float(apply.get(key) or 0)
        for key in ("energy_multiplier", "friendship_multiplier"):
            if key in apply:
                scalars[key] *= float(apply.get(key) or 1.0)
    return bonuses, scalars


def _apply_final_scenario_effects(out: dict[str, int], effects: Iterable[dict[str, Any]]) -> None:
    import math

    stat_cap = None
    skill_pt_cap = None
    for effect in effects:
        apply = _effect_apply(effect)
        multipliers = _normalize_gain_map(apply.get("final_multiplier"))
        all_mult = float((apply.get("final_multiplier") or {}).get("all") or 1.0) if isinstance(apply.get("final_multiplier"), dict) else 1.0
        for stat in ("speed", "stamina", "power", "guts", "wit", "sp"):
            mult = float(multipliers.get(stat, all_mult))
            if mult != 1.0:
                out[stat] = int(math.floor(float(out.get(stat) or 0) * mult))
        for stat, value in _normalize_gain_map(apply.get("final_add")).items():
            if stat in out:
                out[stat] = int(out.get(stat) or 0) + int(value)
        if apply.get("stat_gain_cap") is not None:
            value = int(float(apply.get("stat_gain_cap") or 0))
            stat_cap = value if stat_cap is None else max(stat_cap, value)
        if apply.get("skill_pt_gain_cap") is not None:
            value = int(float(apply.get("skill_pt_gain_cap") or 0))
            skill_pt_cap = value if skill_pt_cap is None else max(skill_pt_cap, value)
    if stat_cap is not None:
        for stat in ("speed", "stamina", "power", "guts", "wit"):
            out[stat] = min(int(out.get(stat) or 0), stat_cap)
    if skill_pt_cap is not None:
        out["sp"] = min(int(out.get("sp") or 0), skill_pt_cap)


def _coerce_growth(growth: dict[str, Any] | None) -> dict[str, float]:
    result: dict[str, float] = {}
    for key, value in (growth or {}).items():
        stat = _canonical_stat(key)
        if stat in STAT_KEYS:
            result[stat] = float(value or 0)
    return result


def _coerce_weights(weights: dict[str, Any] | None) -> dict[str, float]:
    result = {key: 1.0 for key in STAT_KEYS}
    result["sp"] = 0.5
    result["energy"] = 0.0
    for key, value in (weights or {}).items():
        stat = _canonical_stat(key)
        if stat in result:
            result[stat] = float(value)
    return result


def _score_gains(gains: dict[str, int], weights: dict[str, float]) -> float:
    return sum(float(gains.get(key) or 0) * float(weights.get(key, 0.0)) for key in GAIN_KEYS)


def _stat_sum(gains: dict[str, int]) -> int:
    return sum(int(gains.get(key) or 0) for key in STAT_KEYS)


def _normalize_deck(cards: Iterable[int | tuple[int, int] | dict[str, Any]], default_lb: int) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    seen: set[int] = set()
    for row in cards or []:
        if isinstance(row, dict):
            cid = int(row.get("support_card_id") or row.get("card_id") or row.get("id") or 0)
            lb = int(row.get("lb") if row.get("lb") is not None else row.get("lb_level") or default_lb)
        elif isinstance(row, (tuple, list)):
            cid = int(row[0] or 0)
            lb = int(row[1] if len(row) > 1 else default_lb)
        else:
            cid = int(row or 0)
            lb = default_lb
        if cid and cid not in seen:
            out.append((cid, max(0, min(4, lb))))
            seen.add(cid)
    return out


def _bonus_record_effect(record: dict[str, Any], lb: int, key: str, *, bonded: bool = True) -> float:
    """Fallback effect lookup from support_card_bonuses.json.

    The compact uma.guide table is preferred because it encodes the decompiled
    card curves. For newly released cards that exist only in the expanded
    lb_levels table, this keeps the simulator from silently dropping every card
    stat. Unconditional uniques are already merged into lb_levels by the
    extractor; only conditional decoded uniques are applied here.
    """
    if not record or not key:
        return 0.0
    try:
        target_lb = max(0, min(4, int(lb or 0)))
    except (TypeError, ValueError):
        target_lb = 4
    levels = record.get("lb_levels") or []
    row = next((item for item in levels if int((item or {}).get("lb") or 0) == target_lb), None)
    if row is None and levels:
        row = levels[min(target_lb, len(levels) - 1)]
    value = float((row or {}).get(key) or 0)
    for unique in record.get("unique_effects") or []:
        if str((unique or {}).get("condition") or "") != "bond_gte":
            continue
        if not bonded:
            continue
        grants = unique.get("grants") or {}
        try:
            value += float(grants.get(key) or 0)
        except (TypeError, ValueError):
            continue
    return value


def _training_curves_from_gamewith(data_dir: Path, selector: str) -> dict[str, Any] | None:
    data = _load_json(data_dir / "gamewith_scenario_training_curves.json", {})
    scenarios = data.get("scenarios") or []
    if not selector:
        return None
    selector_l = str(selector).strip().lower()
    for scenario in scenarios:
        if str(scenario.get("source_order_newest_first")) == selector_l:
            return {"facilities": scenario.get("facilities") or {}, "source": scenario.get("name")}
    for scenario in scenarios:
        name = str(scenario.get("name") or "")
        if selector_l in name.lower():
            return {"facilities": scenario.get("facilities") or {}, "source": name}
    return None


def load_training_curves(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    scenario: str | None = None,
    curves_path: Path | None = None,
) -> dict[str, Any]:
    if curves_path:
        curves = _load_json(curves_path, {})
        if "facilities" not in curves and "scenarios" in curves:
            raise ValueError(f"{curves_path} contains multiple scenarios; pass --scenario")
        return curves
    if scenario:
        curves = _training_curves_from_gamewith(data_dir, scenario)
        if curves:
            return curves
    return _load_json(data_dir / "training_facility_curves.json", {})


def make_training_calculator(
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    scenario: str | None = None,
    curves_path: Path | None = None,
    scenario_effects_path: Path | None = None,
    active_scenario_effects: Iterable[str] | None = None,
) -> TrainingTileCalculator:
    effect_data = _load_json(scenario_effects_path, {}) if scenario_effects_path else _load_json(data_dir / "scenario_training_effects.json", {})
    return TrainingTileCalculator(
        data_dir=data_dir,
        training_curves=load_training_curves(data_dir=data_dir, scenario=scenario, curves_path=curves_path),
        scenario_key=scenario,
        scenario_effects=effect_data,
        active_scenario_effects=active_scenario_effects,
    )


def tile_gain(
    deck: Iterable[int | tuple[int, int] | dict[str, Any]],
    training_stat: str,
    *,
    data_dir: Path = DEFAULT_DATA_DIR,
    scenario: str | None = None,
    curves_path: Path | None = None,
    scenario_effects_path: Path | None = None,
    active_scenario_effects: Iterable[str] | None = None,
    facility_level: int = 5,
    mood: float = 0.2,
    growth: dict[str, Any] | None = None,
    item_train_pct: float = 0,
    item_energy_pct: float = 0,
    npc: int = 0,
    bonded: bool = True,
    default_lb: int = 4,
) -> dict[str, int]:
    calc = make_training_calculator(
        data_dir=data_dir,
        scenario=scenario,
        curves_path=curves_path,
        scenario_effects_path=scenario_effects_path,
        active_scenario_effects=active_scenario_effects,
    )
    return calc.tile_gain(
        deck,
        _canonical_stat(training_stat),
        facility_level=int(facility_level),
        mood=float(mood),
        growth=_coerce_growth(growth),
        item_train_pct=float(item_train_pct),
        item_energy_pct=float(item_energy_pct),
        npc=int(npc),
        bonded=bool(bonded),
    )


def _card_meta(calc: TrainingTileCalculator, support_card_id: int) -> dict[str, str]:
    record = calc.support_bonus_data.get(str(support_card_id)) or {}
    train = calc.support_train_data.get(str(support_card_id)) or {}
    return {
        "name": str(record.get("name") or f"Support {support_card_id}"),
        "type": str(record.get("type") or train.get("t") or ""),
        "rarity": str(record.get("rarity") or train.get("r") or ""),
    }


def _candidate_ids(
    calc: TrainingTileCalculator,
    candidates: Iterable[int] | None,
    *,
    support_type: str | None = None,
    rarity: str | None = None,
    name_contains: str | None = None,
) -> list[int]:
    if candidates:
        ids = [int(cid) for cid in candidates if int(cid)]
    else:
        ids = [int(cid) for cid in calc.support_train_data.keys() if str(cid).isdigit()]
    type_filter = _canonical_stat(support_type or "")
    rarity_filter = str(rarity or "").strip().upper()
    name_filter = str(name_contains or "").strip().lower()
    out = []
    for cid in ids:
        meta = _card_meta(calc, cid)
        if type_filter and _canonical_stat(meta["type"]) != type_filter:
            continue
        if rarity_filter and meta["rarity"].upper() != rarity_filter:
            continue
        if name_filter and name_filter not in meta["name"].lower():
            continue
        out.append(cid)
    return sorted(set(out))


def rank_candidate_cards(
    *,
    baseline_deck: Iterable[int | tuple[int, int] | dict[str, Any]] = (),
    candidates: Iterable[int] | None = None,
    training_stat: str,
    data_dir: Path = DEFAULT_DATA_DIR,
    scenario: str | None = None,
    curves_path: Path | None = None,
    scenario_effects_path: Path | None = None,
    active_scenario_effects: Iterable[str] | None = None,
    facility_level: int = 5,
    mood: float = 0.2,
    growth: dict[str, Any] | None = None,
    item_train_pct: float = 0,
    item_energy_pct: float = 0,
    npc: int = 0,
    bonded: bool = True,
    default_lb: int = 4,
    candidate_lb: int = 4,
    weights: dict[str, Any] | None = None,
    support_type: str | None = None,
    rarity: str | None = None,
    name_contains: str | None = None,
) -> list[TileComparisonResult]:
    calc = make_training_calculator(
        data_dir=data_dir,
        scenario=scenario,
        curves_path=curves_path,
        scenario_effects_path=scenario_effects_path,
        active_scenario_effects=active_scenario_effects,
    )
    normalized_baseline = _normalize_deck(baseline_deck, default_lb)
    weight_map = _coerce_weights(weights)
    baseline_gain = calc.tile_gain(
        normalized_baseline,
        _canonical_stat(training_stat),
        facility_level=int(facility_level),
        mood=float(mood),
        growth=_coerce_growth(growth),
        item_train_pct=float(item_train_pct),
        item_energy_pct=float(item_energy_pct),
        npc=int(npc),
        bonded=bool(bonded),
    )
    baseline_score = _score_gains(baseline_gain, weight_map)
    baseline_ids = {cid for cid, _ in normalized_baseline}
    rows: list[TileComparisonResult] = []
    for cid in _candidate_ids(
        calc,
        candidates,
        support_type=support_type,
        rarity=rarity,
        name_contains=name_contains,
    ):
        if cid in baseline_ids:
            continue
        deck = [*normalized_baseline, (cid, max(0, min(4, int(candidate_lb))))]
        gains = calc.tile_gain(
            deck,
            _canonical_stat(training_stat),
            facility_level=int(facility_level),
            mood=float(mood),
            growth=_coerce_growth(growth),
            item_train_pct=float(item_train_pct),
            item_energy_pct=float(item_energy_pct),
            npc=int(npc),
            bonded=bool(bonded),
        )
        score = _score_gains(gains, weight_map)
        meta = _card_meta(calc, cid)
        rows.append(
            TileComparisonResult(
                support_card_id=cid,
                name=meta["name"],
                support_type=meta["type"],
                rarity=meta["rarity"],
                lb=max(0, min(4, int(candidate_lb))),
                gains=gains,
                stat_sum=_stat_sum(gains),
                weighted_score=round(score, 4),
                delta_vs_baseline={key: int(gains.get(key) or 0) - int(baseline_gain.get(key) or 0) for key in GAIN_KEYS},
                score_delta_vs_baseline=round(score - baseline_score, 4),
            )
        )
    rows.sort(key=lambda row: (row.weighted_score, row.stat_sum, row.support_card_id), reverse=True)
    return rows
