"""G-6 beneficiary campaign list and G-7 reviewer queue contract regressions."""

from decimal import Decimal

from app.extensions import db
from app.models.core import BeneficiaryProfile, Campaign, CampaignStatus, Role, User

from .conftest import PASSWORD, auth, make_user


def _campaign(*, creator_id, beneficiary_id, slug, status, review_status="not_submitted"):
    return Campaign(creator_id=creator_id, beneficiary_id=beneficiary_id, title=slug, slug=slug,
                    description="x" * 30, category="education", goal_amount=Decimal("100.00"),
                    goal_currency="USD", status=status, review_status=review_status)


def test_beneficiary_campaigns_are_owned_paginated_and_empty(client, seeded):
    own = seeded["beneficiary"]
    creator = User.query.filter_by(email="creator@example.test").one()
    db.session.add(_campaign(creator_id=creator.id, beneficiary_id=own.id, slug="beneficiary-second",
                             status=CampaignStatus.draft))
    other_user = make_user("other-beneficiary@example.test", Role.beneficiary)
    other = BeneficiaryProfile(user_id=other_user.id, display_name="Other", phone_number="+254700002002",
                               country_code="KE", verification_status="verified")
    db.session.add(other); db.session.flush()
    db.session.add(_campaign(creator_id=creator.id, beneficiary_id=other.id, slug="other-beneficiary-campaign",
                             status=CampaignStatus.published))
    empty_user = make_user("empty-beneficiary@example.test", Role.beneficiary)
    db.session.commit()

    own_page = client.get("/api/v1/beneficiaries/me/campaigns?page=1&page_size=1",
                          headers=auth(client, "beneficiary@example.test"))
    assert own_page.status_code == 200
    assert own_page.json["meta"] == {"page": 1, "page_size": 1, "total": 2}
    assert len(own_page.json["data"]) == 1
    assert all(row["beneficiary_id"] == own.id for row in own_page.json["data"])
    assert {"raised", "created_at", "updated_at"} <= own_page.json["data"][0].keys()

    unrelated = client.get("/api/v1/beneficiaries/me/campaigns", headers=auth(client, other_user.email))
    assert unrelated.status_code == 200
    assert unrelated.json["meta"]["total"] == 1
    assert unrelated.json["data"][0]["beneficiary_id"] == other.id
    empty = client.get("/api/v1/beneficiaries/me/campaigns", headers=auth(client, empty_user.email))
    assert empty.status_code == 200 and empty.json == {"data": [], "meta": {"page": 1, "page_size": 20, "total": 0}}
    assert client.get("/api/v1/beneficiaries/me/campaigns", headers=auth(client, "creator@example.test")).status_code == 403


def test_review_queue_is_restricted_paged_and_excludes_nonpending_states(client, seeded):
    creator = User.query.filter_by(email="creator@example.test").one()
    beneficiary = seeded["beneficiary"]
    db.session.add_all([
        _campaign(creator_id=creator.id, beneficiary_id=beneficiary.id, slug="queue-pending-1",
                  status=CampaignStatus.submitted, review_status="pending"),
        _campaign(creator_id=creator.id, beneficiary_id=beneficiary.id, slug="queue-pending-2",
                  status=CampaignStatus.submitted, review_status="pending"),
        _campaign(creator_id=creator.id, beneficiary_id=beneficiary.id, slug="queue-approved",
                  status=CampaignStatus.published, review_status="approved"),
        _campaign(creator_id=creator.id, beneficiary_id=beneficiary.id, slug="queue-draft",
                  status=CampaignStatus.draft, review_status="rejected"),
    ])
    db.session.commit()
    assert client.get("/api/v1/campaigns/review-queue", headers=auth(client, "creator@example.test")).status_code == 403
    queue = client.get("/api/v1/campaigns/review-queue?page=1&page_size=1", headers=auth(client, "reviewer@example.test"))
    assert queue.status_code == 200 and queue.json["meta"] == {"page": 1, "page_size": 1, "total": 2}
    row = queue.json["data"][0]
    assert row["status"] == "submitted" and row["review_status"] == "pending"
    assert row["submitted_at"] and row["beneficiary_id"] == beneficiary.id
    queue_all = client.get("/api/v1/campaigns/review-queue?page=1&page_size=20", headers=auth(client, "reviewer@example.test"))
    assert {row["slug"] for row in queue_all.json["data"]} == {"queue-pending-1", "queue-pending-2"}
