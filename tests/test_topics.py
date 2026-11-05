"""The topic map: precise multi-word searches for the large sources."""
from fastapi.testclient import TestClient

from tarbiyah import topics as tm
from tarbiyah.db import session_scope
from tarbiyah.models import SearchLog, SearchTopic, Source

from .conftest import drain


def test_seed_link_and_vague(env):
    with session_scope() as s:
        assert tm.ensure_seeded(s) == 45
        assert tm.ensure_seeded(s) == 0
        by = {}
        for t in s.query(SearchTopic):
            by.setdefault(t.pillar, []).append(t)
            assert t.phrases_en and t.phrases_ar and not any(tm.is_vague(p) for p in t.phrases_en + t.phrases_ar)
        assert {k: len(v) for k, v in by.items()} == {"children": 15, "parents": 15, "murabbi": 15}
        linked = tm.link(s, "How can parents teach prayer (salah) to young children?", ["children"])
        assert linked[0].name_en == "Teaching salah to children"
        linked = tm.link(s, "ما صفات المربي الناجح في الحلقات القرآنية؟", ["murabbi"])
        assert {t.name_en for t in linked} & {"Qualities of the murabbi", "Quran and halaqa teacher training"}
        fallback = tm.link(s, "xyz", ["parents"])
        assert len(fallback) == 2 and all(t.pillar == "parents" for t in fallback)
    assert tm.is_vague("parenting") and tm.is_vague("تربية") and tm.is_vague('"children"')
    assert not tm.is_vague("Muslim parenting styles") and not tm.is_vague("تربية الأبناء")


def test_research_uses_topics_refuses_vague_and_sweeps(env, monkeypatch):
    from tarbiyah.agents.discovery import investigate
    from tarbiyah.jobs import queue
    from tarbiyah.models import Job, ResearchQuestion
    from tarbiyah.sources import academic

    seen = []
    monkeypatch.setattr(academic.OpenAlexAdapter, "search", lambda self, q, lang, limit: seen.append(q) or [])
    with session_scope() as s:
        for src in s.query(Source):
            src.enabled = src.key == "openalex"
        q = ResearchQuestion(text="How do parents teach salah to children?", text_alt="كيف يعلم الوالدان الأطفال الصلاة؟",
                             pillars=["children"], kind="planner", status="open", dedupe_key="t-salah")
        s.add(q)
        s.flush()
        investigate(s, q)
        jobs = [j.payload for j in s.query(Job).filter(Job.job_type == "search_source")]
        assert jobs and all(j["topic_id"] for j in jobs)  # the large source only gets topic phrases
        assert {j["query"] for j in jobs} >= {"teaching prayer to children", "تعليم الأطفال الصلاة"}
        oa = s.query(Source).filter(Source.key == "openalex").one()
        queue.enqueue(s, "search_source", {"source_id": oa.id, "query": "parenting", "lang": "en"})
    drain(30)
    assert "parenting" not in " ".join(seen)
    with session_scope() as s:
        assert s.query(SearchLog).filter(SearchLog.status == "too_vague").count() == 1
        logs = s.query(SearchLog).filter(SearchLog.topic_id.is_not(None)).all()
        assert logs and all(lg.status == "ok" for lg in logs)
        # topic sweep: one topic every two hours
        queue.enqueue(s, "maintenance", {})
    drain(30)
    with session_scope() as s:
        swept = s.query(SearchTopic).filter(SearchTopic.last_swept_at.is_not(None)).all()
        assert len(swept) == 1
        assert tm.next_sweep_topic(s) is None  # not again within two hours


def test_topic_api_edit_and_stats(env):
    from tarbiyah.api.app import app

    with TestClient(app) as c:
        d = c.get("/api/topics").json()["topics"]
        assert len(d) == 45
        t = d[0]
        assert c.patch(f"/api/topics/{t['id']}", json={"phrases_en": ["parenting"]}).status_code == 400  # vague
        r = c.patch(f"/api/topics/{t['id']}", json={"phrases_en": ["teaching wudu to children"], "enabled": False}).json()
        assert r["phrases_en"] == ["teaching wudu to children"] and r["enabled"] is False
        new = c.post("/api/topics", json={"pillar": "parents", "phrases_ar": ["تربية الأبناء على الحياء"]}).json()
        assert new["name_ar"] == "تربية الأبناء على الحياء" and new["origin"] == "user"
        with session_scope() as s:
            for _ in range(5):
                s.add(SearchLog(adapter="openalex", query="q", query_key="k", results=20, kept=1, status="ok",
                                topic_id=new["id"]))
        row = [x for x in c.get("/api/topics").json()["topics"] if x["id"] == new["id"]][0]
        assert row["stats"]["yield_pct"] == 5 and row["stats"]["weak"] is True
        assert c.delete(f"/api/topics/{new['id']}").json()["deleted"]
