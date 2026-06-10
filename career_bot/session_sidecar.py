"""Sidecar pairing of hachimi capture careers with the active learning session.

Path B from `docs/capture-tool-clarification.md`: the sweepy_capture DLL doesn't
currently embed `learning_session` into manifest.json, and rebuilding the DLL
takes a recompile cycle. As an interim, this module watches the hachimi
"Career turn data" folder and, when it sees a new career subdirectory, drops a
snapshot of `data/learning_sessions/current_session.json` into it as
`learning_session.json`.

Once the bot loader reads a career, it merges the sidecar in alongside the
manifest — same end result as the DLL embed, just snapshotted at filesystem-
detection time rather than at game-side career-start. Small timing risk: if
the user changes session in the seconds between the game starting the career
and this watcher noticing the folder, the wrong session gets attached. Best
mitigation: declare the session before starting the manual run.

Old careers without sidecars get the default session at learn time (Part 10
backwards-compat).
"""

import json
import threading
import time
from pathlib import Path


SIDECAR_NAME = "learning_session.json"
POLL_INTERVAL_SECONDS = 5.0
# Match the stat-typed subdirectory layout the DLL creates after the v2
# folder-routing change. The watcher descends one level into these so
# sidecars land inside the actual career folder.
_STAT_SUBDIR_NAMES = frozenset({"SPD", "STAM", "PWR", "GUTS", "WIT", "BALANCED", "UNKNOWN", "Unlabelled runs"})


def _safe_read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None


def _is_popup_enabled(base_dir):
    """Check the popup-enabled setting. File lives at
    base_dir/data/learning_sessions/popup_setting.json; absence means
    enabled (the default)."""
    path = Path(base_dir) / "data" / "learning_sessions" / "popup_setting.json"
    if not path.exists():
        return True
    data = _safe_read_json(path)
    if not isinstance(data, dict):
        return True
    return bool(data.get("enabled", True))


def _career_has_attached_session(career_folder):
    """A career has an attached session if it has a sidecar OR if its
    manifest.json embeds a non-null `learning_session`. Used by pending_intent
    to decide whether to prompt the user for a new declaration."""
    career_folder = Path(career_folder)
    if (career_folder / SIDECAR_NAME).exists():
        return True
    manifest = career_folder / "manifest.json"
    if not manifest.exists():
        return False
    data = _safe_read_json(manifest)
    if not isinstance(data, dict):
        return False
    embedded = data.get("learning_session")
    # `null` (Python None) means the DLL wrote no session — not attached.
    return isinstance(embedded, dict) and bool(embedded)


def _atomic_write_json(path, payload):
    """Atomic write with per-process .tmp + retry. Matches the pattern in
    parent_memory.write_json. Failure modes are best-effort — a sidecar
    is informational; failing to write one is logged but doesn't crash."""
    import os
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2)
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    tmp.write_text(serialized, encoding="utf-8")
    last_exc = None
    for attempt in range(3):
        try:
            os.replace(tmp, path)
            return True
        except PermissionError as exc:
            last_exc = exc
            time.sleep(0.15 * (attempt + 1))
    if last_exc is not None:
        try:
            path.write_text(serialized, encoding="utf-8")
            try:
                tmp.unlink()
            except Exception:
                pass
            return True
        except Exception:
            return False
    return False


def pair_session_into_career_folder(career_folder, session):
    """Drop `session` into `<career_folder>/learning_session.json` if not present.

    Idempotent: if the sidecar already exists, do nothing (we never overwrite
    a previously-snapshotted session). Returns True if a sidecar was written,
    False if one already existed or session was None.
    """
    career_folder = Path(career_folder)
    sidecar = career_folder / SIDECAR_NAME
    if sidecar.exists():
        return False
    if not isinstance(session, dict):
        return False
    return _atomic_write_json(sidecar, session)


def read_career_sidecar(career_folder):
    """Return the snapshotted session for a career folder, or None."""
    return _safe_read_json(Path(career_folder) / SIDECAR_NAME)


class SessionSidecarWatcher:
    """Polling watcher that drops a session sidecar into each new career folder.

    Started lazily by the FastAPI startup hook. Runs as a daemon thread so it
    doesn't prevent process shutdown. Polls every POLL_INTERVAL_SECONDS — a
    proper inotify/ReadDirectoryChangesW approach would be tighter but adds
    a `watchdog` dependency for limited gain on this scale.
    """

    def __init__(self, base_dir, hachimi_dirs=None, session_path=None):
        self.base_dir = Path(base_dir)
        self.session_path = Path(session_path) if session_path else (
            self.base_dir / "data" / "learning_sessions" / "current_session.json"
        )
        self._explicit_dirs = [Path(p) for p in (hachimi_dirs or []) if p]
        self._thread = None
        self._stop_event = threading.Event()
        self._seen_folders = set()

    def _discover_dirs(self):
        if self._explicit_dirs:
            return [p for p in self._explicit_dirs if p.exists()]
        try:
            # Reuse the same discovery logic the loader uses so test runners
            # are auto-disabled and Steam paths are probed in the same order.
            from career_bot.learning import _hachimi_capture_career_dirs
            return _hachimi_capture_career_dirs()
        except Exception:
            return []

    def _current_session(self):
        return _safe_read_json(self.session_path)

    def _process_once(self):
        session = self._current_session()
        if not isinstance(session, dict):
            return 0
        written = 0
        for hachimi_dir in self._discover_dirs():
            try:
                children = list(hachimi_dir.iterdir())
            except OSError:
                continue
            for child in children:
                if not child.is_dir():
                    continue
                if child.name.startswith("_"):
                    # _latest / _debug are hachimi's bookkeeping folders
                    continue
                if child.name in _STAT_SUBDIR_NAMES:
                    # New stat-typed layout: descend one level so we drop the
                    # sidecar inside the actual career folder, not into the
                    # stat parent.
                    try:
                        for grandchild in child.iterdir():
                            if not grandchild.is_dir() or grandchild.name.startswith("_"):
                                continue
                            if str(grandchild) in self._seen_folders:
                                continue
                            self._seen_folders.add(str(grandchild))
                            if pair_session_into_career_folder(grandchild, session):
                                written += 1
                    except OSError:
                        continue
                    continue
                if str(child) in self._seen_folders:
                    continue
                self._seen_folders.add(str(child))
                if pair_session_into_career_folder(child, session):
                    written += 1
        return written

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self._process_once()
            except Exception:
                pass
            self._stop_event.wait(POLL_INTERVAL_SECONDS)

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="SessionSidecarWatcher")
        self._thread.start()

    def stop(self):
        self._stop_event.set()

    def pending_intent(self):
        """Decide whether the dashboard should pop up the run-intent modal.

        Returns {"needs_intent": bool, "career_name": str|None, "folder": str|None}.

        needs_intent is True iff:
        - the popup is enabled (popup_setting.json missing or {"enabled": true}),
        - no current session is declared (current_session.json missing),
        - and at least one career folder exists on disk without an attached
          session (no sidecar, no non-null embedded session in manifest.json).
        """
        result = {"needs_intent": False, "career_name": None, "folder": None}
        if not _is_popup_enabled(self.base_dir):
            return result
        # If a session is already declared, the DLL will route correctly —
        # no need to prompt the user.
        if self.session_path.exists():
            try:
                if self.session_path.stat().st_size > 0:
                    return result
            except OSError:
                return result
        candidates = []
        for hachimi_dir in self._discover_dirs():
            try:
                children = list(hachimi_dir.iterdir())
            except OSError:
                continue
            for child in children:
                if not child.is_dir() or child.name.startswith("_"):
                    continue
                if child.name in _STAT_SUBDIR_NAMES:
                    try:
                        grandchildren = list(child.iterdir())
                    except OSError:
                        continue
                    for grandchild in grandchildren:
                        if not grandchild.is_dir() or grandchild.name.startswith("_"):
                            continue
                        if _career_has_attached_session(grandchild):
                            continue
                        try:
                            mtime = grandchild.stat().st_mtime
                        except OSError:
                            continue
                        candidates.append((mtime, grandchild))
                    continue
                if _career_has_attached_session(child):
                    continue
                try:
                    mtime = child.stat().st_mtime
                except OSError:
                    continue
                candidates.append((mtime, child))
        if not candidates:
            return result
        candidates.sort(key=lambda x: x[0], reverse=True)
        newest = candidates[0][1]
        return {"needs_intent": True, "career_name": newest.name, "folder": str(newest)}
