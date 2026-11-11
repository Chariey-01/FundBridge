"""Build the configured AI provider from settings. Returns None when AI is disabled."""

from __future__ import annotations

import logging
import os
from typing import Any, Mapping

from .base import AIProvider

log = logging.getLogger("fundbridge.ai")

# Model decision (2026-11-11, see docs/integration/openai.md). gpt-4o-mini is reported for API removal on
# 2027-01-14 and gpt-5-mini on 2026-12-11; gpt-5.4-mini is the reported successor. None of this has been
# verified with an API call from this repository: run `flask fundbridge-ai check` with the real key.
DEFAULT_OPENAI_MODEL = "gpt-5.4-mini"
# "low" is accepted by every reasoning model; "minimal"/"none" are not accepted by all of them.
DEFAULT_REASONING_EFFORT = "low"
REASONING_TOKEN_ALLOWANCE = 1024
_OMIT = ("omit", "off", "unset")


def reasoning_effort_for(model: str, configured: str | None) -> str | None:
    """Explicit setting wins ("omit" sends nothing); otherwise only reasoning-family models get a default."""
    if configured:
        return None if configured.strip().lower() in _OMIT else configured.strip().lower()
    non_reasoning = model.lower().startswith(("gpt-4", "gpt-3", "chatgpt-4"))
    return None if non_reasoning else DEFAULT_REASONING_EFFORT


def _setting(config: Mapping[str, Any], key: str, default: Any = None) -> Any:
    value = config.get(key)
    if value in (None, ""):
        value = os.environ.get(key)
    return default if value in (None, "") else value


def build_ai_provider(config: Mapping[str, Any]) -> AIProvider | None:
    mode = str(_setting(config, "AI_PROVIDER", "auto")).lower()
    api_key = _setting(config, "OPENAI_API_KEY")
    if mode in ("disabled", "none", "off", "fallback"):
        return None
    if mode not in ("auto", "openai"):
        raise ValueError(f"Unsupported AI_PROVIDER '{mode}'. Use 'openai', 'auto' or 'disabled'.")
    if not api_key:
        if mode == "openai":
            log.warning("AI_PROVIDER=openai but OPENAI_API_KEY is empty; AI features run in fallback mode.")
        return None
    from .openai_provider import OpenAIProvider

    model = str(_setting(config, "OPENAI_MODEL", DEFAULT_OPENAI_MODEL)).strip()
    return OpenAIProvider(
        api_key=api_key,
        model=model,
        timeout_seconds=float(_setting(config, "AI_TIMEOUT_SECONDS", 15)),
        max_retries=int(_setting(config, "AI_MAX_RETRIES", 1)),
        base_url=_setting(config, "OPENAI_BASE_URL"),
        reasoning_effort=reasoning_effort_for(model, _setting(config, "OPENAI_REASONING_EFFORT")),
        reasoning_token_allowance=int(_setting(config, "OPENAI_REASONING_TOKEN_ALLOWANCE", REASONING_TOKEN_ALLOWANCE)),
    )
