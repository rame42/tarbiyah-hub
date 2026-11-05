"""Precision for the large sources (scholarly databases and book libraries).

1. Classified, anchored searches: each source is searched with its own subject system (ERIC descriptors,
   library subject headings, field-restricted boolean queries) and an Islamic anchor, never with loose words.
2. A gate before saving: a result is kept only if it is Islamic (anchor in title/abstract/subjects; Arabic
   results may pass on a higher pillar score) AND about a pillar. With an AI key, the AI judges the
   whole batch of a search in one request.
3. Classified sweeps: every two weeks, subject-heading / descriptor searches per pillar.
4. Source selection: Crossref and YouTube are left out of research searches by default; a source whose
   results mostly fail the gate rests until its record improves.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

ANCHOR = ["islam", "islamic", "muslim", "muslims", "quran", "qur'an", "koran", "sunnah", "hadith", "prophet muhammad",
          "tarbiyah", "tarbiya", "madrasa", "madrasah", "pesantren", "pendidikan islam", "mosque", "masjid", "ummah",
          "akhlaq", "adab", "sharia", "fiqh", "iman", "salah", "prophet", "prophets", "seerah", "sirah", "sahaba",
          "allah", "ramadan", "eid", "halal", "hijab", "dua",
          "الإسلام", "الإسلامي", "الإسلامية", "إسلامي", "إسلامية", "المسلم", "المسلمين", "المسلمة", "مسلم",
          "القرآن", "قرآن", "السنة", "النبوية", "النبي", "الشرعية", "الشريعة", "الفقه", "الإيمان", "العقيدة",
          "الصحابة", "الدعوة", "المسجد", "الحديث النبوي", "تربية إسلامية"]

# per source: how a research query is turned into a precise, anchored search ({q} = the query)
TEMPLATES: dict[str, dict[str, str]] = {
    "openalex": {"en": "({q}) AND (Islam OR Islamic OR Muslim OR Muslims OR Quran)", "ar": "{q}"},
    "doaj": {"en": "({q}) AND (islam* OR muslim* OR tarbiya* OR pesantren OR quran)", "ar": "{q}"},
    "eric": {"en": '({q}) AND (subject:"Islam" OR subject:"Muslims" OR subject:"Islamic Culture" '
                   'OR title:Islamic OR title:Muslim)', "ar": '({q}) AND (subject:"Islam" OR subject:"Muslims")'},
    "core": {"en": "({q}) AND (title:(islam OR islamic OR muslim) OR abstract:(islamic OR muslim))", "ar": "{q}"},
    "internet_archive": {"en": '({q}) AND (subject:(islam OR islamic OR muslim OR "Islamic education") '
                               "OR title:(islam OR islamic OR muslim))", "ar": "{q}"},
    "openlibrary": {"en": "{q} subject:islam", "ar": "{q}"},
    "google_books": {"en": "{q} subject:islam", "ar": "{q}"},
    "gutenberg": {"en": "{q} islam", "ar": "{q}"},
    "crossref": {"en": "{q} Islamic Muslim", "ar": "{q}"},
}

# classified sweeps (used as-is): subject headings and descriptors per pillar
SWEEPS: dict[str, list[tuple[str, str | None]]] = {
    "openlibrary": [('subject:"Islamic religious education of children"', None),
                    ('subject:"Child rearing" subject:islam', None), ('subject:"Muslim children"', None),
                    ('subject:"Muslim families"', None), ('subject:"Parenting" subject:islam', None),
                    ('subject:"Islamic education"', None), ('subject:"Muslim teachers"', None),
                    ('subject:"Marriage" subject:islam', None)],
    "internet_archive": [('subject:("Islamic religious education of children" OR "Muslim children")', None),
                         ('subject:("Child rearing") AND subject:(islam OR islamic)', None),
                         ('subject:("Muslim families" OR "Families -- Religious aspects -- Islam")', None),
                         ('subject:("Islamic education") AND mediatype:texts', None),
                         ("subject:(تربية) AND language:(Arabic OR ara)", "ar")],
    "eric": [('subject:"Islam" AND subject:"Child Rearing"', None), ('subject:"Muslims" AND subject:"Parenting Styles"', None),
             ('subject:"Islam" AND subject:"Religious Education"', None), ('subject:"Muslims" AND subject:"Adolescents"', None),
             ('subject:"Islam" AND subject:"Teacher Education"', None),
             ('subject:"Muslims" AND subject:"Family Relationship"', None),
             ('subject:"Islam" AND subject:"Moral Development"', None)],
    "openalex": [('"Islamic education" AND (children OR child OR parenting)', "en"),
                 ('"Muslim parents" OR "Muslim parenting" OR "Islamic parenting"', "en"),
                 ('"Islamic religious education" AND (teacher OR teachers OR educator)', "en"),
                 ('"Muslim families" AND (upbringing OR "child rearing" OR adolescents)', "en"),
                 ("تربية الأبناء", "ar"), ("التربية الإسلامية للطفل", "ar"), ("إعداد المعلم المسلم", "ar")],
    "doaj": [('"pendidikan islam" AND (anak OR keluarga OR guru)', None),
             ('"Islamic education" AND (children OR parents OR teachers)', "en"), ("تربية الأبناء", "ar")],
}

TEMPLATE_DEFAULT = {"en": "{q}", "ar": "{q}"}


def _lang_of(query: str, lang: str | None) -> str:
    import re

    if lang in ("ar", "en"):
        return lang
    return "ar" if re.search(r"[؀-ۿ]", query) else "en"


def scoped_query(adapter: str, query: str, lang: str | None) -> str:
    """The precise search for this source. Queries that already carry an Islamic anchor are kept as they are."""
    from .sources.base import matches_keywords

    lg = _lang_of(query, lang)
    if lg == "en" and matches_keywords(ANCHOR, query):
        tpl = TEMPLATES.get(adapter, TEMPLATE_DEFAULT)
        # still use the field-restricted form for ERIC/CORE, but without a second anchor
        return query if adapter not in ("eric",) else tpl["en"].format(q=query)
    return TEMPLATES.get(adapter, TEMPLATE_DEFAULT)[lg].format(q=query)


def anchored(d: Any) -> bool:
    from .sources.base import matches_keywords

    return matches_keywords(ANCHOR, d.title, d.description, " ".join(d.keywords or []), d.publisher,
                            (d.extra or {}).get("journal"), (d.extra or {}).get("venue"))


def gate(session: Session, items: list[Any], lang: str | None = None) -> tuple[list[Any], dict[str, int]]:
    """Keep only Islamic AND pillar-relevant results. Returns (kept, reasons -> count)."""
    from .ingest.classify import classify_text
    from .settings import get_setting

    min_score = int(get_setting("research_min_score", session) or 25)
    reasons: dict[str, int] = {}
    judged = ai_judge(session, items) if get_setting("research_ai_gate", session) else None
    kept = []
    for i, d in enumerate(items):
        if judged is not None and i in judged:
            score, pillars, why = judged[i]
            ok = score >= max(min_score, 50) and bool(pillars)
            d.extra = {**(d.extra or {}), "relevance_ai": score, "relevance_reason": why, "triaged": True}
            if not ok:
                reasons["AI: not relevant enough"] = reasons.get("AI: not relevant enough", 0) + 1
                continue
            kept.append(d)
            continue
        cl = classify_text(session, d.title, d.description or "", "", d.keywords)
        if not cl.pillars or cl.relevance < min_score:
            reasons["not about a pillar"] = reasons.get("not about a pillar", 0) + 1
            continue
        arabic = (d.language or "").startswith("ar") or _lang_of(d.title or "", None) == "ar"
        if not anchored(d) and not (arabic and cl.relevance >= min_score + 10):
            reasons["no Islamic connection"] = reasons.get("no Islamic connection", 0) + 1
            continue
        kept.append(d)
    return kept, reasons


def ai_judge(session: Session, items: list[Any]) -> dict[int, tuple[int, list[str], str]] | None:
    """One AI request for a whole search result page; None when AI is not available or fails."""
    from .agents.triage import SYSTEM
    from .ai.claude import AIBudgetExceeded, AIUnavailable, claude
    from .ai.schemas import TriageBatch

    if not items or not claude().available():
        return None
    blocks = []
    for i, d in enumerate(items):
        desc = (d.description or "")[:600].replace("<", "‹")
        blocks.append(f'<item id="{i}">\nTitle: {(d.title or "")[:300]}\nType: {d.resource_type}\n'
                      f"Language: {d.language or '-'}\nPublisher/venue: {d.publisher or '-'}\nDescription: {desc or '-'}\n</item>")
    system = SYSTEM + ("\nThis library is specifically about ISLAMIC tarbiyah: general secular material scores below 40 "
                       "unless it is directly about Muslim children, families or educators.")
    try:
        session.commit()  # never hold the write lock while waiting for the model
        out: TriageBatch = claude().structured("triage", system, "Items:\n<source>\n" + "\n".join(blocks) + "\n</source>",
                                               TriageBatch, max_tokens=6000, effort="low")
    except (AIUnavailable, AIBudgetExceeded):
        return None
    except Exception:  # noqa: BLE001 - fall back to the rules
        return None
    return {t.id: (max(0, min(100, int(t.relevance))), list(t.pillars), t.reason[:400])
            for t in out.items if 0 <= t.id < len(items)}
