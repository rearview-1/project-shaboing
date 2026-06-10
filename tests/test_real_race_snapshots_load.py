import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "real_race_snapshots.json"


def test_real_race_snapshots_load_and_cover_core_g1s():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    assert data.get("schema") == "sweepy_real_race_snapshots_v1"
    results = data.get("result_samples") or []
    fields = data.get("field_samples") or []
    assert len(results) >= 1000
    assert len(fields) >= 1

    by_pid = {}
    for row in results:
        by_pid.setdefault(int(row.get("program_id") or 0), []).append(row)

    for program_id in (163, 164, 166, 168, 73, 74, 77, 78, 79, 81):
        assert len(by_pid.get(program_id, [])) >= 20


def test_real_race_samples_have_stats_and_outcomes():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    sample = next(row for row in data.get("result_samples") or [] if row.get("raw_stats"))
    assert sample["result_rank"] >= 1
    assert isinstance(sample["won"], bool)
    assert set(sample["raw_stats"]) == {"speed", "stamina", "power", "guts", "wit"}
    assert sum(sample["raw_stats"].values()) > 0
