import { useEffect, useRef, useState } from "react";
import { Room, RoomEvent, Track, type RemoteTrack } from "livekit-client";
import { api } from "@/lib/api";

interface LiveKitViewerProps {
  cameraId: number;
  className?: string;
  showStatus?: boolean;
}

export default function LiveKitViewer({ cameraId, className, showStatus = true }: LiveKitViewerProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const roomRef = useRef<Room | null>(null);
  const currentTrackRef = useRef<RemoteTrack | null>(null);

  const [loading, setLoading] = useState(true);
  const [connected, setConnected] = useState(false);
  const [hasVideo, setHasVideo] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const detachCurrent = () => {
      const track = currentTrackRef.current;
      if (track) {
        track.detach();
      }
      currentTrackRef.current = null;
      if (containerRef.current) {
        containerRef.current.innerHTML = "";
      }
    };

    const attachTrack = (track: RemoteTrack) => {
      if (track.kind !== Track.Kind.Video) return;
      detachCurrent();
      const el = track.attach();
      el.className = "w-full h-full object-cover";
      el.setAttribute("playsinline", "true");
      if (containerRef.current) {
        containerRef.current.appendChild(el);
      }
      currentTrackRef.current = track;
      setHasVideo(true);
    };

    const connect = async () => {
      setLoading(true);
      setConnected(false);
      setHasVideo(false);
      setError(null);

      try {
        const { data } = await api.get(`/livekit/cameras/${cameraId}/viewer_token/`);
        if (!data?.token || !data?.url) {
          throw new Error("viewer token endpoint returned incomplete data");
        }

        const room = new Room({ adaptiveStream: true, dynacast: true });
        roomRef.current = room;

        room.on(RoomEvent.Connected, () => {
          if (!cancelled) {
            setConnected(true);
          }
        });

        room.on(RoomEvent.TrackSubscribed, (track) => {
          if (!cancelled) {
            attachTrack(track);
          }
        });

        room.on(RoomEvent.TrackUnsubscribed, (track) => {
          if (!cancelled && currentTrackRef.current?.sid === track.sid) {
            detachCurrent();
            setHasVideo(false);
          }
        });

        room.on(RoomEvent.Disconnected, () => {
          if (!cancelled) {
            setConnected(false);
            setHasVideo(false);
          }
          detachCurrent();
        });

        await room.connect(String(data.url), String(data.token));

        room.remoteParticipants.forEach((participant) => {
          participant.trackPublications.forEach((pub) => {
            if (pub.track && pub.track.kind === Track.Kind.Video) {
              attachTrack(pub.track);
            }
          });
        });
      } catch (err) {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : "failed to connect to LiveKit");
        }
      } finally {
        if (!cancelled) {
          setLoading(false);
        }
      }
    };

    connect();

    return () => {
      cancelled = true;
      detachCurrent();
      const room = roomRef.current;
      roomRef.current = null;
      if (room) {
        room.disconnect();
      }
    };
  }, [cameraId]);

  return (
    <div className={`relative bg-muted overflow-hidden ${className ?? ""}`}>
      <div ref={containerRef} className="absolute inset-0" />

      {loading && (
        <div className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground bg-background/30">
          Connecting to LiveKit...
        </div>
      )}

      {!loading && error && (
        <div className="absolute inset-0 flex items-center justify-center text-xs text-destructive bg-background/40 text-center px-3">
          LiveKit error: {error}
        </div>
      )}

      {!loading && !error && connected && !hasVideo && (
        <div className="absolute inset-0 flex items-center justify-center text-xs text-muted-foreground bg-background/30 text-center px-3">
          Connected. Waiting for relay video track...
        </div>
      )}

      {showStatus && connected && (
        <span className="absolute top-2 right-2 text-[11px] bg-emerald-600/85 text-white px-2 py-0.5 rounded">
          LiveKit
        </span>
      )}
    </div>
  );
}
