"""The product's role journeys chained end to end over HTTP against gunicorn, with a redacted evidence transcript.

What is real here: the FundBridge server (gunicorn), migrations, PostgreSQL or SQLite, JWT auth, the ledger, the
USSD/SMS callback handling and the AI service. What is a local double: PayPal Orders v2 and webhook verification,
and OpenAI (see provider_doubles.py). SMS goes to the labelled simulated outbox. None of this proves a live provider.

Set FUNDBRIDGE_EVIDENCE_DIR to write the transcript (method, path, status, selected response fields; no tokens,
e-mail addresses or full phone numbers) to <dir>/journeys.md.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

import sqlalchemy as sa

from .provider_doubles import VALID_WEBHOOK_SIGNATURE
from .test_journeys import _err, _funds, _ok, _phone, _verify

PIN = "4826"


def _redact(text: str) -> str:
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", "[EMAIL]", text)
    return re.sub(r"(\+|%2B)?254\d{6}(\d{3})", r"+254******\2", text)


class Evidence:
    def __init__(self, live):
        self.live, self.lines, self.section = live, [], None

    def step(self, title: str) -> None:
        self.lines.append(f"\n### {title}\n")

    def call(self, label: str, method: str, path: str, token=None, keep=(), **kwargs):
        res = self.live.call(method, path, token, **kwargs)
        shown = _redact(re.sub(r"token=[^&]+", "token=[REDACTED]", path))
        summary = ""
        try:
            body = res.json()
            data = body.get("data", body.get("error"))
            if isinstance(data, list):
                summary = f"{len(data)} item(s)"
                if keep and data:
                    summary += ": " + json.dumps([{k: d.get(k) for k in keep if k in d} for d in data[:3]])
            elif isinstance(data, dict):
                picked = {k: data[k] for k in (keep or ("code", "status")) if k in data}
                summary = json.dumps(picked, ensure_ascii=False)
            if isinstance(body.get("meta"), dict) and body["meta"]:
                meta = {k: v for k, v in body["meta"].items() if k in ("provider", "ai_generated", "degraded",
                        "fallback_reason", "output_replaced_by_guardrail", "simulated", "total", "page")}
                if meta:
                    summary += f" meta={json.dumps(meta)}"
        except ValueError:
            summary = repr(res.text[:120])
        summary = _redact(summary)
        self.lines.append(f"- {label}: `{method} {shown}` -> **{res.status_code}** {summary}")
        return res

    def write(self) -> None:
        target = os.environ.get("FUNDBRIDGE_EVIDENCE_DIR")
        if not target:
            return
        path = Path(target)
        path.mkdir(parents=True, exist_ok=True)
        header = (
            "# FundBridge journey evidence (generated)\n\n"
            f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} by "
            "`backend/tests/e2e/test_product_journeys.py` against a live gunicorn server.\n\n"
            "**Real:** the FundBridge API, database, auth, ledger, USSD/SMS callback handling and AI service.\n"
            "**Local doubles:** PayPal (Orders v2, webhook verification) and OpenAI. SMS goes to the labelled simulated "
            "outbox. This transcript does not prove any live provider integration.\n\n"
            "Tokens, e-mail addresses and full phone numbers are not recorded.\n"
        )
        (path / "journeys.md").write_text(header + "\n".join(self.lines) + "\n")


def test_role_journeys_end_to_end(live):
    ev = Evidence(live)
    token = live.callback_token()
    admin = live.admin_token

    # ------------------------------------------------------------------ creator
    ev.step("Creator: register, get the creator role, AI draft, edit, create, submit")
    creator = live.account("creator")
    agent, reviewer = live.account("agent"), live.account("reviewer")
    beneficiary = live.account("beneficiary")
    ev.lines.append("- Creator, agent, reviewer and beneficiary accounts: each registered through `POST /api/v1/auth/register` "
                    "(always a donor), then given its role by the admin through `PUT /api/v1/admin/users/{id}/role`")
    phone = _phone()
    profile = _ok(ev.call("Agent onboards the beneficiary", "POST", "/api/v1/beneficiaries", agent["token"],
                          keep=("verification_status",), json={
                              "user_id": beneficiary["id"], "display_name": "Neema", "phone_number": phone,
                              "country_code": "KE", "preferred_language": "sw",
                              "payout_destination_reference": "tok_e2e_neema"}), 201)
    _verify(live, reviewer, profile["id"])
    ev.lines.append("- Reviewer verifies the beneficiary profile (revision-checked): verified")
    notes = ("Neema runs a tailoring stall in Kisumu (call +254700111222). A fire destroyed her two sewing machines "
             "and she needs replacements to keep supporting her children.")
    draft = _ok(ev.call("AI campaign draft (phone number redacted before the model call)", "POST",
                        "/api/v1/ai/campaign-draft", creator["token"], keep=("title", "requires_human_review"),
                        json={"story_notes": notes, "category": "small_business", "language": "en",
                              "goal": {"amount": "600.00", "currency": "USD"}}))
    assert "+254700111222" not in json.dumps(live.openai.bodies[-1])
    word = "Tailor" + uuid.uuid4().hex[:5]
    edited_story = draft["story"] + " Funds buy two sewing machines and thread."  # the creator edits the suggestion
    campaign = _ok(ev.call("Creator saves the edited draft as a campaign", "POST", "/api/v1/campaigns",
                           creator["token"], keep=("status", "review_status"), json={
                               "beneficiary_id": profile["id"], "title": f"{word}: sewing machines for Neema",
                               "slug": f"e2e-{uuid.uuid4().hex[:10]}", "description": edited_story,
                               "category": "small_business", "goal_amount": "600.00", "goal_currency": "USD"}), 201)
    cid = campaign["id"]
    _ok(ev.call("Creator submits for review", "POST", f"/api/v1/campaigns/{cid}/submit", creator["token"],
                keep=("status", "review_status")))

    # ------------------------------------------------------------------ reviewer
    ev.step("Reviewer: paginated queue, inspect, reject, resubmission, approve, audit trail")
    _err(ev.call("A donor cannot open the review queue", "GET", "/api/v1/campaigns/review-queue", live.account("donor")["token"]),
         403, "FORBIDDEN")
    queue_ids, page = [], 1
    while True:
        res = ev.call(f"Review queue page {page}", "GET", f"/api/v1/campaigns/review-queue?page={page}&page_size=5",
                      reviewer["token"])
        body = res.json()
        queue_ids += [c["id"] for c in body["data"]]
        if page * 5 >= body["meta"]["total"]:
            break
        page += 1
    assert cid in queue_ids
    detail = _ok(ev.call("Reviewer inspects the campaign", "GET", f"/api/v1/campaigns/{cid}", reviewer["token"],
                         keep=("status", "beneficiary_id")))
    assert detail["beneficiary_id"] == profile["id"]
    _ok(ev.call("Reviewer rejects", "POST", f"/api/v1/campaigns/{cid}/review", reviewer["token"],
                keep=("status", "review_status"), json={"decision": "reject"}))
    _ok(ev.call("Creator edits and resubmits", "POST", f"/api/v1/campaigns/{cid}/submit", creator["token"],
                keep=("status",)))
    published = _ok(ev.call("Reviewer approves", "POST", f"/api/v1/campaigns/{cid}/review", reviewer["token"],
                            keep=("status", "review_status"), json={"decision": "approve"}))
    assert published["status"] == "published"
    assert cid not in [c["id"] for c in _ok(live.call("GET", "/api/v1/campaigns/review-queue", reviewer["token"]))]
    engine = sa.create_engine(live.env["DATABASE_URL"])
    with engine.connect() as conn:
        actions = [r.action for r in conn.execute(sa.text(
            "SELECT action FROM audit_log WHERE resource_id = :id ORDER BY created_at"), {"id": cid})]
    assert actions[0] == "campaign.created" and "campaign.review_reject" in actions and "campaign.review_approve" in actions
    ev.lines.append(f"- Audit trail for the campaign (from `audit_log`): {', '.join(actions)}")

    # ------------------------------------------------------------------ donor
    ev.step("Donor: AI discovery, read the story, PayPal order, approve, capture, signed webhook replay, history")
    donor = live.account("donor")
    found = _ok(ev.call("AI campaign search", "POST", "/api/v1/ai/campaign-search",
                        keep=("filters_relaxed",), json={"query": f"{word} sewing machines"}))
    assert cid in [c["id"] for c in found["results"]] or cid in [
        c["id"] for c in _ok(live.call("GET", f"/api/v1/campaigns?q={word}"))]
    story = _ok(ev.call("Donor reads the public campaign", "GET", f"/api/v1/campaigns/{cid}", donor["token"],
                        keep=("status", "raised")))
    assert "beneficiary_id" not in story and story["raised"]["amount"] == "0.00"
    order = _ok(ev.call("Donation order (PayPal Orders v2 double)", "POST", "/api/v1/donations/orders", donor["token"],
                        keep=("status",), headers={"Idempotency-Key": uuid.uuid4().hex},
                        json={"campaign_id": cid, "amount": "45.00", "currency": "USD",
                              "return_url": "http://localhost:3000/return", "cancel_url": "http://localhost:3000/cancel"}),
                201)
    order_id = order["approval_url"].split("token=")[1]
    explained = _ok(ev.call("AI explains the pending donation", "POST", "/api/v1/ai/status-explanation", donor["token"],
                            keep=("status", "confirmed"), json={"kind": "donation", "id": order["id"]}))
    assert explained["status"] == "pending" and explained["confirmed"] is False
    live.paypal.approve(order_id)
    ev.lines.append("- Donor approves the order at the PayPal double")
    done = _ok(ev.call("Server-side capture", "POST", f"/api/v1/donations/{order['id']}/capture", donor["token"],
                       keep=("status",)))
    assert done["status"] == "completed"
    capture_id = live.paypal.orders[order_id]["capture"]["id"]  # the id PayPal issued for this capture

    def webhook(resource_id):
        return {"id": "WH-EVT-" + uuid.uuid4().hex[:10], "event_type": "PAYMENT.CAPTURE.COMPLETED",
                "resource": {"id": resource_id, "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "45.00"},
                             "supplementary_data": {"related_ids": {"order_id": order_id}}}}

    signed = {"PAYPAL-AUTH-ALGO": "SHA256withRSA", "PAYPAL-CERT-URL": "https://api.sandbox.paypal.com/cert",
              "PAYPAL-TRANSMISSION-ID": uuid.uuid4().hex, "PAYPAL-TRANSMISSION-TIME": "2026-11-11T10:00:00Z",
              "PAYPAL-TRANSMISSION-SIG": VALID_WEBHOOK_SIGNATURE}
    event = webhook(capture_id)
    for attempt in ("Signed webhook for the same capture", "Same webhook event delivered again"):
        assert ev.call(attempt, "POST", "/api/v1/webhooks/paypal", json=event, headers=signed).status_code == 204
    other = ev.call("Signed webhook naming a different capture for the completed order (refused)", "POST",
                    "/api/v1/webhooks/paypal", json=webhook("CAP-OTHER-" + uuid.uuid4().hex[:6]), headers=signed)
    assert other.status_code == 400
    assert _funds(live, cid)["raised"] == "45.00"  # credited exactly once
    ev.lines.append("- Ledger-backed campaign total after capture and two webhook deliveries: 45.00 USD (one credit)")
    assert _ok(live.call("GET", f"/api/v1/campaigns/{cid}"))["raised"]["amount"] == "45.00"
    history = _ok(ev.call("Donation history", "GET", "/api/v1/me/donations", donor["token"], keep=("status", "amount")))
    assert [d["status"] for d in history if d["id"] == order["id"]] == ["completed"]
    explained = _ok(ev.call("AI explains the confirmed donation", "POST", "/api/v1/ai/status-explanation",
                            donor["token"], keep=("status", "confirmed", "campaign_raised"),
                            json={"kind": "donation", "id": order["id"], "language": "sw"}))
    assert explained["confirmed"] is True and explained["campaign_raised"]["amount"] == "45.00"

    # ------------------------------------------------------------------ beneficiary
    ev.step("Beneficiary: own campaigns, USSD (Africa's Talking callback format), PIN, payout, SMS, status")
    mine = _ok(ev.call("Beneficiary lists own campaigns", "GET", "/api/v1/beneficiaries/me/campaigns",
                       beneficiary["token"], keep=("status", "raised")))
    assert [c["id"] for c in mine] == [cid]

    def ussd(label, text, session):
        res = ev.call(label, "POST", f"/api/v1/messaging/ussd?token={token}", data={
            "sessionId": session, "serviceCode": "*384*123#", "phoneNumber": phone, "text": text})
        assert res.status_code == 200 and res.headers["Content-Type"].startswith("text/plain")
        return res.text

    assert ev.call("USSD callback without the shared secret", "POST", "/api/v1/messaging/ussd",
                   data={"phoneNumber": phone, "text": ""}).status_code == 403
    session = "ATUid_" + uuid.uuid4().hex[:8]
    assert ussd("USSD dial (Kiswahili profile)", "", session).startswith("CON FundBridge")
    status_screen = ussd("USSD 1: campaign status", "1", session)
    assert "45.00" in status_screen
    session = "ATUid_" + uuid.uuid4().hex[:8]
    assert ussd("USSD 2: create PIN", "2", session).startswith("CON ")
    assert ussd("USSD 2: PIN entered twice", f"2*{PIN}*{PIN}", session).startswith("END ")
    payout = _ok(ev.call("Beneficiary requests a payout", "POST", "/api/v1/payouts", beneficiary["token"],
                         keep=("status", "amount"), headers={"Idempotency-Key": uuid.uuid4().hex},
                         json={"campaign_id": cid, "beneficiary_id": profile["id"], "amount": "30.00", "currency": "USD"}),
                 201)
    _ok(ev.call("Reviewer approves the payout", "POST", f"/api/v1/payouts/{payout['id']}/review", reviewer["token"],
                keep=("status",), json={"decision": "approve"}))
    screen = ussd("USSD 2: payout status behind the PIN", f"2*{PIN}", "ATUid_" + uuid.uuid4().hex[:8])
    assert "30.00" in screen and "Yameidhinishwa" in screen  # Kiswahili: approved, being prepared (not paid)
    outbox = ev.call("Simulated SMS outbox (labelled simulated)", "GET",
                     f"/api/v1/messaging/simulator/outbox?phone_number={phone}")
    messages = [m["message"] for m in outbox.json()["data"]]
    assert outbox.json()["meta"]["simulated"] is True
    assert any("45.00" in m for m in messages) and any("Yameidhinishwa" in m for m in messages)
    ev.lines.append(f"- {len(messages)} simulated SMS for this number, including the confirmed donation (45.00) and the "
                    "payout approval (Kiswahili 'Yameidhinishwa'); none says the payout was paid")
    assert not any("Yamelipwa" in m for m in messages)
    explained = _ok(ev.call("AI explains the payout", "POST", "/api/v1/ai/status-explanation", beneficiary["token"],
                            keep=("status", "confirmed", "status_label"),
                            json={"kind": "payout", "id": payout["id"], "language": "sw"}))
    assert explained["status"] == "approved_for_submission" and explained["confirmed"] is False
    report = ev.call("SMS delivery report for an unknown id", "POST", f"/api/v1/messaging/sms/delivery?token={token}",
                     data={"id": "ATXid_unknown", "status": "Success", "phoneNumber": phone})
    assert report.status_code == 200

    # ------------------------------------------------------------------ admin and access control
    ev.step("Administrator and unauthorised access")
    _ok(ev.call("Admin finds an account", "GET", f"/api/v1/admin/users?email={beneficiary['email']}", admin))
    for who, tok in (("donor", donor["token"]), ("reviewer", reviewer["token"]), ("beneficiary", beneficiary["token"])):
        _err(ev.call(f"{who} cannot use user management", "PUT", f"/api/v1/admin/users/{donor['id']}/role", tok,
                     json={"role": "admin"}), 403, "FORBIDDEN")
    _err(ev.call("Another beneficiary cannot read this payout", "GET", f"/api/v1/payouts/{payout['id']}",
                 live.account("beneficiary", "stranger")["token"]), 403, "FORBIDDEN")
    _err(ev.call("Another donor cannot read this donation", "GET", f"/api/v1/donations/{order['id']}",
                 live.account("donor", "stranger")["token"]), 403, "FORBIDDEN")
    _err(ev.call("The beneficiary cannot approve their own payout", "POST", f"/api/v1/payouts/{payout['id']}/review",
                 beneficiary["token"], json={"decision": "approve"}), 403, "FORBIDDEN")
    _err(ev.call("Invalid token", "GET", "/api/v1/auth/me", "not-a-real-token"), 401, "INVALID_TOKEN")
    ev.write()
