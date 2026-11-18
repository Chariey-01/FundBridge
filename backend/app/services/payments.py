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


def reverse_donation(donation, *, event_id, event_type, order_id, capture_id, amount):
    """Record a PayPal refund/reversal as an immutable debit before acknowledging it.

    FinancialLedgerEntry.donation_id remains unique for the original capture credit, so
    reversal entries are linked by their unique provider-event reference and campaign.
    The provider webhook event itself supplies the durable de-duplication boundary.
    """
    if donation.status not in (DonationStatus.completed, DonationStatus.partially_refunded):
        raise ValueError("INVALID_DONATION_TRANSITION")
    if order_id != donation.provider_order_id or capture_id != donation.provider_capture_id:
        raise ValueError("PAYMENT_CAPTURE_MISMATCH")
    if amount <= 0:
        raise ValueError("PAYMENT_AMOUNT_MISMATCH")

    prior = db.session.query(FinancialLedgerEntry).filter(
        FinancialLedgerEntry.campaign_id == donation.campaign_id,
        FinancialLedgerEntry.currency == donation.currency,
        FinancialLedgerEntry.reference.like(f"donation-reversal:{donation.id}:%"),
    ).all()
    already_reversed = sum((Decimal(str(entry.amount)) for entry in prior), Decimal("0"))
    if already_reversed + amount > Decimal(donation.amount):
        raise ValueError("PAYMENT_AMOUNT_MISMATCH")

    entry_type = "donation_refunded" if event_type == "PAYMENT.CAPTURE.REFUNDED" else "donation_reversed"
    db.session.add(FinancialLedgerEntry(
        campaign_id=donation.campaign_id,
        entry_type=entry_type,
        amount=amount,
        currency=donation.currency,
        reference=f"donation-reversal:{donation.id}:{event_id}",
    ))
    total_reversed = already_reversed + amount
    donation.status = DonationStatus.refunded if total_reversed == Decimal(donation.amount) else DonationStatus.partially_refunded
    db.session.add(AuditLog(
        action="donation.refunded" if entry_type == "donation_refunded" else "donation.reversed",
        resource_type="donation",
        resource_id=donation.id,
        metadata_json={"provider_event_id": event_id, "amount": str(amount), "currency": donation.currency},
    ))
    return donation
