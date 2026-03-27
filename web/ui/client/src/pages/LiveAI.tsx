import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import {
  Brain,
  Camera,
  AlertTriangle,
  RefreshCw,
  Circle,
  Activity,
  User,
  Dog,
  Car,
  Wifi,
  WifiOff,
  Flame,
  Eye,
  Shield,
  Zap,
} from "lucide-react";
import { api } from "@/lib/api";
import AuthImage from "@/components/AuthImage";
import AuthedMjpeg from "@/components/AuthedMjpeg";
import { useAuthImage } from "@/hooks/use-auth-image";

/* ── Types ──────────────────────────────────────────────────── */
interface AiCamera {
  camera_id: string;
  status?: string;
  fps?: number;
  resolution?: string;
  active_tracks?: number;
  location?: string;
  [key: string]: unknown;
}

interface StreamInfo {
  id: number;
  name: string;
  site: string;
  status: string;
  ai_camera_id: string;
  stream_path: string;
  camera_type: string;
  source_type?: "registered" | "webcam";
}

interface StreamHealth {
  connected: boolean;
  last_frame_ts: number | null;
  last_error: string;
  fps_config: number;
  viewers: number;
}

interface AiAlert {
  id?: string;
  camera_id: string;
  type: string;
  severity?: string | number;
  message?: string;
  timestamp?: string;
  evidence?: {
    keyframe?: string;
    clip?: string;
  };
  [key: string]: unknown;
}

interface SystemStatus {
  device?: string | { torch_device?: string; gpu_name?: string; gpu_usable?: boolean };
  gpu_name?: string;
  active_cameras?: number;
  lanes_loaded?: number;
  uptime?: string;
  uptime_seconds?: number;
  cameras?: Array<{ camera_id: string; active: boolean; lanes: string[] }>;
  [key: string]: unknown;
}

interface AiEntity {
  id: string;
  name: string;
  type: "person" | "pet" | "vehicle";
  group: "household" | "neighbor";
  lastSeen?: string;
  cameras?: string[];
  imageUrl?: string;
}

/* ── Demo data (shown when AI module is offline) ──────────── */
const DEMO_CAMERAS: AiCamera[] = [
  { camera_id: "front_door", status: "active", fps: 24.8, resolution: "1920x1080", active_tracks: 2, location: "Entrance" },
  { camera_id: "living_room", status: "active", fps: 29.7, resolution: "1920x1080", active_tracks: 1, location: "Interior" },
  { camera_id: "garage", status: "active", fps: 15.2, resolution: "1280x720", active_tracks: 0, location: "Garage" },
  { camera_id: "backyard", status: "active", fps: 22.1, resolution: "1920x1080", active_tracks: 3, location: "Outdoor" },
];

const DEMO_ALERTS: AiAlert[] = [
  { id: "demo-1", camera_id: "front_door", type: "stranger", severity: "high", message: "Unknown person detected at front entrance", timestamp: new Date(Date.now() - 1000 * 60 * 12).toISOString() },
  { id: "demo-2", camera_id: "backyard", type: "intrusion", severity: "medium", message: "Motion detected in restricted zone", timestamp: new Date(Date.now() - 1000 * 60 * 45).toISOString() },
  { id: "demo-3", camera_id: "garage", type: "animal", severity: "low", message: "Animal detected near garage door", timestamp: new Date(Date.now() - 1000 * 60 * 120).toISOString() },
  { id: "demo-4", camera_id: "front_door", type: "loitering", severity: "medium", message: "Person loitering near entrance for 3+ minutes", timestamp: new Date(Date.now() - 1000 * 60 * 200).toISOString() },
  { id: "demo-5", camera_id: "backyard", type: "fire", severity: "critical", message: "Smoke/fire signature detected in backyard zone", timestamp: new Date(Date.now() - 1000 * 60 * 360).toISOString() },
];

const DEMO_SYSTEM: SystemStatus = {
  device: "cuda",
  gpu_name: "NVIDIA RTX 4070",
  active_cameras: 4,
  lanes_loaded: 11,
  uptime: "2d 14h 32m",
};

const DEMO_ENTITIES: AiEntity[] = [
  { id: "e1", name: "Dev", type: "person", group: "household", lastSeen: "2 min ago", cameras: ["front_door", "living_room"] },
  { id: "e2", name: "Harsh", type: "person", group: "household", lastSeen: "15 min ago", cameras: ["garage"] },
  { id: "e3", name: "Cameron", type: "person", group: "household", lastSeen: "1 hr ago", cameras: ["backyard"] },
  { id: "e4", name: "Bella", type: "pet", group: "household", lastSeen: "30 min ago", cameras: ["backyard", "living_room"] },
];

/* ── Severity badge colour ───────────────────────────────────── */
function severityVariant(sev: string | number | undefined) {
  const s = typeof sev === "number" ? sev : 0;
  const str = typeof sev === "string" ? sev.toLowerCase() : "";
  if (s >= 4 || str === "critical" || str === "high") return "destructive";
  if (s === 3 || str === "medium") return "default";
  return "secondary";
}

function alertIcon(type: string) {
  switch (type) {
    case "fire": return <Flame className="w-3.5 h-3.5" />;
    case "stranger": return <Eye className="w-3.5 h-3.5" />;
    case "intrusion": return <Shield className="w-3.5 h-3.5" />;
    default: return <Zap className="w-3.5 h-3.5" />;
  }
}

function entityIcon(type: string) {
  if (type === "person") return <User className="w-4 h-4" />;
  if (type === "pet") return <Dog className="w-4 h-4" />;
  return <Car className="w-4 h-4" />;
}

function isValidAiCameraId(value: unknown): value is string {
  return typeof value === "string" && value.trim().length > 0;
}

function LiveAiEntityRow({ entity, accent }: { entity: AiEntity; accent: "household" | "neighbor" }) {
  const img = useAuthImage(entity.imageUrl);
  const fallbackClass = accent === "household"
    ? "bg-green-600/10 text-green-700"
    : "bg-blue-600/10 text-blue-700";

  return (
    <div className="px-4 py-2.5 flex items-center gap-3 hover:bg-accent/50 transition-colors">
      <Avatar className="w-9 h-9">
        {img ? <AvatarImage src={img} /> : null}
        <AvatarFallback className={`${fallbackClass} text-xs`}>
          {entityIcon(entity.type)}
        </AvatarFallback>
      </Avatar>
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{entity.name}</p>
        <p className="text-[11px] text-muted-foreground">
          {entity.lastSeen ?? "Never seen"}
          {entity.cameras?.length ? ` · ${entity.cameras.length} cam${entity.cameras.length > 1 ? "s" : ""}` : ""}
        </p>
      </div>
      <Badge variant="secondary" className="text-[10px] px-1.5 py-0 capitalize shrink-0">
        {entity.type}
      </Badge>
    </div>
  );
}

/* ── Component ──────────────────────────────────────────────── */
export default function LiveAI() {
  const [cameras, setCameras] = useState<AiCamera[]>([]);
  const [streams, setStreams] = useState<StreamInfo[]>([]);
  const [alerts, setAlerts] = useState<AiAlert[]>([]);
  const [entities, setEntities] = useState<AiEntity[]>([]);
  const [systemStatus, setSystemStatus] = useState<SystemStatus | null>(null);
  const [streamHealth, setStreamHealth] = useState<Record<string, StreamHealth>>({});
  const [selectedCamera, setSelectedCamera] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [isLive, setIsLive] = useState(false); // true = connected to real AI
  const [webcamEnabled, setWebcamEnabled] = useState(false);
  const [webcamRunning, setWebcamRunning] = useState<boolean | null>(null);
  const [webcamApplying, setWebcamApplying] = useState(false);
  const [webcamWarning, setWebcamWarning] = useState<string | null>(null);

  const fetchWebcamState = useCallback(async () => {
    try {
      const { data } = await api.get("/ai/webcam-state/");
      setWebcamEnabled(Boolean(data?.webcam_enabled));
      setWebcamRunning(typeof data?.runtime?.running === "boolean" ? data.runtime.running : null);
      setWebcamWarning(data?.warning ? String(data.warning) : null);
    } catch {
      setWebcamRunning(null);
    }
  }, []);

  /* ── Fetch data — real AI first, fallback to demo ──────────── */
  const fetchData = useCallback(async () => {
    setLoading(true);
    await fetchWebcamState();

    // Always fetch streams from Django (no AI dependency)
    try {
      const streamRes = await api.get("/streams/");
      const streamData: StreamInfo[] = Array.isArray(streamRes.data) ? streamRes.data : [];
      setStreams(streamData);

      try {
        const healthRes = await api.get("/streams/health/");
        setStreamHealth((healthRes.data ?? {}) as Record<string, StreamHealth>);
      } catch {
        setStreamHealth({});
      }
    } catch {
      setStreams([]);
      setStreamHealth({});
    }

    try {
      const [camRes, alertRes] = await Promise.all([
        api.get("/ai/cameras/"),
        api.get("/ai/alerts/"),
      ]);
      const camData: AiCamera[] = Array.isArray(camRes.data)
        ? camRes.data
        : camRes.data?.cameras ?? [];
      setCameras(camData);
      if (!selectedCamera && camData.length > 0) {
        const firstValid = camData.find((c) => isValidAiCameraId(c.camera_id));
        if (firstValid) setSelectedCamera(firstValid.camera_id);
      }
      const alertData: AiAlert[] = Array.isArray(alertRes.data)
        ? alertRes.data
        : alertRes.data?.alerts ?? [];
      setAlerts(alertData);
      setIsLive(true);

      // Entities: use Django as the source-of-truth (stores thumbnail_url paths that
      // are accessible through /api/ai/enroll_images/... with auth).
      try {
        const entRes = await api.get("/entities/");
        const entData = Array.isArray(entRes.data) ? entRes.data : entRes.data?.results ?? [];
        setEntities(entData.map((e: Record<string, unknown>) => ({
          id: String(e.id ?? ""),
          name: String(e.name ?? "Unknown"),
          type: (e.category === "pet") ? "pet" as const
            : (e.category === "vehicle") ? "vehicle" as const
            : "person" as const,
          group: (e.group as AiEntity["group"]) ?? "household",
          lastSeen: e.last_seen ? String(e.last_seen) : undefined,
          cameras: Array.isArray(e.cameras) ? e.cameras.map(String) : undefined,
          imageUrl: e.thumbnail_url ? String(e.thumbnail_url) : undefined,
        })));
      } catch {
        setEntities(DEMO_ENTITIES);
      }

      // System status
      try {
        const sysRes = await api.get("/ai/system/status/");
        setSystemStatus(sysRes.data);
      } catch {
        /* optional */
      }
    } catch {
      // AI module offline → use demo data
      setCameras(DEMO_CAMERAS);
      setAlerts(DEMO_ALERTS);
      setEntities(DEMO_ENTITIES);
      setSystemStatus(DEMO_SYSTEM);
      setIsLive(false);
      if (!selectedCamera && isValidAiCameraId(DEMO_CAMERAS[0].camera_id)) {
        setSelectedCamera(DEMO_CAMERAS[0].camera_id);
      }
    } finally {
      setLoading(false);
    }
  }, [selectedCamera, fetchWebcamState]);

  const toggleWebcam = useCallback(async () => {
    const nextEnabled = !webcamEnabled;
    setWebcamApplying(true);
    setWebcamWarning(null);
    try {
      const { data } = await api.post("/ai/webcam-state/", { enabled: nextEnabled });
      setWebcamEnabled(Boolean(data?.webcam_enabled));
      setWebcamRunning(typeof data?.runtime?.running === "boolean" ? data.runtime.running : null);
      setWebcamWarning(data?.warning ? String(data.warning) : null);
      await fetchData();
    } catch (err: any) {
      setWebcamWarning(err?.response?.data?.error || "Failed to update webcam runtime state");
    } finally {
      setWebcamApplying(false);
    }
  }, [webcamEnabled, fetchData]);

  useEffect(() => {
    fetchData();
    const iv = setInterval(fetchData, 10_000);
    return () => clearInterval(iv);
  }, [fetchData]);

  /* ── Resolve mapped Django camera for selected AI camera ───── */
  const getMappedStream = useCallback((camId: string): StreamInfo | null => {
    // Match by ai_camera_id or stream_path
    return streams.find(
      (s) => s.ai_camera_id === camId || s.stream_path === camId
    ) ?? null;
  }, [streams]);

  const selectedCam = cameras.find((c) => c.camera_id === selectedCamera);
  const selectedStreamInfo = selectedCamera
    ? getMappedStream(selectedCamera)
    : null;

  /* ── Render ─────────────────────────────────────────────────── */
  return (
    <div className="p-4 sm:p-6 space-y-6">
      {/* ── Header ──────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <Brain className="w-7 h-7 text-primary" />
          <div>
            <h1 className="text-2xl font-bold">Live AI</h1>
            <p className="text-sm text-muted-foreground">
              Real-time AI detection & monitoring
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <Badge
            variant={isLive ? "default" : "secondary"}
            className="gap-1.5 px-3 py-1"
          >
            {isLive ? (
              <Wifi className="w-3.5 h-3.5" />
            ) : (
              <WifiOff className="w-3.5 h-3.5" />
            )}
            {isLive ? "Connected" : "Demo Mode"}
          </Badge>
          <Button variant="outline" size="sm" onClick={fetchData}>
            <RefreshCw className="w-4 h-4 mr-1" />
            Refresh
          </Button>
          <Button
            variant={webcamEnabled ? "destructive" : "default"}
            size="sm"
            onClick={toggleWebcam}
            disabled={webcamApplying}
          >
            {webcamApplying ? "Updating..." : webcamEnabled ? "Disable Webcam" : "Enable Webcam"}
          </Button>
        </div>
      </div>

      <Card>
        <CardContent className="py-3 flex flex-wrap items-center gap-4 text-sm">
          <span>
            <strong>cam_live:</strong> {webcamEnabled ? "Enabled" : "Disabled"}
          </span>
          <span>
            <strong>Runtime:</strong> {webcamRunning === null ? "Unknown" : webcamRunning ? "Running" : "Stopped"}
          </span>
          {webcamWarning && <span className="text-destructive">{webcamWarning}</span>}
        </CardContent>
      </Card>

      {/* ── System status bar ────────────────────────────────────── */}
      {systemStatus && (
        <Card>
          <CardContent className="py-3 flex flex-wrap gap-6 text-sm">
            <span>
              <Activity className="w-4 h-4 inline mr-1 text-primary" />
              <strong>Device:</strong>{" "}
              {typeof systemStatus.device === "object" && systemStatus.device
                ? (systemStatus.device.gpu_name ?? systemStatus.device.torch_device ?? "N/A")
                : (systemStatus.gpu_name ?? String(systemStatus.device ?? "N/A"))}
            </span>
            <span>
              <strong>Active cameras:</strong>{" "}
              {systemStatus.active_cameras ?? systemStatus.cameras?.length ?? cameras.length}
            </span>
            <span>
              <strong>Detection lanes:</strong>{" "}
              {systemStatus.lanes_loaded
                ?? systemStatus.cameras?.reduce((a, c) => a + (c.lanes?.length ?? 0), 0)
                ?? "N/A"}
            </span>
            {(systemStatus.uptime || systemStatus.uptime_seconds != null) && (
              <span>
                <strong>Uptime:</strong>{" "}
                {systemStatus.uptime
                  ?? (systemStatus.uptime_seconds != null
                    ? `${Math.floor(systemStatus.uptime_seconds / 3600)}h ${Math.floor((systemStatus.uptime_seconds % 3600) / 60)}m`
                    : "N/A")}
              </span>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* ── Left column: Camera list ───────────────────────────── */}
        <Card className="lg:col-span-3">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Camera className="w-4 h-4" />
              AI Cameras ({cameras.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ScrollArea className="h-[460px]">
              {loading && cameras.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">Loading…</p>
              ) : cameras.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">
                  No cameras detected by AI module.
                </p>
              ) : (
                <div className="divide-y">
                  {cameras.map((cam) => {
                    const isSelected = selectedCamera === cam.camera_id;
                    const stream = getMappedStream(cam.camera_id);
                    const canUseAiFrame = isValidAiCameraId(cam.camera_id);
                    return (
                      <button
                        key={cam.camera_id}
                        className={`w-full text-left px-3 py-3 hover:bg-accent transition-colors ${
                          isSelected ? "bg-accent ring-2 ring-primary/30" : ""
                        }`}
                        onClick={() => { setSelectedCamera(cam.camera_id); }}
                      >
                        <div className="flex gap-3">
                          {/* Thumbnail */}
                          <div className="w-20 h-14 rounded overflow-hidden bg-muted shrink-0">
                            {stream ? (
                              <AuthedMjpeg
                                cameraId={stream.id}
                                alt={cam.camera_id}
                                className="w-full h-full object-cover"
                                fallback={
                                  <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                                    <Camera className="w-5 h-5" />
                                  </div>
                                }
                              />
                            ) : (
                              canUseAiFrame ? (
                                <AuthImage
                                  src={`/ai/frame/${encodeURIComponent(cam.camera_id)}/`}
                                  alt={cam.camera_id}
                                  className="w-full h-full object-cover"
                                  refreshInterval={15_000}
                                  fallback={
                                    <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                                      <Camera className="w-5 h-5" />
                                    </div>
                                  }
                                />
                              ) : (
                                <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                                  <Camera className="w-5 h-5" />
                                </div>
                              )
                            )}
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center justify-between gap-1">
                              <span className="font-medium text-sm truncate">
                                {cam.camera_id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                              </span>
                              <Badge
                                variant={cam.status === "active" ? "default" : "secondary"}
                                className="text-[10px] px-1.5 py-0 shrink-0"
                              >
                                <Circle
                                  className={`w-1.5 h-1.5 mr-0.5 ${
                                    cam.status === "active"
                                      ? "fill-green-500 text-green-500"
                                      : "fill-gray-400 text-gray-400"
                                  }`}
                                />
                                {cam.status ?? "unknown"}
                              </Badge>
                            </div>
                            {cam.location && (
                              <p className="text-[11px] text-muted-foreground mt-0.5">{cam.location}</p>
                            )}
                            {cam.fps !== undefined && (
                              <p className="text-[11px] text-muted-foreground mt-0.5">
                                {cam.fps.toFixed(1)} FPS
                                {cam.resolution ? ` · ${cam.resolution}` : ""}
                                {cam.active_tracks !== undefined ? ` · ${cam.active_tracks} tracks` : ""}
                              </p>
                            )}
                            <div className="mt-1">
                              <Badge variant={(stream?.source_type === "webcam" || cam.camera_id === "cam_live") ? "secondary" : "outline"} className="text-[10px] px-1.5 py-0">
                                {(stream?.source_type === "webcam" || cam.camera_id === "cam_live") ? "Webcam" : "Registered"}
                              </Badge>
                            </div>
                          </div>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>

        {/* ── Centre: Live feed ──────────────────────────────────── */}
        <Card className="lg:col-span-6">
          <CardHeader className="pb-3">
            <div className="flex items-center justify-between">
              <CardTitle className="text-base">
                {selectedCamera
                  ? `Live Feed — ${selectedCamera.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}`
                  : "Select a Camera"}
              </CardTitle>
              {selectedCam?.status === "active" && (
                <Badge variant="default" className="gap-1 text-xs animate-pulse">
                  <Circle className="w-2 h-2 fill-red-500 text-red-500" />
                  LIVE
                </Badge>
              )}
            </div>
          </CardHeader>
          <CardContent>
            {selectedCamera && isValidAiCameraId(selectedCamera) ? (
              selectedStreamInfo ? (
                <div className="relative">
                  <AuthedMjpeg
                    cameraId={selectedStreamInfo.id}
                    className="w-full rounded-lg border bg-muted aspect-video object-cover"
                    fallback={
                      <div className="aspect-video rounded-lg border bg-muted flex items-center justify-center text-muted-foreground">
                        <div className="text-center">
                          <Camera className="w-12 h-12 mx-auto mb-2 opacity-40" />
                          <p className="text-sm">Warming up stream…</p>
                        </div>
                      </div>
                    }
                  />
                  {/* Overlay info */}
                  <div className="absolute bottom-3 left-3 flex gap-2">
                    <Badge variant="secondary" className="bg-black/60 text-white border-0 text-xs">
                      {selectedCam?.resolution ?? "1920x1080"}
                    </Badge>
                    <Badge variant="secondary" className="bg-black/60 text-white border-0 text-xs">
                      {selectedCam?.fps?.toFixed(1) ?? "—"} FPS
                    </Badge>
                    {(selectedCam?.active_tracks ?? 0) > 0 && (
                      <Badge variant="secondary" className="bg-black/60 text-white border-0 text-xs">
                        {selectedCam?.active_tracks} tracks
                      </Badge>
                    )}
                  </div>
                  <div className="absolute top-3 right-3">
                    <span className="text-[11px] bg-black/60 text-white px-2 py-0.5 rounded">
                      MJPEG
                    </span>
                  </div>
                  {streamHealth[String(selectedStreamInfo.id)] && (
                    <div className="mt-3 text-xs text-muted-foreground">
                      Health: {streamHealth[String(selectedStreamInfo.id)].connected ? "connected" : "warming_up"}
                      {streamHealth[String(selectedStreamInfo.id)].last_error
                        ? ` (${streamHealth[String(selectedStreamInfo.id)].last_error})`
                        : ""}
                    </div>
                  )}
                </div>
              ) : (
                <div className="relative">
                  {/* Always show a preview from AI so the page is usable even without DB mapping. */}
                  <div className="aspect-video rounded-lg border bg-muted overflow-hidden">
                    <AuthImage
                      src={`/ai/frame/${encodeURIComponent(selectedCamera)}/`}
                      alt={`Preview — ${selectedCamera}`}
                      className="w-full h-full object-cover"
                      refreshInterval={1_000}
                      fallback={
                        <div className="w-full h-full flex items-center justify-center text-muted-foreground">
                          <div className="text-center">
                            <Camera className="w-12 h-12 mx-auto mb-2 opacity-40" />
                            <p className="text-sm font-medium">Preview unavailable</p>
                            <p className="text-xs mt-1">AI frame endpoint returned no image.</p>
                          </div>
                        </div>
                      }
                    />
                  </div>
                  <div className="absolute top-3 right-3">
                    <span className="text-[11px] bg-blue-600/80 text-white px-2 py-0.5 rounded">AI preview</span>
                  </div>
                  <div className="mt-3 text-xs text-muted-foreground">
                    Stream mapping not found for this AI camera. To enable browser preview, create a camera in Settings → Cameras
                    and set its <code>ai_camera_id</code> or <code>stream_path</code> to <b>{selectedCamera}</b>.
                  </div>
                </div>
              )
            ) : (
              <div className="aspect-video flex items-center justify-center bg-muted rounded-lg text-muted-foreground">
                <div className="text-center">
                  <Camera className="w-12 h-12 mx-auto mb-2 opacity-40" />
                  <p>Select a camera from the list</p>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        {/* ── Right: Entities ────────────────────────────────────── */}
        <Card className="lg:col-span-3">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <User className="w-4 h-4" />
              Entities ({entities.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ScrollArea className="h-[460px]">
              {entities.length === 0 ? (
                <p className="p-4 text-sm text-muted-foreground">
                  No entities enrolled.
                </p>
              ) : (
                <div className="divide-y">
                  {/* Household */}
                  {entities.filter((e) => e.group === "household").length > 0 && (
                    <>
                      <div className="px-4 py-2 bg-muted/50">
                        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Household</p>
                      </div>
                      {entities
                        .filter((e) => e.group === "household")
                        .map((entity) => (
                          <LiveAiEntityRow key={entity.id} entity={entity} accent="household" />
                        ))}
                    </>
                  )}
                  {/* Neighbors */}
                  {entities.filter((e) => e.group === "neighbor").length > 0 && (
                    <>
                      <div className="px-4 py-2 bg-muted/50">
                        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wider">Neighbors</p>
                      </div>
                      {entities
                        .filter((e) => e.group === "neighbor")
                        .map((entity) => (
                          <LiveAiEntityRow key={entity.id} entity={entity} accent="neighbor" />
                        ))}
                    </>
                  )}
                </div>
              )}
            </ScrollArea>
          </CardContent>
        </Card>
      </div>

      <Separator />

      {/* ── Recent alerts ────────────────────────────────────────── */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base flex items-center gap-2">
            <AlertTriangle className="w-4 h-4" />
            Recent AI Alerts ({alerts.length})
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <ScrollArea className="h-[300px]">
            {alerts.length === 0 ? (
              <p className="p-4 text-sm text-muted-foreground">
                No alerts yet.
              </p>
            ) : (
              <div className="divide-y">
                {alerts.map((alert, i) => (
                  <div
                    key={alert.id ?? i}
                    className="px-4 py-3 flex items-start gap-3 hover:bg-accent/50 transition-colors"
                  >
                    <div className="mt-0.5 shrink-0">
                      <Badge variant={severityVariant(alert.severity)} className="gap-1">
                        {alertIcon(alert.type)}
                        {alert.type}
                      </Badge>
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium truncate">
                        {alert.message ??
                          `${alert.type} detected on ${alert.camera_id}`}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {alert.camera_id.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())}
                        {alert.timestamp
                          ? ` · ${new Date(alert.timestamp).toLocaleString()}`
                          : ""}
                      </p>
                    </div>
                    {alert.evidence?.keyframe && (
                      <AuthImage
                        src={`/ai/evidence/${alert.evidence.keyframe}`}
                        alt="evidence"
                        className="w-16 h-12 object-cover rounded border shrink-0"
                        refreshInterval={0}
                      />
                    )}
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}
