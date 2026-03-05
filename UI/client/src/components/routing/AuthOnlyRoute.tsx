import { Redirect } from "wouter";
import { hasToken } from "@/lib/authGuard";

export default function AuthOnly({ children }: { children: React.ReactNode }) {
  if (!hasToken()) return <Redirect to="/login" />;
  return <>{children}</>;
}