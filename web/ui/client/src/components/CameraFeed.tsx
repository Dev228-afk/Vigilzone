import { useState, useEffect, useCallback, useRef } from "react";
import { Video, Wifi, WifiOff } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import CanvasStream from "@/components/CanvasStream"; // Legacy
import AuthedMjpeg from "@/components/AuthedMjpeg"; // Legacy
import SnapshotStream from "@/components/SnapshotStream"; // Legacy
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

const METHOD_COLORS: Record<StreamMethod, string> = {
  'webrtc-iframe': 'bg-blue-500',
  'static': 'bg-gray-500',
  'error': 'bg-red-500',
  'idle': 'bg-slate-400',
};

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

  // The active streaming method
  const [activeMethod, setActiveMethod] = useState<StreamMethod>('idle');
  // Methods that have already failed during this component's lifecycle
  const failedRef = useRef<Set<StreamMethod>>(new Set());
  // Force a re-render when the ref changes
  const [, forceUpdate] = useState(0);

  const needsAuth = imageUrl ? isApiUrl(imageUrl) : false;
  const displaySrc = needsAuth ? null : imageUrl;

  // Compute the optimal method based on capabilities, URL, and failures
  const computeNextMethod = useCallback((): StreamMethod => {
    const failed = failedRef.current;

    // 1. WebRTC iframe — only when MediaMTX is confirmed reachable and streamUrl actually exists
    if (streamUrl && mtxChecked && mtxReachable && !failed.has('webrtc-iframe')) {
      // Feature Flag: Is the API healthcheck enabled? (Objective 3)
      const apiHealthcheckEnabled = String(import.meta.env.VITE_ENABLE_MEDIAMTX_API_HEALTHCHECK ?? "true").toLowerCase() === "true";
      
      if (!apiHealthcheckEnabled) {
        // If API check is disabled, we trust mtxReachable (ping) and the provided streamUrl
        return 'webrtc-iframe';
      }

      // Only use WebRTC if the stream path is actively publishing in MediaMTX
      // Prioritize streamPath prop if provided, otherwise extract from URL
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

    // 5. Static image
    if (displaySrc && !failed.has('static')) {
      return 'static';
    }

    return 'error';
  }, [streamUrl, mtxChecked, mtxReachable, cameraId, displaySrc]);

  // Advance to the next method when health check completes or on mount
  useEffect(() => {
    // Wait for MediaMTX health check before deciding
    if (!mtxChecked && streamUrl) return;

    if (activeMethod === 'idle') {
      setActiveMethod(computeNextMethod());
    }
  }, [mtxChecked, streamUrl, activeMethod, computeNextMethod]);

  // Handler: current method failed, advance to next
  const handleMethodFailed = useCallback((method: StreamMethod) => {
    failedRef.current.add(method);
    const next = computeNextMethod();
    console.log(`[CameraFeed] ${name}: ${METHOD_LABELS[method]} failed, advancing to ${METHOD_LABELS[next]}`);
    setActiveMethod(next);
    forceUpdate((v) => v + 1);
  }, [computeNextMethod, name]);

  // Handler: method started successfully
  const handleMethodStarted = useCallback((method: StreamMethod) => {
    console.log(`[CameraFeed] ${name}: Using ${METHOD_LABELS[method]}`);
    setActiveMethod(method);
  }, [name]);

  // Focused camera gets higher FPS; gallery cameras get lower FPS
  const snapshotPollInterval = isFocused ? 200 : 500;
  const canvasFps = isFocused ? 15 : 5;

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
    <Card className="overflow-hidden">
      <div className="relative aspect-video bg-muted">
        {renderMedia()}
        {/* DECOUPLED FIX: Separate Media Status from AI Status */}
        <div className="absolute top-2 left-2 flex flex-col gap-1">
          {/* Stream Status Badge - Based on actual media presence */}
          <Badge variant={(mtxReachable && streamUrl) || displaySrc ? "default" : "destructive"} className="gap-1 w-max opacity-90">
            {(mtxReachable && streamUrl) || displaySrc ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
            {(mtxReachable && streamUrl) || displaySrc ? "Live Feed" : "Feed Offline"}
          </Badge>
          
          {/* AI Status Badge - Maps specifically to the backend 'status' prop */}
          <Badge variant={status === "active" ? "secondary" : "outline"} className="w-max opacity-90 bg-background/80 backdrop-blur-sm">
            {status === "active" ? "AI Synced" : "AI Unsynced"}
          </Badge>
        </div>
        {timestamp && (
          <div className="absolute bottom-2 right-2 bg-black/70 text-white text-xs px-2 py-1 rounded">
            {timestamp}
          </div>
        )}
        {health && (
          <div className="absolute bottom-2 left-2 bg-black/70 text-white text-[10px] px-2 py-1 rounded">
            {health.connected ? "Connected" : "Warming"}
          </div>
        )}
        {/* Streaming Method Indicator */}
        <div className="absolute top-12 left-2">
          <Badge className={`${METHOD_COLORS[activeMethod] || 'bg-slate-400'} text-white text-xs`}>
            {METHOD_LABELS[activeMethod] || 'Unknown'}
          </Badge>
        </div>
      </div>
      <div className="p-3">
        <h3 className="font-semibold text-sm" data-testid={`text-camera-${name.toLowerCase().replace(/\s/g, '-')}`}>{name}</h3>
        <p className="text-xs text-muted-foreground">{location}</p>
      </div>
    </Card>
  );
}
