import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from career_bot.learning import learn_preset, save_learning_outputs  # noqa: E402
from career_bot.presets import PresetStore  # noqa: E402


def parse_args():
    parser = argparse.ArgumentParser(description="Learn a better MANT preset from previous bot/manual careers.")
    parser.add_argument("--preset", default="", help="Source preset name to tune. Defaults to the first available preset.")
    parser.add_argument("--output-name", default=None, help="Name for the learned preset. Defaults to '<preset> learned'.")
    parser.add_argument("--runtime", action="append", default=[], help="Additional uma_runtime path to scan. Can be repeated.")
    parser.add_argument("--recent", type=int, default=None, help="Only scan the N most recent files from each log type.")
    parser.add_argument("--min-samples", type=int, default=3, help="Minimum usable career samples required.")
    parser.add_argument("--apply", action="store_true", help="Overwrite the source preset after writing a backup.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable output.")
    parser.add_argument(
        "--manual-only",
        action="store_true",
        help="Filter samples to manual sources before tuning. Useful when you "
             "want a small batch of deliberate manual runs to dominate the "
             "next preset adjustment instead of being diluted by the bot-career backlog.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    preset_name = str(args.preset or "").strip()
    if not preset_name:
        preset_name = PresetStore(ROOT).default_name(preferred="")
    if not preset_name:
        raise SystemExit("No presets found under data/presets.")
    learned, report = learn_preset(
        ROOT,
        preset_name,
        output_name=args.output_name,
        runtime_paths=args.runtime,
        recent=args.recent,
        min_samples=args.min_samples,
        manual_only=args.manual_only,
    )
    preset_path, report_path = save_learning_outputs(ROOT, learned, report, apply=args.apply)
    output = {
        "success": True,
        "preset_path": str(preset_path),
        "report_path": str(report_path),
        "learned_preset": report.get("learned_preset"),
        "source_preset": report.get("source_preset"),
        "sample_count": report.get("sample_count"),
        "usable_sample_count": report.get("usable_sample_count"),
        "source_counts": report.get("source_counts"),
        "warnings": report.get("warnings"),
        "changes": report.get("changes"),
        "skipped": report.get("skipped"),
    }
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    print(f"learned preset: {preset_path}")
    print(f"learning report: {report_path}")
    print(f"samples: {output['usable_sample_count']} usable / {output['sample_count']} total")
    print(f"sources: {json.dumps(output['source_counts'], ensure_ascii=False)}")
    for warning in output.get("warnings") or []:
        print(f"warning: {warning}")
    changed = ", ".join(output.get("changes", {}).keys()) or "none"
    print(f"changed fields: {changed}")
    if not args.apply:
        print("source preset was not overwritten; use --apply after reviewing the learned preset/report")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
