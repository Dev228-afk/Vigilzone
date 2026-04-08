import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";

interface CanvasStreamProps extends React.CanvasHTMLAttributes<HTMLCanvasElement> {
  /** Camera ID (Django pk) */
  cameraId: number;
  /** Target FPS (default: 10 for efficient canvas rendering) */
  targetFps?: number;
  /** JPEG quality (1-100, default: 85) */
  jpegQuality?: number;
  /** Callback when streaming method changes */
  onStreamingMethod?: (method: 'canvas-stream' | 'error') => void;
  /** Fallback if streaming fails */
  fallback?: React.ReactNode;
}

/**
 * Canvas-based streaming using optimized snapshot polling.
 * Renders frames to canvas at target FPS for smooth, near-real-time video.
 *
 * Uses signed token auth and adaptive frame timing for network efficiency.
 */
export default function CanvasStream({
  cameraId,
  targetFps = 40,
  jpegQuality = 35,
  onStreamingMethod,
  fallback,
  ...canvasProps
}: CanvasStreamProps) {
  const [error, setError] = useState(false);

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const ctxRef = useRef<CanvasRenderingContext2D | null>(null);
  const tokenRef = useRef<string | null>(null);
  const rafRef = useRef<number | null>(null);
  const tokenRefreshRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastFrameTimeRef = useRef(0);
  const frameCountRef = useRef(0);
  const abortControllerRef = useRef<AbortController | null>(null);
  const isMountedRef = useRef(true);
  const fetchingRef = useRef(false);
  // Store callbacks in refs to avoid useEffect dependency issues (A7)
  const onStreamingMethodRef = useRef(onStreamingMethod);
  onStreamingMethodRef.current = onStreamingMethod;

  const frameDuration = 1000 / Math.max(1, targetFps);

  const clearTimers = useCallback(() => {
    if (rafRef.current) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
    if (tokenRefreshRef.current) {
      clearInterval(tokenRefreshRef.current);
      tokenRefreshRef.current = null;
    }
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
  }, []);

  useEffect(() => {
    isMountedRef.current = true;
    frameCountRef.current = 0;
    fetchingRef.current = false;

    if (!Number.isFinite(cameraId) || cameraId <= 0) {
      setError(true);
      return;
    }

    const hasAuth = !!(
      localStorage.getItem("accessToken") || sessionStorage.getItem("accessToken")
    );
    if (!hasAuth) {
      setError(true);
      return;
    }

    // Initialize canvas context
    if (canvasRef.current) {
      const ctx = canvasRef.current.getContext("2d");
      if (ctx) {
        ctxRef.current = ctx;
      }
    }

    clearTimers();
    abortControllerRef.current = new AbortController();

    const fetchToken = async () => {
      try {
        const { data } = await api.get(`/streams/${cameraId}/signed_stream_token/`);
        if (isMountedRef.current) {
          tokenRef.current = data.token;
        }
      } catch (err) {
        if (isMountedRef.current) {
          console.warn(`Failed to fetch token for camera ${cameraId}:`, err);
          setError(true);
        }
      }
    };

    const fetchFrame = async () => {
      if (!tokenRef.current || !isMountedRef.current || fetchingRef.current) return;

      fetchingRef.current = true;
      try {
        const qualityParam = jpegQuality < 100 ? `&jpeg_quality=${jpegQuality}` : '';
        const url = `/streams/${cameraId}/snapshot/?token=${encodeURIComponent(
          tokenRef.current
        )}&v=${frameCountRef.current}${qualityParam}`;

        const { data } = await api.get(url, {
          responseType: "blob",
          signal: abortControllerRef.current?.signal,
        });

        if (!isMountedRef.current) return;

        const img = new Image();
        const objectUrl = URL.createObjectURL(data);

        img.onload = () => {
          if (!isMountedRef.current || !canvasRef.current || !ctxRef.current) {
            URL.revokeObjectURL(objectUrl);
            return;
          }

          if (canvasRef.current.width !== img.width || canvasRef.current.height !== img.height) {
            canvasRef.current.width = img.width;
            canvasRef.current.height = img.height;
          }

          ctxRef.current!.imageSmoothingEnabled = true;
          ctxRef.current!.imageSmoothingQuality = 'high';
          ctxRef.current!.drawImage(img, 0, 0);
          frameCountRef.current++;
          setError(false);

          if (frameCountRef.current === 1) {
            console.log(`[CanvasStream] Camera ${cameraId}: Streaming at ${targetFps} FPS, quality ${jpegQuality}%`);
          }

          URL.revokeObjectURL(objectUrl);
        };

        img.onerror = () => {
          URL.revokeObjectURL(objectUrl);
          setError(true);
        };

        img.src = objectUrl;
      } catch (err) {
        if (!(err instanceof DOMException && err.name === "AbortError")) {
          console.warn(`Failed to fetch frame for camera ${cameraId}:`, err);
          setError(true);
        }
      } finally {
        fetchingRef.current = false;
      }
    };

    // Use isMountedRef (ref) for loop condition instead of state (A9 fix)
    const renderLoop = () => {
      if (!isMountedRef.current) return;

      const now = performance.now();
      const elapsed = now - lastFrameTimeRef.current;

      if (elapsed >= frameDuration) {
        lastFrameTimeRef.current = now;
        fetchFrame();
      }

      rafRef.current = requestAnimationFrame(renderLoop);
    };

    (async () => {
      try {
        await fetchToken();
        if (!isMountedRef.current) return;

        lastFrameTimeRef.current = performance.now();
        rafRef.current = requestAnimationFrame(renderLoop);

        // Notify parent of streaming method via ref (won't cause re-render loop)
        onStreamingMethodRef.current?.('canvas-stream');
        console.log(`[CanvasStream] Started streaming camera ${cameraId} at ${targetFps} FPS`);

        // Refresh token every 50 seconds (before 60s expiry)
        tokenRefreshRef.current = setInterval(fetchToken, 50_000);
      } catch (err) {
        console.error(`[CanvasStream] Failed to initialize stream for camera ${cameraId}:`, err);
        onStreamingMethodRef.current?.('error');
        setError(true);
      }
    })();

    return () => {
      isMountedRef.current = false;
      clearTimers();
    };
    // Intentionally omit onStreamingMethod from deps — stored in ref (A7 fix)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [cameraId, targetFps, jpegQuality, clearTimers, frameDuration]);

  if (error) {
    return <>{fallback ?? null}</>;
  }

  return (
    <canvas
      ref={canvasRef}
      {...canvasProps}
    />
  );
}
