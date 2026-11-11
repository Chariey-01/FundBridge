import uuid
from datetime import datetime, timezone
from decimal import Decimal
from werkzeug.security import check_password_hash, generate_password_hash
from .extensions import db


def uid(): return str(uuid.uuid4())
def utcnow(): return datetime.now(timezone.utc)


class User(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    email = db.Column(db.String(254), unique=True, nullable=True, index=True)
    phone_number = db.Column(db.String(32), unique=True, nullable=True, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(32), nullable=False, default="donor")
    status = db.Column(db.String(32), nullable=False, default="active")
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    def set_password(self, value): self.password_hash = generate_password_hash(value)
    def verify_password(self, value): return check_password_hash(self.password_hash, value)


class BeneficiaryProfile(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    user_id = db.Column(db.String(36), db.ForeignKey("user.id"), unique=True)
    display_name = db.Column(db.String(160), nullable=False)
    phone_number = db.Column(db.String(32))
    preferred_language = db.Column(db.String(16), nullable=False, default="en")
    country_code = db.Column(db.String(2), nullable=False)
    verification_status = db.Column(db.String(32), nullable=False, default="unverified")
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Campaign(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    creator_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=False, index=True)
    beneficiary_id = db.Column(db.String(36), db.ForeignKey("beneficiary_profile.id"), nullable=False)
    title = db.Column(db.String(160), nullable=False)
    slug = db.Column(db.String(180), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=False)
    category = db.Column(db.String(80), nullable=False)
    goal_amount = db.Column(db.Numeric(18, 2), nullable=False)
    goal_currency = db.Column(db.String(3), nullable=False)
    status = db.Column(db.String(32), nullable=False, default="draft")
    review_status = db.Column(db.String(32), nullable=False, default="not_submitted")
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    published_at = db.Column(db.DateTime(timezone=True))


class Donation(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    campaign_id = db.Column(db.String(36), db.ForeignKey("campaign.id"), nullable=False, index=True)
    donor_id = db.Column(db.String(36), db.ForeignKey("user.id"), index=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    provider = db.Column(db.String(40), nullable=False)
    provider_order_id = db.Column(db.String(128), unique=True)
    provider_capture_id = db.Column(db.String(128), unique=True)
    status = db.Column(db.String(32), nullable=False, default="created")
    idempotency_key = db.Column(db.String(128), unique=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Payout(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    beneficiary_id = db.Column(db.String(36), db.ForeignKey("beneficiary_profile.id"), nullable=False)
    campaign_id = db.Column(db.String(36), db.ForeignKey("campaign.id"), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    destination_type = db.Column(db.String(32), nullable=False)
    destination_reference = db.Column(db.String(255), nullable=False)  # protected: never serialized
    provider = db.Column(db.String(40), nullable=False, default="simulator")
    provider_reference = db.Column(db.String(128), unique=True)
    status = db.Column(db.String(40), nullable=False, default="requested")
    idempotency_key = db.Column(db.String(128), unique=True, nullable=False)
    requested_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    submitted_at = db.Column(db.DateTime(timezone=True))
    confirmed_at = db.Column(db.DateTime(timezone=True))
    failure_reason_code = db.Column(db.String(80))


class FinancialLedgerEntry(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    campaign_id = db.Column(db.String(36), db.ForeignKey("campaign.id"), nullable=False, index=True)
    donation_id = db.Column(db.String(36), db.ForeignKey("donation.id"), unique=True)
    payout_id = db.Column(db.String(36), db.ForeignKey("payout.id"), unique=True)
    entry_type = db.Column(db.String(40), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False)
    currency = db.Column(db.String(3), nullable=False)
    reference = db.Column(db.String(160), unique=True, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class AuditLog(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uid)
    actor_id = db.Column(db.String(36), db.ForeignKey("user.id"))
    action = db.Column(db.String(100), nullable=False)
    resource_type = db.Column(db.String(80), nullable=False)
    resource_id = db.Column(db.String(36), nullable=False)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict)
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


def audit(actor_id, action, resource_type, resource_id, metadata=None):
    db.session.add(AuditLog(actor_id=actor_id, action=action, resource_type=resource_type,
                            resource_id=resource_id, metadata_json=metadata or {}))
