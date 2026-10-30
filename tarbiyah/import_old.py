"""`python -m tarbiyah import-old FOLDER`: bring the library of an older Tarbiyah Hub folder into this one.

Copies the old data folder (database, downloaded files, texts, reports, backups) and the old .env
(keys and settings). The old folder is only read, never changed, so nothing can be lost; whatever this
new folder already had is kept aside as data-before-import-<time> / .env-before-import-<time>.
"""
from __future__ import annotations

import shutil
import sqlite3
from datetime import datetime
from pathlib import Path

from .config import PROJECT_ROOT


def _env_value(env: Path, key: str) -> str:
    if not env.exists():
        return ""
    found = ""
    for line in env.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        name, sep, value = line.partition("=")
        value = value.strip().strip("\"'").strip()
        if sep and name.strip() == key and value and not line.lstrip().startswith("#"):
            found = value  # the last filled-in line wins, as when the settings are loaded
    return found


def find_old_install(given: Path) -> tuple[Path, Path]:
    """(old program folder, old data folder) from whatever the person dragged or pasted:
    the program folder, its data folder, the database file, or a folder containing the program folder."""
    given = Path(str(given).strip().strip('"')).expanduser()
    if not given.exists():
        raise ValueError(f"The folder '{given}' does not exist. Check the path (copy it from the address bar).")
    if given.is_file():
        given = given.parent
    candidates = [given, given.parent] + [p for p in sorted(given.glob("*")) if p.is_dir()] + \
                 [p for p in sorted(given.glob("*/*")) if p.is_dir()]
    for c in candidates:
        if c.name == "data" and (c / "tarbiyah.db").exists() and (c.parent / "tarbiyah").is_dir():
            return c.parent, c
        if (c / "tarbiyah" / "__main__.py").exists():
            custom = _env_value(c / ".env", "TH_DATA_DIR")
            data = Path(custom) if custom else c / "data"
            if not data.is_absolute():
                data = c / data
            if (data / "tarbiyah.db").exists():
                return c, data
    raise ValueError(f"No Tarbiyah Hub library was found in '{given}'. Choose the old folder that contains "
                     f"the 'data' folder (with tarbiyah.db inside).")


def _count(db: Path) -> tuple[int, int]:
    try:
        con = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        try:
            items = con.execute("SELECT count(*) FROM resources").fetchone()[0]
            files = con.execute("SELECT count(*) FROM resources WHERE local_path IS NOT NULL").fetchone()[0]
            return int(items), int(files)
        finally:
            con.close()
    except sqlite3.Error:
        return 0, 0


def _old_app_running(old_data: Path) -> bool:
    from .runfiles import pid_alive

    for name in ("worker", "web"):
        try:
            pid = int((old_data / "run" / f"{name}.pid").read_text().strip())
        except (OSError, ValueError):
            continue
        if pid_alive(pid):
            return True
    return False


def import_old(given: str | Path, out=print) -> dict:
    old_root, old_data = find_old_install(Path(given))
    new_root = PROJECT_ROOT
    new_data = _new_data_dir()
    if old_root.resolve() == new_root.resolve() or old_data.resolve() == new_data.resolve():
        raise ValueError("That is this same folder. Choose the OLD Tarbiyah Hub folder.")
    if _old_app_running(old_data):
        raise RuntimeError(f"The old Tarbiyah Hub is still running. Double-click stop.bat in {old_root}, "
                           f"wait until it says it stopped, then try again.")
    items, files = _count(old_data / "tarbiyah.db")
    out(f"Found the old library in {old_root}: {items} item(s), {files} downloaded file(s).")
    need = sum(f.stat().st_size for f in old_data.rglob("*") if f.is_file())
    free = shutil.disk_usage(new_root).free
    if need > free - 500 * 1024 ** 2:
        raise RuntimeError(f"Not enough free disk space: the library needs {need / 1024 ** 3:.1f} GB, "
                           f"{free / 1024 ** 3:.1f} GB is free.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    kept = []
    if new_data.exists() and any(new_data.iterdir()):
        aside = new_data.with_name(f"data-before-import-{stamp}")
        n = 1
        while aside.exists():
            n += 1
            aside = new_data.with_name(f"data-before-import-{stamp}-{n}")
        try:
            new_data.rename(aside)
        except PermissionError as e:
            raise RuntimeError(
                "Windows says a file in this folder's 'data' folder is in use. Close the Tarbiyah Hub windows of "
                "THIS folder (the black worker/dashboard windows on the taskbar) and any File Explorer window showing "
                f"the data folder, then try again. ({e})") from e
        kept.append(aside.name)
    out(f"Copying {need / 1024 ** 2:.0f} MB (database and files); this can take a while...")
    shutil.copytree(old_data, new_data, ignore=shutil.ignore_patterns("*.pid", "stop-*", "*.lock"))
    old_env = old_root / ".env"
    new_env = new_root / ".env"
    if old_env.exists():
        if new_env.exists():
            aside_env = new_root / f".env-before-import-{stamp}"
            shutil.copy2(new_env, aside_env)
            kept.append(aside_env.name)
        lines = [ln for ln in old_env.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
                 if not ln.strip().startswith("TH_DATA_DIR")]  # the library now lives in this folder
        new_env.write_text("\n".join(lines) + "\n", encoding="utf-8")
        out("Copied your keys and settings (.env).")
    copied_items, copied_files = _count(new_data / "tarbiyah.db")
    out(f"Done: {copied_items} item(s) and {copied_files} file(s) are now in this folder. "
        f"The old folder was not changed.")
    if kept:
        out("Kept aside (can be deleted later): " + ", ".join(kept))
    return {"items": copied_items, "files": copied_files, "from": str(old_root), "kept_aside": kept}


def _new_data_dir() -> Path:
    custom = _env_value(PROJECT_ROOT / ".env", "TH_DATA_DIR")
    d = Path(custom) if custom else PROJECT_ROOT / "data"
    return d if d.is_absolute() else PROJECT_ROOT / d
