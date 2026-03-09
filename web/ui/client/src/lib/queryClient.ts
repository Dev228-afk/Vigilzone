import { QueryClient, QueryFunction } from "@tanstack/react-query";
import { api } from "./api";

function toErrorMessage(err: any) {
  // Axios errors have response/data/status
  const status = err?.response?.status;
  const data = err?.response?.data;
  const text =
    typeof data === "string"
      ? data
      : data
      ? JSON.stringify(data)
      : err?.message || "Request failed";
  return status ? `${status}: ${text}` : text;
}

// Keep same signature as before (minimal changes)
export async function apiRequest(
  method: string,
  url: string,
  data?: unknown
): Promise<any> {
  try {
    const res = await api.request({
      method,
      url,   // expects urls like "/things" if baseURL is ".../api"
      data,  // axios uses `data` not `body`
    });
    return res; // you used to return Response; now return AxiosResponse
  } catch (err) {
    throw new Error(toErrorMessage(err));
  }
}

type UnauthorizedBehavior = "returnNull" | "throw";

export const getQueryFn: <T>(options: {
  on401: UnauthorizedBehavior;
}) => QueryFunction<T> =
  ({ on401 }) =>
  async ({ queryKey }) => {
    // Your old code used fetch(queryKey.join("/")) which is odd unless queryKey contains a full URL.
    // Minimal-change approach: support both:
    const path = queryKey.join("/") as string;

    try {
      const res = await api.get(path);
      return res.data as T;
    } catch (err: any) {
      const status = err?.response?.status;
      if (on401 === "returnNull" && status === 401) return null as any;
      throw new Error(toErrorMessage(err));
    }
  };

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      queryFn: getQueryFn({ on401: "throw" }),
      refetchInterval: false,
      refetchOnWindowFocus: false,
      staleTime: Infinity,
      retry: false,
    },
    mutations: {
      retry: false,
    },
  },
});