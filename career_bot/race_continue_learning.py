"""Learn the recovery rate of race-continue attempts and feed it back.

Career runs already log race-continue chains (`continue_resources`,
`continue_failed_ranks`, `continued`, `continue_attempts` on the
race_result event row). What was missing: anything that *learns* from
those outcomes. The bot would spend an alarm clock or carat retry on a
race that historically never recovers, career after career.

This module aggregates per-(program_id, resource_type) recovery rates
from past careers and exposes a `should_attempt_continue` decision the
runner can consult before burning a continue resource. The decision is
deliberately conservative:

- Below `MIN_ATTEMPTS_FOR_DECISION` samples → defer (let the existing
  rule-based logic run; can't make a confident call yet).
- Above the sample floor, if observed recovery rate is below
  `MIN_RECOVERY_RATE_FOR_CONTINUE` → recommend skipping (the resource
  is being thrown away on average).
- Otherwise → recommend continuing.

This is NOT race-skip logic (which the user explicitly rejected). It
runs only when the bot has ALREADY lost a race and is deciding whether
to spend a resource on a retry. Saving continues you'd lose anyway is
the parent-farming-correct play.
"""

from collections import defaultdict


MIN_ATTEMPTS_FOR_DECISION = 3
MIN_RECOVERY_RATE_FOR_CONTINUE = 0.30
RECENT_HISTORY_LIMIT = 12


def aggregate_continue_outcomes(samples):
    """Build per-(program_id, last_resource) continue-recovery stats.

    Each sample is expected to carry the per-turn `events` list (as
    `bot_logs/*.json` produces). We walk the events looking for
    `race_result` rows where `continued=True`. Each such row credits
    its LAST resource — that's what either rescued or failed the race.

    Returns:
        {
          "<program_id>": {
            "<resource>": {"attempts": int, "recoveries": int, "recovery_rate": float},
            ...
            "_recent_history": [{"resource": ..., "won": bool, "started_at": ...}, ...]
          },
          ...
        }
    """
    raw = defaultdict(lambda: defaultdict(lambda: {"attempts": 0, "recoveries": 0}))
    recent = defaultdict(list)
    for sample in samples or []:
        started_at = sample.get("started_at") or ""
        for row in _iter_race_results(sample):
            if not row.get("continued"):
                continue
            resources = row.get("continue_resources") or []
            if not resources:
                continue
            last_resource = str(resources[-1])
            program_id = str(row.get("program_id") or "")
            if not program_id:
                continue
            won = bool(row.get("won"))
            raw[program_id][last_resource]["attempts"] += 1
            if won:
                raw[program_id][last_resource]["recoveries"] += 1
            recent[program_id].append({
                "resource": last_resource,
                "won": won,
                "started_at": started_at,
            })
    result = {}
    for program_id, by_resource in raw.items():
        entry = {}
        for resource, counts in by_resource.items():
            attempts = counts["attempts"]
            recoveries = counts["recoveries"]
            entry[resource] = {
                "attempts": attempts,
                "recoveries": recoveries,
                "recovery_rate": round(recoveries / attempts, 3) if attempts else 0.0,
            }
        # Cap recent history so the JSON doesn't bloat over many careers.
        entry["_recent_history"] = recent[program_id][-RECENT_HISTORY_LIMIT:]
        result[program_id] = entry
    return result


def should_attempt_continue(stats, program_id, resource_type):
    """Recommend whether to spend a continue resource at this race.

    Returns:
        True  — go ahead and continue
        False — recommend skipping (historical recovery too poor)
        None  — defer to the existing rule-based logic (not enough data)

    Conservative semantics: only returns False when there's clear
    evidence the resource is being wasted. Anything ambiguous returns
    None so the existing preset-driven thresholds keep applying.
    """
    if not stats:
        return None
    entry = stats.get(str(program_id))
    if not entry:
        return None
    resource_stat = entry.get(str(resource_type))
    if not resource_stat:
        return None
    attempts = int(resource_stat.get("attempts", 0))
    if attempts < MIN_ATTEMPTS_FOR_DECISION:
        return None
    recovery_rate = float(resource_stat.get("recovery_rate") or 0.0)
    if recovery_rate < MIN_RECOVERY_RATE_FOR_CONTINUE:
        return False
    return True


def _iter_race_results(sample):
    """Yield race_result event rows from a career sample.

    Handles both per-turn events (`sample.turns[i].events`) and
    samples normalized by `normalize_bot_like_log` (which flattens
    things differently). Returns dicts with the fields needed: `won`,
    `continued`, `continue_resources`, `program_id`."""
    turns = sample.get("turns") or []
    if isinstance(turns, list):
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            for row in turn.get("events") or []:
                if isinstance(row, dict) and row.get("event") == "race_result":
                    yield row
    for row in sample.get("race_results") or []:
        if isinstance(row, dict):
            yield row
