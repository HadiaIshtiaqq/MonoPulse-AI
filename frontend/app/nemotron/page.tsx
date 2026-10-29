"use client";

import { useEffect, useState } from "react";
import { Activity, AlertTriangle, CheckCircle2, Cpu, Gauge, Loader2, Zap } from "lucide-react";
import { api, type LLMCall, type Telemetry } from "@/lib/api";

/** What each purpose means to an owner, so the routing table reads as work, not ids. */
const PURPOSES: Record<string, string> = {
  strategy: "Monthly content strategy",
  copywriting: "Captions and posts",
  humanize: "Humanizer rewrite",
  rewrite: "Rewrites and translations",
  reel_script: "Reel scripts",
  ugc_director: "UGC shot direction",
  brand_voice: "Brand voice",
  research_plan: "Research planning",
  research_report: "Research reports",
  insight_extract: "Facts from web pages",
  transliterate: "Roman Urdu to Urdu letters",
  format_seo: "SEO tags and formatting",
  hashtags: "Hashtags",
  classify: "Classification",
  brand_extract: "Brand details from a website",
};

const STATE: Record<Telemetry["state"], { text: string; tone: string }> = {
  ok: { text: "Connected: Nemotron is answering", tone: "bg-emerald-50 text-emerald-700" },
  ready: { text: "Key set: no calls yet", tone: "bg-sky-50 text-sky-700" },
  error: { text: "The last call failed", tone: "bg-amber-50 text-amber-700" },
  key_rejected: { text: "Nebius rejected the key", tone: "bg-red-50 text-red-700" },
  off: { text: "Not connected: templates are used", tone: "bg-slate-100 text-slate-600" },
};

/** Live view of every Nemotron call: which tier took which job, how long it took and what it cost
 *  against today's cap. Nothing here shows or sends a key. */
export default function NemotronPage() {
  const [t, setT] = useState<Telemetry | null>(null);
  const [error, setError] = useState("");
  const [ping, setPing] = useState<{ busy: boolean; text: string; ok?: boolean }>({ busy: false, text: "" });

  useEffect(() => {
    const load = () => api.telemetry().then((d) => { setT(d); setError(""); }).catch((e) => setError((e as Error).message));
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, []);

  async function check() {
    setPing({ busy: true, text: "" });
    try {
      const r = await api.pingNemotron();
      setPing({ busy: false, ok: true, text: `${r.record.model} answered “${r.reply}” in ${(r.record.latency_ms / 1000).toFixed(1)} s` });
    } catch (e) {
      setPing({ busy: false, ok: false, text: (e as Error).message });
    }
    api.telemetry().then(setT).catch(() => {});
  }

  if (!t) {
    return error
      ? <p className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>
      : <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 size={14} className="animate-spin" /> Loading…</div>;
  }
  const state = STATE[t.state];
  const tokenShare = t.today.limit ? Math.min(100, (t.today.tokens / t.today.limit) * 100) : 0;
  const byTier = (tier: string) => Object.entries(t.routing).filter(([, v]) => v === tier).map(([p]) => p);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold">Nemotron</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-500">
            Every AI step in MonoPlus runs on NVIDIA Nemotron through Nebius Token Factory ({t.provider === "bedrock" ? "Amazon Bedrock is on" : "OpenAI-compatible API"}).
            Each agent asks for a <em>purpose</em>; the router sends hard thinking to the large model and quick, structured jobs to the small one.
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <span className={`chip ${state.tone}`}>{t.state === "ok" ? <CheckCircle2 size={12} /> : <AlertTriangle size={12} />} {state.text}</span>
          <button onClick={check} disabled={ping.busy || t.state === "off"} className="btn-primary btn-sm">
            {ping.busy ? <Loader2 size={14} className="animate-spin" /> : <Zap size={14} />} Test a live call
          </button>
        </div>
      </div>
      {ping.text && <p className={`rounded-xl px-4 py-3 text-sm ${ping.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"}`}>{ping.text}</p>}
      {t.state === "key_rejected" && (
        <p className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">
          Nebius answered &ldquo;unable to authenticate&rdquo;. In Token Factory, open API keys, create a new key and copy the whole secret it shows once
          (it&apos;s long), then set <code>NEBIUS_API_KEY</code> in backend/.env and restart MonoPlus.
        </p>
      )}
      {error && <p className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>}

      <div className="grid gap-5 sm:grid-cols-3">
        <Stat icon={<Gauge size={16} />} label="Tokens today" value={t.today.tokens.toLocaleString()}
          sub={t.today.limit ? `of ${t.today.limit.toLocaleString()} (LLM_DAILY_TOKENS)` : "no daily cap"}>
          {t.today.limit > 0 && <div className="mt-2 h-1.5 rounded-full bg-slate-100"><div className="h-1.5 rounded-full bg-brand" style={{ width: `${tokenShare}%` }} /></div>}
        </Stat>
        <Stat icon={<Activity size={16} />} label="Calls since start" value={String(Object.values(t.tiers).reduce((n, x) => n + x.calls, 0))}
          sub={(() => {
            const failed = Object.values(t.tiers).reduce((n, x) => n + x.failures, 0);
            return failed ? `${failed} failed; MonoPlus used a template for those` : "none failed";
          })()} />
        <Stat icon={<Cpu size={16} />} label="Estimated spend today" value={`$${t.today.dollars.toFixed(4)}`}
          sub={t.today.dollar_limit ? `cap $${t.today.dollar_limit} (LLM_DAILY_DOLLARS)` : "set PRICE_PER_M_* to estimate"} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        {(["ultra", "nano"] as const).map((tier) => {
          const s = t.tiers[tier];
          return (
            <section key={tier} className="card p-5">
              <div className="flex items-baseline justify-between gap-3">
                <p className="font-semibold">{tier === "ultra" ? "Ultra tier: reasoning and writing" : "Nano tier: fast, structured jobs"}</p>
                <code className="truncate text-[11px] text-slate-500" title={t.models[tier]}>{t.models[tier]}</code>
              </div>
              <p className="mt-2 text-xs text-slate-500">
                {s.calls} calls · {s.tokens.toLocaleString()} tokens · {s.avg_latency_ms != null ? `${(s.avg_latency_ms / 1000).toFixed(1)} s average` : "no timing yet"}
              </p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                {byTier(tier).map((p) => (
                  <span key={p} className={`chip ${s.purposes.includes(p) ? "bg-brand-soft text-brand-700" : "bg-slate-100 text-slate-500"}`} title={p}>
                    {PURPOSES[p] || p}
                  </span>
                ))}
              </div>
            </section>
          );
        })}
      </div>

      <section className="card overflow-hidden">
        <p className="border-b border-slate-100 px-5 py-3 font-semibold">Recent calls</p>
        {t.recent.length === 0 ? (
          <p className="px-5 py-6 text-sm text-slate-500">No calls yet. Create a campaign or a UGC ad and they appear here as they happen.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-slate-500"><tr><th className="px-5 py-2 font-medium">When</th><th className="px-2 py-2 font-medium">Job</th>
                <th className="px-2 py-2 font-medium">Tier</th><th className="px-2 py-2 font-medium">Tokens</th><th className="px-2 py-2 font-medium">Time</th>
                <th className="px-5 py-2 font-medium">Result</th></tr></thead>
              <tbody>{t.recent.map((r, i) => <Row key={`${r.at}-${i}`} r={r} />)}</tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function Stat({ icon, label, value, sub, children }: { icon: React.ReactNode; label: string; value: string; sub: string; children?: React.ReactNode }) {
  return (
    <section className="card p-5">
      <p className="flex items-center gap-2 text-xs text-slate-500"><span className="text-brand">{icon}</span>{label}</p>
      <p className="mt-1 text-2xl font-bold">{value}</p>
      <p className="text-[11px] text-slate-400">{sub}</p>
      {children}
    </section>
  );
}

function Row({ r }: { r: LLMCall }) {
  const tokens = (r.prompt_tokens || 0) + (r.completion_tokens || 0);
  return (
    <tr className="border-t border-slate-100">
      <td className="whitespace-nowrap px-5 py-2 text-slate-500">{new Date(r.at).toLocaleTimeString()}</td>
      <td className="px-2 py-2">{PURPOSES[r.purpose] || r.purpose}</td>
      <td className="px-2 py-2 capitalize">{r.tier}</td>
      <td className="px-2 py-2">{tokens ? tokens.toLocaleString() : "–"}</td>
      <td className="px-2 py-2">{(r.latency_ms / 1000).toFixed(1)} s</td>
      <td className="max-w-xs truncate px-5 py-2" title={r.error || ""}>
        {r.ok ? <span className="text-emerald-700">ok</span> : <span className="text-red-600">{r.error || "failed"}</span>}
      </td>
    </tr>
  );
}
