"""Shared MANT/TSC fixed-event metadata.

These rows are not a replacement for live event observations. They are a
stable fallback/audit layer for the scenario events that repeatedly appear at
known career turns, so reports, observation exports, and the simulator agree on
calendar labels and known fixed effects.
"""

from __future__ import annotations

from typing import Any


MONTH_LABELS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

YEAR_LABELS = ("Junior", "Classic", "Senior")


MANT_STATIC_FIXED_EVENTS = (
    {"turn": 24, "story_id": "400004010", "event_id": 203059, "effects": {"Speed": 10, "Stamina": 10, "Power": 10, "Guts": 10, "Wisdom": 10, "Skill Pts": 20}},
    {"turn": 24, "story_id": "400004401", "event_id": 203010, "effects": {"Speed": 5, "Stamina": 5, "Power": 5, "Guts": 5, "Wisdom": 5, "Skill Pts": 30}},
    {"turn": 48, "story_id": "400004011", "event_id": 203060, "effects": {"Speed": 5, "Stamina": 5, "Power": 5, "Guts": 5, "Wisdom": 5, "Skill Pts": 30}},
    {"turn": 48, "story_id": "400004403", "event_id": 203011, "effects": {"Speed": 6, "Stamina": 6, "Power": 6, "Guts": 6, "Wisdom": 6, "Skill Pts": 40}},
    {"turn": 60, "story_id": "400004259", "event_id": 203559, "effects": {"Speed": 10}},
    {"turn": 60, "story_id": "400004260", "event_id": 203560, "effects": {"Stamina": 10}},
    {"turn": 68, "story_id": "400004285", "event_id": 203585, "effects": {"Wisdom": 10, "Mood": 1}},
    {"turn": 68, "story_id": "400004286", "event_id": 203586, "effects": {"Speed": 10, "Mood": 1}},
    {"turn": 72, "story_id": "400004012", "event_id": 203061, "effects": {"Speed": 10, "Stamina": 10, "Power": 10, "Guts": 10, "Wisdom": 10, "Skill Pts": 30}},
    {"turn": 72, "story_id": "400004405", "event_id": 203012, "effects": {"Speed": 7, "Stamina": 7, "Power": 7, "Guts": 7, "Wisdom": 7, "Skill Pts": 50}},
    {"turn": 74, "story_id": "400004050", "event_id": 203101, "effects": {}},
    {"turn": 74, "story_id": "400004051", "event_id": 203102, "effects": {"Speed": 10, "Stamina": 10, "Power": 10, "Guts": 10, "Wisdom": 10, "Skill Pts": 30}},
    {"turn": 76, "story_id": "400004060", "event_id": 203103, "effects": {}},
    {"turn": 76, "story_id": "400004061", "event_id": 203104, "effects": {"Speed": 10, "Stamina": 10, "Power": 10, "Guts": 10, "Wisdom": 10, "Skill Pts": 30}},
    {"turn": 78, "story_id": "400004070", "event_id": 203105, "effects": {}},
    {"turn": 78, "story_id": "400004071", "event_id": 203106, "effects": {"Speed": 10, "Stamina": 10, "Power": 10, "Guts": 10, "Wisdom": 10, "Skill Pts": 30}},
    {"turn": 78, "story_id": "400004601", "event_id": 203202, "effects": {"Speed": 10, "Stamina": 10, "Power": 10, "Guts": 10, "Wisdom": 10, "Skill Pts": 40}},
)

MANT_STATIC_FIXED_EVENT_BY_STORY = {
    str(event.get("story_id") or ""): event
    for event in MANT_STATIC_FIXED_EVENTS
    if str(event.get("story_id") or "")
}


def career_turn_calendar(turn: int) -> dict[str, Any]:
    turn = int(turn or 0)
    if turn <= 0:
        return {
            "turn": 0,
            "phase": "",
            "year": "",
            "half": "",
            "month": "",
            "label": "",
        }
    if turn <= 72:
        year_index = (turn - 1) // 24
        period_index = (turn - 1) % 24
        half = "Early" if period_index % 2 == 0 else "Late"
        month = MONTH_LABELS[min(11, period_index // 2)]
        year = YEAR_LABELS[min(2, year_index)]
        phase = year.lower()
        label = f"{year} {half} {month}"
    else:
        phase = "climax"
        year = "TS Climax"
        half = ""
        month = ""
        label = f"TS Climax Turn {turn}"
    return {
        "turn": turn,
        "phase": phase,
        "year": year,
        "half": half,
        "month": month,
        "label": label,
    }


def career_turn_label(turn: int) -> str:
    return str(career_turn_calendar(turn).get("label") or "")


def static_mant_event_for_story(story_id: str | int | None) -> dict[str, Any] | None:
    story = str(story_id or "").strip()
    return MANT_STATIC_FIXED_EVENT_BY_STORY.get(story)
