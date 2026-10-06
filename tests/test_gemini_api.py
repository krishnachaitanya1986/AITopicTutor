import json

import httpx
import pytest

from tutor.config import load_env
from tutor.grok_client import DEFAULT_MODEL, GrokClient, TutorError, strict_schema
from tutor.models import Architecture, Explanation

VALID = {"explanation": "An explanation.", "key_points": ["A", "B", "C"], "pitfalls": ["D", "E"]}


def response(raw=None, **extra):
    return {
        "choices": [{"finish_reason": "stop", "message": {"content": json.dumps(VALID) if raw is None else raw}}],
        "usage": {"prompt_tokens": 20, "completion_tokens": 30},
        **extra,
    }


def client(handler, **kwargs):
    return GrokClient(
        api_key="test-key",
        transport=httpx.MockTransport(handler),
        sleep=lambda _: None,
        **kwargs,
    )


def test_responses_payload_and_output():
    def handler(request):
        assert str(request.url) == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
        assert request.headers["Authorization"] == "Bearer test-key"
        body = json.loads(request.content)
        assert body["model"] == DEFAULT_MODEL
        assert body["stream"] is False
        assert body["response_format"]["type"] == "json_schema"
        assert body["response_format"]["json_schema"]["strict"] is True
        assert "messages" in body and "response_format" in body
        return httpx.Response(200, json=response())

    c = client(handler)
    assert c.generate(Explanation, "Explain", {}) == VALID
    assert c.usage == {"input_tokens": 20, "output_tokens": 30, "reported_responses": 1}


def test_model_access():
    c = client(lambda r: httpx.Response(200, json={"data": [{"id": DEFAULT_MODEL}]}))
    assert c.resolve_model() == DEFAULT_MODEL
    c.model = "nonexistent"
    with pytest.raises(TutorError, match="Available models"):
        c.resolve_model()


def test_missing_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    with pytest.raises(TutorError, match="API key"):
        GrokClient()


def test_nested_strict_schema():
    data = strict_schema(Architecture.model_json_schema())
    edge = data["$defs"]["Edge"]
    assert set(edge["required"]) == {"source", "target", "label"}
    assert edge["additionalProperties"] is False
    assert "default" not in edge["properties"]["label"]


@pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 422])
def test_nonretryable_errors_and_no_secret_leak(status):
    calls = []

    def handler(r):
        calls.append(1)
        return httpx.Response(status, text="test-key private server error")

    with pytest.raises(TutorError) as exc:
        client(handler).generate(Explanation, "Explain", {})
    assert len(calls) == 1 and "test-key" not in str(exc.value) and "private server" not in str(exc.value)


@pytest.mark.parametrize("status", [429, 500, 503])
def test_transient_retry(status):
    calls = []

    def handler(r):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(status, headers={"Retry-After": "0"})
        return httpx.Response(200, json=response())

    assert client(handler).generate(Explanation, "Explain", {}) == VALID
    assert len(calls) == 3


def test_json_repair_and_budget():
    calls = []

    def handler(r):
        calls.append(json.loads(r.content))
        return httpx.Response(200, json=response("{}" if len(calls) == 1 else None))

    client(handler).generate(Explanation, "Explain", {})
    assert len(calls) == 2 and len(calls[1]["messages"]) == 2

    c = client(lambda r: httpx.Response(200, json=response("{}")))
    with pytest.raises(TutorError, match="three attempts"):
        c.generate(Explanation, "Explain", {})
    assert c.usage["reported_responses"] == 3


def test_timeout_no_automatic_billable_retry():
    calls = []

    def handler(r):
        calls.append(1)
        raise httpx.ReadTimeout("private", request=r)

    with pytest.raises(TutorError, match="billed"):
        client(handler).generate(Explanation, "Explain", {})
    assert len(calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        response(finish_reason="length"),
        response(message={"content": "", "refusal": True}),
    ],
)
def test_incomplete_and_refusal_stop(body):
    calls = []

    def handler(r):
        calls.append(1)
        return httpx.Response(200, json=body)

    with pytest.raises(TutorError):
        client(handler).generate(Explanation, "Explain", {})
    assert len(calls) == 1


def test_env_loader(tmp_path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "environment-wins")
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_KEY=file-key\nGEMINI_MODEL=\"gemini-3.8-flash\"\nIGNORED=value\n",
        encoding="utf-8",
    )
    load_env(env_file)
    import os

    assert os.environ["GEMINI_API_KEY"] == "environment-wins"
    assert os.environ["GEMINI_MODEL"] == "gemini-3.8-flash"
    assert "IGNORED" not in os.environ
