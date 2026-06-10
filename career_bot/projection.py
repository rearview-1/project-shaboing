"""Forward-projection planner for the strategy.

Computes per-stat gap-pressure from the schedule's upcoming races, the
trainee's personal growth, current bond states, and facility levels. The
strategy's scoring code consumes this projection to bias training picks
toward the highest-pressure gap, falling through to deck-natural spark
farming when all upcoming race floors are comfortably on track.

Designed to REPLACE the patchwork of competing bonuses
(_speed_priority_bonus, _stamina_priority_bonus, _checkpoint_pressure_bonus,
_manual_race_specific_demand_bonus, _scheduled_race_safety_bonus,
_knowledge_multiplier, _stat_concentration_bonus, _cap_pursuit_bonus,
_RACE_HARD_STAT_FLOORS) with one coherent source of truth.

Roll-out is phased — see `projection_phase` knob below.
"""
from __future__ import annotations

import json
from pathlib import Path


STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")
INVISIBLE_BONUS = 400              # +400 invisible career-mode bonus to every stat during races
SPARK_TARGET_RAW = 1100            # 3-star blue spark threshold
DEFAULT_LOOKAHEAD_TURNS = 18       # next-races window for primary pressure analysis
EXTENDED_LOOKAHEAD_TURNS = 36      # secondary "horizon" check for far races
DEFAULT_PROJECTION_CAP = 0.10      # Phase 1: small additive bonus on top of existing system
PHASE_2_PROJECTION_CAP = 0.40
PHASE_3_PROJECTION_CAP = 0.80      # full authority once redundant bonuses are disabled
DEFAULT_PRESSURE_PIVOT = 0.50      # below this pressure → safe to spark-farm


# ----- Cached data loaders --------------------------------------------------

_RACE_THRESHOLDS_CACHE: dict[str, dict] = {}
_GROWTH_RATES_CACHE: dict | None = None
_FACILITY_CURVES_CACHE: dict | None = None


def _load_race_thresholds(path):
    """Lazy-load and cache race_thresholds.json. Cushion-subtracted from `target_effective`."""
    key = str(path)
    if key in _RACE_THRESHOLDS_CACHE:
        return _RACE_THRESHOLDS_CACHE[key]
    try:
        with open(path, encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        _RACE_THRESHOLDS_CACHE[key] = {}
        return {}
    payload = raw.get("thresholds") or {}
    # Normalize keys to int and store target_effective minus invisible bonus
    # so the comparison happens in raw-stat space.
    result = {}
    for pid_str, info in payload.items():
        try:
            pid = int(pid_str)
        except (TypeError, ValueError):
            continue
        target_eff = info.get("target_effective") or {}
        raw_target = {
            stat: max(0, int((target_eff.get(stat) or 0)) - INVISIBLE_BONUS)
            for stat in STAT_KEYS
        }
        result[pid] = {
            "race_name": info.get("race_name", ""),
            "target_raw": raw_target,
            "target_effective": {stat: int(target_eff.get(stat) or 0) for stat in STAT_KEYS},
            "loss_count": int(info.get("loss_count") or 0),
            "primary_gap_history": info.get("primary_gap_stat_history") or {},
        }
    _RACE_THRESHOLDS_CACHE[key] = result
    return result


def _load_growth_rates(project_root):
    global _GROWTH_RATES_CACHE
    if _GROWTH_RATES_CACHE is not None:
        return _GROWTH_RATES_CACHE
    try:
        with open(Path(project_root) / "data" / "chara_growth_rates.json", encoding="utf-8") as fh:
            _GROWTH_RATES_CACHE = json.load(fh)
    except Exception:
        _GROWTH_RATES_CACHE = {}
    return _GROWTH_RATES_CACHE


def _load_facility_curves(project_root):
    global _FACILITY_CURVES_CACHE
    if _FACILITY_CURVES_CACHE is not None:
        return _FACILITY_CURVES_CACHE
    try:
        with open(Path(project_root) / "data" / "training_facility_curves.json", encoding="utf-8") as fh:
            _FACILITY_CURVES_CACHE = json.load(fh)
    except Exception:
        _FACILITY_CURVES_CACHE = {}
    return _FACILITY_CURVES_CACHE


# ----- Public helpers -------------------------------------------------------

def projection_phase(preset):
    """Phase 1 (additive) / 2 (weight-transfer) / 3 (full authority)."""
    raw = (preset or {}).get("projection_phase")
    try:
        phase = int(raw or 1)
    except (TypeError, ValueError):
        phase = 1
    return max(0, min(3, phase))


def projection_cap_for_phase(phase):
    return {0: 0.0, 1: DEFAULT_PROJECTION_CAP, 2: PHASE_2_PROJECTION_CAP, 3: PHASE_3_PROJECTION_CAP}.get(phase, DEFAULT_PROJECTION_CAP)


def projection_enabled(preset):
    return projection_phase(preset) >= 1


def _trainee_growth(growth_rates_data, chara_id):
    entry = (growth_rates_data or {}).get(str(chara_id)) or (growth_rates_data or {}).get(int(chara_id) if str(chara_id).isdigit() else chara_id)
    if not entry:
        return {stat: 0.0 for stat in STAT_KEYS}
    raw_g = entry.get("growth_rates") or {}
    return {stat: float(raw_g.get(stat) or 0) / 100.0 for stat in STAT_KEYS}


def _deck_card_types(preset):
    """Per-stat card count on the deck (excludes friend slot)."""
    cards = (preset.get("_run_context") or {}).get("support_cards") or []
    counts = {stat: 0 for stat in STAT_KEYS}
    for card in cards:
        if not isinstance(card, dict):
            continue
        ctype = str(card.get("type") or "").lower()
        # Normalize Wit/Wisdom/Intelligence -> "wit"
        if ctype in {"intelligence", "wisdom", "wiz"}:
            ctype = "wit"
        if ctype in counts:
            counts[ctype] += 1
    return counts


def _bonded_card_types(chara):
    """Set of stat types where the player has at least one card at bond >= 80.

    The bot's MantStrategy maintains partner bonds in `evaluation_info_array`,
    but here we approximate from the chara dict's training partner bonds when
    present. If the chara dict doesn't carry bond info, returns the empty set
    (projection conservatively assumes no rainbow available).
    """
    if not isinstance(chara, dict):
        return set()
    bonds = chara.get("evaluation_info_array") or []
    if not isinstance(bonds, list):
        return set()
    # Without a per-card type lookup at call-time, return raw count of high-bond
    # partners; callers can refine with the deck-type lookup.
    high_bond_partner_ids = set()
    for entry in bonds:
        if isinstance(entry, dict):
            ev = entry.get("evaluation") or entry.get("bond") or 0
            if int(ev or 0) >= 80:
                pid = entry.get("target_id") or entry.get("partner_id")
                if pid is not None:
                    high_bond_partner_ids.add(int(pid))
    return high_bond_partner_ids


def _current_raw_stat(chara, stat):
    if not isinstance(chara, dict):
        return 0
    if stat == "wit":
        # Game state uses "wiz" key for wit
        return int(chara.get("wiz") or chara.get("wit") or 0)
    return int(chara.get(stat) or 0)


def _race_thresholds_path(preset, project_root):
    """Resolve which race_thresholds.json to read for this preset's instance."""
    explicit = (preset or {}).get("race_thresholds_path")
    if explicit:
        return Path(explicit)
    runtime_paths = (preset or {}).get("auto_learning_runtime_paths") or []
    if isinstance(runtime_paths, str):
        runtime_paths = [runtime_paths]
    for root in runtime_paths:
        if root:
            candidate = Path(root) / "race_thresholds.json"
            if candidate.exists():
                return candidate
    # Fallback to project-data race_thresholds (rarely populated, but a sane default)
    return Path(project_root) / "uma_runtime" / "instances" / "account_b" / "race_thresholds.json"


# ----- Core projection ------------------------------------------------------

def build_projection(preset, chara, current_turn, project_root, *, lookahead=DEFAULT_LOOKAHEAD_TURNS):
    """Compute the forward projection for the current turn.

    Returns a dict shaped as:
      {
        "enabled": bool,
        "phase": int,
        "cap": float,
        "current_turn": int,
        "lookahead_window": int,
        "stats": {
          "<stat>": {
            "current_raw": int,
            "target_raw_max": int,       # max raw demand in lookahead window
            "gap": int,                  # max(0, target_raw_max - current_raw)
            "critical_race_turn": int,   # earliest scheduled race that drives this target
            "critical_race_name": str,
            "turns_until_critical": int,
            "throughput_estimate": float,# approx raw stat gain per training turn on this stat
            "turns_to_close": float,
            "pressure": float,           # turns_to_close / turns_until_critical, clamped [0,2]
            "is_spark_target": bool,
            "spark_gap": int,            # max(0, 1100 - current_raw) if deck-natural
          }
        },
        "primary_pressure_stat": str | None,
        "race_floors_on_track": bool,
        "spark_targets": [stat,...],
        "scheduled_races_in_window": [{turn, pid, name, target_raw, target_effective}],
      }
    """
    if not projection_enabled(preset):
        return {"enabled": False}

    current_turn = int(current_turn or 0)
    rt_path = _race_thresholds_path(preset, project_root)
    thresholds = _load_race_thresholds(rt_path)
    growth = _trainee_growth(
        _load_growth_rates(project_root),
        (preset.get("_run_context") or {}).get("trainee_card_id") or (preset.get("_run_context") or {}).get("chara_id"),
    )
    deck_counts = _deck_card_types(preset)
    bonded_partners = _bonded_card_types(chara)

    # Schedule lookup, restricted to upcoming-races within window
    sched = preset.get("custom_race_schedule") or []
    upcoming = []
    for entry in sched:
        try:
            t = int(entry.get("turn") or 0)
            pid = int(entry.get("program_id") or 0)
        except (TypeError, ValueError):
            continue
        if t <= current_turn:
            continue
        if t - current_turn > lookahead:
            continue
        if pid not in thresholds:
            continue
        ti = thresholds[pid]
        upcoming.append({
            "turn": t,
            "pid": pid,
            "name": entry.get("name") or ti.get("race_name", ""),
            "target_raw": dict(ti["target_raw"]),
            "target_effective": dict(ti["target_effective"]),
        })
    upcoming.sort(key=lambda r: r["turn"])

    # Per-stat gap analysis
    stats_out = {}
    primary = (None, -1.0)  # (stat, pressure)
    all_on_track = True

    for stat in STAT_KEYS:
        current = _current_raw_stat(chara, stat)
        # Max target across the window for this stat
        target_max = 0
        critical_race = None
        for r in upcoming:
            tgt = int(r["target_raw"].get(stat) or 0)
            if tgt > target_max:
                target_max = tgt
                critical_race = r
        gap = max(0, target_max - current)
        turns_until = max(1, (critical_race["turn"] - current_turn)) if critical_race else lookahead

        # Throughput estimate: rough avg per-turn raw stat gain when training this stat
        # Baseline: facility lv3 base × (1 + growth), with assumed mood/training bonuses
        # If a deck card of matching type is bonded -> double for rainbow
        # Conservative defaults; this is the throughput PROJECTION, not the actual game number
        base_per_lv = {"speed": 16, "stamina": 14, "power": 15, "guts": 12, "wit": 18}.get(stat, 14)
        growth_mult = 1.0 + float(growth.get(stat) or 0.0)
        rainbow_available = deck_counts.get(stat, 0) > 0 and len(bonded_partners) >= 1
        throughput_mult = 2.0 if rainbow_available else 1.0
        # Mood/training/partner approx multiplier
        approx_mult = 1.6
        throughput = base_per_lv * growth_mult * throughput_mult * approx_mult

        turns_to_close = (gap / throughput) if throughput > 0 else float("inf")
        if gap == 0:
            pressure = 0.0
        else:
            pressure = turns_to_close / float(turns_until)
            pressure = max(0.0, min(2.0, pressure))

        # Spark target: deck-natural stat (>=2 cards of this type) and current < 1100
        is_spark = deck_counts.get(stat, 0) >= 2
        spark_gap = max(0, SPARK_TARGET_RAW - current) if is_spark else 0

        stats_out[stat] = {
            "current_raw": current,
            "target_raw_max": target_max,
            "gap": gap,
            "critical_race_turn": critical_race["turn"] if critical_race else None,
            "critical_race_name": critical_race["name"] if critical_race else "",
            "turns_until_critical": turns_until if critical_race else None,
            "throughput_estimate": round(throughput, 2),
            "turns_to_close": round(turns_to_close, 2) if turns_to_close != float("inf") else None,
            "pressure": round(pressure, 3),
            "is_spark_target": is_spark,
            "spark_gap": spark_gap,
            "deck_card_count": deck_counts.get(stat, 0),
            "growth_rate": round(growth.get(stat) or 0.0, 3),
            "rainbow_available": rainbow_available,
        }
        if pressure > primary[1]:
            primary = (stat, pressure)
        # "On track" = pressure < 1 (we project to close the gap with turns to spare)
        if pressure >= 1.0:
            all_on_track = False

    spark_targets = [s for s, info in stats_out.items() if info["is_spark_target"]]
    cap = projection_cap_for_phase(projection_phase(preset))

    return {
        "enabled": True,
        "phase": projection_phase(preset),
        "cap": cap,
        "current_turn": current_turn,
        "lookahead_window": lookahead,
        "stats": stats_out,
        "primary_pressure_stat": primary[0] if primary[1] > 0 else None,
        "primary_pressure_value": round(primary[1], 3) if primary[1] >= 0 else 0.0,
        "race_floors_on_track": all_on_track,
        "spark_targets": spark_targets,
        "scheduled_races_in_window": upcoming,
        "deck_card_counts": deck_counts,
    }


def tile_bonus_from_projection(projection, primary_stat, *, secondary_stat=None, secondary_weight=0.3):
    """Compute the additive bonus this projection assigns to a training tile.

    `primary_stat` is the stat this tile primarily trains. `secondary_stat`
    (if provided) is the off-type stat gain (e.g. Power training also gives
    Stamina). Returns a value in [0, projection["cap"]].
    """
    if not projection or not projection.get("enabled"):
        return 0.0
    cap = float(projection.get("cap") or 0.0)
    if cap <= 0:
        return 0.0
    stats = projection.get("stats") or {}

    def _stat_pressure_or_spark(stat):
        if not stat or stat not in stats:
            return 0.0
        s = stats[stat]
        # Race-floor pressure dominates
        if s["gap"] > 0:
            # Pressure already clamped to [0, 2]; we normalize to bonus space.
            # pressure 1.0 -> uses full cap. pressure > 1 (uncloseable) -> cap.
            return min(1.0, s["pressure"]) * cap
        # No race-floor gap: optionally push toward spark target
        if s["is_spark_target"] and s["spark_gap"] > 0 and projection.get("race_floors_on_track"):
            # Mild secondary pressure scaled by spark_gap proportion
            spark_factor = min(1.0, s["spark_gap"] / SPARK_TARGET_RAW)
            return 0.4 * cap * spark_factor
        return 0.0

    bonus = _stat_pressure_or_spark(primary_stat)
    if secondary_stat:
        bonus += secondary_weight * _stat_pressure_or_spark(secondary_stat)
    return max(0.0, min(cap, bonus))


def summarize_projection(projection):
    """One-line human-readable summary for log/diagnostic output."""
    if not projection or not projection.get("enabled"):
        return "projection: disabled"
    parts = [
        f'T{projection["current_turn"]}',
        f'phase={projection["phase"]}',
        f'cap={projection["cap"]}',
    ]
    primary = projection.get("primary_pressure_stat")
    if primary:
        s = projection["stats"][primary]
        parts.append(
            f'primary={primary}(gap={s["gap"]},p={s["pressure"]},race={s["critical_race_name"]}@T{s["critical_race_turn"]})'
        )
    if projection.get("race_floors_on_track"):
        parts.append("floors_on_track")
    if projection.get("spark_targets"):
        parts.append(f'sparks={projection["spark_targets"]}')
    return "projection: " + " ".join(parts)
