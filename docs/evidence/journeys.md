# FundBridge journey evidence (generated)

Generated 2026-11-12 05:00 UTC by `backend/tests/e2e/test_product_journeys.py` against a live gunicorn server.

**Real:** the FundBridge API, database, auth, ledger, USSD/SMS callback handling and AI service.
**Local doubles:** PayPal (Orders v2, webhook verification) and OpenAI. SMS goes to the labelled simulated outbox. This transcript does not prove any live provider integration.

Tokens, e-mail addresses and full phone numbers are not recorded.

### Creator: register, get the creator role, AI draft, edit, create, submit

- Creator, agent, reviewer and beneficiary accounts: each registered through `POST /api/v1/auth/register` (always a donor), then given its role by the admin through `PUT /api/v1/admin/users/{id}/role`
- Agent onboards the beneficiary: `POST /api/v1/beneficiaries` -> **201** {"verification_status": "unverified"}
- Reviewer verifies the beneficiary profile (revision-checked): verified
- AI campaign draft (phone number redacted before the model call): `POST /api/v1/ai/campaign-draft` -> **200** {"title": "Help Amina finish secondary school", "requires_human_review": true} meta={"ai_generated": true, "degraded": false, "provider": "openai"}
- Creator saves the edited draft as a campaign: `POST /api/v1/campaigns` -> **201** {"status": "draft", "review_status": "not_submitted"}
- Creator submits for review: `POST /api/v1/campaigns/d54dff25-3964-4fef-88d0-3c2f3b1368cd/submit` -> **200** {"status": "submitted", "review_status": "pending"}

### Reviewer: paginated queue, inspect, reject, resubmission, approve, audit trail

- A donor cannot open the review queue: `GET /api/v1/campaigns/review-queue` -> **403** {"code": "FORBIDDEN"}
- Review queue page 1: `GET /api/v1/campaigns/review-queue?page=1&page_size=5` -> **200** 2 item(s) meta={"page": 1, "total": 2}
- Reviewer inspects the campaign: `GET /api/v1/campaigns/d54dff25-3964-4fef-88d0-3c2f3b1368cd` -> **200** {"status": "submitted", "beneficiary_id": "be0192fd-67ae-46ef-8d46-875725324d97"}
- Reviewer rejects: `POST /api/v1/campaigns/d54dff25-3964-4fef-88d0-3c2f3b1368cd/review` -> **200** {"status": "draft", "review_status": "rejected"}
- Creator edits and resubmits: `POST /api/v1/campaigns/d54dff25-3964-4fef-88d0-3c2f3b1368cd/submit` -> **200** {"status": "submitted"}
- Reviewer approves: `POST /api/v1/campaigns/d54dff25-3964-4fef-88d0-3c2f3b1368cd/review` -> **200** {"status": "published", "review_status": "approved"}
- Audit trail for the campaign (from `audit_log`): campaign.created, campaign.submitted, campaign.review_reject, campaign.submitted, campaign.review_approve

### Donor: AI discovery, read the story, PayPal order, approve, capture, signed webhook replay, history

- AI campaign search: `POST /api/v1/ai/campaign-search` -> **200** {"filters_relaxed": false} meta={"ai_generated": true, "degraded": false, "provider": "openai"}
- Donor reads the public campaign: `GET /api/v1/campaigns/d54dff25-3964-4fef-88d0-3c2f3b1368cd` -> **200** {"status": "published", "raised": {"amount": "0.00", "currency": "USD"}}
- Donation order (PayPal Orders v2 double): `POST /api/v1/donations/orders` -> **201** {"status": "pending"}
- AI explains the pending donation: `POST /api/v1/ai/status-explanation` -> **200** {"status": "pending", "confirmed": false} meta={"ai_generated": true, "degraded": false, "output_replaced_by_guardrail": false, "provider": "openai"}
- Donor approves the order at the PayPal double
- Server-side capture: `POST /api/v1/donations/88134e17-e37b-4caf-a3da-3ec42955558e/capture` -> **200** {"status": "completed"}
- Signed webhook for the same capture: `POST /api/v1/webhooks/paypal` -> **204** ''
- Same webhook event delivered again: `POST /api/v1/webhooks/paypal` -> **204** ''
- Signed webhook naming a different capture for the completed order (refused): `POST /api/v1/webhooks/paypal` -> **400** {"code": "PAYMENT_CAPTURE_MISMATCH"}
- Ledger-backed campaign total after capture and two webhook deliveries: 45.00 USD (one credit)
- Donation history: `GET /api/v1/me/donations` -> **200** 1 item(s): [{"status": "completed", "amount": "45.00"}]
- AI explains the confirmed donation: `POST /api/v1/ai/status-explanation` -> **200** {"status": "completed", "confirmed": true, "campaign_raised": {"amount": "45.00", "currency": "USD"}} meta={"ai_generated": true, "degraded": false, "output_replaced_by_guardrail": false, "provider": "openai"}

### Beneficiary: own campaigns, USSD (Africa's Talking callback format), PIN, payout, SMS, status

- Beneficiary lists own campaigns: `GET /api/v1/beneficiaries/me/campaigns` -> **200** 1 item(s): [{"status": "published", "raised": {"amount": "45.00", "currency": "USD"}}] meta={"page": 1, "total": 1}
- USSD callback without the shared secret: `POST /api/v1/messaging/ussd` -> **403** {"code": "INVALID_CALLBACK"}
- USSD dial (Kiswahili profile): `POST /api/v1/messaging/ussd?token=[REDACTED]` -> **200** 'CON FundBridge\n1. Kampeni yangu\n2. Hali ya malipo\n3. Tafuta kampeni\n4. Jinsi ya kuchangia\n5. Msaada\n6. Language/Lugha'
- USSD 1: campaign status: `POST /api/v1/messaging/ussd?token=[REDACTED]` -> **200** 'END Tailor5c7ed: sewing machines for Neema\nHali: Iko hewani\nImechangiwa: USD 45.00 kati ya USD 600.00'
- USSD 2: create PIN: `POST /api/v1/messaging/ussd?token=[REDACTED]` -> **200** 'CON Unda PIN ya tarakimu 4 kulinda taarifa za malipo yako:'
- USSD 2: PIN entered twice: `POST /api/v1/messaging/ussd?token=[REDACTED]` -> **200** 'END Bado hakuna ombi la malipo.'
- Beneficiary requests a payout: `POST /api/v1/payouts` -> **201** {"status": "requested", "amount": "30.00"}
- Reviewer approves the payout: `POST /api/v1/payouts/66dec948-1586-4657-bc29-fdc952db0687/review` -> **200** {"status": "approved_for_submission"}
- USSD 2: payout status behind the PIN: `POST /api/v1/messaging/ussd?token=[REDACTED]` -> **200** 'END Malipo USD 30.00\nHali: Yameidhinishwa, yanaandaliwa\nYamesasishwa: 12 Nov 2026'
- Simulated SMS outbox (labelled simulated): `GET /api/v1/messaging/simulator/outbox?phone_number=+254******432` -> **200** 2 item(s) meta={"simulated": true}
- 2 simulated SMS for this number, including the confirmed donation (45.00) and the payout approval (Kiswahili 'Yameidhinishwa'); none says the payout was paid
- AI explains the payout: `POST /api/v1/ai/status-explanation` -> **200** {"status": "approved_for_submission", "confirmed": false, "status_label": "Yameidhinishwa, yanaandaliwa"} meta={"ai_generated": true, "degraded": false, "output_replaced_by_guardrail": false, "provider": "openai"}
- SMS delivery report for an unknown id: `POST /api/v1/messaging/sms/delivery?token=[REDACTED]` -> **200** ''

### Administrator and unauthorised access

- Admin finds an account: `GET /api/v1/admin/users?email=[EMAIL]` -> **200** 1 item(s)
- donor cannot use user management: `PUT /api/v1/admin/users/2fbad922-d05b-480c-804a-91f8e6a6702c/role` -> **403** {"code": "FORBIDDEN"}
- reviewer cannot use user management: `PUT /api/v1/admin/users/2fbad922-d05b-480c-804a-91f8e6a6702c/role` -> **403** {"code": "FORBIDDEN"}
- beneficiary cannot use user management: `PUT /api/v1/admin/users/2fbad922-d05b-480c-804a-91f8e6a6702c/role` -> **403** {"code": "FORBIDDEN"}
- Another beneficiary cannot read this payout: `GET /api/v1/payouts/66dec948-1586-4657-bc29-fdc952db0687` -> **403** {"code": "FORBIDDEN"}
- Another donor cannot read this donation: `GET /api/v1/donations/88134e17-e37b-4caf-a3da-3ec42955558e` -> **403** {"code": "FORBIDDEN"}
- The beneficiary cannot approve their own payout: `POST /api/v1/payouts/66dec948-1586-4657-bc29-fdc952db0687/review` -> **403** {"code": "FORBIDDEN"}
- Invalid token: `GET /api/v1/auth/me` -> **401** {"code": "INVALID_TOKEN"}
