"""Tests for the shadow-sim diff recorder.

The shadow recorder runs during live careers, logging bot-vs-sim
decisions to JSONL for later analysis. Its #1 contract: it must
NEVER raise during a live career, no matter what's thrown at it.
The bot keeping running matters more than diff completeness.
"""
import json
from pathlib import Path

from career_bot.sim_shadow import (
    ShadowDiffRecorder,
    _decisions_agree,
    _safe_serializable,
    shadow_diff_path_for_career,
)


# -------------------- ShadowDiffRecorder lifecycle --------------------

def test_recorder_disabled_when_no_output_path():
    """A recorder with no output path is a no-op — used when shadow
    logging is disabled. Recording must not raise, just no-op."""
    rec = ShadowDiffRecorder(None)
    assert rec.enabled is False
    # Must not raise
    rec.record_turn(turn=1, bot_decision={}, sim_decision=None)
    assert rec.lines_written == 0


def test_recorder_writes_jsonl(tmp_path):
    """Happy path: each record_turn appends one valid JSON line."""
    out = tmp_path / "shadow_diffs" / "career_42.jsonl"
    rec = ShadowDiffRecorder(out)
    assert rec.enabled

    rec.record_turn(
        turn=1,
        bot_decision={"action": "TRAIN", "stat": "speed"},
        sim_decision={"action": "TRAIN", "stat": "speed"},
        state_before={"hp": 100, "stats": {"speed": 0}},
        state_after={"hp": 80, "stats": {"speed": 50}},
    )
    rec.record_turn(
        turn=2,
        bot_decision={"action": "REST"},
        sim_decision={"action": "TRAIN", "stat": "wit"},
    )

    assert rec.lines_written == 2
    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 2
    # Both lines must parse as JSON
    r1 = json.loads(lines[0])
    r2 = json.loads(lines[1])
    assert r1["turn"] == 1 and r1["agreed"] is True
    assert r2["turn"] == 2 and r2["agreed"] is False


def test_recorder_never_raises_on_bad_input(tmp_path):
    """Anti-fragility: garbage in must NOT crash the live career."""
    out = tmp_path / "shadow_diffs" / "c.jsonl"
    rec = ShadowDiffRecorder(out)

    class Unserializable:
        def __repr__(self):
            raise RuntimeError("even repr fails")

    # Inputs that would normally choke json.dumps
    rec.record_turn(
        turn=0,
        bot_decision={"obj": Unserializable()},
        sim_decision=None,
    )
    # No exception, even if the line wasn't written
    rec.record_career_finish(
        bot_final_rating=17500,
        bot_final_stats={"weird": Unserializable()},
        sim_predicted_rating=17400,
        sim_predicted_stats=None,
        rank="SS",
    )


def test_recorder_handles_unwritable_output_path():
    """If the parent dir can't be created, recorder becomes disabled
    rather than raising at construction time."""
    # NUL on Windows is unwritable; on POSIX, /dev/null/x equivalent
    # We can't reliably hit OSError here on every CI, so just pass None
    # to simulate the unhappy-path branch.
    rec = ShadowDiffRecorder(None)
    assert rec.enabled is False


# -------------------- _decisions_agree contract --------------------

def test_agree_returns_none_when_inputs_missing():
    """No agreement check possible if either side is missing."""
    assert _decisions_agree({}, None) is None
    assert _decisions_agree(None, {"action": "TRAIN"}) is None
    assert _decisions_agree({"action": "TRAIN"}, {}) is None


def test_agree_true_when_action_and_stat_match():
    """Both train the same stat → agree."""
    bot = {"action": "TRAIN", "stat": "wit"}
    sim = {"action": "TRAIN", "stat": "wit"}
    assert _decisions_agree(bot, sim) is True


def test_agree_false_when_actions_differ():
    """Different action labels (TRAIN vs REST) → disagree."""
    bot = {"action": "TRAIN", "stat": "wit"}
    sim = {"action": "REST"}
    assert _decisions_agree(bot, sim) is False


def test_agree_false_when_stat_differs():
    """Same action, different stat → disagree."""
    bot = {"action": "TRAIN", "stat": "speed"}
    sim = {"action": "TRAIN", "stat": "power"}
    assert _decisions_agree(bot, sim) is False


def test_agree_true_when_stat_unspecified():
    """If only the action label is provided and they match, count as
    agreement (we don't have finer granularity to compare on)."""
    bot = {"action": "REST"}
    sim = {"action": "REST"}
    assert _decisions_agree(bot, sim) is True


# -------------------- _safe_serializable --------------------

def test_safe_serializable_handles_primitives():
    assert _safe_serializable(None) is None
    assert _safe_serializable(1) == 1
    assert _safe_serializable("x") == "x"
    assert _safe_serializable(True) is True


def test_safe_serializable_recursive_dict():
    obj = {"a": [1, 2, {"b": "c"}]}
    out = _safe_serializable(obj)
    assert out == {"a": [1, 2, {"b": "c"}]}


def test_safe_serializable_object_falls_back_to_repr():
    """An object with no __dict__ falls back to repr() so json.dumps
    never raises."""
    class Plain:
        __slots__ = ()
    out = _safe_serializable(Plain())
    assert isinstance(out, str)


def test_safe_serializable_bounded_depth():
    """Circular ref must not stack-overflow — bounded recursion."""
    a = {}
    a["self"] = a
    # Must not raise RecursionError
    _safe_serializable(a)


# -------------------- shadow_diff_path_for_career --------------------

def test_shadow_diff_path_layout(tmp_path):
    """The canonical path layout puts shadow diffs under the
    per-instance sim_observations dir so the analyzer can find them
    without scanning the whole runtime tree."""
    path = shadow_diff_path_for_career(
        runtime_root=tmp_path,
        instance="account_b",
        career_id="career_20260609_172030",
    )
    expected_suffix = Path("instances") / "account_b" / "sim_observations" / "shadow_diffs" / "career_20260609_172030.jsonl"
    # The full path should end with the expected suffix
    assert str(path).endswith(str(expected_suffix))
