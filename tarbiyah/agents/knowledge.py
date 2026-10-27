"""Knowledge Extraction Agent: claims, concepts, people, institutions, citations, relations.

Every claim keeps its resource, passage (chunk) and page. Quotes are verified verbatim
against the stored passage; unverifiable quotes are kept only as unverified paraphrases
and flagged for QA. AI statements are marked generated_by=<model>.
"""
from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..ai.claude import claude
from ..ai.schemas import KnowledgeExtraction
from ..db import utcnow
from ..ingest.registry import link_entity, upsert_entity
from ..models import Chunk, Citation, Claim, Relation, Resource, ResourcePillar, ResourceTopic, Topic
from ..search import fts
from ..settings import get_setting
from ..text.arabic import normalize_for_search
from .common import audit, passage_block, sample_chunks, verify_quote

SYSTEM = (
    "You are the knowledge-extraction component of Tarbiyah Hub, a research library on Islamic education "
    "(tarbiyah) organised in three pillars: children's tarbiyah, parents & family, and murabbi (educator/mentor) "
    "development. Extract structured knowledge from ONE source. Report what the source itself says; your own "
    "interpretation belongs only in quality_notes. Keep Qur'anic verses, hadith and scholarly quotations exact and "
    "in their original language. If the source is not related to tarbiyah, return empty lists and pillars=[]."
)


def summary_language(r: Resource) -> str:
    pref = get_setting("ai_summary_language") or "source"
    if pref in ("ar", "en"):
        return pref
    return "ar" if r.language == "ar" else "en"


def analyze_resource(session: Session, r: Resource) -> dict:
    chunks = session.execute(select(Chunk).where(Chunk.resource_id == r.id).order_by(Chunk.seq)).scalars().all()
    if not chunks:
        r.ai_status = "not_applicable"
        return {"status": "no_text"}
    picked = sample_chunks(list(chunks))
    lang = summary_language(r)
    header = (f"Source metadata (from the collector, may be incomplete):\nTitle: {r.title}\nAuthors: {r.authors_text or '-'}\n"
              f"Type: {r.resource_type}\nYear: {r.year or '-'}\nPublisher/venue: {r.publisher or '-'}\n"
              f"Language: {r.language}\nURL: {r.url or '-'}\n\nWrite the summary in "
              f"{'Arabic' if lang == 'ar' else 'English'}. Use only passage ids shown below.\n\n<source>\n")
    body = "\n".join(passage_block(c) for c in picked)
    session.commit()  # release the write lock while waiting for the model
    out: KnowledgeExtraction = claude().structured("extract", SYSTEM, header + body + "\n</source>",
                                                   KnowledgeExtraction, max_tokens=24000)
    model = claude().last_usage.model or claude().model_for("extract")
    by_id = {c.id: c for c in picked}
    # replace previous AI extraction for this resource (re-analysis is idempotent)
    session.execute(delete(Claim).where(Claim.resource_id == r.id))
    verified = 0
    for cl in out.claims[:60]:
        c = by_id.get(cl.passage_id)
        ok = bool(c and verify_quote(cl.quote, c.text))
        verified += ok
        session.add(Claim(resource_id=r.id, chunk_id=c.id if c else None, claim_type=cl.claim_type,
                          statement=cl.statement, statement_lang=lang, quote=cl.quote if ok else None,
                          quote_lang=c.lang if c else None, page=c.page_start if c else None,
                          evidence_type=cl.evidence_type, age_group=cl.age_group or None, pillars=list(cl.pillars),
                          quote_verified=ok, qa_status="verified_quote" if ok else "unverified",
                          generated_by=model))
    # entities
    for group, etype, role in ((out.people, "person", "mentions"), (out.organizations, "organization", "mentions"),
                               (out.programs, "program", "mentions"), (out.concepts, "concept", "subject")):
        for n in group[:40]:
            if not n.name or len(n.name) > 250:
                continue
            e = upsert_entity(session, etype, n.name, description=n.description or None, origin="ai")
            if n.name_other_language:
                if any("؀" <= ch <= "ۿ" for ch in n.name_other_language):
                    e.name_ar = e.name_ar or n.name_other_language
                else:
                    e.name_en = e.name_en or n.name_other_language
            extra = dict(e.extra or {})
            if n.kind:
                extra["kind"] = n.kind
            e.extra = extra
            link_entity(session, r.id, e, role)
    # concept relations (graph edges between entities)
    session.flush()
    for rel in out.relations[:40]:
        a = upsert_entity(session, "concept", rel.subject, origin="ai")
        b = upsert_entity(session, "concept", rel.object, origin="ai")
        session.add(Relation(from_kind="entity", from_id=a.id, rel_type=rel.relation, to_kind="entity", to_id=b.id,
                             evidence_chunk_id=rel.passage_id if rel.passage_id in by_id else None, method="ai"))
    # cited works -> citation records (collected later by the discovery agent)
    have = {normalize_for_search(c.title or "") for c in
            session.execute(select(Citation).where(Citation.resource_id == r.id)).scalars()}
    for cw in out.cited_works[:80]:
        if cw.title and normalize_for_search(cw.title) not in have:
            session.add(Citation(resource_id=r.id, raw=f"{cw.author} ({cw.year}). {cw.title}".strip(),
                                 title=cw.title, year=int(cw.year[:4]) if cw.year[:4].isdigit() else None))
    # pillars/topics refined by AI are stored alongside the rule-based ones
    session.execute(delete(ResourcePillar).where(ResourcePillar.resource_id == r.id, ResourcePillar.method == "ai"))
    session.flush()
    rule_pillars = {p.pillar for p in session.execute(
        select(ResourcePillar).where(ResourcePillar.resource_id == r.id)).scalars()}
    for p in out.pillars:
        if p in rule_pillars:
            continue
        session.add(ResourcePillar(resource_id=r.id, pillar=p, score=0.8, method="ai"))
    topics = {t.name_en.lower(): t for t in session.execute(select(Topic)).scalars()}
    for label in out.topics:
        t = topics.get(label.lower())
        if t and session.get(ResourceTopic, (r.id, t.id)) is None:
            session.add(ResourceTopic(resource_id=r.id, topic_id=t.id, score=0.8, method="ai"))
    r.summary = out.summary
    r.summary_lang = lang
    r.evidence_category = out.evidence_category
    other = "en" if r.language == "ar" else "ar"
    if out.title_translation and other not in (r.title_translations or {}):
        r.title_translations = {**(r.title_translations or {}),
                                other: out.title_translation, f"{other}_status": "machine_translation"}
    quality = dict(r.quality or {})
    quality["ai_notes"] = out.quality_notes
    quality["limitations"] = out.limitations
    quality["claims_verified"] = f"{verified}/{min(len(out.claims), 60)}"
    r.quality = quality
    extra = dict(r.extra or {})
    extra["age_groups"] = sorted(set((extra.get("age_groups") or []) + list(out.age_groups)))
    extra["target_audience"] = out.target_audience
    r.extra = extra
    r.ai_status = "done"
    r.updated_at = utcnow()
    fts.index_resource(session, r)  # title translation becomes searchable
    u = claude().last_usage
    audit(session, "knowledge", "analyze_resource", f"{r.title[:100]}: {len(out.claims)} claims ({verified} verified)",
          resource_id=r.id, ai_input_tokens=u.input_tokens, ai_output_tokens=u.output_tokens)
    return {"claims": len(out.claims), "verified_quotes": verified, "pillars": list(out.pillars)}
