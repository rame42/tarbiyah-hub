"""Background worker process: executes queued jobs and runs the scheduler.

Start with:  python -m tarbiyah worker
It runs independently of the web dashboard and of any Claude Code session.
"""
from __future__ import annotations

import logging
import signal
import threading
import time
import traceback
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from ..db import session_scope, utcnow
from ..models import AgentRun, Job, Setting, Source
from ..settings import flush_usage, get_setting, within_operating_hours
from . import queue

log = logging.getLogger("tarbiyah.worker")

Handler = Callable[["JobContext"], dict[str, Any] | None]
HANDLERS: dict[str, Handler] = {}
SYSTEM_JOB_TYPES = {"daily_report", "maintenance"}  # allowed outside operating hours


def handler(job_type: str) -> Callable[[Handler], Handler]:
    def deco(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn

    return deco


class Deferred(Exception):
    """Raise from a handler to re-queue the job later without consuming an attempt."""

    def __init__(self, reason: str, until: datetime | None = None):
        super().__init__(reason)
        self.until = until or utcnow() + timedelta(hours=1)


class PermanentFailure(Exception):
    """Raise when retrying cannot help (bad input, forbidden by policy...)."""


@dataclass
class JobContext:
    job_id: int
    job_type: str
    payload: dict[str, Any]
    checkpoint: dict[str, Any]
    session: Session
    worker_id: str
    lease_seconds: int
    deadline: float
    stop_event: threading.Event
    logs: list[str] = field(default_factory=list)

    def heartbeat(self, checkpoint: dict[str, Any] | None = None) -> None:
        """Extend the lease and persist a checkpoint (committed immediately)."""
        if checkpoint is not None:
            self.checkpoint = checkpoint
        self.session.commit()
        with session_scope() as s:
            queue.heartbeat(s, self.job_id, self.lease_seconds, checkpoint)

    def commit(self) -> None:
        """Commit work so far (keeps write transactions short; SQLite has a single writer)."""
        self.session.commit()

    def should_stop(self) -> bool:
        return self.stop_event.is_set() or time.monotonic() > self.deadline

    def audit(self, agent: str, action: str, detail: str = "", status: str = "ok", **kw: Any) -> None:
        self.session.add(AgentRun(agent=agent, action=action, job_id=self.job_id, status=status,
                                  detail=detail[:4000], **kw))


def run_job(job_id: int, worker_id: str, stop_event: threading.Event) -> str:
    """Execute one claimed job and record its outcome. Returns final status."""
    from ..http import BudgetExceeded, FetchError, RobotsDisallowed

    with session_scope() as s:
        job = s.get(Job, job_id)
        if job is None:
            return "missing"
        job_type, payload, checkpoint = job.job_type, dict(job.payload or {}), dict(job.checkpoint or {})
    fn = HANDLERS.get(job_type)
    lease = int(get_setting("lease_seconds"))
    timeout = int(get_setting("job_timeout_seconds"))
    if fn is None:
        with session_scope() as s:
            return queue.fail(s, job_id, f"No handler for job type '{job_type}'", retryable=False)
    error: str | None = None
    retryable = True
    deferred: Deferred | None = None
    result: dict[str, Any] | None = None
    try:
        with session_scope() as s:
            ctx = JobContext(job_id, job_type, payload, checkpoint, s, worker_id, lease,
                             time.monotonic() + timeout, stop_event)
            result = fn(ctx) or {}
    except Deferred as d:
        deferred = d
    except BudgetExceeded as e:
        deferred = Deferred(str(e), _tomorrow())
    except RobotsDisallowed as e:
        error, retryable = f"Blocked by robots.txt: {e}", False
    except PermanentFailure as e:
        error, retryable = str(e), False
    except FetchError as e:
        error, retryable = str(e), e.transient
    except OperationalError as e:
        if "locked" in str(e) or "busy" in str(e):  # transient SQLite write contention
            deferred = Deferred("database busy, retrying shortly", utcnow() + timedelta(seconds=30))
        else:
            error = f"{type(e).__name__}: {e}"
    except Exception as e:  # noqa: BLE001 - every failure must be recorded, never crash the worker
        error = f"{type(e).__name__}: {e}\n{traceback.format_exc(limit=6)}"
        retryable = getattr(e, "transient", True)
    flush_usage()
    with session_scope() as s:
        if deferred is not None:
            queue.defer(s, job_id, deferred.until, str(deferred))
            return "deferred"
        if error is not None:
            status = queue.fail(s, job_id, error, retryable=retryable)
            log.warning("job %s (%s) failed -> %s: %s", job_id, job_type, status, error.splitlines()[0])
            return status
        queue.complete(s, job_id, result)
        return "succeeded"


def _tomorrow() -> datetime:
    now = utcnow()
    return (now + timedelta(days=1)).replace(hour=0, minute=10, second=0, microsecond=0)


def blocked_groups(session: Session) -> list[str]:
    groups = [src.key for src in session.query(Source).filter(Source.enabled.is_(False)).all()]
    groups += list(get_setting("paused_collectors", session) or [])
    return groups


def write_status(worker_id: str, running: list[int], started_at: datetime, state: str) -> None:
    with session_scope() as s:
        row = s.get(Setting, "_worker_status")
        value = {"worker_id": worker_id, "state": state, "running_jobs": running,
                 "started_at": started_at.isoformat(), "heartbeat_at": utcnow().isoformat()}
        if row is None:
            s.add(Setting(key="_worker_status", value=value))
        else:
            row.value = value


class Worker:
    def __init__(self, concurrency: int | None = None, poll_seconds: float = 2.0, with_scheduler: bool = True):
        self.worker_id = queue.new_worker_id()
        self.concurrency = concurrency or int(get_setting("worker_concurrency"))
        self.poll = poll_seconds
        self.stop_event = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=self.concurrency, thread_name_prefix="job")
        self.running: dict[int, Future] = {}
        self.started_at = utcnow()
        self.with_scheduler = with_scheduler
        self.scheduler = None

    def install_signal_handlers(self) -> None:
        def _stop(signum, _frame):
            log.info("signal %s received: finishing running jobs, then stopping", signum)
            self.stop_event.set()

        signal.signal(signal.SIGINT, _stop)
        signal.signal(signal.SIGTERM, _stop)
        if hasattr(signal, "SIGBREAK"):  # Windows Ctrl+Break
            signal.signal(signal.SIGBREAK, _stop)

    def startup(self) -> None:
        from . import handlers  # noqa: F401  registers job handlers
        from ..runfiles import clear_stop_request, write_pid

        clear_stop_request("worker")
        write_pid("worker")

        with session_scope() as s:
            n = queue.recover_stale(s, self.worker_id)
        if n:
            log.info("recovered %d interrupted job(s) from a previous run", n)
        if self.with_scheduler:
            from .scheduler import start_scheduler

            self.scheduler = start_scheduler()

    def run_once(self) -> int:
        """Claim and start as many jobs as there are free slots. Returns number started."""
        for jid, fut in list(self.running.items()):
            if fut.done():
                self.running.pop(jid)
        started = 0
        with session_scope() as s:
            if get_setting("paused", s):
                return 0
            in_hours = within_operating_hours(s)
            groups = blocked_groups(s)
        allowed = None if in_hours else sorted(SYSTEM_JOB_TYPES)
        while len(self.running) < self.concurrency and not self.stop_event.is_set():
            with session_scope() as s:
                job = queue.claim(s, self.worker_id, int(get_setting("lease_seconds", s)), groups, allowed)
                jid = job.id if job else None
            if jid is None:
                break
            self.running[jid] = self.pool.submit(run_job, jid, self.worker_id, self.stop_event)
            started += 1
        return started

    def run_forever(self) -> None:
        self.startup()
        log.info("worker %s started (concurrency=%d)", self.worker_id, self.concurrency)
        last_status = 0.0
        try:
            from ..runfiles import stop_requested

            while not self.stop_event.is_set():
                if stop_requested("worker"):
                    log.info("stop requested (python -m tarbiyah stop): finishing running jobs")
                    self.stop_event.set()
                    break
                try:
                    flush_usage()
                    self.run_once()
                except Exception:  # noqa: BLE001 - e.g. database briefly locked; keep running
                    log.exception("worker loop error")
                if time.monotonic() - last_status > 15:
                    state = "paused" if get_setting("paused") else "running"
                    write_status(self.worker_id, list(self.running), self.started_at, state)
                    last_status = time.monotonic()
                self.stop_event.wait(self.poll)
        finally:
            self.shutdown()

    def drain(self, timeout: float = 60) -> None:
        """Run until the queue is empty (used by tests and `run-once` command)."""
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            started = self.run_once()
            for fut in list(self.running.values()):
                fut.result()
            self.running.clear()
            if started == 0:
                break

    def shutdown(self) -> None:
        self.stop_event.set()
        flush_usage()
        if self.scheduler is not None:
            self.scheduler.shutdown(wait=False)
        log.info("waiting for %d running job(s)...", len(self.running))
        self.pool.shutdown(wait=True, cancel_futures=True)
        try:
            write_status(self.worker_id, [], self.started_at, "stopped")
        except Exception:  # noqa: BLE001
            pass
        from ..runfiles import clear_pid

        clear_pid("worker")
        log.info("worker stopped cleanly")
