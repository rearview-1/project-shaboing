import json
from pathlib import Path

from career_bot.sim_observations import (
    load_runtime_event_observations,
    load_runtime_training_snapshots,
    write_sim_observation_export,
)


def test_write_and_load_sim_observations(tmp_path):
    runtime_root = tmp_path / "uma_runtime" / "instances" / "account_b"
    bot_logs = runtime_root / "bot_logs"
    bot_logs.mkdir(parents=True)
    career_log = bot_logs / "career_log_20260604_120000.json"
    career_log.write_text(
        json.dumps(
            {
                "schema": "sweepy_career_log_v1",
                "status": "finished",
                "preset_name": "test preset",
                "scenario_id": 4,
                "run_context": {
                    "runtime_instance": "account_b",
                    "trainee_card_id": 102001,
                    "support_cards": [
                        {"support_card_id": 30028, "name": "Kitasan Black", "type": "Speed", "lb_level": 4},
                        {"support_card_id": 30036, "name": "Riko Kashimoto", "type": "Friend", "lb_level": 4},
                        {"support_card_id": 30017, "name": "Smart Falcon", "type": "Power", "lb_level": 4},
                        {"support_card_id": 30029, "name": "Fine Motion", "type": "Wit", "lb_level": 4},
                        {"support_card_id": 30030, "name": "Super Creek", "type": "Stamina", "lb_level": 4},
                    ],
                    "friend_card_id": 30017,
                    "parent_id_1": 1,
                    "parent_id_2": 2,
                },
                "turns": [
                    {
                        "event": "turn",
                        "turn": 1,
                        "skill_point": 120,
                        "mant_coin": 0,
                        "stats": {
                            "hp": 100,
                            "max_hp": 100,
                            "motivation": 3,
                            "speed": 100,
                            "stamina": 90,
                            "power": 95,
                            "guts": 80,
                            "wit": 110,
                            "skill_point": 120,
                        },
                        "current_action_taken": "command",
                        "current_command": {
                            "command_type": 1,
                            "command_id": 101,
                            "command_group_id": 0,
                            "select_id": 0,
                            "current_turn": 1,
                        },
                        "training_snapshot": {
                            "turn": 1,
                            "stats": {
                                "hp": 100,
                                "max_hp": 100,
                                "motivation": 3,
                                "speed": 100,
                                "stamina": 90,
                                "power": 95,
                                "guts": 80,
                                "wit": 110,
                                "skill_point": 120,
                            },
                            "trainings": [
                                {
                                    "name": "Speed",
                                    "command_id": 101,
                                    "facility_level": 1,
                                    "enabled": True,
                                    "failure_rate": 0,
                                    "partners": [{"target_id": 1, "bond": 30, "deck_partner": True}],
                                    "partner_count": 1,
                                    "rainbow_count": 0,
                                    "stat_gain": {"speed": 12, "power": 6, "skill_point": 2, "hp": -19},
                                }
                            ],
                        },
                    },
                    {
                        "event": "turn",
                        "turn": 2,
                        "skill_point": 122,
                        "mant_coin": 10,
                        "stats": {
                            "hp": 81,
                            "max_hp": 100,
                            "motivation": 3,
                            "speed": 112,
                            "stamina": 90,
                            "power": 101,
                            "guts": 80,
                            "wit": 110,
                            "skill_point": 122,
                        },
                        "events": [
                            {
                                "event": "race_result",
                                "turn": 2,
                                "program_id": 689,
                                "race": {"program_id": 689, "name": "Junior Make Debut", "grade": ""},
                                "finish_rank": 1,
                                "won": True,
                            },
                            {
                                "event": "event_choice",
                                "turn": 2,
                                "event_id": 10002,
                                "story_id": "809006004",
                                "choice_index": 2,
                                "available_choices": 3,
                            },
                        ],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    summary = write_sim_observation_export(career_log, runtime_root=runtime_root)

    assert summary["record_count"] >= 5
    assert summary["training_snapshot_count"] == 1
    assert summary["race_result_count"] == 1
    assert Path(summary["jsonl_path"]).exists()
    records = [
        json.loads(line)
        for line in Path(summary["jsonl_path"]).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    event_record = next(row for row in records if row.get("record_type") == "event_choice")
    metadata = event_record["event_metadata"]
    assert metadata["source"] == "support_card"
    assert metadata["source_id"] == "30036"
    assert metadata["support_card_id"] == 30036
    assert metadata["event_name"] == "Unexpected Side"

    snapshots = load_runtime_training_snapshots(tmp_path, run_context={"runtime_instance": "account_b"})
    assert len(snapshots) == 1
    assert snapshots[0]["turn"] == 1
    assert snapshots[0]["commands"][0]["stat"] == "speed"
    fast_snapshots = load_runtime_training_snapshots(
        tmp_path,
        run_context={"runtime_instance": "account_b"},
        copy_result=False,
    )
    fast_again = load_runtime_training_snapshots(
        tmp_path,
        run_context={"runtime_instance": "account_b"},
        copy_result=False,
    )
    assert fast_snapshots is fast_again
    safe_again = load_runtime_training_snapshots(tmp_path, run_context={"runtime_instance": "account_b"})
    assert safe_again is not fast_snapshots
    safe_again[0]["turn"] = 999
    assert fast_again[0]["turn"] == 1

    events = load_runtime_event_observations(tmp_path, run_context={"runtime_instance": "account_b"})
    assert events["choice_count"] == 1
    assert events["by_source"]["support_card"] == 1
    assert events["events"][0]["event_metadata"]["support_card_id"] == 30036
