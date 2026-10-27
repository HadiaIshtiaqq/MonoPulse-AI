"use client";

import { useEffect, useRef, useState } from "react";
import {
  ArrowDown, ArrowUp, Check, Clapperboard, Copy, Download, Film, ImageOff, ImagePlus, Loader2, Pause, Play, Plus,
  RefreshCw, Share2, Shuffle, Sparkles, Trash2, Undo2, Upload, Volume2, Wand2,
} from "lucide-react";
import { api, logoSrc, media, type BrandKit, type ReelPhoto, type ReelScene, type ReelStyle, type SocialPost } from "@/lib/api";
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

export function ReelPanel({ post, brand, caption, onChange, onPreview }: {
  post: SocialPost; brand: BrandKit | null; caption: string; onChange: (p: SocialPost) => void;
  onPreview: (scene: ReelScene | null) => void;
}) {
  const { toast, confirm } = useFeedback();
  const brandName = brand?.name ?? "";
  const [busy, setBusy] = useState<"make" | "render" | "share" | "download" | "upload" | null>(null);
  const [info, setInfo] = useState<{ seconds: number; used_llm: boolean } | null>(null);
  const [draft, setDraft] = useState<ReelScene[]>(post.reel_scenes ?? []);
  const [focus, setFocus] = useState<number | null>(null);
  const [picking, setPicking] = useState<number | null>(null);
  const [photos, setPhotos] = useState<ReelPhoto[] | null>(null);
  const [shareable, setShareable] = useState(false);
  const [styles, setStyles] = useState<ReelStyle[]>(FALLBACK_STYLES);
  const [look, setLook] = useState(post.reel_style ?? "");  // "" = pick a different one automatically
  const step = useCycle(busy === "render" ? EDIT_STEPS : STEPS, 4500);
  useEffect(() => setShareable(canShareVideo()), []);
  useEffect(() => { api.reelStyles().then(setStyles).catch(() => {}); }, []);
  useEffect(() => setLook(post.reel_style ?? ""), [post.reel_style, post.group_id]);

  const saved = JSON.stringify(post.reel_scenes ?? []);
  useEffect(() => { setDraft(JSON.parse(saved)); setFocus(null); setPicking(null); }, [saved]);
  useEffect(() => { setInfo(null); setPhotos(null); }, [post.group_id]);
  useEffect(() => { onPreview(focus !== null && draft[focus] ? draft[focus] : null); }, [focus, draft, onPreview]);
  useEffect(() => () => onPreview(null), [onPreview]);
  useEffect(() => {
    if (picking !== null && photos === null) api.reelPhotos(post.id).then(setPhotos).catch(() => setPhotos([]));
  }, [picking, photos, post.id]);

  const styleChanged = !!post.reel_scenes?.length && !!look && look !== post.reel_style;
  const dirty = JSON.stringify(draft) !== saved || styleChanged;
  const styleLabel = (key: string) => styles.find((s) => s.key === key)?.label ?? key;
  const fileBase = `${brandName.replace(/[^\w]+/g, "-").toLowerCase() || "post"}-${post.publish_at.slice(0, 10)}`;

  async function make(scenes?: ReelScene[]) {
    if (!scenes && post.reel_scenes?.length) {  // a fresh script would replace the owner's edits
      const ok = await confirm({ title: "Write a new script?", body: "MonoPlus writes new words and picks photos again. Your edits to this reel are replaced.", confirm: "Write a new one" });
      if (!ok) return;
    }
    setBusy(scenes ? "render" : "make");
    try {
      // A fresh script without a chosen look gets a new one; edits keep the look picked above.
      const res = await api.makeReel(post.id, scenes, scenes ? look || undefined : (look && look !== post.reel_style ? look : undefined));
      onChange(res.post);
      setInfo(res);
      setFocus(null);
      toast(scenes ? `Reel updated · ${styleLabel(res.style)}` : `Your ${Math.round(res.seconds)}-second ${styleLabel(res.style)} reel is ready`);
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
    setDraft((d) => [...d.slice(0, at), { kind: "product", text: "", sub: "", photo: "" }, ...d.slice(at)]);
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

  return (
    <>
      {!post.reel_scenes?.length && (
        <section className="rounded-2xl border border-brand-100 bg-gradient-to-br from-brand-50 to-white p-4">
          <div className="flex items-start gap-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-gradient text-white shadow-glow"><Clapperboard size={18} /></span>
            <div className="min-w-0">
              <p className="font-semibold">{post.video_url ? "Make an editable version" : "Turn this post into a reel"}</p>
              <p className="mt-0.5 text-sm text-slate-600">
                {post.video_url
                  ? "This reel was made before reels could be edited. Make a new version to change its words and photos."
                  : <>A 10–15 second vertical video from {brandName}&apos;s own photos: an AI-written hook, each product with its price,
                    and an end card with your logo. You can change every word and photo afterwards.</>}
              </p>
            </div>
          </div>
          <div className="mt-4">
            <StylePicker styles={styles} value={look} current="" auto onPick={setLook} disabled={busy !== null}
              photo={post.background?.thumb_url || ""} brand={brand} />
          </div>
          <button onClick={() => make()} disabled={busy !== null} className="btn-gradient mt-4 w-full">
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

      {draft.length > 0 && (
        <StylePicker styles={styles} value={look} current={post.reel_style ?? ""} auto={false} onPick={setLook} disabled={busy !== null}
          photo={draft.find((s) => s.kind === "product" && s.photo)?.photo || draft[0]?.photo || ""} brand={brand} />
      )}

      {draft.length > 0 && (
        <section>
          <div className="mb-2 flex items-center justify-between">
            <p className="label">Scenes{info ? ` · ${info.seconds.toFixed(0)}s${info.used_llm ? " · written by Nemotron" : ""}` : ""}</p>
            <button onClick={() => make()} disabled={busy !== null} className="flex items-center gap-1 text-xs font-medium text-slate-500 transition hover:text-brand disabled:opacity-50">
              <Wand2 size={12} /> Write a new script
            </button>
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
                      <span className="grid h-[72px] w-[41px] shrink-0 place-items-center rounded-lg text-white" style={{ background: brand?.primary_color ?? "#5B47FB" }}>
                        <Film size={14} />
                      </span>
                    ) : (
                      <button type="button" onClick={() => setPicking(picking === i ? null : i)} title="Change photo"
                        className="group relative h-[72px] w-[41px] shrink-0 overflow-hidden rounded-lg border border-slate-200 bg-slate-100">
                        {s.photo ? (
                          // eslint-disable-next-line @next/next/no-img-element
                          <img src={photoSrc(s.photo)} alt="" className="h-full w-full object-cover" />
                        ) : (
                          <span className="grid h-full w-full place-items-center" style={{ background: brand?.primary_color }}><ImageOff size={13} className="text-white/80" /></span>
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
          {dirty && (
            <div className="sticky bottom-0 -mx-1 mt-3 flex animate-slide-down gap-2 rounded-xl border border-brand-100 bg-white/95 p-2 shadow-lift backdrop-blur">
              <button onClick={() => make(draft)} disabled={busy !== null} className="btn-primary flex-1">
                {busy === "render" ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />} Render my changes
              </button>
              <button onClick={() => { setDraft(JSON.parse(saved)); setLook(post.reel_style ?? ""); setFocus(null); setPicking(null); }} disabled={busy !== null} className="btn-ghost">
                <Undo2 size={15} /> Undo
              </button>
            </div>
          )}
        </section>
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
