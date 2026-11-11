"""Tables owned by the messaging module (PINs, phone preferences, support requests)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.extensions import db


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MessagingPinCredential(db.Model):
    __tablename__ = "messaging_pin_credential"

    beneficiary_id = db.Column(db.String(36), db.ForeignKey("beneficiary_profile.id"), primary_key=True)
    pin_hash = db.Column(db.String(255), nullable=False)
    failed_attempts = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime(timezone=True), nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class MessagingPreference(db.Model):
    __tablename__ = "messaging_preference"

    phone_number = db.Column(db.String(20), primary_key=True)  # E.164
    language = db.Column(db.String(8), nullable=True)
    opted_out = db.Column(db.Boolean, nullable=False, default=False)
    updated_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)


class SupportRequest(db.Model):
    __tablename__ = "support_request"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    reference = db.Column(db.String(16), nullable=False, unique=True)
    phone_number = db.Column(db.String(20), nullable=False, index=True)
    beneficiary_id = db.Column(db.String(36), db.ForeignKey("beneficiary_profile.id"), nullable=True, index=True)
    channel = db.Column(db.String(8), nullable=False)  # ussd | sms | web
    topic = db.Column(db.String(24), nullable=False)  # callback | problem | sim_change
    priority = db.Column(db.String(8), nullable=False, default="normal")
    status = db.Column(db.String(16), nullable=False, default="open")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_utcnow)
