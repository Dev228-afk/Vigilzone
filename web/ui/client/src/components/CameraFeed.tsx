import { useState, useEffect, useCallback, useRef } from "react";
import { Video, Wifi, WifiOff, Sparkles } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { useMediamtxHealth } from "@/hooks/use-mediamtx-health";

interface CameraFeedProps {
  name: string;
  location: string;
  status: "active" | "offline";
  /** Camera DB id — needed for MJPEG fallback */
  cameraId?: number;
  /** Static image or API snapshot URL (legacy fallback) */
  imageUrl?: string;
  /** WebRTC iframe URL — takes priority over imageUrl when provided */
  streamUrl?: string;
  /** Direct stream path name in MediaMTX (used for health gating) */
  streamPath?: string;
  /** Whether this is the focused/selected camera (gets higher frame rates) */
  isFocused?: boolean;
  health?: {
    connected: boolean;
    last_frame_ts: number | null;
    last_error: string;
    fps_config: number;
    viewers: number;
  };
  timestamp?: string;
}

/**
 * Determines if a URL needs authenticated fetching (API route).
 */
function isApiUrl(url: string): boolean {
  return url.startsWith("/api/") || url.startsWith("/streams/") || url.startsWith("/ai/");
}

type StreamMethod = 'idle' | 'webrtc-iframe' | 'static' | 'error';

const METHOD_LABELS: Record<StreamMethod, string> = {
  'webrtc-iframe': 'Live Stream',
  'static': 'Snapshot Preview',
  'error': 'Feed Unavailable',
  'idle': 'Connecting...',
};

export default function CameraFeed({
  name,
  location,
  status,
  cameraId,
  imageUrl,
  streamUrl,
  streamPath,
  isFocused = false,
  health,
  timestamp,
}: CameraFeedProps) {
  const mtxHealth = useMediamtxHealth();
  const mtxReachable = mtxHealth.reachable;
  const mtxChecked = mtxHealth.checked;
  const mtxActivePaths = mtxHealth.activePaths;

  // Intersection Observer for lazy-loading logic
  const [isInView, setIsInView] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const observer = new IntersectionObserver(
      ([entry]) => {
        setIsInView(entry.isIntersecting);
      },
      { threshold: 0.1, rootMargin: "200px" } // Load slightly before it enters view
    );

    if (containerRef.current) {
      observer.observe(containerRef.current);
    }

    return () => observer.disconnect();
  }, []);

  // Methods that have already failed during this component's lifecycle
  const failedRef = useRef<Set<StreamMethod>>(new Set());
  // The active streaming method
  const [activeMethod, setActiveMethod] = useState<StreamMethod>('idle');
  // Force a re-render when the ref changes
  const [, forceUpdate] = useState(0);

  const needsAuth = imageUrl ? isApiUrl(imageUrl) : false;
  const displaySrc = needsAuth ? null : imageUrl;

  // Compute the optimal method based on capabilities, URL, and failures
  const computeNextMethod = useCallback((): StreamMethod => {
    // Only proceed if the camera is in view (Media Lazy Loading)
    if (!isInView) return 'idle';

    const failed = failedRef.current;

    // 1. WebRTC iframe — only when MediaMTX is confirmed reachable and streamUrl actually exists
    if (streamUrl && mtxChecked && mtxReachable && !failed.has('webrtc-iframe')) {
      // Feature Flag: Is the API healthcheck enabled?
      const apiHealthcheckEnabled = String(import.meta.env.VITE_ENABLE_MEDIAMTX_API_HEALTHCHECK ?? "true").toLowerCase() === "true";

      if (!apiHealthcheckEnabled) {
        return 'webrtc-iframe';
      }

      let finalPath = "";
      if (streamPath) {
        finalPath = streamPath;
      } else {
        try {
          const urlObj = new URL(streamUrl);
          finalPath = urlObj.pathname.match(/\/([^/]+)\/?$/)?.[1] || "";
        } catch (e) {
          // Not a valid URL
        }
      }

      if (finalPath && mtxActivePaths.has(finalPath)) {
        return 'webrtc-iframe';
      }
    }

    // 2. Static image
    if (displaySrc && !failed.has('static')) {
      return 'static';
    }

    return 'error';
  }, [streamUrl, mtxChecked, mtxReachable, cameraId, displaySrc, isInView, streamPath, mtxActivePaths]);

  // Advance to the next method when health check completes or on mount
  useEffect(() => {
    // Wait for MediaMTX health check before deciding
    if (!mtxChecked && streamUrl) return;

    // If we've moved out of view, go to idle to stop the stream
    if (!isInView) {
      setActiveMethod('idle');
      return;
    }

    if (activeMethod === 'idle' || activeMethod === 'error') {
      setActiveMethod(computeNextMethod());
    }
  }, [mtxChecked, streamUrl, activeMethod, computeNextMethod, isInView]);

  // Handler: current method failed, advance to next
  const handleMethodFailed = useCallback((method: StreamMethod) => {
    failedRef.current.add(method);
    const next = computeNextMethod();
    console.log(`[CameraFeed] ${name}: ${METHOD_LABELS[method]} failed, advancing to ${METHOD_LABELS[next]}`);
    setActiveMethod(next);
    forceUpdate((v) => v + 1);
  }, [computeNextMethod, name]);

  /* ── Render only the active method ── */
  const renderMedia = () => {
    switch (activeMethod) {
      case 'webrtc-iframe':
        return (
          <iframe
            src={streamUrl}
            title={`Live feed — ${name}`}
            className="w-full h-full border-0"
            allow="autoplay; encrypted-media"
            sandbox="allow-scripts allow-same-origin"
            onError={() => handleMethodFailed('webrtc-iframe')}
          />
        );

      case 'static':
        return (
          <img
            src={displaySrc!}
            alt={name}
            className="w-full h-full object-cover"
            loading="lazy"
            onError={() => handleMethodFailed('static')}
          />
        );

      case 'error':
        return (
          <div className="w-full h-full flex items-center justify-center">
            <Video className="w-12 h-12 text-muted-foreground" />
            <span className="absolute bottom-2 left-2 text-xs text-destructive">Feed unavailable</span>
          </div>
        );

      case 'idle':
      default:
        return (
          <div className="w-full h-full flex items-center justify-center">
            <Video className="w-12 h-12 text-muted-foreground animate-pulse" />
          </div>
        );
    }
  };

  return (
    <Card ref={containerRef} className="overflow-hidden">
      <div className="relative aspect-video bg-muted">
        {renderMedia()}
        <div className="absolute top-2 left-2 flex items-start gap-1.5 p-1">
          <Badge
            variant={(mtxReachable && streamUrl) || displaySrc ? "default" : "destructive"}
            className={`${isFocused ? 'h-6 px-2.5 gap-1.5' : 'h-4 px-1.4 gap-1.4'} shadow-lg backdrop-blur-md opacity-95 transition-all`}
          >
            {(mtxReachable && streamUrl) || displaySrc ? (
              <Wifi className={`${isFocused ? 'w-3.5 h-3.5' : 'w-2.5 h-2.5'} animate-pulse`} />
            ) : (
              <WifiOff className={isFocused ? 'w-3.5 h-3.5' : 'w-2.5 h-2.5'} />
            )}
            <span className={`font-bold ${isFocused ? 'text-[10px]' : 'text-[7px]'} tracking-tight grayscale-0`}>
              {(mtxReachable && streamUrl) || displaySrc ? "LIVE FEED" : "OFFLINE"}
            </span>
          </Badge>

          {status === "active" && (
            <Badge
              variant="secondary"
              className={` ${isFocused ? 'h-6 px-2.5 gap-1.5' : 'h-4 px-1.4 gap-1.5'} bg-sky-500/90 text-white border-0 shadow-lg backdrop-blur-md opacity-95`}
            >
              <Sparkles className={isFocused ? 'w-3.5 h-3.5' : 'w-2.5 h-2.5'} />
              <span className={`font-bold ${isFocused ? 'text-[10px]' : 'text-[7px]'} tracking-tight`}>AI SYNCED</span>
            </Badge>
          )}
        </div>

        {timestamp && (
          <div className={`absolute bottom-2 right-2 bg-black/60 backdrop-blur-sm text-white ${isFocused ? 'text-[10px]' : 'text-[8px]'} font-mono px-2 py-1 rounded-md border border-white/10`}>
            {timestamp}
          </div>
        )}

        {health?.connected && (
          <div className="absolute bottom-2 left-2 flex items-center gap-1.5 bg-black/60 backdrop-blur-sm px-2 py-1 rounded-md border border-white/10">
            <div className={`${isFocused ? 'h-1.5 w-1.5' : 'h-1 w-1'} rounded-full bg-emerald-500`} />
            <span className={`text-white ${isFocused ? 'text-[10px]' : 'text-[9px]'} font-medium tracking-tight`}>Active Stream</span>
          </div>
        )}
      </div>
      <div className={isFocused ? "p-3" : "p-2.5"}>
        <h3 className={`font-semibold ${isFocused ? 'text-sm' : 'text-xs'} truncate`}>{name}</h3>
        <p className={`${isFocused ? 'text-xs' : 'text-[11px]'} text-muted-foreground truncate`}>{location}</p>
      </div>
    </Card>
  );
}
