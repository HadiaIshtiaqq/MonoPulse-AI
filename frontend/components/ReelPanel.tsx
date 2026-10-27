"use client";

import { useEffect, useRef, useState } from "react";
import { Clapperboard, Copy, Download, Film, Loader2, Pause, Play, RefreshCw, Share2, Sparkles, Volume2 } from "lucide-react";
import { api, media, type SocialPost } from "@/lib/api";
import { canShareVideo, copyText, downloadVideo, shareVideo } from "@/lib/share";
import { useCycle } from "@/components/Motion";
import { useFeedback } from "@/components/Feedback";

const STEPS = ["Writing the script…", "Picking your best product photos…", "Animating every scene…", "Encoding a 1080×1920 MP4…"];

/** The reel in a phone frame, playing on a loop like it would in the feed. */
export function ReelPlayer({ post, brandName }: { post: SocialPost; brandName: string }) {
  const ref = useRef<HTMLVideoElement>(null);
  const [playing, setPlaying] = useState(true);
  const [progress, setProgress] = useState(0);

  function toggle() {
    const v = ref.current;
    if (!v) return;
    if (v.paused) { v.play(); setPlaying(true); } else { v.pause(); setPlaying(false); }
  }

  if (!post.video_url) {
    return (
      <div className="relative grid aspect-[9/16] w-[min(100%,300px)] place-items-center overflow-hidden rounded-[2rem] border-[6px] border-ink bg-ink shadow-pop">
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
    <div className="relative aspect-[9/16] w-[min(100%,300px)] animate-scale-in overflow-hidden rounded-[2rem] border-[6px] border-ink bg-ink shadow-pop">
      <video key={post.video_url} ref={ref} src={media(post.video_url)} poster={media(post.video_poster)} autoPlay muted loop playsInline
        onTimeUpdate={(e) => setProgress(e.currentTarget.currentTime / (e.currentTarget.duration || 1))}
        onClick={toggle} className="h-full w-full cursor-pointer object-cover" aria-label={`${brandName} reel`} />
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

export function ReelPanel({ post, brandName, caption, onChange }: {
  post: SocialPost; brandName: string; caption: string; onChange: (p: SocialPost) => void;
}) {
  const { toast } = useFeedback();
  const [busy, setBusy] = useState<"make" | "share" | "download" | null>(null);
  const [script, setScript] = useState<{ scenes: string[]; seconds: number; used_llm: boolean; render_ms: number } | null>(null);
  const [shareable, setShareable] = useState(false);
  const step = useCycle(STEPS, 4500);
  useEffect(() => setShareable(canShareVideo()), []);
  useEffect(() => setScript(null), [post.group_id]);

  const fileBase = `${brandName.replace(/[^\w]+/g, "-").toLowerCase() || "post"}-${post.publish_at.slice(0, 10)}`;

  async function make() {
    setBusy("make");
    try {
      const res = await api.makeReel(post.id);
      onChange(res.post);
      setScript(res);
      toast(`Your ${Math.round(res.seconds)}-second reel is ready`);
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

  return (
    <>
      <section className="rounded-2xl border border-brand-100 bg-gradient-to-br from-brand-50 to-white p-4">
        <div className="flex items-start gap-3">
          <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-gradient text-white shadow-glow"><Clapperboard size={18} /></span>
          <div className="min-w-0">
            <p className="font-semibold">Turn this post into a reel</p>
            <p className="mt-0.5 text-sm text-slate-600">
              A 10–15 second vertical video from {brandName}&apos;s own photos: an AI-written hook, each product with its price,
              and an end card with your logo. Ready for Instagram Reels, TikTok, YouTube Shorts and Facebook Reels.
            </p>
          </div>
        </div>
        <button onClick={make} disabled={busy !== null} className={`${post.video_url ? "btn-ghost" : "btn-gradient"} mt-4 w-full`}>
          {busy === "make" ? <Loader2 size={16} className="animate-spin" /> : post.video_url ? <RefreshCw size={16} /> : <Sparkles size={16} />}
          {busy === "make" ? "Making your reel…" : post.video_url ? "Make a new version" : "Make reel"}
        </button>
        {busy === "make" && (
          <div className="mt-3 space-y-2" aria-live="polite">
            <div className="h-1.5 overflow-hidden rounded-full bg-brand-100">
              <div className="bg-stripes h-full w-full animate-stripes rounded-full bg-brand" />
            </div>
            <p key={step} className="animate-fade-in text-xs text-slate-500">{step} This takes about half a minute.</p>
          </div>
        )}
      </section>

      {script && (
        <section className="animate-fade-up">
          <p className="label mb-2">Script · {script.seconds.toFixed(0)}s{script.used_llm ? " · written by Nemotron" : ""}</p>
          <ol className="stagger flex flex-wrap items-center gap-1.5">
            {script.scenes.map((s, i) => (
              <li key={i} className={`chip border ${i === 0 ? "border-brand-200 bg-brand-soft text-brand-700" : i === script.scenes.length - 1 ? "border-pop/30 bg-pop/10 text-pop" : "border-slate-200 bg-white text-slate-700"}`}>
                <span className="text-[10px] opacity-60">{i === 0 ? "Hook" : i === script.scenes.length - 1 ? "End" : i}</span> {s}
              </li>
            ))}
          </ol>
        </section>
      )}

      {post.video_url && (
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
