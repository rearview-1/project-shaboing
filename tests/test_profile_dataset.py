import json
from pathlib import Path

from career_bot.profile_dataset import (
    extract_profile_records_from_response,
    ingest_trace_dataset,
    load_name_maps,
    summarize_dataset,
)


def write_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def make_project_root(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    write_json(root / "data" / "support_list.json", {
        "30028": {"name": "Kitasan Black", "type": "Speed", "rarity": "SSR"},
        "30036": {"name": "Riko Kashimoto", "type": "Friend", "rarity": "SSR"},
    })
    write_json(root / "data" / "chara_list.json", {"102601": "Oguri Cap"})
    write_json(root / "data" / "factor_map.json", {"303": {"name": "Speed", "stars": 3, "category": "stat"}})
    write_json(root / "data" / "master_map.json", {"skill": {"201541": "Front Runner ○"}})
    write_json(root / "data" / "race_map.json", {"program": {"676": {"name": "Junior Make Debut"}}})
    return root


def public_profile_payload():
    return {
        "team_profile": {
            "viewer_id": 123456,
            "name": "Public Trainer",
            "team_member_array": [
                {
                    "user_trained_chara": {
                        "viewer_id": 123456,
                        "trained_chara_id": 9001,
                        "card_id": 102601,
                        "rank": 18,
                        "rank_score": 20838,
                        "speed": 1200,
                        "stamina": 796,
                        "power": 1120,
                        "guts": 684,
                        "wiz": 1200,
                        "proper_ground_turf": 7,
                        "proper_ground_dirt": 7,
                        "proper_distance_mile": 8,
                        "proper_running_style_senko": 7,
                        "support_card_array": [
                            {"position": 1, "support_card_id": 30028, "limit_break_count": 4},
                            {"position": 6, "support_card_id": 30036, "limit_break_count": 4, "owner_viewer_id": 999},
                        ],
                        "skill_array": [{"skill_id": 201541, "level": 1}],
                        "factor_info_array": [{"factor_id": 303, "level": 3}],
                        "race_history": [
                            {"turn": 12, "program_id": 676, "result_rank": 1, "running_style": 2, "result_time": 1164064},
                            {"turn": 24, "program_id": 676, "result_rank": 2, "running_style": 2},
                        ],
                    }
                }
            ],
        }
    }


def test_extract_public_profile_record_normalizes_full_career_detail(tmp_path):
    root = make_project_root(tmp_path)
    records = extract_profile_records_from_response(
        "team_stadium/profile",
        public_profile_payload(),
        source={"trace_file": "sample.jsonl", "line": 1},
        maps=load_name_maps(root),
    )

    assert len(records) == 1
    record = records[0]
    assert record["viewer_id"] == 123456
    assert record["trainer_name"] == "Public Trainer"
    assert record["card_id"] == 102601
    assert record["chara_name"] == "Oguri Cap"
    assert record["stats"]["speed"] == 1200
    assert record["stats"]["wit"] == 1200
    assert record["aptitudes"]["distance"]["mile"]["rank"] == "S"
    assert record["support_card_ids"] == [30028, 30036]
    assert record["support_cards"][0]["name"] == "Kitasan Black"
    assert record["skill_ids"] == [201541]
    assert record["skills"][0]["name"] == "Front Runner ○"
    assert record["factor_ids"] == [303]
    assert record["races"]["history_count"] == 2
    assert record["races"]["loss_count"] == 1


def test_trace_ingest_replaces_summary_with_richer_profile_record(tmp_path):
    root = make_project_root(tmp_path)
    runtime = tmp_path / "runtime"
    trace_dir = runtime / "trace_logs" / "api_payloads"
    trace_dir.mkdir(parents=True)
    trace_path = trace_dir / "20260602_payloads.jsonl"
    summary_row = {
        "direction": "RES",
        "endpoint": "pre_single_mode/index",
        "req_id": "a",
        "data": {"data": {"friend_support_card_data": {"summary_user_info_array": [{
            "viewer_id": 123456,
            "name": "Public Trainer",
            "user_trained_chara": {
                "viewer_id": 123456,
                "trained_chara_id": 9001,
                "card_id": 102601,
                "rank": 18,
                "rank_score": 20838,
                "factor_id_array": [303],
            },
        }]}}},
    }
    detail_row = {
        "direction": "RES",
        "endpoint": "team_stadium/profile",
        "req_id": "b",
        "data": {"data": public_profile_payload()},
    }
    trace_path.write_text(
        json.dumps(summary_row, ensure_ascii=False) + "\n" + json.dumps(detail_row, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    result = ingest_trace_dataset(root, runtime, recent_files=1, limit=10)
    assert result["total_records"] == 1
    assert result["added"] == 1
    assert result["updated"] == 1

    summary = summarize_dataset(root, runtime, stat="wit", min_value=1200)
    assert summary["filtered_records"] == 1
    assert summary["top_support_cards"][0]["support_card_id"] == 30028
    assert summary["rank_score"]["max"] == 20838


def test_load_index_records_are_skipped_unless_include_self(tmp_path):
    root = make_project_root(tmp_path)
    payload = {
        "trained_chara": [{
            "trained_chara_id": 9001,
            "card_id": 102601,
            "rank_score": 18000,
            "factor_id_array": [303],
        }]
    }

    public_only = extract_profile_records_from_response(
        "load/index",
        payload,
        maps=load_name_maps(root),
        include_self=False,
    )
    include_self = extract_profile_records_from_response(
        "load/index",
        payload,
        maps=load_name_maps(root),
        include_self=True,
    )

    assert public_only == []
    assert len(include_self) == 1
