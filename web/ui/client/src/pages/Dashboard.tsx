import { useState } from "react";
import { useLocation } from "wouter";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import CameraFeed from "@/components/CameraFeed";
import AlertCard from "@/components/AlertCard";
import StatsCard from "@/components/StatsCard";
import { Maximize2, Activity, Clock, TrendingUp, User, Dog, Car } from "lucide-react";
import { PieChart, Pie, Cell, ResponsiveContainer, Legend, Tooltip } from "recharts";
import { api } from "@/lib/api";

import frontDoorImg from '@assets/generated_images/Front_door_camera_view_eee34996.png';

const TYPE_COLORS: Record<string, string> = {
  fire: "#EF4444",
  intrusion: "#F59E0B",
  robbery: "#F59E0B",
  violence: "#10B981",
  stranger: "#10B981",
  crash: "#8B5CF6",
  other: "#6B7280",
};

const CustomPieLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, percentage }: any) => {
  const RADIAN = Math.PI / 180;
  const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);

  return (
    <text
      x={x} y={y} fill="white"
      textAnchor={x > cx ? 'start' : 'end'}
      dominantBaseline="central"
      className="text-xs font-semibold"
    >
      {percentage}
    </text>
  );
};

export default function Dashboard() {
  const [, setLocation] = useLocation();
  const [zoneFilter, setZoneFilter] = useState("all");

  /* ── Queries ──────────────────────────────────────────────── */
  const dashboardQ = useQuery({
    queryKey: ["dashboard-summary"],
    queryFn: async () => {
      const { data } = await api.get("/dashboard/summary/");
      return data as {
        cameras: Array<{ id: number; name: string; site: string; status: string; ai_camera_id: string }>;
        stats: { today: number; week: number; month: number };
        recent_incidents: Array<{
          id: number; type: string; status: string; severity: number;
          started_at: string; camera__name: string; details: Record<string, unknown>;
        }>;
        type_breakdown: Array<{ type: string; count: number }>;
        recent_audit: Array<{ id: number; action: string; actor: string; created_at: string }>;
      };
    },
    refetchInterval: 15_000,
    retry: false,
  });

  const entitiesQ = useQuery({
    queryKey: ["ai-entities-dash"],
    queryFn: async () => {
      const { data } = await api.get("/ai/entities/");
      const list = Array.isArray(data) ? data : data?.entities ?? [];
      return list as Array<{ entity_id?: string; id?: string; name?: string; label?: string; category?: string; group?: string }>;
    },
    refetchInterval: 30_000,
    retry: false,
  });

  const healthQ = useQuery({
    queryKey: ["streams-health"],
    queryFn: async () => {
      const { data } = await api.get("/streams/health/");
      return (data ?? {}) as Record<string, {
        connected: boolean;
        last_frame_ts: number | null;
        last_error: string;
        fps_config: number;
        viewers: number;
      }>;
    },
    refetchInterval: 10_000,
    retry: false,
  });

  /* ── Derived data ────────────────────────────────────────── */
  const d = dashboardQ.data;
  const cameras = (d?.cameras ?? []).map((c) => {
    return {
      id: c.id,
      name: c.name,
      location: c.site || "Unknown",
      status: (c.status === "active" ? "active" : "offline") as "active" | "offline",
      ai_camera_id: c.ai_camera_id,
      // Snapshot fallback (auth-protected) — fetched via CameraFeed blob fetch.
      // NOTE: this is relative to axios baseURL ("/api"), so do NOT prefix with /api.
      imageUrl: c.id ? `/streams/${c.id}/snapshot/` : frontDoorImg,
      health: healthQ.data?.[String(c.id)],
    };
  });

  const alerts = (d?.recent_incidents ?? []).slice(0, 5).map((inc) => ({
    id: inc.id,
    type: (inc.type || "other") as "fire" | "intrusion" | "violence" | "crash",
    location: inc.camera__name || "Unknown",
    time: new Date(inc.started_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    entity: (inc.details as any)?.entity_name ?? "Unknown",
    confidence: (inc.details as any)?.confidence ?? 0,
  }));

  const stats = d?.stats ?? { today: 0, week: 0, month: 0 };

  const pieData = (d?.type_breakdown ?? []).map((tb) => {
    const total = (d?.type_breakdown ?? []).reduce((s, t) => s + t.count, 0) || 1;
    return {
      name: tb.type.charAt(0).toUpperCase() + tb.type.slice(1),
      value: tb.count,
      color: TYPE_COLORS[tb.type] ?? "#6B7280",
      percentage: `${Math.round((tb.count / total) * 100)}%`,
    };
  });

  const allEntities = (entitiesQ.data ?? []).map((e) => ({
    name: String(e.name ?? e.label ?? "Unknown"),
    type: (e.category === "pet" ? "pet" : e.category === "vehicle" ? "vehicle" : "person") as "person" | "pet" | "vehicle",
    group: String(e.group ?? "household"),
  }));
  const knownEntities = allEntities.filter((e) => e.group === "household" || e.group === "neighbor").slice(0, 6);

  const communityActivity = (d?.recent_audit ?? []).slice(0, 5).map((a) => ({
    time: new Date(a.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    action: `${a.actor ?? "System"} — ${a.action.replace(/\./g, " ")}`,
  }));

  const getEntityIcon = (type: string) => {
    if (type === "person") return <User className="w-3 h-3" />;
    if (type === "pet") return <Dog className="w-3 h-3" />;
    return <Car className="w-3 h-3" />;
  };

  return (
    <div className="p-6 space-y-6">
      <div className="flex gap-3 flex-wrap">
        <Select value={zoneFilter} onValueChange={setZoneFilter}>
          <SelectTrigger className="w-[180px]" data-testid="select-zone-filter">
            <SelectValue placeholder="Zone" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Zones</SelectItem>
            <SelectItem value="home">Home</SelectItem>
            <SelectItem value="street">Street</SelectItem>
            <SelectItem value="shared">Shared</SelectItem>
          </SelectContent>
        </Select>
        {dashboardQ.isLoading && <span className="text-sm text-muted-foreground self-center">Loading…</span>}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
        {/* Left: Camera feeds */}
        <div className="lg:col-span-4 space-y-4">
          <div>
            <h2 className="text-lg font-semibold mb-4">Live Feeds</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-1 gap-3">
              {(cameras.length > 0 ? cameras : [{ id: 0, name: "No cameras", location: "-", status: "offline" as const, imageUrl: frontDoorImg, health: undefined }]).map((camera, idx) => (
                <CameraFeed
                  key={idx}
                  name={camera.name}
                  location={camera.location}
                  status={camera.status}
                  cameraId={camera.id || undefined}
                  imageUrl={camera.imageUrl}
                  health={camera.health}
                  timestamp={new Date().toLocaleTimeString()}
                />
              ))}
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="outline" className="flex-1" data-testid="button-fullscreen">
              <Maximize2 className="w-4 h-4 mr-2" />
              View Fullscreen
            </Button>
          </div>
        </div>

        {/* Centre: Alerts & stats */}
        <div className="lg:col-span-5 space-y-6">
          <div>
            <h2 className="text-lg font-semibold mb-4">Recent Alerts</h2>
            <div className="space-y-3">
              {alerts.length === 0 && <p className="text-muted-foreground text-sm">No recent incidents.</p>}
              {alerts.map((alert) => (
                <AlertCard
                  key={alert.id}
                  type={alert.type}
                  location={alert.location}
                  time={alert.time}
                  entity={alert.entity}
                  confidence={alert.confidence}
                  onClick={() => setLocation(`/incidents/${alert.id}`)}
                />
              ))}
            </div>
          </div>

          <div>
            <h2 className="text-lg font-semibold mb-4">Incident Summary</h2>
            <div className="grid grid-cols-3 gap-3">
              <StatsCard title="Today" value={String(stats.today)} icon={Activity} />
              <StatsCard title="Week" value={String(stats.week)} icon={Clock} />
              <StatsCard title="Month" value={String(stats.month)} icon={TrendingUp} />
            </div>

            {pieData.length > 0 && (
              <Card className="mt-4 p-4">
                <h3 className="text-sm font-semibold mb-2">Anomaly Type Breakdown</h3>
                <ResponsiveContainer width="100%" height={220}>
                  <PieChart>
                    <defs>
                      {pieData.map((entry, index) => (
                        <linearGradient key={`gradient-${index}`} id={`gradient-${entry.name}`} x1="0" y1="0" x2="0" y2="1">
                          <stop offset="0%" stopColor={entry.color} stopOpacity={0.95} />
                          <stop offset="100%" stopColor={entry.color} stopOpacity={0.75} />
                        </linearGradient>
                      ))}
                    </defs>
                    <Pie data={pieData} cx="50%" cy="50%" labelLine={false}
                      label={(props) => <CustomPieLabel {...props} />}
                      outerRadius={85} innerRadius={45} fill="#8884d8" dataKey="value"
                      paddingAngle={2} animationBegin={0} animationDuration={800}>
                      {pieData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={`url(#gradient-${entry.name})`}
                          stroke="hsl(var(--background))" strokeWidth={2} />
                      ))}
                    </Pie>
                    <Legend verticalAlign="bottom" height={36} iconType="circle"
                      formatter={(value) => <span className="text-xs">{value}</span>} />
                    <Tooltip content={({ active, payload }) => {
                      if (active && payload && payload.length) {
                        return (
                          <div className="bg-card border border-border rounded-lg shadow-lg p-3">
                            <p className="text-sm font-medium">{payload[0].name}</p>
                            <p className="text-sm text-primary font-semibold">{payload[0].value}</p>
                          </div>
                        );
                      }
                      return null;
                    }} />
                  </PieChart>
                </ResponsiveContainer>
              </Card>
            )}
          </div>
        </div>

        {/* Right: Entities, community */}
        <div className="lg:col-span-3 space-y-4">
          <div>
            <h2 className="text-lg font-semibold mb-4">Entities</h2>
            <Card className="p-4">
              <h3 className="text-sm font-semibold mb-3">Known Entities</h3>
              <div className="flex flex-wrap gap-2">
                {knownEntities.length === 0 && <span className="text-xs text-muted-foreground">None enrolled</span>}
                {knownEntities.map((entity, idx) => (
                  <Badge key={idx} variant="secondary" className="gap-1" data-testid={`chip-entity-${idx}`}>
                    {getEntityIcon(entity.type)}
                    {entity.name}
                  </Badge>
                ))}
              </div>
            </Card>
          </div>

          <div>
            <h2 className="text-lg font-semibold mb-4">Community Activity</h2>
            <Card className="p-4">
              <div className="space-y-3">
                {communityActivity.length === 0 && <p className="text-xs text-muted-foreground">No recent activity</p>}
                {communityActivity.map((activity, idx) => (
                  <div key={idx} className="text-sm">
                    <p className="text-muted-foreground text-xs mb-1">{activity.time}</p>
                    <p>{activity.action}</p>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>
      </div>
    </div>
  );
}
