import unittest

from career_bot.deck_advice import advise_decks, synthesize_deck


def _deck(deck_id, name, cards):
    return {"id": deck_id, "name": name, "cards": cards}


def _card(card_id, name, rarity, type_name):
    return {"id": card_id, "name": name, "rarity": rarity, "type": type_name}


def _owned(card_id, name, rarity, type_name, *, lb=0, level=0, exp=0):
    return {
        "id": card_id,
        "name": name,
        "rarity": rarity,
        "type": type_name,
        "limit_break_count": lb,
        "support_card_level": level,
        "exp": exp,
    }


def _sample(score, support_ids, blue="Power", weight=1.0, trainee_card_id=0, support_cards=None):
    return {
        "score": score,
        "sample_weight": weight,
        "run_context": {
            "support_card_ids": list(support_ids),
            "support_cards": list(support_cards or []),
            "trainee_card_id": trainee_card_id,
            "desired_parent_sparks": {"blue": [blue], "pink": [], "green": [], "white": []},
        },
    }


class DeckAdviceSmokeTests(unittest.TestCase):
    def test_prefers_historically_stronger_goal_matching_deck(self):
        decks = [
            _deck(1, "Current", [
                _card(101, "Power SR A", "SR", "Power"),
                _card(102, "Wit SR A", "SR", "Wit"),
                _card(103, "Speed SR A", "SR", "Speed"),
                _card(104, "Guts SR A", "SR", "Guts"),
                _card(105, "Power SR B", "SR", "Power"),
            ]),
            _deck(2, "Recommended", [
                _card(201, "Power SSR A", "SSR", "Power"),
                _card(202, "Power SR C", "SR", "Power"),
                _card(203, "Wit SR B", "SR", "Wit"),
                _card(204, "Speed SR B", "SR", "Speed"),
                _card(205, "Power SR D", "SR", "Power"),
            ]),
        ]
        samples = [
            _sample(18000, [101, 102, 103, 104, 105], blue="Power"),
            _sample(16500, [101, 102, 103, 104, 105], blue="Power"),
            _sample(26800, [201, 202, 203, 204, 205], blue="Power"),
            _sample(25500, [201, 202, 203, 204, 205], blue="Power"),
        ]

        advice = advise_decks(
            decks,
            samples,
            current_deck_id=1,
            parent_goals={"blue": ["Power"], "pink": [], "green": [], "white": []},
        )

        self.assertEqual(advice["status"], "suboptimal")
        self.assertEqual(advice["best_deck"]["deck_id"], 2)
        self.assertEqual(advice["current_deck"]["deck_id"], 1)
        self.assertIn("Try Recommended instead", advice["message"])

    def test_uses_fallback_pool_when_exact_goal_match_missing(self):
        decks = [
            _deck(7, "Only Deck", [
                _card(701, "Speed SR", "SR", "Speed"),
                _card(702, "Power SR", "SR", "Power"),
                _card(703, "Wit SR", "SR", "Wit"),
                _card(704, "Stamina SR", "SR", "Stamina"),
                _card(705, "Guts SR", "SR", "Guts"),
            ]),
        ]
        samples = [
            _sample(22000, [701, 702, 703, 704, 705], blue="Speed"),
            _sample(21000, [701, 702, 703, 704, 705], blue="Speed"),
        ]

        advice = advise_decks(
            decks,
            samples,
            current_deck_id=7,
            parent_goals={"blue": ["Power"], "pink": [], "green": [], "white": []},
        )

        self.assertTrue(advice["fallback_mode"])
        self.assertEqual(advice["status"], "optimal")
        self.assertEqual(advice["best_deck"]["deck_id"], 7)

    def test_synthesizes_new_deck_from_owned_pool_and_goal(self):
        owned = [
            _owned(101, "Power SSR Ace", "SSR", "Power", lb=4, level=50, exp=60000),
            _owned(102, "Power SR Core", "SR", "Power", lb=4, level=45, exp=42000),
            _owned(103, "Wit SR Core", "SR", "Wit", lb=3, level=45, exp=35000),
            _owned(104, "Speed SR Flex", "SR", "Speed", lb=2, level=40, exp=22000),
            _owned(105, "Stamina SR Flex", "SR", "Stamina", lb=2, level=40, exp=22000),
            _owned(106, "Guts SR Weak", "SR", "Guts", lb=0, level=25, exp=5000),
            _owned(107, "Oguri Cap", "SSR", "Power", lb=4, level=50, exp=60000),
            _owned(108, "Guts SR Drift", "SR", "Guts", lb=1, level=30, exp=9000),
            _owned(109, "Nice Nature", "SSR", "Wit", lb=4, level=50, exp=60000),
        ]
        by_id = {int(card["id"]): card for card in owned}

        def sample_cards(*ids):
            return [dict(by_id[int(card_id)]) for card_id in ids]

        samples = [
            _sample(28200, [101, 102, 103, 104, 105], trainee_card_id=900501, support_cards=sample_cards(101, 102, 103, 104, 105)),
            _sample(27800, [101, 102, 103, 104, 105], trainee_card_id=900501, support_cards=sample_cards(101, 102, 103, 104, 105)),
            _sample(27450, [101, 102, 103, 104, 105], trainee_card_id=900501, support_cards=sample_cards(101, 102, 103, 104, 105)),
            _sample(26100, [101, 102, 103, 104, 108], trainee_card_id=900501, support_cards=sample_cards(101, 102, 103, 104, 108)),
            _sample(25700, [101, 102, 103, 104, 108], trainee_card_id=900501, support_cards=sample_cards(101, 102, 103, 104, 108)),
            _sample(18300, [101, 103, 105, 106, 108], trainee_card_id=900501, support_cards=sample_cards(101, 103, 105, 106, 108)),
            _sample(17600, [101, 103, 105, 106, 108], trainee_card_id=900501, support_cards=sample_cards(101, 103, 105, 106, 108)),
        ]

        current_deck = _deck(1, "Current", [by_id[101], by_id[103], by_id[105], by_id[106], by_id[108]])
        advice = synthesize_deck(
            owned,
            samples,
            parent_goals={"blue": ["Power"], "pink": [], "green": [], "white": ["NHK Mile C.", "Firm Conditions"]},
            trainee={"id": 900501, "name": "Oguri Cap"},
            friend={"support_name": "Nice Nature"},
            current_deck=current_deck,
        )

        self.assertEqual(advice["status"], "upgrade")
        self.assertEqual(len(advice["cards"]), 5)
        recommended_ids = {int(row["id"]) for row in advice["cards"]}
        self.assertIn(102, recommended_ids)
        self.assertIn(103, recommended_ids)
        self.assertNotIn(107, recommended_ids)
        self.assertNotIn(109, recommended_ids)
        self.assertGreater(advice["score_gain"], 0.2)
        self.assertTrue(advice["swap_suggestions"])
        self.assertTrue(advice["current_weaknesses"])


if __name__ == "__main__":
    unittest.main()
