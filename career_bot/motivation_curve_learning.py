"""Learn per-phase motivation thresholds from top-scoring careers.

The bot's existing recreation policy uses hardcoded preset defaults:

    motivation_threshold_year1 = 3   # turns 1-36
    motivation_threshold_year2 = 4   # turns 37-60
    motivation_threshold_year3 = 4   # turns 61+

The threshold is the level below which the bot spends a turn on
recreation to push motivation back up. Lower threshold = less
aggressive about maintaining motivation = more turns spent on stat
training; higher threshold = aim to keep motivation high but burn more
turns recovering it.

The right number depends on what top-scoring careers actually
maintained. If top careers averaged motivation 4.5 in year-1, the
bot should be aggressive about keeping it that high (threshold ≥ 4).
If top careers ran fine at motivation 3, lower thresholds free up
training turns.

This module reads the motivation_curve from top samples and emits
learned thresholds. It's deliberately conservative — only adjusts
when there's enough sample data and the signal is consistent across
top careers.
"""

import statistics


# Phase boundaries (matches mant.py:_mood_threshold).
PHASE_BOUNDS = [
    ("year1", 1, 36),
    ("year2", 37, 60),
    ("year3", 61, 99),
]
# Minimum sample of distinct top careers before any learning fires.
MIN_TOP_CAREERS = 3
# Minimum per-phase samples (turns observed in this phase across
# top careers) before we trust the phase-specific median.
MIN_TURNS_PER_PHASE = 8
# Clamp the threshold to a plausible range — motivation runs 1..5 in
# this game, so allow 2..5 to avoid degenerate zero/negative values.
MIN_THRESHOLD = 2
MAX_THRESHOLD = 5


def aggregate_motivation_curves(top_samples):
    """Compute median motivation per phase across top samples.

    Returns dict {phase_name: median_motivation} for phases with
    sufficient data. Empty when no usable curve data is present.
    """
    by_phase = {name: [] for name, _, _ in PHASE_BOUNDS}
    careers_seen = 0
    for sample in top_samples or []:
        curve = sample.get("motivation_curve") or []
        if not curve:
            continue
        careers_seen += 1
        for row in curve:
            if not isinstance(row, dict):
                continue
            try:
                turn = int(row.get("turn") or 0)
                motivation = int(row.get("motivation") or 0)
            except (TypeError, ValueError):
                continue
            if turn <= 0 or motivation <= 0:
                continue
            for name, lo, hi in PHASE_BOUNDS:
                if lo <= turn <= hi:
                    by_phase[name].append(motivation)
                    break
    if careers_seen < MIN_TOP_CAREERS:
        return {}
    result = {}
    for name, samples in by_phase.items():
        if len(samples) < MIN_TURNS_PER_PHASE:
            continue
        result[name] = round(statistics.median(samples), 2)
    return result


def learned_motivation_thresholds(top_samples):
    """Return {motivation_threshold_year1, motivation_threshold_year2,
    motivation_threshold_year3} suitable for merging into the learned
    preset. Empty when there isn't enough top-sample motivation data
    to make a confident call — caller should keep the existing preset
    values in that case.

    The rule: threshold = floor(median_motivation_in_phase). With a
    threshold of N, the bot recreates when motivation < N — i.e., it
    aims to keep motivation at AT LEAST the median that top careers
    maintained.
    """
    medians = aggregate_motivation_curves(top_samples)
    if not medians:
        return {}
    out = {}
    for phase_name, median in medians.items():
        threshold = max(MIN_THRESHOLD, min(MAX_THRESHOLD, int(median)))
        key = f"motivation_threshold_{phase_name}"
        out[key] = threshold
    return out


def motivation_curve_from_turns(turns):
    """Extract a {turn, motivation} pair list from a career's per-turn
    log. Skips turns missing either field. Used by
    `normalize_bot_like_log` to add a slim `motivation_curve` field to
    each sample so the aggregator can read it without re-loading the
    full career_log JSON.
    """
    out = []
    for turn_row in turns or []:
        if not isinstance(turn_row, dict):
            continue
        turn = turn_row.get("turn")
        motivation = turn_row.get("motivation")
        if motivation is None:
            chara = turn_row.get("chara_info") or {}
            motivation = chara.get("motivation")
        if turn is None or motivation is None:
            continue
        try:
            turn_int = int(turn)
            motivation_int = int(motivation)
        except (TypeError, ValueError):
            continue
        if turn_int <= 0 or motivation_int <= 0:
            continue
        out.append({"turn": turn_int, "motivation": motivation_int})
    return out
