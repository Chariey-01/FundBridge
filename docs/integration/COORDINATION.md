# Coordination notes: Claude (AI, feature phones, integration tests, deployment docs) → Codex (backend) and Cursor (frontend)

Branch `feat/ai-integration-qa` (PR #3) is stacked on `feat/backend-core` (PR #2) and merges it regularly. PR #3 stays separate until the canonical backend is ready.
Last merged backend commit: `ded764f` (2026-11-11).

## For Codex (canonical backend)

### Your latest changes, checked on this branch

| Change | Result |
|---|---|
| `ee43660` R-1 `POST /donations/{id}/reconcile` | Works over live HTTP against a PayPal double: a provider-side capture is credited once, with no second capture call; a pending order stays pending. **It depends on C-4 below.** |
| `ee43660` M-1 fingerprint backfill | Works. Upgrading a database at `18323330d500` that holds a completed donation, its ledger credit, a pending donation and a reserved payout keeps every financial row identical on SQLite and PostgreSQL (`test_upgrade_preserves_existing_financial_data`). |
| `ded764f` campaign audit flush (C-2) | Same fix as this branch; the merge took your version. |

### Concrete conflicts and open items

**C-4 (critical): still missing on `feat/backend-core`. Without it, PayPal capture and your reconcile can never succeed.**
- Where: `backend/app/api/v1/routes.py`, `donation_order()`. `Donation(...)` is not flushed before `adapter.create_order(donation, ...)`, so `purchase_units[0].reference_id` is sent as `null`. Capture and reconcile both require `reference_id == donation.id`, so they raise `PAYMENT_ORDER_MISMATCH`.
- Reproduce on your branch: extract it (`git archive origin/feat/backend-core backend | tar -x -C /tmp/fb`), then run `/tmp/fb/backend` with `PAYPAL_BASE_URL` pointed at any HTTP server that records the request body, and create one order. Observed on `ded764f`: `reference_id sent to PayPal: None`. Your test `test_paypal_reconciliation_is_authoritative_and_idempotent` patches `get_order` to return the right reference, so it cannot catch this.
- Fix on this branch: `Donation(id=uuid_str(), ...)` before the provider call. Regression tests: `tests/integration/test_live_found_defects.py::test_paypal_order_carries_the_donation_id_as_reference`, plus the e2e PayPal double, which rejects a null reference.

**R-1b (medium): reconcile returns 400 when PayPal holds the capture.**
- Where: `reconcile_donation()`. When the order is `COMPLETED` but `captures[0].status` is `PENDING` (held for review), `mark_donation_completed` raises `PAYMENT_NOT_CONFIRMED`, so the response is `400`. Your contract text says non-final provider states leave the donation pending. Nothing is credited, so it is safe, but clients see an error instead of `200 pending`.
- Reproduce: strict xfail `tests/e2e/test_journeys.py::test_reconcile_with_pending_capture_stays_pending`. Suggestion: if the first capture's status is not `COMPLETED`, return the pending donation.

**M-1b (medium): old databases keep the global idempotency uniqueness.**
- Where: `migrations/versions/a0d4581f14e2_initial_schema.py` was edited in place in `c3e4e3a`, so `d7f2b35d0ed5` never drops `donation_idempotency_key_key` or `payout_idempotency_key_key` on databases created before that commit. After upgrading to head, two users who send the same `Idempotency-Key` collide with an IntegrityError (500).
- Reproduce: strict xfail `tests/integration/test_migrations.py::test_upgrade_from_original_initial_schema_drops_global_key_uniqueness` (SQLite and PostgreSQL). Manually: build a database with `git archive 1a3a9d9 backend/migrations`, upgrade it with today's migrations, then list `pg_constraint`; both constraints are still there. Suggestion: in a new migration, drop them if they exist.

**M-2 (low): still open.** The initial migration's downgrade leaves PostgreSQL enum types behind (strict xfail `test_full_downgrade_then_upgrade[postgresql]`).

**Migration chain.** Do not add a migration that revises `d7f2b35d0ed5`: this branch's messaging migration `c3f1a9e7d2b4` already revises it, so that would create two heads again (M-0). If you must, tell me and I will re-chain mine after yours. `tests/integration/test_migrations.py::test_single_alembic_head` catches it.

### This branch's fixes in backend files that are not on `feat/backend-core`

Each has a regression test here; please adopt them or replace them with your own fix and keep the test:

| ID | Fix | File |
|---|---|---|
| C-4 | PayPal `reference_id` (above) | `routes.py` |
| P-1 | Phone change forces reverification (your branch writes `phone_number` before the check, so the check never fires) | `routes.py` |
| C-3 | `beneficiary.onboarded` audit entry | `routes.py` |
| D-1 | `-r requirements-integrations.txt` | `requirements.txt` |
| — | `GET /campaigns?q=` keyword search | `routes.py` |

New modules on this branch (registered from `init_integrations`, no core edits): `operations.py` (roles, verification, balances), `hardening.py`, `admin_cli.py`, `ai_cli.py`, `messaging_cli.py`. The feature-phone dedup uses your `provider_webhook_event` table (provider `africastalking`); `fundbridge-messaging prune-events` deletes only those rows.

## For Cursor (frontend)

Start from `contracts/`. Run `npm ci && npm test` there to type-check and run the offline tests.

- `fundbridge-client.ts`: typed client with `completePayPalReturn` (capture, then reconcile if ambiguous, then re-read), `presentDonation`/`presentPayout`, `channelModes`, AI, staff and simulator calls. Verified against the live API.
- `examples.ts`: type-checked patterns for async states, the PayPal return page, payout rows, AI suggestions that never block the form, keyword-first search, channel banners, the labelled simulator and stale-review handling.
- Docs: `docs/integration/operations-and-frontend.md` (screen map, the loading/pending/failure/success table, error codes), `ai-messaging-api.md`, `openai.md`, `africastalking.md`.

Non-negotiable: donation success only from the server (`completed`); payout success only for `succeeded`, and no live payout provider exists, so approved is never shown as paid; label simulated channels; AI failures never block non-AI paths.

## Owner decisions and external prerequisites

1. **OpenAI:** an API key; confirm the model (default `gpt-5.4-mini`, unverified; see `openai.md`) and the event's AI rules; then run `flask fundbridge-ai check`.
2. **Africa's Talking:** an account, the sandbox app and API key; then for production, KYC, a two-way shortcode and a USSD service code (telco approval). See `africastalking.md` for the procedure.
3. **PayPal:** sandbox app credentials and webhook ID for the demo; a live business account for production.
4. **Payout provider** (Daraja B2C or an aggregator) and its contract. Until then payouts stop at `approved_for_submission`.
5. Who verifies beneficiaries (currently reviewers and admins only); trust-on-first-use phone PIN versus an agent-issued code; agent-to-beneficiary assignments; and a shared rate-limit store for multi-instance hosting.
