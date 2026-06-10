import subprocess
from unittest.mock import patch

from uma_api import client as uma_client


def test_get_ticket_timeout_is_concise_and_uses_explicit_appid():
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"))

    with patch.object(uma_client, "check_deps", return_value=None), patch(
        "uma_api.client.subprocess.run", side_effect=fake_run
    ):
        try:
            uma_client.get_ticket("user", "pass", appid=3224770)
        except Exception as exc:
            message = str(exc)
        else:
            raise AssertionError("expected get_ticket timeout")

    assert "Steam ticket generation timed out" in message
    assert "appid 3224770" in message
    assert "CONST STEAMUSER" not in message.upper()
    assert "--appid" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("--appid") + 1] == "3224770"
