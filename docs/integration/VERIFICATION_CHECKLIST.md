# Independent verification checklist

Maintained on `feat/ai-integration-qa` by the integration/QA owner. It records evidence, not intentions. Backend fixes belong to Codex on `feat/backend-core`; this file only says whether the behaviour was observed.

Last run: 2026-11-11, against `feat/backend-core` **b45ee29**, PostgreSQL 16.15 (local instance), gunicorn 23 (1 worker x 8 threads), `FLASK_ENV=production`, schema built by `flask db upgrade`.

**Status key**

- **Verified passing:** observed passing in that run.
- **Reproduced failing:** a strict-xfail test reproduces the defect today.
- **Not tested.**
- **Blocked:** needs infrastructure or credentials that are not available.

"Double" means a local HTTP stand-in for a provider; it is never a real provider.

## Backend fixes reported by Codex

| Item | Status | Evidence |
|---|---|---|
| PayPal `Prefer: return=representation` on create-order (C-4b) | Verified passing | e2e `test_order_creation_against_paypal_default_response`, with a PayPal double that returns PayPal's default minimal body unless the header is sent. All PayPal journeys run that way. |
| Donation `reference_id` is the persisted donation id (C-4) | Verified passing | `test_paypal_order_carries_the_donation_id_as_reference`; the double rejects a null reference |
| Order id, amount and currency validated against the provider order | Verified passing (create-order, capture) | the tampered capture amount gives `PAYMENT_AMOUNT_MISMATCH` with no credit (e2e) |
| Reconcile: completed → credited once, pending → stays pending, declined → failed | Verified passing | e2e reconcile tests (R-1, R-1b, declined) |
| No second capture call during reconcile | Verified passing | the double counts capture calls (e2e) |
| No duplicate ledger credit under parallel captures (8) | Verified passing | `test_parallel_captures_credit_once` |
| No duplicate ledger credit under parallel reconciles (8) | Verified passing | `test_parallel_reconciliations_credit_once` |
| Parallel reconciles return errors | **Reproduced failing (R-2)** | 7/8 → HTTP 500 `IntegrityError/UniqueViolation` at `routes.py` `reconcile_donation` commit. Strict xfail `test_parallel_reconciliations_never_return_500`. |
| One donation per `Idempotency-Key` under parallel requests (8) | Verified passing | `test_parallel_orders_with_one_idempotency_key_create_one_donation` |
| Parallel same-key orders replay the original donation | **Reproduced failing (S-5)** | 7/8 → HTTP 500 `UniqueViolation` on `uq_donation_donor_idempotency` at `routes.py` `donation_order` flush. Strict xfail `test_parallel_orders_with_one_key_replay_instead_of_500`. |
| One onboarding audit record (X-1) | Verified passing | `test_assisted_onboarding_is_audited`; Codex's `test_beneficiary_onboarding_writes_one_audit_record` |
| Phone change forces reverification (P-1) | Verified passing | `test_phone_change_requires_reverification`, phone-channel tests (the new number gets nothing until re-verified) |
| Campaign keyword search: one coherent filter (X-2) | **Reproduced failing** | two `?q=` filters ANDed; the category match never returns. Strict xfail `test_keyword_search_matches_category_as_ported`. |

## Database, PostgreSQL and migrations

| Item | Status | Evidence |
|---|---|---|
| Fresh install: `flask db upgrade` matches the models | Verified passing (SQLite, PostgreSQL) | `test_upgrade_head_matches_models`; clean venv from `requirements-deploy.txt` |
| Single Alembic head | Verified passing | `test_single_alembic_head` (head `c3f1a9e7d2b4`) |
| Upgrade with existing financial data (M-1) | Verified passing (SQLite, PostgreSQL) | `test_upgrade_preserves_existing_financial_data`: every donation, ledger and payout row identical |
| Database built from the original initial migration (M-1b) | **Reproduced failing** | strict xfail `test_upgrade_from_original_initial_schema_drops_global_key_uniqueness` |
| Full downgrade, then re-upgrade | Verified passing (SQLite); **reproduced failing (PostgreSQL, M-2)** | `test_full_downgrade_then_upgrade` |
| Request-level transaction rollback on PostgreSQL | Verified passing | e2e failure paths (insufficient funds, tampered capture, key reuse, provider errors) leave no partial rows; checked by the ledger audit |
| Ledger consistency after every journey, including rollbacks | Verified passing | `test_ledger_is_consistent_after_every_journey`: each completed donation credited once, each payout reserved once and released only when rejected or failed, no negative balance, `/funds` equals the ledger |
| Concurrent payout reservations (8) | Verified passing | `test_concurrent_payouts_cannot_overspend_postgres`, Codex's `test_two_simultaneous_reservations_cannot_overcommit` |
| Concurrent wrong USSD PINs (8) | Verified passing | `test_parallel_wrong_pins_cannot_exceed_attempt_limit`; fails without the row lock |
| Concurrent donation **and** payout on the same campaign | Not tested | |
| Production-size data, connection pooling, failover | Not tested | |

## Providers

| Item | Status |
|---|---|
| PayPal Sandbox (real) | **Blocked**: no sandbox credentials. Doubles only. |
| OpenAI (real) | **Blocked**: no API key. `fundbridge-ai check` and `tests/ai/test_openai_live.py` are ready and skipped. |
| Africa's Talking (real) | **Blocked**: no account, shortcode or USSD code. Doubles and the simulator only. |
| Mobile-money payout provider | **Blocked**: none chosen; no submission or callback endpoint exists |

## How to rerun

```bash
cd backend
POSTGRES_TEST_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5432/fb_test \
E2E_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5432/fb_e2e \
python -m pytest tests -q -rxs     # both databases are disposable: the suites drop and recreate the schema
```
