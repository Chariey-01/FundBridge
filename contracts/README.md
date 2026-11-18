# FundBridge frontend contracts

Typed, framework-agnostic client for the FundBridge API, plus integration examples. It is maintained on `feat/ai-integration-qa`, reaches the canonical backend through `feat/backend-core`, and is checked against the running API in `backend/tests/e2e/test_frontend_client.py`.

| File | What it is |
|---|---|
| `fundbridge-client.ts` | `FundBridgeClient` (fetch-based), `ApiError`, the presentation rules (`presentDonation`, `presentPayout`, `channelModes`) |
| `ai-messaging.types.ts` | Request and response types for AI, SMS/USSD status, the simulator and staff endpoints, plus payout labels |
| `examples.ts` | Type-checked patterns for every money and AI screen (async states, the PayPal return page, payouts, AI fallback, banners, simulator, reviewer conflicts) |
| `*.test.ts` | Offline rule tests (`npm test`) and the live test run by the backend e2e suite |

## Using it from the frontend (once `feat/frontend-core` is published)

The frontend branch was not available to this branch when this was written. The steps below are written for it, not tested against it.

1. **Bring the files in.** In a monorepo checkout after both branches merge, import from `../contracts/fundbridge-client.ts`. Until then, copy `fundbridge-client.ts` and `ai-messaging.types.ts` into the app (for example `src/lib/fundbridge/`), keep them byte-identical, and note the source commit.
2. **TypeScript settings.** The files use explicit `.ts` import specifiers and `import type`. With a bundler (Vite or Next.js), set `"moduleResolution": "bundler"`, `"allowImportingTsExtensions": true` and `"noEmit": true` (the bundler emits), and keep `"strict": true`. The exhaustive status maps then fail to compile if the backend adds a status the UI does not handle.
3. **One client per session:**
   ```ts
   const client = new FundBridgeClient({
     baseUrl: import.meta.env.VITE_API_BASE_URL,      // e.g. https://api.example; must be allowed by FRONTEND_ORIGIN
     onSessionInvalid: () => router.push("/sign-in"),  // TOKEN_EXPIRED / INVALID_TOKEN / ACCOUNT_INACTIVE
   });
   ```
   Access tokens last 15 minutes and there is no refresh endpoint. Keep the token in memory or `sessionStorage`, not `localStorage`, and send people to sign in on `onSessionInvalid`.
4. **Use the examples as the screen logic.** Wire `donationReturnPage`, `payoutRow`, `suggestDraft`, `searchCampaigns`, `channelBanner`, `simulatorStep` and `verifyBeneficiary` into components; the view models are plain objects. Keep the rules in `docs/integration/operations-and-frontend.md`.
5. **Run `npm ci && npm test` in this folder** in the frontend's CI as well, so a contract change shows up as a type error.

## Rules the client enforces

- **Donations.** `completePayPalReturn(donationId)` captures, reconciles if the capture was ambiguous (`POST /donations/{id}/reconcile` for the same donation ID), then re-reads `GET /donations/{id}`. `confirmed` only when the server says `completed`; `failed` only when the server recorded the payment as not completed. Everything else stays pending, never success.
- **Payouts.** `presentPayout` shows only `succeeded` as success; `approved_for_submission` is pending.
- **Simulated channels.** Simulator calls return the server's `simulated: true` metadata. Show it, and label any channel that `channelModes` reports as not live.
- **Money.** Amounts are decimal strings; never do JavaScript number arithmetic on them.
