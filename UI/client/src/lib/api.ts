import axios, { type AxiosRequestHeaders } from "axios";
import { getSelectedTenantId } from "@/lib/tenant"; // add

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api";

export const api = axios.create({
  baseURL: API_BASE,
  // withCredentials: true, // only if you use cookie auth; likely false for JWT
});

let accessToken: string | null = localStorage.getItem("accessToken");

export function setAccessToken(t: string | null) {
  accessToken = t;
  if (t) localStorage.setItem("accessToken", t);
  else localStorage.removeItem("accessToken");
}


// request: add headers
api.interceptors.request.use((config) => {
  const headers = (config.headers ?? {}) as AxiosRequestHeaders;
  const selectedTenant = getSelectedTenantId();
  console.log("INTERCEPT", localStorage.getItem("selectedTenantId"));

  if (selectedTenant) headers["X-Tenant-ID"] = selectedTenant;
  if (accessToken) headers.Authorization = `Bearer ${accessToken}`;
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

        // IMPORTANT: This should hit your refresh endpoint relative to baseURL.
        // If your refresh endpoint is /api/auth/refresh/ then:
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