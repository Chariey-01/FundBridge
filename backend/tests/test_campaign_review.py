from app.extensions import db
from app.models.core import AuditLog, BeneficiaryProfile, Campaign, CampaignStatus, Role, User
from flask_jwt_extended import create_access_token

def token(app, user):
    with app.app_context(): return create_access_token(identity=user.id)

def setup_campaign(app, same_user=False):
    with app.app_context():
        creator=User(email="creator@test",role=Role.reviewer if same_user else Role.creator); creator.set_password("x"*12)
        reviewer=creator if same_user else User(email="reviewer-campaign@test",role=Role.reviewer)
        if reviewer is not creator: reviewer.set_password("x"*12)
        db.session.add_all([creator,reviewer]); db.session.flush()
        b=BeneficiaryProfile(display_name="Beneficiary",phone_number="+254700000002",country_code="KE"); db.session.add(b); db.session.flush()
        c=Campaign(creator_id=creator.id,beneficiary_id=b.id,title="Campaign review",slug="campaign-review",description="x"*20,category="health",goal_amount="10.00",goal_currency="USD",status=CampaignStatus.submitted,review_status="pending")
        db.session.add(c); db.session.commit(); return c.id, token(app,reviewer)

def test_reviewer_publishes_submitted_campaign(app, client):
    campaign_id, auth=setup_campaign(app)
    r=client.post(f"/api/v1/campaigns/{campaign_id}/review",headers={"Authorization":f"Bearer {auth}"},json={"decision":"approve"})
    assert r.status_code == 200 and r.json["data"]["status"] == "published"

def test_creator_cannot_review_own_campaign(app, client):
    campaign_id, auth=setup_campaign(app, same_user=True)
    r=client.post(f"/api/v1/campaigns/{campaign_id}/review",headers={"Authorization":f"Bearer {auth}"},json={"decision":"approve"})
    assert r.status_code == 403

def test_campaign_creation_persists_before_audit(app, client):
    with app.app_context():
        creator=User(email="new-creator@test",role=Role.creator); creator.set_password("x"*12)
        beneficiary=BeneficiaryProfile(display_name="Beneficiary",phone_number="+254700000003",country_code="KE")
        db.session.add_all([creator, beneficiary]); db.session.commit(); auth=token(app, creator); beneficiary_id=beneficiary.id
    response=client.post("/api/v1/campaigns", headers={"Authorization":f"Bearer {auth}"}, json={
        "beneficiary_id": beneficiary_id, "title": "A new campaign", "slug": "a-new-campaign",
        "description": "A sufficiently long campaign description.", "category": "health",
        "goal_amount": "100.00", "goal_currency": "USD"})
    assert response.status_code == 201
    campaign_id=response.json["data"]["id"]
    with app.app_context():
        assert Campaign.query.get(campaign_id) is not None
        audit=AuditLog.query.filter_by(action="campaign.created", resource_id=campaign_id).one()
        assert audit.resource_type == "campaign"
