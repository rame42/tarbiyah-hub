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
