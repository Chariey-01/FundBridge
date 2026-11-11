"""Wire-level tests of the OpenAI provider against a mocked HTTP transport.

These check the request we send and how responses and errors are mapped. They do
not prove the live API accepts the request; that needs a real key.
"""

from __future__ import annotations

import json

import httpx
import pytest

from app.integrations.ai.base import (
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
