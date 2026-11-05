"""Adding sources from the dashboard form with exact keywords, exclude words and points to be considered."""
from types import SimpleNamespace as NS

from fastapi.testclient import TestClient

from tarbiyah import strict
from tarbiyah.db import session_scope
from tarbiyah.ingest.licensing import decide
from tarbiyah.ingest.pipeline import register_with_content
from tarbiyah.ingest.registry import ResourceIn
from tarbiyah.models import Resource, Source


def test_add_each_kind(env):
    from tarbiyah.api.app import app

    with TestClient(app) as c:
        w = c.post("/api/my-sources/add", json={"kind": "website", "address": "example.org/family/parenting",
                                                "keywords": ["تربية", "parenting"], "exclude": ["football"],
                                                "criteria": "Only practical guidance for parents of children under 12."}).json()
        assert w["adapter"] == "web_crawler" and w["config"]["section_lock"] is True and w["enabled"] is False
        assert w["config"]["start_urls"] == ["https://example.org/family/parenting"]
        st = w["config"]["strict"]
        assert st["enabled"] and st["keywords"] == ["تربية", "parenting"] and "under 12" in st["criteria"]
        y = c.post("/api/my-sources/add", json={"kind": "youtube", "address": "https://www.youtube.com/@SomeChannel"})
        assert y.status_code == 400 or y.json()["config"]["channel_ids"] == ["@SomeChannel"]  # @handles need the key
        y = c.post("/api/my-sources/add", json={"kind": "youtube", "address": "UCRtiU-lpcBSi-ipFKyfIkug", "name": "Lessons"}).json()
        assert y["config"]["channel_ids"] == ["UCRtiU-lpcBSi-ipFKyfIkug"] and y["name"] == "Lessons"
        t = c.post("/api/my-sources/add", json={"kind": "telegram", "address": "https://t.me/tarbiya_daily", "enable": True}).json()
        assert t["config"]["channels"] == ["tarbiya_daily"] and t["enabled"] is True
        r = c.post("/api/my-sources/add", json={"kind": "rss", "address": "https://example.org/feed"}).json()
        assert r["config"]["feeds"] == ["https://example.org/feed"]
        assert c.post("/api/my-sources/add", json={"kind": "website", "address": "nonsense"}).status_code == 400
        assert c.post("/api/my-sources/add", json={"kind": "telegram", "address": "x"}).status_code == 400
        mine = c.get("/api/my-sources").json()["sources"]
        assert len(mine) >= 4 and all(x["mine"] for x in mine)


def test_exact_keyword_rules():
    cfg = {**strict.DEFAULTS, "enabled": True, "keywords": ["تربية الأبناء", "parenting"], "exclude": ["football"]}
    item = lambda title, desc="", text="": NS(title=title, description=desc, text=text, keywords=[], resource_type="article",
                                               download_url=None, url="https://x.org/a", extra={})  # noqa: E731
    assert strict.pre_save(cfg, item("تَرْبِيَةُ الأبناءِ في البيت")) is None  # spelling/diacritics tolerant
    assert strict.pre_save(cfg, item("Market news")) == "none of the keywords"
    assert strict.pre_save(cfg, item("Parenting and football", "")).startswith("contains an excluded word")
    all_cfg = {**cfg, "keywords_mode": "all", "keywords": ["salah", "children"]}
    assert strict.pre_save(all_cfg, item("Teaching salah to children")) is None
    assert strict.pre_save(all_cfg, item("Teaching salah")).startswith("missing keyword")
    text_cfg = {**cfg, "keywords_in": "text", "keywords": ["القدوة"]}
    assert strict.pre_save(text_cfg, item("مقال", "", "الوالدان القدوة الأولى")) is None
    assert strict.pre_save({**text_cfg, "keywords_in": "title"}, item("مقال", "", "القدوة")) == "none of the keywords"


def test_points_to_be_considered_reach_the_ai(env, scripted_claude):
    from tarbiyah.agents.triage import triage_batch
    from tarbiyah.ai import schemas as S

    seen = []

    def respond(text):
        seen.append(text)
        ids = [int(x.split('"')[0]) for x in text.split('<item id="')[1:]]
        return S.TriageBatch(items=[S.TriageItem(id=i, relevance=70, pillars=["parents"], reason="ok") for i in ids])

    fake = scripted_claude({"triage": respond})
    with session_scope() as s:
        src = Source(key="crit", adapter="web_crawler", name="Crit", enabled=True,
                     config={"role": "monitor", "start_urls": ["https://x.org"],
                             "strict": {"enabled": True, "criteria": "Only for parents of teenagers."}})
        s.add(src)
        s.flush()
        for i in range(2):
            register_with_content(s, ResourceIn(title=f"Talking with teens {i}", url=f"https://x.org/{i}", resource_type="article",
                                                access=decide(None), collection_method="scrape:static", source_id=src.id))
        register_with_content(s, ResourceIn(title="General paper", url="https://y.org/p", resource_type="paper",
                                            access=decide(None), collection_method="api", source_key="openalex"))
    with session_scope() as s:
        triage_batch(s)
        triage_batch(s)
    calls = [c for c in fake.calls if c[0] == "triage"]
    assert len(calls) == 2  # one batch with the source's points, one without
    with session_scope() as s:
        assert s.query(Resource).filter(Resource.extra["triaged"].as_boolean().is_(True)).count() == 3
