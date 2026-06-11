"""Smoke test for the skill-plan save logging.

Operator scenario: bot ran Front Runner for ~30 careers when the user
believed they had saved a different style. Investigation showed the save
endpoint had no debug output, so it was impossible to confirm what the
server actually received vs. what the UI sent. Now the endpoint logs the
incoming style/distance and what they normalize to, so the next
mismatch is one console glance away from being diagnosable.
"""
import io
import json
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


def test_save_endpoint_scrubs_stale_instance_learning_style(monkeypatch, tmp_path):
    """Saving the visible strategy must invalidate stale account-local overlays.

    This guards the real bug where an old instance-learning JSON kept
    `skill_profile_style=front_runner` after the UI had saved Late Surger.
    """
    import asyncio
    from career_bot.presets import instance_learning_override_path

    class Store:
        def read_one(self, name):
            return {"name": name}

        def write(self, preset):
            return dict(preset)

    monkeypatch.setattr(main, "preset_store", Store())
    monkeypatch.setenv("SWEEPY_AUTO_LEARNING_SCOPE", "instance_local")
    monkeypatch.setenv("UMA_RUNTIME_DIR", str(tmp_path))

    path = instance_learning_override_path(main.DIR, "xguri parent")
    path.write_text(
        json.dumps(
            {
                "name": "xguri parent",
                "rest_threshold": 72,
                "skill_profile_style": "front_runner",
                "skill_profile_distance": "mile",
                "learn_skill_blacklist": ["stale"],
            }
        ),
        encoding="utf-8",
    )

    req = _make_request(style="late", distance="medium")
    asyncio.run(main.save_skill_plan(req))

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["rest_threshold"] == 72
    assert "skill_profile_style" not in raw
    assert "skill_profile_distance" not in raw
    assert "learn_skill_blacklist" not in raw


def test_save_endpoint_hot_patches_active_runner(monkeypatch):
    """Saving mid-career must update the active runner immediately.

    File polling is too slow and full preset replacement can disturb runtime
    context. The save endpoint should push only operator-owned skill-plan fields
    into the in-memory active preset so the next race uses the new style.
    """
    import asyncio

    class Store:
        def read_one(self, name):
            return {"name": name, "_run_context": {"deck": "keep-runtime"}}

        def write(self, preset):
            return dict(preset)

    class Runner:
        def __init__(self):
            self.calls = []

        def update_active_preset_fields(self, preset_name, fields, *, reason="operator_save"):
            self.calls.append((preset_name, dict(fields), reason))
            return True

    runner = Runner()
    monkeypatch.setattr(main, "preset_store", Store())
    monkeypatch.setattr(main, "career_runner", runner)
    monkeypatch.setenv("SWEEPY_AUTO_LEARNING_SCOPE", "shared")

    req = _make_request(style="late", distance="medium", buy_timing="throughout")
    result = asyncio.run(main.save_skill_plan(req))

    assert result["hot_reloaded"] is True
    assert len(runner.calls) == 1
    preset_name, fields, reason = runner.calls[0]
    assert preset_name == "xguri parent"
    assert reason == "save_skill_plan"
    assert fields["skill_profile_style"] == "late_surger"
    assert fields["skill_profile_distance"] == "medium"
    assert fields["manual_purchase_at_end"] is False
    assert "learn_skill_list" in fields
    assert "_run_context" not in fields


def test_race_picker_save_hot_patches_active_runner_calendar(monkeypatch):
    """Calendar edits must affect the running career before the next decision."""
    import asyncio

    race_id = next(iter(sorted(main.race_catalog.by_id.keys())))

    class Store:
        def read_one(self, name):
            return {"name": name}

        def write(self, preset):
            return dict(preset)

    class Runner:
        def __init__(self):
            self.calls = []

        def update_active_preset_fields(self, preset_name, fields, *, reason="operator_save"):
            self.calls.append((preset_name, dict(fields), reason))
            return True

    runner = Runner()
    monkeypatch.setattr(main, "preset_store", Store())
    monkeypatch.setattr(main, "career_runner", runner)
    monkeypatch.setenv("SWEEPY_AUTO_LEARNING_SCOPE", "shared")

    result = asyncio.run(
        main.save_races(
            main.SaveRacesRequest(
                preset_name="xguri parent",
                races=[race_id],
                styles={str(race_id): "late_surger"},
            )
        )
    )

    assert result["success"] is True
    assert result["hot_reloaded"] is True
    assert len(runner.calls) == 1
    preset_name, fields, reason = runner.calls[0]
    assert preset_name == "xguri parent"
    assert reason == "save_races"
    assert race_id in fields["race_list"]
    assert race_id in fields["extra_race_list"]
    assert fields["custom_race_schedule"][0]["style"] == "late_surger"
