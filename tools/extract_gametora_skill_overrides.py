"""Extract GameTora skill names/descriptions for Hachimi patching.

GameTora publishes its skill database as a static Next.js chunk containing a
JSON.parse payload. This script fetches the current page, finds that chunk, and
writes a compact ID-keyed override file used by apply_gametora_hachimi_skill_names.py.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests


DEFAULT_PAGE_URL = "https://gametora.com/umamusume/skill-condition-viewer"


EFFECT_TYPES = {
    9: ("Current HP", 100.0, "%"),
    21: ("Current Speed", 10000.0, "m/s"),
    22: ("Current Speed (natural decel)", 10000.0, "m/s"),
    27: ("Target Speed", 10000.0, "m/s"),
    28: ("Lane Movement Speed", 100.0, "%"),
    31: ("Acceleration", 10000.0, "m/s^2"),
}

CONDITION_LABELS = {
    "is_lastspurt==1": "Last spurt (mode)",
    "is_last_straight==1": "Last Straight",
    "is_finalcorner==1": "Final Corner",
    "phase_random==1": "Middle leg (random)",
    "phase_firsthalf_random==1": "Middle leg first half (random)",
    "phase_firsthalf_random==3": "Final leg first half (random)",
    "accumulatetime>=10": "10s passed",
}


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def fetch_text(url: str) -> str:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.text


def script_urls(page_url: str, html: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r'<script[^>]+src="([^"]+)"', html):
        src = match.group(1)
        if "/_next/static/chunks/" not in src:
            continue
        urls.append(urljoin(page_url, src))
    return urls


def parse_json_parse_payload(js: str) -> list[dict[str, Any]] | None:
    match = re.search(r"exports=JSON\.parse\('(.*?)'\)", js)
    if not match:
        return None
    payload = ast.literal_eval("'" + match.group(1) + "'")
    data = json.loads(payload)
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        return None
    if not any("id" in row and ("enname" in row or "name_en" in row) for row in data):
        return None
    return data


def clean_seconds(value: Any) -> str:
    try:
        seconds = float(value or 0) / 10000.0
    except (TypeError, ValueError):
        seconds = 0.0
    if seconds <= 0:
        return ""
    if abs(seconds - round(seconds)) < 0.0001:
        return f"{int(round(seconds))} s"
    return f"{seconds:.1f} s"


def clean_effect_value(value: Any, scale: float, suffix: str) -> str:
    try:
        number = float(value or 0) / scale
    except (TypeError, ValueError):
        number = 0.0
    sign = "+" if number >= 0 else ""
    if suffix == "%":
        return f"{sign}{number:g}%"
    return f"{sign}{number:.2f} {suffix}".replace(".00", "")


def describe_effect(effect: dict[str, Any]) -> str:
    try:
        effect_type = int(effect.get("type") or 0)
    except (TypeError, ValueError):
        effect_type = 0
    label, scale, suffix = EFFECT_TYPES.get(effect_type, (f"Effect {effect_type}", 1.0, ""))
    return f"{label} {clean_effect_value(effect.get('value'), scale, suffix).strip()}"


def describe_condition(condition: str) -> str:
    text = str(condition or "").strip()
    if not text:
        return "Always"
    parts = []
    for raw in re.split(r"([&@])", text):
        if raw == "&":
            parts.append("AND")
            continue
        if raw == "@":
            parts.append("OR")
            continue
        token = raw.strip()
        if not token:
            continue
        if token in CONDITION_LABELS:
            parts.append(CONDITION_LABELS[token])
        elif token.startswith("behind_near_lane_time>="):
            parts.append(f"Close behind opponent for >={token.split('>=', 1)[1]}s")
        elif token.startswith("infront_near_lane_time>="):
            parts.append(f"Close in front of opponent for >={token.split('>=', 1)[1]}s")
        elif token.startswith("distance_type=="):
            distance = {"1": "Sprint", "2": "Mile", "3": "Medium", "4": "Long"}.get(token.rsplit("==", 1)[1])
            parts.append(distance or token)
        elif token.startswith("order_rate<="):
            parts.append(f"In leading {token.rsplit('<=', 1)[1]}%")
        elif token.startswith("order_rate>="):
            parts.append(f"In trailing {100 - int(token.rsplit('>=', 1)[1])}%")
        else:
            parts.append(token.replace("==", " = ").replace(">=", " >= ").replace("<=", " <= "))
    return " ".join(parts)


def mechanics_description(row: dict[str, Any]) -> str:
    lines: list[str] = []
    for group in row.get("condition_groups") or []:
        if not isinstance(group, dict):
            continue
        effects = [describe_effect(effect) for effect in group.get("effects") or [] if isinstance(effect, dict)]
        if not effects:
            continue
        duration = clean_seconds(group.get("base_time"))
        effect_text = ", ".join(effects)
        if duration:
            effect_text = f"{effect_text} for {duration}"
        cd = clean_seconds(group.get("cd"))
        cd_text = f" (CD {cd})" if cd else ""
        condition = describe_condition(group.get("condition") or group.get("precondition") or "")
        precondition = group.get("precondition")
        if group.get("condition") and precondition:
            condition = f"{condition} after: {describe_condition(precondition)}"
        lines.append(f"<b>{effect_text}</b>{cd_text} when: {condition}")
    return "\n".join(lines)


def choose_name(row: dict[str, Any]) -> str:
    return str(row.get("name_en") or row.get("enname") or row.get("jpname") or "").strip()


def choose_plain_description(row: dict[str, Any]) -> str:
    return str(row.get("desc_en") or row.get("endesc") or row.get("jpdesc") or "").strip()


def extract(page_url: str) -> dict[str, Any]:
    html = fetch_text(page_url)
    for url in script_urls(page_url, html):
        js = fetch_text(url)
        rows = parse_json_parse_payload(js)
        if not rows:
            continue
        skills: dict[str, Any] = {}
        for row in rows:
            try:
                skill_id = int(row.get("id") or 0)
            except (TypeError, ValueError):
                skill_id = 0
            if not skill_id:
                continue
            name = choose_name(row)
            plain_desc = choose_plain_description(row)
            mechanics_desc = mechanics_description(row)
            skills[str(skill_id)] = {
                "name": name,
                "plain_description": plain_desc,
                "mechanics_description": mechanics_desc or plain_desc,
                "source_name_field": "name_en" if row.get("name_en") else "enname" if row.get("enname") else "jpname",
            }
        return {
            "source": "GameTora",
            "source_url": page_url,
            "chunk_url": url,
            "skills": skills,
        }
    raise RuntimeError("could not find GameTora skill JSON payload")


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract GameTora skill names and mechanics fallback descriptions.")
    parser.add_argument("--url", default=DEFAULT_PAGE_URL)
    parser.add_argument(
        "--output",
        default=str(project_root() / "data" / "gametora_skill_overrides.json"),
    )
    args = parser.parse_args()
    data = extract(args.url)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(data.get('skills') or {})} skills -> {output}")
    sample = (data.get("skills") or {}).get("414011")
    if sample:
        print(f"414011: {sample.get('name')} | {sample.get('mechanics_description')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
