"""Library curation: edit, label, delete (not re-collected), restore, bulk actions."""
from fastapi.testclient import TestClient

from tarbiyah.db import session_scope
from tarbiyah.ingest.licensing import decide
from tarbiyah.ingest.pipeline import import_local_file, process, register_with_content
from tarbiyah.ingest.registry import ResourceIn
from tarbiyah.models import Job, Resource
from tarbiyah.search.fts import search

from .conftest import drain


def test_edit_label_delete_restore_bulk(env, fixtures_dir):
    from tarbiyah.api.app import app

    with session_scope() as s:
        r, _ = import_local_file(s, fixtures_dir / "ar_tarbiyah.pdf")
        process(s, r)
        u, _ = register_with_content(s, ResourceIn(title="Unknown-licence paper", url="https://journal.example/a",
                                                   resource_type="paper", access=decide(None),
                                                   extra={"pdf_url": "https://journal.example/a.pdf"}))
        rid, uid = r.id, u.id
    with TestClient(app) as c:
        assert c.get("/api/resources", params={"access": "unknown"}).json()["total"] == 1
        # relabel access: the user confirms it is openly licensed -> download is queued
        res = c.patch(f"/api/resources/{uid}", json={"access_status": "open_license", "pillars": ["parents"],
                                                      "add_labels": ["important"], "resource_type": "report"})
        assert res.status_code == 200 and set(res.json()["changed"]) >= {"access", "pillars", "labels", "type"}
        with session_scope() as s:
            u = s.get(Resource, uid)
            assert u.download_permitted and "Set by the user" in u.permission_basis and u.labels == ["important"]
            assert [p.pillar for p in u.pillars] == ["parents"] and u.resource_type == "report"
            assert s.query(Job).filter(Job.job_type == "acquire").count() == 1
        assert c.get("/api/resources", params={"label": "important"}).json()["total"] == 1
        assert c.get("/api/labels").json() == [{"label": "important", "count": 1}]
        assert c.patch(f"/api/resources/{uid}", json={"access_status": "bogus"}).status_code == 400
        # delete: gone from search and lists, file removed, and not re-collected later
        with session_scope() as s:
            path = env / s.get(Resource, rid).local_path
        assert c.delete(f"/api/resources/{rid}").json()["deleted"]
        assert not path.exists()
        assert c.get("/api/resources", params={"q": "تربية الأطفال"}).json()["total"] == 0
        assert c.get("/api/resources", params={"show_deleted": True}).json()["total"] == 1
        with session_scope() as s:
            again, created = import_local_file(s, fixtures_dir / "ar_tarbiyah.pdf")
            assert not created and again.deleted  # recognised; stays deleted
        # restore brings it back through processing
        c.post(f"/api/resources/{rid}/restore")
    drain(30)
    with session_scope() as s:
        assert search(s, "الغزالي")["total"] == 0  # restored record has no file anymore: metadata only
        assert not s.get(Resource, rid).deleted
    with TestClient(app) as c:
        b = c.post("/api/resources/bulk", json={"ids": [rid, uid], "action": "add_label", "value": "to read"}).json()
        assert b["done"] == 2
        assert c.post("/api/resources/bulk", json={"ids": [rid], "action": "nonsense"}).status_code == 400
        assert c.post("/api/resources/bulk", json={"ids": [rid, uid], "action": "delete"}).json()["done"] == 2
        assert c.get("/api/resources").json()["total"] == 0


def _web(s, title, desc, url):
    r, _ = register_with_content(s, ResourceIn(title=title, url=url, resource_type="article", description=desc,
                                               access=decide(None), collection_method="api", source_key="openalex"))
    process(s, r)
    return r


def test_relevance_archive_and_cleanup(env, fixtures_dir):
    from tarbiyah.api.app import app
    from tarbiyah.settings import set_setting

    with session_scope() as s:
        good = _web(s, "Raising children: parenting with patience in Islamic tarbiyah",
                    "Guidance for parents on the upbringing of children, child discipline and family worship.",
                    "https://ex.org/good")
        off = _web(s, "Football transfer news", "The striker signed a new contract with the club.",
                   "https://ex.org/off")
        sports = _web(s, "Parenting and football", "Parents watching children play football; parenting tips.",
                      "https://ex.org/sports")
        ids = good.id, off.id, sports.id
        assert good.relevance >= 40 and off.relevance == 0 and good.pillars and not off.pillars
    with TestClient(app) as c:
        summ = c.get("/api/curation").json()
        assert summ["active"] == 3 and summ["unclassified"] >= 1 and summ["low_relevance"] >= 1
        assert c.get("/api/resources", params={"pillar": "none"}).json()["total"] == summ["unclassified"]
        assert c.get("/api/resources", params={"sort": "relevance_low"}).json()["results"][0]["resource"]["id"] == ids[1]
        # clean-up: preview, then archive everything below 20
        assert c.post("/api/curation/archive-low", json={"below": 20, "dry_run": True, "source": "shamela"}).json()["would_archive"] == 0
        assert c.post("/api/curation/archive-low", json={"below": 20, "dry_run": True, "source": "openalex"}).json()["would_archive"] >= 1
        prev = c.post("/api/curation/archive-low", json={"below": 20, "dry_run": True}).json()
        assert prev["would_archive"] >= 1 and any(e["id"] == ids[1] for e in prev["examples"])
        assert c.post("/api/curation/archive-low", json={"below": 20, "dry_run": False}).json()["archived"] >= 1
        assert c.get("/api/resources", params={"view": "archived"}).json()["total"] >= 1
        assert c.get("/api/resources", params={"q": "football transfer"}).json()["total"] == 0  # hidden from search
        assert c.get("/api/resources", params={"q": "football transfer", "view": "archived"}).json()["total"] == 1
        # unarchive is sticky: automatic rules will not archive it again
        assert c.post(f"/api/resources/{ids[1]}/unarchive").json()["status"] == "unarchived"
        # exclude words + auto-archive for new items
        assert c.patch("/api/settings", json={"exclude_terms": ["football"], "auto_archive_below": 15}).json()["ok"]
        assert c.patch("/api/settings", json={"exclude_terms": "football"}).status_code == 400
    with session_scope() as s:
        new = _web(s, "Football league table", "Weekly results.", "https://ex.org/new-off")
        assert new.archived and "excluded word" in new.extra["archived_reason"]
        kept = s.get(Resource, ids[1])
        from tarbiyah.ingest.manage import reclassify
        reclassify(s, kept)
        assert not kept.archived  # the user's decision wins
        upload, _ = import_local_file(s, fixtures_dir / "ar_tarbiyah.pdf")
        process(s, upload)
        assert not upload.archived  # the user's own files are never archived automatically
    # focus words raise relevance; re-sorting runs as a background job
    with TestClient(app) as c:
        c.patch("/api/settings", json={"exclude_terms": [], "focus_terms": ["striker", "contract"]})
        assert c.post("/api/curation/rescore", json={"scope": "all", "ai": False}).json()["job_id"]
    drain(30)
    with session_scope() as s:
        assert s.get(Resource, ids[1]).relevance > 0
        assert s.get(Resource, ids[0]).relevance >= 40
        # set relevance by hand
        from tarbiyah.ingest.manage import set_relevance
        r = s.get(Resource, ids[2])
        set_relevance(s, r, 90)
        assert r.relevance == 90
