import React, { createContext, useContext, useMemo, useCallback, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { useLocation } from "wouter";
import { api } from "@/lib/api";
import { queryClient } from "@/lib/queryClient"; // adjust path
import { logout as logoutFn } from "@/lib/auth";
import { getSelectedTenantId, setSelectedTenantId } from "@/lib/tenant";
import { roleAtLeast, type TenantRole } from "@/lib/rbac";

// Type for /tenants/mine/ response
type TenantMembership = {
  id: number;
  name: string;
  role: TenantRole;
};

// Full user type from /auth/context/ endpoint
export type AuthUser = {
  id: number;
  username: string;
  email: string;
  is_superuser: boolean;
  is_staff: boolean;
};

// Response type for /auth/context/ endpoint
type AuthContextResponse = {
  user: AuthUser;
  tenant: { id: number; name: string } | null;
  role: TenantRole | null;
};

function hasToken() {
  return !!localStorage.getItem("accessToken") || !!sessionStorage.getItem("accessToken");
}

async function fetchAuthContext(): Promise<AuthContextResponse> {
  const { data } = await api.get("/auth/context/");
  return data;
}

// Also keep fetchMyTenants as fallback
async function fetchMyTenants(): Promise<TenantMembership[]> {
  const { data } = await api.get("/tenants/mine/");
  return data;
}

type AuthValue = {
  user: AuthUser | null;
  tenant: { id: number | string; name: string } | null;
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
  const tokenPresent = hasToken();

  // Fetch auth context (user + tenant + role)
  const { data: authContext, isLoading: isLoadingContext } = useQuery({
    queryKey: ["authContext"],
    queryFn: fetchAuthContext,
    enabled: tokenPresent,
    retry: false,
    staleTime: 60_000,
  });

  // Fetch user's tenant memberships as fallback
  const { data: memberships } = useQuery({
    queryKey: ["myTenants"],
    queryFn: fetchMyTenants,
    enabled: tokenPresent && !authContext,
    retry: false,
    staleTime: 60_000,
  });

  // Get current tenantId from storage
  const tenantId = getSelectedTenantId();

  // Auto-select tenant if user has only one (from memberships)
  useEffect(() => {
    if (memberships && memberships.length === 1 && !tenantId) {
      setSelectedTenantId(String(memberships[0].id));
    }
  }, [memberships, tenantId]);

  // If a tenantId is stored but the user is no longer a member, clear it.
  // This prevents a broken "stuck on select community" loop after membership changes.
  useEffect(() => {
    if (!tenantId || !memberships) return;
    const ok = memberships.some((m) => String(m.id) === String(tenantId));
    if (!ok) {
      setSelectedTenantId(null);
    }
  }, [tenantId, memberships]);

  // Get user from auth context
  const user = useMemo(() => {
    return authContext?.user ?? null;
  }, [authContext]);

  // Get tenant and role from auth context or fallback to memberships
  const currentTenant = useMemo(() => {
    if (authContext?.tenant) {
      return { id: authContext.tenant.id, name: authContext.tenant.name };
    }
    if (!tenantId || !memberships) return null;
    const membership = memberships.find(m => String(m.id) === String(tenantId));
    return membership ? { id: membership.id, name: membership.name } : null;
  }, [authContext, tenantId, memberships]);

  const role = useMemo(() => {
    if (authContext?.role) {
      return authContext.role;
    }
    if (!tenantId || !memberships) return null;
    const membership = memberships.find(m => String(m.id) === String(tenantId));
    return membership?.role ?? null;
  }, [authContext, tenantId, memberships]);

  // Set tenant from auth context if we have one but no tenantId selected
  useEffect(() => {
    if (authContext?.tenant && !tenantId) {
      setSelectedTenantId(String(authContext.tenant.id));
    }
  }, [authContext, tenantId]);

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
      tenant: currentTenant,
      tenantId: tenantId || (authContext?.tenant ? String(authContext.tenant.id) : null),
      role,
      isLoading: isLoadingContext,
      isAuthenticated: tokenPresent && !!authContext,
      setTenantId,
      atLeast,
      logout,
      refetch: () => queryClient.invalidateQueries({ queryKey: ["authContext"] }),
    }),
    [user, currentTenant, tenantId, authContext, role, isLoadingContext, tokenPresent, setTenantId, atLeast, logout]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
