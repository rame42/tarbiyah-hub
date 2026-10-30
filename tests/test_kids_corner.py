"""Children's Quran, Seerah & Hadith shelf."""
from fastapi.testclient import TestClient

from tarbiyah.db import session_scope
from tarbiyah.ingest.licensing import decide
from tarbiyah.ingest.pipeline import register_with_content
from tarbiyah.ingest.registry import ResourceIn
from tarbiyah.models import Job, Resource, Setting

from .conftest import drain


def _add(s, i, title, rtype="book", desc=""):
    r, _ = register_with_content(s, ResourceIn(title=title, url=f"https://ex.org/k{i}", resource_type=rtype,
                                               description=desc, access=decide(None), collection_method="api",
                                               source_key="internet_archive"))
    return r


def test_shelf_filters_and_find(env):
    from tarbiyah.api.app import app

    with session_scope() as s:
        a = _add(s, 1, "قصص السيرة النبوية للأطفال")
        b = _add(s, 2, "Quran for Kids: Juz Amma", "video")
        c = _add(s, 3, "Hadith for children", "course", "40 hadith explained for young muslims")
        _add(s, 4, "التربية الحديثة للأطفال")          # "modern" upbringing, not hadith
        _add(s, 5, "Tafsir of Surah al-Baqarah", desc="for advanced students")  # Quran, but not for children
        assert a.extra["kids_corner"] == ["seerah"] and b.extra["kids_corner"] == ["quran"]
        a.local_path = "files/x.pdf"
    with TestClient(app) as c:
        d = c.get("/api/kids-corner").json()
        assert d["counts"] == {"all": 3, "quran": 1, "seerah": 1, "hadith": 1, "files": 1}
        assert d["types"] == {"book": 1, "video": 1, "course": 1}
        assert [x["title"] for x in c.get("/api/kids-corner", params={"subject": "quran"}).json()["items"]] == \
            ["Quran for Kids: Juz Amma"]
        assert c.get("/api/kids-corner", params={"type": "video"}).json()["total"] == 1
        assert c.get("/api/kids-corner", params={"files_only": True}).json()["items"][0]["title"] == "قصص السيرة النبوية للأطفال"
        r = c.post("/api/kids-corner/find").json()
        assert r["queued"] > 0 and "Internet Archive" in " ".join(r["sources"])


def test_existing_library_is_scanned_once(env):
    with session_scope() as s:
        r = _add(s, 9, "Seerah stories for kids")
        r.extra = {k: v for k, v in r.extra.items() if k != "kids_corner"}  # as if collected before the shelf
        rid = r.id
    from tarbiyah.jobs import queue

    with session_scope() as s:
        queue.enqueue(s, "maintenance", {})
    drain(30)
    with session_scope() as s:
        assert s.get(Resource, rid).extra["kids_corner"] == ["seerah"]
        assert s.get(Setting, "_kids_corner_scanned") is not None
        assert s.query(Job).filter(Job.job_type == "kids_corner_scan").count() == 1
