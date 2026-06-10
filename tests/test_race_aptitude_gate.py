"""Race aptitude gate — refuse races where distance or surface
aptitude is at or below the configured threshold (default C).

Style is intentionally NOT gated: a front-runner uma may need to run
late-surger on Kikuka Sho for stamina reasons, so we don't lock the
bot out of races on style aptitude alone. Per user instruction.
"""

import unittest
from pathlib import Path

from career_bot.races import RacePlanner


BASE_DIR = Path(__file__).resolve().parents[1]


def _state(chara_overrides=None):
    chara = {
        "turn": 30,
        "proper_distance_short": 5,  # C
        "proper_distance_mile": 7,    # A
        "proper_distance_middle": 8,  # S
        "proper_distance_long": 5,    # C  <- low long aptitude
        "proper_ground_turf": 8,      # S
        "proper_ground_dirt": 3,      # E  <- low dirt aptitude
    }
    chara.update(chara_overrides or {})
    return {"data": {"chara_info": chara}}


class AptitudeGateTests(unittest.TestCase):
    def setUp(self):
        self.planner = RacePlanner(BASE_DIR)

    def test_rejects_when_distance_aptitude_at_or_below_c(self):
        # Distance=Long → uma's proper_distance_long=5 (C) → blocked.
        entry = {"program_id": 9999, "name": "Made Up Long Turf G1",
                 "distance": "Long", "terrain": "Turf"}
        eligible = self.planner.aptitude_eligible(_state(), {}, 9999, entry)
        self.assertFalse(eligible)
        self.assertEqual(self.planner.last_skip_reason["reason"], "off_aptitude")
        failed_axes = self.planner.last_skip_reason["failed_axes"]
        self.assertEqual(len(failed_axes), 1)
        self.assertEqual(failed_axes[0]["axis"], "distance")
        self.assertEqual(failed_axes[0]["key"], "long")

    def test_rejects_when_surface_aptitude_at_or_below_c(self):
        # Surface=Dirt → uma's proper_ground_dirt=3 (E) → blocked.
        entry = {"program_id": 9998, "name": "Made Up Mile Dirt G1",
                 "distance": "Mile", "terrain": "Dirt"}
        eligible = self.planner.aptitude_eligible(_state(), {}, 9998, entry)
        self.assertFalse(eligible)
        failed_axes = self.planner.last_skip_reason["failed_axes"]
        # Mile is A so only surface should be flagged.
        self.assertEqual({a["axis"] for a in failed_axes}, {"surface"})

    def test_rejects_when_both_distance_and_surface_low(self):
        entry = {"program_id": 9997, "name": "Long Dirt Race",
                 "distance": "Long", "terrain": "Dirt"}
        eligible = self.planner.aptitude_eligible(_state(), {}, 9997, entry)
        self.assertFalse(eligible)
        axes = {a["axis"] for a in self.planner.last_skip_reason["failed_axes"]}
        self.assertEqual(axes, {"distance", "surface"})

    def test_allows_when_both_above_threshold(self):
        entry = {"program_id": 9996, "name": "Mile Turf",
                 "distance": "Mile", "terrain": "Turf"}
        self.assertTrue(self.planner.aptitude_eligible(_state(), {}, 9996, entry))

    def test_style_aptitude_is_not_gated_even_if_low(self):
        """Even if we hypothetically pass style aptitude into the
        entry, the gate must not block based on it. A Front Runner
        running Kikuka Sho on stamina is a valid play."""
        entry = {
            "program_id": 9995,
            "name": "Some Mile Turf",
            "distance": "Mile",
            "terrain": "Turf",
            "style": "late_surger",  # would be low for a Front Runner uma
        }
        chara = {
            "proper_distance_mile": 7,
            "proper_ground_turf": 7,
            "proper_running_style_sashi": 2,  # F — low late_surger
            "proper_running_style_nige": 8,  # S — high front_runner
        }
        self.assertTrue(self.planner.aptitude_eligible(_state(chara), {}, 9995, entry))

    def test_gate_can_be_disabled_via_preset(self):
        entry = {"program_id": 9994, "name": "Dirt Race",
                 "distance": "Mile", "terrain": "Dirt"}
        preset = {"race_aptitude_gate_enabled": False}
        self.assertTrue(self.planner.aptitude_eligible(_state(), preset, 9994, entry))

    def test_threshold_b_blocks_c_rank_aptitudes(self):
        """When threshold raised to B, even C-rank distance becomes
        a block. Used by stricter parent-farming setups."""
        entry = {"program_id": 9993, "name": "Sprint Turf",
                 "distance": "Sprint", "terrain": "Turf"}
        preset = {"race_aptitude_gate_threshold": "B"}
        # proper_distance_short = 5 (C), threshold B (6) → blocked.
        self.assertFalse(self.planner.aptitude_eligible(_state(), preset, 9993, entry))

    def test_threshold_d_allows_c_rank_through(self):
        """When threshold lowered to D, C-rank passes. Used by lenient
        setups where partial proficiency is acceptable."""
        entry = {"program_id": 9992, "name": "Sprint Turf",
                 "distance": "Sprint", "terrain": "Turf"}
        preset = {"race_aptitude_gate_threshold": "D"}
        # proper_distance_short = 5 (C), threshold D (4) → passes.
        self.assertTrue(self.planner.aptitude_eligible(_state(), preset, 9992, entry))

    def test_override_forced_races_bypass(self):
        entry = {"program_id": 9991, "name": "Dirt Race",
                 "distance": "Mile", "terrain": "Dirt"}
        preset = {"override_off_aptitude_forced_races": True}
        self.assertTrue(self.planner.aptitude_eligible(_state(), preset, 9991, entry))


if __name__ == "__main__":
    unittest.main()
