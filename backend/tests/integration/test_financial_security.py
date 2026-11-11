"""Security and financial-integrity tests against the core API (independent QA).

Tests marked ``xfail(strict=True, reason="DEFECT ...")`` document confirmed defects in
the current core backend. They are expected to fail today; when the defect is fixed the
test passes, strict mode reports XPASS as a failure, and the marker must be removed.
Tests commented "Was DEFECT ..." are regressions for defects that have been fixed.
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

from .conftest import add_pending_donation, auth, complete, make_user, provider_capture


def fund(campaign, amount: str, key: str):
    donation = add_pending_donation(campaign, amount, key)
    complete(donation, f"capture-{key}")
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
    complete(donation, "capture-dup")  # replay of the same capture is a no-op
    with pytest.raises(ValueError, match="PAYMENT_CAPTURE_MISMATCH"):
        complete(donation, "capture-other")
    db.session.rollback()
    assert available_funds(seeded["campaign"].id, "USD") == Decimal("20.00")


def test_completion_rejects_wrong_amount_or_currency(client, seeded):
    from app.services.payments import mark_donation_completed

    donation = add_pending_donation(seeded["campaign"], "20.00", "wrong")
    for capture, code in [
        (provider_capture(donation, "c1", value="2.00"), "PAYMENT_AMOUNT_MISMATCH"),
        ({**provider_capture(donation, "c2"), "amount": {"currency_code": "EUR", "value": "20.00"}},
         "PAYMENT_CURRENCY_MISMATCH"),
        ({**provider_capture(donation, "c3"), "status": "PENDING"}, "PAYMENT_NOT_CONFIRMED"),
    ]:
        with pytest.raises(ValueError, match=code):
            mark_donation_completed(donation, order_id=donation.provider_order_id, capture=capture)
    with pytest.raises(ValueError, match="PAYMENT_ORDER_MISMATCH"):
        mark_donation_completed(donation, order_id="someone-elses-order", capture=provider_capture(donation, "c4"))
    db.session.rollback()
    assert available_funds(seeded["campaign"].id, "USD") == Decimal("0")


def test_capture_requires_provider_confirmation(client, seeded, monkeypatch):
    creator_id = seeded["campaign"].creator_id
    donation = add_pending_donation(seeded["campaign"], "30.00", "cap", donor_id=creator_id)
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


def test_capture_amount_must_match_donation(client, seeded, monkeypatch):
    # Was DEFECT C-1; fixed in feat/backend-core a1d4833.
    donation = add_pending_donation(seeded["campaign"], "30.00", "amt", donor_id=seeded["campaign"].creator_id)
    from app.integrations.payments import paypal

    captured = {"status": "COMPLETED", "purchase_units": [{"reference_id": donation.id, "payments": {"captures": [
        {"id": "cap-amt", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "1.00"}}]}}]}
    monkeypatch.setattr(paypal.PayPalSandboxAdapter, "capture_order", lambda self, order_id: captured)
    res = client.post(f"/api/v1/donations/{donation.id}/capture", headers=auth(client, "creator@example.test"))
    assert res.status_code == 400 and res.get_json()["error"]["code"] == "PAYMENT_AMOUNT_MISMATCH"
    assert available_funds(seeded["campaign"].id, "USD") == Decimal("0")


def test_capture_of_someone_elses_donation_forbidden(client, seeded):
    donation = add_pending_donation(seeded["campaign"], "30.00", "own", donor_id=seeded["campaign"].creator_id)
    make_user("donor2@example.test", Role.donor)
    res = client.post(f"/api/v1/donations/{donation.id}/capture", headers=auth(client, "donor2@example.test"))
    assert res.status_code == 403


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


def test_idempotency_key_is_scoped_to_caller(client, seeded):
    # Was DEFECT S-1; fixed in feat/backend-core c3e4e3a.
    fund(seeded["campaign"], "100.00", "f7")
    first = request_payout(client, seeded, "30.00", "leaky-key").get_json()["data"]
    res = request_payout(client, seeded, "30.00", "leaky-key", email="admin@example.test")
    assert res.status_code == 201, "another actor's identical key must create its own resource, not replay"
    assert res.get_json()["data"]["id"] != first["id"]


def test_idempotency_key_reuse_with_different_body_rejected(client, seeded):
    # Was DEFECT S-2; fixed in feat/backend-core c3e4e3a (400 IDEMPOTENCY_KEY_REUSED).
    fund(seeded["campaign"], "100.00", "f8")
    first = request_payout(client, seeded, "30.00", "reused-key")
    res = request_payout(client, seeded, "90.00", "reused-key")
    assert res.status_code == 400 and res.get_json()["error"]["code"] == "IDEMPOTENCY_KEY_REUSED"
    replay = request_payout(client, seeded, "30.00", "reused-key")
    assert replay.status_code == 200 and replay.get_json()["data"]["id"] == first.get_json()["data"]["id"]
    assert available_funds(seeded["campaign"].id, "USD") == Decimal("70.00")


def test_requester_cannot_approve_own_payout(client, seeded):
    # Was DEFECT S-3; fixed in feat/backend-core c3e4e3a.
    fund(seeded["campaign"], "100.00", "f9")
    payout_id = request_payout(client, seeded, "10.00", "self", email="admin@example.test").get_json()["data"]["id"]
    res = client.post(f"/api/v1/payouts/{payout_id}/review", json={"decision": "approve"},
                      headers=auth(client, "admin@example.test"))
    assert res.status_code == 403


def test_unverified_beneficiary_cannot_request_payout(client, seeded):
    # Was DEFECT F-1; fixed in feat/backend-core b6a9d1f.
    beneficiary: BeneficiaryProfile = seeded["beneficiary"]
    beneficiary.verification_status = "unverified"
    db.session.commit()
    fund(seeded["campaign"], "100.00", "f10")
    res = request_payout(client, seeded, "10.00", "unverified")
    assert res.status_code == 400 and res.get_json()["error"]["code"] == "BENEFICIARY_NOT_VERIFIED"


# ----------------------------------------------------------- contract envelope


def test_unauthenticated_core_request_uses_error_envelope(client):
    # Was DEFECT A-1; fixed in feat/backend-core c3e4e3a.
    res = client.get("/api/v1/auth/me")
    assert res.status_code == 401 and res.get_json()["error"]["code"] == "AUTH_REQUIRED"
    res = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert res.status_code == 401 and res.get_json()["error"]["code"] == "INVALID_TOKEN"


def test_unknown_resource_uses_error_envelope(client, seeded):
    # Was DEFECT A-3; fixed in feat/backend-core c3e4e3a.
    res = client.get("/api/v1/payouts/does-not-exist", headers=auth(client, "admin@example.test"))
    assert res.status_code == 404 and res.get_json()["error"]["code"] == "NOT_FOUND"


def test_bad_login_is_401(client, seeded):
    # Was DEFECT A-2; fixed in feat/backend-core c3e4e3a. Unknown account and wrong password look identical.
    wrong = client.post("/api/v1/auth/login", json={"email": "creator@example.test", "password": "wrong-password!!"})
    unknown = client.post("/api/v1/auth/login", json={"email": "nobody@example.test", "password": "wrong-password!!"})
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.get_json() == unknown.get_json()


def test_errors_do_not_leak_internals(client, seeded):
    res = client.post("/api/v1/payouts", data="not json", headers={**auth(client, "beneficiary@example.test"),
                                                                    "Idempotency-Key": "x"})
    body = res.get_data(as_text=True)
    assert res.status_code == 400 and "Traceback" not in body and "sqlalchemy" not in body.lower()


# ------------------------------------------------------------ phone channel identity


def test_phone_change_requires_reverification(client, seeded):
    # Was DEFECT P-1. c3e4e3a added a reverification branch, but the generic field loop above it had already
    # written phone_number, so the branch compared the new value with itself and never ran.
    res = client.patch("/api/v1/beneficiaries/me", json={"phone_number": "+254799999999"},
                       headers=auth(client, "beneficiary@example.test"))
    profile = db.session.get(BeneficiaryProfile, seeded["beneficiary"].id)
    assert res.status_code == 200 and res.get_json()["data"]["verification_status"] == "reverification_required"
    assert profile.phone_number == "+254799999999" and profile.verification_status == "reverification_required"
    from app.models.core import AuditLog
    assert AuditLog.query.filter_by(action="beneficiary.phone_changed", resource_id=profile.id).count() == 1
    fund(seeded["campaign"], "100.00", "after-phone-change")
    assert request_payout(client, seeded, "10.00", "after-phone-change").get_json()["error"]["code"] == \
        "BENEFICIARY_NOT_VERIFIED"


def test_unchanged_phone_keeps_verification(client, seeded):
    res = client.patch("/api/v1/beneficiaries/me", json={"phone_number": seeded["beneficiary"].phone_number,
                                                          "display_name": "Renamed"},
                       headers=auth(client, "beneficiary@example.test"))
    assert res.get_json()["data"]["verification_status"] == "verified"


def test_destination_change_requires_reverification(client, seeded):
    res = client.patch("/api/v1/beneficiaries/me", json={"payout_destination_reference": "tok_new"},
                       headers=auth(client, "beneficiary@example.test"))
    assert res.get_json()["data"]["verification_status"] == "reverification_required"
    fund(seeded["campaign"], "100.00", "after-change")
    assert request_payout(client, seeded, "10.00", "after-change").get_json()["error"]["code"] == \
        "BENEFICIARY_NOT_VERIFIED"
