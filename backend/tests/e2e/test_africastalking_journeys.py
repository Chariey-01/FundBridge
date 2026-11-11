"""Feature-phone journeys with SMS_PROVIDER=africastalking, over HTTP, against an Africa's Talking double.

The production server (gunicorn) receives Africa's Talking-format callbacks and sends SMS through the real
adapter to a local stand-in for api.sandbox.africastalking.com. This proves the request FundBridge sends and
how it reacts to the API's answers. It is not a test of Africa's Talking itself (docs/integration/africastalking.md).
"""

from __future__ import annotations

import uuid

from .test_journeys import _donate, _ok, _published_campaign


def _ussd(live, phone, text, session=None):
    res = live.call("POST", f"/api/v1/messaging/ussd?token={live.callback_token()}", data={
        "sessionId": session or "ATUid_" + uuid.uuid4().hex[:10], "serviceCode": "*384*123#",
        "phoneNumber": phone, "networkCode": "63902", "text": text})
    assert res.status_code == 200 and res.headers["Content-Type"].startswith("text/plain")
    return res.text


def _inbound(live, phone, text, message_id):
    return live.call("POST", f"/api/v1/messaging/sms/inbound?token={live.callback_token()}", data={
        "from": phone, "to": "40123", "text": text, "id": message_id, "linkId": "", "date": "2026-11-11 10:00:00",
        "networkCode": "63902"})


def test_sms_and_ussd_through_africastalking_gateway(live_at):
    live = live_at
    status = _ok(live.call("GET", "/api/v1/integrations/status"))["messaging"]
    assert status["sms"] == {"provider": "africastalking", "mode": "africastalking_sandbox", "delivery_confirmed": False}
    assert live.call("GET", "/api/v1/messaging/simulator").status_code == 404  # simulator off

    world = _published_campaign(live, title_word="Uniform")
    phone, cid = world["phone"], world["campaign"]["id"]
    _donate(live, live.account("donor"), cid, "15.00")

    # The confirmed donation was announced through Africa's Talking, with the configured sender.
    sent = live.at.to(phone)
    assert any("confirmed donation of USD 15.00" in m for m in sent), sent
    assert all(m["from"] == "40123" for m in live.at.messages)

    # USSD is answered synchronously; nothing goes through the SMS API.
    before = len(live.at.messages)
    assert "Uniform fees for Amina" in _ussd(live, phone, "1")
    assert len(live.at.messages) == before

    # Inbound SMS reply goes out through the API exactly once, even if the callback is retried.
    message_id = "ATXid_" + uuid.uuid4().hex[:12]
    assert _inbound(live, phone, "STATUS", message_id).status_code == 200
    assert _inbound(live, phone, "STATUS", message_id).status_code == 200
    replies = [m for m in live.at.to(phone) if "Raised: USD 15.00" in m]
    assert len(replies) == 1, live.at.to(phone)

    # Payout approval -> notification via the gateway.
    payout = _ok(live.call("POST", "/api/v1/payouts", world["beneficiary"]["token"],
                           headers={"Idempotency-Key": uuid.uuid4().hex},
                           json={"campaign_id": cid, "beneficiary_id": world["profile"]["id"], "amount": "5.00",
                                 "currency": "USD"}), 201)
    _ok(live.call("POST", f"/api/v1/payouts/{payout['id']}/review", world["reviewer"]["token"],
                  json={"decision": "approve"}))
    assert any("payout of USD 5.00" in m and "Approved, being prepared" in m for m in live.at.to(phone))

    # Delivery report for that message: accepted once, retries ignored.
    form = {"id": "ATXid_000001", "status": "Success", "phoneNumber": phone, "networkCode": "63902", "retryCount": "0"}
    for _ in range(2):
        assert live.call("POST", f"/api/v1/messaging/sms/delivery?token={live.callback_token()}", data=form).status_code == 200
    assert live.call("POST", "/api/v1/messaging/sms/delivery", data=form).status_code == 403


def test_africastalking_outage_never_breaks_callbacks_or_payouts(live_at):
    live = live_at
    world = _published_campaign(live, title_word="Exam")
    phone, cid = world["phone"], world["campaign"]["id"]
    _donate(live, live.account("donor"), cid, "20.00")
    for mode in ("insufficient_balance", "auth_error"):
        live.at.mode = mode
        try:
            assert _inbound(live, phone, "HALI", "ATXid_" + uuid.uuid4().hex[:12]).status_code == 200
            assert _ussd(live, phone, "").startswith("CON FundBridge")
            payout = _ok(live.call("POST", "/api/v1/payouts", world["beneficiary"]["token"],
                                   headers={"Idempotency-Key": uuid.uuid4().hex},
                                   json={"campaign_id": cid, "beneficiary_id": world["profile"]["id"], "amount": "1.00",
                                         "currency": "USD"}), 201)
            review = _ok(live.call("POST", f"/api/v1/payouts/{payout['id']}/review", world["reviewer"]["token"],
                                   json={"decision": "approve"}))
            assert review["status"] == "approved_for_submission"
        finally:
            live.at.mode = "ok"
    log = live.server_log()
    assert live.at.api_key not in log and live.callback_token() not in log
    assert "unhandled error" not in log
