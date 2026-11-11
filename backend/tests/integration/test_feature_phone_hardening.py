"""Feature-phone hardening through the real gateway callback endpoints.

- Duplicate callbacks: a retried inbound SMS (same Africa's Talking ``id``) is processed once; a retried
  USSD PIN step (same ``sessionId`` + ``text``) is not counted as a second wrong attempt; repeated help
  requests do not open duplicate support tickets.
- PIN setup, validation, lockout, expiry and reset over HTTP, in English and Kiswahili.
- Delivery reports: authenticated, validated, idempotent; logs mask the number.
- Gateway and AI outages never break USSD/SMS or a financial transaction.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from app.extensions import db
from app.models.core import ProviderWebhookEvent
from app.models.messaging import MessagingPinCredential, SupportRequest

from .conftest import BENEFICIARY_PHONE, CALLBACK_TOKEN, auth
from .test_financial_security import fund, request_payout

PHONE = "+254712345678"
assert BENEFICIARY_PHONE == PHONE


def ussd(client, text, session="ATUid_1", phone=PHONE):
    res = client.post(f"/api/v1/messaging/ussd?token={CALLBACK_TOKEN}",
                      data={"sessionId": session, "serviceCode": "*384*123#", "phoneNumber": phone, "text": text})
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_data(as_text=True)


def inbound_sms(client, text, message_id, phone=PHONE):
    return client.post(f"/api/v1/messaging/sms/inbound?token={CALLBACK_TOKEN}",
                       data={"from": phone, "to": "40123", "text": text, "id": message_id, "date": "2026-11-11"})


def outbox(client, phone=PHONE):
    return [m["message"] for m in client.get(f"/api/v1/messaging/simulator/outbox?phone_number={phone}")
            .get_json()["data"]]


def _pin_row(seeded):
    return db.session.get(MessagingPinCredential, seeded["beneficiary"].id)


# ----------------------------------------------------------------------------- duplicates


def test_retried_inbound_sms_is_processed_once(client, seeded):
    assert inbound_sms(client, "AGENT", "ATXid_abc123").status_code == 200
    assert inbound_sms(client, "AGENT", "ATXid_abc123").status_code == 200  # gateway retry
    assert len(outbox(client)) == 1
    assert SupportRequest.query.filter_by(phone_number=PHONE).count() == 1
    assert inbound_sms(client, "HALI", "ATXid_other").status_code == 200  # a new message is processed
    assert len(outbox(client)) == 2


def test_retried_wrong_pin_step_counts_once(client, seeded):
    ussd(client, "2*4826*4826", session="create")
    first = ussd(client, "2*1111", session="S1")
    retry = ussd(client, "2*1111", session="S1")  # same session and text: a gateway retry
    assert first == retry == "END Wrong PIN. 2 attempt(s) left."
    assert _pin_row(seeded).failed_attempts == 1
    ussd(client, "2*2222", session="S2")
    assert _pin_row(seeded).failed_attempts == 2
    # The stored dedup key is an HMAC: neither the PIN digits nor the session id appear in it.
    keys = [e.event_id for e in ProviderWebhookEvent.query.filter(ProviderWebhookEvent.event_id.like("ussd-pin:%"))]
    assert keys and not any("1111" in k or "S1" in k for k in keys)


def test_repeated_help_requests_do_not_duplicate_tickets(client, seeded):
    first = ussd(client, "5*1", session="h1")
    second = ussd(client, "5*1", session="h2")
    assert SupportRequest.query.filter_by(phone_number=PHONE, topic="callback").count() == 1
    assert first == second and "Ref HLP-" in first  # the caller gets the same reference again
    ussd(client, "5*3", session="h3")  # a different topic is a new request
    assert SupportRequest.query.filter_by(phone_number=PHONE).count() == 2


# ------------------------------------------------------------------------- PIN lifecycle


def test_pin_setup_validation_lockout_expiry_and_reset(client, seeded):
    assert ussd(client, "2").startswith("CON ")                    # create a PIN
    assert "too easy to guess" in ussd(client, "2*1234")           # weak PIN refused
    assert "did not match" in ussd(client, "2*4826*4827")          # confirmation mismatch
    assert _pin_row(seeded) is None
    created = ussd(client, "2*4826*4826")
    assert created.startswith("END ") and _pin_row(seeded) is not None
    assert ussd(client, "2").startswith("CON ")                    # now asks for the PIN

    replies = [ussd(client, f"2*{pin}", session=f"w{pin}") for pin in ("1111", "2222", "3333")]
    assert replies[:2] == ["END Wrong PIN. 2 attempt(s) left.", "END Wrong PIN. 1 attempt(s) left."]
    assert replies[2].startswith("END Too many wrong PINs. Try again in 30 minutes")
    assert _pin_row(seeded).locked_until is not None
    locked = ussd(client, "2*4826", session="right-but-locked")
    assert locked.startswith("END Too many wrong PINs")            # correct PIN refused while locked

    assert "Lugha" in ussd(client, "6*2")
    assert ussd(client, "2*4826", session="sw-locked").startswith("END PIN zisizo sahihi mara nyingi")

    row = _pin_row(seeded)
    row.locked_until = datetime.now(timezone.utc) - timedelta(minutes=1)
    db.session.commit()
    assert ussd(client, "2*4826", session="after-expiry") == "END Bado hakuna ombi la malipo."  # unlocked

    admin = auth(client, "admin@example.test")
    res = client.post(f"/api/v1/messaging/beneficiaries/{seeded['beneficiary'].id}/pin-reset", headers=admin)
    assert res.status_code == 200 and _pin_row(seeded) is None
    assert ussd(client, "2", session="after-reset").startswith("CON ")


# -------------------------------------------------------------------------- delivery reports


def test_delivery_reports_are_authenticated_validated_and_idempotent(client, seeded, caplog):
    form = {"id": "ATXid_dlr1", "status": "Failed", "phoneNumber": PHONE, "networkCode": "63902",
            "failureReason": "UserInBlacklist", "retryCount": "0"}
    assert client.post("/api/v1/messaging/sms/delivery", data=form).status_code == 403
    with caplog.at_level(logging.INFO, logger="fundbridge.messaging"):
        assert client.post(f"/api/v1/messaging/sms/delivery?token={CALLBACK_TOKEN}", data=form).status_code == 200
        assert client.post(f"/api/v1/messaging/sms/delivery?token={CALLBACK_TOKEN}", data=form).status_code == 200
    reports = [r for r in caplog.records if "delivery report" in r.getMessage()]
    assert len(reports) == 1 and reports[0].levelno == logging.WARNING
    assert PHONE not in reports[0].getMessage() and "UserInBlacklist" in reports[0].getMessage()
    assert ProviderWebhookEvent.query.filter_by(event_id="sms-dlr:ATXid_dlr1:Failed").count() == 1
    bad = client.post(f"/api/v1/messaging/sms/delivery?token={CALLBACK_TOKEN}", data={"id": "x", "status": "<b>"})
    assert bad.status_code == 400


# ------------------------------------------------------------------------------ outages


@pytest.fixture()
def at_down_app(make_app):
    # Africa's Talking configured but unreachable (closed port).
    return make_app(SMS_PROVIDER="africastalking", AT_USERNAME="sandbox", AT_API_KEY="at-test-key",
                    AT_API_BASE_URL="http://127.0.0.1:9")


def test_sms_provider_outage_never_breaks_callbacks_or_payouts(at_down_app, caplog):
    from app.models.core import BeneficiaryProfile, Campaign, CampaignStatus, Role
    from decimal import Decimal

    from .conftest import make_user

    client = at_down_app.test_client()
    creator = make_user("c@example.test", Role.creator)
    make_user("r@example.test", Role.reviewer)
    user = make_user("b@example.test", Role.beneficiary)
    profile = BeneficiaryProfile(user_id=user.id, display_name="A", phone_number=PHONE, country_code="KE",
                                 verification_status="verified", payout_destination_reference="tok")
    db.session.add(profile)
    db.session.flush()
    campaign = Campaign(creator_id=creator.id, beneficiary_id=profile.id, title="Fees", slug="fees-x",
                        description="x" * 30, category="education", goal_amount=Decimal("100"), goal_currency="USD",
                        status=CampaignStatus.published)
    db.session.add(campaign)
    db.session.commit()
    seeded = {"campaign": campaign, "beneficiary": profile}
    fund(campaign, "50.00", "outage")

    with caplog.at_level(logging.WARNING):
        assert inbound_sms(client, "HALI", "ATXid_outage").status_code == 200
        assert ussd(client, "1").startswith("END ")
        payout = request_payout(client, seeded, "10.00", "outage-p", email="b@example.test").get_json()["data"]
        review = client.post(f"/api/v1/payouts/{payout['id']}/review", json={"decision": "approve"},
                             headers=auth(client, "r@example.test"))
    assert review.status_code == 200 and review.get_json()["data"]["status"] == "approved_for_submission"
    assert any("Africa's Talking request failed" in r.getMessage() for r in caplog.records)
    status = client.get("/api/v1/messaging/status").get_json()["data"]
    assert status["sms"]["mode"] == "africastalking_sandbox" and status["sms"]["delivery_confirmed"] is False


@pytest.fixture()
def ai_down_app(make_app):
    app = make_app(AI_PROVIDER="openai", OPENAI_API_KEY="sk-test-not-real", AI_MAX_RETRIES="0")
    from app.api.v1.ai import AI_EXTENSION

    provider = app.extensions[AI_EXTENSION].provider
    provider._client = provider._client.with_options(http_client=httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(500, json={"error": {"message": "down"}}))))
    return app


def test_ai_outage_leaves_phone_channels_working(ai_down_app):
    client = ai_down_app.test_client()
    assert ussd(client, "").startswith("CON FundBridge")
    assert ussd(client, "3*school").startswith("END ")
    assert inbound_sms(client, "how do donors give money to my campaign", "ATXid_ai").status_code == 200
    replies = outbox(client)
    assert replies and all("FundBridge" in r for r in replies)  # rule-based reply, no error text


# ------------------------------------------------------------------------ operator commands


def test_check_config_flags_blocking_problems_without_printing_secrets(make_app):
    weak = make_app(MESSAGING_CALLBACK_TOKEN="short", PUBLIC_BASE_URL="http://fundbridge.example",
                    SMS_PROVIDER="africastalking", AT_USERNAME="fundbridge", AT_API_KEY="at-secret-key",
                    USSD_SERVICE_CODE="384")
    res = weak.test_cli_runner().invoke(args=["fundbridge-messaging", "check-config"])
    assert res.exit_code != 0
    for expected in ("shorter than 24", "must use https", "is not a USSD code", "AT_SENDER_ID is empty"):
        assert expected in res.output, expected
    assert "at-secret-key" not in res.output


def test_check_config_prints_callback_urls_without_the_token(make_app):
    good = make_app(MESSAGING_CALLBACK_TOKEN="x" * 32, PUBLIC_BASE_URL="https://fb.example")
    res = good.test_cli_runner().invoke(args=["fundbridge-messaging", "check-config", "--api-host",
                                              "https://api.fb.example"])
    assert res.exit_code == 0, res.output
    assert "https://api.fb.example/api/v1/messaging/sms/delivery?token=<MESSAGING_CALLBACK_TOKEN>" in res.output
    assert "x" * 32 not in res.output and "simulated" in res.output


def test_send_test_with_simulator(app):
    res = app.test_cli_runner().invoke(args=["fundbridge-messaging", "send-test", "--to", "0712345678"])
    assert res.exit_code == 0, res.output
    assert "status=simulated" in res.output and "nothing left the server" in res.output


def test_send_test_when_provider_unreachable(at_down_app):
    res = at_down_app.test_cli_runner().invoke(args=["fundbridge-messaging", "send-test", "--to", "+254712345678"])
    assert res.exit_code != 0 and "detail=network_error" in res.output and "at-test-key" not in res.output


def test_prune_events_keeps_paypal_records(app):
    old = datetime.now(timezone.utc) - timedelta(days=40)
    db.session.add_all([
        ProviderWebhookEvent(provider="africastalking", event_id="sms:old", event_type="sms.inbound", created_at=old),
        ProviderWebhookEvent(provider="africastalking", event_id="sms:new", event_type="sms.inbound"),
        ProviderWebhookEvent(provider="paypal", event_id="WH-old", event_type="PAYMENT.CAPTURE.COMPLETED", created_at=old),
    ])
    db.session.commit()
    res = app.test_cli_runner().invoke(args=["fundbridge-messaging", "prune-events", "--days", "30"])
    assert res.exit_code == 0 and "Deleted 1" in res.output
    assert {e.event_id for e in ProviderWebhookEvent.query} == {"sms:new", "WH-old"}
