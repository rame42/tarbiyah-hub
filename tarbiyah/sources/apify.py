"""Apify connector: run any Apify Actor (TikTok, YouTube, Facebook, Instagram, X, Reddit,
Telegram, websites...) and import the items it returns.

How it works
1. Start the Actor run with your input JSON (POST /v2/acts/{actor}/runs) and caps on
   items (maxItems), spend (maxTotalChargeUsd) and duration (timeout).
2. Save the run id as a checkpoint, so a restarted worker keeps polling the SAME run
   instead of paying for a new one.
3. Poll until it finishes, then read its dataset (GET /v2/datasets/{id}/items).
4. Map each item to a resource (URL, text, author, date, transcript), using built-in
   field guesses or the source's own `field_map`.

Apify runs cost money (Apify bills your account). Nothing runs without APIFY_TOKEN, and
every run counts against the daily limits in Settings (apify_daily_run_limit,
apify_max_items_per_run, apify_max_charge_usd_per_run). Use Actors only for public content and
in line with each platform's terms.
"""
from __future__ import annotations

import json
import time
from typing import Any, Iterator
from urllib.parse import quote

from ..config import get_config
from ..http import BudgetExceeded, FetchError, http
from ..ingest.licensing import decide
from ..ingest.registry import ResourceIn
from ..settings import get_setting, record_usage
from .base import AdapterInfo, CollectContext, NotConfigured, SourceAdapter, as_year

FINISHED = {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}

# Starting points per platform. Actor input formats change: always compare with the Actor's
# "Input" tab (JSON view) in Apify Console and adjust the source config.
PRESETS: dict[str, dict[str, Any]] = {
    "tiktok": {"actor": "clockworks/tiktok-scraper", "platform": "tiktok", "resource_type": "video",
               "input": {"searchQueries": ["تربية الأطفال"], "resultsPerPage": 20, "shouldDownloadSubtitles": True,
                         "shouldDownloadVideos": False, "shouldDownloadCovers": False}},
    "youtube": {"actor": "streamers/youtube-scraper", "platform": "youtube", "resource_type": "video",
                "input": {"searchQueries": ["islamic parenting", "تربية الأبناء"], "maxResults": 20,
                          "downloadSubtitles": True, "subtitlesLanguage": "any"}},
    "facebook": {"actor": "apify/facebook-posts-scraper", "platform": "facebook", "resource_type": "social_post",
                 "input": {"startUrls": [{"url": "https://www.facebook.com/<public-page>"}], "resultsLimit": 20}},
    "instagram": {"actor": "apify/instagram-scraper", "platform": "instagram", "resource_type": "social_post",
                  "input": {"directUrls": ["https://www.instagram.com/<public-account>/"], "resultsType": "posts",
                            "resultsLimit": 20}},
    "x": {"actor": "apidojo/tweet-scraper", "platform": "x", "resource_type": "social_post",
          "input": {"searchTerms": ["تربية الأبناء"], "maxItems": 50}},
    "reddit": {"actor": "trudax/reddit-scraper-lite", "platform": "reddit", "resource_type": "social_post",
               "input": {"searches": ["islamic parenting"], "maxItems": 50, "skipComments": True}},
    "website": {"actor": "apify/website-content-crawler", "platform": "web", "resource_type": "article",
                "input": {"startUrls": [{"url": "https://example.org/articles"}], "maxCrawlPages": 50}},
}

# Field names commonly used by popular Actors, tried in order. Dotted paths reach nested fields.
GUESS = {
    "url": ["url", "webVideoUrl", "postUrl", "link", "permalink", "videoUrl", "facebookUrl", "twitterUrl",
            "inputUrl", "loadedUrl"],
    "title": ["title", "name", "headline"],
    "text": ["text", "caption", "description", "message", "fullText", "postText", "content", "body", "markdown"],
    "author": ["authorMeta.name", "authorMeta.nickName", "channelName", "ownerUsername", "author.userName",
               "author.name", "user.name", "pageName", "username", "authorName", "author", "communityName"],
    "date": ["createTimeISO", "date", "uploadDate", "publishedAt", "timestamp", "time", "createdAt", "created_at"],
    "id": ["id", "videoId", "postId", "shortCode", "tweetId"],
    "transcript": ["transcript", "subtitles", "captions", "videoMeta.subtitleLinks"],
    "language": ["language", "lang", "textLanguage"],
}


def get_path(item: Any, path: str) -> Any:
    cur = item
    for part in path.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return None
    return cur


def pick(item: dict[str, Any], field: str, field_map: dict[str, str]) -> Any:
    if field in field_map:
        return get_path(item, field_map[field])
    for path in GUESS[field]:
        v = get_path(item, path)
        if v not in (None, "", [], {}):
            return v
    return None


def transcript_segments(value: Any) -> list[dict[str, Any]] | None:
    """Accept plain text, a list of strings, or a list of {text|plaintext|srt, start} objects."""
    if not value:
        return None
    if isinstance(value, str):
        return [{"text": value}] if value.strip() and not value.startswith("http") else None
    if isinstance(value, list):
        segs = []
        for v in value:
            if isinstance(v, str) and v.strip() and not v.startswith("http"):
                segs.append({"text": v})
            elif isinstance(v, dict):
                t = v.get("text") or v.get("plaintext") or v.get("srt")
                if isinstance(t, str) and t.strip():
                    start = v.get("start") or v.get("offset")
                    segs.append({"text": t, "timestamp": float(start) if isinstance(start, (int, float)) else None})
        return segs or None
    return None


def item_to_resource(item: dict[str, Any], cfg: dict[str, Any], source_key: str | None,
                     source_id: int | None) -> ResourceIn | None:
    fm = cfg.get("field_map") or {}
    url = pick(item, "url", fm)
    text = pick(item, "text", fm)
    if isinstance(text, list):
        text = "\n".join(str(t) for t in text)
    if not url and not text:
        return None
    title = pick(item, "title", fm) or (str(text).strip().split("\n")[0][:160] if text else url)
    author = pick(item, "author", fm)
    if isinstance(author, dict):
        author = author.get("name") or author.get("userName") or author.get("username")
    date = pick(item, "date", fm)
    if isinstance(date, (int, float)):  # epoch seconds or milliseconds
        from datetime import datetime, timezone

        date = datetime.fromtimestamp(date / 1000 if date > 1e11 else date, tz=timezone.utc).isoformat()
    date = str(date)[:10] if date else None
    segs = transcript_segments(pick(item, "transcript", fm))
    platform = cfg.get("platform") or "apify"
    ext = pick(item, "id", fm)
    lang = pick(item, "language", fm)
    return ResourceIn(
        title=str(title)[:500],
        resource_type=cfg.get("resource_type") or "social_post",
        url=str(url) if url else None,
        authors=[str(author)] if author and cfg.get("author_is_creator", True) else [],
        description=str(text)[:3000] if text else None,
        language=lang if lang in ("ar", "en") else cfg.get("language"),
        published_date=date,
        year=as_year(date),
        external_id=f"{platform}:{ext}" if ext else None,
        source_key=source_key,
        source_id=source_id,
        collection_method=f"apify:{cfg.get('actor')}",
        access=decide(None),
        channel=str(author) if author else None,
        text=str(text) if text and not segs else None,
        segments=([{"text": str(text)}] if text else []) + segs if segs else None,
        extra={"platform": platform, "apify_actor": cfg.get("actor"), "transcript": bool(segs),
               "inline_method": "apify"},
    )


class ApifyAdapter(SourceAdapter):
    info = AdapterInfo(
        name="apify", label="Apify Actor (TikTok, YouTube, Facebook, Instagram, X, Reddit, websites)",
        kind="social",
        description="Runs an Apify Actor with your input and imports its results (posts, videos, captions, pages). "
                    "One source per Actor configuration.",
        capabilities=("monitor", "search"), resource_types=("social_post", "video", "article"),
        credentials=("APIFY_TOKEN",), paid=True,
        access_notes="Apify bills your account per run (free plan includes monthly credit). Runs are capped by "
                     "the Apify limits in Settings. Collect public content only and follow each platform's terms.",
        default_schedule_minutes=1440, min_interval_seconds=1.0, seed_search_source=False,
        config_fields={
            "actor": "Actor ID, e.g. clockworks/tiktok-scraper (from the Actor's page)",
            "input": "Actor input JSON (copy from the Actor's Input tab > JSON)",
            "platform": "tiktok | youtube | facebook | instagram | x | reddit | web",
            "resource_type": "social_post | video | article",
            "max_items": "Items per run (also caps cost on pay-per-result Actors)",
            "use_for_research": "true = also run this Actor for research questions (costs per question)",
            "search_input": "Input used for research questions; write {query} where the search text goes",
            "field_map": "Optional: {\"url\": \"path\", \"text\": \"path\", \"author\": \"path\", \"date\": \"path\"}",
            "language": "Language hint (ar / en)",
        },
        default_config={"actor": "", "input": {}, "platform": "", "resource_type": "social_post", "max_items": 30,
                        "use_for_research": False, "search_input": {}, "field_map": {}},
    )

    # ------------------------------------------------------------------ API calls
    @staticmethod
    def _base() -> str:
        return (get_config().apify_base_url or "https://api.apify.com").rstrip("/")

    def _headers(self) -> dict[str, str]:
        self.require()
        return {"Authorization": f"Bearer {get_config().apify_token}", "Content-Type": "application/json"}

    def _check_budget(self) -> None:
        from ..db import session_scope
        from ..settings import within_budget

        with session_scope() as s:
            if not within_budget(s, "apify_runs"):
                raise BudgetExceeded("Daily Apify run limit reached (Settings > apify_daily_run_limit).")

    def start_run(self, actor: str, run_input: dict[str, Any], max_items: int) -> dict[str, Any]:
        self._check_budget()
        cap_items = min(int(max_items), int(get_setting("apify_max_items_per_run")))
        params = {"maxItems": cap_items, "maxTotalChargeUsd": float(get_setting("apify_max_charge_usd_per_run")),
                  "timeout": int(get_setting("apify_run_timeout_seconds"))}
        res = http().fetch(f"{self._base()}/v2/acts/{quote(actor.replace('/', '~'), safe='~')}/runs", method="POST",
                           params=params, data=json.dumps(run_input), headers=self._headers(), check_robots=False,
                           retries=1, timeout=60)
        record_usage("apify_runs")
        return res.json()["data"]

    def get_run(self, run_id: str) -> dict[str, Any]:
        return http().get_json(f"{self._base()}/v2/actor-runs/{quote(run_id)}", headers=self._headers(),
                               check_robots=False, min_interval=0.5)["data"]

    def dataset_items(self, dataset_id: str, limit: int) -> list[dict[str, Any]]:
        data = http().get_json(f"{self._base()}/v2/datasets/{quote(dataset_id)}/items",
                               params={"clean": "true", "format": "json", "limit": limit},
                               headers=self._headers(), check_robots=False)
        return data if isinstance(data, list) else data.get("items", [])

    def run_and_wait(self, actor: str, run_input: dict[str, Any], max_items: int, run_id: str | None = None,
                     save: Any = None, should_stop: Any = None, poll_seconds: float = 10.0,
                     on_poll: Any = None) -> list[dict[str, Any]]:
        if not run_id:
            run = self.start_run(actor, run_input, max_items)
            run_id = run["id"]
            if save:
                save(run_id)
        deadline = time.monotonic() + int(get_setting("apify_run_timeout_seconds")) + 300
        while True:
            run = self.get_run(run_id)
            status = run.get("status")
            if status in FINISHED:
                break
            if on_poll:
                on_poll()  # keeps the job lease alive during long runs
            if (should_stop and should_stop()) or time.monotonic() > deadline:
                raise TimeoutError(f"Apify run {run_id} still {status}; it will be picked up again on the next attempt.")
            time.sleep(poll_seconds)
        if status != "SUCCEEDED":
            raise FetchError(f"Apify run {run_id} ended with status {status}: {run.get('statusMessage') or ''}")
        return self.dataset_items(run["defaultDatasetId"], max_items)

    # ------------------------------------------------------------------ adapter interface
    def collect(self, ctx: CollectContext) -> Iterator[ResourceIn]:
        cfg = {**self.info.default_config, **(ctx.source_config or {})}
        if not cfg.get("actor"):
            raise ValueError("Apify source has no 'actor' configured (e.g. clockworks/tiktok-scraper).")
        self.require()
        try:
            items = self.run_and_wait(
                cfg["actor"], cfg.get("input") or {}, int(cfg.get("max_items") or 30),
                run_id=ctx.checkpoint.get("apify_run_id"),
                save=lambda rid: ctx.save_checkpoint({**ctx.checkpoint, "apify_run_id": rid}),
                should_stop=ctx.should_stop, poll_seconds=float(cfg.get("poll_seconds", 10)),
                on_poll=lambda: ctx.save_checkpoint(ctx.checkpoint))
        except FetchError:
            # the run failed on Apify's side: forget it so the retry starts a fresh run
            ctx.save_checkpoint({k: v for k, v in ctx.checkpoint.items() if k != "apify_run_id"})
            raise
        ctx.log(f"Apify run returned {len(items)} item(s)")
        for item in items:
            d = item_to_resource(item, cfg, ctx.source_key, ctx.source_id)
            if d is not None:
                yield d

    def search_with(self, cfg: dict[str, Any], query: str, lang: str | None, limit: int,
                    source_key: str | None, source_id: int | None) -> list[ResourceIn]:
        template = cfg.get("search_input") or {}
        if not template:
            raise NotConfigured("This Apify source has no 'search_input' with a {query} placeholder.")
        filled = json.loads(json.dumps(template, ensure_ascii=False).replace("{query}", query.replace('"', "'")))
        items = self.run_and_wait(cfg["actor"], filled, min(limit, int(cfg.get("max_items") or 30)),
                                  poll_seconds=float(cfg.get("poll_seconds", 10)))
        out = []
        for item in items:
            d = item_to_resource(item, cfg, source_key, source_id)
            if d is not None:
                out.append(d)
        return out

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        raise NotConfigured("Apify searches run through a configured Apify source with use_for_research=true.")
