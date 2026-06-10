import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from career_bot.storage_cleanup import cleanup_stale_dumps  # noqa: E402


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    result = cleanup_stale_dumps(ROOT, older_than_days=days)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
