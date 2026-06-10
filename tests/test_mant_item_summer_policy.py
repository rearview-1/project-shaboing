import unittest

from career_bot.items import MantItemManager


def command(command_id=101, speed=35, power=15, sp=0):
    return {
        "command_type": 1,
        "command_id": command_id,
        "params_inc_dec_info_array": [
            {"target_type": 1, "value": speed},
            {"target_type": 3, "value": power},
            {"target_type": 30, "value": sp},
        ],
    }


def state(turn, effects=None, hp=100, max_hp=100):
    return {
        "data": {
            "chara_info": {"turn": turn, "vital": hp, "max_vital": max_hp},
            "free_data_set": {"item_effect_array": list(effects or [])},
        }
    }


class MantItemSummerPolicyTests(unittest.TestCase):
    def setUp(self):
        self.manager = MantItemManager()
        self.preset = {
            "mant_config": {
                "summer_item_policy": True,
                "summer_item_reserve_lookahead": 6,
                "summer_energy_prep_lookahead": 2,
                "summer_reserve_break_glass_score": 85,
                "summer_energy_recovery_threshold": 80,
                "summer_energy_entry_threshold": 80,
                "summer_anklet_threshold": 24,
            }
        }

    def test_reserves_megaphone_before_summer_and_uses_it_during_summer(self):
        owned = {"Empowering Megaphone": 1}
        best = command(speed=41, power=22, sp=5)

        before = self.manager._megaphone_target(state(58), best, owned, self.preset, None, 58, None)
        during = self.manager._megaphone_target(state(60), best, owned, self.preset, None, 60, None)

        self.assertIsNone(before)
        self.assertEqual(during, ("Empowering Megaphone", 1))

    def test_hoards_two_empowering_megaphones_for_future_summer(self):
        best = command(speed=90, power=30, sp=10)

        reserved = self.manager._megaphone_target(
            state(20),
            best,
            {"Empowering Megaphone": 2},
            self.preset,
            None,
            20,
            None,
        )
        surplus = self.manager._megaphone_target(
            state(20),
            best,
            {"Empowering Megaphone": 3},
            self.preset,
            None,
            20,
            None,
        )

        self.assertIsNone(reserved)
        self.assertEqual(surplus, ("Empowering Megaphone", 1))

    def test_empowering_megaphone_stock_target_is_two_before_summer(self):
        self.assertTrue(
            self.manager._should_stock_summer_empowering_megaphone(
                "Empowering Megaphone",
                {"Empowering Megaphone": 1},
                self.preset,
                20,
            )
        )
        self.assertFalse(
            self.manager._should_stock_summer_empowering_megaphone(
                "Empowering Megaphone",
                {"Empowering Megaphone": 2},
                self.preset,
                20,
            )
        )

    def test_reserves_matching_anklet_before_summer_and_uses_it_during_summer(self):
        owned = {"Speed Ankle Weights": 1}
        best = command(command_id=101, speed=41, power=22, sp=5)

        before = self.manager._anklet_target(state(58), best, owned, self.preset)
        during = self.manager._anklet_target(state(60), best, owned, self.preset)

        self.assertIsNone(before)
        self.assertEqual(during, ("Speed Ankle Weights", 1))

    def test_summer_energy_threshold_spends_energy_for_training_window(self):
        owned = {"Energy Drink MAX": 1, "Vita 40": 1}

        result = self.manager._energy_targets(
            {"turn": 60, "vital": 65, "max_vital": 100},
            owned,
            self.preset,
            command(),
        )

        self.assertTrue(result)

    def test_pre_climax_keeps_three_cleats_reserved(self):
        choice = self.manager._old_ui_cleat_before_race(
            {"Master Cleat Hammer": 1, "Artisan Cleat Hammer": 2},
            68,
            0,
            None,
        )

        self.assertIsNone(choice)

    def test_senior_shop_keeps_buying_master_cleats_until_three(self):
        available = [
            ("Master Cleat Hammer", _shop_row(501, 11002, coin=40)),
            ("Artisan Cleat Hammer", _shop_row(502, 11001, coin=25)),
        ]

        row = self.manager._old_ui_cleat_shop_target(
            available,
            {"Master Cleat Hammer": 1, "Artisan Cleat Hammer": 2},
            100,
            65,
        )

        self.assertIsNotNone(row)
        self.assertEqual(int(row.get("item_id") or 0), 11002)

    def test_summer_energy_reserve_counts_only_energy_items(self):
        owned = {
            "Vita 40": 1,
            "Energy Drink MAX": 1,
            "Good-Luck Charm": 5,
            "Empowering Megaphone": 2,
        }

        self.assertEqual(self.manager._summer_energy_reserve_value(owned), 70)

    def test_summer_energy_reserve_stocks_until_target_before_camp(self):
        low = {"Vita 40": 1}
        met = {"Vita 40": 2}

        self.assertTrue(self.manager._should_stock_summer_energy("Vita 20", low, self.preset, 58))
        self.assertFalse(self.manager._should_stock_summer_energy("Vita 20", met, self.preset, 58))
        self.assertFalse(self.manager._should_stock_summer_energy("Good-Luck Charm", low, self.preset, 58))

    def test_race_heavy_route_stocks_energy_outside_summer_window(self):
        preset = {
            **self.preset,
            "custom_race_schedule": [{"turn": idx + 1, "program_id": idx + 1000} for idx in range(38)],
        }

        self.assertTrue(self.manager._should_stock_race_heavy_energy("Vita 20", {}, preset, 28))
        self.assertFalse(self.manager._should_stock_race_heavy_energy("Vita 20", {"Vita 40": 2}, preset, 28))
        self.assertFalse(self.manager._should_stock_race_heavy_energy("Good-Luck Charm", {}, preset, 28))

    def test_race_heavy_route_uses_energy_before_hp_crashes(self):
        preset = {
            **self.preset,
            "custom_race_schedule": [{"turn": idx + 1, "program_id": idx + 1000} for idx in range(38)],
        }

        result = self.manager._energy_targets(
            {"turn": 28, "vital": 45, "max_vital": 100, "motivation": 5},
            {"Vita 20": 1},
            preset,
            command(),
        )

        self.assertEqual(result, [("Vita 20", 1)])

    def test_summer_energy_threshold_does_not_fire_before_race(self):
        owned = {"Energy Drink MAX": 1, "Vita 40": 1}

        result = self.manager._energy_targets(
            {"turn": 60, "vital": 65, "max_vital": 100},
            owned,
            self.preset,
            None,
        )

        self.assertEqual(result, [])

    def test_learned_item_policy_can_skip_chronically_dead_weight_buy(self):
        preset = {
            **self.preset,
            "item_learning_policy": {
                "items": {
                    "Pretty Mirror": {
                        "phase_adjustments": {"early": 2},
                        "phase_stats": {"early": {"count": 4, "unused_rate": 1.0}},
                    }
                }
            },
        }

        self.assertTrue(
            self.manager._skip_buy(
                "Pretty Mirror",
                {},
                preset=preset,
                turn=20,
                budget=200,
                data={},
                race_planner=None,
            )
        )

    def test_learned_item_timing_can_use_energy_item_earlier(self):
        preset = {
            **self.preset,
            "item_learning_policy": {
                "items": {
                    "Energy Drink MAX": {
                        "timing_adjustments": {"mid": 2},
                        "phase_stats": {"mid": {"count": 4, "used_count": 4, "fast_use_rate": 1.0}},
                    }
                }
            },
        }

        result = self.manager._energy_targets(
            {"turn": 30, "vital": 33, "max_vital": 100, "motivation": 5},
            {"Energy Drink MAX": 1},
            preset,
            command(),
        )

        self.assertEqual(result, [("Energy Drink MAX", 1)])

    def test_royal_kale_requires_good_or_great_mood(self):
        owned = {"Royal Kale Juice": 1}

        result = self.manager._energy_targets(
            {"turn": 60, "vital": 0, "max_vital": 100, "motivation": 3},
            owned,
            self.preset,
            command(),
        )

        self.assertEqual(result, [])

    def test_royal_kale_at_good_requires_cupcake_pair(self):
        no_pair = self.manager._energy_targets(
            {"turn": 60, "vital": 0, "max_vital": 100, "motivation": 4},
            {"Royal Kale Juice": 1},
            self.preset,
            command(),
        )
        with_pair = self.manager._energy_targets(
            {"turn": 60, "vital": 0, "max_vital": 100, "motivation": 4},
            {"Royal Kale Juice": 1, "Plain Cupcake": 1},
            self.preset,
            command(),
        )

        self.assertEqual(no_pair, [])
        self.assertIn(("Royal Kale Juice", 1), with_pair)
        self.assertEqual(
            self.manager._royal_kale_pair_target(
                {"motivation": 4},
                {"Royal Kale Juice": 1, "Plain Cupcake": 1},
                with_pair,
            ),
            ("Plain Cupcake", 1),
        )

    def test_royal_kale_at_great_can_pair_if_cupcake_exists(self):
        targets = self.manager._energy_targets(
            {"turn": 60, "vital": 0, "max_vital": 100, "motivation": 5},
            {"Royal Kale Juice": 1, "Berry Sweet Cupcake": 1},
            self.preset,
            command(),
        )

        self.assertIn(("Royal Kale Juice", 1), targets)
        self.assertEqual(
            self.manager._royal_kale_pair_target(
                {"motivation": 5},
                {"Royal Kale Juice": 1, "Berry Sweet Cupcake": 1},
                targets,
            ),
            ("Berry Sweet Cupcake", 1),
        )

    def test_summer_reserve_window_keeps_energy_for_entry_unless_critical(self):
        owned = {"Vita 40": 1}

        result = self.manager._energy_targets(
            {"turn": 56, "vital": 40, "max_vital": 100},
            owned,
            self.preset,
            command(),
        )

        self.assertEqual(result, [])

    def test_summer_anklet_stock_targets_follow_deck_counts(self):
        preset = {
            "mant_config": {"summer_item_policy": True},
            "_deck_type_counts": [2, 0, 1, 0, 3],
        }

        self.assertEqual(self.manager._summer_anklet_stock_target("Speed Ankle Weights", preset), 3)
        self.assertEqual(self.manager._summer_anklet_stock_target("Power Ankle Weights", preset), 2)
        self.assertEqual(self.manager._summer_anklet_stock_target("Stamina Ankle Weights", preset), 0)
        self.assertFalse(
            self.manager._skip_buy(
                "Speed Ankle Weights",
                {"Speed Ankle Weights": 2},
                preset,
                turn=58,
                budget=200,
                data={},
            )
        )

    def test_shop_policy_hard_bans_bad_or_unwanted_items(self):
        banned = [
            "Coaching Megaphone",
            "Energy Drink MAX EX",
            "Reporter's Binoculars",
            "Master Practice Guide",
        ]

        for name in banned:
            with self.subTest(name=name):
                self.assertTrue(self.manager._skip_buy(name, {}, self.preset, turn=20, budget=500, data={}))

    def test_cure_items_require_matching_status_except_skin_cream(self):
        no_status = {"chara_info": {"chara_effect_id_array": []}}
        slow_metabolism = {"chara_info": {"chara_effect_id_array": [4]}}

        self.assertTrue(self.manager._skip_buy("Smart Scale", {}, self.preset, turn=20, budget=100, data=no_status))
        self.assertFalse(self.manager._skip_buy("Smart Scale", {}, self.preset, turn=20, budget=100, data=slow_metabolism))
        self.assertFalse(self.manager._skip_buy("Rich Hand Cream", {}, self.preset, turn=20, budget=100, data=no_status))
        self.assertTrue(
            self.manager._skip_buy(
                "Rich Hand Cream",
                {"Rich Hand Cream": 1},
                self.preset,
                turn=20,
                budget=100,
                data=no_status,
            )
        )

    def test_energy_drink_max_buy_cap_is_one(self):
        self.assertFalse(self.manager._skip_buy("Energy Drink MAX", {}, self.preset, turn=20, budget=100, data={}))
        self.assertTrue(
            self.manager._skip_buy(
                "Energy Drink MAX",
                {"Energy Drink MAX": 1},
                self.preset,
                turn=20,
                budget=100,
                data={},
            )
        )

    def test_ankle_weights_buy_cap_is_five(self):
        self.assertFalse(
            self.manager._skip_buy(
                "Power Ankle Weights",
                {"Power Ankle Weights": 4},
                self.preset,
                turn=65,
                budget=200,
                data={},
            )
        )
        self.assertTrue(
            self.manager._skip_buy(
                "Power Ankle Weights",
                {"Power Ankle Weights": 5},
                self.preset,
                turn=65,
                budget=200,
                data={},
            )
        )

    def test_good_luck_charm_is_disabled_by_default(self):
        self.assertTrue(self.manager._skip_buy("Good-Luck Charm", {}, self.preset, turn=25, budget=100, data={}))
        self.assertIsNone(
            self.manager._charm_target(
                {"command_type": 1, "failure_rate": 30},
                {"Good-Luck Charm": 1},
                self.preset,
                None,
            )
        )

    def test_good_luck_charm_can_be_reenabled_explicitly(self):
        preset = {
            **self.preset,
            "mant_config": {
                **self.preset.get("mant_config", {}),
                "enable_good_luck_charm": True,
                "charm_failure_rate": 21,
            },
        }
        self.assertFalse(self.manager._skip_buy("Good-Luck Charm", {}, preset, turn=25, budget=100, data={}))
        self.assertEqual(
            self.manager._charm_target(
                {"command_type": 1, "failure_rate": 30},
                {"Good-Luck Charm": 1},
                preset,
                None,
            ),
            ("Good-Luck Charm", 1),
        )

    def test_exchange_payload_uses_inventory_count_not_shop_buy_count(self):
        """The game's `current_num` field on multi_item_exchange is an
        optimistic-concurrency check of the user's inventory count of the
        underlying item_id — NOT the shop slot's per-snapshot buy count.

        Sending item_buy_num produces 205 for any item the user already
        owns (Megaphones, Ankle Weights, Vitas, etc.). Confirmed via
        diagnostic logging: with item_buy_num=0 and inventory_count=1
        the server rejected; retrying the same shop_item_id with
        current_num=1 succeeded.

        Previously this test asserted the opposite (current_num=0) and
        was codifying the bug. Renamed and flipped to the correct
        semantics."""
        class Client:
            def __init__(self):
                self.payload = None

            def exchange_items(self, payload, current_turn, retry_205=0, retry_208=0):
                self.payload = payload
                return {
                    "data": {
                        "chara_info": {"turn": current_turn},
                        "free_data_set": {"coin_num": 90, "pick_up_item_info_array": []},
                    }
                }

        client = Client()
        state_data = {
            "data": {
                "chara_info": {"turn": 60},
                "free_data_set": {
                    "coin_num": 100,
                    # Player owns 2 Good-Luck Charms already.
                    "user_item_info_array": [{"item_id": 10001, "num": 2}],
                    "pick_up_item_info_array": [
                        {
                            "shop_item_id": 123,
                            "item_id": 10001,
                            "coin_num": 10,
                            "item_buy_num": 0,
                            "limit_buy_count": 1,
                            "limit_turn": 0,
                        }
                    ],
                },
            }
        }

        self.manager._exchange_batch(client, state_data, [{"shop_item_id": 123, "current_num": 99}], 60)

        # The bot should send the user's INVENTORY count (2), not the
        # shop slot's buy count (0) and not the value from the caller's
        # payload (99).
        self.assertEqual(client.payload, [{"shop_item_id": 123, "current_num": 2}])

    def test_pretty_mirror_uses_charming_bond_rule(self):
        healthy_bonds = {
            "chara_info": {
                "evaluation_info_array": [{"target_id": i, "evaluation": 65} for i in range(1, 7)]
            }
        }
        low_bonds = {
            "chara_info": {
                "evaluation_info_array": [
                    {"target_id": 1, "evaluation": 30},
                    {"target_id": 2, "evaluation": 35},
                    {"target_id": 3, "evaluation": 40},
                    {"target_id": 4, "evaluation": 80},
                ]
            }
        }

        self.assertFalse(self.manager._skip_buy("Pretty Mirror", {}, self.preset, turn=25, budget=200, data=healthy_bonds))
        self.assertTrue(self.manager._skip_buy("Pretty Mirror", {}, self.preset, turn=49, budget=200, data=healthy_bonds))
        self.assertFalse(self.manager._skip_buy("Pretty Mirror", {}, self.preset, turn=49, budget=200, data=low_bonds))
        self.assertTrue(
            self.manager._skip_buy(
                "Pretty Mirror",
                {"Pretty Mirror": 1},
                self.preset,
                turn=25,
                budget=200,
                data=healthy_bonds,
            )
        )


def _shop_state(turn, coin, shop_rows, owned=None):
    """Helper to build a state dict resembling the game's response shape.

    `owned` is an optional list of {item_id, num} dicts simulating the
    user's inventory (user_item_info_array)."""
    free = {
        "coin_num": coin,
        "pick_up_item_info_array": list(shop_rows),
    }
    if owned is not None:
        free["user_item_info_array"] = list(owned)
    return {
        "data": {
            "chara_info": {"turn": turn},
            "free_data_set": free,
        }
    }


def _shop_row(shop_item_id, item_id, coin=10, item_buy_num=0, limit_buy_count=1, limit_turn=0):
    return {
        "shop_item_id": shop_item_id,
        "item_id": item_id,
        "coin_num": coin,
        "item_buy_num": item_buy_num,
        "limit_buy_count": limit_buy_count,
        "limit_turn": limit_turn,
    }


class ItemBuyCapTests(unittest.TestCase):
    def test_buy_shop_items_skips_any_item_at_server_inventory_cap(self):
        manager = MantItemManager()
        state = _shop_state(
            37,
            176,
            [_shop_row(55, 2002, coin=55)],
            owned=[{"item_id": 2002, "num": 5}],
        )

        _, count = manager.buy_shop_items(object(), state, {}, None)

        self.assertEqual(count, 0)
        self.assertEqual(manager.last_buy_result.get("skip"), "no_available")
        self.assertEqual(manager.last_buy_options[0]["skip_reason"], "inventory_cap")

    def test_buy_shop_items_skips_motivating_megaphone_at_inventory_cap(self):
        manager = MantItemManager()
        state = _shop_state(
            37,
            176,
            [_shop_row(54, 8002, coin=55)],
            owned=[{"item_id": 8002, "num": 5}],
        )

        _, count = manager.buy_shop_items(object(), state, {}, None)

        self.assertEqual(count, 0)
        self.assertEqual(manager.last_buy_result.get("skip"), "no_available")
        self.assertEqual(manager.last_buy_options[0]["skip_reason"], "inventory_cap")


class Exchange205RecoveryTests(unittest.TestCase):
    """Behavior on shop-exchange 205 (stale-snapshot) errors.

    Old behavior: a single batch 205 marked every item in the batch as
    persistently failed across the career, even though the rejection was
    almost always per-batch (stale snapshot) not per-item. Three batches'
    worth of false positives could blacklist 10-20 standard items.

    New behavior: refresh state + retry batch once, then probe each item
    individually; only items that fail in isolation earn persistent-fail
    strikes."""

    def setUp(self):
        self.manager = MantItemManager()
        # Pretend these shop_item_ids correspond to known item_ids — the
        # persistent fail tracker keys on item_id, so last_buy_options
        # must be populated for the tracker to record anything.
        self.manager.last_buy_options = [
            {"shop_item_id": 101, "item_id": 9001},
            {"shop_item_id": 102, "item_id": 9002},
            {"shop_item_id": 103, "item_id": 9003},
        ]

    def _make_client(self, exchange_results, reload_state=None):
        """Build a stub client. `exchange_results` is a list of either
        callables (called with the payload, returns or raises) or static
        results to be returned in order."""
        client = self  # placeholder — replaced below

        class StubClient:
            def __init__(self, results, reload_state):
                self._results = list(results)
                self._reload_state = reload_state
                self.exchange_calls = []
                self.load_calls = 0

            def exchange_items(self, payload, current_turn, retry_205=0, retry_208=0):
                self.exchange_calls.append({
                    "payload": list(payload),
                    "current_turn": current_turn,
                    "retry_205": retry_205,
                    "retry_208": retry_208,
                })
                if not self._results:
                    raise AssertionError("exchange_items called more times than results provided")
                spec = self._results.pop(0)
                if callable(spec):
                    return spec(payload, current_turn)
                if isinstance(spec, Exception):
                    raise spec
                return spec

            def load_career(self):
                self.load_calls += 1
                return self._reload_state or {"data": {"chara_info": {"turn": 0}, "free_data_set": {"coin_num": 0, "pick_up_item_info_array": []}}}

        return StubClient(exchange_results, reload_state)

    def test_batch_205_refreshes_state_and_retries_before_giving_up(self):
        """First batch attempt 205s → manager calls load_career → retries
        batch against fresh state → succeeds → no persistent fails.

        Two load_career calls happen: one preventive refresh before the
        first exchange, one recovery refresh after the 205."""
        initial_state = _shop_state(30, 100, [_shop_row(101, 9001), _shop_row(102, 9002)])
        refreshed_state = _shop_state(30, 100, [_shop_row(101, 9001), _shop_row(102, 9002)])
        ok_state = _shop_state(30, 80, [])
        client = self._make_client(
            [
                Exception("Game error code 205"),
                ok_state,
            ],
            reload_state=refreshed_state,
        )

        result_state, count = self.manager._exchange_batch(
            client, initial_state,
            [{"shop_item_id": 101, "current_num": 0}, {"shop_item_id": 102, "current_num": 0}],
            30,
        )

        self.assertEqual(count, 2)
        self.assertEqual(client.load_calls, 2)
        self.assertEqual(len(client.exchange_calls), 2)
        # Neither item should have earned a persistent-fail strike.
        self.assertEqual(self.manager.persistent_failed_exchange_item_ids, {})

    def test_preventive_refresh_drops_items_no_longer_in_shop(self):
        """The preventive refresh before exchange can reveal that items
        the bot was about to buy are no longer in the shop (sold out
        after a prior in-turn action). Those items get silently dropped
        instead of producing a 205 from the server."""
        initial_state = _shop_state(30, 100, [_shop_row(101, 9001), _shop_row(102, 9002)])
        # After refresh, 102 has been removed from the shop entirely.
        refreshed_state = _shop_state(30, 100, [_shop_row(101, 9001)])
        ok_state = _shop_state(30, 90, [_shop_row(101, 9001, item_buy_num=1)])
        client = self._make_client([ok_state], reload_state=refreshed_state)

        _, count = self.manager._exchange_batch(
            client, initial_state,
            [{"shop_item_id": 101, "current_num": 0}, {"shop_item_id": 102, "current_num": 0}],
            30,
        )

        self.assertEqual(count, 1)
        # The exchange call should only have been made for the surviving item.
        self.assertEqual(len(client.exchange_calls), 1)
        self.assertEqual(client.exchange_calls[0]["payload"], [{"shop_item_id": 101, "current_num": 0}])
        # Dropped item is not an error — no persistent strike for 9002.
        self.assertEqual(self.manager.persistent_failed_exchange_item_ids, {})

    def test_preventive_refresh_drops_megaphone_when_inventory_hits_cap(self):
        initial_state = _shop_state(
            37,
            176,
            [_shop_row(54, 8002, coin=55)],
            owned=[{"item_id": 8002, "num": 4}],
        )
        refreshed_state = _shop_state(
            37,
            176,
            [_shop_row(54, 8002, coin=55)],
            owned=[{"item_id": 8002, "num": 5}],
        )
        client = self._make_client([], reload_state=refreshed_state)

        _, count = self.manager._exchange_batch(
            client,
            initial_state,
            [{"shop_item_id": 54, "current_num": 4}],
            37,
        )

        self.assertEqual(count, 0)
        self.assertEqual(client.exchange_calls, [])
        self.assertEqual(self.manager.last_buy_result.get("skip"), "all_items_missing_after_refresh")
        self.assertEqual(self.manager.persistent_failed_exchange_item_ids, {})

    def test_preventive_refresh_all_items_gone_returns_zero(self):
        """If every item in the prospective buy has vanished from the
        shop by the time we refresh, we return cleanly with count=0
        instead of sending an empty payload to the server."""
        initial_state = _shop_state(30, 100, [_shop_row(101, 9001), _shop_row(102, 9002)])
        refreshed_state = _shop_state(30, 100, [])  # empty shop
        client = self._make_client([], reload_state=refreshed_state)

        _, count = self.manager._exchange_batch(
            client, initial_state,
            [{"shop_item_id": 101, "current_num": 0}, {"shop_item_id": 102, "current_num": 0}],
            30,
        )

        self.assertEqual(count, 0)
        self.assertEqual(len(client.exchange_calls), 0)
        self.assertEqual(self.manager.persistent_failed_exchange_item_ids, {})

    def test_batch_205_then_per_item_isolates_one_bad_item(self):
        """Batch 205 → refresh+retry 205 → per-item probe. Only the item
        that actually fails individually earns a persistent strike."""
        initial_state = _shop_state(30, 100, [
            _shop_row(101, 9001), _shop_row(102, 9002), _shop_row(103, 9003),
        ])
        refreshed_state = _shop_state(30, 100, [
            _shop_row(101, 9001), _shop_row(102, 9002), _shop_row(103, 9003),
        ])
        # Per-item probe responses: 101 ok, 102 fails 205, 103 ok.
        ok_after_101 = _shop_state(30, 90, [
            _shop_row(101, 9001, item_buy_num=1), _shop_row(102, 9002), _shop_row(103, 9003),
        ])
        ok_after_103 = _shop_state(30, 80, [
            _shop_row(101, 9001, item_buy_num=1), _shop_row(102, 9002), _shop_row(103, 9003, item_buy_num=1),
        ])
        client = self._make_client(
            [
                Exception("Game error code 205"),  # initial batch
                Exception("Game error code 205"),  # refresh-retry batch
                ok_after_101,                       # probe item 101 ok
                Exception("Game error code 205"),  # probe item 102 fails
                ok_after_103,                       # probe item 103 ok
            ],
            reload_state=refreshed_state,
        )

        result_state, count = self.manager._exchange_batch(
            client, initial_state,
            [
                {"shop_item_id": 101, "current_num": 0},
                {"shop_item_id": 102, "current_num": 0},
                {"shop_item_id": 103, "current_num": 0},
            ],
            30,
        )

        self.assertEqual(count, 2, "two items should have succeeded individually")
        # Only item 9002 (the one that failed in isolation) should be in
        # the persistent fail tracker. Items 9001 and 9003 should not.
        self.assertEqual(
            self.manager.persistent_failed_exchange_item_ids,
            {9002: 1},
        )

    def test_non_recoverable_error_does_not_blacklist_items(self):
        """A network/auth error (non-recoverable) marks the snapshot but
        must not bump the persistent fail counter — that counter is
        reserved for actual item-level rejections."""
        initial_state = _shop_state(30, 100, [_shop_row(101, 9001), _shop_row(102, 9002)])
        client = self._make_client([Exception("Connection reset by peer")], reload_state=initial_state)

        _, count = self.manager._exchange_batch(
            client, initial_state,
            [{"shop_item_id": 101, "current_num": 0}, {"shop_item_id": 102, "current_num": 0}],
            30,
        )

        self.assertEqual(count, 0)
        self.assertEqual(self.manager.persistent_failed_exchange_item_ids, {})
        # Snapshot-scoped block stays in place so we don't hammer this snapshot.
        self.assertEqual(self.manager.failed_exchange_this_snapshot, {101, 102})

    def test_batch_sends_inventory_count_when_player_owns_item(self):
        """The fixed behavior: batch exchange sends current_num set to the
        user's inventory count of the item, not the shop slot's
        item_buy_num. Real-world repro: Motivating Megaphone (item_id
        8002) in shop with item_buy_num=0; player already owns 1.
        Sending current_num=1 is what makes the server accept."""
        # Player owns 1 Motivating Megaphone already (item_id 8002).
        initial_state = _shop_state(
            30, 100,
            [_shop_row(201, 8002, coin=55)],
            owned=[{"item_id": 8002, "num": 1}],
        )
        refreshed_state = _shop_state(
            30, 100,
            [_shop_row(201, 8002, coin=55)],
            owned=[{"item_id": 8002, "num": 1}],
        )
        ok_state = _shop_state(
            30, 45,
            [_shop_row(201, 8002, coin=55, item_buy_num=1)],
            owned=[{"item_id": 8002, "num": 2}],
        )
        client = self._make_client([ok_state], reload_state=refreshed_state)
        self.manager.last_buy_options = [{"shop_item_id": 201, "item_id": 8002}]

        _, count = self.manager._exchange_batch(
            client, initial_state,
            [{"shop_item_id": 201, "current_num": 0}],
            30,
        )

        self.assertEqual(count, 1)
        # Verify the actual call was made with inventory_count=1, not
        # item_buy_num=0 and not the placeholder=0 from the caller payload.
        self.assertEqual(
            client.exchange_calls[0]["payload"],
            [{"shop_item_id": 201, "current_num": 1}],
        )
        self.assertEqual(self.manager.persistent_failed_exchange_item_ids, {})

    def test_per_item_probe_primary_is_inventory_count(self):
        """When the batch path falls through to the per-item probe, the
        FIRST attempt should send current_num=inventory_count (matching
        what the server actually wants). item_buy_num is only a backup
        in case some item has the other semantics."""
        initial_state = _shop_state(
            30, 100,
            [_shop_row(201, 8002, coin=55)],
            owned=[{"item_id": 8002, "num": 1}],
        )
        refreshed_state = _shop_state(
            30, 100,
            [_shop_row(201, 8002, coin=55)],
            owned=[{"item_id": 8002, "num": 1}],
        )
        ok_state = _shop_state(
            30, 45,
            [_shop_row(201, 8002, coin=55, item_buy_num=1)],
            owned=[{"item_id": 8002, "num": 2}],
        )
        # Force the per-item probe path by failing the batch twice; let
        # the primary inventory_count probe succeed.
        client = self._make_client(
            [
                Exception("Game error code 205"),  # batch
                Exception("Game error code 205"),  # refresh-retry batch
                ok_state,                           # probe primary = inventory_count=1
            ],
            reload_state=refreshed_state,
        )
        self.manager.last_buy_options = [{"shop_item_id": 201, "item_id": 8002}]

        _, count = self.manager._exchange_batch(
            client, initial_state,
            [{"shop_item_id": 201, "current_num": 0}],
            30,
        )

        self.assertEqual(count, 1)
        self.assertEqual(self.manager.persistent_failed_exchange_item_ids, {})
        # The probe (3rd exchange call) used inventory_count, not item_buy_num.
        self.assertEqual(
            client.exchange_calls[-1]["payload"],
            [{"shop_item_id": 201, "current_num": 1}],
        )

    def test_per_item_probe_falls_back_to_item_buy_num(self):
        """If the inventory_count primary fails with 205 AND item_buy_num
        differs, try item_buy_num as a backup. This handles the
        hypothetical case where a specific item's server-side check uses
        item_buy_num instead of inventory_count."""
        initial_state = _shop_state(
            30, 100,
            [_shop_row(201, 8002, coin=55)],
            owned=[{"item_id": 8002, "num": 2}],
        )
        refreshed_state = _shop_state(
            30, 100,
            [_shop_row(201, 8002, coin=55)],
            owned=[{"item_id": 8002, "num": 2}],
        )
        ok_state = _shop_state(30, 45, [], owned=[{"item_id": 8002, "num": 3}])
        client = self._make_client(
            [
                Exception("Game error code 205"),  # batch (inventory_count=2)
                Exception("Game error code 205"),  # refresh-retry batch
                Exception("Game error code 205"),  # probe primary inventory_count=2
                ok_state,                           # probe fallback item_buy_num=0
            ],
            reload_state=refreshed_state,
        )
        self.manager.last_buy_options = [{"shop_item_id": 201, "item_id": 8002}]

        _, count = self.manager._exchange_batch(
            client, initial_state,
            [{"shop_item_id": 201, "current_num": 0}],
            30,
        )

        self.assertEqual(count, 1)
        self.assertEqual(self.manager.persistent_failed_exchange_item_ids, {})
        # Last call was the item_buy_num fallback (=0).
        self.assertEqual(
            client.exchange_calls[-1]["payload"],
            [{"shop_item_id": 201, "current_num": 0}],
        )

    def test_per_item_probe_records_failure_when_both_values_match(self):
        """If item_buy_num == inventory_count (e.g. both 0 for a fresh
        slot and a never-owned item), the fallback is meaningless and
        only one probe attempt is made. A 205 then records the failure
        normally."""
        initial_state = _shop_state(
            30, 100,
            [_shop_row(201, 8002, coin=55)],
            owned=[],
        )
        refreshed_state = _shop_state(
            30, 100,
            [_shop_row(201, 8002, coin=55)],
            owned=[],
        )
        client = self._make_client(
            [
                Exception("Game error code 205"),  # batch
                Exception("Game error code 205"),  # refresh-retry batch
                Exception("Game error code 205"),  # probe (only one — fallback skipped)
            ],
            reload_state=refreshed_state,
        )
        self.manager.last_buy_options = [{"shop_item_id": 201, "item_id": 8002}]

        _, count = self.manager._exchange_batch(
            client, initial_state,
            [{"shop_item_id": 201, "current_num": 0}],
            30,
        )

        self.assertEqual(count, 0)
        self.assertEqual(self.manager.persistent_failed_exchange_item_ids, {8002: 1})

    def test_three_batch_205s_no_longer_auto_blacklist_items(self):
        """Old behavior: 3 batch 205s with the same items → items hit the
        PERSISTENT_EXCHANGE_FAIL_THRESHOLD (=3) and got disabled for the
        career even though they were never tried individually. New
        behavior: per-item probes succeed → no strikes accumulate."""
        for _ in range(3):
            initial_state = _shop_state(30, 100, [_shop_row(101, 9001), _shop_row(102, 9002)])
            refreshed_state = _shop_state(30, 100, [_shop_row(101, 9001), _shop_row(102, 9002)])
            ok_after_101 = _shop_state(30, 90, [_shop_row(101, 9001, item_buy_num=1), _shop_row(102, 9002)])
            ok_after_102 = _shop_state(30, 80, [_shop_row(101, 9001, item_buy_num=1), _shop_row(102, 9002, item_buy_num=1)])
            client = self._make_client(
                [
                    Exception("Game error code 205"),  # batch
                    Exception("Game error code 205"),  # refresh-retry batch
                    ok_after_101,                       # probe 101 ok
                    ok_after_102,                       # probe 102 ok
                ],
                reload_state=refreshed_state,
            )
            self.manager._exchange_batch(
                client, initial_state,
                [{"shop_item_id": 101, "current_num": 0}, {"shop_item_id": 102, "current_num": 0}],
                30,
            )

        self.assertEqual(
            self.manager.persistent_failed_exchange_item_ids, {},
            "three batch 205s where per-item probes succeed must not blacklist any item",
        )


if __name__ == "__main__":
    unittest.main()
