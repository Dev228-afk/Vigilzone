import { useState, useEffect, useCallback, useRef } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback, AvatarImage } from "@/components/ui/avatar";
import { Checkbox } from "@/components/ui/checkbox";
import { Search, Plus, User, Dog, Car, Eye, Edit, Trash2, Upload, Wifi, WifiOff, Camera, X } from "lucide-react";
import { api } from "@/lib/api";
import { useAuthImage } from "@/hooks/use-auth-image";

interface Entity {
  id: string;
  name: string;
  type: "person" | "pet" | "vehicle";
  group: "household" | "neighbor";
  lastSeen?: string;
  cameras?: string[];
  imageUrl?: string;
}

export default function Entities() {
  const [entities, setEntities] = useState<Entity[]>([]);

  const [isLive, setIsLive] = useState(false);
  const [filterType, setFilterType] = useState("all");
  const [filterGroup, setFilterGroup] = useState("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [isAddDialogOpen, setIsAddDialogOpen] = useState(false);
  const [newEntity, setNewEntity] = useState({
    name: "",
    type: "person" as const,
    group: "household" as const,
    notes: "",
    consentObtained: false,
  });

  // ── File upload state ──────────────────────────────────────
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [filePreviews, setFilePreviews] = useState<string[]>([]);

  // ── Webcam capture state ───────────────────────────────────
  const [showWebcam, setShowWebcam] = useState(false);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);

  // Loading / error state for enrollment
  const [enrolling, setEnrolling] = useState(false);
  const [enrollError, setEnrollError] = useState<string | null>(null);

  // Generate previews when files change
  useEffect(() => {
    const urls = selectedFiles.map((f) => URL.createObjectURL(f));
    setFilePreviews(urls);
    return () => urls.forEach((u) => URL.revokeObjectURL(u));
  }, [selectedFiles]);

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    setSelectedFiles((prev) => [...prev, ...files]);
    // Reset input so re-selecting the same file works
    e.target.value = "";
  };

  const removeFile = (idx: number) => {
    setSelectedFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  // ── Webcam helpers ─────────────────────────────────────────
  const startWebcam = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: "user", width: 640, height: 480 } });
      streamRef.current = stream;
      setShowWebcam(true);
      // Wait for videoRef to mount
      setTimeout(() => {
        if (videoRef.current) {
          videoRef.current.srcObject = stream;
          videoRef.current.play();
        }
      }, 100);
    } catch (err) {
      console.error("Webcam access denied:", err);
      setEnrollError("Unable to access webcam. Check browser permissions.");
    }
  };

  const captureFromWebcam = () => {
    if (!videoRef.current) return;
    const canvas = document.createElement("canvas");
    canvas.width = videoRef.current.videoWidth || 640;
    canvas.height = videoRef.current.videoHeight || 480;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.drawImage(videoRef.current, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (blob) {
        const file = new File([blob], `webcam_${Date.now()}.jpg`, { type: "image/jpeg" });
        setSelectedFiles((prev) => [...prev, file]);
      }
    }, "image/jpeg", 0.92);
  };

  const stopWebcam = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setShowWebcam(false);
  };

  // Cleanup webcam on unmount or dialog close
  useEffect(() => {
    return () => {
      streamRef.current?.getTracks().forEach((t) => t.stop());
    };
  }, []);

  /* ── Fetch entities from Django backend ────────────────────── */
  const fetchEntities = useCallback(async () => {
    try {
      const res = await api.get("/entities/");
      const data = Array.isArray(res.data) ? res.data : res.data?.results ?? [];
      const mapped = data.map((e: Record<string, unknown>) => ({
        id: String(e.id ?? ""),
        name: String(e.name ?? "Unknown"),
        type: (e.category === "pet" ? "pet" as const
          : e.category === "vehicle" ? "vehicle" as const
          : "person" as const),
        group: (e.group as Entity["group"]) ?? "household",
        lastSeen: e.last_seen ? new Date(String(e.last_seen)).toLocaleString() : undefined,
        cameras: Array.isArray(e.cameras) ? e.cameras.map(String) : undefined,
        imageUrl: e.thumbnail_url ? String(e.thumbnail_url) : undefined,
      }));
      setEntities(mapped);
      setIsLive(true);
    } catch {
      setEntities([]);
      setIsLive(false);
    }
  }, []);

  useEffect(() => {
    fetchEntities();
  }, [fetchEntities]);

  const filteredEntities = entities.filter(entity => {
    const matchesType = filterType === "all" || entity.type === filterType;
    const matchesGroup = filterGroup === "all" || entity.group === filterGroup;
    const matchesSearch = entity.name.toLowerCase().includes(searchQuery.toLowerCase());
    return matchesType && matchesGroup && matchesSearch;
  });

  const handleAddEntity = async () => {
    setEnrolling(true);
    setEnrollError(null);
    try {
      const fd = new FormData();
      fd.append("name", newEntity.name);
      fd.append("category", newEntity.type);
      fd.append("group", newEntity.group);
      fd.append("notes", newEntity.notes);
      for (const file of selectedFiles) {
        fd.append("files", file);
      }
      await api.post("/entities/", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      await fetchEntities();
    } catch (err: any) {
      const msg = err?.response?.data?.error
        || err?.response?.data?.detail
        || "Failed to enroll entity. Check images and try again.";
      setEnrollError(msg);
      setEnrolling(false);
      return; // don't close dialog on error
    }
    // Cleanup
    stopWebcam();
    setSelectedFiles([]);
    setEnrolling(false);
    setNewEntity({ name: "", type: "person", group: "household", notes: "", consentObtained: false });
    setIsAddDialogOpen(false);
  };

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/entities/${id}/`);
      await fetchEntities();
    } catch {
      console.error("Failed to delete entity");
    }
  };

  const getTypeIcon = (type: string) => {
    if (type === "person") return <User className="w-4 h-4" />;
    if (type === "pet") return <Dog className="w-4 h-4" />;
    return <Car className="w-4 h-4" />;
  };

  const getGroupBadge = (group: string) => {
    if (group === "household") return <Badge className="bg-green-600">Household</Badge>;
    return <Badge variant="secondary">Neighbor</Badge>;
  };

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <h1 className="text-2xl font-bold">Entities</h1>
          <Badge variant={isLive ? "default" : "secondary"} className="gap-1.5">
            {isLive ? <Wifi className="w-3 h-3" /> : <WifiOff className="w-3 h-3" />}
            {isLive ? "Live" : "Demo"}
          </Badge>
        </div>
        
        <Dialog open={isAddDialogOpen} onOpenChange={setIsAddDialogOpen}>
          <DialogTrigger asChild>
            <Button data-testid="button-add-entity">
              <Plus className="w-4 h-4 mr-2" />
              Add Entity
            </Button>
          </DialogTrigger>
          <DialogContent className="max-w-2xl">
            <DialogHeader>
              <DialogTitle>Add New Entity</DialogTitle>
            </DialogHeader>
            <div className="space-y-4 py-4">
              <div className="space-y-2">
                <Label htmlFor="entity-type">Type</Label>
                <Select value={newEntity.type} onValueChange={(value: any) => setNewEntity({ ...newEntity, type: value })}>
                  <SelectTrigger id="entity-type" data-testid="select-entity-type">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="person">Person</SelectItem>
                    <SelectItem value="pet">Pet</SelectItem>
                    <SelectItem value="vehicle">Vehicle</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              
              <div className="space-y-2">
                <Label htmlFor="entity-name">Display Name</Label>
                <Input
                  id="entity-name"
                  placeholder="e.g., John Doe, Bella, Gray SUV"
                  value={newEntity.name}
                  onChange={(e) => setNewEntity({ ...newEntity, name: e.target.value })}
                  data-testid="input-entity-name"
                />
              </div>

              <div className="space-y-2">
                <Label htmlFor="entity-notes">Notes (Optional)</Label>
                <Textarea
                  id="entity-notes"
                  placeholder="Additional information..."
                  value={newEntity.notes}
                  onChange={(e) => setNewEntity({ ...newEntity, notes: e.target.value })}
                  data-testid="input-entity-notes"
                />
              </div>

              <div className="space-y-2">
                <Label>Reference Media</Label>
                <input
                  type="file"
                  ref={fileInputRef}
                  multiple
                  accept="image/*"
                  className="hidden"
                  onChange={handleFileSelect}
                />
                <div className="border-2 border-dashed rounded-lg p-6 text-center">
                  <Upload className="w-8 h-8 mx-auto mb-2 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground mb-1">Drag & drop or click to upload</p>
                  <p className="text-xs text-muted-foreground">Upload 3-5 clear, frontal photos in varied lighting</p>
                  <div className="flex gap-2 justify-center mt-3">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => fileInputRef.current?.click()}
                      data-testid="button-upload-images"
                    >
                      <Upload className="w-3 h-3 mr-1" />
                      Choose Files
                    </Button>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={showWebcam ? captureFromWebcam : startWebcam}
                      data-testid="button-webcam-capture"
                    >
                      <Camera className="w-3 h-3 mr-1" />
                      {showWebcam ? "Capture" : "Webcam"}
                    </Button>
                    {showWebcam && (
                      <Button variant="ghost" size="sm" onClick={stopWebcam}>
                        <X className="w-3 h-3 mr-1" />
                        Close Cam
                      </Button>
                    )}
                  </div>
                </div>

                {/* Webcam preview */}
                {showWebcam && (
                  <div className="rounded-lg overflow-hidden border bg-muted">
                    <video
                      ref={videoRef}
                      autoPlay
                      playsInline
                      muted
                      className="w-full max-h-48 object-contain"
                    />
                  </div>
                )}

                {/* File previews */}
                {filePreviews.length > 0 && (
                  <div className="flex flex-wrap gap-2 mt-2">
                    {filePreviews.map((url, idx) => (
                      <div key={idx} className="relative group">
                        <img
                          src={url}
                          alt={`Preview ${idx + 1}`}
                          className="w-16 h-16 object-cover rounded border"
                        />
                        <button
                          type="button"
                          onClick={() => removeFile(idx)}
                          className="absolute -top-1 -right-1 bg-destructive text-destructive-foreground rounded-full w-4 h-4 flex items-center justify-center text-xs opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                          ×
                        </button>
                      </div>
                    ))}
                    <p className="text-xs text-muted-foreground self-end">
                      {selectedFiles.length} image{selectedFiles.length !== 1 ? "s" : ""} selected
                    </p>
                  </div>
                )}

                {/* Enrollment error */}
                {enrollError && (
                  <p className="text-sm text-destructive mt-1">{enrollError}</p>
                )}
              </div>

              <div className="space-y-2">
                <Label htmlFor="entity-group">Group</Label>
                <Select value={newEntity.group} onValueChange={(value: any) => setNewEntity({ ...newEntity, group: value })}>
                  <SelectTrigger id="entity-group" data-testid="select-entity-group">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="household">Household</SelectItem>
                    <SelectItem value="neighbor">Neighbor</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="flex items-start space-x-2 pt-2">
                <Checkbox
                  id="consent"
                  checked={newEntity.consentObtained}
                  onCheckedChange={(checked) => setNewEntity({ ...newEntity, consentObtained: checked as boolean })}
                  data-testid="checkbox-consent"
                />
                <Label htmlFor="consent" className="text-sm leading-tight cursor-pointer">
                  I have obtained consent to store and use this entity's images for recognition.
                </Label>
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => { stopWebcam(); setSelectedFiles([]); setEnrollError(null); setIsAddDialogOpen(false); }}>Cancel</Button>
              <Button onClick={handleAddEntity} disabled={!newEntity.name || !newEntity.consentObtained || enrolling} data-testid="button-save-entity">
                {enrolling ? "Enrolling…" : "Save Entity"}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>

      <Card className="p-6">
        <div className="flex flex-wrap gap-4 mb-6">
          <div className="flex-1 min-w-[200px]">
            <div className="relative">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 w-4 h-4 text-muted-foreground" />
              <Input
                placeholder="Search entities..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-10"
                data-testid="input-search-entities"
              />
            </div>
          </div>
          <Select value={filterType} onValueChange={setFilterType}>
            <SelectTrigger className="w-[180px]" data-testid="select-filter-type">
              <SelectValue placeholder="Type" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              <SelectItem value="person">Person</SelectItem>
              <SelectItem value="pet">Pet</SelectItem>
              <SelectItem value="vehicle">Vehicle</SelectItem>
            </SelectContent>
          </Select>
          <Select value={filterGroup} onValueChange={setFilterGroup}>
            <SelectTrigger className="w-[180px]" data-testid="select-filter-group">
              <SelectValue placeholder="Group" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Groups</SelectItem>
              <SelectItem value="household">Household</SelectItem>
              <SelectItem value="neighbor">Neighbor</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {filteredEntities.length === 0 ? (
          <div className="text-center py-12">
            <User className="w-16 h-16 mx-auto mb-4 text-muted-foreground" />
            <h3 className="text-lg font-semibold mb-2">No entities yet</h3>
            <p className="text-muted-foreground mb-4">Add family members, pets, or vehicles for smarter alerts.</p>
            <Button onClick={() => setIsAddDialogOpen(true)}>
              <Plus className="w-4 h-4 mr-2" />
              Add Your First Entity
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredEntities.map((entity) => (
              <EntityCard
                key={entity.id}
                entity={entity}
                getTypeIcon={getTypeIcon}
                getGroupBadge={getGroupBadge}
                onDelete={handleDelete}
              />
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

/** Sub-component for entity cards — allows useAuthImage hook per entity */
function EntityCard({
  entity,
  getTypeIcon,
  getGroupBadge,
  onDelete,
}: {
  entity: Entity;
  getTypeIcon: (type: string) => React.ReactNode;
  getGroupBadge: (group: string) => React.ReactNode;
  onDelete: (id: string) => void;
}) {
  const thumbSrc = useAuthImage(entity.imageUrl);

  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <Avatar className="w-12 h-12">
          {thumbSrc && <AvatarImage src={thumbSrc} />}
          <AvatarFallback className="bg-primary/10 text-primary">
            {getTypeIcon(entity.type)}
          </AvatarFallback>
        </Avatar>
        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2">
            <h3 className="font-semibold truncate" data-testid={`text-entity-${entity.id}`}>{entity.name}</h3>
            {getGroupBadge(entity.group)}
          </div>
          <p className="text-xs text-muted-foreground capitalize">{entity.type}</p>
          {entity.lastSeen && (
            <p className="text-xs text-muted-foreground mt-1">Last seen: {entity.lastSeen}</p>
          )}
          {entity.cameras && entity.cameras.length > 0 && (
            <p className="text-xs text-muted-foreground mt-1">Cameras: {entity.cameras.join(", ")}</p>
          )}
        </div>
      </div>
      <div className="flex gap-2 mt-4">
        <Button size="sm" variant="outline" className="flex-1" data-testid={`button-view-${entity.id}`}>
          <Eye className="w-3 h-3 mr-1" />
          View
        </Button>
        <Button size="sm" variant="outline" className="flex-1" data-testid={`button-edit-${entity.id}`}>
          <Edit className="w-3 h-3 mr-1" />
          Edit
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => onDelete(entity.id)}
          data-testid={`button-delete-${entity.id}`}
        >
          <Trash2 className="w-3 h-3" />
        </Button>
      </div>
    </Card>
  );
}
