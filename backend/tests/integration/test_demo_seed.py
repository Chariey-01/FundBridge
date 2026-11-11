"""`fundbridge-demo seed [--scenarios]`: reproducible, idempotent, labelled, ledger-consistent, silent."""

from __future__ import annotations

from collections import Counter

from app.extensions import db
from app.integrations.demo import DEMO_PHONE, DEMO_PHONE_SW
from app.models.core import Campaign, Donation, FinancialLedgerEntry, Payout, User

from .conftest import CALLBACK_TOKEN

PASSWORD = "demo-password-long-enough"


def _seed(app, *args, env=None):
    return app.test_cli_runner().invoke(args=["fundbridge-demo", "seed", *args],
                                        env={"DEMO_PASSWORD": PASSWORD, **(env or {})})


def _token(client, local):
    res = client.post("/api/v1/auth/login", json={"email": f"{local}@example.test", "password": PASSWORD})
    assert res.status_code == 200, res.get_json()
    return {"Authorization": f"Bearer {res.get_json()['data']['access_token']}"}


def test_scenarios_seed_is_idempotent_labelled_and_consistent(app, client):
    for _ in range(2):
        res = _seed(app, "--scenarios")
        assert res.exit_code == 0, res.output
    assert "not a PayPal payment" in res.output and PASSWORD in res.output

    assert User.query.filter(User.email.like("demo-%@example.test")).count() == 7
    assert Campaign.query.filter(Campaign.slug.like("demo-%")).count() == 4
    assert Donation.query.count() == 6 and Payout.query.count() == 3
    assert {d.provider for d in Donation.query} == {"demo_seed"}
    assert all(d.provider_order_id.startswith("DEMO-ORDER-") for d in Donation.query)
    assert Counter(e.entry_type for e in FinancialLedgerEntry.query) == \
        {"donation_completed": 5, "payout_reserved": 3, "payout_released": 1}

    creator = _token(client, "demo-creator")
    school = Campaign.query.filter_by(slug="demo-school-fees-amina").one()
    clinic = Campaign.query.filter_by(slug="demo-clinic-roof").one()
    school_funds = client.get(f"/api/v1/campaigns/{school.id}/funds", headers=creator).get_json()["data"]["balance"]
    clinic_funds = client.get(f"/api/v1/campaigns/{clinic.id}/funds", headers=creator).get_json()["data"]["balance"]
    assert school_funds == {"currency": "USD", "raised": "150.00", "reserved_for_payouts": "40.00", "paid_out": "0.00",
                            "available": "110.00"}
    assert clinic_funds == {"currency": "USD", "raised": "160.00", "reserved_for_payouts": "30.00", "paid_out": "0.00",
                            "available": "130.00"}

    donor_history = client.get("/api/v1/me/donations", headers=_token(client, "demo-donor")).get_json()["data"]
    assert Counter(d["status"] for d in donor_history) == {"completed": 5, "pending": 1}
    payouts = client.get("/api/v1/payouts", headers=_token(client, "demo-beneficiary")).get_json()["data"]
    assert sorted(p["status"] for p in payouts) == ["approved_for_submission", "rejected"]
    assert all(p.status.value != "succeeded" for p in Payout.query)  # demo money never claims a paid payout

    # Seeding sent nothing to the placeholder numbers.
    for phone in (DEMO_PHONE, DEMO_PHONE_SW):
        assert client.get(f"/api/v1/messaging/simulator/outbox?phone_number={phone}").get_json()["data"] == []


def test_seeded_data_drives_the_phone_demo_in_both_languages(app, client):
    assert _seed(app, "--scenarios").exit_code == 0

    def ussd(phone, text):
        return client.post(f"/api/v1/messaging/ussd?token={CALLBACK_TOKEN}",
                           data={"sessionId": "demo", "phoneNumber": phone, "text": text}).get_data(as_text=True)

    menu = ussd(DEMO_PHONE, "1")  # Amina has a draft and a published campaign, newest first
    assert menu.startswith("CON ") and "School fees for Amina (demo)" in menu
    assert "Raised: USD 150.00 of USD 400.00" in ussd(DEMO_PHONE, "1*2")
    ussd(DEMO_PHONE, "2*4826*4826")
    assert "Approved, being prepared" in ussd(DEMO_PHONE, "2*4826")
    assert ussd(DEMO_PHONE_SW, "").startswith("CON FundBridge\n1. Kampeni yangu")  # Kiswahili from the profile
    assert ussd(DEMO_PHONE_SW, "1").startswith("CON Chagua kampeni:")
    assert "Imechangiwa: USD 160.00" in ussd(DEMO_PHONE_SW, "1*2")


def test_plain_seed_creates_no_money_and_reviewer_has_work(app, client):
    assert _seed(app).exit_code == 0
    assert Donation.query.count() == 0 and Payout.query.count() == 0 and FinancialLedgerEntry.query.count() == 0
    statuses = Counter(c.status.value for c in Campaign.query)
    assert statuses == {"published": 2, "submitted": 1, "draft": 1}


def test_seed_refuses_production_and_short_passwords(app, monkeypatch):
    monkeypatch.setenv("FLASK_ENV", "production")
    res = _seed(app, "--scenarios")
    assert res.exit_code != 0 and "production" in res.output
    monkeypatch.delenv("FLASK_ENV")
    res = _seed(app, env={"DEMO_PASSWORD": "short"})
    assert res.exit_code != 0 and "12 characters" in res.output
    db.session.rollback()
    assert User.query.count() == 0
