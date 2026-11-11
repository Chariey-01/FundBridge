# FundBridge backend API contract (implementation draft)

Base path: `/api/v1`. Responses use `{ "data": ..., "meta": {} }`; failures use the shared `{ "error": { "code", "message", "details" } }` envelope. Resource IDs are UUIDs and money is a decimal string plus uppercase ISO-4217 `currency`.

Implemented endpoints: `GET /health`, `GET /api/v1/public/config`, auth register/login/me, campaign browse/detail/create/update/submit, assisted beneficiary onboarding, donation order creation/server-side capture, PayPal webhook, payout request, and payout review.

`POST /donations/orders` and `POST /payouts` require `Idempotency-Key`. Payment completion occurs only through a verified PayPal webhook. Payout simulator submission, when later enabled, must remain `submitted`/`pending_confirmation`; it must never claim `succeeded`.

Not yet implemented: logout, campaign review/publish, beneficiary self-service, donation retrieval/capture/history, payout retrieval/submission/callback reconciliation, AI and SMS/USSD endpoints. These require the final approved contract and provider choices.
