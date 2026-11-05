"""Large sources: classified + anchored searches, a gate before saving, resting poor sources."""
from tarbiyah import scope
from tarbiyah.db import session_scope
from tarbiyah.ingest.licensing import decide
from tarbiyah.ingest.registry import ResourceIn
from tarbiyah.models import Resource, SearchLog, Source


def _r(title, desc="", lang="en", journal=None):
    return ResourceIn(title=title, description=desc, url=f"https://ex.org/{abs(hash(title))}", resource_type="paper",
                      language=lang, access=decide(None), collection_method="api", source_key="openalex",
                      extra={"journal": journal} if journal else {})


def test_scoped_queries():
    assert scope.scoped_query("openalex", "parenting adolescents", "en") == \
        "(parenting adolescents) AND (Islam OR Islamic OR Muslim OR Muslims OR Quran)"
    assert scope.scoped_query("openalex", "Muslim parenting", "en") == "Muslim parenting"  # already anchored
    assert scope.scoped_query("openlibrary", "تربية الأبناء", None) == "تربية الأبناء"
    assert 'subject:"Islam"' in scope.scoped_query("eric", "child rearing", "en")
    assert scope.scoped_query("unknown", "x", "en") == "x"


def test_gate_keeps_only_islamic_pillar_results(env):
    items = [
        _r("Islamic parenting and children's moral development", "How Muslim parents raise children with faith."),
        _r("Parenting styles and adolescent outcomes", "A survey of parents and teenagers in public schools."),  # no anchor
        _r("Stock market volatility in emerging economies", "Islamic banking and finance."),  # anchor, no pillar
        _r("تربية الأبناء على الصدق والأمانة في البيت", "دور الوالدين في تربية الأطفال وتأديبهم", lang="ar"),
        _r("Teacher training for Quran schools", "Preparing educators and mentors for halaqa teaching."),
    ]
    with session_scope() as s:
        kept, reasons = scope.gate(s, items, "en")
    titles = [d.title for d in kept]
    assert titles == [items[0].title, items[3].title, items[4].title]
    assert reasons == {"no Islamic connection": 1, "not about a pillar": 1}


def test_gate_with_ai_judgement(env, scripted_claude):
    from tarbiyah.ai import schemas as S

    def respond(text):
        assert "ISLAMIC tarbiyah" in text or "<source>" in text
        return S.TriageBatch(items=[S.TriageItem(id=0, relevance=85, pillars=["parents"], reason="Muslim parents."),
                                    S.TriageItem(id=1, relevance=20, pillars=[], reason="Secular survey.")])

    scripted_claude({"triage": respond})
    items = [_r("Raising children: Muslim parents' practices"), _r("Parenting styles and outcomes")]
    with session_scope() as s:
        kept, reasons = scope.gate(s, items, "en")
    assert [d.title for d in kept] == ["Raising children: Muslim parents' practices"]
    assert kept[0].extra["relevance_ai"] == 85 and kept[0].extra["triaged"] is True
    assert reasons == {"AI: not relevant enough": 1}


def test_search_handler_gates_logs_and_rests_poor_sources(env, monkeypatch):
    from tarbiyah.agents.discovery import enabled_search_sources, poor_sources
    from tarbiyah.jobs import queue
    from tarbiyah.sources import academic

    from .conftest import drain

    seen_queries = []

    def fake_search(self, query, lang, limit):
        seen_queries.append(query)
        return [_r("Islamic parenting of young children", "Muslim parents and child upbringing."),
                _r("Parenting styles and adolescent outcomes", "Survey in public schools."),
                _r("Solar panels efficiency", "Engineering study.")]

    monkeypatch.setattr(academic.OpenAlexAdapter, "search", fake_search)
    with session_scope() as s:
        src = s.query(Source).filter(Source.key == "openalex").one()
        queue.enqueue(s, "search_source", {"source_id": src.id, "query": "child upbringing", "lang": "en"})
        queue.enqueue(s, "search_source", {"source_id": src.id, "query": 'subject:"Muslim children"', "raw": True})
    drain(30)
    assert seen_queries[0] == "(child upbringing) AND (Islam OR Islamic OR Muslim OR Muslims OR Quran)"
    assert seen_queries[1] == 'subject:"Muslim children"'  # sweeps / curated searches run as written
    with session_scope() as s:
        logs = s.query(SearchLog).filter(SearchLog.adapter == "openalex").all()
        assert [(lg.results, lg.kept) for lg in logs] == [(3, 1), (3, 1)]
        assert logs[0].gate == {"no Islamic connection": 1, "not about a pillar": 1}
        assert s.query(Resource).filter(Resource.source_key == "openalex").count() == 1  # duplicates merged
        # Crossref and YouTube are not used for research; a source with poor yield rests
        names = {x.adapter for x in enabled_search_sources(s)}
        assert "crossref" not in names and "youtube" not in names
        for _ in range(8):
            s.add(SearchLog(adapter="eric", query="q", query_key="k", results=20, kept=1, status="ok"))
        s.flush()
        assert "eric" in poor_sources(s) and "openalex" not in poor_sources(s)
        assert "eric" not in {x.adapter for x in enabled_search_sources(s)}


def test_precise_query_rejected_falls_back_to_plain(env, monkeypatch):
    from tarbiyah.http import FetchError
    from tarbiyah.jobs import queue
    from tarbiyah.sources import academic

    from .conftest import drain

    seen = []

    def fake(self, query, lang, limit):
        seen.append(query)
        if "subject:" in query:
            raise FetchError("HTTP 400", status=400)
        return [_r("Islamic education of Muslim children", "Raising children with faith.")]

    monkeypatch.setattr(academic.EricAdapter, "search", fake)
    with session_scope() as s:
        src = s.query(Source).filter(Source.key == "eric").one()
        queue.enqueue(s, "search_source", {"source_id": src.id, "query": "child rearing", "lang": "en"})
    drain(20)
    assert seen[0].startswith("(child rearing) AND (subject:") and seen[1] == "child rearing"
    with session_scope() as s:
        lg = s.query(SearchLog).filter(SearchLog.adapter == "eric").one()
        assert lg.status == "ok" and lg.kept == 1


def test_gate_applies_to_earlier_large_source_items(env):
    from fastapi.testclient import TestClient

    from tarbiyah.api.app import app
    from tarbiyah.ingest.pipeline import register_with_content

    with session_scope() as s:
        for t, d in [("Islamic parenting of young children", "Muslim parents and upbringing."),
                     ("Parenting styles and adolescent outcomes", "Survey in public schools."),
                     ("Solar panels efficiency", "Engineering.")]:
            register_with_content(s, _r(t, d))
    with TestClient(app) as c:
        prev = c.post("/api/curation/large-gate", json={"dry_run": True}).json()
        assert prev["would_archive"] == 2
        assert prev["reasons"] == {"no Islamic connection": 1, "not about a pillar": 1}
        assert c.post("/api/curation/large-gate", json={"dry_run": False}).json()["archived"] == 2
        assert c.get("/api/resources").json()["total"] == 1
        assert c.get("/api/curation").json()["search_precision"] == []
