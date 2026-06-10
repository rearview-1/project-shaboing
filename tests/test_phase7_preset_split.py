import json
import tempfile
import unittest
from pathlib import Path

from career_bot.presets import PresetStore
from tools.split_legacy_preset import split_legacy_preset


class Phase7PresetSplitTests(unittest.TestCase):
    def _legacy_preset(self):
        return {
            "name": "xguri parent",
            "scenario_id": 4,
            "preset_family": "xguri",
            "extra_race_list": [101, 102],
            "learn_skill_list": [["Focus"]],
            "desired_parent_sparks": {"blue": ["Power"]},
            "_run_context": {"deck_quality_bucket": 2},
            "_loop_mode": True,
            "training_policy_model": {
                "enabled": True,
                "feature_weights": {"weighted_gain": 0.12},
            },
            "training_policy_validation": {"decision": "challenger_promoted"},
        }

    def test_migration_writes_layers_and_loader_reconstructs_merged_view(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "project"
            preset_dir = base / "data" / "presets"
            preset_dir.mkdir(parents=True)
            legacy = preset_dir / "xguri parent.json"
            legacy.write_text(json.dumps(self._legacy_preset()), encoding="utf-8")

            result = split_legacy_preset(legacy, base_dir=base, account_id="account_a", archive=True)
            store = PresetStore(base)
            merged = store.load_active_preset("account_a", "xguri parent")
            config = json.loads(Path(result["config_path"]).read_text(encoding="utf-8"))

            self.assertEqual(merged["extra_race_list"], [101, 102])
            self.assertEqual(merged["_run_context"]["deck_quality_bucket"], 2)
            self.assertTrue(merged["training_policy_model"]["enabled"])
            self.assertNotIn("_run_context", config)
            self.assertNotIn("training_policy_model", config)
            self.assertTrue(Path(result["archive_path"]).exists())

    def test_same_family_new_preset_inherits_policy_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "project"
            preset_dir = base / "data" / "presets"
            preset_dir.mkdir(parents=True)
            legacy = preset_dir / "xguri parent.json"
            legacy.write_text(json.dumps(self._legacy_preset()), encoding="utf-8")
            split_legacy_preset(legacy, base_dir=base, account_id="account_a")

            store = PresetStore(base)
            store.save_user_config("xguri parent v2", {
                "name": "xguri parent v2",
                "preset_family": "xguri",
                "scenario_id": 4,
            })
            inherited = store.load_active_preset("account_a", "xguri parent v2")

            self.assertEqual(inherited["training_policy_model"]["feature_weights"]["weighted_gain"], 0.12)

    def test_different_family_starts_without_shared_policy_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "project"
            preset_dir = base / "data" / "presets"
            preset_dir.mkdir(parents=True)
            legacy = preset_dir / "xguri parent.json"
            legacy.write_text(json.dumps(self._legacy_preset()), encoding="utf-8")
            split_legacy_preset(legacy, base_dir=base, account_id="account_a")

            store = PresetStore(base)
            store.save_user_config("compat sprint", {
                "name": "compat sprint",
                "preset_family": "compat_sprint",
                "scenario_id": 4,
            })
            clean = store.load_active_preset("account_a", "compat sprint")

            self.assertEqual(clean.get("training_policy_model") or {}, {})

    def test_split_config_write_filters_runtime_and_policy_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "project"
            store = PresetStore(base)
            store.save_user_config("xguri parent", self._legacy_preset())

            merged = store.load_active_preset("account_a", "xguri parent")
            merged["_run_context"] = {"deck_quality_bucket": 3}
            merged["training_policy_model"] = {"enabled": True, "feature_weights": {"weighted_gain": 0.20}}
            merged["extra_race_list"] = [999]
            store.write(merged)
            config = json.loads(store.config_path("xguri parent").read_text(encoding="utf-8"))

            self.assertEqual(config["extra_race_list"], [999])
            self.assertNotIn("_run_context", config)
            self.assertNotIn("training_policy_model", config)

    def test_instance_override_layer_wins_for_account_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "project"
            preset_dir = base / "data" / "presets"
            preset_dir.mkdir(parents=True)
            legacy = preset_dir / "xguri parent.json"
            legacy.write_text(json.dumps(self._legacy_preset()), encoding="utf-8")
            split_legacy_preset(legacy, base_dir=base, account_id="account_a")

            override = dict(self._legacy_preset())
            override["training_policy_model"] = {
                "enabled": True,
                "feature_weights": {"weighted_gain": 0.33},
            }
            override_path = Path(tmp) / "override.json"
            override_path.write_text(json.dumps(override), encoding="utf-8")
            split_legacy_preset(override_path, base_dir=base, account_id="account_b", instance_override=True)

            store = PresetStore(base)
            account_a = store.load_active_preset("account_a", "xguri parent")
            account_b = store.load_active_preset("account_b", "xguri parent")

            self.assertEqual(account_a["training_policy_model"]["feature_weights"]["weighted_gain"], 0.12)
            self.assertEqual(account_b["training_policy_model"]["feature_weights"]["weighted_gain"], 0.33)

    def test_instance_override_cannot_clobber_desired_parent_sparks(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / "project"
            preset_dir = base / "data" / "presets"
            preset_dir.mkdir(parents=True)
            legacy = preset_dir / "xguri parent.json"
            legacy.write_text(json.dumps(self._legacy_preset()), encoding="utf-8")
            split_legacy_preset(legacy, base_dir=base, account_id="account_a")

            override = dict(self._legacy_preset())
            override["desired_parent_sparks"] = {"blue": [], "pink": [], "green": [], "white": []}
            override_path = Path(tmp) / "override.json"
            override_path.write_text(json.dumps(override), encoding="utf-8")
            split_legacy_preset(override_path, base_dir=base, account_id="account_b", instance_override=True)

            store = PresetStore(base)
            account_b = store.load_active_preset("account_b", "xguri parent")
            override_layer = json.loads(store.policy_overrides_path("account_b", "xguri").read_text(encoding="utf-8"))

            self.assertEqual(account_b["desired_parent_sparks"]["blue"], ["Power"])
            self.assertNotIn("desired_parent_sparks", override_layer)


if __name__ == "__main__":
    unittest.main()
