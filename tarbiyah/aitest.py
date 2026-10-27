"""`python -m tarbiyah test-ai`: check the AI settings and make one tiny request, printing
plain-language results. Never prints the key itself."""
from __future__ import annotations

import json
from pathlib import Path

import requests

from .config import PROJECT_ROOT, get_config


def _mask(key: str) -> str:
    return f"{key[:4]}…{key[-4:]} ({len(key)} characters)" if len(key) > 10 else "(too short)"


def run(out=print) -> bool:
    cfg = get_config()
    env = PROJECT_ROOT / ".env"
    out("Tarbiyah Hub - AI connection test\n")
    if not env.exists():
        txt = PROJECT_ROOT / ".env.txt"
        if txt.exists():
            out("PROBLEM: your settings file is named '.env.txt' (Notepad added .txt).")
            out("FIX: rename it to exactly '.env' (in File Explorer: View > show 'File name extensions', then rename).")
        else:
            out(f"PROBLEM: no .env file found in {PROJECT_ROOT}.")
            out("FIX: copy .env.example, rename the copy to .env, and put your AI lines in it.")
        return False
    provider = cfg.ai_provider.strip().lower()
    out(f"Provider setting (TH_AI_PROVIDER): {provider or '(empty)'}")
    if provider in ("", "claude"):
        if not cfg.anthropic_api_key:
            out("PROBLEM: the provider is Claude but ANTHROPIC_API_KEY is empty.")
            out("FIX: for Gemini put TH_AI_PROVIDER=gemini in .env (check spelling, no spaces around =).")
            return False
        key, model, url = cfg.anthropic_api_key, cfg.ai_model, "https://api.anthropic.com"
    else:
        from .ai.openai_compat import KNOWN_SERVICES, base_url

        if provider not in KNOWN_SERVICES and provider not in ("openai_compatible", "other"):
            out(f"PROBLEM: unknown provider name '{provider}'. Use one of: claude, {', '.join(KNOWN_SERVICES)}, openai_compatible.")
            return False
        key, model, url = cfg.ai_api_key, cfg.ai_model, base_url()
    out(f"Service address: {url or '(empty)'}")
    out(f"Model (TH_AI_MODEL): {model or '(empty)'}")
    out(f"Key (TH_AI_API_KEY): {_mask(key) if key else '(empty)'}\n")
    problems = []
    if not key:
        problems.append("The key is empty. Put it right after TH_AI_API_KEY= on the same line.")
    elif key != key.strip() or key[0] in "\"'" or " " in key:
        problems.append("The key contains quotes or spaces. Remove them: TH_AI_API_KEY=yourkey")
    if not model or (provider not in ("", "claude") and model.startswith("claude-")):
        problems.append("TH_AI_MODEL is missing. Copy the exact model name from the service's model list.")
    if not url:
        problems.append("The service address is empty (TH_AI_BASE_URL).")
    if problems:
        for p in problems:
            out("PROBLEM: " + p)
        return False
    if provider in ("", "claude"):
        out("Settings look complete for Claude. (This test sends requests only to other services.)")
        return True
    out("Sending one short test message...")
    try:
        r = requests.post(url.rstrip("/") + "/chat/completions", timeout=60,
                          headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                          data=json.dumps({"model": model, "max_tokens": 20,
                                           "messages": [{"role": "user", "content": "Reply with the word OK."}]}))
    except requests.RequestException as e:
        out(f"PROBLEM: could not reach {url}: {e}")
        out("FIX: check the internet connection, and allow Python through Windows Firewall/antivirus.")
        return False
    if r.status_code == 200:
        try:
            reply = r.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError):
            reply = r.text[:200]
        out(f"SUCCESS: the AI answered: {reply!r}")
        out("Now restart Tarbiyah Hub (stop.bat, then start.bat). The dashboard AI badge should show it as configured.")
        return True
    body = r.text[:600]
    out(f"PROBLEM: the service answered with error {r.status_code}:\n{body}\n")
    hints = {
        400: "Usually a wrong model name. Copy the exact name from the model list (e.g. AI Studio > model selector).",
        401: "The key was rejected. Copy the key again (Copy key button) or create a new one.",
        403: "The key has no permission for this API, or the API is not enabled for its project.",
        404: "Wrong model name or address. Check TH_AI_MODEL spelling.",
        429: "Free-plan limit reached. Wait a minute (or until tomorrow) and try again.",
    }
    low = body.lower()
    if "key" in low and ("invalid" in low or "not valid" in low or "expired" in low):
        hint = ("The key was not accepted. Click 'Copy key' in AI Studio again and paste it right after "
                "TH_AI_API_KEY= with no spaces or quotes. If it still fails, create a new key.")
    elif "model" in low and ("not found" in low or "not supported" in low or "invalid" in low):
        hint = "The model name is wrong. Copy the exact model name from the service's model list."
    else:
        hint = hints.get(r.status_code, "Read the message above; send it to your helper if unclear.")
    out("FIX: " + hint)
    return False


if __name__ == "__main__":
    run()
