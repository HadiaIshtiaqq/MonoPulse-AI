"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Brain, CheckCircle, Clock, FileText, Globe, Lightbulb, ListChecks, Loader2, Play, Search, Sparkles, Square, Swords, Trash2 } from "lucide-react";
import { api, streamEvents, type CampaignSummary, type ResearchInsights, type ResearchTask } from "@/lib/api";
import { Markdown } from "@/components/Markdown";
import { CompetitorReportView } from "@/components/CompetitorReport";

type Ev = { type: string; [k: string]: any };

const EXAMPLES = [
  "What are customers complaining about with bakeries in Austin?",
  "Which social content formats are working for local gyms right now?",
  "How are competing coffee shops pricing and promoting seasonal drinks?",
];

function timeAgo(iso: string | null) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(iso).toLocaleDateString();
}

function Meter({ label, value }: { label: string; value: number }) {
  return (
    <div>
      <div className="flex justify-between text-xs">
        <span className="text-slate-500">{label}</span>
        <span className="font-semibold tabular-nums">{value}</span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-slate-100">
        <div className="h-full rounded-full bg-brand" style={{ width: `${value}%` }} />
      </div>
    </div>
  );
}

function InsightsCard({ i }: { i: ResearchInsights }) {
  return (
    <div className="card grid gap-4 p-4 sm:grid-cols-2">
      <div className="space-y-2">
        <Meter label="Confidence" value={i.confidence} />
        <Meter label="Opportunity" value={i.opportunity} />
        {i.confidence_rationale && <p className="text-xs text-slate-500">{i.confidence_rationale}</p>}
      </div>
      <div className="space-y-1.5 text-sm">
        {[["Trend", i.verified_trend], ["Audience", i.audience_insight], ["Pricing gap", i.pricing_gap], ["Product", i.feature_insights]]
          .filter(([, v]) => v)
          .map(([k, v]) => <p key={k}><span className="label">{k} </span>{v}</p>)}
      </div>
      {i.content_angles.length > 0 && (
        <div className="sm:col-span-2">
          <p className="label mb-1 flex items-center gap-1"><Lightbulb size={12} /> Content angles</p>
          <div className="flex flex-wrap gap-1.5">
            {i.content_angles.map((a) => <span key={a} className="chip bg-brand-soft text-brand">{a}</span>)}
          </div>
        </div>
      )}
    </div>
  );
}

export default function ResearchPage() {
  const [q, setQ] = useState("");
  const [region, setRegion] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const [events, setEvents] = useState<Ev[]>([]);
  const [report, setReport] = useState("");
  const [insights, setInsights] = useState<ResearchInsights | null>(null);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const abort = useRef<AbortController | null>(null);

  useEffect(() => {
    api.campaigns().then((c) => setCampaigns(c.filter((x) => x.status !== "FAILED"))).catch(() => {});
  }, []);

  async function run(e?: React.FormEvent) {
    e?.preventDefault();
    if (q.trim().length < 3) return;
    setEvents([]); setReport(""); setInsights(null); setTaskId(null); setError(""); setRunning(true);
    abort.current = new AbortController();
    const params = new URLSearchParams({ q, region });
    if (campaignId) params.set("campaign_id", campaignId);
    try {
      await streamEvents(`/api/research/stream?${params}`, (ev: Ev) => {
        if (ev.type === "task") setTaskId(ev.id);
        else if (ev.type === "report") setReport(ev.content);
        else if (ev.type === "insights") setInsights(ev.insights);
        else if (ev.type !== "done") setEvents((x) => [...x, ev]);
      }, abort.current.signal);
    } catch (err) {
      if ((err as Error).name !== "AbortError") setError((err as Error).message);
    } finally {
      setRunning(false);
      setRefresh((n) => n + 1);
    }
  }

  async function queue() {
    await api.queueResearch({ topic: q, region, campaign_id: campaignId || null });
    setRefresh((n) => n + 1);
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Market research</h1>
        <p className="mt-1 text-sm text-slate-600">
          The research agent finds a brand&apos;s competitors, reads their websites and turns the comparison into a strategy and a 4-week plan.
          Every new campaign gets one automatically. You can also ask any market question below. Attach a finished report to a campaign and its posts draw on it.
        </p>
      </div>

      <CompetitorAnalysis campaigns={campaigns} onChange={() => setRefresh((n) => n + 1)} />

      <p className="pt-2 text-sm font-semibold text-slate-700">Ask a market question</p>
      <form onSubmit={run} className="card space-y-3 p-4">
        <div className="flex flex-wrap gap-2">
          <input className="input min-w-[260px] flex-1" value={q} onChange={(e) => setQ(e.target.value)} placeholder="What do you want to know about your market?" />
          <input className="input w-40" value={region} onChange={(e) => setRegion(e.target.value)} placeholder="Region (optional)" />
          <select className="input w-auto" value={campaignId} onChange={(e) => setCampaignId(e.target.value)} title="Research from this brand's point of view">
            <option value="">No brand context</option>
            {campaigns.map((c) => <option key={c.id} value={c.id}>For {c.name}</option>)}
          </select>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {running ? (
            <button type="button" className="btn-ghost" onClick={() => abort.current?.abort()}><Square size={14} /> Stop</button>
          ) : (
            <button className="btn-primary" disabled={q.trim().length < 3}><Play size={14} /> Research live</button>
          )}
          <button type="button" className="btn-ghost" disabled={q.trim().length < 3 || running} onClick={queue}><Clock size={14} /> Queue for background</button>
          <span className="mx-1 h-4 w-px bg-slate-200" />
          {EXAMPLES.map((x) => (
            <button type="button" key={x} onClick={() => setQ(x)} className="chip bg-slate-100 text-slate-600 hover:bg-slate-200">{x}</button>
          ))}
        </div>
      </form>
      {error && <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {(events.length > 0 || running) && (
        <div className="grid gap-4 lg:grid-cols-3">
          <div className="card p-4">
            <p className="label mb-3">Agent trace</p>
            <ol className="space-y-2 text-sm">
              {events.map((ev, i) => <TraceLine key={i} ev={ev} />)}
              {running && <li className="flex items-center gap-2 text-slate-400"><Loader2 size={14} className="animate-spin" /> working…</li>}
            </ol>
          </div>
          <div className="space-y-4 lg:col-span-2">
            {insights && <InsightsCard i={insights} />}
            <div className="card min-h-[200px] p-5">
              {report ? <Markdown>{report}</Markdown> : <p className="text-sm text-slate-400">The report appears here when the agent finishes.</p>}
            </div>
            {report && taskId && !running && (
              <Link href={`/?research=${taskId}`} className="btn-primary w-fit"><Sparkles size={14} /> Use in a new campaign</Link>
            )}
          </div>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2"><Library refresh={refresh} /></div>
        <MemoryBrowser refresh={refresh} />
      </div>
    </div>
  );
}

function CompetitorAnalysis({ campaigns, onChange }: { campaigns: CampaignSummary[]; onChange: () => void }) {
  const [url, setUrl] = useState("");
  const [campaignId, setCampaignId] = useState("");
  const [known, setKnown] = useState("");
  const [task, setTask] = useState<ResearchTask | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const running = !!task && (task.status === "pending" || task.status === "running" || task.status === "retry");

  // Open a report linked from a campaign (/research?task=…).
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("task");
    if (id) api.researchTask(id).then(setTask).catch(() => {});
  }, []);

  useEffect(() => {
    if (!task || !running) return;
    const t = setInterval(async () => {
      try {
        const next = await api.researchTask(task.id);
        setTask(next);
        if (next.status === "completed" || next.status === "failed") onChange();
      } catch {}
    }, 1500);
    return () => clearInterval(t);
  }, [task?.id, running]); // eslint-disable-line react-hooks/exhaustive-deps

  async function start(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const t = await api.researchCompetitors({
        url: campaignId ? undefined : url.trim(), campaign_id: campaignId || null,
        competitor_urls: known.split(/[\s,]+/).map((s) => s.trim()).filter(Boolean),
      });
      setTask(t);
      onChange();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card space-y-4 p-5">
      <div className="flex flex-wrap items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand"><Swords size={18} /></span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">Competitor analysis and strategy</p>
          <p className="text-sm text-slate-500">
            Finds brands like yours, reads their sites (prices, sales, promises, platforms), compares them with yours and writes recommendations, a 4-week plan and content ideas.
          </p>
        </div>
      </div>
      <form onSubmit={start} className="space-y-2">
        <div className="flex flex-wrap gap-2">
          <select className="input w-auto" value={campaignId} onChange={(e) => setCampaignId(e.target.value)}>
            <option value="">A website…</option>
            {campaigns.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
          {!campaignId && (
            <input className="input min-w-[240px] flex-1" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="Brand website, e.g. bata.com.pk" />
          )}
          <button className="btn-primary" disabled={busy || running || (!campaignId && url.trim().length < 4)}>
            {busy || running ? <Loader2 size={14} className="animate-spin" /> : <Swords size={14} />} Analyze competitors
          </button>
        </div>
        <input className="input" value={known} onChange={(e) => setKnown(e.target.value)}
          placeholder="Optional: competitors you already know, e.g. sapphireonline.pk, mariab.pk" />
      </form>
      {error && <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}

      {task && (
        <div className="space-y-4 border-t border-slate-100 pt-4">
          <div className="flex items-center gap-2">
            <p className="font-semibold">{task.topic}</p>
            <span className={`chip ${task.status === "completed" ? "bg-emerald-50 text-emerald-700" : task.status === "failed" ? "bg-red-50 text-red-700" : "bg-sky-50 text-sky-700"}`}>
              {running ? "working" : task.status}
            </span>
          </div>
          {(running || !task.competitors) && (
            <ol className="space-y-1.5 text-sm">
              {task.progress.map((p, i) => (
                <li key={i} className="flex gap-2 text-slate-600"><CheckCircle size={14} className="mt-0.5 shrink-0 text-emerald-500" />{p}</li>
              ))}
              {running && <li className="flex items-center gap-2 text-slate-400"><Loader2 size={14} className="animate-spin" /> working…</li>}
            </ol>
          )}
          {task.error && <p className="text-sm text-amber-700">{task.error}</p>}
          {task.competitors && <CompetitorReportView report={task.competitors} />}
          {task.status === "completed" && (
            <Link href={`/?research=${task.id}`} className="btn-ghost w-fit"><Sparkles size={14} /> Use in a new campaign</Link>
          )}
        </div>
      )}
    </div>
  );
}

function TraceLine({ ev }: { ev: Ev }) {
  const row = (icon: React.ReactNode, body: React.ReactNode) => (
    <li className="flex gap-2"><span className="mt-0.5 shrink-0 text-slate-400">{icon}</span><span className="min-w-0">{body}</span></li>
  );
  switch (ev.type) {
    case "memory": return row(<Brain size={14} />, <span className="text-slate-600">Recalled earlier findings from memory</span>);
    case "plan": return row(<ListChecks size={14} />, <span><b>Plan:</b> {ev.rationale} <span className="text-slate-400">({ev.queries.length} searches)</span></span>);
    case "search": return row(<Search size={14} />, <span><span className="chip mr-1 bg-slate-100 text-slate-600">{ev.kind}</span>{ev.query}</span>);
    case "scrape": return row(<Globe size={14} />, <span className="break-all text-slate-600">Reading {ev.url}</span>);
    case "tool_result": return row(<FileText size={14} />, <span className="text-slate-500">{ev.summary}</span>);
    case "thinking": return row(<Brain size={14} />, <span className="text-slate-500">{ev.content}</span>);
    case "error": return row(<span className="text-red-500">!</span>, <span className="text-red-700">{ev.message}</span>);
    default: return null;
  }
}

function Library({ refresh }: { refresh: number }) {
  const [tasks, setTasks] = useState<ResearchTask[] | null>(null);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    const load = () => api.researchTasks().then(setTasks).catch(() => setTasks([]));
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [refresh]);

  const tone = (s: string) =>
    s === "completed" ? "bg-emerald-50 text-emerald-700" : s === "failed" ? "bg-red-50 text-red-700" : s === "running" ? "bg-sky-50 text-sky-700" : "bg-slate-100 text-slate-600";

  return (
    <div className="card">
      <p className="p-4 pb-2 font-semibold">Research library</p>
      <p className="px-4 text-xs text-slate-500">Live runs and queued research (background jobs retry up to 3 times).</p>
      {tasks === null ? <div className="p-4"><Loader2 className="animate-spin text-slate-400" size={18} /></div> : tasks.length === 0 ? (
        <p className="p-4 text-sm text-slate-400">No research yet.</p>
      ) : (
        <div className="mt-2 divide-y divide-slate-100">
          {tasks.map((t) => (
            <div key={t.id} className="p-4">
              <div className="flex items-center gap-2">
                <button onClick={() => setOpen(open === t.id ? null : t.id)} className="min-w-0 flex-1 text-left text-sm font-medium hover:text-brand">
                  {t.kind === "competitors" && <span className="chip mr-1.5 bg-brand-soft text-brand-700"><Swords size={10} /> Competitors</span>}
                  {t.topic}
                </button>
                <span className={`chip ${tone(t.status)}`}>{t.status}</span>
                <span className="text-xs text-slate-400">{timeAgo(t.completed_at ?? t.created_at)}</span>
                {t.status === "completed" && (
                  <Link href={`/?research=${t.id}`} className="chip bg-brand-soft text-brand" title="Start a campaign that uses this research">
                    <Sparkles size={11} /> Use
                  </Link>
                )}
                <button onClick={async () => { await api.deleteResearch(t.id); setTasks((x) => x?.filter((y) => y.id !== t.id) ?? null); }}
                  className="p-1 text-slate-400 hover:text-red-600" aria-label="Delete"><Trash2 size={13} /></button>
              </div>
              {t.error && <p className="mt-1 text-xs text-amber-700">{t.error}</p>}
              {(t.status === "running" || t.status === "pending") && t.progress?.length > 0 && (
                <p className="mt-1 flex items-center gap-1.5 text-xs text-slate-500"><Loader2 size={11} className="animate-spin" /> {t.progress[t.progress.length - 1]}</p>
              )}
              {open === t.id && t.competitors && (
                <div className="mt-3 border-t border-slate-100 pt-3"><CompetitorReportView report={t.competitors} /></div>
              )}
              {open === t.id && !t.competitors && t.report && (
                <div className="mt-3 space-y-3 border-t border-slate-100 pt-3">
                  {t.insights && <InsightsCard i={t.insights} />}
                  <Markdown>{t.report}</Markdown>
                </div>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MemoryBrowser({ refresh }: { refresh: number }) {
  const [q, setQ] = useState("trends");
  const [hits, setHits] = useState<Awaited<ReturnType<typeof api.memory>> | null>(null);
  const search = (e?: React.FormEvent) => { e?.preventDefault(); api.memory(q).then(setHits).catch(() => setHits([])); };
  useEffect(() => { search(); }, [refresh]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="card h-fit p-4">
      <p className="font-semibold">Research memory</p>
      <p className="text-xs text-slate-500">What the agent recalls before starting new research.</p>
      <form onSubmit={search} className="mt-3 flex gap-2">
        <input className="input" value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn-ghost"><Search size={14} /></button>
      </form>
      <ul className="mt-3 space-y-3">
        {hits?.length === 0 && <p className="text-sm text-slate-400">Nothing remembered for that yet.</p>}
        {hits?.map((h, i) => (
          <li key={i} className="text-sm">
            <p className="font-medium">{h.title} <span className="text-xs font-normal text-slate-400">{timeAgo(h.created_at)}</span></p>
            <p className="text-xs text-slate-600">{h.excerpt}</p>
          </li>
        ))}
      </ul>
    </div>
  );
}
