import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
RUNTIME_DIR = PROJECT_ROOT / "uma_runtime"


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _skill_failure_ids():
    ids = set()
    for path in RUNTIME_DIR.rglob("skill_failures.json") if RUNTIME_DIR.exists() else []:
        try:
            data = _load(path)
        except (OSError, json.JSONDecodeError):
            continue
        for key in (data.get("skills") or {}):
            try:
                ids.add(int(key))
            except (TypeError, ValueError):
                continue
    return ids


def test_skill_activation_data_has_required_schema():
    data = _load(DATA_DIR / "skill_activation_data.json")
    prof = data["200331"]
    assert prof["name"] == "Professor of Curvature"
    assert prof["category"] == "speed"
    assert prof["effect_type"] == "target_speed"
    assert prof["effect_magnitude"] > 0
    assert prof["cost"] > 0
    assert "condition" in prof


def test_skill_failures_resolve_when_present():
    data = _load(DATA_DIR / "skill_activation_data.json")
    failed_ids = _skill_failure_ids()
    missing = sorted(str(skill_id) for skill_id in failed_ids if str(skill_id) not in data)
    assert missing == []
