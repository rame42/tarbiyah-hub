"""Children's Quran, Seerah & Hadith shelf.

An item is shelved when it is about one of the subjects AND clearly meant for children (or classified
for a child age group). Matching uses the same spelling-tolerant keyword matcher as the sources;
ambiguous Arabic words are avoided ("حديث" alone also means "modern", "سور" occurs inside "تصور").
The result is stored in resource.extra["kids_corner"] = ["quran", "seerah", ...].
"""
from __future__ import annotations

from typing import Any

SUBJECTS: dict[str, list[str]] = {
    "quran": ["القرآن", "قرآن", "القران", "تحفيظ", "حفظ القرآن", "تجويد", "التجويد", "سورة", "جزء عم", "جزء تبارك",
              "التلاوة", "تلاوة", "مصحف", "المصحف", "نور البيان", "القاعدة النورانية", "تفسير للأطفال",
              "quran", "qur'an", "koran", "tajweed", "tajwid", "juz amma", "surah", "noorani qaida", "qaida",
              "hifz", "memorize the quran", "quran memorization"],
    "seerah": ["السيرة", "سيرة", "السيرة النبوية", "سيرة الرسول", "سيرة النبي", "النبي محمد", "رسول الله", "الرسول",
               "قصص الأنبياء", "قصص النبي", "الصحابة", "صحابة", "الصحابيات", "غزوة", "الهجرة النبوية", "أمهات المؤمنين",
               "seerah", "sirah", "seera", "prophet muhammad", "life of the prophet", "prophet's life", "stories of the prophets",
               "prophet stories", "companions of the prophet", "sahaba", "sahabah"],
    "hadith": ["الحديث النبوي", "الحديث الشريف", "الأحاديث", "أحاديث", "الأربعين النووية", "الأربعون النووية",
               "الأربعين", "السنة النبوية", "رياض الصالحين", "صحيح البخاري", "صحيح مسلم", "الأدب المفرد",
               "hadith", "ahadith", "hadeeth", "forty hadith", "40 hadith", "nawawi", "sunnah", "riyad as-salihin",
               "riyadh us saliheen", "bukhari", "al-adab al-mufrad"],
}
CHILDREN: list[str] = ["طفل", "اطفال", "أطفال", "الطفولة", "للأطفال", "الصغار", "للصغار", "صغار", "الناشئة", "ناشئة",
                       "البراعم", "براعم", "الأولاد", "أبنائنا", "الأبناء", "الفتيان", "الروضة", "رياض الأطفال", "الكتاتيب",
                       "kid", "kids", "child", "children", "childhood", "toddler", "preschool", "kindergarten",
                       "young muslims", "young readers", "boys and girls", "junior", "juniors", "little muslims",
                       "for young", "youngsters"]
CHILD_AGES = {"0-2", "3-6", "7-12"}

QUERIES: dict[str, list[str]] = {
    "ar": ["قصص السيرة النبوية للأطفال", "السيرة النبوية للأطفال", "تحفيظ القرآن للأطفال", "تعليم القرآن للأطفال",
           "قصص القرآن للأطفال", "الأربعون النووية للأطفال", "أحاديث للأطفال", "قصص الأنبياء للأطفال"],
    "en": ["Seerah for kids", "Prophet Muhammad stories for children", "Quran for kids", "teaching Quran to children",
           "Hadith for children", "40 hadith for kids", "stories of the prophets for children"],
}


def subjects_for(title: str | None, description: str | None, keywords: list[str] | None = None,
                 age_groups: list[str] | None = None) -> list[str]:
    from .sources.base import matches_keywords

    texts = (title or "", description or "", " ".join(keywords or []))
    if not (matches_keywords(CHILDREN, *texts) or CHILD_AGES & set(age_groups or [])):
        return []
    return [s for s, words in SUBJECTS.items() if matches_keywords(words, *texts)]


def tag(r: Any) -> bool:
    """Set or clear resource.extra["kids_corner"]; returns True when the item is on the shelf."""
    ex = dict(r.extra or {})
    subs = subjects_for(r.title, r.description, r.keywords, ex.get("age_groups"))
    if subs:
        ex["kids_corner"] = subs
    else:
        ex.pop("kids_corner", None)
    r.extra = ex
    return bool(subs)
