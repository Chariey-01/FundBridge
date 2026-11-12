# FundBridge verification report: AI, feature phones and end-to-end product QA

**Updated:** 2026-11-12 (final release verification). **Branch:** `feat/ai-integration-qa`; see the final commit in
PR #7. It contains `feat/backend-core` **`782b7b5`** (the migration-logging fix) and everything before it.
**Frontend:** no Cursor branch exists on the remote, so no web UI was verified.

Every claim below points to a test or to an evidence file:
- [`evidence/journeys.md`](evidence/journeys.md): role journeys over HTTP;
- [`evidence/release-probe.md`](evidence/release-probe.md): 55 AI and feature-phone checks against a real server.

"Double" means a local stand-in for a provider's HTTP API (`backend/tests/e2e/provider_doubles.py`). A double proves
FundBridge's side of the integration, never the provider's live behaviour.

## Verdict: PASS WITH LIMITATIONS (hackathon demonstration)

| Question | Answer |
|---|---|
| Safe, integrated and ready for the recorded demonstration? | **Yes, with limitations.** The backend, all five AI features (with provider doubles and with fallbacks), USSD and SMS through the Africa's Talking callback format, and the labelled phone simulator all pass against the latest backend. Limitations: the web UI is unpublished (Cursor), and no live OpenAI, PayPal or Africa's Talking request has been made. A real PayPal sandbox payment and a real OpenAI call each need the owner's credentials (about 30 minutes each). |
| Ready for a real production launch? | **No.** There is no payout provider (payouts stop at "approved"), no live PayPal, no approved Africa's Talking sender ID, shortcode or USSD code, no verified OpenAI model, no published frontend, and no native-speaker review of the Kiswahili. Codex's [`BACKEND_RELEASE_READINESS.md`](BACKEND_RELEASE_READINESS.md) adds: no refund, reversal or dispute handling; no token revocation or refresh; no backups, restore drill or monitoring; and a shared rate-limit store is needed for more than one worker. The compliance questions (KYC/AML for payouts, data protection) are open. |

## Feature matrix

The verification levels:
- **Implemented:** the code exists and its own logic is tested.
- **Double:** also tested over HTTP against the real FundBridge server with a local provider stand-in.
- **Live:** tested against the real provider.
- **Not implemented.**

**No feature has a "Live" result: no credentials were available.**

| Feature | Implemented | Double | Live | Evidence | Who must do what |
|---|---|---|---|---|---|
| Registration, sign-in, roles, lockout | yes | n/a (no provider) | n/a | `test_registration_and_authentication`, `test_auth_parity`, `test_hardening` | none |
| Beneficiary onboarding, verification, reverification on phone/destination change | yes | n/a | n/a | `test_beneficiary_onboarding_and_reverification`, `test_phone_channel_verification` | none |
| Campaign create, submit, review (paginated queue), publish, audit | yes | n/a | n/a | journeys, `test_beneficiary_and_review_queues` | none |
| PayPal donation: order, approve, capture, webhook, reconcile, ledger | yes | **yes** (PayPal Orders v2 double; signed and forged webhooks; replay credited once) | **no** | journeys, `test_journeys` | **Owner:** PayPal sandbox app and webhook ID; one sandbox payment recorded in `EXTERNAL_CHECKLIST.md` |
| Ledger totals, reservations, concurrency | yes | n/a | n/a | PostgreSQL concurrency suites | none |
| Payout request and review, no self-approval | yes (simulator provider) | n/a | n/a | `test_payout_request_review_reservation_and_tracking` | none |
| Payout submission, settlement, "paid" | **not implemented** | | | stops at `approved_for_submission` by design | **Owner:** licensed payout provider and contract. **Codex:** submission and callback endpoints |
| AI campaign draft | yes | **yes** (probe: PII redaction on the wire, injection, hostile output) | **no** | `release-probe.md`, `test_ai_api`, `test_ai_provider_failures` | **Owner:** `OPENAI_API_KEY`, then `flask fundbridge-ai check` |
| AI translation | yes | **yes** | **no** | same; 503 without a model, original kept | same |
| AI beneficiary assistant (web and SMS free text) | yes | **yes** (invented payout confirmation replaced) | **no** | same | same |
| AI campaign search | yes | **yes** (results only from the database) | **no** | same | same |
| AI status explanation | yes | **yes** (invented confirmations replaced; access matches the core routes) | **no** | `test_status_explanation`, probe | same |
| AI fallbacks, attribution, rate limit, daily cap | yes | **yes** (provider double failing; cap reached at exactly 40 calls) | n/a | probe, `test_fallback_honesty_and_limits` | none |
| USSD menus, PIN, lockout, admin reset (English and Kiswahili) | yes | **yes** (Africa's Talking callback format over HTTP) | **no** (no telco session) | probe, e2e, `test_feature_phone_hardening` | **Owner:** Africa's Talking account; sandbox USSD channel, then a production service code (telco approval) |
| SMS commands, notifications after commit, delivery reports | yes | **yes** (Africa's Talking double; simulated outbox) | **no** | `test_africastalking_journeys`, probe | **Owner:** API key; for production, KYC and a sender ID or shortcode (approval) |
| Messaging unavailable | yes | **yes** (unreachable Africa's Talking: USSD, payout review and inbound SMS keep working) | n/a | probe, `test_africastalking_outage_never_breaks_callbacks_or_payouts` | none |
| Callback secret (24+ characters), IP allowlist, retry safety | yes (**weak-secret defect fixed today**) | **yes** | n/a | probe, `test_callbacks_refuse_a_guessable_token` | **Owner:** Africa's Talking callback IP list for `MESSAGING_ALLOWED_IPS` |
| Kiswahili wording | yes | n/a | n/a | `integration/kiswahili-review.md` (regenerated and matches the code) | **Owner:** native-speaker review, especially money and PIN text |
| Web frontend journeys and screenshots | **not in the repository** | | | no branch | **Cursor:** publish the frontend; run `integration/FRONTEND_WALKTHROUGH.md` |

No feature failed verification. Five defects were found and fixed across these audits (below).

## Phase 1: AI audit

| Question | Draft | Translate | Assistant | Search | Status explanation |
|---|---|---|---|---|---|
| Real provider integration exists | yes (`OpenAIProvider`, Chat Completions, strict JSON schema) | yes | yes | yes | yes |
| Configured key and supported model | `OPENAI_API_KEY`, `OPENAI_MODEL` (default `gpt-5.4-mini`, **unverified**) | same | same | same | same |
| A real request reached the provider | **No.** No key was available. | No | No | No | No |
| Output validated and safely rendered | schema, sanitize, links removed, claim warnings | schema, placeholders restored | schema, unsafe replies replaced | schema; results from the database only | schema, amount, link, contact, claim and contradiction checks; status from the record |
| Graceful timeout, rate limit, bad credentials | template | 503 `AI_UNAVAILABLE` | rule-based | keyword | verified text |
| Fallback says AI is unavailable | **fixed in this audit**: the disclaimer used to say "AI-assisted" | 503 message | **fixed**: notice | **fixed**: notice | notice |
| User's data preserved on failure | the endpoint never saves; form unchanged | original text kept | n/a | n/a | n/a |
| Usage limits and abuse controls | 10/min per user, 20/min per IP, 16 KB body, **daily cap (new)** | same | same | same | same |

Other AI interaction exposed: free-text SMS goes to the assistant with the same guardrails, and falls back to the
command list. The AI never initiates anything on the phone channels.

## Phase 2: AI in the payment journey

- **Creators:** the draft helps explain the goal and its use, flags amounts that differ from the goal, and warns
  against claims that money moved or that FundBridge verified anything.
- **International donors:** translation of campaign text, and natural-language discovery.
- **Donors and beneficiaries (new):** `POST /api/v1/ai/status-explanation` explains one PayPal donation or one payout
  from the backend record, in the person's language. The AI receives a read-only copy of the facts through a port.
  It cannot import payment, payout, ledger or model code (`test_ai_code_cannot_reach_financial_modules`). A database
  snapshot before and after shows nothing changes (`test_status_explanation`).
- **Prohibitions verified:** the AI creates no PayPal order, captures nothing, writes no ledger entry, approves no
  campaign, beneficiary or payout, and makes no fraud or identity decision. Generated text claiming an unconfirmed
  outcome is replaced (`claims_unconfirmed_outcome`), as is text saying a confirmed donation paid the beneficiary
  (`claims_beneficiary_paid`).
- **PII:** the status-explanation request to the model contains no donor e-mail, user, donation, payout or PayPal
  IDs, phone number or wallet token. This is checked on the wire in `test_model_receives_facts_but_no_personal_or_payment_identifiers`.

## Phase 3: feature phone

| Check | Result | Evidence |
|---|---|---|
| English and Kiswahili menus and commands | pass | `test_english_and_kiswahili_have_the_same_messages`, e2e |
| PIN setup, weak-PIN refusal, hashing, lockout, expiry, admin reset | pass | `test_pin_setup_validation_lockout_expiry_and_reset`, `test_parallel_wrong_pins_cannot_exceed_attempt_limit` (PostgreSQL) |
| Phone verification; reverification after a change | pass | `test_new_unverified_number_gets_nothing_beneficiary_specific`, `test_reverified_number_regains_access` |
| Session continuation and timeout | pass (stateless; an abandoned PIN setup saves nothing) | `test_abandoned_or_timed_out_session_leaves_no_partial_state` |
| Campaign and payout status; clear labels (only `succeeded` says paid) | pass | `test_succeeded_label_only_for_succeeded_state`, e2e |
| SMS notifications after commit only; delivery reports | pass | `test_sms_sent_only_after_committed_completion`, `test_delivery_reports_are_authenticated_validated_and_idempotent` |
| Callback authentication; duplicate and retry handling | pass | `test_callbacks_fail_closed_without_configured_token`, `test_retried_wrong_pin_step_counts_once` |
| Provider unavailable | pass (callbacks and payouts unaffected) | `test_sms_provider_outage_never_breaks_callbacks_or_payouts`, `test_africastalking_outage_never_breaks_callbacks_or_payouts` |
| Real telco USSD session or real SMS | **not run** | needs an Africa's Talking account |

Owner-controlled dependencies, with the exact steps in `integration/africastalking.md`: an Africa's Talking account
(KYC for live), an API key, a sender ID or two-way shortcode, a USSD service code (telco approval), callback URLs
registered on the production host, the callback IP allowlist, and `MESSAGING_CALLBACK_TOKEN`.

## Phase 4: journeys

Run over HTTP against gunicorn with PostgreSQL. Transcript: [`evidence/journeys.md`](evidence/journeys.md).
Screenshots: none. There is no frontend to capture, and the evidence is the HTTP transcript.

| Journey | Result | Notes |
|---|---|---|
| Creator: register, role, AI draft, edit, create, submit, review, publish | pass | the draft came from the OpenAI double |
| Donor: AI discovery, story, PayPal order, approve, capture, signed webhook (twice), ledger, total, history | pass against the PayPal double | a webhook naming a different capture is refused (`PAYMENT_CAPTURE_MISMATCH`) |
| Beneficiary: verified profile, own campaigns, USSD (Africa's Talking format), PIN, payout, SMS, status explanation | pass (simulated SMS outbox) | no live telco |
| Reviewer: paginated queue, inspect, reject, resubmit, approve, audit trail | pass | audit: created, submitted, review_reject, submitted, review_approve |
| Administrator: user management, and denial for other roles | pass | |

| Failure journey | Result | Evidence |
|---|---|---|
| Expired or invalid token | 401 `TOKEN_EXPIRED` / `INVALID_TOKEN` on core, AI and messaging routes | `test_auth_parity` |
| Network interruption (lost capture response) | reconcile completes the donation once | `test_reconcile_after_provider_side_capture_completes_donation_once` |
| Payment provider unreachable | envelope; nothing written | `test_unreachable_payment_provider_returns_envelope_and_writes_nothing` |
| Duplicate submissions | one donation per key; parallel orders replay instead of 500 | `test_parallel_orders_with_one_key_replay_instead_of_500` (PostgreSQL) |
| Provider timeout (AI) | fallback, `degraded: true` | `test_every_failure_degrades_gracefully` |
| AI unavailable | essential paths keep working | `test_ai_features_and_graceful_degradation` |
| Messaging unavailable | callbacks and payouts unaffected | see Phase 3 |
| Rejected payment | donation `failed`, nothing credited | `test_reconcile_with_declined_capture_marks_donation_failed` |
| Duplicate webhook | 204, credited once | `test_paypal_webhook_requires_verified_signature_and_is_idempotent`, journey |
| Unknown payout result | **cannot occur yet**: there is no submission step. The label ("Awaiting confirmation. Do not request again") and its explanation are tested. | not implemented |
| Unauthorised access | 403 or 401 everywhere tested | journey, `test_financial_security` |

## Phase 5: defects

Found in these audits (all in Claude-owned AI and messaging code, all fixed, each with a regression test):

| ID | Severity | Defect | Reproduction | Expected | Actual (before the fix) | Fixed in |
|---|---|---|---|---|---|---|
| AI-1 | **High** | A decimal amount hid "money moved" claims from the guardrail | `find_unsafe_claims("Your payout of 40.00 USD has been sent to your M-Pesa.")` | `["financial_completion"]` | `[]`: the `.` in `40.00` ended the sentence, so the beneficiary assistant would pass the reply | `07bb6a0`; `test_decimal_amounts_do_not_hide_completion_claims` |
| AI-2 | **High** | Kiswahili claims were detected in only one noun class | `find_unsafe_claims("Malipo yako yameidhinishwa.")` | flagged | `[]` (also "pesa zimetumwa", "malipo yamelipwa") | `a1cf9c9`; `test_kiswahili_completion_claims_in_every_noun_class` |
| AI-3 | Low | The template draft was labelled "AI-assisted" when AI was unavailable | `POST /ai/campaign-draft` with no key | says AI is unavailable | "AI-assisted draft…" | `07bb6a0`; `test_template_draft_does_not_call_itself_ai` |
| AI-4 | Medium | No overall cap on provider calls; public endpoints could run up cost | many IPs at 20 requests/min each | a bounded daily spend | unbounded | `07bb6a0`; `AI_DAILY_REQUEST_LIMIT` |
| MSG-1 | Medium | The running app accepted a guessable callback secret. `check-config` flagged tokens under 24 characters, but callbacks still worked with them, so anyone could forge USSD/SMS callbacks for any number (read campaign status, opt a number out with STOP, flood support requests; payout status stays behind the PIN) | `MESSAGING_CALLBACK_TOKEN=letmein`, then `POST /api/v1/messaging/ussd?token=letmein` | refused (503 `MESSAGING_NOT_CONFIGURED`), error logged without the token, `callback_configured: false` | 200 `CON FundBridge…` | 2026-11-12; `test_callbacks_refuse_a_guessable_token` |

Open items (no critical defect is open in code that can be tested here):

| ID | Severity | Item | Owner |
|---|---|---|---|
| L-1 | Medium (operational) | Rate limits, the daily AI cap and the simulated outbox are per process: deploy with one worker, or add a shared store | Claude/owner (hosting) |
| L-2 | Low | Status-explanation claim checks understand English and Kiswahili only. Other languages rely on the amount, link and contact checks, the status fields taken from the record, and the verified English text returned alongside | Claude, after native-speaker input |
| L-3 | Low | AI input redaction does not detect personal names or street addresses (the forms ask only for a first name and a general location) | documented |
| L-4 | Low | The review queue is ordered by creation time, but its `submitted_at` is the last update. A campaign resubmitted after rejection keeps its original place | Codex (by design?) |
| L-5 | Low (by design) | Provider callbacks are not rate-limited. They are authenticated by a 24+ character random secret (now enforced) and the optional IP allowlist; PIN guessing is bounded by the per-number lockout; free-text SMS sent to the AI is limited per number; the simulator is limited per IP. Throttling authenticated gateway traffic could drop real messages | documented |

Security checks run: prompt injection and hostile outputs (`test_adversarial_prompts_and_hostile_outputs_change_nothing`);
PII to the provider (wire checks in the draft and status-explanation tests); cross-user access to beneficiary,
campaign, donation and payout data (journey and integration tests); PIN brute force (lockout, including concurrent
attempts on PostgreSQL); callback replay and authentication; duplicate payments and payouts (PostgreSQL concurrency);
misleading status (labels, `confirmed`, guardrails); secrets and phone numbers in logs
(`test_server_logs_hold_no_secrets_or_phone_numbers`, `test_access_log_omits_query_strings`).

Accessibility:
- **Feature phone:** numbered menus, `0` back and `00` home, at most 182 characters of GSM 7-bit text, two
  languages, nothing to install.
- **Phone simulator page:** `lang`, labelled inputs, `aria-live` regions and a visible "Simulated" banner.
- **Web app:** not available to check.

## Tests run

| Suite | Commit | Result |
|---|---|---|
__FINAL__
| `pytest tests` on the merge of `782b7b5` (before the MSG-1 fix) | `70241e8` | 314 passed, 5 skipped, 0 failed |
| Release probe against a real server (`backend/scripts/release_probe.py`): gunicorn with `FLASK_ENV=production`, PostgreSQL, the OpenAI double, a simulated outbox, then an unreachable Africa's Talking URL | MSG-1 fix applied | **55 passed, 0 failed** ([`evidence/release-probe.md`](evidence/release-probe.md)) |
| `pytest tests`: unit, integration, migrations, PostgreSQL 16 concurrency, e2e on gunicorn with PostgreSQL (includes the TypeScript client against the live API and the contracts type-check) | `06fc6ab` | **313 passed, 5 skipped, 0 failed, 0 xfailed.** Skipped: 4 opt-in real-OpenAI tests and 1 SQLite diagnostic |
| `contracts`: `npm test` (tsc --strict and offline tests) | `06fc6ab` | type-check passes, 11/11 |
| Clean clone, then the `DEPLOYMENT.md` local setup, then `scripts/smoke_test.py` | `078d215` (earlier today) | 21 PASS, 2 SKIP (translation without a key; PayPal order is opt-in), 0 FAIL |

**Live provider tests run: none.** All AI tests used a mocked HTTP transport or the OpenAI double. All PayPal and
Africa's Talking tests used local doubles. SMS went to the simulated outbox. The opt-in real-OpenAI tests
(`tests/ai/test_openai_live.py`) were skipped because there is no key.

## Owner actions, in priority order

1. **PayPal sandbox:** create the app and webhook, set `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` and
   `PAYPAL_WEBHOOK_ID`, then make one sandbox payment and record it (`integration/EXTERNAL_CHECKLIST.md`).
2. **OpenAI:** set `OPENAI_API_KEY`, set a project budget, run `flask fundbridge-ai check` and
   `FUNDBRIDGE_LIVE_OPENAI_TESTS=1 pytest tests/ai/test_openai_live.py`, then record the result in `integration/openai.md`.
3. **Cursor:** publish the frontend branch so its journeys can be verified, and run `FRONTEND_WALKTHROUGH.md`.
4. **Merge PR #7 first, then PR #8.** PR #8 (`feat/backend-core` → `main`) conflicts in one test file,
   `backend/tests/integration/test_live_found_defects.py`, and PR #7 already contains the resolution. With PR #7 merged
   (a fast-forward of `feat/backend-core`), PR #8 merges into `main` without conflicts; this was checked read-only with
   `git merge-tree`.
5. **Africa's Talking:** create an account and use the sandbox (`AT_USERNAME=sandbox`); for production, complete
   KYC, get a sender ID or shortcode and a USSD service code, register the callback URLs, and set
   `MESSAGING_ALLOWED_IPS`.
6. **Kiswahili:** native-speaker review of `integration/kiswahili-review.md`.
7. **Payout provider:** choose a licensed provider and contract. Production cannot launch without it.
8. **Compliance:** KYC/AML obligations for collecting and paying out donations, and data-protection obligations
   (for example Kenya's Data Protection Act) for beneficiary data.
