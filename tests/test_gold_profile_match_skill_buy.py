"""Force-buy gold skills that match the run's style/distance.

User-specified policy: whenever a gold-tier tip (tip_rarity > 0) appears
that matches the skill plan's style or distance, the bot should buy it
within budget — regardless of optimizer score. Gold sparks at a 40%
generation rate vs 20% for plain whites, so profile-matched gold
purchases are the highest spark-rate yield per SP available.
"""

import unittest
from pathlib import Path

from career_bot.skills import SkillBuyer


BASE_DIR = Path(__file__).resolve().parents[1]


class GoldProfileMatchTests(unittest.TestCase):
    def setUp(self):
        self.buyer = SkillBuyer(BASE_DIR)

    def _candidate(self, name, tip_rarity=0, skill_id=99001, cost=180):
        return {
            "skill_id": skill_id,
            "group_id": skill_id // 10 if skill_id < 100000 else skill_id,
            "name": name,
            "tip_rarity": tip_rarity,
            "cost": cost,
        }

    def test_gold_skill_matching_style_passes_match_check(self):
        """A gold tip whose name is in STYLE_SKILLS[front_runner] is
        flagged as a profile-match."""
        preset = {"skill_profile_style": "front_runner", "skill_profile_distance": "mile"}
        candidate = self._candidate("Front Runner Straightaways", tip_rarity=1)
        self.assertTrue(self.buyer._is_gold_match_for_profile(candidate, preset))

    def test_gold_skill_matching_distance_passes_match_check(self):
        preset = {"skill_profile_style": "front_runner", "skill_profile_distance": "mile"}
        candidate = self._candidate("Mile Maven", tip_rarity=1)
        self.assertTrue(self.buyer._is_gold_match_for_profile(candidate, preset))

    def test_non_gold_does_not_pass_even_when_profile_matches(self):
        """A plain white skill (tip_rarity=0) that matches the profile
        should NOT be force-bought. The user opted in specifically for
        gold tips."""
        preset = {"skill_profile_style": "front_runner", "skill_profile_distance": "mile"}
        candidate = self._candidate("Front Runner Straightaways", tip_rarity=0)
        self.assertFalse(self.buyer._is_gold_match_for_profile(candidate, preset))

    def test_gold_without_profile_match_does_not_force_buy(self):
        """A gold tip that doesn't match the style or distance
        shouldn't trigger force-buy. The user's policy was 'gold AND
        matches profile' — gold alone isn't enough."""
        preset = {"skill_profile_style": "front_runner", "skill_profile_distance": "mile"}
        # Long-distance / late-surger skill while plan is front/mile — no match.
        candidate = self._candidate("Long Distance Corners", tip_rarity=1)
        self.assertFalse(self.buyer._is_gold_match_for_profile(candidate, preset))

    def test_select_hard_priority_includes_gold_match(self):
        """The hard-priority pass should include the gold-matching
        candidate even when no explicit skill-plan key matched it."""
        preset = {
            "skill_profile_style": "front_runner",
            "skill_profile_distance": "mile",
            # No learn_skill_list → no user-named hard keys.
        }
        chara = {"skill_point": 500}
        candidates = [
            self._candidate("Front Runner Corners", tip_rarity=1, skill_id=20001, cost=160),
            self._candidate("Some Random White", tip_rarity=0, skill_id=20002, cost=100),
        ]
        selected = self.buyer._select_hard_priority_candidates(candidates, 500, chara, preset, {})
        names = {s["name"] for s in selected}
        self.assertIn("Front Runner Corners", names)
        # The non-gold non-priority skill should NOT be in hard priorities.
        self.assertNotIn("Some Random White", names)

    def test_select_hard_priority_marks_reason(self):
        """The selected gold-match entry should carry the new
        `hard_priority_reason` field so downstream logging/dashboard
        can distinguish user-named priorities from gold-match
        force-buys."""
        preset = {
            "skill_profile_style": "front_runner",
            "skill_profile_distance": "mile",
        }
        chara = {"skill_point": 500}
        candidates = [self._candidate("Front Runner Straightaways", tip_rarity=1, skill_id=20003, cost=160)]
        selected = self.buyer._select_hard_priority_candidates(candidates, 500, chara, preset, {})
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0].get("hard_priority_reason"), "gold_profile_match")
        self.assertTrue(selected[0].get("hard_priority"))

    def test_budget_caps_force_buy(self):
        """If budget runs out, the gold-matching pass should stop;
        the function must not overdraft."""
        preset = {
            "skill_profile_style": "front_runner",
            "skill_profile_distance": "mile",
        }
        chara = {"skill_point": 200}
        candidates = [
            self._candidate("Front Runner Corners", tip_rarity=1, skill_id=21001, cost=160),
            self._candidate("Mile Maven", tip_rarity=1, skill_id=21002, cost=180),
            self._candidate("Mile Straightaways", tip_rarity=1, skill_id=21003, cost=200),
        ]
        selected = self.buyer._select_hard_priority_candidates(candidates, 200, chara, preset, {})
        total_cost = sum(int(s.get("cost") or 0) for s in selected)
        self.assertLessEqual(total_cost, 200, f"force-buy overshot budget: {total_cost} > 200")


if __name__ == "__main__":
    unittest.main()
