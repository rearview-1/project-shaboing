import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from career_bot.learning import collect_samples, factor_quality_metrics, race_quality_metrics, white_spark_rank_diagnostic
from career_bot.parent_memory import annotate_parents, load_registry, remember_bot_career, write_parent_library_snapshot


class ParentMemoryLearningSmokeTests(unittest.TestCase):
    def test_bot_parent_is_tagged_after_completed_career_matches_new_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp) / "project"
            base_dir.mkdir()
            report = {
                "started_at": "2026-05-14T12:00:00",
                "ended_at": "2026-05-14T12:30:00",
                "preset_name": "xguri parent",
                "status": "finished",
                "final_turn": 78,
                "run_context": {
                    "preset_name": "xguri parent",
                    "deck_id": 4,
                    "deck_name": "Parent Run",
                    "trainee_card_id": 100101,
                    "parent_id_1": 9001,
                    "parent_id_2": 9002,
                    "desired_parent_sparks": {"blue": ["Stamina"], "pink": [], "green": [], "white": []},
                },
                "turns": [
                    {
                        "turn": 78,
                        "stats": {"speed": 1000, "stamina": 800, "power": 900, "guts": 500, "wit": 850, "skill_point": 40},
                    }
                ],
            }

            result = remember_bot_career(base_dir, report, career_log="career_log_test.json")
            self.assertTrue(result["pending"])

            parents = [{
                "instance_id": 12345,
                "card_id": 100101,
                "name": "Test Uma",
                "is_new": True,
                "stats": {"speed": 1000, "stamina": 800, "power": 900, "guts": 500, "wit": 850},
                "tree": {"self": {"factors": [], "race_history": []}},
            }]
            annotated = annotate_parents(base_dir, parents)

            self.assertTrue(annotated[0]["made_by_bot"])
            self.assertIn("BOT", annotated[0]["source_tags"])
            self.assertEqual(annotated[0]["bot_parent_info"]["deck_name"], "Parent Run")
            self.assertFalse(load_registry(base_dir)["pending_bot_careers"])

    def test_desired_spark_goals_raise_factor_quality_score(self):
        factors = {"factor_id_array": [203, 3303, 1000703]}
        plain = factor_quality_metrics(factors)
        targeted = factor_quality_metrics(
            factors,
            parent_goals={"blue": ["Stamina"], "pink": ["Medium"], "white": ["NHK Mile C."]},
        )

        self.assertGreater(targeted["score"], plain["score"])
        self.assertEqual(targeted["desired_three_star_hits"]["blue"], 1)
        self.assertEqual(targeted["desired_three_star_hits"]["pink"], 1)
        self.assertEqual(targeted["desired_three_star_hits"]["white"], 1)
        self.assertEqual(targeted["white_3_count"], 1)

    def test_parent_library_snapshot_becomes_learning_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp) / "project"
            base_dir.mkdir()
            parent = {
                "instance_id": 222,
                "card_id": 100101,
                "name": "Manual Parent",
                "score": 17620,
                "stats": {"speed": 1051, "stamina": 735, "power": 1068, "guts": 609, "wit": 1182},
                "tree": {
                    "self": {
                        "factors": [{"id": 203, "name": "Stamina", "stars": 3, "category": "stat"}],
                        "race_history": [{"turn": 20, "program_id": 629, "result_rank": 1, "grade": "G3"}],
                    }
                },
            }
            write_parent_library_snapshot(base_dir, [parent])

            samples = collect_samples(base_dir, parent_goals={"blue": ["Stamina"]})

            self.assertEqual(len(samples), 1)
            self.assertEqual(samples[0]["source"], "user_parent_library")
            self.assertEqual(samples[0]["parent_instance_id"], 222)
            self.assertEqual(samples[0]["factor_quality"]["desired_three_star_hits"]["blue"], 1)

    def test_collect_samples_reads_shared_runtime_parent_libraries(self):
        with tempfile.TemporaryDirectory() as tmp:
            base_dir = Path(tmp) / "project"
            base_dir.mkdir()
            current_runtime = Path(tmp) / "runtimes" / "account_a"
            shared_runtime = Path(tmp) / "runtimes" / "account_b"
            current_runtime.mkdir(parents=True)
            shared_runtime.mkdir(parents=True)

            current_parent = {
                "instance_id": 1001,
                "card_id": 100101,
                "name": "Current Parent",
                "score": 17000,
                "stats": {"speed": 950, "stamina": 800, "power": 900, "guts": 500, "wit": 700},
                "tree": {"self": {"factors": [], "race_history": []}},
            }
            shared_parent = {
                "instance_id": 2002,
                "card_id": 100201,
                "name": "Shared Parent",
                "score": 18200,
                "stats": {"speed": 1000, "stamina": 820, "power": 980, "guts": 520, "wit": 760},
                "tree": {"self": {"factors": [], "race_history": []}},
            }

            with patch.dict("os.environ", {"UMA_RUNTIME_DIR": str(current_runtime)}, clear=False):
                write_parent_library_snapshot(base_dir, [current_parent])
            with patch.dict("os.environ", {"UMA_RUNTIME_DIR": str(shared_runtime)}, clear=False):
                write_parent_library_snapshot(base_dir, [shared_parent])

            with patch.dict(
                "os.environ",
                {
                    "UMA_RUNTIME_DIR": str(current_runtime),
                    "SWEEPY_SHARED_RUNTIME_PATHS": str(shared_runtime),
                },
                clear=False,
            ):
                samples = collect_samples(base_dir)

            sample_paths = {str(sample.get("path") or "") for sample in samples}
            self.assertEqual(len(samples), 2)
            self.assertTrue(any(str(current_runtime) in path for path in sample_paths))
            self.assertTrue(any(str(shared_runtime) in path for path in sample_paths))
            self.assertEqual({sample["parent_instance_id"] for sample in samples}, {1001, 2002})
            self.assertEqual(
                {str(sample.get("runtime_root") or "") for sample in samples},
                {str(current_runtime.resolve()), str(shared_runtime.resolve())},
            )

    def test_global_legacy_race_quality_counts_g2_g3_overlap_points_once(self):
        races = [
            {"overlap_race_id": 100101, "grade": "G1", "result_rank": 1, "won": True},
            {"overlap_race_id": 100101, "grade": "G1", "result_rank": 1, "won": True},
            {"overlap_race_id": 200101, "grade": "G2", "result_rank": 1, "won": True},
            {"overlap_race_id": 300101, "grade": "G3", "result_rank": 1, "won": True},
        ]

        quality = race_quality_metrics(races)

        self.assertIn("G2", quality["global_legacy_overlap_grades"])
        self.assertIn("G3", quality["global_legacy_overlap_grades"])
        self.assertEqual(quality["affinity_overlap_wins"], 4)
        self.assertEqual(quality["global_legacy_overlap_points"], 3)

    def test_white_spark_rank_diagnostic_compares_parent_rank_groups(self):
        samples = [
            {
                "source": "user_parent_library",
                "rank": 8,
                "rank_label": "A",
                "rank_score": 12000,
                "white_metrics": {"white_count": 2, "white_3_count": 0, "white_star_total": 3},
            },
            {
                "source": "user_parent_library",
                "rank": 12,
                "rank_label": "SS",
                "rank_score": 17620,
                "white_metrics": {"white_count": 7, "white_3_count": 1, "white_star_total": 12},
            },
            {
                "source": "bot_parent_library",
                "made_by_bot": True,
                "rank": 12,
                "rank_label": "SS",
                "rank_score": 18100,
                "white_metrics": {"white_count": 5, "white_3_count": 1, "white_star_total": 10},
            },
        ]

        diagnostic = white_spark_rank_diagnostic(samples)

        self.assertEqual(diagnostic["rank_group_count"], 2)
        self.assertEqual(diagnostic["best_avg_white_count"]["rank_label"], "SS")
        self.assertEqual(diagnostic["best_avg_3_star_white_count"]["rank_label"], "SS")
        self.assertIn("guide_prior", diagnostic)


if __name__ == "__main__":
    unittest.main()
