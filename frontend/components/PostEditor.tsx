"use client";

import { useEffect, useState } from "react";
import {
  Check, ChevronLeft, ChevronRight, Copy, Download, ExternalLink, History, ImageOff, Loader2, Palette, PenLine, Plus,
  RefreshCw, Rocket, Send, Trash2, Wand2, X,
} from "lucide-react";
import {
  api, fmtDay, fmtTime, fromLocalInput, media, toLocalInput, type BrandKit, type HumanizeMode, type Layout, type Pattern, type PostUpdate, type Slide, type SocialPost, type TextPosition,
} from "@/lib/api";
import { PLATFORM_META, PlatformIcon } from "@/components/PlatformIcon";
import { PostPreview } from "@/components/PostPreview";
import { PhotoPicker } from "@/components/PhotoPicker";
import { TellScore } from "@/components/TellScore";
import { canShareFiles, copyImage, copyText, downloadAll, pasteKey, shareToApp } from "@/lib/share";

/** What to do in the platform's tab after "Open …", given what MonoPlus could hand over. */
function shareSteps(platform: SocialPost["platform"], imageOnClipboard: boolean, multi: boolean, count: number): string[] {
  const paste = pasteKey();
  const label = PLATFORM_META[platform].label;
  const attach = imageOnClipboard
    ? `Click in the post box and press ${paste}: your image attaches.`
    : `Attach the downloaded image${count > 1 ? `s (${count} slides, in order)` : ""}.`;
  if (platform === "instagram") {
    return [
      `Your image${count > 1 ? "s were" : " was"} downloaded and the caption copied.`,
      `In Instagram, click Create → Post → Select from computer and choose the image${count > 1 ? "s in order" : ""}.`,
      `On the caption step press ${paste}, then Share.`,
    ];
  }
  if (platform === "facebook") {
    return [
      `In Facebook, click "What's on your mind?". ${attach}`,
      `Click "Copy caption" below and paste it (${paste}) into the post.`,
      "Click Post.",
    ];
  }
  return [`${label} is open with your caption already in the post box.`, multi ? attach.replace("Click in the post box and press", "Press") : attach, "Click Post."];
}

type Tab = "design" | "copy" | "publish";
const LAYOUTS: { id: Layout; label: string }[] = [
  { id: "bold", label: "Bold" },
  { id: "split", label: "Split" },
  { id: "quote", label: "Quote" },
  { id: "photo", label: "Photo" },
];
const POSITIONS: { id: TextPosition; label: string }[] = [
  { id: "auto", label: "Auto" },
  { id: "top", label: "Top" },
  { id: "center", label: "Middle" },
  { id: "bottom", label: "Bottom" },
];
const TONES = ["casual", "professional", "playful", "urgent", "storytelling"];
const MODES: { id: HumanizeMode; label: string; hint: string }[] = [
  { id: "light", label: "Light", hint: "Instant rule pass: stock phrases, dashes, stiff grammar." },
  { id: "standard", label: "Standard", hint: "Rules, then a Nemotron rewrite guided by Wikipedia's \"Signs of AI writing\" patterns." },
  { id: "deep", label: "Deep", hint: "Translation chain (EN→ZH→JA→EN) on Nemotron, then the standard pass. Slowest, biggest change." },
];


/** Preview width that keeps the whole post (header, image, actions, caption) inside the viewport. */
function previewWidth(post: SocialPost): string {
  const tall = post.platform === "instagram" || (post.platform === "linkedin" && post.format === "carousel");
  if (post.platform === "x") return "min(100%, 480px)";
  return tall ? "min(100%, 380px, max(240px, calc((100dvh - 330px) * 0.8)))" : "min(100%, 440px, max(260px, calc(100dvh - 360px)))";
}

export function PostEditor({
  post,
  brand,
  connected,
  onClose,
  onChange,
  onPrev,
  onNext,
  versions = [],
  onSwitch,
}: {
  post: SocialPost;
  brand: BrandKit | null;
  connected: boolean;
  onClose: () => void;
  onChange: (p: SocialPost) => void;
  onPrev?: () => void;
  onNext?: () => void;
  versions?: SocialPost[];
  onSwitch?: (id: string) => void;
}) {
  const [tab, setTab] = useState<Tab>("design");
  const [headline, setHeadline] = useState(post.headline);
  const [caption, setCaption] = useState(post.caption);
  const [hashtags, setHashtags] = useState(post.hashtags.join(" "));
  const [cta, setCta] = useState(post.cta);
  const [slides, setSlides] = useState<Slide[]>(post.slides);
  const [scale, setScale] = useState(post.text_scale);
  const [when, setWhen] = useState(toLocalInput(post.publish_at));
  const [busy, setBusy] = useState<string | null>(null);
  const [notice, setNotice] = useState<{ kind: "ok" | "err"; text: string } | null>(null);
  const [mode, setMode] = useState<HumanizeMode>("standard");
  const [tone, setTone] = useState("casual");
  const [showDraft, setShowDraft] = useState(false);
  const [patterns, setPatterns] = useState<{ before: Pattern[]; after: Pattern[] } | null>(null);
  const [guide, setGuide] = useState<{ imageOnClipboard: boolean; multi: boolean } | null>(null);
  const [sheet, setSheet] = useState(false);
  useEffect(() => setSheet(canShareFiles()), []);

  useEffect(() => {
    setHeadline(post.headline); setCaption(post.caption); setHashtags(post.hashtags.join(" ")); setCta(post.cta);
    setSlides(post.slides); setScale(post.text_scale); setWhen(toLocalInput(post.publish_at));
  }, [post]);
  useEffect(() => { setNotice(null); setPatterns(null); setShowDraft(false); setGuide(null); }, [post.id]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      if ((e.target as HTMLElement)?.tagName?.match(/INPUT|TEXTAREA|SELECT/)) return;
      if (e.key === "ArrowLeft" && onPrev) onPrev();
      if (e.key === "ArrowRight" && onNext) onNext();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, onPrev, onNext]);

  async function run(key: string, fn: () => Promise<SocialPost | void>, ok?: string) {
    setBusy(key);
    setNotice(null);
    try {
      const updated = await fn();
      if (updated) onChange(updated);
      if (ok) setNotice({ kind: "ok", text: ok });
    } catch (e) {
      setNotice({ kind: "err", text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }

  const update = (body: PostUpdate, ok?: string, key = "save") => run(key, () => api.updatePost(post.id, body), ok);

  const copyDirty = caption !== post.caption || hashtags !== post.hashtags.join(" ");
  const charCount = caption.length + (hashtags ? hashtags.length + 2 : 0);
  const slidesDirty = JSON.stringify(slides) !== JSON.stringify(post.slides);

  const fileBase = `${(brand?.name || "post").replace(/[^\w]+/g, "-").toLowerCase()}-${post.platform}`;
  const fullCaption = `${caption}\n\n${hashtags}`.trim();

  async function openApp() {
    // Open the tab inside the click so pop-up blockers allow it; point it at the platform below.
    const tab = window.open("about:blank", "_blank");
    setBusy("share");
    setNotice(null);
    try {
      if (copyDirty) onChange(await api.updatePost(post.id, { caption, hashtags: hashtags.split(/\s+/).filter(Boolean) }));
      const share = await api.share(post.id);
      // X and LinkedIn take the caption in the link; everyone else gets it from the clipboard.
      // A single image goes on the clipboard so pasting into the post box attaches it;
      // Instagram's website (and multi-image carousels) need the files instead.
      const multi = images.length > 1 || post.platform === "instagram";
      let imageOnClipboard = false;
      if (multi) {
        await copyText(share.caption);
        await downloadAll(images, fileBase);
      } else {
        imageOnClipboard = await copyImage(images[0]);
        if (!imageOnClipboard) await downloadAll(images, fileBase);
      }
      if (tab) tab.location.href = share.url;
      else window.open(share.url, "_blank");
      setGuide({ imageOnClipboard, multi });
    } catch (e) {
      tab?.close();
      setNotice({ kind: "err", text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }

  async function shareSheet() {
    setBusy("sheet");
    setNotice(null);
    try {
      await copyText(fullCaption); // Facebook and Instagram drop shared text, so it's ready to paste
      await shareToApp(images, fullCaption, fileBase);
      setNotice({ kind: "ok", text: "Shared. If the app didn't keep the caption, it's copied: just paste it. Then click \"Mark as posted\"." });
    } catch (e) {
      if ((e as Error).name !== "AbortError") setNotice({ kind: "err", text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }

  const when_ = new Date(post.publish_at);
  const images = post.image_urls?.length ? post.image_urls : post.image_url ? [post.image_url] : [];

  return (
    <div className="fixed inset-0 z-40 flex items-stretch justify-center bg-ink/40 backdrop-blur-sm sm:p-4" onClick={onClose}>
      <div className="flex h-full w-full max-w-6xl flex-col overflow-hidden bg-white shadow-pop sm:rounded-3xl" onClick={(e) => e.stopPropagation()}>
        {/* header */}
        <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3">
          <div className="flex items-center gap-1">
            <button onClick={onPrev} disabled={!onPrev} className="rounded-lg p-1.5 hover:bg-slate-100 disabled:opacity-30" aria-label="Previous post"><ChevronLeft size={18} /></button>
            <button onClick={onNext} disabled={!onNext} className="rounded-lg p-1.5 hover:bg-slate-100 disabled:opacity-30" aria-label="Next post"><ChevronRight size={18} /></button>
          </div>
          {versions.length > 1 && onSwitch ? (
            <div className="flex items-center gap-0.5 rounded-xl bg-slate-100 p-0.5" role="tablist" aria-label="Platform version">
              {versions.map((v) => (
                <button key={v.id} role="tab" aria-selected={v.id === post.id} onClick={() => onSwitch(v.id)}
                  title={`${PLATFORM_META[v.platform].label} version · ${v.status.toLowerCase()}`}
                  className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-xs font-medium transition ${
                    v.id === post.id ? "bg-white text-ink shadow-sm" : "text-slate-500 hover:text-ink"}`}>
                  <PlatformIcon platform={v.platform} size={12} />
                  <span className="hidden lg:inline">{PLATFORM_META[v.platform].label}</span>
                  {v.status !== "DRAFT" && <Check size={11} className="text-emerald-600" />}
                </button>
              ))}
            </div>
          ) : (
            <span className={`chip ${PLATFORM_META[post.platform].bg}`}><PlatformIcon platform={post.platform} size={12} /> {PLATFORM_META[post.platform].label}</span>
          )}
          {post.format === "carousel" && <span className="chip bg-brand-soft text-brand-700">Carousel · {images.length} slides</span>}
          <span className="hidden text-sm text-slate-500 sm:inline">
            {fmtDay(when_.toISOString())} · {fmtTime(when_.toISOString())}
          </span>
          <span className={`chip ${post.status === "APPROVED" ? "bg-emerald-50 text-emerald-700" : post.status === "PUBLISHED" ? "bg-brand-soft text-brand-700" : "bg-slate-100 text-slate-600"}`}>
            {post.status.toLowerCase()}
          </span>
          <button onClick={onClose} className="ml-auto rounded-lg p-2 hover:bg-slate-100" aria-label="Close"><X size={18} /></button>
        </div>

        <div className="grid min-h-0 flex-1 overflow-y-auto md:grid-cols-[1fr_1.05fr] md:overflow-hidden">
          {/* preview */}
          <div className="flex flex-col items-center gap-3 bg-[radial-gradient(circle_at_top,#EFEDFF,transparent_60%)] p-5 md:overflow-y-auto">
            <div style={{ width: previewWidth(post) }}>
              <PostPreview post={{ ...post, caption: showDraft && post.original_caption ? post.original_caption : caption, hashtags: hashtags.split(/\s+/).filter(Boolean) }} brand={brand} />
            </div>
            {post.background?.credit && post.background.source === "stock" && (
              <a href={post.background.credit_url} target="_blank" rel="noreferrer" className="max-w-[380px] truncate text-[11px] text-slate-500 hover:text-ink">
                {post.background.credit}
              </a>
            )}
            {post.trend_title && (
              <a href={post.trend_url || "#"} target="_blank" rel="noreferrer"
                className="flex max-w-[380px] items-start gap-1.5 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900 hover:underline">
                <span className="font-semibold">Trend hook:</span> {post.trend_title} <ExternalLink size={11} className="mt-0.5 shrink-0" />
              </a>
            )}
          </div>

          {/* controls */}
          <div className="flex min-h-0 flex-col border-l border-slate-100">
            <div className="flex gap-1 border-b border-slate-100 px-4 pt-3">
              {([["design", "Design", Palette], ["copy", "Caption", PenLine], ["publish", "Post", Rocket]] as const).map(([key, label, Icon]) => (
                <button key={key} onClick={() => setTab(key)}
                  className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm font-medium ${tab === key ? "border-brand text-brand" : "border-transparent text-slate-500 hover:text-ink"}`}>
                  <Icon size={14} /> {label}
                </button>
              ))}
            </div>

            <div className="flex-1 space-y-5 overflow-y-auto p-5">
              {tab === "design" && (
                <>
                  <section>
                    <p className="label mb-2">Template</p>
                    <div className="grid grid-cols-4 gap-2">
                      {LAYOUTS.map((l) => (
                        <button key={l.id} disabled={busy !== null || (l.id === "photo" && !post.background)}
                          title={l.id === "photo" && !post.background ? "Pick a photo below first" : ""}
                          onClick={() => update({ layout: l.id }, undefined, "layout")}
                          className={`rounded-xl border px-2 py-2 text-xs font-medium transition disabled:opacity-40 ${post.layout === l.id ? "border-brand bg-brand-soft text-brand-700" : "border-slate-200 hover:border-slate-300"}`}>
                          {l.label}
                        </button>
                      ))}
                    </div>
                  </section>

                  <section>
                    <div className="mb-2 flex items-center justify-between">
                      <p className="label">Background photo</p>
                      {post.background && (
                        <button onClick={() => update({ clear_background: true }, "Photo removed", "bg")} className="flex items-center gap-1 text-xs text-slate-500 hover:text-red-600">
                          <ImageOff size={12} /> Remove
                        </button>
                      )}
                    </div>
                    {post.background && (
                      <div className="mb-2 flex items-center gap-2 rounded-xl bg-slate-50 p-2">
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={media(post.background.thumb_url)} alt="" className="h-12 w-10 rounded-md object-cover" />
                        <p className="min-w-0 flex-1 truncate text-xs text-slate-600">{post.background.credit}</p>
                      </div>
                    )}
                    <PhotoPicker
                      defaultQuery={[brand?.industry, post.pillar !== "Offers & News" ? "" : "product"].filter(Boolean).join(" ") || headline}
                      busy={busy !== null}
                      sitePhotos={[
                        ...(brand?.products ?? []).filter((p) => p.image_url).map((p) => ({ url: p.image_url, label: [p.name, p.price].filter(Boolean).join(" · ") })),
                        ...(brand?.images ?? []).filter((u) => !(brand?.products ?? []).some((p) => p.image_url === u)).map((u) => ({ url: u, label: "Photo from your site" })),
                      ]}
                      onPickSite={(url) => run("bg", () => api.setBackground(post.id, { source: "website", image_url: url }), "Photo applied")}
                      onPickStock={(p) => run("bg", () => api.setBackground(post.id, { source: "stock", photo_id: p.id }), "Photo applied")}
                      onPickUpload={(id) => run("bg", () => api.setBackground(post.id, { source: "upload", upload_id: id }), "Your photo applied")}
                    />
                    {busy === "bg" && <p className="mt-1 flex items-center gap-1 text-xs text-slate-500"><Loader2 size={12} className="animate-spin" /> Applying photo…</p>}
                  </section>

                  <section>
                    <p className="label mb-2">{post.format === "carousel" ? "Cover headline" : "Headline on image"}</p>
                    <div className="flex gap-2">
                      <input value={headline} onChange={(e) => setHeadline(e.target.value)} className="input" maxLength={90} />
                      <button onClick={() => update({ headline }, "Image updated", "headline")} disabled={busy !== null || headline === post.headline} className="btn-ghost btn-sm shrink-0">
                        {busy === "headline" ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Apply
                      </button>
                    </div>
                    <div className="mt-3 flex flex-wrap items-center gap-3">
                      <div className="seg">
                        {POSITIONS.map((p) => (
                          <button key={p.id} data-active={post.text_position === p.id} disabled={busy !== null} onClick={() => update({ text_position: p.id }, undefined, "pos")}>{p.label}</button>
                        ))}
                      </div>
                      <label className="flex flex-1 items-center gap-2 text-xs text-slate-500">
                        Size
                        <input type="range" min={0.7} max={1.4} step={0.05} value={scale} onChange={(e) => setScale(Number(e.target.value))}
                          onMouseUp={() => scale !== post.text_scale && update({ text_scale: scale }, undefined, "scale")}
                          onTouchEnd={() => scale !== post.text_scale && update({ text_scale: scale }, undefined, "scale")}
                          onKeyUp={() => scale !== post.text_scale && update({ text_scale: scale }, undefined, "scale")} className="flex-1 accent-[#5B47FB]" />
                        <span className="w-9 tabular-nums">{Math.round(scale * 100)}%</span>
                      </label>
                    </div>
                  </section>

                  {post.format === "carousel" && (
                    <section>
                      <div className="mb-2 flex items-center justify-between">
                        <p className="label">Carousel slides</p>
                        <span className="text-xs text-slate-400">Cover + {slides.length} slides + CTA</span>
                      </div>
                      <div className="space-y-2">
                        {slides.map((s, i) => (
                          <div key={i} className="rounded-xl border border-slate-200 p-2.5">
                            <div className="flex items-center gap-2">
                              <span className="grid h-6 w-6 shrink-0 place-items-center rounded-md bg-brand-soft text-[11px] font-bold text-brand-700">{i + 2}</span>
                              <input className="input py-1.5" value={s.headline} placeholder="Slide headline"
                                onChange={(e) => setSlides(slides.map((x, k) => (k === i ? { ...x, headline: e.target.value } : x)))} />
                              <button onClick={() => setSlides(slides.filter((_, k) => k !== i))} disabled={slides.length <= 1}
                                className="rounded p-1 text-slate-400 hover:text-red-600 disabled:opacity-30" aria-label="Remove slide"><Trash2 size={14} /></button>
                            </div>
                            <textarea className="input mt-2 min-h-[60px] resize-y py-1.5" value={s.body} placeholder="Slide text"
                              onChange={(e) => setSlides(slides.map((x, k) => (k === i ? { ...x, body: e.target.value } : x)))} />
                          </div>
                        ))}
                      </div>
                      <div className="mt-2 flex gap-2">
                        <button onClick={() => setSlides([...slides, { headline: "", body: "" }])} disabled={slides.length >= 8} className="btn-ghost btn-sm"><Plus size={14} /> Add slide</button>
                        <button onClick={() => update({ slides }, "Slides updated", "slides")} disabled={!slidesDirty || busy !== null} className="btn-primary btn-sm ml-auto">
                          {busy === "slides" ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Save slides
                        </button>
                      </div>
                      <label className="mt-3 block">
                        <span className="label">Last slide call to action</span>
                        <div className="mt-1 flex gap-2">
                          <input className="input" value={cta} onChange={(e) => setCta(e.target.value)} />
                          <button onClick={() => update({ cta }, "CTA updated", "cta")} disabled={cta === post.cta || busy !== null} className="btn-ghost btn-sm shrink-0">Apply</button>
                        </div>
                      </label>
                    </section>
                  )}
                </>
              )}

              {tab === "copy" && (
                <>
                  <section>
                    <div className="mb-2 flex items-center justify-between">
                      <p className="label">Caption</p>
                      <TellScore before={post.ai_tell_before} after={post.ai_tell_after} />
                    </div>
                    {showDraft && post.original_caption ? (
                      <div className="min-h-[180px] whitespace-pre-wrap rounded-xl border border-dashed border-slate-300 bg-slate-50 p-3 text-sm text-slate-500">{post.original_caption}</div>
                    ) : (
                      <textarea value={caption} onChange={(e) => setCaption(e.target.value)} className="input min-h-[180px] resize-y leading-relaxed" />
                    )}
                    <div className="mt-1 flex items-center justify-between text-xs">
                      {post.original_caption ? (
                        <button onClick={() => setShowDraft((s) => !s)} className="flex items-center gap-1 text-slate-500 hover:text-ink">
                          <History size={12} /> {showDraft ? "Back to current caption" : "Compare with the AI draft"}
                        </button>
                      ) : <span />}
                      <span className={post.platform === "x" && charCount > 280 ? "font-medium text-red-600" : "text-slate-400"}>
                        {charCount}{post.platform === "x" ? " / 280" : ""} characters
                      </span>
                    </div>
                  </section>

                  <section className="rounded-2xl border border-slate-200 p-4">
                    <div className="flex items-center justify-between">
                      <p className="flex items-center gap-1.5 text-sm font-semibold"><Wand2 size={15} className="text-brand" /> Humanize</p>
                      <div className="seg">
                        {MODES.map((m) => <button key={m.id} data-active={mode === m.id} onClick={() => setMode(m.id)}>{m.label}</button>)}
                      </div>
                    </div>
                    <p className="mt-1.5 text-xs text-slate-500">{MODES.find((m) => m.id === mode)?.hint}</p>
                    <button className="btn-primary btn-sm mt-3" disabled={busy !== null || copyDirty} title={copyDirty ? "Save your edits first" : ""}
                      onClick={() => run("humanize", async () => {
                        const r = await api.humanizePost(post.id, mode);
                        setPatterns({ before: r.patterns_before, after: r.patterns_after });
                        return r.post;
                      }, "Caption humanized")}>
                      {busy === "humanize" ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />} Humanize caption
                    </button>
                    {patterns && (
                      <div className="mt-3 space-y-1.5 text-xs">
                        {patterns.before.length === 0 ? <p className="text-emerald-700">No AI-writing patterns found.</p> : patterns.before.map((p) => {
                          const left = patterns.after.find((a) => a.id === p.id);
                          return (
                            <p key={p.id} className="flex items-center gap-2">
                              <span className={`h-1.5 w-1.5 rounded-full ${left ? "bg-amber-500" : "bg-emerald-500"}`} />
                              <span className={left ? "" : "text-slate-400 line-through"}>{p.label}</span>
                              {p.example && <span className="truncate text-slate-400">“{p.example}”</span>}
                            </p>
                          );
                        })}
                      </div>
                    )}
                  </section>

                  <section className="flex flex-wrap items-center gap-2">
                    <select value={tone} onChange={(e) => setTone(e.target.value)} className="input w-auto py-1.5 text-xs">
                      {TONES.map((t) => <option key={t}>{t}</option>)}
                    </select>
                    <button onClick={() => run("rewrite", () => api.rewritePost(post.id, tone), `Rewritten in a ${tone} tone`)} disabled={busy !== null} className="btn-ghost btn-sm">
                      {busy === "rewrite" ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />} Rewrite tone
                    </button>
                  </section>

                  <section>
                    <p className="label mb-2">Hashtags</p>
                    <input value={hashtags} onChange={(e) => setHashtags(e.target.value)} className="input font-mono text-xs" />
                  </section>

                  <button onClick={() => update({ caption, hashtags: hashtags.split(/\s+/).filter(Boolean) }, "Saved")} disabled={!copyDirty || busy !== null} className="btn-primary w-full">
                    {busy === "save" ? <Loader2 size={14} className="animate-spin" /> : <Check size={14} />} Save copy
                  </button>
                </>
              )}

              {tab === "publish" && (
                <>
                  <section>
                    <p className="label mb-2">Scheduled for (your local time)</p>
                    <div className="flex gap-2">
                      <input type="datetime-local" className="input" value={when} onChange={(e) => setWhen(e.target.value)} />
                      <button className="btn-ghost btn-sm shrink-0" disabled={when === toLocalInput(post.publish_at) || busy !== null}
                        onClick={() => update({ publish_at: fromLocalInput(when) }, "Rescheduled", "when")}>Save</button>
                    </div>
                  </section>

                  {post.status === "PUBLISHED" ? (
                    <section className="rounded-2xl border border-emerald-200 bg-emerald-50 p-4">
                      <p className="flex items-center gap-2 text-sm font-semibold text-emerald-800"><Check size={16} /> Posted to {PLATFORM_META[post.platform].label}</p>
                      {post.remote_url ? (
                        <a href={post.remote_url} target="_blank" rel="noreferrer" className="btn-ghost btn-sm mt-3"><ExternalLink size={13} /> View live post</a>
                      ) : (
                        <p className="mt-1 text-xs text-emerald-700">Marked as posted.</p>
                      )}
                    </section>
                  ) : (
                    <>
                      <section className="rounded-2xl border border-slate-200 p-4">
                        <p className="text-sm font-semibold">Post to {PLATFORM_META[post.platform].label}</p>
                        {connected ? (
                          <>
                            <p className="mt-1 text-xs text-slate-500">
                              Publishes {images.length > 1 ? `all ${images.length} slides` : "the image"} and caption to your account right now.
                            </p>
                            <button onClick={() => run("publish", () => api.publishNow(post.id), `Posted to ${PLATFORM_META[post.platform].label}`)} disabled={busy !== null || copyDirty}
                              title={copyDirty ? "Save your caption edits first" : ""} className="btn-gradient mt-3 w-full">
                              {busy === "publish" ? <Loader2 size={15} className="animate-spin" /> : <Rocket size={15} />} Post now
                            </button>
                          </>
                        ) : (
                          <>
                            <p className="mt-1 text-xs text-slate-500">
                              {post.platform === "x" || post.platform === "linkedin"
                                ? `Opens ${PLATFORM_META[post.platform].label} with your caption filled in and your image ready to paste.`
                                : post.platform === "facebook"
                                  ? "Opens Facebook with your image ready to paste. Facebook doesn't let other apps fill in the caption, so you paste it too."
                                  : "Downloads your image and copies the caption, then opens Instagram."}
                            </p>
                            <div className="mt-3 flex flex-wrap gap-2">
                              <button onClick={openApp} disabled={busy !== null} className="btn-dark btn-sm flex-1">
                                {busy === "share" ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />} Open {PLATFORM_META[post.platform].label}
                              </button>
                              {sheet && (
                                <button onClick={shareSheet} disabled={busy !== null} className="btn-ghost btn-sm flex-1" title="Send the image and caption to an app on this device">
                                  {busy === "sheet" ? <Loader2 size={14} className="animate-spin" /> : <Rocket size={14} />} Share to an app
                                </button>
                              )}
                              <button onClick={() => run("mark", () => api.markPublished(post.id), "Marked as posted")} disabled={busy !== null} className="btn-ghost btn-sm flex-1">
                                <Check size={14} /> Mark as posted
                              </button>
                            </div>
                            {guide && (
                              <div className="mt-3 rounded-xl bg-indigo-50/70 p-3 text-sm text-slate-700">
                                <ol className="list-decimal space-y-1 pl-5">
                                  {shareSteps(post.platform, guide.imageOnClipboard, guide.multi, images.length).map((s) => <li key={s}>{s}</li>)}
                                  <li>Come back and click &ldquo;Mark as posted&rdquo;.</li>
                                </ol>
                                <div className="mt-2 flex flex-wrap gap-2">
                                  {post.platform !== "x" && post.platform !== "linkedin" && (
                                    <button className="btn-primary btn-sm" onClick={async () => setNotice(await copyText(fullCaption)
                                      ? { kind: "ok", text: "Caption copied. Paste it into the post." } : { kind: "err", text: "Couldn't copy. Select the caption and copy it by hand." })}>
                                      <Copy size={13} /> Copy caption
                                    </button>
                                  )}
                                  {images.length === 1 && post.platform !== "instagram" && (
                                    <button className="btn-ghost btn-sm" onClick={async () => setNotice(await copyImage(images[0])
                                      ? { kind: "ok", text: `Image copied. Press ${pasteKey()} in the post box.` } : { kind: "err", text: "This browser can't copy images; use Download below." })}>
                                      <Copy size={13} /> Copy image again
                                    </button>
                                  )}
                                </div>
                              </div>
                            )}
                            <details className="mt-3 text-xs text-slate-500">
                              <summary className="cursor-pointer select-none font-medium text-slate-600">Want it to post by itself in one click?</summary>
                              <p className="mt-1.5">
                                {post.platform === "facebook" || post.platform === "instagram"
                                  ? "Meta only lets apps post to Facebook Pages and Instagram Business or Creator accounts (not personal profiles). Connect your brand's Page and MonoPlus posts the image and caption itself, on schedule."
                                  : `Connect your ${PLATFORM_META[post.platform].label} account and MonoPlus posts the image and caption itself, on schedule.`}
                                {" "}The keys go in the server&apos;s <code>.env</code> file; the steps are listed there.
                              </p>
                            </details>
                          </>
                        )}
                        {post.publish_error && <p className="mt-3 rounded-xl bg-red-50 px-3 py-2 text-xs text-red-700">Last attempt failed: {post.publish_error}</p>}
                      </section>

                      <section className="rounded-2xl border border-slate-200 p-4">
                        <p className="text-sm font-semibold">Or schedule it</p>
                        <p className="mt-1 text-xs text-slate-500">
                          {connected ? "Approved posts are posted automatically at their time when “Auto-post approved” is on." : "Approve it to mark it ready for its scheduled time."}
                        </p>
                        <button className={post.status === "APPROVED" ? "btn-ghost btn-sm mt-3" : "btn-primary btn-sm mt-3"} disabled={busy !== null}
                          onClick={() => update({ status: post.status === "APPROVED" ? "DRAFT" : "APPROVED" }, post.status === "APPROVED" ? "Moved back to draft" : "Approved", "approve")}>
                          <Check size={14} /> {post.status === "APPROVED" ? "Unapprove" : "Approve post"}
                        </button>
                      </section>
                    </>
                  )}

                  <section>
                    <p className="label mb-2">Download</p>
                    <div className="flex flex-wrap gap-2">
                      {images.map((u, i) => (
                        <a key={u} href={media(u)} download className="btn-ghost btn-sm"><Download size={13} /> {images.length > 1 ? `Slide ${i + 1}` : "Image"}</a>
                      ))}
                      <button onClick={() => { navigator.clipboard.writeText(`${caption}\n\n${hashtags}`.trim()); setNotice({ kind: "ok", text: "Caption copied" }); }} className="btn-ghost btn-sm">
                        <Copy size={13} /> Copy caption
                      </button>
                    </div>
                  </section>
                </>
              )}
            </div>

            {notice && (
              <div className={`mx-5 mb-4 rounded-xl px-3 py-2 text-sm ${notice.kind === "ok" ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"}`}>{notice.text}</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
