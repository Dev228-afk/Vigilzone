import { useState } from "react";
import { useLocation } from "wouter";
import { useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Search, Eye } from "lucide-react";
import { api } from "@/lib/api";

interface Incident {
  id: number;
  type: string;
  status: string;
  severity: number;
  started_at: string;
  ended_at: string | null;
  camera: number;
  camera_name: string;
  details: Record<string, unknown>;
}

const STATUS_BADGE: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  open: "destructive",
  acknowledged: "secondary",
  resolved: "outline",
};

export default function Incidents() {
  const [, setLocation] = useLocation();
  const [searchQuery, setSearchQuery] = useState("");
  const [filterType, setFilterType] = useState("all");
  const [filterStatus, setFilterStatus] = useState("all");

  const incidentsQ = useQuery({
    queryKey: ["incidents"],
    queryFn: async () => {
      const { data } = await api.get("/incidents/");
      return (Array.isArray(data) ? data : data?.results ?? []) as Incident[];
    },
    retry: false,
  });

  const incidents = incidentsQ.data ?? [];

  const filteredIncidents = incidents.filter((inc) => {
    const matchesSearch =
      inc.type.toLowerCase().includes(searchQuery.toLowerCase()) ||
      (inc.camera_name || "").toLowerCase().includes(searchQuery.toLowerCase()) ||
      String(inc.id).includes(searchQuery);
    const matchesType = filterType === "all" || inc.type === filterType;
    const matchesStatus = filterStatus === "all" || inc.status === filterStatus;
    return matchesSearch && matchesType && matchesStatus;
  });

  const formatTime = (iso: string) => {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffDays = Math.floor(diffMs / 86_400_000);
    const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (diffDays === 0) return `Today, ${time}`;
    if (diffDays === 1) return `Yesterday, ${time}`;
    return `${diffDays}d ago, ${time}`;
  };

  if (incidentsQ.isLoading) return <div className="p-6">Loading incidents…</div>;
  if (incidentsQ.isError) return <div className="p-6 text-destructive">Failed to load incidents.</div>;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Incidents</h1>
      </div>

      <Card className="p-6">
        <div className="flex flex-wrap gap-4 mb-6">
          <div className="flex-1 min-w-[200px]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Search incidents..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10"
                data-testid="input-search-incidents"
              />
            </div>
          </div>
          <Select value={filterType} onValueChange={setFilterType}>
            <SelectTrigger className="w-[180px]" data-testid="select-filter-type">
              <SelectValue placeholder="Type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              <SelectItem value="fire">Fire</SelectItem>
              <SelectItem value="intrusion">Intrusion</SelectItem>
              <SelectItem value="robbery">Robbery</SelectItem>
              <SelectItem value="stranger">Stranger</SelectItem>
              <SelectItem value="other">Other</SelectItem>
            </SelectContent>
          </Select>
          <Select value={filterStatus} onValueChange={setFilterStatus}>
            <SelectTrigger className="w-[180px]" data-testid="select-filter-status">
              <SelectValue placeholder="Status" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Statuses</SelectItem>
              <SelectItem value="open">Open</SelectItem>
              <SelectItem value="acknowledged">Acknowledged</SelectItem>
              <SelectItem value="resolved">Resolved</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>ID</TableHead>
              <TableHead>Type</TableHead>
              <TableHead>Camera</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Severity</TableHead>
              <TableHead>Time</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {filteredIncidents.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                  No incidents found.
                </TableCell>
              </TableRow>
            )}
            {filteredIncidents.map((incident) => (
              <TableRow key={incident.id} className="cursor-pointer hover-elevate" onClick={() => setLocation(`/incidents/${incident.id}`)}>
                <TableCell className="font-medium" data-testid={`text-incident-${incident.id}`}>#{incident.id}</TableCell>
                <TableCell className="capitalize">{incident.type}</TableCell>
                <TableCell>{incident.camera_name || `Camera #${incident.camera}`}</TableCell>
                <TableCell>
                  <Badge variant={STATUS_BADGE[incident.status] ?? "default"} className="capitalize">
                    {incident.status}
                  </Badge>
                </TableCell>
                <TableCell>
                  <span className={incident.severity >= 4 ? "text-red-600 font-semibold" : ""}>
                    {incident.severity}/5
                  </span>
                </TableCell>
                <TableCell className="text-muted-foreground">{formatTime(incident.started_at)}</TableCell>
                <TableCell className="text-right">
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={(e) => { e.stopPropagation(); setLocation(`/incidents/${incident.id}`); }}
                    data-testid={`button-view-${incident.id}`}
                  >
                    <Eye className="w-3 h-3 mr-1" />
                    View
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
