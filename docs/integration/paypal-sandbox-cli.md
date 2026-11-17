# PayPal Sandbox CLI workflow (Ubuntu)

This is a **sandbox-only** donation test. It never creates a live PayPal
payment. The helper calls `POST /api/v1/donations/orders` and
`POST /api/v1/donations/{id}/capture`; it does not construct direct Orders v2
or Capture requests. This retains FundBridge's server-side validation,
idempotency, and ledger controls.

## 1. Configure a local sandbox server

In [PayPal Developer](https://developer.paypal.com/), create or select a
**Sandbox** REST app. Copy its sandbox client ID and secret only into the
ignored `backend/.env` file. Do not use a live app and do not paste values into
the terminal history, documentation, chat, or Git.

```bash
cd /home/user/FundBridge/FundBridge/backend
cp -n .env.example .env
chmod 600 .env
```

Set these names in `backend/.env` with an editor that does not echo values:

```dotenv
PAYPAL_CLIENT_ID=<sandbox-client-id>
PAYPAL_CLIENT_SECRET=<sandbox-client-secret>
PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com
PAYPAL_WEBHOOK_ID=<sandbox-webhook-id-after-step-7>
```

Start a disposable local development database; do not use production data. The
demo seed creates only users and published campaigns, never financial records.

```bash
set -a; . ./.env; set +a
.venv/bin/flask --app run:app db upgrade
read -rsp 'Local demo password: ' DEMO_PASSWORD; echo
export DEMO_PASSWORD
.venv/bin/flask --app run:app fundbridge-demo seed
.venv/bin/flask --app run:app run --port 5000
```

In another terminal, use the same `backend/.env`, then sign in as the seeded
donor. The token is kept only in this shell session.

```bash
cd /home/user/FundBridge/FundBridge/backend
set -a; . ./.env; set +a
read -rsp 'Local demo password: ' DEMO_PASSWORD; echo
export DEMO_PASSWORD
export FUND_BRIDGE_API_BASE=http://127.0.0.1:5000/api/v1
export FUND_BRIDGE_DONOR_TOKEN="$({
  .venv/bin/python -c '
import json, os, urllib.request
request = urllib.request.Request(
    os.environ["FUND_BRIDGE_API_BASE"] + "/auth/login",
    data=json.dumps({"email": "demo-donor@example.test", "password": os.environ["DEMO_PASSWORD"]}).encode(),
    headers={"Content-Type": "application/json"}, method="POST")
with urllib.request.urlopen(request, timeout=20) as response:
    print(json.load(response)["data"]["access_token"])
'
})"
export FUND_BRIDGE_CAMPAIGN_ID="$({
  curl --silent --show-error --fail-with-body \
    "$FUND_BRIDGE_API_BASE/campaigns" |
  .venv/bin/python -c 'import json,sys; print(next(x["id"] for x in json.load(sys.stdin)["data"] if x["slug"] == "demo-school-fees-amina"))'
})"
export FUND_BRIDGE_AMOUNT=1.00
export FUND_BRIDGE_CURRENCY=USD
export FUND_BRIDGE_RETURN_URL=http://localhost:3000/paypal/return
export FUND_BRIDGE_CANCEL_URL=http://localhost:3000/paypal/cancel
```

The return/cancel URLs must be URLs appropriate for your local frontend or
test page. They are navigation URLs only: FundBridge never treats a redirect as
payment proof.

## 2. Confirm sandbox OAuth/API connectivity

```bash
.venv/bin/python scripts/paypal_sandbox_smoke.py provider-check
```

The helper requests `POST /v1/oauth2/token` with the sandbox credentials. It
prints only success/failure, never the access token, client ID, or secret.

## 3. Create an order through FundBridge

```bash
.venv/bin/python scripts/paypal_sandbox_smoke.py \
  --state-file /tmp/fundbridge-paypal-sandbox.json create
```

This calls the authenticated FundBridge order endpoint with a fresh
`Idempotency-Key`, then writes only non-secret state at mode `0600`. FundBridge
sends PayPal `Prefer: return=representation`, uses the donation UUID as the
PayPal `reference_id`, and rejects an order whose reference, amount, currency,
or ID does not match. Re-running `create` with the same state-file is refused,
so it cannot accidentally make a second sandbox order.

## 4. Approve as a sandbox buyer

Copy the displayed approval URL into a browser private window. Sign in using a
**PayPal Sandbox personal (buyer) account** created under Developer Dashboard
→ Testing Tools → Sandbox Accounts. Approve the USD 1.00 sandbox payment. Do
not sign in with a live PayPal account and do not use the live paypal.com
checkout.

After the redirect, return to the terminal. A redirect itself is not a
successful payment signal.

## 5. Capture once, then verify the ledger-backed balance

```bash
.venv/bin/python scripts/paypal_sandbox_smoke.py \
  --state-file /tmp/fundbridge-paypal-sandbox.json capture
.venv/bin/python scripts/paypal_sandbox_smoke.py \
  --state-file /tmp/fundbridge-paypal-sandbox.json verify
```

`capture` calls FundBridge's server-side capture route. The backend checks the
PayPal order's donation reference, completed capture status, capture ID,
amount, and currency before inserting the single `donation_completed` ledger
entry. `verify` checks the donation is `completed` and that
`GET /campaigns/{id}/funds` reports a `source` of `ledger` and includes the
amount in its raised balance.

If capture has a timeout or a `5xx`, **do not call capture again**. A PayPal
capture can have succeeded remotely. Use the no-side-effect reconciliation
route instead:

```bash
.venv/bin/python scripts/paypal_sandbox_smoke.py \
  --state-file /tmp/fundbridge-paypal-sandbox.json reconcile
.venv/bin/python scripts/paypal_sandbox_smoke.py \
  --state-file /tmp/fundbridge-paypal-sandbox.json verify
```

## 6. Webhook registration and verification

For a publicly reachable HTTPS deployment, create a PayPal **Sandbox** webhook
at this exact endpoint:

```text
https://<public-backend-host>/api/v1/webhooks/paypal
```

Subscribe to `PAYMENT.CAPTURE.COMPLETED`, copy the webhook ID into
`PAYPAL_WEBHOOK_ID`, and restart the backend. PayPal must be able to reach the
endpoint; localhost needs a temporary HTTPS tunnel for this test.

FundBridge does not accept a webhook merely because it claims to be PayPal. It
sends the received `PAYPAL-AUTH-ALGO`, certificate URL, transmission ID,
signature, and timestamp plus the configured webhook ID to PayPal's sandbox
`/v1/notifications/verify-webhook-signature` endpoint. Only a `SUCCESS`
verification may reach payment completion. Provider event IDs are recorded to
prevent replay credits. Do not use a manually crafted callback as a substitute
for PayPal's delivery.

## Environment variables

| Variable | Purpose | Secret |
| --- | --- | --- |
| `PAYPAL_CLIENT_ID` | Sandbox REST application client ID | Treat as sensitive |
| `PAYPAL_CLIENT_SECRET` | Sandbox REST application secret | Yes |
| `PAYPAL_BASE_URL` | Must be `https://api-m.sandbox.paypal.com` | No |
| `PAYPAL_WEBHOOK_ID` | Sandbox webhook ID for signature verification | Sensitive configuration |
| `FUND_BRIDGE_API_BASE` | Local FundBridge API base URL | No |
| `FUND_BRIDGE_DONOR_TOKEN` | Temporary donor JWT for the CLI session | Yes |
| `FUND_BRIDGE_CAMPAIGN_ID` | Published test campaign UUID | No |
| `FUND_BRIDGE_AMOUNT`, `FUND_BRIDGE_CURRENCY` | Test donation money values | No |
| `FUND_BRIDGE_RETURN_URL`, `FUND_BRIDGE_CANCEL_URL` | PayPal navigation destinations | No |

`.env`, generated state, access tokens, sandbox secrets, and webhook
credentials must never be committed.
