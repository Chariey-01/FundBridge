# Release probe: AI and feature phone against a real server (generated)

Generated 2026-11-12 05:04 UTC by `backend/scripts/release_probe.py`.

**Real:** gunicorn (`FLASK_ENV=production`), PostgreSQL, migrations, seeded demo data, JWT, the AI service and guardrails, USSD/SMS callback handling, the ledger. **Double:** OpenAI (local OpenAI-compatible stand-in, with replies changed per check to simulate hostile model output). SMS: simulated outbox, then an unreachable Africa's Talking URL. **No live OpenAI, PayPal or Africa's Talking request was made.**

**Result: 55 passed, 0 failed.**

### Integration status (labels)

- **PASS** AI mode is 'live' (key configured) but model_verified is false before any call: provider=openai
- **PASS** SMS reported as simulated, delivery not confirmed
- **PASS** USSD shortcode not reported as verified
- **PASS** Five AI features listed, daily cap reported

### AI with the OpenAI double: five features, PII minimisation, injection and hostile outputs

- **PASS** Draft: 200, AI-generated, attributed as AI-assisted
- **PASS** Draft: phone and e-mail redacted before the model call; notes wrapped as data
- **PASS** Draft: request sent with store=false and strict JSON schema
- **PASS** AI status now model_verified=true (a call succeeded in this process)
- **PASS** Draft hostile output: markup and links stripped, claims flagged as warnings: 5 warnings
- **PASS** Translate: 200, labelled machine translation, phone not sent to the model
- **PASS** Search: results only from published campaigns in the database: 1 result(s)
- **PASS** Search: model cannot invent campaigns
- **PASS** Assistant: invented payout confirmation replaced, link removed
- **PASS** Assistant: security report always escalates to a human
- **PASS** Status explanation (completed donation): from the record, AI-written, confirmed=true
- **PASS** Status explanation: 'beneficiary has received' for a donation is replaced
- **PASS** Status explanation: invented confirmation of a pending donation is replaced
- **PASS** Status explanation: 'paid' for an approved (unsent) payout is replaced by the Kiswahili verified text
- **PASS** Status explanation: no payout id, wallet token or phone sent to the model
- **PASS** Status explanation access: donor -> payout = 403: 403
- **PASS** Status explanation access: beneficiary-sw -> payout = 403: 403
- **PASS** Status explanation access: beneficiary -> donation = 403: 403
- **PASS** Status explanation access: reviewer -> payout = 200: 200
- **PASS** Status explanation: anonymous caller refused

### AI unavailable (double returns HTTP 500): fallbacks and attribution

- **PASS** Draft fallback: degraded, not attributed to AI
- **PASS** Assistant fallback says AI is unavailable
- **PASS** Search fallback: keyword results with a notice
- **PASS** Translate fallback: 503 AI_UNAVAILABLE (UI keeps the original)
- **PASS** Status explanation fallback: verified text with a notice
- **PASS** Status reports the provider failure

### Rate limit and daily cap

- **PASS** Per-user limit: 11th request in a minute is 429 with Retry-After
- **PASS** Daily cap: fallbacks answer once the cap is reached; the provider is not called again: provider calls in this process: 40 (cap 40)

### No AI effect on money, campaigns or beneficiaries

- **PASS** Donations, payouts, ledger, campaign statuses and beneficiary profiles unchanged by every AI call above

### USSD and SMS through the Africa's Talking callback format (simulated outbox)

- **PASS** Callback without the secret: 403
- **PASS** Callback with a wrong secret: 403
- **PASS** English menu, text/plain CON
- **PASS** Kiswahili menu for the Kiswahili profile
- **PASS** Campaign choice, then status from the ledger: 150.00 confirmed, the pending 20.00 not counted: END School fees for Amina (demo) | Status: Live | Raised: USD 150.00 of USD 400.00
- **PASS** Unknown number gets nothing beneficiary-specific
- **PASS** PIN setup: weak PIN refused
- **PASS** PIN set; payout status shown, approved is not 'paid': END Payout USD 40.00 | Status: Approved, being prepared | Updated: 12 Nov 2026
- **PASS** Retried wrong-PIN step (same session and text) counts once
- **PASS** Lockout after 3 wrong PINs; the right PIN is refused while locked, nothing leaks
- **PASS** Kiswahili PIN flow and payout label: END Malipo USD 30.00 | Hali: Yameombwa, yanasubiri ukaguzi | Yamesasishwa: 12 Nov 2026
- **PASS** Inbound SMS retried with the same id is answered once
- **PASS** Outbox labelled simulated; every message status 'simulated'
- **PASS** Delivery report without id/status: 400
- **PASS** Delivery report accepted, and accepted again (idempotent)
- **PASS** Simulator USSD labelled simulated
- **PASS** Simulator is rate-limited per IP: first 429 at request 58

### Messaging unavailable: SMS provider unreachable

- **PASS** Status says Africa's Talking sandbox, delivery not confirmed
- **PASS** USSD keeps working while SMS is down
- **PASS** Payout review still succeeds though its SMS cannot be sent
- **PASS** Inbound SMS callback still answers 200 (reply fails quietly, logged)

### Server logs

- **PASS** Logs contain neither the callback secret, the OpenAI key nor a full beneficiary number
