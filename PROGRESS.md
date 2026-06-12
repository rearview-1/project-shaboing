# Autonomous mission journal

**Mission:** produce insanely good parents — careers that win their races and finish with
endgame statlines worth inheriting. Core deliverable: a genuine four-domain self-improvement
loop (racing / training / items / shop) with per-domain (1) decision logging, (2) outcome
attribution, (3) policy update, (4) held-out sim validation before shipping.

**Hard constraints:** race schedule never shrunk · operator preset fields never blanked ·
no auth/session code · tests + sim validation before every commit · one task one commit ·
learned updates validated and reversible.

---

## State of the world (2026-06-12, session start)

- SS = rating ≥ 17,500 (career_bot/rating.py). Sim baseline median ~15.6k, zero SS.
- Live June-12 batch: 19/19 careers had G1 losses (~4/career, mostly rank-2 while
  stat-dominant). Root causes found: phantom guts-gap hints (fixed), runaway tuner wit
  pressure (fixed), end-buy policy racing skill-light (prebuy flag enabled), rainbow
  starvation in sim from bond under-modeling (calibrated from 603 live deltas).
- Backend server may still be running pre-reload code — operator must restart before live runs.
- Codex (operator's other agent) is working on: decoding 221 opaque support-card unique
  effects (task chip queued). Don't collide with data/support_card_bonuses.json extraction work.

## Uncommitted work to land (validated: full suite 1176+30 sim tests green earlier today)

1. Postmortem dominance guard (postmortem_feedback, race_thresholds, race_postmortem, tests)
2. Learning observability JSONL + auto policy-optimizer cadence (runner, new test file)
3. Tuner Rule 12 wit guard + structural lever params (hyperparameter_tuner, tests)
4. Sim bond calibration + rainbow/bond levers + clean_rate objective + no-skills mode
   (career_simulator, mant, optimize_deck_policy, run_simulator_sweep)
5. Preset: calendar_race_prebuy_allow_midcareer_with_end_buy = true (operator-aligned:
   zero-loss-without-retries directive)

## Background tasks in flight

- ~~`bf9qnn18q` p80 optimizer~~ DIED at candidate 27 (~08:54) — almost certainly killed by
  Codex's 08:49 data-file refresh swapping JSON under a mid-candidate read. No process
  remains; no cache write happened (saves only at the end). Relaunch fresh after commits:
  clean_rate objective, final code + data. Lesson: optimizer runs are vulnerable to
  concurrent data refreshes — consider snapshotting data/ at start (future task T7).
- `bvtif55ie`: full test suite (incl. sim) running — gate for the 5 commits.

## Task queue (priority order)

- [ ] T1: Commit uncommitted work as 5 clean commits (after fresh full-suite run)
- [ ] T2: Process optimizer result; launch clean_rate optimizer pass; no-skills diagnostic
- [x] T3: Four-domain learning audit — RESULT: all four domains structurally close the
      loop already. Items/shop: extract_item_decisions_from_turns (log) →
      learn_item_policy score-weighted per-(item,phase) attribution → item_learning_policy
      consumed in items.py (phase/timing adjustments + skip rules) → ships inside learned
      preset behind monotonic gate. Racing: postmortems→hints/thresholds→prebuy/training
      bias (fixed today). Training: snapshots→decision_quality→hyperparams/deck-policies→
      optimizer held-out validation. Focus shifts to loop QUALITY: sim fidelity (skill
      modeling), optimizer cadence results, and measuring whether learned updates actually
      reduce losses career-over-career.
- [ ] T4: Riko/passive-income deck prior — credit expected outing stat income against
      stat floors so fresh decks start smart (composes with Codex's unique-effect decode).
- [ ] T5: Sim fidelity re-audit after next live careers (tools/audit_simulator_fidelity.py);
      recalibrate sim_training_gain_scale if bond fix made sim overshoot live stat totals.
- [ ] T6: Race-domain learning: per-race style/entry decisions are operator-locked (no style
      overrides except TS-Spring/Kikuka — feedback memory). Learning here = stamina/skill
      preparation per race (race_thresholds, prebuy) — verify attribution covers it.

## Journal

### 2026-06-12 — session work before autonomous mode (summary)
- Diagnosed June-12 overnight batch (see memory: jun12-g1-loss-diagnosis, ss-sim-tuning).
- Fixed phantom postmortem hints (dominance guard); corrected hints applied to live preset.
- Reset tuner wit escalation (0.55/0.70 → defaults), added Rule 12 guard + unwind rule.
- Added auto_learning_outcomes.jsonl (skips/errors now durable).
- Calibrated sim bonds (+7/+9 gain, start 20) — measured from live snapshots.
- Added rainbow_take_bonus / junior_bond_build_weight levers (default 0) to mant guard,
  tuner space, optimizer space. A/B validated directionally (bond w0.6 +223 median).
- Auto policy-optimizer every 8 finished careers in runner (default objective clean_rate).
- clean_rate objective + --no-skills diagnostic mode in optimizer/sweep tools.
- Enabled mid-career pre-race skill buying alongside end-buy (zero-loss directive).
- No-skills diagnostic: sim bot still wins ~20 G1s, loses ~1/career with zero skills →
  sim losses are stat/HP-driven; live skill impact likely larger (sim models skills as
  flat win-prob bonus — fidelity gap, noted in memory).
