"""Test that calibrate loads the same merged preset the live bot uses.

Bug observed 2026-06-10: calibrate was reading directly from the
instance-learning override file, bypassing the config layer (where the
UI's Save Skill Plan writes). When the operator saved style=Late, the
config.json had 'late_surger' but the instance override still had a
stale 'front_runner' from the previous day's auto-tuning. Calibrate
loaded the stale override and reported `strats=[Front:33 ...]`.

Fix: `_base_preset()` now goes through `main.resolve_effective_preset`,
which uses `_preserve_operator_owned_fields` to keep the operator's
saved style winning over any stale learned overrides. Same path the
live bot uses, so calibrate + live bot strategies match.
"""
from unittest.mock import patch

import main
from tools.optimize_deck_policy import _base_preset


def test_base_preset_uses_resolve_effective_preset_when_no_path_given():
    """When called with no preset_path, _base_preset must funnel through
    main.resolve_effective_preset rather than reading a file directly.
    This ensures the operator's UI-saved values win over stale learned
    overrides."""
    fake = {
        "name": "test preset",
        "skill_profile_style": "late_surger",  # operator's UI save
        "scenario_id": 4,
    }
    with patch.object(main, "resolve_effective_preset", return_value=fake) as mock_resolve, \
         patch.object(main, "default_run_preset_name", return_value="test preset"):
        out = _base_preset()
    mock_resolve.assert_called_once()
    assert out["skill_profile_style"] == "late_surger"
    # Optimizer adds the __optimizer suffix so its logs don't shadow the user's preset
    assert out["name"].endswith("__optimizer")


def test_base_preset_falls_back_to_file_load_when_resolution_fails():
    """If resolve_effective_preset raises (e.g., preset store mis-set
    in a test environment), fall back gracefully to direct file load
    rather than crashing the calibrate."""
    with patch.object(main, "resolve_effective_preset", side_effect=Exception("boom")), \
         patch.object(main, "default_run_preset_name", return_value="xguri parent"):
        # Should not raise — uses fallback path
        out = _base_preset()
    # In a test env the default fallback path may or may not exist; either
    # way we should get a dict (vanilla shape or the loaded file)
    assert isinstance(out, dict)
    assert "scenario_id" in out


def test_base_preset_explicit_path_bypasses_resolution(tmp_path):
    """When the caller passes preset_path explicitly (e.g., a unit test
    or a custom-preset workflow), use that file directly without going
    through resolve_effective_preset. This is the escape hatch."""
    import json
    preset_file = tmp_path / "explicit.json"
    preset_file.write_text(json.dumps({
        "name": "explicit_test",
        "skill_profile_style": "pace_chaser",
        "scenario_id": 4,
    }), encoding="utf-8")

    with patch.object(main, "resolve_effective_preset") as mock_resolve:
        out = _base_preset(preset_file)
    # Explicit path should NOT have called the resolver
    mock_resolve.assert_not_called()
    assert out["skill_profile_style"] == "pace_chaser"
    assert out["name"].endswith("__optimizer")
