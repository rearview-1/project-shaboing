import unittest
import sys
import types
from types import SimpleNamespace

sys.modules.setdefault("frida", types.SimpleNamespace())

import main


class DeckTypeCountsSmokeTests(unittest.TestCase):
    def test_apply_deck_type_counts_from_request_includes_friend_card(self):
        old_support_map = dict(main.support_map)
        try:
            main.support_map.clear()
            main.support_map.update({
                "101": {"type": "Speed"},
                "102": {"type": "Speed"},
                "103": {"type": "Power"},
                "104": {"type": "Wisdom"},
                "105": {"type": "Wisdom"},
                "201": {"type": "Wisdom"},
            })
            preset = {}
            req = SimpleNamespace(support_card_ids=[101, 102, 103, 104, 105], friend_card_id=201)

            main.apply_deck_type_counts(preset, req=req)

            self.assertEqual(preset["_deck_type_counts"], [2, 0, 1, 0, 3])
            self.assertEqual(preset["_deck_type_counts_source"], "request")
            self.assertGreater(preset["_deck_multipliers"][0], preset["_deck_multipliers"][2])
        finally:
            main.support_map.clear()
            main.support_map.update(old_support_map)

    def test_apply_deck_type_counts_ignores_empty_unknown_data(self):
        preset = {}

        main.apply_deck_type_counts(preset, chara_info={"support_card_array": []})

        self.assertNotIn("_deck_type_counts", preset)


if __name__ == "__main__":
    unittest.main()
