import json
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_PATH = PROJECT_ROOT / "data" / "real_training_snapshots.json"
STAT_TO_COMMAND = {
    "speed": 101,
    "stamina": 105,
    "power": 102,
    "guts": 103,
    "wit": 106,
}


def test_real_training_snapshots_load_and_cover_all_training_types():
    data = json.loads(DATA_PATH.read_text(encoding="utf-8-sig"))
    snapshots = data.get("snapshots") or []
    assert len(snapshots) >= 100

    counts = {stat: 0 for stat in STAT_TO_COMMAND}
    for snapshot in snapshots:
        for command in snapshot.get("commands") or []:
            stat = command.get("stat")
            if stat in counts:
                counts[stat] += 1
                assert command.get("command_id") == STAT_TO_COMMAND[stat]
                assert command.get("params_inc_dec_info_array")
                assert "failure_rate" in command

    assert all(count > 0 for count in counts.values())
