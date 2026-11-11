# FundBridge: setup, sandbox configuration and deployment

Covers the backend (Codex), plus the AI and SMS/USSD layer (Claude). The frontend has its own instructions.

## What is live, sandboxed or simulated

| Integration | State in this repository | What it takes to change |
|---|---|---|
| PayPal donations | Sandbox adapter. Unconfigured until credentials are set. A donation completes only after a verified webhook or a server-side capture whose amount, currency and order match. | `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID` (sandbox app) |
| Mobile-money payouts | Labelled simulator. Never reports `succeeded`. No Daraja B2C integration. | Safaricom B2C credentials and approval (not started) |
| SMS | Simulated gateway: messages go to an in-memory outbox. The Africa's Talking adapter is written but **has not been run** against AT. | `SMS_PROVIDER=africastalking`, `AT_USERNAME`, `AT_API_KEY` |
| USSD | Africa's Talking callback format implemented, plus a simulator. No service code is registered or verified. | AT USSD channel, callback URL, `MESSAGING_CALLBACK_TOKEN` |
| AI | OpenAI provider implemented; tested only with a mocked HTTP transport. Deterministic fallbacks are active when no key is set. | `OPENAI_API_KEY`, `OPENAI_MODEL` |

`GET /api/v1/integrations/status` reports the current AI and messaging state at runtime. `GET /api/v1/public/config` reports PayPal and payout state.

## Local setup

Requires Python 3.12 and, for anything beyond a quick local trial, PostgreSQL 14+.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt -r requirements-integrations.txt
cp .env.example .env            # then fill in the values below
set -a; . ./.env; set +a
.venv/bin/flask --app run:app db upgrade
.venv/bin/flask --app run:app fundbridge-demo seed     # optional demo accounts and campaigns
.venv/bin/flask --app run:app run --port 5000
```

The demo seed creates accounts (`demo-<role>@example.test`), a verified beneficiary on `+254712345678` and two published campaigns. It creates **no donations, ledger entries or payouts**, so raised totals stay at 0 until real sandbox payments are captured. Set `DEMO_PASSWORD` or read the generated password from the output. It refuses to run with `FLASK_ENV=production`.

Phone demo: set `MESSAGING_SIMULATOR_ENABLED=true` and open `http://localhost:5000/api/v1/messaging/simulator`.

## Required secrets

Generate each with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. Keep them out of git.

| Variable | Purpose |
|---|---|
| `SECRET_KEY` | Flask secret; also salts the hashed user identifier sent to OpenAI |
| `JWT_SECRET_KEY` | Signs access tokens (at least 32 bytes) |
| `MESSAGING_CALLBACK_TOKEN` | Shared secret on SMS/USSD gateway callback URLs. Without it, callbacks return 503. |
| `DATABASE_URL` | `postgresql+psycopg://user:pass@host:5432/fundbridge` |

All other variables are documented in `backend/.env.example`.

## Sandbox configuration

### PayPal (sandbox)
1. developer.paypal.com → Apps & Credentials → Sandbox → create an app → copy the client ID and secret.
2. Add a webhook for `https://<backend-host>/api/v1/webhooks/paypal` with event `PAYMENT.CAPTURE.COMPLETED`, then copy the webhook ID into `PAYPAL_WEBHOOK_ID`.
3. Keep `PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com`.
4. Pay with a sandbox personal account. Confirm success through `GET /api/v1/donations/{id}`, never through the redirect.

### Africa's Talking (sandbox). Not yet exercised from this repository.
1. Create an Africa's Talking account and open the Sandbox app; generate an API key. Use `AT_USERNAME=sandbox`.
2. USSD: create a sandbox service code and set the callback URL to `https://<backend-host>/api/v1/messaging/ussd?token=<MESSAGING_CALLBACK_TOKEN>`.
3. SMS: set the incoming-messages callback to `https://<backend-host>/api/v1/messaging/sms/inbound?token=<MESSAGING_CALLBACK_TOKEN>`.
4. Set `SMS_PROVIDER=africastalking`, `AT_API_KEY`, and optionally `AT_SENDER_ID`.
5. Test from Africa's Talking's web simulator. Sandbox messages do not reach real phones. A `submitted` send result means AT accepted the message, not that it was delivered.
6. Optionally restrict callers with `MESSAGING_ALLOWED_IPS` once AT's callback source addresses are confirmed.

The callback URL carries the secret, so it **must be HTTPS**.

### OpenAI
Set `OPENAI_API_KEY` and confirm `OPENAI_MODEL` is available to the account; the default is `gpt-4o-mini`. Requests use Chat Completions with strict JSON-schema output, `store=false` and a 15 s timeout. If a call fails, the feature falls back to its deterministic path and responses carry `meta.degraded: true`.

## Deployment requirements

- **PostgreSQL, not SQLite.** Payout reservations rely on `SELECT … FOR UPDATE` on the campaign row. This was verified on PostgreSQL 16 with 8 concurrent requests: exactly one reservation. SQLite ignores the lock.
- **One worker process for the demo.** Rate limits and the simulated SMS outbox are in memory, per process. Use, for example, `gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT run:app` (`pip install gunicorn`). Multiple workers need a shared store such as Redis.
- **Reverse proxy:** set `TRUSTED_PROXY_HOPS=1` (or the actual hop count) so IP rate limits and the callback allowlist see the client address.
- **HTTPS** for the API, the PayPal webhook and the SMS/USSD callbacks.
- `FRONTEND_ORIGIN` must be the deployed frontend origin (CORS allowlist). `PUBLIC_BASE_URL` is the URL shown in SMS/USSD messages.
- Run `flask --app run:app db upgrade` on every deploy. Current head: `c3f1a9e7d2b4`.
- Keep `MESSAGING_SIMULATOR_ENABLED=false` on any deployment that holds real beneficiary data.

## Tests

```bash
cd backend
.venv/bin/python -m pytest tests -q
# include the PostgreSQL concurrency tests (use an isolated, disposable database):
POSTGRES_TEST_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5432/fundbridge_test .venv/bin/python -m pytest tests -q
```

Tests marked `xfail` with reason `DEFECT …` reproduce known core-backend defects. They are listed in `docs/integration/COORDINATION.md`.
