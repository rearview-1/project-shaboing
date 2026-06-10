"""Cross-career race attempt + outcome ledger.

`uma_runtime/race_attempt_history.json` accumulates one entry per
`program_id`:

    {
      "11017": {
        "race_name": "NHK Mile Cup",
        "attempts": 8,
        "wins": 2,
        "losses": 6,
        "recent_results": [
          {"career_started_at": "...", "turn": 35, "finish_rank": 3},
          ...
        ]
      },
      ...
    }

The ledger is NOT used to gate race entry — the user explicitly
rejected that idea. The existing optional-race policy
(`optional_race_max_training_score` etc.) decides race vs train.

What this gives the system instead:
- A signal for chronic problem races so the dashboard / diagnosis
  module can surface "you've lost this 6/8 attempts."
- A pairing with the postmortem-feedback diagnosis so the bot can
  classify the dominant failure cause across attempts, not just per
  isolated postmortem.

The file is atomically written with the same per-process .tmp pattern
parent_memory.write_json uses, so concurrent learning + careers don't
trample each other.
"""

import json
import os
import time
from pathlib import Path

HISTORY_FILE_NAME = "race_attempt_history.json"
RECENT_RESULTS_LIMIT = 12


def _file_path(runtime_root):
    return Path(runtime_root) / HISTORY_FILE_NAME


def _atomic_write_json(path, payload):
    """Same pattern as session_sidecar._atomic_write_json: per-process
    .tmp + os.replace with retry, fallback to direct write on Windows
    lock contention."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    tmp.write_text(serialized, encoding="utf-8")
    last_exc = None
    for attempt in range(3):
        try:
            os.replace(tmp, path)
            return True
        except PermissionError as exc:
            last_exc = exc
            time.sleep(0.15 * (attempt + 1))
    if last_exc is not None:
        try:
            path.write_text(serialized, encoding="utf-8")
            try:
                tmp.unlink()
            except Exception:
                pass
            return True
        except Exception:
            return False
    return False


def load_history(runtime_root):
    """Return the full history dict. Empty when the file doesn't exist
    or is unreadable — callers can treat 'no history' as 'never raced
    here before'."""
    path = _file_path(runtime_root)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def record_race_attempt(runtime_root, program_id, race_name, finish_rank, *, turn=None, career_started_at=None, is_g1=False):
    """Append a single race result to the ledger.

    Args:
        runtime_root: Path to uma_runtime/.
        program_id: int, the race's program_id (game's internal id).
        race_name: display name for dashboard / diagnosis output.
        finish_rank: 1-based finish position; 1 = win.
        turn: optional career turn at race time.
        career_started_at: optional ISO timestamp of the career.
        is_g1: whether this was a G1. Stored but not currently used
            for filtering; future diagnosis layers may weight G1 attempts
            differently.

    Returns the updated entry for that program_id. Safe to call from
    the runner's race_end hook — file errors are swallowed (no career
    should crash because the history file was locked).
    """
    try:
        program_id = int(program_id)
    except (TypeError, ValueError):
        return None
    if program_id <= 0:
        return None
    try:
        finish_rank = int(finish_rank)
    except (TypeError, ValueError):
        return None
    history = load_history(runtime_root)
    key = str(program_id)
    entry = history.get(key) or {
        "program_id": program_id,
        "race_name": race_name or "",
        "is_g1": bool(is_g1),
        "attempts": 0,
        "wins": 0,
        "losses": 0,
        "recent_results": [],
    }
    entry["attempts"] = int(entry.get("attempts", 0)) + 1
    if finish_rank == 1:
        entry["wins"] = int(entry.get("wins", 0)) + 1
    else:
        entry["losses"] = int(entry.get("losses", 0)) + 1
    if race_name and not entry.get("race_name"):
        entry["race_name"] = race_name
    if is_g1:
        entry["is_g1"] = True
    recent = list(entry.get("recent_results") or [])
    recent.append({
        "finish_rank": finish_rank,
        "turn": int(turn) if turn is not None else None,
        "career_started_at": str(career_started_at) if career_started_at else None,
    })
    entry["recent_results"] = recent[-RECENT_RESULTS_LIMIT:]
    history[key] = entry
    try:
        _atomic_write_json(_file_path(runtime_root), history)
    except Exception:
        # History tracking is best-effort. Don't kill a career over a
        # write failure on a forensic ledger.
        pass
    return entry


def chronic_loss_streak(history, program_id, min_attempts=3):
    """Return the count of consecutive losses ending at the latest
    attempt, or 0 if the latest attempt was a win. A streak of >=N is
    used by the diagnosis to flag races as chronic problems."""
    try:
        program_id = int(program_id)
    except (TypeError, ValueError):
        return 0
    entry = history.get(str(program_id))
    if not entry:
        return 0
    if int(entry.get("attempts", 0)) < min_attempts:
        return 0
    recent = list(entry.get("recent_results") or [])
    streak = 0
    for result in reversed(recent):
        rank = int((result or {}).get("finish_rank") or 0)
        if rank == 1:
            return streak
        streak += 1
    return streak


def attempt_summary(history, program_id):
    """Return {attempts, wins, losses, win_rate, race_name} for one
    program_id, or None if not tracked."""
    try:
        program_id = int(program_id)
    except (TypeError, ValueError):
        return None
    entry = history.get(str(program_id))
    if not entry:
        return None
    attempts = int(entry.get("attempts", 0))
    wins = int(entry.get("wins", 0))
    losses = int(entry.get("losses", 0))
    return {
        "program_id": program_id,
        "race_name": entry.get("race_name") or "",
        "attempts": attempts,
        "wins": wins,
        "losses": losses,
        "win_rate": round(wins / attempts, 3) if attempts else None,
    }
