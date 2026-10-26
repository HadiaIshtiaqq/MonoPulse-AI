"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { CalendarDays, Download, Trash2 } from "lucide-react";
import { api, media, timeAgo, type CampaignSummary } from "@/lib/api";
import { PlatformIcon } from "@/components/PlatformIcon";

export function CampaignCard({ c, onDelete }: { c: CampaignSummary; onDelete?: (id: string) => void }) {
  const pct = c.posts ? Math.round((c.approved / c.posts) * 100) : 0;
  const failed = c.status === "FAILED";
  const generating = c.status === "GENERATING";
  const [filled, setFilled] = useState(false);
  useEffect(() => { const t = setTimeout(() => setFilled(true), 250); return () => clearTimeout(t); }, []);
  return (
    <div className="card card-hover group flex flex-col overflow-hidden">
      <Link href={`/campaign/${c.id}`} className="relative grid grid-cols-4 gap-0.5 overflow-hidden bg-slate-100">
        {c.thumbnails.length ? (
          c.thumbnails.slice(0, 4).map((t, i) => (
            <span key={i} className="block overflow-hidden">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={media(t)} alt="" className="zoom-on-hover aspect-[4/5] h-full w-full object-cover object-left" style={{ transitionDelay: `${i * 40}ms` }} />
            </span>
          ))
        ) : (
          <div className="col-span-4 grid aspect-[16/5] place-items-center text-sm text-slate-400"
            style={{ background: c.primary_color ? `linear-gradient(135deg, ${c.primary_color}, ${c.accent_color ?? c.primary_color})` : undefined }}>
            <span className="flex items-center gap-1.5 rounded-full bg-white/85 px-3 py-1 text-xs font-medium text-slate-600 backdrop-blur">
              {generating && <span className="h-1.5 w-1.5 animate-pulse-ring rounded-full bg-brand" />}
              {generating ? "Generating…" : failed ? "Failed" : "No posts"}
            </span>
          </div>
        )}
        <span className="pointer-events-none absolute inset-0 bg-gradient-to-t from-ink/20 to-transparent opacity-0 transition-opacity duration-500 group-hover:opacity-100" />
      </Link>
      <div className="flex flex-1 flex-col p-4">
        <div className="flex items-start gap-3">
          <span className="mt-0.5 h-8 w-8 shrink-0 rounded-lg" style={{ background: c.primary_color ? `linear-gradient(135deg, ${c.primary_color}, ${c.accent_color ?? c.primary_color})` : "#CBD5E1" }} />
          <Link href={`/campaign/${c.id}`} className="min-w-0 flex-1">
            <p className="truncate font-semibold hover:text-brand">{c.name}</p>
            <p className="flex items-center gap-1 text-xs text-slate-500">
              <CalendarDays size={12} /> {c.days} days from {new Date(c.start_date).toLocaleDateString("en", { month: "short", day: "numeric" })} · {timeAgo(c.created_at)}
            </p>
          </Link>
          <div className="flex gap-0.5">
            {c.platforms.map((p) => <span key={p} className="grid h-6 w-6 place-items-center rounded-md bg-slate-50"><PlatformIcon platform={p} size={12} /></span>)}
          </div>
        </div>
        <div className="mt-4">
          <div className="flex justify-between text-xs text-slate-500">
            <span>{c.approved}/{c.posts} approved{c.published ? ` · ${c.published} published` : ""}</span>
            <span>{pct}%</span>
          </div>
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-slate-100">
            <div className="h-full rounded-full bg-brand-gradient transition-[width] duration-1000 ease-out" style={{ width: `${filled ? pct : 0}%` }} />
          </div>
        </div>
        <div className="mt-4 flex items-center gap-2">
          <Link href={`/campaign/${c.id}`} className="btn-ghost btn-sm flex-1">Open</Link>
          {c.posts > 0 && (
            <a href={api.exportUrl(c.id)} className="btn-ghost btn-sm" title="Download images + captions (ZIP)"><Download size={14} /></a>
          )}
          {onDelete && (
            <button onClick={() => onDelete(c.id)} className="btn-ghost btn-sm text-slate-400 hover:text-red-600" aria-label="Delete campaign"><Trash2 size={14} /></button>
          )}
        </div>
      </div>
    </div>
  );
}
