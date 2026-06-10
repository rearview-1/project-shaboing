"""Tests for client-version-stale detection.

Observed failure: bot in an infinite auth-retry loop because
`tool/start_session` kept returning `result_code: 204` with a
`store_url` field. That's this game's "client version is too old,
update at this URL" signal — a TERMINAL error. The retry loop
hammered the server every 3-90 seconds without progress and gave
the user no actionable signal.

Fix: detect the 204+store_url pattern as a non-recoverable error
that surfaces an actionable message pointing to
`SWEEPY_DEFAULT_APP_VER` / `SWEEPY_DEFAULT_RES_VER`, so the bot
stops retrying and the user knows to update.
"""

from unittest.mock import MagicMock, patch

import pytest

import main
from uma_api import client as uma_client


def _make_204_store_url_error(store_url="https://example.com/update.html"):
    text = (
        f'API error 204 on tool/start_session: '
        f'{{"endpoint": "tool/start_session", "response_code": 204, '
        f'"result_code": 204, "data_headers": {{"viewer_id": 1, '
        f'"sid": "<redacted>", "servertime": 1, "result_code": 204, '
        f'"store_url": "{store_url}"}}}}'
    )
    return Exception(text)


def test_detects_204_with_store_url():
    exc = _make_204_store_url_error()
    assert main.is_client_version_stale_error(exc) is True


def test_204_without_store_url_is_not_a_version_stale_signal():
    """A bare 204 (no store_url) is some other transient state, not
    a version-mismatch verdict. Don't latch onto it."""
    exc = Exception(
        'API error 204 on tool/start_session: '
        '{"endpoint": "tool/start_session", "response_code": 204, '
        '"result_code": 204, "data_headers": {"viewer_id": 1, "result_code": 204}}'
    )
    assert main.is_client_version_stale_error(exc) is False


def test_other_codes_are_not_version_stale():
    for code in (394, 501, 391, 709, 202):
        exc = Exception(f"API error {code} on tool/start_session: { {'store_url': 'x'} }")
        assert main.is_client_version_stale_error(exc) is False, (
            f"{code} should not be a version-stale signal"
        )


def test_204_takes_precedence_over_recoverable():
    """Even though we have logic for `501` etc., a 204+store_url must
    short-circuit `is_recoverable_session_error` so the retry path
    doesn't fire."""
    exc = _make_204_store_url_error()
    assert main.is_recoverable_session_error(exc) is False


def test_recoverable_still_works_for_501():
    """Regression: don't break the 501-as-recoverable contract."""
    exc = Exception("API error 501 on tool/start_session")
    assert main.is_recoverable_session_error(exc) is True
    assert main.is_client_version_stale_error(exc) is False


def test_detail_message_mentions_env_vars_and_action():
    exc = _make_204_store_url_error()
    detail = main.client_version_stale_detail(exc)
    # Must point the user at the actionable thing
    assert "SWEEPY_DEFAULT_APP_VER" in detail
    assert "SWEEPY_DEFAULT_RES_VER" in detail
    # And explain why retrying won't help
    assert "Retrying will not help" in detail


def _build_204_test_client():
    """Build a minimal UmaClient stub that simulates a server returning
    204+store_url on every call."""
    client = object.__new__(uma_client.UmaClient)
    client.viewer_id = 209937075503
    client.udid_str = "12345678-1234-1234-1234-1234567890ab"
    client.auth_key_hex = "aa" * 48
    client.steam_id = "76561198371537804"
    client.steam_ticket = "ticket"
    client.device_id = "device-id"
    client.device_name = "System Product Name"
    client.graphics_device = "GPU"
    client.ip_address = "127.0.0.1"
    client.platform_os = "Windows"
    client.locale = "JPN"
    client.app_ver = "1.21.1"
    client.res_ver = "10006200"
    client.unity_ver = "2022.3.62f2"
    client.sid = bytes(16)
    client.api_log = lambda *args, **kwargs: None
    client.auth_bytes = lambda: b""
    client.regen_sid = MagicMock()
    client.common = lambda: {
        "viewer_id": client.viewer_id,
        "device": 4,
        "device_id": client.device_id,
        "device_name": client.device_name,
        "graphics_device_name": client.graphics_device,
        "ip_address": client.ip_address,
        "platform_os_version": client.platform_os,
        "carrier": "",
        "keychain": 0,
        "locale": client.locale,
        "button_info": "",
        "dmm_viewer_id": None,
        "dmm_onetime_token": None,
        "steam_id": client.steam_id,
        "steam_session_ticket": client.steam_ticket,
    }

    viewer_headers = []

    class FakeResponse:
        status_code = 200
        text = "packed"

    class FakeSession:
        def __init__(self):
            self.headers = {}

        def post(self, url, data=None, headers=None, timeout=None):
            viewer_headers.append(str((headers or {}).get("ViewerID") or ""))
            return FakeResponse()

    client.session = FakeSession()
    return client, viewer_headers


def test_uma_client_surfaces_tool_start_session_204_as_terminal_version_error():
    """When auto-discovery is disabled (or already attempted), 204+store_url
    surfaces as the actionable terminal error."""
    client, viewer_headers = _build_204_test_client()
    # Skip auto-discovery for this test so we exercise the terminal-error
    # path directly. The auto-discovery flow has its own test below.
    client._attempted_version_autodiscovery = True

    response = {
        "response_code": 204,
        "data_headers": {
            "viewer_id": 4665295244463,
            "sid": "<redacted>",
            "servertime": 1780568619,
            "result_code": 204,
            "store_url": "https://example.com/auto_build2/update.html",
        },
    }

    with patch.object(uma_client, "pack", return_value=b"body"), \
         patch.object(uma_client, "get_raw_udid", return_value=b"udid"), \
         patch.object(uma_client, "unpack", return_value=response):
        with pytest.raises(uma_client.ApiCallError) as caught:
            uma_client.UmaClient.call(client, "tool/start_session", {"attestation_type": 0, "device_token": None})

    message = str(caught.value)
    assert "API error 204 on tool/start_session" in message
    assert "game client version metadata is stale" in message
    assert "SWEEPY_DEFAULT_APP_VER" in message
    assert "SWEEPY_DEFAULT_RES_VER" in message
    assert "APP-VER=1.21.1" in message
    assert "RES-VER=10006200" in message
    assert client.viewer_id == 209937075503
    assert viewer_headers == ["209937075503"]
    client.regen_sid.assert_not_called()


def test_uma_client_attempts_autodiscovery_on_204_store_url():
    """When auto-discovery hasn't run yet, 204+store_url triggers a probe
    pass before the terminal error fires. If all probes also return 204,
    the terminal error still surfaces — but the client should have
    attempted multiple version candidates."""
    client, viewer_headers = _build_204_test_client()
    # Auto-discovery NOT pre-flagged → should fire.

    response = {
        "response_code": 204,
        "data_headers": {
            "viewer_id": 4665295244463,
            "sid": "<redacted>",
            "servertime": 1780568619,
            "result_code": 204,
            "store_url": "https://example.com/auto_build2/update.html",
        },
    }

    # Make the sleep in auto-discovery a no-op so the test stays fast
    with patch.object(uma_client, "pack", return_value=b"body"), \
         patch.object(uma_client, "get_raw_udid", return_value=b"udid"), \
         patch.object(uma_client, "unpack", return_value=response), \
         patch.object(uma_client.time, "sleep"):
        with pytest.raises(uma_client.ApiCallError):
            uma_client.UmaClient.call(client, "tool/start_session", {"attestation_type": 0, "device_token": None})

    # Auto-discovery should have been attempted: more than just the initial
    # request (12 candidates → 13 total POSTs).
    assert len(viewer_headers) > 1, (
        f"Expected auto-discovery to make additional probes; "
        f"only saw {len(viewer_headers)} POST(s)"
    )
    # The flag must be set so we don't loop forever on subsequent calls
    assert client._attempted_version_autodiscovery is True
    # After all probes fail, original versions must be restored
    assert client.app_ver == "1.21.1"
    assert client.res_ver == "10006200"
