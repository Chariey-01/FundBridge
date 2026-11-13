import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";
import { EnvironmentProvider } from "../src/session/EnvironmentContext.tsx";
import { SessionProvider } from "../src/session/SessionContext.tsx";

export type Reply = { status?: number; body?: unknown } | ((req: { url: URL; init: RequestInit }) => { status?: number; body?: unknown });

export const PUBLIC_CONFIG = { payments: { paypal: { mode: "sandbox" } }, payouts: { provider: "simulator", mode: "simulator" }, feature_phone: { sms: false, ussd: false } };
export const INTEGRATIONS = {
  ai: { provider: "none", model: null, mode: "fallback_only", features: {}, supported_languages: {}, model_verified: false, last_success_at: null, last_error: null },
  messaging: { sms: { provider: "simulator", mode: "simulated", delivery_confirmed: false }, ussd: { service_code: "*384*123#", callback_configured: true, live_shortcode_verified: false }, simulator_enabled: true, notifications_enabled: true, sms_assistant: "rule_based" },
};

/** A fake backend: "METHOD /path" → reply. Unrouted calls fail the test loudly. */
export function fakeBackend(routes: Record<string, Reply>) {
  const calls: { method: string; path: string; headers: Record<string, string>; body: unknown }[] = [];
  const all: Record<string, Reply> = {
    "GET /api/v1/public/config": { body: { data: PUBLIC_CONFIG, meta: {} } },
    "GET /api/v1/integrations/status": { body: { data: INTEGRATIONS, meta: {} } },
    ...routes,
  };
  const fetchImpl = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input));
    const method = (init.method ?? "GET").toUpperCase();
    const key = `${method} ${url.pathname}`;
    calls.push({ method, path: url.pathname + url.search, headers: { ...(init.headers as Record<string, string>) }, body: init.body ? JSON.parse(String(init.body)) : undefined });
    const route = all[key];
    if (!route) throw new Error(`Unexpected request ${key}`);
    const r = typeof route === "function" ? route({ url, init }) : route;
    return new Response(r.body === undefined ? "" : JSON.stringify(r.body), { status: r.status ?? 200, headers: { "Content-Type": "application/json", "X-Request-ID": "req-test-1" } });
  });
  return { fetchImpl: fetchImpl as unknown as typeof fetch, calls };
}

export const ok = (data: unknown, meta: unknown = {}) => ({ body: { data, meta } });
export const fail = (status: number, code: string, details: Record<string, unknown> = {}) => ({ status, body: { error: { code, message: code, details } } });

export function signedIn(role: string, id = "u-1") {
  // exp far in the future so the expiry timer does not fire during a test
  const payload = btoa(JSON.stringify({ sub: id, exp: Math.floor(Date.now() / 1000) + 900 })).replace(/=+$/, "");
  window.sessionStorage.setItem("fundbridge.session", JSON.stringify({
    token: `h.${payload}.s`, user: { id, role, email: `${role}@example.test`, phone_number: null }, expiresAt: Date.now() + 900_000,
  }));
}

export function renderApp(ui: ReactElement, { route = "/", path = "*", fetchImpl }: { route?: string; path?: string; fetchImpl: typeof fetch }) {
  return render(
    <MemoryRouter initialEntries={[route]}>
      <SessionProvider fetchImpl={fetchImpl} baseUrl="http://api.test">
        <EnvironmentProvider>
          <Routes>
            <Route path={path} element={ui} />
            <Route path="/signin" element={<p>Sign-in page</p>} />
          </Routes>
        </EnvironmentProvider>
      </SessionProvider>
    </MemoryRouter>,
  );
}
