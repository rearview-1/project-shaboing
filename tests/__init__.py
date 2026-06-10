"""Test package init.

Globally disables SkillBuyer cross-career failure persistence so tests do
not write into (or read from) the user's real runtime data file at
uma_runtime/skill_failures.json. Each test that constructs a SkillBuyer
should still see fresh in-memory state.
"""

from career_bot.skills import SkillBuyer

_original_skill_buyer_init = SkillBuyer.__init__


def _patched_skill_buyer_init(self, base_dir, *args, **kwargs):
    self._cross_career_failures_disabled = True
    _original_skill_buyer_init(self, base_dir, *args, **kwargs)


SkillBuyer.__init__ = _patched_skill_buyer_init
