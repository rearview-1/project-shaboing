# Deviation logging: capturing "human disagreed with bot and won"

## Goal

When a human plays a manual career while `ManualCareerRecorder` is capturing,
we currently log:

- the bot's full view of the turn (`training_snapshot.trainings` — all
  tiles with stat gains, partners, rainbows, failure rates)
- which tile the human actually picked (`selected_training`)

What's missing: **the bot's would-have-picked tile, recorded alongside the
human's pick, so that every turn the human disagrees with the bot becomes
a labeled correction.** Combined with the career outcome, this gives the
auto-tuner a signal nothing else in the system has: "in winning manual runs,
where did the human override the bot, and what did they pick instead?"

## Why this matters

Right now manual careers get a 1.45× weight bump and flow through the
same top-vs-bottom split as bot careers. That's a *result* signal — "this
career scored well" — but it ignores the *decision* signal. A manual career
where you agreed with the bot on 78/78 turns teaches the same as a manual
career where you overrode the bot on 30 turns and still scored well. The
second is way more informative; we should treat it that way.

## Implementation plan

### Step 1 — Extract bot's would-have-decision into the turn log

**File:** `career_bot/manual_recorder.py`

The recorder already calls `runner._training_snapshot(state, preset)` and
saves it under `training_snapshot`. We add a second sibling field
`bot_recommendation` that computes what the bot's strategy would have
picked from the same state:

```python
# manual_recorder.py, near where training_snapshot is captured (~line 156)
try:
    bot_recommendation = self._compute_bot_recommendation(state)
except Exception as exc:
    bot_recommendation = {"error": str(exc)}

turn_record["bot_recommendation"] = bot_recommendation
```

`_compute_bot_recommendation` instantiates the same `MantStrategy` the
runner uses and calls `next_decision(state, preset)`, then extracts the
`command_id` / `command_type` / `program_id` from the returned Decision.
Reuse — don't fork — the strategy code so this stays in sync as we tune
the bot.

### Step 2 — Emit deviation rows when the human submits a turn

When the human commits a turn (`record_command` in manual_recorder.py),
the recorder already knows:

- `human_choice`: `command_type`, `command_id` from the request payload
- `bot_choice`: from `bot_recommendation` field captured in Step 1

Add a `deviation` field to the turn row:

```python
deviation = {
    "agreed": (bot_choice == human_choice),
    "bot_command_type": bot_recommendation.get("command_type"),
    "bot_command_id": bot_recommendation.get("command_id"),
    "human_command_type": req.get("command_type"),
    "human_command_id": req.get("command_id"),
    "bot_training_idx": TRAINING_COMMANDS.get(bot_recommendation.get("command_id")),
    "human_training_idx": TRAINING_COMMANDS.get(req.get("command_id")),
}
turn_record["deviation"] = deviation
```

Now every manual turn log row carries `agreed: bool` plus both choices.

### Step 3 — Loader function in learning.py

```python
def load_deviation_signals(runtime_root, recent=None, min_career_score=15000):
    """Return per-turn deviation rows from finished manual careers that scored
    above `min_career_score`. Only winning runs teach — losing-run deviations
    are noise."""
    rows = []
    for sample in load_manual_hachimi_careers(runtime_root, recent=recent):
        if as_float(sample.get("score")) < min_career_score:
            continue
        for turn in sample.get("turns") or []:
            dev = turn.get("deviation") or {}
            if not dev:
                continue
            rows.append({
                "career_path": sample.get("path"),
                "career_score": sample.get("score"),
                "turn": as_int(turn.get("turn")),
                "agreed": bool(dev.get("agreed")),
                "bot_training_idx": as_int(dev.get("bot_training_idx"), -1),
                "human_training_idx": as_int(dev.get("human_training_idx"), -1),
            })
    return rows
```

### Step 4 — New tuner term: `tune_deviation_bias`

```python
def tune_deviation_bias(learned, deviation_rows):
    """For each (period, training_idx), compute how often the human overrode
    the bot toward this training in winning runs. Convert to a small bias on
    `extra_weight` so the bot starts mimicking those overrides."""
    if not deviation_rows:
        return learned
    by_period_human = Counter()
    by_period_bot = Counter()
    for row in deviation_rows:
        if row["agreed"]:
            continue
        period = _period_index(row["turn"])
        if 0 <= row["human_training_idx"] < 5:
            by_period_human[(period, row["human_training_idx"])] += 1
        if 0 <= row["bot_training_idx"] < 5:
            by_period_bot[(period, row["bot_training_idx"])] += 1

    extra = list(learned.get("extra_weight") or [[0]*5 for _ in range(4)])
    for (period, idx), count in by_period_human.most_common():
        # Clamp bias so a small disagreement set can't override broader top-vs-bottom learning.
        bias = clamp(count * 0.01, 0.0, 0.05)
        if period < len(extra) and idx < len(extra[period]):
            extra[period][idx] = round(min(0.6, extra[period][idx] + bias), 4)

    # Symmetric demotion: where bot consistently chose X but human chose other things,
    # very slightly demote X in that period.
    for (period, idx), count in by_period_bot.most_common():
        if (period, idx) in by_period_human:
            continue
        penalty = clamp(count * 0.005, 0.0, 0.03)
        if period < len(extra) and idx < len(extra[period]):
            extra[period][idx] = round(max(-0.6, extra[period][idx] - penalty), 4)

    learned["extra_weight"] = extra
    return learned
```

### Step 5 — Wire it into learn_preset

After `tune_extra_weight` is applied, call `tune_deviation_bias` so it
adjusts on top of the existing top-vs-bottom result:

```python
# in learn_preset, after the existing tune_* calls:
deviations = load_deviation_signals(runtime_roots(base_dir)[0], recent=recent)
learned = tune_deviation_bias(learned, deviations)
report["deviation_signal"] = {
    "total_rows": len(deviations),
    "disagreed_rows": sum(1 for r in deviations if not r["agreed"]),
    "min_career_score": 15000,
}
```

### Step 6 — Tests

Two unit tests in `tests/test_learning_safeguards.py`:

- `test_deviation_bias_boosts_period_training_where_human_overrode`
- `test_deviation_bias_ignores_agreed_turns`

A smoke test in `tests/test_manual_recorder_smoke.py`:

- `test_deviation_row_marks_disagreement_when_bot_recommendation_differs`

## Effort estimate

- Step 1 (bot recommendation extraction): ~30 min
- Step 2 (deviation rows): ~20 min
- Step 3 (loader): ~20 min
- Step 4 (tuner): ~1 hour
- Step 5 (wiring + report): ~15 min
- Step 6 (tests): ~1 hour

Total: ~3 hours of focused work.

## Risks / mitigations

- **Small sample sizes** — if you only have 2 manual careers with 20
  disagreements each, the bias adjustments will be tiny. The clamp
  `count * 0.01 ≤ 0.05` keeps any single batch from steamrolling the
  broader top-vs-bottom signal. Build up the deviation corpus over time.
- **Reusing strategy code** — Step 1 needs to call `MantStrategy.next_decision`
  with the same state shape the runner uses. If the strategy's expected
  state ever drifts from what `manual_recorder` captures, the bot recommendation
  will error out. Catch & log the error; treat the turn as "no recommendation"
  rather than failing the recorder.
- **Career-score filter** — the `min_career_score=15000` floor only learns
  from manual runs that actually went well. If your manual runs score lower
  than this initially, lower the floor in the loader.

## What this does NOT do

- It doesn't predict bonds, plan multi-turn bond pushes, or change race
  decisions. It only learns from training-tile overrides.
- It doesn't weigh "how big the disagreement was" — a 0.01 score-delta
  override counts the same as a 0.5 override. A follow-up could weight
  by the score delta the bot computed.

## When to do this

After the auto-tuner has had a chance to ingest several manual runs with
the `manual_only=True` flag (which is shipped now), and after you've
recorded a small batch (5-10) of deliberate manual careers. Without
manual data in the system, this whole pipeline is dark.

---

## Precautions to bake in NOW (cheap; expensive to retrofit later)

These guard against the case where the bot eventually outperforms human
judgement and the deviation system would otherwise teach it to regress
toward worse human picks.

### Schema-level: log per-deviation alongside the row

Every `deviation` field on a turn row should also carry:

```python
deviation = {
    # ... existing fields ...
    "bot_score": float,                # bot's own confidence (best-tile score)
    "bot_second_best_score": float,    # next-best alternative
    "bot_score_margin": float,         # bot_score - bot_second_best_score
    "human_choice_bot_score": float,   # what the bot scored the tile the human picked
    "predicted_stat_gain": dict,       # bot's prediction for its own choice
    "actual_stat_gain": dict,          # what actually happened next turn
    "bot_parity_at_capture": float,    # mean(last_5_bot_scores) / mean(last_5_manual_scores), clamped [0, 1]
}
```

`bot_score_margin` is the most important — it captures bot confidence at
decision time. A 0.45-vs-0.43 disagreement is high-uncertainty; the bot
basically said "either is fine." A 0.65-vs-0.20 disagreement is the
bot saying "definitely train Speed" and the human overriding. The latter
should require *more* evidence before the tuner learns from it.

### Tuner-level: auto-fade as bot reaches parity

In `tune_deviation_bias`:

```python
def tune_deviation_bias(learned, deviation_rows):
    if not deviation_rows:
        return learned
    # Auto-fade: if the bot is averaging at parity with manual play, deviation
    # influence drops to ~0. The system stops learning from human overrides
    # once humans are no longer demonstrably better than the bot itself.
    parity_values = [as_float(r.get("bot_parity_at_capture"), 0.0) for r in deviation_rows]
    bot_parity = clamp(sum(parity_values) / max(1, len(parity_values)), 0.0, 1.0)
    fade_multiplier = max(0.0, 1.0 - bot_parity)
    # ... apply fade_multiplier to all deviation-derived bias terms
```

When `bot_parity` is 0.0 (bot far below manual), `fade_multiplier=1.0`,
full deviation influence. When `bot_parity` is 1.0 (bot matches manual),
`fade_multiplier=0.0`, no deviation influence. Linear interpolation in
between.

### Tuner-level: outcome verification gate

Only count a deviation row toward learning when the human's override
*demonstrably* outperformed the bot's prediction:

```python
def _deviation_outperformed_prediction(row):
    predicted = row.get("predicted_stat_gain") or {}
    actual = row.get("actual_stat_gain") or {}
    if not actual:
        return False  # No outcome data — can't verify
    pred_total = sum(predicted.values())
    actual_total = sum(actual.values())
    return actual_total > pred_total * 1.10  # 10% headroom
```

Filters lucky overrides that happened not to hurt. Only deviations with
measurable per-turn benefit teach.

### Operational: holdout A/B

Every 5th career, set `apply_deviation_bias=False` for that run and tag
it `deviation_holdout=True`. The learning report compares mean score
across `deviation_applied` vs `deviation_holdout` cohorts. If holdouts
match or beat the bias cohort, the report surfaces a warning that
deviation learning is no longer helping — user can flip
`learning_use_deviation_signal=False` to disable.

### Operational: sunset flag

```python
# In preset:
"learning_use_deviation_signal": True  # default; flip to False to disable
```

`learn_preset` reads this; if False, skip `tune_deviation_bias` entirely.
Easy reversal if the system goes south.

## Priority of the precautions

If only two can be done before deviation logging ships:

1. **Auto-fade based on bot parity** — the structural fix that prevents
   the system from regressing as the bot catches up.
2. **Bot-confidence schema fields** — cheap to add now, expensive to
   re-record careers later if missing.

Holdout A/B and sunset flag are valuable but can be added after data
collection starts. Outcome verification is the next layer of polish.
