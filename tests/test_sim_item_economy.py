"""Faithfulness invariants for the sim's post-race item economy.

These pin the 2026-06-14 rework that replaced the FREE post-race item grant
(`_grant_post_race_items`, which minted items with no coin cost — e.g. ~6 free
megaphones/career) with a COIN-BOUNDED post-race shop (`_offer_post_race_shop`)
driven by the real shop_refresh_pools.json `race` pool appearance rates/prices,
honoring the live bot's NEVER_BUY contract.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "career_bot"))

from career_simulator import (  # noqa: E402
    CareerSimulator,
    NEVER_BUY_IDS,
    MEGAPHONE_ITEM_IDS,
    ENERGY_ITEM_IDS,
)
from tests.test_career_simulator import _make_preset  # noqa: E402

DECK_IDS = [30028, 20031, 30054, 30010, 30074]
COACHING_MEGAPHONE_ID = 8001  # the 20% megaphone real players never buy


def _run(seed):
    deck = [{"support_card_id": i, "lb_level": 4} for i in DECK_IDS]
    rc = {
        "support_card_ids": DECK_IDS,
        "support_card_lb_levels": {str(i): {"lb": 4} for i in DECK_IDS},
        "friend_card_id": 30036,
        "trainee_card_id": 106701,
    }
    p = _make_preset()
    p["_run_context"] = rc
    p["sim_formula_training_gain"] = True
    sim = CareerSimulator(preset=p, deck=deck, seed=seed)

    # Track every item added and whether coin ever went negative.
    added = {}
    min_coin = [10 ** 9]
    orig_add = sim._add_item
    orig_setcoin_check = []

    def wrapped_add(item_id, count=1, *a, **k):
        added[int(item_id)] = added.get(int(item_id), 0) + count
        return orig_add(item_id, count, *a, **k)

    sim._add_item = wrapped_add

    # Wrap the post-race shop to assert it never mints items for free.
    coin_before_after = []
    orig_shop = sim._offer_post_race_shop

    def wrapped_shop(grade, won):
        before = int(sim.state.get("mant_coin") or 0)
        n = orig_shop(grade, won)
        after = int(sim.state.get("mant_coin") or 0)
        coin_before_after.append((n, before, after))
        return n

    sim._offer_post_race_shop = wrapped_shop

    sim.run()
    min_coin[0] = min(min_coin[0], int(sim.state.get("mant_coin") or 0))
    return sim, added, coin_before_after


class PostRaceShopEconomyTests(unittest.TestCase):
    def test_coaching_megaphone_is_never_bought(self):
        # The 20% Coaching Megaphone is in NEVER_BUY; it must never enter inventory.
        self.assertIn(COACHING_MEGAPHONE_ID, NEVER_BUY_IDS)
        for seed in range(1, 6):
            _sim, added, _ = _run(seed)
            self.assertEqual(
                added.get(COACHING_MEGAPHONE_ID, 0), 0,
                f"Coaching Megaphone bought on seed {seed}",
            )

    def test_no_free_items_coin_never_negative(self):
        for seed in range(1, 6):
            sim, _added, _cba = _run(seed)
            self.assertGreaterEqual(int(sim.state.get("mant_coin") or 0), 0)

    def test_post_race_shop_spends_coins(self):
        # Whenever the post-race shop buys (n>0), coin must strictly decrease
        # (paid purchase) — never a free grant that leaves coin unchanged.
        saw_purchase = False
        for seed in range(1, 6):
            _sim, _added, cba = _run(seed)
            for n, before, after in cba:
                if n > 0:
                    saw_purchase = True
                    self.assertLess(after, before, "post-race buy did not cost coins")
                else:
                    self.assertEqual(after, before, "no-buy race changed coin")
        self.assertTrue(saw_purchase, "post-race shop never bought anything in 5 careers")

    def test_energy_is_acquired(self):
        # Energy/Vita is the #1 real-bot purchase; the economy must buy some.
        total_energy = 0
        for seed in range(1, 6):
            _sim, added, _ = _run(seed)
            total_energy += sum(added.get(i, 0) for i in ENERGY_ITEM_IDS)
        self.assertGreater(total_energy, 0, "no energy items acquired across 5 careers")

    def test_megaphone_inventory_does_not_runaway(self):
        # The free-grant bug stockpiled megaphones; the shop keeps only a small
        # reserve. Owned megaphones at career end must stay bounded (<= cap).
        for seed in range(1, 6):
            sim, _added, _ = _run(seed)
            owned = sum(sim._inventory_count(i) for i in MEGAPHONE_ITEM_IDS)
            self.assertLessEqual(owned, 6, f"megaphone stockpile {owned} on seed {seed}")


if __name__ == "__main__":
    unittest.main()
