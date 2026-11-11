from decimal import Decimal
from sqlalchemy import func

from app.extensions import db
from app.models.core import FinancialLedgerEntry


def available_funds(campaign_id, currency):
    """Completed donations less reservations/payouts. All values stay Decimal."""
    rows = db.session.query(FinancialLedgerEntry.entry_type, func.coalesce(func.sum(FinancialLedgerEntry.amount), 0)).filter_by(campaign_id=campaign_id, currency=currency).group_by(FinancialLedgerEntry.entry_type).all()
    totals = {kind: Decimal(str(amount)) for kind, amount in rows}
    return totals.get("donation_completed", Decimal("0")) - totals.get("payout_reserved", Decimal("0")) + totals.get("payout_released", Decimal("0"))


def reserve_payout(payout):
    # Called in the payout-request transaction. PostgreSQL locks the campaign row first in caller.
    if available_funds(payout.campaign_id, payout.currency) < Decimal(payout.amount):
        raise ValueError("INSUFFICIENT_AVAILABLE_FUNDS")
    db.session.add(FinancialLedgerEntry(campaign_id=payout.campaign_id, payout_id=payout.id,
        entry_type="payout_reserved", amount=payout.amount, currency=payout.currency, reference=f"payout-reservation:{payout.id}"))


def release_payout(payout, reason):
    db.session.add(FinancialLedgerEntry(campaign_id=payout.campaign_id, payout_id=payout.id,
        entry_type="payout_released", amount=payout.amount, currency=payout.currency, reference=f"payout-release:{payout.id}:{reason}"))
