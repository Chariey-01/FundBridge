"""Security and financial-integrity tests against the core API (independent QA).

Tests marked ``xfail(strict=True, reason="DEFECT ...")`` document confirmed defects in
the current core backend. They are expected to fail today; when the defect is fixed the
test passes, strict mode reports XPASS as a failure, and the marker must be removed.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.extensions import db
from app.models.core import (
    BeneficiaryProfile,
    Donation,
    DonationStatus,
    FinancialLedgerEntry,
    Payout,
    PayoutStatus,
    Role,
)
from app.services.ledger import available_funds
from app.services.payments import mark_donation_completed

from .conftest import add_pending_donation, auth, make_user


def fund(campaign, amount: str, key: str):
    donation = add_pending_donation(campaign, amount, key)
    mark_donation_completed(donation, f"capture-{key}")
    db.session.commit()
    return donation


def request_payout(client, seeded, amount, key, email="beneficiary@example.test", currency="USD"):
    return client.post(
        "/api/v1/payouts",
        json={"campaign_id": seeded["campaign"].id, "beneficiary_id": seeded["beneficiary"].id,
              "amount": amount, "currency": currency},
        headers={**auth(client, email), "Idempotency-Key": key},
    )


# ------------------------------------------------------------------ donations


def test_unsigned_paypal_webhook_cannot_complete_donation(client, seeded):
    donation = add_pending_donation(seeded["campaign"], "50.00", "w1")
    event = {
        "event_type": "PAYMENT.CAPTURE.COMPLETED",
        "resource": {"id": "forged-capture", "supplementary_data": {"related_ids": {"order_id": "order-w1"}}},
    }
    res = client.post("/api/v1/webhooks/paypal", json=event)
    assert res.status_code == 403
    assert db.session.get(Donation, donation.id).status == DonationStatus.pending
    assert FinancialLedgerEntry.query.count() == 0


def test_duplicate_completion_credits_ledger_once(client, seeded):
    donation = fund(seeded["campaign"], "20.00", "dup")
    mark_donation_completed(donation, "capture-dup")
    mark_donation_completed(donation, "capture-other")
    db.session.commit()
    assert available_funds(seeded["campaign"].id, "USD") == Decimal("20.00")


def test_capture_requires_provider_confirmation(client, seeded, monkeypatch):
    donation = add_pending_donation(seeded["campaign"], "30.00", "cap")
    from app.integrations.payments import paypal

    monkeypatch.setattr(paypal.PayPalSandboxAdapter, "capture_order", lambda self, order_id: {"status": "PENDING"})
    res = client.post(f"/api/v1/donations/{donation.id}/capture", headers=auth(client, "creator@example.test"))
    assert res.status_code == 400
    assert db.session.get(Donation, donation.id).status == DonationStatus.pending
    assert available_funds(seeded["campaign"].id, "USD") == Decimal("0")


def test_client_cannot_set_donation_status(client, seeded):
    donation = add_pending_donation(seeded["campaign"], "30.00", "cs")
    headers = auth(client, "creator@example.test")
    for method in (client.patch, client.put):
        res = method(f"/api/v1/donations/{donation.id}", json={"status": "completed"}, headers=headers)
        assert res.status_code in (404, 405)
    assert db.session.get(Donation, donation.id).status == DonationStatus.pending


@pytest.mark.xfail(strict=True, reason="DEFECT C-1: capture does not compare the captured amount/currency with the "
                                       "donation; the ledger credits the requested amount, not what PayPal captured")
def test_capture_amount_must_match_donation(client, seeded, monkeypatch):
    donation = add_pending_donation(seeded["campaign"], "30.00", "amt")
    from app.integrations.payments import paypal

    captured = {"status": "COMPLETED", "purchase_units": [{"payments": {"captures": [
        {"id": "cap-amt", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "1.00"}}]}}]}
    monkeypatch.setattr(paypal.PayPalSandboxAdapter, "capture_order", lambda self, order_id: captured)
    client.post(f"/api/v1/donations/{donation.id}/capture", headers=auth(client, "creator@example.test"))
    assert available_funds(seeded["campaign"].id, "USD") in (Decimal("0"), Decimal("1.00"))


# -------------------------------------------------------------------- payouts


def test_payout_cannot_exceed_available_funds(client, seeded):
    fund(seeded["campaign"], "100.00", "f1")
    assert request_payout(client, seeded, "60.00", "p-a").status_code == 201
    res = request_payout(client, seeded, "50.00", "p-b")
    assert res.status_code == 400 and res.get_json()["error"]["code"] == "INSUFFICIENT_AVAILABLE_FUNDS"
    assert available_funds(seeded["campaign"].id, "USD") == Decimal("40.00")


def test_payout_without_funds_or_in_other_currency_rejected(client, seeded):
    assert request_payout(client, seeded, "1.00", "p-none").status_code == 400
    fund(seeded["campaign"], "100.00", "f2")
    assert request_payout(client, seeded, "10.00", "p-kes", currency="KES").status_code == 400


def test_payout_idempotency_key_replay_creates_one_reservation(client, seeded):
    fund(seeded["campaign"], "100.00", "f3")
    first = request_payout(client, seeded, "30.00", "same-key")
    second = request_payout(client, seeded, "30.00", "same-key")
    assert first.status_code == 201 and second.status_code == 200
    assert first.get_json()["data"]["id"] == second.get_json()["data"]["id"]
    assert Payout.query.count() == 1
    assert available_funds(seeded["campaign"].id, "USD") == Decimal("70.00")


def test_rejected_payout_releases_reservation(client, seeded):
    fund(seeded["campaign"], "100.00", "f4")
    payout_id = request_payout(client, seeded, "80.00", "p-rej").get_json()["data"]["id"]
    res = client.post(f"/api/v1/payouts/{payout_id}/review", json={"decision": "reject"},
                      headers=auth(client, "reviewer@example.test"))
    assert res.status_code == 200
    assert available_funds(seeded["campaign"].id, "USD") == Decimal("100.00")
    again = client.post(f"/api/v1/payouts/{payout_id}/review", json={"decision": "approve"},
                        headers=auth(client, "reviewer@example.test"))
    assert again.status_code == 400  # rejected is terminal


def test_beneficiary_cannot_request_payout_for_someone_else(client, seeded):
    fund(seeded["campaign"], "100.00", "f5")
    make_user("other-beneficiary@example.test", Role.beneficiary)
    res = request_payout(client, seeded, "10.00", "p-other", email="other-beneficiary@example.test")
    assert res.status_code == 403
    assert Payout.query.count() == 0


def test_creator_and_agent_cannot_review_payouts(client, seeded):
    fund(seeded["campaign"], "100.00", "f6")
    payout_id = request_payout(client, seeded, "10.00", "p-rev").get_json()["data"]["id"]
    for email in ("creator@example.test", "agent@example.test", "beneficiary@example.test"):
        res = client.post(f"/api/v1/payouts/{payout_id}/review", json={"decision": "approve"},
                          headers=auth(client, email))
        assert res.status_code == 403
    assert db.session.get(Payout, payout_id).status == PayoutStatus.requested


def test_registration_cannot_choose_privileged_role(client):
    res = client.post("/api/v1/auth/register",
                      json={"email": "eve@example.test", "password": "long-enough-password", "role": "admin"})
    assert res.get_json()["data"]["role"] == "donor"


@pytest.mark.xfail(strict=True, reason="DEFECT S-1: idempotency keys are global, not scoped to the caller; another "
                                       "user replaying a key receives someone else's payout record")
def test_idempotency_key_is_scoped_to_caller(client, seeded):
    fund(seeded["campaign"], "100.00", "f7")
    request_payout(client, seeded, "30.00", "leaky-key")
    res = request_payout(client, seeded, "30.00", "leaky-key", email="admin@example.test")
    assert res.status_code != 200 or res.get_json()["data"].get("beneficiary_id") is None


@pytest.mark.xfail(strict=True, reason="DEFECT S-2: reusing an Idempotency-Key with a different amount silently "
                                       "returns the original payout instead of rejecting the mismatched request")
def test_idempotency_key_reuse_with_different_body_rejected(client, seeded):
    fund(seeded["campaign"], "100.00", "f8")
    request_payout(client, seeded, "30.00", "reused-key")
    res = request_payout(client, seeded, "90.00", "reused-key")
    assert res.status_code in (409, 422)


@pytest.mark.xfail(strict=True, reason="DEFECT S-3: an admin can request a payout and then approve it; the contract "
                                       "requires that nobody approves their own payout submission")
def test_requester_cannot_approve_own_payout(client, seeded):
    fund(seeded["campaign"], "100.00", "f9")
    payout_id = request_payout(client, seeded, "10.00", "self", email="admin@example.test").get_json()["data"]["id"]
    res = client.post(f"/api/v1/payouts/{payout_id}/review", json={"decision": "approve"},
                      headers=auth(client, "admin@example.test"))
    assert res.status_code == 403


@pytest.mark.xfail(strict=True, reason="DEFECT F-1: payouts are accepted for beneficiaries whose verification_status "
                                       "is not 'verified', to a destination entered at assisted onboarding")
def test_unverified_beneficiary_cannot_request_payout(client, seeded):
    beneficiary: BeneficiaryProfile = seeded["beneficiary"]
    beneficiary.verification_status = "unverified"
    db.session.commit()
    fund(seeded["campaign"], "100.00", "f10")
    assert request_payout(client, seeded, "10.00", "unverified").status_code in (400, 403)


# ----------------------------------------------------------- contract envelope


@pytest.mark.xfail(strict=True, reason="DEFECT A-1: missing/invalid JWT returns flask_jwt_extended's {'msg': ...} "
                                       "body, not the contract error envelope")
def test_unauthenticated_core_request_uses_error_envelope(client):
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401
    assert res.get_json()["error"]["code"] in ("AUTHENTICATION_REQUIRED", "INVALID_TOKEN")


@pytest.mark.xfail(strict=True, reason="DEFECT A-2: wrong password returns 403 INVALID_CREDENTIALS instead of 401")
def test_bad_login_is_401(client, seeded):
    res = client.post("/api/v1/auth/login", json={"email": "creator@example.test", "password": "wrong-password!!"})
    assert res.status_code == 401


def test_errors_do_not_leak_internals(client, seeded):
    res = client.post("/api/v1/payouts", data="not json", headers={**auth(client, "beneficiary@example.test"),
                                                                    "Idempotency-Key": "x"})
    body = res.get_data(as_text=True)
    assert res.status_code == 400 and "Traceback" not in body and "sqlalchemy" not in body.lower()
