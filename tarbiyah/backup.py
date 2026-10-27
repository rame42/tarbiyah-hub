"""Backup and restore of the whole knowledge base (database + files + extracted text + outputs).

Backups use SQLite's online backup API, so they are consistent even while the
worker is running. Secrets (.env) are never included.
"""
from __future__ import annotations

import shutil
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from .config import PROJECT_ROOT, get_config

INCLUDE_DIRS = ("files", "text", "outputs", "inbox")


def backup(dest: Path | None = None) -> Path:
    cfg = get_config()
    dest = Path(dest) if dest else PROJECT_ROOT / "backups"
    dest.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive = dest / f"tarbiyah-backup-{stamp}.zip"
    db_path = cfg.data_dir / "tarbiyah.db"
    with tempfile.TemporaryDirectory() as tmp:
        snap = Path(tmp) / "tarbiyah.db"
        src = sqlite3.connect(db_path)
        dst = sqlite3.connect(snap)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as z:
            z.write(snap, "tarbiyah.db")
            for d in INCLUDE_DIRS:
                root = cfg.data_dir / d
                if not root.exists():
                    continue
                for f in root.rglob("*"):
                    if f.is_file() and not f.name.endswith(".part"):
                        z.write(f, f.relative_to(cfg.data_dir).as_posix())
    return archive


def restore(archive: Path) -> str:
    """Replace the current data folder with the archive contents. Stop web + worker first.
    The previous data folder is kept as data.before-restore-<time>."""
    cfg = get_config()
    archive = Path(archive)
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        if "tarbiyah.db" not in names:
            raise ValueError("Not a Tarbiyah Hub backup (tarbiyah.db missing).")
        for n in names:  # refuse path traversal
            if n.startswith("/") or ".." in Path(n).parts:
                raise ValueError(f"Unsafe path in archive: {n}")
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        old = cfg.data_dir.with_name(cfg.data_dir.name + f".before-restore-{stamp}")
        if cfg.data_dir.exists():
            shutil.move(str(cfg.data_dir), old)
        cfg.data_dir.mkdir(parents=True)
        z.extractall(cfg.data_dir)
    cfg.ensure_dirs()
    return f"Restored {archive.name}. Previous data kept in {old}."
