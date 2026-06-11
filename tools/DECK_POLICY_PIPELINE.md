# Per-Deck Policy Pipeline — Many-Worlds Optimization

## The architecture

```
                  ┌──────────────────────────────────┐
                  │  career_logs (real game data)    │
                  └─────────────┬────────────────────┘
                                │
                                ▼
                  ┌──────────────────────────────────┐
                  │  build_event_probability_model.py│
                  │  (per-event fire rates, choice   │
                  │   picks, effect distributions)   │
                  └─────────────┬────────────────────┘
                                │
                                ▼
                  ┌──────────────────────────────────┐
                  │  Sim runs many "worlds" per deck │
                  │  optimize_deck_policy.py samples │
                  │  hyperparameter candidates and   │
                  │  evaluates each across N sims    │
                  └─────────────┬────────────────────┘
                                │ (winning policy)
                                ▼
                  ┌──────────────────────────────────┐
                  │  deck_policies.json cache        │
                  │  keyed by deck_signature         │
                  └─────────────┬────────────────────┘
                                │
                                ▼
                  ┌──────────────────────────────────┐
                  │  main._apply_cached_deck_policy  │
                  │  hydrates preset before runner   │
                  │  starts a real career            │
                  └──────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `tools/build_event_probability_model.py` | Mines career_logs → `event_probability_model.json` |
| `tools/EVENT_PROBABILITY_MODEL.md` | Schema + sim wiring guidance for the event model |
| `tools/optimize_deck_policy.py` | Per-deck random search; writes winning policy to cache |
| `career_bot/deck_policy_cache.py` | Cache module: signatures, load/save, apply-to-preset |
| `main._apply_cached_deck_policy()` | Wiring point in real-career hydration |
| `tests/test_deck_policy_cache.py` | API/behavior pins for the cache module |
| `uma_runtime/instances/<inst>/sim_calibration/deck_policies.json` | The cache file (per instance) |

## Lifecycle

### 1. Build the event probability model
```
python tools/build_event_probability_model.py
```
Rebuild after each batch of new careers. Writes to
`sim_calibration/event_probability_model.json`.

### 2. Optimize hyperparameters for the current deck
```
python tools/optimize_deck_policy.py
```
Defaults: 8 random candidates × 5 sims each, 8 baseline sims, 8 validation
sims. ~25 minutes on the user's deck. Writes winner to
`sim_calibration/deck_policies.json` keyed by deck signature.

Tune for thoroughness vs speed:
```
python tools/optimize_deck_policy.py --candidates 16 --sims-per-candidate 8 --validation-sims 12
```

### 3. The bot's next real career auto-uses the policy
`main._apply_cached_deck_policy(preset)` is called inside
`start_career_runner_once`. It:
- Computes the deck signature from preset's `_run_context`.
- Looks up the cached policy.
- Merges into `preset.learned_hyperparameters`; deck-specific optimizer keys
  win over stale auto-learned execution knobs for the same deck signature.

The bot prints either:
- `deck policy: applied cached entry <sig> (added N hyperparameter keys: [...])`
- `deck policy: no cached entry for signature <sig> (trainee=..., deck=...)`

So you always know whether the policy hit or missed.

### 4. New deck? Run the optimizer between sessions
The bot doesn't BLOCK on optimization — it just uses defaults if no policy
is cached. When you switch decks, run the optimizer once, then the bot uses
the tuned policy.

## Deck signature

`hashlib.sha1(canonical_json({trainee, support_card_ids (sorted), scenario, friend})).hexdigest()[:16]`

- Slot-order independent (support cards are sorted)
- Differentiates trainee, deck, friend, scenario — each change → new signature
- 16 hex chars = 64 bits = collision-free in practice

## What's NOT covered yet

- **Per-turn MCTS at decision time.** The sim still uses heuristic decisions
  inside each rollout. The deeper "look at K rollouts per choice" is a
  follow-up.
- **Cross-deck policy transfer.** Each deck optimization is independent;
  similar decks don't bootstrap from each other.
- **Auto-optimization on first encounter.** If the bot sees a new deck and
  no policy exists, it logs the miss but doesn't trigger optimization
  automatically. Doing so live would block the career for ~25 min; better
  to surface the miss and let the user trigger between sessions.
- **Wiring the event probability model into the sim.** The model is built
  but not yet consumed by the simulator. See `tools/EVENT_PROBABILITY_MODEL.md`
  for the integration plan.

## Verifying the pipeline end-to-end

```
# 1. Run cache tests
python -m pytest tests/test_deck_policy_cache.py -v

# 2. Verify policy loader doesn't break startup
python -c "import main; print('ok')"

# 3. Run optimization on current deck (will save policy if winner beats baseline)
python tools/optimize_deck_policy.py

# 4. After a real career runs, look for the loader log line
#    grep "deck policy: " in the runtime logs.
```
