"""My Sources: the person's own sources keep everything; similar sources are suggested from what they collect."""
from fastapi.testclient import TestClient

from tarbiyah.db import session_scope
from tarbiyah.ingest.licensing import decide
from tarbiyah.ingest.pipeline import process, register_with_content
from tarbiyah.ingest.registry import ResourceIn
from tarbiyah.models import Resource, Source

from .conftest import drain


def _item(s, src, i, title, desc="", extra=None):
    r, _ = register_with_content(s, ResourceIn(
        title=title, url=f"https://ex.org/{src.key}/{i}", resource_type="video", description=desc,
        access=decide(None), collection_method="youtube_feed", source_key=src.key, source_id=src.id, extra=extra or {}))
    process(s, r)
    return r


def test_my_sources_keep_everything_and_suggestions(env):
    from tarbiyah.api.app import app
    from tarbiyah.settings import set_setting

    with TestClient(app) as c:
        yt = c.post("/api/sources", json={"adapter": "youtube", "name": "My channel",
                                          "config": {"channel_ids": ["UCRtiU-lpcBSi-ipFKyfIkug"]}}).json()
        web = c.post("/api/sources", json={"adapter": "web_crawler", "name": "My site",
                                           "config": {"start_urls": ["https://mysite.org/"]}}).json()
    with session_scope() as s:
        set_setting(s, "auto_archive_below", 30)
        ysrc, wsrc = s.get(Source, yt["id"]), s.get(Source, web["id"])
        assert ysrc.config["added_by"] == "user"
        off = _item(s, ysrc, 0, "Weekly football results")  # unrelated, but from MY source: kept
        assert off.relevance == 0 and not off.archived
        for i in range(3):
            _item(s, ysrc, i + 1, f"Raising children lesson {i}",
                  "Parents and children tarbiyah. Also see https://www.youtube.com/@GoodTarbiyah and "
                  "https://youtube.com/channel/UCRtiU-lpcBSi-ipFKyfIkug and our Telegram t.me/tarbiya_channel "
                  "and t.me/joinchat/xyz and https://parenting-institute.org/articles")
        for i in range(2):
            r, _ = register_with_content(s, ResourceIn(
                title=f"Upbringing article {i}", url=f"https://mysite.org/a{i}", resource_type="article",
                access=decide(None), collection_method="scrape:static", source_key=wsrc.key, source_id=wsrc.id,
                extra={"outlinks": ["https://www.parenting-institute.org/x", "https://facebook.com/page",
                                    "https://mysite.org/self"]}))
        ids = off.id
    with TestClient(app) as c:
        found = c.post("/api/suggestions/refresh").json()
        d = c.get("/api/my-sources").json()
        assert [x["name"] for x in d["sources"]] == ["My channel", "My site"]
        assert d["sources"][0]["items"] == 4 and d["sources"][0]["collect_everything"]
        keys = {x["key"]: x for x in d["suggestions"]}
        assert found["suggestions"] == len(keys)
        assert set(keys) == {"youtube:@goodtarbiyah", "telegram:tarbiya_channel", "web:parenting-institute.org"}
        assert keys["web:parenting-institute.org"]["mentions"] == 5  # 3 videos + 2 site pages
        assert "My site" in keys["web:parenting-institute.org"]["from_sources"]
        # the already-monitored channel UCRtiU... is not suggested again; joinchat/facebook/own site ignored
        added = c.post("/api/suggestions/add", json={"key": "telegram:tarbiya_channel"}).json()
        assert added["adapter"] == "telegram" and added["config"]["channels"] == ["tarbiya_channel"]
        assert added["config"]["added_by"] == "user"
        c.post("/api/suggestions/dismiss", json={"key": "youtube:@goodtarbiyah"})
        c.post("/api/suggestions/refresh")
        left = {x["key"] for x in c.get("/api/my-sources").json()["suggestions"]}
        assert left == {"web:parenting-institute.org"}  # added and dismissed ones do not come back
        # switching "keep everything" off applies the relevance rules to that source again
        assert c.post(f"/api/my-sources/{yt['id']}/keep-everything", json={"on": False}).json()["changed"] == 1
        with session_scope() as s:
            assert s.get(Resource, ids).archived
        assert c.post(f"/api/my-sources/{yt['id']}/keep-everything", json={"on": True}).json()["changed"] == 1
        with session_scope() as s:
            assert not s.get(Resource, ids).archived
        # auto-add: strong suggestions become sources by themselves (their items stay relevance-filtered)
        c.patch("/api/settings", json={"auto_add_sources": True, "auto_add_min_mentions": 5})
        assert c.post("/api/suggestions/refresh").json()["auto_added"] == ["parenting-institute.org"]
        auto = [x for x in c.get("/api/my-sources").json()["sources"] if x["added_by"] == "auto"]
        assert auto and auto[0]["config"]["start_urls"] == ["https://parenting-institute.org/"] and not auto[0]["mine"]


def test_telegram_collects_older_history_over_runs(env, monkeypatch):
    from tarbiyah.sources import social
    from tarbiyah.sources.base import CollectContext

    def page(ids):
        return "".join(
            f'<div class="tgme_widget_message" data-post="ch/{i}"><div class="tgme_widget_message_text">post {i} '
            f'about tarbiyah</div><time datetime="2025-01-01T00:00:00+00:00"></time></div>' for i in ids)

    class R:
        def __init__(self, t):
            self.text = t

    def fetch(url, **kw):
        before = int(url.split("before=")[1]) if "before=" in url else 101
        return R(page(range(max(1, before - 20), before)))

    monkeypatch.setattr(social, "http", lambda: type("H", (), {"fetch": staticmethod(fetch)})())
    a = social.TelegramAdapter()
    state: dict = {}
    seen = set()
    for _ in range(6):
        for d in a.collect(CollectContext(source_config={"channels": ["ch"], "max_pages": 2}, checkpoint={}, state=state)):
            seen.add(d.url)
    assert len(seen) == 100 and state["history_done"]["ch"] is True


def test_arabic_source_names_get_unique_keys(env):
    from tarbiyah.api.app import app

    with TestClient(app) as c:
        a = c.post("/api/sources", json={"adapter": "youtube", "name": "قناة التربية",
                                         "config": {"channel_ids": ["UCRtiU-lpcBSi-ipFKyfIkug"]}})
        b = c.post("/api/sources", json={"adapter": "youtube", "name": "قناة أخرى",
                                         "config": {"channel_ids": ["UCcCfpDNl1Bi-LopV2noq_pg"]}})
        assert a.status_code == 200 and b.status_code == 200
        assert a.json()["key"] == "youtube-my" and b.json()["key"] == "youtube-my-2"


def test_daily_limit_shows_waiting_and_resumes_when_raised(env, monkeypatch):
    from tarbiyah.api.app import app
    from tarbiyah.http import BudgetExceeded
    from tarbiyah.jobs import queue
    from tarbiyah.models import Job
    from tarbiyah.sources import youtube

    def over(*a, **k):
        raise BudgetExceeded("Daily HTTP request budget reached")

    monkeypatch.setattr(youtube.YouTubeAdapter, "collect", over)
    with TestClient(app) as c:
        src = c.post("/api/sources", json={"adapter": "youtube", "name": "Ch",
                                           "config": {"channel_ids": ["UCRtiU-lpcBSi-ipFKyfIkug"]}}).json()
        c.post(f"/api/sources/{src['id']}/run")
        drain(20)
        card = [x for x in c.get("/api/sources").json() if x["id"] == src["id"]][0]
        assert card["health"] == "waiting" and "not a problem with this source" in card["last_error"]
        with session_scope() as s:
            job = s.query(Job).filter(Job.job_type == "collect_source").one()
            assert job.status == "queued" and job.run_after > queue.utcnow()
        c.patch("/api/settings", json={"daily_http_request_limit": 20000})
        card = [x for x in c.get("/api/sources").json() if x["id"] == src["id"]][0]
        assert card["health"] == "ready"
        with session_scope() as s:
            assert s.query(Job).filter(Job.job_type == "collect_source").one().run_after <= queue.utcnow()


def test_keywords_match_word_starts_and_apply_to_existing_items(env):
    from tarbiyah.api.app import app
    from tarbiyah.sources.base import matches_keywords as m

    assert not m(["son", "parent", "teen"], "The reason a transparent person studies at fourteen")
    assert m(["parent"], "Islamic Parenting Strategies") and m(["teen"], "Raising Teenagers")
    assert m(["أطفال"], "تربية الأطفال") and m(["تربية"], "التَّربية الإيمانية")
    with TestClient(app) as c:
        src = c.post("/api/sources", json={"adapter": "web_crawler", "name": "Yaqeen",
                                           "config": {"start_urls": ["https://yaqeen.example/"]}}).json()
        with session_scope() as s:
            ysrc = s.get(Source, src["id"])
            for i, t in enumerate(["Islamic Parenting Strategies", "The Reason for Creation", "Marriage in Islam"]):
                register_with_content(s, ResourceIn(title=t, url=f"https://yaqeen.example/{i}", resource_type="article",
                                                    access=decide(None), collection_method="scrape:static",
                                                    source_key=ysrc.key, source_id=ysrc.id))
        assert c.post(f"/api/my-sources/{src['id']}/apply-keywords", json={}).status_code == 400  # no keywords yet
        c.patch(f"/api/sources/{src['id']}", json={"config": {"keywords": ["parent", "marriage", "son"]}})
        prev = c.post(f"/api/my-sources/{src['id']}/apply-keywords", json={"dry_run": True}).json()
        assert prev["would_archive"] == 1 and prev["examples"][0]["title"] == "The Reason for Creation"
        assert c.post(f"/api/my-sources/{src['id']}/apply-keywords", json={"dry_run": False}).json()["archived"] == 1
        card = [x for x in c.get("/api/my-sources").json()["sources"] if x["id"] == src["id"]][0]
        assert card["items"] == 2 and card["archived"] == 1
