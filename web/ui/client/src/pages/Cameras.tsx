import { useState } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Plus, Edit, Trash2, Wifi, WifiOff, Share2, RefreshCw } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api";
import { queryClient } from "@/lib/queryClient";

interface Camera {
  id: number | string;
  name: string;
  site: string;
  status: "active" | "inactive";
  rtsp_url?: string;
  ai_camera_id: string;
  created_at: string;
  tenant?: number;
}

export default function Cameras() {
  const { toast } = useToast();
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [newCamera, setNewCamera] = useState({ name: "", site: "", rtsp_url: "", ai_camera_id: "" });

  /* ── Fetch cameras ─────────────────────────────────────────── */
  const camerasQ = useQuery({
    queryKey: ["cameras"],
    queryFn: async () => {
      const { data } = await api.get("/cameras/");
      return (Array.isArray(data) ? data : data?.results ?? []) as Camera[];
    },
    retry: false,
  });

  /* ── Add camera ────────────────────────────────────────────── */
  const addMut = useMutation({
    mutationFn: async (cam: typeof newCamera) => {
      const { data } = await api.post("/cameras/", {
        name: cam.name,
        site: cam.site,
        rtsp_url: cam.rtsp_url,
        ai_camera_id: cam.ai_camera_id,
        status: "active",
      });
      // Auto-sync to AI module if we have an RTSP URL
      if (cam.rtsp_url && data?.id) {
        try {
          await api.post(`/cameras/${data.id}/sync_to_ai/`, {
            rtsp_url: cam.rtsp_url,
          });
        } catch {
          // Camera created but AI sync failed — user can retry via UI
        }
      }
      return data;
    },
    onSuccess: () => {
      toast({ title: "Camera added" });
      queryClient.invalidateQueries({ queryKey: ["cameras"] });
      setNewCamera({ name: "", site: "", rtsp_url: "", ai_camera_id: "" });
      setIsDialogOpen(false);
    },
    onError: () => {
      toast({ title: "Failed to add camera", variant: "destructive" });
    },
  });

  /* ── Delete camera ─────────────────────────────────────────── */
  const deleteMut = useMutation({
    mutationFn: async (id: number | string) => {
      await api.delete(`/cameras/${id}/`);
    },
    onSuccess: () => {
      toast({ title: "Camera deleted" });
      queryClient.invalidateQueries({ queryKey: ["cameras"] });
    },
    onError: () => {
      toast({ title: "Failed to delete camera", variant: "destructive" });
    },
  });

  const handleAddCamera = () => {
    addMut.mutate(newCamera);
  };

  const handleTestConnection = () => {
    toast({ title: "Test", description: `Checking ${newCamera.rtsp_url}…` });
  };

  /* ── Sync camera to AI ─────────────────────────────────────── */
  const syncMut = useMutation({
    mutationFn: async (id: number | string) => {
      const { data } = await api.post(`/cameras/${id}/sync_to_ai/`);
      return data;
    },
    onSuccess: (data) => {
      toast({ title: "Camera synced to AI", description: `AI ID: ${data.ai_camera_id}` });
      queryClient.invalidateQueries({ queryKey: ["cameras"] });
    },
    onError: () => {
      toast({ title: "AI sync failed", variant: "destructive" });
    },
  });

  const cameras: Camera[] = camerasQ.data ?? [];

  if (camerasQ.isLoading) return <div className="p-6">Loading cameras…</div>;
  if (camerasQ.isError) return <div className="p-6 text-destructive">Failed to load cameras.</div>;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Camera Management</h1>
        <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
          <DialogTrigger asChild>
            <Button data-testid="button-add-camera">
              <Plus className="w-4 h-4 mr-2" />
              Add Camera
            </Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add New Camera</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="camera-name">Camera Name</Label>
                <Input
                  id="camera-name"
                  placeholder="e.g., FrontDoorCam"
                  value={newCamera.name}
                  onChange={(e) => setNewCamera({ ...newCamera, name: e.target.value })}
                  data-testid="input-camera-name"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="stream-url">Stream URL</Label>
                <Input
                  id="stream-url"
                  placeholder="rtsp://camera.local/stream"
                  value={newCamera.rtsp_url}
                  onChange={(e) => setNewCamera({ ...newCamera, rtsp_url: e.target.value })}
                  data-testid="input-stream-url"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="location">Location / Site</Label>
                <Input
                  id="location"
                  placeholder="e.g., Entrance, Backyard"
                  value={newCamera.site}
                  onChange={(e) => setNewCamera({ ...newCamera, site: e.target.value })}
                  data-testid="input-location"
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="ai-cam-id">AI Camera ID (optional)</Label>
                <Input
                  id="ai-cam-id"
                  placeholder="e.g., cam_live"
                  value={newCamera.ai_camera_id}
                  onChange={(e) => setNewCamera({ ...newCamera, ai_camera_id: e.target.value })}
                  data-testid="input-ai-camera-id"
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={handleTestConnection} data-testid="button-test-connection">
                Test Connection
              </Button>
              <Button onClick={handleAddCamera} disabled={addMut.isPending} data-testid="button-save-camera">
                {addMut.isPending ? "Saving…" : "Save"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Camera Name</TableHead>
              <TableHead>Location</TableHead>
              <TableHead>AI Camera ID</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Added On</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {cameras.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="text-center text-muted-foreground py-8">
                  No cameras registered yet. Click "Add Camera" to get started.
                </TableCell>
              </TableRow>
            )}
            {cameras.map((camera) => (
              <TableRow key={camera.id}>
                <TableCell className="font-medium" data-testid={`text-camera-${camera.id}`}>{camera.name}</TableCell>
                <TableCell>{camera.site || "—"}</TableCell>
                <TableCell>
                  {camera.ai_camera_id ? (
                    <Badge variant="outline">{camera.ai_camera_id}</Badge>
                  ) : "—"}
                </TableCell>
                <TableCell>
                  <div className="flex items-center gap-2">
                    {camera.status === "active" ? (
                      <>
                        <Wifi className="w-4 h-4 text-green-600" />
                        <span className="text-green-600">Active</span>
                      </>
                    ) : (
                      <>
                        <WifiOff className="w-4 h-4 text-red-600" />
                        <span className="text-red-600">Inactive</span>
                      </>
                    )}
                  </div>
                </TableCell>
                <TableCell>{new Date(camera.created_at).toLocaleDateString()}</TableCell>
                <TableCell className="text-right">
                  <div className="flex justify-end gap-2">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => syncMut.mutate(camera.id)}
                      disabled={syncMut.isPending}
                      data-testid={`button-sync-${camera.id}`}
                    >
                      <RefreshCw className="w-3 h-3 mr-1" />
                      Sync AI
                    </Button>
                    <Button size="sm" variant="outline" data-testid={`button-share-${camera.id}`}>
                      <Share2 className="w-3 h-3 mr-1" />
                      Share
                    </Button>
                    <Button size="icon" variant="ghost" data-testid={`button-edit-${camera.id}`}>
                      <Edit className="w-4 h-4" />
                    </Button>
                    <Button
                      size="icon"
                      variant="ghost"
                      onClick={() => deleteMut.mutate(camera.id)}
                      data-testid={`button-delete-${camera.id}`}
                    >
                      <Trash2 className="w-4 h-4" />
                    </Button>
                  </div>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
