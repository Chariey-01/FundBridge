"""AI provider abstraction.

Business code talks to an ``AIProvider``; it never imports a vendor SDK.
A provider only turns a prompt into a JSON object. It has no access to the
database, payment providers, payout providers or any other tool, so a model
output can never move money, approve anything or change a payout destination.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class AIProviderError(Exception):
    """A provider call failed. Callers fall back; the message is safe to log."""

    code = "AI_PROVIDER_ERROR"


class AIProviderTimeout(AIProviderError):
    code = "AI_PROVIDER_TIMEOUT"


class AIProviderUnavailable(AIProviderError):
    """Not configured, rate limited upstream, or credentials rejected."""

    code = "AI_PROVIDER_UNAVAILABLE"


class AIProviderRefusal(AIProviderError):
    code = "AI_PROVIDER_REFUSAL"


class AIProviderInvalidOutput(AIProviderError):
    code = "AI_INVALID_OUTPUT"


@dataclass(frozen=True)
class StructuredRequest:
    """One structured-output call.

    ``json_schema`` must be a strict JSON schema: every property listed in
    ``required`` and ``additionalProperties`` false at every object level.
    """

    task: str
    system_prompt: str
    user_content: str
    json_schema: dict[str, Any]
    max_output_tokens: int = 1000
    # Hashed, non-reversible actor identifier for provider abuse monitoring.
    safety_identifier: str | None = None


@dataclass(frozen=True)
class StructuredResult:
    data: dict[str, Any]
    provider: str
    model: str | None
    latency_ms: int


@runtime_checkable
class AIProvider(Protocol):
    name: str
    model: str | None
    # True only when calls reach a real external model.
    live: bool

    def generate_structured(self, request: StructuredRequest) -> StructuredResult:
        ...
