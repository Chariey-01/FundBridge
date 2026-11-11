"""Operator commands for the SMS/USSD channel (Africa's Talking).

    flask --app run:app fundbridge-messaging check-config       # no network; exit 1 on blocking problems
    flask --app run:app fundbridge-messaging send-test --to +2547...   # one real SMS through the gateway
    flask --app run:app fundbridge-messaging prune-events --days 30    # retention for callback dedup records

None of them prints the API key or the callback token.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

import click
from flask import Flask, current_app
from flask.cli import AppGroup

messaging_cli = AppGroup("fundbridge-messaging", help="SMS/USSD gateway operations.")


def _setting(key: str, default=None):
    value = current_app.config.get(key)
    if value in (None, ""):
        value = os.environ.get(key)
    return default if value in (None, "") else value


def config_findings() -> tuple[list[str], list[str], dict[str, str]]:
    """Return (errors, warnings, facts) for the messaging configuration. Pure; no network."""
    errors: list[str] = []
    warnings: list[str] = []
    provider = str(_setting("SMS_PROVIDER", "simulator")).lower()
    username, api_key = _setting("AT_USERNAME"), _setting("AT_API_KEY")
    production = os.environ.get("FLASK_ENV") == "production"
    facts = {"SMS_PROVIDER": provider}

    if provider == "africastalking":
        if not (username and api_key):
            errors.append("SMS_PROVIDER=africastalking but AT_USERNAME/AT_API_KEY are missing; the simulator would be used.")
        facts["mode"] = "sandbox (Africa's Talking simulator only)" if username == "sandbox" else "live"
        if username and username != "sandbox" and not _setting("AT_SENDER_ID"):
            warnings.append("AT_SENDER_ID is empty: replies come from Africa's Talking's default sender. For two-way "
                            "SMS set it to your shortcode.")
    elif provider == "simulator":
        facts["mode"] = "simulated (nothing is sent to phones)"
        if production:
            warnings.append("Production is using the SMS simulator: no notification reaches a phone.")
    else:
        errors.append(f"SMS_PROVIDER must be 'simulator' or 'africastalking', not '{provider}'.")

    token = _setting("MESSAGING_CALLBACK_TOKEN")
    if not token:
        errors.append("MESSAGING_CALLBACK_TOKEN is empty: USSD/SMS callbacks return 503.")
    elif len(token) < 24:
        errors.append("MESSAGING_CALLBACK_TOKEN is shorter than 24 characters; generate a long random value.")

    base = str(_setting("PUBLIC_BASE_URL") or _setting("FRONTEND_ORIGIN") or "")
    parsed = urlparse(base)
    if not base:
        errors.append("PUBLIC_BASE_URL is empty: USSD/SMS messages would link to localhost.")
    else:
        if parsed.scheme != "https" and parsed.hostname not in ("localhost", "127.0.0.1"):
            errors.append("PUBLIC_BASE_URL must use https.")
        if len(base) > 40:
            warnings.append(f"PUBLIC_BASE_URL is {len(base)} characters; USSD screens hold 182, so search shows fewer "
                            "results. A short domain helps.")

    code = str(_setting("USSD_SERVICE_CODE", "*384*123#"))
    facts["USSD_SERVICE_CODE"] = code
    if not re.fullmatch(r"\*\d+(\*\d+)*#", code):
        errors.append(f"USSD_SERVICE_CODE '{code}' is not a USSD code like *384*123#.")
    if str(_setting("MESSAGING_SIMULATOR_ENABLED", "false")).lower() == "true" and production:
        errors.append("MESSAGING_SIMULATOR_ENABLED=true in production exposes an unauthenticated phone simulator.")
    if not _setting("MESSAGING_ALLOWED_IPS"):
        warnings.append("MESSAGING_ALLOWED_IPS is empty: callbacks are protected by the token only. Add Africa's "
                        "Talking's callback addresses once confirmed.")
    elif int(_setting("TRUSTED_PROXY_HOPS", 0) or 0) == 0:
        warnings.append("MESSAGING_ALLOWED_IPS is set but TRUSTED_PROXY_HOPS=0; behind a proxy every caller "
                        "appears as the proxy.")
    if not current_app.config.get("SECRET_KEY"):
        warnings.append("SECRET_KEY is empty: USSD retry detection only works within one process.")
    return errors, warnings, facts


@messaging_cli.command("check-config")
@click.option("--api-host", default=None, help="Public https URL of this backend, to print the callback URLs.")
def check_config(api_host: str | None) -> None:
    errors, warnings, facts = config_findings()
    for key, value in facts.items():
        click.echo(f"{key}: {value}")
    host = (api_host or "https://<backend-host>").rstrip("/")
    click.echo("Callback URLs to register with Africa's Talking (append the secret, never share it):")
    for label, path in (("USSD", "ussd"), ("Incoming SMS", "sms/inbound"), ("Delivery reports", "sms/delivery")):
        click.echo(f"  {label:<17} {host}/api/v1/messaging/{path}?token=<MESSAGING_CALLBACK_TOKEN>")
    for message in warnings:
        click.echo(f"WARNING: {message}")
    for message in errors:
        click.echo(f"ERROR: {message}")
    if errors:
        raise click.ClickException(f"{len(errors)} configuration error(s).")
    click.echo("Messaging configuration has no blocking errors (this does not contact Africa's Talking).")


@messaging_cli.command("send-test")
@click.option("--to", "to", required=True, help="Destination number, e.g. +254712345678.")
@click.option("--message", default="FundBridge test message. No action needed.")
def send_test(to: str, message: str) -> None:
    from app.api.v1.messaging import MESSAGING_EXTENSION
    from app.services.messaging.phone import mask_msisdn, normalize_msisdn

    service = current_app.extensions[MESSAGING_EXTENSION]["service"]
    msisdn = normalize_msisdn(to, service.settings.default_country)
    if msisdn is None:
        raise click.ClickException("Not a valid phone number.")
    gateway = service.gateway
    click.echo(f"Gateway: {gateway.name} ({gateway.mode}) -> {mask_msisdn(msisdn)}")
    result = gateway.send(msisdn, message)
    click.echo(f"Result: status={result.status} message_id={result.message_id or '-'} detail={result.detail or '-'}")
    if result.status == "simulated":
        click.echo("Simulated: nothing left the server.")
    elif result.status == "submitted":
        click.echo("Accepted by the gateway. This is not proof of delivery; check delivery reports.")
    else:
        raise click.ClickException("The gateway did not accept the message.")


@messaging_cli.command("prune-events")
@click.option("--days", default=30, show_default=True, type=click.IntRange(1, 3650))
def prune_events(days: int) -> None:
    from app.extensions import db
    from app.integrations.core_adapters import GATEWAY_EVENT_PROVIDER
    from app.models.core import ProviderWebhookEvent

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    deleted = (ProviderWebhookEvent.query.filter(ProviderWebhookEvent.provider == GATEWAY_EVENT_PROVIDER,
                                                 ProviderWebhookEvent.created_at < cutoff)
               .delete(synchronize_session=False))
    db.session.commit()
    click.echo(f"Deleted {deleted} gateway callback record(s) older than {days} days (PayPal events are kept).")


def register_messaging_cli(app: Flask) -> None:
    app.cli.add_command(messaging_cli)
