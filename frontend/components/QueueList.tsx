"use client";

import { Check, ExternalLink, Layers } from "lucide-react";
import { fmtDay, fmtTime, groupKey, groupPosts, groupStatus, media, type SocialPost } from "@/lib/api";
import { PLATFORM_META, PlatformIcon } from "@/components/PlatformIcon";

const STATUS: Record<string, string> = {
  DRAFT: "bg-slate-100 text-slate-600",
  APPROVED: "bg-emerald-50 text-emerald-700",
  PUBLISHED: "bg-brand-soft text-brand-700",
};

/** Buffer-style queue: one row per post (with its version for each platform), in posting order. */
export function QueueList({ posts, onOpen, onApprove }: { posts: SocialPost[]; onOpen: (p: SocialPost) => void; onApprove: (p: SocialPost) => void }) {
  let lastDay = "";
  return (
    <div className="card divide-y divide-slate-100 overflow-hidden">
      {groupPosts(posts).map((g) => {
        const p = g.find((v) => v.image_url) ?? g[0];
        const day = fmtDay(g[0].publish_at, { weekday: "long", month: "long", day: "numeric" });
        const header = day !== lastDay;
        lastDay = day;
        const status = groupStatus(g);
        const drafts = g.filter((v) => v.status === "DRAFT");
        const live = g.filter((v) => v.remote_url);
        return (
          <div key={groupKey(p)}>
            {header && <p className="bg-slate-50/80 px-4 py-2 text-xs font-semibold text-slate-500">{day}</p>}
            <div className="group flex items-center gap-4 px-4 py-3 transition hover:bg-slate-50/60">
              <button onClick={() => onOpen(p)} className="relative h-16 w-16 shrink-0 overflow-hidden rounded-xl bg-slate-100">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={media(p.image_url)} alt="" className="h-full w-full object-cover" />
                {g.some((v) => v.format === "carousel") && <Layers size={13} className="absolute right-1 top-1 text-white drop-shadow" />}
              </button>
              <div className="min-w-0 flex-1">
                <button onClick={() => onOpen(p)} className="block w-full min-w-0 text-left">
                  <p className="truncate text-sm font-semibold">{p.headline}</p>
                  <p className="truncate text-sm text-slate-500">{p.caption}</p>
                </button>
                <div className="mt-1 flex flex-wrap items-center gap-1">
                  {g.map((v) => (
                    <button key={v.id} onClick={() => onOpen(v)} title={`Open the ${PLATFORM_META[v.platform].label} version`}
                      className={`flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] transition hover:border-slate-300 ${
                        v.status === "DRAFT" ? "border-slate-200 text-slate-500" : "border-emerald-200 bg-emerald-50/60 text-emerald-800"}`}>
                      <PlatformIcon platform={v.platform} size={11} /> {fmtTime(v.publish_at)}
                      {v.format === "carousel" && <Layers size={10} />}
                    </button>
                  ))}
                </div>
              </div>
              <span className={`chip hidden sm:inline-flex ${STATUS[status]}`}>{status === "PUBLISHED" ? "posted" : status.toLowerCase()}</span>
              {drafts.length > 0 && (
                <button onClick={() => drafts.forEach(onApprove)} className="btn-ghost btn-sm" title="Approve every platform version">
                  <Check size={14} /> <span className="hidden md:inline">Approve{g.length > 1 ? " all" : ""}</span>
                </button>
              )}
              {live.length > 0 && (
                <a href={live[0].remote_url!} target="_blank" rel="noreferrer" className="btn-ghost btn-sm" title="View live post"><ExternalLink size={14} /></a>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
