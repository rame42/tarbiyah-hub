"""RSS / Atom feeds: blogs, institutional news, podcasts (with published transcripts)."""
from __future__ import annotations

import calendar
import re
from datetime import datetime, timezone
from typing import Any, Iterator

import feedparser
from lxml import etree

from ..http import FetchError, http
from ..ingest.extract import extract_html
from ..ingest.licensing import decide
from ..ingest.registry import ResourceIn
from .base import AdapterInfo, CollectContext, SourceAdapter


def _date(entry: Any) -> tuple[str | None, int | None, float | None]:
    st = entry.get("published_parsed") or entry.get("updated_parsed")
    if not st:
        return None, None, None
    ts = calendar.timegm(st)
    d = datetime.fromtimestamp(ts, tz=timezone.utc)
    return d.date().isoformat(), d.year, ts


def _html_to_text(html: str) -> str:
    if not html:
        return ""
    if "<" not in html:
        return html.strip()
    return extract_html(f"<html><body><article>{html}</article></body></html>").full_text


def podcast_transcripts(xml: bytes) -> dict[str, list[dict[str, str]]]:
    """Map item guid/link -> [{url, type, language}] from <podcast:transcript> tags."""
    out: dict[str, list[dict[str, str]]] = {}
    try:
        root = etree.fromstring(xml, parser=etree.XMLParser(recover=True, resolve_entities=False, no_network=True))
    except etree.XMLSyntaxError:
        return out
    if root is None:
        return out
    for item in root.iter("item"):
        key = None
        for tag in ("guid", "link"):
            el = item.find(tag)
            if el is not None and el.text:
                key = el.text.strip()
                break
        trs = [dict(el.attrib) for el in item.iter() if isinstance(el.tag, str) and el.tag.endswith("}transcript")]
        if key and trs:
            out[key] = trs
    return out


def parse_transcript(content: bytes, kind: str) -> list[dict[str, Any]]:
    """Parse WebVTT/SRT/plain/HTML transcripts into timestamped segments."""
    text = content.decode("utf-8", errors="replace")
    if "html" in kind:
        return [{"text": _html_to_text(text)}]
    if "vtt" in kind or "srt" in kind or "-->" in text:
        segs: list[dict[str, Any]] = []
        for block in re.split(r"\n\s*\n", text):
            m = re.search(r"(\d+):(\d{2}):(\d{2})[.,](\d{3})\s*-->", block) or \
                re.search(r"(\d{2}):(\d{2})[.,](\d{3})\s*-->", block)
            lines = [ln for ln in block.splitlines() if "-->" not in ln and not ln.strip().isdigit()
                     and not ln.startswith("WEBVTT")]
            if not lines:
                continue
            ts = None
            if m:
                g = [int(x) for x in m.groups()]
                ts = g[0] * 3600 + g[1] * 60 + g[2] if len(g) == 4 else g[0] * 60 + g[1]
            segs.append({"text": " ".join(lines).strip(), "timestamp": ts})
        merged: list[dict[str, Any]] = []
        for sgm in segs:  # merge cues into ~1-minute segments that keep their start time
            if merged and sgm["timestamp"] is not None and merged[-1]["timestamp"] is not None \
                    and sgm["timestamp"] - merged[-1]["timestamp"] < 60:
                merged[-1]["text"] += " " + sgm["text"]
            else:
                merged.append(dict(sgm))
        return merged
    return [{"text": text}]


class RssAdapter(SourceAdapter):
    info = AdapterInfo(
        name="rss", label="RSS / Atom feed (blogs, news, podcasts)", kind="feed",
        description="Monitors one or more feeds for new posts and podcast episodes. Optionally reads the "
                    "full public article page for indexing.",
        capabilities=("monitor",), resource_types=("article", "podcast_episode", "video"),
        access_notes="Feeds are published for syndication. Podcast audio is not downloaded; published "
                     "transcripts (<podcast:transcript>) are collected when available.",
        default_schedule_minutes=360, min_interval_seconds=2.0, required_config=(("feeds", "url"),),
        config_fields={"feeds": "List of feed URLs", "fetch_full_text": "Read the full article page (true/false)",
                       "resource_type": "Type for items (article / podcast_episode)", "language": "Language hint"},
        default_config={"feeds": [], "fetch_full_text": True},
    )

    def entry_to_resource(self, e: Any, feed_title: str, cfg: dict[str, Any], ctx: CollectContext,
                          transcripts: dict[str, list[dict[str, str]]]) -> ResourceIn:
        date, year, _ = _date(e)
        content = ""
        if e.get("content"):
            content = _html_to_text(e["content"][0].get("value", ""))
        summary = _html_to_text(e.get("summary", ""))
        audio = next((enc.get("href") for enc in e.get("enclosures", []) if (enc.get("type") or "").startswith("audio")), None)
        video = next((enc.get("href") for enc in e.get("enclosures", []) if (enc.get("type") or "").startswith("video")), None)
        rtype = cfg.get("resource_type") or ("podcast_episode" if audio else "article")
        key = (e.get("id") or e.get("link") or "").strip()
        segments = None
        tr_info = transcripts.get(key) or transcripts.get(e.get("link", ""))
        if tr_info:
            tr = sorted(tr_info, key=lambda t: 0 if "vtt" in t.get("type", "") or "srt" in t.get("type", "") else 1)[0]
            try:
                res = http().fetch(tr["url"], max_bytes=5_000_000)
                segments = parse_transcript(res.content, tr.get("type", "") or res.content_type)
            except FetchError as ex:
                ctx.log(f"transcript fetch failed: {ex}")
        text = content if len(content) > len(summary) else summary
        extra: dict[str, Any] = {"feed": feed_title, "audio_url": audio, "video_url": video,
                                 "has_transcript": bool(segments)}
        if cfg.get("fetch_full_text", True) and rtype == "article" and len(text) < 1500 and e.get("link"):
            extra["fetch_page"] = True  # processing reads the public page itself
            text = ""
        authors = [a.get("name") for a in e.get("authors", []) if a.get("name")] or ([e["author"]] if e.get("author") else [])
        return ResourceIn(
            title=e.get("title") or "(untitled)",
            resource_type=rtype,
            url=e.get("link"),
            authors=authors,
            description=summary[:3000] or None,
            language=cfg.get("language"),
            published_date=date,
            year=year,
            publisher=feed_title,
            external_id=key or None,
            source_key=ctx.source_key,
            source_id=ctx.source_id,
            collection_method="rss",
            access=decide(e.get("rights") or cfg.get("license")),
            license=e.get("rights"),
            keywords=[t.get("term") for t in e.get("tags", []) if t.get("term")][:10],
            text=text or None,
            segments=segments,
            channel=feed_title,
            extra=extra,
        )

    def collect(self, ctx: CollectContext) -> Iterator[ResourceIn]:
        cfg = {**self.info.default_config, **(ctx.source_config or {})}
        feeds = cfg.get("feeds") or ([cfg["url"]] if cfg.get("url") else [])
        if not feeds:
            raise ValueError("RSS source has no feeds configured.")
        seen: dict[str, float] = dict(ctx.state.get("last_seen", {}))
        for url in feeds:
            if ctx.should_stop():
                break
            try:
                res = http().fetch(url, max_bytes=15_000_000)
            except FetchError as e:
                ctx.log(f"feed failed {url}: {e}")
                continue
            parsed = feedparser.parse(res.content)
            if parsed.bozo and not parsed.entries:
                ctx.log(f"not a valid feed: {url}")
                continue
            feed_title = parsed.feed.get("title") or url
            transcripts = podcast_transcripts(res.content)
            newest = seen.get(url, 0.0)
            for e in parsed.entries[: int(cfg.get("max_items", 100))]:
                _, _, ts = _date(e)
                if ts and ts <= seen.get(url, 0.0):
                    continue  # already collected in a previous run (dedupe also happens by URL)
                yield self.entry_to_resource(e, feed_title, cfg, ctx, transcripts)
                newest = max(newest, ts or 0.0)
            seen[url] = newest
            ctx.state["last_seen"] = seen
