"""Research loop: planning, question generation/limits, discovery, synthesis, QA, reports, outputs.

Runs (1) without any AI (the default free mode) and (2) with a SCRIPTED test double in
place of Claude, to verify how the system stores, verifies and limits AI output. The
scripted double is not an AI integration; live Claude calls need ANTHROPIC_API_KEY.
"""
from datetime import date

import pytest

from tarbiyah.agents.questions import Candidate, admit
from tarbiyah.ai import schemas as S
from tarbiyah.db import session_scope
from tarbiyah.ingest.licensing import decide
from tarbiyah.ingest.pipeline import import_local_file, process
from tarbiyah.ingest.registry import ResourceIn
from tarbiyah.jobs import queue
from tarbiyah.models import (
    Chunk, Claim, DailyReport, Finding, Job, Output, ResearchObjective, ResearchQuestion, Resource, SearchLog, Source,
)
from tarbiyah.settings import set_setting
from tarbiyah.sources.base import AdapterInfo, SourceAdapter
from tarbiyah.sources.registry import ADAPTERS

from .conftest import drain


class LocalSearch(SourceAdapter):
    """Search adapter over the local test website (stands in for an online index in tests)."""

    info = AdapterInfo(name="local_search", label="Local test index", kind="academic", description="test",
                       capabilities=("search",), resource_types=("article",), default_enabled=True)

    def __init__(self, base: str):
        self.base = base
        self.queries: list[tuple[str, str | None]] = []

    def search(self, query, lang, limit):
        self.queries.append((query, lang))
        return [ResourceIn(title="", url=f"{self.base}/en/posts/teacher-training.html", resource_type="article",
                           source_key="local_search", collection_method="api", access=decide(None),
                           extra={"fetch_page": True}),
                ResourceIn(title="", url=f"{self.base}/ar/articles/murabbi.html", resource_type="article",
                           source_key="local_search", collection_method="api", access=decide(None),
                           extra={"fetch_page": True})]


@pytest.fixture()
def local_search(env, site):
    a = LocalSearch(site["base"])
    ADAPTERS["local_search"] = a
    with session_scope() as s:
        for src in s.query(Source):
            src.enabled = False
        s.add(Source(key="local_search", adapter="local_search", name="Local", enabled=True, config={"role": "search"}))
    yield a
    ADAPTERS.pop("local_search", None)


def test_research_cycle_without_ai(env, local_search, fixtures_dir):
    with session_scope() as s:
        set_setting(s, "max_questions_per_cycle", 1)
        r, _ = import_local_file(s, fixtures_dir / "ar_tarbiyah.pdf")
        process(s, r)
        queue.enqueue(s, "research_cycle", {}, dedupe_key="research_cycle")
    drain(180, concurrency=2)
    with session_scope() as s:  # synthesis is scheduled 15 min after the searches; run it now
        synth = s.query(Job).filter(Job.job_type == "synthesize_question").one()
        assert synth.status == "queued" and synth.run_after > synth.created_at
        from tarbiyah.db import utcnow

        synth.run_after = utcnow()
    drain(60)
    with session_scope() as s:
        obj = s.query(ResearchObjective).order_by(ResearchObjective.priority.desc(), ResearchObjective.id).first()
        assert obj.planned_at is not None
        qs = s.query(ResearchQuestion).all()
        assert qs and all(q.created_by == "rules" for q in qs)
        assert all(q.text_alt for q in qs if q.kind == "planner")  # bilingual questions
        investigated = [q for q in qs if q.attempts == 1]
        assert len(investigated) == 1  # bounded by max_questions_per_cycle
        q = investigated[0]
        langs = {sq["lang"] for sq in q.search_queries}
        assert langs == {"ar", "en"}  # searched in both languages
        assert s.query(SearchLog).filter(SearchLog.question_id == q.id, SearchLog.status == "ok").count() >= 2
        found = s.query(Resource).filter(Resource.source_key == "local_search").all()
        assert len(found) == 2 and all(r.processing_status == "extracted" for r in found)
        assert all(r.discovered_by_question_id == q.id for r in found)
        assert q.status == "deferred" and "Claude" in q.answer_summary  # synthesis waits for AI, nothing invented
        assert s.query(Finding).count() == 0
    # an identical search is not repeated within search_repeat_days
    n_before = len(local_search.queries)
    with session_scope() as s:
        q = s.get(ResearchQuestion, q.id)
        q.status = "open"
        queue.enqueue(s, "investigate_question", {"question_id": q.id})
    drain(60)
    assert len(local_search.queries) == n_before


def test_question_dedupe_and_limits(env):
    with session_scope() as s:
        set_setting(s, "max_open_questions", 3)
        a = admit(s, [Candidate(text="What methods help teach honesty to children aged 7-12?")])
        assert len(a) == 1
        dup = admit(s, [Candidate(text="What methods help teach honesty to children aged 7–12 ?")])
        assert dup == []  # near-duplicate rejected
        topics = ["Quran memorisation methods in kuttab schools", "Screen time rules in Muslim households",
                  "Training of trainers for halaqa leaders", "Assessment rubrics for adab in primary school",
                  "Fathers' involvement in adolescent mentoring"]
        many = admit(s, [Candidate(text=f"What evidence exists on {t}?") for t in topics], limit=10)
        assert len(many) == 2  # capped by max_open_questions (3 open in total)
        parent = a[0]
        set_setting(s, "max_question_depth", 1)
        parent.depth = 1
        assert admit(s, [Candidate(text="A deeper follow-up question that is new")], parent=parent) == []


def _knowledge_response(text: str) -> S.KnowledgeExtraction:
    import re

    pid = int(re.search(r'<passage id="(\d+)"', text).group(1))
    return S.KnowledgeExtraction(
        summary="ملخص المصدر", title_translation="Raising children in light of the Islamic approach",
        pillars=["children", "parents"], topics=["Character & manners (akhlaq, adab)"],
        evidence_category="classical_scholarship", target_audience="parents", age_groups=["3-6"],
        claims=[
            S.ClaimOut(claim_type="recommendation", statement="Good example outweighs verbal instruction.",
                       quote="القدوة الحسنة أقوى أثرًا من كثرة التوجيه بالكلام", passage_id=pid,
                       evidence_type="scholarly_opinion", age_group="", pillars=["children"]),
            S.ClaimOut(claim_type="finding", statement="Invented claim.", quote="هذا نص غير موجود في المصدر إطلاقا",
                       passage_id=pid, evidence_type="empirical", age_group="", pillars=["children"]),
        ],
        concepts=[S.NamedThing(name="القدوة الحسنة", name_other_language="Good role model", kind="concept")],
        people=[S.NamedThing(name="الغزالي", name_other_language="Al-Ghazali", kind="scholar")],
        organizations=[], programs=[], cited_works=[S.CitedWork(title="إحياء علوم الدين", author="الغزالي")],
        relations=[S.RelationOut(subject="القدوة الحسنة", relation="method_for", object="تربية الأطفال")],
        limitations=["No empirical data"], quality_notes="Educational essay; not empirical research.")


def test_knowledge_extraction_with_scripted_ai(env, fixtures_dir, scripted_claude):
    from tarbiyah.agents.knowledge import analyze_resource

    scripted_claude({"extract": _knowledge_response})
    with session_scope() as s:
        r, _ = import_local_file(s, fixtures_dir / "ar_tarbiyah.pdf")
        process(s, r)
        analyze_resource(s, r)
        claims = s.query(Claim).filter(Claim.resource_id == r.id).all()
        good = [c for c in claims if c.quote_verified]
        bad = [c for c in claims if not c.quote_verified]
        assert len(good) == 1 and good[0].page == 1 and good[0].qa_status == "verified_quote"
        assert len(bad) == 1 and bad[0].quote is None and bad[0].qa_status == "unverified"  # fabricated quote dropped
        assert all(c.generated_by == "scripted-test-double" for c in claims)
        assert r.ai_status == "done" and r.summary == "ملخص المصدر"
        assert r.title_translations["en_status"] == "machine_translation"
        assert r.title == "تربية الأطفال في ضوء المنهج الإسلامي"  # original title untouched
        from tarbiyah.search.fts import search

        assert search(s, "Raising children Islamic approach")["results"][0]["resource"]["id"] == r.id


def test_synthesis_keeps_only_verified_evidence(env, fixtures_dir, scripted_claude):
    from tarbiyah.agents.synthesis import synthesize

    def synth(text):
        import re

        ids = [int(x) for x in re.findall(r'<passage id="(\d+)"', text)]
        return S.SynthesisOut(
            answer_summary="Sources emphasise role modelling.", status="partially_answered",
            findings=[
                S.FindingOut(statement="Role modelling is emphasised.", finding_type="supported", confidence="high",
                             evidence_basis="scholarly", evidence=[S.EvidenceOut(passage_id=ids[0], supports="supports",
                             quote="القدوة الحسنة أقوى أثرًا من كثرة التوجيه بالكلام")]),
                S.FindingOut(statement="Unsupported statement.", finding_type="supported", confidence="high",
                             evidence_basis="empirical", evidence=[S.EvidenceOut(passage_id=ids[0], supports="supports",
                             quote="a quote that is not in any passage")]),
            ],
            disagreements=[], gaps=["No empirical studies on age 3-6 found."],
            follow_up_questions=[S.QuestionOut(text="What empirical studies test role modelling in early childhood?",
                                               text_other_language="ما الدراسات التجريبية حول القدوة في الطفولة المبكرة؟",
                                               lang="en", kind="evidence", rationale="gap", pillars=["children"],
                                               importance=0.8, novelty=0.9, feasibility=0.6,
                                               search_queries=[S.SearchQuery(query="role modelling early childhood", lang="en")],
                                               next_steps="search", related_passage_ids=[ids[0]])])

    scripted_claude({"synthesis": synth})
    with session_scope() as s:
        r, _ = import_local_file(s, fixtures_dir / "ar_tarbiyah.pdf")
        process(s, r)
        q = admit(s, [Candidate(text="ما أثر القدوة الحسنة في تربية الطفل؟", lang="ar")])[0]
        q.attempts = 1
        synthesize(s, q)
        fs = {f.statement: f for f in s.query(Finding).filter(Finding.question_id == q.id)}
        assert fs["Role modelling is emphasised."].qa_status == "verified_quotes"
        assert fs["Role modelling is emphasised."].evidence[0]["page"] == 1
        bad = fs["Unsupported statement."]
        assert bad.finding_type == "insufficient" and bad.confidence == "low" and bad.qa_status == "unsupported_downgraded"
        assert fs["No empirical studies on age 3-6 found."].finding_type == "gap"
        child = s.query(ResearchQuestion).filter(ResearchQuestion.parent_id == q.id).one()
        assert child.depth == 1 and child.created_by == "ai" and child.text_alt
        assert q.status == "open" and q.priority < 0.6


def test_assistant_modes(env, fixtures_dir, scripted_claude):
    from tarbiyah.agents.assistant import answer

    with session_scope() as s:
        r, _ = import_local_file(s, fixtures_dir / "en_parenting.pdf")
        process(s, r)
        res = answer(s, "What parenting style supports emotional regulation?", "en")
        assert res["mode"] == "passages_only" and res["evidence"]  # no AI key: passages, no invented answer
        none = answer(s, "quantum chromodynamics lattice", "en")
        assert none["mode"] == "no_evidence"

    def ans(text):
        import re

        pid = int(re.search(r'<passage id="(\d+)"', text).group(1))
        return S.AssistantAnswer(answer=f"An authoritative style is associated with better regulation [P{pid}].",
                                 sufficiency="partial", evidence_vs_interpretation="Stated by the source.",
                                 citations=[S.Citation(passage_id=pid, quote="authoritative style"),
                                            S.Citation(passage_id=999999, quote="invented")])

    scripted_claude({"assistant": ans, "query_terms": lambda t: S.QueryTerms(terms_en=["parenting style"], terms_ar=["أساليب المعاملة الوالدية"])})
    with session_scope() as s:
        res = answer(s, "What parenting style supports emotional regulation?", "en")
        assert res["mode"] == "ai"
        assert res["citations"][0]["verified"] and not res["citations"][1]["verified"]
        assert not res["citations"][1]["known_passage"]


def test_daily_report_and_plan_persist(env, fixtures_dir):
    from tarbiyah.agents.reports import build_daily_report

    with session_scope() as s:
        for f in ("ar_tarbiyah.pdf", "en_parenting.pdf"):
            r, _ = import_local_file(s, fixtures_dir / f)
            process(s, r)
        admit(s, [Candidate(text="Which murabbi competency frameworks exist in Arabic?", pillars=["murabbi"])])
        rep = build_daily_report(s, date.today())
        st = rep.stats
        assert st["discoveries"]["total"] == 2 and st["discoveries"]["by_language"] == {"ar": 1, "en": 1}
        assert st["pillars"]["children"] >= 1 and st["pillars"]["murabbi"] >= 1
        assert st["research"]["questions_created"] == 1
        assert rep.plan["prioritized_questions"][0]["text"].startswith("Which murabbi")
    with session_scope() as s:
        assert s.get(DailyReport, date.today()).summary.startswith("2 new resources")


def test_outputs_without_ai(env, fixtures_dir):
    from tarbiyah.agents.outputs import generate

    with session_scope() as s:
        for f in ("ar_tarbiyah.pdf", "en_parenting.pdf"):
            r, _ = import_local_file(s, fixtures_dir / f)
            process(s, r)
        o = Output(kind="bibliography", title="Bib", params={"pillar": "children"})
        s.add(o)
        s.flush()
        generate(s, o)
        assert o.status == "done" and "تربية الأطفال في ضوء المنهج الإسلامي" in o.content
        assert (env / "outputs" / f"{o.id:05d}_bibliography.md").exists()
        lr = Output(kind="literature_review", title="LR", params={"query": "parenting"})
        s.add(lr)
        s.flush()
        generate(s, lr)
        assert lr.status == "failed" and "ANTHROPIC_API_KEY" in lr.error  # never faked
