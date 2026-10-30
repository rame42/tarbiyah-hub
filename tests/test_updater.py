"""In-place updates replace program files only; data/, .env, .venv/ and backups/ are never touched."""
import zipfile

import pytest

from tarbiyah import updater


def _install(root):
    (root / "tarbiyah").mkdir(parents=True)
    (root / "tarbiyah" / "__main__.py").write_text("old")
    (root / "requirements.txt").write_text("same\n")
    (root / "data").mkdir()
    (root / "data" / "tarbiyah.db").write_text("MY DATABASE")
    (root / ".env").write_text("ANTHROPIC_API_KEY=secret")
    (root / "backups").mkdir()
    (root / "backups" / "b.zip").write_text("backup")


def _zip(path, files):
    with zipfile.ZipFile(path, "w") as z:
        for name, content in files.items():
            z.writestr("tarbiyah-hub/" + name, content)


def test_update_from_zip_keeps_user_data(env, tmp_path, monkeypatch):
    root = tmp_path / "install"
    _install(root)
    monkeypatch.setattr(updater, "PROJECT_ROOT", root)
    z = tmp_path / "new.zip"
    _zip(z, {"tarbiyah/__main__.py": "new", "tarbiyah/new_module.py": "x", "requirements.txt": "same\n",
             "data/tarbiyah.db": "EMPTY DATABASE FROM ZIP", ".env": "ANTHROPIC_API_KEY=", "update.bat": "bat"})
    res = updater.update(str(z), log=lambda m: None)
    assert (root / "tarbiyah" / "__main__.py").read_text() == "new"
    assert (root / "tarbiyah" / "new_module.py").exists() and (root / "update.bat").exists()
    assert (root / "data" / "tarbiyah.db").read_text() == "MY DATABASE"  # never overwritten
    assert (root / ".env").read_text() == "ANTHROPIC_API_KEY=secret"
    assert (root / "backups" / "b.zip").read_text() == "backup"
    assert res["files"] == 4  # __main__, new_module, requirements.txt, update.bat and updater.installed_version()["source"] == "zip:new.zip"


def test_update_rejects_unrelated_or_unsafe_zips(env, tmp_path, monkeypatch):
    root = tmp_path / "install"
    _install(root)
    monkeypatch.setattr(updater, "PROJECT_ROOT", root)
    other = tmp_path / "other.zip"
    _zip(other, {"readme.txt": "not tarbiyah"})
    with pytest.raises(ValueError):
        updater.update(str(other), log=lambda m: None)
    assert (root / "tarbiyah" / "__main__.py").read_text() == "old"
    assert updater._repo()[0] == "rame42/tarbiyah-hub"  # no TH_UPDATE_REPO: the project's own repository


def test_update_messages_are_plain_and_env_is_tolerant(env, monkeypatch, tmp_path):
    from tarbiyah import updater

    envf = tmp_path / ".env"
    envf.write_text('﻿TH_UPDATE_REPO = "me/repo"\nTH_UPDATE_TOKEN=\n', encoding="utf-8")
    monkeypatch.setattr(updater, "PROJECT_ROOT", tmp_path)
    monkeypatch.delenv("TH_UPDATE_REPO", raising=False)
    monkeypatch.delenv("TH_UPDATE_TOKEN", raising=False)
    assert updater._repo()[0] == "me/repo"

    class R:
        status_code, text = 404, '{"message":"Not Found"}'

    monkeypatch.setattr(updater.requests, "get", lambda *a, **k: R())
    info = updater.check()
    assert "private" in info["error"] and "TH_UPDATE_TOKEN" in info["error"]
    assert updater.update_logged() is False
    assert "Update failed" in updater.last_update_log() and "private" in updater.last_update_log()
    R.status_code = 401
    envf.write_text("TH_UPDATE_REPO=me/repo\nTH_UPDATE_TOKEN=github_pat_x\n", encoding="utf-8")
    assert "rejected TH_UPDATE_TOKEN" in updater.check()["error"]
