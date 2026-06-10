"""Tests for the short running-style label that gets attached to every
race result row in turn data.

Operator ask: in turn data where the race outcome shows (won, stats,
mood, etc.), the row should also show the strat used — Front, Pace,
Late, or End. This catches the conversion contract for any of:

  - numeric tactic code (1/2/3/4 from the game API)
  - canonical snake_case style (front_runner/pace_chaser/late_surger/end_closer)
  - alias / display label / empty / None

so a refactor that adds a new lookup site doesn't accidentally surface
the raw code or an empty string in the user's logs.
"""
from career_bot.race_schedule import (
    STYLE_DISPLAY_LABEL,
    STYLE_TO_TACTIC,
    TACTIC_TO_STYLE,
    running_style_label,
)


def test_numeric_tactic_codes_map_to_short_labels():
    """The game API delivers race_running_style as 1-4. Each must map
    to its short display label."""
    assert running_style_label(1) == "Front"
    assert running_style_label(2) == "Pace"
    assert running_style_label(3) == "Late"
    assert running_style_label(4) == "End"


def test_canonical_styles_map_to_short_labels():
    """Internal code uses snake_case style names. Each must map."""
    assert running_style_label("front_runner") == "Front"
    assert running_style_label("pace_chaser") == "Pace"
    assert running_style_label("late_surger") == "Late"
    assert running_style_label("end_closer") == "End"


def test_display_labels_round_trip():
    """If the value is already 'Front'/'Pace'/'Late'/'End', return it
    unchanged. Idempotent so we can call running_style_label() on
    already-formatted data."""
    for label in ("Front", "Pace", "Late", "End"):
        assert running_style_label(label) == label
    # Case-insensitive: 'front' or 'FRONT' should also resolve
    assert running_style_label("front") == "Front"
    assert running_style_label("LATE") == "Late"


def test_unknown_or_empty_inputs_return_empty():
    """Anything we don't recognise returns '' so callers can detect
    'no label available' without try/except."""
    assert running_style_label(None) == ""
    assert running_style_label("") == ""
    assert running_style_label(0) == ""
    assert running_style_label(99) == ""
    assert running_style_label("not a style") == ""
    assert running_style_label({}) == ""


def test_style_display_label_covers_all_canonical_styles():
    """The STYLE_DISPLAY_LABEL map must cover every TACTIC_TO_STYLE
    entry. If a new style is added to the game and only mapped on the
    tactic side, this catches the gap."""
    for tactic, style in TACTIC_TO_STYLE.items():
        assert style in STYLE_DISPLAY_LABEL, (
            f"TACTIC_TO_STYLE has '{style}' (tactic {tactic}) but "
            f"STYLE_DISPLAY_LABEL doesn't"
        )


def test_style_to_tactic_round_trip():
    """For each canonical style, tactic→style→tactic round trips."""
    for style, tactic in STYLE_TO_TACTIC.items():
        assert TACTIC_TO_STYLE[tactic] == style
