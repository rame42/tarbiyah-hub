"""Recommended YouTube channels (podcasts, discussions and lectures on tarbiyah), Arabic and English.

Each entry names the channel exactly; when it is added the app finds it through the YouTube API (by its
@handle when known, otherwise by searching the exact name) and shows which channel it found, so the person can
check it. Every channel arrives with strict mode on: only videos about children, parents or educators, of at
least `min_minutes`, and the person approves them in "To review".
"""
from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Source

EN_KEYWORDS = [
    "parenting", "parent", "parents", "children", "child", "kids", "teen", "teens", "youth", "family", "families",
    "mother", "father", "son", "daughter", "tarbiyah", "tarbiya", "upbringing", "raising", "teacher", "teachers",
    "educator", "islamic education", "school", "adab",
]
AR_KEYWORDS = [
    "تربية", "التربية", "الأبناء", "الأطفال", "الطفل", "الأولاد", "أبنائ", "أولاد", "المراهق", "المراهقة", "الشباب",
    "الأسرة", "الوالدين", "بر الوالدين", "الأمهات", "الآباء", "المربي", "المعلم", "الطفولة", "الناشئة",
]
POINTS = ("Keep only episodes whose main subject is raising children, guiding parents, youth and teens, or "
          "preparing the Muslim educator/teacher, from an Islamic perspective. Reject news, politics, debates "
          "between religions, general reminders that are not about upbringing, Quran recitation only, and short clips.")

# kind: podcast | discussion | lectures
CHANNELS: list[dict[str, Any]] = [
    # ---------------------------------------------------------------- Arabic
    {"key": "riwaa-husn", "name": "بودكاست رِواء – مركز حصين", "query": "مركز حصين بودكاست رواء", "lang": "ar",
     "kind": "podcast", "pillars": ["parents", "children"], "about": "حوارات تربوية: تربية الأبناء والتحديات المعاصرة."},
    {"key": "mithaq", "name": "بودكاست ميثاق", "query": "بودكاست ميثاق", "lang": "ar", "kind": "podcast",
     "pillars": ["parents", "children"], "about": "حوارات عن الأسرة وتربية الأبناء تربية قرآنية."},
    {"key": "islamology", "name": "إسلامولوجيا – بودكاست مجالس", "query": "إسلامولوجيا", "lang": "ar",
     "kind": "podcast", "pillars": ["parents", "children"], "about": "حوارات مع مرشدين تربويين وأسريين (جيل زد، الأسرة)."},
    {"key": "abaa", "name": "بودكاست آباء", "query": "بودكاست آباء تربية", "lang": "ar", "kind": "podcast",
     "pillars": ["parents"], "about": "سلسلة حلقات للوالدين عن قضايا التربية الحساسة."},
    {"key": "ibonai", "name": "أي بُنَي – I-Bonai", "query": "I-Bonai أي بني", "lang": "ar", "kind": "lectures",
     "pillars": ["parents", "children", "murabbi"], "about": "محتوى معرفي للمربين: مصطفى أبو سعد، إبراهيم الخليفي وغيرهما."},
    {"key": "abusaad", "name": "د. مصطفى أبو سعد", "query": "مصطفى أبو سعد", "lang": "ar", "kind": "lectures",
     "pillars": ["parents", "children"], "about": "خبير التربية الإيجابية: دورات ومحاضرات للوالدين."},
    {"key": "almutawa", "name": "د. جاسم المطوع", "query": "جاسم المطوع", "lang": "ar", "kind": "lectures",
     "pillars": ["parents", "children"], "about": "استشارات أسرية وتربوية قصيرة وعملية."},
    {"key": "bakkar", "name": "د. عبد الكريم بكار", "query": "عبد الكريم بكار", "lang": "ar", "kind": "lectures",
     "pillars": ["parents", "murabbi"], "about": "مفكر تربوي: بناء الأجيال، التربية الرشيدة، إعداد المربي."},
    {"key": "alhuzaimi", "name": "د. ياسر الحزيمي", "query": "ياسر الحزيمي", "lang": "ar", "kind": "lectures",
     "pillars": ["parents"], "about": "فن التواصل في الأسرة والعلاقة مع الأبناء."},
    {"key": "alkhulaifi", "name": "د. إبراهيم الخليفي", "query": "إبراهيم الخليفي", "lang": "ar", "kind": "lectures",
     "pillars": ["parents", "children"], "about": "محاضرات في التربية والعلاقات الأسرية."},
    {"key": "alhashemi", "name": "د. عبد الرحمن ذاكر الهاشمي", "query": "عبد الرحمن ذاكر الهاشمي", "lang": "ar",
     "kind": "lectures", "pillars": ["parents", "murabbi"], "about": "التربية والنفس من منظور إسلامي، وإعداد المربين."},
    {"key": "alharami", "name": "د. عبد الرحمن الحرمي", "query": "عبد الرحمن الحرمي", "lang": "ar", "kind": "lectures",
     "pillars": ["parents", "children"], "about": "تربية الأبناء في زمن التفاهة، الأسرة والقيم."},
    {"key": "nabulsi", "name": "د. محمد راتب النابلسي", "query": "محمد راتب النابلسي", "lang": "ar", "kind": "lectures",
     "pillars": ["parents", "children"], "about": "دروس كثيرة في تربية الأولاد والأسرة المسلمة (يُصفّى المحتوى بالكلمات)."},
    {"key": "ahmad-alsayed", "name": "أحمد يوسف السيد", "query": "أحمد يوسف السيد", "lang": "ar", "kind": "discussion",
     "pillars": ["children", "murabbi"], "about": "الشباب والناشئة، بناء المحاور، تحصين الجيل فكريًا."},
    {"key": "dalail", "name": "مركز دلائل", "query": "مركز دلائل", "lang": "ar", "kind": "discussion",
     "pillars": ["children", "murabbi"], "about": "محاضرات وحوارات للشباب وتحصين الناشئة."},
    # ---------------------------------------------------------------- English
    {"key": "yaqeen", "name": "Yaqeen Institute", "handle": "@YaqeenInstitute", "query": "Yaqeen Institute",
     "lang": "en", "kind": "discussion", "pillars": ["parents", "children"],
     "about": "Parenting series, youth and family khutbahs (raising Muslims in the West)."},
    {"key": "qalam", "name": "Qalam Institute", "query": "Qalam Institute", "lang": "en", "kind": "lectures",
     "pillars": ["parents", "children"], "about": "Family, youth and marriage programmes."},
    {"key": "jannah-institute", "name": "Jannah Institute (Dr. Haifaa Younis)", "query": "Jannah Institute Haifaa Younis",
     "lang": "en", "kind": "lectures", "pillars": ["parents"], "about": "Mothers, family and spiritual growth."},
    {"key": "khalil-center", "name": "Khalil Center", "query": "Khalil Center", "lang": "en", "kind": "discussion",
     "pillars": ["parents"], "about": "Islamic psychology: parenting, youth and family wellbeing."},
    {"key": "bayyinah", "name": "Bayyinah Institute (Nouman Ali Khan)", "handle": "@bayyinah", "query": "Bayyinah Institute",
     "lang": "en", "kind": "lectures", "pillars": ["parents", "children"],
     "about": "Talks on family and parents and children in the Quran (filtered to those)."},
    {"key": "menk", "name": "Mufti Menk", "query": "Mufti Menk", "lang": "en", "kind": "lectures",
     "pillars": ["parents"], "about": "Many talks on parents, children and family (filtered to those)."},
    {"key": "mogahed", "name": "Yasmin Mogahed", "query": "Yasmin Mogahed", "lang": "en", "kind": "lectures",
     "pillars": ["parents"], "about": "Family, youth and emotional upbringing."},
    {"key": "thinking-muslim", "name": "The Thinking Muslim (podcast)", "query": "The Thinking Muslim podcast",
     "lang": "en", "kind": "podcast", "pillars": ["parents", "murabbi"],
     "about": "Long-form discussions; episodes on raising children, education and youth are kept."},
    {"key": "one-message", "name": "One Message Foundation", "query": "One Message Foundation", "lang": "en",
     "kind": "discussion", "pillars": ["children"], "about": "Youth-focused discussions and identity."},
    {"key": "mommying-while-muslim", "name": "Mommying While Muslim (podcast)", "query": "Mommying While Muslim",
     "lang": "en", "kind": "podcast", "pillars": ["parents", "children"], "about": "A podcast on Islamic parenting styles."},
    {"key": "cup-of-parenting", "name": "Cup of Parenting (Aisha Abdul Hadi)", "query": "Cup of Parenting Aisha",
     "lang": "en", "kind": "podcast", "pillars": ["parents", "children"],
     "about": "A parenting coach and speech therapist on raising Muslim children."},
    {"key": "hisham-abu-yusuf", "name": "Hisham Abu Yusuf", "query": "Hisham Abu Yusuf", "lang": "en", "kind": "podcast",
     "pillars": ["parents"], "about": "Podcast episodes on parenting and family."},
    {"key": "bilal-philips", "name": "Dr. Bilal Philips", "query": "Dr Bilal Philips", "lang": "en", "kind": "lectures",
     "pillars": ["parents", "murabbi"], "about": "Parenting Excellence series and Islamic education."},
    {"key": "sound-vision", "name": "Sound Vision", "query": "Sound Vision Islamic", "lang": "en", "kind": "lectures",
     "pillars": ["parents", "children"], "about": "Muslim parenting and children's Islamic content."},
    {"key": "safina", "name": "Safina Society (Dr. Shadee Elmasry)", "query": "Safina Society", "lang": "en",
     "kind": "podcast", "pillars": ["parents", "murabbi"],
     "about": "Daily podcast; episodes on parenting, schooling and youth are kept."},
]


def _added(session: Session) -> dict[str, Source]:
    out: dict[str, Source] = {}
    for src in session.execute(select(Source).where(Source.adapter == "youtube", Source.health != "deleted")).scalars():
        k = (src.config or {}).get("catalog")
        if k:
            out[k] = src
    return out


def listing(session: Session) -> list[dict[str, Any]]:
    have = _added(session)
    return [{**c, "added": c["key"] in have, "source_id": have[c["key"]].id if c["key"] in have else None,
             "found_as": (have[c["key"]].config or {}).get("found_as") if c["key"] in have else None}
            for c in CHANNELS]


def find_channel(entry: dict[str, Any]) -> dict[str, Any] | None:
    """The channel on YouTube: by @handle (1 unit) or by searching its exact name (100 units)."""
    from .sources.youtube import YouTubeAdapter

    a = YouTubeAdapter()
    if entry.get("handle"):
        items = a._api("channels", part="snippet,statistics", forHandle=entry["handle"]).get("items") or []
        if items:
            return items[0]
    res = a._api("search", part="snippet", q=entry["query"], type="channel", maxResults=5,
                 relevanceLanguage=entry["lang"]).get("items") or []
    ids = [((it.get("id") or {}).get("channelId")) for it in res if (it.get("id") or {}).get("channelId")]
    if not ids:
        return None
    details = a._api("channels", part="snippet,statistics", id=",".join(ids)).get("items") or []
    by_id = {d["id"]: d for d in details}
    words = [w for w in re.split(r"[\s–\-()]+", entry["name"].lower()) if len(w) > 2]
    best, best_score = None, -1.0
    for rank, cid in enumerate(ids):  # the name must match; among matches prefer the bigger, better-ranked channel
        d = by_id.get(cid)
        if not d:
            continue
        title = (d.get("snippet") or {}).get("title", "").lower()
        hits = sum(1 for w in words if w in title)
        subs = int((d.get("statistics") or {}).get("subscriberCount") or 0)
        score = hits * 10 + min(subs, 5_000_000) / 1_000_000 - rank
        if score > best_score:
            best, best_score = d, score
    return best


def add(session: Session, keys: list[str]) -> dict[str, Any]:
    from . import strict
    from .sources.youtube import YouTubeAdapter

    have = _added(session)
    by_key = {c["key"]: c for c in CHANNELS}
    added, skipped, failed = [], [], []
    a = YouTubeAdapter()
    for k in keys:
        c = by_key.get(k)
        if c is None:
            continue
        if k in have:
            skipped.append(c["name"])
            continue
        session.commit()  # never hold the write lock while calling YouTube
        try:
            ch = find_channel(c)
        except Exception as e:  # noqa: BLE001 - shown to the person
            failed.append(f"{c['name']}: {e}")
            continue
        if ch is None:
            failed.append(f"{c['name']}: not found on YouTube")
            continue
        sn, st = ch.get("snippet") or {}, ch.get("statistics") or {}
        found = {"id": ch["id"], "title": sn.get("title"), "subscribers": int(st.get("subscriberCount") or 0),
                 "videos": int(st.get("videoCount") or 0), "url": f"https://www.youtube.com/channel/{ch['id']}"}
        base = re.sub(r"[^a-z0-9]+", "-", f"youtube-{k}").strip("-")
        key, n = base, 1
        while session.execute(select(Source).where(Source.key == key)).first():
            n += 1
            key = f"{base}-{n}"
        cfg = {**a.info.default_config, "channel_ids": [ch["id"]], "role": "monitor", "added_by": "user",
               "catalog": k, "found_as": found, "min_minutes": 10 if c["kind"] == "podcast" else 5,
               "suggested_because": f"recommended channel ({c['kind']})",
               "strict": {**strict.DEFAULTS, "enabled": True, "pillars": c["pillars"],
                          "keywords": AR_KEYWORDS + EN_KEYWORDS, "keywords_mode": "any",
                          "keywords_in": "title_description", "criteria": POINTS, "review": True}}
        session.add(Source(key=key, adapter="youtube", name=c["name"], enabled=False, config=cfg,
                           schedule_minutes=a.info.default_schedule_minutes, health="ready"))
        session.flush()
        added.append({"name": c["name"], "found": found})
    return {"added": added, "skipped": skipped, "failed": failed}
