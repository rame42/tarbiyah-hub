"""General-purpose website crawler (Arabic and English sites).

Per-site configuration (Source.config):
  start_urls:        ["https://example.org/articles"]
  allowed_domains:   ["example.org"]            (default: domains of start_urls)
  include_patterns:  [regex...]   URLs to follow (default: everything on allowed domains)
  exclude_patterns:  [regex...]   URLs never to fetch
  content_patterns:  [regex...]   URLs that are content pages to save (default: any page with enough text)
  max_pages:         pages fetched per run (default from settings)
  max_depth:         link depth from start URLs
  use_sitemap:       read robots.txt Sitemap: lines and /sitemap.xml
  recrawl_hours:     revisit already-fetched content pages after this many hours (update detection)
  min_text_chars:    minimum extracted text for a page to be saved as a resource
  resource_type:     type given to saved pages (article, web_page, institution_page, course...)
  download_documents: true ONLY if you have permission to store this site's files (PDF/EPUB/DOCX)
  render_js:         use Playwright for JavaScript-heavy sites (optional dependency)
  language:          hint when pages do not declare one

The frontier lives in the crawl_urls table, so an interrupted crawl resumes where it
stopped and later runs only fetch new or changed pages (ETag / Last-Modified / content hash).
"""
from __future__ import annotations

import hashlib
import re
from datetime import timedelta
from typing import Any, Iterator
from urllib.parse import urldefrag, urljoin, urlsplit

from lxml import etree
from sqlalchemy import select

from ..db import utcnow
from ..http import FetchError, RobotsDisallowed, http
from ..ingest.extract import extract_html, finalize
from ..ingest.licensing import decide
from ..ingest.registry import ResourceIn, canonical_url, url_hash
from ..models import CrawlUrl
from ..settings import get_setting
from .base import AdapterInfo, CollectContext, SourceAdapter

DOC_EXT = (".pdf", ".epub", ".docx")
SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".svg", ".webp", ".mp3", ".mp4", ".zip", ".rar", ".css", ".js",
            ".ico", ".woff", ".woff2", ".ttf", ".xml", ".json", ".avi", ".mov", ".exe", ".apk")


def _domain(url: str) -> str:
    h = (urlsplit(url).hostname or "").lower()  # hostname: no port, no credentials
    return h[4:] if h.startswith("www.") else h


def _in_domains(url: str, domains: list[str]) -> bool:
    d = _domain(url)
    return any(d == x or d.endswith("." + x) for x in domains)


def render_with_playwright(url: str, timeout_ms: int = 30000) -> str:
    """Render a JavaScript page. Requires `pip install playwright` + `playwright install chromium`."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        try:
            page = browser.new_page(user_agent=http().user_agent)
            page.goto(url, timeout=timeout_ms, wait_until="networkidle")
            return page.content()
        finally:
            browser.close()


def parse_sitemap(xml: bytes) -> tuple[list[str], list[str]]:
    """Return (page_urls, child_sitemaps)."""
    try:
        root = etree.fromstring(xml, parser=etree.XMLParser(recover=True, resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError:
        return [], []
    if root is None:
        return [], []
    tag = etree.QName(root).localname
    locs = [el.text.strip() for el in root.iter() if etree.QName(el).localname == "loc" and el.text]
    return ([], locs) if tag == "sitemapindex" else (locs, [])


class WebCrawlerAdapter(SourceAdapter):
    info = AdapterInfo(
        name="web_crawler", label="Website crawler", kind="web",
        description="Crawls a registered website (Arabic or English): sitemaps, pagination, articles, "
                    "institution pages and document links, with incremental re-crawls.",
        capabilities=("monitor", "crawl"),
        resource_types=("article", "web_page", "institution_page", "course", "book", "paper"),
        access_notes="Obeys robots.txt and per-site rate limits. Documents are stored only when the site "
                     "declares an open licence or you set download_documents=true for a site you have permission for.",
        default_schedule_minutes=1440, min_interval_seconds=2.0, required_config=("start_urls",),
        config_fields={
            "start_urls": "List of starting URLs", "allowed_domains": "Domains to stay within",
            "include_patterns": "Regex list of URLs to follow", "exclude_patterns": "Regex list of URLs to skip",
            "content_patterns": "Regex list of URLs that are content pages", "max_pages": "Pages per run",
            "max_depth": "Link depth", "use_sitemap": "Read sitemaps (true/false)",
            "recrawl_hours": "Revisit fetched pages after N hours", "min_text_chars": "Minimum text to save a page",
            "resource_type": "Type for saved pages", "download_documents": "Permission to store site files",
            "render_js": "Render with Playwright", "language": "Language hint",
            "only_courses": "Keep only course pages (for course catalogues: true/false)",
        },
        default_config={"start_urls": [], "max_depth": 3, "use_sitemap": True, "recrawl_hours": 168,
                        "min_text_chars": 400, "resource_type": "article", "download_documents": False,
                        "render_js": False},
    )

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        raise NotImplementedError("The crawler monitors registered sites; it is not a search engine.")

    # ------------------------------------------------------------------ frontier helpers
    def _add(self, ctx: CollectContext, url: str, depth: int) -> bool:
        s = ctx.session
        url = urldefrag(url)[0]
        key = url_hash(url)
        exists = s.execute(select(CrawlUrl.id).where(CrawlUrl.source_id == ctx.source_id,
                                                     CrawlUrl.url_key == key)).first()
        if exists:
            return False
        s.add(CrawlUrl(source_id=ctx.source_id, url=url, url_key=key, depth=depth, status="pending"))
        s.flush()
        return True

    def _allowed(self, url: str, cfg: dict[str, Any], domains: list[str]) -> bool:
        if not url.startswith(("http://", "https://")):
            return False
        path = urlsplit(url).path.lower()
        if path.endswith(SKIP_EXT):
            return False
        if not _in_domains(url, domains):
            return False
        for pat in cfg.get("exclude_patterns") or []:
            if re.search(pat, url):
                return False
        inc = cfg.get("include_patterns") or []
        if inc and not path.endswith(DOC_EXT) and not any(re.search(p, url) for p in inc):
            return False
        return True

    def _is_content(self, url: str, cfg: dict[str, Any]) -> bool:
        pats = cfg.get("content_patterns") or []
        return True if not pats else any(re.search(p, url) for p in pats)

    def _seed(self, ctx: CollectContext, cfg: dict[str, Any], domains: list[str]) -> None:
        for u in cfg.get("start_urls") or []:
            self._add(ctx, u, 0)
            # start pages are listing pages: always revisit them to discover new links
            row = ctx.session.execute(select(CrawlUrl).where(CrawlUrl.source_id == ctx.source_id,
                                                             CrawlUrl.url_key == url_hash(u))).scalars().first()
            if row and row.status != "pending":
                row.status = "pending"
        if cfg.get("use_sitemap", True) and not ctx.checkpoint.get("sitemap_done_at_run"):
            self._seed_sitemaps(ctx, cfg, domains)

    def _seed_sitemaps(self, ctx: CollectContext, cfg: dict[str, Any], domains: list[str]) -> None:
        seen: set[str] = set()
        queue: list[str] = []
        for u in cfg.get("start_urls") or []:
            parts = urlsplit(u)
            base = f"{parts.scheme}://{parts.netloc}"
            try:
                robots = http().fetch(base + "/robots.txt", check_robots=False, max_bytes=500_000)
                queue += [ln.split(":", 1)[1].strip() for ln in robots.text.splitlines()
                          if ln.lower().startswith("sitemap:")]
            except FetchError:
                pass
            queue.append(base + "/sitemap.xml")
        added = 0
        max_urls = int(cfg.get("max_sitemap_urls", 5000))
        while queue and len(seen) < 50 and added < max_urls:
            sm = queue.pop(0)
            if sm in seen:
                continue
            seen.add(sm)
            try:
                res = http().fetch(sm, max_bytes=20_000_000)
            except (FetchError, RobotsDisallowed):
                continue
            pages, children = parse_sitemap(res.content)
            queue += children
            for p in pages:
                if added >= max_urls:
                    break
                if self._allowed(p, cfg, domains) and self._add(ctx, p, 1):
                    added += 1
        ctx.log(f"sitemaps read: {len(seen)}, new URLs: {added}")

    # ------------------------------------------------------------------ crawl
    def collect(self, ctx: CollectContext) -> Iterator[ResourceIn]:
        cfg = {**self.info.default_config, **(ctx.source_config or {})}
        if not cfg.get("start_urls"):
            raise ValueError('This Website crawler source has no website address. Edit it on the Sources page and set '
                             '"start_urls", e.g. {"start_urls": ["https://example.org/articles"]}. If you meant to '
                             'add an Apify scraper, delete this source and add a new one with type "Apify Actor".')
        domains = cfg.get("allowed_domains") or sorted({_domain(u) for u in cfg["start_urls"]})
        max_pages = int(cfg.get("max_pages") or get_setting("crawler_default_max_pages"))
        max_depth = int(cfg.get("max_depth") or get_setting("crawler_default_max_depth"))
        recrawl = timedelta(hours=float(cfg.get("recrawl_hours") or 168))
        min_chars = int(cfg.get("min_text_chars") or 400)
        s = ctx.session
        if not ctx.checkpoint.get("seeded"):
            self._seed(ctx, cfg, domains)
            ctx.save_checkpoint({**ctx.checkpoint, "seeded": True, "fetched": 0})
        # due for revisit: content pages older than recrawl window
        cutoff = utcnow() - recrawl
        for row in s.execute(select(CrawlUrl).where(CrawlUrl.source_id == ctx.source_id, CrawlUrl.status == "done",
                                                    CrawlUrl.last_fetched_at < cutoff).limit(max_pages)).scalars():
            row.status = "pending"
        fetched = int(ctx.checkpoint.get("fetched", 0))
        while fetched < max_pages and not ctx.should_stop():
            row = s.execute(select(CrawlUrl).where(CrawlUrl.source_id == ctx.source_id, CrawlUrl.status == "pending")
                            .order_by(CrawlUrl.depth, CrawlUrl.id).limit(1)).scalars().first()
            if row is None:
                break
            fetched += 1
            ctx.commit()  # never hold the write lock while waiting on the network
            yield from self._visit(ctx, row, cfg, domains, max_depth, min_chars)
            if fetched % 10 == 0:
                ctx.save_checkpoint({**ctx.checkpoint, "seeded": True, "fetched": fetched})
        ctx.save_checkpoint({})  # run finished: next run starts fresh (frontier persists in the table)

    def _visit(self, ctx: CollectContext, row: CrawlUrl, cfg: dict[str, Any], domains: list[str],
               max_depth: int, min_chars: int) -> Iterator[ResourceIn]:
        url = row.url
        path = urlsplit(url).path.lower()
        if path.endswith(DOC_EXT):
            row.status = "done"
            row.last_fetched_at = utcnow()
            yield self._document(url, cfg, ctx, None, None)
            return
        try:
            res = http().fetch(url, etag=row.etag, last_modified=row.last_modified,
                               min_interval=float(cfg.get("min_interval_seconds", self.info.min_interval_seconds)),
                               max_bytes=8_000_000)
        except RobotsDisallowed:
            row.status = "blocked"
            return
        except FetchError as e:
            row.status = "error" if not e.transient else "pending"
            row.http_status = e.status
            row.last_fetched_at = utcnow()
            if e.transient:
                raise
            return
        row.last_fetched_at = utcnow()
        row.http_status = res.status
        row.etag = res.headers.get("etag")
        row.last_modified = res.headers.get("last-modified")
        if res.not_modified:
            row.status = "done"
            return
        ctype = res.content_type
        if ctype in ("application/pdf", "application/epub+zip") or res.content[:4] == b"%PDF":
            row.status = "done"
            yield self._document(res.final_url, cfg, ctx, None, None)
            return
        if "html" not in ctype and ctype not in ("", "text/plain"):
            row.status = "skipped"
            return
        html_bytes = res.content
        if cfg.get("render_js"):
            try:
                html_bytes = render_with_playwright(url).encode("utf-8")
            except ImportError:
                ctx.log("render_js requested but Playwright is not installed; using static HTML")
            except Exception as e:  # noqa: BLE001
                ctx.log(f"Playwright render failed for {url}: {e}")
        ex = finalize(extract_html(html_bytes, res.final_url))
        new_hash = hashlib.sha256(ex.full_text.encode("utf-8")).hexdigest()
        changed = row.content_hash is not None and row.content_hash != new_hash
        first_time = row.content_hash is None
        row.content_hash = new_hash
        row.status = "done"
        # links
        if row.depth < max_depth:
            for link in ex.links:
                href = urljoin(res.final_url, link.get("url", ""))
                href = urldefrag(href)[0]
                low = urlsplit(href).path.lower()
                if low.endswith(DOC_EXT) and _in_domains(href, domains):
                    if self._add(ctx, href, row.depth + 1):
                        pass
                elif self._allowed(href, cfg, domains):
                    self._add(ctx, href, row.depth + 1)
        from ..ingest.courses import course_access, course_from_html

        course = course_from_html(html_bytes, res.final_url)
        if cfg.get("only_courses") and not course:
            return  # course catalogues: keep only the course pages (links are still followed)
        is_start = canonical_url(url) in {canonical_url(u) for u in cfg.get("start_urls") or []}
        if not course and (is_start or not self._is_content(url, cfg) or len(ex.full_text) < min_chars):
            return
        if not (first_time or changed):
            return
        lang = cfg.get("language") or ex.language
        d = ResourceIn(
            title=ex.title or url,
            resource_type=cfg.get("resource_type", "article"),
            url=res.final_url,
            authors=ex.authors,
            description=ex.description,
            language=lang if lang not in ("und",) else None,
            published_date=ex.published,
            year=int(ex.published[:4]) if ex.published and ex.published[:4].isdigit() else None,
            publisher=ex.meta.get("sitename") or _domain(url),
            source_key=ctx.source_key,
            source_id=ctx.source_id,
            collection_method="scrape:" + ("playwright" if cfg.get("render_js") else "static"),
            license=ex.license_hint,
            access=decide(ex.license_hint),
            text=ex.full_text,
            extra={"crawl_depth": row.depth, "updated_content": changed, "content_hash": new_hash,
                   "inline_method": "trafilatura"},
        )
        if course:
            d.resource_type, d.title = "course", course["title"]
            d.description = course.get("description") or d.description
            d.publisher = course.get("provider") or d.publisher
            d.access = course_access(course)
            if not course.get("free"):
                d.price, d.currency = course.get("price"), course.get("currency")
                d.purchase_url = course.get("offer_url") or res.final_url
            d.extra["course"] = {k: course.get(k) for k in ("provider", "free", "price", "currency")}
        yield d

    def _document(self, url: str, cfg: dict[str, Any], ctx: CollectContext, title: str | None,
                  license_hint: str | None) -> ResourceIn:
        name = urlsplit(url).path.rsplit("/", 1)[-1] or url
        permitted = bool(cfg.get("download_documents"))
        access = decide(license_hint, site_permission=permitted)
        ext = name.lower().rsplit(".", 1)[-1] if "." in name else ""
        return ResourceIn(
            title=title or re.sub(r"[_\-]+", " ", name.rsplit(".", 1)[0]) or url,
            resource_type=cfg.get("document_type", "document"),
            url=url,
            download_url=url if access.download_permitted else None,
            source_key=ctx.source_key,
            source_id=ctx.source_id,
            collection_method="scrape:document_link",
            access=access,
            language=cfg.get("language"),
            extra={"format": ext, "title_from_filename": True},
        )
