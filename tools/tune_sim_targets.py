"""Search simulator policy candidates against explicit target stats.

This is intentionally separate from auto_learning.  It does not create fake
career samples.  It runs the simulator, scores candidate preset knobs against a
target vector, and optionally applies the best candidate to the instance preset.

Usage:
    python -m tools.tune_sim_targets --target 1200,700,1100,600,1200 --n 6
    python -m tools.tune_sim_targets --target 1200,700,1100,600,1200 --apply
"""

from __future__ import annotations

import argparse
import copy
import json
import random
import time
from pathlib import Path
from statistics import mean, median
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")
STAT_MULT_FLOOR = [0.002, 0.002, 0.002, 0.002, 0.002, 0.002]
STAT_MULT_CEIL = [0.050, 0.050, 0.050, 0.050, 0.050, 0.010]
BASE_FLOOR = -0.08
BASE_CEIL = 0.12
EXTRA_FLOOR = -0.12
EXTRA_CEIL = 0.25


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _parse_target(text: str) -> list[int]:
    parts = [part.strip() for part in str(text or "").split(",") if part.strip()]
    if len(parts) != 5:
        raise SystemExit("--target must be five comma-separated stats, e.g. 1200,700,1100,600,1200")
    return [int(part) for part in parts]


def _runtime_instance_from_env() -> str:
    import os

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


def _default_preset_path(project_root: Path, instance: str) -> Path:
    preset_dir = project_root / "uma_runtime" / "instances" / instance / "instance_learning" / "presets"
    if preset_dir.exists():
        candidates = sorted(preset_dir.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in candidates:
            if path.exists():
                return path
    return preset_dir / "xguri parent.json"


def _load_preset(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _calendar_signature(rows: Any) -> list[tuple[int, int, str]]:
    signature = []
    if not isinstance(rows, list):
        return signature
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            turn = int(row.get("turn") or 0)
            program_id = int(row.get("program_id") or 0)
        except (TypeError, ValueError):
            continue
        if not turn or not program_id:
            continue
        signature.append((turn, program_id, str(row.get("style") or row.get("strategy") or row.get("tactic") or "")))
    signature.sort(key=lambda item: (item[0], item[1], item[2]))
    return signature


def _schedule_summary(preset: dict[str, Any], *, source: str) -> dict[str, Any]:
    rows = preset.get("custom_race_schedule") if isinstance(preset, dict) else []
    signature = _calendar_signature(rows)
    by_grade: dict[str, int] = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        grade = str(row.get("type") or row.get("grade") or "").upper() or "UNKNOWN"
        by_grade[grade] = by_grade.get(grade, 0) + 1
    first = rows[0] if isinstance(rows, list) and rows else {}
    last = rows[-1] if isinstance(rows, list) and rows else {}
    return {
        "source": source,
        "count": len(signature),
        "by_grade": by_grade,
        "first": {
            "turn": first.get("turn"),
            "program_id": first.get("program_id"),
            "name": first.get("name"),
            "style": first.get("style") or "",
        } if isinstance(first, dict) else {},
        "last": {
            "turn": last.get("turn"),
            "program_id": last.get("program_id"),
            "name": last.get("name"),
            "style": last.get("style") or "",
        } if isinstance(last, dict) else {},
        "signature": signature,
    }


def _normalize_vector(value: Any, length: int, fallback: list[float]) -> list[float]:
    raw = value if isinstance(value, list) else []
    out = []
    for idx in range(length):
        base = fallback[idx] if idx < len(fallback) else 0.0
        try:
            out.append(float(raw[idx]))
        except (TypeError, ValueError, IndexError):
            out.append(float(base))
    return out


def _normalize_matrix(value: Any, rows: int, cols: int, fallback: list[list[float]]) -> list[list[float]]:
    raw = value if isinstance(value, list) else []
    out = []
    for row_idx in range(rows):
        fallback_row = fallback[row_idx] if row_idx < len(fallback) else [0.0] * cols
        raw_row = raw[row_idx] if row_idx < len(raw) and isinstance(raw[row_idx], list) else []
        out.append(_normalize_vector(raw_row, cols, fallback_row))
    return out


def _apply_target_profiles(preset: dict[str, Any], target: list[int], profile_keys: list[str]) -> None:
    profiles = dict(preset.get("expect_attribute_profiles") or {})
    for key in profile_keys:
        if not key:
            continue
        existing = profiles.get(key)
        if isinstance(existing, dict):
            row = dict(existing)
        else:
            row = {}
        row["expect_attribute"] = list(target)
        row["sim_target_override"] = True
        profiles[key] = row
    preset["expect_attribute_profiles"] = profiles


def _apply_candidate(
    base: dict[str, Any],
    name: str,
    changes: dict[str, Any],
    *,
    profile_keys: list[str] | None = None,
) -> dict[str, Any]:
    preset = copy.deepcopy(base)
    preset["expect_attribute"] = list(changes.get("expect_attribute") or preset.get("expect_attribute") or [])
    if changes.get("expect_attribute") and profile_keys:
        _apply_target_profiles(preset, list(changes["expect_attribute"]), profile_keys)
    learned = dict(preset.get("learned_hyperparameters") or {})
    learned.update(changes.get("learned_hyperparameters") or {})
    if learned:
        preset["learned_hyperparameters"] = learned
    for key in ("stat_value_multiplier", "base_score", "extra_weight"):
        if key in changes:
            preset[key] = copy.deepcopy(changes[key])
    preset["_sim_target_candidate"] = name
    return preset


def _candidate_templates(base: dict[str, Any], target: list[int], random_count: int, seed: int) -> list[tuple[str, dict[str, Any]]]:
    default_stat_mult = [0.022, 0.016, 0.018, 0.012, 0.016, 0.006]
    stat_mult = _normalize_vector(base.get("stat_value_multiplier"), 6, default_stat_mult)
    base_score = _normalize_vector(base.get("base_score"), 5, [0, 0, 0, 0, 0])
    extra = _normalize_matrix(base.get("extra_weight"), 4, 5, [[0, 0, 0, 0, 0] for _ in range(4)])

    def sm(*values: float) -> list[float]:
        return [
            round(_clamp(value, STAT_MULT_FLOOR[idx], STAT_MULT_CEIL[idx]), 4)
            for idx, value in enumerate(values)
        ]

    def bs(*values: float) -> list[float]:
        return [round(_clamp(value, BASE_FLOOR, BASE_CEIL), 4) for value in values]

    def ew(rows: list[list[float]]) -> list[list[float]]:
        return [
            [round(_clamp(value, EXTRA_FLOOR, EXTRA_CEIL), 4) for value in row]
            for row in rows
        ]

    common_hp = {
        "speed_soft_cap": 1200,
        "power_soft_cap": 1200,
        "wit_soft_cap": 1200,
        "stamina_soft_cap": max(600, min(900, target[1] + 25)),
        "guts_soft_cap": max(550, min(850, target[3] + 25)),
        "stamina_floor_target": max(550, min(800, target[1])),
        "power_floor_target": max(700, min(950, target[2] - 100)),
        "stamina_priority_bonus_base": 0.06,
        "stamina_priority_deficit_boost": 0.08,
        "power_priority_bonus_base": 0.08,
        "power_priority_deficit_boost": 0.08,
        "speed_priority_deficit_scale": 0.95,
    }

    candidates: list[tuple[str, dict[str, Any]]] = [
        ("baseline_target", {"expect_attribute": target}),
        ("cap_target_only", {"expect_attribute": target, "learned_hyperparameters": common_hp}),
        (
            "direct_spd_pwr_wit_value",
            {
                "expect_attribute": target,
                "learned_hyperparameters": common_hp,
                "stat_value_multiplier": sm(0.035, 0.012, 0.030, 0.006, 0.035, stat_mult[5]),
                "base_score": bs(0.08, -0.03, 0.06, -0.07, 0.10),
            },
        ),
        (
            "direct_power_floor",
            {
                "expect_attribute": target,
                "learned_hyperparameters": {**common_hp, "power_floor_target": 950, "guts_soft_cap": 600},
                "stat_value_multiplier": sm(0.024, 0.012, 0.025, 0.006, 0.024, stat_mult[5]),
                "base_score": bs(0.04, -0.02, 0.07, -0.06, 0.05),
            },
        ),
        (
            "senior_spd_pwr_wit_extra",
            {
                "expect_attribute": target,
                "learned_hyperparameters": common_hp,
                "stat_value_multiplier": sm(0.025, 0.012, 0.024, 0.006, 0.025, stat_mult[5]),
                "extra_weight": ew([
                    [extra[0][0], extra[0][1], extra[0][2], extra[0][3], extra[0][4]],
                    [0.04, -0.02, 0.05, -0.05, 0.05],
                    [0.08, -0.03, 0.08, -0.06, 0.08],
                    [0.10, -0.05, 0.10, -0.08, 0.10],
                ]),
            },
        ),
        (
            "wit_speed_first",
            {
                "expect_attribute": target,
                "learned_hyperparameters": {**common_hp, "power_floor_target": 850},
                "stat_value_multiplier": sm(0.025, 0.012, 0.021, 0.006, 0.025, stat_mult[5]),
                "base_score": bs(0.06, -0.02, 0.03, -0.06, 0.08),
            },
        ),
        (
            "power_speed_first",
            {
                "expect_attribute": target,
                "learned_hyperparameters": {**common_hp, "power_floor_target": 950},
                "stat_value_multiplier": sm(0.025, 0.011, 0.025, 0.006, 0.021, stat_mult[5]),
                "base_score": bs(0.07, -0.03, 0.08, -0.07, 0.03),
            },
        ),
    ]

    rng = random.Random(seed)
    for idx in range(max(0, int(random_count))):
        speed_weight = rng.uniform(0.026, 0.042)
        stamina_weight = rng.uniform(0.008, 0.024)
        power_weight = rng.uniform(0.020, 0.038)
        guts_weight = rng.uniform(0.004, 0.012)
        wit_weight = rng.uniform(0.026, 0.042)
        learned = dict(common_hp)
        learned.update({
            "stamina_floor_target": rng.choice([625, 650, 675, 700, 725]),
            "power_floor_target": rng.choice([825, 850, 875, 900, 925, 950]),
            "guts_soft_cap": rng.choice([575, 600, 625, 650, 675]),
            "stamina_soft_cap": rng.choice([675, 700, 725, 750]),
        })
        base_row = [
            rng.uniform(0.00, 0.10),
            rng.uniform(-0.06, 0.02),
            rng.uniform(0.00, 0.10),
            rng.uniform(-0.08, 0.00),
            rng.uniform(0.00, 0.10),
        ]
        senior_row = [
            rng.uniform(0.02, 0.14),
            rng.uniform(-0.08, 0.02),
            rng.uniform(0.02, 0.14),
            rng.uniform(-0.10, 0.00),
            rng.uniform(0.02, 0.14),
        ]
        candidates.append((
            f"random_{idx + 1:02d}",
            {
                "expect_attribute": target,
                "learned_hyperparameters": learned,
                "stat_value_multiplier": sm(speed_weight, stamina_weight, power_weight, guts_weight, wit_weight, stat_mult[5]),
                "base_score": bs(*base_row),
                "extra_weight": ew([
                    [0, 0, 0, 0, 0],
                    [v * 0.35 for v in senior_row],
                    [v * 0.70 for v in senior_row],
                    senior_row,
                ]),
            },
        ))

    return candidates


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * max(0.0, min(1.0, float(pct)))
    lo = int(pos)
    hi = min(len(ordered) - 1, lo + 1)
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def _run_objective(result: Any, target: list[int]) -> float:
    weights = {"speed": 1.35, "stamina": 0.60, "power": 1.15, "guts": 0.35, "wit": 1.35}
    stats = {stat: int((result.final_stats or {}).get(stat) or 0) for stat in STAT_KEYS}
    deficit = {
        stat: max(0, target[idx] - stats[stat])
        for idx, stat in enumerate(STAT_KEYS)
    }
    over = {
        stat: max(0, stats[stat] - target[idx])
        for idx, stat in enumerate(STAT_KEYS)
    }
    race_losses = sum(1 for race in result.races_run if not race.get("won"))
    g1_losses = int(result.g1_losses or 0)
    weighted_deficit = sum(deficit[stat] * weights[stat] for stat in STAT_KEYS)
    weighted_over = over["stamina"] * 0.20 + over["guts"] * 0.15
    return (
        weighted_deficit
        + weighted_over
        + race_losses * 300.0
        + g1_losses * 550.0
        - (int(result.rating_score or 0) / 90.0)
    )


def _evaluate(name: str, preset: dict[str, Any], deck: list[dict[str, Any]] | None, *, target: list[int], n: int, seed: int) -> dict[str, Any]:
    from career_bot.career_simulator import run_sweep

    sweep = run_sweep(n_runs=n, preset=preset, deck=deck, seed_base=seed)
    results = sweep["results"]
    med_stats = {
        stat: int(median(result.final_stats[stat] for result in results))
        for stat in STAT_KEYS
    }
    race_losses = [sum(1 for race in result.races_run if not race.get("won")) for result in results]
    g1_losses = [result.g1_losses for result in results]
    train_picks = {
        stat: sum(result.train_picks_by_stat.get(stat, 0) for result in results)
        for stat in STAT_KEYS
    }
    deficit = {
        stat: max(0, target[idx] - med_stats[stat])
        for idx, stat in enumerate(STAT_KEYS)
    }
    over = {
        stat: max(0, med_stats[stat] - target[idx])
        for idx, stat in enumerate(STAT_KEYS)
    }
    median_losses = float(median(race_losses))
    median_g1_losses = float(median(g1_losses))
    run_objectives = [_run_objective(result, target) for result in results]
    objective = (
        median(run_objectives)
        + _percentile(run_objectives, 0.75) * 0.30
        + mean(run_objectives) * 0.20
    )
    return {
        "name": name,
        "objective": round(objective, 3),
        "target": dict(zip(STAT_KEYS, target)),
        "median_stats": med_stats,
        "deficit": deficit,
        "over": over,
        "rating_score_median": sweep["rating_score_median"],
        "rating_score_mean": sweep["rating_score_mean"],
        "rating_score_min": sweep["rating_score_min"],
        "stat_sum_median": sweep["stat_sum_median"],
        "objective_median": round(float(median(run_objectives)), 3),
        "objective_p75": round(float(_percentile(run_objectives, 0.75)), 3),
        "objective_mean": round(float(mean(run_objectives)), 3),
        "rank_distribution": sweep["rank_distribution"],
        "race_losses_median": int(median_losses),
        "g1_losses_median": int(median_g1_losses),
        "train_picks": train_picks,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="1200,700,1100,600,1200")
    parser.add_argument("--n", type=int, default=6, help="Sim careers per candidate.")
    parser.add_argument("--seed", type=int, default=9000)
    parser.add_argument("--validation-n", type=int, default=0, help="Extra sims for a separate validation gate before applying.")
    parser.add_argument("--validation-seed", type=int, default=0)
    parser.add_argument("--validate-top", type=int, default=4)
    parser.add_argument("--allow-loss-regression", action="store_true")
    parser.add_argument("--allow-rating-regression", action="store_true")
    parser.add_argument("--allow-stat-sum-regression", action="store_true")
    parser.add_argument("--allow-missing-schedule", action="store_true")
    parser.add_argument("--random-candidates", type=int, default=8)
    parser.add_argument("--instance", default="")
    parser.add_argument("--preset", default="")
    parser.add_argument("--apply", action="store_true", help="Apply best candidate to the instance preset if it beats baseline.")
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    from career_bot.career_simulator import hydrate_preset_with_latest_session_context

    target = _parse_target(args.target)
    instance = args.instance or _runtime_instance_from_env()
    preset_path = Path(args.preset) if args.preset else _default_preset_path(PROJECT_ROOT, instance)
    if not preset_path.exists():
        raise SystemExit(f"preset not found: {preset_path}")
    base = _load_preset(preset_path)
    base["sim_runtime_instance"] = instance
    hydrated = hydrate_preset_with_latest_session_context(copy.deepcopy(base), PROJECT_ROOT)
    base_schedule = _schedule_summary(base, source="preset")
    hydrated_schedule = _schedule_summary(
        hydrated,
        source=hydrated.get("_sim_latest_session_context_source") or "preset",
    )
    if not args.allow_missing_schedule and not hydrated_schedule["count"]:
        raise SystemExit(
            "custom_race_schedule is required for sim target tuning. "
            "Refusing to fall back to the generic G1 calendar."
        )
    schedule_changed_by_hydration = (
        bool(base_schedule["count"])
        and bool(hydrated_schedule["count"])
        and base_schedule["signature"] != hydrated_schedule["signature"]
    )
    deck = (hydrated.get("_run_context") or {}).get("support_cards") or None
    try:
        from career_bot.presets import expect_attribute_profile_lookup_keys

        active_profile_keys = expect_attribute_profile_lookup_keys(
            hydrated,
            run_context=hydrated.get("_run_context") or {},
            desired_parent_sparks=hydrated.get("desired_parent_sparks"),
        )
    except Exception:
        active_profile_keys = []

    rows = []
    candidates = _candidate_templates(base, target, args.random_candidates, args.seed)
    started = time.time()
    for idx, (name, changes) in enumerate(candidates, start=1):
        candidate = _apply_candidate(base, name, changes, profile_keys=active_profile_keys)
        candidate["sim_runtime_instance"] = instance
        candidate = hydrate_preset_with_latest_session_context(candidate, PROJECT_ROOT)
        row = _evaluate(name, candidate, deck, target=target, n=args.n, seed=args.seed)
        row["changes"] = changes
        rows.append(row)
        print(
            f"{idx:02d}/{len(candidates)} {name}: "
            f"obj={row['objective']:.1f} rating={row['rating_score_median']} "
            f"stats={list(row['median_stats'].values())} losses={row['race_losses_median']}",
            flush=True,
        )

    rows.sort(key=lambda row: row["objective"])
    baseline = next((row for row in rows if row["name"] == "baseline_target"), rows[-1])
    training_best = rows[0]
    best = training_best
    selected = training_best
    validation_rows: list[dict[str, Any]] = []
    validation_baseline: dict[str, Any] | None = None
    validation_apply_allowed = True
    if args.validation_n > 0:
        validation_seed = int(args.validation_seed or (args.seed + 100000))
        top_rows: list[dict[str, Any]] = []
        if baseline not in top_rows:
            top_rows.append(baseline)
        for row in rows:
            if row["name"] == baseline["name"]:
                continue
            top_rows.append(row)
            if len(top_rows) >= max(2, int(args.validate_top) + 1):
                break
        for row in top_rows:
            candidate = _apply_candidate(base, row["name"], row.get("changes") or {}, profile_keys=active_profile_keys)
            candidate["sim_runtime_instance"] = instance
            candidate = hydrate_preset_with_latest_session_context(candidate, PROJECT_ROOT)
            validation = _evaluate(
                row["name"],
                candidate,
                deck,
                target=target,
                n=args.validation_n,
                seed=validation_seed,
            )
            validation["changes"] = row.get("changes") or {}
            validation["training_objective"] = row.get("objective")
            validation["training_rating_score_median"] = row.get("rating_score_median")
            validation["training_stat_sum_median"] = row.get("stat_sum_median")
            validation["training_median_stats"] = row.get("median_stats")
            validation_rows.append(validation)
            print(
                f"validate {row['name']}: obj={validation['objective']:.1f} "
                f"rating={validation['rating_score_median']} "
                f"stats={list(validation['median_stats'].values())} "
                f"losses={validation['race_losses_median']} g1={validation['g1_losses_median']}",
                flush=True,
            )
        validation_rows.sort(key=lambda row: row["objective"])
        validation_baseline = next((row for row in validation_rows if row["name"] == baseline["name"]), None)
        if validation_baseline:
            eligible = []
            for row in validation_rows:
                if row["name"] == validation_baseline["name"]:
                    continue
                loss_safe = (
                    args.allow_loss_regression
                    or (
                        int(row.get("race_losses_median") or 0) <= int(validation_baseline.get("race_losses_median") or 0)
                        and int(row.get("g1_losses_median") or 0) <= int(validation_baseline.get("g1_losses_median") or 0)
                    )
                )
                rating_safe = (
                    args.allow_rating_regression
                    or int(row.get("rating_score_median") or 0) >= int(validation_baseline.get("rating_score_median") or 0)
                )
                stat_sum_safe = (
                    args.allow_stat_sum_regression
                    or int(row.get("stat_sum_median") or 0) >= int(validation_baseline.get("stat_sum_median") or 0)
                )
                if row["objective"] < validation_baseline["objective"] and loss_safe and rating_safe and stat_sum_safe:
                    eligible.append(row)
                else:
                    row["validation_rejected"] = {
                        "objective": not (row["objective"] < validation_baseline["objective"]),
                        "loss_regression": not loss_safe,
                        "rating_regression": not rating_safe,
                        "stat_sum_regression": not stat_sum_safe,
                    }
            if eligible:
                eligible.sort(key=lambda row: row["objective"])
                selected = eligible[0]
                best = selected
            else:
                validation_apply_allowed = False
    report = {
        "schema": "sweepy_sim_target_tuning_v1",
        "instance": instance,
        "preset_path": str(preset_path),
        "target": dict(zip(STAT_KEYS, target)),
        "n_per_candidate": args.n,
        "seed": args.seed,
        "schedule": {
            "base": base_schedule,
            "hydrated": hydrated_schedule,
            "changed_by_latest_session_context": schedule_changed_by_hydration,
            "required": not args.allow_missing_schedule,
        },
        "elapsed_sec": round(time.time() - started, 1),
        "baseline": baseline,
        "training_best": training_best,
        "validation_baseline": validation_baseline,
        "validation_candidates": validation_rows,
        "validation_apply_allowed": validation_apply_allowed,
        "best": best,
        "selected": selected,
        "all_candidates": rows,
        "applied": False,
    }

    out_path = Path(args.output) if args.output else (
        PROJECT_ROOT / "uma_runtime" / "instances" / instance / "sim_tuning" / f"target_tune_{int(time.time())}.json"
    )
    _write_json(out_path, report)

    comparison_baseline = validation_baseline or baseline
    can_apply = (
        selected["name"] != comparison_baseline["name"]
        and selected["objective"] < comparison_baseline["objective"]
        and validation_apply_allowed
        and (
            args.allow_rating_regression
            or int(selected.get("rating_score_median") or 0) >= int(comparison_baseline.get("rating_score_median") or 0)
        )
        and (
            args.allow_stat_sum_regression
            or int(selected.get("stat_sum_median") or 0) >= int(comparison_baseline.get("stat_sum_median") or 0)
        )
    )
    if args.apply and can_apply:
        updated = _apply_candidate(base, selected["name"], selected.get("changes") or {}, profile_keys=active_profile_keys)
        # Keep the exact race calendar used by the validated simulator run.  In
        # normal UI use this is already in the preset; this also protects cases
        # where latest-session context supplied a newer calendar than the file.
        if hydrated.get("custom_race_schedule"):
            updated["custom_race_schedule"] = copy.deepcopy(hydrated.get("custom_race_schedule") or [])
        updated["_sim_target_tuning"] = {
            "applied_at": int(time.time()),
            "report": str(out_path),
            "target": dict(zip(STAT_KEYS, target)),
            "candidate": selected["name"],
            "objective": selected["objective"],
            "baseline_objective": comparison_baseline["objective"],
            "validation_n": int(args.validation_n or 0),
            "validation_seed": int(args.validation_seed or (args.seed + 100000)) if args.validation_n > 0 else None,
            "race_schedule_count": int(hydrated_schedule.get("count") or 0),
        }
        _write_json(preset_path, updated)
        report["applied"] = True
        _write_json(out_path, report)

    print("\n=== SIM TARGET TUNING RESULT ===")
    print(json.dumps({
        "report": str(out_path),
        "applied": report["applied"],
        "baseline": {
            "name": baseline["name"],
            "objective": baseline["objective"],
            "rating": baseline["rating_score_median"],
            "stats": baseline["median_stats"],
            "losses": baseline["race_losses_median"],
        },
        "schedule": {
            "count": hydrated_schedule["count"],
            "first": hydrated_schedule["first"],
            "last": hydrated_schedule["last"],
            "changed_by_latest_session_context": schedule_changed_by_hydration,
        },
        "best": {
            "name": best["name"],
            "objective": best["objective"],
            "rating": best["rating_score_median"],
            "stats": best["median_stats"],
            "losses": best["race_losses_median"],
            "deficit": best["deficit"],
        },
        "selected": {
            "name": selected["name"],
            "objective": selected["objective"],
            "rating": selected["rating_score_median"],
            "stats": selected["median_stats"],
            "losses": selected["race_losses_median"],
            "g1_losses": selected["g1_losses_median"],
            "can_apply": can_apply,
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
