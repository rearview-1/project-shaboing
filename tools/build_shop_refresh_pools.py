"""Build structured MANT shop refresh pool data from Hakuraku.

The live page renders from two raw sources:
  * /api/shop-refresh carries sampled pool odds and histograms.
  * /data/gamedata.bin.gz carries item display labels/icons.

The generated JSON is checked in so the bot never depends on Hakuraku during a
career run.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "data" / "shop_refresh_pools.json"
API_URL = "https://hakuraku.moe/api/shop-refresh"
METADATA_URL = "https://hakuraku.moe/data/gamedata.bin.gz"
PAGE_URL = "https://hakuraku.moe/shop-refresh"

RACE_GRADE_LABELS = {
    100: "G1",
    200: "G2",
    300: "G3",
    400: "OP",
    700: "Pre-OP",
    900: "Maiden Race",
}

EVENT_LABELS = {
    "Victory!": "victory",
    "Solid Showing": "solid_showing",
    "Defeat": "defeat",
    "Etsuko's Elated Coverage": "etsuko_elated",
    "Etsuko's Exhaustive Coverage": "etsuko_exhaustive",
}

REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36 SweepyDataFetcher/1.0"
    ),
    "Accept": "application/json,text/plain,*/*",
    "Referer": PAGE_URL,
}


def _load_item_names() -> tuple[dict[int, str], dict[str, int]]:
    sys.path.insert(0, str(ROOT))
    from career_bot.items import DISPLAY_TO_ID, ITEM_NAMES  # pylint: disable=import-outside-toplevel

    return {int(k): str(v) for k, v in ITEM_NAMES.items()}, {str(k): int(v) for k, v in DISPLAY_TO_ID.items()}


def _request_bytes(url: str, *, retries: int = 5, timeout: int = 45) -> bytes:
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers=REQUEST_HEADERS)
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last_exc = exc
            time.sleep(min(8, 1.5 + attempt * 1.5))
    raise RuntimeError(f"failed to fetch {url}: {last_exc}") from last_exc


def _load_api(path: Path | None = None) -> dict[str, Any]:
    raw = path.read_bytes() if path else _request_bytes(API_URL)
    return json.loads(raw.decode("utf-8-sig"))


def _load_metadata(path: Path | None = None) -> dict[str, Any]:
    raw = path.read_bytes() if path else _request_bytes(METADATA_URL)
    return json.loads(gzip.decompress(raw).decode("utf-8-sig"))


def _round(value: Any, places: int = 6) -> Any:
    if isinstance(value, float):
        return round(value, places)
    return value


def _histogram(rows: list[dict[str, Any]], samples: int, *, min_count: int = 0, max_count: int | None = None) -> dict[str, dict[str, Any]]:
    counts = {int(row.get("itemCount") or 0): int(row.get("samples") or 0) for row in rows}
    if max_count is None:
        max_count = max(counts.keys(), default=0)
    result: dict[str, dict[str, Any]] = {}
    for count in range(min_count, max_count + 1):
        n = int(counts.get(count, 0))
        result[str(count)] = {
            "samples": n,
            "appearance_rate": _round((n / samples * 100.0) if samples else 0.0),
        }
    return result


def _expected(item: dict[str, Any]) -> float:
    return float(item.get("appearanceRate") or 0.0) / 100.0 * float(item.get("avgCopies") or 0.0)


def _turn_from_group(group_id: int) -> int:
    return int(group_id) * 6 + 6


def _race_key(grade: int, event: str) -> str:
    grade_label = RACE_GRADE_LABELS.get(int(grade), f"grade_{grade}").replace("-", "").replace(" ", "")
    event_label = EVENT_LABELS.get(str(event), str(event).strip().lower().replace(" ", "_").replace("'", "").replace("!", ""))
    return f"{grade_label}_{event_label}"


def _metadata_items(metadata: dict[str, Any]) -> dict[int, dict[str, Any]]:
    shop = metadata.get("shop_refresh/data") or {}
    by_id: dict[int, dict[str, Any]] = {}
    containers: list[Any] = list(shop.get("scheduledTurns") or [])
    graded = shop.get("gradedRacePool")
    if isinstance(graded, dict):
        containers.append(graded)
    elif isinstance(graded, list):
        containers.extend(graded)
    for container in containers:
        if not isinstance(container, dict):
            continue
        for row in container.get("items") or []:
            if not isinstance(row, dict):
                continue
            item_id = int(row.get("id") or 0)
            if item_id <= 0:
                continue
            by_id.setdefault(item_id, {
                "hakuraku_display_name": row.get("name") or "",
                "icon": row.get("icon") or "",
            })
    return by_id


def _item_row(item: dict[str, Any], item_names: dict[int, str], metadata_by_id: dict[int, dict[str, Any]]) -> dict[str, Any]:
    item_id = int(item.get("itemId") or item.get("id") or 0)
    meta = metadata_by_id.get(item_id) or {}
    return {
        "item_id": item_id,
        "bot_display_name": item_names.get(item_id, ""),
        "hakuraku_display_name": meta.get("hakuraku_display_name") or item_names.get(item_id, ""),
        "icon": meta.get("icon") or "",
        "batches": int(item.get("batches") or 0),
        "appearance_rate": _round(float(item.get("appearanceRate") or 0.0)),
        "avg_copies": _round(float(item.get("avgCopies") or 0.0)),
        "expected_copies": _round(_expected(item)),
        "avg_price": _round(float(item.get("avgPrice") or 0.0)),
        "max_copies": int(item.get("maxCopies") or 0),
    }


def build_shop_refresh_pools(api: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
    item_names, display_to_id = _load_item_names()
    metadata_by_id = _metadata_items(metadata)

    scheduled: dict[str, dict[str, Any]] = {}
    scheduled_refreshes: dict[str, dict[str, Any]] = {}
    race: dict[str, dict[str, Any]] = {}
    race_refreshes: dict[str, dict[str, Any]] = {}
    mapping: dict[str, dict[str, Any]] = {}
    unmapped: list[str] = []

    def record_mapping(item_id: int) -> None:
        meta = metadata_by_id.get(item_id) or {}
        label = str(meta.get("hakuraku_display_name") or item_names.get(item_id, "")).strip()
        if not label:
            return
        bot_name = item_names.get(item_id, "")
        direct = display_to_id.get(label)
        mapping[label] = {
            "item_id": item_id if bot_name else None,
            "bot_display_name": bot_name,
            "mapped": bool(bot_name),
            "method": "display_name" if direct == item_id else "metadata_item_id",
            "needs_display_alias": direct != item_id,
        }
        if not bot_name and label not in unmapped:
            unmapped.append(label)

    for group in sorted(api.get("scheduledShops") or [], key=lambda row: int(row.get("groupId") or 0)):
        group_id = int(group.get("groupId") or 0)
        turn = _turn_from_group(group_id)
        samples = int(group.get("samples") or 0)
        items_by_id: dict[str, dict[str, Any]] = {}
        for item in group.get("items") or []:
            row = _item_row(item, item_names, metadata_by_id)
            item_id = row["item_id"]
            record_mapping(item_id)
            items_by_id[str(item_id)] = row
            agg = scheduled.setdefault(str(item_id), {
                "item_id": item_id,
                "bot_display_name": row["bot_display_name"],
                "hakuraku_display_name": row["hakuraku_display_name"],
                "icon": row["icon"],
                "expected_copies_by_turn": {},
                "appearance_rate_by_turn": {},
                "avg_copies_when_spawned_by_turn": {},
                "avg_price_by_turn": {},
                "max_copies_by_turn": {},
                "max_copies": 0,
                "appearance_rate": 0.0,
            })
            agg["expected_copies_by_turn"][str(turn)] = row["expected_copies"]
            agg["appearance_rate_by_turn"][str(turn)] = row["appearance_rate"]
            agg["avg_copies_when_spawned_by_turn"][str(turn)] = row["avg_copies"]
            agg["avg_price_by_turn"][str(turn)] = row["avg_price"]
            agg["max_copies_by_turn"][str(turn)] = row["max_copies"]
            agg["max_copies"] = max(int(agg["max_copies"]), int(row["max_copies"]))

        scheduled_refreshes[str(turn)] = {
            "turn": turn,
            "group_id": group_id,
            "samples": samples,
            "contributors": int(group.get("contributors") or 0),
            "avg_new_items": _round(float(group.get("avgItems") or 0.0)),
            "items_per_refresh_distribution": _histogram(group.get("itemCountDistribution") or [], samples),
            "items": items_by_id,
        }

    total_scheduled = sum(int(group.get("samples") or 0) for group in api.get("scheduledShops") or [])
    for item_id, agg in scheduled.items():
        batches = 0
        for group in api.get("scheduledShops") or []:
            for item in group.get("items") or []:
                if str(int(item.get("itemId") or 0)) == item_id:
                    batches += int(item.get("batches") or 0)
        agg["appearance_rate"] = _round((batches / total_scheduled * 100.0) if total_scheduled else 0.0)

    for group in sorted(
        api.get("raceGrades") or [],
        key=lambda row: (int(row.get("raceGrade") or 0), str(row.get("event") or "")),
    ):
        grade = int(group.get("raceGrade") or 0)
        event = str(group.get("event") or "")
        key = _race_key(grade, event)
        samples = int(group.get("samples") or 0)
        items_by_id = {}
        for item in group.get("items") or []:
            row = _item_row(item, item_names, metadata_by_id)
            item_id = row["item_id"]
            record_mapping(item_id)
            items_by_id[str(item_id)] = row
            agg = race.setdefault(str(item_id), {
                "item_id": item_id,
                "bot_display_name": row["bot_display_name"],
                "hakuraku_display_name": row["hakuraku_display_name"],
                "icon": row["icon"],
                "expected_copies_by_grade_result": {},
                "appearance_rate_by_grade_result": {},
                "avg_copies_when_spawned_by_grade_result": {},
                "avg_price_by_grade_result": {},
                "max_copies_by_grade_result": {},
                "max_copies": 0,
            })
            agg["expected_copies_by_grade_result"][key] = row["expected_copies"]
            agg["appearance_rate_by_grade_result"][key] = row["appearance_rate"]
            agg["avg_copies_when_spawned_by_grade_result"][key] = row["avg_copies"]
            agg["avg_price_by_grade_result"][key] = row["avg_price"]
            agg["max_copies_by_grade_result"][key] = row["max_copies"]
            agg["max_copies"] = max(int(agg["max_copies"]), int(row["max_copies"]))

        race_refreshes[key] = {
            "key": key,
            "group_id": grade,
            "grade": RACE_GRADE_LABELS.get(grade, str(grade)),
            "result": EVENT_LABELS.get(event, event),
            "source_event": event,
            "samples": samples,
            "contributors": int(group.get("contributors") or 0),
            "avg_new_items": _round(float(group.get("avgItems") or 0.0)),
            "items_per_refresh_distribution": _histogram(group.get("itemCountDistribution") or [], samples, min_count=0, max_count=6),
            "items": items_by_id,
        }

    return {
        "schema": "sweepy_shop_refresh_pools_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "page_url": PAGE_URL,
            "api_url": API_URL,
            "metadata_url": METADATA_URL,
            "api_generated_at": api.get("generatedAt"),
            "metadata_generated_at": (metadata.get("shop_refresh/data") or {}).get("generatedAt"),
            "api_totals": api.get("totals") or {},
        },
        "scheduled": dict(sorted(scheduled.items(), key=lambda item: int(item[0]))),
        "scheduled_refreshes": dict(sorted(scheduled_refreshes.items(), key=lambda item: int(item[0]))),
        "race": dict(sorted(race.items(), key=lambda item: int(item[0]))),
        "race_refreshes": dict(sorted(race_refreshes.items(), key=lambda item: item[0])),
        "display_name_mapping": dict(sorted(mapping.items())),
        "unmapped_display_names": sorted(unmapped),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--api-json", type=Path, default=None, help="Optional cached /api/shop-refresh JSON")
    parser.add_argument("--metadata-gzip", type=Path, default=None, help="Optional cached /data/gamedata.bin.gz")
    args = parser.parse_args()

    api = _load_api(args.api_json)
    metadata = _load_metadata(args.metadata_gzip)
    payload = build_shop_refresh_pools(api, metadata)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"wrote {args.output}: "
        f"{len(payload['scheduled'])} scheduled items, "
        f"{len(payload['scheduled_refreshes'])} scheduled refreshes, "
        f"{len(payload['race'])} race items, "
        f"{len(payload['race_refreshes'])} race refreshes, "
        f"{len(payload['unmapped_display_names'])} unmapped names"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
