import { CheckCircle2, Circle, ExternalLink, Loader2, MinusCircle, XCircle } from "lucide-react";
import type { Job } from "@/lib/api";

function StepIcon({ status }: { status: string }) {
  if (status === "done") return <CheckCircle2 size={18} className="text-emerald-500" />;
  if (status === "running") return <Loader2 size={18} className="animate-spin text-brand" />;
  if (status === "skipped") return <MinusCircle size={18} className="text-slate-300" />;
  if (status === "error") return <XCircle size={18} className="text-red-500" />;
  return <Circle size={18} className="text-slate-200" />;
}

export function GenerationProgress({ job, elapsed }: { job: Job; elapsed: number }) {
  const done = job.steps.filter((s) => s.status === "done" || s.status === "skipped").length;
  const pct = Math.round((done / job.steps.length) * 100);
  const brand = job.brand;

  return (
    <div className="mx-auto grid max-w-5xl gap-4 md:grid-cols-5">
      <div className="card p-6 md:col-span-3">
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Building your campaign</h2>
          <span className="font-mono text-sm text-slate-500">{elapsed.toFixed(1)}s</span>
        </div>
        <div className="mt-3 h-2 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full rounded-full bg-brand transition-all duration-500" style={{ width: `${Math.max(4, pct)}%` }} />
        </div>
        <ol className="mt-5 space-y-3">
          {job.steps.map((s) => (
            <li key={s.key} className="flex items-start gap-3">
              <StepIcon status={s.status} />
              <div className="min-w-0 flex-1">
                <p className={`text-sm ${s.status === "pending" ? "text-slate-400" : "font-medium"}`}>{s.label}</p>
                {s.detail && <p className="truncate text-xs text-slate-500">{s.detail}</p>}
              </div>
              {s.seconds !== null && <span className="font-mono text-xs text-slate-400">{s.seconds.toFixed(1)}s</span>}
            </li>
          ))}
        </ol>
        {job.error && <p className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{job.error}</p>}
      </div>

      <div className="space-y-4 md:col-span-2">
        <div className="card p-5">
          <p className="label">Brand kit</p>
          {brand ? (
            <div className="mt-3 space-y-3">
              <div className="flex items-center gap-3">
                {brand.logo_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img src={brand.logo_url} alt="" className="h-10 w-10 rounded-lg border border-slate-100 object-contain" />
                ) : (
                  <span className="h-10 w-10 rounded-lg" style={{ background: brand.primary_color }} />
                )}
                <div className="min-w-0">
                  <p className="truncate font-semibold">{brand.name}</p>
                  <p className="truncate text-xs text-slate-500">
                    {[brand.industry, brand.location].filter(Boolean).join(" · ")}
                  </p>
                </div>
              </div>
              <div className="flex gap-1.5">
                {[brand.primary_color, brand.accent_color, brand.secondary_color, ...brand.palette.slice(2)].map((c, i) => (
                  <span key={i} title={c} className="h-7 flex-1 rounded-md border border-black/5" style={{ background: c }} />
                ))}
              </div>
              {brand.tagline && <p className="text-sm italic text-slate-600">&ldquo;{brand.tagline}&rdquo;</p>}
            </div>
          ) : (
            <div className="mt-3 space-y-2">
              <div className="h-10 animate-pulse rounded-lg bg-slate-100" />
              <div className="h-7 animate-pulse rounded-lg bg-slate-100" />
            </div>
          )}
        </div>
        <div className="card p-5">
          <p className="label">Live trends</p>
          {job.trends && job.trends.length > 0 ? (
            <ul className="mt-3 space-y-2">
              {job.trends.slice(0, 5).map((t) => (
                <li key={t.url || t.title} className="text-sm">
                  <a href={t.url} target="_blank" rel="noreferrer" className="flex items-start gap-1 hover:text-brand">
                    <span className="line-clamp-2">{t.title}</span>
                    <ExternalLink size={12} className="mt-1 shrink-0 text-slate-400" />
                  </a>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-3 text-sm text-slate-400">Waiting for the Tavily search…</p>
          )}
        </div>
      </div>
    </div>
  );
}
