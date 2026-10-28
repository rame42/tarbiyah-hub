"""Edit the .env file (keys and AI settings) from the dashboard.

Only the keys listed in FIELDS can be changed. Secret values are never sent back to the browser:
the dashboard sees whether a key is set and its last 4 characters. Existing lines, comments and
unknown keys in .env are kept as they are. The web server and the worker pick up changes without
a restart (`reload_if_changed`).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from . import config as _config
from .config import reset_config_cache

AI_PROVIDERS = ["claude", "gemini", "openai", "groq", "openrouter", "deepseek", "mistral", "openai_compatible"]

# key, group, label, secret, help, choices
FIELDS: list[dict[str, Any]] = [
    {"key": "TH_AI_PROVIDER", "group": "ai", "label": "AI service", "choices": AI_PROVIDERS,
     "help": "claude = Anthropic Claude (strongest). gemini = Google Gemini (has a free plan). Others are optional."},
    {"key": "TH_AI_MODEL", "group": "ai", "label": "AI model",
     "help": "Claude: claude-opus-5-5 (best) or claude-sonnet-5-5 (cheaper). Gemini: gemini-2.5-flash (free, fast) "
             "or gemini-2.5-pro (stronger; small free quota)."},
    {"key": "ANTHROPIC_API_KEY", "group": "ai", "label": "Claude API key", "secret": True,
     "help": "From console.anthropic.com > API keys. Used when the AI service is claude."},
    {"key": "TH_AI_API_KEY", "group": "ai", "label": "API key for the other AI service", "secret": True,
     "help": "Gemini: aistudio.google.com > Get API key. Used when the AI service is not claude."},
    {"key": "TH_AI_BASE_URL", "group": "ai", "label": "Service address (only for openai_compatible)",
     "help": "Leave empty for the named services; it is filled in automatically."},
    {"key": "YOUTUBE_API_KEY", "group": "collect", "label": "YouTube API key", "secret": True,
     "help": "Free. Enables YouTube search, full channel history and course playlists."},
    {"key": "APIFY_TOKEN", "group": "collect", "label": "Apify token", "secret": True,
     "help": "Paid service with monthly free credit; for TikTok, Facebook, Instagram via Apify."},
    {"key": "CORE_API_KEY", "group": "collect", "label": "CORE API key (open-access papers)", "secret": True},
    {"key": "VOYAGE_API_KEY", "group": "collect", "label": "Voyage key (meaning-based search)", "secret": True},
    {"key": "REDDIT_CLIENT_ID", "group": "social", "label": "Reddit client id"},
    {"key": "REDDIT_CLIENT_SECRET", "group": "social", "label": "Reddit client secret", "secret": True},
    {"key": "FACEBOOK_ACCESS_TOKEN", "group": "social", "label": "Facebook access token", "secret": True},
    {"key": "INSTAGRAM_ACCESS_TOKEN", "group": "social", "label": "Instagram access token", "secret": True},
    {"key": "INSTAGRAM_BUSINESS_ACCOUNT_ID", "group": "social", "label": "Instagram business account id"},
    {"key": "X_BEARER_TOKEN", "group": "social", "label": "X (Twitter) bearer token", "secret": True},
    {"key": "TIKTOK_CLIENT_KEY", "group": "social", "label": "TikTok client key"},
    {"key": "TIKTOK_CLIENT_SECRET", "group": "social", "label": "TikTok client secret", "secret": True},
    {"key": "TH_CONTACT_EMAIL", "group": "other", "label": "Contact e-mail (sent to OpenAlex/Crossref)",
     "help": "Recommended: academic services answer faster when they know who is asking."},
    {"key": "TH_UPDATE_REPO", "group": "other", "label": "Updates: GitHub repository (owner/name)"},
    {"key": "TH_UPDATE_TOKEN", "group": "other", "label": "Updates: GitHub token (private repository only)",
     "secret": True},
]
ALLOWED = {f["key"]: f for f in FIELDS}
_last_mtime: float | None = None


def env_path() -> Path:
    return _config.ENV_FILE


def _read_lines() -> list[str]:
    p = env_path()
    if not p.exists():
        txt = p.with_name(".env.txt")  # Notepad's habit; use it rather than start empty
        p = txt if txt.exists() else p
    try:
        return p.read_text(encoding="utf-8-sig", errors="ignore").splitlines()
    except OSError:
        return []


def read_values() -> dict[str, str]:
    out: dict[str, str] = {}
    for line in _read_lines():
        if line.lstrip().startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if sep and name.strip():
            out[name.strip()] = value.strip().strip("\"'").strip()
    return out


def _mask(v: str) -> str:
    return f"…{v[-4:]}" if len(v) > 8 else "set"


def public_view() -> list[dict[str, Any]]:
    vals = read_values()
    out = []
    for f in FIELDS:
        v = vals.get(f["key"], "")
        item = {k: f.get(k) for k in ("key", "group", "label", "help", "choices")}
        item["secret"] = bool(f.get("secret"))
        item["is_set"] = bool(v)
        item["value"] = (_mask(v) if v else "") if f.get("secret") else v
        out.append(item)
    return out


def write_values(changes: dict[str, Any]) -> list[str]:
    """Apply changes. For secrets an empty value means 'keep'; None or '__clear__' removes the value."""
    clean: dict[str, str] = {}
    for k, v in changes.items():
        f = ALLOWED.get(k)
        if f is None:
            raise ValueError(f"'{k}' cannot be changed here.")
        if v is None or v == "__clear__":
            clean[k] = ""
            continue
        v = str(v).strip().strip("\"'").strip()
        if "\n" in v or "\r" in v:
            raise ValueError(f"{f['label']}: must be on one line.")
        if f.get("secret") and v == "":
            continue  # left empty in the form: keep the saved key
        if f.get("secret") and " " in v:
            raise ValueError(f"{f['label']}: a key never contains spaces. Copy it again.")
        if f.get("choices") and v and v not in f["choices"]:
            raise ValueError(f"{f['label']}: choose one of {', '.join(f['choices'])}.")
        clean[k] = v
    if not clean:
        return []
    lines = _read_lines()
    done: set[str] = set()
    for i, line in enumerate(lines):
        name, sep, _ = line.partition("=")
        key = name.strip()
        if sep and key in clean and not line.lstrip().startswith("#"):
            if key in done:
                lines[i] = ""  # a duplicate line would be confusing; keep one
                continue
            lines[i] = f"{key}={clean[key]}"
            done.add(key)
    missing = [k for k in clean if k not in done]
    if missing:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"{k}={clean[k]}" for k in missing]
    p = env_path()
    tmp = p.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    os.replace(tmp, p)
    reload_now()
    return sorted(clean)


def reload_now() -> None:
    """Make this process use the new values (config and AI provider)."""
    global _last_mtime
    for k in ALLOWED:  # values set in the environment would hide the file's values
        os.environ.pop(k, None)
    reset_config_cache()
    from .ai.claude import set_provider

    set_provider(None)
    try:
        _last_mtime = env_path().stat().st_mtime
    except OSError:
        _last_mtime = None


def reload_if_changed() -> bool:
    """Called regularly by the worker: pick up .env edits made in the dashboard or in Notepad."""
    global _last_mtime
    try:
        m = env_path().stat().st_mtime
    except OSError:
        return False
    if _last_mtime is None:
        _last_mtime = m
        return False
    if m != _last_mtime:
        reload_now()
        return True
    return False
