"""Dependency-free language detection focused on the two primary languages.

Returns 'ar', 'en', 'mixed', 'other' or 'und' (undetermined). Script ratio decides
Arabic; English is confirmed with a stop-word ratio so French/Malay/Turkish text
in Latin script is not mislabelled as English.
"""
from __future__ import annotations

import re

from .arabic import ARABIC_CHAR

_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")
_EN_STOP = set(
    "the of and to in is that for it as with was on be by this are or from at an which have not "
    "their they his her can has were but been children child parents education will more these".split()
)
_WORD = re.compile(r"[A-Za-z']+")


def detect_language(text: str, sample: int = 6000) -> str:
    if not text or not text.strip():
        return "und"
    s = text[:sample]
    ar = len(ARABIC_CHAR.findall(s))
    la = len(_LATIN.findall(s))
    letters = ar + la
    if letters < 3:
        return "und"
    ar_ratio = ar / letters
    if ar_ratio >= 0.8:
        return "ar"
    if 0.2 <= ar_ratio < 0.8 and letters > 40:
        return "mixed"
    words = [w.lower() for w in _WORD.findall(s)]
    if not words:
        return "und"
    if len(words) < 4:
        return "en"  # too short to tell; titles/queries in Latin script are usually English here
    stop_ratio = sum(1 for w in words if w in _EN_STOP) / len(words)
    return "en" if stop_ratio >= 0.08 else "other"


def detect_sections(paragraphs: list[str]) -> list[str]:
    return [detect_language(p) for p in paragraphs]
