# Setup — Fresh Install

Install Sweepy with **`git clone`**, not a ZIP download. The backend
auto-updates itself from GitHub when you hit **Refresh Backend**, and that only
works inside a git working copy — a ZIP extraction has no `.git`, so the update
step silently does nothing (the launcher will warn you if it detects this).

## Install

```bash
git clone https://github.com/rearview-1/project-shaboing.git
cd project-shaboing
```

Then run the one-stop setup below. If you previously ran from an unzipped
folder, re-clone into a fresh directory — your per-account data lives under
`uma_runtime/` and is regenerated automatically, so nothing important is lost.

## Prerequisites

1. **Python 3.10 or newer** on your PATH. Install from <https://www.python.org/downloads/>.
   - During install, **check "Add Python to PATH"**.
   - Verify by opening a new terminal and running `python --version`.
2. **Node.js 18+** on your PATH. Install with `winget install -e --id OpenJS.NodeJS` or from <https://nodejs.org/>.
   - Verify by running `node --version` and `npm --version`.
3. **Umamusume game client** (Steam version). The bot attaches to a running game session, so the game must launch successfully before you can auth.

## One-stop setup and run

On Windows, double-click:

```bat
setup_and_run_sweepy.bat
```

That script creates a local `.venv`, installs Python dependencies, runs
`npm install`, creates the empty runtime directory structure, verifies the
project, and starts the bot backend. Runtime data is generated locally on that
machine and is not included in the repository.

## Auto-updates from GitHub

**This requires a git clone (see Install above).** A ZIP download has no git
metadata, so the update check finds no repository and silently no-ops — you'd
restart on the same code every time.

When the backend is running (and installed via `git clone`), Sweepy checks
GitHub for fast-forward updates and applies them when no career runner is
active. It will not update while a career is running, and it will not merge
over local edits or divergent local commits. After a successful pull, the
backend queues a safe restart and — because the launcher runs a supervisor loop
— the same console window relaunches on the updated code and the web page
reconnects automatically.

Useful overrides:

```bat
set SWEEPY_AUTO_GIT_UPDATE=0
set SWEEPY_AUTO_GIT_UPDATE_INTERVAL_SEC=300
set SWEEPY_AUTO_GIT_UPDATE_REMOTE=origin
set SWEEPY_AUTO_GIT_UPDATE_BRANCH=main
```

The default remote is `shaboing` when present, otherwise `origin`.

## Manual install dependencies

From a terminal inside this folder:

```bash
npm install
pip install -r requirements.txt
```

That installs:

- `steam-user` (Node) — Steam ticket capture
- `fastapi`, `uvicorn` (Python) — the bot's local API
- `frida` — runtime instrumentation to read game state
- `msgpack`, `pycryptodome`, `pydantic`, `requests` — game-protocol decoding

## Game-client version pinning

The bot ships defaults for the game's `app_ver` and `res_ver` in [main.py:903-905](main.py#L903). These are the version strings the game server checks; if they don't match the live game build, the server returns `204 on tool/start_session` with a `store_url` (this is the **client-version-stale** error).

### Auto-discovery (zero-effort path)

When the bot detects the 204+store_url signal, it now **automatically probes plausible newer versions** before giving up:

- Same `app_ver` with `res_ver + 100`, `+200`, `+300`, `+500`, `+1000`, up to `+10000` (Cygames most often bumps `res_ver` in 100-step increments)
- Patch bumps of `app_ver` (e.g. `1.22.0 → 1.22.1/+2/+3`) with current or bumped `res_ver`
- Minor bumps of `app_ver` (e.g. `1.22.0 → 1.23.0/+2/+3/+5`) with bumped `res_ver`

30 candidates tried in priority order by default, with a 1-second gap between probes to avoid rate-limiting. On the first candidate that works, the bot persists the discovered versions to `dev_session.json` and continues normally — no user action needed.

You can widen or narrow the probe budget with:

```bash
set SWEEPY_VERSION_AUTODISCOVERY_MAX_CANDIDATES=50
```

Higher = better chance of finding the right version when the live game has jumped far ahead; lower = faster failure when the version isn't actually the issue. Default 30 covers a range up to `app_ver` minor +5 and `res_ver` +10000.

You'll see this in the bot's console output:

```text
VERSION AUTO-DISCOVERY: 204+store_url on tool/start_session with APP-VER=1.22.0 RES-VER=10006300. Probing 30 candidate(s).
  [1/30] trying APP-VER=1.22.0 RES-VER=10006400
VERSION AUTO-DISCOVERY: success — APP-VER=1.22.0 RES-VER=10006400 accepted.
```

### If auto-discovery fails too

If all probed candidates also return 204+store_url, the live version is further away than the probe range covers. You'll get a clear terminal error pointing you at the fix:

**Option A — env vars (no code edit):**

```bash
set SWEEPY_DEFAULT_APP_VER=<current live value>
set SWEEPY_DEFAULT_RES_VER=<current live value>
```

**Option B — update `main.py:903` and `main.py:905`** to the current values, then restart.

The current live values can be found by:

- Asking someone whose bot is currently authenticating against the live server
- Capturing fresh auth from your own updated game client (the bot reads `app_ver` / `res_ver` from the running game)

After updating, **delete any cached `dev_session.json` first** so the bot uses the new values on the next session start:

```bash
del uma_runtime\instances\<your-instance>\dev_session.json
```

## First run

```bash
run_sweepy.bat
```

Or directly:

```bash
.venv\Scripts\python.exe main.py
```

The bot starts a local API server (FastAPI/uvicorn) and waits for the game client to launch and auth.

## JP Hachimi GameTora skill names + mechanics text

If JP Hachimi translation updates overwrite local skill names or descriptions, run:

```bat
apply_jp_gametora_skill_names.bat
```

The script refreshes `data/gametora_skill_overrides.json` from GameTora, then reapplies
GameTora skill names to every `localized_data*/text_data_dict.json` in the JP Hachimi
install. Skill descriptions use Hachimi's mechanics text when it exists; new skills that
Hachimi does not know about fall back to generated GameTora condition/effect text. Backups
are created before writing. You can override the JP Hachimi path with:

```bat
apply_jp_gametora_skill_names.bat --hachimi-dir "C:\path\to\UmamusumePrettyDerby_Jpn\hachimi"
```

Set `SWEEPY_SKIP_GAMETORA_FETCH=1` before running the script to apply the cached
`data/gametora_skill_overrides.json` without fetching fresh GameTora data.

On first run with no prior data, you'll see fidelity warnings like:

- `manual race thresholds unavailable; using fallback race thresholds`
- `empirical skill-rating calibration unavailable; using fallback skill rating defaults`
- `empirical SP-budget calibration unavailable; using unscaled race SP rewards`
- `empirical race-stat distribution unavailable; using balanced race stat distribution`

These are **expected on a clean install** — the bot's empirical calibrations build up from your own career data as you accumulate runs. The bot still functions, just with vanilla strategy parameters until it has enough data of its own to learn from.

## What the bot creates at runtime

Everything writes to `uma_runtime/`:

- `uma_runtime/instances/<viewer_id>/` — your per-account state (auth, logs, learning, parent memory, calibrations)
- `uma_runtime/policy_models/` — model artifacts (auto-created)

You do not need to put anything in `uma_runtime/` manually. The bot auto-creates whatever it needs.

## Optional: smoke tests

To refresh static game data after a game update or when a new trainee/support
card is missing from the UI:

```bash
update_game_data.bat
```

This pulls the current public card/skill data, rebuilds `data/support_list.json`,
`data/support_card_bonuses.json`, `data/chara_list.json`,
`data/chara_growth_rates.json`, `data/master_map.json`, and simulator support
files, then verifies that the lightweight lists and full simulator records are
in sync. Existing JSON files are backed up under
`data/backups/game_data_updates/`.

To tune the current deck/trainee/friend/parent setup before live careers:

```bash
optimizer.bat
```

Verify the install works without touching the game:

```bash
scripts\windows\run_smoke_tests.bat
```

Or via pytest directly:

```bash
.venv\Scripts\python.exe -m pytest tests/ -q
```

Other optional Windows helpers live in `scripts\windows\`:

- `run_calibrate.bat`
- `run_dry_preflight.bat`
- `run_dual_sweepy.bat`

## Troubleshooting

| Symptom | Likely cause | Fix |
| ------- | ------------ | --- |
| `'python' is not recognized` when running `run_sweepy.bat` | Python not on PATH and `.venv` is missing | Run `setup_and_run_sweepy.bat`, or reinstall Python with "Add to PATH" checked |
| `API error 204 on tool/start_session` with `store_url` in response | Client `app_ver` / `res_ver` is stale | See "Game-client version pinning" above |
| `ImportError: No module named fastapi` (or any other Python module) | Dependency install step skipped or wrong Python was used | Run `setup_and_run_sweepy.bat`; launchers prefer `.venv\Scripts\python.exe` automatically |
| `ImportError: No module named 'steam-user'` style Node errors | `npm install` step skipped | Run `npm install` |
| Bot starts but does nothing | Game client not running / not authed | Launch Umamusume from Steam first, log in, then start the bot |

## What's NOT included in the repo

- Per-account session credentials (`dev_session.json`) — these are tied to a specific Steam account and shouldn't be shared (and are gitignored).
- Career logs from any other user.
- Empirical calibration data built from someone else's careers.

These will all be regenerated as you use the bot on your own account.
