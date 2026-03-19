import { api } from "@/lib/api";

const KEY = "selectedTenantId";

export function getSelectedTenantId() {
  try {
    return localStorage.getItem(KEY) || sessionStorage.getItem(KEY);
  } catch {
    // Some browsers (e.g., private mode) can throw on storage access.
    return null;
  }
}

export function setSelectedTenantId(id: string | null) {
  // Keep both local + session in sync to avoid route guard / axios mismatch.
  try {
    if (id) {
      localStorage.setItem(KEY, id);
      sessionStorage.setItem(KEY, id);
    } else {
      localStorage.removeItem(KEY);
      sessionStorage.removeItem(KEY);
    }
  } catch {
    // ignore storage failures; header will still be set for this session
  }

  if (id) api.defaults.headers.common["X-Tenant-ID"] = id;
  else delete api.defaults.headers.common["X-Tenant-ID"];
}

export type MyTenant = { id: number | string; name: string; role: string };

export async function getMyTenants(): Promise<MyTenant[]> {
  const { data } = await api.get("/tenants/mine/");
  return data;
}

export async function createTenant(name: string) {
  const { data } = await api.post("/tenants/", { name });
  return data;
}