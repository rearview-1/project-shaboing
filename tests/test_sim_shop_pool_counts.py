"""Sim shop availability uses the real measured refresh pool, not replay
of the bot's own (mediocre) purchase history."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ROOT = Path(__file__).resolve().parents[1]
PRESET = ROOT / "uma_runtime/instances/account_b/instance_learning/presets/xguri parent.json"


def _sim():
    from career_bot.career_simulator import CareerSimulator, hydrate_preset_with_latest_session_context
    preset = json.loads(PRESET.read_text(encoding="utf-8-sig"))
    preset["sim_runtime_instance"] = "account_b"
    preset = hydrate_preset_with_latest_session_context(preset, ROOT)
    deck = (preset.get("_run_context") or {}).get("support_cards") or None
    return CareerSimulator(preset=preset, deck=deck, seed=1, project_root=ROOT)


class ShopPoolCountsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not PRESET.exists():
            raise unittest.SkipTest("account_b preset not present")
        cls.sim = _sim()

    def test_megaphone_available_all_career(self):
        # Motivating Megaphone (8002) is abundant early and late.
        self.assertGreater(self.sim._shop_pool_counts(12).get(8002, 0), 300)
        self.assertGreater(self.sim._shop_pool_counts(48).get(8002, 0), 300)

    def test_early_stat_candy_stops_late(self):
        # SPD+3 (1001) offered through T24, absent from T30 on (data shape).
        self.assertGreater(self.sim._shop_pool_counts(12).get(1001, 0), 0)
        self.assertFalse(self.sim._shop_pool_counts(48).get(1001))

    def test_anklets_appear_midcareer(self):
        # Speed Ankle Weights (9001) absent at T12, present by T48.
        self.assertFalse(self.sim._shop_pool_counts(12).get(9001))
        self.assertGreater(self.sim._shop_pool_counts(48).get(9001, 0), 0)

    def test_accurate_sim_flags_enabled_in_preset(self):
        # The accurate offline-sim model (formula training + empirical race
        # stat total + real shop pools) is enabled in the preset so the
        # optimizer/sweeps train against accurate physics. These affect
        # offline sim only; live careers play the real game. If the buy
        # path can't find a pool it still falls back to observed counts.
        self.assertTrue(bool(self.sim.preset.get("sim_use_shop_refresh_pools")))
        self.assertTrue(bool(self.sim.preset.get("sim_formula_training_gain")))
        self.assertTrue(bool(self.sim.preset.get("sim_empirical_race_stat_total")))


if __name__ == "__main__":
    unittest.main()
