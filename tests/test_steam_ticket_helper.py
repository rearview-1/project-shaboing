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


def test_login_does_not_retry_tool_start_session_501():
    class FakeSession:
        def __init__(self):
            self.headers = {}

        def close(self):
            return None

    client = uma_client.UmaClient.__new__(uma_client.UmaClient)
    client.session = FakeSession()
    client.has_captured_auth = lambda: True
    client.regen_sid = lambda: None
    client.refresh_cached_account_state = lambda data: None
    calls = []

    def fake_call(endpoint, payload=None, **kwargs):
        calls.append((endpoint, kwargs))
        raise uma_client.ApiCallError(
            "API error 501 on tool/start_session",
            endpoint="tool/start_session",
            result_code=501,
            response_code=501,
        )

    client.call = fake_call

    try:
        client.login(max_retries=3)
    except uma_client.ApiCallError:
        pass
    else:
        raise AssertionError("expected terminal start_session auth error")

    assert len(calls) == 1
    assert calls[0][0] == "tool/start_session"
    assert calls[0][1]["quiet_result_codes"] == {394, 501}
