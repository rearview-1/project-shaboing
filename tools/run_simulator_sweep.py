"""Run a swept set of simulated careers against the user's actual preset.

Usage:
    python -m tools.run_simulator_sweep            # 50 runs vs current preset
    python -m tools.run_simulator_sweep --n 200    # 200 runs
    python -m tools.run_simulator_sweep --preset "path/to/preset.json"

Prints a one-screen summary: median rating, rank distribution, G1 win
median, training-pick distribution, bonus fire counts. Use this to
verify a code change actually moves the median in the right direction
before running a real career.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from statistics import median


def _runtime_instance_from_env():
    for key in ("SWEEPY_SIM_INSTANCE_NAME", "SWEEPY_INSTANCE_NAME"):
        value = str(os.environ.get(key) or "").strip()
        if value:
            return value
    runtime_dir = str(os.environ.get("UMA_RUNTIME_DIR") or "").strip()
    if runtime_dir:
        path = Path(runtime_dir)
        if path.parent.name.lower() == "instances":
            return path.name
    return "account_b"


def _default_preset_path(project_root, instance):
    candidates = []
    preset_dir = project_root / "uma_runtime" / "instances" / instance / "instance_learning" / "presets"
    if preset_dir.exists():
        candidates.extend(sorted(preset_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True))
    fallback = project_root / "uma_runtime" / "instances" / "account_b" / "instance_learning" / "presets" / "xguri parent.json"
    candidates.append(fallback)
    return next((path for path in candidates if path.exists()), fallback)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=50)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--instance", default="", help="runtime instance to hydrate from, e.g. account_a/account_b")
    parser.add_argument(
        "--preset",
        default="",
        help="preset JSON path; defaults to newest preset for --instance",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(project_root))
    from career_bot.career_simulator import (
        CareerSimulator,
        hydrate_preset_with_latest_session_context,
        run_sweep,
    )
    from career_bot.rating import RATING_BADGE_MINIMA

    instance = args.instance or _runtime_instance_from_env()
    preset_path = Path(args.preset) if args.preset else _default_preset_path(project_root, instance)
    if not preset_path.exists():
        print(f"ERROR: preset not found at {preset_path}")
        sys.exit(2)
    preset = json.loads(preset_path.read_text(encoding="utf-8-sig"))
    if instance:
        preset["sim_runtime_instance"] = instance
    preset = hydrate_preset_with_latest_session_context(preset, project_root)
    deck = (preset.get("_run_context") or {}).get("support_cards") or None
    probe = CareerSimulator(preset=preset, deck=deck, seed=args.seed)

    print(f"Running {args.n} simulated careers against preset '{preset.get('name')}'...")
    ctx = probe.preset.get("_run_context") or {}
    source = probe.latest_session_context_source or "preset/default"
    print(f"Resolved sim context source: {source}")
    print(
        "Resolved sim setup: "
        f"deck={ctx.get('deck_name') or ctx.get('deck_id') or '?'} "
        f"trainee={ctx.get('trainee_card_id') or '?'} "
        f"borrow={ctx.get('friend_card_id') or '?'}@{ctx.get('friend_viewer_id') or 0} "
        f"parents={ctx.get('parent_id_1') or '?'} / {ctx.get('parent_id_2') or '?'}"
    )
    print("Resolved sim deck:")
    for card in probe.sim_support_cards:
        friend = " friend" if card.get("friend") else ""
        print(
            f"  {card['support_card_id']} {card.get('rarity') or ''} "
            f"{card.get('type') or '?'} {card.get('name') or ''} "
            f"LB{card.get('lb', 0)}{friend}"
        )
    print(f"  Type counts [spd,sta,pwr,gut,wit]: {probe._deck_type_counts()}")
    sweep = run_sweep(n_runs=args.n, preset=preset, deck=deck, seed_base=args.seed)

    print(f"\n=== Simulated career sweep (n={sweep['n_runs']}) ===")
    print(f"  Rating:    median={sweep['rating_score_median']:5d}  mean={sweep['rating_score_mean']:5d}  "
          f"min={sweep['rating_score_min']:5d}  max={sweep['rating_score_max']:5d}")
    print(f"  Stat sum:  median={sweep['stat_sum_median']:5d}  mean={sweep['stat_sum_mean']:5d}  "
          f"min={sweep['stat_sum_min']:5d}  max={sweep['stat_sum_max']:5d}")
    print(f"  Stat score median:  {int(median(r.stat_rating_score for r in sweep['results'])):5d}")
    print(f"  Skill score median: {int(median(r.skill_rating_score for r in sweep['results'])):5d}")
    print(f"  G1 wins median: {sweep['g1_wins_median']}")
    race_loss_counts = [sum(1 for race in r.races_run if not race.get("won")) for r in sweep["results"]]
    event_counts = [len(r.events_fired) for r in sweep["results"]]
    print(f"  Race losses median: {int(median(race_loss_counts))}")
    print(f"  Event count median:  {int(median(event_counts))}")
    rd = sweep["rank_distribution"]
    rank_order = [label for _minimum, label in reversed(RATING_BADGE_MINIMA) if label in rd]
    print(f"  Rank distribution:  ", "  ".join(
        f"{r}={rd.get(r,0)}" for r in rank_order
    ))
    print(f"  S-or-better count:  {sweep['s_or_better_count']} / {sweep['n_runs']}  "
          f"({100*sweep['s_or_better_count']/sweep['n_runs']:.0f}%)")

    # Aggregate training picks
    total_picks = {"speed": 0, "stamina": 0, "power": 0, "guts": 0, "wit": 0}
    for r in sweep["results"]:
        for k, v in r.train_picks_by_stat.items():
            total_picks[k] += v
    total = sum(total_picks.values()) or 1
    print(f"\n=== Aggregate training picks ===")
    for k, v in sorted(total_picks.items(), key=lambda kv: -kv[1]):
        print(f"  {k:>8}: {v:4d} ({100*v/total:.0f}%)")

    print(f"\n=== Final stat medians ===")
    for stat in ("speed", "stamina", "power", "guts", "wit"):
        med = int(median(r.final_stats[stat] for r in sweep["results"]))
        print(f"  {stat:>8}: {med}")

    warnings = sorted({
        warning
        for result in sweep["results"]
        for warning in getattr(result, "fidelity_warnings", [])
    })
    if warnings:
        print("\n=== Fidelity warnings ===")
        for warning in warnings:
            print(f"  - {warning}")


if __name__ == "__main__":
    main()
