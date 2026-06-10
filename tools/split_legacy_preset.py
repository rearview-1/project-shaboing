import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from career_bot.presets import PresetStore, slugify, split_preset_layers  # noqa: E402


def _read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload or {}, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _archive_legacy(source_path, archive_root, *, move=False):
    source = Path(source_path)
    archive_root.mkdir(parents=True, exist_ok=True)
    target = archive_root / f"{source.stem}.json.pre_phase7"
    suffix = 1
    while target.exists():
        target = archive_root / f"{source.stem}.{suffix}.json.pre_phase7"
        suffix += 1
    if move:
        shutil.move(str(source), str(target))
    else:
        shutil.copy2(source, target)
    return target


def split_legacy_preset(path, *, base_dir=ROOT, account_id="", instance_override=False, archive=False, move_archive=False):
    store = PresetStore(base_dir)
    store.ensure()
    source = Path(path)
    data = _read_json(source)
    layers = split_preset_layers(data, instance_override=instance_override)
    name = layers["config"].get("name") or source.stem
    family = layers["family"]

    config_path = store.config_path(name)
    if instance_override and not config_path.exists():
        raise ValueError(
            f"Base split config is missing for preset {name!r}. "
            "Run this tool once on the saved/global preset before migrating instance overrides."
        )
    if not instance_override:
        _write_json(config_path, layers["config"])
    runtime_path = None
    if layers["runtime"]:
        runtime_path = store.save_runtime_state(account_id, name, layers["runtime"])
    model_path = None
    if layers["model"] and not instance_override:
        model_path = store.save_policy_model(family, layers["model"])
    override_path = None
    if layers["overrides"]:
        override_path = store.save_policy_overrides(account_id, family, layers["overrides"])
    archive_path = None
    if archive:
        archive_path = _archive_legacy(
            source,
            Path(base_dir) / "data" / "presets" / "_archive_legacy",
            move=move_archive,
        )

    return {
        "source": str(source),
        "name": name,
        "family": family,
        "config_path": str(config_path),
        "runtime_path": str(runtime_path) if runtime_path else "",
        "policy_model_path": str(model_path) if model_path else "",
        "policy_overrides_path": str(override_path) if override_path else "",
        "archive_path": str(archive_path) if archive_path else "",
        "config_key_count": len(layers["config"]),
        "runtime_key_count": len(layers["runtime"]),
        "model_key_count": len(layers["model"]),
        "override_key_count": len(layers["overrides"]),
    }


def main():
    parser = argparse.ArgumentParser(description="Split a legacy Sweepy preset into Phase 7 config/state/model layers.")
    parser.add_argument("path", help="Path to legacy preset JSON")
    parser.add_argument("--base-dir", default=str(ROOT), help="Project root")
    parser.add_argument("--account-id", default="", help="Instance/account id for runtime state or overrides")
    parser.add_argument("--instance-override", action="store_true", help="Treat the source as an instance-local learned override")
    parser.add_argument("--archive", action="store_true", help="Copy source into data/presets/_archive_legacy")
    parser.add_argument("--move-archive", action="store_true", help="Move source into archive instead of copying it")
    args = parser.parse_args()

    result = split_legacy_preset(
        args.path,
        base_dir=Path(args.base_dir),
        account_id=args.account_id,
        instance_override=args.instance_override,
        archive=args.archive or args.move_archive,
        move_archive=args.move_archive,
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
