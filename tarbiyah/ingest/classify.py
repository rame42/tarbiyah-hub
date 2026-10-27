"""Rule-based bilingual classification into pillars, topics and age groups.

Works without any AI. When Claude is available, the knowledge agent may refine the
result; refined rows are stored with method='ai' so both are distinguishable.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import Resource, ResourcePillar, ResourceTopic, Topic
from ..taxonomy import AGE_GROUPS, PILLAR_KEYWORDS
from ..text.arabic import light_stem, tokens

_STOP = set(
    "the a an of and or to in on for with by from at as is are was were be been this that these those it its "
    "their his her they we you our your not no can will would should may might also than then there which who "
    "whom what when where how why all any each other such into about between over under more most some very "
    "page pages chapter vol pp et al http https www com org".split()
) | set("في من على إلى الى عن مع هذا هذه ذلك التي الذي الذين كان كانت أن ان إن لا ما لم لن قد كل بين او أو ثم هو هي هم و".split())


def _stem_seq(text: str) -> str:
    return " " + " ".join(light_stem(t) for t in tokens(text)) + " "


def _count(hay: str, phrase: str) -> int:
    key = _stem_seq(phrase)
    if key.strip() == "":
        return 0
    return hay.count(key)


@dataclass
class Classification:
    pillars: dict[str, float] = field(default_factory=dict)
    topics: dict[int, float] = field(default_factory=dict)
    age_groups: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


def classify_text(session: Session, title: str, description: str = "", body: str = "",
                  extra_keywords: list[str] | None = None) -> Classification:
    weighted = [(_stem_seq(title or ""), 3.0), (_stem_seq(" ".join(extra_keywords or [])), 2.0),
                (_stem_seq(description or ""), 2.0), (_stem_seq((body or "")[:30000]), 1.0)]
    out = Classification()
    raw: dict[str, float] = {}
    for pillar, langs in PILLAR_KEYWORDS.items():
        score = 0.0
        for kw in set(langs["en"] + langs["ar"]):
            for hay, w in weighted:
                n = _count(hay, kw)
                if n:
                    score += w * min(n, 5)
        raw[pillar] = score
    topics = session.execute(select(Topic)).scalars().all()
    for t in topics:
        score = 0.0
        for kw in set((t.keywords_en or []) + (t.keywords_ar or [])):
            for hay, w in weighted:
                n = _count(hay, kw)
                if n:
                    score += w * min(n, 5)
        if score >= 3:
            out.topics[t.id] = score
            if t.pillar:
                raw[t.pillar] = raw.get(t.pillar, 0) + score * 0.5
    top = max(raw.values()) if raw else 0
    if top >= 3:
        for p, s in raw.items():
            if s >= 3 and s >= 0.35 * top:
                out.pillars[p] = round(min(1.0, s / (top or 1)), 3)
    if out.topics:
        mt = max(out.topics.values())
        out.topics = {k: round(v / mt, 3) for k, v in out.topics.items() if v >= 0.2 * mt}
    for band, langs in AGE_GROUPS.items():
        if any(_count(hay, kw) for kw in langs["en"] + langs["ar"] for hay, _ in weighted):
            out.age_groups.append(band)
    out.keywords = top_keywords(" ".join([title or "", description or "", (body or "")[:30000]]))
    return out


def top_keywords(text: str, n: int = 12) -> list[str]:
    toks = [t for t in tokens(text) if len(t) > 3 and t not in _STOP and not t.isdigit()]
    return [w for w, _ in Counter(toks).most_common(n)]


def apply_classification(session: Session, r: Resource, c: Classification, method: str = "rules") -> None:
    session.execute(delete(ResourcePillar).where(ResourcePillar.resource_id == r.id, ResourcePillar.method == method))
    session.execute(delete(ResourceTopic).where(ResourceTopic.resource_id == r.id, ResourceTopic.method == method))
    session.flush()
    existing = {p.pillar for p in session.execute(
        select(ResourcePillar).where(ResourcePillar.resource_id == r.id)).scalars()}
    for p, s in c.pillars.items():
        if p not in existing:
            session.add(ResourcePillar(resource_id=r.id, pillar=p, score=s, method=method))
    existing_t = set(session.execute(
        select(ResourceTopic.topic_id).where(ResourceTopic.resource_id == r.id)).scalars())
    for tid, s in c.topics.items():
        if tid not in existing_t:
            session.add(ResourceTopic(resource_id=r.id, topic_id=tid, score=s, method=method))
    extra = dict(r.extra or {})
    extra["age_groups"] = c.age_groups
    r.extra = extra
    if c.keywords and not r.keywords:
        r.keywords = c.keywords
