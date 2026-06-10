# Per-decision learning (the big one)

**Status**: Implemented in `career_bot/decision_quality.py` and
`career_bot/learning.py`. 2026-05-22 update: action weighting now uses a
non-multiplicative composition so high-quality decisions in mediocre careers
still carry learning signal.

## Goal

Move the auto-tuner from "score each career as one data point and pool
them" to "score each in-career decision as a data point." A 78-turn
career has ~50 training decisions plus race/skill/item decisions — easily
100+ decision points. Treating each as its own observation grows the
effective sample size by ~100× without running new careers.

This is the biggest single ML improvement available. It's also the
largest scope of change — touches `tune_extra_weight`, `tune_base_score`,
`tune_score_value`, `tune_optional_race_policy`, and possibly
`tune_rest_threshold` / `tune_learn_skill_threshold`.

## What "per-decision learning" actually means here

The current tuner flow:

```
for each tune_* function:
    aggregate stats across all actions in top_samples
    aggregate stats across all actions in bottom_samples
    compute top_avg - bottom_avg → nudge preset value
```

The proposed flow:

```
for each action across ALL samples (not just top vs bottom):
    score that action's local quality (per-decision quality)
    accumulate (action.features, decision_quality) pairs
for each tune_* function:
    fit preset values to maximize predicted-decision-quality
```

The key change is **how an action gets labeled**. Right now, an action's
label is "did the career it belonged to score highly?" — coarse, indirect,
mostly tells you about the career not the action. We want:

> "Did this particular action have above-median efficiency relative to
> alternatives the bot considered on that same turn?"

## Per-decision quality scoring

Three candidate signals, listed in order of confidence:

### Signal A — Local stat-gain efficiency

For training actions:
```python
quality = (
    weighted_gain                     # raw stat gain weighted by stat value
    + rainbow_count * 0.10            # rainbow tile bonus
    + hint_count * 0.05               # hint tile bonus
    - failure_rate / 50               # failure penalty
    - max(0, energy_delta * -0.01)    # energy cost penalty (negative deltas)
)
```

Pure numeric, no comparison needed. Good baseline. Already partially
encoded in `_action_features.weighted_gain`.

### Signal B — Relative-to-alternatives quality

Per turn, what other tiles were available? Each `training_snapshot.trainings`
row carries the bot's score for every available tile. So we know:
- The chosen action's score
- The score of every alternative

Quality = `chosen_score - second_best_score`. Positive = bot picked well
relative to alternatives; negative = there was a clearly better option.

This is more informative than Signal A but requires the `training_snapshot`
to be in the career log (which it IS — manual recorder logs it, but bot
logs may need to be updated to log it too).

### Signal C — Retrospective N-turn delta

For training actions, look N turns forward (say N=4) and compute stat
gain in that window. If a Speed train at turn 20 produced 4 turns of
above-median Speed gain (compounding via rainbows / motivation), that's
a high-quality decision.

Hardest to implement; most informative when it works.

**Recommendation:** Start with Signal A + Signal B combined. Signal C is
a follow-up.

## Where to change in the codebase

### Step 1 — Add per-decision quality scorer

New module: `career_bot/decision_quality.py`

```python
def score_action(action, snapshot=None):
    """Combined Signal A + Signal B quality score for one action."""
    quality_a = signal_a_local_efficiency(action)
    quality_b = signal_b_relative_to_alternatives(action, snapshot) if snapshot else 0.0
    return 0.6 * quality_a + 0.4 * quality_b


def annotate_career_with_decision_quality(career_log):
    """Walk a career_log's actions and inject a `decision_quality` field
    on each. Idempotent — safe to re-run."""
    for action in career_log.get("actions") or []:
        action["decision_quality"] = score_action(action, action.get("training_snapshot"))
    return career_log
```

Call this from `collect_samples` so every loaded sample's actions get
quality-labeled before they reach the tuners.

### Step 2 — Replace `action_distribution` with `weighted_action_distribution`

Current `action_distribution(samples)` counts how often each
(period, training_idx) appears in top/bottom, treating every action with
equal weight. New version: weight each action by its `decision_quality`.

```python
def weighted_action_distribution(samples):
    # Same shape as action_distribution but cells accumulate
    # sum(action.decision_quality) instead of sum(1) for the action's count.
    ...
```

Then the tune_* functions consume this enriched distribution — the
"top rate" for a (period, idx) cell becomes "fraction of total quality"
rather than "fraction of total count."

### Step 3 — Update the tune_* functions

For `tune_extra_weight`:
- Today: `delta = (top_rates[idx] - bottom_rates[idx]) * 0.55`
- Per-decision: `delta = (quality_rates[idx] - 0.20) * 0.55 * lr_scale`
  where `quality_rates[idx]` is the share of total decision quality
  attributed to action idx in this period, and `0.20` is the "neutral
  baseline" (uniform across 5 training types).

Same pattern for `tune_base_score`, `tune_score_value`.

### Step 4 — Backwards compatibility

Two ways the system needs to handle old data:
1. Career logs without `training_snapshot` per action → Signal B
   contributes 0; we fall back to Signal A only.
2. Career logs without per-action `decision_quality` annotations →
   `annotate_career_with_decision_quality` adds them at load time. Old
   data gets the same treatment as new.

This means the change is rollout-safe: as soon as the new code ships,
all existing career logs auto-upgrade on next `learn_preset`.

### Step 5 — Reporting

Add a `decision_quality_summary` block to the learning report:
- mean quality per training idx (Speed/Stamina/Power/Guts/Wit)
- mean quality per period
- "highest-quality decisions" — top 10 actions across all samples
- "lowest-quality decisions" — bottom 10

Easy debugging signal: if the bot's mean Guts-decision quality is
consistently negative, we know the bot is mis-evaluating Guts trainings.

## Effort estimate

| Step | Time | Risk |
|------|------|------|
| Decision quality scorer | ~2 hours | Low — pure compute |
| weighted_action_distribution | ~1 hour | Low |
| Rewrite tune_extra_weight | ~1 hour | Medium — validate against current reports |
| Rewrite tune_base_score | ~30 min | Low |
| Rewrite tune_score_value | ~1 hour | Medium |
| Backwards-compat for old logs | ~1 hour | Low |
| Test coverage | ~2 hours | Low |
| Validation against last 30 reports | ~1 hour | Medium |

Total: **~10 hours of focused work, weekend project.**

## Risks

1. **Signal B requires training_snapshot in bot logs.** Need to verify
   that bot career logs capture the same snapshot the manual recorder
   does. If not, the bot logger needs a small extension.
2. **Quality scoring weights are themselves hyperparameters.** The
   coefficients in `signal_a_local_efficiency` (0.10 for rainbow,
   0.05 for hint, etc.) are guesses. Should be validated against
   manual run data.
3. **Top-vs-bottom split is no longer needed** for the tuners that move
   to per-decision learning. But `split_reference_groups` is still used
   by `tune_optional_race_policy` and `tune_expect_attribute`. Leave
   those alone in this pass — they're aggregate measures that genuinely
   benefit from career-level summaries.
4. **Convergence speed assumption may not pan out.** The other Claude
   estimated ~10× faster convergence. Reality could be 2-5× depending
   on how noisy individual decisions are. Worth measuring after first
   rollout.

## When to do this

After:
- The deviation logging pipeline (PLAN_deviation_logging.md) is shipped,
  which gives us per-turn bot-vs-human signal — natural complement to
  per-decision learning.
- We have ≥10 manual careers in the corpus, so Signal B has training_snapshot
  data to learn from.

Per-decision learning amplifies the value of those manual careers far more
than career-aggregate scoring ever could.

## What this does NOT replace

- The auto-tuner's preset-level adjustments (expect_attribute,
  rest_threshold, optional_race_max_training_score) still need career-level
  inputs. Only the action-frequency tuners benefit from per-decision.
- The training-policy linear classifier (`build_training_policy_model`)
  already operates per-action. This change makes its inputs cleaner but
  doesn't replace it.

This is genuinely the next big lever. Worth doing right.
