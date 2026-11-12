"""Defects found by the 2026-11-12 release audit in core-backend code (owner: Codex).

Each test states the correct behaviour and is a strict xfail until the owner fixes it. When a fix lands the
test XPASSes, strict mode turns that into a failure, and the marker must be removed so the test becomes a
plain regression test. Reproductions against a live gunicorn + PostgreSQL server are recorded in
docs/RELEASE_AUDIT.md. No production code is changed here.
"""

from __future__ import annotations

import os
import threading

import pytest

from app import create_app
from app.extensions import db
from app.models.core import FinancialLedgerEntry, Payout, PayoutStatus, Role

from .conftest import BASE_CONFIG, PASSWORD, auth, make_user
from .test_financial_security import fund, request_payout

PG_URL = os.environ.get("POSTGRES_TEST_DATABASE_URL") or os.environ.get("FUNDBRIDGE_TEST_DATABASE_URL")


# ---------------------------------------------------------------- AUD-2 authentication


@pytest.mark.xfail(strict=True, reason="AUD-2: login without email/phone matches 'email IS NULL OR phone IS NULL' "
                                       "and signs in as the first such account (routes.py login)")
def test_login_without_an_identifier_is_rejected(client, app):
    make_user("admin@example.test", Role.admin)
    res = client.post("/api/v1/auth/login", json={"password": PASSWORD})
    assert res.status_code == 401, res.get_json()


@pytest.mark.xfail(strict=True, reason="AUD-4: non-string email reaches the database and returns 500 "
                                       "(routes.py register)")
def test_register_rejects_a_non_string_email_with_400(client):
    res = client.post("/api/v1/auth/register", json={"email": {"x": 1}, "password": PASSWORD})
    assert res.status_code == 400, res.get_json()


@pytest.mark.xfail(strict=True, reason="AUD-5: emails are stored and matched case-sensitively (routes.py register/login)")
def test_login_matches_email_case_insensitively(client):
    assert client.post("/api/v1/auth/register", json={"email": "Mixed.Case@Example.test", "password": PASSWORD}).status_code == 201
    res = client.post("/api/v1/auth/login", json={"email": "mixed.case@example.test", "password": PASSWORD})
    assert res.status_code == 200, res.get_json()


@pytest.mark.xfail(strict=True, reason="AUD-6: register accepts any string as an email address (routes.py register)")
def test_register_rejects_a_malformed_email(client):
    res = client.post("/api/v1/auth/register", json={"email": "not-an-email", "password": PASSWORD})
    assert res.status_code == 400, res.get_json()


# ------------------------------------------------------------- AUD-3 campaign edits


def _draft(client, seeded):
    res = client.post("/api/v1/campaigns", headers=auth(client, "creator@example.test"), json={
        "title": "School fees for Baraka", "slug": "school-fees-baraka", "category": "education",
        "description": "Baraka needs help with secondary school fees in Kisumu.", "goal_amount": "300.00",
        "goal_currency": "USD", "beneficiary_id": seeded["beneficiary"].id})
    assert res.status_code == 201, res.get_json()
    return res.get_json()["data"]["id"]


@pytest.mark.xfail(strict=True, reason="AUD-3: PATCH /campaigns/<id> skips the create rules "
                                       "(description >= 20 chars) (routes.py update_campaign)")
def test_campaign_edit_enforces_the_create_description_rule(client, seeded):
    campaign_id = _draft(client, seeded)
    res = client.patch(f"/api/v1/campaigns/{campaign_id}", headers=auth(client, "creator@example.test"),
                       json={"description": "short"})
    assert res.status_code == 400, res.get_json()


@pytest.mark.xfail(strict=True, reason="AUD-3: PATCH accepts a title longer than the 160-character column; "
                                       "PostgreSQL then returns 500 (routes.py update_campaign)")
def test_campaign_edit_rejects_an_overlong_title_with_400(client, seeded):
    campaign_id = _draft(client, seeded)
    res = client.patch(f"/api/v1/campaigns/{campaign_id}", headers=auth(client, "creator@example.test"),
                       json={"title": "T" * 300})
    assert res.status_code == 400, res.get_json()


# ---------------------------------------------------------- AUD-1 payout review race


@pytest.mark.skipif(not PG_URL, reason="set POSTGRES_TEST_DATABASE_URL to an isolated PostgreSQL test database")
@pytest.mark.xfail(strict=True, reason="AUD-1: review_payout reads the payout without a row lock, so a concurrent "
                                       "approve and reject both succeed; the payout can end approved while its "
                                       "reservation is released (routes.py review_payout)")
def test_concurrent_approve_and_reject_cannot_both_succeed(monkeypatch):
    """Deterministic interleaving: both requests are held after their status check, just before commit.

    Without a lock both pass the check and both commit. With a row lock (or a conditional update) the second
    request waits on the lock, the barrier times out, and it then sees the first decision and is refused.
    """
    import app.api.v1.routes as routes
    from app.models.core import BeneficiaryProfile, Campaign, CampaignStatus
    from decimal import Decimal

    flask_app = create_app({**BASE_CONFIG, "SQLALCHEMY_DATABASE_URI": PG_URL})
    with flask_app.app_context():
        db.drop_all()
        db.create_all()
        creator = make_user("creator@example.test", Role.creator)
        make_user("reviewer@example.test", Role.reviewer)
        make_user("admin@example.test", Role.admin)
        user = make_user("beneficiary@example.test", Role.beneficiary)
        profile = BeneficiaryProfile(user_id=user.id, display_name="Amina", phone_number="0712345678",
                                     country_code="KE", verification_status="verified",
                                     payout_destination_reference="tok")
        db.session.add(profile)
        db.session.flush()
        campaign = Campaign(creator_id=creator.id, beneficiary_id=profile.id, title="Race campaign",
                            slug="review-race", description="x" * 30, category="education",
                            goal_amount=Decimal("500"), goal_currency="USD", status=CampaignStatus.published)
        db.session.add(campaign)
        db.session.commit()
        fund(campaign, "100.00", "review-race-fund")
        client = flask_app.test_client()
        res = request_payout(client, {"campaign": campaign, "beneficiary": profile}, "40.00", "review-race-1")
        assert res.status_code == 201, res.get_json()
        payout_id = res.get_json()["data"]["id"]
        headers = {"reviewer": auth(client, "reviewer@example.test"), "admin": auth(client, "admin@example.test")}

    barrier = threading.Barrier(2, timeout=3)
    real_audit = routes.AuditLog

    def held_audit(*args, **kwargs):
        if str(kwargs.get("action", "")).startswith("payout."):
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                pass
        return real_audit(*args, **kwargs)

    monkeypatch.setattr(routes, "AuditLog", held_audit)
    statuses: dict[str, int] = {}

    def review(who: str, decision: str) -> None:
        res = flask_app.test_client().post(f"/api/v1/payouts/{payout_id}/review", headers=headers[who],
                                           json={"decision": decision})
        statuses[decision] = res.status_code

    threads = [threading.Thread(target=review, args=("reviewer", "approve")),
               threading.Thread(target=review, args=("admin", "reject"))]
    [t.start() for t in threads]
    [t.join(30) for t in threads]
    monkeypatch.setattr(routes, "AuditLog", real_audit)

    with flask_app.app_context():
        status = db.session.get(Payout, payout_id).status
        released = FinancialLedgerEntry.query.filter_by(payout_id=payout_id, entry_type="payout_released").count()
        db.session.remove()
        db.drop_all()
    assert sorted(statuses.values()) != [200, 200], statuses
    assert not (status == PayoutStatus.approved_for_submission and released), (status, released)
