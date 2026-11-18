# Runbook: local setup, demo data, smoke test, deployment

Short and command-first. Details: [`DEPLOYMENT.md`](DEPLOYMENT.md). Provider setup: [`integration/EXTERNAL_CHECKLIST.md`](integration/EXTERNAL_CHECKLIST.md).

**Deploy from `feat/backend-core` at `967781d` or later** (or `main` once PR #8 is merged). Earlier commits lack the review queue, the beneficiary campaign list and the concurrency fixes; commits before `b45ee29` cannot create real PayPal orders (C-4b).

## 1. Local (about 5 minutes)

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements-deploy.txt
cp .env.example .env
# edit .env: set SECRET_KEY, JWT_SECRET_KEY (random values), DATABASE_URL (PostgreSQL recommended),
#            MESSAGING_CALLBACK_TOKEN (random), MESSAGING_SIMULATOR_ENABLED=true for the phone demo
set -a; . ./.env; set +a
.venv/bin/flask --app run:app db upgrade
DEMO_PASSWORD='choose-a-demo-password' .venv/bin/flask --app run:app fundbridge-demo seed --scenarios
.venv/bin/gunicorn -w 1 --threads 8 -b 127.0.0.1:5000 run:app
```

The seed prints every demo account, its role, the beneficiary phone numbers and the campaign IDs. Every account uses the same `DEMO_PASSWORD`. Demo money is labelled `demo_seed`; it is not a PayPal payment.

| Account | Role | Use it for |
|---|---|---|
| `demo-donor@example.test` | donor | browse, search, donate, donation history |
| `demo-creator@example.test` | creator | AI draft, create, submit |
| `demo-reviewer@example.test` | reviewer | review campaigns, verify beneficiaries, approve payouts |
| `demo-beneficiary@example.test` | beneficiary (Amina, English, `+254712345678`) | payouts, USSD |
| `demo-beneficiary-sw@example.test` | beneficiary (Baraka, Kiswahili, `+254712345679`) | USSD in Kiswahili |
| `demo-agent@example.test` | agent | onboarding, phone support requests |
| `demo-admin@example.test` | admin | roles, PIN reset |

Phone demo: open `http://127.0.0.1:5000/api/v1/messaging/simulator`. Every screen is labelled as simulated.

## 2. Smoke test (any environment)

```bash
.venv/bin/python scripts/smoke_test.py --base-url http://127.0.0.1:5000 --password "$DEMO_PASSWORD" \
    --callback-token "$MESSAGING_CALLBACK_TOKEN" [--try-donation]
```

Every line is PASS, SKIP or FAIL. SKIP means a provider is not configured (for example PayPal or OpenAI); it is not success. Exit code 1 if anything fails.

## 3. Provider checks (only with real credentials)

```bash
.venv/bin/flask --app run:app fundbridge-ai check                       # real OpenAI search and translation
.venv/bin/flask --app run:app fundbridge-messaging check-config --api-host https://<host>
.venv/bin/flask --app run:app fundbridge-messaging send-test --to +2547XXXXXXXX
```

## 4. Deployment (for example Railway or Render)

1. PostgreSQL 14 or later. Set `DATABASE_URL` and every secret in the host's secret store. Set `FLASK_ENV=production`, `FRONTEND_ORIGIN` and `PUBLIC_BASE_URL` (keep it short), and `TRUSTED_PROXY_HOPS=1` behind the platform proxy.
2. Build: `pip install -r backend/requirements-deploy.txt`. Release: `flask --app run:app db upgrade`. Start: `gunicorn -w 1 --threads 8 -b 0.0.0.0:$PORT run:app` (one worker: rate limits and the simulated SMS outbox live in process).
3. First admin: `FUNDBRIDGE_ADMIN_PASSWORD=... flask --app run:app fundbridge-admin create-admin --email you@org`. Then remove the variable.
4. For a demo deployment only: set `FLASK_ENV=development` for the seed command alone, run `fundbridge-demo seed --scenarios`, and keep `MESSAGING_SIMULATOR_ENABLED=true`. **Never seed a database that holds real people, and never point a live SMS gateway at seeded data.**
5. Run the smoke test against the public URL. Do not enable gunicorn's access log: callback tokens travel in the query string.

## 5. Reset the demo

Drop and recreate the demo database, run `db upgrade`, then seed again. The seed is idempotent but never deletes anything, so donations made during a rehearsal stay until you reset.

## 6. Run the tests

```bash
cd backend
POSTGRES_TEST_DATABASE_URL=postgresql+psycopg://u@127.0.0.1:5432/fb_test \
E2E_DATABASE_URL=postgresql+psycopg://u@127.0.0.1:5432/fb_e2e .venv/bin/python -m pytest tests -q -rxs
cd ../contracts && npm ci && npm test
```

Both test databases are disposable: the suites drop and recreate the schema.
