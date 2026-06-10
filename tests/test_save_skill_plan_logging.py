"""Smoke test for the skill-plan save logging.

Operator scenario: bot ran Front Runner for ~30 careers when the user
believed they had saved a different style. Investigation showed the save
endpoint had no debug output, so it was impossible to confirm what the
server actually received vs. what the UI sent. Now the endpoint logs the
incoming style/distance and what they normalize to, so the next
mismatch is one console glance away from being diagnosable.
"""
import io
from contextlib import redirect_stdout
from unittest.mock import MagicMock

import main


def _make_request(**overrides):
    """Build a minimal SaveSkillPlanRequest-shaped object."""
    req = MagicMock()
    req.preset_name = overrides.get("preset_name", "xguri parent")
    req.buy_on_sight = overrides.get("buy_on_sight", ["Groundwork"])
    req.blacklist = overrides.get("blacklist", [])
    req.style = overrides.get("style", "")
    req.distance = overrides.get("distance", "")
    req.buy_timing = overrides.get("buy_timing", "end_of_career")
    req.desired_sparks = overrides.get("desired_sparks", {})
    req.alarm_clock_mode = overrides.get("alarm_clock_mode", "")
    req.alarm_clock_limit = overrides.get("alarm_clock_limit", 0)
    return req


def test_save_endpoint_logs_incoming_style_and_normalized_style():
    """The endpoint must print both what the UI sent and what it
    normalizes to. If they differ, the user can spot the desync (e.g.,
    UI sent 'Pace' but server normalized to '' because of an alias gap)."""
    import asyncio
    req = _make_request(style="pace", distance="medium")

    # Mock the heavyweight downstream deps so we just exercise the
    # logging + normalize path
    main.preset_store.read_one = MagicMock(return_value={"name": "xguri parent"})
    main.preset_store.write = MagicMock(return_value={"name": "xguri parent"})

    buf = io.StringIO()
    with redirect_stdout(buf):
        asyncio.run(main.save_skill_plan(req))

    output = buf.getvalue()
    assert "[SAVE_SKILL_PLAN]" in output, (
        "Expected the new endpoint log line to appear; got:\n" + output
    )
    assert "style_in='pace'" in output
    assert "style_saved='pace_chaser'" in output  # normalized
    assert "distance_in='medium'" in output


def test_save_endpoint_logs_empty_style_distinctly():
    """Empty input must be visible too — that's the case where the UI
    desync caused the save to land an empty/auto value instead of the
    visible button choice."""
    import asyncio
    req = _make_request(style="", distance="")

    main.preset_store.read_one = MagicMock(return_value={"name": "xguri parent"})
    main.preset_store.write = MagicMock(return_value={"name": "xguri parent"})

    buf = io.StringIO()
    with redirect_stdout(buf):
        asyncio.run(main.save_skill_plan(req))

    output = buf.getvalue()
    assert "style_in=''" in output
    # Empty input normalizes to empty (no alias match)
    assert "style_saved=''" in output


def test_save_endpoint_logs_style_with_alias_normalization():
    """Aliases (front → front_runner, late → late_surger) should be
    surfaced in the log so the user can confirm the normalization."""
    import asyncio
    req = _make_request(style="late", distance="long")

    main.preset_store.read_one = MagicMock(return_value={"name": "xguri parent"})
    main.preset_store.write = MagicMock(return_value={"name": "xguri parent"})

    buf = io.StringIO()
    with redirect_stdout(buf):
        asyncio.run(main.save_skill_plan(req))

    output = buf.getvalue()
    assert "style_in='late'" in output
    assert "style_saved='late_surger'" in output
