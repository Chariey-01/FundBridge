"""`flask --app run:app fundbridge-ai check`: verify the configured OpenAI key, model and parameters.

Makes real, small requests through the same service path the API uses (structured output, output
validation, guardrails): one natural-language search and one translation. It prints the model, the
latency and the outcome, never the key. Exit code 0 only when both calls were answered by the model
itself (not by a fallback). Costs a few hundred tokens.
"""

from __future__ import annotations

import time

import click
from flask import Flask, current_app
from flask.cli import AppGroup

ai_cli = AppGroup("fundbridge-ai", help="AI provider operations.")


@ai_cli.command("check")
def check() -> None:
    from app.api.v1.ai import AI_EXTENSION
    from app.services.ai.schemas import CampaignSearchRequest, TranslateRequest
    from app.services.ai.service import AIUnavailableError

    service = current_app.extensions[AI_EXTENSION]
    provider = service.provider
    if provider is None:
        raise click.ClickException(
            "No AI provider is configured (AI_PROVIDER is disabled or OPENAI_API_KEY is empty). "
            "AI features run on deterministic fallbacks.")
    click.echo(f"Provider: {provider.name}  model: {provider.model}  "
               f"reasoning_effort: {getattr(provider, 'reasoning_effort', None) or 'not sent'}")

    failures = 0
    started = time.monotonic()
    search = service.campaign_search("ops-check", CampaignSearchRequest(query="school fees for a girl in Kisumu"))
    meta = search["meta"]
    if meta.get("ai_generated"):
        click.echo(f"  search     OK   model={meta.get('model')} filters={search['data']['interpreted_filters']} "
                   f"({int((time.monotonic() - started) * 1000)} ms)")
    else:
        failures += 1
        click.echo(f"  search     FAIL fallback used: {meta.get('fallback_reason')}")

    started = time.monotonic()
    try:
        out = service.translate("ops-check", TranslateRequest(text="Thank you for your donation.", target_language="sw"))
        click.echo(f"  translate  OK   \"{out['data']['translated_text'][:60]}\" "
                   f"({int((time.monotonic() - started) * 1000)} ms)")
    except AIUnavailableError:
        failures += 1
        error = service.status().get("last_error") or {}
        click.echo(f"  translate  FAIL {error.get('code', 'unavailable')}")

    if failures:
        raise click.ClickException(
            "The provider did not answer. Check OPENAI_API_KEY, that OPENAI_MODEL is available to the account, and "
            "OPENAI_REASONING_EFFORT (set it to 'omit' for non-reasoning models). Application logs name the error.")
    click.echo("OpenAI verified: the configured key and model answered with valid structured output.")


def register_ai_cli(app: Flask) -> None:
    app.cli.add_command(ai_cli)
