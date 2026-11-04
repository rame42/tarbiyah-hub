"""Strict mode for the sources the person adds: only exactly what they need enters the library.

Checks, in order (an item failing any of them is not kept):
 1. right place     the crawler stays in the section (web sources: section_lock, see sources/web.py)
 2. site's label    the page's own breadcrumb / category / tags match `site_sections` (when set)
 3. right kind      resource type in `types`, or a downloadable file when `files_only`
 4. pillar check    the item belongs to one of `pillars` with a score >= `min_score`
                    (judged by the AI when configured, otherwise by the full-text rules after processing).
                    Until it is judged the item is held (archived, reason "waiting for the pillar check").
Optional: `review` puts items that pass into "To review" for the person's approval.
Precision watch: if too many items fail (or the person rejects them), the source pauses itself.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "pillars": ["children", "parents", "murabbi"],
    "types": [],             # empty = any kind
    "files_only": False,
    "site_sections": [],     # words that must appear in the page's own section labels (web)
    "min_score": 40,
    "review": False,
    "pause_below": 30,       # % precision under which the source pauses (0 = never)
    "min_judged": 20,
}
FILE_TYPES = {"document", "book", "book_chapter", "paper", "thesis", "report", "manual", "curriculum"}


def settings_of(src: Any) -> dict[str, Any] | None:
    cfg = ((src.config or {}).get("strict") if src is not None else None) or {}
    if not cfg.get("enabled"):
        return None
    return {**DEFAULTS, **cfg}


def pre_save(cfg: dict[str, Any], d: Any) -> str | None:
    """Checks that need no AI, done before anything is saved. Returns the reason for rejecting, or None."""
    from .sources.base import matches_keywords

    if cfg.get("types") and d.resource_type not in cfg["types"]:
        return f"kind '{d.resource_type}' not allowed"
    if cfg.get("files_only") and not _is_file(d):
        return "not a downloadable file"
    sections = cfg.get("site_sections") or []
    if sections and not _is_file(d):  # files (PDFs) carry no site labels; they were found on section pages
        labels = (d.extra or {}).get("site_labels") or []
        if not labels:
            return "the site gives no section label for this page"
        if not matches_keywords(sections, *labels):
            return "filed by the site under: " + " / ".join(labels[:4])
    return None


DOC_SUFFIXES = (".pdf", ".epub", ".doc", ".docx", ".odt", ".rtf", ".djvu", ".txt", ".ppt", ".pptx")


def _is_file(d: Any) -> bool:
    from urllib.parse import urlsplit

    if d.download_url:
        return True
    path = urlsplit(d.url or "").path.lower()
    return path.endswith(DOC_SUFFIXES) or (d.extra or {}).get("format") in ("pdf", "epub", "doc", "docx")


def _stats(src: Any) -> dict[str, int]:
    st = dict(src.state or {})
    s = dict(st.get("strict_stats") or {})
    for k in ("passed", "rejected", "approved", "rejected_user", "skipped_before_saving"):
        s.setdefault(k, 0)
    return s


def _save_stats(src: Any, s: dict[str, int]) -> None:
    src.state = {**(src.state or {}), "strict_stats": s}


def precision(src: Any) -> tuple[int | None, int]:
    """(precision %, number of judged items). With review: the person's approvals; otherwise the pillar check."""
    s = _stats(src)
    cfg = settings_of(src) or DEFAULTS
    if cfg.get("review") and s["approved"] + s["rejected_user"]:
        n = s["approved"] + s["rejected_user"]
        return round(100 * s["approved"] / n), n
    n = s["passed"] + s["rejected"] + s["rejected_user"]
    if not n:
        return None, 0
    return round(100 * max(0, s["passed"] - s["rejected_user"]) / n), n


def _watch(src: Any) -> None:
    cfg = settings_of(src)
    if not cfg or not int(cfg.get("pause_below") or 0):
        return
    p, n = precision(src)
    if p is not None and n >= int(cfg.get("min_judged") or 20) and p < int(cfg["pause_below"]) and src.enabled:
        src.enabled = False
        src.health = "paused"
        src.last_error = (f"Paused by the precision watch: only {p}% of the last {n} judged items were relevant "
                          f"(your minimum is {cfg['pause_below']}%). Adjust the strict settings, then enable it again.")


def count_skipped(src: Any) -> None:
    s = _stats(src)
    s["skipped_before_saving"] += 1
    _save_stats(src, s)


def decide(session: Session, r: Any, src: Any, cfg: dict[str, Any]) -> None:
    """Hold, pass or reject an item from a strict source (called whenever its scores change)."""
    from .ai.claude import claude
    from .ingest.manage import archive_resource, unarchive_resource
    from .settings import get_setting

    ex = dict(r.extra or {})
    if ex.get("archived_by") == "user" or ex.get("strict") in ("approved", "rejected_user"):
        return  # the person decided
    ai_on = claude().available() and bool(get_setting("ai_triage", session))
    if ex.get("relevance_user") is not None:
        score = int(ex["relevance_user"])
    elif ex.get("relevance_ai") is not None:
        score = int(ex["relevance_ai"])
    elif not ai_on and r.processing_status not in ("pending",):
        score = r.relevance if r.relevance is not None else 0
    else:
        score = None
    before = ex.get("strict")
    if score is None:
        if not r.archived:
            archive_resource(session, r, by="strict", reason="waiting for the pillar check")
        return
    wanted = set(cfg.get("pillars") or DEFAULTS["pillars"])
    have = {p.pillar for p in r.pillars}
    ok = score >= int(cfg.get("min_score") or 0) and bool(have & wanted)
    if ok:
        if cfg.get("review"):
            archive_resource(session, r, by="review", reason="passed the checks; waiting for your approval")
        elif r.archived:
            unarchive_resource(session, r, by="auto")
        state = "passed"
    else:
        why = (f"score {score} below {cfg.get('min_score')}" if score < int(cfg.get("min_score") or 0)
               else "not in the chosen pillars")
        archive_resource(session, r, by="strict", reason=f"did not pass the pillar check ({why})")
        state = "rejected"
    r.extra = {**(r.extra or {}), "strict": state}
    if before != state:
        s = _stats(src)
        if before in ("passed", "rejected"):
            s[before] = max(0, s[before] - 1)
        s[state] += 1
        _save_stats(src, s)
        _watch(src)


def review(session: Session, r: Any, keep: bool) -> None:
    """The person's ✔ / ✖ on an item waiting in "To review" (or any item of a strict source)."""
    from .ingest.manage import delete_resource, unarchive_resource
    from .models import Source

    src = session.get(Source, r.source_id) if r.source_id else None
    if keep:
        unarchive_resource(session, r, by="user")
        r.extra = {**(r.extra or {}), "strict": "approved", "feedback": "up"}
    else:
        r.extra = {**(r.extra or {}), "strict": "rejected_user", "feedback": "down"}
        delete_resource(session, r)  # never collected again
    if src is not None and settings_of(src):
        s = _stats(src)
        s["approved" if keep else "rejected_user"] += 1
        _save_stats(src, s)
        _watch(src)
