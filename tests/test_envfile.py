"""Editing keys and AI settings from the dashboard (.env)."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def envdir(env, tmp_path, monkeypatch):
    from tarbiyah import config, envfile

    root = tmp_path / "install"
    root.mkdir()
    (root / ".env").write_text("# my notes\nTH_AI_PROVIDER=claude\nANTHROPIC_API_KEY=sk-ant-oldkey1234\n"
                               "CUSTOM_THING=keep me\nYOUTUBE_API_KEY=\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", root / ".env")
    yield root
    envfile.reload_now()


def test_edit_env_keeps_lines_masks_and_reloads(envdir):
    from tarbiyah.ai.claude import claude
    from tarbiyah.api.app import app
    from tarbiyah.config import get_config

    with TestClient(app) as c:
        view = {f["key"]: f for f in c.get("/api/env").json()["fields"]}
        assert view["ANTHROPIC_API_KEY"]["value"] == "…1234" and view["ANTHROPIC_API_KEY"]["is_set"]
        assert "oldkey" not in c.get("/api/env").text  # secrets never go to the browser
        r = c.patch("/api/env", json={"TH_AI_PROVIDER": "gemini", "TH_AI_MODEL": "Gemini 2.5 Flash",
                                      "TH_AI_API_KEY": " 'AIzaNEWKEY99' ", "ANTHROPIC_API_KEY": ""})
        assert r.status_code == 200 and r.json()["provider"] == "gemini"
        text = (envdir / ".env").read_text()
        assert "# my notes" in text and "CUSTOM_THING=keep me" in text
        assert "ANTHROPIC_API_KEY=sk-ant-oldkey1234" in text  # empty secret field = keep
        assert "TH_AI_API_KEY=AIzaNEWKEY99" in text and text.count("TH_AI_PROVIDER=") == 1
        assert get_config().ai_api_key == "AIzaNEWKEY99" and claude().name == "gemini"
        assert c.patch("/api/env", json={"ANTHROPIC_API_KEY": "__clear__"}).status_code == 200
        assert "ANTHROPIC_API_KEY=\n" in (envdir / ".env").read_text()
        assert c.patch("/api/env", json={"TH_DATA_DIR": "/x"}).status_code == 400
        assert c.patch("/api/env", json={"TH_AI_PROVIDER": "bogus"}).status_code == 400
        assert c.patch("/api/env", json={"YOUTUBE_API_KEY": "a b"}).status_code == 400
        # other web pages cannot read or change keys
        assert c.get("/api/env", headers={"origin": "https://evil.example"}).status_code == 403
        assert c.patch("/api/env", json={"TH_AI_MODEL": "x"}, headers={"host": "evil.example"}).status_code == 403


def test_worker_picks_up_notepad_edits(envdir):
    import os
    import time

    from tarbiyah import envfile
    from tarbiyah.config import get_config

    envfile.reload_now()
    assert envfile.reload_if_changed() is False
    p = envdir / ".env"
    p.write_text(p.read_text() + "YOUTUBE_API_KEY=fresh\n")
    os.utime(p, (time.time() + 5, time.time() + 5))
    assert envfile.reload_if_changed() is True
    assert get_config().youtube_api_key == "fresh"
