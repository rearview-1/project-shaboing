# Changelog

## Unreleased

- Phase 9: `resolve_expect_attribute` call sites now pass style, distance,
  deck, run-context, and spark-goal context so learned stat-target profiles are
  reachable during MANT scoring and training-policy feature extraction.
- Phase 10: Per-decision action weighting no longer multiplies decision quality
  through the full career-level weight, preserving strong turn-level decisions
  from otherwise mediocre runs.
- Phase 11: Event-choice learning classifies historical choices by each
  career's recorded spark goal instead of the current preset's spark goal.
- Phase 12: `expect_attribute` tuning can drift targets downward when observed
  high-quality parents support lower realistic targets.
- Phase 13: Stamina training scoring now uses style, distance, and planned
  recovery demand instead of fixed Oguri-tuned style multipliers.
- Phase 17: New career logs are tagged with `sweepy_career_log_v1`.
- Phase 24: Training decisions now score and log facility level-up state, and
  the training policy model receives facility level/progress features.
