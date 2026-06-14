import json
import re
import csv
import traceback
from pathlib import Path

from career_bot.skill_profiles import (
    COMMON_SKILLS,
    DISTANCE_SKILLS,
    STYLE_SKILLS,
    normalize_distance as normalize_profile_distance,
    normalize_style as normalize_profile_style,
)
from career_bot.unique_race_modifiers import race_unique_recovery_profile

try:
    from career_bot.manual_race_data import (
        aggregate_race_specific_targets,
        load_manual_race_data,
    )
except ImportError:
    aggregate_race_specific_targets = None
    load_manual_race_data = None

# Skill Markers
MARK_WHITE_CIRCLE = "○"  # U+25CB
MARK_DOUBLE_CIRCLE = "◎" # U+25CE
MARK_X = "×"             # U+00D7
MARK_LARGE_CIRCLE = "◯"  # U+25EF

UNICODE_WHITE_CIRCLE = "\u25cb"
UNICODE_DOUBLE_CIRCLE = "\u25ce"
UNICODE_X = "\u00d7"
UNICODE_LARGE_CIRCLE = "\u25ef"

# Mojibake variants found in logs/source
MOJI_WHITE_CIRCLE = "â—‹"
MOJI_LARGE_CIRCLE = "â—¯"
MOJI_DOUBLE_CIRCLE = "â—Ž"
MOJI_X = "Ã—"

SKILL_LEARN_PRIORITY_LIST = [
    [
        'Corner Acceleration ○', 'Corner Adept ○', 'Slipstream', 'Tail Held High',
        'Straightaway Spurt', 'Ramp Up', 'Inside Scoop', 'Passing Pro', 'Homestretch Haste',
        'Fast-Paced', 'Outer Swell', 'Sprinting Gear', 'Slick Surge', 'Corner Recovery ○',
        'Hydrate', 'After-School Stroll', 'Clean Heart', 'Dominator', 'All-Seeing Eyes', 'Mystifying Murmur'
    ],
    [
        'Acceleration', 'Focus', 'Go with the Flow', 'I Can See Right Through You',
        'Nimble Navigator', 'Straightaway Recovery', 'Deep Breaths', 'Preferred Position',
        'Groundwork', 'Up-Tempo', 'Unyielding Spirit', 'Pressure', 'Strategist', 'Triple 7s',
        'Shake It Out', 'Intimidate', 'Stamina Eater', 'Intense Gaze', 'Speed Star',
        'Staggering Lead', 'Blinding Flash', 'Restless', 'Trackblazer', 'Meticulous Measures',
        'Moxie', 'Keeping the Lead', 'Leader\'s Pride', 'Wait-and-See', 'A Small Breather'
    ],
    [
        'Levelheaded', 'Stop Right There!', 'Super Lucky Seven', 'Maverick ○', 'Sympathy',
        'Long Shot ○', 'Inner Post Proficiency ○', 'Outer Post Proficiency ○', 'Right-Handed ○',
        'Left-Handed ○', 'Firm Conditions ○', 'Wet Conditions ○', 'Standard Distance ○',
        'Non-Standard Distance ○', 'Competitive Spirit ○', 'Target in Sight ○', 'Lone Wolf'
    ]
]

STAMINA_RECOVERY_SKILLS = {
    "swingingmaestro", "cornerrecovery", "breathoffreshair", "straightawayrecovery",
    "cooldown", "deepbreaths", "relax", "asmallbreather", "hydrate", "secondwind",
    "staminatospare", "rosyoutlook", "triple7s", "calmandcollected", "ofcalmmind",
    "superiorheal", "unrestrained", "finalpush", "calminacrowd", "unruffled",
    "gourmand", "trackblazer", "moxie", "reignition", "freespirited",
}

STAMINA_RECOVERY_PRIORITY = {
    norm_name: index for index, norm_name in enumerate([
        "swingingmaestro", "cornerrecovery", "breathoffreshair", "straightawayrecovery",
        "cooldown", "deepbreaths", "relax", "asmallbreather", "hydrate", "secondwind",
        "staminatospare", "rosyoutlook", "triple7s", "calmandcollected", "ofcalmmind",
        "superiorheal", "unrestrained", "finalpush", "calminacrowd", "unruffled",
        "gourmand", "trackblazer", "moxie", "reignition", "freespirited",
    ])
}

STAMINA_RECOVERY_TAGS = {
    "swingingmaestro": {"generic"},
    "cornerrecovery": {"generic"},
    "breathoffreshair": {"generic"},
    "straightawayrecovery": {"generic"},
    "superiorheal": {"generic"},
    "triple7s": {"generic"},
    "secondwind": {"generic"},
    "reignition": {"generic"},
    "cooldown": {"long"},
    "deepbreaths": {"long"},
    "unrestrained": {"long"},
    "finalpush": {"long"},
    "trackblazer": {"front_runner"},
    "moxie": {"front_runner"},
    "rosyoutlook": {"front_runner"},
    "calmandcollected": {"front_runner"},
    "staminatospare": {"front_runner"},
    "gourmand": {"pace_chaser"},
    "hydrate": {"pace_chaser"},
    "relax": {"late_surger"},
    "asmallbreather": {"late_surger"},
    "ofcalmmind": {"end_closer"},
    "freespirited": {"end_closer"},
    "unruffled": {"end_closer"},
    "calminacrowd": {"end_closer"},
}

DEFAULT_KIKUKA_GENERIC_SAFETY_SKILLS = [
    "Corner Acceleration",
    "Straightaway Acceleration",
    "Corner Recovery",
    "Straightaway Recovery",
]

DEFAULT_FINAL_STAMINA_RECOVERY_MAX_COUNT = 2

STYLE_PROFILE_TO_ROLE = {
    "front_runner": "front",
    "pace_chaser": "pace",
    "late_surger": "late",
    "end_closer": "end",
}

STYLE_ROLE_TO_PROFILE = {value: key for key, value in STYLE_PROFILE_TO_ROLE.items()}

VALID_RATING_ROLES = {
    "turf", "dirt",
    "sprint", "mile", "medium", "long",
    "front", "pace", "late", "end",
}

RATING_ROLE_ALIASES = {
    "front runner": "front",
    "front_runner": "front",
    "nige": "front",
    "pace chaser": "pace",
    "pace_chaser": "pace",
    "senko": "pace",
    "late surger": "late",
    "late_surger": "late",
    "sashi": "late",
    "end closer": "end",
    "end_closer": "end",
    "oikomi": "end",
    "middle": "medium",
    "mid": "medium",
    "short": "sprint",
}

CHARA_APTITUDE_FIELDS = {
    "turf": "proper_ground_turf",
    "dirt": "proper_ground_dirt",
    "sprint": "proper_distance_short",
    "mile": "proper_distance_mile",
    "medium": "proper_distance_middle",
    "long": "proper_distance_long",
    "front": "proper_running_style_nige",
    "pace": "proper_running_style_senko",
    "late": "proper_running_style_sashi",
    "end": "proper_running_style_oikomi",
}

STYLE_TRIGGER_WORDS = {
    "front": {"front", "leader", "lead", "escape", "nige"},
    "pace": {"pace", "chaser", "senko"},
    "late": {"late", "surger", "sashi"},
    "end": {"end", "closer", "oikomi"},
}

DISTANCE_TRIGGER_WORDS = {
    "sprint": {"sprint", "short"},
    "mile": {"mile"},
    "medium": {"medium", "middle"},
    "long": {"long"},
}

SKILL_RATING_SOURCE_URL = "https://raw.githubusercontent.com/daftuyda/UmaTools/main/assets/uma_skills.csv"


def norm(text):
    return re.sub(r'[^a-z0-9]+', '', str(text or '').lower())


def strip_mark(text):
    if not text:
        return ""
    for m in [
        MARK_WHITE_CIRCLE, MARK_DOUBLE_CIRCLE, MARK_X, MARK_LARGE_CIRCLE,
        UNICODE_WHITE_CIRCLE, UNICODE_DOUBLE_CIRCLE, UNICODE_X, UNICODE_LARGE_CIRCLE,
        MOJI_WHITE_CIRCLE, MOJI_DOUBLE_CIRCLE, MOJI_X, MOJI_LARGE_CIRCLE,
    ]:
        text = text.replace(m, "")
    return text.strip()


def failed_group_key(group_id):
    return -abs(int(group_id or 0))


def extract_error_codes(text):
    codes = []
    seen = set()
    for token in str(text or "").replace(":", " ").replace(",", " ").split():
        if not token.isdigit():
            continue
        code = int(token)
        if code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


def exception_details(exc):
    details = {
        "type": type(exc).__name__,
        "message": str(exc),
        "error_codes": extract_error_codes(str(exc)),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }
    for attr in (
        "endpoint",
        "request_payload",
        "response_body",
        "response_text",
        "http_status",
        "result_code",
        "response_code",
        "req_id",
    ):
        value = getattr(exc, attr, None)
        if value is not None and value != "":
            details[attr] = value
    return details


class SkillBuyer:
    # After this many CONSECUTIVE careers have disabled a skill mid-run,
    # treat it as permanently broken for this preset/build and never try
    # again. The logs showed skills like 200581/201151/201161 etc. getting
    # rejected with 205/208 in every career — typically because the skill
    # has an unmet prerequisite or its group's owned form changed under it.
    # Trying them per-career wastes SP budget and produces 205 storms.
    CROSS_CAREER_DISABLE_THRESHOLD = 5

    def __init__(self, base_dir):
        self.base_dir = Path(base_dir)
        self.skill_names = {}
        self.skill_id_exists = set()
        self.group_to_skill_ids = {}
        self.skill_to_group_id = {}
        # Lineage spark cache. Built lazily from chara_info's
        # succession_trained_chara_id_1/2 + parent_library, then cached
        # per (succession_id_1, succession_id_2) so each end-of-career
        # skill-buy session reuses the same lookup.
        self._lineage_cache = {}
        self._parent_library_cache = None
        self.failed_this_turn = {}
        # Career-scoped permanent failures: skills the server has rejected
        # repeatedly with 205/208 across multiple turn-buy passes — almost
        # certainly desync between bot's tip list and server's actual buyable
        # set (skill already owned, tip-list rotated, etc.). Skip these in
        # candidate selection so the SP-drain retry doesn't keep hammering
        # the same dead skill while ignoring affordable alternatives.
        self.permanent_failed_skills = set()
        # Cross-career counter for skills that get disabled mid-career.
        # Persisted to disk so consecutive careers see the same accumulating
        # signal. Once a skill_id crosses CROSS_CAREER_DISABLE_THRESHOLD it
        # is filtered out at candidate selection forever (until the file is
        # deleted manually).
        self.cross_career_failed_skills = {}
        self._cross_career_failed_changed = False
        self.current_turn = None
        self.last_candidates = []
        self.last_selected = []
        self.last_attempt = []
        self.last_result = {}
        self.last_recovery_cap_skipped = []
        self.last_per_skill_rejections = []
        self.recover_after_error = False
        self.attempt_events = []
        self.known_bought_skill_ids = set()
        self.known_bought_group_ids = set()
        self.skill_rating_meta = {}
        self.skill_activation_data = {}
        self._load()
        self._load_skill_activation_data()
        self._load_cross_career_failures()

    def _load(self):
        path = self.base_dir / "data" / "master_map.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.skill_names = {int(k): v for k, v in data.get("skill", {}).items()}
        except Exception:
            return
        self.skill_id_exists = set(self.skill_names)
        self.group_to_skill_ids = {}
        self.skill_to_group_id = {}
        for skill_id in self.skill_names:
            group_id = skill_id if skill_id < 100000 else skill_id // 10
            self.skill_to_group_id[skill_id] = group_id
            self.group_to_skill_ids.setdefault(group_id, []).append(skill_id)
        
        for group_id, ids in self.group_to_skill_ids.items():
            children = [sid for sid in ids if sid >= 100000]
            if children:
                # Exclude the 5-digit parent group ID if 6-digit children exist
                self.group_to_skill_ids[group_id] = sorted(children)
            else:
                self.group_to_skill_ids[group_id] = sorted(ids)
        self._load_rating_metadata()

    def _load_skill_activation_data(self):
        self.skill_activation_data = {}
        path = self.base_dir / "data" / "skill_activation_data.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self.skill_activation_data = {}
            return
        for key, value in (data or {}).items():
            if not isinstance(value, dict):
                continue
            try:
                skill_id = int(value.get("skill_id") or key)
            except (TypeError, ValueError):
                continue
            if skill_id:
                self.skill_activation_data[skill_id] = value

    def _load_rating_metadata(self):
        """Load optional UmaTools rating metadata for end-career skill optimization.

        The bot does not require this file; without it the optimizer falls back
        to name/profile heuristics. If present, `uma_skills.csv` gives us the
        same score buckets and affinity roles used by UmaTools' rating mode.
        """
        self.skill_rating_meta = {}
        paths = [
            self.base_dir / "data" / "uma_skills.csv",
            self.base_dir.parent / "uma_runtime" / "skill_rating" / "uma_skills.csv",
        ]
        source = next((path for path in paths if path.exists()), None)
        if not source:
            return
        try:
            with source.open("r", encoding="utf-8-sig", newline="") as fh:
                reader = csv.DictReader(fh)
                for row in reader:
                    meta = self._parse_rating_meta_row(row)
                    if not meta:
                        continue
                    for key in meta["keys"]:
                        self.skill_rating_meta.setdefault(key, meta)
        except Exception:
            self.skill_rating_meta = {}

    def _parse_rating_meta_row(self, row):
        name = str((row or {}).get("name") or "").strip()
        if not name:
            return None
        aliases = []
        for field in ("name", "alias_name", "localized_name"):
            raw = str(row.get(field) or "")
            for part in raw.replace("|", "\n").splitlines():
                text = part.strip()
                if text:
                    aliases.append(text)
        keys = []
        for text in aliases:
            key = norm(text)
            if key and key not in keys:
                keys.append(key)
            stripped = norm(strip_mark(text))
            if stripped and stripped not in keys:
                keys.append(stripped)
        if not keys:
            return None

        def parse_score(field):
            raw = str(row.get(field) or "").strip()
            if not raw:
                return None
            try:
                return float(raw)
            except (TypeError, ValueError):
                return None

        roles = []
        for raw_role in str(row.get("affinity_role") or "").replace(",", "/").split("/"):
            role = self._normalize_rating_role(raw_role)
            if role and role not in roles:
                roles.append(role)
        return {
            "name": name,
            "category": str(row.get("skill_type") or "").strip().lower(),
            "roles": roles,
            "base": parse_score("base_value") or 0,
            "scores": {
                "good": parse_score("S_A"),
                "average": parse_score("B_C"),
                "bad": parse_score("D_E_F"),
                "terrible": parse_score("G"),
            },
        }

    def _cross_career_failures_path(self):
        # Returning None disables both load and save — used by tests to keep
        # them from writing into the user's real runtime data.
        if getattr(self, "_cross_career_failures_disabled", False):
            return None
        # Auto-detect test runners. Production code never imports unittest or
        # pytest, so their presence in sys.modules is a reliable signal that
        # we're inside a test process. Without this guard, `unittest discover`
        # (which doesn't load tests/__init__.py reliably) would let the suite
        # write into the user's real runtime file.
        import sys as _sys
        if "unittest" in _sys.modules or "pytest" in _sys.modules:
            return None
        return self.base_dir.parent / "uma_runtime" / "skill_failures.json"

    def disable_cross_career_failure_persistence(self):
        """Test hook — call before any buy() so persistence is skipped."""
        self._cross_career_failures_disabled = True
        self.cross_career_failed_skills = {}

    def _load_cross_career_failures(self):
        path = self._cross_career_failures_path()
        if not path or not path.exists():
            self.cross_career_failed_skills = {}
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self.cross_career_failed_skills = {}
            return
        raw = (data or {}).get("skills") or {}
        result = {}
        for key, value in raw.items():
            try:
                skill_id = int(key)
                count = int(value)
            except (TypeError, ValueError):
                continue
            if skill_id and count > 0:
                result[skill_id] = count
        self.cross_career_failed_skills = result

    def _save_cross_career_failures(self):
        if not self._cross_career_failed_changed:
            return
        path = self._cross_career_failures_path()
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "schema": "sweepy_skill_failures_v1",
                "threshold": self.CROSS_CAREER_DISABLE_THRESHOLD,
                "skills": {str(skill_id): count for skill_id, count in sorted(self.cross_career_failed_skills.items())},
            }
            path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            self._cross_career_failed_changed = False
        except Exception:
            pass

    def _record_cross_career_failure(self, skill_id):
        try:
            skill_id = int(skill_id)
        except (TypeError, ValueError):
            return
        if not skill_id:
            return
        current = int(self.cross_career_failed_skills.get(skill_id, 0))
        self.cross_career_failed_skills[skill_id] = current + 1
        self._cross_career_failed_changed = True
        if self.cross_career_failed_skills[skill_id] == self.CROSS_CAREER_DISABLE_THRESHOLD:
            name = self.skill_names.get(skill_id) or ""
            label = f"{skill_id} ({name})" if name else str(skill_id)
            print(
                f"Skill {label} crossed cross-career disable threshold "
                f"({self.CROSS_CAREER_DISABLE_THRESHOLD} careers); will be auto-skipped going forward"
            )
        self._save_cross_career_failures()

    def _is_cross_career_disabled(self, skill_id):
        try:
            sid = int(skill_id)
        except (TypeError, ValueError):
            return False
        return self.cross_career_failed_skills.get(sid, 0) >= self.CROSS_CAREER_DISABLE_THRESHOLD

    def _is_skill_blocked_for_purchase(self, skill_id, failed=None):
        """Return true for skill IDs the bot must not submit to gain_skills.

        This is intentionally skill-ID scoped, not group scoped. If the server
        rejects one variant in a group (for example a priority-selected sibling),
        the live/default sibling may still be buyable and should remain eligible.
        """
        try:
            sid = int(skill_id or 0)
        except (TypeError, ValueError):
            return True
        if sid <= 0:
            return True
        if failed is not None and sid in failed:
            return True
        if sid in self.permanent_failed_skills:
            return True
        if self._is_cross_career_disabled(sid):
            return True
        return False

    def _required_existing_skill_ids(self, skill_id):
        try:
            skill_id_int = int(skill_id or 0)
        except (TypeError, ValueError):
            return set()
        record = self.skill_activation_data.get(skill_id_int)
        if not isinstance(record, dict):
            return set()
        texts = [str(record.get("condition") or "")]
        for group in record.get("condition_groups") or []:
            if isinstance(group, dict):
                texts.append(str(group.get("condition") or ""))
        required = set()
        for text in texts:
            for match in re.finditer(r"is_exist_skill_id\s*==\s*(\d+)", text):
                try:
                    required.add(int(match.group(1)))
                except (TypeError, ValueError):
                    continue
        return required

    def _missing_purchase_prereqs(self, skill_id, owned_skill_ids):
        required = self._required_existing_skill_ids(skill_id)
        if not required:
            return set()
        owned = {int(sid or 0) for sid in owned_skill_ids or []}
        owned |= set(self.known_bought_skill_ids)
        return {sid for sid in required if sid not in owned}

    def reset_scoped_failures(self):
        # Intentionally preserves failed_this_turn and current_turn. _set_turn already
        # resets failed_this_turn when the turn actually changes; clearing here too
        # would wipe the "this skill just failed with 205" tracking between same-turn
        # retries (e.g. _finish_career's "SP still high, retry" path), causing the
        # runner to fire the same doomed batch again instead of skipping the bad skills.
        # NOTE: permanent_failed_skills is also preserved here — it's career-scoped,
        # not turn-scoped, and only reset by reset_career_scoped_failures() at start().
        self.last_candidates = []
        self.last_selected = []
        self.last_attempt = []
        self.last_result = {}
        self.last_recovery_cap_skipped = []
        self.last_per_skill_rejections = []

    def reset_career_scoped_failures(self):
        """Wipe career-wide state. Called at the start of every new career."""
        self.permanent_failed_skills = set()
        self.failed_this_turn = {}
        self.current_turn = None
        self.attempt_events = []
        self.recover_after_error = False
        self.known_bought_skill_ids = set()
        self.known_bought_group_ids = set()
        self.last_per_skill_rejections = []

    def _set_turn(self, turn):
        turn = int(turn or 0)
        if self.current_turn != turn:
            self.current_turn = turn
            self.failed_this_turn = {turn: set()}
        self.failed_this_turn.setdefault(turn, set())

    def _failed_for_turn(self, turn=None):
        turn = int(turn if turn is not None else self.current_turn or 0)
        return self.failed_this_turn.setdefault(turn, set())

    def buy(self, client, state, preset, force=False):
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        self.recover_after_error = False
        self.attempt_events = []
        self.last_per_skill_rejections = []
        if not chara:
            return state, 0
        state = self.enrich_state_with_known_bought(state)
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}

        points = int(chara.get("skill_point") or 0)
        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)

        # SP-economy guard: aggressive mid-career buying drains the
        # end-of-career skill pool that produces white factors. Restored
        # to conservative defaults — only fire mid-career when SP is
        # very high (1500+) so the end-of-career drain has material to
        # work with. Pre-race calendar buys are handled by the dedicated
        # `buy_limited_for_race` path which respects its own budget.
        is_hoarding = points > 1500
        threshold = int(preset.get("learn_skill_threshold") or 444)
        if not force and not is_hoarding and points <= threshold:
            self.last_candidates = []
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "threshold", "points": points, "threshold": threshold}
            return state, 0

        if preset.get("manual_purchase_at_end") and not force:
            self.last_candidates = []
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "manual_purchase_at_end"}
            return state, 0

        candidates = self._candidates_with_fallback(chara, preset, force=force)
        candidates = self._apply_general_recovery_cap(candidates, chara, preset, force=force)
        if not candidates:
            candidates = self._fallback_after_recovery_cap(chara, preset)

        self.last_candidates = [dict(item) for item in candidates]
        if not candidates:
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {
                "skip": "no_candidates",
                "points": points,
                "recovery_cap_skipped": [dict(item) for item in self.last_recovery_cap_skipped],
            }
            return state, 0

        if force and bool(preset.get("skill_optimizer_enabled", True)):
            selected = self._select_final_candidates(candidates, points, chara, preset)
        else:
            selected = []
            spent = 0
            for candidate in candidates:
                candidate, cost = self._candidate_for_budget(candidate, points - spent, force=force)
                if not candidate:
                    continue
                if spent + cost > points:
                    continue
                selected.append(candidate)
                spent += cost

        if not selected:
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "not_enough_points", "points": points}
            return state, 0

        self.last_selected = [dict(item) for item in selected]

        current_state, total_bought = self._buy_batch(client, state, selected, turn, preset)

        return current_state, total_bought

    def _estimate_pre_race_win_probability(self, chara, race_check, owned_skill_count):
        """Estimate win probability for an upcoming calendar race.

        Ported from `CareerSimulator._manual_threshold_probability_estimate`.
        Uses the user's `manual_race_data.json` median winning stats as
        the race-field threshold, then computes a weighted ratio coverage
        across primary/secondary/tertiary stats. Returns a probability
        in [0.06, 0.96]. None when no usable threshold exists.

        Used by `buy_limited_for_race` to skip pre-race buys when the
        bot already has the stats to win — saving SP for the end-of-
        career drain (which produces white-factor sparks worth far more
        rating than borderline pre-race skills).
        """
        if not load_manual_race_data or not aggregate_race_specific_targets:
            return None
        if not isinstance(race_check, dict):
            return None
        try:
            pid = int(race_check.get("program_id") or 0)
        except (TypeError, ValueError):
            pid = 0
        if not pid:
            return None

        runtime_root = None
        try:
            runtime_root = Path(self.base_dir).parent / "uma_runtime"
        except Exception:
            return None
        try:
            mrd = load_manual_race_data(runtime_root)
        except Exception:
            return None
        if not mrd:
            return None

        # Card-id-aware threshold lookup. Falls back to cross-trainee
        # median when bot's trainee has no exact data for this race.
        card_id = None
        try:
            card_id = int(chara.get("card_id") or 0)
        except (TypeError, ValueError):
            pass
        try:
            threshold = aggregate_race_specific_targets(
                mrd,
                pid,
                current_trainee_card_id=card_id,
            ) or {}
        except Exception:
            return None
        if not threshold:
            return None

        distance = str(race_check.get("distance") or "").lower()
        primary_stat = "stamina" if distance == "long" else "speed"
        secondary_stat = "power" if distance != "long" else "speed"
        tertiary_stat = "wit"

        def _stat(name):
            keys = {
                "speed": "speed",
                "stamina": "stamina",
                "power": "power",
                "guts": "guts",
                "wit": "wiz",
            }
            return float(chara.get(keys.get(name, name)) or 0)

        cur_p = _stat(primary_stat)
        cur_s = _stat(secondary_stat)
        cur_t = _stat(tertiary_stat)

        thr_p = max(1.0, float(threshold.get(primary_stat) or 1))
        thr_s = max(1.0, float(threshold.get(secondary_stat) or 1))
        thr_t = max(1.0, float(threshold.get(tertiary_stat) or 1))

        ratio_p = cur_p / thr_p
        ratio_s = cur_s / thr_s
        ratio_t = cur_t / thr_t

        # Already-owned skill gives small probability boost (12 bps per skill, max 22%)
        skill_bonus = min(0.22, max(0, int(owned_skill_count or 0)) * 0.012)

        # Coverage formula from sim: weighted ratio across 3 stats
        coverage = (ratio_p * 0.45) + (ratio_s * 0.35) + (ratio_t * 0.20)
        prob = max(0.06, min(0.96, 0.10 + (coverage - 0.78) * 1.25 + skill_bonus))
        return prob

    def buy_limited_for_race(self, client, state, preset, race_check=None, max_skills=None, budget=None, reserve=None, min_sp=None):
        """Buy a small number of race-relevant skills before a mandatory calendar race.

        `manual_purchase_at_end` is intentionally ignored here. Calendar races are
        mandatory, so this path spends a capped amount of SP to avoid entering G1s
        with 700+ unspent SP while still preserving most end-buy budget.
        """
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        self.recover_after_error = False
        self.attempt_events = []
        self.last_per_skill_rejections = []
        if not chara:
            return state, 0
        state = self.enrich_state_with_known_bought(state)
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}

        def _as_int(value, default=0):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        points = _as_int(chara.get("skill_point"), 0)
        turn = _as_int(chara.get("turn"), 0)
        self._set_turn(turn)
        min_sp = _as_int(
            min_sp if min_sp is not None else (preset or {}).get("calendar_race_prebuy_min_sp"),
            450,
        )
        if points < min_sp:
            self.last_candidates = []
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "pre_race_skill_min_sp", "points": points, "min_sp": min_sp}
            return state, 0

        # ── Win-probability gate (ported from CareerSimulator's clean_record_mode).
        # If the bot's current stats already give it a high win probability
        # vs this race's field, skip the pre-race buy and save SP for
        # end-of-career drain. The drain produces white-factor sparks
        # worth ~85-300 rating per skill, while borderline pre-race buys
        # mostly add ~50-150 rating each. Conserving SP for end-of-career
        # is the documented bottleneck blocking the bot's S-rank ceiling.
        gate_enabled = bool((preset or {}).get("pre_race_winprob_gate_enabled", True))
        target_prob = float((preset or {}).get("pre_race_target_win_probability", 0.93))
        gate_min_save_sp = _as_int((preset or {}).get("pre_race_winprob_gate_min_save_sp"), 1200)
        if gate_enabled:
            # Compute current owned-skill count (used by probability model)
            data_now = state.get("data") or {}
            owned_skills = (data_now.get("chara_info") or {}).get("skill_array") or []
            try:
                owned_count = len(owned_skills)
            except TypeError:
                owned_count = 0
            prob = self._estimate_pre_race_win_probability(chara, race_check, owned_count)
            if prob is not None and prob >= target_prob and points <= gate_min_save_sp:
                self.last_candidates = []
                self.last_selected = []
                self.last_attempt = []
                self.last_result = {
                    "skip": "pre_race_skip_high_win_prob",
                    "points": points,
                    "win_probability": round(prob, 4),
                    "target_prob": target_prob,
                    "race": (race_check or {}).get("race_name") or (race_check or {}).get("program_id"),
                }
                return state, 0

        reserve = _as_int(reserve if reserve is not None else (preset or {}).get("calendar_race_prebuy_keep_sp"), 350)
        spendable = max(0, points - reserve)
        if spendable <= 0:
            self.last_candidates = []
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "pre_race_skill_reserve", "points": points, "reserve": reserve}
            return state, 0
        budget = _as_int(budget if budget is not None else (preset or {}).get("calendar_race_prebuy_budget"), 520)
        budget = max(0, min(spendable, budget))
        if budget <= 0:
            self.last_candidates = []
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {"skip": "pre_race_skill_budget", "points": points, "reserve": reserve}
            return state, 0
        max_skills = max(1, _as_int(max_skills if max_skills is not None else (preset or {}).get("calendar_race_prebuy_max_skills"), 2))

        race_preset = dict(preset or {})
        race_preset["manual_purchase_at_end"] = False
        race_preset["learn_skill_only_user_provided"] = False
        race_preset["learn_skill_append_defaults"] = True
        race_check = race_check or {}
        race_style = normalize_profile_style(race_check.get("style") or "")
        race_distance = normalize_profile_distance(race_check.get("distance") or "")
        if race_style:
            race_preset["skill_profile_style"] = race_style
        if race_distance:
            race_preset["skill_profile_distance"] = race_distance

        candidates = self._candidates_with_fallback(chara, race_preset, force=False)
        candidates = self._apply_general_recovery_cap(candidates, chara, race_preset, force=False)
        self.last_candidates = [dict(item) for item in candidates]
        if not candidates:
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {
                "skip": "no_pre_race_skill_candidates",
                "points": points,
                "budget": budget,
                "race": race_check.get("race_name"),
            }
            return state, 0

        selected = []
        seen_groups = set()
        spent = 0
        priority = self._priority_context(race_preset)
        scored = []
        for candidate in candidates:
            group_id = self._candidate_group_id(candidate)
            if not group_id or group_id in seen_groups:
                continue
            row, cost = self._candidate_for_budget(candidate, budget - spent, force=False)
            if not row or cost <= 0:
                continue
            item = dict(row)
            item["cost"] = cost
            item["pre_race_score"] = self._optimizer_skill_score(item, chara, race_preset, priority)
            scored.append(item)
        scored.sort(key=lambda item: (
            -float(item.get("pre_race_score") or 0.0),
            int(item.get("priority", 999)),
            int(item.get("cost") or 0),
            -int(item.get("hint_level") or 0),
            int(item.get("skill_id") or 0),
        ))
        for item in scored:
            group_id = self._candidate_group_id(item)
            cost = int(item.get("cost") or self._estimate_cost(item))
            if not group_id or group_id in seen_groups:
                continue
            if spent + cost > budget:
                continue
            selected.append(item)
            seen_groups.add(group_id)
            spent += cost
            if len(selected) >= max_skills:
                break

        self.last_selected = [dict(item) for item in selected]
        if not selected:
            self.last_attempt = []
            self.last_result = {
                "skip": "no_affordable_pre_race_skill",
                "points": points,
                "budget": budget,
                "reserve": reserve,
                "race": race_check.get("race_name"),
            }
            return state, 0

        current_state, bought = self._buy_batch(client, state, selected, turn, race_preset)
        if bought:
            self.last_result.setdefault("reason", "pre_race_calendar_skill_budget")
            self.last_result.setdefault("budget", budget)
            self.last_result.setdefault("reserve", reserve)
            self.last_result.setdefault("race", race_check.get("race_name"))
        return current_state, bought

    def buy_stamina_for_race(self, client, state, preset, stamina_check):
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        self.recover_after_error = False
        self.attempt_events = []
        self.last_per_skill_rejections = []
        if not chara or not stamina_check:
            return state, 0
        if not bool(preset.get("auto_buy_stamina_skill_for_race", True)):
            self.last_result = {"skip": "race_stamina_skill_disabled"}
            return state, 0
        if not self._stamina_skill_needed(chara, preset, stamina_check):
            return state, 0

        points = int(chara.get("skill_point") or 0)
        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)
        if points <= 0:
            self.last_result = {"skip": "no_skill_points_for_stamina_skill", "points": points}
            return state, 0

        candidate_preset = self._stamina_recovery_candidate_preset(preset)
        candidates = self._candidates(chara, candidate_preset)
        stamina_candidates = [item for item in candidates if self._is_stamina_recovery_skill(item.get("skill_id"), item.get("name"))]
        affordable = []
        for item in stamina_candidates:
            cost = int(item.get("cost") or self._estimate_cost(item))
            if cost <= points:
                item = dict(item)
                item["cost"] = cost
                affordable.append(item)
        if not affordable:
            self.last_candidates = [dict(item) for item in stamina_candidates]
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {
                "skip": "no_affordable_stamina_skill",
                "points": points,
                "race": stamina_check.get("race_name"),
                "required_stamina": (stamina_check.get("requirements") or {}).get("stamina"),
                "current_stamina": (stamina_check.get("stats") or {}).get("stamina"),
            }
            return state, 0
        usable = [item for item in affordable if self._stamina_skill_match_score(item, stamina_check) < 99]
        if not usable:
            self.last_candidates = [dict(item) for item in stamina_candidates]
            self.last_selected = []
            self.last_attempt = []
            self.last_result = {
                "skip": "no_usable_stamina_skill_for_race",
                "race": stamina_check.get("race_name"),
                "distance": stamina_check.get("distance"),
                "style": stamina_check.get("style"),
            }
            return state, 0

        usable.sort(key=lambda item: (
            self._stamina_skill_match_score(item, stamina_check),
            STAMINA_RECOVERY_PRIORITY.get(norm(strip_mark(item.get("name"))), 999),
            item["cost"],
            -int(item.get("hint_level") or 0),
            int(item.get("skill_id") or 0),
        ))
        selected = usable[:1]
        self.last_candidates = [dict(item) for item in stamina_candidates]
        self.last_selected = [dict(item) for item in selected]
        current_state, bought = self._buy_batch(client, state, selected, turn, candidate_preset)
        if bought:
            self.last_result.setdefault("reason", "pre_race_stamina_skill")
        return current_state, bought

    def _stamina_recovery_candidate_preset(self, preset):
        """Build a temporary preset that only prioritizes recovery skills.

        Pre-race stamina rescue is a safety rail, not the normal parent-spark
        skill plan. The saved plan may intentionally target only style/distance
        whites, but a low-stamina Long/Medium G1 still needs to be allowed to
        buy any usable recovery tip the server offers.
        """
        recovery_names = []
        seen = set()
        for skill_id, name in sorted(self.skill_names.items()):
            if not self._is_stamina_recovery_skill(skill_id, name):
                continue
            for value in (name, strip_mark(name)):
                key = norm(value)
                if key and key not in seen:
                    recovery_names.append(value)
                    seen.add(key)
        for key in sorted(STAMINA_RECOVERY_SKILLS):
            if key and key not in seen:
                recovery_names.append(key)
                seen.add(key)
        return {
            **(preset or {}),
            "learn_skill_list": [recovery_names],
            "learn_skill_only_user_provided": False,
            "learn_skill_append_defaults": False,
        }

    def buy_profile_safety_for_race(self, client, state, preset, stamina_check):
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        self.recover_after_error = False
        self.attempt_events = []
        self.last_per_skill_rejections = []
        if not chara or not stamina_check:
            return state, 0

        try:
            required_count = int((preset or {}).get("kikuka_front_runner_min_usable_skills") or 0)
        except (TypeError, ValueError):
            required_count = 0
        if required_count <= 0:
            self.last_result = {"skip": "race_profile_safety_disabled"}
            return state, 0

        safety_names = self._race_profile_safety_names(preset, stamina_check)
        safety_keys = {norm(name) for name in safety_names}
        owned_count = self._race_profile_safety_skill_count(chara, preset, stamina_check)
        needed = max(0, required_count - owned_count)
        if needed <= 0:
            self.last_result = {
                "skip": "race_profile_safety_met",
                "owned_usable_skill_count": owned_count,
                "required_usable_skill_count": required_count,
            }
            return state, 0

        points = int(chara.get("skill_point") or 0)
        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)
        if points <= 0:
            self.last_result = {"skip": "no_skill_points_for_profile_safety", "points": points}
            return state, 0

        safety_preset = dict(preset or {})
        safety_preset["learn_skill_list"] = [safety_names]
        safety_preset["learn_skill_only_user_provided"] = False
        safety_preset["learn_skill_append_defaults"] = False
        candidates = [
            item for item in self._candidates(chara, safety_preset)
            if norm(strip_mark(item.get("name"))) in safety_keys
        ]
        candidates.sort(key=lambda item: (
            int(item.get("priority", 999)),
            int(item.get("cost") or self._estimate_cost(item)),
            -int(item.get("hint_level") or 0),
            int(item.get("skill_id") or 0),
        ))

        selected = []
        spent = 0
        for item in candidates:
            cost = int(item.get("cost") or self._estimate_cost(item))
            if spent + cost > points:
                continue
            item = dict(item)
            item["cost"] = cost
            selected.append(item)
            spent += cost
            if len(selected) >= needed:
                break

        self.last_candidates = [dict(item) for item in candidates]
        self.last_selected = [dict(item) for item in selected]
        if not selected:
            self.last_attempt = []
            self.last_result = {
                "skip": "no_affordable_profile_safety_skill",
                "points": points,
                "owned_usable_skill_count": owned_count,
                "required_usable_skill_count": required_count,
            }
            return state, 0

        current_state, bought = self._buy_batch(client, state, selected, turn, safety_preset)
        if bought:
            self.last_result.setdefault("reason", "pre_race_profile_safety_skill")
        return current_state, bought

    def preview(self, state, preset, force=False):
        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        if not chara:
            self.last_candidates = []
            self.last_selected = []
            return
        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)
        points = int(chara.get("skill_point") or 0)
        threshold = int(preset.get("learn_skill_threshold") or 444)
        if not force and points <= threshold:
            self.last_candidates = []
            self.last_selected = []
            return
        if preset.get("manual_purchase_at_end") and not force:
            self.last_candidates = []
            self.last_selected = []
            return
        candidates = self._candidates_with_fallback(chara, preset, force=force)
        candidates = self._apply_general_recovery_cap(candidates, chara, preset, force=force)
        if not candidates:
            candidates = self._fallback_after_recovery_cap(chara, preset)
        if force and bool(preset.get("skill_optimizer_enabled", True)):
            selected = self._select_final_candidates(candidates, points, chara, preset)
        else:
            selected = []
            spent = 0
            for candidate in candidates:
                candidate, cost = self._candidate_for_budget(candidate, points - spent, force=force)
                if not candidate:
                    continue
                if spent + cost > points:
                    continue
                selected.append(candidate)
                spent += cost
        self.last_candidates = [dict(item) for item in candidates]
        self.last_selected = [dict(item) for item in selected]

    def _normal_skill_preset(self, preset):
        fallback = dict(preset or {})
        fallback["learn_skill_list"] = []
        fallback["learn_skill_only_user_provided"] = False
        fallback["learn_skill_append_defaults"] = False
        return fallback

    def _has_explicit_skill_profile(self, preset):
        return any(row for row in ((preset or {}).get("learn_skill_list") or []))

    def _candidate_group_id(self, candidate):
        skill_id = int((candidate or {}).get("skill_id") or 0)
        return self._skill_group_id(skill_id)

    def _skill_group_id(self, skill_id):
        try:
            skill_id = int(skill_id or 0)
        except (TypeError, ValueError):
            skill_id = 0
        return self.skill_to_group_id.get(skill_id, skill_id // 10)

    def _remember_bought(self, rows):
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            try:
                skill_id = int(row.get("skill_id") or 0)
            except (TypeError, ValueError):
                skill_id = 0
            try:
                group_id = int(row.get("group_id") or 0)
            except (TypeError, ValueError):
                group_id = 0
            if skill_id:
                self.known_bought_skill_ids.add(skill_id)
                self.known_bought_group_ids.add(self._skill_group_id(skill_id))
            elif group_id:
                self.known_bought_group_ids.add(group_id)

    def _owned_skill_ids(self, chara):
        owned = set(self.known_bought_skill_ids)
        for item in (chara or {}).get("skill_array") or []:
            try:
                skill_id = int(item.get("skill_id") or 0)
            except (TypeError, ValueError, AttributeError):
                skill_id = 0
            if skill_id:
                owned.add(skill_id)
        return owned

    def enrich_state_with_known_bought(self, state):
        """Merge server-accepted buys into snapshots that omit final skill_array rows."""
        if not isinstance(state, dict) or not self.known_bought_skill_ids:
            return state
        data = state.get("data") or {}
        if not isinstance(data, dict):
            return state
        for key in ("chara_info", "single_mode_chara_light"):
            chara = data.get(key)
            if not isinstance(chara, dict):
                continue
            skill_array = chara.get("skill_array")
            if not isinstance(skill_array, list):
                skill_array = list(skill_array or [])
                chara["skill_array"] = skill_array
            existing = set()
            for item in skill_array:
                try:
                    skill_id = int((item or {}).get("skill_id") or 0)
                except (TypeError, ValueError, AttributeError):
                    skill_id = 0
                if skill_id:
                    existing.add(skill_id)
            for skill_id in sorted(self.known_bought_skill_ids):
                if skill_id not in existing:
                    skill_array.append({"skill_id": skill_id, "level": 1})
                    existing.add(skill_id)
        return state

    def _owned_groups(self, chara):
        groups = set(self.known_bought_group_ids)
        for skill_id in self._owned_skill_ids(chara):
            groups.add(self._skill_group_id(skill_id))
        return groups

    def _merge_skill_candidates(self, primary, fallback):
        merged = []
        seen_skill_ids = set()
        seen_groups = set()
        for item in list(primary or []) + list(fallback or []):
            skill_id = int(item.get("skill_id") or 0)
            group_id = self._candidate_group_id(item)
            if not skill_id or skill_id in seen_skill_ids or group_id in seen_groups:
                continue
            merged.append(item)
            seen_skill_ids.add(skill_id)
            seen_groups.add(group_id)
        return merged

    def _candidate_for_budget(self, candidate, remaining_points, force=False):
        if self._is_skill_blocked_for_purchase((candidate or {}).get("skill_id"), self._failed_for_turn()):
            return None, int((candidate or {}).get("cost") or 0)
        cost = int(candidate.get("cost") or self._estimate_cost(candidate))
        if cost <= remaining_points:
            return candidate, cost
        return None, cost

    def _select_hard_priority_candidates(self, candidates, budget, chara, preset, priority):
        hard_keys = self._final_priority_keys(preset)
        desired_white_keys = self._desired_white_skill_keys(preset)
        selected = []
        spent = 0
        seen_groups = set()
        # Pass 1: user-named hard-priority skills (skill plan first row
        # + skill_buy_on_sight). Existing behavior.
        if hard_keys:
            for candidate in candidates or []:
                group_id = self._candidate_group_id(candidate)
                if not group_id or group_id in seen_groups:
                    continue
                if not self._candidate_matches_keys(candidate, hard_keys):
                    continue
                remaining = budget - spent
                if remaining <= 0:
                    break
                row, cost = self._candidate_for_budget(candidate, remaining, force=True)
                if not row or cost > remaining:
                    continue
                if not self._candidate_matches_keys(row, hard_keys):
                    continue
                row = dict(row)
                row["cost"] = cost
                row["hard_priority"] = True
                row["hard_priority_reason"] = "skill_plan_priority"
                row["optimizer_score"] = self._optimizer_skill_score(row, chara, preset, priority)
                selected.append(row)
                spent += cost
                seen_groups.add(group_id)
        # Pass 2: desired-white-spark force-buy. If the user listed a
        # specific white spark name in `desired_parent_sparks.white` on
        # the dashboard, the bot prioritizes buying that exact skill so
        # the resulting parent has the highest chance of generating
        # that white spark. Higher rank than gold-match pass — the user
        # explicitly named these as their target sparks.
        if desired_white_keys:
            for candidate in candidates or []:
                group_id = self._candidate_group_id(candidate)
                if not group_id or group_id in seen_groups:
                    continue
                if not self._candidate_matches_keys(candidate, desired_white_keys):
                    continue
                remaining = budget - spent
                if remaining <= 0:
                    break
                row, cost = self._candidate_for_budget(candidate, remaining, force=True)
                if not row or cost > remaining:
                    continue
                if not self._candidate_matches_keys(row, desired_white_keys):
                    continue
                row = dict(row)
                row["cost"] = cost
                row["hard_priority"] = True
                row["hard_priority_reason"] = "desired_white_spark"
                row["optimizer_score"] = self._optimizer_skill_score(row, chara, preset, priority)
                selected.append(row)
                spent += cost
                seen_groups.add(group_id)
        # Pass 3: gold-tier candidates (tip_rarity > 0) that match the
        # user's style/distance from the skill-plan setup area. User
        # explicitly opted in: gold skills are the highest-spark-rate
        # purchases per SP (40% generation rate vs 20% for plain whites
        # — see WHITE_GENERATION_BASE_RATES in spark_rates.py), so as
        # long as they fit the run's style/distance they should be
        # bought regardless of optimizer score.
        for candidate in candidates or []:
            group_id = self._candidate_group_id(candidate)
            if not group_id or group_id in seen_groups:
                continue
            if not self._is_gold_match_for_profile(candidate, preset):
                continue
            remaining = budget - spent
            if remaining <= 0:
                break
            row, cost = self._candidate_for_budget(candidate, remaining, force=True)
            if not row or cost > remaining:
                continue
            row = dict(row)
            row["cost"] = cost
            row["hard_priority"] = True
            row["hard_priority_reason"] = "gold_profile_match"
            row["optimizer_score"] = self._optimizer_skill_score(row, chara, preset, priority)
            selected.append(row)
            spent += cost
            seen_groups.add(group_id)
        return selected

    def _desired_white_skill_keys(self, preset):
        """Pull `desired_parent_sparks.white` from the preset and
        normalize into a key set the existing `_candidate_matches_keys`
        helper can use. Returns the empty set when no white sparks were
        declared — caller should skip the pass in that case."""
        if not isinstance(preset, dict):
            return set()
        raw = (preset.get("desired_parent_sparks") or {}).get("white")
        if not raw:
            return set()
        items = raw if isinstance(raw, (list, tuple)) else str(raw or "").replace(",", "\n").splitlines()
        keys = set()
        for item in items:
            text = str(item or "").strip()
            if not text:
                continue
            key = norm(text)
            if key:
                keys.add(key)
            if text.isdigit():
                keys.add(text)
        return keys

    def _cached_parent_library(self):
        """Lazy-load parent_library.json once per SkillBuyer instance.
        Returns an empty dict if the file is missing or unreadable —
        lineage scoring then becomes a no-op."""
        if self._parent_library_cache is None:
            try:
                from career_bot.parent_memory import load_parent_library
                self._parent_library_cache = load_parent_library(self.base_dir) or {}
            except Exception:
                self._parent_library_cache = {}
        return self._parent_library_cache

    def _lineage_factors(self, chara):
        """Return a list of (id_str|None, name_norm|None) tuples for
        every skill-category factor across the trainee's lineage.

        Lineage = the two `succession_trained_chara_id_*` from
        chara_info, each looked up in parent_library, walking each
        legacy's `tree.self`, `tree.p1`, `tree.p2` factor arrays for
        category == "skill" entries. Up to 6 lineage sources per
        career; each appearance is one entry in the returned list
        (NOT double-counted across id and name dimensions — that's
        the matcher's job).

        Cached per (succession_id_1, succession_id_2) tuple so a
        single end-of-career skill-buy session reuses the lookup."""
        if not isinstance(chara, dict):
            return []
        succession_ids = []
        for key in ("succession_trained_chara_id_1", "succession_trained_chara_id_2"):
            try:
                val = int(chara.get(key) or 0)
            except (TypeError, ValueError):
                val = 0
            if val > 0:
                succession_ids.append(val)
        if not succession_ids:
            return []
        cache_key = tuple(sorted(succession_ids))
        cached = self._lineage_cache.get(cache_key)
        if cached is not None:
            return cached
        library = self._cached_parent_library()
        parents = library.get("parents") if isinstance(library, dict) else None
        if not parents:
            self._lineage_cache[cache_key] = []
            return []
        parents_by_id = {}
        for parent in parents:
            if not isinstance(parent, dict):
                continue
            for key in ("trained_chara_id", "instance_id"):
                try:
                    pid = int(parent.get(key) or 0)
                except (TypeError, ValueError):
                    pid = 0
                if pid > 0 and pid not in parents_by_id:
                    parents_by_id[pid] = parent
        factors = []
        for sid in succession_ids:
            parent = parents_by_id.get(sid)
            if not parent:
                continue
            tree = parent.get("tree") or {}
            for slot in ("self", "p1", "p2"):
                node = tree.get(slot) or {}
                for factor in node.get("factors") or []:
                    if not isinstance(factor, dict):
                        continue
                    if factor.get("category") != "skill":
                        continue
                    fid = factor.get("id")
                    fid_str = str(fid) if fid is not None else None
                    fname = norm(strip_mark(factor.get("name") or "")) or None
                    factors.append((fid_str, fname))
        self._lineage_cache[cache_key] = factors
        return factors

    def _lineage_multiplier(self, candidate, chara):
        """Return a score multiplier in [1.0, 1.5] based on how many
        lineage factors match this candidate. Each match contributes
        one factor of 1.1 (matching the
        `WHITE_GENERATION_LINEAGE_MULTIPLIER` from spark_rates);
        capped at 1.5 so a deep lineage doesn't make a single skill
        purchase overwhelm everything else.

        Match check (any one of these wins per factor): skill_id ==
        factor.id, group_id == factor.id, OR normalized name match.
        Each factor counted at most ONCE — id-match and name-match on
        the same factor don't double-count."""
        if not candidate:
            return 1.0
        factors = self._lineage_factors(chara)
        if not factors:
            return 1.0
        try:
            sid_int = int(candidate.get("skill_id") or 0)
        except (TypeError, ValueError):
            sid_int = 0
        sid_str = str(sid_int) if sid_int else None
        gid = self._candidate_group_id(candidate)
        gid_str = str(gid) if gid and gid != sid_int else None
        name_norm = norm(strip_mark(candidate.get("name") or "")) or None
        matches = 0
        for fid, fname in factors:
            if sid_str and fid == sid_str:
                matches += 1
                continue
            if gid_str and fid == gid_str:
                matches += 1
                continue
            if name_norm and fname == name_norm:
                matches += 1
        if matches <= 0:
            return 1.0
        return min(1.5, 1.1 ** matches)

    def _is_gold_match_for_profile(self, candidate, preset):
        """Return True if `candidate` is a gold-tier tip (tip_rarity > 0)
        AND it matches the run's style or distance from the skill-plan
        setup area. Used by `_select_hard_priority_candidates` to
        force-buy these candidates within budget. Profile match comes
        in two flavors:
          1) Exact name match against STYLE_SKILLS / DISTANCE_SKILLS
             — the curated lists per style/distance.
          2) Trigger-word match (the skill name contains a role word
             that lines up with the plan's style/distance roles).
        """
        if not candidate:
            return False
        try:
            if int(candidate.get("tip_rarity") or 0) <= 0:
                return False
        except (TypeError, ValueError):
            return False
        name = strip_mark(candidate.get("name") or "")
        key = norm(name)
        if not key:
            return False
        style = normalize_profile_style((preset or {}).get("skill_profile_style") or "")
        distance = normalize_profile_distance((preset or {}).get("skill_profile_distance") or "")
        style_names = {norm(item) for item in STYLE_SKILLS.get(style, [])} if style else set()
        distance_names = {norm(item) for item in DISTANCE_SKILLS.get(distance, [])} if distance else set()
        if key in style_names or key in distance_names:
            return True
        roles = self._name_trigger_roles(name)
        target_roles = self._skill_plan_target_roles(preset)
        if roles and target_roles and (roles & target_roles):
            return True
        return False

    def _select_final_candidates(self, candidates, points, chara, preset):
        """End-career optimizer: choose the best skill set within SP budget.

        This follows the same shape as UmaTools' optimizer: candidates are
        grouped by skill group, each group offers mutually-exclusive variants
        plus skip, and a rolling DP knapsack maximizes rating/profile value.
        """
        try:
            budget = max(0, int(points or 0))
        except (TypeError, ValueError):
            budget = 0
        if budget <= 0:
            return []

        priority = self._priority_context(preset or {})
        hard_selected = self._select_hard_priority_candidates(candidates, budget, chara, preset, priority)
        hard_groups = {self._candidate_group_id(item) for item in hard_selected}
        hard_spent = sum(max(0, int(item.get("cost") or self._estimate_cost(item))) for item in hard_selected)
        remaining_budget = max(0, budget - hard_spent)
        groups = []
        seen_groups = set()
        for candidate in candidates or []:
            group_id = self._candidate_group_id(candidate)
            if not group_id or group_id in seen_groups:
                continue
            if group_id in hard_groups:
                continue
            seen_groups.add(group_id)
            options = [{"none": True, "cost": 0, "score": 0, "candidate": None}]
            seen_skill_ids = set()
            for variant in self._final_candidate_variants(candidate, remaining_budget):
                skill_id = int(variant.get("skill_id") or 0)
                if not skill_id or skill_id in seen_skill_ids:
                    continue
                seen_skill_ids.add(skill_id)
                cost = int(variant.get("cost") or self._estimate_cost(variant))
                if cost > remaining_budget:
                    continue
                scored = dict(variant)
                scored["cost"] = cost
                scored["optimizer_score"] = self._optimizer_skill_score(scored, chara, preset, priority)
                options.append({
                    "none": False,
                    "cost": cost,
                    "score": max(0, int(scored["optimizer_score"])),
                    "candidate": scored,
                })
            if len(options) > 1:
                groups.append(options)

        selected = self._run_group_knapsack(groups, remaining_budget)
        selected.sort(key=lambda item: (
            -int(item.get("optimizer_score") or 0),
            int(item.get("priority", 999)),
            -int(item.get("cost") or 0),
            int(item.get("skill_id") or 0),
        ))
        # End-of-career drain sweep. The knapsack maximizes optimizer_score
        # and will pick "none" for any group whose variants don't justify
        # their SP cost — correct mid-career, wrong at end-of-career where
        # unspent SP is wasted. After the knapsack settles, greedily buy
        # the cheapest affordable variant of every group that has none
        # selected, until budget is exhausted.
        spent_so_far = hard_spent + sum(int(item.get("cost") or 0) for item in selected)
        drain_budget = max(0, budget - spent_so_far)
        if drain_budget > 0:
            picked_groups = hard_groups | {self._candidate_group_id(item) for item in selected}
            sweep_picks = []
            for candidate in candidates or []:
                group_id = self._candidate_group_id(candidate)
                if not group_id or group_id in picked_groups:
                    continue
                cheapest = None
                cheapest_cost = None
                for variant in self._final_candidate_variants(candidate, drain_budget):
                    cost = int(variant.get("cost") or self._estimate_cost(variant))
                    if cost <= 0 or cost > drain_budget:
                        continue
                    if cheapest_cost is None or cost < cheapest_cost:
                        cheapest = variant
                        cheapest_cost = cost
                if not cheapest:
                    continue
                row = dict(cheapest)
                row["cost"] = cheapest_cost
                row["optimizer_score"] = self._optimizer_skill_score(row, chara, preset, priority)
                row["resolution_reason"] = f"{row.get('resolution_reason') or 'drain_sweep'}_drain"
                row["drain_sweep"] = True
                sweep_picks.append(row)
                picked_groups.add(group_id)
                drain_budget -= cheapest_cost
                if drain_budget <= 0:
                    break
            if sweep_picks:
                selected = selected + sweep_picks
        return hard_selected + selected

    def _final_candidate_variants(self, candidate, budget):
        variants = []
        failed = self._failed_for_turn()

        def add_variant(skill_id, source):
            try:
                skill_id = int(skill_id or 0)
            except (TypeError, ValueError):
                return
            if self._is_skill_blocked_for_purchase(skill_id, failed):
                return
            name = self.skill_names.get(skill_id) or candidate.get("name") or ""
            if not name or name.endswith((MARK_X, UNICODE_X, MOJI_X)):
                return
            row = dict(candidate)
            row["skill_id"] = skill_id
            row["name"] = name
            row["group_id"] = self._skill_group_id(skill_id)
            row["cost"] = self._estimate_cost({
                "skill_id": skill_id,
                "name": name,
                "hint_level": candidate.get("hint_level") or 0,
            })
            row["resolution_reason"] = f"{candidate.get('resolution_reason') or 'candidate'}_{source}"
            variants.append(row)

        add_variant(candidate.get("skill_id"), "selected")
        deduped = []
        seen = set()
        for row in variants:
            skill_id = int(row.get("skill_id") or 0)
            if skill_id in seen:
                continue
            seen.add(skill_id)
            if int(row.get("cost") or 0) <= budget:
                deduped.append(row)
        return deduped

    def _run_group_knapsack(self, groups, budget):
        if not groups:
            return []
        budget = max(0, int(budget or 0))
        neg = -10**15
        dp_prev = [0] * (budget + 1)
        dp_curr = [neg] * (budget + 1)
        choices = [[-1] * (budget + 1) for _ in range(len(groups) + 1)]

        for group_index, options in enumerate(groups, start=1):
            has_none = any(option.get("none") for option in options)
            for current_budget in range(budget + 1):
                if has_none:
                    dp_curr[current_budget] = dp_prev[current_budget]
                    choices[group_index][current_budget] = -1
                else:
                    dp_curr[current_budget] = neg
                    choices[group_index][current_budget] = -1
                for option_index, option in enumerate(options):
                    if option.get("none"):
                        continue
                    cost = max(0, int(option.get("cost") or 0))
                    score = max(0, int(option.get("score") or 0))
                    if cost <= current_budget and dp_prev[current_budget - cost] > neg // 2:
                        value = dp_prev[current_budget - cost] + score
                        if value > dp_curr[current_budget]:
                            dp_curr[current_budget] = value
                            choices[group_index][current_budget] = option_index
            dp_prev, dp_curr = dp_curr, [neg] * (budget + 1)

        if dp_prev[budget] <= neg // 2:
            return []

        selected = []
        remaining = budget
        for group_index in range(len(groups), 0, -1):
            option_index = choices[group_index][remaining]
            if option_index >= 0:
                option = groups[group_index - 1][option_index]
                candidate = option.get("candidate")
                if candidate:
                    selected.append(candidate)
                remaining -= max(0, int(option.get("cost") or 0))
        selected.reverse()
        return selected

    def _skill_activation_record(self, candidate):
        try:
            skill_id = int((candidate or {}).get("skill_id") or 0)
        except (TypeError, ValueError):
            skill_id = 0
        if not skill_id:
            return None
        return self.skill_activation_data.get(skill_id)

    def _activation_roles(self, record):
        roles = set()
        condition = str((record or {}).get("condition") or "")
        for match in re.finditer(r"running_style\s*==\s*([1-4])", condition):
            roles.add({"1": "front", "2": "pace", "3": "late", "4": "end"}.get(match.group(1), ""))
        for match in re.finditer(r"distance_type\s*==\s*([1-4])", condition):
            roles.add({"1": "sprint", "2": "mile", "3": "medium", "4": "long"}.get(match.group(1), ""))
        tag_roles = {
            "run": "front",
            "ldr": "pace",
            "btw": "late",
            "cha": "end",
            "sho": "sprint",
            "mil": "mile",
            "med": "medium",
            "lng": "long",
            "tur": "turf",
            "dir": "dirt",
        }
        for tag in (record or {}).get("tags") or []:
            role = tag_roles.get(str(tag).lower())
            if role:
                roles.add(role)
        roles.discard("")
        return roles

    def _activation_data_score(self, candidate, preset):
        record = self._skill_activation_record(candidate)
        if not record:
            return 0.0
        category = str(record.get("category") or "").lower()
        effect_type = str(record.get("effect_type") or "").lower()
        try:
            magnitude = abs(float(record.get("effect_magnitude") or 0.0))
        except (TypeError, ValueError):
            magnitude = 0.0
        if category == "speed":
            score = 520.0 * max(0.35, magnitude) / 0.35
        elif category == "acceleration":
            score = 560.0 * max(0.30, magnitude) / 0.40
        elif category == "recovery":
            score = 380.0 + min(180.0, magnitude * 32.0)
        elif category == "passive":
            stat_passive = effect_type.endswith("_stat_up") or effect_type == "all_stats"
            score = 260.0 + (90.0 if stat_passive else 0.0) + min(170.0, magnitude * 1.8)
        elif category == "debuff":
            score = 190.0 + min(130.0, magnitude * 900.0)
        else:
            score = 220.0

        if str(record.get("color") or "").lower() == "gold":
            score *= 1.08

        target_roles = self._skill_plan_target_roles(preset)
        roles = self._activation_roles(record)
        if target_roles and roles:
            if roles & target_roles:
                score += 240.0
            else:
                role_categories = {self._role_category(role) for role in roles}
                target_categories = {self._role_category(role) for role in target_roles}
                if role_categories & target_categories:
                    score *= 0.42

        try:
            cost = int(candidate.get("cost") or record.get("cost") or self._estimate_cost(candidate))
        except (TypeError, ValueError):
            cost = 180
        if cost > 0:
            score *= (180.0 / max(80.0, float(cost))) ** 0.18
        return max(0.0, score)

    def _optimizer_skill_score(self, candidate, chara, preset, priority):
        rating = self._rating_metadata_score(candidate, chara, preset)
        if rating <= 0:
            rating = self._heuristic_rating_score(candidate, preset)
        activation_rating = self._activation_data_score(candidate, preset)
        if activation_rating > rating:
            rating = activation_rating

        profile_bonus = self._profile_match_bonus(candidate, preset)
        priority_value = int(candidate.get("priority", 999))
        if priority_value < 999:
            # Explicit or generated skill-plan rows remain strong preferences,
            # but the optimizer can still choose two better profile skills over
            # one inefficient fallback when budget is tight.
            profile_bonus += max(0, 900 - (priority_value * 120))
        if int(candidate.get("tip_rarity") or 0) > 0:
            profile_bonus += 180
        if candidate.get("profile_fallback"):
            profile_bonus -= 120

        cost = int(candidate.get("cost") or self._estimate_cost(candidate))
        base_score = int(max(0, rating + profile_bonus) * 100 + min(cost, 300))
        # Lineage-aware multiplier. Spark generation rate compounds at
        # 1.1^lineage_count (per spark_rates.WHITE_GENERATION_LINEAGE_MULTIPLIER),
        # so a skill that's already in the trainee's lineage has a
        # meaningfully higher chance of producing a white spark when
        # bought. Soft preference (multiplier), not a force-buy — gold
        # tier and user-named priorities still come first.
        lineage_mult = self._lineage_multiplier(candidate, chara)
        if lineage_mult > 1.0:
            candidate["_lineage_multiplier"] = round(lineage_mult, 3)
            base_score = int(base_score * lineage_mult)
        return base_score

    def _rating_metadata_score(self, candidate, chara, preset):
        meta = self._rating_meta_for_candidate(candidate)
        if not meta:
            return 0
        roles = meta.get("roles") or []
        base = float(meta.get("base") or 0)
        scores = meta.get("scores") or {}
        if not roles:
            return base

        target_roles = self._skill_plan_target_roles(preset)
        if target_roles and any(role in target_roles for role in roles):
            bucket = "good"
        else:
            buckets = [self._role_aptitude_bucket(chara, role) for role in roles]
            bucket_rank = {"good": 0, "average": 1, "bad": 2, "terrible": 3}
            bucket = min(buckets, key=lambda item: bucket_rank.get(item, 9)) if buckets else "average"
            if target_roles and any(role in VALID_RATING_ROLES for role in roles):
                role_categories = {self._role_category(role) for role in roles}
                target_categories = {self._role_category(role) for role in target_roles}
                if role_categories & target_categories:
                    # Off-style/off-distance skills are usually bad buys even
                    # when the uma has an acceptable secondary aptitude.
                    bucket = "bad"
        scored = scores.get(bucket)
        return float(scored if scored is not None else base)

    def _rating_meta_for_candidate(self, candidate):
        if not self.skill_rating_meta:
            return None
        name = candidate.get("name") or self.skill_names.get(int(candidate.get("skill_id") or 0), "")
        for key in (norm(name), norm(strip_mark(name))):
            if key in self.skill_rating_meta:
                return self.skill_rating_meta[key]
        return None

    def _heuristic_rating_score(self, candidate, preset):
        name = candidate.get("name") or ""
        skill_id = int(candidate.get("skill_id") or 0)
        clean = norm(strip_mark(name))
        if skill_id < 100000:
            base = 180
        elif skill_id >= 900000:
            base = 180
        elif name.endswith((MARK_DOUBLE_CIRCLE, UNICODE_DOUBLE_CIRCLE, MOJI_DOUBLE_CIRCLE)):
            base = 262
        elif any(mark in name for mark in (
            MARK_WHITE_CIRCLE, MARK_LARGE_CIRCLE, UNICODE_WHITE_CIRCLE,
            UNICODE_LARGE_CIRCLE, MOJI_WHITE_CIRCLE, MOJI_LARGE_CIRCLE,
        )):
            base = 217
        elif skill_id % 10 == 1:
            base = 508
        else:
            base = 217
        if clean in {norm(item) for item in COMMON_SKILLS}:
            base += 60
        return base

    def _profile_match_bonus(self, candidate, preset):
        name = strip_mark(candidate.get("name") or "")
        key = norm(name)
        style = normalize_profile_style((preset or {}).get("skill_profile_style") or "")
        distance = normalize_profile_distance((preset or {}).get("skill_profile_distance") or "")

        bonus = 0
        style_names = {norm(item) for item in STYLE_SKILLS.get(style, [])}
        distance_names = {norm(item) for item in DISTANCE_SKILLS.get(distance, [])}
        if key in style_names:
            bonus += 360
        if key in distance_names:
            bonus += 360
        if key in {norm(item) for item in COMMON_SKILLS}:
            bonus += 100

        roles = self._name_trigger_roles(name)
        target_roles = self._skill_plan_target_roles(preset)
        if target_roles and roles:
            if roles & target_roles:
                bonus += 220
            elif {self._role_category(role) for role in roles} & {self._role_category(role) for role in target_roles}:
                bonus -= 380
        return bonus

    def _name_trigger_roles(self, name):
        words = set(re.findall(r"[a-z0-9]+", str(name or "").lower().replace("_", " ")))
        roles = set()
        for role, needles in STYLE_TRIGGER_WORDS.items():
            if words & needles:
                roles.add(role)
        for role, needles in DISTANCE_TRIGGER_WORDS.items():
            if words & needles:
                roles.add(role)
        return roles

    def _skill_plan_target_roles(self, preset):
        targets = set()
        style = normalize_profile_style((preset or {}).get("skill_profile_style") or "")
        distance = normalize_profile_distance((preset or {}).get("skill_profile_distance") or "")
        if style in STYLE_PROFILE_TO_ROLE:
            targets.add(STYLE_PROFILE_TO_ROLE[style])
        if distance:
            targets.add(distance)
        return targets

    def _normalize_rating_role(self, value):
        text = str(value or "").strip().lower().replace("_", " ").replace("-", " ")
        text = re.sub(r"\s+", " ", text)
        role = RATING_ROLE_ALIASES.get(text, text)
        return role if role in VALID_RATING_ROLES else ""

    def _role_category(self, role):
        if role in {"front", "pace", "late", "end"}:
            return "style"
        if role in {"sprint", "mile", "medium", "long"}:
            return "distance"
        if role in {"turf", "dirt"}:
            return "surface"
        return "other"

    def _role_aptitude_bucket(self, chara, role):
        field = CHARA_APTITUDE_FIELDS.get(role)
        try:
            value = int((chara or {}).get(field) or 0)
        except (TypeError, ValueError):
            value = 0
        if value >= 7:
            return "good"
        if value >= 4:
            return "average"
        if value >= 1:
            return "bad"
        return "terrible"

    def _candidates_with_fallback(self, chara, preset, force=False):
        candidates = self._candidates(chara, preset, force=force)

        priority = self._priority_context(preset)
        if not priority or preset.get("learn_skill_only_user_provided"):
            return candidates

        # Normal-skill fallback path — extends candidate list with tips that
        # didn't match the user's named priorities. Always merge in force mode
        # so end-of-career SP drain can actually spend remaining budget; mid-
        # career still only falls back when the primary list was empty.
        fallback_candidates = self._candidates(chara, self._normal_skill_preset(preset), force=force)
        for item in fallback_candidates:
            item["profile_fallback"] = True
        if force:
            return self._merge_skill_candidates(candidates, fallback_candidates)
        if candidates:
            return candidates
        return fallback_candidates

    def _fallback_after_recovery_cap(self, chara, preset):
        """If profile candidates were all capped recovery skills, use normal priorities.

        This preserves the intended "buy style/distance first, then fall back to useful
        defaults" behavior without letting the final SP dump stack extra recoveries.
        """
        if not self.last_recovery_cap_skipped:
            return []
        if not self._priority_context(preset) or (preset or {}).get("learn_skill_only_user_provided"):
            return []
        fallback_candidates = self._candidates(chara, self._normal_skill_preset(preset), force=True)
        for item in fallback_candidates:
            item["profile_fallback"] = True
        return self._apply_general_recovery_cap(fallback_candidates, chara, preset, append_skipped=True)

    def _general_recovery_cap(self, preset):
        preset = preset or {}
        raw = preset.get(
            "final_stamina_recovery_max_count",
            preset.get("general_stamina_recovery_max_count", DEFAULT_FINAL_STAMINA_RECOVERY_MAX_COUNT),
        )
        try:
            return max(0, int(raw))
        except (TypeError, ValueError):
            return DEFAULT_FINAL_STAMINA_RECOVERY_MAX_COUNT

    def _apply_general_recovery_cap(self, candidates, chara, preset, append_skipped=False, force=False):
        """Cap recovery skills during normal/end skill dumps.

        Pre-race stamina rescue uses buy_stamina_for_race() and is intentionally
        separate. This guard prevents the final SP dump from buying every available
        recovery-like skill after the character already has enough recovery coverage.

        End-of-career force mode still respects this cap; if profile recoveries are
        exhausted by the cap, the caller can fall back to normal useful skills.
        """
        if not append_skipped:
            self.last_recovery_cap_skipped = []
        cap = self._general_recovery_cap(preset)
        owned_count = self._stamina_recovery_skill_count(chara)
        selected_count = owned_count
        result = []
        for item in candidates or []:
            if self._is_stamina_recovery_skill(item.get("skill_id"), item.get("name")):
                if selected_count >= cap:
                    skipped = dict(item)
                    skipped["skip_reason"] = "stamina_recovery_cap"
                    skipped["owned_recovery_count"] = owned_count
                    skipped["max_recovery_count"] = cap
                    if int(skipped.get("skill_id") or 0) not in {
                        int(row.get("skill_id") or 0) for row in self.last_recovery_cap_skipped
                    }:
                        self.last_recovery_cap_skipped.append(skipped)
                    continue
                selected_count += 1
            result.append(item)
        return result

    def _priority(self, rows):
        result = {}
        for index, row in enumerate(rows):
            for name in row:
                key = norm(name)
                result[key] = min(index, result.get(key, index))
        return result

    def _priority_value(self, skill_id, name, base_name, priority):
        values = [priority.get(str(skill_id)), priority.get(norm(name)), priority.get(norm(base_name))]
        values = [v for v in values if v is not None]
        return min(values) if values else 999

    def _priority_context(self, preset):
        raw_priority = preset.get("learn_skill_list") or []
        if raw_priority:
            rows = list(raw_priority)
            if preset.get("learn_skill_append_defaults") and not preset.get("learn_skill_only_user_provided"):
                rows.extend(SKILL_LEARN_PRIORITY_LIST)
            return self._priority(rows)
        if not preset.get("learn_skill_only_user_provided"):
            return self._priority(SKILL_LEARN_PRIORITY_LIST)
        return self._priority([])

    def _has_priority_plan(self, preset, priority=None):
        if priority is None:
            priority = self._priority_context(preset)
        return bool(priority)

    def _configured_priority_keys(self, preset):
        """Names/ids the user or saved skill plan explicitly wants.

        Defaults from SKILL_LEARN_PRIORITY_LIST are intentionally excluded so a
        real blacklist can still suppress generic defaults. Anything saved in
        the UI skill plan should win over stale learned/legacy blacklists.
        """
        keys = set()
        preset = preset or {}
        for row in preset.get("learn_skill_list") or []:
            items = row if isinstance(row, (list, tuple)) else [row]
            for item in items:
                key = norm(item)
                if key:
                    keys.add(key)
                text = str(item or "").strip()
                if text.isdigit():
                    keys.add(text)
        for item in preset.get("skill_buy_on_sight") or []:
            key = norm(item)
            if key:
                keys.add(key)
            text = str(item or "").strip()
            if text.isdigit():
                keys.add(text)
        return keys

    def _final_priority_keys(self, preset):
        """Only the first skill-plan row is the hard end-career priority row."""
        preset = preset or {}
        rows = preset.get("learn_skill_list") or []
        hard_rows = []
        if rows:
            hard_rows.append(rows[0])
        if preset.get("skill_buy_on_sight"):
            hard_rows.append(preset.get("skill_buy_on_sight") or [])
        keys = set()
        for row in hard_rows:
            items = row if isinstance(row, (list, tuple)) else [row]
            for item in items:
                key = norm(item)
                if key:
                    keys.add(key)
                text = str(item or "").strip()
                if text.isdigit():
                    keys.add(text)
        return keys

    def _candidate_matches_keys(self, candidate, keys):
        if not keys:
            return False
        try:
            skill_id = int((candidate or {}).get("skill_id") or 0)
        except (TypeError, ValueError):
            skill_id = 0
        group_id = self._candidate_group_id(candidate)
        names = [
            str(skill_id) if skill_id else "",
            str(group_id) if group_id else "",
            (candidate or {}).get("name") or "",
            strip_mark((candidate or {}).get("name") or ""),
            self.skill_names.get(skill_id, "") if skill_id else "",
            strip_mark(self.skill_names.get(skill_id, "")) if skill_id else "",
        ]
        candidate_ids = []
        for raw in (candidate or {}).get("candidate_skill_ids") or []:
            try:
                candidate_ids.append(int(raw))
            except (TypeError, ValueError):
                continue
        names.extend(str(sid) for sid in candidate_ids if sid)
        names.extend(self.skill_names.get(sid, "") for sid in candidate_ids if sid)
        names.extend(strip_mark(self.skill_names.get(sid, "")) for sid in candidate_ids if sid)
        return any((norm(name) in keys) or (str(name).strip() in keys) for name in names if name)

    def _blacklist(self, preset):
        blacklist = {norm(item) for item in preset.get("learn_skill_blacklist") or []}
        return blacklist - self._configured_priority_keys(preset)

    def _is_stamina_recovery_skill(self, skill_id, name=None):
        names = []
        if name:
            names.append(name)
        try:
            skill_id = int(skill_id or 0)
        except (TypeError, ValueError):
            skill_id = 0
        if skill_id:
            names.append(self.skill_names.get(skill_id, ""))
        for value in names:
            clean = norm(strip_mark(value))
            if clean in STAMINA_RECOVERY_SKILLS:
                return True
        return False

    def _has_stamina_recovery_skill(self, chara):
        return self._stamina_recovery_skill_count(chara) > 0

    def _stamina_recovery_skill_count(self, chara):
        count = 0
        for skill_id in self._owned_skill_ids(chara):
            if self._is_stamina_recovery_skill(skill_id):
                count += 1
        return count

    def usable_stamina_recovery_skill_count(self, chara, stamina_check):
        return self._usable_stamina_recovery_skill_count(chara, stamina_check)

    def _usable_stamina_recovery_skill_count(self, chara, stamina_check):
        count = 0
        for skill_id in self._owned_skill_ids(chara):
            name = self.skill_names.get(skill_id, "")
            if not self._is_stamina_recovery_skill(skill_id, name):
                continue
            if self._stamina_skill_match_score({"skill_id": skill_id, "name": name}, stamina_check) < 99:
                count += 1
        return count

    def _max_stamina_recovery_count(self, preset):
        try:
            return max(1, min(int((preset or {}).get("race_stamina_skill_max_count") or 1), 1))
        except (TypeError, ValueError):
            return 1

    def _card_id(self, chara):
        for key in ("card_id", "chara_id"):
            try:
                value = int(chara.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value:
                return value
        return 0

    def _race_unique_recovery_profile(self, chara, preset, stamina_check=None):
        stamina_check = stamina_check or {}
        return race_unique_recovery_profile(
            chara,
            distance=(stamina_check or {}).get("distance"),
            style=(stamina_check or {}).get("style"),
            count_conditional=bool((preset or {}).get("count_conditional_recovery_uniques")),
        )

    def _stamina_skill_match_score(self, candidate, stamina_check):
        clean = norm(strip_mark(candidate.get("name")))
        tags = STAMINA_RECOVERY_TAGS.get(clean, {"generic"})
        style = str(stamina_check.get("style") or "")
        distance = str(stamina_check.get("distance") or "").lower()
        desired = {style, distance}
        if tags & desired:
            return 0
        if "generic" in tags or not tags:
            return 1
        return 99

    def race_profile_safety_skill_count(self, chara, preset, stamina_check):
        return self._race_profile_safety_skill_count(chara, preset, stamina_check)

    def _race_profile_safety_skill_count(self, chara, preset, stamina_check):
        safety_keys = {norm(name) for name in self._race_profile_safety_names(preset, stamina_check)}
        count = 0
        for skill_id in self._owned_skill_ids(chara):
            name = self.skill_names.get(skill_id, "")
            if norm(strip_mark(name)) in safety_keys:
                count += 1
        return count

    def _race_profile_safety_names(self, preset, stamina_check):
        style = normalize_profile_style(
            (stamina_check or {}).get("style") or (preset or {}).get("skill_profile_style") or ""
        )
        names = list(STYLE_SKILLS.get(style, []))
        configured = (preset or {}).get("kikuka_front_runner_generic_skill_names")
        generic_names = self._split_configured_names(configured) or list(DEFAULT_KIKUKA_GENERIC_SAFETY_SKILLS)
        names.extend(generic_names)
        result = []
        seen = set()
        for name in names:
            key = norm(name)
            if key and key not in seen:
                seen.add(key)
                result.append(name)
        return result

    def _split_configured_names(self, value):
        if value is None:
            return []
        if isinstance(value, (list, tuple)):
            raw = value
        else:
            raw = str(value).replace(",", "\n").splitlines()
        return [str(item).strip() for item in raw if str(item).strip()]

    def _stamina_skill_needed(self, chara, preset, stamina_check):
        requirements = stamina_check.get("requirements") or {}
        stats = stamina_check.get("stats") or {}
        required_stamina = int(requirements.get("stamina") or 0)
        current_stamina = int(stats.get("stamina") or chara.get("stamina") or 0)
        distance = str(stamina_check.get("distance") or "")
        if required_stamina <= 0 or distance not in {"Medium", "Long"}:
            self.last_result = {"skip": "race_stamina_skill_not_relevant", "distance": distance}
            return False
        min_ratio = float(stamina_check.get("min_stamina_ratio") or preset.get("race_stamina_skill_min_ratio") or 0.96)
        stamina_low = (
            bool(stamina_check.get("stamina_low"))
            or bool(stamina_check.get("static_stamina_low"))
            or current_stamina < int(required_stamina * min_ratio)
        )
        if not stamina_low:
            self.last_result = {
                "skip": "stamina_requirement_met",
                "current_stamina": current_stamina,
                "required_stamina": required_stamina,
                "min_ratio": min_ratio,
            }
            return False
        recovery_count = self._usable_stamina_recovery_skill_count(chara, stamina_check)
        max_count = self._max_stamina_recovery_count(preset)
        if recovery_count >= max_count:
            if max_count <= 1:
                self.last_result = {"skip": "already_has_usable_stamina_recovery_skill", "race": stamina_check.get("race_name")}
                return False
            self.last_result = {
                "skip": "stamina_recovery_skill_cap_reached",
                "race": stamina_check.get("race_name"),
                "owned_usable_recovery_count": recovery_count,
                "max_recovery_count": max_count,
            }
            return False
        unique_recovery = self._race_unique_recovery_profile(chara, preset, stamina_check)
        if unique_recovery:
            self.last_result = {
                "skip": "reliable_recovery_unique",
                "race": stamina_check.get("race_name"),
                "card_id": self._card_id(chara),
                "unique_recovery_profile": unique_recovery,
            }
            return False
        self.last_result = {
            "trigger": "stamina_requirement_unmet",
            "race": stamina_check.get("race_name"),
            "current_stamina": current_stamina,
            "required_stamina": required_stamina,
            "min_ratio": min_ratio,
            "distance": stamina_check.get("distance"),
            "style": stamina_check.get("style"),
        }
        return True

    def _candidates(self, chara, preset, force=False):
        priority = self._priority_context(preset)
        result = []
        for resolved in self._resolved_tip_rows(chara, preset):
            if not resolved or resolved.get("skip_reason"):
                continue
            result.append({
                "skill_id": resolved["resolved_skill_id"],
                "resolved_skill_id": resolved["resolved_skill_id"],
                "default_resolved_skill_id": resolved.get("default_resolved_skill_id") or 0,
                "group_id": resolved["group_id"],
                "tip_rarity": resolved["tip_rarity"],
                "hint_level": resolved["hint_level"],
                "name": resolved["resolved_name"],
                "resolved_name": resolved["resolved_name"],
                "default_resolved_name": resolved.get("default_resolved_name") or "",
                "priority_selected_skill_id": resolved.get("priority_selected_skill_id") or 0,
                "priority_selected_name": resolved.get("priority_selected_name") or "",
                "priority_override_blocked": bool(resolved.get("priority_override_blocked")),
                "priority": resolved["priority"],
                "cost": resolved["cost"],
                "resolution_reason": resolved["resolution_reason"],
                "failed_scope": resolved["failed_scope"],
                "candidate_skill_ids": resolved["candidate_skill_ids"],
            })
        result.sort(key=lambda item: (item["priority"], -item["hint_level"], item["cost"], item["skill_id"]))

        deduped = []
        seen = set()
        for item in result:
            if item["skill_id"] not in seen:
                seen.add(item["skill_id"])
                deduped.append(item)
        result = deduped

        # When a priority map exists, only buy skills that actually matched it.
        # This prevents mid-career SP from drifting into random off-style tips.
        # BUT — `force=True` is the end-of-career drain path. At that point any
        # affordable skill is better than letting 1000+ SP rot. Skip the filter
        # in force mode so the bot can spend leftover budget on non-priority
        # tips that the server is offering.
        if self._has_priority_plan(preset, priority) and (not force or self._has_explicit_skill_profile(preset)):
            result = [item for item in result if int(item.get("priority", 999)) < 999]

        if preset.get("learn_skill_only_user_provided"):
            if not any(row for row in (preset.get("learn_skill_list") or [])):
                return []
            if force:
                return result  # drain mode overrides user-only restriction too
            return [item for item in result if item["priority"] < 999]
        return result

    def _resolved_tip_rows(self, chara, preset):
        owned = self._owned_skill_ids(chara)
        owned_groups = self._owned_groups(chara)
        priority = self._priority_context(preset)
        blacklist = self._blacklist(preset)
        rows = []
        for tip in chara.get("skill_tips_array") or []:
            rows.append(self.resolve_skill_tip(tip, owned, owned_groups, priority, blacklist, preset))
        return rows

    def resolve_skill_tip(self, tip, owned_skill_ids, owned_groups, priority, blacklist, preset):
        group_id = int(tip.get("group_id") or 0)
        tip_rarity = int(tip.get("rarity") or 0)
        hint_level = int(tip.get("level") or 0)
        failed = self._failed_for_turn()
        candidate_skill_ids = [
            sid for sid in self.group_to_skill_ids.get(group_id, [])
            if (
                sid not in owned_skill_ids
                and not self._is_skill_blocked_for_purchase(sid, failed)
                and not self._missing_purchase_prereqs(sid, owned_skill_ids)
            )
        ]
        
        row = {
            "group_id": group_id,
            "tip_rarity": tip_rarity,
            "hint_level": hint_level,
            "candidate_skill_ids": list(candidate_skill_ids),
            "resolved_skill_id": 0,
            "resolved_name": "",
            "default_resolved_skill_id": 0,
            "default_resolved_name": "",
            "priority_selected_skill_id": 0,
            "priority_selected_name": "",
            "priority_override_blocked": False,
            "cost": 0,
            "priority": 999,
            "resolution_reason": "",
            "master_exists": False,
            "skip_reason": None,
            "failed_scope": None,
        }
        if group_id in owned_groups:
            row["skip_reason"] = "owned_group"
            return row
        if failed_group_key(group_id) in failed:
            row["skip_reason"] = "failed_group_this_turn"
            row["failed_scope"] = "this_turn"
            return row
        if not candidate_skill_ids:
            row["skip_reason"] = "unknown_master"
            return row

        usable = [sid for sid in candidate_skill_ids if not self._is_skill_blocked_for_purchase(sid, failed)]
        if not usable:
            row["skip_reason"] = "failed_this_turn"
            row["failed_scope"] = "this_turn"
            return row

        normal = [
            sid for sid in usable
            if not self.skill_names.get(sid, "").endswith((MARK_X, UNICODE_X, MOJI_X))
        ]
        if not normal:
            row["skip_reason"] = "no_normal_skills"
            return row

        def tier_order(sid):
            last_digit = sid % 10
            if last_digit == 2: return 0
            if last_digit == 1: return 1
            if last_digit == 4: return 2
            if last_digit == 5: return 3
            return 99

        normal.sort(key=tier_order)
        resolved = normal[0]
        name = self.skill_names.get(resolved, "")
        row["default_resolved_skill_id"] = resolved
        row["default_resolved_name"] = name
        configured_priority_keys = self._configured_priority_keys(preset or {})
        
        best_priority = 999
        best_sid = resolved
        reason = "first_valid_variant"
        usable_normal = []
        blocked_by_blacklist = False
        best_is_explicit_priority = False
        
        for sid in normal:
            s_name = self.skill_names.get(sid, "")
            base_name = strip_mark(s_name)
            p_val = self._priority_value(sid, s_name, base_name, priority)
            explicit_priority_hit = any(
                key in configured_priority_keys
                for key in (
                    str(sid),
                    str(group_id),
                    norm(s_name),
                    norm(base_name),
                )
                if key
            )
            is_blacklisted = norm(s_name) in blacklist or norm(base_name) in blacklist
            if is_blacklisted and p_val >= 999:
                blocked_by_blacklist = True
                continue
            usable_normal.append(sid)
            if p_val < best_priority:
                best_priority = p_val
                best_sid = sid
                reason = "priority_match"
                best_is_explicit_priority = explicit_priority_hit

        if not usable_normal:
            row["skip_reason"] = "blacklist" if blocked_by_blacklist else "no_normal_skills"
            return row
        if resolved not in usable_normal:
            resolved = usable_normal[0]
            name = self.skill_names.get(resolved, "")
            best_sid = resolved

        # Inherited gold / chara unique boost: in the game's API, a tip with
        # rarity > 0 is a gold-tier inherited skill (the green-bordered ones
        # that come from parent inspirations or are the trainee's own unique).
        # Without this boost, they get the same weight as plain whites — which
        # is why parent careers were buying 13 whites and zero golds even when
        # parents had great unique sparks to pass down. Force them ahead of
        # plain whites whenever no explicit priority name matched.
        has_user_priority = self._has_explicit_skill_profile(preset)
        if best_priority >= 999 and tip_rarity > 0 and not has_user_priority and not preset.get("learn_skill_only_user_provided"):
            best_priority = 1  # below an explicit priority hit (0) but above all whites
            reason = "rarity_unique_boost"

        if best_priority < 999:
            row["priority_selected_skill_id"] = best_sid
            row["priority_selected_name"] = self.skill_names.get(best_sid, "")
            if best_sid != resolved and not best_is_explicit_priority:
                row["priority_override_blocked"] = True
                reason = "priority_match_blocked_to_default_variant"
            else:
                resolved = best_sid
                name = self.skill_names.get(resolved, "")
        elif not self._has_priority_plan(preset, priority):
            for sid in usable_normal:
                s_name = self.skill_names.get(sid, "")
                if any(s_name.endswith(m) for m in [
                    MARK_WHITE_CIRCLE, MARK_LARGE_CIRCLE,
                    UNICODE_WHITE_CIRCLE, UNICODE_LARGE_CIRCLE,
                    MOJI_WHITE_CIRCLE, MOJI_LARGE_CIRCLE,
                ]):
                    resolved = sid
                    name = s_name
                    best_priority = 500
                    reason = "circle_variant"
                    break

        if not name:
            row["skip_reason"] = "unknown_master"
            return row
            
        # Double circle rule
        is_double = name.endswith((MARK_DOUBLE_CIRCLE, UNICODE_DOUBLE_CIRCLE, MOJI_DOUBLE_CIRCLE))
        if preset.get("skip_double_circle_unless_high_hint", False) and is_double and hint_level < 4:
            row["skip_reason"] = "rule_rejected"
            return row

        row["resolved_skill_id"] = resolved
        row["resolved_name"] = name
        row["cost"] = self._estimate_cost({"skill_id": resolved, "hint_level": hint_level, "name": name})
        row["priority"] = best_priority
        row["resolution_reason"] = reason
        row["master_exists"] = resolved in self.skill_id_exists
        if resolved in failed:
            row["failed_scope"] = "this_turn"

        return row

    def _buy_batch(self, client, state, candidates, turn, preset=None):
        if not candidates:
            return state, 0

        data = state.get("data") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        current_turn = int(chara.get("turn") or 0)
        
        if current_turn != turn:
            self.last_result = {"skip": "stale_turn_detected", "request_current_turn": turn, "source_state_turn": current_turn}
            return state, 0

        live_tip_rows = self._resolved_tip_rows(chara, preset or {})
        live_tip_rows_by_group = {}
        valid_tips = set()
        for row in live_tip_rows:
            group_id = int(row.get("group_id") or 0)
            if group_id and group_id not in live_tip_rows_by_group:
                live_tip_rows_by_group[group_id] = row
            skill_id = int(row.get("resolved_skill_id") or 0)
            if skill_id > 0:
                valid_tips.add(skill_id)
        if not valid_tips:
            for tip in chara.get("skill_tips_array") or []:
                group_id = int(tip.get("group_id") or 0)
                valid_tips.update(self.group_to_skill_ids.get(group_id, []))

        points = int(chara.get("skill_point") or 0)
        selected_total_cost = 0
        valid_candidates = []

        for item in candidates:
            skill_id = item["skill_id"]
            group_id = int(item.get("group_id") or self._candidate_group_id(item) or self._skill_group_id(skill_id) or 0)
            live_row = live_tip_rows_by_group.get(group_id) or {}
            # The server's current tip row is authoritative. Priority/profile
            # resolution can choose a sibling in the same group, but gain_skills
            # rejects that with 205 if the live row resolves to a different ID.
            live_skill_id = int(live_row.get("resolved_skill_id") or item.get("resolved_skill_id") or 0)
            cost = int(item.get("cost") or 0)
            if skill_id <= 0 or item.get("skip_reason"):
                item["preflight_error"] = "invalid_skill"
                continue
            if int(skill_id) in self.permanent_failed_skills:
                item["preflight_error"] = "permanent_fail_205"
                continue
            if self._is_cross_career_disabled(skill_id):
                item["preflight_error"] = "cross_career_disabled"
                continue
            missing_prereqs = self._missing_purchase_prereqs(skill_id, self._owned_skill_ids(chara))
            if missing_prereqs:
                item["preflight_error"] = "missing_required_base_skill"
                item["missing_required_skill_ids"] = sorted(missing_prereqs)
                item["missing_required_skill_names"] = [
                    self.skill_names.get(sid, str(sid))
                    for sid in sorted(missing_prereqs)
                ]
                continue
            if live_skill_id > 0 and int(skill_id) != live_skill_id:
                item["preflight_error"] = "not_live_resolved_variant"
                item["live_resolved_skill_id"] = live_skill_id
                item["live_resolved_name"] = (
                    live_row.get("resolved_name")
                    or item.get("resolved_name")
                    or self.skill_names.get(live_skill_id, "")
                )
                continue
            if int(skill_id) in self.permanent_failed_skills:
                # Server has rejected this skill repeatedly this career — don't
                # waste another gain_skills call on it. The retry-loop will pick
                # the next affordable candidate from the priority list.
                item["preflight_error"] = "permanent_fail_205"
                continue
            if self._is_cross_career_disabled(skill_id):
                # Skill has been disabled in multiple consecutive careers — it's
                # almost certainly broken for this build (prereq miss, group
                # already owned, etc.). Skip permanently until the
                # skill_failures.json file is deleted by hand.
                item["preflight_error"] = "cross_career_disabled"
                continue
            if skill_id not in valid_tips:
                item["preflight_error"] = "not_in_live_tips"
                continue
            if selected_total_cost + cost > points:
                item["preflight_error"] = "unaffordable"
                continue
            item["preflight_passed"] = True
            selected_total_cost += cost
            valid_candidates.append(item)

        if not valid_candidates:
            self.last_result = {"skip": "preflight_failed", "turn": turn, "points": points}
            return state, 0

        payload = [{"skill_id": item["skill_id"], "level": 1} for item in valid_candidates]
        self.last_attempt = [dict(item) for item in valid_candidates]
        event = {
            "turn": turn,
            "selected": [dict(item) for item in candidates],
            "attempt": [dict(item) for item in valid_candidates],
            "payload": payload,
            "recovery_cap_skipped": [dict(item) for item in self.last_recovery_cap_skipped],
            "result": {},
        }
        self.attempt_events.append(event)

        try:
            if hasattr(client, "wait_complex_delay"):
                client.wait_complex_delay()
            # 205/208 are often transient sync/double-click responses during
            # long loop sessions. Retrying the first batch prevents a one-skill
            # pre-race safety buy from being dropped before the per-skill
            # fallback can help.
            result = client.gain_skills(payload, turn, retry_205=1, retry_208=1)
            self._remember_bought(valid_candidates)
            result = self.enrich_state_with_known_bought(result)
            self.last_result = {"result": "ok", "turn": turn, "count": len(valid_candidates), "payload": payload}
            event["result"] = self.last_result
            self._failed_for_turn(turn).clear()
            return result, len(valid_candidates)
        except Exception as exc:
            print(f"Skill Purchase Error at turn {turn}: {exc}")
            is_recoverable = any(code in str(exc) for code in ("201", "205", "208"))
            if is_recoverable:
                # Don't fire load_career here. When the server returns 205/208 it's already
                # under rate-limit pressure, and adding another sensitive call (load_career)
                # makes recovery slower. The caller (_buy_skills) will reload via
                # _fresh_career_state when recover_after_error is set.
                self.recover_after_error = True
            # A 205 on a multi-skill batch usually means *one* skill in the payload is
            # invalid (cost mismatch, no longer in the tip list, etc.) and the server
            # rejects the whole batch. Fall back to per-skill calls so the bad apple
            # doesn't sink the whole basket — we mark the actually-failing skills and
            # keep the ones that succeed.
            if is_recoverable and "205" in str(exc) and len(valid_candidates) > 1:
                per_state, per_bought, accepted_ids, rejected_ids, skipped_ids = self._buy_per_skill(
                    client, state, valid_candidates, turn
                )
                if per_bought:
                    if not rejected_ids:
                        self.recover_after_error = False
                        self.last_result = {
                            "result": "ok_after_recovery",
                            "turn": turn,
                            "count": per_bought,
                            "accepted": accepted_ids,
                            "rejected": rejected_ids,
                            "skipped": skipped_ids,
                            "per_skill_rejections": list(self.last_per_skill_rejections),
                            "payload": payload,
                            "recoverable": True,
                            "error_codes": extract_error_codes(str(exc)),
                            "batch_error_details": exception_details(exc),
                        }
                        event["result"] = self.last_result
                        return per_state, per_bought
                    self.last_result = {
                        "result": "ok_partial",
                        "turn": turn,
                        "count": per_bought,
                        "accepted": accepted_ids,
                        "rejected": rejected_ids,
                        "skipped": skipped_ids,
                        "per_skill_rejections": list(self.last_per_skill_rejections),
                        "payload": payload,
                        "recoverable": True,
                        "error_codes": extract_error_codes(str(exc)),
                        "batch_error_details": exception_details(exc),
                    }
                    event["result"] = self.last_result
                    return per_state, per_bought
                # Per-skill calls all failed too — same as the original failure but now
                # we know per-skill IDs. Track them and fall through to the normal failure path.
                self._failed_for_turn(turn).update(rejected_ids)
                self.last_result = {
                    "result": "failed",
                    "turn": turn,
                    "error": str(exc),
                    "payload": payload,
                    "rejected": rejected_ids,
                    "skipped": skipped_ids,
                    "per_skill_rejections": list(self.last_per_skill_rejections),
                    "recoverable": True,
                    "error_codes": extract_error_codes(str(exc)),
                    "error_details": exception_details(exc),
                }
                event["result"] = self.last_result
                return state, 0
            failed = self._failed_for_turn(turn)
            for item in valid_candidates:
                skill_id = int(item["skill_id"])
                failed.add(skill_id)
                group_id = self._candidate_group_id(item)
                if group_id:
                    failed.add(failed_group_key(group_id))
                if "205" in str(exc):
                    # A single-skill 205 has already gone through client-level
                    # retry. Disable it for this career so pre-race skill buying
                    # does not hammer the same rejected payload on every forced
                    # race turn.
                    self.permanent_failed_skills.add(skill_id)
            self.last_result = {
                "result": "failed",
                "turn": turn,
                "error": str(exc),
                "payload": payload,
                "recoverable": is_recoverable,
                "error_codes": extract_error_codes(str(exc)),
                "error_details": exception_details(exc),
            }
            event["result"] = self.last_result
            return state, 0

    def _buy_per_skill(self, client, state, candidates, turn):
        """Fall back to one gain_skills call per skill after a batch 205. Returns
        (state, bought_count, accepted_skill_ids, rejected_skill_ids, skipped).

        The API client already retries transient 205/208 responses. Do not add
        an outer retry loop here; doing so creates 205 storms and can keep the
        runner busy long enough to desync from the game state.
        """
        current = state
        bought = 0
        accepted = []
        rejected = []
        skipped = []
        rejected_details = []
        base_chara = ((state.get("data") or {}).get("chara_info") or {}) if isinstance(state, dict) else {}
        local_points = int(base_chara.get("skill_point") or 0)
        for item in candidates:
            try:
                skill_id = int(item["skill_id"])
            except (TypeError, ValueError, KeyError):
                continue
            current_chara = ((current.get("data") or {}).get("chara_info") or {}) if isinstance(current, dict) else {}
            if not current_chara:
                current_chara = base_chara
            state_points = int(current_chara.get("skill_point") or 0)
            points_now = min(state_points, local_points) if state_points and local_points else (state_points or local_points or 0)
            cost = int(item.get("cost") or self._estimate_cost(item))
            group_id = self._candidate_group_id(item)
            if group_id in self._owned_groups(current_chara):
                skipped.append({"skill_id": skill_id, "reason": "already_owned_group"})
                continue
            if points_now and cost > points_now:
                skipped.append({
                    "skill_id": skill_id,
                    "reason": "unaffordable_after_previous_buys",
                    "cost": cost,
                    "skill_point": points_now,
                })
                continue
            single_payload = [{"skill_id": skill_id, "level": 1}]
            buy_ok = False
            last_exc = None
            try:
                if hasattr(client, "wait_complex_delay"):
                    client.wait_complex_delay()
                result = client.gain_skills(single_payload, turn, retry_205=1, retry_208=1)
                self._remember_bought([item])
                if isinstance(result, dict) and result.get("data"):
                    current = self.enrich_state_with_known_bought(result)
                    result_chara = (result.get("data") or {}).get("chara_info") or {}
                    estimated_points = max(0, points_now - cost)
                    returned_points = int(result_chara.get("skill_point") or 0)
                    local_points = min(returned_points, estimated_points) if returned_points else estimated_points
                    if result_chara:
                        result_chara["skill_point"] = local_points
                else:
                    local_points = max(0, points_now - cost)
                bought += 1
                accepted.append(skill_id)
                buy_ok = True
            except Exception as single_exc:
                last_exc = single_exc
            if buy_ok:
                continue
            print(f"Per-skill retry rejected {skill_id} at turn {turn}: {last_exc}")
            rejected.append(skill_id)
            rejected_details.append({
                "skill_id": skill_id,
                "group_id": group_id,
                "name": item.get("name") or self.skill_names.get(skill_id, ""),
                "cost": cost,
                "skill_point": points_now,
                "payload": list(single_payload),
                "error": str(last_exc) if last_exc is not None else "",
                "error_codes": extract_error_codes(str(last_exc) if last_exc is not None else ""),
                "error_details": exception_details(last_exc) if last_exc is not None else {},
            })
            failed = self._failed_for_turn(turn)
            failed.add(skill_id)
            failed.add(failed_group_key(group_id))
            # If the server kept 205'ing this skill after 3 outer attempts ×
            # 2 client-level retries (= 9 tries), it's not a transient sync
            # error — the server actually rejects this skill (tip-list desync,
            # already-owned, prereq-fail, etc.). Park it in the career-scoped
            # permanent set so the SP-drain retry picks DIFFERENT candidates
            # instead of hammering the same dead skill on every retry pass.
            if last_exc is not None and "205" in str(last_exc):
                self.permanent_failed_skills.add(int(skill_id))
                print(f"Skill {skill_id} disabled for this career after persistent 205")
                if points_now >= cost + 150:
                    self._record_cross_career_failure(int(skill_id))
        self.last_per_skill_rejections = rejected_details
        return self.enrich_state_with_known_bought(current), bought, accepted, rejected, skipped


    def _select_skill_id(self, group_id, priority, owned, rarity=0):
        owned = {int(sid or 0) for sid in owned or []} | set(self.known_bought_skill_ids)
        owned_groups = {self._skill_group_id(sid) for sid in owned} | set(self.known_bought_group_ids)
        resolved = self.resolve_skill_tip({"group_id": group_id, "rarity": rarity, "level": 0}, owned, owned_groups, priority, set(), {})
        return int((resolved or {}).get("resolved_skill_id") or 0)

    def _estimate_cost(self, candidate):
        name = candidate.get("name") or ""
        skill_id = candidate.get("skill_id") or 0
        try:
            skill_id_int = int(skill_id or 0)
        except (TypeError, ValueError):
            skill_id_int = 0

        record = self.skill_activation_data.get(skill_id_int) if skill_id_int else None
        if isinstance(record, dict):
            try:
                cost = int(record.get("cost") or 0)
            except (TypeError, ValueError):
                cost = 0
            if cost > 0:
                return cost
        
        is_circle = any(m in name for m in [
            MARK_WHITE_CIRCLE, MARK_LARGE_CIRCLE,
            UNICODE_WHITE_CIRCLE, UNICODE_LARGE_CIRCLE,
            MOJI_WHITE_CIRCLE, MOJI_LARGE_CIRCLE,
        ])
        
        if is_circle:
            base = 130
        elif skill_id_int >= 900000:
            base = 200
        elif skill_id_int % 10 >= 2:
            base = 200
        else:
            base = 160
        # `skill_tips_array.level` is not a reliable SP discount in the live
        # API. Using it here made the bot submit unaffordable payloads such as
        # Corner Adept at 91 SP while the server still required the full 180.
        # Unknown skills should therefore fail closed with the full fallback
        # estimate instead of underbidding and triggering repeated 205s.
        return max(1, int(base))
