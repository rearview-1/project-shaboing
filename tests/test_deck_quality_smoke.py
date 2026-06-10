import unittest

from career_bot.deck_quality import (
    DECK_QUALITY_BUCKETS,
    compute_deck_quality_bucket,
    deck_from_career_log,
)


def _card(rarity, lb=0):
    return {"card_id": 1, "rarity": rarity, "lb_level": lb, "type": "speed"}


class ComputeDeckQualityBucketTests(unittest.TestCase):
    def test_premium_ssr_heavy(self):
        deck = [_card("SSR", lb=4) for _ in range(4)] + [_card("SR", lb=2)]
        self.assertEqual(compute_deck_quality_bucket(deck), 3)

    def test_mixed_ssr_sr(self):
        deck = [_card("SSR", lb=2), _card("SSR", lb=1)] + [_card("SR") for _ in range(3)]
        self.assertEqual(compute_deck_quality_bucket(deck), 2)

    def test_sr_heavy(self):
        deck = [_card("SR") for _ in range(4)] + [_card("R")]
        self.assertEqual(compute_deck_quality_bucket(deck), 1)

    def test_r_heavy(self):
        deck = [_card("R") for _ in range(4)] + [_card("SR")]
        self.assertEqual(compute_deck_quality_bucket(deck), 0)

    def test_missing_deck_defaults_to_mixed(self):
        self.assertEqual(compute_deck_quality_bucket(None), 2)
        self.assertEqual(compute_deck_quality_bucket([]), 2)
        self.assertEqual(compute_deck_quality_bucket("not-a-list"), 2)

    def test_bucket_labels_exposed(self):
        self.assertEqual(DECK_QUALITY_BUCKETS[3], "premium_ssr_heavy")
        self.assertEqual(DECK_QUALITY_BUCKETS[0], "r_heavy_or_baseline")


class DeckFromCareerLogTests(unittest.TestCase):
    def test_pulls_from_manifest_first(self):
        deck = [_card("SSR")]
        log = {"manifest": {"deck": deck}, "deck": []}
        self.assertEqual(deck_from_career_log(log), deck)

    def test_falls_back_to_top_level_deck(self):
        deck = [_card("SR")]
        log = {"deck": deck}
        self.assertEqual(deck_from_career_log(log), deck)

    def test_falls_back_to_run_context_support_cards(self):
        deck = [_card("SSR")]
        log = {"run_context": {"support_cards": deck}}
        self.assertEqual(deck_from_career_log(log), deck)

    def test_returns_empty_for_missing(self):
        self.assertEqual(deck_from_career_log({}), [])
        self.assertEqual(deck_from_career_log(None), [])


if __name__ == "__main__":
    unittest.main()
