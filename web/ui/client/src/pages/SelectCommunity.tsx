import { useEffect, useState } from "react";
import { useLocation } from "wouter";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useToast } from "@/hooks/use-toast";
import { queryClient } from "@/lib/queryClient";
import { setSelectedTenantId } from "@/lib/tenant";
import { getMyTenants, createTenant } from "@/lib/tenant";
import { getPendingInvites, acceptInvite } from "@/lib/invitations";

export default function SelectCommunity() {
  const { toast } = useToast();
  const [, setLocation] = useLocation();
  const [newName, setNewName] = useState("");

  const tenantsQ = useQuery({ queryKey: ["tenants", "mine"], queryFn: getMyTenants, retry: false });
  const invitesQ = useQuery({
    queryKey: ["invites", "pending"],
    queryFn: getPendingInvites,
    retry: false,
    enabled: (tenantsQ.data?.length ?? 0) === 0, // only when no tenants
  });

  // Auto-select if exactly one tenant
  useEffect(() => {
    const tenants = tenantsQ.data;
    if (!tenants) return;
    if (tenants.length === 1) {
      const t = tenants[0];
      setSelectedTenantId(String(t.id));
      toast({ title: `Selected ${t.name}`, description: "Redirecting…" });
      queryClient.invalidateQueries();
      setLocation("/dashboard");
    }
  }, [tenantsQ.data, setLocation, toast]);

  const acceptMut = useMutation({
    mutationFn: (inviteId: number | string) => acceptInvite(inviteId),
    onSuccess: async () => {
      toast({ title: "Invite accepted", description: "Loading your community…" });
      await queryClient.invalidateQueries({ queryKey: ["tenants", "mine"] });
      await queryClient.invalidateQueries({ queryKey: ["invites", "pending"] });
      // next effect will auto-select if now single tenant, or user can choose
    },
    onError: () => toast({ title: "Failed to accept invite", variant: "destructive" }),
  });

  const createMut = useMutation({
    mutationFn: (name: string) => createTenant(name),
    onSuccess: async (tenant: any) => {
      toast({ title: "Community created", description: "Redirecting…" });
      setSelectedTenantId(String(tenant.id));
      await queryClient.invalidateQueries();
      setLocation("/dashboard");
    },
    onError: () => toast({ title: "Failed to create community", variant: "destructive" }),
  });

  if (tenantsQ.isLoading) {
    return <div className="min-h-screen flex items-center justify-center">Loading…</div>;
  }

  if (tenantsQ.isError) {
    return <div className="min-h-screen flex items-center justify-center">Failed to load communities.</div>;
  }

  const tenants = tenantsQ.data ?? [];

  // If multiple tenants, let them pick
  if (tenants.length > 1) {
    return (
      <div className="min-h-screen flex items-center justify-center p-4">
        <Card className="w-full max-w-md p-6 space-y-4">
          <h1 className="text-xl font-semibold">Select a community</h1>
          <div className="space-y-2">
            {tenants.map((t) => (
              <Button
                key={t.id}
                variant="outline"
                className="w-full justify-between"
                onClick={() => {
                  setSelectedTenantId(String(t.id));
                  queryClient.invalidateQueries();
                  setLocation("/dashboard");
                }}
              >
                <span>{t.name}</span>
                <span className="text-xs text-muted-foreground">{t.role}</span>
              </Button>
            ))}
          </div>
        </Card>
      </div>
    );
  }

  // If zero tenants: show invites + create
  const invites = invitesQ.data ?? [];

  return (
    <div className="min-h-screen flex items-center justify-center p-4">
      <Card className="w-full max-w-md p-6 space-y-4">
        <h1 className="text-xl font-semibold">Join or create a community</h1>

        {invitesQ.isLoading ? (
          <p className="text-sm text-muted-foreground">Checking for invitations…</p>
        ) : invites.length > 0 ? (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">Pending invitations</p>
            {invites.map((inv) => (
              <div key={inv.id} className="flex items-center justify-between border rounded-md p-3">
                <div>
                  <div className="font-medium">{inv.tenant.name}</div>
                  <div className="text-xs text-muted-foreground">Role: {inv.role}</div>
                </div>
                <Button
                  size="sm"
                  onClick={() => acceptMut.mutate(inv.id)}
                  disabled={acceptMut.isPending}
                >
                  Accept
                </Button>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">No invitations found.</p>
        )}

        <div className="border-t pt-4 space-y-2">
          <p className="text-sm font-medium">Create a new community</p>
          <Input
            placeholder="Community name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
          />
          <Button
            className="w-full"
            onClick={() => createMut.mutate(newName)}
            disabled={!newName.trim() || createMut.isPending}
          >
            Create community
          </Button>
        </div>
      </Card>
    </div>
  );
}