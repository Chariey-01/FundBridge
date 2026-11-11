# AI and feature-phone API

For the frontend (Cursor) and anyone calling these endpoints. Base path `/api/v1`. All JSON responses use the shared envelope:

```json
{ "data": { }, "meta": { } }
{ "error": { "code": "VALIDATION_ERROR", "message": "…", "details": { "field": ["…"] } } }
```

Authentication is the core backend's JWT: `Authorization: Bearer <access_token>` from `POST /api/v1/auth/login`.

## Rules for the UI

1. **Never show a financial outcome the backend has not reported.** Donation success comes only from `GET /donations/{id}` returning `status: "completed"`. Payout success comes only from `GET /payouts/{id}` returning `status: "succeeded"`. Do not infer success from a PayPal redirect, a 2xx on create, an AI reply or an SMS.
2. **AI output is a suggestion.** Drafts are never saved by the AI endpoint. Put them into the editable form, show `warnings` and `disclaimer`, and save through `POST/PATCH /campaigns`.
3. **Label machine output.** Show `meta.ai_generated` / `meta.provider`. When `provider` is `"fallback"`, the text came from a template or rule, not a model.
4. **Render text as text.** All strings are plain text (markup is stripped server-side); still escape on render and never use `dangerouslySetInnerHTML`.
5. **Show integration states honestly.** Read `GET /integrations/status` and label simulated channels as simulated.

## Integration status

`GET /integrations/status` (public)

```json
{
  "data": {
    "ai": {
      "provider": "fallback", "model": null, "mode": "fallback_only",
      "features": { "campaign_draft": "template_fallback", "translate": "unavailable",
                    "beneficiary_assistant": "rule_based_fallback", "campaign_search": "keyword_fallback",
                    "status_explanation": "verified_text_only" },
      "daily_request_limit": 2000,
      "supported_languages": { "en": "English", "sw": "Kiswahili", "...": "..." },
      "model_verified": false, "last_success_at": null, "last_error": null
    },
    "messaging": {
      "sms": { "provider": "simulator", "mode": "simulated", "delivery_confirmed": false },
      "ussd": { "service_code": "*384*123#", "callback_configured": true, "live_shortcode_verified": false },
      "simulator_enabled": true, "notifications_enabled": true, "sms_assistant": "rule_based"
    }
  }
}
```

`ai.mode` is `live` when an OpenAI key is configured; that alone does not mean it works. `model_verified` becomes `true` after a real model call succeeds in that server process, and `last_error` (`{code, feature, at}`) shows the most recent provider failure. Model, configuration and verification: `openai.md`. `sms.mode` is `simulated`, `africastalking_sandbox` (messages reach Africa's Talking's simulator, not phones) or `africastalking_live`.

## AI endpoints

Rate limits: 10/min per signed-in user, 20/min per IP for anonymous calls (`429 RATE_LIMITED`, `Retry-After` header). `AI_DAILY_REQUEST_LIMIT` (default 2000 provider calls per UTC day per process) switches to the fallbacks when reached.
Errors: `400 VALIDATION_ERROR` (with `details`), `401 AUTH_REQUIRED` / `INVALID_TOKEN` / `TOKEN_EXPIRED` and `403 ACCOUNT_INACTIVE` (same codes as the core API), `403 FORBIDDEN` / `404 NOT_FOUND` (status explanation), `413 PAYLOAD_TOO_LARGE`, `429 RATE_LIMITED`, `503 AI_UNAVAILABLE` (translation only).

Every success has `meta`: `{ "provider": "openai" | "fallback" | "none", "model": string | null, "ai_generated": bool, "degraded": bool, "fallback_reason"?: string }`. `degraded: true` means a configured provider failed and the fallback answered.

### `POST /ai/campaign-draft` (signed in)

Request:
```json
{ "story_notes": "20-3000 chars", "category": "education", "beneficiary_first_name": "Amina",
  "location": "Kisumu", "goal": { "amount": "400.00", "currency": "USD" }, "language": "en" }
```
Only `story_notes` is required. `category` is one of `medical, education, emergency, community, agriculture, small_business, housing, water_sanitation, other`. Amounts are decimal strings, never numbers.

Response `data`:
```json
{ "title": "…", "summary": "…", "story": "…", "suggested_category": "education",
  "missing_information": ["School name"], "warnings": ["…"], "language": "en",
  "requires_human_review": true, "disclaimer": "AI-assisted draft. …" }
```
`warnings` covers removed contact details, removed links, claims that money moved or that FundBridge verified something, guarantees, and amounts that differ from the goal. When AI is unavailable (`meta.ai_generated: false`), `disclaimer` says the text is a template built from the notes, not an AI draft. Keep the creator's original notes in the form either way.

### `POST /ai/translate` (public, IP-limited when anonymous)

Request: `{ "text": "≤2000 chars", "target_language": "sw", "source_language": "en" }` (source optional).
Response `data`: `{ "translated_text", "source_language", "target_language", "machine_translation": true, "notice", "warnings" }`.
No fallback: `503 AI_UNAVAILABLE` when no model is configured. Show the original text.

### `POST /ai/beneficiary-assistant` (signed in)

Request: `{ "message": "≤1000 chars", "language": "sw", "topic": "general|payouts|campaign|account|donations" }`.
Response `data`:
```json
{ "reply": "…", "language": "sw", "suggested_actions": ["view_payout_status"],
  "escalate_to_human": false, "notice": "This assistant cannot see or change balances, …" }
```
When AI is unavailable, `notice` starts "AI is unavailable, so this is a standard answer." `suggested_actions` ⊂ `view_campaign_status, view_payout_status, contact_community_agent, edit_campaign_draft, verify_phone_number, learn_about_fees, learn_about_payouts, learn_about_donating`. They are navigation hints only. If `escalate_to_human` is true, show the agent contact path prominently. `meta.output_replaced_by_guardrail: true` means the model's reply asserted a financial outcome and was replaced.

### `POST /ai/campaign-search` (public)

Request: `{ "query": "help girls finish school in Kenya", "language": "en", "limit": 10 }`.
Response `data`:
```json
{ "interpreted_filters": { "keywords": ["school"], "category": "education", "country_code": "KE" },
  "filters_relaxed": false,
  "results": [ { "id", "slug", "title", "summary", "category", "country_code",
                 "goal": { "amount": "400.00", "currency": "USD" },
                 "raised": { "amount": "25.50", "currency": "USD" } } ] }
```
Only published campaigns. `raised` is summed from confirmed ledger entries; pending donations are not counted. `notice` is `null` when AI interpreted the query, otherwise "AI search is unavailable, so results use simple keyword matching."

### `POST /ai/status-explanation` (signed in)

Explains one donation or payout in plain language **from FundBridge's own record**. It is read-only: nothing it returns or does can change a status, an amount or the ledger. Access is exactly that of `GET /donations/{id}` (the donor, reviewers, admins) and `GET /payouts/{id}` (the payout's own beneficiary, reviewers, admins): `403 FORBIDDEN` otherwise, `404 NOT_FOUND` for an unknown id.

Request: `{ "kind": "donation" | "payout", "id": "<uuid>", "language": "sw" }`.
Response `data`:
```json
{ "kind": "payout", "id": "…", "status": "approved_for_submission", "status_label": "Approved, being prepared",
  "confirmed": false, "final": false, "amount": { "amount": "40.00", "currency": "USD" },
  "campaign_title": "School fees for Amina", "campaign_raised": null, "as_of": "2026-11-11T10:00:00+00:00",
  "explanation": "…", "language": "en",
  "verified_text": "Your payout of 40.00 USD from \"School fees for Amina\" is approved and being prepared. It has not been sent to the mobile-money provider yet, so the money has not arrived.",
  "verified_text_language": "en", "notice": "…", "source": "backend_record" }
```
- Render the status badge from `status_label` and `confirmed`; `confirmed` is true only for donation `completed` and payout `succeeded`. The `explanation` is supporting text.
- `verified_text` is FundBridge's deterministic wording, in English or Kiswahili. When AI is live, `explanation` is the model's rewording (en/sw) or translation (other languages). If the model's text contradicts the record, it is replaced by `verified_text`, and `meta.output_replaced_by_guardrail` and `meta.guardrail_reason` say so.
- Without AI, `explanation` equals `verified_text`. For languages other than English and Kiswahili it is in English, and `language` says `en`.
- `campaign_raised` (donations only) is the campaign's ledger-backed confirmed total.

### `GET /ai/status` (public)

Same as `data.ai` in `/integrations/status`.

## Feature-phone endpoints

### Gateway callbacks (Africa's Talking format)

| Endpoint | Body (form-encoded) | Response |
|---|---|---|
| `POST /messaging/ussd?token=…` | `sessionId, serviceCode, phoneNumber, text` | `text/plain`: `CON …` (continue) or `END …` |
| `POST /messaging/sms/inbound?token=…` | `from, to, text, date, id, linkId, networkCode` | `200`; replies go out through the SMS gateway |
| `POST /messaging/sms/delivery?token=…` | `id, status, phoneNumber, networkCode, failureReason, retryCount` | `200`; recorded and logged (masked number); `400` if `id`/`status` missing |

Retries are safe: an inbound SMS with an `id` already processed gets no second reply; a repeated USSD PIN step (same `sessionId` and `text`) is not counted as another wrong attempt; repeated help requests within 30 minutes return the same reference. Gateway setup and testing: `africastalking.md`.

The token can also be sent as `X-FundBridge-Callback-Token`. A wrong token returns `403 INVALID_CALLBACK`; no configured token returns `503 MESSAGING_NOT_CONFIGURED`.

Every screen is GSM 7-bit text of at most 182 characters (long titles are shortened; search may show fewer than three results). Options 1 and 2 answer only numbers on a **verified** beneficiary profile; after a phone or payout-destination change the number gets "waiting for verification, contact your agent" until a reviewer re-verifies it.

USSD menu (English and Kiswahili; `0` back, `00` home). The Kiswahili text awaits native-speaker review: `kiswahili-review.md`.

```
1. My campaign        -> status and confirmed raised total (from the ledger)
2. My payout status   -> 4-digit PIN (created on first use, 3 tries then 30 min lock) -> latest payout state
3. Find a campaign    -> keyword search, top 3
4. How donors give    -> PayPal link to the web app
5. Get help           -> agent callback / report problem / changed phone or SIM (high priority)
6. Language/Lugha
```

SMS commands: `HELP`/`MSAADA`, `STATUS`/`HALI`, `FIND <word>`/`TAFUTA`, `AGENT`/`WAKALA`, `LANG SW|EN`, `STOP`/`START`, `PAYOUT` (replies with the USSD code; payout details are never sent by SMS). Other text gets the guarded assistant when AI is live, otherwise the command list.

### Notifications sent to beneficiaries

Sent after the database commit, never on rollback, and only to verified beneficiary profiles (GSM 7-bit, at most two SMS segments):
- a donation becomes `completed`: "received a confirmed donation of USD 15.00. Total raised: …";
- a payout changes status: the status label below. Payout messages are sent even after `STOP` because they are account-security relevant.

### Payout status labels (shared state machine)

| status | English label |
|---|---|
| requested | Requested, waiting for review |
| under_review | Under review |
| rejected | Not approved. Contact your agent |
| approved_for_submission | Approved, being prepared |
| submitted | Sent to the mobile money provider, awaiting confirmation |
| pending_confirmation | Awaiting confirmation. Do not request again |
| succeeded | Paid to your mobile money account |
| failed | Not completed. Your agent will help you |

Use the same meanings in the web UI. Only `succeeded` may say the money arrived.

### Staff endpoints

| Endpoint | Who | Purpose |
|---|---|---|
| `GET /messaging/support-requests` | agent, admin | Latest 100 phone support requests |
| `POST /messaging/beneficiaries/{id}/pin-reset` | admin | Clear the phone PIN; the beneficiary creates a new one on next use (audited) |

### Simulator (demo only, `MESSAGING_SIMULATOR_ENABLED=true`)

| Endpoint | Body | Notes |
|---|---|---|
| `GET /messaging/simulator` | | HTML phone simulator |
| `POST /messaging/simulator/ussd` | `{ "phone_number", "text", "session_id"? }` | `text` is cumulative, like Africa's Talking (`"2*4826"`) |
| `POST /messaging/simulator/sms` | `{ "phone_number", "text" }` | returns `replies` |
| `GET /messaging/simulator/outbox?phone_number=` | | simulated outbound SMS |

All simulator responses carry `meta.simulated: true`. Disabled endpoints return 404.
