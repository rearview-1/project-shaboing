# Autonomous mission journal

> **OPERATOR: one action needed.** The live server imported its code at 09:23; everything
> committed after that (adaptive score floor 417c683 — the fix that lets learning run at
> all on this account; Riko passive-income credit ab307a3) is dormant in-process until you
> stop the runner + REFRESH BACKEND once. I deliberately did NOT force it remotely: a
> restart mid-loop would leave the farm idle until you return. The auto-optimizer cadence
> spawns fresh subprocesses, so policy optimization already uses current code meanwhile.

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

- [x] T1: DONE — 6 commits landed (9ffdc08..e87dcb8), full suite 1209 green first.
- [ ] T2: clean_rate optimizer pass — BLOCKED until Codex's data edits settle
      (support_card_bonuses.json + extract_game_data.py modified in working tree at
      ~10:0x; new commit 22aa31d 'Add safe GitHub auto updater' appeared). Re-check
      mtimes; launch when stable. No-skills diagnostic running (bnt4mphp5).
- [ ] T7: Snapshot data/ at optimizer start (copy to temp, point sims at it) so
      concurrent data refreshes can't kill long runs — implement before/with T2 relaunch.
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

### 2026-06-12 ~12:30 — autonomous block 4: THE LOOP CLOSED
- Production optimizer run 105248 (self-spawned by the cadence) VALIDATED AND SAVED its
  winner: clean_rate 0.500 vs baseline 0.438 on 16 held-out seeds each, mean rating +474,
  SS hits 4/16 vs 0/16. Policy persisted to deck_policies.json (signature d5df4a34...,
  matches live deck). Winner profile ~cand9: rainbow_take 1.96, junior_bond 0.64,
  speed_floor 1150, stamina_deficit_boost 0.21, rest 32, prebuy keep_sp 21.
  First complete end-to-end cycle: live careers -> cadence -> search -> held-out
  validation -> persisted policy -> (next career hydrates it; load_cache is per-career).
- The run crashed AFTER the save printing a unicode arrow to cp1252 stdout. Fixed
  (5e0182d): ASCII prints + PYTHONUTF8=1 in the spawn env.
- dab1fa6: sim fidelity warning now names the threshold source actually in use
  (postmortem-learned race_thresholds.json was active but reported as 'fallback').
- Verified item/shop domain artifacts: 45 learned items with phase stats on the live
  instance — all four domains now demonstrably log->attribute->update->validate.
- WATCHING (monitor bjrq2uy2k): next 5 live careers post-policy-save. Decision rule:
  if live clean rate stays ~0 while sim claims ~0.5 under the same policy, the sim race
  model is too optimistic — pull T8 recalibration forward immediately.

### 2026-06-12 ~12:00 — autonomous block 3
- 5d9d730: clean_rate display fix (was :.0f → every candidate printed "score=0").
- 071ed02: clean_rate objective now lexicographic (clean fraction → mean losses → rating)
  so candidates rank even when no career is clean; tests pin the term ordering.
- T5 fidelity audit vs fresh logs: stat sum +160 (mild sim optimism), final SP +9,
  G1 losses sim -2 vs real median. CAUTION before recalibrating: today's live sample
  includes the bad pre-fix morning runs and yesterday's wit-overweight policy, so part
  of the -2 is policy delta, not sim infidelity. Defer race-loss recalibration until
  ~20 live careers on current code exist (queued T8).
- PRODUCTION OPTIMIZER MILESTONES (run 105248, in flight): cand8 max rating 17,590 —
  first SS career in any sim; cand9 scored 5+/8 CLEAN careers (rainbow 1.96,
  junior_bond 0.64, stamina_deficit_boost 0.21, speed_floor 1150). Clean careers ARE
  reachable; validation step will decide the save. Live loop ran 2 more careers since.
- Queue add T8: race-loss realism recalibration after fresh-corpus accumulation.
- Queue add T9: when optimizer run 105248 completes, verify save/no-save decision and,
  if saved, confirm next careers hydrate the policy (deck policy: applied cached entry
  in server log / career run_context).

### 2026-06-12 ~11:30 — autonomous block 2
- PRODUCTION LOOP IS LIVE: operator restarted backend 09:23; 9 careers ran 09:37-10:58;
  the runner's auto policy-optimizer self-spawned at 10:52 after the 8th finished career
  (pid 27848, clean_rate, exactly the shipped cadence). Do not kill it.
- Live trend: first 5 careers bad (6-7 G1 losses), last 4 improving (2-4 losses; one hit
  wit 1200 cap; stat sums to 4316). Small n — keep watching.
- ab307a3: T4 passive-income floor credit (Riko: +110 stamina/+55 guts measured from 211
  live event deltas; linear decay to turn 78). Validated: 1189 tests + 30 sim tests +
  12-sweep median 15794 (up from 15252), stamina median unchanged.
- 417c683: ADAPTIVE SCORE FLOOR — the big one. Outcomes JSONL revealed every learning
  pass skips on no_top_samples_above_score_floor (floors 16k-17.5k vs best bot career
  14.3k; absolute bar unreachable => zero learning from own careers, ever). Now: when >=8
  finished bot careers exist and none clears its bucket floor, bar drops to account's
  recent p75 (clamped [4k, configured]). Verified end-to-end: learn_preset fits
  (p75=10394, 37 bot careers) instead of skipping. Monotonic gate still guards shipping.
- Codex landed: b72fbeb (conditional uniques in sim), d66a34e, d022d27 + in-flight
  daily_tasks/main.py/public work — staying off those files.
- My stale manual clean_rate optimizer run died/superseded; the production auto-run
  (current code) replaces it. Its result will land in deck_policies cache + log under
  learning/policy_optimizer_logs/.

### 2026-06-12 ~10:30 — autonomous block 1
- T1 done: 6 commits (9ffdc08, ec50241, 307a9a7, 7928c64, 3b64c80, e87dcb8), suite 1209 green.
- T7 done (71b91cf): optimizer snapshots data/ per run (junction for uma_runtime, rmdir-first
  cleanup, stale-snapshot sweep). Verified safe: runtime intact after orphan cleanup.
- Codex landed unique-effect decode in working tree (0/539 opaque, new condition/grants
  schema) — but career_simulator's merge still expects key/value, so uniques are currently
  IGNORED by sims until Codex's sim-side change lands. DO NOT touch career_simulator's
  unique merge — Codex owns it (task chip). Re-baseline + re-optimize after it lands.
- Tiny smoke run with Codex's refreshed data showed baseline mean ~17k on n=2 (vs 15.5k
  earlier) — n too small to trust; the data refresh changed LB values broadly. Re-baseline
  with n=30 once Codex finishes.
- T2 RUNNING: clean_rate optimizer (b730burzj), 40 cand x 10 sims + 40 validation,
  snapshot-isolated. On completion: review validation lift, confirm cache write.
- No-skills diagnostic (n=30): only 6/30 clean without skills; losses concentrate at
  Takarazuka Kinen 13x, TS-Spring 7x, Arima 5x, Osaka Hai 4x — senior medium/long G1s.
  Attribution run in flight (b2ebl78r1): extracting win_probability/pre_race_stats/
  race_model_details for lost-vs-won at those races to derive per-race stat/HP fixes.

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
