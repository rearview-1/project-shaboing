import json

from career_bot.presets import PresetStore


def test_race_agenda_config_wins_over_account_policy_override(tmp_path, monkeypatch):
    base = tmp_path
    preset_dir = base / "data" / "presets"
    preset_dir.mkdir(parents=True)

    runtime = base / "uma_runtime" / "instances" / "account_b"
    monkeypatch.setenv("UMA_RUNTIME_DIR", str(runtime))
    monkeypatch.setenv("SWEEPY_INSTANCE_NAME", "account_b")

    config_schedule = [
        {"race_id": 1, "program_id": 628, "turn": 14, "name": "Hakodate Junior Stakes"},
        {"race_id": 2, "program_id": 631, "turn": 17, "name": "Kokura Junior Stakes"},
    ]
    stale_schedule = [
        {"race_id": 3, "program_id": 630, "turn": 17, "name": "Sapporo Junior Stakes"},
    ]

    (preset_dir / "xguri parent.config.json").write_text(
        json.dumps(
            {
                "name": "xguri parent",
                "preset_family": "xguri parent",
                "custom_race_schedule": config_schedule,
                "extra_race_list": [1, 2],
            }
        ),
        encoding="utf-8",
    )

    stale_override = runtime / "instances" / "account_b" / "policy_overrides" / "xguri parent.json"
    stale_override.parent.mkdir(parents=True)
    stale_override.write_text(
        json.dumps(
            {
                "name": "xguri parent",
                "preset_family": "xguri parent",
                "custom_race_schedule": stale_schedule,
                "extra_race_list": [3],
            }
        ),
        encoding="utf-8",
    )

    preset = PresetStore(base).read_one("xguri parent")

    assert [row["program_id"] for row in preset["custom_race_schedule"]] == [628, 631]
    assert preset["extra_race_list"] == [1, 2]


def test_source_files_includes_split_config_for_hot_reload(tmp_path):
    base = tmp_path
    preset_dir = base / "data" / "presets"
    preset_dir.mkdir(parents=True)
    config = preset_dir / "xguri parent.config.json"
    config.write_text('{"name":"xguri parent"}', encoding="utf-8")

    files = PresetStore(base).source_files()

    assert config in files
