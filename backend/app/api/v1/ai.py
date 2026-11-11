"""AI endpoints under /api/v1/ai.

Wire into the application factory with ``init_ai(app, actor_resolver=..., campaign_catalog=...)``.
"""

from __future__ import annotations

import os
from typing import Any, Callable

from flask import Blueprint, Flask, current_app, request
from pydantic import BaseModel, ValidationError

from app.integrations.ai.factory import build_ai_provider
from app.integrations.http_envelope import error, ok, validation_details
from app.services.ai.ports import Actor, ActorResolver, CampaignCatalog
from app.services.ai.schemas import (
    AssistantRequest,
    CampaignDraftRequest,
    CampaignSearchRequest,
    TranslateRequest,
)
from app.services.ai.service import AIConfig, AIService, AIUnavailableError, InteractionRecorder, RateLimitedError

bp = Blueprint("fundbridge_ai", __name__)

AI_EXTENSION = "fundbridge.ai"
ACTOR_EXTENSION = "fundbridge.actor_resolver"
MAX_BODY_BYTES = 16 * 1024
_UNSET: Any = object()


def init_ai(
    app: Flask,
    *,
    actor_resolver: ActorResolver,
    campaign_catalog: CampaignCatalog,
    provider: Any = _UNSET,
    interaction_recorder: InteractionRecorder | None = None,
    url_prefix: str = "/api/v1/ai",
) -> AIService:
    if provider is _UNSET:
        provider = build_ai_provider(app.config)

    def setting(key: str, default: int) -> int:
        return int(app.config.get(key) or os.environ.get(key) or default)

    service = AIService(
        provider,
        campaign_catalog=campaign_catalog,
        config=AIConfig(
            user_rate_limit_per_minute=setting("AI_RATE_LIMIT_PER_MINUTE", 10),
            public_rate_limit_per_minute=setting("AI_PUBLIC_RATE_LIMIT_PER_MINUTE", 20),
            safety_id_salt=app.config.get("SECRET_KEY") or None,
        ),
        interaction_recorder=interaction_recorder,
    )
    app.extensions[AI_EXTENSION] = service
    app.extensions[ACTOR_EXTENSION] = actor_resolver
    app.register_blueprint(bp, url_prefix=url_prefix)
    return service


def _service() -> AIService:
    return current_app.extensions[AI_EXTENSION]


def _actor() -> Actor | None:
    resolver: Callable[[], Actor | None] = current_app.extensions[ACTOR_EXTENSION]
    return resolver()


def _client_key() -> str:
    # Behind a reverse proxy the app factory must apply ProxyFix so remote_addr is the client.
    return f"ip:{request.remote_addr or 'unknown'}"


def _parse(model: type[BaseModel]):
    if request.content_length and request.content_length > MAX_BODY_BYTES:
        return None, error("PAYLOAD_TOO_LARGE", "The request body is too large.", 413)
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return None, error("VALIDATION_ERROR", "Send a JSON object.", 400, {"body": ["Expected a JSON object."]})
    try:
        return model.model_validate(body), None
    except ValidationError as exc:
        return None, error("VALIDATION_ERROR", "The supplied information is invalid.", 400, validation_details(exc))


def _run(fn: Callable[[], dict], rate_key: str, *, public: bool):
    try:
        _service().check_rate(rate_key, public=public)
        result = fn()
    except RateLimitedError as exc:
        return error(
            "RATE_LIMITED",
            "Too many requests. Please wait and try again.",
            429,
            {"retry_after_seconds": exc.retry_after},
            headers={"Retry-After": str(exc.retry_after)},
        )
    except AIUnavailableError as exc:
        return error("AI_UNAVAILABLE", str(exc), 503)
    return ok(result["data"], result["meta"])


def _require_actor():
    actor = _actor()
    if actor is None:
        return None, error("AUTHENTICATION_REQUIRED", "Sign in to use this feature.", 401)
    return actor, None


@bp.get("/status")
def ai_status():
    return ok(_service().status())


@bp.post("/campaign-draft")
def campaign_draft():
    actor, err = _require_actor()
    if err:
        return err
    req, err = _parse(CampaignDraftRequest)
    if err:
        return err
    return _run(lambda: _service().campaign_draft(actor, req), f"user:{actor.id}", public=False)


@bp.post("/translate")
def translate():
    # Public so guest donors can translate campaign stories; anonymous callers get the stricter IP limit.
    actor = _actor()
    req, err = _parse(TranslateRequest)
    if err:
        return err
    key, public = (f"user:{actor.id}", False) if actor else (_client_key(), True)
    return _run(lambda: _service().translate(actor.id if actor else key, req), key, public=public)


@bp.post("/beneficiary-assistant")
def beneficiary_assistant():
    actor, err = _require_actor()
    if err:
        return err
    req, err = _parse(AssistantRequest)
    if err:
        return err
    return _run(lambda: _service().beneficiary_assistant(actor.id, req), f"user:{actor.id}", public=False)


@bp.post("/campaign-search")
def campaign_search():
    actor = _actor()
    req, err = _parse(CampaignSearchRequest)
    if err:
        return err
    key, public = (f"user:{actor.id}", False) if actor else (_client_key(), True)
    return _run(lambda: _service().campaign_search(actor.id if actor else key, req), key, public=public)
