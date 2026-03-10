import { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";

interface AuthImageProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  /** API path to fetch with auth, e.g. "/streams/3/snapshot/" */
  src: string;
  /** Auto-refresh interval in ms (0 = no refresh). Default 10 000 ms. */
  refreshInterval?: number;
  /** Render when the image fails or is loading */
  fallback?: React.ReactNode;
}

/**
 * An `<img>` wrapper that fetches the resource through the authenticated
 * axios instance, converting the response to a blob object URL.
 *
 * Solves the problem where raw `<img src="/api/...">` doesn't send
 * the JWT Bearer header and gets a 401.
 */
export default function AuthImage({
  src,
  refreshInterval = 10_000,
  fallback,
  alt,
  ...imgProps
}: AuthImageProps) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const prevUrl = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchBlob() {
      try {
        const resp = await api.get(src, { responseType: "blob" });
        if (cancelled) return;
        const url = URL.createObjectURL(resp.data);
        // Revoke previous URL to prevent memory leaks
        if (prevUrl.current) URL.revokeObjectURL(prevUrl.current);
        prevUrl.current = url;
        setObjectUrl(url);
        setError(false);
      } catch {
        if (!cancelled) setError(true);
      }
    }

    fetchBlob();

    // Auto-refresh
    let iv: ReturnType<typeof setInterval> | undefined;
    if (refreshInterval > 0) {
      iv = setInterval(fetchBlob, refreshInterval);
    }

    return () => {
      cancelled = true;
      if (iv) clearInterval(iv);
    };
  }, [src, refreshInterval]);

  // Revoke on unmount
  useEffect(() => {
    return () => {
      if (prevUrl.current) URL.revokeObjectURL(prevUrl.current);
    };
  }, []);

  if (error || !objectUrl) {
    return <>{fallback ?? null}</>;
  }

  return <img src={objectUrl} alt={alt} {...imgProps} />;
}
