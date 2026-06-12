"""Verify that a copied/rebuilt Sweepy project is complete enough to run.

This intentionally avoids importing main.py. It catches missing source files
and broken module specs before the startup imports can crash with a traceback.
"""
from __future__ import annotations

import argparse
import importlib.util
import py_compile
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "main.py",
    "requirements.txt",
    "package.json",
    "run_sweepy.bat",
    "setup_and_run_sweepy.bat",
    "optimizer.bat",
    "run_dry_preflight.bat",
    "run_dual_sweepy.bat",
    "run_smoke_tests.bat",
    "career_bot/__init__.py",
    "career_bot/deck_advice.py",
    "career_bot/runner.py",
    "career_bot/races.py",
    "career_bot/race_schedule.py",
    "career_bot/scenarios/mant.py",
    "career_bot/skill_profiles.py",
    "career_bot/team_trials_dataset.py",
    "uma_api/__init__.py",
    "uma_api/client.py",
    "public/index.html",
    "public/app.js",
    "public/styles.css",
    "scripts/windows/run_calibrate.bat",
    "scripts/windows/run_dry_preflight.bat",
    "scripts/windows/run_dual_sweepy.bat",
    "scripts/windows/run_smoke_tests.bat",
)

REQUIRED_MODULES = (
    "career_bot.deck_advice",
    "career_bot.runner",
    "career_bot.races",
    "career_bot.race_schedule",
    "career_bot.skill_profiles",
    "career_bot.team_trials_dataset",
    "uma_api.client",
)

SKIP_COMPILE_DIRS = {
    ".git",
    ".pytest_cache",
    ".venv",
    "__pycache__",
    "external_tools",
    "node_modules",
    "uma_runtime",
    "venv",
}

LAUNCHER_EXPECTATIONS = {
    "run_sweepy.bat": ("tools\\verify_project_integrity.py", "main.py"),
    "optimizer.bat": ("scripts\\windows\\run_calibrate.bat",),
    "run_dry_preflight.bat": ("scripts\\windows\\run_dry_preflight.bat",),
    "run_dual_sweepy.bat": ("scripts\\windows\\run_dual_sweepy.bat",),
    "run_smoke_tests.bat": ("scripts\\windows\\run_smoke_tests.bat",),
    "scripts/windows/run_calibrate.bat": ("cd /d \"%~dp0..\\..\"", "tools\\calibrate_deck.py"),
    "scripts/windows/run_dry_preflight.bat": ("cd /d \"%~dp0..\\..\"", "tools\\dry_run_preflight.py"),
    "scripts/windows/run_dual_sweepy.bat": ("cd /d \"%~dp0..\\..\"", "tools\\launch_dual_sweepy.py"),
    "scripts/windows/run_smoke_tests.bat": ("cd /d \"%~dp0..\\..\"", "-m unittest discover"),
}


def _project_py_files() -> list[Path]:
    rows: list[Path] = []
    for path in PROJECT_ROOT.rglob("*.py"):
        rel_parts = set(path.relative_to(PROJECT_ROOT).parts)
        if rel_parts & SKIP_COMPILE_DIRS:
            continue
        rows.append(path)
    return sorted(rows)


def verify(*, compile_python: bool = False) -> tuple[bool, list[str]]:
    errors: list[str] = []

    for rel in REQUIRED_FILES:
        path = PROJECT_ROOT / rel
        if not path.exists():
            errors.append(f"missing required file: {rel}")

    for rel, expected_tokens in LAUNCHER_EXPECTATIONS.items():
        path = PROJECT_ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in expected_tokens:
            if token not in text:
                errors.append(f"launcher {rel} does not reference expected target: {token}")
        if (
            "umamusume-sweepy-main\\umamusume-sweepy-main" in text
            or "umamusume-sweepy-main/umamusume-sweepy-main" in text
        ):
            errors.append(f"launcher {rel} still references the old nested project layout")
        if rel.endswith(".bat") and rel != "setup_and_run_sweepy.bat":
            delegates_to_windows_launcher = "scripts\\windows\\" in text
            if (
                ".venv\\Scripts\\python.exe" not in text
                and "run_calibrate.bat" not in text
                and not delegates_to_windows_launcher
            ):
                errors.append(f"launcher {rel} does not prefer .venv\\Scripts\\python.exe")

    # Make the project root explicit so this works from .bat launchers and
    # from copied folders whose cwd has not been added to sys.path yet.
    root_text = str(PROJECT_ROOT)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

    for module in REQUIRED_MODULES:
        try:
            spec = importlib.util.find_spec(module)
        except Exception as exc:  # noqa: BLE001 - diagnostic script
            errors.append(f"module lookup failed: {module}: {exc}")
            continue
        if spec is None:
            errors.append(f"missing importable module: {module}")

    if compile_python:
        with tempfile.TemporaryDirectory(prefix="sweepy_compile_") as tmp:
            tmp_root = Path(tmp)
            for path in _project_py_files():
                rel = path.relative_to(PROJECT_ROOT)
                cfile = (tmp_root / rel).with_suffix(".pyc")
                cfile.parent.mkdir(parents=True, exist_ok=True)
                try:
                    py_compile.compile(str(path), cfile=str(cfile), doraise=True)
                except py_compile.PyCompileError as exc:
                    errors.append(f"python compile failed: {rel}: {exc.msg}")
                except OSError as exc:
                    errors.append(f"python compile failed: {rel}: {exc}")

    return not errors, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Sweepy project integrity before launch.")
    parser.add_argument("--compile", action="store_true", help="Also compile every project Python file.")
    args = parser.parse_args()

    ok, errors = verify(compile_python=args.compile)
    if ok:
        print("Project integrity check passed.")
        return 0
    print("Project integrity check failed:")
    for error in errors:
        print(f" - {error}")
    print("")
    print("Fix: rebuild/copy the full project folder from the current source tree, not a partial older folder.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
