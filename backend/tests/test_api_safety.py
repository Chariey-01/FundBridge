from decimal import Decimal
from unittest.mock import patch

from flask_jwt_extended import create_access_token
from app.extensions import db
from app.models.core import BeneficiaryProfile, Campaign, CampaignStatus, Donation, DonationStatus, FinancialLedgerEntry, Payout, PayoutStatus, Role, User

def token(app, user):
    with app.app_context(): return create_access_token(identity=user.id)

def test_donation_order_requires_valid_authentication(client):
    response=client.post("/api/v1/donations/orders", headers={"Idempotency-Key":"a"}, json={})
    assert response.status_code == 401
    response=client.post("/api/v1/donations/orders", headers={"Authorization":"Bearer invalid","Idempotency-Key":"a"}, json={})
    assert response.status_code == 422

def test_webhook_is_idempotent_and_rejects_wrong_amount(app, client):
    with app.app_context():
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="Campaign title",slug="webhook-campaign",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published)
        db.session.add(c); db.session.flush(); d=Donation(campaign_id=c.id,amount=Decimal("5"),currency="USD",provider="paypal",provider_order_id="order-ok",idempotency_key="webhook",status=DonationStatus.pending); db.session.add(d); db.session.flush(); donation_id=d.id; db.session.commit()
        payload={"event_type":"PAYMENT.CAPTURE.COMPLETED","resource":{"id":"capture-ok","status":"COMPLETED","amount":{"currency_code":"USD","value":"5.00"},"supplementary_data":{"related_ids":{"order_id":"order-ok"}}}}
    with patch("app.api.v1.routes.PayPalSandboxAdapter.verify_webhook", return_value=True):
        assert client.post("/api/v1/webhooks/paypal",json=payload).status_code == 204
        assert client.post("/api/v1/webhooks/paypal",json=payload).status_code == 204
    with app.app_context():
        assert Donation.query.filter_by(provider_capture_id="capture-ok").one().status == DonationStatus.completed
        assert FinancialLedgerEntry.query.filter_by(donation_id=donation_id).count() == 1
    payload["resource"]["id"]="capture-bad"; payload["resource"]["amount"]["value"]="7.00"
    with patch("app.api.v1.routes.PayPalSandboxAdapter.verify_webhook", return_value=True):
        assert client.post("/api/v1/webhooks/paypal",json=payload).status_code == 400

def test_rejected_payout_releases_reservation(app, client):
    with app.app_context():
        reviewer=User(email="reviewer@test",role=Role.reviewer); reviewer.set_password("x"*12)
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="Campaign title",slug="reject-campaign",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published)
        db.session.add_all([reviewer,c]); db.session.flush(); p=Payout(campaign_id=c.id,beneficiary_id="beneficiary",amount=Decimal("5"),currency="USD",destination_type="wallet",destination_reference="token",provider="simulator",idempotency_key="reject",status=PayoutStatus.requested); db.session.add(p); db.session.flush(); payout_id=p.id; db.session.add(FinancialLedgerEntry(campaign_id=c.id,entry_type="donation_completed",amount=Decimal("5"),currency="USD",reference="reject-credit")); db.session.add(FinancialLedgerEntry(campaign_id=c.id,payout_id=p.id,entry_type="payout_reserved",amount=Decimal("5"),currency="USD",reference="reject-reserve")); db.session.commit(); auth=token(app,reviewer)
    r=client.post(f"/api/v1/payouts/{payout_id}/review",headers={"Authorization":f"Bearer {auth}"},json={"decision":"reject"})
    assert r.status_code == 200 and r.json["data"]["status"] == "rejected"
    with app.app_context(): assert FinancialLedgerEntry.query.filter_by(payout_id=payout_id,entry_type="payout_released").count() == 1
