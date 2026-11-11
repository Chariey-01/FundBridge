# FundBridge backend API contract (implementation draft)

Base path: `/api/v1`. Responses use `{ "data": ..., "meta": {} }`; failures use the shared `{ "error": { "code", "message", "details" } }` envelope. Resource IDs are UUIDs and money is a decimal string plus uppercase ISO-4217 `currency`.

Authentication failures use HTTP 401 with `AUTH_REQUIRED`, `INVALID_TOKEN`, `TOKEN_EXPIRED`, or `INVALID_CREDENTIALS`; protected-resource authorization failures use HTTP 403. Login does not reveal whether an account exists.

Implemented endpoints: `GET /health`, `GET /api/v1/public/config`, auth register/login/me, campaign browse/detail/create/update/submit/review/current-creator list, assisted beneficiary onboarding, beneficiary self-profile/update, donation order creation/server-side capture/reconciliation/detail/current-donor list, PayPal webhook, payout request/list/detail, and payout review.

`POST /campaigns/{id}/review` accepts `{ "decision": "approve" | "reject" }` for a reviewer/admin. A reviewer cannot review their own campaign. Approval publishes the campaign; rejection returns it to draft. Both decisions are audited.

`POST /donations/orders` and `POST /payouts` require authenticated accounts and an `Idempotency-Key`. Guest donation is unavailable until an approved guest-ownership/capture contract exists. Payment completion occurs only after verified PayPal data confirms the stored order association, donation reference, capture status, amount, and currency. `POST /donations/{id}/reconcile` retrieves authoritative PayPal order state after an ambiguous capture timeout; it never issues another capture, credits only a verified completed capture, and leaves non-final provider states pending. Payout simulator submission, when later enabled, must remain `submitted`/`pending_confirmation`; it must never claim `succeeded`.

Idempotency keys are scoped to the authenticated actor and operation. Replaying the same key with a different canonical request fingerprint returns `IDEMPOTENCY_KEY_REUSED`; a replay never returns another actor's resource. Payout requesters cannot approve their own requests, including admins.

Unavailable (not simulated): guest donation/capture, logout/revocation, payout provider submission/callback reconciliation, AI, and SMS/USSD endpoints. Campaign review/publish is implemented above; the remaining unavailable capabilities require final approved contracts and provider choices.

Assisted onboarding is implemented for an agent/admin. It may link only an existing active account already provisioned with the `beneficiary` role; public registration always creates a donor and cannot grant roles. The role-provisioning and beneficiary-verification workflow is unavailable pending an approved admin/review contract. Payout requests reject profiles that are not `verified`.

Testing: the PostgreSQL reservation-concurrency test is included and runs only when `POSTGRES_TEST_DATABASE_URL` names an isolated test database. It is deliberately skipped for SQLite because SQLite cannot validate `FOR UPDATE` locking behavior.

The repository CI workflow provisions PostgreSQL and sets `POSTGRES_TEST_DATABASE_URL`, so pull requests run the reservation-concurrency test against PostgreSQL. It has not yet passed in CI until GitHub Actions reports a successful run.
