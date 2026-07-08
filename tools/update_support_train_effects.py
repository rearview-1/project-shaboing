# -*- coding: utf-8 -*-
"""Sync data/support_card_training_effects.json from uma.guide's
jp-support-card-data chunk (the original source of all card curves/uniques).

Run when new JP support cards release and the training sim shows them without
training data. The tool:
  1. finds the current jp-support-card-data chunk URL from uma.guide's bundle
     (hashed filename changes per deploy), or uses --chunk-file,
  2. converts every entry to our compact schema
       {c: {effectType: [11 level-milestone values]}, u: uniqueEffect, r, t},
  3. VALIDATES itself by requiring the conversion to reproduce the existing
     entries (>=99% identical) before it will merge anything,
  4. adds missing cards (and reports, but does not overwrite, changed ones).
"""
import argparse
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "support_card_training_effects.json"
HEADERS = {"User-Agent": "Mozilla/5.0 (sweepy training data sync)"}
LEVEL_KEYS = (
    "initValue", "level5Value", "level10Value", "level15Value", "level20Value",
    "level25Value", "level30Value", "level35Value", "level40Value",
    "level45Value", "level50Value",
)


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=90) as resp:
        return resp.read().decode("utf-8", "replace")


def find_chunk_url() -> str:
    html = fetch("https://uma.guide/")
    app = re.search(r'src="(/assets/app\.[A-Za-z0-9_-]+\.js)"', html)
    if not app:
        raise SystemExit("could not find uma.guide app bundle in page HTML")
    bundle = fetch("https://uma.guide" + app.group(1))
    m = re.search(r'assets/chunks/(jp-support-card-data\.[A-Za-z0-9_-]+\.js)', bundle)
    if not m:
        raise SystemExit("could not find jp-support-card-data chunk in app bundle")
    return "https://uma.guide/assets/chunks/" + m.group(1)


def extract_json_array(chunk_js: str) -> list:
    m = re.search(r"JSON\.parse\(`", chunk_js)
    if not m:
        raise SystemExit("chunk format changed: no JSON.parse(` found")
    start = m.end()
    end = chunk_js.index("`)", start)
    raw = chunk_js[start:end]
    # undo template-literal escapes
    raw = raw.replace("\\`", "`").replace("\\${", "${").replace("\\\\", "\\")
    return json.loads(raw)


# Only the training-relevant effect types the resolver reads (derived from the
# union across the existing 539 entries): friendship, mood, stat bonuses,
# training effectiveness, energy discount, SP bonus.
KEEP_EFFECT_TYPES = {1, 2, 3, 4, 5, 6, 7, 8, 28, 30}
# uniqueEffect keys as stored (no *Name, no value11..14).
KEEP_UNIQUE_KEYS = ("level", "type0", "value0", "value01", "value02", "value03", "value04", "type1", "value1")


def convert(entry: dict) -> dict:
    curves = {}
    for eff in entry.get("effects") or []:
        etype = eff.get("effectType")
        if etype is None or int(etype) not in KEEP_EFFECT_TYPES:
            continue
        curves[str(int(etype))] = [int(eff.get(k) if eff.get(k) is not None else -1) for k in LEVEL_KEYS]
    unique = entry.get("uniqueEffect")
    if isinstance(unique, dict):
        unique = {k: unique.get(k) for k in KEEP_UNIQUE_KEYS if k in unique}
    else:
        unique = {}
    return {
        "c": curves,
        "u": unique,
        "r": str(entry.get("rarityDisplay") or ""),
        "t": int(entry.get("supportCardType") or 0),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chunk-file", help="use a locally saved chunk instead of fetching")
    ap.add_argument("--write", action="store_true", help="write the merged file (default: dry run)")
    args = ap.parse_args()

    if args.chunk_file:
        chunk = Path(args.chunk_file).read_text(encoding="utf-8")
        src_desc = args.chunk_file
    else:
        url = find_chunk_url()
        print(f"chunk: {url}")
        chunk = fetch(url)
        src_desc = url

    entries = extract_json_array(chunk)
    print(f"chunk entries: {len(entries)}")
    existing = json.loads(OUT.read_text(encoding="utf-8"))
    converted = {str(int(e.get("supportCardId") or 0)): convert(e) for e in entries if e.get("supportCardId")}

    # Self-validation: the conversion must reproduce what we already have.
    same = diff = 0
    diff_ids = []
    for sid, old in existing.items():
        new = converted.get(sid)
        if new is None:
            continue
        if new == old:
            same += 1
        else:
            diff += 1
            diff_ids.append(sid)
    total = same + diff
    print(f"validation vs existing: identical {same}/{total}, changed {diff} {diff_ids[:8]}")
    if total and same / total < 0.99:
        raise SystemExit("conversion drifted from existing format — NOT merging. Inspect before use.")

    missing = sorted(set(converted) - set(existing), key=int)
    print(f"new cards to add: {missing}")
    if not args.write:
        print("dry run (pass --write to merge)")
        return
    merged = dict(existing)
    for sid in missing:
        merged[sid] = converted[sid]
    OUT.write_text(json.dumps(merged, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    print(f"wrote {OUT}: {len(merged)} cards (+{len(missing)}) from {src_desc}")


if __name__ == "__main__":
    main()
