"""Automatic updates: install, verify, roll back on failure, restart; never touch data."""
from tarbiyah import autoupdate, updater


def _install(tmp_path, monkeypatch):
    root = tmp_path / "app"
    (root / "tarbiyah").mkdir(parents=True)
    (root / "tarbiyah" / "core.py").write_text("v1")
    (root / "start.bat").write_text("start v1")
    (root / "data").mkdir()
    (root / "data" / "tarbiyah.db").write_text("my library")
    (root / ".env").write_text("TH_AI_API_KEY=secret")
    (root / "data-before-import-1").mkdir()
    (root / "data-before-import-1" / "big.db").write_text("old copy")
    monkeypatch.setattr(autoupdate, "PROJECT_ROOT", root)
    monkeypatch.setattr(updater, "check", lambda: {"update_available": True, "latest": {"sha": "abc123", "message": "new"}})
    return root


def _fake_update(root, content):
    def update(zip_path=None, log=print):
        (root / "tarbiyah" / "core.py").write_text(content)
        (root / "tarbiyah" / "new_module.py").write_text("added")
        log("Updated 2 program file(s).")
    return update


def test_successful_update_restarts(env, tmp_path, monkeypatch):
    root = _install(tmp_path, monkeypatch)
    monkeypatch.setattr(updater, "update", _fake_update(root, "v2"))
    monkeypatch.setattr(autoupdate, "self_check", lambda: (True, ""))
    calls = []
    res = autoupdate.run_self_update(lambda m: None, stop=lambda log: calls.append("stop"), start=lambda: calls.append("start"))
    assert res == {"updated": True, "version": "abc123"} and calls == ["stop", "start"]
    assert (root / "tarbiyah" / "core.py").read_text() == "v2"
    assert (root / "data" / "tarbiyah.db").read_text() == "my library" and (root / ".env").exists()
    log = (autoupdate._run_dir() / "last-update.txt").read_text()
    assert "starts correctly" in log and "Starting Tarbiyah Hub again" in log
    names = autoupdate.program_files(root)
    assert all("data" not in p.relative_to(root).parts[0] for p in names)  # library copies never in the backup


def test_broken_update_is_rolled_back(env, tmp_path, monkeypatch):
    root = _install(tmp_path, monkeypatch)
    monkeypatch.setattr(updater, "update", _fake_update(root, "BROKEN"))
    monkeypatch.setattr(autoupdate, "self_check", lambda: (False, "SyntaxError"))
    calls = []
    res = autoupdate.run_self_update(lambda m: None, stop=lambda log: calls.append("stop"), start=lambda: calls.append("start"))
    assert res["updated"] is False and "did not start correctly" in res["error"]
    assert (root / "tarbiyah" / "core.py").read_text() == "v1"  # previous version is back
    assert calls == ["stop", "start"]  # and the app runs again
    assert "previous version is back" in (autoupdate._run_dir() / "last-update.txt").read_text()
    assert not (autoupdate._run_dir() / autoupdate.LOCK_NAME).exists()


def test_up_to_date_does_nothing_and_checks_every_few_hours(env, tmp_path, monkeypatch):
    root = _install(tmp_path, monkeypatch)
    monkeypatch.setattr(updater, "check", lambda: {"update_available": False})
    calls = []
    assert autoupdate.run_self_update(lambda m: None, stop=lambda log: calls.append("stop"),
                                      start=lambda: calls.append("start")) == {"updated": False}
    assert calls == []  # not stopped, not restarted

    from tarbiyah.db import session_scope

    monkeypatch.setattr(updater, "check", lambda: {"update_available": True})
    spawned = []
    monkeypatch.setattr(autoupdate, "spawn", lambda: spawned.append(1) or True)
    with session_scope() as s:
        assert autoupdate.maybe_check(s) == "started"
    with session_scope() as s:
        assert autoupdate.maybe_check(s) is None  # checked less than 6 hours ago
    assert spawned == [1]
    (root / ".git").mkdir()
    with session_scope() as s:
        s.query(__import__("tarbiyah.models", fromlist=["Setting"]).Setting).filter_by(key="_update_checked_at").delete()
    with session_scope() as s:
        assert autoupdate.maybe_check(s) is None  # developer copies are never auto-updated
