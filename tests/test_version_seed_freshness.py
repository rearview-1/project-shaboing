"""Tests for the version-seed bootstrap path in main.best_known_headless_auth_seed.

Observed failure: a fresh install (or re-install) has dev_session.json with
SENTINEL placeholder values (app_ver="1.0.0", res_ver="2", steam_id="steam-restore",
viewer_id=123456, etc.). The bot was reading these as if they were real config and
seeding the client with them — every tool/start_session then 204'd because the
"versions" 1.0.0/2 obviously don't match the live game build.

Separate failure: a user updates the bot code (newer hardcoded app_ver default in
main.py) but their cached dev_session.json keeps the OLD version. The cache wins
over the new default, so the bot uses stale versions and 204s.

Both fixes live in best_known_headless_auth_seed:
  1. Placeholder candidates are skipped entirely.
  2. If a seeded value is older than the baked-in default, the default wins.
"""
import os
from unittest.mock import patch

import main


def _no_real_dev_session():
    """Return a patch context that makes dev_session_cache_path point at a
    path that does not exist, so the function doesn't read real on-disk
    session data during the test."""
    fake = type(main).__name__  # arbitrary attr; we just need a Path-like with .exists() returning False
    class _FakePath:
        def exists(self):
            return False
        def __fspath__(self):
            return ""
    return patch.object(main, "dev_session_cache_path", return_value=_FakePath())


def _patch_candidates(candidates):
    """Patch out the auth-profile/dev-session readers so the only candidate
    source is the list we pass in."""
    return [
        patch.object(main, "load_reusable_auth_profiles", return_value={}),
        patch.object(main, "active_client", None),
        _no_real_dev_session(),
    ]


def test_placeholder_app_ver_is_ignored():
    """app_ver='1.0.0' is a known sentinel — must NOT win over the default."""
    candidate = {
        "app_ver": "1.0.0",
        "res_ver": "10006300",
        "locale": "JPN",
        "unity_ver": "2022.3.62f2",
        "steam_id": "76561198000000000",
        "steam_session_ticket": "real-ticket",
        "viewer_id": 209937075503,
    }
    with patch.object(main, "load_reusable_auth_profiles",
                      return_value={"76561198000000000": {"config": candidate}}), \
         patch.object(main, "active_client", None), \
         _no_real_dev_session():
        seed = main.best_known_headless_auth_seed(steam_id="76561198000000000")
    # Placeholder app_ver must not be used; fall through to default.
    assert seed["app_ver"] != "1.0.0"
    assert seed["app_ver"] == os.environ.get("SWEEPY_DEFAULT_APP_VER", "1.22.0")


def test_placeholder_res_ver_is_ignored():
    """res_ver='2' is a sentinel — must NOT win."""
    candidate = {
        "app_ver": "1.22.0",
        "res_ver": "2",
        "locale": "JPN",
        "unity_ver": "2022.3.62f2",
        "steam_id": "76561198000000000",
        "steam_session_ticket": "real-ticket",
        "viewer_id": 209937075503,
    }
    with patch.object(main, "load_reusable_auth_profiles",
                      return_value={"76561198000000000": {"config": candidate}}), \
         patch.object(main, "active_client", None), \
         _no_real_dev_session():
        seed = main.best_known_headless_auth_seed(steam_id="76561198000000000")
    assert seed["res_ver"] != "2"
    assert seed["res_ver"] == os.environ.get("SWEEPY_DEFAULT_RES_VER", "10006300")


def test_placeholder_steam_id_is_ignored():
    """steam_id='steam-restore' is the sentinel the bot writes when there's
    no real session. The ENTIRE candidate dict must be ignored if this is
    present, not just steam_id."""
    candidate = {
        "app_ver": "1.20.0",  # would also be too old
        "res_ver": "10000000",
        "locale": "JPN",
        "unity_ver": "2022.3.62f2",
        "steam_id": "steam-restore",
        "steam_session_ticket": "ticket-restore",
        "viewer_id": 123456,
    }
    with patch.object(main, "load_reusable_auth_profiles",
                      return_value={"steam-restore": {"config": candidate}}), \
         patch.object(main, "active_client", None), \
         _no_real_dev_session():
        seed = main.best_known_headless_auth_seed(steam_id="steam-restore")
    # All fields should come from defaults, not the sentinel candidate
    assert seed["app_ver"] == os.environ.get("SWEEPY_DEFAULT_APP_VER", "1.22.0")
    assert seed["res_ver"] == os.environ.get("SWEEPY_DEFAULT_RES_VER", "10006300")


def test_stale_app_ver_in_cache_replaced_by_newer_default():
    """When dev_session.json has app_ver=1.20.0 but main.py default is
    1.22.0, the default wins — otherwise a code update doesn't help users
    whose cache is sticky."""
    candidate = {
        "app_ver": "1.20.0",  # OLDER than the 1.22.0 default
        "res_ver": "10006300",
        "locale": "JPN",
        "unity_ver": "2022.3.62f2",
        "steam_id": "76561198000000001",
        "steam_session_ticket": "real-ticket",
        "viewer_id": 209937075504,
    }
    with patch.dict(os.environ, {"SWEEPY_DEFAULT_APP_VER": "1.22.0"}, clear=False), \
         patch.object(main, "load_reusable_auth_profiles",
                      return_value={"76561198000000001": {"config": candidate}}), \
         patch.object(main, "active_client", None), \
         _no_real_dev_session():
        seed = main.best_known_headless_auth_seed(steam_id="76561198000000001")
    assert seed["app_ver"] == "1.22.0", (
        f"Expected default 1.22.0 to win over stale cache 1.20.0, got {seed['app_ver']}"
    )


def test_stale_res_ver_in_cache_replaced_by_newer_default():
    """Same freshness rule for res_ver — numeric comparison."""
    candidate = {
        "app_ver": "1.22.0",
        "res_ver": "10006000",  # OLDER than 10006300 default
        "locale": "JPN",
        "unity_ver": "2022.3.62f2",
        "steam_id": "76561198000000002",
        "steam_session_ticket": "real-ticket",
        "viewer_id": 209937075505,
    }
    with patch.dict(os.environ, {"SWEEPY_DEFAULT_RES_VER": "10006300"}, clear=False), \
         patch.object(main, "load_reusable_auth_profiles",
                      return_value={"76561198000000002": {"config": candidate}}), \
         patch.object(main, "active_client", None), \
         _no_real_dev_session():
        seed = main.best_known_headless_auth_seed(steam_id="76561198000000002")
    assert seed["res_ver"] == "10006300", (
        f"Expected default 10006300 to win over stale cache 10006000, got {seed['res_ver']}"
    )


def test_newer_cache_versions_preserved():
    """Inverse — when cache has a NEWER version than the default (because
    auto-discovery found it and persisted), the cache wins. Otherwise we'd
    keep rolling back the auto-discovered values on every startup."""
    candidate = {
        "app_ver": "1.23.0",  # NEWER than 1.22.0 default
        "res_ver": "10006500",  # NEWER than 10006300 default
        "locale": "JPN",
        "unity_ver": "2022.3.62f2",
        "steam_id": "76561198000000003",
        "steam_session_ticket": "real-ticket",
        "viewer_id": 209937075506,
    }
    with patch.dict(os.environ,
                    {"SWEEPY_DEFAULT_APP_VER": "1.22.0",
                     "SWEEPY_DEFAULT_RES_VER": "10006300"}, clear=False), \
         patch.object(main, "load_reusable_auth_profiles",
                      return_value={"76561198000000003": {"config": candidate}}), \
         patch.object(main, "active_client", None), \
         _no_real_dev_session():
        seed = main.best_known_headless_auth_seed(steam_id="76561198000000003")
    assert seed["app_ver"] == "1.23.0", "Auto-discovered newer app_ver must persist"
    assert seed["res_ver"] == "10006500", "Auto-discovered newer res_ver must persist"


def test_dedicated_version_cache_beats_stale_auth_profile():
    """The shared client-version cache should seed login before auth profiles.

    Reusable auth profiles are account-specific and can be stale. A version pair
    accepted by auto-discovery should become the preferred metadata for all
    later headless login/validate attempts.
    """
    stale_profile = {
        "app_ver": "1.22.0",
        "res_ver": "10006300",
        "locale": "JPN",
        "unity_ver": "2022.3.62f2",
        "steam_id": "76561198000000004",
        "steam_session_ticket": "real-ticket",
        "viewer_id": 209937075507,
    }
    with patch.dict(os.environ, {"SWEEPY_DEFAULT_APP_VER": "1.22.0", "SWEEPY_DEFAULT_RES_VER": "10006300"}, clear=False), \
         patch.object(main, "read_client_version_cache", return_value={"app_ver": "1.23.0", "res_ver": "10006600"}), \
         patch.object(main, "load_reusable_auth_profiles", return_value={"76561198000000004": {"config": stale_profile}}), \
         patch.object(main, "active_client", None), \
         _no_real_dev_session():
        seed = main.best_known_headless_auth_seed(steam_id="76561198000000004")

    assert seed["app_ver"] == "1.23.0"
    assert seed["res_ver"] == "10006600"
    assert seed["locale"] == "JPN"
