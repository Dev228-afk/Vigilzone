import { Redirect } from "wouter";
import { hasToken, getTenantId } from "@/lib/authGuard";

export default function TenantRoute({ children }: { children: React.ReactNode }) {
  if (!hasToken()) return <Redirect to="/login" />;
  if (!getTenantId()) return <Redirect to="/select-community" />;
  return <>{children}</>;
}