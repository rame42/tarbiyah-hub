"""Book discovery and legal acquisition adapters.

- Internet Archive: downloads only items with a public-domain / Creative Commons
  licence URL. Lending-library items ("inlibrary", "printdisabled"...) are catalogued
  as lending_only. Items with no rights information are metadata + link only.
- Open Library: catalogue; 'public' scans resolve through Internet Archive.
- Project Gutenberg (via Gutendex): public domain in the USA.
- Google Books: bibliographic catalogue incl. paid books (price + buy link);
  public-domain volumes may be downloadable.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import quote

from ..http import http
from ..ingest.licensing import decide
from ..ingest.registry import ResourceIn
from .base import AdapterInfo, SourceAdapter, as_year, first

LENDING_COLLECTIONS = {"inlibrary", "printdisabled", "lendinglibrary", "internetarchivebooks", "browserlending",
                       "americana_lending"}
IA_LANG = {"arabic": "ar", "ara": "ar", "english": "en", "eng": "en"}


class InternetArchiveAdapter(SourceAdapter):
    info = AdapterInfo(
        name="internet_archive", label="Internet Archive", kind="books",
        description="Digitized books, manuscripts and audio. Includes many Arabic and classical texts.",
        capabilities=("search",), resource_types=("book", "manuscript", "audio"),
        access_notes="Only items with a public-domain or Creative Commons licence are downloaded. Lending-library "
                     "books are catalogued as 'lending only'. Uploads without rights information are not downloaded.",
        default_enabled=True, min_interval_seconds=1.5,
    )
    SEARCH = "https://archive.org/advancedsearch.php"
    FIELDS = ["identifier", "title", "creator", "date", "year", "language", "licenseurl", "rights", "collection",
              "description", "mediatype", "subject", "publisher"]

    def parse(self, d: dict[str, Any]) -> ResourceIn:
        ident = d.get("identifier")
        colls = d.get("collection") or []
        colls = [colls] if isinstance(colls, str) else colls
        lic = d.get("licenseurl")
        lending = any(c in LENDING_COLLECTIONS for c in colls)
        pd = bool(lic and "publicdomain" in lic.lower())
        access = decide(lic, public_domain=pd, lending_only=lending and not lic)
        lang_raw = first(d.get("language"))
        lang = IA_LANG.get(str(lang_raw).lower(), None) if lang_raw else None
        creators = d.get("creator") or []
        creators = [creators] if isinstance(creators, str) else creators
        desc = d.get("description")
        desc = " ".join(desc) if isinstance(desc, list) else desc
        mediatype = d.get("mediatype") or "texts"
        rtype = {"texts": "book", "audio": "audio", "movies": "video"}.get(mediatype, "other")
        return ResourceIn(
            title=first(d.get("title")) or ident or "(untitled)",
            resource_type=rtype,
            url=f"https://archive.org/details/{ident}",
            download_url=f"https://archive.org/metadata/{ident}" if access.download_permitted else None,
            authors=creators[:10],
            description=(desc or "")[:5000] or None,
            language=lang,
            year=as_year(d.get("year") or d.get("date")),
            publisher=first(d.get("publisher")),
            external_id=ident,
            source_key="internet_archive",
            collection_method="api",
            license=lic or d.get("rights"),
            license_url=lic,
            access=access,
            keywords=(d.get("subject") if isinstance(d.get("subject"), list) else [d.get("subject")] if d.get("subject") else [])[:10],
            extra={"resolver": "internet_archive", "collections": colls, "rights": d.get("rights")},
        )

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        q = f"({query}) AND mediatype:(texts OR audio)"
        if lang == "ar":
            q += " AND language:(Arabic OR ara)"
        elif lang == "en":
            q += " AND language:(English OR eng)"
        params: list[tuple[str, Any]] = [("q", q), ("rows", min(limit, 50)), ("output", "json")]
        params += [("fl[]", f) for f in self.FIELDS]
        data = http().get_json(self.SEARCH, params=params, min_interval=self.info.min_interval_seconds)
        return [self.parse(d) for d in (data.get("response") or {}).get("docs", [])]

    @staticmethod
    def resolve_download(identifier: str) -> tuple[str, str] | None:
        """Pick the best file of an item: PDF > EPUB > plain text. Returns (url, format)."""
        meta = http().get_json(f"https://archive.org/metadata/{quote(identifier)}")
        files = meta.get("files") or []
        prefs = [("Text PDF", "pdf"), ("PDF", "pdf"), ("EPUB", "epub"), ("DjVuTXT", "txt")]
        for fmt, kind in prefs:
            for f in files:
                if f.get("format") == fmt and f.get("name"):
                    return f"https://archive.org/download/{quote(identifier)}/{quote(f['name'])}", kind
        return None


class OpenLibraryAdapter(SourceAdapter):
    info = AdapterInfo(
        name="openlibrary", label="Open Library", kind="books",
        description="Open catalogue of books (editions, ISBNs, subjects) linked to Internet Archive scans.",
        capabilities=("search",), resource_types=("book",),
        access_notes="Catalogue metadata. Only 'public' scans are downloaded; borrowable books are lending-only.",
        default_enabled=True, min_interval_seconds=1.0,
    )
    BASE = "https://openlibrary.org/search.json"

    def parse(self, d: dict[str, Any]) -> ResourceIn:
        ebook = d.get("ebook_access") or "no_ebook"
        ia = first(d.get("ia"))
        public = ebook == "public" and bool(ia)
        access = decide(None, public_domain=public, lending_only=ebook in ("borrowable", "printdisabled"))
        langs = d.get("language") or []
        lang = "ar" if "ara" in langs else ("en" if "eng" in langs else None)
        return ResourceIn(
            title=d.get("title") or "(untitled)",
            alt_titles=[d["subtitle"]] if d.get("subtitle") else [],
            resource_type="book",
            url=f"https://openlibrary.org{d.get('key')}" if d.get("key") else None,
            download_url=f"https://archive.org/metadata/{ia}" if public else None,
            authors=d.get("author_name") or [],
            language=lang,
            year=d.get("first_publish_year"),
            publisher=first(d.get("publisher")),
            isbn=first(d.get("isbn")),
            external_id=d.get("key"),
            source_key="openlibrary",
            collection_method="api",
            access=access,
            keywords=(d.get("subject") or [])[:10],
            extra={"resolver": "internet_archive" if public else None, "ia_identifier": ia, "ebook_access": ebook,
                   "edition_count": d.get("edition_count")},
        )

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        params: dict[str, Any] = {"q": query, "limit": min(limit, 50),
                                  "fields": "key,title,subtitle,author_name,first_publish_year,language,isbn,"
                                            "ebook_access,ia,publisher,subject,edition_count"}
        if lang == "ar":
            params["language"] = "ara"
        data = http().get_json(self.BASE, params=params, min_interval=self.info.min_interval_seconds)
        return [self.parse(d) for d in data.get("docs", [])]


class GutendexAdapter(SourceAdapter):
    info = AdapterInfo(
        name="gutenberg", label="Project Gutenberg (Gutendex)", kind="books",
        description="Public-domain e-books (mostly older English works; some Arabic).",
        capabilities=("search",), resource_types=("book",),
        access_notes="Works are public domain in the USA; check the copyright law of your country before reuse.",
        default_enabled=True, min_interval_seconds=2.0,
    )
    BASE = "https://gutendex.com/books/"

    def parse(self, b: dict[str, Any]) -> ResourceIn:
        fmts = b.get("formats") or {}
        url = fmts.get("application/epub+zip") or next((u for m, u in fmts.items() if m.startswith("text/plain")), None)
        pd = b.get("copyright") is False
        access = decide("Public domain in the USA" if pd else None, public_domain=pd)
        langs = b.get("languages") or []
        return ResourceIn(
            title=b.get("title") or "(untitled)",
            resource_type="book",
            url=f"https://www.gutenberg.org/ebooks/{b.get('id')}",
            download_url=url if access.download_permitted else None,
            authors=[a.get("name") for a in (b.get("authors") or []) if a.get("name")],
            language=first(langs),
            external_id=str(b.get("id")),
            source_key="gutenberg",
            collection_method="api",
            license="Public domain in the USA" if pd else None,
            access=access,
            keywords=(b.get("subjects") or [])[:10],
            extra={"format": "epub" if url and "epub" in url else "txt", "download_count": b.get("download_count")},
        )

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        params = {"search": query}
        if lang in ("ar", "en"):
            params["languages"] = lang
        data = http().get_json(self.BASE, params=params, min_interval=self.info.min_interval_seconds)
        return [self.parse(b) for b in data.get("results", [])][:limit]


class GoogleBooksAdapter(SourceAdapter):
    info = AdapterInfo(
        name="google_books", label="Google Books (catalogue & paid books)", kind="catalog",
        description="Bibliographic catalogue incl. Arabic books; records prices and authorized purchase links.",
        capabilities=("search",), resource_types=("book",),
        access_notes="Free for modest volumes without a key. Paid books are catalogued with price and buy link only; "
                     "nothing is purchased automatically.",
        default_enabled=True, min_interval_seconds=1.5,
    )
    BASE = "https://www.googleapis.com/books/v1/volumes"

    def parse(self, it: dict[str, Any]) -> ResourceIn:
        v = it.get("volumeInfo") or {}
        sale = it.get("saleInfo") or {}
        acc = it.get("accessInfo") or {}
        pd = bool(acc.get("publicDomain"))
        dl = ((acc.get("pdf") or {}).get("downloadLink")) or ((acc.get("epub") or {}).get("downloadLink"))
        paid = sale.get("saleability") == "FOR_SALE"
        access = decide(None, public_domain=pd and bool(dl), paid=paid)
        price = sale.get("retailPrice") or sale.get("listPrice") or {}
        isbn = next((i.get("identifier") for i in (v.get("industryIdentifiers") or [])
                     if i.get("type") in ("ISBN_13", "ISBN_10")), None)
        return ResourceIn(
            title=v.get("title") or "(untitled)",
            alt_titles=[v["subtitle"]] if v.get("subtitle") else [],
            resource_type="book",
            url=v.get("infoLink") or v.get("canonicalVolumeLink"),
            download_url=dl if access.download_permitted else None,
            authors=v.get("authors") or [],
            description=v.get("description"),
            language=v.get("language"),
            published_date=v.get("publishedDate"),
            year=as_year(v.get("publishedDate")),
            publisher=v.get("publisher"),
            isbn=isbn,
            external_id=it.get("id"),
            source_key="google_books",
            collection_method="api",
            access=access,
            price=str(price.get("amount")) if price.get("amount") is not None else None,
            currency=price.get("currencyCode"),
            purchase_url=sale.get("buyLink"),
            keywords=(v.get("categories") or [])[:6],
            extra={"saleability": sale.get("saleability"), "preview": v.get("previewLink"),
                   "viewability": acc.get("viewability"), "page_count": v.get("pageCount")},
        )

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        params: dict[str, Any] = {"q": query, "maxResults": min(limit, 40), "printType": "books"}
        if lang in ("ar", "en"):
            params["langRestrict"] = lang
        data = http().get_json(self.BASE, params=params, min_interval=self.info.min_interval_seconds)
        return [self.parse(i) for i in data.get("items", []) or []]
