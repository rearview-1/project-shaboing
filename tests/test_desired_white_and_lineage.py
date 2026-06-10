"""Desired-white-spark force-buy and lineage-aware skill scoring.

Two related but independent spark-odds features:

A) Force-buy candidates whose name matches the user's
   `desired_parent_sparks.white` list (the DESIRED WHITE box on the
   dashboard setup area). Highest priority — the user explicitly
   named these as spark targets, so the buyer prioritizes them above
   the gold profile-match force-buy.

B) Multiply each candidate's optimizer score by 1.1^lineage_count
   (capped at 1.5x), where lineage_count is the number of times the
   candidate's skill appears in the trainee's legacies (their two
   parents + the parents' parents). Mirrors the empirical
   `WHITE_GENERATION_LINEAGE_MULTIPLIER` from spark_rates.py — a
   skill already in the lineage has a meaningfully higher chance of
   generating a white spark when bought.
"""

import unittest
from pathlib import Path

from career_bot.skills import SkillBuyer


BASE_DIR = Path(__file__).resolve().parents[1]


def _candidate(name, *, tip_rarity=0, skill_id=99001, cost=180, group_id=None):
    return {
        "skill_id": skill_id,
        "group_id": group_id if group_id is not None else (skill_id // 10 if skill_id < 100000 else skill_id),
        "name": name,
        "tip_rarity": tip_rarity,
        "cost": cost,
    }


class DesiredWhiteForceBuyTests(unittest.TestCase):
    def setUp(self):
        self.buyer = SkillBuyer(BASE_DIR)

    def test_desired_white_keys_normalized(self):
        preset = {"desired_parent_sparks": {"white": ["NHK Mile C.", "Firm Conditions"]}}
        keys = self.buyer._desired_white_skill_keys(preset)
        self.assertEqual(len(keys), 2)

    def test_empty_when_no_desired_whites(self):
        self.assertEqual(self.buyer._desired_white_skill_keys({}), set())
        self.assertEqual(self.buyer._desired_white_skill_keys({"desired_parent_sparks": {}}), set())

    def test_force_buys_desired_white_candidate(self):
        preset = {
            "skill_profile_style": "front_runner",
            "skill_profile_distance": "mile",
            "desired_parent_sparks": {"white": ["Front Runner Straightaways"]},
        }
        chara = {"skill_point": 500}
        candidates = [
            _candidate("Front Runner Straightaways", tip_rarity=0, skill_id=30001, cost=180),
            _candidate("Some Other White", tip_rarity=0, skill_id=30002, cost=100),
        ]
        selected = self.buyer._select_hard_priority_candidates(candidates, 500, chara, preset, {})
        names_to_reasons = {s["name"]: s.get("hard_priority_reason") for s in selected}
        # Front Runner Straightaways should be force-bought even with
        # tip_rarity=0 because it's named in DESIRED WHITE.
        self.assertEqual(names_to_reasons.get("Front Runner Straightaways"), "desired_white_spark")
        self.assertNotIn("Some Other White", names_to_reasons)

    def test_desired_white_takes_priority_over_gold_match(self):
        """Both reasons can fire in the same selection. The selected
        rows must keep their distinct reasons (no overwrite) so the
        dashboard can tell them apart. Using skill_ids that floor-div
        to DIFFERENT group_ids so the dedup doesn't collapse them."""
        preset = {
            "skill_profile_style": "front_runner",
            "skill_profile_distance": "mile",
            "desired_parent_sparks": {"white": ["NHK Mile C."]},
        }
        chara = {"skill_point": 1000}
        candidates = [
            _candidate("NHK Mile C.", tip_rarity=0, skill_id=31001, cost=180),
            _candidate("Front Runner Corners", tip_rarity=1, skill_id=42001, cost=180),
        ]
        selected = self.buyer._select_hard_priority_candidates(candidates, 1000, chara, preset, {})
        reasons = {s["name"]: s.get("hard_priority_reason") for s in selected}
        self.assertEqual(reasons.get("NHK Mile C."), "desired_white_spark")
        self.assertEqual(reasons.get("Front Runner Corners"), "gold_profile_match")


class LineageMultiplierTests(unittest.TestCase):
    def setUp(self):
        self.buyer = SkillBuyer(BASE_DIR)
        # Patch the parent_library cache with a synthetic lineage so we
        # don't rely on whatever's on disk.
        self.buyer._parent_library_cache = {
            "parents": [
                {
                    "instance_id": 1001,
                    "trained_chara_id": 1001,
                    "tree": {
                        "self": {"factors": [
                            {"category": "skill", "id": 50001, "name": "Lineage Skill One"},
                        ]},
                        "p1": {"factors": [
                            {"category": "skill", "id": 50001, "name": "Lineage Skill One"},
                            {"category": "skill", "id": 50002, "name": "Lineage Skill Two"},
                        ]},
                        "p2": {"factors": []},
                    },
                },
                {
                    "instance_id": 1002,
                    "trained_chara_id": 1002,
                    "tree": {
                        "self": {"factors": [
                            {"category": "skill", "id": 50001, "name": "Lineage Skill One"},
                        ]},
                        "p1": {"factors": []},
                        "p2": {"factors": []},
                    },
                },
            ],
        }

    def _chara(self):
        return {
            "succession_trained_chara_id_1": 1001,
            "succession_trained_chara_id_2": 1002,
        }

    def test_no_lineage_multiplier_when_chara_has_no_legacies(self):
        chara = {}
        mult = self.buyer._lineage_multiplier(_candidate("Anything", skill_id=50001), chara)
        self.assertEqual(mult, 1.0)

    def test_one_lineage_match_yields_1_1(self):
        # Skill 50002 appears once (legacy 1001's p1).
        cand = _candidate("Lineage Skill Two", skill_id=50002)
        mult = self.buyer._lineage_multiplier(cand, self._chara())
        self.assertAlmostEqual(mult, 1.1, places=3)

    def test_multiple_matches_compound(self):
        # Skill 50001 appears 3 times across the lineage (legacy 1001
        # self + p1, legacy 1002 self) → 1.1^3 = 1.331.
        cand = _candidate("Lineage Skill One", skill_id=50001)
        mult = self.buyer._lineage_multiplier(cand, self._chara())
        self.assertAlmostEqual(mult, 1.1 ** 3, places=3)

    def test_multiplier_capped_at_1_5(self):
        # Synthesize a lineage with many copies of the same skill
        # (more than enough to push 1.1^N past 1.5).
        self.buyer._parent_library_cache = {
            "parents": [{
                "instance_id": 1003,
                "trained_chara_id": 1003,
                "tree": {
                    "self": {"factors": [{"category": "skill", "id": 60001, "name": "X"}] * 10},
                    "p1": {"factors": []},
                    "p2": {"factors": []},
                },
            }],
        }
        self.buyer._lineage_cache = {}
        chara = {"succession_trained_chara_id_1": 1003}
        mult = self.buyer._lineage_multiplier(_candidate("X", skill_id=60001), chara)
        self.assertLessEqual(mult, 1.5)

    def test_non_skill_factors_ignored(self):
        # Only category=="skill" factors should contribute.
        self.buyer._parent_library_cache = {
            "parents": [{
                "instance_id": 1004,
                "trained_chara_id": 1004,
                "tree": {
                    "self": {"factors": [
                        {"category": "stat", "id": 70001, "name": "Speed"},
                        {"category": "aptitude", "id": 70002, "name": "Mile"},
                    ]},
                },
            }],
        }
        self.buyer._lineage_cache = {}
        chara = {"succession_trained_chara_id_1": 1004}
        # Stat-category factor with id 70001 shouldn't match a skill
        # with the same id (different namespace anyway, but the filter
        # should make it bulletproof).
        mult = self.buyer._lineage_multiplier(_candidate("Speed", skill_id=70001), chara)
        self.assertEqual(mult, 1.0)

    def test_name_match_works_when_id_missing(self):
        """Some library entries may have name but no id. The matcher
        should still pick those up."""
        self.buyer._parent_library_cache = {
            "parents": [{
                "instance_id": 1005,
                "trained_chara_id": 1005,
                "tree": {
                    "self": {"factors": [{"category": "skill", "name": "Named Only"}]},
                },
            }],
        }
        self.buyer._lineage_cache = {}
        chara = {"succession_trained_chara_id_1": 1005}
        cand = _candidate("Named Only", skill_id=80001)
        mult = self.buyer._lineage_multiplier(cand, chara)
        self.assertAlmostEqual(mult, 1.1, places=3)


if __name__ == "__main__":
    unittest.main()
