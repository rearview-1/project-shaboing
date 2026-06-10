"""Per-deck cached policy: offline-optimized hyperparameters keyed by
deck/trainee/scenario signature.

The bot's training/race strategy has dozens of tunable scoring weights
(speed priority bonuses, soft caps, failure caps, facility bonuses, etc).
Different decks favor different weightings — a 2-Speed/2-Wit deck wants
different bonuses than a 3-Power deck.

This module:
1. Computes a stable signature for a deck/trainee/scenario combo.
2. Looks up cached hyperparameter overrides for that signature.
3. Applies them onto a preset as `learned_hyperparameters` overrides.

The offline optimizer (`tools/optimize_deck_policy.py`) writes entries here.
The bot's preset-hydration path reads entries here at the start of every
real career.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path


SCHEMA = "sweepy_deck_policy_cache_v1"


def deck_signature(*,
                   trainee_card_id: int,
                   support_card_ids,
                   scenario_id: int = 4,
                   friend_card_id: int = 0) -> str:
    """Stable hash of the deck/trainee/scenario combo.

    Same deck composition → same signature regardless of slot order.
    Friend card is included separately because it changes which stat-friend
    recreations are available.
    """
    ids = sorted(int(i or 0) for i in support_card_ids or [] if int(i or 0))
    payload = json.dumps({
        "scenario_id": int(scenario_id or 0),
        "trainee_card_id": int(trainee_card_id or 0),
        "support_card_ids": ids,
        "friend_card_id": int(friend_card_id or 0),
    }, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def cache_path(project_root: Path, instance: str = "account_b") -> Path:
    return (Path(project_root) / "uma_runtime" / "instances" / instance
            / "sim_calibration" / "deck_policies.json")


def load_cache(project_root: Path, instance: str = "account_b") -> dict:
    p = cache_path(project_root, instance)
    if not p.exists():
        return {"schema": SCHEMA, "policies": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("schema") != SCHEMA:
            return {"schema": SCHEMA, "policies": {}}
        if not isinstance(data.get("policies"), dict):
            data["policies"] = {}
        return data
    except Exception:
        return {"schema": SCHEMA, "policies": {}}


def save_cache(cache: dict, project_root: Path, instance: str = "account_b"):
    p = cache_path(project_root, instance)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")


def lookup_policy(cache: dict, signature: str) -> dict | None:
    return ((cache.get("policies") or {}).get(signature) or {}).get("learned_hyperparameters")


def save_policy(cache: dict, signature: str, *,
                trainee_card_id: int,
                support_card_ids,
                scenario_id: int,
                friend_card_id: int,
                learned_hyperparameters: dict,
                baseline_rating_mean: float,
                optimized_rating_mean: float,
                rating_lift: float,
                n_baseline: int,
                n_optimized: int,
                optimized_at_iso: str) -> dict:
    """Record an optimized policy. Returns the cache (modified in-place)."""
    policies = cache.setdefault("policies", {})
    policies[signature] = {
        "trainee_card_id": int(trainee_card_id),
        "support_card_ids": sorted(int(i) for i in support_card_ids or []),
        "scenario_id": int(scenario_id),
        "friend_card_id": int(friend_card_id),
        "learned_hyperparameters": dict(learned_hyperparameters or {}),
        "baseline_rating_mean": float(baseline_rating_mean),
        "optimized_rating_mean": float(optimized_rating_mean),
        "rating_lift": float(rating_lift),
        "n_baseline_sims": int(n_baseline),
        "n_optimized_sims": int(n_optimized),
        "optimized_at": str(optimized_at_iso),
    }
    return cache


def apply_policy_to_preset(preset: dict, policy: dict | None) -> dict:
    """Merge a cached policy's hyperparameters into the preset's
    `learned_hyperparameters` sub-dict. Existing user-set values WIN — the
    cache only fills gaps, so user overrides aren't clobbered by stale
    optimized policies.
    """
    if not policy:
        return preset
    existing = dict(preset.get("learned_hyperparameters") or {})
    for k, v in policy.items():
        existing.setdefault(k, v)
    preset["learned_hyperparameters"] = existing
    return preset
