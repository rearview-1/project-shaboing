"""Schema checks for observed MANT shop/item/rival telemetry."""

import json
from pathlib import Path


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "real_shop_snapshots.json"


def test_real_shop_snapshots_load():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8-sig"))
    assert data.get("schema") == "sweepy_real_shop_snapshots_v1"
    summary = data.get("summary") or {}
    assert int(summary.get("snapshots") or 0) >= 1000
    assert int(summary.get("buy_events") or 0) > 0
    assert int(summary.get("use_events") or 0) > 0
    assert len(summary.get("rival_programs") or {}) > 0


def test_real_shop_item_summary_has_core_items():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8-sig"))
    items = (data.get("summary") or {}).get("item_summary") or {}
    for item_id in ("2001", "8002", "11001", "11002"):
        row = items.get(item_id) or {}
        assert int(row.get("bought") or 0) > 0
        assert int(row.get("used") or 0) > 0
