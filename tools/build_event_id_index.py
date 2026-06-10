"""Build the simulator event-id index from wiki-rendered event data and local logs.

The public wiki exposes support event ownership through the same Lua module it
uses to render card pages. Direct master DB queries are not available through
the normal API, so this script asks the module to render each support card's
training events, parses the story IDs/effects, and combines that with locally
observed career event choices from `uma_runtime`.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import html
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote

import requests


ROOT = Path(__file__).resolve().parents[1]
API_URL = "https://umamusu.wiki/w/api.php"
USER_AGENT = "SweepyCareerSimulator/1.0 (local data index builder)"
REQUIRED_SUPPORT_IDS = {30036}

EFFECT_NAMES = [
    "Skill points",
    "Skill Pts",
    "Skill Pt",
    "Max Energy",
    "Friendship",
    "Stamina",
    "Wisdom",
    "Energy",
    "Speed",
    "Power",
    "Guts",
    "Mood",
    "Bond",
    "Wit",
    "HP",
]

EFFECT_NAME_RE = "|".join(re.escape(name) for name in EFFECT_NAMES)
EFFECT_RE = re.compile(
    rf"\b((?:{EFFECT_NAME_RE})(?:/(?:{EFFECT_NAME_RE}))*)\s*([+-]?\d+(?:\.\d+)?)",
    re.IGNORECASE,
)
HINT_RE = re.compile(r"\bHint\s*([+-]?\d+(?:\.\d+)?)", re.IGNORECASE)
TAG_RE = re.compile(r"<[^>]+>")


def _strip_tags(value: str) -> str:
    text = TAG_RE.sub(" ", value or "")
    text = html.unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _canonical_effect_name(name: str) -> str:
    key = re.sub(r"\s+", " ", str(name or "").strip()).lower()
    if key in {"energy", "hp"}:
        return "HP"
    if key in {"skill points", "skill pt", "skill pts"}:
        return "Skill Pts"
    if key == "bond":
        return "Friendship"
    if key == "wit":
        return "Wisdom"
    if key == "max energy":
        return "Max Energy"
    return {
        "speed": "Speed",
        "stamina": "Stamina",
        "power": "Power",
        "guts": "Guts",
        "wisdom": "Wisdom",
        "mood": "Mood",
        "friendship": "Friendship",
    }.get(key, name)


def _add_effects(target: dict[str, float], effects: dict[str, float], scale: float = 1.0) -> None:
    for key, value in effects.items():
        numeric = float(value or 0) * scale
        if numeric:
            target[key] = round(float(target.get(key) or 0) + numeric, 3)


def _parse_simple_effects(text: str) -> dict[str, float]:
    effects: dict[str, float] = {}
    for match in EFFECT_RE.finditer(text or ""):
        names = [part.strip() for part in match.group(1).split("/") if part.strip()]
        try:
            value = float(match.group(2))
        except (TypeError, ValueError):
            continue
        for raw_name in names:
            key = _canonical_effect_name(raw_name)
            effects[key] = round(float(effects.get(key) or 0) + value, 3)
    hint_match = HINT_RE.search(text or "")
    if hint_match:
        try:
            effects["Skill Hint"] = round(float(effects.get("Skill Hint") or 0) + float(hint_match.group(1)), 3)
        except (TypeError, ValueError):
            pass
    return effects


def _parse_effects(text: str) -> dict[str, float]:
    clean = _strip_tags(text)
    success_match = re.search(r"\bOn Success:\s*", clean, re.IGNORECASE)
    failure_match = re.search(r"\bOn Failure:\s*", clean, re.IGNORECASE)
    if success_match and failure_match and success_match.start() < failure_match.start():
        base = clean[: success_match.start()]
        success = clean[success_match.end() : failure_match.start()]
        failure = clean[failure_match.end() :]
        effects: dict[str, float] = {}
        _add_effects(effects, _parse_simple_effects(base), 1.0)
        _add_effects(effects, _parse_simple_effects(success), 0.75)
        _add_effects(effects, _parse_simple_effects(failure), 0.25)
        return effects
    return _parse_simple_effects(clean)


def _choice_label(choice_html: str) -> str:
    text = _strip_tags(choice_html)
    # Tooltip text duplicates JP/skill descriptions. Keep the first readable part.
    if " " in text:
        parts = re.split(r"\s{2,}|(?<=[.!?])\s+(?=[A-Z])", text)
        return parts[0].strip() if parts else text
    return text


def _parse_event_boxes(rendered_html: str) -> list[dict]:
    events: list[dict] = []
    for chunk in re.split(r'<div class="training-event-box">', rendered_html or "")[1:]:
        story_match = re.search(r"/Game:Training_Events/(\d+)", chunk)
        title_match = re.search(r'<div class="training-event-title-text"><b>(.*?)</b>', chunk, re.S)
        if not story_match or not title_match:
            continue
        story_id = story_match.group(1)
        event_name = _strip_tags(title_match.group(1))
        chain_num = 0
        chain_max = 0
        chain_match = re.search(r"\((\d+)\s*/\s*(\d+)\)", _strip_tags(chunk))
        if chain_match:
            chain_num = int(chain_match.group(1))
            chain_max = int(chain_match.group(2))

        choices = []
        choice_matches = list(re.finditer(
            r'<div class="training-event-choice training-event-choice-(\d+)">(.*?)</div>\s*'
            r'<div class="training-event-description">(.*?)</div>',
            chunk,
            flags=re.S,
        ))
        if choice_matches:
            for match in choice_matches:
                effects = _parse_effects(match.group(3))
                if not effects:
                    continue
                choices.append({
                    "choice": str(int(match.group(1)) - 1),
                    "label": _choice_label(match.group(2)),
                    "description": _strip_tags(match.group(3)),
                    "effects": effects,
                })
        else:
            desc_matches = re.findall(r'<div class="training-event-description">(.*?)</div>', chunk, flags=re.S)
            for idx, desc_html in enumerate(desc_matches):
                effects = _parse_effects(desc_html)
                if not effects:
                    continue
                choices.append({
                    "choice": str(idx),
                    "label": "",
                    "description": _strip_tags(desc_html),
                    "effects": effects,
                })
        events.append({
            "story_id": story_id,
            "event_name": event_name,
            "chain_num": chain_num,
            "chain_max": chain_max,
            "choices": choices,
        })
    return events


def _post_parse(session: requests.Session, text: str, retries: int = 3) -> str:
    payload = {
        "action": "parse",
        "contentmodel": "wikitext",
        "text": text,
        "prop": "text",
        "format": "json",
    }
    last_error = None
    for attempt in range(retries):
        try:
            response = session.post(API_URL, data=payload, timeout=40)
            response.raise_for_status()
            data = response.json()
            return ((data.get("parse") or {}).get("text") or {}).get("*") or ""
        except Exception as exc:  # noqa: BLE001 - keep the builder resilient.
            last_error = exc
            time.sleep(0.5 + attempt)
    raise RuntimeError(f"wiki parse failed: {last_error}")


def _fetch_support_events(session: requests.Session, support_id: int) -> tuple[str, list[dict], str | None]:
    try:
        rendered = _post_parse(session, f"{{{{#invoke:Game/TrainingEvents|supportPageInsert|{support_id}}}}}")
        return str(support_id), _parse_event_boxes(rendered), None
    except Exception as exc:  # noqa: BLE001 - keep other card IDs usable.
        return str(support_id), [], str(exc)


def _fetch_story_title(session: requests.Session, story_id: str) -> tuple[str, str]:
    rendered = _post_parse(session, f"{{{{#invoke:Game/TrainingEvents|eventPage|Dummy|storyId={story_id}}}}}")
    title_match = re.search(r'<div class="training-event-title-text"><b>(.*?)</b>', rendered, re.S)
    return story_id, _strip_tags(title_match.group(1)) if title_match else ""


def _load_support_ids(root: Path, all_cards: bool) -> list[int]:
    ids: set[int] = set()
    if all_cards:
        data = json.loads((root / "data" / "support_card_bonuses.json").read_text(encoding="utf-8"))
        for key in data:
            if str(key).isdigit():
                ids.add(int(key))
        return sorted(ids)

    for path in (root / "uma_runtime").rglob("career_log_*.json"):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        ctx = report.get("run_context") or {}
        for raw_id in ctx.get("support_card_ids") or []:
            try:
                ids.add(int(raw_id))
            except (TypeError, ValueError):
                pass
        try:
            friend_id = int(ctx.get("friend_card_id") or 0)
        except (TypeError, ValueError):
            friend_id = 0
        if friend_id:
            ids.add(friend_id)
    ids.update(REQUIRED_SUPPORT_IDS)
    return sorted(ids)


def _story_source_from_id(story_id: str) -> tuple[str, str]:
    story = str(story_id or "")
    if len(story) >= 9 and story.startswith("8") and story[1:6].isdigit():
        return "support_card", str(int(story[1:6]))
    if story.startswith("5"):
        return "chara", ""
    if story.startswith("4"):
        return "scenario", ""
    return "guest", "0"


def _observed_events(root: Path, support_story_owner: dict[str, str]) -> tuple[dict, set[str]]:
    observed = {
        "support_card_events": defaultdict(lambda: defaultdict(lambda: {"count": 0, "choice_counts": Counter()})),
        "chara_events": defaultdict(lambda: defaultdict(lambda: {"count": 0, "choice_counts": Counter()})),
        "scenario_events": defaultdict(lambda: defaultdict(lambda: {"count": 0, "choice_counts": Counter()})),
        "guest_events": defaultdict(lambda: defaultdict(lambda: {"count": 0, "choice_counts": Counter()})),
    }
    titles_needed: set[str] = set()
    for path in (root / "uma_runtime").rglob("career_log_*.json"):
        try:
            report = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        ctx = report.get("run_context") or {}
        trainee_id = str(ctx.get("trainee_card_id") or "")
        scenario_id = str(report.get("scenario_id") or ctx.get("scenario_id") or 4)
        for turn in report.get("turns") or []:
            for event in turn.get("events") or []:
                if event.get("event") != "event_choice":
                    continue
                story_id = str(event.get("story_id") or "")
                if not story_id:
                    continue
                source, source_id = _story_source_from_id(story_id)
                if story_id in support_story_owner:
                    source = "support_card"
                    source_id = support_story_owner[story_id]
                elif source == "chara":
                    source_id = trainee_id
                elif source == "scenario":
                    source_id = scenario_id
                bucket = f"{source}_events"
                entry = observed[bucket][str(source_id)][story_id]
                entry["count"] += 1
                entry["choice_counts"][str(event.get("choice_index") or 0)] += 1
                if not support_story_owner.get(story_id):
                    titles_needed.add(story_id)

    serial = {}
    for bucket, by_source in observed.items():
        serial[bucket] = {}
        for source_id, by_story in by_source.items():
            rows = []
            for story_id, entry in by_story.items():
                rows.append({
                    "story_id": story_id,
                    "count": int(entry["count"]),
                    "choice_counts": dict(entry["choice_counts"]),
                })
            rows.sort(key=lambda row: (-row["count"], row["story_id"]))
            serial[bucket][source_id] = rows
    return serial, titles_needed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all-supports", action="store_true", help="Fetch every support in support_card_bonuses.json.")
    parser.add_argument("--output", default=str(ROOT / "data" / "event_id_index.json"))
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--skip-wiki", action="store_true")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    support_ids = _load_support_ids(ROOT, all_cards=args.all_supports)
    support_events: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}
    if not args.skip_wiki and support_ids:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            futures = [executor.submit(_fetch_support_events, session, support_id) for support_id in support_ids]
            for future in concurrent.futures.as_completed(futures):
                support_id, events, error = future.result()
                support_events[support_id] = events
                if error:
                    errors[support_id] = error

    support_story_owner = {}
    for support_id, events in support_events.items():
        for event in events:
            story_id = str(event.get("story_id") or "")
            if story_id:
                support_story_owner[story_id] = support_id

    observed, titles_needed = _observed_events(ROOT, support_story_owner)
    event_titles: dict[str, str] = {}
    if not args.skip_wiki and titles_needed:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
            futures = [executor.submit(_fetch_story_title, session, story_id) for story_id in sorted(titles_needed)]
            for future in concurrent.futures.as_completed(futures):
                try:
                    story_id, title = future.result()
                except Exception:
                    continue
                if title:
                    event_titles[story_id] = title

    for bucket in ("support_card_events", "chara_events", "scenario_events", "guest_events"):
        for rows in observed.get(bucket, {}).values():
            for row in rows:
                row["event_name"] = event_titles.get(row["story_id"], row.get("event_name", ""))

    output = {
        "schema": "sweepy_event_id_index_v1",
        "sources": {
            "support_events": "https://umamusu.wiki/Module:Game/TrainingEvents and https://umamusu.wiki/Module:Game/Supports/Data/Events",
            "observed_events": "uma_runtime/**/bot_logs/career_log_*.json",
        },
        "support_card_events": support_events,
        "observed": observed,
        "errors": errors,
    }
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    print(f"wrote {out_path}")
    print(f"support cards indexed: {len(support_events)}")
    print(f"support events indexed: {sum(len(rows) for rows in support_events.values())}")
    print(f"observed chara sources: {len(observed.get('chara_events', {}))}")
    print(f"observed scenario events: {sum(len(rows) for rows in observed.get('scenario_events', {}).values())}")
    if errors:
        print(f"support fetch errors: {len(errors)}")
    print(f"wiki support URL example: https://umamusu.wiki/{quote('Module:Game/Supports/Data/Events')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
