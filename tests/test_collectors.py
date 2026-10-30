"""Collectors against a real bilingual website served over HTTP on localhost, plus
contract tests of the API adapters against response shapes from their public documentation.

NOTE: the API contract tests do not contact OpenAlex/Crossref/etc. (the development
environment had no access to them); they verify parsing and licensing decisions only.
"""
from datetime import timedelta

import pytest

from tarbiyah.db import session_scope, utcnow
from tarbiyah.jobs.scheduler import dispatch_due_sources
from tarbiyah.models import CrawlUrl, Resource, Source

from .conftest import drain


def _sources(site, **over):
    base = site["base"]
    cfg = {
        "site-ar": {"start_urls": [base + "/ar/index.html"], "allowed_domains": ["127.0.0.1"],
                    "include_patterns": ["/ar/", "/docs/"], "language": "ar", "min_interval_seconds": 0.1},
        "site-en": {"start_urls": [base + "/en/index.html"], "allowed_domains": ["127.0.0.1"],
                    "include_patterns": ["/en/", "/docs/"], "download_documents": True, "min_interval_seconds": 0.1},
    }
    with session_scope() as s:
        for src in s.query(Source):
            src.enabled = False
        s.add(Source(key="site-ar", adapter="web_crawler", name="ar", enabled=True, config={"role": "monitor", **cfg["site-ar"], **over}))
        s.add(Source(key="site-en", adapter="web_crawler", name="en", enabled=True, config={"role": "monitor", **cfg["site-en"], **over}))
        s.add(Source(key="podcast", adapter="rss", name="pod", enabled=True,
                     config={"role": "monitor", "feeds": [base + "/feed.xml"], "fetch_full_text": False}))
        s.add(Source(key="tg", adapter="telegram", name="tg", enabled=True,
                     config={"role": "monitor", "channels": ["testchannel"], "base_url": base + "/tg", "max_pages": 1}))


def test_arabic_and_english_sites_feeds_and_telegram(env, site):
    _sources(site)
    assert dispatch_due_sources() == 4
    drain(120, concurrency=3)
    with session_scope() as s:
        ar = s.query(Resource).filter(Resource.source_key == "site-ar", Resource.resource_type == "article").all()
        en = s.query(Resource).filter(Resource.source_key == "site-en", Resource.resource_type == "article").all()
        assert len(ar) == 3 and all(r.language == "ar" for r in ar)
        assert all(r.access_status == "open_license" for r in ar)  # rel=license CC-BY detected on page
        assert len(en) == 2 and all(r.language == "en" for r in en)
        assert all(r.acquisition_status == "text_collected" and r.processing_status == "extracted" for r in ar + en)
        # documents: Arabic site has no permission/licence -> link only; English site permits downloads
        ar_doc = s.query(Resource).filter(Resource.source_key == "site-ar", Resource.resource_type == "document").one()
        assert ar_doc.acquisition_status == "metadata_only" and not ar_doc.local_path
        en_doc = s.query(Resource).filter(Resource.source_key == "site-en", Resource.resource_type == "document").one()
        assert en_doc.acquisition_status == "downloaded" and en_doc.processing_status == "extracted"
        assert en_doc.title.startswith("Positive Parenting")  # title from the PDF, not the file name
        # robots.txt: /private/ is never fetched
        assert not s.query(CrawlUrl).filter(CrawlUrl.url.like("%private%"), CrawlUrl.status == "done").count()
        assert not s.query(Resource).filter(Resource.url.like("%private%")).count()
        # podcast transcript collected with timestamps
        ep = s.query(Resource).filter(Resource.source_key == "podcast", Resource.title.like("Episode 1%")).one()
        assert ep.extra["has_transcript"] and any(c.timestamp_start is not None for c in ep.chunks)
        assert "patience and dialogue" in " ".join(c.text for c in ep.chunks)
        tg = s.query(Resource).filter(Resource.source_key == "tg").all()
        assert len(tg) == 3 and {r.language for r in tg} == {"ar", "en"}
        for key in ("site-ar", "site-en", "podcast", "tg"):
            src = s.query(Source).filter(Source.key == key).one()
            assert src.health == "ok" and src.last_success_at is not None


def test_incremental_recrawl_detects_updates_without_duplicates(env, site):
    _sources(site, recrawl_hours=0.0001)
    dispatch_due_sources()
    drain(120, concurrency=3)
    with session_scope() as s:
        n_before = s.query(Resource).count()
        for src in s.query(Source):
            src.next_run_at = utcnow() - timedelta(seconds=1)
    page = site["root"] / "ar" / "articles" / "qudwa.html"
    original = page.read_text(encoding="utf-8")
    page.write_text(original.replace("القدوة الحسنة أقوى", "القدوة الصالحة أقوى (نسخة محدثة)"), encoding="utf-8")
    try:
        dispatch_due_sources()
        drain(120, concurrency=3)
        with session_scope() as s:
            assert s.query(Resource).count() == n_before  # nothing duplicated
            r = s.query(Resource).filter(Resource.url.like("%qudwa.html")).one()
            assert r.extra.get("content_updated_at")
            assert "نسخة محدثة" in " ".join(c.text for c in r.chunks)  # re-indexed new version
            src = s.query(Source).filter(Source.key == "site-ar").one()
            assert src.last_result["updated"] == 1 and src.last_result["new"] == 0
            tg = s.query(Source).filter(Source.key == "tg").one()
            assert tg.last_result["new"] == 0  # telegram: only messages newer than last run
    finally:
        page.write_text(original, encoding="utf-8")


def test_local_inbox_folder_import(env, fixtures_dir):
    import shutil

    inbox = env / "inbox"
    shutil.copy(fixtures_dir / "framework.docx", inbox / "framework.docx")
    dispatch_due_sources()
    drain(60)
    with session_scope() as s:
        r = s.query(Resource).filter(Resource.source_key == "inbox").one()
        assert r.processing_status == "extracted" and r.access_status == "user_provided"
    assert (inbox / "imported" / "framework.docx").exists()


# ----------------------------------------------------------------------- API adapter contracts

def test_openalex_parsing_and_licence(env):
    from tarbiyah.sources.academic import OpenAlexAdapter

    w = {"id": "https://openalex.org/W1", "doi": "https://doi.org/10.1/x", "display_name": "Parenting styles in Muslim families",
         "publication_year": 2021, "publication_date": "2021-05-01", "language": "en", "type": "article",
         "open_access": {"is_oa": True, "oa_status": "gold"},
         "best_oa_location": {"pdf_url": "https://j.org/x.pdf", "landing_page_url": "https://j.org/x", "license": "cc-by"},
         "primary_location": {"landing_page_url": "https://j.org/x", "source": {"display_name": "J Fam"}},
         "authorships": [{"author": {"display_name": "A. Author"}, "institutions": [{"display_name": "Univ X"}]}],
         "abstract_inverted_index": {"Parents": [0], "matter": [1]}, "referenced_works": ["https://openalex.org/W2"],
         "keywords": [{"display_name": "parenting"}]}
    d = OpenAlexAdapter().parse(w)
    assert d.description == "Parents matter" and d.download_url == "https://j.org/x.pdf" and d.access.download_permitted
    w2 = {**w, "best_oa_location": {"pdf_url": "https://j.org/y.pdf", "license": None}, "open_access": {"is_oa": True, "oa_status": "green"}}
    d2 = OpenAlexAdapter().parse(w2)
    assert not d2.access.download_permitted and d2.download_url is None and d2.access.access_status == "open_access"


def test_crossref_doaj_eric_parsing(env):
    from tarbiyah.sources.academic import CrossrefAdapter, DoajAdapter, EricAdapter

    c = CrossrefAdapter().parse({"DOI": "10.5/abc", "title": ["Teacher training"], "author": [{"given": "S", "family": "Ali"}],
                                 "issued": {"date-parts": [[2019, 3]]}, "type": "journal-article", "publisher": "P",
                                 "abstract": "<jats:p>Abstract text</jats:p>",
                                 "license": [{"URL": "http://creativecommons.org/licenses/by/4.0/"}],
                                 "link": [{"URL": "https://p.org/a.pdf", "content-type": "application/pdf"}]})
    assert c.year == 2019 and c.published_date == "2019-03" and c.description == "Abstract text"
    assert c.authors == ["S Ali"] and c.access.download_permitted and c.download_url == "https://p.org/a.pdf"
    d = DoajAdapter().parse({"id": "x1", "bibjson": {"title": "التربية الأسرية", "year": "2020",
                             "journal": {"title": "مجلة", "language": ["AR"], "license": [{"type": "CC BY-NC"}]},
                             "link": [{"type": "fulltext", "url": "https://j.dz/a.pdf"}],
                             "identifier": [{"type": "doi", "id": "10.9/z"}], "author": [{"name": "أحمد"}]}})
    assert d.language == "ar" and d.access.download_permitted and d.download_url == "https://j.dz/a.pdf"
    e = EricAdapter().parse({"id": "ED123", "title": "Mentoring", "e_fulltextauth": 1, "publicationdateyear": 2018,
                             "author": ["B"], "language": ["English"], "publicationtype": ["Reports - Research"]})
    assert e.download_url == "https://files.eric.ed.gov/fulltext/ED123.pdf" and e.resource_type == "report"
    e2 = EricAdapter().parse({"id": "EJ9", "title": "Journal art", "e_fulltextauth": 0})
    assert e2.download_url is None and not e2.access.download_permitted


def test_book_sources_lending_paid_and_public_domain(env):
    from tarbiyah.sources.books import GoogleBooksAdapter, GutendexAdapter, InternetArchiveAdapter, OpenLibraryAdapter

    ia = InternetArchiveAdapter()
    lending = ia.parse({"identifier": "b1", "title": "Book", "collection": ["inlibrary", "printdisabled"]})
    assert lending.access.access_status == "lending_only" and lending.download_url is None
    pd = ia.parse({"identifier": "b2", "title": "Old", "licenseurl": "http://creativecommons.org/publicdomain/mark/1.0/",
                   "language": "Arabic", "collection": ["opensource"]})
    assert pd.access.download_permitted and pd.language == "ar" and pd.extra["resolver"] == "internet_archive"
    unknown = ia.parse({"identifier": "b3", "title": "Upload without rights", "collection": ["opensource"]})
    assert not unknown.access.download_permitted  # publicly viewable is not a licence
    ol = OpenLibraryAdapter().parse({"key": "/works/OL1W", "title": "T", "ebook_access": "borrowable", "ia": ["x"]})
    assert ol.access.access_status == "lending_only"
    g = GutendexAdapter().parse({"id": 5, "title": "G", "copyright": False, "languages": ["en"],
                                 "formats": {"application/epub+zip": "https://www.gutenberg.org/5.epub"}})
    assert g.access.download_permitted and g.download_url.endswith(".epub")
    paid = GoogleBooksAdapter().parse({"id": "gb1", "volumeInfo": {"title": "تربية الأبناء", "language": "ar",
                                       "industryIdentifiers": [{"type": "ISBN_13", "identifier": "9781234567897"}]},
                                       "saleInfo": {"saleability": "FOR_SALE", "retailPrice": {"amount": 4.99, "currencyCode": "USD"},
                                                    "buyLink": "https://play.google.com/store/books/details?id=gb1"},
                                       "accessInfo": {"publicDomain": False}})
    assert paid.access.access_status == "paid" and paid.price == "4.99" and paid.purchase_url and paid.download_url is None


def test_social_adapters_parsing_and_credentials(env):
    from tarbiyah.sources.base import NotConfigured
    from tarbiyah.sources.social import FacebookAdapter, RedditAdapter, XAdapter
    from tarbiyah.sources.youtube import video_id_from_url

    assert video_id_from_url("https://youtu.be/dQw4w9WgXcQ?t=1") == "dQw4w9WgXcQ"
    r = RedditAdapter()._parse({"id": "a", "name": "t3_a", "title": "Raising kids", "selftext": "How?", "subreddit": "islam",
                                "permalink": "/r/islam/comments/a/x/", "created_utc": 1700000000}, None)
    assert r.url == "https://www.reddit.com/r/islam/comments/a/x/" and r.published_date == "2023-11-14"
    x = XAdapter()._parse({"data": [{"id": "9", "text": "تربية", "author_id": "1", "created_at": "2026-01-01T00:00:00Z"}],
                           "includes": {"users": [{"id": "1", "username": "acc"}]}}, None)
    assert x[0].url == "https://x.com/acc/status/9"
    for adapter in (RedditAdapter(), XAdapter(), FacebookAdapter()):
        assert not adapter.is_configured()
        with pytest.raises(NotConfigured):
            adapter.require()


def test_youtube_channel_validation_and_full_history(env, monkeypatch):
    from tarbiyah.config import get_config
    from tarbiyah.sources import youtube
    from tarbiyah.sources.base import CollectContext

    a = youtube.YouTubeAdapter()
    assert youtube.parse_channel("https://www.youtube.com/channel/UCcCfpDNl1Bi-LopV2noq_pg") == ("id", "UCcCfpDNl1Bi-LopV2noq_pg")
    assert youtube.parse_channel("https://www.youtube.com/@SomeChannel") == ("handle", "@SomeChannel")
    assert youtube.parse_playlist("https://www.youtube.com/playlist?list=PLabcdefghijkl") == "PLabcdefghijkl"
    problems = a.config_problems({"channel_ids": ["UCcCfpDNl1Bi-LopV2noq_pg", "UCcccc...", "@Handle"]})
    assert len(problems) == 2 and "UCcccc..." in problems[0] and "@Handle" in problems[1]

    # with a key: uploads playlist (UC -> UU), newest page, then the back-catalogue in later runs
    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    get_config.cache_clear()
    assert a.config_problems({"channel_ids": ["@Handle"]}) == []
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid: ([], None, False))
    pages = {None: ([f"v{i:010d}" for i in range(0, 50)], "p2"), "p2": ([f"v{i:010d}" for i in range(50, 100)], "p3"),
             "p3": ([f"v{i:010d}" for i in range(100, 130)], None)}
    calls = []

    def fake_api(path, **params):
        calls.append((path, params))
        if path == "channels":
            return {"items": [{"id": "UCcCfpDNl1Bi-LopV2noq_pg"}]}
        assert params["playlistId"] == "UUcCfpDNl1Bi-LopV2noq_pg"
        ids, nxt = pages[params.get("pageToken")]
        return {"items": [{"snippet": {"title": f"Lesson {v}", "channelTitle": "Ch", "publishedAt": "2025-01-01T00:00:00Z"},
                           "contentDetails": {"videoId": v}} for v in ids], **({"nextPageToken": nxt} if nxt else {})}

    monkeypatch.setattr(a, "_api", fake_api)
    state: dict = {}
    cfg = {"channel_ids": ["@Handle"], "max_videos_per_run": 60}
    run1 = list(a.collect(CollectContext(source_config=cfg, checkpoint={}, state=state)))
    assert len(run1) == 100 and run1[0].url == "https://www.youtube.com/watch?v=v0000000000"
    assert state["handles"] == {"@Handle": "UCcCfpDNl1Bi-LopV2noq_pg"}
    run2 = list(a.collect(CollectContext(source_config=cfg, checkpoint={}, state=state)))
    assert len(run2) == 30 and state["backfill"]["UUcCfpDNl1Bi-LopV2noq_pg"]["done"] is True
    assert list(a.collect(CollectContext(source_config=cfg, checkpoint={}, state=state))) == []
    assert sum(1 for c in calls if c[0] == "channels") == 1


def test_youtube_single_video_links(env, monkeypatch):
    from tarbiyah.sources import youtube
    from tarbiyah.sources.base import CollectContext

    a = youtube.YouTubeAdapter()
    assert youtube.classify_link("https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=5") == ("video", "dQw4w9WgXcQ")
    assert youtube.classify_link("https://youtu.be/dQw4w9WgXcQ") == ("video", "dQw4w9WgXcQ")
    assert youtube.classify_link("https://www.youtube.com/shorts/dQw4w9WgXcQ") == ("video", "dQw4w9WgXcQ")
    assert youtube.classify_link("https://www.youtube.com/playlist?list=PLabcdefghijkl") == ("playlist", "PLabcdefghijkl")
    # video links pasted into channel_ids are accepted too
    assert a.config_problems({"channel_ids": ["https://youtu.be/dQw4w9WgXcQ"]}) == []
    assert a.config_problems({"video_urls": "https://youtu.be/dQw4w9WgXcQ"})  # not a list
    assert a.config_problems({"video_urls": ["hello"]})

    monkeypatch.setattr(youtube, "fetch_transcript",
                        lambda vid: ([{"text": "patience with children", "timestamp": 0.0}], "en", False))

    class FakeHttp:
        def get_json(self, url, **kw):
            assert url.endswith("/oembed")
            return {"title": "Raising children", "author_name": "Some Channel"}

    monkeypatch.setattr(youtube, "http", lambda: FakeHttp())
    state: dict = {}
    cfg = {"video_urls": ["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "https://youtu.be/dQw4w9WgXcQ"]}
    out = list(a.collect(CollectContext(source_config=cfg, checkpoint={}, state=state)))
    assert len(out) == 1
    d = out[0]
    assert d.title == "Raising children" and d.channel == "Some Channel" and d.resource_type == "video"
    assert d.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ" and d.segments and d.extra["transcript"] is True
    assert list(a.collect(CollectContext(source_config=cfg, checkpoint={}, state=state))) == []


def test_doaj_403_falls_back_to_doaj_journals_in_openalex(env, monkeypatch):
    from tarbiyah.http import FetchError
    from tarbiyah.sources import academic

    calls = []

    class FakeHttp:
        def get_json(self, url, **kw):
            calls.append((url, kw))
            if "doaj.org" in url:
                assert kw["check_robots"] is False and "crawler" not in kw["headers"]["User-Agent"]
                raise FetchError(f"HTTP 403 for {url}", status=403)
            assert "is_in_doaj:true" in kw["params"]["filter"]
            return {"results": [{"id": "https://openalex.org/W1", "display_name": "Family cohesion among Muslim youth",
                                 "type": "article", "publication_year": 2024, "doi": "https://doi.org/10.1/x",
                                 "open_access": {"is_oa": True, "oa_status": "gold"},
                                 "primary_location": {"landing_page_url": "https://journal.example/a",
                                                      "license": "cc-by", "source": {"display_name": "J. Ed"}}}]}

    monkeypatch.setattr(academic, "http", lambda: FakeHttp())
    out = academic.DoajAdapter().search("family cohesion immigrant Muslim youth", "en", 10)
    assert len(out) == 1 and out[0].source_key == "doaj" and out[0].extra["via"].startswith("openalex")
    assert out[0].access.access_status == "open_license"
    assert [c[0] for c in calls][:2] == ["https://doaj.org/api/search/articles/family%20cohesion%20immigrant%20Muslim%20youth",
                                         "https://doaj.org/api/v4/search/articles/family%20cohesion%20immigrant%20Muslim%20youth"]

    class Down(FakeHttp):
        def get_json(self, url, **kw):
            raise FetchError("HTTP 500", status=500)

    monkeypatch.setattr(academic, "http", lambda: Down())
    with pytest.raises(FetchError):  # a real outage is reported, not hidden
        academic.DoajAdapter().search("x", None, 5)


def test_crawler_keywords_focus(env):
    from types import SimpleNamespace as NS

    from tarbiyah.sources.web import _matches_keywords

    cfg = {"keywords": ["تربية", "اولاد", "طفل", "معلم"]}
    assert _matches_keywords(cfg, NS(title="تربيةُ الأولادِ في الإسلام", description="", full_text=""))
    assert _matches_keywords(cfg, NS(title="آداب المعلّم والمتعلّم", description="", full_text=""))
    assert not _matches_keywords(cfg, NS(title="ديوان المتنبي", description="شعر", full_text="... الطفل ..."))
    assert _matches_keywords({**cfg, "keywords_in": "text"}, NS(title="ديوان", description="", full_text="عن الطفل"))
    assert not _matches_keywords({"keywords": ["طفل"], "keywords_in": "title"},
                                 NS(title="كتاب", description="في الطفل", full_text=""))


def test_crawler_patterns_match_arabic_and_encoded_urls():
    from tarbiyah.sources.web import _url_match

    enc = "https://islamonline.net/category/%d8%a7%d9%84%d8%a3%d8%b3%d8%b1%d8%a9-%d9%81%d9%8a-%d8%a7%d9%84%d8%a5%d8%b3%d9%84%d8%a7%d9%85/page/2/"
    assert _url_match("/category/الأسرة", enc) and _url_match("/page/\\d+/?$", enc)
    assert not _url_match("/category/سياسة", enc)
