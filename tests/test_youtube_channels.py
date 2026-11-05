"""YouTube: discover tarbiyah channels, add/dismiss, choose playlists, length and rules before captions, quota."""
from fastapi.testclient import TestClient

from tarbiyah.db import session_scope
from tarbiyah.models import Source

GOOD, BAD, TINY = "UC" + "g" * 22, "UC" + "b" * 22, "UC" + "t" * 22


def fake_api(self, path, **p):
    from tarbiyah.settings import record_usage

    record_usage("youtube_units", 100 if path == "search" else 1)
    if path == "search":
        return {"items": [{"id": {"channelId": c}} for c in (GOOD, BAD, TINY)]}
    if path == "channels":
        info = {GOOD: ("قناة تربية الأبناء", "دروس في تربية الأطفال على القيم الإسلامية والصلاة", 120),
                BAD: ("Football Highlights", "Goals and match results every week", 900),
                TINY: ("تربية الأطفال", "قناة تربية الأطفال في الإسلام", 1)}
        return {"items": [{"id": c, "snippet": {"title": info[c][0], "description": info[c][1]},
                           "statistics": {"subscriberCount": "5000", "videoCount": str(info[c][2])},
                           "contentDetails": {"relatedPlaylists": {"uploads": "UU" + c[2:]}}}
                          for c in p["id"].split(",") if c in info]}
    if path == "playlistItems":
        titles = ["تعليم الأطفال الصلاة", "التربية الإيمانية للطفل", "بر الوالدين"] if p["playlistId"] == "UU" + GOOD[2:] \
            else ["Best goals 2026", "Match recap"]
        return {"items": [{"snippet": {"title": t}} for t in titles]}
    if path == "playlists":
        return {"items": [{"id": "PLkidsTarbiya1Tarbiya1", "snippet": {"title": "سلسلة تربية الأبناء"}, "contentDetails": {"itemCount": 30}},
                          {"id": "PLnews", "snippet": {"title": "أخبار"}, "contentDetails": {"itemCount": 5}}]}
    raise AssertionError(path)


def test_discover_add_dismiss_playlists_quota(env, monkeypatch):
    from tarbiyah.api.app import app
    from tarbiyah.config import get_config
    from tarbiyah.sources import youtube

    from .conftest import drain

    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    get_config.cache_clear()
    monkeypatch.setattr(youtube.YouTubeAdapter, "_api", fake_api)
    with TestClient(app) as c:
        assert c.post("/api/youtube/discover", json={"pillars": ["children"], "max_queries": 2}).json()["job_id"]
        drain(30)
        d = c.get("/api/youtube").json()
        assert [x["id"] for x in d["suggestions"]] == [GOOD]  # football: not tarbiyah; tiny: too few videos
        sug = d["suggestions"][0]
        assert sug["sample_titles"][0] == "تعليم الأطفال الصلاة" and "children" in sug["pillars"]
        assert d["quota_used_today"] >= 200
        src = c.post("/api/youtube/add", json={"channel_id": GOOD}).json()
        assert src["config"]["channel_ids"] == [GOOD] and src["config"]["strict"]["enabled"]
        assert c.get("/api/youtube").json()["suggestions"] == []
        # dismissed channels never come back
        c.post("/api/youtube/dismiss", json={"channel_id": BAD})
        c.post("/api/youtube/discover", json={"pillars": ["children"], "max_queries": 1})
        drain(30)
        assert c.get("/api/youtube").json()["suggestions"] == []
        # choose only the channel's tarbiyah playlist
        pl = c.get(f"/api/my-sources/{src['id']}/youtube-playlists").json()["playlists"]
        assert [p["title"] for p in pl] == ["سلسلة تربية الأبناء", "أخبار"]
        r = c.put(f"/api/my-sources/{src['id']}/youtube-playlists", json={"playlist_ids": ["PLkidsTarbiya1Tarbiya1"], "min_minutes": 10}).json()
        assert r == {"channel_ids": [], "playlist_ids": ["PLkidsTarbiya1Tarbiya1"], "min_minutes": 10.0}
        ch = [x for x in c.get("/api/youtube").json()["channels"] if x["id"] == src["id"]][0]
        assert ch["only_playlists"] and ch["channel_ids"] == [GOOD]
        r = c.put(f"/api/my-sources/{src['id']}/youtube-playlists", json={"whole_channel": True}).json()
        assert r["channel_ids"] == [GOOD]


def test_rules_and_length_before_captions(env, monkeypatch):
    from tarbiyah.config import get_config
    from tarbiyah.sources import youtube
    from tarbiyah.sources.base import CollectContext

    monkeypatch.setenv("YOUTUBE_API_KEY", "k")
    get_config.cache_clear()
    captions = []
    monkeypatch.setattr(youtube, "fetch_transcript", lambda vid: captions.append(vid) or ([], None, False))

    def api(self, path, **p):
        if path == "playlistItems":
            vids = [("a" * 11, "تعليم الأطفال الصلاة"), ("b" * 11, "Funny short clip"), ("c" * 11, "تعليم الأطفال الوضوء - قصير")]
            return {"items": [{"snippet": {"title": t}, "contentDetails": {"videoId": v}} for v, t in vids]}
        if path == "videos":
            lens = {"a" * 11: "PT20M", "b" * 11: "PT15M", "c" * 11: "PT50S"}
            return {"items": [{"id": v, "contentDetails": {"duration": lens[v]}} for v in p["id"].split(",")]}
        raise AssertionError(path)

    monkeypatch.setattr(youtube.YouTubeAdapter, "_api", api)
    cfg = {"playlist_ids": ["PLkidsTarbiya1Tarbiya1"], "full_history": False, "min_minutes": 5,
           "strict": {"enabled": True, "keywords": ["الأطفال"]}}
    out = list(youtube.YouTubeAdapter().collect(CollectContext(source_config=cfg, checkpoint={}, state={})))
    assert [d.external_id for d in out] == ["a" * 11]  # b: no keyword; c: under 5 minutes
    assert captions == ["a" * 11]  # captions downloaded only for the kept video
    assert out[0].extra["duration_seconds"] == 1200


def test_quota_guard(env):
    from tarbiyah.http import BudgetExceeded
    from tarbiyah.settings import record_usage, set_setting
    from tarbiyah.sources.youtube import YouTubeAdapter

    with session_scope() as s:
        set_setting(s, "youtube_daily_units", 150)
    record_usage("youtube_units", 100)
    try:
        YouTubeAdapter()._api("search", q="x")
        raise AssertionError("should have stopped")
    except BudgetExceeded as e:
        assert "quota" in str(e)
