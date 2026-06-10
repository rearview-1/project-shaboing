# Audit #3 — Auto-tuner / Hyperparameter Learning

**Date:** 2026-06-10
**Scope:** Read-only audit of `career_bot/hyperparameter_tuner.py`. Examined the
TUNABLE_PARAMS table, the 11 proposal rules in `propose_tune_decisions`, the
summarization function that feeds them, and the apply path. Did not modify any code.

## Files / functions examined

- `career_bot/hyperparameter_tuner.py`
  - `TUNABLE_PARAMS` (line 87, 35 entries)
  - `_load_recent_careers` (line 269)
  - `_context_adapt_careers` (line 331)
  - `summarize_recent_outcomes` (line 420)
  - `_clamp` (line 501)
  - `_current_value` (line 505)
  - `_gap_multiplier` (line 514)
  - `_stuck_multiplier` (line 527)
  - `propose_tune_decisions` (line 538, 11 rules)
  - `apply_tune_decisions` (line 762)
  - `run_tuner` (line 796)

## Pipeline shape

```
run_tuner(bot_logs_dir, race_history_path, preset, log_path)
  ├─ _load_recent_careers(bot_logs_dir, n=20)         from bot_logs/*.json
  ├─ _context_adapt_careers(careers, preset)          filter to current deck/trainee context
  ├─ _load_race_history(race_history_path)             per-pid win rates
  ├─ summarize_recent_outcomes(careers, history)      → summary dict (stat medians, race losses, etc.)
  ├─ _read_tune_log_tail(log_path, n=8)                → tail of past tune decisions
  ├─ propose_tune_decisions(summary, learned, source_preset, log_tail)
  │     ├─ gap_mult = _gap_multiplier(summary)        1.0 - 4.0 based on stat_sum gap
  │     ├─ stuck_mult = _stuck_multiplier(log_tail)   1.0 or 2.0
  │     └─ 11 rules each call _propose(param, direction, reason)
  └─ apply_tune_decisions(preset, decisions, log_path, summary)
        └─ writes to preset["learned_hyperparameters"]
```

## Observations

### Obs 1 — Stamina/Power priority knobs have ceiling 0.08; speed/wit have ceiling 0.32-0.42

**Location:** TUNABLE_PARAMS lines 89-128

**What the code does:**
- `speed_priority_bonus_late`: ceiling 0.32, default 0.22
- `wit_priority_bonus_late`: ceiling 0.42, default 0.30
- `stamina_priority_bonus_base`: ceiling 0.08, default 0.03
- `stamina_priority_deficit_boost`: ceiling 0.08, default 0.03
- `power_priority_bonus_base`: ceiling 0.08, default 0.03
- `power_priority_deficit_boost`: ceiling 0.08, default 0.03

**Observation:** The auto-tuner cannot push stamina or power priority bonuses above
0.16 total (base + deficit). Wit late and speed late can reach 0.42 and 0.32. This
is a fixed architectural ratio of ~3-5x in favor of speed/wit. Same observation we
discussed during the (now-reverted) `power_priority_bonus_late` work — the architecture
itself caps stamina/power priority below speed/wit ceilings.

### Obs 2 — Operator policy floors exceed TUNABLE_PARAMS ceilings (silent clamp)

**Location:** TUNABLE_PARAMS lines 95, 98, 120, 121 vs calibrate's POLICY_FLOORS

**What the code does:**
- `stamina_floor_target` TUNABLE_PARAMS ceiling: **750**
- Calibrate's POLICY_FLOORS `stamina_floor_target.policy_default`: **1000**
- `power_floor_target` TUNABLE_PARAMS ceiling: **1000**
- Calibrate's POLICY_FLOORS `power_floor_target.policy_default`: **1100**
- `stamina_soft_cap` TUNABLE_PARAMS ceiling: **1100**
- Calibrate's POLICY_FLOORS `stamina_soft_cap.policy_default`: **1200**
- `guts_soft_cap` TUNABLE_PARAMS ceiling: **1100**
- Calibrate's POLICY_FLOORS `guts_soft_cap.policy_default`: **1200**

**Concern:** When calibrate's `_apply_policy_floor_corrections` writes 1200 to
`stamina_soft_cap` in learned_hyperparameters, the value persists in the preset
file. But when the sim's `_tuned_value(preset, "stamina_soft_cap", default)` looks
it up, `_bounded` (career_simulator.py line 56-63 area) clamps to the TUNABLE_PARAMS
ceiling of 1100. So the operator policy of 1200 is silently reduced to 1100 at every
read. The same applies to stamina_floor_target (1000 → 750) and power_floor_target
(1100 → 1000). The corrections appear in the report but don't fully take effect at
runtime.

### Obs 3 — 11 proposal rules favor speed; stamina has 1 rule, power has 0 direct rules

**Location:** `propose_tune_decisions` lines 573-689

**Rule list:**
- Rule 1 (line 573): proposes `speed_priority_bonus_late` up
- Rule 2 (line 580): proposes `speed_priority_bonus_mid` up
- Rule 3 (line 585): proposes `speed_priority_bonus_early` up
- Rule 4 (line 590): proposes `postmortem_bonus_cap` up (race-targeted)
- Rule 5 (line 598): proposes `race_specific_demand_cap` up
- (anonymous block line 605-622): proposes `calendar_race_prebuy_*` and `race_success_bonus_cap`
- Rule 6 (line 624): proposes `calendar_race_prebuy_*` (skill budget)
- Rule 7 (line 632): proposes `checkpoint_pressure_base` up (only stamina-mentioning rule)
- Rule 8 (line 638): proposes `race_success_bonus_cap` up
- Rule 9 (line 643): proposes `speed_priority_bonus_late` up + `race_specific_demand_cap` up
- Rule 10 (line 650): proposes `speed_soft_cap`, `power_soft_cap`, `wit_soft_cap` up
- Rule 11 (line 671): proposes `race_heavy_rest_threshold_penalty` and `low_hp_wit_training_max_failure`

**Observation:** No rule directly proposes `stamina_priority_bonus_base`,
`stamina_priority_deficit_boost`, `power_priority_bonus_base`, or
`power_priority_deficit_boost`. The auto-tuner cannot lift stamina or power priority
bonuses, only those knobs that already have rules. So even when stamina is observed
to lag, the tuner's response is `checkpoint_pressure_base` (Rule 7) — a different
lever.

### Obs 4 — `_propose` clamps NEW values but reads existing values without floor check

**Location:** `_propose` lines 553-571, `_current_value` lines 505-511

**What the code does:**
```python
old = _current_value(param, learned_hyperparameters, source_preset)
# ...
new = old + step if direction == "up" else old - step
new = _clamp(new, cfg["floor"], cfg["ceiling"])
```

**Observation:** If the existing learned value is OUTSIDE the floor/ceiling range
(e.g., a preset has `stamina_soft_cap = 1200` while TUNABLE_PARAMS ceiling is 1100),
`old` reads as 1200. A direction="up" proposal would compute `new = 1225`, then
clamp to 1100. So an out-of-range value gets SILENTLY pulled back into range on the
next tune cycle. A direction="down" proposal from 1200 with step 25 would compute
`new = 1175`, also clamped to 1100. So the first tune cycle after operator policy
sets stamina_soft_cap to 1200 will clamp it to 1100.

### Obs 5 — Stuck multiplier doubles step size after 4 non-improving cycles

**Location:** `_stuck_multiplier` lines 527-535

**What the code does:**
```python
recent_medians = [e.get("median_at_time") for e in log_tail if "median_at_time" in e]
if all(current_med <= m for m in recent_medians[-4:]):
    return 2.0
```

**Observation:** When the last 4 tune cycles all logged a median_at_time ≥ current
median, the step multiplier is 2.0x. Combined with `_gap_multiplier` (up to 4.0x),
the total step multiplier can reach 8.0x. Rule 9 also applies `step_multiplier=1.5`.
Combined max step on speed_priority_bonus_late (cfg step 0.01): 0.01 × 4.0 × 2.0 ×
1.5 = 0.12 per cycle.

**Concern:** Rapid escalation. With initial value 0.22 and ceiling 0.32, two STUCK
+ gap_mult > 1 cycles can move from default to ceiling.

### Obs 6 — `summarize_recent_outcomes` reads from `bot_logs/`, not sim outputs

**Location:** `_load_recent_careers` (called from `run_tuner` line 797),
`summarize_recent_outcomes` (line 420)

**What the code does:** Reads up to N=20 most-recent career_log_*.json files from
`bot_logs_dir`. These are LIVE bot careers, not sim careers.

**Observation:** The auto-tuner only learns from real-game outcomes, not sim
outcomes. If the operator's sim and live careers diverge (which we know they do
right now — the +400 work uncovered several gaps), the tuner is tuning against
reality not against the sim. Sim improvements don't propagate to learned_hyperparameters
via this path.

**Concern:** A sim-driven self-learning loop (the Module 1 work that was
reverted earlier today) would need a separate path or to feed sim careers into the
same `_load_recent_careers` input.

### Obs 7 — `_context_adapt_careers` filters careers by deck/trainee context

**Location:** line 331 (not read in full)

**Observation:** Not traced in this audit. Documented in the function signature. The
tuner adapts to context changes (deck swap, trainee swap). This is potentially the
most important behavior for the user's use case — ensuring stale learned values
from a different deck don't poison the current run. Worth a closer read in a follow-up.

### Obs 8 — `low_winrate_races` rule keyed on hard-coded program_id sets

**Location:** lines 480-482, 484-496

**What the code does:**
```python
junior_races = {623, 625}
classic_races = {163, 164, 166, 168, 81}
senior_races = {3, 4, 5, 76, 79, 80}
```

If a race shows wins/attempts ratio < 0.5 with attempts ≥ 5, it's added to
`low_winrate_races[era]`. Rule 4 then proposes `postmortem_bonus_cap` up if
classic/senior had low-rate races.

**Concern:** The hardcoded program_id sets cover 13 races. The bot's actual scheduled
race list (33 entries in the user's preset) extends beyond these. Races NOT in any
of the three sets are classified as `"mixed"` (line 495). Rule 4 fires on
`classic/senior` only — `mixed` races never trigger this rule.

### Obs 9 — `apply_tune_decisions` writes only to `preset["learned_hyperparameters"]`

**Location:** `apply_tune_decisions` lines 762-793

**What the code does:**
```python
learned = dict(preset.get("learned_hyperparameters") or {})
# ...for each decision:
learned[param] = new_value
preset["learned_hyperparameters"] = learned
```

**Observation:** No write to other preset top-level fields. Operator-owned keys
(skill_profile_style, expect_attribute, race_plan_text, custom_race_schedule, etc.)
are not in TUNABLE_PARAMS, so they cannot be modified by this path.

**Note:** The write is in-memory only (mutates the preset dict). Persistence to disk
happens elsewhere — caller of `run_tuner` would need to call `preset_store.write()`
or equivalent. This audit did not trace where `run_tuner` is invoked or whether the
post-tune preset gets persisted.

### Obs 10 — No rule mentions skill plan style/distance, recreation, items, events

**Location:** all of `propose_tune_decisions` lines 538-731

**Observation:** Rules touch: speed/wit/stamina priority bonuses, soft_caps, floor
targets, postmortem/race-specific demand caps, race_success_bonus_cap, checkpoint
pressure, calendar prebuy parameters, rest threshold, low-HP wit substitution
parameters, stat_friend_recreation parameters.

Not touched: `skill_profile_style`, `skill_profile_distance`, `learn_skill_list`,
recreation outing stat targeting, item usage thresholds, event choice
hyperparameters, anything related to Riko Kashimoto specifically.

### Obs 11 — `propose_tune_decisions` requires MIN_CAREERS_FOR_TUNE = 4

**Location:** line 540

**What the code does:** Early return if `n_careers < 4`.

**Observation:** Tuner only fires after 4+ finished careers. For the operator's use
case ("the bot should learn from sim"), this means a calibrate batch of fewer than
4 sims would never trigger tuning. Calibrate's typical batch is 4-10 sims, so this
is borderline relevant — but the tuner is wired to read from `bot_logs/` (Obs 6),
not sim outputs, so the question is moot for sim batches anyway.

## What I did NOT check

- `_context_adapt_careers` implementation (Obs 7)
- Where `run_tuner` is invoked (when does tuning actually happen — after every
  career? On demand? In a background loop?)
- Whether the post-tune preset gets persisted to disk
- The `_load_recent_careers` JSON parsing for edge cases
- Specific magnitudes of `gap_mult * stuck_mult * step_multiplier` for each rule
  combination
- The `_tuned_value` reader's `_bounded` clamping logic (referenced in Obs 2; lives
  in career_simulator.py, not the tuner module)
- The `tune_log.jsonl` log format details
- Whether the auto-tuner is run on a separate thread or blocks the main career loop

## Summary

11 observations. The two biggest:

- **Obs 2** — calibrate's policy floors exceed TUNABLE_PARAMS ceilings for
  `stamina_floor_target`, `power_floor_target`, `stamina_soft_cap`, `guts_soft_cap`.
  The operator's policy values get silently clamped down at read time. The calibrate
  reports show the corrections applied; the sim runs with the clamped values.
- **Obs 3 + Obs 1** — the tuner has no rule that lifts stamina or power priority
  bonuses, AND the architectural ceilings on those knobs are 5x lower than speed/wit.
  Power has zero direct rules. The tuner cannot organically push power priority even
  if power is the bottleneck.

**Obs 6** — the tuner reads from live bot_logs, not sim outputs. Wiring sim
self-learning into this path would require a deliberate change.

No code changes made by this audit.
