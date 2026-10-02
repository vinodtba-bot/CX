import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Link } from "react-router-dom";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { CallRow, Stats } from "@/lib/api";
import { fmtDate, fmtDuration, pct } from "@/lib/utils";
import { useAdminQuery } from "./useAdmin";

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card>
      <CardContent className="p-5">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
        {hint && <div className="mt-1 text-xs text-muted-foreground">{hint}</div>}
      </CardContent>
    </Card>
  );
}

const TOOL_LABELS: Record<string, string> = {
  verify_member_identity: "Verify member",
  verify_provider_identity: "Verify provider",
  get_coverage_and_accumulators: "Coverage & deductible",
  check_member_eligibility: "Patient eligibility",
  check_claim_status: "Claim status",
  check_procedure_coverage: "Procedure coverage",
  get_prior_authorizations: "Prior auths",
  create_service_request: "Service request",
};

export default function Overview() {
  const { data: s, error, reload } = useAdminQuery<Stats>("/api/v1/admin/stats?days=30");
  const { data: calls } = useAdminQuery<{ results: CallRow[] }>("/api/v1/admin/calls?limit=6");

  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!s) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const byDay = Object.entries(s.conversations_by_day).map(([day, n]) => ({ day: day.slice(5), n }));
  const tools = Object.entries(s.tool_usage).map(([t, n]) => ({ tool: TOOL_LABELS[t] ?? t, n }));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Overview</h1>
          <p className="text-sm text-muted-foreground">Last {s.window_days} days across voice and chat.</p>
        </div>
        <Button variant="outline" size="sm" onClick={reload}>Refresh</Button>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Tile label="Conversations" value={String(s.total_conversations)} hint={`${s.by_channel.phone ?? 0} phone · ${s.by_channel.web_call ?? 0} web voice · ${s.by_channel.chat ?? 0} chat`} />
        <Tile label="Containment" value={pct(s.containment_rate)} hint={`${s.transfer_count} transferred to a person`} />
        <Tile label="Avg handle time" value={s.avg_handle_time_seconds ? fmtDuration(s.avg_handle_time_seconds * 1000) : "–"} hint={`${s.total_minutes} billable minutes`} />
        <Tile label="Verified callers" value={pct(s.verified_rate)} hint={`${s.core_system_errors} core system errors`} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader><CardTitle>Conversations per day</CardTitle></CardHeader>
          <CardContent className="h-56">
            <ResponsiveContainer>
              <BarChart data={byDay}>
                <CartesianGrid vertical={false} strokeOpacity={0.15} />
                <XAxis dataKey="day" tickLine={false} axisLine={false} fontSize={12} />
                <YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={12} width={28} />
                <Tooltip cursor={{ fillOpacity: 0.08 }} />
                <Bar isAnimationActive={false} dataKey="n" name="Conversations" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
        <Card>
          <CardHeader><CardTitle>Tool usage</CardTitle><CardDescription>Which backend lookups the agent performed</CardDescription></CardHeader>
          <CardContent className="h-56">
            <ResponsiveContainer>
              <BarChart data={tools} layout="vertical" margin={{ left: 24 }}>
                <XAxis type="number" allowDecimals={false} hide />
                <YAxis type="category" dataKey="tool" tickLine={false} axisLine={false} fontSize={12} width={130} />
                <Tooltip cursor={{ fillOpacity: 0.08 }} />
                <Bar isAnimationActive={false} dataKey="n" name="Calls" fill="hsl(var(--primary))" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <CardTitle>Recent conversations</CardTitle>
          <Link to="/admin/calls" className="text-xs text-primary hover:underline">View all</Link>
        </CardHeader>
        <CardContent className="flex flex-col divide-y">
          {(calls?.results ?? []).map((c) => (
            <Link key={c.call_id} to={`/admin/calls/${encodeURIComponent(c.call_id)}`} className="flex flex-col gap-1 py-3 hover:bg-secondary/50 sm:flex-row sm:items-center sm:gap-4">
              <div className="w-32 shrink-0 text-xs text-muted-foreground">{fmtDate(c.started_at)}</div>
              <div className="flex shrink-0 gap-1">
                <Badge variant="secondary">{c.persona ?? "unknown"}</Badge>
                <Badge variant="outline">{c.channel}</Badge>
                {c.transferred && <Badge variant="warning">transferred</Badge>}
              </div>
              <div className="truncate text-sm">{c.summary ?? "No summary yet"}</div>
            </Link>
          ))}
          {calls && calls.results.length === 0 && (
            <p className="py-6 text-center text-sm text-muted-foreground">No conversations yet. Run scripts/simulate_call.py or open the portal demo.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
