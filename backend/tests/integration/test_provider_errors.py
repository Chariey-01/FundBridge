"""PayPal HTTP failures surface as JSON envelopes and never leave a partial donation.

Regression for H-2 (2026-11-11): a provider timeout or 4xx (for example ORDER_NOT_APPROVED when
capturing before the donor approved) raised an unhandled ``requests`` exception, so the API
returned Flask's HTML 500 page instead of the contract envelope.
"""

from __future__ import annotations

import pytest
import requests

from app.extensions import db
from app.models.core import Donation, DonationStatus, Role

from .conftest import add_pending_donation, auth, make_user


@pytest.fixture()
def app(make_app):
    # PayPal "configured" but pointed at a closed port, so every provider call fails at the network layer.
    return make_app(PAYPAL_CLIENT_ID="sandbox-client", PAYPAL_CLIENT_SECRET="sandbox-secret",
                    PAYPAL_BASE_URL="http://127.0.0.1:9")  # nothing listens on the discard port


def test_unreachable_payment_provider_returns_envelope_and_writes_nothing(client, seeded):
    make_user("donor@example.test", Role.donor)
    res = client.post("/api/v1/donations/orders", headers={**auth(client, "donor@example.test"), "Idempotency-Key": "k1"},
                      json={"campaign_id": seeded["campaign"].id, "amount": "10.00", "currency": "USD"})
    assert res.status_code == 503 and res.get_json()["error"]["code"] == "PROVIDER_UNAVAILABLE"
    assert Donation.query.count() == 0


def test_provider_rejection_keeps_donation_pending(client, seeded, monkeypatch):
    from app.integrations.payments import paypal

    def rejected(self, order_id):
        response = requests.Response()
        response.status_code = 422
        response._content = b'{"name":"UNPROCESSABLE_ENTITY","details":[{"issue":"ORDER_NOT_APPROVED"}]}'
        raise requests.HTTPError(response=response)

    monkeypatch.setattr(paypal.PayPalSandboxAdapter, "capture_order", rejected)
    donation = add_pending_donation(seeded["campaign"], "25.00", "nap", donor_id=seeded["campaign"].creator_id)
    res = client.post(f"/api/v1/donations/{donation.id}/capture", headers=auth(client, "creator@example.test"))
    body = res.get_json()["error"]
    assert res.status_code == 502 and body["code"] == "PROVIDER_REQUEST_REJECTED"
    assert body["details"] == {"provider_status": 422, "provider_issue": "ORDER_NOT_APPROVED"}
    assert "charged" not in body["message"]  # never claim the donor was or was not charged
    assert db.session.get(Donation, donation.id).status == DonationStatus.pending
