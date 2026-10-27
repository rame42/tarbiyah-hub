"""Shared fixtures: an isolated data directory per test, a local test website, and a
*scripted* Claude provider used ONLY to test the plumbing around AI calls (storage,
quote verification, limits). It is a test double, not an AI integration."""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    """Fresh database + data folder, no API keys, permissive storage limits."""
    monkeypatch.setenv("TH_DATA_DIR", str(tmp_path / "data"))
    for k in ("ANTHROPIC_API_KEY", "VOYAGE_API_KEY", "YOUTUBE_API_KEY", "CORE_API_KEY", "REDDIT_CLIENT_ID",
              "REDDIT_CLIENT_SECRET", "FACEBOOK_ACCESS_TOKEN", "INSTAGRAM_ACCESS_TOKEN", "X_BEARER_TOKEN",
              "TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"):
        monkeypatch.setenv(k, "")
    from tarbiyah import http as http_mod
    from tarbiyah.ai import claude as claude_mod
    from tarbiyah.config import reset_config_cache
    from tarbiyah.db import reset_engine, session_scope
    from tarbiyah.search import semantic

    reset_config_cache()
    reset_engine()
    http_mod._client = None
    claude_mod.set_provider(None)
    semantic.set_embedder(None)
    from tarbiyah.bootstrap import init_app
    from tarbiyah.settings import _pending, set_setting

    _pending.clear()
    init_app()
    with session_scope() as s:
        set_setting(s, "min_free_disk_gb", 0.01)
    yield tmp_path / "data"
    claude_mod.set_provider(None)
    semantic.set_embedder(None)
    reset_engine()
    reset_config_cache()


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    from tests.fixtures.make_fixtures import build_all

    return build_all()


@pytest.fixture(scope="session")
def site():
    """Bilingual test website served over real HTTP on 127.0.0.1."""
    from tests.fixtures.site import build_site, serve

    root = Path(tempfile.mkdtemp(prefix="th_site_"))
    srv, base = serve(root)
    build_site(root, base)
    yield {"root": root, "base": base}
    srv.shutdown()


class ScriptedClaude:
    """Test double for ClaudeProvider: returns pre-built structured outputs per task."""

    def __init__(self, responses: dict[str, Callable[[str], Any]]):
        from tarbiyah.ai.claude import Usage

        self.responses = responses
        self.calls: list[tuple[str, str]] = []
        self.last_usage = Usage(100, 50, 0.0014, "scripted-test-double")

    def available(self) -> bool:
        return True

    def configured(self) -> bool:
        return True

    def model_for(self, task: str) -> str:
        return "scripted-test-double"

    def status(self) -> dict:
        return {"configured": True, "enabled": True, "model": "scripted-test-double"}

    def structured(self, task, system, content, schema, max_tokens=16000, effort=None):
        text = content if isinstance(content, str) else str(content)
        self.calls.append((task, text))
        if task not in self.responses:
            raise AssertionError(f"unexpected AI task {task}")
        return self.responses[task](text)

    def text(self, task, system, content, max_tokens=32000, effort=None):
        text = content if isinstance(content, str) else str(content)
        self.calls.append((task, text))
        return self.responses[task](text)


@pytest.fixture()
def scripted_claude():
    from tarbiyah.ai import claude as claude_mod

    def install(responses: dict[str, Callable[[str], Any]]) -> ScriptedClaude:
        fake = ScriptedClaude(responses)
        claude_mod.set_provider(fake)  # type: ignore[arg-type]
        return fake

    yield install
    claude_mod.set_provider(None)


def drain(seconds: int = 120, concurrency: int = 2) -> None:
    from tarbiyah.jobs.worker import Worker

    w = Worker(concurrency=concurrency, with_scheduler=False)
    w.startup()
    w.drain(timeout=seconds)
    w.pool.shutdown(wait=True)
