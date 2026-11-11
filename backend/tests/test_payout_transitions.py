from decimal import Decimal
from app.extensions import db
from app.models.core import FinancialLedgerEntry, Payout, PayoutStatus
from app.services.payouts import apply_provider_status

def payout():
    return Payout(campaign_id="campaign",beneficiary_id="beneficiary",amount=Decimal("5"),currency="USD",destination_type="wallet",destination_reference="token",provider="simulator",idempotency_key="transition",status=PayoutStatus.submitted)

def test_failure_releases_only_once_and_timeout_does_not_release(app):
    with app.app_context():
        p=payout(); db.session.add(p); db.session.flush(); db.session.add(FinancialLedgerEntry(campaign_id=p.campaign_id,payout_id=p.id,entry_type="payout_reserved",amount=p.amount,currency=p.currency,reference=f"payout-reservation:{p.id}")); db.session.commit()
        apply_provider_status(p,"PENDING"); assert p.status == PayoutStatus.pending_confirmation
        apply_provider_status(p,"FAILED",failure_reason="timeout_reconciled"); db.session.commit()
        assert FinancialLedgerEntry.query.filter_by(payout_id=p.id,entry_type="payout_released").count() == 1
        apply_provider_status(p,"FAILED"); db.session.commit()
        assert FinancialLedgerEntry.query.filter_by(payout_id=p.id,entry_type="payout_released").count() == 1

def test_success_cannot_be_retried_or_released(app):
    with app.app_context():
        p=payout(); p.idempotency_key="success"; db.session.add(p); db.session.flush(); apply_provider_status(p,"SUCCEEDED"); db.session.commit()
        assert p.status == PayoutStatus.succeeded
        try: apply_provider_status(p,"FAILED")
        except ValueError as error: assert str(error) == "INVALID_PAYOUT_TRANSITION"
        else: raise AssertionError("successful payout was released")
