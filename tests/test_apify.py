"""Apify connector against a local stand-in for the Apify API (v2 run/poll/dataset flow).

This does NOT contact apify.com (unreachable from the development environment); it verifies
the request flow, cost caps, resume-after-restart and result mapping.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

import pytest

from tarbiyah.db import session_scope
from tarbiyah.jobs import queue
from tarbiyah.models import Job, Resource, Source
from tarbiyah.settings import set_setting

from .conftest import drain

ITEMS = [
    {"id": "7301", "text": "نصائح في تربية الأطفال على الصدق #تربية", "webVideoUrl": "https://www.tiktok.com/@murabbi/video/7301",
     "createTimeISO": "2026-10-20T08:00:00.000Z", "authorMeta": {"name": "murabbi"},
     "subtitles": [{"text": "السلام عليكم، اليوم نتحدث عن الصدق مع الأطفال", "start": 0}]},
    {"title": "Raising children with patience", "url": "https://www.youtube.com/watch?v=abcdefghijk",
     "text": "Lecture description", "date": "2026-09-01", "channelName": "Family Lectures", "id": "abcdefghijk"},
    {"unrelated": True},
]


class FakeApify(BaseHTTPRequestHandler):
    calls: list[dict] = []
    polls = 0
    status_after_polls = "SUCCEEDED"

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        u = urlsplit(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        FakeApify.calls.append({"path": u.path, "query": parse_qs(u.query), "body": body,
                                "auth": self.headers.get("Authorization")})
        if self.headers.get("Authorization") != "Bearer test-token":
            return self._send({"error": {"type": "token-not-provided"}}, 401)
        self._send({"data": {"id": f"run{len(FakeApify.calls)}", "status": "RUNNING", "defaultDatasetId": "ds1"}}, 201)

    def do_GET(self):
        u = urlsplit(self.path)
        if u.path.startswith("/v2/actor-runs/"):
            FakeApify.polls += 1
            st = FakeApify.status_after_polls if FakeApify.polls >= 2 else "RUNNING"
            return self._send({"data": {"id": u.path.rsplit("/", 1)[-1], "status": st, "defaultDatasetId": "ds1"}})
        if u.path == "/v2/datasets/ds1/items":
            return self._send(ITEMS)
        self._send({"error": "not found"}, 404)


@pytest.fixture()
def apify(env, monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeApify)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    FakeApify.calls, FakeApify.polls, FakeApify.status_after_polls = [], 0, "SUCCEEDED"
    monkeypatch.setenv("APIFY_TOKEN", "test-token")
    monkeypatch.setenv("TH_APIFY_BASE_URL", f"http://127.0.0.1:{srv.server_port}")
    from tarbiyah.config import reset_config_cache

    reset_config_cache()
    with session_scope() as s:
        for src in s.query(Source):
            src.enabled = False
        s.add(Source(key="apify-tiktok", adapter="apify", name="TikTok via Apify", enabled=True,
                     config={"role": "monitor", "actor": "clockworks/tiktok-scraper", "platform": "tiktok",
                             "resource_type": "video", "max_items": 500, "poll_seconds": 0.05,
                             "input": {"searchQueries": ["تربية الأطفال"], "resultsPerPage": 20}}))
    yield srv
    srv.shutdown()


def _collect():
    with session_scope() as s:
        src = s.query(Source).filter(Source.key == "apify-tiktok").one()
        return queue.enqueue(s, "collect_source", {"source_id": src.id}, group=src.key).id


def test_apify_run_maps_results_with_caps(apify):
    jid = _collect()
    drain(60)
    call = FakeApify.calls[0]
    assert call["path"] == "/v2/acts/clockworks~tiktok-scraper/runs"
    assert call["body"] == {"searchQueries": ["تربية الأطفال"], "resultsPerPage": 20}
    assert call["query"]["maxItems"] == ["50"]  # capped by apify_max_items_per_run, not the source's 500
    assert call["query"]["maxTotalChargeUsd"] == ["0.5"]
    with session_scope() as s:
        assert s.get(Job, jid).status == "succeeded"
        rs = {r.url: r for r in s.query(Resource).filter(Resource.source_key == "apify-tiktok")}
        assert len(rs) == 2  # the item without URL/text is skipped
        tk = rs["https://www.tiktok.com/@murabbi/video/7301"]
        assert tk.resource_type == "video" and tk.language == "ar" and tk.published_date == "2026-10-20"
        assert tk.collection_method == "apify:clockworks/tiktok-scraper" and tk.extra["transcript"]
        assert "الصدق مع الأطفال" in " ".join(c.text for c in tk.chunks)  # subtitles indexed
        assert {p.pillar for p in tk.pillars} >= {"children"}
        yt = rs["https://www.youtube.com/watch?v=abcdefghijk"]
        assert yt.title == "Raising children with patience" and yt.authors_text == "Family Lectures"
        src = s.query(Source).filter(Source.key == "apify-tiktok").one()
        assert src.health == "ok" and src.last_result["new"] == 2


def test_apify_daily_run_limit_and_resume(apify):
    with session_scope() as s:
        set_setting(s, "apify_daily_run_limit", 1)
    _collect()
    drain(60)
    assert len(FakeApify.calls) == 1
    jid = _collect()  # second run the same day: deferred to tomorrow, nothing billed
    drain(30)
    assert len(FakeApify.calls) == 1
    with session_scope() as s:
        job = s.get(Job, jid)
        assert job.status == "queued" and "Apify run limit" in job.error
        # a restarted worker with a saved run id keeps polling that run instead of starting a new one
        job.checkpoint = {"apify_run_id": "run1"}
        from tarbiyah.db import utcnow

        job.run_after = utcnow()
        set_setting(s, "apify_daily_run_limit", 0)
    FakeApify.polls = 0
    drain(30)
    assert len(FakeApify.calls) == 1
    with session_scope() as s:
        assert s.get(Job, jid).status == "succeeded"


def test_apify_failed_run_and_missing_token(apify, monkeypatch):
    FakeApify.status_after_polls = "FAILED"
    jid = _collect()
    drain(30)
    with session_scope() as s:
        job = s.get(Job, jid)
        assert "FAILED" in job.error and "apify_run_id" not in job.checkpoint  # retry will start a fresh run
    monkeypatch.setenv("APIFY_TOKEN", "")
    from tarbiyah.config import reset_config_cache
    from tarbiyah.sources.registry import ADAPTERS

    reset_config_cache()
    assert not ADAPTERS["apify"].is_configured()


def test_apify_keywords_keep_only_matching_posts(apify):
    with session_scope() as s:
        src = s.query(Source).filter(Source.key == "apify-tiktok").one()
        src.config = {**src.config, "keywords": ["تربيه", "اطفال"]}  # spelling variants still match
    _collect()
    drain(60)
    with session_scope() as s:
        rs = [r.url for r in s.query(Resource).filter(Resource.source_key == "apify-tiktok")]
        assert rs == ["https://www.tiktok.com/@murabbi/video/7301"]  # the English lecture has none of the words
        src = s.query(Source).filter(Source.key == "apify-tiktok").one()
        assert any("skipped" in m for m in src.last_result["messages"])
