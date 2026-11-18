# Frontend browser walkthrough: test cases for `feat/frontend-core`

**Request to Cursor:** run these cases in a browser against a backend at `feat/backend-core` `b45ee29` or later, seeded with `fundbridge-demo seed --scenarios` (see `docs/RUNBOOK.md`). Record the results in the table at the end, in the frontend PR or this file. A case passes only if the UI shows the state in "Must show" and **never** shows anything in "Must never show".

The cases use the seeded accounts (same `DEMO_PASSWORD`) and seeded numbers. API references are to `contracts/fundbridge-client.ts`; screen rules are in `operations-and-frontend.md`.

## Donor (`demo-donor@example.test`)

| # | Steps | Expected API calls | Must show | Must never show |
|---|---|---|---|---|
| D1 | Browse; search "school" | `listCampaigns({q})` | 2 published demo campaigns; search finds the school-fees campaign | drafts or submitted campaigns |
| D2 | Natural-language search "help a girl finish school in Kenya" | `aiSearch` → on error, `listCampaigns` | results; "AI" or "keyword" label from `meta` | an error that blocks search |
| D3 | Open "School fees for Amina (demo)" | `getCampaign`, `campaignFunds` | Raised USD 150.00 of USD 400.00 | a client-side sum |
| D4 | Donation history | `myDonations` | 5 completed and 1 pending (pending styled as pending) | "confirmed" on the pending one |
| D5 | Donate USD 10 without PayPal configured | `createDonationOrder` → 400 `PAYMENT_PROVIDER_UNCONFIGURED` | "Payments are not available right now" | a thank-you or "donation received" |
| D6 | Donate USD 10 with PayPal sandbox; approve; return | `createDonationOrder` → redirect → `completePayPalReturn` | "Donation confirmed" only for outcome `confirmed`; Raised +10 after reload | success before the server re-read |
| D7 | Return from PayPal **without** approving | `completePayPalReturn` → `not_approved` | "Payment not completed at PayPal", plus "Return to PayPal" | failure of the donation; success |
| D8 | Double-click Donate | one idempotency key per intent | one pending donation | two donations. (A 500 is possible today because of S-5; re-read `myDonations` before showing an error.) |
| D9 | Leave the tab for over 15 minutes, then act | `onSessionInvalid` (`TOKEN_EXPIRED`) | the sign-in page | raw error text |

## Creator (`demo-creator@example.test`)

| # | Steps | Expected API calls | Must show | Must never show |
|---|---|---|---|---|
| C1 | "Draft with AI" from notes that include `0712345678` | `draftCampaign` | an editable draft, the warnings (contact details removed), the review disclaimer; AI or template label | the phone number in the draft; an automatic save |
| C2 | AI unavailable or rate limited | `draftCampaign` fails → `null` | the manual form still works | a blocked form |
| C3 | Save, then submit | `createCampaign` (flat `goal_amount`/`goal_currency`, a slug the UI generates), `submitCampaign` | status `submitted` | "published" |
| C4 | My campaigns | `myCampaigns` | the draft "Books for the village library", the published campaigns and the submitted one | |

## Reviewer (`demo-reviewer@example.test`)

| # | Steps | Expected API calls | Must show | Must never show |
|---|---|---|---|---|
| R1 | Review queue | `reviewQueue()` lists `demo-water-tank` (submitted); page through with `page`/`page_size` | the submitted campaign; approve and reject | |
| R2 | Approve `demo-water-tank` | `reviewCampaign(id, "approve")` | status `published`; it appears in public browse | |
| R3 | Beneficiary verification | `listBeneficiaries`, `getBeneficiary`, `decideVerification(id, decision, revision)` | profiles with `has_payout_destination`; on `409 PROFILE_CHANGED`, "Profile changed, review again" | the payout destination value |
| R4 | Approve Baraka's USD 30 payout | `listPayouts`, `reviewPayout(id, "approve")` | "Approved, being prepared" (pending style) | "Paid", "Sent" or "Completed" |
| R5 | Reject a payout | `reviewPayout(id, "reject")` | "Not approved"; the campaign's `available` goes up | |

## Beneficiary (`demo-beneficiary@example.test`, Amina)

| # | Steps | Expected API calls | Must show | Must never show |
|---|---|---|---|---|
| B1 | Dashboard | `myBeneficiaryProfile`, `listPayouts` | verified; payouts "Approved, being prepared" (USD 40) and "Not approved" (USD 15) | "paid" |
| B2 | Request a payout | pick the campaign from `beneficiaryCampaigns()`, then `requestPayout` | `requested`; `available` falls by the amount | success wording |
| B3 | Request more than available (USD 1000) | `requestPayout` → `INSUFFICIENT_AVAILABLE_FUNDS` | a clear error | |
| B4 | Change phone number | `updateMyBeneficiaryProfile({phone_number})` → `reverification_required` | "Re-verification required; payouts and the phone service are paused until an agent checks your details" | |
| B5 | Feature-phone help | `channelModes` | "Simulated SMS, nothing is sent to phones" and "USSD … not yet verified on a live network" | a claim that SMS was delivered |

## Cross-cutting

| # | Check | Must show |
|---|---|---|
| X1 | Every page that mentions SMS, USSD, AI or payouts | `channelBanner` labels for each channel that is not live |
| X2 | Any 5xx | a generic message with `requestId` |
| X3 | Money | strings exactly as the API returns them (`"150.00"`), never floats |
| X4 | `npm run build` and the type-check pass with `contracts/` included | |

## Results (to be filled in by Cursor)

| Case | Result | Frontend commit | Notes |
|---|---|---|---|
| D1–D9, C1–C4, R1–R5, B1–B5, X1–X4 | *not yet run* | | |
