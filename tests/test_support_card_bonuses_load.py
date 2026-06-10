import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"


def _load(name):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8-sig"))


def _walk_support_ids(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"support_card_id", "support_id"}:
                try:
                    yield int(item)
                except (TypeError, ValueError):
                    pass
            yield from _walk_support_ids(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_support_ids(item)


def test_support_list_resolves_to_bonus_records():
    support_list = _load("support_list.json")
    bonuses = _load("support_card_bonuses.json")
    missing = sorted(str(card_id) for card_id in support_list if str(card_id) not in bonuses)
    assert missing == []

    kitasan = bonuses["30028"]
    assert kitasan["name"] == "Kitasan Black"
    assert kitasan["type"] == "Speed"
    assert len(kitasan["lb_levels"]) == 5
    assert "training_effectiveness" in kitasan["lb_levels"][-1]


def test_recent_career_support_ids_resolve_when_logs_exist():
    bonuses = _load("support_card_bonuses.json")
    logs_root = PROJECT_ROOT / "uma_runtime" / "instances"
    logs = sorted(logs_root.glob("*/bot_logs/career_log_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:30]
    support_ids = set()
    for path in logs:
        try:
            support_ids.update(_walk_support_ids(json.loads(path.read_text(encoding="utf-8-sig"))))
        except (OSError, json.JSONDecodeError):
            continue
    support_ids = {sid for sid in support_ids if str(sid) in bonuses or 10000 <= sid <= 39999}
    missing = sorted(str(sid) for sid in support_ids if str(sid) not in bonuses)
    assert missing == []
