"""Verify that a copied/rebuilt Sweepy project is complete enough to run.

This intentionally avoids importing main.py. It catches missing source files
and broken module specs before the startup imports can crash with a traceback.
"""
from __future__ import annotations

import argparse
import importlib.util
import py_compile
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]

REQUIRED_FILES = (
    "main.py",
    "requirements.txt",
    "package.json",
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
    "__pycache__",
    "node_modules",
    "uma_runtime",
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
        for path in _project_py_files():
            try:
                py_compile.compile(str(path), doraise=True)
            except py_compile.PyCompileError as exc:
                rel = path.relative_to(PROJECT_ROOT)
                errors.append(f"python compile failed: {rel}: {exc.msg}")

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
