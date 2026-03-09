import { useState } from "react";
import { useLocation } from "wouter";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Shield } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import { api } from "@/lib/api"; // axios client

export default function ForgotPassword() {
  const { toast } = useToast();
  const [, setLocation] = useLocation();

  const [email, setEmail] = useState("");
  const [loading, setLoading] = useState(false);

  const handleForgot = async (e: React.FormEvent) => {
    e.preventDefault();
    try {
      setLoading(true);

      // Adjust endpoint to your Django password reset request endpoint
      // Example: POST /api/auth/password-reset/
      await api.post("/auth/password-reset/", { email });

      toast({
        title: "Check your email",
        description: "If that email exists, we sent reset instructions.",
      });

      setTimeout(() => setLocation("/login"), 1200);
    } catch (err: any) {
      console.error(err);
      toast({
        title: "Request failed",
        description: "Please try again.",
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
          <h1 className="text-2xl font-bold">Forgot password</h1>
          <p className="text-muted-foreground mt-2">
            We’ll email you a reset link.
          </p>
        </div>

        <form onSubmit={handleForgot} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="email">Email</Label>
            <Input
              id="email"
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              required
            />
          </div>

          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? "Sending..." : "Send reset link"}
          </Button>

          <Button type="button" variant="ghost" className="w-full" onClick={() => setLocation("/login")}>
            Back to login
          </Button>
        </form>
      </Card>
    </div>
  );
}