import { defineConfig, devices } from "@playwright/test";

/**
 * Browser journeys against the REAL FundBridge API (gunicorn, migrations, first-admin CLI) and a
 * PRODUCTION build of the frontend served by `vite preview`. PayPal is the repository's local test
 * double; see e2e/live_stack.py. Set E2E_DATABASE_URL to a disposable PostgreSQL database
 * (its public schema is dropped) and E2E_PYTHON to an interpreter with backend/requirements-deploy.txt.
 */
export const API_PORT = Number(process.env.E2E_API_PORT ?? 5051);
export const PAYPAL_PORT = Number(process.env.E2E_PAYPAL_PORT ?? 58301);
const WEB_PORT = 4173;
const python = process.env.E2E_PYTHON ?? "python3";

export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 2,
  retries: 0,
  forbidOnly: !!process.env.CI,
  reporter: [["list"], ["html", { open: "never" }]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "desktop", use: { ...devices["Desktop Chrome"], viewport: { width: 1366, height: 860 } } },
    { name: "mobile", use: { ...devices["Pixel 7"] } },
  ],
  webServer: [
    {
      command: `${python} e2e/live_stack.py`,
      url: `http://127.0.0.1:${API_PORT}/health`,
      timeout: 180_000,
      reuseExistingServer: false,
      stdout: "pipe",
      env: { E2E_API_PORT: String(API_PORT), E2E_PAYPAL_PORT: String(PAYPAL_PORT) },
    },
    {
      command: `npx vite build && npx vite preview --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      timeout: 180_000,
      reuseExistingServer: false,
      env: { FUNDBRIDGE_BACKEND_URL: `http://127.0.0.1:${API_PORT}` },
    },
  ],
});
