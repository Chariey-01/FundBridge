# Release and demo-readiness checklist

Status key: ✅ verified (evidence linked); ⚠️ works with a known limitation; ❌ open defect or not done; ⏸ blocked on credentials or another agent.
State as of 2026-11-11, backend `feat/backend-core` `b45ee29`. Evidence: `docs/integration/VERIFICATION_CHECKLIST.md`.

## Backend and financial integrity
| Item | Status | Evidence / owner |
|---|---|---|
| Backend regression suite | ✅ | `pytest tests` on PostgreSQL 16.15 (see COORDINATION "Test runs") |
| Ledger: one credit per completed donation, reservations and releases consistent | ✅ | `test_ledger_is_consistent_after_every_journey`, run after all e2e journeys |
| Concurrent payouts and PINs cannot overspend or exceed attempts | ✅ | PostgreSQL concurrency tests |
| Parallel captures, reconciles and same-key orders never double-credit | ✅ | `test_zz_financial_integrity.py` |
| Parallel reconcile / same-key orders return 500 (money safe) | ❌ R-2, S-5 | Codex |
| Campaign search duplicate filter | ❌ X-2 | Codex |
| `main` contains `b45ee29` (PayPal `Prefer` header) | ❌ | maintainer: merge `feat/backend-core` → `main` |

## Database
| Item | Status | Evidence / owner |
|---|---|---|
| Fresh `flask db upgrade` matches the models; single head | ✅ | `test_migrations.py` (SQLite and PostgreSQL) |
| Upgrade keeps existing financial rows | ✅ | `test_upgrade_preserves_existing_financial_data` |
| Databases from before `c3e4e3a` | ❌ M-1b | Codex. Recreate old demo databases instead. |
| Full downgrade and re-upgrade on PostgreSQL | ❌ M-2 | Codex. Rollback is not a release procedure; restore from backup. |

## Frontend
| Item | Status | Evidence / owner |
|---|---|---|
| Branch published and reviewable | ⏸ | Cursor (`feat/frontend-core` is not on GitHub) |
| Build and type-check with `contracts/` | ⏸ | Cursor; `contracts/` itself: `npm test` ✅ |
| Browser walkthrough D1–X4 | ⏸ | Cursor (`docs/integration/FRONTEND_WALKTHROUGH.md`) |
| Beneficiary campaign list (G-6), reviewer queue (G-7) | ❌ | Codex (proposed contracts in `tests/integration/test_proposed_contract_gaps.py`). Demo workaround: campaign IDs printed by the seed. |

## AI and messaging
| Item | Status | Evidence |
|---|---|---|
| Four AI features, fallbacks, redaction, hostile output, rate limits, no DB writes | ✅ (mocked transport and HTTP double) | `tests/ai`, `test_ai_provider_failures.py`, e2e |
| Real OpenAI | ⏸ key | `flask fundbridge-ai check`, `test_openai_live.py` |
| USSD/SMS in English and Kiswahili, PIN, verification gate, retries, delivery reports, 182-character screens | ✅ (simulator and Africa's Talking double) | `tests/messaging`, `test_feature_phone_hardening.py`, e2e |
| Real Africa's Talking (shortcode, USSD code) | ⏸ account and telco approval | `docs/integration/africastalking.md` |

## Demo
| Item | Status | Evidence |
|---|---|---|
| Reproducible seed with every role, campaigns, donations and payouts (labelled) | ✅ | `fundbridge-demo seed --scenarios`; `test_demo_seed.py` |
| Smoke test of the principal journeys | ✅ | `scripts/smoke_test.py`; `test_demo_smoke.py` (23 PASS on gunicorn) |
| `.env.example` complete, no secrets | ✅ | `test_env_example.py` |
| Live donation in the demo | ⏸ PayPal sandbox credentials | without them, the seeded donations are used and disclosed |
| Mobile-money payout | ⚠️ simulated; stops at "approved" | disclosed in the demo script |
| Judge script | ✅ | `docs/DEMO_SCRIPT.md` |
| Runbook | ✅ | `docs/RUNBOOK.md` |

## Disclosures to make during the demo
- PayPal: sandbox, if configured; otherwise the seeded `demo_seed` records. Never real money.
- AI: OpenAI if a key is set and `model_verified` is true; otherwise template or keyword fallback.
- USSD/SMS: simulator; Africa's Talking is not connected.
- Payouts: no licensed provider; nothing is ever shown as paid.
