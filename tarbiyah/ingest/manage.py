"""User curation of the library: edit, label, delete (and undo delete).

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
            else:
                raise ValueError(f"Unknown action '{action}'")
            ok += 1
        except ValueError as e:
            errors.append(f"#{rid}: {e}")
            if "Unknown action" in str(e) or "Unknown access" in str(e) or "Unknown pillar" in str(e) or "Unknown type" in str(e):
                break
    return {"done": ok, "errors": errors[:20]}
