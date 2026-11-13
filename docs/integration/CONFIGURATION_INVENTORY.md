# AI and messaging configuration inventory

Verified against the code on 2026-11-12. Every variable below is read by `backend/app/` (found with the same scan
that `tests/integration/test_env_example.py` runs) and listed in `backend/.env.example`. No names are invented. This
file contains no values; never commit real ones.

**Configured today: none of the provider settings.**
- No `backend/.env` exists in the repository checkouts, and `.env` is git-ignored.
- No AI or messaging variable is set in the development shell.
- The GitHub repository has no Actions secrets or variables.
- The repository has no deployment config (no Procfile, render, fly or Docker files).

Wherever a default exists, the code's default applies.

Environments:
- **Local:** your machine; providers simulated or absent.
- **Sandbox:** a real provider sandbox (OpenAI has no sandbox; it means the real API with a test project).
- **Staging / Production:** deployed hosts.

## OpenAI

| Variable | Controls | Where you get it | Needed for | Secret? | Code support | Status |
|---|---|---|---|---|---|---|
| `OPENAI_API_KEY` | Enables the OpenAI provider; without it every AI feature uses its fallback and translation returns 503 | platform.openai.com → your project → API keys → create a **project** key | real-API test, staging, production (not local) | **secret** | yes | **missing** |
| `OPENAI_MODEL` | Chat Completions model; it must support strict JSON-schema Structured Outputs | your choice; confirm the project can use it (`flask --app run:app fundbridge-ai check`) | optional (default `gpt-5.4-mini`, never verified by a real call) | public | yes | default only |
| `AI_PROVIDER` | `auto` (OpenAI when a key is set), `openai` (same, plus a warning when the key is missing), `disabled` (fallbacks only) | your choice | optional (default `auto`) | public | yes | default |
| `OPENAI_REASONING_EFFORT` | `reasoning_effort` sent with reasoning models; `omit` sends nothing | your choice | optional (default `low` for reasoning models, nothing for `gpt-4*`) | public | yes | default |
| `OPENAI_REASONING_TOKEN_ALLOWANCE` | Extra `max_completion_tokens` when an effort is sent | your choice | optional (default `1024`) | public | yes | default |
| `OPENAI_BASE_URL` | Alternative endpoint (proxy or compatible gateway); tests point it at the local double | leave empty for OpenAI | optional | public | yes | empty |
| `AI_TIMEOUT_SECONDS` | Per-request timeout | your choice | optional (default `15`) | public | yes | default |
| `AI_MAX_RETRIES` | SDK retries for 5xx, 429 and connection errors | your choice | optional (default `1`) | public | yes | default |
| `AI_RATE_LIMIT_PER_MINUTE` | Per signed-in user, per process | your choice | optional (default `10`) | public | yes | default |
| `AI_PUBLIC_RATE_LIMIT_PER_MINUTE` | Per IP for anonymous translate and search, per process | your choice | optional (default `20`) | public | yes | default |
| `AI_DAILY_REQUEST_LIMIT` | Provider calls per UTC day per process; beyond it the fallbacks answer; `0` = no cap | your choice | optional (default `2000`) | public | yes | default |
| `SECRET_KEY` | Also salts the hashed `safety_identifier` sent to OpenAI, and the USSD retry-detection HMAC | generate: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` | every environment | **secret** | yes | **missing** (no deployment) |

OpenAI project settings have no FundBridge variable:
- **Key:** use a project-scoped key; the project travels with the key.
- **Spending:** set a monthly budget or usage limit on the project in the OpenAI dashboard.
- **SDK variables:** FundBridge does not read `OPENAI_ORG_ID` or `OPENAI_PROJECT_ID`. The installed OpenAI SDK (2.54.0) would pick them up from the environment, but with a project key they are unnecessary. They are not documented or tested here, so leave them unset.

Test-only switch: `FUNDBRIDGE_LIVE_OPENAI_TESTS=1` (together with `OPENAI_API_KEY`) runs `tests/ai/test_openai_live.py`. The app does not read it.

## Africa's Talking (SMS and USSD)

| Variable | Controls | Where you get it | Needed for | Secret? | Code support | Status |
|---|---|---|---|---|---|---|
| `SMS_PROVIDER` | `simulator` (in-memory outbox, nothing sent) or `africastalking` | your choice | sandbox, staging, production: `africastalking` | public | yes | default `simulator` |
| `AT_USERNAME` | `sandbox` sends to `api.sandbox.africastalking.com` (Africa's Talking's simulator only); any other value is your live app username and uses `api.africastalking.com` | Africa's Talking dashboard: the sandbox app's username is `sandbox`; a live app shows its username | sandbox, staging, production | public identifier | yes | **missing** |
| `AT_API_KEY` | Authenticates outbound SMS (`apiKey` header) | Africa's Talking dashboard → the app (sandbox or live) → Settings → API key | sandbox, staging, production | **secret** | yes | **missing** |
| `AT_SENDER_ID` | `from` on outbound SMS. Empty uses Africa's Talking's default sender. For two-way SMS, use your shortcode. An alphanumeric sender ID is one-way and must be registered | sandbox: a sandbox shortcode; live: a leased shortcode or a registered sender ID (KYC and approval) | optional in sandbox; production | public identifier | yes | **missing** |
| `AT_API_BASE_URL` | Overrides the API host (tests and egress proxies only) | leave empty | no | public | yes | empty |
| `USSD_SERVICE_CODE` | The code shown in SMS replies and docs, such as `*384*123#`. Routing itself is set in Africa's Talking's USSD channel | sandbox: create a USSD channel; live: a shared or dedicated code (telco approval) | sandbox, staging, production | public | yes | default `*384*123#` is a **placeholder** |
| `MESSAGING_CALLBACK_TOKEN` | Shared secret on all three callbacks; **at least 24 characters** (shorter: callbacks refused with 503) | generate it yourself (same command as `SECRET_KEY`) | any environment that receives callbacks | **secret** | yes | **missing** |
| `MESSAGING_ALLOWED_IPS` | Comma-separated IPs or CIDRs allowed to call the callbacks; empty means token only | Africa's Talking's published or support-confirmed callback source addresses (not confirmed in this repository) | recommended for production | public | yes | empty |
| `TRUSTED_PROXY_HOPS` | Number of reverse proxies to trust for the client IP (allowlist and rate limits) | your hosting setup (often `1`) | staging and production behind a proxy | public | yes | default `0` |
| `PUBLIC_BASE_URL` | HTTPS link printed in SMS and USSD text; keep it short (182-character screens) | your web app's public URL | staging, production (`check-config` errors if it is empty, or not https unless the host is localhost) | public | yes | **missing** (falls back to `FRONTEND_ORIGIN`, then localhost) |
| `MESSAGING_DEFAULT_COUNTRY` | Country for normalising local numbers (`0712…` → `+254712…`) | `KE` for Kenya | optional (default `KE`) | public | yes | default |
| `MESSAGING_NOTIFICATIONS_ENABLED` | SMS on confirmed donations and payout status changes (after commit) | your choice | optional (default `true`) | public | yes | default |
| `MESSAGING_SMS_ASSISTANT_ENABLED` | Free-text SMS answered by the AI assistant (rule-based without AI) | your choice | optional (default `true`) | public | yes | default |
| `MESSAGING_SIMULATOR_ENABLED` | Browser phone simulator and its endpoints (labelled simulated) | `true` only for local or demo | local and demo only; `check-config` errors if it is on in production | public | yes | default `false` |
| `MESSAGING_SIMULATOR_RATE_LIMIT` | Simulator requests per minute per IP | your choice | optional (default `60`) | public | yes | default |

### Callback URLs to register in the Africa's Talking dashboard

Africa's Talking cannot send custom headers, so the token goes in the query string (the app also accepts the
`X-FundBridge-Callback-Token` header). `flask --app run:app fundbridge-messaging check-config --api-host https://<backend-host>`
prints these URLs without the token:

| Callback | URL | What Africa's Talking sends | FundBridge answers |
|---|---|---|---|
| USSD channel callback | `https://<backend-host>/api/v1/messaging/ussd?token=<MESSAGING_CALLBACK_TOKEN>` | form: `sessionId`, `serviceCode`, `phoneNumber`, `text` | `text/plain` starting `CON ` or `END ` |
| SMS incoming messages | `https://<backend-host>/api/v1/messaging/sms/inbound?token=<MESSAGING_CALLBACK_TOKEN>` | form: `from`, `to`, `text`, `date`, `id`, `linkId`, `networkCode` | 200; the reply goes out through the SMS API |
| SMS delivery reports | `https://<backend-host>/api/v1/messaging/sms/delivery?token=<MESSAGING_CALLBACK_TOKEN>` | form: `id`, `status`, `phoneNumber`, `networkCode`, `failureReason`, `retryCount` | 200 (400 when `id` or `status` is missing) |

The callbacks must be reachable over public HTTPS, so sandbox callbacks need a staging host (or a tunnel). Locally,
use the simulator: `MESSAGING_SIMULATOR_ENABLED=true`, then open `/api/v1/messaging/simulator`. Step-by-step sandbox
test: `africastalking.md`.

## Also required by every deployment (not provider-specific)

`SECRET_KEY` and `JWT_SECRET_KEY` are secrets; `DATABASE_URL` (PostgreSQL) is a secret because it contains the password; `FRONTEND_ORIGIN` is public; and `FLASK_ENV=production` must be set. PayPal (`PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` (secret), `PAYPAL_WEBHOOK_ID`, `PAYPAL_BASE_URL`) is covered in `docs/DEPLOYMENT.md` and `EXTERNAL_CHECKLIST.md`.

## Copy-ready checklist

```text
OpenAI (real API test, then staging/production)
[ ] Create an OpenAI project for FundBridge; set a monthly budget on it
[ ] Create a project API key                          -> OPENAI_API_KEY        (secret; server only)
[ ] Decide the model                                  -> OPENAI_MODEL          (default gpt-5.4-mini, unverified)
[ ] Keep AI_PROVIDER=auto; keep AI_DAILY_REQUEST_LIMIT (2000) or lower it
[ ] flask --app run:app fundbridge-ai check           -> expect a verified model; record date + model in openai.md
[ ] FUNDBRIDGE_LIVE_OPENAI_TESTS=1 pytest tests/ai/test_openai_live.py

Africa's Talking sandbox (needs a public HTTPS staging host)
[ ] Create an Africa's Talking account; open the sandbox app
[ ] AT_USERNAME=sandbox ; generate the sandbox API key -> AT_API_KEY           (secret)
[ ] SMS_PROVIDER=africastalking
[ ] Generate MESSAGING_CALLBACK_TOKEN (>= 24 chars)    (secret)
[ ] Create a sandbox USSD channel                      -> USSD_SERVICE_CODE
[ ] Optional: sandbox shortcode for two-way SMS        -> AT_SENDER_ID
[ ] PUBLIC_BASE_URL=https://<short web URL> ; MESSAGING_SIMULATOR_ENABLED=false on staging
[ ] Register the 3 callback URLs (USSD, incoming SMS, delivery reports) with ?token=
[ ] flask --app run:app fundbridge-messaging check-config --api-host https://<backend-host>  -> exit 0
[ ] flask --app run:app fundbridge-messaging send-test --to +2547XXXXXXXX
[ ] Run steps 3-8 of docs/integration/africastalking.md; record results (numbers masked)

Africa's Talking production
[ ] Live app + KYC; prepaid balance                    -> AT_USERNAME=<live app username>, AT_API_KEY (secret)
[ ] Two-way shortcode or registered sender ID          -> AT_SENDER_ID
[ ] USSD code (shared or dedicated, telco approval)    -> USSD_SERVICE_CODE
[ ] Africa's Talking callback source IPs               -> MESSAGING_ALLOWED_IPS ; TRUSTED_PROXY_HOPS behind a proxy
[ ] One gunicorn worker (rate limits, AI cap and simulator are per process)
```
