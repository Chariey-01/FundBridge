"""POST /api/v1/ai/status-explanation through the real application: JWT, SQL records, the real OpenAIProvider.

Only the provider's HTTP transport is mocked (no real OpenAI request is made here). The point of these tests is
that the explanation is built from the backend record, cannot change it, gives the same access as the core
GET /donations/{id} and GET /payouts/{id}, and never lets generated text claim an outcome the record does not show.
"""

from __future__ import annotations

import json

import httpx
import pytest
import sqlalchemy as sa

from app.api.v1.ai import AI_EXTENSION
from app.extensions import db
from app.models.core import Role

from .conftest import add_pending_donation, auth, make_user
from .test_financial_security import fund, request_payout

URL = "/api/v1/ai/status-explanation"


def _completion(payload: dict) -> dict:
    return {"id": "c", "object": "chat.completion", "created": 0, "model": "gpt-5.4-mini",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": json.dumps(payload), "refusal": None}}]}


@pytest.fixture()
def app(make_app):
    return make_app(AI_PROVIDER="openai", OPENAI_API_KEY="sk-test-not-real", OPENAI_MODEL="gpt-5.4-mini",
                    AI_MAX_RETRIES="0")


@pytest.fixture()
def model(app):
    """Scripted model: set ``model.reply`` to the explanation it returns. Records every request body."""
    state = {"reply": "", "bodies": []}

    def handler(request: httpx.Request) -> httpx.Response:
        state["bodies"].append(json.loads(request.content))
        return httpx.Response(200, json=_completion({"explanation": state["reply"]}))

    provider = app.extensions[AI_EXTENSION].provider
    provider._client = provider._client.with_options(http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    return state


def _donor(client, email="donor@example.test"):
    user = make_user(email, Role.donor)
    return user, auth(client, email)


def _snapshot():
    with db.engine.connect() as conn:
        return [conn.execute(sa.text(q)).fetchall() for q in (
            "SELECT id, status, amount FROM donation ORDER BY id",
            "SELECT id, status, amount FROM payout ORDER BY id",
            "SELECT id, entry_type, amount FROM financial_ledger_entry ORDER BY id",
            "SELECT count(*) FROM audit_log")]


def test_pending_donation_is_explained_from_the_record_and_unconfirmed_claims_are_replaced(client, seeded, model):
    donor, headers = _donor(client)
    donation = add_pending_donation(seeded["campaign"], "25.00", "se1", donor_id=donor.id)
    before = _snapshot()

    model["reply"] = "Great news! Your donation of 25.00 USD has been received and sent to Amina."
    res = client.post(URL, json={"kind": "donation", "id": donation.id, "language": "en"}, headers=headers)
    assert res.status_code == 200, res.get_json()
    data, meta = res.get_json()["data"], res.get_json()["meta"]
    assert data["status"] == "pending" and data["confirmed"] is False and data["final"] is False
    assert data["amount"] == {"amount": "25.00", "currency": "USD"}
    assert data["explanation"] == data["verified_text"] and "not confirmed yet" in data["explanation"]
    assert meta["output_replaced_by_guardrail"] is True and meta["ai_generated"] is False
    assert meta["guardrail_reason"] == "claims_unconfirmed_outcome"
    assert _snapshot() == before  # nothing written: status, ledger and audit are unchanged

    model["reply"] = "Your 25.00 USD gift is waiting for PayPal to confirm it. Please check again shortly."
    data = client.post(URL, json={"kind": "donation", "id": donation.id}, headers=headers).get_json()
    assert data["meta"]["ai_generated"] is True and data["meta"]["provider"] == "openai"
    assert data["data"]["explanation"].startswith("Your 25.00 USD gift") and data["data"]["status"] == "pending"
    assert _snapshot() == before


def test_completed_donation_counts_but_never_says_the_beneficiary_was_paid(client, seeded, model):
    donor, headers = _donor(client)
    donation = add_pending_donation(seeded["campaign"], "40.00", "se2", donor_id=donor.id)
    fund(seeded["campaign"], "10.00", "se2-other")
    from .conftest import complete

    complete(donation, "cap-se2")
    db.session.commit()

    model["reply"] = "Your donation of 40.00 USD is confirmed and Amina has the money. The beneficiary has received it."
    body = client.post(URL, json={"kind": "donation", "id": donation.id}, headers=headers).get_json()
    assert body["data"]["status"] == "completed" and body["data"]["confirmed"] is True
    assert body["data"]["campaign_raised"] == {"amount": "50.00", "currency": "USD"}  # ledger, both donations
    assert body["meta"]["guardrail_reason"] == "claims_beneficiary_paid"
    assert "does not mean the beneficiary has been paid" in body["data"]["explanation"]

    model["reply"] = "Your donation of 99.00 USD is confirmed."
    assert client.post(URL, json={"kind": "donation", "id": donation.id},
                       headers=headers).get_json()["meta"]["guardrail_reason"] == "amount_mismatch"

    model["reply"] = "Your donation of 40.00 USD is confirmed and counted. The campaign has 50.00 USD confirmed so far."
    ok = client.post(URL, json={"kind": "donation", "id": donation.id}, headers=headers).get_json()
    assert ok["meta"]["ai_generated"] is True and ok["data"]["explanation"] == model["reply"]


def test_model_receives_facts_but_no_personal_or_payment_identifiers(client, seeded, model):
    donor, headers = _donor(client, "private.donor@example.test")
    donation = add_pending_donation(seeded["campaign"], "12.00", "se3", donor_id=donor.id)
    model["reply"] = "Waiting for PayPal."
    client.post(URL, json={"kind": "donation", "id": donation.id, "language": "sw"}, headers=headers)
    sent = json.dumps(model["bodies"][-1])
    assert "12.00 USD" in sent and "pending" in sent and "School fees for Amina" in sent
    for private in ("private.donor@example.test", donor.id, donation.id, "order-se3", "0712345678",
                    "tok_wallet_demo_only", seeded["beneficiary"].id):
        assert private not in sent, private
    assert model["bodies"][-1]["store"] is False


def test_payout_explanation_access_matches_the_core_payout_route(client, seeded, model):
    fund(seeded["campaign"], "100.00", "se4")
    res = request_payout(client, seeded, "30.00", "se4-p")
    assert res.status_code == 201, res.get_json()
    payout_id = res.get_json()["data"]["id"]
    other = make_user("other.beneficiary@example.test", Role.beneficiary)
    from app.models.core import BeneficiaryProfile

    db.session.add(BeneficiaryProfile(user_id=other.id, display_name="Other", phone_number="0712000000",
                                      country_code="KE", verification_status="verified",
                                      payout_destination_reference="tok_other"))
    db.session.commit()
    donor, donor_headers = _donor(client)
    body = {"kind": "payout", "id": payout_id}
    model["reply"] = "Good news, your payout of 30.00 USD has been sent to your M-Pesa."

    for email, expected in (("beneficiary@example.test", 200), ("reviewer@example.test", 200),
                            ("admin@example.test", 200), ("other.beneficiary@example.test", 403),
                            ("creator@example.test", 403), ("agent@example.test", 403)):
        headers = auth(client, email)
        core = client.get(f"/api/v1/payouts/{payout_id}", headers=headers).status_code
        ai = client.post(URL, json=body, headers=headers)
        assert (core, ai.status_code) == (expected, expected), email
        if expected == 403:
            assert ai.get_json()["error"]["code"] == "FORBIDDEN"
    assert client.post(URL, json=body, headers=donor_headers).status_code == 403
    assert client.post(URL, json=body).status_code == 401
    assert client.post(URL, json={"kind": "payout", "id": "no-such-payout"},
                       headers=auth(client, "admin@example.test")).status_code == 404
    assert client.post(URL, json={"kind": "refund", "id": payout_id},
                       headers=auth(client, "admin@example.test")).status_code == 400

    data = client.post(URL, json={**body, "language": "sw"}, headers=auth(client, "beneficiary@example.test")).get_json()
    assert data["data"]["status"] == "requested" and data["data"]["confirmed"] is False
    assert data["meta"]["guardrail_reason"] == "claims_unconfirmed_outcome"
    assert data["data"]["language"] == "sw" and "Hakuna pesa iliyotumwa bado" in data["data"]["explanation"]


def test_donation_access_matches_the_core_donation_route(client, seeded, model):
    owner, owner_headers = _donor(client)
    donation = add_pending_donation(seeded["campaign"], "5.00", "se5", donor_id=owner.id)
    _, stranger_headers = _donor(client, "stranger@example.test")
    model["reply"] = "Waiting for PayPal."
    for headers, expected in ((owner_headers, 200), (stranger_headers, 403),
                              (auth(client, "beneficiary@example.test"), 403),
                              (auth(client, "reviewer@example.test"), 200)):
        core = client.get(f"/api/v1/donations/{donation.id}", headers=headers).status_code
        ai = client.post(URL, json={"kind": "donation", "id": donation.id}, headers=headers).status_code
        assert (core, ai) == (expected, expected)
