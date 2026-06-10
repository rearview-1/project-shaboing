"""Build a per-event probability model from career_logs.

Reads every event_resolution across all career_logs and computes:
- For each story_id: total fires, careers seen in, choice picks distribution,
  state-delta medians, turn distribution, phase breakdown.
- For support_card events: deck_presence count (card was in the deck when fired)
  vs guest_presence count (card NOT in the deck — the rare "guest event" case).
- For chara events: chara_id-keyed presence rate (typically should be 100% for
  the active trainee).
- For scenario events: scripted vs recurring based on turn-share concentration.

Output: uma_runtime/instances/<instance>/sim_calibration/event_probability_model.json

This file is meant to be consumed by the sim's runtime_event_observations
loader. With per-event probabilities + per-choice picks + per-effect medians,
the sim can roll each event independently per turn and apply the actually-
chosen branch's effects, instead of replaying observed medians or averaging.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


STATE_KEYS = ("speed", "stamina", "power", "guts", "wit", "wiz",
              "skill_point", "vital", "motivation", "max_vital",
              "mant_coin", "fans")


def _phase_for_turn(turn: int) -> str:
    if turn <= 24:
        return "junior"
    if turn <= 48:
        return "classic"
    if turn <= 72:
        return "senior"
    return "tsc"


def _safe_int(v, default=0):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return default


def _classify_source(event_resolution: dict) -> tuple[str, int]:
    """Return (source_kind, source_id) — best-effort classification."""
    payload = event_resolution.get("event_payload") or {}
    raw = payload.get("raw_event") or {}
    support_id = _safe_int(raw.get("support_card_id"))
    chara_id = _safe_int(raw.get("chara_id"))
    if support_id > 0:
        return ("support_card", support_id)
    if chara_id > 0:
        return ("chara", chara_id)
    story = str(event_resolution.get("story_id") or "")
    # story_id 400000XXX / 400004XXX → scenario events in this codebase
    if story.startswith("4000"):
        return ("scenario", 0)
    return ("other", 0)


def _delta(event_resolution: dict) -> dict:
    sb = event_resolution.get("state_before") or {}
    sa = event_resolution.get("state_after") or {}
    out = {}
    for k in STATE_KEYS:
        if k not in sb and k not in sa:
            continue
        b = sb.get(k, 0)
        a = sa.get(k, 0)
        if not isinstance(b, (int, float)) or not isinstance(a, (int, float)):
            continue
        d = a - b
        if d != 0:
            # Normalize wiz → wit
            out_key = "wit" if k == "wiz" else k
            out[out_key] = out.get(out_key, 0) + d
    return out


def _deck_ids_from_career(career: dict) -> set[int]:
    rc = career.get("run_context") or {}
    ids = rc.get("support_card_ids") or []
    if not ids and rc.get("support_cards"):
        ids = [_safe_int(c.get("id") or c.get("support_card_id"))
               for c in rc.get("support_cards") or []]
    return {int(i) for i in ids if int(i or 0)}


def _trainee_id_from_career(career: dict) -> int:
    rc = career.get("run_context") or {}
    return _safe_int(rc.get("trainee_card_id") or rc.get("chara_id"))


def build_model(career_log_paths: list[Path]) -> dict:
    # Per-story aggregate
    per_story = defaultdict(lambda: {
        "source": "",
        "source_id": 0,            # representative
        "total_fires": 0,
        "careers_fired_in": set(),
        "turn_distribution": Counter(),
        "phase_distribution": Counter(),
        "available_choice_counts": Counter(),
        "choice_picks": Counter(),
        "delta_samples": defaultdict(list),
        "deck_presence_fires": 0,  # for support_card: card in deck
        "guest_fires": 0,           # for support_card: card NOT in deck
    })

    careers_total = 0
    careers_finished = 0
    careers_seen_card = defaultdict(set)
    careers_with_card = defaultdict(set)

    for path in career_log_paths:
        try:
            career = json.loads(path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        careers_total += 1
        status = str(career.get("status") or "")
        if status == "finished":
            careers_finished += 1

        deck_ids = _deck_ids_from_career(career)
        career_key = path.name

        for card_id in deck_ids:
            careers_with_card[card_id].add(career_key)

        for turn in career.get("turns") or []:
            for ev in turn.get("events") or []:
                if ev.get("event") != "event_resolution":
                    continue
                story = str(ev.get("story_id") or "")
                if not story:
                    continue
                source_kind, source_id = _classify_source(ev)
                phase = _phase_for_turn(_safe_int(ev.get("turn") or turn.get("turn")))
                turn_n = _safe_int(ev.get("turn") or turn.get("turn"))
                chosen = _safe_int(ev.get("choice_index"))
                avail = _safe_int(ev.get("available_choices"))
                delta = _delta(ev)

                s = per_story[story]
                if not s["source"]:
                    s["source"] = source_kind
                    s["source_id"] = source_id
                s["total_fires"] += 1
                s["careers_fired_in"].add(career_key)
                s["turn_distribution"][turn_n] += 1
                s["phase_distribution"][phase] += 1
                if avail:
                    s["available_choice_counts"][avail] += 1
                s["choice_picks"][chosen] += 1
                for k, v in delta.items():
                    s["delta_samples"][k].append(v)

                if source_kind == "support_card":
                    if source_id in deck_ids:
                        s["deck_presence_fires"] += 1
                        careers_seen_card[source_id].add(career_key)
                    else:
                        s["guest_fires"] += 1

    # Reduce
    events_out = {}
    for story, s in per_story.items():
        careers_fired = len(s["careers_fired_in"])
        sample = {
            "source": s["source"],
            "source_id": s["source_id"],
            "total_fires": s["total_fires"],
            "careers_fired_in": careers_fired,
            "career_fire_rate": careers_fired / max(1, careers_total),
            "mean_fires_per_career_when_fired": s["total_fires"] / max(1, careers_fired),
            "turn_distribution": dict(s["turn_distribution"].most_common()),
            "phase_distribution": dict(s["phase_distribution"]),
            "top_turn": s["turn_distribution"].most_common(1)[0][0]
                if s["turn_distribution"] else 0,
            "top_turn_share": (s["turn_distribution"].most_common(1)[0][1] / s["total_fires"])
                if s["turn_distribution"] else 0.0,
            "available_choice_counts": dict(s["available_choice_counts"]),
            "choice_picks": dict(s["choice_picks"]),
        }
        # Choice pick rates as fractions
        total_picks = sum(s["choice_picks"].values())
        if total_picks:
            sample["choice_pick_rates"] = {
                str(k): v / total_picks for k, v in s["choice_picks"].items()
            }
        # Delta medians
        delta_summary = {}
        for k, samples in s["delta_samples"].items():
            if samples:
                delta_summary[k] = {
                    "median": statistics.median(samples),
                    "mean": statistics.mean(samples),
                    "min": min(samples),
                    "max": max(samples),
                    "n": len(samples),
                }
        sample["effect_deltas"] = delta_summary

        if s["source"] == "support_card":
            sample["deck_presence_fires"] = s["deck_presence_fires"]
            sample["guest_fires"] = s["guest_fires"]
            card_id = s["source_id"]
            careers_with = len(careers_with_card.get(card_id, set()))
            careers_without = careers_total - careers_with
            sample["careers_with_card_in_deck"] = careers_with
            sample["careers_without_card_in_deck"] = careers_without
            sample["fire_rate_when_card_in_deck"] = (
                s["deck_presence_fires"] / max(1, careers_with)
                if careers_with else 0.0
            )
            sample["guest_fire_rate_when_card_not_in_deck"] = (
                s["guest_fires"] / max(1, careers_without)
                if careers_without else 0.0
            )

        events_out[story] = sample

    # Top-level summary
    return {
        "schema": "sweepy_event_probability_model_v1",
        "careers_total": careers_total,
        "careers_finished": careers_finished,
        "event_count": len(events_out),
        "events": events_out,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="account_b",
                    help="Runtime instance to scan (default: account_b)")
    ap.add_argument("--out", default=None,
                    help="Output path. Defaults to "
                         "uma_runtime/instances/<instance>/sim_calibration/event_probability_model.json")
    args = ap.parse_args()

    project_root = Path(__file__).resolve().parent.parent
    instance_root = project_root / "uma_runtime" / "instances" / args.instance
    bot_logs = instance_root / "bot_logs"
    if not bot_logs.exists():
        print(f"no bot_logs found at {bot_logs}", file=sys.stderr)
        sys.exit(1)
    career_logs = sorted(bot_logs.glob("career_log_*.json"))
    if not career_logs:
        print(f"no career_log_*.json files in {bot_logs}", file=sys.stderr)
        sys.exit(1)
    print(f"scanning {len(career_logs)} career_log files...")
    model = build_model(career_logs)

    out_path = Path(args.out) if args.out else instance_root / "sim_calibration" / "event_probability_model.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(model, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"  careers_total: {model['careers_total']}")
    print(f"  careers_finished: {model['careers_finished']}")
    print(f"  unique events: {model['event_count']}")


if __name__ == "__main__":
    main()
