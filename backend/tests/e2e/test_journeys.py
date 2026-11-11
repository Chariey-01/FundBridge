"""End-to-end user journeys against the live API (see conftest.py for what is real and what is a double)."""

from __future__ import annotations

import json
import random
import uuid
from decimal import Decimal

import pytest

from .provider_doubles import VALID_WEBHOOK_SIGNATURE


def _phone() -> str:
    return "+25471" + "".join(random.choice("0123456789") for _ in range(7))


def _ok(res, status=200):
    assert res.status_code == status, f"{res.request.method} {res.request.path_url} -> {res.status_code} {res.text}"
    return res.json()["data"]


def _err(res, status, code):
    assert res.status_code == status, f"{res.request.method} {res.request.path_url} -> {res.status_code} {res.text}"
    assert res.json()["error"]["code"] == code, res.text
    return res.json()["error"]


def _verify(live, reviewer, profile_id):
    revision = _ok(live.call("GET", f"/api/v1/beneficiaries/{profile_id}", reviewer["token"]))["revision"]
    return _ok(live.call("POST", f"/api/v1/beneficiaries/{profile_id}/verification", reviewer["token"],
                         json={"decision": "verify", "revision": revision}))


def _published_campaign(live, *, title_word: str):
    """Beneficiary onboarding -> verification -> campaign draft -> submit -> review -> publish, all via HTTP."""
    creator, agent, reviewer = live.account("creator"), live.account("agent"), live.account("reviewer")
    beneficiary = live.account("beneficiary")
    phone = _phone()
    profile = _ok(live.call("POST", "/api/v1/beneficiaries", agent["token"], json={
        "user_id": beneficiary["id"], "display_name": "Amina", "phone_number": phone, "country_code": "KE",
        "preferred_language": "en", "payout_destination_reference": "tok_e2e_wallet"}), 201)
    _verify(live, reviewer, profile["id"])
    campaign = _ok(live.call("POST", "/api/v1/campaigns", creator["token"], json={
        "beneficiary_id": profile["id"], "title": f"{title_word} fees for Amina", "slug": f"e2e-{uuid.uuid4().hex[:10]}",
        "description": f"Amina needs help with {title_word.lower()} fees for her final year in Kisumu.",
        "category": "education", "goal_amount": "400.00", "goal_currency": "USD"}), 201)
    _ok(live.call("POST", f"/api/v1/campaigns/{campaign['id']}/submit", creator["token"]))
    published = _ok(live.call("POST", f"/api/v1/campaigns/{campaign['id']}/review", reviewer["token"],
                              json={"decision": "approve"}))
    assert published["status"] == "published"
    return {"creator": creator, "agent": agent, "reviewer": reviewer, "beneficiary": beneficiary,
            "profile": profile, "phone": phone, "campaign": published}


def _donate(live, donor, campaign_id, amount, *, approve=True, capture=True):
    order = _ok(live.call("POST", "/api/v1/donations/orders", donor["token"],
                          headers={"Idempotency-Key": uuid.uuid4().hex},
                          json={"campaign_id": campaign_id, "amount": amount, "currency": "USD",
                                "return_url": "http://localhost:3000/return", "cancel_url": "http://localhost:3000/cancel"}),
                201)
    order_id = order["approval_url"].split("token=")[1]
    if approve:
        live.paypal.approve(order_id)
    if capture:
        return _ok(live.call("POST", f"/api/v1/donations/{order['id']}/capture", donor["token"])), order_id
    return order, order_id


def _funds(live, campaign_id, token=None):
    return _ok(live.call("GET", f"/api/v1/campaigns/{campaign_id}/funds", token))["balance"]


# ------------------------------------------------------------------------------ journeys


def test_platform_status_reports_modes_honestly(live):
    assert _ok(live.call("GET", "/health"))["status"] == "ok"
    cfg = _ok(live.call("GET", "/api/v1/public/config"))
    assert cfg["payouts"] == {"provider": "simulator", "mode": "simulator"}
    status = _ok(live.call("GET", "/api/v1/integrations/status"))
    assert status["messaging"]["sms"]["mode"] == "simulated"
    assert live.call("GET", "/health").headers["X-Request-ID"]


def test_registration_and_authentication(live):
    email = f"donor-{uuid.uuid4().hex[:8]}@example.test"
    reg = _ok(live.call("POST", "/api/v1/auth/register", json={"email": email, "password": "e2e-long-enough-password",
                                                                "role": "admin"}), 201)
    assert reg["role"] == "donor"
    _err(live.call("POST", "/api/v1/auth/register", json={"email": email, "password": "e2e-long-enough-password"}),
         400, "ACCOUNT_ALREADY_EXISTS")
    _err(live.call("POST", "/api/v1/auth/register", json={"email": "x@example.test", "password": "short"}),
         400, "VALIDATION_ERROR")
    token = live.login(email)
    assert _ok(live.call("GET", "/api/v1/auth/me", token))["email"] == email
    wrong = live.call("POST", "/api/v1/auth/login", json={"email": email, "password": "wrong-password-xx"})
    unknown = live.call("POST", "/api/v1/auth/login", json={"email": "nobody@example.test", "password": "wrong-password-xx"})
    assert _err(wrong, 401, "INVALID_CREDENTIALS") == _err(unknown, 401, "INVALID_CREDENTIALS")
    _err(live.call("GET", "/api/v1/auth/me"), 401, "AUTH_REQUIRED")
    _err(live.call("GET", "/api/v1/auth/me", "garbage"), 401, "INVALID_TOKEN")
    # Repeated failures lock the account temporarily, even for the right password.
    for _ in range(4):
        live.call("POST", "/api/v1/auth/login", json={"email": email, "password": "wrong-password-xx"})
    locked = live.call("POST", "/api/v1/auth/login", json={"email": email, "password": "e2e-long-enough-password"})
    _err(locked, 429, "RATE_LIMITED")
    assert int(locked.headers["Retry-After"]) > 0


def test_beneficiary_onboarding_and_reverification(live):
    agent, reviewer, beneficiary = live.account("agent"), live.account("reviewer"), live.account("beneficiary")
    profile = _ok(live.call("POST", "/api/v1/beneficiaries", agent["token"], json={
        "user_id": beneficiary["id"], "display_name": "Baraka", "phone_number": _phone(), "country_code": "KE",
        "payout_destination_reference": "tok_e2e_a"}), 201)
    assert profile["verification_status"] == "unverified"
    pending = _ok(live.call("GET", "/api/v1/beneficiaries?verification_status=unverified", reviewer["token"]))
    assert any(p["id"] == profile["id"] for p in pending)
    # The agent who onboarded cannot also verify.
    _err(live.call("POST", f"/api/v1/beneficiaries/{profile['id']}/verification", agent["token"],
                   json={"decision": "verify", "revision": "x"}), 403, "FORBIDDEN")
    seen = _ok(live.call("GET", f"/api/v1/beneficiaries/{profile['id']}", reviewer["token"]))
    # The beneficiary changes the payout destination between the reviewer's look and decision.
    changed = _ok(live.call("PATCH", "/api/v1/beneficiaries/me", beneficiary["token"],
                            json={"payout_destination_reference": "tok_e2e_b"}))
    assert changed["verification_status"] == "reverification_required"
    _err(live.call("POST", f"/api/v1/beneficiaries/{profile['id']}/verification", reviewer["token"],
                   json={"decision": "verify", "revision": seen["revision"]}), 409, "PROFILE_CHANGED")
    assert _verify(live, reviewer, profile["id"])["verification_status"] == "verified"
    me = _ok(live.call("GET", "/api/v1/beneficiaries/me", beneficiary["token"]))
    assert me["verification_status"] == "verified" and "payout_destination_reference" not in me
    # Phone change also forces reverification.
    assert _ok(live.call("PATCH", "/api/v1/beneficiaries/me", beneficiary["token"],
                         json={"phone_number": _phone()}))["verification_status"] == "reverification_required"


def test_campaign_creation_review_publication_and_discovery(live):
    creator, reviewer, agent = live.account("creator"), live.account("reviewer"), live.account("agent")
    profile = _ok(live.call("POST", "/api/v1/beneficiaries", agent["token"], json={
        "display_name": "Clinic committee", "phone_number": _phone(), "country_code": "KE"}), 201)
    word = "Zebrawood" + uuid.uuid4().hex[:4]
    campaign = _ok(live.call("POST", "/api/v1/campaigns", creator["token"], json={
        "beneficiary_id": profile["id"], "title": f"{word} clinic roof", "slug": f"e2e-{uuid.uuid4().hex[:10]}",
        "description": "The community clinic roof leaks during the long rains.", "category": "medical",
        "goal_amount": "1500.00", "goal_currency": "USD"}), 201)
    assert campaign["status"] == "draft"
    # Not visible to the public or to search while in draft.
    assert _ok(live.call("GET", f"/api/v1/campaigns?q={word}")) == []
    _err(live.call("GET", f"/api/v1/campaigns/{campaign['id']}"), 401, "AUTH_REQUIRED")
    _ok(live.call("POST", f"/api/v1/campaigns/{campaign['id']}/submit", creator["token"]))
    _err(live.call("POST", f"/api/v1/campaigns/{campaign['id']}/review", creator["token"], json={"decision": "approve"}),
         403, "FORBIDDEN")
    rejected = _ok(live.call("POST", f"/api/v1/campaigns/{campaign['id']}/review", reviewer["token"],
                             json={"decision": "reject"}))
    assert rejected["status"] == "draft" and rejected["review_status"] == "rejected"
    _ok(live.call("PATCH", f"/api/v1/campaigns/{campaign['id']}", creator["token"],
                  json={"description": "The community clinic roof leaks; funds buy iron sheets and labour."}))
    _ok(live.call("POST", f"/api/v1/campaigns/{campaign['id']}/submit", creator["token"]))
    published = _ok(live.call("POST", f"/api/v1/campaigns/{campaign['id']}/review", reviewer["token"],
                              json={"decision": "approve"}))
    assert published["status"] == "published"
    assert [c["id"] for c in _ok(live.call("GET", f"/api/v1/campaigns?q={word.lower()}"))] == [campaign["id"]]
    assert campaign["id"] in [c["id"] for c in _ok(live.call("GET", "/api/v1/campaigns?category=medical"))]
    assert campaign["id"] in [c["id"] for c in _ok(live.call("GET", "/api/v1/me/campaigns", creator["token"]))]
    assert _funds(live, campaign["id"]) == {"currency": "USD", "raised": "0.00"}


def test_donation_paypal_capture_ledger_and_history(live):
    world = _published_campaign(live, title_word="School")
    cid, donor = world["campaign"]["id"], live.account("donor")
    key = uuid.uuid4().hex
    body = {"campaign_id": cid, "amount": "25.00", "currency": "USD"}
    order = _ok(live.call("POST", "/api/v1/donations/orders", donor["token"], headers={"Idempotency-Key": key}, json=body),
                201)
    assert order["status"] == "pending" and order["approval_url"].startswith("https://www.sandbox.paypal.com/")
    replay = _ok(live.call("POST", "/api/v1/donations/orders", donor["token"], headers={"Idempotency-Key": key}, json=body))
    assert replay["id"] == order["id"]
    _err(live.call("POST", "/api/v1/donations/orders", donor["token"], headers={"Idempotency-Key": key},
                   json={**body, "amount": "99.00"}), 400, "IDEMPOTENCY_KEY_REUSED")

    # Capturing before the donor approves at PayPal: refused, nothing credited.
    err = _err(live.call("POST", f"/api/v1/donations/{order['id']}/capture", donor["token"]), 502,
               "PROVIDER_REQUEST_REJECTED")
    assert err["details"]["provider_issue"] == "ORDER_NOT_APPROVED"
    assert _ok(live.call("GET", f"/api/v1/donations/{order['id']}", donor["token"]))["status"] == "pending"
    assert _funds(live, cid)["raised"] == "0.00"

    live.paypal.approve(order["approval_url"].split("token=")[1])
    done = _ok(live.call("POST", f"/api/v1/donations/{order['id']}/capture", donor["token"]))
    assert done["status"] == "completed"
    assert _ok(live.call("POST", f"/api/v1/donations/{order['id']}/capture", donor["token"]))["status"] == "completed"
    assert _funds(live, cid)["raised"] == "25.00"  # credited once
    history = _ok(live.call("GET", "/api/v1/me/donations", donor["token"]))
    assert [(d["id"], d["status"], d["amount"]) for d in history] == [(order["id"], "completed", "25.00")]
    stranger = live.account("donor", "stranger")
    _err(live.call("GET", f"/api/v1/donations/{order['id']}", stranger["token"]), 403, "FORBIDDEN")

    # A capture whose amount does not match the donation is never credited.
    tampered, order_id = _donate(live, donor, cid, "40.00", capture=False)
    live.paypal.capture_override[order_id] = {"amount": {"currency_code": "USD", "value": "1.00"}}
    _err(live.call("POST", f"/api/v1/donations/{tampered['id']}/capture", donor["token"]), 400, "PAYMENT_AMOUNT_MISMATCH")
    assert _ok(live.call("GET", f"/api/v1/donations/{tampered['id']}", donor["token"]))["status"] == "pending"
    assert _funds(live, cid)["raised"] == "25.00"


def test_paypal_webhook_requires_verified_signature_and_is_idempotent(live):
    world = _published_campaign(live, title_word="Uniform")
    cid, donor = world["campaign"]["id"], live.account("donor")
    donation, order_id = _donate(live, donor, cid, "15.00", capture=False)
    event = {"id": "WH-EVT-" + uuid.uuid4().hex[:10], "event_type": "PAYMENT.CAPTURE.COMPLETED",
             "resource": {"id": "CAP-WH-" + uuid.uuid4().hex[:8], "status": "COMPLETED",
                          "amount": {"currency_code": "USD", "value": "15.00"},
                          "supplementary_data": {"related_ids": {"order_id": order_id}}}}
    headers = {"PAYPAL-AUTH-ALGO": "SHA256withRSA", "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/cert",
               "PAYPAL-TRANSMISSION-ID": uuid.uuid4().hex, "PAYPAL-TRANSMISSION-TIME": "2026-11-11T10:00:00Z"}
    _err(live.call("POST", "/api/v1/webhooks/paypal", json=event, headers={**headers, "PAYPAL-TRANSMISSION-SIG": "forged"}),
         403, "INVALID_WEBHOOK_SIGNATURE")
    assert _funds(live, cid)["raised"] == "0.00"
    signed = {**headers, "PAYPAL-TRANSMISSION-SIG": VALID_WEBHOOK_SIGNATURE}
    assert live.call("POST", "/api/v1/webhooks/paypal", json=event, headers=signed).status_code == 204
    assert live.call("POST", "/api/v1/webhooks/paypal", json=event, headers=signed).status_code == 204
    assert _ok(live.call("GET", f"/api/v1/donations/{donation['id']}", donor["token"]))["status"] == "completed"
    assert _funds(live, cid)["raised"] == "15.00"


def test_reconcile_after_provider_side_capture_completes_donation_once(live):
    """Was DEFECT R-1; fixed in feat/backend-core ee43660 by POST /donations/{id}/reconcile (no second capture)."""
    world = _published_campaign(live, title_word="Bursary")
    cid, donor = world["campaign"]["id"], live.account("donor")
    donation, order_id = _donate(live, donor, cid, "9.00", capture=False)
    live.paypal.capture_out_of_band(order_id)  # PayPal captured; our capture response was lost
    retry = _err(live.call("POST", f"/api/v1/donations/{donation['id']}/capture", donor["token"]), 502,
                 "PROVIDER_REQUEST_REJECTED")
    assert retry["details"]["provider_issue"] == "ORDER_ALREADY_CAPTURED"
    assert _ok(live.call("GET", f"/api/v1/donations/{donation['id']}", donor["token"]))["status"] == "pending"
    captures_before = sum(1 for r in live.paypal.requests if r["path"].endswith(f"{order_id}/capture"))
    done = _ok(live.call("POST", f"/api/v1/donations/{donation['id']}/reconcile", donor["token"]))
    assert done["status"] == "completed"
    assert _ok(live.call("POST", f"/api/v1/donations/{donation['id']}/reconcile", donor["token"]))["status"] == "completed"
    assert sum(1 for r in live.paypal.requests if r["path"].endswith(f"{order_id}/capture")) == captures_before
    assert _funds(live, cid)["raised"] == "9.00"  # credited exactly once
    stranger = live.account("donor", "reconcile-stranger")
    _err(live.call("POST", f"/api/v1/donations/{donation['id']}/reconcile", stranger["token"]), 403, "FORBIDDEN")


def test_reconcile_with_declined_capture_marks_donation_failed(live):
    """feat/backend-core 9d3f80c: a DECLINED capture found by reconciliation is final; nothing is credited."""
    world = _published_campaign(live, title_word="Declined")
    donor = live.account("donor")
    donation, order_id = _donate(live, donor, world["campaign"]["id"], "7.00", capture=False)
    live.paypal.capture_out_of_band(order_id, capture_status="DECLINED")
    assert _ok(live.call("POST", f"/api/v1/donations/{donation['id']}/reconcile", donor["token"]))["status"] == "failed"
    assert _ok(live.call("GET", f"/api/v1/donations/{donation['id']}", donor["token"]))["status"] == "failed"
    assert _funds(live, world["campaign"]["id"])["raised"] == "0.00"


def test_reconcile_before_capture_leaves_donation_pending(live):
    world = _published_campaign(live, title_word="Sports")
    donor = live.account("donor")
    donation, _ = _donate(live, donor, world["campaign"]["id"], "4.00", capture=False)  # approved, not captured
    assert _ok(live.call("POST", f"/api/v1/donations/{donation['id']}/reconcile", donor["token"]))["status"] == "pending"
    assert _funds(live, world["campaign"]["id"])["raised"] == "0.00"


def test_reconcile_with_pending_capture_stays_pending(live):
    """Was DEFECT R-1b (400 PAYMENT_NOT_CONFIRMED); fixed in feat/backend-core b7bf45b."""
    world = _published_campaign(live, title_word="Held")
    donor = live.account("donor")
    donation, order_id = _donate(live, donor, world["campaign"]["id"], "6.00", capture=False)
    live.paypal.capture_out_of_band(order_id, capture_status="PENDING")
    res = live.call("POST", f"/api/v1/donations/{donation['id']}/reconcile", donor["token"])
    assert _funds(live, world["campaign"]["id"])["raised"] == "0.00"  # never credited (holds either way)
    assert res.status_code == 200 and res.json()["data"]["status"] == "pending"


def test_payout_request_review_reservation_and_tracking(live):
    world = _published_campaign(live, title_word="Exam")
    cid, pid = world["campaign"]["id"], world["profile"]["id"]
    beneficiary, reviewer, creator = world["beneficiary"], world["reviewer"], world["creator"]
    _donate(live, live.account("donor"), cid, "100.00")

    def payout(token, amount, key=None):
        return live.call("POST", "/api/v1/payouts", token, headers={"Idempotency-Key": key or uuid.uuid4().hex},
                         json={"campaign_id": cid, "beneficiary_id": pid, "amount": amount, "currency": "USD"})

    _err(payout(beneficiary["token"], "100.01"), 400, "INSUFFICIENT_AVAILABLE_FUNDS")
    first = _ok(payout(beneficiary["token"], "60.00"), 201)
    assert first["status"] == "requested"
    _err(payout(beneficiary["token"], "50.00"), 400, "INSUFFICIENT_AVAILABLE_FUNDS")  # 60 is reserved
    assert _funds(live, cid, creator["token"]) == {"currency": "USD", "raised": "100.00", "reserved_for_payouts": "60.00",
                                                   "paid_out": "0.00", "available": "40.00"}
    other = live.account("beneficiary", "other")
    _err(live.call("GET", f"/api/v1/payouts/{first['id']}", other["token"]), 403, "FORBIDDEN")
    _err(live.call("POST", f"/api/v1/payouts/{first['id']}/review", beneficiary["token"], json={"decision": "approve"}),
         403, "FORBIDDEN")
    approved = _ok(live.call("POST", f"/api/v1/payouts/{first['id']}/review", reviewer["token"], json={"decision": "approve"}))
    assert approved["status"] == "approved_for_submission"  # never "succeeded" without a provider confirmation
    assert _ok(live.call("GET", f"/api/v1/payouts/{first['id']}", beneficiary["token"]))["status"] == "approved_for_submission"

    second = _ok(payout(beneficiary["token"], "30.00"), 201)
    _ok(live.call("POST", f"/api/v1/payouts/{second['id']}/review", reviewer["token"], json={"decision": "reject"}))
    bal = _funds(live, cid, beneficiary["token"])
    assert bal["available"] == "40.00" and bal["reserved_for_payouts"] == "60.00"
    assert Decimal(bal["raised"]) == Decimal(bal["available"]) + Decimal(bal["reserved_for_payouts"]) + Decimal(bal["paid_out"])
    statuses = {p["id"]: p["status"] for p in _ok(live.call("GET", "/api/v1/payouts", beneficiary["token"]))}
    assert statuses == {first["id"]: "approved_for_submission", second["id"]: "rejected"}

    # Nobody approves their own request, including admins.
    own = _ok(payout(live.admin_token, "5.00"), 201)
    _err(live.call("POST", f"/api/v1/payouts/{own['id']}/review", live.admin_token, json={"decision": "approve"}),
         403, "SELF_APPROVAL_FORBIDDEN")
    # A destination change blocks payouts until re-verified.
    _ok(live.call("PATCH", "/api/v1/beneficiaries/me", beneficiary["token"], json={"payout_destination_reference": "tok_x"}))
    _err(payout(beneficiary["token"], "1.00"), 400, "BENEFICIARY_NOT_VERIFIED")
    _verify(live, reviewer, pid)
    _ok(payout(beneficiary["token"], "1.00"), 201)


def test_feature_phone_ussd_and_sms_in_english_and_kiswahili(live):
    world = _published_campaign(live, title_word="Library")
    cid, phone, reviewer = world["campaign"]["id"], world["phone"], world["reviewer"]
    _donate(live, live.account("donor"), cid, "20.00")
    token = live.callback_token()

    def ussd(text, number=phone):
        res = live.call("POST", f"/api/v1/messaging/ussd?token={token}", data={
            "sessionId": "ATUid_" + uuid.uuid4().hex[:8], "serviceCode": "*384*123#", "phoneNumber": number, "text": text})
        assert res.status_code == 200 and res.headers["Content-Type"].startswith("text/plain")
        return res.text

    assert live.call("POST", "/api/v1/messaging/ussd", data={"phoneNumber": phone, "text": ""}).status_code == 403
    assert ussd("").startswith("CON FundBridge\n1. My campaign")
    mine = ussd("1")
    assert mine.startswith("END ") and "Library fees for Amina" in mine and "USD 20.00" in mine
    assert ussd("2").startswith("CON ")  # create a PIN
    pay = ussd("2*4826*4826")  # PIN set; no payout requested yet
    assert pay.startswith("END ") and "Payout USD" not in pay, pay
    found = ussd("3*library")
    assert "Library fees for Amina" in found

    payout = _ok(live.call("POST", "/api/v1/payouts", world["beneficiary"]["token"],
                           headers={"Idempotency-Key": uuid.uuid4().hex},
                           json={"campaign_id": cid, "beneficiary_id": world["profile"]["id"], "amount": "12.00",
                                 "currency": "USD"}), 201)
    _ok(live.call("POST", f"/api/v1/payouts/{payout['id']}/review", reviewer["token"], json={"decision": "approve"}))
    status = ussd("2*4826")
    assert "USD 12.00" in status and "Approved, being prepared" in status

    # Switch to Kiswahili; menus and payout labels follow.
    assert "Kiswahili" in ussd("6*2")
    assert ussd("").startswith("CON FundBridge\n1. Kampeni yangu")
    assert "Malipo USD 12.00" in ussd("2*4826")

    # Inbound SMS through the gateway callback (Africa's Talking form fields); replies go to the simulated outbox.
    sms = live.call("POST", f"/api/v1/messaging/sms/inbound?token={token}",
                    data={"from": phone, "to": "40123", "text": "HALI", "id": uuid.uuid4().hex, "date": "2026-11-11"})
    assert sms.status_code == 200
    outbox = live.call("GET", f"/api/v1/messaging/simulator/outbox?phone_number={phone}")
    meta, messages = outbox.json()["meta"], [m["message"] for m in outbox.json()["data"]]
    assert meta.get("simulated") is True
    # Sent before the switch to Kiswahili, so in English; every notification is driven by server state changes.
    assert any("confirmed donation of USD 20.00" in m for m in messages), messages
    assert any("payout of USD 12.00" in m and "Approved, being prepared" in m for m in messages), messages
    # The HALI reply came after the switch, so in Kiswahili, with the ledger total.
    assert any("Hali:" in m and "Imechangiwa: USD 20.00" in m for m in messages), messages


def test_ai_features_and_graceful_degradation(live):
    world = _published_campaign(live, title_word="Secondary school")
    creator, beneficiary = world["creator"], world["beneficiary"]
    notes = ("My niece Amina (call me on +254700123456 or amina.family@example.test) is in her final year of "
             "secondary school in Kisumu and we cannot pay the remaining fees.")
    draft = live.call("POST", "/api/v1/ai/campaign-draft", creator["token"],
                      json={"story_notes": notes, "category": "education", "language": "en"})
    body = draft.json()
    assert draft.status_code == 200 and body["meta"]["provider"] == "openai" and body["meta"]["ai_generated"] is True
    assert body["meta"]["degraded"] is False
    sent = json.dumps(live.openai.bodies[-1])
    assert "+254700123456" not in sent and "amina.family@example.test" not in sent  # redacted before leaving the server

    tr = _ok(live.call("POST", "/api/v1/ai/translate", json={"text": "Amina needs help with school fees.",
                                                             "target_language": "sw"}))
    assert "Amina" in json.dumps(tr)
    _ok(live.call("POST", "/api/v1/ai/beneficiary-assistant", beneficiary["token"],
                  json={"message": "When will my payout arrive?", "language": "en"}))
    found = _ok(live.call("POST", "/api/v1/ai/campaign-search", json={"query": "school fees in Kenya"}))
    assert world["campaign"]["id"] in [c["id"] for c in found["results"]]

    # Provider outage: AI degrades, everything essential keeps working.
    live.openai.fail = True
    try:
        degraded = live.call("POST", "/api/v1/ai/campaign-draft", creator["token"],
                             json={"story_notes": notes, "category": "education", "language": "en"})
        assert degraded.status_code == 200 and degraded.json()["meta"]["degraded"] is True
        _err(live.call("POST", "/api/v1/ai/translate", json={"text": "Hello", "target_language": "sw"}), 503,
             "AI_UNAVAILABLE")
        fallback = live.call("POST", "/api/v1/ai/campaign-search", json={"query": "secondary school"})
        assert fallback.status_code == 200 and world["campaign"]["id"] in [c["id"] for c in fallback.json()["data"]["results"]]
        assert world["campaign"]["id"] in [c["id"] for c in _ok(live.call("GET", "/api/v1/campaigns?q=secondary"))]
        done, _ = _donate(live, live.account("donor"), world["campaign"]["id"], "5.00")
        assert done["status"] == "completed"
    finally:
        live.openai.fail = False


def test_cors_allows_only_the_configured_frontend(live):
    good = live.call("OPTIONS", "/api/v1/campaigns", headers={"Origin": "http://localhost:3000",
                                                              "Access-Control-Request-Method": "GET"})
    assert good.headers.get("Access-Control-Allow-Origin") == "http://localhost:3000"
    evil = live.call("OPTIONS", "/api/v1/campaigns", headers={"Origin": "https://evil.example",
                                                              "Access-Control-Request-Method": "GET"})
    assert "Access-Control-Allow-Origin" not in evil.headers


def test_server_logs_hold_no_secrets_or_phone_numbers(live):
    """Runs last in this module: checks everything the server logged during the journeys."""
    log = live.server_log()
    assert "request method=" in log  # the access log is on
    for secret in (live.callback_token(), live.env["FUNDBRIDGE_ADMIN_PASSWORD"], live.env["OPENAI_API_KEY"],
                   live.env["PAYPAL_CLIENT_SECRET"], "eyJ"):
        assert secret not in log, f"secret material in server log: {secret[:6]}..."
    assert "+25471" not in log, "phone number in server log"
    assert "unhandled error" not in log, "a journey hit an unhandled server error"


@pytest.mark.xfail(strict=True, reason="DEFECT C-4b: PayPal's create-order returns a minimal body (id, status, links) "
                                       "unless the request sends 'Prefer: return=representation'; the canonical adapter "
                                       "does not send it but b7bf45b requires purchase_units in the response, so every "
                                       "real order fails with 400 PAYMENT_ORDER_MISMATCH")
def test_order_creation_against_paypal_default_response(live):
    world = _published_campaign(live, title_word="Minimal")
    donor = live.account("donor")
    live.paypal.assume_representation = False  # behave exactly like PayPal's default
    try:
        res = live.call("POST", "/api/v1/donations/orders", donor["token"], headers={"Idempotency-Key": uuid.uuid4().hex},
                        json={"campaign_id": world["campaign"]["id"], "amount": "5.00", "currency": "USD"})
    finally:
        live.paypal.assume_representation = True
    assert res.status_code == 201, res.text

