"""Workflow Coordinator: one bounded research cycle.

1. plan one unplanned objective   2. top up the question queue (rules / AI)
3. pick the highest-value open questions within limits   4. hand them to Discovery
Synthesis, follow-up questions and QA happen in their own jobs. The cycle never
loops on itself: the scheduler starts the next cycle after research_cycle_minutes.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.claude import AIBudgetExceeded, AIUnavailable, AIRefused, claude
from ..models import Chunk, ResearchObjective, ResearchQuestion, Resource
from ..settings import get_setting
from .common import audit
from .discovery import investigate
from .planner import plan_objective
from .questions import admit, ai_candidates, existing_texts, rule_candidates


def top_up_questions(session: Session) -> dict:
    open_n = session.execute(select(func.count()).select_from(ResearchQuestion)
                             .where(ResearchQuestion.status == "open")).scalar() or 0
    result = {"rules": 0, "ai": 0}
    if open_n < 10:
        result["rules"] = len(admit(session, rule_candidates(session)))
    if claude().available() and open_n < int(get_setting("max_open_questions", session)) // 2:
        # read recently processed material and ask for gaps it reveals
        recent = session.execute(select(Resource).where(Resource.processing_status.in_(("extracted", "metadata_only")),
                                                        Resource.ai_status == "done")
                                 .order_by(Resource.processed_at.desc()).limit(6)).scalars().all()
        passages, by_chunk = [], {}
        for r in recent:
            c = session.execute(select(Chunk).where(Chunk.resource_id == r.id).order_by(Chunk.seq).limit(1)).scalars().first()
            if c:
                passages.append(c)
                by_chunk[c.id] = r.id
        if passages:
            try:
                cands = ai_candidates(session, "Newly processed resources in the collection.", passages, by_chunk,
                                      existing_texts(session))
                result["ai"] = len(admit(session, cands))
            except (AIUnavailable, AIBudgetExceeded, AIRefused) as e:
                result["ai_error"] = str(e)[:200]
    return result


def research_cycle(session: Session, job_id: int | None = None) -> dict:
    if not get_setting("automation_enabled", session):
        return {"skipped": "automation disabled"}
    out: dict = {}
    obj = session.execute(select(ResearchObjective).where(ResearchObjective.status == "active",
                                                          ResearchObjective.planned_at.is_(None))
                          .order_by(ResearchObjective.priority.desc()).limit(1)).scalars().first()
    if obj:
        out["planned"] = plan_objective(session, obj)
    out["new_questions"] = top_up_questions(session)
    n = int(get_setting("max_questions_per_cycle", session))
    chosen = session.execute(select(ResearchQuestion).where(ResearchQuestion.status == "open",
                                                            ResearchQuestion.attempts < 3)
                             .order_by(ResearchQuestion.priority.desc(), ResearchQuestion.id).limit(n)).scalars().all()
    out["investigating"] = [investigate(session, q, job_id) for q in chosen]
    audit(session, "coordinator", "research_cycle",
          f"planned={bool(obj)} questions_added={out['new_questions']} investigating={[q.id for q in chosen]}")
    return out
