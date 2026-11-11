from decimal import Decimal
from unittest.mock import patch

from flask_jwt_extended import create_access_token
from app.extensions import db
from app.models.core import AuditLog, BeneficiaryProfile, Campaign, CampaignStatus, Donation, DonationStatus, FinancialLedgerEntry, Payout, PayoutStatus, ProviderWebhookEvent, Role, User

def token(app, user):
    with app.app_context(): return create_access_token(identity=user.id)

def test_donation_order_requires_valid_authentication(client):
    response=client.post("/api/v1/donations/orders", headers={"Idempotency-Key":"a"}, json={})
    assert response.status_code == 401

def test_paypal_order_uses_persisted_donation_reference_and_validates_response(app, client):
    with app.app_context():
        app.config["PAYPAL_CLIENT_ID"] = "sandbox-client"
        user=User(email="order@test",role=Role.donor); db.session.add(user); db.session.flush()
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="Campaign title",slug="order-campaign",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published); db.session.add(c); db.session.commit(); auth=token(app,user); campaign_id=c.id
    def provider_order(donation, *_):
        assert donation.id
        return {"id":"paypal-order-1","purchase_units":[{"reference_id":donation.id,"amount":{"currency_code":"USD","value":"5.00"}}],"links":[]}
    with patch("app.api.v1.routes.PayPalSandboxAdapter.create_order", side_effect=provider_order):
        response=client.post("/api/v1/donations/orders",headers={"Authorization":f"Bearer {auth}","Idempotency-Key":"order-1"},json={"campaign_id":campaign_id,"amount":"5.00","currency":"USD"})
    assert response.status_code == 201
    with app.app_context():
        donation=Donation.query.filter_by(provider_order_id="paypal-order-1").one()
        assert donation.id

def test_paypal_order_mismatch_is_rejected_without_persisting_donation(app, client):
    with app.app_context():
        app.config["PAYPAL_CLIENT_ID"] = "sandbox-client"
        user=User(email="order-mismatch@test",role=Role.donor); db.session.add(user); db.session.flush()
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="Campaign title",slug="order-mismatch",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published); db.session.add(c); db.session.commit(); auth=token(app,user); campaign_id=c.id
    with patch("app.api.v1.routes.PayPalSandboxAdapter.create_order", return_value={"id":"paypal-order-2","purchase_units":[{"reference_id":"wrong","amount":{"currency_code":"USD","value":"5.00"}}]}):
        response=client.post("/api/v1/donations/orders",headers={"Authorization":f"Bearer {auth}","Idempotency-Key":"order-2"},json={"campaign_id":campaign_id,"amount":"5.00","currency":"USD"})
    assert response.status_code == 400 and response.json["error"]["code"] == "PAYMENT_ORDER_MISMATCH"
    with app.app_context(): assert Donation.query.filter_by(idempotency_key="order-2").count() == 0
    response=client.post("/api/v1/donations/orders", headers={"Authorization":"Bearer invalid","Idempotency-Key":"a"}, json={})
    assert response.status_code == 401

def test_webhook_is_idempotent_and_rejects_wrong_amount(app, client):
    with app.app_context():
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="Campaign title",slug="webhook-campaign",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published)
        db.session.add(c); db.session.flush(); d=Donation(campaign_id=c.id,amount=Decimal("5"),currency="USD",provider="paypal",provider_order_id="order-ok",idempotency_key="webhook",status=DonationStatus.pending); db.session.add(d); db.session.flush(); donation_id=d.id; db.session.commit()
        payload={"id":"event-ok","event_type":"PAYMENT.CAPTURE.COMPLETED","resource":{"id":"capture-ok","status":"COMPLETED","amount":{"currency_code":"USD","value":"5.00"},"supplementary_data":{"related_ids":{"order_id":"order-ok"}}}}
    with patch("app.api.v1.routes.PayPalSandboxAdapter.verify_webhook", return_value=True):
        assert client.post("/api/v1/webhooks/paypal",json=payload).status_code == 204
        assert client.post("/api/v1/webhooks/paypal",json=payload).status_code == 204
    with app.app_context():
        assert Donation.query.filter_by(provider_capture_id="capture-ok").one().status == DonationStatus.completed
        assert FinancialLedgerEntry.query.filter_by(donation_id=donation_id).count() == 1
        assert ProviderWebhookEvent.query.filter_by(provider="paypal",event_id="event-ok").count() == 1
    payload["id"]="event-bad"; payload["resource"]["id"]="capture-bad"; payload["resource"]["amount"]["value"]="7.00"
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

def test_unverified_beneficiary_cannot_request_payout(app, client):
    with app.app_context():
        user=User(email="beneficiary@test",role=Role.beneficiary); user.set_password("x"*12); db.session.add(user); db.session.flush()
        beneficiary=BeneficiaryProfile(user_id=user.id,display_name="Beneficiary",phone_number="+254700000000",country_code="KE",verification_status="unverified",payout_destination_reference="token"); db.session.add(beneficiary); db.session.flush()
        c=Campaign(creator_id="creator",beneficiary_id=beneficiary.id,title="Campaign title",slug="unverified-campaign",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published)
        db.session.add(c); db.session.commit(); auth=token(app,user); campaign_id=c.id; beneficiary_id=beneficiary.id
    r=client.post("/api/v1/payouts",headers={"Authorization":f"Bearer {auth}","Idempotency-Key":"unverified"},json={"campaign_id":campaign_id,"beneficiary_id":beneficiary_id,"amount":"1.00","currency":"USD"})
    assert r.status_code == 400 and r.json["error"]["code"] == "BENEFICIARY_NOT_VERIFIED"

def test_destination_change_requires_reverification(app, client):
    with app.app_context():
        user=User(email="verified@test",role=Role.beneficiary); user.set_password("x"*12); db.session.add(user); db.session.flush()
        profile=BeneficiaryProfile(user_id=user.id,display_name="Verified",phone_number="+254700000001",country_code="KE",verification_status="verified",payout_destination_reference="old-token"); db.session.add(profile); db.session.commit(); auth=token(app,user)
    r=client.patch("/api/v1/beneficiaries/me",headers={"Authorization":f"Bearer {auth}"},json={"payout_destination_reference":"new-token"})
    assert r.status_code == 200 and r.json["data"]["verification_status"] == "reverification_required"

def test_phone_change_requires_reverification(app, client):
    with app.app_context():
        user=User(email="phone-change@test",role=Role.beneficiary); db.session.add(user); db.session.flush()
        profile=BeneficiaryProfile(user_id=user.id,display_name="Verified",phone_number="+254700000010",country_code="KE",verification_status="verified"); db.session.add(profile); db.session.commit(); auth=token(app,user)
    response=client.patch("/api/v1/beneficiaries/me",headers={"Authorization":f"Bearer {auth}"},json={"phone_number":"+254700000011"})
    assert response.status_code == 200 and response.json["data"]["verification_status"] == "reverification_required"
    with app.app_context():
        assert BeneficiaryProfile.query.filter_by(phone_number="+254700000011").one().verification_status == "reverification_required"

def test_beneficiary_onboarding_writes_one_audit_record(app, client):
    with app.app_context():
        admin=User(email="onboard-admin@test",role=Role.admin); db.session.add(admin); db.session.commit(); auth=token(app,admin)
    response=client.post("/api/v1/beneficiaries",headers={"Authorization":f"Bearer {auth}"},json={"display_name":"New beneficiary","phone_number":"+254700000012","country_code":"KE"})
    assert response.status_code == 201
    beneficiary_id=response.json["data"]["id"]
    with app.app_context():
        assert AuditLog.query.filter_by(action="beneficiary.onboarded",resource_id=beneficiary_id).count() == 1

def test_campaign_keyword_search_returns_published_matches(app, client):
    with app.app_context():
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="Clean water project",slug="clean-water-project",description="Clean water for a village",category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published); db.session.add(c); db.session.commit(); campaign_id=c.id
    response=client.get("/api/v1/campaigns?q=water")
    assert response.status_code == 200 and [x["id"] for x in response.json["data"]] == [campaign_id]

def test_paypal_reconciliation_is_authoritative_and_idempotent(app, client):
    with app.app_context():
        user=User(email="reconcile@test",role=Role.donor); db.session.add(user); db.session.flush()
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="Campaign title",slug="reconcile-campaign",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published); db.session.add(c); db.session.flush()
        d=Donation(campaign_id=c.id,donor_id=user.id,amount=Decimal("5.00"),currency="USD",provider="paypal",provider_order_id="order-reconcile",idempotency_key="reconcile",idempotency_fingerprint="fp",status=DonationStatus.pending); db.session.add(d); db.session.commit(); donation_id=d.id; auth=token(app,user)
    completed={"status":"COMPLETED","purchase_units":[{"reference_id":donation_id,"payments":{"captures":[{"id":"capture-reconcile","status":"COMPLETED","amount":{"currency_code":"USD","value":"5.00"}}]}}]}
    with patch("app.api.v1.routes.PayPalSandboxAdapter.get_order", return_value=completed):
        assert client.post(f"/api/v1/donations/{donation_id}/reconcile",headers={"Authorization":f"Bearer {auth}"}).status_code == 200
        assert client.post(f"/api/v1/donations/{donation_id}/reconcile",headers={"Authorization":f"Bearer {auth}"}).status_code == 200
    with app.app_context():
        assert Donation.query.get(donation_id).status == DonationStatus.completed
        assert FinancialLedgerEntry.query.filter_by(donation_id=donation_id).count() == 1

def test_paypal_reconciliation_keeps_ambiguous_order_pending(app, client):
    with app.app_context():
        user=User(email="pending-reconcile@test",role=Role.donor); db.session.add(user); db.session.flush()
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="Campaign title",slug="pending-reconcile",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published); db.session.add(c); db.session.flush()
        d=Donation(campaign_id=c.id,donor_id=user.id,amount=Decimal("5.00"),currency="USD",provider="paypal",provider_order_id="order-pending",idempotency_key="pending",idempotency_fingerprint="fp",status=DonationStatus.pending); db.session.add(d); db.session.commit(); donation_id=d.id; auth=token(app,user)
    with patch("app.api.v1.routes.PayPalSandboxAdapter.get_order", return_value={"status":"APPROVED"}):
        response=client.post(f"/api/v1/donations/{donation_id}/reconcile",headers={"Authorization":f"Bearer {auth}"})
    assert response.status_code == 200 and response.json["data"]["status"] == "pending"

def test_paypal_reconciliation_with_incomplete_capture_stays_pending(app, client):
    with app.app_context():
        user=User(email="capture-pending@test",role=Role.donor); db.session.add(user); db.session.flush()
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="Campaign title",slug="capture-pending",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published); db.session.add(c); db.session.flush()
        d=Donation(campaign_id=c.id,donor_id=user.id,amount=Decimal("5.00"),currency="USD",provider="paypal",provider_order_id="order-capture-pending",idempotency_key="capture-pending",idempotency_fingerprint="fp",status=DonationStatus.pending); db.session.add(d); db.session.commit(); donation_id=d.id; auth=token(app,user)
    result={"status":"COMPLETED","purchase_units":[{"reference_id":donation_id,"payments":{"captures":[{"id":"capture-pending","status":"PENDING","amount":{"currency_code":"USD","value":"5.00"}}]}}]}
    with patch("app.api.v1.routes.PayPalSandboxAdapter.get_order", return_value=result):
        response=client.post(f"/api/v1/donations/{donation_id}/reconcile",headers={"Authorization":f"Bearer {auth}"})
    assert response.status_code == 200 and response.json["data"]["status"] == "pending"

def test_paypal_reconciliation_denied_capture_fails_without_credit(app, client):
    with app.app_context():
        user=User(email="capture-denied@test",role=Role.donor); db.session.add(user); db.session.flush()
        c=Campaign(creator_id="creator",beneficiary_id="beneficiary",title="Campaign title",slug="capture-denied",description="x"*20,category="health",goal_amount=Decimal("100"),goal_currency="USD",status=CampaignStatus.published); db.session.add(c); db.session.flush()
        d=Donation(campaign_id=c.id,donor_id=user.id,amount=Decimal("5.00"),currency="USD",provider="paypal",provider_order_id="order-capture-denied",idempotency_key="capture-denied",idempotency_fingerprint="fp",status=DonationStatus.pending); db.session.add(d); db.session.commit(); donation_id=d.id; auth=token(app,user)
    result={"status":"COMPLETED","purchase_units":[{"reference_id":donation_id,"payments":{"captures":[{"id":"capture-denied","status":"DENIED","amount":{"currency_code":"USD","value":"5.00"}}]}}]}
    with patch("app.api.v1.routes.PayPalSandboxAdapter.get_order", return_value=result):
        response=client.post(f"/api/v1/donations/{donation_id}/reconcile",headers={"Authorization":f"Bearer {auth}"})
    assert response.status_code == 200 and response.json["data"]["status"] == "failed"
