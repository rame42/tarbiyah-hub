"""Social media collectors. Each is independent, with its own credentials and limits.

| Platform  | Method                                        | Credentials                                  |
|-----------|-----------------------------------------------|----------------------------------------------|
| Telegram  | Public channel web preview (t.me/s/<channel>) | none (public channels only)                  |
| Reddit    | Official OAuth API (app-only)                 | REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET      |
| Facebook  | Graph API page posts                          | FACEBOOK_ACCESS_TOKEN (page token / approved app) |
| Instagram | Graph API (own account + business discovery)  | INSTAGRAM_ACCESS_TOKEN + INSTAGRAM_BUSINESS_ACCOUNT_ID |
| X         | API v2 recent search / user timelines         | X_BEARER_TOKEN (paid API tiers)              |
| TikTok    | oEmbed metadata for listed videos; Research API | TIKTOK_CLIENT_KEY/SECRET for Research API (approval required) |

No collector logs in as a user, bypasses login walls/CAPTCHAs or reads private content.
Only posts are collected by default; comments are excluded to avoid gathering personal data.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Iterator
from urllib.parse import quote

from bs4 import BeautifulSoup

from ..config import get_config
from ..http import FetchError, http
from ..ingest.licensing import decide
from ..ingest.registry import ResourceIn
from .base import AdapterInfo, CollectContext, NotConfigured, SourceAdapter, as_year

GRAPH = "https://graph.facebook.com/v19.0"


def _iso(ts: float | int | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(float(ts), tz=timezone.utc).date().isoformat()


def _post(title_text: str, url: str, text: str, platform: str, channel: str | None, date: str | None,
          ext_id: str, ctx: CollectContext | None, method: str, extra: dict[str, Any] | None = None,
          rtype: str = "social_post", source_key: str | None = None) -> ResourceIn:
    title = (title_text or text or url).strip().split("\n")[0][:160] or url
    return ResourceIn(
        title=title,
        resource_type=rtype,
        url=url,
        description=text[:3000] if text else None,
        published_date=date,
        year=as_year(date),
        external_id=ext_id,
        source_key=(ctx.source_key if ctx else None) or source_key or platform,
        source_id=ctx.source_id if ctx else None,
        collection_method=method,
        access=decide(None),
        channel=channel,
        text=text or None,
        extra={"platform": platform, **(extra or {})},
    )


# ------------------------------------------------------------------------------- Telegram

def parse_telegram_page(html: str, channel: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for msg in soup.select("div.tgme_widget_message[data-post]"):
        post = msg.get("data-post", "")
        try:
            mid = int(post.rsplit("/", 1)[-1])
        except ValueError:
            continue
        txt_el = msg.select_one("div.tgme_widget_message_text")
        text = txt_el.get_text("\n", strip=True) if txt_el else ""
        t = msg.select_one("a.tgme_widget_message_date time")
        date = t.get("datetime") if t else None
        links = [a["href"] for a in (txt_el.select("a[href]") if txt_el else []) if a["href"].startswith("http")]
        docs = [d.get_text(" ", strip=True) for d in msg.select("div.tgme_widget_message_document_title")]
        out.append({"id": mid, "text": text, "date": date, "links": links, "documents": docs,
                    "url": f"https://t.me/{post}"})
    return out


class TelegramAdapter(SourceAdapter):
    info = AdapterInfo(
        name="telegram", label="Telegram public channels", kind="social",
        description="Reads public channels through Telegram's public web preview (t.me/s/<channel>): messages, "
                    "links and document titles.",
        capabilities=("monitor",), resource_types=("social_post",),
        optional_credentials=("TELEGRAM_API_ID", "TELEGRAM_API_HASH"),
        access_notes="Only channels with a public web preview. Private groups/chats are never accessed. "
                     "Files shared in channels are listed by title; they are not downloaded.",
        default_schedule_minutes=360, min_interval_seconds=3.0,
        config_fields={"channels": "List of public channel usernames (without @)", "max_pages": "Pages of history per run"},
        default_config={"channels": [], "max_pages": 5},
    )

    def collect(self, ctx: CollectContext) -> Iterator[ResourceIn]:
        cfg = {**self.info.default_config, **(ctx.source_config or {})}
        chans = [c.lstrip("@").strip() for c in cfg.get("channels") or [] if c.strip()]
        if not chans:
            raise ValueError("Telegram source has no channels configured.")
        last: dict[str, int] = dict(ctx.state.get("last_id", {}))
        for ch in chans:
            newest = last.get(ch, 0)
            before = None
            for _ in range(int(cfg.get("max_pages", 5))):
                if ctx.should_stop():
                    break
                base = str(cfg.get("base_url") or "https://t.me").rstrip("/")
                url = f"{base}/s/{quote(ch)}" + (f"?before={before}" if before else "")
                try:
                    res = http().fetch(url, min_interval=self.info.min_interval_seconds)
                except FetchError as e:
                    ctx.log(f"telegram {ch}: {e}")
                    break
                msgs = parse_telegram_page(res.text, ch)
                if not msgs:
                    break
                fresh = [m for m in msgs if m["id"] > last.get(ch, 0)]
                for m in fresh:
                    if not m["text"] and not m["documents"]:
                        continue
                    body = m["text"] + ("\n\nDocuments: " + "; ".join(m["documents"]) if m["documents"] else "")
                    yield _post("", m["url"], body, "telegram", ch, (m["date"] or "")[:10] or None, f"{ch}/{m['id']}",
                                ctx, "telegram_web_preview", {"links": m["links"][:20], "documents": m["documents"]})
                    newest = max(newest, m["id"])
                oldest = min(m["id"] for m in msgs)
                if len(fresh) < len(msgs) or oldest <= 1:
                    break  # reached already-collected history
                before = oldest
            last[ch] = newest
        ctx.state["last_id"] = last


# ------------------------------------------------------------------------------- Reddit

class RedditAdapter(SourceAdapter):
    info = AdapterInfo(
        name="reddit", label="Reddit", kind="social",
        description="Relevant discussions from selected subreddits or site-wide search via the official API.",
        capabilities=("search", "monitor"), resource_types=("social_post",),
        credentials=("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET"),
        access_notes="Free 'script' app at https://www.reddit.com/prefs/apps (non-commercial use). Posts only; "
                     "usernames are kept as public attribution, comments are not collected.",
        languages=("en", "ar"), default_schedule_minutes=720, min_interval_seconds=2.0,
        config_fields={"subreddits": "List of subreddit names", "queries": "Search queries within them"},
        default_config={"subreddits": ["islam", "MuslimLounge", "Parenting"], "queries": ["tarbiyah", "islamic parenting"]},
    )
    _token: tuple[str, float] | None = None

    def _auth(self) -> dict[str, str]:
        self.require()
        cfg = get_config()
        if self._token and self._token[1] > time.time() + 60:
            return {"Authorization": f"bearer {self._token[0]}"}
        res = http().fetch("https://www.reddit.com/api/v1/access_token", method="POST",
                           data={"grant_type": "client_credentials"},
                           auth=(cfg.reddit_client_id, cfg.reddit_client_secret), check_robots=False)
        tok = res.json()
        RedditAdapter._token = (tok["access_token"], time.time() + float(tok.get("expires_in", 3600)))
        return {"Authorization": f"bearer {tok['access_token']}"}

    def _parse(self, d: dict[str, Any], ctx: CollectContext | None) -> ResourceIn:
        text = d.get("selftext") or ""
        url = "https://www.reddit.com" + d.get("permalink", "")
        return _post(d.get("title", ""), url, (d.get("title", "") + "\n\n" + text).strip(), "reddit",
                     "r/" + d.get("subreddit", ""), _iso(d.get("created_utc")), d.get("name") or d.get("id", ""), ctx,
                     "reddit_api", {"score": d.get("score"), "num_comments": d.get("num_comments"),
                                    "linked_url": d.get("url") if d.get("url") != url else None},
                     source_key="reddit")

    def _search(self, path: str, query: str, limit: int, restrict: bool) -> list[dict[str, Any]]:
        params = {"q": query, "limit": min(limit, 50), "sort": "relevance", "t": "all", "type": "link"}
        if restrict:
            params["restrict_sr"] = "1"
        data = http().get_json(f"https://oauth.reddit.com{path}/search", params=params, headers=self._auth(),
                               check_robots=False, min_interval=self.info.min_interval_seconds)
        return [c["data"] for c in (data.get("data") or {}).get("children", [])]

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        return [self._parse(d, None) for d in self._search("", query, limit, False)]

    def collect(self, ctx: CollectContext) -> Iterator[ResourceIn]:
        cfg = {**self.info.default_config, **(ctx.source_config or {})}
        for sub in cfg.get("subreddits") or []:
            for q in cfg.get("queries") or []:
                if ctx.should_stop():
                    return
                for d in self._search(f"/r/{sub}", q, 25, True):
                    yield self._parse(d, ctx)


# ------------------------------------------------------------------------------- Facebook

class FacebookAdapter(SourceAdapter):
    info = AdapterInfo(
        name="facebook", label="Facebook Pages", kind="social",
        description="Posts from Facebook Pages through the Graph API.",
        capabilities=("monitor",), resource_types=("social_post",),
        credentials=("FACEBOOK_ACCESS_TOKEN",),
        access_notes="Requires a Page access token for pages you manage, or a Meta app approved for "
                     "'Page Public Content Access'. Scraping facebook.com is not permitted and not implemented.",
        default_schedule_minutes=720, min_interval_seconds=2.0,
        config_fields={"page_ids": "List of Page IDs or usernames"}, default_config={"page_ids": []},
    )

    def collect(self, ctx: CollectContext) -> Iterator[ResourceIn]:
        self.require()
        token = get_config().facebook_access_token
        cfg = {**self.info.default_config, **(ctx.source_config or {})}
        for page in cfg.get("page_ids") or []:
            url = f"{GRAPH}/{quote(str(page))}/posts"
            params: dict[str, Any] | None = {"fields": "id,message,created_time,permalink_url", "limit": 50,
                                             "access_token": token}
            for _ in range(int(cfg.get("max_pages", 3))):
                data = http().get_json(url, params=params, check_robots=False)
                for p in data.get("data", []):
                    if p.get("message"):
                        yield _post("", p.get("permalink_url") or f"https://facebook.com/{p['id']}", p["message"],
                                    "facebook", str(page), (p.get("created_time") or "")[:10], p["id"], ctx, "graph_api")
                nxt = (data.get("paging") or {}).get("next")
                if not nxt or ctx.should_stop():
                    break
                url, params = nxt, None


# ------------------------------------------------------------------------------- Instagram

class InstagramAdapter(SourceAdapter):
    info = AdapterInfo(
        name="instagram", label="Instagram (Graph API)", kind="social",
        description="Captions and metadata from your Instagram professional account and, via business discovery, "
                    "other public business/creator accounts.",
        capabilities=("monitor",), resource_types=("social_post",),
        credentials=("INSTAGRAM_ACCESS_TOKEN", "INSTAGRAM_BUSINESS_ACCOUNT_ID"),
        access_notes="Requires an Instagram professional account connected to a Meta app. Personal accounts and "
                     "private profiles cannot be collected.",
        default_schedule_minutes=720, min_interval_seconds=2.0,
        config_fields={"usernames": "Business/creator usernames to read via business discovery"},
        default_config={"usernames": []},
    )

    def collect(self, ctx: CollectContext) -> Iterator[ResourceIn]:
        self.require()
        cfg_env = get_config()
        token, ig = cfg_env.instagram_access_token, cfg_env.instagram_business_account_id
        cfg = {**self.info.default_config, **(ctx.source_config or {})}
        for user in cfg.get("usernames") or []:
            fields = f"business_discovery.username({user}){{username,media.limit(50){{id,caption,permalink,timestamp,media_type}}}}"
            data = http().get_json(f"{GRAPH}/{ig}", params={"fields": fields, "access_token": token}, check_robots=False)
            media = (((data.get("business_discovery") or {}).get("media")) or {}).get("data", [])
            for m in media:
                if m.get("caption"):
                    yield _post("", m.get("permalink", ""), m["caption"], "instagram", user,
                                (m.get("timestamp") or "")[:10], m["id"], ctx, "graph_api",
                                {"media_type": m.get("media_type")})


# ------------------------------------------------------------------------------- X / Twitter

class XAdapter(SourceAdapter):
    info = AdapterInfo(
        name="x", label="X (Twitter)", kind="social",
        description="Recent posts matching queries or from selected accounts via the X API v2.",
        capabilities=("search", "monitor"), resource_types=("social_post",),
        credentials=("X_BEARER_TOKEN",), paid=True,
        access_notes="X API read access requires a paid tier. Disabled until a bearer token is configured.",
        default_schedule_minutes=1440, min_interval_seconds=3.0,
        config_fields={"queries": "Search queries", "usernames": "Accounts to follow"},
        default_config={"queries": [], "usernames": []},
    )
    API = "https://api.twitter.com/2"

    def _headers(self) -> dict[str, str]:
        self.require()
        return {"Authorization": f"Bearer {get_config().x_bearer_token}"}

    def _parse(self, data: dict[str, Any], ctx: CollectContext | None) -> list[ResourceIn]:
        users = {u["id"]: u for u in (data.get("includes") or {}).get("users", [])}
        out = []
        for t in data.get("data", []) or []:
            u = users.get(t.get("author_id"), {})
            handle = u.get("username", "i")
            out.append(_post("", f"https://x.com/{handle}/status/{t['id']}", t.get("text", ""), "x", "@" + handle,
                             (t.get("created_at") or "")[:10], t["id"], ctx, "x_api_v2", {"lang": t.get("lang")},
                             source_key="x"))
        return out

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        q = f"({query}) -is:retweet" + (f" lang:{lang}" if lang in ("ar", "en") else "")
        data = http().get_json(f"{self.API}/tweets/search/recent", headers=self._headers(), check_robots=False,
                               params={"query": q, "max_results": max(10, min(limit, 100)),
                                       "tweet.fields": "created_at,lang,author_id", "expansions": "author_id",
                                       "user.fields": "username,name"})
        return self._parse(data, None)

    def collect(self, ctx: CollectContext) -> Iterator[ResourceIn]:
        cfg = {**self.info.default_config, **(ctx.source_config or {})}
        for q in cfg.get("queries") or []:
            yield from self.search(q, None, 50)
        for name in cfg.get("usernames") or []:
            u = http().get_json(f"{self.API}/users/by/username/{quote(name)}", headers=self._headers(), check_robots=False)
            uid = (u.get("data") or {}).get("id")
            if uid:
                data = http().get_json(f"{self.API}/users/{uid}/tweets", headers=self._headers(), check_robots=False,
                                       params={"max_results": 50, "tweet.fields": "created_at,lang,author_id",
                                               "expansions": "author_id", "user.fields": "username"})
                yield from self._parse(data, ctx)


# ------------------------------------------------------------------------------- TikTok

class TikTokAdapter(SourceAdapter):
    info = AdapterInfo(
        name="tiktok", label="TikTok", kind="video",
        description="Metadata for listed public videos via oEmbed (no key); keyword search with transcripts "
                    "(voice_to_text) via the TikTok Research API when approved credentials are configured.",
        capabilities=("search", "monitor"), resource_types=("video",),
        optional_credentials=("TIKTOK_CLIENT_KEY", "TIKTOK_CLIENT_SECRET"),
        access_notes="oEmbed gives title and author only. The Research API is limited to approved researchers; "
                     "transcripts are available only through it.",
        default_schedule_minutes=1440, min_interval_seconds=2.0,
        config_fields={"video_urls": "List of TikTok video URLs to catalogue"}, default_config={"video_urls": []},
    )

    def _research_token(self) -> str:
        cfg = get_config()
        if not (cfg.tiktok_client_key and cfg.tiktok_client_secret):
            raise NotConfigured("TikTok Research API needs TIKTOK_CLIENT_KEY and TIKTOK_CLIENT_SECRET (approved access).")
        res = http().fetch("https://open.tiktokapis.com/v2/oauth/token/", method="POST", check_robots=False,
                           data={"client_key": cfg.tiktok_client_key, "client_secret": cfg.tiktok_client_secret,
                                 "grant_type": "client_credentials"},
                           headers={"Content-Type": "application/x-www-form-urlencoded"})
        return res.json()["access_token"]

    def search(self, query: str, lang: str | None, limit: int) -> list[ResourceIn]:
        import json as _json

        token = self._research_token()
        end = datetime.now(timezone.utc)
        start = end.replace(year=end.year - 1) if end.month != 2 or end.day != 29 else end.replace(year=end.year - 1, day=28)
        body = {"query": {"and": [{"operation": "IN", "field_name": "keyword", "field_values": [query]}]},
                "start_date": start.strftime("%Y%m%d"), "end_date": end.strftime("%Y%m%d"),
                "max_count": min(limit, 100)}
        res = http().fetch("https://open.tiktokapis.com/v2/research/video/query/"
                           "?fields=id,video_description,create_time,username,voice_to_text",
                           method="POST", data=_json.dumps(body), check_robots=False,
                           headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
        out = []
        for v in ((res.json().get("data") or {}).get("videos") or []):
            text = (v.get("video_description") or "") + ("\n\nTranscript: " + v["voice_to_text"] if v.get("voice_to_text") else "")
            out.append(_post(v.get("video_description", ""), f"https://www.tiktok.com/@{v.get('username')}/video/{v['id']}",
                             text, "tiktok", "@" + str(v.get("username")), _iso(v.get("create_time")), str(v["id"]),
                             None, "tiktok_research_api", {"transcript": bool(v.get("voice_to_text"))}, rtype="video",
                             source_key="tiktok"))
        return out

    def collect(self, ctx: CollectContext) -> Iterator[ResourceIn]:
        cfg = {**self.info.default_config, **(ctx.source_config or {})}
        for url in cfg.get("video_urls") or []:
            try:
                o = http().get_json("https://www.tiktok.com/oembed", params={"url": url}, check_robots=False)
            except FetchError as e:
                ctx.log(f"oEmbed failed for {url}: {e}")
                continue
            yield _post(o.get("title", ""), url, o.get("title", ""), "tiktok", o.get("author_name"), None, url, ctx,
                        "tiktok_oembed", {"author_url": o.get("author_url"), "transcript": False}, rtype="video")
