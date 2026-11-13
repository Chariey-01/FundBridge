"""G-6 and G-7 as implemented by Codex in feat/backend-core 967781d, checked against the seeded demo data.

G-6  GET /api/v1/beneficiaries/me/campaigns  (beneficiary only)  -> the caller's campaigns, every status, paginated.
G-7  GET /api/v1/campaigns/review-queue       (reviewer, admin)   -> submitted campaigns awaiting review, oldest first.

These were proposed as strict xfails (the earlier shape was ``GET /campaigns?status=submitted`` for G-7); Codex chose
``/campaigns/review-queue``, so the tests and ``contracts/`` follow that shape.
"""

from __future__ import annotations

import json

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


def test_g6_beneficiary_lists_only_their_own_campaigns_without_private_profile_data(client, demo):
    res = client.get("/api/v1/beneficiaries/me/campaigns", headers=_auth(client, "demo-beneficiary"))
    assert res.status_code == 200
    body = res.get_json()
    assert sorted(c["slug"] for c in body["data"]) == ["demo-library-draft", "demo-school-fees-amina"]
    assert body["meta"] == {"page": 1, "page_size": 20, "total": 2}
    for item in body["data"]:
        assert item["raised"] == {"amount": "0.00", "currency": "USD"}  # plain seed: no money
    raw = json.dumps(body)
    for private in ("+2547", "254712345678", "demo-simulator-wallet", "payout_destination"):
        assert private not in raw

    other = client.get("/api/v1/beneficiaries/me/campaigns", headers=_auth(client, "demo-beneficiary-sw"))
    assert sorted(c["slug"] for c in other.get_json()["data"]) == ["demo-clinic-roof", "demo-water-tank"]
    for role in ("demo-donor", "demo-creator", "demo-reviewer", "demo-agent"):
        assert client.get("/api/v1/beneficiaries/me/campaigns", headers=_auth(client, role)).status_code == 403
    assert client.get("/api/v1/beneficiaries/me/campaigns").status_code == 401


def test_g7_review_queue_is_staff_only_and_public_listing_unchanged(client, demo):
    res = client.get("/api/v1/campaigns/review-queue", headers=_auth(client, "demo-reviewer"))
    assert res.status_code == 200
    assert [c["slug"] for c in res.get_json()["data"]] == ["demo-water-tank"]
    assert res.get_json()["meta"]["total"] == 1 and "submitted_at" in res.get_json()["data"][0]
    assert client.get("/api/v1/campaigns/review-queue", headers=_auth(client, "demo-admin")).status_code == 200
    for role in ("demo-donor", "demo-creator", "demo-beneficiary", "demo-agent"):
        assert client.get("/api/v1/campaigns/review-queue", headers=_auth(client, role)).status_code == 403
    assert client.get("/api/v1/campaigns/review-queue").status_code == 401
    assert client.get("/api/v1/campaigns/review-queue?page=x", headers=_auth(client, "demo-reviewer")).status_code == 400
    public = sorted(c["slug"] for c in client.get("/api/v1/campaigns").get_json()["data"])
    assert public == ["demo-clinic-roof", "demo-school-fees-amina"]
    # The public listing ignores an attempted status filter; drafts and submitted campaigns stay hidden.
    assert sorted(c["slug"] for c in client.get("/api/v1/campaigns?status=submitted").get_json()["data"]) == public


def test_public_campaign_detail_hides_beneficiary_id_and_tolerates_a_stale_token(client, demo):
    campaign = demo["demo-school-fees-amina"]
    public = client.get(f"/api/v1/campaigns/{campaign.id}").get_json()["data"]
    assert "beneficiary_id" not in public and public["raised"]["currency"] == "USD"
    stale = {"Authorization": "Bearer not-a-valid-token"}
    res = client.get(f"/api/v1/campaigns/{campaign.id}", headers=stale)
    assert res.status_code == 200 and "beneficiary_id" not in res.get_json()["data"]
    donor = client.get(f"/api/v1/campaigns/{campaign.id}", headers=_auth(client, "demo-donor")).get_json()["data"]
    assert "beneficiary_id" not in donor
    reviewer = client.get(f"/api/v1/campaigns/{campaign.id}", headers=_auth(client, "demo-reviewer")).get_json()["data"]
    assert reviewer["beneficiary_id"] == campaign.beneficiary_id
