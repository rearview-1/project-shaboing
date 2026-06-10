# Audit #2 — Training Execution Layer

**Date:** 2026-06-10
**Scope:** Read-only audit of the bot's training-tile decision logic in
`career_bot/scenarios/mant.py`. Traced from `next_decision` through
`_score_command` to identify where preset values translate (or don't)
into bot behavior. Did not modify any code.

## Files / functions examined

All in `career_bot/scenarios/mant.py`:

- `next_decision()` (line 486) — top-level decision dispatch
- `_make_training_commands` / `_pick_training_command` (called from `next_decision`, lines 1220-1300+)
- `_score_command()` (line 2594) — composite tile scorer
- `_stat_priority_bonus_generic()` (line 4442) — stamina/power bonuses
- `_stamina_priority_bonus`, `_power_priority_bonus` (lines 4493, 4504)
- `_per_stat_soft_cap()` (line 4760) — distinct cap-policy function (touched this session)
- Module-level constants at lines 375-380

## High-level flow

```
next_decision()
  └─ build enabled[] from data.home_info.command_info_array
  └─ training = [cmd in enabled if cmd is a TRAINING command]
  └─ scored = [(_score_command(cmd, …), cmd) for cmd in training]      (line 1232)
  └─ T48-72 dampener: highest-stat tile *= 0.95                          (line 1233-1236)
  └─ _apply_bond_equity_gate(scored, …)                                  (line 1237)
  └─ _apply_imitation_prior(scored, …)                                   (line 1238)
  └─ best = max(scored) → Decision                                       (line 1250)
```

## `_score_command` bonus stack

`_score_command` builds a single scalar by combining ~37 additive/multiplicative signals.
Order matters — multipliers applied later affect everything added earlier.
Listed in the order they execute:

1. base score per stat (preset.base_score[idx])                              line 2600
2. per-partner bond yield (decayed by turn; pal_score, npc_score, lv1→lv2)   line 2614-2649
3. hint count → `+ w_hint` if any tipset partners                             line 2650-2651
4. per-stat-gain term: `value * stat_value_multiplier[target]`               line 2652-2666
5. stamina-only multiplier: `stamina_demand_multiplier(style, distance, …)`  line 2667-2672
6. **soft/hard cap taper** on stat gain                                       line 2680-2688
7. **`expect_attribute` ratio piecewise taper** (8 tiers)                     line 2689-2710
8. `_knowledge_multiplier` on the stat gain                                   line 2711
9. pal_count multiplier (preset.pal_card_multiplier)                          line 2713-2714
10. solo-tile penalty (`-= 0.20` if 0 partners)                               line 2722-2725
11. failure-rate penalty (compensate_failure)                                 line 2726-2727
12. rest-tile vital handling (idx==4)                                         line 2728-2739
13. `extra_weight` (preset.extra_weight[idx][turn-band])                      line 2740-2750
14. race_heavy_core_floor_adjustment                                          line 2751
15. race_heavy_training_efficiency_adjustment                                 line 2752-2755
16. deck_multipliers (turn < 60)                                              line 2757-2760
17. postmortem_training_bonus                                                 line 2766-2769
18. race_success_training_bonus                                               line 2771-2774
19. threshold_deficit_bonus                                                   line 2779-2782
20. scheduled_race_safety_training_bonus                                      line 2784-2787
21. cap_pursuit_bonus                                                         line 2792-2795
22. user_manual_target_bonus                                                  line 2801-2804
23. manual_race_specific_demand_bonus                                         line 2810-2813
24. race_hard_stat_floor_bonus                                                line 2819-2822
25. projection_tile_bonus (forward planner)                                   line 2832-2835
26. trajectory_training_bonus                                                 line 2837-2842
27. near_rainbow_training_bonus                                               line 2850-2853
28. lagging_bond_partner_bonus                                                line 2859-2862
29. first_summer_friendship_bonus                                             line 2863-2866
30. facility_level_training_bonus                                             line 2867-2870
31. desired_parent_spark_training_multiplier (computed, applied at end)       line 2872-2874 + 2942-2943
32. speed_priority_bonus                                                      line 2878-2881
33. wit_priority_bonus                                                        line 2883-2886
34. target_closeout_bonus                                                     line 2888-2891
35. stamina_priority_bonus                                                    line 2900-2903
36. power_priority_bonus                                                      line 2904-2907
37. checkpoint_pressure_bonus                                                 line 2910-2913
38. race_heavy_lane_balance_bonus                                             line 2915-2918
39. stat_concentration_bonus (× projected_overcap_multiplier)                 line 2931-2936
40. learned_policy_bonus (training_policy_model output)                       line 2938-2941
41. spark_goal_mult applied as final multiplier                               line 2942-2943

## Observations

### Obs 1 — Soft-cap taper becomes a hard cliff when soft_cap == hard_cap

**Location:** `_score_command` lines 2682-2688

**What the code does:**
```python
soft_cap = self._per_stat_soft_cap(target, preset, turn=turn)
hard_cap = float(_tuned_value(preset, "stat_hard_cap", 1200.0))
if current_for_stat >= hard_cap:
    stat_gain_score *= 0.05
elif current_for_stat >= soft_cap:
    progress = (current_for_stat - soft_cap) / max(1.0, (hard_cap - soft_cap))
    stat_gain_score *= max(0.10, 1.0 - 0.90 * progress)
```

**Concern:** When `soft_cap` and `hard_cap` are both 1200 (operator policy this session
raised soft caps to 1200 across the board, and `stat_hard_cap` defaults to 1200), the
`elif` branch's denominator is `max(1.0, 1200 - 1200)` = `max(1.0, 0)` = `1.0`. The
`progress` term then equals `(current - 1200) / 1.0` = `current - 1200`. For
`current = 1200`, however, the `if` branch fires first (`*= 0.05`). For
`current = 1199`, neither branch fires. So the taper region is empty — the score
abruptly drops from full value to 0.05x at exactly 1200, no graceful descent. The
original cap-taper design relied on `soft_cap < hard_cap`.

### Obs 2 — `expect_attribute` controls an implicit per-stat cap via ratio taper

**Location:** `_score_command` lines 2689-2710

**What the code does:** After the soft/hard cap taper, a separate 8-tier piecewise
function scales `stat_gain_score` based on `current / expect_attribute[target]`:

```
ratio > 1.00 → 0.00x   (training value zeroed out)
ratio > 0.97 → 0.35 → 0.10x (linear interp)
ratio > 0.94 → 0.55 → 0.35x
ratio > 0.90 → 0.75 → 0.55x
ratio > 0.86 → 0.85 → 0.75x
ratio > 0.82 → 0.91 → 0.85x
ratio > 0.78 → 0.95 → 0.91x
ratio > 0.74 → 0.98 → 0.95x
ratio > 0.70 → 1.00 → 0.98x
```

**Observation:** This is independent of the soft/hard cap path in Obs 1.

The operator's preset `xguri parent.json` has `expect_attribute = [1200, 857, 1134, 1146, 1200]`
(speed, stamina, power, guts, wit). So the **effective per-stat training-value caps from
this taper alone**:

- speed: tapers to 0 above 1200 (no constraint here)
- stamina: tapers to 0 above **857**
- power: tapers to 0 above 1134
- guts: tapers to 0 above 1146
- wit: tapers to 0 above 1200

**Concern:** Stamina training value goes to zero above 857. Above ~800 it's already at
0.85x-0.91x of base. This taper is what governs the practical stamina ceiling in
training, not the soft_cap from `_per_stat_soft_cap` or any priority bonus. The session
discussion of "why doesn't stamina go past 750-800" centered on priority bonuses; the
much larger effect is this `expect_attribute` ratio taper. The taper applies before any
priority bonus is added (Obs 1, Obs 2 happen at lines 2685-2710, priority bonuses at
lines 2900+), so a stamina-priority bonus added later cannot recover the zeroed-out
stat-gain term.

### Obs 3 — Senior-year highest-stat 0.95x dampener

**Location:** line 1233-1236

**What the code does:**
```python
if 48 < turn <= 72:
    stat_keys = ["speed", "stamina", "power", "guts", "wiz"]
    highest_idx = max(range(5), key=lambda idx: int(chara.get(stat_keys[idx]) or 0))
    scored = [(score * 0.95 if TRAINING_COMMANDS.get(cmd.get("command_id"), 0) == highest_idx and score > 0 else score, cmd) for score, cmd in scored]
```

**Observation:** During Senior year (turn 49-72), the command for the *currently-highest*
stat gets a 5% score penalty. No comment in the code explaining why. Likely a
balance-shaping mechanism.

**Concern:** This fires regardless of whether the highest stat is actually being
"over-trained." If the operator's policy is "push Speed to 1200" and Speed is the
highest stat through Senior year, every Speed tile is penalized 5%. The intent
seems to be "spread training across stats" but the operator's intent may be the
opposite.

### Obs 4 — Postmortem / threshold / projection / cap-pursuit / user-manual / per-race-demand / hard-floor bonuses overlap

**Location:** line 2766-2822, line 2832-2835

**What the code does:** 7 separate additive bonuses all aim at "push the bot toward
stats upcoming scheduled races demand":

- `_postmortem_training_bonus` (cap from `postmortem_bonus_cap`, default 0.20)
- `_race_success_training_bonus` (cap from `race_success_bonus_cap`, default 0.20)
- `_threshold_deficit_bonus`
- `_scheduled_race_safety_training_bonus`
- `_cap_pursuit_bonus`
- `_user_manual_target_bonus`
- `_manual_race_specific_demand_bonus` (cap from `race_specific_demand_cap`, default 0.25)
- `_race_hard_stat_floor_bonus` (cap ~0.80 per the comment at line 2817)
- `_projection_tile_bonus` (line 2832, cap 0.10 in Phase 1)

**Observation:** Code comment at line 2832 explicitly states the projection bonus is
"designed to eventually replace the patchwork of competing priority bonuses above" but
is still in Phase 1 (additive, cap 0.10). Both the patchwork AND the projection are
currently active.

**Concern:** When multiple of these fire on the same tile (e.g., Stamina training when
Kikuka Sho is upcoming AND user has manual stamina hint AND postmortem flagged the race
AND threshold deficit AND projection), the bonuses sum. The operator presumably tuned
the individual caps for use in isolation; their combined behavior is the sum, not the
max. Did not measure typical combined magnitudes against the base score.

### Obs 5 — Stamina/Power priority bonus only fires below floor_target

**Location:** `_stat_priority_bonus_generic` lines 4477-4491

**What the code does:**
```python
target_floor = float(_tuned_value(preset, "<stat>_floor_target", default))
…
current = float(self._current_stat(chara, stat_index) or 0.0)
if current >= target_floor:
    return 0.0
```

For stamina: `target_floor` default is `_STAMINA_FLOOR_TARGET = 650.0`.
For power: `target_floor` default is `_POWER_FLOOR_TARGET = 800.0`.

**Concern (numeric):** With user's preset `stamina_floor_target = 750` and operator
policy correction this session raised it to 1000, the stamina priority bonus fires
while current stamina < 1000. The bonus magnitude is
`base_bonus + deficit_boost * (1 - current/floor)` where `base_bonus` and
`deficit_boost` ceilings in TUNABLE_PARAMS are both 0.08. Maximum bonus when
current=0 is 0.16. Maximum bonus when current=750, floor=1000:
`0.08 + 0.08 * (1 - 750/1000) = 0.08 + 0.02 = 0.10`.

This bonus is added at line 2900-2903, AFTER the `expect_attribute` ratio taper at
line 2689-2710 has potentially scaled the underlying `stat_gain_score` to a small
value (Obs 2). When `expect_attribute[stamina] = 857`, the taper at stamina=750
multiplies the stat gain by ~0.95 (still close to full). When stamina=857, the
taper multiplies by ~0.35. The priority bonus is a flat 0.08-0.10 added on top, not
proportional to the base score. So in the "stamina near 857" region, priority bonus
0.10 is comparable to base stat-gain-score ~0.35 — competitive.

### Obs 6 — `stat_value_multiplier` is a per-stat scalar that gates everything

**Location:** line 2605, line 2666

**What the code does:** `stat_mult = preset.get("stat_value_multiplier") or [0.01,
0.01, 0.01, 0.01, 0.01, 0.005]`. Each stat-gain term is `value * stat_mult[target]`
at line 2666. The user's preset has `stat_value_multiplier = [0.022, 0.016, 0.018,
0.012, 0.016, 0.01]`.

**Observation:** All stat-gain contributions are scaled by these per-stat
coefficients. The user's coefficients favor speed (0.022) > power (0.018) >
stamina (0.016) = wit (0.016) > guts (0.012). Speed gets ~38% more weight per unit
gained than stamina.

**Concern:** This is a fundamental weighting that affects all training scoring. Not
listed in `LEARNABLE_PARAMS` from the (now-reverted) self-learning analyzer; not in
`TUNABLE_PARAMS` in the auto-tuner. Set per-preset by the operator. May or may not
align with operator intent — depends on what the operator believes these values
encode.

### Obs 7 — `_target_closeout_bonus` and `stat_concentration_bonus` semantics

**Location:** lines 2888-2891, 2931-2936

**Observation:** `_target_closeout_bonus` (per comment at line 4515) is designed to
push the bot to close out explicit 1100+ stat targets. `_stat_concentration_bonus`
(touched this session) pushes the top-2 stats toward soft_cap.

**Concern:** Both fire at the end of `_score_command` and both target "push this stat
harder." They can compound. The `stat_concentration_bonus` is multiplied by
`_projected_overcap_multiplier` so it shrinks when the stat would overshoot, but
`_target_closeout_bonus` is not.

### Obs 8 — Solo-tile penalty is additive, not multiplicative

**Location:** line 2722-2725

**What the code does:**
```python
if partner_array_len == 0:
    solo_penalty = float(_tuned_value(preset, "solo_training_penalty", 0.20))
    score -= solo_penalty
```

**Observation:** The penalty is a flat `-0.20`. If the rest of `_score_command`
produces a score of e.g. 0.18 for a solo tile, the result is `-0.02`. If it
produces 3.5, the result is 3.30. The relative impact varies wildly with the rest
of the score.

### Obs 9 — `compensate_failure` penalty is multiplicative on the post-base score

**Location:** line 2726-2727

**What the code does:**
```python
if preset.get("compensate_failure", True):
    score *= max(0.0, 1.0 - (float(command.get("failure_rate") or 0) / 50.0))
```

**Observation:** Failure rate of 50 → score zeroed. Failure rate of 25 → score
halved. Default is enabled. Applied BEFORE all the priority bonuses at lines 2766+.
So a high-failure tile has its base score halved but then receives the full
priority bonuses on top, potentially making it competitive again.

### Obs 10 — Knowledge multiplier and stamina-demand multiplier are stat-specific

**Location:** lines 2667-2672, 2711

**What the code does:** Stamina training value is multiplied by `stamina_demand_multiplier(style, distance, recovery_count)`.
All stats are multiplied by `_knowledge_multiplier(target, chara, preset, targets, turn)`.

**Concern:** Neither function was traced in this audit (would require additional
read). Their outputs influence the relative weights of training picks. If
`stamina_demand_multiplier` returns less than 1.0 for the user's late_surger +
medium combination, stamina is further deprioritized.

### Obs 11 — Code comment acknowledges sim-only bias

**Location:** lines 2896-2899

**Comment text (verbatim):**
> "The sim's per-stat training output is biased toward speed (a known sim-only bug),
> so these bonuses cannot be cleanly tested in-sim. They're sized small (additive,
> never decay) so worst case they nudge a few extra stamina/power picks per career."

**Observation:** The operator-authored code itself states that **training output is
known to be biased toward speed in the sim**. This is highly relevant context for
the user's "sim isn't hitting SS" concern. The bias is documented but not (apparently)
quantified or addressed.

### Obs 12 — `_apply_bond_equity_gate` and `_apply_imitation_prior` modify scores after `_score_command`

**Location:** lines 1237-1238

**What the code does:** After `_score_command` produces the scored list, two
additional transforms re-weight the scores. Not traced in this audit.

**Concern:** Final winning tile may not be the highest-scored tile from
`_score_command` alone. These post-scoring transforms can shift behavior in ways
not reflected in `command["_strategy_score"]` (which is set at line 1242 from the
already-transformed score, so it does match the final used score).

### Obs 13 — Learned policy bonus is applied unconditionally

**Location:** line 2938-2941

**What the code does:**
```python
learned_bonus = score_training_policy_bonus(command, data, chara, preset)
if learned_bonus:
    score += learned_bonus
```

**Observation:** The training_policy_model produces a learned-from-past-careers bonus
applied to every command. Magnitude bounded by `training_policy_model_max_bonus`
(0.08 in the user's preset). Direction and signal source not examined in this audit.

**Concern:** This is the closest thing to "the bot learning from past careers" in the
training execution path. Its outputs are not surfaced in this audit but worth a
focused look in Audit #3 (auto-tuner / learning systems).

## What I did NOT check

- `_apply_bond_equity_gate`, `_apply_imitation_prior` implementations (Obs 12)
- `_knowledge_multiplier` content (Obs 10)
- `stamina_demand_multiplier` content (Obs 10)
- `score_training_policy_bonus` and the `training_policy_model` it reads (Obs 13)
- The 7 race-targeted bonuses individually — only their interaction surface
- `_expect_attribute_targets` reader (Obs 2 assumes it returns preset values unchanged)
- The rest, recreation, medic, race tile decision paths — only training was audited
- Skill purchase timing (could be a separate audit)
- Item usage / shop logic
- Event choice logic

## Summary

13 observations. The single largest behavioral lever the operator can pull for
"why does my deck stop at stamina 750" is **Obs 2 — the `expect_attribute` ratio
taper at lines 2689-2710 zeros out stamina training value above
`expect_attribute[stamina] = 857`** in the operator's preset. This is not the
priority bonus issue I was discussing earlier in the session; it's a separate
piecewise function that runs before any priority bonus is added.

**Obs 1** (soft-cap = hard-cap creates a cliff, not a taper) is a known-by-me
consequence of this session's policy correction work.

**Obs 11** is a self-documented sim training bias toward speed — directly relevant
to the operator's "should hit SS easily" framing.

**Obs 4** describes 7+ overlapping race-targeted bonuses that compound. Worth a
follow-up that *measures* what magnitudes they produce in practice.

No code changes made by this audit.
