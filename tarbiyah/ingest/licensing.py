"""Decide whether a resource may be downloaded and stored.

The rule is conservative: a file is downloaded only when there is a positive basis
(public domain, an open licence, an open-access repository statement, the user's own
import, or a site the user registered with explicit permission). Being publicly
viewable is NOT a basis. Everything else is catalogued as metadata + authorized link.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

OPEN_LICENSE = re.compile(
    r"(creativecommons\.org/(licenses|publicdomain)|\bcc[- ]?(by|0|zero)\b|cc-by|public[- ]domain|"
    r"\bpd\b|publicdomain|opendatacommons|gnu free documentation|\bgfdl\b|\bmit license\b|"
    r"open government licen[cs]e)",
    re.I,
)
NON_COMMERCIAL_OK = True  # research/personal library use is non-commercial


@dataclass
class AccessDecision:
    access_status: str
    download_permitted: bool
    basis: str


def decide(license_text: str | None = None, *, public_domain: bool = False, open_access: bool = False,
           oa_status: str | None = None, paid: bool = False, lending_only: bool = False,
           restricted: bool = False, user_provided: bool = False, site_permission: bool = False,
           allow_free_to_read: bool = False) -> AccessDecision:
    lic = (license_text or "").strip()
    if user_provided:
        return AccessDecision("user_provided", True, "Imported by the user from their own files.")
    if public_domain:
        return AccessDecision("public_domain", True, f"Public domain per source metadata{f' ({lic})' if lic else ''}.")
    if lic and OPEN_LICENSE.search(lic):
        if re.search(r"\bnd\b|-nd", lic, re.I):
            basis = f"Open licence {lic} (no-derivatives: original kept unmodified)."
        else:
            basis = f"Open licence: {lic}."
        return AccessDecision("open_license", True, basis)
    if paid:
        return AccessDecision("paid", False, "Commercial resource: metadata and purchase link only.")
    if lending_only:
        return AccessDecision("lending_only", False, "Available only through controlled digital lending.")
    if restricted:
        return AccessDecision("restricted", False, "Access restricted by the source.")
    if site_permission:
        return AccessDecision("open_access", True, "User registered this site with download permission.")
    if open_access or (oa_status and oa_status.lower() in {"gold", "diamond", "green", "hybrid"}):
        if allow_free_to_read:
            return AccessDecision("open_access", True,
                                  f"Open access ({oa_status or 'repository'}); downloads of free-to-read files enabled in settings.")
        return AccessDecision("open_access", False,
                              f"Open access ({oa_status or 'repository'}) but no explicit licence found: link kept, file not stored.")
    if oa_status and oa_status.lower() == "bronze":
        return AccessDecision("free_to_read", allow_free_to_read,
                              "Free to read on publisher site without a licence.")
    return AccessDecision("unknown", False, "No licence information: metadata and link only.")
