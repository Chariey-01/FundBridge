"""Adapters from the core backend (Codex's models, JWT auth, ledger) to the AI/messaging ports.

Read-only with respect to financial data: these adapters query campaigns,
beneficiaries, payouts and ledger entries but never write them.
"""

from __future__ import annotations

import logging
import secrets
from decimal import Decimal
from typing import Sequence

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.core import (
    BeneficiaryProfile,
    Campaign,
    CampaignStatus,
    FinancialLedgerEntry,
    Payout,
    ProviderWebhookEvent,
    User,
)
from app.models.messaging import MessagingPinCredential, MessagingPreference, SupportRequest
from app.services.ai.ports import Actor, Money, PublicCampaignSummary, SearchFilters
from app.services.messaging.phone import phone_variants
from app.services.messaging.ports import (
    BeneficiaryRecord,
    CampaignStatusView,
    PayoutStatusView,
    PinRecord,
    Preference,
)

log = logging.getLogger("fundbridge.integrations")

GATEWAY_EVENT_PROVIDER = "africastalking"

# Ledger entry types that count towards "raised". Refund/reversal types are subtracted
# once the core ledger defines them (see docs/integration/ai-messaging.md, open items).
_RAISED_CREDIT = ("donation_completed",)
_RAISED_DEBIT = ("donation_refunded", "donation_reversed", "chargeback")


def _value(enum_or_str) -> str:
    return getattr(enum_or_str, "value", enum_or_str)


def _money(amount, currency: str) -> Money:
    return Money(str(Decimal(str(amount)).quantize(Decimal("0.01"))), currency)


def raised_total(campaign_id: str, currency: str) -> Money:
    """Confirmed donations for a campaign, from immutable ledger entries only."""
    rows = (
        db.session.query(FinancialLedgerEntry.entry_type, func.coalesce(func.sum(FinancialLedgerEntry.amount), 0))
        .filter(FinancialLedgerEntry.campaign_id == campaign_id, FinancialLedgerEntry.currency == currency)
        .filter(FinancialLedgerEntry.entry_type.in_(_RAISED_CREDIT + _RAISED_DEBIT))
        .group_by(FinancialLedgerEntry.entry_type)
        .all()
    )
    total = Decimal("0")
    for entry_type, amount in rows:
        total += Decimal(str(amount)) * (1 if entry_type in _RAISED_CREDIT else -1)
    return _money(total, currency)


def jwt_actor_resolver() -> Actor | None:
    """Current authenticated user as an Actor, or None (missing, invalid or expired token)."""
    from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

    try:
        verify_jwt_in_request(optional=True)
        identity = get_jwt_identity()
    except Exception:  # invalid/expired tokens are treated as anonymous; protected routes then return 401
        return None
    if not identity:
        return None
    user = db.session.get(User, identity)
    if user is None or user.status != "active":
        return None
    return Actor(user.id, _value(user.role))


def jwt_auth_failure() -> tuple[str, str, int]:
    """Classify why a request has no usable caller, using the same codes as the core JWT loaders."""
    from flask_jwt_extended import verify_jwt_in_request
    from flask_jwt_extended.exceptions import NoAuthorizationError
    from jwt import ExpiredSignatureError

    try:
        verify_jwt_in_request()
    except NoAuthorizationError:
        return "AUTH_REQUIRED", "Authentication is required.", 401
    except ExpiredSignatureError:
        return "TOKEN_EXPIRED", "Authentication has expired.", 401
    except Exception:  # malformed, wrong signature, wrong token type, bad header
        return "INVALID_TOKEN", "Authentication is invalid.", 401
    # A valid token whose user no longer exists or is not active (core: PermissionError ACCOUNT_INACTIVE).
    return "ACCOUNT_INACTIVE", "You are not authorized to perform this action.", 403


class SqlCampaignCatalog:
    def search(self, filters: SearchFilters, limit: int) -> Sequence[PublicCampaignSummary]:
        query = Campaign.query.filter(Campaign.status == CampaignStatus.published)
        if filters.category:
            query = query.filter(Campaign.category == filters.category)
        if filters.country_code:
            query = query.join(BeneficiaryProfile, Campaign.beneficiary_id == BeneficiaryProfile.id).filter(
                BeneficiaryProfile.country_code == filters.country_code
            )
        if filters.keywords:
            clauses = []
            for keyword in filters.keywords:
                pattern = f"%{keyword.replace('%', '').replace('_', '')}%"
                clauses += [Campaign.title.ilike(pattern), Campaign.description.ilike(pattern),
                            Campaign.category.ilike(pattern)]
            query = query.filter(or_(*clauses))
        campaigns = query.order_by(Campaign.published_at.desc().nullslast(), Campaign.created_at.desc()).limit(
            max(limit * 3, limit)
        ).all()

        def score(c: Campaign) -> int:
            text = f"{c.title} {c.description} {c.category}".lower()
            return sum(1 for kw in filters.keywords if kw.lower() in text)

        campaigns.sort(key=score, reverse=True)
        results = []
        for c in campaigns[:limit]:
            beneficiary = db.session.get(BeneficiaryProfile, c.beneficiary_id)
            results.append(
                PublicCampaignSummary(
                    id=c.id,
                    slug=c.slug,
                    title=c.title,
                    summary=(c.description or "")[:200],
                    category=c.category,
                    country_code=beneficiary.country_code if beneficiary else None,
                    goal=_money(c.goal_amount, c.goal_currency),
                    raised=raised_total(c.id, c.goal_currency),
                )
            )
        return results


class SqlBeneficiaryDirectory:
    def __init__(self, default_country: str = "KE") -> None:
        self.default_country = default_country

    def find_by_phone(self, msisdn: str) -> BeneficiaryRecord | None:
        matches = BeneficiaryProfile.query.filter(
            BeneficiaryProfile.phone_number.in_(phone_variants(msisdn, self.default_country))
        ).limit(2).all()
        if len(matches) != 1:
            if matches:
                log.warning("Phone number matches several beneficiary profiles; refusing to choose one.")
            return None
        b = matches[0]
        return BeneficiaryRecord(b.id, b.display_name, msisdn, b.preferred_language or "en",
                                 b.verification_status)

    def campaigns_for(self, beneficiary_id: str) -> Sequence[CampaignStatusView]:
        campaigns = (
            Campaign.query.filter_by(beneficiary_id=beneficiary_id).order_by(Campaign.created_at.desc()).limit(5).all()
        )
        return [
            CampaignStatusView(c.id, c.slug, c.title, _value(c.status), _money(c.goal_amount, c.goal_currency),
                               raised_total(c.id, c.goal_currency))
            for c in campaigns
        ]

    def latest_payout(self, beneficiary_id: str) -> PayoutStatusView | None:
        p = Payout.query.filter_by(beneficiary_id=beneficiary_id).order_by(Payout.created_at.desc()).first()
        if p is None:
            return None
        return PayoutStatusView(p.id, _money(p.amount, p.currency), _value(p.status), p.updated_at or p.created_at)


class SqlMessagingStore:
    def get_pin(self, beneficiary_id: str) -> PinRecord | None:
        # Row lock (PostgreSQL) so concurrent wrong PINs cannot lose failed-attempt updates and get extra guesses.
        row = (db.session.query(MessagingPinCredential).filter_by(beneficiary_id=beneficiary_id)
               .with_for_update().one_or_none())
        return PinRecord(row.pin_hash, row.failed_attempts, row.locked_until) if row else None

    def save_pin(self, beneficiary_id: str, record: PinRecord) -> None:
        row = db.session.get(MessagingPinCredential, beneficiary_id)
        if row is None:
            row = MessagingPinCredential(beneficiary_id=beneficiary_id, pin_hash=record.pin_hash)
            db.session.add(row)
        row.pin_hash = record.pin_hash
        row.failed_attempts = record.failed_attempts
        row.locked_until = record.locked_until
        db.session.commit()

    def delete_pin(self, beneficiary_id: str) -> None:
        row = db.session.get(MessagingPinCredential, beneficiary_id)
        if row is not None:
            db.session.delete(row)
            db.session.commit()

    def first_delivery(self, channel: str, key: str) -> bool:
        """Uses the core provider-event dedup table (unique provider + event_id); no payload is stored."""
        db.session.add(ProviderWebhookEvent(provider=GATEWAY_EVENT_PROVIDER, event_id=f"{channel}:{key}"[:255],
                                            event_type=f"{channel}.inbound"))
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            return False
        return True

    def get_preference(self, msisdn: str) -> Preference:
        row = db.session.get(MessagingPreference, msisdn)
        return Preference(row.language, row.opted_out) if row else Preference()

    def save_preference(self, msisdn: str, preference: Preference) -> None:
        row = db.session.get(MessagingPreference, msisdn)
        if row is None:
            row = MessagingPreference(phone_number=msisdn)
            db.session.add(row)
        row.language = preference.language
        row.opted_out = preference.opted_out
        db.session.commit()

    def open_support_request(self, *, msisdn, beneficiary_id, channel, topic, priority) -> str:
        # A repeated dial or a gateway retry within 30 minutes returns the open request instead of a duplicate.
        recent = (SupportRequest.query.filter_by(phone_number=msisdn, topic=topic, channel=channel, status="open")
                  .filter(SupportRequest.created_at >= datetime.now(timezone.utc) - timedelta(minutes=30))
                  .order_by(SupportRequest.created_at.desc()).first())
        if recent is not None:
            return recent.reference
        reference = "HLP-" + secrets.token_hex(3).upper()
        db.session.add(
            SupportRequest(reference=reference, phone_number=msisdn, beneficiary_id=beneficiary_id,
                           channel=channel, topic=topic, priority=priority)
        )
        db.session.commit()
        return reference
