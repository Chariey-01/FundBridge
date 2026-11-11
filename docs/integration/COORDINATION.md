# Coordination notes: Claude (AI, feature phones, integration tests, deployment docs) → Codex (backend) and Cursor (frontend)


## Current state (updated 2026-11-11)

| Branch | Owner | Latest known / verified | Notes |
|---|---|---|---|
| `feat/backend-core` | Codex | **`7115094`**, merged and verified by this branch's full suite | canonical backend; PR #8 (→ `main`) open |
| `feat/frontend-core` | Cursor | **not on the remote** (checked 2026-11-11 evening with `git ls-remote`; no frontend branch of any name) | nothing could be verified |
| `feat/ai-integration-qa` | AI, messaging, integration, demo infrastructure | see `git log`; PR **#7** (→ `feat/backend-core`) is open | byte-identical to `feat/backend-core` in every backend-owned file |
| `main` | maintainer | `6f3c335` | **lacks `b45ee29`..`7115094`**: deploy from `feat/backend-core` until PR #8 is merged |

### Integration blockers, by severity
1. `main` lacks `b45ee29`..`7115094` (C-4b, X-1, R-2, S-5, X-2, M-1b, M-2 fixes). Owner: maintainer, merging PR #8 (`feat/backend-core` → `main`).
2. The frontend is not published, so no route, payload, loading/error state or "no false success" rule has been checked against Cursor's code, and there is no browser walkthrough (`FRONTEND_WALKTHROUGH.md`). Owner: Cursor.
3. **G-6** (beneficiary campaign list) and **G-7** (reviewer queue) are missing, which blocks the web beneficiary payout and reviewer screens. Proposed contracts are in `tests/integration/test_proposed_contract_gaps.py`. Owner: Codex. Demo workaround: the campaign IDs the seed prints.
4. Credentials: PayPal sandbox, OpenAI key, Africa's Talking account, shortcode and USSD code, payout provider. Owner: project owner.
5. Kiswahili wording has not been reviewed by a native speaker: `kiswahili-review.md`. Owner: project owner.

### Work completed on this branch (most recent first)
- **Final sprint (2026-11-11 evening):**
  - merged `7115094`; R-2, S-5 and X-2 xfails now pass and are kept as regression tests;
  - fixed an AI guardrail gap: Kiswahili "money moved" claims were only caught in the i- noun class (`imetumwa`), so "malipo yameidhinishwa" or "pesa zimetumwa" passed; now every noun class is covered, with a regression test;
  - `kiswahili-review.md`, generated from the code, for a native-speaker reviewer;
  - clean-checkout check of `docs/DEPLOYMENT.md` "Local setup" on a fresh PostgreSQL database: migrate, create-admin, check-config, plain seed (0 financial rows), smoke test 21 PASS / 2 SKIP / 0 FAIL.
- **Demo infrastructure:**
  - `fundbridge-demo seed --scenarios`: labelled demo donations and payouts created through the core services;
  - `scripts/smoke_test.py`;
  - a validated `.env.example`;
  - `docs/RUNBOOK.md`, `docs/DEMO_SCRIPT.md`, `docs/RELEASE_CHECKLIST.md`, `FRONTEND_WALKTHROUGH.md`.
- **Executable proposed contracts** for G-6 and G-7.
- **Independent verification of `b45ee29`:** C-4b and X-1 fixed; R-2, S-5 and X-2 found or kept, with reproductions.
- **Frontend contracts:** reconcile-aware PayPal return with a `failed` outcome, a consumption guide and type-checked examples.

Outstanding: nothing blocking on this branch. Remaining work belongs to Codex, Cursor or the owner (blockers above).

### Test runs
| When | Backend commit | Branch commit | Suite | Result |
|---|---|---|---|---|
| 2026-11-11 evening | `7115094` | merge `078d215` (before the guardrail fix) | `pytest tests`, PostgreSQL 16 (integration and e2e), gunicorn | 285 passed, 5 skipped (4 opt-in real-OpenAI, 1 diagnostic), 2 xfailed (G-6, G-7), 3 failed = the R-2, S-5 and X-2 strict xfails now passing; converted to regression tests, then `tests/e2e` 28/28 and `test_live_found_defects` + `test_migrations` all pass |
| 2026-11-11 evening | `7115094` | this commit | `tests/ai`, `tests/messaging`, AI/messaging integration | 141 passed, 4 skipped (opt-in real OpenAI) |
| 2026-11-11 evening | `7115094` | merge `078d215` | clean clone → `DEPLOYMENT.md` local setup → `scripts/smoke_test.py` | 21 PASS, 2 SKIP (translation without a key; PayPal order is opt-in), 0 FAIL |
| 2026-11-11 | `b45ee29` | `dbaa6e1` plus the docs and contract-gap tests in the next commit | `pytest tests`, PostgreSQL 16.15 (integration and e2e), gunicorn | **275 passed**, 5 skipped (4 opt-in real-OpenAI, 1 diagnostic), 8 xfailed (R-2, S-5, X-2, M-2, M-1b ×2, G-6, G-7) |
| 2026-11-11 | `b45ee29` | same | `contracts`: `npm test` | tsc --strict ✅, 11/11 |
| 2026-11-11 | `b45ee29` | same | e2e `test_demo_smoke`: seed CLI, then `scripts/smoke_test.py` against gunicorn | 23 PASS, 0 SKIP (PayPal and OpenAI were local doubles) |

### External services: simulated versus connected
| Service | State | Evidence available |
|---|---|---|
| PayPal | **Not connected.** Sandbox adapter, tested only against a local Orders v2 double | real sandbox needs credentials (`EXTERNAL_CHECKLIST.md`) |
| OpenAI | **Not connected.** Tested against mocks and a local double | `flask fundbridge-ai check` once a key exists |
| Africa's Talking (SMS/USSD) | **Not connected.** Simulator plus a local API double | account, shortcode and USSD code needed |
| Mobile-money payouts | **Simulated**; stops at `approved_for_submission` | no provider chosen |

## For Codex (canonical backend)

### Status of every tracked item against `7115094`

| ID | Item | Status |
|---|---|---|
| C-4, C-4b | PayPal reference and `Prefer: return=representation` | **Fixed**, verified over HTTP with a PayPal-default double |
| R-1, R-1b, declined capture | Reconciliation | Fixed and verified |
| X-1 | Duplicate onboarding audit | **Fixed** (b45ee29), verified |
| P-1 | Phone reverification | Fixed, verified |
| M-1 | Upgrade with existing data | Fixed, verified on SQLite and PostgreSQL |
| X-2 | Two `?q=` filters ANDed in `list_campaigns()` | **Fixed** (4bae876), regression test `test_keyword_search_matches_category_as_ported` |
| R-2 | Parallel reconciles → HTTP 500 | **Fixed** (4bae876, 7115094), regression test `test_parallel_reconciliations_never_return_500` (PostgreSQL, gunicorn) |
| S-5 | Parallel same-key orders → HTTP 500 instead of replay | **Fixed** (4bae876), regression test `test_parallel_orders_with_one_key_replay_instead_of_500` |
| M-1b | Old global idempotency uniqueness survives upgrade | **Fixed** (e4a6c8d9f012), verified on SQLite and PostgreSQL |
| M-2 | PostgreSQL full rollback leaves enum types | **Fixed** (7115094), verified on PostgreSQL |

No backend defect found by this branch is open against `7115094`. The sections on R-2 and S-5 below are kept for the record.

### R-2 (fixed in 4bae876/7115094): parallel reconciliations returned HTTP 500
- Where: `backend/app/api/v1/routes.py` `reconcile_donation()`. Two requests both read `pending`, both call `mark_donation_completed`, and the second `db.session.commit()` raises `IntegrityError` (`UniqueViolation` on the ledger credit).
- Money is safe: the unique constraints keep it to one credit, and the e2e test checks that. But clients get `500 INTERNAL_ERROR` for a benign race, and the logs fill with errors.
- Reproduce on PostgreSQL: `E2E_DATABASE_URL=... pytest tests/e2e/test_zz_financial_integrity.py::test_parallel_reconciliations_never_return_500 --runxfail` → 7 of 8 responses are 500.
- Suggestion: lock the donation row (`with_for_update()`) and re-check its status before calling the provider, or catch `IntegrityError`, roll back, re-read and return the donation. Capture has the same shape: it only avoids the race today because PayPal answers repeat captures with 422.

### S-5 (fixed in 4bae876): parallel orders with one Idempotency-Key returned HTTP 500
- Where: `routes.py` `donation_order()` at `db.session.add(donation); db.session.flush()`. On PostgreSQL the second insert waits for the first transaction, then raises `UniqueViolation` on `uq_donation_donor_idempotency`.
- Exactly one donation is created, which is correct, but the other callers get 500 instead of the replayed donation the contract promises. A double-clicked "Donate" button or a retried request on a slow network hits this.
- Reproduce: `pytest tests/e2e/test_zz_financial_integrity.py::test_parallel_orders_with_one_key_replay_instead_of_500 --runxfail` (PostgreSQL) → 7 of 8 are 500.
- Suggestion: on `IntegrityError` at that flush, roll back, re-select by `(donor_id, idempotency_key)`, check the fingerprint, and return the existing donation. The PayPal order created by the losing request is never used.

### API gaps found while reviewing the frontend contract (not defects, missing capabilities)
Proposed contracts, executable as strict xfails in `tests/integration/test_proposed_contract_gaps.py` (they XPASS when implemented in this shape; adjust them together with `contracts/` if you choose another shape):
- `GET /api/v1/beneficiaries/me/campaigns` (beneficiary only; 403 for other roles) returns the caller's campaigns in every status, serialized like `GET /campaigns`.
- `GET /api/v1/campaigns?status=submitted` for reviewers and admins is the review queue. Other callers asking for a non-published status get 401/403. The public listing stays published-only.

- **G-6:** a beneficiary cannot list the campaigns they benefit from. `serialize_campaign` has no `beneficiary_id`, and `/me/campaigns` returns campaigns the user *created*. The web payout-request screen therefore cannot find a `campaign_id`. Suggestion: `GET /beneficiaries/me/campaigns`, or `beneficiary_id` in the campaign payload.
- **G-7:** there is no reviewer queue; `GET /campaigns` lists only published campaigns. Suggestion: `GET /campaigns?status=submitted` for reviewers and admins.
- **G-8:** no lookup by `slug`, no pagination beyond 50 results, and no timestamps (`created_at`, `published_at`) in campaign, donation and payout payloads.

### Migration chain
The head is `e4a6c8d9f012` (after the messaging tables, `c3f1a9e7d2b4`). Chain new migrations after it; `test_single_alembic_head` guards this.

## For Cursor (frontend)

`feat/frontend-core` has not been published, so nothing here has been checked against it. Start from `contracts/` (see `contracts/README.md` for how to consume it). Run `npm ci && npm test` there to type-check and run the offline tests.

- `fundbridge-client.ts`: typed client with `completePayPalReturn` (capture, then reconcile the same donation id if ambiguous, then re-read; outcomes `confirmed`, `failed`, `not_approved`, `provider_unavailable`, `needs_review`, `pending`), `presentDonation`/`presentPayout`, `channelModes`, AI, staff and simulator calls. Verified against the live API.
- `examples.ts`: type-checked patterns for async states, the PayPal return page, payout rows, AI suggestions that never block the form, keyword-first search, channel banners, the labelled simulator and stale-review handling.
- **Please run the browser walkthrough** in `docs/integration/FRONTEND_WALKTHROUGH.md` (donor, creator, reviewer and beneficiary on the seeded demo data) and record the results there or in your PR.
- Docs: `docs/integration/operations-and-frontend.md` (screen map, the loading/pending/failure/success table, error codes), `ai-messaging-api.md`, `openai.md`, `africastalking.md`.

Non-negotiable: donation success only from the server (`completed`); payout success only for `succeeded`, and no live payout provider exists, so approved is never shown as paid; label simulated channels; AI failures never block non-AI paths.

## Owner decisions and external prerequisites

Step-by-step checks and the evidence to record for each provider: `EXTERNAL_CHECKLIST.md`.

1. **OpenAI:** an API key; confirm the model (default `gpt-5.4-mini`, unverified; see `openai.md`) and the event's AI rules; then run `flask fundbridge-ai check`.
2. **Africa's Talking:** an account, the sandbox app and API key; then for production, KYC, a two-way shortcode and a USSD service code (telco approval). See `africastalking.md` for the procedure.
3. **PayPal:** sandbox app credentials and webhook ID for the demo; a live business account for production.
4. **Payout provider** (Daraja B2C or an aggregator) and its contract. Until then payouts stop at `approved_for_submission`.
5. Who verifies beneficiaries (currently reviewers and admins only); trust-on-first-use phone PIN versus an agent-issued code; agent-to-beneficiary assignments; and a shared rate-limit store for multi-instance hosting.
