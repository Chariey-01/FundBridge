"""SMS notifications to beneficiaries when authoritative financial state changes.

Hooks SQLAlchemy session events so the core payment/payout code does not need to
call messaging directly:
- after_flush: detect Donation rows that became ``completed`` and Payout rows whose
  status changed, and render the messages while SQL is still allowed;
- after_commit: hand the rendered messages to the SMS gateway;
- after_rollback: discard them.

A message is therefore only sent for state that was actually committed. Nothing
here writes financial data.
"""

from __future__ import annotations

import logging

from flask import current_app, has_app_context
from sqlalchemy import event, inspect

from app.extensions import db

log = logging.getLogger("fundbridge.notifications")

_PENDING_KEY = "fundbridge_pending_sms"
_registered = False


def register_notification_hooks() -> None:
    global _registered
    if _registered:
        return
    event.listen(db.session, "after_flush", _after_flush)
    event.listen(db.session, "after_commit", _after_commit)
    event.listen(db.session, "after_soft_rollback", _after_rollback)
    _registered = True


def _messaging():
    if not has_app_context():
        return None
    ext = current_app.extensions.get("fundbridge.messaging")
    if not ext or not ext.get("notifications_enabled"):
        return None
    return ext["service"]


def _status_change(obj) -> tuple[str | None, str | None] | None:
    history = inspect(obj).attrs.status.history
    if not history.added:
        return None
    new = getattr(history.added[0], "value", history.added[0])
    old = getattr(history.deleted[0], "value", history.deleted[0]) if history.deleted else None
    return (old, new) if old != new else None


def _after_flush(session, flush_context) -> None:
    service = _messaging()
    if service is None:
        return
    from app.models.core import BeneficiaryProfile, Campaign, Donation, Payout

    from .core_adapters import raised_total
    from app.services.messaging.service import fmt_money

    pending = session.info.setdefault(_PENDING_KEY, [])
    try:
        with session.no_autoflush:
            for obj in list(session.new) + list(session.dirty):
                if isinstance(obj, Donation):
                    change = _status_change(obj)
                    if not change or change[1] != "completed":
                        continue
                    campaign = session.get(Campaign, obj.campaign_id)
                    beneficiary = session.get(BeneficiaryProfile, campaign.beneficiary_id) if campaign else None
                    if not beneficiary:
                        continue
                    pending.append(_render(service, beneficiary, "notify_donation", title=campaign.title[:40],
                                           amount=f"{obj.currency} {obj.amount}",
                                           raised=fmt_money(raised_total(campaign.id, campaign.goal_currency))))
                elif isinstance(obj, Payout):
                    change = _status_change(obj)
                    if not change:
                        continue
                    beneficiary = session.get(BeneficiaryProfile, obj.beneficiary_id)
                    if not beneficiary:
                        continue
                    pending.append(_render(service, beneficiary, "notify_payout", amount=f"{obj.currency} {obj.amount}",
                                           status=change[1], essential=True))
    except Exception:  # notifications must never break a financial transaction
        log.exception("Could not prepare notification")
    session.info[_PENDING_KEY] = [p for p in pending if p]


def _render(service, beneficiary, template: str, essential: bool = False, **params):
    from app.services.messaging.i18n import payout_status_label, phone_language, t
    from app.services.messaging.phone import normalize_msisdn

    msisdn = normalize_msisdn(beneficiary.phone_number, service.settings.default_country)
    if msisdn is None:
        return None
    pref = service.store.get_preference(msisdn) if hasattr(service.store, "get_preference") else None
    if pref and pref.opted_out and not essential:
        return None
    lang = phone_language((pref.language if pref else None) or beneficiary.preferred_language)
    if template == "notify_payout":
        params["status"] = payout_status_label(lang, params["status"])
    params.setdefault("ussd", service.settings.ussd_code)
    return (msisdn, t(lang, template, **params))


def _after_commit(session) -> None:
    pending = session.info.pop(_PENDING_KEY, [])
    service = _messaging()
    if service is None:
        return
    for msisdn, text in pending:
        try:
            service.gateway.send(msisdn, text)
        except Exception:
            log.exception("SMS notification failed")


def _after_rollback(session, previous_transaction) -> None:
    session.info.pop(_PENDING_KEY, None)
