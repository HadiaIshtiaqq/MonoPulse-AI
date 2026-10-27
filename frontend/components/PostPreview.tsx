"use client";

import { useEffect, useState } from "react";
import { Bookmark, ChevronLeft, ChevronRight, Heart, MessageCircle, MoreHorizontal, Repeat2, Send, Share2, ThumbsUp } from "lucide-react";
import { logoSrc, media, type BrandKit, type SocialPost } from "@/lib/api";

function Avatar({ brand }: { brand: BrandKit | null }) {
  if (brand?.logo_url) {
    const src = logoSrc(brand) ?? "";
    // eslint-disable-next-line @next/next/no-img-element
    return <img src={src} alt="" className="h-9 w-9 rounded-full border border-slate-200 bg-white object-contain p-0.5" />;
  }
  return (
    <span className="grid h-9 w-9 place-items-center rounded-full text-sm font-bold text-white"
      style={{ background: `linear-gradient(135deg, ${brand?.primary_color ?? "#5B47FB"}, ${brand?.accent_color ?? "#FF5C8A"})` }}>
      {(brand?.name ?? "B").slice(0, 1)}
    </span>
  );
}

function Pager({ images, alt, aspect }: { images: string[]; alt: string; aspect: string }) {
  const [i, setI] = useState(0);
  const first = images[0];
  useEffect(() => setI(0), [images.length, first]);
  const many = images.length > 1;
  return (
    <div className={`relative ${aspect} w-full overflow-hidden bg-slate-100`}>
      <div className="flex h-full transition-transform duration-300" style={{ transform: `translateX(-${i * 100}%)` }}>
        {images.map((src, k) => (
          // eslint-disable-next-line @next/next/no-img-element
          <img key={k} src={media(src)} alt={k === 0 ? alt : `${alt} (${k + 1})`} className="h-full w-full shrink-0 object-cover" />
        ))}
      </div>
      {many && (
        <>
          {i > 0 && (
            <button onClick={() => setI(i - 1)} className="absolute left-2 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-full bg-white/90 shadow" aria-label="Previous">
              <ChevronLeft size={16} />
            </button>
          )}
          {i < images.length - 1 && (
            <button onClick={() => setI(i + 1)} className="absolute right-2 top-1/2 grid h-7 w-7 -translate-y-1/2 place-items-center rounded-full bg-white/90 shadow" aria-label="Next">
              <ChevronRight size={16} />
            </button>
          )}
          <span className="absolute right-2 top-2 rounded-full bg-black/60 px-2 py-0.5 text-[11px] font-medium text-white">{i + 1}/{images.length}</span>
          <div className="absolute bottom-2 left-0 right-0 flex justify-center gap-1">
            {images.map((_, k) => <span key={k} className={`h-1.5 w-1.5 rounded-full ${k === i ? "bg-white" : "bg-white/50"}`} />)}
          </div>
        </>
      )}
    </div>
  );
}

function Caption({ text, tags, clamp }: { text: string; tags: string[]; clamp: number }) {
  const [more, setMore] = useState(false);
  const full = `${text}${tags.length ? `\n\n${tags.join(" ")}` : ""}`;
  const long = full.length > clamp;
  return (
    <p className="whitespace-pre-wrap text-[13px] leading-snug text-slate-800">
      {more || !long ? full : `${full.slice(0, clamp).trimEnd()}… `}
      {long && !more && <button onClick={() => setMore(true)} className="text-slate-500">more</button>}
    </p>
  );
}

export function PostPreview({ post, brand }: { post: SocialPost; brand: BrandKit | null }) {
  const images = post.image_urls?.length ? post.image_urls : post.image_url ? [post.image_url] : [];
  const name = brand?.name ?? "Your brand";
  const handle = name.toLowerCase().replace(/[^a-z0-9]+/g, "");

  if (post.platform === "instagram") {
    return (
      <div className="mx-auto w-full max-w-[380px] overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-lift">
        <div className="flex items-center gap-2.5 px-3 py-2.5">
          <Avatar brand={brand} />
          <div className="min-w-0 flex-1 leading-tight">
            <p className="truncate text-[13px] font-semibold">{handle}</p>
            <p className="text-[11px] text-slate-500">{brand?.location || "Sponsored"}</p>
          </div>
          <MoreHorizontal size={18} />
        </div>
        <Pager images={images} alt={post.alt_text} aspect="aspect-[4/5]" />
        <div className="flex items-center gap-3.5 px-3 pt-2.5">
          <Heart size={22} /><MessageCircle size={22} /><Send size={22} />
          <Bookmark size={22} className="ml-auto" />
        </div>
        <div className="space-y-1 px-3 pb-3 pt-2">
          <Caption text={`${handle} ${post.caption}`} tags={post.hashtags} clamp={125} />
        </div>
      </div>
    );
  }

  if (post.platform === "linkedin") {
    return (
      <div className="mx-auto w-full max-w-[460px] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lift">
        <div className="flex items-start gap-2.5 p-3">
          <Avatar brand={brand} />
          <div className="min-w-0 flex-1 leading-tight">
            <p className="truncate text-[13px] font-semibold">{name}</p>
            <p className="truncate text-[11px] text-slate-500">{brand?.tagline || brand?.industry || "Company"}</p>
            <p className="text-[11px] text-slate-500">1h · 🌐</p>
          </div>
        </div>
        <div className="px-3 pb-2"><Caption text={post.caption} tags={post.hashtags} clamp={210} /></div>
        <Pager images={images} alt={post.alt_text} aspect={post.format === "carousel" ? "aspect-[4/5]" : "aspect-square"} />
        <div className="grid grid-cols-4 border-t border-slate-100 px-2 py-1.5 text-[12px] font-medium text-slate-600">
          {[[ThumbsUp, "Like"], [MessageCircle, "Comment"], [Repeat2, "Repost"], [Send, "Send"]].map(([Icon, l]) => {
            const I = Icon as typeof ThumbsUp;
            return <span key={l as string} className="flex items-center justify-center gap-1 py-1.5"><I size={15} /> {l as string}</span>;
          })}
        </div>
      </div>
    );
  }

  if (post.platform === "x") {
    return (
      <div className="mx-auto flex w-full max-w-[480px] gap-2.5 rounded-2xl border border-slate-200 bg-white p-3 shadow-lift">
        <Avatar brand={brand} />
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px]"><span className="font-bold">{name}</span> <span className="text-slate-500">@{handle} · 1h</span></p>
          <div className="mt-0.5"><Caption text={post.caption} tags={post.hashtags} clamp={280} /></div>
          <div className="mt-2 overflow-hidden rounded-2xl border border-slate-200">
            <Pager images={images} alt={post.alt_text} aspect="aspect-video" />
          </div>
          <div className="mt-2 flex justify-between pr-6 text-slate-500">
            <MessageCircle size={16} /><Repeat2 size={16} /><Heart size={16} /><Share2 size={16} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto w-full max-w-[460px] overflow-hidden rounded-xl border border-slate-200 bg-white shadow-lift">
      <div className="flex items-center gap-2.5 p-3">
        <Avatar brand={brand} />
        <div className="leading-tight">
          <p className="text-[13px] font-semibold">{name}</p>
          <p className="text-[11px] text-slate-500">1h · 🌐</p>
        </div>
      </div>
      <div className="px-3 pb-2"><Caption text={post.caption} tags={post.hashtags} clamp={240} /></div>
      <Pager images={images} alt={post.alt_text} aspect="aspect-square" />
      <div className="grid grid-cols-3 border-t border-slate-100 py-1.5 text-[12px] font-medium text-slate-600">
        <span className="flex items-center justify-center gap-1"><ThumbsUp size={15} /> Like</span>
        <span className="flex items-center justify-center gap-1"><MessageCircle size={15} /> Comment</span>
        <span className="flex items-center justify-center gap-1"><Share2 size={15} /> Share</span>
      </div>
    </div>
  );
}
