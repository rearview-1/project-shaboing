from dataclasses import dataclass, field


@dataclass
class Decision:
    action: str
    payload: dict
    reason: str
    understanding: dict = field(default_factory=dict)


class ScenarioStrategy:
    scenario_id = 0

    def next_decision(self, state, preset):
        raise NotImplementedError
