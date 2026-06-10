# Scenarios

This package contains per-scenario strategy implementations. The bot currently
supports MANT / Trackblazer (`scenario_id=4`).

`base.py` defines the `ScenarioStrategy` interface. `mant.py` implements the
MANT strategy: command scoring, race decisions, item/skill hooks, event choices,
and diagnostic decision summaries.

To add another scenario, create a new scenario module, subclass
`ScenarioStrategy`, register it in the runner dispatch, and add tests for the
scenario-specific command/race flow.

The abstraction exists so future scenarios can be added without rewriting the
runner, but active development should assume MANT unless a new scenario is
explicitly required.
