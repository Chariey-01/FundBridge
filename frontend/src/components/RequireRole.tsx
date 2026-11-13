import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import type { Role } from "../api/client.ts";
import { useSession } from "../session/SessionContext.tsx";
import { Empty } from "./ui.tsx";

/** Hides screens from the wrong roles. The server enforces every rule again; this is only navigation. */
export function RequireRole({ roles, children }: { roles?: Role[]; children: ReactNode }) {
  const { user } = useSession();
  const location = useLocation();
  if (!user) return <Navigate to={`/signin?next=${encodeURIComponent(location.pathname + location.search)}`} replace />;
  if (roles && !roles.includes(user.role))
    return (
      <div className="container section">
        <Empty title="This area is for other roles">
          <p>Your account is signed in as <strong>{user.role}</strong>. An administrator assigns roles.</p>
        </Empty>
      </div>
    );
  return <>{children}</>;
}
