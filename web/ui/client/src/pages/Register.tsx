import { useState } from "react";
import { useLocation } from "wouter";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Shield } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api";
import { login } from "@/lib/auth";
import { setSelectedTenantId } from "@/lib/tenant";
import { queryClient } from "@/lib/queryClient";

export default function Register() {
  const { toast } = useToast();
  const [, setLocation] = useLocation();

  const [email, setEmail] = useState("");
  const [username, setUsername] = useState(""); // keep if your backend needs it
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [loading, setLoading] = useState(false);

  const handleRegister = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password !== confirm) {
      toast({
        title: "Passwords don’t match",
        description: "Please re-enter your password.",
        variant: "destructive",
      });
      return;
    }

    try {
      setLoading(true);

      // Register the user (backend auto-creates tenant + membership)
      await api.post("/auth/register/", { email, username, password });

      // Auto-login immediately so the user never has to re-enter credentials
      await login(username, password);

      // Fetch auth context to pick up the auto-created tenant
      const { data: ctx } = await api.get("/auth/context/");

      if (ctx.tenant) {
        setSelectedTenantId(String(ctx.tenant.id));
        queryClient.invalidateQueries();
        toast({
          title: "Welcome to VigilZone!",
          description: "Your community is ready.",
        });
        setLocation("/dashboard");
      } else {
        // Edge case: tenant wasn't auto-created (flag disabled)
        toast({
          title: "Account created",
          description: "Please select or create a community.",
        });
        setLocation("/select-community");
      }
      return; // exit early — navigation already happened
    } catch (err: any) {
      console.error(err);
      toast({
        title: "Registration failed",
        description: err?.response?.data
          ? JSON.stringify(err.response.data)
          : "Please try again.",
        variant: "destructive",
      });
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen bg-background flex items-center justify-center p-4">
      <Card className="w-full max-w-md p-8">
        <div className="text-center mb-8">
          <div className="flex justify-center mb-4">
            <div className="w-14 h-14 bg-primary/10 rounded-lg flex items-center justify-center">
              <Shield className="w-8 h-8 text-primary" />
            </div>
          </div>
          <h1 className="text-2xl font-bold">Create account</h1>
          <p className="text-muted-foreground mt-2">Join VigilZone</p>
        </div>

        <form onSubmit={handleRegister} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
          </div>

          <div className="space-y-2">
            <Label htmlFor="username">Username</Label>
            <Input id="username" value={username} onChange={(e) => setUsername(e.target.value)} />
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </div>

          <div className="space-y-2">
            <Label htmlFor="confirm">Confirm password</Label>
            <Input id="confirm" type="password" value={confirm} onChange={(e) => setConfirm(e.target.value)} required />
          </div>

          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? "Creating..." : "Create account"}
          </Button>

          <Button type="button" variant="ghost" className="w-full" onClick={() => setLocation("/login")}>
            Back to login
          </Button>
        </form>
      </Card>
    </div>
  );
}