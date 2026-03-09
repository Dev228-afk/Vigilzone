import { Route, Redirect } from "wouter";
import { hasToken, getTenantId } from "@/lib/authGuard";

export default function PublicOnlyRoute({ path, component: Component }: any) {
  return (
    <Route
      path={path}
      component={(props: any) => {
        if (!hasToken()) return <Component {...props} />;

        return getTenantId()
          ? <Redirect to="/dashboard" />
          : <Redirect to="/select-community" />;
      }}
    />
  );
}