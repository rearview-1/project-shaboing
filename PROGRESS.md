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

### 2026-06-13 — fidelity residual characterized; loop running on fixed sim
- Probed the residual ~430 gap (proven deck 4468 vs manual 4901). Findings:
  * Found a test bug: my proven-deck reconstruction used the LIVE friend (Riko 30036)
    instead of the manual career's friend (30094) - so proven-deck numbers were slightly
    off (right 5 cards/MLB, wrong friend). Live-deck optimizer is unaffected (real setup
    resolves the correct friend).
  * The proven deck is wit+guts focused (2 wit:30054/30010, 2 guts:30019/20041, 1 spd:30028)
    - clarifies why current speed/wit-tuned levers can't push it; and manual's
    speed1161/power1114/guts1200 distribution implies heavy use of race/event/inheritance
    stats + 2874 SP (a play pattern the sim only partly models).
  * Even with aggressive concentration levers the accurate sim caps ~4472 on it - residual
    is NOT pure lever-tuning; partly the empirical race total being a MEDIAN (good play
    exceeds it via more/higher wins) and partly non-rainbow stats (power/guts here) reaching
    cap via sources the sim under-credits. Closing it needs per-grade race-stat data or
    manual per-turn captures I don't have, or fresh live careers (farm down).
- DECISION: dominant fidelity bug is fixed (race under-credit, +492, S->S+); the sim now
  REPRESENTS good play, which is what the optimizer needs. Rather than chase the last ~9%
  by hand against confounded data, run the self-improvement loop on the fixed ground:
  launched optimizer (mean obj, 24 cand x10, 32-sim validation) on the LIVE deck in the
  accurate sim (accurate_sim_opt.log). This is the core deliverable operating on an honest
  training ground for the first time.
- RESIDUAL FIDELITY (queued, needs data): (a) race stat total should scale with win
  quality/grade, not flat per-era median; (b) re-audit absolute bot-match vs FRESH post-fix
  live careers once the farm runs (current +331 vs stale logs is confounded).



### 2026-06-13 — SIM UNDER-PRODUCTION ROOT-CAUSED + FIXED (the ~20% gap)
- Decomposed a proven-SS-deck career by stat source. Found the dominant bug: race stat
  rewards used hardcoded RACE_GRADE_REWARDS (G1=10, one random stat) while the sim ALREADY
  loaded real per-race-turn data (empirical median ~31, distributed) but BYPASSED it; the
  distributed-application path was dead code. Those hardcoded rewards were tuned to the
  bot's mediocre stat_sum and, with the inflated replay training scale (1.95), were two
  OFFSETTING errors. Formula training (accurate) exposed the race under-credit.
- FIX (acd7866, flag sim_empirical_race_stat_total): use empirical per-era total +
  distributed application. Proven-SS deck: 3976 -> 4468 median / 4626 max, rating S -> S+.
  +492 stat sum from one fix. 31 sim tests green.
- Enabled all 3 accurate-model flags in the preset (837c173): sim_formula_training_gain +
  sim_empirical_race_stat_total + sim_use_shop_refresh_pools. OFFLINE-SIM ONLY (live plays
  the real game; the sim is the optimizer's training ground). The optimizer/cadence now
  train against accurate physics instead of an S-capped offsetting-error model.
- Decomposition after fix (proven deck, 4416 this seed): start 696, training +1532,
  race_dist +964, climax +275, event +496. Remaining gap to manual 4901 (~430-485) is
  now POLICY: running the proven deck's CARDS through the CURRENT preset's LEVERS (tuned
  for a speed/wit deck, not the proven speed/power/guts deck) -> power 866/guts 683 vs
  manual 1114/1200. Concentration for the actual deck is the optimizer's job now.
- Calibration caveats (honest): (a) accurate model reads +331 vs the bot's HISTORICAL
  (pre-fix, mediocre) logs - confounded; re-audit vs fresh post-fix live careers (farm
  down). (b) empirical race total is a MEDIAN; manual good play may exceed it (more/higher
  wins) - a percentile or win-quality scaling could close more of the residual.
- STATUS vs mission: sim went from "cannot represent SS, capped S+/4166" to "represents
  good play at S+/4468, max 4626" on a proven-SS deck. The training ground is now honest
  enough for the optimizer/self-play to target SS. NEXT: let the optimizer find the
  concentration policy for the live deck in the accurate sim; re-audit vs fresh live data.



### 2026-06-13 — DECISIVE: sim under-produces ~20% even on a PROVEN-SS deck
- Ran the sim on the EXACT deck+trainee that hit 4901 manually (trainee 106102, friend
  30094, deck [30054,30019,30010,30028,20041]) in formula mode + shop pools + good-play
  levers -> stat_sum median 3915, MAX 4166. Cannot reproduce 4901 on a 4901 deck.
  => IT'S THE SIM, NOT THE DECK. Systematic ~15-20% total-stat under-production, deck-agnostic.
- This corrects two earlier framings:
  * My "deck can't hit SS" (wrong - user's manual proves the card pool can).
  * Tonight's "concentration is the bottleneck" (partly wrong - even a proven-SS deck with
    concentration caps ~4166; the gap is AGGREGATE production, not distribution).
  * NOTE: none of the 4800+ manual careers used the CURRENTLY-LOADED deck (trainee 106701 +
    Riko friend) - they used 106102/104101/102001 + meta SSRs. Current deck's true ceiling
    is unproven, but the proven-deck test isolates the sim as the under-producer regardless.
- Off-core suppression change was built then REVERTED: no-op on this deck (stamina 636 /
  guts 413 already low - nothing to suppress). Diagnosis kept, code reverted (validation gate).
- THE fidelity bug to fix (next session, highest priority): decompose a formula-mode career
  on the proven deck into stat-by-source (training total / race rewards / events / climax
  +10-all x3 / epithets) and compare to where 4901 must come from. Candidates for the ~20%:
  (a) too few training turns, (b) high-facility/rainbow/great-mood regime under-modeled,
  (c) non-training sources (race/climax/epithet stats) under-credited, (d) mood lower than
  real play. Likely (c)+(b). Fix so the sim reproduces ~4900 on the proven deck BEFORE any
  more policy/optimizer work - a policy tuned on a 20%-light sim learns wrong lessons.
- Shop-pool sim wiring (ed71e2f) stands: validated correct, default off, A/B showed it
  doubles boost-item buys but is outcome-dormant (consistent - amplifier on a short sim).



### 2026-06-13 ~03:00 — shop-refresh data landed (Codex) + sim wiring (mine)
- Codex shipped (69488b3): data/shop_refresh_pools.json from the REAL hakuraku API
  (/api/shop-refresh; 14,720 scheduled + 29,505 race samples). Structure exactly to spec:
  scheduled[item_id].expected_copies_by_turn, race[item_id].expected_copies_by_grade_result,
  full name->id mapping (0 unmapped). Plus shop_refresh.py loader, runner hook
  (build_shop_decision_state - exposes shop + refresh DESCRIPTOR; actual paid refresh left
  unwired at the auth boundary, correct), rebuild tool, tests. All green.
- Mine (ed71e2f): _shop_pool_counts wires the real pool into the sim's buy-sampling,
  replacing replay-biased _observed_item_counts. Behind sim_use_shop_refresh_pools
  (default OFF). Validated vs source (megaphone 0.62->0.80, anklets T18+, SPD+3 stops T24);
  caught+fixed a carry-forward bug (absence=not offered=0).
- NEXT UNITS (fresh session, need A/B validation - do NOT rush tired):
  1. Flip sim_use_shop_refresh_pools on; A/B career outcomes vs observed-counts baseline
     (expect better training-item acquisition; measure stat-sum/rating shift).
  2. Model race-refresh shop (the missing acquisition channel) using race[] pool.
  3. Buy-priority policy: prioritize megaphone/anklet/hammer when offered (works live now,
     no refresh needed). Touches items.py (Codex's lane too - coordinate).
  4. STILL the dominant gap per earlier finding: stat CONCENTRATION (spread 5 -> cap 3).
     Shop items amplify a concentrated build; wasted on a spread one. Concentration first.
- Honest status: shop domain now has real data + sim hook; it's a force-multiplier that's
  mostly dormant until concentration is fixed (measured +135 alone). Not the SS unlock by
  itself - consistent with the earlier honest assessment.



### 2026-06-13 ~02:00 — formula model SHIPPED + validated necessary-but-not-sufficient
- Committed 10ac98d: formula-based training gain (drops 1.65/1.95 fudges; L1 speed/0card/bad
  mood now = 7/3 matching the game table; 7x dynamic range worst->strong tile). Flag
  sim_formula_training_gain (default OFF, survives hydration unlike sim_training_gain_scale).
  30 sim tests + regression test green.
- THEN immediately tested whether formula mode unlocks SS. IT DOES NOT alone:
  formula + aggressive good-play levers -> max stat sum 4295, 0/12 SS (vs manual 4800-4900).
- Localized the REMAINING bottleneck with data (NOT the per-tile formula, NOT facilities,
  NOT rainbow rate):
  * facilities DO reach L5 (27 L5 speed tiles seen) -> facility-building is fine
  * rainbows fire 55% of chosen tiles -> rainbow achievement is fine
  * the gap is STAT CONCENTRATION: bot spreads output across all 5 stats (~780-1000 each,
    none capping); manual SS careers concentrate 3 racing stats to 1200 + leave 2 low.
    Convex rating curve punishes spreading. Deck is [2spd,0sta,1pow,2wit]+Riko(sta) ->
    a concentrated speed/wit/power build (Riko covers stamina via outings) is the target.
- OPEN / NOT YET PROVEN: that the formula sim can reach 4800 with ANY policy. Current
  levers max at 4295. Next: hand-construct a maximally-concentrated policy; if it reaches
  ~4800 the gap is lever-expressiveness (need concentration levers in PARAM_SPACE); if not,
  the sim still under-produces vs manual and needs further calibration. DO NOT flip the
  formula flag on for live until this is settled + validated vs manual end-states.
- Honest state: formula fix was real, necessary, committed. SS is still NOT unlocked.
  Multi-front as expected: concentration policy is the next layer.



### 2026-06-13 — TRAINING MODEL IS REPLAY-BASED (corrected twice; verified)
- User gave the game's facility base table + asked what the sim yields for L1 speed/0 cards/bad mood.
- Direct answer: sim gives ~12 spd/6 pow; game base 8 x0.9 mood x1.0 growth ~7 spd/3 pow.
- Chased the `x1.65 sim_training_gain_scale` -> RED HERRING. Verified account_b sims use
  `_make_real_training_commands`: REPLAY the bot's real observed tiles x `_real_training_gain_scale()`
  = **1.95** (DEFAULT 1.85 + deck bonus). The 1.65 synthetic path is an unused fallback.
- So: real knob = `_real_training_gain_scale` (~1.95, the measured 2x per-tile inflation).
  Applied UNIFORMLY -> can't represent good-play tile STRUCTURE (high facility/rainbows).
  And replay can only reproduce tiles the bot has played -> sim structurally can't represent
  SS training. THAT is the ceiling (replay-coverage + flat-scale), not a fudge constant.
- My no-op tests (patching _support_training_gain, setting sim_training_gain_scale) hit the
  wrong/dead path; sim_training_gain_scale is also stripped by hydration. Memory updated.
- FIX (scoped, keystone = facility table): build a FORMULA tile-gain model
  (facility base x growth x mood x training-eff x friendship/rainbow) replacing replay+1.95,
  so the sim can represent unobserved good-play tiles; validate vs manual careers.
- Honest note: humbling turn — wrong about the deck ceiling (manual careers prove SS), wrong
  about which scale, no-op tests. But converged on the verified architecture + the real fix.



### 2026-06-12 ~23:45 — DECK-CEILING FINDING (re-scopes the SS goal)
- Goal restated by operator: SS consistently (rating >=17,500) + 95% WR on ALL G1s.
- Two independent sim sweeps with the saved policy (n=40 ceiling + n=40 variance), 80
  careers total: rating median ~15,400-15,750 (S), max 17,385, **0/80 SS**. p90 ~16,500.
  CONCLUSION: this deck's ceiling is S+, not SS. SS *consistently* (median SS) needs
  ~+1,500 rating at the median over the best tuning — NOT reachable by policy on this
  deck. It is a DECK constraint (trainee 106701 + Riko friend + current 5 supports cap
  ~4,000-4,400 stat sum; SS needs ~4,600+ concentrated). Operator decision: stronger
  SSR/limit-breaks for SS. Confirming with a rating-max optimizer (ceiling_search.log).
- Variance (rating stdev ~654) is normal career RNG, NOT an early-bond collapse: top vs
  bottom third had near-identical t30 bonds@80 (1.4 vs 1.5) and rainbows (0.2 vs 0.2);
  the gap is whole-career stat accumulation (+282 sum) + race RNG. No single bug to squash.
- 95% G1 WR: sim (current code) says this deck+policy already does ~96% (median 1 G1
  loss). CANNOT trust vs live yet — the live 13:50-16:40 "full-stack" careers (median 6.5
  losses) ran STALE in-process code (restart was ~16:40). Only the 16:57 clean career is
  post-restart, and it matches the sim's top third. Need post-restart live careers to
  judge. FARM IS IDLE since 16:57 (~7h) — no fresh data; restart the runner to resume.
- ACHIEVABLE near-term: (a) drive this deck reliably to its S+ ceiling with <=1-2 G1
  losses; (b) per-phase skill modeling (deepest sim gap, serves 95% WR, validatable w/o
  live). NEXT BUILD = per-phase skills.



### 2026-06-12 ~20:00 — FIRST CLEAN CAREER
- 16:57 career: 0 losses, 0 G1 losses, sum 4388 (1004/780/864/559/1181). First clean
  record of the entire project under the autonomous stack — and likely among the first
  careers on fully current code post-restart (16:40 truncated career suggests the
  operator restarted). 1000+ speed, wit 1181: an inheritable parent.
- Mission metric officially moving: clean rate no longer zero. Watch the next cadence
  corpus pick this career up as a top sample (it should dominate the learning pool).

### 2026-06-12 ~19:00 — churn-save guard
- 15:27 cadence verdict: validation IDENTICAL to baseline (clean 0.060 both, rating -10)
  yet saved on a microscopic loss-term tiebreak. 7d53e8e: saves now require a meaningful
  lift (0.5/n_validation for fractional objectives, +25 for rating-scale). The saved
  policy was ~the incumbent, so no revert needed.
- Self-healing pid release verified in code path (81cbafc); counter cycling normally.
- Steady state: career stream 4-9 losses, sums 3700-4300; stamina>=840 careers remain
  the standouts. Next cadence in ~6 careers under the new min-lift gate.

### 2026-06-12 ~18:30 — second pid-reuse deadlock; made cadence self-healing
- Cadence froze again at careers_since=15 (12:51 run's pid reused). Manual unstick #2.
- Permanent fix that works WITHOUT a server restart: the spawned optimizer (always
  current code) now zeroes its own pid in policy_optimizer_state.json on exit
  (finally block). Plus 1f2fe18's log-based liveness applies post-restart.
- Career stream since last entry: 4, 8, 8, 5, 9 losses (sums 3741-4304; stamina>=840
  careers keep being the good ones). Next finished career spawns the overdue cadence.

### 2026-06-12 ~17:45 — revert rule resolved: policy stays
- Post-save (13:50 clean-rate policy) cohort: 2, 16, 8, 6 losses (G1: 2, 11, 6, 1).
  The 16-loss career triggered a revert watch; rule was 'two consecutive >8 -> revert'.
  14:25 hit exactly 8, 14:35 came in at 6 (1 G1) -> NO revert; the 16 reads as outlier.
  Next cadence (~3 careers) re-validates with this data in corpus.
- Recurring signal worth a future lever: two of the loss-heavy careers overshot wit to
  1187 while speed/stamina lagged - the live (stale-server) scoring still over-buys wit
  occasionally; the optimizer searches wit_priority so the cadence should converge it,
  but if wit>1150 careers keep pairing with 6+ losses, add a wit-overshoot penalty to
  the sim objective corpus analysis.

### 2026-06-12 ~17:15 — 20-career fidelity re-audit: T8 CLOSED
- Audit vs current-code corpus: G1-loss median delta -1 (was -2 pre-recalibration).
  Decision rule said tighten only if < -1; we're AT the boundary and the integer median
  can't resolve finer. No further race-model changes. Stat sum +149 / SP +47 stable.
- Residual known gaps (low priority): support_events SP -105, skill-spend +398 estimate
  mismatch. Queue only if they start distorting optimizer choices.
- LOOP IS SELF-DRIVING. Next operator-visible milestones: restart applies the 32-sim
  validation gate + in-process consumers; cadence re-validates the clean-rate-first
  policy every 8 careers; watch live clean rate climb from ~0.06-0.12 baseline.

### 2026-06-12 ~16:45 — first honest-odds cadence verdict: SAVED
- Run optimizer_20260612_125144: winner clean_rate 0.123 vs baseline 0.060 on held-out
  seeds (+0.062), mean rating 16460 vs 16611 (-151), SS 1/16 vs 3/16. Saved — correct
  under the lexicographic objective (clean record outranks rating). Candidate-phase
  winner hit mean 17,127.
- Confirmation of the recalibration: the previously-saved policy's clean rate under
  honest odds is ~0.06-0.12, not the 0.50 the old fantasy model claimed.
- Caveat: validation ran n=16 (stale server still spawns with old args; 32-sim gate
  c74b384 takes effect after operator restart). Half-sigma saves remain possible until
  then; incumbent-seeded re-validation every 8 careers self-corrects.

### 2026-06-12 ~16:15 — career stream + pending triggers (pre-compaction checkpoint)
- Full-stack career series: 2, 5, 4, 8, 1, 9, 6, 6, 8 losses. Mean ~5.4, variance high.
  Clear coupling: loss-heavy runs have weak statlines (3726-4001) while the 1-loss run
  hit 4492 — early stat production (bonds/rainbows) drives BOTH outcomes. The optimizer
  levers target exactly that.
- PENDING when this resumes:
  1. Optimizer verdict monitor bc9np8y6p armed — run optimizer_20260612_125144.log
     started 12:51 (incumbent-seeded, 32-sim gate, honest race odds). Journal verdict;
     if saved, the next careers hydrate it automatically.
  2. ~17 current-code careers done; at ~20 run the fidelity re-audit
     (tools/audit_simulator_fidelity.py --n 16 --instance account_b) and compare G1-loss
     delta against THIS corpus only; recalibrate further only if delta still < -1.
  3. Re-arm a career-outcome monitor (script pattern in this journal's earlier blocks).
- All loop components live: subprocess learning per career, cadence optimizer (deadlock
  fixed 1f2fe18), reality-capped race model (199edb8), adaptive score floor (417c683).

### 2026-06-12 ~15:30 — cadence deadlock found and fixed
- Optimizer cadence was DEADLOCKED at careers_since=11: the finished 10:52 run's pid was
  reused by an unrelated process, pid_exists stayed true forever. 1f2fe18: liveness now
  judged by the run's own log (terminal markers) + 2.5h max age; os.kill(0) probe removed
  (TerminateProcess on Windows!). Live state unstuck (running_pid=0) -> next finished
  career spawns the run; monitor bc9np8y6p armed for its verdict.
- Career stream: 12:28 8L/8G1 (sum 4243), 12:37 1L (best of day, sum 4492), 12:47 9L/6G1
  (wit 1187 - occasional wit-overinvestment persists). High variance; mean trending down.

### 2026-06-12 ~15:00 — cohort verdict (5/5)
- Post-policy cohort complete: losses 7, 8, 2, 5, 4 (G1: 4,3,2,4,3). Mean 5.2 vs ~7.6
  pre-policy today. Trend right, not clean yet. Stats clearly better: final career hit
  speed 1059 (first 1000+ live speed today), wit 1066, sum 4296; guts stable 570-700.
- New sim model implies ~2.9 losses/career at 91.9% win rate over ~36 races — live mean
  5.2 still above it, but live includes the two pre-learned-update careers (7, 8). The
  three careers with the full stack: 2, 5, 4 (mean 3.7) — close to sim. Calibration
  holding; full re-audit still queued at ~20 current-code careers.
- Next event: cadence optimizer run (monitor b7xk0970v) — honest-odds validation of the
  incumbent policy.

### 2026-06-12 ~14:30 — autonomous block 8: T8 SHIPPED (race-model realism)
- Branch probe pinpointed it: 92% of sim races rode threshold branches at flat 0.985 →
  95% sim win rate vs ~80% live. 199edb8 ships three bounded fixes (lift 0.985→0.95,
  global per-race ceiling 0.96, hard observed-evidence block <0.70). Post-fix probe:
  91.9% overall, threshold branches 0.945-0.952 — inside the live good-career band.
  30 sim tests green. G1-loss median delta still -2 vs the MIXED live corpus; re-audit
  against the post-policy cohort once ~20 current-code careers exist before tightening
  further (do not over-correct against old-policy data).
- Cohort update (3/5): losses 7, 8, then **2** — the 11:58 career was the first running
  BOTH the saved policy and the 11:44 self-learned preset update; guts 698 shows the
  allocation shift landing. Small n, right direction.
- NOTE: the saved deck policy + incumbent seeding + new race model meet in the NEXT
  cadence run (monitor b7xk0970v armed) — its validation now happens under honest race
  odds.

### 2026-06-12 ~14:00 — autonomous block 7: T8 promoted to top priority
- Post-policy cohort so far: 2 careers, 7 and 8 losses (G1 4 and 3). No live improvement
  signal from the saved policy yet; n tiny.
- DECISIVE GAP: live careers lose 7-8 races; sim with the SAME policy claims mean 1.47.
  Sim G1 win rate far above live (audit already showed G1-loss median -2). The optimizer
  is tuning in a world where races are nearly free wins -> it under-invests in race
  safety. T8 (race-model realism) is now the binding constraint on everything else.
- T8 plan (execute next, regardless of cohort completion):
  1. Branch probe running (diag_race_model_branches.py): per-model win rates in sim —
     suspicion: manual_safe_threshold_override (the 0.985 clean-prebuy lift) fires far
     more generously than reality.
  2. Compare sim win_probability vs LIVE outcome at the live careers' actual pre-race
     stats (postmortems have them) — per-race calibration table.
  3. Recalibrate: cap/temper the optimistic branch(es); validate via audit tool's
     G1-loss delta reaching ~0 against the post-fix live corpus; full suite + sweep.
- Monitors active: cohort careers (bjrq2uy2k), next cadence optimizer run (b7xk0970v).

### 2026-06-12 ~13:30 — autonomous block 6: learning runs current code, always
- 64b370b (committed by Codex's auto-commit while my suite ran — benign collision,
  identical content; NOTE: commit promptly after validation, Codex sweeps the tree):
  per-career auto-learning now runs in a spawned subprocess
  (tools/run_auto_learning_once.py, UTF-8, 30-min timeout, blocking before tuner;
  rc=2 falls back in-process). Long-lived servers no longer pin learning to
  start-of-process code.
- Integration smoke against the live runtime applied the FIRST self-learned update from
  this account's own careers: 225 usable samples; gate corrective_apply; floor
  adaptation active (p75 9,721, 40 bot careers); changes across training policy, item
  policy, stat weights; operator fields preserved (report learning_report_20260612_114454).
  Career start re-reads the instance preset, so the running server consumes it without
  restart. The operator-restart note at the top of this file is now LESS urgent (only
  in-process consumers like the runner's own scoring remain stale).
- Cohort watch: 1/5 post-policy careers in (7 losses; policy hydration uncertain for
  that one — started seconds after the cache save).

### 2026-06-12 ~13:00 — autonomous block 5: variance reality-check
- c6c24ea: cadence search now seeds from the incumbent policy (verbatim + local
  perturbations + random explorers) — passes compound instead of re-searching.
- Post-policy sim baseline (n=30, seeds 777): clean 4/30, mean losses 1.47, SS 0/30,
  median 15,642 — far below the validation run's numbers on its own 16 seeds. Lesson:
  clean_rate at n=16 has sigma ~0.12; the save gate was acting on half-sigma evidence.
  c74b384: validation sims 16 -> 32 (preset-tunable). The saved policy itself is
  plausibly fine (beat baseline on identical seeds) but absolute claims need bigger n.
- Live-vs-sim verdict so far: live 0/14 clean vs sim ~13% — NOT yet conclusive sim
  optimism (p(0/14 | p=.133) ~ 0.14). First post-policy career: 7 losses (policy
  hydration uncertain — started seconds after the save). Cohort monitor continues.
- T8 stays queued pending cohort; T10 queued: move per-career auto-learning into a
  spawned subprocess (like the optimizer) so learning always runs current code without
  operator restarts.

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
