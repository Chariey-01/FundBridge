from decimal import Decimal
from app.extensions import db
from app.models.core import Campaign, CampaignStatus, Donation, DonationStatus, FinancialLedgerEntry, Payout, PayoutStatus
from app.services.ledger import available_funds, reserve_payout
from app.services.payments import mark_donation_completed

def test_completed_donation_creates_credit(app):
    with app.app_context():
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="A valid campaign",slug="valid-campaign",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published)
        db.session.add(c); db.session.flush(); d=Donation(campaign_id=c.id,amount=Decimal("10.25"),currency="USD",provider="paypal",idempotency_key="one",status=DonationStatus.pending)
        db.session.add(d); db.session.flush(); mark_donation_completed(d,order_id=None,capture={"id":"capture-one","status":"COMPLETED","amount":{"currency_code":"USD","value":"10.25"}}); db.session.commit()
        assert available_funds(c.id,"USD") == Decimal("10.25")

def test_reservation_prevents_overcommit(app):
    with app.app_context():
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="A valid campaign",slug="reserved-campaign",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published)
        db.session.add(c); db.session.flush(); db.session.add(FinancialLedgerEntry(campaign_id=c.id,entry_type="donation_completed",amount=Decimal("10"),currency="USD",reference="credit")); db.session.flush()
        p=Payout(campaign_id=c.id,beneficiary_id="beneficiary",amount=Decimal("7"),currency="USD",destination_type="wallet",destination_reference="token",provider="simulator",idempotency_key="p1",status=PayoutStatus.requested)
        db.session.add(p); db.session.flush(); reserve_payout(p); db.session.flush()
        p2=Payout(campaign_id=c.id,beneficiary_id="beneficiary",amount=Decimal("4"),currency="USD",destination_type="wallet",destination_reference="token",provider="simulator",idempotency_key="p2",status=PayoutStatus.requested)
        db.session.add(p2); db.session.flush()
        try: reserve_payout(p2)
        except ValueError as error: assert str(error) == "INSUFFICIENT_AVAILABLE_FUNDS"
        else: raise AssertionError("overcommit allowed")

def test_capture_amount_or_currency_mismatch_cannot_credit(app):
    with app.app_context():
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="A valid campaign",slug="mismatch-campaign",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published)
        db.session.add(c); db.session.flush(); d=Donation(campaign_id=c.id,amount=Decimal("10"),currency="USD",provider="paypal",provider_order_id="order-1",idempotency_key="bad",status=DonationStatus.pending); db.session.add(d)
        for capture in ({"id":"bad-amount","status":"COMPLETED","amount":{"currency_code":"USD","value":"9.99"}}, {"id":"bad-currency","status":"COMPLETED","amount":{"currency_code":"KES","value":"10.00"}}):
            try: mark_donation_completed(d,order_id="order-1",capture=capture)
            except ValueError: pass
            else: raise AssertionError("invalid capture credited")
        assert d.status == DonationStatus.pending
