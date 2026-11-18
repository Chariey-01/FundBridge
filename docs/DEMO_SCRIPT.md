# FundBridge demonstration script (about 7 minutes)

For the presenter. It follows one story: a donor abroad funds Amina's school fees, a reviewer keeps it honest, and a beneficiary **without a smartphone** follows the money by USSD in Kiswahili. Read the disclosures aloud; the judges should hear what is simulated from us.

## Before the judges arrive (10 minutes)

1. Deploy (see [`RUNBOOK.md`](RUNBOOK.md)), run `fundbridge-demo seed --scenarios`, and keep the printed campaign IDs.
2. Run the smoke test: everything is PASS or an expected SKIP. Know which providers are SKIP.
3. Open these tabs:
   - the web app (Cursor's frontend), or an API client if the frontend is not ready;
   - the phone simulator at `/api/v1/messaging/simulator`;
   - `/api/v1/integrations/status`.
4. Sign in as the donor, creator, reviewer and beneficiary in separate browser profiles.

## 1. The problem (30 s)

"Families in rural Kenya often have a feature phone, no bank card and no smartphone data. Donors abroad want proof their money arrived. FundBridge connects the two, and it never claims money moved until the system of record says so."

## 2. Donor finds and funds a campaign (2 min)

1. **Search in plain language:** "help a girl finish secondary school in Kenya". The AI only turns the request into filters; the results always come from the database.
   - Disclose if no OpenAI key is set: *"AI is in fallback mode; you are seeing keyword search."*
2. **Campaign page:** "Raised" comes from the ledger (`/campaigns/{id}/funds`), not from a counter the browser keeps.
3. **Donate USD 10 with PayPal.**
   - **With PayPal sandbox configured:** approve with the sandbox buyer. The return page says *"Donation confirmed"* only after the server re-reads the donation, and "Raised" goes up by 10.
     - Disclose: *"This is PayPal's sandbox; no real money moves."*
   - **Without PayPal credentials:** the API answers "payment provider unconfigured", and the UI must say so. Show the seeded donation history instead.
     - Disclose: *"These donations are seeded demo records labelled `demo_seed`, not payments."*
   - Talking point: a timeout between PayPal and us is reconciled from PayPal's own record, and is never counted twice.

## 3. Creator drafts with AI (1 min)

1. **Draft from rough notes:** paste notes that include a phone number. The draft comes back with a warning that personal details were removed before anything was sent to the AI. It is a suggestion: edit it, then submit for review.
   - Disclose if no key is set: *"AI unavailable, so this is the template fallback."*
2. **No AI authority:** the AI cannot publish, approve, verify anyone or move money. It has no access to those functions.

## 4. Reviewer keeps it honest (1 min)

1. **Approve the submitted campaign** (`demo-water-tank`). A reviewer cannot approve their own campaign.
2. **Verify beneficiaries:**
   - show the verified profiles;
   - if a beneficiary changes their phone number, they drop back to "reverification required", and the phone channel stops answering the new number until someone re-verifies it.
3. **Approve Baraka's payout request (USD 30).** The status becomes **"Approved, being prepared"**, never "paid".
   - Disclose: *"Mobile-money payout is simulated. We have no licensed payout provider yet, so the system stops honestly at 'approved'."*

## 5. Beneficiary without a smartphone (2 min)

In the **phone simulator** (it says *simulated* on screen):

1. Number `+254712345679` (Baraka), dial with empty input. The menu is in **Kiswahili**: *"1. Kampeni yangu / 2. Hali ya malipo / …"*.
2. `1` → choose the clinic roof → *"Hali: Iko hewani, Imechangiwa: USD 160.00 kati ya USD 1500.00"*. These are the same ledger numbers the donor sees.
3. `2` → create a 4-digit PIN (*"Unda PIN ya tarakimu 4…"*) → the latest payout: *"Yameidhinishwa, yanaandaliwa"* ("approved, being prepared").
4. **Lockout:** three wrong PINs lock it for 30 minutes. Payout details are never sent by SMS.
5. **Notifications:** the outbox shows the SMS the approval triggered. Send `HALI` by SMS to get the status in one message.
6. **Switch to `+254712345678` (Amina)** for the same journey in English.
7. Disclose: *"This is our simulator. A real USSD code and SMS shortcode need Africa's Talking and telco approval; the integration is built and tested against a local stand-in, not yet against Africa's Talking."*

## 6. Close (30 s)

"Every number you saw came from one ledger, and nothing was marked paid that wasn't. And the person on the other end needed only a basic phone."

## If something fails

- **AI errors:** the app falls back to templates or keyword search. Say so and continue.
- **PayPal unavailable:** use the seeded history (section 2, the no-credentials case).
- **Simulator disabled:** set `MESSAGING_SIMULATOR_ENABLED=true` (demo deployments only).
- **The beneficiary payout form cannot find a campaign:** the backend must be `967781d` or later (`GET /beneficiaries/me/campaigns`). On an older deployment, use the campaign ID printed by the seed.
