"""Moving to a new folder: the old library, files and keys are copied; the old folder is untouched."""
import shutil
import sqlite3

import pytest

from tarbiyah import import_old as io


def _fake_install(root, items=3, files=2, env="ANTHROPIC_API_KEY=old-key\nTH_AI_PROVIDER=gemini\n"):
    (root / "tarbiyah").mkdir(parents=True)
    (root / "tarbiyah" / "__main__.py").write_text("")
    (root / "start.bat").write_text("")
    data = root / "data"
    (data / "files").mkdir(parents=True)
    (data / "run").mkdir()
    con = sqlite3.connect(data / "tarbiyah.db")
    con.execute("CREATE TABLE resources (id INTEGER PRIMARY KEY, local_path TEXT)")
    for i in range(items):
        con.execute("INSERT INTO resources (local_path) VALUES (?)", (f"files/{i}.pdf" if i < files else None,))
    con.commit()
    con.close()
    for i in range(files):
        (data / "files" / f"{i}.pdf").write_bytes(b"%PDF " + bytes(i))
    (data / "run" / "worker.pid").write_text("999999")
    (root / ".env").write_text(env)
    return data


def test_import_old_copies_everything_and_keeps_old(tmp_path, monkeypatch):
    old = tmp_path / "Downloads" / "tarbiyah-hub final update"
    old_data = _fake_install(old, items=5, files=3)
    new = tmp_path / "new" / "tarbiyah-hub"
    (new / "tarbiyah").mkdir(parents=True)
    (new / "tarbiyah" / "__main__.py").write_text("")
    (new / ".env").write_text("TH_UPDATE_REPO=x/y\n")
    (new / "data").mkdir()
    (new / "data" / "tarbiyah.db").write_bytes(b"")  # the fresh, empty install
    monkeypatch.setattr(io, "PROJECT_ROOT", new)
    before = sorted(p.relative_to(old) for p in old.rglob("*"))

    # the person may drag the folder above, the folder itself or its data folder
    assert io.find_old_install(old.parent)[0] == old
    assert io.find_old_install(old_data)[0] == old
    res = io.import_old(str(old))
    assert res["items"] == 5 and res["files"] == 3
    assert (new / "data" / "files" / "2.pdf").read_bytes() == (old_data / "files" / "2.pdf").read_bytes()
    assert not (new / "data" / "run" / "worker.pid").exists()
    assert "old-key" in (new / ".env").read_text()
    assert any(k.startswith("data-before-import-") for k in res["kept_aside"])
    assert sorted(p.relative_to(old) for p in old.rglob("*")) == before  # old folder untouched

    with pytest.raises(ValueError, match="same folder"):
        io.import_old(str(new))
    (tmp_path / "Pictures").mkdir()
    with pytest.raises(ValueError, match="No Tarbiyah Hub library"):
        io.import_old(str(tmp_path / "Pictures"))
    assert io.import_old(str(old_data / "files"))["items"] == 5  # a folder inside the old install works too
    with pytest.raises(ValueError, match="does not exist"):
        io.import_old(str(tmp_path / "nope"))


def test_import_old_refuses_while_old_app_runs(tmp_path, monkeypatch):
    import os

    old = tmp_path / "old"
    data = _fake_install(old)
    (data / "run" / "worker.pid").write_text(str(os.getpid()))  # "running"
    new = tmp_path / "new"
    new.mkdir()
    monkeypatch.setattr(io, "PROJECT_ROOT", new)
    with pytest.raises(RuntimeError, match="still running"):
        io.import_old(str(old))
    shutil.rmtree(new, ignore_errors=True)
