"""Organized file storage with checksums and storage-limit enforcement."""
from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_config
from .models import Resource
from .settings import get_setting

EXT_BY_MIME = {
    "application/pdf": ".pdf",
    "application/epub+zip": ".epub",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "text/html": ".html",
    "text/plain": ".txt",
    "application/xhtml+xml": ".html",
}


class StorageLimitError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_name(name: str, max_len: int = 80) -> str:
    name = re.sub(r"[^\w؀-ۿ.\- ]+", "_", name, flags=re.UNICODE).strip(" ._")
    return (name or "file")[:max_len]


def guess_ext(mime: str | None, url_or_name: str = "") -> str:
    if mime:
        mime = mime.split(";")[0].strip().lower()
        if mime in EXT_BY_MIME:
            return EXT_BY_MIME[mime]
    suffix = Path(url_or_name.split("?")[0]).suffix.lower()
    if suffix and len(suffix) <= 6:
        return suffix
    return mimetypes.guess_extension(mime or "") or ".bin"


def used_bytes(session: Session) -> int:
    return int(session.execute(select(func.coalesce(func.sum(Resource.file_size), 0))).scalar() or 0)


def check_capacity(session: Session, incoming_bytes: int) -> None:
    cfg = get_config()
    limit = float(get_setting("storage_limit_gb", session)) * (1024 ** 3)
    if used_bytes(session) + incoming_bytes > limit:
        raise StorageLimitError("Storage limit reached (storage_limit_gb). Raise it in Settings or free space.")
    free = shutil.disk_usage(cfg.data_dir).free
    if free - incoming_bytes < float(get_setting("min_free_disk_gb", session)) * (1024 ** 3):
        raise StorageLimitError("Not enough free disk space (min_free_disk_gb).")


def store_bytes(session: Session, data: bytes, checksum: str, ext: str, title: str) -> Path:
    """Content-addressed layout: files/<aa>/<checksum>_<title><ext>."""
    check_capacity(session, len(data))
    cfg = get_config()
    folder = cfg.files_dir / checksum[:2]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{checksum[:16]}_{safe_name(title, 60)}{ext}"
    if not path.exists():
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        tmp.replace(path)
    return path


def store_file(session: Session, src: Path, checksum: str, title: str) -> Path:
    size = src.stat().st_size
    check_capacity(session, size)
    cfg = get_config()
    folder = cfg.files_dir / checksum[:2]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{checksum[:16]}_{safe_name(title, 60)}{src.suffix.lower()}"
    if not path.exists():
        shutil.copy2(src, path)
    return path


def relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(get_config().data_dir).as_posix()
    except ValueError:
        return str(path)


def absolute(rel: str) -> Path:
    p = Path(rel)
    return p if p.is_absolute() else get_config().data_dir / p
