"""AI Research Assistant: answers from the indexed collection, with inspectable evidence."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from ..ai.claude import AIBudgetExceeded, AIRefused, AIUnavailable, claude
from ..ai.schemas import AssistantAnswer, QueryTerms
from ..models import Chunk, Resource
from ..search.fts import build_query, search_chunks
from .common import audit, passage_block, verify_quote

ASYSTEM = (
    "You are the research assistant of Tarbiyah Hub, a library on Islamic education (children's tarbiyah, parents & "
    "family, murabbi development). Answer ONLY from the passages provided and cite them as [P<id>] after each "
    "sentence they support. Distinguish scriptural texts and classical scholarship, empirical research, practical "
    "guidance and opinion. If the passages are insufficient, say clearly what is missing instead of filling gaps "
    "from general knowledge. Do not issue religious rulings."
)


def expand_terms(question: str) -> list[str]:
    if not claude().available():
        return []
    try:
        t: QueryTerms = claude().structured(
            "query_terms", "Give search terms for a bilingual (Arabic/English) library on Islamic education.",
            f"Question: {question}\nReturn up to 5 short English and 5 short Arabic search terms/synonyms, "
            "including Arabic spelling variants.", QueryTerms, max_tokens=2000, effort="low")
        return (t.terms_en + t.terms_ar)[:10]
    except (AIUnavailable, AIBudgetExceeded, AIRefused):
        return []


def answer(session: Session, question: str, lang: str = "en", pillar: str | None = None,
           use_ai_terms: bool = True) -> dict[str, Any]:
    terms = expand_terms(question) if use_ai_terms else []
    hits = search_chunks(session, question, limit=14, extra_terms=terms)
    passages = []
    for h in hits:
        c = session.get(Chunk, h["chunk_id"])
        r = session.get(Resource, h["resource_id"])
        if pillar and r and pillar not in {p.pillar for p in r.pillars}:
            continue
        passages.append((c, r))
    evidence = [{"passage_id": c.id, "resource_id": r.id, "title": r.title, "authors": r.authors_text, "year": r.year,
                 "page": c.page_start, "timestamp": c.timestamp_start, "url": r.url, "lang": c.lang,
                 "text": c.text[:1500], "access_status": r.access_status} for c, r in passages]
    pq = build_query(session, question, True, terms)
    base = {"question": question, "evidence": evidence, "expanded_terms": terms, "expansions": pq.expansions}
    if not passages:
        return {**base, "mode": "no_evidence", "answer": (
            "لا تحتوي المجموعة حتى الآن على مصادر تجيب عن هذا السؤال." if lang == "ar"
            else "The collection does not yet contain sources that address this question."), "citations": [],
            "sufficiency": "insufficient"}
    if not claude().available():
        return {**base, "mode": "passages_only", "sufficiency": "unknown", "citations": [],
                "answer": ("الذكاء الاصطناعي غير مفعّل: هذه أكثر المقاطع صلة من المصادر." if lang == "ar" else
                           "AI is not configured (ANTHROPIC_API_KEY). Showing the most relevant source passages.")}
    body = "\n".join(passage_block(c, r) for c, r in passages)
    out: AssistantAnswer = claude().structured(
        "assistant", ASYSTEM, f"Answer in {'Arabic' if lang == 'ar' else 'English'}.\nQuestion: {question}\n\n<source>\n{body}\n</source>",
        AssistantAnswer, max_tokens=12000)
    by_id = {c.id: c for c, _ in passages}
    cites = []
    for ct in out.citations:
        c = by_id.get(ct.passage_id)
        cites.append({"passage_id": ct.passage_id, "quote": ct.quote,
                      "verified": bool(c and verify_quote(ct.quote, c.text)), "known_passage": c is not None})
    audit(session, "assistant", "answer", question[:200], ai_input_tokens=claude().last_usage.input_tokens,
          ai_output_tokens=claude().last_usage.output_tokens)
    return {**base, "mode": "ai", "answer": out.answer, "sufficiency": out.sufficiency, "citations": cites,
            "evidence_vs_interpretation": out.evidence_vs_interpretation,
            "note": "AI-generated answer. Check the cited passages; unverified citations are marked."}
