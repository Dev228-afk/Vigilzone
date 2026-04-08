import axios, { type AxiosRequestHeaders } from "axios";
import { getSelectedTenantId } from "@/lib/tenant"; // add

// ── Django REST API (behind Nginx at /api) ───────────────────
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "/api";

export const api = axios.create({
  baseURL: API_BASE,
});

// Keep client + route guards consistent: accept token from either localStorage
// or sessionStorage. Some flows may store tokens in one or the other.
let accessToken =
  localStorage.getItem("accessToken") ?? sessionStorage.getItem("accessToken");

export function setAccessToken(t: string | null) {
  accessToken = t;
  if (t) {
    localStorage.setItem("accessToken", t);
    sessionStorage.setItem("accessToken", t);
  } else {
    localStorage.removeItem("accessToken");
    sessionStorage.removeItem("accessToken");
  }
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
let isRefreshing = false;
let failedQueue: Array<{ resolve: (value?: unknown) => void; reject: (reason?: any) => void }> = [];

const processQueue = (error: any, token: string | null = null) => {
  failedQueue.forEach((prom) => {
    if (error) {
      prom.reject(error);
    } else {
      prom.resolve(token);
    }
  });
  failedQueue = [];
};

api.interceptors.response.use(
  (r) => r,
  async (err) => {
    const originalRequest = err.config;

    if (err.response?.status === 401 && originalRequest && !originalRequest._retry) {
      if (isRefreshing) {
        // If already refreshing, queue the request
        return new Promise((resolve, reject) => {
          failedQueue.push({ resolve, reject });
        })
          .then((token) => {
            originalRequest.headers.Authorization = `Bearer ${token}`;
            return api(originalRequest);
          })
          .catch((err) => Promise.reject(err));
      }

      originalRequest._retry = true;
      isRefreshing = true;

      try {
        const rt = localStorage.getItem("refreshToken");
        if (!rt) throw new Error("no refresh");

        const { data } = await axios.post(`${API_BASE}/auth/refresh/`, { refresh: rt });

        setAccessToken(data.access);
        originalRequest.headers.Authorization = `Bearer ${data.access}`;
        
        processQueue(null, data.access);
        return api(originalRequest);
      } catch (refreshError) {
        processQueue(refreshError, null);
        setAccessToken(null);
        return Promise.reject(refreshError);
      } finally {
        isRefreshing = false;
      }
    }

    return Promise.reject(err);
  }
);