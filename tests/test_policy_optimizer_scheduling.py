"""Cadence tests for the automatic sim-driven policy optimizer."""

import json
import types
import unittest
from pathlib import Path
import tempfile
import subprocess

from career_bot.runner import CareerRunner


def _stub_runner(base_dir):
    stub = types.SimpleNamespace(base_dir=Path(base_dir))
    stub._maybe_schedule_policy_optimizer = (
        CareerRunner._maybe_schedule_policy_optimizer.__get__(stub)
    )
    return stub


class PolicyOptimizerSchedulingTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self._tmp.name) / "instances" / "account_t"
        (self.runtime_root / "learning").mkdir(parents=True)
        self.runner = _stub_runner(self._tmp.name)
        self.spawned = []
        self._orig_popen = subprocess.Popen

        def fake_popen(cmd, **kwargs):
            self.spawned.append(cmd)
            return types.SimpleNamespace(pid=4242)

        subprocess.Popen = fake_popen

    def tearDown(self):
        subprocess.Popen = self._orig_popen
        self._tmp.cleanup()

    def _state(self):
        path = self.runtime_root / "learning" / "policy_optimizer_state.json"
        return json.loads(path.read_text(encoding="utf-8"))

    def test_counts_finished_careers_and_spawns_at_threshold(self):
        preset = {"auto_policy_optimizer_every": 3}
        report = {"status": "finished"}
        for _ in range(2):
            self.runner._maybe_schedule_policy_optimizer(self.runtime_root, preset, report)
        self.assertEqual(self.spawned, [])
        self.assertEqual(self._state()["careers_since_optimize"], 2)

        self.runner._maybe_schedule_policy_optimizer(self.runtime_root, preset, report)
        self.assertEqual(len(self.spawned), 1)
        state = self._state()
        self.assertEqual(state["careers_since_optimize"], 0)
        self.assertEqual(state["running_pid"], 4242)
        cmd = self.spawned[0]
        self.assertIn("--instance", cmd)
        self.assertEqual(cmd[cmd.index("--instance") + 1], "account_t")

    def test_disabled_via_preset_flag(self):
        preset = {"auto_policy_optimizer_enabled": False, "auto_policy_optimizer_every": 2}
        report = {"status": "finished"}
        for _ in range(5):
            self.runner._maybe_schedule_policy_optimizer(self.runtime_root, preset, report)
        self.assertEqual(self.spawned, [])

    def test_non_finished_careers_do_not_count(self):
        preset = {"auto_policy_optimizer_every": 2}
        for _ in range(5):
            self.runner._maybe_schedule_policy_optimizer(self.runtime_root, preset, {"status": "stopped"})
        self.assertEqual(self.spawned, [])


if __name__ == "__main__":
    unittest.main()
