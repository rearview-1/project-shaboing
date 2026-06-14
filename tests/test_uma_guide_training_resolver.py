"""Regression tests for the uma.guide-faithful training-gain resolver.

These pin the decompiled uma.guide training calculator (career_simulator._uma_*
+ _uma_tile_gain) to the exact integers observed on the live uma.guide panel,
and AUDIT all 539 support cards to guarantee every card's unique effects are
acknowledged (the recurring "card unique mis-modeled" class of bug — e.g. NN's
20 vs 15 Race Bonus, the friendship-effectiveness fold, NTR's fan-scaled +20
training-eff). Data: data/support_card_training_effects.json.
"""

import json
from pathlib import Path

from career_bot.career_simulator import (
    CareerSimulator,
    _UMA_EFFECT_KEYS,
    _uma_card_effect,
    _uma_el_level,
    _uma_unique_grant,
)

_DATA = Path(__file__).resolve().parents[1] / "data"


def _sim():
    return CareerSimulator(preset={"scenario_id": 4}, seed=1)


def _train_data():
    return json.loads((_DATA / "support_card_training_effects.json").read_text(encoding="utf-8"))


def test_ntr_matikane_speed_tile_exact():
    """Live uma.guide panel: Narita Top Road (30086) + Matikanefukukitaru (30078),
    Speed L5, Great mood, 30% speed growth, 60% megaphone + speed anklet (=+110%
    training / +20% energy). Panel showed Speed +100, Power +42, SP +10, Energy -27.
    Exercises: multiplicative friendship, NTR's fan-scaled +20 training-eff unique,
    Matikane's +15 mood unique, the post-calc item addon, and energy reduction."""
    out = _sim()._uma_tile_gain(
        [(30086, 4), (30078, 4)], "speed",
        facility_level=5, mood=0.2, growth={"speed": 30},
        item_train_pct=110, item_energy_pct=20,
    )
    assert out["speed"] == 100
    assert out["power"] == 42
    assert out["sp"] == 10
    assert out["energy"] == -27


def test_shinko_ksb_no_item_anchor():
    """User-confirmed: Shinko Windy SR (20031) + Kitasan Black SSR (30028), Speed
    L5, Great mood, no items -> +38 main / +20 sub. Pins the friendship-
    effectiveness fold (Shinko base 25 + 10% unique = 37.5, NOT 35)."""
    out = _sim()._uma_tile_gain([(20031, 4), (30028, 4)], "speed", facility_level=5, mood=0.2)
    assert out["speed"] == 38
    assert out["power"] == 20


def test_known_card_uniques_resolve():
    """Spot-check the specific uniques that previously slipped through."""
    data = _train_data()
    # Narita Top Road: fan-scaled training-eff unique applies a flat +20.
    ntr = data["30086"]
    assert _uma_card_effect(ntr, 8, _uma_el_level(4, "SSR"), matching=True) == 20
    # Matikane 30286 (new SSR): base te 10 + type-101 unique +10 = 20.
    m286 = data["30286"]
    assert _uma_card_effect(m286, 8, _uma_el_level(4, "SSR"), matching=True) == 20
    # Shinko Windy SR: friendship base 25 folded with +10% effectiveness = 37.5.
    sw = data["20031"]
    assert _uma_card_effect(sw, 1, _uma_el_level(4, "SR"), matching=True) == 37.5


def test_all_cards_present_in_training_data():
    """Every support card the sim knows about must have uma.guide training data,
    so no card silently falls back to a guess."""
    bonuses = json.loads((_DATA / "support_card_bonuses.json").read_text(encoding="utf-8"))
    data = _train_data()
    missing = [cid for cid in bonuses if str(cid).isdigit() and str(cid) not in data]
    assert not missing, f"{len(missing)} cards missing training data: {missing[:10]}"


def test_every_training_relevant_unique_is_acknowledged():
    """AUDIT: for every card whose unique grants a training-relevant effect, the
    resolver's output for that effect must change vs ignoring the unique. This is
    the guarantee the user asked for — no card's unique is silently dropped."""
    data = _train_data()
    acknowledged = 0
    failures = []
    for cid, record in data.items():
        unique = record.get("u") or {}
        if not unique:
            continue
        rarity = record.get("r") or "SSR"
        level = _uma_el_level(4, rarity)
        no_unique = {"c": record.get("c") or {}, "u": {}, "r": rarity, "t": record.get("t")}
        for fx in _UMA_EFFECT_KEYS:
            for matching in (True, False):
                grant = _uma_unique_grant(unique, fx, level, matching)
                if not grant:
                    continue
                with_u = _uma_card_effect(record, fx, level, matching)
                without_u = _uma_card_effect(no_unique, fx, level, matching)
                if with_u == without_u:
                    failures.append((cid, fx, matching, with_u, grant))
                else:
                    acknowledged += 1
    assert not failures, f"uniques granted but not reflected in resolved value: {failures[:10]}"
    # Sanity: a meaningful number of cards have training-relevant uniques.
    assert acknowledged > 100, f"only {acknowledged} training-relevant unique grants acknowledged"


def test_per_turn_item_addon_matches_tile():
    """The per-turn _apply_training must apply megaphone+anklet as the additive
    post-calc addon (final = R + floor(R*train_pct/100)), not a max() multiplier.
    A base gain of 48 with 60% megaphone + 50% speed anklet must land at 100 —
    the same as the validated NTR+Matikane tile."""
    sim = _sim()
    sim.state["turn"] = 1
    sim.state["active_item_effects"] = [
        {"kind": "megaphone", "train_pct": 60, "end_turn": 99},
        {"kind": "ankle", "stat": "speed", "train_pct": 50, "hp_cost": 5, "end_turn": 99},
    ]
    # megaphone hits every facility; the speed anklet only its own facility
    assert sim._active_training_addons("speed") == 110.0
    assert sim._active_training_addons("power") == 60.0
    sim.state["speed"] = 0
    sim.state["skill_point"] = 0
    sim.state["hp"] = 100
    cmd = {
        "_sim_primary_stat": "speed", "failure_rate": 0,
        "params_inc_dec_info_array": [
            {"target_type": 1, "value": 48},   # speed base R
            {"target_type": 30, "value": 5},   # SP base
        ],
        "training_partner_array": [],
    }
    sim._apply_training(cmd)
    assert sim.state["speed"] == 100      # 48 + floor(48*1.10)
    assert sim.state["skill_point"] == 10  # 5 + floor(5*1.10)


def test_mant_megaphone_is_20_40_60():
    """MANT (scenario 4) megaphones are +20/40/60% (trackblazer), not the
    standard +15/30/45%. Tier-3 megaphone item 8003 = the 60% trackblazer one."""
    mant = _sim()
    mant.state["turn"] = 1
    mant._add_item(8003)
    mant._use_item(8003)
    pct = next(e["train_pct"] for e in mant.state["active_item_effects"] if e.get("kind") == "megaphone")
    assert pct == 60
    std = CareerSimulator(preset={"scenario_id": 1}, seed=1)
    std.state["turn"] = 1
    std._add_item(8003)
    std._use_item(8003)
    pct2 = next(e["train_pct"] for e in std.state["active_item_effects"] if e.get("kind") == "megaphone")
    assert pct2 == 45


def test_resolver_never_crashes_on_any_card():
    """Resolve every effect type for every card at every limit break — proves the
    full 539-card dataset is well-formed and the resolver is total."""
    data = _train_data()
    for cid, record in data.items():
        rarity = record.get("r") or "SSR"
        for lb in range(5):
            level = _uma_el_level(lb, rarity)
            for fx in _UMA_EFFECT_KEYS:
                val = _uma_card_effect(record, fx, level, matching=True)
                assert isinstance(val, (int, float))
