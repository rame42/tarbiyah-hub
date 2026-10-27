"""Research & Synthesis Agent: answers a question from the collection, with verified evidence.

Findings keep only evidence whose quote is found verbatim in the cited passage. A
finding without verified evidence is downgraded to 'insufficient'. Disagreements are
preserved as 'contested' findings instead of being merged into a false consensus.
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.claude import claude
from ..ai.schemas import SynthesisOut
from ..db import utcnow
from ..models import Chunk, Finding, Job, ResearchQuestion, Resource
from ..search.fts import search_chunks
from .common import audit, passage_block, verify_quote
from .questions import admit, existing_texts, from_ai

SSYSTEM = (
    "You are the research-synthesis component of Tarbiyah Hub. Answer the research question ONLY from the passages "
    "provided. Compare sources: note agreements, contradictions and methodological differences. Separate (a) "
    "Qur'an/hadith and classical scholarship, (b) contemporary empirical research, (c) practical guidance and "
    "programs, (d) opinion/promotional content. Every finding must cite passages with exact verbatim quotes. If the "
    "passages do not answer the question, say so with finding_type 'insufficient' or 'gap' rather than guessing. "
    "Suggest at most 3 follow-up questions that would close the most important gaps."
)


def pending_work(session: Session, q: ResearchQuestion) -> int:
    searches = session.execute(select(func.count()).select_from(Job).where(
        Job.job_type == "search_source", Job.status.in_(("queued", "running")),
        Job.payload["question_id"].as_integer() == q.id)).scalar() or 0
    processing = session.execute(select(func.count()).select_from(Resource).where(
        Resource.discovered_by_question_id == q.id,
        Resource.processing_status == "pending", Resource.acquisition_status.in_(("pending", "metadata_only",
                                                                                  "downloaded")))).scalar() or 0
    return searches + processing


def gather_passages(session: Session, q: ResearchQuestion, limit: int = 24) -> list[Chunk]:
    seen: dict[int, Chunk] = {}
    for text in filter(None, [q.text, q.text_alt]):
        for h in search_chunks(session, text, limit=limit,
                               extra_terms=[sq["query"] for sq in (q.search_queries or []) if sq.get("query")][:4]):
            if h["chunk_id"] not in seen:
                c = session.get(Chunk, h["chunk_id"])
                if c is not None:
                    seen[c.id] = c
    return list(seen.values())[:limit]


def synthesize(session: Session, q: ResearchQuestion) -> dict:
    passages = gather_passages(session, q)
    q.related_resource_ids = sorted({c.resource_id for c in passages} | set(q.related_resource_ids or []))[:200]
    if not claude().available():
        q.status = "deferred"
        q.answer_summary = (f"{len(passages)} relevant passage(s) from {len({c.resource_id for c in passages})} source(s) "
                            "collected. Synthesis waits for Claude (ANTHROPIC_API_KEY not configured).")
        audit(session, "synthesis", "deferred_no_ai", f"Q{q.id}", question_id=q.id)
        return {"status": "deferred_no_ai", "passages": len(passages)}
    if not passages:
        q.status = "unresolved" if q.attempts >= 2 else "open"
        q.priority = round(q.priority * 0.7, 4)
        q.answer_summary = "No relevant passages in the collection yet."
        session.add(Finding(question_id=q.id, statement="The collection does not yet contain sources addressing this question.",
                            lang="en", finding_type="gap", evidence=[], confidence="low", qa_status="not_applicable",
                            generated_by="rules"))
        return {"status": q.status, "passages": 0}
    resources = {c.resource_id: session.get(Resource, c.resource_id) for c in passages}
    body = "\n".join(passage_block(c, resources[c.resource_id]) for c in passages)
    lang = q.lang or "en"
    prompt = (f"Research question ({lang}): {q.text}\n" + (f"Same question in the other language: {q.text_alt}\n" if q.text_alt else "")
              + f"Write findings in {'Arabic' if lang == 'ar' else 'English'}.\n\nAlready queued questions:\n- "
              + "\n- ".join(existing_texts(session, 25)) + f"\n\n<source>\n{body}\n</source>")
    session.commit()  # release the write lock while waiting for the model
    out: SynthesisOut = claude().structured("synthesis", SSYSTEM, prompt, SynthesisOut, max_tokens=24000)
    model = claude().last_usage.model or claude().model_for("synthesis")
    by_id = {c.id: c for c in passages}
    stored = 0
    for f in out.findings[:15]:
        evidence = []
        for ev in f.evidence[:8]:
            c = by_id.get(ev.passage_id)
            if c is None:
                continue
            ok = verify_quote(ev.quote, c.text)
            r = resources[c.resource_id]
            evidence.append({"chunk_id": c.id, "resource_id": c.resource_id, "title": r.title if r else None,
                             "page": c.page_start, "quote": ev.quote, "quote_verified": ok, "relation": ev.supports})
        verified = [e for e in evidence if e["quote_verified"]]
        ftype = f.finding_type
        qa = "verified_quotes" if verified else "unverified"
        if ftype in ("supported", "contested") and not verified:
            ftype, qa = "insufficient", "unsupported_downgraded"
        session.add(Finding(question_id=q.id, statement=f.statement, lang=lang, finding_type=ftype, evidence=evidence,
                            confidence=f.confidence if verified else "low", qa_status=qa, generated_by=model,
                            qa_notes=f"evidence basis: {f.evidence_basis}"))
        stored += 1
    for d in out.disagreements[:5]:
        session.add(Finding(question_id=q.id, statement=d, lang=lang, finding_type="contested", evidence=[],
                            confidence="low", qa_status="needs_review", generated_by=model))
    for g in out.gaps[:5]:
        session.add(Finding(question_id=q.id, statement=g, lang=lang, finding_type="gap", evidence=[],
                            confidence="low", qa_status="not_applicable", generated_by=model))
    q.answer_summary = out.answer_summary
    q.status = {"answered": "answered", "partially_answered": "open", "unresolved": "unresolved"}[out.status]
    if q.status == "open":
        q.priority = round(q.priority * 0.6, 4)  # partially answered: lower priority, may be revisited
        if q.attempts >= 3:
            q.status = "unresolved"
    resource_by_chunk = {c.id: c.resource_id for c in passages}
    follow = [from_ai(fq, sorted({resource_by_chunk[i] for i in fq.related_passage_ids if i in resource_by_chunk}))
              for fq in out.follow_up_questions[:3]]
    added = admit(session, follow, parent=q)
    u = claude().last_usage
    audit(session, "synthesis", "synthesize", f"Q{q.id}: {stored} finding(s), status {q.status}, "
          f"{len(added)} follow-up(s)", question_id=q.id, ai_input_tokens=u.input_tokens, ai_output_tokens=u.output_tokens)
    return {"status": q.status, "findings": stored, "follow_ups": [x.id for x in added]}


def wait_time() -> timedelta:
    return timedelta(minutes=10)


def recent(session: Session, hours: int = 24) -> list[Finding]:
    return session.execute(select(Finding).where(Finding.created_at >= utcnow() - timedelta(hours=hours))).scalars().all()
