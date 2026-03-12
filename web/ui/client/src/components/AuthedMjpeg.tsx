import { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";

interface AuthedMjpegProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  /** Camera ID (Django pk) */
  cameraId: number;
  /** Rendered while loading or on error */
  fallback?: React.ReactNode;
}

/**
 * Renders an `<img>` tag pointing at the MJPEG endpoint using a
 * short-lived signed token (60 s).  Automatically refreshes the token
 * before expiry so the stream stays alive.
 *
 * Works in plain `<img>` (no JS fetch needed) because auth is in the
 * query-string rather than the Authorization header.
 */
export default function AuthedMjpeg({
  cameraId,
  fallback,
  alt,
  ...imgProps
}: AuthedMjpegProps) {
  const [src, setSrc] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function fetchToken() {
      try {
        const { data } = await api.get(`/streams/${cameraId}/signed_stream_token/`);
        if (cancelled) return;
        const token: string = data.token;
        const ttl: number = data.ttl ?? 60;
        setSrc(`/api/streams/${cameraId}/mjpeg/?token=${encodeURIComponent(token)}`);
        setError(false);
        // Refresh token at 80% of TTL
        timerRef.current = setTimeout(fetchToken, ttl * 800);
      } catch {
        if (!cancelled) setError(true);
      }
    }

    fetchToken();

    return () => {
      cancelled = true;
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [cameraId]);

  if (error || !src) {
    return <>{fallback ?? null}</>;
  }

  return (
    <img
      src={src}
      alt={alt ?? "MJPEG stream"}
      onError={() => setError(true)}
      {...imgProps}
    />
  );
}
