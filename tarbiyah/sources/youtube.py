"""YouTube: channel/playlist monitoring, video search, captions/transcripts.

- Monitoring channels and playlists uses YouTube's public Atom feeds (no key needed). The feed
  only lists the newest 15 videos, so without a key older videos are not collected.
- With a YOUTUBE_API_KEY, channels and playlists are read through the Data API instead: the
  whole upload history is collected gradually (max_videos_per_run per run), newest first.
  This costs 1 quota unit per 50 videos. @handles are resolved with 1 unit each.
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
CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
PLAYLIST_ID = re.compile(r"^[A-Za-z0-9_-]{12,64}$")


def parse_channel(value: str) -> tuple[str, str] | None:
    """('id', 'UC...') or ('handle', '@name') from an ID, a handle or a channel link; None if unusable."""
    v = str(value or "").strip()
    m = re.search(r"youtube\.com/channel/(UC[A-Za-z0-9_-]{22})", v)
    if m:
        return "id", m.group(1)
    if CHANNEL_ID.match(v):
        return "id", v
    m = re.search(r"(?:youtube\.com/)?(@[\w.\-]{3,100})/?$", v)
    if m:
        return "handle", m.group(1)
    return None


def parse_playlist(value: str) -> str | None:
    v = str(value or "").strip()
    m = re.search(r"[?&]list=([A-Za-z0-9_-]+)", v)
    v = m.group(1) if m else v
    return v if PLAYLIST_ID.match(v) else None


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
        config_fields={"channel_ids": "List of channels: IDs (UC...), @handles or channel links",
                       "playlist_ids": "List of playlist IDs or playlist links",
                       "transcripts": "Collect captions (true/false)", "language": "Language hint",
                       "full_history": "With an API key: also collect older videos, not just the newest (true/false)",
                       "max_videos_per_run": "With an API key: older videos added per run per channel (default 100)"},
        default_config={"channel_ids": [], "playlist_ids": [], "transcripts": True, "full_history": True,
                        "max_videos_per_run": 100},
    )

    def config_problems(self, cfg: dict[str, Any]) -> list[str]:
        problems = super().config_problems(cfg)
        has_key = bool(get_config().youtube_api_key)
        for c in cfg.get("channel_ids") or []:
            parsed = parse_channel(c)
            if parsed is None:
                problems.append(f'YouTube: "{c}" is not a channel. Use the channel ID (starts with UC, 24 characters, '
                                f'e.g. UCcCfpDNl1Bi-LopV2noq_pg), the @handle, or the channel link.')
            elif parsed[0] == "handle" and not has_key:
                problems.append(f'YouTube: "{c}" is a @handle; turning it into a channel needs YOUTUBE_API_KEY. '
                                f'Without a key, use the channel ID (UC...) instead.')
        for p in cfg.get("playlist_ids") or []:
            if parse_playlist(p) is None:
                problems.append(f'YouTube: "{p}" is not a playlist ID or playlist link.')
        return problems

    # ------------------------------------------------------------------ Data API helpers (need a key)
    def _api(self, path: str, **params: Any) -> dict[str, Any]:
        return http().get_json(f"{API}/{path}", params={**params, "key": get_config().youtube_api_key},
                               check_robots=False)

    def _resolve_handle(self, handle: str, ctx: CollectContext) -> str | None:
        cache = ctx.state.setdefault("handles", {})
        if handle not in cache:
            items = self._api("channels", part="id", forHandle=handle).get("items") or []
            if not items:
                ctx.log(f"YouTube: no channel found for {handle}")
                return None
            cache[handle] = items[0]["id"]
        return cache[handle]

    def _playlist_page(self, playlist: str, token: str | None) -> tuple[list[dict[str, Any]], str | None]:
        params: dict[str, Any] = {"part": "snippet,contentDetails", "playlistId": playlist, "maxResults": 50}
        if token:
            params["pageToken"] = token
        data = self._api("playlistItems", **params)
        return data.get("items") or [], data.get("nextPageToken")

    def _collect_api(self, ctx: CollectContext, label: str, playlist: str, cfg: dict[str, Any],
                     seen: set[str]) -> Iterator[ResourceIn]:
        """Newest page first (new uploads), then continue the back-catalogue from the saved page token."""
        back = ctx.state.setdefault("backfill", {}).setdefault(playlist, {"token": None, "done": False})
        budget = max(1, int(cfg.get("max_videos_per_run") or 100))
        new_count = 0

        def emit(items: list[dict[str, Any]]) -> Iterator[ResourceIn]:
            nonlocal new_count
            for it in items:
                sn, cd = it.get("snippet") or {}, it.get("contentDetails") or {}
                vid = cd.get("videoId") or (sn.get("resourceId") or {}).get("videoId")
                if not vid or vid in seen or sn.get("title") in ("Private video", "Deleted video"):
                    continue
                seen.add(vid)
                new_count += 1
                yield self._resource(vid, sn.get("title", ""), sn.get("description", ""),
                                     sn.get("videoOwnerChannelTitle") or sn.get("channelTitle"),
                                     cd.get("videoPublishedAt") or sn.get("publishedAt"), ctx.source_key,
                                     ctx.source_id, bool(cfg.get("transcripts")), cfg.get("language"))

        items, first_next = self._playlist_page(playlist, None)
        yield from emit(items)
        if not cfg.get("full_history", True) or back["done"]:
            return
        token = back["token"] or first_next
        while token and new_count < budget and not ctx.should_stop():
            items, nxt = self._playlist_page(playlist, token)
            yield from emit(items)
            token = nxt
            back["token"] = token
        if not token:
            back["done"] = True
            ctx.log(f"YouTube: all older videos of {label} collected")

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

            raise NotConfigured("YouTube search (used by the research agent) needs a free YOUTUBE_API_KEY in .env. "
                                "Channels you add by channel ID work without it; untick Enabled here if you do not need search.")
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
        if not (cfg.get("channel_ids") or cfg.get("playlist_ids")):
            raise ValueError("YouTube source has no channel_ids or playlist_ids configured.")
        has_key = bool(get_config().youtube_api_key)
        targets: list[tuple[str, str]] = []
        for c in cfg.get("channel_ids") or []:
            parsed = parse_channel(c)
            if parsed is None:
                ctx.log(f'YouTube: skipped "{c}": not a channel ID, @handle or channel link')
            elif parsed[0] == "id":
                targets.append(("channel_id", parsed[1]))
            elif not has_key:
                ctx.log(f'YouTube: skipped "{c}": @handles need YOUTUBE_API_KEY; use the UC... channel ID')
            else:
                try:
                    cid = self._resolve_handle(parsed[1], ctx)
                except FetchError as e:
                    ctx.log(f"YouTube: could not look up {parsed[1]}: {e}")
                    cid = None
                if cid:
                    targets.append(("channel_id", cid))
        for p in cfg.get("playlist_ids") or []:
            pid = parse_playlist(p)
            if pid:
                targets.append(("playlist_id", pid))
            else:
                ctx.log(f'YouTube: skipped "{p}": not a playlist ID')
        if not targets:
            raise ValueError("None of the YouTube channels/playlists in this source are valid (see the log).")
        seen = set(ctx.state.get("seen_ids", []))
        for param, value in targets:
            if ctx.should_stop():
                break
            if has_key:
                # a channel's uploads playlist is its ID with UC replaced by UU
                playlist = "UU" + value[2:] if param == "channel_id" else value
                try:
                    yield from self._collect_api(ctx, value, playlist, cfg, seen)
                    continue
                except FetchError as e:
                    ctx.log(f"YouTube API failed for {value} ({e}); using the public feed (newest 15 videos)")
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
        ctx.state["seen_ids"] = list(seen)[-20000:]
