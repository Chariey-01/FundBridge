"""Wire-level tests of the Africa's Talking SMS adapter against a fake HTTP session.

They check the request FundBridge builds and how responses are classified. They do not prove that
Africa's Talking accepts the request: that needs an authorised account (docs/integration/africastalking.md).
"""

from __future__ import annotations

import pytest
import requests

from app.integrations.messaging.gateways import SMS_MAX_CHARS, AfricasTalkingSmsGateway


class FakeResponse:
    def __init__(self, status_code=201, json_body=None, text=""):
        self.status_code, self._json, self.text = status_code, json_body, text

    def json(self):
        if self._json is None:
            raise ValueError("not json")
        return self._json


class FakeSession:
    def __init__(self, response=None, exc=None):
        self.response, self.exc, self.calls = response, exc, []

    def post(self, url, data=None, headers=None, timeout=None):
        self.calls.append({"url": url, "data": data, "headers": headers, "timeout": timeout})
        if self.exc:
            raise self.exc
        return self.response


def recipients(status_code, status, message_id="ATXid_1"):
    return {"SMSMessageData": {"Message": "Sent to 1/1 Total Cost: KES 0.8000", "Recipients": [
        {"statusCode": status_code, "number": "+254712345678", "status": status, "cost": "KES 0.8000",
         "messageId": message_id}]}}


def gateway(session, username="sandbox", sender=None, base=None):
    return AfricasTalkingSmsGateway(username=username, api_key="at-key-123", sender_id=sender, session=session,
                                    api_base_url=base)


def test_request_shape_sandbox_and_live_hosts():
    session = FakeSession(FakeResponse(201, recipients(101, "Success")))
    result = gateway(session, sender="FUNDBRIDGE").send("+254712345678", "Hello “Amina” …")
    call = session.calls[0]
    assert call["url"] == "https://api.sandbox.africastalking.com/version1/messaging"
    assert call["headers"] == {"apiKey": "at-key-123", "Accept": "application/json"}
    assert call["data"] == {"username": "sandbox", "to": "+254712345678", "message": 'Hello "Amina" ...',
                            "from": "FUNDBRIDGE"}
    assert call["timeout"] == 10.0
    assert result.status == "submitted" and result.message_id == "ATXid_1"

    live = gateway(FakeSession(FakeResponse(201, recipients(101, "Success"))), username="fundbridge")
    assert live.url == "https://api.africastalking.com/version1/messaging" and live.mode == "africastalking_live"
    assert gateway(FakeSession(), base="http://127.0.0.1:8099/").url == "http://127.0.0.1:8099/version1/messaging"


def test_long_messages_are_capped_at_two_segments():
    session = FakeSession(FakeResponse(201, recipients(101, "Success")))
    gateway(session).send("+254712345678", "word " * 200)
    assert len(session.calls[0]["data"]["message"]) <= SMS_MAX_CHARS


@pytest.mark.parametrize("code, status", [(100, "Processed"), (101, "Success"), (102, "Queued")])
def test_accepted_status_codes_are_submitted_not_delivered(code, status):
    result = gateway(FakeSession(FakeResponse(201, recipients(code, status)))).send("+254712345678", "x")
    assert result.status == "submitted"  # accepted by the gateway; handset delivery is unknown


@pytest.mark.parametrize("code, status", [
    (401, "RiskHold"), (402, "InvalidSenderId"), (403, "InvalidPhoneNumber"), (404, "UnsupportedNumberType"),
    (405, "InsufficientBalance"), (406, "UserInBlacklist"), (407, "CouldNotRoute"), (409, "DoNotDisturbRejection"),
    (500, "InternalServerError"), (501, "GatewayError"), (502, "RejectedByGateway"),
])
def test_rejected_status_codes_fail_with_reason(code, status):
    result = gateway(FakeSession(FakeResponse(201, recipients(code, status)))).send("+254712345678", "x")
    assert result.status == "failed" and result.detail == status


@pytest.mark.parametrize("response, detail", [
    (FakeResponse(401, text="The supplied authentication is invalid"), "http_401"),
    (FakeResponse(500, text="error"), "http_500"),
    (FakeResponse(201, None, text="<html>proxy</html>"), "unexpected_response"),
    (FakeResponse(201, {"SMSMessageData": {"Message": "InvalidSenderId", "Recipients": []}}), "unexpected_response"),
])
def test_http_and_body_errors_fail_safely(response, detail):
    result = gateway(FakeSession(response)).send("+254712345678", "x")
    assert result.status == "failed" and result.detail == detail


@pytest.mark.parametrize("exc", [requests.Timeout("slow"), requests.ConnectionError("refused")])
def test_network_errors_fail_without_raising(exc):
    result = gateway(FakeSession(exc=exc)).send("+254712345678", "x")
    assert result.status == "failed" and result.detail == "network_error"


def test_requires_credentials():
    with pytest.raises(ValueError):
        AfricasTalkingSmsGateway(username="", api_key="k")
    with pytest.raises(ValueError):
        AfricasTalkingSmsGateway(username="sandbox", api_key="")
