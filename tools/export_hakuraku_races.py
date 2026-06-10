import argparse
import json
import re
import shutil
import sys
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from career_bot.races import RacePlanner

BACKING = lambda name: f"<{name}>k__BackingField"
_RACE_PROGRAM_INSTANCE_CACHE = None

WEATHER_NAMES = {
    1: "Sunny",
    2: "Cloudy",
    3: "Rainy",
    4: "Snowy",
}

GROUND_CONDITION_NAMES = {
    1: "Good",
    2: "Yielding",
    3: "Soft",
    4: "Heavy",
}

SEASON_NAMES = {
    1: "Spring",
    2: "Summer",
    3: "Fall",
    4: "Winter",
    5: "CherryBlossom",
}

DISTANCE_TYPE_NAMES = {
    "Sprint": "Short",
    "Mile": "Mile",
    "Medium": "Middle",
    "Long": "Long",
}

DISTANCE_METERS = {
    "Sprint": 1200,
    "Mile": 1600,
    "Medium": 2000,
    "Long": 3000,
}

GRADE_VALUES = {
    "G1": 100,
    "G2": 200,
    "G3": 300,
    "OP": 400,
    "Pre-OP": 700,
}

APTITUDE_NAMES = {
    1: "G",
    2: "F",
    3: "E",
    4: "D",
    5: "C",
    6: "B",
    7: "A",
    8: "S",
}

RESPONSE_HORSE_FIELDS = [
    "trainer_name",
    "owner_trainer_name",
    "single_mode_chara_id",
    "trained_chara_id",
    "nickname_id",
    "card_id",
    "chara_id",
    "rarity",
    "talent_level",
    "frame_order",
    "skill_array",
    "stamina",
    "speed",
    "pow",
    "guts",
    "wiz",
    "running_style",
    "race_dress_id",
    "chara_color_type",
    "npc_type",
    "final_grade",
    "popularity",
    "popularity_mark_rank_array",
    "proper_distance_short",
    "proper_distance_mile",
    "proper_distance_middle",
    "proper_distance_long",
    "proper_running_style_nige",
    "proper_running_style_senko",
    "proper_running_style_sashi",
    "proper_running_style_oikomi",
    "proper_ground_turf",
    "proper_ground_dirt",
    "motivation",
    "mob_id",
    "win_saddle_id_array",
    "race_result_array",
    "team_id",
    "team_member_id",
    "item_id_array",
    "motivation_change_flag",
    "frame_order_change_flag",
    "team_rank",
    "single_mode_win_count",
]


def runtime_output_root(base_dir):
    override = None
    try:
        import os

        override = os.environ.get("UMA_RUNTIME_DIR")
    except Exception:
        override = None
    if override:
        return Path(override).expanduser().resolve()

    base = Path(base_dir).resolve()
    for candidate in (base, *base.parents):
        if (candidate / ".git").exists():
            return candidate / "uma_runtime"
    return base.parent / "uma_runtime"


def parse_local_iso(value):
    if not value:
        return None
    return datetime.fromisoformat(str(value))


def safe_int(value, default=0):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return default


def clean_filename(value):
    text = re.sub(r"[^\w .()\\-]+", "_", str(value or ""), flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or "race"


def load_chara_names(project_root):
    path = Path(project_root) / "data" / "chara_list.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def race_id_from_instance(race_instance_id):
    race_instance_id = safe_int(race_instance_id)
    if race_instance_id <= 0:
        return 0
    return race_instance_id // 100


def race_instance_id_for_program(program_id):
    global _RACE_PROGRAM_INSTANCE_CACHE
    program_id = safe_int(program_id)
    if not program_id:
        return 0
    if _RACE_PROGRAM_INSTANCE_CACHE is None:
        cache = {}
        path = PROJECT_ROOT / "data" / "race_map.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except Exception:
            data = {}
        for raw_program_id, row in (data.get("program") or {}).items():
            rid = safe_int(raw_program_id)
            instance_id = safe_int((row or {}).get("race_instance_id"))
            if rid and instance_id:
                cache[rid] = instance_id
        for row in (data.get("meta") or {}).values():
            rid = safe_int((row or {}).get("program_id"))
            instance_id = safe_int((row or {}).get("race_instance_id"))
            if rid and instance_id:
                cache.setdefault(rid, instance_id)
        _RACE_PROGRAM_INSTANCE_CACHE = cache
    return _RACE_PROGRAM_INSTANCE_CACHE.get(program_id, 0)


def chara_name(raw, chara_names):
    card_id = safe_int(raw.get("card_id"))
    chara_id = safe_int(raw.get("chara_id"))
    if card_id and str(card_id) in chara_names:
        return chara_names[str(card_id)]
    outfit_id = chara_id * 100 + 1
    if outfit_id and str(outfit_id) in chara_names:
        return chara_names[str(outfit_id)]
    if chara_id and str(chara_id) in chara_names:
        return chara_names[str(chara_id)]
    if raw.get("trainer_name"):
        return str(raw.get("trainer_name"))
    return f"Chara {chara_id or raw.get('mob_id') or '?'}"


def aptitude_name(value):
    return APTITUDE_NAMES.get(safe_int(value), "G")


def active_distance_aptitude(raw, distance_type):
    key_by_distance = {
        "Short": "proper_distance_short",
        "Mile": "proper_distance_mile",
        "Middle": "proper_distance_middle",
        "Long": "proper_distance_long",
    }
    return aptitude_name(raw.get(key_by_distance.get(distance_type, "proper_distance_middle")))


def active_ground_aptitude(raw, meta):
    key = "proper_ground_dirt" if (meta.get("terrain") or "").lower() == "dirt" else "proper_ground_turf"
    return aptitude_name(raw.get(key))


def horseact_race_param(raw):
    return {
        BACKING("RawSpeed"): safe_int(raw.get("speed")),
        BACKING("RawStamina"): safe_int(raw.get("stamina")),
        BACKING("RawPow"): safe_int(raw.get("pow")),
        BACKING("RawGuts"): safe_int(raw.get("guts")),
        BACKING("RawWiz"): safe_int(raw.get("wiz")),
        BACKING("BaseSpeed"): safe_int(raw.get("speed")),
        BACKING("BaseStamina"): safe_int(raw.get("stamina")),
        BACKING("BasePow"): safe_int(raw.get("pow")),
        BACKING("BaseGuts"): safe_int(raw.get("guts")),
        BACKING("BaseWiz"): safe_int(raw.get("wiz")),
        BACKING("Motivation"): safe_int(raw.get("motivation")),
        BACKING("MotivationCoef"): 1.0,
    }


def horseact_response_horse(raw):
    return {key: raw.get(key) for key in RESPONSE_HORSE_FIELDS if key in raw}


def horseact_race_record(raw):
    results = raw.get("race_result_array") or []
    return {
        BACKING("IsUndefeated"): all(safe_int(item.get("result_rank")) == 1 for item in results) if results else False,
        BACKING("WinRaceInstanceIdList"): list(raw.get("win_saddle_id_array") or []),
        "_raceInstanceIdList": [
            race_instance_id_for_program(item.get("program_id")) or safe_int(item.get("race_instance_id"))
            for item in results
            if safe_int(item.get("program_id")) or safe_int(item.get("race_instance_id"))
        ],
    }


def choose_player_index(horses):
    for index, raw in enumerate(horses):
        if safe_int(raw.get("viewer_id")):
            return index
    return 0


def finish_orders(num_horses, player_index, player_rank):
    player_rank = safe_int(player_rank) or 1
    orders = []
    next_rank = 1
    for index in range(num_horses):
        if index == player_index:
            orders.append(player_rank)
            continue
        if next_rank == player_rank:
            next_rank += 1
        orders.append(next_rank)
        next_rank += 1
    return orders


def horseact_horse(raw, index, finish_order, meta, chara_names):
    marks = list(raw.get("popularity_mark_rank_array") or [])
    distance_type = DISTANCE_TYPE_NAMES.get(meta.get("distance"), meta.get("distance") or "Middle")
    race_dress_id = safe_int(raw.get("race_dress_id") or raw.get("card_id"))
    return {
        "horseIndex": index,
        "postNumber": safe_int(raw.get("frame_order") or index + 1),
        "charaId": safe_int(raw.get("chara_id")),
        BACKING("charaName"): chara_name(raw, chara_names),
        "FinishOrder": safe_int(finish_order),
        "FinishTimeRaw": 0.0,
        "FinishTimeScaled": 0.0,
        "FinishDiffTimeFromPrev": 0.0,
        "_raceParam": horseact_race_param(raw),
        "_responseHorseData": horseact_response_horse(raw),
        BACKING("Popularity"): safe_int(raw.get("popularity")),
        BACKING("PopularityRankLeft"): safe_int(marks[0]) if len(marks) > 0 else 0,
        BACKING("PopularityRankCenter"): safe_int(marks[1]) if len(marks) > 1 else 0,
        BACKING("PopularityRankRight"): safe_int(marks[2]) if len(marks) > 2 else 0,
        "_gateInPopularity": safe_int(marks[1]) if len(marks) > 1 else 0,
        BACKING("Rarity"): f"Rare{safe_int(raw.get('rarity')) or 0}",
        BACKING("TrainerName"): raw.get("trainer_name") or None,
        "IsGhost": False,
        "_isRunningStyleExInitialized": True,
        "_runningStyleEx": "None",
        BACKING("Defeat"): "None",
        BACKING("RaceDressId"): race_dress_id,
        BACKING("RaceDressIdWithOption"): race_dress_id,
        BACKING("RunningType"): "Pitch",
        BACKING("ActiveProperDistance"): active_distance_aptitude(raw, distance_type),
        BACKING("ActiveProperGroundType"): active_ground_aptitude(raw, meta),
        BACKING("MobId"): safe_int(raw.get("mob_id")),
        "_raceRecord": horseact_race_record(raw),
        BACKING("FinishOrderRawScore"): 0,
        BACKING("TrainedCharaData"): None,
    }


def horseact_course(meta, start_info):
    distance = DISTANCE_METERS.get(meta.get("distance"), 1600)
    race_instance_id = safe_int(meta.get("race_instance_id"))
    race_id = race_id_from_instance(race_instance_id) or safe_int(meta.get("race_id"))
    grade = meta.get("grade") or ""
    return {
        "race_course_set": {
            "Id": 0,
            "RaceTrackId": 0,
            "Distance": distance,
            "Ground": 2 if (meta.get("terrain") or "").lower() == "dirt" else 1,
            "Inout": 0,
            "Turn": 0,
            "FenceSet": 0,
            "FloatLaneMax": 0,
            "CourseSetStatusId": 1,
            "FinishTimeMin": 0,
            "FinishTimeMinRandomRange": 0,
            "FinishTimeMax": 0,
            "FinishTimeMaxRandomRange": 0,
        },
        "fence_set": {
            "Id": 0,
            "Fence1": 0,
            "Fence2": 0,
            "Fence3": 0,
            "Fence4": 0,
            "Fence5": 0,
            "Fence6": 0,
            "Fence7": 0,
            "Fence8": 0,
        },
        "race_track": {
            "Id": 0,
            "InitialLaneType": "ExtraSpaceAfter9",
            "EnableHalfGate": False,
            "HorseNumGateVariation": False,
            "TurfVisionType": "URA",
            "FootsmokeColorType": 0,
            "Area": 0,
            "FlagType": 0,
            "GatePanelType": 0,
            "GateLampType": 0,
        },
        "race_master": {
            "Id": race_id,
            "Group": 1,
            "Grade": GRADE_VALUES.get(grade, 0),
            "CourseSet": 0,
            "ThumbnailId": race_id,
            "FfCueName": "",
            "FfCuesheetName": "",
            "FfAnim": race_id,
            "FfCamera": 0,
            "FfCameraSub": 0,
            "FfSub": 0,
            "GoalGate": 0,
            "GoalFlower": 0,
            "Audience": 0,
            "EntryNum": 0,
        },
        "race_instance_master": {
            "Id": race_instance_id,
            "RaceId": race_id,
            "NpcGroupId": 0,
            "Date": 0,
            "Time": 2,
            "ClockTime": 0,
            "RaceNumber": 11,
        },
        "distance": float(distance),
    }


def build_horseact_payload(record, meta, chara_names, career_result=None):
    start_info = record.get("race_start_info") or {}
    reward_info = record.get("race_end_info") or {}
    raw_horses = list(record.get("race_horse_data_array") or [])
    player_index = choose_player_index(raw_horses)
    player_rank = safe_int((career_result or {}).get("finish_rank") or record.get("finish_rank") or reward_info.get("result_rank") or 1)
    orders = finish_orders(len(raw_horses), player_index, player_rank)
    horses = [
        horseact_horse(raw, index, orders[index], meta, chara_names)
        for index, raw in enumerate(raw_horses)
    ]
    player_horse = horses[player_index] if horses else None
    sorted_by_finish = sorted(horses, key=lambda horse: (safe_int(horse.get("FinishOrder")), safe_int(horse.get("horseIndex"))))
    sorted_by_popularity = sorted(horses, key=lambda horse: (safe_int(horse.get(BACKING("Popularity"))) or 999, safe_int(horse.get("horseIndex"))))
    winner = sorted_by_finish[0] if sorted_by_finish else player_horse
    course = horseact_course(meta, start_info)
    distance = course["distance"]
    phase = {
        BACKING("PhaseMiddleStartDistance"): distance / 6.0,
        BACKING("PhaseEndStartDistance"): distance * 2.0 / 3.0,
        BACKING("PhaseLastStartDistance"): distance * 5.0 / 6.0,
        "_courseDistance": distance,
        "_isInitialized": True,
    }
    race_id = race_id_from_instance(meta.get("race_instance_id")) or safe_int(meta.get("race_id"))
    payload = {
        BACKING("RaceType"): "Single",
        BACKING("IsExistPlayerRace"): True,
        BACKING("IsExistGhostRace"): False,
        BACKING("IsExistFollowRace"): False,
        BACKING("IsMultiplePlayerRace"): False,
        BACKING("RandomSeed"): safe_int(start_info.get("random_seed")),
        BACKING("SingleRaceProgramId"): safe_int(record.get("program_id")),
        BACKING("IsSingleRaceExportRetryEnable"): False,
        BACKING("SingleRaceRetryCount"): safe_int(start_info.get("continue_num")),
        BACKING("OpponentEvaluate"): 0,
        BACKING("SelfEvaluate"): 0,
        BACKING("SupportCardScoreBonus"): 0,
        BACKING("ScoreCalcTeamId"): 0,
        BACKING("RaceNo"): 11,
        BACKING("RaceCourseSet"): course["race_course_set"],
        BACKING("FenceSet"): course["fence_set"],
        BACKING("RaceTrack"): course["race_track"],
        BACKING("GoalGate"): 0,
        BACKING("GoalGateFlower"): 0,
        BACKING("InitialLaneType"): "ExtraSpaceAfter9",
        BACKING("RotationCategory"): "Right",
        BACKING("GroundTypeAvailable"): "TurfAndDirt",
        BACKING("CourseSectionDistance"): distance / 24.0,
        BACKING("CourseDistanceType"): DISTANCE_TYPE_NAMES.get(meta.get("distance"), meta.get("distance") or "Middle"),
        BACKING("CourseFurlongNum"): int(distance / 200),
        BACKING("IsHalfGate"): False,
        BACKING("IsHorseNumVariationGate"): False,
        BACKING("TurfVisionType"): "URA",
        BACKING("GroundCondition"): GROUND_CONDITION_NAMES.get(safe_int(start_info.get("ground_condition")), "Good"),
        BACKING("Weather"): WEATHER_NAMES.get(safe_int(start_info.get("weather")), "Sunny"),
        BACKING("Season"): SEASON_NAMES.get(safe_int(start_info.get("season")), "Spring"),
        BACKING("Time"): "Daytime",
        "_baseSpeed": -1.0,
        BACKING("BorderTimeScaled"): 0.0,
        BACKING("ChallengeMatchDifficulty"): "Easy",
        BACKING("NumRaceHorses"): len(horses),
        BACKING("PostNumberMax"): 8,
        "_playerHorseIndex": player_index,
        BACKING("PlayerTeamMemberArray"): [player_horse] if player_horse else [],
        BACKING("PlayerTeamTopFinishOrderHorse"): player_horse,
        BACKING("IsGateInPopularityInitialized"): True,
        BACKING("RaceHorse"): horses,
        BACKING("RaceBibMaster"): {
            "Grade": GRADE_VALUES.get(meta.get("grade"), 0),
            "RaceId": race_id,
            "BibColor": 0,
            "FontColor": 0,
        },
        "_raceMaster": course["race_master"],
        "_raceInstanceMaster": course["race_instance_master"],
        BACKING("SimDataBase64"): record.get("race_scenario"),
        BACKING("EpisodeRaceReplayId"): 0,
        BACKING("IsNotSimulateExport"): False,
        BACKING("LaneDistanceMax"): 0.0,
        BACKING("ReplayCheckInfo"): {
            "RewardSetArray": None,
            "RewardPlusBonusSetArray": None,
            "BonusRewardSetArray": None,
            "BonusRewardWinSetArray": None,
            "IsItemNumLimit": False,
        },
        BACKING("ReplayCheckInfoDaily"): None,
        BACKING("ReplayCheckInfoLegend"): None,
        BACKING("IsDailyLegendRace"): False,
        BACKING("ReplayCheckInfoChallengeMatch"): None,
        "RaceRewardSingle": {
            "reward": None,
            "RaceGainedFanCount": safe_int(reward_info.get("gained_fans")),
            "RaceAfterPlayer": None,
        },
        BACKING("ResultHorseIndex"): safe_int((winner or {}).get("horseIndex")),
        BACKING("PrevGradeType"): "None",
        BACKING("MainStoryRaceGimmickType"): "None",
        BACKING("IsMainStoryRaceMatchGimmick"): False,
        "_phaseCalculator": phase,
        BACKING("HorseIndexByFinishOrder"): [safe_int(horse.get("horseIndex")) for horse in sorted_by_finish],
        BACKING("HorseIndexByPopularity"): [safe_int(horse.get("horseIndex")) for horse in sorted_by_popularity],
        "horseACT_version": "1.1.2",
    }
    return payload


def newest_trace(trace_dir, started=None, ended=None):
    traces = sorted(trace_dir.glob("*.jsonl"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not traces:
        raise FileNotFoundError(f"No trace payload files found in {trace_dir}")
    if not started or not ended:
        return traces[0]
    start = started - timedelta(minutes=2)
    stop = ended + timedelta(minutes=2)
    candidates = []
    for path in traces:
        modified = datetime.fromtimestamp(path.stat().st_mtime)
        if modified >= start and modified <= stop + timedelta(minutes=15):
            candidates.append(path)
    return candidates[0] if candidates else traces[0]


def load_career_results(path):
    report = json.loads(path.read_text(encoding="utf-8"))
    final_results = {}
    attempt_results = {}
    for turn in report.get("turns") or []:
        for event in turn.get("events") or []:
            event_name = event.get("event")
            if event_name not in {"race_result", "g1_result", "race_attempt_result"}:
                continue
            key = (safe_int(event.get("turn")), safe_int(event.get("program_id")))
            if key[0] and key[1]:
                result = {
                    "turn": key[0],
                    "program_id": key[1],
                    "finish_rank": safe_int(event.get("finish_rank")),
                    "won": bool(event.get("won")),
                    "status": event.get("status"),
                    "label": event.get("label"),
                    "is_g1": bool(event.get("is_g1")),
                    "race": event.get("race") or {},
                }
                for extra_key in (
                    "attempt",
                    "continue_attempt",
                    "continue_type",
                    "continued_with",
                    "continued",
                    "continue_attempts",
                    "continue_resources",
                    "continue_resource",
                    "continue_failed_ranks",
                ):
                    if extra_key in event:
                        result[extra_key] = event.get(extra_key)
                if event_name == "race_attempt_result":
                    attempt = safe_int(event.get("attempt")) or 1
                    attempt_results[(key[0], key[1], attempt)] = result
                elif event_name == "race_result":
                    final_results[key] = result
                elif key not in final_results:
                    final_results[key] = result
    return report, {"final": final_results, "attempts": attempt_results}


def trace_rows(path, started=None, ended=None):
    start_ts = (started - timedelta(seconds=2)).timestamp() if started else None
    end_ts = (ended + timedelta(minutes=1)).timestamp() if ended else None
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, 1):
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = row.get("ts")
            if start_ts is not None and ts is not None and float(ts) < start_ts:
                continue
            if end_ts is not None and ts is not None and float(ts) > end_ts:
                continue
            row["_line_number"] = line_number
            yield row


def find_latest_open(records, turn, program_id=0):
    for record in reversed(records):
        if record.get("current_turn") != turn or record.get("race_end_info"):
            continue
        if program_id and safe_int(record.get("program_id")) != safe_int(program_id):
            continue
        return record
    return None


def find_latest_record(records, turn, program_id=0):
    for record in reversed(records):
        if record.get("current_turn") != turn:
            continue
        if program_id and safe_int(record.get("program_id")) != safe_int(program_id):
            continue
        return record
    return None


def clone_retry_record(previous, turn, program_id, start_info=None, line_number=None, continue_type=0):
    start_info = start_info or {}
    previous = previous or {}
    base_start_info = start_info or previous.get("race_start_info") or {}
    return {
        "current_turn": turn,
        "program_id": safe_int(program_id or base_start_info.get("program_id") or previous.get("program_id")),
        "race_start_info": base_start_info,
        "race_horse_data_array": base_start_info.get("race_horse_data") or previous.get("race_horse_data_array") or [],
        "continue_line": line_number,
        "continue_type": safe_int(continue_type),
        "continued_from_end_line": previous.get("end_line"),
    }


def extract_races(trace_path, started=None, ended=None):
    requests = {}
    records = []
    for row in trace_rows(trace_path, started, ended):
        endpoint = row.get("endpoint")
        direction = row.get("direction")
        req_id = row.get("req_id")
        if direction == "REQ":
            requests[req_id] = ((row.get("data") or {}).get("payload") or {})
            continue
        if direction != "RES":
            continue
        payload = requests.get(req_id) or {}
        data = ((row.get("data") or {}).get("data") or {})
        turn = safe_int(payload.get("current_turn"))

        if endpoint == "single_mode_free/race_entry":
            info = data.get("race_start_info") or {}
            program_id = safe_int(payload.get("program_id") or info.get("program_id"))
            records.append({
                "current_turn": turn,
                "program_id": program_id,
                "race_start_info": info,
                "race_horse_data_array": info.get("race_horse_data") or [],
                "entry_line": row.get("_line_number"),
            })
            continue

        if endpoint == "single_mode_free/continue":
            info = data.get("race_start_info") or {}
            program_id = safe_int(info.get("program_id"))
            previous = find_latest_record(records, turn, program_id)
            if not program_id and previous:
                program_id = safe_int(previous.get("program_id"))
            records.append(clone_retry_record(
                previous,
                turn,
                program_id,
                start_info=info,
                line_number=row.get("_line_number"),
                continue_type=payload.get("continue_type"),
            ))
            continue

        if endpoint == "single_mode_free/race_start":
            start_info = data.get("race_start_info") or {}
            program_id = safe_int(start_info.get("program_id"))
            record = find_latest_open(records, turn, program_id)
            if not record:
                previous = find_latest_record(records, turn, program_id)
                if not previous:
                    continue
                record = clone_retry_record(
                    previous,
                    turn,
                    program_id or previous.get("program_id"),
                    start_info=start_info or previous.get("race_start_info") or {},
                    line_number=row.get("_line_number"),
                )
                records.append(record)
            record["race_start_response_info"] = start_info
            record["race_scenario"] = data.get("race_scenario")
            record["start_line"] = row.get("_line_number")
            if not record.get("program_id"):
                record["program_id"] = safe_int(start_info.get("program_id"))
            continue

        if endpoint == "single_mode_free/race_end":
            record = find_latest_open(records, turn)
            if not record:
                continue
            reward = data.get("race_reward_info") or {}
            record["race_end_info"] = reward
            record["race_history"] = data.get("race_history") or []
            record["end_line"] = row.get("_line_number")
            record["finish_rank"] = safe_int(reward.get("result_rank"))
            continue

    complete = [
        record for record in records
        if record.get("race_scenario") and record.get("race_horse_data_array")
    ]
    deduped = []
    seen = set()
    attempt_counts = {}
    for record in complete:
        key = (
            safe_int(record.get("current_turn")),
            safe_int(record.get("program_id")),
            safe_int(record.get("entry_line")),
            safe_int(record.get("continue_line")),
            safe_int(record.get("start_line")),
            safe_int(record.get("end_line")),
        )
        if key in seen:
            continue
        seen.add(key)
        attempt_key = (safe_int(record.get("current_turn")), safe_int(record.get("program_id")))
        if record.get("continue_line") or record.get("continued_from_end_line"):
            attempt_counts[attempt_key] = max(1, attempt_counts.get(attempt_key, 1)) + 1
        else:
            attempt_counts[attempt_key] = 1
        record["race_attempt_index"] = attempt_counts[attempt_key]
        deduped.append(record)
    return deduped


def is_truncated_trace_string(value):
    return isinstance(value, str) and value.endswith("...<truncated>")


def race_metadata(planner, program_id):
    race = dict(planner.catalog.by_program_id.get(safe_int(program_id)) or {})
    program = dict((planner.program or {}).get(safe_int(program_id)) or {})
    race_instance_id = safe_int(race.get("race_instance_id") or program.get("race_instance_id"))
    return {
        "program_id": safe_int(program_id),
        "race_id": safe_int(race.get("id") or program.get("race_id")),
        "race_instance_id": race_instance_id,
        "name": race.get("name") or program.get("name") or "",
        "date": race.get("date") or "",
        "turn": safe_int(race.get("turn") or program.get("turn")),
        "grade": race.get("type") or "",
        "terrain": race.get("terrain") or "",
        "distance": race.get("distance") or "",
        "venue": race.get("venue") or "",
    }


def build_hakuraku_payload(record, meta, career_result=None):
    start_info = record.get("race_start_info") or {}
    payload = {
        "format": "sweepy_hakuraku_race_v1",
        "horseACT_version": "sweepy-api-trace",
        "race_type": "Single",
        "program_id": safe_int(record.get("program_id")),
        "current_turn": safe_int(record.get("current_turn")),
        "race": meta,
        "race_name": meta.get("name") or str(record.get("program_id")),
        "race_instance_id": meta.get("race_instance_id"),
        "random_seed": start_info.get("random_seed"),
        "season": start_info.get("season"),
        "weather": start_info.get("weather"),
        "ground_condition": start_info.get("ground_condition"),
        "race_scenario": record.get("race_scenario"),
        "race_horse_data_array": record.get("race_horse_data_array") or [],
        "race_start_info": start_info,
        "race_reward_info": record.get("race_end_info") or {},
        "race_history": record.get("race_history") or [],
    }
    if career_result:
        payload["career_report_result"] = career_result
    return payload


def result_from_record(record, meta):
    rank = safe_int(record.get("finish_rank") or (record.get("race_end_info") or {}).get("result_rank"))
    return {
        "turn": safe_int(record.get("current_turn")),
        "program_id": safe_int(record.get("program_id")),
        "attempt": safe_int(record.get("race_attempt_index")) or 1,
        "finish_rank": rank,
        "won": rank == 1 if rank else False,
        "status": "won" if rank == 1 else "lost" if rank else "unknown",
        "label": f"{'WON' if rank == 1 else 'LOST'} #{rank}" if rank else "",
        "is_g1": str(meta.get("grade") or "").upper() == "G1",
        "race": meta,
    }


def export_races(project_root, career_log=None, trace_path=None, output_dir=None, clean=True, preserve_existing_on_empty=True, trace_root=None):
    project_root = Path(project_root).resolve()
    runtime_root = runtime_output_root(project_root)
    career_log = Path(career_log) if career_log else runtime_root / "bot_logs" / "latest_career_log.json"
    report, career_result_data = load_career_results(career_log)
    career_results = career_result_data.get("final", {})
    career_attempt_results = career_result_data.get("attempts", {})
    started = parse_local_iso(report.get("started_at"))
    ended = parse_local_iso(report.get("ended_at"))

    if trace_path:
        trace_path = Path(trace_path)
    else:
        # When the runner passes an instance-specific runtime (e.g.,
        # uma_runtime/instances/account_b), per-account trace files live
        # there, not at the project-root-level uma_runtime/trace_logs.
        # Probe the instance path first; fall back to the project-root
        # path if the instance has no trace_logs directory.
        candidate_roots = []
        if trace_root:
            candidate_roots.append(Path(trace_root) / "trace_logs" / "api_payloads")
        candidate_roots.append(runtime_root / "trace_logs" / "api_payloads")
        trace_path = None
        for candidate in candidate_roots:
            if candidate.exists():
                resolved = newest_trace(candidate, started, ended)
                if resolved:
                    trace_path = resolved
                    break

    planner = RacePlanner(project_root)
    chara_names = load_chara_names(project_root)
    records = extract_races(trace_path, started, ended)
    out_root = Path(output_dir) if output_dir else runtime_root / "hakuraku_races" / career_log.stem
    all_dir = out_root / "all"
    loss_dir = out_root / "g1_losses"
    if preserve_existing_on_empty and not records and out_root.exists():
        manifest = {
            "format": "sweepy_hakuraku_race_manifest_v1",
            "career_log": str(career_log),
            "trace_file": str(trace_path),
            "started_at": report.get("started_at"),
            "ended_at": report.get("ended_at"),
            "total_exported": 0,
            "skipped_truncated_race_scenario": [],
            "races": [],
            "g1_losses": [],
            "all_races_dir": str(all_dir),
            "g1_losses_dir": str(loss_dir),
            "preserved_existing_export": True,
            "preserve_reason": "no_race_payloads",
        }
        out_root.mkdir(parents=True, exist_ok=True)
        (out_root / "manifest.empty.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    out_root.mkdir(parents=True, exist_ok=True)
    for path in (all_dir, loss_dir):
        if clean and path.exists():
            shutil.rmtree(path)
        path.mkdir(parents=True, exist_ok=True)
    final_attempt_by_race = {}
    for record in records:
        key = (safe_int(record.get("current_turn")), safe_int(record.get("program_id")))
        final_attempt_by_race[key] = max(
            final_attempt_by_race.get(key, 0),
            safe_int(record.get("race_attempt_index")) or 1,
        )
    written = []
    losses = []
    race_manifest_rows = []
    skipped_truncated = []
    for index, record in enumerate(records, 1):
        if is_truncated_trace_string(record.get("race_scenario")):
            skipped_truncated.append({
                "turn": safe_int(record.get("current_turn")),
                "program_id": safe_int(record.get("program_id")),
            })
            continue
        program_id = safe_int(record.get("program_id"))
        turn = safe_int(record.get("current_turn"))
        meta = race_metadata(planner, program_id)
        attempt = safe_int(record.get("race_attempt_index")) or 1
        career_result = career_attempt_results.get((turn, program_id, attempt))
        if not career_result and attempt == final_attempt_by_race.get((turn, program_id)):
            career_result = career_results.get((turn, program_id))
        if not career_result:
            career_result = result_from_record(record, meta)
        payload = build_horseact_payload(record, meta, chara_names, career_result)
        result = career_result or {}
        rank = safe_int(result.get("finish_rank") or record.get("finish_rank"))
        won = bool(result.get("won")) if "won" in result else rank == 1
        outcome = "won" if won else "lost" if rank else "race"
        grade = meta.get("grade") or "UNK"
        name = clean_filename(meta.get("name") or f"program_{program_id}")
        filename = f"T{turn:02d}_{grade}_{outcome}_rank{rank or 'x'}_attempt{attempt}_{program_id}_{name}.json"
        path = all_dir / filename
        if path.exists():
            filename = f"R{index:02d}_{filename}"
            path = all_dir / filename
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)
        manifest_row = {
            "file": str(path),
            "turn": turn,
            "program_id": program_id,
            "race": meta,
            "attempt": attempt,
            "finish_rank": rank,
            "won": won,
            "status": result.get("status") or outcome,
            "label": result.get("label") or "",
            "continue_type": safe_int(record.get("continue_type")),
            "continued_with": result.get("continued_with"),
            "continue_attempt": result.get("continue_attempt"),
            "continued": bool(result.get("continued")),
            "continue_attempts": safe_int(result.get("continue_attempts")),
            "continue_failed_ranks": result.get("continue_failed_ranks") or [],
        }
        race_manifest_rows.append(manifest_row)
        if result.get("is_g1") and won is False:
            loss_path = loss_dir / filename
            shutil.copyfile(path, loss_path)
            losses.append(loss_path)

    manifest = {
        "format": "sweepy_hakuraku_race_manifest_v1",
        "career_log": str(career_log),
        "trace_file": str(trace_path),
        "started_at": report.get("started_at"),
        "ended_at": report.get("ended_at"),
        "total_exported": len(written),
        "skipped_truncated_race_scenario": skipped_truncated,
        "races": race_manifest_rows,
        "g1_losses": [str(path) for path in losses],
        "all_races_dir": str(all_dir),
        "g1_losses_dir": str(loss_dir),
    }
    (out_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description="Export Sweepy API trace races into Hakuraku Race Analysis JSON files.")
    parser.add_argument("--project-root", default=Path(__file__).resolve().parents[1])
    parser.add_argument("--career-log", default=None)
    parser.add_argument("--trace", default=None)
    parser.add_argument("--output-dir", default=None)
    args = parser.parse_args()

    manifest = export_races(
        project_root=Path(args.project_root),
        career_log=args.career_log,
        trace_path=args.trace,
        output_dir=args.output_dir,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
