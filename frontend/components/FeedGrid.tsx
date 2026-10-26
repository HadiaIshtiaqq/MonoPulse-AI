"use client";

import { useState } from "react";
import { Layers } from "lucide-react";
import { fmtDay, logoSrc, media, type BrandKit, type Platform, type SocialPost } from "@/lib/api";
import { PLATFORM_META, PlatformIcon } from "@/components/PlatformIcon";

/** Instagram-profile-style grid, so you can judge how the month looks as a feed. */
export function FeedGrid({ posts, brand, platforms, onOpen }: { posts: SocialPost[]; brand: BrandKit | null; platforms: Platform[]; onOpen: (p: SocialPost) => void }) {
  const [platform, setPlatform] = useState<Platform>(platforms.includes("instagram") ? "instagram" : platforms[0]);
  const shown = posts.filter((p) => p.platform === platform).sort((a, b) => b.publish_at.localeCompare(a.publish_at));
  return (
    <div className="card overflow-hidden">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 p-4">
        <div className="flex items-center gap-3">
          {brand?.logo_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={logoSrc(brand) ?? ""} alt="" className="h-12 w-12 rounded-full border border-slate-200 bg-white object-contain p-1" />
          ) : (
            <span className="h-12 w-12 rounded-full" style={{ background: `linear-gradient(135deg, ${brand?.primary_color}, ${brand?.accent_color})` }} />
          )}
          <div>
            <p className="font-semibold">{brand?.name}</p>
            <p className="text-xs text-slate-500">{shown.length} posts scheduled · newest first, like your profile will look</p>
          </div>
        </div>
        <div className="seg">
          {platforms.map((p) => (
            <button key={p} data-active={platform === p} onClick={() => setPlatform(p)} className="flex items-center gap-1">
              <PlatformIcon platform={p} size={12} /> {PLATFORM_META[p].label}
            </button>
          ))}
        </div>
      </div>
      <div className="mx-auto grid max-w-3xl grid-cols-3 gap-1 p-1">
        {shown.map((p) => (
          <button key={p.id} onClick={() => onOpen(p)} className="group relative aspect-[4/5] overflow-hidden bg-slate-100">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={media(p.image_url)} alt={p.alt_text} className="h-full w-full object-cover transition-transform duration-700 ease-out group-hover:scale-[1.05]" />
            {p.format === "carousel" && <Layers size={16} className="absolute right-2 top-2 text-white drop-shadow" />}
            <span className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-black/60 to-transparent px-2 pb-1.5 pt-6 text-left text-[11px] text-white opacity-0 transition group-hover:opacity-100">
              {fmtDay(p.publish_at, { month: "short", day: "numeric" })} · {p.status === "PUBLISHED" ? "posted" : p.status.toLowerCase()}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
