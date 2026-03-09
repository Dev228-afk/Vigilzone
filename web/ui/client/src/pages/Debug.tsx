import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import StatsCard from "@/components/StatsCard";
import { Activity, Cpu, Database, Wifi, WifiOff, HardDrive, Clock } from "lucide-react";
import { api } from "@/lib/api";

export default function Debug() {
  const debugQ = useQuery({
    queryKey: ["debug-system"],
    queryFn: async () => {
      const { data } = await api.get("/debug/system/");
      return data as {
        django: { uptime_seconds: number; db_ok: boolean; debug_mode: boolean };
        ai: {
          service: string;
          version: string;
          uptime_seconds: number;
          device: { torch_device?: string; gpu_name?: string; gpu_usable?: boolean };
          cameras: Array<{ camera_id: string; active: boolean; lanes: string[] }>;
          webhooks: number;
          diagnostics: Record<string, unknown>;
        } | null;
        ai_cameras: { cameras?: Array<{ camera_id: string; frame_count: number; fps: number; connected?: boolean; last_error?: string; last_frame_ts?: string }> } | null;
      };
    },
    refetchInterval: 10_000,
    retry: false,
  });

  const d = debugQ.data;
  const ai = d?.ai;
  const django = d?.django;
  const cams = d?.ai_cameras?.cameras ?? ai?.cameras ?? [];

  const djangoUptime = django?.uptime_seconds
    ? `${Math.floor(django.uptime_seconds / 3600)}h ${Math.floor((django.uptime_seconds % 3600) / 60)}m`
    : "N/A";
  const aiUptime = ai?.uptime_seconds
    ? `${Math.floor(ai.uptime_seconds / 3600)}h ${Math.floor((ai.uptime_seconds % 3600) / 60)}m`
    : "N/A";

  const aiDevice = ai?.device;
  const gpuName =
    typeof aiDevice === "object" && aiDevice
      ? aiDevice.gpu_name ?? aiDevice.torch_device ?? "N/A"
      : String(aiDevice ?? "N/A");

  return (
    <div className="p-6 space-y-6">
      <h1 className="text-2xl font-bold">System Debug</h1>

      {debugQ.isLoading && <p className="text-muted-foreground">Loading diagnostics…</p>}
      {debugQ.isError && (
        <p className="text-destructive">Failed to load debug info. Is the backend running?</p>
      )}

      {/* Top stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatsCard title="AI Device" value={gpuName} icon={Cpu} />
        <StatsCard title="AI Uptime" value={aiUptime} icon={Clock} />
        <StatsCard title="Django Uptime" value={djangoUptime} icon={Activity} />
        <StatsCard title="Database" value={django?.db_ok ? "OK" : "Error"} icon={Database} />
      </div>

      {/* AI Service */}
      <Card className="p-5 space-y-3">
        <h2 className="text-lg font-semibold flex items-center gap-2">
          <HardDrive className="w-5 h-5" />
          AI Service
        </h2>
        {ai ? (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
            <div>
              <span className="text-muted-foreground">Service:</span>{" "}
              {ai.service} v{ai.version}
            </div>
            <div>
              <span className="text-muted-foreground">GPU Usable:</span>{" "}
              <Badge variant={aiDevice?.gpu_usable ? "default" : "destructive"}>
                {aiDevice?.gpu_usable ? "Yes" : "No"}
              </Badge>
            </div>
            <div>
              <span className="text-muted-foreground">Webhooks:</span> {ai.webhooks}
            </div>
            <div>
              <span className="text-muted-foreground">Active Cameras:</span>{" "}
              {ai.cameras?.length ?? 0}
            </div>
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">AI service unavailable</p>
        )}
      </Card>

      {/* Camera Health Table */}
      <Card className="p-5 space-y-3">
        <h2 className="text-lg font-semibold">Camera Ingest Health</h2>
        {Array.isArray(cams) && cams.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-muted-foreground">
                  <th className="pb-2 pr-4">Camera</th>
                  <th className="pb-2 pr-4">Connected</th>
                  <th className="pb-2 pr-4">Frames</th>
                  <th className="pb-2 pr-4">FPS</th>
                  <th className="pb-2 pr-4">Lanes</th>
                  <th className="pb-2">Last Error</th>
                </tr>
              </thead>
              <tbody>
                {cams.map((cam: any) => (
                  <tr key={cam.camera_id} className="border-b last:border-0">
                    <td className="py-2 pr-4 font-medium">{cam.camera_id}</td>
                    <td className="py-2 pr-4">
                      {cam.connected !== undefined ? (
                        cam.connected ? (
                          <Wifi className="w-4 h-4 text-green-500 inline" />
                        ) : (
                          <WifiOff className="w-4 h-4 text-red-500 inline" />
                        )
                      ) : cam.active ? (
                        <Wifi className="w-4 h-4 text-green-500 inline" />
                      ) : (
                        <WifiOff className="w-4 h-4 text-red-500 inline" />
                      )}
                    </td>
                    <td className="py-2 pr-4">{cam.frame_count ?? "—"}</td>
                    <td className="py-2 pr-4">{cam.fps != null ? cam.fps.toFixed(1) : "—"}</td>
                    <td className="py-2 pr-4">
                      {cam.lanes
                        ? cam.lanes.length
                        : "—"}
                    </td>
                    <td className="py-2 text-muted-foreground text-xs truncate max-w-[200px]">
                      {cam.last_error || "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-muted-foreground text-sm">No camera data available</p>
        )}
      </Card>

      {/* Django Info */}
      <Card className="p-5 space-y-3">
        <h2 className="text-lg font-semibold">Django Backend</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
          <div>
            <span className="text-muted-foreground">Debug Mode:</span>{" "}
            <Badge variant={django?.debug_mode ? "secondary" : "default"}>
              {django?.debug_mode ? "ON" : "OFF"}
            </Badge>
          </div>
          <div>
            <span className="text-muted-foreground">Database:</span>{" "}
            <Badge variant={django?.db_ok ? "default" : "destructive"}>
              {django?.db_ok ? "Connected" : "Error"}
            </Badge>
          </div>
          <div>
            <span className="text-muted-foreground">Uptime:</span> {djangoUptime}
          </div>
        </div>
      </Card>

      {/* Raw diagnostics */}
      {ai?.diagnostics && Object.keys(ai.diagnostics).length > 0 && (
        <Card className="p-5 space-y-3">
          <h2 className="text-lg font-semibold">AI Diagnostics (raw)</h2>
          <pre className="text-xs bg-muted p-3 rounded overflow-auto max-h-60">
            {JSON.stringify(ai.diagnostics, null, 2)}
          </pre>
        </Card>
      )}
    </div>
  );
}
