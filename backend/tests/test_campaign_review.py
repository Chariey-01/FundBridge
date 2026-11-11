from app.extensions import db
from app.models.core import BeneficiaryProfile, Campaign, CampaignStatus, Role, User
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
