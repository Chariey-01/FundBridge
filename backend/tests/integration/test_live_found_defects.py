"""Regressions for defects first found by the live end-to-end suite (tests/e2e).

C-2: ``POST /campaigns`` always failed with a 500. The audit row was built before the campaign was
     flushed, so ``resource_id`` was NULL. Every existing test seeded campaigns directly in the
     database, so campaign creation through the API had never succeeded.
C-3: assisted beneficiary onboarding (a sensitive agent action) wrote no audit entry.
L-1: the unhandled-error log included exception messages, which for database errors contain SQL
     parameters such as phone numbers and emails.
"""

from __future__ import annotations

import logging

import sqlalchemy.exc

from app.models.core import AuditLog, Campaign, User

from .conftest import auth


def test_creator_can_create_campaign_through_the_api(client, seeded):
    res = client.post("/api/v1/campaigns", headers=auth(client, "creator@example.test"), json={
        "beneficiary_id": seeded["beneficiary"].id, "title": "Water tank for the school", "slug": "water-tank",
        "description": "A 10,000 litre tank so pupils have clean water.", "category": "water_sanitation",
        "goal_amount": "800.00", "goal_currency": "USD"})
    assert res.status_code == 201, res.get_json()
    campaign_id = res.get_json()["data"]["id"]
    assert Campaign.query.get(campaign_id).status.value == "draft"
    assert AuditLog.query.filter_by(action="campaign.created", resource_id=campaign_id).count() == 1


def test_assisted_onboarding_is_audited(client, seeded):
    res = client.post("/api/v1/beneficiaries", headers=auth(client, "agent@example.test"),
                      json={"display_name": "Otieno", "phone_number": "+254711222333", "country_code": "KE"})
    assert res.status_code == 201
    entry = AuditLog.query.filter_by(action="beneficiary.onboarded", resource_id=res.get_json()["data"]["id"]).one()
    assert entry.actor_id == User.query.filter_by(email="agent@example.test").one().id


def test_unhandled_database_error_log_omits_sql_parameters(client, seeded, monkeypatch, caplog):
    from app.api.v1 import routes

    def boom(_):
        raise sqlalchemy.exc.IntegrityError("INSERT INTO user (phone_number, email) VALUES (?, ?)",
                                            ("+254799887766", "private@example.test"), Exception("UNIQUE failed"))

    monkeypatch.setattr(routes, "serialize_campaign", boom)
    with caplog.at_level(logging.INFO):
        res = client.get("/api/v1/campaigns")
    assert res.status_code == 500 and res.get_json()["error"]["code"] == "INTERNAL_ERROR"
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "IntegrityError" in text  # the type is still recorded for diagnosis
    assert "+254799887766" not in text and "private@example.test" not in text


def test_paypal_order_carries_the_donation_id_as_reference(client, seeded, monkeypatch):
    """C-4: the PayPal order was created before the donation had an id, so reference_id was None and
    every later capture failed the reference_id == donation.id check (PAYMENT_ORDER_MISMATCH)."""
    from flask import current_app

    from app.integrations.payments import paypal

    sent = {}

    def create_order(self, donation, return_url, cancel_url):
        sent["reference_id"] = donation.id
        return {
            "id": "ORDER-REF-1", "status": "CREATED",
            "purchase_units": [{"reference_id": donation.id, "amount": {"currency_code": donation.currency, "value": str(donation.amount)}}],
            "links": [{"rel": "approve", "href": "https://pp/approve"}],
        }

    monkeypatch.setattr(paypal.PayPalSandboxAdapter, "create_order", create_order)
    current_app.config["PAYPAL_CLIENT_ID"] = "sandbox-client"
    res = client.post("/api/v1/donations/orders", headers={**auth(client, "creator@example.test"), "Idempotency-Key": "r1"},
                      json={"campaign_id": seeded["campaign"].id, "amount": "10.00", "currency": "USD"})
    assert res.status_code == 201
    assert sent["reference_id"] and sent["reference_id"] == res.get_json()["data"]["id"]
