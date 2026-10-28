"""Courses (free and paid): recognised from the schema.org "Course" data that course websites
publish for search engines (Udemy, Coursera, edX, many academies). Only what the page itself states
is used: title, provider, description, language, price and whether it is free. Paid courses are
catalogued with their price and link; nothing behind a login or payment is accessed.
"""
from __future__ import annotations

import json
import re
from typing import Any

from .licensing import AccessDecision

_LD = re.compile(rb'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I)
COURSE_TYPES = {"course", "courseinstance", "educationaloccupationalprogram"}


def _nodes(data: Any):
    if isinstance(data, list):
        for x in data:
            yield from _nodes(x)
    elif isinstance(data, dict):
        yield data
        for k in ("@graph", "itemListElement", "item", "mainEntity"):
            if k in data:
                yield from _nodes(data[k])


def _types(node: dict) -> set[str]:
    t = node.get("@type")
    return {str(x).lower() for x in (t if isinstance(t, list) else [t]) if x}


def _text(v: Any) -> str | None:
    if isinstance(v, dict):
        v = v.get("name") or v.get("@value")
    if isinstance(v, list):
        v = ", ".join(str(_text(x) or "") for x in v if _text(x))
    s = str(v).strip() if v not in (None, "") else ""
    return re.sub(r"\s+", " ", s) or None


def _offer(node: dict) -> tuple[float | None, str | None, str | None]:
    offers = node.get("offers")
    for inst in node.get("hasCourseInstance") or []:
        if isinstance(inst, dict) and not offers:
            offers = inst.get("offers")
    for o in (offers if isinstance(offers, list) else [offers]):
        if not isinstance(o, dict):
            continue
        price = o.get("price", o.get("lowPrice"))
        if isinstance(o.get("priceSpecification"), dict):
            price = o["priceSpecification"].get("price", price)
        try:
            value = float(str(price).replace(",", "")) if price not in (None, "") else None
        except ValueError:
            value = None
        if str(o.get("category", "")).lower() == "free":
            value = 0.0
        return value, _text(o.get("priceCurrency")), o.get("url")
    return None, None, None


def course_from_html(html: bytes, url: str) -> dict[str, Any] | None:
    """Course details from a page's schema.org data, or None when the page is not a course."""
    for m in _LD.finditer(html or b""):
        try:
            data = json.loads(m.group(1).decode("utf-8", "ignore").strip())
        except ValueError:
            continue
        for node in _nodes(data):
            if not (_types(node) & COURSE_TYPES):
                continue
            name = _text(node.get("name"))
            if not name:
                continue
            price, currency, offer_url = _offer(node)
            free = node.get("isAccessibleForFree")
            if isinstance(free, str):
                free = free.strip().lower() in ("true", "yes", "1")
            if free is None and price is not None:
                free = price == 0
            return {
                "title": name,
                "description": _text(node.get("description")),
                "provider": _text(node.get("provider")) or _text(node.get("publisher")),
                "language": _text(node.get("inLanguage")),
                "price": None if price is None else (f"{price:g}"),
                "currency": currency,
                "free": free,
                "url": _text(node.get("url")) or url,
                "offer_url": offer_url,
            }
    return None


def course_access(info: dict[str, Any]) -> AccessDecision:
    if info.get("free"):
        return AccessDecision("free_to_read", False, "Free course according to the provider's page.")
    if info.get("price"):
        return AccessDecision("paid", False, f"Paid course ({info['price']} {info.get('currency') or ''}).".replace(" )", ")"))
    return AccessDecision("unknown", False, "Course; the provider's page does not state the price.")


def apply_course(r: Any, info: dict[str, Any]) -> None:
    """Update a Resource row with course details found on its page."""
    a = course_access(info)
    r.resource_type = "course"
    r.title = info.get("title") or r.title
    r.description = r.description or info.get("description")
    r.publisher = r.publisher or info.get("provider")
    if not info.get("free"):
        r.price = info.get("price")
        r.currency = info.get("currency")
        r.purchase_url = info.get("offer_url") or info.get("url")
    r.access_status, r.download_permitted, r.permission_basis = a.access_status, a.download_permitted, a.basis
    r.extra = {**(r.extra or {}), "course": {k: info.get(k) for k in ("provider", "free", "price", "currency")}}
