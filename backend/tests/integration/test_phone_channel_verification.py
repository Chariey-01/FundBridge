"""The phone channel honours beneficiary verification.

Regression for I-2 (2026-11-11): USSD/SMS treated the number on any beneficiary profile as an
identity, whatever its verification status. Once P-1 made a phone change set
``reverification_required``, the new, unverified number could still set the USSD PIN (trust on first
use), read payout status and receive payout notifications.
"""

from __future__ import annotations

from app.extensions import db
from app.models.core import BeneficiaryProfile
from app.models.messaging import MessagingPinCredential

from .conftest import CALLBACK_TOKEN, auth
from .test_financial_security import fund, request_payout

NEW_NUMBER = "+254799000111"


def ussd(client, phone, text=""):
    res = client.post(f"/api/v1/messaging/ussd?token={CALLBACK_TOKEN}",
                      data={"sessionId": "s1", "serviceCode": "*384*123#", "phoneNumber": phone, "text": text})
    assert res.status_code == 200
    return res.get_data(as_text=True)


def sms(client, phone, text):
    res = client.post("/api/v1/messaging/simulator/sms", json={"phone_number": phone, "text": text})
    return res.get_json()["data"]["replies"]


def outbox(client, phone):
    return client.get(f"/api/v1/messaging/simulator/outbox?phone_number={phone}").get_json()["data"]


def _review(client, profile_id, decision="verify"):
    revision = client.get(f"/api/v1/beneficiaries/{profile_id}",
                          headers=auth(client, "reviewer@example.test")).get_json()["data"]["revision"]
    return client.post(f"/api/v1/beneficiaries/{profile_id}/verification", json={"decision": decision,
                       "revision": revision}, headers=auth(client, "reviewer@example.test"))


def test_new_unverified_number_gets_nothing_beneficiary_specific(client, seeded):
    profile = seeded["beneficiary"]
    fund(seeded["campaign"], "100.00", "pc-fund")
    payout_id = request_payout(client, seeded, "20.00", "pc-1").get_json()["data"]["id"]
    client.patch("/api/v1/beneficiaries/me", json={"phone_number": NEW_NUMBER},
                 headers=auth(client, "beneficiary@example.test"))
    assert db.session.get(BeneficiaryProfile, profile.id).verification_status == "reverification_required"

    for option in ("1", "2"):
        reply = ussd(client, NEW_NUMBER, option)
        assert reply.startswith("END ") and "waiting for verification" in reply, reply
    assert MessagingPinCredential.query.filter_by(beneficiary_id=profile.id).count() == 0
    assert "waiting for verification" in sms(client, NEW_NUMBER, "STATUS")[0]

    # Kiswahili caller gets the same refusal in Kiswahili.
    assert "Lugha imewekwa" in ussd(client, NEW_NUMBER, "6*2")
    assert "inasubiri kuthibitishwa" in ussd(client, NEW_NUMBER, "2")

    # A payout decision while unverified sends no SMS to the new number.
    client.post(f"/api/v1/payouts/{payout_id}/review", json={"decision": "reject"},
                headers=auth(client, "reviewer@example.test"))
    sent = [m["message"] for m in outbox(client, NEW_NUMBER)]
    assert sent and not any("payout" in m.lower() or "malipo" in m.lower() for m in sent), sent

    # Help still works, so the person can reach an agent to be re-verified.
    assert "END" in ussd(client, NEW_NUMBER, "5*1")


def test_reverified_number_regains_access(client, seeded):
    profile = seeded["beneficiary"]
    client.patch("/api/v1/beneficiaries/me", json={"phone_number": NEW_NUMBER},
                 headers=auth(client, "beneficiary@example.test"))
    assert _review(client, profile.id).get_json()["data"]["verification_status"] == "verified"
    assert ussd(client, NEW_NUMBER, "2").startswith("CON ")  # PIN creation prompt
    assert "School fees for Amina" in ussd(client, NEW_NUMBER, "1")
