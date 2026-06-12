from career_bot.career_trajectory_prediction import predict_trajectory
from career_bot.deck_quality import compute_deck_quality_bucket
from career_bot.event_choice_learning import pick_learned_choice
from career_bot.events import EventManager
from career_bot.imitation import (
    select_prior as imitation_select_prior,
    prior_action_for_turn as imitation_prior_action,
)
from career_bot.projection import (
    build_projection as _build_projection,
    tile_bonus_from_projection as _tile_bonus_from_projection,
    projection_enabled as _projection_enabled,
    projection_phase as _projection_phase,
)
from career_bot.postmortem_feedback import upcoming_race_stat_demand
from career_bot.presets import resolve_expect_attribute
from career_bot.race_success_feedback import upcoming_race_success_demand
from career_bot.race_thresholds import (
    aggregate_stat_deficit,
    compute_race_deficits,
    load_race_thresholds,
)
from career_bot.manual_race_data import (
    STAMINA_RECOVERY_UNIQUE_CARDS,
    aggregate_race_specific_targets,
    aggregate_user_targets_by_attributes,
    aggregate_user_targets_for_trainee,
    load_manual_race_data,
)
from career_bot.scenarios.base import Decision, ScenarioStrategy
from career_bot.scenarios.mant_stamina import (
    STAMINA_RECOVERY_SKILL_NAMES,
    normalize_skill_name,
    stamina_demand_multiplier,
)
from career_bot.spark_rates import stat_value_band
from career_bot.training_policy import score_training_policy_bonus


def _tuned_value(preset, param_name, fallback):
    """Read `learned_hyperparameters[param_name]` from the preset if the
    hyperparameter tuner has set it; otherwise return `fallback` (the
    module-level default). This lets the auto-tuner (see
    `career_bot/hyperparameter_tuner.py`) adjust scoring magnitudes per
    operator/deck without me hand-editing constants."""
    def _bounded(value):
        try:
            from career_bot.hyperparameter_tuner import TUNABLE_PARAMS
            cfg = TUNABLE_PARAMS.get(param_name)
        except Exception:
            cfg = None
        if not cfg:
            return value
        try:
            numeric = float(value)
            floor = float(cfg.get("floor"))
            ceiling = float(cfg.get("ceiling"))
        except (TypeError, ValueError):
            return value
        numeric = max(floor, min(ceiling, numeric))
        if isinstance(cfg.get("default"), int):
            return int(round(numeric))
        return numeric

    if isinstance(preset, dict):
        learned = preset.get("learned_hyperparameters")
        if isinstance(learned, dict) and param_name in learned:
            try:
                return type(fallback)(_bounded(learned[param_name]))
            except (TypeError, ValueError):
                return fallback
    return fallback


# Index → stat name used by upcoming_race_stat_demand lookups. Matches
# the TRAINING_COMMANDS mapping below: 0=Speed, 1=Stamina, etc.
_COMMAND_IDX_TO_STAT = {0: "speed", 1: "stamina", 2: "power", 3: "guts", 4: "wit"}
# Cap on the postmortem-derived training bonus. Bumped from 0.10 to
# 0.20 to make stat-gap feedback from past losses bite harder — the
# bot was diagnosing "lost Tenno Sho Spring by 216 stamina" but the
# 0.10 cap couldn't outweigh the learned policy or other scoring.
_POSTMORTEM_BONUS_CAP = 0.20
# Demand divisor lowered so smaller gaps still fire meaningful pressure.
_POSTMORTEM_DEMAND_FULL_BONUS_AT = 180.0  # was 250
_RACE_SUCCESS_BONUS_CAP = 0.12  # was 0.08
_RACE_SUCCESS_DEMAND_FULL_BONUS_AT = 180.0  # was 220
_TRAJECTORY_BONUS_CAP = 0.18
_TRAJECTORY_DEMAND_FULL_BONUS_AT = 140.0
# Hard race-threshold deficit bonus. Bigger cap than the soft postmortem
# hint because this is the "no more losses" rail — when projected stats
# fall short of a required-race threshold, the bot needs to *meaningfully*
# bias toward closing the gap, not just nudge. 200pt deficit on a stat
# (after time-weighting) produces the full cap bonus.
_THRESHOLD_DEFICIT_BONUS_CAP = 0.32
_THRESHOLD_DEFICIT_FULL_BONUS_AT = 200.0
_THRESHOLD_DEFICIT_LOOKAHEAD_TURNS = 20
_SCHEDULED_RACE_SAFETY_BONUS_CAP = 1.35
_SCHEDULED_RACE_SAFETY_CRITICAL_BONUS_CAP = 1.75
_SCHEDULED_RACE_SAFETY_LOOKAHEAD_TURNS = 24
_SCHEDULED_RACE_SAFETY_FULL_DEFICIT_RATIO = 0.22
_SCHEDULED_RACE_PROJECTED_GAIN_PER_TURN = {
    "speed": 9.0,
    "stamina": 4.5,
    "power": 8.5,
    "guts": 5.5,
    "wit": 6.5,
}
# Cap-pursuit bonus. Fires ONLY for stats the user has explicitly
# listed in `desired_parent_sparks.blue` — these are the stats the user
# wants to spark as a parent. Target is 1100 (the ★★ blue-spark
# threshold). When no blue spark is set, cap-pursuit returns 0 and the
# bot follows the deck's natural flow via partner-count scoring.
#
# Per user feedback: no predestined stat targets. If the deck has no
# Wit cards, the bot shouldn't max Wit. If the user wants a Power
# spark, they say so explicitly via desired_parent_sparks.blue, and
# THEN cap-pursuit guarantees Power >= 1100 by career end.
#
# Late-career escalation: bonus magnitude grows in the final third of
# the career to ensure the target is actually hit by turn 78. Early
# career it's a gentle nudge; late career it's a hammer.
_CAP_PURSUIT_TARGET_VALUE = 1100.0
_FREE_STATS_BUDGET_PER_STAT = 150.0
_CAP_PURSUIT_BONUS_CAP_EARLY = 0.20
_CAP_PURSUIT_BONUS_CAP_LATE = 0.45
# Stat ratio below this triggers full bonus (e.g., 0.65 = stat at 65%
# of target). Above this the bonus scales down linearly to 0 at ratio 1.0.
_CAP_PURSUIT_FULL_BONUS_RATIO = 0.65
# Phase cutoff: don't apply cap-pursuit before turn 12 — junior year is
# the energy/bond-building phase and the bot needs to actually train
# partners to high bond before stat-cramming makes sense.
_CAP_PURSUIT_START_TURN = 12
# User-manual-data bonus: when the user has 3+ winning manual races for
# the current trainee in `manual_race_data.json`, derive cap-pursuit
# targets from the median winning stats across those races. This is
# stronger evidence than the `desired_parent_sparks.blue` hint because
# the user actually played AND won with those stats. Applies regardless
# of the blue-spark setting.
_USER_MANUAL_BONUS_CAP = 0.35
_USER_MANUAL_MIN_WINS = 3
_USER_MANUAL_FULL_BONUS_RATIO = 0.70  # bonus at full when stat is at/below 70% of user's median winning value

# Per-race demand bonus: applies pressure on training toward stats the user
# historically had when WINNING the upcoming scheduled race. Differs from
# `_user_manual_target_bonus` (which collapses across all of a trainee's
# races) by preserving the per-race signal — Kikuka Sho's stamina demand
# isn't diluted by Mile race stat profiles.
_RACE_SPECIFIC_DEMAND_BONUS_CAP = 0.45  # was 0.30 — pushes harder toward user's race-winning stats
_RACE_SPECIFIC_DEMAND_LOOKAHEAD_TURNS = 14  # was 12 — fire earlier
_RACE_SPECIFIC_DEMAND_FULL_BONUS_RATIO = 0.70  # was 0.65 — full bonus kicks in slightly higher
_RACE_SPECIFIC_DEMAND_MIN_WINS = 2  # need at least 2 user wins for cross-trainee aggregation

# Hard floor: races where the bot MUST hit a minimum stat by race time
# to have any chance of winning. Stronger than the soft demand bonus —
# bypasses deck-realism throttle and ramps when the projection falls
# short.
#
# `program_id -> {stat_name: minimum_value}`. Empty by default. Route safety
# is handled by scheduled-race pressure plus target-aware shop buys; forcing
# hard floors globally caused this Speed/Wit deck to waste turns on low-output
# off-deck training and reduced cap consistency.
_RACE_HARD_STAT_FLOORS = {
    # Keep these narrow. Broad multi-stat hard floors force Speed/Wit decks
    # into low-output off-deck training and made the sim/live gap worse. Race
    # safety for the full calendar is handled by scheduled-race pressure plus
    # pre-race skill buys; only the long-distance stamina traps need hard floors.
    # Recent live xguri/sussy careers were still losing Kikuka at ~295-360
    # stamina and Tenno Spring at ~380-530 stamina. These floors are below a
    # stamina-card build's ideal, but high enough that this Speed/Wit deck
    # must build a safety margin before the long-race traps.
    629: {"speed": 285, "power": 255},                # Niigata Junior Stakes, Junior Late Aug
    625: {"speed": 330, "stamina": 190, "power": 310}, # Hopeful Stakes, Junior Late Dec
    168: {"stamina": 500, "power": 540},              # Kikuka Sho, Classic Late Oct
    4: {"stamina": 660, "power": 650},                # Tenno Sho (Spring), Senior Late Apr
}
_RACE_HARD_FLOOR_BONUS_CAP = 1.05     # significantly above other bonuses
_RACE_HARD_FLOOR_LOOKAHEAD_TURNS = 28  # long-race stamina must build before the race cluster
# Projection assumption: average stamina gain per stamina training in a
# stamina-card-less deck is ~6-8 raw points; with 1+ stamina card or
# rainbows it climbs to 12-18. We use a conservative 8 to under-project
# and over-fire the bonus — false-positive is "trains stamina too
# eagerly", false-negative is "enters Kikuka Sho at 200 stamina".
_RACE_HARD_FLOOR_PROJECTED_GAIN_PER_TURN = 4.5
# Fraction of remaining turns we expect to be stamina training when the
# bonus is firing. If we're already pushing stamina hard, expect ~60%.
_RACE_HARD_FLOOR_TRAINING_FRACTION = 0.45

# Turn at which the bonus reaches its late-career magnitude. Linear
# interpolation between START_TURN and LATE_CAREER_TURN.
_CAP_PURSUIT_LATE_CAREER_TURN = 60

# Pre-rainbow band: partners at bond in this range are one or two
# trainings away from crossing 80 (the rainbow threshold). Per-partner
# bonus and overall cap are tuned to nudge training picks without
# overpowering the existing scoring's clear winners.
_NEAR_RAINBOW_BOND_MIN = 60
_NEAR_RAINBOW_BOND_MAX = 80
_NEAR_RAINBOW_BONUS_PER_PARTNER = 0.04
_NEAR_RAINBOW_BONUS_CAP = 0.12
# Phase falloff: once past the senior year (turn > 60), the rainbow
# investment window is mostly closed and we shouldn't push the bot to
# bond-train at the expense of stat-pushing.
_NEAR_RAINBOW_LATE_PHASE_TURN = 60
_NEAR_RAINBOW_LATE_PHASE_SCALE = 0.35
_FIRST_SUMMER_FRIENDSHIP_TARGET_TURN = 35
_FIRST_SUMMER_FRIENDSHIP_TARGETS = (
    (12, 1),
    (24, 2),
    (35, 4),
)
_FIRST_SUMMER_FRIENDSHIP_BONUS_20_39 = 0.035
_FIRST_SUMMER_FRIENDSHIP_BONUS_40_59 = 0.065
_FIRST_SUMMER_FRIENDSHIP_BONUS_60_79 = 0.10
_FIRST_SUMMER_FRIENDSHIP_URGENCY_PER_DEFICIT = 0.75
_FIRST_SUMMER_FRIENDSHIP_BONUS_CAP = 0.45
_FIRST_SUMMER_FRIENDSHIP_REST_THRESHOLD_PENALTY_PER_GAP = 10
_FIRST_SUMMER_FRIENDSHIP_EARLY_REST_THRESHOLD_PENALTY = 6
_FIRST_SUMMER_FRIENDSHIP_MIN_PUSH_VITAL = 18
_FIRST_SUMMER_FRIENDSHIP_MAX_PUSH_FAILURE = 16
_FIRST_SUMMER_FRIENDSHIP_MIN_PUSH_SCORE = 0.06
_FIRST_SUMMER_FRIENDSHIP_RECREATION_MAX_TRAINING_SCORE = 0.06
_FIRST_SUMMER_FRIENDSHIP_RECREATION_MAX_VITAL = 35

# Support cards whose recreation/outing events grant a meaningful stat bonus
# (per `support_card_bonuses.json` and observed event data). These can appear
# in the deck or friend slot; the runtime gate below still requires the game to
# expose the actual outing as available, so card presence alone does not cause
# recreation spam.
_STAT_RECREATION_FRIEND_CARDS = {
    30021,  # Tazuna Hayakawa → speed
    30036,  # Riko Kashimoto  → stamina
    30052,  # Light Hello     → guts + speed
    30160,  # Mei Satake      → power
    30257,  # Tucker Bryne    → stamina
    30276,  # Kiyoko Hoshina  → guts
}
_STAT_RECREATION_SCORE_CAP_BONUS = 0.10
_STAT_RECREATION_TARGET_BOND = 60
_RIKO_KASHIMOTO_EVENT_PREFIXES = ("809006", "830036")
# Per-card outing chain length (verified from data/event_id_index.json:
# `support_card_events[<card_id>][n].chain_max`). Cards whose chain data
# isn't in the local dataset default to 5 (matching the sim's
# FRIEND_RECREATION_DEFAULT_MAX_USES). Riko is the verified anchor.
_STAT_RECREATION_OUTING_MAX = {
    30021: 5,  # Tazuna - default until verified
    30036: 5,  # Riko Kashimoto - VERIFIED chain_max=5 (5 outings: chain_num 1-5)
    30052: 5,  # Light Hello - default
    30160: 5,  # Mei Satake - default
    30257: 5,  # Tucker Bryne - default
    30276: 5,  # Kiyoko Hoshina - default
}
_STAT_RECREATION_OUTING_MAX_DEFAULT = 5
_STAT_RECREATION_CARD_NAMES = {
    30021: "Tazuna",
    30036: "Riko",
    30052: "Light Hello",
    30160: "Mei Satake",
    30257: "Tucker Bryne",
    30276: "Kiyoko Hoshina",
}
# Recreation is wasted at high HP — the energy/mood recovery and the
# event reward are both clamped by the trainee's current state. Cap the
# action at HP <= 80 regardless of which friend is slotted.
_RECREATION_VITAL_CEILING = 80
_FACILITY_LEVELUP_BASE_BONUS = 0.16        # Was 0.08 — concentrate XP harder
_FACILITY_LEVELUP_EARLY_MULTIPLIER = 2.5   # Was 1.8 — push facility-leveling much harder in Junior
_FACILITY_LEVELUP_LATE_MULTIPLIER = 0.3
_FACILITY_LEVELUP_LEVEL_4_TO_5_BONUS = 0.08  # Was 0.04 — lv5 base gain is 2× lv3; reward reaching it
_FACILITY_PROGRESS_NEAR_LEVELUP_BONUS = 0.04 # Was 0.02 — also reward "2 away from levelup"
# Bonus per facility level already reached on this tile — push the bot
# to concentrate training on the SAME facility instead of spreading thin
# (manual play: 33 wit trainings = lv5 wit facility; bot: 5 wit = lv2)
_FACILITY_HIGH_LEVEL_REINFORCEMENT = 0.04   # Per level above 1, capped at lv4 -> +0.12
_FACILITY_LEVEL_TRAINING_BONUS_CAP = 0.28
# Bootstrap pressure for facilities still at lv 1-2. Fires for deck-
# supported stats (and Wit, by operator policy) so the underused
# facilities reach lv3 before summer camp. Without this, Wit facility
# was stuck at lv2 through Senior summer in the S+ 16,116 career while
# Speed climbed to lv4.
_FACILITY_BOOTSTRAP_BONUS = 0.20            # Strong pull until facility >= 3
_FACILITY_BOOTSTRAP_END_TURN = 56           # Stop trying to level after this
_LAGGING_BOND_PARTNER_THRESHOLD = 70        # Below this, partner counts as lagging
_LAGGING_BOND_BONUS_CAP = 0.15              # Max bonus for picking the lagging partner's tile
_LAGGING_BOND_LATE_TURN = 60                # Stop firing after Senior — too late to invest
_BOND_EQUITY_GATE_END_TURN = 42         # Was 36; extend so the gate can finish the job
_BOND_EQUITY_MAX_AVG_GAP = 15           # (legacy relative-gap, kept as secondary signal)
_BOND_EQUITY_EMERGENCY_START_TURN = 33
_BOND_EQUITY_EMERGENCY_FLOOR = 70
_BOND_EQUITY_HIGH_VALUE_GAIN = 45.0     # A strong 2+ partner tile can beat bond catch-up.
_BOND_EQUITY_HIGH_VALUE_PARTNERS = 2
# Absolute bond-target ramp. By _BOND_EQUITY_TARGET_FULL_TURN every deck
# card should be at 80 bond (rainbow-ready). Cards more than TOLERANCE
# below the turn's target are force-prioritized. This replaces the old
# relative-gap detection that never fired on a uniformly low deck (real
# careers reached end-of-Junior with only 1/6 cards rainbow-ready).
_BOND_EQUITY_TARGET_FULL_TURN = 28      # Was 33 — push bonds to 80 earlier per audit
                                        # (manual rainbows online from turn 25;
                                        # bot was hitting them only from turn 40-50)
_BOND_EQUITY_TARGET_TOLERANCE = 6       # Was 8 — tighter grace band
_RACE_HEAVY_CORE_FLOORS = (
    (24, {"speed": 350, "stamina": 260, "power": 310, "guts": 170}),
    (36, {"speed": 520, "stamina": 390, "power": 480, "guts": 250}),
    (48, {"speed": 700, "stamina": 500, "power": 650, "guts": 330}),
    (60, {"speed": 880, "stamina": 620, "power": 820, "guts": 420}),
    (72, {"speed": 1050, "stamina": 700, "power": 980, "guts": 520}),
    (78, {"speed": 1120, "stamina": 760, "power": 1040, "guts": 580}),
)
_RACE_HEAVY_EFFICIENCY_START_TURN = 25

# Do not let target closeout over-push Wit while race-critical stats are far
# behind. Recent A+ collapses were high-Wit/low-Speed or low-Stamina profiles
# that then lost the same long G1s repeatedly.
_WIT_CLOSEOUT_CRITICAL_SPEED_FLOOR = 1000.0
_WIT_CLOSEOUT_CRITICAL_STAMINA_FLOOR = 620.0
_WIT_CLOSEOUT_CRITICAL_POWER_FLOOR = 820.0
_WIT_CLOSEOUT_DAMPING_WHEN_CORE_BEHIND = 0.28
_WIT_CLOSEOUT_DAMPING_WHEN_SPEED_BEHIND = 0.45
_WIT_CLOSEOUT_DAMPING_MIN_WIT = 1000.0
_WIT_CLOSEOUT_DAMPING_LEAD_OVER_SPEED = 80.0

# Ordinary recreation is not normally worth a training turn on race-heavy
# MANT, but mood 1-2 is run-poisoning. Let it beat mediocre training instead
# of resting at terrible mood.
_CRITICAL_MOOD_RECREATION_THRESHOLD = 2
_CRITICAL_MOOD_RECREATION_SCORE_CAP = 1.15
_CRITICAL_MOOD_RECREATION_VITAL_CEILING = 90
_RACE_HEAVY_LANE_BALANCE_START_TURN = 18
_RACE_HEAVY_LANE_BALANCE_MAX_BONUS = 0.42
_RACE_HEAVY_LANE_BALANCE_GAP = 90.0
_RACE_HEAVY_POWER_SUPPORT_GAP = 140.0
_RACE_HEAVY_PRIORITY_LEAD_DAMP_GAP = 120.0
_RACE_HEAVY_PRIORITY_LEAD_DAMP_MULTIPLIER = 0.58


# ============================================================
# Stat Priority Architecture
# Speed is always wanted. Per-stat checkpoint pressure ensures
# the bot stays on year-pace for each stat.
# ============================================================

# --- Speed Always ---
_SPEED_PRIORITY_ENABLED = True
_SPEED_PRIORITY_BONUS_EARLY = 0.06      # Junior bonus
_SPEED_PRIORITY_BONUS_MID = 0.16        # Classic — strong
_SPEED_PRIORITY_BONUS_LATE = 0.22       # Senior — STRONGEST (was 0.12)
# Rationale: variance analysis of 41 recent careers showed Senior speed
# is the dominant gap between top-quartile and bottom-quartile careers
# (+188 speed delta vs +12 stamina at T24). Bottom-quartile careers
# under-train speed in Senior, fall behind the race field, lose Senior
# G1s, forfeit epithet stats. Bumping LATE > MID makes the bot push
# speed harder in T48-T78 specifically.
_SPEED_PRIORITY_FLOOR_RAW = 1100.0      # Was 1000 — full bonus persists higher
_SPEED_PRIORITY_TARGET_RAW = 1200.0     # At this raw Speed: bonus decays to 0.1x
_SPEED_PRIORITY_DEFICIT_BOOST = 0.15    # Was 0.10 — stronger boost when below race-floor
_SPEED_PRIORITY_RACE_DEFICIT_THRESHOLD = 950.0  # Was 900 — fires earlier

# --- Wit Priority ---
# A 2-Wit deck with top-tier Wisdom cards should actually push Wit toward
# cap. Previously Wit only got generic checkpoint/concentration bonuses while
# Speed had a dedicated priority lane, so Nature/Fine decks still finished
# around 850-950 Wit on race-heavy routes.
_WIT_PRIORITY_ENABLED = True
_WIT_PRIORITY_MIN_DECK_CARDS = 2
_WIT_PRIORITY_BONUS_EARLY = 0.04
_WIT_PRIORITY_BONUS_MID = 0.14
_WIT_PRIORITY_BONUS_LATE = 0.30
_WIT_PRIORITY_FLOOR_RAW = 1050.0
_WIT_PRIORITY_TARGET_RAW = 1200.0

# --- Stamina + Power floors ---
# Until raw stamina/power clear these floors, speed-priority bonuses get
# scaled down so the bot doesn't over-invest in speed at the expense of
# the stats that decide medium/long races (Kikuka, Derby, Tenno Sho).
# Discovered diagnosing why sim/real both produced 460 stamina / 617
# power profiles that auto-lose 3000m+ races regardless of speed.
_STAMINA_FLOOR_TARGET = 650.0
_POWER_FLOOR_TARGET = 800.0
_SPEED_PRIORITY_DEFICIT_SCALE = 0.65    # Speed × 0.65 when both stamina and power are below floor
_STAMINA_PRIORITY_BONUS_BASE = 0.08     # Small additive bonus, only when below floor
_STAMINA_PRIORITY_DEFICIT_BOOST = 0.12
_POWER_PRIORITY_BONUS_BASE = 0.07
_POWER_PRIORITY_DEFICIT_BOOST = 0.10

# --- Checkpoint Pressure ---
_CHECKPOINT_PRESSURE_ENABLED = True

# End-of-year baseline targets (operator-supplied empirical values).
# Order: [Speed, Stamina, Power, Guts, Wit]
_CHECKPOINT_TARGETS_END_JUNIOR = [360, 240, 380, 200, 360]
_CHECKPOINT_TARGETS_END_CLASSIC = [680, 540, 700, 360, 700]
_CHECKPOINT_TARGETS_END_SENIOR = [1050, 720, 950, 500, 1050]

# Career year boundaries
_CHECKPOINT_TURN_END_JUNIOR = 24
_CHECKPOINT_TURN_END_CLASSIC = 48
_CHECKPOINT_TURN_END_SENIOR = 78

# Starting stats baseline (approximate value at turn 1)
_CHECKPOINT_STARTING_STATS = [100, 80, 80, 80, 100]

# Deck composition multiplier table. Targets scale by card count on each stat.
# Index = card count (0-5+), value = multiplier on the baseline target.
# Rationale: 1 card enables some rainbows, 2 cards enables consistent rainbows,
# 3+ cards enables rainbow-on-demand, allowing significantly higher endpoints.
_CHECKPOINT_DECK_CARD_SCALE = [1.00, 1.08, 1.15, 1.22, 1.30, 1.38]

# Bonus magnitudes
_CHECKPOINT_PRESSURE_BASE = 0.10            # base bonus when behind pace
_CHECKPOINT_PRESSURE_BEHIND_BOOST = 0.06    # additional bonus when significantly behind
_CHECKPOINT_PRESSURE_CRITICAL_DEFICIT = 0.25  # deficit ratio threshold for critical boost
_CHECKPOINT_PRESSURE_MAX_BONUS = 0.20       # cap so multi-stat trainings don't dominate
_CHECKPOINT_TYPICAL_GAIN = 12.0             # typical training gain (used for gain-weight scaling)

# Stat Concentration: push each stat toward its per-stat soft cap
# (1100 for speed/power/wit, 800 for stamina/guts) without overshooting.
# Operator policy: "stat capped or slightly below cap, not overcapped."
# Fires from T48 (Senior). The bonus is anchored as a fraction of the
# soft cap so it works correctly across per-stat overrides and the
# `desired_parent_sparks.blue` bump.
_STAT_CONCENTRATION_START_TURN = 42
_STAT_CONCENTRATION_RAMP_START = 0.50  # ratio current/soft_cap below which no push
_STAT_CONCENTRATION_PEAK_START = 0.95  # ratio at which peak bonus is reached
_STAT_CONCENTRATION_PEAK_BONUS = 0.34  # peak magnitude near the soft cap

# Visible-tile quality guard. The policy score can correctly prefer bond/race
# setup over immediate gain, but live audits showed it was skipping clearly
# stronger rainbow/high-output tiles too often. This bounded pass reinforces
# obvious board quality without disabling race hard-floor pressure.
_VISIBLE_TILE_CLEAR_GAP = 7.0
_VISIBLE_TILE_BONUS_CAP = 0.28
_VISIBLE_TILE_PENALTY_CAP = 0.34
_VISIBLE_TILE_PENALTY_SCALE = 0.024
_VISIBLE_TILE_RAINBOW_BONUS = 0.12
_VISIBLE_TILE_MISSED_RAINBOW_PENALTY = 0.10
_VISIBLE_TILE_RACE_PRESSURE_PROTECTION = 0.60


STAT_TARGETS = {
    1: 0,
    2: 1,
    3: 2,
    4: 3,
    5: 4,
    30: 5,
}

TRAINING_COMMANDS = {101: 0, 105: 1, 102: 2, 103: 3, 106: 4, 601: 0, 602: 1, 603: 2, 604: 3, 605: 4}
TRAINING_NAMES = ["Speed", "Stamina", "Power", "Guts", "Wit"]
SUMMER_CAMP_TURNS = {36, 37, 38, 39, 40, 60, 61, 62, 63, 64}
SUMMER_CONSERVE_TURNS = {35, 36, 59, 60}
SUMMER_CONSERVE_ENERGY = 60
ENERGY_FAST_MEDIC = 80
ENERGY_MEDIC_GENERAL = 85
DECK_PARTNERS = {1, 2, 3, 4, 5, 6}
BAD_EFFECT_NAMES = {
    1: "Night Owl",
    2: "Slacker",
    3: "Skin Outbreak",
    4: "Slow Metabolism",
    5: "Migraine",
    6: "Practice Poor",
}

BLUE_SPARK_STAT_ALIASES = {
    "speed": 0,
    "stamina": 1,
    "power": 2,
    "guts": 3,
    "wit": 4,
    "wisdom": 4,
    "wiz": 4,
    "intelligence": 4,
}


class MantStrategy(ScenarioStrategy):
    scenario_id = 4

    def __init__(self, race_planner=None):
        self.race_planner = race_planner
        self.event_manager = None
        self._stat_recreation_payloads = {}
        self._stat_recreation_payloads_mtime = None
        self._stat_recreation_payloads_path = None
        # Cached on each `next_decision` so `choose_from_event` can
        # consult the learned `event_choice_stats` map without needing
        # a preset argument plumbed through the runner.
        self.preset = None
        # Per-turn cache for race threshold deficits. Avoids reading the
        # thresholds file + reprojecting stats for every one of the ~10
        # training-command scores fired in a single decision tick. Keyed
        # by current_turn so a new turn invalidates.
        self._threshold_deficit_cache_turn = None
        self._threshold_deficit_cache_pressure = {}
        self._threshold_deficit_cache_per_race = []
        if self.race_planner and self.race_planner.base_dir:
            self.event_manager = EventManager(self.race_planner.base_dir)

    def next_decision(self, state, preset):
        # Cache the active preset so `choose_from_event` (which the
        # runner calls without a preset argument) can read learned
        # event_choice_stats off it. `next_decision` is always the
        # first strategy method touched on each tick so this is a
        # safe place to refresh.
        self.preset = preset
        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        home = data.get("home_info") or {}
        try:
            chara_state = int(chara.get("state") or 0)
        except (TypeError, ValueError):
            chara_state = 0
        try:
            current_turn = int(chara.get("turn") or 0)
        except (TypeError, ValueError):
            current_turn = 0
        try:
            finish_min_turn = int((preset or {}).get("complete_career_min_turn") or 70)
        except (TypeError, ValueError):
            finish_min_turn = 70
        late_enough_to_finish = current_turn >= finish_min_turn
        if "single_mode_finish_common" in data:
            return Decision("finish", {"current_turn": chara.get("turn", 78)}, "finished")
        if (
            (chara.get("playing_state") or 0) == 5
            and chara_state == 3
            and late_enough_to_finish
            and not data.get("race_start_info")
            and not int(chara.get("race_program_id") or 0)
        ):
            return Decision("finish", {"current_turn": chara.get("turn", 78)}, "Complete Career screen")
        events = data.get("unchecked_event_array") or []
        if events:
            event = events[0] or {}
            choice = self._choice(event)
            payload = {
                "event_id": event.get("event_id"),
                "chara_id": event.get("chara_id", 0),
                "choice_number": choice,
                "current_turn": chara.get("turn", 1),
                "_event": event,
                "_current_turn": chara.get("turn", 1),
            }
            if choice is None:
                payload = {"event_id": event.get("event_id"), "_event": event, "_current_turn": chara.get("turn", 1)}
            return Decision("event", payload, "event")
        race = data.get("race_start_info")
        playing_state = (chara.get("playing_state") or 0)
        actionable_home = self._has_actionable_home_commands(data)
        active_program_id = 0
        try:
            active_program_id = int((race or {}).get("program_id") or chara.get("race_program_id") or 0)
        except (TypeError, ValueError):
            active_program_id = 0
        if active_program_id or race:
            internal_state = 0
            try:
                internal_state = int(chara.get("state") or 0)
            except (TypeError, ValueError):
                internal_state = 0
            if playing_state in (2, 3) and internal_state != 0:
                detail = f"stale race metadata state {playing_state}/{internal_state}"
                return Decision(
                    "settle_state",
                    {"current_turn": chara.get("turn", 1)},
                    detail,
                    self._settle_state_understanding(chara, detail, "stale_race_metadata"),
                )
            payload = {"current_turn": chara.get("turn", 1), "race_start_info": race, "program_id": active_program_id, "chara_info": chara}
            if playing_state == 2:
                payload["phase"] = "start"
                return Decision("race_progress", payload, "resume race start")
            if playing_state == 3:
                payload["phase"] = "end"
                return Decision("race_progress", payload, "resume race end")
            if playing_state in (4, 5):
                payload["phase"] = "end"
                return Decision("race_progress", payload, "resume race result")
        if playing_state == 5 and not active_program_id and not race:
            if late_enough_to_finish and (chara_state == 3 or (chara_state == 2 and actionable_home)):
                return Decision("finish", {"current_turn": chara.get("turn", 78)}, "Complete Career screen")
            return Decision(
                "settle_state",
                {"current_turn": chara.get("turn", 1)},
                "post-action state without active race",
                self._settle_state_understanding(chara, "post-action state without active race", "post_action_no_race"),
            )
        if playing_state not in (0, 1):
            if not actionable_home:
                detail = f"non-home state {playing_state} without active race"
                return Decision(
                    "settle_state",
                    {"current_turn": chara.get("turn", 1)},
                    detail,
                    self._settle_state_understanding(chara, detail, "non_home_no_race"),
                )
        command = self._best_command(data, chara, preset)
        training_context = {}
        if self.race_planner:
            training_context = self._command_training_context(command, data, chara, preset)
            training_context["stat_lag_factor"] = self._stat_lag_factor(chara, preset)
            training_context["consecutive_race_count"] = self._consecutive_race_count(data, chara)
            training_context["is_climax_turn"] = self._is_climax_turn(chara)
        if self.race_planner:
            forced_program_id = self.race_planner.forced_program(state)
            if forced_program_id:
                payload = {"program_id": forced_program_id, "current_turn": chara.get("turn", 1), "_strategy": self}
                return Decision(
                    "race",
                    payload,
                    self.race_planner.label(forced_program_id),
                    self._race_decision_understanding(forced_program_id, chara, forced=True),
                )
            program_id = self.race_planner.choose(state, preset, training_context)
            if program_id:
                payload = {"program_id": program_id, "current_turn": chara.get("turn", 1), "_strategy": self}
                return Decision(
                    "race",
                    payload,
                    self.race_planner.label(program_id),
                    self._race_decision_understanding(program_id, chara, forced=False),
                )
        if self.race_planner:
            cmd_type = (command or {}).get("command_type")
            cmd_id = (command or {}).get("command_id")
            best_is_training = cmd_type == 1 and cmd_id in TRAINING_COMMANDS
            vital = int(chara.get("vital") or 0)
            rest_floor = int(preset.get("rest_threshold") or 48)
            current_turn = int(chara.get("turn") or 0)
            scheduled_entries = self.race_planner.scheduled_entries(preset)
            scheduled_this_turn = [
                entry for entry in scheduled_entries
                if int(entry.get("turn") or 0) == current_turn
            ]
            allow_optional_fillers = bool((preset or {}).get("calendar_optional_fillers_enabled", False))
            calendar_blocks_optional = bool(scheduled_this_turn) or (bool(scheduled_entries) and not allow_optional_fillers)
            if best_is_training and vital > rest_floor and not calendar_blocks_optional:
                program_id = self.race_planner.choose_optional(state, preset, training_context)
                if program_id:
                    payload = {"program_id": program_id, "current_turn": chara.get("turn", 1), "_strategy": self}
                    return Decision(
                        "race",
                        payload,
                        self.race_planner.label(program_id),
                        self._race_decision_understanding(program_id, chara, forced=False, optional=True),
                    )
        if command:
            command_type = command.get("command_type", 1)
            command_id = command.get("command_id")
            command_group_id = command.get("command_group_id", 0)
            select_id = command.get("select_id", 0)
            reason = self._command_reason(command, chara=chara, preset=preset)
            understanding = self._command_decision_understanding(command, data, chara, preset)
            exact_recreation_payload = command.get("_exec_command_payload")
            if command_type == 3:
                if isinstance(exact_recreation_payload, dict):
                    command_type = exact_recreation_payload.get("command_type", command_type)
                    command_id = exact_recreation_payload.get("command_id", command_id)
                    command_group_id = exact_recreation_payload.get("command_group_id", command_group_id)
                    select_id = exact_recreation_payload.get("select_id", select_id)
                else:
                    effective_command_id = self._effective_command_id(command)
                    command_group_id = effective_command_id
                    command_id = 0
            return Decision("command", {
                "command_type": command_type,
                "command_id": command_id,
                "command_group_id": command_group_id,
                "select_id": select_id,
                "current_turn": chara.get("turn", 1),
                "current_vital": chara.get("vital", 0),
            }, reason, understanding)
        return Decision("idle", {}, "no action")

    def _has_actionable_home_commands(self, data):
        commands = ((data or {}).get("home_info") or {}).get("command_info_array") or []
        for command in commands:
            enabled_value = command.get("is_enable")
            try:
                enabled = True if enabled_value is None else bool(int(enabled_value))
            except (TypeError, ValueError):
                enabled = bool(enabled_value)
            if enabled:
                return True
        return False

    def _command_training_context(self, command, data, chara, preset):
        context = {
            "score": 0.0,
            "stat_gain": 0.0,
            "skill_point_gain": 0.0,
            "energy_delta": 0.0,
            "rainbow_count": 0,
            "partner_count": 0,
            "hint_count": 0,
            "failure_rate": 0,
            "command_id": (command or {}).get("command_id"),
            "command_type": (command or {}).get("command_type"),
        }
        if not command or command.get("command_type") != 1 or command.get("command_id") not in TRAINING_COMMANDS:
            return context

        context["score"] = round(self._score_command(command, data, chara, preset), 4)
        context["failure_rate"] = int(command.get("failure_rate") or 0)
        bonds = self._bond_map(chara)
        partners = list(command.get("training_partner_array") or [])
        hints = set(command.get("tips_event_partner_array") or [])
        context["partner_count"] = len(partners)
        context["hint_count"] = len(hints)
        context["rainbow_count"] = sum(1 for partner_id in partners if partner_id in DECK_PARTNERS and bonds.get(partner_id, 0) >= 80)
        for item in command.get("params_inc_dec_info_array") or []:
            value = float(item.get("value") or 0)
            target_type = item.get("target_type")
            if target_type == 10:
                context["energy_delta"] += value
                continue
            target = STAT_TARGETS.get(target_type)
            if target is None:
                continue
            if target == 5:
                context["skill_point_gain"] += max(0.0, value)
            elif 0 <= target < 5:
                context["stat_gain"] += max(0.0, value)
        context["stat_gain"] = round(context["stat_gain"], 4)
        context["skill_point_gain"] = round(context["skill_point_gain"], 4)
        context["energy_delta"] = round(context["energy_delta"], 4)
        return context

    def _stat_lag_factor(self, chara, preset):
        targets = self._expect_attribute_targets(preset, chara, default=[9999, 9999, 9999, 9999, 9999])
        turn = max(1, int(chara.get("turn") or 1))
        pacing = min(1.0, turn / 78.0)
        primary = [0, 1, 2]
        min_ratio = 1.0
        # Per user "no predestined stats" feedback: when target is
        # unbounded (>= 9999), skip pacing pressure for that stat. If
        # ALL primary stats are unbounded the function returns the
        # neutral 1.0 — the deck flows naturally, no race-vs-train bias.
        for idx in primary:
            current = float(self._current_stat(chara, idx) or 0)
            target = float(targets[idx] if idx < len(targets) else 9999)
            if target >= 9999 or target <= 0:
                continue
            future_relief = self._future_stat_relief(idx, chara, preset)
            expected = max(1.0, (target * pacing) - future_relief)
            if expected <= 0:
                continue
            ratio = current / expected
            if ratio < min_ratio:
                min_ratio = ratio
        return max(0.45, min(1.10, min_ratio))

    def _consecutive_race_count(self, data, chara):
        history = (data or {}).get("race_history") or []
        if not history:
            return 0
        try:
            current_turn = int(chara.get("turn") or 0)
        except (TypeError, ValueError):
            current_turn = 0
        if current_turn <= 0:
            return 0
        turns_with_race = set()
        for row in history:
            try:
                row_turn = int(row.get("turn") or 0)
            except (TypeError, ValueError):
                continue
            if 0 < row_turn < current_turn:
                turns_with_race.add(row_turn)
        count = 0
        prev = current_turn - 1
        while prev > 0 and prev in turns_with_race:
            count += 1
            prev -= 1
        return count

    def _is_climax_turn(self, chara):
        try:
            turn = int(chara.get("turn") or 0)
        except (TypeError, ValueError):
            return False
        return turn >= 73

    def _scheduled_race_turns(self, preset):
        turns = set()
        for entry in (preset or {}).get("custom_race_schedule") or []:
            try:
                turn = int((entry or {}).get("turn") or 0)
            except (TypeError, ValueError):
                turn = 0
            if turn > 0:
                turns.add(turn)
        if self.race_planner:
            try:
                for entry in self.race_planner.scheduled_entries(preset) or []:
                    turn = int((entry or {}).get("turn") or 0)
                    if turn > 0:
                        turns.add(turn)
            except Exception:
                pass
        scenario_id = int((preset or {}).get("scenario_id") or (preset or {}).get("scenario") or 4)
        if scenario_id == 4:
            turns.update({74, 76, 78})
        return turns

    def _planned_race_count(self, preset):
        return len(self._scheduled_race_turns(preset))

    def _is_race_heavy_route(self, preset):
        min_races = int((preset or {}).get("race_heavy_route_min_races") or 32)
        return self._planned_race_count(preset) >= max(1, min_races)

    def _training_positive_stat_gain(self, command):
        total = 0.0
        for item in (command or {}).get("params_inc_dec_info_array") or []:
            target = STAT_TARGETS.get(item.get("target_type"))
            if target is None or target == 5:
                continue
            try:
                total += max(0.0, float(item.get("value") or 0.0))
            except (TypeError, ValueError):
                continue
        return total

    def _training_stat_gain_map(self, command):
        gains = {stat: 0.0 for stat in _COMMAND_IDX_TO_STAT.values()}
        for item in (command or {}).get("params_inc_dec_info_array") or []:
            target = STAT_TARGETS.get(item.get("target_type"))
            stat_name = _COMMAND_IDX_TO_STAT.get(target)
            if not stat_name:
                continue
            try:
                value = float(item.get("value") or 0.0)
            except (TypeError, ValueError):
                continue
            if value > 0:
                gains[stat_name] += value
        return {stat: value for stat, value in gains.items() if value > 0}

    def _deck_partner_count(self, command):
        return sum(1 for partner_id in (command or {}).get("training_partner_array") or [] if partner_id in DECK_PARTNERS)

    def _bond_equity_state(self, chara, preset, turn):
        if not bool((preset or {}).get("bond_equity_gate_enabled", True)):
            return {}
        try:
            current_turn = int(turn or 0)
        except (TypeError, ValueError):
            return {}
        end_turn = int((preset or {}).get("bond_equity_gate_end_turn") or _BOND_EQUITY_GATE_END_TURN)
        if current_turn <= 0 or current_turn > end_turn:
            return {}
        stat_recreation_partners = self._stat_recreation_partner_ids(preset)
        outing_ready = self._outing_ready_partner_ids(chara, preset)
        stat_recreation_target = self._stat_recreation_target_bond(preset)
        bonds = {}
        for partner_id, value in self._bond_map(chara).items():
            if partner_id not in DECK_PARTNERS:
                continue
            bond = int(value or 0)
            if (
                partner_id in stat_recreation_partners
                and (partner_id in outing_ready or bond >= stat_recreation_target)
            ):
                continue
            bonds[partner_id] = bond
        if not bonds:
            return {}
        avg_bond = sum(bonds.values()) / float(len(bonds))
        # Absolute target ramp: linearly approach 80 bond by the full-turn.
        # Any deck card more than TOLERANCE below this turn's target gets
        # force-prioritized. This fires even when the WHOLE deck is low
        # (the real failure mode), unlike the old relative-gap check.
        full_turn = int((preset or {}).get("bond_equity_target_full_turn") or _BOND_EQUITY_TARGET_FULL_TURN)
        tolerance = float((preset or {}).get("bond_equity_target_tolerance") or _BOND_EQUITY_TARGET_TOLERANCE)
        target_bond = min(80.0, 80.0 * (current_turn / float(max(1, full_turn))))
        lagging = {
            partner_id: bond
            for partner_id, bond in bonds.items()
            if bond < 80 and bond < (target_bond - tolerance)
        }
        # Retain the relative-gap signal as a secondary trigger (catches a
        # single card falling far behind an otherwise well-bonded deck).
        max_gap = float((preset or {}).get("bond_equity_max_avg_gap") or _BOND_EQUITY_MAX_AVG_GAP)
        for partner_id, bond in bonds.items():
            if bond < 80 and bond < (avg_bond - max_gap):
                lagging[partner_id] = bond
        emergency_start = int(
            (preset or {}).get("bond_equity_emergency_start_turn")
            or _BOND_EQUITY_EMERGENCY_START_TURN
        )
        emergency_floor = int(
            (preset or {}).get("bond_equity_emergency_floor")
            or _BOND_EQUITY_EMERGENCY_FLOOR
        )
        emergency = {}
        for partner_id, bond in bonds.items():
            floor = stat_recreation_target if partner_id in stat_recreation_partners else emergency_floor
            if current_turn >= emergency_start and bond < floor:
                emergency[partner_id] = bond
        target_ids = sorted(set(lagging) | set(emergency))
        if not target_ids:
            return {
                "active": False,
                "avg_bond": round(avg_bond, 2),
                "lagging_ids": [],
                "emergency_ids": [],
            }
        reason = "pre_summer_emergency" if emergency else "bond_ramp"
        return {
            "active": True,
            "reason": reason,
            "avg_bond": round(avg_bond, 2),
            "target_bond": round(target_bond, 1),
            "max_gap": max_gap,
            "emergency_floor": emergency_floor,
            "lagging_ids": sorted(lagging),
            "emergency_ids": sorted(emergency),
            "target_ids": target_ids,
            "target_bonds": {str(partner_id): bonds.get(partner_id, 0) for partner_id in target_ids},
        }

    def _apply_bond_equity_gate(self, scored, chara, preset, turn):
        state = self._bond_equity_state(chara, preset, turn)
        if not state.get("active"):
            return scored, state
        race_pressure = max(
            (
                float((command or {}).get("_scheduled_race_safety_bonus") or 0.0)
                + float((command or {}).get("_race_hard_floor_bonus") or 0.0)
                + float((command or {}).get("_threshold_deficit_bonus") or 0.0)
                + float((command or {}).get("_manual_race_specific_demand_bonus") or 0.0)
            )
            for _score, command in (scored or [])
        ) if scored else 0.0
        if race_pressure >= float((preset or {}).get("bond_equity_yield_race_pressure") or 0.24):
            return scored, {**state, "active": False, "override": "race_prep_pressure"}
        high_value_gain = float((preset or {}).get("bond_equity_high_value_gain") or _BOND_EQUITY_HIGH_VALUE_GAIN)
        high_value_partners = int(
            (preset or {}).get("bond_equity_high_value_partners")
            or _BOND_EQUITY_HIGH_VALUE_PARTNERS
        )
        for _score, command in scored or []:
            if self._training_positive_stat_gain(command) >= high_value_gain and self._deck_partner_count(command) >= high_value_partners:
                command["_bond_equity_gate"] = {
                    **state,
                    "active": False,
                    "override": "high_value_training",
                }
                return scored, {**state, "active": False, "override": "high_value_training"}
        targets = set(state.get("target_ids") or [])
        filtered = [
            (score, command)
            for score, command in scored or []
            if targets.intersection(command.get("training_partner_array") or [])
        ]
        if not filtered:
            return scored, {**state, "active": False, "override": "no_matching_training"}
        for _score, command in filtered:
            command["_bond_equity_gate"] = dict(state)
        return filtered, state

    def _imitation_archive_path(self, preset):
        ctx = (preset or {}).get("_run_context") or {}
        explicit = (preset or {}).get("imitation_archive_path")
        if explicit:
            return str(explicit)
        from pathlib import Path
        roots = (preset or {}).get("auto_learning_runtime_paths") or []
        if isinstance(roots, str):
            roots = [roots]
        for root in roots:
            if root:
                return str(Path(root) / "imitation" / "sweep_archive.json")
        # Fallback to the legacy instance path for safety
        base = ctx.get("instance_runtime_root") or "uma_runtime/instances/account_b"
        return str(Path(base) / "imitation" / "sweep_archive.json")

    def _load_imitation_prior(self, preset):
        """Lazy-load and cache the imitation prior for the current career."""
        if not bool((preset or {}).get("imitation_enabled", True)):
            return None
        # Cache key: the run_context fingerprint. Refresh if it changes.
        ctx = (preset or {}).get("_run_context") or {}
        cache_key = (
            int(ctx.get("trainee_card_id") or ctx.get("chara_id") or 0),
            int(ctx.get("friend_card_id") or 0),
            tuple(sorted(int(c or 0) for c in (ctx.get("support_card_ids") or [
                (c.get("id") or c.get("support_card_id") or 0)
                for c in (ctx.get("support_cards") or [])
            ]))),
        )
        cached = getattr(self, "_cached_imitation_key", None)
        if cached == cache_key and getattr(self, "_cached_imitation_prior", None) is not None:
            return self._cached_imitation_prior
        target_rc = {
            "trainee_card_id": cache_key[0],
            "friend_card_id": cache_key[1],
            "support_card_ids": list(cache_key[2]),
            "schedule_program_ids": sorted({
                int((e or {}).get("program_id") or 0)
                for e in (preset or {}).get("custom_race_schedule") or []
                if (e or {}).get("program_id")
            }),
        }
        archive_path = self._imitation_archive_path(preset)
        try:
            prior, match_score, detail = imitation_select_prior(archive_path, target_rc, min_match_score=100)
        except Exception:
            prior, match_score, detail = None, 0, {"reason": "archive_error"}
        self._cached_imitation_key = cache_key
        self._cached_imitation_prior = prior
        self._cached_imitation_match = {"score": match_score, "detail": detail}
        return prior

    def _apply_imitation_prior(self, scored, preset, turn):
        """Add a small score bonus to commands matching the imitation prior's choice.

        The bonus is intentionally small (0.06 default) so high-conviction
        decisions (rainbow tiles, race-prep urgency) still dominate, but
        ties get broken in favor of the proven sequence. Disabled when no
        prior is found or when imitation_enabled is false.
        """
        if not scored:
            return scored, {"active": False, "reason": "no_scored_commands"}
        prior = self._load_imitation_prior(preset)
        if not prior:
            return scored, {"active": False, "reason": "no_prior_matched"}
        action = imitation_prior_action(prior, turn)
        if not action:
            return scored, {"active": False, "reason": "no_prior_action_for_turn", "turn": int(turn or 0)}
        target_ct, target_cid = action
        # Only apply to training commands (command_type == 1) here. Rest/
        # recreation/race decisions go through other selectors.
        if int(target_ct) != 1:
            return scored, {"active": False, "reason": "prior_not_training", "prior_command_type": int(target_ct)}
        bonus = float(_tuned_value(preset, "imitation_prior_bonus", 0.06))
        if bonus <= 0:
            return scored, {"active": False, "reason": "bonus_zero"}
        boosted = []
        applied = False
        for score, command in scored:
            if int(command.get("command_id") or 0) == int(target_cid):
                boosted.append((score + bonus, command))
                command["_imitation_bonus_applied"] = round(bonus, 4)
                applied = True
            else:
                boosted.append((score, command))
        state = {
            "active": bool(applied),
            "prior_command_id": int(target_cid),
            "bonus": round(bonus, 4),
            "match_score": (self._cached_imitation_match or {}).get("score"),
        }
        return boosted, state

    def _race_heavy_core_floor_adjustment(self, idx, chara, preset, turn):
        if not self._is_race_heavy_route(preset):
            return 0.0
        if idx not in (0, 1, 2, 3, 4):
            return 0.0
        floors = {}
        for max_turn, row in _RACE_HEAVY_CORE_FLOORS:
            floors = row
            if int(turn or 0) <= max_turn:
                break
        if not floors:
            return 0.0
        current = {
            "speed": float(chara.get("speed") or 0.0),
            "stamina": float(chara.get("stamina") or 0.0),
            "power": float(chara.get("power") or 0.0),
            "guts": float(chara.get("guts") or 0.0),
        }
        deficit_ratio = {}
        for key, floor in floors.items():
            floor_value = float(floor or 0.0)
            if floor_value <= 0:
                deficit_ratio[key] = 0.0
                continue
            deficit_ratio[key] = max(0.0, (floor_value - current.get(key, 0.0)) / floor_value)
        missing_core = sum(1 for value in deficit_ratio.values() if value > 0.04)
        stat_name = _COMMAND_IDX_TO_STAT.get(idx, "")
        if stat_name in deficit_ratio:
            deficit = deficit_ratio.get(stat_name, 0.0)
            if deficit > 0.0:
                bonus = min(0.20, 0.04 + deficit * 0.34)
                if stat_name == "speed":
                    bonus = min(0.24, bonus + 0.02)
                elif stat_name == "power":
                    bonus = min(0.22, bonus + 0.015)
                return bonus
            return 0.0
        if stat_name == "wit" and missing_core >= 2:
            return -min(0.16, 0.04 + max(deficit_ratio.values()) * 0.18)
        if stat_name == "guts" and missing_core >= 2:
            return -min(0.12, 0.03 + max(deficit_ratio.values()) * 0.14)
        return 0.0

    def _race_heavy_training_efficiency_adjustment(self, command, chara, preset, turn):
        """Make scarce training turns count on 32+ race schedules.

        Race-heavy parent routes cannot afford many filler trainings. Once the
        first-summer setup window is reached, directly reward high-gain rainbow
        tiles and mildly penalize empty/low-gain tiles so the bot does not keep
        choosing safe but low-output turns while still respecting failure guards.
        """
        if not self._is_race_heavy_route(preset):
            return 0.0
        if int(turn or 0) < _RACE_HEAVY_EFFICIENCY_START_TURN:
            return 0.0
        if int(command.get("command_type") or 0) != 1:
            return 0.0
        bonds = self._bond_map(chara)
        partners = command.get("training_partner_array") or []
        deck_partner_count = sum(1 for partner_id in partners if partner_id in DECK_PARTNERS)
        rainbow_count = sum(1 for partner_id in partners if partner_id in DECK_PARTNERS and bonds.get(partner_id, 0) >= 80)
        total_gain = 0.0
        core_gain = 0.0
        for item in command.get("params_inc_dec_info_array") or []:
            target = STAT_TARGETS.get(item.get("target_type"))
            if target is None or target == 5:
                continue
            value = max(0.0, float(item.get("value") or 0.0))
            total_gain += value
            if target in (0, 1, 2):
                core_gain += value
        bonus = 0.0
        if rainbow_count >= 2:
            bonus += min(0.12, 0.035 * rainbow_count)
        if deck_partner_count >= 3:
            bonus += min(0.06, 0.012 * deck_partner_count)
        if total_gain >= 36:
            bonus += 0.04
        elif total_gain <= 18 and rainbow_count == 0 and deck_partner_count <= 1:
            bonus -= 0.08
        if core_gain >= 30:
            bonus += 0.04
        if core_gain <= 10 and int(turn or 0) >= 48 and rainbow_count <= 1:
            bonus -= 0.05
        return max(-0.12, min(0.22, bonus))

    def _training_skill_point_gain(self, command):
        total = 0.0
        for item in (command or {}).get("params_inc_dec_info_array") or []:
            if STAT_TARGETS.get(item.get("target_type")) != 5:
                continue
            try:
                total += max(0.0, float(item.get("value") or 0.0))
            except (TypeError, ValueError):
                continue
        return total

    def _visible_tile_quality(self, command):
        if not command:
            return 0.0
        partners = command.get("training_partner_array") or []
        bonds = getattr(self, "_last_quality_bonds", {}) or {}
        deck_partner_count = sum(1 for partner_id in partners if partner_id in DECK_PARTNERS)
        rainbow_count = sum(
            1
            for partner_id in partners
            if partner_id in DECK_PARTNERS and int(bonds.get(partner_id, 0) or 0) >= 80
        )
        hints = command.get("hint_tips_array") or command.get("tips_event_partner_array") or []
        hint_count = len(hints) if isinstance(hints, list) else 0
        return (
            self._training_positive_stat_gain(command)
            + self._training_skill_point_gain(command) * 0.65
            + deck_partner_count * 1.4
            + rainbow_count * 6.0
            + hint_count * 2.0
        )

    def _command_race_pressure_bonus(self, command):
        total = 0.0
        for key in (
            "_scheduled_race_safety_bonus",
            "_race_hard_floor_bonus",
            "_threshold_deficit_bonus",
            "_manual_race_specific_demand_bonus",
            "_postmortem_training_bonus",
            "_race_success_training_bonus",
        ):
            try:
                total += max(0.0, float((command or {}).get(key) or 0.0))
            except (TypeError, ValueError):
                continue
        return total

    def _apply_visible_tile_quality_guard(self, scored, chara, preset, turn):
        if not bool((preset or {}).get("visible_tile_quality_guard_enabled", True)):
            return scored
        if not scored:
            return scored
        try:
            self._last_quality_bonds = self._bond_map(chara)
            rows = []
            for score, command in scored:
                quality = self._visible_tile_quality(command)
                partners = command.get("training_partner_array") or []
                rainbow_count = sum(
                    1
                    for partner_id in partners
                    if partner_id in DECK_PARTNERS and int(self._last_quality_bonds.get(partner_id, 0) or 0) >= 80
                )
                rows.append((float(score or 0.0), command, quality, rainbow_count))
        finally:
            self._last_quality_bonds = {}
        best_quality = max((row[2] for row in rows), default=0.0)
        max_rainbow = max((row[3] for row in rows), default=0)
        if best_quality <= 0.0 and max_rainbow <= 0:
            return scored

        clear_gap = float((preset or {}).get("visible_tile_quality_clear_gap") or _VISIBLE_TILE_CLEAR_GAP)
        bonus_cap = float((preset or {}).get("visible_tile_quality_bonus_cap") or _VISIBLE_TILE_BONUS_CAP)
        penalty_cap = float((preset or {}).get("visible_tile_quality_penalty_cap") or _VISIBLE_TILE_PENALTY_CAP)
        penalty_scale = float((preset or {}).get("visible_tile_quality_penalty_scale") or _VISIBLE_TILE_PENALTY_SCALE)
        adjusted = []
        for score, command, quality, rainbow_count in rows:
            delta = 0.0
            quality_gap = max(0.0, best_quality - quality)
            race_pressure = self._command_race_pressure_bonus(command)
            pressure_scale = 0.35 if race_pressure >= _VISIBLE_TILE_RACE_PRESSURE_PROTECTION else 1.0

            if quality >= max(0.0, best_quality - clear_gap):
                ratio = quality / max(1.0, best_quality)
                delta += min(bonus_cap, 0.08 + ratio * 0.12)
            elif quality_gap > clear_gap:
                delta -= min(penalty_cap, (quality_gap - clear_gap) * penalty_scale) * pressure_scale

            if rainbow_count > 0:
                delta += min(bonus_cap, _VISIBLE_TILE_RAINBOW_BONUS + 0.04 * max(0, rainbow_count - 1))
            if max_rainbow > rainbow_count and quality_gap > 3.0:
                delta -= min(
                    penalty_cap,
                    (max_rainbow - rainbow_count) * _VISIBLE_TILE_MISSED_RAINBOW_PENALTY,
                ) * pressure_scale

            if delta:
                command["_visible_tile_quality"] = round(quality, 3)
                command["_visible_tile_quality_best"] = round(best_quality, 3)
                command["_visible_tile_quality_delta"] = round(delta, 4)
            adjusted.append((score + delta, command))
        return adjusted

    def _future_turn_effect_totals(self, chara, preset, max_turn=None):
        forecast = (preset or {}).get("future_turn_effects") or {}
        turns = forecast.get("turns") if isinstance(forecast, dict) else {}
        if not isinstance(turns, dict) or not turns:
            return {}
        try:
            current_turn = int(chara.get("turn") or 0)
        except (TypeError, ValueError):
            current_turn = 0
        if current_turn <= 0:
            return {}
        if max_turn is None:
            max_turn = 78
        scheduled_race_turns = self._scheduled_race_turns(preset)
        totals = {}
        for raw_turn, row in turns.items():
            try:
                source_turn = int(raw_turn)
            except (TypeError, ValueError):
                continue
            if source_turn < current_turn or source_turn > int(max_turn or 78):
                continue
            if not isinstance(row, dict):
                continue
            kind = str(row.get("kind") or "").strip().lower()
            if kind == "race":
                if source_turn not in scheduled_race_turns:
                    continue
            effects = row.get("effects") or {}
            if not isinstance(effects, dict):
                continue
            for key, value in effects.items():
                amount = float(value or 0.0)
                if amount <= 0:
                    continue
                totals[key] = totals.get(key, 0.0) + amount
        return totals

    def _future_stat_relief(self, target, chara, preset, max_turn=None):
        stat_name = _COMMAND_IDX_TO_STAT.get(target)
        if not stat_name:
            return 0.0
        return float(self._future_turn_effect_totals(chara, preset, max_turn=max_turn).get(stat_name) or 0.0)

    def _future_hp_relief(self, chara, preset, max_turn=None):
        return float(self._future_turn_effect_totals(chara, preset, max_turn=max_turn).get("hp") or 0.0)

    def _choice(self, event):
        choices = ((event.get("event_contents_info") or {}).get("choice_array") or [])
        if not choices:
            return 0
        if len(choices) > 1:
            return None
        return 0

    def choice_from_rewards(self, rewards, event):
        choices = ((event.get("event_contents_info") or {}).get("choice_array") or [])
        if not choices:
            return 0
        if not rewards:
            return choices[0].get("select_index", 1)
        best_index = 0
        best_score = None
        for i, reward in enumerate(rewards):
            score = self._reward_score(reward)
            if best_score is None or score > best_score:
                best_score = score
                best_index = i
        if best_index < len(choices):
            return choices[best_index].get("select_index", best_index + 1)
        return choices[0].get("select_index", 1)

    def _reward_score(self, reward):
        score = 0.0
        for item in reward.get("params_inc_dec_info_array") or reward.get("effected_parameter_array") or []:
            target = STAT_TARGETS.get(item.get("target_type"))
            value = float(item.get("value") or 0)
            if target is None:
                if item.get("target_type") == 10:
                    score += value * 0.03
                continue
            score += value * (0.02 if target < 5 else 0.01)
        score += float(reward.get("skill_point") or 0) * 0.01
        score += float(reward.get("vital") or 0) * 0.03
        return score

    def _best_command(self, data, chara, preset):
        commands = (data.get("home_info") or {}).get("command_info_array") or []
        enabled = [cmd for cmd in commands if cmd.get("is_enable", 1)]
        rest = self._rest_command(enabled)
        recreation = self._recreation_command(enabled)
        stat_recreation = self._stat_recreation_command(enabled)
        medic = self._medic_command(enabled)
        training = [cmd for cmd in enabled if cmd.get("command_type") == 1 and cmd.get("command_id") in TRAINING_COMMANDS]
        turn = int(chara.get("turn") or 0)
        vital = int(chara.get("vital") or 0)
        motivation = int(chara.get("motivation") or 3)
        bad_status = self._has_curable_bad_status(chara, preset)
        if not training:
            if medic and bad_status and vital <= ENERGY_MEDIC_GENERAL:
                return medic
            return rest or recreation
        scored = [(self._score_command(cmd, data, chara, preset), cmd) for cmd in training]
        if 48 < turn <= 72:
            stat_keys = ["speed", "stamina", "power", "guts", "wiz"]
            highest_idx = max(range(5), key=lambda idx: int(chara.get(stat_keys[idx]) or 0))
            scored = [(score * 0.95 if TRAINING_COMMANDS.get(cmd.get("command_id"), 0) == highest_idx and score > 0 else score, cmd) for score, cmd in scored]
        scored = self._apply_visible_tile_quality_guard(scored, chara, preset, turn)
        scored, bond_equity_state = self._apply_bond_equity_gate(scored, chara, preset, turn)
        scored, imitation_state = self._apply_imitation_prior(scored, preset, turn)
        sorted_scored = sorted(scored, key=lambda row: row[0], reverse=True)
        second_best_score = sorted_scored[1][0] if len(sorted_scored) > 1 else (sorted_scored[0][0] if sorted_scored else 0.0)
        for rank, (score, cmd) in enumerate(sorted_scored, start=1):
            cmd["_strategy_score"] = round(score, 4)
            cmd["_strategy_rank"] = rank
            cmd["_strategy_second_best_score"] = round(second_best_score, 4)
            cmd["_strategy_score_margin"] = round(score - second_best_score, 4)
            if bond_equity_state.get("active"):
                cmd["_bond_equity_gate"] = dict(bond_equity_state)
            if imitation_state.get("active"):
                cmd["_imitation_prior"] = dict(imitation_state)
        best_score, best = max(scored, key=lambda row: row[0])
        rest_threshold = int(_tuned_value(preset, "rest_threshold", int((preset or {}).get("rest_threshold") or 48)))
        if self._is_race_heavy_route(preset):
            rest_threshold -= int(
                _tuned_value(
                    preset,
                    "race_heavy_rest_threshold_penalty",
                    int((preset or {}).get("race_heavy_rest_threshold_penalty") or 4),
                )
            )
        base_rest_threshold = rest_threshold
        run_mode = self._current_run_mode(chara, preset)
        run_mode_policy = (preset or {}).get("run_mode_policy") or {}
        if run_mode == "preserve":
            rest_threshold += int(run_mode_policy.get("preserve_rest_bonus") or 2)
        elif run_mode == "push":
            rest_threshold -= int(run_mode_policy.get("push_rest_penalty") or 1)
        future_hp_relief = self._future_hp_relief(chara, preset, max_turn=turn + 2)
        if future_hp_relief > 0:
            rest_threshold -= min(12, int(future_hp_relief / 4.0))
        friendship_gap = self._first_summer_friendship_gap(chara, turn, preset)
        if friendship_gap > 0:
            rest_threshold -= int(
                (preset.get("first_summer_friendship_rest_threshold_penalty_per_gap")
                 or _FIRST_SUMMER_FRIENDSHIP_REST_THRESHOLD_PENALTY_PER_GAP)
                * min(friendship_gap, 3)
            )
            if turn <= 24:
                rest_threshold -= int(
                    preset.get("first_summer_friendship_early_rest_threshold_penalty")
                    or _FIRST_SUMMER_FRIENDSHIP_EARLY_REST_THRESHOLD_PENALTY
                )
        min_rest_threshold = 12 if friendship_gap > 0 else 30
        rest_threshold = max(min_rest_threshold, min(80, rest_threshold))
        failure = int(best.get("failure_rate") or 0)
        if medic and bad_status and vital <= ENERGY_FAST_MEDIC:
            return medic
        if medic and bad_status and vital <= ENERGY_MEDIC_GENERAL:
            return medic
        push_friendship_training = self._should_push_first_summer_training(
            turn,
            preset,
            friendship_gap,
            vital,
            failure,
            best_score,
        )
        friendship_failure_guard = False
        if friendship_gap > 0:
            strict_failure_cap = int(
                (preset.get("first_summer_friendship_max_push_failure")
                 or _FIRST_SUMMER_FRIENDSHIP_MAX_PUSH_FAILURE)
            )
            low_hp_failure_guard = max(
                base_rest_threshold + 8,
                int(
                    (preset.get("first_summer_friendship_min_push_vital")
                     or _FIRST_SUMMER_FRIENDSHIP_MIN_PUSH_VITAL)
                ) + 8,
            )
            friendship_failure_guard = failure >= strict_failure_cap and vital <= low_hp_failure_guard
        safe_low_hp_wit = self._safe_low_hp_wit_training(
            scored,
            preset,
            vital,
            max(rest_threshold, base_rest_threshold),
            False,
        )

        # Stat-friend outings are real recovery/stat actions, but the API
        # payload is not the same as ordinary recreation. Command row 390 is a
        # useful readiness signal only; direct 390 payload guesses failed live.
        # Only execute it when a verified wire payload has been captured.
        stat_friend_outing_ceiling = int(
            _tuned_value(
                preset,
                "stat_friend_recreation_max_vital",
                int((preset or {}).get("stat_friend_recreation_max_vital") or _RECREATION_VITAL_CEILING),
            )
        )
        specific_outing_priority = (
            self._specific_stat_outing_available(preset, stat_recreation, chara)
            and vital < stat_friend_outing_ceiling
        )
        if specific_outing_priority and self._should_take_stat_friend_recreation(
            preset,
            turn=turn,
            motivation=motivation,
            vital=vital,
            best_score=best_score,
            failure=failure,
            rest_threshold=rest_threshold,
            chara=chara,
        ):
            learned_recreation = self._learned_stat_recreation_command(stat_recreation, chara, preset)
            if learned_recreation:
                return learned_recreation
            initial_recreation = self._with_initial_stat_recreation_payload(stat_recreation, chara, preset)
            if initial_recreation:
                return initial_recreation
            # A ready stat-friend row without a verified payload is capture
            # debt, not an executable command. Continue normal training/rest
            # evaluation instead of breaking the run with API 102/205.
        # Non-Wit failure cap. Operator policy: 24-30% failure on
        # Speed/Power/Stamina/Guts tiles is unacceptable — those should
        # rest or substitute with Wit instead. Wit retains the higher
        # 25% allowance because it inherently has low failure AND it's
        # the rest-substitute. Observed bot picking Speed @ 30% (T49)
        # and Speed @ 24% (T55) in the S+ 16,116 career — both bad.
        non_wit_failure_cap = int(_tuned_value(preset, "non_wit_training_max_failure", 15))
        best_is_wit = TRAINING_COMMANDS.get((best or {}).get("command_id")) == 4
        high_value_non_wit_failure_cap = int(
            _tuned_value(
                preset,
                "non_wit_high_value_training_max_failure",
                int((preset or {}).get("non_wit_high_value_training_max_failure") or 24),
            )
        )
        high_value_non_wit = (
            (not best_is_wit)
            and failure <= high_value_non_wit_failure_cap
            and (
                self._training_positive_stat_gain(best) >= 25.0
                or self._deck_partner_count(best) >= 2
            )
        )
        non_wit_over_cap = (not best_is_wit) and failure > non_wit_failure_cap and not high_value_non_wit
        hard_failure_threshold = int(
            _tuned_value(
                preset,
                "hard_failure_safe_wit_threshold",
                int((preset or {}).get("hard_failure_safe_wit_threshold") or 28),
            )
        )
        hard_failure_vital_ceiling = int(
            _tuned_value(
                preset,
                "hard_failure_safe_wit_vital_ceiling",
                int((preset or {}).get("hard_failure_safe_wit_vital_ceiling") or 60),
            )
        )
        if (
            vital <= hard_failure_vital_ceiling
            and (failure >= hard_failure_threshold or non_wit_over_cap)
        ):
            forced_safe_wit = self._safe_low_hp_wit_training(
                scored,
                preset,
                vital,
                max(rest_threshold, base_rest_threshold, hard_failure_vital_ceiling),
                False,
                ignore_score_floor=True,
            )
            if forced_safe_wit:
                return forced_safe_wit
        if self._should_take_low_hp_wit_training(best, preset, vital, rest_threshold, failure, best_score, friendship_failure_guard):
            return best
        if safe_low_hp_wit and (
            vital <= max(rest_threshold, base_rest_threshold)
            or failure >= 35
            or non_wit_over_cap
            or best_score < 0
            or friendship_failure_guard
        ):
            return safe_low_hp_wit
        # Recreation is unavailable during Summer Camp in MANT — fall back to
        # rest instead. If the game ever exposes a `command_type == 3` during
        # summer, treating it as recreation would still be wrong because the
        # camp's level-5 training board is the whole point of the window.
        if turn in SUMMER_CAMP_TURNS and rest and (vital <= rest_threshold or failure >= 35 or best_score < 0):
            if push_friendship_training:
                return best
            return rest
        if self._should_recreate(recreation, preset, turn, motivation, vital, best_score, friendship_gap=friendship_gap, chara=chara):
            return recreation
        if rest and (vital <= rest_threshold or failure >= 35 or non_wit_over_cap or best_score < 0 or friendship_failure_guard):
            if push_friendship_training and not friendship_failure_guard:
                return best
            return rest
        conserve = self._summer_conserve_command(enabled, turn, vital, best_score, preset, rest, recreation)
        if conserve:
            return conserve
        return best

    def _safe_low_hp_wit_training(
        self,
        scored,
        preset,
        vital,
        rest_threshold,
        friendship_failure_guard=False,
        *,
        ignore_score_floor=False,
    ):
        """Prefer a safe HP-positive Wit tile over spending a full rest turn.

        This only fires when HP is already low and the Wit training itself is
        low-risk. It does not authorize risky non-Wit training, so it should
        reduce wasted recovery turns without adding high-failure gambles.
        """
        if not bool((preset or {}).get("low_hp_wit_training_override_enabled", True)):
            return None
        if friendship_failure_guard:
            return None
        try:
            vital = int(vital or 0)
            rest_threshold = int(rest_threshold or 0)
        except (TypeError, ValueError):
            return None
        if vital > rest_threshold:
            return None
        # Wit-as-rest substitution: rest gives ZERO stat output, so we should
        # prefer any HP-positive Wit tile over rest unless wit is actively
        # dangerous. Per audit, manual play does 0 rests vs bot's 6 — wit
        # training (positive HP, low failure) substitutes for rest in
        # manual play. Made the thresholds permissive so the bot does
        # the same. Failure ≤ 25%, any score ≥ 0.01.
        max_failure = int(
            _tuned_value(
                preset,
                "low_hp_wit_training_max_failure",
                int((preset or {}).get("low_hp_wit_training_max_failure") or 25),
            )
        )
        min_score = float(
            _tuned_value(
                preset,
                "low_hp_wit_training_substitute_min_score",
                float((preset or {}).get("low_hp_wit_training_substitute_min_score") or 0.01),
            )
        )
        best = None
        best_score = None
        for score, command in scored or []:
            if not command or TRAINING_COMMANDS.get(command.get("command_id")) != 4:
                continue
            try:
                failure = int(command.get("failure_rate") or 0)
                score_value = float(score or 0.0)
            except (TypeError, ValueError):
                continue
            if failure > max_failure or (not ignore_score_floor and score_value < min_score):
                continue
            hp_gain = 0.0
            for item in command.get("params_inc_dec_info_array") or []:
                if item.get("target_type") == 10:
                    hp_gain += max(0.0, float(item.get("value") or 0.0))
            if hp_gain <= 0.0:
                continue
            if best is None or score_value > best_score:
                best = command
                best_score = score_value
        return best

    def _should_take_low_hp_wit_training(self, command, preset, vital, rest_threshold, failure, best_score, friendship_failure_guard=False):
        if not bool((preset or {}).get("low_hp_wit_training_override_enabled", True)):
            return False
        if friendship_failure_guard:
            return False
        if not command or TRAINING_COMMANDS.get(command.get("command_id")) != 4:
            return False
        try:
            vital = int(vital or 0)
            rest_threshold = int(rest_threshold or 0)
            failure = int(failure or 0)
            best_score = float(best_score or 0.0)
        except (TypeError, ValueError):
            return False
        if vital > rest_threshold:
            return False
        max_failure = int(
            _tuned_value(
                preset,
                "low_hp_wit_training_max_failure",
                int((preset or {}).get("low_hp_wit_training_max_failure") or 25),
            )
        )
        if failure > max_failure:
            return False
        min_score = float(
            _tuned_value(
                preset,
                "low_hp_wit_training_min_score",
                float((preset or {}).get("low_hp_wit_training_min_score") or 0.08),
            )
        )
        if best_score < min_score:
            return False
        hp_gain = 0.0
        for item in command.get("params_inc_dec_info_array") or []:
            if item.get("target_type") == 10:
                hp_gain += max(0.0, float(item.get("value") or 0.0))
        return hp_gain > 0.0

    def _rest_command(self, commands):
        for cmd in commands:
            if cmd.get("command_type") == 7 and cmd.get("command_id") == 701:
                return cmd
        return None

    def _recreation_command(self, commands):
        # Ordinary recreation is command 301. Stat-friend outings use a
        # separate row and are handled by _stat_recreation_command so generic
        # low-HP/mood logic cannot accidentally spam unverified Riko payloads.
        for cmd in commands:
            if cmd.get("command_type") == 3 and self._effective_command_id(cmd) == 301:
                return cmd
        return None

    def _stat_recreation_command(self, commands):
        for cmd in commands:
            if cmd.get("command_type") == 3 and self._effective_command_id(cmd) == 390:
                return cmd
        return None

    def _effective_command_id(self, command):
        """Return the actionable command id even after recreation payload
        rewriting.

        Home command rows usually carry the ID in `command_id`, but selected
        recreation payloads are rewritten to `command_id=0` and
        `command_group_id=<outing id>`. Recreation gating must compare the
        effective ID or it will mistake every rewritten outing for a
        non-generic pal event.
        """
        if not command:
            return 0
        for key in ("command_id", "command_group_id"):
            try:
                value = int(command.get(key) or 0)
            except (TypeError, ValueError):
                value = 0
            if value:
                return value
        return 0

    def _medic_command(self, commands):
        for cmd in commands:
            if cmd.get("command_type") == 8 and cmd.get("command_id") == 801:
                return cmd
        return None

    def _enabled_training(self, commands, command_id):
        for cmd in commands:
            if cmd.get("command_type") == 1 and cmd.get("command_id") == command_id:
                return cmd
        return None

    def _enabled_training_idx(self, commands, idx):
        for cmd in commands:
            if cmd.get("command_type") == 1 and TRAINING_COMMANDS.get(cmd.get("command_id")) == idx:
                return cmd
        return None

    def _stat_recreation_payload_file(self):
        from pathlib import Path

        base_dir = None
        if self.race_planner is not None:
            base_dir = getattr(self.race_planner, "base_dir", None)
        if base_dir:
            return Path(base_dir) / "data" / "stat_friend_recreation_payloads.json"
        return Path(__file__).resolve().parents[2] / "data" / "stat_friend_recreation_payloads.json"

    def _load_stat_recreation_payloads(self):
        """Load verified stat-friend outing request shapes.

        This file is intentionally separate from normal policy config. These
        values are wire-level API payloads learned from successful captures; if
        no verified payload exists, the bot must not guess.
        """
        path = self._stat_recreation_payload_file()
        self._stat_recreation_payloads_path = path
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0
        if self._stat_recreation_payloads_mtime == mtime:
            return self._stat_recreation_payloads
        self._stat_recreation_payloads_mtime = mtime
        if not mtime:
            self._stat_recreation_payloads = {}
            return self._stat_recreation_payloads
        try:
            import json

            loaded = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            loaded = {}
        self._stat_recreation_payloads = loaded if isinstance(loaded, dict) else {}
        return self._stat_recreation_payloads

    def _stat_recreation_payload_config(self, preset):
        if isinstance(preset, dict):
            override = preset.get("stat_friend_recreation_payloads")
            if isinstance(override, dict):
                return override
        return self._load_stat_recreation_payloads()

    def _stat_recreation_card_payloads(self, preset, card_id):
        payloads = self._stat_recreation_payload_config(preset)
        if not isinstance(payloads, dict):
            return {}
        cards = payloads.get("cards") if isinstance(payloads.get("cards"), dict) else payloads
        if not isinstance(cards, dict):
            return {}
        card_payloads = cards.get(str(card_id)) or cards.get(card_id) or {}
        return card_payloads if isinstance(card_payloads, dict) else {}

    def _stat_recreation_payload_template(self, preset, card_id, info):
        card_payloads = self._stat_recreation_card_payloads(preset, card_id)
        if not card_payloads:
            return None
        try:
            taken = int((info or {}).get("taken") or 0)
        except (TypeError, ValueError):
            taken = 0
        if taken <= 0:
            template = (
                card_payloads.get("initial")
                or card_payloads.get("verified_initial")
                or card_payloads.get("first")
            )
            return template if self._stat_recreation_payload_verified(template) else None

        next_outing = taken + 1
        stages = card_payloads.get("stages")
        if isinstance(stages, dict):
            for key in (str(next_outing), str(taken), f"story_step_{taken}", f"outing_{next_outing}"):
                template = stages.get(key)
                if self._stat_recreation_payload_verified(template):
                    return template
        for key in (f"outing_{next_outing}", f"story_step_{taken}", "started", "after_initial"):
            template = card_payloads.get(key)
            if self._stat_recreation_payload_verified(template):
                return template
        return None

    def _stat_recreation_payload_verified(self, template):
        if not isinstance(template, dict):
            return False
        status = str(template.get("status") or "").strip().lower()
        source = str(template.get("source") or "").strip().lower()
        return bool(
            template.get("verified") is True
            or template.get("captured") is True
            or status == "verified"
            or source.startswith("verified")
            or source.startswith("captured")
        )

    def _resolve_stat_recreation_payload_value(self, value, partner_id, info):
        if isinstance(value, str):
            key = value.strip().lower()
            if key in {"partner_id", "target_id", "training_partner_id"}:
                return int(partner_id or 0)
            if key == "card_id":
                return int((info or {}).get("card_id") or 0)
            if key == "taken":
                return int((info or {}).get("taken") or 0)
            if key == "next_outing":
                return int((info or {}).get("taken") or 0) + 1
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    def _command_with_stat_recreation_payload(self, command, template, partner_id, info):
        if not command or not isinstance(template, dict):
            return None
        selected = dict(command)
        fallback_group_id = self._effective_command_id(command)
        exact = {
            "command_type": self._resolve_stat_recreation_payload_value(
                template.get("command_type", command.get("command_type", 3)),
                partner_id,
                info,
            ),
            "command_id": self._resolve_stat_recreation_payload_value(
                template.get("command_id", command.get("command_id", 0)),
                partner_id,
                info,
            ),
            "command_group_id": self._resolve_stat_recreation_payload_value(
                template.get("command_group_id", command.get("command_group_id", fallback_group_id)),
                partner_id,
                info,
            ),
            "select_id": self._resolve_stat_recreation_payload_value(
                template.get("select_id", command.get("select_id", 0)),
                partner_id,
                info,
            ),
        }
        selected.update(exact)
        selected["_exec_command_payload"] = exact
        selected["_stat_recreation_card_id"] = int((info or {}).get("card_id") or 0)
        selected["_stat_recreation_partner_id"] = int(partner_id or 0)
        selected["_stat_recreation_payload_source"] = template.get("source") or "learned"
        return selected

    def _with_initial_stat_recreation_payload(self, command, chara, preset):
        per_card = self._outing_status_per_card(chara or {}, preset or {})
        for partner_id, info in per_card.items():
            if not info.get("ready") or int(info.get("taken") or 0) > 0:
                continue
            template = self._stat_recreation_payload_template(preset, info.get("card_id"), info)
            learned = self._command_with_stat_recreation_payload(command, template, partner_id, info)
            if learned:
                return learned
        return None

    def _learned_stat_recreation_command(self, command, chara, preset):
        if not self._stat_recreation_chain_started(chara, preset):
            return None
        per_card = self._outing_status_per_card(chara or {}, preset or {})
        for partner_id, info in per_card.items():
            if not info.get("ready") or int(info.get("taken") or 0) <= 0:
                continue
            template = self._stat_recreation_payload_template(preset, info.get("card_id"), info)
            learned = self._command_with_stat_recreation_payload(command, template, partner_id, info)
            if learned:
                return learned
        return None

    def _stat_recreation_card_ids(self, preset):
        # Scan both deck cards and friend slot. A stat friend only unlocks
        # recreation priority when the live evaluation row says `is_outing=1`
        # AND we have a verified payload entry for that card. Do not execute
        # other pal/friend cards from the broad candidate list until their
        # outing packets have been captured.
        ctx = (preset or {}).get("_run_context") or {}
        ids = set()
        raw_support_ids = list(ctx.get("support_card_ids") or [])
        for card in ctx.get("support_cards") or []:
            if isinstance(card, dict):
                raw_support_ids.append(card.get("support_card_id") or card.get("id"))
        raw_support_ids.append(ctx.get("friend_card_id"))
        for raw_id in raw_support_ids:
            try:
                value = int(raw_id or 0)
            except (TypeError, ValueError):
                continue
            if value:
                ids.add(value)
        candidate_ids = {card_id for card_id in ids if card_id in _STAT_RECREATION_FRIEND_CARDS}
        payloads = self._stat_recreation_payload_config(preset)
        cards = payloads.get("cards") if isinstance(payloads, dict) and isinstance(payloads.get("cards"), dict) else payloads
        if not isinstance(cards, dict):
            return set()
        verified_ids = set()
        for card_id in candidate_ids:
            card_payloads = cards.get(str(card_id)) or cards.get(card_id)
            if not isinstance(card_payloads, dict):
                continue
            templates = []
            for key in ("initial", "verified_initial", "first", "started", "after_initial"):
                templates.append(card_payloads.get(key))
            stages = card_payloads.get("stages")
            if isinstance(stages, dict):
                templates.extend(stages.values())
            if any(self._stat_recreation_payload_verified(template) for template in templates):
                verified_ids.add(card_id)
        return verified_ids

    def _specific_stat_outing_available(self, preset, recreation_command, chara=None):
        """Return True only when a stat-recreation friend is outing-ready.

        Command 390 by itself is not trusted. It only becomes executable after
        a successful raw game-client request shape is recorded for that card.
        Command 301 alone is ordinary recreation and must never be treated as
        Riko.
        """
        if not recreation_command:
            return False
        cmd_id = self._effective_command_id(recreation_command)
        if cmd_id == 0:
            return False
        stat_partner_ids = self._stat_recreation_partner_ids(preset)
        if not stat_partner_ids:
            return False
        outing_ready = self._outing_ready_partner_ids(chara or {}, preset)
        if not (stat_partner_ids & outing_ready):
            return False
        if cmd_id == 390:
            return True

        # Non-390 commands must carry explicit target/card metadata. This
        # keeps bare 301 from being misclassified as Riko.
        def as_int(value) -> int:
            try:
                return int(value or 0)
            except (TypeError, ValueError):
                return 0

        explicit_card_id = as_int(
            recreation_command.get("support_card_id")
            or recreation_command.get("card_id")
            or recreation_command.get("target_card_id")
        )
        explicit_target_id = as_int(
            recreation_command.get("target_id")
            or recreation_command.get("training_partner_id")
            or recreation_command.get("select_id")
        )
        if explicit_card_id:
            if explicit_card_id not in self._stat_recreation_card_ids(preset):
                return False
        elif explicit_target_id:
            if explicit_target_id not in self._stat_recreation_partner_ids(preset):
                return False
        else:
            return False
        return True

    def _stat_recreation_target_bond(self, preset):
        try:
            return max(1, int((preset or {}).get("stat_friend_recreation_target_bond") or _STAT_RECREATION_TARGET_BOND))
        except (TypeError, ValueError):
            return _STAT_RECREATION_TARGET_BOND

    def _stat_recreation_partner_ids(self, preset):
        ctx = (preset or {}).get("_run_context") or {}
        stat_card_ids = self._stat_recreation_card_ids(preset)
        if not stat_card_ids:
            return set()
        partner_ids = set()
        support_ids = ctx.get("support_card_ids") or []
        for index, raw_id in enumerate(support_ids, start=1):
            try:
                card_id = int(raw_id or 0)
            except (TypeError, ValueError):
                continue
            if card_id in stat_card_ids:
                partner_ids.add(index)
        support_cards = ctx.get("support_cards") or []
        for index, card in enumerate(support_cards, start=1):
            if not isinstance(card, dict):
                continue
            try:
                card_id = int(card.get("support_card_id") or card.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if card_id in stat_card_ids:
                partner_ids.add(index)
        try:
            friend_card_id = int(ctx.get("friend_card_id") or 0)
        except (TypeError, ValueError):
            friend_card_id = 0
        if friend_card_id in stat_card_ids:
            partner_ids.add(6)
        return partner_ids

    def _outing_ready_partner_ids(self, chara, preset):
        return {
            int(partner_id)
            for partner_id, info in self._outing_status_per_card(chara or {}, preset or {}).items()
            if info.get("ready")
        }

    def _stat_recreation_chain_started(self, chara, preset):
        for info in self._outing_status_per_card(chara or {}, preset or {}).values():
            if info.get("ready") and int(info.get("taken") or 0) > 0:
                return True
        return False

    def _with_stat_recreation_select_id(self, command, chara, preset):
        if not command:
            return command
        selected = dict(command)
        if not self._stat_recreation_chain_started(chara, preset):
            return selected
        per_card = self._outing_status_per_card(chara or {}, preset or {})
        for partner_id, info in per_card.items():
            if info.get("ready") and int(info.get("taken") or 0) > 0:
                selected["select_id"] = int(partner_id)
                break
        return selected

    def _outing_card_max(self, card_id):
        """Return the total outing count for a stat-recreation card.

        Verified from `data/event_id_index.json` (chain_max field). Cards
        without local chain data fall back to the sim's default of 5.
        """
        try:
            cid = int(card_id or 0)
        except (TypeError, ValueError):
            return _STAT_RECREATION_OUTING_MAX_DEFAULT
        return _STAT_RECREATION_OUTING_MAX.get(cid, _STAT_RECREATION_OUTING_MAX_DEFAULT)

    def _outing_status_per_card(self, chara, preset):
        """Return outing progress for every stat-recreation card the bot has.

        Reads the game's `story_step` field from `evaluation_info_array` —
        that field counts outings already completed for the chain. Combined
        with the static per-card max, we know how many remain.

        Returns: {partner_id: {card_id, max, taken, remaining, ready, bond}}
        """
        out = {}
        stat_card_ids = self._stat_recreation_card_ids(preset)
        if not stat_card_ids:
            return out
        ctx = (preset or {}).get("_run_context") or {}
        # Build partner_id -> card_id mapping from the deck + friend slot
        partner_to_card = {}
        support_ids = ctx.get("support_card_ids") or []
        for index, raw_id in enumerate(support_ids, start=1):
            try:
                partner_to_card[index] = int(raw_id or 0)
            except (TypeError, ValueError):
                continue
        for card in ctx.get("support_cards") or []:
            if not isinstance(card, dict):
                continue
            try:
                pid = int(card.get("partner_id") or 0)
                cid = int(card.get("support_card_id") or card.get("id") or 0)
            except (TypeError, ValueError):
                continue
            if pid and cid:
                partner_to_card[pid] = cid
        # Friend partner_id is typically a high index like 6 (deck has 5
        # cards + 1 friend) — accept either explicit mapping or implicit
        friend_id = 0
        try:
            friend_id = int(ctx.get("friend_card_id") or 0)
        except (TypeError, ValueError):
            friend_id = 0

        for row in (chara or {}).get("evaluation_info_array") or []:
            try:
                target_id = int(row.get("target_id") or 0)
                story_step = int(row.get("story_step") or 0)
                is_outing = int(row.get("is_outing") or 0)
                bond = int(row.get("evaluation") or 0)
            except (TypeError, ValueError):
                continue
            card_id = partner_to_card.get(target_id)
            # If this partner_id isn't in our map but it's the friend slot,
            # use the friend card_id (friend slot's partner_id is variable).
            if not card_id and friend_id and friend_id in stat_card_ids:
                # Heuristic: if no mapping but friend card matches, attribute
                # this row to the friend slot.
                card_id = friend_id
            if not card_id or card_id not in stat_card_ids:
                continue
            max_outings = self._outing_card_max(card_id)
            taken = max(0, min(max_outings, story_step))
            remaining = max(0, max_outings - taken)
            out[target_id] = {
                "card_id": card_id,
                "max": max_outings,
                "taken": taken,
                "remaining": remaining,
                # The game can leave is_outing=1 after the final pal outing.
                # Do not keep spending turns on command 390 once the chain is
                # exhausted.
                "ready": bool(is_outing and remaining > 0),
                "bond": bond,
            }
        return out

    def _outing_summary_for_signals(self, chara, preset):
        """Compact outing-status summary for decision_understanding signals."""
        per_card = self._outing_status_per_card(chara, preset)
        if not per_card:
            return None
        summary = {
            "total_max": 0,
            "total_taken": 0,
            "total_remaining": 0,
            "any_ready": False,
            "per_partner": {},
        }
        for partner_id, info in per_card.items():
            summary["total_max"] += info["max"]
            summary["total_taken"] += info["taken"]
            summary["total_remaining"] += info["remaining"]
            summary["any_ready"] = summary["any_ready"] or info["ready"]
            summary["per_partner"][str(partner_id)] = {
                "card_id": info["card_id"],
                "taken": info["taken"],
                "max": info["max"],
                "ready": info["ready"],
            }
        return summary

    def _summer_conserve_command(self, enabled, turn, vital, best_score, preset, rest, recreation):
        if turn not in SUMMER_CONSERVE_TURNS:
            return None
        if best_score >= float(preset.get("summer_score_threshold") or 0.34):
            return None
        if vital < SUMMER_CONSERVE_ENERGY:
            # Recreation is unavailable during Summer Camp; rest is the
            # correct conserve action there.
            return rest
        return self._enabled_training_idx(enabled, 4)

    def _has_curable_bad_status(self, chara, preset):
        wanted = self._cure_condition_names(preset)
        if not wanted:
            return False
        for effect_id in chara.get("chara_effect_id_array") or []:
            try:
                effect_id = int(effect_id)
            except (TypeError, ValueError):
                continue
            name = BAD_EFFECT_NAMES.get(effect_id)
            if name and self._condition_key(name) in wanted:
                return True
        return False

    def _cure_condition_names(self, preset):
        result = set()
        names = preset.get("cure_asap_conditions") or []
        if isinstance(names, str):
            names = names.split(",")
        for name in names:
            key = self._condition_key(name)
            if key:
                result.add(key)
        return result

    def _condition_key(self, name):
        text = str(name or "").strip()
        if not text or text.startswith("("):
            return ""
        return "".join(ch.lower() for ch in text if ch.isalnum())

    def _distance_category(self, distance):
        text = str(distance or "").strip().lower()
        if not text:
            return "any"
        if text in {"short", "sprint"}:
            return "sprint"
        if text == "mile":
            return "mile"
        if text in {"middle", "medium", "mid"}:
            return "medium"
        if text == "long":
            return "long"
        try:
            value = int(float(text))
        except (TypeError, ValueError):
            return "any"
        if value <= 1400:
            return "sprint"
        if value <= 1800:
            return "mile"
        if value <= 2400:
            return "medium"
        return "long"

    def _trainee_style(self, preset, chara=None):
        style = str((preset or {}).get("skill_profile_style") or "").strip().lower()
        return style or "any"

    def _trainee_distance(self, preset, chara=None):
        configured = self._distance_category((preset or {}).get("skill_profile_distance"))
        if configured != "any":
            return configured
        counts = {"sprint": 0, "mile": 0, "medium": 0, "long": 0}
        entries = []
        if self.race_planner:
            try:
                entries = self.race_planner.scheduled_entries(preset or {}) or []
            except Exception:
                entries = []
        if not entries:
            entries = (preset or {}).get("custom_race_schedule") or []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            category = self._distance_category(entry.get("distance"))
            if category in counts:
                counts[category] += 1
        if not any(counts.values()):
            return "any"
        return max(counts.items(), key=lambda item: item[1])[0]

    def _trainee_deck_quality_bucket(self, preset):
        run_context = (preset or {}).get("_run_context") or {}
        if not isinstance(run_context, dict):
            run_context = {}
        for value in ((preset or {}).get("_deck_quality_bucket"), run_context.get("deck_quality_bucket")):
            try:
                if value is not None:
                    return int(value)
            except (TypeError, ValueError):
                pass
        return compute_deck_quality_bucket((preset or {}).get("deck") or (preset or {}).get("support_cards") or [])

    def _expect_attribute_targets(self, preset, chara=None, default=None):
        run_context = (preset or {}).get("_run_context") or {}
        if not isinstance(run_context, dict):
            run_context = {}
        return resolve_expect_attribute(
            preset,
            default=default,
            run_context=run_context,
            style=self._trainee_style(preset, chara),
            distance=self._trainee_distance(preset, chara),
            deck_quality_bucket=self._trainee_deck_quality_bucket(preset),
            desired_parent_sparks=(preset or {}).get("desired_parent_sparks"),
        )

    def _facility_progress_value(self, row):
        if not isinstance(row, dict):
            return 0
        for key in ("progress", "facility_progress", "training_progress", "count"):
            if row.get(key) is None:
                continue
            try:
                return max(0, min(3, int(row.get(key) or 0)))
            except (TypeError, ValueError):
                continue
        for key in ("training_count", "failure_num", "total_training_count"):
            if row.get(key) is None:
                continue
            try:
                return max(0, int(row.get(key) or 0) % 4)
            except (TypeError, ValueError):
                continue
        return 0

    def _facility_level_info(self, command, chara):
        """Return (level, progress, until_next_level) for a training command."""
        if not isinstance(command, dict) or not isinstance(chara, dict):
            return (None, None, None)
        try:
            command_id = int(command.get("command_id") or 0)
        except (TypeError, ValueError):
            command_id = 0
        if not command_id:
            return (None, None, None)
        command_idx = TRAINING_COMMANDS.get(command_id)
        rows = chara.get("training_level_info_array") or []
        matched = None
        for position, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            try:
                row_command_id = int(row.get("command_id") or 0)
            except (TypeError, ValueError):
                row_command_id = 0
            row_idx = TRAINING_COMMANDS.get(row_command_id)
            if row_command_id == command_id:
                matched = row
                break
            if command_idx is not None and row_idx == command_idx:
                matched = row
                break
            if command_idx is not None and not row_command_id and position == command_idx:
                matched = row
                break
        if not matched:
            return (None, None, None)
        try:
            level = int(matched.get("level") or matched.get("facility_level") or command.get("level") or 1)
        except (TypeError, ValueError):
            level = 1
        level = max(1, min(5, level))
        progress = self._facility_progress_value(matched)
        until_next = max(0, 4 - progress) if level < 5 else None
        return (level, progress, until_next)

    def _planned_recovery_count(self, preset):
        """Count configured stamina recovery skills in the preset skill plan."""
        if not isinstance(preset, dict):
            return 1
        entries = preset.get("learn_skill_list") or []
        names = set()

        def visit(value):
            if isinstance(value, dict):
                for key in ("name", "skill_name", "display_name"):
                    if value.get(key):
                        visit(value.get(key))
                return
            if isinstance(value, (list, tuple, set)):
                for item in value:
                    visit(item)
                return
            key = normalize_skill_name(value)
            if key in STAMINA_RECOVERY_SKILL_NAMES:
                names.add(key)

        visit(entries)
        return max(0, min(3, len(names)))

    def _command_reason(self, command, chara=None, preset=None):
        command_type = command.get("command_type")
        command_id = command.get("command_id")
        if command_id in TRAINING_COMMANDS:
            return f"training {TRAINING_NAMES[TRAINING_COMMANDS.get(command_id, 0)]} {command_id}"
        if command_type == 7 and command_id == 701:
            return f"rest {command_id}"
        if command_type == 3:
            # Render `outing (3/5) Riko` only for verified stat-friend
            # commands. Generic 301 recreation can coexist with a ready Riko
            # row and must stay labeled as ordinary recreation.
            try:
                if (
                    chara is not None
                    and preset is not None
                    and self._specific_stat_outing_available(preset, command, chara)
                ):
                    per_card = self._outing_status_per_card(chara, preset or self.preset)
                    # Pick the partner whose outing is currently ready —
                    # that's the one this command will trigger.
                    ready_entry = None
                    for partner_id, info in per_card.items():
                        if info.get("ready"):
                            ready_entry = info
                            break
                    if ready_entry:
                        card_id = ready_entry.get("card_id")
                        # Outing about to be taken is `taken + 1` (1-indexed)
                        next_n = int(ready_entry.get("taken", 0)) + 1
                        max_n = int(ready_entry.get("max", _STAT_RECREATION_OUTING_MAX_DEFAULT))
                        name = _STAT_RECREATION_CARD_NAMES.get(card_id, f"card{card_id}")
                        return f"outing ({next_n}/{max_n}) {name}"
            except Exception:
                pass
            return f"recreation {self._effective_command_id(command)}"
        if command_type == 8 and command_id == 801:
            return "medic 801"
        return f"command {command_type}:{command_id}"

    def _race_info_for_program(self, program_id):
        program_id = int(program_id or 0)
        if not program_id or not self.race_planner:
            return {"program_id": program_id}
        race = dict(self.race_planner.catalog.by_program_id.get(program_id) or {})
        program = dict((self.race_planner.program or {}).get(program_id) or {})
        race_instance_id = int(race.get("race_instance_id") or program.get("race_instance_id") or 0)
        grade = race.get("type") or program.get("type") or ""
        if not grade and race_instance_id:
            first_digit = str(race_instance_id)[0]
            grade = {"1": "G1", "2": "G2", "3": "G3", "4": "OP"}.get(first_digit, "")
        return {
            "program_id": program_id,
            "race_id": int(race.get("id") or program.get("race_id") or 0),
            "race_instance_id": race_instance_id,
            "name": race.get("name") or program.get("name") or "",
            "grade": grade,
            "distance": race.get("distance") or program.get("distance") or "",
            "terrain": race.get("terrain") or program.get("terrain") or "",
        }

    def _race_decision_understanding(self, program_id, chara, forced=False, optional=False):
        race_info = self._race_info_for_program(program_id)
        intent_tags = ["forced_race" if forced else "scheduled_race"]
        if optional:
            intent_tags.append("optional_race")
        if str(race_info.get("grade") or "").upper() == "G1":
            intent_tags.append("must_win_race")
        summary = f"{'force' if forced else 'run'} {race_info.get('grade') or 'scheduled'} race {race_info.get('name') or program_id}"
        return {
            "schema": "sweepy_decision_understanding_v1",
            "action": "race",
            "primary_intent": intent_tags[0],
            "intent_tags": intent_tags,
            "summary": summary.strip(),
            "signals": {
                "program_id": int(program_id or 0),
                "turn": int(chara.get("turn") or 0),
                "forced": bool(forced),
                "optional": bool(optional),
                "grade": race_info.get("grade") or "",
                "race_name": race_info.get("name") or "",
            },
        }

    def _settle_state_understanding(self, chara, detail, kind):
        """Decision-understanding payload for settle_state branches.

        Previously settle_state Decisions were built without an
        understanding dict, so the resulting turn detail had an empty
        `decision_understanding` and the post-mortem couldn't see why
        the bot bailed. Surface playing_state / chara_state / turn /
        kind into signals so the log explains the stall.
        """
        return {
            "schema": "sweepy_decision_understanding_v1",
            "action": "settle_state",
            "primary_intent": "state_reconcile",
            "intent_tags": ["state_reconcile", kind],
            "summary": detail,
            "signals": {
                "turn": int(chara.get("turn") or 0),
                "playing_state": int(chara.get("playing_state") or 0),
                "chara_state": int(chara.get("state") or 0),
                "race_program_id": int(chara.get("race_program_id") or 0),
                "vital": int(chara.get("vital") or 0),
                "kind": str(kind or ""),
            },
        }

    def _command_decision_understanding(self, command, data, chara, preset):
        command_type = int(command.get("command_type") or 0)
        command_id = int(command.get("command_id") or 0)
        if command_type == 1 and command_id in TRAINING_COMMANDS:
            return self._training_decision_understanding(command, chara, preset)
        if command_type == 7 and command_id == 701:
            vital = int(chara.get("vital") or 0)
            return {
                "schema": "sweepy_decision_understanding_v1",
                "action": "rest",
                "primary_intent": "energy_recovery",
                "intent_tags": ["energy_recovery"],
                "summary": f"recover energy at {vital} vitality before the next turn",
                "signals": {
                    "current_vital": vital,
                    "turn": int(chara.get("turn") or 0),
                },
            }
        if command_type == 3:
            vital = int(chara.get("vital") or 0)
            return {
                "schema": "sweepy_decision_understanding_v1",
                "action": "recreation",
                "primary_intent": "energy_recovery",
                "intent_tags": ["energy_recovery", "motivation_or_summer_reset"],
                "summary": f"use recreation at {vital} vitality for recovery or camp setup",
                "signals": {
                    "current_vital": vital,
                    "turn": int(chara.get("turn") or 0),
                    "outing_status": self._outing_summary_for_signals(chara, self.preset),
                },
            }
        if command_type == 8 and command_id == 801:
            return {
                "schema": "sweepy_decision_understanding_v1",
                "action": "medic",
                "primary_intent": "condition_recovery",
                "intent_tags": ["condition_recovery", "energy_recovery"],
                "summary": "use medic to clear bad status before training or racing again",
                "signals": {
                    "current_vital": int(chara.get("vital") or 0),
                    "turn": int(chara.get("turn") or 0),
                },
            }
        return {}

    def _training_decision_understanding(self, command, chara, preset):
        idx = TRAINING_COMMANDS.get(int(command.get("command_id") or 0), -1)
        if idx < 0:
            return {}
        stat_name = _COMMAND_IDX_TO_STAT.get(idx, "")
        turn = int(chara.get("turn") or 0)
        progress = max(0.25, min(1.0, float(turn or 0) / 78.0))
        targets = self._expect_attribute_targets(preset, chara, default=[9999, 9999, 9999, 9999, 9999])
        current = float(self._current_stat(chara, idx) or 0.0)
        target_cap = float(targets[idx] if idx < len(targets) else 9999.0) or 9999.0
        # When target is unbounded (>= 9999), there's no "expected at
        # this turn" baseline — set expected_now high enough that the
        # lagging diagnostic never fires. Per "no predestined stats".
        if target_cap >= 9999:
            expected_now = 0.0
        else:
            expected_now = target_cap * progress
        selected_stat_gain = 0.0
        for item in command.get("params_inc_dec_info_array") or []:
            target = STAT_TARGETS.get(item.get("target_type"))
            if target == idx:
                selected_stat_gain += max(0.0, float(item.get("value") or 0.0))
        projected_after = current + selected_stat_gain
        blue_indices = self._desired_blue_target_indices(preset)
        blue_match = idx in blue_indices
        blue_band_before = stat_value_band(current) if blue_match else ""
        blue_band_after = stat_value_band(projected_after) if blue_match else ""
        lagging = bool(expected_now > 0 and current < expected_now)
        partner_bonds = self._bond_map(chara)
        near_rainbow_count = sum(
            1
            for partner_id in command.get("training_partner_array") or []
            if 60 <= int(partner_bonds.get(partner_id, 0) or 0) < 80
        )
        postmortem_bonus = float(command.get("_postmortem_training_bonus") or 0.0)
        race_success_bonus = float(command.get("_race_success_training_bonus") or 0.0)
        race_pressure_bonus = postmortem_bonus + race_success_bonus
        trajectory_bonus = float(command.get("_trajectory_training_bonus") or 0.0)
        trajectory_label = str(command.get("_trajectory_label") or "").strip()
        learned_bonus = float(command.get("_learned_policy_bonus") or 0.0)
        speed_priority_bonus = float(command.get("_speed_priority_bonus") or 0.0)
        checkpoint_pressure_bonus = float(command.get("_checkpoint_pressure_bonus") or 0.0)
        manual_race_specific_demand_bonus = float(command.get("_manual_race_specific_demand_bonus") or 0.0)
        race_hard_floor_bonus = float(command.get("_race_hard_floor_bonus") or 0.0)
        stat_concentration_bonus = float(command.get("_stat_concentration_bonus") or 0.0)
        near_rainbow_bonus = float(command.get("_near_rainbow_bonus") or 0.0)
        first_summer_friendship_bonus = float(command.get("_first_summer_friendship_bonus") or 0.0)
        projection_bonus = float(command.get("_projection_bonus") or 0.0)
        visible_tile_quality = float(command.get("_visible_tile_quality") or 0.0)
        visible_tile_quality_best = float(command.get("_visible_tile_quality_best") or 0.0)
        visible_tile_quality_delta = float(command.get("_visible_tile_quality_delta") or 0.0)
        facility_level, facility_progress, facility_until_next = self._facility_level_info(command, chara)
        facility_level_bonus = float(command.get("_facility_level_bonus") or 0.0)
        facility_triggers_level_up = bool(facility_until_next == 1)
        bond_equity_gate = command.get("_bond_equity_gate") or {}
        spark_multiplier = float(command.get("_desired_parent_spark_training_multiplier") or 1.0)
        overcap_multiplier = self._projected_overcap_multiplier(idx, chara, preset, targets, turn)
        future_stat_relief = self._future_stat_relief(idx, chara, preset)
        future_hp_relief = self._future_hp_relief(chara, preset, max_turn=turn + 2)
        score = float(command.get("_strategy_score") or 0.0)
        second_best = float(command.get("_strategy_second_best_score") or 0.0)
        score_margin = float(command.get("_strategy_score_margin") or (score - second_best))
        intent_tags = []
        if blue_match and current < 1100.0:
            intent_tags.append("blue_target_progress")
        elif blue_match:
            intent_tags.append("blue_target_maintenance")
        if race_pressure_bonus > 0:
            intent_tags.append("race_prep")
        if manual_race_specific_demand_bonus > 0:
            intent_tags.append("manual_race_specific_demand")
        if race_hard_floor_bonus > 0:
            intent_tags.append("race_hard_floor")
        if near_rainbow_count > 0 or near_rainbow_bonus > 0:
            intent_tags.append("rainbow_setup")
        if first_summer_friendship_bonus > 0:
            intent_tags.append("first_summer_friendship")
        if facility_level_bonus > 0:
            intent_tags.append("facility_levelup")
        if bond_equity_gate.get("active"):
            intent_tags.append("bond_equity")
        if lagging:
            intent_tags.append("lagging_stat_recovery")
        if spark_multiplier > 1.0:
            intent_tags.append("late_white_pressure")
        if int(command.get("failure_rate") or 0) <= 5:
            intent_tags.append("low_risk")
        if score_margin > 0.15:
            intent_tags.append("clear_best_tile")
        if visible_tile_quality_delta > 0:
            intent_tags.append("visible_tile_quality")
        primary_intent = next(
            (
                tag
                for tag in (
                    "blue_target_progress",
                    "race_prep",
                    "bond_equity",
                    "first_summer_friendship",
                    "facility_levelup",
                    "visible_tile_quality",
                    "rainbow_setup",
                    "lagging_stat_recovery",
                    "late_white_pressure",
                    "clear_best_tile",
                    "low_risk",
                )
                if tag in intent_tags
            ),
            "immediate_yield",
        )
        summary_parts = []
        if primary_intent == "blue_target_progress":
            summary_parts.append(f"push {stat_name} toward the blue spark band")
        elif primary_intent == "race_prep":
            summary_parts.append(f"raise {stat_name} for an upcoming race")
        elif primary_intent == "bond_equity":
            summary_parts.append(f"train {stat_name} to catch up lagging support bonds")
        elif primary_intent == "first_summer_friendship":
            summary_parts.append(f"accelerate friendship setup in {stat_name} before first summer")
        elif primary_intent == "facility_levelup":
            summary_parts.append(f"train {stat_name} to advance facility level payoff")
        elif primary_intent == "visible_tile_quality":
            summary_parts.append(f"take the strongest visible {stat_name} tile")
        elif primary_intent == "rainbow_setup":
            summary_parts.append(f"train {stat_name} while advancing near-rainbow bonds")
        elif primary_intent == "lagging_stat_recovery":
            summary_parts.append(f"recover a lagging {stat_name} line")
        elif primary_intent == "late_white_pressure":
            summary_parts.append(f"take late output in {stat_name} for white or scenario pressure")
        else:
            summary_parts.append(f"take the strongest available {stat_name} tile")
        if race_pressure_bonus > 0 and primary_intent != "race_prep":
            summary_parts.append("it also helps upcoming race prep")
        if near_rainbow_count > 0 and primary_intent != "rainbow_setup":
            summary_parts.append("it keeps rainbow setup moving")
        if first_summer_friendship_bonus > 0 and primary_intent != "first_summer_friendship":
            summary_parts.append("it helps unlock friendship before first summer")
        if facility_level_bonus > 0 and primary_intent != "facility_levelup":
            summary_parts.append("it advances a facility level-up with enough career left to pay off")
        if bond_equity_gate.get("active") and primary_intent != "bond_equity":
            summary_parts.append("it prevents a support card from falling behind on bond")
        if blue_match and primary_intent != "blue_target_progress":
            summary_parts.append("it still matches the desired blue target")
        summary = "; ".join(summary_parts)
        return {
            "schema": "sweepy_decision_understanding_v1",
            "action": "train",
            "primary_intent": primary_intent,
            "intent_tags": intent_tags,
            "summary": summary,
            "signals": {
                "turn": turn,
                "selected_stat": stat_name,
                "selected_stat_index": idx,
                "strategy_score": round(score, 4),
                "score_margin": round(score_margin, 4),
                "failure_rate": int(command.get("failure_rate") or 0),
                "partner_count": len(command.get("training_partner_array") or []),
                "hint_count": len(set(command.get("tips_event_partner_array") or [])),
                "near_rainbow_count": int(near_rainbow_count),
                "current_stat": round(current, 2),
                "target_cap": round(target_cap, 2),
                "target_ratio": round(current / max(1.0, target_cap), 4),
                "expected_ratio_now": round(current / max(1.0, expected_now), 4),
                "projected_stat_after": round(projected_after, 2),
                "blue_target_match": bool(blue_match),
                "blue_target_band_before": blue_band_before,
                "blue_target_band_after": blue_band_after,
                "blue_target_threshold_gap": round(max(0.0, 1100.0 - current), 2) if blue_match else 0.0,
                "future_guaranteed_stat_gain": round(future_stat_relief, 2),
                "future_hp_relief_next_two_turns": round(future_hp_relief, 2),
                "lagging_for_selected_stat": bool(lagging),
                "postmortem_bonus": round(postmortem_bonus, 4),
                "race_success_bonus": round(race_success_bonus, 4),
                "race_pressure_bonus": round(race_pressure_bonus, 4),
                "trajectory_bonus": round(trajectory_bonus, 4),
                "trajectory_label": trajectory_label,
                "learned_policy_bonus": round(learned_bonus, 4),
                "speed_priority_bonus": round(speed_priority_bonus, 4),
                "checkpoint_pressure_bonus": round(checkpoint_pressure_bonus, 4),
                "manual_race_specific_demand_bonus": round(manual_race_specific_demand_bonus, 4),
                "race_hard_floor_bonus": round(race_hard_floor_bonus, 4),
                "stat_concentration_bonus": round(stat_concentration_bonus, 4),
                "near_rainbow_bonus": round(near_rainbow_bonus, 4),
                "first_summer_friendship_bonus": round(first_summer_friendship_bonus, 4),
                "projection_bonus": round(projection_bonus, 4),
                "visible_tile_quality": round(visible_tile_quality, 3),
                "visible_tile_quality_best": round(visible_tile_quality_best, 3),
                "visible_tile_quality_delta": round(visible_tile_quality_delta, 4),
                "outing_status": self._outing_summary_for_signals(chara, preset),
                "facility_level": facility_level,
                "facility_progress": facility_progress,
                "facility_until_next_level": facility_until_next,
                "facility_triggers_level_up": facility_triggers_level_up,
                "facility_level_bonus": round(facility_level_bonus, 4),
                "bond_equity_gate_active": bool(bond_equity_gate.get("active")),
                "bond_equity_reason": str(bond_equity_gate.get("reason") or ""),
                "bond_equity_target_ids": list(bond_equity_gate.get("target_ids") or []),
                "bond_equity_avg_bond": bond_equity_gate.get("avg_bond", 0),
                "current_rainbow_unlocked_count": int(self._current_rainbow_unlocked_count(chara)),
                "target_rainbow_unlocked_count": int(self._first_summer_friendship_target(turn)),
                "late_white_pressure_multiplier": round(spark_multiplier, 4),
                "projected_overcap_multiplier": round(overcap_multiplier, 4),
                "projected_overcap_risk": bool(overcap_multiplier < 1.0),
            },
        }

    def _score_command(self, command, data, chara, preset):
        turn = int(chara.get("turn") or 0)
        weights = self._period_row(preset.get("score_value"), turn, [0.11, 0.10, 0.006, 0.09])
        base = preset.get("base_score") or [0, 0, 0, 0, 0]
        targets = self._expect_attribute_targets(preset, chara, default=[9999, 9999, 9999, 9999, 9999])
        idx = TRAINING_COMMANDS.get(command.get("command_id"), 0)
        score = float(base[idx] if idx < len(base) else 0)
        w_lv1 = float(weights[0] if len(weights) > 0 else 0.11)
        w_lv2 = float(weights[1] if len(weights) > 1 else 0.10)
        w_energy = float(weights[2] if len(weights) > 2 else 0.006)
        w_hint = float(weights[3] if len(weights) > 3 else 0.09)
        stat_mult = preset.get("stat_value_multiplier") or [0.01, 0.01, 0.01, 0.01, 0.01, 0.005]
        bonds = self._bond_map(chara)
        stat_recreation_partners = self._stat_recreation_partner_ids(preset)
        outing_ready = self._outing_ready_partner_ids(chara, preset)
        stat_recreation_target = self._stat_recreation_target_bond(preset)
        partners = command.get("training_partner_array") or []
        hints = set(command.get("tips_event_partner_array") or [])
        pal_count = 0
        hint_count = 0
        for partner_id in partners:
            bond = bonds.get(partner_id, 0)
            if partner_id in hints:
                hint_count += 1

            if partner_id in stat_recreation_partners:
                if partner_id in outing_ready or bond >= stat_recreation_target:
                    continue
                time_decay = max(0.0, (72 - turn) / 72.0)
                efficiency_boost = 1.0 + (bond / max(1.0, float(stat_recreation_target))) * 0.5
                pal_count += 1
                score += self._pal_score(bond, preset, target_bond=stat_recreation_target) * time_decay * efficiency_boost
                continue

            if bond >= 80:
                continue

            time_decay = max(0.0, (72 - turn) / 72.0)
            efficiency_boost = 1.0 + (bond / 80.0) * 0.5 if bond >= 60 else 1.0
            
            weight = time_decay * efficiency_boost

            if partner_id not in DECK_PARTNERS:
                yield_val = self._npc_score(bond, turn, preset)
                score += yield_val * weight
                continue

            if partner_id == 6:
                pal_count += 1
                yield_val = self._pal_score(bond, preset)
                score += yield_val * weight
                continue

            ratio = min(1.0, bond / 80.0)
            yield_val = w_lv1 + (w_lv2 - w_lv1) * ratio
            score += yield_val * weight
        if hint_count:
            score += w_hint
        for item in command.get("params_inc_dec_info_array") or []:
            value = float(item.get("value") or 0)
            if item.get("target_type") == 10:
                energy_score = value * w_energy
                if int(chara.get("vital") or 0) >= 80 and value < 0:
                    energy_score *= 0.9
                score += energy_score
                continue
            target = STAT_TARGETS.get(item.get("target_type"))
            if target is None:
                continue
            if target == 5:
                continue

            stat_gain_score = value * float(stat_mult[target] if target < len(stat_mult) else 0.01)
            if target == 1:
                stat_gain_score *= stamina_demand_multiplier(
                    self._trainee_style(preset, chara),
                    self._trainee_distance(preset, chara),
                    self._planned_recovery_count(preset),
                )
            # PER-STAT soft-cap: per operator policy, speed/power/wit get
            # cap 1100 (high-priority stats — push to near max); stamina
            # and guts get cap 800 ("just enough for the race schedule").
            # User overrides via `desired_parent_sparks.blue` — any stat
            # listed there gets bumped to 1100 (the blue-spark target).
            # Stats keep climbing past these via race rewards / events /
            # skills, but DIRECT training tapers above the soft cap.
            current_for_stat = float(self._current_stat(chara, target) or 0.0)
            soft_cap = self._per_stat_soft_cap(target, preset, turn=turn)
            hard_cap = float(_tuned_value(preset, "stat_hard_cap", 1200.0))
            if current_for_stat >= hard_cap:
                stat_gain_score *= 0.05
            elif current_for_stat >= soft_cap:
                progress = (current_for_stat - soft_cap) / max(1.0, (hard_cap - soft_cap))
                # Taper from full value at soft cap down to 0.10× at hard cap
                stat_gain_score *= max(0.10, 1.0 - 0.90 * progress)
            cap = float(targets[target] if target < len(targets) else 9999)
            if cap > 0 and target < 5:
                current = self._current_stat(chara, target)
                ratio = current / cap
                if ratio > 1.0:
                    stat_gain_score *= 0.0
                elif ratio > 0.97:
                    stat_gain_score *= 0.35 - ((ratio - 0.97) / 0.03) * 0.25
                elif ratio > 0.94:
                    stat_gain_score *= 0.55 - ((ratio - 0.94) / 0.03) * 0.20
                elif ratio > 0.90:
                    stat_gain_score *= 0.75 - ((ratio - 0.90) / 0.04) * 0.20
                elif ratio > 0.86:
                    stat_gain_score *= 0.85 - ((ratio - 0.86) / 0.04) * 0.10
                elif ratio > 0.82:
                    stat_gain_score *= 0.91 - ((ratio - 0.82) / 0.04) * 0.06
                elif ratio > 0.78:
                    stat_gain_score *= 0.95 - ((ratio - 0.78) / 0.04) * 0.04
                elif ratio > 0.74:
                    stat_gain_score *= 0.98 - ((ratio - 0.74) / 0.04) * 0.03
                elif ratio > 0.70:
                    stat_gain_score *= 1.00 - ((ratio - 0.70) / 0.04) * 0.02
            stat_gain_score *= self._knowledge_multiplier(target, chara, preset, targets, turn)
            score += stat_gain_score
        if pal_count:
            score *= 1.0 + max(0.0, min(1.0, float(preset.get("pal_card_multiplier") or 0.1)))
        # Solo-tile penalty: training with 0 partners is base-output garbage.
        # Operator complaint: S+ 16,116 career T32 picked Speed solo (0
        # partners, lv2 facility, full HP) — wasted turn. Apply a fixed
        # penalty so any tile with at least 1 partner beats a solo tile;
        # if every tile is solo (rare), they all get the same penalty and
        # the best base score still wins.
        partner_array_len = len(command.get("training_partner_array") or [])
        if partner_array_len == 0:
            solo_penalty = float(_tuned_value(preset, "solo_training_penalty", 0.20))
            command["_solo_training_penalty"] = round(solo_penalty, 4)
            score -= solo_penalty
        if preset.get("compensate_failure", True):
            score *= max(0.0, 1.0 - (float(command.get("failure_rate") or 0) / 50.0))
        if idx == 4:
            vital = int(chara.get("vital") or 0)
            max_vital = int(chara.get("max_vital") or 100)
            gain = 0
            for item in command.get("params_inc_dec_info_array") or []:
                if item.get("target_type") == 10:
                    gain = float(item.get("value") or 0)
                    break
            if vital >= max_vital or (gain > 0 and vital + gain > max_vital):
                score *= 0.35 if turn > 72 else 0.75
            elif vital < 85:
                score *= 1.03
        extra = self._extra_weight(idx, turn, preset)
        if extra == -1:
            return -999.0
        if extra < 0 and idx in _COMMAND_IDX_TO_STAT:
            stat_name = _COMMAND_IDX_TO_STAT.get(idx)
            active_cap_stats = self._cap_pursuit_active_stats(preset)
            cap_target = self._cap_pursuit_training_target(preset, stat_name=stat_name, chara=chara)
            if stat_name in active_cap_stats and float(self._current_stat(chara, idx) or 0.0) < cap_target:
                command["_negative_extra_weight_clamped"] = round(float(extra), 4)
                extra = 0.0
        score *= max(0.0, min(2.0, 1.0 + extra))
        score += self._race_heavy_core_floor_adjustment(idx, chara, preset, turn)
        efficiency_bonus = self._race_heavy_training_efficiency_adjustment(command, chara, preset, turn)
        if efficiency_bonus:
            command["_race_heavy_efficiency_bonus"] = round(efficiency_bonus, 4)
            score += efficiency_bonus

        if turn < 60:
            deck_mults = preset.get("_deck_multipliers")
            if deck_mults and len(deck_mults) > idx:
                score *= float(deck_mults[idx])

        # Postmortem-driven race-specific training bias. If the bot has
        # an upcoming scheduled race that historically demanded more of
        # this command's stat, nudge the score upward. Bounded so it
        # influences close calls without overriding the existing scoring.
        postmortem_bonus = self._postmortem_training_bonus(idx, chara, preset)
        if postmortem_bonus:
            command["_postmortem_training_bonus"] = round(postmortem_bonus, 4)
            score += postmortem_bonus

        race_success_bonus = self._race_success_training_bonus(idx, chara, preset)
        if race_success_bonus:
            command["_race_success_training_bonus"] = round(race_success_bonus, 4)
            score += race_success_bonus

        # Hard race-threshold deficit. Bigger than the soft postmortem
        # hint so the bot actually closes gaps for must-win races rather
        # than just nudging in the right direction.
        threshold_deficit_bonus = self._threshold_deficit_bonus(idx, chara, preset)
        if threshold_deficit_bonus:
            command["_threshold_deficit_bonus"] = round(threshold_deficit_bonus, 4)
            score += threshold_deficit_bonus

        scheduled_safety_bonus = self._scheduled_race_safety_training_bonus(command, chara, preset)
        if scheduled_safety_bonus:
            command["_scheduled_race_safety_bonus"] = round(scheduled_safety_bonus, 4)
            score += scheduled_safety_bonus

        # Cap-pursuit: push training toward stats explicitly far below
        # the user's expect_attribute target. Beats partner-count
        # dominance for stats the user told the bot to chase.
        cap_pursuit_bonus = self._cap_pursuit_bonus(idx, chara, preset)
        if cap_pursuit_bonus:
            command["_cap_pursuit_bonus"] = round(cap_pursuit_bonus, 4)
            score += cap_pursuit_bonus

        # User-manual-data target: when user has 3+ winning manual races
        # for this trainee, push training toward stats they actually hit.
        # Strongest signal in the system — derived from the user's
        # observed winning gameplay, not heuristic.
        user_manual_bonus = self._user_manual_target_bonus(idx, chara, preset)
        if user_manual_bonus:
            command["_user_manual_target_bonus"] = round(user_manual_bonus, 4)
            score += user_manual_bonus

        # Per-race manual demand: look up user's median winning stats for
        # the SPECIFIC upcoming scheduled race (e.g., Kikuka Sho stamina
        # target = 380 from 12 user wins). Differs from the trainee-wide
        # aggregate above by preserving race-specific signal.
        race_specific_demand_bonus = self._manual_race_specific_demand_bonus(idx, chara, preset)
        if race_specific_demand_bonus:
            command["_manual_race_specific_demand_bonus"] = round(race_specific_demand_bonus, 4)
            score += race_specific_demand_bonus

        # Race hard floors: e.g., Kikuka Sho stamina must be ≥ 380 by T44
        # or the bot loses regardless of skills. Bonus magnitude up to
        # 0.80 (vs 0.30 cap on the soft demand). Bypasses deck-realism
        # throttle — Kikuka Sho stamina target is non-negotiable.
        race_hard_floor_bonus = self._race_hard_stat_floor_bonus(idx, chara, preset, command)
        if race_hard_floor_bonus:
            command["_race_hard_floor_bonus"] = round(race_hard_floor_bonus, 4)
            score += race_hard_floor_bonus

        # Forward-projection planner. Computes per-stat gap-pressure for
        # upcoming scheduled races (reading race_thresholds.json), factors
        # in the trainee's growth rates and current bond states, and emits
        # a coherent per-tile bonus. Designed to eventually replace the
        # patchwork of competing priority bonuses above. Phase 1 is
        # additive (cap 0.10); Phase 2 raises the cap and lowers
        # competing bonus caps; Phase 3 disables them entirely. Toggle
        # via preset["projection_phase"] (0=off, 1, 2, 3).
        projection_bonus = self._projection_tile_bonus(idx, chara, preset, turn)
        if projection_bonus:
            command["_projection_bonus"] = round(projection_bonus, 4)
            score += projection_bonus

        trajectory_bonus = self._trajectory_training_bonus(idx, chara, preset)
        if trajectory_bonus:
            command["_trajectory_training_bonus"] = round(trajectory_bonus, 4)
            trajectory_prediction = self._trajectory_prediction(chara, preset)
            command["_trajectory_label"] = trajectory_prediction.get("label") if isinstance(trajectory_prediction, dict) else ""
            score += trajectory_bonus

        # Pre-rainbow bond targeting. Training with partners in the
        # 60-79 bond band advances them toward the rainbow threshold
        # (80). Once they cross 80, ALL future trainings with them
        # benefit from the rainbow bonus. Reward this directly so the
        # bot doesn't need to wait for the training_policy_model to
        # learn the weight.
        near_rainbow_bonus = self._near_rainbow_training_bonus(command, chara, turn)
        if near_rainbow_bonus:
            command["_near_rainbow_bonus"] = round(near_rainbow_bonus, 4)
            score += near_rainbow_bonus
        # Within-stat bond drift: when a deck partner is significantly
        # behind others on bond, prefer tiles where that partner appears
        # so it catches up. Without this, one of two Wisdom cards in a
        # 2-Wisdom deck can stall at 72 the whole career (Fine Motion in
        # the S+ 16,116 run) while its peer hits rainbow.
        lagging_bond_bonus = self._lagging_bond_partner_bonus(command, chara, preset, turn)
        if lagging_bond_bonus:
            command["_lagging_bond_bonus"] = round(lagging_bond_bonus, 4)
            score += lagging_bond_bonus
        first_summer_friendship_bonus = self._first_summer_friendship_bonus(command, chara, turn, preset)
        if first_summer_friendship_bonus:
            command["_first_summer_friendship_bonus"] = round(first_summer_friendship_bonus, 4)
            score += first_summer_friendship_bonus
        facility_level_bonus = self._facility_level_training_bonus(command, chara, preset, turn)
        if facility_level_bonus:
            command["_facility_level_bonus"] = round(facility_level_bonus, 4)
            score += facility_level_bonus

        spark_goal_mult = self._desired_parent_spark_training_multiplier(command, chara, preset, turn)
        if spark_goal_mult != 1.0:
            command["_desired_parent_spark_training_multiplier"] = round(spark_goal_mult, 4)

        # --- Stat Priority Architecture ---
        # Speed is always wanted, regardless of spark goal.
        speed_bonus = self._speed_priority_bonus(command, chara, preset, turn)
        if speed_bonus:
            command["_speed_priority_bonus"] = round(speed_bonus, 4)
            score += speed_bonus

        wit_bonus = self._wit_priority_bonus(command, chara, preset, turn)
        if wit_bonus:
            command["_wit_priority_bonus"] = round(wit_bonus, 4)
            score += wit_bonus

        target_closeout_bonus = self._target_closeout_bonus(command, chara, preset, turn)
        if target_closeout_bonus:
            command["_target_closeout_bonus"] = round(target_closeout_bonus, 4)
            score += target_closeout_bonus

        # Stamina + Power priority. These fire only when the trainee is
        # BELOW the race-grade floor for that stat. Stamina decides
        # Kikuka/Tenno Sho Spring/Arima; power decides Derby/Japan Cup.
        # The sim's per-stat training output is biased toward speed (a
        # known sim-only bug), so these bonuses cannot be cleanly tested
        # in-sim. They're sized small (additive, never decay) so worst
        # case they nudge a few extra stamina/power picks per career.
        stamina_bonus = self._stamina_priority_bonus(command, chara, preset, turn)
        if stamina_bonus:
            command["_stamina_priority_bonus"] = round(stamina_bonus, 4)
            score += stamina_bonus
        power_bonus = self._power_priority_bonus(command, chara, preset, turn)
        if power_bonus:
            command["_power_priority_bonus"] = round(power_bonus, 4)
            score += power_bonus

        # Per-stat checkpoint pressure on lagging stats.
        checkpoint_bonus = self._checkpoint_pressure_bonus(command, chara, preset, turn)
        if checkpoint_bonus:
            command["_checkpoint_pressure_bonus"] = round(checkpoint_bonus, 4)
            score += checkpoint_bonus

        lane_balance_bonus = self._race_heavy_lane_balance_bonus(command, chara, preset, turn)
        if lane_balance_bonus:
            command["_race_heavy_lane_balance_bonus"] = round(lane_balance_bonus, 4)
            score += lane_balance_bonus

        # Senior-year stat concentration: push the top-2 stats toward
        # the 1200 cap. The in-game rank score rewards stats-near-cap,
        # so this beats balanced-stat builds for final rank.
        #
        # Gated by overcap multiplier: if this stat is already projected
        # to overshoot its target, shrink the concentration bonus by the
        # same fraction the base score is shrunk. Without this, Wit at
        # 1014 (overcap_mult=0.35) still received +0.26 concentration
        # bonus on top of the shrunken base, which outweighed Speed/Power
        # tiles that had higher raw gain. Observed in S+ 16,116 career
        # T73/T75/T77 where bot picked Wit over higher-base Speed/Guts.
        concentration_bonus = self._stat_concentration_bonus(command, chara, preset, turn)
        if concentration_bonus:
            overcap_mult = self._projected_overcap_multiplier(idx, chara, preset, targets, turn)
            concentration_bonus *= overcap_mult
            command["_stat_concentration_bonus"] = round(concentration_bonus, 4)
            score += concentration_bonus

        learned_bonus = score_training_policy_bonus(command, data, chara, preset)
        if learned_bonus:
            command["_learned_policy_bonus"] = learned_bonus
            score += learned_bonus
        if spark_goal_mult != 1.0:
            score *= spark_goal_mult

        return score

    def _postmortem_training_bonus(self, command_idx, chara, preset):
        """Return a bounded bonus to add to a command score based on
        upcoming-race postmortem demand for this command's stat.

        Returns 0.0 when there's no race_planner, no hints, no upcoming
        races, or no demand for this stat. The bonus is bounded by
        _POSTMORTEM_BONUS_CAP so it can sway borderline picks without
        derailing the existing scoring's clear winners."""
        if not self.race_planner:
            return 0.0
        hints = preset.get("race_specific_stat_hints") if isinstance(preset, dict) else None
        if not hints:
            return 0.0
        scheduled = []
        try:
            scheduled = self.race_planner.scheduled_entries(preset) or []
        except Exception:
            return 0.0
        if not scheduled:
            return 0.0

        try:
            current_turn = int(chara.get("turn") or 0)
        except (TypeError, ValueError):
            return 0.0
        stat_name = _COMMAND_IDX_TO_STAT.get(command_idx)
        if not stat_name:
            return 0.0
        # Normalize the hints dict: postmortem feedback stores program_ids
        # as integers but JSON roundtrips through string keys, so accept
        # both forms.
        normalized_hints = {}
        for key, value in hints.items():
            try:
                normalized_hints[int(key)] = value
            except (TypeError, ValueError):
                continue
        demand = upcoming_race_stat_demand(normalized_hints, scheduled, current_turn)
        stat_demand = float(demand.get(stat_name) or 0)
        if stat_demand <= 0:
            return 0.0
        scaled = min(stat_demand / _POSTMORTEM_DEMAND_FULL_BONUS_AT, 1.0)
        return scaled * _tuned_value(preset, "postmortem_bonus_cap", _POSTMORTEM_BONUS_CAP)

    def _threshold_runtime_root(self):
        """Where race_thresholds.json lives — same dir the postmortems
        and learning reports use. Tied to the race_planner's base_dir
        so it picks up per-instance runtime roots correctly."""
        if not self.race_planner:
            return None
        base_dir = getattr(self.race_planner, "base_dir", None)
        if not base_dir:
            return None
        # base_dir of race_planner points at the project root; postmortems
        # live under uma_runtime/instances/<instance>/postmortems. We need
        # the same instance-scoped path. The cleanest source of truth is
        # the *trace dir* hint on preset, but for now use the same logic
        # the postmortem writer uses by walking the preset's `_runtime_root`
        # if set, otherwise fall back to project base.
        return None  # filled in per-call via preset hint

    def _threshold_deficit_cache(self, chara, preset):
        """Compute (and cache for this turn) the per-stat threshold
        deficit pressure for upcoming races. Returns the cached
        pressure dict {stat: float}. Re-evaluates whenever the turn
        changes."""
        try:
            current_turn = int(chara.get("turn") or 0)
        except (TypeError, ValueError):
            return {}
        if self._threshold_deficit_cache_turn == current_turn:
            return self._threshold_deficit_cache_pressure
        # Reset cache for the new turn.
        self._threshold_deficit_cache_turn = current_turn
        self._threshold_deficit_cache_pressure = {}
        self._threshold_deficit_cache_per_race = []
        if not self.race_planner:
            return {}
        # Resolve runtime root — preset records the per-instance runtime
        # root where postmortems and thresholds are written. Falls back
        # to base_dir/uma_runtime when not set.
        runtime_root = None
        if isinstance(preset, dict):
            runtime_root = preset.get("_runtime_root")
        if not runtime_root:
            base_dir = getattr(self.race_planner, "base_dir", None)
            if base_dir is not None:
                try:
                    from pathlib import Path as _Path
                    runtime_root = _Path(base_dir).parent / "uma_runtime"
                except Exception:
                    runtime_root = None
        if not runtime_root:
            return {}
        thresholds = load_race_thresholds(runtime_root)
        if not thresholds:
            return {}
        try:
            scheduled = self.race_planner.scheduled_entries(preset) or []
        except Exception:
            scheduled = []
        if not scheduled:
            return {}
        current_stats = {
            "speed": self._current_stat(chara, 0),
            "stamina": self._current_stat(chara, 1),
            "power": self._current_stat(chara, 2),
            "guts": self._current_stat(chara, 3),
            "wit": self._current_stat(chara, 4),
        }
        deficits = compute_race_deficits(
            thresholds, scheduled, current_stats, current_turn
        )
        pressure = aggregate_stat_deficit(
            deficits, max_lookahead_turns=_THRESHOLD_DEFICIT_LOOKAHEAD_TURNS
        )
        self._threshold_deficit_cache_pressure = pressure
        self._threshold_deficit_cache_per_race = deficits
        return pressure

    def _cap_pursuit_blue_spark_stats(self, preset):
        """Return the set of stat names the user explicitly wants to
        spark as a parent. Reads `desired_parent_sparks.blue` and
        normalizes to lowercase stat keys. Empty set = no explicit
        blue-spark cap-pursuit.

        See `_cap_pursuit_active_stats` for the union with deck-derived
        stats — the bot autonomously pursues stats with 2+ deck cards
        even when no blue spark is explicitly set.
        """
        if not isinstance(preset, dict):
            return set()
        sparks = preset.get("desired_parent_sparks")
        if not isinstance(sparks, dict):
            return set()
        blue = sparks.get("blue") or []
        if not isinstance(blue, (list, tuple)):
            return set()
        valid_stats = {"speed", "stamina", "power", "guts", "wit"}
        out = set()
        for raw in blue:
            name = str(raw or "").strip().lower()
            if name in valid_stats:
                out.add(name)
        return out

    def _cap_pursuit_deck_derived_stats(self, preset):
        """Stats with 2+ supporting cards in the deck become autonomous
        cap-pursuit targets. The deck IS implicit intent — if the user
        brought 2 Power cards, Power should be pursued; if 0 Stamina
        cards, Stamina should NOT be artificially pushed.

        Friend cards count toward every stat (they train all). A friend-
        plus-one-of-a-stat still counts as "2+" for that stat.

        Returns set of stat names with sufficient deck support.
        """
        counts = self._deck_stat_card_counts(preset)
        return {stat for stat, count in counts.items() if count >= 2}

    def _cap_pursuit_active_stats(self, preset):
        """Union of user-explicit (blue spark) and deck-derived stats.

        Cap-pursuit fires for any stat in this set. The explicit blue
        spark always counts; deck-derived adds stats the deck naturally
        supports so the bot autonomously pursues what's brought.
        """
        return (
            self._cap_pursuit_blue_spark_stats(preset)
            | self._cap_pursuit_deck_derived_stats(preset)
        )

    def _cap_pursuit_training_target(self, preset, stat_name=None, chara=None):
        base_target = _CAP_PURSUIT_TARGET_VALUE
        if stat_name:
            stat_index = {value: key for key, value in _COMMAND_IDX_TO_STAT.items()}.get(stat_name)
            if stat_index is not None:
                targets = self._expect_attribute_targets(
                    preset,
                    chara,
                    default=[_CAP_PURSUIT_TARGET_VALUE] * 5,
                )
                try:
                    expected_target = float(targets[stat_index] if stat_index < len(targets) else 0.0)
                except (TypeError, ValueError):
                    expected_target = 0.0
                if 0.0 < expected_target < 9999.0:
                    base_target = max(base_target, expected_target)
        raw_free_stats = (preset or {}).get("cap_pursuit_free_stats_budget_per_stat")
        if raw_free_stats is None:
            free_stats = 40.0 if self._is_race_heavy_route(preset) else _FREE_STATS_BUDGET_PER_STAT
        else:
            free_stats = float(raw_free_stats or 0.0)
        # When the user's actual target is a hard cap (1200 speed/wit), do
        # not subtract a large "future free stats" budget. Race/event rewards
        # are too noisy to rely on for the final 100 points, so train much
        # closer to the cap before tapering.
        if base_target >= 1200.0:
            free_stats = min(free_stats, 15.0)
        return max(1.0, base_target - max(0.0, free_stats))

    def _cap_pursuit_bonus(self, command_idx, chara, preset):
        """Push training toward stats the user explicitly listed in
        `desired_parent_sparks.blue`. Target: 1100 (the ★★ blue spark
        threshold). NOT driven by `expect_attribute` — that field is
        a leftover from the old "predestined stats" approach and is
        ignored here per user feedback.

        Behavior:
        - If `desired_parent_sparks.blue` is empty → return 0. The
          bot follows the deck's natural flow.
        - If the user listed a stat (e.g., "Power") → guarantee that
          stat reaches 1100 by career end. Bonus magnitude grows from
          a gentle early-career nudge to a late-career hammer.
        - Bonus is 0 once the stat is at or above 1100.

        Why this isn't redundant with the threshold-deficit bonus:
        thresholds come from race-loss postmortems (what the bot needs
        to win races). Cap-pursuit comes from the user's spark goal —
        a parent-farming intent that's independent of race demands.
        """
        try:
            current_turn = int(chara.get("turn") or 0)
        except (TypeError, ValueError):
            return 0.0
        if current_turn < _CAP_PURSUIT_START_TURN:
            return 0.0
        if command_idx not in _COMMAND_IDX_TO_STAT:
            return 0.0
        if not isinstance(preset, dict):
            return 0.0
        active_stats = self._cap_pursuit_active_stats(preset)
        if not active_stats:
            return 0.0
        stat_name = _COMMAND_IDX_TO_STAT.get(command_idx)
        if stat_name not in active_stats:
            return 0.0
        current = float(self._current_stat(chara, command_idx))
        target = self._cap_pursuit_training_target(preset, stat_name=stat_name, chara=chara)
        if current >= target:
            return 0.0
        ratio = current / target
        if ratio >= 1.0:
            return 0.0
        # Time-phased bonus magnitude: gentle nudge early, hammer late.
        # Linearly interpolate the cap from EARLY → LATE between the
        # start turn and the late-career turn.
        if current_turn >= _CAP_PURSUIT_LATE_CAREER_TURN:
            bonus_cap = _CAP_PURSUIT_BONUS_CAP_LATE
        else:
            span = max(1, _CAP_PURSUIT_LATE_CAREER_TURN - _CAP_PURSUIT_START_TURN)
            progress = (current_turn - _CAP_PURSUIT_START_TURN) / span
            bonus_cap = (
                _CAP_PURSUIT_BONUS_CAP_EARLY
                + (_CAP_PURSUIT_BONUS_CAP_LATE - _CAP_PURSUIT_BONUS_CAP_EARLY) * progress
            )
        # Deficit scaling: ratio at/below FULL_BONUS_RATIO gets bonus_cap,
        # linearly falls off to 0 at ratio=1.0.
        if ratio <= _CAP_PURSUIT_FULL_BONUS_RATIO:
            return bonus_cap
        falloff = (1.0 - ratio) / (1.0 - _CAP_PURSUIT_FULL_BONUS_RATIO)
        return bonus_cap * falloff

    def _user_manual_target_stats(self, chara, preset):
        """Look up the user's median winning stats relevant to the current
        trainee. Two-tier:

        1. **Exact-trainee match**: if the user has 3+ winning manual
           races as this exact card_id, aggregate from those.
        2. **Attribute-matched cross-trainee fallback**: otherwise, look
           at ALL user wins where the source trainee shared this trainee's
           running style (and optionally distance focus). Filters out
           stamina-recovery-unique source trainees when the current
           trainee lacks the same unique (so stamina targets don't get
           dragged down).

        Returns dict {stat: median_winning_value} or {} on insufficient data.
        """
        if not self.race_planner or not getattr(self.race_planner, "base_dir", None):
            return {}
        card_id = (chara or {}).get("card_id")
        if not card_id:
            run_context = (preset or {}).get("_run_context") or {}
            card_id = run_context.get("trainee_card_id")
        if not card_id:
            return {}
        runtime_root = None
        if isinstance(preset, dict):
            runtime_root = preset.get("_runtime_root")
        if not runtime_root:
            from pathlib import Path as _Path
            base_dir = self.race_planner.base_dir
            try:
                runtime_root = _Path(base_dir).parent / "uma_runtime"
            except Exception:
                runtime_root = None
        if not runtime_root:
            return {}
        data = load_manual_race_data(runtime_root)
        if not data:
            return {}

        # Tier 1: exact-trainee aggregation.
        exact = aggregate_user_targets_for_trainee(data, card_id, min_wins=_USER_MANUAL_MIN_WINS)
        if exact:
            return exact

        # Tier 2: attribute-matched cross-trainee fallback.
        style = self._trainee_style(preset, chara)
        try:
            current_card_id = int(card_id)
        except (TypeError, ValueError):
            current_card_id = None
        has_recovery_unique = (
            current_card_id is not None and current_card_id in STAMINA_RECOVERY_UNIQUE_CARDS
        )
        return aggregate_user_targets_by_attributes(
            data,
            style=style,
            current_trainee_card_id=current_card_id,
            current_trainee_has_recovery_unique=has_recovery_unique,
            min_wins=_USER_MANUAL_MIN_WINS,
        )

    def _deck_stat_card_counts(self, preset):
        """Count deck cards per stat type for the deck-realism throttle.

        Returns dict {stat_name: card_count} where card_count is the
        number of support cards whose type primarily trains that stat.
        Friend cards count toward every stat (they train any).
        """
        raw_counts = (preset or {}).get("_deck_type_counts")
        if isinstance(raw_counts, list) and len(raw_counts) >= 5 and any(raw_counts[:5]):
            keys = ("speed", "stamina", "power", "guts", "wit")
            return {
                key: int(raw_counts[index] or 0)
                for index, key in enumerate(keys)
            }
        run_context = (preset or {}).get("_run_context") or {}
        cards = run_context.get("support_cards") or []
        if not isinstance(cards, list):
            return {}
        type_to_stat = {
            "speed": "speed", "stamina": "stamina", "power": "power",
            "guts": "guts", "wit": "wit", "wisdom": "wit",
            "wiz": "wit", "int": "wit", "intelligence": "wit",
        }
        counts = {"speed": 0, "stamina": 0, "power": 0, "guts": 0, "wit": 0}
        for card in cards:
            if not isinstance(card, dict):
                continue
            card_type = str(card.get("type") or "").strip().lower()
            stat = type_to_stat.get(card_type)
            if stat:
                counts[stat] += 1
            elif card_type in ("friend", "pal"):
                # Friend cards train every stat — boost all
                for s in counts:
                    counts[s] += 1
        return counts

    def _user_manual_target_bonus(self, command_idx, chara, preset):
        """Push training toward stats the user actually hit when winning
        with this trainee. Strongest signal in the system because it's
        derived from the user's actual successful gameplay.

        Behavior:
        - When user has 3+ winning manual races for this trainee:
          look up the median winning stat per stat. For the current
          command's stat, if current value < user's median, push training.
        - Bonus scales with deficit, capped at _USER_MANUAL_BONUS_CAP.
        - Returns 0 when no manual data exists for this trainee.

        This bonus is INDEPENDENT of `desired_parent_sparks.blue` —
        it fires whenever the user has historical winning data for the
        current trainee, regardless of whether they've explicitly set
        a spark target.
        """
        try:
            current_turn = int(chara.get("turn") or 0)
        except (TypeError, ValueError):
            return 0.0
        if current_turn < _CAP_PURSUIT_START_TURN:
            return 0.0
        if command_idx not in _COMMAND_IDX_TO_STAT:
            return 0.0
        stat_name = _COMMAND_IDX_TO_STAT.get(command_idx)
        if not stat_name:
            return 0.0
        targets = self._user_manual_target_stats(chara, preset)
        target = targets.get(stat_name)
        if not target or target <= 0:
            return 0.0
        current = float(self._current_stat(chara, command_idx))
        if current >= target:
            return 0.0
        ratio = current / float(target)
        if ratio >= 1.0:
            return 0.0
        # Deck-realism throttle. If the current deck has no cards
        # supporting this stat, the user's manual target is likely
        # unreachable — don't waste training cycles pursuing it. Card
        # counts: 0 = no support → 30% bonus, 1 = minimal → 70%, 2+ =
        # full bonus.
        deck_counts = self._deck_stat_card_counts(preset)
        deck_card_count = deck_counts.get(stat_name, 0)
        if deck_card_count <= 0:
            deck_realism = 0.3
        elif deck_card_count == 1:
            deck_realism = 0.7
        else:
            deck_realism = 1.0

        if ratio <= _USER_MANUAL_FULL_BONUS_RATIO:
            return _USER_MANUAL_BONUS_CAP * deck_realism
        falloff = (1.0 - ratio) / (1.0 - _USER_MANUAL_FULL_BONUS_RATIO)
        return _USER_MANUAL_BONUS_CAP * falloff * deck_realism

    def _manual_race_specific_demand_bonus(self, command_idx, chara, preset):
        """Apply per-race stat pressure based on the user's median winning
        stats for upcoming scheduled races.

        Differs from `_postmortem_training_bonus` (which is driven by races
        the BOT has lost) by being driven by races the USER has WON — so it
        produces a positive baseline target even when the bot has never
        recorded a postmortem on that race.

        Differs from `_user_manual_target_bonus` (which collapses across
        all of a trainee's wins into one stat profile) by preserving the
        per-race signal — Kikuka Sho stamina demand isn't diluted by Mile
        race stat profiles.

        Returns 0 unless:
        - There's an upcoming scheduled race within the lookahead window,
        - The user has 2+ wins on that race (exact card or cross-trainee),
        - Current stat is below user's median winning value.

        Bonus scales with (a) deficit ratio and (b) race proximity — closer
        races push harder. Capped at `_RACE_SPECIFIC_DEMAND_BONUS_CAP`.
        """
        if not self.race_planner:
            return 0.0
        stat_name = _COMMAND_IDX_TO_STAT.get(command_idx)
        if not stat_name:
            return 0.0
        try:
            current_turn = int(chara.get("turn") or 0)
        except (TypeError, ValueError):
            return 0.0
        if current_turn < _CAP_PURSUIT_START_TURN:
            return 0.0
        base_dir = getattr(self.race_planner, "base_dir", None)
        if not base_dir:
            return 0.0
        runtime_root = None
        if isinstance(preset, dict):
            runtime_root = preset.get("_runtime_root")
        if not runtime_root:
            from pathlib import Path as _Path
            try:
                runtime_root = _Path(base_dir).parent / "uma_runtime"
            except Exception:
                return 0.0
        data = load_manual_race_data(runtime_root)
        if not data:
            return 0.0

        try:
            scheduled = self.race_planner.scheduled_entries(preset) or []
        except Exception:
            return 0.0
        if not scheduled:
            return 0.0

        card_id = (chara or {}).get("card_id")
        if not card_id:
            run_context = (preset or {}).get("_run_context") or {}
            card_id = run_context.get("trainee_card_id")
        try:
            current_card_id = int(card_id) if card_id else None
        except (TypeError, ValueError):
            current_card_id = None
        has_recovery_unique = (
            current_card_id is not None and current_card_id in STAMINA_RECOVERY_UNIQUE_CARDS
        )
        style = self._trainee_style(preset, chara)
        current = float(self._current_stat(chara, command_idx) or 0.0)

        deck_counts = self._deck_stat_card_counts(preset)
        deck_card_count = deck_counts.get(stat_name, 0)
        if deck_card_count <= 0:
            deck_realism = 0.3
        elif deck_card_count == 1:
            deck_realism = 0.7
        else:
            deck_realism = 1.0

        best_bonus = 0.0
        for entry in scheduled:
            try:
                race_turn = int(entry.get("turn") or 0)
                program_id = int(entry.get("program_id") or 0)
            except (TypeError, ValueError):
                continue
            if not program_id:
                continue
            # Only consider races in the lookahead window (future only).
            turns_until = race_turn - current_turn
            if turns_until < 0 or turns_until > _RACE_SPECIFIC_DEMAND_LOOKAHEAD_TURNS:
                continue

            targets = aggregate_race_specific_targets(
                data,
                program_id,
                current_trainee_card_id=current_card_id,
                current_trainee_has_recovery_unique=has_recovery_unique,
                style=style,
                min_wins=_RACE_SPECIFIC_DEMAND_MIN_WINS,
            )
            if not targets:
                continue
            target = targets.get(stat_name)
            if not target or target <= 0:
                continue
            if current >= target:
                continue

            ratio = current / float(target)
            if ratio >= 1.0:
                continue
            # Deficit scaling: full bonus at <=65% of target, linear falloff to 0 at 100%.
            if ratio <= _RACE_SPECIFIC_DEMAND_FULL_BONUS_RATIO:
                deficit_factor = 1.0
            else:
                deficit_factor = (1.0 - ratio) / (1.0 - _RACE_SPECIFIC_DEMAND_FULL_BONUS_RATIO)
            # Proximity scaling: race within 3 turns = full, 4-8 = 0.7, 9-12 = 0.4.
            if turns_until <= 3:
                proximity_factor = 1.0
            elif turns_until <= 8:
                proximity_factor = 0.7
            else:
                proximity_factor = 0.4

            bonus = (
                _tuned_value(preset, "race_specific_demand_cap", _RACE_SPECIFIC_DEMAND_BONUS_CAP)
                * deficit_factor
                * proximity_factor
                * deck_realism
            )
            if bonus > best_bonus:
                best_bonus = bonus

        return best_bonus

    def _projection_tile_bonus(self, command_idx, chara, preset, turn):
        """Bridge to `career_bot.projection.tile_bonus_from_projection`.

        Caches the per-turn projection so we don't rebuild it for every
        scored tile. Returns 0 when projection_phase is 0/unset.
        """
        if not _projection_enabled(preset):
            return 0.0
        try:
            t = int(turn or chara.get("turn") or 0)
        except (TypeError, ValueError):
            return 0.0
        cache_key = (id(preset), t)
        if getattr(self, "_cached_projection_key", None) != cache_key:
            from pathlib import Path as _P
            project_root = str(_P(__file__).resolve().parents[2])
            try:
                self._cached_projection = _build_projection(preset, chara, t, project_root)
            except Exception as exc:  # noqa: BLE001
                self._cached_projection = {"enabled": False, "error": str(exc)}
            self._cached_projection_key = cache_key
        projection = self._cached_projection or {}
        if not projection.get("enabled"):
            return 0.0
        primary_stat = _COMMAND_IDX_TO_STAT.get(int(command_idx or 0))
        if not primary_stat:
            return 0.0
        return _tile_bonus_from_projection(projection, primary_stat)

    def _race_hard_stat_floor_bonus(self, command_idx, chara, preset):
        """Hard-floor enforcement for race-critical stats.

        Unlike `_manual_race_specific_demand_bonus` (a soft bias capped at
        0.30 and throttled by deck composition), this fires only for
        races in `_RACE_HARD_STAT_FLOORS` (or preset-level `race_hard_floors`)
        and projects whether the bot will REACH the floor by race time.
        If projection falls short, the bonus ramps to as much as 0.80 —
        well above any other bonus — and BYPASSES the deck-realism throttle.

        The intent: if Kikuka Sho is on the schedule and the user requires
        stamina ≥ 380, the bot prioritizes stamina training over almost
        everything else once the projection shows a shortfall.

        Returns 0 unless an upcoming race in the floor map can't be met
        by current pace.
        """
        if not self.race_planner:
            return 0.0
        stat_name = _COMMAND_IDX_TO_STAT.get(command_idx)
        if not stat_name:
            return 0.0
        try:
            current_turn = int(chara.get("turn") or 0)
        except (TypeError, ValueError):
            return 0.0
        if current_turn < _CAP_PURSUIT_START_TURN:
            return 0.0

        # Floors come from preset first (operator-configurable), then
        # fall back to the module-level defaults. Preset format:
        # race_hard_floors: { "168": { "stamina": 380 }, ... }
        floors_map = {}
        preset_floors = (preset or {}).get("race_hard_floors")
        if isinstance(preset_floors, dict):
            for pid_key, row in preset_floors.items():
                try:
                    floors_map[int(pid_key)] = dict(row) if isinstance(row, dict) else {}
                except (TypeError, ValueError):
                    continue
        for pid, row in _RACE_HARD_STAT_FLOORS.items():
            floors_map.setdefault(pid, dict(row))
        if not floors_map:
            return 0.0

        try:
            scheduled = self.race_planner.scheduled_entries(preset) or []
        except Exception:
            return 0.0
        if not scheduled:
            return 0.0
        scheduled_turns = set()
        for scheduled_entry in scheduled:
            try:
                scheduled_turn = int((scheduled_entry or {}).get("turn") or 0)
            except (TypeError, ValueError):
                continue
            if scheduled_turn > current_turn:
                scheduled_turns.add(scheduled_turn)

        current = float(self._current_stat(chara, command_idx) or 0.0)

        best_bonus = 0.0
        for entry in scheduled:
            try:
                race_turn = int(entry.get("turn") or 0)
                program_id = int(entry.get("program_id") or 0)
            except (TypeError, ValueError):
                continue
            if not program_id:
                continue
            floor_row = floors_map.get(program_id)
            if not floor_row:
                continue
            required = floor_row.get(stat_name)
            if not required or required <= 0:
                continue
            turns_until = race_turn - current_turn
            if turns_until < 0 or turns_until > _RACE_HARD_FLOOR_LOOKAHEAD_TURNS:
                continue
            if current >= float(required):
                continue  # already at floor — no pressure needed

            # Project: how much stat can we gain in `turns_until` turns
            # if we spent a typical fraction of them on this stat?
            projected_gain = (
                turns_until
                * _RACE_HARD_FLOOR_PROJECTED_GAIN_PER_TURN
                * _RACE_HARD_FLOOR_TRAINING_FRACTION
            )
            projected = current + projected_gain
            if projected >= float(required):
                continue  # on pace — no need to override

            deficit = float(required) - projected
            # Deficit factor scales with how short we'll fall; saturates
            # so even moderate gaps still get a strong push.
            deficit_factor = min(1.0, deficit / max(1.0, float(required) * 0.4))
            # Urgency: race closer = more urgent. Linear ramp from 0.4
            # at lookahead-max to 1.0 at race time.
            span = max(1, _RACE_HARD_FLOOR_LOOKAHEAD_TURNS)
            urgency_factor = max(0.4, 1.0 - (max(0, turns_until - 1) / span))
            bonus = _RACE_HARD_FLOOR_BONUS_CAP * deficit_factor * urgency_factor
            if bonus > best_bonus:
                best_bonus = bonus

        return best_bonus

    def _race_hard_stat_floor_bonus(self, command_idx, chara, preset, command=None):
        """Hard-floor enforcement that counts side-stat training gains.

        The legacy implementation only credited the primary training stat.
        In a 2 Speed / 2 Wit / 1 Power / Riko deck, stamina often comes from
        Power side-gains and Riko events, so primary-only pressure still let
        the bot enter Kikuka/Tenno Spring short on stamina.
        """
        if not self.race_planner:
            return 0.0
        command_stat_gains = self._training_stat_gain_map(command) if command else {}
        if not command_stat_gains:
            stat_name = _COMMAND_IDX_TO_STAT.get(command_idx)
            command_stat_gains = {stat_name: 10.0} if stat_name else {}
        if not command_stat_gains:
            return 0.0
        try:
            current_turn = int(chara.get("turn") or 0)
        except (TypeError, ValueError):
            return 0.0
        if current_turn < _CAP_PURSUIT_START_TURN:
            return 0.0

        floors_map = {}
        preset_floors = (preset or {}).get("race_hard_floors")
        if isinstance(preset_floors, dict):
            for pid_key, row in preset_floors.items():
                try:
                    floors_map[int(pid_key)] = dict(row) if isinstance(row, dict) else {}
                except (TypeError, ValueError):
                    continue
        for pid, row in _RACE_HARD_STAT_FLOORS.items():
            floors_map.setdefault(pid, dict(row))
        if not floors_map:
            return 0.0

        try:
            scheduled = self.race_planner.scheduled_entries(preset) or []
        except Exception:
            return 0.0
        if not scheduled:
            return 0.0

        scheduled_turns = set()
        for scheduled_entry in scheduled:
            try:
                scheduled_turn = int((scheduled_entry or {}).get("turn") or 0)
            except (TypeError, ValueError):
                continue
            if scheduled_turn > current_turn:
                scheduled_turns.add(scheduled_turn)

        stat_to_command_idx = {value: key for key, value in _COMMAND_IDX_TO_STAT.items()}
        best_bonus = 0.0
        for entry in scheduled:
            try:
                race_turn = int(entry.get("turn") or 0)
                program_id = int(entry.get("program_id") or 0)
            except (TypeError, ValueError):
                continue
            floor_row = floors_map.get(program_id)
            if not floor_row:
                continue
            turns_until = race_turn - current_turn
            if turns_until < 0 or turns_until > _RACE_HARD_FLOOR_LOOKAHEAD_TURNS:
                continue
            blocked_turns = sum(1 for scheduled_turn in scheduled_turns if current_turn < scheduled_turn < race_turn)
            projection_slots = max(0.0, float(turns_until - blocked_turns))
            entry_bonus = 0.0
            for stat_name, command_gain in command_stat_gains.items():
                required = floor_row.get(stat_name)
                if not required or required <= 0:
                    continue
                stat_idx = stat_to_command_idx.get(stat_name, command_idx)
                current = float(self._current_stat(chara, stat_idx) or 0.0)
                if current >= float(required):
                    continue
                projected_gain = (
                    projection_slots
                    * _RACE_HARD_FLOOR_PROJECTED_GAIN_PER_TURN
                    * _RACE_HARD_FLOOR_TRAINING_FRACTION
                )
                projected = current + projected_gain
                if projected >= float(required):
                    continue
                deficit = float(required) - projected
                deficit_factor = min(1.0, deficit / max(1.0, float(required) * 0.4))
                span = max(1, _RACE_HARD_FLOOR_LOOKAHEAD_TURNS)
                urgency_factor = max(0.4, 1.0 - (max(0, turns_until - 1) / span))
                gain_factor = min(1.35, max(0.45, float(command_gain or 0.0) / 10.0))
                bonus = _RACE_HARD_FLOOR_BONUS_CAP * deficit_factor * urgency_factor * gain_factor
                entry_bonus += max(0.0, bonus)
            if entry_bonus > best_bonus:
                best_bonus = entry_bonus
        return min(_RACE_HARD_FLOOR_BONUS_CAP, best_bonus)

    def _scheduled_race_safety_training_bonus(self, command, chara, preset):
        """Generic must-win pressure for the next scheduled race.

        The postmortem/manual-data paths are strong once the bot has
        enough losses for a specific race. This rail is earlier and more
        direct: every calendar race is mandatory, so if projected stats
        are below the static race profile, commands that actually gain the
        deficient stat get a large bounded bonus before the race arrives.
        """
        if not self.race_planner or not bool((preset or {}).get("scheduled_race_clean_record_mode", True)):
            return 0.0
        if isinstance(command, int):
            stat_name = _COMMAND_IDX_TO_STAT.get(command)
            command_stat_gains = {stat_name: 18.0} if stat_name else {}
        else:
            command_stat_gains = self._training_stat_gain_map(command)
        if not command_stat_gains:
            return 0.0
        try:
            current_turn = int(chara.get("turn") or 0)
        except (TypeError, ValueError):
            return 0.0
        try:
            raw_lookahead = int((preset or {}).get("scheduled_race_safety_training_lookahead_turns") or 0)
        except (TypeError, ValueError):
            raw_lookahead = 0
        lookahead = max(raw_lookahead, _SCHEDULED_RACE_SAFETY_LOOKAHEAD_TURNS)
        try:
            scheduled = self.race_planner.scheduled_entries(preset) or []
        except Exception:
            return 0.0
        if not scheduled:
            return 0.0

        scheduled_turns = set()
        for scheduled_entry in scheduled:
            try:
                scheduled_turn = int((scheduled_entry or {}).get("turn") or 0)
            except (TypeError, ValueError):
                continue
            if scheduled_turn > current_turn:
                scheduled_turns.add(scheduled_turn)

        raw_gain_map = (preset or {}).get("scheduled_race_projected_gain_per_turn")
        try:
            requirement_scale = float((preset or {}).get("scheduled_race_safety_requirement_scale") or 0.94)
        except (TypeError, ValueError):
            requirement_scale = 0.94
        requirement_scale = max(0.96, requirement_scale)
        try:
            raw_cap = float((preset or {}).get("scheduled_race_safety_bonus_cap") or 0.0)
        except (TypeError, ValueError):
            raw_cap = 0.0
        cap = max(raw_cap, _SCHEDULED_RACE_SAFETY_BONUS_CAP)
        try:
            raw_critical_cap = float((preset or {}).get("scheduled_race_safety_critical_bonus_cap") or 0.0)
        except (TypeError, ValueError):
            raw_critical_cap = 0.0
        critical_cap = max(raw_critical_cap, _SCHEDULED_RACE_SAFETY_CRITICAL_BONUS_CAP, cap)
        best_bonus = 0.0
        max_allowed_bonus = cap
        state = {"data": {"chara_info": chara or {}}}
        stat_to_command_idx = {value: key for key, value in _COMMAND_IDX_TO_STAT.items()}
        for entry in scheduled:
            try:
                race_turn = int(entry.get("turn") or 0)
                program_id = int(entry.get("program_id") or 0)
            except (TypeError, ValueError):
                continue
            turns_until = race_turn - current_turn
            if turns_until < 1 or turns_until > lookahead:
                continue
            if not program_id:
                continue
            try:
                check = self.race_planner.stamina_for_program(state, preset, program_id, entry)
            except Exception:
                check = {}
            grade = str((entry or {}).get("type") or (check or {}).get("grade") or "").upper()
            distance = str((entry or {}).get("distance") or (check or {}).get("distance") or "").strip().lower()
            # Prefer observed/manual race thresholds when available. The
            # generic stamina estimator can inflate all-stat requirements
            # for short/mile races, which makes the bot tunnel Speed and
            # stop training the actual deck-supported output stats.
            requirements = dict(
                (check or {}).get("manual_threshold_requirements")
                or (check or {}).get("fallback_threshold_requirements")
                or (check or {}).get("requirements")
                or {}
            )
            if not requirements:
                continue
            blocked_turns = sum(1 for scheduled_turn in scheduled_turns if current_turn < scheduled_turn < race_turn)
            training_slots = max(0, turns_until - blocked_turns)
            try:
                slot_floor = float((preset or {}).get("scheduled_race_projection_training_slot_floor") or 0.62)
            except (TypeError, ValueError):
                slot_floor = 0.62
            if grade == "G1" and distance == "long":
                # Dense 37-race calendars make the generic floor too
                # optimistic for Kikuka/Tenno Spring. Use actual non-race
                # slots with only a small floor so the bot starts fixing
                # stamina/power before the race wall is already here.
                projection_slots = max(float(training_slots), float(turns_until) * 0.25)
            else:
                projection_slots = max(float(training_slots), float(turns_until) * max(0.0, min(1.0, slot_floor)))
            for stat_name, command_gain in command_stat_gains.items():
                required_scale = requirement_scale
                if grade == "G1":
                    required_scale = max(required_scale, 1.0)
                elif grade == "G2":
                    required_scale = max(required_scale, 0.98)
                required = float(requirements.get(stat_name) or 0.0) * required_scale
                if required <= 0:
                    continue
                current = float(self._current_stat(chara, stat_to_command_idx.get(stat_name, -1)) or 0.0)
                raw_gain = (
                    raw_gain_map.get(stat_name)
                    if isinstance(raw_gain_map, dict)
                    else _SCHEDULED_RACE_PROJECTED_GAIN_PER_TURN.get(stat_name, 7.0)
                )
                try:
                    gain_per_turn = float(raw_gain)
                except (TypeError, ValueError):
                    gain_per_turn = _SCHEDULED_RACE_PROJECTED_GAIN_PER_TURN.get(stat_name, 7.0)
                if gain_per_turn <= 0:
                    gain_per_turn = _SCHEDULED_RACE_PROJECTED_GAIN_PER_TURN.get(stat_name, 7.0)
                # Race-heavy calendars can have long calendar distance but very
                # few actual training opportunities. Project from available
                # non-race slots, but keep a floor so dense calendars do not
                # collapse into "only Speed is urgent" tunnel vision.
                projected = current + (projection_slots * gain_per_turn)
                if projected >= required:
                    continue
                deficit = required - projected
                deficit_ratio = deficit / max(1.0, required)
                deficit_factor = min(1.0, deficit_ratio / _SCHEDULED_RACE_SAFETY_FULL_DEFICIT_RATIO)
                proximity_factor = max(0.35, 1.0 - (max(0, turns_until - 1) / max(1.0, float(lookahead))))
                grade_factor = 1.2 if grade == "G1" else 1.1 if grade == "G2" else 1.0 if grade == "G3" else 0.7
                if stat_name == "stamina" and distance == "long":
                    # Long races need stamina built before dense race blocks;
                    # a late-only ramp cannot recover once the schedule is packed.
                    proximity_factor = max(proximity_factor, 0.85)
                    grade_factor = max(grade_factor, 1.45 if grade == "G1" else 1.2)
                command_gain_factor = max(0.35, min(1.0, float(command_gain) / 18.0))
                local_cap = critical_cap if grade == "G1" and (turns_until <= 4 or distance == "long") else cap
                max_allowed_bonus = max(max_allowed_bonus, local_cap)
                bonus = local_cap * deficit_factor * proximity_factor * grade_factor * command_gain_factor
                if bonus > best_bonus:
                    best_bonus = bonus
        return min(max_allowed_bonus, best_bonus)

    def _threshold_deficit_bonus(self, command_idx, chara, preset):
        """Hard-target training bonus.

        The companion to soft postmortem hints: when projected stats
        fall below the threshold needed to win an upcoming race, push
        training toward the deficient stat with a larger-than-soft-hint
        bonus. This is the "no more losses" lever: the bot stops being
        merely nudged toward higher stats and starts being *pressured*.

        Bonus magnitude:
            full_bonus_at_200pt_deficit × _THRESHOLD_DEFICIT_BONUS_CAP
            (capped — distant or trivial deficits stay small)
        """
        if not self.race_planner:
            return 0.0
        stat_name = _COMMAND_IDX_TO_STAT.get(command_idx)
        if not stat_name:
            return 0.0
        pressure = self._threshold_deficit_cache(chara, preset)
        stat_pressure = float(pressure.get(stat_name) or 0)
        if stat_pressure <= 0:
            return 0.0
        scaled = min(stat_pressure / _THRESHOLD_DEFICIT_FULL_BONUS_AT, 1.0)
        return scaled * _THRESHOLD_DEFICIT_BONUS_CAP

    def _race_success_training_bonus(self, command_idx, chara, preset):
        """Bounded stat bonus from historically successful versions of
        upcoming races.

        If the corpus says "we usually won this race around 820 Power /
        760 Speed by this point" and the current career is below those
        bands, nudge the corresponding training command. This learns
        from the full run corpus instead of only from explicit loss
        postmortems.
        """
        if not self.race_planner:
            return 0.0
        hints = preset.get("race_specific_success_hints") if isinstance(preset, dict) else None
        if not hints:
            return 0.0
        try:
            scheduled = self.race_planner.scheduled_entries(preset) or []
        except Exception:
            scheduled = []
        if not scheduled:
            return 0.0
        try:
            current_turn = int(chara.get("turn") or 0)
        except (TypeError, ValueError):
            return 0.0
        stat_name = _COMMAND_IDX_TO_STAT.get(command_idx)
        if not stat_name:
            return 0.0
        current_stats = {
            "speed": self._current_stat(chara, 0),
            "stamina": self._current_stat(chara, 1),
            "power": self._current_stat(chara, 2),
            "guts": self._current_stat(chara, 3),
            "wit": self._current_stat(chara, 4),
        }
        demand = upcoming_race_success_demand(
            hints,
            scheduled,
            current_turn=current_turn,
            current_stats=current_stats,
        )
        stat_demand = float(demand.get(stat_name) or 0)
        if stat_demand <= 0:
            return 0.0
        scaled = min(stat_demand / _RACE_SUCCESS_DEMAND_FULL_BONUS_AT, 1.0)
        return scaled * _tuned_value(preset, "race_success_bonus_cap", _RACE_SUCCESS_BONUS_CAP)

    def _trajectory_prediction(self, chara, preset):
        if not isinstance(preset, dict):
            return {}
        centroids = preset.get("trajectory_centroids") or {}
        if not centroids:
            return {}
        current_stats = {
            "speed": self._current_stat(chara, 0),
            "stamina": self._current_stat(chara, 1),
            "power": self._current_stat(chara, 2),
            "guts": self._current_stat(chara, 3),
            "wit": self._current_stat(chara, 4),
            "hp": float(chara.get("vital") or 0),
            "skill_point": self._current_stat(chara, 5),
        }
        try:
            return predict_trajectory(centroids, current_stats, int(chara.get("turn") or 0)) or {}
        except Exception:
            return {}

    def _trajectory_training_bonus(self, command_idx, chara, preset):
        prediction = self._trajectory_prediction(chara, preset)
        label = str((prediction or {}).get("label") or "")
        if label not in {"tracking_bottom", "ambiguous"}:
            return 0.0
        checkpoint = (prediction or {}).get("checkpoint")
        if checkpoint is None:
            return 0.0
        centroids = (preset or {}).get("trajectory_centroids") or {}
        checkpoint_row = ((centroids.get("checkpoints") or {}).get(str(checkpoint)) or {})
        top_centroid = checkpoint_row.get("top_centroid") or {}
        stat_name = _COMMAND_IDX_TO_STAT.get(command_idx)
        if not stat_name:
            return 0.0
        target = float(top_centroid.get(stat_name) or 0.0)
        if target <= 0:
            return 0.0
        current = float(self._current_stat(chara, command_idx) or 0.0)
        deficit = target - current
        if deficit <= 0:
            return 0.0
        confidence = float((prediction or {}).get("confidence") or 0.0)
        if label == "tracking_bottom":
            pressure = max(0.55, confidence)
        else:
            pressure = max(0.20, confidence * 0.5)
        scaled = min(deficit / _TRAJECTORY_DEMAND_FULL_BONUS_AT, 1.0)
        return scaled * pressure * _TRAJECTORY_BONUS_CAP

    def _current_run_mode(self, chara, preset):
        policy = (preset or {}).get("run_mode_policy") or {}
        if not bool(policy.get("enabled", True)):
            return "neutral"
        prediction = self._trajectory_prediction(chara, preset)
        label = str((prediction or {}).get("label") or "")
        confidence = float((prediction or {}).get("confidence") or 0.0)
        if label == "tracking_top" and confidence >= float(policy.get("preserve_confidence") or 0.62):
            return "preserve"
        if label == "tracking_bottom" and confidence >= float(policy.get("push_confidence") or 0.45):
            return "push"
        return "neutral"

    def _near_rainbow_training_bonus(self, command, chara, turn):
        """Bonus for training with partners whose bond is in the
        pre-rainbow band (60-79). Crossing 80 unlocks the rainbow
        multiplier on every future training with that partner — so
        this is essentially a small "investment" lift that pays off
        for the rest of the career.

        Capped per-command at _NEAR_RAINBOW_BONUS_CAP and tapered in
        the senior year (turn > 60) where the remaining career is too
        short to justify trading stat-push turns for bonding."""
        partners = command.get("training_partner_array") or []
        if not partners:
            return 0.0
        bonds = self._bond_map(chara)
        stat_recreation_partners = self._stat_recreation_partner_ids(getattr(self, "preset", {}) or {})
        outing_ready = self._outing_ready_partner_ids(chara, getattr(self, "preset", {}) or {})
        stat_recreation_target = self._stat_recreation_target_bond(getattr(self, "preset", {}) or {})
        near_count = 0
        for partner_id in partners:
            try:
                bond = int(bonds.get(partner_id, 0) or 0)
            except (TypeError, ValueError):
                bond = 0
            if (
                partner_id in stat_recreation_partners
                and (partner_id in outing_ready or bond >= stat_recreation_target)
            ):
                continue
            if _NEAR_RAINBOW_BOND_MIN <= bond < _NEAR_RAINBOW_BOND_MAX:
                near_count += 1
        if near_count <= 0:
            return 0.0
        bonus = min(
            _NEAR_RAINBOW_BONUS_CAP,
            near_count * _NEAR_RAINBOW_BONUS_PER_PARTNER,
        )
        if turn > _NEAR_RAINBOW_LATE_PHASE_TURN:
            bonus *= _NEAR_RAINBOW_LATE_PHASE_SCALE
        return bonus

    def _current_rainbow_unlocked_count(self, chara):
        bonds = self._bond_map(chara)
        preset = getattr(self, "preset", {}) or {}
        stat_recreation_partners = self._stat_recreation_partner_ids(preset)
        outing_ready = self._outing_ready_partner_ids(chara, preset)
        stat_recreation_target = self._stat_recreation_target_bond(preset)
        return sum(
            1
            for partner_id in DECK_PARTNERS
            if (
                int(bonds.get(partner_id, 0) or 0) >= 80
                or (
                    partner_id in stat_recreation_partners
                    and (
                        partner_id in outing_ready
                        or int(bonds.get(partner_id, 0) or 0) >= stat_recreation_target
                    )
                )
            )
        )

    def _first_summer_friendship_target(self, turn):
        current_turn = int(turn or 0)
        for max_turn, target in _FIRST_SUMMER_FRIENDSHIP_TARGETS:
            if current_turn <= max_turn:
                return target
        return _FIRST_SUMMER_FRIENDSHIP_TARGETS[-1][1]

    def _first_summer_friendship_gap(self, chara, turn, preset):
        if not bool((preset or {}).get("first_summer_friendship_enabled", True)):
            return 0
        target_turn = int((preset or {}).get("first_summer_friendship_target_turn") or _FIRST_SUMMER_FRIENDSHIP_TARGET_TURN)
        if int(turn or 0) > target_turn:
            return 0
        current_unlocked = self._current_rainbow_unlocked_count(chara)
        target_unlocked = int(
            (preset or {}).get("first_summer_friendship_target_rainbows")
            or self._first_summer_friendship_target(turn)
        )
        return max(0, target_unlocked - current_unlocked)

    def _first_summer_friendship_bonus(self, command, chara, turn, preset):
        """Push friendship setup earlier so first summer is not entered
        with the deck still sitting in the 40-59 bond band.

        The old direct bond bonus only cared about 60-79, which was too
        late in weak runs. Before turn 35, reward deck partners in the
        40-79 band and add urgency when the career is behind the target
        count of unlocked rainbow/friendship supports."""
        if not bool((preset or {}).get("first_summer_friendship_enabled", True)):
            return 0.0
        if int(turn or 0) > int((preset or {}).get("first_summer_friendship_target_turn") or _FIRST_SUMMER_FRIENDSHIP_TARGET_TURN):
            return 0.0
        partners = command.get("training_partner_array") or []
        if not partners:
            return 0.0
        bonds = self._bond_map(chara)
        stat_recreation_partners = self._stat_recreation_partner_ids(preset)
        outing_ready = self._outing_ready_partner_ids(chara, preset)
        stat_recreation_target = self._stat_recreation_target_bond(preset)
        deficit = self._first_summer_friendship_gap(chara, turn, preset)
        bonus = 0.0
        for partner_id in partners:
            if partner_id not in DECK_PARTNERS:
                continue
            try:
                bond = int(bonds.get(partner_id, 0) or 0)
            except (TypeError, ValueError):
                bond = 0
            if (
                partner_id in stat_recreation_partners
                and (partner_id in outing_ready or bond >= stat_recreation_target)
            ):
                continue
            if bond >= 80:
                continue
            if 60 <= bond < 80:
                bonus += float((preset or {}).get("first_summer_friendship_bonus_60_79") or _FIRST_SUMMER_FRIENDSHIP_BONUS_60_79)
            elif 40 <= bond < 60:
                bonus += float((preset or {}).get("first_summer_friendship_bonus_40_59") or _FIRST_SUMMER_FRIENDSHIP_BONUS_40_59)
            elif 20 <= bond < 40 and int(turn or 0) <= 24:
                bonus += float((preset or {}).get("first_summer_friendship_bonus_20_39") or _FIRST_SUMMER_FRIENDSHIP_BONUS_20_39)
        if bonus <= 0:
            return 0.0
        if deficit > 0:
            urgency = 1.0 + deficit * float((preset or {}).get("first_summer_friendship_urgency_per_deficit") or _FIRST_SUMMER_FRIENDSHIP_URGENCY_PER_DEFICIT)
            bonus *= urgency
        return min(
            float((preset or {}).get("first_summer_friendship_bonus_cap") or _FIRST_SUMMER_FRIENDSHIP_BONUS_CAP),
            bonus,
        )

    def _facility_level_training_bonus(self, command, chara, preset, turn):
        """Reward early trainings that trigger or approach facility level-ups."""
        if not isinstance(preset, dict):
            return 0.0
        level, _progress, until_next = self._facility_level_info(command, chara)
        if level is None or level >= 5:
            return 0.0
        if until_next is None or until_next <= 0:
            return 0.0
        try:
            turn = int(turn or 0)
        except (TypeError, ValueError):
            turn = 0
        remaining_turns = max(0, 78 - turn)
        if remaining_turns <= 8:
            return 0.0
        early_progress = max(0.0, min(1.0, remaining_turns / 70.0))
        timing_mult = (
            _FACILITY_LEVELUP_LATE_MULTIPLIER
            + (_FACILITY_LEVELUP_EARLY_MULTIPLIER - _FACILITY_LEVELUP_LATE_MULTIPLIER) * early_progress
        )
        if until_next == 1:
            bonus = _FACILITY_LEVELUP_BASE_BONUS * timing_mult
            if level >= 3:
                bonus += _FACILITY_LEVELUP_LEVEL_4_TO_5_BONUS * timing_mult
        elif until_next == 2:
            bonus = _FACILITY_PROGRESS_NEAR_LEVELUP_BONUS * timing_mult
        else:
            bonus = 0.0
        # Concentration reinforcement: training a facility already at a
        # higher level produces more stat per turn (lv5 base ≈ 2× lv3).
        # Reward picking the SAME facility repeatedly so it climbs to lv5
        # instead of stalling all 5 facilities at lv2-3.
        if level >= 2 and remaining_turns > 14:
            bonus += _FACILITY_HIGH_LEVEL_REINFORCEMENT * min(3, level - 1) * timing_mult
        # Bootstrap pressure: if facility is still lv 1-2 AND the stat
        # is deck-supported (or Wit by operator policy), apply a strong
        # bonus to force the bot to invest 1-2 picks to level it up.
        # Otherwise Power/Wisdom facilities can sit at lv1 the whole
        # career while Speed/Wit dominate. This bonus only fires for
        # facilities the deck actually backs — Stamina/Guts on a
        # Speed/Wisdom deck stay at lv1 because no card supports them.
        if level <= 2 and turn <= _FACILITY_BOOTSTRAP_END_TURN:
            if self._stat_facility_should_bootstrap(command, preset):
                bonus += _FACILITY_BOOTSTRAP_BONUS * timing_mult
        cap = float((preset or {}).get("facility_level_training_bonus_cap") or _FACILITY_LEVEL_TRAINING_BONUS_CAP)
        return min(cap, bonus)

    def _stat_facility_should_bootstrap(self, command, preset):
        """Whether this command's facility deserves the bootstrap bonus.

        Returns True for:
        - Wit (operator policy: Wit always deserves to be leveled —
          high training output, recovery substitute, universally useful)
        - Any stat the deck has 2+ supporting cards in (deck-derived)

        Returns False for stats with no deck support: pushing those
        facilities up wastes the limited bootstrap window.
        """
        command_id = command.get("command_id")
        stat_idx = TRAINING_COMMANDS.get(command_id)
        if stat_idx is None:
            return False
        stat_names = ("speed", "stamina", "power", "guts", "wit")
        name = stat_names[stat_idx] if 0 <= stat_idx < 5 else ""
        if name == "wit":
            return True
        deck_supported = self._cap_pursuit_deck_derived_stats(preset) or set()
        return name in deck_supported

    def _lagging_bond_partner_bonus(self, command, chara, preset, turn):
        """Reward tiles containing the lagging deck partner.

        Within-stat bond drift: a 2-Wisdom deck should bond both Wisdom
        cards roughly evenly, but RNG/appearance bias often leaves one
        stuck (Fine Motion at 72 the entire S+ 16,116 career while Nice
        Nature hit 94). When the bot picks Wit, prefer the tile where
        the lagging partner appears so the slack card catches up.

        Inactive in Senior (turn > 60) — too late to invest in bond.
        Only fires for deck-supported stats (the bot shouldn't grind
        bond on a stat it doesn't need anyway).
        """
        try:
            turn = int(turn or 0)
        except (TypeError, ValueError):
            return 0.0
        if turn > _LAGGING_BOND_LATE_TURN:
            return 0.0
        partners = command.get("training_partner_array") or []
        if not partners:
            return 0.0
        bonds = self._bond_map(chara)
        # Find the lowest-bonded deck partner overall (deck partners
        # only — skip the friend slot and NPCs).
        lagging_id = None
        lagging_bond = 999
        for pid in DECK_PARTNERS:
            b = int(bonds.get(pid, 0) or 0)
            if b < lagging_bond:
                lagging_id = pid
                lagging_bond = b
        if lagging_id is None:
            return 0.0
        if lagging_bond >= _LAGGING_BOND_PARTNER_THRESHOLD:
            return 0.0
        if lagging_id not in partners:
            return 0.0
        # Scale bonus with how far behind the lagging partner is.
        gap = max(0, _LAGGING_BOND_PARTNER_THRESHOLD - lagging_bond)
        return min(_LAGGING_BOND_BONUS_CAP, gap * 0.003)

    def _speed_priority_bonus(self, command, chara, preset, turn):
        """Unconditional bonus for Speed training.

        Speed is the foundational race stat. The bot should always want to
        train Speed, regardless of the user's desired blue spark, deck
        composition, or current rainbow setup. This bonus overlays on top
        of all other scoring paths.

        Returns 0.0 if the command does not gain Speed (primary or secondary)
        or if the architecture is disabled via preset flag.
        """
        if not _SPEED_PRIORITY_ENABLED:
            return 0.0
        if not (preset or {}).get("stat_priority_architecture_enabled", True):
            return 0.0

        command_idx = TRAINING_COMMANDS.get(int(command.get("command_id") or 0))
        primary_speed_tile = command_idx == 0
        speed_gain = 0.0
        non_speed_stat_gain = 0.0
        for item in command.get("params_inc_dec_info_array") or []:
            value = float(item.get("value") or 0)
            if value <= 0:
                continue
            target = STAT_TARGETS.get(item.get("target_type"))
            if target == 0:
                speed_gain += value
            elif target in {1, 2, 3, 4}:
                non_speed_stat_gain += value

        if speed_gain <= 0:
            return 0.0
        if command_idx is None and non_speed_stat_gain <= 0:
            primary_speed_tile = True

        turn = int(turn or 0)
        # Allow the hyperparameter tuner to override per-phase magnitudes.
        if turn <= _CHECKPOINT_TURN_END_JUNIOR:
            base_bonus = _tuned_value(preset, "speed_priority_bonus_early", _SPEED_PRIORITY_BONUS_EARLY)
            source_floor = _SPEED_PRIORITY_BONUS_EARLY
        elif turn <= _CHECKPOINT_TURN_END_CLASSIC:
            base_bonus = _tuned_value(preset, "speed_priority_bonus_mid", _SPEED_PRIORITY_BONUS_MID)
            source_floor = _SPEED_PRIORITY_BONUS_MID
        else:
            base_bonus = _tuned_value(preset, "speed_priority_bonus_late", _SPEED_PRIORITY_BONUS_LATE)
            source_floor = _SPEED_PRIORITY_BONUS_LATE
        deck_counts = (preset or {}).get("_deck_type_counts") or [0, 0, 0, 0, 0]
        try:
            speed_cards = int(deck_counts[0]) if len(deck_counts) > 0 else 0
        except (TypeError, ValueError):
            speed_cards = 0
        if speed_cards >= 2:
            base_bonus = max(float(base_bonus), float(source_floor))

        current_speed = float(self._current_stat(chara, 0) or 0.0)
        if current_speed >= _SPEED_PRIORITY_TARGET_RAW:
            decay_factor = 0.1
        elif current_speed <= _SPEED_PRIORITY_FLOOR_RAW:
            decay_factor = 1.0
        else:
            span = _SPEED_PRIORITY_TARGET_RAW - _SPEED_PRIORITY_FLOOR_RAW
            progress = (current_speed - _SPEED_PRIORITY_FLOOR_RAW) / span
            decay_factor = 1.0 - (progress * 0.9)

        bonus = base_bonus * decay_factor

        if current_speed < _SPEED_PRIORITY_RACE_DEFICIT_THRESHOLD and turn >= _CHECKPOINT_TURN_END_JUNIOR:
            deficit_ratio = 1.0 - (current_speed / _SPEED_PRIORITY_RACE_DEFICIT_THRESHOLD)
            bonus += _SPEED_PRIORITY_DEFICIT_BOOST * deficit_ratio

        if not primary_speed_tile:
            # Secondary Speed side-gains are useful, but they should not
            # receive the same priority lane as an actual Speed training.
            # Without this guard, raising speed_priority can accidentally
            # make Wit/Guts side-gain tiles beat true Speed tiles.
            secondary_multiplier = float((preset or {}).get("speed_priority_secondary_multiplier") or 0.35)
            if speed_gain >= 20:
                secondary_multiplier = max(secondary_multiplier, 0.50)
            bonus *= max(0.0, min(1.0, secondary_multiplier))

        # Stat-floor scale-down: when stamina/power are below race-grade floor,
        # speed-priority is partially dampened so other priority bonuses can
        # win the tile selection. This lets stamina/power_priority_bonus
        # actually compete with speed_priority once both are firing.
        current_stamina = float(self._current_stat(chara, 1) or 0.0)
        current_power = float(self._current_stat(chara, 2) or 0.0)
        current_wit = float(self._current_stat(chara, 4) or 0.0)
        stamina_floor = _tuned_value(preset, "stamina_floor_target", _STAMINA_FLOOR_TARGET)
        power_floor = _tuned_value(preset, "power_floor_target", _POWER_FLOOR_TARGET)
        speed_scale_when_deficit = _tuned_value(
            preset, "speed_priority_deficit_scale", _SPEED_PRIORITY_DEFICIT_SCALE
        )
        learned_hp = (preset or {}).get("learned_hyperparameters")
        if not isinstance(learned_hp, dict):
            learned_hp = {}
        floor_pressure_keys = {
            "stamina_floor_target",
            "power_floor_target",
            "speed_priority_deficit_scale",
            "race_heavy_speed_deficit_scale_ceiling",
            "race_heavy_priority_lead_damp_gap",
            "race_heavy_priority_lead_damp_multiplier",
        }
        floor_pressure_enabled = (
            self._is_race_heavy_route(preset)
            or "stamina_floor_target" in (preset or {})
            or "power_floor_target" in (preset or {})
            or any(key in learned_hp for key in floor_pressure_keys)
        )
        if floor_pressure_enabled and turn >= _CHECKPOINT_TURN_END_JUNIOR:
            stamina_short = current_stamina < stamina_floor
            power_short = current_power < power_floor
            if self._is_race_heavy_route(preset):
                # Stale ML can tune this as high as 0.95, effectively
                # disabling the stamina/power safety rail after deck swaps.
                speed_scale_when_deficit = min(
                    float(speed_scale_when_deficit),
                    float((preset or {}).get("race_heavy_speed_deficit_scale_ceiling") or 0.82),
                )
            if stamina_short and power_short:
                bonus *= speed_scale_when_deficit
            elif stamina_short or power_short:
                bonus *= (1.0 + speed_scale_when_deficit) / 2.0
            lead_gap = float((preset or {}).get("race_heavy_priority_lead_damp_gap") or _RACE_HEAVY_PRIORITY_LEAD_DAMP_GAP)
            if current_speed > current_wit + lead_gap and current_wit < 1050:
                bonus *= float(
                    (preset or {}).get("race_heavy_priority_lead_damp_multiplier")
                    or _RACE_HEAVY_PRIORITY_LEAD_DAMP_MULTIPLIER
                )

        return bonus

    def _wit_priority_bonus(self, command, chara, preset, turn):
        """Dedicated Wit pressure for 2-Wit decks and high-Wit targets.

        Generic checkpoint pressure was too weak for Nature/Fine-style decks:
        Speed had an unconditional priority lane while Wit only received
        indirect bonuses, so race-heavy parent routes finished with Wit far
        below cap. This bonus is bounded and decays near 1200, but it lets a
        real 2-Wit deck compete for enough Wit trainings.
        """
        if not _WIT_PRIORITY_ENABLED:
            return 0.0
        if not (preset or {}).get("stat_priority_architecture_enabled", True):
            return 0.0

        wit_gain = 0.0
        for item in command.get("params_inc_dec_info_array") or []:
            value = float(item.get("value") or 0)
            if value <= 0:
                continue
            target = STAT_TARGETS.get(item.get("target_type"))
            if target == 4:
                wit_gain += value
        if wit_gain <= 0:
            return 0.0

        deck_counts = (preset or {}).get("_deck_type_counts") or [0, 0, 0, 0, 0]
        try:
            wit_cards = int(deck_counts[4]) if len(deck_counts) > 4 else 0
        except (TypeError, ValueError):
            wit_cards = 0
        targets = self._expect_attribute_targets(preset, chara, default=[9999, 9999, 9999, 9999, 9999])
        try:
            target_wit = float(targets[4] if len(targets) > 4 else 9999)
        except (TypeError, ValueError):
            target_wit = 9999.0
        if wit_cards < int(_tuned_value(preset, "wit_priority_min_deck_cards", _WIT_PRIORITY_MIN_DECK_CARDS)) and target_wit < 1100:
            return 0.0

        turn = int(turn or 0)
        if turn <= _CHECKPOINT_TURN_END_JUNIOR:
            base_bonus = _tuned_value(preset, "wit_priority_bonus_early", _WIT_PRIORITY_BONUS_EARLY)
        elif turn <= _CHECKPOINT_TURN_END_CLASSIC:
            base_bonus = _tuned_value(preset, "wit_priority_bonus_mid", _WIT_PRIORITY_BONUS_MID)
        else:
            base_bonus = _tuned_value(preset, "wit_priority_bonus_late", _WIT_PRIORITY_BONUS_LATE)

        current_wit = float(self._current_stat(chara, 4) or 0.0)
        target_raw = min(
            float(_tuned_value(preset, "wit_priority_target_raw", _WIT_PRIORITY_TARGET_RAW)),
            max(1050.0, target_wit if target_wit < 9999 else _WIT_PRIORITY_TARGET_RAW),
        )
        floor_raw = float(_tuned_value(preset, "wit_priority_floor_raw", _WIT_PRIORITY_FLOOR_RAW))
        if current_wit >= target_raw:
            return 0.0
        if current_wit <= floor_raw:
            decay_factor = 1.0
        else:
            span = max(1.0, target_raw - floor_raw)
            progress = (current_wit - floor_raw) / span
            decay_factor = max(0.10, 1.0 - (progress * 0.90))

        card_factor = 1.0 + min(0.30, max(0, wit_cards - 1) * 0.15)
        vital = int(chara.get("vital") or chara.get("hp") or 0)
        hp_factor = 1.10 if vital < 75 else 1.0
        bonus = float(base_bonus) * decay_factor * card_factor * hp_factor
        if self._is_race_heavy_route(preset):
            current_speed = float(self._current_stat(chara, 0) or 0.0)
            lead_gap = float((preset or {}).get("race_heavy_priority_lead_damp_gap") or _RACE_HEAVY_PRIORITY_LEAD_DAMP_GAP)
            if current_wit > current_speed + lead_gap and current_speed < 1050:
                bonus *= float(
                    (preset or {}).get("race_heavy_priority_lead_damp_multiplier")
                    or _RACE_HEAVY_PRIORITY_LEAD_DAMP_MULTIPLIER
                )
        return bonus

    def _stat_priority_bonus_generic(self, command, chara, preset, turn,
                                     *, stat_index, target_floor,
                                     base_bonus_key, base_bonus_default,
                                     deficit_boost_key, deficit_boost_default):
        """Shared logic for stamina/power priority bonuses.

        Fires only when current stat is below `target_floor`. Bonus grows
        as the stat falls further below the floor. Tunable via preset.
        """
        if not (preset or {}).get("stat_priority_architecture_enabled", True):
            return 0.0

        # Check the command actually gains this stat
        stat_gain = 0.0
        for item in command.get("params_inc_dec_info_array") or []:
            value = float(item.get("value") or 0)
            if value <= 0:
                continue
            target = STAT_TARGETS.get(item.get("target_type"))
            if target == stat_index:
                stat_gain += value
        if stat_gain <= 0:
            return 0.0

        target_floor = float(_tuned_value(preset, base_bonus_key.replace("_bonus_base", "_floor_target"), target_floor))
        race_heavy_power_lane = False
        if stat_index == 2 and self._is_race_heavy_route(preset):
            deck_counts = self._deck_stat_card_counts(preset)
            race_heavy_power_lane = int(deck_counts.get("power", 0) or 0) >= 1
            if race_heavy_power_lane:
                target_floor = max(
                    target_floor,
                    float((preset or {}).get("race_heavy_power_floor_target") or 950.0),
                )
        current = float(self._current_stat(chara, stat_index) or 0.0)
        if current >= target_floor:
            return 0.0

        base_bonus = float(_tuned_value(preset, base_bonus_key, base_bonus_default))
        deficit_boost = float(_tuned_value(preset, deficit_boost_key, deficit_boost_default))

        deficit_ratio = 1.0 - (current / max(1.0, target_floor))
        bonus = base_bonus + (deficit_boost * deficit_ratio)
        if race_heavy_power_lane:
            bonus *= float((preset or {}).get("race_heavy_power_priority_multiplier") or 1.35)
        # Stronger pre-Classic so early stamina/power foundation is built
        # before speed-priority takes over in Senior.
        if turn <= _CHECKPOINT_TURN_END_JUNIOR:
            bonus *= 0.7
        return bonus

    def _stamina_priority_bonus(self, command, chara, preset, turn):
        return self._stat_priority_bonus_generic(
            command, chara, preset, turn,
            stat_index=1,
            target_floor=_STAMINA_FLOOR_TARGET,
            base_bonus_key="stamina_priority_bonus_base",
            base_bonus_default=_STAMINA_PRIORITY_BONUS_BASE,
            deficit_boost_key="stamina_priority_deficit_boost",
            deficit_boost_default=_STAMINA_PRIORITY_DEFICIT_BOOST,
        )

    def _power_priority_bonus(self, command, chara, preset, turn):
        return self._stat_priority_bonus_generic(
            command, chara, preset, turn,
            stat_index=2,
            target_floor=_POWER_FLOOR_TARGET,
            base_bonus_key="power_priority_bonus_base",
            base_bonus_default=_POWER_PRIORITY_BONUS_BASE,
            deficit_boost_key="power_priority_deficit_boost",
            deficit_boost_default=_POWER_PRIORITY_DEFICIT_BOOST,
        )

    def _target_closeout_bonus(self, command, chara, preset, turn):
        """Force explicit 1100+ stat targets to close instead of stalling.

        Learned runs can make the bot "comfortable" at 1050-1150 because
        race-heavy routes still look playable there. For decks intentionally
        built to cap Speed/Wit, that is not acceptable: after Classic, the
        scoring needs a direct bonus on the lagging cap stat so the final
        training turns finish the target rather than only following generic
        partner/race pressure.
        """
        if not (preset or {}).get("stat_priority_architecture_enabled", True):
            return 0.0
        try:
            turn = int(turn or 0)
        except (TypeError, ValueError):
            return 0.0
        if turn < 36:
            return 0.0
        targets = self._expect_attribute_targets(preset, chara, default=[0, 0, 0, 0, 0])
        deck_counts = self._deck_stat_card_counts(preset)
        urgency = max(0.0, min(1.0, (turn - 36) / 42.0))
        cap = float((preset or {}).get("target_closeout_bonus_cap") or 0.72)
        if turn >= 60:
            cap = max(cap, float((preset or {}).get("target_closeout_late_bonus_cap") or 1.05))
        total = 0.0
        for item in command.get("params_inc_dec_info_array") or []:
            value = float(item.get("value") or 0)
            if value <= 0:
                continue
            target_idx = STAT_TARGETS.get(item.get("target_type"))
            if target_idx is None or target_idx >= 5:
                continue
            try:
                target_value = float(targets[target_idx] if target_idx < len(targets) else 0.0)
            except (TypeError, ValueError):
                target_value = 0.0
            if target_value < 1100.0 or target_value >= 9999.0:
                continue
            stat_name = _COMMAND_IDX_TO_STAT.get(target_idx)
            if not stat_name:
                continue
            # Only force stats the deck can realistically support. Speed/Wit
            # need two real cards for cap pressure; Power can be driven by one
            # Power friend plus Speed secondary gains, so one card is enough.
            required_cards = 1 if stat_name == "power" else 2
            if int(deck_counts.get(stat_name, 0) or 0) < required_cards:
                continue
            current = float(self._current_stat(chara, target_idx) or 0.0)
            if current >= target_value:
                continue
            ratio = current / max(1.0, target_value)
            deficit_factor = min(1.0, max(0.0, (1.0 - ratio) / 0.25))
            gain_weight = min(1.35, value / 18.0)
            lane_multiplier = 1.0
            if stat_name == "wit" and self._is_race_heavy_route(preset):
                current_speed = float(self._current_stat(chara, 0) or 0.0)
                current_stamina = float(self._current_stat(chara, 1) or 0.0)
                current_power = float(self._current_stat(chara, 2) or 0.0)
                core_behind = (
                    current_speed < float((preset or {}).get("wit_closeout_critical_speed_floor") or _WIT_CLOSEOUT_CRITICAL_SPEED_FLOOR)
                    or current_stamina < float((preset or {}).get("wit_closeout_critical_stamina_floor") or _WIT_CLOSEOUT_CRITICAL_STAMINA_FLOOR)
                    or current_power < float((preset or {}).get("wit_closeout_critical_power_floor") or _WIT_CLOSEOUT_CRITICAL_POWER_FLOOR)
                )
                damp_wit = (
                    current >= float((preset or {}).get("wit_closeout_damping_min_wit") or _WIT_CLOSEOUT_DAMPING_MIN_WIT)
                    or current >= current_speed + float(
                        (preset or {}).get("wit_closeout_damping_lead_over_speed")
                        or _WIT_CLOSEOUT_DAMPING_LEAD_OVER_SPEED
                    )
                )
                if core_behind and damp_wit:
                    lane_multiplier *= float(
                        (preset or {}).get("wit_closeout_damping_when_core_behind")
                        or _WIT_CLOSEOUT_DAMPING_WHEN_CORE_BEHIND
                    )
                elif current_speed < target_value * 0.92 and damp_wit:
                    lane_multiplier *= float(
                        (preset or {}).get("wit_closeout_damping_when_speed_behind")
                        or _WIT_CLOSEOUT_DAMPING_WHEN_SPEED_BEHIND
                    )
            total += cap * urgency * deficit_factor * gain_weight * lane_multiplier
        return min(cap, total)

    def _checkpoint_pressure_bonus(self, command, chara, preset, turn):
        """Apply per-stat pressure based on year-checkpoint progress.

        Each year has expected end-state stats (operator-supplied baseline).
        The bot should be on linear pace toward those at each turn within
        the year. If a stat is significantly behind pace, training that stat
        gets a bonus.

        Targets scale by deck composition: more cards on a stat means a
        higher realistic target because of rainbow stacking opportunities.

        Returns total bonus across all stats this command gains.
        """
        if not _CHECKPOINT_PRESSURE_ENABLED:
            return 0.0
        if not (preset or {}).get("stat_priority_architecture_enabled", True):
            return 0.0

        turn = int(turn or 0)

        if turn <= _CHECKPOINT_TURN_END_JUNIOR:
            target_vec = _CHECKPOINT_TARGETS_END_JUNIOR
            start_turn = 1
            end_turn = _CHECKPOINT_TURN_END_JUNIOR
            previous_targets = _CHECKPOINT_STARTING_STATS
        elif turn <= _CHECKPOINT_TURN_END_CLASSIC:
            target_vec = _CHECKPOINT_TARGETS_END_CLASSIC
            start_turn = _CHECKPOINT_TURN_END_JUNIOR
            end_turn = _CHECKPOINT_TURN_END_CLASSIC
            previous_targets = _CHECKPOINT_TARGETS_END_JUNIOR
        else:
            target_vec = _CHECKPOINT_TARGETS_END_SENIOR
            start_turn = _CHECKPOINT_TURN_END_CLASSIC
            end_turn = _CHECKPOINT_TURN_END_SENIOR
            previous_targets = _CHECKPOINT_TARGETS_END_CLASSIC

        deck_counts = (preset or {}).get("_deck_type_counts") or [0, 0, 0, 0, 0]
        scaled_targets = []
        scaled_previous = []
        for i in range(5):
            try:
                card_count = int(deck_counts[i]) if i < len(deck_counts) else 0
            except (TypeError, ValueError):
                card_count = 0
            scale = _CHECKPOINT_DECK_CARD_SCALE[min(5, max(0, card_count))]
            scaled_targets.append(target_vec[i] * scale)
            scaled_previous.append(previous_targets[i] * scale)

        total_bonus = 0.0
        for item in command.get("params_inc_dec_info_array") or []:
            value = float(item.get("value") or 0)
            if value <= 0:
                continue
            target_idx = STAT_TARGETS.get(item.get("target_type"))
            if target_idx is None or target_idx >= 5:
                continue

            current = float(self._current_stat(chara, target_idx) or 0.0)

            span = max(1, end_turn - start_turn)
            progress = (turn - start_turn) / span
            progress = max(0.0, min(1.0, progress))
            expected_pace = (
                scaled_previous[target_idx]
                + (scaled_targets[target_idx] - scaled_previous[target_idx]) * progress
            )

            if current >= expected_pace:
                continue

            deficit_ratio = (expected_pace - current) / max(1.0, expected_pace)
            stat_bonus = _tuned_value(preset, "checkpoint_pressure_base", _CHECKPOINT_PRESSURE_BASE) * min(1.0, deficit_ratio * 2.0)
            if deficit_ratio >= _CHECKPOINT_PRESSURE_CRITICAL_DEFICIT:
                stat_bonus += _CHECKPOINT_PRESSURE_BEHIND_BOOST

            gain_weight = min(1.0, value / _CHECKPOINT_TYPICAL_GAIN)
            total_bonus += stat_bonus * gain_weight

        return min(total_bonus, _CHECKPOINT_PRESSURE_MAX_BONUS)

    def _race_heavy_lane_balance_bonus(self, command, chara, preset, turn):
        """Keep 2-Speed/2-Wit race-heavy decks from collapsing into one lane.

        The recent A+ failures split into two shapes: high-Wit/low-Speed and
        high-Speed/low-Wit. Both are bad for this deck because the calendar
        leaves only ~30 training turns; the bot needs both supported lanes
        online instead of over-following whichever tile scored well early.
        """
        if not self._is_race_heavy_route(preset):
            return 0.0
        try:
            turn = int(turn or 0)
        except (TypeError, ValueError):
            return 0.0
        if turn < int((preset or {}).get("race_heavy_lane_balance_start_turn") or _RACE_HEAVY_LANE_BALANCE_START_TURN):
            return 0.0

        deck_counts = self._deck_stat_card_counts(preset)
        stat_gains = {}
        for item in command.get("params_inc_dec_info_array") or []:
            value = float(item.get("value") or 0)
            if value <= 0:
                continue
            target = STAT_TARGETS.get(item.get("target_type"))
            stat_name = _COMMAND_IDX_TO_STAT.get(target)
            if stat_name:
                stat_gains[stat_name] = stat_gains.get(stat_name, 0.0) + value
        if not stat_gains:
            return 0.0

        speed = float(self._current_stat(chara, 0) or 0.0)
        stamina = float(self._current_stat(chara, 1) or 0.0)
        power = float(self._current_stat(chara, 2) or 0.0)
        wit = float(self._current_stat(chara, 4) or 0.0)
        progress = max(0.0, min(1.0, turn / 78.0))
        # Targets used for the race-heavy lane-balance deficit bonus.
        # Earlier "no-power-card" Power target was 900 — too low. Real
        # careers regularly push Power past 900 via TSC, races, events
        # even without Power-typed cards in the deck, so capping the
        # lane-balance target at 900 made the bot under-push Power on
        # race-heavy routes. Lifted to 1050 (matching the with-power-
        # card case) so the bonus keeps firing while there's headroom.
        targets = {
            "speed": 1200.0 if int(deck_counts.get("speed", 0) or 0) >= 2 else 1050.0,
            "wit": 1200.0 if int(deck_counts.get("wit", 0) or 0) >= 2 else 1000.0,
            "power": 1050.0,
            "stamina": 720.0,
        }
        current_by_stat = {"speed": speed, "stamina": stamina, "power": power, "wit": wit}
        cap = float((preset or {}).get("race_heavy_lane_balance_max_bonus") or _RACE_HEAVY_LANE_BALANCE_MAX_BONUS)
        gap = float((preset or {}).get("race_heavy_lane_balance_gap") or _RACE_HEAVY_LANE_BALANCE_GAP)
        total = 0.0

        for stat_name, gain in stat_gains.items():
            if stat_name not in {"speed", "power", "wit"}:
                continue
            supported = int(deck_counts.get(stat_name, 0) or 0)
            if stat_name in {"speed", "wit"} and supported < 2:
                continue
            if stat_name == "power" and supported < 1:
                continue
            current = current_by_stat.get(stat_name, 0.0)
            target = targets[stat_name]
            expected_now = target * (0.20 + 0.80 * progress)
            pace_deficit = max(0.0, (expected_now - current) / max(1.0, expected_now))
            balance_deficit = 0.0
            if stat_name == "speed":
                balance_deficit = max(0.0, (wit - speed - gap) / max(1.0, gap * 2.0))
            elif stat_name == "wit":
                balance_deficit = max(0.0, (speed - wit - gap) / max(1.0, gap * 2.0))
            elif stat_name == "power":
                desired_power_anchor = ((speed + wit) / 2.0) - float(
                    (preset or {}).get("race_heavy_power_support_gap") or _RACE_HEAVY_POWER_SUPPORT_GAP
                )
                balance_deficit = max(0.0, (desired_power_anchor - power) / max(1.0, gap * 2.5))
            deficit = min(1.0, max(pace_deficit * 1.35, balance_deficit))
            if deficit <= 0:
                continue
            gain_weight = min(1.0, max(0.35, gain / 22.0))
            total += cap * deficit * gain_weight
        return min(cap, total)

    def _per_stat_soft_cap(self, target, preset, turn=None):
        """Return the per-stat soft cap (operator policy).

        General-career caps are deliberately high (1200 for the main
        rating stats, 1000 for the support stats) so the bot can push
        any stat as far as the deck supports without artificially
        tapering off. A stat listed in `desired_parent_sparks.blue` is
        bumped to the high cap. Each can be overridden via
        `<stat>_soft_cap` in the preset (or via the auto-tuner).

        LATE-WEEK CLAMP (operator rule, 2026-06-09): in the final
        training stretch (late Oct senior, T >= `late_week_cap_turn`,
        default 70), ALL stat caps snap to a firm 1100. Past 1100 the
        rating curve has flattened (R2 gradient drops sharply past
        ~1100 displayed stat) and any further training is wasted —
        time is better spent on SP / skill / race buffer. This clamp
        ignores expected_target, deck_count protections, and tuned
        overrides: when the late-week window opens, 1100 is final.
        """
        if target < 0 or target >= 5:
            return 0.0
        stat_name = ("speed", "stamina", "power", "guts", "wit")[target]
        # Defaults raised across the board so general-career training
        # isn't held back. The previous defaults (1100/800) date from
        # an earlier era when the bot landed A/A+; with current
        # performance hitting S+/SS, the cap needs to allow pushing
        # past 1100 for the main rating stats.
        DEFAULT_HIGH_CAP = 1200.0
        DEFAULT_LOW_CAP = 1000.0
        HIGH_PRIORITY_STATS = {"speed", "power", "wit"}
        spark_stats = self._cap_pursuit_blue_spark_stats(preset)
        if stat_name in HIGH_PRIORITY_STATS or stat_name in spark_stats:
            default = DEFAULT_HIGH_CAP
        else:
            default = DEFAULT_LOW_CAP
        targets = self._expect_attribute_targets(preset, None, default=[0, 0, 0, 0, 0])
        try:
            expected_target = float(targets[target] if target < len(targets) else 0.0)
        except (TypeError, ValueError):
            expected_target = 0.0
        if 0.0 < expected_target < 9999.0:
            default = max(default, expected_target)
        tuned = float(_tuned_value(preset, f"{stat_name}_soft_cap", default))
        deck_counts = (preset or {}).get("_deck_type_counts") or [0, 0, 0, 0, 0]
        try:
            card_count = int(deck_counts[target]) if target < len(deck_counts) else 0
        except (TypeError, ValueError):
            card_count = 0
        # Learned caps are allowed to trim unsupported stats, but they must
        # not poison a deck's main lanes after the user swaps cards. A 2-Speed
        # or 2-Wit deck is explicitly built to cap those stats; stale learned
        # values like `wit_soft_cap: 900` make the bot stop pushing exactly
        # where this route needs pressure.
        if stat_name in {"speed", "wit"} and card_count >= 2:
            tuned = max(tuned, 1200.0)
        elif stat_name == "power" and card_count >= 1:
            tuned = max(tuned, 1050.0)
        # Learned hyperparameters may tune caps down after mediocre runs, but
        # explicit operator targets are hard goals. Do not let ML tell a
        # 1200 Speed/Wit route to stop at 1050/1100.
        if 0.0 < expected_target < 9999.0:
            tuned = max(tuned, expected_target)

        # LATE-WEEK CLAMP. This is operator policy and must win over all
        # of the above. When in the late-week window, 1100 is the cap,
        # period — not 1099, not 1101.
        if turn is not None:
            try:
                cur_turn = int(turn)
            except (TypeError, ValueError):
                cur_turn = 0
            late_week_turn = int(_tuned_value(preset, "late_week_cap_turn", 70))
            late_week_cap = float(_tuned_value(preset, "late_week_hard_cap", 1100))
            if cur_turn >= late_week_turn:
                return late_week_cap
        return tuned

    def _stat_concentration_bonus(self, command, chara, preset, turn):
        """Push each stat toward its per-stat soft cap (not past it).

        Operator policy: "stat capped or slightly below cap, not
        overcapped." So the bonus is anchored to each stat's soft cap
        (1100 for speed/power/wit, 800 for stamina/guts, configurable
        via `<stat>_soft_cap`):

        - ratio = current / soft_cap
        - below 0.55 of soft cap: 0 (stat isn't ready to concentrate)
        - 0.55 → 0.95 of soft cap: linear ramp 0 → peak
        - 0.95 → 1.00 of soft cap: peak +0.25 (close the last gap)
        - at or above soft cap: 0 (overcap multiplier handles overshoot)

        Inactive before T48 (Senior) — Junior/Classic still build a
        balanced base via Checkpoint Pressure. This replaces the prior
        "push top-2 to 1200" logic which left Speed/Power 100+ below
        their caps while Wit overshot to 1062 in the S+ 16,116 career.
        """
        try:
            turn = int(turn or 0)
        except (TypeError, ValueError):
            return 0.0
        if turn < _STAT_CONCENTRATION_START_TURN:
            return 0.0

        primary_target = None
        max_gain = 0.0
        for item in command.get("params_inc_dec_info_array") or []:
            value = float(item.get("value") or 0)
            if value <= 0:
                continue
            target = STAT_TARGETS.get(item.get("target_type"))
            if target is None or target >= 5:
                continue
            if value > max_gain:
                max_gain = value
                primary_target = target
        if primary_target is None:
            return 0.0

        soft_cap = self._per_stat_soft_cap(primary_target, preset, turn=turn)
        if soft_cap <= 0:
            return 0.0

        current = float(self._current_stat(chara, primary_target) or 0.0)
        ratio = current / soft_cap

        if ratio >= 1.0:
            return 0.0
        if ratio < _STAT_CONCENTRATION_RAMP_START:
            return 0.0
        if ratio >= _STAT_CONCENTRATION_PEAK_START:
            return _STAT_CONCENTRATION_PEAK_BONUS
        span = _STAT_CONCENTRATION_PEAK_START - _STAT_CONCENTRATION_RAMP_START
        progress = (ratio - _STAT_CONCENTRATION_RAMP_START) / max(0.01, span)
        return _STAT_CONCENTRATION_PEAK_BONUS * progress

    def _current_stat(self, chara, target):
        keys = ["speed", "stamina", "power", "guts", "wiz", "skill_point"]
        return float(chara.get(keys[target], 0) or 0)

    def _desired_parent_goals(self, preset):
        raw = (preset or {}).get("desired_parent_sparks")
        goals = {"blue": [], "pink": [], "green": [], "white": []}
        if not isinstance(raw, dict):
            return goals
        aliases = {
            "red": "pink",
            "aptitude": "pink",
            "stat": "blue",
            "unique": "green",
            "skill": "white",
            "race": "white",
            "scenario": "white",
        }
        for raw_key, raw_value in raw.items():
            key = aliases.get(str(raw_key or "").strip().lower(), str(raw_key or "").strip().lower())
            if key not in goals:
                continue
            parts = raw_value if isinstance(raw_value, list) else str(raw_value or "").replace(",", "\n").splitlines()
            seen = set()
            for part in parts:
                text = str(part or "").strip()
                folded = text.lower()
                if not text or folded in seen:
                    continue
                seen.add(folded)
                goals[key].append(text)
        return goals

    def _desired_blue_target_indices(self, preset):
        indices = []
        seen = set()
        for raw in self._desired_parent_goals(preset).get("blue") or []:
            idx = BLUE_SPARK_STAT_ALIASES.get(str(raw or "").strip().lower())
            if idx is None or idx in seen:
                continue
            seen.add(idx)
            indices.append(idx)
        return indices

    def _desired_blue_spark_multiplier(self, target, chara, preset, turn):
        if target not in self._desired_blue_target_indices(preset):
            return 1.0
        current = float(self._current_stat(chara, target) or 0.0)
        future_relief = self._future_stat_relief(target, chara, preset)
        projected_with_future = current + future_relief
        if projected_with_future >= 1100.0:
            return 0.97
        progress = max(0.25, min(1.0, float(turn or 0) / 78.0))
        expected_now = max(1.0, min(1100.0, 1100.0 * progress) - future_relief)
        gap_ratio = max(0.0, (expected_now - current) / max(1.0, expected_now))
        multiplier = 1.06
        band = stat_value_band(current)
        if band == "low":
            multiplier += 0.08
        elif band == "mid":
            multiplier += 0.04
        if current < expected_now:
            multiplier += min(0.14, gap_ratio * 0.18)
        if int(turn or 0) >= 60 and projected_with_future < 1100.0:
            multiplier += 0.04
        return min(1.30, multiplier)

    def _desired_parent_spark_training_multiplier(self, command, chara, preset, turn):
        goals = self._desired_parent_goals(preset)
        white_goals = goals.get("white") or []
        green_goals = goals.get("green") or []
        if (not white_goals and not green_goals) or int(turn or 0) < 48:
            return 1.0
        stat_gain = 0.0
        skill_point_gain = 0.0
        for item in command.get("params_inc_dec_info_array") or []:
            value = float(item.get("value") or 0)
            if value <= 0:
                continue
            target = STAT_TARGETS.get(item.get("target_type"))
            if target is None:
                continue
            if target == 5:
                skill_point_gain += value
            elif 0 <= target < 5:
                stat_gain += value
        output_score = min(1.0, (stat_gain + (skill_point_gain * 0.6)) / 45.0)
        if output_score <= 0:
            return 1.0
        turn_pressure = min(1.0, max(0.0, (int(turn or 0) - 48) / 30.0))
        pressure = 0.0
        if white_goals:
            pressure += 0.04
        if green_goals:
            pressure += 0.03
        return 1.0 + (output_score * turn_pressure * pressure)

    def _projected_overcap_multiplier(self, target, chara, preset, targets, turn):
        try:
            turn = int(turn or 0)
        except (TypeError, ValueError):
            turn = 0
        if target < 0 or target >= 5 or turn < 36:
            return 1.0
        cap = float(targets[target] if target < len(targets) else 0.0) or 0.0
        if cap <= 0:
            return 1.0
        current = float(self._current_stat(chara, target) or 0.0)
        if current <= 0:
            return 1.0
        future_relief = self._future_stat_relief(target, chara, preset, max_turn=78)
        progress = max(0.35, min(1.0, turn / 78.0))
        expected_progress = 0.25 + (0.75 * progress)
        projected_final = (current / max(0.45, expected_progress)) + future_relief
        projected_ratio = projected_final / cap if cap > 0 else 1.0
        if projected_ratio >= 1.18:
            return 0.35
        if projected_ratio >= 1.12:
            return 0.50 - ((projected_ratio - 1.12) / 0.06) * 0.15
        if projected_ratio >= 1.06:
            return 0.68 - ((projected_ratio - 1.06) / 0.06) * 0.18
        if projected_ratio >= 1.00:
            return 0.84 - ((projected_ratio - 1.00) / 0.06) * 0.16
        if turn >= 60 and projected_ratio >= 0.96:
            return 0.92
        return 1.0

    def _knowledge_multiplier(self, target, chara, preset, targets, turn):
        mult = 1.0
        distance_key = str((preset or {}).get("skill_profile_distance") or "").strip().lower()
        if target == 3:
            guts_floor = {
                "sprint": 210,
                "mile": 260,
                "dirt": 260,
                "medium": 320,
                "long": 420,
            }.get(distance_key, 280)
            current = float(self._current_stat(chara, 3) or 0)
            if current < guts_floor:
                mult = 1.25
            elif current >= guts_floor * 1.4:
                mult = 0.85
        elif target == 4:
            current_wit = float(self._current_stat(chara, 4) or 0)
            try:
                target_wit = float(targets[4] if len(targets) > 4 else _WIT_PRIORITY_TARGET_RAW)
            except (TypeError, ValueError):
                target_wit = _WIT_PRIORITY_TARGET_RAW
            if target_wit <= 0 or target_wit >= 9999:
                target_wit = _WIT_PRIORITY_TARGET_RAW
            deck_counts = (preset or {}).get("_deck_type_counts") or [0, 0, 0, 0, 0]
            try:
                wit_cards = int(deck_counts[4]) if len(deck_counts) > 4 else 0
            except (TypeError, ValueError):
                wit_cards = 0
            wit_focus_context = wit_cards >= 2
            if current_wit >= target_wit:
                mult = 0.55
            elif current_wit >= target_wit * 0.95:
                mult = 0.80
            elif current_wit >= target_wit * 0.85:
                mult = 0.95
            elif wit_focus_context:
                mult = 1.08 if current_wit < target_wit * 0.70 else 1.02
            elif current_wit >= 500:
                mult = 0.85
            else:
                mult = 1.04
        elif target == 1:
            style = str((preset or {}).get("skill_profile_style") or "").strip().lower()
            distance_key = str((preset or {}).get("skill_profile_distance") or "").strip().lower()
            current_sta = float(self._current_stat(chara, 1) or 0)
            distance_base = {
                "sprint": 180,
                "mile": 260,
                "dirt": 260,
                "medium": 320,
                "long": 400,
            }.get(distance_key, 280)
            style_bias = {
                "front_runner": 1.10,
                "pace_chaser": 1.08,
                "late_surger": 0.92,
                "end_closer": 0.96,
            }.get(style, 1.0)
            sta_floor = int(distance_base * style_bias)
            if current_sta < sta_floor:
                mult = 1.15
            else:
                cap_sta = float(targets[1] if 1 < len(targets) else 1100) or 1100.0
                if cap_sta > 0 and (current_sta / cap_sta) >= 0.97:
                    mult = 0.55
        elif target == 0:
            cap_speed = float(targets[0] if 0 < len(targets) else 1100) or 1100.0
            current_speed = float(self._current_stat(chara, 0) or 0)
            ratio = current_speed / cap_speed if cap_speed else 1.0
            if turn >= 25 and ratio < 0.55:
                mult = 1.15
            elif turn >= 60 and ratio < 0.85:
                mult = 1.10
        elif target == 2:
            cap_pwr = float(targets[2] if 2 < len(targets) else 1100) or 1100.0
            current_pwr = float(self._current_stat(chara, 2) or 0)
            if cap_pwr > 0 and (current_pwr / cap_pwr) < 0.55 and turn >= 25:
                mult = 1.10
        mult *= self._desired_blue_spark_multiplier(target, chara, preset, turn)
        mult *= self._projected_overcap_multiplier(target, chara, preset, targets, turn)
        return mult

    def _team_command(self, data, command_id):
        team_data = data.get("team_data_set") or {}
        for cmd in team_data.get("command_info_array") or []:
            if cmd.get("command_id") == command_id:
                return cmd
        return None

    def _bond_map(self, chara):
        result = {}
        for row in chara.get("evaluation_info_array") or []:
            result[row.get("target_id", 0)] = row.get("evaluation", 0)
        return result

    def _npc_score(self, bond, turn, preset):
        if bond >= 80:
            return 0.0
        row = self._period_row(preset.get("npc_score_value"), turn, [0.05, 0.05, 0.05])
        v1 = float(row[0] if len(row) > 0 else 0.05)
        v2 = float(row[1] if len(row) > 1 else v1)
        ratio = min(1.0, bond / 80.0)
        return v1 + (v2 - v1) * ratio

    def _pal_score(self, bond, preset, target_bond=80):
        target_bond = max(1, int(target_bond or 80))
        if bond >= target_bond:
            return 0.0
        scores = preset.get("pal_friendship_score") or [0.08, 0.057, 0.018]
        v1 = float(scores[0] if len(scores) > 0 else 0.08)
        v2 = float(scores[1] if len(scores) > 1 else v1)
        ratio = min(1.0, bond / float(target_bond))
        return v1 + (v2 - v1) * ratio

    def _period_index(self, turn):
        if turn <= 24:
            return 0
        if turn <= 48:
            return 1
        if turn <= 60:
            return 2
        if turn <= 72:
            return 3
        return 4

    def _period_row(self, rows, turn, fallback):
        if not isinstance(rows, list) or not rows:
            return fallback
        idx = min(self._period_index(turn), len(rows) - 1)
        row = rows[idx]
        return row if isinstance(row, list) else fallback

    def _extra_weight(self, idx, turn, preset):
        rows = preset.get("extra_weight") or [[0, 0, 0, 0, 0]] * 4
        if turn <= 24:
            row_idx = 0
        elif turn <= 48:
            row_idx = 1
        elif turn in SUMMER_CAMP_TURNS and len(rows) >= 4:
            row_idx = 3
        else:
            row_idx = 2
        if row_idx >= len(rows) or not isinstance(rows[row_idx], list) or idx >= len(rows[row_idx]):
            return 0.0
        return float(rows[row_idx][idx] or 0)

    def _mood_threshold(self, turn, preset):
        if turn <= 36:
            return int(preset.get("motivation_threshold_year1") or 3)
        if turn <= 60:
            return int(preset.get("motivation_threshold_year2") or 4)
        return int(preset.get("motivation_threshold_year3") or 4)

    def _should_push_first_summer_training(self, turn, preset, friendship_gap, vital, failure, best_score):
        if friendship_gap <= 0:
            return False
        target_turn = int((preset or {}).get("first_summer_friendship_target_turn") or _FIRST_SUMMER_FRIENDSHIP_TARGET_TURN)
        if int(turn or 0) > target_turn:
            return False
        min_vital = int(
            (preset or {}).get("first_summer_friendship_min_push_vital")
            or _FIRST_SUMMER_FRIENDSHIP_MIN_PUSH_VITAL
        )
        min_vital = max(10, min_vital - (max(0, friendship_gap - 1) * 4))
        max_failure = int(
            (preset or {}).get("first_summer_friendship_max_push_failure")
            or _FIRST_SUMMER_FRIENDSHIP_MAX_PUSH_FAILURE
        )
        max_failure += max(0, friendship_gap - 1) * 2
        min_score = float(
            (preset or {}).get("first_summer_friendship_min_push_score")
            or _FIRST_SUMMER_FRIENDSHIP_MIN_PUSH_SCORE
        )
        return int(vital or 0) >= min_vital and int(failure or 0) <= max_failure and float(best_score or 0.0) >= min_score

    def _should_recreate(self, recreation, preset, turn, motivation, vital, best_score, friendship_gap=0, chara=None):
        if not recreation:
            return False
        if turn in SUMMER_CAMP_TURNS:
            return False
        if recreation.get("_stat_recreation_started_blocked"):
            return False
        recreate_score_cap = 0.3
        if self._is_race_heavy_route(preset):
            recreate_score_cap = float(
                _tuned_value(
                    preset,
                    "race_heavy_recreation_max_training_score",
                    float((preset or {}).get("race_heavy_recreation_max_training_score") or 0.18),
                )
            )
        # Stat-granting pal/friend cards (Riko Kashimoto, Tazuna, Mei Satake,
        # etc.) are only stat-farming actions once the game exposes their
        # real outing command. Do not infer that from card presence alone.
        stat_friend = self._specific_stat_outing_available(preset, recreation, chara=chara)
        if stat_friend:
            if vital >= int(
                _tuned_value(
                    preset,
                    "stat_friend_recreation_max_vital",
                    int((preset or {}).get("stat_friend_recreation_max_vital") or _RECREATION_VITAL_CEILING),
                )
            ):
                return False
            recreate_score_cap += float(
                _tuned_value(
                    preset,
                    "stat_friend_recreation_score_cap_bonus",
                    float((preset or {}).get("stat_friend_recreation_score_cap_bonus") or _STAT_RECREATION_SCORE_CAP_BONUS),
                )
            )
            stat_friend_score_cap = float(
                _tuned_value(
                    preset,
                    "stat_friend_recreation_max_training_score",
                    float((preset or {}).get("stat_friend_recreation_max_training_score") or max(0.42, recreate_score_cap)),
                )
            )
            if vital <= int(
                _tuned_value(
                    preset,
                    "stat_friend_recreation_force_vital",
                    int((preset or {}).get("stat_friend_recreation_force_vital") or 50),
                )
            ):
                return True
            if best_score <= stat_friend_score_cap:
                return True
        if friendship_gap > 0 and int(turn or 0) <= int((preset or {}).get("first_summer_friendship_target_turn") or _FIRST_SUMMER_FRIENDSHIP_TARGET_TURN):
            recreate_score_cap = min(
                recreate_score_cap,
                float(
                    (preset or {}).get("first_summer_friendship_recreation_max_training_score")
                    or _FIRST_SUMMER_FRIENDSHIP_RECREATION_MAX_TRAINING_SCORE
                ),
            )
            if vital > int(
                (preset or {}).get("first_summer_friendship_recreation_max_vital")
                or _FIRST_SUMMER_FRIENDSHIP_RECREATION_MAX_VITAL
            ):
                return False
        if motivation < self._mood_threshold(turn, preset) and vital <= _RECREATION_VITAL_CEILING and best_score <= recreate_score_cap:
            return True
        critical_mood = int(
            (preset or {}).get("critical_mood_recreation_threshold")
            or _CRITICAL_MOOD_RECREATION_THRESHOLD
        )
        if motivation <= critical_mood:
            critical_vital_ceiling = int(
                (preset or {}).get("critical_mood_recreation_vital_ceiling")
                or _CRITICAL_MOOD_RECREATION_VITAL_CEILING
            )
            critical_score_cap = float(
                (preset or {}).get("critical_mood_recreation_score_cap")
                or _CRITICAL_MOOD_RECREATION_SCORE_CAP
            )
            if vital <= critical_vital_ceiling and best_score <= critical_score_cap:
                return True
        if not preset.get("prioritize_recreation"):
            return False
        thresholds = preset.get("pal_thresholds") or []
        if not thresholds:
            return False
        stage = int(preset.get("_pal_event_stage") or 0)
        if stage >= len(thresholds):
            stage = 0
        row = thresholds[stage]
        if not isinstance(row, list) or len(row) < 2:
            return False
        mood_ok = motivation <= int(row[0])
        energy_ok = vital <= int(row[1])
        score_ok = True
        if len(row) > 2:
            score_ok = best_score <= float(row[2])
        return mood_ok and energy_ok and score_ok

    def _should_take_stat_friend_recreation(
        self,
        preset,
        *,
        turn,
        motivation,
        vital,
        best_score,
        failure,
        rest_threshold,
        chara=None,
    ):
        """Gate stat-friend outings so they replace recovery, not good training.

        Riko and similar pal cards are valuable, but live logs showed the bot
        spending all five outings in Junior/early Classic and still resting
        later. That is worse than using outings as rest substitutes. Keep early
        pacing tight, then allow the outing when HP/failure/mood says this turn
        would otherwise be recovery-like.
        """
        if turn in SUMMER_CAMP_TURNS:
            return False
        try:
            vital = int(vital or 0)
            turn = int(turn or 0)
            failure = int(failure or 0)
            rest_threshold = int(rest_threshold or 0)
            best_score = float(best_score or 0.0)
            motivation = int(motivation or 3)
        except (TypeError, ValueError):
            return False

        try:
            max_vital = int(
                _tuned_value(
                    preset,
                    "stat_friend_recreation_max_vital",
                    int((preset or {}).get("stat_friend_recreation_max_vital") or _RECREATION_VITAL_CEILING),
                )
            )
        except (TypeError, ValueError):
            max_vital = _RECREATION_VITAL_CEILING
        if vital >= max_vital:
            return False

        per_card = self._outing_status_per_card(chara or {}, preset or {})
        ready = [info for info in per_card.values() if info.get("ready")]
        if not ready:
            return False
        taken = max(int(info.get("taken") or 0) for info in ready)

        try:
            early_limit_turn = int((preset or {}).get("stat_friend_recreation_early_limit_turn") or 25)
        except (TypeError, ValueError):
            early_limit_turn = 25
        try:
            early_max_uses = int((preset or {}).get("stat_friend_recreation_early_max_uses") or 2)
        except (TypeError, ValueError):
            early_max_uses = 2
        try:
            emergency_vital = int((preset or {}).get("stat_friend_recreation_emergency_vital") or 28)
        except (TypeError, ValueError):
            emergency_vital = 28

        if turn <= early_limit_turn and taken >= early_max_uses and vital > emergency_vital:
            return False

        # Pace finite pal outings across the career. Burning all five Riko
        # outings by early Classic left later bad-mood/low-HP turns with only
        # plain rest available, which correlated with the A+ collapses.
        mood_emergency = motivation <= int(
            (preset or {}).get("critical_mood_recreation_threshold")
            or _CRITICAL_MOOD_RECREATION_THRESHOLD
        )
        outing_emergency = (
            vital <= emergency_vital
            or failure >= 35
            or mood_emergency
        )
        if not outing_emergency:
            junior_cap = int((preset or {}).get("stat_friend_recreation_junior_use_cap") or 1)
            early_classic_cap = int((preset or {}).get("stat_friend_recreation_early_classic_use_cap") or 3)
            classic_cap = int((preset or {}).get("stat_friend_recreation_classic_use_cap") or 4)
            if turn <= 24 and taken >= junior_cap:
                return False
            if turn <= 36 and taken >= early_classic_cap:
                return False
            if turn <= 48 and taken >= classic_cap:
                return False

        if vital <= emergency_vital:
            return True

        recovery_like = vital <= rest_threshold or failure >= 35 or best_score < 0.0
        if recovery_like:
            return True

        try:
            force_vital = int(
                _tuned_value(
                    preset,
                    "stat_friend_recreation_force_vital",
                    int((preset or {}).get("stat_friend_recreation_force_vital") or 50),
                )
            )
        except (TypeError, ValueError):
            force_vital = 50
        try:
            score_cap = float(
                _tuned_value(
                    preset,
                    "stat_friend_recreation_max_training_score",
                    float((preset or {}).get("stat_friend_recreation_max_training_score") or 0.75),
                )
            )
        except (TypeError, ValueError):
            score_cap = 0.75

        if vital <= force_vital:
            return True
        if taken > 0 and turn > early_limit_turn and vital <= min(max_vital - 1, force_vital + 10):
            return True

        mood_low = motivation < self._mood_threshold(turn, preset or {})
        if mood_low and best_score <= score_cap:
            return True

        return False

    def choose_from_event(self, event, current_turn):
        # Layered picker. In order:
        #   1) Riko Kashimoto outing/event chain: force the middle option.
        #   2) Learned per-(story_id, choice_index) stats from past
        #      careers. If a clear winner has emerged in the bot's own
        #      data, prefer it. Returns 1-based select_index matching
        #      the API convention.
        #   3) Static EventManager (curated good/bad outcomes file).
        #   4) Default to choice 1.
        event_data = event or {}
        story_id = str(event_data.get("story_id") or "")
        choices = ((event_data.get("event_contents_info") or {}).get("choice_array") or [])
        if story_id.startswith(_RIKO_KASHIMOTO_EVENT_PREFIXES) and choices:
            # Live GLB captures show Riko's unlock story can present duplicate
            # select_index values. The stable discriminator is the displayed
            # middle option, not select_index=2; choosing the top branch caused
            # several careers to never unlock the five outing commands.
            middle_idx = min(len(choices) - 1, len(choices) // 2)
            return middle_idx

        learned_stats = None
        if isinstance(self.preset, dict):
            learned_stats = self.preset.get("event_choice_stats")
        if learned_stats:
            picked_idx = pick_learned_choice(
                learned_stats,
                event_data.get("story_id"),
                choices,
                current_turn=current_turn,
                preset=self.preset,
            )
            if picked_idx is not None and 0 <= picked_idx < len(choices):
                # API expects 1-based select_index — pass through from
                # the choice the learner picked.
                return picked_idx
        if self.event_manager:
            return self.event_manager.choose(event)
        return 1
