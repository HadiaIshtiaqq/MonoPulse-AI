"use client";

import { useState } from "react";
import Link from "next/link";
import { Check, ExternalLink, Loader2, Minus, RotateCcw, Sparkles, X } from "lucide-react";
import { logoSrc, type Job } from "@/lib/api";

function StepIcon({ status }: { status: string }) {
  if (status === "done") {
    return <span className="grid h-6 w-6 animate-pop-in place-items-center rounded-full bg-emerald-500 text-white shadow-sm"><Check size={14} strokeWidth={3} /></span>;
  }
  if (status === "running") {
    return (
      <span className="grid h-6 w-6 animate-pulse-ring place-items-center rounded-full bg-brand text-white">
        <Loader2 size={13} className="animate-spin" />
      </span>
    );
  }
  if (status === "skipped") return <span className="grid h-6 w-6 place-items-center rounded-full bg-slate-100 text-slate-400"><Minus size={13} /></span>;
  if (status === "error") return <span className="grid h-6 w-6 animate-pop-in place-items-center rounded-full bg-red-500 text-white"><X size={13} strokeWidth={3} /></span>;
  return <span className="h-6 w-6 rounded-full border-2 border-slate-200" />;
}

export function GenerationProgress({ job, elapsed, onRetry }: { job: Job; elapsed: number; onRetry?: () => Promise<void> }) {
  const [retrying, setRetrying] = useState(false);
  const done = job.steps.filter((s) => s.status === "done" || s.status === "skipped").length;
  const pct = Math.round((done / job.steps.length) * 100);
  const brand = job.brand;
  const running = job.status === "running";
  const current = job.steps.find((s) => s.status === "running");

  return (
    <div className="mx-auto grid max-w-5xl gap-4 md:grid-cols-5">
      <div className="card animate-scale-in p-6 md:col-span-3">
        <div className="flex items-center justify-between gap-3">
          <div className="min-w-0">
            <h2 className="flex items-center gap-2 font-semibold">
              <Sparkles size={16} className={`text-brand ${running ? "animate-pulse" : ""}`} /> Building your campaign
            </h2>
            {current && <p key={current.key} className="mt-0.5 animate-fade-in truncate text-xs text-slate-500">{current.label}…</p>}
          </div>
          <span className="shrink-0 rounded-lg bg-slate-50 px-2 py-1 font-mono text-sm tabular-nums text-slate-500">{elapsed.toFixed(1)}s</span>
        </div>
        <div className="mt-4 h-2.5 overflow-hidden rounded-full bg-slate-100">
          <div className="relative h-full overflow-hidden rounded-full bg-brand-gradient transition-[width] duration-700 ease-out" style={{ width: `${Math.max(4, pct)}%` }}>
            {running && <span className="bg-stripes absolute inset-0 animate-stripes" />}
          </div>
        </div>
        <ol className="stagger relative mt-6 space-y-4">
          {/* The line connecting the steps fills in as they complete. */}
          <span aria-hidden className="absolute bottom-3 left-3 top-3 w-px bg-slate-200" />
          <span aria-hidden className="absolute left-3 top-3 w-px bg-emerald-400 transition-[height] duration-700 ease-out"
            style={{ height: `calc(${(done / Math.max(1, job.steps.length - 1)) * 100}% - 1.5rem)` }} />
          {job.steps.map((s) => (
            <li key={s.key} className="relative flex items-start gap-3">
              <span className="relative z-10 bg-white"><StepIcon status={s.status} /></span>
              <div className="min-w-0 flex-1 pt-0.5">
                <p className={`text-sm transition-colors duration-300 ${s.status === "pending" ? "text-slate-400" : s.status === "running" ? "font-semibold text-ink" : "font-medium"}`}>{s.label}</p>
                {s.detail && <p className="animate-fade-in truncate text-xs text-slate-500">{s.detail}</p>}
              </div>
              {s.seconds !== null && <span className="animate-fade-in pt-0.5 font-mono text-xs tabular-nums text-slate-400">{s.seconds.toFixed(1)}s</span>}
            </li>
          ))}
        </ol>
        {job.error && (
          <div className="mt-5 animate-slide-down rounded-xl bg-red-50 p-3 text-sm text-red-700">
            <p>{job.error}</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {onRetry && (
                <button className="btn-primary btn-sm" disabled={retrying}
                  onClick={() => { setRetrying(true); onRetry().catch(() => setRetrying(false)); }}>
                  {retrying ? <Loader2 size={14} className="animate-spin" /> : <RotateCcw size={14} />} Try again
                </button>
              )}
              <Link href="/" className="btn-ghost btn-sm">New campaign</Link>
            </div>
          </div>
        )}
      </div>

      <div className="space-y-4 md:col-span-2">
        <div className="card delay-1 animate-scale-in overflow-hidden p-5">
          <p className="label">Brand kit</p>
          {brand ? (
            <div className="mt-3 animate-fade-up space-y-3">
              <div className="flex items-center gap-3">
                {brand.logo_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={logoSrc(brand) ?? ""} alt="" className="h-11 w-11 animate-pop-in rounded-xl border border-slate-100 bg-white object-contain p-1" />
                ) : (
                  <span className="h-11 w-11 animate-pop-in rounded-xl" style={{ background: brand.primary_color }} />
                )}
                <div className="min-w-0">
                  <p className="truncate font-semibold">{brand.name}</p>
                  <p className="truncate text-xs text-slate-500">{[brand.industry, brand.location].filter(Boolean).join(" · ")}</p>
                </div>
              </div>
              <div className="flex gap-1.5">
                {[brand.primary_color, brand.accent_color, brand.secondary_color, ...brand.palette.slice(2)].map((c, i) => (
                  <span key={i} title={c} className="h-8 flex-1 animate-pop-in rounded-lg border border-black/5 shadow-sm"
                    style={{ background: c, animationDelay: `${150 + i * 90}ms` }} />
                ))}
              </div>
              {brand.tagline && <p className="animate-fade-in text-sm italic text-slate-600">&ldquo;{brand.tagline}&rdquo;</p>}
            </div>
          ) : (
            <div className="mt-3 space-y-2">
              <div className="flex items-center gap-3"><div className="skeleton h-11 w-11" /><div className="flex-1 space-y-1.5"><div className="skeleton h-4 w-2/3" /><div className="skeleton h-3 w-1/3" /></div></div>
              <div className="skeleton h-8" />
            </div>
          )}
        </div>
        <div className="card delay-2 animate-scale-in p-5">
          <p className="label">Live trends</p>
          {job.trends && job.trends.length > 0 ? (
            <ul className="stagger mt-3 space-y-2">
              {job.trends.slice(0, 5).map((t) => (
                <li key={t.url || t.title} className="text-sm">
                  <a href={t.url} target="_blank" rel="noreferrer" className="group flex items-start gap-1 transition-colors hover:text-brand">
                    <span className="line-clamp-2">{t.title}</span>
                    <ExternalLink size={12} className="mt-1 shrink-0 text-slate-400 transition-transform duration-300 group-hover:-translate-y-0.5 group-hover:translate-x-0.5" />
                  </a>
                </li>
              ))}
            </ul>
          ) : job.status === "error" ? (
            <p className="mt-3 text-sm text-slate-400">Not reached.</p>
          ) : (
            <div className="mt-3 space-y-2">
              {[80, 65, 72].map((w) => <div key={w} className="skeleton h-3.5" style={{ width: `${w}%` }} />)}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
