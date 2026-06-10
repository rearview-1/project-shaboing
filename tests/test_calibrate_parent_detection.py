"""Tests for calibrate's parent-ID auto-detection.

Critical bug found 2026-06-09: calibrate runs the sim without parent
factors unless `_run_context.parent_id_1/2` are set on the preset.
Parents typically contribute +200-500 stats (blue factors), 10-50%
skill discounts (white sparks), aptitude rank upgrades, and scenario
factor stat bonuses. Calibrate without parents under-predicts rating
by ~1000-3000 per career.

`_detect_parent_ids` reads parents from (in priority order):
  1. dev_session.json → selection.veterans (UI-set picks)
  2. latest bot_logs/career_log_*.json → _run_context.parent_id_1/2
  3. None found → return (0, 0) and warn loudly in caller
"""
import json
from pathlib import Path
from unittest.mock import patch

from tools.calibrate_deck import _detect_parent_ids


def _setup_runtime(tmp_path: Path, instance: str = "test_inst",
                    selection_veterans=None, career_logs=None):
    """Build a fake runtime directory structure."""
    inst_root = tmp_path / "uma_runtime" / "instances" / instance
    inst_root.mkdir(parents=True, exist_ok=True)
    if selection_veterans is not None:
        dev = {"selection": {"veterans": selection_veterans}}
        (inst_root / "dev_session.json").write_text(
            json.dumps(dev), encoding="utf-8"
        )
    if career_logs:
        log_dir = inst_root / "bot_logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        for log_name, ctx in career_logs:
            data = {"_run_context": ctx, "status": "finished"}
            (log_dir / log_name).write_text(json.dumps(data), encoding="utf-8")
    return inst_root


def test_detects_parents_from_dev_session_veterans(tmp_path):
    """Tier 1: UI-set parents in dev_session.json win over everything."""
    _setup_runtime(
        tmp_path,
        selection_veterans=[
            {"instance_id": 111, "trained_chara_id": 9001},
            {"instance_id": 222, "trained_chara_id": 9002},
        ],
        # Also has a career_log with DIFFERENT IDs to prove dev_session wins
        career_logs=[
            ("career_log_001.json", {"parent_id_1": 999, "parent_id_2": 888}),
        ],
    )
    with patch("tools.calibrate_deck.PROJECT_ROOT", tmp_path):
        p1, p2, source = _detect_parent_ids("test_inst")
    assert p1 == 111
    assert p2 == 222
    assert "dev_session" in source


def test_falls_back_to_career_log_when_veterans_empty(tmp_path):
    """Tier 2: empty veterans → use latest career_log's parents."""
    _setup_runtime(
        tmp_path,
        selection_veterans=[],  # empty
        career_logs=[
            ("career_log_001.json", {"parent_id_1": 555, "parent_id_2": 777}),
        ],
    )
    with patch("tools.calibrate_deck.PROJECT_ROOT", tmp_path):
        p1, p2, source = _detect_parent_ids("test_inst")
    assert p1 == 555
    assert p2 == 777
    assert "career_log" in source


def test_picks_most_recent_career_log_when_multiple(tmp_path):
    """Among multiple career_logs, the most recently modified one wins
    (the bot's current run, not a stale one)."""
    import time as _time
    inst = _setup_runtime(
        tmp_path,
        selection_veterans=[],
        career_logs=[
            ("career_log_OLD.json", {"parent_id_1": 100, "parent_id_2": 200}),
        ],
    )
    # Touch the old one with an old mtime, then create a newer one
    old_path = inst / "bot_logs" / "career_log_OLD.json"
    _time.sleep(0.05)
    new_data = {"_run_context": {"parent_id_1": 999, "parent_id_2": 1999}}
    (inst / "bot_logs" / "career_log_NEW.json").write_text(
        json.dumps(new_data), encoding="utf-8"
    )
    with patch("tools.calibrate_deck.PROJECT_ROOT", tmp_path):
        p1, p2, source = _detect_parent_ids("test_inst")
    assert p1 == 999  # from NEW, not OLD
    assert p2 == 1999


def test_returns_zeros_when_nothing_found(tmp_path):
    """Tier 3: no dev_session.json, no career_logs → (0, 0, 'none found')."""
    # Empty instance, no dev_session, no bot_logs
    inst_root = tmp_path / "uma_runtime" / "instances" / "empty_inst"
    inst_root.mkdir(parents=True)
    with patch("tools.calibrate_deck.PROJECT_ROOT", tmp_path):
        p1, p2, source = _detect_parent_ids("empty_inst")
    assert p1 == 0
    assert p2 == 0
    assert source == "none found"


def test_skips_partial_parent_data(tmp_path):
    """A career_log with only parent_id_1 set (not p2) shouldn't be
    used — we need both for the sim's legacy_effects to make sense."""
    _setup_runtime(
        tmp_path,
        selection_veterans=[],
        career_logs=[
            ("career_log_partial.json", {"parent_id_1": 100, "parent_id_2": 0}),
            ("career_log_full.json", {"parent_id_1": 500, "parent_id_2": 600}),
        ],
    )
    import time
    # Ensure full has newer mtime
    time.sleep(0.05)
    Path(tmp_path / "uma_runtime" / "instances" / "test_inst" / "bot_logs"
         / "career_log_full.json").touch()
    with patch("tools.calibrate_deck.PROJECT_ROOT", tmp_path):
        p1, p2, source = _detect_parent_ids("test_inst")
    # Either gets the full one OR returns zeros, but must NOT use the partial
    assert (p1, p2) in [(500, 600), (0, 0)]


def test_handles_malformed_dev_session_gracefully(tmp_path):
    """A corrupt dev_session.json must not crash detection — fall
    through to the career_log tier."""
    inst_root = tmp_path / "uma_runtime" / "instances" / "test_inst"
    inst_root.mkdir(parents=True)
    (inst_root / "dev_session.json").write_text(
        "not valid json {{", encoding="utf-8"
    )
    log_dir = inst_root / "bot_logs"
    log_dir.mkdir()
    (log_dir / "career_log_001.json").write_text(
        json.dumps({"_run_context": {"parent_id_1": 42, "parent_id_2": 84}}),
        encoding="utf-8",
    )
    with patch("tools.calibrate_deck.PROJECT_ROOT", tmp_path):
        p1, p2, source = _detect_parent_ids("test_inst")
    assert p1 == 42
    assert p2 == 84
