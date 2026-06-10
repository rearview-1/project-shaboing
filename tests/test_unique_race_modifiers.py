import unittest

from career_bot.unique_race_modifiers import race_unique_recovery_profile


class UniqueRaceModifierTests(unittest.TestCase):
    def test_mejiro_bright_recovery_only_applies_to_long_races(self):
        long_profile = race_unique_recovery_profile(
            {"card_id": 107401},
            distance="Long",
            style="front_runner",
        )
        mile_profile = race_unique_recovery_profile(
            {"card_id": 107401},
            distance="Mile",
            style="front_runner",
        )

        self.assertEqual(long_profile.get("skill_equivalent"), 0.75)
        self.assertEqual(mile_profile, {})

    def test_biwa_hayahide_recovery_applies_to_medium_and_long(self):
        medium_profile = race_unique_recovery_profile(
            {"card_id": 102301},
            distance="Medium",
            style="pace_chaser",
        )
        sprint_profile = race_unique_recovery_profile(
            {"card_id": 102301},
            distance="Sprint",
            style="pace_chaser",
        )

        self.assertEqual(medium_profile.get("skill_equivalent"), 0.85)
        self.assertEqual(sprint_profile, {})

    def test_grass_wonder_recovery_profile_is_counted_by_default(self):
        profile = race_unique_recovery_profile(
            {"card_id": 101102},
            distance="Long",
            style="late_surger",
        )

        self.assertEqual(profile.get("source"), "stamina_recovery_unique")
        self.assertEqual(profile.get("skill_equivalent"), 0.85)


if __name__ == "__main__":
    unittest.main()
