"""Adapter registry and default source rows.

Two kinds of Source rows exist:
- role "search":  one per searchable adapter (key = adapter name). Used by the research agents for
                  discovery queries; enable/disable and health are tracked here.
- role "monitor": a configured feed / channel / website / folder revisited on a schedule.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator

from sqlalchemy import select

from ..config import get_config
from ..db import session_scope
from ..ingest.registry import ResourceIn
from ..models import Source
from .academic import CoreAdapter, CrossrefAdapter, DoajAdapter, EricAdapter, OpenAlexAdapter
from .base import AdapterInfo, CollectContext, SourceAdapter
from .books import GoogleBooksAdapter, GutendexAdapter, InternetArchiveAdapter, OpenLibraryAdapter
from .feeds import RssAdapter
from .social import FacebookAdapter, InstagramAdapter, RedditAdapter, TelegramAdapter, TikTokAdapter, XAdapter
from .web import WebCrawlerAdapter
from .apify import ApifyAdapter
from .youtube import YouTubeAdapter, YouTubeCoursesAdapter


class LocalFolderAdapter(SourceAdapter):
    """Watches a folder (default data/inbox) and imports any supported file dropped into it."""

    info = AdapterInfo(
        name="local_folder", label="Local folder (inbox)", kind="books",
        description="Drop PDF, EPUB, DOCX, HTML or TXT files (e.g. books you bought) into the inbox folder; "
                    "they are imported automatically.",
        capabilities=("monitor",), resource_types=("book", "paper", "document"),
        access_notes="Files you add yourself are stored as 'user provided'.",
        default_schedule_minutes=15, default_enabled=True,
        config_fields={"path": "Folder to watch", "resource_type": "Type for imported files"},
        default_config={"path": "inbox", "resource_type": "book"},
    )

    def collect(self, ctx: CollectContext) -> Iterator[ResourceIn]:
        return iter(())  # handled specially in the collect handler (needs file import, not registration)

    def folder(self, cfg: dict[str, Any]) -> Path:
        p = Path(cfg.get("path") or "inbox")
        return p if p.is_absolute() else get_config().data_dir / p


ADAPTERS: dict[str, SourceAdapter] = {a.info.name: a for a in [
    OpenAlexAdapter(), CrossrefAdapter(), DoajAdapter(), EricAdapter(), CoreAdapter(),
    InternetArchiveAdapter(), OpenLibraryAdapter(), GutendexAdapter(), GoogleBooksAdapter(),
    WebCrawlerAdapter(), RssAdapter(), YouTubeAdapter(), YouTubeCoursesAdapter(), TelegramAdapter(), RedditAdapter(),
    FacebookAdapter(), InstagramAdapter(), XAdapter(), TikTokAdapter(), LocalFolderAdapter(), ApifyAdapter(),
]}


def get_adapter(name: str) -> SourceAdapter:
    try:
        return ADAPTERS[name]
    except KeyError:
        raise KeyError(f"Unknown adapter '{name}'") from None


def adapter_status(a: SourceAdapter) -> dict[str, Any]:
    i = a.info
    missing = a.missing_credentials()
    cfg = get_config()
    optional_missing = [c for c in i.optional_credentials if not getattr(cfg, c.lower(), "")]
    return {
        "name": i.name, "label": i.label, "kind": i.kind, "description": i.description,
        "capabilities": list(i.capabilities), "resource_types": list(i.resource_types),
        "credentials": list(i.credentials), "missing_credentials": missing,
        "optional_credentials": list(i.optional_credentials), "optional_missing": optional_missing,
        "paid": i.paid, "access_notes": i.access_notes, "configured": not missing,
        "config_fields": i.config_fields, "default_config": i.default_config,
        "default_schedule_minutes": i.default_schedule_minutes,
    }


def searchable_adapters() -> list[str]:
    return [n for n, a in ADAPTERS.items() if a.supports("search")]


def seed_sources() -> None:
    with session_scope() as s:
        have = {src.key for src in s.execute(select(Source)).scalars()}
        for name, a in ADAPTERS.items():
            if a.supports("search") and a.info.seed_search_source and name not in have:
                s.add(Source(key=name, adapter=name, name=a.info.label,
                             enabled=a.info.default_enabled and a.is_configured(),
                             config={"role": "search"}, schedule_minutes=a.info.default_schedule_minutes,
                             health="ready" if a.is_configured() else "needs_credentials"))
        if "inbox" not in have:
            la = ADAPTERS["local_folder"]
            s.add(Source(key="inbox", adapter="local_folder", name="Inbox folder", enabled=True,
                         config={"role": "monitor", **la.info.default_config}, schedule_minutes=15, health="ready"))
            (get_config().data_dir / "inbox").mkdir(parents=True, exist_ok=True)


def refresh_credential_health() -> None:
    """Re-evaluate credential status (e.g. after the user edits .env and restarts)."""
    with session_scope() as s:
        for src in s.execute(select(Source)).scalars():
            a = ADAPTERS.get(src.adapter)
            if a is None:
                continue
            if a.missing_credentials():
                src.health = "needs_credentials"
            elif src.health == "needs_credentials":
                src.health = "ready"
