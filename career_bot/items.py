import traceback

ITEM_NAMES = {
    1001: "Speed Notepad",
    1002: "Stamina Notepad",
    1003: "Power Notepad",
    1004: "Guts Notepad",
    1005: "Wit Notepad",
    1101: "Speed Manual",
    1102: "Stamina Manual",
    1103: "Power Manual",
    1104: "Guts Manual",
    1105: "Wit Manual",
    1201: "Speed Scroll",
    1202: "Stamina Scroll",
    1203: "Power Scroll",
    1204: "Guts Scroll",
    1205: "Wit Scroll",
    2001: "Vita 20",
    2002: "Vita 40",
    2003: "Vita 65",
    2101: "Royal Kale Juice",
    2201: "Energy Drink MAX",
    2202: "Energy Drink MAX EX",
    2301: "Plain Cupcake",
    2302: "Berry Sweet Cupcake",
    3001: "Yummy Cat Food",
    3101: "Grilled Carrots",
    4001: "Pretty Mirror",
    4002: "Reporter's Binoculars",
    4003: "Master Practice Guide",
    4004: "Scholar's Hat",
    4101: "Fluffy Pillow",
    4102: "Pocket Planner",
    4103: "Rich Hand Cream",
    4104: "Smart Scale",
    4105: "Aroma Diffuser",
    4106: "Practice Drills DVD",
    4201: "Miracle Cure",
    5001: "Speed Training Application",
    5002: "Stamina Training Application",
    5003: "Power Training Application",
    5004: "Guts Training Application",
    5005: "Wit Training Application",
    7001: "Reset Whistle",
    8001: "Coaching Megaphone",
    8002: "Motivating Megaphone",
    8003: "Empowering Megaphone",
    9001: "Speed Ankle Weights",
    9002: "Stamina Ankle Weights",
    9003: "Power Ankle Weights",
    9004: "Guts Ankle Weights",
    10001: "Good-Luck Charm",
    11001: "Artisan Cleat Hammer",
    11002: "Master Cleat Hammer",
    11003: "Glow Sticks",
}

DISPLAY_TO_ID = {v: k for k, v in ITEM_NAMES.items()}

SLUG_TO_DISPLAY = {name.lower().replace("'", "").replace(" ", "_"): name for name in ITEM_NAMES.values()}

SHOP_ITEM_COSTS = {
    "Speed Notepad": 10, "Stamina Notepad": 10, "Power Notepad": 10, "Guts Notepad": 10, "Wit Notepad": 10,
    "Speed Manual": 15, "Stamina Manual": 15, "Power Manual": 15, "Guts Manual": 15, "Wit Manual": 15,
    "Speed Scroll": 30, "Stamina Scroll": 30, "Power Scroll": 30, "Guts Scroll": 30, "Wit Scroll": 30,
    "Vita 20": 35, "Vita 40": 55, "Vita 65": 75, "Royal Kale Juice": 70,
    "Energy Drink MAX": 30, "Energy Drink MAX EX": 50,
    "Plain Cupcake": 30, "Berry Sweet Cupcake": 55,
    "Yummy Cat Food": 10, "Grilled Carrots": 40,
    "Pretty Mirror": 150, "Reporter's Binoculars": 150, "Master Practice Guide": 150, "Scholar's Hat": 280,
    "Fluffy Pillow": 15, "Pocket Planner": 15, "Rich Hand Cream": 15, "Smart Scale": 15,
    "Aroma Diffuser": 15, "Practice Drills DVD": 15, "Miracle Cure": 40,
    "Speed Training Application": 150, "Stamina Training Application": 150,
    "Power Training Application": 150, "Guts Training Application": 150, "Wit Training Application": 150,
    "Reset Whistle": 20,
    "Coaching Megaphone": 40, "Motivating Megaphone": 55, "Empowering Megaphone": 70,
    "Speed Ankle Weights": 50, "Stamina Ankle Weights": 50, "Power Ankle Weights": 50, "Guts Ankle Weights": 50,
    "Good-Luck Charm": 40,
    "Artisan Cleat Hammer": 25, "Master Cleat Hammer": 40,
    "Glow Sticks": 15,
}

AILMENT_CURE_MAP = {
    "Night Owl": "Fluffy Pillow",
    "Slacker": "Pocket Planner",
    "Skin Outbreak": "Rich Hand Cream",
    "Slow Metabolism": "Smart Scale",
    "Migraine": "Aroma Diffuser",
    "Practice Poor": "Practice Drills DVD",
}

BAD_EFFECT_NAMES = {
    1: "Night Owl",
    2: "Slacker",
    3: "Skin Outbreak",
    4: "Slow Metabolism",
    5: "Migraine",
    6: "Practice Poor",
}

AILMENT_CURE_ALL = "Miracle Cure"

CURE_ITEMS = set(AILMENT_CURE_MAP.values()) | {AILMENT_CURE_ALL}
CUPCAKE_ITEMS = ("Plain Cupcake", "Berry Sweet Cupcake")
NEVER_BUY_ITEMS = {
    "Coaching Megaphone",
    "Energy Drink MAX EX",
    "Reporter's Binoculars",
    "Master Practice Guide",
}
BUY_CAPS = {
    "Energy Drink MAX": 1,
    "Rich Hand Cream": 1,
    "Pretty Mirror": 1,
    "Speed Ankle Weights": 5,
    "Stamina Ankle Weights": 5,
    "Power Ankle Weights": 5,
    "Guts Ankle Weights": 5,
}
SERVER_ITEM_INVENTORY_CAP = 5

INSTANT_USE_ITEMS = [
    "Grilled Carrots",
    "Yummy Cat Food",
    "Energy Drink MAX EX",
    "Pretty Mirror",
    "Scholar's Hat",
    "Reporter's Binoculars",
    "Master Practice Guide",
    "Speed Notepad", "Stamina Notepad", "Power Notepad", "Guts Notepad", "Wit Notepad",
    "Speed Manual", "Stamina Manual", "Power Manual", "Guts Manual", "Wit Manual",
    "Speed Scroll", "Stamina Scroll", "Power Scroll", "Guts Scroll", "Wit Scroll",
    "Speed Training Application", "Stamina Training Application",
    "Power Training Application", "Guts Training Application", "Wit Training Application",
]

ONE_TIME_BUFF_ITEMS = {
    "Pretty Mirror",
    "Scholar's Hat",
    "Reporter's Binoculars",
    "Master Practice Guide",
}

ENERGY_ITEMS = {
    "Vita 20": 20,
    "Vita 40": 40,
    "Vita 65": 65,
    "Royal Kale Juice": 100,
    "Energy Drink MAX": 30,
}

MEGAPHONE_TIERS = {
    "Coaching Megaphone": (1, 4),
    "Motivating Megaphone": (2, 3),
    "Empowering Megaphone": (3, 2),
}

TRAINING_TYPE_ANKLET = {
    101: "Speed Ankle Weights",
    601: "Speed Ankle Weights",
    105: "Stamina Ankle Weights",
    602: "Stamina Ankle Weights",
    102: "Power Ankle Weights",
    603: "Power Ankle Weights",
    103: "Guts Ankle Weights",
    604: "Guts Ankle Weights",
}

TRAINING_ITEM_DECK_TYPE_INDEX = {
    "Speed Ankle Weights": 0,
    "Stamina Ankle Weights": 1,
    "Power Ankle Weights": 2,
    "Guts Ankle Weights": 3,
    "Speed Training Application": 0,
    "Stamina Training Application": 1,
    "Power Training Application": 2,
    "Guts Training Application": 3,
    "Wit Training Application": 4,
}

SUMMER_CAMP_TURNS = {36, 37, 38, 39, 40, 60, 61, 62, 63, 64}
SUMMER_CAMP_STARTS = (36, 60)
SUMMER_POWER_MEGAPHONE = "Empowering Megaphone"
STAT_ORDER = ("speed", "stamina", "power", "guts", "wit")
STAT_FIELD_BY_NAME = {
    "speed": "speed",
    "stamina": "stamina",
    "power": "power",
    "guts": "guts",
    "wit": "wiz",
}
TARGET_STAT_ITEM_BY_NAME = {
    "Speed Notepad": "speed",
    "Speed Manual": "speed",
    "Speed Scroll": "speed",
    "Speed Training Application": "speed",
    "Stamina Notepad": "stamina",
    "Stamina Manual": "stamina",
    "Stamina Scroll": "stamina",
    "Stamina Training Application": "stamina",
    "Power Notepad": "power",
    "Power Manual": "power",
    "Power Scroll": "power",
    "Power Training Application": "power",
    "Guts Notepad": "guts",
    "Guts Manual": "guts",
    "Guts Scroll": "guts",
    "Guts Training Application": "guts",
    "Wit Notepad": "wit",
    "Wit Manual": "wit",
    "Wit Scroll": "wit",
    "Wit Training Application": "wit",
}

DEFAULT_ITEM_TIERS = {
    "speed_notepad": 1,
    "speed_manual": 1,
    "speed_scroll": 1,
    "stamina_notepad": 1,
    "stamina_manual": 1,
    "stamina_scroll": 1,
    "power_notepad": 1,
    "power_manual": 1,
    "power_scroll": 1,
    "guts_notepad": 1,
    "guts_manual": 1,
    "guts_scroll": 1,
    "wit_notepad": 1,
    "wit_manual": 1,
    "wit_scroll": 1,
    "vita_20": 3,
    "vita_40": 2,
    "vita_65": 2,
    "royal_kale_juice": 3,
    "energy_drink_max": 6,
    "energy_drink_max_ex": 7,
    "plain_cupcake": 3,
    "berry_sweet_cupcake": 4,
    "yummy_cat_food": 7,
    "grilled_carrots": 4,
    "pretty_mirror": 7,
    "reporters_binoculars": 8,
    "master_practice_guide": 7,
    "scholars_hat": 8,
    "fluffy_pillow": 7,
    "pocket_planner": 7,
    "rich_hand_cream": 5,
    "smart_scale": 7,
    "aroma_diffuser": 7,
    "practice_drills_dvd": 8,
    "miracle_cure": 5,
    "speed_training_application": 7,
    "stamina_training_application": 7,
    "power_training_application": 7,
    "guts_training_application": 7,
    "wit_training_application": 7,
    "reset_whistle": 1,
    "coaching_megaphone": 999,
    "motivating_megaphone": 3,
    "empowering_megaphone": 3,
    "speed_ankle_weights": 7,
    "stamina_ankle_weights": 7,
    "power_ankle_weights": 7,
    "guts_ankle_weights": 7,
    "good-luck_charm": 3,
    "artisan_cleat_hammer": 1,
    "master_cleat_hammer": 1,
    "glow_sticks": 8,
}


def display_to_slug(name):
    return str(name or "").lower().replace("'", "").replace(" ", "_")


def extract_error_codes(text):
    codes = []
    seen = set()
    for token in str(text or "").replace(":", " ").replace(",", " ").split():
        if not token.isdigit():
            continue
        code = int(token)
        if code in seen:
            continue
        seen.add(code)
        codes.append(code)
    return codes


def exception_details(exc):
    details = {
        "type": type(exc).__name__,
        "message": str(exc),
        "error_codes": extract_error_codes(str(exc)),
        "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)),
    }
    for attr in (
        "endpoint",
        "request_payload",
        "response_body",
        "response_text",
        "http_status",
        "result_code",
        "response_code",
        "req_id",
    ):
        value = getattr(exc, attr, None)
        if value is not None and value != "":
            details[attr] = value
    return details


class MantItemManager:
    # After this many failed exchange attempts (across different shop snapshots
    # — i.e. across turns), an item is blacklisted for the rest of the career.
    # The original snapshot-only failure set resets every turn (because
    # limit_turn ticks down each turn → new snapshot key → cleared set), which
    # meant the bot kept retrying the same broken items on every shop refresh
    # and producing endless 205 storms. The persistent tracker survives shop
    # refreshes and stops the spam after N consecutive failures.
    PERSISTENT_EXCHANGE_FAIL_THRESHOLD = 3

    def __init__(self):
        self.used_buffs = set()
        self.failed_exchange_this_snapshot = set()
        # Persistent (career-scoped) item-level fail tracker. Keyed by the
        # stable `item_id` (NOT shop_item_id, which changes per snapshot).
        # Once a fail count crosses PERSISTENT_EXCHANGE_FAIL_THRESHOLD the
        # item is permanently skipped for this career.
        self.persistent_failed_exchange_item_ids = {}
        self.failed_use_this_turn = set()
        self.current_turn = None
        self.shop_snapshot_key = None
        self.recover_after_exchange_error = False
        self.recover_after_use_error = False
        self.last_buy_options = []
        self.last_buy_selected = []
        self.last_buy_attempt = []
        self.last_buy_result = {}
        self.last_use_options = []
        self.last_use_selected = []
        self.last_use_attempt = []
        self.last_use_result = {}
        self.last_use_decision_rationale = {}
        self.last_pre_race_use_selected = []
        self.last_pre_race_use_attempt = []
        self.last_pre_race_use_result = {}
        self.buy_attempt_events = []
        self.use_attempt_events = []

    def reset_scoped_failures(self):
        # Preserves failed_exchange_this_snapshot / failed_use_this_turn / current_turn /
        # shop_snapshot_key. _set_turn and _set_shop_snapshot reset them when the
        # underlying turn or shop snapshot actually changes; clearing here too would wipe
        # the failure tracking between same-turn retries and cause the bot to retry the
        # exact same doomed payload.
        # NOTE: persistent_failed_exchange_item_ids is also preserved here —
        # it's career-scoped, not call-scoped, and is only cleared by
        # reset_career_scoped_failures() at the start of a new career.
        self.last_buy_options = []
        self.last_buy_selected = []
        self.last_buy_attempt = []
        self.last_buy_result = {}
        self.last_use_options = []
        self.last_use_selected = []
        self.last_use_attempt = []
        self.last_use_result = {}
        self.buy_attempt_events = []
        self.use_attempt_events = []

    def reset_career_scoped_failures(self):
        """Wipe career-wide fail tracking. Called at the start of every new
        career so persistent-failed items don't bleed across careers."""
        self.persistent_failed_exchange_item_ids = {}
        self.used_buffs = set()
        self.failed_exchange_this_snapshot = set()
        self.failed_use_this_turn = set()
        self.shop_snapshot_key = None
        self.recover_after_exchange_error = False
        self.recover_after_use_error = False

    def _set_turn(self, turn):
        turn = int(turn or 0)
        if self.current_turn != turn:
            self.current_turn = turn
            self.failed_use_this_turn = set()

    def _set_shop_snapshot(self, rows):
        key = tuple(
            (
                int(row.get("shop_item_id") or 0),
                int(row.get("item_id") or 0),
                int(row.get("coin_num") or 0),
                int(row.get("item_buy_num") or 0),
                int(row.get("limit_buy_count") or 0),
                int(row.get("limit_turn") or 0),
            )
            for row in rows or []
        )
        if self.shop_snapshot_key != key:
            self.shop_snapshot_key = key
            self.failed_exchange_this_snapshot = set()

    def _inventory_row_count(self, row):
        return int((row or {}).get("num") or (row or {}).get("current_num") or (row or {}).get("item_num") or 0)

    def _server_inventory_cap_reached(self, name, owned, pending=0):
        if not name:
            return False
        return int((owned or {}).get(name) or 0) + int(pending or 0) >= SERVER_ITEM_INVENTORY_CAP

    def _exchange_request_payload(self, payload, current_turn):
        return {
            "exchange_item_info_array": [
                {
                    "shop_item_id": int((item or {}).get("shop_item_id") or 0),
                    "current_num": int((item or {}).get("current_num") or 0),
                }
                for item in (payload or [])
                if int((item or {}).get("shop_item_id") or 0) > 0
            ],
            "current_turn": int(current_turn or 0),
        }

    def _use_request_payload(self, payload, current_turn):
        return {
            "use_item_info_array": [
                {
                    "item_id": int((item or {}).get("item_id") or 0),
                    "use_num": int((item or {}).get("use_num") or 0),
                    "current_num": int((item or {}).get("current_num") or 0),
                }
                for item in (payload or [])
                if int((item or {}).get("item_id") or 0) > 0
            ],
            "current_turn": int(current_turn or 0),
        }

    def _exchange_payload_context(self, state, payload, current_turn):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        free = data.get("free_data_set") or {}
        source_turn = int(chara.get("turn") or 0)
        shop_rows = {
            int(row.get("shop_item_id") or 0): dict(row or {})
            for row in free.get("pick_up_item_info_array") or []
            if int(row.get("shop_item_id") or 0) > 0
        }
        inventory_rows = {
            int(row.get("item_id") or 0): dict(row or {})
            for row in free.get("user_item_info_array") or []
            if int(row.get("item_id") or 0) > 0
        }
        payload_shop_rows = []
        payload_inventory_rows = []
        payload_item_details = []
        payload_shop_item_ids = []
        payload_item_ids = []
        seen_inventory_ids = set()
        for item in payload or []:
            shop_item_id = int((item or {}).get("shop_item_id") or 0)
            if shop_item_id <= 0:
                continue
            payload_shop_item_ids.append(shop_item_id)
            shop_row = dict(shop_rows.get(shop_item_id) or {})
            item_id = int(shop_row.get("item_id") or self._resolve_item_id_for_shop_item(shop_item_id) or 0)
            inventory_row = dict(inventory_rows.get(item_id) or {})
            payload_shop_rows.append(shop_row or {"shop_item_id": shop_item_id, "item_id": item_id, "_missing": True})
            if item_id > 0:
                payload_item_ids.append(item_id)
                if item_id not in seen_inventory_ids:
                    seen_inventory_ids.add(item_id)
                    payload_inventory_rows.append(inventory_row or {"item_id": item_id, "_missing": True})
            payload_item_details.append({
                "payload_row": {
                    "shop_item_id": shop_item_id,
                    "current_num": int((item or {}).get("current_num") or 0),
                },
                "item_id": item_id,
                "item_name": ITEM_NAMES.get(item_id, ""),
                "shop_row": shop_row or {"shop_item_id": shop_item_id, "item_id": item_id, "_missing": True},
                "inventory_row": inventory_row or ({"item_id": item_id, "_missing": True} if item_id > 0 else {}),
                "inventory_count": self._inventory_row_count(inventory_row),
            })
        return {
            "endpoint": "single_mode_free/multi_item_exchange",
            "request_payload": self._exchange_request_payload(payload, current_turn),
            "source_state_turn": source_turn,
            "request_current_turn": int(current_turn or 0),
            "turn_drift": source_turn != int(current_turn or 0),
            "payload_shop_item_ids": payload_shop_item_ids,
            "payload_item_ids": payload_item_ids,
            "payload_shop_rows": payload_shop_rows,
            "payload_inventory_rows": payload_inventory_rows,
            "payload_item_details": payload_item_details,
        }

    def _use_payload_context(self, state, payload, current_turn):
        data = (state or {}).get("data") or {}
        chara = data.get("chara_info") or {}
        free = data.get("free_data_set") or {}
        source_turn = int(chara.get("turn") or 0)
        inventory_rows = {
            int(row.get("item_id") or 0): dict(row or {})
            for row in free.get("user_item_info_array") or []
            if int(row.get("item_id") or 0) > 0
        }
        payload_inventory_rows = []
        payload_item_details = []
        payload_item_ids = []
        seen_inventory_ids = set()
        for item in payload or []:
            item_id = int((item or {}).get("item_id") or 0)
            if item_id <= 0:
                continue
            inventory_row = dict(inventory_rows.get(item_id) or {})
            payload_item_ids.append(item_id)
            if item_id not in seen_inventory_ids:
                seen_inventory_ids.add(item_id)
                payload_inventory_rows.append(inventory_row or {"item_id": item_id, "_missing": True})
            payload_item_details.append({
                "payload_row": {
                    "item_id": item_id,
                    "use_num": int((item or {}).get("use_num") or 0),
                    "current_num": int((item or {}).get("current_num") or 0),
                },
                "item_name": ITEM_NAMES.get(item_id, ""),
                "inventory_row": inventory_row or {"item_id": item_id, "_missing": True},
                "inventory_count": self._inventory_row_count(inventory_row),
            })
        return {
            "endpoint": "single_mode_free/multi_item_use",
            "request_payload": self._use_request_payload(payload, current_turn),
            "source_state_turn": source_turn,
            "request_current_turn": int(current_turn or 0),
            "turn_drift": source_turn != int(current_turn or 0),
            "payload_item_ids": payload_item_ids,
            "payload_inventory_rows": payload_inventory_rows,
            "payload_item_details": payload_item_details,
        }

    def handle(self, client, state, preset, best_command=None, status=None, race_planner=None):
        current = state
        current, bought = self.buy_shop_items(client, current, preset, race_planner)
        # On success, exchange_items already returned the updated state in `current`.
        # Only reload when the operation hit a recoverable error (201/205/208) that left
        # client-side state desynced from the server.
        if self.recover_after_exchange_error:
            current = self._reload_career(client, current, "buy")
        current, used = self.use_items(client, current, preset, best_command, status, race_planner)
        if self.recover_after_use_error:
            current = self._reload_career(client, current, "use")
        return current, bought, used

    def handle_pre_race(self, client, state, preset, payload, status=None, race_planner=None):
        current, bought = self.buy_shop_items(client, state, preset, race_planner)
        if self.recover_after_exchange_error:
            current = self._reload_career(client, current, "pre_race_buy")

        current, instant_used = self.use_items(client, current, preset, None, status, race_planner)
        if self.recover_after_use_error:
            current = self._reload_career(client, current, "pre_race_use")

        data = current.get("data") or {}
        free = data.get("free_data_set") or {}
        chara = data.get("chara_info") or {}
        owned = self._owned_map(free)
        self.last_pre_race_use_selected = []
        self.last_pre_race_use_attempt = []
        self.last_pre_race_use_result = {}

        turn = int(chara.get("turn") or 0)
        self._set_turn(turn)
        program_id = int((payload or {}).get("program_id") or 0)

        if not owned:
            self.last_pre_race_use_result = {"skip": "no_owned"}
            return current, instant_used

        targets = []
        SUMMER_CAMP_2_START = 60
        CLIMAX_RACE_TURNS = [74, 76, 78]

        vital = int(chara.get("vital") or 0)
        cfg = self._mant_cfg(preset)
        if self._is_race_heavy_route(preset) and vital <= int(cfg.get("race_heavy_pre_race_energy_threshold") or 25):
            # Dense parent-farming schedules can chain mandatory races into
            # summer/training windows. Spend normal energy items before the
            # race only when vitality is already critical; this preserves
            # post-race training turns without enabling race retries/clocks.
            targets.extend(self._energy_targets(
                chara,
                owned,
                preset,
                {"command_type": 1, "command_id": 101},
            ))
        elif owned.get("Energy Drink MAX", 0) > 0 and vital <= 1:
            targets.append(("Energy Drink MAX", 1))

        cleat_choice = self._old_ui_cleat_before_race(owned, turn, program_id, race_planner)
        is_climax_race = turn in CLIMAX_RACE_TURNS
        is_g1 = self._is_g1_program(program_id, race_planner)
        use_gear = cleat_choice is not None or is_climax_race or is_g1 or turn > SUMMER_CAMP_2_START
        if use_gear and owned.get("Glow Sticks", 0) > 0:
            targets.append(("Glow Sticks", 1))
        if cleat_choice:
            targets.append((cleat_choice, 1))

        targets = self._merge_targets(targets, owned)
        self.last_pre_race_use_selected = [{"name": name, "item_id": DISPLAY_TO_ID.get(name), "use_num": count} for name, count in targets]
        if not targets:
            self.last_pre_race_use_result = {"skip": "no_targets"}
            return current, instant_used

        use_payload = []
        for name, count in targets:
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id or item_id in self.failed_use_this_turn:
                continue
            item_count = int(owned.get(name) or 0)
            if item_count <= 0:
                continue
            use_payload.append({"item_id": item_id, "use_num": min(count, item_count), "current_num": item_count})

        if use_payload:
            self.last_pre_race_use_attempt = list(use_payload)
            request_context = self._use_payload_context(current, use_payload, turn)
            event = {
                "turn": turn,
                "source_state_turn": request_context.get("source_state_turn"),
                "request_current_turn": request_context.get("request_current_turn"),
                "turn_drift": request_context.get("turn_drift"),
                "endpoint": request_context.get("endpoint"),
                "selected": list(self.last_pre_race_use_selected),
                "attempt": list(use_payload),
                "payload": list(use_payload),
                "request_payload": request_context.get("request_payload"),
                "payload_inventory_rows": request_context.get("payload_inventory_rows"),
                "payload_item_details": request_context.get("payload_item_details"),
                "result": {},
            }
            self.use_attempt_events.append(event)
            try:
                if hasattr(client, "wait_complex_delay"):
                    client.wait_complex_delay()
                use_response = client.use_items(use_payload, turn)
                # use_items response already carries the updated state; assign instead
                # of firing a redundant single_mode_free/load right after.
                self.last_pre_race_use_result = {
                    "result": "ok",
                    "turn": turn,
                    "endpoint": request_context.get("endpoint"),
                    "payload": list(use_payload),
                    "request_payload": request_context.get("request_payload"),
                    "payload_inventory_rows": request_context.get("payload_inventory_rows"),
                    "payload_item_details": request_context.get("payload_item_details"),
                    "source_state_turn": request_context.get("source_state_turn"),
                    "request_current_turn": request_context.get("request_current_turn"),
                    "turn_drift": request_context.get("turn_drift"),
                    "response_body_verbatim": use_response,
                }
                if isinstance(use_response, dict) and use_response.get("data"):
                    current = use_response
                event["result"] = self.last_pre_race_use_result
                return current, instant_used + len(use_payload)
            except Exception as exc:
                print(f"Pre-Race Item Use Error at turn {turn}: {exc}")
                if "205" in str(exc):
                    for item in use_payload:
                        self.failed_use_this_turn.add(item["item_id"])
                error_details = exception_details(exc)
                self.last_pre_race_use_result = {
                    "result": "failed",
                    "turn": turn,
                    "endpoint": request_context.get("endpoint"),
                    "error": str(exc),
                    "payload": use_payload,
                    "request_payload": request_context.get("request_payload"),
                    "payload_inventory_rows": request_context.get("payload_inventory_rows"),
                    "payload_item_details": request_context.get("payload_item_details"),
                    "source_state_turn": request_context.get("source_state_turn"),
                    "request_current_turn": request_context.get("request_current_turn"),
                    "turn_drift": request_context.get("turn_drift"),
                    "recoverable": any(code in str(exc) for code in ("201", "205", "208")),
                    "error_codes": extract_error_codes(str(exc)),
                    "error_details": error_details,
                    "response_body_verbatim": error_details.get("response_body") or error_details.get("response_text"),
                }
                event["result"] = self.last_pre_race_use_result
                return current, instant_used

        return current, instant_used

    def buy_shop_items(self, client, state, preset, race_planner=None):
        data = state.get("data") or {}
        free = data.get("free_data_set") or {}
        chara = data.get("chara_info") or {}
        current_turn = int(chara.get("turn") or 0)
        pickups = free.get("pick_up_item_info_array") or []
        self._set_turn(current_turn)
        self._set_shop_snapshot(pickups)
        cfg = self._mant_cfg(preset)
        tiers = cfg.get("item_tiers") or DEFAULT_ITEM_TIERS
        tier_count = int(cfg.get("tier_count") or 8)
        coin_val = free.get("coin_num")
        if coin_val is None:
            coin_val = free.get("gained_coin_num")
        budget = int(coin_val or 0)
        start_budget = budget
        self.last_buy_options = []
        self.last_buy_selected = []
        self.last_buy_attempt = []
        self.last_buy_result = {"mant_coin": budget}
        self.buy_attempt_events = []
        if not pickups:
            self.last_buy_result = {"skip": "no_pickups", "mant_coin": budget}
            return state, 0
        if budget <= 0:
            self.last_buy_result = {"skip": "no_mant_coin", "mant_coin": budget}
            return state, 0

        owned = self._owned_map(free)
        any_sale = any(int(row.get("coin_num") or 0) < int(row.get("original_coin_num") or 0) for row in pickups if int(row.get("original_coin_num") or 0) > 0)
        sale_modifier = 0.9 if any_sale else 1.0
        motivation = int(chara.get("motivation") or 3)
        non_rainbow_count = 0
        for row in chara.get("evaluation_info_array") or []:
            if int(row.get("target_id") or 0) in {1, 2, 3, 4, 5, 6} and int(row.get("evaluation") or 0) < 80:
                non_rainbow_count += 1
        bbq_threshold = int(cfg.get("bbq_unmaxxed_cards") or 3)
        bbq_shift = non_rainbow_count - bbq_threshold
        is_senior_or_later = current_turn > 48
        total_cupcakes = sum(owned.get(n, 0) for n in CUPCAKE_ITEMS)
        shop_has_kale = any(ITEM_NAMES.get(int(row.get("item_id") or 0)) == "Royal Kale Juice" for row in pickups or [])
        kale_pair_needed = owned.get("Royal Kale Juice", 0) > total_cupcakes or (shop_has_kale and total_cupcakes <= 0)
        skip_cupcakes = not kale_pair_needed and (
            total_cupcakes >= 2 or (is_senior_or_later and total_cupcakes >= 1) or motivation >= 5
        )
        active_ailments = self._active_bad_statuses(data)
        has_miracle = owned.get("Miracle Cure", 0) > 0

        available = []
        for row in pickups:
            shop_item_id = int(row.get("shop_item_id") or 0)
            item_id = int(row.get("item_id") or 0)
            name = ITEM_NAMES.get(item_id)
            if not name:
                continue
            cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(name, 9999))
            limit_turn = int(row.get("limit_turn") or 0)
            limit = int(row.get("limit_buy_count") or 1)
            current_num = int(row.get("item_buy_num") or 0)
            skip_reason = None
            if shop_item_id <= 0 or shop_item_id in self.failed_exchange_this_snapshot:
                skip_reason = "failed_snapshot"
            elif self.persistent_failed_exchange_item_ids.get(item_id, 0) >= self.PERSISTENT_EXCHANGE_FAIL_THRESHOLD:
                # Career-scoped permanent skip: this item_id has failed exchange
                # >= 3 times across different shop snapshots, so the server is
                # genuinely refusing it (state desync, prereq lock, etc.) and
                # retrying every turn just spams 205s. Move on to other items.
                skip_reason = "persistent_failed_career"
            elif limit_turn > 0 and limit_turn < current_turn:
                skip_reason = "expired"
            elif current_num >= limit:
                skip_reason = "limit_reached"
            elif self._server_inventory_cap_reached(name, owned):
                skip_reason = "inventory_cap"
            elif self._skip_buy(name, owned, preset, current_turn, start_budget, data, race_planner):
                skip_reason = "skip_buy"
            self.last_buy_options.append({
                "name": name,
                "item_id": item_id,
                "shop_item_id": shop_item_id,
                "cost": cost,
                "current_num": current_num,
                "limit": limit,
                "limit_turn": limit_turn,
                "turns_left": (limit_turn - current_turn) if limit_turn > 0 else None,
                "skip_reason": skip_reason,
            })
            if not skip_reason:
                available.append((name, row))

        if not available:
            self.last_buy_result = {"skip": "no_available", "mant_coin": budget}
            return state, 0

        effective_rows = []
        for name, row in available:
            slug = display_to_slug(name)
            base_t = int(tiers.get(slug) or 999)
            eff_t = base_t
            for ailment in active_ailments:
                specific_cure = AILMENT_CURE_MAP.get(ailment)
                if specific_cure and name == specific_cure and not has_miracle and owned.get(name, 0) <= 0:
                    eff_t = 1
            if slug == "miracle_cure" and active_ailments and not has_miracle:
                eff_t = 1
            if slug == "grilled_carrots":
                eff_t = min(eff_t, base_t - bbq_shift)
            elif slug == "good-luck_charm":
                eff_t = 1
            elif slug == "pretty_mirror":
                eff_t = min(eff_t, int(cfg.get("pretty_mirror_buy_tier") or 2))
            elif slug in {"plain_cupcake", "berry_sweet_cupcake"}:
                if kale_pair_needed:
                    eff_t = 1
                elif skip_cupcakes:
                    eff_t = 999
            elif slug in {"artisan_cleat_hammer", "master_cleat_hammer"}:
                eff_t = 999
            if self._summer_item_policy_enabled(preset):
                if self._should_stock_summer_empowering_megaphone(name, owned, preset, current_turn):
                    eff_t = min(eff_t, int(cfg.get("summer_empowering_megaphone_buy_tier") or 1))
                elif self._should_stock_summer_energy(name, owned, preset, current_turn):
                    eff_t = min(eff_t, int(cfg.get("summer_energy_reserve_buy_tier") or 1))
                elif self._should_stock_race_heavy_energy(name, owned, preset, current_turn):
                    eff_t = min(eff_t, int(cfg.get("race_heavy_energy_buy_tier") or 1))
                elif self._is_summer_training_turn(current_turn) or self._is_summer_reserve_turn(current_turn, preset):
                    if name in MEGAPHONE_TIERS:
                        eff_t = min(eff_t, int(cfg.get("summer_megaphone_buy_tier") or 2))
                    elif name in TRAINING_TYPE_ANKLET.values():
                        deck_count = self._deck_type_count_for_item(name, preset)
                        if deck_count >= 2:
                            eff_t = min(eff_t, int(cfg.get("summer_anklet_primary_buy_tier") or 1))
                        elif deck_count >= 1:
                            eff_t = min(eff_t, int(cfg.get("summer_anklet_buy_tier") or 2))
                        else:
                            eff_t = min(eff_t, int(cfg.get("summer_anklet_offdeck_buy_tier") or eff_t))
                    elif name in ENERGY_ITEMS:
                        eff_t = min(eff_t, int(cfg.get("summer_energy_buy_tier") or 2))
            target_tier = self._target_stat_item_tier(name, preset, data, current_turn)
            if target_tier is not None:
                eff_t = min(eff_t, target_tier)
            learned_adjustment = self._learned_item_phase_adjustment(name, current_turn, preset)
            if learned_adjustment:
                eff_t = max(1, eff_t + learned_adjustment)
            effective_rows.append((max(1, eff_t), name, row))

        targets = []
        selected_ids = set()
        selected_counts = {}
        cleat_row = self._old_ui_cleat_shop_target(available, owned, budget, current_turn)
        if cleat_row:
            cleat_name = ITEM_NAMES.get(int(cleat_row.get("item_id") or 0), "")
            cleat_cost = int(cleat_row.get("coin_num") or SHOP_ITEM_COSTS.get(cleat_name, 9999))
            if cleat_cost <= budget:
                targets.append(cleat_row)
                selected_ids.add(id(cleat_row))
                selected_counts[cleat_name] = selected_counts.get(cleat_name, 0) + 1
                budget -= cleat_cost

        for tier in range(1, tier_count + 1):
            tier_rows = [(name, row) for eff_t, name, row in effective_rows if eff_t == tier and id(row) not in selected_ids]
            tier_rows.sort(key=lambda item: (int(item[1].get("limit_turn") or 99), int(item[1].get("coin_num") or SHOP_ITEM_COSTS.get(item[0], 9999))))
            for name, row in tier_rows:
                if self._server_inventory_cap_reached(name, owned, selected_counts.get(name, 0)):
                    continue
                cap = BUY_CAPS.get(name)
                if cap is not None and int(owned.get(name) or 0) + selected_counts.get(name, 0) >= cap:
                    continue
                cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(name, 9999))
                remaining = budget - cost
                if remaining < 0:
                    continue
                threshold = 0
                thresholds = cfg.get("tier_thresholds") or {}
                if tier > 1 and current_turn <= 64:
                    raw_threshold = int(thresholds.get(str(tier), thresholds.get(tier, (tier - 1) * 50)) or 0)
                    threshold = int(raw_threshold * sale_modifier)
                floor = self._buy_floor(name, tier, current_turn, start_budget, budget, threshold, cfg)
                if remaining < floor:
                    continue
                targets.append(row)
                selected_ids.add(id(row))
                selected_counts[name] = selected_counts.get(name, 0) + 1
                budget = remaining

        if not targets:
            self.last_buy_result = {"skip": "no_targets", "mant_coin": budget, "start_mant_coin": start_budget}
            return state, 0

        self.last_buy_selected = [{
            "name": ITEM_NAMES.get(int(row.get("item_id") or 0), ""),
            "item_id": int(row.get("item_id") or 0),
            "shop_item_id": int(row.get("shop_item_id") or 0),
            "cost": int(row.get("coin_num") or SHOP_ITEM_COSTS.get(ITEM_NAMES.get(int(row.get("item_id") or 0), ""), 9999)),
            "current_num": int(row.get("item_buy_num") or 0),
            "limit_turn": int(row.get("limit_turn") or 0),
        } for row in targets]

        payload = []
        for row in targets:
            sid = int(row.get("shop_item_id") or 0)
            if sid > 0 and sid not in self.failed_exchange_this_snapshot:
                payload.append({"shop_item_id": sid, "current_num": 0})

        if not payload:
            self.last_buy_result = {"skip": "empty_payload", "mant_coin": budget, "start_mant_coin": start_budget}
            return state, 0

        return self._exchange_batch(client, state, payload, current_turn)

    def _exchange_batch(self, client, state, payload, current_turn):
        if not payload:
            return state, 0

        data = state.get("data") or {}
        chara = data.get("chara_info") or {}
        source_turn = int(chara.get("turn") or 0)
        initial_context = self._exchange_payload_context(state, payload, current_turn)

        if source_turn != current_turn:
            self.last_buy_result = {
                "skip": "stale_turn_detected",
                "endpoint": initial_context.get("endpoint"),
                "payload": list(payload),
                "request_payload": initial_context.get("request_payload"),
                "payload_shop_rows": initial_context.get("payload_shop_rows"),
                "payload_inventory_rows": initial_context.get("payload_inventory_rows"),
                "payload_item_details": initial_context.get("payload_item_details"),
                "request_current_turn": current_turn,
                "source_state_turn": source_turn,
                "turn_drift": True,
            }
            return state, 0

        free = data.get("free_data_set") or {}
        coin_val = free.get("coin_num")
        if coin_val is None:
            coin_val = free.get("gained_coin_num")
        budget = int(coin_val or 0)

        valid_shop_rows = {int(row.get("shop_item_id") or 0): row for row in free.get("pick_up_item_info_array") or []}
        # The server's `current_num` field is an optimistic-concurrency check
        # of the user's inventory count of the underlying item_id, not the
        # shop slot's per-snapshot buy count. Sending item_buy_num triggers
        # 205 for any item the user already owns (Megaphones, Ankle Weights,
        # Vitas, etc.). Confirmed via diagnostic logging in the per-item
        # probe — runs consistently recovered with current_num=inventory.
        owned = self._owned_map(free)

        valid_payload = []
        attempt_items = []
        total_cost = 0
        for item in payload:
            shop_item_id = int(item.get("shop_item_id") or 0)
            if shop_item_id <= 0:
                continue
            shop_row = valid_shop_rows.get(shop_item_id)
            if not shop_row:
                continue
            item_id = int(shop_row.get("item_id") or 0)
            item_name = ITEM_NAMES.get(item_id, "")
            cost = int(shop_row.get("coin_num") or SHOP_ITEM_COSTS.get(item_name, 9999))
            limit_turn = int(shop_row.get("limit_turn") or 0)
            if limit_turn > 0 and limit_turn < current_turn:
                continue
            if int(shop_row.get("item_buy_num") or 0) >= int(shop_row.get("limit_buy_count") or 1):
                continue
            if self._server_inventory_cap_reached(item_name, owned):
                continue
            if total_cost + cost > budget:
                continue
            total_cost += cost
            current_num = int(owned.get(item_name, 0))

            valid_payload.append({
                "shop_item_id": shop_item_id,
                "current_num": current_num,
            })
            attempt_items.append({
                "shop_item_id": shop_item_id,
                "cost": cost,
                "current_num": current_num,
            })

        if not valid_payload:
            self.last_buy_result = {"skip": "preflight_failed", "mant_coin": budget}
            return state, 0

        self.last_buy_attempt = list(valid_payload)
        event = {}
        # Preventive refresh: state passed in here may be several API calls
        # stale (skill buys, event drains, command applies in this turn).
        # multi_item_exchange is the most snapshot-sensitive endpoint in the
        # bot's per-turn sequence, so refresh immediately before the call.
        # Re-validates `valid_payload` against the refreshed shop rows — any
        # items that disappeared since the in-turn snapshot are silently
        # dropped (they're not errors, just gone).
        state, valid_payload = self._refresh_and_revalidate_before_exchange(
            client, state, valid_payload, current_turn, event
        )
        request_context = self._exchange_payload_context(state, valid_payload, current_turn)
        event.update({
            "turn": current_turn,
            "source_state_turn": request_context.get("source_state_turn"),
            "request_current_turn": request_context.get("request_current_turn"),
            "turn_drift": request_context.get("turn_drift"),
            "endpoint": request_context.get("endpoint"),
            "selected": list(self.last_buy_selected),
            "attempt": list(attempt_items),
            "payload": list(valid_payload),
            "request_payload": request_context.get("request_payload"),
            "payload_shop_rows": request_context.get("payload_shop_rows"),
            "payload_inventory_rows": request_context.get("payload_inventory_rows"),
            "payload_item_details": request_context.get("payload_item_details"),
            "result": {},
        })
        self.buy_attempt_events.append(event)
        if not valid_payload:
            self.last_buy_result = {
                "skip": "all_items_missing_after_refresh",
                "turn": current_turn,
                "endpoint": request_context.get("endpoint"),
                "request_payload": request_context.get("request_payload"),
                "payload_shop_rows": request_context.get("payload_shop_rows"),
                "payload_inventory_rows": request_context.get("payload_inventory_rows"),
                "payload_item_details": request_context.get("payload_item_details"),
                "source_state_turn": request_context.get("source_state_turn"),
                "request_current_turn": request_context.get("request_current_turn"),
                "turn_drift": request_context.get("turn_drift"),
            }
            event["result"] = self.last_buy_result
            return state, 0
        # First attempt: original batch. Drop the client-side 205 retry — a
        # 205 is a stale-snapshot signal from the server, and retrying the
        # same payload won't make the server's view of the shop catch up to
        # ours. We handle 205 by refreshing state and retrying once at this
        # layer, then falling back to per-item probes (see below).
        try:
            if hasattr(client, "wait_complex_delay"):
                client.wait_complex_delay()
            result = client.exchange_items(valid_payload, current_turn, retry_205=0, retry_208=3)
            self.last_buy_result = {
                "result": "ok",
                "turn": current_turn,
                "endpoint": request_context.get("endpoint"),
                "payload": list(valid_payload),
                "request_payload": request_context.get("request_payload"),
                "payload_shop_rows": request_context.get("payload_shop_rows"),
                "payload_inventory_rows": request_context.get("payload_inventory_rows"),
                "payload_item_details": request_context.get("payload_item_details"),
                "source_state_turn": request_context.get("source_state_turn"),
                "request_current_turn": request_context.get("request_current_turn"),
                "turn_drift": request_context.get("turn_drift"),
                "response_body_verbatim": result,
            }
            event["result"] = self.last_buy_result
            self.failed_exchange_this_snapshot = set()
            return result, len(valid_payload)
        except Exception as first_err:
            first_err_str = str(first_err)
            first_error_details = exception_details(first_err)
            is_recoverable = any(code in first_err_str for code in ("201", "205", "208"))
            if not is_recoverable:
                # Non-recoverable (network, auth, etc.) — don't blacklist
                # items for this. Snapshot-mark so we stop hammering this
                # snapshot, but leave the career-wide persistent counter
                # alone since the failure isn't an item-specific signal.
                print(f"Item Exchange Error at turn {current_turn}: {first_err}")
                for item in valid_payload:
                    self.failed_exchange_this_snapshot.add(int(item.get("shop_item_id") or 0))
                self.last_buy_result = {
                    "result": "failed",
                    "turn": current_turn,
                    "endpoint": request_context.get("endpoint"),
                    "error": first_err_str,
                    "payload": list(valid_payload),
                    "request_payload": request_context.get("request_payload"),
                    "payload_shop_rows": request_context.get("payload_shop_rows"),
                    "payload_inventory_rows": request_context.get("payload_inventory_rows"),
                    "payload_item_details": request_context.get("payload_item_details"),
                    "source_state_turn": request_context.get("source_state_turn"),
                    "request_current_turn": request_context.get("request_current_turn"),
                    "turn_drift": request_context.get("turn_drift"),
                    "recoverable": False,
                    "error_codes": extract_error_codes(first_err_str),
                    "error_details": first_error_details,
                    "response_body_verbatim": first_error_details.get("response_body") or first_error_details.get("response_text"),
                }
                event["result"] = self.last_buy_result
                return state, 0

            # Recoverable (201/205/208). Refresh shop state so the server's
            # current view becomes ours, then retry the batch ONCE against
            # the refreshed snapshot. If that still fails, fall through to
            # the per-item probe — a batch failure can't tell us WHICH item
            # is the culprit, so we have to ask one at a time.
            print(f"Item Exchange Batch failed at turn {current_turn} with {first_err}; refreshing shop and retrying.")
            self.recover_after_exchange_error = True
            refreshed_state = self._reload_career(client, state, "exchange_205_refresh")
            retry_payload = self._rebuild_payload_against_state(valid_payload, refreshed_state, current_turn)
            if retry_payload:
                retry_context = self._exchange_payload_context(refreshed_state, retry_payload, current_turn)
                event["refresh_retry_attempt"] = {
                    "turn": current_turn,
                    "source_state_turn": retry_context.get("source_state_turn"),
                    "request_current_turn": retry_context.get("request_current_turn"),
                    "turn_drift": retry_context.get("turn_drift"),
                    "endpoint": retry_context.get("endpoint"),
                    "payload": list(retry_payload),
                    "request_payload": retry_context.get("request_payload"),
                    "payload_shop_rows": retry_context.get("payload_shop_rows"),
                    "payload_inventory_rows": retry_context.get("payload_inventory_rows"),
                    "payload_item_details": retry_context.get("payload_item_details"),
                }
                try:
                    if hasattr(client, "wait_complex_delay"):
                        client.wait_complex_delay()
                    result = client.exchange_items(retry_payload, current_turn, retry_205=0, retry_208=2)
                    self.last_buy_result = {
                        "result": "ok_after_refresh",
                        "turn": current_turn,
                        "endpoint": retry_context.get("endpoint"),
                        "payload": list(retry_payload),
                        "request_payload": retry_context.get("request_payload"),
                        "payload_shop_rows": retry_context.get("payload_shop_rows"),
                        "payload_inventory_rows": retry_context.get("payload_inventory_rows"),
                        "payload_item_details": retry_context.get("payload_item_details"),
                        "source_state_turn": retry_context.get("source_state_turn"),
                        "request_current_turn": retry_context.get("request_current_turn"),
                        "turn_drift": retry_context.get("turn_drift"),
                        "original_error": first_err_str,
                        "original_error_codes": extract_error_codes(first_err_str),
                        "original_response_body_verbatim": first_error_details.get("response_body") or first_error_details.get("response_text"),
                        "response_body_verbatim": result,
                    }
                    event["result"] = self.last_buy_result
                    self.failed_exchange_this_snapshot = set()
                    return result, len(retry_payload)
                except Exception as second_err:
                    second_error_details = exception_details(second_err)
                    print(f"Item Exchange Refresh-Retry failed at turn {current_turn} with {second_err}; falling back to per-item probe.")
                    event["refresh_retry_error"] = {
                        "error": str(second_err),
                        "endpoint": retry_context.get("endpoint"),
                        "payload": list(retry_payload),
                        "request_payload": retry_context.get("request_payload"),
                        "payload_shop_rows": retry_context.get("payload_shop_rows"),
                        "payload_inventory_rows": retry_context.get("payload_inventory_rows"),
                        "payload_item_details": retry_context.get("payload_item_details"),
                        "source_state_turn": retry_context.get("source_state_turn"),
                        "request_current_turn": retry_context.get("request_current_turn"),
                        "turn_drift": retry_context.get("turn_drift"),
                        "error_codes": extract_error_codes(str(second_err)),
                        "error_details": second_error_details,
                        "response_body_verbatim": second_error_details.get("response_body") or second_error_details.get("response_text"),
                    }
                    refreshed_state = self._reload_career(client, refreshed_state, "exchange_205_probe_refresh")

            return self._exchange_per_item_fallback(
                client,
                refreshed_state,
                valid_payload,
                current_turn,
                event,
                first_err_str,
                original_error_details=first_error_details,
                original_request_context=request_context,
            )

    def _refresh_and_revalidate_before_exchange(self, client, state, valid_payload, current_turn, event):
        """Refresh shop state immediately before an exchange and drop any
        payload items that no longer appear in the refreshed snapshot.

        The state passed into _exchange_batch can be many API calls stale
        by the time the bot reaches the buy step; multi_item_exchange
        rejects with 205 when its view of the shop has drifted from the
        client's. A pre-call reload makes 205s much rarer in practice.

        Returns (state, surviving_payload). Best-effort: if the reload
        fails for any reason, returns the original state and payload
        unchanged — the regular 205-handling path will catch it.
        """
        try:
            if not hasattr(client, "load_career"):
                return state, valid_payload
            fresh = client.load_career()
        except Exception:
            return state, valid_payload
        if not isinstance(fresh, dict) or not fresh.get("data"):
            return state, valid_payload
        data = fresh.get("data") or {}
        chara = data.get("chara_info") or {}
        # If the server says we're on a different turn now, abort — the
        # rest of the turn logic operates on `current_turn` and crossing
        # that boundary mid-flow would put us out of sync.
        if int(chara.get("turn") or 0) != current_turn:
            return state, valid_payload
        free = data.get("free_data_set") or {}
        refreshed_shop_rows = {
            int(row.get("shop_item_id") or 0): row
            for row in (free.get("pick_up_item_info_array") or [])
        }
        owned = self._owned_map(free)
        survivors = []
        for item in valid_payload:
            shop_item_id = int(item.get("shop_item_id") or 0)
            shop_row = refreshed_shop_rows.get(shop_item_id)
            if not shop_row:
                continue
            item_name = ITEM_NAMES.get(int(shop_row.get("item_id") or 0), "")
            if self._server_inventory_cap_reached(item_name, owned):
                continue
            survivors.append(item)
        dropped = len(valid_payload) - len(survivors)
        if dropped:
            event["dropped_after_refresh"] = dropped
        return fresh, survivors

    def _rebuild_payload_against_state(self, prior_payload, state, current_turn):
        """Re-validate a batch payload against a freshly-loaded state. Drops
        items that are no longer in the shop, that have hit their buy limit,
        whose limit_turn has passed, or that no longer fit the budget. Used
        between batch attempts after a 205 refresh.

        Sends `current_num = inventory_count` (the server's expected value
        — see comment in _exchange_batch)."""
        data = state.get("data") or {}
        free = data.get("free_data_set") or {}
        chara = data.get("chara_info") or {}
        if int(chara.get("turn") or 0) != current_turn:
            return []
        valid_shop_rows = {int(row.get("shop_item_id") or 0): row for row in free.get("pick_up_item_info_array") or []}
        coin_val = free.get("coin_num")
        if coin_val is None:
            coin_val = free.get("gained_coin_num")
        budget = int(coin_val or 0)
        owned = self._owned_map(free)
        rebuilt = []
        total_cost = 0
        for item in prior_payload:
            shop_item_id = int(item.get("shop_item_id") or 0)
            if shop_item_id <= 0:
                continue
            shop_row = valid_shop_rows.get(shop_item_id)
            if not shop_row:
                continue
            item_id = int(shop_row.get("item_id") or 0)
            item_name = ITEM_NAMES.get(item_id, "")
            cost = int(shop_row.get("coin_num") or SHOP_ITEM_COSTS.get(item_name, 9999))
            limit_turn = int(shop_row.get("limit_turn") or 0)
            if limit_turn > 0 and limit_turn < current_turn:
                continue
            if int(shop_row.get("item_buy_num") or 0) >= int(shop_row.get("limit_buy_count") or 1):
                continue
            if self._server_inventory_cap_reached(item_name, owned):
                continue
            if total_cost + cost > budget:
                continue
            total_cost += cost
            rebuilt.append({
                "shop_item_id": shop_item_id,
                "current_num": int(owned.get(item_name, 0)),
            })
        return rebuilt

    def _exchange_per_item_fallback(
        self,
        client,
        state,
        original_payload,
        current_turn,
        event,
        original_error,
        original_error_details=None,
        original_request_context=None,
    ):
        """Try each item from the failed batch individually so a single bad
        item doesn't blacklist the whole batch. An item only earns a strike
        on the career-scoped `persistent_failed_exchange_item_ids` counter
        if it fails in isolation here — failing as part of a multi-item
        batch is not strong evidence the item itself is the problem.

        On 205, retry once with `current_num = inventory_count` instead of
        `current_num = item_buy_num`. The `current_num` field is the
        client's claim about how many of this item it has, and the server
        rejects with 205 when its view disagrees. The two reasonable
        interpretations of the field are "per-slot buy count" and
        "user inventory count"; the bot historically sent the former but
        the symptoms suggest the server wants the latter for at least
        some items (the same items keep tripping 205 across snapshots).
        Logs the diagnostic so we can tell which interpretation actually
        worked for which item.

        State is threaded through each call so successful single-item
        exchanges accumulate correctly.
        """
        current_state = state
        succeeded_sids = []
        failed_records = []
        for item in original_payload:
            shop_item_id = int(item.get("shop_item_id") or 0)
            if shop_item_id <= 0:
                continue
            data = current_state.get("data") or {}
            free = data.get("free_data_set") or {}
            chara = data.get("chara_info") or {}
            if int(chara.get("turn") or 0) != current_turn:
                # Turn rolled (e.g. via implicit advance) — bail; later turns
                # will get their own snapshot and re-evaluate.
                break
            valid_shop_rows = {int(row.get("shop_item_id") or 0): row for row in free.get("pick_up_item_info_array") or []}
            shop_row = valid_shop_rows.get(shop_item_id)
            if not shop_row:
                # Item no longer in shop (e.g. limit_turn passed, sold out
                # after refresh). Not an item-failure signal.
                continue
            coin_val = free.get("coin_num")
            if coin_val is None:
                coin_val = free.get("gained_coin_num")
            budget = int(coin_val or 0)
            item_id = int(shop_row.get("item_id") or 0)
            item_name = ITEM_NAMES.get(item_id, "")
            cost = int(shop_row.get("coin_num") or SHOP_ITEM_COSTS.get(item_name, 9999))
            if cost > budget:
                continue
            item_buy_num = int(shop_row.get("item_buy_num") or 0)
            if item_buy_num >= int(shop_row.get("limit_buy_count") or 1):
                continue
            inventory_count = int((self._owned_map(free) or {}).get(item_name, 0)) if item_name else 0
            if self._server_inventory_cap_reached(item_name, {item_name: inventory_count}):
                continue

            # Primary: current_num = inventory_count (server's expected value).
            # We left the per-item probe with this order even though
            # _exchange_batch now sends inventory_count too: if the batch
            # fell back to us, the snapshot might be stale on a per-item
            # basis (someone consumed an item between snapshot and call).
            # Item_buy_num is a sane backup interpretation worth trying.
            current_state, probe_info = self._probe_single_item(
                client, current_state, shop_item_id, inventory_count, current_turn
            )
            if probe_info.get("result") == "ok":
                succeeded_sids.append(shop_item_id)
                continue

            first_error = str(probe_info.get("error") or "")
            print(
                f"Per-item probe 205 turn={current_turn} item_id={item_id} "
                f"name={item_name!r} shop_item_id={shop_item_id} "
                f"item_buy_num={item_buy_num} inventory_count={inventory_count} "
                f"limit_buy_count={int(shop_row.get('limit_buy_count') or 1)} "
                f"cost={cost} budget={budget} primary=inventory_count"
            )

            # Fallback: try item_buy_num. The two values are equal in the
            # common case (player owns 0, slot fresh), so the fallback is
            # only meaningful when they differ — otherwise we'd be sending
            # the same payload again.
            tried_buy_num = False
            fallback_probe = {}
            if "205" in first_error and item_buy_num != inventory_count:
                tried_buy_num = True
                current_state = self._reload_career(client, current_state, "exchange_per_item_buynum_fallback")
                current_state, fallback_probe = self._probe_single_item(
                    client, current_state, shop_item_id, item_buy_num, current_turn
                )
                if fallback_probe.get("result") == "ok":
                    succeeded_sids.append(shop_item_id)
                    print(
                        f"Per-item probe RECOVERED with current_num=item_buy_num "
                        f"item_id={item_id} name={item_name!r} (inventory_count={inventory_count} failed, "
                        f"item_buy_num={item_buy_num} accepted). "
                        f"This item may need item_buy_num semantics."
                    )
                    continue
                first_error = str(fallback_probe.get("error") or "")

            final_probe = fallback_probe or probe_info
            failed_records.append({
                "shop_item_id": shop_item_id,
                "item_id": item_id,
                "name": item_name,
                "item_buy_num": item_buy_num,
                "inventory_count": inventory_count,
                "tried_item_buy_num_fallback": tried_buy_num,
                "error": first_error,
                "error_codes": extract_error_codes(first_error),
                "source_state_turn": final_probe.get("source_state_turn"),
                "request_current_turn": final_probe.get("request_current_turn"),
                "turn_drift": final_probe.get("turn_drift"),
                "request_payload": final_probe.get("request_payload"),
                "payload_shop_rows": final_probe.get("payload_shop_rows"),
                "payload_inventory_rows": final_probe.get("payload_inventory_rows"),
                "payload_item_details": final_probe.get("payload_item_details"),
                "response_body_verbatim": final_probe.get("response_body_verbatim"),
                "primary_probe": probe_info,
                "fallback_probe": fallback_probe if fallback_probe else None,
            })
            self.failed_exchange_this_snapshot.add(shop_item_id)
            if item_id:
                self.persistent_failed_exchange_item_ids[item_id] = (
                    self.persistent_failed_exchange_item_ids.get(item_id, 0) + 1
                )
                if self.persistent_failed_exchange_item_ids[item_id] == self.PERSISTENT_EXCHANGE_FAIL_THRESHOLD:
                    print(
                        f"Shop item_id={item_id} ({item_name}) permanently disabled this career after "
                        f"{self.PERSISTENT_EXCHANGE_FAIL_THRESHOLD} INDIVIDUAL exchange rejections "
                        f"(item_buy_num-fallback {'tried' if tried_buy_num else 'not applicable'})."
                    )
            if "205" in first_error or "208" in first_error:
                # Refresh between probes so the next single-item attempt
                # gets a fresh shop snapshot.
                current_state = self._reload_career(client, current_state, "exchange_per_item_refresh")
        original_request_context = dict(original_request_context or {})
        original_error_details = dict(original_error_details or {})
        self.last_buy_result = {
            "result": "per_item_fallback",
            "turn": current_turn,
            "endpoint": original_request_context.get("endpoint") or "single_mode_free/multi_item_exchange",
            "succeeded": list(succeeded_sids),
            "failed": list(failed_records),
            "original_error": original_error,
            "original_error_codes": extract_error_codes(original_error),
            "request_payload": original_request_context.get("request_payload"),
            "payload": list(original_payload),
            "payload_shop_rows": original_request_context.get("payload_shop_rows"),
            "payload_inventory_rows": original_request_context.get("payload_inventory_rows"),
            "payload_item_details": original_request_context.get("payload_item_details"),
            "source_state_turn": original_request_context.get("source_state_turn"),
            "request_current_turn": original_request_context.get("request_current_turn"),
            "turn_drift": original_request_context.get("turn_drift"),
            "recoverable": True,
            "error_details": original_error_details,
            "response_body_verbatim": original_error_details.get("response_body") or original_error_details.get("response_text"),
        }
        event["result"] = self.last_buy_result
        return current_state, len(succeeded_sids)

    def _probe_single_item(self, client, state, shop_item_id, current_num, current_turn):
        """Send a single-item exchange. Returns `(new_state, info)` where
        `info` carries the exact request payload, matching shop/inventory
        rows, and the verbatim response/error body for snapshot logging."""
        single_payload = [{
            "shop_item_id": int(shop_item_id),
            "current_num": int(current_num),
        }]
        request_context = self._exchange_payload_context(state, single_payload, current_turn)
        try:
            if hasattr(client, "wait_complex_delay"):
                client.wait_complex_delay()
            new_state = client.exchange_items(single_payload, current_turn, retry_205=0, retry_208=1)
            return new_state, {
                "result": "ok",
                "turn": int(current_turn or 0),
                "endpoint": request_context.get("endpoint"),
                "payload": list(single_payload),
                "request_payload": request_context.get("request_payload"),
                "payload_shop_rows": request_context.get("payload_shop_rows"),
                "payload_inventory_rows": request_context.get("payload_inventory_rows"),
                "payload_item_details": request_context.get("payload_item_details"),
                "source_state_turn": request_context.get("source_state_turn"),
                "request_current_turn": request_context.get("request_current_turn"),
                "turn_drift": request_context.get("turn_drift"),
                "response_body_verbatim": new_state,
            }
        except Exception as exc:
            error_details = exception_details(exc)
            return state, {
                "result": "failed",
                "turn": int(current_turn or 0),
                "endpoint": request_context.get("endpoint"),
                "payload": list(single_payload),
                "request_payload": request_context.get("request_payload"),
                "payload_shop_rows": request_context.get("payload_shop_rows"),
                "payload_inventory_rows": request_context.get("payload_inventory_rows"),
                "payload_item_details": request_context.get("payload_item_details"),
                "source_state_turn": request_context.get("source_state_turn"),
                "request_current_turn": request_context.get("request_current_turn"),
                "turn_drift": request_context.get("turn_drift"),
                "error": str(exc),
                "error_codes": extract_error_codes(str(exc)),
                "error_details": error_details,
                "response_body_verbatim": error_details.get("response_body") or error_details.get("response_text"),
            }

    def _resolve_item_id_for_shop_item(self, shop_item_id):
        """Map a shop_item_id back to its stable item_id via last_buy_options.
        Used by the per-item failure tracker; persistent_failed keys on
        item_id (not shop_item_id) so blacklists carry across snapshots."""
        sid = int(shop_item_id or 0)
        if sid <= 0:
            return 0
        for option in self.last_buy_options or []:
            if int(option.get("shop_item_id") or 0) == sid:
                return int(option.get("item_id") or 0)
        return 0

    def _is_g1_program(self, program_id, race_planner):
        if not race_planner or not program_id:
            return False
        info = (race_planner.program or {}).get(program_id) or {}
        race_inst = str(info.get("race_instance_id") or "")
        return race_inst.startswith("1")

    def _old_ui_cleat_before_race(self, owned, turn, program_id, race_planner):
        SUMMER_CAMP_2_START = 60
        CLASSIC_YEAR_END = 48
        SENIOR_YEAR_END = 72
        CLIMAX_RACE_TURNS = [74, 76, 78]
        CLIMAX_CLEAT_RESERVE = 3
        CLIMAX_MASTER_TARGET = 3

        master_qty = owned.get("Master Cleat Hammer", 0)
        artisan_qty = owned.get("Artisan Cleat Hammer", 0)
        if master_qty + artisan_qty <= 0:
            return None

        if turn in CLIMAX_RACE_TURNS:
            if master_qty > 0:
                return "Master Cleat Hammer"
            if artisan_qty > 0:
                return "Artisan Cleat Hammer"
            return None

        if turn > SUMMER_CAMP_2_START:
            total = master_qty + artisan_qty
            if total <= CLIMAX_CLEAT_RESERVE:
                return None
            reserve_total = min(CLIMAX_CLEAT_RESERVE, total)
            reserve_master = min(master_qty, reserve_total)
            spare_master = master_qty - reserve_master
            spare_artisan = artisan_qty - (reserve_total - reserve_master)

            is_senior = turn <= SENIOR_YEAR_END
            if is_senior and master_qty < CLIMAX_MASTER_TARGET and spare_artisan > 0:
                return "Artisan Cleat Hammer"
            if spare_master > 0:
                return "Master Cleat Hammer"
            if spare_artisan > 0:
                return "Artisan Cleat Hammer"
            return None

        if not self._is_g1_program(program_id, race_planner):
            return None

        is_senior = CLASSIC_YEAR_END < turn <= SENIOR_YEAR_END
        if is_senior and master_qty < CLIMAX_MASTER_TARGET:
            if artisan_qty > 0:
                return "Artisan Cleat Hammer"
            if master_qty > 0:
                return "Master Cleat Hammer"
            return None

        if master_qty > 0:
            return "Master Cleat Hammer"
        if artisan_qty > 0:
            return "Artisan Cleat Hammer"
        return None

    def _old_ui_cleat_shop_target(self, available, owned, budget, current_turn):
        CLASSIC_YEAR_END = 48
        SENIOR_YEAR_END = 72
        CLIMAX_CLEAT_RESERVE = 3
        CLIMAX_MASTER_TARGET = 3

        master_qty = owned.get("Master Cleat Hammer", 0)
        artisan_qty = owned.get("Artisan Cleat Hammer", 0)
        total_cleats = master_qty + artisan_qty
        is_senior = CLASSIC_YEAR_END < current_turn <= SENIOR_YEAR_END
        is_climax = current_turn > SENIOR_YEAR_END
        if not (is_senior or is_climax):
            return None

        available_by_name = {name: row for name, row in available}
        if is_senior:
            # Prefer building to 3 Masters for the 3 Twinkle Star Climax races.
            master_row = available_by_name.get("Master Cleat Hammer")
            if master_qty < CLIMAX_MASTER_TARGET and master_row:
                cost = int(master_row.get("coin_num") or SHOP_ITEM_COSTS.get("Master Cleat Hammer", 9999))
                if cost <= budget:
                    return master_row
            if total_cleats >= CLIMAX_CLEAT_RESERVE:
                return None
            artisan_row = available_by_name.get("Artisan Cleat Hammer")
            if artisan_row:
                cost = int(artisan_row.get("coin_num") or SHOP_ITEM_COSTS.get("Artisan Cleat Hammer", 9999))
                if cost <= budget:
                    return artisan_row
            return None

        if total_cleats >= CLIMAX_CLEAT_RESERVE:
            return None
        if total_cleats < 2 and budget < 40:
            return None
        for candidate in ("Master Cleat Hammer", "Artisan Cleat Hammer"):
            row = available_by_name.get(candidate)
            if not row:
                continue
            cost = int(row.get("coin_num") or SHOP_ITEM_COSTS.get(candidate, 9999))
            if cost > budget:
                continue
            if total_cleats < 2 and budget - cost < 40:
                continue
            return row
        return None

    def use_items(self, client, state, preset, best_command=None, status=None, race_planner=None):
        data = state.get("data") or {}
        free = data.get("free_data_set") or {}
        chara = data.get("chara_info") or {}
        owned = self._owned_map(free)
        current_turn = int(chara.get("turn") or 0)
        self._set_turn(current_turn)
        self.last_use_options = []
        self.last_use_selected = []
        self.last_use_attempt = []
        self.last_use_result = {}
        self.last_use_decision_rationale = {}
        self.use_attempt_events = []
        if not owned:
            self.last_use_result = {"skip": "no_owned"}
            self.last_use_decision_rationale = {
                "inputs": {
                    "turn": current_turn,
                    "hp": int(chara.get("vital") or 0),
                    "max_hp": int(chara.get("max_vital") or 100),
                    "motivation": int(chara.get("motivation") or 3),
                },
                "skip": "no_owned_items",
            }
            return state, 0
        targets = []
        for name in INSTANT_USE_ITEMS:
            qty = owned.get(name, 0)
            if qty <= 0:
                continue
            if DISPLAY_TO_ID.get(name) in self.failed_use_this_turn:
                continue
            if name in ONE_TIME_BUFF_ITEMS:
                if name in self.used_buffs:
                    continue
                targets.append((name, 1))
            else:

                targets.append((name, qty))

        energy_targets = self._energy_targets(chara, owned, preset, best_command)
        targets.extend(energy_targets)
        kale_pair = self._royal_kale_pair_target(chara, owned, energy_targets)
        if kale_pair:
            targets.append(kale_pair)
        ailment_targets = self._ailment_cure_targets(data, owned)
        targets.extend(ailment_targets)
        mood_target = None if kale_pair else self._mood_target(chara, owned)
        if mood_target:
            targets.append(mood_target)

        whistle = self._whistle_target(best_command, owned, preset, status, current_turn)
        charm = None
        mega = None
        anklet = None
        if whistle:
            targets = [whistle]
        else:
            charm = self._charm_target(best_command, owned, preset, status)
            if charm:
                targets.append(charm)
            mega = self._megaphone_target(state, best_command, owned, preset, status, current_turn, race_planner)
            if mega:
                targets.append(mega)
            anklet = self._anklet_target(state, best_command, owned, preset)
            if anklet:
                targets.append(anklet)

        # Per-category rationale for auditing item decisions. Captures
        # the inputs to each target-finding helper so the post-run log
        # explains why a category did or didn't fire (e.g. HP above
        # threshold, megaphone score below small_threshold, motivation
        # already maxed). Doesn't change behavior — pure visibility.
        cfg = self._mant_cfg(preset)
        decision_rationale = {
            "inputs": {
                "turn": current_turn,
                "hp": int(chara.get("vital") or 0),
                "max_hp": int(chara.get("max_vital") or 100),
                "motivation": int(chara.get("motivation") or 3),
                "best_command_id": int((best_command or {}).get("command_id") or 0),
                "best_command_type": int((best_command or {}).get("command_type") or 0),
                "best_command_failure": int((best_command or {}).get("failure_rate") or 0),
                "best_command_score": round(float(self._command_stat_gain(best_command, sp_weight=0.5)), 2) if best_command else 0.0,
                "is_summer_training_turn": self._is_summer_training_turn(current_turn),
                "is_summer_reserve_turn": self._is_summer_reserve_turn(current_turn, preset),
                "is_summer_energy_prep_turn": self._is_summer_energy_prep_turn(current_turn, preset),
            },
            "energy": {
                "threshold_used": int(cfg.get("energy_recovery_threshold") or 30),
                "targets_picked": [{"name": n, "count": c} for n, c in energy_targets],
                "fired": bool(energy_targets),
            },
            "mood": {
                "selected": list(mood_target) if mood_target else None,
                "fired": bool(mood_target),
            },
            "ailment": {
                "active_ailments": list(self._active_bad_statuses(data) or []),
                "targets_picked": [{"name": n, "count": c} for n, c in (ailment_targets or [])],
                "fired": bool(ailment_targets),
            },
            "megaphone": {
                "small_threshold": float(cfg.get("mega_small_threshold") or 11),
                "medium_threshold": float(cfg.get("mega_medium_threshold") or 21),
                "large_threshold": float(cfg.get("mega_large_threshold") or 35),
                "selected": list(mega) if mega else None,
                "fired": bool(mega),
            },
            "anklet": {
                "selected": list(anklet) if anklet else None,
                "fired": bool(anklet),
            },
            "charm": {
                "selected": list(charm) if charm else None,
                "fired": bool(charm),
            },
            "whistle": {
                "selected": list(whistle) if whistle else None,
                "fired": bool(whistle),
            },
            "kale_pair": {
                "selected": list(kale_pair) if kale_pair else None,
                "fired": bool(kale_pair),
            },
        }
        self.last_use_decision_rationale = decision_rationale

        targets = self._merge_targets(targets, owned)
        selected_names = {name for name, _ in targets}
        for name, count in sorted(owned.items()):
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id or count <= 0:
                continue
            failed = item_id in self.failed_use_this_turn
            selected = name in selected_names and not failed
            reason = None if selected else ("failed_this_turn" if failed else "not_useful_now")
            self.last_use_options.append({
                "name": name,
                "item_id": item_id,
                "current_num": int(count),
                "selected": selected,
                "skip_reason": reason,
                "reason": "selected" if selected else reason,
                "turn": current_turn,
                "context": {
                    "command_type": int((best_command or {}).get("command_type") or 0),
                    "command_id": int((best_command or {}).get("command_id") or 0),
                    "command_group_id": int((best_command or {}).get("command_group_id") or 0),
                },
            })
        if not targets:
            self.last_use_result = {"skip": "no_targets"}
            return state, 0

        payload = []
        valid_targets = []
        for name, count in targets:
            item_id = DISPLAY_TO_ID.get(name)
            if not item_id or item_id in self.failed_use_this_turn:
                continue
            have = int(owned.get(name) or 0)
            if have < count or have <= 0:
                continue

            valid_targets.append((name, count))
            payload.append({
                "item_id": item_id,
                "use_num": count,
                "current_num": have
            })

        if not payload:
            self.last_use_result = {"skip": "empty_payload"}
            return state, 0

        self.last_use_selected = [{"name": name, "item_id": DISPLAY_TO_ID.get(name), "use_num": count} for name, count in valid_targets]
        self.last_use_attempt = list(payload)
        request_context = self._use_payload_context(state, payload, current_turn)
        event = {
            "turn": current_turn,
            "source_state_turn": request_context.get("source_state_turn"),
            "request_current_turn": request_context.get("request_current_turn"),
            "turn_drift": request_context.get("turn_drift"),
            "endpoint": request_context.get("endpoint"),
            "selected": list(self.last_use_selected),
            "attempt": list(payload),
            "payload": list(payload),
            "request_payload": request_context.get("request_payload"),
            "payload_inventory_rows": request_context.get("payload_inventory_rows"),
            "payload_item_details": request_context.get("payload_item_details"),
            "result": {},
        }
        self.use_attempt_events.append(event)
        try:
            if hasattr(client, "wait_complex_delay"):
                client.wait_complex_delay()
            state = client.use_items(payload, current_turn)
            self.failed_use_this_turn = set()
            for name, _ in valid_targets:
                if name in ONE_TIME_BUFF_ITEMS:
                    self.used_buffs.add(name)
            self.last_use_result = {
                "result": "ok",
                "turn": current_turn,
                "endpoint": request_context.get("endpoint"),
                "payload": list(payload),
                "request_payload": request_context.get("request_payload"),
                "payload_inventory_rows": request_context.get("payload_inventory_rows"),
                "payload_item_details": request_context.get("payload_item_details"),
                "source_state_turn": request_context.get("source_state_turn"),
                "request_current_turn": request_context.get("request_current_turn"),
                "turn_drift": request_context.get("turn_drift"),
                "response_body_verbatim": state,
            }
            event["result"] = self.last_use_result
            return state, len(payload)
        except Exception as exc:
            print(f"Item Use Error at turn {current_turn}: {exc}")
            if any(code in str(exc) for code in ("201", "205", "208")):
                self.recover_after_use_error = True
                for item in payload:
                    self.failed_use_this_turn.add(int(item.get("item_id") or 0))
            error_details = exception_details(exc)
            self.last_use_result = {
                "result": "failed",
                "turn": current_turn,
                "endpoint": request_context.get("endpoint"),
                "error": str(exc),
                "payload": list(payload),
                "request_payload": request_context.get("request_payload"),
                "payload_inventory_rows": request_context.get("payload_inventory_rows"),
                "payload_item_details": request_context.get("payload_item_details"),
                "source_state_turn": request_context.get("source_state_turn"),
                "request_current_turn": request_context.get("request_current_turn"),
                "turn_drift": request_context.get("turn_drift"),
                "recoverable": any(code in str(exc) for code in ("201", "205", "208")),
                "error_codes": extract_error_codes(str(exc)),
                "error_details": error_details,
                "response_body_verbatim": error_details.get("response_body") or error_details.get("response_text"),
            }
            event["result"] = self.last_use_result
            return state, 0

    def _reload_career(self, client, state, reason):
        try:
            if hasattr(client, "load_career"):
                return client.load_career()
            return client.call("single_mode_free/load", {})
        except Exception as e:
            print(f"Item Manager reload failure after {reason}: {e}")
            return state

    def _is_instant_stat_item(self, name):
        slug = display_to_slug(name)
        return slug.endswith("_notepad") or slug.endswith("_manual") or slug.endswith("_scroll")

    def _coin_reserve(self, turn, budget, cfg):
        if turn <= 20:
            reserve = 160
        elif turn <= 35:
            reserve = 220
        elif turn <= 45:
            reserve = 180
        elif turn <= 55:
            reserve = 120
        elif turn <= 64:
            reserve = 80
        elif turn <= 72:
            reserve = 40
        else:
            reserve = 0
        reserve = int(cfg.get("mant_coin_reserve", reserve) if "mant_coin_reserve" in cfg else reserve)
        cap = self._coin_cap(turn, cfg)
        if cap and budget > cap:
            reserve = min(reserve, max(0, cap // 2))
        if turn >= 73:
            return 0
        if turn >= 65 and budget > 300:
            return min(reserve, 40)
        if turn >= 56 and budget > 220:
            return min(reserve, 60)
        if turn >= 46 and budget > 260:
            return min(reserve, 80)
        if turn >= 36 and budget > 320:
            return min(reserve, 120)
        return reserve

    def _coin_cap(self, turn, cfg):
        if turn <= 20:
            return int(cfg.get("mant_coin_cap_t20", 999999))
        if turn <= 35:
            return int(cfg.get("mant_coin_cap_t35", 300))
        if turn <= 45:
            return int(cfg.get("mant_coin_cap_t45", 260))
        if turn <= 55:
            return int(cfg.get("mant_coin_cap_t55", 200))
        if turn <= 64:
            return int(cfg.get("mant_coin_cap_t64", 140))
        if turn <= 72:
            return int(cfg.get("mant_coin_cap_t72", 80))
        return int(cfg.get("mant_coin_cap_final", 0))

    def _buy_floor(self, name, tier, turn, start_budget, budget, threshold, cfg):
        reserve = self._coin_reserve(turn, start_budget, cfg)
        cap = self._coin_cap(turn, cfg)
        floor = max(int(threshold or 0), reserve) if tier > 1 else 0
        if self._is_instant_stat_item(name):
            if turn >= 46:
                return 0
            if turn >= 36 and start_budget > cap:
                return min(floor, 40)
            if start_budget > cap:
                return min(floor, reserve // 2)
            return min(floor, reserve)
        if turn >= 73:
            return 0
        if start_budget > cap:
            floor = min(floor, max(0, reserve // 2))
        if start_budget >= reserve + 400:
            floor = min(floor, max(0, reserve // 3))
        elif start_budget >= reserve + 250:
            floor = min(floor, max(0, reserve // 2))
        if turn >= 65:
            floor = min(floor, 40)
        elif turn >= 56:
            floor = min(floor, 80)
        elif turn >= 46:
            floor = min(floor, 120)
        return max(0, int(floor))

    def _mant_cfg(self, preset):
        cfg = dict((preset or {}).get("mant_config") or {})
        cfg.setdefault("item_tiers", DEFAULT_ITEM_TIERS)
        cfg.setdefault("tier_count", 8)
        cfg.setdefault("tier_thresholds", {"3": 31, "7": 100, "8": 99999999999})
        cfg.setdefault("enable_good_luck_charm", False)
        cfg.setdefault("charm_failure_rate", 15)
        cfg.setdefault("pretty_mirror_early_shop_last_turn", 28)
        cfg.setdefault("pretty_mirror_late_low_bond_threshold", 45)
        cfg.setdefault("pretty_mirror_late_low_bond_count", 3)
        cfg.setdefault("pretty_mirror_buy_tier", 2)
        cfg.setdefault("mega_small_threshold", 11)
        cfg.setdefault("mega_medium_threshold", 21)
        cfg.setdefault("mega_large_threshold", 35)
        cfg.setdefault("mega_late_buy_buffer", 5)
        cfg.setdefault("training_weights_threshold", 40)
        cfg.setdefault("summer_item_policy", True)
        cfg.setdefault("summer_item_reserve_lookahead", 6)
        cfg.setdefault("summer_energy_prep_lookahead", 2)
        cfg.setdefault("summer_energy_recovery_threshold", 80)
        cfg.setdefault("summer_energy_entry_threshold", 80)
        cfg.setdefault("summer_energy_reserve_critical_threshold", 25)
        cfg.setdefault("summer_reserve_break_glass_score", 85)
        cfg.setdefault("summer_mega_small_threshold", 11)
        cfg.setdefault("summer_mega_medium_threshold", 21)
        cfg.setdefault("summer_mega_large_threshold", 35)
        cfg.setdefault("summer_empowering_megaphone_target", 2)
        cfg.setdefault("summer_empowering_megaphone_buy_tier", 1)
        cfg.setdefault("summer_anklet_threshold", 24)
        cfg.setdefault("summer_megaphone_buy_tier", 2)
        cfg.setdefault("summer_anklet_primary_buy_tier", 1)
        cfg.setdefault("summer_anklet_buy_tier", 2)
        cfg.setdefault("summer_anklet_offdeck_buy_tier", 7)
        cfg.setdefault("summer_anklet_primary_target", 3)
        cfg.setdefault("summer_anklet_secondary_target", 2)
        cfg.setdefault("summer_energy_reserve_target", 80)
        cfg.setdefault("summer_energy_reserve_buy_tier", 1)
        cfg.setdefault("summer_energy_buy_tier", 2)
        cfg.setdefault("race_heavy_route_min_races", 32)
        cfg.setdefault("race_heavy_energy_reserve_target", 80)
        cfg.setdefault("race_heavy_energy_buy_tier", 1)
        cfg.setdefault("race_heavy_energy_recovery_threshold", 76)
        cfg.setdefault("race_heavy_pre_race_energy_threshold", 25)
        cfg.setdefault("target_stat_item_policy", True)
        cfg.setdefault("target_stat_item_min_target", 700)
        cfg.setdefault("target_stat_app_latest_turn", 70)
        cfg.setdefault("target_stat_primary_app_tier", 1)
        cfg.setdefault("target_stat_secondary_app_tier", 2)
        return cfg

    def _owned_map(self, free):
        result = {}
        for row in free.get("user_item_info_array") or []:
            item_id = int(row.get("item_id") or 0)
            name = ITEM_NAMES.get(item_id)
            if name:

                qty = int(row.get("num") or row.get("current_num") or row.get("item_num") or 0)
                result[name] = result.get(name, 0) + qty
        return result

    def _active_bad_statuses(self, data):
        result = []
        for effect_id in (data.get("chara_info") or {}).get("chara_effect_id_array") or []:
            try:
                effect_id = int(effect_id)
            except (TypeError, ValueError):
                continue
            name = BAD_EFFECT_NAMES.get(effect_id)
            if name:
                result.append(name)
        return result

    def _needed_cures(self, data, owned):
        result = []
        if owned.get(AILMENT_CURE_ALL, 0) > 0:
            return result
        for ailment in self._active_bad_statuses(data):
            cure = AILMENT_CURE_MAP.get(ailment)
            if cure and owned.get(cure, 0) <= 0:
                result.append(cure)
        return result

    def _ailment_cure_targets(self, data, owned):
        result = []
        active_ailments = self._active_bad_statuses(data)
        if not active_ailments:
            return result

        unhandled_ailments = []
        for ailment in active_ailments:
            cure = AILMENT_CURE_MAP.get(ailment)
            if cure and owned.get(cure, 0) > 0:
                result.append((cure, 1))
            else:
                unhandled_ailments.append(ailment)

        if unhandled_ailments and owned.get(AILMENT_CURE_ALL, 0) > 0:
            result.append((AILMENT_CURE_ALL, 1))
        return result

    def _summer_item_policy_enabled(self, preset):
        return bool(self._mant_cfg(preset).get("summer_item_policy", True))

    def _is_summer_training_turn(self, turn):
        return int(turn or 0) in SUMMER_CAMP_TURNS

    def _turns_until_next_summer(self, turn):
        current = int(turn or 0)
        for start in SUMMER_CAMP_STARTS:
            if current < start:
                return start - current
        return None

    def _is_summer_reserve_turn(self, turn, preset):
        delta = self._turns_until_next_summer(turn)
        if delta is None or delta <= 0:
            return False
        cfg = self._mant_cfg(preset)
        return delta <= int(cfg.get("summer_item_reserve_lookahead") or 0)

    def _is_summer_energy_prep_turn(self, turn, preset):
        delta = self._turns_until_next_summer(turn)
        if delta is None or delta <= 0:
            return False
        cfg = self._mant_cfg(preset)
        return delta <= int(cfg.get("summer_energy_prep_lookahead") or 0)

    def _summer_turns_left(self, turn):
        current = int(turn or 0)
        if 36 <= current <= 40:
            return 40 - current + 1
        if 60 <= current <= 64:
            return 64 - current + 1
        return 0

    def _has_upcoming_or_current_summer(self, turn):
        return self._is_summer_training_turn(turn) or self._turns_until_next_summer(turn) is not None

    def _summer_empowering_megaphone_target(self, preset):
        return max(0, int(self._mant_cfg(preset).get("summer_empowering_megaphone_target") or 0))

    def _should_stock_summer_empowering_megaphone(self, name, owned, preset, turn):
        if name != SUMMER_POWER_MEGAPHONE:
            return False
        if not self._summer_item_policy_enabled(preset):
            return False
        if not self._has_upcoming_or_current_summer(turn):
            return False
        return int(owned.get(SUMMER_POWER_MEGAPHONE) or 0) < self._summer_empowering_megaphone_target(preset)

    def _reserved_summer_empowering_megaphones(self, owned, preset, turn):
        if not self._summer_item_policy_enabled(preset):
            return 0
        if self._is_summer_training_turn(turn):
            return 0
        if self._turns_until_next_summer(turn) is None:
            return 0
        target = self._summer_empowering_megaphone_target(preset)
        return min(target, int(owned.get(SUMMER_POWER_MEGAPHONE) or 0))

    def _summer_energy_reserve_target(self, preset):
        return max(0, int(self._mant_cfg(preset).get("summer_energy_reserve_target") or 0))

    def _summer_energy_reserve_value(self, owned):
        total = 0
        for name, value in ENERGY_ITEMS.items():
            total += int(owned.get(name) or 0) * int(value or 0)
        return total

    def _should_stock_summer_energy(self, name, owned, preset, turn):
        if name not in ENERGY_ITEMS:
            return False
        if not self._summer_item_policy_enabled(preset):
            return False
        if not (self._is_summer_training_turn(turn) or self._is_summer_reserve_turn(turn, preset)):
            return False
        return self._summer_energy_reserve_value(owned) < self._summer_energy_reserve_target(preset)

    def _is_race_heavy_route(self, preset):
        schedule = (preset or {}).get("custom_race_schedule") or []
        if not isinstance(schedule, list):
            return False
        target = int(self._mant_cfg(preset).get("race_heavy_route_min_races") or 32)
        return len(schedule) >= target

    def _race_heavy_energy_reserve_target(self, preset):
        return max(0, int(self._mant_cfg(preset).get("race_heavy_energy_reserve_target") or 0))

    def _should_stock_race_heavy_energy(self, name, owned, preset, turn):
        if name not in ENERGY_ITEMS:
            return False
        if not self._is_race_heavy_route(preset):
            return False
        if int(turn or 0) > 72:
            return False
        return self._summer_energy_reserve_value(owned) < self._race_heavy_energy_reserve_target(preset)

    def _stat_targets_from_preset(self, preset):
        result = {}
        for key in ("expect_attribute", "expect_attribute_minimum"):
            values = (preset or {}).get(key) or []
            if not isinstance(values, (list, tuple)):
                continue
            for idx, stat in enumerate(STAT_ORDER):
                if idx >= len(values):
                    continue
                try:
                    value = int(values[idx] or 0)
                except (TypeError, ValueError):
                    value = 0
                if value > result.get(stat, 0):
                    result[stat] = value
        return result

    def _current_stat_value(self, data, stat):
        chara = (data or {}).get("chara_info") or {}
        field = STAT_FIELD_BY_NAME.get(stat, stat)
        try:
            return int(chara.get(field) or 0)
        except (TypeError, ValueError):
            return 0

    def _target_stat_item_tier(self, name, preset, data, turn):
        cfg = self._mant_cfg(preset)
        if not bool(cfg.get("target_stat_item_policy", True)):
            return None
        stat = TARGET_STAT_ITEM_BY_NAME.get(name)
        if not stat:
            return None
        targets = self._stat_targets_from_preset(preset)
        target = int(targets.get(stat) or 0)
        if target < int(cfg.get("target_stat_item_min_target") or 700):
            return None
        current = self._current_stat_value(data or {}, stat)
        gap = target - current
        if gap <= 20:
            return None

        is_app = name.endswith("Training Application")
        if is_app:
            if int(turn or 0) > int(cfg.get("target_stat_app_latest_turn") or 70):
                return None
            if self._deck_type_count_for_item(name, preset) <= 0:
                return None
            if target >= 1100 and stat in {"speed", "wit"} and current < int(target * 0.94):
                return int(cfg.get("target_stat_primary_app_tier") or 1)
            if target >= 900 and stat == "power" and current < int(target * 0.88):
                return int(cfg.get("target_stat_secondary_app_tier") or 2)
            if gap >= 180 and current < int(target * 0.80):
                return 3
            return None

        if target >= 1100 and stat in {"speed", "wit"}:
            return 1 if gap >= 70 else 2
        if stat == "stamina" and target >= 700:
            if int(turn or 0) <= 56 and gap >= 90:
                return 1
            return 2 if gap >= 70 else 3
        if stat == "power" and target >= 900:
            return 1 if gap >= 150 else 2
        if gap >= 150:
            return 2
        if gap >= 80:
            return 3
        return None

    def _deck_type_count_for_item(self, name, preset):
        type_idx = TRAINING_ITEM_DECK_TYPE_INDEX.get(name)
        if type_idx is None:
            return 0
        counts = (preset or {}).get("_deck_type_counts") or []
        return int(counts[type_idx] or 0) if len(counts) > type_idx else 0

    def _summer_anklet_stock_target(self, name, preset):
        if name not in TRAINING_TYPE_ANKLET.values():
            return 0
        deck_count = self._deck_type_count_for_item(name, preset)
        if deck_count >= 2:
            return int(self._mant_cfg(preset).get("summer_anklet_primary_target") or 3)
        if deck_count >= 1:
            return int(self._mant_cfg(preset).get("summer_anklet_secondary_target") or 2)
        return 0

    def _energy_targets(self, chara, owned, preset, best_command=None):
        result = []
        hp = int(chara.get("vital") or 0)
        max_hp = int(chara.get("max_vital") or 100)
        motivation = int(chara.get("motivation") or 3)
        gap = max_hp - hp
        if gap < 20:
            return result
        cfg = self._mant_cfg(preset)
        threshold = int(cfg.get("energy_recovery_threshold") or 30)
        turn = int(chara.get("turn") or 0)
        is_training_command = bool(best_command and int(best_command.get("command_type") or 0) == 1)
        if is_training_command and self._summer_item_policy_enabled(preset):
            if self._is_summer_training_turn(turn):
                threshold = max(threshold, int(cfg.get("summer_energy_recovery_threshold") or threshold))
            elif self._is_summer_energy_prep_turn(turn, preset):
                threshold = max(threshold, int(cfg.get("summer_energy_entry_threshold") or threshold))
            elif self._is_summer_reserve_turn(turn, preset):
                threshold = min(threshold, int(cfg.get("summer_energy_reserve_critical_threshold") or threshold))
        if is_training_command and self._is_race_heavy_route(preset):
            threshold = max(threshold, int(cfg.get("race_heavy_energy_recovery_threshold") or threshold))
        learned_urgency = max(
            [self._learned_item_timing_adjustment(name, turn, preset) for name in ENERGY_ITEMS]
            or [0]
        )
        if learned_urgency > 0:
            threshold = min(max_hp, threshold + (learned_urgency * 4))
        if hp > threshold:
            return result

        candidates = []
        for name, value in ENERGY_ITEMS.items():
            qty = owned.get(name, 0)
            if qty > 0:
                if name == "Royal Kale Juice":
                    has_cupcake = any(owned.get(cupcake, 0) > 0 for cupcake in CUPCAKE_ITEMS)
                    if motivation < 4:
                        continue
                    if motivation == 4 and not has_cupcake:
                        continue
                candidates.append({"name": name, "value": value, "qty": qty})

        candidates.sort(key=lambda x: x["value"], reverse=True)

        remaining_gap = gap
        for c in candidates:
            if remaining_gap <= 5: break
            num_to_use = min(c["qty"], (remaining_gap + 5) // c["value"])
            if num_to_use > 0:
                result.append((c["name"], num_to_use))
                remaining_gap -= num_to_use * c["value"]

        return result

    def _royal_kale_pair_target(self, chara, owned, energy_targets):
        if not any(name == "Royal Kale Juice" for name, _ in energy_targets or []):
            return None
        motivation = int((chara or {}).get("motivation") or 3)
        if motivation < 4:
            return None
        for name in CUPCAKE_ITEMS:
            if owned.get(name, 0) > 0:
                return (name, 1)
        return None

    def _mood_target(self, chara, owned):
        motivation = int(chara.get("motivation") or 3)
        if motivation >= 5:
            return None

        needed = 5 - motivation

        if owned.get("Berry Sweet Cupcake", 0) > 0:
            return ("Berry Sweet Cupcake", 1)

        if owned.get("Plain Cupcake", 0) > 0:
            use_num = min(owned.get("Plain Cupcake"), needed)
            return ("Plain Cupcake", use_num)

        return None

    def _whistle_target(self, best_command, owned, preset, status, turn):
        if owned.get("Reset Whistle", 0) <= 0:
            return None
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None

        score = self._command_stat_gain(best_command)
        cfg = self._mant_cfg(preset)
        threshold = int(cfg.get("whistle_score_threshold") or 35)
        if score < threshold and turn <= 72:
             return ("Reset Whistle", 1)
        return None

    def _charm_target(self, best_command, owned, preset, status):
        cfg = self._mant_cfg(preset)
        if not bool(cfg.get("enable_good_luck_charm", False)):
            return None
        if owned.get("Good-Luck Charm", 0) <= 0:
            return None
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None
        fail_rate = int(best_command.get("failure_rate") or 0)
        threshold = int(cfg.get("charm_failure_rate") or 15)
        if fail_rate >= threshold:
            return ("Good-Luck Charm", 1)
        return None

    def _megaphone_target(self, state, best_command, owned, preset, status, turn, race_planner):
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None

        data = state.get("data") or {}
        free_data = data.get("free_data_set") or {}
        item_effects = free_data.get("item_effect_array") or []
        current_mega_tier = self._active_megaphone_tier(state)

        score = self._command_stat_gain(best_command, sp_weight=0.5)
        cfg = self._mant_cfg(preset)
        small_threshold = float(cfg.get("mega_small_threshold") or 11)
        medium_threshold = float(cfg.get("mega_medium_threshold") or 21)
        large_threshold = float(cfg.get("mega_large_threshold") or 35)
        empowering_available = max(
            0,
            int(owned.get(SUMMER_POWER_MEGAPHONE) or 0)
            - self._reserved_summer_empowering_megaphones(owned, preset, turn),
        )
        if self._summer_item_policy_enabled(preset):
            if self._is_summer_reserve_turn(turn, preset):
                break_glass = float(cfg.get("summer_reserve_break_glass_score") or 85)
                if score < break_glass:
                    return None
            elif self._is_summer_training_turn(turn):
                small_threshold = float(cfg.get("summer_mega_small_threshold") or small_threshold)
                medium_threshold = float(cfg.get("summer_mega_medium_threshold") or medium_threshold)
                large_threshold = float(cfg.get("summer_mega_large_threshold") or large_threshold)
        dump_mode = self._megaphone_dump_mode(data, owned, turn, race_planner, preset)
        slots_left = self._remaining_megaphone_slots(data, turn, race_planner, preset)
        owned_count = self._owned_megaphone_count(owned)
        inventory_pressure = slots_left > 0 and owned_count >= slots_left
        has_upgrade_pair = owned.get("Motivating Megaphone", 0) > 0 and empowering_available > 0 and slots_left >= 2

        target_tier = 0
        if current_mega_tier <= 0:
            if has_upgrade_pair and score >= medium_threshold:
                return ("Motivating Megaphone", 1)
            if score >= large_threshold and empowering_available > 0:
                return (SUMMER_POWER_MEGAPHONE, 1)
            if score >= medium_threshold and owned.get("Motivating Megaphone", 0) > 0:
                return ("Motivating Megaphone", 1)
            if score >= small_threshold and owned.get("Coaching Megaphone", 0) > 0:
                return ("Coaching Megaphone", 1)
            if inventory_pressure or dump_mode:
                if has_upgrade_pair:
                    return ("Motivating Megaphone", 1)
                if empowering_available > 0:
                    return (SUMMER_POWER_MEGAPHONE, 1)
                if score >= medium_threshold and owned.get("Motivating Megaphone", 0) > 0:
                    return ("Motivating Megaphone", 1)
                if score >= small_threshold and owned.get("Coaching Megaphone", 0) > 0:
                    return ("Coaching Megaphone", 1)
                if owned.get("Coaching Megaphone", 0) > 0:
                    return ("Coaching Megaphone", 1)
                if owned.get("Motivating Megaphone", 0) > 0:
                    return ("Motivating Megaphone", 1)
                if empowering_available > 0:
                    return (SUMMER_POWER_MEGAPHONE, 1)
            elif self._summer_item_policy_enabled(preset) and self._is_summer_training_turn(turn) and self._summer_turns_left(turn) <= 2:
                if empowering_available > 0 and score >= medium_threshold:
                    return (SUMMER_POWER_MEGAPHONE, 1)
                if owned.get("Motivating Megaphone", 0) > 0 and score >= small_threshold:
                    return ("Motivating Megaphone", 1)
                if owned.get("Coaching Megaphone", 0) > 0 and score >= small_threshold:
                    return ("Coaching Megaphone", 1)
            else:
                if score >= large_threshold:
                    target_tier = 3
                elif score >= medium_threshold:
                    target_tier = 2
                elif score >= small_threshold:
                    target_tier = 1
        elif current_mega_tier == 1:
            if score >= large_threshold * 1.2:
                target_tier = 3
            elif score >= medium_threshold * 1.1:
                target_tier = 2
        elif current_mega_tier == 2:
            if score >= large_threshold * 1.1:
                target_tier = 3

        if target_tier >= 3 and current_mega_tier < 3 and empowering_available > 0:
            return (SUMMER_POWER_MEGAPHONE, 1)
        if target_tier >= 2 and current_mega_tier < 2 and owned.get("Motivating Megaphone", 0) > 0:
            return ("Motivating Megaphone", 1)
        if target_tier >= 1 and current_mega_tier < 1 and owned.get("Coaching Megaphone", 0) > 0:
            return ("Coaching Megaphone", 1)

        return None

    def _megaphone_dump_mode(self, data, owned, turn, race_planner, preset):
        training_turns_left = self._remaining_megaphone_slots(data, turn, race_planner, preset)
        total_duration = 0
        for name, (_, duration) in MEGAPHONE_TIERS.items():
            total_duration += int(owned.get(name, 0) or 0) * duration
        return training_turns_left > 0 and total_duration >= training_turns_left

    def _owned_megaphone_count(self, owned):
        total = 0
        for name in MEGAPHONE_TIERS:
            total += int(owned.get(name, 0) or 0)
        return total

    def _megaphone_buy_surplus(self, data, owned, turn, race_planner, preset):
        slots_left = self._remaining_megaphone_slots(data, turn, race_planner, preset)
        if slots_left <= 0:
            return False
        cfg = self._mant_cfg(preset)
        buffer = int(cfg.get("mega_late_buy_buffer") or 3)
        target = max(0, slots_left - buffer)
        return self._owned_megaphone_count(owned) >= target

    def _remaining_megaphone_slots(self, data, turn, race_planner, preset):
        return self._remaining_training_turns_to_77(data, turn, race_planner, preset)

    def _remaining_training_turns_to_77(self, data, turn, race_planner, preset):
        planned_race_turns = self._planned_race_turns_to_77(data, turn, race_planner, preset)
        race_condition_array = data.get("race_condition_array") or []
        remaining = 0
        for t in range(int(turn or 0), 77):
            if t in (74, 76):
                continue
            if t not in planned_race_turns:
                remaining += 1
        return remaining

    def _planned_race_turns_to_77(self, data, turn, race_planner, preset):
        current_turn = int(turn or 0)
        wanted_pids = set()
        if race_planner and preset:
            wanted_pids = race_planner.wanted_programs(preset)
        result = set()
        for item in data.get("race_condition_array") or []:
            item_turn = int(item.get("turn") or 0)
            program_id = int(item.get("program_id") or 0)
            if item_turn >= current_turn and item_turn < 77 and (not wanted_pids or program_id in wanted_pids):
                result.add(item_turn)
        if race_planner and wanted_pids:
            for program_id in wanted_pids:
                info = (race_planner.program or {}).get(int(program_id or 0)) or {}
                race_turn = self._program_turn_from_month_half(info, current_turn)
                if race_turn >= current_turn and race_turn < 77:
                    result.add(race_turn)
        return result

    def _program_turn_from_month_half(self, program_info, current_turn):
        month = int((program_info or {}).get("month") or 0)
        half = int((program_info or {}).get("half") or 0)
        if month <= 0 or half <= 0:
            return 0
        base_turn = (month - 1) * 2 + half
        candidates = [base_turn + 24 * year for year in range(4)]
        for candidate in candidates:
            if candidate >= int(current_turn or 0):
                return candidate
        return candidates[-1]

    def _anklet_target(self, state, best_command, owned, preset):
        if not best_command or int(best_command.get("command_type") or 0) != 1:
            return None

        cmd_id = int(best_command.get("command_id") or 0)
        anklet = TRAINING_TYPE_ANKLET.get(cmd_id)
        if not anklet or owned.get(anklet, 0) <= 0:
            return None

        data = state.get("data") or {}
        free_data = data.get("free_data_set") or {}
        item_effects = free_data.get("item_effect_array") or []
        turn = int((data.get("chara_info") or {}).get("turn") or 0)
        for eff in item_effects:
            if eff.get("item_id") in (9001, 9002, 9003, 9004, 9005):
                return None

        score = self._command_stat_gain(best_command, sp_weight=0.5)
        cfg = self._mant_cfg(preset)
        if self._summer_item_policy_enabled(preset) and self._is_summer_reserve_turn(turn, preset):
            break_glass = float(cfg.get("summer_reserve_break_glass_score") or 85)
            if score < break_glass:
                return None
        base_threshold = 30
        if self._summer_item_policy_enabled(preset) and self._is_summer_training_turn(turn):
            base_threshold = float(cfg.get("summer_anklet_threshold") or base_threshold)
        threshold = base_threshold * (1 - (0.2 * self._active_megaphone_tier(state)))
        if score > threshold:
            return (anklet, 1)
        return None

    def _active_megaphone_tier(self, state):
        current_mega_tier = 0
        for eff in ((state.get("data") or {}).get("free_data_set") or {}).get("item_effect_array") or []:
            item_id = eff.get("item_id")
            if item_id == 8001: current_mega_tier = max(current_mega_tier, 1)
            elif item_id == 8002: current_mega_tier = max(current_mega_tier, 2)
            elif item_id == 8003: current_mega_tier = max(current_mega_tier, 3)
        return current_mega_tier

    def _command_stat_gain(self, cmd, sp_weight=0):
        if not cmd: return 0
        total = 0
        for item in cmd.get("params_inc_dec_info_array") or []:
            tt = item.get("target_type")
            if tt in [1, 2, 3, 4, 5]:
                total += int(item.get("value") or 0)
            elif (tt == 6 or tt == 30) and sp_weight > 0:
                total += int(item.get("value") or 0) * sp_weight
        if total == 0:
            for field in ["speed", "stamina", "power", "guts", "wiz"]:
                total += int(cmd.get(field) or 0)
            if sp_weight > 0:
                total += int(cmd.get("lp") or cmd.get("skill_point") or 0) * sp_weight
        return total

    def _merge_targets(self, targets, owned):
        counts = {}
        for name, count in targets:
            counts[name] = counts.get(name, 0) + count
        result = []
        for name, count in counts.items():
            actual = min(count, owned.get(name, 0))
            if actual > 0:
                result.append((name, actual))
        return result

    def _skip_buy(self, name, owned, preset=None, turn=0, budget=0, data=None, race_planner=None):
        if name in NEVER_BUY_ITEMS:
            return True
        if name == "Good-Luck Charm" and not bool(self._mant_cfg(preset).get("enable_good_luck_charm", False)):
            return True
        if self._server_inventory_cap_reached(name, owned):
            return True
        cap = BUY_CAPS.get(name)
        if cap is not None and int(owned.get(name) or 0) >= cap:
            return True
        target_stat_tier = self._target_stat_item_tier(name, preset, data or {}, turn)
        if self._learned_item_should_skip(name, turn, preset) and target_stat_tier is None:
            return True
        if name == "Pretty Mirror" and not self._should_buy_pretty_mirror(owned, preset, turn, data or {}):
            return True
        if name in MEGAPHONE_TIERS and self._megaphone_buy_surplus(data or {}, owned, turn, race_planner, preset):
            if not self._should_stock_summer_empowering_megaphone(name, owned, preset, turn):
                return True
        if name in CURE_ITEMS:
            if self._should_skip_cure_buy(name, owned, data or {}):
                return True
        if self._summer_item_policy_enabled(preset) and self._is_summer_reserve_turn(turn, preset) and name in TRAINING_TYPE_ANKLET.values():
            target = self._summer_anklet_stock_target(name, preset)
            if target > 0 and int(owned.get(name) or 0) >= target:
                return True
        type_idx = TRAINING_ITEM_DECK_TYPE_INDEX.get(name)
        if type_idx is not None:
            count = self._deck_type_count_for_item(name, preset)
            if count >= 1:
                return False
            return not ((turn >= 49 and budget >= 300) or (turn >= 65 and budget >= 150))
        if name in ONE_TIME_BUFF_ITEMS and name in self.used_buffs:
            return True
        return False

    def _learned_item_phase(self, turn):
        turn = int(turn or 0)
        if turn <= 24:
            return "early"
        if turn <= 48:
            return "mid"
        if turn <= 64:
            return "late"
        return "climax"

    def _learned_item_policy_row(self, name, preset=None):
        policy = ((preset or {}).get("item_learning_policy") or {})
        if not isinstance(policy, dict):
            return {}
        items = policy.get("items") or {}
        if not isinstance(items, dict):
            return {}
        return items.get(name) if isinstance(items.get(name), dict) else {}

    def _learned_item_phase_adjustment(self, name, turn, preset=None):
        row = self._learned_item_policy_row(name, preset)
        phase_adjustments = row.get("phase_adjustments") if isinstance(row, dict) else {}
        if not isinstance(phase_adjustments, dict):
            return 0
        phase = self._learned_item_phase(turn)
        try:
            return int(phase_adjustments.get(phase) or 0)
        except (TypeError, ValueError):
            return 0

    def _learned_item_timing_adjustment(self, name, turn, preset=None):
        row = self._learned_item_policy_row(name, preset)
        timing_adjustments = row.get("timing_adjustments") if isinstance(row, dict) else {}
        if not isinstance(timing_adjustments, dict):
            return 0
        phase = self._learned_item_phase(turn)
        try:
            return int(timing_adjustments.get(phase) or 0)
        except (TypeError, ValueError):
            return 0

    def _learned_item_should_skip(self, name, turn, preset=None):
        row = self._learned_item_policy_row(name, preset)
        if not isinstance(row, dict):
            return False
        stats = row.get("phase_stats") or {}
        phase_row = stats.get(self._learned_item_phase(turn)) if isinstance(stats, dict) else {}
        if not isinstance(phase_row, dict):
            return False
        if int(phase_row.get("count") or 0) < 4:
            return False
        if float(phase_row.get("unused_rate") or 0.0) < 0.85:
            return False
        if float(phase_row.get("fast_use_rate") or 0.0) >= 0.6 and float(phase_row.get("score_ratio") or 0.0) >= 1.0:
            return False
        return self._learned_item_phase_adjustment(name, turn, preset) >= 2

    def _should_skip_cure_buy(self, name, owned, data):
        if name == "Rich Hand Cream":
            return int(owned.get(name) or 0) >= 1
        if owned.get(name, 0) > 0:
            return True
        active_ailments = self._active_bad_statuses(data or {})
        if not active_ailments:
            return True
        if name == AILMENT_CURE_ALL:
            return False
        if owned.get(AILMENT_CURE_ALL, 0) > 0:
            return True
        return not any(AILMENT_CURE_MAP.get(ailment) == name for ailment in active_ailments)

    def _should_buy_pretty_mirror(self, owned, preset, turn, data):
        if int(owned.get("Pretty Mirror") or 0) >= 1 or "Pretty Mirror" in self.used_buffs:
            return False
        cfg = self._mant_cfg(preset)
        early_last_turn = int(cfg.get("pretty_mirror_early_shop_last_turn") or 28)
        if int(turn or 0) <= early_last_turn:
            return True
        threshold = int(cfg.get("pretty_mirror_late_low_bond_threshold") or 45)
        required_count = int(cfg.get("pretty_mirror_late_low_bond_count") or 3)
        low_count = 0
        for row in ((data or {}).get("chara_info") or {}).get("evaluation_info_array") or []:
            if int(row.get("target_id") or 0) not in {1, 2, 3, 4, 5, 6}:
                continue
            if int(row.get("evaluation") or 0) < threshold:
                low_count += 1
        return low_count >= required_count
