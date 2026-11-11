# FundBridge: setup, provider configuration and deployment

Covers the backend (core API by Codex; AI, SMS/USSD, operations and hardening by Claude). The frontend has its own instructions; its API client is `contracts/fundbridge-client.ts`.

## What is live, sandboxed or simulated

Nothing in this repository has been run against a real provider account. "Tested against a double" means the real adapter code ran over HTTP against a local stand-in (`backend/tests/e2e/provider_doubles.py`) that models the provider's API; it says nothing about the provider's live behaviour.

| Integration | State | Evidence | Needed to go live |
|---|---|---|---|
| PayPal donations (Orders v2) | Sandbox adapter. Unconfigured until credentials are set. A donation completes only after a server-side capture or a signature-verified webhook whose order, reference, amount and currency match. | Live e2e suite against a PayPal Orders v2 double: order, approval, capture, capture-before-approval, tampered amount, signed and forged webhooks, replay | PayPal sandbox app (`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`), a webhook (`PAYPAL_WEBHOOK_ID`), then a real sandbox payment. Production needs a live PayPal business account and app review. |
| Mobile-money payouts | Labelled simulator. Payouts stop at `approved_for_submission`; there is no submission endpoint, and nothing ever reports `succeeded`. | Reservation, review, rejection release and concurrency tests | A licensed payout provider (for example Safaricom Daraja B2C or an aggregator), credentials, approval, and a submission/callback contract. Not started. |
| SMS | Simulated gateway (in-memory outbox, per process). An Africa's Talking adapter exists but **has never been run against Africa's Talking**. | Integration and e2e tests through the real callback endpoints | Africa's Talking account, `SMS_PROVIDER=africastalking`, `AT_USERNAME`, `AT_API_KEY`, optionally `AT_SENDER_ID` |
| USSD | Africa's Talking callback format implemented, plus a simulator. No service code is registered. | e2e: English and Kiswahili menus, PIN, payout status, search, through the authenticated callback | Africa's Talking USSD channel and service code; callback URL with `MESSAGING_CALLBACK_TOKEN` |
| AI (OpenAI) | Provider implemented; deterministic fallbacks when no key is set or the provider fails. | Mocked transport tests, plus e2e against an OpenAI Chat Completions double (PII redaction checked at the provider boundary, outage fallback) | `OPENAI_API_KEY`; confirm `OPENAI_MODEL` is available to the account and allowed by the event's AI rules |

`GET /api/v1/integrations/status` reports AI and messaging modes at runtime. `GET /api/v1/public/config` reports PayPal and payout modes. Its `feature_phone` flags are always `false`; use `/integrations/status` for SMS/USSD.

## Local setup

Requires Python 3.12. Use PostgreSQL 14+ for anything beyond a quick trial.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt          # includes the AI/messaging dependencies
cp .env.example .env                               # then fill in the values below
set -a; . ./.env; set +a
.venv/bin/flask --app run:app db upgrade
.venv/bin/flask --app run:app fundbridge-admin create-admin --email you@example.org   # prompts for a password
.venv/bin/flask --app run:app run --port 5000
```

Optional demo data: `flask --app run:app fundbridge-demo seed` creates `demo-<role>@example.test` accounts, a verified beneficiary on `+254712345678` and two published campaigns. It creates **no donations, ledger entries or payouts** and refuses to run with `FLASK_ENV=production`. Phone demo: set `MESSAGING_SIMULATOR_ENABLED=true` and open `http://localhost:5000/api/v1/messaging/simulator`.

## Accounts and roles

Public registration always creates a `donor`. To set up everyone else:

1. Create the first admin with `flask fundbridge-admin create-admin --email ...`. The password comes from `FUNDBRIDGE_ADMIN_PASSWORD` or a hidden prompt; it is never echoed, and the action is audited. Do not leave `FUNDBRIDGE_ADMIN_PASSWORD` in the deployed environment.
2. People register, then the admin finds them with `GET /api/v1/admin/users?email=` and assigns `creator`, `beneficiary`, `agent`, `reviewer` or `admin` with `PUT /api/v1/admin/users/{id}/role`. Changes are audited and take effect immediately.
3. An agent creates the beneficiary profile (`POST /api/v1/beneficiaries`). A reviewer verifies it (`POST /api/v1/beneficiaries/{id}/verification` with the `revision` they reviewed). Payouts, USSD payout status and SMS notifications all require `verified`.

## Environment variables

Generate secrets with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` and keep them out of git. `backend/.env.example` lists every variable.

| Variable | Required | Purpose |
|---|---|---|
| `FLASK_ENV=production` | prod | Refuses to start without `SECRET_KEY` / `JWT_SECRET_KEY`; blocks demo seeding |
| `SECRET_KEY`, `JWT_SECRET_KEY` | yes | Flask secret, JWT signing key (at least 32 bytes). Access tokens expire after 15 minutes; there is no refresh endpoint, so clients re-login on `TOKEN_EXPIRED`. |
| `DATABASE_URL` | yes | `postgresql+psycopg://user:pass@host:5432/fundbridge` |
| `FRONTEND_ORIGIN` | yes | The only origin allowed by CORS |
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`, `PAYPAL_BASE_URL` | for donations | Without the client ID, donation orders return `PAYMENT_PROVIDER_UNCONFIGURED` |
| `PAYOUT_PROVIDER` | no | `simulator` (only option today) |
| `MESSAGING_CALLBACK_TOKEN` | for SMS/USSD | Shared secret on gateway callbacks; callbacks return 503 without it |
| `SMS_PROVIDER`, `AT_*`, `USSD_SERVICE_CODE`, `MESSAGING_*`, `PUBLIC_BASE_URL` | for SMS/USSD | See `.env.example` |
| `AI_PROVIDER`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `AI_*` | no | AI runs in fallback mode without a key |
| `TRUSTED_PROXY_HOPS` | behind a proxy | Number of proxy hops to trust for the client IP (rate limits, callback allowlist) |
| `AUTH_LOGIN_LIMIT_PER_IP_PER_MINUTE` (30), `AUTH_LOGIN_FAILURES_PER_ACCOUNT` (5), `AUTH_LOGIN_FAILURE_WINDOW_SECONDS` (900), `AUTH_REGISTER_LIMIT_PER_IP_PER_10_MINUTES` (20), `DONATION_ORDER_LIMIT_PER_IP_PER_MINUTE` (30), `RATE_LIMITS_ENABLED` (true) | no | Sign-in and order throttling. A venue demo behind one NAT address may need higher per-IP values. |

## Provider configuration

### PayPal (sandbox)
1. developer.paypal.com → Apps & Credentials → Sandbox → create an app → copy the client ID and secret.
2. Add a webhook for `https://<backend-host>/api/v1/webhooks/paypal` with event `PAYMENT.CAPTURE.COMPLETED`, then copy its ID into `PAYPAL_WEBHOOK_ID`.
3. Keep `PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com`.
4. Pay with a sandbox personal account. The frontend calls `POST /donations/{id}/capture` on return, then trusts only `GET /donations/{id}` (see `FundBridgeClient.completePayPalReturn`).
5. Configure the webhook even if capture-on-return works. If a capture times out, the payment may already be captured at PayPal; a retried capture then gets `ORDER_ALREADY_CAPTURED`, and only the webhook moves the donation to `completed` (open item R-1 in `docs/integration/COORDINATION.md`).

### Africa's Talking (sandbox). Not yet exercised from this repository.
1. Create an account, open the Sandbox app, generate an API key. Use `AT_USERNAME=sandbox`.
2. USSD: create a sandbox service code with callback `https://<backend-host>/api/v1/messaging/ussd?token=<MESSAGING_CALLBACK_TOKEN>`.
3. SMS: set the incoming-messages callback to `https://<backend-host>/api/v1/messaging/sms/inbound?token=<MESSAGING_CALLBACK_TOKEN>`.
4. Set `SMS_PROVIDER=africastalking`, `AT_API_KEY`, optionally `AT_SENDER_ID`.
5. Sandbox messages do not reach real phones. `submitted` means Africa's Talking accepted a message, not that it was delivered.
6. Once Africa's Talking's callback source addresses are confirmed, restrict callers with `MESSAGING_ALLOWED_IPS`.

The callback URL carries the secret, so it **must be HTTPS**. Do not log full request URLs for these paths (see Logging).

### OpenAI
Set `OPENAI_API_KEY` and confirm `OPENAI_MODEL` (default `gpt-4o-mini`) is available to the account. Calls use Chat Completions with strict JSON-schema output, `store=false`, a 15 s timeout, and PII redaction before the request leaves the server. If a call fails, the feature falls back and responses carry `meta.degraded: true`; translation has no fallback and returns `503 AI_UNAVAILABLE`.

## Production deployment

```bash
pip install -r backend/requirements-deploy.txt                  # requirements.txt + gunicorn
cd backend
flask --app run:app db upgrade                                  # every deploy; Alembic head: c3f1a9e7d2b4
gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT run:app              # start command
```

- **PostgreSQL, not SQLite.** Payout reservations rely on `SELECT … FOR UPDATE`. On PostgreSQL 16, 8 concurrent payout requests produced exactly one reservation.
- **One worker process.** Rate limits and the simulated SMS outbox are in memory, per process. Use threads, not workers. Several workers or instances need a shared store (for example Redis) for the limiter.
- **Reverse proxy:** set `TRUSTED_PROXY_HOPS` to the real hop count.
- **HTTPS** for the API, the PayPal webhook and the gateway callbacks.
- Keep `MESSAGING_SIMULATOR_ENABLED=false` wherever real beneficiary data exists.
- Existing databases: a database created before backend commit `397ef42` cannot upgrade cleanly if it holds donations (defect M-1). Recreate demo databases instead.

## Logging, errors and audit

- Every response has `X-Request-ID`; a sane incoming ID is kept. Error envelopes for 500s include it in `details.request_id`.
- The application access log (`fundbridge.http`) records method, path, status, duration and request ID only. It never records query strings or bodies, so callback tokens, search terms, emails and phone numbers stay out. **Do not enable gunicorn's `--access-logfile`** with its default format: it logs the query string, which carries the callback token.
- Unhandled errors log the exception type and stack frames but not the exception message, which can contain SQL parameters.
- Provider failures return `502 PROVIDER_REQUEST_REJECTED` (with `provider_status` and `provider_issue`) or `503 PROVIDER_UNAVAILABLE`. Neither claims whether the donor was charged; clients re-read the donation.
- `audit_log` records campaign create/update/submit/review, beneficiary onboarding, profile changes, verification decisions, role changes, operator admin creation, donation completion and payout request/review/provider outcomes.

## Tests

```bash
cd backend
.venv/bin/python -m pytest tests -q                    # unit, integration, migrations, live e2e (SQLite)

# with PostgreSQL (each URL must be a disposable database; the suites drop and recreate schemas):
POSTGRES_TEST_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5432/fundbridge_test \
E2E_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5432/fundbridge_e2e \
.venv/bin/python -m pytest tests -q
```

- `tests/e2e` starts gunicorn on the migrated database and drives every journey over HTTP, including the TypeScript client (needs Node.js 22.6+; skipped otherwise). It needs `requirements-deploy.txt` installed (falls back to `flask run` without gunicorn).
- Tests marked `xfail` with reason `DEFECT …` reproduce open defects listed in `docs/integration/COORDINATION.md`.
