import { useEffect, useState } from "react";
import { useLocation } from "wouter";

import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { Shield } from "lucide-react";
import { login } from "@/lib/auth";
import { getUserTenants } from "@/lib/user";
import { useToast } from "@/hooks/use-toast";

export default function Login() {
  const { toast } = useToast();

  const [, setLocation] = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    const token = localStorage.getItem("accessToken");
    if (token) setLocation("/dashboard");
  }, [setLocation]);

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setLoading(true);

      await login(username, password);
      const tenants = await getUserTenants();

      if (Array.isArray(tenants) && tenants.length > 0) {
        toast({
          title: "Welcome back!",
          description: "Redirecting to your dashboard…",
        });
        setTimeout(() => setLocation("/dashboard"), 800);
      } else {
        toast({
          title: "One more step",
          description: "Please select your community.",
        });
        setTimeout(() => setLocation("/select-community"), 800);
      }
    } catch (err) {
      console.error(err);
      toast({
        title: "Login failed",
        description: "Invalid email/username or password.",
        variant: "destructive", // works if your Toast supports it
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
          <h1 className="text-2xl font-bold" data-testid="text-title">
            VigilZone
          </h1>
          <p className="text-muted-foreground mt-2">
            Community Smart Surveillance
          </p>
        </div>

        <form onSubmit={handleLogin} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="username">Username</Label>
            <Input
              id="username"
              type="text"
              placeholder="Enter your username"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              required
              data-testid="input-username"
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="password">Password</Label>
            <Input
              id="password"
              type="password"
              placeholder="Enter your password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              data-testid="input-password"
            />
          </div>

          <div className="flex items-center space-x-2">
            <Checkbox
              id="remember"
              checked={rememberMe}
              onCheckedChange={(checked) => setRememberMe(checked as boolean)}
              data-testid="checkbox-remember"
            />
            <Label
              htmlFor="remember"
              className="text-sm font-normal cursor-pointer"
            >
              Remember me
            </Label>
          </div>

          <Button type="submit" className="w-full" data-testid="button-login">
            Login
          </Button>

          <div className="flex justify-between text-sm">
            <button
              type="button"
              className="text-primary hover-elevate px-1 rounded"
              data-testid="link-register"
              onClick={() => setLocation("/register")}
            >
              Register
            </button>
            <button
              type="button"
              className="text-primary hover-elevate px-1 rounded"
              data-testid="link-forgot-password"
              onClick={() => setLocation("/forgot-password")}
            >
              Forgot password?
            </button>
          </div>
        </form>

        <p className="text-xs text-center text-muted-foreground mt-8">
          All connections are encrypted and private.
        </p>
      </Card>
    </div>
  );
}
