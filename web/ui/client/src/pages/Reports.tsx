import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Download, FileText, Calendar } from "lucide-react";
import { BarChart, Bar, PieChart, Pie, Cell, AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer } from "recharts";
import { api } from "@/lib/api";

const TYPE_COLORS: Record<string, string> = {
  fire: "#EF4444", intrusion: "#F59E0B", robbery: "#F59E0B",
  stranger: "#10B981", violence: "#10B981", crash: "#8B5CF6", other: "#6B7280",
};

const DAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-card border border-border rounded-lg shadow-lg p-3">
        <p className="text-sm font-medium mb-1">{label}</p>
        <p className="text-sm text-primary font-semibold">
          {payload[0].value} {payload[0].dataKey === 'time' ? 'min' : 'incidents'}
        </p>
      </div>
    );
  }
  return null;
};

const CustomPieLabel = ({ cx, cy, midAngle, innerRadius, outerRadius, percentage }: any) => {
  const RADIAN = Math.PI / 180;
  const radius = innerRadius + (outerRadius - innerRadius) * 0.5;
  const x = cx + radius * Math.cos(-midAngle * RADIAN);
  const y = cy + radius * Math.sin(-midAngle * RADIAN);

  return (
    <text x={x} y={y} fill="white" textAnchor={x > cx ? 'start' : 'end'}
      dominantBaseline="central" className="text-xs font-semibold">
      {percentage}
    </text>
  );
};

export default function Reports() {
  const [dateRange, setDateRange] = useState("last-7-days");
  const [incidentType, setIncidentType] = useState("all");

  const statsQ = useQuery({
    queryKey: ["incident-stats"],
    queryFn: async () => {
      const { data } = await api.get("/incidents/stats/");
      return data as {
        today: number; week: number; month: number; total: number;
        type_breakdown: Array<{ type: string; count: number }>;
        per_day: Array<{ day: string; count: number }>;
        status_breakdown: Array<{ status: string; count: number }>;
      };
    },
    retry: false,
  });

  const s = statsQ.data;

  /* ── Incidents per Day ───────────────────────────────────── */
  const incidentsPerDay = (s?.per_day ?? []).map((d) => {
    const date = new Date(d.day);
    return { day: DAY_NAMES[date.getDay()] || d.day, incidents: d.count };
  });

  /* ── Type breakdown pie ──────────────────────────────────── */
  const total = (s?.type_breakdown ?? []).reduce((a, t) => a + t.count, 0) || 1;
  const incidentBreakdown = (s?.type_breakdown ?? []).map((tb) => ({
    name: tb.type.charAt(0).toUpperCase() + tb.type.slice(1),
    value: tb.count,
    color: TYPE_COLORS[tb.type] ?? "#6B7280",
    percentage: `${Math.round((tb.count / total) * 100)}%`,
  }));

  /* ── Response trends (static placeholder until we track ack times) */
  const responseTrends = [
    { month: 'Jan', time: 45 }, { month: 'Feb', time: 38 },
    { month: 'Mar', time: 42 }, { month: 'Apr', time: 35 },
    { month: 'May', time: 32 }, { month: 'Jun', time: 28 },
  ];

  const handleDownloadCSV = () => {
    // Build CSV from incidents
    const rows = incidentsPerDay.map((d) => `${d.day},${d.incidents}`);
    const csv = "Day,Incidents\n" + rows.join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = "incidents_report.csv"; a.click();
    URL.revokeObjectURL(url);
  };

  const handleExportPDF = () => {
    window.print();
  };

  /* ── Key insights (computed from real data) ──────────────── */
  const totalIncidents = s?.total ?? 0;
  const openCount = (s?.status_breakdown ?? []).find((sb) => sb.status === "open")?.count ?? 0;
  const resolvedCount = (s?.status_breakdown ?? []).find((sb) => sb.status === "resolved")?.count ?? 0;
  const topType = (s?.type_breakdown ?? []).sort((a, b) => b.count - a.count)[0];

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Analytics & Reports</h1>

      <Card className="p-6">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2">
            <Calendar className="w-4 h-4 text-muted-foreground" />
            <Select value={dateRange} onValueChange={setDateRange}>
              <SelectTrigger className="w-[180px]" data-testid="select-date-range">
                <SelectValue placeholder="Select date range" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="last-7-days">Last 7 days</SelectItem>
                <SelectItem value="last-30-days">Last 30 days</SelectItem>
                <SelectItem value="last-90-days">Last 90 days</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <Select value={incidentType} onValueChange={setIncidentType}>
            <SelectTrigger className="w-[180px]" data-testid="select-incident-type">
              <SelectValue placeholder="Incident type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              <SelectItem value="fire">Fire</SelectItem>
              <SelectItem value="intrusion">Intrusion</SelectItem>
              <SelectItem value="robbery">Robbery</SelectItem>
              <SelectItem value="stranger">Stranger</SelectItem>
            </SelectContent>
          </Select>

          <div className="ml-auto flex gap-2">
            <Button variant="outline" onClick={handleDownloadCSV} data-testid="button-download-csv">
              <Download className="w-4 h-4 mr-2" />
              Download CSV
            </Button>
            <Button variant="outline" onClick={handleExportPDF} data-testid="button-export-pdf">
              <FileText className="w-4 h-4 mr-2" />
              Export PDF
            </Button>
          </div>
        </div>
      </Card>

      {statsQ.isLoading && <p className="text-muted-foreground">Loading stats…</p>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Bar chart */}
        <Card className="p-6">
          <h2 className="text-lg font-semibold mb-4">Incidents per Day</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={incidentsPerDay} barSize={50}>
              <defs>
                <linearGradient id="barGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="hsl(var(--primary))" stopOpacity={0.95} />
                  <stop offset="100%" stopColor="hsl(var(--primary))" stopOpacity={0.6} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
              <XAxis dataKey="day" stroke="hsl(var(--muted-foreground))" tickLine={false} axisLine={false} />
              <YAxis stroke="hsl(var(--muted-foreground))" tickLine={false} axisLine={false} />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'hsl(var(--muted))', opacity: 0.1 }} />
              <Bar dataKey="incidents" fill="url(#barGradient)" radius={[8, 8, 0, 0]} animationDuration={1000} />
            </BarChart>
          </ResponsiveContainer>
        </Card>

        {/* Pie chart */}
        <Card className="p-6">
          <h2 className="text-lg font-semibold mb-4">Incident Breakdown by Type</h2>
          {incidentBreakdown.length === 0 ? (
            <p className="text-muted-foreground text-sm py-8 text-center">No data yet</p>
          ) : (
            <ResponsiveContainer width="100%" height={300}>
              <PieChart>
                <defs>
                  {incidentBreakdown.map((entry, index) => (
                    <linearGradient key={`gradient-${index}`} id={`gradient-${entry.name}`} x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={entry.color} stopOpacity={0.95} />
                      <stop offset="100%" stopColor={entry.color} stopOpacity={0.75} />
                    </linearGradient>
                  ))}
                </defs>
                <Pie data={incidentBreakdown} cx="50%" cy="50%" labelLine={false}
                  label={(props) => <CustomPieLabel {...props} />}
                  outerRadius={110} innerRadius={60} fill="#8884d8"
                  dataKey="value" paddingAngle={3} animationBegin={0} animationDuration={800}>
                  {incidentBreakdown.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={`url(#gradient-${entry.name})`}
                      stroke="hsl(var(--background))" strokeWidth={2} />
                  ))}
                </Pie>
                <Legend verticalAlign="bottom" height={36} iconType="circle"
                  formatter={(value) => <span className="text-sm">{value}</span>} />
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
          )}
        </Card>
      </div>

      {/* Response time trend */}
      <Card className="p-6">
        <h2 className="text-lg font-semibold mb-4">Response Time Trends</h2>
        <ResponsiveContainer width="100%" height={300}>
          <AreaChart data={responseTrends}>
            <defs>
              <linearGradient id="colorResponse" x1="0" y1="0" x2="0" y2="1">
                <stop offset="5%" stopColor="#10B981" stopOpacity={0.4}/>
                <stop offset="95%" stopColor="#10B981" stopOpacity={0.05}/>
              </linearGradient>
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.3} />
            <XAxis dataKey="month" stroke="hsl(var(--muted-foreground))" tickLine={false} axisLine={false} />
            <YAxis stroke="hsl(var(--muted-foreground))"
              label={{ value: 'Minutes', angle: -90, position: 'insideLeft', style: { fill: 'hsl(var(--muted-foreground))' } }}
              tickLine={false} axisLine={false} />
            <Tooltip content={<CustomTooltip />} />
            <Legend iconType="circle" formatter={() => <span className="text-sm">Avg Response Time</span>} />
            <Area type="monotone" dataKey="time" stroke="#10B981" strokeWidth={3}
              fill="url(#colorResponse)" name="Avg Response Time" animationDuration={1200}
              dot={{ fill: '#10B981', r: 4 }} activeDot={{ r: 6, stroke: '#10B981', strokeWidth: 2 }} />
          </AreaChart>
        </ResponsiveContainer>
      </Card>

      {/* Key insights */}
      <Card className="p-6 bg-muted/50">
        <h3 className="font-semibold mb-2">Key Insights</h3>
        <p className="text-sm text-muted-foreground">
          Total incidents: <strong>{totalIncidents}</strong>.{" "}
          {openCount > 0 && <><strong>{openCount}</strong> still open. </>}
          {resolvedCount > 0 && <><strong>{resolvedCount}</strong> resolved. </>}
          {topType && <>Most common type: <strong className="capitalize">{topType.type}</strong> ({topType.count} incidents). </>}
        </p>
      </Card>
    </div>
  );
}
