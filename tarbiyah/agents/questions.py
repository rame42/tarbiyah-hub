"""Question Generation Agent.

Produces candidate research questions from (a) coverage analysis of the collection
(no AI needed) and (b) Claude reading new material and findings. Candidates are
deduplicated (fuzzy, bilingual), ranked, and admitted under hard limits so the queue
cannot grow without bound.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.claude import claude
from ..ai.schemas import QuestionBatch, QuestionOut
from ..models import (
    Citation,
    Entity,
    GlossaryTerm,
    ResearchObjective,
    ResearchQuestion,
    Resource,
    ResourceEntity,
    ResourcePillar,
    ResourceTopic,
    Topic,
)
from ..settings import get_setting
from ..taxonomy import AGE_GROUPS, PILLAR_LABELS
from ..text.arabic import light_stem, normalize_for_search, tokens
from .common import audit, passage_block

LIVE_STATUSES = ("open", "investigating", "answered", "unresolved", "deferred", "not_relevant", "duplicate")


@dataclass
class Candidate:
    text: str
    lang: str = "en"
    text_alt: str | None = None
    kind: str = "gap"
    rationale: str = ""
    pillars: list[str] = field(default_factory=list)
    importance: float = 0.5
    novelty: float = 0.5
    feasibility: float = 0.6
    search_queries: list[dict[str, str]] = field(default_factory=list)
    next_steps: str = ""
    related_resource_ids: list[int] = field(default_factory=list)
    created_by: str = "rules"


def dedupe_key(text: str) -> str:
    toks = sorted({light_stem(t) for t in tokens(text) if len(t) > 2})
    return " ".join(toks)[:300]


def is_duplicate(session: Session, c: Candidate) -> ResearchQuestion | None:
    key = dedupe_key(c.text)
    exact = session.execute(select(ResearchQuestion).where(ResearchQuestion.dedupe_key == key)).scalars().first()
    if exact:
        return exact
    texts = [normalize_for_search(c.text)] + ([normalize_for_search(c.text_alt)] if c.text_alt else [])
    rows = session.execute(select(ResearchQuestion.id, ResearchQuestion.text, ResearchQuestion.text_alt)
                           .order_by(ResearchQuestion.id.desc()).limit(3000)).all()
    for qid, t, alt in rows:
        for mine in texts:
            for theirs in (t, alt):
                if theirs and fuzz.token_set_ratio(mine, normalize_for_search(theirs)) >= 90:
                    return session.get(ResearchQuestion, qid)
    return None


def priority(c: Candidate, objective_priority: float = 0.5) -> float:
    return round(0.35 * c.importance + 0.25 * c.novelty + 0.2 * c.feasibility + 0.2 * objective_priority, 4)


def admit(session: Session, candidates: list[Candidate], *, parent: ResearchQuestion | None = None,
          objective_id: int | None = None, limit: int | None = None) -> list[ResearchQuestion]:
    """Deduplicate, rank and insert candidates within the configured limits."""
    max_open = int(get_setting("max_open_questions", session))
    max_new = limit if limit is not None else int(get_setting("max_new_questions_per_run", session))
    max_depth = int(get_setting("max_question_depth", session))
    depth = (parent.depth + 1) if parent else 0
    if depth > max_depth:
        return []
    open_count = session.execute(select(func.count()).select_from(ResearchQuestion)
                                 .where(ResearchQuestion.status.in_(("open", "investigating")))).scalar() or 0
    room = max(0, min(max_new, max_open - open_count))
    obj_pri = 0.5
    if objective_id or (parent and parent.objective_id):
        obj = session.get(ResearchObjective, objective_id or parent.objective_id)
        obj_pri = obj.priority if obj else 0.5
    ranked = sorted(candidates, key=lambda c: priority(c, obj_pri), reverse=True)
    added: list[ResearchQuestion] = []
    for c in ranked:
        if len(added) >= room:
            break
        if not c.text or len(c.text) < 8:
            continue
        dup = is_duplicate(session, c)
        if dup is not None:
            if c.related_resource_ids:
                dup.related_resource_ids = sorted(set((dup.related_resource_ids or []) + c.related_resource_ids))[:200]
            continue
        q = ResearchQuestion(
            objective_id=objective_id or (parent.objective_id if parent else None),
            parent_id=parent.id if parent else None, text=c.text.strip(), lang=c.lang,
            text_alt=c.text_alt, rationale=c.rationale, kind=c.kind, pillars=c.pillars,
            priority=priority(c, obj_pri),
            scores={"importance": c.importance, "novelty": c.novelty, "feasibility": c.feasibility,
                    "objective_priority": obj_pri},
            status="open", depth=depth, search_queries=c.search_queries[:6],
            related_resource_ids=c.related_resource_ids[:100], next_steps=c.next_steps,
            dedupe_key=dedupe_key(c.text), created_by=c.created_by,
        )
        session.add(q)
        session.flush()
        added.append(q)
    if added:
        audit(session, "questions", "admit", f"{len(added)} new question(s) from {len(candidates)} candidate(s)")
    return added


# ------------------------------------------------------------------ rule-based (no AI)

def _topic_queries(t: Topic) -> list[dict[str, str]]:
    q = []
    if t.keywords_en:
        q.append({"query": " ".join(t.keywords_en[:1]) + " islamic", "lang": "en"})
    if t.keywords_ar:
        q.append({"query": t.keywords_ar[0], "lang": "ar"})
    return q


def coverage_candidates(session: Session, max_items: int = 6) -> list[Candidate]:
    """Questions for under-covered topics and age groups."""
    out: list[Candidate] = []
    counts = dict(session.execute(select(ResourceTopic.topic_id, func.count()).group_by(ResourceTopic.topic_id)).all())
    topics = session.execute(select(Topic)).scalars().all()
    for t in sorted(topics, key=lambda t: counts.get(t.id, 0))[:max_items]:
        n = counts.get(t.id, 0)
        out.append(Candidate(
            text=f"What sources, methods and evidence exist on {t.name_en.lower()} in Tarbiyah?",
            text_alt=f"ما المصادر والأساليب والأدلة المتوفرة حول {t.name_ar} في التربية؟",
            kind="coverage", pillars=[t.pillar] if t.pillar else [],
            rationale=f"Only {n} collected resource(s) are classified under '{t.name_en}'.",
            importance=0.6, novelty=1.0 if n == 0 else max(0.2, 1 - n / 30), feasibility=0.8,
            search_queries=_topic_queries(t), next_steps="Search academic indexes and book catalogues in both languages."))
    # age-group coverage (children pillar)
    total_children = session.execute(select(func.count()).select_from(ResourcePillar)
                                     .where(ResourcePillar.pillar == "children")).scalar() or 0
    if total_children:
        band_counts: dict[str, int] = {b: 0 for b in AGE_GROUPS}
        for (extra,) in session.execute(select(Resource.extra).join(ResourcePillar).where(ResourcePillar.pillar == "children")):
            for b in (extra or {}).get("age_groups", []):
                if b in band_counts:
                    band_counts[b] += 1
        band, n = min(band_counts.items(), key=lambda kv: kv[1])
        en = AGE_GROUPS[band]["en"][0]
        ar = AGE_GROUPS[band]["ar"][0]
        out.append(Candidate(
            text=f"What is known about Islamic upbringing and character development for children aged {band} ({en})?",
            text_alt=f"ما الذي يُعرف عن التربية الإسلامية وبناء الخلق للأطفال في سن {band} ({ar})؟",
            kind="coverage", pillars=["children"], importance=0.7,
            novelty=max(0.3, 1 - n / max(1, total_children)), feasibility=0.7,
            rationale=f"Age group {band} has the fewest resources ({n} of {total_children}) in the children pillar.",
            search_queries=[{"query": f"{en} islamic education", "lang": "en"}, {"query": f"تربية {ar}", "lang": "ar"}],
            next_steps="Collect developmental and practical sources for this age group."))
    return out


def citation_candidates(session: Session, max_items: int = 5) -> list[Candidate]:
    out = []
    rows = session.execute(select(Citation).where(Citation.status == "uncollected", Citation.title.is_not(None))
                           .order_by(Citation.id.desc()).limit(max_items)).scalars().all()
    for c in rows:
        out.append(Candidate(
            text=f"Locate and collect the cited work: \"{c.title[:200]}\"",
            kind="citation_followup", rationale="Cited by a collected resource but not yet in the library.",
            importance=0.5, novelty=0.8, feasibility=0.6,
            search_queries=[{"query": c.title[:200], "lang": "ar" if any('؀' <= ch <= 'ۿ' for ch in c.title) else "en"}],
            related_resource_ids=[c.resource_id], next_steps="Search catalogues by title; acquire if legally available."))
        c.status = "queued"
    return out


def entity_candidates(session: Session, max_items: int = 4) -> list[Candidate]:
    """Scholars/institutions mentioned by several resources but not investigated yet."""
    out = []
    rows = session.execute(
        select(Entity, func.count(ResourceEntity.resource_id))
        .join(ResourceEntity, ResourceEntity.entity_id == Entity.id)
        .where(Entity.entity_type.in_(("person", "organization", "program")), ResourceEntity.role == "mentions")
        .group_by(Entity.id).having(func.count(ResourceEntity.resource_id) >= 2)
        .order_by(func.count(ResourceEntity.resource_id).desc()).limit(50)).all()
    for e, n in rows:
        if (e.extra or {}).get("investigated"):
            continue
        kind = "scholar or researcher" if e.entity_type == "person" else "institution or program"
        out.append(Candidate(
            text=f"What has {e.name} contributed to Tarbiyah (works, programs, methods)?",
            text_alt=(f"ما إسهامات {e.name_ar or e.name} في التربية (مؤلفات، برامج، مناهج)؟"),
            kind="entity_followup", rationale=f"This {kind} is mentioned in {n} collected resources but has not been investigated.",
            importance=0.55, novelty=0.7, feasibility=0.7,
            search_queries=[{"query": e.name, "lang": "ar" if any('؀' <= ch <= 'ۿ' for ch in e.name) else "en"}]
            + ([{"query": e.name_en, "lang": "en"}] if e.name_en and e.name_en != e.name else []),
            next_steps="Search for works by or about this entity."))
        e.extra = {**(e.extra or {}), "investigated": True}
        if len(out) >= max_items:
            break
    return out


def terminology_candidates(session: Session, max_items: int = 3) -> list[Candidate]:
    """Glossary concepts with Arabic coverage but little English (or vice versa)."""
    out = []
    lang_counts = dict(session.execute(select(Resource.language, func.count()).group_by(Resource.language)).all())
    ar, en = lang_counts.get("ar", 0), lang_counts.get("en", 0)
    weaker = "ar" if ar < en else "en"
    for g in session.execute(select(GlossaryTerm).order_by(func.random()).limit(max_items)).scalars():
        terms = g.terms_ar if weaker == "ar" else g.terms_en
        if not terms:
            continue
        label = g.terms_en[0] if g.terms_en else g.concept_key
        out.append(Candidate(
            text=f"Find {'Arabic' if weaker == 'ar' else 'English'}-language sources on '{label}' ({terms[0]}).",
            kind="terminology", pillars=[g.pillar] if g.pillar else [],
            rationale=f"The collection has {ar} Arabic vs {en} English resources; balancing coverage for this concept.",
            importance=0.45, novelty=0.6, feasibility=0.8,
            search_queries=[{"query": t, "lang": weaker} for t in terms[:2]],
            next_steps="Search with the listed terminology and spelling variants."))
    return out


def rule_candidates(session: Session) -> list[Candidate]:
    return (coverage_candidates(session) + citation_candidates(session) + entity_candidates(session)
            + terminology_candidates(session))


# ------------------------------------------------------------------ AI-generated

QSYSTEM = (
    "You are the question-generation component of Tarbiyah Hub, an autonomous research system on Islamic "
    "education (tarbiyah): children's tarbiyah, parents & family, murabbi (educator) development. Propose a few "
    "high-value research questions that would add NEW knowledge: unanswered questions, claims needing stronger "
    "evidence, competing definitions, uninvestigated scholars/institutions, missing Arabic terminology, age groups "
    "with weak coverage, methods lacking implementation guidance, findings relevant to another pillar, cited works "
    "not collected. Prefer specific, searchable questions over vague ones. Give each question in Arabic and English, "
    "and 2-4 concrete search queries mixing both languages. Never propose collecting private or sensitive personal "
    "data, or accessing paid/restricted content."
)


def from_ai(out: QuestionOut, related: list[int]) -> Candidate:
    return Candidate(text=out.text, lang=out.lang, text_alt=out.text_other_language, kind=out.kind,
                     rationale=out.rationale, pillars=list(out.pillars), importance=out.importance,
                     novelty=out.novelty, feasibility=out.feasibility,
                     search_queries=[q.model_dump() for q in out.search_queries], next_steps=out.next_steps,
                     related_resource_ids=related, created_by="ai")


def ai_candidates(session: Session, context: str, passages: list[Any], resources_by_chunk: dict[int, int],
                  existing_sample: list[str]) -> list[Candidate]:
    if not claude().available():
        return []
    body = "\n".join(passage_block(c) for c in passages)
    prompt = (f"Context:\n{context}\n\nAlready queued questions (avoid duplicates):\n- " +
              "\n- ".join(existing_sample[:40]) + f"\n\n<source>\n{body}\n</source>\n\nPropose at most 6 questions.")
    session.commit()
    batch: QuestionBatch = claude().structured("questions", QSYSTEM, prompt, QuestionBatch, max_tokens=12000)
    out = []
    for q in batch.questions[:6]:
        rel = sorted({resources_by_chunk[i] for i in q.related_passage_ids if i in resources_by_chunk})
        out.append(from_ai(q, rel))
    return out


def existing_texts(session: Session, n: int = 60) -> list[str]:
    return [t for (t,) in session.execute(select(ResearchQuestion.text).where(ResearchQuestion.status.in_(
        ("open", "investigating"))).order_by(ResearchQuestion.priority.desc()).limit(n))]


def pillar_label(p: str) -> str:
    return PILLAR_LABELS.get(p, {}).get("en", p)
