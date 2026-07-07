"""Build data/support_card_releases.json — support_card_id -> release date.

Source: umapyoi.net public API (per-card `start_date`, unix epoch, JP release).
Used by the training sim to sort the card toolbox by release date, newest
first (GameTora-style). One-time build; re-run to pick up new cards.
"""
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "support_card_releases.json"
API = "https://umapyoi.net/api/v1/support"
HEADERS = {"User-Agent": "Mozilla/5.0 (sweepy training sim; release-date build)"}


def get_json(url: str):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    existing = {}
    if OUT.exists():
        try:
            existing = {str(k): v for k, v in (json.loads(OUT.read_text(encoding="utf-8")).get("cards") or {}).items()}
        except Exception:
            existing = {}
    cards = get_json(API)
    print(f"card list: {len(cards)}")
    out = {}
    fetched = 0
    for row in cards:
        sid = str(row.get("id") or "")
        if not sid.isdigit():
            continue
        prev = existing.get(sid)
        if prev and prev.get("release_ts"):
            out[sid] = prev  # already resolved; don't refetch
            continue
        try:
            detail = get_json(f"{API}/{sid}")
        except Exception as exc:
            print(f"  {sid}: FETCH FAILED {exc}")
            continue
        ts = int(detail.get("start_date") or 0)
        out[sid] = {
            "release_ts": ts,
            "release_date": time.strftime("%Y-%m-%d", time.gmtime(ts)) if ts else None,
            "title_en": detail.get("title_en") or "",
            "chara_id": int(detail.get("chara_id") or 0),
        }
        fetched += 1
        if fetched % 50 == 0:
            print(f"  fetched {fetched}...")
        time.sleep(0.12)  # be polite to the public API
    payload = {
        "_source": API + " (per-card start_date, unix epoch, JP release)",
        "_description": "support_card_id -> JP release date. Training sim sorts its card toolbox by release_ts desc (newest first, GameTora-style). Rebuild with tools/fetch_support_card_releases.py.",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "cards": out,
    }
    OUT.write_text(json.dumps(payload, indent=1, ensure_ascii=False), encoding="utf-8")
    dated = sum(1 for v in out.values() if v.get("release_ts"))
    print(f"wrote {OUT}: {len(out)} cards, {dated} with dates, {fetched} newly fetched")


if __name__ == "__main__":
    main()
