// Admin API client. The admin token lives in sessionStorage only; production
// replaces it with an OIDC login (Okta / Ping / Entra ID).
const TOKEN_KEY = "payer-admin-token";

export const adminToken = {
  get: () => sessionStorage.getItem(TOKEN_KEY) ?? "",
  set: (t: string) => sessionStorage.setItem(TOKEN_KEY, t),
  clear: () => sessionStorage.removeItem(TOKEN_KEY),
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export async function adminFetch<T>(path: string, init: RequestInit = {}): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", Authorization: `Bearer ${adminToken.get()}`, ...(init.headers ?? {}) },
  });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new ApiError(resp.status, typeof body.detail === "string" ? body.detail : `Request failed (${resp.status})`);
  }
  return resp.json() as Promise<T>;
}

export interface Stats {
  window_days: number;
  total_conversations: number;
  by_channel: Record<string, number>;
  by_persona: Record<string, number>;
  containment_rate: number | null;
  transfer_count: number;
  verified_rate: number | null;
  avg_handle_time_seconds: number | null;
  total_minutes: number;
  conversations_by_day: Record<string, number>;
  tool_usage: Record<string, number>;
  sentiment: Record<string, number>;
  core_system_errors: number;
}

export interface CallRow {
  call_id: string;
  channel: string;
  persona: string | null;
  direction: string | null;
  status: string | null;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  disconnection_reason: string | null;
  verified: boolean;
  transferred: boolean;
  sentiment: string | null;
  call_successful: boolean | null;
  summary: string | null;
  tools_used: string[];
}

export interface AuditEvent {
  id?: number;
  ts: string;
  call_id?: string | null;
  actor: string;
  action: string;
  outcome: string;
  latency_ms: number | null;
  detail: Record<string, unknown> | null;
}

export interface CallDetail extends CallRow {
  transcript_redacted: string | null;
  analysis: Record<string, unknown> | null;
  events: AuditEvent[];
}

export type AgentConfig = {
  payer_name: string;
  member_greeting: string;
  provider_greeting: string;
  business_hours: string;
  member_services_transfer_number: string;
  provider_services_transfer_number: string;
  nurse_line_number: string;
  escalation_topics: string[];
  allow_claim_status: boolean;
  allow_benefit_checks: boolean;
  allow_prior_auth_lookup: boolean;
  disclose_dollar_amounts: boolean;
  plan_year_note: string;
};
