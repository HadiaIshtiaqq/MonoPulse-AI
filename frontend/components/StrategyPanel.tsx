"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ExternalLink, FlaskConical, Loader2, Shuffle, Swords } from "lucide-react";
import { api, KIND_LABELS, type Campaign, type ContentMix, type PostKind, type ResearchTask } from "@/lib/api";

function ResearchUsed({ ids }: { ids: string[] }) {
  const [tasks, setTasks] = useState<ResearchTask[]>([]);
  useEffect(() => {
    Promise.all(ids.map((id) => api.researchTask(id).catch(() => null))).then((t) => setTasks(t.filter((x): x is ResearchTask => !!x)));
  }, [ids]);
  if (!tasks.length) return null;
  return (
    <div className="card p-5">
      <p className="label flex items-center gap-1"><FlaskConical size={12} /> Market research used</p>
      <ul className="mt-3 space-y-3">
        {tasks.map((t) => (
          <li key={t.id} className="text-sm">
            <Link href="/research" className="font-medium hover:text-brand">{t.topic}</Link>
            {t.insights?.verified_trend && <p className="text-xs text-slate-600">{t.insights.verified_trend}</p>}
            {t.insights?.content_angles && t.insights.content_angles.length > 0 && (
              <p className="mt-1 text-xs text-slate-500">Angles: {t.insights.content_angles.join(" · ")}</p>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function CompetitorInsights({ taskId }: { taskId: string }) {
  const [task, setTask] = useState<ResearchTask | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => api.researchTask(taskId).then((t) => alive && setTask(t)).catch(() => {});
    load();
    const t = setInterval(() => {
      if (task?.status === "completed" || task?.status === "failed") return;
      load();
    }, 3000);
    return () => { alive = false; clearInterval(t); };
  }, [taskId, task?.status]);
  if (!task) return null;
  const r = task.competitors;
  const working = task.status !== "completed" && task.status !== "failed";
  return (
    <div className="card p-5">
      <p className="label flex items-center gap-1"><Swords size={12} /> Competitor insights</p>
      {working && (
        <p className="mt-2 flex items-center gap-2 text-sm text-slate-500">
          <Loader2 size={14} className="animate-spin" /> {task.progress[task.progress.length - 1] ?? "Finding competitors…"}
        </p>
      )}
      {task.status === "failed" && <p className="mt-2 text-sm text-amber-700">{task.error ?? "The analysis didn't finish."}</p>}
      {r && (
        <>
          {r.competitors.length > 0 && (
            <p className="mt-2 text-xs text-slate-500">Compared with {r.competitors.filter((c) => c.reachable).map((c) => c.name).join(", ") || "no readable competitors"}</p>
          )}
          <ol className="mt-3 space-y-2 text-sm">
            {r.recommendations.slice(0, 3).map((rec, i) => (
              <li key={rec.title}><span className="font-semibold text-brand">{i + 1}. {rec.title}.</span> <span className="text-slate-600">{rec.how}</span></li>
            ))}
          </ol>
        </>
      )}
      <Link href={`/research?task=${task.id}`} className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-brand hover:underline">
        Full analysis and 4-week plan <ExternalLink size={12} />
      </Link>
    </div>
  );
}

function ContentMixCard({ mix }: { mix: ContentMix }) {
  const types = (Object.entries(mix.types) as [PostKind, number][]).sort((a, b) => b[1] - a[1]);
  return (
    <div className="card p-5">
      <p className="label flex items-center gap-1"><Shuffle size={12} /> Content mix</p>
      <p className="mt-1 text-xs text-slate-500">
        {mix.posts} posts · {types.length} post types · {mix.layouts} looks · {mix.repeated_headlines === 0 ? "no repeated headlines" : `${mix.repeated_headlines} repeated headlines`}
      </p>
      <ul className="mt-3 space-y-1.5">
        {types.map(([kind, n]) => (
          <li key={kind} className="flex items-center gap-2 text-sm">
            <span className="w-28 shrink-0 text-slate-700">{KIND_LABELS[kind] ?? kind}</span>
            <span className="h-2 rounded-full bg-brand/70" style={{ width: `${Math.max(6, (n / mix.posts) * 100)}%` }} />
            <span className="text-xs text-slate-500">{n}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function StrategyPanel({ campaign }: { campaign: Campaign }) {
  const s = campaign.strategy;
  const b = campaign.brand;
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="space-y-4 lg:col-span-2">
        {s && (
          <div className="card space-y-4 p-5">
            <div>
              <p className="label">Positioning</p>
              <p className="mt-1">{s.positioning}</p>
            </div>
            <div>
              <p className="label">Audience</p>
              <p className="mt-1 text-slate-700">{s.audience}</p>
            </div>
            <div>
              <p className="label mb-2">Content pillars</p>
              <div className="grid gap-2 sm:grid-cols-2">
                {s.pillars.map((p) => (
                  <div key={p.name} className="rounded-xl bg-slate-50 p-3">
                    <p className="font-medium">{p.name}</p>
                    <p className="text-sm text-slate-600">{p.description}</p>
                  </div>
                ))}
              </div>
            </div>
            <div>
              <p className="label mb-2">Weekly themes</p>
              <ol className="space-y-1 text-sm">
                {s.weekly_themes.map((t, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="font-mono text-slate-400">W{i + 1}</span> {t}
                  </li>
                ))}
              </ol>
            </div>
            <div>
              <p className="label mb-2">Voice rules</p>
              <ul className="list-inside list-disc space-y-1 text-sm text-slate-700">
                {s.voice_rules.map((r) => (
                  <li key={r}>{r}</li>
                ))}
              </ul>
            </div>
          </div>
        )}
      </div>
      <div className="space-y-4">
        {campaign.competitor_task_id && <CompetitorInsights taskId={campaign.competitor_task_id} />}
        {campaign.content_mix && campaign.content_mix.posts > 0 && <ContentMixCard mix={campaign.content_mix} />}
        {campaign.research_ids?.length > 0 && <ResearchUsed ids={campaign.research_ids} />}
        {b && (
          <div className="card space-y-3 p-5">
            <p className="label">Brand voice</p>
            <p className="text-sm text-slate-700">{b.brand_voice_prompt}</p>
            <p className="label">Value props</p>
            <ul className="list-inside list-disc text-sm text-slate-700">
              {b.value_props.map((v) => (
                <li key={v}>{v}</li>
              ))}
            </ul>
          </div>
        )}
        <div className="card p-5">
          <p className="label">News used</p>
          {campaign.trends.length === 0 && <p className="mt-2 text-sm text-slate-400">No news relevant to this brand this week, so the plan follows its seasonal calendar.</p>}
          <ul className="mt-3 space-y-3">
            {campaign.trends.map((t) => (
              <li key={t.url || t.title}>
                <a href={t.url} target="_blank" rel="noreferrer" className="flex gap-1 text-sm font-medium hover:text-brand">
                  {t.title} <ExternalLink size={12} className="mt-1 shrink-0 text-slate-400" />
                </a>
                <p className="line-clamp-2 text-xs text-slate-500">{t.snippet}</p>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
