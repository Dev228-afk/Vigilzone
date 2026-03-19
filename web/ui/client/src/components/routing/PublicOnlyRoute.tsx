import { Route, Redirect } from "wouter";
import { useAuth } from "@/auth/AuthProvider";

/**
 * PublicOnlyRoute
 *
 * Used for /login, /register, /forgot-password.
 * Must wait for auth context resolution to avoid redirect races.
 */
export default function PublicOnlyRoute({ path, component: Component }: any) {
  return (
    <Route
      path={path}
      component={(props: any) => {
        const { isLoading, isAuthenticated, tenantId } = useAuth();

        if (isLoading) {
          // While loading, don't bounce between pages.
          return <div className="p-6">Loading…</div>;
        }

        if (!isAuthenticated) return <Component {...props} />;

        // If authenticated but no tenant yet, they must choose/create one.
        return tenantId ? <Redirect to="/dashboard" /> : <Redirect to="/select-community" />;
      }}
    />
  );
}
