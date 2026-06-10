import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from career_bot.storage_cleanup import rotate_preset_backups  # noqa: E402


def main():
    keep = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    result = rotate_preset_backups(ROOT, keep=keep)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
