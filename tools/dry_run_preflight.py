import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


MUTATING_ENDPOINTS = {
    "single_mode_free/start",
    "single_mode_free/finish",
    "single_mode_free/exec_command",
    "single_mode_free/gain_skills",
    "single_mode_free/multi_item_use",
    "single_mode_free/multi_item_exchange",
    "single_mode_free/race_entry",
    "single_mode_free/race_start",
    "single_mode_free/race_end",
    "single_mode_free/race_out",
    "single_mode_free/check_event",
    "single_mode_free/continue",
    "single_mode_free/reserve_race",
}


def load_request(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data


def dump_result(result):
    print(json.dumps(result, ensure_ascii=False, indent=2))


def post_json(url, payload, timeout=60):
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_server_preflight(args, payload):
    url = args.server.rstrip("/") + "/api/career/run/preflight"
    return post_json(url, payload, timeout=args.timeout)


class GuardedClient:
    def __init__(self, client):
        self._client = client

    def __getattr__(self, name):
        return getattr(self._client, name)

    def call(self, endpoint, args=None, **kwargs):
        if endpoint in MUTATING_ENDPOINTS:
            raise RuntimeError(f"dry-run blocked mutating endpoint: {endpoint}")
        return self._client.call(endpoint, args, **kwargs)


def run_live_capture_preflight(args, payload):
    import main
    from uma_api.client import UmaClient, get_ticket

    if not main.refresh_auth_before_serving(timeout_sec=args.capture_timeout):
        return {"success": False, "detail": "Fresh in-game auth capture failed"}

    cfg = dict(main.pending_game_auth_config)
    main.pending_game_auth_config = {}
    if args.steam_id and args.steam_ticket:
        cfg["steam_id"] = args.steam_id
        cfg["steam_session_ticket"] = args.steam_ticket
    elif args.username and args.password:
        steam_id, ticket = get_ticket(args.username, args.password, args.code)
        cfg["steam_id"] = steam_id
        cfg["steam_session_ticket"] = ticket
    else:
        return {
            "success": False,
            "detail": "Live capture mode requires --steam-id/--steam-ticket or --username/--password",
        }

    if args.password:
        cfg["steam_password_seed"] = args.password
    if not main.has_fresh_auth_config(cfg):
        return {"success": False, "detail": "Captured auth was incomplete or stale"}

    client = GuardedClient(main.attach_turn_delay(UmaClient(cfg, trace_enabled=False)))
    login_result = client.login()
    load_data = login_result.get("data", {})
    career_data = None
    if load_data.get("single_mode_chara_light") or load_data.get("single_mode_chara"):
        try:
            career_data = client.load_career().get("data")
        except Exception:
            career_data = None

    main.active_client = client
    main.active_dashboard_data = main.build_dashboard_data(load_data, career_data, preserve_friends=False)
    req = main.RunCareerRequest(**payload)
    return main.preflight_career_run_request(req)


def main_cli():
    parser = argparse.ArgumentParser(description="Non-mutating career start preflight.")
    parser.add_argument("--request", required=True, help="Path to a RunCareerRequest JSON file.")
    parser.add_argument("--server", default="http://127.0.0.1:1616", help="Running Sweepy server URL.")
    parser.add_argument("--timeout", type=int, default=60, help="Server request timeout in seconds.")
    parser.add_argument("--live-capture", action="store_true", help="Capture auth and run preflight directly without the UI server.")
    parser.add_argument("--capture-timeout", type=int, default=180, help="Auth capture timeout for --live-capture.")
    parser.add_argument("--steam-id", default="")
    parser.add_argument("--steam-ticket", default="")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--code", default="")
    args = parser.parse_args()

    payload = load_request(args.request)
    try:
        if args.live_capture:
            result = run_live_capture_preflight(args, payload)
        else:
            result = run_server_preflight(args, payload)
    except urllib.error.URLError as exc:
        result = {"success": False, "detail": f"Could not reach Sweepy server: {exc}"}
    except Exception as exc:
        result = {"success": False, "detail": str(exc)}

    dump_result(result)
    return 0 if result.get("success") else 2


if __name__ == "__main__":
    raise SystemExit(main_cli())
