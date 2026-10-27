"""Daily research reports and next-day plans (stored permanently in daily_reports)."""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import (
    AgentRun,
    Claim,
    DailyReport,
    Entity,
    Finding,
    Job,
    ResearchQuestion,
    Resource,
    ResourcePillar,
    ResourceTopic,
    SearchLog,
    Source,
    Topic,
)
from ..settings import get_usage
from ..search.fts import resource_brief


def _bounds(day: date) -> tuple[datetime, datetime]:
    """Local-day bounds converted to the naive-UTC timestamps stored in the database."""
    start_local = datetime.combine(day, time.min).astimezone()  # aware, local time zone
    end_local = datetime.combine(day + timedelta(days=1), time.min).astimezone()
    return (start_local.astimezone(timezone.utc).replace(tzinfo=None),
            end_local.astimezone(timezone.utc).replace(tzinfo=None))


def compute_stats(session: Session, day: date) -> dict[str, Any]:
    a, b = _bounds(day)
    in_day = lambda col: (col >= a) & (col < b)  # noqa: E731
    new = session.execute(select(Resource).where(in_day(Resource.discovered_at), Resource.duplicate_of_id.is_(None),
                                 Resource.deleted.is_(False))
                          .order_by(Resource.discovered_at.desc())).scalars().all()
    by_type = Counter(r.resource_type for r in new)
    by_lang = Counter(r.language or "und" for r in new)
    by_source = Counter(r.source_key or "?" for r in new)
    by_access = Counter(r.access_status for r in new)
    ids = [r.id for r in new]
    pillar_counts: Counter = Counter()
    if ids:
        for (p,) in session.execute(select(ResourcePillar.pillar).where(ResourcePillar.resource_id.in_(ids))):
            pillar_counts[p] += 1
    unclassified = len([r for r in new if not r.pillars])
    entities = session.execute(select(Entity).where(in_day(Entity.discovered_at))).scalars().all()
    ent_types = Counter(e.entity_type for e in entities)
    q_created = session.execute(select(func.count()).select_from(ResearchQuestion).where(in_day(ResearchQuestion.created_at))).scalar()
    q_invest = session.execute(select(func.count()).select_from(ResearchQuestion).where(in_day(ResearchQuestion.investigated_at))).scalar()
    q_answered = session.execute(select(func.count()).select_from(ResearchQuestion).where(
        ResearchQuestion.status == "answered", in_day(ResearchQuestion.updated_at))).scalar()
    q_open = session.execute(select(func.count()).select_from(ResearchQuestion).where(ResearchQuestion.status == "open")).scalar()
    findings = session.execute(select(Finding).where(in_day(Finding.created_at))).scalars().all()
    claims = session.execute(select(func.count()).select_from(Claim).where(in_day(Claim.created_at))).scalar()
    claims_verified = session.execute(select(func.count()).select_from(Claim).where(
        in_day(Claim.created_at), Claim.quote_verified.is_(True))).scalar()
    jobs = session.execute(select(Job.job_type, Job.status, func.count()).where(
        in_day(Job.finished_at) | (in_day(Job.created_at) & Job.status.in_(("queued", "running"))))
        .group_by(Job.job_type, Job.status)).all()
    job_summary: dict[str, dict[str, int]] = {}
    for jt, st, n in jobs:
        job_summary.setdefault(jt, {})[st] = n
    searches = session.execute(select(SearchLog.adapter, func.count(), func.sum(SearchLog.new_resources))
                               .where(in_day(SearchLog.executed_at)).group_by(SearchLog.adapter)).all()
    processed = session.execute(select(func.count()).select_from(Resource).where(in_day(Resource.processed_at))).scalar()
    downloaded = session.execute(select(func.count()).select_from(Resource).where(
        in_day(Resource.collected_at), Resource.acquisition_status == "downloaded")).scalar()
    failed_jobs = session.execute(select(Job).where(Job.status == "failed", in_day(Job.finished_at))
                                  .order_by(Job.finished_at.desc()).limit(20)).scalars().all()
    # emerging topics: today's topic counts vs the previous 7-day daily average
    def topic_counts(x: datetime, y: datetime) -> Counter:
        rows = session.execute(select(ResourceTopic.topic_id, func.count()).join(Resource, Resource.id == ResourceTopic.resource_id)
                               .where(Resource.discovered_at >= x, Resource.discovered_at < y)
                               .group_by(ResourceTopic.topic_id)).all()
        return Counter(dict(rows))
    today_t = topic_counts(a, b)
    prev_t = topic_counts(a - timedelta(days=7), a)
    topics = {t.id: t for t in session.execute(select(Topic)).scalars()}
    emerging = sorted(
        ({"topic": topics[t].name_en, "topic_ar": topics[t].name_ar, "today": n, "prev_daily_avg": round(prev_t.get(t, 0) / 7, 2)}
         for t, n in today_t.items() if t in topics and n > prev_t.get(t, 0) / 7 * 1.5 and n >= 2),
        key=lambda x: x["today"], reverse=True)[:8]
    gap_qs = session.execute(select(ResearchQuestion).where(in_day(ResearchQuestion.created_at))
                             .order_by(ResearchQuestion.priority.desc()).limit(15)).scalars().all()
    gap_findings = [f for f in findings if f.finding_type in ("gap", "insufficient")][:15]
    return {
        "day": day.isoformat(),
        "discoveries": {
            "total": len(new), "by_type": dict(by_type), "by_language": dict(by_lang), "by_source": dict(by_source),
            "by_access": dict(by_access), "paid_catalogued": by_access.get("paid", 0),
            "entities": dict(ent_types),
            "institutions": [{"id": e.id, "name": e.name} for e in entities if e.entity_type == "organization"][:15],
            "experts": [{"id": e.id, "name": e.name} for e in entities if e.entity_type == "person"][:15],
            "items": [resource_brief(r) for r in new[:40]],
        },
        "pillars": {"children": pillar_counts.get("children", 0), "parents": pillar_counts.get("parents", 0),
                    "murabbi": pillar_counts.get("murabbi", 0), "unclassified": unclassified},
        "research": {
            "questions_created": q_created, "questions_investigated": q_invest, "questions_answered": q_answered,
            "open_questions": q_open, "findings": len(findings),
            "findings_with_verified_evidence": sum(1 for f in findings if any(e.get("quote_verified") for e in f.evidence)),
            "claims_extracted": claims, "claims_with_verified_quotes": claims_verified,
            "findings_list": [{"id": f.id, "question_id": f.question_id, "statement": f.statement[:300],
                               "type": f.finding_type, "confidence": f.confidence, "qa": f.qa_status}
                              for f in findings[:20]],
        },
        "activity": {
            "searches": [{"source": ad, "searches": n, "new": int(nn or 0)} for ad, n, nn in searches],
            "sources_visited": session.execute(select(func.count()).select_from(Source).where(in_day(Source.last_run_at))).scalar(),
            "downloaded": downloaded, "processed": processed, "jobs": job_summary,
            "failed_jobs": [{"id": j.id, "type": j.job_type, "error": (j.error or "")[:200]} for j in failed_jobs],
            "pending_jobs": session.execute(select(func.count()).select_from(Job).where(Job.status == "queued")).scalar(),
            "http_requests": get_usage(session, "http_requests", day),
            "ai_calls": get_usage(session, "ai_calls", day), "ai_cost_usd": round(get_usage(session, "ai_cost_usd", day), 4),
        },
        "gaps": {
            "emerging_topics": emerging,
            "new_questions": [{"id": q.id, "text": q.text, "text_alt": q.text_alt, "kind": q.kind,
                               "priority": q.priority, "rationale": q.rationale} for q in gap_qs],
            "gap_findings": [{"id": f.id, "statement": f.statement[:300], "question_id": f.question_id} for f in gap_findings],
        },
    }


def next_day_plan(session: Session) -> dict[str, Any]:
    tomorrow_end = utcnow() + timedelta(days=1)
    qs = session.execute(select(ResearchQuestion).where(ResearchQuestion.status == "open")
                         .order_by(ResearchQuestion.priority.desc()).limit(12)).scalars().all()
    sources = session.execute(select(Source).where(Source.enabled.is_(True), Source.next_run_at <= tomorrow_end)
                              .order_by(Source.next_run_at)).scalars().all()
    pending_docs = session.execute(select(Resource).where(
        (Resource.acquisition_status == "pending") | (Resource.processing_status.in_(("pending", "needs_ocr"))))
        .order_by(Resource.discovered_at).limit(15)).scalars().all()
    queued = dict(session.execute(select(Job.job_type, func.count()).where(Job.status == "queued").group_by(Job.job_type)).all())
    return {
        "prioritized_questions": [{"id": q.id, "text": q.text, "text_alt": q.text_alt, "priority": q.priority,
                                   "kind": q.kind, "pillars": q.pillars} for q in qs],
        "sources_to_revisit": [{"id": s.id, "name": s.name, "next_run_at": s.next_run_at.isoformat() if s.next_run_at else None}
                               for s in sources if (s.config or {}).get("role") != "search"],
        "pending_documents": [{"id": r.id, "title": r.title, "acquisition": r.acquisition_status,
                               "processing": r.processing_status} for r in pending_docs],
        "queued_jobs": queued,
        "deferred_questions": session.execute(select(func.count()).select_from(ResearchQuestion)
                                              .where(ResearchQuestion.status == "deferred")).scalar(),
    }


def summary_text(stats: dict[str, Any]) -> str:
    d, p, r, a = stats["discoveries"], stats["pillars"], stats["research"], stats["activity"]
    return (f"{d['total']} new resources ({', '.join(f'{k}: {v}' for k, v in d['by_type'].items()) or 'none'}); "
            f"pillars - children {p['children']}, parents {p['parents']}, murabbi {p['murabbi']}. "
            f"{a['downloaded']} files downloaded, {a['processed']} processed. "
            f"Questions: {r['questions_created']} created, {r['questions_investigated']} investigated, "
            f"{r['questions_answered']} answered; {r['findings']} findings "
            f"({r['findings_with_verified_evidence']} with verified evidence). "
            f"{len(a['failed_jobs'])} failed job(s).")


def build_daily_report(session: Session, day: date, finalize: bool = False) -> DailyReport:
    stats = compute_stats(session, day)
    rep = session.get(DailyReport, day)
    if rep is None:
        rep = DailyReport(day=day)
        session.add(rep)
    if rep.finalized and not finalize:
        return rep
    rep.stats = stats
    rep.summary = summary_text(stats)
    if finalize or day == date.today():
        rep.plan = next_day_plan(session)
    rep.finalized = finalize
    rep.generated_at = utcnow()
    session.add(AgentRun(agent="coordinator", action="daily_report", detail=f"{day} finalized={finalize}"))
    return rep
