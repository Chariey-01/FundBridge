# FundBridge backend API contract (implementation draft)

Base path: `/api/v1`. Responses use `{ "data": ..., "meta": {} }`; failures use the shared `{ "error": { "code", "message", "details" } }` envelope. Resource IDs are UUIDs and money is a decimal string plus uppercase ISO-4217 `currency`.

Implemented endpoints: `GET /health`, `GET /api/v1/public/config`, auth register/login/me, campaign browse/detail/create/update/submit, assisted beneficiary onboarding, donation order creation/server-side capture, PayPal webhook, payout request, and payout review.

`POST /donations/orders` and `POST /payouts` require authenticated accounts and an `Idempotency-Key`. Guest donation is unavailable until an approved guest-ownership/capture contract exists. Payment completion occurs only after verified PayPal data confirms the stored order association, donation reference, capture status, amount, and currency. Payout simulator submission, when later enabled, must remain `submitted`/`pending_confirmation`; it must never claim `succeeded`.

Unavailable (not simulated): guest donation/capture, logout/revocation, campaign review/publish, beneficiary self-service, donation retrieval/history, payout retrieval/submission/callback reconciliation, AI, and SMS/USSD endpoints. These require final approved contracts and provider choices.

Testing: the PostgreSQL reservation-concurrency test is included and runs only when `POSTGRES_TEST_DATABASE_URL` names an isolated test database. It is deliberately skipped for SQLite because SQLite cannot validate `FOR UPDATE` locking behavior.
