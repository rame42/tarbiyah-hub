"""Helpers shared by agents: passage formatting, quote verification, audit logging."""
from __future__ import annotations

import re
from typing import Any, Iterable

from sqlalchemy.orm import Session

from ..models import AgentRun, Chunk, Resource
from ..text.arabic import normalize_for_search


def passage_block(c: Chunk, r: Resource | None = None, max_chars: int = 3000) -> str:
    attrs = [f'id="{c.id}"']
    if r is not None:
        attrs.append(f'source="{(r.title or "")[:120].replace(chr(34), chr(39))}"')
        if r.authors_text:
            attrs.append(f'authors="{r.authors_text[:80].replace(chr(34), chr(39))}"')
        if r.year:
            attrs.append(f'year="{r.year}"')
        attrs.append(f'type="{r.resource_type}"')
    if c.page_start:
        attrs.append(f'page="{c.page_start}"')
    if c.timestamp_start is not None:
        attrs.append(f'time="{int(c.timestamp_start)}s"')
    if c.lang:
        attrs.append(f'lang="{c.lang}"')
    return f"<passage {' '.join(attrs)}>\n{c.text[:max_chars]}\n</passage>"


def sample_chunks(chunks: list[Chunk], budget_chars: int = 60000) -> list[Chunk]:
    """Evenly spread passages across a long document within a character budget."""
    if sum(len(c.text) for c in chunks) <= budget_chars:
        return chunks
    avg = max(1, sum(len(c.text) for c in chunks) // len(chunks))
    n = max(3, budget_chars // avg)
    step = len(chunks) / n
    picked = [chunks[int(i * step)] for i in range(n)]
    return list(dict.fromkeys(picked))


_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    s = normalize_for_search(s)
    s = re.sub(r"[\"'«»“”‘’`.,;:!?؟،؛()\[\]{}…\-–—]", " ", s)
    return _WS.sub(" ", s).strip()


def verify_quote(quote: str, passage_text: str) -> bool:
    """True when the quote occurs in the passage (ignoring case, diacritics, punctuation, spacing).
    Quotes with '...' are verified piece by piece."""
    if not quote or not quote.strip():
        return False
    hay = _norm(passage_text)
    pieces = [p for p in re.split(r"\.\.\.|…", quote) if _norm(p)]
    return bool(pieces) and all(_norm(p) in hay for p in pieces if len(_norm(p)) >= 3)


def audit(session: Session, agent: str, action: str, detail: str = "", status: str = "ok", **kw: Any) -> None:
    session.add(AgentRun(agent=agent, action=action, status=status, detail=detail[:4000], **kw))


def chunk_map(session: Session, ids: Iterable[int]) -> dict[int, Chunk]:
    out = {}
    for i in set(ids):
        c = session.get(Chunk, i)
        if c is not None:
            out[i] = c
    return out
