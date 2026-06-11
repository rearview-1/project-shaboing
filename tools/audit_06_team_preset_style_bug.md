# Audit #6 — Team-Preset Style Bug ("All my runs were Front when should be Late")

**Date:** 2026-06-10
**Scope:** Read-only investigation of the bug where careers run with
`Front` when the operator's `skill_profile_style` is `late_surger`. Did
not modify any code.

## Evidence summary

10 most recent career_logs (`uma_runtime/instances/account_b/bot_logs/`):

| Career | Status | Races | Style distribution |
|--------|--------|-------|---------------------|
| 09:28:46 | error | 21 | (no style recorded) |
| 08:47:18 | finished | 37 | **Front: 34**, Pace: 1, Late: 2 |
| 08:59:36 | finished | 37 | **Front: 34**, Pace: 1, Late: 2 |
| 09:11:52 | finished | 37 | **Front: 34**, Pace: 1, Late: 2 |
| 09:23:48 | finished | 37 | **Front: 34**, Pace: 1, Late: 2 |
| 09:36:56 | finished | 37 | **Front: 34**, Pace: 1, Late: 2 |
| 09:51:04 | finished | 37 | **Front: 34**, Pace: 1, Late: 2 |
| 10:03:54 | finished | 37 | **Front: 34**, Pace: 1, Late: 2 |
| 10:16:25 | finished | 37 | **Front: 35**, Late: 2 |
| 10:19:30 | stopped | 5 | Front: 4, Pace: 1 |

The 1 Pace race in each career corresponds to **Niigata Junior Stakes** (`custom_race_schedule` has `style: "pace_chaser"`).
The 2 Late races correspond to **Kikuka Sho** and **Tenno Sho (Spring)** (`custom_race_schedule` has `style: "late_surger"`).

Every other race ran as **Front** despite `skill_profile_style: "late_surger"` in the preset.

## Inspecting per-race resolution in the career log

From `career_log_20260610_101625.json` (most-recent finished), each race
result was inspected for the runner's recorded style fields:

```
T12 Junior Make Debut          desired=None  source=None  ran=Front
T16 Junior Maiden Race         desired=None  source=None  ran=Front
T19 Saudi Arabia Royal Cup     desired=None  source=None  ran=Front
T23 Hanshin Juvenile Fillies   desired=None  source=None  ran=Front
T31 Satsuki Sho                desired=None  source=None  ran=Front
T33 NHK Mile Cup               desired=None  source=None  ran=Front
T34 Tokyo Yushun (Derby)       desired=None  source=None  ran=Front
T44 Kikuka Sho                 desired=None  source=None  ran=Late
T46 Mile Championship          desired=None  source=None  ran=Front
T48 Arima Kinen                desired=None  source=None  ran=Front
T56 Tenno Sho (Spring)         desired=None  source=None  ran=Late
T59 Yasuda Kinen               desired=None  source=None  ran=Front
T68 Tenno Sho (Autumn)         desired=None  source=None  ran=Front
(... 37 races total)
```

**Key observation:** Every race has `desired=None` and `source=None`. The
race result fields `desired_running_style` (the STRING form) and
`style_source` are both empty across all races.

## What `desired=None, source=None` means

`career_bot/runner.py` line 5092 — `_maybe_change_running_style()`:

```python
resolution = self.race_planner.style_resolution_for_entry(...) or {}
desired_style = str(resolution.get("style") or "").strip()
if not desired_style:
    desired_style = str((scheduled_entry or {}).get("style") or
                         (preset or {}).get("skill_profile_style") or "").strip()
if not desired_style:
    return    # ← early return, NO change_running_style call
desired_value = STYLE_TO_TACTIC.get(desired_style)
...
client.change_running_style(program_id=program_id, running_style=desired_value, ...)
```

For `style_source` (set from `resolution.get("source")`) to be empty
AND `desired_running_style` to be empty, the function must have
returned early at line 5107 (`if not desired_style: return`). The bot
then **never calls `change_running_style`**, leaving the in-game
default running style — which for Satono Diamond is Front.

For `desired_style` to be empty at line 5107:
1. `style_resolution_for_entry` returned `{"style": "", "source": ""}` — that requires `preset.skill_profile_style` to be falsy at that point.
2. The fallback `scheduled_entry.style or preset.skill_profile_style` was also falsy — so `scheduled_entry.style` is empty AND `preset.skill_profile_style` is empty.

**At the time these careers ran, the bot's in-memory preset had
`skill_profile_style = "" / None`.**

## Why preset.skill_profile_style was empty at run time

Current state of all preset layers (read 2026-06-10 after the bug):

| Layer | Path | `skill_profile_style` |
|-------|------|-----------------------|
| config | `data/presets/xguri parent.config.json` | `late_surger` ✓ |
| legacy | `data/presets/xguri parent.json` | `late_surger` ✓ |
| saved/legacy | `data/presets/saved/xguri parent.json` | **`front_runner`** ❌ |
| instance_learning | `uma_runtime/instances/account_b/instance_learning/presets/xguri parent.json` | **`front_runner`** ❌ |
| orphan policy_overrides | `uma_runtime/instances/account_b/instances/account_b/policy_overrides/xguri parent.json` | **`front_runner`** ❌ |
| planner_profile | `data/planner_profiles/Generic Late Spark Farm.json` | `late_surger` ✓ |

Calling `resolve_effective_preset('xguri parent')` from a fresh Python
process **currently returns `late_surger` correctly** — the
`_preserve_operator_owned_fields` logic does pull the config layer's
`late_surger` value over the instance_learning override's `front_runner`.

So the per-layer state right now is **inconsistent but not actively
buggy for the current process**. The runtime bug for the careers that
ran today was that the bot's preset path produced empty (or
`front_runner`) at the time those careers started.

## Suspected mechanisms (no single smoking gun, but several plausible paths)

### Mechanism 1 — Hyperparameter tuner perpetuates stale style

**Location:** `career_bot/runner.py` lines 591-617

```python
instance_preset_path = runtime_root / "instance_learning" / "presets" / f"{preset_name}.json"
live_preset = None
if instance_preset_path.exists():
    live_preset = json.loads(instance_preset_path.read_text(encoding="utf-8-sig"))
...
result = run_tuner(bot_logs_dir=bot_logs_dir, preset=live_preset, ...)
applied = result.get("applied") or []
if applied:
    instance_preset_path.write_text(
        json.dumps(live_preset, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
```

The tuner runs at the end of each career. It reads the instance_learning
preset file directly (bypassing `resolve_effective_preset` and
`_preserve_operator_owned_fields`), mutates hyperparameters
in-place, and writes the WHOLE dict back. **`skill_profile_style`
inside `live_preset` is never preserved against the operator's config
layer** — whatever style was already in the instance_learning file
remains.

Once `instance_learning/presets/xguri parent.json` has stale
`skill_profile_style: "front_runner"`, the tuner keeps writing it back
on every career end. The operator changing the style via UI Save
updates the config layer but does not touch instance_learning.

### Mechanism 2 — Early instance_learning override write before operator changed style

`career_bot/learning.py` `save_instance_learning_outputs` (line 7657) DOES
call `_preserve_operator_owned_fields` at line 7674:

```python
current_source = store.read_one(source_name) or {}
learned = copy.deepcopy(learned)
learned["name"] = source_name
learned["instance_learning_source_preset"] = source_name
learned, preserved_keys = _preserve_operator_owned_fields(learned, current_source)
...
learned_path = instance_learning_override_path(base_dir, source_name)
_atomic_write_json(learned_path, normalize_preset(learned))
```

This SHOULD restore `skill_profile_style` from `current_source` (the
operator's config) when writing the instance_learning file. So this
path is correctly defensive.

However, this is only one of TWO paths that write to
`instance_learning/presets/`. The tuner path (Mechanism 1) lacks the
same protection.

### Mechanism 3 — `_maybe_change_running_style` silently early-returns

**Location:** `career_bot/runner.py` line 5107

```python
if not desired_style:
    return
```

When this early return fires, NO log message is emitted explaining why,
and the bot proceeds to race with the trainee's in-game default
running style. There is no operator-visible signal that "the style I
chose isn't being applied." This is what allowed 34 races per career to
run as Front without surfacing.

A defensive log line here ("skill_profile_style empty for race
{program_id}, using in-game default {current_style}") would make this
fail visibly.

### Mechanism 4 — `build_run_context` does not include `skill_profile_style`

**Location:** `main.py` `build_run_context` lines 6267-6286

The dict built here is what gets written into `run_context` in each
`career_log_*.json`. It includes `preset_name`, `deck_id`,
`trainee_card_id`, `support_card_ids`, etc. — but `skill_profile_style`
is not in the list.

This is why every career_log has `run_context.skill_profile_style:
None`, and why diagnosing this bug from logs required reading per-race
`desired_style` fields rather than the career's intended style.

## Where the orphan/stale state came from

The path `uma_runtime/instances/account_b/instances/account_b/policy_overrides/xguri parent.json`
has the structure `<runtime_output_root>/instances/<account>/policy_overrides/`
where `runtime_output_root` already equals `uma_runtime/instances/account_b/`.
So the actual path includes a redundant `/instances/account_b/`
segment. This file is NOT read by `PresetStore.load_active_preset` —
that function constructs `policy_overrides_path("", "xguri-parent")`
which resolves to `uma_runtime/instances/default/policy_overrides/xguri-parent.json` (single-nested, file does not exist).

The doubly-nested file is an orphan from some past write where the
account_id or base_dir was wrong. It contains a snapshot of the
operator's old `front_runner` configuration.

## What I did NOT verify

- Exact mechanism by which `preset.skill_profile_style` became empty
  during the 08:47-10:19 careers (would need access to the in-flight
  preset state, which is not logged)
- Whether `update_active_preset` was called mid-career to push stale
  values into the running preset
- Whether the planner profile load endpoint was triggered between the
  careers that ran as Front
- The full set of code paths that write to `instance_learning/presets/`

## Summary

**The proximate cause** of "all my runs were Front" is that
`_maybe_change_running_style` early-returns silently when
`desired_style` is empty, leaving the trainee's in-game default style
(Front for Satono Diamond) in effect for the entire race. This
explains why 34 of 37 races per career came up Front while only the 3
races with explicit `custom_race_schedule.style` entries ran the
correct style.

**The underlying cause** is that `preset.skill_profile_style` was
empty when those careers started. Multiple stale-state sources exist
that could contribute to this (instance_learning override has
`front_runner`, the tuner perpetuates it without operator-preserve,
the orphan policy_overrides file has it). The current
`resolve_effective_preset` returns `late_surger` correctly, so the
state is partially self-healed — but the underlying conditions that
allowed the bug to fire are still present.

**Three concrete defensive changes would prevent recurrence** (described
as findings, not fixes — no code changes made by this audit):

1. `runner.py` line 614 — wrap the tuner's instance_learning write in
   `_preserve_operator_owned_fields` so the tuner cannot perpetuate
   stale operator-owned fields.
2. `runner.py` line 5107 — when `desired_style` is empty, emit a log
   line and a flag in the race result so the operator sees that no
   change_running_style call happened.
3. `main.py` `build_run_context` — add `skill_profile_style` (and
   `skill_profile_distance`) to the run_context dict so career_logs
   record the operator's intended style alongside the deck/parent
   identity.

No code changes were made by this audit. The orphan
`uma_runtime/instances/account_b/instances/account_b/` directory
exists and contains stale state but is not read by any code path I
traced.
