"""Job handlers: the glue between the durable queue, the collectors and the agents."""
from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, select

from ..ai.claude import AIBudgetExceeded, AIRefused, AIUnavailable, claude
from ..db import utcnow
from ..ingest.extract import SUPPORTED_EXT
from ..ingest.pipeline import AcquisitionError, acquire, import_local_file, process, register_with_content, save_inline_segments
from ..ingest.registry import ResourceIn
from ..models import Citation, Job, Output, ResearchObjective, ResearchQuestion, Resource, SearchLog, Source
from ..settings import get_setting
from ..sources.base import CollectContext, NotConfigured
from ..sources.registry import ADAPTERS, LocalFolderAdapter, refresh_credential_health
from ..storage import absolute
from . import queue
from .worker import Deferred, JobContext, PermanentFailure, handler

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ shared

def after_register(ctx: JobContext, r: Resource, created: bool, d: ResourceIn | None = None) -> None:
    """Queue the next pipeline step for a newly registered (or updated) resource."""
    s = ctx.session
    if not created and d is not None and d.extra.get("updated_content") and (d.text or d.segments):
        save_inline_segments(r, d.segments or [{"text": d.text}])  # page changed: re-index new version
        r.extra = {**(r.extra or {}), "content_updated_at": utcnow().isoformat()}
        r.processing_status = "pending"
        created = True
    if not created:
        return
    if r.acquisition_status == "pending":
        queue.enqueue(s, "acquire", {"resource_id": r.id}, priority=50, group="acquisition", dedupe_key=f"acquire:{r.id}")
    else:
        queue.enqueue(s, "process", {"resource_id": r.id}, priority=55, group="processing", dedupe_key=f"process:{r.id}")


def claude_ocr(path: Path, pages: list[int]) -> dict[int, str]:
    import pymupdf

    out: dict[int, str] = {}
    src = pymupdf.open(path)
    for i in range(0, len(pages), 10):
        batch = pages[i:i + 10]
        sub = pymupdf.open()
        for p in batch:
            sub.insert_pdf(src, from_page=p - 1, to_page=p - 1)
        out.update(claude().ocr_pdf_pages(sub.tobytes(), batch))
        sub.close()
    src.close()
    return out


# ------------------------------------------------------------------ collection

@handler("collect_source")
def collect_source(ctx: JobContext) -> dict[str, Any]:
    s = ctx.session
    src = s.get(Source, ctx.payload["source_id"])
    if src is None:
        raise PermanentFailure("source no longer exists")
    adapter = ADAPTERS.get(src.adapter)
    if adapter is None:
        raise PermanentFailure(f"unknown adapter {src.adapter}")
    src.last_run_at = utcnow()
    messages: list[str] = []
    created = updated = seen = 0
    try:
        if isinstance(adapter, LocalFolderAdapter):
            folder = adapter.folder(src.config or {})
            folder.mkdir(parents=True, exist_ok=True)
            for f in sorted(folder.iterdir()):
                if f.is_file() and f.suffix.lower() in SUPPORTED_EXT:
                    r, new = import_local_file(s, f, resource_type=(src.config or {}).get("resource_type", "book"))
                    seen += 1
                    if new:
                        created += 1
                        r.source_id, r.source_key = src.id, src.key
                        after_register(ctx, r, True)
                    done = folder / "imported"
                    done.mkdir(exist_ok=True)
                    f.replace(done / f.name)
        else:
            adapter.require()
            state = dict(src.state or {})
            cctx = CollectContext(source_config=src.config or {}, checkpoint=ctx.checkpoint,
                                  save_checkpoint=lambda cp: ctx.heartbeat(cp), should_stop=ctx.should_stop,
                                  log=messages.append, source_id=src.id, source_key=src.key, session=s, state=state,
                                  commit=ctx.commit)
            ctx.commit()
            for d in adapter.collect(cctx):
                d.source_id, d.source_key = src.id, src.key
                r, new = register_with_content(s, d)
                seen += 1
                created += int(new)
                updated += int(bool(not new and d.extra.get("updated_content")))
                after_register(ctx, r, new, d)
                src.state = state
                ctx.commit()  # one short transaction per collected item
                if seen % 20 == 0:
                    ctx.heartbeat(ctx.checkpoint)
                if ctx.should_stop():
                    break
            src.state = state
    except NotConfigured as e:
        src.health, src.last_error = "needs_credentials", str(e)
        raise PermanentFailure(str(e)) from e
    except Exception as e:
        src.health, src.last_error = "error", f"{type(e).__name__}: {e}"[:2000]
        s.commit()  # keep the health status even though the job fails
        raise
    src.health, src.last_error = "ok", "; ".join(messages)[-2000:] or None
    src.last_success_at = utcnow()
    src.items_collected = (src.items_collected or 0) + created
    src.last_result = {"seen": seen, "new": created, "updated": updated, "at": utcnow().isoformat()}
    ctx.audit("social_media" if adapter.info.kind in ("social", "video") else "discovery", "collect_source",
              f"{src.name}: {seen} seen, {created} new, {updated} updated")
    if ctx.stop_event.is_set():
        s.commit()  # keep what was collected; the rest resumes from the checkpoint
        raise Deferred("worker stopping; collection resumes from checkpoint", utcnow())
    return {"seen": seen, "new": created, "updated": updated, "messages": messages[-10:]}


@handler("search_source")
def search_source(ctx: JobContext) -> dict[str, Any]:
    from ..agents.discovery import query_key

    s = ctx.session
    p = ctx.payload
    src = s.get(Source, p["source_id"])
    if src is None:
        raise PermanentFailure("source no longer exists")
    adapter = ADAPTERS[src.adapter]
    log_row = SearchLog(adapter=src.adapter, query=p["query"], query_key=query_key(src.adapter, p["query"]),
                        lang=p.get("lang"), question_id=p.get("question_id"))
    s.add(log_row)
    src.last_run_at = utcnow()
    ctx.commit()
    try:
        items = adapter.search(p["query"], p.get("lang"), int(p.get("limit", 15)))
    except NotConfigured as e:
        log_row.status, log_row.error = "not_configured", str(e)
        src.health = "needs_credentials"
        return {"skipped": str(e)}
    except Exception as e:
        log_row.status, log_row.error = "error", f"{type(e).__name__}: {e}"[:2000]
        src.health, src.last_error = "error", log_row.error
        s.commit()
        raise
    new = 0
    for d in items:
        d.source_id = src.id
        d.question_id = p.get("question_id")
        r, created = register_with_content(s, d)
        new += int(created)
        after_register(ctx, r, created, d)
        if p.get("question_id"):
            q = s.get(ResearchQuestion, p["question_id"])
            if q is not None and r.id not in (q.related_resource_ids or []):
                q.related_resource_ids = [*(q.related_resource_ids or []), r.id][-200:]
    log_row.results, log_row.new_resources = len(items), new
    src.health, src.last_success_at, src.last_error = "ok", utcnow(), None
    src.items_collected = (src.items_collected or 0) + new
    ctx.audit("discovery", "search", f"{src.adapter} '{p['query']}' -> {len(items)} results, {new} new",
              question_id=p.get("question_id"))
    return {"results": len(items), "new": new}


# ------------------------------------------------------------------ pipeline

@handler("acquire")
def acquire_job(ctx: JobContext) -> dict[str, Any]:
    r = ctx.session.get(Resource, ctx.payload["resource_id"])
    if r is None:
        raise PermanentFailure("resource deleted")
    try:
        status = acquire(ctx.session, r)
    except AcquisitionError as e:
        if "limit" in str(e).lower():
            raise Deferred(str(e), (utcnow() + timedelta(days=1)).replace(hour=0, minute=15)) from e
        r.acquisition_status = "failed" if not e.transient else r.acquisition_status
        r.last_error = str(e)
        ctx.session.commit()
        if e.transient:
            raise
        raise PermanentFailure(str(e)) from e
    if status in ("downloaded", "metadata_only", "text_collected"):
        queue.enqueue(ctx.session, "process", {"resource_id": r.id}, priority=55, group="processing",
                      dedupe_key=f"process:{r.id}")
    ctx.audit("acquisition", "acquire", f"{r.title[:100]} -> {status}", resource_id=r.id)
    return {"status": status, "error": r.last_error}


@handler("process")
def process_job(ctx: JobContext) -> dict[str, Any]:
    r = ctx.session.get(Resource, ctx.payload["resource_id"])
    if r is None:
        raise PermanentFailure("resource deleted")
    ocr = claude_ocr if claude().available() else None
    status = process(ctx.session, r, ocr)
    if status in ("extracted", "low_quality", "metadata_only", "needs_ocr") and r.chunks:
        if claude().available():
            queue.enqueue(ctx.session, "analyze", {"resource_id": r.id}, priority=65, group="ai",
                          dedupe_key=f"analyze:{r.id}")
        else:
            r.ai_status = "skipped_no_ai"
    ctx.audit("processing", "process", f"{r.title[:100]} -> {status} ({r.language}, {len(r.chunks)} passages)",
              resource_id=r.id)
    return {"status": status, "language": r.language, "chunks": len(r.chunks)}


@handler("analyze")
def analyze_job(ctx: JobContext) -> dict[str, Any]:
    from ..agents.knowledge import analyze_resource

    r = ctx.session.get(Resource, ctx.payload["resource_id"])
    if r is None:
        raise PermanentFailure("resource deleted")
    try:
        return analyze_resource(ctx.session, r)
    except AIUnavailable:
        r.ai_status = "skipped_no_ai"
        return {"skipped": "no AI"}
    except AIBudgetExceeded as e:
        raise Deferred(str(e), (utcnow() + timedelta(days=1)).replace(hour=0, minute=20)) from e
    except AIRefused as e:
        r.ai_status = "failed"
        r.last_error = str(e)
        raise PermanentFailure(str(e)) from e


# ------------------------------------------------------------------ research

@handler("research_cycle")
def research_cycle_job(ctx: JobContext) -> dict[str, Any]:
    from ..agents.coordinator import research_cycle

    return research_cycle(ctx.session, ctx.job_id)


@handler("plan_objective")
def plan_job(ctx: JobContext) -> dict[str, Any]:
    from ..agents.planner import plan_objective

    obj = ctx.session.get(ResearchObjective, ctx.payload["objective_id"])
    if obj is None:
        raise PermanentFailure("objective deleted")
    return plan_objective(ctx.session, obj)


@handler("investigate_question")
def investigate_job(ctx: JobContext) -> dict[str, Any]:
    from ..agents.discovery import investigate

    q = ctx.session.get(ResearchQuestion, ctx.payload["question_id"])
    if q is None:
        raise PermanentFailure("question deleted")
    return investigate(ctx.session, q, ctx.job_id)


@handler("synthesize_question")
def synthesize_job(ctx: JobContext) -> dict[str, Any]:
    from ..agents.synthesis import pending_work, synthesize

    q = ctx.session.get(ResearchQuestion, ctx.payload["question_id"])
    if q is None:
        raise PermanentFailure("question deleted")
    waits = int(ctx.checkpoint.get("waits", 0))
    if pending_work(ctx.session, q) and waits < 6:
        ctx.heartbeat({"waits": waits + 1})
        raise Deferred("waiting for searches / processing of new sources", utcnow() + timedelta(minutes=10))
    try:
        return synthesize(ctx.session, q)
    except AIBudgetExceeded as e:
        raise Deferred(str(e), (utcnow() + timedelta(days=1)).replace(hour=0, minute=30)) from e


@handler("qa")
def qa_job(ctx: JobContext) -> dict[str, Any]:
    from ..agents.qa import run_qa

    return run_qa(ctx.session, with_links=ctx.payload.get("links", True))


@handler("fetch_citations")
def fetch_citations_job(ctx: JobContext) -> dict[str, Any]:
    """Collect works referenced by a resource (OpenAlex referenced_works)."""
    s = ctx.session
    r = s.get(Resource, ctx.payload["resource_id"])
    if r is None:
        return {}
    refs = (r.extra or {}).get("referenced_works") or []
    adapter = ADAPTERS["openalex"]
    new = 0
    for d in adapter.fetch_works(refs[:50]):  # type: ignore[attr-defined]
        nr, created = register_with_content(s, d)
        new += int(created)
        after_register(ctx, nr, created, d)
        if s.execute(select(Citation).where(Citation.resource_id == r.id, Citation.external_id == d.external_id)).first() is None:
            s.add(Citation(resource_id=r.id, title=d.title, doi=d.doi, external_id=d.external_id, year=d.year,
                           cited_resource_id=nr.id, status="collected"))
    r.extra = {**(r.extra or {}), "citations_fetched": True}
    ctx.audit("discovery", "fetch_citations", f"{r.title[:80]}: {new} new cited works", resource_id=r.id)
    return {"new": new}


@handler("embed")
def embed_job(ctx: JobContext) -> dict[str, Any]:
    from ..search import semantic

    if not semantic.available():
        return {"skipped": "VOYAGE_API_KEY not set"}
    return {"embedded": semantic.embed_pending(ctx.session, limit=int(ctx.payload.get("limit", 512)))}


@handler("generate_output")
def output_job(ctx: JobContext) -> dict[str, Any]:
    from ..agents.outputs import generate

    o = ctx.session.get(Output, ctx.payload["output_id"])
    if o is None:
        raise PermanentFailure("output deleted")
    try:
        generate(ctx.session, o)
    except (AIUnavailable, AIRefused, ValueError) as e:
        o.status, o.error = "failed", str(e)
        return {"status": "failed", "error": str(e)}
    return {"status": o.status}


@handler("daily_report")
def daily_report_job(ctx: JobContext) -> dict[str, Any]:
    from ..agents.reports import build_daily_report

    day = date.fromisoformat(ctx.payload["day"])
    rep = build_daily_report(ctx.session, day, finalize=bool(ctx.payload.get("finalize")))
    return {"day": day.isoformat(), "finalized": rep.finalized}


@handler("maintenance")
def maintenance_job(ctx: JobContext) -> dict[str, Any]:
    """Sweep for work that has no active job (e.g. after a crash or a newly added API key)."""
    s = ctx.session
    refresh_credential_health()
    active = {(j.job_type, (j.payload or {}).get("resource_id")) for j in
              s.execute(select(Job).where(Job.status.in_(queue.ACTIVE))).scalars()}
    out = {"acquire": 0, "process": 0, "analyze": 0, "citations": 0, "resynthesize": 0, "qa": 0}
    for r in s.execute(select(Resource).where(Resource.acquisition_status == "pending").limit(200)).scalars():
        if ("acquire", r.id) not in active:
            queue.enqueue(s, "acquire", {"resource_id": r.id}, group="acquisition", dedupe_key=f"acquire:{r.id}")
            out["acquire"] += 1
    for r in s.execute(select(Resource).where(Resource.processing_status == "pending",
                                              Resource.acquisition_status.in_(("downloaded", "metadata_only", "text_collected")))
                       .limit(200)).scalars():
        if ("process", r.id) not in active:
            queue.enqueue(s, "process", {"resource_id": r.id}, group="processing", dedupe_key=f"process:{r.id}")
            out["process"] += 1
    if claude().available():
        for r in s.execute(select(Resource).where(Resource.ai_status.in_(("pending", "skipped_no_ai")),
                                                  Resource.index_status == "indexed")
                           .order_by(Resource.discovered_at.desc()).limit(20)).scalars():
            if ("analyze", r.id) not in active and r.chunks:
                queue.enqueue(s, "analyze", {"resource_id": r.id}, priority=65, group="ai", dedupe_key=f"analyze:{r.id}")
                out["analyze"] += 1
        for q in s.execute(select(ResearchQuestion).where(ResearchQuestion.status == "deferred").limit(5)).scalars():
            q.status = "investigating"
            queue.enqueue(s, "synthesize_question", {"question_id": q.id}, priority=55, group="research",
                          dedupe_key=f"synth:{q.id}")
            out["resynthesize"] += 1
    # follow citations of relevant open-access papers (bounded)
    openalex = s.execute(select(Source).where(Source.key == "openalex")).scalars().first()
    if openalex is not None and openalex.enabled:
        for r in s.execute(select(Resource).where(Resource.source_key == "openalex").order_by(Resource.id.desc()).limit(30)).scalars():
            if (r.extra or {}).get("referenced_works") and not (r.extra or {}).get("citations_fetched") and r.pillars:
                queue.enqueue(s, "fetch_citations", {"resource_id": r.id}, priority=70, group="openalex",
                              dedupe_key=f"citations:{r.id}")
                out["citations"] += 1
                if out["citations"] >= 3:
                    break
    from ..search import semantic

    if semantic.available():
        queue.enqueue(s, "embed", {"limit": 512}, priority=68, group="embeddings", dedupe_key="embed")
        out["embed"] = 1
    last_qa = s.execute(select(func.max(Job.created_at)).where(Job.job_type == "qa")).scalar()
    if last_qa is None or last_qa < utcnow() - timedelta(hours=6):
        queue.enqueue(s, "qa", {"links": True}, priority=70, dedupe_key="qa")
        out["qa"] = 1
    # keep the database small: drop succeeded job rows older than 60 days (audit log is kept)
    old = s.execute(select(Job).where(Job.status == "succeeded", Job.finished_at < utcnow() - timedelta(days=60)).limit(2000)).scalars().all()
    for j in old:
        s.delete(j)
    out["pruned_jobs"] = len(old)
    return out
