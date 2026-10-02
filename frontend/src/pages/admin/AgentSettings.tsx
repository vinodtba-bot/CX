import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { adminFetch, type AgentConfig } from "@/lib/api";
import { useAdminQuery } from "./useAdmin";

export default function AgentSettings() {
  const { data } = useAdminQuery<{ config: AgentConfig }>("/api/v1/admin/agent-config");
  const [cfg, setCfg] = useState<AgentConfig | null>(null);
  const [status, setStatus] = useState<string | null>(null);

  useEffect(() => { if (data) setCfg(data.config); }, [data]);
  if (!cfg) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const set = <K extends keyof AgentConfig>(k: K, v: AgentConfig[K]) => setCfg({ ...cfg, [k]: v });
  const save = async () => {
    setStatus("Saving…");
    try {
      const r = await adminFetch<{ config: AgentConfig }>("/api/v1/admin/agent-config", { method: "PUT", body: JSON.stringify(cfg) });
      setCfg(r.config);
      setStatus("Saved. New conversations use these settings.");
    } catch (e) {
      setStatus(e instanceof Error ? e.message : "Save failed");
    }
  };

  const text = (k: keyof AgentConfig, label: string, hint?: string) => (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={k}>{label}</Label>
      <Input id={k} value={String(cfg[k])} onChange={(e) => set(k, e.target.value as never)} />
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
  const toggle = (k: keyof AgentConfig, label: string, hint: string) => (
    <div className="flex items-start justify-between gap-4">
      <div>
        <Label htmlFor={k} className="text-sm text-foreground">{label}</Label>
        <p className="text-xs text-muted-foreground">{hint}</p>
      </div>
      <Switch id={k} checked={Boolean(cfg[k])} onChange={(v) => set(k, v as never)} />
    </div>
  );

  return (
    <div className="flex max-w-3xl flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold">Agent settings</h1>
        <p className="text-sm text-muted-foreground">Change what the assistants say and may do, without editing prompts. Applies to new conversations.</p>
      </div>
      <Card>
        <CardHeader><CardTitle>Greetings</CardTitle><CardDescription>Use {"{payer_name}"} to insert the plan name.</CardDescription></CardHeader>
        <CardContent className="flex flex-col gap-4">
          {text("payer_name", "Plan name")}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="mg">Member services greeting</Label>
            <Textarea id="mg" value={cfg.member_greeting} onChange={(e) => set("member_greeting", e.target.value)} />
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="pg">Provider services greeting</Label>
            <Textarea id="pg" value={cfg.provider_greeting} onChange={(e) => set("provider_greeting", e.target.value)} />
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Routing and escalation</CardTitle></CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2">
          {text("member_services_transfer_number", "Member services transfer number", "E.164, e.g. +15555550150")}
          {text("provider_services_transfer_number", "Provider services transfer number")}
          {text("nurse_line_number", "Nurse line")}
          {text("business_hours", "Representative hours")}
          <div className="flex flex-col gap-1.5 sm:col-span-2">
            <Label htmlFor="esc">Always transfer for these topics (comma separated)</Label>
            <Input id="esc" value={cfg.escalation_topics.join(", ")} onChange={(e) => set("escalation_topics", e.target.value.split(",").map((s) => s.trim()).filter(Boolean))} />
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader><CardTitle>Capabilities</CardTitle></CardHeader>
        <CardContent className="flex flex-col gap-4">
          {toggle("allow_claim_status", "Claim status", "Let callers check claim status and denial reasons.")}
          {toggle("allow_benefit_checks", "Benefit and procedure checks", "Coverage, cost share and prior auth requirements by CPT code.")}
          {toggle("allow_prior_auth_lookup", "Prior authorization lookup", "Status of existing prior authorizations.")}
          {toggle("disclose_dollar_amounts", "Speak dollar amounts", "Deductible and out-of-pocket figures. Off sends members to the portal for amounts.")}
        </CardContent>
      </Card>
      <div className="flex items-center gap-3">
        <Button onClick={save}>Save settings</Button>
        {status && <span className="text-sm text-muted-foreground">{status}</span>}
      </div>
    </div>
  );
}
