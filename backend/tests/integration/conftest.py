"""Fixtures that run the real application factory (core backend + AI + messaging)."""

from __future__ import annotations

import os
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models.core import (  # noqa: E402
    BeneficiaryProfile,
    Campaign,
    CampaignStatus,
    Donation,
    DonationStatus,
    Role,
    User,
)

CALLBACK_TOKEN = "test-callback-token-0123456789"
PASSWORD = "long-enough-password"
BENEFICIARY_PHONE = "+254712345678"

BASE_CONFIG = {
    "TESTING": True,
    "SQLALCHEMY_DATABASE_URI": "sqlite://",
    "SECRET_KEY": "test-secret",
    "JWT_SECRET_KEY": "test-jwt-secret-with-at-least-thirty-two-bytes",
    "PAYPAL_CLIENT_ID": None,
    "AI_PROVIDER": "disabled",
    "SMS_PROVIDER": "simulator",
    "MESSAGING_CALLBACK_TOKEN": CALLBACK_TOKEN,
    "MESSAGING_SIMULATOR_ENABLED": "true",
    "PUBLIC_BASE_URL": "https://fundbridge.test",
}


@pytest.fixture()
def make_app():
    apps = []

    def factory(**overrides):
        app = create_app({**BASE_CONFIG, **overrides})
        ctx = app.app_context()
        ctx.push()
        db.create_all()
        apps.append(ctx)
        return app

    yield factory
    for ctx in apps:
        db.session.remove()
        db.drop_all()
        ctx.pop()


@pytest.fixture()
def app(make_app):
    return make_app()


@pytest.fixture()
def client(app):
    return app.test_client()


def make_user(email: str, role: Role) -> User:
    user = User(email=email, role=role)
    user.set_password(PASSWORD)
    db.session.add(user)
    db.session.commit()
    return user


def token_for(client, email: str) -> str:
    res = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert res.status_code == 200, res.get_json()
    return res.get_json()["data"]["access_token"]


def auth(client, email: str) -> dict:
    return {"Authorization": f"Bearer {token_for(client, email)}"}


@pytest.fixture()
def seeded(app):
    """A creator, an admin, a reviewer, a beneficiary account with a published campaign."""
    creator = make_user("creator@example.test", Role.creator)
    make_user("admin@example.test", Role.admin)
    make_user("reviewer@example.test", Role.reviewer)
    make_user("agent@example.test", Role.agent)
    beneficiary_user = make_user("beneficiary@example.test", Role.beneficiary)
    beneficiary = BeneficiaryProfile(
        user_id=beneficiary_user.id, display_name="Amina", phone_number="0712345678", country_code="KE",
        preferred_language="en", verification_status="verified",
        payout_destination_reference="tok_wallet_demo_only",
    )
    db.session.add(beneficiary)
    db.session.flush()
    campaign = Campaign(
        creator_id=creator.id, beneficiary_id=beneficiary.id, title="School fees for Amina",
        slug="school-fees-amina", description="Amina needs help with secondary school fees in Kisumu.",
        category="education", goal_amount=Decimal("400.00"), goal_currency="USD", status=CampaignStatus.published,
    )
    db.session.add(campaign)
    db.session.commit()
    return {"beneficiary": beneficiary, "campaign": campaign, "beneficiary_user": beneficiary_user}


def add_pending_donation(campaign, amount: str, key: str) -> Donation:
    donation = Donation(campaign_id=campaign.id, amount=Decimal(amount), currency="USD", provider="paypal",
                        idempotency_key=key, status=DonationStatus.pending, provider_order_id=f"order-{key}")
    db.session.add(donation)
    db.session.commit()
    return donation
