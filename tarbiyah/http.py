"""Polite HTTP client shared by all collectors.

- identifies itself with a User-Agent (+ contact e-mail when configured)
- obeys robots.txt (setting `respect_robots_txt`)
- per-host minimum interval between requests (rate limiting)
- retries transient failures (429/5xx/connection) with exponential backoff and Retry-After
- caps download size, counts every request against the daily HTTP budget
- never sends credentials unless an adapter passes them explicitly
"""
from __future__ import annotations

import threading
import time
import urllib.robotparser
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import requests

from .config import get_config
from .db import session_scope
from .settings import get_setting, record_usage, within_budget


class BudgetExceeded(RuntimeError):
    """Daily request/download budget exhausted; job should be retried tomorrow."""


class RobotsDisallowed(RuntimeError):
    pass


class FetchError(RuntimeError):
    def __init__(self, msg: str, status: int | None = None, transient: bool = False):
        super().__init__(msg)
        self.status = status
        self.transient = transient


@dataclass
class FetchResult:
    url: str
    final_url: str
    status: int
    headers: dict[str, str]
    content: bytes
    not_modified: bool = False

    @property
    def content_type(self) -> str:
        return self.headers.get("content-type", "").split(";")[0].strip().lower()

    @property
    def text(self) -> str:
        enc = None
        ct = self.headers.get("content-type", "")
        if "charset=" in ct:
            enc = ct.split("charset=")[-1].split(";")[0].strip()
        try:
            return self.content.decode(enc or "utf-8")
        except (UnicodeDecodeError, LookupError):
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        import json

        return json.loads(self.content.decode("utf-8"))


class PoliteHttp:
    def __init__(self) -> None:
        cfg = get_config()
        ua = cfg.user_agent + (f" mailto:{cfg.contact_email}" if cfg.contact_email else "")
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": ua, "Accept-Language": "ar,en;q=0.9"})
        self.user_agent = ua
        self._last: dict[str, float] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}
        self._glock = threading.Lock()
        self.default_interval = 1.5  # seconds between requests to the same host

    # -------------------------------------------------- robots
    def allowed(self, url: str) -> bool:
        if not get_setting("respect_robots_txt"):
            return True
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        with self._glock:
            if base not in self._robots:
                rp = urllib.robotparser.RobotFileParser()
                try:
                    r = self.session.get(base + "/robots.txt", timeout=15)
                    self._count()
                    if r.status_code in (401, 403):
                        rp.disallow_all = True
                    elif r.status_code >= 400:
                        rp.allow_all = True
                    else:
                        rp.parse(r.text.splitlines())
                except requests.RequestException:
                    rp = None  # unreachable robots.txt: treat as allowed, the fetch itself will fail if down
                self._robots[base] = rp
            rp = self._robots[base]
        return True if rp is None else rp.can_fetch(self.user_agent, url)

    def crawl_delay(self, url: str) -> float | None:
        parts = urlsplit(url)
        rp = self._robots.get(f"{parts.scheme}://{parts.netloc}")
        if rp is None:
            return None
        try:
            d = rp.crawl_delay(self.user_agent)
            return float(d) if d else None
        except Exception:
            return None

    # -------------------------------------------------- rate limit + budget
    def _wait(self, host: str, interval: float) -> None:
        with self._glock:
            lock = self._locks.setdefault(host, threading.Lock())
        with lock:
            last = self._last.get(host, 0.0)
            delay = interval - (time.monotonic() - last)
            if delay > 0:
                time.sleep(delay)
            self._last[host] = time.monotonic()

    def _count(self) -> None:
        with session_scope() as s:  # read-only: no write lock taken
            if not within_budget(s, "http_requests"):
                raise BudgetExceeded("Daily HTTP request budget reached")
        record_usage("http_requests")

    # -------------------------------------------------- fetch
    def fetch(self, url: str, *, params: dict | None = None, headers: dict | None = None,
              max_bytes: int | None = None, min_interval: float | None = None, retries: int = 3,
              check_robots: bool = True, etag: str | None = None, last_modified: str | None = None,
              timeout: float = 30, method: str = "GET", data: Any = None, auth: Any = None) -> FetchResult:
        if check_robots and not self.allowed(url):
            raise RobotsDisallowed(f"robots.txt disallows {url}")
        host = urlsplit(url).netloc
        interval = max(min_interval or self.default_interval, self.crawl_delay(url) or 0)
        hdrs = dict(headers or {})
        if etag:
            hdrs["If-None-Match"] = etag
        if last_modified:
            hdrs["If-Modified-Since"] = last_modified
        max_bytes = max_bytes or int(get_setting("max_file_mb")) * 1024 * 1024
        attempt = 0
        while True:
            attempt += 1
            self._wait(host, interval)
            self._count()
            try:
                resp = self.session.request(method, url, params=params, headers=hdrs, timeout=timeout,
                                            stream=True, allow_redirects=True, data=data, auth=auth)
            except requests.RequestException as e:
                if attempt <= retries:
                    time.sleep(min(60, 2 ** attempt))
                    continue
                raise FetchError(f"Network error: {e}", transient=True) from e
            if resp.status_code == 304:
                resp.close()
                return FetchResult(url, resp.url, 304, {k.lower(): v for k, v in resp.headers.items()}, b"", True)
            if resp.status_code == 429 or resp.status_code >= 500:
                ra = resp.headers.get("Retry-After")
                resp.close()
                if attempt <= retries:
                    wait = float(ra) if ra and ra.isdigit() else min(120, 3 * 2 ** attempt)
                    time.sleep(min(wait, 300))
                    continue
                raise FetchError(f"HTTP {resp.status_code} from {host}", resp.status_code, transient=True)
            if resp.status_code >= 400:
                resp.close()
                raise FetchError(f"HTTP {resp.status_code} for {url}", resp.status_code,
                                 transient=resp.status_code in (408,))
            declared = resp.headers.get("Content-Length")
            if declared and declared.isdigit() and int(declared) > max_bytes:
                resp.close()
                raise FetchError(f"File too large ({int(declared) // 1048576} MB > limit)", resp.status_code)
            buf = bytearray()
            for chunk in resp.iter_content(65536):
                buf.extend(chunk)
                if len(buf) > max_bytes:
                    resp.close()
                    raise FetchError("File exceeds size limit", resp.status_code)
            return FetchResult(url, resp.url, resp.status_code,
                               {k.lower(): v for k, v in resp.headers.items()}, bytes(buf))

    def get_json(self, url: str, **kw: Any) -> Any:
        h = {"Accept": "application/json", **(kw.pop("headers", None) or {})}
        return self.fetch(url, headers=h, **kw).json()


_client: PoliteHttp | None = None
_client_lock = threading.Lock()


def http() -> PoliteHttp:
    global _client
    with _client_lock:
        if _client is None:
            _client = PoliteHttp()
        return _client
