// Stand-in for a payer's logged-in member/provider portal, showing the widget
// as it would be embedded. In production the portal's own backend signs the
// identity token; here /api/v1/demo/portal-token does it for sample personas.
import { useCallback, useEffect, useState } from "react";
import { Building2, CreditCard, FileText, Stethoscope, User } from "lucide-react";
import PayerAssistant from "@/widget/PayerAssistant";
import { cn } from "@/lib/utils";

type Persona = { key: string; persona: "member" | "provider"; name: string };

const MEMBER_PROMPTS = ["How much of my deductible is left?", "Why was claim CLM-112233 denied?", "Is CPT 70553 covered?", "What prior authorizations do I have?"];
const PROVIDER_PROMPTS = ["Status of claim CLM-334455", "Eligibility for MEM-445566 born 1979-11-02", "Does 73721 need prior auth for MEM-445566 DOB 1979-11-02?", "List my recent claims"];

export default function PortalDemo() {
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [active, setActive] = useState<Persona | null>(null);
  const [token, setToken] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/v1/demo/personas")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error("Demo mode is off"))))
      .then((d) => { setPersonas(d.results); setActive(d.results[0]); })
      .catch((e) => setErr(e.message));
  }, []);

  useEffect(() => {
    if (!active) return;
    setToken(null);
    fetch("/api/v1/demo/portal-token", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ persona_key: active.key }) })
      .then((r) => r.json())
      .then((d) => setToken(d.token));
  }, [active]);

  const getPortalToken = useCallback(() => token ?? "", [token]);
  const isMember = active?.persona === "member";

  return (
    <div className="min-h-screen bg-secondary/40">
      <header className="border-b bg-card">
        <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex items-center gap-2 font-semibold"><Building2 className="h-5 w-5 text-primary" />Acme Health Plan <span className="font-normal text-muted-foreground">{isMember ? "Member Portal" : "Provider Portal"}</span></div>
          <div className="flex flex-wrap items-center gap-2 text-xs">
            <span className="text-muted-foreground">Signed in as (demo):</span>
            {personas.map((p) => (
              <button key={p.key} onClick={() => setActive(p)} className={cn("rounded-full border px-3 py-1", active?.key === p.key ? "border-primary bg-accent font-medium" : "bg-background")}>
                {p.name}
              </button>
            ))}
          </div>
        </div>
      </header>
      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-4 py-8">
        {err && <p className="text-sm text-destructive">{err}</p>}
        <div>
          <h1 className="text-2xl font-semibold">Welcome back{active ? `, ${active.name.split(" ")[0]}` : ""}</h1>
          <p className="text-sm text-muted-foreground">This page imitates a payer portal. The assistant in the corner is the embeddable widget, already aware of who is signed in.</p>
        </div>
        <div className="grid gap-4 sm:grid-cols-3">
          {(isMember
            ? [[CreditCard, "Plan & ID card"], [FileText, "Claims & EOBs"], [User, "Find care"]]
            : [[FileText, "Claim status"], [Stethoscope, "Eligibility & benefits"], [User, "Prior authorizations"]]
          ).map(([Icon, label]) => {
            const I = Icon as typeof CreditCard;
            return (
              <div key={label as string} className="flex items-center gap-3 rounded-lg border bg-card p-4 text-sm"><I className="h-5 w-5 text-primary" />{label as string}</div>
            );
          })}
        </div>
        <div className="rounded-lg border bg-card p-5">
          <h2 className="text-sm font-semibold">Try asking the assistant</h2>
          <ul className="mt-2 list-inside list-disc text-sm text-muted-foreground">
            {(isMember ? MEMBER_PROMPTS : PROVIDER_PROMPTS).map((p) => <li key={p}>{p}</li>)}
          </ul>
        </div>
      </main>
      {token && <PayerAssistant key={token} getPortalToken={getPortalToken} defaultOpen />}
    </div>
  );
}
