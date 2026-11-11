# FundBridge backend

## Configuration and setup

Copy `.env.example` to `.env`, set `SECRET_KEY`, `JWT_SECRET_KEY`, and a
PostgreSQL `DATABASE_URL`, then install `requirements.txt`. Apply migrations
with `flask --app run.py db upgrade`; tests use SQLite and need no provider
credentials.

## Integrations

`paypal_simulator` and `payout_simulator` are deterministic development
adapters. They do **not** submit funds or invent success: an authenticated
simulator webhook with `X-FundBridge-Simulator: verified` is required to mark
a donation completed. Live PayPal and local-wallet provider adapters remain
blocked pending approved credentials, product eligibility, signature-verification
details, and compliance review.

No SMS/USSD or AI provider is configured yet; no endpoint claims either is live.

## Financial behaviour

Amounts use `Numeric(18,2)` and decimal strings in responses. A completed
donation writes one immutable ledger entry. Payout requests reserve available
completed funds in the same database transaction and require reviewer approval
before any future provider submission. Stored payout destination references are
never returned by the API.

## Tests

Run `pytest` from this directory. External services are mocked/simulated; no
test calls a live payment, payout, SMS, or AI provider.
