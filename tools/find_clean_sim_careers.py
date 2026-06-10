"""Search simulator seeds for clean no-loss careers.

Usage:
    python -m tools.find_clean_sim_careers --target 10 --max-seeds 500
"""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PRESET = None
DECK = None


def _init_worker(preset_path: str):
    global PRESET, DECK
    path = Path(preset_path)
    PRESET = json.loads(path.read_text(encoding="utf-8-sig"))
    DECK = (PRESET.get("_run_context") or {}).get("support_cards") or None


def _run_seed(seed: int):
    from career_bot.career_simulator import CareerSimulator

    sim = CareerSimulator(preset=PRESET, deck=DECK, seed=seed)
    result = sim.run()
    races = result.races_run
    wins = sum(1 for race in races if race.get("won"))
    losses = len(races) - wins
    payload = {
        "seed": seed,
        "rank": result.rank,
        "rating_score": result.rating_score,
        "stat_sum": result.stat_sum,
        "rating_breakdown": {
            "stats": result.stat_rating_score,
            "unique": result.unique_rating_bonus,
            "skills": result.skill_rating_score,
        },
        "final_stats": result.final_stats,
        "race_record": f"{wins}-{losses}",
        "g1_record": f"{result.g1_wins}-{result.g1_losses}",
        "skills_bought": result.skills_bought,
        "skill_rating_score": result.skill_rating_score,
        "purchased_skills": result.purchased_skills,
        "final_sp": result.final_sp,
        "shop_items_bought": result.shop_items_bought,
        "shop_items_used": result.shop_items_used,
        "race_continues_used": getattr(result, "race_continues_used", 0),
        "losses": [
            {
                "turn": race.get("turn"),
                "pid": race.get("pid"),
                "name": race.get("name"),
                "grade": race.get("grade"),
                "win_probability": race.get("win_probability"),
                "model": race.get("model"),
                "pre_race_stats": race.get("pre_race_stats"),
                "pre_race_sp": race.get("pre_race_sp"),
                "pre_race_skills_bought": race.get("pre_race_skills_bought"),
            }
            for race in races
            if not race.get("won")
        ],
    }
    return {
        "seed": seed,
        "losses": losses,
        "g1_losses": result.g1_losses,
        "stat_sum": result.stat_sum,
        "rating_score": result.rating_score,
        "payload": payload,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=int, default=10)
    parser.add_argument("--max-seeds", type=int, default=500)
    parser.add_argument("--start-seed", type=int, default=0)
    parser.add_argument("--workers", type=int, default=max(1, min(6, (os.cpu_count() or 2) - 1)))
    parser.add_argument(
        "--preset",
        default=str(
            PROJECT_ROOT
            / "uma_runtime"
            / "instances"
            / "account_b"
            / "instance_learning"
            / "presets"
            / "xguri parent.json"
        ),
    )
    args = parser.parse_args()

    start_time = time.time()
    clean = []
    best = None
    checked = 0
    seed_stop = args.start_seed + args.max_seeds
    seeds = range(args.start_seed, seed_stop)
    print(
        f"Searching seeds {args.start_seed}..{seed_stop - 1} "
        f"for {args.target} clean careers using {args.workers} workers",
        flush=True,
    )

    with ProcessPoolExecutor(
        max_workers=args.workers,
        initializer=_init_worker,
        initargs=(args.preset,),
    ) as executor:
        future_to_seed = {executor.submit(_run_seed, seed): seed for seed in seeds}
        for future in as_completed(future_to_seed):
            checked += 1
            try:
                row = future.result()
            except Exception as exc:
                print(f"seed {future_to_seed[future]} failed: {exc}", flush=True)
                continue
            key = (row["losses"], row["g1_losses"], -row["rating_score"])
            if best is None or key < best[0]:
                best = (key, row["payload"])
                print(
                    f"new best seed={row['seed']} losses={row['losses']} "
                    f"g1_losses={row['g1_losses']} rank={row['payload']['rank']} "
                    f"rating={row['rating_score']} stat_sum={row['stat_sum']}",
                    flush=True,
                )
            if row["losses"] == 0:
                clean.append(row["payload"])
                print(
                    f"CLEAN {len(clean)}/{args.target}: seed={row['seed']} "
                    f"rank={row['payload']['rank']} rating={row['rating_score']} "
                    f"stat_sum={row['stat_sum']} "
                    f"g1={row['payload']['g1_record']}",
                    flush=True,
                )
                if len(clean) >= args.target:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
            if checked % 25 == 0:
                print(f"checked={checked} clean={len(clean)} elapsed={time.time() - start_time:.1f}s", flush=True)

    output = {
        "target": args.target,
        "clean_found": len(clean),
        "checked": checked,
        "elapsed_sec": round(time.time() - start_time, 1),
        "clean_careers": clean[: args.target],
        "best_nonclean": None if len(clean) >= args.target else (best[1] if best else None),
    }
    print("\n=== CLEAN SIM SEARCH RESULT ===")
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
