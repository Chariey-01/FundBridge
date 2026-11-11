from app.extensions import db
from app.models import User, BeneficiaryProfile, Campaign, Donation, FinancialLedgerEntry
from app.security import issue_token

def auth(app, user):
    with app.app_context(): return {"Authorization": "Bearer " + issue_token(user)}

def seed(app):
    with app.app_context():
        creator = User(email="creator@example.test", role="creator"); creator.set_password("long-password-123")
        donor = User(email="donor@example.test"); donor.set_password("long-password-123")
        beneficiary_user = User(email="beneficiary@example.test", role="beneficiary"); beneficiary_user.set_password("long-password-123")
        db.session.add_all([creator, donor, beneficiary_user]); db.session.flush()
        b = BeneficiaryProfile(user_id=beneficiary_user.id, display_name="Amina", country_code="KE")
        db.session.add(b); db.session.flush()
        c = Campaign(creator_id=creator.id, beneficiary_id=b.id, title="Fund a school", slug="fund-school", description="Books", category="education", goal_amount="100.00", goal_currency="USD", status="published")
        db.session.add(c); db.session.commit()
        return creator, donor, beneficiary_user, b, c

def test_webhook_completes_once_and_creates_one_ledger_entry(app, client):
    creator, donor, _, _, campaign = seed(app)
    response = client.post("/api/v1/donations/orders", json={"campaign_id": campaign.id, "amount": "12.50", "currency": "USD"}, headers={**auth(app, donor), "Idempotency-Key": "donation-1"})
    assert response.status_code == 201
    order = response.json["data"]["provider_order"]["id"]
    webhook = {"order_id": order, "capture_id": "capture-1", "event_type": "PAYMENT.CAPTURE.COMPLETED"}
    headers = {"X-FundBridge-Simulator": "verified"}
    assert client.post("/api/v1/webhooks/paypal", json=webhook, headers=headers).status_code == 200
    assert client.post("/api/v1/webhooks/paypal", json=webhook, headers=headers).status_code == 200
    with app.app_context():
        assert Donation.query.one().status == "completed"
        assert FinancialLedgerEntry.query.count() == 1

def test_client_capture_never_completes_payment(app, client):
    _, donor, _, _, campaign = seed(app)
    order = client.post("/api/v1/donations/orders", json={"campaign_id": campaign.id, "amount": "5", "currency": "USD"}, headers={**auth(app, donor), "Idempotency-Key": "donation-2"}).json["data"]
    assert client.post(f"/api/v1/donations/{order['id']}/capture", headers=auth(app, donor)).status_code == 200
    with app.app_context(): assert Donation.query.get(order["id"]).status == "pending"

def test_payout_rejects_unfunded_campaign(app, client):
    _, _, beneficiary, b, campaign = seed(app)
    response = client.post("/api/v1/payouts", json={"beneficiary_id": b.id, "campaign_id": campaign.id, "amount": "1.00", "currency": "USD", "destination_reference": "protected"}, headers={**auth(app, beneficiary), "Idempotency-Key": "payout-1"})
    assert response.status_code == 409

def test_registration_cannot_self_assign_admin_role(app, client):
    response = client.post("/api/v1/auth/register", json={"email": "new@example.test", "password": "long-password-123", "role": "admin"})
    assert response.status_code == 201
    assert response.json["data"]["user"]["role"] == "donor"
