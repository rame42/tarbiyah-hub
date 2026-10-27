"""YouTube: channel/playlist monitoring, video search, captions/transcripts.

- Monitoring channels and playlists uses YouTube's public Atom feeds (no key needed).
- Search uses the YouTube Data API v3 (free key, 10,000 quota units/day; a search costs 100).
- Captions are read with youtube-transcript-api when the uploader or YouTube published them.
  Videos themselves are never downloaded.
"""
from __future__ import annotations

import re
from typing import Any, Iterator

import feedparser

from ..config import get_config
from ..http import FetchError, http
from ..ingest.licensing import decide
from ..ingest.registry import ResourceIn
from .base import AdapterInfo, CollectContext, SourceAdapter, as_year

FEED = "https://www.youtube.com/feeds/videos.xml"
API = "https://www.googleapis.com/youtube/v3"


def video_id_from_url(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|/shorts/|/embed/|/live/)([A-Za-z0-9_-]{11})", url or "")
    return m.group(1) if m else None


def fetch_transcript(video_id: str, languages: tuple[str, ...] = ("ar", "en")) -> tuple[list[dict[str, Any]], str | None, bool]:
    """Return (segments, language_code, is_generated). Empty list when no captions are available."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
    except ImportError:
        return [], None, False
    api = YouTubeTranscriptApi()
    try:
        listing = api.list(video_id)
        try:
            tr = listing.find_manually_created_transcript(list(languages))
        except Exception:  # noqa: BLE001
            tr = listing.find_transcript(list(languages))
        fetched = tr.fetch()
    except Exception:  # noqa: BLE001 - disabled captions, unavailable video, blocked request
        return [], None, False
    segs: list[dict[str, Any]] = []
    for sn in fetched:
        start = float(getattr(sn, "start", 0.0))
        text = getattr(sn, "text", "")
        if segs and start - segs[-1]["timestamp"] < 60:
            segs[-1]["text"] += " " + text
        else:
            segs.append({"text": text, "timestamp": start})
    return segs, getattr(tr, "language_code", None), bool(getattr(tr, "is_generated", False))


class YouTubeAdapter(SourceAdapter):
    info = AdapterInfo(
        name="youtube", label="YouTube", kind="video",
        description="Lectures, courses and talks: channel/playlist monitoring (no key), search (API key), "
                    "and captions/transcripts when published.",
        capabilities=("search", "monitor"), resource_types=("video",),
        optional_credentials=("YOUTUBE_API_KEY",),
        access_notes="Channel monitoring works without credentials. Search needs a free YouTube Data API key. "
                     "Video files are never downloaded; only metadata and available captions.",
        default_schedule_minutes=720, min_interval_seconds=1.0, required_config=(("channel_ids", "playlist_ids"),),
        config_fields={"channel_ids": "List of channel IDs (UC...)", "playlist_ids": "List of playlist IDs",
                       "transcripts": "Collect captions (true/false)", "language": "Language hint"},
        default_config={"channel_ids": [], "playlist_ids": [], "transcripts": True},
    )

    def _resource(self, vid: str, title: str, desc: str, channel: str | None, published: str | None,
                  ctx_source_key: str | None, source_id: int | None, want_transcript: bool,
                  lang_hint: str | None = None) -> ResourceIn:
        segs, tlang, generated = fetch_transcript(vid) if want_transcript else ([], None, False)
        return ResourceIn(
            title=title or vid,
            resource_type="video",
            url=f"https://www.youtube.com/watch?v={vid}",
            description=desc or None,
            language=tlang[:2] if tlang else lang_hint,
            published_date=(published or "")[:10] or None,
            year=as_year(published),
            external_id=vid,
            source_key=ctx_source_key or "youtube",
            source_id=source_id,
            collection_method="youtube_feed" if source_id else "youtube_api",
            access=decide(None),
            channel=channel,
            segments=segs or None,
            text=None if segs else (desc or None),
            extra={"platform": "youtube", "transcript": bool(segs), "transcript_generated": generated,
                   "transcript_language": tlang, "inline_method": "youtube_captions" if segs else "description"},
        )

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        key = get_config().youtube_api_key
        if not key:
            from .base import NotConfigured

            raise NotConfigured("YouTube search needs YOUTUBE_API_KEY (free, Google Cloud console).")
        params: dict[str, Any] = {"part": "snippet", "q": query, "type": "video", "maxResults": min(limit, 25), "key": key}
        if lang in ("ar", "en"):
            params["relevanceLanguage"] = lang
        data = http().get_json(f"{API}/search", params=params, check_robots=False)
        out = []
        for it in data.get("items", []):
            vid = (it.get("id") or {}).get("videoId")
            sn = it.get("snippet") or {}
            if vid:
                out.append(self._resource(vid, sn.get("title", ""), sn.get("description", ""), sn.get("channelTitle"),
                                          sn.get("publishedAt"), None, None, True, lang))
        return out

    def collect(self, ctx: CollectContext) -> Iterator[ResourceIn]:
        cfg = {**self.info.default_config, **(ctx.source_config or {})}
        targets = [("channel_id", c) for c in cfg.get("channel_ids") or []] + \
                  [("playlist_id", p) for p in cfg.get("playlist_ids") or []]
        if not targets:
            raise ValueError("YouTube source has no channel_ids or playlist_ids configured.")
        seen = set(ctx.state.get("seen_ids", []))
        for param, value in targets:
            if ctx.should_stop():
                break
            try:
                res = http().fetch(FEED, params={param: value}, check_robots=False)
            except FetchError as e:
                ctx.log(f"YouTube feed failed for {value}: {e}")
                continue
            feed = feedparser.parse(res.content)
            for e in feed.entries:
                vid = e.get("yt_videoid") or video_id_from_url(e.get("link", ""))
                if not vid or vid in seen:
                    continue
                desc = e.get("media_description") or e.get("summary") or ""
                yield self._resource(vid, e.get("title", ""), desc, feed.feed.get("title") or e.get("author"),
                                     e.get("published"), ctx.source_key, ctx.source_id, bool(cfg.get("transcripts")),
                                     cfg.get("language"))
                seen.add(vid)
        ctx.state["seen_ids"] = sorted(seen)[-5000:]
