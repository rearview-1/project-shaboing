"""Physics-based Umamusume race simulator.

Replaces the legacy "weighted stat-sum -> kernel over a result corpus -> hardcoded
win-probability floors" race model with an actual section-by-section run, so that
stamina exhaustion, the last spurt, power-driven acceleration and the late-race
guts term decide outcomes the way the real game does. A speed-heavy / stamina-thin
build now *stalls* (decelerates -1.2 m/s^2 when HP hits 0) instead of always winning.

EVERY constant below is cited to a uma.guide page. The only knobs that are NOT
directly cited are isolated in `RaceParams` and are meant to be CALIBRATED from
observed race data, never hand-tuned to force a number.

Sources (see memory/reference_uma_guide.md for the page index):
  - uma.guide/guides/target-speed   : BaseSpeed, style speed coefs, distance
                                       target-speed multipliers, LastSpurt, MinSpeed,
                                       Wit section randomness.
  - uma.guide/guides/race-mechanics : 24 sections / 4 phases, acceleration formula,
                                       style accel coefs, ground accel aptitude,
                                       distance accel aptitude (E or lower),
                                       deceleration values incl. HP-out -1.2.
  - uma.guide/guides/race-hp         : MaxHP = 0.8*StrategyCoef*Stamina + Distance;
                                       per-second drain 20*(v-Base+12)^2/144*Status*Ground;
                                       late-race guts mod 1 + 200/sqrt(600*Guts).
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field

STAT_KEYS = ("speed", "stamina", "power", "guts", "wit")

# Canonical style keys used throughout the project.
STYLES = ("runaway", "front", "pace", "late", "end")

# --- target-speed page: style speed coefficient by phase (early, mid, late+spurt) ---
STYLE_SPEED_COEF = {
    "runaway": (1.063, 0.962, 0.95),
    "front":   (1.0,   0.98,  0.962),
    "pace":    (0.978, 0.991, 0.975),
    "late":    (0.938, 0.998, 0.994),
    "end":     (0.931, 1.0,   1.0),
}
# --- race-mechanics page: style acceleration coefficient (opening, middle, late) ---
STYLE_ACCEL_COEF = {
    "runaway": (1.17,  0.94, 0.956),
    "front":   (1.0,   1.0,  0.996),
    "pace":    (0.985, 1.0,  0.996),
    "late":    (0.975, 1.0,  1.0),
    "end":     (0.945, 1.0,  0.997),
}
# --- race-hp page: strategy (style) HP coefficient ---
STRATEGY_HP_COEF = {
    "runaway": 0.86, "front": 0.95, "pace": 0.89, "late": 1.0, "end": 0.995,
}
# Pace Chaser carries an extra ~11% stamina penalty (reference doc); applied to MaxHP.
PACE_EXTRA_STAMINA_PENALTY = {"pace": 0.89}

# --- target-speed page: distance proficiency -> target-speed multiplier ---
DIST_PROF_SPEED = {"S": 1.05, "A": 1.0, "B": 0.9, "C": 0.8, "D": 0.6, "E": 0.4, "F": 0.2, "G": 0.1}
# --- race-mechanics page: ground (surface) aptitude -> acceleration multiplier ---
GROUND_PROF_ACCEL = {"S": 1.05, "A": 1.0, "B": 0.9, "C": 0.8, "D": 0.7, "E": 0.5, "F": 0.3, "G": 0.1}
# --- race-mechanics page: distance aptitude -> acceleration multiplier.
# Page cites "E or lower" explicitly (E 0.6 / F 0.5 / G 0.4). A-D mirror the ground
# shape; MANT keeps C+ so the A-D values are rarely load-bearing. Flagged in RaceParams.
DIST_PROF_ACCEL = {"S": 1.05, "A": 1.0, "B": 0.9, "C": 0.8, "D": 0.7, "E": 0.6, "F": 0.5, "G": 0.4}

# Deceleration by phase (race-mechanics page) + HP-out.
DECEL = {0: -1.2, 1: -0.8, 2: -1.0, 3: -1.0}
DECEL_HP_OUT = -1.2
BASE_ACCEL_FLAT = 0.0006          # race-mechanics
BASE_ACCEL_UPHILL = 0.0004        # race-mechanics
START_DASH_ACCEL = 24.0           # race-mechanics: +24 while in start dash
START_SPEED = 3.0                 # target-speed: 3 m/s out of the gate

# Phase index by section number 1..24 (race-mechanics).
def _phase_for_section(section: int) -> int:
    if section <= 4:
        return 0          # opening
    if section <= 16:
        return 1          # middle
    if section <= 20:
        return 2          # final leg / accel zone
    return 3              # last spurt / homestretch


@dataclass
class RaceParams:
    """Calibratable / situational knobs. Defaults are the neutral (Firm/Good, flat)
    case. Magnitudes here are the ONLY values not directly cited; calibrate from data."""
    dt: float = 0.2                 # integration step (s); 0.2 ~halves cost vs 0.1 with negligible rank change
    status_mod: float = 1.0         # race-hp StatusMod (Rushed 1.6 / PaceDown 0.6 / Downhill 0.4)
    ground_mod: float = 1.0         # race-hp GroundMod (Firm/Good 1.0; Soft 1.02; Heavy 1.02)
    # Global HP-drain calibration. NOT cited — fit to the 51 real full-field samples
    # (data/real_race_snapshots.json): drain x1.3 minimises finish-rank error (~1.5)
    # raw-vs-raw before skills are modelled. PROVISIONAL: re-fit once per-phase skill
    # procs land, since skills raise the player's effective spurt/recovery.
    hp_drain_scale: float = 1.3
    # Distance-accel for A-D is mirrored from ground shape (E-G are cited). Kept here
    # so it can be corrected against a source without touching the engine.
    max_seconds: float = 240.0      # safety cap
    # --- aggregate skill model (Task 4) ---
    # Skills proc per the cited Wit gate (proc% = max(20, 100 - 9000/Wit)); rather
    # than simulate every named skill, model the EXPECTED contribution of a horse's
    # skill loadout: a sustained mid/late velocity boost + recovery. Magnitudes are
    # NOT cited — fit to the 51 real fields (which carry skill_count for player AND
    # opponents). velocity_skill_frac/recovery split per skills-recovery page (~20%
    # recovery). Both sides use the same model, so it does not bias the player.
    per_skill_velocity: float = 0.20   # m/s per active velocity skill (fit: 51 fields -> 78% win, rank_err 1.11)
    velocity_skill_frac: float = 0.6   # fraction of a loadout that boosts speed/accel
    recovery_per_skill_frac: float = 0.025  # HP restored per recovery skill (white~1.5%, gold~5.5%)
    # --- field effective strength (Approach A) ---
    # The real game NPC field effectively races ABOVE its displayed/trainer-screen
    # stats: 1768 account_b G1 losses show the player LEADING field-max in
    # speed/stamina/power yet finishing mid-pack. This is NOT a player +400 bug
    # (the live physics path runs the player at displayed stats too); it is the
    # opponent field being under-modeled. `field_effective_uplift` is added to an
    # OPPONENT entrant's stats by the live opponent-builder so a displayed-dominant
    # player keeps only a modest effective lead, letting guts/style/skills decide.
    # 0 = backward-compatible. Fit jointly with the guts knobs below; a flat uplift
    # alone over-buffs the field on speed/power (where the player legitimately wins
    # the anchor set), so the calibrated value is modest and paired with guts-bite.
    field_effective_uplift: float = 0.0
    # --- guts as a real outcome factor (root-cause 2) ---
    # The cited late-race guts term (target-speed page) only fed the spurt target
    # via math.pow(450*Guts, spurt_guts_exp)*spurt_guts_coef and the HP-drain mod
    # (1 + 200/sqrt(600*Guts)). At realistic guts (~290 vs ~350) those move spurt
    # speed by <0.02 m/s and drain by ~3%, far too weak to reproduce the 66%-of-
    # losses guts signal. We expose the cited term's MAGNITUDE (coef) and add a
    # guts-driven SPURT-SUSTAIN penalty drawn from the SAME cited 1+200/sqrt(600*G)
    # family (no new shape): below `guts_sustain_ref` guts, the horse cannot hold
    # the full spurt target. Both knobs apply symmetrically to every entrant.
    spurt_guts_coef: float = 0.0001    # magnitude of the cited last-spurt guts term
    spurt_guts_exp: float = 0.597      # cited exponent (target-speed page); do not invent
    late_guts_sustain: float = 0.0     # strength of the guts spurt-sustain penalty (0 = off)
    guts_sustain_ref: float = 400.0    # guts at/above which the sustain penalty vanishes
    guts_sustain_floor: float = 0.80   # max spurt-target cut from the guts-sustain penalty


def _coef3_for_phase(triplet, phase: int) -> float:
    # speed/accel coef triplets are (early/opening, mid/middle, late[+spurt]).
    return triplet[0] if phase == 0 else (triplet[1] if phase == 1 else triplet[2])


def base_speed(distance_m: float) -> float:
    # target-speed page.
    return 20.0 - (distance_m - 2000.0) / 1000.0


def max_hp(stamina: float, distance_m: float, style: str) -> float:
    # race-hp page. Pace Chaser extra stamina penalty folded in.
    coef = STRATEGY_HP_COEF.get(style, 1.0)
    eff_stam = stamina * PACE_EXTRA_STAMINA_PENALTY.get(style, 1.0)
    return 0.8 * coef * eff_stam + distance_m


def simulate_entrant(
    *,
    stats: dict,
    aptitudes: dict | None = None,
    style: str = "pace",
    distance_m: float = 1600.0,
    surface: str = "turf",
    rng=None,
    params: RaceParams | None = None,
    skill_hooks=None,
    skill_count: int = 0,
    recovery_skill_count: int = 0,
):
    """Run one horse over the course. `stats` are EFFECTIVE in-race stats (caller
    applies the +400 career bonus / mood). Returns a dict with finish `time` (s),
    whether it `stalled` (ran out of HP before the spurt), and diagnostics.

    `skill_hooks` (optional) is a callable(phase, section, state)->dict with optional
    keys {accel, velocity, hp_recover_frac} applied that step — used by the per-phase
    skill-proc layer; the base engine runs fine with it None.
    """
    params = params or RaceParams()
    aptitudes = aptitudes or {}
    style = style if style in STYLE_SPEED_COEF else "pace"

    spd = float(stats.get("speed") or 0)
    stam = float(stats.get("stamina") or 0)
    pwr = float(stats.get("power") or 0)
    guts = float(stats.get("guts") or 0)
    wit = float(stats.get("wit") or 0)

    dist_apt = str(aptitudes.get("distance") or aptitudes.get(_distance_band(distance_m)) or "A").upper()
    surf_apt = str(aptitudes.get("surface") or aptitudes.get(surface) or "A").upper()
    dprof_speed = DIST_PROF_SPEED.get(dist_apt, 1.0)
    gprof_accel = GROUND_PROF_ACCEL.get(surf_apt, 1.0)
    dprof_accel = DIST_PROF_ACCEL.get(dist_apt, 1.0)

    bspeed = base_speed(distance_m)
    hp = max_hp(stam, distance_m, style)
    hp0 = hp

    # Wit section-randomness band (target-speed page), as a fraction.
    if wit > 0:
        mod_max = (wit / 5500.0) * math.log10(max(1.0, wit * 0.1)) / 100.0
    else:
        mod_max = 0.0
    mod_min = mod_max - 0.0065

    # MinSpeed (target-speed page): 0.85*Base + sqrt(200*Guts)*0.001
    min_speed = 0.85 * bspeed + math.sqrt(200.0 * guts) * 0.001

    # --- aggregate skill model (Task 4): expected contribution of the loadout,
    # gated by the cited Wit proc rate. Velocity skills add a sustained mid/late
    # target-speed boost; recovery skills restore HP once on entering the spurt zone.
    proc_rate = max(0.20, 1.0 - 9000.0 / wit) if wit > 0 else 0.20
    n_vel = max(0.0, skill_count - recovery_skill_count) * params.velocity_skill_frac
    skill_velocity_bonus = n_vel * params.per_skill_velocity * proc_rate
    skill_recovery_frac = recovery_skill_count * params.recovery_per_skill_frac * proc_rate
    recovery_done = False

    section_len = distance_m / 24.0
    pos = 0.0
    v = START_SPEED
    t = 0.0
    stalled = False
    spurt_speed = None
    cur_section = 1
    section_rand = _section_rand(rng, mod_min, mod_max)

    while pos < distance_m and t < params.max_seconds:
        section = min(24, int(pos // section_len) + 1)
        if section != cur_section:
            cur_section = section
            section_rand = _section_rand(rng, mod_min, mod_max)
        phase = _phase_for_section(section)

        # ---- target speed for this phase ----
        base_target = bspeed * _coef3_for_phase(STYLE_SPEED_COEF[style], phase) * dprof_speed
        base_target *= (1.0 + section_rand)
        if phase == 3:
            # last spurt: scale up, add speed & guts terms (target-speed page).
            # The guts term's coefficient/exponent are the cited shape with a
            # CALIBRATABLE magnitude (params.spurt_guts_coef/_exp); raising the
            # coef makes guts a real homestretch differentiator instead of a
            # <0.02 m/s rounding term at realistic stats.
            late_target = bspeed * STYLE_SPEED_COEF[style][2] * dprof_speed
            target = ((late_target + 0.01 * bspeed) * 1.05
                      + math.sqrt(500.0 * spd) * dprof_speed * 0.002
                      + math.pow(450.0 * guts, params.spurt_guts_exp) * params.spurt_guts_coef)
            # Guts spurt-SUSTAIN penalty (cited 1+200/sqrt(600*G) family applied to
            # velocity, not just drain): a horse below guts_sustain_ref cannot hold
            # the full spurt target in the homestretch. Symmetric across entrants.
            if params.late_guts_sustain > 0.0 and guts < params.guts_sustain_ref:
                deficit = (200.0 / math.sqrt(600.0 * max(1.0, guts))
                           - 200.0 / math.sqrt(600.0 * params.guts_sustain_ref))
                target *= max(params.guts_sustain_floor, 1.0 - params.late_guts_sustain * max(0.0, deficit))
            target *= (1.0 + section_rand)
            if spurt_speed is None:
                spurt_speed = target
        else:
            target = base_target
        # skills add a sustained velocity boost from mid-race onward (phase >= 1)
        if phase >= 1:
            target += skill_velocity_bonus
        target = max(target, min_speed)

        # recovery skills restore HP once on entering the late-race / accel zone
        if phase >= 2 and not recovery_done and skill_recovery_frac > 0:
            hp = min(hp0, hp + hp0 * skill_recovery_frac)
            recovery_done = True

        hp_out = hp <= 0.0
        if hp_out:
            target = min_speed   # cannot sustain pace once HP is gone

        # ---- acceleration / deceleration toward target ----
        if v < target:
            accel = (BASE_ACCEL_FLAT * math.sqrt(500.0 * pwr)
                     * _coef3_for_phase(STYLE_ACCEL_COEF[style], min(phase, 2))
                     * gprof_accel * dprof_accel)
            if v < 0.85 * bspeed and phase == 0:
                accel += START_DASH_ACCEL
            dv = accel
        else:
            dv = (DECEL_HP_OUT if hp_out else DECEL[phase])

        # ---- skill hook (per-phase procs) ----
        if skill_hooks is not None:
            mod = skill_hooks(phase=phase, section=section, v=v, hp=hp, hp0=hp0) or {}
            if mod.get("accel"):
                dv += float(mod["accel"])
            if mod.get("velocity"):
                v += float(mod["velocity"])
            if mod.get("hp_recover_frac"):
                hp = min(hp0, hp + hp0 * float(mod["hp_recover_frac"]))

        v = max(min_speed if not hp_out else 0.0, v + dv * params.dt)

        # ---- HP drain (race-hp page) ----
        drain = 20.0 * (v - bspeed + 12.0) ** 2 / 144.0 * params.status_mod * params.ground_mod * params.hp_drain_scale
        if phase >= 2:  # late-race guts mod
            drain *= (1.0 + 200.0 / math.sqrt(600.0 * max(1.0, guts)))
        hp -= drain * params.dt
        if hp <= 0.0 and not stalled:
            stalled = True

        pos += v * params.dt
        t += params.dt

    return {
        "time": t,
        "finished": pos >= distance_m,
        "stalled": stalled,
        "hp_left": max(0.0, hp),
        "hp0": hp0,
        "avg_speed": (distance_m / t) if t > 0 else 0.0,
        "spurt_speed": spurt_speed,
        "base_speed": bspeed,
    }


def _distance_band(distance_m: float) -> str:
    if distance_m <= 1400:
        return "sprint"
    if distance_m <= 1800:
        return "mile"
    if distance_m <= 2400:
        return "medium"
    return "long"


def _section_rand(rng, lo, hi):
    if rng is None or hi <= lo:
        return 0.0
    return lo + (hi - lo) * rng.random()


def simulate_race(entrants, *, distance_m, surface="turf", rng=None, params=None):
    """Simulate a full field. `entrants` is a list of dicts with keys
    {stats, aptitudes, style, (id)}. Returns the list sorted by finish time with
    `rank` assigned (1 = winner). Lower time wins; stalled horses fall back."""
    results = []
    for e in entrants:
        out = simulate_entrant(
            stats=e["stats"], aptitudes=e.get("aptitudes"), style=e.get("style", "pace"),
            distance_m=distance_m, surface=surface, rng=rng, params=params,
            skill_hooks=e.get("skill_hooks"),
            skill_count=int(e.get("skill_count") or 0),
            recovery_skill_count=int(e.get("recovery_skill_count") or 0),
        )
        out["id"] = e.get("id")
        out["entrant"] = e
        results.append(out)
    # not finished -> sort by distance covered (more is better) then time
    results.sort(key=lambda r: (0 if r["finished"] else 1, r["time"]))
    for i, r in enumerate(results):
        r["rank"] = i + 1
    return results
