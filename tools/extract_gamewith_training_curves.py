"""Extract GameWith scenario training base values.

The GameWith support-card comparison tool embeds scenario base training
values in its frontend bundle as a JavaScript constant named ``Ps``.
This script converts that constant into repo-native JSON so simulator work can
compare JP scenario base tiles without scraping the rendered page.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


DEFAULT_SCRIPT_URL = (
    "https://gamewith-tool.s3.ap-northeast-1.amazonaws.com/"
    "assets/js/uma_supportcard_compare.v3.min.js?67"
)
DEFAULT_UPDATE_URL = (
    "https://gamewith-tool.s3-ap-northeast-1.amazonaws.com/"
    "uma-musume/update.json"
)

JP_TO_KEY = {
    "スピード": "speed",
    "スタミナ": "stamina",
    "パワー": "power",
    "根性": "guts",
    "賢さ": "wit",
    "スキルPt": "skill_pt",
}


def _fetch_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8")


def _extract_js_array(bundle: str) -> str:
    match = re.search(r"\bPs\s*=", bundle)
    if not match:
        raise RuntimeError("Could not find GameWith scenario constant Ps in bundle")
    start = match.end()
    end = bundle.find(",Es=", start)
    if end < 0:
        raise RuntimeError("Could not find end marker for GameWith scenario constant Ps")
    return bundle[start:end]


def _eval_js_array(js_array: str) -> list[dict[str, Any]]:
    """Use Node to parse the JS object literal without reimplementing JS syntax."""
    script = (
        "const data = "
        + js_array
        + ";\nprocess.stdout.write(JSON.stringify(data));\n"
    )
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".js", delete=False) as fh:
        fh.write(script)
        temp_path = Path(fh.name)
    try:
        result = subprocess.run(
            ["node", str(temp_path)],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Node.js is required to parse the GameWith bundle") from exc
    finally:
        temp_path.unlink(missing_ok=True)
    return json.loads(result.stdout)


def _normalize_training_name(name: str) -> str:
    return JP_TO_KEY.get(name, name)


def _normalize_stats(values: dict[str, Any]) -> dict[str, int]:
    normalized: dict[str, int] = {}
    for key, value in values.items():
        normalized[JP_TO_KEY.get(key, key)] = int(value)
    return normalized


def _normalize_scenario(raw: dict[str, Any], index: int) -> dict[str, Any]:
    facilities: dict[str, dict[str, dict[str, int]]] = {}
    for level, trainings in (raw.get("baseValues") or {}).items():
        for training_name, gains in trainings.items():
            training_key = _normalize_training_name(training_name)
            facilities.setdefault(training_key, {})[str(level)] = _normalize_stats(gains)
    return {
        "source_order_newest_first": index,
        "name": raw.get("name", ""),
        "facilities": facilities,
        "available_levels": sorted(
            {level for by_level in facilities.values() for level in by_level.keys()},
            key=lambda item: int(item),
        ),
    }


def build_curves(script_url: str = DEFAULT_SCRIPT_URL, update_url: str = DEFAULT_UPDATE_URL) -> dict[str, Any]:
    update: dict[str, Any] = {}
    try:
        update = json.loads(_fetch_text(update_url))
    except Exception as exc:  # noqa: BLE001 - update timestamp is helpful, not required.
        update = {"error": str(exc)}
    bundle = _fetch_text(script_url)
    raw_scenarios = _eval_js_array(_extract_js_array(bundle))
    scenarios = [
        _normalize_scenario(raw, index)
        for index, raw in enumerate(raw_scenarios, start=1)
    ]
    return {
        "schema": "sweepy_gamewith_scenario_training_curves_v1",
        "source": "GameWith support-card comparison tool frontend data",
        "source_urls": {
            "article": "https://gamewith.jp/uma-musume/article/show/283210",
            "script": script_url,
            "update": update_url,
        },
        "last_update": update.get("lastUpdate"),
        "notes": [
            "GameWith exposes stat and skill-point base values, but not HP/energy cost in this table.",
            "Current extracted data only includes the levels present in the GameWith bundle; at the time of extraction this is level 5.",
            "source_order_newest_first is GameWith display order, not confirmed internal game scenario_id.",
        ],
        "scenarios": scenarios,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out",
        default=str(Path("data") / "gamewith_scenario_training_curves.json"),
        help="Output JSON path.",
    )
    parser.add_argument("--script-url", default=DEFAULT_SCRIPT_URL)
    parser.add_argument("--update-url", default=DEFAULT_UPDATE_URL)
    args = parser.parse_args()

    data = build_curves(args.script_url, args.update_url)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        f"wrote {out_path} with {len(data['scenarios'])} scenarios "
        f"(last_update={data.get('last_update')})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
