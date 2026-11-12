# FundBridge backend API contract (implementation draft)

Base path: `/api/v1`. Responses use `{ "data": ..., "meta": {} }`; failures use the shared `{ "error": { "code", "message", "details" } }` envelope. Resource IDs are UUIDs and money is a decimal string plus uppercase ISO-4217 `currency`.

Authentication failures use HTTP 401 with `AUTH_REQUIRED`, `INVALID_TOKEN`, `TOKEN_EXPIRED`, or `INVALID_CREDENTIALS`; protected-resource authorization failures use HTTP 403. Login does not reveal whether an account exists.

Implemented endpoints: `GET /health`, `GET /api/v1/public/config`, auth register/login/me, campaign browse/detail/create/update/submit/review/review-queue/current-creator list, assisted beneficiary onboarding, beneficiary self-profile/update, donation order creation/server-side capture/reconciliation/detail/current-donor list, PayPal webhook, payout request/list/detail, and payout review.

Registration and sign-in are deliberately separate: `POST /auth/register` creates a donor account and returns `{id, role}` with HTTP 201, never an access token. Clients must then call `POST /auth/login` and present its `access_token` before accessing protected routes. Public campaign detail contains ledger-backed `raised` (`{amount,currency}`), but not `beneficiary_id`; the campaign creator, reviewers, and admins receive `beneficiary_id` for editing/review flows. `GET /campaigns/{id}/funds` remains the authoritative richer balance endpoint.

`GET /campaigns/review-queue?page=1&page_size=20` is restricted to reviewer/admin accounts. It returns submitted, pending campaigns ordered oldest-first and pagination metadata `{page,page_size,total}`. `POST /campaigns` returns `409 SLUG_ALREADY_EXISTS` in the shared error envelope for a duplicate slug.

`GET /beneficiaries/me/campaigns?page=1&page_size=20` is restricted to the authenticated `beneficiary` role. It returns only campaigns whose `beneficiary_id` belongs to that caller's own profile, newest-first (then descending ID), with `{page,page_size,total}` metadata. Items include public campaign fields, the caller's own `beneficiary_id`, `created_at`/`updated_at`, and ledger-backed `raised`; no beneficiary phone number, payout destination, or other profile data is exposed. A beneficiary with no profile or no campaigns receives an empty list. Review-queue items additionally contain `submitted_at`, the submission state-transition timestamp.

`GET /beneficiaries/lookup?q=` is restricted to creator/admin accounts for campaign creation. It returns only beneficiary ID, display name, country code, and verification status; phone numbers, account links, and payout information are never returned.

`POST /campaigns/{id}/review` accepts `{ "decision": "approve" | "reject" }` for a reviewer/admin. A reviewer cannot review their own campaign. Approval publishes the campaign; rejection returns it to draft. Both decisions are audited.

`POST /donations/orders` and `POST /payouts` require authenticated accounts and an `Idempotency-Key`. Guest donation is unavailable until an approved guest-ownership/capture contract exists. Payment completion occurs only after verified PayPal data confirms the stored order association, donation reference, capture status, amount, and currency. The Create Order request sends `Prefer: return=representation`; if PayPal returns a minimal response, the server retrieves and validates the authoritative representation before associating it. Missing, malformed, or mismatched order responses are rejected without committing a donation/order association. `POST /donations/{id}/reconcile` retrieves authoritative PayPal order state after an ambiguous capture timeout; it never issues another capture, credits only a verified completed capture, and leaves pending/awaiting-settlement provider states pending. Denied or voided orders are marked failed. Reconciliation is idempotent. Payout simulator submission, when later enabled, must remain `submitted`/`pending_confirmation`; it must never claim `succeeded`.

Idempotency keys are scoped to the authenticated actor and operation. For donation-order creation, PostgreSQL serializes same-actor/key requests before any PayPal call: identical replays return the same donation/order association, while a changed payload returns `IDEMPOTENCY_KEY_REUSED`. Reconciliation locks the donation only for the state transition after provider retrieval; concurrent callers observe the completed/failed authoritative state and cannot write another ledger credit. Payout requesters cannot approve their own requests, including admins.

Unavailable (not simulated): guest donation/capture, logout/revocation, payout provider submission/callback reconciliation, and provider-backed refund/reversal/dispute processing. AI and SMS/USSD endpoints are implemented below and remain assistance or provider-boundary features: they cannot approve campaigns or beneficiaries, change financial records, initiate payments, or settle payouts. Campaign review/publish is implemented above; provider-backed capabilities require approved contracts and credentials.

Assisted onboarding is implemented for an agent/admin. It may link only an existing active account already provisioned with the `beneficiary` role; public registration always creates a donor and cannot grant roles. Admin role assignment and reviewer/admin beneficiary verification are documented in the integration addendum below. Payout requests reject profiles that are not `verified`.

Testing: the PostgreSQL reservation-concurrency test is included and runs only when `POSTGRES_TEST_DATABASE_URL` names an isolated test database. It is deliberately skipped for SQLite because SQLite cannot validate `FOR UPDATE` locking behavior.

The repository CI workflow provisions PostgreSQL and sets `POSTGRES_TEST_DATABASE_URL`, so pull requests run the reservation-concurrency test against PostgreSQL. It has not yet passed in CI until GitHub Actions reports a successful run.

## Addendum: integration branch (`feat/ai-integration-qa`, PR #3)

PR #3 adds the following on top of this contract. Details are in `docs/integration/operations-and-frontend.md` and `docs/integration/ai-messaging-api.md`.

- AI (`/api/v1/ai/*`), SMS/USSD gateway callbacks and simulator (`/api/v1/messaging/*`), and `GET /api/v1/integrations/status`.
- Role assignment by an admin (`GET /admin/users`, `PUT /admin/users/{id}/role`) and the first-admin CLI `flask fundbridge-admin create-admin`.
- Beneficiary verification by a reviewer or admin (`GET /beneficiaries`, `GET /beneficiaries/{id}`, `POST /beneficiaries/{id}/verification` with a `revision` that guards against stale reviews).
- `GET /campaigns/{id}/funds` (ledger-backed balances) and `GET /campaigns?q=` (keyword search).
- Uniform error envelopes for 405, 500 (`INTERNAL_ERROR` with `request_id`), provider failures (`502 PROVIDER_REQUEST_REJECTED`, `503 PROVIDER_UNAVAILABLE`) and rate limits (`429 RATE_LIMITED`). `X-Request-ID` is on every response.
- The provider callbacks `POST /messaging/ussd` and `POST /messaging/sms/inbound` accept the gateway's form format and callback authentication only. The separate opt-in, rate-limited development simulator accepts JSON at `POST /messaging/simulator/ussd` and `POST /messaging/simulator/sms`; it is labelled simulated and cannot authenticate as a provider callback.
