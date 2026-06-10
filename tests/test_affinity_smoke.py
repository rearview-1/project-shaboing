import unittest

from career_bot.affinity import (
    compute_career_affinity,
    compute_lineage_counts_for_sparks,
)


class ComputeCareerAffinityTests(unittest.TestCase):
    def test_handles_missing_log(self):
        result = compute_career_affinity(None)
        self.assertEqual(result["total"], 0)

    def test_sums_all_three_components(self):
        log = {
            "final_summary": {
                "base_affinity": 5,
                "race_history": [
                    {"granted_epithet": True},
                    {"granted_epithet": False},
                    {"granted_epithet": True},
                ],
                "grandparents": [
                    {"g1_wins": 3},
                    {"g1_wins": 2},
                ],
            }
        }
        result = compute_career_affinity(log)
        self.assertEqual(result["base_affinity"], 5)
        self.assertEqual(result["race_epithets_count"], 2)
        self.assertEqual(result["grandparent_g1_wins"], 5)
        self.assertEqual(result["total"], 12)

    def test_malformed_subfields_treated_as_zero(self):
        log = {"final_summary": {"base_affinity": "garbage", "race_history": "not-a-list"}}
        result = compute_career_affinity(log)
        self.assertEqual(result["base_affinity"], 0)
        self.assertEqual(result["race_epithets_count"], 0)
        self.assertEqual(result["total"], 0)


class ComputeLineageCountsForSparksTests(unittest.TestCase):
    def test_counts_matches_across_lineage(self):
        sparks = [
            {"name": "Stamina"},
            {"name": "Front Runner"},
            {"name": "Concentration"},
        ]
        lineage = {
            "parent_1": {"sparks": [{"name": "Stamina"}, {"name": "Front Runner"}]},
            "parent_2": {"sparks": [{"name": "Stamina"}]},
            "grandparent_p1_1": {"sparks": [{"name": "Front Runner"}]},
        }
        counts = compute_lineage_counts_for_sparks(sparks, lineage)
        self.assertEqual(counts["stamina"], 2)
        self.assertEqual(counts["front runner"], 2)
        self.assertEqual(counts["concentration"], 0)

    def test_handles_missing_inputs(self):
        self.assertEqual(compute_lineage_counts_for_sparks(None, {}), {})
        self.assertEqual(compute_lineage_counts_for_sparks([], None), {})


if __name__ == "__main__":
    unittest.main()
