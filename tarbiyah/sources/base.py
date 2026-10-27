"""Source adapter interface.

An adapter knows how to talk to one kind of source (an API, a feed format, a website
family). A `Source` row is a configured instance of an adapter (e.g. one RSS feed,
one YouTube channel list, one website to crawl), with its own schedule, rate limit,
enable switch and health status. One failing adapter never stops the others: every
call is isolated in its own job.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from ..config import get_config
from ..ingest.registry import ResourceIn


class NotConfigured(RuntimeError):
    """Adapter needs credentials or configuration the user has not provided."""


@dataclass
class AdapterInfo:
    name: str
    label: str
    kind: str  # academic | books | web | feed | video | social | catalog
    description: str
    capabilities: tuple[str, ...]  # search | monitor | crawl
    resource_types: tuple[str, ...]
    credentials: tuple[str, ...] = ()  # env var names required
    optional_credentials: tuple[str, ...] = ()
    paid: bool = False
    access_notes: str = ""
    languages: tuple[str, ...] = ("en", "ar")
    default_schedule_minutes: int = 1440
    min_interval_seconds: float = 1.5
    config_fields: dict[str, str] = field(default_factory=dict)  # name -> help text
    default_config: dict[str, Any] = field(default_factory=dict)
    default_enabled: bool = False


@dataclass
class CollectContext:
    """What an adapter may use while collecting: checkpointing and stop signals."""

    source_config: dict[str, Any]
    checkpoint: dict[str, Any]
    save_checkpoint: Callable[[dict[str, Any]], None] = lambda cp: None
    should_stop: Callable[[], bool] = lambda: False
    log: Callable[[str], None] = lambda msg: None
    source_id: int | None = None
    source_key: str | None = None
    session: Any = None  # SQLAlchemy session (crawler needs its frontier table)
    state: dict[str, Any] = field(default_factory=dict)  # persisted across runs (cursors, last-seen ids)
    commit: Callable[[], None] = lambda: None  # end the current write transaction


class SourceAdapter:
    info: AdapterInfo

    def missing_credentials(self) -> list[str]:
        cfg = get_config()
        missing = []
        for env in self.info.credentials:
            attr = env.lower()
            if not getattr(cfg, attr, ""):
                missing.append(env)
        return missing

    def is_configured(self) -> bool:
        return not self.missing_credentials()

    def require(self) -> None:
        missing = self.missing_credentials()
        if missing:
            raise NotConfigured(f"{self.info.label} needs: {', '.join(missing)} (set in .env). "
                                f"{self.info.access_notes}")

    # discovery by query (used by the research agents)
    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        raise NotImplementedError

    # monitoring of a configured source (feeds, channels, sites)
    def collect(self, ctx: CollectContext) -> Iterator[ResourceIn]:
        raise NotImplementedError
        yield  # pragma: no cover

    def supports(self, capability: str) -> bool:
        return capability in self.info.capabilities


def first(v: Any) -> Any:
    if isinstance(v, list):
        return v[0] if v else None
    return v


def as_year(v: Any) -> int | None:
    if v is None:
        return None
    s = str(v).strip()
    if len(s) >= 4 and s[:4].isdigit():
        y = int(s[:4])
        if 500 <= y <= 2100:
            return y
    return None
