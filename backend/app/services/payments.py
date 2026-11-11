from app.extensions import db
from app.models.core import AuditLog, DonationStatus, FinancialLedgerEntry


def mark_donation_completed(donation, capture_id, actor_id=None):
    if donation.status == DonationStatus.completed:
        return donation
    if donation.status not in (DonationStatus.created, DonationStatus.pending):
        raise ValueError("INVALID_DONATION_TRANSITION")
    donation.status = DonationStatus.completed
    donation.provider_capture_id = capture_id
    db.session.add(FinancialLedgerEntry(campaign_id=donation.campaign_id, donation_id=donation.id,
        entry_type="donation_completed", amount=donation.amount, currency=donation.currency,
        reference=f"donation-capture:{capture_id}"))
    db.session.add(AuditLog(actor_id=actor_id, action="donation.completed", resource_type="donation", resource_id=donation.id))
    return donation
