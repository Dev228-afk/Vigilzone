import { useState, useEffect, useRef } from "react";
import { Video, Wifi, WifiOff } from "lucide-react";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";

interface CameraFeedProps {
  name: string;
  location: string;
  status: "active" | "offline";
  imageUrl?: string;
  timestamp?: string;
}

/**
 * Determines if a URL needs authenticated fetching (API route).
 * Static imports (data URLs, relative assets) can be used directly.
 */
function isApiUrl(url: string): boolean {
  return url.startsWith("/api/");
}

export default function CameraFeed({ name, location, status, imageUrl, timestamp }: CameraFeedProps) {
  const [blobSrc, setBlobSrc] = useState<string | null>(null);
  const [error, setError] = useState(false);
  const prevBlobRef = useRef<string | null>(null);

  const needsAuth = imageUrl ? isApiUrl(imageUrl) : false;

  useEffect(() => {
    if (!imageUrl || !needsAuth) {
      setBlobSrc(null);
      setError(false);
      return;
    }

    let cancelled = false;

    (async () => {
      try {
        const resp = await api.get(imageUrl, { responseType: "blob" });
        if (cancelled) return;
        const url = URL.createObjectURL(resp.data);
        // Revoke the previous blob URL to prevent memory leaks
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
  }, [imageUrl, needsAuth]);

  // Clean up on unmount
  useEffect(() => {
    return () => {
      if (prevBlobRef.current) URL.revokeObjectURL(prevBlobRef.current);
    };
  }, []);

  const displaySrc = needsAuth ? blobSrc : imageUrl;

  return (
    <Card className="overflow-hidden">
      <div className="relative aspect-video bg-muted">
        {displaySrc && !error ? (
          <img
            src={displaySrc}
            alt={name}
            className="w-full h-full object-cover"
            onError={() => setError(true)}
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center">
            <Video className="w-12 h-12 text-muted-foreground" />
            {error && (
              <span className="absolute bottom-2 left-2 text-xs text-destructive">Feed unavailable</span>
            )}
          </div>
        )}
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
      </div>
      <div className="p-3">
        <h3 className="font-semibold text-sm" data-testid={`text-camera-${name.toLowerCase().replace(/\s/g, '-')}`}>{name}</h3>
        <p className="text-xs text-muted-foreground">{location}</p>
      </div>
    </Card>
  );
}
