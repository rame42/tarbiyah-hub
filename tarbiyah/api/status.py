"""System status shared by the API and the CLI."""
from __future__ import annotations

import shutil
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.claude import claude
from ..config import get_config
from ..db import utcnow
from ..ingest.extract import tesseract_available, tesseract_languages
from ..models import Entity, Job, ResearchQuestion, Resource, Setting, Source
from ..settings import get_all, get_usage, within_operating_hours
from ..storage import used_bytes


def worker_status(session: Session) -> dict[str, Any]:
    row = session.get(Setting, "_worker_status")
    if row is None:
        return {"alive": False, "state": "never_started"}
    v = dict(row.value or {})
    try:
        hb = datetime.fromisoformat(v.get("heartbeat_at"))
        v["alive"] = v.get("state") != "stopped" and (utcnow() - hb) < timedelta(seconds=90)
    except (TypeError, ValueError):
        v["alive"] = False
    return v


def system_status(session: Session) -> dict[str, Any]:
    cfg = get_config()
    settings = get_all(session)
    jobs = dict(session.execute(select(Job.status, func.count()).group_by(Job.status)).all())
    disk = shutil.disk_usage(cfg.data_dir)
    sources = session.execute(select(Source)).scalars().all()
    tess = tesseract_available(cfg.tesseract_cmd)
    return {
        "worker": worker_status(session),
        "automation": {"enabled": settings["automation_enabled"], "paused": settings["paused"],
                       "within_operating_hours": within_operating_hours(session),
                       "operating_hours": settings["operating_hours"],
                       "paused_collectors": settings["paused_collectors"]},
        "ai": claude().status(),
        "ocr": {"tesseract": tess, "languages": tesseract_languages(cfg.tesseract_cmd) if tess else [],
                "provider_setting": settings["ocr_provider"],
                "claude_ocr_available": claude().available()},
        "jobs": jobs,
        "counts": {
            "resources": session.execute(select(func.count()).select_from(Resource).where(Resource.duplicate_of_id.is_(None))).scalar(),
            "files": session.execute(select(func.count()).select_from(Resource).where(Resource.local_path.is_not(None))).scalar(),
            "entities": session.execute(select(func.count()).select_from(Entity)).scalar(),
            "open_questions": session.execute(select(func.count()).select_from(ResearchQuestion).where(ResearchQuestion.status == "open")).scalar(),
            "sources_enabled": sum(1 for s in sources if s.enabled),
            "sources_error": sum(1 for s in sources if s.health == "error"),
        },
        "storage": {"used_gb": round(used_bytes(session) / 1024 ** 3, 3), "limit_gb": settings["storage_limit_gb"],
                    "disk_free_gb": round(disk.free / 1024 ** 3, 2), "data_dir": str(cfg.data_dir)},
        "usage_today": {k: round(get_usage(session, k), 4) for k in
                        ("http_requests", "downloads", "download_mb", "ai_calls", "ai_cost_usd", "apify_runs")},
        "limits": {k: settings[k] for k in ("daily_http_request_limit", "daily_download_limit",
                                             "daily_download_mb_limit", "daily_ai_call_limit", "daily_ai_budget_usd",
                                             "worker_concurrency", "max_questions_per_cycle", "research_cycle_minutes")},
        "credentials": {k: bool(getattr(cfg, k)) for k in
                        ("anthropic_api_key", "voyage_api_key", "youtube_api_key", "core_api_key", "reddit_client_id",
                         "facebook_access_token", "instagram_access_token", "x_bearer_token", "tiktok_client_key",
                         "apify_token")},
    }
