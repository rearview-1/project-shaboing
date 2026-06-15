# Sweepy — Full Code Audit & Improvement Analysis

> Living document. Goal: understand **every cog**, log problems/bottlenecks/short-sighted
> losses, fix what's broken, and produce grounded, data-backed plans for using the sim to
> make the bot meaningfully better. Started 2026-06-14. Every claim is grounded in `file:line`
> or real data — no speculation; unverified items are marked **⚠ UNVERIFIED**.

## How to read this
- **§Inventory** — the map of the codebase.
- **§Subsystem audits** — one section per module group: what it does, every significant
  function ("cogs"), problems, bottlenecks, improvement ideas.
- **§Problems ledger** — consolidated, severity-tagged, with fix status.
- **§Bottlenecks** — what limits the project.
- **§Sim→better-bot proposals** — the deliverable: in-depth, reasoned, data-backed plans.

---

## §Inventory (2026-06-14)

Source LOC (excl. `.venv`, tests):
| Area | Files | Lines |
|---|---|---|
| `career_bot/` (top level) | 55 | 49,343 |
| `career_bot/scenarios/` | 3 | 5,792 |
| `uma_api/` | 2 | 2,184 |
| `tools/` | 37 | 9,999 |
| `main.py` (root) | 1 | 10,833 |
| **tests/** | 112 | 30,128 |

Biggest source files: `main.py` 10,833 · `career_simulator.py` 9,174 · `learning.py` 7,783 ·
`scenarios/mant.py` 5,720 · `runner.py` 5,683.

**Key architecture facts already established (this session):**
- The career sim **REPLAYS real training snapshots** (`data/real_training_snapshots.json`, ~39MB)
  for covered decks — `_support_training_gain` is called **0×/career** for account_b. Training-formula
  code is the **synthetic fallback + tile calculator** only. (See `project_sim_replay_and_bot_learning`.)
- Sim is ~99% synced to live on stat_sum (sim ~4085 vs real-career median 4111) **via replay**.
- The bot loses long/epithet G1s because the optimizer chased rating (speed/wit 0.45–0.60) while the
  **winning-profile** learning (`race_success_feedback.winning_stat_baseline`) was throttled
  (cap 0.20, absent from self-learn) — fixed in commit `5fcb30f`.
- Two-station setup: a VSC/auth station also commits here; its recent commits broke 7 tests in
  `test_version_seed_freshness.py` (auth version persistence) — their domain.

---

## §Subsystem audits

### Cross-cutting: orchestration & optimizer flow (audited directly, 2026-06-14)

**End-to-end loop:**
1. `career_bot/runner.py::CareerRunner` drives a **LIVE** career against the game client
   (`start`/`_run`, max_steps 2500), writing `career_log_*.json` + real training/race snapshots.
2. Post-run (`_schedule_post_run_outputs`, runner.py:707): runs `_run_hyperparameter_tuner`,
   `_run_auto_learning_subprocess` (learning.py), and `_maybe_schedule_policy_optimizer`.
3. `_maybe_schedule_policy_optimizer` (runner.py:1022): **every N=8 finished careers** spawns
   `tools/optimize_deck_policy.py` as a subprocess → writes a winning policy to `deck_policies.json`.
4. Next career's `_apply_cached_deck_policy` loads it. Loop closes.

**TWO optimizers, DIFFERENT objectives, DIFFERENT candidate sources (key finding):**
| | `tools/calibrate_deck.py` (manual `optimizer.bat`) | `tools/optimize_deck_policy.py` (auto, every 8 careers) |
|---|---|---|
| Objective | SS-rate / mean / win-rate + **epithet-loss veto** | **`clean_rate`** (lexicographic: clean careers → fewer losses → rating) |
| Candidates | `sim_self_learning` proposals + random | own `PARAM_SPACE` uniform sample + Gaussian perturb (`_sample_candidate`/`_perturb_candidate`) |
| Time | ~240s budget | candidates×sims (10×8), validation 32 |

- The auto loop's `clean_rate` objective (`_objective_score`, optimize_deck_policy.py:170) is well-designed
  (lexicographic, strict term scaling so a 1/N clean step always beats a loss delta beats rating).
- **⚠ The two optimizers don't share a candidate generator** — `optimize_deck_policy.py` does NOT import
  `sim_self_learning`, so improvements to one search space don't reach the other. This split is a
  maintenance/coverage hazard (see problem AUD-1).

### `runner.py` cogs (high level)
- `CareerRunner.start/_run` — live career driver (turn loop, action dispatch).
- `_maybe_schedule_policy_optimizer` (1022) — cadence-gated auto-optimizer spawn; Windows pid-reuse-safe
  via log-terminal + age checks (good defensive code).
- `_run_hyperparameter_tuner` (606), `_run_auto_learning_subprocess` (955) — post-run learning.
- Race-continue machinery (1317–2308: `_race_continue_*`, `_try_continues_pre_race_end`,
  `_resolve_race_end_with_retries`) — large live-game retry/recovery subsystem (carat/resource spend).
- `_training_snapshot` (2800) — emits the real training snapshots the sim later replays.

### Architecture map (full-stack)
- **`main.py`** — FastAPI backend (442 defs, ~40 `/api/*` endpoints): auth/session/login, presets,
  `/api/calibrate` trigger, decks/advice, learning_session, dailies, supports, team_bundle, admin.
  This is the server the UI talks to; it also kicks off the runner + calibrate.
- **`career_bot/runner.py`** — `CareerRunner`: drives LIVE careers via the game client; post-run
  learning/optimizer orchestration; race-continue/retry machinery.
- **`career_bot/career_simulator.py`** — the SIM (replays real snapshots; synthetic fallback + tile calc).
- **`career_bot/scenarios/mant.py`** — `MantStrategy`: the per-turn decision policy (SHARED by live + sim).
- **Learning/optimizer stack** — `learning.py` (career→preset aggregation), `sim_self_learning.py` +
  `hyperparameter_tuner.py` (candidate proposals), `tools/calibrate_deck.py` (manual) +
  `tools/optimize_deck_policy.py` (auto), `deck_policy_cache.py` (policy persistence).
- **`uma_api/`** — game API client/auth.
- **Race**: `race_sim.py` (physics) + `races.py`/`race_thresholds.py`/`race_success_feedback.py`/`postmortem_feedback.py`.
- **Economy**: `items.py`, `skills.py`, `event_choice_learning.py`.

**✅ Decision parity (foundational, verified):** both the sim (`career_simulator.py:2946` instantiates
`MantStrategy`, calls `next_decision` at 9021/9033) and the live runner (`runner.py:370/390`) drive the
**same** `MantStrategy.next_decision(state, preset)`. So a policy tuned in the sim IS what the live bot
executes — sims can legitimately improve the bot. **⚠ Open risk to verify:** the sim builds `sim_state`
vs the live `state` from the game payload — if their SHAPES diverge, the shared policy can still behave
differently (decision-INPUT parity, separate from decision-CODE parity). Flag for batch-2 verification.

_(agent reports appended below as batches complete)_

---

## §Problems ledger

| # | Severity | File:line | Problem | Status |
|---|---|---|---|---|
| AUD-1 | HIGH | optimize_deck_policy.py:144 `PARAM_SPACE` | The **auto** optimizer (runs every 8 careers — the real long-term improvement engine) optimizes `clean_rate` (win races) but its search space omitted `race_success_bonus_cap`/`race_specific_demand_cap` — so it could only chase clean careers via raw speed/wit, the bias that loses balanced G1s. My 5fcb30f fix only reached the manual calibrate. | **FIXED** 2026-06-14 (added both to PARAM_SPACE) |
| AUD-2 | MED | calibrate_deck.py vs optimize_deck_policy.py | Two optimizers with **separate** candidate generators (sim_self_learning vs own PARAM_SPACE) and **different objectives** (SS-rate+veto vs clean_rate). Improvements/levers must be added in BOTH; easy to forget (AUD-1 was exactly this). Consider unifying the search space. | Noted |
| AUD-3 | LOW | mant.py:3743-3850 | **Dead duplicate** `_race_hard_stat_floor_bonus` — defined at 3743 (3-arg) AND 3851 (4-arg, `command=None`); caller (3032) passes 4 args so 3851 is active and 3743 (~108 lines) is unreachable dead code from an incomplete refactor. **VERIFIED.** | TODO remove |
| AUD-4 | MED | sim_self_learning.py:36-37 + mant `_stamina_priority_bonus` (4748) | Stamina lacks a `_late` priority knob that speed/power/wit all have (only `stamina_priority_bonus_base` + `_deficit_boost`). So the optimizer can't raise stamina priority specifically in late game (when the long stamina G1s land); stamina relies only on deficit-based pressure. **VERIFIED (real coverage gap; partly mitigated by deficit + threshold + race-success levers).** | TODO |
| AUD-5 | HIGH | calibrate_deck.py ~826 + ~1168 | Epithet-loss veto rejects candidates on **1-2 sim screening noise** (one unlucky race → auto-reject a good candidate); and `max_epithet_losses=2` in screening vs comfort requiring 0 can cache a policy that drops epithet G1s live. **CLAIMED — needs verification.** Matches the observed "no candidate saved" calibrate behavior. | To verify |
| AUD-6 | MED | race_sim.py:96,107-109 | `hp_drain_scale=1.3` + aggregate skill model (per_skill_velocity 0.20) are PROVISIONAL fits to 51 fields, comment says "re-fit once per-phase skill procs land" — no re-validation marker. Affects every race time. **Known calibration debt (real, low-urgency).** | Noted |
| AUD-7 | — | mant.py:4099 `_threshold_deficit_bonus` | Agent claimed it's an INERT stub → **REJECTED (FALSE):** it's a full impl (cache→scaled pressure→cap 0.32 at 200pt deficit), the strongest race-floor lever. | Rejected |
| AUD-8 | — | race_sim.py:171-175 wit randomness | Agent claimed mod_max goes negative for low wit → **REJECTED (FALSE):** `math.log10(max(1.0, wit*0.1))` guard prevents negativity. | Rejected |
| AUD-9 | MED | race_success_feedback.py:334 | `_race_effort_score` uses flat 120 SP/skill cost → biases `efficient_win_profile` toward low-skill runs (real skills cost 3-10 SP). **CLAIMED — needs verification.** | To verify |
| AUD-10 | LOW | items.py (cupcake/buff double-path) | Multiple item-decision pathways can select the same item; `_merge_targets` dedups so it's cosmetic/debuggability, not a functional double-buy. **CLAIMED — low impact.** | Noted |

**Verification scorecard (batch 1):** of agent "CRITICAL/HIGH" claims spot-checked, ~50% were real, ~50% hallucinated/overstated. Every claim below the verified ones is tagged "needs verification" and will NOT be treated as fact until checked against code.

### Batch 2 findings
| # | Severity | File:line | Problem | Status |
|---|---|---|---|---|
| AUD-11 | HIGH | main.py:1331-1390 `best_known_headless_auth_seed` | **VERIFIED — root cause of the 7 failing `test_version_seed_freshness` tests.** Candidate loop takes the FIRST non-placeholder app_ver/res_ver (cache is candidate #1), and the version check (1361-1390) only compares the seeded value to the *default* — never candidate-vs-candidate. So cache `1.22.1` wins over a fresher profile `1.23.0`. **FIX:** select the NEWEST version across all candidates (sort by `_version_tuple(app_ver)` desc, or track max), keeping app_ver+res_ver as a matched pair. **VSC/auth-station domain (their recent commits b2cfe2a..545301f caused it) — documented, not edited by me.** | Documented (VSC) |
| AUD-12 | HIGH(sec) | main.py:8062-8063, 10625-10636, 7470/8615 | Plaintext Steam creds in reusable_auth_profiles.json; path traversal in `/assets/data/{file}` & `/races/{file}` (no `.resolve()`/bounds check); race conditions on `active_client`/`active_loop` globals (no lock). **Matches the prior security-isolation audit.** VSC/backend domain. | Documented |
| AUD-13 | HIGH | runner.py:2056 | Continued-race result loss: if `_run_continued_race` succeeds but `_race_result_from_response` returns `{}`, `race_result = new_result or race_result` keeps the PREVIOUS (losing) result → learning records a win as a loss. **Affects LEARNING DATA (my domain) though code is in runner.** NEEDS VERIFICATION. | To verify |
| AUD-14 | MED | runner.py:486, 2651, 4488 | Silent `except: pass` on crash-log write, race-attempt-ledger write, and pre-race state reload → blind operator + missing learning signal. Real but defensive (add logging). | To verify/fix |
| AUD-15 | MED | career_simulator.py:407 `_load_json_data` | Silent fallback (`{}`/`[]`) on missing/corrupt data file → sim silently degrades to synthetic with no loud warning (only `fidelity_warnings`, "rarely read"). If `real_training_snapshots.json` is gone, the whole replay path silently disables. **My domain — add a loud warning / integrity check.** | To fix |
| AUD-16 | MED | tools/extract_game_data.py, build_event_id_index.py | Data-import fragility: hardcoded gametora/wiki URLs, broad `except: pass` drops a card's events silently, unknown effect_id (117+) silently dropped (no "unknown effect type" warning) → truncated support data. | To verify |
| AUD-17 | HIGH | tests/ coverage | No FastAPI endpoint integration tests; no race-prediction-vs-real-outcome validation test; no test of the replay-vs-formula decision or the optimizer candidate→winner flow. Top missing tests for the high-value paths. | Backlog |
| AUD-18 | MED | career_simulator.py:4145 | Snapshot pool size `min(40, max(8, len(scored)//20))` → as few as 8 distinct snapshots/turn → overfit to local deck clusters; weak diversity for rare decks. | To verify |

---

## §Bottlenecks

### BN-1 (THE big one): the default sim REPLAYS the bot's own tiles ×1.85 — it cannot represent SS
**Grounded:** `_make_training_commands` (career_simulator.py:4282): if `sim_formula_training_gain` is
False (DEFAULT), it calls `_make_real_training_commands` which replays a matched real snapshot's tile
*structure* but **multiplies the stat gains by `_real_training_gain_scale()` ≈ 1.85** (4197/4202/4251).
The code's own comment (4276-4281): replay *"structurally cannot represent the high-facility/stacked-
rainbow tiles that good (manual) play uses to reach SS — which capped the optimizer at the bot's own
mediocre envelope."* So **the optimizer searches inside the bot's historical tile distribution** — it
can reorder/retime tiles but cannot discover the higher-gain tiles that manual SS play uses. This is
why the sim sits at ~4085/S+ (matching the *bot*, not the deck's ~4,879 manual potential) and why
calibrate candidates top out ~4,559. It's a calibration fudge (1.85) on a structurally-capped replay.

**The escape hatch already exists:** `sim_formula_training_gain=True` switches to the mechanical
formula path (`_support_training_gain` — the **uma.guide resolver I validated to the exact integer**:
NTR+Matikane 100/42/10/-27, Shinko+KSB 38/20). Formula mode can represent ANY tile config (high
facility + stacked rainbows) → can represent SS. It's default OFF pending career-level validation.

> **This reframes the resolver work: it is NOT inert — it is the enabler for an SS-capable sim.**
> The resolver is inert only in the DEFAULT (replay) mode; in formula mode it IS the training engine.

### BN-1 RESOLVED-IN-PRINCIPLE (deep dig 2026-06-14): formula mode is faithful; the gap is the ITEM ECONOMY
**User's actual design intent (corrected):** the sim should generate its OWN original career from first
principles (formula), NOT replay the bot's tiles. Replay was a wrong turn. So formula mode must be THE engine.

**Deep instrumented findings (real deck, account_b):**
1. A from-scratch formula career produces the RIGHT PROFILE (deck-driven: speed/wit/power high, guts/stamina
   low — matches the real careers' shape) because tiles for stats with no rainbow card stay low-gain. The
   facility model is FAITHFUL (`level_up_every_uses=4` == sim `picks//4`; `level_multipliers` all 1.0).
2. But the MAGNITUDE was low: **stat_sum 3326-3446 vs real 4111** — and forcing the policy to diversify
   barely helped (the profile is correctly deck-driven, not a policy bug).
3. **Root cause MEASURED:** the formula career applied a megaphone/anklet boost on **3 of 45** training
   turns (1 megaphone use) — real play (esp. summer camp) uses them heavily; the ×1.85 replay had that
   baked in. Forcing realistic item usage:
   - formula + 60% megaphone every train → **stat_sum 4133 ≈ real 4111** (PROP-2 career-validated!)
   - formula + 110% mega+anklet every train → **4423**, toward manual SS 4879.
**Conclusion:** the formula sim is faithful; the replay ×1.85 was compensating for a broken sim-side ITEM
ECONOMY (the bot doesn't buy/use training megaphones). Fix the item economy → formula mode matches real →
optimizer in formula mode can push to SS. **This is the concrete, data-proven path to the user's vision.**

**Implementation plan (replaces/sharpens PROP-1/2):**
- (a) Fix the sim's item-buy/use policy so it buys + applies summer megaphones + anklets on training turns
  to realistic uptime (the 3346→4133 lever). Root-cause the under-buying in items.py first.
- (b) Make `sim_formula_training_gain` the default (deprecate the replay path) once (a) lands and the
  formula career reproduces ~4111 with the *real* item policy (not forced).
- (c) Run the optimizer in formula mode → it finds the policy (rainbow timing, facility build, item timing)
  that pushes 4133 → SS, which replay structurally could never represent.

**Item-economy root cause (fully nailed, 2026-06-14):** over a full formula career the buy policy
(`_maybe_buy_shop_items`:4964) acquires **1 megaphone, 0 anklets, 64 other items**. Two compounding
causes: (1) it samples from `_observed_item_counts("bought_by_turn_bucket")` = **the bot's own purchase
history** (circular — the mediocre bot under-bought megaphones, comment 4981-4985); (2) even the
`sim_use_shop_refresh_pools=True` real-pool path didn't help (flip test: 3433 vs 3446) because buying is
**volume-limited random sampling** (1-2 items/turn @ 42% from many types) — megaphones are rarely drawn.
The USE logic (`_maybe_use_training_items`:5152) already applies a megaphone on strong/summer tiles IF
owned — so the fix is purely **deliberate acquisition**: buy megaphones (tier by phase, max in summer)
+ the deck's primary-stat anklets for strong/summer training turns, budgeted by mant_coin. That alone
should move the formula career 3446 → ~4111 with the *real* item policy (no forcing). THE SAME
replay-the-mediocre-bot disease as BN-1, in the item economy. **Both must be flipped to real/formula for
the from-scratch sim the user wants.**

### Next concrete implementation (sharpened, data-proven)
1. **Deliberate training-item acquisition** in `_maybe_buy_shop_items` (the 3446→~4111 lever) — verify it
   reproduces real magnitude with the REAL (non-forced) policy.
2. **Flip `sim_formula_training_gain` default on + deprecate the training-tile replay** once (1) lands and
   formula+real-items ≈ 4111. (Keep events + race-opponent fields as game-side data — those aren't the
   bot's behavior, so they're legitimate to keep.)
3. **Run the optimizer in formula mode** (PROP-1) — now it can discover SS policies (4133→4423→4879).
4. Then PROP-3 (manual-imitation prior) to anchor it to better-than-bot decisions.

_(other bottlenecks appended from agent reports)_

---

## §Sim→better-bot proposals

> In-depth, data-backed. Each: claim → grounding → mechanism → expected impact → risk.

### PROP-1 (highest leverage): run the OPTIMIZER in formula mode to break the replay cap
**Claim:** The single biggest reason the bot can't be optimized to SS is BN-1 — the default sim
*replays the bot's own historical tiles ×1.85*, so the optimizer searches inside the bot's mediocre
tile distribution and structurally cannot discover the high-facility/stacked-rainbow tiles that manual
SS play (~4,879 stat_sum) uses. `sim_formula_training_gain=True` switches to the mechanical formula
(the uma.guide resolver, validated to the exact integer) which can represent ANY tile.

**Grounding:**
- `_make_training_commands` (career_simulator.py:4282) gates replay vs formula; comment 4276-4281 admits
  replay "capped the optimizer at the bot's own mediocre envelope."
- Resolver tile-accuracy: validated (NTR+Matikane 100/42/10/-27, Shinko+KSB 38/20; `test_uma_guide_training_resolver.py`).
- **Measured (this audit):** formula vs replay career aggregate on the real deck with a weak preset =
  2776 vs 2796 — i.e. formula mode is **career-consistent with replay** (not inflated), so flipping it
  on doesn't desync the sim; it just removes the structural ceiling.

**Mechanism:** (1) Career-validate formula mode against a *known policy's live careers* (run formula
mode with the learned preset; confirm stat_sum tracks the real ~4111 — the weak-preset 2776≈2796 is a
good first signal). (2) Then run `optimize_deck_policy.py`/`calibrate_deck.py` with
`sim_formula_training_gain=True` so candidates are evaluated on the SS-capable sim. (3) The optimizer
can now reward policies that build facilities + stacked rainbows + train them — which replay scored as
impossible. Pair with the winning-profile levers (5fcb30f + AUD-1) so it targets *winning* builds.

**Expected impact:** unlocks the optimizer's ability to find SS/epithet-winning policies at all — this
is the difference between "optimize within mediocre" and "discover better-than-manual." Without it, no
amount of lever-tuning escapes the ~4,085/S+ replay ceiling.

**Risk:** formula mode is tile-accurate but its *career aggregate* under a strong policy is unproven vs
live (you can't validate a policy live that the bot has never run). Mitigation: validate the *known*
policy first; cross-check the formula career's per-turn tile gains against the matched real snapshots
(should agree where they overlap); keep replay mode as the live-fidelity reference.

### PROP-2: career-validate formula mode, then optimize-in-formula → validate-live (the safe rollout of PROP-1)
**Claim:** PROP-1 (optimize in formula mode) is only safe if formula mode's *career aggregate* is trusted.
The validation path is concrete and cheap.
**Grounding:** resolver tile-accuracy is proven; replay≈formula at the career level for a weak policy
(2776≈2796); the comment at career_simulator.py:4280 names the exact gate ("validate against the game
table + manual career end-states"). Manual SS careers hit ~4,879 (memory `project_sim_calibrated_to_mediocre`).
**Mechanism:** (a) Run formula mode with the *current learned preset*; confirm stat_sum tracks the real
~4,111 (per-turn tile gains should agree with the matched real snapshots where they overlap — write a
diff harness over `real_training_snapshots`). (b) Reconstruct one **manual** SS career's per-turn tile
sequence and feed it through formula mode; confirm it reproduces ~4,879 (proves the formula CAN represent
SS — the thing replay can't). (c) Only then flip `sim_formula_training_gain` default on and re-baseline
the handful of tests that pin replay numbers. **Impact:** turns PROP-1 from "plausible" into "validated."
**Risk:** if (b) under-shoots 4,879, the formula/energy/mood terms still have a gap → fix those *before*
flipping (this is where the deferred energy/failure work would re-enter, but now with a clear target).

### PROP-3: a manual-imitation prior — learn the user's winning DECISIONS, not just outcomes (directly: "beat my manual play")
**Claim:** The sim↔live gap for the user's deck is **decision quality**, not training math (replay already
matches live stats; the bot lands 4,111 vs manual 4,879 on the *same deck*). The fastest way to close it
is to learn what the *user* does differently, turn by turn.
**Grounding:** decision parity verified (live+sim share `MantStrategy`); manual careers exist
(`uma_runtime/instances/account_b/manual_career_logs/`); an imitation scaffold already exists
(`runner._rebuild_imitation_archive`, line 549) but is outcome-keyed, not decision-keyed.
**Mechanism:** extract per-(turn, state-bucket) manual DECISIONS (which tile/race/skill/item) from the
manual career logs; build an **imitation prior** that adds a score bonus in `MantStrategy._score_command`
when the bot's choice matches the manual choice in a similar state — weighted by how much better the
manual careers did. Expose the weight as a tunable so the optimizer balances imitation vs exploration.
**Impact:** the optimizer is no longer searching blind — it's anchored to a known-better policy and only
explores *around* it. This is the single most direct mechanism for "legit better than me": start from
imitating the user, then let the sim find improvements the user didn't try. **Risk:** manual logs are
sparse (few careers); state-bucketing must be coarse enough to generalize. Mitigation: bucket by
(phase, facility-levels, top-deficit-stat); fall back to the existing policy when no manual analog exists.

### PROP-4: unify the two optimizers' search space + objective (closes AUD-1/AUD-2 permanently)
**Claim:** Two optimizers (`calibrate_deck.py` SS-rate+veto vs `optimize_deck_policy.py` clean_rate) with
**separate** candidate generators caused AUD-1 (a lever added to one, missing from the other). They should
share one search space and a single coherent objective.
**Grounding:** AUD-1 (verified) — the winning-profile levers were absent from the auto loop's PARAM_SPACE
for months; the clean_rate objective (optimize_deck_policy.py:194) is well-designed and should be canonical.
**Mechanism:** extract one `PARAM_SPACE`/bounds module imported by both; adopt a single lexicographic
objective = (clean_rate → SS-rate → mean rating) so it rewards *winning races first, then reaching SS*.
**Impact:** every future lever reaches both paths automatically; the manual + auto loops converge on the
same definition of "better." **Risk:** low (refactor + re-run both test suites); the objectives must be
reconciled carefully (the SS-veto is stricter — keep it as a *gate* on top of the shared objective).

### PROP-5: make race-floor pressure start earlier + give stamina a late knob (AUD-4)
**Claim:** Long G1 losses need stamina/power built *before* the race, but the winning-profile demand only
looks 8 turns ahead and stamina has no late-game priority lever.
**Grounding:** real winning profiles need +44-48 stamina + +30-78 power for the long G1s (audit data);
`upcoming_race_success_demand` lookahead=8 (race_success_feedback.py); stamina lacks a `_late` param (AUD-4).
**Mechanism:** (a) scale the demand lookahead by the deficit size (a 200pt stamina gap for a t56 race needs
~15 turns of lead, not 8); (b) add `stamina_priority_bonus_late` to mant + both search spaces. **Impact:**
the bot builds the balanced stat line *in time* instead of being pressured too late. **Risk:** longer
lookahead can over-pressure early; cap it and let the optimizer tune the new levers.

### PROP-6: value race-winning SKILLS in the sim so the optimizer learns to buy them
**Claim:** Medium/mile G1s are won by **more skills** (+1.3 to +2.2 vs losers), but the sim's skill-value
model is parent-memory-calibrated to rating, not to *winning specific races*.
**Grounding:** audit winning-vs-losing data (Takarazuka +1.3, Victoria +1.4, QE II +2.2 skills); skill
buying flows through `calendar_race_prebuy_*` + `_buy_*_skill_for_race` (runner).
**Mechanism:** derive per-race "skill demand" from the winning corpus (which skill *categories* — recovery/
speed/accel — winners of each race carried) and feed it into the pre-race skill-buy scoring, so the bot
buys race-relevant skills, and the optimizer can weight it. **Impact:** directly attacks the medium/mile
losses that aren't pure stat gaps. **Risk:** skill data quality; start with skill *categories* not IDs.

### PROP-7: Monte-Carlo robust scoring in the optimizer (don't ship brittle per-seed winners)
**Claim:** The sim is largely deterministic per seed; live has RNG (training fails, mood dips, skill procs,
race variance). A candidate that wins on seed K may be brittle.
**Grounding:** `optimize_deck_policy` already runs 32 validation sims but scores by mean; the audit found
the sim's stochastic surface (failures, rest mood, event tiebreak, race wit-band).
**Mechanism:** score candidates by `mean − k·std` (or clean_rate at the 25th percentile) across seeds, so
the saved policy is robust, not lucky. **Impact:** policies that hold up live, fewer "looked great in
calibrate, lost live" surprises. **Risk:** needs enough seeds (cost); pairs naturally with PROP-1 (formula
mode adds real per-tile variance to make multi-seed meaningful).

### PROP-8: race-model recalibration against the 9,780-sample corpus (so the optimizer targets winnable builds)
**Claim:** The binding constraint is *races* (epithet losses), so the race outcome model must be accurate;
its key constants are provisional fits to only 51 fields.
**Grounding:** AUD-6 — `hp_drain_scale=1.3`, `per_skill_velocity=0.20` fit to 51 fields, comment says
"re-fit once per-phase skill procs land"; `real_race_snapshots.json` now has **9,780** result samples +
51 fields. **Mechanism:** build a calibration harness that fits the physics constants to the full result
corpus (predicted vs actual win/loss + finish rank), track fit-quality (win-match %, rank error) with a
date stamp, and re-fit on a cadence. **Impact:** the optimizer's "will this build win race X" signal
becomes trustworthy → it targets genuinely winnable builds instead of over/under-preparing. **Risk:**
over-fitting to account_b's field; hold out a validation split.

### Secondary / hygiene (still grounded)
- **Unify + de-dupe** the dead `_race_hard_stat_floor_bonus` (AUD-3) and document the 3 race-pressure
  levers (threshold-deficit 0.32 / race-success 0.45 / postmortem-demand 0.40) in one place — they
  currently overlap with no single owner.
- **Coverage self-check** (AUD-18): warn when the replay pool for a turn/deck is < ~15 snapshots (overfit
  risk) so the operator knows the sim is extrapolating.
- **Test the high-value paths** (AUD-17): replay-vs-formula decision, optimizer candidate→winner, and a
  race-prediction-vs-real-outcome regression — none exist today.
- **VSC-domain (flagged, not mine to fix):** AUD-11 version-freshness (the 7 red tests — exact fix
  documented), AUD-12 security (plaintext creds / path traversal / global races), AUD-13 continued-race
  result-loss.

### Recommended execution order (by leverage)
1. **PROP-2** (validate formula mode) → **PROP-1** (optimize in formula mode) — unlocks SS at all.
2. **PROP-3** (manual-imitation prior) — the most direct "beat manual" mechanism.
3. **PROP-8** (race-model recalibration) — makes the race signal the optimizer trusts accurate.
4. **PROP-4** (unify optimizers) + **PROP-5/6** (race-floor timing + skills) — targeted win-rate gains.
5. **PROP-7** (robust scoring) — lock in policies that survive live RNG.

---

## SS Reachability — Grounded Diagnosis (2026-06-14, FORMULA mode)

Established the from-scratch formula sim (`sim_formula_training_gain=True`) computes decisions via
`MantStrategy` (verified: `_score_command` fires ~1821×/career; the gain *and* decision replay paths
are both off). All numbers below are formula-mode careers on the real-account 6-speed deck.

**1. The rating curve is strongly CONVEX (rating.py `stat_rating_score`).** +100 of a stat is worth
+270 rating at 400, +536 at 1000, **+748 at 1150**. Therefore a skewed build beats a balanced one at
equal sum (9729 vs 8740 at sum 3915), and the SS-optimal shape is **the top 3-4 stats pushed as high
as possible** (one stat caps at STAT_CAP=1200). Confirms the `project_ss_sim_tuning` convexity note.

**2. The SS recipe (math + a real career, both agree).** SS = rating ≥ 17500.
`estimate_rating_score`: speed 1200 + power 1200 + stamina 900 + wit 700 + guts 400 (=4400) + skill
5800 → **18,071 = SS**. The peak real career in `real_training_snapshots` on a **6-speed deck** hit
**4901**: speed 1161 / power 1114 / **guts 1200** / wit 829 / stamina 597 — i.e. 3-4 high stats, the
convex shape. So SS is genuinely reachable on the production deck. NOT impossible.

**3. The bot caps at S+ (~16,700), and the gap is THROUGHPUT, not allocation.**
- A tuned cap-targeting policy reaches stat_sum ~4100, rating ~16,700 (best seed), 0/N SS — building
  only speed+power high, guts/stamina/wit low.
- **Forcing guts allocation FAILS the right way:** forcing guts tiles to win builds guts to ~900-1000
  but *drops* total to 3094-3500 and rating to ~12,000. On a no-guts deck, guts training is low-value
  (~10/train) vs rainbow speed (~50/train). Spending turns on guts sacrifices more than it adds. This
  proves the bot is **total-stat-throughput limited** (~4100 points) — it can only afford to push 2
  stats into the convex zone. The manual generated ~4900 points → could push 3-4.

**4. Where the ~800-point throughput gap lives (manual 4901 vs bot formula career).**
| driver | manual 4901 | bot formula | lever |
|---|---|---|---|
| rainbow-ready bonds (≥80) | 7-8 (all maxed) | 5 | junior_bond_build / near-rainbow targeting |
| energy use | avg vital ~39 (grinds) | rests more (higher vital) | rest_threshold (with failure safety) |
| wit (→ SP → skills) | 829 | ~630 | wit priority → more SP → +~700 skill rating |
| item (megaphone) uptime | heavy | ~11/career, ~110-290 coin left unspent | shop reserve target ↑ within coin |

**Per-tile gain is validated-exact (uma.guide resolver: 100/42/10/-27), so this is a policy/play-quality
gap, NOT a gain-scale calibration problem.** The current strategy, even optimally tuned within the
existing PARAM_SPACE, tops out at S+ — reaching SS requires *improving play-quality throughput*
(faster full-bond-building, aggressive-but-safe energy, more wit/SP for skills, max item uptime), which
is exactly the "beat manual" core. Item economy (post-race drops + shop buying from `shop_refresh_pools.json`)
shipped this pass (commit c2c2a80). Remaining SS work tracked as the throughput-gap task.

**DO NOT** "reach SS" by inflating gains or forcing a stat distribution — both are unfaithful and were
shown to be rating-negative or fabricated. SS must come from the bot generating manual-level throughput.

---

## Item economy rework — free grant → coin-bounded post-race shop (2026-06-14)

**Bug the user caught:** `_grant_post_race_items` treated the shop_refresh_pools.json
`race` pool `expected_copies_by_grade_result` as FREE drops — minting ~6 Empowering
Megaphones + ~41 total items/career with no coin cost (peaked at 8 items from one race).
But every race-pool row also carries `avg_price_by_grade_result` + `appearance_rate` —
these are post-race SHOP items you BUY with coins, not gifts (confirmed by real ground
truth: items have buy_events; Coaching Megaphone shop_seen=1722 / bought=0).

**Fix (commit pending, local):** deleted the free grant; added `_offer_post_race_shop`
— rolls each item's real `appearance_rate_by_grade_result` into a ~2-slot offer at its
real `avg_price`, then BUYS within `mant_coin` by a priority that mirrors the live bot +
the measured real per-career profile (energy → deck anklet → late-game hammer → megaphone
[reserve-capped] → target-stat study → mood). Imports `NEVER_BUY_ITEMS` from items.py and
guards ALL THREE buy paths so the 20% Coaching Megaphone (8001) + Energy Drink MAX EX are
never bought (real parity). Every bought consumable flows through the existing `_use_item`
effects (no new effect wiring needed). Regression test: tests/test_sim_item_economy.py
(Coaching never bought, coin never negative, post-race buys always cost coins, energy is
acquired, megaphones don't stockpile).

**Real per-career profile (639 careers, the faithful target):** Vita energy 3.9 buy/5.3 use
(#1), each color Manual ~2.5, Cleat Hammers ~1.75, Speed Ankle ~1.6, Motivating Megaphone
1.36, Empowering 0.88; stat-study is the dominant category; ~1,266 coin spent/career.

**OPEN — coin-income calibration (flagged, NOT fudged):** the sim earns **~2,320 coin/career**
vs real **~1,377** (real keeps a stable ~150-235 balance, ends ~111). Traced to the bot
running **26 G1 races/career** (catalog type really is G1 — not a grading bug), each paying
`_race_coin_reward` G1=95. The over-income makes the (now coin-bounded) buy paths over-buy
~1.8× across the board (stat-study 43 vs ~20, energy 18 vs ~7, megaphone 5 vs ~2). This is
a coin/race-calendar calibration, separate from the item-logic fix: needs verifying whether
real careers run that many G1s and whether G1=95 is the cited MANT reward before changing
anything. Do NOT mask it by throttling buys — the buys auto-correct once income is right.

---

## Authoritative Trackblazer item table + sim modeling (2026-06-14)

Source: Game8 "List of All Trackblazer Items" (verified against real-capture
effect_type codes: 11=multi-turn train%, 12=anklet energy, 14=race-reward).
The user flagged that items were mis-modeled / Reset Whistle wrongly excluded.
Every item is now ACCOUNTED FOR in career_simulator.py with its real effect:

| Item (id) | Real effect | Sim modeling |
|---|---|---|
| Notepad/Manual/Scroll (1001-1205) | +3/+7/+15 stat | STAT_ITEM_GAINS (exact) |
| Vita 20/40/65 (2001-2003) | +20/40/65 energy | ENERGY_ITEM_IDS (exact) |
| Royal Kale Juice (2101) | +100 energy, -1 mood | energy + mood-1 (fixed) |
| Energy Drink MAX (2201) | +4 max energy, +5 restore | max+restore (fixed; was +30) |
| Plain/Berry Cupcake (2301/2302) | mood +1/+2 | MOOD_ITEM_GAINS |
| Megaphones (8001-8003) | +20/40/60% train (4/3/2 turns) | megaphone addon (exact); 8001 NEVER_BUY |
| Ankle Weights (9001-9004) | +50% train, +20% energy | ankle addon (exact) |
| Training Application (5001-5005) | facility level +1 | TRAINING_APP_ITEMS facility boost |
| **Grilled Carrots (3101)** | **all supports bond +5** | BOND_ITEM_GAINS all+5 (was mood) |
| **Yummy Cat Food (3001)** | **director bond +5** | BOND_ITEM_GAINS director+5 (was mood) |
| **Cleat Hammer A/M (11001/11002)** | race stat **+20%/+35%** | RACE_REWARD_BUFF 1.20/1.35 (was 1.12/1.25) |
| **Glow Sticks (11003)** | **race FAN +50%** | _race_fan_reward ×1.50 (was stat ×1.08) |
| Good-Luck Charm (10001) | training failure 0% this turn | good_luck effect |
| **Reset Whistle (7001)** | **rearrange training partners** | one-turn train-% uplift (re-roll proxy, tunable) — was EXCLUDED |
| Pretty Mirror/Scholar's Hat/Tips/Binoculars | **skill hints** (Charming/Fast Learner/…) | SKILL_HINT_ITEMS map — effect wiring is a FLAGGED follow-up (was mis-modeled as mood) |
| Cures: Practice Drills DVD/Pocket Planner/Smart Scale/Rich Hand Cream/Aroma Diffuser/Fluffy Pillow/Miracle Cure | cure a bad status | NO-OP — sim has no bad-status model; FLAGGED follow-up |

**Two remaining sub-models (flagged, not fudged):** (1) skill-hint items → wire each
named skill's SP-cost discount / acquisition into the skill-purchase path; (2) a
bad-status model (Night Owl/Slacker/etc. occur, reduce training, cured by the
matching item) so the 7 cure items become meaningful. Both need their own data
(skill IDs/values; real bad-status occurrence rate from captures) before modeling.

**Reset Whistle** is now bought (tier-1, like the live bot) and used on strong
training turns; its re-roll is modeled as a bounded, preset-tunable one-turn
training uplift (sim_reset_whistle_train_pct) pending a full per-tile partner
re-roll. **Calibration note:** Grilled Carrots is offered (~46%) but under-bought
on this deck due to early-career coin scarcity (bonding useful early when coin is
low); ties into the coin-income flag above.

---

## Placement-based coin + win-rate finding (2026-06-14, user-directed)

**Coin reward is by FINISHING PLACEMENT, not win/lose.** User: ~100 (1st), ~55
(2nd), ~30 (3rd), tapering below. The old `_race_coin_reward(grade, won)` used
grade x0.45 for any non-win — flattening 2nd and 5th to the same ~43 coin and
over-paying losses. Fixed: takes `finish_rank` (the sim already computes it via
`_sim_loss_finish_rank`) and pays {1:100, 2:55, 3:30, 4:18, 5:10, 6+:5} (+20 rival
win). This is why a live bot that LOSES races earns less coin than an all-wins sim.

**Residual coin gap is now the WIN RATE, not the coin formula.** With placement
coin, sim income is still ~2,122/career (real ~1,377) because the sim bot WINS
~69% of races (18-23 of ~29). To match real ~1,377 the bot should win ~10/career,
i.e. lose far more. The sim's win probability is optimistic for mediocre statlines
(it wins most G1s with A+ stats) — a RACE-MODEL calibration (see race physics
engine), separate from the coin formula. Flagged, not fudged.

## STOP reporting stat_sum — report the STATLINE + rating/rank (user-directed)

stat_sum is misleading because the rating curve is convex: 4,000 sum as 800x5 vs
1000x4+0 give very different ranks. Always report the per-stat line
(speed/stamina/power/guts/wit) + rating + rank. Reporting this way immediately
exposed that the BUG-FREE item economy yields A+/A (sp~900/st~580/pw~730/gu~390/
wt~650, ~12-13k) — NOT the S+ the buggy free-megaphone+fake-mood economy faked.
No statline is in the 1100-1200 rank-earning zone. The honest corrected sim is
weaker than the buggy one; reaching real-bot S+ (let alone SS) must come from
legitimate item/training value (megaphone uptime, bond rainbows), not the bugs.
