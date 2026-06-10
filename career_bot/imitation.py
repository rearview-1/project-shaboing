"""Imitation-learning prior for the strategy.

The auto-tuner's feature-based learning needs many positive examples to
generalize. With sparse positives (often <10 sweep/near-sweep careers in
the local archive), feature learning fails. Imitation instead picks the
single best-matching past career and biases the bot toward replaying its
turn-by-turn decisions.

Pipeline:
  1. `build_archive` scans bot_logs + postmortems, ranks finished careers
     by composite quality, keeps the top N as imitation candidates.
  2. `select_prior` matches a new career's run_context against the archive
     and returns the best-fit entry (or None).
  3. `prior_action_for_turn` returns what command the prior took at a
     given turn (used by the strategy to add a small score bonus to the
     matching tile).

Disable globally by setting `imitation_enabled: false` in the preset.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from collections import Counter


_ARCHIVE_SCHEMA = "sweepy_imitation_archive_v1"
_DEFAULT_TOP_N = 25
_DEFAULT_MIN_STAT_SUM = 3000   # exclude failed/stopped careers
_DEFAULT_RATING_FLOOR = 9000   # require at least A-tier rating
_DEFAULT_ARCHIVE_FILENAME = "imitation/sweep_archive.json"


def _read_json(path):
    try:
        with open(path, encoding="utf-8-sig") as fh:
            return json.load(fh)
    except Exception:
        return None


def _compute_composite_score(career):
    """Rank metric: prefer high stat_sum, many G1 wins, few G1 losses.

    Wins weighted heavily (160 each) and losses penalized hard (180 each)
    so a 17-win/2-loss career beats a 0-win/0-loss career with higher
    stat_sum. The old weighting let high-stat-sum-but-zero-win careers
    dominate, which produced misleading priors.
    """
    last = (career.get("turns") or [{}])[-1]
    stats = last.get("stats") or {}
    stat_sum = sum(int(stats.get(k) or 0) for k in ("speed", "stamina", "power", "guts", "wit"))
    summary = career.get("final_summary") or {}
    g1_wins = int(summary.get("g1_wins") or 0)
    g1_losses = int(summary.get("g1_losses") or 0)
    if not g1_wins and not g1_losses:
        # Fallback: estimate from race-command turns when summary is missing
        turns = career.get("turns") or []
        for t in turns:
            cmd = (t.get("current_command") or {})
            if cmd.get("command_type") == 4:
                g1_wins += 1  # crude, but loss data isn't reliably in turns
    score = stat_sum + g1_wins * 160 - g1_losses * 180
    return score, stat_sum, g1_wins, g1_losses


def _extract_run_context(career):
    rc = career.get("run_context") or {}
    cards = rc.get("support_card_ids")
    if not cards:
        cards = [
            (c.get("id") or c.get("support_card_id") or 0)
            for c in (rc.get("support_cards") or [])
        ]
    cards = sorted(int(c or 0) for c in cards if int(c or 0))
    schedule = []
    for entry in rc.get("custom_race_schedule") or []:
        try:
            schedule.append(int(entry.get("program_id") or 0))
        except (TypeError, ValueError):
            continue
    schedule = sorted(set(p for p in schedule if p))
    return {
        "trainee_card_id": int(rc.get("trainee_card_id") or rc.get("chara_id") or 0),
        "friend_card_id": int(rc.get("friend_card_id") or 0),
        "support_card_ids": cards,
        "schedule_program_ids": schedule,
        "deck_name": str(rc.get("deck_name") or ""),
        "parent_id_1": int(rc.get("parent_id_1") or 0),
        "parent_id_2": int(rc.get("parent_id_2") or 0),
    }


def _extract_turn_sequence(career):
    """For each turn the bot acted, record (turn, command_type, command_id)."""
    seq = []
    for t in career.get("turns") or []:
        cmd = t.get("current_command") or {}
        ct = cmd.get("command_type")
        cid = cmd.get("command_id")
        try:
            turn = int(t.get("turn") or 0)
        except (TypeError, ValueError):
            continue
        if not turn or ct is None:
            continue
        try:
            ct_i = int(ct)
            cid_i = int(cid or 0)
        except (TypeError, ValueError):
            continue
        seq.append([turn, ct_i, cid_i])
    seq.sort()
    return seq


def _g1_losses_from_postmortem(career_log_path, postmortems_dir):
    """Find the matching postmortem for this career_log and return G1 loss count."""
    pmd = Path(postmortems_dir)
    if not pmd.exists():
        return None
    target_name = Path(career_log_path).name
    for pm_path in pmd.glob("postmortem_*.json"):
        try:
            d = json.loads(pm_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        cl = d.get("career_log") or ""
        if Path(cl).name == target_name:
            return len(d.get("g1_losses") or [])
    return None


def _count_scheduled_g1s(career, race_attempt_history_path=None):
    """Estimate scheduled G1 count from the career's run_context schedule.

    Career logs don't preserve `custom_race_schedule` reliably, so this
    often returns 0. Callers should treat None as "couldn't determine"
    and use a fallback (e.g., current preset's G1 count).
    """
    rc = career.get("run_context") or {}
    sched = rc.get("custom_race_schedule") or []
    if not sched:
        return None
    if not race_attempt_history_path:
        return None
    try:
        ra = json.loads(Path(race_attempt_history_path).read_text(encoding="utf-8"))
    except Exception:
        return None
    g1_pids = {int(pid) for pid, info in ra.items() if info.get("is_g1")}
    return sum(1 for e in sched if int((e or {}).get("program_id") or 0) in g1_pids)


def build_archive(
    bot_logs_dir,
    archive_path,
    *,
    top_n=_DEFAULT_TOP_N,
    min_stat_sum=_DEFAULT_MIN_STAT_SUM,
    rating_floor=_DEFAULT_RATING_FLOOR,
    postmortems_dir=None,
    race_attempt_history_path=None,
    fallback_scheduled_g1=None,
):
    """Scan finished careers, keep the top N by composite score.

    When `postmortems_dir` is supplied, G1 wins/losses are computed by
    correlating each career_log with its postmortem (which has the loss
    list). This is critical because final_summary is empty in current
    career logs, so the composite score otherwise falls back to a
    bad heuristic.
    """
    bot_logs_dir = Path(bot_logs_dir)
    archive_path = Path(archive_path)
    candidates = []
    for log_path in bot_logs_dir.glob("career_log_*.json"):
        career = _read_json(log_path)
        if not career:
            continue
        if (career.get("final_turn") or 0) < 70:
            continue
        if str(career.get("status") or "") != "finished":
            continue
        score, stat_sum, g1w, g1l = _compute_composite_score(career)
        # Correlate with postmortem for real loss count, with optional
        # fallback_scheduled_g1 (the current preset's scheduled G1 count)
        # so wins can be inferred even when the career_log doesn't carry
        # a schedule snapshot.
        if postmortems_dir:
            losses_from_pm = _g1_losses_from_postmortem(log_path, postmortems_dir)
            if losses_from_pm is not None:
                g1l = losses_from_pm
                scheduled_g1 = _count_scheduled_g1s(career, race_attempt_history_path)
                if scheduled_g1 is None and fallback_scheduled_g1:
                    scheduled_g1 = int(fallback_scheduled_g1)
                if scheduled_g1 is not None:
                    g1w = max(0, scheduled_g1 - g1l)
                score = stat_sum + g1w * 160 - g1l * 180
        if stat_sum < min_stat_sum:
            continue
        candidates.append({
            "source_path": str(log_path),
            "composite_score": score,
            "stat_sum": stat_sum,
            "g1_wins": g1w,
            "g1_losses": g1l,
            "run_context": _extract_run_context(career),
            "turn_sequence": _extract_turn_sequence(career),
            "final_stats": (career.get("turns") or [{}])[-1].get("stats") or {},
        })
    candidates.sort(key=lambda c: -c["composite_score"])
    top = candidates[:top_n]
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": _ARCHIVE_SCHEMA,
        "candidate_count": len(top),
        "source_pool_count": len(candidates),
        "top_n_limit": top_n,
        "candidates": top,
    }
    with open(archive_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    return payload


def _run_context_similarity(target, candidate):
    """Score how well a candidate's run_context matches the target.

    Returns (total_score, match_detail). Higher = better. trainee match is
    required (score 0 otherwise); friend, deck, and schedule weigh in.

    Schedule alignment is now WEIGHTED HEAVILY — replaying decisions from
    a career that ran a different schedule is misleading because training
    priorities are schedule-driven. Old long-race-schedule priors would
    push stamina training the new sprint schedule doesn't need.
    """
    if not target or not candidate:
        return 0, {}
    if int(target.get("trainee_card_id") or 0) != int(candidate.get("trainee_card_id") or 0):
        return 0, {"trainee_mismatch": True}

    # Schedule-overlap gate: if BOTH sides have schedules and they don't
    # substantially overlap, the candidate is for a different optimization
    # target. If the candidate has no schedule recorded (career_logs don't
    # preserve `custom_race_schedule`), skip the gate — fall back to
    # trainee+friend+deck similarity only.
    target_sched = set(target.get("schedule_program_ids") or [])
    cand_sched = set(candidate.get("schedule_program_ids") or [])
    schedule_jaccard = 0.0
    schedule_known = bool(target_sched and cand_sched)
    if schedule_known:
        intersect = len(target_sched & cand_sched)
        union = len(target_sched | cand_sched)
        if union:
            schedule_jaccard = intersect / union
        if schedule_jaccard < 0.30:
            return 0, {
                "trainee_match": True,
                "schedule_mismatch": True,
                "schedule_jaccard": round(schedule_jaccard, 3),
            }

    score = 100
    detail = {"trainee_match": True}
    if int(target.get("friend_card_id") or 0) == int(candidate.get("friend_card_id") or 0) and target.get("friend_card_id"):
        score += 60
        detail["friend_match"] = True
    target_deck = set(target.get("support_card_ids") or [])
    cand_deck = set(candidate.get("support_card_ids") or [])
    if target_deck and cand_deck:
        intersect = len(target_deck & cand_deck)
        union = len(target_deck | cand_deck)
        if union:
            jaccard = intersect / union
            score += int(round(jaccard * 80))
            detail["deck_jaccard"] = round(jaccard, 3)
            detail["deck_overlap_count"] = intersect
    # Schedule weight raised from 40 -> 120 so it dominates when present.
    # A 50% schedule overlap is worth 60 points (about as much as friend match).
    if schedule_known:
        score += int(round(schedule_jaccard * 120))
        detail["schedule_jaccard"] = round(schedule_jaccard, 3)
    return score, detail


def select_prior(archive_path, run_context, *, min_match_score=100):
    """Find the best-matching archive entry for a new career.

    Returns (entry_dict, match_score, detail) or (None, 0, {}).
    """
    payload = _read_json(archive_path)
    if not payload or not payload.get("candidates"):
        return None, 0, {"reason": "empty_archive"}
    if not run_context:
        return None, 0, {"reason": "missing_run_context"}
    best = None
    best_score = 0
    best_detail = {}
    for entry in payload["candidates"]:
        s, detail = _run_context_similarity(run_context, entry.get("run_context") or {})
        if s > best_score:
            best, best_score, best_detail = entry, s, detail
    if not best or best_score < min_match_score:
        return None, best_score, {"reason": "no_match_above_threshold", "best_score": best_score, **best_detail}
    return best, best_score, best_detail


def prior_action_for_turn(prior, turn):
    """Return (command_type, command_id) the prior took at this turn, or None."""
    if not prior:
        return None
    try:
        target_turn = int(turn or 0)
    except (TypeError, ValueError):
        return None
    if target_turn <= 0:
        return None
    for entry in prior.get("turn_sequence") or []:
        t, ct, cid = entry[0], entry[1], entry[2]
        if int(t) == target_turn:
            return (int(ct), int(cid))
    return None
