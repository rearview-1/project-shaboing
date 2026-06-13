import unittest

from career_bot.items import ITEM_NAMES
from career_bot.shop_refresh import build_shop_decision_state, next_scheduled_refresh_turn


class ShopRefreshDecisionStateTests(unittest.TestCase):
    def test_build_shop_decision_state_includes_offers_and_refresh_action(self):
        state = {
            "data": {
                "chara_info": {"turn": 12},
                "free_data_set": {
                    "coin_num": 80,
                    "pick_up_item_info_array": [
                        {
                            "shop_item_id": 101,
                            "item_id": 8002,
                            "coin_num": 55,
                            "original_coin_num": 55,
                            "item_buy_num": 0,
                            "limit_buy_count": 1,
                            "limit_turn": 18,
                        },
                        {
                            "shop_item_id": 102,
                            "item_id": 9001,
                            "coin_num": 50,
                            "original_coin_num": 50,
                            "item_buy_num": 0,
                            "limit_buy_count": 1,
                            "limit_turn": 18,
                        },
                    ],
                },
            }
        }
        preset = {"mant_config": {"shop_refresh_cost": 10, "shop_refresh_endpoint": "single_mode_free/shop_refresh"}}

        decision = build_shop_decision_state(state, preset=preset, item_names=ITEM_NAMES)

        self.assertEqual(decision["schema"], "sweepy_shop_decision_state_v1")
        self.assertEqual(decision["turn"], 12)
        self.assertEqual(decision["mant_coin"], 80)
        self.assertEqual(decision["scheduled_refresh_turn"], 12)
        self.assertEqual(decision["next_scheduled_refresh_turn"], 18)
        self.assertAlmostEqual(float(decision["scheduled_pool"]["avg_new_items"]), 5.020222, places=5)
        self.assertEqual(decision["current_offers"][0]["name"], "Motivating Megaphone")
        self.assertGreater(float(decision["current_offers"][0]["appearance_rate_this_turn"]), 50.0)
        self.assertTrue(decision["refresh_shop"]["available"])
        self.assertEqual(decision["refresh_shop"]["cost"], 10)

    def test_refresh_action_is_safe_disabled_without_known_endpoint_or_cost(self):
        state = {
            "data": {
                "chara_info": {"turn": 13},
                "free_data_set": {
                    "coin_num": 80,
                    "pick_up_item_info_array": [{"shop_item_id": 1, "item_id": 8002, "coin_num": 55}],
                },
            }
        }

        decision = build_shop_decision_state(state, item_names=ITEM_NAMES)

        self.assertFalse(decision["refresh_shop"]["available"])
        self.assertIn("refresh_cost_unknown", decision["refresh_shop"]["unavailable_reasons"])
        self.assertIn("refresh_endpoint_not_configured", decision["refresh_shop"]["unavailable_reasons"])
        self.assertEqual(next_scheduled_refresh_turn(13), 18)


if __name__ == "__main__":
    unittest.main()
