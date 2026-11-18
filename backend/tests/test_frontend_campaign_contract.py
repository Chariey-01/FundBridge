from decimal import Decimal

from flask_jwt_extended import create_access_token

from app.extensions import db
from app.models.core import (BeneficiaryProfile, Campaign, CampaignStatus,
                             FinancialLedgerEntry, Role, User)


def _token(app, user):
    with app.app_context():
        return create_access_token(identity=user.id)


def _campaign_world(app):
    with app.app_context():
        creator = User(email="campaign-owner@example.test", role=Role.creator); creator.set_password("x" * 12)
        reviewer = User(email="campaign-reviewer@example.test", role=Role.reviewer); reviewer.set_password("x" * 12)
        outsider = User(email="campaign-outsider@example.test", role=Role.donor); outsider.set_password("x" * 12)
        db.session.add_all([creator, reviewer, outsider]); db.session.flush()
        beneficiary = BeneficiaryProfile(display_name="Private beneficiary", phone_number="+254700001001", country_code="KE")
        db.session.add(beneficiary); db.session.flush()
        published = Campaign(creator_id=creator.id, beneficiary_id=beneficiary.id, title="Published detail", slug="published-detail", description="x" * 30, category="health", goal_amount=Decimal("100.00"), goal_currency="USD", status=CampaignStatus.published)
        pending = Campaign(creator_id=creator.id, beneficiary_id=beneficiary.id, title="Pending review", slug="pending-review", description="x" * 30, category="health", goal_amount=Decimal("100.00"), goal_currency="USD", status=CampaignStatus.submitted, review_status="pending")
        db.session.add_all([published, pending]); db.session.flush()
        db.session.add(FinancialLedgerEntry(campaign_id=published.id, entry_type="donation_completed", amount=Decimal("12.50"), currency="USD", reference="frontend-detail-credit"))
        db.session.commit()
        return {"creator": _token(app, creator), "reviewer": _token(app, reviewer), "outsider": _token(app, outsider), "beneficiary_id": beneficiary.id, "published_id": published.id, "pending_id": pending.id}


def test_campaign_detail_privacy_and_ledger_progress(app, client):
    world = _campaign_world(app)
    public = client.get(f"/api/v1/campaigns/{world['published_id']}")
    assert public.status_code == 200
    assert public.json["data"]["raised"] == {"amount": "12.50", "currency": "USD"}
    assert "beneficiary_id" not in public.json["data"]
    creator = client.get(f"/api/v1/campaigns/{world['published_id']}", headers={"Authorization": f"Bearer {world['creator']}"})
    assert creator.json["data"]["beneficiary_id"] == world["beneficiary_id"]
    assert client.get(f"/api/v1/campaigns/{world['pending_id']}", headers={"Authorization": f"Bearer {world['outsider']}"}).status_code == 403


def test_duplicate_slug_is_json_conflict_and_review_queue_is_paginated(app, client):
    world = _campaign_world(app)
    duplicate = client.post("/api/v1/campaigns", headers={"Authorization": f"Bearer {world['creator']}"}, json={
        "beneficiary_id": world["beneficiary_id"], "title": "Duplicate slug", "slug": "published-detail", "description": "x" * 30,
        "category": "health", "goal_amount": "25.00", "goal_currency": "USD"})
    assert duplicate.status_code == 409 and duplicate.json["error"]["code"] == "SLUG_ALREADY_EXISTS"
    forbidden = client.get("/api/v1/campaigns/review-queue", headers={"Authorization": f"Bearer {world['outsider']}"})
    assert forbidden.status_code == 403
    queue = client.get("/api/v1/campaigns/review-queue?page=1&page_size=1", headers={"Authorization": f"Bearer {world['reviewer']}"})
    assert queue.status_code == 200
    assert queue.json["meta"] == {"page": 1, "page_size": 1, "total": 1}
    assert queue.json["data"][0]["id"] == world["pending_id"]
    assert queue.json["data"][0]["beneficiary_id"] == world["beneficiary_id"]


def test_registration_requires_explicit_login(client):
    registered = client.post("/api/v1/auth/register", json={"email": "explicit-login@example.test", "password": "long-enough-password"})
    assert registered.status_code == 201 and "access_token" not in registered.json["data"]
    login = client.post("/api/v1/auth/login", json={"email": "explicit-login@example.test", "password": "long-enough-password"})
    assert login.status_code == 200 and login.json["data"]["access_token"]
