"use client";

import { Check, ExternalLink, Layers } from "lucide-react";
import { fmtDay, fmtTime, media, type SocialPost } from "@/lib/api";
import { PLATFORM_META, PlatformIcon } from "@/components/PlatformIcon";

const STATUS: Record<string, string> = {
  DRAFT: "bg-slate-100 text-slate-600",
  APPROVED: "bg-emerald-50 text-emerald-700",
  PUBLISHED: "bg-brand-soft text-brand-700",
};

/** Buffer-style queue: one row per post, in posting order, with quick approve. */
export function QueueList({ posts, onOpen, onApprove }: { posts: SocialPost[]; onOpen: (p: SocialPost) => void; onApprove: (p: SocialPost) => void }) {
  const ordered = [...posts].sort((a, b) => a.publish_at.localeCompare(b.publish_at));
  let lastDay = "";
  return (
    <div className="card divide-y divide-slate-100 overflow-hidden">
      {ordered.map((p) => {
        const d = new Date(p.publish_at);
        const day = fmtDay(p.publish_at, { weekday: "long", month: "long", day: "numeric" });
        const header = day !== lastDay;
        lastDay = day;
        return (
          <div key={p.id}>
            {header && <p className="bg-slate-50/80 px-4 py-2 text-xs font-semibold text-slate-500">{day}</p>}
            <div className="group flex items-center gap-4 px-4 py-3 transition hover:bg-slate-50/60">
              <button onClick={() => onOpen(p)} className="relative h-16 w-16 shrink-0 overflow-hidden rounded-xl bg-slate-100">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={media(p.image_url)} alt="" className="h-full w-full object-cover" />
                {p.format === "carousel" && <Layers size={13} className="absolute right-1 top-1 text-white drop-shadow" />}
              </button>
              <button onClick={() => onOpen(p)} className="min-w-0 flex-1 text-left">
                <p className="flex items-center gap-2 text-xs text-slate-500">
                  <PlatformIcon platform={p.platform} size={12} /> {PLATFORM_META[p.platform].label} ·{" "}
                  {fmtTime(p.publish_at)}
                  {p.format === "carousel" && <span>· carousel</span>}
                </p>
                <p className="truncate text-sm font-semibold">{p.headline}</p>
                <p className="truncate text-sm text-slate-500">{p.caption}</p>
              </button>
              <span className={`chip hidden sm:inline-flex ${STATUS[p.status]}`}>{p.status === "PUBLISHED" ? "posted" : p.status.toLowerCase()}</span>
              {p.status === "DRAFT" && (
                <button onClick={() => onApprove(p)} className="btn-ghost btn-sm" title="Approve">
                  <Check size={14} /> <span className="hidden md:inline">Approve</span>
                </button>
              )}
              {p.remote_url && (
                <a href={p.remote_url} target="_blank" rel="noreferrer" className="btn-ghost btn-sm" title="View live post"><ExternalLink size={14} /></a>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
