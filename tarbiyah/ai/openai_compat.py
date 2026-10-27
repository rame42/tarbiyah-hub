"""Optional non-Claude AI provider for services that implement the OpenAI-style
"chat completions" API: OpenAI, Google Gemini (OpenAI-compatible endpoint), DeepSeek,
Mistral, Groq, OpenRouter, and similar.

Selected with TH_AI_PROVIDER=openai_compatible in .env, plus TH_AI_BASE_URL, TH_AI_API_KEY
and TH_AI_MODEL. It plugs into the same place as Claude: same structured outputs (validated
with the same Pydantic schemas), same daily call/spend limits, same quote verification
downstream. Scanned-page OCR is Claude-only; with this provider OCR uses Tesseract.
"""
from __future__ import annotations

import json
import re
import time
from typing import Any, TypeVar

import requests
from pydantic import BaseModel, ValidationError

from ..config import get_config
from .claude import UNTRUSTED_NOTICE, AIRefused, AIUnavailable, ClaudeProvider

T = TypeVar("T", bound=BaseModel)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)


# Friendly names for TH_AI_PROVIDER; the address is filled in when TH_AI_BASE_URL is empty.
KNOWN_SERVICES = {
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openai": "https://api.openai.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "deepseek": "https://api.deepseek.com",
    "mistral": "https://api.mistral.ai/v1",
}


def model_name() -> str:
    """Accept display names too: 'Gemini 2.5 Flash' -> 'gemini-2.5-flash'; strip quotes and 'models/'."""
    m = get_config().ai_model.strip().strip("\"'").strip()
    if m.lower().startswith("models/"):
        m = m[7:]
    if " " in m or (m != m.lower() and get_config().ai_provider.strip().lower() == "gemini"):
        m = "-".join(m.lower().split())
    return m


def list_models() -> list[str]:
    """Model ids the key can use (OpenAI-style GET /models)."""
    cfg = get_config()
    r = requests.get(base_url().rstrip("/") + "/models", headers={"Authorization": f"Bearer {cfg.ai_api_key}"},
                     timeout=30)
    r.raise_for_status()
    ids = [str(m.get("id", "")) for m in (r.json().get("data") or [])]
    return sorted({i[7:] if i.startswith("models/") else i for i in ids if i})


def base_url() -> str:
    cfg = get_config()
    return (cfg.ai_base_url or KNOWN_SERVICES.get(cfg.ai_provider.strip().lower(), "")).strip()


class OpenAICompatProvider(ClaudeProvider):
    @property
    def name(self) -> str:  # shown on the dashboard
        p = get_config().ai_provider.strip().lower()
        return p if p in KNOWN_SERVICES else "openai_compatible"

    def configured(self) -> bool:
        cfg = get_config()
        return bool(cfg.ai_api_key and base_url() and cfg.ai_model and not cfg.ai_model.startswith("claude-"))

    def status(self) -> dict[str, Any]:
        st = super().status()
        st["provider"] = self.name
        st["base_url"] = base_url()
        if not self.configured():
            st["problem"] = ("Set TH_AI_BASE_URL, TH_AI_API_KEY and TH_AI_MODEL (your provider's model name) in .env.")
        return st

    def client(self):  # no SDK: plain HTTPS requests
        raise AIUnavailable("not used")

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        cfg = get_config()
        url = base_url().rstrip("/") + "/chat/completions"
        headers = {"Authorization": f"Bearer {cfg.ai_api_key}", "Content-Type": "application/json"}
        last: Exception | None = None
        for attempt in range(4):
            try:
                r = requests.post(url, headers=headers, data=json.dumps(body), timeout=600)
            except requests.RequestException as e:
                last = e
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (401, 403):
                raise AIUnavailable(f"The AI provider rejected the API key ({r.status_code}): {r.text[:300]}")
            if r.status_code == 429 or r.status_code >= 500:
                last = RuntimeError(f"AI provider busy ({r.status_code})")
                time.sleep(min(30, 3 * 2 ** attempt))
                continue
            if r.status_code >= 400:
                raise _BadRequest(r.status_code, r.text[:1000])
            return r.json()
        raise RuntimeError(f"AI provider unreachable: {last}")

    def _complete(self, system: str, content: str, max_tokens: int, response_format: dict | None) -> tuple[str, Any]:
        self._check_budget()
        model = model_name()
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": f"{system}\n\n{UNTRUSTED_NOTICE}"},
                         {"role": "user", "content": content}],
            "max_tokens": max_tokens,
        }
        if response_format:
            body["response_format"] = response_format
        data = self._post(body)
        usage = data.get("usage") or {}
        self._record(model, _Usage(usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)))
        choice = (data.get("choices") or [{}])[0]
        reason = choice.get("finish_reason")
        msg = choice.get("message") or {}
        if reason == "content_filter" or msg.get("refusal"):
            raise AIRefused(f"The AI provider declined the request: {msg.get('refusal') or reason}")
        if reason == "length":
            raise RuntimeError(f"AI output truncated (max_tokens={max_tokens})")
        return msg.get("content") or "", data

    @staticmethod
    def _as_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        raise AIUnavailable("This AI provider is used for text tasks only (document/image input needs Claude).")

    def structured(self, task: str, system: str, content: Any, schema: type[T], max_tokens: int = 16000,
                   effort: str | None = None) -> T:
        text = self._as_text(content)
        json_schema = schema.model_json_schema()
        fmt = {"type": "json_schema", "json_schema": {"name": schema.__name__, "schema": json_schema, "strict": False}}
        try:
            raw, _ = self._complete(system, text, max_tokens, fmt)
        except _BadRequest:
            # provider without JSON-schema support: ask for JSON in the instructions instead
            raw, _ = self._complete(system + "\n\nReply with ONLY a JSON object matching this JSON schema:\n"
                                    + json.dumps(json_schema), text, max_tokens, {"type": "json_object"})
        try:
            return schema.model_validate_json(_FENCE.sub("", raw.strip()))
        except ValidationError as e:
            raise RuntimeError(f"AI provider returned JSON that does not match the expected structure: {e}") from e

    def text(self, task: str, system: str, content: Any, max_tokens: int = 32000, effort: str | None = None) -> str:
        raw, _ = self._complete(system, self._as_text(content), max_tokens, None)
        return raw.strip()

    def ocr_pdf_pages(self, pdf_bytes: bytes, pages: list[int]) -> dict[int, str]:
        raise AIUnavailable("OCR with this AI provider is not supported; install Tesseract (see docs).")


class _BadRequest(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"AI provider rejected the request ({status}): {body}")


class _Usage:
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
