import { useCallback, useEffect, useRef, useState } from "react";
import { RetellClient, type WebCallSession } from "retell-client-js-sdk";
import { MessageSquare, Mic, MicOff, PhoneOff, Send, X } from "lucide-react";
import { cn } from "@/lib/utils";

export interface PayerAssistantProps {
  /** Base URL of the middleware, e.g. https://ai.payer.example. Empty = same origin. */
  apiBase?: string;
  /** Returns the portal's signed identity token for the logged-in user. */
  getPortalToken: () => Promise<string> | string;
  /** Start opened (useful for demos). */
  defaultOpen?: boolean;
}

interface WidgetConfig {
  payer_name: string;
  persona: "member" | "provider";
  voice_enabled: boolean;
  chat_mode: "retell" | "simulated" | "disabled";
}

type Msg = { role: "agent" | "user"; content: string };

export default function PayerAssistant({ apiBase = "", getPortalToken, defaultOpen = false }: PayerAssistantProps) {
  const [open, setOpen] = useState(defaultOpen);
  const [tab, setTab] = useState<"chat" | "voice">("chat");
  const [cfg, setCfg] = useState<WidgetConfig | null>(null);
  const [error, setError] = useState<string | null>(null);

  const authed = useCallback(
    async (path: string, init: RequestInit = {}) => {
      const token = await getPortalToken();
      const resp = await fetch(apiBase + path, {
        ...init,
        headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      });
      if (!resp.ok) throw new Error((await resp.json().catch(() => ({}))).detail ?? `Request failed (${resp.status})`);
      return resp.status === 204 ? null : resp.json();
    },
    [apiBase, getPortalToken],
  );

  useEffect(() => {
    if (!open || cfg) return;
    authed("/api/v1/widget/config").then(setCfg).catch((e) => setError(e.message));
  }, [open, cfg, authed]);

  return (
    <div className="pointer-events-none fixed bottom-4 right-4 z-[2147483000] flex flex-col items-end gap-3 font-sans text-foreground">
      {open && (
        <div className="pointer-events-auto flex h-[560px] max-h-[calc(100vh-6rem)] w-[min(380px,calc(100vw-2rem))] flex-col overflow-hidden rounded-2xl border bg-card shadow-2xl">
          <div className="flex items-center justify-between bg-primary px-4 py-3 text-primary-foreground">
            <div>
              <div className="text-sm font-semibold">{cfg?.payer_name ?? "Health Plan"} Assistant</div>
              <div className="text-xs opacity-80">{cfg?.persona === "provider" ? "Provider services" : "Member services"} · AI assistant</div>
            </div>
            <button aria-label="Close" onClick={() => setOpen(false)} className="rounded p-1 hover:bg-white/10"><X className="h-4 w-4" /></button>
          </div>
          <div className="flex border-b text-sm">
            {(["chat", "voice"] as const).map((t) => (
              <button key={t} onClick={() => setTab(t)} className={cn("flex-1 py-2", tab === t ? "border-b-2 border-primary font-medium" : "text-muted-foreground")}>
                {t === "chat" ? "Chat" : "Talk"}
              </button>
            ))}
          </div>
          {error && <div className="m-3 rounded-md bg-red-50 p-2 text-xs text-red-800">{error}</div>}
          {cfg && tab === "chat" && <ChatPane cfg={cfg} authed={authed} />}
          {cfg && tab === "voice" && <VoicePane cfg={cfg} apiBase={apiBase} getPortalToken={getPortalToken} />}
          <div className="border-t px-4 py-2 text-[10px] leading-tight text-muted-foreground">
            You're talking with an AI. Don't share your Social Security number. In an emergency call 911.
          </div>
        </div>
      )}
      <button
        aria-label={open ? "Close assistant" : "Open assistant"}
        onClick={() => setOpen((o) => !o)}
        className="pointer-events-auto flex h-14 w-14 items-center justify-center rounded-full bg-primary text-primary-foreground shadow-lg transition-transform hover:scale-105"
      >
        {open ? <X className="h-6 w-6" /> : <MessageSquare className="h-6 w-6" />}
      </button>
    </div>
  );
}

function ChatPane({ cfg, authed }: { cfg: WidgetConfig; authed: (p: string, i?: RequestInit) => Promise<any> }) {
  const [chatId, setChatId] = useState<string | null>(null);
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current || cfg.chat_mode === "disabled") return;
    started.current = true;
    authed("/api/v1/widget/chat/start", { method: "POST" })
      .then((r) => { setChatId(r.chat_id); setMsgs([{ role: "agent", content: r.greeting }]); })
      .catch((e) => setErr(e.message));
  }, [cfg.chat_mode, authed]);

  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [msgs, busy]);

  const send = async () => {
    const text = draft.trim();
    if (!text || !chatId || busy) return;
    setDraft("");
    setMsgs((m) => [...m, { role: "user", content: text }]);
    setBusy(true);
    try {
      const r = await authed(`/api/v1/widget/chat/${chatId}/messages`, { method: "POST", body: JSON.stringify({ content: text }) });
      setMsgs((m) => [...m, ...r.messages]);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const end = async () => {
    if (!chatId) return;
    await authed(`/api/v1/widget/chat/${chatId}/end`, { method: "POST" }).catch(() => undefined);
    setMsgs((m) => [...m, { role: "agent", content: "Chat ended. Thanks for contacting us." }]);
    setChatId(null);
  };

  if (cfg.chat_mode === "disabled") return <p className="p-4 text-sm text-muted-foreground">Chat isn't available right now.</p>;
  return (
    <>
      {cfg.chat_mode === "simulated" && (
        <div className="bg-amber-50 px-4 py-1.5 text-[11px] text-amber-900">Demo mode: keyword-routed stand-in for the Retell chat agent.</div>
      )}
      <div className="flex flex-1 flex-col gap-2 overflow-y-auto p-3">
        {msgs.map((m, i) => (
          <div key={i} className={cn("max-w-[85%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-sm", m.role === "user" ? "self-end bg-primary text-primary-foreground" : "self-start bg-secondary")}>
            {m.content}
          </div>
        ))}
        {busy && <div className="self-start rounded-2xl bg-secondary px-3 py-2 text-sm text-muted-foreground">…</div>}
        {err && <div className="text-xs text-red-700">{err}</div>}
        <div ref={endRef} />
      </div>
      <form className="flex items-center gap-2 border-t p-2" onSubmit={(e) => { e.preventDefault(); send(); }}>
        <input
          className="h-9 flex-1 rounded-full border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          placeholder={chatId ? "Ask about claims, benefits, deductible…" : "Chat ended"}
          value={draft}
          disabled={!chatId}
          onChange={(e) => setDraft(e.target.value)}
        />
        <button type="submit" aria-label="Send" disabled={!chatId || !draft.trim()} className="flex h-9 w-9 items-center justify-center rounded-full bg-primary text-primary-foreground disabled:opacity-40">
          <Send className="h-4 w-4" />
        </button>
        {chatId && <button type="button" onClick={end} className="text-xs text-muted-foreground hover:underline">End</button>}
      </form>
    </>
  );
}

function VoicePane({ cfg, apiBase, getPortalToken }: { cfg: WidgetConfig; apiBase: string; getPortalToken: PayerAssistantProps["getPortalToken"] }) {
  const [status, setStatus] = useState<"idle" | "connecting" | "live" | "ended">("idle");
  const [talking, setTalking] = useState(false);
  const [muted, setMuted] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const session = useRef<WebCallSession | null>(null);

  useEffect(() => () => { session.current?.end(); }, []);

  const start = async () => {
    setErr(null);
    const token = await getPortalToken();
    // The SDK's create-web-call request is sent to our middleware instead of
    // api.retellai.com. The middleware decides agent and caller identity from
    // the portal token and holds the Retell API key; the browser never sees it.
    const client = new RetellClient({
      key: "server-side",
      fetch: (url, init) =>
        fetch(`${apiBase}/api/v1/widget/voice${new URL(String(url)).pathname}`, {
          method: init?.method ?? "POST",
          body: init?.body,
          headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
        }),
    });
    session.current = client.createWebCall({
      agent_id: "chosen-by-server",
      hooks: {
        onStatus: (s) => setStatus(s === "live" ? "live" : s === "ended" ? "ended" : "connecting"),
        onAgentStartTalking: () => setTalking(true),
        onAgentStopTalking: () => setTalking(false),
        onError: (e) => setErr(e.message),
      },
    });
    setStatus("connecting");
  };

  const stop = async () => { await session.current?.end(); setStatus("ended"); setTalking(false); };
  const toggleMute = () => {
    if (!session.current) return;
    if (muted) session.current.unmute(); else session.current.mute();
    setMuted(!muted);
  };

  if (!cfg.voice_enabled) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 p-6 text-center">
        <MicOff className="h-8 w-8 text-muted-foreground" />
        <p className="text-sm font-medium">Voice isn't configured</p>
        <p className="text-xs text-muted-foreground">Set RETELL_API_KEY and the {cfg.persona} agent ID in the middleware .env (see scripts/provision_retell.py).</p>
      </div>
    );
  }

  const live = status === "live" || status === "connecting";
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-5 p-6 text-center">
      <div className={cn("flex h-28 w-28 items-center justify-center rounded-full transition-all", live ? "bg-primary/15" : "bg-secondary", talking && "ring-8 ring-primary/20 scale-105")}>
        <Mic className={cn("h-10 w-10", live ? "text-primary" : "text-muted-foreground")} />
      </div>
      <div className="text-sm">
        {status === "idle" && "Talk to our assistant in your browser."}
        {status === "connecting" && "Connecting…"}
        {status === "live" && (talking ? "Assistant is speaking" : "Listening")}
        {status === "ended" && "Call ended."}
      </div>
      {err && <div className="text-xs text-red-700">{err}</div>}
      {!live ? (
        <button onClick={start} className="rounded-full bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground">
          {status === "ended" ? "Start again" : "Start talking"}
        </button>
      ) : (
        <div className="flex gap-3">
          <button onClick={toggleMute} aria-label={muted ? "Unmute" : "Mute"} className="flex h-11 w-11 items-center justify-center rounded-full border">
            {muted ? <MicOff className="h-5 w-5" /> : <Mic className="h-5 w-5" />}
          </button>
          <button onClick={stop} aria-label="End call" className="flex h-11 w-11 items-center justify-center rounded-full bg-destructive text-destructive-foreground">
            <PhoneOff className="h-5 w-5" />
          </button>
        </div>
      )}
    </div>
  );
}
