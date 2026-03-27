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
import { useAuth } from "@/auth/AuthProvider";

interface Camera {
  id: number | string;
  name: string;
  site: string;
  status: "active" | "inactive";
  rtsp_url?: string;
  ai_camera_id: string;
  stream_path?: string;
  created_at: string;
  tenant?: number;
}

export default function Cameras() {
  const { toast } = useToast();
  const { atLeast } = useAuth();
  const canManage = atLeast("member");
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [newCamera, setNewCamera] = useState({
    name: "",
    site: "",
    rtsp_url: "",
    ai_camera_id: "",
    stream_path: "",
  });

  const [editCamera, setEditCamera] = useState<Camera | null>(null);
  const [editForm, setEditForm] = useState({
    name: "",
    site: "",
    rtsp_url: "",
    ai_camera_id: "",
    stream_path: "",
    status: "active",
  });

  const camerasQ = useQuery({
    queryKey: ["cameras"],
    queryFn: async () => {
      const { data } = await api.get("/cameras/");
      return (Array.isArray(data) ? data : data?.results ?? []) as Camera[];
    },
    retry: false,
  });

  const addMut = useMutation({
    mutationFn: async (cam: typeof newCamera) => {
      const { data } = await api.post("/cameras/", {
        name: cam.name,
        site: cam.site,
        rtsp_url: cam.rtsp_url,
        ai_camera_id: cam.ai_camera_id,
        stream_path: cam.stream_path,
        status: "active",
      });
      if (cam.rtsp_url && data?.id) {
        try {
          await api.post(`/cameras/${data.id}/sync_to_ai/`, { rtsp_url: cam.rtsp_url });
        } catch {
          // Camera created but AI sync failed; user can retry manually.
        }
      }
      return data;
    },
    onSuccess: () => {
      toast({ title: "Camera added" });
      queryClient.invalidateQueries({ queryKey: ["cameras"] });
      setNewCamera({ name: "", site: "", rtsp_url: "", ai_camera_id: "", stream_path: "" });
      setIsDialogOpen(false);
    },
    onError: () => {
      toast({ title: "Failed to add camera", variant: "destructive" });
    },
  });

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

  const editMut = useMutation({
    mutationFn: async ({ id, ...fields }: { id: number | string; [k: string]: unknown }) => {
      const { data } = await api.patch(`/cameras/${id}/`, fields);
      return data;
    },
    onSuccess: () => {
      toast({ title: "Camera updated" });
      queryClient.invalidateQueries({ queryKey: ["cameras"] });
      setEditCamera(null);
    },
    onError: () => {
      toast({ title: "Failed to update camera", variant: "destructive" });
    },
  });

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

  const openEditModal = (cam: Camera) => {
    setEditCamera(cam);
    setEditForm({
      name: cam.name,
      site: cam.site ?? "",
      rtsp_url: cam.rtsp_url ?? "",
      ai_camera_id: cam.ai_camera_id ?? "",
      stream_path: cam.stream_path ?? "",
      status: cam.status ?? "active",
    });
  };

  const handleAddCamera = () => {
    if (!canManage) return;
    addMut.mutate(newCamera);
  };
  const handleSaveEdit = () => {
    if (!canManage) return;
    if (!editCamera) return;
    editMut.mutate({ id: editCamera.id, ...editForm });
  };

  const handleTestConnection = async () => {
    if (!canManage) return;
    const url = newCamera.rtsp_url.trim();
    if (!url) {
      toast({ title: "No URL", description: "Enter an RTSP URL first.", variant: "destructive" });
      return;
    }
    toast({ title: "Testing…", description: `Checking ${url}` });
    try {
      const { data } = await api.post("/cameras/test_connection/", { rtsp_url: url, timeout_s: 3 });
      if (data.ok) {
        const d = data.details;
        const info = d ? `${d.codec ?? ""} ${d.width ?? ""}x${d.height ?? ""} ${d.fps ?? ""}`.trim() : "";
        toast({ title: "Connection OK", description: `${data.method} — ${data.latency_ms} ms${info ? ` (${info})` : ""}` });
      } else {
        toast({ title: "Connection failed", description: data.error ?? "Unknown error", variant: "destructive" });
      }
    } catch {
      toast({ title: "Test failed", description: "Could not reach backend", variant: "destructive" });
    }
  };

  const cameras: Camera[] = camerasQ.data ?? [];

  if (camerasQ.isLoading) return <div className="p-6">Loading cameras…</div>;
  if (camerasQ.isError) return <div className="p-6 text-destructive">Failed to load cameras.</div>;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-bold">Camera Management</h1>
        {canManage && (
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
                <Input id="camera-name" value={newCamera.name} onChange={(e) => setNewCamera({ ...newCamera, name: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="stream-url">Stream URL</Label>
                <Input id="stream-url" placeholder="rtsp://camera.local/stream" value={newCamera.rtsp_url} onChange={(e) => setNewCamera({ ...newCamera, rtsp_url: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="location">Location / Site</Label>
                <Input id="location" value={newCamera.site} onChange={(e) => setNewCamera({ ...newCamera, site: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="ai-cam-id">AI Camera ID (optional)</Label>
                <Input id="ai-cam-id" value={newCamera.ai_camera_id} onChange={(e) => setNewCamera({ ...newCamera, ai_camera_id: e.target.value })} />
              </div>
              <div className="space-y-2">
                <Label htmlFor="stream-path">Stream Path (optional)</Label>
                <Input id="stream-path" value={newCamera.stream_path} onChange={(e) => setNewCamera({ ...newCamera, stream_path: e.target.value })} />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={handleTestConnection} data-testid="button-test-connection">Test Connection</Button>
              <Button onClick={handleAddCamera} disabled={addMut.isPending} data-testid="button-save-camera">
                {addMut.isPending ? "Saving…" : "Save"}
              </Button>
            </DialogFooter>
            </DialogContent>
          </Dialog>
        )}
      </div>
      {!canManage && (
        <p className="text-sm text-muted-foreground">Viewer role has read-only access to cameras.</p>
      )}

      <Card>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Camera Name</TableHead>
              <TableHead>Location</TableHead>
              <TableHead>AI Camera ID</TableHead>
              <TableHead>Stream Path</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Added On</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {cameras.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="text-center text-muted-foreground py-8">
                  No cameras registered yet. Click "Add Camera" to get started.
                </TableCell>
              </TableRow>
            )}
            {cameras.map((camera) => (
              <TableRow key={camera.id}>
                <TableCell className="font-medium">{camera.name}</TableCell>
                <TableCell>{camera.site || "—"}</TableCell>
                <TableCell>{camera.ai_camera_id ? <Badge variant="outline">{camera.ai_camera_id}</Badge> : "—"}</TableCell>
                <TableCell>{camera.stream_path ? <Badge variant="outline">{camera.stream_path}</Badge> : "—"}</TableCell>
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
                  {canManage ? (
                    <div className="flex justify-end gap-2">
                      <Button size="sm" variant="outline" onClick={() => syncMut.mutate(camera.id)} disabled={syncMut.isPending}>
                        <RefreshCw className="w-3 h-3 mr-1" />
                        Sync AI
                      </Button>
                      <Button size="sm" variant="outline">
                        <Share2 className="w-3 h-3 mr-1" />
                        Share
                      </Button>
                      <Button size="icon" variant="ghost" onClick={() => openEditModal(camera)}>
                        <Edit className="w-4 h-4" />
                      </Button>
                      <Button size="icon" variant="ghost" onClick={() => deleteMut.mutate(camera.id)}>
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  ) : (
                    <span className="text-xs text-muted-foreground">Read-only</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <Dialog open={canManage && !!editCamera} onOpenChange={(open) => { if (!open) setEditCamera(null); }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Edit Camera</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="edit-name">Camera Name</Label>
              <Input id="edit-name" value={editForm.name} onChange={(e) => setEditForm({ ...editForm, name: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-rtsp">Stream URL</Label>
              <Input id="edit-rtsp" placeholder="rtsp://..." value={editForm.rtsp_url} onChange={(e) => setEditForm({ ...editForm, rtsp_url: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-site">Location / Site</Label>
              <Input id="edit-site" value={editForm.site} onChange={(e) => setEditForm({ ...editForm, site: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-ai-id">AI Camera ID</Label>
              <Input id="edit-ai-id" value={editForm.ai_camera_id} onChange={(e) => setEditForm({ ...editForm, ai_camera_id: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-stream-path">Stream Path</Label>
              <Input id="edit-stream-path" value={editForm.stream_path} onChange={(e) => setEditForm({ ...editForm, stream_path: e.target.value })} />
            </div>
            <div className="space-y-2">
              <Label htmlFor="edit-status">Status</Label>
              <Select value={editForm.status} onValueChange={(v) => setEditForm({ ...editForm, status: v })}>
                <SelectTrigger id="edit-status">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="active">Active</SelectItem>
                  <SelectItem value="inactive">Inactive</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            {editCamera && (
              <Button variant="outline" onClick={() => syncMut.mutate(editCamera.id)} disabled={syncMut.isPending}>
                <RefreshCw className="w-3 h-3 mr-1" />
                Sync to AI
              </Button>
            )}
            <Button onClick={handleSaveEdit} disabled={editMut.isPending}>
              {editMut.isPending ? "Saving…" : "Save Changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
