from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models.core import AuditLog, DonationStatus, FinancialLedgerEntry


def mark_donation_completed(donation, *, order_id, capture, actor_id=None):
    """Validate authoritative provider data before a ledger credit is committed."""
    if order_id != donation.provider_order_id:
        raise ValueError("PAYMENT_ORDER_MISMATCH")
    if capture.get("status") != "COMPLETED" or not capture.get("id"):
        raise ValueError("PAYMENT_NOT_CONFIRMED")
    amount = capture.get("amount") or {}
    if amount.get("currency_code") != donation.currency:
        raise ValueError("PAYMENT_CURRENCY_MISMATCH")
    try:
        captured_amount = Decimal(str(amount.get("value")))
    except (InvalidOperation, ValueError):
        raise ValueError("PAYMENT_AMOUNT_MISMATCH")
    if captured_amount != Decimal(donation.amount):
        raise ValueError("PAYMENT_AMOUNT_MISMATCH")
    capture_id = capture["id"]
    if donation.status == DonationStatus.completed:
        if donation.provider_capture_id != capture_id:
            raise ValueError("PAYMENT_CAPTURE_MISMATCH")
        return donation
    prior = donation.__class__.query.filter_by(provider_capture_id=capture_id).first()
    if prior and prior.id != donation.id:
        raise ValueError("PAYMENT_CAPTURE_ALREADY_USED")
    if donation.status not in (DonationStatus.created, DonationStatus.pending):
        raise ValueError("INVALID_DONATION_TRANSITION")
    donation.status = DonationStatus.completed
    donation.provider_capture_id = capture_id
    db.session.add(FinancialLedgerEntry(campaign_id=donation.campaign_id, donation_id=donation.id,
        entry_type="donation_completed", amount=donation.amount, currency=donation.currency,
        reference=f"donation-capture:{capture_id}"))
    db.session.add(AuditLog(actor_id=actor_id, action="donation.completed", resource_type="donation", resource_id=donation.id))
    return donation
