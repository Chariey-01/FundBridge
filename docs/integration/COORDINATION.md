# Coordination notes: Claude (AI, messaging, integration, QA) → Codex (backend) and Cursor (frontend)

Branch `feat/ai-integration-qa` (PR #3) is stacked on `feat/backend-core` (PR #2) and merges it regularly.
Last merged backend commit: `8b6b285` (2026-11-11).

## For Codex (backend)

### Verified fixed in `c3e4e3a`…`397ef42`

Each was reproduced before the fix and is now a passing regression test in `backend/tests/integration/test_financial_security.py`:

| ID | Defect | Result |
|---|---|---|
| S-1 | Idempotency key lookup was global | Fixed: scoped to the actor |
| S-2 | Key reuse with a different body returned the original | Fixed: `400 IDEMPOTENCY_KEY_REUSED` (409 was suggested; 400 accepted) |
| S-3 | Admin could approve own payout | Fixed: `403 SELF_APPROVAL_FORBIDDEN` |
| A-1 | JWT failures used `{"msg": …}` | Fixed: `AUTH_REQUIRED` / `INVALID_TOKEN` / `TOKEN_EXPIRED` |
| A-2 | Wrong password returned 403 | Fixed: 401, identical for unknown accounts |
| A-3 | HTML 404 | Fixed: `NOT_FOUND` envelope |

### Found during integration and fixed on this branch, in backend files

Minimal edits, each with a regression test. Please keep them when merging, or replace them with your own fix and keep the test.

| ID | Severity | Defect | Fix (file) |
|---|---|---|---|
| C-2 | **Critical** | `POST /campaigns` always returned 500: the audit row was built before the campaign was flushed, so `resource_id` was NULL. No test had ever created a campaign through the API. | Flush before the audit row (`routes.py`) |
| C-4 | **Critical** | `POST /donations/orders` sent the PayPal order with `reference_id: null` (the id is generated at INSERT). Capture checks `reference_id == donation.id`, so every real capture would fail with `PAYMENT_ORDER_MISMATCH`. Unit tests mocked the adapter. | Assign the donation id before the provider call (`routes.py`) |
| P-1 | High | The phone-change reverification added in `c3e4e3a` never ran: the generic field loop wrote `phone_number` first, so the new branch compared the value with itself. | Remove `phone_number` from the generic loop (`routes.py`) |
| M-0 | High | Two Alembic heads (`c3f1a9e7d2b4` and `d7f2b35d0ed5` both revised `18323330d500`), so `flask db upgrade` failed. | Messaging migration re-chained after `d7f2b35d0ed5` (Claude's migration). **Chain new migrations after `c3f1a9e7d2b4`.** |
| D-1 | High | `requirements.txt` lacked the AI/messaging dependencies that `create_app` imports, so a fresh install crashed. | `-r requirements-integrations.txt` (`requirements.txt`) |
| C-3 | Medium | Assisted beneficiary onboarding wrote no audit entry. | `beneficiary.onboarded` audit row (`routes.py`) |
| T-2 | Medium (test) | `tests/test_postgres_concurrency.py` read `beneficiary_user.id` from a detached instance in worker threads, so it could not pass on PostgreSQL. | Capture the id before the threads |
| — | Feature | No plain keyword search. | `GET /campaigns?q=` with escaped wildcards (`routes.py`, additive) |

### Open for Codex

| ID | Severity | Issue | Reproduction / suggestion |
|---|---|---|---|
| R-1 | High | If capture times out after PayPal captured, a retry gets `422 ORDER_ALREADY_CAPTURED` and the donation stays `pending` unless the webhook arrives. | On that issue, `GET /v2/checkout/orders/{id}` and complete through `mark_donation_completed` with the verified capture. |
| M-1 | Medium | `d7f2b35d0ed5` adds NOT NULL `idempotency_fingerprint` with no server default, so upgrading a database that holds donations fails. `a0d4581f14e2` was edited in place, so databases built from the old version keep the global `idempotency_key` unique constraints. | strict xfail `tests/integration/test_migrations.py::test_upgrade_with_existing_donation_rows`. Add `server_default=""` and drop the old constraints if present. |
| M-2 | Low | The initial migration's downgrade leaves PostgreSQL enum types behind, so re-upgrading after a full rollback fails. | strict xfail `test_full_downgrade_then_upgrade[postgresql]`. Drop the enum types in `downgrade()`. |
| G-5 | — | No payout submission or provider-callback endpoint; payouts stop at `approved_for_submission`. | Needs an owner decision on the payout provider. |
| — | Low | `GET /public/config` reports `feature_phone: {sms: false, ussd: false}` regardless of configuration. | Source it from `app.api.v1.messaging.integration_status()`. The client uses `/integrations/status`. |
| — | Low | `API_CONTRACT.md` lists AI, SMS/USSD, role provisioning and beneficiary verification as unavailable; they exist on this branch. | See the addendum at the end of `API_CONTRACT.md`. |
| — | Low | `Query.get()` legacy warnings (SQLAlchemy 2.x). | `db.session.get(Model, id)` |

### Added on this branch (new modules, registered from `init_integrations`)

- `app/api/v1/operations.py`: role assignment, beneficiary list/detail/verification (stale-review protection, no self-verification), ledger-backed campaign balances.
- `app/integrations/hardening.py`: request IDs, access log without query strings, sign-in and order rate limits, JSON envelopes for provider failures, HTTP errors and unhandled exceptions (no SQL parameters in logs).
- `app/integrations/admin_cli.py`: `flask fundbridge-admin create-admin`.

If you would rather own role and verification endpoints in `routes.py`, move them; the tests in `tests/integration/test_operations.py` and `tests/e2e` define the behaviour.

### Integration points that touch backend files

- `app/__init__.py`: one line, `init_integrations(app)`.
- `routes.py`: the fixes above (C-2, C-3, C-4, P-1, `q` search).
- `requirements.txt`: `-r requirements-integrations.txt`. `requirements-deploy.txt` adds gunicorn.
- `.env.example`: AI, messaging and rate-limit variables appended.

## For Cursor (frontend)

No frontend branch exists yet. Start from:

- `contracts/fundbridge-client.ts`, the typed client. It is verified against the live API, with the PayPal return flow, payout status, balances and channel labels built in.
- `docs/integration/operations-and-frontend.md`, which has the screen-to-endpoint map, state rules and error codes.
- `docs/integration/ai-messaging-api.md` for AI and SMS/USSD.

Non-negotiable: donation success only from `GET /donations/{id}` → `completed` (use `completePayPalReturn`); payout success only for `succeeded` (no live payout provider exists); label simulated channels; keep every non-AI path working when AI fails.

## Owner decisions still open

1. Payout provider (Daraja B2C or an aggregator) and its contract. Until then payouts cannot be submitted.
2. PayPal: sandbox app credentials and webhook for the demo; live account and review for production.
3. Africa's Talking account, shortcode and USSD service code. None are configured or verified.
4. OpenAI model (`OPENAI_MODEL`, default `gpt-4o-mini`) and the event's AI rules.
5. Who may verify beneficiaries. Currently reviewers and admins only; the onboarding agent cannot.
6. Phone PIN: trust on first use (current, and now only for verified profiles) or an agent-issued one-time code.
7. Agent-to-beneficiary assignments. Today any agent sees all beneficiaries and phone support requests.
8. Multi-instance hosting needs a shared rate-limit store (for example Redis). The current setup is one process.
