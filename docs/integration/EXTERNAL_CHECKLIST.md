# External integration checklist

For the project owner and whoever holds the provider accounts. **None of these integrations has been verified against a real provider from this repository.** The checks below say what to configure, how to verify it, and what evidence to record before calling an integration live. Never commit credentials; set them in the host's secret store.

Status key: **Not started**, **Configured** (credentials set, no successful real call), **Verified** (the steps below passed and the evidence is recorded).

| Provider | Status | Blocking issue in code |
|---|---|---|
| OpenAI | Not started (no key) | None |
| Africa's Talking | Not started (no account) | None |
| PayPal | Not started (no sandbox credentials) | **C-4b**: order creation fails against PayPal's default response (see below) |
| Payout provider | Not started (no provider chosen) | No submission or callback endpoint exists yet |

## OpenAI

Full details: [`openai.md`](openai.md).

1. **Key:** create an API key in the OpenAI dashboard for the project's organisation, and set `OPENAI_API_KEY` (server only; it is never sent to the browser).
2. **Model:** confirm the model is listed for the account and is not on OpenAI's deprecations page. Set `OPENAI_MODEL` (default `gpt-5.4-mini`, which is unverified). For a `gpt-4*` model also set `OPENAI_REASONING_EFFORT=omit`.
3. **Check:** run `flask --app run:app fundbridge-ai check`. Expect `search OK` and `translate OK` with a Kiswahili translation, then exit 0. `FAIL` lines name the error code; the log has the reason.
4. **Full features:** `FUNDBRIDGE_LIVE_OPENAI_TESTS=1 python -m pytest tests/ai/test_openai_live.py -v` → 4 passed (draft, translation, assistant, search).
5. **Deployed:** after one real request, `GET /api/v1/ai/status` shows `model_verified: true`.
6. **Evidence:** the date, the model, the `check` output (it never prints the key) and the live test result.

## Africa's Talking (SMS and USSD)

Full details and the step-by-step procedure: [`africastalking.md`](africastalking.md).

1. **Credentials:** `AT_USERNAME` (`sandbox` first), `AT_API_KEY`, `SMS_PROVIDER=africastalking`.
2. **Sender:** for two-way SMS, `AT_SENDER_ID` is the shortcode. An alphanumeric sender ID is one-way and must be registered.
3. **Callbacks:** run `flask fundbridge-messaging check-config --api-host https://<backend>` and paste the USSD, incoming-SMS and delivery-report URLs into the AT dashboard. `MESSAGING_CALLBACK_TOKEN` must be set; HTTPS only.
4. **Delivery reports:** after `fundbridge-messaging send-test --to +254...`, the log shows `SMS delivery report id=... status=...`.
5. **Shortcode and USSD approval (production):** KYC on the AT account, then apply for a two-way shortcode and a USSD service code (shared or dedicated). Telco approval takes weeks. Budget the prepaid SMS balance.
6. **Sandbox to production:** run steps 1–8 of `africastalking.md` in the sandbox, then repeat with live credentials and a handset on each target network.
7. **Evidence:** dates, message IDs, the masked numbers used, and screenshots of the USSD screens in English and Kiswahili.

## PayPal (donations)

1. **Sandbox app:** at developer.paypal.com, go to Apps & Credentials → Sandbox → create an app. Set `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` and `PAYPAL_BASE_URL=https://api-m.sandbox.paypal.com`.
2. **Webhook:** add `https://<backend>/api/v1/webhooks/paypal` for `PAYMENT.CAPTURE.COMPLETED`, then set `PAYPAL_WEBHOOK_ID`. The backend verifies every event with PayPal's verify-webhook-signature API and rejects anything unverified. Trigger it with a real sandbox payment.
3. **Order creation:** `POST /api/v1/donations/orders` → `201` with an `approval_url` on sandbox.paypal.com.
   **Blocked by C-4b** until the canonical adapter sends `Prefer: return=representation` on create-order. PayPal's default response omits `purchase_units`, which the backend now validates, so this returns `400 PAYMENT_ORDER_MISMATCH`. The reproductions are in `COORDINATION.md`.
4. **Approval and capture:** approve with a sandbox personal account. The return page calls capture and then `GET /donations/{id}` → `completed`. `GET /campaigns/{id}/funds` shows the amount raised once.
5. **Ambiguous capture reconciliation:**
   - `POST /api/v1/donations/{id}/reconcile` on the completed donation returns it unchanged, with no second credit.
   - On an approved but uncaptured order it stays `pending`.
   - The timeout path itself (PayPal captured, our response lost) is tested only against the local double.
6. **Evidence:** the order ID, capture ID, donation ID, the ledger entry and the webhook event ID.
7. **Production:** a PayPal business account in good standing, live app credentials and a live webhook. Confirm PayPal's rules for charitable or crowdfunding use in the target markets **before** launch. Never route donations around PayPal's restrictions.

## Payout provider (mobile money to beneficiaries)

No provider is integrated. Payouts stop at `approved_for_submission` and the payout simulator never reports `succeeded`. Direct payouts from PayPal to another person's M-Pesa wallet are **not** a confirmed capability; do not design around them.

1. **Eligibility:** choose a provider licensed for business-to-customer disbursements in the target country (for example the mobile-network operator's B2C API, or a licensed aggregator). Confirm KYC and KYB requirements for FundBridge as the disbursing organisation, per-transaction and daily limits, supported wallets, fees and whether the provider is allowed to pay out crowdfunding proceeds.
2. **Authorization:**
   - **Already in place:** the requester is never the approver (`SELF_APPROVAL_FORBIDDEN`); the beneficiary must be verified; reserved funds are checked under a row lock.
   - **Still to build (backend, Codex):** a submission endpoint that sends an approved payout with server-side credentials and a provider idempotency reference, moving it to `submitted`.
3. **Settlement confirmation:**
   - **Already in place:** `succeeded` is set only through `apply_provider_status` on a verified provider callback or status query; submission is never success.
   - **Still to build:** callbacks must be authenticated by the provider's documented mechanism (signature, mutual TLS or an allowlist plus secret).
4. **Failure and reconciliation:**
   - **Already in place:** `FAILED` releases the reservation; ambiguous timeouts never release funds.
   - **Still to build:**
     - a scheduled status query for `submitted` and `pending_confirmation` payouts;
     - a daily reconciliation against the provider statement;
     - a manual-review queue for mismatches;
     - beneficiary SMS for every state change (the notification hooks already send them).
5. **Evidence:** the provider contract or approval, sandbox payout IDs for success, failure and timeout cases, and a reconciliation report.
