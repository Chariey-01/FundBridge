import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, FundBridgeClient, apiBaseUrl, type Role } from "../api/client.ts";
import { readJson, remove, writeJson } from "../lib/storage.ts";
import { tokenExpiry } from "./jwt.ts";

export interface SessionUser { id: string; role: Role; email: string | null; phone_number: string | null }
interface StoredSession { token: string; user: SessionUser; expiresAt: number | null }

interface SessionValue {
  client: FundBridgeClient;
  user: SessionUser | null;
  expiresAt: number | null;
  notice: string | null;
  signIn: (email: string, password: string) => Promise<SessionUser>;
  signOut: (notice?: string) => void;
  clearNotice: () => void;
}

const KEY = "fundbridge.session";
const SessionContext = createContext<SessionValue | null>(null);

function loadStored(): StoredSession | null {
  const s = readJson<StoredSession>(KEY);
  if (!s?.token || !s.user) return null;
  if (s.expiresAt && s.expiresAt <= Date.now()) { remove(KEY); return null; }
  return s;
}

/** `fetchImpl` and `baseUrl` exist for tests; the app uses the browser fetch and apiBaseUrl(). */
export function SessionProvider({ children, fetchImpl, baseUrl }: { children: ReactNode; fetchImpl?: typeof fetch; baseUrl?: string }) {
  const [session, setSession] = useState<StoredSession | null>(loadStored);
  const [notice, setNotice] = useState<string | null>(null);
  const invalidate = useRef<(e: ApiError) => void>(() => undefined);

  const client = useMemo(
    () => new FundBridgeClient({
      baseUrl: baseUrl ?? apiBaseUrl(),
      // Bound so the browser's fetch is never called with the client as `this`.
      fetch: fetchImpl ?? ((input, init) => globalThis.fetch(input, init)),
      onSessionInvalid: (e) => invalidate.current(e),
    }),
    [fetchImpl, baseUrl],
  );
  client.token = session?.token ?? null;

  const signOut = useCallback((message?: string) => {
    remove(KEY);
    client.token = null;
    setSession(null);
    setNotice(message ?? null);
  }, [client]);

  invalidate.current = (e: ApiError) =>
    signOut(e.code === "ACCOUNT_INACTIVE" ? "This account is no longer active." : "Your session ended. Please sign in again.");

  // Tokens last 15 minutes and there is no refresh endpoint: sign out when the token expires.
  useEffect(() => {
    if (!session?.expiresAt) return;
    const ms = session.expiresAt - Date.now();
    const timer = window.setTimeout(() => signOut("Your session expired after 15 minutes. Please sign in again."), Math.max(0, ms));
    return () => window.clearTimeout(timer);
  }, [session, signOut]);

  const signIn = useCallback(async (email: string, password: string) => {
    const result = await client.login(email, password);
    const me = await client.me();
    const stored: StoredSession = {
      token: result.access_token,
      user: { id: me.id, role: me.role, email: me.email, phone_number: me.phone_number },
      expiresAt: tokenExpiry(result.access_token),
    };
    writeJson(KEY, stored);
    setSession(stored);
    setNotice(null);
    return stored.user;
  }, [client]);

  const value = useMemo<SessionValue>(() => ({
    client,
    user: session?.user ?? null,
    expiresAt: session?.expiresAt ?? null,
    notice,
    signIn,
    signOut,
    clearNotice: () => setNotice(null),
  }), [client, session, notice, signIn, signOut]);

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionValue {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside SessionProvider");
  return value;
}

export function hasRole(user: SessionUser | null, ...roles: Role[]): boolean {
  return !!user && roles.includes(user.role);
}
