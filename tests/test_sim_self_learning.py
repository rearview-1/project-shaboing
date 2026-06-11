"""Tests for the sim self-learning analyzer.

Architectural commitment: the analyzer ONLY proposes adjustments to
keys in LEARNABLE_PARAMS — never operator-owned fields (deck,
calendar, skill_profile_style, parents). The tests pin this so a
future refactor that adds a new "learnable" key has to be explicit
about it, and a refactor that accidentally lets the analyzer touch an
operator-owned key gets caught.
"""
from career_bot.sim_self_learning import (
    LEARNABLE_PARAMS,
    Proposal,
    clamp_learned_value,
    _current_lhp_value,
    _quartile_split,
    _train_pick_rates,
    analyze_batch,
    propose_final_stat_pressure_adjustments,
    propose_priority_bonus_adjustments,
)


class _FakeResult:
    """Minimal stand-in for SimResult — only the fields the analyzer reads."""
    def __init__(self, rating, train_picks=None, final_stats=None):
        self.rating_score = rating
        self.train_picks_by_stat = train_picks or {
            "speed": 0, "stamina": 0, "power": 0, "guts": 0, "wit": 0,
        }
        self.final_stats = final_stats or {}


# -------------------- LEARNABLE_PARAMS guard --------------------

def test_learnable_params_excludes_operator_owned_keys():
    """Critical invariant: the analyzer must NEVER propose changes to
    operator-owned fields. If a future change adds an operator-owned
    key to LEARNABLE_PARAMS by mistake, this catches it."""
    operator_owned = {
        # Deck composition / identity
        "support_card_ids", "trainee_card_id", "friend_card_id",
        # Style / skill plan / aspiration
        "skill_profile_style", "skill_profile_distance",
        "skill_buy_on_sight", "learn_skill_list", "skill_blacklist_custom",
        # Calendar / race agenda
        "race_plan_text", "custom_race_schedule", "extra_race_list", "race_list",
        # Parents
        "parent_id_1", "parent_id_2", "desired_parent_sparks",
        # Scenario-level identity
        "scenario_id", "preset_family", "name",
    }
    leaked = operator_owned & LEARNABLE_PARAMS
    assert leaked == set(), (
        f"Operator-owned keys leaked into LEARNABLE_PARAMS: {leaked}. "
        f"The analyzer must NEVER touch these — they're the user's "
        f"intent, not bot-tunable execution."
    )


def test_proposal_only_touches_learnable_param():
    """Every Proposal the analyzer emits must target a LEARNABLE_PARAMS
    key. The dataclass itself doesn't enforce this — the production
    code in `analyze_batch`/`propose_*` is responsible for it. This
    test verifies the contract holds."""
    # Build a batch that should produce SOME proposals
    bottom = [_FakeResult(14000, {"speed": 10, "stamina": 2, "power": 2, "wit": 3, "guts": 1}) for _ in range(3)]
    top = [_FakeResult(17600, {"speed": 4, "stamina": 4, "power": 6, "wit": 4, "guts": 1}) for _ in range(3)]
    proposals = analyze_batch(bottom + top, preset={})
    for p in proposals:
        assert p.param_name in LEARNABLE_PARAMS, (
            f"Proposal touches {p.param_name} which is not in "
            f"LEARNABLE_PARAMS — analyzer violated its scope."
        )


# -------------------- _train_pick_rates --------------------

def test_train_pick_rates_normalizes_across_batch():
    """Rates must sum to 1.0 (or 0 for an empty batch) and be the
    aggregated share per stat across ALL sims in the batch."""
    results = [
        _FakeResult(15000, {"speed": 8, "stamina": 2}),
        _FakeResult(16000, {"speed": 6, "wit": 4}),
    ]
    rates = _train_pick_rates(results)
    # 14 speed / 20 total, 2 stamina / 20, 4 wit / 20
    assert abs(rates["speed"] - 14 / 20) < 1e-9
    assert abs(rates["stamina"] - 2 / 20) < 1e-9
    assert abs(rates["wit"] - 4 / 20) < 1e-9
    # Must sum to 1.0
    assert abs(sum(rates.values()) - 1.0) < 1e-9


def test_train_pick_rates_empty_batch_returns_zeros():
    """Empty batch must not raise — return 0.0 for every stat."""
    rates = _train_pick_rates([])
    assert sum(rates.values()) == 0.0
    assert all(v == 0.0 for v in rates.values())


# -------------------- _quartile_split --------------------

def test_quartile_split_returns_bottom_and_top():
    """Quartile split puts the worst-rating sims in `bottom` and the
    best in `top`. Used by the analyzer to compare patterns."""
    results = [_FakeResult(r) for r in [14000, 15000, 16000, 17000, 18000]]
    bottom, top = _quartile_split(results)
    assert all(r.rating_score < 17000 for r in bottom)
    assert all(r.rating_score >= 17000 for r in top)


def test_quartile_split_handles_tiny_batch():
    """Fewer than 2 results → return empty lists (can't split)."""
    assert _quartile_split([]) == ([], [])
    assert _quartile_split([_FakeResult(15000)]) == ([], [])


# -------------------- propose_priority_bonus_adjustments --------------------

def test_no_proposal_when_top_and_bottom_pick_similarly():
    """If top and bottom quartile sims picked stats at the same rate,
    there's no learnable signal — emit no proposals."""
    same = {"speed": 6, "stamina": 2, "power": 4, "wit": 6, "guts": 2}
    results = [_FakeResult(15000 + i * 100, same) for i in range(8)]
    proposals = propose_priority_bonus_adjustments(results, preset={})
    assert proposals == []


def test_proposal_when_top_picks_power_more_often():
    """The headline use case: top-quartile sims trained Power more.
    Analyzer should propose increasing power_priority_bonus_late."""
    bottom = [_FakeResult(14000, {
        "speed": 10, "stamina": 2, "power": 2, "wit": 5, "guts": 1,
    }) for _ in range(3)]
    top = [_FakeResult(17600, {
        "speed": 6, "stamina": 2, "power": 8, "wit": 3, "guts": 1,
    }) for _ in range(3)]
    proposals = propose_priority_bonus_adjustments(bottom + top, preset={})
    power_props = [p for p in proposals if "power" in p.param_name]
    assert power_props, (
        "Expected at least one power-related proposal when top-quartile "
        "picked power more often"
    )
    p = power_props[0]
    assert p.proposed_value > p.current_value, (
        "Proposed value must be HIGHER than current — top picked it more"
    )
    assert p.param_name in LEARNABLE_PARAMS


def test_proposal_below_min_delta_skipped():
    """Small differences (< min_rate_delta) should be treated as noise."""
    # Top picks power 1pp more — way below the 4pp default threshold
    bottom = [_FakeResult(14000, {"speed": 5, "power": 5, "wit": 5}) for _ in range(3)]
    top = [_FakeResult(17600, {"speed": 5, "power": 5.5, "wit": 5}) for _ in range(3)]
    proposals = propose_priority_bonus_adjustments(bottom + top, preset={})
    # Should be empty — no signal big enough to act on
    assert proposals == []


def test_proposal_respects_existing_preset_value():
    """When the preset already has a learned value, the proposal
    increments FROM that value, not from the default. This makes
    iteration cumulative."""
    bottom = [_FakeResult(14000, {"speed": 10, "stamina": 2, "power": 2, "wit": 5, "guts": 1}) for _ in range(3)]
    top = [_FakeResult(17600, {"speed": 4, "stamina": 2, "power": 9, "wit": 4, "guts": 1}) for _ in range(3)]
    preset = {"learned_hyperparameters": {"power_priority_bonus_late": 0.15}}
    proposals = propose_priority_bonus_adjustments(bottom + top, preset)
    pp = next((p for p in proposals if p.param_name == "power_priority_bonus_late"), None)
    assert pp is not None
    assert pp.current_value == 0.15, (
        f"current_value must read from preset (0.15), got {pp.current_value}"
    )
    assert pp.proposed_value > 0.15


def test_proposal_includes_rationale():
    """Every proposal must carry a plain-language rationale the
    operator can audit — no opaque adjustments."""
    bottom = [_FakeResult(14000, {"speed": 10, "stamina": 2, "power": 2, "wit": 4, "guts": 2}) for _ in range(3)]
    top = [_FakeResult(17600, {"speed": 4, "stamina": 4, "power": 8, "wit": 3, "guts": 1}) for _ in range(3)]
    proposals = propose_priority_bonus_adjustments(bottom + top, preset={})
    assert proposals
    for p in proposals:
        assert p.rationale, "Proposal must have a non-empty rationale"
        # Some basic content check — the rationale should reference numbers
        assert "%" in p.rationale, (
            f"Rationale should include pick-rate percentages: {p.rationale}"
        )


# -------------------- _current_lhp_value --------------------

def test_current_lhp_value_reads_preset_when_present():
    preset = {"learned_hyperparameters": {"speed_priority_bonus_late": 0.42}}
    assert _current_lhp_value(preset, "speed_priority_bonus_late", 0.22) == 0.42


def test_current_lhp_value_falls_back_to_default_when_missing():
    preset = {"learned_hyperparameters": {}}
    assert _current_lhp_value(preset, "speed_priority_bonus_late", 0.22) == 0.22


def test_current_lhp_value_handles_no_lhp_block():
    """Preset with no learned_hyperparameters block at all → default."""
    assert _current_lhp_value({"name": "raw"}, "stamina_priority_bonus_base", 0.03) == 0.03
    # None preset
    assert _current_lhp_value(None, "stamina_priority_bonus_base", 0.03) == 0.03


# -------------------- bounds / final stat pressure --------------------

def test_clamp_learned_value_bounds_and_integer_params():
    assert clamp_learned_value("wit_priority_bonus_late", 99) == 0.7
    assert clamp_learned_value("wit_priority_bonus_late", -1) == 0.0
    assert clamp_learned_value("power_floor_target", 1199.6) == 1200
    assert clamp_learned_value("calendar_race_prebuy_max_skills", 99) == 12


def test_final_stat_pressure_proposes_speed_wit_when_under_target():
    results = [
        _FakeResult(14500, final_stats={
            "speed": 900, "stamina": 700, "power": 1000, "guts": 500, "wit": 880,
        }),
        _FakeResult(15000, final_stats={
            "speed": 940, "stamina": 720, "power": 980, "guts": 480, "wit": 900,
        }),
    ]
    proposals = propose_final_stat_pressure_adjustments(
        results,
        {"learned_hyperparameters": {
            "speed_floor_target": 950,
            "wit_priority_bonus_late": 0.30,
        }},
        target_stats={"speed": 1120, "wit": 1120},
    )
    names = {p.param_name for p in proposals}
    assert "speed_priority_bonus_late" in names
    assert "wit_priority_bonus_mid" in names
    assert "wit_priority_bonus_late" in names
    for p in proposals:
        assert p.param_name in LEARNABLE_PARAMS
        assert p.proposed_value > p.current_value
        assert p.rationale


def test_final_stat_pressure_skips_when_batch_is_close_enough():
    results = [
        _FakeResult(17600, final_stats={"speed": 1110, "wit": 1100, "power": 940}),
        _FakeResult(17800, final_stats={"speed": 1120, "wit": 1120, "power": 960}),
    ]
    proposals = propose_final_stat_pressure_adjustments(
        results,
        {},
        target_stats={"speed": 1120, "wit": 1120, "power": 950},
        min_shortfall=80,
    )
    assert proposals == []


# -------------------- analyze_batch entry point --------------------

def test_analyze_batch_returns_empty_for_too_few_results():
    """Below 4 results we don't have enough signal — return []."""
    assert analyze_batch([_FakeResult(15000)] * 3) == []


def test_analyze_batch_aggregates_all_analyzers():
    """analyze_batch is the public entry point. Currently it only
    runs the priority-bonus analyzer; future analyzers (outing timing,
    skill timing) will be added here. Test ensures the public surface
    works end-to-end."""
    bottom = [_FakeResult(14000, {"speed": 10, "stamina": 2, "power": 2, "wit": 5, "guts": 1}) for _ in range(3)]
    top = [_FakeResult(17600, {"speed": 4, "stamina": 4, "power": 8, "wit": 3, "guts": 1}) for _ in range(3)]
    out = analyze_batch(bottom + top, preset={})
    assert isinstance(out, list)
    for p in out:
        assert isinstance(p, Proposal)
