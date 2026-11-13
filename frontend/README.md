# FundBridge web frontend

React 18, Vite 6 and TypeScript. The app talks to the Flask API only through the typed client in
[`../contracts/fundbridge-client.ts`](../contracts/fundbridge-client.ts). The backend's live tests exercise
that same client, so the UI and the API share one contract.

## Run it

```bash
cd frontend
npm ci
cp .env.example .env.local      # optional; defaults are fine for local work
npm run dev                     # http://localhost:5173, proxies /api to FUNDBRIDGE_BACKEND_URL (default http://127.0.0.1:5000)
```

Start the backend separately (see the repository README and `docs/DEPLOYMENT.md`). In development and
preview, the browser stays same-origin because Vite proxies `/api`, so no CORS setup is needed. To serve the
built site from another origin, set `VITE_API_BASE_URL` at build time and list that site in the backend's
`FRONTEND_ORIGIN`.

| Command | What it does |
|---|---|
| `npm run typecheck` | `tsc -b` over the app, the unit tests, the e2e specs and the imported contracts |
| `npm run lint` | ESLint with zero warnings allowed |
| `npm test` | Vitest and Testing Library unit and component tests (jsdom) |
| `npm run build` | Type-checks, then builds `dist/` for production |
| `npm run e2e` | Playwright browser journeys against the real API (see below) |

## Who can do what

| Role | Screens |
|---|---|
| Visitor | Home, browse and search, campaign page (ledger-backed amount raised), environment page |
| Donor (any signed-in account) | Donate through PayPal, return and confirmation page, donation status, My donations |
| Creator | My campaigns, new campaign (needs a beneficiary reference from an agent), edit draft, submit for review |
| Beneficiary | Verification status, own campaigns with available, reserved and paid-out amounts, payout requests, profile edits (a phone or destination change triggers re-verification) |
| Agent | Onboard a beneficiary and share the reference with the creator |
| Reviewer | Review desk: campaign queue, beneficiary verification (stale reviews are refused), payout approval |
| Admin | Everything a reviewer and an agent can do, plus People (role assignment) |

The server enforces every rule again. Role checks in the UI only decide what is shown.

## Rules the UI follows

- **A donation is a success only when the server says `completed`.** Creating a PayPal order is shown as
  "set up, not paid yet". On return from PayPal the server captures the payment; if the capture is
  ambiguous it reconciles with PayPal, and then the donation is re-read. PayPal's query parameters are never
  treated as proof.
- **A payout is paid only when its status is `succeeded`.** Every other status is shown as pending. With the
  simulator provider, each payout carries a "Simulated payout" tag and the text "No money has been sent".
- **Every channel that is not live is labelled.** The strip under the header and `/system` read
  `GET /public/config` and `GET /integrations/status`.
  - PayPal `sandbox` is shown as "PayPal test mode, no real money". The server does not yet say whether
    that means PayPal's own Sandbox or a local stand-in (release audit AUD-11), so the UI does not claim
    either. The UI already understands the proposed values `local_standin` and `live`.
  - SMS is labelled simulated or sandbox; even live SMS is never described as delivered.
- **Money stays a decimal string.** Comparisons and progress bars use BigInt cents, and formatting is
  done on the string.
- **One idempotency key per intent.** A retry of the same donation or payout (same campaign and amount)
  reuses its key, so it cannot create a second one.
- **Sessions:** tokens last 15 minutes and there is no refresh endpoint. When a token expires, or the
  server reports `TOKEN_EXPIRED`, `INVALID_TOKEN` or `ACCOUNT_INACTIVE`, the person is signed out with an
  explanation. "Sign out" only forgets the token in this browser, because the server has no logout.

## Security notes

- React escapes all rendered text. The app has no `dangerouslySetInnerHTML`, `innerHTML` or `eval`.
- Links that leave the site, such as PayPal checkout, must be `https:` URLs (`src/lib/urls.ts`). Any other
  value from the server, such as `javascript:`, is never rendered as a link.
- The destination after sign-in must be a same-site path. Paths containing `//`, backslashes or control
  characters are refused (`src/lib/roleHome.ts`).
- The access token is kept in `sessionStorage`, so it is gone when the tab closes, and expires after 15
  minutes. The hosting platform should send a Content-Security-Policy header; none is configured here.
- `npm audit --omit=dev` reports no runtime vulnerabilities. One moderate advisory remains in the
  development toolchain: `minimatch`, used by typescript-eslint, which has no fixed release yet. It
  affects only the linter's handling of untrusted glob patterns.

## Continuous integration

`.github/workflows/frontend.yml` has two jobs:

1. **checks:** typecheck, lint, unit tests, production build, and a runtime dependency audit.
2. **browser:** the browser journeys below, against PostgreSQL 16.

## Browser journeys (`npm run e2e`)

`e2e/live_stack.py` starts the real API the way an operator would:

1. Alembic migrations.
2. The first-admin CLI.
3. gunicorn with `FLASK_ENV=production`.

Every other account and record is created through the HTTP API by the tests. PayPal is the repository's
local Orders v2 test double (`backend/tests/e2e/provider_doubles.py`). It is **not PayPal**: no PayPal
system is contacted and no money moves. The tests stand in for the donor's click on PayPal's page by
calling the double's test-only approve endpoint, then send the browser back to the app's return URL.
Payouts use the backend's simulator.

```bash
# a Python environment with backend/requirements-deploy.txt installed
export E2E_PYTHON=/path/to/venv/bin/python
# optional: a DISPOSABLE PostgreSQL database; its public schema is dropped and recreated
export E2E_DATABASE_URL=postgresql+psycopg://user@127.0.0.1:5432/fundbridge_e2e
npx playwright install chromium   # once
npm run e2e
```

Each journey runs twice: on desktop (1366×860) and on mobile (Pixel 7). The specs also check that no page
scrolls horizontally.
