"""Tests for the Calibrate button backend (`tools/calibrate_deck.py`).

The script is the engine behind the "CALIBRATE" UI button. Operator
plugs in their deck, clicks the button, and a 3-5 minute sim sweep
finds a strategy override that hits the SS-comfort threshold for that
exact deck. The winner is cached in `deck_policy_cache` so the next
live career picks it up automatically.

Tests pin the calibration helpers' contract so a refactor that
silently breaks the comfort check or the persistence path is caught.
"""
import copy

from tools.calibrate_deck import (
    _comfort_seed_overrides,
    _dedupe_override_candidates,
    _epithet_losses,
    _epithet_race_names,
    _is_best_effort_clean_progress,
    _is_comfortable,
    _merge_overrides_into_preset,
    _mean_rating,
    _quality_key,
    _self_learning_overrides_from_results,
    _ss_rate,
    _strat_summary,
    _win_rate,
)


class _FakeResult:
    """Mimics the relevant CareerSimulator result fields."""
    def __init__(self, rating: int, races_run=None, train_picks=None, final_stats=None):
        self.rating_score = rating
        self.rank = "SS" if rating >= 17500 else ("S+" if rating >= 15900 else "S")
        self.stat_sum = 4000
        # Each race: dict with at least `name` and `won`
        self.races_run = races_run or []
        self.train_picks_by_stat = train_picks or {
            "speed": 0, "stamina": 0, "power": 0, "guts": 0, "wit": 0,
        }
        self.final_stats = final_stats or {}


# -------------------- _ss_rate / _mean_rating --------------------

def test_ss_rate_counts_only_above_threshold():
    """SS rate is the fraction of results >= threshold."""
    results = [_FakeResult(17600), _FakeResult(17500), _FakeResult(17499), _FakeResult(0)]
    # Default threshold 17500
    assert _ss_rate(results) == 0.5


def test_ss_rate_empty_is_zero():
    """Empty list shouldn't crash."""
    assert _ss_rate([]) == 0.0


def test_mean_rating_handles_empty():
    """Empty mean is 0, not a ZeroDivisionError."""
    assert _mean_rating([]) == 0.0


def test_mean_rating_is_arithmetic_mean():
    results = [_FakeResult(15000), _FakeResult(17000), _FakeResult(19000)]
    assert _mean_rating(results) == 17000


# -------------------- _is_comfortable --------------------

def test_comfortable_requires_both_ss_rate_and_mean():
    """A deck only counts as 'comfortably calibrated' if BOTH the SS
    rate target AND the mean target are met. Otherwise low-variance
    near-misses or high-variance flukes pass the gate.

    These cases also pass a relaxed win-rate gate (0.0) and unlimited
    epithet losses so we isolate the SS-rate/mean behavior under test."""
    # SS rate met (3/5 = 60%), mean too low — NOT comfortable
    # Mean = (17500*3 + 10000*2)/5 = 71500/5 = 14300 < 17000
    bad_mean = [_FakeResult(17500)] * 3 + [_FakeResult(10000)] * 2
    assert _is_comfortable(bad_mean, target_ss_rate=0.6, target_mean=17000,
                            ss_threshold=17500, target_win_rate=0.0,
                            max_epithet_losses=999) is False
    # Mean met, SS rate too low — NOT comfortable
    bad_ss = [_FakeResult(17400)] * 5
    assert _is_comfortable(bad_ss, target_ss_rate=0.6, target_mean=17000,
                            ss_threshold=17500, target_win_rate=0.0,
                            max_epithet_losses=999) is False
    # Both met — comfortable
    good = [_FakeResult(17600)] * 4 + [_FakeResult(17000)]
    assert _is_comfortable(good, target_ss_rate=0.6, target_mean=17000,
                            ss_threshold=17500, target_win_rate=0.0,
                            max_epithet_losses=999) is True


def test_comfortable_at_exact_threshold():
    """Boundary: exactly hitting the target should count as comfortable
    (>=, not >). The whole point of calibrate is to STOP when threshold
    hits — off-by-one here would cause unnecessary extra probes."""
    on_target = [_FakeResult(17500), _FakeResult(17500), _FakeResult(17500)]
    # 100% SS, mean 17500
    assert _is_comfortable(on_target, target_ss_rate=1.0, target_mean=17500,
                            ss_threshold=17500, target_win_rate=0.0,
                            max_epithet_losses=999) is True


def test_comfortable_rejects_below_min_rating_floor():
    """A calibration batch with an A+ outlier is not comfortable."""
    mostly_ss = [_FakeResult(18000)] * 9 + [_FakeResult(14000)]
    assert _is_comfortable(
        mostly_ss,
        target_ss_rate=0.90,
        target_mean=17500,
        ss_threshold=17500,
        target_win_rate=0.0,
        max_epithet_losses=999,
        min_rating=14500,
    ) is False


def test_best_effort_clean_progress_can_trade_small_rating_for_zero_epithet_losses():
    baseline = [
        _FakeResult(17600, races_run=[{"name": "Kikuka Sho", "won": False}]),
        _FakeResult(17100, races_run=[{"name": "Tenno Sho (Autumn)", "won": False}]),
        _FakeResult(16000, races_run=[{"name": "Japan Cup", "won": True}]),
    ]
    candidate = [
        _FakeResult(16600, races_run=[{"name": "Kikuka Sho", "won": True}]),
        _FakeResult(16500, races_run=[{"name": "Tenno Sho (Autumn)", "won": True}]),
        _FakeResult(16400, races_run=[{"name": "Japan Cup", "won": True}]),
    ]

    assert _is_best_effort_clean_progress(
        candidate,
        baseline,
        ss_threshold=17500,
        target_win_rate=0.95,
        max_epithet_losses=0,
        min_rating=14500,
    ) is True


def test_best_effort_clean_progress_rejects_large_rating_drop():
    baseline = [
        _FakeResult(17600, races_run=[{"name": "Kikuka Sho", "won": False}]),
        _FakeResult(17100, races_run=[{"name": "Tenno Sho (Autumn)", "won": False}]),
    ]
    candidate = [
        _FakeResult(15000, races_run=[{"name": "Kikuka Sho", "won": True}]),
        _FakeResult(14900, races_run=[{"name": "Tenno Sho (Autumn)", "won": True}]),
    ]

    assert _is_best_effort_clean_progress(
        candidate,
        baseline,
        ss_threshold=17500,
        target_win_rate=0.95,
        max_epithet_losses=0,
        min_rating=14500,
    ) is False


def test_quality_key_prefers_mean_after_clean_gates():
    lower_mean_higher_min = [_FakeResult(16400), _FakeResult(16400)]
    higher_mean_lower_min = [_FakeResult(16350), _FakeResult(16900)]

    assert _quality_key(
        higher_mean_lower_min,
        ss_threshold=17500,
        target_win_rate=0.95,
        max_epithet_losses=0,
        min_rating=14500,
    ) > _quality_key(
        lower_mean_higher_min,
        ss_threshold=17500,
        target_win_rate=0.95,
        max_epithet_losses=0,
        min_rating=14500,
    )


# -------------------- _merge_overrides_into_preset --------------------

def test_merge_overrides_adds_to_existing_lhp():
    """Sampled overrides must merge on top of existing
    `learned_hyperparameters`, not replace them. The user's preset
    carries dozens of learned values; losing them via a clean replace
    would regress every other lever."""
    base = {
        "name": "test",
        "learned_hyperparameters": {
            "wit_priority_bonus_late": 0.35,
            "speed_priority_bonus_late": 0.10,
            "stat_value_bonus": 99,
        },
    }
    overrides = {"wit_priority_bonus_late": 0.40, "new_param": 7}
    merged = _merge_overrides_into_preset(base, overrides)
    lhp = merged["learned_hyperparameters"]
    # Existing un-touched values preserved
    assert lhp["stat_value_bonus"] == 99
    assert lhp["speed_priority_bonus_late"] == 0.10
    # Override wins on the collision
    assert lhp["wit_priority_bonus_late"] == 0.40
    # New keys added
    assert lhp["new_param"] == 7


def test_merge_does_not_mutate_input_preset():
    """The merge must deepcopy — running calibrate must NOT silently
    mutate the in-memory baseline preset for the rest of the bot."""
    base = {
        "name": "test",
        "learned_hyperparameters": {"x": 1},
    }
    base_snapshot = copy.deepcopy(base)
    _merge_overrides_into_preset(base, {"x": 999, "y": 2})
    # Base should be untouched
    assert base == base_snapshot


def test_merge_handles_missing_lhp_block():
    """If baseline preset has no learned_hyperparameters block yet, the
    merge should create one cleanly rather than crash."""
    base = {"name": "test"}
    merged = _merge_overrides_into_preset(base, {"speed_soft_cap": 1150})
    assert merged["learned_hyperparameters"]["speed_soft_cap"] == 1150


# -------------------- self-learning candidate helpers --------------------

def test_dedupe_override_candidates_keeps_first_unique():
    candidates = [
        {"speed_priority_bonus_late": 0.3},
        {"speed_priority_bonus_late": 0.3},
        {"wit_priority_bonus_late": 0.5},
        {},
    ]
    assert _dedupe_override_candidates(candidates) == [
        {"speed_priority_bonus_late": 0.3},
        {"wit_priority_bonus_late": 0.5},
    ]


def test_self_learning_overrides_from_results_only_returns_learnable_keys():
    low = [_FakeResult(
        14000,
        train_picks={"speed": 10, "stamina": 1, "power": 1, "guts": 1, "wit": 2},
        final_stats={"speed": 900, "stamina": 700, "power": 800, "guts": 500, "wit": 850},
    ) for _ in range(3)]
    high = [_FakeResult(
        17600,
        train_picks={"speed": 5, "stamina": 2, "power": 7, "guts": 1, "wit": 6},
        final_stats={"speed": 1000, "stamina": 720, "power": 950, "guts": 520, "wit": 980},
    ) for _ in range(3)]
    out = _self_learning_overrides_from_results(
        low + high,
        {"learned_hyperparameters": {"skill_profile_style": "pace"}},
        base_overrides={"speed_priority_bonus_late": 0.3},
    )
    assert out
    forbidden = {
        "skill_profile_style", "custom_race_schedule", "support_card_ids",
        "parent_id_1", "parent_id_2",
    }
    for row in out:
        assert forbidden.isdisjoint(row)
        if "speed_priority_bonus_late" in row:
            assert row["speed_priority_bonus_late"] >= 0.3


def test_comfort_seed_overrides_can_lower_sp_reserve_for_race_safety():
    preset = {"learned_hyperparameters": {"calendar_race_prebuy_keep_sp": 250}}
    rows = _comfort_seed_overrides(preset)
    assert rows
    reserve_rows = [
        row for row in rows
        if "calendar_race_prebuy_keep_sp" in row
    ]
    assert reserve_rows
    for row in reserve_rows:
        assert 0 <= row["calendar_race_prebuy_keep_sp"] <= 250


# -------------------- _win_rate --------------------

def test_win_rate_aggregates_across_sims():
    """Win rate is total wins / total races across all sims in the batch."""
    r1 = _FakeResult(17600, races_run=[
        {"name": "Race A", "won": True},
        {"name": "Race B", "won": True},
    ])
    r2 = _FakeResult(15000, races_run=[
        {"name": "Race C", "won": True},
        {"name": "Race D", "won": False},
    ])
    assert _win_rate([r1, r2]) == 0.75  # 3/4


def test_win_rate_empty_is_zero():
    assert _win_rate([]) == 0.0
    assert _win_rate([_FakeResult(15000)]) == 0.0  # no races


# -------------------- _epithet_race_names + _epithet_losses --------------------

def test_epithet_race_names_contains_known_routes():
    """Spot-check well-known MANT epithet races appear in the set."""
    names = _epithet_race_names()
    # Lady route
    assert "Oka Sho" in names
    assert "Japanese Oaks" in names
    # Stunning route
    assert "Satsuki Sho" in names
    assert "Tokyo Yushun (Japanese Derby)" in names
    assert "Kikuka Sho" in names
    # Sprint Go-Getter route
    assert "Sprinters Stakes" in names


def test_epithet_losses_counts_only_epithet_race_losses():
    """A loss on a non-epithet race must NOT count. Only losses on
    races that gate a Lady/Stunning/etc bonus matter."""
    r = _FakeResult(15000, races_run=[
        {"name": "Random G2", "won": False},  # not epithet → 0
        {"name": "Oka Sho", "won": True},      # epithet but won → 0
        {"name": "Kikuka Sho", "won": False},  # epithet AND lost → 1
        {"name": "Sprinters Stakes", "won": False},  # epithet AND lost → 1
    ])
    assert _epithet_losses([r]) == 2


def test_epithet_losses_zero_when_no_epithet_races():
    """A career with no epithet races and no losses is clean."""
    r = _FakeResult(17600, races_run=[
        {"name": "Random G3", "won": True},
        {"name": "Random G2", "won": True},
    ])
    assert _epithet_losses([r]) == 0


# -------------------- _is_comfortable with new gates --------------------

def _good_results(n=5):
    """Build n SS-hitting results with full clean race records."""
    return [
        _FakeResult(17600, races_run=[
            {"name": "Oka Sho", "won": True},
            {"name": "Random G3", "won": True},
        ])
        for _ in range(n)
    ]


def test_comfortable_requires_high_win_rate():
    """A configuration hitting SS rate + mean but losing too many
    non-epithet races is NOT comfortable."""
    results = _good_results(5)
    # Add one bad race to each to drop win rate below 0.95
    for r in results:
        r.races_run.extend([{"name": "Random G2", "won": False}] * 5)
    # win rate: 10 wins / 35 races = 0.286 — way below 0.95
    assert _win_rate(results) < 0.95
    # But SS rate and mean are still satisfied
    assert _ss_rate(results) == 1.0
    assert _mean_rating(results) == 17600
    # → still NOT comfortable because win rate is too low
    assert _is_comfortable(results, target_ss_rate=0.80, target_mean=17500,
                            ss_threshold=17500, target_win_rate=0.95,
                            max_epithet_losses=0) is False


def test_comfortable_rejects_any_epithet_loss():
    """Even one epithet-bonus loss disqualifies — the bonus is irrecoverable."""
    results = _good_results(5)
    # Last sim drops Kikuka Sho (an epithet race for Stunning route)
    results[-1].races_run.append({"name": "Kikuka Sho", "won": False})
    # Win rate barely dipped but epithet loss is the killer
    assert _epithet_losses(results) == 1
    assert _is_comfortable(results, target_ss_rate=0.80, target_mean=17500,
                            ss_threshold=17500, target_win_rate=0.90,
                            max_epithet_losses=0) is False


def test_comfortable_passes_when_all_four_gates_met():
    """All four conditions satisfied → comfortable. Spec sanity."""
    results = _good_results(5)
    # SS rate 1.0, mean 17600, win rate 1.0, epithet losses 0 → all green
    assert _is_comfortable(results, target_ss_rate=0.80, target_mean=17500,
                            ss_threshold=17500, target_win_rate=0.95,
                            max_epithet_losses=0) is True


# -------------------- _strat_summary (per-seed strat readout) -------

def test_strat_summary_single_style_collapses_to_strat_equals_label():
    """If every race used the same strat, the calibrate per-seed line
    just shows 'strat=Pace' — no need for the distribution noise."""
    r = _FakeResult(17600, races_run=[
        {"name": "A", "won": True, "running_style_label": "Pace"},
        {"name": "B", "won": True, "running_style_label": "Pace"},
        {"name": "C", "won": True, "running_style_label": "Pace"},
    ])
    assert _strat_summary(r) == "strat=Pace"


def test_strat_summary_mixed_styles_shows_distribution_sorted():
    """If the bot used multiple strats across races, show the counts
    sorted by frequency: 'strats=[Late:6 Pace:2]'. Helps spot decks
    that flop between strats race-to-race."""
    r = _FakeResult(17600, races_run=[
        {"name": "A", "won": True, "running_style_label": "Late"},
        {"name": "B", "won": True, "running_style_label": "Late"},
        {"name": "C", "won": True, "running_style_label": "Pace"},
        {"name": "D", "won": False, "running_style_label": "Pace"},
        {"name": "E", "won": True, "running_style_label": "Late"},
    ])
    out = _strat_summary(r)
    # Late is most common (3 races) → must come first
    assert out.startswith("strats=[Late:3 ")
    assert "Pace:2" in out


def test_strat_summary_empty_when_no_strat_recorded():
    """If the sim didn't populate strat labels (older code path or
    older snapshot), summary returns '' instead of garbage."""
    r = _FakeResult(17600, races_run=[
        {"name": "A", "won": True},  # no running_style_label
        {"name": "B", "won": True, "running_style_label": ""},  # explicit empty
    ])
    assert _strat_summary(r) == ""
    # Also no races at all
    r2 = _FakeResult(0, races_run=[])
    assert _strat_summary(r2) == ""
