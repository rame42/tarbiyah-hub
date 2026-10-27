"""Durable queue semantics, budgets, crash recovery and the worker as an independent process."""
import os
import signal
import subprocess
import sys
import time
from datetime import timedelta

import pytest

from tarbiyah.db import session_scope, utcnow
from tarbiyah.jobs import queue
from tarbiyah.models import Job, Setting
from tarbiyah.settings import record_usage, set_setting, within_budget

from .conftest import ROOT, drain


def test_enqueue_dedupes_active_jobs(env):
    with session_scope() as s:
        a = queue.enqueue(s, "process", {"resource_id": 1}, dedupe_key="process:1")
        b = queue.enqueue(s, "process", {"resource_id": 1}, dedupe_key="process:1")
        assert a.id == b.id
        queue.complete(s, a.id)
        c = queue.enqueue(s, "process", {"resource_id": 1}, dedupe_key="process:1")
        assert c.id != a.id  # finished jobs do not block new work


def test_claim_priority_lease_and_blocked_groups(env):
    with session_scope() as s:
        low = queue.enqueue(s, "x", priority=90)
        high = queue.enqueue(s, "x", priority=10, group="paused-src")
        mid = queue.enqueue(s, "x", priority=50)
    with session_scope() as s:
        j = queue.claim(s, "host:1", 60, blocked_groups=["paused-src"])
        assert j.id == mid.id and j.status == "running" and j.attempts == 1 and j.lease_until > utcnow()
        j2 = queue.claim(s, "host:1", 60)
        assert j2.id == high.id
        j3 = queue.claim(s, "host:1", 60, allowed_types=["daily_report"])
        assert j3 is None  # outside operating hours only system jobs run
        assert queue.claim(s, "host:1", 60).id == low.id


def test_retry_backoff_then_permanent_failure(env):
    with session_scope() as s:
        j = queue.enqueue(s, "x", max_attempts=2)
        jid = j.id
    for expected in ("queued", "failed"):
        with session_scope() as s:
            s.get(Job, jid).run_after = utcnow() - timedelta(seconds=1)
        with session_scope() as s:
            assert queue.claim(s, "h:1", 60).id == jid
            assert queue.fail(s, jid, "boom") == expected
    with session_scope() as s:
        job = s.get(Job, jid)
        assert job.status == "failed" and job.error == "boom"  # stays visible
        assert queue.retry(s, jid) and job.status == "queued" and job.attempts == 0


def test_defer_does_not_consume_attempts(env):
    with session_scope() as s:
        jid = queue.enqueue(s, "x").id
    with session_scope() as s:
        queue.claim(s, "h:1", 60)
        queue.defer(s, jid, utcnow() + timedelta(hours=1), "budget")
        job = s.get(Job, jid)
        assert job.status == "queued" and job.attempts == 0 and "budget" in job.error


def test_recover_stale_after_crash(env):
    with session_scope() as s:
        a = queue.enqueue(s, "x")
        b = queue.enqueue(s, "x")
    with session_scope() as s:
        ja = queue.claim(s, "myhost:111", 60)
        jb = queue.claim(s, "otherhost:5", 60)
        ja.checkpoint = {"fetched": 40}
    with session_scope() as s:  # restart on 'myhost' with a new pid: own orphaned job is recovered at once
        assert queue.recover_stale(s, "myhost:222") == 1
        assert s.get(Job, a.id).status == "queued" and s.get(Job, a.id).checkpoint == {"fetched": 40}
        assert s.get(Job, b.id).status == "running"  # other machine's job: wait for its lease
        s.get(Job, b.id).lease_until = utcnow() - timedelta(seconds=1)
    with session_scope() as s:
        assert queue.recover_stale(s) == 1


def test_daily_budget(env):
    with session_scope() as s:
        set_setting(s, "daily_http_request_limit", 3)
    for _ in range(3):
        record_usage("http_requests")
    with session_scope() as s:
        assert not within_budget(s, "http_requests")


def test_budget_exhaustion_defers_job_until_tomorrow(env, site):
    from tarbiyah.models import Source

    with session_scope() as s:
        set_setting(s, "daily_http_request_limit", 0)
        src = Source(key="tg", adapter="telegram", name="t", enabled=True,
                     config={"role": "monitor", "channels": ["testchannel"], "base_url": site["base"] + "/tg"})
        s.add(src)
        s.flush()
        jid = queue.enqueue(s, "collect_source", {"source_id": src.id}).id
    drain(20)
    with session_scope() as s:
        job = s.get(Job, jid)
        assert job.status == "queued" and job.attempts == 0 and job.run_after > utcnow() + timedelta(hours=1)


def _spawn_worker(data_dir):
    env = {**os.environ, "TH_DATA_DIR": str(data_dir), "PYTHONUNBUFFERED": "1"}
    return subprocess.Popen([sys.executable, "-m", "tarbiyah", "worker"], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _wait(pred, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(0.5)
    return False


@pytest.mark.skipif(sys.platform == "win32", reason="uses POSIX signals")
def test_worker_runs_as_independent_process_and_survives_kill(env, site):
    """The worker runs on its own (no Claude Code, no web server). It is killed with SIGKILL in the
    middle of a crawl, restarted, and finishes the work without losing or duplicating it."""
    from tarbiyah.models import Resource, Source

    with session_scope() as s:
        set_setting(s, "worker_concurrency", 1)
        for src in s.query(Source):
            src.enabled = False
        src = Source(key="site-ar", adapter="web_crawler", name="ar", enabled=True, schedule_minutes=1440,
                     config={"role": "monitor", "start_urls": [site["base"] + "/ar/index.html"],
                             "allowed_domains": ["127.0.0.1"], "include_patterns": ["/ar/"],
                             "min_interval_seconds": 1.5, "use_sitemap": False})
        s.add(src)
    p = _spawn_worker(env)
    try:
        def crawling():
            with session_scope() as s:
                return s.query(Job).filter(Job.job_type == "collect_source", Job.status == "running").count() > 0
        assert _wait(crawling, 60), "scheduler did not start the crawl"
        time.sleep(2.5)
        p.send_signal(signal.SIGKILL)  # simulate power loss / crash
        p.wait(10)
        with session_scope() as s:
            assert s.query(Job).filter(Job.status == "running").count() >= 1  # orphaned
        p = _spawn_worker(env)

        def finished():
            with session_scope() as s:
                active = s.query(Job).filter(Job.status.in_(("queued", "running")), Job.run_after <= utcnow()).count()
                arts = s.query(Resource).filter(Resource.source_key == "site-ar", Resource.resource_type == "article").count()
                return active == 0 and arts == 3
        assert _wait(finished, 120), "work did not complete after restart"
        with session_scope() as s:
            urls = [r.canonical_url for r in s.query(Resource).filter(Resource.source_key == "site-ar")]
            assert len(urls) == len(set(urls)) == 4  # 3 articles + 1 linked PDF, no duplicates after the crash
            st = s.get(Setting, "_worker_status").value
            assert st["state"] == "running"
        p.send_signal(signal.SIGTERM)  # graceful stop
        out, _ = p.communicate(timeout=60)
        assert p.returncode == 0 and "worker stopped cleanly" in out
        assert "recovered 1 interrupted job" in out or "recovered" in out
    finally:
        if p.poll() is None:
            p.kill()
