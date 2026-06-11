"""Tests for the auto-discovery probe path that fires when the game
server returns 204+store_url on tool/start_session.

The candidate generator orders probes by likelihood so the first
successful start_session uses the most plausible new version. Cygames
historically bumps res_ver in 100-step increments and bumps app_ver in
patch/minor moves — the candidate order should reflect that.
"""
from contextlib import contextmanager
from unittest.mock import patch

from uma_api.client import (
    discover_version_candidates_from_store_url,
    extract_version_candidates_from_text,
    generate_version_candidates,
    is_client_version_stale_response,
)


@contextmanager
def no_external_version_sources():
    with patch("uma_api.client.read_client_version_cache", return_value={}), \
         patch("uma_api.client.discover_version_candidates_from_store_url", return_value=[]):
        yield


# -------------------- candidate generator --------------------

def test_candidates_start_with_res_ver_bumps():
    """First several candidates should be same app_ver, incrementing
    res_ver — Cygames most often bumps res_ver alone."""
    with no_external_version_sources():
        out = generate_version_candidates("1.22.0", "10006300")
    assert len(out) >= 5
    # First 5 should all have app_ver == "1.22.0"
    for app, _ in out[:5]:
        assert app == "1.22.0"
    # res_ver should be strictly increasing in the res-only block
    res_vals = [int(r) for _, r in out[:5]]
    assert res_vals == sorted(res_vals)
    # First bump should be +100 (most common Cygames step)
    assert res_vals[0] == 10006400


def test_candidates_include_patch_bumps():
    """After res_ver-only candidates, app_ver patch bumps should appear."""
    with no_external_version_sources():
        out = generate_version_candidates("1.22.0", "10006300")
    patch_bumps = [(a, r) for a, r in out if a == "1.22.1"]
    assert patch_bumps, "Expected at least one 1.22.1 candidate"


def test_candidates_include_minor_bumps():
    """And minor bumps last."""
    with no_external_version_sources():
        out = generate_version_candidates("1.22.0", "10006300")
    minor_bumps = [(a, r) for a, r in out if a == "1.23.0"]
    assert minor_bumps, "Expected at least one 1.23.0 candidate"


def test_candidates_deduplicated():
    """Generator should not emit duplicate (app, res) pairs."""
    with no_external_version_sources():
        out = generate_version_candidates("1.22.0", "10006300")
    assert len(out) == len(set(out)), f"Duplicates in {out}"


def test_candidates_respect_max():
    """Caller can cap the probe budget."""
    with no_external_version_sources():
        out = generate_version_candidates("1.22.0", "10006300", max_candidates=3)
    assert len(out) == 3


def test_candidates_try_cached_live_version_first():
    """Accepted discovery cache must beat stale auth-profile versions."""
    with patch(
        "uma_api.client.read_client_version_cache",
        return_value={"app_ver": "1.23.0", "res_ver": "10006600"},
    ):
        out = generate_version_candidates("1.22.0", "10006300", max_candidates=5, steam_app_id="3224770")

    assert out[0] == ("1.23.0", "10006600")


def test_candidates_try_store_url_versions_before_guesses():
    """If the update page exposes exact metadata, try it before blind bumps."""
    with patch(
        "uma_api.client.discover_version_candidates_from_store_url",
        return_value=[("1.24.0", "10007100")],
    ), patch("uma_api.client.read_client_version_cache", return_value={}):
        out = generate_version_candidates(
            "1.22.0",
            "10006300",
            max_candidates=5,
            store_url="https://example.com/auto_build2/update.html",
        )

    assert out[0] == ("1.24.0", "10007100")


def test_candidates_handle_invalid_input_gracefully():
    """Malformed app/res input should never make candidate generation raise."""
    with no_external_version_sources():
        out_junk_res = generate_version_candidates("1.22.0", "not-a-number")
        assert isinstance(out_junk_res, list) and len(out_junk_res) > 0

        out_junk_app = generate_version_candidates("not.a.version", "10006300")
        assert any("not.a.version" in str(a) or a != "" for a, _ in out_junk_app)

        out_both_junk = generate_version_candidates("", "")
        assert isinstance(out_both_junk, list)


def test_extract_version_candidates_from_launcher_text():
    text = """
    window.__client = {
      app_ver: "1.24.1",
      resource_version: "10007100",
      "APP-VER": "1.24.1",
      "RES-VER": "10007100"
    };
    """

    assert ("1.24.1", "10007100") in extract_version_candidates_from_text(text)


def test_store_url_probe_follows_script_refs():
    class Response:
        def __init__(self, text):
            self.status_code = 200
            self.text = text

    calls = []

    def fake_get(url, **_kwargs):
        calls.append(url)
        if url.endswith("update.html"):
            return Response('<script src="assets/client.js"></script>')
        return Response('const app_ver="1.24.1"; const res_ver="10007100";')

    with patch("uma_api.client.requests.get", side_effect=fake_get):
        out = discover_version_candidates_from_store_url("https://example.com/auto_build2/update.html")

    assert ("1.24.1", "10007100") in out
    assert calls == [
        "https://example.com/auto_build2/update.html",
        "https://example.com/auto_build2/assets/client.js",
    ]


# -------------------- stale-response detection --------------------

def test_stale_detection_requires_start_session_endpoint():
    """The 204+store_url signal only counts on tool/start_session, not
    on other endpoints (which use 204 for different reasons)."""
    headers = {"store_url": "https://example.com/update"}
    res = {"data_headers": headers}
    assert is_client_version_stale_response("tool/start_session", 204, res) is True
    # Same payload on a different endpoint should not trigger
    assert is_client_version_stale_response("single_mode/start", 204, res) is False


def test_stale_detection_requires_store_url():
    """A 204 without store_url is some other transient — don't treat it
    as version-stale (the auto-discovery would waste probes)."""
    res = {"data_headers": {"viewer_id": 12345}}
    assert is_client_version_stale_response("tool/start_session", 204, res) is False


def test_stale_detection_ignores_non_204():
    """Only result_code 204 triggers."""
    headers = {"store_url": "https://example.com/update"}
    res = {"data_headers": headers}
    for code in (0, 200, 214, 394, 501, 709):
        assert is_client_version_stale_response("tool/start_session", code, res) is False


def test_candidate_ordering_res_bumps_before_app_bumps():
    """The whole point of the priority order is that the most common
    Cygames change (res_ver bump) gets probed first. If this order
    breaks, probe latency on real failures gets much worse."""
    with no_external_version_sources():
        out = generate_version_candidates("1.22.0", "10006300")
    # Index of first res-only bump (app_ver unchanged)
    first_res_only = next(
        (i for i, (a, _) in enumerate(out) if a == "1.22.0"),
        None,
    )
    # Index of first app patch bump
    first_patch = next(
        (i for i, (a, _) in enumerate(out) if a == "1.22.1"),
        None,
    )
    assert first_res_only is not None and first_patch is not None
    assert first_res_only < first_patch, (
        "res_ver-only bumps must be probed BEFORE app_ver patch bumps"
    )
