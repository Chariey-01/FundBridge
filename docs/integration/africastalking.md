# Africa's Talking (SMS and USSD): configuration and real-provider testing

FundBridge's feature-phone channel uses Africa's Talking (AT) for USSD sessions, inbound SMS, outbound SMS and delivery reports. The default `SMS_PROVIDER=simulator` sends nothing; it is labelled as simulated everywhere.

## Verification status

**FundBridge has not been connected to an Africa's Talking account.** No sandbox or live request has been made from this repository, and no service code or shortcode exists. What has been tested:

| Level | What runs | Where |
|---|---|---|
| Adapter wire tests | Real `AfricasTalkingSmsGateway` against a fake HTTP session: request fields, `apiKey` header, sandbox and live hosts, status codes 100-502, HTTP errors, timeouts, malformed bodies, GSM normalization, 2-segment cap | `backend/tests/messaging/test_africastalking_gateway.py` |
| Callback tests | USSD, inbound-SMS and delivery-report callbacks through the real app: token and IP checks, retries, PIN lockout and race, verification gating, English and Kiswahili, gateway and AI outages | `backend/tests/integration/test_feature_phone_hardening.py`, `test_phone_channel_verification.py`, `test_pin_concurrency.py` (PostgreSQL) |
| Live HTTP (e2e) | gunicorn with `SMS_PROVIDER=africastalking`, sending to a local double of the AT SMS API; callbacks in AT's form format | `backend/tests/e2e/test_africastalking_journeys.py` |

**Assumptions to confirm against AT's documentation or a real callback:**

- **Confirmed by public sources:** USSD fields `sessionId, serviceCode, phoneNumber, networkCode, text` with cumulative `text`, `CON`/`END` replies, and a response window of about 10 s; the SMS endpoint `/version1/messaging` with an `apiKey` header; recipient `statusCode` 101.
- **Not confirmed:** the inbound-SMS fields (`from, to, text, date, id, linkId, networkCode`), the delivery-report fields (`id, status, phoneNumber, networkCode, failureReason, retryCount`), and whether AT retries callbacks. The handlers accept exactly these fields, and duplicates are harmless either way.
- **The 182-character screen limit** is the GSM USSD maximum. AT's own limit was not found in its docs.

## What you need from Africa's Talking

| Item | Sandbox | Live (production) |
|---|---|---|
| Account | Free; use the built-in "sandbox" app | Verified business account (KYC); prepaid balance for SMS |
| API key | Generate in the sandbox app → `AT_API_KEY`; `AT_USERNAME=sandbox` | Generate in the live app → `AT_API_KEY`; `AT_USERNAME=<your app username>` |
| USSD service code | Create a sandbox channel such as `*384*xxxx#` → `USSD_SERVICE_CODE` | Apply for a shared or dedicated code. Telco approval is required and takes time; plan for weeks, not days. |
| SMS shortcode / sender | Create a sandbox shortcode for inbound SMS | Buy or lease a shortcode for two-way SMS (`AT_SENDER_ID` = the shortcode). An alphanumeric sender ID is one-way and must be registered. |
| Callback URLs | Set in the AT dashboard (below) | Same, on the production host |

Africa's Talking does not document signatures on these callbacks. FundBridge therefore requires a shared secret in the URL (`?token=`), compared in constant time, plus an optional source-IP allowlist (`MESSAGING_ALLOWED_IPS`, with `TRUSTED_PROXY_HOPS` behind a proxy). Without `MESSAGING_CALLBACK_TOKEN`, or with one shorter than 24 characters, every callback returns 503 (`MESSAGING_NOT_CONFIGURED`). Generate it with `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. Use HTTPS only, and do not enable access logs that record query strings.

## Configuration

```bash
SMS_PROVIDER=africastalking
AT_USERNAME=sandbox                 # live: your app username
AT_API_KEY=...                      # secret; never commit
AT_SENDER_ID=                       # live two-way SMS: your shortcode
USSD_SERVICE_CODE=*384*1234#
MESSAGING_CALLBACK_TOKEN=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
PUBLIC_BASE_URL=https://short.domain  # shown on USSD screens; keep it short (182-character screens)
MESSAGING_ALLOWED_IPS=                # add AT's callback addresses once confirmed
MESSAGING_SIMULATOR_ENABLED=false
```

Then run `flask --app run:app fundbridge-messaging check-config --api-host https://<backend-host>`. It reports blocking errors (missing token, non-https URL, bad USSD code, simulator enabled in production) and prints the three callback URLs to paste into the AT dashboard:

```
USSD              https://<backend-host>/api/v1/messaging/ussd?token=<MESSAGING_CALLBACK_TOKEN>
Incoming SMS      https://<backend-host>/api/v1/messaging/sms/inbound?token=<MESSAGING_CALLBACK_TOKEN>
Delivery reports  https://<backend-host>/api/v1/messaging/sms/delivery?token=<MESSAGING_CALLBACK_TOKEN>
```

## Real-provider test procedure (sandbox first)

Prerequisites: the backend deployed on HTTPS with PostgreSQL, a verified beneficiary whose profile phone number is the number you will use in AT's simulator, at least one published campaign, and one confirmed sandbox donation.

1. **Configuration:** `check-config` exits 0.
2. **Outbound SMS:** `flask --app run:app fundbridge-messaging send-test --to +2547XXXXXXXX`. Expect `status=submitted` with an AT message ID. In the sandbox, open AT's simulator for that number and confirm the message appears. `submitted` alone is not delivery.
3. **Delivery report:** within a few minutes the backend logs `SMS delivery report id=... status=...`. If nothing arrives, check the delivery-report URL and token.
4. **USSD:** in AT's simulator, dial the service code from the beneficiary's number. Check each of these:
   - The main menu appears, and option 6 switches to Kiswahili.
   - Option 1 shows the campaign with the ledger total.
   - Option 2 asks you to create a PIN, then shows the latest payout status.
   - Three wrong PINs lock it for 30 minutes.
   - Option 3 finds the campaign.
   - Option 5 → 1 returns a reference that appears in `GET /api/v1/messaging/support-requests`.
5. **Verification gate:** change the beneficiary's phone (`PATCH /beneficiaries/me`), dial from the new number, and confirm options 1 and 2 answer "waiting for verification". After a reviewer re-verifies, confirm they work.
6. **Inbound SMS:** send `HALI` and `AGENT` to the sandbox shortcode. Expect one reply each, and one support request.
7. **Notifications:** approve a payout as a reviewer. The beneficiary's number receives "payout of ...: Approved, being prepared", which is never "paid".
8. **Outage behaviour:** set a wrong `AT_API_KEY` and repeat step 7. The payout review still succeeds and the log shows `Africa's Talking request failed` or `http_401`.
9. Record the results (date, numbers masked, message IDs) and only then change the status of this integration in `docs/DEPLOYMENT.md`.

For live traffic, repeat steps 1–8 with the live credentials, a real handset on each target network, and a small prepaid balance. Before inviting users, run `fundbridge-messaging prune-events` on a schedule (for example daily, `--days 30`).

## Behaviour reference

- **USSD is synchronous and stateless.** Each step is rebuilt from the cumulative `text`, PINs live in the database, and no AI or external call happens on the request path. It works with any number of threads and stays well inside the response window.
- **Every screen fits the handset.** Screens are GSM 7-bit and at most 182 characters. Outbound SMS are GSM 7-bit and at most two segments (306 characters).
- **Payout privacy and PINs.** Payout status needs a verified profile and a PIN; payout details are never sent by SMS. PINs are 4 digits; weak PINs are refused; three failures lock for 30 minutes; the lock is safe under concurrency; an admin can reset a PIN (audited).
- **Duplicate callbacks.** These are recorded in `provider_webhook_event` (provider `africastalking`): the inbound-SMS `id`, an HMAC of each USSD PIN step (never the PIN), and the delivery-report ID and status. `prune-events` removes old rows.
- **Gateway failures.** A failure is logged and never raised. Notifications are sent after the database commit, so a failure cannot undo a donation or payout.
