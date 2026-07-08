import json
import os
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from career_bot.auto_learning import _apply_scope, run_auto_learning
from career_bot.learning import (
    DECK_AWARE_TOP_SCORE_FLOORS,
    LearnedPresetInvariantError,
    _attach_learning_metadata_to_samples,
    _instance_local_learning_scope_enabled,
    _is_behavior_learning_sample,
    _is_manual_sample,
    _preserve_operator_owned_fields,
    _shadow_challenger_update,
    apply_recency_weights,
    aggregate_future_turn_effects,
    auto_learning_recency_config,
    assert_learned_preset_invariants,
    build_postmortem_feedback_refresh,
    compute_empirical_score_floors,
    extract_actions_from_turns,
    extract_support_actions_from_turns,
    first_summer_friendship_diagnostic,
    is_full_career_sample,
    learn_item_policy,
    learn_expect_attribute_profiles,
    learn_race_style_overrides,
    learn_run_mode_policy,
    learning_rate_scale,
    load_deviation_signals,
    monotonic_apply_gate,
    recent_validation_samples,
    race_entries_from_turns,
    resolve_runtime_learning_pools,
    runtime_roots,
    save_learning_outputs,
    sample_signature,
    select_context_adaptive_samples,
    select_context_validation_samples,
    select_reference_groups,
    selected_training_action,
    split_action_classifier_groups,
    split_reference_groups,
    tune_deviation_bias,
    tune_base_score,
    tune_expect_attribute,
    tune_optional_race_policy,
    tune_stat_value_multiplier,
)
from career_bot.presets import (
    EXPECT_ATTRIBUTE_DEFAULT,
    PresetStore,
    expect_attribute_profile_lookup_keys,
    normalize_preset,
    resolve_expect_attribute,
)


def sample(source, score, status="finished", final_turn=78, action_count=30, race_total=25, losses=0, g1_losses=0, per_action_gain=1.0, deck_quality_bucket=None):
    s = {
        "source": source,
        "score": score,
        "status": status,
        "final_turn": final_turn,
        "turn_count": final_turn,
        "has_turn_data": True,
        "first_turn": 1 if final_turn >= 78 else max(1, final_turn - 10),
        "has_turn_one": final_turn >= 78,
        "has_turn_78": final_turn >= 78,
        "full_career_capture": final_turn >= 78 and status in {"finished", "rolled_over", "complete", "completed"},
        "actions": [
            {"idx": 0, "turn": idx + 1, "weighted_gain": per_action_gain}
            for idx in range(action_count)
        ],
        "race_quality": {
            "race_total": race_total,
            "race_losses": losses,
            "g1_losses": g1_losses,
            "g2_wins": 2,
            "g3_wins": 2,
            "affinity_overlap_wins": 4,
            "epithet_sets_completed": 1,
        },
    }
    if deck_quality_bucket is not None:
        s["deck_quality_bucket"] = deck_quality_bucket
    return s


class DeckAwareScoreFloorTests(unittest.TestCase):
    """Per-deck-bucket score floors."""

    def test_empirical_parent_library_floors_use_median_minus_ten_percent(self):
        rows = [
            {"source": "bot_parent_library", "score": 18000, "deck_quality_bucket": 2},
            {"source": "user_parent_library", "score": 20000, "deck_quality_bucket": 2},
            {"source": "bot_parent_library", "rank_score": 24000, "deck_quality_bucket": 3},
            {"source": "bot", "score": 30000, "deck_quality_bucket": 2},
            {"source": "bot_parent_library", "score": 12000, "deck_quality_bucket": 1},
        ]

        floors, diagnostic = compute_empirical_score_floors(rows)

        self.assertEqual(floors[2], 17500)
        self.assertEqual(floors[3], 21600)
        self.assertNotIn(1, floors)
        self.assertEqual(diagnostic["3"]["sample_count"], 1)


class RuntimeLearningPoolTests(unittest.TestCase):
    def test_instance_local_pool_prefers_primary_runtime_when_enough_local_samples(self):
        primary = str(Path("C:/tmp/account_a").resolve())
        shared = str(Path("C:/tmp/account_b").resolve())
        rows = [
            {"path": "a1.json", "runtime_root": primary, "actions": [{}] * 12},
            {"path": "a2.json", "runtime_root": primary, "actions": [{}] * 12},
            {"path": "a3.json", "runtime_root": primary, "actions": [{}] * 12},
            {"path": "b1.json", "runtime_root": shared, "actions": [{}] * 12},
        ]

        pools = resolve_runtime_learning_pools(
            rows,
            primary,
            instance_local=True,
            min_local_samples=3,
        )

        self.assertEqual(pools["mode"], "instance_local")
        self.assertEqual(pools["local_sample_count"], 3)
        self.assertEqual(len(pools["behavior_samples"]), 3)
        self.assertEqual({row["path"] for row in pools["behavior_samples"]}, {"a1.json", "a2.json", "a3.json"})

    def test_instance_local_pool_keeps_shared_manual_behavior(self):
        primary = str(Path("C:/tmp/account_a").resolve())
        shared = str(Path("C:/tmp/shared_runtime").resolve())
        rows = [
            {**sample("bot", 12000), "path": "a1.json", "runtime_root": primary},
            {**sample("bot", 12100), "path": "a2.json", "runtime_root": primary},
            {**sample("bot", 12200), "path": "a3.json", "runtime_root": primary},
            {**sample("manual_hachimi", 18194), "path": "manual.json", "runtime_root": shared},
        ]

        pools = resolve_runtime_learning_pools(
            rows,
            primary,
            instance_local=True,
            min_local_samples=3,
        )

        self.assertEqual(pools["mode"], "instance_local")
        self.assertEqual(pools["local_sample_count"], 3)
        self.assertEqual(pools["manual_behavior_sample_count"], 1)
        self.assertEqual({row["path"] for row in pools["behavior_samples"]}, {"a1.json", "a2.json", "a3.json", "manual.json"})

    def test_instance_local_pool_falls_back_to_shared_when_local_samples_are_thin(self):
        primary = str(Path("C:/tmp/account_a").resolve())
        shared = str(Path("C:/tmp/account_b").resolve())
        rows = [
            {"path": "a1.json", "runtime_root": primary, "actions": [{}] * 12},
            {"path": "b1.json", "runtime_root": shared, "actions": [{}] * 12},
            {"path": "b2.json", "runtime_root": shared, "actions": [{}] * 12},
        ]

        pools = resolve_runtime_learning_pools(
            rows,
            primary,
            instance_local=True,
            min_local_samples=3,
        )

        self.assertEqual(pools["mode"], "shared_fallback")
        self.assertEqual(pools["local_sample_count"], 1)
        self.assertEqual(len(pools["behavior_samples"]), 3)

    def test_legacy_absolute_floor_still_filters(self):
        """When only the legacy single floor is passed, behavior is
        unchanged: samples below it can't enter top."""
        rows = [
            sample("a", 18000),
            sample("b", 17000),
            sample("c", 12000),  # below 17500 floor — filtered
            sample("d", 11000),
            sample("e", 9000),
            sample("f", 8000),
        ]
        top, _ = split_reference_groups(rows, score_floor=17500)
        scores = [s["score"] for s in top]
        self.assertTrue(all(s >= 17500 for s in scores))


    def test_default_deck_aware_floor_no_longer_relaxes_sr_only_pool(self):
        """SR-heavy decks should no longer get a softer definition of
        top samples than mixed decks. The default map keeps the premium
        SSR bucket stricter, but SR-heavy samples still need to clear
        the standard 17,500 parent-farming bar."""
        rows = [
            sample("sr_a", 13000, deck_quality_bucket=1),
            sample("sr_b", 12500, deck_quality_bucket=1),
            sample("sr_c", 12000, deck_quality_bucket=1),
            sample("sr_d", 11500, deck_quality_bucket=1),
            sample("sr_e", 9500, deck_quality_bucket=1),
            sample("sr_f", 9000, deck_quality_bucket=1),
            sample("sr_g", 8500, deck_quality_bucket=1),
            sample("sr_h", 8000, deck_quality_bucket=1),
        ]
        top, _ = split_reference_groups(rows, score_floors_by_deck=DECK_AWARE_TOP_SCORE_FLOORS)
        self.assertEqual(top, [], "default SR deck floor should no longer admit sub-17500 samples")

    def test_deck_aware_floor_still_rejects_below_bucket(self):
        """Samples below their OWN deck bucket's floor are still
        rejected — the deck-aware floor only relaxes the bar for
        lower-deck samples, it doesn't disable filtering entirely."""
        rows = [
            sample("sr_top", 13000, deck_quality_bucket=1),
            sample("sr_top2", 12500, deck_quality_bucket=1),
            sample("sr_mid", 11000, deck_quality_bucket=1),
            sample("sr_low", 10500, deck_quality_bucket=1),
            sample("sr_bad", 5000, deck_quality_bucket=1),  # below 10k SR floor
            sample("sr_bad2", 4000, deck_quality_bucket=1),
        ]
        floors_by_deck = {3: 22000, 2: 17500, 1: 10000, 0: 6500}
        top, _ = split_reference_groups(rows, score_floors_by_deck=floors_by_deck)
        sources = {s["source"] for s in top}
        self.assertNotIn("sr_bad", sources)
        self.assertNotIn("sr_bad2", sources)

    def test_unknown_deck_bucket_falls_back_to_mixed_bucket(self):
        """Samples without a `deck_quality_bucket` field (older sample
        format) default to bucket 2 (mixed) — matches the runtime
        default in compute_deck_quality_bucket."""
        rows = [
            sample("legacy", 18000),  # no deck_quality_bucket set
            sample("ssr", 22000, deck_quality_bucket=3),
            sample("sr", 11000, deck_quality_bucket=1),
        ]
        floors_by_deck = {3: 22000, 2: 17500, 1: 10000, 0: 6500}
        top, _ = split_reference_groups(rows, score_floors_by_deck=floors_by_deck)
        sources = {s["source"] for s in top}
        # legacy 18,000 should qualify under mixed (bucket 2) floor 17,500.
        self.assertIn("legacy", sources)

    def test_high_white_intent_requires_rank_score_threshold_for_top_parent_samples(self):
        def parent_sample(source, score, rank_score):
            row = sample(source, score, deck_quality_bucket=2)
            row["source"] = f"bot_parent_library::{source}"
            row["rank_score"] = rank_score
            row["learning_metadata"] = {
                "session": {
                    "primary_stat_target": {"stat": "power"},
                    "blue_spark_intent": {"preferred_color": "power"},
                    "white_spark_intent": {"target_rank_score_band": "high"},
                },
                "deck_quality_bucket": 2,
            }
            return row

        rows = [
            parent_sample("low_rank_but_factor_rich", 52000, 16000),
            parent_sample("high_rank_target_hit", 51000, 18000),
            parent_sample("mid_a", 32000, 15000),
            parent_sample("mid_b", 30000, 14900),
            parent_sample("mid_c", 28000, 14800),
            parent_sample("mid_d", 26000, 14700),
            parent_sample("low_a", 24000, 14600),
            parent_sample("low_b", 22000, 14500),
        ]

        top, _ = split_reference_groups(rows, score_floor=17500)
        sources = {s["source"] for s in top}

        self.assertIn("bot_parent_library::high_rank_target_hit", sources)
        self.assertNotIn("bot_parent_library::low_rank_but_factor_rich", sources)


class TurnActionExtractionTests(unittest.TestCase):
    def test_selected_training_action_preserves_decision_understanding(self):
        turn = {
            "turn": 12,
            "selected_action": "command",
            "decision_reason": "training Speed 101",
            "decision_understanding": {
                "summary": "push speed toward the blue spark band",
                "signals": {"blue_target_match": True},
            },
            "current_command": {"command_id": 101},
            "stats": {"hp": 72, "skill_point": 40},
            "training_snapshot": {
                "trainings": [
                    {
                        "command_id": 101,
                        "name": "Speed",
                        "failure_rate": 0,
                        "stat_gain": {"speed": 18},
                        "weighted_total_gain": 18,
                        "partners": [],
                    }
                ]
            },
        }

        action = selected_training_action(turn)

        self.assertIsNotNone(action)
        self.assertEqual(
            ((action or {}).get("decision_understanding") or {}).get("summary"),
            "push speed toward the blue spark band",
        )

    def test_support_action_extraction_maps_command_types_to_rest_recreation_and_medic(self):
        turns = [
            {"turn": 5, "selected_action": "command", "current_action_taken": "command", "current_command": {"command_type": 7}, "stats": {"hp": 44}},
            {"turn": 6, "selected_action": "command", "current_action_taken": "command", "current_command": {"command_type": 3}, "stats": {"hp": 61}},
            {"turn": 7, "selected_action": "command", "current_action_taken": "command", "current_command": {"command_type": 8}, "stats": {"hp": 38}},
            {"turn": 8, "selected_action": "race", "current_action_taken": "race", "stats": {"hp": 72}},
        ]

        actions = extract_support_actions_from_turns(turns)

        self.assertEqual([row["kind"] for row in actions], ["rest", "recreation", "medic", "race"])


class LearningSafeguardsTests(unittest.TestCase):
    def test_is_full_career_sample_requires_turn_one_and_turn_seventy_eight_for_turn_data(self):
        full = {
            "source": "bot",
            "status": "finished",
            "final_turn": 78,
            "has_turn_data": True,
            "first_turn": 1,
            "has_turn_one": True,
            "has_turn_78": True,
            "full_career_capture": True,
        }
        interrupted = {
            "source": "bot",
            "status": "finished",
            "final_turn": 78,
            "has_turn_data": True,
            "first_turn": 12,
            "has_turn_one": False,
            "has_turn_78": True,
            "full_career_capture": False,
        }
        self.assertTrue(is_full_career_sample(full))
        self.assertTrue(is_full_career_sample(full, require_turn_data=True))
        self.assertFalse(is_full_career_sample(interrupted))
        self.assertFalse(is_full_career_sample(interrupted, require_turn_data=True))

    def test_is_full_career_sample_rejects_sparse_turn_one_to_seventy_eight_capture(self):
        sparse = {
            "source": "bot",
            "status": "finished",
            "final_turn": 78,
            "has_turn_data": True,
            "first_turn": 1,
            "has_turn_one": True,
            "has_turn_78": True,
            "observed_turn_count": 2,
            "full_career_capture": False,
        }
        self.assertFalse(is_full_career_sample(sparse))
        self.assertFalse(is_full_career_sample(sparse, require_turn_data=True))

    def test_postmortem_refresh_rebuilds_race_loss_hints_without_full_learning(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            PresetStore(base_dir).write({"name": "goal-test"})
            postmortem_dir = base_dir / "uma_runtime" / "postmortems"
            postmortem_dir.mkdir(parents=True, exist_ok=True)
            (postmortem_dir / "postmortem_20260517_000001.json").write_text(
                json.dumps(
                    {
                        "g1_losses": [
                            {
                                "program_id": 11017,
                                "race_name": "NHK Mile Cup",
                                "field_max_gap_over_player": {
                                    "speed": 40,
                                    "stamina": 10,
                                    "power": 180,
                                    "guts": 0,
                                    "wit": 0,
                                },
                            }
                        ],
                        "summary": {"count": 1},
                    }
                ),
                encoding="utf-8",
            )

            learned, report = build_postmortem_feedback_refresh(base_dir, "goal-test")

            self.assertIsNotNone(learned)
            self.assertEqual(report["hint_count"], 1)
            self.assertIn(11017, learned["race_specific_stat_hints"])
            self.assertEqual(
                learned["race_specific_stat_hints"][11017]["worst_stat"],
                "power",
            )
            self.assertEqual(
                (learned.get("learning_metadata") or {}).get("last_postmortem_refresh_reason"),
                "status_not_enabled",
            )

    def test_auto_learning_status_skip_still_applies_postmortem_refresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            preset = PresetStore(base_dir).write(
                {
                    "name": "goal-test",
                    "auto_learning_enabled": True,
                    "auto_learning_apply": True,
                    "auto_learning_statuses": ["finished"],
                }
            )
            postmortem_dir = base_dir / "uma_runtime" / "postmortems"
            postmortem_dir.mkdir(parents=True, exist_ok=True)
            (postmortem_dir / "postmortem_20260517_000002.json").write_text(
                json.dumps(
                    {
                        "g1_losses": [
                            {
                                "program_id": 30045,
                                "race_name": "Kikuka Sho",
                                "field_max_gap_over_player": {
                                    "speed": 0,
                                    "stamina": 220,
                                    "power": 40,
                                    "guts": 160,
                                    "wit": 0,
                                },
                            }
                        ],
                        "summary": {"count": 1},
                    }
                ),
                encoding="utf-8",
            )

            result = run_auto_learning(base_dir, preset, status="stopped")
            refreshed = PresetStore(base_dir).read_one("goal-test")

            self.assertFalse(result["success"])
            self.assertEqual(result["skipped"], "status_not_enabled")
            self.assertTrue((result.get("postmortem_refresh") or {}).get("applied"))
            self.assertIn("30045", refreshed.get("race_specific_stat_hints", {}))
            self.assertEqual(
                refreshed["race_specific_stat_hints"]["30045"]["worst_stat"],
                "stamina",
            )

    def test_auto_learning_passes_active_preset_override_into_learning_fit(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            preset = {
                "name": "goal-test",
                "auto_learning_enabled": True,
                "auto_learning_apply": False,
                "training_policy_model": {"enabled": True, "weights": {"speed": 0.12}},
                "training_policy_challenger": {"fingerprint": "abc123", "streak": 1},
            }
            learned = {"name": "goal-test learned", "training_policy_model": {"enabled": True}}
            report = {"source_preset": "goal-test", "learned_preset": "goal-test learned"}
            with patch("career_bot.auto_learning.learn_preset", return_value=(learned, report)) as learn_mock, patch(
                "career_bot.auto_learning.save_learning_outputs",
                return_value=(base_dir / "data" / "presets" / "goal-test.json", base_dir / "uma_runtime" / "learning" / "report.json"),
            ):
                result = run_auto_learning(base_dir, preset, status="finished")

            self.assertTrue(result["success"])
            self.assertEqual(learn_mock.call_args.kwargs["source_preset_override"], preset)

    def test_auto_learning_blocks_apply_when_monotonic_gate_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            preset = {
                "name": "goal-test",
                "auto_learning_enabled": True,
                "auto_learning_apply": True,
            }
            learned = {"name": "goal-test learned"}
            report = {
                "source_preset": "goal-test",
                "learned_preset": "goal-test learned",
                "monotonic_apply_gate": {
                    "enabled": True,
                    "allowed": False,
                    "reason": "latest bot run score did not clear baseline",
                },
            }
            with patch("career_bot.auto_learning.learn_preset", return_value=(learned, report)), patch(
                "career_bot.auto_learning.save_learning_report_only",
                return_value=base_dir / "uma_runtime" / "learning" / "report.json",
            ) as report_mock, patch("career_bot.auto_learning.save_learning_outputs") as save_mock, patch(
                "career_bot.auto_learning.save_instance_learning_outputs"
            ) as instance_save_mock:
                result = run_auto_learning(base_dir, preset, status="finished")

            self.assertFalse(result["success"])
            self.assertEqual(result["skipped"], "monotonic_apply_gate")
            self.assertFalse(result["applied"])
            report_mock.assert_called_once()
            save_mock.assert_not_called()
            instance_save_mock.assert_not_called()

    def test_auto_learning_applies_corrective_monotonic_gate(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            preset = {
                "name": "goal-test",
                "auto_learning_enabled": True,
                "auto_learning_apply": True,
            }
            learned = {"name": "goal-test learned"}
            report = {
                "source_preset": "goal-test",
                "learned_preset": "goal-test learned",
                "monotonic_apply_gate": {
                    "enabled": True,
                    "allowed": True,
                    "corrective_apply": True,
                    "baseline_preserved": True,
                    "reason": "corrective_apply_after_latest_regression",
                },
            }
            with patch("career_bot.auto_learning.learn_preset", return_value=(learned, report)), patch(
                "career_bot.auto_learning.save_learning_outputs",
                return_value=(base_dir / "data" / "presets" / "goal-test.json", base_dir / "uma_runtime" / "learning" / "report.json"),
            ) as save_mock, patch(
                "career_bot.auto_learning.save_learning_report_only"
            ) as report_mock:
                result = run_auto_learning(base_dir, preset, status="finished")

            self.assertTrue(result["success"])
            self.assertTrue(result["applied"])
            save_mock.assert_called_once()
            report_mock.assert_not_called()

    def test_runtime_roots_use_explicit_dual_roots_without_fallback_duplicates(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp) / "project"
            base_dir.mkdir()
            explicit_a = Path(tmp) / "runtime_a"
            explicit_b = Path(tmp) / "runtime_b"
            fallback = Path(tmp) / "uma_runtime"
            explicit_a.mkdir()
            explicit_b.mkdir()
            fallback.mkdir()

            with patch.dict(
                os.environ,
                {
                    "UMA_RUNTIME_DIR": str(explicit_b),
                    "SWEEPY_SHARED_RUNTIME_PATHS": f"{explicit_a}{os.pathsep}{explicit_b}",
                },
                clear=False,
            ):
                roots = runtime_roots(base_dir)

            self.assertEqual(roots, [explicit_b.resolve(), explicit_a.resolve()])
            self.assertNotIn(fallback.resolve(), roots)

    def test_dual_runtime_paths_do_not_force_instance_local_learning(self):
        with tempfile.TemporaryDirectory() as tmp:
            explicit_a = Path(tmp) / "runtime_a"
            explicit_b = Path(tmp) / "runtime_b"
            explicit_a.mkdir()
            explicit_b.mkdir()

            with patch.dict(
                os.environ,
                {
                    "UMA_RUNTIME_DIR": str(explicit_b),
                    "SWEEPY_INSTANCE_NAME": "account_b",
                    "SWEEPY_SHARED_RUNTIME_PATHS": f"{explicit_a}{os.pathsep}{explicit_b}",
                },
                clear=True,
            ):
                self.assertFalse(_instance_local_learning_scope_enabled())

    def test_instance_local_learning_still_requires_explicit_scope(self):
        with patch.dict(os.environ, {"SWEEPY_AUTO_LEARNING_SCOPE": "instance_local"}, clear=True):
            self.assertTrue(_instance_local_learning_scope_enabled())

    def test_auto_learning_apply_scope_defaults_shared_overlay_in_dual_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            explicit_a = Path(tmp) / "runtime_a"
            explicit_b = Path(tmp) / "runtime_b"
            explicit_a.mkdir()
            explicit_b.mkdir()

            with patch.dict(
                os.environ,
                {
                    "UMA_RUNTIME_DIR": str(explicit_b),
                    "SWEEPY_INSTANCE_NAME": "account_b",
                    "SWEEPY_SHARED_RUNTIME_PATHS": f"{explicit_a}{os.pathsep}{explicit_b}",
                },
                clear=True,
            ):
                self.assertEqual(_apply_scope({}), "shared_overlay")

    def test_preset_store_saved_copy_shadows_legacy_template_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            legacy_dir = base_dir / "data" / "presets"
            legacy_dir.mkdir(parents=True, exist_ok=True)
            (legacy_dir / "goal-test.json").write_text(
                json.dumps({"name": "goal-test", "rest_threshold": 48}),
                encoding="utf-8",
            )

            store = PresetStore(base_dir)
            store.write({"name": "goal-test", "rest_threshold": 72})
            loaded = store.read_one("goal-test")

            self.assertEqual(loaded["rest_threshold"], 72)
            self.assertTrue((legacy_dir / "goal-test.json").exists())
            self.assertTrue((legacy_dir / "saved" / "goal-test.json").exists())

    def test_save_learning_outputs_splits_learned_and_saved_preset_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            legacy_dir = base_dir / "data" / "presets"
            legacy_dir.mkdir(parents=True, exist_ok=True)
            (legacy_dir / "goal-test.json").write_text(
                json.dumps({"name": "goal-test", "rest_threshold": 48}),
                encoding="utf-8",
            )

            learned_path, _ = save_learning_outputs(
                base_dir,
                {"name": "goal-test learned", "rest_threshold": 64},
                {"source_preset": "goal-test", "learned_preset": "goal-test learned"},
                apply=False,
            )
            applied_path, _ = save_learning_outputs(
                base_dir,
                {"name": "goal-test learned", "rest_threshold": 72},
                {"source_preset": "goal-test", "learned_preset": "goal-test learned"},
                apply=True,
            )

            self.assertIn(str(Path("data") / "presets" / "learned"), str(learned_path))
            self.assertIn(str(Path("data") / "presets" / "saved"), str(applied_path))
            self.assertEqual(
                json.loads((legacy_dir / "goal-test.json").read_text(encoding="utf-8"))["rest_threshold"],
                48,
            )
            self.assertEqual(
                json.loads((legacy_dir / "saved" / "goal-test.json").read_text(encoding="utf-8"))["rest_threshold"],
                72,
            )

    def test_aggregate_future_turn_effects_learns_stable_race_and_event_relief(self):
        samples = []
        for _ in range(8):
            samples.append({
                "source": "bot",
                "status": "finished",
                "final_turn": 78,
                "has_turn_data": True,
                "first_turn": 1,
                "has_turn_one": True,
                "has_turn_78": True,
                "observed_turn_count": 78,
                "full_career_capture": True,
                "future_effect_curve": [
                    {
                        "turn": 71,
                        "next_turn": 72,
                        "kind": "training",
                        "delta": {"hp": 50, "speed": 0, "stamina": 0, "power": 0, "guts": 0, "wit": 0, "skill_point": 0},
                    },
                    {
                        "turn": 74,
                        "next_turn": 75,
                        "kind": "race",
                        "program_id": 2308,
                        "delta": {"hp": 0, "speed": 18, "stamina": 18, "power": 18, "guts": 18, "wit": 18, "skill_point": 58},
                    },
                ],
            })

        learned = aggregate_future_turn_effects(samples)

        self.assertEqual(learned["schema"], "sweepy_future_turn_effects_v1")
        self.assertEqual(learned["turns"]["71"]["effects"]["hp"], 50.0)
        self.assertEqual(learned["turns"]["74"]["effects"]["stamina"], 18.0)
        self.assertEqual(learned["turns"]["74"]["effects"]["skill_point"], 58.0)

    def test_metadata_fallback_uses_user_blue_target_from_sample_objective(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp)
            PresetStore(base_dir).write(
                {
                    "name": "goal-test",
                    "skill_profile_style": "late_surger",
                    "desired_parent_sparks": {
                        "blue": ["Power"],
                        "pink": [],
                        "green": [],
                        "white": ["NHK Mile C."],
                    },
                }
            )
            rows = [
                {
                    "source": "bot",
                    "preset_name": "goal-test",
                    "desired_parent_sparks": {
                        "blue": ["Wit"],
                        "pink": [],
                        "green": [],
                        "white": ["NHK Mile C."],
                    },
                    "score": 18250,
                    "sample_weight": 1.0,
                    "final_stats": {
                        "speed": 720,
                        "stamina": 640,
                        "power": 780,
                        "guts": 430,
                        "wit": 1132,
                    },
                    "final_sparks": [
                        {"type": "blue", "name": "wit", "star_level": 2},
                        {"type": "white", "name": "NHK Mile C.", "star_level": 2},
                    ],
                    "race_results": [],
                    "actions": [{"turn": 1, "weighted_gain": 1.0}],
                    "final_turn": 78,
                    "status": "finished",
                }
            ]

            _attach_learning_metadata_to_samples(base_dir, rows)

            session = rows[0]["learning_metadata"]["session"]
            self.assertEqual(session["primary_stat_target"]["stat"], "wit")
            self.assertEqual(session["blue_spark_intent"]["preferred_color"], "wit")
            self.assertEqual(session["white_spark_intent"]["target_rank_score_band"], "high")
            self.assertIn("NHK Mile C.", session["white_spark_intent"]["high_value_targets"])
            self.assertEqual(session["style_target"], "late_surger")

    def test_reference_groups_ignore_short_probe_like_finished_runs(self):
        rows = [
            sample("bad_probe", 99999, final_turn=20, action_count=1, race_total=1),
            sample("top_a", 18000),
            sample("top_b", 17000),
            sample("top_c", 16000),
            sample("top_d", 15000),
            sample("bottom_a", 9000, losses=3),
            sample("bottom_b", 8500, losses=3),
            sample("bottom_c", 8000, losses=4),
            sample("bottom_d", 7500, losses=4),
        ]
        for row in rows:
            row["has_turn_data"] = True
            row["first_turn"] = 1
            row["has_turn_one"] = True
            row["has_turn_78"] = row.get("final_turn", 0) >= 78
            row["full_career_capture"] = row.get("final_turn", 0) >= 78
        rows[0]["full_career_capture"] = False
        rows[0]["has_turn_78"] = False

        top, bottom = split_reference_groups(rows)

        self.assertTrue(top)
        self.assertTrue(bottom)
        self.assertNotIn("bad_probe", {row["source"] for row in top + bottom})

    def test_recent_validation_samples_prefers_newest_timestamped_rows(self):
        rows = [
            {"path": "older.json", "ended_at": "2026-05-10T12:00:00", "actions": [{}] * 12},
            {"path": "newer.json", "ended_at": "2026-05-15T12:00:00", "actions": [{}] * 12},
            {"path": "newest.json", "ended_at": "2026-05-16T12:00:00", "actions": [{}] * 12},
        ]

        picked = recent_validation_samples(rows, limit=2, min_actions=10)

        self.assertEqual([row["path"] for row in picked], ["newest.json", "newer.json"])

    def test_context_validation_samples_prefers_matching_trainee_deck_and_objective(self):
        anchor = {
            "path": "anchor.json",
            "ended_at": "2026-05-16T12:00:00",
            "actions": [{}] * 12,
            "preset_name": "xguri parent",
            "desired_parent_sparks": {"blue": ["Power"], "pink": [], "green": [], "white": []},
            "run_context": {
                "trainee_card_id": 106101,
                "support_cards": [
                    {"type": "Speed"},
                    {"type": "Speed"},
                    {"type": "Power"},
                    {"type": "Wit"},
                    {"type": "Wit"},
                ],
            },
            "learning_metadata": {
                "session": {
                    "session_id": "preset_parent_power_late_surger",
                    "primary_stat_target": {"stat": "power"},
                    "style_target": "late_surger",
                },
                "deck_quality_bucket": 2,
            },
        }
        matching = {
            "path": "matching.json",
            "ended_at": "2026-05-15T12:00:00",
            "actions": [{}] * 12,
            "preset_name": "xguri parent",
            "desired_parent_sparks": {"blue": ["Power"], "pink": [], "green": [], "white": []},
            "run_context": {
                "trainee_card_id": 106101,
                "support_cards": [
                    {"type": "Speed"},
                    {"type": "Speed"},
                    {"type": "Power"},
                    {"type": "Wit"},
                    {"type": "Wit"},
                ],
            },
            "learning_metadata": {
                "session": {
                    "session_id": "preset_parent_power_late_surger",
                    "primary_stat_target": {"stat": "power"},
                    "style_target": "late_surger",
                },
                "deck_quality_bucket": 2,
            },
        }
        unrelated_newer = {
            "path": "unrelated.json",
            "ended_at": "2026-05-17T12:00:00",
            "actions": [{}] * 12,
            "preset_name": "other",
            "desired_parent_sparks": {"blue": ["Wit"], "pink": [], "green": [], "white": []},
            "run_context": {
                "trainee_card_id": 999999,
                "support_cards": [
                    {"type": "Stamina"},
                    {"type": "Stamina"},
                    {"type": "Guts"},
                    {"type": "Pal"},
                    {"type": "Group"},
                ],
            },
            "learning_metadata": {
                "session": {
                    "session_id": "preset_parent_wit_front_runner",
                    "primary_stat_target": {"stat": "wit"},
                    "style_target": "front_runner",
                },
                "deck_quality_bucket": 1,
            },
        }

        picked = select_context_validation_samples(
            [matching, unrelated_newer],
            anchor,
            limit=2,
            min_actions=10,
            min_match_count=1,
        )

        self.assertEqual(picked["mode"], "contextual")
        self.assertEqual([row["path"] for row in picked["samples"]], ["matching.json"])
        self.assertGreaterEqual(picked["match_count"], 1)

    def test_context_adaptive_samples_use_low_count_similar_instead_of_global_pool(self):
        preset = {
            "name": "xguri parent",
            "skill_profile_style": "late_surger",
            "skill_profile_distance": "medium",
            "_run_context": {
                "preset_name": "xguri parent",
                "trainee_card_id": 101502,
                "friend_card_id": 30032,
                "deck_quality_bucket": 2,
                "support_cards": [
                    {"support_card_id": 20031, "type": "Speed", "lb_level": 4},
                    {"support_card_id": 30028, "type": "Speed", "lb_level": 4},
                    {"support_card_id": 30016, "type": "Stamina", "lb_level": 3},
                    {"support_card_id": 30007, "type": "Power", "lb_level": 4},
                    {"support_card_id": 20008, "type": "Stamina", "lb_level": 4},
                ],
            },
            "learning_context_min_exact_samples": 4,
            "learning_context_min_similar_samples": 8,
            "learning_context_soft_min_similar_samples": 3,
        }

        def similar_row(idx):
            return {
                "path": f"tm_similar_{idx}.json",
                "preset_name": "xguri parent",
                "actions": [{}] * 20,
                "run_context": {
                    "preset_name": "xguri parent",
                    "trainee_card_id": 101502,
                    "friend_card_id": 30032,
                    "deck_quality_bucket": 2,
                    "skill_profile_style": "late_surger",
                    "skill_profile_distance": "medium",
                    "support_cards": [
                        {"support_card_id": 20031, "type": "Speed", "lb_level": 4},
                        {"support_card_id": 30028, "type": "Speed", "lb_level": 4},
                        {"support_card_id": 30016, "type": "Stamina", "lb_level": 3},
                        {"support_card_id": 30007, "type": "Power", "lb_level": 4},
                        {"support_card_id": 20008, "type": "Stamina", "lb_level": 4},
                    ],
                },
            }

        unrelated = [
            {
                "path": f"manual_bakushin_{idx}.json",
                "preset_name": "xguri parent",
                "actions": [{}] * 20,
                "run_context": {
                    "preset_name": "xguri parent",
                    "trainee_card_id": 104101,
                    "friend_card_id": 30094,
                    "deck_quality_bucket": 3,
                    "skill_profile_style": "front_runner",
                    "skill_profile_distance": "sprint",
                    "support_cards": [
                        {"support_card_id": 30019, "type": "Speed", "lb_level": 4},
                        {"support_card_id": 20041, "type": "Wit", "lb_level": 4},
                        {"support_card_id": 30086, "type": "Wit", "lb_level": 4},
                    ],
                },
            }
            for idx in range(5)
        ]
        rows = [*unrelated, *(similar_row(idx) for idx in range(3))]

        selected = select_context_adaptive_samples(rows, preset=preset)

        self.assertEqual(selected["mode"], "similar_context_low_sample")
        self.assertEqual(selected["selected_count"], 3)
        self.assertEqual(
            {row["path"] for row in selected["samples"]},
            {"tm_similar_0.json", "tm_similar_1.json", "tm_similar_2.json"},
        )

    def test_context_adaptive_samples_keep_pool_when_no_strong_anchor_exists(self):
        rows = [
            {"path": "a.json", "actions": [{}], "run_context": {}},
            {"path": "b.json", "actions": [{}], "run_context": {}},
        ]

        selected = select_context_adaptive_samples(rows, preset={"name": "test"})

        self.assertEqual(selected["mode"], "no_context_anchor")
        self.assertEqual(selected["selected_count"], 2)
        self.assertEqual([row["path"] for row in selected["samples"]], ["a.json", "b.json"])

    def test_shadow_challenger_stages_then_promotes(self):
        preset = {
            "training_policy_challenger_enabled": True,
            "training_policy_challenger_promotion_passes": 2,
            "training_policy_challenger_min_margin": 0.01,
        }
        old_model = {"enabled": True, "feature_weights": {"weighted_gain": 0.1}}
        new_model = {"enabled": True, "feature_weights": {"weighted_gain": 0.2}}

        staged = _shadow_challenger_update(
            preset,
            old_model,
            new_model,
            0.80,
            0.84,
            0.78,
            0.81,
            0.99,
        )
        self.assertEqual(staged["decision"], "challenger_staged")
        self.assertEqual(staged["challenger"]["streak"], 1)

        preset["training_policy_challenger"] = staged["challenger"]
        promoted = _shadow_challenger_update(
            preset,
            old_model,
            new_model,
            0.80,
            0.84,
            0.78,
            0.81,
            0.99,
        )
        self.assertEqual(promoted["decision"], "challenger_promoted")
        self.assertEqual(promoted["active_model"], new_model)

    def test_shadow_challenger_keeps_streak_for_new_candidates_against_same_active_model(self):
        preset = {
            "training_policy_challenger_enabled": True,
            "training_policy_challenger_promotion_passes": 2,
            "training_policy_challenger_min_margin": 0.01,
        }
        old_model = {"enabled": True, "feature_weights": {"weighted_gain": 0.1}}
        first_model = {"enabled": True, "feature_weights": {"weighted_gain": 0.2}}
        second_model = {"enabled": True, "feature_weights": {"weighted_gain": 0.21}}

        staged = _shadow_challenger_update(
            preset,
            old_model,
            first_model,
            0.80,
            0.84,
            0.78,
            0.81,
            0.99,
        )
        self.assertEqual(staged["decision"], "challenger_staged")
        self.assertEqual(staged["challenger"]["streak"], 1)

        preset["training_policy_challenger"] = staged["challenger"]
        promoted = _shadow_challenger_update(
            preset,
            old_model,
            second_model,
            0.80,
            0.85,
            0.78,
            0.82,
            0.99,
        )
        self.assertEqual(promoted["decision"], "challenger_promoted")
        self.assertEqual(promoted["active_model"], second_model)

    def test_race_style_overrides_prefer_success_style_then_chronic_loss_advice(self):
        per_race_hints = {
            2202: {"loss_count": 5, "diagnosis": {"style_advice": "front_runner", "chronic": True}},
        }
        success_hints = {
            11017: {
                "preferred_running_style": "pace_chaser",
                "preferred_running_style_share": 0.7,
                "confidence": 0.6,
                "win_rate": 0.6,
            },
            3303: {
                "preferred_running_style": "late_surger",
                "preferred_running_style_share": 0.4,
                "confidence": 0.3,
                "win_rate": 0.4,
            },
        }

        overrides = learn_race_style_overrides(per_race_hints, success_hints)

        self.assertEqual(overrides["global"]["11017"], "pace_chaser")
        self.assertEqual(overrides["global"]["2202"], "front_runner")
        self.assertNotIn("3303", overrides["global"])

    def test_run_mode_policy_learns_preserve_and_push_bounds(self):
        top = [
            {
                **sample("top_a", 19000, losses=0, action_count=25),
                "support_actions": [{"kind": "race", "optional_race": True}] * 2,
            },
            {
                **sample("top_b", 18800, losses=0, action_count=25),
                "support_actions": [{"kind": "race", "optional_race": True}] * 2,
            },
        ]
        all_rows = top + [
            {
                **sample("all_c", 16000, losses=2, action_count=25),
                "support_actions": [],
            },
            {
                **sample("all_d", 15500, losses=3, action_count=25),
                "support_actions": [],
            },
        ]

        policy = learn_run_mode_policy(top, all_rows)

        self.assertTrue(policy["enabled"])
        self.assertGreaterEqual(policy["preserve_optional_race_penalty"], 0.03)
        self.assertGreaterEqual(policy["push_optional_race_bonus"], 0.02)

    def test_optional_race_policy_tightens_after_recurring_losses(self):
        preset = {
            "optional_race_max_training_score": 0.40,
            "optional_race_min_value": 0.66,
            "optional_race_rival_bonus": 0.34,
        }
        all_samples = [
            sample("loss_a", 11000, losses=3, g1_losses=1),
            sample("loss_b", 10800, losses=3, g1_losses=1),
            sample("loss_c", 10600, losses=2, g1_losses=1),
            sample("loss_d", 10400, losses=3, g1_losses=0),
        ]

        result = tune_optional_race_policy(preset, all_samples[:2], all_samples)

        self.assertLessEqual(result["optional_race_max_training_score"], 0.37)
        self.assertGreaterEqual(result["optional_race_min_value"], 0.71)
        self.assertTrue(result["optional_race_skip_if_stamina_low"])

    def test_race_result_dedupe_preserves_richer_race_time_context(self):
        turns = [{
            "turn": 35,
            "stats": {"speed": 820, "stamina": 540, "power": 760, "guts": 420, "wit": 690},
            "owned_skills": [{"skill_id": 200101}, {"skill_id": 200201}],
            "race_history": [{"turn": 35, "program_id": 11017, "running_style": 2, "result_rank": 1}],
            "events": [{
                "event": "race_result",
                "turn": 35,
                "program_id": 11017,
                "won": True,
                "finish_rank": 1,
                "running_style": 2,
                "skill_count_at_race": 2,
                "stats_at_race": {"speed": 820, "power": 760},
                "race": {"program_id": 11017, "name": "NHK Mile Cup", "grade": "G1"},
            }],
        }]

        races = race_entries_from_turns(turns)

        self.assertEqual(len(races), 1)
        self.assertEqual(races[0]["skill_count_at_race"], 2)
        self.assertEqual(races[0]["stats_at_race"]["speed"], 820)

    def test_select_reference_groups_prefers_stratified_when_buckets_exist(self):
        rows = []
        for idx, score in enumerate([19000, 18000, 12000, 11000]):
            s = sample(f"speed_{idx}", score, deck_quality_bucket=2)
            s["learning_metadata"] = {
                "session": {
                    "primary_stat_target": {"stat": "speed"},
                    "blue_spark_intent": {"preferred_color": "speed"},
                },
                "deck_quality_bucket": 2,
            }
            rows.append(s)
        for idx, score in enumerate([18500, 18000, 10000, 9000]):
            s = sample(f"power_{idx}", score, deck_quality_bucket=2)
            s["learning_metadata"] = {
                "session": {
                    "primary_stat_target": {"stat": "power"},
                    "blue_spark_intent": {"preferred_color": "power"},
                },
                "deck_quality_bucket": 2,
            }
            rows.append(s)

        top, bottom, stats, strategy = select_reference_groups(
            rows,
            score_floor=8000,
            score_floors_by_deck={2: 8000},
            prefer_stratified=True,
        )

        self.assertEqual(strategy, "stratified")
        self.assertTrue(top)
        self.assertTrue(bottom)
        self.assertTrue(any("speed_speed" in key for key in stats))
        self.assertTrue(any("power_power" in key for key in stats))

    def test_deviation_bias_boosts_human_override_and_dampens_bot_pick(self):
        learned = {"extra_weight": [[0.0] * 5 for _ in range(4)]}
        rows = [{
            "career_score": 18000,
            "turn": 60,
            "agreed": False,
            "bot_training_idx": 0,
            "human_training_idx": 2,
            "bot_score_margin": 2.0,
            "bot_predicted_total_gain": 20.0,
            "human_predicted_total_gain": 24.0,
            "actual_total_gain": 30.0,
            "bot_parity_at_capture": 0.0,
        }]

        tuned, summary = tune_deviation_bias(learned, rows)

        self.assertEqual(summary["used_rows"], 1)
        self.assertGreater(tuned["extra_weight"][2][2], 0.0)
        self.assertLess(tuned["extra_weight"][2][0], 0.0)

    def test_deviation_bias_fades_hard_when_bot_parity_is_high(self):
        learned = {"extra_weight": [[0.0] * 5 for _ in range(4)]}
        rows = [{
            "career_score": 18200,
            "turn": 42,
            "agreed": False,
            "bot_training_idx": 1,
            "human_training_idx": 2,
            "bot_score_margin": 1.5,
            "bot_predicted_total_gain": 24.0,
            "human_predicted_total_gain": 26.0,
            "actual_total_gain": 28.0,
            "bot_parity_at_capture": 0.91,
        } for _ in range(5)]

        _tuned, summary = tune_deviation_bias(learned, rows)

        self.assertLess(summary["fade_multiplier"], 0.2)
        self.assertGreater(summary["bot_parity"], 0.9)

    def test_item_policy_marks_unused_early_buy_as_dead_weight(self):
        samples = [
            {
                "score": 9000,
                "sample_weight": 1.0,
                "item_decisions": [{"kind": "buy", "turn": 18, "phase": "early", "name": "Pretty Mirror", "item_id": 4001}],
            },
            {
                "score": 9200,
                "sample_weight": 1.0,
                "item_decisions": [{"kind": "buy", "turn": 20, "phase": "early", "name": "Pretty Mirror", "item_id": 4001}],
            },
            {
                "score": 9100,
                "sample_weight": 1.0,
                "item_decisions": [{"kind": "buy", "turn": 22, "phase": "early", "name": "Pretty Mirror", "item_id": 4001}],
            },
            {
                "score": 9400,
                "sample_weight": 1.0,
                "item_decisions": [{"kind": "buy", "turn": 24, "phase": "early", "name": "Pretty Mirror", "item_id": 4001}],
            },
        ]

        policy, summary = learn_item_policy(samples)

        self.assertEqual(summary["learned_items"], 1)
        self.assertEqual(policy["items"]["Pretty Mirror"]["phase_adjustments"]["early"], 2)

    def test_item_policy_tracks_fast_use_timing(self):
        samples = [{
            "score": 18500,
            "sample_weight": 1.0,
            "item_decisions": [
                {"kind": "buy", "turn": 56, "phase": "late", "name": "Energy Drink MAX", "item_id": 5001},
                {"kind": "use", "turn": 58, "phase": "late", "name": "Energy Drink MAX", "item_id": 5001},
            ],
            "race_results": [{"turn": 59, "program_id": 11017, "won": True}],
        } for _ in range(4)]

        policy, _summary = learn_item_policy(samples)

        row = policy["items"]["Energy Drink MAX"]["phase_stats"]["late"]
        self.assertGreaterEqual(row["fast_use_rate"], 1.0)
        self.assertGreaterEqual(row["race_window_use_rate"], 1.0)
        self.assertGreaterEqual(policy["items"]["Energy Drink MAX"]["timing_adjustments"]["late"], 1)

    def test_extract_actions_tracks_multi_window_setup_payoff(self):
        turns = [
            {
                "turn": 10,
                "selected_action": "train",
                "current_command": {"command_id": 101},
                "stats": {"speed": 100, "stamina": 100, "power": 100, "guts": 100, "wit": 100, "skill_point": 50, "hp": 80},
                "support_bonds": {"1": 74},
                "training_snapshot": {
                    "trainings": [
                        {
                            "command_id": 101,
                            "name": "Speed",
                            "weighted_total_gain": 20,
                            "partner_count": 1,
                            "deck_partner_count": 1,
                            "rainbow_count": 0,
                            "hint_count": 0,
                            "failure_rate": 0,
                            "stat_gain": {"speed": 18},
                            "partners": [{"target_id": 1, "bond": 74, "deck_partner": True, "rainbow": False}],
                        }
                    ]
                },
            },
            {
                "turn": 12,
                "stats": {"speed": 130, "stamina": 100, "power": 100, "guts": 100, "wit": 100, "skill_point": 55, "hp": 70},
                "support_bonds": {"1": 82},
                "training_snapshot": {
                    "trainings": [
                        {
                            "command_id": 101,
                            "name": "Speed",
                            "weighted_total_gain": 46,
                            "partner_count": 1,
                            "deck_partner_count": 1,
                            "rainbow_count": 1,
                            "hint_count": 0,
                            "failure_rate": 0,
                            "stat_gain": {"speed": 30},
                            "partners": [{"target_id": 1, "bond": 82, "deck_partner": True, "rainbow": True}],
                        }
                    ]
                },
            },
            {
                "turn": 16,
                "stats": {"speed": 180, "stamina": 100, "power": 100, "guts": 100, "wit": 100, "skill_point": 60, "hp": 60},
                "support_bonds": {"1": 86},
                "training_snapshot": {
                    "trainings": [
                        {
                            "command_id": 101,
                            "name": "Speed",
                            "weighted_total_gain": 52,
                            "partner_count": 1,
                            "deck_partner_count": 1,
                            "rainbow_count": 1,
                            "hint_count": 0,
                            "failure_rate": 0,
                            "stat_gain": {"speed": 34},
                            "partners": [{"target_id": 1, "bond": 86, "deck_partner": True, "rainbow": True}],
                        }
                    ]
                },
            },
        ]

        actions = extract_actions_from_turns(turns)

        self.assertEqual(len(actions), 1)
        metrics = actions[0]["future_window_metrics"]
        self.assertIn("2", metrics)
        self.assertIn("4", metrics)
        self.assertEqual(metrics["2"]["rainbow_unlocks"], 1)
        self.assertGreater(metrics["4"]["best_training_gain_delta"], 20)
        self.assertGreater(metrics["4"]["selected_partner_best_training_reuse"], 0)


class ActionClassifierSplitTests(unittest.TestCase):
    def test_picks_only_clean_high_output_samples_as_positive_policy_signal(self):
        rows = [
            sample("clean_efficient_a", 19000, per_action_gain=2.5),
            sample("clean_efficient_b", 18800, per_action_gain=2.3),
            sample("clean_mediocre_a", 18500, per_action_gain=0.8),
            sample("clean_mediocre_b", 18000, per_action_gain=0.7),
            sample("losing_high_gain_a", 24000, losses=2, g1_losses=1, per_action_gain=3.0),
            sample("losing_high_gain_b", 23000, losses=1, g1_losses=0, per_action_gain=2.9),
            sample("low_score_high_gain", 12000, per_action_gain=2.8),
            sample("low_score_mid_gain", 11500, per_action_gain=1.8),
        ]
        top, bottom = split_action_classifier_groups(rows)
        self.assertTrue(top)
        self.assertTrue(bottom)
        top_sources = {row["source"] for row in top}
        bottom_sources = {row["source"] for row in bottom}
        self.assertIn("clean_efficient_a", top_sources)
        self.assertNotIn("losing_high_gain_a", top_sources)
        self.assertNotIn("low_score_high_gain", top_sources)
        self.assertTrue(bottom_sources & {"losing_high_gain_a", "losing_high_gain_b", "low_score_high_gain", "low_score_mid_gain"})

    def test_returns_no_positive_action_group_when_every_run_fails_objective_gate(self):
        rows = [
            sample("loss_a", 22000, losses=2, g1_losses=1, per_action_gain=3.0),
            sample("loss_b", 21000, losses=1, g1_losses=0, per_action_gain=2.8),
            sample("low_a", 12000, losses=0, g1_losses=0, per_action_gain=2.6),
            sample("low_b", 11000, losses=0, g1_losses=0, per_action_gain=2.4),
        ]

        top, bottom = split_action_classifier_groups(rows)

        self.assertEqual(top, [])
        self.assertTrue(bottom)

    def test_parent_library_imports_without_actions_are_excluded(self):
        rows = [
            {"source": "user_parent_library", "score": 50000, "actions": []},
            {"source": "user_parent_library", "score": 48000, "actions": []},
            sample("bot_a", 10000, per_action_gain=1.5),
            sample("bot_b", 10000, per_action_gain=1.4),
            sample("bot_c", 10000, per_action_gain=1.3),
            sample("bot_d", 10000, per_action_gain=1.2),
        ]
        top, bottom = split_action_classifier_groups(rows)
        all_picks = {row["source"] for row in top + bottom}
        self.assertNotIn("user_parent_library", all_picks)

    def test_parent_library_samples_are_not_behavior_learning_samples(self):
        row = {
            "source": "user_parent_library",
            "status": "parent_library",
            "final_turn": 78,
            "actions": [],
        }
        self.assertFalse(_is_behavior_learning_sample(row))

    def test_returns_empty_when_too_few_action_rich_samples(self):
        rows = [
            sample("only_one", 12000, per_action_gain=2.0),
            {"source": "parent_lib", "score": 50000, "actions": []},
        ]
        top, bottom = split_action_classifier_groups(rows)
        self.assertEqual(top, [])
        self.assertEqual(bottom, [])


class ManualDeviationSignalTests(unittest.TestCase):
    def test_latest_manual_career_log_feeds_synthesized_deviation_signal(self):
        with tempfile.TemporaryDirectory() as tmp:
            runtime = Path(tmp)
            manual_dir = runtime / "manual_career_logs"
            manual_dir.mkdir(parents=True)
            path = manual_dir / "latest_manual_career_log.json"
            data = {
                "status": "finished",
                "turns": [
                    {
                        "turn": 1,
                        "selected_action": "train",
                        "current_command": {"command_id": 101},
                        "stats": {"speed": 100, "stamina": 100, "power": 100, "guts": 100, "wit": 100, "skill_point": 0, "hp": 100},
                        "support_bonds": {"1": 75},
                        "training_snapshot": {
                            "trainings": [
                                {
                                    "command_id": 101,
                                    "name": "Speed",
                                    "weighted_total_gain": 18,
                                    "stat_gain": {"speed": 8},
                                    "partners": [{"target_id": 1, "deck_partner": True, "bond": 75}],
                                },
                                {
                                    "command_id": 106,
                                    "name": "Wit",
                                    "weighted_total_gain": 25,
                                    "stat_gain": {"wit": 20, "skill_point": 10},
                                    "partners": [],
                                },
                            ],
                        },
                    },
                    {
                        "turn": 5,
                        "stats": {"speed": 145, "stamina": 105, "power": 110, "guts": 100, "wit": 110, "skill_point": 20, "hp": 80},
                        "support_bonds": {"1": 85},
                        "training_snapshot": {
                            "trainings": [
                                {"command_id": 101, "weighted_total_gain": 30, "stat_gain": {"speed": 25}, "partners": []},
                                {"command_id": 106, "weighted_total_gain": 20, "stat_gain": {"wit": 18}, "partners": []},
                            ],
                        },
                    },
                    {
                        "turn": 78,
                        "stats": {"speed": 1100, "stamina": 800, "power": 900, "guts": 650, "wit": 900, "skill_point": 2200, "hp": 70},
                    },
                ],
            }
            path.write_text(json.dumps(data), encoding="utf-8")

            rows = load_deviation_signals(runtime, recent=5, min_career_score=1)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["source"], "manual_hachimi_synthetic")
        self.assertFalse(row["agreed"])
        self.assertEqual(row["human_training_idx"], 0)
        self.assertEqual(row["bot_training_idx"], 4)
        self.assertGreater(row["actual_total_gain"], row["bot_predicted_total_gain"])


class MonotonicApplyGateTests(unittest.TestCase):
    def test_allows_corrective_apply_below_previous_accepted_score(self):
        older = sample("bot", 13200)
        older["parent_instance_id"] = 1
        latest = sample("bot", 12900)
        latest["parent_instance_id"] = 2
        preset = {
            "learning_metadata": {
                "monotonic_apply_gate": {
                    "accepted_score": 13200,
                    "accepted_score_source": "estimated_score",
                }
            }
        }

        gate = monotonic_apply_gate(preset, [older, latest])

        self.assertTrue(gate["enabled"])
        self.assertTrue(gate["allowed"])
        self.assertTrue(gate["corrective_apply"])
        self.assertTrue(gate["baseline_preserved"])
        self.assertEqual(gate["baseline_source"], "previous_accepted")
        self.assertEqual(gate["accepted_score"], 13200)
        self.assertLess(gate["delta_vs_baseline"], 0)

    def test_accepts_latest_bot_run_above_previous_accepted_score(self):
        older = sample("bot", 13200)
        older["parent_instance_id"] = 1
        latest = sample("bot", 13400)
        latest["parent_instance_id"] = 2
        preset = {
            "learning_metadata": {
                "monotonic_apply_gate": {
                    "accepted_score": 13200,
                    "accepted_score_source": "estimated_score",
                }
            }
        }

        gate = monotonic_apply_gate(preset, [older, latest])

        self.assertTrue(gate["allowed"])
        self.assertEqual(gate["accepted_score"], 13400)
        self.assertGreater(gate["delta_vs_baseline"], 0)

    def test_allows_corrective_apply_below_best_prior_when_no_accepted_score(self):
        best = sample("bot", 14000)
        best["parent_instance_id"] = 1
        worse_previous = sample("bot", 9000)
        worse_previous["parent_instance_id"] = 2
        latest = sample("bot", 9500)
        latest["parent_instance_id"] = 3

        gate = monotonic_apply_gate({}, [best, worse_previous, latest])

        self.assertTrue(gate["allowed"])
        self.assertTrue(gate["corrective_apply"])
        self.assertEqual(gate["baseline_source"], "best_prior_bot_run")
        self.assertEqual(gate["best_prior_score"], 14000)
        self.assertEqual(gate["baseline_score"], 14000)
        self.assertEqual(gate["accepted_score"], 14000)

    def test_uses_best_prior_when_it_is_higher_than_previous_accepted_score(self):
        best = sample("bot", 14000)
        best["parent_instance_id"] = 1
        latest = sample("bot", 13200)
        latest["parent_instance_id"] = 2
        preset = {
            "learning_metadata": {
                "monotonic_apply_gate": {
                    "accepted_score": 13000,
                    "accepted_score_source": "estimated_score",
                }
            }
        }

        gate = monotonic_apply_gate(preset, [best, latest])

        self.assertTrue(gate["allowed"])
        self.assertTrue(gate["corrective_apply"])
        self.assertEqual(gate["baseline_source"], "best_prior_bot_run")
        self.assertEqual(gate["baseline_score"], 14000)
        self.assertEqual(gate["accepted_score"], 14000)

    def test_can_disable_corrective_apply(self):
        older = sample("bot", 13200)
        older["parent_instance_id"] = 1
        latest = sample("bot", 12900)
        latest["parent_instance_id"] = 2
        preset = {
            "auto_learning_corrective_apply_enabled": False,
            "learning_metadata": {
                "monotonic_apply_gate": {
                    "accepted_score": 13200,
                    "accepted_score_source": "estimated_score",
                }
            },
        }

        gate = monotonic_apply_gate(preset, [older, latest])

        self.assertFalse(gate["allowed"])
        self.assertEqual(gate["baseline_source"], "previous_accepted")
        self.assertEqual(gate["accepted_score"], 13200)


class LearningRateScaleTests(unittest.TestCase):
    def test_scale_above_one_when_data_below_baseline(self):
        scale = learning_rate_scale(top_count=2, action_count=50)
        self.assertGreater(scale, 1.0)

    def test_scale_near_one_at_baseline(self):
        scale = learning_rate_scale(top_count=8, action_count=200)
        self.assertAlmostEqual(scale, 1.0, places=2)

    def test_scale_shrinks_as_sample_count_grows(self):
        late = learning_rate_scale(top_count=64, action_count=2000)
        self.assertLess(late, 0.6)

    def test_scale_floor_prevents_freeze(self):
        scale = learning_rate_scale(top_count=10000, action_count=1000000)
        self.assertGreaterEqual(scale, 0.25)


class RecencyWeightingTests(unittest.TestCase):
    def test_newer_samples_get_higher_weight_than_older_samples(self):
        samples = [
            {
                "source": "bot",
                "path": "new.json",
                "ended_at": "2026-05-15T12:00:00",
                "score": 12000,
                "sample_weight": 1.0,
                "learning_metadata": {"outcome_assessment": {"overall": "objective_success"}},
            },
            {
                "source": "bot",
                "path": "old.json",
                "ended_at": "2026-05-01T12:00:00",
                "score": 12000,
                "sample_weight": 1.0,
                "learning_metadata": {"outcome_assessment": {"overall": "objective_success"}},
            },
        ]

        summary = apply_recency_weights(
            samples,
            {
                "enabled": True,
                "bias": 0.5,
                "half_life": 1,
                "recent_failure_bias": 0.0,
            },
        )

        self.assertGreater(samples[0]["sample_weight"], samples[1]["sample_weight"])
        self.assertEqual(samples[0]["learning_metadata"]["recency"]["rank"], 0)
        self.assertEqual(summary["newest_sample"]["path"], "new.json")

    def test_recent_failures_are_not_recency_amplified(self):
        samples = [
            {
                "source": "bot",
                "path": "fresh_failure.json",
                "ended_at": "2026-05-15T12:00:00",
                "score": 7000,
                "sample_weight": 0.4,
                "learning_metadata": {"outcome_assessment": {"overall": "run_failure"}},
            },
            {
                "source": "bot",
                "path": "older_failure.json",
                "ended_at": "2026-05-01T12:00:00",
                "score": 7000,
                "sample_weight": 0.4,
                "learning_metadata": {"outcome_assessment": {"overall": "run_failure"}},
            },
        ]

        apply_recency_weights(
            samples,
            {
                "enabled": True,
                "bias": 0.25,
                "half_life": 1,
                "recent_failure_bias": 0.5,
            },
        )

        fresh = samples[0]["learning_metadata"]["recency"]
        older = samples[1]["learning_metadata"]["recency"]
        self.assertEqual(fresh["failure_bonus"], 0.0)
        self.assertEqual(older["failure_bonus"], 0.0)
        self.assertEqual(fresh["multiplier"], 1.0)
        self.assertEqual(older["multiplier"], 1.0)
        self.assertEqual(samples[0]["sample_weight"], samples[1]["sample_weight"])

    def test_score_regression_is_marked_but_not_amplified_for_partial_success(self):
        samples = [
            {
                "source": "bot",
                "path": "older_a.json",
                "ended_at": "2026-05-01T12:00:00",
                "score": 18000,
                "sample_weight": 1.0,
                "learning_metadata": {"outcome_assessment": {"overall": "objective_success"}},
            },
            {
                "source": "bot",
                "path": "older_b.json",
                "ended_at": "2026-05-02T12:00:00",
                "score": 17600,
                "sample_weight": 1.0,
                "learning_metadata": {"outcome_assessment": {"overall": "objective_success"}},
            },
            {
                "source": "bot",
                "path": "new_slump.json",
                "ended_at": "2026-05-03T12:00:00",
                "score": 12000,
                "sample_weight": 1.0,
                "learning_metadata": {"outcome_assessment": {"overall": "partial_success"}},
            },
        ]

        summary = apply_recency_weights(
            samples,
            {
                "enabled": True,
                "bias": 0.25,
                "half_life": 6,
                "recent_failure_bias": 0.0,
                "regression_enabled": True,
                "regression_bias": 0.6,
                "regression_window": 2,
                "regression_floor": 0.85,
            },
        )

        regression = samples[2]["learning_metadata"]["performance_regression"]
        recency = samples[2]["learning_metadata"]["recency"]
        self.assertTrue(regression["triggered"])
        self.assertLess(regression["score_ratio"], 0.85)
        self.assertEqual(regression["effective_bonus"], 0.0)
        self.assertEqual(recency["regression_bonus"], 0.0)
        self.assertTrue(recency["diagnostic_only"])
        self.assertEqual(summary["regression_count"], 1)

    def test_recent_score_jump_gets_progression_bonus(self):
        samples = [
            {
                "source": "bot",
                "path": "older_a.json",
                "ended_at": "2026-05-01T12:00:00",
                "score": 15000,
                "sample_weight": 1.0,
                "learning_metadata": {"outcome_assessment": {"overall": "objective_success"}},
            },
            {
                "source": "bot",
                "path": "older_b.json",
                "ended_at": "2026-05-02T12:00:00",
                "score": 15200,
                "sample_weight": 1.0,
                "learning_metadata": {"outcome_assessment": {"overall": "objective_success"}},
            },
            {
                "source": "bot",
                "path": "new_jump.json",
                "ended_at": "2026-05-03T12:00:00",
                "score": 15850,
                "sample_weight": 1.0,
                "learning_metadata": {"outcome_assessment": {"overall": "objective_success"}},
            },
        ]

        summary = apply_recency_weights(
            samples,
            {
                "enabled": True,
                "bias": 0.25,
                "half_life": 6,
                "recent_failure_bias": 0.0,
                "regression_enabled": False,
                "progression_enabled": True,
                "progression_bias": 0.6,
                "progression_window": 2,
                "progression_delta": 500,
            },
        )

        progression = samples[2]["learning_metadata"]["performance_progression"]
        recency = samples[2]["learning_metadata"]["recency"]
        self.assertTrue(progression["triggered"])
        self.assertGreaterEqual(progression["score_delta"], 500)
        self.assertGreater(progression["effective_bonus"], 0.0)
        self.assertGreater(recency["progression_bonus"], 0.0)
        self.assertEqual(summary["progression_count"], 1)

    def test_sample_signature_changes_when_recency_config_changes(self):
        samples = [{
            "source": "bot",
            "path": "career_log_1.json",
            "status": "finished",
            "final_turn": 78,
            "turn_count": 78,
            "final_stats": {"speed": 1000, "stamina": 800, "power": 900, "guts": 500, "wit": 850, "skill_point": 40},
            "race_wins": 10,
            "race_losses": 2,
            "actions": [{"idx": 0}],
        }]

        sig_a = sample_signature(samples, recency_config={"enabled": True, "bias": 0.3, "half_life": 8, "recent_failure_bias": 0.2})
        sig_b = sample_signature(samples, recency_config={"enabled": True, "bias": 0.8, "half_life": 8, "recent_failure_bias": 0.2})

        self.assertNotEqual(sig_a, sig_b)

    def test_preset_recency_config_uses_defaults(self):
        config = auto_learning_recency_config({})

        self.assertTrue(config["enabled"])
        self.assertEqual(config["bias"], 0.55)
        self.assertEqual(config["half_life"], 12)
        self.assertEqual(config["recent_failure_bias"], 0.35)
        self.assertTrue(config["regression_enabled"])
        self.assertEqual(config["regression_bias"], 0.7)
        self.assertEqual(config["regression_window"], 5)
        self.assertEqual(config["regression_floor"], 0.92)
        self.assertTrue(config["progression_enabled"])
        self.assertEqual(config["progression_bias"], 0.35)
        self.assertEqual(config["progression_window"], 5)
        self.assertEqual(config["progression_delta"], 500)


class ManualOnlyFilterTests(unittest.TestCase):
    def test_manual_sources_are_recognised(self):
        self.assertTrue(_is_manual_sample({"source": "manual_hachimi"}))


class FirstSummerFriendshipDiagnosticTests(unittest.TestCase):
    def test_diagnostic_summarizes_friendship_hit_rates(self):
        samples = [
            {
                "source": "bot",
                "actions": [
                    {
                        "turn": 35,
                        "decision_understanding": {
                            "signals": {
                                "current_rainbow_unlocked_count": 2,
                                "target_rainbow_unlocked_count": 4,
                            }
                        },
                    }
                ],
            },
            {
                "source": "manual_hachimi",
                "actions": [
                    {
                        "turn": 35,
                        "decision_understanding": {
                            "signals": {
                                "current_rainbow_unlocked_count": 4,
                                "target_rainbow_unlocked_count": 4,
                            }
                        },
                    }
                ],
            },
        ]

        summary = first_summer_friendship_diagnostic(samples, top_samples=[samples[1]], bottom_samples=[samples[0]])

        self.assertEqual(summary["overall"]["sample_count"], 2)
        self.assertEqual(summary["overall"]["hit_rate"], 0.5)
        self.assertEqual(summary["overall"]["manual_hit_rate"], 1.0)
        self.assertEqual(summary["overall"]["bot_hit_rate"], 0.0)
        self.assertEqual(summary["top"]["hit_rate"], 1.0)
        self.assertEqual(summary["bottom"]["hit_rate"], 0.0)

        self.assertTrue(_is_manual_sample({"source": "manual_legacy"}))
        self.assertTrue(_is_manual_sample({"source": "MANUAL_SUMMARY"}))

    def test_non_manual_sources_are_rejected(self):
        self.assertFalse(_is_manual_sample({"source": "bot"}))
        self.assertFalse(_is_manual_sample({"source": "user_parent_library"}))
        self.assertFalse(_is_manual_sample({"source": "bot_parent_library"}))
        self.assertFalse(_is_manual_sample({}))


class OperatorOwnedPresetFieldTests(unittest.TestCase):
    def test_auto_learning_preserves_user_skill_plan_and_parent_targets(self):
        learned = {
            "skill_profile_style": "front_runner",
            "skill_profile_distance": "medium",
            "skill_buy_on_sight": ["Groundwork"],
            "desired_parent_sparks": {"blue": ["Stamina"], "pink": [], "green": [], "white": []},
            "training_policy_model": {"enabled": True, "weights": {"speed": 0.1}},
            "optional_race_min_value": 0.82,
        }
        current = {
            "skill_profile_style": "late_surger",
            "skill_profile_distance": "medium",
            "skill_buy_on_sight": ["Groundwork", "Corner Adept", "Straightaway Spurt"],
            "desired_parent_sparks": {
                "blue": ["Power"],
                "pink": ["Medium", "Mile"],
                "green": [],
                "white": ["NHK Mile C.", "Firm Conditions"],
            },
            "training_policy_model": {"enabled": False},
            "optional_race_min_value": 1.05,
        }

        merged, preserved = _preserve_operator_owned_fields(learned, current)

        self.assertEqual(merged["skill_profile_style"], "late_surger")
        self.assertEqual(merged["skill_buy_on_sight"], ["Groundwork", "Corner Adept", "Straightaway Spurt"])
        self.assertEqual(merged["desired_parent_sparks"]["blue"], ["Power"])
        self.assertEqual(merged["desired_parent_sparks"]["pink"], ["Medium", "Mile"])
        self.assertEqual(merged["training_policy_model"], learned["training_policy_model"])
        self.assertEqual(merged["optional_race_min_value"], learned["optional_race_min_value"])
        self.assertIn("skill_buy_on_sight", preserved)
        self.assertIn("desired_parent_sparks", preserved)

    def test_learned_race_style_overrides_survive_empty_operator_default(self):
        learned = {
            "race_style_overrides": {
                "11017": "pace_chaser",
                "2202": "front_runner",
            }
        }
        current = {
            "race_style_overrides": {},
        }

        merged, preserved = _preserve_operator_owned_fields(learned, current)

        self.assertEqual(merged["race_style_overrides"], learned["race_style_overrides"])
        self.assertNotIn("race_style_overrides", preserved)

    def test_operator_race_style_override_wins_without_dropping_learned_rest(self):
        learned = {
            "race_style_overrides": {
                "11017": "pace_chaser",
                "2202": "front_runner",
            }
        }
        current = {
            "race_style_overrides": {
                "2202": "late_surger",
            }
        }

        merged, preserved = _preserve_operator_owned_fields(learned, current)

        self.assertEqual(
            merged["race_style_overrides"],
            {
                "11017": "pace_chaser",
                "2202": "late_surger",
            },
        )
        self.assertIn("race_style_overrides", preserved)

    def test_v2_schema_learned_overrides_survive_empty_v2_current(self):
        """Bug-fix regression: the source preset stores
        race_style_overrides as `{schema, global: {}, by_chara: {}}`
        (the v2 schema with empty maps). The learner produces v2 with
        a populated global. Previously a shallow `dict.update` was
        overwriting the learned populated global with the source's
        empty one — silently discarding every learned per-race
        override. Symptom: `change_running_style` never firing for
        chronic style-mismatch races even though the learner had
        correctly flagged them.
        """
        learned = {
            "race_style_overrides": {
                "schema": "sweepy_race_style_overrides_v2",
                "global": {
                    "73": "late_surger",
                    "164": "late_surger",
                    "80": "pace_chaser",
                },
                "by_chara": {},
            }
        }
        current = {
            "race_style_overrides": {
                "schema": "sweepy_race_style_overrides_v2",
                "global": {},
                "by_chara": {},
            }
        }
        merged, preserved = _preserve_operator_owned_fields(learned, current)
        # All three learned overrides must survive.
        self.assertEqual(
            merged["race_style_overrides"]["global"],
            {"73": "late_surger", "164": "late_surger", "80": "pace_chaser"},
        )
        # Empty operator input is a no-op; not flagged as preserved.
        self.assertNotIn("race_style_overrides", preserved)

    def test_v2_schema_user_override_layers_on_top_of_learned(self):
        """When the source preset DOES carry user-set overrides in the
        v2 format, they must layer on top of the learned ones per
        program_id (user wins for that race; learned wins everywhere
        else)."""
        learned = {
            "race_style_overrides": {
                "schema": "sweepy_race_style_overrides_v2",
                "global": {
                    "73": "late_surger",
                    "164": "late_surger",
                },
                "by_chara": {},
            }
        }
        current = {
            "race_style_overrides": {
                "schema": "sweepy_race_style_overrides_v2",
                "global": {
                    "73": "pace_chaser",  # user overrides learned for race 73
                    "200": "end_closer",  # new race not in learned
                },
                "by_chara": {},
            }
        }
        merged, preserved = _preserve_operator_owned_fields(learned, current)
        self.assertEqual(
            merged["race_style_overrides"]["global"],
            {
                "73": "pace_chaser",   # user override wins
                "164": "late_surger",  # learned-only survives
                "200": "end_closer",   # user-only added
            },
        )
        self.assertIn("race_style_overrides", preserved)

    def test_flat_user_overrides_promote_into_v2_global(self):
        """Bug-fix regression: when the user has legacy-flat-format
        overrides on the source preset AND the learner produces v2
        format, `_style_for_entry` ignores top-level flat keys whenever
        the v2 `global` sub-dict is present. So flat user overrides
        must be PROMOTED into the v2 global at user-wins priority,
        not just copied at top level.

        Real data hit this: 9 user-set flat pace_chaser overrides were
        being silently dropped because the learner was supplying a
        v2 `global` for other races.
        """
        learned = {
            "race_style_overrides": {
                "schema": "sweepy_race_style_overrides_v2",
                "global": {
                    "73": "late_surger",   # learned only — no user override
                    "164": "late_surger",  # learner says late_surger
                },
                "by_chara": {},
            }
        }
        current = {
            "race_style_overrides": {
                # Legacy flat format that the user manually authored
                # before the v2 schema existed.
                "163": "pace_chaser",  # user-only — not in learned
                "164": "pace_chaser",  # CONFLICTS with learned → user wins
                "81": "pace_chaser",
            }
        }
        merged, preserved = _preserve_operator_owned_fields(learned, current)
        ov = merged["race_style_overrides"]
        # All overrides end up in the v2 `global` sub-dict so
        # `_style_for_entry` (which only consults `global` when the
        # v2 schema is detected) actually sees them.
        self.assertEqual(
            ov["global"],
            {
                "73": "late_surger",     # learned-only survived
                "164": "pace_chaser",    # user override won over learned
                "163": "pace_chaser",    # user-only added
                "81": "pace_chaser",     # user-only added
            },
        )
        self.assertIn("race_style_overrides", preserved)

    def test_v2_schema_by_chara_overrides_deep_merge(self):
        """Per-character overrides nested under by_chara should also
        deep-merge — user adding overrides for one chara shouldn't
        wipe out the learned global or other chara entries."""
        learned = {
            "race_style_overrides": {
                "schema": "sweepy_race_style_overrides_v2",
                "global": {"73": "late_surger"},
                "by_chara": {
                    "100501": {"164": "pace_chaser"},
                },
            }
        }
        current = {
            "race_style_overrides": {
                "schema": "sweepy_race_style_overrides_v2",
                "global": {},
                "by_chara": {
                    "100502": {"73": "front_runner"},
                },
            }
        }
        merged, preserved = _preserve_operator_owned_fields(learned, current)
        ov = merged["race_style_overrides"]
        # Learned global preserved
        self.assertEqual(ov["global"], {"73": "late_surger"})
        # Both chara entries present
        self.assertEqual(ov["by_chara"]["100501"], {"164": "pace_chaser"})
        self.assertEqual(ov["by_chara"]["100502"], {"73": "front_runner"})


class InvariantAssertionTests(unittest.TestCase):
    def _baseline(self):
        return {
            "expect_attribute": [1200, 1166, 1166, 1166, 1166],
            "extra_weight": [[0.0] * 5 for _ in range(4)],
            "base_score": [0.0] * 5,
            "rest_threshold": 48,
            "learn_skill_threshold": 350,
            "optional_race_max_training_score": 0.34,
            "optional_race_min_value": 0.76,
            "score_value": [[0.11, 0.10, 0.006, 0.09] for _ in range(5)],
        }

    def test_baseline_preset_passes_invariants(self):
        assert_learned_preset_invariants(self._baseline())

    def test_expect_attribute_out_of_range_raises(self):
        p = self._baseline()
        p["expect_attribute"] = [9999, 1166, 1166, 1166, 1166]
        with self.assertRaises(LearnedPresetInvariantError):
            assert_learned_preset_invariants(p)

    def test_expect_attribute_wrong_length_raises(self):
        p = self._baseline()
        p["expect_attribute"] = [1100, 1100, 1100]
        with self.assertRaises(LearnedPresetInvariantError):
            assert_learned_preset_invariants(p)

    def test_expect_attribute_profile_out_of_range_raises(self):
        p = self._baseline()
        p["expect_attribute_profiles"] = {
            "power_power|style=late_surger|distance=medium|deck=speed3_stamina1_wit1": {
                "expect_attribute": [1200, 1701, 1100, 700, 700],
            }
        }
        with self.assertRaises(LearnedPresetInvariantError):
            assert_learned_preset_invariants(p)

    def test_extra_weight_out_of_clamp_raises(self):
        p = self._baseline()
        p["extra_weight"][0][2] = 1.5  # outside [-0.5, 0.7]
        with self.assertRaises(LearnedPresetInvariantError):
            assert_learned_preset_invariants(p)

    def test_rest_threshold_out_of_range_raises(self):
        p = self._baseline()
        p["rest_threshold"] = 200
        with self.assertRaises(LearnedPresetInvariantError):
            assert_learned_preset_invariants(p)

    def test_skill_threshold_out_of_range_raises(self):
        p = self._baseline()
        p["learn_skill_threshold"] = 50000
        with self.assertRaises(LearnedPresetInvariantError):
            assert_learned_preset_invariants(p)

    def test_none_or_missing_optional_race_keys_pass(self):
        p = self._baseline()
        del p["optional_race_max_training_score"]
        del p["optional_race_min_value"]
        assert_learned_preset_invariants(p)

    def test_score_value_energy_column_tight_bound(self):
        # Energy column (index 2) clamps to 0.010 in the tuner. A refactor
        # that silently widened it to 0.30 (column 0/1 range) should be caught.
        p = self._baseline()
        p["score_value"][2][2] = 0.10  # well above the energy column cap
        with self.assertRaises(LearnedPresetInvariantError):
            assert_learned_preset_invariants(p)

    def test_stat_value_multiplier_negative_raises(self):
        p = self._baseline()
        p["stat_value_multiplier"] = [-0.01, 0.01, 0.01, 0.01, 0.01, 0.005]
        with self.assertRaises(LearnedPresetInvariantError):
            assert_learned_preset_invariants(p)

    def test_stat_value_multiplier_above_cap_raises(self):
        p = self._baseline()
        p["stat_value_multiplier"] = [0.5, 0.01, 0.01, 0.01, 0.01, 0.005]
        with self.assertRaises(LearnedPresetInvariantError):
            assert_learned_preset_invariants(p)

    def test_optional_race_bonus_out_of_range_raises(self):
        p = self._baseline()
        p["optional_race_epithet_bonus"] = 1.2
        with self.assertRaises(LearnedPresetInvariantError):
            assert_learned_preset_invariants(p)


class ExpectAttributeProfileTests(unittest.TestCase):
    def test_default_expect_attribute_is_realistic_not_unbounded(self):
        self.assertEqual(EXPECT_ATTRIBUTE_DEFAULT, [1100, 700, 950, 600, 800])
        self.assertEqual(normalize_preset({"name": "fresh"})["expect_attribute"], EXPECT_ATTRIBUTE_DEFAULT)

    def test_resolve_expect_attribute_prefers_matching_deck_profile(self):
        preset = normalize_preset({
            "name": "expect-profile-test",
            "expect_attribute": [1200, 1166, 1166, 1166, 1166],
            "desired_parent_sparks": {"blue": ["Power"], "pink": [], "green": [], "white": []},
            "skill_profile_style": "late_surger",
            "skill_profile_distance": "medium",
            "_run_context": {
                "support_cards": [
                    {"type": "Speed"},
                    {"type": "Speed"},
                    {"type": "Speed"},
                    {"type": "Stamina"},
                    {"type": "Wit"},
                ],
                "deck_quality_bucket": 2,
            },
        })
        keys = expect_attribute_profile_lookup_keys(preset)
        preset["expect_attribute_profiles"] = {
            keys[0]: [1200, 760, 1100, 680, 780],
            keys[1]: [1180, 900, 1080, 720, 760],
        }

        self.assertEqual(
            resolve_expect_attribute(preset),
            [1200, 760, 1100, 680, 780],
        )

    def test_resolve_expect_attribute_falls_back_to_balanced_profile_before_top_level(self):
        preset = normalize_preset({
            "name": "expect-balanced-fallback-test",
            "expect_attribute": [1200, 1166, 1166, 1166, 1166],
            "desired_parent_sparks": {"blue": ["Power"], "pink": [], "green": [], "white": []},
            "skill_profile_style": "front_runner",
            "skill_profile_distance": "long",
        })
        preset["expect_attribute_profiles"] = {
            "balanced_any": [1160, 795, 1014, 564, 847],
        }

        self.assertEqual(resolve_expect_attribute(preset), [1160, 795, 1014, 564, 847])

    def test_learn_expect_attribute_profiles_emits_lower_target_for_speed_heavy_deck(self):
        def row(name, speed, stamina, power, guts, wit, support_types, score):
            return {
                "source": name,
                "score": score,
                "status": "finished",
                "final_turn": 78,
                "full_career_capture": True,
                "final_stats": {
                    "speed": speed,
                    "stamina": stamina,
                    "power": power,
                    "guts": guts,
                    "wit": wit,
                },
                "learning_metadata": {
                    "session": {
                        "primary_stat_target": {"stat": "power"},
                        "blue_spark_intent": {"preferred_color": "power"},
                        "style_target": "late_surger",
                    },
                    "deck_quality_bucket": 2,
                },
                "desired_parent_sparks": {"blue": ["Power"], "pink": [], "green": [], "white": []},
                "run_context": {
                    "support_cards": [{"type": item} for item in support_types],
                    "deck_quality_bucket": 2,
                    "skill_profile_distance": "medium",
                    "desired_parent_sparks": {"blue": ["Power"], "pink": [], "green": [], "white": []},
                },
                "skill_profile_distance": "medium",
            }

        speed_heavy_top = [
            row("a1", 1160, 700, 1080, 560, 780, ["Speed", "Speed", "Speed", "Stamina", "Wit"], 17000),
            row("a2", 1140, 720, 1060, 550, 770, ["Speed", "Speed", "Speed", "Stamina", "Wit"], 16800),
            row("a3", 1180, 690, 1100, 580, 790, ["Speed", "Speed", "Speed", "Stamina", "Wit"], 17200),
            row("a4", 1150, 710, 1070, 570, 760, ["Speed", "Speed", "Speed", "Stamina", "Wit"], 16950),
        ]
        stamina_heavy = [
            row("b1", 1000, 980, 1040, 520, 640, ["Speed", "Stamina", "Stamina", "Power", "Wit"], 16600),
            row("b2", 1010, 960, 1020, 510, 650, ["Speed", "Stamina", "Stamina", "Power", "Wit"], 16550),
            row("b3", 990, 1000, 1030, 500, 630, ["Speed", "Stamina", "Stamina", "Power", "Wit"], 16750),
            row("b4", 995, 970, 1010, 515, 645, ["Speed", "Stamina", "Stamina", "Power", "Wit"], 16450),
        ]

        profiles = learn_expect_attribute_profiles(
            {"expect_attribute": [1200, 1166, 1166, 1166, 1166]},
            speed_heavy_top,
            speed_heavy_top + stamina_heavy,
            default_targets=[1200, 1166, 1166, 1166, 1166],
            min_bucket_size=2,
        )
        keys = expect_attribute_profile_lookup_keys(
            session=speed_heavy_top[0]["learning_metadata"]["session"],
            run_context=speed_heavy_top[0]["run_context"],
            desired_parent_sparks=speed_heavy_top[0]["desired_parent_sparks"],
            distance=speed_heavy_top[0]["skill_profile_distance"],
            deck_quality_bucket=2,
        )

        self.assertIn(keys[0], profiles)
        self.assertIn(keys[3], profiles)
        self.assertEqual(profiles[keys[0]]["sample_count"], 4)
        self.assertEqual(profiles[keys[3]]["sample_count"], 8)


class TuneExpectAttributeTests(unittest.TestCase):
    def _finished_sample(self, stats):
        row = sample("manual", 18000, final_turn=78, action_count=30, race_total=35)
        row["final_stats"] = dict(stats)
        row["sample_weight"] = 1.0
        return row

    def test_tune_expect_attribute_can_decrease(self):
        preset = {"expect_attribute": [1200, 1200, 1200, 1200, 1200]}
        samples = [
            self._finished_sample({"speed": 1100, "stamina": 800, "power": 900, "guts": 600, "wit": 900}),
            self._finished_sample({"speed": 1100, "stamina": 800, "power": 900, "guts": 600, "wit": 900}),
        ]

        result = tune_expect_attribute(preset, samples, samples)

        self.assertLess(result[0], 1200)
        self.assertLess(result[1], 1200)
        self.assertLess(result[3], 1200)

    def test_tune_expect_attribute_respects_minimum_floor(self):
        preset = {
            "expect_attribute": [1200, 1200, 1200, 1200, 1200],
            "expect_attribute_minimum": [1200, 750, 950, 600, 1200],
        }
        samples = [
            self._finished_sample({"speed": 900, "stamina": 650, "power": 850, "guts": 500, "wit": 850}),
            self._finished_sample({"speed": 920, "stamina": 640, "power": 830, "guts": 520, "wit": 870}),
        ]

        result = tune_expect_attribute(preset, samples, samples)

        floor = [1200, 750, 950, 600, 1200]
        self.assertTrue(all(value >= floor[idx] for idx, value in enumerate(result)))
        self.assertLess(result[1], 1200)
        self.assertLess(result[2], 1200)
        self.assertLess(result[3], 1200)

    def test_learn_expect_attribute_profiles_respect_minimum_floor(self):
        rows = [
            self._finished_sample({"speed": 900, "stamina": 650, "power": 850, "guts": 500, "wit": 850}),
            self._finished_sample({"speed": 920, "stamina": 640, "power": 830, "guts": 520, "wit": 870}),
            self._finished_sample({"speed": 910, "stamina": 660, "power": 840, "guts": 510, "wit": 860}),
            self._finished_sample({"speed": 930, "stamina": 670, "power": 860, "guts": 530, "wit": 880}),
        ]

        profiles = learn_expect_attribute_profiles(
            {
                "expect_attribute": [1200, 1200, 1200, 1200, 1200],
                "expect_attribute_minimum": [1200, 750, 950, 600, 1200],
            },
            rows,
            rows,
            default_targets=[1200, 1200, 1200, 1200, 1200],
            min_bucket_size=1,
        )

        self.assertIn("balanced_any", profiles)
        self.assertEqual(profiles["balanced_any"]["expect_attribute"], [1200, 750, 950, 600, 1200])

    def test_tune_stat_value_multiplier_respects_minimum_floor(self):
        preset = {
            "stat_value_multiplier": [0.035, 0.012, 0.03, 0.006, 0.035, 0.01],
            "stat_value_multiplier_minimum": [0.035, 0.012, 0.03, 0.006, 0.035, 0.008],
        }
        rows = [
            self._finished_sample({"speed": 1200, "stamina": 900, "power": 1100, "guts": 700, "wit": 1200, "skill_point": 2000}),
            self._finished_sample({"speed": 1200, "stamina": 900, "power": 1100, "guts": 700, "wit": 1200, "skill_point": 2000}),
        ]

        result = tune_stat_value_multiplier(preset, rows, rows, [900, 650, 800, 500, 900])

        self.assertEqual(result, [0.035, 0.012, 0.03, 0.006, 0.035, 0.0092])

    def test_tune_base_score_respects_minimum_floor(self):
        preset = {
            "base_score": [0.12, -0.02, 0.10, -0.06, 0.12],
            "base_score_minimum": [0.08, -0.04, 0.06, -0.08, 0.10],
        }
        top_dist = {"overall": [{"count": 0}, {"count": 10}, {"count": 0}, {"count": 0}, {"count": 0}]}
        bottom_dist = {"overall": [{"count": 10}, {"count": 0}, {"count": 10}, {"count": 0}, {"count": 10}]}

        result = tune_base_score(preset, top_dist, bottom_dist)

        self.assertGreaterEqual(result[0], 0.08)
        self.assertGreaterEqual(result[2], 0.06)
        self.assertGreaterEqual(result[4], 0.10)

    def test_tune_expect_attribute_moves_up_fast_for_large_gap(self):
        preset = {"expect_attribute": [600, 600, 600, 600, 600]}
        samples = [
            self._finished_sample({"speed": 1200, "stamina": 800, "power": 1000, "guts": 600, "wit": 900}),
        ]

        result = tune_expect_attribute(preset, samples, samples)

        self.assertGreater(result[0], 850)
        self.assertGreater(result[2], 800)


class RaceStyleOverrideLearningTests(unittest.TestCase):
    def test_race_style_overrides_prefer_per_chara_success_profiles(self):
        overrides = learn_race_style_overrides(
            {},
            {
                168: {
                    "preferred_running_style": "late_surger",
                    "preferred_running_style_share": 0.62,
                    "preferred_running_style_by_chara": {
                        "103201": {"style": "pace_chaser", "share": 1.0, "wins": 3},
                        "105901": {"style": "late_surger", "share": 1.0, "wins": 2},
                    },
                    "confidence": 0.52,
                    "win_rate": 0.51,
                }
            },
        )

        self.assertEqual(
            overrides["by_chara"]["103201"]["168"],
            "pace_chaser",
        )
        self.assertEqual(
            overrides["by_chara"]["105901"]["168"],
            "late_surger",
        )
        self.assertEqual(overrides["global"], {})

    def test_race_style_overrides_keep_global_only_for_strong_consensus(self):
        overrides = learn_race_style_overrides(
            {},
            {
                168: {
                    "preferred_running_style": "late_surger",
                    "preferred_running_style_share": 0.78,
                    "preferred_running_style_by_chara": {},
                    "confidence": 0.71,
                    "win_rate": 0.73,
                }
            },
        )

        self.assertEqual(overrides["global"]["168"], "late_surger")


if __name__ == "__main__":
    unittest.main()


class AdaptiveScoreFloorTests(unittest.TestCase):
    """The configured deck-aware floors only ratchet up; an account whose
    careers never reach them must fall back to learning from its own best
    quartile instead of skipping forever."""

    @staticmethod
    def _bot(score, ts, bucket=2):
        return {
            "source": "bot", "status": "finished", "score": score,
            "deck_quality_bucket": bucket, "first_turn": 1, "final_turn": 78,
            "observed_turn_count": 78, "path": f"p{ts}",
        }

    def test_unreachable_floor_adapts_to_account_p75(self):
        from career_bot.learning import adapt_score_floors_to_account
        rows = [self._bot(5000 + i * 500, i) for i in range(12)]
        floor, by_deck, report = adapt_score_floors_to_account(
            rows, 17500.0, {2: 17500.0, 3: 22000.0})
        self.assertTrue(report["applied"])
        self.assertEqual(floor, 9000.0)
        self.assertEqual(by_deck, {2: 9000.0, 3: 9000.0})

    def test_reachable_floor_left_alone(self):
        from career_bot.learning import adapt_score_floors_to_account
        rows = [self._bot(5000 + i * 500, i) for i in range(12)]
        rows.append(self._bot(18000, 99))
        floor, by_deck, report = adapt_score_floors_to_account(
            rows, 17500.0, {2: 17500.0})
        self.assertFalse(report["applied"])
        self.assertEqual(floor, 17500.0)
        self.assertEqual(by_deck, {2: 17500.0})

    def test_sanity_minimum_filters_degenerate_accounts(self):
        from career_bot.learning import adapt_score_floors_to_account
        rows = [self._bot(2000 + i * 100, i) for i in range(12)]
        floor, _by_deck, report = adapt_score_floors_to_account(
            rows, 17500.0, {2: 17500.0})
        self.assertTrue(report["applied"])
        self.assertEqual(floor, 4000.0)

    def test_insufficient_history_or_disabled_no_adaptation(self):
        from career_bot.learning import adapt_score_floors_to_account
        rows = [self._bot(5000, i) for i in range(3)]
        floor, _by_deck, report = adapt_score_floors_to_account(
            rows, 17500.0, {2: 17500.0})
        self.assertFalse(report["applied"])
        self.assertEqual(floor, 17500.0)
        rows = [self._bot(5000 + i * 500, i) for i in range(12)]
        floor, _by_deck, report = adapt_score_floors_to_account(
            rows, 17500.0, {2: 17500.0}, enabled=False)
        self.assertFalse(report["applied"])
        self.assertEqual(floor, 17500.0)
