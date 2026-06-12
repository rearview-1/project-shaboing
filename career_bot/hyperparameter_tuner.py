"""Auto-tuning of scoring hyperparameters from observed career outcomes.

Commitment baked into this module:
  - **S+ rank is the floor.** Stat-sum target >= 4,480.
  - **SS is what the tuner climbs toward.** Stat-sum target >= 4,635.
  - **UG is the eventual ceiling.** Stat-sum target >= 4,865.

The module owns "what changes should the bot make to reach those
targets" so the operator no longer has to ask me to patch constants.

After each career, it:
  1. Pulls the last 20 finished careers + race attempt history.
  2. Computes signals: rank distribution, stat-sum percentiles, per-G1
     win rates, top-vs-bottom variance.
  3. Compares against the S floor and S+ target.
  4. Proposes adjustments. Step size **scales with gap to target** —
     small nudges when close, big jumps when 500+ points short.
  5. Detects "stuck": if median stat_sum hasn't moved up in 8 cycles,
     doubles the next step.
  6. Applies with hard floors/ceilings + writes a tune-log entry.

mant.py and runner.py honor `preset["learned_hyperparameters"]` so the
tuned values take effect on the next career.
"""

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median


MIN_CAREERS_FOR_TUNE = 4      # adapt sooner after deck/trainee/parent changes
RECENT_WINDOW = 20            # number of recent careers to summarize
STUCK_WINDOW = 8              # cycles without improvement before doubling step
LOG_FILENAME = "tune_log.jsonl"

# Stat-sum thresholds tied to in-game rank.
#
# CALIBRATED against the user's actual parent_library.json (154 parents
# with both `rank` ID and `stats`). Per-rank p25 stat_sum from that
# data:
#   rank 13 (A):   p25=3388, p50=3466, p75=3528
#   rank 14 (A+):  p25=3704, p50=3796, p75=3912
#   rank 15 (S):   p25=4075, p50=4298, p75=4384
#   rank 16 (S+):  p25=4483, p50=4535, p75=4647
#   rank 17 (SS):  p25=4635, p50=4657, p75=4809
#   rank 18 (UG):  p25=4865, p50=4901
#   rank 19 (UG2): p25=4879, p50=5016
#
# Thresholds set to p25 of each rank so we cross into the rank when at
# least 25% of historical parents at that rank had this stat_sum.
RANK_TARGETS = {
    "A":   3_400,
    "A+":  3_700,
    "S":   4_075,   # ← the S floor we commit to (rank-15 p25)
    "S+":  4_480,
    "SS":  4_635,
    "UG":  4_865,
}
S_FLOOR_STAT_SUM = RANK_TARGETS["S"]
SPLUS_TARGET_STAT_SUM = RANK_TARGETS["SS"]


def _rank_for_stat_sum(stat_sum):
    """Map a final stat sum to an approximate in-game rank label.
    Calibrated against user's parent_library.json (see RANK_TARGETS)."""
    if stat_sum >= RANK_TARGETS["UG"]:  return "UG"
    if stat_sum >= RANK_TARGETS["SS"]:  return "SS"
    if stat_sum >= RANK_TARGETS["S+"]:  return "S+"
    if stat_sum >= RANK_TARGETS["S"]:   return "S"
    if stat_sum >= RANK_TARGETS["A+"]:  return "A+"
    if stat_sum >= RANK_TARGETS["A"]:   return "A"
    return "B+"


# Each entry: (floor, ceiling, base_step, default).
# `base_step` is multiplied by a gap-to-target factor when the bot is
# far from S+, so big gaps produce big moves and small gaps produce
# small nudges.
#
# NOTE: with the forward-projection planner active (projection_phase ≥ 2),
# the priority-bonus knobs below have their CEILINGS lowered so the tuner
# can't push them back up to compete with the projection's authority.
# Phase 2: ceilings ≤ 0.10. Phase 3: ceilings = 0 (effectively disabled).
TUNABLE_PARAMS = {
    # Speed Priority bonus per phase — ceilings capped so they can't fight projection
    "speed_priority_bonus_early":  {"floor": 0.06, "ceiling": 0.10, "step": 0.01, "default": 0.06},
    "speed_priority_bonus_mid":    {"floor": 0.16, "ceiling": 0.45, "step": 0.01, "default": 0.16},
    "speed_priority_bonus_late":   {"floor": 0.22, "ceiling": 0.60, "step": 0.01, "default": 0.22},
    # Stamina + Power priority — same treatment
    "stamina_priority_bonus_base":    {"floor": 0.00, "ceiling": 0.25, "step": 0.01, "default": 0.03},
    "stamina_priority_deficit_boost": {"floor": 0.00, "ceiling": 0.25, "step": 0.01, "default": 0.03},
    "stamina_floor_target":           {"floor": 380,  "ceiling": 1100, "step": 25,   "default": 500},
    "power_priority_bonus_base":      {"floor": 0.00, "ceiling": 0.30, "step": 0.01, "default": 0.03},
    "power_priority_deficit_boost":   {"floor": 0.00, "ceiling": 0.30, "step": 0.01, "default": 0.03},
    "power_floor_target":             {"floor": 450,  "ceiling": 1200, "step": 25,   "default": 800},
    "speed_priority_deficit_scale":   {"floor": 0.40, "ceiling": 0.95, "step": 0.05, "default": 0.70},
    # Postmortem feedback strength — kept high, this feeds the projection's gap inputs indirectly
    "postmortem_bonus_cap":        {"floor": 0.08, "ceiling": 0.40, "step": 0.02, "default": 0.20},
    # Per-race manual demand — kept for legacy compat; projection is dominant
    "race_specific_demand_cap":    {"floor": 0.10, "ceiling": 0.40, "step": 0.02, "default": 0.25},
    # Race success learning
    "race_success_bonus_cap":      {"floor": 0.04, "ceiling": 0.20, "step": 0.02, "default": 0.10},
    # Checkpoint pressure base — projection supersedes; keep small
    "checkpoint_pressure_base":    {"floor": 0.04, "ceiling": 0.12, "step": 0.01, "default": 0.06},
    # Pre-race skill purchase per G1
    "calendar_race_prebuy_min_sp": {"floor": 80,   "ceiling": 450,  "step": 25,   "default": 280},
    "calendar_race_prebuy_budget": {"floor": 400,  "ceiling": 1800, "step": 75,   "default": 850},
    "calendar_race_prebuy_keep_sp": {"floor": 0,   "ceiling": 400,  "step": 25,   "default": 100},
    "calendar_race_prebuy_max_skills": {"floor": 2, "ceiling": 12,    "step": 1,    "default": 4},
    # PER-STAT soft caps: speed/power/wit at 1100 (high-priority, near-max
    # via training + race rewards); stamina/guts at 800 ("just enough").
    # Operator overrides any of these by listing the stat in
    # desired_parent_sparks.blue, which bumps the bot to 1100 for that stat.
    "speed_soft_cap":              {"floor": 1100, "ceiling": 1200, "step": 25,   "default": 1150},
    "power_soft_cap":              {"floor": 950,  "ceiling": 1200, "step": 25,   "default": 1100},
    "wit_soft_cap":                {"floor": 1100, "ceiling": 1200, "step": 25,   "default": 1150},
    "stamina_soft_cap":            {"floor": 500,  "ceiling": 1100, "step": 25,   "default": 800},
    "guts_soft_cap":               {"floor": 500,  "ceiling": 1100, "step": 25,   "default": 800},
    # Universal hard cap = game's 1200 stat ceiling (not really tunable)
    "stat_hard_cap":               {"floor": 1100, "ceiling": 1200, "step": 25,   "default": 1200},
    # Legacy wit_hard_cap kept for backward compat
    "wit_hard_cap":                {"floor": 1100, "ceiling": 1200, "step": 50,   "default": 1200},
    "wit_priority_bonus_early":    {"floor": 0.04, "ceiling": 0.10, "step": 0.01, "default": 0.04},
    "wit_priority_bonus_mid":      {"floor": 0.14, "ceiling": 0.55, "step": 0.01, "default": 0.14},
    "wit_priority_bonus_late":     {"floor": 0.30, "ceiling": 0.70, "step": 0.01, "default": 0.30},
    "wit_priority_target_raw":     {"floor": 1100, "ceiling": 1200, "step": 25,   "default": 1200},
    "wit_priority_floor_raw":      {"floor": 950,  "ceiling": 1150, "step": 25,   "default": 1050},
    # Recovery/action adaptation. These directly attack the observed A+
    # failure mode on race-heavy routes: too many full rest turns and too few
    # low-HP Wit/Riko recovery substitutes after deck changes.
    "rest_threshold":              {"floor": 24,   "ceiling": 75,   "step": 2,    "default": 48},
    # Structural policy levers (see mant._apply_visible_tile_quality_guard).
    # Tile scores run ~1.4-5.5; these need to be a meaningful fraction of
    # 1.0 to flip borderline picks. Defaults 0 = lever off until tuned.
    "rainbow_take_bonus":          {"floor": 0.0,  "ceiling": 2.5,  "step": 0.1,  "default": 0.0},
    "junior_bond_build_weight":    {"floor": 0.0,  "ceiling": 1.5,  "step": 0.1,  "default": 0.0},
    "junior_bond_build_end_turn":  {"floor": 20,   "ceiling": 40,   "step": 2,    "default": 30},
    "race_heavy_rest_threshold_penalty": {"floor": 4, "ceiling": 18, "step": 2,    "default": 4},
    "race_heavy_recreation_max_training_score": {"floor": 0.10, "ceiling": 0.45, "step": 0.03, "default": 0.18},
    "low_hp_wit_training_max_failure": {"floor": 18, "ceiling": 25, "step": 1,    "default": 25},
    "non_wit_high_value_training_max_failure": {"floor": 18, "ceiling": 24, "step": 1, "default": 24},
    "low_hp_wit_training_min_score": {"floor": 0.06, "ceiling": 0.22, "step": 0.02, "default": 0.08},
    "low_hp_wit_training_substitute_min_score": {"floor": 0.01, "ceiling": 0.08, "step": 0.01, "default": 0.01},
    "stat_friend_recreation_max_vital": {"floor": 60, "ceiling": 85, "step": 5, "default": 80},
    "stat_friend_recreation_force_vital": {"floor": 35, "ceiling": 60, "step": 5, "default": 35},
    "stat_friend_recreation_max_training_score": {"floor": 0.42, "ceiling": 1.05, "step": 0.08, "default": 0.75},
    "stat_friend_recreation_score_cap_bonus": {"floor": 0.06, "ceiling": 0.25, "step": 0.03, "default": 0.10},
}


def _safe_float(v, default=0.0):
    try: return float(v)
    except (TypeError, ValueError): return default


def _safe_int(v, default=0):
    try: return int(v)
    except (TypeError, ValueError): return default


def _find_wit(turns):
    for t in reversed(turns):
        s = t.get("stats") or {}
        for k in ("wiz", "wit", "wisdom"):
            v = s.get(k)
            if v: return int(v)
    return 0


def _race_counts_from_log(turns):
    seen = set()
    wins = 0
    losses = 0
    g1_wins = 0
    g1_losses = 0
    for turn in turns or []:
        events = list(turn.get("events") or [])
        for event in events:
            if not isinstance(event, dict) or event.get("event") != "race_result":
                continue
            key = (_safe_int(event.get("turn") or turn.get("turn")), _safe_int(event.get("program_id")))
            if key in seen:
                continue
            seen.add(key)
            rank = _safe_int(event.get("finish_rank") or event.get("rank") or event.get("result_rank"))
            won = bool(event.get("won")) if event.get("won") is not None else rank == 1
            is_g1 = bool(event.get("is_g1")) or str(((event.get("race") or {}).get("grade") or "")).upper() == "G1"
            if won:
                wins += 1
                if is_g1:
                    g1_wins += 1
            elif rank > 1 or event.get("won") is False:
                losses += 1
                if is_g1:
                    g1_losses += 1
    return wins, losses, g1_wins, g1_losses


def _race_program_ids_from_log(turns):
    rows = []
    for turn in turns or []:
        for event in turn.get("events") or []:
            if not isinstance(event, dict) or event.get("event") != "race_result":
                continue
            program_id = _safe_int(event.get("program_id") or ((event.get("race") or {}).get("program_id")))
            if program_id:
                rows.append(program_id)
    return rows


_TRAINING_COMMAND_TO_STAT = {
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


def _action_counts_from_log(turns):
    actions = Counter()
    training_stats = Counter()
    for turn in turns or []:
        selected = str(turn.get("selected_action") or "")
        cmd = turn.get("current_command") or {}
        if selected == "race" or (isinstance(cmd, dict) and cmd.get("program_id")):
            actions["race"] += 1
            continue
        if selected == "finish":
            actions["finish"] += 1
            continue
        if not isinstance(cmd, dict):
            continue
        command_type = _safe_int(cmd.get("command_type"))
        command_id = _safe_int(cmd.get("command_id"))
        command_group_id = _safe_int(cmd.get("command_group_id"))
        select_id = _safe_int(cmd.get("select_id"))
        if command_type == 1 and command_id in _TRAINING_COMMAND_TO_STAT:
            actions["train"] += 1
            training_stats[_TRAINING_COMMAND_TO_STAT[command_id]] += 1
        elif command_type == 7 and command_id == 701:
            actions["rest"] += 1
        elif command_type == 3:
            if command_group_id == 390 or select_id >= 9000:
                actions["stat_friend_recreation"] += 1
            else:
                actions["recreation"] += 1
        elif command_type == 8:
            actions["medic"] += 1
    return actions, training_stats


def _deck_type_counts(run_context):
    counts = Counter()
    for card in (run_context or {}).get("support_cards") or []:
        if not isinstance(card, dict):
            continue
        kind = str(card.get("type") or "").strip().lower()
        if kind:
            counts[kind] += 1
    friend_type = str(((run_context or {}).get("friend_card") or {}).get("type") or "").strip().lower()
    if friend_type:
        counts[friend_type] += 1
    return counts


def _load_recent_careers(bot_logs_dir, n=RECENT_WINDOW):
    bot_logs_dir = Path(bot_logs_dir)
    if not bot_logs_dir.exists():
        return []
    log_files = sorted(
        bot_logs_dir.glob("career_log_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    careers = []
    for path in log_files:
        if len(careers) >= n: break
        try: log = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError): continue
        if log.get("status") != "finished": continue
        turns = log.get("turns") or []
        if not turns: continue
        last = turns[-1]
        s = last.get("stats") or {}
        wit = _find_wit(turns)
        spd = _safe_int(s.get("speed"))
        sta = _safe_int(s.get("stamina"))
        pwr = _safe_int(s.get("power"))
        guts = _safe_int(s.get("guts"))
        stat_sum = spd + sta + pwr + guts + wit
        race_wins, race_losses, g1_wins, g1_losses = _race_counts_from_log(turns)
        action_counts, training_counts = _action_counts_from_log(turns)
        run_context = log.get("run_context") or {}
        deck_counts = _deck_type_counts(run_context)
        careers.append({
            "ended_at": log.get("ended_at", ""),
            "preset_name": log.get("preset_name") or "",
            "run_context": run_context,
            "race_program_ids": _race_program_ids_from_log(turns),
            "speed": spd, "stamina": sta, "power": pwr, "guts": guts, "wit": wit,
            "stat_sum": stat_sum,
            "rank": _rank_for_stat_sum(stat_sum),
            "final_turn": _safe_int(log.get("final_turn")),
            "race_wins": race_wins,
            "race_losses": race_losses,
            "g1_wins": g1_wins,
            "g1_losses": g1_losses,
            "rest_count": _safe_int(action_counts.get("rest")),
            "recreation_count": _safe_int(action_counts.get("recreation")),
            "stat_friend_recreation_count": _safe_int(action_counts.get("stat_friend_recreation")),
            "medic_count": _safe_int(action_counts.get("medic")),
            "training_count": _safe_int(action_counts.get("train")),
            "speed_training_count": _safe_int(training_counts.get("speed")),
            "stamina_training_count": _safe_int(training_counts.get("stamina")),
            "power_training_count": _safe_int(training_counts.get("power")),
            "guts_training_count": _safe_int(training_counts.get("guts")),
            "wit_training_count": _safe_int(training_counts.get("wit")),
            "deck_speed_count": _safe_int(deck_counts.get("speed")),
            "deck_stamina_count": _safe_int(deck_counts.get("stamina")),
            "deck_power_count": _safe_int(deck_counts.get("power")),
            "deck_guts_count": _safe_int(deck_counts.get("guts")),
            "deck_wit_count": _safe_int(deck_counts.get("wit")),
            "deck_pal_count": _safe_int(deck_counts.get("pal")),
        })
    return careers


def _context_adapt_careers(careers, preset):
    careers = list(careers or [])
    preset = preset if isinstance(preset, dict) else {}
    enabled = bool(preset.get("learning_context_adaptation_enabled", True))
    if not enabled or not careers:
        return careers, {
            "enabled": enabled,
            "mode": "disabled" if not enabled else "empty",
            "career_count": len(careers),
            "selected_count": len(careers),
        }
    try:
        from career_bot.learning import (
            _preset_validation_context,
            _sample_validation_match_score,
            context_fingerprint_from_validation_context,
        )
    except Exception:
        return careers, {
            "enabled": True,
            "mode": "global_fallback_import_failed",
            "career_count": len(careers),
            "selected_count": len(careers),
        }
    anchor = _preset_validation_context(preset)
    exact_threshold = _safe_int(preset.get("learning_context_exact_match_score"), 28)
    similar_threshold = _safe_int(preset.get("learning_context_similar_match_score"), 14)
    min_exact = max(1, _safe_int(preset.get("learning_context_min_exact_samples"), 4))
    min_similar = max(min_exact, _safe_int(preset.get("learning_context_min_similar_samples"), 8))
    exact = []
    similar = []
    max_score = 0
    for career in careers:
        sample_like = {
            "preset_name": career.get("preset_name") or "",
            "run_context": career.get("run_context") or {},
            "race_results": [{"program_id": pid} for pid in career.get("race_program_ids") or []],
        }
        score = _sample_validation_match_score(anchor, sample_like)
        max_score = max(max_score, score)
        if score >= exact_threshold:
            exact.append(career)
        if score >= similar_threshold:
            similar.append(career)
    if len(exact) >= min_exact:
        selected = exact
        mode = "exact_context"
    elif len(similar) >= min_similar:
        selected = similar
        mode = "similar_context"
    else:
        selected = careers
        mode = "global_fallback"
    return selected, {
        "enabled": True,
        "mode": mode,
        "anchor": context_fingerprint_from_validation_context(anchor),
        "career_count": len(careers),
        "selected_count": len(selected),
        "exact_count": len(exact),
        "similar_count": len(similar),
        "max_match_score": max_score,
        "exact_threshold": exact_threshold,
        "similar_threshold": similar_threshold,
        "min_exact_samples": min_exact,
        "min_similar_samples": min_similar,
    }


def _load_race_history(history_path):
    history_path = Path(history_path)
    if not history_path.exists(): return {}
    try: return json.loads(history_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError): return {}


def _read_tune_log_tail(log_path, n=STUCK_WINDOW):
    """Read the last N entries from the tune log to detect stuck cycles."""
    log_path = Path(log_path) if log_path else None
    if not log_path or not log_path.exists():
        return []
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    return [json.loads(l) for l in lines[-n:] if l.strip()]


def summarize_recent_outcomes(careers, race_history):
    if not careers:
        return {"n_careers": 0}

    sums = [c["stat_sum"] for c in careers]
    careers_sorted = sorted(careers, key=lambda c: c["stat_sum"])
    n = len(careers_sorted)
    q = n // 4 or 1
    bottom = careers_sorted[:q]
    top = careers_sorted[-q:]

    def _median_key(rows, key):
        if not rows:
            return 0
        return int(median(_safe_int(c.get(key)) for c in rows))

    rank_counts = {}
    for c in careers:
        rank_counts[c["rank"]] = rank_counts.get(c["rank"], 0) + 1

    summary = {
        "n_careers": n,
        "stat_sum_median": int(median(sums)),
        "stat_sum_mean": int(mean(sums)),
        "stat_sum_max": int(max(sums)),
        "stat_sum_p25": int(median(c["stat_sum"] for c in bottom)),
        "stat_sum_p75": int(median(c["stat_sum"] for c in top)),
        "speed_median": int(median(c["speed"] for c in careers)),
        "stamina_median": int(median(c["stamina"] for c in careers)),
        "power_median": int(median(c["power"] for c in careers)),
        "guts_median": int(median(c["guts"] for c in careers)),
        "wit_median": int(median(c["wit"] for c in careers)),
        "speed_top_vs_bottom_delta": int(median(c["speed"] for c in top)) - int(median(c["speed"] for c in bottom)),
        "stamina_top_vs_bottom_delta": int(median(c["stamina"] for c in top)) - int(median(c["stamina"] for c in bottom)),
        "power_top_vs_bottom_delta": int(median(c["power"] for c in top)) - int(median(c["power"] for c in bottom)),
        "wit_top_vs_bottom_delta": int(median(c["wit"] for c in top)) - int(median(c["wit"] for c in bottom)),
        "rank_distribution": rank_counts,
        "s_or_better_count": sum(rank_counts.get(r, 0) for r in ("S", "S+", "SS", "SS+", "UG")),
        "sub_s_count": sum(rank_counts.get(r, 0) for r in ("B+", "A", "A+")),
        "race_wins_total": sum(_safe_int(c.get("race_wins")) for c in careers),
        "race_losses_total": sum(_safe_int(c.get("race_losses")) for c in careers),
        "race_losses_median": int(median(_safe_int(c.get("race_losses")) for c in careers)),
        "clean_career_count": sum(1 for c in careers if _safe_int(c.get("race_wins")) > 0 and _safe_int(c.get("race_losses")) == 0),
        "g1_losses_total": sum(_safe_int(c.get("g1_losses")) for c in careers),
        "rest_median": _median_key(careers, "rest_count"),
        "rest_top_vs_bottom_delta": _median_key(bottom, "rest_count") - _median_key(top, "rest_count"),
        "stat_friend_recreation_median": _median_key(careers, "stat_friend_recreation_count"),
        "stat_friend_recreation_top_vs_bottom_delta": _median_key(top, "stat_friend_recreation_count") - _median_key(bottom, "stat_friend_recreation_count"),
        "medic_median": _median_key(careers, "medic_count"),
        "speed_training_median": _median_key(careers, "speed_training_count"),
        "wit_training_median": _median_key(careers, "wit_training_count"),
        "power_training_median": _median_key(careers, "power_training_count"),
        "stamina_training_median": _median_key(careers, "stamina_training_count"),
        "deck_speed_median": _median_key(careers, "deck_speed_count"),
        "deck_wit_median": _median_key(careers, "deck_wit_count"),
        "deck_pal_median": _median_key(careers, "deck_pal_count"),
        "g1_win_rates": {},
        "low_winrate_races": {},
    }

    junior_races = {623, 625}
    classic_races = {163, 164, 166, 168, 81}
    senior_races = {3, 4, 5, 76, 79, 80}

    for pid_key, data in (race_history or {}).items():
        try: pid = int(pid_key)
        except (TypeError, ValueError): continue
        if not isinstance(data, dict): continue
        attempts = _safe_int(data.get("attempts"))
        wins = _safe_int(data.get("wins"))
        if attempts < 5: continue
        rate = wins / max(1, attempts)
        race_name = str(data.get("race_name") or f"pid{pid}")
        summary["g1_win_rates"][race_name] = round(rate, 3)
        if rate < 0.5:
            era = "junior" if pid in junior_races else "classic" if pid in classic_races else "senior" if pid in senior_races else "mixed"
            summary["low_winrate_races"].setdefault(era, []).append((race_name, round(rate, 2)))

    return summary


def _clamp(value, floor, ceiling):
    return max(floor, min(ceiling, value))


def _current_value(param, learned, source_preset=None):
    if param in (learned or {}):
        return learned[param]
    cfg = TUNABLE_PARAMS[param]
    if source_preset and param in source_preset:
        return source_preset[param]
    return cfg["default"]


def _gap_multiplier(summary):
    """Step-size multiplier based on distance from S+. Bigger gap → bigger
    moves. Caps at 4× to avoid blowing through floors/ceilings."""
    median_sum = summary.get("stat_sum_median", 0)
    gap = SPLUS_TARGET_STAT_SUM - median_sum
    if gap <= 0:   return 1.0  # at/above S+ → small nudges only
    if gap < 200:  return 1.0  # right at S+ boundary
    if gap < 400:  return 1.5  # mid A+ tier
    if gap < 700:  return 2.0  # A tier
    if gap < 1000: return 3.0  # B+ tier
    return 4.0                 # very far


def _stuck_multiplier(log_tail, summary):
    """If recent tune log shows N moves with NO median improvement, double."""
    if not log_tail: return 1.0
    recent_medians = [e.get("median_at_time") for e in log_tail if "median_at_time" in e]
    if len(recent_medians) < 4: return 1.0
    current_med = summary.get("stat_sum_median", 0)
    if all(current_med <= m for m in recent_medians[-4:]):
        return 2.0  # stuck — double step size
    return 1.0


def propose_tune_decisions(summary, learned_hyperparameters, source_preset=None, log_tail=None):
    """Aggressive, gap-scaled tuning toward S floor → S+ target."""
    if not summary or summary.get("n_careers", 0) < MIN_CAREERS_FOR_TUNE:
        return []

    gap_mult = _gap_multiplier(summary)
    stuck_mult = _stuck_multiplier(log_tail or [], summary)
    multiplier = gap_mult * stuck_mult

    decisions = []
    median_sum = summary.get("stat_sum_median", 0)
    median_rank = _rank_for_stat_sum(median_sum)
    s_or_better = summary.get("s_or_better_count", 0)
    sub_s = summary.get("sub_s_count", 0)

    def _propose(param, direction, reason, step_multiplier=1.0):
        cfg = TUNABLE_PARAMS[param]
        old = _current_value(param, learned_hyperparameters, source_preset)
        try: old = float(old)
        except (TypeError, ValueError): old = float(cfg["default"])
        step = cfg["step"] * multiplier * step_multiplier
        new = old + step if direction == "up" else old - step
        new = _clamp(new, cfg["floor"], cfg["ceiling"])
        if isinstance(cfg["default"], int):
            new = int(round(new)); old = int(round(old))
        else:
            new = round(new, 4); old = round(old, 4)
        if new == old: return
        decisions.append({
            "param": param, "direction": direction,
            "old": old, "new": new,
            "reason": reason,
            "gap_mult": gap_mult, "stuck_mult": stuck_mult,
        })

    # ── Rule 1: Speed Priority Late — fires on top-vs-bottom delta
    speed_delta = summary.get("speed_top_vs_bottom_delta", 0)
    speed_median = summary.get("speed_median", 0)
    if speed_delta > 120 and speed_median < 950:
        _propose("speed_priority_bonus_late", "up",
                 f"speed top-vs-bot={speed_delta}, median speed={speed_median}<950")

    # ── Rule 2: Classic Speed pressure if median rank is sub-S
    if median_sum < S_FLOOR_STAT_SUM and speed_median < 880:
        _propose("speed_priority_bonus_mid", "up",
                 f"median sum={median_sum}<S floor ({S_FLOOR_STAT_SUM}), speed={speed_median}")

    # ── Rule 3: Junior Speed if S-or-better count is low
    if s_or_better == 0 and summary.get("n_careers", 0) >= MIN_CAREERS_FOR_TUNE:
        _propose("speed_priority_bonus_early", "up",
                 f"zero S+ careers in last {summary['n_careers']} — push Junior speed harder")

    # ── Rule 4: Per-race postmortem cap if Classic/Senior G1s lose
    low_rates = summary.get("low_winrate_races") or {}
    if low_rates.get("classic") or low_rates.get("senior"):
        ttl = sum(len(v) for v in low_rates.values())
        names = [n for v in low_rates.values() for (n, _) in v][:4]
        _propose("postmortem_bonus_cap", "up",
                 f"{ttl} G1s under 50%: {', '.join(names)}")

    # ── Rule 5: Race-specific demand cap if 2+ severe losses
    all_low = [(n, r) for v in low_rates.values() for (n, r) in v]
    severe = [n for n, r in all_low if r < 0.4]
    if len(severe) >= 2:
        _propose("race_specific_demand_cap", "up",
                 f"{len(severe)} G1s under 40%: {', '.join(severe[:3])}")

    race_losses_total = summary.get("race_losses_total", 0)
    clean_career_count = summary.get("clean_career_count", 0)
    if race_losses_total > 0:
        _propose("calendar_race_prebuy_budget", "up",
                 f"{race_losses_total} race losses in recent finished careers; raise scheduled prebuy budget",
                 step_multiplier=1.4)
        _propose("calendar_race_prebuy_max_skills", "up",
                 f"{race_losses_total} race losses in recent finished careers; allow more pre-race skills")
        _propose("calendar_race_prebuy_keep_sp", "down",
                 f"{race_losses_total} race losses; lower SP reserve for mandatory race safety")
        _propose("calendar_race_prebuy_min_sp", "down",
                 f"{race_losses_total} race losses; let early scheduled races buy sooner")
        _propose("race_success_bonus_cap", "up",
                 f"{race_losses_total} race losses; increase race-success training pressure")
    elif clean_career_count < summary.get("n_careers", 0):
        _propose("calendar_race_prebuy_keep_sp", "down",
                 f"only {clean_career_count}/{summary.get('n_careers', 0)} clean careers; keep safety reserve low",
                 step_multiplier=0.5)

    # ── Rule 6: Skill budget — sub-S floors get bigger budgets
    if median_sum < S_FLOOR_STAT_SUM:
        _propose("calendar_race_prebuy_budget", "up",
                 f"median sum={median_sum} below S floor — bump skill budget")
        _propose("calendar_race_prebuy_max_skills", "up",
                 f"median sum={median_sum} below S floor — bump skills per race",
                 step_multiplier=0.5)  # int param — partial step OK after clamp

    # ── Rule 7: Stamina variance / checkpoint pressure
    sta_delta = summary.get("stamina_top_vs_bottom_delta", 0)
    if sta_delta > 100:
        _propose("checkpoint_pressure_base", "up",
                 f"stamina top-vs-bot={sta_delta}>100")

    # ── Rule 8: Race success cap when we're improving but plateauing
    if median_rank in ("S", "S+") and speed_median < 1050:
        _propose("race_success_bonus_cap", "up",
                 f"plateau at {median_rank} — push race-success learning")

    # ── Rule 9: Aggressive escalation when stuck and far from S
    if stuck_mult > 1.0 and median_sum < S_FLOOR_STAT_SUM:
        _propose("speed_priority_bonus_late", "up",
                 f"STUCK below S — escalating speed bonus", step_multiplier=1.5)
        _propose("race_specific_demand_cap", "up",
                 f"STUCK below S — escalating race demand cap", step_multiplier=1.5)

    # ── Rule 10: Never learn low caps while the account is below target.
    # The previous heuristic tried to infer "Wit over-training" from an
    # incomplete median and could drive `wit_soft_cap` down to 900. That is
    # deck-poison for 2-Wit routes: after a deck swap, the bot stops pushing
    # the exact stat the deck was built to cap. Keep high-priority caps high
    # until the route is consistently at the SS climb target.
    speed_med = summary.get("speed_median", 0)
    stamina_med = summary.get("stamina_median", 0)
    if median_sum < SPLUS_TARGET_STAT_SUM:
        if speed_med and speed_med < 1150:
            _propose("speed_soft_cap", "up",
                     f"median speed={speed_med}<1150 while below SS target — keep Speed cap pressure high",
                     step_multiplier=1.2)
        if summary.get("power_median", 0) and summary.get("power_median", 0) < 1000:
            _propose("power_soft_cap", "up",
                     f"median power={summary.get('power_median', 0)}<1000 while below SS target — keep Power pressure high",
                     step_multiplier=0.8)
        _propose("wit_soft_cap", "up",
                 f"median stat sum={median_sum}<SS target — do not learn low Wit caps",
                 step_multiplier=1.2)

    # Rule 11: A+ prevention from action economy. Weak live careers are usually
    # still running the calendar; they fall short because recovery consumes too
    # many turns. Push the bot toward Riko/Pal and safe low-HP Wit substitutes
    # before it spends another full rest turn.
    rest_median = summary.get("rest_median", 0)
    rest_delta = summary.get("rest_top_vs_bottom_delta", 0)
    stat_friend_median = summary.get("stat_friend_recreation_median", 0)
    pal_cards = summary.get("deck_pal_median", 0)
    if median_sum < SPLUS_TARGET_STAT_SUM and (sub_s > 0 or rest_median >= 6 or rest_delta >= 2):
        if rest_median >= 6 or rest_delta >= 2:
            _propose(
                "race_heavy_rest_threshold_penalty",
                "up",
                f"rest-heavy context: median rest={rest_median}, bottom-vs-top rest delta={rest_delta}; lower race-heavy rest threshold",
                step_multiplier=1.4,
            )
            _propose(
                "low_hp_wit_training_max_failure",
                "up",
                "rest-heavy context: allow safe Wit-as-rest at a higher failure cap instead of full rest",
            )
            _propose(
                "non_wit_high_value_training_max_failure",
                "up",
                "rest-heavy context: allow strong non-Wit rainbow/high-output tiles through the low-20% failure band",
            )
            _propose(
                "low_hp_wit_training_min_score",
                "down",
                "rest-heavy context: lower direct Wit-as-rest score gate",
            )
            _propose(
                "low_hp_wit_training_substitute_min_score",
                "down",
                "rest-heavy context: lower substitute Wit-as-rest score gate",
            )
        if pal_cards > 0 and stat_friend_median < 5:
            _propose(
                "stat_friend_recreation_force_vital",
                "up",
                f"Pal deck but median stat-friend outings={stat_friend_median}<5; force ready outings at higher HP",
            )
            _propose(
                "stat_friend_recreation_max_training_score",
                "up",
                f"Pal deck but median stat-friend outings={stat_friend_median}<5; let ready Pal outing beat mediocre training",
                step_multiplier=1.2,
            )
            _propose(
                "stat_friend_recreation_max_vital",
                "up",
                f"Pal deck but median stat-friend outings={stat_friend_median}<5; avoid missing ready outings due to HP ceiling",
                step_multiplier=0.8,
            )

    # Rule 12: Deck-aware Wit pressure. With two Wit cards, sub-1100 Wit means
    # the current deck's best lane is not being converted consistently.
    # Guard: only escalate while Wit actually LAGS the build. On the Jun-12
    # overnight batch this rule kept raising Wit pressure to its ceiling
    # (0.55/0.70) with median Wit already 960-1100 and ABOVE median Speed by
    # 100+ — every extra Wit turn came out of the lagging stats, which is
    # why final Speed sat at 800-950. When Wit already leads Speed, the
    # stat-sum shortfall is not a Wit problem; step the pressure back down
    # so the turns flow to the stats that are actually short.
    wit_cards = summary.get("deck_wit_median", 0)
    wit_med = summary.get("wit_median", 0)
    wit_turns = summary.get("wit_training_median", 0)
    wit_already_dominant = bool(wit_med and speed_med and wit_med >= speed_med)
    if (
        median_sum < SPLUS_TARGET_STAT_SUM
        and wit_cards >= 2
        and (wit_med < 1100 or wit_turns < 8)
        and not wit_already_dominant
    ):
        _propose(
            "wit_priority_bonus_mid",
            "up",
            f"2-Wit deck but median Wit={wit_med}, Wit turns={wit_turns}; raise midgame Wit pressure",
            step_multiplier=1.2,
        )
        _propose(
            "wit_priority_bonus_late",
            "up",
            f"2-Wit deck but median Wit={wit_med}, Wit turns={wit_turns}; raise late Wit cap pressure",
            step_multiplier=1.4,
        )
        _propose(
            "wit_priority_floor_raw",
            "up",
            "2-Wit deck under-capping Wit; keep Wit priority active deeper into the climb",
            step_multiplier=0.8,
        )
    elif median_sum < SPLUS_TARGET_STAT_SUM and wit_already_dominant and wit_med - speed_med >= 100:
        _propose(
            "wit_priority_bonus_mid",
            "down",
            f"median Wit={wit_med} leads Speed={speed_med} by {wit_med - speed_med}; unwind midgame Wit pressure",
            step_multiplier=2.0,
        )
        _propose(
            "wit_priority_bonus_late",
            "down",
            f"median Wit={wit_med} leads Speed={speed_med} by {wit_med - speed_med}; unwind late Wit pressure",
            step_multiplier=2.0,
        )

    # Dedup: keep only the strongest move per param (largest new-old delta)
    by_param = {}
    for d in decisions:
        gap = abs(d["new"] - d["old"])
        existing = by_param.get(d["param"])
        if not existing or gap > abs(existing["new"] - existing["old"]):
            by_param[d["param"]] = d

    return list(by_param.values())


def apply_tune_decisions(preset, decisions, log_path=None, summary=None):
    if not decisions:
        return preset, []
    learned = dict(preset.get("learned_hyperparameters") or {})
    applied = []
    for d in decisions:
        param = d["param"]
        cfg = TUNABLE_PARAMS.get(param)
        if not cfg: continue
        new_value = d["new"]
        if isinstance(cfg["default"], int):
            new_value = int(round(new_value))
        learned[param] = new_value
        applied.append(d)
    preset["learned_hyperparameters"] = learned

    if log_path and applied:
        try:
            log_path = Path(log_path)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            median_at_time = (summary or {}).get("stat_sum_median")
            with open(log_path, "a", encoding="utf-8") as f:
                for d in applied:
                    row = {
                        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "median_at_time": median_at_time,
                        **d,
                    }
                    f.write(json.dumps(row, ensure_ascii=False) + "\n")
        except OSError:
            pass
    return preset, applied


def run_tuner(*, bot_logs_dir, race_history_path, preset, log_path=None):
    careers = _load_recent_careers(bot_logs_dir, n=RECENT_WINDOW)
    careers, context_adaptation = _context_adapt_careers(careers, preset)
    history = _load_race_history(race_history_path)
    summary = summarize_recent_outcomes(careers, history)
    summary["context_adaptation"] = context_adaptation
    log_tail = _read_tune_log_tail(log_path, n=STUCK_WINDOW)
    decisions = propose_tune_decisions(
        summary,
        preset.get("learned_hyperparameters") or {},
        source_preset=preset,
        log_tail=log_tail,
    )
    preset, applied = apply_tune_decisions(preset, decisions, log_path=log_path, summary=summary)
    return {"summary": summary, "proposed": decisions, "applied": applied}
