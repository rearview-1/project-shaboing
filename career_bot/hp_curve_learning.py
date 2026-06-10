"""Learn per-phase HP targets from top-scoring careers.

The bot's rest decision uses a fixed `rest_threshold` (default 48) and
period-based extra logic, but doesn't tune those values from outcome
data. If top-scoring careers consistently kept HP above some level in
mid-game, the bot should aim for that level too instead of dropping
to 48 before considering rest.

This module mirrors `motivation_curve_learning.py`: aggregate per-phase
median HP from top samples and emit learned targets that the preset
can consume. Conservative — only emits when there's enough data
(MIN_TOP_CAREERS samples with curves AND MIN_TURNS_PER_PHASE turns
observed per phase).

The bot's rest logic reads `target_hp_year{1,2,3}` from the preset
when present and uses them as soft floors (rest when HP < target),
falling back to the static `rest_threshold` otherwise.
"""

import statistics


PHASE_BOUNDS = [
    ("year1", 1, 36),
    ("year2", 37, 60),
    ("year3", 61, 99),
]
MIN_TOP_CAREERS = 3
MIN_TURNS_PER_PHASE = 8
# Clamp the target to a realistic range. HP can go to 100 (or 120 with
# items) and must stay above 0 to do anything. Below 30 the bot is
# stress-failing constantly; above 95 it's wastefully resting.
MIN_TARGET = 30
MAX_TARGET = 95


def aggregate_hp_curves(top_samples):
    """Compute median HP per phase across top samples.

    Returns dict {phase_name: median_hp}; empty when not enough data.
    """
    by_phase = {name: [] for name, _, _ in PHASE_BOUNDS}
    careers_seen = 0
    for sample in top_samples or []:
        curve = sample.get("hp_curve") or []
        if not curve:
            continue
        careers_seen += 1
        for row in curve:
            if not isinstance(row, dict):
                continue
            try:
                turn = int(row.get("turn") or 0)
                hp = int(row.get("hp") or 0)
            except (TypeError, ValueError):
                continue
            if turn <= 0 or hp <= 0:
                continue
            for name, lo, hi in PHASE_BOUNDS:
                if lo <= turn <= hi:
                    by_phase[name].append(hp)
                    break
    if careers_seen < MIN_TOP_CAREERS:
        return {}
    result = {}
    for name, samples in by_phase.items():
        if len(samples) < MIN_TURNS_PER_PHASE:
            continue
        result[name] = round(statistics.median(samples), 1)
    return result


def learned_hp_targets(top_samples):
    """Return per-phase `target_hp_year{1,2,3}` learned from top
    samples. Empty when there isn't enough data; caller should leave
    the preset's existing `rest_threshold` in place.

    The rule: target = floor(median_hp_in_phase). With a target of N,
    the bot's rest decision treats HP below N as "low" — soft floor
    aligning with what top performers maintained.
    """
    medians = aggregate_hp_curves(top_samples)
    if not medians:
        return {}
    out = {}
    for phase_name, median in medians.items():
        target = max(MIN_TARGET, min(MAX_TARGET, int(median)))
        out[f"target_hp_{phase_name}"] = target
    return out


def hp_curve_from_turns(turns):
    """Extract a {turn, hp} pair list from a career's per-turn log.

    HP is captured at two locations depending on log version:
      - turn_row["vital"] (newer per-turn snapshot)
      - turn_row["chara_info"]["vital"] (legacy nested chara_info)
    Skips rows missing either field.
    """
    out = []
    for turn_row in turns or []:
        if not isinstance(turn_row, dict):
            continue
        turn = turn_row.get("turn")
        hp = turn_row.get("vital")
        if hp is None:
            chara = turn_row.get("chara_info") or {}
            hp = chara.get("vital")
        if turn is None or hp is None:
            continue
        try:
            turn_int = int(turn)
            hp_int = int(hp)
        except (TypeError, ValueError):
            continue
        if turn_int <= 0 or hp_int <= 0:
            continue
        out.append({"turn": turn_int, "hp": hp_int})
    return out
