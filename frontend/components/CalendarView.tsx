"use client";

import { useMemo, useState } from "react";
import { Film, Layers } from "lucide-react";
import { groupKey, groupPosts, groupStatus, KIND_LABELS, localDayKey, media, type SocialPost } from "@/lib/api";
import { PLATFORM_META, PlatformIcon } from "@/components/PlatformIcon";

const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const STATUS_RING: Record<string, string> = {
  DRAFT: "ring-slate-200",
  APPROVED: "ring-emerald-400",
  PUBLISHED: "ring-brand",
};

const dateKey = localDayKey;

/** Local midnight of a YYYY-MM-DD string (the campaign start date). */
function localMidnight(ymd: string) {
  const [y, m, d] = ymd.slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, d);
}

function dayOf(iso: string) {
  const d = new Date(iso);
  return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}

function addDays(d: Date, n: number) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
}

export function CalendarView({
  posts,
  startDate,
  days,
  onOpen,
  onMove,
}: {
  posts: SocialPost[];
  startDate: string;
  days: number;
  onOpen: (p: SocialPost) => void;
  onMove: (p: SocialPost, newDate: string) => void;
}) {
  const [dragOver, setDragOver] = useState<string | null>(null);

  const { cells, byDay, rangeEnd, rangeStart } = useMemo(() => {
    let start = localMidnight(startDate);
    // One card per post idea, holding its versions for every platform.
    const byDay = new Map<string, SocialPost[][]>();
    let last = addDays(start, days - 1);
    for (const g of groupPosts(posts)) {
      const d = dayOf(g.reduce((m, p) => (p.publish_at < m ? p.publish_at : m), g[0].publish_at));
      const k = dateKey(d);
      byDay.set(k, [...(byDay.get(k) || []), g]);
      if (d > last) last = d;
      if (d < start) start = d;
    }
    const gridStart = addDays(start, -((start.getDay() + 6) % 7));
    const gridEnd = addDays(last, 6 - ((last.getDay() + 6) % 7));
    const cells: Date[] = [];
    for (let d = gridStart; d <= gridEnd; d = addDays(d, 1)) cells.push(d);
    return { cells, byDay, rangeEnd: last, rangeStart: start };
  }, [posts, startDate, days]);

  const start = rangeStart;
  const today = dateKey(new Date());

  return (
    <div className="card overflow-hidden">
      <div className="grid grid-cols-7 border-b border-slate-200 bg-slate-50 text-center text-xs font-medium text-slate-500">
        {DOW.map((d) => (
          <div key={d} className="py-2">
            {d}
          </div>
        ))}
      </div>
      <div className="grid grid-cols-7">
        {cells.map((d, ci) => {
          const k = dateKey(d);
          const inRange = d >= start && d <= rangeEnd;
          const list = byDay.get(k) || [];
          return (
            <div
              key={k}
              onDragOver={(e) => {
                if (!inRange) return;
                e.preventDefault();
                setDragOver(k);
              }}
              onDragLeave={() => setDragOver((cur) => (cur === k ? null : cur))}
              onDrop={(e) => {
                e.preventDefault();
                setDragOver(null);
                const id = e.dataTransfer.getData("text/post-id");
                const post = posts.find((p) => p.id === id);
                if (post && dateKey(new Date(post.publish_at)) !== k) onMove(post, k);
              }}
              style={{ animationDelay: `${Math.min(ci, 41) * 12}ms` }}
              className={`min-h-[132px] animate-fade-in border-b border-r border-slate-100 p-1.5 transition-colors duration-200 ${
                inRange ? "bg-white" : "bg-slate-50/60"
              } ${dragOver === k ? "bg-indigo-50 ring-2 ring-inset ring-brand" : ""}`}
            >
              <div className="mb-1 flex items-center justify-between px-1">
                <span
                  className={`text-xs ${k === today ? "animate-pulse-ring rounded-full bg-brand px-1.5 font-semibold text-white" : inRange ? "text-slate-600" : "text-slate-300"}`}
                >
                  {d.getDate() === 1 || k === dateKey(start) ? d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) : d.getDate()}
                </span>
              </div>
              <div className="space-y-1.5">
                {list.map((g) => {
                  const p = g.find((v) => v.image_url) ?? g[0];
                  const posted = g.filter((v) => v.status === "PUBLISHED").length;
                  return (
                    <div
                      key={groupKey(p)}
                      role="button"
                      tabIndex={0}
                      draggable
                      onDragStart={(e) => {
                        e.dataTransfer.setData("text/post-id", p.id);
                        e.dataTransfer.effectAllowed = "move";
                      }}
                      onClick={() => onOpen(p)}
                      onKeyDown={(e) => { if (e.key === "Enter") onOpen(p); }}
                      className={`group block w-full cursor-grab animate-scale-in overflow-hidden rounded-lg bg-white text-left ring-2 transition-all duration-300 ease-out hover:-translate-y-0.5 hover:shadow-pop active:scale-[.98] active:cursor-grabbing ${STATUS_RING[groupStatus(g)]}`}
                      style={{ animationDelay: `${Math.min(ci, 41) * 12 + 80}ms` }}
                    >
                      {p.image_url && (
                        <span className="relative block overflow-hidden">
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          <img src={media(p.image_url)} alt={p.alt_text} className="zoom-on-hover aspect-square w-full bg-slate-100 object-contain" draggable={false} />
                          {g.some((v) => v.format === "carousel") && (
                            <span className="absolute right-1 top-1 flex items-center gap-0.5 rounded-md bg-black/60 px-1 py-0.5 text-[9px] font-semibold text-white">
                              <Layers size={9} /> {Math.max(...g.map((v) => v.image_urls.length))}
                            </span>
                          )}
                          {g.some((v) => v.video_url) && (
                            <span title="Has a reel" className="absolute bottom-1 right-1 grid h-5 w-5 animate-pop-in place-items-center rounded-md bg-brand-gradient text-white shadow">
                              <Film size={10} />
                            </span>
                          )}
                          {posted > 0 && (
                            <span className="absolute left-1 top-1 rounded-md bg-brand px-1 py-0.5 text-[9px] font-semibold text-white">
                              posted{posted < g.length ? ` ${posted}/${g.length}` : ""}
                            </span>
                          )}
                        </span>
                      )}
                      <p className="truncate px-1.5 pt-1 text-[11px] text-slate-600">
                        {p.kind && p.kind !== "spotlight" && <span className="mr-1 font-semibold text-brand-700">{KIND_LABELS[p.kind]} ·</span>}
                        {p.headline}
                      </p>
                      <div className="flex items-center gap-0.5 px-1 pb-1">
                        {g.map((v) => (
                          <button key={v.id} type="button" onClick={(e) => { e.stopPropagation(); onOpen(v); }}
                            title={`Open the ${PLATFORM_META[v.platform].label} version`}
                            className={`grid h-5 w-5 place-items-center rounded-md transition hover:bg-slate-100 ${v.status === "DRAFT" ? "opacity-60" : ""}`}>
                            <PlatformIcon platform={v.platform} size={11} />
                          </button>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
