# Sim Calibration Notes

Captures the calibration journey: what was wrong, what was fixed, and
what the validated outcomes were. Pin this when reviewing future
calibration drifts.

## Symptom (start of session 2026-06-06 part 2)

User reported the sim "may not be tracking epithets correctly" and
"was getting lower results due to bad soft caps being 900." After
investigation:

- Real career distribution (140 careers): **9 SS / 55 S+ / 60 S / 15 A+ / 1 UG**
- Sim with production preset baseline: **mean 14,468, max 15,932, 0 SS hits**
- The optimizer's hyperparameter perturbations couldn't reach SS regardless of
  configuration — the sim mechanics themselves were the ceiling.

## Root cause

`REAL_TRAINING_GAIN_SCALE_DEFAULT` was **1.28**, calibrated against the
old bot when real careers landed around A/A+ (~14,100 mean rating).
The bot improved substantially since (real mean now ~16,500, S+/S
centroid). The sim was producing OLD-bot outcomes regardless of
hyperparameter perturbation.

The comment on the constant even said "Adding another deck-quality
multiplier makes the sim predict SS/UG careers while real runs are
landing around A/A+" — explicitly tying the constant to the old bot's
performance.

## Fix

| Constant | Before | After | Why |
|----------|--------|-------|-----|
| `REAL_TRAINING_GAIN_SCALE_DEFAULT` | 1.28 | **1.85** | Match real S+ centroid |
| `REAL_TRAINING_GAIN_SCALE_MAX_DECK_BONUS` | 0.0 | **0.10** | Re-enable small deck-quality bonus |
| `REAL_TRAINING_GAIN_SCALE_DECK_QUALITY_STEP` | 0.16 | **0.08** | Halved per-tier step to keep total within cap |

Selection of 1.85 was empirical — a 10-sim sweep:
- 1.65 → mean 15,464, 0% SS, 10% S+, 80% S
- **1.85 → mean 16,347, 0% SS, 70% S+, 30% S**  ← matches real S+ centroid
- 2.00 → mean 16,391, 10% SS, 60% S+, 30% S

## Validation

10-sim batch with the new defaults on the user's production preset:
- **Mean rating 16,600** (vs 14,468 baseline; +2,132)
- **10/10 hit S+** (real has 39% S+, sim variance is currently low)
- Max 17,211 (just 289 short of SS = 17,500)
- All Speed=1200 in 7/10 seeds

## Also fixed this session

1. **Power lane-balance target** (`mant.py:4716`) — was 900 when deck has
   no Power cards, raised to 1050 matching the with-power-card case.
2. **Missing epithets** — added Phenomenal (Stunning + 2 of 5 majors,
   +15) and Sprint Speedster (4 of 5 sprint/mile races, +15) with a
   `min_match` mechanism on the epithet schema. Total now 10 of 9
   documented epithets (2 Incredible variants).
3. **`_per_stat_soft_cap` floor for wit** — discovered the auto-tuner's
   wit_soft_cap floor of 1100 silently clamps the user's preset value of
   900 up to 1100. Not a bug per se; explains why the preset value
   "didn't seem to matter" in earlier A/B tests.

## Tests added

- `tests/test_real_training_gain_scale.py` — pins 1.85 default, deck-bonus enabled, modest step.
- `tests/test_deck_policy_cache.py` (earlier in session, 11 tests) — pins the cache module API.

## Limitations remaining

- **No SS hits in sim** despite consistently hitting S+ (mean 16,600).
  Real bot achieves SS in 6.4% of careers — sim's variance is currently
  too low to produce that tail. This is a sim accuracy gap, not a bot
  ceiling. Probably needs higher event variance or a slight scale lift.
- **Sim baseline variance is artificially compressed** — all 10 sims hit
  S+, none fall to S/A+. Real distribution has 53% S-or-lower. Suggests
  the sim's RNG bands inside training/event apply are too narrow.

## Workflow going forward

1. After each batch of N real careers, rebuild empirical calibrations:
   ```
   python tools/build_event_probability_model.py
   ```
2. If the real bot continues to improve, lift the training scale further
   (and update `test_real_training_gain_scale.py`).
3. For new decks, run the optimizer to find their tuned policy:
   ```
   python tools/optimize_deck_policy.py --candidates 12 --sims-per-candidate 5
   ```
