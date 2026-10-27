"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, Clapperboard, Globe, Loader2, LogIn, LogOut, MousePointerClick, RefreshCw, Rocket } from "lucide-react";
import { api, type SocialPost } from "@/lib/api";
import { PLATFORM_META } from "@/components/PlatformIcon";
import { useFeedback } from "@/components/Feedback";

type Status = { available: boolean; signed_in: Record<string, boolean>; scheduled: boolean; error?: string };

/** Post the way a person (or Claude) does: in a real browser where you're signed in. */
export function BrowserPostPanel({ post, onChange, dirty }: { post: SocialPost; onChange: (p: SocialPost) => void; dirty: boolean }) {
  const { toast, confirm } = useFeedback();
  const [status, setStatus] = useState<Status | null>(null);
  const [busy, setBusy] = useState<"check" | "login" | "review" | "post" | "auto" | "signout" | null>(null);
  const [useReel, setUseReel] = useState(false);
  const label = PLATFORM_META[post.platform].label;
  const signedIn = !!status?.signed_in[post.platform];
  const canReel = !!post.video_url && (post.platform === "instagram" || post.platform === "facebook" || post.platform === "x");

  const check = useCallback(async () => {
    setBusy("check");
    try { setStatus(await api.browserStatus()); } catch { setStatus({ available: false, signed_in: {}, scheduled: false }); }
    finally { setBusy(null); }
  }, []);
  useEffect(() => { check(); }, [check]);

  async function signIn() {
    setBusy("login");
    try {
      const res = await api.browserLogin(post.platform);
      toast(res.note, "info");
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(null); }
  }

  async function go(submit: boolean) {
    if (submit) {
      const ok = await confirm({
        title: `Post this on ${label} now?`,
        body: `MonoPlus will open ${label} in its browser, attach the ${useReel ? "reel" : images(post)}, type the caption and press Post for you.`,
        confirm: "Post it",
      });
      if (!ok) return;
    }
    setBusy(submit ? "post" : "review");
    try {
      const res = await api.browserPost(post.id, submit, useReel ? "reel" : "images");
      onChange(res.post);
      toast(res.message, submit ? "success" : "info");
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(null); }
  }

  async function signOutEverywhere() {
    const ok = await confirm({
      title: "Sign out everywhere?",
      body: "MonoPlus's browser forgets every sign-in it holds (LinkedIn, Facebook, Instagram, X) and scheduled browser posting turns off. You can sign in again any time.",
      confirm: "Sign out",
      danger: true,
    });
    if (!ok) return;
    setBusy("signout");
    try {
      await api.browserSignOut();
      setStatus((s) => (s ? { ...s, signed_in: {}, scheduled: false } : s));
      toast("Signed out of every platform in MonoPlus's browser", "success");
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(null); }
  }

  async function toggleScheduled(enabled: boolean) {
    setBusy("auto");
    try {
      const res = await api.browserScheduled(enabled);
      setStatus((s) => (s ? { ...s, scheduled: res.scheduled } : s));
      toast(enabled ? "Approved posts will go out at their time through MonoPlus's browser" : "Scheduled browser posting is off", "info");
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(null); }
  }

  return (
    <section className="rounded-2xl border border-brand-100 bg-gradient-to-br from-brand-50 to-white p-4">
      <div className="flex items-start gap-3">
        <span className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-brand-gradient text-white shadow-glow"><Globe size={16} /></span>
        <div className="min-w-0 flex-1">
          <p className="text-sm font-semibold">Post from MonoPlus&apos;s browser</p>
          <p className="mt-0.5 text-xs text-slate-600">
            Like Claude does it: MonoPlus opens {label} in its own browser on this computer, where you&apos;re signed in, attaches
            the {images(post)} and types the caption. No developer apps needed.
          </p>
        </div>
      </div>

      {status === null ? (
        <div className="mt-3 flex items-center gap-2 text-xs text-slate-500"><Loader2 size={13} className="animate-spin" /> Checking the browser…</div>
      ) : !status.available ? (
        <p className="mt-3 rounded-xl bg-amber-50 px-3 py-2 text-xs text-amber-900">
          {status.error ?? "This needs Playwright on the computer running MonoPlus:"}{" "}
          {!status.error && <code className="font-mono">pip install playwright &amp;&amp; python -m playwright install chromium</code>}
        </p>
      ) : (
        <>
          <div className="mt-3 flex items-center gap-2 text-xs">
            {signedIn ? (
              <span className="flex items-center gap-1.5 font-medium text-emerald-700"><CheckCircle2 size={14} /> Signed in to {label}</span>
            ) : (
              <span className="text-slate-600">Not signed in to {label} in MonoPlus&apos;s browser yet.</span>
            )}
            <button onClick={check} disabled={busy !== null} className="ml-auto flex items-center gap-1 text-slate-500 hover:text-ink" title="Check again">
              {busy === "check" ? <Loader2 size={12} className="animate-spin" /> : <RefreshCw size={12} />} Check
            </button>
          </div>

          {!signedIn ? (
            <button onClick={signIn} disabled={busy !== null} className="btn-primary mt-3 w-full">
              {busy === "login" ? <Loader2 size={15} className="animate-spin" /> : <LogIn size={15} />} Sign in to {label}
            </button>
          ) : (
            <>
              {canReel && (
                <label className="mt-3 flex cursor-pointer items-center gap-2 text-xs text-slate-600">
                  <input type="checkbox" checked={useReel} onChange={(e) => setUseReel(e.target.checked)} className="accent-brand" />
                  <Clapperboard size={13} /> Post the reel instead of the image
                </label>
              )}
              <div className="mt-3 grid grid-cols-2 gap-2">
                <button onClick={() => go(false)} disabled={busy !== null || dirty} title={dirty ? "Save your caption edits first" : ""} className="btn-ghost">
                  {busy === "review" ? <Loader2 size={15} className="animate-spin" /> : <MousePointerClick size={15} />} Fill in for review
                </button>
                <button onClick={() => go(true)} disabled={busy !== null || dirty} title={dirty ? "Save your caption edits first" : ""} className="btn-gradient">
                  {busy === "post" ? <Loader2 size={15} className="animate-spin" /> : <Rocket size={15} />} Post now
                </button>
              </div>
            </>
          )}

          <label className="mt-3 flex cursor-pointer items-start gap-2 text-xs text-slate-600">
            <input type="checkbox" checked={status.scheduled} disabled={busy !== null} onChange={(e) => toggleScheduled(e.target.checked)} className="mt-0.5 accent-brand" />
            <span>Post approved posts automatically at their scheduled time through this browser (when auto-posting is on and MonoPlus is running).</span>
          </label>
          <p className="mt-2 text-[11px] leading-relaxed text-slate-500">
            Your passwords stay with the platforms: you sign in inside the browser window, never in MonoPlus. Platforms discourage
            automated posting, so keep it to your normal schedule; &ldquo;Fill in for review&rdquo; lets you press Post yourself.
          </p>
          {Object.values(status.signed_in).some(Boolean) && (
            <button onClick={signOutEverywhere} disabled={busy !== null} className="mt-2 flex items-center gap-1 text-[11px] font-medium text-slate-500 hover:text-red-600">
              {busy === "signout" ? <Loader2 size={11} className="animate-spin" /> : <LogOut size={11} />} Sign out everywhere
            </button>
          )}
        </>
      )}
    </section>
  );
}

function images(post: SocialPost): string {
  const n = post.image_urls?.length ?? (post.image_url ? 1 : 0);
  return n > 1 ? `${n} images` : "image";
}
