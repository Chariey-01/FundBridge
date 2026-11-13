import { createContext, useContext, useMemo, type ReactNode } from "react";
import type { IntegrationStatus } from "../api/client.ts";
import { environmentModes, type ModeLabel, type PublicConfig } from "../lib/modes.ts";
import { useResource } from "../lib/useResource.ts";
import { useSession } from "./SessionContext.tsx";

interface EnvironmentValue { config: PublicConfig | null; status: IntegrationStatus | null; modes: ModeLabel[]; loading: boolean; failed: boolean }

const EnvironmentContext = createContext<EnvironmentValue | null>(null);

export function EnvironmentProvider({ children }: { children: ReactNode }) {
  const { client } = useSession();
  const config = useResource(() => client.publicConfig() as Promise<PublicConfig>, [client]);
  const status = useResource(() => client.integrationStatus(), [client]);
  const value = useMemo<EnvironmentValue>(() => {
    const cfg = config.data ?? null;
    const st = status.data ?? null;
    return { config: cfg, status: st, modes: environmentModes(cfg, st), loading: config.loading || status.loading, failed: !!config.error };
  }, [config.data, config.loading, config.error, status.data, status.loading]);
  return <EnvironmentContext.Provider value={value}>{children}</EnvironmentContext.Provider>;
}

export function useEnvironment(): EnvironmentValue {
  const value = useContext(EnvironmentContext);
  if (!value) throw new Error("useEnvironment must be used inside EnvironmentProvider");
  return value;
}
