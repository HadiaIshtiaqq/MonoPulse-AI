"use client";

import { useMemo, useState } from "react";
import { Layers } from "lucide-react";
import { localDayKey, media, type SocialPost } from "@/lib/api";
import { PlatformIcon } from "@/components/PlatformIcon";

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
    const byDay = new Map<string, SocialPost[]>();
    let last = addDays(start, days - 1);
    for (const p of posts) {
      const d = dayOf(p.publish_at);
      const k = dateKey(d);
      byDay.set(k, [...(byDay.get(k) || []), p]);
      if (d > last) last = d;
      if (d < start) start = d;
    }
    for (const list of byDay.values()) list.sort((a, b) => a.publish_at.localeCompare(b.publish_at));
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
        {cells.map((d) => {
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
              className={`min-h-[132px] border-b border-r border-slate-100 p-1.5 transition ${
                inRange ? "bg-white" : "bg-slate-50/60"
              } ${dragOver === k ? "bg-indigo-50 ring-2 ring-inset ring-brand" : ""}`}
            >
              <div className="mb-1 flex items-center justify-between px-1">
                <span
                  className={`text-xs ${k === today ? "rounded-full bg-brand px-1.5 font-semibold text-white" : inRange ? "text-slate-600" : "text-slate-300"}`}
                >
                  {d.getDate() === 1 || k === dateKey(start) ? d.toLocaleDateString(undefined, { month: "short", day: "numeric" }) : d.getDate()}
                </span>
              </div>
              <div className="space-y-1.5">
                {list.map((p) => (
                  <button
                    key={p.id}
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData("text/post-id", p.id);
                      e.dataTransfer.effectAllowed = "move";
                    }}
                    onClick={() => onOpen(p)}
                    className={`group block w-full cursor-grab overflow-hidden rounded-lg bg-white text-left ring-2 transition hover:shadow-pop active:cursor-grabbing ${STATUS_RING[p.status]}`}
                  >
                    {p.image_url && (
                      <span className="relative block">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={media(p.image_url)} alt={p.alt_text} className="aspect-square w-full bg-slate-100 object-contain" draggable={false} />
                        {p.format === "carousel" && (
                          <span className="absolute right-1 top-1 flex items-center gap-0.5 rounded-md bg-black/60 px-1 py-0.5 text-[9px] font-semibold text-white">
                            <Layers size={9} /> {p.image_urls.length}
                          </span>
                        )}
                        {p.status === "PUBLISHED" && (
                          <span className="absolute left-1 top-1 rounded-md bg-brand px-1 py-0.5 text-[9px] font-semibold text-white">posted</span>
                        )}
                      </span>
                    )}
                    <div className="flex items-center gap-1 px-1.5 py-1">
                      <PlatformIcon platform={p.platform} size={11} />
                      <span className="truncate text-[11px] text-slate-600">{p.headline}</span>
                    </div>
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
