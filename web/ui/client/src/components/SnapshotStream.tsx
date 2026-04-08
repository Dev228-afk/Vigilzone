import { useState, useEffect, useRef } from "react";
import { api } from "@/lib/api";

interface SnapshotStreamProps extends React.ImgHTMLAttributes<HTMLImageElement> {
  /** Camera ID (Django pk) */
  cameraId: number;
  /** Polling interval in milliseconds (default: 500 = 2 FPS) */
  pollInterval?: number;
  /** JPEG quality (1-100, default: 75) */
  jpegQuality?: number;
  /** Callback when streaming starts */
  onStarted?: () => void;
  /** Rendered while loading or on error */
  fallback?: React.ReactNode;
}

/**
 * Renders an `<img>` tag that periodically fetches the latest snapshot from
 * the camera. Uses signed token auth for query-string compatibility.
 *
 * Automatically refreshes the token before expiry (every 50s for 60s TTL).
 * Falls back to parent fallback on persistent errors.
 *
 * Default 500ms poll (2 FPS) balances near-real-time updates vs. network load.
 * Deduplicates requests to prevent overwhelming the backend.
 */
export default function SnapshotStream({
  cameraId,
  pollInterval = 500,
  jpegQuality = 75,
  onStarted,
  fallback,
  alt,
  ...imgProps
}: SnapshotStreamProps) {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [retryTick, setRetryTick] = useState(0);
  
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const tokenRefreshRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const prevBlobRef = useRef<string | null>(null);
  const tokenRef = useRef<string | null>(null);
  const fetchInProgressRef = useRef(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  // Store callback in ref to avoid useEffect dep issues (A8 fix)
  const onStartedRef = useRef(onStarted);
  onStartedRef.current = onStarted;

  const clearTimers = () => {
    if (timerRef.current) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
    if (tokenRefreshRef.current) {
      clearInterval(tokenRefreshRef.current);
      tokenRefreshRef.current = null;
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  };

  // Fetch and set current snapshot (with request deduplication)
  const fetchSnapshot = async (token: string | null) => {
    if (fetchInProgressRef.current) return;
    
    fetchInProgressRef.current = true;
    
    // Cancel any previous pending request
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }
    abortControllerRef.current = new AbortController();

    try {
      let url = `/streams/${cameraId}/snapshot/`;
      const params = new URLSearchParams();
      if (token) {
        params.append('token', token);
      }
      if (jpegQuality < 100) {
        params.append('jpeg_quality', String(jpegQuality));
      }
      if (params.toString()) {
        url += `?${params.toString()}`;
      }
      
      const { data } = await api.get(url, {
        responseType: "blob",
        signal: abortControllerRef.current.signal,
      });
      
      const newBlobUrl = URL.createObjectURL(data);
      
      // Revoke previous blob URL to prevent memory leaks (A6 fix)
      if (prevBlobRef.current) {
        URL.revokeObjectURL(prevBlobRef.current);
      }
      prevBlobRef.current = newBlobUrl;
      setBlobUrl(newBlobUrl);
      setError(false);
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) {
        setError(true);
        console.warn(`[SnapshotStream] Failed to fetch snapshot for camera ${cameraId}:`, err);
      }
    } finally {
      fetchInProgressRef.current = false;
    }
  };

  // Fetch new signed token
  const fetchToken = async () => {
    try {
      const { data } = await api.get(`/streams/${cameraId}/signed_stream_token/`);
      const newToken = data.token;
      tokenRef.current = newToken;
      await fetchSnapshot(newToken);
    } catch (err) {
      console.warn(`Failed to fetch signed token for camera ${cameraId}:`, err);
      setError(true);
    }
  };

  useEffect(() => {
    let cancelled = false;

    if (!Number.isFinite(cameraId) || cameraId <= 0) {
      setError(true);
      setBlobUrl(null);
      clearTimers();
      return () => {
        cancelled = true;
      };
    }

    const hasAuth = !!(
      localStorage.getItem("accessToken") || sessionStorage.getItem("accessToken")
    );
    if (!hasAuth) {
      setError(true);
      setBlobUrl(null);
      clearTimers();
      return () => {
        cancelled = true;
      };
    }

    clearTimers();
    
    (async () => {
      try {
        await fetchToken();
        if (cancelled) return;

        pollRef.current = setInterval(() => {
          if (!cancelled && tokenRef.current) {
            fetchSnapshot(tokenRef.current);
          }
        }, pollInterval);
        
        // Notify parent via ref (won't trigger re-render loop — A8 fix)
        onStartedRef.current?.();
        console.log(`[SnapshotStream] Started polling camera ${cameraId} at ${pollInterval}ms interval, quality ${jpegQuality}%`);

        tokenRefreshRef.current = setInterval(() => {
          if (!cancelled) {
            fetchToken();
          }
        }, 50_000);
      } catch {
        if (!cancelled) {
          setError(true);
        }
      }
    })();

    return () => {
      cancelled = true;
      clearTimers();
    };
    // Intentionally omit onStarted from deps — stored in ref (A8 fix)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId, pollInterval, jpegQuality, retryTick]);

  // Cleanup blob URLs on unmount
  useEffect(() => {
    return () => {
      if (prevBlobRef.current) {
        URL.revokeObjectURL(prevBlobRef.current);
        prevBlobRef.current = null;
      }
    };
  }, []);

  const handleImgError = () => {
    setError(true);
    clearTimers();
    timerRef.current = setTimeout(() => {
      setRetryTick((v) => v + 1);
    }, 2000);
  };

  if (error || !blobUrl) {
    return <>{fallback ?? null}</>;
  }

  return (
    <img
      src={blobUrl}
      alt={alt ?? "Snapshot stream"}
      onError={handleImgError}
      {...imgProps}
    />
  );
}
