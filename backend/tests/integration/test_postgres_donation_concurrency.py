"""PostgreSQL-only regressions for concurrent donation order/reconciliation requests."""
import os
import threading
from decimal import Decimal
from unittest.mock import patch

import pytest

from app import create_app
from app.extensions import db
from app.models.core import Campaign, CampaignStatus, Donation, DonationStatus, FinancialLedgerEntry, Payout, PayoutStatus, Role, User
from app.services.ledger import available_funds, reserve_payout
from app.services.payments import mark_donation_completed

from .conftest import BASE_CONFIG, PASSWORD

PG_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL")
WORKERS = 8
pytestmark = pytest.mark.skipif(not PG_URL, reason="POSTGRES_TEST_DATABASE_URL is required")


def _app_with_donor():
    app = create_app({**BASE_CONFIG, "SQLALCHEMY_DATABASE_URI": PG_URL, "PAYPAL_CLIENT_ID": "test-client"})
    with app.app_context():
        db.drop_all(); db.create_all()
        donor = User(email="donor-race@example.test", role=Role.donor); donor.set_password(PASSWORD)
        campaign = Campaign(creator_id="creator", beneficiary_id="beneficiary", title="Donation race", slug="donation-race", description="x" * 30, category="education", goal_amount=Decimal("100"), goal_currency="USD", status=CampaignStatus.published)
        db.session.add_all([donor, campaign]); db.session.commit()
        login = app.test_client().post("/api/v1/auth/login", json={"email": donor.email, "password": PASSWORD})
        return app, campaign.id, donor.id, login.get_json()["data"]["access_token"]


def _parallel(work):
    barrier, results, lock = threading.Barrier(WORKERS), [], threading.Lock()
    def run(index):
        barrier.wait()
        result = work(index)
        with lock: results.append(result)
    threads = [threading.Thread(target=run, args=(index,)) for index in range(WORKERS)]
    [thread.start() for thread in threads]; [thread.join(30) for thread in threads]
    assert all(not thread.is_alive() for thread in threads)
    return results


def test_eight_reconciles_credit_once_without_server_errors():
    app, campaign_id, donor_id, token = _app_with_donor()
    with app.app_context():
        donation = Donation(campaign_id=campaign_id, donor_id=donor_id, amount=Decimal("5.00"), currency="USD", provider="paypal", provider_order_id="race-order", idempotency_key="race-reconcile", idempotency_fingerprint="x", status=DonationStatus.pending)
        db.session.add(donation); db.session.commit(); donation_id = donation.id
    order = {"status": "COMPLETED", "purchase_units": [{"reference_id": donation_id, "payments": {"captures": [{"id": "race-capture", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "5.00"}}]}}]}
    with patch("app.api.v1.routes.PayPalSandboxAdapter.get_order", return_value=order):
        statuses = _parallel(lambda _: app.test_client().post(f"/api/v1/donations/{donation_id}/reconcile", headers={"Authorization": f"Bearer {token}"}).status_code)
    with app.app_context():
        assert statuses == [200] * WORKERS
        assert Donation.query.get(donation_id).status == DonationStatus.completed
        assert FinancialLedgerEntry.query.filter_by(donation_id=donation_id).count() == 1
        db.session.remove(); db.drop_all()


def test_eight_identical_donation_orders_share_one_provider_order():
    app, campaign_id, _, token = _app_with_donor(); calls = []
    def create_order(donation, *_):
        calls.append(donation.id)
        return {"id": f"order-{donation.id}", "purchase_units": [{"reference_id": donation.id, "amount": {"currency_code": "USD", "value": "5.00"}}]}
    with patch("app.api.v1.routes.PayPalSandboxAdapter.create_order", side_effect=create_order):
        statuses = _parallel(lambda _: app.test_client().post("/api/v1/donations/orders", json={"campaign_id": campaign_id, "amount": "5.00", "currency": "USD"}, headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "same-race-key"}).status_code)
    with app.app_context():
        assert sorted(statuses) == [200] * (WORKERS - 1) + [201]
        assert len(calls) == 1
        assert Donation.query.filter_by(idempotency_key="same-race-key").count() == 1
        db.session.remove(); db.drop_all()


def test_conflicting_concurrent_donation_orders_return_clear_conflict():
    app, campaign_id, _, token = _app_with_donor(); barrier = threading.Barrier(2); results = []
    def create_order(donation, *_):
        return {"id": f"order-{donation.id}", "purchase_units": [{"reference_id": donation.id, "amount": {"currency_code": donation.currency, "value": str(donation.amount)}}]}
    def request(amount):
        barrier.wait()
        response = app.test_client().post("/api/v1/donations/orders", json={"campaign_id": campaign_id, "amount": amount, "currency": "USD"}, headers={"Authorization": f"Bearer {token}", "Idempotency-Key": "conflicting-race-key"})
        results.append((response.status_code, response.get_json()))
    with patch("app.api.v1.routes.PayPalSandboxAdapter.create_order", side_effect=create_order):
        threads = [threading.Thread(target=request, args=(amount,)) for amount in ("5.00", "6.00")]
        [thread.start() for thread in threads]; [thread.join(30) for thread in threads]
    with app.app_context():
        assert sorted(status for status, _ in results) == [201, 400]
        assert any(body.get("error", {}).get("code") == "IDEMPOTENCY_KEY_REUSED" for _, body in results)
        assert Donation.query.filter_by(idempotency_key="conflicting-race-key").count() == 1
        db.session.remove(); db.drop_all()


def test_donation_credit_and_payout_reservation_race_keeps_nonnegative_balance():
    """A payout either sees the credit and reserves it, or is safely rejected first."""
    app, campaign_id, donor_id, _ = _app_with_donor()
    with app.app_context():
        donation = Donation(campaign_id=campaign_id, donor_id=donor_id, amount=Decimal("10.00"), currency="USD", provider="paypal", provider_order_id="credit-race", idempotency_key="credit-race", idempotency_fingerprint="x", status=DonationStatus.pending)
        db.session.add(donation); db.session.commit(); donation_id = donation.id
    barrier, outcomes, lock = threading.Barrier(2), [], threading.Lock()
    def credit():
        with app.app_context():
            barrier.wait(); d = db.session.get(Donation, donation_id)
            mark_donation_completed(d, order_id="credit-race", capture={"id": "credit-race-capture", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "10.00"}})
            db.session.commit()
            with lock: outcomes.append("credited")
    def reserve():
        with app.app_context():
            barrier.wait(); db.session.query(Campaign).filter_by(id=campaign_id).with_for_update().one()
            payout = Payout(campaign_id=campaign_id, beneficiary_id="beneficiary", requested_by=donor_id, amount=Decimal("10.00"), currency="USD", destination_type="wallet", destination_reference="token", provider="simulator", idempotency_key="reserve-race", idempotency_fingerprint="x", status=PayoutStatus.requested)
            db.session.add(payout); db.session.flush()
            try:
                reserve_payout(payout); db.session.commit(); outcome = "reserved"
            except ValueError:
                db.session.rollback(); outcome = "rejected"
            with lock: outcomes.append(outcome)
    threads = [threading.Thread(target=credit), threading.Thread(target=reserve)]
    [thread.start() for thread in threads]; [thread.join(30) for thread in threads]
    with app.app_context():
        assert sorted(outcomes) in (["credited", "rejected"], ["credited", "reserved"])
        assert FinancialLedgerEntry.query.filter_by(donation_id=donation_id, entry_type="donation_completed").count() == 1
        assert available_funds(campaign_id, "USD") >= Decimal("0")
        db.session.remove(); db.drop_all()
