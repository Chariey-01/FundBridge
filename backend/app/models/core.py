import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db


def utcnow(): return datetime.now(timezone.utc)
def uuid_str(): return str(uuid.uuid4())


class Role(str, enum.Enum):
    donor = "donor"; creator = "creator"; beneficiary = "beneficiary"; agent = "agent"; reviewer = "reviewer"; admin = "admin"
class CampaignStatus(str, enum.Enum): draft = "draft"; submitted = "submitted"; published = "published"; closed = "closed"
class DonationStatus(str, enum.Enum): created = "created"; pending = "pending"; completed = "completed"; failed = "failed"; cancelled = "cancelled"; refunded = "refunded"; partially_refunded = "partially_refunded"
class PayoutStatus(str, enum.Enum): requested = "requested"; under_review = "under_review"; rejected = "rejected"; approved_for_submission = "approved_for_submission"; submitted = "submitted"; pending_confirmation = "pending_confirmation"; failed = "failed"; succeeded = "succeeded"


class Timestamped:
    created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = db.Column(db.DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class User(Timestamped, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uuid_str)
    email = db.Column(db.String(255), unique=True, nullable=True)
    phone_number = db.Column(db.String(32), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=True)
    role = db.Column(db.Enum(Role), nullable=False, default=Role.donor)
    status = db.Column(db.String(24), nullable=False, default="active")
    def set_password(self, value): self.password_hash = generate_password_hash(value)
    def check_password(self, value): return bool(self.password_hash and check_password_hash(self.password_hash, value))


class BeneficiaryProfile(Timestamped, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uuid_str)
    user_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=True, index=True)
    display_name = db.Column(db.String(160), nullable=False)
    phone_number = db.Column(db.String(32), nullable=False)
    preferred_language = db.Column(db.String(16), nullable=False, default="en")
    country_code = db.Column(db.String(2), nullable=False)
    verification_status = db.Column(db.String(32), nullable=False, default="unverified")
    payout_destination_reference = db.Column(db.String(512), nullable=True)  # provider-tokenized/protected only


class Campaign(Timestamped, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uuid_str)
    creator_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=False, index=True)
    beneficiary_id = db.Column(db.String(36), db.ForeignKey("beneficiary_profile.id"), nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False); slug = db.Column(db.String(180), unique=True, nullable=False)
    description = db.Column(db.Text, nullable=False); category = db.Column(db.String(80), nullable=False)
    goal_amount = db.Column(db.Numeric(18, 2), nullable=False); goal_currency = db.Column(db.String(3), nullable=False)
    status = db.Column(db.Enum(CampaignStatus), nullable=False, default=CampaignStatus.draft)
    review_status = db.Column(db.String(32), nullable=False, default="not_submitted")
    published_at = db.Column(db.DateTime(timezone=True), nullable=True)


class Donation(Timestamped, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uuid_str)
    campaign_id = db.Column(db.String(36), db.ForeignKey("campaign.id"), nullable=False, index=True)
    donor_id = db.Column(db.String(36), db.ForeignKey("user.id"), nullable=True, index=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False); currency = db.Column(db.String(3), nullable=False)
    provider = db.Column(db.String(40), nullable=False); provider_order_id = db.Column(db.String(255), unique=True, nullable=True)
    provider_capture_id = db.Column(db.String(255), unique=True, nullable=True)
    status = db.Column(db.Enum(DonationStatus), nullable=False, default=DonationStatus.created)
    idempotency_key = db.Column(db.String(255), nullable=False, unique=True)


class Payout(Timestamped, db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uuid_str)
    beneficiary_id = db.Column(db.String(36), db.ForeignKey("beneficiary_profile.id"), nullable=False, index=True)
    campaign_id = db.Column(db.String(36), db.ForeignKey("campaign.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(18, 2), nullable=False); currency = db.Column(db.String(3), nullable=False)
    destination_type = db.Column(db.String(32), nullable=False); destination_reference = db.Column(db.String(512), nullable=False)
    provider = db.Column(db.String(40), nullable=False); provider_reference = db.Column(db.String(255), unique=True, nullable=True)
    status = db.Column(db.Enum(PayoutStatus), nullable=False, default=PayoutStatus.requested)
    idempotency_key = db.Column(db.String(255), nullable=False, unique=True)
    submitted_at = db.Column(db.DateTime(timezone=True)); confirmed_at = db.Column(db.DateTime(timezone=True)); failure_reason_code = db.Column(db.String(80))


class FinancialLedgerEntry(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uuid_str)
    campaign_id = db.Column(db.String(36), db.ForeignKey("campaign.id"), nullable=False, index=True)
    donation_id = db.Column(db.String(36), db.ForeignKey("donation.id"), nullable=True, unique=True)
    payout_id = db.Column(db.String(36), db.ForeignKey("payout.id"), nullable=True, index=True)
    entry_type = db.Column(db.String(40), nullable=False)
    amount = db.Column(db.Numeric(18, 2), nullable=False); currency = db.Column(db.String(3), nullable=False)
    reference = db.Column(db.String(255), nullable=False, unique=True); created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)


class AuditLog(db.Model):
    id = db.Column(db.String(36), primary_key=True, default=uuid_str); actor_id = db.Column(db.String(36), nullable=True)
    action = db.Column(db.String(100), nullable=False); resource_type = db.Column(db.String(60), nullable=False); resource_id = db.Column(db.String(36), nullable=False)
    metadata_json = db.Column(db.JSON, nullable=False, default=dict); created_at = db.Column(db.DateTime(timezone=True), default=utcnow, nullable=False)
