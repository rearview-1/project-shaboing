"""Tests that the runner force-releases stuck careers in loop mode.

Observed failure: 18 successful careers, then a T24 game state with
`playing_state=5` and no home commands wedged. The runner's safe-by-
default behavior is to stop, but in loop mode the wedged career
persists server-side and every next iteration hits the same state,
eventually killing the loop after 5 consecutive failures.

Fix: when `_settle_state` detects "post-action without active race"
in loop mode, call `client.finish_career(is_force_delete=True)` to
release the wedged career so the next iteration starts clean.
"""

import threading
import types
import pytest
from career_bot.runner import CareerRunner


class _FakeClient:
    def __init__(self, finish_raises=False):
        self.finish_calls = []
        self.finish_raises = finish_raises

    def finish_career(self, current_turn=0, is_force_delete=False):
        self.finish_calls.append({"current_turn": current_turn, "is_force_delete": is_force_delete})
        if self.finish_raises:
            raise RuntimeError("simulated 1503 on finish")
        return {"data": {}}


def _make_runner():
    runner = CareerRunner.__new__(CareerRunner)
    runner.status = {"loop_mode": False, "finished": False, "running": False, "stop_requested": False}
    runner.stop_requested = False
    runner.report = None
    runner._active_preset = None
    runner.lock = threading.RLock()
    # Stub the log/mark/stop methods so they don't depend on full init
    logs = []
    runner._log = lambda kind, turn, detail: logs.append((kind, turn, detail))
    runner._mark = lambda **kwargs: runner.status.update(kwargs)
    runner.stop = lambda: runner.status.__setitem__("stop_requested", True)
    runner._logs = logs
    return runner


def test_force_release_called_in_loop_mode():
    runner = _make_runner()
    runner.status["loop_mode"] = True
    client = _FakeClient()
    runner._force_release_stuck_career(client, 24, "post-action stuck")
    assert len(client.finish_calls) == 1
    assert client.finish_calls[0] == {"current_turn": 24, "is_force_delete": True}
    assert any(entry[0] == "stuck_career_force_released" for entry in runner._logs)


def test_force_release_swallows_exceptions():
    runner = _make_runner()
    client = _FakeClient(finish_raises=True)
    # Must not raise — the runner is already in a stop path.
    runner._force_release_stuck_career(client, 24, "post-action stuck")
    assert any(entry[0] == "stuck_career_force_release_failed" for entry in runner._logs)


def test_settle_state_releases_stuck_career_in_loop_mode(monkeypatch):
    runner = _make_runner()
    runner.status["loop_mode"] = True
    client = _FakeClient()

    fresh_state = {
        "data": {
            "chara_info": {"turn": 24, "playing_state": 5, "state": 2, "race_program_id": 0},
        }
    }
    # Force the post-action-without-active-race path.
    runner._fresh_career_state = lambda c, s: fresh_state
    runner._is_post_action_without_active_race = lambda s: True
    runner._has_stale_race_metadata = lambda s: False
    runner._drain_events = lambda c, s, st: st

    result = runner._settle_state(client, None, fresh_state, {"current_turn": 24})

    assert len(client.finish_calls) == 1
    assert client.finish_calls[0]["is_force_delete"] is True
    assert runner.status["stop_requested"] is True
    assert result is fresh_state


def test_settle_state_skips_force_release_outside_loop_mode():
    runner = _make_runner()
    # loop_mode left False
    client = _FakeClient()
    fresh_state = {
        "data": {
            "chara_info": {"turn": 24, "playing_state": 5, "state": 2, "race_program_id": 0},
        }
    }
    runner._fresh_career_state = lambda c, s: fresh_state
    runner._is_post_action_without_active_race = lambda s: True
    runner._has_stale_race_metadata = lambda s: False
    runner._drain_events = lambda c, s, st: st

    runner._settle_state(client, None, fresh_state, {"current_turn": 24})

    # Non-loop: don't force-delete; let the user investigate.
    assert client.finish_calls == []
    assert runner.status["stop_requested"] is True


def test_watchdog_threshold_value_matches_documentation():
    """The settle_state watchdog threshold is documented in the runner
    comment as 5. If anyone tweaks the magic number, update the docs.

    This is a guard test — it reads the source so a code change without
    a comment change fails CI.
    """
    import inspect
    from career_bot import runner as runner_mod
    src = inspect.getsource(runner_mod.CareerRunner._run)
    assert "consecutive_settle >= 5" in src, "watchdog threshold should be 5"
    assert "settle_state watchdog tripped" in src
