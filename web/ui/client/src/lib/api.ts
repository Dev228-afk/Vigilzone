import axios, { type AxiosRequestHeaders } from "axios";
import { getSelectedTenantId } from "@/lib/tenant"; // add

// ── Django REST API (behind Nginx at /api) ───────────────────
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export const api = axios.create({
  baseURL: API_BASE,
});

let accessToken: string | null = localStorage.getItem("accessToken");

export function setAccessToken(t: string | null) {
  accessToken = t;
  if (t) localStorage.setItem("accessToken", t);
  else localStorage.removeItem("accessToken");
}


// Endpoints that must never carry a stale Bearer token
const PUBLIC_PATHS = ["/auth/token/", "/auth/refresh/", "/auth/register/"];

// request: add headers
api.interceptors.request.use((config) => {
  const headers = (config.headers ?? {}) as AxiosRequestHeaders;
  const selectedTenant = getSelectedTenantId();

  const isPublic = PUBLIC_PATHS.some((p) => config.url?.includes(p));

  if (selectedTenant) headers["X-Tenant-ID"] = selectedTenant;
  if (accessToken && !isPublic) headers.Authorization = `Bearer ${accessToken}`;
  config.headers = headers;
  return config;
});

// response: refresh once on 401
api.interceptors.response.use(
  (r) => r,
  async (err) => {
    const original = err.config;

    if (err.response?.status === 401 && original && !original._retry) {
      original._retry = true;
      try {
        const rt = localStorage.getItem("refreshToken");
        if (!rt) throw new Error("no refresh");

        const { data } = await axios.post(`${API_BASE}/auth/refresh/`, { refresh: rt });

        setAccessToken(data.access);
        return api(original);
      } catch {
        setAccessToken(null);
      }
    }

    throw err;
  }
);