"""Recommended websites: added switched off; sections chosen in the dashboard."""
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from tarbiyah.db import session_scope
from tarbiyah.models import Source

from .fixtures.site import serve


def test_catalog_add_off_and_no_duplicates(env):
    from tarbiyah.api.app import app

    with TestClient(app) as c:
        sites = c.get("/api/catalog").json()["sites"]
        assert len(sites) >= 10 and not any(x["added"] for x in sites)
        keys = [x["key"] for x in sites]
        r = c.post("/api/catalog/add", json={"keys": keys}).json()
        assert len(r["added"]) == len(keys) and r["skipped"] == []
        again = c.post("/api/catalog/add", json={"keys": keys[:2]}).json()
        assert again["added"] == [] and len(again["skipped"]) == 2
        mine = c.get("/api/my-sources").json()["sources"]
        assert len(mine) == len(keys) and not any(x["enabled"] for x in mine)  # nothing runs until enabled
        y = [x for x in mine if "Yaqeen" in x["name"]][0]
        assert y["config"]["section_lock"] and y["strict"]["enabled"] and y["strict"]["pillars"] == ["parents", "children"]
        assert all(x["added"] for x in c.get("/api/catalog").json()["sites"])


def test_explore_and_choose_sections(env):
    from tarbiyah.api.app import app

    root = Path(tempfile.mkdtemp(prefix="th_explore_"))
    srv, base = serve(root)
    (root / "index.html").write_text(
        '<html><head><meta charset="utf-8"></head><body><nav class="main-menu"><a href="/family/">الأسرة</a> '
        '<a href="/news/">أخبار</a> <a href="/login">دخول</a></nav>'
        '<div><a href="/family/a1.html">مقال عن تربية الأبناء</a> <a href="/family/a2.html">مقال آخر</a> '
        '<a href="https://other.example/x">خارجي</a></div></body></html>', encoding="utf-8")
    try:
        with TestClient(app) as c:
            src = c.post("/api/sources", json={"adapter": "web_crawler", "name": "Site",
                                               "config": {"start_urls": [base + "/index.html"],
                                                          "allowed_domains": ["127.0.0.1"]}}).json()
            d = c.post(f"/api/my-sources/{src['id']}/explore").json()
            labels = [x["label"] for x in d["links"]]
            assert labels[:2] == ["الأسرة", "أخبار"]  # menu sections first, biggest first
            assert "دخول" not in labels and "خارجي" not in labels
            fam = d["links"][0]
            assert fam["menu"] and fam["inside"] == 2
            r = c.put(f"/api/my-sources/{src['id']}/sections", json={"urls": [fam["url"]]})
            assert r.json()["start_urls"] == [base + "/family/"]
            with session_scope() as s:
                cfg = s.get(Source, src["id"]).config
                assert cfg["section_lock"] is True and cfg["start_urls"] == [base + "/family/"]
            assert c.put(f"/api/my-sources/{src['id']}/sections", json={"urls": []}).status_code == 400
    finally:
        srv.shutdown()
