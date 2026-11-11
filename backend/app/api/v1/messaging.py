"""Feature-phone endpoints under /api/v1/messaging.

Gateway callbacks (Africa's Talking request format):
  POST /ussd           form: sessionId, serviceCode, phoneNumber, text  -> text/plain "CON ..." | "END ..."
  POST /sms/inbound    form: from, to, text, date, id, linkId           -> 200, replies sent via the gateway
Both require MESSAGING_CALLBACK_TOKEN (?token= or X-FundBridge-Callback-Token) and fail closed without it.

Simulator (only when MESSAGING_SIMULATOR_ENABLED=true; every response is labelled simulated):
  GET  /simulator                 phone simulator page
  POST /simulator/ussd            JSON {phone_number, text, session_id?}
  POST /simulator/sms             JSON {phone_number, text}
  GET  /simulator/outbox          ?phone_number=
"""

from __future__ import annotations

import os
import pathlib
from typing import Any

from flask import Blueprint, Flask, Response, current_app, request

from app.integrations.http_envelope import error, ok, unauthenticated
from app.integrations.messaging.callback_auth import ip_allowed, token_matches
from app.integrations.messaging.gateways import AfricasTalkingSmsGateway, SimulatedSmsGateway
from app.services.ai.ports import ActorResolver, CampaignCatalog
from app.services.ai.rate_limit import SlidingWindowRateLimiter
from app.services.ai.schemas import AssistantRequest
from app.services.messaging.phone import mask_msisdn, normalize_msisdn
from app.services.messaging.ports import BeneficiaryDirectory, MessagingStore
from app.services.messaging.service import MessagingService, MessagingSettings

bp = Blueprint("fundbridge_messaging", __name__)

MESSAGING_EXTENSION = "fundbridge.messaging"
_SIMULATOR_PAGE = pathlib.Path(__file__).resolve().parents[2] / "integrations" / "messaging" / "simulator.html"


def _setting(app: Flask, key: str, default: Any = None) -> Any:
    value = app.config.get(key)
    if value in (None, ""):
        value = os.environ.get(key)
    return default if value in (None, "") else value


def _flag(app: Flask, key: str, default: bool = False) -> bool:
    value = _setting(app, key)
    if value is None:
        return default
    return value is True or str(value).lower() in ("1", "true", "yes", "on")


def build_gateway(app: Flask):
    provider = str(_setting(app, "SMS_PROVIDER", "simulator")).lower()
    if provider == "africastalking":
        username, api_key = _setting(app, "AT_USERNAME"), _setting(app, "AT_API_KEY")
        if username and api_key:
            return AfricasTalkingSmsGateway(username=username, api_key=api_key,
                                            sender_id=_setting(app, "AT_SENDER_ID"))
        app.logger.warning("SMS_PROVIDER=africastalking but AT_USERNAME/AT_API_KEY are missing; using simulator.")
    elif provider != "simulator":
        raise ValueError("SMS_PROVIDER must be 'simulator' or 'africastalking'")
    return SimulatedSmsGateway()


def init_messaging(
    app: Flask,
    *,
    directory: BeneficiaryDirectory,
    store: MessagingStore,
    catalog: CampaignCatalog,
    actor_resolver: ActorResolver,
    ai_service=None,
    gateway=None,
    url_prefix: str = "/api/v1/messaging",
) -> MessagingService:
    settings = MessagingSettings(
        public_base_url=_setting(app, "PUBLIC_BASE_URL") or _setting(app, "FRONTEND_ORIGIN") or "http://localhost:3000",
        ussd_code=_setting(app, "USSD_SERVICE_CODE", "*384*123#"),
        default_country=_setting(app, "MESSAGING_DEFAULT_COUNTRY", "KE"),
    )

    assistant = None
    if ai_service is not None and _flag(app, "MESSAGING_SMS_ASSISTANT_ENABLED", True):
        from app.services.ai.service import RateLimitedError

        def assistant(msisdn: str, text: str, lang: str) -> str | None:
            try:
                ai_service.check_rate(f"sms:{msisdn}", public=True)
                result = ai_service.beneficiary_assistant(
                    f"sms:{msisdn}", AssistantRequest(message=text[:1000], language=lang), channel="sms"
                )
            except (RateLimitedError, ValueError):
                return None
            return result["data"]["reply"]

    service = MessagingService(
        directory=directory,
        store=store,
        catalog=catalog,
        gateway=gateway or build_gateway(app),
        settings=settings,
        assistant=assistant,
    )
    app.extensions[MESSAGING_EXTENSION] = {
        "service": service,
        "actor_resolver": actor_resolver,
        "callback_token": _setting(app, "MESSAGING_CALLBACK_TOKEN"),
        "allowed_ips": _setting(app, "MESSAGING_ALLOWED_IPS"),
        "simulator_enabled": _flag(app, "MESSAGING_SIMULATOR_ENABLED", False),
        "notifications_enabled": _flag(app, "MESSAGING_NOTIFICATIONS_ENABLED", True),
        "simulator_limiter": SlidingWindowRateLimiter(int(_setting(app, "MESSAGING_SIMULATOR_RATE_LIMIT", 60))),
        "ai_live": bool(ai_service and ai_service.provider is not None),
    }
    app.register_blueprint(bp, url_prefix=url_prefix)
    return service


def _ext() -> dict:
    return current_app.extensions[MESSAGING_EXTENSION]


def _service() -> MessagingService:
    return _ext()["service"]


def integration_status(app: Flask | None = None) -> dict:
    ext = (app or current_app).extensions[MESSAGING_EXTENSION]
    gateway = ext["service"].gateway
    return {
        "sms": {
            "provider": gateway.name,
            "mode": gateway.mode,
            # Delivery reports are not consumed yet, so delivery to handsets is never confirmed here.
            "delivery_confirmed": False,
        },
        "ussd": {
            "service_code": ext["service"].settings.ussd_code,
            "callback_configured": bool(ext["callback_token"]),
            "live_shortcode_verified": False,
        },
        "simulator_enabled": ext["simulator_enabled"],
        "notifications_enabled": ext["notifications_enabled"],
        "sms_assistant": "ai" if ext["ai_live"] else "rule_based",
    }


# ------------------------------------------------------------------ callbacks


def _callback_denied() -> Response | None:
    ext = _ext()
    if not ext["callback_token"]:
        return error("MESSAGING_NOT_CONFIGURED", "Messaging callbacks are not configured.", 503)
    supplied = request.headers.get("X-FundBridge-Callback-Token") or request.args.get("token")
    if not token_matches(ext["callback_token"], supplied) or not ip_allowed(request.remote_addr, ext["allowed_ips"]):
        current_app.logger.warning("Rejected messaging callback from %s", request.remote_addr)
        return error("INVALID_CALLBACK", "The callback could not be authenticated.", 403)
    return None


def _plain(text: str) -> Response:
    return Response(text, status=200, mimetype="text/plain")


@bp.post("/ussd")
def ussd_callback():
    denied = _callback_denied()
    if denied is not None:
        return denied
    form = request.form
    if not form.get("phoneNumber"):
        return _plain("END Invalid request.")
    reply = _service().handle_ussd(
        phone_number=form.get("phoneNumber", ""), text=form.get("text", ""), session_id=form.get("sessionId")
    )
    return _plain(reply.render())


@bp.post("/sms/inbound")
def sms_inbound():
    denied = _callback_denied()
    if denied is not None:
        return denied
    form = request.form
    sender = form.get("from")
    if not sender:
        return error("VALIDATION_ERROR", "Missing sender.", 400, {"from": ["Required."]})
    _service().handle_inbound_sms(phone_number=sender, text=form.get("text", ""))
    return _plain("")


@bp.get("/status")
def messaging_status():
    return ok(integration_status())


# ------------------------------------------------------------- staff actions


def _require_roles(*roles: str):
    actor = _ext()["actor_resolver"]()
    if actor is None:
        return None, unauthenticated()
    if actor.role not in roles:
        return None, error("FORBIDDEN", "You are not authorized to perform this action.", 403)
    return actor, None


@bp.get("/support-requests")
def list_support_requests():
    # Agents see every request until agent-to-beneficiary assignments exist in the core model.
    actor, err = _require_roles("agent", "admin")
    if err:
        return err
    from app.models.messaging import SupportRequest

    rows = SupportRequest.query.order_by(SupportRequest.created_at.desc()).limit(100).all()
    return ok([
        {"id": r.id, "reference": r.reference, "phone_number": r.phone_number, "beneficiary_id": r.beneficiary_id,
         "channel": r.channel, "topic": r.topic, "priority": r.priority, "status": r.status,
         "created_at": r.created_at.isoformat()}
        for r in rows
    ])


@bp.post("/beneficiaries/<beneficiary_id>/pin-reset")
def reset_pin(beneficiary_id: str):
    # Admin only: without agent assignments an agent could reset any beneficiary's PIN.
    actor, err = _require_roles("admin")
    if err:
        return err
    from app.extensions import db
    from app.models.core import AuditLog, BeneficiaryProfile

    if db.session.get(BeneficiaryProfile, beneficiary_id) is None:
        return error("NOT_FOUND", "Beneficiary not found.", 404)
    _service().pins.reset(beneficiary_id)
    db.session.add(AuditLog(actor_id=actor.id, action="messaging.pin_reset", resource_type="beneficiary",
                            resource_id=beneficiary_id))
    db.session.commit()
    return ok({"beneficiary_id": beneficiary_id, "pin": "reset"})


# ------------------------------------------------------------------ simulator


def _simulator_denied() -> Response | None:
    ext = _ext()
    if not ext["simulator_enabled"]:
        return error("NOT_FOUND", "Not found.", 404)
    decision = ext["simulator_limiter"].hit(f"ip:{request.remote_addr}")
    if not decision.allowed:
        return error("RATE_LIMITED", "Too many requests.", 429, {"retry_after_seconds": decision.retry_after_seconds},
                     headers={"Retry-After": str(decision.retry_after_seconds)})
    return None


_SIM_META = {"simulated": True, "notice": "Simulated phone session. No real SMS or USSD traffic is involved."}


def _json_phone() -> tuple[dict, str | None, Response | None]:
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}, None, error("VALIDATION_ERROR", "Send a JSON object.", 400)
    msisdn = normalize_msisdn(body.get("phone_number"), _service().settings.default_country)
    if msisdn is None:
        return body, None, error("VALIDATION_ERROR", "Enter a valid phone number.", 400,
                                 {"phone_number": ["Use international format, e.g. +254712345678."]})
    text = body.get("text", "")
    if not isinstance(text, str) or len(text) > 480:
        return body, None, error("VALIDATION_ERROR", "Text is too long.", 400, {"text": ["At most 480 characters."]})
    return body, msisdn, None


@bp.get("/simulator")
def simulator_page():
    denied = _simulator_denied()
    if denied is not None:
        return denied
    return Response(_SIMULATOR_PAGE.read_text(encoding="utf-8"), mimetype="text/html")


@bp.post("/simulator/ussd")
def simulator_ussd():
    denied = _simulator_denied()
    if denied is not None:
        return denied
    body, msisdn, err = _json_phone()
    if err:
        return err
    reply = _service().handle_ussd(phone_number=msisdn, text=body.get("text", ""), session_id=body.get("session_id"))
    return ok({"response": reply.render(), "text": reply.text, "session_ended": reply.end}, _SIM_META)


@bp.post("/simulator/sms")
def simulator_sms():
    denied = _simulator_denied()
    if denied is not None:
        return denied
    body, msisdn, err = _json_phone()
    if err:
        return err
    replies = _service().handle_inbound_sms(phone_number=msisdn, text=body.get("text", ""))
    return ok({"replies": replies, "to": mask_msisdn(msisdn)}, _SIM_META)


@bp.get("/simulator/outbox")
def simulator_outbox():
    denied = _simulator_denied()
    if denied is not None:
        return denied
    gateway = _service().gateway
    if not isinstance(gateway, SimulatedSmsGateway):
        return ok([], {**_SIM_META, "notice": "SMS is using a real provider; there is no simulated outbox."})
    msisdn = normalize_msisdn(request.args.get("phone_number"), _service().settings.default_country)
    return ok(gateway.messages_for(msisdn), _SIM_META)
