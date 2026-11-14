"""`python -m tarbiyah test-ai`: check the AI settings and make one tiny request, printing
plain-language results. Never prints the key itself."""
from __future__ import annotations

import json
from pathlib import Path

import requests

from .config import PROJECT_ROOT, get_config


def _mask(key: str) -> str:
    return f"{key[:4]}…{key[-4:]} ({len(key)} characters)" if len(key) > 10 else "(too short)"


def run(out=print, _retry: bool = True) -> bool:
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
        from .ai.claude import claude_model

        key, model, url = cfg.anthropic_api_key, claude_model(), "https://api.anthropic.com"
        if model != cfg.ai_model.strip():
            out(f"(the model box says '{cfg.ai_model.strip() or 'nothing'}', which is not a Claude model, so '{model}' is used)")
    else:
        from .ai.openai_compat import KNOWN_SERVICES, base_url

        if provider not in KNOWN_SERVICES and provider not in ("openai_compatible", "other"):
            out(f"PROBLEM: unknown provider name '{provider}'. Use one of: claude, {', '.join(KNOWN_SERVICES)}, openai_compatible.")
            return False
        from .ai.openai_compat import model_name

        key, model, url = cfg.ai_api_key, model_name(), base_url()
        if model != cfg.ai_model.strip():
            if not cfg.ai_model.strip() or cfg.ai_model.strip().lower().startswith("claude-"):
                out(f"(the model box says '{cfg.ai_model.strip() or 'nothing'}', which is not a {provider} model, "
                    f"so {provider}'s default '{model}' is used)")
            else:
                out(f"(model name '{cfg.ai_model.strip()}' is used as '{model}')")
    out(f"Service address: {url or '(empty)'}")
    out(f"Model (TH_AI_MODEL): {model or '(empty)'}")
    out(f"Key ({'ANTHROPIC_API_KEY' if provider in ('', 'claude') else 'TH_AI_API_KEY'}): {_mask(key) if key else '(empty)'}\n")
    problems = []
    if not key:
        problems.append("The key is empty. Put it right after TH_AI_API_KEY= on the same line.")
    elif key != key.strip() or key[0] in "\"'" or " " in key:
        problems.append("The key contains quotes or spaces. Remove them: TH_AI_API_KEY=yourkey")
    if not model:
        problems.append("TH_AI_MODEL is missing. Copy the exact model name from the service's model list.")
    elif provider not in ("", "claude") and model.startswith("claude-"):
        example = {"gemini": "gemini-2.5-flash", "openai": "gpt-4o-mini", "groq": "llama-3.3-70b-versatile"}.get(provider, "")
        problems.append(f"'{model}' is a Claude model, but the AI service is '{provider}'. Either set the AI model to one "
                        f"of {provider}'s models" + (f" (for example {example})" if example else "") +
                        ", or set the AI service to 'claude' and use a Claude key (it starts with sk-ant-).")
    if not url:
        problems.append("The service address is empty (TH_AI_BASE_URL).")
    if problems:
        for p in problems:
            out("PROBLEM: " + p)
        return False
    if provider in ("", "claude"):
        return _test_claude(out, key, model)
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
        out("Done: Tarbiyah Hub uses this AI from now on (no restart needed). The dashboard AI badge shows it as configured.")
        return True
    body = r.text[:600]
    if r.status_code == 404 and _retry:
        from .ai.openai_compat import recommended_model, switch_model

        new = recommended_model(r.text, model)
        if new:
            out(f"The service has retired '{model}' and recommends '{new}'.")
            out(f"Switching the AI model to '{new}' (saved in Settings) and trying again...\n")
            switch_model(new)
            return run(out, _retry=False)
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
    elif "model" in low and ("not found" in low or "not_found" in low or "no longer available" in low
                             or "not supported" in low or "invalid" in low or "format" in low):
        hint = "The model name is wrong. Put one of the names listed below after TH_AI_MODEL= in .env."
        try:
            from .ai.openai_compat import list_models

            names = list_models()
            pref = [n for n in names if "flash" in n] + [n for n in names if "flash" not in n]
            if pref:
                out("Model names your key can use (Flash models first):")
                for n in pref[:25]:
                    out("   " + n)
                out("")
        except Exception as e:  # noqa: BLE001 - listing is a convenience
            out(f"(Could not list models: {e})")
    else:
        hint = hints.get(r.status_code, "Read the message above; send it to your helper if unclear.")
    out("FIX: " + hint)
    return False


def _test_claude(out, key: str, model: str) -> bool:
    """Send Claude one tiny message and explain the answer in plain words."""
    import anthropic

    if not key.startswith("sk-ant-"):
        out("NOTE: Claude API keys start with 'sk-ant-'. This key does not, so it is probably not a Claude key.\n")
    elif len(key) < 80:
        out(f"NOTE: this key is only {len(key)} characters long; a full Claude key is about 100 characters "
            "(sk-ant-api03-...). Part of it is probably missing: copy it again in one piece.\n")
    out("Sending one short test message to Claude...")
    client = anthropic.Anthropic(api_key=key, max_retries=1, timeout=60.0)
    try:
        r = client.messages.create(model=model, max_tokens=20,
                                   messages=[{"role": "user", "content": "Reply with the word OK."}])
    except anthropic.AuthenticationError:
        out("PROBLEM: Claude rejected the key.")
        out("FIX: in console.anthropic.com > API keys, create a key, copy it whole and paste it in "
            "Settings > Keys & AI > Claude API key. A Gemini/Google key does not work here.")
        return False
    except anthropic.PermissionDeniedError as e:
        out(f"PROBLEM: this key is not allowed to use Claude: {e.message}")
        return False
    except anthropic.NotFoundError:
        out(f"PROBLEM: Claude does not know the model '{model}'.")
        try:
            names = [m.id for m in client.models.list(limit=50).data]
            out("Model names your key can use (put one in Settings > Keys & AI > AI model):")
            for n in names[:20]:
                out("   " + n)
        except Exception:  # noqa: BLE001 - listing is a convenience
            out("FIX: put a Claude model name such as claude-haiku-5-5 in the AI model box.")
        return False
    except anthropic.RateLimitError:
        out("PROBLEM: Claude's limit for this key is reached right now. Wait a minute and test again.")
        return False
    except anthropic.BadRequestError as e:
        msg = str(getattr(e, "message", e))
        if "credit" in msg.lower() or "billing" in msg.lower():
            out("PROBLEM: the Claude account behind this key has no API credit.")
            out("FIX: a Claude.ai chat subscription (free or paid) does not include API use. Add credit in "
                "console.anthropic.com > Billing, or use the free Gemini service instead (AI service: gemini).")
        else:
            out(f"PROBLEM: Claude refused the test request: {msg}")
        return False
    except anthropic.APIConnectionError as e:
        out(f"PROBLEM: could not reach Claude: {e}")
        out("FIX: check the internet connection, and allow Python through Windows Firewall/antivirus.")
        return False
    reply = "".join(getattr(b, "text", "") for b in r.content).strip()
    out(f"SUCCESS: Claude answered: {reply!r}")
    out("Done: Tarbiyah Hub uses Claude from now on (no restart needed). The dashboard AI badge shows it as configured.")
    return True


if __name__ == "__main__":
    run()
