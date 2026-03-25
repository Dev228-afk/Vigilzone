import { useEffect, useState } from "react";
import { useLocation } from "wouter";
import { useMutation, useQuery } from "@tanstack/react-query";
import { motion, AnimatePresence } from "framer-motion";
import { Users, Plus, Mail, Check, Shield, ChevronRight, Loader2, Building2, Sparkles } from "lucide-react";
import { queryClient } from "@/lib/queryClient";
import { getSelectedTenantId, setSelectedTenantId } from "@/lib/tenant";
import { getMyTenants, createTenant } from "@/lib/tenant";
import { getPendingInvites, acceptInvite } from "@/lib/invitations";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/use-toast";

export default function SelectCommunity() {
  const { toast } = useToast();
  const [, setLocation] = useLocation();
  const [newName, setNewName] = useState("");
  const [isCreating, setIsCreating] = useState(false);
  const [acceptingInviteId, setAcceptingInviteId] = useState<number | string | null>(null);

  // If tenant is already selected (e.g. from login), skip straight to dashboard
  useEffect(() => {
    if (getSelectedTenantId()) {
      setLocation("/dashboard");
    }
  }, [setLocation]);

  const tenantsQ = useQuery({ queryKey: ["tenants", "mine"], queryFn: getMyTenants, retry: 1 });
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
      queryClient.invalidateQueries();
      setLocation("/dashboard");
    }
  }, [tenantsQ.data, setLocation]);

  const acceptMut = useMutation({
    mutationFn: (inviteId: number | string) => acceptInvite(inviteId),
    onSuccess: async (data) => {
      setAcceptingInviteId(null);
      toast({
        title: "Invite accepted!",
        description: "You can now access this community.",
      });
      await queryClient.invalidateQueries({ queryKey: ["tenants", "mine"] });
      await queryClient.invalidateQueries({ queryKey: ["invites", "pending"] });
      // Navigate to dashboard with the new tenant
      if (data?.tenant_id) {
        setSelectedTenantId(String(data.tenant_id));
        setLocation("/dashboard");
      }
    },
    onError: (error: any) => {
      console.error("Accept invite error:", error);
      setAcceptingInviteId(null);
      toast({
        title: "Failed to accept invite",
        description: error?.response?.data?.detail || "Please try again.",
        variant: "destructive",
      });
    },
  });

  const createMut = useMutation({
    mutationFn: (name: string) => createTenant(name),
    onSuccess: async (tenant: any) => {
      setSelectedTenantId(String(tenant.id));
      await queryClient.invalidateQueries();
      setLocation("/dashboard");
    },
  });

  const handleCreateCommunity = () => {
    if (!newName.trim()) return;
    setIsCreating(true);
    createMut.mutate(newName);
  };

  if (tenantsQ.isLoading) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background via-background to-muted/20 flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0, scale: 0.95 }}
          animate={{ opacity: 1, scale: 1 }}
          className="w-full max-w-lg"
        >
          <div className="bg-card/80 backdrop-blur-xl rounded-2xl border shadow-2xl p-8 space-y-6">
            <div className="flex justify-center">
              <div className="w-16 h-16 rounded-2xl bg-primary/10 flex items-center justify-center">
                <Loader2 className="w-8 h-8 text-primary animate-spin" />
              </div>
            </div>
            <div className="space-y-3">
              <div className="h-4 bg-muted rounded-full animate-pulse w-3/4 mx-auto" />
              <div className="h-4 bg-muted rounded-full animate-pulse w-1/2 mx-auto" />
            </div>
          </div>
        </motion.div>
      </div>
    );
  }

  if (tenantsQ.isError) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background via-background to-muted/20 flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="w-full max-w-md"
        >
          <div className="bg-card/80 backdrop-blur-xl rounded-2xl border shadow-2xl p-8 text-center space-y-4">
            <div className="w-16 h-16 rounded-2xl bg-destructive/10 flex items-center justify-center mx-auto">
              <Shield className="w-8 h-8 text-destructive" />
            </div>
            <div>
              <h2 className="text-xl font-semibold">Something went wrong</h2>
              <p className="text-sm text-muted-foreground mt-1">Failed to load communities. Please try again.</p>
            </div>
            <div className="flex gap-3 justify-center pt-2">
              <button
                onClick={() => tenantsQ.refetch()}
                className="px-4 py-2 rounded-lg bg-primary text-primary-foreground text-sm font-medium hover:opacity-90 transition-opacity"
              >
                Retry
              </button>
              <button
                onClick={() => setLocation("/login")}
                className="px-4 py-2 rounded-lg border text-sm font-medium hover:bg-muted transition-colors"
              >
                Back to Login
              </button>
            </div>
          </div>
        </motion.div>
      </div>
    );
  }

  const tenants = tenantsQ.data ?? [];

  // If multiple tenants, let them pick
  if (tenants.length > 1) {
    return (
      <div className="min-h-screen bg-gradient-to-br from-background via-background to-muted/20 flex items-center justify-center p-4">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          className="w-full max-w-lg"
        >
          <div className="bg-card/80 backdrop-blur-xl rounded-2xl border shadow-2xl overflow-hidden">
            <div className="bg-gradient-to-r from-primary/20 via-primary/10 to-primary/20 p-6 border-b">
              <div className="flex items-center gap-3">
                <div className="w-12 h-12 rounded-xl bg-primary/20 flex items-center justify-center">
                  <Users className="w-6 h-6 text-primary" />
                </div>
                <div>
                  <h1 className="text-xl font-semibold">Select a Community</h1>
                  <p className="text-sm text-muted-foreground">Choose which community to access</p>
                </div>
              </div>
            </div>
            <div className="p-6 space-y-3">
              <AnimatePresence>
                {tenants.map((t, i) => (
                  <motion.button
                    key={t.id}
                    initial={{ opacity: 0, x: -20 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: 20 }}
                    transition={{ delay: i * 0.1 }}
                    onClick={() => {
                      setSelectedTenantId(String(t.id));
                      queryClient.invalidateQueries();
                      setLocation("/dashboard");
                    }}
                    className="w-full group p-4 rounded-xl border bg-background/50 hover:bg-background hover:border-primary/50 hover:shadow-lg transition-all duration-200 flex items-center justify-between"
                  >
                    <div className="flex items-center gap-3">
                      <div className="w-10 h-10 rounded-lg bg-primary/10 flex items-center justify-center">
                        <Building2 className="w-5 h-5 text-primary" />
                      </div>
                      <div className="text-left">
                        <div className="font-medium">{t.name}</div>
                        <div className="text-xs text-muted-foreground capitalize">{t.role}</div>
                      </div>
                    </div>
                    <ChevronRight className="w-5 h-5 text-muted-foreground group-hover:text-primary group-hover:translate-x-1 transition-all" />
                  </motion.button>
                ))}
              </AnimatePresence>
            </div>
          </div>
        </motion.div>
      </div>
    );
  }

  // If zero tenants: show invites + create
  const invites = invitesQ.data ?? [];

  return (
    <div className="min-h-screen bg-gradient-to-br from-background via-background to-muted/20 flex items-center justify-center p-4">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="w-full max-w-lg"
      >
        <div className="bg-card/80 backdrop-blur-xl rounded-2xl border shadow-2xl overflow-hidden">
          {/* Header */}
          <div className="bg-gradient-to-r from-primary/20 via-primary/10 to-primary/20 p-8 border-b text-center">
            <motion.div
              initial={{ scale: 0.8 }}
              animate={{ scale: 1 }}
              transition={{ delay: 0.2, type: "spring" }}
              className="w-20 h-20 rounded-2xl bg-gradient-to-br from-primary/30 to-primary/10 flex items-center justify-center mx-auto mb-4 shadow-lg shadow-primary/20"
            >
              <Shield className="w-10 h-10 text-primary" />
            </motion.div>
            <motion.h1
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
              className="text-2xl font-bold"
            >
              Welcome to VigilZone
            </motion.h1>
            <motion.p
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.4 }}
              className="text-muted-foreground mt-2"
            >
              Join a community or create your own
            </motion.p>
          </div>

          <div className="p-6 space-y-6">
            {/* Invitations Section */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.5 }}
            >
              {invitesQ.isLoading ? (
                <div className="space-y-3">
                  <div className="h-4 bg-muted rounded-full animate-pulse w-32" />
                  <div className="space-y-2">
                    {[1, 2].map((i) => (
                      <div key={i} className="h-20 bg-muted/50 rounded-xl animate-pulse" />
                    ))}
                  </div>
                </div>
              ) : invites.length > 0 ? (
                <div className="space-y-4">
                  <div className="flex items-center gap-2 text-sm font-medium">
                    <Mail className="w-4 h-4 text-primary" />
                    <span>Pending Invitations</span>
                    <span className="ml-auto text-xs bg-primary/10 text-primary px-2 py-0.5 rounded-full">
                      {invites.length}
                    </span>
                  </div>
                  <div className="space-y-3">
                    {invites.map((inv) => (
                      <div
                        key={inv.id}
                        className="relative rounded-xl border bg-gradient-to-r from-background to-muted/20 hover:border-green-500/50 transition-all duration-200 overflow-hidden"
                      >
                        <div className="p-4 flex items-center justify-between relative z-10">
                          <div className="flex items-center gap-3">
                            <div className="w-12 h-12 rounded-xl bg-gradient-to-br from-green-500/20 to-green-500/5 flex items-center justify-center">
                              <Users className="w-6 h-6 text-green-600" />
                            </div>
                            <div>
                              <div className="font-medium">{inv.tenant.name}</div>
                              <div className="text-xs text-muted-foreground flex items-center gap-1">
                                <span className="capitalize px-1.5 py-0.5 bg-muted rounded text-[10px] font-medium">
                                  {inv.role}
                                </span>
                                <span>invited you</span>
                              </div>
                            </div>
                          </div>
                          <button
                            onClick={() => {
                              console.log("Accepting invite:", inv.id);
                              setAcceptingInviteId(inv.id);
                              acceptMut.mutate(inv.id);
                            }}
                            disabled={acceptMut.isPending}
                            className={cn(
                              "px-4 py-2 rounded-lg text-sm font-medium transition-all duration-200 z-20 relative",
                              "bg-gradient-to-r from-green-500 to-green-600 text-white",
                              "hover:shadow-lg hover:shadow-green-500/25 hover:-translate-y-0.5",
                              "active:translate-y-0",
                              "disabled:opacity-50 disabled:cursor-not-allowed"
                            )}
                          >
                            {acceptMut.isPending ? (
                              <Loader2 className="w-4 h-4 animate-spin" />
                            ) : (
                              <span className="flex items-center gap-1">
                                <Check className="w-4 h-4" />
                                Accept
                              </span>
                            )}
                          </button>
                        </div>
                        <div className="absolute inset-0 bg-gradient-to-r from-green-500/5 to-transparent opacity-0 hover:opacity-100 transition-opacity pointer-events-none" />
                      </div>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="text-center py-6 px-4 rounded-xl bg-muted/30 border border-dashed">
                  <div className="w-12 h-12 rounded-xl bg-muted flex items-center justify-center mx-auto mb-3">
                    <Mail className="w-6 h-6 text-muted-foreground" />
                  </div>
                  <p className="text-sm text-muted-foreground">No pending invitations</p>
                  <p className="text-xs text-muted-foreground/70 mt-1">
                    Create a community or ask someone to invite you
                  </p>
                </div>
              )}
            </motion.div>

            {/* Divider */}
            <div className="flex items-center gap-4">
              <div className="flex-1 h-px bg-gradient-to-r from-transparent via-border to-transparent" />
              <span className="text-xs text-muted-foreground font-medium">OR</span>
              <div className="flex-1 h-px bg-gradient-to-r from-transparent via-border to-transparent" />
            </div>

            {/* Create Community Section */}
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.6 }}
              className="space-y-4"
            >
              <div className="flex items-center gap-2 text-sm font-medium">
                <Sparkles className="w-4 h-4 text-primary" />
                <span>Create a New Community</span>
              </div>

              <div className="space-y-3">
                <div className="relative group">
                  <div className="absolute -inset-0.5 bg-gradient-to-r from-primary/50 to-primary/30 rounded-xl blur opacity-0 group-focus-within:opacity-100 transition duration-300" />
                  <div className="relative">
                    <input
                      type="text"
                      placeholder="Enter community name..."
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      onKeyDown={(e) => e.key === "Enter" && handleCreateCommunity()}
                      disabled={createMut.isPending}
                      className={cn(
                        "w-full px-4 py-3 rounded-xl border bg-background/80 text-sm",
                        "placeholder:text-muted-foreground/50",
                        "focus:outline-none focus:ring-2 focus:ring-primary/50 focus:border-primary",
                        "disabled:opacity-50 disabled:cursor-not-allowed",
                        "transition-all duration-200"
                      )}
                    />
                  </div>
                </div>

                <button
                  onClick={handleCreateCommunity}
                  disabled={!newName.trim() || createMut.isPending}
                  className={cn(
                    "w-full py-3 rounded-xl text-sm font-medium transition-all duration-200 flex items-center justify-center gap-2",
                    "bg-gradient-to-r from-primary to-primary/90 text-primary-foreground",
                    "shadow-lg shadow-primary/25 hover:shadow-xl hover:shadow-primary/30 hover:-translate-y-0.5",
                    "active:translate-y-0",
                    "disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:translate-y-0 disabled:hover:shadow-lg disabled:hover:shadow-primary/25"
                  )}
                >
                  {createMut.isPending ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      <span>Creating...</span>
                    </>
                  ) : (
                    <>
                      <Plus className="w-4 h-4" />
                      <span>Create Community</span>
                    </>
                  )}
                </button>
              </div>
            </motion.div>
          </div>

          {/* Footer */}
          <div className="px-6 py-4 bg-muted/30 border-t text-center">
            <p className="text-xs text-muted-foreground">
              Need help?{" "}
              <a href="#" className="text-primary hover:underline">
                Contact Support
              </a>
            </p>
          </div>
        </div>
      </motion.div>
    </div>
  );
}
