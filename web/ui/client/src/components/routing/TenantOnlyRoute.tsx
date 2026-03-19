import { Redirect } from "wouter";
import { useAuth } from "@/auth/AuthProvider";

/**
 * TenantOnlyRoute
 *
 * Critical demo-stability guard:
 * - NEVER redirect based on localStorage synchronously.
 * - Always wait for AuthProvider (/api/auth/context/) to resolve.
 *
 * Otherwise we create a race condition where the user has a valid membership,
 * but we redirect to /select-community before the tenant is selected.
 */
export default function TenantOnlyRoute({ children }: { children: React.ReactNode }) {
  const { isLoading, isAuthenticated, tenantId } = useAuth();

  if (isLoading) {
    return <div className="p-6">Loading…</div>;
  }

  if (!isAuthenticated) return <Redirect to="/login" />;
  if (!tenantId) return <Redirect to="/select-community" />;

  return <>{children}</>;
}
