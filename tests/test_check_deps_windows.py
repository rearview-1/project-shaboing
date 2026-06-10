"""Tests for `check_deps()` Windows-compat behavior.

Observed failure: on Windows, `subprocess.run(['npm', ...])` fails with
`[WinError 2] The system cannot find the file specified` because `npm`
is a `.cmd` shim and the Win32 process loader looks for an `.exe`.
The fix resolves `npm` via `shutil.which()` (gets the full `.cmd` path)
and falls back to `shell=True` if even that fails.

These tests guard against a future refactor that "cleans up" the
shim-resolution logic and silently breaks fresh-install bootstrap
again.
"""
from unittest.mock import MagicMock, patch

import pytest

from uma_api import client as uma_client


def test_check_deps_raises_helpful_message_when_node_missing(tmp_path, monkeypatch):
    """When `node` isn't on PATH, the error should tell the user where
    to get it."""
    monkeypatch.setattr(uma_client, "DIR", str(tmp_path))
    with patch.object(uma_client.shutil, "which", return_value=None):
        with pytest.raises(Exception) as caught:
            uma_client.check_deps()
    assert "node" in str(caught.value).lower()
    assert "PATH" in str(caught.value) or "nodejs" in str(caught.value)


def test_check_deps_skips_install_when_node_modules_exists(tmp_path, monkeypatch):
    """If `node_modules` already exists, no subprocess should fire — the
    install step is gated on that."""
    monkeypatch.setattr(uma_client, "DIR", str(tmp_path))
    (tmp_path / "node_modules").mkdir()
    fake_run = MagicMock()
    with patch.object(uma_client.shutil, "which", return_value="C:\\node\\node.exe"), \
         patch.object(uma_client.subprocess, "run", fake_run):
        uma_client.check_deps()
    fake_run.assert_not_called()


def test_check_deps_uses_resolved_npm_path_not_bare_string(tmp_path, monkeypatch):
    """Critical: must call subprocess.run with the FULL resolved path to
    npm.cmd, NOT the bare string 'npm'. Calling with bare 'npm' is what
    triggers WinError 2 on Windows."""
    monkeypatch.setattr(uma_client, "DIR", str(tmp_path))
    # Don't create node_modules → install path fires

    def fake_which(name):
        if name == "node":
            return "C:\\Program Files\\nodejs\\node.exe"
        if name == "npm":
            return "C:\\Program Files\\nodejs\\npm.cmd"
        return None

    fake_run = MagicMock()
    with patch.object(uma_client.shutil, "which", side_effect=fake_which), \
         patch.object(uma_client.subprocess, "run", fake_run):
        uma_client.check_deps()

    fake_run.assert_called_once()
    call_args = fake_run.call_args
    # First positional arg is the command list
    cmd = call_args.args[0] if call_args.args else call_args.kwargs.get("args")
    assert isinstance(cmd, list), f"Expected list cmd, got {type(cmd).__name__}: {cmd}"
    # MUST be the resolved .cmd path, not the bare 'npm' string
    assert cmd[0] == "C:\\Program Files\\nodejs\\npm.cmd", (
        f"Expected resolved npm.cmd path; got {cmd[0]!r}. "
        f"Calling with bare 'npm' triggers WinError 2 on Windows."
    )
    assert "install" in cmd, f"Expected 'install' in cmd; got {cmd}"


def test_check_deps_raises_helpful_message_when_npm_missing(tmp_path, monkeypatch):
    """If `node` is found but `npm` isn't (broken/partial Node install),
    surface a clear message instead of WinError 2."""
    monkeypatch.setattr(uma_client, "DIR", str(tmp_path))

    def fake_which(name):
        if name == "node":
            return "C:\\Program Files\\nodejs\\node.exe"
        return None  # npm missing

    with patch.object(uma_client.shutil, "which", side_effect=fake_which):
        with pytest.raises(Exception) as caught:
            uma_client.check_deps()
    assert "npm" in str(caught.value).lower()


def test_check_deps_falls_back_to_shell_on_filenotfound(tmp_path, monkeypatch):
    """If even the resolved-path call somehow throws FileNotFoundError
    (e.g., npm.cmd was deleted between which() and run()), fall back to
    shell=True so cmd.exe can resolve."""
    monkeypatch.setattr(uma_client, "DIR", str(tmp_path))

    def fake_which(name):
        if name == "node":
            return "C:\\Program Files\\nodejs\\node.exe"
        if name == "npm":
            return "C:\\Program Files\\nodejs\\npm.cmd"
        return None

    # First call raises, second call (shell=True fallback) succeeds
    fake_run = MagicMock(side_effect=[FileNotFoundError(2, "missing"), None])
    with patch.object(uma_client.shutil, "which", side_effect=fake_which), \
         patch.object(uma_client.subprocess, "run", fake_run):
        uma_client.check_deps()  # should not raise

    assert fake_run.call_count == 2
    # Second call must use shell=True
    second_kwargs = fake_run.call_args_list[1].kwargs
    assert second_kwargs.get("shell") is True
