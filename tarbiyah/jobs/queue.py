"""Durable job queue stored in the database.

Guarantees:
- jobs survive restarts (they are rows, not in-memory tasks)
- a job is claimed atomically by one worker and protected by a lease
- crashed/interrupted jobs are re-queued when their lease expires or the worker restarts
- identical active jobs are not duplicated (dedupe_key)
- failures retry with exponential backoff up to max_attempts, then stay visible as 'failed'
"""
from __future__ import annotations

import socket
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import or_, select, text, update
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Job

ACTIVE = ("queued", "running")


def enqueue(session: Session, job_type: str, payload: dict[str, Any] | None = None, *, priority: int = 50,
            dedupe_key: str | None = None, group: str | None = None, run_after: datetime | None = None,
            max_attempts: int = 4, parent_id: int | None = None) -> Job:
    if dedupe_key:
        existing = session.execute(
            select(Job).where(Job.dedupe_key == dedupe_key, Job.status.in_(ACTIVE))
        ).scalars().first()
        if existing:
            return existing
    job = Job(job_type=job_type, payload=payload or {}, priority=priority, dedupe_key=dedupe_key, group=group,
              run_after=run_after or utcnow(), max_attempts=max_attempts, parent_id=parent_id, status="queued")
    session.add(job)
    session.flush()
    return job


def claim(session: Session, worker_id: str, lease_seconds: int, blocked_groups: list[str] | None = None,
          allowed_types: list[str] | None = None) -> Job | None:
    """Atomically take the next due job. Uses UPDATE ... RETURNING on a single row."""
    now = utcnow()
    conds = ["status = 'queued'", "run_after <= :now"]
    params: dict[str, Any] = {"now": now, "lease": now + timedelta(seconds=lease_seconds), "wid": worker_id}
    if blocked_groups:
        names = []
        for i, g in enumerate(blocked_groups):
            params[f"g{i}"] = g
            names.append(f":g{i}")
        conds.append(f"(\"group\" IS NULL OR \"group\" NOT IN ({', '.join(names)}))")
    if allowed_types is not None:
        if not allowed_types:
            return None
        names = []
        for i, t in enumerate(allowed_types):
            params[f"t{i}"] = t
            names.append(f":t{i}")
        conds.append(f"job_type IN ({', '.join(names)})")
    sql = text(
        "UPDATE jobs SET status = 'running', lease_until = :lease, worker_id = :wid, "
        "started_at = :now, attempts = attempts + 1 "
        f"WHERE id = (SELECT id FROM jobs WHERE {' AND '.join(conds)} ORDER BY priority, id LIMIT 1) "
        "AND status = 'queued' RETURNING id"
    )
    row = session.execute(sql, params).first()
    if row is None:
        return None
    session.flush()
    job = session.get(Job, row[0])
    if job is not None:
        session.refresh(job)
    return job


def heartbeat(session: Session, job_id: int, lease_seconds: int, checkpoint: dict[str, Any] | None = None) -> None:
    values: dict[str, Any] = {"lease_until": utcnow() + timedelta(seconds=lease_seconds)}
    if checkpoint is not None:
        values["checkpoint"] = checkpoint
    session.execute(update(Job).where(Job.id == job_id, Job.status == "running").values(**values))


def complete(session: Session, job_id: int, result: dict[str, Any] | None = None) -> None:
    session.execute(update(Job).where(Job.id == job_id).values(
        status="succeeded", result=result or {}, finished_at=utcnow(), lease_until=None, error=None))


def backoff_seconds(attempts: int) -> int:
    return min(6 * 3600, 60 * (2 ** max(0, attempts - 1)))


def fail(session: Session, job_id: int, error: str, *, retryable: bool = True) -> str:
    job = session.get(Job, job_id)
    if job is None:
        return "missing"
    job.error = error[:4000]
    job.lease_until = None
    if retryable and job.attempts < job.max_attempts:
        job.status = "queued"
        job.run_after = utcnow() + timedelta(seconds=backoff_seconds(job.attempts))
    else:
        job.status = "failed"
        job.finished_at = utcnow()
    return job.status


def defer(session: Session, job_id: int, until: datetime, reason: str) -> None:
    """Re-queue without consuming an attempt (budget exhausted, outside operating hours...)."""
    job = session.get(Job, job_id)
    if job is None:
        return
    job.status = "queued"
    job.attempts = max(0, job.attempts - 1)
    job.run_after = until
    job.lease_until = None
    job.error = f"deferred: {reason}"


def retry(session: Session, job_id: int) -> bool:
    job = session.get(Job, job_id)
    if job is None or job.status in ACTIVE:
        return False
    job.status = "queued"
    job.attempts = 0
    job.run_after = utcnow()
    job.error = None
    job.finished_at = None
    return True


def cancel(session: Session, job_id: int) -> bool:
    job = session.get(Job, job_id)
    if job is None or job.status not in ("queued",):
        return False
    job.status = "cancelled"
    job.finished_at = utcnow()
    return True


def recover_stale(session: Session, worker_id: str | None = None) -> int:
    """Requeue jobs whose lease expired (crash, power loss, killed process).

    When `worker_id` is given (worker startup), jobs left 'running' by a previous
    process on this same machine are recovered immediately instead of waiting for
    their lease to expire.
    """
    now = utcnow()
    conds = [Job.lease_until < now]
    if worker_id:
        host = worker_id.split(":")[0]
        conds.append(Job.worker_id.like(f"{host}:%") & (Job.worker_id != worker_id))
    stale = session.execute(select(Job).where(Job.status == "running", or_(*conds))).scalars().all()
    for job in stale:
        job.lease_until = None
        if job.attempts >= job.max_attempts:
            job.status = "failed"
            job.error = (job.error or "") + " | interrupted (worker stopped) and out of attempts"
            job.finished_at = now
        else:
            job.status = "queued"
            job.run_after = now
            job.error = "recovered after interruption; resuming from checkpoint" if job.checkpoint else \
                "recovered after interruption"
    return len(stale)


def new_worker_id() -> str:
    import os

    return f"{socket.gethostname()}:{os.getpid()}"
