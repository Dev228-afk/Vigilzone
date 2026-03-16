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
  const [retryTick, setRetryTick] = useState(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const refreshRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const versionRef = useRef(0);

  const clearTimers = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (refreshRef.current) {
      clearInterval(refreshRef.current);
      refreshRef.current = null;
    }
  };

  useEffect(() => {
    let cancelled = false;

    if (!Number.isFinite(cameraId) || cameraId <= 0) {
      setError(true);
      setSrc(null);
      clearTimers();
      return () => {
        cancelled = true;
      };
    }

    const hasAuth = !!(
      localStorage.getItem("accessToken") || sessionStorage.getItem("accessToken")
    );
    if (!hasAuth) {
      // Avoid hammering signed token endpoint when user is not authenticated yet.
      setError(true);
      setSrc(null);
      clearTimers();
      return () => {
        cancelled = true;
      };
    }

    async function fetchToken() {
      try {
        const { data } = await api.get(`/streams/${cameraId}/signed_stream_token/`);
        if (cancelled) return;
        const token: string = data.token;
        versionRef.current += 1;
        setSrc(`/api/streams/${cameraId}/mjpeg/?token=${encodeURIComponent(token)}&v=${versionRef.current}`);
        setError(false);
      } catch {
        if (!cancelled) setError(true);
      }
    }

    clearTimers();
    fetchToken();

    // Refresh token every 50 seconds to stay under the 60-second token TTL.
    refreshRef.current = setInterval(fetchToken, 50_000);

    return () => {
      cancelled = true;
      clearTimers();
    };
  }, [cameraId, retryTick]);

  const handleImgError = () => {
    setError(true);
    // Back off briefly for warm-up scenarios, then request a new token.
    clearTimers();
    timerRef.current = setTimeout(() => {
      setRetryTick((v) => v + 1);
    }, 1500);
  };

  if (error || !src) {
    return <>{fallback ?? null}</>;
  }

  return (
    <img
      src={src}
      alt={alt ?? "MJPEG stream"}
      onError={handleImgError}
      {...imgProps}
    />
  );
}
