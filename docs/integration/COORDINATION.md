# Coordination notes: Claude (AI, feature phones, integration tests, deployment docs) → Codex (backend) and Cursor (frontend)

Branch `feat/ai-integration-qa` (PR #3) is stacked on `feat/backend-core` (PR #2) and merges it regularly. PR #3 stays separate until the canonical backend is ready.
Last merged backend commit: **`b45ee29`** (feat/backend-core). `main` contains the backend through `6fd76b3` plus this branch up to `0b12b4c` (PRs #4, #5, #6); **`main` does not yet contain `b45ee29`**, so it still has C-4b and X-1.
This branch is byte-identical to `feat/backend-core` in every backend-owned file; only tests, docs and `contracts/` differ. Full evidence: `VERIFICATION_CHECKLIST.md`.

## For Codex (canonical backend)

### Status of every tracked item against `b45ee29`

| ID | Item | Status |
|---|---|---|
| C-4, C-4b | PayPal reference and `Prefer: return=representation` | **Fixed**, verified over HTTP with a PayPal-default double |
| R-1, R-1b, declined capture | Reconciliation | Fixed and verified |
| X-1 | Duplicate onboarding audit | **Fixed** (b45ee29), verified |
| P-1 | Phone reverification | Fixed, verified |
| M-1 | Upgrade with existing data | Fixed, verified on SQLite and PostgreSQL |
| **X-2** | Two `?q=` filters ANDed in `list_campaigns()` | **Open**: strict xfail `test_keyword_search_matches_category_as_ported` |
| **R-2** | Parallel reconciles → HTTP 500 | **Open, new**: see below |
| **S-5** | Parallel same-key orders → HTTP 500 instead of replay | **Open, new**: see below |
| M-1b | Old global idempotency uniqueness survives upgrade | Open: strict xfail |
| M-2 | PostgreSQL full rollback leaves enum types | Open: strict xfail |

### R-2 (medium, new): parallel reconciliations return HTTP 500
- Where: `backend/app/api/v1/routes.py` `reconcile_donation()`. Two requests both read `pending`, both call `mark_donation_completed`, and the second `db.session.commit()` raises `IntegrityError` (`UniqueViolation` on the ledger credit).
- Money is safe: the unique constraints keep it to one credit, and the e2e test checks that. But clients get `500 INTERNAL_ERROR` for a benign race, and the logs fill with errors.
- Reproduce on PostgreSQL: `E2E_DATABASE_URL=... pytest tests/e2e/test_zz_financial_integrity.py::test_parallel_reconciliations_never_return_500 --runxfail` → 7 of 8 responses are 500.
- Suggestion: lock the donation row (`with_for_update()`) and re-check its status before calling the provider, or catch `IntegrityError`, roll back, re-read and return the donation. Capture has the same shape: it only avoids the race today because PayPal answers repeat captures with 422.

### S-5 (medium, new): parallel orders with one Idempotency-Key return HTTP 500
- Where: `routes.py` `donation_order()` at `db.session.add(donation); db.session.flush()`. On PostgreSQL the second insert waits for the first transaction, then raises `UniqueViolation` on `uq_donation_donor_idempotency`.
- Exactly one donation is created, which is correct, but the other callers get 500 instead of the replayed donation the contract promises. A double-clicked "Donate" button or a retried request on a slow network hits this.
- Reproduce: `pytest tests/e2e/test_zz_financial_integrity.py::test_parallel_orders_with_one_key_replay_instead_of_500 --runxfail` (PostgreSQL) → 7 of 8 are 500.
- Suggestion: on `IntegrityError` at that flush, roll back, re-select by `(donor_id, idempotency_key)`, check the fingerprint, and return the existing donation. The PayPal order created by the losing request is never used.

### X-2: duplicate search filters
`list_campaigns()` applies both the escaped title/description filter and the ported title/description/category filter. Delete one, keep the escaping and the 100-character cap (`test_keyword_search_without_ai`), and keep category matching if wanted (`test_keyword_search_matches_category_as_ported`).

### API gaps found while reviewing the frontend contract (not defects, missing capabilities)
- **G-6:** a beneficiary cannot list the campaigns they benefit from. `serialize_campaign` has no `beneficiary_id`, and `/me/campaigns` returns campaigns the user *created*. The web payout-request screen therefore cannot find a `campaign_id`. Suggestion: `GET /beneficiaries/me/campaigns`, or `beneficiary_id` in the campaign payload.
- **G-7:** there is no reviewer queue; `GET /campaigns` lists only published campaigns. Suggestion: `GET /campaigns?status=submitted` for reviewers and admins.
- **G-8:** no lookup by `slug`, no pagination beyond 50 results, and no timestamps (`created_at`, `published_at`) in campaign, donation and payout payloads.

### M-1b and M-2
Unchanged; see the strict xfails in `tests/integration/test_migrations.py`.

### Migration chain
The head is `c3f1a9e7d2b4`. Chain new migrations after it; `test_single_alembic_head` guards this.

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
