"""Resource registration with duplicate detection and provenance.

Every collector funnels discoveries through `register()`. Duplicates are detected by
(in order) DOI, ISBN, source+external id, canonical URL, then bibliographic
similarity (normalized title key + year + author overlap). A duplicate never creates
a second record: missing metadata is merged into the existing one instead.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from rapidfuzz import fuzz
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import utcnow
from ..models import Entity, Resource, ResourceEntity
from ..text.arabic import normalize_for_search, title_key
from ..text.lang import detect_language
from .licensing import AccessDecision

_TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ref_|igshid|si$)")


def canonical_url(url: str | None) -> str | None:
    if not url:
        return None
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url
    if not parts.scheme:
        return url
    q = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=False) if not _TRACKING.match(k.lower())]
    host = parts.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if host in ("m.youtube.com", "youtu.be"):
        host = "youtube.com"
    path = parts.path.rstrip("/") or "/"
    return urlunsplit(("https" if parts.scheme in ("http", "https") else parts.scheme, host, path,
                       urlencode(sorted(q)), ""))


def url_hash(url: str) -> str:
    return hashlib.sha1((canonical_url(url) or url).encode()).hexdigest()


def norm_doi(doi: str | None) -> str | None:
    if not doi:
        return None
    d = doi.strip().lower()
    d = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", d)
    return d or None


@dataclass
class ResourceIn:
    title: str
    resource_type: str = "other"
    url: str | None = None
    download_url: str | None = None
    authors: list[str] = field(default_factory=list)
    description: str | None = None
    language: str | None = None
    published_date: str | None = None
    year: int | None = None
    publisher: str | None = None
    doi: str | None = None
    isbn: str | None = None
    external_id: str | None = None
    source_key: str | None = None
    source_id: int | None = None
    collection_method: str | None = None
    license: str | None = None
    license_url: str | None = None
    access: AccessDecision | None = None
    price: str | None = None
    currency: str | None = None
    purchase_url: str | None = None
    alt_titles: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    text: str | None = None  # inline content (posts, abstracts-as-content, transcripts)
    segments: list[dict[str, Any]] | None = None  # pre-segmented content (transcripts with timestamps)
    channel: str | None = None  # social account / channel name
    question_id: int | None = None


def find_duplicate(session: Session, d: ResourceIn) -> Resource | None:
    doi = norm_doi(d.doi)
    if doi:
        r = session.execute(select(Resource).where(Resource.doi == doi)).scalars().first()
        if r:
            return r
    if d.isbn:
        isbn = re.sub(r"[^0-9Xx]", "", d.isbn)
        r = session.execute(select(Resource).where(Resource.isbn == isbn)).scalars().first()
        if r:
            return r
    if d.external_id and d.source_key:
        r = session.execute(select(Resource).where(Resource.source_key == d.source_key,
                                                   Resource.external_id == d.external_id)).scalars().first()
        if r:
            return r
    cu = canonical_url(d.url)
    if cu:
        r = session.execute(select(Resource).where(Resource.canonical_url == cu)).scalars().first()
        if r:
            return r
    tk = title_key(d.title or "")
    if tk and len(tk) >= 12 and d.resource_type not in ("social_post", "web_page"):
        cands = session.execute(select(Resource).where(Resource.title_key == tk)).scalars().all()
        for c in cands:
            if d.year and c.year and abs(d.year - c.year) > 1:
                continue
            if d.authors and c.authors_text:
                a1 = normalize_for_search(" ".join(d.authors))
                a2 = normalize_for_search(c.authors_text)
                if fuzz.token_set_ratio(a1, a2) < 60:
                    continue
            return c
    return None


def _merge(existing: Resource, d: ResourceIn) -> None:
    def fill(attr: str, value: Any) -> None:
        if value and not getattr(existing, attr):
            setattr(existing, attr, value)

    fill("description", d.description)
    fill("published_date", d.published_date)
    fill("year", d.year)
    fill("publisher", d.publisher)
    fill("doi", norm_doi(d.doi))
    fill("license", d.license)
    fill("license_url", d.license_url)
    fill("purchase_url", d.purchase_url)
    fill("price", d.price)
    if d.title and d.title != existing.title and d.title not in (existing.alt_titles or []):
        existing.alt_titles = [*(existing.alt_titles or []), d.title]
    # A newly found legal download source upgrades a metadata-only record.
    if d.access and d.access.download_permitted and not existing.download_permitted and d.download_url:
        existing.download_permitted = True
        existing.access_status = d.access.access_status
        existing.permission_basis = d.access.basis
        existing.download_url = d.download_url
        if existing.acquisition_status in ("metadata_only", "failed"):
            existing.acquisition_status = "pending"
    seen = dict(existing.extra or {})
    seen.setdefault("also_seen_at", [])
    if d.url and d.url not in seen["also_seen_at"] and canonical_url(d.url) != existing.canonical_url:
        seen["also_seen_at"] = [*seen["also_seen_at"], d.url][-20:]
        existing.extra = seen


def entity_key(name: str) -> str:
    return normalize_for_search(re.sub(r"[.,]", " ", name))[:300]


def upsert_entity(session: Session, entity_type: str, name: str, **kw: Any) -> Entity:
    key = entity_key(name)
    e = session.execute(select(Entity).where(Entity.entity_type == entity_type, Entity.norm_key == key)).scalars().first()
    if e is None:
        lang = detect_language(name)
        e = Entity(entity_type=entity_type, name=name.strip(), norm_key=key,
                   name_ar=name if lang == "ar" else None, name_en=name if lang == "en" else None, **kw)
        session.add(e)
        session.flush()
    else:
        for k, v in kw.items():
            if v and not getattr(e, k, None):
                setattr(e, k, v)
    return e


def link_entity(session: Session, resource_id: int, entity: Entity, role: str) -> None:
    if session.get(ResourceEntity, (resource_id, entity.id, role)) is None:
        session.add(ResourceEntity(resource_id=resource_id, entity_id=entity.id, role=role))


def register(session: Session, d: ResourceIn) -> tuple[Resource, bool]:
    """Insert a discovered resource or merge into an existing one. Returns (resource, created).

    Safe under concurrency: if another job inserted the same URL/DOI in the meantime, the unique
    index rejects the insert and the record is merged into the one that won."""
    dup = find_duplicate(session, d)
    if dup is not None:
        _merge(dup, d)
        return dup, False
    try:
        with session.begin_nested():
            return _insert(session, d)
    except IntegrityError:
        dup = find_duplicate(session, d)
        if dup is None:
            raise
        _merge(dup, d)
        return dup, False


def _insert(session: Session, d: ResourceIn) -> tuple[Resource, bool]:
    access = d.access
    lang = d.language or detect_language(" ".join(filter(None, [d.title, d.description or "", (d.text or "")[:3000]])))
    r = Resource(
        resource_type=d.resource_type,
        title=(d.title or "(untitled)").strip()[:2000],
        alt_titles=d.alt_titles,
        authors_text="; ".join(d.authors) if d.authors else None,
        description=d.description,
        language=lang,
        published_date=d.published_date,
        year=d.year,
        publisher=d.publisher,
        url=d.url,
        canonical_url=canonical_url(d.url),
        download_url=d.download_url,
        source_id=d.source_id,
        source_key=d.source_key,
        external_id=d.external_id,
        doi=norm_doi(d.doi),
        isbn=re.sub(r"[^0-9Xx]", "", d.isbn) if d.isbn else None,
        collection_method=d.collection_method,
        license=d.license,
        license_url=d.license_url,
        access_status=access.access_status if access else "unknown",
        download_permitted=bool(access and access.download_permitted),
        permission_basis=access.basis if access else "No licence information: metadata and link only.",
        price=d.price,
        currency=d.currency,
        purchase_url=d.purchase_url,
        title_key=title_key(d.title or "") or None,
        keywords=d.keywords,
        extra={**d.extra, **({"channel": d.channel} if d.channel else {})},
        discovered_by_question_id=d.question_id,
        acquisition_status="pending" if (access and access.download_permitted and d.download_url) else "metadata_only",
        discovered_at=utcnow(),
    )
    session.add(r)
    session.flush()
    for a in d.authors[:25]:
        if a and len(a) < 300:
            link_entity(session, r.id, upsert_entity(session, "person", a), "author")
    if d.publisher and len(d.publisher) < 300:
        link_entity(session, r.id, upsert_entity(session, "organization", d.publisher), "publisher")
    if d.channel:
        link_entity(session, r.id, upsert_entity(session, "channel", d.channel), "channel")
    return r, True
