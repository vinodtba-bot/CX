import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import type { CallRow } from "@/lib/api";
import { cn, fmtDate, fmtDuration } from "@/lib/utils";
import { useAdminQuery } from "./useAdmin";

const sentimentVariant = (s: string | null) =>
  s === "Positive" ? "success" : s === "Negative" ? "destructive" : "secondary";

export default function Calls() {
  const [persona, setPersona] = useState("");
  const [channel, setChannel] = useState("");
  const qs = new URLSearchParams({ limit: "200", ...(persona && { persona }), ...(channel && { channel }) });
  const { data, error } = useAdminQuery<{ results: CallRow[] }>(`/api/v1/admin/calls?${qs}`);

  const Filter = ({ value, set, options }: { value: string; set: (v: string) => void; options: [string, string][] }) => (
    <div className="flex gap-1 rounded-md bg-secondary p-1">
      {options.map(([v, label]) => (
        <button key={v} onClick={() => set(v)} className={cn("rounded px-2.5 py-1 text-xs", value === v ? "bg-background shadow-sm font-medium" : "text-muted-foreground")}>
          {label}
        </button>
      ))}
    </div>
  );

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">Conversations</h1>
      <div className="flex flex-wrap gap-2">
        <Filter value={persona} set={setPersona} options={[["", "All lines"], ["member", "Member"], ["provider", "Provider"]]} />
        <Filter value={channel} set={setChannel} options={[["", "All channels"], ["phone", "Phone"], ["web_call", "Web voice"], ["chat", "Chat"]]} />
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full min-w-[720px] text-sm">
            <thead className="border-b text-left text-xs text-muted-foreground">
              <tr>
                <th className="px-4 py-3 font-medium">Started</th>
                <th className="px-4 py-3 font-medium">Line</th>
                <th className="px-4 py-3 font-medium">Channel</th>
                <th className="px-4 py-3 font-medium">Duration</th>
                <th className="px-4 py-3 font-medium">Verified</th>
                <th className="px-4 py-3 font-medium">Outcome</th>
                <th className="px-4 py-3 font-medium">Sentiment</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {(data?.results ?? []).map((c) => (
                <tr key={c.call_id} className="hover:bg-secondary/50">
                  <td className="px-4 py-3">
                    <Link className="text-primary hover:underline" to={`/admin/calls/${encodeURIComponent(c.call_id)}`}>{fmtDate(c.started_at)}</Link>
                  </td>
                  <td className="px-4 py-3 capitalize">{c.persona ?? "–"}</td>
                  <td className="px-4 py-3">{c.channel}</td>
                  <td className="px-4 py-3 tabular-nums">{fmtDuration(c.duration_ms)}</td>
                  <td className="px-4 py-3">{c.verified ? <Badge variant="success">yes</Badge> : <Badge variant="secondary">no</Badge>}</td>
                  <td className="px-4 py-3">
                    {c.transferred ? <Badge variant="warning">transferred</Badge> : c.call_successful ? <Badge variant="success">resolved</Badge> : <Badge variant="secondary">{c.disconnection_reason ?? "–"}</Badge>}
                  </td>
                  <td className="px-4 py-3"><Badge variant={sentimentVariant(c.sentiment)}>{c.sentiment ?? "–"}</Badge></td>
                </tr>
              ))}
            </tbody>
          </table>
          {data && data.results.length === 0 && <p className="p-6 text-center text-sm text-muted-foreground">No conversations match.</p>}
        </CardContent>
      </Card>
    </div>
  );
}
