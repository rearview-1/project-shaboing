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

    def test_root_runtime_does_not_spawn_invalid_instance_job(self):
        root_runtime = Path(self._tmp.name) / "uma_runtime"
        (root_runtime / "learning").mkdir(parents=True)
        preset = {"auto_policy_optimizer_every": 2}

        for _ in range(3):
            self.runner._maybe_schedule_policy_optimizer(root_runtime, preset, {"status": "finished"})

        self.assertEqual(self.spawned, [])
        self.assertFalse((root_runtime / "learning" / "policy_optimizer_state.json").exists())


if __name__ == "__main__":
    unittest.main()


class AutoLearningSubprocessTests(unittest.TestCase):
    """The runner prefers learning in a fresh subprocess (current code on
    disk) and only falls back in-process when spawning fails."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.runtime_root = Path(self._tmp.name) / "instances" / "account_t"
        (self.runtime_root / "learning").mkdir(parents=True)
        self.runner = _stub_runner(self._tmp.name)
        self.runner._run_auto_learning_subprocess = (
            CareerRunner._run_auto_learning_subprocess.__get__(self.runner)
        )
        self.calls = []
        self._orig_run = subprocess.run

        def fake_run(cmd, **kwargs):
            self.calls.append((cmd, kwargs))
            return types.SimpleNamespace(returncode=self._rc)

        subprocess.run = fake_run
        self._rc = 0

    def tearDown(self):
        subprocess.run = self._orig_run
        self._tmp.cleanup()

    def _invoke(self):
        return self.runner._run_auto_learning_subprocess(
            self.runtime_root,
            {"name": "p", "auto_learning_enabled": True},
            {"status": "finished"},
            Path(self._tmp.name) / "career_log_x.json",
        )

    def test_successful_subprocess_handles_learning(self):
        self.assertTrue(self._invoke())
        cmd, kwargs = self.calls[0]
        self.assertIn("run_auto_learning_once.py", str(cmd[1]))
        self.assertIn("--outcomes-path", cmd)
        self.assertEqual(kwargs["env"].get("PYTHONUTF8"), "1")
        # Snapshot temp file is cleaned up after the run.
        leftovers = list((self.runtime_root / "learning" / "preset_snapshots").glob("*.json"))
        self.assertEqual(leftovers, [])

    def test_tool_error_rc1_does_not_double_run(self):
        self._rc = 1
        self.assertTrue(self._invoke())

    def test_setup_failure_rc2_falls_back(self):
        self._rc = 2
        self.assertFalse(self._invoke())
