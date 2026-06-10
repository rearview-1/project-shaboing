import json
import re
from pathlib import Path

from career_bot.unique_race_modifiers import (
    CAREER_INVISIBLE_STAT_BONUS,
    race_unique_recovery_profile,
)


STYLE_ALIASES = {
    "front": "front_runner",
    "front runner": "front_runner",
    "nige": "front_runner",
    "pace": "pace_chaser",
    "pace chaser": "pace_chaser",
    "senko": "pace_chaser",
    "late": "late_surger",
    "late surger": "late_surger",
    "sashi": "late_surger",
    "closer": "end_closer",
    "end closer": "end_closer",
    "end": "end_closer",
    "oikomi": "end_closer",
}

TACTIC_TO_STYLE = {
    1: "front_runner",
    2: "pace_chaser",
    3: "late_surger",
    4: "end_closer",
}
STYLE_TO_TACTIC = {style: value for value, style in TACTIC_TO_STYLE.items()}

# Short, UI-friendly labels for the four running styles. Used in race
# result records (turn data → race_result.running_style_label) so the
# operator can see at a glance which style was used for a given race
# without decoding `front_runner`/`pace_chaser`/etc.
STYLE_DISPLAY_LABEL = {
    "front_runner": "Front",
    "pace_chaser": "Pace",
    "late_surger": "Late",
    "end_closer": "End",
}


def running_style_label(value) -> str:
    """Map any of (numeric tactic 1-4, snake_case style, display label,
    empty) to the short UI label. Returns "" for unrecognised input."""
    if value is None or value == "":
        return ""
    # Numeric tactic code
    try:
        as_int = int(value)
        canonical = TACTIC_TO_STYLE.get(as_int)
        if canonical:
            return STYLE_DISPLAY_LABEL.get(canonical, "")
    except (TypeError, ValueError):
        pass
    # snake_case style
    text = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if text in STYLE_DISPLAY_LABEL:
        return STYLE_DISPLAY_LABEL[text]
    # Already a display label?
    title = str(value).strip().title()
    if title in {"Front", "Pace", "Late", "End"}:
        return title
    return ""

DISTANCE_REQUIREMENTS = {
    "Sprint": {"speed": 360, "stamina": 140, "power": 320, "guts": 180, "wit": 170},
    "Mile": {"speed": 420, "stamina": 230, "power": 350, "guts": 200, "wit": 190},
    "Medium": {"speed": 480, "stamina": 370, "power": 380, "guts": 230, "wit": 210},
    "Long": {"speed": 520, "stamina": 520, "power": 400, "guts": 260, "wit": 230},
}

GRADE_FACTOR = {
    "G1": 1.12,
    "G2": 1.04,
    "G3": 0.98,
    "OP": 0.90,
    "PRE-OP": 0.84,
}

STYLE_FACTORS = {
    "front_runner": {"speed": 1.05, "stamina": 0.96, "power": 0.98, "guts": 1.00, "wit": 1.03},
    "pace_chaser": {"speed": 1.00, "stamina": 1.00, "power": 1.00, "guts": 1.00, "wit": 1.00},
    "late_surger": {"speed": 0.98, "stamina": 1.05, "power": 1.10, "guts": 1.04, "wit": 1.00},
    "end_closer": {"speed": 0.96, "stamina": 1.08, "power": 1.14, "guts": 1.07, "wit": 1.02},
}

STAMINA_RECOVERY_SKILL_GROUPS = {
    11011, 20035, 20038, 20048, 20055, 20056, 20071, 20074,
    20128, 20129, 20135, 20142, 20157, 20207, 91011,
}


def normalize_text(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def normalize_style(value):
    text = re.sub(r"[^a-z0-9 ]+", " ", str(value or "").lower())
    text = re.sub(r"\s+", " ", text).strip()
    return STYLE_ALIASES.get(text, "")


def skill_group_id(skill_id):
    try:
        skill_id = int(skill_id or 0)
    except (TypeError, ValueError):
        return 0
    return skill_id if skill_id < 100000 else skill_id // 10


def stamina_recovery_skill_count(chara):
    count = 0
    for row in chara.get("skill_array") or []:
        if skill_group_id(row.get("skill_id")) in STAMINA_RECOVERY_SKILL_GROUPS:
            count += 1
    return count


class RaceCatalog:
    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.races = []
        self.by_id = {}
        self.by_program_id = {}
        self.by_name_key = {}
        self.date_keys = {}
        self._load()

    def _load(self):
        race_map_path = self.base_dir / "data" / "race_map.json"
        public_path = self.base_dir / "public" / "assets" / "data" / "uma_race_data.json"
        race_map = {}
        if race_map_path.exists():
            race_map = json.loads(race_map_path.read_text(encoding="utf-8"))
        meta = {int(k): v for k, v in (race_map.get("meta") or {}).items()}

        ui_races = []
        if public_path.exists():
            data = json.loads(public_path.read_text(encoding="utf-8"))
            ui_races = data.get("races") or []

        for row in ui_races:
            race_id = int(row.get("id") or 0)
            info = dict(row)
            info["id"] = race_id
            info["turn"] = self.date_to_turn(info.get("date"))
            if race_id in meta:
                info["program_id"] = int(meta[race_id].get("program_id") or 0)
                info["race_instance_id"] = int(meta[race_id].get("race_instance_id") or 0)
            self._add(info)

        for race_id, row in meta.items():
            if race_id in self.by_id:
                continue
            info = {
                "id": race_id,
                "name": row.get("name", ""),
                "date": self.turn_to_date(row.get("turn")),
                "turn": int(row.get("turn") or 0),
                "type": "",
                "terrain": "",
                "distance": "",
                "venue": "",
                "program_id": int(row.get("program_id") or 0),
                "race_instance_id": int(row.get("race_instance_id") or 0),
            }
            self._add(info)

        self.date_keys = {normalize_text(race.get("date")): race.get("date") for race in self.races if race.get("date")}

    def _add(self, info):
        race_id = int(info.get("id") or 0)
        if not race_id:
            return
        self.races.append(info)
        self.by_id[race_id] = info
        program_id = int(info.get("program_id") or 0)
        if program_id:
            self.by_program_id[program_id] = info
        self.by_name_key.setdefault(normalize_text(info.get("name")), []).append(info)

    def date_to_turn(self, date):
        text = str(date or "").strip()
        match = re.fullmatch(r"(Junior|Classic|Senior) Year (Early|Late) ([A-Za-z]+)", text)
        if not match:
            return 0
        year = {"Junior": 1, "Classic": 2, "Senior": 3}[match.group(1)]
        half = 0 if match.group(2) == "Early" else 1
        month = [
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"
        ].index(match.group(3)) + 1
        return (year - 1) * 24 + (month - 1) * 2 + half + 1

    def turn_to_date(self, turn):
        try:
            turn = int(turn or 0)
        except (TypeError, ValueError):
            return ""
        if turn <= 0:
            return ""
        year_idx = (turn - 1) // 24
        slot = (turn - 1) % 24
        month_idx = slot // 2
        half = "Early" if slot % 2 == 0 else "Late"
        years = ["Junior", "Classic", "Senior"]
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        if year_idx >= len(years):
            return ""
        return f"{years[year_idx]} Year {half} {months[month_idx]}"

    def parse_turn(self, value):
        text = str(value or "").strip()
        match = re.search(r"\bturn\s*(\d{1,2})\b", text, flags=re.I)
        if match:
            return int(match.group(1))
        if re.fullmatch(r"\d{1,2}", text):
            return int(text)
        return self.date_to_turn(text)

    def extract_date_prefix(self, line):
        key = normalize_text(line)
        for date_key, date in sorted(self.date_keys.items(), key=lambda item: -len(item[0])):
            if key.startswith(date_key):
                return date, line[len(date):].strip(" :-@")
            if key.endswith(date_key):
                return date, line[:-len(date)].strip(" :-@")
        return "", line

    def resolve(self, name, when=None):
        key = normalize_text(name)
        if not key:
            return None, "missing race name"
        if key.isdigit() and int(key) in self.by_id:
            race = self.by_id[int(key)]
            return race, ""
        candidates = self.by_name_key.get(key) or []
        if not candidates:
            partials = [race for race in self.races if key and key in normalize_text(race.get("name"))]
            candidates = partials
        if not candidates:
            return None, f"unknown race '{name}'"
        turn = self.parse_turn(when)
        if turn:
            turn_matches = [race for race in candidates if int(race.get("turn") or 0) == turn]
            if turn_matches:
                return turn_matches[0], ""
            return None, f"'{name}' is not available at {when}"
        if len(candidates) == 1:
            return candidates[0], ""
        options = ", ".join(f"{race.get('name')} ({race.get('date')})" for race in candidates[:4])
        return None, f"ambiguous race '{name}': {options}"

    def parse_plan_input(self, value):
        if isinstance(value, (list, dict)):
            return self.parse_plan_json(value)
        text = str(value or "").strip()
        if not text:
            return {"entries": [], "errors": []}
        if text[0] in "[{":
            try:
                return self.parse_plan_json(json.loads(text))
            except json.JSONDecodeError as exc:
                return {"entries": [], "errors": [{"line": 1, "text": text[:120], "error": str(exc)}]}
        return self.parse_plan_text(text)

    def parse_plan_json(self, value):
        rows = value.get("races") if isinstance(value, dict) else value
        if not isinstance(rows, list):
            return {"entries": [], "errors": [{"line": 1, "text": "", "error": "race plan JSON must be a list or object with races"}]}
        entries = []
        errors = []
        used_turns = {}
        for index, row in enumerate(rows, 1):
            if not isinstance(row, dict):
                errors.append({"line": index, "text": str(row), "error": "race entry must be an object"})
                continue
            name = row.get("raceName") or row.get("name") or row.get("race_name")
            when = self.json_row_date(row)
            style = normalize_style(row.get("style") or row.get("tactic") or row.get("strategy"))
            race, error = self.resolve(name, when)
            if error:
                errors.append({"line": index, "text": str(row), "error": error})
                continue
            turn = int(race.get("turn") or 0)
            if turn in used_turns:
                errors.append({
                    "line": index,
                    "text": str(row),
                    "error": f"turn {turn} already has {used_turns[turn]}"
                })
                continue
            used_turns[turn] = race.get("name")
            entry = self.entry_from_race(race, style, row)
            entries.append(entry)
        entries.sort(key=lambda item: (item["turn"], item["race_id"]))
        return {"entries": entries, "errors": errors}

    def json_row_date(self, row):
        if row.get("date"):
            return row.get("date")
        year_text = str(row.get("year") or "").strip().lower()
        year = {
            "first year": "Junior",
            "junior year": "Junior",
            "junior": "Junior",
            "second year": "Classic",
            "classic year": "Classic",
            "classic": "Classic",
            "third year": "Senior",
            "senior year": "Senior",
            "senior": "Senior",
        }.get(year_text, "")
        turn = str(row.get("turn") or "").strip()
        match = re.fullmatch(r"(\d{1,2})[_/-](0?1|0?2)", turn)
        if not year or not match:
            return turn
        month_idx = int(match.group(1)) - 1
        half = "Early" if int(match.group(2)) == 1 else "Late"
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        if month_idx < 0 or month_idx >= len(months):
            return turn
        return f"{year} Year {half} {months[month_idx]}"

    def entry_from_race(self, race, style="", source=None):
        return {
            "race_id": int(race.get("id")),
            "program_id": int(race.get("program_id") or 0),
            "race_instance_id": int(race.get("race_instance_id") or 0),
            "turn": int(race.get("turn") or 0),
            "date": race.get("date", ""),
            "name": race.get("name", ""),
            "type": race.get("type", ""),
            "terrain": race.get("terrain", ""),
            "distance": race.get("distance", ""),
            "venue": race.get("venue", ""),
            "style": style or "",
            "source": source if isinstance(source, dict) else str(source or "").strip(),
        }

    def parse_plan_text(self, text):
        entries = []
        errors = []
        used_turns = {}
        for line_no, raw_line in enumerate(str(text or "").splitlines(), 1):
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            parsed = self.parse_line(line)
            race, error = self.resolve(parsed["name"], parsed.get("when"))
            if error:
                errors.append({"line": line_no, "text": raw_line, "error": error})
                continue
            turn = int(race.get("turn") or 0)
            if turn in used_turns:
                errors.append({
                    "line": line_no,
                    "text": raw_line,
                    "error": f"turn {turn} already has {used_turns[turn]}"
                })
                continue
            used_turns[turn] = race.get("name")
            entries.append(self.entry_from_race(race, parsed.get("style", ""), raw_line.strip()))
        entries.sort(key=lambda item: (item["turn"], item["race_id"]))
        return {"entries": entries, "errors": errors}

    def parse_line(self, line):
        style = ""
        style_match = re.search(r"\b(?:style|tactic)\s*[:=]\s*([a-zA-Z -]+)", line, flags=re.I)
        if style_match:
            style = normalize_style(style_match.group(1))
            line = (line[:style_match.start()] + line[style_match.end():]).strip(" |,-")

        parts = [part.strip() for part in re.split(r"\s+\|\s+", line) if part.strip()]
        line = parts[0] if parts else line
        for part in parts[1:]:
            maybe_style = normalize_style(part)
            if maybe_style:
                style = maybe_style
                continue
            if not self.parse_turn(part):
                continue
            return {"name": line, "when": part, "style": style}

        if "@" in line:
            left, right = [part.strip() for part in line.split("@", 1)]
            if self.parse_turn(left):
                return {"name": right, "when": left, "style": style}
            if self.parse_turn(right):
                return {"name": left, "when": right, "style": style}
            return {"name": left, "when": right, "style": style}

        for sep in (":", "-", "->"):
            if sep in line:
                left, right = [part.strip() for part in line.split(sep, 1)]
                if self.parse_turn(left):
                    return {"name": right, "when": left, "style": style}
                if self.parse_turn(right):
                    return {"name": left, "when": right, "style": style}

        date, rest = self.extract_date_prefix(line)
        if date and rest:
            return {"name": rest, "when": date, "style": style}

        turn_match = re.match(r"turn\s*(\d{1,2})\s+(.+)$", line, flags=re.I)
        if turn_match:
            return {"name": turn_match.group(2).strip(), "when": turn_match.group(1), "style": style}

        return {"name": line, "when": "", "style": style}


class RaceStaminaEstimator:
    def estimate(self, chara, race, style="", min_ratio=0.96):
        distance = race.get("distance") or "Medium"
        base_req = DISTANCE_REQUIREMENTS.get(distance, DISTANCE_REQUIREMENTS["Medium"])
        grade_factor = GRADE_FACTOR.get(race.get("type"), 0.94)
        style = style or self.style_from_chara(chara)
        style_factors = STYLE_FACTORS.get(style, {})
        unique_recovery = race_unique_recovery_profile(chara, distance=distance, style=style)
        stats = {
            "speed": int(chara.get("speed") or 0),
            "stamina": int(chara.get("stamina") or 0),
            "power": int(chara.get("power") or 0),
            "guts": int(chara.get("guts") or 0),
            "wit": int(chara.get("wiz") or chara.get("wit") or 0),
        }
        raw_stats = dict(stats)
        recovery_count = stamina_recovery_skill_count(chara)
        requirements = {}
        ratios = {}
        for stat, req in base_req.items():
            adjusted = req * grade_factor * float(style_factors.get(stat, 1.0))
            requirements[stat] = int(round(adjusted))
            if stat == "stamina" and distance in ("Medium", "Long"):
                # Approximate one reliable recovery skill as covering about 45% of the race's stamina target.
                recovery_equivalent = float(min(recovery_count, 2))
                recovery_equivalent += float(unique_recovery.get("skill_equivalent") or 0.0)
                if recovery_equivalent > 0.0:
                    stats["stamina"] += int(round(adjusted * 0.45 * min(recovery_equivalent, 2.25)))
            ratio = stats[stat] / adjusted if adjusted else 0.0
            ratios[stat] = ratio

        warnings = []
        stamina_low = ratios.get("stamina", 1) < float(min_ratio or 0.96) and distance in ("Medium", "Long")
        if stamina_low:
            warnings.append("stamina low")
        if recovery_count and distance in ("Medium", "Long"):
            warnings.append("stamina recovery skill counted")
        if unique_recovery and distance in ("Medium", "Long"):
            warnings.append(f"unique stamina recovery counted ({unique_recovery.get('name')})")

        return {
            "race_id": race.get("id"),
            "program_id": race.get("program_id"),
            "race_name": race.get("name"),
            "distance": distance,
            "grade": race.get("type", ""),
            "style": style,
            "requirements": requirements,
            "stats": stats,
            "raw_stats": raw_stats,
            "effective_visible_stats": {
                key: int(raw_stats.get(key) or 0) + CAREER_INVISIBLE_STAT_BONUS for key in raw_stats
            },
            "career_invisible_stat_bonus": CAREER_INVISIBLE_STAT_BONUS,
            "stamina_low": stamina_low,
            "stamina_ratio": ratios.get("stamina", 1),
            "min_stamina_ratio": float(min_ratio or 0.96),
            "stamina_recovery_skill_count": recovery_count,
            "unique_recovery_profile": unique_recovery,
            "warnings": warnings,
        }

    def style_from_chara(self, chara):
        for key in ("race_tactic", "running_style", "style"):
            try:
                style = TACTIC_TO_STYLE.get(int(chara.get(key) or 0))
                if style:
                    return style
            except (TypeError, ValueError):
                pass
        return ""
