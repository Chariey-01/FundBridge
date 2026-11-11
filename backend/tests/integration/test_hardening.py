"""Sign-in rate limits, request IDs, provider-failure and unexpected-error envelopes.

Regressions for H-1 (no sign-in throttling), H-2 (a PayPal HTTP error or timeout surfaced as Flask's
HTML 500 page; see test_provider_errors.py) and H-3 (unhandled exceptions returned HTML, without a
request ID to correlate logs).
"""

from __future__ import annotations

import logging

from app.models.core import Role

from .conftest import PASSWORD, auth, make_user


def _login(client, email, password):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def test_repeated_failed_logins_lock_the_account_temporarily(make_app):
    client = make_app(AUTH_LOGIN_FAILURES_PER_ACCOUNT=3).test_client()
    make_user("target@example.test", Role.donor)
    for _ in range(3):
        assert _login(client, "target@example.test", "wrong-password-123").status_code == 401
    blocked = _login(client, "TARGET@example.test", PASSWORD)  # correct password, different case
    assert blocked.status_code == 429 and blocked.get_json()["error"]["code"] == "RATE_LIMITED"
    assert int(blocked.headers["Retry-After"]) > 0
    # Other accounts are unaffected.
    make_user("other@example.test", Role.donor)
    assert _login(client, "other@example.test", PASSWORD).status_code == 200


def test_successful_login_resets_failure_count(make_app):
    client = make_app(AUTH_LOGIN_FAILURES_PER_ACCOUNT=3).test_client()
    make_user("user@example.test", Role.donor)
    for _ in range(2):
        _login(client, "user@example.test", "wrong-password-123")
    assert _login(client, "user@example.test", PASSWORD).status_code == 200
    for _ in range(2):
        assert _login(client, "user@example.test", "wrong-password-123").status_code == 401
    assert _login(client, "user@example.test", PASSWORD).status_code == 200


def test_per_ip_login_and_registration_limits(make_app):
    client = make_app(AUTH_LOGIN_LIMIT_PER_IP_PER_MINUTE=3, AUTH_REGISTER_LIMIT_PER_IP_PER_10_MINUTES=2).test_client()
    codes = [_login(client, f"nobody{i}@example.test", "wrong-password-123").status_code for i in range(4)]
    assert codes == [401, 401, 401, 429]
    reg = [client.post("/api/v1/auth/register", json={"email": f"r{i}@example.test", "password": PASSWORD}).status_code
           for i in range(3)]
    assert reg == [201, 201, 429]


def test_request_id_is_returned_and_sanitised(client):
    generated = client.get("/health").headers["X-Request-ID"]
    assert len(generated) == 32
    assert client.get("/health", headers={"X-Request-ID": "trace-1234abcd"}).headers["X-Request-ID"] == "trace-1234abcd"
    forged = client.get("/health", headers={"X-Request-ID": "x<script>"}).headers["X-Request-ID"]
    assert forged != "x<script>" and len(forged) == 32


def test_access_log_omits_query_strings(client, caplog):
    with caplog.at_level(logging.INFO, logger="fundbridge.http"):
        client.get("/api/v1/campaigns?q=private-search-term")
    lines = [r.getMessage() for r in caplog.records if r.name == "fundbridge.http"]
    assert lines and "private-search-term" not in " ".join(lines) and "path=/api/v1/campaigns" in lines[-1]


def test_unexpected_error_returns_envelope_with_request_id(client, seeded, monkeypatch):
    from app.api.v1 import routes

    monkeypatch.setattr(routes, "serialize_campaign", lambda c: 1 / 0)
    res = client.get("/api/v1/campaigns", headers={"X-Request-ID": "corr-00000001"})
    body = res.get_json()["error"]
    assert res.status_code == 500 and body["code"] == "INTERNAL_ERROR"
    assert body["details"]["request_id"] == "corr-00000001" and "ZeroDivision" not in res.get_data(as_text=True)


def test_method_not_allowed_uses_envelope(client):
    res = client.delete("/api/v1/campaigns")
    assert res.status_code == 405 and res.get_json()["error"]["code"] == "METHOD_NOT_ALLOWED"


def test_core_validation_errors_unchanged(client, seeded):
    # The generic handlers must not swallow the core ValueError/PermissionError mapping.
    res = client.post("/api/v1/payouts", json={}, headers={**auth(client, "beneficiary@example.test"),
                                                            "Idempotency-Key": "v"})
    assert res.status_code == 400 and res.get_json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get("/api/v1/campaigns/missing").get_json()["error"]["code"] == "NOT_FOUND"
