import { Switch, Route, Redirect } from "wouter";
import { queryClient } from "./lib/queryClient";
import { QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/components/ThemeProvider";
import { AuthProvider } from "@/auth/AuthProvider";
import NotFound from "@/pages/not-found";
import Login from "@/pages/Login";
import Dashboard from "@/pages/Dashboard";
import Incidents from "@/pages/Incidents";
import IncidentDetails from "@/pages/IncidentDetails";
import Entities from "@/pages/Entities";
import Community from "@/pages/Community";
import Reports from "@/pages/Reports";
import Cameras from "@/pages/Cameras";    
import Settings from "@/pages/Settings";
import LiveAI from "@/pages/LiveAI";
import Debug from "@/pages/Debug";
import NavBar from "@/components/NavBar";
import Register from "./pages/Register";
import ForgotPassword from "./pages/ForgotPassword";
import SelectCommunity from "./pages/SelectCommunity";
import AuthOnlyRoute from "./components/routing/AuthOnlyRoute";
import TenantOnlyRoute from "./components/routing/TenantOnlyRoute";
import PublicOnlyRoute from "./components/routing/PublicOnlyRoute";
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
  );
}
function App() {
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
