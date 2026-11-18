"""Concurrent payout requests must not reserve more than the available funds.

Needs a real database server, because the core backend relies on ``SELECT ... FOR UPDATE``:
    POSTGRES_TEST_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5432/fundbridge_test pytest tests/integration
Skipped when the variable is not set. Set FUNDBRIDGE_TEST_SQLITE_RACE=1 to run the same
scenario against a SQLite file and observe whether SQLite serialises reservations.
"""

from __future__ import annotations

import os
import threading
from decimal import Decimal

import pytest

from app import create_app
from app.extensions import db
from app.models.core import BeneficiaryProfile, Campaign, CampaignStatus, FinancialLedgerEntry, Payout, PayoutStatus, Role
from app.services.ledger import available_funds

from .conftest import BASE_CONFIG, PASSWORD
from .test_financial_security import fund

PG_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL") or os.environ.get("FUNDBRIDGE_TEST_DATABASE_URL")
WORKERS = 8


def _run_race(database_url: str) -> tuple[list[int], Decimal, int]:
    app = create_app({**BASE_CONFIG, "SQLALCHEMY_DATABASE_URI": database_url})
    with app.app_context():
        db.drop_all()
        db.create_all()
        from .conftest import make_user
        from app.models.core import BeneficiaryProfile, Campaign, CampaignStatus, Role

        creator = make_user("creator@example.test", Role.creator)
        user = make_user("beneficiary@example.test", Role.beneficiary)
        beneficiary = BeneficiaryProfile(user_id=user.id, display_name="Amina", phone_number="0712345678",
                                         country_code="KE", verification_status="verified",
                                         payout_destination_reference="tok")
        db.session.add(beneficiary)
        db.session.flush()
        campaign = Campaign(creator_id=creator.id, beneficiary_id=beneficiary.id, title="Race campaign",
                            slug="race-campaign", description="x" * 30, category="education",
                            goal_amount=Decimal("500"), goal_currency="USD", status=CampaignStatus.published)
        db.session.add(campaign)
        db.session.commit()
        fund(campaign, "100.00", "race-fund")
        campaign_id, beneficiary_id = campaign.id, beneficiary.id

    login = app.test_client().post("/api/v1/auth/login",
                                   json={"email": "beneficiary@example.test", "password": PASSWORD})
    token = login.get_json()["data"]["access_token"]
    barrier = threading.Barrier(WORKERS)
    statuses: list[int] = []
    lock = threading.Lock()

    def worker(index: int) -> None:
        client = app.test_client()
        barrier.wait()
        res = client.post(
            "/api/v1/payouts",
            json={"campaign_id": campaign_id, "beneficiary_id": beneficiary_id, "amount": "60.00", "currency": "USD"},
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": f"race-{index}"},
        )
        with lock:
            statuses.append(res.status_code)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(WORKERS)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(30)

    with app.app_context():
        remaining = available_funds(campaign_id, "USD")
        count = Payout.query.count()
        db.session.remove()
        db.drop_all()
    return statuses, remaining, count


@pytest.mark.skipif(not PG_URL, reason="set POSTGRES_TEST_DATABASE_URL to an isolated PostgreSQL test database")
def test_concurrent_payouts_cannot_overspend_postgres():
    statuses, remaining, count = _run_race(PG_URL)
    assert statuses.count(201) == 1, statuses
    assert count == 1
    assert remaining == Decimal("40.00")


@pytest.mark.skipif(not os.environ.get("FUNDBRIDGE_TEST_SQLITE_RACE"), reason="diagnostic only")
def test_concurrent_payouts_sqlite_diagnostic(tmp_path):
    statuses, remaining, count = _run_race(f"sqlite:///{tmp_path / 'race.db'}")
    print(f"sqlite race: statuses={sorted(statuses)} payouts={count} remaining={remaining}")
    assert remaining >= 0, f"OVERSPEND on SQLite: {count} payouts, remaining {remaining}"


def _run_review_race(database_url: str) -> tuple[list[int], PayoutStatus, int, Decimal]:
    """Race an approval against a rejection and return the durable financial state."""
    app = create_app({**BASE_CONFIG, "SQLALCHEMY_DATABASE_URI": database_url})
    with app.app_context():
        db.drop_all(); db.create_all()
        from .conftest import make_user

        creator = make_user("review-creator@example.test", Role.creator)
        beneficiary_user = make_user("review-beneficiary@example.test", Role.beneficiary)
        reviewer = make_user("review-reviewer@example.test", Role.reviewer)
        admin = make_user("review-admin@example.test", Role.admin)
        beneficiary = BeneficiaryProfile(user_id=beneficiary_user.id, display_name="Review Amina", phone_number="0712345670",
                                         country_code="KE", verification_status="verified", payout_destination_reference="tok")
        db.session.add(beneficiary); db.session.flush()
        campaign = Campaign(creator_id=creator.id, beneficiary_id=beneficiary.id, title="Review race campaign",
                            slug="review-race-campaign", description="x" * 30, category="education",
                            goal_amount=Decimal("100"), goal_currency="USD", status=CampaignStatus.published)
        db.session.add(campaign); db.session.flush()
        db.session.add(FinancialLedgerEntry(campaign_id=campaign.id, entry_type="donation_completed", amount=Decimal("100"),
                                            currency="USD", reference="review-race-credit"))
        db.session.commit()
        campaign_id, beneficiary_id = campaign.id, beneficiary.id

    def login(email: str) -> str:
        response = app.test_client().post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert response.status_code == 200
        return response.get_json()["data"]["access_token"]

    beneficiary_token = login("review-beneficiary@example.test")
    reviewer_token, admin_token = login("review-reviewer@example.test"), login("review-admin@example.test")
    created = app.test_client().post("/api/v1/payouts", headers={"Authorization": f"Bearer {beneficiary_token}", "Idempotency-Key": "review-race"},
                                     json={"campaign_id": campaign_id, "beneficiary_id": beneficiary_id, "amount": "100.00", "currency": "USD"})
    assert created.status_code == 201, created.get_json()
    payout_id = created.get_json()["data"]["id"]
    barrier, lock, statuses = threading.Barrier(2), threading.Lock(), []

    def worker(decision: str, token: str) -> None:
        client = app.test_client(); barrier.wait()
        response = client.post(f"/api/v1/payouts/{payout_id}/review", json={"decision": decision},
                               headers={"Authorization": f"Bearer {token}"})
        with lock: statuses.append(response.status_code)

    workers = [threading.Thread(target=worker, args=("approve", reviewer_token)),
               threading.Thread(target=worker, args=("reject", admin_token))]
    for worker_thread in workers: worker_thread.start()
    for worker_thread in workers: worker_thread.join(30)

    with app.app_context():
        payout = db.session.get(Payout, payout_id)
        released = FinancialLedgerEntry.query.filter_by(payout_id=payout_id, entry_type="payout_released").count()
        available = available_funds(campaign_id, "USD")
        status = payout.status
        db.session.remove(); db.drop_all()
    return statuses, status, released, available


@pytest.mark.skipif(not PG_URL, reason="set POSTGRES_TEST_DATABASE_URL to an isolated PostgreSQL test database")
def test_concurrent_payout_approval_and_rejection_are_atomic_postgres():
    statuses, status, released, available = _run_review_race(PG_URL)
    assert sorted(statuses) == [200, 400], statuses
    assert status in (PayoutStatus.approved_for_submission, PayoutStatus.rejected)
    if status == PayoutStatus.rejected:
        assert released == 1 and available == Decimal("100.00")
    else:
        assert released == 0 and available == Decimal("0.00")
