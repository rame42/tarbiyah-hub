"""Acquisition (legal download) and processing (extract -> chunk -> classify -> index)."""
from __future__ import annotations

import json
import logging
import mimetypes
from pathlib import Path
from typing import Callable

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..config import get_config
from ..db import utcnow
from ..http import FetchError, http
from ..models import Chunk, Resource
from ..search import fts
from ..settings import get_setting, record_usage, within_budget
from ..storage import StorageLimitError, absolute, guess_ext, relative, sha256_bytes, sha256_file, store_bytes, store_file
from ..text.arabic import title_key
from ..text.lang import detect_language
from .classify import apply_classification, classify_text
from .extract import (
    ExtractionError,
    ExtractResult,
    Segment,
    chunk_segments,
    extract_file,
    extract_html,
    finalize,
    ocr_pdf_pages_tesseract,
    tesseract_available,
    text_quality,
)
from .licensing import decide
from .registry import ResourceIn, register

log = logging.getLogger(__name__)

MAGIC = {b"%PDF": "application/pdf", b"PK\x03\x04": "application/zip"}


class AcquisitionError(RuntimeError):
    def __init__(self, msg: str, transient: bool = False):
        super().__init__(msg)
        self.transient = transient


# ------------------------------------------------------------------ inline content

def save_inline_segments(r: Resource, segments: list[dict]) -> None:
    """Persist collected text (posts, transcripts, abstracts) for processing."""
    cfg = get_config()
    path = cfg.text_dir / "inline" / f"{r.id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(segments, ensure_ascii=False), encoding="utf-8")
    extra = dict(r.extra or {})
    extra["inline_path"] = relative(path)
    r.extra = extra


def register_with_content(session: Session, d: ResourceIn) -> tuple[Resource, bool]:
    r, created = register(session, d)
    if created and (d.text or d.segments):
        segs = d.segments or [{"text": d.text}]
        save_inline_segments(r, segs)
        if r.acquisition_status == "metadata_only":
            r.acquisition_status = "text_collected"  # page/post/transcript text collected; no file stored
            r.collected_at = utcnow()
    return r, created


# ------------------------------------------------------------------ local import

def import_local_file(session: Session, path: Path, *, title: str | None = None, authors: list[str] | None = None,
                      resource_type: str = "book", language: str | None = None, description: str | None = None,
                      license: str | None = None, url: str | None = None) -> tuple[Resource, bool]:
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    checksum = sha256_file(path)
    existing = session.execute(select(Resource).where(Resource.checksum_sha256 == checksum)).scalars().first()
    if existing:
        return existing, False
    d = ResourceIn(title=title or path.stem.replace("_", " "), resource_type=resource_type, authors=authors or [],
                   language=language, description=description, license=license, url=url,
                   collection_method="local_import", source_key="local_import",
                   access=decide(license, user_provided=True))
    r, created = register(session, d)
    if not created:  # bibliographic duplicate of a known record: attach the file if it had none
        if r.local_path:
            return r, False
    stored = store_file(session, path, checksum, r.title)
    r.local_path = relative(stored)
    r.file_size = path.stat().st_size
    r.file_mime = mimetypes.guess_type(path.name)[0]
    r.checksum_sha256 = checksum
    r.acquisition_status = "downloaded"
    r.collected_at = utcnow()
    extra = dict(r.extra or {})
    extra["original_filename"] = path.name
    if not title:
        extra["title_from_filename"] = True  # replaced by the document's own title during processing
    r.extra = extra
    return r, created


# ------------------------------------------------------------------ acquisition

def acquire(session: Session, r: Resource) -> str:
    """Download the file when (and only when) download is permitted. Returns new status."""
    if r.local_path:
        r.acquisition_status = "downloaded"
        return r.acquisition_status
    if not r.download_permitted or not r.download_url:
        if r.acquisition_status != "text_collected":
            r.acquisition_status = "metadata_only"
        return r.acquisition_status
    if not within_budget(session, "downloads"):
        raise AcquisitionError("Daily download limit reached", transient=True)
    if not within_budget(session, "download_mb"):
        raise AcquisitionError("Daily download volume limit reached", transient=True)
    extra = r.extra or {}
    if extra.get("resolver") == "internet_archive" and "archive.org/metadata/" in r.download_url:
        from ..sources.books import InternetArchiveAdapter

        ident = extra.get("ia_identifier") or r.external_id
        try:
            found = InternetArchiveAdapter.resolve_download(ident)
        except FetchError as e:
            raise AcquisitionError(str(e), transient=e.transient) from e
        if not found:
            r.acquisition_status = "failed"
            r.last_error = "No PDF/EPUB/text file listed for this Internet Archive item."
            return r.acquisition_status
        r.download_url = found[0]
        r.extra = {**extra, "format": found[1]}
    try:
        res = http().fetch(r.download_url, timeout=120)
    except FetchError as e:
        r.last_error = str(e)
        raise AcquisitionError(str(e), transient=e.transient) from e
    data = res.content
    head = data[:8]
    ctype = res.content_type
    expected_pdf = r.download_url.lower().split("?")[0].endswith(".pdf") or (r.extra or {}).get("format") == "pdf"
    if expected_pdf and not head.startswith(b"%PDF"):
        r.acquisition_status = "failed"
        r.last_error = f"Expected a PDF but received {ctype or 'unknown content'} (landing page or access wall)."
        return r.acquisition_status
    if len(data) < 200:
        r.acquisition_status = "failed"
        r.last_error = "Downloaded file is empty or truncated."
        return r.acquisition_status
    checksum = sha256_bytes(data)
    other = session.execute(select(Resource).where(Resource.checksum_sha256 == checksum,
                                                   Resource.id != r.id)).scalars().first()
    if other:
        r.duplicate_of_id = other.id
        r.acquisition_status = "duplicate"
        r.checksum_sha256 = checksum
        return r.acquisition_status
    if head.startswith(b"%PDF"):
        ctype = "application/pdf"
    elif head.startswith(b"PK\x03\x04") and (r.download_url.lower().endswith(".epub") or "epub" in ctype):
        ctype = "application/epub+zip"
    ext = guess_ext(ctype, r.download_url)
    try:
        path = store_bytes(session, data, checksum, ext, r.title)
    except StorageLimitError as e:
        r.acquisition_status = "skipped_limit"
        r.last_error = str(e)
        return r.acquisition_status
    r.local_path = relative(path)
    r.file_size = len(data)
    r.file_mime = ctype or None
    r.checksum_sha256 = checksum
    r.acquisition_status = "downloaded"
    r.collected_at = utcnow()
    r.last_error = None
    record_usage("downloads")
    record_usage("download_mb", len(data) / 1048576)
    return r.acquisition_status


# ------------------------------------------------------------------ processing

OcrFn = Callable[[Path, list[int]], dict[int, str]]


def _ocr(path: Path, pages: list[int], claude_ocr: OcrFn | None) -> tuple[dict[int, str], str]:
    provider = get_setting("ocr_provider")
    cfg = get_config()
    if provider in ("auto", "tesseract") and tesseract_available(cfg.tesseract_cmd):
        return ocr_pdf_pages_tesseract(path, pages, get_setting("ocr_languages"), cfg.tesseract_cmd), "tesseract"
    if provider in ("auto", "claude") and claude_ocr is not None:
        return claude_ocr(path, pages), "claude"
    return {}, "none"


def _load_extract(session: Session, r: Resource, claude_ocr: OcrFn | None) -> ExtractResult | None:
    extra = r.extra or {}
    if r.local_path:
        path = absolute(r.local_path)
        res = extract_file(path, r.file_mime)
        if res.ocr_pages:
            texts, method = _ocr(path, res.ocr_pages[:400], claude_ocr)
            if texts:
                for seg in res.segments:
                    if seg.page in texts and texts[seg.page]:
                        seg.text = texts[seg.page]
                res.method += f"+ocr:{method}"
                res.meta["ocr_pages"] = len(texts)
                res.ocr_pages = [p for p in res.ocr_pages if not texts.get(p)]
            finalize(res)
        return res
    if extra.get("inline_path"):
        segs = json.loads(absolute(extra["inline_path"]).read_text(encoding="utf-8"))
        res = ExtractResult(method=extra.get("inline_method", "collected_text"))
        res.segments = [Segment(text=s.get("text", ""), page=s.get("page"), heading=s.get("heading"),
                                timestamp=s.get("timestamp")) for s in segs]
        return finalize(res)
    if extra.get("fetch_page") and r.url:
        fr = http().fetch(r.url)
        if "html" not in fr.content_type:
            return None
        res = extract_html(fr.content, r.url)
        if r.resource_type in ("article", "web_page", "course", "institution_page", "other"):
            from .courses import apply_course, course_from_html

            info = course_from_html(fr.content, r.url)
            if info:
                apply_course(r, info)
        return finalize(res)
    if r.description and len(r.description) >= 120:
        # Abstract / description published by the source: indexed as passages so it can be cited,
        # but the record stays "metadata_only" (the full text was not acquired).
        res = ExtractResult(method="abstract")
        res.segments = [Segment(text=r.description, heading="Abstract / description (from source metadata)")]
        return finalize(res)
    return None


def process(session: Session, r: Resource, claude_ocr: OcrFn | None = None) -> str:
    """Extract, chunk, classify and index one resource. Returns processing status."""
    try:
        res = _load_extract(session, r, claude_ocr)
    except ExtractionError as e:
        r.processing_status = "failed"
        r.last_error = str(e)
        _index_metadata_only(session, r)
        return r.processing_status
    session.execute(delete(Chunk).where(Chunk.resource_id == r.id))
    fts.remove_resource(session, r.id)
    session.flush()
    if res is None or not res.full_text.strip():
        if res is not None and res.ocr_pages:
            r.processing_status = "needs_ocr"
            r.last_error = (f"{len(res.ocr_pages)} scanned page(s) without a text layer. Install Tesseract "
                            "(see docs) or enable Claude OCR.")
        else:
            r.processing_status = "metadata_only"
        _index_metadata_only(session, r)
        return r.processing_status
    # fill metadata from the document itself when the record lacks it
    if res.title and (not r.title or r.title in ("(untitled)",) or (r.extra or {}).get("title_from_filename")):
        r.title = res.title.strip()[:2000]
        r.title_key = title_key(r.title) or None
        extra = dict(r.extra or {})
        extra.pop("title_from_filename", None)
        r.extra = extra
    if res.authors and not r.authors_text:
        r.authors_text = "; ".join(res.authors)
    if res.description and not r.description:
        r.description = res.description
    if res.published and not r.published_date:
        r.published_date = res.published
        if res.published[:4].isdigit():
            r.year = int(res.published[:4])
    if res.license_hint and not r.license:
        r.license = res.license_hint[:200]
    r.language = res.language or r.language or detect_language(r.title)
    if res.method != "abstract":
        r.page_count = res.page_count
        r.word_count = res.word_count
    r.extraction_method = res.method
    q = text_quality(res.full_text)
    r.extraction_quality = q
    quality = dict(r.quality or {})
    quality["extraction"] = {"score": q, "method": res.method, "ocr_pages_remaining": len(res.ocr_pages),
                             "note": "heuristic indicator, not an objective measure"}
    r.quality = quality
    # keep the full original text on disk
    cfg = get_config()
    tp = cfg.text_dir / f"{r.id // 1000:03d}" / f"{r.id}.txt"
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text(res.full_text, encoding="utf-8")
    r.text_path = relative(tp)
    chunks = []
    for i, c in enumerate(chunk_segments(res.segments)):
        ch = Chunk(resource_id=r.id, seq=i, page_start=c["page"], page_end=c["page"], heading=c["heading"],
                   text=c["text"], lang=detect_language(c["text"]), timestamp_start=c["timestamp"])
        session.add(ch)
        chunks.append(ch)
    session.flush()
    fts.index_chunks(session, chunks)
    cl = classify_text(session, r.title, r.description or "", res.full_text, r.keywords)
    apply_classification(session, r, cl)
    fts.index_resource(session, r)
    if res.links:
        extra = dict(r.extra or {})
        extra["outlinks"] = [lk["url"] for lk in res.links if lk.get("url", "").startswith("http")][:300]
        r.extra = extra
    r.index_status = "indexed"
    r.processed_at = utcnow()
    if res.method == "abstract":
        r.processing_status = "metadata_only"
    elif res.ocr_pages:
        r.processing_status = "needs_ocr"
    elif q < 0.55:
        r.processing_status = "low_quality"
    else:
        r.processing_status = "extracted"
    r.last_error = None
    return r.processing_status


def _index_metadata_only(session: Session, r: Resource) -> None:
    cl = classify_text(session, r.title, r.description or "", "", r.keywords)
    apply_classification(session, r, cl)
    fts.index_resource(session, r)
    r.index_status = "indexed"
    r.processed_at = utcnow()
