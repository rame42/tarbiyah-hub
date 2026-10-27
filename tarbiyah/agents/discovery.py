"""Discovery Agent: turns a research question into bilingual searches across enabled sources.

Avoids repeating identical searches (same adapter + normalized query) within
`search_repeat_days`; every search is logged in search_log with its outcome.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..jobs import queue
from ..models import GlossaryTerm, ResearchQuestion, SearchLog, Source
from ..settings import get_setting
from ..sources.registry import ADAPTERS
from ..text.arabic import has_arabic, normalize_for_search, tokens
from .common import audit

_STOP = set("what how which who where when why is are the of and in on for to do does a an about exist exists "
            "known there their its from with by tarbiyah sources methods evidence recommend find locate collect "
            "ما ماذا كيف هل من في على عن التي الذي المتوفره المصادر والاساليب والادله حول".split())


def query_key(adapter: str, q: str) -> str:
    return f"{adapter}:{normalize_for_search(q)}"[:300]


def derive_queries(session: Session, q: ResearchQuestion, max_queries: int = 4) -> list[dict[str, str]]:
    """Use planner/AI queries when present, otherwise keywords from the question in both languages."""
    out: list[dict[str, str]] = [sq for sq in (q.search_queries or []) if sq.get("query")]
    if len(out) < 2:
        for text in filter(None, [q.text, q.text_alt]):
            kws = [t for t in tokens(text) if t not in _STOP and len(t) > 2][:6]
            if kws:
                out.append({"query": " ".join(kws), "lang": "ar" if has_arabic(text) else "en"})
    langs = {sq.get("lang") for sq in out}
    if "ar" not in langs or "en" not in langs:  # add the other language through the glossary
        padded = " " + " ".join(tokens(" ".join(sq["query"] for sq in out))) + " "
        en_terms, ar_terms = [], []
        for g in session.execute(select(GlossaryTerm)).scalars():
            if any(f" {normalize_for_search(t)} " in padded for t in (g.terms_en or []) + (g.terms_ar or [])):
                en_terms += g.terms_en[:1]
                ar_terms += g.terms_ar[:1]
        if "ar" not in langs and ar_terms:
            out.append({"query": " ".join(dict.fromkeys(ar_terms))[:120], "lang": "ar"})
        if "en" not in langs and en_terms:
            out.append({"query": " ".join(dict.fromkeys(en_terms))[:120], "lang": "en"})
    seen, uniq = set(), []
    for sq in out:
        k = normalize_for_search(sq["query"])
        if k and k not in seen:
            seen.add(k)
            uniq.append(sq)
    return uniq[:max_queries]


def recently_searched(session: Session, adapter: str, query: str) -> bool:
    days = int(get_setting("search_repeat_days", session))
    return session.execute(select(SearchLog.id).where(
        SearchLog.query_key == query_key(adapter, query), SearchLog.status == "ok",
        SearchLog.executed_at >= utcnow() - timedelta(days=days))).first() is not None


def enabled_search_sources(session: Session) -> list[Source]:
    rows = session.execute(select(Source).where(Source.enabled.is_(True))).scalars().all()
    out = []
    for s in rows:
        a = ADAPTERS.get(s.adapter)
        if a and a.supports("search") and (s.config or {}).get("role") == "search" and a.is_configured():
            out.append(s)
    return out


def investigate(session: Session, q: ResearchQuestion, parent_job_id: int | None = None) -> dict:
    queries = derive_queries(session, q)
    q.search_queries = queries
    sources = enabled_search_sources(session)
    limit = int(get_setting("max_results_per_search", session))
    paused = set(get_setting("paused_collectors", session) or [])
    enqueued, skipped = 0, 0
    for src in sources:
        if src.key in paused:
            continue
        a = ADAPTERS[src.adapter]
        for sq in queries:
            if sq.get("lang") == "ar" and "ar" not in a.info.languages:
                continue
            if recently_searched(session, src.adapter, sq["query"]):
                skipped += 1
                continue
            queue.enqueue(session, "search_source",
                          {"source_id": src.id, "query": sq["query"], "lang": sq.get("lang"), "question_id": q.id,
                           "limit": limit},
                          priority=45, group=src.key, parent_id=parent_job_id,
                          dedupe_key=f"search:{query_key(src.adapter, sq['query'])}")
            enqueued += 1
    q.status = "investigating"
    q.attempts = (q.attempts or 0) + 1
    q.investigated_at = utcnow()
    # synthesis runs after the searches and the processing of what they find
    queue.enqueue(session, "synthesize_question", {"question_id": q.id}, priority=55, group="research",
                  run_after=utcnow() + timedelta(minutes=15 if enqueued else 0), dedupe_key=f"synth:{q.id}",
                  parent_id=parent_job_id)
    audit(session, "discovery", "investigate", f"Q{q.id}: {enqueued} search(es) queued, {skipped} skipped as recent",
          question_id=q.id)
    return {"question_id": q.id, "searches": enqueued, "skipped_recent": skipped, "queries": queries}
