"""PID files and stop requests, so start/stop scripts work the same on Windows and Linux."""
from __future__ import annotations

import os
from pathlib import Path

from .config import get_config


def _dir() -> Path:
    d = get_config().data_dir / "run"
    d.mkdir(parents=True, exist_ok=True)
    return d


def write_pid(name: str) -> None:
    (_dir() / f"{name}.pid").write_text(str(os.getpid()))


def read_pid(name: str) -> int | None:
    p = _dir() / f"{name}.pid"
    try:
        return int(p.read_text().strip())
    except (OSError, ValueError):
        return None


def clear_pid(name: str) -> None:
    p = _dir() / f"{name}.pid"
    if p.exists() and read_pid(name) == os.getpid():
        p.unlink(missing_ok=True)


def request_stop(name: str) -> None:
    (_dir() / f"stop-{name}").write_text("stop")


def stop_requested(name: str) -> bool:
    return (_dir() / f"stop-{name}").exists()


def clear_stop_request(name: str) -> None:
    (_dir() / f"stop-{name}").unlink(missing_ok=True)


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        if os.name == "nt":
            import ctypes

            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
            if not handle:
                return False
            code = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            ctypes.windll.kernel32.CloseHandle(handle)
            return code.value == 259  # STILL_ACTIVE
        os.kill(pid, 0)
        try:  # an exited-but-unreaped (zombie) process is not running
            with open(f"/proc/{pid}/stat") as f:
                return f.read().split(") ", 1)[1][:1] != "Z"
        except OSError:
            return True
    except OSError:
        return False


class InterProcessLock:
    """Exclusive lock on a file, shared by all Tarbiyah Hub processes (Windows and POSIX)."""

    def __init__(self, name: str):
        self.path = _dir() / f"{name}.lock"
        self.fh = None

    def __enter__(self):
        self.fh = open(self.path, "a+b")
        if os.name == "nt":
            import msvcrt
            import time

            while True:
                try:
                    self.fh.seek(0)
                    msvcrt.locking(self.fh.fileno(), msvcrt.LK_LOCK, 1)
                    break
                except OSError:
                    time.sleep(0.5)
        else:
            import fcntl

            fcntl.flock(self.fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            if os.name == "nt":
                import msvcrt

                self.fh.seek(0)
                msvcrt.locking(self.fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.fh.fileno(), fcntl.LOCK_UN)
        finally:
            self.fh.close()
