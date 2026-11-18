from decimal import Decimal
from unittest.mock import patch
from app.extensions import db
from app.models.core import Campaign, CampaignStatus, Donation, DonationStatus, FinancialLedgerEntry, Payout, PayoutStatus
from app.services.ledger import available_funds, reserve_payout
from app.services.payments import mark_donation_completed
from app.services.payouts import apply_provider_status

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

def test_donation_to_ledger_to_payout_failure_lifecycle(app):
    with app.app_context():
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="Lifecycle campaign",slug="lifecycle-campaign",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published)
        db.session.add(c); db.session.flush()
        d=Donation(campaign_id=c.id,amount=Decimal("12"),currency="USD",provider="paypal",provider_order_id="lifecycle-order",idempotency_key="lifecycle-donation",status=DonationStatus.pending)
        db.session.add(d); db.session.flush(); mark_donation_completed(d,order_id="lifecycle-order",capture={"id":"lifecycle-capture","status":"COMPLETED","amount":{"currency_code":"USD","value":"12.00"}}); db.session.flush()
        assert available_funds(c.id,"USD") == Decimal("12.00")
        p=Payout(campaign_id=c.id,beneficiary_id="beneficiary",amount=Decimal("12"),currency="USD",destination_type="wallet",destination_reference="token",provider="simulator",idempotency_key="lifecycle-payout",status=PayoutStatus.requested)
        db.session.add(p); db.session.flush(); reserve_payout(p); p.status=PayoutStatus.submitted
        assert available_funds(c.id,"USD") == Decimal("0.00")
        apply_provider_status(p,"FAILED",failure_reason="provider_reconciled_failure"); db.session.commit()
        assert available_funds(c.id,"USD") == Decimal("12.00")

def test_same_idempotency_key_isolated_between_actors(app):
    with app.app_context():
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="Scoped campaign",slug="scoped-campaign",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published); db.session.add(c); db.session.flush()
        first=Donation(campaign_id=c.id,donor_id="donor-a",amount=Decimal("1"),currency="USD",provider="paypal",idempotency_key="same-key",idempotency_fingerprint="a"); second=Donation(campaign_id=c.id,donor_id="donor-b",amount=Decimal("2"),currency="USD",provider="paypal",idempotency_key="same-key",idempotency_fingerprint="b"); db.session.add_all([first,second]); db.session.commit()
        assert Donation.query.filter_by(idempotency_key="same-key").count() == 2
        p1=Payout(campaign_id=c.id,beneficiary_id="beneficiary",requested_by="admin-a",amount=Decimal("1"),currency="USD",destination_type="wallet",destination_reference="one",provider="simulator",idempotency_key="payout-key",idempotency_fingerprint="one")
        p2=Payout(campaign_id=c.id,beneficiary_id="beneficiary",requested_by="admin-b",amount=Decimal("1"),currency="USD",destination_type="wallet",destination_reference="two",provider="simulator",idempotency_key="payout-key",idempotency_fingerprint="two"); db.session.add_all([p1,p2]); db.session.commit()
        assert Payout.query.filter_by(idempotency_key="payout-key").count() == 2


def _completed_donation(app, *, amount=Decimal("10.00")):
    with app.app_context():
        campaign=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="Refund campaign",slug="refund-campaign",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published)
        db.session.add(campaign); db.session.flush()
        donation=Donation(campaign_id=campaign.id,amount=amount,currency="USD",provider="paypal",provider_order_id="refund-order",idempotency_key="refund-key",status=DonationStatus.pending)
        db.session.add(donation); db.session.flush()
        mark_donation_completed(donation,order_id="refund-order",capture={"id":"refund-capture","status":"COMPLETED","amount":{"currency_code":"USD","value":str(amount)}})
        db.session.commit()
        return campaign.id, donation.id


def _reversal_event(event_id, event_type, amount, *, capture_id="refund-capture"):
    return {"id":event_id,"event_type":event_type,"resource":{"id":f"resource-{event_id}","amount":{"currency_code":"USD","value":str(amount)},"supplementary_data":{"related_ids":{"order_id":"refund-order","capture_id":capture_id}}}}


def test_refund_webhook_debits_ledger_is_idempotent_and_blocks_new_payout(app, client):
    campaign_id, donation_id = _completed_donation(app)
    event=_reversal_event("refund-event","PAYMENT.CAPTURE.REFUNDED",Decimal("10.00"))
    with patch("app.api.v1.routes.PayPalSandboxAdapter.verify_webhook", return_value=True):
        assert client.post("/api/v1/webhooks/paypal",json=event).status_code == 204
        assert client.post("/api/v1/webhooks/paypal",json=event).status_code == 204
    with app.app_context():
        donation=Donation.query.get(donation_id)
        assert donation.status == DonationStatus.refunded
        debits=FinancialLedgerEntry.query.filter_by(campaign_id=campaign_id,entry_type="donation_refunded").all()
        assert len(debits) == 1 and Decimal(debits[0].amount) == Decimal("10.00")
        assert available_funds(campaign_id,"USD") == Decimal("0.00")
        payout=Payout(campaign_id=campaign_id,beneficiary_id="beneficiary",amount=Decimal("1.00"),currency="USD",destination_type="wallet",destination_reference="token",provider="simulator",idempotency_key="refund-payout",status=PayoutStatus.requested)
        db.session.add(payout); db.session.flush()
        try: reserve_payout(payout)
        except ValueError as error: assert str(error) == "INSUFFICIENT_AVAILABLE_FUNDS"
        else: raise AssertionError("refunded funds could be reserved for payout")


def test_chargeback_reversal_debits_ledger_and_rejects_wrong_capture(app, client):
    campaign_id, donation_id = _completed_donation(app)
    wrong=_reversal_event("reversal-wrong","PAYMENT.CAPTURE.REVERSED",Decimal("10.00"),capture_id="other-capture")
    with patch("app.api.v1.routes.PayPalSandboxAdapter.verify_webhook", return_value=True):
        assert client.post("/api/v1/webhooks/paypal",json=wrong).status_code == 400
        assert client.post("/api/v1/webhooks/paypal",json=_reversal_event("reversal-event","PAYMENT.CAPTURE.REVERSED",Decimal("10.00"))).status_code == 204
    with app.app_context():
        assert Donation.query.get(donation_id).status == DonationStatus.refunded
        assert FinancialLedgerEntry.query.filter_by(campaign_id=campaign_id,entry_type="donation_reversed").count() == 1
        assert available_funds(campaign_id,"USD") == Decimal("0.00")


def test_partial_refunds_are_cumulative_and_cannot_exceed_capture(app, client):
    campaign_id, donation_id = _completed_donation(app)
    with patch("app.api.v1.routes.PayPalSandboxAdapter.verify_webhook", return_value=True):
        assert client.post("/api/v1/webhooks/paypal",json=_reversal_event("refund-partial-1","PAYMENT.CAPTURE.REFUNDED",Decimal("4.00"))).status_code == 204
    with app.app_context():
        assert Donation.query.get(donation_id).status == DonationStatus.partially_refunded
        assert available_funds(campaign_id,"USD") == Decimal("6.00")
    with patch("app.api.v1.routes.PayPalSandboxAdapter.verify_webhook", return_value=True):
        assert client.post("/api/v1/webhooks/paypal",json=_reversal_event("refund-over","PAYMENT.CAPTURE.REFUNDED",Decimal("7.00"))).status_code == 400
        assert client.post("/api/v1/webhooks/paypal",json=_reversal_event("refund-partial-2","PAYMENT.CAPTURE.REFUNDED",Decimal("6.00"))).status_code == 204
    with app.app_context():
        assert Donation.query.get(donation_id).status == DonationStatus.refunded
        assert available_funds(campaign_id,"USD") == Decimal("0.00")
