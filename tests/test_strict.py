"""Strict mode: only exactly what the person needs enters the library."""
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from tarbiyah.db import session_scope
from tarbiyah.models import Resource, Source

from .conftest import drain
from .fixtures.site import serve

PARENTING = ("Raising children with patience and prayer. Parents should teach children salah with kindness, "
             "be a role model for their sons and daughters, and build the Muslim family on mercy. ") * 6
OTHER = "Market prices rose this week and the football league results were announced. " * 12


def _page(title, crumbs, body, links=""):
    nav = "".join(f'<a href="/x">{c}</a> ' for c in crumbs)
    return (f'<html><head><meta charset="utf-8"><title>{title}</title></head><body><nav class="breadcrumb">{nav}</nav>'
            f"<h1>{title}</h1><p>{body}</p>{links}</body></html>")


def _site():
    root = Path(tempfile.mkdtemp(prefix="th_strict_"))
    srv, base = serve(root)
    (root / "family").mkdir()
    (root / "news").mkdir()
    (root / "articles").mkdir()
    (root / "family" / "index.html").write_text(_page("Family section", ["Home", "Family"], "List of family articles",
        '<a href="/articles/a1.html">a1</a> <a href="/articles/a2.html">a2</a> <a href="/articles/a3.html">a3</a> '
        '<a href="/family/page2.html">next</a> <a href="/docs/guide.pdf">guide</a>'))
    (root / "family" / "page2.html").write_text(_page("Family section 2", ["Home", "Family"], "More",
        '<a href="/articles/a4.html">a4</a>'))
    (root / "articles" / "a1.html").write_text(_page("Raising children with patience", ["Home", "Family", "Parenting"],
        PARENTING, '<a href="/news/n1.html">related news</a>'))
    (root / "articles" / "a2.html").write_text(_page("Market and sports update", ["Home", "News"], OTHER))
    (root / "articles" / "a3.html").write_text(_page("Weekly market notes", ["Home", "Family"], OTHER))
    (root / "articles" / "a4.html").write_text(_page("Teaching salah to sons and daughters", ["Home", "Parenting"], PARENTING))
    (root / "news" / "n1.html").write_text(_page("Raising children news", ["Home", "News"], PARENTING))
    (root / "docs").mkdir()
    (root / "docs" / "guide.pdf").write_bytes(b"%PDF-1.4 fake")
    return srv, base


def test_strict_web_source_end_to_end(env):
    from tarbiyah.api.app import app
    from tarbiyah.jobs.scheduler import dispatch_due_sources

    srv, base = _site()
    try:
        with TestClient(app) as c:
            for x in c.get("/api/sources").json():
                c.patch(f"/api/sources/{x['id']}", json={"enabled": False})
            src = c.post("/api/sources", json={"adapter": "web_crawler", "name": "Family site", "config": {
                "start_urls": [base + "/family/index.html"], "allowed_domains": ["127.0.0.1"], "use_sitemap": False,
                "section_lock": True, "min_text_chars": 50, "min_interval_seconds": 0.05}}).json()
            # preview: nothing stored
            prev = c.post(f"/api/my-sources/{src['id']}/preview", json={"strict": {
                "site_sections": ["Family", "Parenting"], "min_score": 20}}).json()
            assert prev["error"] is None
            saved = {x["title"] for x in prev["would_save"]}
            rejected = {x["title"]: x["reason"] for x in prev["would_reject"]}
            assert saved == {"Raising children with patience", "Teaching salah to sons and daughters"}
            assert "filed by the site under" in rejected["Market and sports update"]
            assert rejected["Weekly market notes"].startswith("pillar check")
            assert "Raising children news" not in saved | set(rejected)  # outside the section: never visited
            with session_scope() as s:
                assert s.query(Resource).count() == 0 and s.query(Source).filter(Source.name == "preview").count() == 0
            # real run with strict mode on (no AI: rules decide after processing)
            r = c.put(f"/api/my-sources/{src['id']}/strict", json={"strict": {
                "enabled": True, "site_sections": ["Family", "Parenting"], "min_score": 20, "review": True}})
            assert r.status_code == 200
        with session_scope() as s:
            s.get(Source, src["id"]).next_run_at = None
        dispatch_due_sources()
        drain(60)
        with TestClient(app) as c:
            card = [x for x in c.get("/api/my-sources").json()["sources"] if x["id"] == src["id"]][0]
            assert card["to_review"] == 2 and card["items"] == 0  # nothing enters the library without approval
            stats = card["strict_stats"]
            assert stats["passed"] == 2 and stats["rejected"] == 1 and stats["skipped_before_saving"] >= 2
            assert any("strict mode" in m for m in card["last_result"]["messages"])
            items = c.get("/api/review").json()["items"]
            keep = [x for x in items if x["title"].startswith("Raising")][0]
            drop = [x for x in items if x["title"].startswith("Teaching")][0]
            c.post(f"/api/review/{keep['id']}", json={"keep": True})
            c.post(f"/api/review/{drop['id']}", json={"keep": False})
            card = [x for x in c.get("/api/my-sources").json()["sources"] if x["id"] == src["id"]][0]
            assert card["items"] == 1 and card["to_review"] == 0 and card["precision"] == 50
            with session_scope() as s:
                assert s.get(Resource, drop["id"]).deleted  # rejected: never collected again
    finally:
        srv.shutdown()


def test_precision_watch_pauses_and_files_only(env):
    from types import SimpleNamespace as NS

    from tarbiyah import strict

    src = NS(config={"strict": {"enabled": True, "pause_below": 30, "min_judged": 5}}, state={}, enabled=True,
             health="ok", last_error=None)
    s = strict._stats(src)
    s.update(passed=1, rejected=6)
    strict._save_stats(src, s)
    strict._watch(src)
    assert src.enabled is False and "precision watch" in src.last_error
    cfg = {**strict.DEFAULTS, "files_only": True}
    page = NS(resource_type="article", download_url=None, url="https://x.org/a", extra={})
    pdf = NS(resource_type="document", download_url=None, url="https://x.org/guide.PDF", extra={})
    assert strict.pre_save(cfg, page) == "not a downloadable file" and strict.pre_save(cfg, pdf) is None
    assert strict.pre_save({**strict.DEFAULTS, "types": ["video"]}, page).startswith("kind 'article'")
