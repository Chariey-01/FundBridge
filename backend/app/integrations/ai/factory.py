"""Build the configured AI provider from settings. Returns None when AI is disabled."""

from __future__ import annotations

import logging
import os
from typing import Any, Mapping

from .base import AIProvider

log = logging.getLogger("fundbridge.ai")

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"


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

    return OpenAIProvider(
        api_key=api_key,
        model=_setting(config, "OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        timeout_seconds=float(_setting(config, "AI_TIMEOUT_SECONDS", 15)),
        max_retries=int(_setting(config, "AI_MAX_RETRIES", 1)),
        base_url=_setting(config, "OPENAI_BASE_URL"),
    )
