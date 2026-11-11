"""PROPOSED API contracts for gaps that block the frontend's beneficiary and reviewer journeys.

Not implemented in the canonical backend (Codex owns it). These strict-xfail tests are the proposal in
executable form. When Codex implements the endpoints in this shape they XPASS: remove the markers. If
Codex chooses another shape, update these tests and contracts/ together. Spec: docs/integration/COORDINATION.md.

G-6  GET /api/v1/beneficiaries/me/campaigns  (beneficiary)  -> the caller's campaigns, every status.
     Without it the web payout form cannot discover a campaign_id.
G-7  GET /api/v1/campaigns?status=submitted   (reviewer, admin) -> the review queue.
     The public listing stays published-only; other callers asking for another status get 403.
"""

from __future__ import annotations

import pytest

from app.models.core import Campaign

PASSWORD = "demo-password-long-enough"


@pytest.fixture()
def demo(app):
    res = app.test_cli_runner().invoke(args=["fundbridge-demo", "seed"], env={"DEMO_PASSWORD": PASSWORD})
    assert res.exit_code == 0, res.output
    return {c.slug: c for c in Campaign.query}


def _auth(client, local):
    res = client.post("/api/v1/auth/login", json={"email": f"{local}@example.test", "password": PASSWORD})
    return {"Authorization": f"Bearer {res.get_json()['data']['access_token']}"}


@pytest.mark.xfail(strict=True, reason="GAP G-6 (proposed contract): GET /beneficiaries/me/campaigns does not exist")
def test_g6_beneficiary_lists_own_campaigns(client, demo):
    res = client.get("/api/v1/beneficiaries/me/campaigns", headers=_auth(client, "demo-beneficiary"))
    assert res.status_code == 200
    slugs = sorted(c["slug"] for c in res.get_json()["data"])
    assert slugs == ["demo-library-draft", "demo-school-fees-amina"]  # draft included: it is theirs
    other = client.get("/api/v1/beneficiaries/me/campaigns", headers=_auth(client, "demo-beneficiary-sw"))
    assert sorted(c["slug"] for c in other.get_json()["data"]) == ["demo-clinic-roof", "demo-water-tank"]
    assert client.get("/api/v1/beneficiaries/me/campaigns", headers=_auth(client, "demo-donor")).status_code == 403


@pytest.mark.xfail(strict=True, reason="GAP G-7 (proposed contract): GET /campaigns?status=submitted (review queue) "
                                       "does not exist; the listing ignores status")
def test_g7_reviewer_lists_submitted_campaigns(client, demo):
    res = client.get("/api/v1/campaigns?status=submitted", headers=_auth(client, "demo-reviewer"))
    assert res.status_code == 200
    assert [c["slug"] for c in res.get_json()["data"]] == ["demo-water-tank"]
    assert client.get("/api/v1/campaigns?status=submitted", headers=_auth(client, "demo-donor")).status_code == 403
    assert client.get("/api/v1/campaigns?status=submitted").status_code in (401, 403)
    public = sorted(c["slug"] for c in client.get("/api/v1/campaigns").get_json()["data"])
    assert public == ["demo-clinic-roof", "demo-school-fees-amina"]  # unchanged for everyone else
