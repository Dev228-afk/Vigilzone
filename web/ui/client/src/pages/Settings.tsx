import { useState, useEffect } from "react";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { useAuth } from "@/auth/AuthProvider";
import { api } from "@/lib/api";
import { queryClient } from "@/lib/queryClient";

interface ProfileData {
  id: number;
  user: string;
  username: string;
  email: string;
  bio: string;
  notify_email: boolean;
  notify_push: boolean;
  notify_sms: boolean;
  alert_sensitivity: string;
  data_retention_days: number;
  audio_detection: boolean;
  blur_faces: boolean;
  consent_required: boolean;
}

export default function Settings() {
  const { user } = useAuth();
  const { toast } = useToast();

  const profileQ = useQuery({
    queryKey: ["profile-me"],
    queryFn: async () => {
      const { data } = await api.get("/profile/me/");
      return data as ProfileData;
    },
    retry: false,
  });

  const saveMut = useMutation({
    mutationFn: async (patch: Partial<ProfileData>) => {
      const { data } = await api.patch("/profile/me/", patch);
      return data;
    },
    onSuccess: () => {
      toast({ title: "Settings saved" });
      queryClient.invalidateQueries({ queryKey: ["profile-me"] });
    },
    onError: () => toast({ title: "Failed to save", variant: "destructive" }),
  });

  const p = profileQ.data;

  /* Local editing state, synced from query */
  const [profile, setProfile] = useState({
    fullName: user?.username || "",
    email: user?.email || "",
    bio: "",
    currentPassword: "",
    newPassword: "",
  });

  const [notifications, setNotifications] = useState({
    email: true, push: true, sms: false,
  });

  const [preferences, setPreferences] = useState({
    alertSensitivity: "medium",
    dataRetention: "60",
    audioDetection: true,
    blurFaces: true,
    consentRequired: true,
  });

  useEffect(() => {
    if (p) {
      setProfile((prev) => ({
        ...prev,
        fullName: p.username || prev.fullName,
        email: p.email || prev.email,
        bio: p.bio || "",
      }));
      setNotifications({ email: p.notify_email, push: p.notify_push, sms: p.notify_sms });
      setPreferences({
        alertSensitivity: p.alert_sensitivity,
        dataRetention: String(p.data_retention_days),
        audioDetection: p.audio_detection,
        blurFaces: p.blur_faces,
        consentRequired: p.consent_required,
      });
    }
  }, [p]);

  const handleSaveProfile = () => {
    saveMut.mutate({ bio: profile.bio });
  };

  const handleSaveNotifications = () => {
    saveMut.mutate({
      notify_email: notifications.email,
      notify_push: notifications.push,
      notify_sms: notifications.sms,
    });
  };

  const handleSavePreferences = () => {
    saveMut.mutate({
      alert_sensitivity: preferences.alertSensitivity,
      data_retention_days: parseInt(preferences.dataRetention, 10),
      audio_detection: preferences.audioDetection,
      blur_faces: preferences.blurFaces,
      consent_required: preferences.consentRequired,
    });
  };

  return (
    <div className="p-6 max-w-4xl mx-auto space-y-6">
      <h1 className="text-2xl font-bold">Settings</h1>
      {profileQ.isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}

      <Tabs defaultValue="profile" className="w-full">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="profile" data-testid="tab-profile">Profile</TabsTrigger>
          <TabsTrigger value="notifications" data-testid="tab-notifications">Notifications</TabsTrigger>
          <TabsTrigger value="privacy" data-testid="tab-privacy">Privacy & Retention</TabsTrigger>
          <TabsTrigger value="system" data-testid="tab-system">System Preferences</TabsTrigger>
        </TabsList>

        {/* ── Profile ─────────────────────────────────────── */}
        <TabsContent value="profile" className="space-y-4 mt-6">
          <Card className="p-6">
            <h2 className="text-lg font-semibold mb-4">Profile Information</h2>
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="fullName">Username</Label>
                <Input id="fullName" value={profile.fullName} disabled data-testid="input-full-name" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input id="email" type="email" value={profile.email} disabled data-testid="input-email" />
              </div>
              <div className="space-y-2">
                <Label htmlFor="bio">Bio</Label>
                <Input
                  id="bio"
                  value={profile.bio}
                  onChange={(e) => setProfile({ ...profile, bio: e.target.value })}
                  placeholder="A short bio…"
                />
              </div>
              <Button onClick={handleSaveProfile} disabled={saveMut.isPending} data-testid="button-save-profile">
                {saveMut.isPending ? "Saving…" : "Save Changes"}
              </Button>
            </div>
          </Card>
        </TabsContent>

        {/* ── Notifications ──────────────────────────────── */}
        <TabsContent value="notifications" className="space-y-4 mt-6">
          <Card className="p-6">
            <h2 className="text-lg font-semibold mb-4">Notification Preferences</h2>
            <div className="space-y-6">
              <div className="flex items-center justify-between">
                <div>
                  <Label htmlFor="email-alerts" className="text-base">Email Alerts</Label>
                  <p className="text-sm text-muted-foreground">Receive alerts via email</p>
                </div>
                <Switch id="email-alerts" checked={notifications.email}
                  onCheckedChange={(checked) => setNotifications({ ...notifications, email: checked })}
                  data-testid="toggle-email" />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <Label htmlFor="push-alerts" className="text-base">Push Notifications</Label>
                  <p className="text-sm text-muted-foreground">Receive push notifications on your device</p>
                </div>
                <Switch id="push-alerts" checked={notifications.push}
                  onCheckedChange={(checked) => setNotifications({ ...notifications, push: checked })}
                  data-testid="toggle-push" />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <Label htmlFor="sms-alerts" className="text-base">SMS Alerts</Label>
                  <p className="text-sm text-muted-foreground">Receive alerts via text message</p>
                </div>
                <Switch id="sms-alerts" checked={notifications.sms}
                  onCheckedChange={(checked) => setNotifications({ ...notifications, sms: checked })}
                  data-testid="toggle-sms" />
              </div>
              <Button onClick={handleSaveNotifications} disabled={saveMut.isPending}>Save Notifications</Button>
            </div>
          </Card>
        </TabsContent>

        {/* ── Privacy & Retention ────────────────────────── */}
        <TabsContent value="privacy" className="space-y-4 mt-6">
          <Card className="p-6">
            <h2 className="text-lg font-semibold mb-4">Privacy & Retention</h2>
            <div className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="retention-period">Data Retention Period</Label>
                <Select value={preferences.dataRetention}
                  onValueChange={(v) => setPreferences({ ...preferences, dataRetention: v })}>
                  <SelectTrigger id="retention-period" data-testid="select-retention-period">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="30">30 days</SelectItem>
                    <SelectItem value="60">60 days</SelectItem>
                    <SelectItem value="90">90 days</SelectItem>
                  </SelectContent>
                </Select>
                <p className="text-sm text-muted-foreground">Footage and incidents older than this will be automatically deleted</p>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <Label className="text-base">Blur Faces for Shared Video</Label>
                  <p className="text-sm text-muted-foreground">Automatically blur faces in community-shared feeds</p>
                </div>
                <Switch checked={preferences.blurFaces}
                  onCheckedChange={(c) => setPreferences({ ...preferences, blurFaces: c })}
                  data-testid="toggle-blur-faces" />
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <Label className="text-base">Entity Consent Management</Label>
                  <p className="text-sm text-muted-foreground">Require consent before storing entity images</p>
                </div>
                <Switch checked={preferences.consentRequired}
                  onCheckedChange={(c) => setPreferences({ ...preferences, consentRequired: c })}
                  data-testid="toggle-consent" />
              </div>
              <Button onClick={handleSavePreferences} disabled={saveMut.isPending}>Save Privacy Settings</Button>
            </div>
          </Card>
        </TabsContent>

        {/* ── System ─────────────────────────────────────── */}
        <TabsContent value="system" className="space-y-4 mt-6">
          <Card className="p-6">
            <h2 className="text-lg font-semibold mb-4">System Preferences</h2>
            <div className="space-y-6">
              <div className="space-y-2">
                <Label htmlFor="sensitivity">Alert Sensitivity</Label>
                <Select value={preferences.alertSensitivity}
                  onValueChange={(v) => setPreferences({ ...preferences, alertSensitivity: v })}>
                  <SelectTrigger id="sensitivity" data-testid="select-sensitivity">
                    <SelectValue placeholder="Select sensitivity" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="low">Low</SelectItem>
                    <SelectItem value="medium">Medium</SelectItem>
                    <SelectItem value="high">High</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="flex items-center justify-between">
                <div>
                  <Label htmlFor="audio-detection" className="text-base">Enable Audio Detection</Label>
                  <p className="text-sm text-muted-foreground">Detect anomalies using audio analysis</p>
                </div>
                <Switch id="audio-detection" checked={preferences.audioDetection}
                  onCheckedChange={(c) => setPreferences({ ...preferences, audioDetection: c })}
                  data-testid="toggle-audio" />
              </div>
              <Button onClick={handleSavePreferences} disabled={saveMut.isPending}>Save System Preferences</Button>
            </div>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
}
