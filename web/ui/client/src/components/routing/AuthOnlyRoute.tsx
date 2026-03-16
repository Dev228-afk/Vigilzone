import { Redirect } from "wouter";
import { useAuth } from "@/auth/AuthProvider";

/**
 * AuthOnlyRoute
 *
 * Allows access only when authenticated (tenant not required).
 * Used for /select-community.
 */
export default function AuthOnlyRoute({ children }: { children: React.ReactNode }) {
  const { isLoading, isAuthenticated } = useAuth();

  if (isLoading) return <div className="p-6">Loading…</div>;
  if (!isAuthenticated) return <Redirect to="/login" />;
  return <>{children}</>;
}
