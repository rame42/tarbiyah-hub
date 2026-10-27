"""Quality Assurance Agent.

Checks performed (results are indicators, never presented as objective truth):
- claim and finding quotes found verbatim in their passages (deterministic)
- AI review of whether finding statements are supported by their verified quotes (optional)
- low extraction quality / OCR flags, sent back for reprocessing when a better method is available
- possible duplicate records (same normalized title) not yet linked
- link checks on a small daily sample of source URLs
"""
from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..ai.claude import claude
from ..ai.schemas import QAReview
from ..db import utcnow
from ..http import FetchError, RobotsDisallowed, http
from ..ingest.extract import tesseract_available
from ..jobs import queue
from ..models import Chunk, Claim, Finding, Resource
from ..settings import get_setting
from ..config import get_config
from .common import audit, verify_quote


def recheck_claims(session: Session, limit: int = 200) -> int:
    n = 0
    for cl in session.execute(select(Claim).where(Claim.qa_status == "pending").limit(limit)).scalars():
        c = session.get(Chunk, cl.chunk_id) if cl.chunk_id else None
        cl.quote_verified = bool(c and cl.quote and verify_quote(cl.quote, c.text))
        cl.qa_status = "verified_quote" if cl.quote_verified else "unverified"
        n += 1
    return n


def review_findings(session: Session, limit: int = 15) -> int:
    rows = session.execute(select(Finding).where(Finding.qa_status == "verified_quotes")
                           .order_by(Finding.id).limit(limit)).scalars().all()
    if not rows or not claude().available():
        return 0
    items = []
    for i, f in enumerate(rows):
        quotes = "\n".join(f"  - \"{e['quote']}\" ({e.get('title') or ''}, p.{e.get('page') or '-'})"
                           for e in f.evidence if e.get("quote_verified"))
        items.append(f"[{i}] Statement: {f.statement}\n Evidence quotes:\n{quotes}")
    session.commit()
    out: QAReview = claude().structured(
        "qa", "You are a strict fact-checker. For each statement decide whether the quoted evidence alone supports it.",
        "<source>\n" + "\n\n".join(items) + "\n</source>", QAReview, max_tokens=8000)
    for v in out.verdicts:
        if 0 <= v.index < len(rows):
            f = rows[v.index]
            f.qa_status = {"supported": "qa_supported", "partially_supported": "qa_partial",
                           "unsupported": "qa_unsupported"}[v.verdict]
            f.qa_notes = ((f.qa_notes or "") + f" | QA: {v.note}").strip(" |")
            if v.verdict == "unsupported":
                f.confidence = "low"
    audit(session, "qa", "review_findings", f"{len(out.verdicts)} finding(s) reviewed")
    return len(out.verdicts)


def reprocess_flagged(session: Session, limit: int = 20) -> int:
    """Send scanned/low-quality documents back for processing when OCR became available."""
    ocr_ready = tesseract_available(get_config().tesseract_cmd) or (
        claude().available() and get_setting("ocr_provider", session) in ("auto", "claude"))
    if not ocr_ready:
        return 0
    n = 0
    for r in session.execute(select(Resource).where(Resource.processing_status == "needs_ocr").limit(limit)).scalars():
        if (r.extra or {}).get("ocr_attempted"):
            continue
        r.extra = {**(r.extra or {}), "ocr_attempted": True}
        queue.enqueue(session, "process", {"resource_id": r.id}, priority=50, group="processing",
                      dedupe_key=f"process:{r.id}")
        n += 1
    return n


def flag_possible_duplicates(session: Session) -> int:
    rows = session.execute(select(Resource.title_key, func.count()).where(
        Resource.title_key.is_not(None), Resource.duplicate_of_id.is_(None),
        Resource.resource_type.not_in(("social_post", "web_page", "article")))
        .group_by(Resource.title_key).having(func.count() > 1).limit(50)).all()
    n = 0
    for key, _ in rows:
        group = session.execute(select(Resource).where(Resource.title_key == key)).scalars().all()
        ids = [r.id for r in group]
        for r in group:
            q = dict(r.quality or {})
            if q.get("possible_duplicates") != ids:
                q["possible_duplicates"] = [i for i in ids if i != r.id]
                r.quality = q
                n += 1
    return n


def check_links(session: Session, sample: int = 8) -> int:
    cutoff = utcnow() - timedelta(days=30)
    rows = session.execute(select(Resource).where(Resource.url.is_not(None)).order_by(func.random()).limit(sample * 3)).scalars().all()
    n = 0
    for r in rows:
        last = (r.quality or {}).get("link_checked_at")
        if last and last > cutoff.isoformat():
            continue
        try:
            http().fetch(r.url, method="HEAD", retries=1, timeout=20)
            status = "ok"
        except RobotsDisallowed:
            status = "not_checked_robots"
        except FetchError as e:
            status = f"error:{e.status or 'network'}"
        q = dict(r.quality or {})
        q["link_status"] = status
        q["link_checked_at"] = utcnow().isoformat()
        r.quality = q
        n += 1
        if n >= sample:
            break
    return n


def run_qa(session: Session, with_links: bool = True) -> dict:
    res = {"claims_rechecked": recheck_claims(session), "findings_reviewed": 0,
           "reprocess_queued": reprocess_flagged(session), "duplicate_flags": flag_possible_duplicates(session),
           "links_checked": 0}
    try:
        res["findings_reviewed"] = review_findings(session)
    except Exception as e:  # noqa: BLE001 - QA by AI is optional
        res["ai_qa_error"] = str(e)[:200]
    if with_links:
        res["links_checked"] = check_links(session)
    audit(session, "qa", "run", str(res))
    return res
