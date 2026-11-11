# FundBridge backend release-readiness assessment

Assessment scope: `feat/backend-core`, evaluated from commit `967781de5a021ab7c1ca011e05e0df05b2d1b04b` on 2026-11-11. This is an evidence record, not an assertion of provider certification. `PASS` means the repository implementation and its automated tests cover the stated boundary; `SIMULATED` means a deterministic local adapter/double was exercised; `BLOCKED` needs an owner account, credential, approval, or operating service.

## Requirements-to-implementation matrix

| Area | Implementation and evidence | Release state |
|---|---|---|
| Campaign lifecycle | Creator-only draft creation/editing/submission; reviewer/admin oldest-first queue; self-review refusal; approval publishes and rejection returns a draft. Audited in `routes.py`; covered by campaign, queue and live journey tests. | PASS (automated) |
| Authentication and donor history | Donor-only public registration; login issues a 15-minute JWT; protected-route envelopes, caller-owned donation history/detail, password hashes and rate limiting are exercised in auth, hardening and journey tests. No logout/revocation/refresh flow exists. | PARTIAL — no token revocation/refresh |
| Beneficiary onboarding and privacy | Agent/admin onboarding binds only a provisioned beneficiary account; reviewer/admin verification is revision-guarded; phone/destination changes force reverification; profile/campaign access is role/ownership limited. Tests cover cross-account denial and re-verification. | PASS (automated) |
| Staff permissions | Admin role assignment, reviewer campaign queue and beneficiary verification, self-review/self-approval refusal, and audit records are implemented and tested. | PASS (automated) |
| PayPal order and capture | Server creates the donation ID before the provider call; Orders v2 request includes `Prefer: return=representation`; canonical order ID, reference, amount and currency are validated; minimal responses are fetched and revalidated; capture is server-side only. `test_paypal_adapter.py`, API safety tests and HTTP provider-double journeys cover this. | SIMULATED — no PayPal Sandbox credential run |
| PayPal webhook and reconciliation | PayPal signature-verification endpoint is called before handling an event; provider event IDs de-duplicate delivery; completion and ledger write share one transaction; reconciliation never creates another capture and leaves non-final captures pending. | SIMULATED — no real webhook/Sandbox event |
| Ledger, refunds and reversals | `Numeric(18,2)`/`Decimal`, unique capture/reference constraints, transactional donation credit and payout reservation, plus PostgreSQL locking/concurrency tests are present. Refund/reversal/dispute provider processing is **not** implemented despite model status values. | PARTIAL — refunds/reversals/disputes absent |
| Payouts | Verified beneficiary, balance reservation, requester-scoped idempotency, reviewer/admin approval and no self-approval are enforced and audited. The only configured provider is a simulator; approval is not settlement and no endpoint marks it paid. | BLOCKED for real payouts — provider, licensing and callback contract required |
| AI assistance | Typed provider boundary, rate limits, PII/hostile-output guardrails and deterministic fallback are implemented. Tests verify prompts cannot alter financial, beneficiary, campaign or audit records. | SIMULATED — no OpenAI live verification |
| SMS/USSD | Form-only authenticated callbacks; separate opt-in JSON simulator; English/Kiswahili flows; hashed PINs, expiry/lockout/reset, callback de-duplication and delivery reports are covered. Africa's Talking adapter is exercised through a local double. | SIMULATED — shortcode/service code and provider approval required |
| Security and privacy | JWT/role/object checks, error envelopes, input validation, rate limits, callback token/IP controls, request IDs, query/body-free app access logs and secret scan reviewed. Multi-worker rate limiting remains in-process only. | PARTIAL — shared limiter/production security review still required |
| Operations and deployment | Alembic has one head; upgrade, rollback/re-upgrade, historical financial preservation and PostgreSQL concurrency suites exist. Health endpoint, configuration template and deployment guide exist. No configured backups, restore drill, production monitoring, or alerting exists. | PARTIAL — operational controls not configured |

## Provider and owner actions

1. Create a PayPal Sandbox app; supply `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, `PAYPAL_WEBHOOK_ID`; register the documented HTTPS webhook; run a real Sandbox approval/capture and replay test. Production also requires the business account/app approval.
2. Select and contract a licensed beneficiary payout provider (for example Daraja B2C or a regulated aggregator), obtain its KYC/approval/credentials, then implement and test submission, callback authentication, settlement and reversal reconciliation. Do not call the simulator a payout integration.
3. Obtain Africa's Talking credentials, a two-way SMS shortcode and USSD service code/telco approval; configure callback HTTPS, secret and allowed IP ranges; conduct live delivery and retry tests.
4. Supply an approved OpenAI key/model decision and run `flask --app run:app fundbridge-ai check`; assess applicable event and privacy requirements first.
5. Provide production PostgreSQL, TLS/reverse-proxy settings, a single allowed `FRONTEND_ORIGIN`, a shared rate-limit store for more than one worker/instance, backups with a restore drill, error monitoring, and payment/payout outage alerts.
6. Approve a refund, reversal and dispute product/ledger contract before exposing those capabilities. They are not safe to infer from the current donation status enum.

## Release gates

- **Hackathon demonstration:** conditional PASS once the automated suite below is green and the demo uses clearly labelled local doubles/simulators or approved Sandbox credentials.
- **Production financial launch:** FAIL. Real PayPal lifecycle verification, a licensed payout route, refund/reversal/dispute handling, backups/restore, monitoring, shared rate limiting and production security operations remain required.

## Exact verification record

Run from `backend/` with a disposable PostgreSQL 16 database:

```bash
POSTGRES_TEST_DATABASE_URL='postgresql+psycopg://user@/fundbridge_release_gate?host=/tmp&port=55434' \
  .venv/bin/python -m pytest tests -q
```

The same command initially fails under an execution sandbox that prohibits both loopback sockets and the PostgreSQL Unix socket; that is an environment restriction, not a passing result. Outside that restriction, the working checkout completed **276 passed, 6 skipped, 144 warnings in 187.11s**. A clean `git archive HEAD` checkout completed the same command with **276 passed, 6 skipped, 144 warnings in 167.77s**. The skips are opt-in live-provider tests; live OpenAI, PayPal Sandbox, and Africa's Talking tests were not run without credentials.
