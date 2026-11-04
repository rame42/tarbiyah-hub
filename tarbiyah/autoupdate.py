"""Automatic updates: the program updates itself from GitHub, safely.

The worker checks GitHub every few hours (setting auto_update). When a new version exists it starts a
small separate helper process (`python -m tarbiyah self-update`) that:
  1. stops the worker (running jobs finish first) and the web server,
  2. keeps a copy of the current program files,
  3. installs the new version (data/, .env and .venv are never touched),
  4. checks that the new version starts; if not, puts the previous version back,
  5. starts Tarbiyah Hub again (without opening a new browser tab).
Every step is written to data/run/last-update.txt, shown in Settings > Updates.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .config import PROJECT_ROOT, get_config
from .updater import PROTECTED

SKIP_DIRS = PROTECTED | {"__pycache__", "frontend/node_modules"}
LOCK_NAME = "self-update.lock"


def _run_dir() -> Path:
    d = get_config().data_dir / "run"
    d.mkdir(parents=True, exist_ok=True)
    return d


def enabled() -> bool:
    """Off for developer checkouts (a .git folder): those are updated with git."""
    return not (PROJECT_ROOT / ".git").exists()


def program_files(root: Path | None = None) -> list[Path]:
    root = root or PROJECT_ROOT
    out = []
    for f in root.rglob("*"):
        rel = f.relative_to(root)
        if f.is_dir() or rel.parts[0] in PROTECTED or "__pycache__" in rel.parts or "node_modules" in rel.parts:
            continue
        if rel.parts[0].startswith((".env", "data-before-import")) or (len(rel.parts) == 1 and rel.suffix == ".zip"):
            continue  # settings, library copies left by import-old, downloaded zips
        out.append(f)
    return out


def backup_program(dest: Path) -> int:
    files = program_files()
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for f in files:
            z.write(f, f.relative_to(PROJECT_ROOT).as_posix())
    return len(files)


def restore_program(backup: Path) -> int:
    with zipfile.ZipFile(backup) as z:
        z.extractall(PROJECT_ROOT)
        return len(z.namelist())


def self_check(timeout: int = 180) -> tuple[bool, str]:
    """Does the installed version load (dashboard, worker, database upgrade code)?"""
    code = "import tarbiyah.api.app, tarbiyah.jobs.worker, tarbiyah.migrate; print('ok')"
    try:
        r = subprocess.run([sys.executable, "-c", code], cwd=str(PROJECT_ROOT), capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "the new version did not start within 3 minutes"
    return r.returncode == 0 and "ok" in r.stdout, (r.stderr or r.stdout)[-1500:]


def stop_app(out: Callable[[str], None] = print, wait_seconds: int = 300) -> None:
    import signal

    from .runfiles import pid_alive, read_pid, request_stop

    wpid = read_pid("worker")
    if pid_alive(wpid):
        request_stop("worker")
        out(f"Worker (pid {wpid}) asked to stop; waiting for running jobs to finish...")
        for _ in range(wait_seconds):
            if not pid_alive(wpid):
                break
            time.sleep(1)
        out("Worker stopped." if not pid_alive(wpid) else "Worker still finishing a job; it will stop on its own.")
    else:
        out("Worker is not running.")
    web = read_pid("web")
    if pid_alive(web):
        os.kill(web, signal.SIGTERM)
        for _ in range(30):
            if not pid_alive(web):
                break
            time.sleep(1)
        out(f"Web server (pid {web}) stopped.")
    else:
        out("Web server is not running.")


def start_app() -> None:
    """Start worker and dashboard again, in the background, without opening a browser tab."""
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        subprocess.Popen(["cmd", "/c", "start.bat", "--no-browser"], cwd=str(PROJECT_ROOT), creationflags=flags,
                         close_fds=True)
    else:
        subprocess.Popen(["bash", "start.sh"], cwd=str(PROJECT_ROOT), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _lock_busy() -> bool:
    lock = _run_dir() / LOCK_NAME
    if not lock.exists():
        return False
    try:
        started = datetime.fromisoformat(lock.read_text().strip())
    except ValueError:
        return False
    return datetime.now() - started < timedelta(minutes=30)  # an older lock is left over from a crash


def spawn() -> bool:
    """Start the helper process that performs the update (it outlives the worker it stops)."""
    if _lock_busy():
        return False
    (_run_dir() / LOCK_NAME).write_text(datetime.now().isoformat())
    cmd = [sys.executable, "-m", "tarbiyah", "self-update"]
    if os.name == "nt":
        flags = (getattr(subprocess, "DETACHED_PROCESS", 0x8) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x200)
                 | getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), creationflags=flags, close_fds=True)
    else:
        subprocess.Popen(cmd, cwd=str(PROJECT_ROOT), start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return True


def run_self_update(out: Callable[[str], None] = print, *, restart: bool = True,
                    stop: Callable[..., None] = stop_app, start: Callable[[], None] = start_app) -> dict:
    """The helper's work. Never leaves the program half-updated: on any failure the old version returns."""
    from .updater import check, update

    lines: list[str] = [f"Automatic update started {datetime.now():%Y-%m-%d %H:%M}"]

    def log(msg: str) -> None:
        out(msg)
        lines.append(msg)

    result: dict = {"updated": False}
    try:
        info = check()
        if info.get("error") or not info.get("update_available"):
            log(info.get("error") or "Already up to date.")
            return result
        log(f"New version {info['latest']['sha']}: {info['latest']['message']}")
        stop(log)
        backup = _run_dir() / "program-backup.zip"
        log(f"Kept a copy of the current version ({backup_program(backup)} files).")
        try:
            update(None, log=log)
            ok, detail = self_check()
            if not ok:
                raise RuntimeError(f"the new version did not start correctly: {detail}")
            log("The new version starts correctly.")
            result = {"updated": True, "version": info["latest"]["sha"]}
        except Exception as e:  # noqa: BLE001 - always fall back to the working version
            log(f"Update failed ({e}). Putting the previous version back...")
            restore_program(backup)
            log("The previous version is back. Nothing was lost.")
            result = {"updated": False, "error": str(e)}
    finally:
        if restart and len(lines) > 2:
            log("Starting Tarbiyah Hub again...")
            start()
        try:
            (_run_dir() / "last-update.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        except OSError:
            pass
        (_run_dir() / LOCK_NAME).unlink(missing_ok=True)
    return result


def maybe_check(session) -> str | None:
    """Called by the worker's maintenance: every auto_update_hours, start the update helper if needed."""
    from .models import Setting
    from .settings import get_setting
    from .updater import check

    if not enabled() or not get_setting("auto_update", session):
        return None
    row = session.get(Setting, "_update_checked_at")
    hours = float(get_setting("auto_update_hours", session) or 6)
    now = datetime.now()
    if row is not None:
        try:
            if now - datetime.fromisoformat(row.value.get("at")) < timedelta(hours=hours):
                return None
        except (TypeError, ValueError, AttributeError):
            pass
    if row is None:
        session.add(Setting(key="_update_checked_at", value={"at": now.isoformat()}))
    else:
        row.value = {"at": now.isoformat()}
    info = check()
    if info.get("update_available"):
        return "started" if spawn() else "busy"
    return None
