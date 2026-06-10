"""Tests for the per-deck cached policy pipeline.

The pipeline:
  1. `deck_signature` produces a stable hash from trainee + deck + scenario.
  2. `optimize_deck_policy.py` writes winning hyperparameters keyed by that
     signature to `uma_runtime/instances/<instance>/sim_calibration/deck_policies.json`.
  3. `main._apply_cached_deck_policy` reads from that cache and fills any
     `learned_hyperparameters` keys the user hasn't already set.

These tests pin the cache module's API + behavior. The optimizer itself is
exercised via integration (running it on the user's deck), not unit tests.
"""
from __future__ import annotations

from pathlib import Path

from career_bot.deck_policy_cache import (
    SCHEMA,
    apply_policy_to_preset,
    cache_path,
    deck_signature,
    load_cache,
    lookup_policy,
    save_cache,
    save_policy,
)


def test_signature_is_stable_across_slot_order():
    a = deck_signature(trainee_card_id=102001,
                        support_card_ids=[30036, 30054, 30014, 30010, 30028],
                        scenario_id=4, friend_card_id=30017)
    b = deck_signature(trainee_card_id=102001,
                        support_card_ids=[30028, 30010, 30014, 30054, 30036],
                        scenario_id=4, friend_card_id=30017)
    assert a == b, "signature must be slot-order independent"


def test_signature_changes_with_deck():
    a = deck_signature(trainee_card_id=102001,
                        support_card_ids=[30036, 30054, 30014, 30010, 30028],
                        scenario_id=4, friend_card_id=30017)
    b = deck_signature(trainee_card_id=102001,
                        support_card_ids=[30036, 30054, 30014, 30010, 99999],
                        scenario_id=4, friend_card_id=30017)
    assert a != b


def test_signature_changes_with_trainee():
    a = deck_signature(trainee_card_id=102001,
                        support_card_ids=[30036, 30054, 30014, 30010, 30028],
                        scenario_id=4, friend_card_id=30017)
    b = deck_signature(trainee_card_id=102002,
                        support_card_ids=[30036, 30054, 30014, 30010, 30028],
                        scenario_id=4, friend_card_id=30017)
    assert a != b


def test_signature_changes_with_friend():
    a = deck_signature(trainee_card_id=102001,
                        support_card_ids=[30036, 30054, 30014, 30010, 30028],
                        scenario_id=4, friend_card_id=30017)
    b = deck_signature(trainee_card_id=102001,
                        support_card_ids=[30036, 30054, 30014, 30010, 30028],
                        scenario_id=4, friend_card_id=30021)
    assert a != b


def test_load_cache_returns_empty_when_missing(tmp_path):
    cache = load_cache(tmp_path, "fake-instance")
    assert cache.get("schema") == SCHEMA
    assert cache.get("policies") == {}


def test_save_and_reload_round_trip(tmp_path):
    cache = load_cache(tmp_path, "fake-instance")
    sig = deck_signature(trainee_card_id=1, support_card_ids=[10, 20],
                         scenario_id=4, friend_card_id=30)
    save_policy(
        cache, sig,
        trainee_card_id=1,
        support_card_ids=[10, 20],
        scenario_id=4,
        friend_card_id=30,
        learned_hyperparameters={"speed_priority_bonus_mid": 0.18},
        baseline_rating_mean=15000.0,
        optimized_rating_mean=15500.0,
        rating_lift=500.0,
        n_baseline=8,
        n_optimized=8,
        optimized_at_iso="2026-06-06T00:00:00",
    )
    save_cache(cache, tmp_path, "fake-instance")
    reload = load_cache(tmp_path, "fake-instance")
    entry = reload["policies"][sig]
    assert entry["learned_hyperparameters"]["speed_priority_bonus_mid"] == 0.18
    assert entry["rating_lift"] == 500.0
    assert entry["trainee_card_id"] == 1


def test_apply_policy_fills_missing_keys_only():
    """User overrides MUST WIN. Cache only fills gaps."""
    preset = {"learned_hyperparameters": {"speed_priority_bonus_mid": 0.99}}
    policy = {"speed_priority_bonus_mid": 0.20, "wit_priority_bonus_mid": 0.15}
    apply_policy_to_preset(preset, policy)
    # User's 0.99 must be preserved
    assert preset["learned_hyperparameters"]["speed_priority_bonus_mid"] == 0.99
    # Cache's wit value should fill in
    assert preset["learned_hyperparameters"]["wit_priority_bonus_mid"] == 0.15


def test_apply_policy_handles_no_policy():
    preset = {"learned_hyperparameters": {"x": 1}}
    apply_policy_to_preset(preset, None)
    assert preset == {"learned_hyperparameters": {"x": 1}}


def test_apply_policy_creates_section_when_absent():
    preset = {}
    apply_policy_to_preset(preset, {"speed_priority_bonus_mid": 0.20})
    assert preset["learned_hyperparameters"]["speed_priority_bonus_mid"] == 0.20


def test_cache_path_routes_to_instance_dir():
    p = cache_path(Path("/tmp/myroot"), "instance_x")
    assert p.parts[-3:] == ("instance_x", "sim_calibration", "deck_policies.json")


def test_lookup_returns_none_for_unknown_signature():
    cache = {"schema": SCHEMA, "policies": {}}
    assert lookup_policy(cache, "nonexistent") is None
