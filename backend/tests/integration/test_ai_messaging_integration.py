"""AI and messaging running inside the real application factory."""

from __future__ import annotations

from app.extensions import db

from .conftest import BENEFICIARY_PHONE, CALLBACK_TOKEN, add_pending_donation, auth, complete


def outbox(client, phone=BENEFICIARY_PHONE):
    return client.get(f"/api/v1/messaging/simulator/outbox?phone_number={phone}").get_json()["data"]


def ussd(client, text, phone=BENEFICIARY_PHONE, token=CALLBACK_TOKEN):
    return client.post(
        f"/api/v1/messaging/ussd?token={token}",
        data={"sessionId": "ATUid_1", "serviceCode": "*384*123#", "phoneNumber": phone, "text": text},
    )


# -------------------------------------------------------------------- status


def test_integration_status_is_honest(client):
    data = client.get("/api/v1/integrations/status").get_json()["data"]
    assert data["ai"]["mode"] == "fallback_only"
    assert data["messaging"]["sms"]["mode"] == "simulated"
    assert data["messaging"]["sms"]["delivery_confirmed"] is False
    assert data["messaging"]["ussd"]["live_shortcode_verified"] is False


# --------------------------------------------------------------- AI with JWT


def test_ai_draft_requires_valid_jwt(client, seeded):
    body = {"story_notes": "Amina is in Form 4 and her mother cannot pay the fees this term."}
    assert client.post("/api/v1/ai/campaign-draft", json=body).status_code == 401
    bad = {"Authorization": "Bearer not-a-jwt"}
    assert client.post("/api/v1/ai/campaign-draft", json=body, headers=bad).status_code == 401
    res = client.post("/api/v1/ai/campaign-draft", json=body, headers=auth(client, "creator@example.test"))
    assert res.status_code == 200
    assert res.get_json()["data"]["requires_human_review"] is True


def test_ai_draft_does_not_create_or_change_campaigns(client, seeded):
    from app.models.core import Campaign

    before = Campaign.query.count()
    client.post("/api/v1/ai/campaign-draft", json={"story_notes": "x" * 40}, headers=auth(client, "creator@example.test"))
    assert Campaign.query.count() == before


def test_ai_search_reads_ledger_totals(client, seeded):
    donation = add_pending_donation(seeded["campaign"], "25.50", "d1")
    complete(donation, "capture-1")
    db.session.commit()
    res = client.post("/api/v1/ai/campaign-search", json={"query": "school fees in Kenya"})
    results = res.get_json()["data"]["results"]
    assert results[0]["slug"] == "school-fees-amina"
    assert results[0]["raised"] == {"amount": "25.50", "currency": "USD"}


def test_ai_search_hides_unpublished(client, seeded):
    seeded["campaign"].status = seeded["campaign"].status.__class__.draft
    db.session.commit()
    res = client.post("/api/v1/ai/campaign-search", json={"query": "school"})
    assert res.get_json()["data"]["results"] == []


# ------------------------------------------------------- callback authentication


def test_ussd_callback_requires_token(client, seeded):
    assert ussd(client, "", token="wrong").status_code == 403
    res = client.post("/api/v1/messaging/ussd", data={"phoneNumber": BENEFICIARY_PHONE, "text": ""})
    assert res.status_code == 403
    res = client.post("/api/v1/messaging/ussd", data={"phoneNumber": BENEFICIARY_PHONE, "text": ""},
                      headers={"X-FundBridge-Callback-Token": CALLBACK_TOKEN})
    assert res.status_code == 200 and res.mimetype == "text/plain"


def test_callbacks_fail_closed_without_configured_token(make_app):
    client = make_app(MESSAGING_CALLBACK_TOKEN="").test_client()
    res = client.post("/api/v1/messaging/ussd?token=", data={"phoneNumber": BENEFICIARY_PHONE, "text": ""})
    assert res.status_code == 503
    assert res.get_json()["error"]["code"] == "MESSAGING_NOT_CONFIGURED"


def test_callbacks_refuse_a_guessable_token(make_app, caplog):
    """Regression: check-config rejected tokens under 24 characters, but the running app accepted them, so a weak
    secret let anyone forge USSD/SMS callbacks for any phone number."""
    weak = "letmein"
    client = make_app(MESSAGING_CALLBACK_TOKEN=weak).test_client()
    for path in ("/api/v1/messaging/ussd", "/api/v1/messaging/sms/inbound", "/api/v1/messaging/sms/delivery"):
        res = client.post(f"{path}?token={weak}", data={"phoneNumber": BENEFICIARY_PHONE, "from": BENEFICIARY_PHONE,
                                                         "text": "", "id": "x", "status": "Success"})
        assert res.status_code == 503 and res.get_json()["error"]["code"] == "MESSAGING_NOT_CONFIGURED", path
    assert "shorter than 24 characters" in caplog.text and weak not in caplog.text
    status = client.get("/api/v1/integrations/status").get_json()["data"]["messaging"]["ussd"]
    assert status["callback_configured"] is False
    assert make_app(MESSAGING_CALLBACK_TOKEN="x" * 24).test_client().post(
        f"/api/v1/messaging/ussd?token={'x' * 24}", data={"phoneNumber": BENEFICIARY_PHONE, "text": ""}).status_code == 200


def test_ip_allowlist(make_app):
    client = make_app(MESSAGING_ALLOWED_IPS="10.0.0.0/8").test_client()
    assert ussd(client, "").status_code == 403  # test client is 127.0.0.1


def test_simulator_disabled_by_default(make_app):
    client = make_app(MESSAGING_SIMULATOR_ENABLED="false").test_client()
    assert client.post("/api/v1/messaging/simulator/ussd", json={"phone_number": BENEFICIARY_PHONE}).status_code == 404
    assert client.get("/api/v1/messaging/simulator").status_code == 404


# -------------------------------------------------------------- USSD end to end


def test_ussd_campaign_status_from_ledger(client, seeded):
    res = ussd(client, "")
    assert res.get_data(as_text=True).startswith("CON FundBridge")
    donation = add_pending_donation(seeded["campaign"], "40.00", "d2")
    complete(donation, "capture-2")
    db.session.commit()
    text = ussd(client, "1").get_data(as_text=True)
    assert text.startswith("END ") and "Raised: USD 40.00 of USD 400.00" in text


def test_pending_donation_is_not_counted(client, seeded):
    add_pending_donation(seeded["campaign"], "99.00", "d3")
    assert "Raised: USD 0.00" in ussd(client, "1").get_data(as_text=True)


def test_ussd_payout_status_behind_pin(client, seeded):
    beneficiary_headers = auth(client, "beneficiary@example.test")
    donation = add_pending_donation(seeded["campaign"], "100.00", "d4")
    complete(donation, "capture-4")
    db.session.commit()
    res = client.post(
        "/api/v1/payouts",
        json={"campaign_id": seeded["campaign"].id, "beneficiary_id": seeded["beneficiary"].id,
              "amount": "60.00", "currency": "USD"},
        headers={**beneficiary_headers, "Idempotency-Key": "payout-1"},
    )
    assert res.status_code == 201, res.get_json()
    assert "Create a 4-digit PIN" in ussd(client, "2").get_data(as_text=True)
    text = ussd(client, "2*4826*4826").get_data(as_text=True)
    assert "USD 60.00" in text and "Requested, waiting for review" in text
    # PIN persisted in the database: the next session asks for it.
    assert "Enter your 4-digit" in ussd(client, "2").get_data(as_text=True)
    assert "Wrong PIN" in ussd(client, "2*9999").get_data(as_text=True)


def test_inbound_sms_reply_goes_to_simulated_outbox(client, seeded):
    res = client.post(f"/api/v1/messaging/sms/inbound?token={CALLBACK_TOKEN}",
                      data={"from": BENEFICIARY_PHONE, "to": "12345", "text": "STATUS", "id": "1"})
    assert res.status_code == 200
    messages = outbox(client)
    assert messages and "School fees for Amina" in messages[0]["message"]
    assert messages[0]["status"] == "simulated"


def test_simulator_endpoints_are_labelled(client, seeded):
    res = client.post("/api/v1/messaging/simulator/ussd", json={"phone_number": "0712345678", "text": "1"})
    body = res.get_json()
    assert body["meta"]["simulated"] is True and body["data"]["session_ended"] is True
    res = client.post("/api/v1/messaging/simulator/sms", json={"phone_number": "0712345678", "text": "HELP"})
    assert res.get_json()["meta"]["simulated"] is True
    assert client.get("/api/v1/messaging/simulator").status_code == 200


# --------------------------------------------------------------- notifications


def test_sms_sent_only_after_committed_completion(client, seeded):
    donation = add_pending_donation(seeded["campaign"], "15.00", "d5")
    assert outbox(client) == []
    complete(donation, "capture-5")
    db.session.rollback()  # never committed: no message
    assert outbox(client) == []
    donation = db.session.get(type(donation), donation.id)
    complete(donation, "capture-5b")
    db.session.commit()
    messages = outbox(client)
    assert len(messages) == 1
    assert "received a confirmed donation of USD 15.00" in messages[0]["message"]
    assert "Total raised: USD 15.00" in messages[0]["message"]


def test_payout_review_triggers_status_sms(client, seeded):
    donation = add_pending_donation(seeded["campaign"], "100.00", "d6")
    complete(donation, "capture-6")
    db.session.commit()
    res = client.post(
        "/api/v1/payouts",
        json={"campaign_id": seeded["campaign"].id, "beneficiary_id": seeded["beneficiary"].id,
              "amount": "50.00", "currency": "USD"},
        headers={**auth(client, "beneficiary@example.test"), "Idempotency-Key": "payout-2"},
    )
    payout_id = res.get_json()["data"]["id"]
    client.post(f"/api/v1/payouts/{payout_id}/review", json={"decision": "approve"},
                headers=auth(client, "reviewer@example.test"))
    messages = [m["message"] for m in outbox(client)]
    assert any("Approved, being prepared" in m for m in messages)
    assert not any("Paid to your mobile money account" in m for m in messages)


# --------------------------------------------------------------- staff actions


def test_pin_reset_is_admin_only(client, seeded):
    url = f"/api/v1/messaging/beneficiaries/{seeded['beneficiary'].id}/pin-reset"
    assert client.post(url).status_code == 401
    assert client.post(url, headers=auth(client, "agent@example.test")).status_code == 403
    ussd(client, "2*4826*4826")
    assert client.post(url, headers=auth(client, "admin@example.test")).status_code == 200
    assert "Create a 4-digit PIN" in ussd(client, "2").get_data(as_text=True)


def test_support_requests_visible_to_agents_only(client, seeded):
    ussd(client, "5*3")
    assert client.get("/api/v1/messaging/support-requests",
                      headers=auth(client, "creator@example.test")).status_code == 403
    rows = client.get("/api/v1/messaging/support-requests",
                      headers=auth(client, "agent@example.test")).get_json()["data"]
    assert rows[0]["topic"] == "sim_change" and rows[0]["priority"] == "high"


def test_proxy_hops_make_allowlist_see_client_ip(make_app):
    client = make_app(MESSAGING_ALLOWED_IPS="10.0.0.0/8", TRUSTED_PROXY_HOPS="1").test_client()
    res = client.post(f"/api/v1/messaging/ussd?token={CALLBACK_TOKEN}",
                      data={"phoneNumber": BENEFICIARY_PHONE, "text": ""}, headers={"X-Forwarded-For": "10.1.2.3"})
    assert res.status_code == 200
    res = client.post(f"/api/v1/messaging/ussd?token={CALLBACK_TOKEN}",
                      data={"phoneNumber": BENEFICIARY_PHONE, "text": ""}, headers={"X-Forwarded-For": "8.8.8.8"})
    assert res.status_code == 403
