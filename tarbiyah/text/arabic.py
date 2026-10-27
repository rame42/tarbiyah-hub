"""Arabic/English normalization for *search keys only*.

Original text is never modified; these functions produce the normalized copies that
go into the full-text index and into duplicate-detection keys.
"""
from __future__ import annotations

import re
import unicodedata

ARABIC_DIACRITICS = re.compile("[ؐ-ًؚ-ٰٟۖ-ۭ]")
TATWEEL = "ـ"
_ALIF_VARIANTS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا"})
_OTHER = str.maketrans(
    {
        "ى": "ي",  # alif maqsura -> ya
        "ة": "ه",  # ta marbuta -> ha
        "ؤ": "و",  # waw hamza -> waw
        "ئ": "ي",  # ya hamza -> ya
        "ی": "ي",  # farsi ya
        "ک": "ك",  # keheh -> kaf
        "،": ",",  # arabic comma
        "؛": ";",
        "؟": "?",
    }
)
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
ARABIC_CHAR = re.compile("[؀-ۿݐ-ݿࢠ-ࣿﭐ-﷿ﹰ-﻿]")
TOKEN = re.compile(r"[\w؀-ۿ]+", re.UNICODE)

# Light stemming (no root extraction): strip frequent prefixes/suffixes only when the
# remaining stem is long enough. This is deliberately conservative.
_PREFIXES = ("وبال", "وال", "بال", "كال", "فال", "لل", "ال", "و")
_SUFFIXES = ("هما", "كما", "تين", "ات", "ون", "ين", "ان", "ها", "هم", "هن", "كم", "نا", "ه", "ي")


def has_arabic(text: str) -> bool:
    return bool(text) and ARABIC_CHAR.search(text) is not None


def normalize_arabic(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = ARABIC_DIACRITICS.sub("", text).replace(TATWEEL, "")
    return text.translate(_ALIF_VARIANTS).translate(_OTHER).translate(_DIGITS)


def normalize_for_search(text: str) -> str:
    """Lower-case Latin, normalize Arabic orthographic variants, collapse whitespace."""
    if not text:
        return ""
    text = normalize_arabic(text).lower()
    # strip latin accents (e.g. transliterations: tarbiyah / tarbīyah)
    text = "".join(c for c in unicodedata.normalize("NFD", text) if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", text).strip()


def light_stem(token: str) -> str:
    if not has_arabic(token):
        return token
    t = token
    for p in _PREFIXES:
        if t.startswith(p) and len(t) - len(p) >= 3:
            t = t[len(p):]
            break
    for s in _SUFFIXES:
        if t.endswith(s) and len(t) - len(s) >= 3:
            t = t[: -len(s)]
            break
    return t


def tokens(text: str) -> list[str]:
    return TOKEN.findall(normalize_for_search(text))


def stems_text(text: str) -> str:
    """Space-joined Arabic light stems (Latin tokens are left for the porter tokenizer)."""
    return " ".join(light_stem(t) for t in tokens(text) if has_arabic(t))


def title_key(title: str, max_tokens: int = 12) -> str:
    """Key for bibliographic duplicate detection: normalized, stop-word-free title prefix."""
    stop = {"the", "a", "an", "of", "and", "in", "on", "for", "to", "في", "من", "على", "الى", "عن", "و"}
    toks = [light_stem(t) for t in tokens(title) if t not in stop]
    return " ".join(toks[:max_tokens])


STOPWORDS = set(
    "the a an of and or to in on for with by from at as is are was were be been this that these those it its "
    "what how why when where which who whom do does did can could should would will about into there their "
    "my your our me i you we they he she them his her us any some".split()
) | {normalize_for_search(w) for w in (
    "ما ماذا كيف لماذا متى أين هل من في على إلى الى عن مع هذا هذه ذلك تلك التي الذي الذين كان كانت أن إن "
    "لا لم لن قد كل بين أو او ثم هو هي هم هن أنا نحن انت أنت عند غير بعض أي اي").split()}


def content_tokens(text: str) -> list[str]:
    """Tokens without stop-words (used for lenient passage retrieval)."""
    return [t for t in tokens(text) if t not in STOPWORDS and len(t) > 1]
