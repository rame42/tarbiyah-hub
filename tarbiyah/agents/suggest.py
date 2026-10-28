"""Source suggestions: learn from the sources the person added and propose similar ones.

Evidence comes only from what those sources already collected (no extra browsing):
- YouTube channels mentioned in collected video descriptions (youtube.com/@name, /channel/UC...);
- Telegram channels linked or mentioned in collected posts (t.me/name);
- websites that the monitored websites (and posts/videos) keep linking to.
A suggestion's score = number of collected items mentioning it x their average relevance, so channels
mentioned by relevant material rank first. The person adds suggestions with one click; with
auto_add_sources on, strong suggestions are added automatically (their items are still filtered
by relevance, unlike the person's own sources)."""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import utcnow
from ..ingest.manage import is_my_source
from ..models import Resource, Setting, Source
from ..settings import get_setting

KEY = "_source_suggestions"
YT = re.compile(r"(?:youtube\.com/(?:c/|user/)?(@[\w.\-]{3,60}|channel/(UC[\w-]{22})))", re.I)
TG = re.compile(r"(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z][A-Za-z0-9_]{4,31})\b", re.I)
URL = re.compile(r"https?://[^\s<>\"')\]]+")
TG_RESERVED = {"joinchat", "share", "addstickers", "addlist", "proxy", "socks", "iv", "setlanguage", "contact", "boost"}
# big platforms are not "websites to monitor"
PLATFORMS = ("youtube.com", "youtu.be", "facebook.com", "fb.com", "instagram.com", "twitter.com", "x.com", "t.me",
             "telegram.me", "tiktok.com", "linkedin.com", "whatsapp.com", "wa.me", "google.com", "goo.gl", "bit.ly",
             "apple.com", "amazon.", "wikipedia.org", "wikimedia.org", "pinterest.", "snapchat.com", "soundcloud.com",
             "spotify.com", "play.google.com", "microsoft.com", "creativecommons.org", "doi.org", "archive.org",
             "github.com", "paypal.", "patreon.com", "linktr.ee", "tinyurl.com", "wordpress.com", "blogspot.com")


def _host(url: str) -> str:
    try:
        h = (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""
    return h[4:] if h.startswith("www.") else h


def _existing(session: Session) -> dict[str, set[str]]:
    have: dict[str, set[str]] = {"youtube": set(), "telegram": set(), "web": set()}
    for src in session.execute(select(Source)).scalars():
        cfg = src.config or {}
        if src.adapter == "youtube":
            for c in (cfg.get("channel_ids") or []) + (cfg.get("video_urls") or []):
                have["youtube"].add(str(c).strip().lower().split("/")[-1])
        elif src.adapter == "telegram":
            have["telegram"] |= {str(c).lstrip("@").lower() for c in cfg.get("channels") or []}
        elif src.adapter == "web_crawler":
            have["web"] |= {_host(u) for u in cfg.get("start_urls") or []} | \
                           {str(d).lower().removeprefix("www.") for d in cfg.get("allowed_domains") or []}
    return have


def _state(session: Session) -> dict[str, Any]:
    row = session.get(Setting, KEY)
    return dict(row.value or {}) if row else {"items": {}, "dismissed": []}


def _save(session: Session, st: dict[str, Any]) -> None:
    row = session.get(Setting, KEY)
    if row is None:
        session.add(Setting(key=KEY, value=st))
    else:
        row.value = dict(st)


def find_suggestions(session: Session, per_source_items: int = 400) -> dict[str, Any]:
    mine = [s for s in session.execute(select(Source)).scalars() if is_my_source(s)]
    have = _existing(session)
    st = _state(session)
    dismissed = set(st.get("dismissed") or [])
    found: dict[str, dict[str, Any]] = {}
    ev_items: dict[str, set[int]] = defaultdict(set)
    ev_sources: dict[str, set[str]] = defaultdict(set)
    rel_sum: dict[str, float] = defaultdict(float)

    def note(key: str, base: dict[str, Any], r: Resource, src: Source) -> None:
        if key in dismissed:
            return
        found.setdefault(key, base)
        if r.id not in ev_items[key]:
            ev_items[key].add(r.id)
            rel_sum[key] += r.relevance if r.relevance is not None else 30
        ev_sources[key].add(src.name)

    for src in mine:
        own_hosts = {_host(u) for u in (src.config or {}).get("start_urls") or []}
        rows = session.execute(select(Resource).where(Resource.source_id == src.id, Resource.deleted.is_(False))
                               .order_by(Resource.discovered_at.desc()).limit(per_source_items)).scalars()
        for r in rows:
            ex = r.extra or {}
            links = [str(x) for x in (ex.get("outlinks") or []) + (ex.get("links") or [])]
            links += URL.findall(r.description or "")  # websites named in video descriptions or posts
            text = " ".join([r.description or "", " ".join(links)])
            for m in YT.finditer(text):
                handle, uc = m.group(1), m.group(2)
                ident = uc or handle
                if ident.lower().split("/")[-1] in have["youtube"]:
                    continue
                note(f"youtube:{ident.lower()}", {"adapter": "youtube", "name": ident if not uc else f"YouTube {uc}",
                                                  "config": {"channel_ids": [ident if not uc else uc]},
                                                  "link": f"https://www.youtube.com/{ident if not uc else 'channel/' + uc}"},
                     r, src)
            for m in TG.finditer(text):
                name = m.group(1)
                if name.lower() in TG_RESERVED or name.lower() in have["telegram"] or name.lower().endswith("bot"):
                    continue
                note(f"telegram:{name.lower()}", {"adapter": "telegram", "name": f"Telegram @{name}",
                                                   "config": {"channels": [name]}, "link": f"https://t.me/s/{name}"},
                     r, src)
            for u in links:
                h = _host(u)
                if (not h or "." not in h or h in have["web"] or h in own_hosts
                        or any(h == p or h.endswith("." + p) or (p.endswith(".") and p in h) for p in PLATFORMS)):
                    continue
                note(f"web:{h}", {"adapter": "web_crawler", "name": h,
                                  "config": {"start_urls": [f"https://{h}/"], "allowed_domains": [h]},
                                  "link": f"https://{h}/"}, r, src)

    items = {}
    for key, base in found.items():
        n = len(ev_items[key])
        if n < 2:  # mentioned once is not a pattern
            continue
        avg = rel_sum[key] / n
        prev = (st.get("items") or {}).get(key, {})
        items[key] = {**base, "key": key, "mentions": n, "avg_relevance": round(avg),
                      "score": round(n * max(avg, 5) / 10, 1), "from_sources": sorted(ev_sources[key])[:5],
                      "status": prev.get("status", "new"), "first_seen": prev.get("first_seen") or utcnow().isoformat()}
    for key, prev in (st.get("items") or {}).items():  # keep added ones visible
        if prev.get("status") == "added" and key not in items:
            items[key] = prev
    st = {"items": items, "dismissed": sorted(dismissed), "updated_at": utcnow().isoformat()}
    _save(session, st)
    added = auto_add(session) if get_setting("auto_add_sources", session) else []
    return {"suggestions": sum(1 for x in items.values() if x["status"] == "new"), "auto_added": added}


def due(session: Session, hours: int = 6) -> bool:
    from datetime import datetime, timedelta

    last = _state(session).get("updated_at")
    try:
        return not last or utcnow() - datetime.fromisoformat(last) > timedelta(hours=hours)
    except ValueError:
        return True


def list_suggestions(session: Session) -> list[dict[str, Any]]:
    st = _state(session)
    return sorted((x for x in (st.get("items") or {}).values() if x.get("status") == "new"),
                  key=lambda x: -x.get("score", 0))


def add_suggestion(session: Session, key: str, by: str = "user") -> Source:
    from ..sources.registry import ADAPTERS

    st = _state(session)
    item = (st.get("items") or {}).get(key)
    if item is None:
        raise KeyError(key)
    a = ADAPTERS[item["adapter"]]
    skey = re.sub(r"[^a-z0-9]+", "-", f"{item['adapter']}-{item['name']}".lower()).strip("-")[:100]
    n = 1
    while session.execute(select(Source).where(Source.key == skey)).first():
        n += 1
        skey = f"{skey[:95]}-{n}"
    cfg = {**a.info.default_config, **item["config"], "role": "monitor", "added_by": by,
           "suggested_because": f"mentioned in {item['mentions']} item(s) from {', '.join(item['from_sources'])}"}
    src = Source(key=skey, adapter=item["adapter"], name=item["name"], enabled=True, config=cfg,
                 schedule_minutes=a.info.default_schedule_minutes,
                 health="ready" if a.is_configured() and not a.config_problems(cfg) else "needs_credentials")
    session.add(src)
    item["status"] = "added"
    st["items"][key] = item
    _save(session, st)
    session.flush()
    return src


def dismiss_suggestion(session: Session, key: str) -> None:
    st = _state(session)
    st.setdefault("dismissed", [])
    if key not in st["dismissed"]:
        st["dismissed"].append(key)
    (st.get("items") or {}).pop(key, None)
    _save(session, st)


def auto_add(session: Session) -> list[str]:
    need = int(get_setting("auto_add_min_mentions", session) or 5)
    added = []
    for x in list_suggestions(session)[:5]:  # at most 5 new sources per run
        if x["mentions"] >= need and x.get("avg_relevance", 0) >= 30:
            if x["adapter"] == "youtube" and str(x["config"]["channel_ids"][0]).startswith("@"):
                from ..config import get_config

                if not get_config().youtube_api_key:
                    continue  # @handles need the YouTube key
            added.append(add_suggestion(session, x["key"], by="auto").name)
    return added
