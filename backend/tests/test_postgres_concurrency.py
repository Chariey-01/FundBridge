"""Run only with POSTGRES_TEST_DATABASE_URL; SQLite cannot verify row-lock semantics."""
import os
import threading
from decimal import Decimal

import pytest

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="POSTGRES_TEST_DATABASE_URL is required for PostgreSQL locking test")

from app import create_app
from app.extensions import db
from app.models.core import Campaign, CampaignStatus, FinancialLedgerEntry, Payout, PayoutStatus
from app.services.ledger import reserve_payout

def test_two_simultaneous_reservations_cannot_overcommit():
    app=create_app({"TESTING":True,"SQLALCHEMY_DATABASE_URI":POSTGRES_URL,"SECRET_KEY":"test-secret","JWT_SECRET_KEY":"test-jwt-secret-with-at-least-thirty-two-bytes"})
    with app.app_context():
        db.drop_all(); db.create_all()
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="Concurrency campaign",slug="postgres-concurrency",description="x"*20,category="health",goal_amount=Decimal("20"),goal_currency="USD",status=CampaignStatus.published)
        db.session.add(c); db.session.flush(); db.session.add(FinancialLedgerEntry(campaign_id=c.id,entry_type="donation_completed",amount=Decimal("10"),currency="USD",reference="seed-credit")); db.session.commit(); campaign_id=c.id
    results=[]; barrier=threading.Barrier(2)
    def reserve(key):
        with app.app_context():
            try:
                barrier.wait(); c=db.session.query(Campaign).filter_by(id=campaign_id).with_for_update().one()
                p=Payout(campaign_id=c.id,beneficiary_id="beneficiary",amount=Decimal("7"),currency="USD",destination_type="wallet",destination_reference="token",provider="simulator",idempotency_key=key,status=PayoutStatus.requested)
                db.session.add(p); db.session.flush(); reserve_payout(p); db.session.commit(); results.append("reserved")
            except ValueError: db.session.rollback(); results.append("rejected")
            finally: db.session.remove()
    threads=[threading.Thread(target=reserve,args=(f"concurrent-{i}",)) for i in range(2)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert sorted(results) == ["rejected","reserved"]
