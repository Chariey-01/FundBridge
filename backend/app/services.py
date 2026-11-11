from decimal import Decimal
from sqlalchemy import func
from .extensions import db
from .errors import error
from .models import FinancialLedgerEntry, Donation, Payout, audit


def money(value):
    try: amount = Decimal(str(value)).quantize(Decimal("0.01"))
    except Exception: error("VALIDATION_ERROR", "The supplied information is invalid.", 400, {"amount": ["A decimal amount is required."]})
    if amount <= 0: error("VALIDATION_ERROR", "The supplied information is invalid.", 400, {"amount": ["Amount must be greater than zero."]})
    return amount


def available_funds(campaign_id, currency):
    rows = db.session.query(FinancialLedgerEntry.entry_type, func.coalesce(func.sum(FinancialLedgerEntry.amount), 0)).filter_by(
        campaign_id=campaign_id, currency=currency).group_by(FinancialLedgerEntry.entry_type).all()
    totals = {kind: Decimal(str(amount)) for kind, amount in rows}
    return totals.get("donation_completed", Decimal("0")) - totals.get("payout_reserved", Decimal("0")) - totals.get("payout_succeeded", Decimal("0")) + totals.get("payout_reservation_released", Decimal("0"))


def complete_donation(donation, capture_id, actor_id=None):
    if donation.status == "completed": return donation
    if donation.status not in {"created", "pending"}: error("INVALID_STATE", "Donation cannot be completed from its current state.", 409)
    donation.status, donation.provider_capture_id = "completed", capture_id
    db.session.add(FinancialLedgerEntry(campaign_id=donation.campaign_id, donation_id=donation.id,
        entry_type="donation_completed", amount=donation.amount, currency=donation.currency,
        reference="donation:" + donation.id))
    audit(actor_id, "donation.completed", "donation", donation.id)
    return donation


def reserve_payout(payout, actor_id):
    if available_funds(payout.campaign_id, payout.currency) < payout.amount:
        error("INSUFFICIENT_FUNDS", "Available funds are insufficient.", 409)
    payout.status = "under_review"
    db.session.add(FinancialLedgerEntry(campaign_id=payout.campaign_id, payout_id=payout.id,
        entry_type="payout_reserved", amount=payout.amount, currency=payout.currency, reference="payout-reserve:" + payout.id))
    audit(actor_id, "payout.reserved", "payout", payout.id)
