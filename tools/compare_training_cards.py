"""Compare support cards on one training tile.

Examples:

  python tools/compare_training_cards.py --training speed --type speed --top 15

  python tools/compare_training_cards.py --training speed --scenario island ^
    --card 20031 --card 30028 --growth speed=20 --weights speed=1,power=0.8,sp=0.5

  python tools/compare_training_cards.py --training speed --baseline 30028:4,30078:4 ^
    --type speed --top 20
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from career_bot.training_compare import rank_candidate_cards, tile_gain


def _parse_card_list(raw: str | None) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            cid, lb = part.split(":", 1)
            out.append((int(cid), int(lb)))
        else:
            out.append((int(part), 4))
    return out


def _parse_key_values(raw: str | None) -> dict[str, float]:
    out: dict[str, float] = {}
    if not raw:
        return out
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"Expected key=value in {part!r}")
        key, value = part.split("=", 1)
        out[key.strip()] = float(value)
    return out


def _parse_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _format_gains(gains: dict[str, Any]) -> str:
    keys = ("speed", "stamina", "power", "guts", "wit", "sp", "energy")
    return " ".join(f"{key}={int(gains.get(key) or 0):>4}" for key in keys)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--training", required=True, help="Training tile: speed/stamina/power/guts/wit.")
    parser.add_argument("--scenario", help="GameWith scenario name substring or newest-first order number.")
    parser.add_argument("--curves", type=Path, help="Explicit training curve JSON path.")
    parser.add_argument("--scenario-effects", type=Path, help="Scenario training effects JSON path.")
    parser.add_argument(
        "--effect",
        default="",
        help="Comma-separated scenario effect IDs to enable. Use 'all' to enable every matched effect.",
    )
    parser.add_argument("--level", type=int, default=5, help="Facility level.")
    parser.add_argument("--mood", type=float, default=0.2, help="Mood base effect: 0.2 = great mood.")
    parser.add_argument("--growth", default="", help="Comma-separated growth rates, e.g. speed=20,power=10.")
    parser.add_argument("--weights", default="", help="Comma-separated score weights, e.g. speed=1,power=.8,sp=.5.")
    parser.add_argument("--item-train-pct", type=float, default=0)
    parser.add_argument("--item-energy-pct", type=float, default=0)
    parser.add_argument("--npc", type=int, default=0, help="Non-support characters on the tile.")
    parser.add_argument("--unbonded", action="store_true", help="Disable friendship/rainbow effects.")
    parser.add_argument("--baseline", default="", help="Comma card list for always-present cards, e.g. 30028:4,30078:4.")
    parser.add_argument("--card", action="append", type=int, default=[], help="Candidate card ID. Repeatable.")
    parser.add_argument("--type", help="Filter candidate support type.")
    parser.add_argument("--rarity", help="Filter candidate rarity.")
    parser.add_argument("--name", help="Filter candidate name substring.")
    parser.add_argument("--candidate-lb", type=int, default=4)
    parser.add_argument("--default-lb", type=int, default=4)
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    args = parser.parse_args()

    baseline = _parse_card_list(args.baseline)
    growth = _parse_key_values(args.growth)
    weights = _parse_key_values(args.weights)
    active_effects = _parse_csv(args.effect)

    baseline_gain = tile_gain(
        baseline,
        args.training,
        scenario=args.scenario,
        curves_path=args.curves,
        scenario_effects_path=args.scenario_effects,
        active_scenario_effects=active_effects,
        facility_level=args.level,
        mood=args.mood,
        growth=growth,
        item_train_pct=args.item_train_pct,
        item_energy_pct=args.item_energy_pct,
        npc=args.npc,
        bonded=not args.unbonded,
        default_lb=args.default_lb,
    )
    rows = rank_candidate_cards(
        baseline_deck=baseline,
        candidates=args.card or None,
        training_stat=args.training,
        scenario=args.scenario,
        curves_path=args.curves,
        scenario_effects_path=args.scenario_effects,
        active_scenario_effects=active_effects,
        facility_level=args.level,
        mood=args.mood,
        growth=growth,
        item_train_pct=args.item_train_pct,
        item_energy_pct=args.item_energy_pct,
        npc=args.npc,
        bonded=not args.unbonded,
        default_lb=args.default_lb,
        candidate_lb=args.candidate_lb,
        weights=weights,
        support_type=args.type,
        rarity=args.rarity,
        name_contains=args.name,
    )
    rows = rows[: max(1, int(args.top))]

    if args.json:
        print(
            json.dumps(
                {
                    "baseline": {"deck": baseline, "gains": baseline_gain},
                    "active_scenario_effects": active_effects,
                    "results": [
                        {
                            "support_card_id": row.support_card_id,
                            "name": row.name,
                            "type": row.support_type,
                            "rarity": row.rarity,
                            "lb": row.lb,
                            "gains": row.gains,
                            "stat_sum": row.stat_sum,
                            "weighted_score": row.weighted_score,
                            "delta_vs_baseline": row.delta_vs_baseline,
                            "score_delta_vs_baseline": row.score_delta_vs_baseline,
                        }
                        for row in rows
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    print(f"Baseline: {_format_gains(baseline_gain)}")
    if active_effects:
        print(f"Scenario effects: {', '.join(active_effects)}")
    print("Rank  ID      LB  Type      Rarity  Score   Delta   StatSum  Gains")
    for idx, row in enumerate(rows, start=1):
        print(
            f"{idx:>4}  {row.support_card_id:<7} {row.lb:<3} "
            f"{row.support_type[:9]:<9} {row.rarity:<6} "
            f"{row.weighted_score:>7.2f} {row.score_delta_vs_baseline:>7.2f} "
            f"{row.stat_sum:>7}  {_format_gains(row.gains)}  {row.name}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
