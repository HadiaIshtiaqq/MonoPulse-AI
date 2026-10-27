"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle, ArrowDown, ArrowUp, BookOpen, Check, ChevronDown, Clapperboard, Copy, Download, Film, Flame, ImageOff, ImagePlus, Lightbulb, ListOrdered, Loader2,
  PartyPopper, Pause, Pipette, Play, Plus, RefreshCw, Share2, ShoppingBag, Shuffle, Sparkles, Trash2, Undo2, Upload, Volume2, Vote, Wand2,
} from "lucide-react";
import {
  api, logoSrc, media, type BrandKit, type ReelLanguage, type ReelOccasion, type ReelOptions, type ReelOptionsInfo, type ReelPalette, type ReelPhoto,
  type ReelScene, type ReelStyle, type SocialPost,
} from "@/lib/api";
import { canShareVideo, copyText, downloadVideo, shareVideo } from "@/lib/share";
import { useCycle } from "@/components/Motion";
import { useFeedback } from "@/components/Feedback";

const STEPS = ["Writing the script…", "Picking your best product photos…", "Animating every scene…", "Encoding a 1080×1920 MP4…"];
const EDIT_STEPS = ["Applying your edits…", "Animating every scene…", "Encoding a 1080×1920 MP4…"];
const MAX_SCENES = 8;
const LABEL: Record<ReelScene["kind"], string> = { hook: "Opening", product: "Scene", fact: "Scene", cta: "End card" };

/** A /media path or one of the brand's web photos, as an <img> src. */
const photoSrc = (url: string) => (url.startsWith("/media/") ? media(url) : url);

/** A still of one scene, drawn in the browser, so edits show up before the video is rendered. */
function ScenePreview({ scene, brand }: { scene: ReelScene; brand: BrandKit | null }) {
  const primary = brand?.primary_color ?? "#5B47FB";
  const accent = brand?.accent_color ?? "#FF5C8A";
  const logo = logoSrc(brand);
  const centered = scene.kind !== "product";
  return (
    <div className="absolute inset-0 animate-fade-in" style={{ background: `linear-gradient(180deg, ${primary}, color-mix(in srgb, ${primary} 45%, black))` }}>
      {scene.photo && scene.kind !== "cta" && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={photoSrc(scene.photo)} alt="" className={`absolute inset-0 h-full w-full object-cover ${scene.kind === "hook" || scene.kind === "fact" ? "scale-110 blur-md" : ""}`} />
      )}
      {scene.photo && scene.kind !== "product" && scene.kind !== "cta" && <div className="absolute inset-0" style={{ background: `color-mix(in srgb, ${primary} 55%, transparent)` }} />}
      {scene.kind === "product" && <div className="absolute inset-0" style={{ background: `linear-gradient(180deg, transparent 50%, color-mix(in srgb, ${primary} 30%, black) 100%)` }} />}
      {logo && scene.kind !== "cta" && (
        // eslint-disable-next-line @next/next/no-img-element
        <img src={logo} alt="" className="absolute left-[7%] top-[8%] h-[6%] max-w-[30%] rounded-md bg-white object-contain p-1" />
      )}
      {scene.tag && (
        <span className="absolute right-[7%] top-[16%] animate-pop-in rounded-full px-2.5 py-0.5 text-xs font-extrabold" style={{ background: accent, color: "#111" }}>
          {scene.tag}
        </span>
      )}
      <div className={`absolute inset-x-[8%] ${centered ? "top-1/2 -translate-y-1/2 text-center" : "bottom-[9%]"}`}>
        {scene.kind === "cta" && logo && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={logo} alt="" className="mx-auto mb-[12%] h-16 max-w-[60%] rounded-xl bg-white object-contain p-2" />
        )}
        <p className="break-words text-[22px] font-extrabold leading-tight text-white drop-shadow-md">{scene.text || "Add some words"}</p>
        <span className={`mt-3 block h-1 w-12 rounded-full ${centered ? "mx-auto" : ""}`} style={{ background: accent }} />
        {scene.sub && (
          <span className="mt-3 inline-block rounded-full px-3 py-1 text-xs font-bold"
            style={scene.kind === "cta" ? { background: "white", color: primary } : { background: accent, color: "#111" }}>
            {scene.sub}
          </span>
        )}
      </div>
    </div>
  );
}

/** The reel in a phone frame, playing on a loop like it would in the feed, or a still of the scene being edited. */
export function ReelPlayer({ post, brand, preview, onExitPreview }: {
  post: SocialPost; brand: BrandKit | null; preview?: ReelScene | null; onExitPreview?: () => void;
}) {
  const ref = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(true);
  const [progress, setProgress] = useState(0);
  // The frame keeps its 9:16 shape and fits the window's height, so the video is never cropped.
  const frame = "relative aspect-[9/16] shrink-0 overflow-hidden rounded-[2rem] border-[6px] border-ink bg-ink shadow-pop";
  const size = { width: "min(100%, 300px, calc((100dvh - 210px) * 9 / 16))" };

  function toggle() {
    const v = ref.current;
    if (!v) return;
    if (v.paused) { v.play(); setPlaying(true); } else { v.pause(); setPlaying(false); }
  }

  if (preview) {
    return (
      <div className="flex flex-col items-center gap-2">
        <div className={frame} style={size}><ScenePreview scene={preview} brand={brand} /></div>
        <p className="text-xs text-slate-500">Preview of this scene · render to see it move</p>
        {post.video_url && onExitPreview && (
          <button onClick={onExitPreview} className="btn-ghost btn-sm"><Play size={12} /> Play the reel</button>
        )}
      </div>
    );
  }
  if (!post.video_url) {
    return (
      <div className={`${frame} grid place-items-center`} style={size}>
        {post.image_url && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={media(post.image_url)} alt="" className="absolute inset-0 h-full w-full scale-110 object-cover opacity-40 blur-md" />
        )}
        <div className="relative px-6 text-center text-white">
          <Film className="mx-auto mb-3 opacity-80" size={30} />
          <p className="text-sm font-semibold">Your reel will play here</p>
          <p className="mt-1 text-xs text-white/70">9:16 · 10–15 seconds</p>
        </div>
      </div>
    );
  }
  return (
    <div className={`${frame} animate-scale-in`} style={size}>
      <video key={post.video_url} ref={ref} src={media(post.video_url)} poster={media(post.video_poster)} autoPlay muted loop playsInline
        onTimeUpdate={(e) => setProgress(e.currentTarget.currentTime / (e.currentTarget.duration || 1))}
        onClick={toggle} className="h-full w-full cursor-pointer object-contain" aria-label={`${brand?.name ?? ""} reel`} />
      <div className="pointer-events-none absolute inset-x-3 bottom-3 flex items-center gap-2 text-white">
        <span className="grid h-7 w-7 place-items-center rounded-full bg-black/40 backdrop-blur">{playing ? <Pause size={13} /> : <Play size={13} />}</span>
        <span className="h-1 flex-1 overflow-hidden rounded-full bg-white/30">
          <span className="block h-full rounded-full bg-white" style={{ width: `${progress * 100}%` }} />
        </span>
        <span className="grid h-7 w-7 place-items-center rounded-full bg-black/40 backdrop-blur" title="Add music when you post: each app has its own licensed library"><Volume2 size={13} /></span>
      </div>
    </div>
  );
}

function PhotoGrid({ photos, current, allowNone, onPick, onUpload, uploading }: {
  photos: ReelPhoto[] | null; current: string; allowNone: boolean; onPick: (p: ReelPhoto | null) => void;
  onUpload: (f: File) => void; uploading: boolean;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="mt-3 animate-slide-down rounded-xl border border-slate-200 bg-slate-50 p-2">
      <div className="grid max-h-64 grid-cols-4 gap-2 overflow-y-auto p-0.5 sm:grid-cols-5">
        <button type="button" onClick={() => input.current?.click()} disabled={uploading}
          className="grid aspect-[9/16] place-items-center rounded-lg border-2 border-dashed border-slate-300 text-slate-500 transition hover:border-brand hover:text-brand">
          <span className="flex flex-col items-center gap-1 text-[10px] font-medium">{uploading ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />} Upload</span>
        </button>
        {allowNone && (
          <button type="button" onClick={() => onPick(null)}
            className={`grid aspect-[9/16] place-items-center rounded-lg border bg-white text-slate-500 transition hover:border-brand ${current ? "border-slate-200" : "border-brand ring-2 ring-brand-200"}`}>
            <span className="flex flex-col items-center gap-1 px-1 text-center text-[10px] font-medium"><ImageOff size={16} /> Brand colour</span>
          </button>
        )}
        {photos === null && Array.from({ length: 8 }).map((_, i) => <div key={i} className="skeleton aspect-[9/16] rounded-lg" />)}
        {photos?.map((p) => {
          const on = p.url === current;
          return (
            <button type="button" key={p.url} onClick={() => onPick(p)} title={p.label + (p.price ? ` · ${p.price}` : "")}
              className={`group relative aspect-[9/16] overflow-hidden rounded-lg border bg-white transition ${on ? "border-brand ring-2 ring-brand-200" : "border-slate-200 hover:border-brand"}`}>
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={photoSrc(p.url)} alt={p.label} loading="lazy" className="zoom-on-hover h-full w-full object-cover" />
              <span className="absolute inset-x-0 bottom-0 truncate bg-gradient-to-t from-black/70 to-transparent px-1 pb-1 pt-4 text-left text-[9px] font-medium text-white">{p.label}</span>
              {on && <span className="absolute right-1 top-1 grid h-4 w-4 animate-pop-in place-items-center rounded-full bg-brand text-white"><Check size={10} /></span>}
            </button>
          );
        })}
      </div>
      <input ref={input} type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
        onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); e.target.value = ""; }} />
    </div>
  );
}

const FALLBACK_STYLES: ReelStyle[] = [
  { key: "cinematic", label: "Cinematic", blurb: "Full-screen photos, slow zooms, words that rise in, soft crossfades" },
  { key: "punch", label: "Fast cuts", blurb: "Quick cuts with a zoom punch and a flash, bold caption blocks that pop in" },
  { key: "showcase", label: "Showcase", blurb: "Each photo slides in on a floating card over your brand colours" },
  { key: "magazine", label: "Magazine", blurb: "An editorial page: a photo panel, numbered pages, words that write themselves on" },
  { key: "scrapbook", label: "Scrapbook", blurb: "Polaroids that drop onto a pile, with sticker prices" },
];

/** A tiny drawing of each style with the post's own photo and brand colours, so the looks can be compared at a glance. */
function StyleThumb({ style, photo, brand }: { style: string; photo: string; brand: BrandKit | null }) {
  const primary = brand?.primary_color ?? "#5B47FB";
  const accent = brand?.accent_color ?? "#FF5C8A";
  // eslint-disable-next-line @next/next/no-img-element
  const img = photo ? <img src={photoSrc(photo)} alt="" className="h-full w-full object-cover" /> : <span className="block h-full w-full" style={{ background: primary }} />;
  const bar = (w: string, c = "white") => <span className="block h-[3px] rounded-full" style={{ width: w, background: c }} />;
  if (style === "punch") {
    return (
      <span className="relative block h-full w-full overflow-hidden">
        {img}
        <span className="absolute inset-x-1.5 top-[55%] space-y-0.5">
          <span className="mx-auto block h-2 w-9 -rotate-3 rounded-sm bg-white" />
          <span className="mx-auto block h-2 w-7 rotate-2 rounded-sm" style={{ background: accent }} />
        </span>
        <span className="absolute right-1 top-[30%] h-3.5 w-3.5 rounded-full border border-white" style={{ background: accent }} />
      </span>
    );
  }
  if (style === "showcase") {
    return (
      <span className="relative block h-full w-full overflow-hidden" style={{ background: `linear-gradient(180deg, ${primary}, color-mix(in srgb, ${primary} 40%, black))` }}>
        <span className="absolute left-2 top-2.5 space-y-0.5">{bar("26px")}{bar("18px")}</span>
        <span className="absolute inset-x-2 bottom-3 top-[34%] overflow-hidden rounded-md border-2 border-white shadow">{img}</span>
      </span>
    );
  }
  if (style === "magazine") {
    return (
      <span className="relative block h-full w-full overflow-hidden" style={{ background: "#FAF7F2" }}>
        <span className="block h-[55%] overflow-hidden">{img}</span>
        <span className="absolute inset-x-2 top-[61%] space-y-1">{bar("100%", primary)}{bar("70%", "#1f2937")}{bar("50%", "#1f2937")}</span>
        <span className="absolute bottom-1 right-1.5 text-[5px] font-bold text-slate-400">01/05</span>
      </span>
    );
  }
  if (style === "scrapbook") {
    return (
      <span className="relative block h-full w-full overflow-hidden" style={{ backgroundColor: "#FFFBF5", backgroundImage: `radial-gradient(${primary}33 1.2px, transparent 1.2px)`, backgroundSize: "7px 7px" }}>
        <span className="absolute left-1.5 top-[24%] h-[52%] w-[70%] rotate-6 bg-white p-1 pb-3 shadow" />
        <span className="absolute left-2.5 top-[20%] h-[56%] w-[72%] -rotate-6 bg-white p-1 pb-3.5 shadow-md">
          <span className="block h-full overflow-hidden">{img}</span>
        </span>
      </span>
    );
  }
  return (
    <span className="relative block h-full w-full overflow-hidden">
      {img}
      <span className="absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent" />
      <span className="absolute bottom-3 left-2 space-y-0.5">{bar("30px")}{bar("20px")}{bar("12px", accent)}</span>
      <span className="absolute inset-x-0 top-0 h-[2px]" style={{ background: accent }} />
    </span>
  );
}

function StylePicker({ styles, value, current, auto, onPick, photo, brand, disabled }: {
  styles: ReelStyle[]; value: string; current: string; auto: boolean; onPick: (key: string) => void;
  photo: string; brand: BrandKit | null; disabled: boolean;
}) {
  const active = styles.find((s) => s.key === value);
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <p className="label">Look</p>
        <p className="truncate text-[11px] text-slate-500">
          {value ? active?.blurb : "A different look from your other reels, picked for you"}
        </p>
      </div>
      <div className="no-scrollbar -mx-1 flex gap-2 overflow-x-auto px-1 pb-1">
        {auto && (
          <button type="button" onClick={() => onPick("")} disabled={disabled} aria-pressed={!value}
            className={`flex w-[68px] shrink-0 flex-col items-center gap-1 rounded-xl p-1 text-[10px] font-medium transition ${!value ? "bg-brand-soft text-brand-700 ring-2 ring-brand" : "text-slate-600 hover:bg-slate-100"}`}>
            <span className="grid aspect-[9/16] w-full place-items-center rounded-lg bg-brand-gradient text-white"><Shuffle size={16} /></span>
            Surprise me
          </button>
        )}
        {styles.map((s) => {
          const on = s.key === value;
          return (
            <button type="button" key={s.key} onClick={() => onPick(s.key)} disabled={disabled} aria-pressed={on} title={s.blurb}
              className={`group flex w-[68px] shrink-0 flex-col items-center gap-1 rounded-xl p-1 text-[10px] font-medium transition ${on ? "bg-brand-soft text-brand-700 ring-2 ring-brand" : "text-slate-600 hover:bg-slate-100"}`}>
              <span className="relative block aspect-[9/16] w-full overflow-hidden rounded-lg border border-slate-200 transition-transform duration-300 group-hover:-translate-y-0.5">
                <StyleThumb style={s.key} photo={photo} brand={brand} />
                {s.key === current && <span className="absolute left-1 top-1 rounded bg-black/55 px-1 text-[7px] font-semibold uppercase text-white">Now</span>}
              </span>
              {s.label}
            </button>
          );
        })}
      </div>
    </section>
  );
}

const TOPIC_ICONS: Record<string, typeof ShoppingBag> = {
  products: ShoppingBag, countdown: ListOrdered, tips: Lightbulb, poll: Vote, story: BookOpen, occasion: PartyPopper, trend: Flame,
};
const LANG_FALLBACK: { key: ReelLanguage; label: string }[] = [
  { key: "en", label: "English" }, { key: "roman", label: "Roman Urdu" }, { key: "ur", label: "اردو" }, { key: "mix", label: "Mix" },
];

function Chips<T extends string>({ label, hint, value, options, onPick, disabled }: {
  label: string; hint?: string; value: T; options: { key: T; label: string }[]; onPick: (k: T) => void; disabled: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3">
      <p className="label shrink-0" title={hint}>{label}</p>
      <div className="seg">
        {options.map((o) => (
          <button key={o.key} type="button" data-active={value === o.key} onClick={() => onPick(o.key)} disabled={disabled}>{o.label}</button>
        ))}
      </div>
    </div>
  );
}

/** What the reel is about. Each topic is one connected story: a promise, scenes that deliver it, a payoff. */
function TopicPicker({ options, value, suggested, onPick, disabled }: {
  options: ReelOptionsInfo | null; value: string; suggested: string; onPick: (k: string) => void; disabled: boolean;
}) {
  const topics = options?.topics ?? [];
  const active = topics.find((t) => t.key === (value || suggested));
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <p className="label">Topic</p>
        <p className="truncate text-[11px] text-slate-500">{active?.blurb}</p>
      </div>
      <div className="grid grid-cols-3 gap-1.5">
        {topics.map((t) => {
          const Icon = TOPIC_ICONS[t.key] ?? Sparkles;
          const on = (value || suggested) === t.key;
          return (
            <button key={t.key} type="button" onClick={() => onPick(t.key)} disabled={disabled || !t.available}
              title={t.available ? t.blurb : "There isn't enough in this campaign for this one"}
              className={`relative flex items-center gap-1.5 rounded-xl border px-2.5 py-2 text-left text-xs font-medium transition disabled:opacity-35 ${on ? "border-brand bg-brand-soft text-brand-700" : "border-slate-200 bg-white hover:border-slate-300"}`}>
              <Icon size={14} className={on ? "text-brand" : "text-slate-400"} />
              <span className="truncate">{t.label}</span>
              {!value && t.key === suggested && <span className="absolute -top-1.5 right-1.5 rounded bg-brand px-1 text-[8px] font-bold uppercase text-white">Fits</span>}
            </button>
          );
        })}
      </div>
    </section>
  );
}

function OccasionPicker({ occasions, value, onPick, disabled }: {
  occasions: ReelOccasion[]; value: string; onPick: (k: string) => void; disabled: boolean;
}) {
  return (
    <section className="animate-slide-down">
      <p className="label mb-2">Occasion</p>
      <div className="flex flex-wrap gap-1.5">
        {occasions.map((o) => {
          const on = value === o.key;
          return (
            <button key={o.key} type="button" onClick={() => onPick(o.key)} disabled={disabled} title={o.greeting}
              className={`flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition ${on ? "border-ink bg-ink text-white" : "border-slate-200 bg-white hover:border-slate-300"}`}>
              <span className="flex">
                <span className="h-3 w-3 rounded-full border border-white" style={{ background: o.colors[0] }} />
                <span className="-ml-1 h-3 w-3 rounded-full border border-white" style={{ background: o.colors[1] }} />
              </span>
              {o.label}
              {o.soon && <span className={`text-[10px] ${on ? "text-white/70" : "text-brand"}`}>· {o.soon.replace(/^.*\((.*)\)$/, "$1")}</span>}
            </button>
          );
        })}
      </div>
    </section>
  );
}

function ColourPicker({ palettes, value, color, festive, auto, onPick, onColor, disabled }: {
  palettes: ReelPalette[]; value: string; color: string; festive: string[] | null; auto: boolean;
  onPick: (k: string) => void; onColor: (c: string) => void; disabled: boolean;
}) {
  const swatch = (cols: string[]) => (
    <span className="flex h-7 w-7 overflow-hidden rounded-full border border-slate-200 shadow-sm">
      <span className="h-full w-1/2" style={{ background: cols[0] }} />
      <span className="h-full w-1/2" style={{ background: cols[1] }} />
    </span>
  );
  const item = (key: string, label: string, body: React.ReactNode) => (
    <button key={key} type="button" onClick={() => onPick(key)} disabled={disabled} aria-pressed={value === key} title={label}
      className={`flex w-[54px] shrink-0 flex-col items-center gap-1 rounded-xl p-1 text-[10px] font-medium transition ${value === key ? "bg-brand-soft text-brand-700 ring-2 ring-brand" : "text-slate-600 hover:bg-slate-100"}`}>
      {body}
      <span className="w-full truncate text-center">{label}</span>
    </button>
  );
  return (
    <section>
      <p className="label mb-2">Colours</p>
      <div className="no-scrollbar -mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
        {auto && item("", "Mix it up", <span className="grid h-7 w-7 place-items-center rounded-full bg-brand-gradient text-white"><Shuffle size={12} /></span>)}
        {festive && item("occasion", "Festive", swatch(festive))}
        {palettes.map((p) => item(p.key, p.label, swatch(p.colors)))}
        <label className={`flex w-[54px] shrink-0 cursor-pointer flex-col items-center gap-1 rounded-xl p-1 text-[10px] font-medium transition ${value === "custom" ? "bg-brand-soft text-brand-700 ring-2 ring-brand" : "text-slate-600 hover:bg-slate-100"}`}>
          <span className="relative grid h-7 w-7 place-items-center overflow-hidden rounded-full border border-slate-200" style={{ background: color }}>
            <Pipette size={12} className="text-white mix-blend-difference" />
            <input type="color" value={color} disabled={disabled} aria-label="Pick your own colour"
              onChange={(e) => { onColor(e.target.value); onPick("custom"); }} className="absolute inset-0 cursor-pointer opacity-0" />
          </span>
          Your pick
        </label>
      </div>
    </section>
  );
}

export function ReelPanel({ post, brand, caption, onChange, onPreview }: {
  post: SocialPost; brand: BrandKit | null; caption: string; onChange: (p: SocialPost) => void;
  onPreview: (scene: ReelScene | null, colors?: string[]) => void;
}) {
  const { toast, confirm } = useFeedback();
  const brandName = brand?.name ?? "";
  const [busy, setBusy] = useState<"make" | "render" | "share" | "download" | "upload" | "humanize" | null>(null);
  const [info, setInfo] = useState<{ seconds: number; used_llm: boolean } | null>(null);
  const [draft, setDraft] = useState<ReelScene[]>(post.reel_scenes ?? []);
  const [focus, setFocus] = useState<number | null>(null);
  const [picking, setPicking] = useState<number | null>(null);
  const [photos, setPhotos] = useState<ReelPhoto[] | null>(null);
  const [shareable, setShareable] = useState(false);
  const [opts, setOpts] = useState<ReelOptionsInfo | null>(null);
  const [optsError, setOptsError] = useState(false);
  const styles = opts?.styles ?? FALLBACK_STYLES;
  const has = !!post.reel_scenes?.length;
  // "" means "pick for me": the topic that fits the post, a style and palette the campaign hasn't used much.
  const [look, setLook] = useState(post.reel_style ?? "");
  const [topic, setTopic] = useState(post.reel_topic ?? "");
  const [occasion, setOccasion] = useState(post.reel_occasion ?? "");
  const [palette, setPalette] = useState(post.reel_options?.palette ?? "");
  const [color, setColor] = useState(post.reel_options?.color || brand?.primary_color || "#5B47FB");
  const [pace, setPace] = useState<ReelOptions["pace"]>(post.reel_options?.pace ?? "normal");
  const [textCase, setTextCase] = useState<ReelOptions["case"]>(post.reel_options?.case ?? "auto");
  const [language, setLanguage] = useState<ReelLanguage>(post.reel_options?.language ?? "en");
  const [trend, setTrend] = useState(post.reel_topic === "trend" ? post.reel_occasion ?? "" : "");
  const step = useCycle(busy === "render" ? EDIT_STEPS : STEPS, 4500);
  useEffect(() => setShareable(canShareVideo()), []);
  const loadOptions = useCallback(() => {
    setOptsError(false);
    api.reelOptions(post.id).then(setOpts).catch(() => setOptsError(true));
  }, [post.id]);
  useEffect(loadOptions, [loadOptions]);

  const resetChoices = () => {
    setLook(post.reel_style ?? ""); setTopic(post.reel_topic ?? ""); setOccasion(post.reel_occasion ?? "");
    setPalette(post.reel_options?.palette ?? ""); setColor(post.reel_options?.color || brand?.primary_color || "#5B47FB");
    setPace(post.reel_options?.pace ?? "normal"); setTextCase(post.reel_options?.case ?? "auto");
    setLanguage(post.reel_options?.language ?? "en"); setTrend(post.reel_topic === "trend" ? post.reel_occasion ?? "" : "");
  };
  const saved = JSON.stringify(post.reel_scenes ?? []);
  const savedOpts = JSON.stringify([post.reel_style, post.reel_topic, post.reel_occasion, post.reel_options]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { setDraft(JSON.parse(saved)); setFocus(null); setPicking(null); resetChoices(); }, [saved, savedOpts]);
  useEffect(() => { setInfo(null); setPhotos(null); }, [post.group_id]);
  useEffect(() => {
    if (picking !== null && photos === null) api.reelPhotos(post.id).then(setPhotos).catch(() => setPhotos([]));
  }, [picking, photos, post.id]);

  const effectiveTopic = topic || opts?.suggested_topic || "products";
  const effectiveOccasion = occasion || opts?.suggested_occasion || opts?.occasions[0]?.key || "";
  const occasionInfo = opts?.occasions.find((o) => o.key === effectiveOccasion);
  const festive = effectiveTopic === "occasion" && occasionInfo ? occasionInfo.colors : null;
  const previewColors = palette === "occasion" && festive ? festive : palette === "custom" ? [color, color]
    : opts?.palettes.find((p) => p.key === palette)?.colors ?? (festive && !has ? festive : undefined);
  useEffect(() => { onPreview(focus !== null && draft[focus] ? draft[focus] : null, previewColors); },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [focus, draft, onPreview, JSON.stringify(previewColors)]);
  useEffect(() => () => onPreview(null), [onPreview]);

  // A new topic or occasion needs a new script; the look, colours, pace, lettering and edits only need a re-render.
  const storyChanged = has && ((!!topic && topic !== post.reel_topic) || (effectiveTopic === "occasion" && !!occasion && occasion !== post.reel_occasion)
    || (effectiveTopic === "trend" && !!trend && trend !== post.reel_occasion) || language !== (post.reel_options?.language ?? "en"));
  const lookChanged = has && (
    JSON.stringify(draft) !== saved || (!!look && look !== post.reel_style) || (palette !== (post.reel_options?.palette ?? ""))
    || (palette === "custom" && color !== post.reel_options?.color) || pace !== (post.reel_options?.pace ?? "normal")
    || textCase !== (post.reel_options?.case ?? "auto"));
  const dirty = storyChanged || lookChanged;
  const label = (list: { key: string; label: string }[] | undefined, key: string) => list?.find((s) => s.key === key)?.label ?? key;
  const fileBase = `${brandName.replace(/[^\w]+/g, "-").toLowerCase() || "post"}-${post.publish_at.slice(0, 10)}`;
  const options = (): ReelOptions => ({ palette, color: palette === "custom" ? color : "", pace, case: textCase, language });

  async function make(kind: "fresh" | "render", ask = true) {
    if (kind === "fresh" && has && ask && !storyChanged) {  // a fresh script replaces the owner's edits
      const ok = await confirm({ title: "Write a new script?", body: "MonoPlus tells a new story with new words, photos and a new look. Your edits to this reel are replaced.", confirm: "Write a new one" });
      if (!ok) return;
    }
    setBusy(kind === "render" ? "render" : "make");
    try {
      const fresh = kind === "fresh";
      const res = await api.makeReel(post.id, fresh ? {
        // Unchanged choices are left out, so a fresh script moves on to a new topic, look and colours.
        style: look && (!has || look !== post.reel_style) ? look : undefined,
        topic: topic && (!has || topic !== post.reel_topic || storyChanged) ? topic : undefined,
        occasion: effectiveTopic === "occasion" ? effectiveOccasion : undefined,
        trend: effectiveTopic === "trend" && trend ? trend : undefined,
        options: { ...options(), palette: has && palette === post.reel_options?.palette && !storyChanged ? "" : palette },
      } : { scenes: draft, style: look || undefined, options: options() });
      onChange(res.post);
      setInfo(res);
      setFocus(null);
      const what = `${label(opts?.topics, res.topic)} · ${label(styles, res.style)}`;
      toast(fresh ? `Your ${Math.round(res.seconds)}-second reel is ready: ${what}` : `Reel updated: ${what}`);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function humanizeWords() {
    setBusy("humanize");
    try {
      const res = await api.humanizeReel(post.id, draft);
      setDraft(res.scenes);
      toast(res.after < res.before ? `Sounds more human: AI-tell score ${res.before} → ${res.after}` : "Already reads like a person wrote it", "info");
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  async function run(kind: "share" | "download") {
    if (!post.video_url) return;
    setBusy(kind);
    try {
      await copyText(caption);
      if (kind === "share") await shareVideo(post.video_url, caption, fileBase);
      else await downloadVideo(post.video_url, fileBase);
      toast(kind === "share" ? "Shared. The caption is copied too, in case the app drops it." : "Reel downloaded and caption copied", "info");
    } catch (e) {
      if ((e as Error).name !== "AbortError") toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  const edit = (i: number, patch: Partial<ReelScene>) => setDraft((d) => d.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  function move(i: number, by: -1 | 1) {
    setDraft((d) => { const n = [...d]; [n[i], n[i + by]] = [n[i + by], n[i]]; return n; });
    setFocus(i + by);
    setPicking(null);
  }
  function remove(i: number) {
    setDraft((d) => d.filter((_, j) => j !== i));
    setFocus(null);
    setPicking(null);
  }
  function add() {
    const at = draft.length && draft[draft.length - 1].kind === "cta" ? draft.length - 1 : draft.length;
    setDraft((d) => [...d.slice(0, at), { kind: "product", text: "", sub: "", photo: "", tag: "" }, ...d.slice(at)]);
    setFocus(at);
    setPicking(at);
  }
  function pick(i: number, p: ReelPhoto | null) {
    const s = draft[i];
    if (!p) edit(i, { photo: "", kind: s.kind === "product" ? "fact" : s.kind });
    else {
      // A product photo fills in its name and price when the scene has no words yet.
      const named = p.label && !p.label.startsWith("From ");
      edit(i, {
        photo: p.url,
        kind: s.kind === "fact" ? "product" : s.kind,
        text: s.text || (named ? p.label : ""),
        sub: s.kind !== "hook" && !s.sub && p.price ? p.price : s.sub,
      });
    }
    setPicking(null);
  }
  async function upload(i: number, f: File) {
    setBusy("upload");
    try {
      const u = await api.upload(f);
      const photo: ReelPhoto = { url: u.url, label: "Your upload", price: "", remote: false };
      setPhotos((ps) => [photo, ...(ps ?? [])]);
      pick(i, photo);
    } catch (e) {
      toast((e as Error).message, "error");
    } finally {
      setBusy(null);
    }
  }

  const middle = (i: number) => draft[i].kind !== "hook" && draft[i].kind !== "cta";
  const working = busy === "make" || busy === "render";
  const choices = optsError ? (
    <div className="flex items-center gap-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2.5 text-sm text-amber-900">
      <AlertTriangle size={16} className="shrink-0 text-amber-600" />
      <p className="flex-1">Couldn&apos;t reach MonoPlus to load the reel options. Is the server running?</p>
      <button type="button" onClick={loadOptions} className="btn-ghost btn-sm"><RefreshCw size={13} /> Retry</button>
    </div>
  ) : !opts ? (
    <div className="space-y-3" aria-busy="true" aria-label="Loading reel options">
      <div className="skeleton h-4 w-24" />
      <div className="grid grid-cols-3 gap-1.5">{Array.from({ length: 6 }).map((_, i) => <div key={i} className="skeleton h-9 rounded-xl" />)}</div>
      <div className="flex gap-2">{Array.from({ length: 5 }).map((_, i) => <div key={i} className="skeleton aspect-[9/16] w-[60px] rounded-lg" />)}</div>
    </div>
  ) : (
    <>
      <div className="flex items-center justify-between gap-3">
        <p className="label shrink-0" title="The words on screen; product names stay as they are">Language</p>
        <div className="seg">
          {(opts.languages ?? LANG_FALLBACK).map((l) => (
            <button key={l.key} type="button" data-active={language === l.key} onClick={() => setLanguage(l.key)} disabled={busy !== null}>
              {l.key === "ur" ? "اردو" : l.key === "mix" ? "Mix" : l.label}
            </button>
          ))}
        </div>
      </div>
      <TopicPicker options={opts} value={topic} suggested={has ? post.reel_topic ?? "" : opts?.suggested_topic ?? ""}
        onPick={(k) => { setTopic(k); if (k === "occasion" && !palette) setPalette("occasion"); }} disabled={busy !== null} />
      {effectiveTopic === "occasion" && opts && (
        <OccasionPicker occasions={opts.occasions} value={effectiveOccasion} onPick={setOccasion} disabled={busy !== null} />
      )}
      {effectiveTopic === "trend" && (
        <section className="animate-slide-down">
          <p className="label mb-2">Format</p>
          <div className="flex flex-wrap gap-1.5">
            {[{ key: "", label: "Surprise me" }, ...(opts.trends ?? [])].map((t) => (
              <button key={t.key || "any"} type="button" onClick={() => setTrend(t.key)} disabled={busy !== null}
                className={`rounded-full border px-3 py-1 text-xs font-medium transition ${trend === t.key ? "border-ink bg-ink text-white" : "border-slate-200 bg-white hover:border-slate-300"}`}>
                {t.label}
              </button>
            ))}
          </div>
        </section>
      )}
      <StylePicker styles={styles} value={look} current={has ? post.reel_style ?? "" : ""} auto={!has} onPick={setLook} disabled={busy !== null}
        photo={draft.find((s) => s.kind === "product" && s.photo)?.photo || post.background?.thumb_url || ""} brand={brand} />
      <ColourPicker palettes={opts?.palettes ?? []} value={palette} color={color} festive={festive} auto={!has}
        onPick={setPalette} onColor={setColor} disabled={busy !== null} />
      {/* Fine-tuning most reels don't need, folded away so the main choices stay easy to scan. */}
      <details className="group rounded-xl border border-slate-200 bg-white/60 px-3 py-2" open={pace !== "normal" || textCase !== "auto"}>
        <summary className="flex cursor-pointer list-none items-center justify-between text-xs font-medium text-slate-500 hover:text-ink">
          More options: pace and lettering
          <ChevronDown size={14} className="transition-transform duration-300 group-open:rotate-180" />
        </summary>
        <div className="mt-3 space-y-2">
          <Chips label="Pace" hint="How long each scene stays on screen" value={pace} onPick={setPace} disabled={busy !== null}
            options={[{ key: "relaxed", label: "Relaxed" }, { key: "normal", label: "Normal" }, { key: "snappy", label: "Snappy" }]} />
          <Chips label="Text" hint="Capital letters or not; Auto lets the style decide" value={textCase} onPick={setTextCase} disabled={busy !== null}
            options={[{ key: "auto", label: "Auto" }, { key: "normal", label: "Aa" }, { key: "upper", label: "AA" }]} />
        </div>
      </details>
    </>
  );

  return (
    <>
      {!has && (
        <section className="space-y-4 rounded-2xl border border-brand-100 bg-gradient-to-br from-brand-50 to-white p-4">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-gradient text-white shadow-glow"><Clapperboard size={18} /></span>
            <div className="min-w-0">
              <p className="font-semibold">{post.video_url ? "Make an editable version" : "Turn this post into a reel"}</p>
              <p className="mt-0.5 text-sm text-slate-600">
                {post.video_url
                  ? "This reel was made before reels could be edited. Make a new version to change its words and photos."
                  : <>A 10–15 second vertical video from {brandName}&apos;s own photos that tells one story: an opening that makes a
                    promise, scenes that deliver it, and an ending that pays it off. Every word is humanized, and you can change anything afterwards.</>}
              </p>
            </div>
          </div>
          {choices}
          <button onClick={() => make("fresh", false)} disabled={busy !== null} className="btn-gradient w-full">
            {busy === "make" ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />}
            {busy === "make" ? "Making your reel…" : post.video_url ? "Make a new version" : "Make reel"}
          </button>
        </section>
      )}

      {working && (
        <div className="space-y-2" aria-live="polite">
          <div className="h-1.5 overflow-hidden rounded-full bg-brand-100">
            <div className="bg-stripes h-full w-full animate-stripes rounded-full bg-brand" />
          </div>
          <p key={step} className="animate-fade-in text-xs text-slate-500">{step} This takes about 20 seconds.</p>
        </div>
      )}

      {has && <div className="space-y-4">{choices}</div>}

      {draft.length > 0 && (
        <section>
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="label">Scenes{info ? ` · ${info.seconds.toFixed(0)}s${info.used_llm ? " · written by Nemotron" : ""}` : ""}</p>
            <span className="flex items-center gap-3">
              <button onClick={humanizeWords} disabled={busy !== null} className="flex items-center gap-1 text-xs font-medium text-slate-500 transition hover:text-brand disabled:opacity-50">
                {busy === "humanize" ? <Loader2 size={12} className="animate-spin" /> : <Wand2 size={12} />} Humanize words
              </button>
              <button onClick={() => make("fresh")} disabled={busy !== null} className="flex items-center gap-1 text-xs font-medium text-slate-500 transition hover:text-brand disabled:opacity-50">
                <Sparkles size={12} /> Write a new script
              </button>
            </span>
          </div>
          <ol className="stagger space-y-2">
            {draft.map((s, i) => {
              const on = focus === i;
              const n = draft.slice(0, i + 1).filter((x) => x.kind === "product" || x.kind === "fact").length;
              return (
                <li key={i} onFocusCapture={() => setFocus(i)} onClick={() => setFocus(i)}
                  className={`rounded-xl border bg-white p-2.5 transition-all duration-200 ${on ? "border-brand shadow-lift ring-2 ring-brand-100" : "border-slate-200 hover:border-slate-300"}`}>
                  <div className="flex gap-3">
                    {s.kind === "cta" ? (
                      <span className="grid h-[72px] w-[41px] shrink-0 place-items-center rounded-lg text-white" style={{ background: previewColors?.[0] ?? brand?.primary_color ?? "#5B47FB" }}>
                        <Film size={14} />
                      </span>
                    ) : (
                      <button type="button" onClick={() => setPicking(picking === i ? null : i)} title="Change photo"
                        className="group relative h-[72px] w-[41px] shrink-0 overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
                        {s.photo ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={photoSrc(s.photo)} alt="" className="h-full w-full object-cover" />
                        ) : (
                          <span className="grid h-full w-full place-items-center" style={{ background: previewColors?.[0] ?? brand?.primary_color }}><ImageOff size={13} className="text-white/80" /></span>
                        )}
                        <span className="absolute inset-0 grid place-items-center bg-black/45 text-white opacity-0 transition group-hover:opacity-100"><ImagePlus size={14} /></span>
                      </button>
                    )}
                    <div className="min-w-0 flex-1 space-y-1.5">
                      <div className="flex items-center gap-1">
                        <span className={`chip px-2 py-0.5 text-[10px] ${s.kind === "hook" ? "bg-brand-soft text-brand-700" : s.kind === "cta" ? "bg-pop/10 text-pop" : "bg-slate-100 text-slate-600"}`}>
                          {LABEL[s.kind]}{middle(i) ? ` ${n}` : ""}
                        </span>
                        {middle(i) && (
                          <input value={s.tag ?? ""} maxLength={12} onChange={(e) => edit(i, { tag: e.target.value })} placeholder="Label"
                            title="Its place in the story, shown on screen: Tip 1, #2, A…" aria-label="Scene label"
                            className="w-16 rounded-md border border-slate-200 px-1.5 py-0.5 text-[10px] font-semibold text-slate-600 outline-none focus:border-brand" />
                        )}
                        {middle(i) && (
                          <span className="ml-auto flex items-center">
                            <button type="button" onClick={() => move(i, -1)} disabled={i <= 0 || !middle(i - 1)} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-ink disabled:opacity-30" aria-label="Move up"><ArrowUp size={13} /></button>
                            <button type="button" onClick={() => move(i, 1)} disabled={i >= draft.length - 1 || !middle(i + 1)} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-ink disabled:opacity-30" aria-label="Move down"><ArrowDown size={13} /></button>
                            <button type="button" onClick={() => remove(i)} disabled={draft.filter((_, j) => middle(j)).length <= 1} className="rounded p-1 text-slate-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-30" aria-label="Remove scene"><Trash2 size={13} /></button>
                          </span>
                        )}
                      </div>
                      <input value={s.text} maxLength={80} onChange={(e) => edit(i, { text: e.target.value })}
                        placeholder={s.kind === "hook" ? "Words that stop the scroll" : s.kind === "cta" ? "Order now" : "A few words for this photo"}
                        className="input py-1.5 text-sm font-semibold" aria-label={`${LABEL[s.kind]} text`} />
                      {s.kind !== "hook" && (
                        <input value={s.sub} maxLength={40} onChange={(e) => edit(i, { sub: e.target.value })}
                          placeholder={s.kind === "cta" ? "Website or handle" : "Price or short note (optional)"}
                          className="input py-1 text-xs" aria-label={`${LABEL[s.kind]} ${s.kind === "cta" ? "website" : "price"}`} />
                      )}
                    </div>
                  </div>
                  {picking === i && (
                    <PhotoGrid photos={photos} current={s.photo} allowNone={s.kind !== "cta"} uploading={busy === "upload"}
                      onPick={(p) => pick(i, p)} onUpload={(f) => upload(i, f)} />
                  )}
                </li>
              );
            })}
          </ol>
          {draft.length < MAX_SCENES && (
            <button type="button" onClick={add} disabled={busy !== null}
              className="mt-2 flex w-full items-center justify-center gap-1.5 rounded-xl border-2 border-dashed border-slate-200 py-2 text-xs font-medium text-slate-500 transition hover:border-brand hover:text-brand">
              <Plus size={14} /> Add a scene
            </button>
          )}
        </section>
      )}

      {dirty && (
        <div className="sticky bottom-0 -mx-1 flex animate-slide-down gap-2 rounded-xl border border-brand-100 bg-white/95 p-2 shadow-lift backdrop-blur">
          {storyChanged ? (
            <button onClick={() => make("fresh")} disabled={busy !== null} className="btn-gradient flex-1">
              {busy === "make" ? <Loader2 size={15} className="animate-spin" /> : <Sparkles size={15} />}
              Make a {label(opts?.topics, effectiveTopic).toLowerCase()} reel
            </button>
          ) : (
            <button onClick={() => make("render")} disabled={busy !== null} className="btn-primary flex-1">
              {busy === "render" ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />} Render my changes
            </button>
          )}
          <button onClick={() => { setDraft(JSON.parse(saved)); resetChoices(); setFocus(null); setPicking(null); }} disabled={busy !== null} className="btn-ghost">
            <Undo2 size={15} /> Undo
          </button>
        </div>
      )}

      {post.video_url && !dirty && !working && (
        <section className="space-y-3">
          <p className="label">Post it</p>
          <div className="grid grid-cols-2 gap-2">
            <button onClick={() => run("download")} disabled={busy !== null} className="btn-primary">
              {busy === "download" ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />} Download MP4
            </button>
            {shareable ? (
              <button onClick={() => run("share")} disabled={busy !== null} className="btn-ghost">
                {busy === "share" ? <Loader2 size={15} className="animate-spin" /> : <Share2 size={15} />} Share to app
              </button>
            ) : (
              <button onClick={async () => { await copyText(caption); toast("Caption copied", "info"); }} className="btn-ghost">
                <Copy size={15} /> Copy caption
              </button>
            )}
          </div>
          <ul className="space-y-1.5 rounded-xl bg-slate-50 p-3 text-xs text-slate-600">
            <li><span className="font-semibold text-ink">Instagram:</span> Create → Reel → pick the video, add a sound from Instagram&apos;s library, paste the caption.</li>
            <li><span className="font-semibold text-ink">TikTok / YouTube Shorts:</span> Upload → pick the video, add a sound, paste the caption.</li>
            <li className="text-slate-500">Reels come without music on purpose: songs from each app&apos;s own library are licensed for you, and posts with trending sounds reach more people.</li>
          </ul>
        </section>
      )}
    </>
  );
}
