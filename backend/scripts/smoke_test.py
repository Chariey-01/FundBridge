#!/usr/bin/env python3
"""Smoke test for a running FundBridge API (local, staging or the demo host).

    python scripts/smoke_test.py --base-url https://api.example --password "$DEMO_PASSWORD" \
        [--callback-token "$MESSAGING_CALLBACK_TOKEN"] [--try-donation]

Uses the accounts created by `flask fundbridge-demo seed --scenarios`. Read-only by default;
--try-donation also creates one pending donation order (and, with PayPal configured, one unapproved
sandbox order). Prints PASS / SKIP / FAIL per step and never prints tokens or passwords. Exit code 1 if
anything FAILs. SKIP means a provider is not configured or a feature is disabled. It is never success.
"""

from __future__ import annotations

import argparse
import sys
import uuid

import requests

ROLES = ("donor", "creator", "beneficiary", "reviewer", "admin", "agent")


class Smoke:
    def __init__(self, base: str, timeout: float = 20.0):
        self.base, self.timeout, self.results = base.rstrip("/"), timeout, []
        self.http = requests.Session()

    def call(self, method, path, token=None, **kw):
        headers = dict(kw.pop("headers", {}) or {})
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return self.http.request(method, self.base + path, headers=headers, timeout=self.timeout, **kw)

    def record(self, outcome: str, name: str, detail: str = "") -> None:
        self.results.append((outcome, name, detail))
        print(f"{outcome:<5} {name}" + (f" - {detail}" if detail else ""), flush=True)

    def step(self, name: str, fn) -> object:
        try:
            outcome, detail, value = fn()
        except Exception as exc:  # network errors, bad JSON, assertion-style failures
            self.record("FAIL", name, f"{type(exc).__name__}: {str(exc)[:160]}")
            return None
        self.record(outcome, name, detail)
        return value


def run(args) -> int:
    s = Smoke(args.base_url)

    def ok(res, *codes):
        if res.status_code not in (codes or (200,)):
            raise RuntimeError(f"HTTP {res.status_code}: {res.text[:160]}")
        return res.json().get("data") if res.content else None

    s.step("health", lambda: ("PASS", "", ok(s.call("GET", "/health"))))
    status = s.step("integration status", lambda: (lambda d: ("PASS", (
        f"ai={d['ai']['mode']} model_verified={d['ai'].get('model_verified')} sms={d['messaging']['sms']['mode']}"), d))(
        ok(s.call("GET", "/api/v1/integrations/status"))))
    config = s.step("public config", lambda: (lambda d: ("PASS", (
        f"paypal={d['payments']['paypal']['mode']} payouts={d['payouts']['mode']}"), d))(
        ok(s.call("GET", "/api/v1/public/config"))))

    tokens = {}
    for role in ROLES:
        email = f"{args.account_prefix}{role}@example.test"
        tokens[role] = s.step(f"sign in as {role}", lambda e=email: ("PASS", "", ok(s.call(
            "POST", "/api/v1/auth/login", json={"email": e, "password": args.password}))["access_token"]))

    campaigns = s.step("browse published campaigns", lambda: (lambda d: (
        "PASS" if d else "FAIL", f"{len(d)} published", d))(ok(s.call("GET", "/api/v1/campaigns"))))
    s.step("keyword search ?q=school", lambda: (lambda d: ("PASS", f"{len(d)} match(es)", d))(
        ok(s.call("GET", "/api/v1/campaigns?q=school"))))
    if campaigns:
        cid = campaigns[0]["id"]
        s.step("campaign balance (public, from the ledger)", lambda: (lambda d: (
            "PASS", f"raised {d['balance']['raised']} {d['balance']['currency']}", d))(
            ok(s.call("GET", f"/api/v1/campaigns/{cid}/funds"))))

    def ai_search():
        res = s.call("POST", "/api/v1/ai/campaign-search", json={"query": "school fees in Kenya"})
        body = ok(res)
        meta = res.json()["meta"]
        return "PASS", f"{len(body['results'])} result(s) via {'AI' if meta['ai_generated'] else 'keyword fallback'}", body
    s.step("AI natural-language search", ai_search)

    if tokens.get("creator"):
        def ai_draft():
            res = s.call("POST", "/api/v1/ai/campaign-draft", tokens["creator"], json={
                "story_notes": "My niece is in her final year of secondary school in Kisumu and needs help with fees.",
                "category": "education", "language": "en"})
            ok(res)
            meta = res.json()["meta"]
            return "PASS", "AI" if meta["ai_generated"] else f"template fallback ({meta.get('fallback_reason') or 'no provider'})", None
        s.step("AI campaign draft", ai_draft)

    def ai_translate():
        res = s.call("POST", "/api/v1/ai/translate", json={"text": "Thank you for your donation.", "target_language": "sw"})
        if res.status_code == 503:
            return "SKIP", "translation needs a working AI provider", None
        ok(res)
        return "PASS", res.json()["data"]["translated_text"][:50], None
    s.step("AI translation to Kiswahili", ai_translate)

    if tokens.get("beneficiary"):
        def assistant():
            res = s.call("POST", "/api/v1/ai/beneficiary-assistant", tokens["beneficiary"],
                         json={"message": "When will my payout arrive?", "language": "en"})
            ok(res)
            return "PASS", "AI" if res.json()["meta"]["ai_generated"] else "rule-based fallback", None
        s.step("AI beneficiary assistant", assistant)
        s.step("beneficiary profile", lambda: (lambda d: ("PASS", f"verification={d['verification_status']}", d))(
            ok(s.call("GET", "/api/v1/beneficiaries/me", tokens["beneficiary"]))))
        s.step("beneficiary payouts", lambda: (lambda d: ("PASS", ", ".join(p["status"] for p in d) or "none", d))(
            ok(s.call("GET", "/api/v1/payouts", tokens["beneficiary"]))))
    if tokens.get("donor"):
        s.step("donor history", lambda: (lambda d: ("PASS", f"{len(d)} donation(s)", d))(
            ok(s.call("GET", "/api/v1/me/donations", tokens["donor"]))))
    if tokens.get("reviewer"):
        s.step("reviewer: beneficiaries to verify", lambda: (lambda d: ("PASS", f"{len(d)} profile(s)", d))(
            ok(s.call("GET", "/api/v1/beneficiaries", tokens["reviewer"]))))
    if tokens.get("admin"):
        s.step("admin: find an account", lambda: (lambda d: ("PASS" if d else "FAIL", f"{len(d)} found", d))(
            ok(s.call("GET", f"/api/v1/admin/users?email={args.account_prefix}donor@example.test", tokens["admin"]))))

    if args.try_donation and tokens.get("donor") and campaigns:
        def donation():
            res = s.call("POST", "/api/v1/donations/orders", tokens["donor"], headers={"Idempotency-Key": uuid.uuid4().hex},
                         json={"campaign_id": campaigns[0]["id"], "amount": "1.00", "currency": "USD",
                               "return_url": "https://example.invalid/return", "cancel_url": "https://example.invalid/cancel"})
            if res.status_code == 400 and res.json()["error"]["code"] == "PAYMENT_PROVIDER_UNCONFIGURED":
                return "SKIP", "PayPal is not configured", None
            d = ok(res, 201)
            return ("PASS" if d["status"] == "pending" and d.get("approval_url") else "FAIL",
                    "pending order created; approve it at PayPal to complete", d)
        s.step("donation order (PayPal)", donation)
    else:
        s.record("SKIP", "donation order (PayPal)", "pass --try-donation to create one pending order")

    if args.callback_token:
        s.step("USSD callback (main menu)", lambda: (lambda r: (
            "PASS" if r.status_code == 200 and r.text.startswith("CON FundBridge") else "FAIL", r.text[:30].replace("\n", " / "), r))(
            s.call("POST", f"/api/v1/messaging/ussd?token={args.callback_token}",
                   data={"sessionId": "smoke-" + uuid.uuid4().hex[:8], "phoneNumber": args.ussd_phone, "text": ""})))
    elif status and status["messaging"].get("simulator_enabled"):
        s.step("USSD simulator (main menu, simulated)", lambda: (lambda r: (
            "PASS" if r.status_code == 200 and r.json()["meta"].get("simulated") else "FAIL", "labelled simulated", r))(
            s.call("POST", "/api/v1/messaging/simulator/ussd", json={"phone_number": args.ussd_phone, "text": ""})))
    else:
        s.record("SKIP", "USSD", "no --callback-token and the simulator is disabled")

    if config:
        s.record("INFO", "payouts", f"mode={config['payouts']['mode']} (payouts stop at approved_for_submission)")
    counts = {k: sum(1 for r in s.results if r[0] == k) for k in ("PASS", "SKIP", "FAIL")}
    print(f"\n{counts['PASS']} passed, {counts['SKIP']} skipped, {counts['FAIL']} failed")
    return 1 if counts["FAIL"] else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--password", required=True, help="DEMO_PASSWORD used when seeding")
    parser.add_argument("--account-prefix", default="demo-")
    parser.add_argument("--callback-token", default=None, help="MESSAGING_CALLBACK_TOKEN, to test the real USSD callback")
    parser.add_argument("--ussd-phone", default="+254712345678")
    parser.add_argument("--try-donation", action="store_true")
    sys.exit(run(parser.parse_args()))


if __name__ == "__main__":
    main()
