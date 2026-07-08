import os
from pathlib import Path

from career_bot.learning import (
    build_postmortem_feedback_refresh,
    learn_preset,
    save_instance_learning_outputs,
    save_learning_report_only,
    save_learning_outputs,
    save_shared_learning_outputs,
)


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _as_int(value, default=0):
    try:
        if value is None or value == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _apply_scope(preset):
    scope = str(
        (preset or {}).get("auto_learning_apply_scope")
        or os.environ.get("SWEEPY_AUTO_LEARNING_SCOPE")
        or ""
    ).strip().lower()
    if not scope and os.environ.get("SWEEPY_SHARED_RUNTIME_PATHS") and os.environ.get("SWEEPY_INSTANCE_NAME"):
        scope = "shared_overlay"
    aliases = {
        "instance": "instance_local",
        "local": "instance_local",
        "instance_local": "instance_local",
        "shared": "shared_preset",
        "shared_preset": "shared_preset",
        "shared_overlay": "shared_overlay",
        "shared_runtime": "shared_overlay",
        "shared_learning": "shared_overlay",
        "global": "shared_preset",
    }
    return aliases.get(scope, "shared_preset")


def _apply_postmortem_refresh(base_dir, preset, apply_scope, runtime_paths=None, reason="monotonic_blocked"):
    try:
        refreshed, refresh_report = build_postmortem_feedback_refresh(
            base_dir,
            preset.get("name"),
            current_preset=preset,
            runtime_paths=runtime_paths or preset.get("auto_learning_runtime_paths") or [],
        )
        if refreshed and refresh_report:
            hint_count = int(refresh_report.get("hint_count") or 0)
            if hint_count <= 0:
                return {
                    "applied": False,
                    "skipped": "no_postmortem_hints",
                    "hint_count": 0,
                }
            refresh_report["trigger_reason"] = reason
            if apply_scope == "instance_local":
                preset_path, report_path = save_instance_learning_outputs(base_dir, refreshed, refresh_report)
            elif apply_scope == "shared_overlay":
                preset_path, report_path = save_shared_learning_outputs(base_dir, refreshed, refresh_report)
            else:
                preset_path, report_path = save_learning_outputs(base_dir, refreshed, refresh_report, apply=True)
            return {
                "applied": True,
                "apply_scope": apply_scope,
                "preset_path": str(preset_path),
                "report_path": str(report_path),
                "hint_count": hint_count,
            }
        return {
            "applied": False,
            "skipped": (refresh_report or {}).get("skipped") if refresh_report else "no_refresh_report",
            "hint_count": int((refresh_report or {}).get("hint_count") or 0) if refresh_report else 0,
        }
    except Exception as exc:
        return {
            "applied": False,
            "error": str(exc),
        }


def _career_log_looks_complete(career_log):
    """Treat a complete career as learnable even if runner status is stale.

    A few finish/loop bugs have produced reports labeled "stopped" after the
    run had already reached the career end. Blocking those logs prevents the
    learner from adapting from exactly the data we need. This check is strict
    enough to avoid empty/early-aborted logs.
    """
    if not career_log:
        return False
    try:
        import json

        path = Path(career_log)
        doc = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return False
    try:
        final_turn = int(doc.get("final_turn") or 0)
    except (TypeError, ValueError):
        final_turn = 0
    turns = doc.get("turns") or []
    race_count = 0
    if isinstance(turns, list):
        for turn in turns:
            if isinstance(turn, dict) and str(turn.get("event") or "").lower() in {"race", "race_result"}:
                race_count += 1
    return final_turn >= 76 or (isinstance(turns, list) and len(turns) >= 60 and race_count >= 8)


def run_auto_learning(base_dir, preset, *, career_log=None, status=None, account_tier=None):
    """Learn from all available career logs and apply the tuned preset.

    The latest career log is already on disk by the time this runs. The learner
    scans the backlog every time, so each new run updates the model using the
    complete local sample set instead of overfitting to just the last run.

    `account_tier` lets the caller block learning when the run came from a
    weaker secondary account. Without this gate, a side account's mediocre
    careers would silently dilute the main account's tuning. The preset's
    `auto_learning_min_tier` (one of "primary", "secondary", "any" — default
    "primary") controls which tiers are allowed to update the model. Pass
    `account_tier=None` for legacy behavior.
    """
    preset = dict(preset or {})
    if not _as_bool(preset.get("auto_learning_enabled"), True):
        return {"success": False, "skipped": "auto_learning_disabled"}

    min_tier = str(preset.get("auto_learning_min_tier") or "primary").strip().lower()
    if account_tier is not None and min_tier != "any":
        observed_tier = str(account_tier).strip().lower()
        # "primary" only allows the primary account; "secondary" allows
        # primary OR secondary. Anything else is blocked.
        allowed = {"primary": {"primary"}, "secondary": {"primary", "secondary"}}.get(min_tier, {"primary"})
        if observed_tier and observed_tier not in allowed:
            return {
                "success": False,
                "skipped": "account_tier_below_minimum",
                "account_tier": observed_tier,
                "min_tier": min_tier,
            }

    trigger_statuses = set(preset.get("auto_learning_statuses") or ["finished"])
    if status and trigger_statuses and str(status) not in trigger_statuses:
        if _as_bool(preset.get("auto_learning_learn_from_complete_logs"), True) and _career_log_looks_complete(career_log):
            status = f"{status}:complete_log_override"
        else:
            refresh_result = None
            try:
                refreshed, refresh_report = build_postmortem_feedback_refresh(
                    base_dir,
                    preset.get("name"),
                    current_preset=preset,
                    runtime_paths=preset.get("auto_learning_runtime_paths") or [],
                )
                if refreshed and refresh_report:
                    apply_scope = _apply_scope(preset)
                    if apply_scope == "instance_local":
                        preset_path, report_path = save_instance_learning_outputs(base_dir, refreshed, refresh_report)
                    elif apply_scope == "shared_overlay":
                        preset_path, report_path = save_shared_learning_outputs(base_dir, refreshed, refresh_report)
                    else:
                        preset_path, report_path = save_learning_outputs(base_dir, refreshed, refresh_report, apply=True)
                    refresh_result = {
                        "applied": True,
                        "apply_scope": apply_scope,
                        "preset_path": str(preset_path),
                        "report_path": str(report_path),
                        "hint_count": int(refresh_report.get("hint_count") or 0),
                    }
                elif refresh_report and refresh_report.get("skipped"):
                    refresh_result = {
                        "applied": False,
                        "skipped": refresh_report.get("skipped"),
                        "hint_count": int((refresh_report or {}).get("hint_count") or 0),
                    }
            except Exception as exc:
                refresh_result = {
                    "applied": False,
                    "error": str(exc),
                }
            return {
                "success": False,
                "skipped": "status_not_enabled",
                "status": status,
                "postmortem_refresh": refresh_result,
            }

    preset_name = str(preset.get("name") or "").strip()
    if not preset_name:
        return {"success": False, "skipped": "missing_preset_name"}

    recent = _as_int(preset.get("auto_learning_recent"), 0) or None
    min_samples = max(1, _as_int(preset.get("auto_learning_min_samples"), 3))
    apply = _as_bool(preset.get("auto_learning_apply"), True)
    manual_only = _as_bool(preset.get("auto_learning_manual_only"), False)
    runtime_paths = preset.get("auto_learning_runtime_paths") or []
    if isinstance(runtime_paths, (str, Path)):
        runtime_paths = [str(runtime_paths)]
    apply_scope = _apply_scope(preset)

    learned, report = learn_preset(
        base_dir,
        preset_name,
        output_name=preset.get("auto_learning_output_name") or None,
        runtime_paths=runtime_paths,
        recent=recent,
        min_samples=min_samples,
        manual_only=manual_only,
        source_preset_override=preset,
    )
    if career_log:
        report["trigger_career_log"] = str(career_log)
    if report.get("skipped"):
        return {
            "success": False,
            "skipped": report.get("skipped"),
            "source_preset": report.get("source_preset"),
            "sample_count": report.get("sample_count"),
            "usable_sample_count": report.get("usable_sample_count"),
            "source_counts": report.get("source_counts"),
            "warnings": report.get("warnings"),
        }
    report["auto_learning"] = {
        "enabled": True,
        "applied": apply,
        "apply_scope": apply_scope,
        "recent": recent,
        "min_samples": min_samples,
        "trigger_status": status,
    }
    gate = report.get("monotonic_apply_gate") or {}
    if apply and gate.get("enabled") and gate.get("allowed") is False:
        postmortem_refresh = _apply_postmortem_refresh(
            base_dir,
            preset,
            apply_scope,
            runtime_paths=runtime_paths,
            reason="monotonic_apply_gate_blocked",
        )
        report["auto_learning"]["applied"] = False
        report["auto_learning"]["apply_blocked_by"] = "monotonic_apply_gate"
        report["auto_learning"]["monotonic_apply_gate"] = gate
        report["auto_learning"]["postmortem_refresh"] = postmortem_refresh
        report["skipped_apply"] = "monotonic_apply_gate"
        report_path = save_learning_report_only(base_dir, report)
        return {
            "success": False,
            "skipped": "monotonic_apply_gate",
            "report_path": str(report_path),
            "applied": False,
            "apply_scope": apply_scope,
            "source_preset": report.get("source_preset"),
            "learned_preset": report.get("learned_preset"),
            "sample_count": report.get("sample_count"),
            "usable_sample_count": report.get("usable_sample_count"),
            "source_counts": report.get("source_counts"),
            "monotonic_apply_gate": gate,
            "postmortem_refresh": postmortem_refresh,
            "warnings": report.get("warnings"),
        }
    if apply and apply_scope == "instance_local":
        preset_path, report_path = save_instance_learning_outputs(base_dir, learned, report)
    elif apply and apply_scope == "shared_overlay":
        preset_path, report_path = save_shared_learning_outputs(base_dir, learned, report)
    else:
        preset_path, report_path = save_learning_outputs(base_dir, learned, report, apply=apply)
    return {
        "success": True,
        "preset_path": str(preset_path),
        "report_path": str(report_path),
        "applied": apply,
        "apply_scope": apply_scope,
        "source_preset": report.get("source_preset"),
        "learned_preset": report.get("learned_preset"),
        "sample_count": report.get("sample_count"),
        "usable_sample_count": report.get("usable_sample_count"),
        "source_counts": report.get("source_counts"),
        "changes": report.get("changes"),
        "warnings": report.get("warnings"),
    }
