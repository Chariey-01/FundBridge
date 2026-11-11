# FundBridge
An AI-powered global crowdfunding platform connecting international donors with beneficiaries through accessible local payout channels.

## Backend (Codex scope)

The Flask service is in [`backend/`](backend). It uses PostgreSQL in deployment, SQLAlchemy migrations, `Numeric`/`Decimal` money values, immutable ledger entries, role checks, idempotency keys, and server-verified PayPal sandbox events.

```bash
cd backend
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env  # set non-development secrets and DATABASE_URL
.venv/bin/flask --app run:app db upgrade
.venv/bin/pytest tests -q
```

PayPal is unconfigured until sandbox credentials are supplied. The payout adapter defaults to a labelled simulator and never reports submission as a successful beneficiary receipt. SMS/USSD and AI endpoints remain pending the approved provider/API decisions.

## Integration, AI and feature-phone layer (Claude scope)

Added on `feat/ai-integration-qa`: AI drafting, translation, assistance and search behind a provider abstraction with deterministic fallbacks; USSD/SMS in English and Kiswahili with a labelled simulator; role assignment, beneficiary verification, ledger-backed balances and keyword search; sign-in rate limits, request IDs and uniform error envelopes; and a typed frontend client in `contracts/fundbridge-client.ts`.

- Quick start, demo data and smoke test: [`docs/RUNBOOK.md`](docs/RUNBOOK.md) · demo script: [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md) · release checklist: [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md)
- Setup, providers, deployment and what is live versus simulated: [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md)
- Frontend guide and new endpoints: [`docs/integration/operations-and-frontend.md`](docs/integration/operations-and-frontend.md)
- AI and SMS/USSD API: [`docs/integration/ai-messaging-api.md`](docs/integration/ai-messaging-api.md)
- Open defects and cross-team requests: [`docs/integration/COORDINATION.md`](docs/integration/COORDINATION.md)

`pytest tests` includes a live end-to-end suite (`tests/e2e`) that runs the API under gunicorn on a migrated database and drives every user journey over HTTP. PayPal and OpenAI are local test doubles there, not live services.

