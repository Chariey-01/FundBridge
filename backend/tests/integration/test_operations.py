"""Roles, beneficiary verification, campaign balances, keyword search, admin bootstrap.

Regression for journey gap G-1..G-4 (2026-11-11): no API could assign a non-donor role, verify
or re-verify a beneficiary, or report campaign balances, so the beneficiary, campaign and
payout journeys required direct database edits.
"""

from __future__ import annotations

from decimal import Decimal

from app.extensions import db
from app.models.core import AuditLog, BeneficiaryProfile, Campaign, CampaignStatus, Role, User

from .conftest import PASSWORD, auth, make_user
from .test_financial_security import fund, request_payout


def _profile(client, profile_id, email="reviewer@example.test"):
    return client.get(f"/api/v1/beneficiaries/{profile_id}", headers=auth(client, email)).get_json()["data"]


def _decide(client, profile_id, decision, revision, email="reviewer@example.test"):
    return client.post(f"/api/v1/beneficiaries/{profile_id}/verification",
                       json={"decision": decision, "revision": revision}, headers=auth(client, email))


# ------------------------------------------------------------------------- roles


def test_admin_assigns_roles_and_change_is_audited_and_immediate(client, seeded):
    client.post("/api/v1/auth/register", json={"email": "new@example.test", "password": PASSWORD})
    donor_token = auth(client, "new@example.test")
    assert client.post("/api/v1/campaigns", json={}, headers=donor_token).status_code == 403

    admin = auth(client, "admin@example.test")
    found = client.get("/api/v1/admin/users?email=NEW@example.test", headers=admin).get_json()["data"]
    assert [u["role"] for u in found] == ["donor"]
    res = client.put(f"/api/v1/admin/users/{found[0]['id']}/role", json={"role": "creator"}, headers=admin)
    assert res.status_code == 200 and res.get_json()["data"]["role"] == "creator"
    audit = AuditLog.query.filter_by(action="user.role_changed", resource_id=found[0]["id"]).one()
    assert audit.metadata_json == {"from": "donor", "to": "creator"}
    # Role is read from the database on each request, so the existing token now has creator rights.
    assert client.post("/api/v1/campaigns", json={}, headers=donor_token).status_code == 400


def test_role_assignment_guards(client, seeded):
    admin_id = User.query.filter_by(email="admin@example.test").one().id
    creator_id = User.query.filter_by(email="creator@example.test").one().id
    admin = auth(client, "admin@example.test")
    assert client.put(f"/api/v1/admin/users/{admin_id}/role", json={"role": "donor"}, headers=admin).status_code == 403
    assert client.put(f"/api/v1/admin/users/{creator_id}/role", json={"role": "superuser"},
                      headers=admin).get_json()["error"]["code"] == "VALIDATION_ERROR"
    reviewer = auth(client, "reviewer@example.test")
    assert client.put(f"/api/v1/admin/users/{creator_id}/role", json={"role": "admin"},
                      headers=reviewer).status_code == 403
    assert client.get("/api/v1/admin/users?email=creator@example.test", headers=reviewer).status_code == 403


def test_creator_can_lookup_campaign_beneficiaries_without_private_fields(client, seeded):
    creator = auth(client, "creator@example.test")
    result = client.get("/api/v1/beneficiaries/lookup?q=Amina", headers=creator)
    assert result.status_code == 200
    row = result.get_json()["data"]
    assert row == [{"id": seeded["beneficiary"].id, "display_name": "Amina", "country_code": "KE",
                    "verification_status": "verified"}]
    assert client.get("/api/v1/beneficiaries/lookup", headers=auth(client, "beneficiary@example.test")).status_code == 403


# --------------------------------------------------------- beneficiary verification


def test_onboarding_verification_and_reverification_journey(client, seeded):
    admin = auth(client, "admin@example.test")
    user = make_user("wanjiru@example.test", Role.donor)
    client.put(f"/api/v1/admin/users/{user.id}/role", json={"role": "beneficiary"}, headers=admin)
    created = client.post("/api/v1/beneficiaries", headers=auth(client, "agent@example.test"), json={
        "user_id": user.id, "display_name": "Wanjiru", "phone_number": "+254711000222", "country_code": "KE",
        "payout_destination_reference": "tok_wanjiru"}).get_json()["data"]
    assert created["verification_status"] == "unverified"

    pending = client.get("/api/v1/beneficiaries?verification_status=unverified",
                         headers=auth(client, "reviewer@example.test")).get_json()["data"]
    row = next(p for p in pending if p["id"] == created["id"])
    assert row["has_payout_destination"] is True and "payout_destination_reference" not in row

    # An agent onboards but cannot verify.
    assert _decide(client, created["id"], "verify", row["revision"], "agent@example.test").status_code == 403
    res = _decide(client, created["id"], "verify", row["revision"])
    assert res.status_code == 200 and res.get_json()["data"]["verification_status"] == "verified"

    # Beneficiary changes the payout destination: back to reverification, and the old review is stale.
    stale = res.get_json()["data"]["revision"]
    client.patch("/api/v1/beneficiaries/me", json={"payout_destination_reference": "tok_new"},
                 headers=auth(client, "wanjiru@example.test"))
    assert _profile(client, created["id"])["verification_status"] == "reverification_required"
    conflict = _decide(client, created["id"], "verify", stale)
    assert conflict.status_code == 409 and conflict.get_json()["error"]["code"] == "PROFILE_CHANGED"
    assert _profile(client, created["id"])["verification_status"] == "reverification_required"

    fresh = _profile(client, created["id"])["revision"]
    assert _decide(client, created["id"], "verify", fresh).get_json()["data"]["verification_status"] == "verified"
    actions = [a.action for a in AuditLog.query.filter_by(resource_id=created["id"]).order_by(AuditLog.created_at)]
    assert actions.count("beneficiary.verified") == 2 and "beneficiary.payout_destination_changed" in actions


def test_rejected_beneficiary_cannot_request_payout(client, seeded):
    profile = seeded["beneficiary"]
    res = _decide(client, profile.id, "reject", _profile(client, profile.id)["revision"])
    assert res.get_json()["data"]["verification_status"] == "rejected"
    fund(seeded["campaign"], "50.00", "rej")
    assert request_payout(client, seeded, "10.00", "rej").get_json()["error"]["code"] == "BENEFICIARY_NOT_VERIFIED"


def test_nobody_verifies_their_own_profile(client, seeded):
    reviewer = User.query.filter_by(email="reviewer@example.test").one()
    own = BeneficiaryProfile(user_id=reviewer.id, display_name="Self", phone_number="+254700111222", country_code="KE")
    db.session.add(own)
    db.session.commit()
    res = _decide(client, own.id, "verify", _profile(client, own.id)["revision"])
    assert res.status_code == 403 and res.get_json()["error"]["code"] == "SELF_VERIFICATION_FORBIDDEN"
    assert db.session.get(BeneficiaryProfile, own.id).verification_status == "unverified"


# --------------------------------------------------------------- campaign balances


def test_balances_come_from_the_ledger_and_reconcile(client, seeded):
    campaign = seeded["campaign"]
    fund(campaign, "100.00", "bal-1")
    fund(campaign, "20.00", "bal-2")
    kept = request_payout(client, seeded, "30.00", "bal-p1").get_json()["data"]
    dropped = request_payout(client, seeded, "15.00", "bal-p2").get_json()["data"]
    client.post(f"/api/v1/payouts/{dropped['id']}/review", json={"decision": "reject"},
                headers=auth(client, "reviewer@example.test"))

    public = client.get(f"/api/v1/campaigns/{campaign.id}/funds").get_json()["data"]
    assert public["visibility"] == "public" and public["balance"] == {"currency": "USD", "raised": "120.00"}

    for email in ("creator@example.test", "beneficiary@example.test", "reviewer@example.test"):
        full = client.get(f"/api/v1/campaigns/{campaign.id}/funds", headers=auth(client, email)).get_json()["data"]
        bal = full["balance"]
        assert full["visibility"] == "full", email
        assert bal == {"currency": "USD", "raised": "120.00", "reserved_for_payouts": "30.00",
                       "paid_out": "0.00", "available": "90.00"}, email
        assert Decimal(bal["raised"]) == Decimal(bal["available"]) + Decimal(bal["reserved_for_payouts"]) + \
            Decimal(bal["paid_out"])
    assert kept["status"] == "requested"


def test_unpublished_campaign_balance_is_private(client, seeded):
    campaign = seeded["campaign"]
    campaign.status = CampaignStatus.draft
    db.session.commit()
    res = client.get(f"/api/v1/campaigns/{campaign.id}/funds")
    assert res.status_code == 401 and res.get_json()["error"]["code"] == "AUTH_REQUIRED"
    make_user("stranger@example.test", Role.donor)
    assert client.get(f"/api/v1/campaigns/{campaign.id}/funds",
                      headers=auth(client, "stranger@example.test")).status_code == 403
    assert client.get(f"/api/v1/campaigns/{campaign.id}/funds",
                      headers=auth(client, "creator@example.test")).status_code == 200


# ------------------------------------------------------------------ keyword search


def test_keyword_search_without_ai(client, seeded):
    other = Campaign(creator_id=seeded["campaign"].creator_id, beneficiary_id=seeded["beneficiary"].id,
                     title="Clinic roof repair", slug="clinic-roof", description="Iron sheets for the village clinic.",
                     category="medical", goal_amount=Decimal("900"), goal_currency="USD", status=CampaignStatus.published)
    db.session.add(other)
    db.session.commit()
    titles = lambda q: [c["title"] for c in client.get(f"/api/v1/campaigns?q={q}").get_json()["data"]]  # noqa: E731
    assert titles("SCHOOL") == ["School fees for Amina"]
    assert titles("iron%20sheets") == ["Clinic roof repair"]
    assert titles("%25") == []  # a literal %, not a wildcard
    assert titles("_") == []
    assert len(titles("")) == 2


# ------------------------------------------------------------------- admin bootstrap


def test_create_admin_cli(app):
    runner = app.test_cli_runner()
    short = runner.invoke(args=["fundbridge-admin", "create-admin", "--email", "ops@example.test"],
                          env={"FUNDBRIDGE_ADMIN_PASSWORD": "short"})
    assert short.exit_code != 0 and User.query.filter_by(email="ops@example.test").first() is None

    ok = runner.invoke(args=["fundbridge-admin", "create-admin", "--email", "ops@example.test"],
                       env={"FUNDBRIDGE_ADMIN_PASSWORD": "a-long-operator-password"})
    assert ok.exit_code == 0, ok.output
    assert "a-long-operator-password" not in ok.output
    user = User.query.filter_by(email="ops@example.test").one()
    assert user.role == Role.admin and user.check_password("a-long-operator-password")
    assert AuditLog.query.filter_by(action="user.admin_created_by_operator", resource_id=user.id).count() == 1

    again = runner.invoke(args=["fundbridge-admin", "create-admin", "--email", "ops@example.test"],
                          env={"FUNDBRIDGE_ADMIN_PASSWORD": "a-long-operator-password"})
    assert again.exit_code != 0 and "--promote-existing" in again.output
