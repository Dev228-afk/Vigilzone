import { Route, Redirect } from "wouter";
import { useAuth } from "@/auth/AuthProvider";
import type { TenantRole } from "@/lib/rbac";

export default function RoleRoute({ path, component: Component, minRole }: { path: string; component: any; minRole: TenantRole }) {
  return (
    <Route
      path={path}
      component={(props: any) => {
        const { isLoading, isAuthenticated, tenantId, atLeast } = useAuth();
        if (isLoading) return null;
        if (!isAuthenticated) return <Redirect to="/login" />;
        if (!tenantId) return <Redirect to="/select-community" />;
        return atLeast(minRole) ? <Component {...props} /> : <Redirect to="/dashboard" />;
      }}
    />
  );
}