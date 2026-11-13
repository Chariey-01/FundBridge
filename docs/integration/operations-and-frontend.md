# Operations API and frontend integration guide

For whoever builds the web frontend. It covers the endpoints added on `feat/ai-integration-qa` (roles, beneficiary verification, balances, search, hardening) and how each screen should use the API. Core endpoints are in `backend/API_CONTRACT.md`; AI and SMS/USSD endpoints are in `ai-messaging-api.md`.

Use `contracts/fundbridge-client.ts`. It is typed, framework-agnostic and tested against the live API (`backend/tests/e2e/test_frontend_client.py`). `contracts/examples.ts` has type-checked integration patterns for every screen below. `cd contracts && npm ci && npm test` type-checks the client, the contracts and the examples (`tsc --strict`) and runs the offline tests.

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
| Reviewer queue | `reviewCampaign`, `listBeneficiaries("unverified" / "reverification_required")`, `getBeneficiary`, `decideVerification(id, decision, revision)` | `409 PROFILE_CHANGED`: reload the profile and review again |
| Agent: onboard beneficiary | `onboardBeneficiary` | New profiles are `unverified` until a reviewer decides |
| Beneficiary dashboard | `myBeneficiaryProfile`, `campaignFunds` (full), `listPayouts`, `requestPayout`, `presentPayout` | `BENEFICIARY_NOT_VERIFIED`, `INSUFFICIENT_AVAILABLE_FUNDS`, `PAYOUT_DESTINATION_UNVERIFIED`; editing phone or destination returns `reverification_required` |
| Admin: people | `findAccounts`, `assignRole` | `403 SELF_ROLE_CHANGE_FORBIDDEN` |
| Status banner | `publicConfig`, `integrationStatus` → `channelModes` (or `channelBanner` in the examples) | Simulated/sandbox labels; AI "not responding" when `last_error` and not `model_verified` |
| Agent: phone support | `supportRequests`, admin `resetPhonePin` | Phone numbers are personal data: show them to staff only |
| Demo phone simulator | `simulateUssd`, `simulateSms`, `simulatorOutbox` (404 unless enabled) | Always show the server's `meta.notice` and a "SIMULATED" badge |

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
| 200 | Donation `pending` (from reconcile) | PayPal holds the capture or the order has not completed; keep showing pending. It is never credited until a completed capture is authoritatively verified. |
| 405 | `METHOD_NOT_ALLOWED` | Envelope instead of HTML |
| 500 | `INTERNAL_ERROR` | `details.request_id` for support |

Every response carries `X-Request-ID`.
