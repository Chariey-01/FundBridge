"""OpenAI provider using the Chat Completions API with strict JSON-schema output.

Verified against the installed ``openai`` Python SDK (2.x) signature:
``client.chat.completions.create(model, messages, response_format,
max_completion_tokens, store, safety_identifier, timeout)``.
Not verified against a live account in this repository: no API key was
available during development. The deterministic fallback in
``app.services.ai`` covers every feature when this provider fails.
"""

from __future__ import annotations

import json
import time
from typing import Any

from .base import (
    AIProviderError,
    AIProviderInvalidOutput,
    AIProviderRefusal,
    AIProviderTimeout,
    AIProviderUnavailable,
    StructuredRequest,
    StructuredResult,
)


class OpenAIProvider:
    name = "openai"
    live = True

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float = 15.0,
        max_retries: int = 1,
        base_url: str | None = None,
        http_client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAIProvider requires an API key")
        if not model:
            raise ValueError("OpenAIProvider requires a model name")
        import openai  # imported lazily so the app runs without the SDK when AI is disabled

        self._openai = openai
        kwargs: dict[str, Any] = {
            "api_key": api_key,
            "timeout": timeout_seconds,
            "max_retries": max_retries,
        }
        if base_url:
            kwargs["base_url"] = base_url
        if http_client is not None:
            kwargs["http_client"] = http_client
        self._client = openai.OpenAI(**kwargs)
        self.model = model

    def generate_structured(self, request: StructuredRequest) -> StructuredResult:
        openai = self._openai
        started = time.monotonic()
        params: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": request.user_content},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": request.task,
                    "strict": True,
                    "schema": request.json_schema,
                },
            },
            "max_completion_tokens": request.max_output_tokens,
            # Do not retain prompts for provider-side features such as evals/distillation.
            "store": False,
        }
        if request.safety_identifier:
            params["safety_identifier"] = request.safety_identifier

        try:
            completion = self._client.chat.completions.create(**params)
        except openai.APITimeoutError as exc:
            raise AIProviderTimeout("OpenAI request timed out") from exc
        except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
            raise AIProviderUnavailable("OpenAI rejected the configured credentials") from exc
        except openai.RateLimitError as exc:
            raise AIProviderUnavailable("OpenAI rate limit or quota reached") from exc
        except openai.APIConnectionError as exc:
            raise AIProviderUnavailable("Could not reach OpenAI") from exc
        except openai.APIError as exc:
            raise AIProviderError(f"OpenAI API error ({type(exc).__name__})") from exc

        latency_ms = int((time.monotonic() - started) * 1000)
        if not completion.choices:
            raise AIProviderInvalidOutput("OpenAI returned no choices")
        choice = completion.choices[0]
        message = choice.message
        if getattr(message, "refusal", None):
            raise AIProviderRefusal("Model refused the request")
        if choice.finish_reason == "length":
            raise AIProviderInvalidOutput("Model output was truncated")
        if choice.finish_reason == "content_filter":
            raise AIProviderRefusal("Output blocked by provider content filter")
        content = message.content
        if not content:
            raise AIProviderInvalidOutput("Model returned empty content")
        try:
            data = json.loads(content)
        except (TypeError, ValueError) as exc:
            raise AIProviderInvalidOutput("Model output was not valid JSON") from exc
        if not isinstance(data, dict):
            raise AIProviderInvalidOutput("Model output was not a JSON object")
        return StructuredResult(
            data=data,
            provider=self.name,
            model=getattr(completion, "model", None) or self.model,
            latency_ms=latency_ms,
        )
