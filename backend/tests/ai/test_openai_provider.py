"""Wire-level tests of the OpenAI provider against a mocked HTTP transport.

These check the request we send and how responses and errors are mapped. They do
not prove the live API accepts the request; that needs a real key.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.integrations.ai.base import (
    AIProviderError,
    AIProviderInvalidOutput,
    AIProviderRefusal,
    AIProviderTimeout,
    AIProviderUnavailable,
    StructuredRequest,
)
from app.integrations.ai.factory import build_ai_provider
from app.integrations.ai.openai_provider import OpenAIProvider

REQ = StructuredRequest(
    task="campaign_search",
    system_prompt="sys",
    user_content="user",
    json_schema={"type": "object", "additionalProperties": False, "properties": {"k": {"type": "string"}},
                 "required": ["k"]},
    max_output_tokens=123,
    safety_identifier="abc",
)


def completion(content=None, finish_reason="stop", refusal=None):
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": "gpt-test-2026",
        "choices": [
            {
                "index": 0,
                "finish_reason": finish_reason,
                "message": {"role": "assistant", "content": content, "refusal": refusal},
            }
        ],
    }


def provider_with(handler) -> OpenAIProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    return OpenAIProvider(api_key="sk-test", model="gpt-test", http_client=client, max_retries=0)


def test_request_shape_and_success():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=completion('{"k": "v"}'))

    result = provider_with(handler).generate_structured(REQ)
    assert result.data == {"k": "v"} and result.model == "gpt-test-2026" and result.provider == "openai"
    assert seen["url"].endswith("/chat/completions")
    assert seen["auth"] == "Bearer sk-test"
    body = seen["body"]
    assert body["model"] == "gpt-test"
    assert body["store"] is False
    assert body["max_completion_tokens"] == 123
    assert body["safety_identifier"] == "abc"
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["strict"] is True
    assert body["messages"][0] == {"role": "system", "content": "sys"}


@pytest.mark.parametrize(
    "response, exc",
    [
        (completion(None, refusal="I can't help with that"), AIProviderRefusal),
        (completion('{"k": "v"', finish_reason="length"), AIProviderInvalidOutput),
        (completion("not json"), AIProviderInvalidOutput),
        (completion("[1, 2]"), AIProviderInvalidOutput),
    ],
)
def test_bad_outputs_raise(response, exc):
    with pytest.raises(exc):
        provider_with(lambda r: httpx.Response(200, json=response)).generate_structured(REQ)


def test_auth_and_rate_limit_errors_map_to_unavailable():
    for status in (401, 429):
        p = provider_with(lambda r, s=status: httpx.Response(s, json={"error": {"message": "x"}}))
        with pytest.raises(AIProviderUnavailable):
            p.generate_structured(REQ)


def test_timeout_maps_to_timeout():
    def handler(request):
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(AIProviderTimeout):
        provider_with(handler).generate_structured(REQ)


def test_factory_modes(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AI_PROVIDER", raising=False)
    assert build_ai_provider({}) is None
    assert build_ai_provider({"AI_PROVIDER": "openai"}) is None  # no key: fallback, not crash
    assert build_ai_provider({"AI_PROVIDER": "disabled", "OPENAI_API_KEY": "sk"}) is None
    p = build_ai_provider({"OPENAI_API_KEY": "sk", "OPENAI_MODEL": "m"})
    assert isinstance(p, OpenAIProvider) and p.model == "m"
    with pytest.raises(ValueError):
        build_ai_provider({"AI_PROVIDER": "other"})


# ------------------------------------------------------------------ failure modes over HTTP


def counting_provider(handler, *, max_retries=0, model="gpt-test"):
    calls = {"n": 0}

    def wrapped(request):
        calls["n"] += 1
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(wrapped))
    return OpenAIProvider(api_key="sk-test", model=model, http_client=client, max_retries=max_retries), calls


@pytest.mark.parametrize("status", [500, 502, 503])
def test_server_errors_are_retried_then_raise_provider_error(status):
    provider, calls = counting_provider(lambda r: httpx.Response(status, json={"error": {"message": "boom"}}),
                                        max_retries=1)
    with pytest.raises(AIProviderError) as info:
        provider.generate_structured(REQ)
    assert not isinstance(info.value, AIProviderUnavailable)
    assert calls["n"] == 2  # the first attempt plus AI_MAX_RETRIES


def test_rate_limit_and_quota_are_unavailable_without_hanging():
    for body in ({"error": {"message": "Rate limit reached", "type": "requests"}},
                 {"error": {"message": "You exceeded your current quota", "code": "insufficient_quota"}}):
        provider, calls = counting_provider(
            lambda r, b=body: httpx.Response(429, json=b, headers={"retry-after": "30"}), max_retries=0)
        with pytest.raises(AIProviderUnavailable, match="rate limit or quota"):
            provider.generate_structured(REQ)
        assert calls["n"] == 1


def test_unknown_model_and_rejected_parameters_name_the_configuration():
    provider, _ = counting_provider(lambda r: httpx.Response(404, json={"error": {"message": "model not found"}}),
                                    model="gpt-retired")
    with pytest.raises(AIProviderUnavailable, match="gpt-retired"):
        provider.generate_structured(REQ)
    provider, _ = counting_provider(lambda r: httpx.Response(400, json={"error": {
        "message": "Unsupported parameter: 'reasoning_effort'", "param": "reasoning_effort"}}))
    with pytest.raises(AIProviderUnavailable, match="OPENAI_REASONING_EFFORT"):
        provider.generate_structured(REQ)


def test_connection_failure_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("refused", request=request)

    provider, _ = counting_provider(handler)
    with pytest.raises(AIProviderUnavailable):
        provider.generate_structured(REQ)


@pytest.mark.parametrize("response", [
    httpx.Response(200, text="<html>gateway error</html>", headers={"content-type": "text/html"}),
    httpx.Response(200, text="{not json", headers={"content-type": "application/json"}),
    httpx.Response(200, json={"unexpected": "shape"}),
])
def test_malformed_http_bodies_raise_provider_errors(response):
    provider, _ = counting_provider(lambda r: response)
    with pytest.raises(AIProviderError):
        provider.generate_structured(REQ)


@pytest.mark.parametrize("payload, exc", [
    ({**completion('{"k": "v"}'), "choices": []}, AIProviderInvalidOutput),
    (completion('{"k": "v"}', finish_reason="content_filter"), AIProviderRefusal),
    (completion(""), AIProviderInvalidOutput),
])
def test_empty_or_filtered_completions(payload, exc):
    provider, _ = counting_provider(lambda r: httpx.Response(200, json=payload))
    with pytest.raises(exc):
        provider.generate_structured(REQ)


# ------------------------------------------------------------------ model and reasoning configuration


def _sent_body(config):
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=completion('{"k": "v"}'))

    provider = build_ai_provider({"OPENAI_API_KEY": "sk", **config})
    provider._client = provider._client.with_options(http_client=httpx.Client(transport=httpx.MockTransport(handler)),
                                                     max_retries=0)
    provider.generate_structured(REQ)
    return provider, seen


def test_default_model_is_a_reasoning_model_with_low_effort_and_token_allowance(monkeypatch):
    for key in ("OPENAI_MODEL", "OPENAI_REASONING_EFFORT", "OPENAI_REASONING_TOKEN_ALLOWANCE"):
        monkeypatch.delenv(key, raising=False)
    provider, body = _sent_body({})
    assert provider.model == "gpt-5.4-mini"
    assert body["reasoning_effort"] == "low"
    assert body["max_completion_tokens"] == REQ.max_output_tokens + 1024


@pytest.mark.parametrize("config, effort, tokens", [
    ({"OPENAI_MODEL": "gpt-4o-mini"}, None, 123),                                   # non-reasoning: nothing extra
    ({"OPENAI_MODEL": "gpt-5.4-mini", "OPENAI_REASONING_EFFORT": "omit"}, None, 123),
    ({"OPENAI_MODEL": "gpt-5.4-mini", "OPENAI_REASONING_EFFORT": "Minimal"}, "minimal", 123 + 1024),
    ({"OPENAI_MODEL": "o4-mini", "OPENAI_REASONING_TOKEN_ALLOWANCE": "200"}, "low", 323),
])
def test_reasoning_configuration(monkeypatch, config, effort, tokens):
    for key in ("OPENAI_MODEL", "OPENAI_REASONING_EFFORT", "OPENAI_REASONING_TOKEN_ALLOWANCE"):
        monkeypatch.delenv(key, raising=False)
    _, body = _sent_body(config)
    assert body.get("reasoning_effort") == effort
    assert body["max_completion_tokens"] == tokens
