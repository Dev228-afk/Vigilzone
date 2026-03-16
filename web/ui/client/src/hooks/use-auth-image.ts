import { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";

/**
 * Hook that fetches an API-protected image via the authenticated axios client
 * and returns a blob URL that can be used in <img src>.
 *
 * For non-API URLs (static assets, data URIs), returns the URL as-is.
 * Returns null while loading or if the fetch fails.
 */
export function useAuthImage(url: string | undefined | null): string | null {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const prevRef = useRef<string | null>(null);

  // Treat both "raw" backend paths and paths behind the Django API base as protected.
  // - "/streams/..." and "/ai/..." are fetched via axios baseURL ("/api").
  // - "/api/..." may appear in older stored URLs; strip the extra prefix.
  const isApi = url
    ? (url.startsWith("/api/") || url.startsWith("/streams/") || url.startsWith("/ai/"))
    : false;

  const normalizeForAxios = (u: string) => (u.startsWith("/api/") ? u.slice(4) : u);

  useEffect(() => {
    // Non-API URLs — use directly
    if (!url) {
      setBlobUrl(null);
      return;
    }
    if (!isApi) {
      setBlobUrl(url);
      return;
    }

    // API URL — fetch with auth
    let cancelled = false;
    (async () => {
      try {
        const resp = await api.get(normalizeForAxios(url), { responseType: "blob" });
        if (cancelled) return;
        const objectUrl = URL.createObjectURL(resp.data);
        if (prevRef.current) URL.revokeObjectURL(prevRef.current);
        prevRef.current = objectUrl;
        setBlobUrl(objectUrl);
      } catch {
        if (!cancelled) setBlobUrl(null);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [url, isApi]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (prevRef.current) URL.revokeObjectURL(prevRef.current);
    };
  }, []);

  return blobUrl;
}
