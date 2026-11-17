"""Regression: reviewing a payout that does not exist returns the 404 envelope, not a 500.

The row-locked lookup added to ``review_payout`` in 941766c calls ``abort(404)`` but ``abort`` was not
imported, so the request raised ``NameError`` and returned ``500 INTERNAL_ERROR``.
"""
import uuid

import pytest
from flask_jwt_extended import create_access_token

from app.extensions import db
from app.models.core import AuditLog, FinancialLedgerEntry, Role, User


def _reviewer_token(app):
    with app.app_context():
        reviewer = User(email="missing-payout-reviewer@test", role=Role.reviewer)
        reviewer.set_password("x" * 12)
        db.session.add(reviewer)
        db.session.commit()
        return create_access_token(identity=reviewer.id)


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_reviewing_a_missing_payout_returns_404_and_changes_nothing(app, client, decision):
    auth = _reviewer_token(app)
    response = client.post(f"/api/v1/payouts/{uuid.uuid4()}/review",
                           headers={"Authorization": f"Bearer {auth}"}, json={"decision": decision})
    assert response.status_code == 404, response.get_json()
    assert response.get_json()["error"]["code"] == "NOT_FOUND"
    with app.app_context():
        assert AuditLog.query.filter(AuditLog.action.like("payout.%")).count() == 0
        assert FinancialLedgerEntry.query.count() == 0
