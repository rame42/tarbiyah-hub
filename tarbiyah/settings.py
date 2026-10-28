"""Operational settings stored in the database (editable from the dashboard),
plus daily usage counters used to enforce budgets."""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import session_scope
from .models import Setting, UsageCounter

DEFAULTS: dict[str, Any] = {
    # automation
    "automation_enabled": True,          # master switch for the scheduled research loop
    "paused": False,                     # global pause (worker keeps running, takes no new jobs)
    "paused_collectors": [],             # source keys whose jobs are held
    "operating_hours": {"start": "00:00", "end": "23:59"},  # local time window for collection/research
    "worker_concurrency": 3,
    "job_timeout_seconds": 900,
    "lease_seconds": 1200,
    # research loop bounds
    "research_cycle_minutes": 30,
    "max_questions_per_cycle": 2,
    "max_open_questions": 300,
    "max_new_questions_per_run": 8,
    "max_question_depth": 3,
    "search_repeat_days": 14,            # do not re-run an identical search within this many days
    "max_results_per_search": 15,
    # budgets (per day)
    "daily_http_request_limit": 3000,
    "daily_download_limit": 150,
    "daily_download_mb_limit": 2000,
    "daily_ai_call_limit": 200,
    "daily_ai_budget_usd": 2.0,
    # Apify (paid service; applies only when APIFY_TOKEN is set)
    "apify_daily_run_limit": 5,          # Actor runs per day (each run is billed by Apify)
    "apify_max_items_per_run": 50,       # results per run (caps cost of pay-per-result Actors)
    "apify_max_charge_usd_per_run": 0.5, # spending cap per run (pay-per-event Actors)
    "apify_run_timeout_seconds": 900,
    # storage
    "storage_limit_gb": 20.0,
    "max_file_mb": 150,
    "min_free_disk_gb": 2.0,
    "download_free_to_read": False,      # download OA files that carry no explicit licence
    # AI
    "ai_enabled": True,                  # still requires ANTHROPIC_API_KEY
    "ai_effort": "low",
    "ai_summary_language": "source",     # source | en | ar
    "ocr_provider": "auto",              # auto | tesseract | claude | none
    "ocr_languages": "ara+eng",
    # crawler
    "crawler_default_max_pages": 200,
    "crawler_default_max_depth": 3,
    "respect_robots_txt": True,
    # relevance and clean-up
    "focus_terms": [],                   # extra words/phrases that make an item MORE relevant (Arabic or English)
    "exclude_terms": [],                 # words/phrases in a title or description that make an item irrelevant
    "auto_archive_below": 0,             # new automatically collected items scoring below this are archived (0 = off)
    # ui
    "ui_language": "en",
}


def get_setting(key: str, session: Session | None = None) -> Any:
    if session is None:
        with session_scope() as s:
            return get_setting(key, s)
    row = session.get(Setting, key)
    if row is None:
        return DEFAULTS.get(key)
    return row.value


def get_all(session: Session) -> dict[str, Any]:
    out = dict(DEFAULTS)
    for row in session.execute(select(Setting)).scalars():
        out[row.key] = row.value
    return out


def set_setting(session: Session, key: str, value: Any) -> None:
    if key not in DEFAULTS:
        raise KeyError(f"Unknown setting: {key}")
    row = session.get(Setting, key)
    if row is None:
        session.add(Setting(key=key, value=value))
    else:
        row.value = value


def within_operating_hours(session: Session, now: datetime | None = None) -> bool:
    hours = get_setting("operating_hours", session) or {}
    now = now or datetime.now()
    try:
        sh, sm = (int(x) for x in str(hours.get("start", "00:00")).split(":"))
        eh, em = (int(x) for x in str(hours.get("end", "23:59")).split(":"))
    except ValueError:
        return True
    cur = now.hour * 60 + now.minute
    start, end = sh * 60 + sm, eh * 60 + em
    if start <= end:
        return start <= cur <= end
    return cur >= start or cur <= end  # window crosses midnight


# ------------------------------------------------------------------ usage counters
#
# Counters are incremented in memory and flushed to the database in short transactions
# (worker loop, end of each job, after API requests). This keeps budget accounting from
# competing with long-running jobs for SQLite's single write lock.

import threading as _threading

_pending: dict[tuple[date, str], float] = {}
_pending_lock = _threading.Lock()


def record_usage(key: str, amount: float = 1.0) -> None:
    with _pending_lock:
        k = (date.today(), key)
        _pending[k] = _pending.get(k, 0.0) + amount


def pending_usage(key: str, day: date | None = None) -> float:
    with _pending_lock:
        return _pending.get((day or date.today(), key), 0.0)


def flush_usage() -> bool:
    """Write pending counters. Returns False (and keeps them) if the database is busy."""
    from .db import session_scope

    with _pending_lock:
        items = dict(_pending)
    if not items:
        return True
    try:
        with session_scope() as s:
            for (day, key), amount in items.items():
                add_usage(s, key, amount, day)
    except Exception:  # noqa: BLE001 - busy database: try again on the next flush
        return False
    with _pending_lock:
        for k, amount in items.items():
            _pending[k] = _pending.get(k, 0.0) - amount
            if abs(_pending[k]) < 1e-12:
                del _pending[k]
    return True


def add_usage(session: Session, key: str, amount: float = 1.0, day: date | None = None) -> float:
    day = day or date.today()
    row = session.get(UsageCounter, (day, key))
    if row is None:
        row = UsageCounter(day=day, key=key, value=0.0)
        session.add(row)
    row.value = (row.value or 0.0) + amount
    return row.value


def get_usage(session: Session, key: str, day: date | None = None) -> float:
    row = session.get(UsageCounter, (day or date.today(), key))
    return (float(row.value) if row else 0.0) + pending_usage(key, day)


LIMITS = {
    "http_requests": "daily_http_request_limit",
    "downloads": "daily_download_limit",
    "download_mb": "daily_download_mb_limit",
    "ai_calls": "daily_ai_call_limit",
    "ai_cost_usd": "daily_ai_budget_usd",
    "apify_runs": "apify_daily_run_limit",
}


def budget_remaining(session: Session, key: str) -> float:
    limit = float(get_setting(LIMITS[key], session) or 0)
    return limit - get_usage(session, key)


def within_budget(session: Session, key: str, amount: float = 1.0) -> bool:
    return budget_remaining(session, key) >= amount
