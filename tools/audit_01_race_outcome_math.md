# Audit #1 — Race Outcome Math

**Date:** 2026-06-10
**Scope:** Read-only audit of every code path in `career_bot/career_simulator.py` that
computes a race's win probability or outcome. Did not modify any code.

## Files / functions examined

All in `career_bot/career_simulator.py`:

- `RACE_WEIGHT_PROFILES` (constant, line 313)
- `_current_race_stats()` (line 5259) — displayed stats
- `_effective_race_stats()` (line 5274) — displayed + 400
- `_current_aptitudes()` (line 5298)
- `_race_style()` (line 5891)
- `_race_effort_score()` (line 5894) — core scoring function
- `_sample_race_score()` (line 5954) — opponent sample scoring
- `_candidate_race_result_samples()` (line 5989)
- `_estimate_race_from_results()` (line 6008)
- `_field_sample_threshold()` (line 6077)
- `_estimate_race_from_fields()` (line 6097)
- `_empirical_race_outcome()` (line 6133)
- `_race_probability_estimate()` (line 6162)
- `_observed_race_probability()` (line 6218)
- `_blend_observed_race_probability()` (line 6230)
- `_load_race_thresholds_json_targets()` (line 6280)
- `_manual_threshold_probability_estimate()` (line 6304)
- `_simulate_race()` (line 6446)

## Map of call relationships

```
_simulate_race                                 (entry)
  └─ _race_probability_estimate                (line 6451)
       ├─ _empirical_race_outcome              (line 6163)
       │    ├─ _estimate_race_from_results     (line 6148)
       │    │    ├─ _race_effort_score(_effective_race_stats(), ...)   (line 6014)
       │    │    └─ _sample_race_score(...) — adds +400 to sample raw  (line 5967)
       │    └─ _estimate_race_from_fields      (line 6160)
       │         ├─ _race_effort_score(_effective_race_stats(), ...)   (line 6103)
       │         └─ _field_sample_threshold(...)
       │              └─ _race_effort_score(opponent.stats, ...) — NO +400  (line 6081)
       ├─ _manual_threshold_probability_estimate                       (line 6171)
       │    └─ uses _effective_race_stats() at line 6338
       └─ _blend_observed_race_probability                             (line 6207-2)
            └─ _observed_race_probability — pulls real win-rate per pid
```

## Observations

### Obs 1 — Double-counted +400 in `_manual_threshold_probability_estimate` (introduced 2026-06-10)

**Location:** career_simulator.py lines 6338 and 6400

**What the code does:**

- Line 6338: `current = self._effective_race_stats()` — `current["stamina"]` is now `displayed + 400` because `_effective_race_stats()` already adds the bonus.
- Line 6400: `effective_current_stamina = current["stamina"] + CAREER_INVISIBLE_STAT_BONUS` — adds another +400 on top.

Net: `effective_current_stamina = displayed + 800`. Used in line 6401's `true_stamina_ratio` for the hard-stamina-floor penalty check.

**Origin:** Pre 2026-06-10 the function read `current = self._current_race_stats()` (displayed only) and the +400 at line 6400 was the single correct application. This session's `_current_race_stats` → `_effective_race_stats` swap at line 6338 (to fix the previously-missing +400 in the coverage math) did not strip the now-redundant +400 at line 6400.

**Effect:** The hard-stamina-floor penalty (`if true_stamina_ratio < stamina_floor_ratio: prob *= max(0.005, 1.0 - shortfall * 7.0)`) now uses a stamina ratio inflated by 400. A bot at displayed stamina 750 racing a 600-stamina-threshold long race had `true_stamina_ratio = 1150/1000 = 1.15` previously; now has `1550/1000 = 1.55`. The "critically under-stamina" branch (line 6418) is less likely to trigger.

### Obs 2 — Asymmetric +400 in `_manual_threshold_probability_estimate` ratio math

**Location:** career_simulator.py lines 6338, 6342

**What the code does:**

- Bot stats: `current = self._effective_race_stats()` — displayed + 400 per stat
- Threshold values: come from `_load_race_thresholds_json_targets()` (line 6321-6322) or `self.race_thresholds` (line 6324) or `_fallback_race_threshold()` (line 6326). The docstring at line 6284 states the `target_raw` map is stored "raw + 400 invisible bonus stripped" — i.e., raw values, no +400.
- Line 6342: `ratio(stat) = current[stat] / max(1, int(threshold.get(stat) or 1))` — so ratios divide (displayed + 400) by raw threshold.

**Effect:** Each stat ratio is shifted upward by `400 / raw_threshold` relative to pre-2026-06-10 behavior. For a 700 raw threshold this is ~+0.57 to the ratio. The downstream coverage formula `prob = 0.10 + (coverage - 0.78) * 1.25 + skill_bonus` (line 6379) is linear in coverage so the manual probability rises.

Note: contrasts with `_race_effort_score` (`_estimate_race_from_results` and `_estimate_race_from_fields`) where my fix applies +400 to BOTH bot and sample sides (via `_sample_race_score`), keeping the comparison scale consistent. Only the threshold model is asymmetric.

### Obs 3 — Asymmetric +400 in `_estimate_race_from_fields` opponent scoring

**Location:** career_simulator.py lines 6103 (bot side) and 6081 (opponent side)

**What the code does:**

- Bot score at line 6103 uses `_effective_race_stats()` → +400 applied
- Opponent score at line 6081 inside `_field_sample_threshold`: `self._race_effort_score(opponent.get("stats") or {}, ...)` — opponent stats are passed as-is from the sample's `opponents[*].stats` field. **No +400 added to opponents.**

**Effect:** When `_estimate_race_from_results` returns None (samples not available) and the bot falls back to `_estimate_race_from_fields`, the bot scores at effective stats and opponents score at displayed stats. Bot's `current_score / threshold` ratio is shifted up relative to pre-2026-06-10 behavior.

Note: `_sample_race_score` (line 5967) was explicitly patched for symmetry; this opponent path was not.

### Obs 4 — Mood multiplier applied symmetrically in `_race_effort_score`

**Location:** career_simulator.py line 5939: `mood_mult = {5: 1.04, 4: 1.02, 3: 1.00, 2: 0.97, 1: 0.93}.get(int(motivation or 3), 1.0); score *= mood_mult`

**What the code does:** The mood multiplier reads from the `motivation` argument passed to `_race_effort_score`. Bot side passes `self.state.get("motivation") or 3`; sample side passes `sample.get("motivation") or 3`; opponent side (in `_field_sample_threshold`) passes `opponent.get("motivation") or 3`.

**Concern:** No verification that opponents in the sampled fields actually have a `motivation` field, or what value is used when absent. Falls back to 3 (neutral). If real-game opponents always race at non-neutral motivation, this could shift opponent threshold up/down systematically. Not investigated further — would need to look at the shape of `race_fields_by_pid` data.

### Obs 5 — `RACE_WEIGHT_PROFILES` stat weights are claimed but stamina is heavy on long

**Location:** career_simulator.py lines 313-319

**What the code does:** Per-distance stat weighting:

- sprint: speed 1.25, power 1.00, wit 0.55, stamina 0.42, guts 0.35
- mile: speed 1.15, power 0.92, wit 0.62, stamina 0.62, guts 0.38
- medium: speed 1.05, stamina 0.90, power 0.86, wit 0.55, guts 0.45
- long: stamina 1.25, speed 0.95, power 0.76, guts 0.58, wit 0.48
- default "": speed 1.00, stamina 0.80, power 0.80, wit 0.50, guts 0.40

**Observation:** Stamina is weight 1.25 on long (highest of any stat anywhere) but only 0.42 on sprint. Power peaks at 1.00 on sprint. Speed peaks at 1.25 on sprint. These weights drive `_race_effort_score` directly — the score is `sum(stat * weight)`.

**Concern:** These weights are constants in source. No comment explaining their derivation. They are NOT the same as the per-distance coverage weights in `_manual_threshold_probability_estimate` (lines 6361, 6367, 6371, 6377). Two different stat-weighting schemes are used at different scoring sites in the same race outcome pipeline.

### Obs 6 — Skill-count capping uses bot's total `self.skills_bought`

**Location:** career_simulator.py line 5916: `score += min(420.0, max(0, int(skill_count or 0)) * 18.0)`

**What the code does:** Each skill contributes 18 points to race-effort-score, capped at 420 total (about 23 skills). Called consistently for bot (passes `self.skills_bought`) and for samples (passes `sample.get("skill_count") or 0`) and for opponents (passes `opponent.get("skill_count") or 0`).

**Concern:** All skills are weighted equally — no distinction between race-relevant skills bought for this distance/style and irrelevant skills. A bot that hoards 20 sprint skills before running a long race gets the same +360 score contribution as one that bought 20 long-distance skills. This is acknowledged in the docstring at line 5913 ("Skills are not full race simulation here") but worth noting because the user has explicit skill plans by style/distance.

### Obs 7 — `_blend_observed_race_probability` minimum floors when observed real-game wins are common

**Location:** career_simulator.py lines 6255-6262

**What the code does:**

```python
if runs >= 5 and raw_win_rate >= 0.999:
    blended_prob = max(blended_prob, 0.935)
elif runs >= 6 and raw_win_rate >= 0.90:
    blended_prob = max(blended_prob, 0.90)
elif runs >= 6 and raw_win_rate >= 0.80:
    blended_prob = max(blended_prob, 0.84)
elif runs >= 6 and obs_prob >= 0.78:
    blended_prob = max(blended_prob, obs_prob)
```

**Observation:** When a real career has won a specific race 5+ times at ≥99.9% rate, the sim's blended win prob is floored at 0.935. This means the empirical observation **overrides** stat-based predictions when sufficient run history exists.

**Concern:** The reverse case (line 6265-6266, "raw_win_rate <= 0.45 → cap at obs_prob + 0.08") similarly floors low. The observed data comes from `_observed_race_probability` (`race_outcome_calibration.by_pid`). If that calibration cache was built when the bot was running a different strategy (e.g., before the user switched to Late surger), the observed win rates encode the OLD strategy's results. The blending will pull current-strategy predictions toward OLD-strategy historical outcomes.

### Obs 8 — Race outcome decision at line 6064 uses a single RNG roll

**Location:** career_simulator.py line 6064: `won = (self.rng.random() <= win_probability) if sample else None`

**What the code does:** Single uniform random number compared to win_probability. No additional sources of variance.

**Observation:** Race outcomes are stochastic only through this roll. Given identical stats, identical opponents, identical RNG seed, the outcome is fully determined. The full sim's RNG seed is set at sim init and the only race-related rolls are these uniform comparisons.

**Concern:** No issue noted — flagged for visibility because the per-race outcome variance is exactly the win_probability roll. If win_probability is miscalibrated, every roll is miscalibrated.

### Obs 9 — `_race_effort_score` style-hint check matches against parent skills only

**Location:** career_simulator.py lines 5929-5937

**What the code does:**

```python
if style:
    style_text = str(style or "").lower()
    style_hint_hits = 0
    for parent in getattr(self, "selected_parents", []) or []:
        for skill in parent.get("skills") or []:
            name = str(skill.get("name") or "").lower()
            if style_text in name or (style_text == "front" and "front runner" in name) ...
    score += min(80.0, style_hint_hits * 10.0)
```

**Observation:** Style-matched parent skill hints add up to 80 points to race effort score. Only PARENT skills count — the bot's own purchased skills are not separately style-checked here (they all count via the line 5916 skill_count formula).

**Concern:** The match logic checks if `style_text` (e.g., `"late"`) is in the skill name. Skills with names containing "late" that aren't actually Late-surger skills (hypothetically, "Latest News" or similar) would match. Did not enumerate the skill name space to check for false positives.

### Obs 10 — `_estimate_race_from_results` uses k-nearest sample matching but k floor is 35

**Location:** career_simulator.py line 6029: `k = min(max(35, len(scored) // 5), 120, len(scored))`

**What the code does:** Finds the `k` samples whose effort scores are closest to the bot's. `k` is `max(35, len(samples)//5)`, capped at 120.

**Observation:** Even when only 35 samples exist, all of them are used. The "nearest" filter is a no-op for small sample sets. Only above 35 samples does k-nearest do meaningful selection.

**Concern:** If `_candidate_race_result_samples` returns the minimum threshold (30-60 depending on tier), the win-probability estimate `(near_wins + base_rate * 8.0) / (len(nearest) + 8.0)` is effectively `(total_wins + base_rate * 8.0) / (n + 8.0)` — the bot's score isn't actually informing the prediction. Worth being aware of which races fall in this regime; not investigated per-race.

## What I did NOT check

- The data shape and population of `race_fields_by_pid` and `race_samples_by_pid` — only how they're consumed
- Whether `race_thresholds.json` actually contains the field-max values the docstring at line 6284 describes
- Whether opponent samples have `motivation` populated and what defaults flow through
- Whether `selected_parents` skills lists are populated and well-formed
- Whether `_load_race_thresholds_json_targets` correctly reads the postmortem pipeline output
- The `_observed_race_probability` calibration source (`race_outcome_calibration`) — its freshness, sample biases
- Any callers OUTSIDE `_simulate_race` that might compute race outcomes via a different path
- The bot's race-style override logic (separate audit; "training execution" #2 covers parts of it)
- The threshold from `race_thresholds.json` being raw vs effective for non-stamina stats (only stamina was explicitly examined in the double-count obs)

## Summary

3 observations describe behavior that diverges from pre-session symmetry around the +400 bonus. Obs 1 is a clear double-count introduced by this session's `_current_race_stats → _effective_race_stats` swap. Obs 2 and Obs 3 describe asymmetric +400 applications that did not exist before this session — bot side has +400, threshold/opponent sides do not.

Obs 4-10 are properties of the existing code (not changed this session) that may or may not be intentional. They're flagged for operator review.

No code changes were made by this audit.
