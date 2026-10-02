import { Link } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import type { AuditEvent } from "@/lib/api";
import { fmtDate } from "@/lib/utils";
import { useAdminQuery } from "./useAdmin";

export default function AuditLog() {
  const { data, error } = useAdminQuery<{ results: AuditEvent[] }>("/api/v1/admin/audit?limit=300");
  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold">Audit log</h1>
        <p className="text-sm text-muted-foreground">Every backend lookup, webhook, config change and transcript view. Sensitive arguments are masked.</p>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Card>
        <CardContent className="overflow-x-auto p-0">
          <table className="w-full min-w-[760px] text-xs">
            <thead className="border-b text-left text-muted-foreground">
              <tr>
                <th className="px-4 py-2 font-medium">Time</th>
                <th className="px-4 py-2 font-medium">Actor</th>
                <th className="px-4 py-2 font-medium">Action</th>
                <th className="px-4 py-2 font-medium">Outcome</th>
                <th className="px-4 py-2 font-medium">Conversation</th>
                <th className="px-4 py-2 font-medium">Detail</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {(data?.results ?? []).map((e) => (
                <tr key={e.id}>
                  <td className="whitespace-nowrap px-4 py-2">{fmtDate(e.ts)}</td>
                  <td className="px-4 py-2">{e.actor}</td>
                  <td className="px-4 py-2 font-mono">{e.action}</td>
                  <td className="px-4 py-2">{e.outcome}</td>
                  <td className="px-4 py-2">
                    {e.call_id ? <Link className="font-mono text-primary hover:underline" to={`/admin/calls/${encodeURIComponent(e.call_id)}`}>{e.call_id.slice(0, 18)}</Link> : "–"}
                  </td>
                  <td className="max-w-xs truncate px-4 py-2 font-mono text-muted-foreground" title={JSON.stringify(e.detail)}>{e.detail ? JSON.stringify(e.detail) : ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
    </div>
  );
}
