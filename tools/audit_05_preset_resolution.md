# Audit #5 — Preset Resolution Layered System

**Date:** 2026-06-10
**Scope:** Read-only audit of the preset save/load/merge pipeline.
End-to-end trace: UI save → file → bot load → which fields win at career start.
Did not modify any code.

## Files / functions examined

- `career_bot/presets.py`
  - `CONFIG_ONLY_KEYS` (line 29)
  - `POLICY_MODEL_KEYS` (line 68)
  - `RUNTIME_STATE_KEYS` (line 73)
  - `split_preset_layers()` (line 112)
  - `merge_preset_layers()` (line 153)
  - `read_instance_learning_override()` / `write_instance_learning_override()` (lines 561, 571)
  - `PresetStore.load_active_preset()` (line 1022)
  - `PresetStore.write()` (line 953)
  - `PresetStore.save_user_config()` (line 1039)
  - `PresetStore.read_one()` / `read_all()` (lines 915, 935)
- `main.py`
  - `resolve_effective_preset()` (line 4522)
  - `read_requested_base_preset()` (line 4547)
- `career_bot/learning.py`
  - `OPERATOR_OWNED_PRESET_KEYS` (line 7400)
  - `_preserve_operator_owned_fields()` (line 7507)

## File-system layout (per preset name "X")

| Path | Layer | Written by |
|---|---|---|
| `data/presets/X.json` | legacy unified | `PresetStore.write()` when `X.config.json` doesn't exist |
| `data/presets/X.config.json` | config | `save_user_config()` (UI Save Skill Plan path goes here) |
| `uma_runtime/instances/<acct>/state/X.runtime.json` | runtime | `save_runtime_state()` |
| `data/presets/<family>.policy_model.json` | model | `save_policy_model()` |
| `uma_runtime/instances/<acct>/policy_overrides/<family>.json` | overrides | `save_policy_overrides()` |
| `uma_runtime/instances/<acct>/instance_learning/presets/X.json` | instance learning override | `write_instance_learning_override()` |

## Two resolution paths

### Path A — `PresetStore.load_active_preset` (called by `read_one`, `read_all`)

```
load_active_preset(account_id, preset_name):
    config = read X.config.json
    if not config: fall back to legacy X.json
    runtime = read X.runtime.json
    model = read <family>.policy_model.json
    overrides = read <family> instance overrides
    # strip CONFIG_ONLY_KEYS from model and overrides
    merged = merge_preset_layers(config, runtime, model, overrides)
    return normalize_preset(merged)
```

`merge_preset_layers` is `dict.update` in order: config → runtime → model → overrides.
**Last layer wins.**

### Path B — `resolve_effective_preset` (called by career start, see main.py:1278, 4557, 4901, 5363)

```
resolve_effective_preset(name, base_preset=None):
    preset = preset_store.read_one(name)        # → Path A result
    if not instance_local_learning_enabled():
        return preset
    override = read_instance_learning_override(DIR, name)
    if not override: return preset
    merged = dict(preset)
    merged.update(override)                     # instance learning wins
    merged, _ = _preserve_operator_owned_fields(merged, preset)   # operator wins back
    return merged
```

So the effective preset goes: Path A result → instance learning override → operator-owned
fields restored from Path A result. The instance learning override is in
`uma_runtime/instances/<acct>/instance_learning/presets/<name>.json`.

## Observations

### Obs 1 — Two paths, used in different contexts

**Location:** `read_one` calls `load_active_preset` (line 921); `resolve_effective_preset`
also calls `read_one` then adds the instance-learning layer (line 4530-4544)

**Observation:** Several call sites use `read_one` / `read_requested_base_preset`
(skipping the instance-learning override). Others use `resolve_effective_preset`.

Call sites for `resolve_effective_preset` (from grep):
- main.py:1278 — career runner setup
- main.py:4557 — `read_requested_preset` (different from `read_requested_base_preset`)
- main.py:4901
- main.py:5363

Call sites for `read_requested_base_preset` (skips Path B):
- main.py:4641 — `save_skill_plan` endpoint
- main.py and elsewhere

**Concern:** When the UI saves a skill plan, it reads via `read_requested_base_preset`
(Path A only). When the bot runs a career, it reads via `resolve_effective_preset`
(Path A + instance learning override). The "saved preset" and the "running preset" can
diverge. This was the cause of the `front_runner` vs `late_surger` discrepancy we hit
earlier this session.

### Obs 2 — `_preserve_operator_owned_fields` runs only on Path B

**Location:** main.py:4542

**Observation:** Only `resolve_effective_preset` calls `_preserve_operator_owned_fields`.
`load_active_preset` does not. The merge order in Path A is `config → runtime → model →
overrides`, with `overrides` winning. If the `<family>.policy_overrides` file (in
`uma_runtime/instances/<acct>/policy_overrides/`) contains a stale value for an
operator-owned key, it overwrites the config — and there is no `_preserve_*` step at
this layer.

**Concern:** This is subtle. The CONFIG_ONLY_KEYS strip at lines 1032-1033 removes
specific keys from model and overrides, but the strip set is small:

```python
CONFIG_ONLY_KEYS = {
    "desired_parent_sparks",
    "race_plan_text",
    "custom_race_schedule",
    "extra_race_list",
    "race_list",
}
```

The OPERATOR_OWNED_PRESET_KEYS set (used by `_preserve_operator_owned_fields`) is much
larger, including `skill_profile_style`, `skill_profile_distance`, `skill_buy_on_sight`,
`learn_skill_list`, `manual_purchase_at_end`, `calendar_race_prebuy_enabled`, etc.

So if `policy_overrides` contains, say, `skill_profile_style="front_runner"` (because the
learning system wrote it there), Path A merges that on top of the user's
`skill_profile_style="late_surger"` from config.json. Path B then runs
`_preserve_operator_owned_fields` and restores the user's value. But Path A consumers
(such as `read_requested_base_preset` → `save_skill_plan` endpoint flow) get the
overridden value.

### Obs 3 — `save_user_config` writes ONLY the config layer

**Location:** `save_user_config` lines 1039-1056

**What the code does:**
```python
layers = split_preset_layers(preset)
config = layers["config"]
self._write_layer(path, config)
return self.load_active_preset("", config["name"]) or normalize_preset(config)
```

**Observation:** When the UI saves a skill plan, only the `config` layer is written
to `X.config.json`. The other layers on disk (runtime, model, overrides, instance
learning override) are not modified.

**Concern:** A user save updates the config layer but does not touch the instance
learning override. If the override has a stale value for a key the user is updating
(e.g., user changes `skill_profile_style` but the override still has the old style),
Path B's merge would let the override win until `_preserve_operator_owned_fields`
catches it. The "save" is correctly persisted; the bot's effective value depends on
which path is reading.

### Obs 4 — `split_preset_layers` distributes keys based on the key's identity

**Location:** `split_preset_layers` lines 112-150

**What the code does:**
```python
for key, value in data.items():
    if key in POLICY_MODEL_KEYS: model[key] = value; continue
    if key in RUNTIME_STATE_KEYS or str(key).startswith("_"): runtime[key] = value; continue
    if instance_override and key not in {"name", "preset_family"}:
        if key in CONFIG_ONLY_KEYS: continue
        overrides[key] = value
        continue
    config[key] = value
```

`POLICY_MODEL_KEYS = {"training_policy_model", "training_policy_challenger",
"training_policy_validation"}` (line 68)
`RUNTIME_STATE_KEYS = {"_run_context", "_deck_multipliers", "_deck_type_counts",
"_deck_type_counts_source", "_loop_mode"}` (line 73)

**Observation:** Any key starting with `_` is automatically a runtime key. So
`_run_context` (which carries parent_ids, deck, trainee) is always runtime. Any other
key goes to config (unless instance_override mode, which sends it to overrides).

**Concern:** The split is by key NAME, not by VALUE. A preset dict where an operator
hand-added e.g. `_my_custom_override` would have that silently treated as runtime
(stripped on save). No warning.

### Obs 5 — `read_legacy_unified` is the fallback when no `X.config.json` exists

**Location:** lines 1024-1026, fallback to `read_legacy_unified(preset_name)` (line 1144)

**Observation:** If `X.config.json` doesn't exist, the legacy `X.json` is loaded
whole, normalize_preset'd, and returned. No layer separation, no merge.

**Concern:** Legacy presets bypass the layered system entirely. Mixed-mode operation
(some presets layered, some legacy) is possible. The user's `xguri parent` has both
`xguri parent.json` (legacy) and `xguri parent.config.json` (layered) on disk. The
layered config takes precedence when both exist.

### Obs 6 — `instance_local_learning_enabled()` toggle gates Path B

**Location:** main.py:4528

**What the code does:**
```python
if not instance_local_learning_enabled():
    return preset
```

**Observation:** Path B can be disabled entirely by `instance_local_learning_enabled`
returning False (function not read in this audit; presumably reads an env var or
preset flag). When disabled, the instance learning override is never read, and the
effective preset is just `read_one`'s result.

**Concern:** A toggle that's off would make the bot ignore the instance learning
override entirely. Not investigated whether/how this is configurable per session.

### Obs 7 — `_preserve_operator_owned_fields` deep-merges `race_style_overrides` but shallow-replaces other keys

**Location:** lines 7507-7592

**What the code does:** Special case for `race_style_overrides` at lines 7514-7589
(v1 flat + v2 nested merging). For ALL other operator-owned keys at line 7590:
`merged[key] = copy.deepcopy(current_source[key])` — full replacement from source.

**Observation:** For 26 of the 27 operator-owned keys, the source value replaces the
learned value entirely. For `race_style_overrides`, the merge is structural (handles
the v1/v2 schema split).

**Concern:** Non-trivial keys like `learn_skill_list` (a 2-element list of skill
lists) are replaced wholesale. If learning wrote useful learned values into a
`learn_skill_list` entry, they're discarded when the source has any value (even an
empty list).

### Obs 8 — Order of operations: `merged.update(override)` then preserve

**Location:** main.py:4541-4542

**What the code does:**
```python
merged = dict(preset)
merged.update(override)
merged, _ = _preserve_operator_owned_fields(merged, preset)
```

**Observation:** The override is applied first, THEN operator-owned fields are pulled
back from the original `preset`. For operator-owned keys, this is a no-op pair (apply
+ restore = original). For non-operator-owned keys, the override wins.

**Concern:** Correctness-wise this works. Efficiency-wise it's a temp dict mutation
then partial restore. Not a behavior concern, but it's worth noting that the
override file's operator-owned-field values are effectively dead — they get written
but never read in a way that affects behavior. Wasted disk and confusion potential.

### Obs 9 — `preset_store.write()` chooses path based on file existence

**Location:** `PresetStore.write` lines 953-976

**What the code does:**
```python
def write(self, preset, *, target="saved"):
    self.ensure()
    data = normalize_preset(preset)
    if self.config_path(data["name"]).exists():
        return self.save_user_config(data["name"], data)
    path = self._path_for_name(data["name"], target=target)
    # ... back up old file ...
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    # ...
    return data
```

**Observation:** If `X.config.json` exists, route the save to `save_user_config`
(writes only the config layer). Otherwise, write the whole preset as a legacy
unified file.

**Concern:** Once an `X.config.json` exists, the legacy `X.json` becomes read-only
in normal operation. There's no path that writes the legacy file when a config file
exists. The legacy file's contents could drift from what's actively in use — the
user's `xguri parent.json` legacy file has mtime "2026-06-05" while
`xguri parent.config.json` was written 2026-06-10. That's expected given Obs 9 but
worth being aware of.

### Obs 10 — UI save endpoint flow

**Location:** main.py:4641 (`save_skill_plan`)

**Trace (from earlier session work):**

1. User clicks "Save Skill Plan" in UI
2. Frontend reads visible seg-button (the fix from earlier this session)
3. POST `/api/presets/save_skill_plan`
4. Endpoint calls `read_requested_base_preset(req)` → Path A (no instance override)
5. Endpoint mutates the dict (sets `skill_profile_style`, `skill_buy_on_sight`, etc.)
6. Endpoint calls `preset_store.write(preset)` → if config.json exists, goes to
   `save_user_config` → only writes config layer
7. Returns the layered-merged-back result

**Observation:** The save endpoint reads via Path A and writes the config layer.
Path A doesn't preserve operator-owned fields against the instance learning override.
So if the instance learning override has a stale style value, the read pulls THE
USER'S VALUE through (since user changes were just made and the dict mutation at
step 5 explicitly sets the new value), and the write only updates the config layer.

The instance learning override is left untouched, but Path B (on the bot's career
start) restores user-owned fields from the (now updated) config. So the effective
flow is correct, but it relies on `_preserve_operator_owned_fields` being called.

**Concern:** If any caller uses Path A directly to read what the bot is doing (e.g.,
a "show me the active preset" debug endpoint), it would see the override's stale
value, not the user's saved value. The actual career run uses Path B, which is
correct.

## What I did NOT check

- `instance_local_learning_enabled()` definition (Obs 6)
- `_path_for_name` and the `target=` parameter handling on `PresetStore.write`
- The exact behavior of `normalize_preset` (key normalization, type coercion)
- All call sites of Path A vs Path B systematically — only the most common were traced
- `save_runtime_state`, `save_policy_model`, `save_policy_overrides` callers — when do
  these layers actually get updated, and by which subsystems
- `read_one` vs `read_requested_base_preset` vs `read_requested_preset` —
  similar names, different behavior; only `read_one` was traced
- The data format expected on disk for each layer (what keys are valid where)

## Summary

10 observations. The architecture is consistent and the merge math is correct, but
the layered design has nontrivial complexity:

- **Two read paths** (Obs 1) with different semantics — Path A skips instance learning,
  Path B applies it
- **`_preserve_operator_owned_fields` only runs on Path B** (Obs 2) — Path A consumers
  could see overridden operator-owned values

The user's actual symptom that surfaced earlier this session — UI save going to one
file, bot reading from another — was a calibrate-tool issue (Audit #2) where
`_base_preset` was loading the instance learning override file DIRECTLY instead of
using `resolve_effective_preset`. That bug was fixed earlier. The preset resolution
system itself works as designed; the bug was at the consumer.

The design's main risk is consumer mistakes — any new code that reads presets needs
to choose between Path A and Path B carefully. The function names don't make the
distinction obvious (`read_one` vs `resolve_effective_preset`).

No code changes made by this audit.
