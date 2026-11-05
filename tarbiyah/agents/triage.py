"""Triage agent: the AI screens newly collected items in batches of 20 using only their metadata
(title, description, type, source). One request per batch, so it is cheap even with thousands of
items and works for items without full text. The score becomes the item's relevance; with
auto-archive on, weak items are put aside automatically (never deleted)."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.claude import claude
from ..ai.schemas import TriageBatch
from ..models import Resource, ResourcePillar
from .common import audit

SYSTEM = (
    "You screen items collected for a research library on Islamic tarbiyah (upbringing and education) in three "
    "pillars: children's tarbiyah, parents & family, and murabbi (educator/mentor) development. For each item "
    "give relevance 0-100 judged ONLY from the metadata shown:\n"
    "0-10 unrelated (sports, politics, commerce, unrelated science, spam);\n"
    "10-30 only mentions children, family or education in passing, or very general content;\n"
    "30-60 related to parenting, child development or education but not specifically useful;\n"
    "60-85 clearly useful for one of the pillars (Islamic or well-founded general research/guidance);\n"
    "85-100 central, substantive source (scholarly work, serious book, structured course, strong research).\n"
    "Be strict: clickbait, promotional or shallow content scores lower. Give the pillars the item serves "
    "(empty list if none). Return every item id you were given."
)


def _candidates(session: Session, limit: int) -> list[Resource]:
    return session.execute(
        select(Resource).where(Resource.deleted.is_(False), Resource.duplicate_of_id.is_(None),
                               func.json_extract(Resource.extra, "$.relevance_ai").is_(None),
                               func.json_extract(Resource.extra, "$.triaged").is_(None),
                               Resource.collection_method.not_in(("manual", "local_import")))
        .order_by(Resource.discovered_at.desc()).limit(limit)).scalars().all()


def _criteria(session: Session, r: Resource) -> str:
    from ..models import Source

    if not r.source_id:
        return ""
    src = session.get(Source, r.source_id)
    return str(((src.config or {}).get("strict") or {}).get("criteria") or "").strip() if src else ""


def pending_count(session: Session) -> int:
    return len(_candidates(session, 1000))


def _block(r: Resource) -> str:
    desc = (r.description or "")[:600].replace("<", "‹")
    return (f'<item id="{r.id}">\nTitle: {r.title[:300]}\nType: {r.resource_type}\nLanguage: {r.language or "-"}\n'
            f"Source: {r.source_key or '-'} | Publisher/channel: {r.publisher or '-'}\n"
            f"Description: {desc or '-'}\n</item>")


def triage_batch(session: Session, size: int = 20) -> dict[str, Any]:
    from ..ingest.manage import auto_curate

    items = _candidates(session, size * 3)
    if not items:
        return {"triaged": 0}
    # items from a source with its own "points to be considered" are judged together, with those points
    crit = _criteria(session, items[0])
    items = [r for r in items if _criteria(session, r) == crit][:size]
    system = SYSTEM
    if crit:
        system += ("\nThe person who added the source of these items gave these points to be considered. Apply them "
                   "strictly: items that do not meet them score below 30.\nPOINTS TO BE CONSIDERED:\n" + crit[:2000])
    content = "Items:\n<source>\n" + "\n".join(_block(r) for r in items) + "\n</source>"
    session.commit()  # release the write lock while waiting for the model
    out: TriageBatch = claude().structured("triage", system, content, TriageBatch, max_tokens=6000, effort="low")
    by_id = {r.id: r for r in items}
    done = 0
    for t in out.items:
        r = by_id.pop(t.id, None)
        if r is None:
            continue
        extra = dict(r.extra or {})
        extra["relevance_ai"] = max(0, min(100, int(t.relevance)))
        extra["relevance_reason"] = t.reason[:400]
        extra["triaged"] = True
        r.extra = extra
        if t.pillars and not r.pillars:
            for p in dict.fromkeys(t.pillars):
                session.add(ResourcePillar(resource_id=r.id, pillar=p, score=0.6, method="ai"))
            session.flush()
        auto_curate(session, r)
        done += 1
    for r in by_id.values():  # not returned by the model: do not ask again
        r.extra = {**(r.extra or {}), "triaged": True}
    audit(session, "knowledge", "triage", f"{done} item(s) screened for relevance")
    return {"triaged": done}
