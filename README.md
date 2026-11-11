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
