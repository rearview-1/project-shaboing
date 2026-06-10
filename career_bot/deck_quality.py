"""Deck quality bucketing.

Premium SSR-heavy decks score systematically higher than R-heavy decks
regardless of execution quality. Stratifying samples by deck quality
during learning prevents the bot from "learning" that good plays mean
high scores when really it's the SSR decks doing the work.

Buckets:
  3 = premium_ssr_heavy   (>=4 SSRs and avg LB >= 3)
  2 = mixed_ssr_sr        (>=2 SSRs)
  1 = sr_heavy            (>=3 SRs and <=1 R)
  0 = r_heavy_or_baseline (anything else)
"""


DECK_QUALITY_BUCKETS = {
    3: "premium_ssr_heavy",
    2: "mixed_ssr_sr",
    1: "sr_heavy",
    0: "r_heavy_or_baseline",
}


def compute_deck_quality_bucket(deck):
    """Return an integer bucket (0-3) for a deck.

    Defaults to bucket 2 when the deck data is missing or malformed —
    "I don't know, assume average" rather than "no deck means baseline".
    """
    if not isinstance(deck, list) or not deck:
        return 2
    valid_cards = [c for c in deck if isinstance(c, dict)]
    if not valid_cards:
        return 2

    def rarity_of(card):
        return str(card.get("rarity", "")).upper()

    ssr_count = sum(1 for c in valid_cards if rarity_of(c) == "SSR")
    sr_count = sum(1 for c in valid_cards if rarity_of(c) == "SR")
    r_count = sum(1 for c in valid_cards if rarity_of(c) == "R")
    lb_levels = []
    for c in valid_cards:
        try:
            lb_levels.append(int(c.get("lb_level", 0) or 0))
        except (TypeError, ValueError):
            lb_levels.append(0)
    avg_lb = sum(lb_levels) / len(lb_levels) if lb_levels else 0

    if ssr_count >= 4 and avg_lb >= 3:
        return 3
    if ssr_count >= 2:
        return 2
    if sr_count >= 3 and r_count <= 1:
        return 1
    return 0


def deck_from_career_log(career_log):
    """Pull the deck list out of a career log.

    Looks in manifest.deck (hachimi capture layout) first, then top-level
    deck (older bot logs). Returns [] if nothing usable is found —
    `compute_deck_quality_bucket` handles that gracefully.
    """
    if not isinstance(career_log, dict):
        return []
    manifest = career_log.get("manifest") or {}
    deck = manifest.get("deck") or career_log.get("deck") or []
    if not deck:
        ctx = career_log.get("run_context") or {}
        deck = ctx.get("support_cards") or []
    return deck if isinstance(deck, list) else []
