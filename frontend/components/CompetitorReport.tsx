"use client";

import { AlertTriangle, CalendarRange, CheckCircle2, ExternalLink, Lightbulb, Sparkles, Target, TrendingUp } from "lucide-react";
import type { CompetitorProfile, CompetitorReport } from "@/lib/api";

const PLATFORM_LABEL: Record<string, string> = {
  instagram: "Instagram", facebook: "Facebook", tiktok: "TikTok", youtube: "YouTube", x: "X", pinterest: "Pinterest",
  linkedin: "LinkedIn", whatsapp: "WhatsApp", snapchat: "Snapchat",
};

function CompetitorCard({ c, isBrand = false }: { c: CompetitorProfile; isBrand?: boolean }) {
  const host = c.url ? c.url.split("//")[1]?.split("/")[0] : "";
  return (
    <div className={`group flex flex-col overflow-hidden rounded-xl border transition-all duration-300 hover:-translate-y-1 hover:shadow-lift ${isBrand ? "border-brand bg-brand-soft/40" : "border-slate-200 bg-white"}`}>
      {c.sample_products.length > 0 && (
        <div className="grid grid-cols-3 gap-px overflow-hidden bg-slate-100">
          {c.sample_products.slice(0, 3).map((p, i) => (
            // eslint-disable-next-line @next/next/no-img-element
            <img key={i} src={p.image_url} alt={p.name} loading="lazy" className="zoom-on-hover aspect-[3/4] w-full object-cover" />
          ))}
        </div>
      )}
      <div className="flex flex-1 flex-col gap-1.5 p-3">
        <div className="flex items-start justify-between gap-2">
          <p className="font-semibold leading-tight">{c.name}{isBrand && <span className="ml-1.5 chip bg-brand text-white">You</span>}</p>
          {c.url && (
            <a href={c.url} target="_blank" rel="noreferrer" className="shrink-0 text-slate-400 hover:text-brand" aria-label={`Open ${host}`}><ExternalLink size={13} /></a>
          )}
        </div>
        {!c.reachable ? (
          <p className="text-xs text-amber-700">Couldn&apos;t read this site right now{c.note ? `: ${c.note}` : ""}.</p>
        ) : (
          <>
            {c.tagline && <p className="line-clamp-2 text-xs text-slate-500">{c.tagline}</p>}
            <dl className="mt-1 space-y-1 text-xs">
              {c.price_range && <div className="flex gap-1"><dt className="w-16 shrink-0 text-slate-400">Prices</dt><dd>{c.price_range}</dd></div>}
              <div className="flex gap-1"><dt className="w-16 shrink-0 text-slate-400">On sale</dt>
                <dd>{c.best_discount ? <span className="font-semibold text-red-600">up to {c.best_discount}% off</span> : "no sale seen"}</dd></div>
              {c.segments.length > 0 && <div className="flex gap-1"><dt className="w-16 shrink-0 text-slate-400">Sells for</dt><dd>{c.segments.join(", ")}</dd></div>}
              {c.claims.length > 0 && <div className="flex gap-1"><dt className="w-16 shrink-0 text-slate-400">Promises</dt><dd>{c.claims.join(", ")}</dd></div>}
              {c.socials.length > 0 && <div className="flex gap-1"><dt className="w-16 shrink-0 text-slate-400">On</dt>
                <dd>{c.socials.map((s) => PLATFORM_LABEL[s] ?? s).join(", ")}</dd></div>}
            </dl>
          </>
        )}
        {!isBrand && c.found_via && <p className="mt-auto pt-1 text-[11px] text-slate-400">Found: {c.found_via}</p>}
      </div>
    </div>
  );
}

function Facts({ title, items, icon, tone }: { title: string; items: string[]; icon: React.ReactNode; tone: string }) {
  if (!items.length) return null;
  return (
    <div className="rounded-xl border border-slate-200 p-4">
      <p className={`mb-2 flex items-center gap-1.5 text-sm font-semibold ${tone}`}>{icon} {title}</p>
      <ul className="space-y-1.5 text-sm text-slate-700">
        {items.map((x) => <li key={x} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-slate-400" />{x}</li>)}
      </ul>
    </div>
  );
}

export function CompetitorReportView({ report }: { report: CompetitorReport }) {
  return (
    <div className="space-y-5">
      {report.summary && (
        <div className="rounded-xl bg-indigo-50/70 p-4 text-sm leading-relaxed text-slate-800">
          <p className="mb-1 flex items-center gap-1.5 font-semibold text-brand-700"><Sparkles size={14} /> Summary
            <span className="ml-auto text-[11px] font-normal text-slate-500">{report.method === "model" ? "Advice written by Nemotron" : "Advice derived from the comparison"}</span>
          </p>
          {report.summary}
        </div>
      )}

      <div>
        <p className="label mb-2">Brands compared</p>
        <div className="stagger grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {report.brand && <CompetitorCard c={report.brand} isBrand />}
          {report.competitors.map((c) => <CompetitorCard key={c.url || c.name} c={c} />)}
        </div>
        {report.competitors.length === 0 && <p className="text-sm text-slate-500">No competitor sites could be found or read this time.</p>}
      </div>

      <div className="stagger grid gap-3 lg:grid-cols-3">
        <Facts title="Where you stand" items={report.position} icon={<Target size={14} />} tone="text-slate-800" />
        <Facts title="Your strengths" items={report.strengths} icon={<CheckCircle2 size={14} />} tone="text-emerald-700" />
        <Facts title="Gaps to close" items={report.gaps} icon={<AlertTriangle size={14} />} tone="text-amber-700" />
      </div>

      {report.recommendations.length > 0 && (
        <div>
          <p className="label mb-2 flex items-center gap-1"><TrendingUp size={12} /> Recommended strategy</p>
          <ol className="stagger grid gap-3 md:grid-cols-2">
            {report.recommendations.map((r, i) => (
              <li key={r.title} className="rounded-xl border border-slate-200 bg-white p-4 transition-all duration-300 hover:-translate-y-0.5 hover:border-brand-200 hover:shadow-lift">
                <p className="flex items-baseline gap-2 font-semibold"><span className="text-brand">{i + 1}.</span>{r.title}</p>
                {r.why && <p className="mt-1 text-sm text-slate-600"><span className="font-medium text-slate-700">Why: </span>{r.why}</p>}
                {r.how && <p className="mt-1 text-sm text-slate-600"><span className="font-medium text-slate-700">How: </span>{r.how}</p>}
              </li>
            ))}
          </ol>
        </div>
      )}

      {report.plan.length > 0 && (
        <div>
          <p className="label mb-2 flex items-center gap-1"><CalendarRange size={12} /> 4-week plan</p>
          <div className="stagger grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            {report.plan.map((w) => (
              <div key={w.week} className="rounded-xl border border-slate-200 bg-white p-4">
                <p className="text-xs font-semibold uppercase tracking-wide text-brand">Week {w.week}</p>
                <p className="mt-0.5 font-semibold">{w.focus}</p>
                <ul className="mt-2 space-y-1 text-sm text-slate-600">
                  {w.actions.map((a) => <li key={a} className="flex gap-2"><span className="mt-2 h-1 w-1 shrink-0 rounded-full bg-brand" />{a}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </div>
      )}

      {report.content_ideas.length > 0 && (
        <div>
          <p className="label mb-2 flex items-center gap-1"><Lightbulb size={12} /> Content ideas</p>
          <div className="flex flex-wrap gap-2">
            {report.content_ideas.map((x) => <span key={x} className="chip bg-brand-soft text-brand-700">{x}</span>)}
          </div>
        </div>
      )}
    </div>
  );
}
