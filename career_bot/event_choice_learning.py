"""Event-choice learning from career outcomes.

Career events with multiple choices are an under-explored adaptive
surface. The existing `EventManager` reads a static `event_outcomes.json`
file (manually curated good/bad labels) as a baseline, but it does not
learn from how the bot's own careers turn out.

This module aggregates per-event choice statistics from completed
careers. It keeps the original global per-story view, then layers a
bounded context split on top:

- turn phase: early / mid / late / climax
- primary desired blue target when known

At runtime the picker consults the matching context first and falls back
to the global event view when the context bucket is too sparse.
"""

import random
from collections import defaultdict


MIN_PICKS_PER_CHOICE = 3
MIN_TOTAL_PICKS = 5
SIGNIFICANT_SCORE_LIFT = 800.0
EXPLORATION_RATE = 0.10


def _choice_context_key(choice, current_turn=None, preset=None):
    phase = str((choice or {}).get("phase") or "").strip().lower()
    if not phase and current_turn is not None:
        try:
            turn = int(current_turn or 0)
        except (TypeError, ValueError):
            turn = 0
        if turn <= 24:
            phase = "early"
        elif turn <= 48:
            phase = "mid"
        elif turn <= 64:
            phase = "late"
        else:
            phase = "climax"
    blue_target = str((choice or {}).get("blue_target") or "").strip().lower()
    if not blue_target and isinstance(preset, dict):
        desired = ((preset.get("desired_parent_sparks") or {}).get("blue") or [])
        if isinstance(desired, list) and desired:
            blue_target = str(desired[0] or "").strip().lower()
    parts = []
    if phase:
        parts.append(f"phase={phase}")
    if blue_target:
        parts.append(f"blue={blue_target}")
    return "|".join(parts)


def _summarize_choice_scores(by_choice):
    choices_summary = {}
    for choice_index, scores in by_choice.items():
        if not scores:
            continue
        choices_summary[str(choice_index)] = {
            "count": len(scores),
            "avg_score": round(sum(scores) / len(scores), 1),
            "best_score": round(max(scores), 1),
        }
    total = sum(c["count"] for c in choices_summary.values())
    if total < MIN_TOTAL_PICKS:
        return None
    eligible = {
        ci: data
        for ci, data in choices_summary.items()
        if data["count"] >= MIN_PICKS_PER_CHOICE
    }
    if not eligible:
        return None
    best_choice = max(eligible.items(), key=lambda kv: kv[1]["avg_score"])
    best_avg = best_choice[1]["avg_score"]
    runners_up = [data["avg_score"] for ci, data in eligible.items() if ci != best_choice[0]]
    if runners_up:
        lift = best_avg - max(runners_up)
        confidence = min(1.0, max(0.0, lift / SIGNIFICANT_SCORE_LIFT))
    else:
        confidence = 0.5
    return {
        "choices": choices_summary,
        "best_choice": best_choice[0],
        "confidence": round(confidence, 3),
        "sample_count": total,
    }


def aggregate_event_choices(samples, preset_fallback=None):
    """Build per-(story_id, choice_index) statistics from career samples."""
    raw = defaultdict(lambda: defaultdict(list))
    contextual = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for sample in samples or []:
        score = _safe_float(sample.get("score"))
        if score <= 0:
            continue
        sample_sparks = _sample_desired_parent_sparks(sample, preset_fallback=preset_fallback)
        sample_blue = _first_blue_target(sample_sparks)
        for choice in _iter_event_choices(sample):
            story_id = str(choice.get("story_id") or "").strip()
            choice_index = choice.get("choice_index")
            if not story_id or choice_index is None:
                continue
            try:
                choice_index = int(choice_index)
            except (TypeError, ValueError):
                continue
            raw[story_id][choice_index].append(score)
            if not choice.get("blue_target") and sample_blue:
                choice = dict(choice)
                choice["blue_target"] = sample_blue
            context_key = _choice_context_key(choice)
            if context_key:
                contextual[story_id][context_key][choice_index].append(score)
    result = {}
    for story_id, by_choice in raw.items():
        summary = _summarize_choice_scores(by_choice)
        if not summary:
            continue
        entry = {
            "story_id": story_id,
            **summary,
        }
        contexts = {}
        for context_key, context_choices in (contextual.get(story_id) or {}).items():
            context_summary = _summarize_choice_scores(context_choices)
            if not context_summary:
                continue
            contexts[context_key] = {
                "context_key": context_key,
                **context_summary,
            }
        if contexts:
            entry["contexts"] = contexts
        result[story_id] = entry
    return result


def pick_learned_choice(stats, story_id, choices, rng=None, current_turn=None, preset=None):
    """Return a 0-based choice index from `choices`, or None.

    Runner logs `choice_index` as the zero-based `choice_number` sent to
    `check_event`. Do not map through `select_index` here: live GLB events can
    expose duplicate select_index values, and using them makes learned event
    choices fail exactly when deck/trainee-specific event chains matter.
    """
    if not stats or not choices:
        return None
    entry = stats.get(str(story_id))
    if not entry:
        return None
    context_key = _choice_context_key({}, current_turn=current_turn, preset=preset)
    if context_key:
        context_entry = ((entry.get("contexts") or {}).get(context_key) or {})
        if context_entry:
            entry = context_entry
    confidence = float(entry.get("confidence") or 0)
    best_choice = entry.get("best_choice")
    choices_summary = entry.get("choices") or {}
    choice_indices_in_api = [str(i) for i in range(len(choices))]
    if best_choice not in choice_indices_in_api:
        return None
    best_idx = choice_indices_in_api.index(best_choice)
    rng = rng or random
    if confidence < 1.0 and rng.random() < EXPLORATION_RATE * (1.0 - confidence):
        under_sampled = [
            (i, choice_indices_in_api[i])
            for i in range(len(choices))
            if choices_summary.get(choice_indices_in_api[i], {}).get("count", 0) < MIN_PICKS_PER_CHOICE
        ]
        if under_sampled:
            return rng.choice(under_sampled)[0]
    return best_idx


def _iter_event_choices(sample):
    """Yield {story_id, choice_index, phase, blue_target} rows."""
    turns = sample.get("turns") or []
    if isinstance(turns, list):
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            for row in turn.get("events") or []:
                if not isinstance(row, dict):
                    continue
                if row.get("event") != "event_choice":
                    continue
                yield {
                    "story_id": row.get("story_id"),
                    "choice_index": row.get("choice_index"),
                    "turn": turn.get("turn"),
                    "phase": row.get("phase"),
                    "blue_target": row.get("blue_target"),
                }
    for row in sample.get("event_choices") or []:
        if isinstance(row, dict):
            yield {
                "story_id": row.get("story_id"),
                "choice_index": row.get("choice_index"),
                "turn": row.get("turn"),
                "phase": row.get("phase"),
                "blue_target": row.get("blue_target"),
            }


def _sample_desired_parent_sparks(sample, preset_fallback=None):
    run_context = (sample or {}).get("run_context") or {}
    if isinstance(run_context, dict) and isinstance(run_context.get("desired_parent_sparks"), dict):
        return run_context.get("desired_parent_sparks") or {}
    if isinstance((sample or {}).get("desired_parent_sparks"), dict):
        return (sample or {}).get("desired_parent_sparks") or {}
    if isinstance(preset_fallback, dict):
        return preset_fallback.get("desired_parent_sparks") or {}
    return {}


def _first_blue_target(desired_parent_sparks):
    desired = ((desired_parent_sparks or {}).get("blue") or [])
    if isinstance(desired, str):
        desired = desired.replace(",", "\n").splitlines()
    if not isinstance(desired, list) or not desired:
        return ""
    return str(desired[0] or "").strip().lower()


def _safe_float(value, default=0.0):
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return default
