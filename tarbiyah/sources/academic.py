"""Academic discovery adapters: OpenAlex, Crossref, DOAJ, ERIC, CORE.

All are free to query. Files are downloaded only when an open licence is reported
(see ingest.licensing); otherwise the record keeps the DOI / landing page link.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from ..config import get_config
from ..http import FetchError, http
from ..ingest.licensing import AccessDecision, decide
from ..ingest.registry import ResourceIn
from ..settings import get_setting
from .base import AdapterInfo, SourceAdapter, as_year, first

log = logging.getLogger(__name__)

TYPE_MAP = {
    "article": "paper", "journal-article": "paper", "book": "book", "monograph": "book", "edited-book": "book",
    "book-chapter": "book_chapter", "dissertation": "thesis", "report": "report", "proceedings-article": "paper",
    "posted-content": "paper", "preprint": "paper", "review": "paper", "dataset": "dataset", "other": "other",
}


def _strip_tags(s: str | None) -> str | None:
    if not s:
        return s
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s)).strip()


def _allow_ftr() -> bool:
    return bool(get_setting("download_free_to_read"))


# ---------------------------------------------------------------------------- OpenAlex

def openalex_abstract(inv: dict[str, list[int]] | None) -> str | None:
    if not inv:
        return None
    pos: dict[int, str] = {}
    for word, idxs in inv.items():
        for i in idxs:
            pos[i] = word
    return " ".join(pos[i] for i in sorted(pos)) or None


class OpenAlexAdapter(SourceAdapter):
    info = AdapterInfo(
        name="openalex", label="OpenAlex", kind="academic",
        description="Open index of 250M+ scholarly works (papers, books, theses) with open-access links.",
        capabilities=("search",), resource_types=("paper", "book", "thesis", "report"),
        access_notes="Free API, no key. Set TH_CONTACT_EMAIL to join the polite pool.",
        default_enabled=True, min_interval_seconds=0.5,
    )
    BASE = "https://api.openalex.org/works"

    def parse(self, w: dict[str, Any]) -> ResourceIn:
        best = w.get("best_oa_location") or {}
        prim = w.get("primary_location") or {}
        oa = w.get("open_access") or {}
        lic = best.get("license") or prim.get("license")
        pdf = best.get("pdf_url") or prim.get("pdf_url")
        access = decide(lic, open_access=bool(oa.get("is_oa")), oa_status=oa.get("oa_status"),
                        allow_free_to_read=_allow_ftr())
        venue = ((prim.get("source") or {}).get("display_name")) or None
        authors = [((a.get("author") or {}).get("display_name")) for a in (w.get("authorships") or [])]
        institutions = sorted({i.get("display_name") for a in (w.get("authorships") or [])
                               for i in (a.get("institutions") or []) if i.get("display_name")})
        kws = [k.get("display_name") for k in (w.get("keywords") or []) if k.get("display_name")]
        return ResourceIn(
            title=w.get("display_name") or w.get("title") or "(untitled)",
            resource_type=TYPE_MAP.get(w.get("type") or "", "paper"),
            url=prim.get("landing_page_url") or w.get("doi") or w.get("id"),
            download_url=pdf if access.download_permitted else None,
            authors=[a for a in authors if a],
            description=openalex_abstract(w.get("abstract_inverted_index")),
            language=w.get("language"),
            published_date=w.get("publication_date"),
            year=w.get("publication_year"),
            publisher=venue,
            doi=w.get("doi"),
            external_id=(w.get("id") or "").rsplit("/", 1)[-1] or None,
            source_key="openalex",
            collection_method="api",
            license=lic,
            access=access,
            keywords=kws[:15],
            extra={"oa_status": oa.get("oa_status"), "oa_url": oa.get("oa_url"), "pdf_url": pdf,
                   "institutions": institutions[:20], "venue": venue, "format": "pdf" if pdf else None,
                   "referenced_works": (w.get("referenced_works") or [])[:200],
                   "cited_by_count": w.get("cited_by_count")},
        )

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        params: dict[str, Any] = {"search": query, "per-page": min(limit, 50)}
        if lang in ("ar", "en"):
            params["filter"] = f"language:{lang}"
        if get_config().contact_email:
            params["mailto"] = get_config().contact_email
        data = http().get_json(self.BASE, params=params, min_interval=self.info.min_interval_seconds, check_robots=False)
        return [self.parse(w) for w in data.get("results", [])]

    def fetch_works(self, ids: list[str]) -> list[ResourceIn]:
        """Resolve OpenAlex work ids (used to collect works cited by collected resources)."""
        short = [i.rsplit("/", 1)[-1] for i in ids][:50]
        if not short:
            return []
        params = {"filter": "openalex:" + "|".join(short), "per-page": 50}
        data = http().get_json(self.BASE, params=params, min_interval=self.info.min_interval_seconds, check_robots=False)
        return [self.parse(w) for w in data.get("results", [])]


# ---------------------------------------------------------------------------- Crossref

class CrossrefAdapter(SourceAdapter):
    info = AdapterInfo(
        name="crossref", label="Crossref", kind="academic",
        description="DOI registration metadata for journal articles, books and reports.",
        capabilities=("search",), resource_types=("paper", "book", "report"),
        access_notes="Free REST API, no key. Metadata only unless a CC licence and a PDF link are listed.",
        default_enabled=True, min_interval_seconds=1.0,
    )
    BASE = "https://api.crossref.org/works"

    def parse(self, it: dict[str, Any]) -> ResourceIn:
        dp = ((it.get("issued") or it.get("published") or {}).get("date-parts") or [[None]])[0]
        year = dp[0] if dp else None
        date = "-".join(f"{p:02d}" if i else str(p) for i, p in enumerate(dp) if p) if dp and dp[0] else None
        authors = []
        for a in it.get("author") or []:
            name = a.get("name") or " ".join(x for x in (a.get("given"), a.get("family")) if x)
            if name:
                authors.append(name)
        lic_urls = [lc.get("URL") for lc in (it.get("license") or []) if lc.get("URL")]
        lic = next((u for u in lic_urls if "creativecommons" in u), first(lic_urls))
        pdf = next((lk.get("URL") for lk in (it.get("link") or [])
                    if (lk.get("content-type") or "").endswith("pdf")), None)
        access = decide(lic, allow_free_to_read=_allow_ftr())
        isbn = first(it.get("ISBN"))
        return ResourceIn(
            title=first(it.get("title")) or "(untitled)",
            alt_titles=[t for t in (it.get("subtitle") or []) if t][:3],
            resource_type=TYPE_MAP.get(it.get("type") or "", "paper"),
            url=it.get("URL"),
            download_url=pdf if access.download_permitted else None,
            authors=authors,
            description=_strip_tags(it.get("abstract")),
            language=it.get("language"),
            published_date=date,
            year=year,
            publisher=it.get("publisher"),
            doi=it.get("DOI"),
            isbn=isbn,
            source_key="crossref",
            collection_method="api",
            license=lic,
            access=access,
            keywords=(it.get("subject") or [])[:10],
            extra={"container": first(it.get("container-title")), "format": "pdf" if pdf else None,
                   "references_count": it.get("references-count")},
        )

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        params: dict[str, Any] = {"query": query, "rows": min(limit, 50)}
        if get_config().contact_email:
            params["mailto"] = get_config().contact_email
        data = http().get_json(self.BASE, params=params, min_interval=self.info.min_interval_seconds, check_robots=False)
        return [self.parse(it) for it in (data.get("message") or {}).get("items", [])]


# ---------------------------------------------------------------------------- DOAJ

class DoajAdapter(SourceAdapter):
    info = AdapterInfo(
        name="doaj", label="DOAJ (Directory of Open Access Journals)", kind="academic",
        description="Articles from peer-reviewed open-access journals, including many Arabic journals.",
        capabilities=("search",), resource_types=("paper",),
        access_notes="Free API, no key. Licences are reported per journal (usually Creative Commons).",
        default_enabled=True, min_interval_seconds=1.0,
    )
    BASE = "https://doaj.org/api/search/articles/"
    BASE_V4 = "https://doaj.org/api/v4/search/articles/"

    def parse(self, item: dict[str, Any]) -> ResourceIn:
        b = item.get("bibjson") or {}
        journal = b.get("journal") or {}
        lic_list = journal.get("license") or b.get("license") or []
        lic = None
        if lic_list:
            l0 = lic_list[0]
            lic = l0.get("type") or l0.get("title") or l0.get("url")
        fulltext = next((lk.get("url") for lk in (b.get("link") or []) if lk.get("type") == "fulltext"), None)
        doi = next((i.get("id") for i in (b.get("identifier") or []) if (i.get("type") or "").lower() == "doi"), None)
        is_pdf = bool(fulltext and fulltext.lower().split("?")[0].endswith(".pdf"))
        access = decide(lic, open_access=True, oa_status="gold", allow_free_to_read=_allow_ftr())
        langs = journal.get("language") or []
        lang = None
        if langs:
            l0 = str(langs[0]).lower()
            lang = {"ar": "ar", "ara": "ar", "arabic": "ar", "en": "en", "eng": "en", "english": "en"}.get(l0, l0[:2])
        return ResourceIn(
            title=b.get("title") or "(untitled)",
            resource_type="paper",
            url=fulltext or (f"https://doi.org/{doi}" if doi else None),
            download_url=fulltext if (access.download_permitted and is_pdf) else None,
            authors=[a.get("name") for a in (b.get("author") or []) if a.get("name")],
            description=_strip_tags(b.get("abstract")),
            language=lang,
            year=as_year(b.get("year")),
            publisher=journal.get("publisher") or journal.get("title"),
            doi=doi,
            external_id=item.get("id"),
            source_key="doaj",
            collection_method="api",
            license=lic,
            access=access,
            keywords=(b.get("keywords") or [])[:10],
            extra={"journal": journal.get("title"), "format": "pdf" if is_pdf else None, "fetch_page": not is_pdf},
        )

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        """DOAJ's own API first. Some networks get HTTP 403 from DOAJ's firewall; then the same DOAJ journals
        are searched through OpenAlex, which indexes every DOAJ journal (filter is_in_doaj)."""
        from urllib.parse import quote

        cfg = get_config()
        headers = {"User-Agent": "TarbiyahHub/0.2 (research library; "
                                 + (f"mailto:{cfg.contact_email})" if cfg.contact_email else "non-commercial)")}
        last: FetchError | None = None
        for base in (self.BASE, self.BASE_V4):
            try:
                data = http().get_json(base + quote(query, safe=""), params={"pageSize": min(limit, 50)},
                                       headers=headers, min_interval=self.info.min_interval_seconds,
                                       check_robots=False)
                return [self.parse(i) for i in data.get("results", [])]
            except FetchError as e:
                if e.status not in (400, 403, 404):
                    raise
                last = e
        log.warning("DOAJ API refused the request (%s); searching DOAJ journals through OpenAlex", last)
        return self.via_openalex(query, lang, limit)

    def via_openalex(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        oa = OpenAlexAdapter()
        flt = "primary_location.source.is_in_doaj:true" + (f",language:{lang}" if lang in ("ar", "en") else "")
        params: dict[str, Any] = {"search": query, "per-page": min(limit, 50), "filter": flt}
        if get_config().contact_email:
            params["mailto"] = get_config().contact_email
        data = http().get_json(oa.BASE, params=params, min_interval=oa.info.min_interval_seconds, check_robots=False)
        out = []
        for w in data.get("results", []):
            d = oa.parse(w)
            d.source_key = "doaj"
            d.extra = {**d.extra, "via": "openalex (DOAJ journal)"}
            out.append(d)
        return out


# ---------------------------------------------------------------------------- ERIC

class EricAdapter(SourceAdapter):
    info = AdapterInfo(
        name="eric", label="ERIC (Education Resources Information Center)", kind="academic",
        description="U.S. Department of Education index of education research, many with free full text.",
        capabilities=("search",), resource_types=("paper", "report", "thesis"),
        access_notes="Free API, no key. Full texts flagged by ERIC as distributable are downloaded.",
        languages=("en",), default_enabled=True, min_interval_seconds=1.0,
    )
    BASE = "https://api.ies.ed.gov/eric/"
    FIELDS = "id,title,author,description,publicationdateyear,publicationtype,subject,language,source,isbn,url,e_fulltextauth,peerreviewed,publisher"

    def parse(self, d: dict[str, Any]) -> ResourceIn:
        eid = d.get("id") or ""
        full = str(d.get("e_fulltextauth", "")) in ("1", "T", "true", "True")
        pdf = f"https://files.eric.ed.gov/fulltext/{eid}.pdf" if (full and eid.startswith("ED")) else None
        if pdf:
            access = AccessDecision("open_access", True,
                                    "ERIC full text that ERIC is authorized to distribute free of charge (e_fulltextauth=1).")
        else:
            access = decide(None)
        ptypes = d.get("publicationtype") or []
        rtype = "thesis" if any("Dissertation" in p for p in ptypes) else ("report" if eid.startswith("ED") else "paper")
        lang = first(d.get("language"))
        return ResourceIn(
            title=d.get("title") or "(untitled)",
            resource_type=rtype,
            url=d.get("url") or f"https://eric.ed.gov/?id={eid}",
            download_url=pdf,
            authors=d.get("author") or [],
            description=d.get("description"),
            language={"English": "en", "Arabic": "ar"}.get(lang or "", None),
            year=as_year(d.get("publicationdateyear")),
            publisher=d.get("publisher") or d.get("source"),
            isbn=first(d.get("isbn")),
            external_id=eid or None,
            source_key="eric",
            collection_method="api",
            access=access,
            keywords=(d.get("subject") or [])[:12],
            extra={"publication_type": ptypes, "peer_reviewed": d.get("peerreviewed"), "format": "pdf" if pdf else None},
        )

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        data = http().get_json(self.BASE, params={"search": query, "format": "json", "rows": min(limit, 50),
                                                   "fields": self.FIELDS},
                               min_interval=self.info.min_interval_seconds, check_robots=False)
        return [self.parse(d) for d in (data.get("response") or {}).get("docs", [])]


# ---------------------------------------------------------------------------- CORE

class CoreAdapter(SourceAdapter):
    info = AdapterInfo(
        name="core", label="CORE (open-access repositories)", kind="academic",
        description="Aggregator of full texts from institutional and subject repositories worldwide.",
        capabilities=("search",), resource_types=("paper", "thesis", "report"),
        credentials=("CORE_API_KEY",),
        access_notes="Free API key from https://core.ac.uk/services/api . Files without an explicit licence are "
                     "linked, not stored, unless 'download_free_to_read' is enabled.",
        min_interval_seconds=2.0,
    )
    BASE = "https://api.core.ac.uk/v3/search/works"

    def parse(self, w: dict[str, Any]) -> ResourceIn:
        lic = w.get("license") or None
        dl = w.get("downloadUrl") or next((lk.get("url") for lk in (w.get("links") or [])
                                           if lk.get("type") == "download"), None)
        access = decide(lic, open_access=True, allow_free_to_read=_allow_ftr())
        lang = (w.get("language") or {}).get("code") if isinstance(w.get("language"), dict) else w.get("language")
        return ResourceIn(
            title=w.get("title") or "(untitled)",
            resource_type="thesis" if (w.get("documentType") or "").lower() == "thesis" else "paper",
            url=first(w.get("sourceFulltextUrls")) or (f"https://core.ac.uk/works/{w.get('id')}" if w.get("id") else None),
            download_url=dl if access.download_permitted else None,
            authors=[a.get("name") for a in (w.get("authors") or []) if a.get("name")],
            description=w.get("abstract"),
            language=lang,
            published_date=w.get("publishedDate"),
            year=w.get("yearPublished"),
            publisher=w.get("publisher"),
            doi=w.get("doi"),
            external_id=str(w.get("id")) if w.get("id") else None,
            source_key="core",
            collection_method="api",
            license=lic,
            access=access,
            extra={"format": "pdf" if dl else None, "download_url_found": dl},
        )

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        self.require()
        q = query if not lang else f"({query}) AND language.code:{lang}"
        data = http().get_json(self.BASE, params={"q": q, "limit": min(limit, 50)},
                               headers={"Authorization": f"Bearer {get_config().core_api_key}"},
                               min_interval=self.info.min_interval_seconds, check_robots=False)
        return [self.parse(w) for w in data.get("results", [])]
