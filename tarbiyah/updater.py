"""In-place updates that keep all user data.

Two ways to get a new version:
  1. GitHub:  set TH_UPDATE_REPO=owner/repo in .env (and TH_UPDATE_TOKEN for a private repo);
     `python -m tarbiyah update` downloads the latest code of the branch.
  2. A zip file: `python -m tarbiyah update --zip path\\to\\tarbiyah-hub.zip`
     (on Windows: drag the zip onto update.bat).

Only program files are replaced. These are never touched: data/, .env, .venv/, backups/.
Python packages are reinstalled only when requirements.txt changed. Database changes are
applied automatically on the next start (migrations).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

from .config import PROJECT_ROOT, get_config

PROTECTED = {"data", ".env", ".venv", "backups", ".git", "node_modules"}
VERSION_FILE = "version.json"
DEFAULT_REPO = "rame42/tarbiyah-hub"


def _version_path() -> Path:
    d = get_config().data_dir / "run"
    d.mkdir(parents=True, exist_ok=True)
    return d / VERSION_FILE


def installed_version() -> dict:
    try:
        return json.loads(_version_path().read_text())
    except (OSError, ValueError):
        return {}


def _save_version(info: dict) -> None:
    _version_path().write_text(json.dumps(info))


def _repo() -> tuple[str, str, str]:
    # this installation's own public repository is the default, so update.bat works without any setting
    repo = os.environ.get("TH_UPDATE_REPO") or _env_value("TH_UPDATE_REPO") or DEFAULT_REPO
    token = os.environ.get("TH_UPDATE_TOKEN") or _env_value("TH_UPDATE_TOKEN")
    branch = os.environ.get("TH_UPDATE_BRANCH") or _env_value("TH_UPDATE_BRANCH") or "main"
    return (repo or "").strip(), (token or "").strip(), branch.strip()


def _env_value(key: str) -> str:
    env = PROJECT_ROOT / ".env"
    if not env.exists():
        return ""
    found = ""
    for line in env.read_text(encoding="utf-8-sig", errors="ignore").splitlines():
        if line.lstrip().startswith("#"):
            continue
        name, sep, value = line.partition("=")
        value = value.strip().strip("\"'").strip()
        if sep and name.strip() == key and value:  # tolerate spaces and quotes; the last filled-in line wins
            found = value
    return found


def _headers(token: str) -> dict:
    h = {"Accept": "application/vnd.github+json", "User-Agent": "TarbiyahHub-updater"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def check() -> dict:
    """Is a newer version available on GitHub?"""
    repo, token, branch = _repo()
    current = installed_version()
    if not repo:
        return {"configured": False, "current": current,
                "message": "Automatic updates are not set up (TH_UPDATE_REPO in .env). "
                           "You can still update by dragging a zip file onto update.bat."}
    try:
        r = requests.get(f"https://api.github.com/repos/{repo}/commits/{branch}", headers=_headers(token), timeout=20)
    except requests.RequestException as e:
        return {"configured": True, "current": current,
                "error": f"Could not reach GitHub (check the internet connection): {e}"}
    if r.status_code in (401, 403, 404):
        if r.status_code == 401:
            why = "GitHub rejected TH_UPDATE_TOKEN (wrong, expired or incompletely copied). Create a new token."
        elif r.status_code == 403 and "rate limit" in r.text.lower():
            why = "GitHub's hourly limit for requests without a token was reached. Try again in an hour."
        elif not token:
            why = (f"GitHub did not find '{repo}'. It is private, so TH_UPDATE_TOKEN is needed in .env "
                   f"(or the name in TH_UPDATE_REPO is misspelled).")
        else:
            why = (f"GitHub did not find '{repo}' with this token. Check the spelling of TH_UPDATE_REPO and that the "
                   f"token has access to this repository with Contents: Read-only.")
        return {"configured": True, "current": current, "error": why}
    try:
        r.raise_for_status()
        latest = r.json()
    except (requests.RequestException, ValueError) as e:
        return {"configured": True, "current": current, "error": f"GitHub answered with an error: {e}"}
    sha = latest.get("sha", "")
    return {"configured": True, "current": current, "latest": {
        "sha": sha[:12], "date": ((latest.get("commit") or {}).get("committer") or {}).get("date"),
        "message": ((latest.get("commit") or {}).get("message") or "").split("\n")[0]},
        "update_available": bool(sha) and sha[:12] != current.get("sha")}


def _download_github(dest: Path) -> tuple[Path, dict]:
    repo, token, branch = _repo()
    if not repo:
        raise RuntimeError("TH_UPDATE_REPO is not set in .env.")
    info = check()
    if info.get("error"):
        raise RuntimeError(info["error"])
    r = requests.get(f"https://api.github.com/repos/{repo}/zipball/{branch}", headers=_headers(token),
                     timeout=300, stream=True)
    r.raise_for_status()
    z = dest / "update.zip"
    with open(z, "wb") as f:
        for chunk in r.iter_content(1 << 16):
            f.write(chunk)
    return z, {"sha": info["latest"]["sha"], "date": info["latest"]["date"], "source": f"github:{repo}@{branch}",
               "message": info["latest"]["message"]}


def _file_hash(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def apply_zip(zip_path: Path, info: dict | None = None, log=print) -> dict:
    """Copy program files from the zip over the installation. Never touches PROTECTED paths."""
    zip_path = Path(zip_path)
    if not zipfile.is_zipfile(zip_path):
        raise ValueError(f"{zip_path} is not a zip file.")
    req_before = _file_hash(PROJECT_ROOT / "requirements.txt")
    copied = 0
    with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(zip_path) as z:
        for n in z.namelist():
            if n.startswith("/") or ".." in Path(n).parts:
                raise ValueError(f"Unsafe path in zip: {n}")
        z.extractall(tmp)
        roots = [p for p in Path(tmp).iterdir()]
        src = roots[0] if len(roots) == 1 and roots[0].is_dir() else Path(tmp)
        if not (src / "tarbiyah" / "__main__.py").exists():
            raise ValueError("This zip does not contain Tarbiyah Hub (tarbiyah/__main__.py missing).")
        for f in src.rglob("*"):
            rel = f.relative_to(src)
            if rel.parts[0] in PROTECTED or f.is_dir():
                continue
            target = PROJECT_ROOT / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            copied += 1
    log(f"Updated {copied} program file(s). Your data, keys and settings were not touched.")
    if _file_hash(PROJECT_ROOT / "requirements.txt") != req_before:
        log("New Python packages are needed; installing (this can take a minute)...")
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(PROJECT_ROOT / "requirements.txt")],
                       check=True)
    info = info or {"sha": "zip:" + _file_hash(zip_path)[:8], "source": f"zip:{zip_path.name}"}
    from datetime import datetime

    info["installed_at"] = datetime.now().isoformat(timespec="seconds")
    _save_version(info)
    return {"files": copied, **info}


def last_update_log() -> str:
    try:
        return (_version_path().parent / "last-update.txt").read_text(encoding="utf-8")[-4000:]
    except OSError:
        return ""


def update_logged(zip_path: str | None = None) -> bool:
    """Run an update, print what happens and keep it in data/run/last-update.txt (shown in Settings)."""
    from datetime import datetime

    lines = [f"Update started {datetime.now():%Y-%m-%d %H:%M}"]

    def log(msg: str) -> None:
        print(msg)
        lines.append(msg)

    ok = True
    try:
        update(zip_path, log=log)
    except Exception as e:  # noqa: BLE001 - show a plain message to the user
        log(f"Update failed: {e}")
        ok = False
    try:
        (_version_path().parent / "last-update.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    return ok


def update(zip_path: str | None = None, log=print) -> dict:
    if zip_path:
        return apply_zip(Path(zip_path), log=log)
    status = check()
    if not status.get("configured"):
        raise RuntimeError(status["message"])
    if status.get("error"):
        raise RuntimeError(status["error"])
    if not status.get("update_available"):
        log("Already up to date.")
        return {"files": 0, **status.get("current", {})}
    with tempfile.TemporaryDirectory() as tmp:
        z, info = _download_github(Path(tmp))
        log(f"Downloaded version {info['sha']}: {info['message']}")
        return apply_zip(z, info, log=log)
