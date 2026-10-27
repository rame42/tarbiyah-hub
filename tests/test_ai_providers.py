"""Other AI providers through the OpenAI-style chat completions API, against a local stand-in server
(not a real provider): structured output, JSON-mode fallback, usage/budget accounting, refusals."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tarbiyah.ai import schemas as S
from tarbiyah.db import session_scope
from tarbiyah.settings import flush_usage, get_usage


class FakeLLM(BaseHTTPRequestHandler):
    requests: list[dict] = []
    reject_schema = False
    refuse = False

    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeLLM.requests.append({"path": self.path, "body": body, "auth": self.headers.get("Authorization")})
        fmt = (body.get("response_format") or {}).get("type")
        if FakeLLM.reject_schema and fmt == "json_schema":
            return self._send({"error": {"message": "response_format json_schema unsupported"}}, 400)
        if FakeLLM.refuse:
            return self._send({"choices": [{"finish_reason": "content_filter", "message": {"content": None}}],
                               "usage": {"prompt_tokens": 10, "completion_tokens": 0}})
        content = json.dumps({"terms_en": ["parenting style"], "terms_ar": ["أساليب المعاملة الوالدية"]}) if fmt else "plain answer"
        if (body.get("response_format") or {}).get("json_schema", {}).get("name") == "AssistantAnswer":
            import re

            pid = int(re.search(r'<passage id="(\d+)"', body["messages"][1]["content"]).group(1))
            content = json.dumps({"answer": f"An authoritative style is associated with better regulation [P{pid}].",
                                  "sufficiency": "partial", "evidence_vs_interpretation": "Stated by the source.",
                                  "citations": [{"passage_id": pid, "quote": "authoritative style"}]})
        if fmt == "json_object":
            content = "```json\n" + content + "\n```"
        self._send({"choices": [{"finish_reason": "stop", "message": {"content": content}}],
                    "usage": {"prompt_tokens": 1000, "completion_tokens": 500}})

    def _send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)


@pytest.fixture()
def other_ai(env, monkeypatch):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FakeLLM)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    FakeLLM.requests, FakeLLM.reject_schema, FakeLLM.refuse = [], False, False
    for k, v in {"TH_AI_PROVIDER": "openai_compatible", "TH_AI_BASE_URL": f"http://127.0.0.1:{srv.server_port}/v1",
                 "TH_AI_API_KEY": "k-test", "TH_AI_MODEL": "some-model", "TH_AI_PRICE_INPUT": "1.0",
                 "TH_AI_PRICE_OUTPUT": "2.0"}.items():
        monkeypatch.setenv(k, v)
    from tarbiyah.ai import claude as claude_mod
    from tarbiyah.config import reset_config_cache

    reset_config_cache()
    claude_mod.set_provider(None)
    yield claude_mod.claude()
    srv.shutdown()
    claude_mod.set_provider(None)


def test_structured_output_usage_and_budget(other_ai):
    assert other_ai.name == "openai_compatible" and other_ai.available()
    out = other_ai.structured("query_terms", "sys", "Question: parenting", S.QueryTerms, max_tokens=500)
    assert out.terms_ar == ["أساليب المعاملة الوالدية"]
    req = FakeLLM.requests[0]
    assert req["path"] == "/v1/chat/completions" and req["auth"] == "Bearer k-test"
    assert req["body"]["model"] == "some-model" and req["body"]["response_format"]["type"] == "json_schema"
    assert "untrusted data" in req["body"]["messages"][0]["content"]  # same prompt-injection notice as Claude
    flush_usage()
    with session_scope() as s:
        assert get_usage(s, "ai_calls") == 1
        assert abs(get_usage(s, "ai_cost_usd") - (1000 * 1.0 + 500 * 2.0) / 1e6) < 1e-9  # configured prices
    assert other_ai.text("output", "sys", "hi") == "plain answer"


def test_json_mode_fallback_refusal_and_no_ocr(other_ai):
    from tarbiyah.ai.claude import AIRefused, AIUnavailable

    FakeLLM.reject_schema = True
    out = other_ai.structured("query_terms", "sys", "q", S.QueryTerms)
    assert out.terms_en == ["parenting style"]  # retried with json_object, code fences stripped
    assert [r["body"]["response_format"]["type"] for r in FakeLLM.requests] == ["json_schema", "json_object"]
    FakeLLM.reject_schema, FakeLLM.refuse = False, True
    with pytest.raises(AIRefused):
        other_ai.structured("query_terms", "sys", "q", S.QueryTerms)
    with pytest.raises(AIUnavailable):
        other_ai.ocr_pdf_pages(b"%PDF", [1])


def test_assistant_runs_on_other_provider(other_ai, fixtures_dir):
    from tarbiyah.agents.assistant import answer
    from tarbiyah.ingest.pipeline import import_local_file, process

    with session_scope() as s:
        r, _ = import_local_file(s, fixtures_dir / "en_parenting.pdf")
        process(s, r)
    FakeLLM.reject_schema = False
    with session_scope() as s:
        res = answer(s, "What parenting style supports emotional regulation?", "en")
    assert res["mode"] == "ai" and res["expanded_terms"][0] == "parenting style"
    assert res["citations"][0]["verified"]  # quote checked against the stored passage, same as with Claude


def test_free_plan_prices_zero(other_ai, monkeypatch):
    monkeypatch.setenv("TH_AI_PRICE_INPUT", "0")
    monkeypatch.setenv("TH_AI_PRICE_OUTPUT", "0")
    from tarbiyah.config import reset_config_cache

    reset_config_cache()
    other_ai.structured("query_terms", "sys", "q", S.QueryTerms)
    flush_usage()
    with session_scope() as s:
        assert get_usage(s, "ai_calls") == 1 and get_usage(s, "ai_cost_usd") == 0  # free plan: no spend counted


def test_friendly_provider_name_fills_address(env, monkeypatch):
    for k, v in {"TH_AI_PROVIDER": "gemini", "TH_AI_BASE_URL": "", "TH_AI_API_KEY": "k", "TH_AI_MODEL": "m"}.items():
        monkeypatch.setenv(k, v)
    from tarbiyah.ai import claude as claude_mod
    from tarbiyah.ai.openai_compat import base_url
    from tarbiyah.config import reset_config_cache

    reset_config_cache()
    claude_mod.set_provider(None)
    p = claude_mod.claude()
    assert p.name == "gemini" and p.configured()
    assert base_url() == "https://generativelanguage.googleapis.com/v1beta/openai"
    claude_mod.set_provider(None)
