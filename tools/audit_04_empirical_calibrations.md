# Audit #4 — Empirical Calibrations

**Date:** 2026-06-10
**Scope:** Read-only audit of the `load_empirical_*` functions in
`career_bot/career_simulator.py`. These build per-deck/per-trainee calibrations from
the operator's accumulated career_logs and parent_memory, then feed the sim's race
outcome, race-stat-gain, SP-budget, and skill-rating models. Did not modify any code.

## Files / functions examined

All in `career_bot/career_simulator.py`:

- `_SIM_CALIBRATION_CACHE` — module-level dict, in-process cache
- `_calibration_context_key()` (line 884)
- `_skill_calibration_sample_weight()` (line 896)
- `load_empirical_skill_rating_calibration()` (line 915)
- `load_empirical_sp_budget_calibration()` (line 1024)
- `load_empirical_race_stat_gain_calibration()` (line 1120)
- `load_empirical_race_outcome_calibration()` (line 1312)
- `_runtime_roots()` (helper, not read in full)

## Data sources

Each calibration reads from `uma_runtime/instances/*/...`:

| Calibration | Reads from |
|---|---|
| skill_rating | `*/parent_memory/parent_library.json` |
| sp_budget | `*/bot_logs/career_log_*.json` (finished only) |
| race_stat_gain | `*/bot_logs/career_log_*.json` (turn events) |
| race_outcome | `*/bot_logs/career_log_*.json` (race_result events) |

All read live-game data, not sim outputs.

## Observations

### Obs 1 — All calibrations are process-cached forever, keyed by run_context

**Location:** `_SIM_CALIBRATION_CACHE` (module-level), `_calibration_context_key`
(line 884), used at lines 925-927, 1033-1035, 1130-1132, 1322-1324

**What the code does:** Each `load_empirical_*` function checks
`_SIM_CALIBRATION_CACHE[cache_key]` before doing any I/O. The cache key is
`(project_root, instance_name, trainee_card_id, deck_id, friend_card_id,
support_card_ids_tuple)`. Once cached, the result is returned via `copy.deepcopy`
on every subsequent call.

**Concern:** The cache has no TTL or invalidation hook. Within one Python process,
even if new career_logs are written to disk (e.g., a live career finishes during a
long-running calibrate or runner), the existing process keeps using the cached
pre-update snapshot. For the typical calibrate run (process lifetime ~5 minutes,
no new careers expected), this is fine. For a long-running runner that hosts
multiple back-to-back live careers, the calibration snapshot from process startup
is used for every subsequent career until process restart.

### Obs 2 — `_skill_calibration_sample_weight` strongly favors same-trainee, same-deck samples

**Location:** lines 896-912

**What the code does:** Per-sample weight starts at 0.35 and accumulates:
- +2.0 if `made_by_bot`
- +4.0 if same `trainee_card_id`
- +1.25 if same `friend_card_id`
- +(overlap × 4.0) for deck overlap (overlap is 0.0-1.0 from `_deck_overlap_score`)
- ×1.8 multiplier applied at line 959 if `made_by_bot` (compounds with the +2.0 above)

Maximum weight (made_by_bot + same trainee + same friend + full deck overlap):
`(0.35 + 2.0 + 4.0 + 1.25 + 4.0) × 1.8 = 21.78`. Minimum weight (anonymous,
no context match): `0.35`. Ratio: ~62×.

**Concern:** A small handful of exact-context samples can dominate the weighted
percentile calculations over a much larger pool of weaker matches. With few exact
matches in the user's parent_memory (the user told me the deck has been refined
recently — likely few prior careers with the exact same deck), the model's
percentiles may be driven by 2-3 samples. The `_weighted_percentile` function is
not examined here, but high weight concentration is a known statistical risk.

### Obs 3 — `load_empirical_skill_rating_calibration` switches to non-bot samples when bot sample count < 8

**Location:** lines 980-981

**What the code does:**
```python
bot_samples = [row for row in samples if row["made_by_bot"]]
model_samples = bot_samples if len(bot_samples) >= 8 else samples
```

**Observation:** When fewer than 8 bot-made parent samples exist, the model falls
back to ALL samples including non-bot (human-made) parents. The implicit assumption
is that non-bot samples are still informative.

**Concern:** Non-bot samples have different optimization goals than the bot's
(human players may optimize for a specific spark target, not pure rating). When the
bot has < 8 careers of history, the skill-rating model is calibrated against
human play patterns, not bot patterns. The minimum total sample count for the
model to be `enabled: True` is 5 (line 982).

### Obs 4 — `load_empirical_sp_budget_calibration` skips careers with zero estimated skill spend

**Location:** lines 1067-1068

**What the code does:**
```python
if skill_spend <= 0:
    continue
```

**Observation:** Careers where no purchased skill could be cost-estimated (e.g.,
unknown skill IDs in `_estimated_sim_skill_point_cost`, or the bot bought no
skills) are excluded entirely from the SP budget sample pool.

**Concern:** If the operator's recent careers used skill IDs not in the sim's
cost map, those careers don't contribute to budget calibration. The budget then
calibrates against an older subset of careers.

### Obs 5 — `load_empirical_race_outcome_calibration` requires same-trainee match minimum

**Location:** lines 1354-1358

**What the code does:**
```python
usable_context = exact_match or (
    target_trainee and _as_int(sample_context.get("trainee_card_id")) == target_trainee
)
if not usable_context:
    continue
```

**Observation:** A career_log is used only if it matches the current
`trainee_card_id`, OR exactly matches trainee + deck + friend. Cross-trainee data
is excluded.

**Concern:** If the operator has been using the same trainee but with different
deck compositions over time (deck refinement), the per-pid win-rate samples
aggregate across all those deck compositions. A race that the bot won frequently
with an older deck contributes positively to the win rate even when the current
deck struggles with that race.

### Obs 6 — `EXACT_CONTEXT_MIN_RACE_SAMPLES` gates exact-match preference

**Location:** line 1382, constant defined at module level (line 74)

**What the code does:**
```python
EXACT_CONTEXT_MIN_RACE_SAMPLES = 250  # at line 74
# ...
use_exact = sum(row["runs"] for row in exact_by_pid.values()) >= EXACT_CONTEXT_MIN_RACE_SAMPLES
```

**Observation:** Race-outcome calibration uses the exact-context (same deck) sample
set ONLY if the total observed race runs across all program_ids in that exact set
sum to ≥ 250. Otherwise it uses the broader same-trainee set.

**Concern:** 250 race runs at typical ~25-30 races per career means the operator
needs roughly 8-10 finished careers with the *exact same deck* before the
exact-context calibration kicks in. For a freshly-tuned deck (which the operator's
seems to be), this threshold has likely not been met, and the broader
same-trainee aggregate is used.

### Obs 7 — Bayesian smoothing `(wins + 1.5) / (runs + 3.0)` at line 1400

**Location:** `load_empirical_race_outcome_calibration` line 1400

**What the code does:**
```python
smoothed = (wins + 1.5) / (runs + 3.0)
```

**Observation:** This is a Beta(1.5, 1.5) prior — a mildly-informative prior that
pulls win rates toward 0.5 when run count is low. At runs=1, wins=1, smoothed=
2.5/4.0 = 0.625. At runs=10, wins=10, smoothed = 11.5/13.0 = 0.885. At runs=100,
wins=100, smoothed = 0.985.

**Concern:** A race the bot has won 1/1 has `smoothed_win_rate = 0.625`, but
`win_rate = 1.0`. The `_blend_observed_race_probability` function (Audit #1, Obs 7)
uses `smoothed_win_rate` for blending and `win_rate` for the floor checks at lines
6255-6262. The 99.9%+ floor at line 6255 uses `raw_win_rate` not smoothed, so this
smoothing doesn't affect that floor. The floors at lines 6257-6261 also use
`raw_win_rate`.

### Obs 8 — Race stat gain calibration loads but was not read in detail in this audit

**Location:** `load_empirical_race_stat_gain_calibration` line 1120 (read first 24 lines only)

**Observation:** The function exists and follows the same cache + multi-instance read
pattern as the others. Beyond that, this audit did not trace which fields it
extracts from career logs, how it aggregates them, or what shape it returns.

### Obs 9 — All `load_empirical_*` walk every instance directory under the project root

**Location:** lines 936, 1043, 1138 (inferred), 1337

**What the code does:**
```python
for runtime_root in _runtime_roots(root):
    instance_root = runtime_root / "instances"
    if not instance_root.exists():
        continue
    for path in instance_root.glob("*/bot_logs/career_log_*.json"):
        ...
```

**Observation:** The glob walks all `instances/*/` directories. If the operator has
multiple accounts (`account_a`, `account_b`, etc.) under the same project root,
career logs from ALL accounts contribute to the calibration pool.

**Concern:** If the operator has historical career_logs from a different
optimization regime or different account, those contribute to the current deck's
calibrations.

### Obs 10 — `made_by_bot` flag is the only quality marker

**Location:** line 956

**What the code does:**
```python
made_by_bot = bool(parent.get("made_by_bot") or str(parent.get("source_kind") or "").lower() == "bot")
```

**Observation:** Bot-made vs human-made is the only distinction. There's no
distinction within bot-made samples for "good run" vs "bad run", "current
strategy" vs "old strategy", etc.

**Concern:** A bot-made parent from a poorly-tuned earlier version of the bot
contributes the same `made_by_bot=True` weight as a recent well-tuned one. If
the operator has years of bot-made parents, old ones may dominate the
percentile calculations.

### Obs 11 — Calibration cache key does not include the bot version or strategy

**Location:** `_calibration_context_key` lines 884-893

**What the code does:**
```python
return (
    _path_key(project_root or Path(__file__).resolve().parents[1]),
    _preferred_runtime_instance({"_run_context": ctx}),
    _as_int(trainee_card_id),
    _as_int(ctx.get("deck_id")),
    _as_int(ctx.get("friend_card_id")),
    tuple(_as_int(value) for value in (ctx.get("support_card_ids") or []) if _as_int(value)),
)
```

**Observation:** Cache key fields: project root, instance, trainee, deck_id,
friend_card_id, support_card_ids. NOT in the key: strategy
(skill_profile_style), preset values, bot version, time.

**Concern:** If the operator changes `skill_profile_style` (e.g., from Front to
Late) without restarting the process, the cached calibration from the Front-strategy
data is still used. Process restart clears the cache.

## What I did NOT check

- `_runtime_roots()` and `_preferred_runtime_instance()` implementations
- `_load_bot_parent_registry_contexts()`
- `_parent_skill_rating_residual()`, `_skill_count()`, `_parent_final_stats()`
- `_weighted_percentile()` — heavily relied on by all calibrations
- `_deck_overlap_score()`
- `_estimated_sim_skill_point_cost()` — drives Obs 4
- `load_empirical_race_stat_gain_calibration` body beyond signature
- Whether the calibrations are loaded eagerly at sim init or lazily on first reference
- Sample dataset sizes for the operator's current setup (would require running the
  loaders against your data and inspecting results)

## Summary

11 observations. The most relevant for "is the calibration biased toward old data":

- **Obs 1** — calibration cache has no TTL or invalidation
- **Obs 5** — cross-deck career_logs contribute to per-pid win rates if same trainee
- **Obs 6** — exact-deck calibration only kicks in at 250 race-runs (~8-10 careers)
- **Obs 10** — no time-decay or strategy-version awareness on samples

Together these mean: if the operator's recent strategy is materially different from
the strategy used in most of their historical career_logs, those historical careers
are still driving the calibration. The "samples" the sim uses to model race outcomes
are a long-running pool, not a recent window.

**Obs 11** — strategy isn't in the cache key, so process restart is required to pick
up strategy changes in the calibration.

No code changes made by this audit.
