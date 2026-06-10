import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = PROJECT_ROOT / "data"
STAT_KEYS = {"speed", "stamina", "power", "guts", "wit"}
APTITUDE_KEYS = {"turf", "dirt", "sprint", "mile", "medium", "long", "front", "pace", "late", "end"}


def _load(name):
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8-sig"))


def test_all_chara_list_ids_have_growth_records():
    chara_list = _load("chara_list.json")
    growth = _load("chara_growth_rates.json")
    missing = sorted(str(chara_id) for chara_id in chara_list if str(chara_id) not in growth)
    assert missing == []

    for chara_id in chara_list:
        row = growth[str(chara_id)]
        assert STAT_KEYS <= set(row.get("growth_rates") or {})
        assert STAT_KEYS <= set(row.get("initial_stats") or {})
        assert APTITUDE_KEYS <= set(row.get("base_aptitudes") or {})


def test_maruzensky_growth_record_matches_known_game_shape():
    growth = _load("chara_growth_rates.json")
    maru = growth["100401"]
    assert maru["name"] == "Maruzensky"
    assert maru["growth_rates"]["speed"] == 10
    assert maru["growth_rates"]["wit"] == 20
    assert maru["base_aptitudes"]["mile"] == "A"
