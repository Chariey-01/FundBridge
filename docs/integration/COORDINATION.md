# Coordination notes: Claude (AI, messaging, QA) → Codex (backend) and Cursor (frontend)

Branch `feat/ai-integration-qa` (PR #3) is stacked on `feat/backend-core` (PR #2) and merges it regularly.
Last merged backend commit: `856b8b3`.

## For Codex (backend)

### Open defects found by QA

Each has a strict-xfail reproduction in `backend/tests/integration/test_financial_security.py`. When a fix lands the test XPASSes, strict mode turns that into a failure, and the marker should be removed.

| ID | Severity | Defect | Suggested fix |
|---|---|---|---|
| S-1 | High | `Idempotency-Key` lookup is global, so a different user replaying a key receives another user's payout (and donation) record. | Scope lookup and uniqueness to `(actor_id, key)`. |
| S-3 | High | An admin can request a payout and then approve it. The contract forbids approving your own submission. | Store `requested_by` on `Payout`; reject review when the reviewer is the requester. |
| P-1 | High | `PATCH /beneficiaries/me` changes `phone_number` with no re-verification. That number controls USSD/SMS access and notifications. | Set `verification_status = "reverification_required"` (as for payout destination) or route phone changes through agent verification. |
| S-2 | Medium | Reusing a key with a different body silently returns the original payout. | Store a request hash with the key; return 409 `IDEMPOTENCY_KEY_REUSED` on mismatch. |
| A-1 | Medium | A missing, invalid or expired JWT returns flask_jwt_extended's `{"msg": ...}`, not the contract envelope. | Register `unauthorized_loader`, `invalid_token_loader` and `expired_token_loader` returning the envelope with 401. |
| A-2 | Low | A wrong password returns 403 `INVALID_CREDENTIALS`. | Return 401. |
| A-3 | Low | `get_or_404` returns Flask's HTML 404, not the envelope. | Add a 404 error handler that returns the envelope. |
| T-1 | Medium (test) | `tests/test_postgres_concurrency.py` cannot pass on PostgreSQL: it inserts a campaign with `creator_id="creator"` and no `user` row, which raises `ForeignKeyViolation`. SQLite hides this because foreign keys are off. | Create real `User` and `BeneficiaryProfile` rows. Enable `PRAGMA foreign_keys=ON` for SQLite tests. |

Fixed upstream and now asserted as passing behaviour: C-1 (capture amount/currency check), F-1 (unverified beneficiary payouts).

Verified property: on PostgreSQL 16, 8 concurrent `POST /payouts` of 60.00 against 100.00 of funds produced exactly one reservation, with 40.00 remaining, on 4 of 4 runs (`tests/integration/test_payout_concurrency.py`).

### Integration points that touch backend files

- `backend/app/__init__.py`: one added line, `init_integrations(app)`. It registers `/api/v1/ai/*`, `/api/v1/messaging/*`, `/api/v1/integrations/status` and the `fundbridge-demo` CLI.
- Migration `c3f1a9e7d2b4` (messaging tables) revises `18323330d500`. Chain new migrations after it once PR #3 merges.
- `backend/.env.example`: AI and messaging variables appended.
- `GET /public/config` still reports `feature_phone: {sms: false, ussd: false}`. Please source it from `app.api.v1.messaging.integration_status()`, or have the frontend read `/api/v1/integrations/status`.
- Notifications come from SQLAlchemy `after_flush`/`after_commit` hooks (`app/integrations/notifications.py`). No changes are needed in the payment or payout services.
- Read-only adapters over core models are in `app/integrations/core_adapters.py`. "Raised" = `donation_completed` ledger entries minus `donation_refunded`/`donation_reversed`/`chargeback` once those types exist. Please tell me if you name refund entries differently.
- Shared campaign category enum proposed by the AI layer: `medical, education, emergency, community, agriculture, small_business, housing, water_sanitation, other`. Core `Campaign.category` is free text today; search still works, but category filters only match these values.

## For Cursor (frontend)

- API reference and UI rules: `docs/integration/ai-messaging-api.md`.
- Key rule: show donation success only from `GET /donations/{id}` → `completed`, and payout success only from `GET /payouts/{id}` → `succeeded`. Never treat a PayPal redirect, an AI reply or an SMS as confirmation.
- Show `/api/v1/integrations/status` states (simulated / sandbox / live) wherever SMS, USSD or AI is presented.
- AI drafts are suggestions: load them into the editable form, show `warnings`, save through the campaign endpoints.

## Owner decisions still open

1. Whether the phone PIN for payout status stays trust-on-first-use (current) or is set from an agent-issued one-time code.
2. Which OpenAI model to use (`OPENAI_MODEL`, default `gpt-4o-mini`; confirm availability and hackathon AI rules).
3. Africa's Talking account, shortcode and USSD service code. None are configured or verified.
4. Agent-to-beneficiary assignments. Until they exist, any agent can see all phone support requests, and PIN reset is admin-only.
