import { useState } from "react";
import { NavLink, Outlet } from "react-router-dom";
import { Activity, LayoutDashboard, LogOut, PhoneCall, ShieldCheck, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { adminToken } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/admin", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/admin/calls", label: "Conversations", icon: PhoneCall },
  { to: "/admin/agent", label: "Agent settings", icon: SlidersHorizontal },
  { to: "/admin/audit", label: "Audit log", icon: ShieldCheck },
];

function Login({ onDone }: { onDone: () => void }) {
  const [token, setToken] = useState("");
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>Payer AI Console</CardTitle>
          <CardDescription>Prototype sign-in with the admin API token from .env. Production uses your SSO provider.</CardDescription>
        </CardHeader>
        <CardContent>
          <form
            className="flex flex-col gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              adminToken.set(token.trim());
              onDone();
            }}
          >
            <Label htmlFor="tok">Admin token</Label>
            <Input id="tok" type="password" value={token} onChange={(e) => setToken(e.target.value)} autoFocus />
            <Button type="submit" disabled={!token.trim()}>Sign in</Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}

export default function AdminLayout() {
  const [authed, setAuthed] = useState(Boolean(adminToken.get()));
  if (!authed) return <Login onDone={() => setAuthed(true)} />;
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="border-b bg-card md:w-56 md:border-b-0 md:border-r">
        <div className="flex items-center gap-2 px-4 py-4">
          <Activity className="h-5 w-5 text-primary" />
          <span className="text-sm font-semibold">Payer AI Console</span>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:pb-4">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              className={({ isActive }) =>
                cn("flex items-center gap-2 rounded-md px-3 py-2 text-sm", isActive ? "bg-accent text-accent-foreground font-medium" : "text-muted-foreground hover:bg-secondary")
              }
            >
              <Icon className="h-4 w-4" />
              {label}
            </NavLink>
          ))}
          <a href="/portal" className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-muted-foreground hover:bg-secondary">
            Portal demo ↗
          </a>
        </nav>
        <div className="hidden px-2 md:block">
          <Button variant="ghost" size="sm" className="w-full justify-start" onClick={() => { adminToken.clear(); setAuthed(false); }}>
            <LogOut className="h-4 w-4" /> Sign out
          </Button>
        </div>
      </aside>
      <main className="flex-1 p-4 md:p-8">
        <Outlet context={{ onAuthError: () => { adminToken.clear(); setAuthed(false); } }} />
      </main>
    </div>
  );
}
