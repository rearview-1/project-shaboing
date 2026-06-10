# Event Probability Model — How the Sim Should Use It

This file is for Codex (or whoever wires it). The data extraction is done;
this doc explains how the sim should consume it for per-decision dynamism.

## What we built

`tools/build_event_probability_model.py` parses every `event_resolution`
across all `career_log_*.json` and produces:

`uma_runtime/instances/<instance>/sim_calibration/event_probability_model.json`

Schema: `sweepy_event_probability_model_v1`. Top-level:

```json
{
  "schema": "sweepy_event_probability_model_v1",
  "careers_total": 150,
  "careers_finished": 140,
  "event_count": 395,
  "events": { "<story_id>": {... per-event stats ...}, ... }
}
```

Per-event entry includes:
- `source` — "scenario" / "chara" / "support_card" / "other"
- `source_id` — chara_id or support_card_id (0 for scenario)
- `total_fires` — total observed fires across all careers
- `careers_fired_in` — how many distinct careers fired it
- `career_fire_rate` — careers_fired_in / careers_total
- `mean_fires_per_career_when_fired` — average fires/career when it does fire
- `turn_distribution` — `{turn_number: count}`
- `phase_distribution` — `{"junior": n, "classic": n, "senior": n, "tsc": n}`
- `top_turn` / `top_turn_share` — most common turn and its share
- `choice_picks` / `choice_pick_rates` — `{choice_index: count}` and `{choice_index: rate}`
- `effect_deltas` — per-state-field `{median, mean, min, max, n}` of observed deltas
- For `support_card` events:
  - `careers_with_card_in_deck` / `careers_without_card_in_deck`
  - `deck_presence_fires` / `guest_fires`
  - `fire_rate_when_card_in_deck` — conditional probability when card IS in deck
  - `guest_fire_rate_when_card_not_in_deck` — conditional rate when card NOT in deck (the rare guest case)

## How the sim should use it

Current sim ([career_simulator.py:4544+](../career_bot/career_simulator.py))
uses phase-based fire probability (86%/78%/68%/58%) and weighted source
selection. That's a single "an event fires" roll per turn, then picks one event.

**Replace with per-event independent rolls:**

### 1. Loading
At sim init, load the model. Build per-event:
- `effective_fire_rate` — `fire_rate_when_card_in_deck` if support_card and card in deck;
  `guest_fire_rate_when_card_not_in_deck` if card not in deck; `career_fire_rate` for chara/scenario.
- `expected_fires_per_career` — `effective_fire_rate × mean_fires_per_career_when_fired`
- `turn_probability_distribution` — normalize `turn_distribution` so it sums to `expected_fires_per_career`.

Per turn, for each event in the pool, P(fires this turn) = `turn_probability_distribution[turn]`.

### 2. Per-turn roll
For each event in the pool, roll a Bernoulli(P_turn). Multiple events can fire same turn (unlike current sim which fires ≤1).

### 3. Choice selection
When an event fires, sample choice from `choice_pick_rates`. This is the
observed bot-behavior distribution; it makes sim outcomes match bot outcomes.

**For the strategy-improvement use case**, the bot can override: at sim time,
the bot's `choose_from_event` strategy picks (not the empirical distribution).
This lets us A/B "what if bot picked choice 0 more often."

### 4. Effect application
Apply effect deltas from `effect_deltas` medians, scaled by support card
`event_effectiveness` / `event_recovery` per current sim logic. Don't average
across all events — apply each event's own median.

### 5. Guest events
Replace the hardcoded 7% (`sim_guest_event_probability` at
[career_simulator.py:4590](../career_bot/career_simulator.py#L4590))
with the model's `guest_fire_rate_when_card_not_in_deck` summed across all
support_card events with `guest_fires > 0`. Empirically this is currently 0%
in 150 careers — keep a small floor (1%) so the sim can still surface rare
guest events in long sweeps.

## What this enables

- **Per-deck dynamism:** different decks produce different event pools and
  different rates. A new deck would pull in its cards' event probabilities
  automatically.
- **Stat variance from event picks:** the choice pick rates capture that
  the bot sometimes picks the better choice and sometimes the worse one.
  This explains real-career stat variance the current sim averages away.
- **SP/stat budget realism:** each career rolls its own event sequence;
  good runs roll high-SP events fortunately, bad runs don't. Matches the
  variance you see (A+ vs S+ vs SS).
- **Chain completion:** modeling each step of a card's event chain as
  independent rolls naturally produces the "got all 5 Riko outings" vs
  "only got 3" variance.

## Limitations (to flag to user)

- **Choice picks are bot-conditional:** if the bot strategy changes, the
  observed pick distribution becomes stale. Best to use this for "predict
  current bot's outcomes" and let the strategy override for "what if bot
  picked differently" A/B tests.
- **Effect deltas are also bot-conditional:** if the bot only picked choice 1,
  we only have data for choice 1's effects. To explore choice 0/2 outcomes,
  we'd need to either (a) trigger those choices in some careers, (b) parse
  `data/event_id_index.json` for the raw template effects.
- **No fixed-turn scripted events surfaced:** all observed events spread
  across many turns. Either the user's bot triggers scripted events out of
  order, or there are very few strict turn-fixed events in MANT. Worth
  cross-referencing against the static event tables.
- **Recurring events:** top events fire ~20× per career. The "fire rate per
  turn" distribution captures this — the per-turn integral of probability
  across the career equals the expected fires-per-career.

## How to rebuild the model

After more careers are run:
```bash
python tools/build_event_probability_model.py
# (defaults to account_b instance)
```

It re-reads all `career_log_*.json` and rebuilds the JSON. Run it after each
batch to keep the calibration fresh.
