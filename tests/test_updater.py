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
    assert updater.check()["configured"] is False  # no TH_UPDATE_REPO: explains how to update by zip
