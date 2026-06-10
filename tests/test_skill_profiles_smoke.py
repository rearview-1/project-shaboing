import unittest

from career_bot.skill_profiles import build_skill_priority_rows, normalize_distance, normalize_style, split_skill_text


class SkillProfileSmokeTests(unittest.TestCase):
    def test_build_skill_priority_rows_prioritizes_buy_on_sight_then_profile(self):
        rows = build_skill_priority_rows("Groundwork\nCorner Adept", "late surger", "medium")

        self.assertEqual(rows[0], ["Groundwork", "Corner Adept"])
        self.assertIn("Late Surger Corners", rows[1])
        self.assertIn("Medium Corners", rows[1])
        self.assertEqual(rows[1].count("Groundwork"), 1)

    def test_style_and_distance_aliases_normalize(self):
        self.assertEqual(normalize_style("sashi"), "late_surger")
        self.assertEqual(normalize_style("front"), "front_runner")
        self.assertEqual(normalize_distance("middle"), "medium")
        self.assertEqual(normalize_distance("short"), "sprint")

    def test_split_skill_text_accepts_commas_and_lines(self):
        self.assertEqual(split_skill_text("Groundwork, Corner Adept\nSlipstream"), ["Groundwork", "Corner Adept", "Slipstream"])


if __name__ == "__main__":
    unittest.main()
