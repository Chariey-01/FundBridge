# Coordination notes: Claude (AI, feature phones, integration tests, deployment docs) → Codex (backend) and Cursor (frontend)

Branch `feat/ai-integration-qa` (PR #3) is stacked on `feat/backend-core` (PR #2) and merges it regularly. PR #3 stays separate until the canonical backend is ready.
Last merged backend commit: `6fd76b3` (feat/backend-core after PR #3 merged), plus `9d3f80c`. PR #2 merged into `main` (backend through `3edf6c4`); PR #3 merged into `feat/backend-core`. `main` does not yet contain PR #3.
This branch is byte-identical to `feat/backend-core` in every backend-owned file; only tests and docs differ.

## For Codex (canonical backend)

### Status of every tracked item (reviewed against `feat/backend-core` 6fd76b3)

| ID | Item | Status | Evidence on this branch |
|---|---|---|---|
| C-4 | PayPal `reference_id` must be the donation id | **Fixed** (b7bf45b flush) | `test_paypal_order_carries_the_donation_id_as_reference` passes |
| **C-4b** | **create-order response validation vs PayPal's default response** | **Open, blocks all real PayPal orders** | strict xfail ×2 (below) |
| R-1 | Ambiguous capture reconciliation | Fixed (ee43660) | e2e `test_reconcile_after_provider_side_capture_completes_donation_once` |
| R-1b | Pending capture must stay pending during reconcile | Fixed (b7bf45b) | e2e `test_reconcile_with_pending_capture_stays_pending` |
| — | Declined/denied capture, cancelled order → failed | Added (9d3f80c) | e2e `test_reconcile_with_declined_capture_marks_donation_failed` |
| M-1 | Upgrade with existing donations | Fixed (ee43660) | `test_upgrade_preserves_existing_financial_data` (SQLite + PostgreSQL, every financial row identical) |
| M-1b | Old global idempotency-key uniqueness survives upgrade | Open | strict xfail `test_upgrade_from_original_initial_schema_drops_global_key_uniqueness` |
| M-2 | PostgreSQL full rollback leaves enum types | Open | strict xfail `test_full_downgrade_then_upgrade[postgresql]` |
| P-1 | Phone change forces reverification | Fixed (3edf6c4) | `test_phone_change_requires_reverification`, phone-channel tests |
| C-3 | Onboarding audit | Ported (3edf6c4), but see **X-1** | strict xfail |
| — | Keyword search | Ported (3edf6c4), but see **X-2** | strict xfail; `test_keyword_search_without_ai` passes |
| **X-1** | **Duplicate onboarding audit (merge artifact)** | **Open** | strict xfail `test_assisted_onboarding_is_audited` |
| **X-2** | **Duplicate `?q=` filters (merge artifact)** | **Open** | strict xfail `test_keyword_search_matches_category_as_ported` |

### C-4b (critical): PayPal order creation fails against PayPal's default response
- Where: `backend/app/api/v1/routes.py` `donation_order()` (b7bf45b) requires `order["purchase_units"][0]` with `reference_id`, `amount.currency_code` and `amount.value` in the **create-order response**. `backend/app/integrations/payments/paypal.py` `create_order()` sends no `Prefer` header. PayPal documents `Prefer: return=minimal` as the default, which returns only `id`, `status` and `links`; the full order requires `Prefer: return=representation`. Result: every real order → `400 PAYMENT_ORDER_MISMATCH`.
- Why your suite passes: `test_api_safety.py` mocks `create_order` to return `purchase_units`.
- Reproduce: `pytest tests/integration/test_live_found_defects.py::test_paypal_default_minimal_create_order_response_is_accepted --runxfail` (mocked minimal response) and `pytest tests/e2e/test_journeys.py::test_order_creation_against_paypal_default_response --runxfail` (live HTTP; the PayPal double honours `Prefer` like PayPal).
- Suggested fix, validated locally and not committed: add `"Prefer": "return=representation"` to the create-order request headers. Both reproductions then XPASS. Alternatively, drop the response check; capture and reconcile already verify the reference and amount.
- Note: until this is fixed, the e2e stacks run with a labelled accommodation (`PayPalDouble.assume_representation = True`) so downstream journeys stay testable. It is removed when C-4b is fixed.

### X-1 and X-2: merge artifacts from PR #3 into `feat/backend-core` (6fd76b3)
Both the integration-branch fixes and your ports (3edf6c4) survived the merge:
- **X-1** `assisted_beneficiary()`: two `AuditLog(action="beneficiary.onboarded")` writes, the one-line version with `metadata_json` and your two-line version. Each onboarding creates two audit rows.
- **X-2** `list_campaigns()`: two `?q=` filters ANDed together. The first (escaped, title/description, 100-character cap) excludes rows your second filter would match by category, so `?q=education` never finds an education campaign by category.
- Suggested fix, validated locally and not committed: delete one block of each pair. Both reproductions then XPASS. Please keep the wildcard escaping and the 100-character cap in whichever search filter remains: `test_keyword_search_without_ai` asserts that `%` and `_` match literally.

### M-1b and M-2
Unchanged; see the strict-xfail tests in `tests/integration/test_migrations.py`. Manual M-1b check: build a database from `git archive 1a3a9d9 backend/migrations`, upgrade it with today's migrations, and `donation_idempotency_key_key` and `payout_idempotency_key_key` are still present.

### Migration chain
The head is `c3f1a9e7d2b4` (messaging tables, revising `d7f2b35d0ed5`). Chain any new migration after it; `test_single_alembic_head` catches a second head.

## For Cursor (frontend)

`feat/frontend-core` has not been published, so nothing here has been checked against it. Start from `contracts/` (see `contracts/README.md` for how to consume it). Run `npm ci && npm test` there to type-check and run the offline tests.

- `fundbridge-client.ts`: typed client with `completePayPalReturn` (capture, then reconcile the same donation id if ambiguous, then re-read; outcomes `confirmed`, `failed`, `not_approved`, `provider_unavailable`, `needs_review`, `pending`), `presentDonation`/`presentPayout`, `channelModes`, AI, staff and simulator calls. Verified against the live API.
- `examples.ts`: type-checked patterns for async states, the PayPal return page, payout rows, AI suggestions that never block the form, keyword-first search, channel banners, the labelled simulator and stale-review handling.
- Docs: `docs/integration/operations-and-frontend.md` (screen map, the loading/pending/failure/success table, error codes), `ai-messaging-api.md`, `openai.md`, `africastalking.md`.

Non-negotiable: donation success only from the server (`completed`); payout success only for `succeeded`, and no live payout provider exists, so approved is never shown as paid; label simulated channels; AI failures never block non-AI paths.

## Owner decisions and external prerequisites

Step-by-step checks and the evidence to record for each provider: `EXTERNAL_CHECKLIST.md`.

1. **OpenAI:** an API key; confirm the model (default `gpt-5.4-mini`, unverified; see `openai.md`) and the event's AI rules; then run `flask fundbridge-ai check`.
2. **Africa's Talking:** an account, the sandbox app and API key; then for production, KYC, a two-way shortcode and a USSD service code (telco approval). See `africastalking.md` for the procedure.
3. **PayPal:** sandbox app credentials and webhook ID for the demo; a live business account for production.
4. **Payout provider** (Daraja B2C or an aggregator) and its contract. Until then payouts stop at `approved_for_submission`.
5. Who verifies beneficiaries (currently reviewers and admins only); trust-on-first-use phone PIN versus an agent-issued code; agent-to-beneficiary assignments; and a shared rate-limit store for multi-instance hosting.
