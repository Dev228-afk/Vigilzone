import { useState, useEffect, useRef } from "react";
import { Video, Wifi, WifiOff } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import AuthedMjpeg from "@/components/AuthedMjpeg";
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
 * Handles both "/api/..." (full path) and "/streams/..." (relative to baseURL).
 * Static imports (data URLs, relative assets) can be used directly.
 */
function isApiUrl(url: string): boolean {
  return url.startsWith("/api/") || url.startsWith("/streams/") || url.startsWith("/ai/");
}

/**
 * Strip leading "/api" when present so axios baseURL ("/api") doesn't double it.
 */
function normalizeForAxios(url: string): string {
  if (url.startsWith("/api/")) return url.slice(4); // "/api/streams/..." → "/streams/..."
  return url;
}

export default function CameraFeed({ name, location, status, cameraId, imageUrl, streamUrl, health, timestamp }: CameraFeedProps) {
  const [blobSrc, setBlobSrc] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const [iframeError, setIframeError] = useState(false);
  const prevBlobRef = useRef<string | null>(null);
  const { reachable: mtxReachable, checked: mtxChecked } = useMediamtxHealth();

  const needsAuth = imageUrl ? isApiUrl(imageUrl) : false;

  // Legacy blob-fetch path (only used when streamUrl is absent)
  useEffect(() => {
    if (streamUrl || !imageUrl || !needsAuth) {
      setBlobSrc(null);
      setError(false);
      return;
    }

    let cancelled = false;

    (async () => {
      try {
        const resp = await api.get(normalizeForAxios(imageUrl), { responseType: "blob" });
        if (cancelled) return;
        const url = URL.createObjectURL(resp.data);
        if (prevBlobRef.current) URL.revokeObjectURL(prevBlobRef.current);
        prevBlobRef.current = url;
        setBlobSrc(url);
        setError(false);
      } catch {
        if (!cancelled) setError(true);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [imageUrl, needsAuth, streamUrl]);

  useEffect(() => {
    return () => {
      if (prevBlobRef.current) URL.revokeObjectURL(prevBlobRef.current);
    };
  }, []);

  const displaySrc = needsAuth ? blobSrc : imageUrl;

  /* ── Render priority: streamUrl (WebRTC iframe) > MJPEG > imageUrl > placeholder ── */
  const renderMedia = () => {
    // WebRTC iframe — only attempt when MediaMTX is confirmed reachable
    if (streamUrl && !iframeError && mtxChecked && mtxReachable) {
      return (
        <iframe
          src={streamUrl}
          title={`Live feed — ${name}`}
          className="w-full h-full border-0"
          allow="autoplay; encrypted-media"
          sandbox="allow-scripts allow-same-origin"
          onError={() => setIframeError(true)}
        />
      );
    }
    // MJPEG fallback — when WebRTC fails or MediaMTX unreachable, but we have a camera ID
    if ((iframeError || (mtxChecked && !mtxReachable)) && cameraId) {
      return (
        <AuthedMjpeg
          cameraId={cameraId}
          alt={name}
          className="w-full h-full object-cover"
          fallback={
            displaySrc && !error ? (
              <img
                src={displaySrc}
                alt={name}
                className="w-full h-full object-cover"
                onError={() => setError(true)}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center">
                <Video className="w-12 h-12 text-muted-foreground" />
                <span className="absolute bottom-2 left-2 text-xs text-destructive">Feed unavailable</span>
              </div>
            )
          }
        />
      );
    }
    // Image fallback
    if (displaySrc && !error) {
      return (
        <img
          src={displaySrc}
          alt={name}
          className="w-full h-full object-cover"
          onError={() => setError(true)}
        />
      );
    }
    // Placeholder
    return (
      <div className="w-full h-full flex items-center justify-center">
        <Video className="w-12 h-12 text-muted-foreground" />
        {(error || iframeError) && (
          <span className="absolute bottom-2 left-2 text-xs text-destructive">Feed unavailable</span>
        )}
      </div>
    );
  };

  return (
    <Card className="overflow-hidden">
      <div className="relative aspect-video bg-muted">
        {renderMedia()}
        <div className="absolute top-2 left-2">
          <Badge variant={status === "active" ? "default" : "destructive"} className="gap-1">
            {status === "active" ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
            {status === "active" ? "Live" : "Offline"}
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
      </div>
      <div className="p-3">
        <h3 className="font-semibold text-sm" data-testid={`text-camera-${name.toLowerCase().replace(/\s/g, '-')}`}>{name}</h3>
        <p className="text-xs text-muted-foreground">{location}</p>
      </div>
    </Card>
  );
}
