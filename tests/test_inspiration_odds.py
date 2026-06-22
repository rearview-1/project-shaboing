"""Pins the cited inheritance/inspiration model (uma.guide/sparks) and the
shared odds DB so a future refactor can't silently drift the rates.

Source of truth: public/assets/data/inspiration_odds.json. The sim
(career_bot.career_simulator._compute_legacy_effects_cited) and the front end
(public/app.js INSPIRATION_ODDS_FALLBACK) must both reflect these values.
"""
import json
from pathlib import Path

from career_bot.career_simulator import CareerSimulator, _load_inspiration_odds
from tests.test_career_simulator import _make_preset

ROOT = Path(__file__).resolve().parents[1]
DECK = [20031, 30028, 30016, 30007, 20008]


def _sim(cited=True, affinity=0):
    rc = {
        "support_card_ids": DECK,
        "support_card_lb_levels": {str(i): {"lb": 4} for i in DECK},
        "friend_card_id": 30032,
        "trainee_card_id": 101502,
        "parent_id_1": 1,
        "parents": [{
            "instance_id": 1, "name": "TestParent",
            "tree": {"self": {"factors": [
                {"category": "stat", "name": "Speed", "stars": 3, "id": 103},
                {"category": "aptitude", "name": "Mile", "stars": 3, "id": 9903},
                {"category": "skill", "name": "Pinned White Skill", "stars": 3, "id": 200001},
            ]}},
        }],
    }
    deck = [{"support_card_id": i, "lb_level": 4} for i in DECK]
    p = _make_preset()
    p["_run_context"] = rc
    p["scenario_id"] = 4
    p["sim_inheritance_cited_odds"] = cited
    p["sim_inheritance_affinity"] = affinity
    return CareerSimulator(preset=p, deck=deck, seed=0)


def test_db_has_cited_base_odds():
    """The DB matches uma.guide/sparks verbatim."""
    odds = _load_inspiration_odds()
    by_star = odds["base_odds_by_star"]
    assert by_star["blue"] == {"1": 0.70, "2": 0.80, "3": 0.90}
    assert by_star["pink"] == {"1": 0.01, "2": 0.03, "3": 0.05}
    assert by_star["green"] == {"1": 0.05, "2": 0.10, "3": 0.15}
    assert by_star["race"] == {"1": 0.01, "2": 0.02, "3": 0.03}
    assert by_star["white"] == {"1": 0.03, "2": 0.06, "3": 0.09}
    assert int(odds["activations_per_career"]) == 3
    assert odds["blue_stat_roll"]["3"] == [1, 28]


def test_frontend_fallback_matches_db():
    """public/app.js INSPIRATION_ODDS_FALLBACK must mirror the DB so the UI is
    correct even before the fetch resolves."""
    odds = _load_inspiration_odds()
    app_js = (ROOT / "public" / "app.js").read_text(encoding="utf-8")
    # spot-check the cited rates appear in the fallback block
    for rate in ("0.70", "0.80", "0.90", "0.03", "0.06", "0.09", "0.05", "0.10", "0.15"):
        assert rate in app_js, f"front-end fallback missing rate {rate}"
    assert "INSPIRATION_ODDS_FALLBACK" in app_js


def test_pink_aptitude_is_probabilistic_not_guaranteed():
    """The cited model must NOT guarantee aptitude upgrades (cited pink = 1/3/5%).
    A single 3* mile spark at affinity 0 should upgrade ~14% of careers
    (1-(0.95)^3 = 0.143), and the legacy deterministic path should upgrade ~always."""
    sim = _sim(cited=True, affinity=0)
    n = 2000
    ups = 0
    for s in range(n):
        sim._career_seed = s
        le = sim._compute_legacy_effects_cited()
        if "mile" in (le.get("aptitude_upgrades") or {}):
            ups += 1
    rate = ups / n
    assert 0.10 <= rate <= 0.19, f"cited pink mile upgrade rate {rate:.3f} not ~0.143"

    # Legacy deterministic path guarantees the upgrade (the bug we replaced).
    sim_old = _sim(cited=False)
    le_old = sim_old.legacy_effects
    assert "mile" in (le_old.get("aptitude_upgrades") or {}), "legacy path should be deterministic"


def test_white_skill_learn_rate_matches_cited():
    """A 3* white skill at affinity 0 is learned ~25% of careers (1-(0.91)^3)."""
    sim = _sim(cited=True, affinity=0)
    n = 2000
    learned = 0
    for s in range(n):
        sim._career_seed = s
        le = sim._compute_legacy_effects_cited()
        if any("pinned white skill" in (h.get("name", "").lower())
               for h in (le.get("legacy_skill_hints") or [])):
            learned += 1
    rate = learned / n
    assert 0.19 <= rate <= 0.31, f"cited white-skill learn rate {rate:.3f} not ~0.247"


def test_affinity_raises_odds():
    """InheritanceOdds = base * (1 + affinity/100): higher affinity -> more upgrades."""
    def mile_rate(affinity):
        sim = _sim(cited=True, affinity=affinity)
        n = 1500
        ups = sum(
            1 for s in range(n)
            if (setattr(sim, "_career_seed", s) or "mile" in (sim._compute_legacy_effects_cited().get("aptitude_upgrades") or {}))
        )
        return ups / n
    assert mile_rate(200) > mile_rate(0) + 0.10
