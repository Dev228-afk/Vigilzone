import React, { createContext, useContext, useMemo, useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { api } from "@/lib/api";
import { queryClient } from "@/lib/queryClient"; // adjust path
import { logout as logoutFn } from "@/lib/auth";
import { getSelectedTenantId, setSelectedTenantId } from "@/lib/tenant";
import { roleAtLeast, type TenantRole } from "@/lib/rbac";

type AuthContextResponse = {
  user: { id: number | string; username: string };
  tenant: { id: number | string; name: string } | null;
  role: TenantRole | null;
};

async function fetchAuthContext(): Promise<AuthContextResponse> {
  const { data } = await api.get("/auth/context/"); // implement on backend
  return data;
}

function hasToken() {
  return !!localStorage.getItem("accessToken") || !!sessionStorage.getItem("accessToken");
}

type AuthValue = {
  user: AuthContextResponse["user"] | null;
  tenant: AuthContextResponse["tenant"];
  tenantId: string | null;
  role: TenantRole | null;

  isLoading: boolean;
  isAuthenticated: boolean;

  setTenantId: (id: string | null) => void;
  atLeast: (min: TenantRole) => boolean;

  logout: () => void;
  refetch: () => void;
};

const AuthContext = createContext<AuthValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [, setLocation] = useLocation();
  const tenantId = getSelectedTenantId();
  const tokenPresent = hasToken();

  const q = useQuery({
    queryKey: ["authContext", tenantId],
    queryFn: fetchAuthContext,
    enabled: tokenPresent && !!tenantId,
    retry: false,
    staleTime: 30_000,
  });

  const user = q.data?.user ?? null;
  const tenant = q.data?.tenant ?? null;
  const role = q.data?.role ?? null;

  const setTenantId = useCallback((id: string | null) => {
    setSelectedTenantId(id);
    queryClient.invalidateQueries(); // refresh tenant-scoped data
  }, []);

  const atLeast = useCallback((min: TenantRole) => roleAtLeast(role, min), [role]);

  const logout = useCallback(() => {
    logoutFn();
    setSelectedTenantId(null);
    queryClient.clear();
    setLocation("/login");
  }, [setLocation]);

  const value = useMemo<AuthValue>(
    () => ({
      user,
      tenant,
      tenantId,
      role,
      isLoading: q.isLoading,
      isAuthenticated: tokenPresent && !!user,
      setTenantId,
      atLeast,
      logout,
      refetch: () => q.refetch(),
    }),
    [user, tenant, tenantId, role, q.isLoading, tokenPresent, setTenantId, atLeast, logout, q]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}