"""The topic map: every search sent to the large sources comes from a precise, multi-word topic phrase.

- 45 starting topics (15 per pillar), each with English and Arabic phrases; editable in the dashboard.
- A research question is linked to its closest topics (shared content words); when nothing matches,
  the least-recently searched topics of the question's pillars are used.
- Topic sweeps: one topic every two hours is searched across the large sources, so the whole map is
  covered regularly, independent of the research questions.
- Single-word searches are never sent to the large sources.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import utcnow
from .models import SearchLog, SearchTopic

# (pillar, name_en, name_ar, phrases_en, phrases_ar)
SEED: list[tuple[str, str, str, list[str], list[str]]] = [
    # ---------------------------------------------------------------- children
    ("children", "Teaching salah to children", "تعليم الأطفال الصلاة",
     ["teaching prayer to children", "children salah practice"], ["تعليم الأطفال الصلاة", "تعويد الأطفال على الصلاة"]),
    ("children", "Quran memorization for children", "تحفيظ القرآن للأطفال",
     ["Quran memorization children", "hifz program children"], ["تحفيظ القرآن للأطفال", "حفظ القرآن الكريم للأطفال"]),
    ("children", "Instilling faith (aqidah) in children", "غرس العقيدة في نفوس الأطفال",
     ["faith development Muslim children", "teaching aqidah to children"], ["غرس العقيدة في نفوس الأطفال", "التربية الإيمانية للطفل"]),
    ("children", "Moral and character education", "التربية الأخلاقية للطفل",
     ["moral education Muslim children", "Islamic character education children"], ["التربية الأخلاقية للطفل", "تربية الطفل على الأخلاق"]),
    ("children", "Prophetic methods of upbringing", "التربية النبوية للطفل",
     ["prophetic parenting", "Prophet Muhammad children upbringing"], ["منهج التربية النبوية للطفل", "التربية النبوية للأطفال"]),
    ("children", "Islamic early childhood education", "التربية الإسلامية في الطفولة المبكرة",
     ["Islamic early childhood education", "Muslim preschool education"], ["التربية الإسلامية في الطفولة المبكرة", "رياض الأطفال الإسلامية"]),
    ("children", "Teaching Seerah and Islamic stories", "تعليم السيرة والقصص للأطفال",
     ["Seerah for children", "Islamic stories children education"], ["تعليم السيرة النبوية للأطفال", "القصص في تربية الطفل المسلم"]),
    ("children", "Children's Islamic identity", "الهوية الإسلامية للطفل",
     ["Muslim children religious identity", "Islamic identity formation children"], ["الهوية الإسلامية للطفل", "بناء هوية الطفل المسلم"]),
    ("children", "Discipline, reward and punishment", "الثواب والعقاب في تربية الطفل",
     ["child discipline Islamic upbringing", "reward and punishment Islamic education"], ["الثواب والعقاب في تربية الطفل", "تأديب الأطفال في الإسلام"]),
    ("children", "Islamic rulings concerning children", "أحكام الأطفال والمولود",
     ["Islamic rulings children newborn"], ["أحكام المولود", "أحكام الأطفال في الفقه الإسلامي"]),
    ("children", "Adolescence and puberty", "تربية المراهقين والبلوغ",
     ["Muslim adolescents religiosity", "puberty Islamic education"], ["تربية المراهقين في الإسلام", "البلوغ والتكليف"]),
    ("children", "Children, media and screens", "الطفل المسلم والإعلام والشاشات",
     ["Muslim children media use", "screen time Muslim families"], ["الطفل المسلم ووسائل الإعلام", "الأطفال والأجهزة الذكية والتربية"]),
    ("children", "Islamic studies in primary education", "التربية الإسلامية في المرحلة الابتدائية",
     ["Islamic religious education primary school", "Islamic studies curriculum children"], ["مناهج التربية الإسلامية للأطفال", "تدريس التربية الإسلامية في المرحلة الابتدائية"]),
    ("children", "Children's spiritual development", "التربية الروحية للطفل",
     ["spiritual development Muslim children"], ["التربية الروحية للطفل"]),
    ("children", "Children with special needs", "الأطفال ذوو الاحتياجات الخاصة",
     ["special needs children Islamic perspective"], ["تربية ذوي الاحتياجات الخاصة في الإسلام"]),
    # ---------------------------------------------------------------- parents & family
    ("parents", "Parental role modeling", "القدوة الوالدية",
     ["parental role modeling Islam", "parents as role models Muslim families"], ["القدوة الوالدية", "الوالدان قدوة للأبناء"]),
    ("parents", "Muslim parenting styles", "أساليب التربية الأسرية الإسلامية",
     ["Muslim parenting styles", "Islamic parenting practices"], ["أساليب المعاملة الوالدية في الإسلام", "أساليب التربية الأسرية الإسلامية"]),
    ("parents", "Rights of children over parents", "حقوق الأولاد على الوالدين",
     ["rights of children in Islam"], ["حقوق الأولاد على الوالدين", "حقوق الطفل في الإسلام"]),
    ("parents", "Parents and adolescents", "الوالدان والمراهق",
     ["Muslim adolescents and parents", "parent adolescent relationship Muslim"], ["العلاقة بين الوالدين والمراهق", "الحوار مع الأبناء المراهقين"]),
    ("parents", "Family dialogue and communication", "الحوار الأسري",
     ["family communication Muslim families"], ["الحوار الأسري", "التواصل داخل الأسرة المسلمة"]),
    ("parents", "Marriage and upbringing", "الزواج وتربية الأبناء",
     ["Islamic marriage child upbringing", "marital relationship Islamic family"], ["الزواج في الإسلام وتربية الأبناء", "العلاقة الزوجية وأثرها على الأبناء"]),
    ("parents", "The mother's role", "دور الأم في التربية",
     ["role of the mother Islamic upbringing", "Muslim mothers child rearing"], ["دور الأم في التربية الإسلامية", "الأمومة في الإسلام"]),
    ("parents", "The father's role", "دور الأب في التربية",
     ["role of the father Muslim family", "Muslim fathers involvement"], ["دور الأب في تربية الأبناء"]),
    ("parents", "Kindness to parents (birr)", "بر الوالدين",
     ["filial piety Islam", "kindness to parents Islam"], ["بر الوالدين", "تربية الأبناء على بر الوالدين"]),
    ("parents", "Muslim families in the West", "الأسرة المسلمة في الغرب",
     ["Muslim immigrant families parenting", "Muslim families in the West"], ["الأسرة المسلمة في الغرب", "تربية الأبناء في بلاد الغربة"]),
    ("parents", "Family resilience and wellbeing", "استقرار الأسرة المسلمة",
     ["Muslim family resilience", "Muslim family wellbeing"], ["استقرار الأسرة المسلمة", "الصحة النفسية للأسرة المسلمة"]),
    ("parents", "Divorce and children", "الطلاق وأثره على الأبناء",
     ["divorce Muslim children effects"], ["الطلاق وأثره على الأبناء"]),
    ("parents", "Family worship and the Muslim home", "البيت المسلم والعبادة الأسرية",
     ["family worship Muslim home", "Islamic home environment"], ["البيت المسلم", "العبادة في الأسرة المسلمة"]),
    ("parents", "Parent education programmes", "برامج تأهيل الوالدين",
     ["Islamic parenting program", "parent training Muslim community"], ["برامج تأهيل الوالدين", "التثقيف التربوي للوالدين"]),
    ("parents", "Raising daughters", "تربية البنات",
     ["raising daughters Islam"], ["تربية البنات في الإسلام"]),
    # ---------------------------------------------------------------- murabbi
    ("murabbi", "Islamic teacher education", "إعداد المعلم المسلم",
     ["Islamic teacher education", "training Islamic religious education teachers"], ["إعداد المعلم المسلم", "تأهيل معلمي التربية الإسلامية"]),
    ("murabbi", "Etiquette of teacher and student", "آداب المعلم والمتعلم",
     ["adab of teacher and student Islam"], ["آداب المعلم والمتعلم", "أدب العالم والمتعلم"]),
    ("murabbi", "Qualities of the murabbi", "صفات المربي",
     ["qualities of the Muslim educator", "murabbi characteristics"], ["صفات المربي", "المربي الناجح"]),
    ("murabbi", "Quran and halaqa teacher training", "إعداد معلمي الحلقات القرآنية",
     ["Quran teachers training", "halaqa teaching methods"], ["إعداد معلمي الحلقات القرآنية", "طرق التدريس في حلقات التحفيظ"]),
    ("murabbi", "Mentoring Muslim youth", "الإرشاد التربوي للشباب المسلم",
     ["mentoring Muslim youth", "Muslim youth workers mentors"], ["الإرشاد التربوي للشباب المسلم", "المربي والشباب"]),
    ("murabbi", "Madrasa and Islamic school pedagogy", "طرق التدريس في المدارس الإسلامية",
     ["madrasa pedagogy", "Islamic school pedagogy"], ["طرق التدريس في المدارس الإسلامية"]),
    ("murabbi", "Islamic philosophy of education", "فلسفة التربية الإسلامية",
     ["Islamic philosophy of education", "Islamic educational theory"], ["فلسفة التربية الإسلامية", "النظرية التربوية الإسلامية"]),
    ("murabbi", "Classical Muslim scholars on education", "الفكر التربوي عند علماء المسلمين",
     ["al-Ghazali education", "Ibn Khaldun education", "classical Muslim educational thought"], ["الفكر التربوي عند الغزالي", "الفكر التربوي الإسلامي"]),
    ("murabbi", "Islamic school leadership", "القيادة التربوية في المدارس الإسلامية",
     ["Islamic school leadership"], ["القيادة التربوية في المدارس الإسلامية"]),
    ("murabbi", "Prophetic teaching methods", "أساليب النبي في التعليم",
     ["prophetic teaching methods"], ["أساليب النبي صلى الله عليه وسلم في التعليم", "الأساليب النبوية في التربية"]),
    ("murabbi", "Islamic curriculum design", "بناء مناهج التربية الإسلامية",
     ["Islamic education curriculum development"], ["بناء مناهج التربية الإسلامية"]),
    ("murabbi", "Integrating Islamic values in teaching", "دمج القيم الإسلامية في التعليم",
     ["integration of Islamic values in teaching"], ["دمج القيم الإسلامية في التعليم"]),
    ("murabbi", "Youth programmes and tarbiyah circles", "المحاضن التربوية وبرامج الشباب",
     ["Islamic youth programs", "Muslim youth education programs"], ["المحاضن التربوية", "برامج الشباب التربوية"]),
    ("murabbi", "Teacher ethics in Islam", "أخلاقيات المعلم في الإسلام",
     ["Muslim teacher ethics", "teacher professional ethics Islam"], ["أخلاقيات المعلم في الإسلام"]),
    ("murabbi", "Assessment in Islamic education", "التقويم في التربية الإسلامية",
     ["assessment in Islamic education"], ["التقويم في التربية الإسلامية"]),
]


def ensure_seeded(session: Session) -> int:
    if session.execute(select(func.count()).select_from(SearchTopic)).scalar():
        return 0
    for pillar, en, ar, pe, pa in SEED:
        session.add(SearchTopic(pillar=pillar, name_en=en, name_ar=ar, phrases_en=pe, phrases_ar=pa))
    session.flush()
    return len(SEED)


def _words(text: str) -> set[str]:
    from .text.arabic import STOPWORDS, light_stem, tokens

    extra = {"islam", "islamic", "muslim", "muslims", "children", "child", "role", "education", "تربية", "الإسلام",
             "الإسلامية", "المسلم", "في", "على"}
    return {light_stem(t) for t in tokens(text or "") if len(t) > 2 and t not in STOPWORDS and t not in extra}


def is_vague(query: str) -> bool:
    """A search of a single word (or nothing) is too vague for the large sources."""
    from .text.arabic import tokens

    return len([t for t in tokens(query.replace('"', " ")) if len(t) > 1]) < 2


def link(session: Session, text: str, pillars: list[str] | None = None, n: int = 2) -> list[SearchTopic]:
    """The topics closest to a research question (shared content words); else its pillars' least-searched topics."""
    ensure_seeded(session)
    topics = session.execute(select(SearchTopic).where(SearchTopic.enabled.is_(True))).scalars().all()
    q = _words(text)
    scored = []
    for t in topics:
        tw = _words(" ".join([t.name_en, t.name_ar, *t.phrases_en, *t.phrases_ar]))
        score = len(q & tw) + (0.5 if pillars and t.pillar in pillars else 0)
        if len(q & tw) >= 2 or (len(q & tw) == 1 and pillars and t.pillar in pillars):
            scored.append((score, t))
    if scored:
        return [t for _, t in sorted(scored, key=lambda x: -x[0])[:n]]
    pool = [t for t in topics if not pillars or t.pillar in pillars] or list(topics)
    return sorted(pool, key=lambda t: t.last_swept_at or utcnow() - timedelta(days=3650))[:n]


def queries_for(topics: list[SearchTopic], per_lang: int = 1) -> list[dict[str, Any]]:
    out = []
    for t in topics:
        out += [{"query": p, "lang": "en", "topic_id": t.id} for p in t.phrases_en[:per_lang] if not is_vague(p)]
        out += [{"query": p, "lang": "ar", "topic_id": t.id} for p in t.phrases_ar[:per_lang] if not is_vague(p)]
    return out


def next_sweep_topic(session: Session, every_hours: float = 2) -> SearchTopic | None:
    """One topic every two hours is searched across the large sources (the least recently swept first)."""
    ensure_seeded(session)
    last = session.execute(select(func.max(SearchTopic.last_swept_at))).scalar()
    if last is not None and utcnow() - last < timedelta(hours=every_hours):
        return None
    return session.execute(select(SearchTopic).where(SearchTopic.enabled.is_(True))
                           .order_by(SearchTopic.last_swept_at.is_not(None), SearchTopic.last_swept_at, SearchTopic.id)
                           .limit(1)).scalars().first()


def stats(session: Session, days: int = 60) -> dict[int, dict[str, Any]]:
    rows = session.execute(select(SearchLog.topic_id, func.count(), func.sum(SearchLog.results), func.sum(SearchLog.kept),
                                  func.sum(SearchLog.new_resources))
                           .where(SearchLog.topic_id.is_not(None), SearchLog.executed_at >= utcnow() - timedelta(days=days),
                                  SearchLog.status == "ok")
                           .group_by(SearchLog.topic_id)).all()
    out = {}
    for tid, n, res, kept, new in rows:
        y = round(100 * (kept or 0) / res) if res else None
        out[tid] = {"searches": n, "returned": int(res or 0), "kept": int(kept or 0), "new": int(new or 0),
                    "yield_pct": y, "weak": bool(n >= 5 and y is not None and y < 10)}
    return out
