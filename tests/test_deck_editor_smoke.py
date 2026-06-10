import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import main


def support(card_id, name):
    return {
        "id": card_id,
        "support_card_id": card_id,
        "name": name,
        "rarity": "SSR",
        "type": "Speed",
        "limit_break_count": 4,
        "support_card_level": 50,
        "stock": 0,
    }


class DeckEditorSmokeTests(unittest.TestCase):
    def setUp(self):
        self.saved_dashboard = main.active_dashboard_data
        self.saved_selection = dict(main.active_selection)
        self.saved_client = main.active_client
        self.saved_cache = dict(main.deck_advice_cache)

    def tearDown(self):
        main.active_dashboard_data = self.saved_dashboard
        main.active_selection = self.saved_selection
        main.active_client = self.saved_client
        main.deck_advice_cache.clear()
        main.deck_advice_cache.update(self.saved_cache)

    def test_save_deck_persists_local_override_and_updates_selected_deck(self):
        with tempfile.TemporaryDirectory() as tmp:
            override_path = Path(tmp) / "deck_overrides.json"
            supports = [support(card_id, f"Card {card_id}") for card_id in [101, 102, 103, 104, 105]]
            original_deck = {
                "id": 1,
                "name": "Normal",
                "cards": supports,
                "support_card_ids": [101, 102, 103, 104, 105],
                "source": "synced",
            }
            main.active_client = None
            main.active_dashboard_data = {"supports": supports, "decks": [dict(original_deck)]}
            main.active_selection = {"deck": dict(original_deck)}

            with patch.object(main, "deck_overrides_path", return_value=override_path), \
                 patch.object(main, "persist_dev_session_cache", return_value=None):
                result = asyncio.run(main.save_deck(main.SaveDeckRequest(
                    deck_id=1,
                    name="Edited",
                    support_card_ids=[101, 103, 105],
                )))

                self.assertTrue(result["success"])
                self.assertEqual([card["id"] for card in result["deck"]["cards"]], [101, 103, 105])
                self.assertTrue(result["deck"]["edited"])
                self.assertEqual(main.active_selection["deck"]["support_card_ids"], [101, 103, 105])

                stored = json.loads(override_path.read_text(encoding="utf-8"))
                self.assertEqual(stored["decks"]["1"]["support_card_ids"], [101, 103, 105])
                self.assertEqual(stored["decks"]["1"]["synced_support_card_ids"], [101, 102, 103, 104, 105])

                overlaid = main.apply_deck_overrides([dict(original_deck)], supports)
                self.assertEqual(overlaid[0]["support_card_ids"], [101, 103, 105])
                self.assertTrue(overlaid[0]["edited"])

                reset = asyncio.run(main.save_deck(main.SaveDeckRequest(deck_id=1, clear_override=True)))

                self.assertTrue(reset["success"])
                self.assertEqual(reset["deck"]["support_card_ids"], [101, 102, 103, 104, 105])
                self.assertFalse(reset["deck"]["edited"])
                self.assertEqual(json.loads(override_path.read_text(encoding="utf-8"))["decks"], {})


if __name__ == "__main__":
    unittest.main()
