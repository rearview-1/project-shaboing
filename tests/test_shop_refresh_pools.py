import json
import unittest
from pathlib import Path

from career_bot.items import ITEM_NAMES


DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "shop_refresh_pools.json"


class ShopRefreshPoolsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(DATA_PATH.read_text(encoding="utf-8-sig"))

    def test_shop_refresh_pools_load(self):
        self.assertEqual(self.data.get("schema"), "sweepy_shop_refresh_pools_v1")
        self.assertEqual(len(self.data.get("scheduled_refreshes") or {}), 11)
        self.assertEqual(len(self.data.get("race_refreshes") or {}), 25)
        self.assertIn("12", self.data["scheduled_refreshes"])
        self.assertIn("72", self.data["scheduled_refreshes"])
        self.assertIn("G1_victory", self.data["race_refreshes"])
        self.assertIn("G1_etsuko_elated", self.data["race_refreshes"])
        self.assertEqual(self.data.get("unmapped_display_names"), [])

    def test_scheduled_refresh_distribution_and_item_ids(self):
        turn_12 = self.data["scheduled_refreshes"]["12"]
        self.assertAlmostEqual(float(turn_12["avg_new_items"]), 5.020222, places=5)
        self.assertIn("3", turn_12["items_per_refresh_distribution"])
        self.assertIn("7", turn_12["items_per_refresh_distribution"])
        for item_id in self.data["scheduled"]:
            self.assertIn(int(item_id), ITEM_NAMES)

    def test_race_refresh_distribution_has_zero_to_six_counts(self):
        g1_victory = self.data["race_refreshes"]["G1_victory"]
        self.assertAlmostEqual(float(g1_victory["avg_new_items"]), 2.37935, places=5)
        self.assertEqual(set(g1_victory["items_per_refresh_distribution"]), {str(i) for i in range(7)})
        for item_id in self.data["race"]:
            self.assertIn(int(item_id), ITEM_NAMES)

    def test_display_aliases_map_to_bot_item_ids(self):
        mapping = self.data["display_name_mapping"]
        self.assertEqual(mapping["+40%3T Megaphone"]["item_id"], 8002)
        self.assertEqual(mapping["+40%3T Megaphone"]["bot_display_name"], "Motivating Megaphone")
        self.assertEqual(mapping["Speed Weight"]["item_id"], 9001)
        self.assertEqual(mapping["Speed Weight"]["bot_display_name"], "Speed Ankle Weights")


if __name__ == "__main__":
    unittest.main()
