"""Periodic triggers (APScheduler) running inside the worker process.

The scheduler only *enqueues* work; all state lives in the database, so nothing is
lost when the process stops. Schedules are re-derived from the database on start.
"""
from __future__ import annotations

import logging
from datetime import date, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import select

from ..db import session_scope, utcnow
from ..models import DailyReport, Job, Source
from ..settings import get_setting
from . import queue

log = logging.getLogger("tarbiyah.scheduler")


def dispatch_due_sources() -> int:
    """Enqueue a collection run for every enabled source whose next run is due."""
    n = 0
    with session_scope() as s:
        if not get_setting("automation_enabled", s):
            return 0
        now = utcnow()
        for src in s.execute(select(Source).where(Source.enabled.is_(True))).scalars():
            if (src.config or {}).get("role") == "search":
                continue  # search adapters are driven by research questions, not by a timetable
            if src.next_run_at is None or src.next_run_at <= now:
                queue.enqueue(s, "collect_source", {"source_id": src.id}, priority=40,
                              dedupe_key=f"collect:{src.id}", group=src.key)
                src.next_run_at = now + timedelta(minutes=max(15, src.schedule_minutes or 1440))
                n += 1
    return n


def dispatch_research_cycle() -> bool:
    with session_scope() as s:
        if not get_setting("automation_enabled", s):
            return False
        minutes = int(get_setting("research_cycle_minutes", s))
        last = s.execute(select(Job).where(Job.job_type == "research_cycle")
                         .order_by(Job.created_at.desc()).limit(1)).scalars().first()
        if last and last.status in queue.ACTIVE:
            return False
        if last and last.created_at > utcnow() - timedelta(minutes=minutes):
            return False
        queue.enqueue(s, "research_cycle", {}, priority=30, dedupe_key="research_cycle", group="research")
        return True


def dispatch_daily_reports() -> None:
    today = date.today()
    with session_scope() as s:
        queue.enqueue(s, "daily_report", {"day": today.isoformat()}, priority=20,
                      dedupe_key=f"daily_report:{today}")
        y = today - timedelta(days=1)
        rep = s.get(DailyReport, y)
        if rep is None or not rep.finalized:
            queue.enqueue(s, "daily_report", {"day": y.isoformat(), "finalize": True}, priority=10,
                          dedupe_key=f"daily_report_final:{y}")


def dispatch_maintenance() -> None:
    with session_scope() as s:
        queue.enqueue(s, "maintenance", {}, priority=60, dedupe_key="maintenance")


def recover() -> None:
    with session_scope() as s:
        n = queue.recover_stale(s)
    if n:
        log.info("re-queued %d job(s) with expired leases", n)


def _safe(fn):
    def wrapper():
        try:
            fn()
        except Exception:  # noqa: BLE001 - a failed tick must not kill the scheduler
            log.exception("scheduled trigger %s failed", fn.__name__)
    wrapper.__name__ = fn.__name__
    return wrapper


def start_scheduler() -> BackgroundScheduler:
    sched = BackgroundScheduler(daemon=True, job_defaults={"coalesce": True, "max_instances": 1,
                                                           "misfire_grace_time": 300})
    sched.add_job(_safe(dispatch_due_sources), "interval", seconds=60, id="sources", next_run_time=utcnow_local())
    sched.add_job(_safe(dispatch_research_cycle), "interval", minutes=2, id="research")
    sched.add_job(_safe(dispatch_daily_reports), "interval", minutes=10, id="daily", next_run_time=utcnow_local())
    sched.add_job(_safe(dispatch_maintenance), "interval", minutes=20, id="maintenance", next_run_time=utcnow_local())
    sched.add_job(_safe(recover), "interval", minutes=5, id="recover")
    sched.start()
    return sched


def utcnow_local():
    from datetime import datetime

    return datetime.now() + timedelta(seconds=5)
