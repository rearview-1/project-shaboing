#!/usr/bin/env python3
"""Build full trainee aptitude / growth map keyed by 6-digit card_id.

Sources:
- https://api.umapyoi.net/api/v1/outfit
- https://gametora.com/umamusume/characters/{gametora-slug}

The existing trainee menu falls back to a 4-digit base chara_id when a
card-specific entry is missing, which causes alternate outfits to inherit the
wrong growth rates and sometimes the wrong aptitudes. This script generates a
card-specific map for every known outfit and also writes a 4-digit fallback
entry for the lowest card_id of each base trainee.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Tuple
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


OUTFIT_API_URL = "https://api.umapyoi.net/api/v1/outfit"
GAMETORA_CHARACTER_URL = "https://gametora.com/umamusume/characters/{slug}"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "public" / "assets" / "data" / "chara_aptitude_map.json"
USER_AGENT = "Mozilla/5.0 (compatible; SweepyAptitudeBuilder/1.0)"

STAT_ORDER = ("Speed", "Stamina", "Power", "Guts", "Wit")
TERRAIN_ORDER = ("turf", "dirt")
DISTANCE_ORDER = ("sprint", "mile", "medium", "long")
STYLE_ORDER = ("front", "pace", "late", "end")
GRADE_SCORE = {"S": 8, "A": 7, "B": 6, "C": 5, "D": 4, "E": 3, "F": 2, "G": 1}

APTITUDE_LABEL_TO_KEY = {
    "Turf": "turf",
    "Dirt": "dirt",
    "Short": "sprint",
    "Mile": "mile",
    "Medium": "medium",
    "Long": "long",
    "Front": "front",
    "Pace": "pace",
    "Late": "late",
    "End": "end",
}

KEY_TO_DISPLAY = {
    "turf": "Turf",
    "dirt": "Dirt",
    "sprint": "Sprint",
    "mile": "Mile",
    "medium": "Medium",
    "long": "Long",
    "front": "Front",
    "pace": "Pace",
    "late": "Late",
    "end": "End",
}


def fetch_text(url: str, *, retries: int = 3, timeout: int = 30) -> str:
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = Request(url, headers={"User-Agent": USER_AGENT})
            with urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", "ignore")
        except (HTTPError, URLError, TimeoutError) as exc:
            last_error = exc
            if attempt >= retries:
                break
            time.sleep(0.5 * attempt)
    raise RuntimeError(f"failed to fetch {url}: {last_error}")


def fetch_json(url: str) -> object:
    return json.loads(fetch_text(url))


def parse_rarity(html: str) -> int | None:
    marker = '<div class="characters_infobox_item__kE_e0"><span>'
    idx = html.find(marker)
    if idx < 0:
        return None
    idx += len(marker)
    end = html.find("</span></div>", idx)
    if end < 0:
        return None
    stars = html[idx:end]
    return stars.count("⭐") or None


def parse_growths(html: str) -> List[Dict[str, int | str]]:
    match = re.search(
        r"Stat bonuses</div><div class=\"characters_infobox_stats__MHrw9\"><div class=\"characters_infobox_row__RNXnI\">(.*?)</div></div><div class=\"characters_infobox_caption__UHck_\">Aptitude",
        html,
        re.S,
    )
    if not match:
        raise ValueError("could not locate stat bonuses section")
    pairs = re.findall(r'alt="(Speed|Stamina|Power|Guts|Wit)".*?<div>([^<]+)</div>', match.group(1), re.S)
    if len(pairs) != 5:
        raise ValueError(f"unexpected stat bonus shape: {pairs!r}")
    ordered = {stat: value.strip() for stat, value in pairs}
    growths: List[Dict[str, int | str]] = []
    for stat in STAT_ORDER:
        raw = ordered.get(stat, "-")
        if raw == "-" or not raw:
            continue
        pct = int(raw.rstrip("%"))
        if pct:
            growths.append({"stat": stat, "pct": pct})
    return growths


def parse_aptitudes(html: str) -> Dict[str, str]:
    match = re.search(r"Aptitude</div>(.*?)<div class=\"incontent-ad-mobile\"", html, re.S)
    if not match:
        raise ValueError("could not locate aptitude section")
    block = match.group(1)
    aptitudes: Dict[str, str] = {}
    for label, key in APTITUDE_LABEL_TO_KEY.items():
        item_match = re.search(rf"<div>{re.escape(label)}</div><div>([A-GS])</div>", block)
        if not item_match:
            raise ValueError(f"missing aptitude for {label}")
        aptitudes[key] = item_match.group(1)
    return aptitudes


def best_key(aptitudes: Dict[str, str], keys: Iterable[str]) -> str | None:
    ranked = [(GRADE_SCORE.get(aptitudes.get(key, ""), 0), idx, key) for idx, key in enumerate(keys)]
    ranked = [row for row in ranked if row[0] > 0]
    if not ranked:
        return None
    ranked.sort(key=lambda row: (-row[0], row[1]))
    return ranked[0][2]


def build_entry(outfit: Dict[str, object]) -> Tuple[str, Dict[str, object]]:
    card_id = str(outfit["id"])
    slug = str(outfit["gametora"])
    url = GAMETORA_CHARACTER_URL.format(slug=slug)
    html = fetch_text(url)
    growths = parse_growths(html)
    aptitudes = parse_aptitudes(html)
    terrain_key = best_key(aptitudes, TERRAIN_ORDER)
    distance_key = best_key(aptitudes, DISTANCE_ORDER)
    style_key = best_key(aptitudes, STYLE_ORDER)
    entry: Dict[str, object] = {
        "name": str(slug.split("-", 1)[1].replace("-", " ").title()) if "-" in slug else str(outfit.get("title") or ""),
        "title": outfit.get("title"),
        "rarity": parse_rarity(html),
        "growths": growths,
        "terrain": KEY_TO_DISPLAY[terrain_key] if terrain_key else None,
        "distance": KEY_TO_DISPLAY[distance_key] if distance_key else None,
        "style": KEY_TO_DISPLAY[style_key] if style_key else None,
        "aptitudes": aptitudes,
        "source_slug": slug,
    }
    return card_id, entry


def build_map(outfits: List[Dict[str, object]], *, max_workers: int = 8) -> Dict[str, object]:
    result: Dict[str, object] = {
        "_doc": (
            "Aptitude / growth map for trainees. Primarily keyed by 6-digit card_id so alternate outfits keep "
            "their own growth rates and aptitudes. 4-digit base chara_id fallbacks are included for compatibility. "
            "Generated from Umapyoi outfit data + GameTora character pages."
        )
    }
    by_base: defaultdict[str, List[Tuple[int, Dict[str, object]]]] = defaultdict(list)
    errors: List[str] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
        future_map = {pool.submit(build_entry, outfit): outfit for outfit in outfits}
        for future in concurrent.futures.as_completed(future_map):
            outfit = future_map[future]
            try:
                card_id, entry = future.result()
            except Exception as exc:  # pragma: no cover - operational path
                errors.append(f"{outfit.get('id')} {outfit.get('gametora')}: {exc}")
                continue
            result[card_id] = entry
            base_id = str(outfit["chara_game_id"])
            by_base[base_id].append((int(card_id), entry))
    if errors:
        sample = "\n".join(errors[:10])
        raise RuntimeError(f"failed to build {len(errors)} outfit entries\n{sample}")
    for base_id, entries in by_base.items():
        entries.sort(key=lambda row: row[0])
        result[base_id] = entries[0][1]
    return dict(sorted(result.items(), key=lambda row: (row[0] == "_doc", row[0]) if row[0] == "_doc" else (1, row[0])))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--max-workers", type=int, default=8)
    args = parser.parse_args()

    outfits = fetch_json(OUTFIT_API_URL)
    if not isinstance(outfits, list):
        raise SystemExit("outfit API did not return a list")
    playable_outfits = [
        outfit
        for outfit in outfits
        if isinstance(outfit, dict)
        and outfit.get("id")
        and outfit.get("gametora")
        and outfit.get("chara_game_id")
    ]
    data = build_map(playable_outfits, max_workers=max(1, args.max_workers))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {len(data) - 1} trainee aptitude entries to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
