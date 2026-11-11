"""Run only with POSTGRES_TEST_DATABASE_URL; SQLite cannot verify row-lock semantics."""
import os
import threading
from decimal import Decimal

import pytest

POSTGRES_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="POSTGRES_TEST_DATABASE_URL is required for PostgreSQL locking test")

from app import create_app
from app.extensions import db
from app.models.core import BeneficiaryProfile, Campaign, CampaignStatus, FinancialLedgerEntry, Payout, PayoutStatus, Role, User
from app.services.ledger import reserve_payout

def test_two_simultaneous_reservations_cannot_overcommit():
    app=create_app({"TESTING":True,"SQLALCHEMY_DATABASE_URI":POSTGRES_URL,"SECRET_KEY":"test-secret","JWT_SECRET_KEY":"test-jwt-secret-with-at-least-thirty-two-bytes"})
    with app.app_context():
        db.drop_all(); db.create_all()
        creator=User(email="concurrency-creator@test",role=Role.creator); beneficiary_user=User(email="concurrency-beneficiary@test",role=Role.beneficiary); db.session.add_all([creator,beneficiary_user]); db.session.flush()
        beneficiary=BeneficiaryProfile(user_id=beneficiary_user.id,display_name="Concurrency beneficiary",phone_number="+254700000099",country_code="KE",verification_status="verified",payout_destination_reference="token"); db.session.add(beneficiary); db.session.flush()
        c=Campaign(creator_id=creator.id,beneficiary_id=beneficiary.id,title="Concurrency campaign",slug="postgres-concurrency",description="x"*20,category="health",goal_amount=Decimal("20"),goal_currency="USD",status=CampaignStatus.published)
        db.session.add(c); db.session.flush(); db.session.add(FinancialLedgerEntry(campaign_id=c.id,entry_type="donation_completed",amount=Decimal("100"),currency="USD",reference="seed-credit")); db.session.commit(); campaign_id=c.id; beneficiary_id=beneficiary.id
    results=[]; barrier=threading.Barrier(2)
    def reserve(key):
        with app.app_context():
            try:
                barrier.wait(); c=db.session.query(Campaign).filter_by(id=campaign_id).with_for_update().one()
                p=Payout(campaign_id=c.id,beneficiary_id=beneficiary_id,requested_by=beneficiary_user.id,amount=Decimal("60"),currency="USD",destination_type="wallet",destination_reference="token",provider="simulator",idempotency_key=key,idempotency_fingerprint=key,status=PayoutStatus.requested)
                db.session.add(p); db.session.flush(); reserve_payout(p); db.session.commit(); results.append("reserved")
            except ValueError: db.session.rollback(); results.append("rejected")
            finally: db.session.remove()
    threads=[threading.Thread(target=reserve,args=(f"concurrent-{i}",)) for i in range(2)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert sorted(results) == ["rejected","reserved"]
