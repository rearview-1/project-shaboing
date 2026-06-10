"""Shadow-sim diff logger — foundation for the calibrate→play→diff→improve loop.

During a live career, the bot makes a real decision each turn (which
training tile to take, which event choice to pick, which skills to buy).
The shadow sim runs in parallel and records what IT would have decided
in the same state. After the career ends, the two streams are compared:

  - Decisions where bot+sim agreed (high-confidence sim prediction)
  - Decisions where they diverged (sim got it wrong OR bot did)
  - Stat trajectories vs sim-predicted trajectories
  - Final rating delta (real - sim predicted)

That diff stream is what we use to:
  1. Tune sim calibration constants (e.g., is training scale too high
     in junior year? too low in senior year?)
  2. Identify where bot strategy makes choices the sim wouldn't predict
     (potential learning targets)

This module is the LOGGING half — the analyzer that ingests these
records and produces sim-improvement diffs is the next session's work.

Records are appended as JSONL to:
  uma_runtime/instances/<instance>/sim_observations/shadow_diffs/<career_id>.jsonl

so a separate analyzer can sweep them later without holding state in
memory across the live career.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any


class ShadowDiffRecorder:
    """Append-only, fail-safe per-turn record buffer.

    Designed to NEVER raise during a live career — every public method
    catches and swallows its own exceptions. The bot must keep running
    even if disk fills up or the shadow sim crashes; we'd rather lose
    diff data than tank the career.
    """

    def __init__(self, output_path: str | Path | None):
        self._output_path: Path | None = None
        self._lines_written = 0
        if output_path:
            try:
                p = Path(output_path)
                p.parent.mkdir(parents=True, exist_ok=True)
                self._output_path = p
            except OSError:
                self._output_path = None

    @property
    def enabled(self) -> bool:
        return self._output_path is not None

    @property
    def lines_written(self) -> int:
        return self._lines_written

    @property
    def output_path(self) -> Path | None:
        return self._output_path

    def record_turn(
        self,
        *,
        turn: int,
        bot_decision: dict,
        sim_decision: dict | None,
        state_before: dict | None = None,
        state_after: dict | None = None,
        metadata: dict | None = None,
    ) -> None:
        """Record one turn's bot decision and the sim's parallel choice.

        Args:
          turn: the turn number (1-indexed, matches the bot's turn counter)
          bot_decision: the real choice the bot made — at minimum should
            contain `action` (string label like "TRAIN_SPEED") and any
            params (e.g. `command_id`, `select_id`). Full decision blob
            is OK; we serialize whatever fits.
          sim_decision: what the shadow sim would have picked in the same
            state. None if the shadow sim wasn't able to evaluate this
            turn. Same shape as bot_decision.
          state_before: optional state snapshot before the decision (stats,
            HP, motivation, fans, SP). Used for matching trajectories.
          state_after: optional state snapshot after the bot's decision
            (so the analyzer can compute deltas).
          metadata: anything else the live-vs-sim diff might want — fail
            codes, RNG seed, deck signature, etc.
        """
        if self._output_path is None:
            return
        try:
            record = {
                "turn": int(turn),
                "ts": time.time(),
                "bot_decision": _safe_serializable(bot_decision),
                "sim_decision": _safe_serializable(sim_decision) if sim_decision else None,
                "agreed": _decisions_agree(bot_decision, sim_decision),
            }
            if state_before is not None:
                record["state_before"] = _safe_serializable(state_before)
            if state_after is not None:
                record["state_after"] = _safe_serializable(state_after)
            if metadata is not None:
                record["metadata"] = _safe_serializable(metadata)
            line = json.dumps(record, ensure_ascii=False, default=str)
            with self._output_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            self._lines_written += 1
        except (OSError, TypeError, ValueError):
            # Never let logging break the bot
            pass

    def record_career_finish(
        self,
        *,
        bot_final_rating: int,
        bot_final_stats: dict,
        sim_predicted_rating: int | None = None,
        sim_predicted_stats: dict | None = None,
        rank: str = "",
        metadata: dict | None = None,
    ) -> None:
        """Special record fired once at the end of a career — captures
        the overall sim-vs-real delta. This is the headline metric the
        analyzer uses to decide whether the sim is "in parity" or not."""
        if self._output_path is None:
            return
        try:
            record = {
                "kind": "career_finish",
                "ts": time.time(),
                "bot_final_rating": int(bot_final_rating or 0),
                "bot_final_stats": _safe_serializable(bot_final_stats),
                "sim_predicted_rating": (
                    int(sim_predicted_rating) if sim_predicted_rating is not None else None
                ),
                "sim_predicted_stats": (
                    _safe_serializable(sim_predicted_stats) if sim_predicted_stats else None
                ),
                "rating_delta": (
                    int(bot_final_rating) - int(sim_predicted_rating)
                    if sim_predicted_rating is not None else None
                ),
                "rank": str(rank or ""),
            }
            if metadata is not None:
                record["metadata"] = _safe_serializable(metadata)
            line = json.dumps(record, ensure_ascii=False, default=str)
            with self._output_path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
            self._lines_written += 1
        except (OSError, TypeError, ValueError):
            pass


def _safe_serializable(obj: Any, _depth: int = 0) -> Any:
    """Convert arbitrary objects into JSON-friendly shapes without raising.
    Bounded depth to avoid runaway recursion on circular refs."""
    if _depth > 8:
        return repr(obj)
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_safe_serializable(x, _depth + 1) for x in obj]
    if isinstance(obj, dict):
        return {
            str(k): _safe_serializable(v, _depth + 1)
            for k, v in obj.items()
        }
    # Fall back to attribute dict for dataclass-like objects
    try:
        return _safe_serializable(vars(obj), _depth + 1)
    except (TypeError, AttributeError):
        return repr(obj)


def _decisions_agree(bot_decision: dict | None, sim_decision: dict | None) -> bool | None:
    """Loose alignment check for the agreement flag in the record.

    Returns True/False if both decisions are present and comparable,
    None if either is missing (so the analyzer can distinguish 'no
    comparison made' from 'compared and disagreed').
    """
    if not bot_decision or not sim_decision:
        return None
    try:
        b_action = str(bot_decision.get("action") or "").strip()
        s_action = str(sim_decision.get("action") or "").strip()
        if not b_action or not s_action:
            return None
        if b_action != s_action:
            return False
        # If both are training, compare the chosen stat
        b_stat = str(bot_decision.get("stat") or bot_decision.get("primary_stat") or "")
        s_stat = str(sim_decision.get("stat") or sim_decision.get("primary_stat") or "")
        if b_stat and s_stat:
            return b_stat == s_stat
        # Action labels match and we don't have finer detail; call it agreement
        return True
    except (AttributeError, TypeError):
        return None


def shadow_diff_path_for_career(runtime_root: str | Path, instance: str,
                                  career_id: str) -> Path:
    """Compute the canonical output path for a career's shadow diff log."""
    root = Path(runtime_root) / "instances" / instance / "sim_observations" / "shadow_diffs"
    return root / f"{career_id}.jsonl"
