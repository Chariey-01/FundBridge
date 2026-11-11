# Operations API and frontend integration guide

For whoever builds the web frontend. It covers the endpoints added on `feat/ai-integration-qa` (roles, beneficiary verification, balances, search, hardening) and how each screen should use the API. Core endpoints are in `backend/API_CONTRACT.md`; AI and SMS/USSD endpoints are in `ai-messaging-api.md`.

Use `contracts/fundbridge-client.ts` (consumption steps: `contracts/README.md`). It is typed, framework-agnostic and tested against the live API (`backend/tests/e2e/test_frontend_client.py`). `contracts/examples.ts` has type-checked integration patterns for every screen below. `cd contracts && npm ci && npm test` type-checks the client, the contracts and the examples (`tsc --strict`) and runs the offline tests.

## Rules every screen must follow

1. **Money is a decimal string.** Display it as given and never do arithmetic in JS numbers. Balances come from `GET /campaigns/{id}/funds`, never from summing donations client-side.
2. **Donation success only from the server.** On the PayPal return page, call `client.completePayPalReturn(donationId)` (or `donationReturnPage` in the examples). Show "Donation confirmed" only for outcome `confirmed`, which requires `GET /donations/{id}` to say `completed`. Ignore PayPal's query parameters. When a capture is ambiguous (timeout, or PayPal says the order was already captured), the client calls `POST /donations/{id}/reconcile`, which re-reads PayPal without capturing again.
3. **Payout success only for `succeeded`.** No payout provider is live, so payouts end at `approved_for_submission`, shown as "Approved, being prepared" in a pending style. Never say money was sent.
4. **Label simulated channels** with `channelModes()`: simulated SMS, USSD not verified on a live network, AI fallback, simulated payouts.
5. **AI is optional.** Wrap every AI call; on any `ApiError`, keep the plain form. Search falls back to `GET /campaigns?q=`, which has no AI dependency or AI rate limit.
6. **Sessions:** tokens last 15 minutes and there is no refresh endpoint. On `TOKEN_EXPIRED` / `INVALID_TOKEN` / `ACCOUNT_INACTIVE` (`ApiError.sessionInvalid`), clear the token and send the person to sign in.
7. **Idempotency:** create one key per user intent with `FundBridgeClient.newIdempotencyKey()` and reuse it when retrying that same intent. A changed amount needs a new key (otherwise `400 IDEMPOTENCY_KEY_REUSED`).

## Loading, pending, failure and success

| Situation | Show | Never show |
|---|---|---|
| Request in flight | A loading state, with the action disabled (prevents double submits; idempotency keys also protect retries) | Any outcome |
| Donation `created`/`pending` | "Waiting for payment confirmation", plus "Check again" | "Thank you, your donation went through" |
| Donation return outcome `not_approved` | "Payment not completed at PayPal", plus "Return to PayPal" | Failure of the donation itself (it is still pending) |
| Outcome `provider_unavailable` | "PayPal is not responding; we will keep checking", plus re-check | "Payment failed" or "Payment succeeded" |
| Outcome `needs_review` | "We could not confirm this payment; support will check", with the request ID | Success |
| Outcome `failed` (server status `failed`/`cancelled`, e.g. PayPal declined the capture) | "Payment not completed", plus "Donate again" (a new donation with a new idempotency key) | Success, or "still checking" |
| Donation `completed` | "Donation confirmed" (success) | |
| Payout `requested`/`under_review`/`approved_for_submission`/`submitted`/`pending_confirmation` | The label from `presentPayout`, in a pending style | "Paid", "Sent" or "Received" |
| Payout `rejected`/`failed` | The failure label; the reserved funds are back in `available` | |
| Payout `succeeded` | "Paid to your mobile money account". Not reachable today: no live payout provider exists | |
| AI call fails or is rate limited | Hide the suggestion; the manual form and keyword search keep working | An error that blocks the form |
| `401`/`ACCOUNT_INACTIVE` | Sign in again (`ApiError.sessionInvalid`) | Raw error text |
| `429` | "Try again in N seconds" (`retryAfterSeconds`) | |
| `5xx` | A generic message with `requestId` for support | Stack traces or provider messages |

## Screen → endpoint map

| Screen | Calls | States to show |
|---|---|---|
| Sign up / sign in | `register`, `login`, `me` | `401 INVALID_CREDENTIALS`; `429 RATE_LIMITED` with `retry_after_seconds` |
| Browse / search | `listCampaigns({q, category})`, optional `aiSearch` | AI search may return `meta.degraded`; fall back to `listCampaigns` on error |
| Campaign page | `getCampaign`, `campaignFunds` (public: `raised` only) | `as_of` timestamp |
| Donate | `createDonationOrder` → redirect to `approval_url` → return page → `completePayPalReturn` (capture, then reconcile if ambiguous, then re-read) | `confirmed` (success), `not_approved` (donor did not finish at PayPal), `provider_unavailable` (re-check later), `needs_review` (contact support, quote `error.requestId`), `pending` |
| My donations | `myDonations` + `presentDonation` | Only `completed` is success |
| Creator: new campaign | optional `draftCampaign` (suggestion only, shows `warnings`), then `createCampaign`, `updateCampaign`, `submitCampaign` | `draft` → `submitted` → `published`, or back to `draft` with `review_status: rejected` |
| Reviewer queue | `reviewCampaign` (by id only; **no endpoint lists submitted campaigns**, gap G-7), `listBeneficiaries("unverified" / "reverification_required")`, `getBeneficiary`, `decideVerification(id, decision, revision)` | `409 PROFILE_CHANGED`: reload the profile and review again |
| Agent: onboard beneficiary | `onboardBeneficiary` | New profiles are `unverified` until a reviewer decides |
| Beneficiary dashboard | `myBeneficiaryProfile`, `campaignFunds` (full), `listPayouts`, `requestPayout`, `presentPayout`. **No endpoint lists the beneficiary's campaigns** (gap G-6), so the payout form cannot discover a `campaign_id` until the backend adds one | `BENEFICIARY_NOT_VERIFIED`, `INSUFFICIENT_AVAILABLE_FUNDS`, `PAYOUT_DESTINATION_UNVERIFIED`; editing phone or destination returns `reverification_required` |
| Admin: people | `findAccounts`, `assignRole` | `403 SELF_ROLE_CHANGE_FORBIDDEN` |
| Status banner | `publicConfig`, `integrationStatus` → `channelModes` (or `channelBanner` in the examples) | Simulated/sandbox labels; AI "not responding" when `last_error` and not `model_verified` |
| Agent: phone support | `supportRequests`, admin `resetPhonePin` | Phone numbers are personal data: show them to staff only |
| Demo phone simulator | `simulateUssd`, `simulateSms`, `simulatorOutbox` (404 unless enabled) | Always show the server's `meta.notice` and a "SIMULATED" badge |

## API contract review: what the frontend must not assume (backend `b45ee29`)

`feat/frontend-core` has not been published, so this is a review from the API side. Check it against the frontend once the branch is visible.

**Safe to use now:**
- **AI** (see `ai-messaging-api.md`):
  - `GET /ai/status` (public);
  - `POST /ai/campaign-search` (public, 20/min per IP; returns real catalog campaigns only);
  - `POST /ai/translate` (public; `503 AI_UNAVAILABLE` without a provider);
  - `POST /ai/campaign-draft` and `POST /ai/beneficiary-assistant` (signed in, 10/min per user).

  Every AI response has `meta.ai_generated`/`degraded`; show a suggestion only, and never block the form.
- **Feature phones (web side):**
  - `GET /integrations/status` for banners;
  - `GET /messaging/support-requests` (agent, admin);
  - `POST /messaging/beneficiaries/{id}/pin-reset` (admin).

  The simulator endpoints are 404 unless enabled, and are always labelled simulated.

**Explain in the UI:**
- USSD/SMS answer only numbers on a verified beneficiary profile. After a phone or payout-destination change, the beneficiary must be re-verified.
- The USSD PIN is created on the handset; staff cannot see it, only reset it.
- SMS delivery is never shown as confirmed.

**Not supported. Do not build against these:**
- refresh tokens, logout or revocation (tokens last 15 minutes);
- password reset or email verification;
- guest (anonymous) donations;
- campaign images or media;
- editing goal or currency after creation (`PATCH` changes only title, description and category, and only in draft);
- closing a campaign;
- slug lookup (G-8);
- pagination beyond 50;
- payout submission or settlement (payouts stop at `approved_for_submission`);
- a beneficiary's own campaign list (G-6);
- a reviewer queue of submitted campaigns (G-7).

**Payload notes:**
- Campaign create takes flat `goal_amount`/`goal_currency`, but responses nest `goal: {amount, currency}`.
- Campaign, donation and payout payloads have no timestamps.
- Donation history has `campaign_id` only (fetch titles separately).
- `GET /public/config` always reports `feature_phone: {sms: false, ussd: false}`; use `/integrations/status`.
- AI drafts return `title`, `summary`, `story` and `suggested_category`; the campaign has no summary field, so put the story in `description`.

## Endpoints added on this branch

| Method and path | Who | Notes |
|---|---|---|
| `GET /api/v1/campaigns?q=` | public | Case-insensitive keyword match on title or description, max 100 characters, wildcards escaped. Combines with `category`. |
| `GET /api/v1/campaigns/{id}/funds` | public for published campaigns (`raised` only); creator, the beneficiary, reviewer, admin see `reserved_for_payouts`, `paid_out`, `available` | From the ledger, using the same `available_funds()` that guards payout reservation. `raised = available + reserved_for_payouts + paid_out` while there are no refunds. Unpublished: `401`/`403` for others. |
| `GET /api/v1/admin/users?email=` or `?phone_number=` | admin | Up to 20 accounts |
| `PUT /api/v1/admin/users/{id}/role` | admin | `{ "role": "creator" }`. Cannot change your own role. Audited (`user.role_changed`). |
| `GET /api/v1/beneficiaries?verification_status=` | agent, reviewer, admin | Never returns the payout destination, only `has_payout_destination` |
| `GET /api/v1/beneficiaries/{id}` | agent, reviewer, admin | Includes `revision` |
| `POST /api/v1/beneficiaries/{id}/verification` | reviewer, admin | `{ "decision": "verify" \| "reject", "revision": "<from GET>", "reason"?: "..." }`. `409 PROFILE_CHANGED` if anything the reviewer vouched for changed since. `403 SELF_VERIFICATION_FORBIDDEN`. Audited. |
| `flask fundbridge-admin create-admin --email` | operator CLI | First admin; see `docs/DEPLOYMENT.md` |

## Error codes added or unified

| Status | Code | Meaning |
|---|---|---|
| 401 | `AUTH_REQUIRED`, `INVALID_TOKEN`, `TOKEN_EXPIRED` | Same on core, AI and messaging routes |
| 403 | `ACCOUNT_INACTIVE` | Valid token, account no longer active |
| 409 | `PROFILE_CHANGED` | Stale verification decision |
| 429 | `RATE_LIMITED` | `Retry-After` header and `details.retry_after_seconds` |
| 502 | `PROVIDER_REQUEST_REJECTED` | PayPal refused (`details.provider_status`, `details.provider_issue`, e.g. `ORDER_NOT_APPROVED`) |
| 503 | `PROVIDER_UNAVAILABLE` | PayPal unreachable or timed out; the donation may or may not have been captured, so reconcile and re-read it |
| 400 | `PAYMENT_ORDER_MISMATCH` (from create order) | The provider's order does not match the donation (amount, currency or reference). Nothing is stored; show a retry |
| 500 | `INTERNAL_ERROR` on a retried order or reconcile | Open items S-5/R-2: a concurrent retry can return 500 although the donation exists. Re-read with `myDonations`/`getDonation` before showing an error |
| 405 | `METHOD_NOT_ALLOWED` | Envelope instead of HTML |
| 500 | `INTERNAL_ERROR` | `details.request_id` for support |

Every response carries `X-Request-ID`.
