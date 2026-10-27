"""API behaviour, secret handling, semantic-search plumbing and backup/restore."""
import json

from fastapi.testclient import TestClient

from tarbiyah.db import session_scope


def test_api_end_to_end(env, fixtures_dir, monkeypatch):
    monkeypatch.setenv("YOUTUBE_API_KEY", "SECRET-YT-KEY-123")
    from tarbiyah.config import reset_config_cache

    reset_config_cache()
    from tarbiyah.api.app import app

    with TestClient(app) as c:
        with open(fixtures_dir / "ar_tarbiyah.pdf", "rb") as f:
            r = c.post("/api/import", files={"file": ("ar.pdf", f, "application/pdf")}, data={"resource_type": "book"})
        assert r.status_code == 200 and r.json()["created"]
        rid = r.json()["resource_id"]
        with open(fixtures_dir / "ar_tarbiyah.pdf", "rb") as f:
            again = c.post("/api/import", files={"file": ("copy.pdf", f, "application/pdf")})
        assert again.json()["created"] is False
        bad = c.post("/api/import", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
        assert bad.status_code == 400
        from tests.conftest import drain

        drain(60)
        res = c.get("/api/resources", params={"q": "تربية الأطفال"}).json()
        assert res["results"][0]["resource"]["id"] == rid
        d = c.get(f"/api/resources/{rid}").json()
        assert d["has_file"] and d["chunk_count"] >= 2 and d["history"]
        assert c.get(f"/api/resources/{rid}/file").status_code == 200
        dash = c.get("/api/dashboard").json()
        assert dash["stats"]["discoveries"]["total"] == 1 and dash["previous"] is not None
        q = c.post("/api/questions", json={"text": "How do classical scholars describe the child as a trust?"}).json()
        assert c.post("/api/questions", json={"text": "How do classical scholars describe the child as a trust ?"}).status_code == 409
        assert c.patch(f"/api/questions/{q['id']}", json={"status": "bogus"}).status_code == 400
        assert c.patch("/api/settings", json={"worker_concurrency": "many"}).status_code == 400
        assert c.patch("/api/settings", json={"worker_concurrency": 2}).status_code == 200
        src = c.post("/api/sources", json={"adapter": "rss", "name": "Blog", "config": {"feeds": ["https://example.org/feed"]}}).json()
        assert src["role"] == "monitor" and src["enabled"]
        assert c.post("/api/sources", json={"adapter": "openalex", "name": "x"}).status_code == 400
        assert c.patch(f"/api/sources/{src['id']}", json={"paused": True}).json()["paused"]
        # secrets never leave the server
        for path in ("/api/status", "/api/settings", "/api/sources", "/api/adapters", "/api/dashboard"):
            assert "SECRET-YT-KEY-123" not in c.get(path).text
        assert c.get("/api/status").json()["credentials"]["youtube_api_key"] is True
        out = c.post("/api/outputs", json={"kind": "evidence_table", "params": {"resource_ids": [rid]}}).json()
        drain(30)
        o = c.get(f"/api/outputs/{out['id']}").json()
        assert o["status"] == "done" and "csv" in o["formats"]
        assert c.get(f"/api/outputs/{out['id']}/download", params={"fmt": "csv"}).status_code == 200


def test_semantic_fusion_plumbing(env, fixtures_dir):
    """Uses a deterministic local embedder to test storage/fusion; real embeddings need VOYAGE_API_KEY."""
    import hashlib

    from tarbiyah.ingest.pipeline import import_local_file, process
    from tarbiyah.search import semantic
    from tarbiyah.search.fts import search_chunks

    def fake(texts, _kind):
        out = []
        for t in texts:
            v = [0.0] * 32
            for w in t.lower().split():
                v[int(hashlib.md5(w.encode()).hexdigest(), 16) % 32] += 1.0
            out.append(v)
        return out

    semantic.set_embedder(fake, model="test-hash")
    with session_scope() as s:
        r, _ = import_local_file(s, fixtures_dir / "en_parenting.pdf")
        process(s, r)
        assert semantic.embed_pending(s) >= 2
        hits = semantic.semantic_chunks(s, "Teacher Training and Mentoring", k=3)
        assert hits and hits[0][1] > 0
        assert search_chunks(s, "mentoring teachers", limit=3)
    assert semantic.fuse([1, 2, 3], [3, 4]) [0] == 3


def test_backup_and_restore_roundtrip(env, fixtures_dir):
    from tarbiyah.backup import backup, restore
    from tarbiyah.db import reset_engine
    from tarbiyah.ingest.pipeline import import_local_file, process
    from tarbiyah.models import Resource

    with session_scope() as s:
        r, _ = import_local_file(s, fixtures_dir / "en_parenting.pdf")
        process(s, r)
    archive = backup(env.parent / "bk")
    assert archive.exists()
    with session_scope() as s:
        s.query(Resource).one().title = "changed after backup"
    reset_engine()
    msg = restore(archive)
    assert "Restored" in msg
    reset_engine()
    with session_scope() as s:
        r = s.query(Resource).one()
        assert r.title.startswith("Positive Parenting") and (env / r.local_path).exists()
    assert json.dumps  # keep import used
