# FundBridge release audit, 2026-11-12

**Verdict: release gate FAILED. Do not deploy.** The backend works end to end for every role on PostgreSQL, and
the AI integration works against the real OpenAI model. But there is no web frontend anywhere, and the backend
has a payout data-integrity defect and an authentication defect, both reproduced on a live server.

Audited commit: `feat/ai-integration-qa` at `102b2d5`, plus the audit tests added with this report. This branch
contains every commit of `feat/backend-core` (`601b152`), which contains every commit of `main` (`6f3c335`).

## 1. Repository and pull-request state (verified with `git` and `gh`, not taken from earlier reports)

| Item | State |
|---|---|
| PR #7 `feat/ai-integration-qa` → `feat/backend-core` | **Open, not merged.** Merges cleanly (`git merge-tree`), 18 commits ahead, 0 behind |
| PR #8 `feat/backend-core` → `main` | **Open, not merged.** Fast-forward, 11 commits ahead of `main` |
| `main` (`6f3c335`) | Lacks the 11 backend fixes of PR #8 (C-4b, R-2, S-5, X-2, M-1b, M-2, G-6, G-7) and all of PR #7 |
| Integration head | `feat/ai-integration-qa`: backend + AI + feature phone + tests + docs + typed client |
| Frontend | **Absent.** No frontend branch on the remote, no `package.json`/Vite project in any commit on any ref, none on disk, no dev server running. Only the typed API client in `contracts/` exists |
| Untracked work | `.github/workflows/backend.yml` exists only as an untracked file in Codex's checkout: CI is not active on GitHub |
| Stale | `codex/backend-foundation` (PR #1, closed): local `f7a25f0` differs from remote `a206826`. Several leftover worktrees under `/tmp` |
| Conflicts | None between the three live branches |

## 2. Test results

Missing credentials are reported as BLOCKED, never as passed. "Stand-in" means the repository's local PayPal
Orders v2 double (`tests/e2e/provider_doubles.py`): it exercises the real adapter over HTTP but is not PayPal.

| Suite | Environment | Result |
|---|---|---|
| Backend, all (unit, integration, migrations, concurrency, e2e on gunicorn) | PostgreSQL 16 | **315 passed, 5 skipped, 0 failed** (skips: 4 opt-in live OpenAI, 1 diagnostic) |
| Backend, same suite plus the 7 audit tests | PostgreSQL 16 | **315 passed, 5 skipped, 7 xfailed, 0 failed** (the 7 are the defects in §2.1) |
| Backend, all | SQLite (README's default command) | **302 passed, 2 failed, 16 skipped.** Failures: `test_parallel_reconciliations_never_return_500`, `test_parallel_orders_with_one_key_replay_instead_of_500` (9 and 12 HTTP 500s). Their guarantees use PostgreSQL locks only; SQLite is unsupported for concurrent payments, but the README presents the SQLite run as complete |
| Live OpenAI (`tests/ai/test_openai_live.py`, opt-in) | real API, `gpt-5.4-mini` | **4 passed** |
| `flask fundbridge-ai check` | real API | **OK**: model `gpt-5.4-mini-2026-03-17` answered search and an en→sw translation with valid structured output |
| Release probe (`scripts/release_probe.py`, 55 AI/feature-phone checks) | real server, PostgreSQL, OpenAI stand-in | **55 passed, 0 failed** |
| Typed client `contracts/`: `tsc --strict` + offline tests | Node 24 | **type-check clean, 11/11** |
| Typed client live tests | against the audit's own gunicorn + PostgreSQL + PayPal stand-in | **4/4** |
| Independent live API journeys (written for this audit) | gunicorn, `FLASK_ENV=production`, PostgreSQL, PayPal stand-in | **113 steps: 101 pass, 11 product failures, 1 audit-script error** (see §4) |
| Feature-phone journeys over the Africa's Talking callback format | same server, simulated SMS outbox | **29 steps: 28 pass, 1 audit-script error** (re-checked: correct) |
| AI over HTTP | fallback mode, then the real model | all access, labelling, limit and privacy checks pass (§3 G) |
| Browser (Playwright + Chrome), phone simulator page | 1366×900 and 390×844 | **17/18**: the one failure is a missing favicon (404) |
| Payout review race (written for this audit) | gunicorn + PostgreSQL, 15 races | **Defect: 14/15 races both decisions returned 200; 5/15 left an approved payout with its reservation released** |
| Ledger reconciliation (SQL) | PostgreSQL, after all journeys | completed donations = ledger credits (5 = 5, 85.75 = 85.75); no orphan credits |
| Frontend unit tests, TypeScript, lint, production build, browser journeys | — | **BLOCKED: no frontend exists** |
| Real PayPal sandbox checkout | — | **BLOCKED: no sandbox credentials** |
| Real Africa's Talking SMS/USSD | — | **BLOCKED: no account, no service code** |
| Payout provider | — | **NOT IMPLEMENTED: simulator only** |

### 2.1 Audit tests added (strict xfail until fixed)
`backend/tests/integration/test_release_audit_defects.py` holds 7 tests that state the correct behaviour. Each was
run with `--runxfail` and fails on its stated assertion. The race test was also run against a scratch copy of the
backend with a candidate one-line row-lock fix applied, and it passed there, so the test can be satisfied. Nothing
in production code was changed.

## 3. Feature matrix

There is no frontend, so the frontend column is "none" for every feature and is omitted. "Live" means verified over
HTTP against gunicorn and PostgreSQL in this audit.

### A. Authentication and accounts
| Feature | Backend | Tests | Live result | Status | Missing work / owner |
|---|---|---|---|---|---|
| Registration | `POST /auth/register` (donor role only, 12+ char password) | yes | works; role escalation via body ignored | **Defect** | accepts `"not-an-email"` (AUD-6); non-string email → 500 (AUD-4) — Codex |
| Login | `POST /auth/login`, 15-min JWT | yes | works | **Defect (security)** | **AUD-2**: a password with no email/phone signs in as whichever account with a NULL email or phone the unordered query returns first (the admin in the audit run); emails are case-sensitive (AUD-5) — Codex |
| Logout | none | — | `POST /auth/logout` → 404 | **Missing** | stateless JWT: client discards token; no server revocation — Codex (decide) |
| Session renewal | none | — | `POST /auth/refresh` → 404 | **Missing** | users are signed out every 15 min — Codex |
| Password security | werkzeug hashing; lockout 5 failures/15 min; 30 logins/min/IP | yes | lockout works for identified attempts | Partial | no password reset or change; limits are per process — Codex |
| Role-based access | `roles_allowed`; admin role assignment with audit | yes | every role check tested passed | **Verified** | — |
| Unauthorized handling | JSON 401/403 envelopes | yes | missing, forged and wrong-role tokens refused | **Verified** | — |
| User profile | `GET /auth/me` only | — | `PATCH /auth/me` → 405 | **Missing** | — Codex |

### B. Campaign management
| Feature | Backend | Tests | Live result | Status | Missing work / owner |
|---|---|---|---|---|---|
| Create / save draft | `POST /campaigns` (creator, admin) | yes | works; validation; duplicate slug 409 | **Verified** | — |
| Edit draft | `PATCH /campaigns/<id>` (title, description, category) | yes | works | **Defect** | **AUD-3**: no validation on edit (5-char description accepted); 300-char title → **HTTP 500 on PostgreSQL**; `goal_amount` silently ignored with 200 — Codex |
| Submit | `POST /campaigns/<id>/submit` | yes | works; locked after submit | **Verified** | — |
| Review queue | `GET /campaigns/review-queue` (paginated) | yes | works; creators refused | **Verified** | — |
| Approve / publish | `POST /campaigns/<id>/review` | yes | works; self-review blocked | **Verified, with a gap** | campaigns for an **unverified beneficiary** can be published and take donations (AUD-8) — owner decision, then Codex |
| Reject | same | yes | back to draft, `review_status=rejected` | Partial | the rejection reason is not stored or shown to the creator (AUD-9) — Codex |
| Detail and progress | `GET /campaigns/<id>`, `/funds` | yes | ledger-backed raised total; drafts hidden | **Verified** | — |
| Ownership | creator-only edit; staff read | yes | non-owner edit/read refused | **Verified** | — |

### C. Donations and PayPal
| Feature | Backend | Tests | Live result | Status | Missing work / owner |
|---|---|---|---|---|---|
| Donation journey | signed-in donors only | yes | works end to end with the stand-in | Verified (stand-in) | guest donation not available (by design) |
| Order creation | Orders v2, `reference_id` = donation id, response validated | yes | works; `approval_url` is PayPal sandbox checkout | Verified (stand-in) | **real sandbox BLOCKED: credentials** |
| Approval | PayPal hosted page | — | stand-in approval only | **Blocked** | sandbox buyer account |
| Server-side capture | `POST /donations/<id>/capture` | yes | refuses before approval (502, nothing credited); completes after; idempotent | Verified (stand-in) | — |
| Webhook signature | PayPal verify-webhook-signature API | yes | forged → 403; verified → completes; replay deduplicated; amount mismatch refused | Verified (stand-in) | real webhook ID |
| Idempotency | per-donor key + fingerprint; PostgreSQL advisory lock | yes | replay returns same donation; reused key with new amount refused | **Verified** | — |
| Ledger | immutable entries; unique per donation and capture | yes | SQL reconciliation exact | **Verified** | — |
| Failures | provider errors → 502/503 envelopes, rollback | yes | verified | **Verified** | — |
| Reconciliation | `POST /donations/<id>/reconcile` re-reads the order | yes | lost capture response reconciled once | Verified (stand-in) | — |
| Confirmation / receipt | donation status only | — | no capture id, completion time or receipt | **Missing** | receipt data and e-mail (AUD-10) — Codex |

### D. Beneficiaries
| Feature | Backend | Tests | Live result | Status | Missing work / owner |
|---|---|---|---|---|---|
| Profile (agent-assisted onboarding, self-view, edit) | yes | yes | works; destination never returned | **Verified** | — |
| Verification | reviewer decision bound to a profile revision | yes | stale revision 409; self-verification refused | **Verified** | — |
| Reverification | phone or destination change | yes | forces `reverification_required`, blocks payouts | **Verified** | — |
| Campaigns and ledger view | `/beneficiaries/me/campaigns`, `/funds` full view | yes | raised, reserved, available shown | **Verified** (see AUD-1 for `available`) | — |
| Payout request | `POST /payouts` | yes | works | **Verified** | — |

### E. Administration and review
| Feature | Backend | Tests | Live result | Status | Missing work / owner |
|---|---|---|---|---|---|
| Reviewer dashboard | API only (queues, lists) | yes | works | Backend only | **UI missing** — Cursor |
| Approve/reject workflows | campaigns, beneficiaries, payouts | yes | work sequentially | **Defect under concurrency** | AUD-1 — Codex |
| Audit history | `audit_log` written for every change | yes | every action recorded | Partial | **no API to read the audit log** — Codex |
| Admin restrictions | admin-only role changes; no self role change | yes | verified | **Verified** | — |

### F. Payouts
| Feature | Backend | Tests | Live result | Status | Missing work / owner |
|---|---|---|---|---|---|
| Request + reservation | row-locked campaign; ledger reservation | yes | over-reservation refused; concurrent requests safe | **Verified** | — |
| Review | `POST /payouts/<id>/review`; no self-approval | yes | works sequentially | **Defect (critical)** | **AUD-1**: concurrent approve and reject both succeed; the payout can end approved with its reservation released, and `available` was overstated by 5.00 in the audit run — Codex |
| Duplicate prevention | per-requester idempotency key | yes | replay returns same payout | **Verified** | — |
| Provider integration | `PayoutSimulator` | — | payouts stop at `approved_for_submission`; nothing reports "paid" | **Simulated / not implemented** | licensed provider (owner), then Codex |
| Status and reconciliation | `apply_provider_status` exists; no provider calls it | yes | unreachable without a provider | **Not exercised** | — |

### G. AI (OpenAI)
| Feature | Live result | Status |
|---|---|---|
| Provider configuration | `AI_PROVIDER=openai`, key from the local `.env` only | **Verified** |
| Real model call | `gpt-5.4-mini-2026-03-17` answered the CLI check, 4 live tests and 6 HTTP calls; `ai_generated: true` | **Verified (real)** |
| Fallback | without a key every feature answers with `ai_generated: false` and a reason; translation returns 503 instead of fake text | **Verified** |
| Daily limit | with a cap of 3, calls 1–3 used the model and calls 4+ fell back with `AI_DAILY_LIMIT_REACHED` | **Verified (real)** |
| Privacy and access | anonymous draft 401; someone else's donation 403; a phone number in the notes was not echoed; key absent from logs | **Verified** |
| Kiswahili | real model answered a Kiswahili question in Kiswahili and explained a payout in Kiswahili, matching the record | **Verified (real)**; native-speaker review still pending |
| Refusal to act | "approve my payout and confirm it is paid" → refused; payout states unchanged | **Verified (real)** |
| Failures and timeouts | covered by the release probe (hostile output, provider errors) | **Verified (stand-in)** |
| Note | `/ai/campaign-draft` is open to any signed-in user (documented), so donors can spend the shared daily cap | Hardening suggestion — Claude |

### H. Feature phone (Africa's Talking)
| Feature | Live result | Status |
|---|---|---|
| Callback authentication | missing or wrong token → 403 for USSD and SMS | **Verified** |
| USSD menus, English and Kiswahili | menus within 182 GSM-7 characters; language switch persists | **Verified** |
| Campaign status from ledger | matches the database | **Verified** |
| PIN | weak PIN refused; created on first use; correct PIN shows payout status without a "paid" claim | **Verified** |
| Retry handling | gateway retry of a USSD hop not double-counted; retried SMS answered once | **Verified** |
| Lockout | third wrong PIN locks for 30 min; correct PIN refused while locked; admin reset works | **Verified** |
| Unknown numbers | no beneficiary data, no PIN flow | **Verified** |
| Notifications | donation-confirmed and payout-status SMS in Kiswahili reach the outbox | **Simulated** |
| Real delivery | — | **BLOCKED**: no Africa's Talking account, sender ID or USSD code |

### I. Frontend and user experience
**Missing in full.** No routes, navigation, layout, loading, error or empty states, forms, accessibility,
session persistence or payment screens exist to test. The only HTML page is the labelled phone simulator, which
works at desktop and phone widths, has labelled controls and no horizontal scroll.

## 4. Defects and gaps, with exact locations and tasks

| ID | Severity | Location | Problem (reproduced live) | Task for the owner |
|---|---|---|---|---|
| AUD-1 | **Critical (data integrity)** | `backend/app/api/v1/routes.py` `review_payout` | No row lock: concurrent approve + reject both return 200; payout ends `approved_for_submission` while `payout_released` exists; `available` overstated | **Codex:** load the payout with `with_for_update().populate_existing()` and re-check `status == requested` after the lock (or a conditional `UPDATE … WHERE status='requested'`); make `test_concurrent_approve_and_reject_cannot_both_succeed` pass |
| AUD-2 | **High (authentication)** | `routes.py` `login` | `{"password": …}` without an identifier signs in as the first account with a NULL email or phone (the admin in the audit); per-account lockout does not apply to these attempts | **Codex:** require a non-empty string identifier, query only the column that was supplied. **Claude** follow-up: count identifier-less attempts in `hardening.py` |
| AUD-3 | High (500 + validation bypass) | `routes.py` `update_campaign` | 300-char title → 500 on PostgreSQL; 5-char description accepted; `goal_amount` silently ignored with 200 | **Codex:** apply the create validators on edit; reject or support unknown fields explicitly |
| AUD-4 | Medium (500) | `routes.py` `register` | non-string `email` → 500 | **Codex:** type-check every field |
| AUD-5 | Medium | `routes.py` `register`/`login` | emails stored case-sensitively; `Mixed@x` cannot sign in as `mixed@x`; case variants create separate accounts | **Codex:** lower-case on write and lookup; migration for existing rows |
| AUD-6 | Low | `routes.py` `register` | any string accepted as an email | **Codex:** basic format check |
| AUD-7 | Medium (deployment) | `backend/app/config.py` | without `DATABASE_URL`, production starts on `sqlite:///fundbridge.db` (lost on every redeploy on free hosts); `postgres://` URLs are not rewritten for psycopg 3 | **Codex:** refuse to start in production without a PostgreSQL URL; normalise the scheme |
| AUD-8 | Medium (trust) | `routes.py` `review_campaign` | campaign for an unverified beneficiary can be published and accept donations | **Owner decision**, then Codex: require `verified` before approval |
| AUD-9 | Medium (UX) | `routes.py` `review_campaign` | rejection reason not stored or returned | **Codex:** store and return the reason |
| AUD-10 | Medium (product) | `serialize_donation` | no receipt data (capture id, completion time), no receipt message | **Codex** |
| AUD-11 | Low (labelling) | `routes.py` `public_config` | PayPal "sandbox" is inferred from the client id alone (would say sandbox with live credentials); `feature_phone` hard-coded `false` while the simulator runs | **Codex:** derive from `PAYPAL_BASE_URL` and messaging status |
| AUD-12 | Medium (gaps) | auth | no logout/revocation, refresh, profile update, password reset, audit-log API | **Codex** (scope with the owner) |
| T-1 | Low (tests/docs) | `README.md`, `tests/e2e/test_zz_financial_integrity.py` | the documented SQLite run fails 2 PostgreSQL-only concurrency tests | **Claude:** owner to choose: gate those 2 tests on PostgreSQL, or change the README to require PostgreSQL. Not changed here, so as not to hide a failure |
| F-1 | **Blocker** | — | no web frontend | **Cursor:** publish the frontend branch; build against `contracts/fundbridge-client.ts` |
| CI-1 | Low | `.github/workflows/backend.yml` | untracked in Codex's checkout, so no CI runs | **Codex:** commit it |

## 5. Release acceptance gate

| Category | Items |
|---|---|
| Implemented and verified | auth and roles (apart from AUD-2), campaign lifecycle, beneficiary onboarding and verification, donation idempotency, ledger, capture/webhook/reconcile logic (stand-in), payout request and reservation, AI (real model), feature-phone flows (simulated delivery), migrations |
| Implemented, not verified against the real provider | PayPal sandbox order, approval, capture and webhook; Africa's Talking SMS and USSD |
| Partially implemented | campaign edit, rejection feedback, audit history (no read API), password security (no reset) |
| Missing | **web frontend**, receipts, logout, refresh, profile update, password reset, payout provider |
| Simulated | payouts (stop at `approved_for_submission`), SMS outbox, phone simulator |
| Blocked tests | all frontend suites, PayPal sandbox checkout, real SMS/USSD delivery |
| Security / data-integrity blockers | **AUD-1**, **AUD-2** |
| Configuration still required | PayPal sandbox client id, secret and webhook id; `FRONTEND_ORIGIN`; `DATABASE_URL` (PostgreSQL); secrets; `MESSAGING_CALLBACK_TOKEN`; `TRUSTED_PROXY_HOPS`; Africa's Talking account; payout provider |

**Gate result: FAIL.** Blocking: F-1 (no frontend), AUD-1 (critical data integrity), AUD-2 (authentication).
PR #7 and PR #8 should also be merged so that `main` contains the audited code.

## 6. Hosting recommendation (no deployment made)

Free tiers checked on 2026-11-12. Sources disagree on some limits; re-check at sign-up.

| Part | Recommendation | Cost | Caveats |
|---|---|---|---|
| Frontend (React + Vite, once it exists) | Cloudflare Pages or Netlify (Vercel Hobby also works if Deployment Protection is off for production) | $0 | Use the production domain, never a preview URL; set `VITE_` API base URL before the build |
| Backend (Flask, gunicorn `-w 1 --threads 8`) | Render free web service | $0 (750 instance-hours/month) | Sleeps after 15 min idle, about 1 min to wake: USSD sessions time out during a cold start, and in-process rate limits and the simulated outbox reset. Real USSD needs an always-on paid instance, which needs your approval first |
| PostgreSQL | Neon free plan (1 GB per project, scale to zero, no expiry) | $0 | Prefer it over Render's free PostgreSQL, which is deleted after a fixed period (30 or 90 days, sources differ); use `postgresql+psycopg://` with `sslmode=require` |

Deployment steps are ready in `docs/DEPLOYMENT.md` and `docs/RELEASE_CHECKLIST.md`.

## 7. Evidence

Raw outputs, the audit scripts and screenshots were kept outside the repository (they contain test tokens). The
results that matter are summarised above. The audit tests in §2.1 reproduce AUD-1 to AUD-6 in CI.
