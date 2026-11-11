"""Core, AI and messaging routes report authentication failures identically.

Regression for integration defect I-1 (2026-11-11): after the backend adopted AUTH_REQUIRED /
INVALID_TOKEN / TOKEN_EXPIRED (c3e4e3a), the AI and messaging routes still returned a single
AUTHENTICATION_REQUIRED code for every case. A client could not tell an expired session (re-login)
from a missing one, and had to handle two codes for the same condition.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from flask_jwt_extended import create_access_token

from app.extensions import db
from app.models.core import Role

from .conftest import make_user

DRAFT = {"story_notes": "My daughter needs school fees for her final year of secondary school in Kisumu.",
         "category": "education", "goal_amount": "300.00", "currency": "USD", "language": "en"}

PROTECTED = [
    ("get", "/api/v1/auth/me", None),                      # core
    ("post", "/api/v1/ai/campaign-draft", DRAFT),           # AI
    ("get", "/api/v1/messaging/support-requests", None),    # messaging staff route
]


def _call(client, method, path, body, headers):
    return getattr(client, method)(path, json=body, headers=headers) if body else getattr(client, method)(path, headers=headers)


@pytest.fixture()
def tokens(app):
    user = make_user("parity@example.test", Role.agent)
    inactive = make_user("inactive@example.test", Role.agent)
    inactive.status = "suspended"
    db.session.commit()
    return {
        "missing": {},
        "invalid": {"Authorization": "Bearer not-a-jwt"},
        "expired": {"Authorization": "Bearer " + create_access_token(identity=user.id, expires_delta=timedelta(seconds=-5))},
        "inactive": {"Authorization": "Bearer " + create_access_token(identity=inactive.id)},
    }


@pytest.mark.parametrize("case,status,code", [
    ("missing", 401, "AUTH_REQUIRED"),
    ("invalid", 401, "INVALID_TOKEN"),
    ("expired", 401, "TOKEN_EXPIRED"),
    ("inactive", 403, "ACCOUNT_INACTIVE"),
])
def test_auth_failures_match_across_core_ai_and_messaging(client, tokens, case, status, code):
    seen = {}
    for method, path, body in PROTECTED:
        res = _call(client, method, path, body, tokens[case])
        seen[path] = (res.status_code, (res.get_json() or {}).get("error", {}).get("code"))
    assert set(seen.values()) == {(status, code)}, seen


def test_public_ai_routes_treat_bad_tokens_as_anonymous(client, tokens):
    # Guest translation/search must keep working when a stale token is still in browser storage.
    res = client.post("/api/v1/ai/campaign-search", json={"query": "school fees"}, headers=tokens["expired"])
    assert res.status_code == 200
