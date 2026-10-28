"""Courses (free/paid from schema.org data), the Files page and AI relevance screening."""
import io
import json
import tempfile
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

from tarbiyah.db import session_scope
from tarbiyah.ingest.licensing import decide
from tarbiyah.ingest.pipeline import import_local_file, process, register_with_content
from tarbiyah.ingest.registry import ResourceIn
from tarbiyah.models import Resource, Source

from .conftest import drain
from .fixtures.site import serve


def _course_page(title, offers=None, free=None):
    data = {"@context": "https://schema.org", "@type": "Course", "name": title,
            "description": "A structured course for parents on raising children with Islamic values.",
            "provider": {"@type": "Organization", "name": "Tarbiyah Academy"}, "inLanguage": "en"}
    if offers is not None:
        data["offers"] = offers
    if free is not None:
        data["isAccessibleForFree"] = free
    return (f"<html><head><title>{title}</title><script type='application/ld+json'>{json.dumps(data)}</script>"
            f"</head><body><h1>{title}</h1><p>{'Course content overview. ' * 30}</p></body></html>")


def _academy():
    root = Path(tempfile.mkdtemp(prefix="th_courses_"))
    srv, base = serve(root)
    (root / "index.html").write_text("<html><body><a href='/c/free.html'>free</a> <a href='/c/paid.html'>paid</a>"
                                     "<a href='/blog/post.html'>blog</a></body></html>")
    (root / "c").mkdir()
    (root / "c" / "free.html").write_text(_course_page("Raising Children with Patience", free=True))
    (root / "c" / "paid.html").write_text(_course_page("Murabbi Training Program",
                                                       offers={"@type": "Offer", "price": "49.00", "priceCurrency": "USD"}))
    (root / "c" / "unlinked.html").write_text(_course_page("Teen Tarbiyah Workshop", free=True))
    (root / "blog").mkdir()
    (root / "blog" / "post.html").write_text("<html><body><h1>News</h1><p>" + "Academy news. " * 80 + "</p></body></html>")
    return srv, base


def test_courses_from_catalogue_and_manual_add(env):
    from tarbiyah.api.app import app
    from tarbiyah.ingest.courses import course_from_html
    from tarbiyah.jobs.scheduler import dispatch_due_sources

    assert course_from_html(b"<html>no data</html>", "x") is None
    srv, base = _academy()
    try:
        with session_scope() as s:
            for src in s.query(Source):
                src.enabled = False
            s.add(Source(key="academy", adapter="web_crawler", name="Academy", enabled=True,
                         config={"role": "monitor", "start_urls": [base + "/index.html"], "allowed_domains": ["127.0.0.1"],
                                 "only_courses": True, "min_interval_seconds": 0.05}))
        assert dispatch_due_sources() == 1
        drain(60)
        with session_scope() as s:
            rows = {r.title: r for r in s.query(Resource).filter(Resource.source_key == "academy")}
            assert set(rows) == {"Raising Children with Patience", "Murabbi Training Program"}  # blog skipped
            paid = rows["Murabbi Training Program"]
            assert paid.resource_type == "course" and paid.access_status == "paid"
            assert paid.price == "49" and paid.currency == "USD" and paid.publisher == "Tarbiyah Academy"
            assert rows["Raising Children with Patience"].access_status == "free_to_read"
        with TestClient(app) as c:
            d = c.get("/api/courses").json()
            assert d["counts"] == {"all": 2, "free": 1, "paid": 1}
            assert [x["title"] for x in c.get("/api/courses", params={"price": "paid"}).json()["items"]] == \
                ["Murabbi Training Program"]
            # a course added by hand: its page is read and the details filled in
            assert not c.post("/api/courses", json={"url": base + "/c/free.html?ref=x"}).json()["created"]  # known
            r = c.post("/api/courses", json={"url": base + "/c/unlinked.html"}).json()
            assert r["created"]
            assert c.post("/api/courses", json={"url": "not a link"}).status_code == 400
            assert c.post("/api/courses/find", json={}).status_code == 400  # needs the YouTube key
        drain(30)
        with session_scope() as s:
            m = s.get(Resource, r["resource_id"])
            assert m.resource_type == "course" and m.title == "Teen Tarbiyah Workshop"
            assert m.access_status == "free_to_read" and m.publisher == "Tarbiyah Academy"
    finally:
        srv.shutdown()


def test_files_page_named_downloads_and_zip(env, fixtures_dir):
    from tarbiyah.api.app import app

    with session_scope() as s:
        a, _ = import_local_file(s, fixtures_dir / "ar_tarbiyah.pdf", title="تربية الأطفال: كتاب")
        process(s, a)
        b, _ = import_local_file(s, fixtures_dir / "framework.docx")
        process(s, b)
        aid, bid = a.id, b.id
    with TestClient(app) as c:
        d = c.get("/api/files").json()
        assert d["total"] == 2 and d["total_size"] > 0 and d["files_folder"]
        names = {x["id"]: x["file_name"] for x in d["items"]}
        assert names[aid] == "تربية الأطفال كتاب.pdf"
        r = c.get(f"/api/resources/{aid}/file", params={"download": True})
        assert r.status_code == 200 and r.headers["content-disposition"].startswith("attachment")
        assert c.get(f"/api/resources/{aid}/file").headers["content-disposition"].startswith("inline")
        z = c.post("/api/files/zip", json={"ids": [aid, bid]})
        assert z.status_code == 200
        assert sorted(zipfile.ZipFile(io.BytesIO(z.content)).namelist()) == sorted(names.values())
        assert c.post("/api/files/zip", json={"ids": [999]}).status_code == 400


def test_ai_triage_scores_and_archives(env, scripted_claude):
    from tarbiyah.ai import schemas as S
    from tarbiyah.settings import set_setting

    with session_scope() as s:
        set_setting(s, "auto_archive_below", 30)
        ids = []
        for t in ("Tarbiyah of young children through stories", "Car insurance discounts this week",
                  "Weekly football results"):
            r, _ = register_with_content(s, ResourceIn(title=t, url=f"https://ex.org/{len(ids)}", resource_type="article",
                                                       access=decide(None), collection_method="api", source_key="openalex"))
            ids.append(r.id)

    def respond(text):
        assert "Car insurance" in text and "<source>" in text
        return S.TriageBatch(items=[S.TriageItem(id=ids[0], relevance=80, pillars=["children"], reason="On topic."),
                                    S.TriageItem(id=ids[1], relevance=2, pillars=[], reason="Commerce.")])

    fake = scripted_claude({"triage": respond})
    from tarbiyah.agents.triage import triage_batch

    with session_scope() as s:
        assert triage_batch(s)["triaged"] == 2
    with session_scope() as s:
        good, junk, missing = (s.get(Resource, i) for i in ids)
        assert good.relevance == 80 and [p.pillar for p in good.pillars] == ["children"] and not good.archived
        assert junk.relevance == 2 and junk.archived and junk.extra["relevance_reason"] == "Commerce."
        assert missing.extra["triaged"] is True  # not returned: not asked again
        assert triage_batch(s)["triaged"] == 0
    assert len([c for c in fake.calls if c[0] == "triage"]) == 1
