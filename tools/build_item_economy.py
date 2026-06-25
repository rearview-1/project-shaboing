"""Build data/real_item_economy.json — the empirical per-era item-acquisition
profile from real careers (data/real_shop_snapshots.json), so the sim drives
its shop/item economy from REAL data instead of synthetic chance-based buying.

Categories map item names to their sim effect bucket:
  energy   - Vita* (HP recovery -> more training)
  stat     - *Manual / *Notepad (direct +stat)
  megaphone- Motivating Megaphone (training tile buff)
  cleat    - *Cleat Hammer (race stat-reward buff)
  bond     - Grilled Carrots (all bonds +)
  mood     - mood items
  other
Output: per-era {category: avg_count_per_career}, plus avg coin spend / era.
"""
import json
import collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "real_shop_snapshots.json"
OUT = ROOT / "data" / "real_item_economy.json"


def category(name: str) -> str:
    n = (name or "").lower()
    if "vita" in n or "energy" in n or "carrot juice" in n:
        return "energy"
    if "manual" in n or "notepad" in n:
        return "stat"
    if "megaphone" in n:
        return "megaphone"
    if "cleat hammer" in n or "hammer" in n:
        return "cleat"
    if "grilled carrot" in n or "bond" in n:
        return "bond"
    if "mood" in n or "cupcake" in n or "snack" in n:
        return "mood"
    return "other"


def era(turn) -> str:
    t = int(turn or 0)
    return "junior" if t <= 24 else "classic" if t <= 48 else "senior"


def main():
    data = json.loads(SRC.read_text(encoding="utf-8"))
    snaps = data.get("snapshots") or []
    # per-career, per-era category counts + coin spend
    careers = collections.defaultdict(lambda: collections.defaultdict(collections.Counter))
    coin = collections.defaultdict(lambda: collections.Counter())
    for s in snaps:
        src = s.get("source")
        e = era(s.get("turn"))
        for b in (s.get("selected_buy") or []):
            cat = category(str(b.get("name") or b.get("item_id")))
            qty = int(b.get("use_num") or 1)
            careers[src][e][cat] += qty
            coin[src][e] += int(b.get("cost") or 0) * qty
    ncar = max(1, len(careers))
    profile = {}
    for e in ("junior", "classic", "senior"):
        cats = collections.Counter()
        coins = 0
        for src in careers:
            cats.update(careers[src][e])
            coins += coin[src][e]
        profile[e] = {
            "items_per_career": {k: round(v / ncar, 3) for k, v in cats.items()},
            "coin_spend_per_career": round(coins / ncar, 1),
        }
    out = {
        "_source": "data/real_shop_snapshots.json",
        "_description": "Empirical per-era item acquisition from real careers. Drives the sim's data-driven item economy (career_simulator._buy_items_from_real_profile). Regenerate with tools/build_item_economy.py.",
        "careers_analyzed": ncar,
        "profile": profile,
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {OUT} ({ncar} careers)")
    print(json.dumps(profile, indent=1))


if __name__ == "__main__":
    main()
