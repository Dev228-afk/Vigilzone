import { api } from "./api";

export async function getUserTenants() {
  const { data } = await api.get("/tenants/"); // adjust endpoint
  return data; // should be an array
}
