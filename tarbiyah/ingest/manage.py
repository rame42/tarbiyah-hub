"""User curation of the library: edit, label, archive, delete (and undo), relevance.

Archive puts an item aside: it keeps its file and text but is hidden from the library, search,
research and reports until it is unarchived. Items can be archived automatically by the
relevance rules (exclude words, auto_archive_below); the user's own choice always wins.

Deleting keeps a small record (title, link, checksum) marked `deleted`, so the same item is
recognised as a duplicate and is NOT collected again by later searches or crawls. Its file,
extracted text, passages and search entries are removed.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Chunk, Claim, Embedding, Resource, ResourcePillar
from ..search import fts
from ..storage import absolute
from ..taxonomy import PILLAR_LABELS
from .licensing import AccessDecision

ACCESS_VALUES = ("public_domain", "open_license", "open_access", "free_to_read", "user_provided", "paid",
                 "lending_only", "restricted", "unknown")
DOWNLOADABLE = {"public_domain", "open_license", "open_access", "user_provided"}
TYPE_VALUES = ("book", "book_chapter", "paper", "thesis", "report", "article", "web_page", "document", "video",
               "podcast_episode", "audio", "social_post", "course", "curriculum", "manual", "institution_page",
               "manuscript", "other")


def delete_resource(session: Session, r: Resource) -> None:
    if r.deleted:
        return
    ids = [c for (c,) in session.execute(select(Chunk.id).where(Chunk.resource_id == r.id))]
    fts.remove_resource(session, r.id)
    if ids:
        session.execute(delete(Embedding).where(Embedding.chunk_id.in_(ids)))
        session.execute(delete(Claim).where(Claim.resource_id == r.id))
        session.execute(delete(Chunk).where(Chunk.resource_id == r.id))
    for rel in (r.local_path, r.text_path, (r.extra or {}).get("inline_path")):
        if rel:
            try:
                absolute(rel).unlink(missing_ok=True)
            except OSError:
                pass
    r.local_path = None
    r.text_path = None
    r.file_size = None
    r.deleted = True
    r.processing_status = "deleted"
    r.extra = {**(r.extra or {}), "deleted_at": utcnow().isoformat(), "inline_path": None}


def restore_resource(session: Session, r: Resource) -> str:
    """Undo a delete. The content is collected again (download if permitted, or page/abstract)."""
    from ..jobs import queue

    r.deleted = False
    r.processing_status = "pending"
    extra = dict(r.extra or {})
    extra.pop("deleted_at", None)
    if r.url and r.resource_type in ("article", "web_page", "institution_page", "course"):
        extra["fetch_page"] = True
    r.extra = extra
    if r.download_permitted and r.download_url:
        r.acquisition_status = "pending"
        queue.enqueue(session, "acquire", {"resource_id": r.id}, group="acquisition", dedupe_key=f"acquire:{r.id}")
    else:
        queue.enqueue(session, "process", {"resource_id": r.id}, group="processing", dedupe_key=f"process:{r.id}")
    return "restored"


USER_METHODS = {"manual", "local_import", "upload"}


def is_my_source(src: Any) -> bool:
    """A source the person added themselves (not a built-in search source, the inbox or an auto-added one)."""
    cfg = (src.config or {}) if src is not None else {}
    return bool(src is not None and cfg.get("role") == "monitor" and src.key != "inbox"
                and cfg.get("added_by") != "auto")


def keeps_everything(session: Session, r: Resource) -> bool:
    """Items from the person's own monitored sources are never archived automatically."""
    from ..models import Source

    if not r.source_id:
        return False
    src = session.get(Source, r.source_id)
    return is_my_source(src) and (src.config or {}).get("collect_everything", True) is not False


def _final_relevance(r: Resource) -> int | None:
    ex = r.extra or {}
    for k in ("relevance_user", "relevance_ai", "relevance_rules"):
        if ex.get(k) is not None:
            return int(ex[k])
    return None


def auto_curate(session: Session, r: Resource) -> None:
    """Set the final relevance and apply the automatic archive rules (never overriding the user)."""
    from ..settings import get_setting

    r.relevance = _final_relevance(r)
    ex = r.extra or {}
    if r.deleted or ex.get("archived_by") == "user" or r.collection_method in USER_METHODS:
        return
    if keeps_everything(session, r):
        if r.archived and ex.get("archived_by") == "auto":
            unarchive_resource(session, r, by="auto")
        return
    threshold = int(get_setting("auto_archive_below", session) or 0)
    reason = None
    if ex.get("excluded_by") and ex.get("relevance_user") is None:
        reason = f"contains the excluded word '{ex['excluded_by']}'"
    elif threshold and r.relevance is not None and r.relevance < threshold:
        reason = f"relevance {r.relevance} is below {threshold}"
    if reason and not r.archived:
        archive_resource(session, r, by="auto", reason=reason)
    elif not reason and r.archived and ex.get("archived_by") == "auto":
        unarchive_resource(session, r, by="auto")


def archive_resource(session: Session, r: Resource, by: str = "user", reason: str | None = None) -> None:
    r.archived = True
    r.extra = {**(r.extra or {}), "archived_by": by, "archived_reason": reason or "archived by the user",
               "archived_at": utcnow().isoformat()}


def unarchive_resource(session: Session, r: Resource, by: str = "user") -> None:
    r.archived = False
    extra = {k: v for k, v in (r.extra or {}).items() if k not in ("archived_reason", "archived_at")}
    # the user's decision to keep it sticks: automatic rules will not archive it again
    extra["archived_by"] = "user" if by == "user" else None
    r.extra = extra


def set_relevance(session: Session, r: Resource, value: int | None) -> None:
    extra = dict(r.extra or {})
    if value is None:
        extra.pop("relevance_user", None)
    else:
        extra["relevance_user"] = max(0, min(100, int(value)))
    r.extra = extra
    auto_curate(session, r)


def reclassify(session: Session, r: Resource) -> None:
    """Run the keyword rules again (after new focus/exclude words or glossary terms)."""
    from ..storage import absolute as _abs
    from .classify import apply_classification, classify_text

    body = ""
    if r.text_path:
        try:
            body = _abs(r.text_path).read_text(encoding="utf-8")[:30000]
        except OSError:
            body = ""
    if not body:
        body = " ".join(c for (c,) in session.execute(
            select(Chunk.text).where(Chunk.resource_id == r.id).order_by(Chunk.seq).limit(20)))
    apply_classification(session, r, classify_text(session, r.title, r.description or "", body, r.keywords))


def set_pillars(session: Session, r: Resource, pillars: list[str]) -> None:
    bad = [p for p in pillars if p not in PILLAR_LABELS]
    if bad:
        raise ValueError(f"Unknown pillar(s): {bad}. Use: {', '.join(PILLAR_LABELS)}")
    session.execute(delete(ResourcePillar).where(ResourcePillar.resource_id == r.id))
    session.flush()
    for p in dict.fromkeys(pillars):
        session.add(ResourcePillar(resource_id=r.id, pillar=p, score=1.0, method="user"))


def set_access(session: Session, r: Resource, access: str) -> None:
    from ..jobs import queue

    if access not in ACCESS_VALUES:
        raise ValueError(f"Unknown access status '{access}'. Use: {', '.join(ACCESS_VALUES)}")
    d = AccessDecision(access, access in DOWNLOADABLE,
                       f"Set by the user to '{access}' on {utcnow().date().isoformat()}.")
    r.access_status, r.download_permitted, r.permission_basis = d.access_status, d.download_permitted, d.basis
    if d.download_permitted and not r.local_path:
        if not r.download_url and (r.extra or {}).get("pdf_url"):
            r.download_url = r.extra["pdf_url"]
        if r.download_url:
            r.acquisition_status = "pending"
            queue.enqueue(session, "acquire", {"resource_id": r.id}, group="acquisition", dedupe_key=f"acquire:{r.id}")


def update_resource(session: Session, r: Resource, changes: dict[str, Any]) -> list[str]:
    done = []
    if "title" in changes and str(changes["title"]).strip():
        r.title = str(changes["title"]).strip()[:2000]
        done.append("title")
    if "resource_type" in changes:
        if changes["resource_type"] not in TYPE_VALUES:
            raise ValueError(f"Unknown type. Use: {', '.join(TYPE_VALUES)}")
        r.resource_type = changes["resource_type"]
        done.append("type")
    if "language" in changes:
        r.language = changes["language"] or None
        done.append("language")
    if "pillars" in changes:
        set_pillars(session, r, list(changes["pillars"] or []))
        done.append("pillars")
    if "access_status" in changes:
        set_access(session, r, changes["access_status"])
        done.append("access")
    labels = list(r.labels or [])
    for lb in changes.get("add_labels") or []:
        lb = str(lb).strip()[:60]
        if lb and lb not in labels:
            labels.append(lb)
    for lb in changes.get("remove_labels") or []:
        labels = [x for x in labels if x != lb]
    if "labels" in changes:
        labels = [str(x).strip()[:60] for x in changes["labels"] if str(x).strip()]
    if labels != (r.labels or []):
        r.labels = labels
        done.append("labels")
    if "relevance" in changes:
        set_relevance(session, r, None if changes["relevance"] in (None, "") else int(changes["relevance"]))
        done.append("relevance")
    if "archived" in changes:
        (archive_resource if changes["archived"] else unarchive_resource)(session, r)
        done.append("archived")
    if "notes" in changes:
        r.extra = {**(r.extra or {}), "user_notes": str(changes["notes"])[:5000]}
        done.append("notes")
    if done and not r.deleted:
        fts.index_resource(session, r)  # new title/labels become searchable
    return done


def bulk(session: Session, ids: list[int], action: str, value: Any = None) -> dict[str, Any]:
    ok, errors = 0, []
    for rid in ids[:2000]:
        r = session.get(Resource, rid)
        if r is None:
            continue
        try:
            if action == "delete":
                delete_resource(session, r)
            elif action == "restore":
                restore_resource(session, r)
            elif action == "set_access":
                set_access(session, r, value)
            elif action == "set_pillars":
                set_pillars(session, r, value or [])
            elif action == "add_label":
                update_resource(session, r, {"add_labels": [value]})
            elif action == "remove_label":
                update_resource(session, r, {"remove_labels": [value]})
            elif action == "set_type":
                update_resource(session, r, {"resource_type": value})
            elif action == "archive":
                archive_resource(session, r)
            elif action == "unarchive":
                unarchive_resource(session, r)
            elif action == "reclassify":
                reclassify(session, r)
            elif action == "analyze":
                from ..jobs import queue

                queue.enqueue(session, "analyze", {"resource_id": r.id}, group="ai", dedupe_key=f"analyze:{r.id}")
            elif action == "set_relevance":
                set_relevance(session, r, None if value in (None, "") else int(value))
            else:
                raise ValueError(f"Unknown action '{action}'")
            ok += 1
        except ValueError as e:
            errors.append(f"#{rid}: {e}")
            if "Unknown action" in str(e) or "Unknown access" in str(e) or "Unknown pillar" in str(e) or "Unknown type" in str(e):
                break
    return {"done": ok, "errors": errors[:20]}
