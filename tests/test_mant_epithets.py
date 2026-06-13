"""MANT epithet engine — full 35-route table.

Pins the corrections from 2026-06-13: all 35 epithets modeled (32 stat, 3
hint), Incredible counts ONCE (Japan Cup OR Arima), epithet chains resolve
(Legendary needs Spring+Fall Champion + Lady/Stunning), hint epithets grant 0
stat, and Race Bonus does NOT scale epithet rewards.
"""

import json
import unittest
from pathlib import Path

from career_bot.career_simulator import (
    CareerSimulator,
    MANT_EPITHET_SETS,
    hydrate_preset_with_latest_session_context,
)

ROOT = Path(__file__).resolve().parents[1]


def _account_b_sim():
    preset_path = ROOT / "uma_runtime" / "instances" / "account_b" / "instance_learning" / "presets" / "xguri parent.json"
    preset = json.loads(preset_path.read_text(encoding="utf-8-sig"))
    preset["sim_runtime_instance"] = "account_b"
    preset = hydrate_preset_with_latest_session_context(preset, ROOT)
    deck = (preset.get("_run_context") or {}).get("support_cards") or None
    return CareerSimulator(preset=preset, deck=deck, seed=42)


def _award_all_scheduled(sim):
    """Mark every scheduled race won and run the epithet evaluator (ceiling)."""
    sim.race_names_won = set()
    sim.won_race_meta = []
    sim.epithets_completed = []
    for row in (sim.scheduled_g1s or []):
        _t, pid, name = row[0], row[1], row[2]
        cat = sim.race_catalog_by_program_id.get(int(pid)) or {}
        sim.race_names_won.add(name)
        sim.won_race_meta.append({
            "name": name,
            "grade": (cat.get("type") or "").upper(),
            "terrain": (cat.get("terrain") or "").title(),
            "distance": (cat.get("distance") or "").title(),
            "venue": cat.get("venue") or "",
            "meters": sim._race_distance_meters(int(pid)),
        })
    sim._apply_epithet_bonuses_if_completed(1.0)


class EpithetTableTests(unittest.TestCase):
    def test_full_table_has_35_entries_32_stat_3_hint(self):
        self.assertEqual(len(MANT_EPITHET_SETS), 35)
        stat = [e for e in MANT_EPITHET_SETS if e.get("reward", "stat") == "stat"]
        hint = [e for e in MANT_EPITHET_SETS if e.get("reward") == "hint"]
        self.assertEqual(len(stat), 32)
        self.assertEqual(len(hint), 3)
        self.assertEqual(
            {e["name"] for e in hint},
            {"Mile a Minute", "Legendary", "Dirt G1 Dominator"},
        )

    def test_incredible_is_single_epithet(self):
        names = [e["name"] for e in MANT_EPITHET_SETS]
        self.assertIn("Incredible", names)
        self.assertNotIn("Incredible Classic JC", names)
        self.assertNotIn("Incredible Classic Arima", names)


class AccountBCeilingTests(unittest.TestCase):
    def setUp(self):
        self.sim = _account_b_sim()
        _award_all_scheduled(self.sim)
        self.fired = {e["name"]: e for e in self.sim.epithets_completed}

    def test_classic_and_spring_autumn_routes_fire(self):
        for name in ("Stunning", "Incredible", "Phenomenal",
                     "Spring Champion", "Fall Champion", "Shield Bearer",
                     "Breakneck Miler"):
            self.assertIn(name, self.fired, f"{name} should fire on the turf route")

    def test_legendary_chain_fires_as_hint(self):
        # Spring + Fall Champion + Stunning are all present -> Legendary.
        self.assertIn("Legendary", self.fired)
        self.assertEqual(self.fired["Legendary"]["reward"], "hint")
        self.assertEqual(self.fired["Legendary"]["bonus"], 0)

    def test_both_distance_leaders_fire_with_real_meters(self):
        # 19 standard + 14 non-standard wins on the route -> both fire.
        self.assertIn("Standard Distance Leader", self.fired)
        self.assertIn("Non-Standard Distance Leader", self.fired)

    def test_tiara_and_dirt_routes_do_not_fire_on_turf_colt_schedule(self):
        for name in ("Lady", "Heroine", "Goddess", "Dirty Work",
                     "Dirt G1 Achiever"):
            self.assertNotIn(name, self.fired, f"{name} must not fire here")

    def test_globe_trotter_excludes_home_country(self):
        # Only Saudi Arabia + American are foreign-named (< 3); Japan Cup /
        # Japanese Derby must not count toward Globe-Trotter.
        self.assertNotIn("Globe-Trotter", self.fired)

    def test_stat_total_matches_user_verified_ceiling(self):
        stat_total = sum(int(e["bonus"]) * 2 for e in self.sim.epithets_completed if e["reward"] == "stat")
        # User-verified all-win ceiling: exactly 270.
        self.assertEqual(stat_total, 270)


class UniqueSkillLevelTests(unittest.TestCase):
    """Trainee unique-skill level (1-4) from MANT fan-checkpoint gates."""

    def setUp(self):
        self.sim = _account_b_sim()

    def _set(self, jr, cl, sr):
        self.sim._fans_end_junior = jr
        self.sim._fans_end_classic = cl
        self.sim._fans_end_senior = sr
        self.sim.state["fans"] = sr

    def test_lv1_when_no_gate_met(self):
        self._set(0, 0, 0)
        self.assertEqual(self.sim._estimated_unique_level(), 1)

    def test_lv2_when_only_junior_gate_met(self):
        self._set(6000, 50000, 50000)
        self.assertEqual(self.sim._estimated_unique_level(), 2)

    def test_lv4_caps_for_full_career(self):
        self._set(10000, 80000, 200000)
        self.assertEqual(self.sim._estimated_unique_level(), 4)

    def test_preset_override_wins(self):
        self.sim.preset["sim_rating_unique_level"] = 3
        self._set(10000, 80000, 200000)
        self.assertEqual(self.sim._estimated_unique_level(), 3)


if __name__ == "__main__":
    unittest.main()
