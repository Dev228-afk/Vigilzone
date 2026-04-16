import { Switch, Route, Redirect } from "wouter";
import React, { Suspense, useEffect } from "react";
import { queryClient } from "./lib/queryClient";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/components/ThemeProvider";
import { AuthProvider } from "@/auth/AuthProvider";
import { unlockAudio } from "@/lib/audio";

import NavBar from "@/components/NavBar";
import LoadingDisplay from "@/components/LoadingDisplay";
import AuthOnlyRoute from "./components/routing/AuthOnlyRoute";
import TenantOnlyRoute from "./components/routing/TenantOnlyRoute";
import PublicOnlyRoute from "./components/routing/PublicOnlyRoute";

// Lazy-loaded pages
const NotFound = React.lazy(() => import("@/pages/not-found"));
const Login = React.lazy(() => import("@/pages/Login"));
const Register = React.lazy(() => import("@/pages/Register"));
const ForgotPassword = React.lazy(() => import("@/pages/ForgotPassword"));
const Dashboard = React.lazy(() => import("@/pages/Dashboard"));
const Incidents = React.lazy(() => import("@/pages/Incidents"));
const IncidentDetails = React.lazy(() => import("@/pages/IncidentDetails"));
const Entities = React.lazy(() => import("@/pages/Entities"));
const Community = React.lazy(() => import("@/pages/Community"));
const Reports = React.lazy(() => import("@/pages/Reports"));
const Cameras = React.lazy(() => import("@/pages/Cameras"));
const Settings = React.lazy(() => import("@/pages/Settings"));
const LiveAI = React.lazy(() => import("@/pages/LiveAI"));
const Debug = React.lazy(() => import("@/pages/Debug"));
const SelectCommunity = React.lazy(() => import("./pages/SelectCommunity"));

function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-background">
      <NavBar />
      <main>{children}</main>
    </div>
  );
}

function Router() {
  return (
    <Suspense fallback={<LoadingDisplay />}>
      <Switch>
        {/* Redirect root to dashboard */}
        <Route path="/">
          <Redirect to="/dashboard" />
        </Route>
        <PublicOnlyRoute path="/login" component={Login} />
        <PublicOnlyRoute path="/register" component={Register} />
        <PublicOnlyRoute path="/forgot-password" component={ForgotPassword} />

        <Route path="/dashboard">
          <TenantOnlyRoute>
            <AuthenticatedLayout>
              <Dashboard />
            </AuthenticatedLayout>
          </TenantOnlyRoute>
        </Route>
        <Route path="/incidents">
          <TenantOnlyRoute>
            <AuthenticatedLayout>
              <Incidents />
            </AuthenticatedLayout>
          </TenantOnlyRoute>
        </Route>
        <Route path="/incidents/:id">
          <TenantOnlyRoute>
            <AuthenticatedLayout>
              <IncidentDetails />
            </AuthenticatedLayout>
          </TenantOnlyRoute>
        </Route>
        <Route path="/entities">
          <TenantOnlyRoute>
            <AuthenticatedLayout>
              <Entities />
            </AuthenticatedLayout>
          </TenantOnlyRoute>
        </Route>
        <Route path="/community">
          <TenantOnlyRoute>
            <AuthenticatedLayout>
              <Community />
            </AuthenticatedLayout>
          </TenantOnlyRoute>
        </Route>
        <Route path="/select-community">
          <AuthOnlyRoute>
            <AuthenticatedLayout>
              <SelectCommunity />
            </AuthenticatedLayout>
          </AuthOnlyRoute>
        </Route>
        <Route path="/reports">
          <TenantOnlyRoute>
            <AuthenticatedLayout>
              <Reports />
            </AuthenticatedLayout>
          </TenantOnlyRoute>
        </Route>
        <Route path="/cameras">
          <TenantOnlyRoute>
            <AuthenticatedLayout>
              <Cameras />
            </AuthenticatedLayout>
          </TenantOnlyRoute>
        </Route>
        <Route path="/live-ai">
          <TenantOnlyRoute>
            <AuthenticatedLayout>
              <LiveAI />
            </AuthenticatedLayout>
          </TenantOnlyRoute>
        </Route>
        <Route path="/settings">
          <TenantOnlyRoute>
            <AuthenticatedLayout>
              <Settings />
            </AuthenticatedLayout>
          </TenantOnlyRoute>
        </Route>
        <Route path="/debug">
          <TenantOnlyRoute>
            <AuthenticatedLayout>
              <Debug />
            </AuthenticatedLayout>
          </TenantOnlyRoute>
        </Route>
        <Route component={NotFound} />
      </Switch>
    </Suspense>
  );
}
function App() {
  useEffect(() => {
    // High-performance, one-time listener to unlock the Web Audio API on first interaction.
    // This allows background notification sounds for the rest of the session.
    const handleFirstInteraction = () => {
      unlockAudio();
      document.removeEventListener('click', handleFirstInteraction);
      document.removeEventListener('keydown', handleFirstInteraction);
    };

    document.addEventListener('click', handleFirstInteraction);
    document.addEventListener('keydown', handleFirstInteraction);

    return () => {
      document.removeEventListener('click', handleFirstInteraction);
      document.removeEventListener('keydown', handleFirstInteraction);
    };
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeProvider>
        <TooltipProvider>
          <Toaster />
          <AuthProvider>
            <Router />
          </AuthProvider>
        </TooltipProvider>
      </ThemeProvider>
    </QueryClientProvider>
  );
}

export default App;
