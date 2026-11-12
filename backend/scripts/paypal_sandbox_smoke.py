#!/usr/bin/env python3
"""Exercise FundBridge's PayPal *sandbox* path without printing credentials.

This helper intentionally creates orders only through FundBridge's API.  It
never calls PayPal's Orders or Capture endpoints directly, so the application
continues to own canonical donation references, idempotency and ledger writes.

It stores only non-secret state (donation ID, amount, campaign ID and
idempotency key) in a mode-0600 JSON file.  See
docs/integration/paypal-sandbox-cli.md before running it.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


SANDBOX_HOST = "api-m.sandbox.paypal.com"
DEFAULT_API = "http://127.0.0.1:5000/api/v1"


def fail(message: str) -> "None":
    print(f"ERROR: {message}", file=sys.stderr)
    raise SystemExit(1)


def sandbox_base() -> str:
    base = os.environ.get("PAYPAL_BASE_URL", f"https://{SANDBOX_HOST}").rstrip("/")
    parsed = urlparse(base)
    if parsed.scheme != "https" or parsed.hostname != SANDBOX_HOST:
        fail("PAYPAL_BASE_URL must be exactly the HTTPS PayPal sandbox host; live endpoints are refused.")
    return base


def required(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        fail(f"{name} is required (set it in the ignored backend/.env or your shell).")
    return value


def request(url: str, *, method: str = "GET", headers: dict[str, str] | None = None,
            json_body: dict | None = None, form: dict[str, str] | None = None) -> tuple[int, dict]:
    body = None
    headers = dict(headers or {})
    if json_body is not None:
        body = json.dumps(json_body).encode()
        headers["Content-Type"] = "application/json"
    elif form is not None:
        body = urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=20) as response:
            raw = response.read()
            return response.status, json.loads(raw.decode() or "{}")
    except HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw.decode() or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {"raw": "non-JSON response"}
        return exc.code, payload
    except URLError as exc:
        fail(f"network request failed: {exc.reason}")


def describe_error(status: int, payload: dict) -> str:
    error = payload.get("error") if isinstance(payload, dict) else None
    if isinstance(error, dict):
        return f"HTTP {status} {error.get('code', 'UNKNOWN_ERROR')}"
    name = payload.get("name") if isinstance(payload, dict) else None
    return f"HTTP {status} {name or 'provider request rejected'}"


def paypal_token() -> str:
    client_id = required("PAYPAL_CLIENT_ID")
    client_secret = required("PAYPAL_CLIENT_SECRET")
    credentials = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    status, payload = request(
        f"{sandbox_base()}/v1/oauth2/token",
        method="POST",
        headers={"Authorization": f"Basic {credentials}", "Accept": "application/json"},
        form={"grant_type": "client_credentials"},
    )
    token = payload.get("access_token") if isinstance(payload, dict) else None
    if status != 200 or not isinstance(token, str) or not token:
        fail(f"sandbox OAuth failed: {describe_error(status, payload)}")
    return token


def api_base() -> str:
    return os.environ.get("FUND_BRIDGE_API_BASE", DEFAULT_API).rstrip("/")


def api(path: str, *, token: str | None = None, method: str = "GET", body: dict | None = None,
        idempotency_key: str | None = None) -> dict:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    status, payload = request(f"{api_base()}{path}", method=method, headers=headers, json_body=body)
    if not 200 <= status < 300:
        fail(f"FundBridge request {path} failed: {describe_error(status, payload)}")
    if not isinstance(payload, dict) or "data" not in payload:
        fail(f"FundBridge request {path} returned an unexpected response envelope.")
    return payload["data"]


def state_path(value: str | None) -> Path:
    path = Path(value or os.environ.get("FUND_BRIDGE_PAYPAL_STATE", ".paypal-sandbox-state.json"))
    if path.is_absolute():
        return path
    return Path.cwd() / path


def write_state(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    os.chmod(path, 0o600)


def read_state(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"state file not found: {path}; run create first.")
    except json.JSONDecodeError:
        fail(f"state file is not valid JSON: {path}")
    if not isinstance(value, dict) or not all(isinstance(value.get(k), str) for k in ("donation_id", "campaign_id", "amount", "currency")):
        fail("state file has an unexpected shape; remove it and start a new sandbox test.")
    return value


def command_provider_check(_: argparse.Namespace) -> None:
    paypal_token()  # Deliberately not displayed or persisted.
    print("PayPal sandbox OAuth and API connectivity: OK (access token obtained but not printed).")


def command_create(args: argparse.Namespace) -> None:
    token = required("FUND_BRIDGE_DONOR_TOKEN")
    campaign_id = required("FUND_BRIDGE_CAMPAIGN_ID")
    return_url = required("FUND_BRIDGE_RETURN_URL")
    cancel_url = required("FUND_BRIDGE_CANCEL_URL")
    amount = required("FUND_BRIDGE_AMOUNT")
    currency = required("FUND_BRIDGE_CURRENCY").upper()
    try:
        if Decimal(amount) <= 0:
            raise InvalidOperation
    except InvalidOperation:
        fail("FUND_BRIDGE_AMOUNT must be a positive decimal string.")

    path = state_path(args.state_file)
    if path.exists():
        fail(f"state file already exists: {path}; use its existing order or choose a new --state-file.")
    public_config = api("/public/config")
    if public_config.get("payments", {}).get("paypal", {}).get("mode") != "sandbox":
        fail("FundBridge does not report PayPal sandbox mode; check its environment and restart the server.")
    baseline = api(f"/campaigns/{campaign_id}/funds").get("balance", {}).get("raised")
    idempotency_key = f"paypal-sandbox-{uuid.uuid4()}"
    created = api(
        "/donations/orders", token=token, method="POST", idempotency_key=idempotency_key,
        body={"campaign_id": campaign_id, "amount": amount, "currency": currency,
              "return_url": return_url, "cancel_url": cancel_url},
    )
    approval_url = created.get("approval_url")
    donation_id = created.get("id")
    if not isinstance(approval_url, str) or not isinstance(donation_id, str):
        fail("FundBridge created no usable approval URL or donation ID; do not attempt a direct PayPal order.")
    write_state(path, {"donation_id": donation_id, "campaign_id": campaign_id, "amount": amount,
                       "currency": currency, "idempotency_key": idempotency_key,
                       "baseline_raised": baseline})
    print(f"Created pending FundBridge donation: {donation_id}")
    print(f"Approval URL (open only in a sandbox-buyer browser): {approval_url}")
    print(f"Non-secret state saved to: {path}")
    print("Approve the order, then run the capture command exactly once.")


def command_capture(args: argparse.Namespace) -> None:
    token = required("FUND_BRIDGE_DONOR_TOKEN")
    state = read_state(state_path(args.state_file))
    try:
        captured = api(f"/donations/{state['donation_id']}/capture", token=token, method="POST")
    except SystemExit:
        print("Capture was not confirmed. Do not retry capture after an ambiguous failure; run reconcile instead.", file=sys.stderr)
        raise
    if captured.get("status") != "completed":
        fail("capture response was not completed; do not retry blindly. Run reconcile.")
    print(f"Server-side capture completed for donation: {state['donation_id']}")


def command_reconcile(args: argparse.Namespace) -> None:
    token = required("FUND_BRIDGE_DONOR_TOKEN")
    state = read_state(state_path(args.state_file))
    reconciled = api(f"/donations/{state['donation_id']}/reconcile", token=token, method="POST")
    print(f"Reconciled donation status: {reconciled.get('status')}")


def command_verify(args: argparse.Namespace) -> None:
    token = required("FUND_BRIDGE_DONOR_TOKEN")
    state = read_state(state_path(args.state_file))
    donation = api(f"/donations/{state['donation_id']}", token=token)
    funds = api(f"/campaigns/{state['campaign_id']}/funds")
    balance = funds.get("balance", {})
    if donation.get("status") != "completed":
        fail(f"donation is {donation.get('status')!r}, not completed; no ledger credit is asserted.")
    if funds.get("source") != "ledger" or balance.get("currency") != state["currency"]:
        fail("campaign funds response is not the expected ledger-backed balance.")
    try:
        if Decimal(str(balance.get("raised"))) < Decimal(state["amount"]):
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        fail("ledger-backed raised total does not include the sandbox donation amount.")
    print(f"Donation status: {donation['status']}")
    print(f"Ledger-backed campaign raised: {balance.get('raised')} {balance.get('currency')}")
    print("Verification passed: a completed donation is reflected by the ledger-backed funds endpoint.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", help="non-secret JSON state path (mode 0600)")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("provider-check", help="obtain a sandbox OAuth token without displaying it")
    commands.add_parser("create", help="create an order through FundBridge only")
    commands.add_parser("capture", help="server-side capture after buyer approval")
    commands.add_parser("reconcile", help="read provider state after an ambiguous capture")
    commands.add_parser("verify", help="verify donation state and ledger-backed balance")
    args = parser.parse_args()
    {"provider-check": command_provider_check, "create": command_create, "capture": command_capture,
     "reconcile": command_reconcile, "verify": command_verify}[args.command](args)


if __name__ == "__main__":
    main()
