import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from career_bot.runner import runtime_output_root  # noqa: E402
from career_bot.storage_cleanup import rotate_hachimi_exact_hooks  # noqa: E402


def main():
    manual_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else runtime_output_root(ROOT) / "manual_career_logs"
    result = rotate_hachimi_exact_hooks(manual_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
