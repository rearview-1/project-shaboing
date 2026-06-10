import tempfile
import unittest
from pathlib import Path

from career_bot.deck_advice import advise_decks
from career_bot.observed_profiles import (
    append_team_observations,
    load_observation_samples,
    samples_from_team,
    summarize_observation_samples,
)


def support_card(card_id, card_type="Speed"):
    return {
        "support_card_id": card_id,
        "name": f"Support {card_id}",
        "type": card_type,
        "rarity": "SSR",
        "limit_break_count": 4,
        "level": 50,
    }


def observed_team(style="Front", distance="long", support_ids=None, score=21480):
    support_ids = support_ids or [1, 2, 3, 4, 5]
    return {
        "trainer_id": 1234,
        "trainer_name": "Observed",
        "team_rank_rating": 1356989,
        "team_class": 6,
        "members": [
            {
                "team_member_id": 1,
                "is_ace": True,
                "distance": distance,
                "style": style,
                "card_id": 100101,
                "trained_chara_id": 9001,
                "name": "Special Week",
                "rank_label": "UG4",
                "rank_score": score,
                "stats": {"speed": 1200, "stamina": 800, "power": 1100, "guts": 600, "wit": 1200},
                "support_cards": [support_card(card_id) for card_id in support_ids],
                "races": {"history": [{"result_rank": 1} for _ in range(40)]},
                "skills": [{"skill_id": 1, "name": "Skill"}],
                "parents": [{"card_id": 100201, "name": "Parent"}],
            }
        ],
    }


class ObservedProfileTests(unittest.TestCase):
    def test_team_trials_observations_persist_as_read_only_samples(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            team = observed_team()

            result = append_team_observations(runtime, team, source={"endpoint": "team_stadium/user_detail"})
            self.assertEqual(result["candidate_count"], 1)
            self.assertEqual(result["written_count"], 1)

            loaded = load_observation_samples(runtime, style="front_runner", distance="long")
            self.assertEqual(len(loaded), 1)
            self.assertEqual(loaded[0]["source"], "team_trials_observation")
            self.assertEqual(loaded[0]["style"], "front_runner")
            self.assertEqual(loaded[0]["team_trials_distance_slot"], "long")
            self.assertTrue(loaded[0]["not_behavior_learning"])
            self.assertEqual(loaded[0]["run_context"]["support_card_ids"], [1, 2, 3, 4, 5])

            summary = summarize_observation_samples(loaded)
            self.assertEqual(summary["sample_count"], 1)
            self.assertEqual(summary["by_style"]["front_runner"], 1)
            self.assertEqual(summary["by_distance"]["long"], 1)

    def test_observed_style_distance_context_can_steer_deck_advice(self):
        decks = [
            {"id": 1, "name": "Long Front", "cards": [support_card(card_id) for card_id in [1, 2, 3, 4, 5]]},
            {"id": 2, "name": "Mile Late", "cards": [support_card(card_id, "Wit") for card_id in [6, 7, 8, 9, 10]]},
        ]
        samples = []
        for idx in range(4):
            row = samples_from_team(observed_team(style="Front", distance="long", support_ids=[1, 2, 3, 4, 5], score=22000))[0]
            row["path"] += f":front:{idx}"
            samples.append(row)
        for idx in range(4):
            row = samples_from_team(observed_team(style="Late", distance="mile", support_ids=[6, 7, 8, 9, 10], score=22000))[0]
            row["path"] += f":late:{idx}"
            samples.append(row)

        long_advice = advise_decks(decks, samples, current_deck_id=2, parent_goals={}, style="front_runner", distance="long")
        mile_advice = advise_decks(decks, samples, current_deck_id=1, parent_goals={}, style="late_surger", distance="mile")

        self.assertEqual(long_advice["best_deck"]["deck_id"], 1)
        self.assertEqual(mile_advice["best_deck"]["deck_id"], 2)
        self.assertEqual(long_advice["style_context"], "front_runner")
        self.assertEqual(mile_advice["distance_context"], "mile")


if __name__ == "__main__":
    unittest.main()
