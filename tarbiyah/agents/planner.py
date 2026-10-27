"""Research Planner: turns an objective into prioritized, searchable questions.

With Claude: decomposes the objective, proposes bilingual questions and glossary terms.
Without Claude: builds questions from the taxonomy topics of the objective's pillars.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..ai.claude import AIBudgetExceeded, AIUnavailable, claude
from ..ai.schemas import PlanOut
from ..db import utcnow
from ..models import GlossaryTerm, ResearchObjective, Topic
from .common import audit
from .questions import Candidate, admit, existing_texts, from_ai

PSYSTEM = (
    "You are the research planner of Tarbiyah Hub (Islamic education: children's tarbiyah, parents & family, murabbi "
    "development). Break the objective into 6-10 specific research questions covering: classical/scriptural "
    "foundations, contemporary empirical research, practical methods and programs, and gaps. For each, give Arabic "
    "and English versions, concrete bilingual search queries, and realistic importance/novelty/feasibility scores. "
    "Also list key concepts with Arabic and English terminology and spelling variants for search."
)


def template_plan(session: Session, obj: ResearchObjective) -> list[Candidate]:
    pillars = obj.pillars or ["children", "parents", "murabbi"]
    out = []
    topics = session.execute(select(Topic).where(Topic.pillar.in_(pillars))).scalars().all()
    for t in topics:
        out.append(Candidate(
            text=f"{t.name_en}: what do classical sources, contemporary research and practitioners recommend?",
            text_alt=f"{t.name_ar}: ماذا توصي المصادر التراثية والبحوث المعاصرة والممارسون؟",
            kind="planner", pillars=[t.pillar] if t.pillar else list(pillars), importance=0.7, novelty=0.7,
            feasibility=0.75, rationale=f"Planned from objective '{obj.title}' and taxonomy topic '{t.name_en}'.",
            search_queries=[{"query": t.keywords_en[0], "lang": "en"} if t.keywords_en else {},
                            {"query": t.keywords_ar[0], "lang": "ar"} if t.keywords_ar else {}],
            next_steps="Search academic indexes, open book collections and registered sites in both languages."))
    for c in out:
        c.search_queries = [q for q in c.search_queries if q]
    return out


def plan_objective(session: Session, obj: ResearchObjective) -> dict:
    method = "template"
    candidates: list[Candidate] = []
    if claude().available():
        try:
            prompt = (f"Objective: {obj.title}\nDescription: {obj.description or '-'}\nPillars: {', '.join(obj.pillars or [])}"
                      "\n\nExisting questions (avoid duplicates):\n- " + "\n- ".join(existing_texts(session, 40)))
            session.commit()
            plan: PlanOut = claude().structured("plan", PSYSTEM, prompt, PlanOut, max_tokens=16000)
            candidates = [from_ai(q, []) for q in plan.questions]
            method = "ai"
            have = {g.concept_key for g in session.execute(select(GlossaryTerm)).scalars()}
            for g in plan.glossary[:20]:
                key = g.concept.lower().strip()[:120]
                if key and key not in have and (g.terms_en or g.terms_ar):
                    session.add(GlossaryTerm(concept_key=key, terms_en=g.terms_en[:8], terms_ar=g.terms_ar[:8], origin="ai"))
                    have.add(key)
        except (AIUnavailable, AIBudgetExceeded):
            candidates = []
    if not candidates:
        candidates = template_plan(session, obj)
        method = "template"
    added = admit(session, candidates, objective_id=obj.id, limit=10)
    obj.planned_at = utcnow()
    audit(session, "planner", "plan_objective", f"{obj.title[:80]}: {len(added)} question(s) via {method}")
    return {"objective_id": obj.id, "questions": [q.id for q in added], "method": method}
