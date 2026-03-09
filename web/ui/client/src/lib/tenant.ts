import { api } from "@/lib/api";

const KEY = "selectedTenantId";

export function getSelectedTenantId() {
  return localStorage.getItem(KEY);
}

export function setSelectedTenantId(id: string | null) {
  if (id) localStorage.setItem(KEY, id);
  else localStorage.removeItem(KEY);

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