"""Single entry point that wires AI, messaging and operational hardening into the core Flask app.

Called once from ``create_app``:

    from app.integrations.bootstrap import init_integrations
    init_integrations(app)
"""

from __future__ import annotations

from flask import Flask


def init_integrations(flask_app: Flask) -> None:
    import app.models.messaging  # noqa: F401  (registers messaging tables with SQLAlchemy metadata)
    from app.api.v1.ai import init_ai
    from app.api.v1.messaging import _flag, _setting, init_messaging

    from .core_adapters import (
        SqlBeneficiaryDirectory,
        SqlCampaignCatalog,
        SqlMessagingStore,
        SqlStatusReader,
        jwt_actor_resolver,
        jwt_auth_failure,
    )
    from .http_envelope import AUTH_FAILURE_EXTENSION
    from .notifications import register_notification_hooks

    hops = int(_setting(flask_app, "TRUSTED_PROXY_HOPS", 0) or 0)
    if hops > 0:
        # Behind a reverse proxy (Railway/Render/nginx): trust exactly this many X-Forwarded-* hops so
        # remote_addr is the real client for IP rate limits and the callback IP allowlist.
        from werkzeug.middleware.proxy_fix import ProxyFix

        flask_app.wsgi_app = ProxyFix(flask_app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)

    # AI/messaging 401s use the same codes as core (AUTH_REQUIRED / INVALID_TOKEN / TOKEN_EXPIRED).
    flask_app.extensions[AUTH_FAILURE_EXTENSION] = jwt_auth_failure

    catalog = SqlCampaignCatalog()
    ai_service = init_ai(flask_app, actor_resolver=jwt_actor_resolver, campaign_catalog=catalog,
                         status_reader=SqlStatusReader())
    init_messaging(
        flask_app,
        directory=SqlBeneficiaryDirectory(_setting(flask_app, "MESSAGING_DEFAULT_COUNTRY", "KE")),
        store=SqlMessagingStore(),
        catalog=catalog,
        actor_resolver=jwt_actor_resolver,
        ai_service=ai_service,
    )
    if _flag(flask_app, "MESSAGING_NOTIFICATIONS_ENABLED", True):
        register_notification_hooks()

    from app.api.v1.operations import init_operations

    from .admin_cli import register_admin_cli
    from .ai_cli import register_ai_cli
    from .messaging_cli import register_messaging_cli
    from .demo import register_demo_cli
    from .hardening import init_hardening

    init_hardening(flask_app)  # request IDs, access log, sign-in rate limits, JSON error envelopes
    init_operations(flask_app)  # roles, beneficiary verification, campaign balances
    register_demo_cli(flask_app)
    register_admin_cli(flask_app)
    register_ai_cli(flask_app)
    register_messaging_cli(flask_app)

    @flask_app.get("/api/v1/integrations/status")
    def integrations_status():
        from app.api.v1.messaging import integration_status
        from app.integrations.http_envelope import ok

        return ok({"ai": ai_service.status(), "messaging": integration_status()})
