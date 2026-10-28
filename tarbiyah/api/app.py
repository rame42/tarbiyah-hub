"""FastAPI application: REST API under /api and the built dashboard at /.

Security: binds to 127.0.0.1 by default. Credentials are never returned by any
endpoint (only whether each one is configured).
"""
from __future__ import annotations

import shutil
import tempfile
from urllib.parse import urlsplit
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import String, case, func, or_, select
from sqlalchemy.orm import Session

from ..bootstrap import init_app
from ..config import PROJECT_ROOT, get_config
from ..db import get_session, utcnow
from ..jobs import queue
from ..models import (
    AgentRun,
    Chunk,
    Citation,
    Claim,
    DailyReport,
    Entity,
    Finding,
    GlossaryTerm,
    Job,
    Output,
    ResearchObjective,
    ResearchQuestion,
    Resource,
    ResourceEntity,
    ResourcePillar,
    ResourceTopic,
    SearchLog,
    Source,
    Topic,
)
from ..search.fts import SearchFilters, resource_brief, search
from ..ai.claude import claude
from ..settings import DEFAULTS, flush_usage, get_all, set_setting
from ..sources.registry import ADAPTERS, adapter_status, refresh_credential_health
from ..storage import absolute
from ..taxonomy import PILLAR_LABELS
from .status import system_status

@asynccontextmanager
async def lifespan(_app: FastAPI):
    from ..runfiles import clear_pid, write_pid

    init_app()
    write_pid("web")
    yield
    flush_usage()
    clear_pid("web")


app = FastAPI(title="Tarbiyah Hub", version="0.1.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def _flush_usage(request, call_next):
    response = await call_next(request)
    flush_usage()
    return response


def _404(what: str) -> HTTPException:
    return HTTPException(status_code=404, detail=f"{what} not found")


# ============================================================== status & dashboard

@app.get("/api/status")
def status(s: Session = Depends(get_session)) -> dict[str, Any]:
    return system_status(s)


@app.get("/api/meta")
def meta(s: Session = Depends(get_session)) -> dict[str, Any]:
    topics = s.execute(select(Topic).order_by(Topic.pillar, Topic.name_en)).scalars().all()
    types = [t for (t,) in s.execute(select(Resource.resource_type).distinct())]
    sources = [k for (k,) in s.execute(select(Resource.source_key).distinct()) if k]
    return {"pillars": PILLAR_LABELS,
            "topics": [{"id": t.id, "slug": t.slug, "name_en": t.name_en, "name_ar": t.name_ar, "pillar": t.pillar} for t in topics],
            "resource_types": sorted(types), "source_keys": sorted(sources)}


@app.get("/api/dashboard")
def dashboard(day: str | None = None, s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..agents.reports import build_daily_report, compute_stats, next_day_plan

    d = date.fromisoformat(day) if day else date.today()
    rep = s.get(DailyReport, d)
    if d == date.today() or rep is None:
        stats = compute_stats(s, d)
        plan = next_day_plan(s) if d == date.today() else (rep.plan if rep else {})
        live = True
    else:
        stats, plan, live = rep.stats, rep.plan, False
    prev = s.get(DailyReport, d - timedelta(days=1))
    if prev is None and d == date.today():
        prev = build_daily_report(s, d - timedelta(days=1))
    return {"day": d.isoformat(), "live": live, "stats": stats, "plan": plan,
            "previous": {"day": prev.day.isoformat(), "summary": prev.summary, "stats": prev.stats,
                         "plan": prev.plan, "finalized": prev.finalized} if prev else None,
            "status": system_status(s)}


@app.get("/api/reports")
def reports(limit: int = 60, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = s.execute(select(DailyReport).order_by(DailyReport.day.desc()).limit(limit)).scalars().all()
    return [{"day": r.day.isoformat(), "summary": r.summary, "finalized": r.finalized,
             "discoveries": (r.stats or {}).get("discoveries", {}).get("total", 0),
             "pillars": (r.stats or {}).get("pillars", {}),
             "findings": (r.stats or {}).get("research", {}).get("findings", 0)} for r in rows]


@app.post("/api/reports/{day}/rebuild")
def rebuild_report(day: str, s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..agents.reports import build_daily_report

    d = date.fromisoformat(day)
    rep = build_daily_report(s, d, finalize=d < date.today())
    return {"day": day, "summary": rep.summary}


# ============================================================== library

@app.get("/api/resources")
def list_resources(q: str = "", language: str | None = None, pillar: str | None = None, type: str | None = None,
                   access: str | None = None, source: str | None = None, topic: int | None = None,
                   date_from: str | None = None, date_to: str | None = None, status: str | None = None,
                   label: str | None = None, show_deleted: bool = False, view: str = "active",
                   min_relevance: int | None = None, max_relevance: int | None = None, sort: str = "newest",
                   page: int = 1, page_size: int = 25, cross_language: bool = True,
                   s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..search.fts import pillar_clause, view_clause

    if show_deleted:
        view = "deleted"
    f = SearchFilters(language=language, pillar=pillar, resource_type=type, access_status=access, source_key=source,
                      topic_id=topic, discovered_from=date_from, discovered_to=date_to, label=label, view=view,
                      min_relevance=min_relevance, max_relevance=max_relevance)
    offset = (max(1, page) - 1) * page_size
    if q.strip() and view != "deleted":
        res = search(s, q, f, limit=page_size, offset=offset, cross_language=cross_language)
        return {**res, "page": page, "page_size": page_size}
    stmt = select(Resource).where(Resource.duplicate_of_id.is_(None), view_clause(view))
    if min_relevance is not None:
        stmt = stmt.where(Resource.relevance >= min_relevance)
    if max_relevance is not None:
        stmt = stmt.where(Resource.relevance <= max_relevance)
    if label:
        import json as _json

        stmt = stmt.where(Resource.labels.cast(String).like(f"%{_json.dumps(label)[1:-1]}%"))
    if language:
        stmt = stmt.where(Resource.language == language)
    if type:
        stmt = stmt.where(Resource.resource_type == type)
    if access:
        stmt = stmt.where(Resource.access_status == access)
    if source:
        stmt = stmt.where(Resource.source_key == source)
    if status:
        stmt = stmt.where(or_(Resource.processing_status == status, Resource.acquisition_status == status))
    if date_from:
        stmt = stmt.where(Resource.discovered_at >= date_from)
    if date_to:
        stmt = stmt.where(Resource.discovered_at < date_to + "T23:59:59.999")
    if pillar:
        stmt = stmt.where(pillar_clause(pillar))
    if topic:
        stmt = stmt.where(Resource.id.in_(select(ResourceTopic.resource_id).where(ResourceTopic.topic_id == topic)))
    total = s.execute(select(func.count()).select_from(stmt.subquery())).scalar()
    order = {"relevance_low": (Resource.relevance.asc().nulls_first(), Resource.id.desc()),
             "relevance_high": (Resource.relevance.desc().nulls_last(), Resource.id.desc()),
             "oldest": (Resource.discovered_at.asc(),)}.get(sort, (Resource.discovered_at.desc(),))
    rows = s.execute(stmt.order_by(*order).offset(offset).limit(page_size)).scalars().all()
    return {"query": "", "total": total, "page": page, "page_size": page_size,
            "results": [{"resource": resource_brief(r), "passage": None,
                         "description_snippet": (r.description or "")[:240] or None} for r in rows]}


@app.get("/api/resources/{rid}")
def get_resource(rid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    r = s.get(Resource, rid)
    if r is None:
        raise _404("resource")
    topics = s.execute(select(Topic, ResourceTopic.score, ResourceTopic.method).join(ResourceTopic)
                       .where(ResourceTopic.resource_id == rid)).all()
    ents = s.execute(select(Entity, ResourceEntity.role).join(ResourceEntity, ResourceEntity.entity_id == Entity.id)
                     .where(ResourceEntity.resource_id == rid)).all()
    claims = s.execute(select(Claim).where(Claim.resource_id == rid).order_by(Claim.id)).scalars().all()
    cits = s.execute(select(Citation).where(Citation.resource_id == rid)).scalars().all()
    history = s.execute(select(AgentRun).where(AgentRun.resource_id == rid).order_by(AgentRun.created_at.desc()).limit(50)).scalars().all()
    jobs = s.execute(select(Job).where(Job.payload["resource_id"].as_integer() == rid).order_by(Job.id.desc()).limit(20)).scalars().all()
    chunk_count = s.execute(select(func.count()).select_from(Chunk).where(Chunk.resource_id == rid)).scalar()
    source = s.get(Source, r.source_id) if r.source_id else None
    data = {c.name: getattr(r, c.name) for c in Resource.__table__.columns}
    data.pop("text_path", None)
    return {
        **data,
        "pillars": [{"pillar": p.pillar, "score": p.score, "method": p.method} for p in r.pillars],
        "topics": [{"id": t.id, "name_en": t.name_en, "name_ar": t.name_ar, "score": sc, "method": m} for t, sc, m in topics],
        "entities": [{"id": e.id, "type": e.entity_type, "name": e.name, "role": role} for e, role in ents],
        "claims": [{"id": c.id, "type": c.claim_type, "statement": c.statement, "quote": c.quote, "page": c.page,
                    "evidence_type": c.evidence_type, "verified": c.quote_verified, "qa": c.qa_status,
                    "generated_by": c.generated_by, "chunk_id": c.chunk_id} for c in claims],
        "citations": [{"id": c.id, "title": c.title, "raw": c.raw, "status": c.status, "doi": c.doi,
                       "cited_resource_id": c.cited_resource_id} for c in cits],
        "history": [{"at": h.created_at.isoformat(), "agent": h.agent, "action": h.action, "status": h.status,
                     "detail": h.detail} for h in history],
        "jobs": [{"id": j.id, "type": j.job_type, "status": j.status, "attempts": j.attempts, "error": j.error,
                  "finished_at": j.finished_at.isoformat() if j.finished_at else None} for j in jobs],
        "chunk_count": chunk_count,
        "source": {"id": source.id, "name": source.name, "adapter": source.adapter} if source else None,
        "has_file": bool(r.local_path and absolute(r.local_path).exists()),
    }


@app.get("/api/resources/{rid}/passages")
def resource_passages(rid: int, offset: int = 0, limit: int = 20, s: Session = Depends(get_session)) -> dict[str, Any]:
    rows = s.execute(select(Chunk).where(Chunk.resource_id == rid).order_by(Chunk.seq).offset(offset).limit(limit)).scalars().all()
    total = s.execute(select(func.count()).select_from(Chunk).where(Chunk.resource_id == rid)).scalar()
    return {"total": total, "passages": [{"id": c.id, "seq": c.seq, "page": c.page_start, "heading": c.heading,
                                          "lang": c.lang, "timestamp": c.timestamp_start, "text": c.text} for c in rows]}


@app.get("/api/passages/{cid}")
def get_passage(cid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    c = s.get(Chunk, cid)
    if c is None:
        raise _404("passage")
    r = s.get(Resource, c.resource_id)
    return {"id": c.id, "resource": resource_brief(r), "page": c.page_start, "heading": c.heading, "lang": c.lang,
            "timestamp": c.timestamp_start, "text": c.text}


def _download_name(r: Resource, p: Path) -> str:
    """A readable file name from the title (Arabic kept), safe for Windows."""
    import re as _re

    stem = _re.sub(r'[\\/:*?"<>|\x00-\x1f]+', " ", r.title or "")
    stem = _re.sub(r"\s+", " ", stem).strip().rstrip(".")[:90].strip() or p.stem
    return f"{stem}{p.suffix}"


@app.get("/api/resources/{rid}/file")
def resource_file(rid: int, download: bool = False, s: Session = Depends(get_session)):
    r = s.get(Resource, rid)
    if r is None or not r.local_path:
        raise _404("file")
    p = absolute(r.local_path)
    if not p.exists():
        raise _404("file")
    return FileResponse(p, media_type=r.file_mime or None, filename=_download_name(r, p),
                        content_disposition_type="attachment" if download else "inline")


@app.get("/api/files")
def list_files(q: str = "", type: str | None = None, pillar: str | None = None, view: str = "active",
               page: int = 1, page_size: int = 50, s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..search.fts import pillar_clause, view_clause

    stmt = select(Resource).where(Resource.local_path.is_not(None), Resource.duplicate_of_id.is_(None),
                                  view_clause(view))
    if q.strip():
        stmt = stmt.where(Resource.title.ilike(f"%{q.strip()}%"))
    if type:
        stmt = stmt.where(Resource.resource_type == type)
    if pillar:
        stmt = stmt.where(pillar_clause(pillar))
    sub = stmt.subquery()
    total, size = s.execute(select(func.count(), func.sum(sub.c.file_size)).select_from(sub)).one()
    rows = s.execute(stmt.order_by(Resource.discovered_at.desc()).offset((max(1, page) - 1) * page_size)
                     .limit(page_size)).scalars().all()
    items = []
    for r in rows:
        p = absolute(r.local_path)
        items.append({**resource_brief(r), "file_name": _download_name(r, p), "file_size": r.file_size,
                      "file_mime": r.file_mime, "ext": p.suffix.lstrip(".").lower(), "exists": p.exists()})
    return {"total": total or 0, "total_size": int(size or 0), "page": page, "page_size": page_size,
            "files_folder": str(get_config().files_dir), "items": items}


# ============================================================== courses

COURSE_QUERIES = {"ar": ["تربية الأبناء", "تربية الطفل المسلم", "تربية المراهقين", "إعداد المربين", "التربية الإيمانية للأطفال"],
                  "en": ["Islamic parenting", "raising Muslim children", "Muslim teenagers parenting",
                         "Islamic teacher training", "Quran teaching children"]}


@app.get("/api/courses")
def list_courses(price: str = "all", q: str = "", pillar: str | None = None, view: str = "active",
                 page: int = 1, page_size: int = 30, s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..search.fts import pillar_clause, view_clause

    stmt = select(Resource).where(Resource.resource_type == "course", Resource.duplicate_of_id.is_(None),
                                  view_clause(view))
    if price == "free":
        stmt = stmt.where(Resource.access_status.in_(("free_to_read", "open_access", "open_license", "public_domain")))
    elif price == "paid":
        stmt = stmt.where(Resource.access_status == "paid")
    if q.strip():
        stmt = stmt.where(or_(Resource.title.ilike(f"%{q.strip()}%"), Resource.publisher.ilike(f"%{q.strip()}%")))
    if pillar:
        stmt = stmt.where(pillar_clause(pillar))
    total = s.execute(select(func.count()).select_from(stmt.subquery())).scalar() or 0
    rows = s.execute(stmt.order_by(Resource.relevance.desc().nulls_last(), Resource.discovered_at.desc())
                     .offset((max(1, page) - 1) * page_size).limit(page_size)).scalars().all()
    counts = dict(s.execute(select(Resource.access_status, func.count()).where(
        Resource.resource_type == "course", Resource.duplicate_of_id.is_(None), view_clause("active"))
        .group_by(Resource.access_status)).all())
    free_n = sum(n for k, n in counts.items() if k in ("free_to_read", "open_access", "open_license", "public_domain"))
    return {"total": total, "page": page, "page_size": page_size,
            "counts": {"all": sum(counts.values()), "free": free_n, "paid": counts.get("paid", 0)},
            "items": [{**resource_brief(r), "provider": r.publisher, "price": r.price, "currency": r.currency,
                       "purchase_url": r.purchase_url, "description": (r.description or "")[:300] or None}
                      for r in rows]}


class CourseIn(BaseModel):
    title: str = ""
    url: str
    provider: str | None = None
    free: bool | None = None
    price: str | None = None
    currency: str | None = None
    description: str | None = None
    language: str | None = None


@app.post("/api/courses")
def add_course(body: CourseIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..ingest.courses import course_access
    from ..ingest.pipeline import register_with_content
    from ..ingest.registry import ResourceIn

    if not body.url.lower().startswith(("http://", "https://")):
        raise HTTPException(400, "Paste the full course link (starting with https://).")
    free = body.free if body.free is not None else (None if not body.price else False)
    info = {"free": free, "price": body.price, "currency": body.currency}
    d = ResourceIn(title=body.title.strip() or body.url, url=body.url, resource_type="course",
                   description=body.description, language=body.language, publisher=body.provider,
                   price=None if free else body.price, currency=None if free else body.currency,
                   purchase_url=None if free else body.url, source_key="manual", collection_method="manual",
                   access=course_access(info), extra={"fetch_page": True, "course": {**info, "provider": body.provider}})
    r, created = register_with_content(s, d)
    if created:
        queue.enqueue(s, "process", {"resource_id": r.id}, priority=30, group="processing", dedupe_key=f"process:{r.id}")
    return {"resource_id": r.id, "created": created}


class FindCoursesIn(BaseModel):
    query: str | None = None


@app.post("/api/courses/find")
def find_courses(body: FindCoursesIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    src = s.execute(select(Source).where(Source.adapter == "youtube_courses")).scalars().first()
    if src is None or not src.enabled:
        raise HTTPException(400, "The 'YouTube courses' source is disabled. Enable it on the Sources page.")
    if not get_config().youtube_api_key:
        raise HTTPException(400, "Finding courses on YouTube needs the free YouTube API key (Settings > Keys & AI).")
    pairs = [(body.query.strip(), None)] if body.query and body.query.strip() else \
        [(q, lang) for lang, qs in COURSE_QUERIES.items() for q in qs]
    jobs = [queue.enqueue(s, "search_source", {"source_id": src.id, "query": q, "lang": lang, "limit": 15},
                          priority=30, group="youtube", dedupe_key=f"search:{src.id}:{q}").id for q, lang in pairs]
    return {"queued": len(jobs), "message": f"Searching for courses with {len(jobs)} search(es) in the background."}


class ZipIn(BaseModel):
    ids: list[int]


@app.post("/api/files/zip")
def files_zip(body: ZipIn, s: Session = Depends(get_session)):
    import zipfile

    from starlette.background import BackgroundTask

    entries, total = [], 0
    for rid in body.ids[:1000]:
        r = s.get(Resource, rid)
        if r is None or not r.local_path or r.deleted:
            continue
        p = absolute(r.local_path)
        if p.exists():
            entries.append((r, p))
            total += p.stat().st_size
    if not entries:
        raise HTTPException(400, "None of the selected items has a downloaded file.")
    if total > 2 * 1024 ** 3:
        raise HTTPException(400, f"The selection is {total / 1024 ** 3:.1f} GB; choose at most 2 GB at a time.")
    tmpdir = Path(tempfile.mkdtemp(prefix="tarbiyah-zip-"))
    out = tmpdir / "tarbiyah-files.zip"
    used: set[str] = set()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for r, p in entries:
            name = _download_name(r, p)
            base, n = name, 1
            while name.lower() in used:
                n += 1
                name = f"{Path(base).stem} ({n}){p.suffix}"
            used.add(name.lower())
            z.write(p, arcname=name)
    return FileResponse(out, media_type="application/zip", filename=out.name,
                        background=BackgroundTask(shutil.rmtree, tmpdir, ignore_errors=True))


@app.get("/api/resources/{rid}/text", response_class=PlainTextResponse)
def resource_text(rid: int, s: Session = Depends(get_session)) -> str:
    r = s.get(Resource, rid)
    if r is None or not r.text_path:
        raise _404("text")
    return absolute(r.text_path).read_text(encoding="utf-8")


class BulkIn(BaseModel):
    ids: list[int]
    action: str
    value: Any = None


@app.post("/api/resources/bulk")
def resources_bulk(body: BulkIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..ingest.manage import bulk

    res = bulk(s, body.ids, body.action, body.value)
    if res["errors"] and not res["done"]:
        raise HTTPException(400, "; ".join(res["errors"]))
    return res


@app.get("/api/labels")
def labels(s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for (lbs,) in s.execute(select(Resource.labels).where(Resource.deleted.is_(False))):
        for lb in lbs or []:
            counts[lb] = counts.get(lb, 0) + 1
    return [{"label": k, "count": v} for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))]


@app.patch("/api/resources/{rid}")
def edit_resource(rid: int, body: dict[str, Any], s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..ingest.manage import update_resource

    r = s.get(Resource, rid)
    if r is None:
        raise _404("resource")
    try:
        changed = update_resource(s, r, body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"changed": changed}


@app.delete("/api/resources/{rid}")
def remove_resource(rid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..ingest.manage import delete_resource

    r = s.get(Resource, rid)
    if r is None:
        raise _404("resource")
    delete_resource(s, r)
    return {"deleted": True, "note": "Removed from the library; it will not be collected again. Restore is possible."}


@app.post("/api/resources/{rid}/{action}")
def resource_action(rid: int, action: str, s: Session = Depends(get_session)) -> dict[str, Any]:
    r = s.get(Resource, rid)
    if r is None:
        raise _404("resource")
    if action == "restore":
        from ..ingest.manage import restore_resource

        return {"status": restore_resource(s, r)}
    if action in ("archive", "unarchive"):
        from ..ingest.manage import archive_resource, unarchive_resource

        (archive_resource if action == "archive" else unarchive_resource)(s, r)
        return {"status": action + "d"}
    mapping = {"reprocess": ("process", "processing"), "reanalyze": ("analyze", "ai"), "acquire": ("acquire", "acquisition")}
    if action not in mapping:
        raise HTTPException(400, "unknown action")
    jt, group = mapping[action]
    if jt == "acquire":
        r.acquisition_status = "pending" if r.download_permitted and r.download_url else r.acquisition_status
    j = queue.enqueue(s, jt, {"resource_id": rid}, priority=40, group=group, dedupe_key=f"{jt}:{rid}")
    return {"job_id": j.id}


# ============================================================== sort & clean

class CurateIn(BaseModel):
    scope: str = "unclassified"  # unclassified | all
    ai: bool = True


class ArchiveLowIn(BaseModel):
    below: int = 20
    dry_run: bool = True
    only_unclassified: bool = False
    source: str | None = None


def _archive_low_stmt(body: ArchiveLowIn):
    from ..search.fts import pillar_clause, view_clause

    stmt = select(Resource).where(view_clause("active"), Resource.duplicate_of_id.is_(None),
                                  Resource.relevance.is_not(None), Resource.relevance < body.below)
    if body.only_unclassified:
        stmt = stmt.where(pillar_clause("none"))
    if body.source:
        stmt = stmt.where(Resource.source_key == body.source)
    return stmt


@app.get("/api/curation")
def curation_summary(below: int = 20, s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..search.fts import pillar_clause, view_clause

    def count(*conds) -> int:
        return s.execute(select(func.count()).select_from(Resource)
                         .where(Resource.duplicate_of_id.is_(None), *conds)).scalar() or 0

    active = view_clause("active")
    buckets = []
    for lo, hi in ((0, 19), (20, 39), (40, 59), (60, 79), (80, 100)):
        buckets.append({"from": lo, "to": hi, "count": count(active, Resource.relevance >= lo, Resource.relevance <= hi)})
    rows = s.execute(select(Resource.source_key, func.count(), func.avg(Resource.relevance),
                            func.sum(case((Resource.relevance >= 40, 1), else_=0)),
                            func.sum(case((Resource.archived.is_(True), 1), else_=0)))
                     .where(Resource.deleted.is_(False), Resource.duplicate_of_id.is_(None))
                     .group_by(Resource.source_key)).all()
    names = {src.key: (src.id, src.name, src.enabled) for src in s.execute(select(Source)).scalars()}
    sources = []
    for key, n, avg, good, arch in rows:
        sid, name, enabled = names.get(key or "", (None, key or "?", None))
        sources.append({"key": key, "source_id": sid, "name": name, "enabled": enabled, "items": n,
                        "avg_relevance": round(avg) if avg is not None else None,
                        "relevant_pct": round(100 * (good or 0) / n) if n else 0, "archived": int(arch or 0)})
    sources.sort(key=lambda x: (x["relevant_pct"], -x["items"]))
    settings = get_all(s)
    running = s.execute(select(Job).where(Job.job_type == "curate_all", Job.status.in_(queue.ACTIVE))).scalars().first()
    return {
        "active": count(active),
        "unclassified": count(active, pillar_clause("none")),
        "unscored": count(active, Resource.relevance.is_(None)),
        "low_relevance": count(active, Resource.relevance < below),
        "below": below,
        "archived": count(view_clause("archived")),
        "archived_auto": count(view_clause("archived"), Resource.extra["archived_by"].as_string() == "auto"),
        "deleted": count(view_clause("deleted")),
        "buckets": buckets,
        "sources": sources,
        "focus_terms": settings["focus_terms"], "exclude_terms": settings["exclude_terms"],
        "auto_archive_below": settings["auto_archive_below"],
        "ai_triage": settings["ai_triage"], "research_trusted_only": settings["research_trusted_only"],
        "ai_screened": count(view_clause("all"), func.json_extract(Resource.extra, "$.relevance_ai").is_not(None)),
        "ai_available": claude().available(),
        "job_running": {"id": running.id, "checkpoint": running.checkpoint} if running else None,
    }


@app.post("/api/curation/rescore")
def curation_rescore(body: CurateIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    if body.scope not in ("unclassified", "all"):
        raise HTTPException(400, "scope must be 'unclassified' or 'all'")
    j = queue.enqueue(s, "curate_all", {"scope": body.scope, "ai": body.ai}, priority=30, group="processing",
                      dedupe_key=f"curate_all:{body.scope}")
    return {"job_id": j.id, "message": "Sorting started in the background."}


@app.post("/api/curation/archive-low")
def curation_archive_low(body: ArchiveLowIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..ingest.manage import archive_resource

    items = [r for r in s.execute(_archive_low_stmt(body)).scalars()
             if (r.extra or {}).get("archived_by") != "user"]  # items the user chose to keep stay
    if body.dry_run:
        return {"would_archive": len(items),
                "examples": [{"id": r.id, "title": r.title, "relevance": r.relevance} for r in items[:8]]}
    for r in items:
        archive_resource(s, r, by="user", reason=f"archived in clean-up (relevance {r.relevance} < {body.below})")
    return {"archived": len(items)}


@app.post("/api/import")
async def import_file(file: UploadFile = File(...), resource_type: str = Form("book"), title: str = Form(""),
                      authors: str = Form(""), license: str = Form(""), s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..ingest.extract import SUPPORTED_EXT
    from ..ingest.pipeline import import_local_file

    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in SUPPORTED_EXT:
        raise HTTPException(400, f"Unsupported file type {suffix}. Supported: {', '.join(sorted(SUPPORTED_EXT))}")
    with tempfile.TemporaryDirectory() as tmp:
        p = Path(tmp) / Path(file.filename or f"upload{suffix}").name
        with open(p, "wb") as f:
            shutil.copyfileobj(file.file, f)
        r, created = import_local_file(s, p, title=title or None, resource_type=resource_type,
                                       authors=[a.strip() for a in authors.split(";") if a.strip()],
                                       license=license or None)
    if created:
        queue.enqueue(s, "process", {"resource_id": r.id}, priority=30, group="processing", dedupe_key=f"process:{r.id}")
    return {"resource_id": r.id, "created": created,
            "message": "Imported; processing queued." if created else "This file is already in the library."}


class ManualResource(BaseModel):
    title: str
    url: str | None = None
    resource_type: str = "article"
    authors: list[str] = []
    description: str | None = None
    language: str | None = None
    year: int | None = None
    publisher: str | None = None
    price: str | None = None
    currency: str | None = None
    purchase_url: str | None = None
    license: str | None = None
    fetch_page: bool = False


@app.post("/api/resources")
def add_resource(body: ManualResource, s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..ingest.licensing import decide
    from ..ingest.pipeline import register_with_content
    from ..ingest.registry import ResourceIn

    d = ResourceIn(title=body.title, url=body.url, resource_type=body.resource_type, authors=body.authors,
                   description=body.description, language=body.language, year=body.year, publisher=body.publisher,
                   price=body.price, currency=body.currency, purchase_url=body.purchase_url, license=body.license,
                   source_key="manual", collection_method="manual",
                   access=decide(body.license, paid=bool(body.price or body.purchase_url)),
                   extra={"fetch_page": body.fetch_page})
    r, created = register_with_content(s, d)
    if created:
        queue.enqueue(s, "process", {"resource_id": r.id}, priority=35, group="processing", dedupe_key=f"process:{r.id}")
    return {"resource_id": r.id, "created": created}


# ============================================================== knowledge

@app.get("/api/entities")
def entities(type: str | None = None, q: str = "", limit: int = 100, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    stmt = select(Entity, func.count(ResourceEntity.resource_id)).outerjoin(ResourceEntity, ResourceEntity.entity_id == Entity.id)
    if type:
        stmt = stmt.where(Entity.entity_type == type)
    if q:
        stmt = stmt.where(or_(Entity.name.ilike(f"%{q}%"), Entity.name_en.ilike(f"%{q}%"), Entity.name_ar.ilike(f"%{q}%")))
    rows = s.execute(stmt.group_by(Entity.id).order_by(func.count(ResourceEntity.resource_id).desc()).limit(limit)).all()
    return [{"id": e.id, "type": e.entity_type, "name": e.name, "name_ar": e.name_ar, "name_en": e.name_en,
             "origin": e.origin, "resources": n} for e, n in rows]


@app.get("/api/entities/{eid}")
def entity(eid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    e = s.get(Entity, eid)
    if e is None:
        raise _404("entity")
    rows = s.execute(select(Resource, ResourceEntity.role).join(ResourceEntity, ResourceEntity.resource_id == Resource.id)
                     .where(ResourceEntity.entity_id == eid).limit(200)).all()
    return {"id": e.id, "type": e.entity_type, "name": e.name, "name_ar": e.name_ar, "name_en": e.name_en,
            "description": e.description, "origin": e.origin, "extra": e.extra,
            "resources": [{**resource_brief(r), "role": role} for r, role in rows]}


@app.get("/api/glossary")
def glossary(s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [{"id": g.id, "concept": g.concept_key, "terms_en": g.terms_en, "terms_ar": g.terms_ar,
             "transliterations": g.transliterations, "pillar": g.pillar, "origin": g.origin}
            for g in s.execute(select(GlossaryTerm).order_by(GlossaryTerm.concept_key)).scalars()]


class GlossaryIn(BaseModel):
    concept: str
    terms_en: list[str] = []
    terms_ar: list[str] = []
    transliterations: list[str] = []
    pillar: str | None = None


@app.post("/api/glossary")
def add_glossary(body: GlossaryIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    g = s.execute(select(GlossaryTerm).where(GlossaryTerm.concept_key == body.concept)).scalars().first()
    if g is None:
        g = GlossaryTerm(concept_key=body.concept, origin="user")
        s.add(g)
    g.terms_en, g.terms_ar, g.transliterations, g.pillar = body.terms_en, body.terms_ar, body.transliterations, body.pillar
    s.flush()
    return {"id": g.id}


# ============================================================== research

class ObjectiveIn(BaseModel):
    title: str
    description: str | None = None
    pillars: list[str] = []
    priority: float = 0.6
    status: str = "active"


@app.get("/api/objectives")
def objectives(s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    out = []
    for o in s.execute(select(ResearchObjective).order_by(ResearchObjective.priority.desc())).scalars():
        counts = dict(s.execute(select(ResearchQuestion.status, func.count()).where(ResearchQuestion.objective_id == o.id)
                                .group_by(ResearchQuestion.status)).all())
        out.append({"id": o.id, "title": o.title, "description": o.description, "pillars": o.pillars, "priority": o.priority,
                    "status": o.status, "planned_at": o.planned_at.isoformat() if o.planned_at else None, "questions": counts})
    return out


@app.post("/api/objectives")
def create_objective(body: ObjectiveIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    o = ResearchObjective(**body.model_dump())
    s.add(o)
    s.flush()
    return {"id": o.id}


@app.patch("/api/objectives/{oid}")
def update_objective(oid: int, body: dict[str, Any], s: Session = Depends(get_session)) -> dict[str, Any]:
    o = s.get(ResearchObjective, oid)
    if o is None:
        raise _404("objective")
    for k in ("title", "description", "pillars", "priority", "status"):
        if k in body:
            setattr(o, k, body[k])
    if body.get("replan"):
        o.planned_at = None
    return {"ok": True}


@app.post("/api/objectives/{oid}/plan")
def plan_now(oid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    j = queue.enqueue(s, "plan_objective", {"objective_id": oid}, priority=25, group="research", dedupe_key=f"plan:{oid}")
    return {"job_id": j.id}


def _question(q: ResearchQuestion) -> dict[str, Any]:
    return {"id": q.id, "text": q.text, "text_alt": q.text_alt, "lang": q.lang, "kind": q.kind, "pillars": q.pillars,
            "priority": q.priority, "scores": q.scores, "status": q.status, "depth": q.depth, "rationale": q.rationale,
            "search_queries": q.search_queries, "next_steps": q.next_steps, "answer_summary": q.answer_summary,
            "created_by": q.created_by, "attempts": q.attempts, "parent_id": q.parent_id, "objective_id": q.objective_id,
            "related_count": len(q.related_resource_ids or []),
            "created_at": q.created_at.isoformat(), "investigated_at": q.investigated_at.isoformat() if q.investigated_at else None}


@app.get("/api/questions")
def questions(status: str | None = None, pillar: str | None = None, kind: str | None = None, q: str = "",
              limit: int = 100, offset: int = 0, s: Session = Depends(get_session)) -> dict[str, Any]:
    stmt = select(ResearchQuestion)
    if status:
        stmt = stmt.where(ResearchQuestion.status == status)
    if kind:
        stmt = stmt.where(ResearchQuestion.kind == kind)
    if q:
        stmt = stmt.where(or_(ResearchQuestion.text.ilike(f"%{q}%"), ResearchQuestion.text_alt.ilike(f"%{q}%")))
    rows = s.execute(stmt.order_by(ResearchQuestion.priority.desc(), ResearchQuestion.id.desc())).scalars().all()
    if pillar:
        rows = [r for r in rows if pillar in (r.pillars or [])]
    counts = dict(s.execute(select(ResearchQuestion.status, func.count()).group_by(ResearchQuestion.status)).all())
    return {"total": len(rows), "counts": counts, "questions": [_question(x) for x in rows[offset: offset + limit]]}


@app.get("/api/questions/{qid}")
def question(qid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    q = s.get(ResearchQuestion, qid)
    if q is None:
        raise _404("question")
    findings = s.execute(select(Finding).where(Finding.question_id == qid).order_by(Finding.id)).scalars().all()
    children = s.execute(select(ResearchQuestion).where(ResearchQuestion.parent_id == qid)).scalars().all()
    related = [r for r in (s.get(Resource, i) for i in (q.related_resource_ids or [])[:50]) if r is not None]
    searches = s.execute(select(SearchLog).where(SearchLog.question_id == qid).order_by(SearchLog.executed_at.desc()).limit(50)).scalars().all()
    parent = s.get(ResearchQuestion, q.parent_id) if q.parent_id else None
    return {**_question(q),
            "parent": _question(parent) if parent else None,
            "findings": [{"id": f.id, "statement": f.statement, "type": f.finding_type, "confidence": f.confidence,
                          "qa_status": f.qa_status, "qa_notes": f.qa_notes, "evidence": f.evidence,
                          "generated_by": f.generated_by, "created_at": f.created_at.isoformat()} for f in findings],
            "children": [_question(c) for c in children],
            "related_resources": [resource_brief(r) for r in related],
            "searches": [{"adapter": x.adapter, "query": x.query, "results": x.results, "new": x.new_resources,
                          "status": x.status, "error": x.error, "at": x.executed_at.isoformat()} for x in searches]}


class QuestionIn(BaseModel):
    text: str
    text_alt: str | None = None
    pillars: list[str] = []
    objective_id: int | None = None
    investigate_now: bool = True


@app.post("/api/questions")
def add_question(body: QuestionIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..agents.questions import Candidate, admit
    from ..text.lang import detect_language

    lang = "ar" if detect_language(body.text) == "ar" else "en"
    added = admit(s, [Candidate(text=body.text, text_alt=body.text_alt, lang=lang, kind="planner", pillars=body.pillars,
                                importance=0.9, novelty=0.8, feasibility=0.8, rationale="Added by the user.",
                                created_by="user")], objective_id=body.objective_id, limit=1)
    if not added:
        raise HTTPException(409, "A very similar question already exists (or the question queue is full).")
    if body.investigate_now:
        queue.enqueue(s, "investigate_question", {"question_id": added[0].id}, priority=20, group="research",
                      dedupe_key=f"investigate:{added[0].id}")
    return {"id": added[0].id}


@app.patch("/api/questions/{qid}")
def update_question(qid: int, body: dict[str, Any], s: Session = Depends(get_session)) -> dict[str, Any]:
    q = s.get(ResearchQuestion, qid)
    if q is None:
        raise _404("question")
    allowed = {"open", "answered", "unresolved", "duplicate", "not_relevant", "deferred"}
    if "status" in body:
        if body["status"] not in allowed:
            raise HTTPException(400, f"status must be one of {sorted(allowed)}")
        q.status = body["status"]
    if "priority" in body:
        q.priority = float(body["priority"])
    return _question(q)


@app.post("/api/questions/{qid}/investigate")
def investigate_now(qid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    q = s.get(ResearchQuestion, qid)
    if q is None:
        raise _404("question")
    q.status = "open"
    j = queue.enqueue(s, "investigate_question", {"question_id": qid}, priority=20, group="research",
                      dedupe_key=f"investigate:{qid}")
    return {"job_id": j.id}


@app.post("/api/questions/{qid}/synthesize")
def synthesize_now(qid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    j = queue.enqueue(s, "synthesize_question", {"question_id": qid}, priority=20, group="research",
                      dedupe_key=f"synth:{qid}")
    return {"job_id": j.id}


@app.get("/api/findings")
def findings(limit: int = 100, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    rows = s.execute(select(Finding).order_by(Finding.id.desc()).limit(limit)).scalars().all()
    return [{"id": f.id, "question_id": f.question_id, "statement": f.statement, "type": f.finding_type,
             "confidence": f.confidence, "qa_status": f.qa_status, "evidence_count": len(f.evidence or []),
             "verified_evidence": sum(1 for e in (f.evidence or []) if e.get("quote_verified")),
             "created_at": f.created_at.isoformat()} for f in rows]


class AskIn(BaseModel):
    question: str
    lang: str = "en"
    pillar: str | None = None


@app.post("/api/assistant")
def ask(body: AskIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..agents.assistant import answer

    try:
        return answer(s, body.question, body.lang, body.pillar)
    except Exception as e:  # noqa: BLE001 - surface AI errors to the user plainly
        raise HTTPException(502, f"Assistant failed: {type(e).__name__}: {e}") from e


# ============================================================== sources & jobs

@app.get("/api/adapters")
def adapters() -> list[dict[str, Any]]:
    return [adapter_status(a) for a in ADAPTERS.values()]


def _source(src: Source, s: Session) -> dict[str, Any]:
    a = ADAPTERS.get(src.adapter)
    active = s.execute(select(func.count()).select_from(Job).where(Job.group == src.key, Job.status.in_(queue.ACTIVE))).scalar()
    return {"id": src.id, "key": src.key, "adapter": src.adapter, "name": src.name, "enabled": src.enabled,
            "role": (src.config or {}).get("role", "monitor"),
            "config": {k: v for k, v in (src.config or {}).items() if k != "role"},
            "schedule_minutes": src.schedule_minutes, "rate_limit_per_min": src.rate_limit_per_min,
            "last_run_at": src.last_run_at.isoformat() if src.last_run_at else None,
            "last_success_at": src.last_success_at.isoformat() if src.last_success_at else None,
            "next_run_at": src.next_run_at.isoformat() if src.next_run_at else None,
            "health": src.health, "last_error": src.last_error, "items_collected": src.items_collected,
            "last_result": src.last_result, "active_jobs": active,
            "paused": src.key in (get_all(s).get("paused_collectors") or []),
            "adapter_info": adapter_status(a) if a else None}


@app.get("/api/sources")
def sources(s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    return [_source(x, s) for x in s.execute(select(Source).order_by(Source.adapter, Source.name)).scalars()]


class SourceIn(BaseModel):
    adapter: str
    name: str
    key: str | None = None
    config: dict[str, Any] = {}
    schedule_minutes: int | None = None
    enabled: bool = True


@app.post("/api/sources")
def create_source(body: SourceIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    import re

    a = ADAPTERS.get(body.adapter)
    if a is None or not a.supports("monitor"):
        raise HTTPException(400, "This adapter cannot be registered as a monitored source.")
    key = body.key or re.sub(r"[^a-z0-9]+", "-", f"{body.adapter}-{body.name}".lower()).strip("-")[:100]
    if s.execute(select(Source).where(Source.key == key)).first():
        raise HTTPException(409, f"Source key '{key}' already exists")
    cfg = {**a.info.default_config, **body.config, "role": "monitor"}
    problems = a.config_problems(cfg)
    if problems:
        raise HTTPException(400, "Settings incomplete: " + " | ".join(problems))
    src = Source(key=key, adapter=body.adapter, name=body.name, enabled=body.enabled, config=cfg,
                 schedule_minutes=body.schedule_minutes or a.info.default_schedule_minutes,
                 health="ready" if a.is_configured() else "needs_credentials")
    s.add(src)
    s.flush()
    return _source(src, s)


@app.patch("/api/sources/{sid}")
def update_source(sid: int, body: dict[str, Any], s: Session = Depends(get_session)) -> dict[str, Any]:
    src = s.get(Source, sid)
    if src is None:
        raise _404("source")
    for k in ("name", "enabled", "schedule_minutes", "rate_limit_per_min"):
        if k in body:
            setattr(src, k, body[k])
    if "config" in body:
        new_cfg = {**(src.config or {}), **body["config"], "role": (src.config or {}).get("role", "monitor")}
        a = ADAPTERS.get(src.adapter)
        if a is not None and new_cfg.get("role") == "monitor":
            problems = a.config_problems(new_cfg)
            if problems:
                raise HTTPException(400, "Settings incomplete: " + " | ".join(problems))
        src.config = new_cfg
    if "paused" in body:
        paused = set(get_all(s).get("paused_collectors") or [])
        (paused.add if body["paused"] else paused.discard)(src.key)
        set_setting(s, "paused_collectors", sorted(paused))
    return _source(src, s)


@app.delete("/api/sources/{sid}")
def delete_source(sid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    src = s.get(Source, sid)
    if src is None:
        raise _404("source")
    if (src.config or {}).get("role") == "search":
        raise HTTPException(400, "Built-in search sources can be disabled but not deleted.")
    src.enabled = False
    src.health = "deleted"
    src.key = f"{src.key}--deleted-{src.id}"
    return {"ok": True, "note": "Source disabled and archived; collected resources are kept."}


@app.post("/api/sources/{sid}/run")
def run_source(sid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    src = s.get(Source, sid)
    if src is None:
        raise _404("source")
    if (src.config or {}).get("role") == "search":
        raise HTTPException(400, "Search sources run when research questions are investigated.")
    j = queue.enqueue(s, "collect_source", {"source_id": src.id}, priority=20, group=src.key, dedupe_key=f"collect:{src.id}")
    return {"job_id": j.id}


@app.get("/api/jobs")
def jobs(status: str | None = None, type: str | None = None, limit: int = 100, s: Session = Depends(get_session)) -> dict[str, Any]:
    stmt = select(Job)
    if status:
        stmt = stmt.where(Job.status == status)
    if type:
        stmt = stmt.where(Job.job_type == type)
    rows = s.execute(stmt.order_by(Job.id.desc()).limit(limit)).scalars().all()
    counts = dict(s.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    by_type = [{"type": t, "status": st, "n": n} for t, st, n in
               s.execute(select(Job.job_type, Job.status, func.count()).group_by(Job.job_type, Job.status)).all()]
    return {"counts": counts, "by_type": by_type, "jobs": [
        {"id": j.id, "type": j.job_type, "status": j.status, "group": j.group, "priority": j.priority,
         "attempts": j.attempts, "max_attempts": j.max_attempts, "payload": j.payload, "result": j.result,
         "error": j.error, "run_after": j.run_after.isoformat() if j.run_after else None,
         "created_at": j.created_at.isoformat(), "started_at": j.started_at.isoformat() if j.started_at else None,
         "finished_at": j.finished_at.isoformat() if j.finished_at else None} for j in rows]}


@app.post("/api/jobs/{jid}/{action}")
def job_action(jid: int, action: str, s: Session = Depends(get_session)) -> dict[str, Any]:
    if action == "retry":
        ok = queue.retry(s, jid)
    elif action == "cancel":
        ok = queue.cancel(s, jid)
    else:
        raise HTTPException(400, "unknown action")
    if not ok:
        raise HTTPException(409, f"Cannot {action} this job in its current state")
    return {"ok": True}


@app.post("/api/jobs/retry-failed")
def retry_failed(s: Session = Depends(get_session)) -> dict[str, Any]:
    ids = [j.id for j in s.execute(select(Job).where(Job.status == "failed")).scalars()]
    for i in ids:
        queue.retry(s, i)
    return {"retried": len(ids)}


@app.get("/api/activity")
def activity(limit: int = 100, agent: str | None = None, s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    stmt = select(AgentRun)
    if agent:
        stmt = stmt.where(AgentRun.agent == agent)
    rows = s.execute(stmt.order_by(AgentRun.id.desc()).limit(limit)).scalars().all()
    return [{"id": a.id, "agent": a.agent, "action": a.action, "status": a.status, "detail": a.detail,
             "job_id": a.job_id, "question_id": a.question_id, "resource_id": a.resource_id,
             "tokens": a.ai_input_tokens + a.ai_output_tokens, "at": a.created_at.isoformat()} for a in rows]


@app.post("/api/automation/{action}")
def automation(action: str, s: Session = Depends(get_session)) -> dict[str, Any]:
    if action == "pause":
        set_setting(s, "paused", True)
    elif action == "resume":
        set_setting(s, "paused", False)
    elif action == "enable":
        set_setting(s, "automation_enabled", True)
    elif action == "disable":
        set_setting(s, "automation_enabled", False)
    elif action == "cycle":
        j = queue.enqueue(s, "research_cycle", {}, priority=20, dedupe_key="research_cycle", group="research")
        return {"job_id": j.id}
    elif action == "maintenance":
        j = queue.enqueue(s, "maintenance", {}, priority=20, dedupe_key="maintenance")
        return {"job_id": j.id}
    else:
        raise HTTPException(400, "unknown action")
    return {"ok": True}


# ============================================================== settings, outputs, backup

@app.get("/api/settings")
def get_settings(s: Session = Depends(get_session)) -> dict[str, Any]:
    vals = get_all(s)
    def kind(v: Any) -> str:
        return ("boolean" if isinstance(v, bool) else "integer" if isinstance(v, int) else
                "decimal" if isinstance(v, float) else "list" if isinstance(v, list) else
                "object" if isinstance(v, dict) else "string")

    return {"values": {k: vals[k] for k in DEFAULTS}, "defaults": DEFAULTS,
            "types": {k: kind(v) for k, v in DEFAULTS.items()},
            "model": get_config().ai_model, "data_dir": str(get_config().data_dir)}


# ============================================================== keys & AI (.env)

def _local_only(request: Request) -> None:
    """Keys can only be read/changed from the dashboard on this computer (not from other web pages)."""
    host = (request.headers.get("host") or "").split(":")[0]
    origin = request.headers.get("origin") or ""
    if host not in ("127.0.0.1", "localhost", "testserver") or (
            origin and urlsplit(origin).hostname not in ("127.0.0.1", "localhost")):
        raise HTTPException(403, "Keys can only be changed from the dashboard on this computer.")


@app.get("/api/env")
def env_get(request: Request) -> dict[str, Any]:
    from ..envfile import env_path, public_view

    _local_only(request)
    return {"fields": public_view(), "file": str(env_path()), "provider": claude().name,
            "ai_configured": claude().configured()}


@app.patch("/api/env")
def env_patch(body: dict[str, Any], request: Request) -> dict[str, Any]:
    from ..envfile import write_values

    _local_only(request)
    try:
        changed = write_values(body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    refresh_credential_health()
    return {"changed": changed, "provider": claude().name, "ai_configured": claude().configured()}


@app.post("/api/env/test-ai")
def env_test_ai(request: Request) -> dict[str, Any]:
    from ..aitest import run

    _local_only(request)
    lines: list[str] = []
    ok = run(out=lines.append)
    return {"ok": ok, "output": "\n".join(lines)}


@app.patch("/api/settings")
def patch_settings(body: dict[str, Any], s: Session = Depends(get_session)) -> dict[str, Any]:
    for k, v in body.items():
        if k not in DEFAULTS:
            raise HTTPException(400, f"Unknown setting {k}")
        d = DEFAULTS[k]
        if isinstance(d, bool) and not isinstance(v, bool):
            raise HTTPException(400, f"{k} must be true/false")
        if isinstance(d, (int, float)) and not isinstance(d, bool) and not isinstance(v, (int, float)):
            raise HTTPException(400, f"{k} must be a number")
        if isinstance(d, list) and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
            raise HTTPException(400, f"{k} must be a list of words")
        if isinstance(v, list):
            v = [x.strip() for x in v if x.strip()][:300]
        set_setting(s, k, v)
    return {"ok": True}


class OutputIn(BaseModel):
    kind: str
    title: str | None = None
    lang: str = "en"
    params: dict[str, Any] = {}


@app.get("/api/outputs")
def outputs(s: Session = Depends(get_session)) -> list[dict[str, Any]]:
    from ..agents.outputs import KINDS

    return [{"id": o.id, "kind": o.kind, "kind_label": KINDS.get(o.kind, (o.kind,))[0], "title": o.title, "lang": o.lang,
             "status": o.status, "error": o.error, "params": o.params, "generated_by": o.generated_by,
             "resources": len(o.resource_ids or []), "created_at": o.created_at.isoformat()}
            for o in s.execute(select(Output).order_by(Output.id.desc())).scalars()]


@app.get("/api/output-kinds")
def output_kinds() -> list[dict[str, Any]]:
    from ..agents.outputs import KINDS

    return [{"kind": k, "label": v[0], "needs_ai": v[1]} for k, v in KINDS.items()]


@app.post("/api/outputs")
def create_output(body: OutputIn, s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..agents.outputs import KINDS

    if body.kind not in KINDS:
        raise HTTPException(400, "unknown output kind")
    o = Output(kind=body.kind, title=body.title or KINDS[body.kind][0], lang=body.lang, params=body.params, status="queued")
    s.add(o)
    s.flush()
    j = queue.enqueue(s, "generate_output", {"output_id": o.id}, priority=20, dedupe_key=f"output:{o.id}")
    return {"id": o.id, "job_id": j.id}


@app.get("/api/outputs/{oid}")
def get_output(oid: int, s: Session = Depends(get_session)) -> dict[str, Any]:
    from ..agents.outputs import export_files

    o = s.get(Output, oid)
    if o is None:
        raise _404("output")
    return {"id": o.id, "kind": o.kind, "title": o.title, "status": o.status, "error": o.error, "content": o.content,
            "params": o.params, "resource_ids": o.resource_ids, "generated_by": o.generated_by,
            "formats": list(export_files(o).keys()) + (["html"] if o.content else [])}


@app.get("/api/outputs/{oid}/download")
def download_output(oid: int, fmt: str = "md", s: Session = Depends(get_session)):
    from ..agents.outputs import export_files

    o = s.get(Output, oid)
    if o is None:
        raise _404("output")
    if fmt == "html":
        import html

        body = html.escape(o.content or "")
        doc = (f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(o.title)}</title></head>"
               f"<body dir='{'rtl' if o.lang == 'ar' else 'ltr'}'><pre style='white-space:pre-wrap;font-family:serif'>{body}</pre></body></html>")
        return HTMLResponse(doc, headers={"Content-Disposition": f'attachment; filename="output-{oid}.html"'})
    files = export_files(o)
    if fmt not in files:
        raise _404("format")
    return FileResponse(files[fmt], filename=Path(files[fmt]).name)


@app.get("/api/update")
def update_status() -> dict[str, Any]:
    from ..updater import check, last_update_log

    return {**check(), "last_log": last_update_log()}


@app.post("/api/backup")
def make_backup() -> dict[str, Any]:
    from ..backup import backup

    p = backup()
    return {"path": str(p), "size_mb": round(p.stat().st_size / 1048576, 2)}


@app.get("/api/backups")
def list_backups() -> list[dict[str, Any]]:
    d = PROJECT_ROOT / "backups"
    if not d.exists():
        return []
    return [{"name": p.name, "size_mb": round(p.stat().st_size / 1048576, 2)} for p in sorted(d.glob("*.zip"), reverse=True)]


# ============================================================== frontend

DIST = PROJECT_ROOT / "frontend" / "dist"
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def spa(path: str):
    if path.startswith("api/"):
        raise _404("endpoint")
    index = DIST / "index.html"
    if not index.exists():
        return HTMLResponse("<h1>Tarbiyah Hub API is running</h1><p>The dashboard has not been built. "
                            "Run <code>scripts/build-frontend</code> or see docs/INSTALL.md. API docs: "
                            "<a href='/docs'>/docs</a></p>")
    f = DIST / path
    if path and f.is_file() and DIST in f.resolve().parents:
        return FileResponse(f)
    # never cache the page itself, so an update shows up without clearing the browser cache
    # (the script/style files it loads have the version in their names)
    return FileResponse(index, headers={"Cache-Control": "no-cache, no-store, must-revalidate"})
