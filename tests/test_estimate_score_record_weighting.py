"""Pins the parent-farming rating tweaks to the scoring formula.

The formula at career_bot/learning.estimate_score is the bot's internal
yardstick for "how good was this career." The weighting was re-tuned so
that clean race records and G1 wins drive the score the way they
actually drive parent quality — previously a 5/2 G1 mixed-loss career
scored only ~25% below an 8/0 clean run.

These tests pin down the new behavior so it doesn't silently regress
back to the old weighting if the formula is touched in future.
"""

import unittest

from career_bot.learning import estimate_score, race_quality_metrics


def _stats(speed=1100, stamina=1100, power=1100, guts=950, wit=1100, skill_point=140, fans=80000):
    """Default stat baseline used by most tests. Kept *under* the 1200
    cap so the multi-stat-cap bonus doesn't bleed into tests that are
    isolating other behavior — tests that need cap-pegged stats pass
    them explicitly."""
    return {
        "speed": speed,
        "stamina": stamina,
        "power": power,
        "guts": guts,
        "wit": wit,
        "skill_point": skill_point,
        "fans": fans,
    }


def _race_quality(g1_wins=0, g1_losses=0, race_total=0, **kwargs):
    base = {
        "g1_wins": g1_wins,
        "g1_losses": g1_losses,
        "race_total": race_total,
        "affinity_overlap_wins": 0,
        "affinity_overlap_g1_wins": 0,
        "global_legacy_overlap_points": 0,
        "epithet_sets_completed": 0,
        "distance_variety": 0,
        "venue_variety": 0,
    }
    base.update(kwargs)
    return base


class CleanRecordRatingTests(unittest.TestCase):
    """A clean, G1-heavy schedule should rate substantially higher than
    the same stat profile with mixed wins/losses — that's the whole
    point of parent-farming."""

    def test_clean_run_beats_mixed_record_by_wide_margin(self):
        stats = _stats()
        mixed_score = estimate_score(
            stats, wins=20, losses=5, status="finished",
            factor_score=500,
            race_quality=_race_quality(g1_wins=5, g1_losses=2, race_total=25),
            factor_quality={"score": 500},
            skill_quality={"spend_score": 150},
        )
        clean_score = estimate_score(
            stats, wins=25, losses=0, status="finished",
            factor_score=500,
            race_quality=_race_quality(g1_wins=8, g1_losses=0, race_total=25),
            factor_quality={"score": 500},
            skill_quality={"spend_score": 150},
        )
        # Pre-tweak the gap was ~25%. New gap should be >50%.
        ratio = clean_score / mixed_score
        self.assertGreater(ratio, 1.50, f"clean/mixed ratio {ratio:.3f} not wide enough")

    def test_perfect_15_plus_race_bonus_dominates_ten_race_clean_bonus(self):
        stats = _stats(speed=1100, stamina=1100, power=1100, guts=900, wit=1100, fans=40000)
        ten_clean = estimate_score(
            stats, wins=10, losses=0, status="finished",
            race_quality=_race_quality(g1_wins=3, g1_losses=0, race_total=10),
        )
        fifteen_clean = estimate_score(
            stats, wins=15, losses=0, status="finished",
            race_quality=_race_quality(g1_wins=3, g1_losses=0, race_total=15),
        )
        # 5 extra wins are +250 (×50), plus +700 from the clean-record
        # ladder step (800 → 1500). Total bump should be ~950.
        gap = fifteen_clean - ten_clean
        self.assertGreater(gap, 800)
        self.assertLess(gap, 1200)


class G1LossPenaltyTests(unittest.TestCase):
    """Multiple G1 losses should compound non-linearly. One G1 loss is
    recoverable; two is bad; three is career-killing."""

    def test_g1_loss_penalty_compounds(self):
        stats = _stats()
        kwargs = dict(
            stats=stats, wins=20, losses=2, status="finished",
            factor_score=500,
        )
        one_loss = estimate_score(
            race_quality=_race_quality(g1_wins=5, g1_losses=1, race_total=22),
            **kwargs,
        )
        two_loss = estimate_score(
            race_quality=_race_quality(g1_wins=5, g1_losses=2, race_total=22),
            **kwargs,
        )
        three_loss = estimate_score(
            race_quality=_race_quality(g1_wins=5, g1_losses=3, race_total=22),
            **kwargs,
        )
        # First G1 loss: -350. Second: -500 more = -850 total. Third:
        # another -500 = -1350 total. So the deltas should grow, not
        # stay constant.
        gap_1_to_2 = one_loss - two_loss
        gap_2_to_3 = two_loss - three_loss
        self.assertGreater(gap_2_to_3, gap_1_to_2 * 0.9,
                           "going from 2 to 3 G1 losses should not be cheaper than 1 to 2")
        # And the third loss should specifically cost at least 400 more.
        self.assertGreater(gap_2_to_3, 400)

    def test_zero_g1_losses_is_meaningfully_better_than_one(self):
        stats = _stats()
        kwargs = dict(
            stats=stats, wins=20, losses=0, status="finished",
            factor_score=500,
        )
        zero_loss = estimate_score(
            race_quality=_race_quality(g1_wins=5, g1_losses=0, race_total=20),
            **kwargs,
        )
        one_loss = estimate_score(
            race_quality=_race_quality(g1_wins=5, g1_losses=1, race_total=21),
            wins=20, losses=1, stats=stats, status="finished", factor_score=500,
        )
        # Even accounting for the +1 race entered, the loss penalty
        # should dominate. Zero-loss should win by at least 700.
        self.assertGreater(zero_loss - one_loss, 700)


class G1WinValueTests(unittest.TestCase):
    """A G1 win should be worth several ordinary race wins."""

    def test_g1_win_worth_more_than_three_regular_wins(self):
        stats = _stats()
        kwargs = dict(stats=stats, losses=0, status="finished")
        baseline = estimate_score(
            wins=10,
            race_quality=_race_quality(g1_wins=2, g1_losses=0, race_total=10),
            **kwargs,
        )
        with_extra_g1 = estimate_score(
            wins=11,
            race_quality=_race_quality(g1_wins=3, g1_losses=0, race_total=11),
            **kwargs,
        )
        with_three_extra_regular = estimate_score(
            wins=13,
            race_quality=_race_quality(g1_wins=2, g1_losses=0, race_total=13),
            **kwargs,
        )
        extra_g1_gain = with_extra_g1 - baseline
        extra_regular_gain = with_three_extra_regular - baseline
        # An added G1 win (220 + 50) should beat three added regular
        # wins (150). The point: G1 wins are the lifeblood of parent
        # compatibility, not just stat-padding extra races.
        self.assertGreater(extra_g1_gain, extra_regular_gain)


class StatCapAndTargetBonusTests(unittest.TestCase):
    """Cap-awareness + target-stat threshold bonuses. The bot should be
    rewarded for putting the target stat into the spark band (1100+)
    and for capping it at 1200, but NOT for "overtraining" beyond cap."""

    def test_overcap_stat_does_not_accrue_more_linear_reward(self):
        below_cap = estimate_score(
            _stats(power=1200), wins=0, losses=0,
            race_quality=_race_quality(),
        )
        over_cap = estimate_score(
            _stats(power=1400), wins=0, losses=0,
            race_quality=_race_quality(),
        )
        # Past 1200, the linear stat reward should freeze. Tiny tolerance
        # for floating-point but no meaningful gain.
        self.assertLess(over_cap - below_cap, 1.0)

    def test_target_stat_at_1100_gets_threshold_bonus(self):
        below = estimate_score(
            _stats(wit=1099), wins=0, losses=0,
            race_quality=_race_quality(),
            parent_goals={"blue": ["Wit"]},
        )
        at_threshold = estimate_score(
            _stats(wit=1100), wins=0, losses=0,
            race_quality=_race_quality(),
            parent_goals={"blue": ["Wit"]},
        )
        # Crossing 1100 on target adds +400 (the threshold bonus) plus
        # ~1 from the linear stat. So the step should be ~400+.
        self.assertGreater(at_threshold - below, 350.0)
        self.assertLess(at_threshold - below, 450.0)

    def test_target_stat_at_cap_gets_full_ladder(self):
        below = estimate_score(
            _stats(wit=1099), wins=0, losses=0,
            race_quality=_race_quality(),
            parent_goals={"blue": ["Wit"]},
        )
        at_cap = estimate_score(
            _stats(wit=1200), wins=0, losses=0,
            race_quality=_race_quality(),
            parent_goals={"blue": ["Wit"]},
        )
        # Crossing 1100 (+400) AND capping (+800) = +1200 of bonus,
        # plus ~117 of linear stat (101 × 1.16). So ~1317.
        gap = at_cap - below
        self.assertGreater(gap, 1100.0)
        self.assertLess(gap, 1500.0)

    def test_threshold_bonus_only_fires_for_target_stat(self):
        with_speed_target = estimate_score(
            _stats(speed=1200, wit=600), wins=0, losses=0,
            race_quality=_race_quality(),
            parent_goals={"blue": ["Speed"]},
        )
        with_wit_target = estimate_score(
            _stats(speed=1200, wit=600), wins=0, losses=0,
            race_quality=_race_quality(),
            parent_goals={"blue": ["Wit"]},
        )
        # Speed is the one actually at cap; only Speed-target gets the
        # +1200 ladder bonus, Wit-target gets nothing (Wit is at 600).
        self.assertGreater(with_speed_target - with_wit_target, 1000.0)

    def test_multi_stat_cap_bonus_compounds(self):
        one_cap = estimate_score(
            _stats(speed=1200, stamina=800, power=800, guts=800, wit=800),
            race_quality=_race_quality(),
        )
        two_caps = estimate_score(
            _stats(speed=1200, stamina=1200, power=800, guts=800, wit=800),
            race_quality=_race_quality(),
        )
        three_caps = estimate_score(
            _stats(speed=1200, stamina=1200, power=1200, guts=800, wit=800),
            race_quality=_race_quality(),
        )
        four_caps = estimate_score(
            _stats(speed=1200, stamina=1200, power=1200, guts=1200, wit=800),
            race_quality=_race_quality(),
        )
        five_caps = estimate_score(
            _stats(speed=1200, stamina=1200, power=1200, guts=1200, wit=1200),
            race_quality=_race_quality(),
        )
        # Each step's marginal bonus should grow non-linearly: 0 → +500
        # → +700 (1200 total) → +1300 (2500) → +2500 (5000).
        # (The linear stat reward adds a fixed contribution per +400
        # stat, so the deltas reflect both stat reward and the cap
        # bonus.)
        d1 = two_caps - one_cap
        d2 = three_caps - two_caps
        d3 = four_caps - three_caps
        d4 = five_caps - four_caps
        # Going from 4 to 5 caps must be a meaningfully bigger jump than
        # going from 2 to 3 caps — that's what "compounding" means.
        self.assertGreater(d4, d2 * 1.5)


class G1MilestoneTests(unittest.TestCase):
    """G1 wins in volume should hit milestone ladders on top of the
    linear per-G1 reward."""

    def test_20_g1_wins_far_better_than_10_of_same_stats(self):
        stats = _stats()
        ten_g1 = estimate_score(
            stats, wins=22, losses=0, status="finished",
            race_quality=_race_quality(g1_wins=10, g1_losses=0, race_total=22),
        )
        twenty_g1 = estimate_score(
            stats, wins=32, losses=0, status="finished",
            race_quality=_race_quality(g1_wins=20, g1_losses=0, race_total=32),
        )
        # 10 extra G1 wins = 2200 (×220). Plus the 10-tier milestone is
        # +800 and the 20-tier is +3500, so the 20-G1 career should add
        # ~2700 of milestone bonus on top of linear. Plus 10 extra wins
        # (×50 = 500) and a perfect-record ladder step (15→30: +3000).
        # Conservative lower bound: gap of at least 5000.
        self.assertGreater(twenty_g1 - ten_g1, 5000.0)


class PerfectRecordAtScaleTests(unittest.TestCase):
    """Sustained perfect records should compound: a 30-race clean run
    is qualitatively rarer than a 15-race clean run."""

    def test_40_race_perfect_beats_15_race_perfect_substantially(self):
        stats = _stats()
        fifteen = estimate_score(
            stats, wins=15, losses=0, status="finished",
            race_quality=_race_quality(g1_wins=5, g1_losses=0, race_total=15),
        )
        forty = estimate_score(
            stats, wins=40, losses=0, status="finished",
            race_quality=_race_quality(g1_wins=5, g1_losses=0, race_total=40),
        )
        # 40-race perfect ladder is +7000; 15-race is +1500. Pure ladder
        # gap = +5500. Plus 25 extra wins × 50 = +1250. Total expected
        # gap ~6750.
        self.assertGreater(forty - fifteen, 6000.0)


class DeferredSkillPurchaseBonusTests(unittest.TestCase):
    """Reward the parent-farming flow: save SP all career, dump skills
    at end_skill_purchase when full information is available, while
    racing clean. The bot should learn this is the optimal pattern."""

    def _quality_with_end_purchase(self, learned, end_bought):
        return {"learned_skill_count": learned, "end_purchase_count": end_bought, "spend_score": 100}

    def test_clean_run_with_deferred_skills_gets_bonus(self):
        stats = _stats()
        kwargs = dict(
            stats=stats, wins=20, losses=0, status="finished",
            race_quality=_race_quality(g1_wins=5, g1_losses=0, race_total=20),
        )
        # 10 skills, ALL bought at end_skill_purchase phase.
        deferred = estimate_score(
            skill_quality=self._quality_with_end_purchase(10, 10),
            **kwargs,
        )
        # 10 skills, NONE bought at the end (i.e. bought throughout).
        spread = estimate_score(
            skill_quality=self._quality_with_end_purchase(10, 0),
            **kwargs,
        )
        # Bonus is +1000 for full deferral.
        self.assertEqual(round(deferred - spread, 0), 1000)

    def test_deferred_skill_bonus_does_not_fire_when_career_had_losses(self):
        """Without a clean record, the bonus shouldn't fire — otherwise
        the bot might learn to skip skills as a shortcut even when
        buying them mid-career would have saved a race."""
        stats = _stats()
        kwargs = dict(
            stats=stats, wins=20, losses=2, status="finished",
            race_quality=_race_quality(g1_wins=5, g1_losses=1, race_total=22),
        )
        deferred = estimate_score(
            skill_quality=self._quality_with_end_purchase(10, 10),
            **kwargs,
        )
        spread = estimate_score(
            skill_quality=self._quality_with_end_purchase(10, 0),
            **kwargs,
        )
        # No deferred bonus because there were losses.
        self.assertEqual(deferred, spread)

    def test_partial_deferral_below_80_percent_does_not_get_bonus(self):
        """Buying 7/10 skills at end isn't enough; the threshold is 80%
        so the bot has to actually commit to the deferred-buying flow."""
        stats = _stats()
        kwargs = dict(
            stats=stats, wins=20, losses=0, status="finished",
            race_quality=_race_quality(g1_wins=5, g1_losses=0, race_total=20),
        )
        almost = estimate_score(
            skill_quality=self._quality_with_end_purchase(10, 7),
            **kwargs,
        )
        baseline = estimate_score(
            skill_quality=self._quality_with_end_purchase(10, 0),
            **kwargs,
        )
        self.assertEqual(almost, baseline)


class RaceWinSkillParsimonyTests(unittest.TestCase):
    """Winning with fewer race-time skills should rate better than
    needing a larger mid-career skill stack to secure the same record."""

    def _races_with_skill_count(self, count, wins=5):
        rows = []
        for idx in range(wins):
            rows.append({
                "turn": 10 + idx,
                "program_id": 11000 + idx,
                "grade": "G1",
                "overlap_race_id": 20000 + idx,
                "result_rank": 1,
                "won": True,
                "skill_count_at_race": count,
            })
        return rows

    def test_cleaner_wins_with_fewer_skills_score_higher(self):
        stats = _stats()
        clean_race_quality = race_quality_metrics(self._races_with_skill_count(0))
        heavy_race_quality = race_quality_metrics(self._races_with_skill_count(4))
        clean = estimate_score(
            stats,
            wins=5,
            losses=0,
            status="finished",
            race_quality=clean_race_quality,
        )
        heavy = estimate_score(
            stats,
            wins=5,
            losses=0,
            status="finished",
            race_quality=heavy_race_quality,
        )
        self.assertGreater(clean_race_quality["skill_parsimony_bonus"], heavy_race_quality["skill_parsimony_bonus"])
        self.assertGreater(clean, heavy)

    def test_c_or_worse_aptitude_races_are_ignored_for_learning_record(self):
        races = [
            {
                "turn": 10,
                "program_id": 11001,
                "terrain": "Turf",
                "distance": "Medium",
                "running_style": 2,
                "grade": "G1",
                "overlap_race_id": 20001,
                "result_rank": 1,
                "won": True,
            },
            {
                "turn": 12,
                "program_id": 11002,
                "terrain": "Turf",
                "distance": "Mile",
                "running_style": 3,
                "grade": "G1",
                "overlap_race_id": 20002,
                "result_rank": 4,
                "won": False,
            },
        ]
        quality = race_quality_metrics(races, sample={"trainee_card_id": 100101})
        self.assertEqual(quality["race_total"], 1)
        self.assertEqual(quality["race_wins"], 1)
        self.assertEqual(quality["race_losses"], 0)
        self.assertEqual(quality["ignored_off_aptitude_races"], 1)
        self.assertEqual(quality["ignored_off_aptitude_losses"], 1)


class DreamCareerTests(unittest.TestCase):
    """End-to-end: the user's described dream career profile (3 capped
    stats including target, 44 perfect races, 24 G1 wins) should rate
    at least 2x a typical career."""

    def test_dream_career_rates_at_least_2x_typical(self):
        # Dream profile.
        dream = estimate_score(
            _stats(speed=1200, stamina=700, power=1200, guts=500, wit=1200, skill_point=140, fans=80000),
            wins=44, losses=0, status="finished",
            factor_score=500,
            race_quality=_race_quality(
                g1_wins=24, g1_losses=0, race_total=44,
                affinity_overlap_wins=12, affinity_overlap_g1_wins=10,
                global_legacy_overlap_points=30, epithet_sets_completed=4,
                distance_variety=4, venue_variety=8,
            ),
            factor_quality={"score": 700},
            skill_quality={"spend_score": 200},
            parent_goals={"blue": ["Wit"]},
        )
        # Typical career.
        typical = estimate_score(
            _stats(speed=1100, stamina=1100, power=1100, guts=900, wit=1100, skill_point=140, fans=50000),
            wins=22, losses=0, status="finished",
            factor_score=400,
            race_quality=_race_quality(
                g1_wins=5, g1_losses=0, race_total=22,
                affinity_overlap_wins=4, affinity_overlap_g1_wins=2,
                global_legacy_overlap_points=12, epithet_sets_completed=1,
                distance_variety=3, venue_variety=5,
            ),
            factor_quality={"score": 500},
            skill_quality={"spend_score": 150},
            parent_goals={"blue": ["Wit"]},
        )
        self.assertGreater(dream / typical, 2.0,
                           f"dream/typical ratio {dream/typical:.3f} should be >2x")


if __name__ == "__main__":
    unittest.main()
