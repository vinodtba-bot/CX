import { Fragment } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, Lock } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import type { CallDetail } from "@/lib/api";
import { cn, fmtDate, fmtDuration } from "@/lib/utils";
import { useAdminQuery } from "./useAdmin";

function Transcript({ text }: { text: string }) {
  return (
    <div className="flex flex-col gap-2">
      {text.split("\n").filter(Boolean).map((line, i) => {
        const m = line.match(/^(Agent|User):\s*(.*)$/);
        const who = m?.[1];
        const body = m ? m[2] : line;
        const parts = body.split(/(\[REDACTED_[A-Z]+\])/g);
        return (
          <div key={i} className={cn("max-w-[85%] rounded-lg px-3 py-2 text-sm", who === "User" ? "self-end bg-primary text-primary-foreground" : "self-start bg-secondary")}>
            {parts.map((p, j) =>
              p.startsWith("[REDACTED_") ? (
                <span key={j} className="mx-0.5 inline-flex items-center gap-1 rounded bg-amber-200 px-1 text-xs font-medium text-amber-900"><Lock className="h-3 w-3" />{p.slice(10, -1).toLowerCase()}</span>
              ) : (
                <span key={j}>{p}</span>
              ),
            )}
          </div>
        );
      })}
    </div>
  );
}

export default function CallDetailPage() {
  const { callId = "" } = useParams();
  const { data: c, error } = useAdminQuery<CallDetail>(`/api/v1/admin/calls/${encodeURIComponent(callId)}`);
  if (error) return <p className="text-sm text-destructive">{error}</p>;
  if (!c) return <p className="text-sm text-muted-foreground">Loading…</p>;

  return (
    <div className="flex flex-col gap-4">
      <Link to="/admin/calls" className="flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"><ArrowLeft className="h-3 w-3" />Conversations</Link>
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="mr-2 text-xl font-semibold capitalize">{c.persona ?? "Unknown"} {c.channel === "chat" ? "chat" : "call"}</h1>
        <Badge variant="outline">{c.channel}</Badge>
        {c.verified ? <Badge variant="success">verified</Badge> : <Badge variant="secondary">not verified</Badge>}
        {c.transferred && <Badge variant="warning">transferred</Badge>}
        {c.sentiment && <Badge variant="secondary">{c.sentiment}</Badge>}
      </div>
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Transcript</CardTitle>
            <CardDescription>Redacted before storage. Viewing this record is written to the audit log.</CardDescription>
          </CardHeader>
          <CardContent>{c.transcript_redacted ? <Transcript text={c.transcript_redacted} /> : <p className="text-sm text-muted-foreground">No transcript.</p>}</CardContent>
        </Card>
        <div className="flex flex-col gap-4">
          <Card>
            <CardHeader><CardTitle>Details</CardTitle></CardHeader>
            <CardContent>
              <dl className="grid grid-cols-2 gap-y-2 text-sm">
                <dt className="text-muted-foreground">Started</dt><dd>{fmtDate(c.started_at)}</dd>
                <dt className="text-muted-foreground">Duration</dt><dd className="tabular-nums">{fmtDuration(c.duration_ms)}</dd>
                <dt className="text-muted-foreground">Ended by</dt><dd>{c.disconnection_reason ?? "–"}</dd>
                <dt className="text-muted-foreground">Resolved</dt><dd>{c.call_successful == null ? "–" : c.call_successful ? "Yes" : "No"}</dd>
                <dt className="text-muted-foreground">Call ID</dt><dd className="truncate font-mono text-xs" title={c.call_id}>{c.call_id}</dd>
              </dl>
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Summary</CardTitle></CardHeader>
            <CardContent className="flex flex-col gap-3 text-sm">
              <p>{c.summary ?? "Not analyzed yet."}</p>
              {c.analysis && (
                <dl className="grid grid-cols-2 gap-y-1 text-xs">
                  {Object.entries(c.analysis).map(([k, v]) => (
                    <Fragment key={k}><dt className="text-muted-foreground">{k.replace(/_/g, " ")}</dt><dd>{String(v)}</dd></Fragment>
                  ))}
                </dl>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader><CardTitle>Backend activity</CardTitle><CardDescription>Tool calls and events for this conversation</CardDescription></CardHeader>
            <CardContent>
              <ol className="flex flex-col gap-2 text-xs">
                {c.events.map((e, i) => (
                  <li key={i} className="flex items-start justify-between gap-2">
                    <div>
                      <div className="font-medium">{e.action}</div>
                      <div className="text-muted-foreground">{new Date(e.ts).toLocaleTimeString()} · {e.actor}{e.latency_ms != null && ` · ${e.latency_ms} ms`}</div>
                    </div>
                    <Badge variant={["ok", "verified", "found"].includes(e.outcome) ? "success" : ["failed", "not_verified", "locked", "core_unavailable"].includes(e.outcome) ? "destructive" : "secondary"}>{e.outcome}</Badge>
                  </li>
                ))}
              </ol>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
