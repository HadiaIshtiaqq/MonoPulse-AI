"use client";

import { useEffect, useState } from "react";
import { Bot, CheckCircle2, Circle, Clapperboard, Instagram, Loader2, Search, ShieldCheck, Sparkles } from "lucide-react";
import { api, type ConnectionItem, type Connections } from "@/lib/api";

/** What MonoPlus is connected to. Keys live only in the backend's .env file: this page never asks
 *  for one, sends one or shows one. It says what's set up and which lines to add. */
export default function ConnectionsPage() {
  const [status, setStatus] = useState<Connections | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.connections().then(setStatus).catch((e) => setError((e as Error).message)); }, []);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Connections</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          Keys and tokens are set only in <code className="rounded bg-slate-100 px-1">backend/.env</code> on the computer MonoPlus runs on.
          They never pass through this page or the browser. Add the lines below, then restart MonoPlus.
        </p>
      </div>
      <p className="flex max-w-3xl items-start gap-2 rounded-xl bg-slate-50 px-4 py-3 text-xs text-slate-600">
        <ShieldCheck size={15} className="mt-0.5 shrink-0 text-emerald-600" />
        <span>
          To check every key you&apos;ve set with its service (it prints only &ldquo;ok&rdquo; or why not, never a key), run in the backend folder:{" "}
          <code className="rounded bg-white px-1">.venv\Scripts\python -m app.connections check</code>
        </span>
      </p>
      {error && <p className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>}
      {!status ? (
        <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 size={14} className="animate-spin" /> Loading…</div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <Service icon={<Sparkles size={16} />} title="AI writing and directing: Nemotron on Nebius" item={status.nebius}
            blurb="Strategy, captions, research, UGC scripts and shot direction by NVIDIA Nemotron. Without it MonoPlus uses templates."
            how={<>Create a key in <a className="link" href="https://tokenfactory.nebius.com/" target="_blank" rel="noreferrer">Nebius Token Factory</a> (API keys).</>} />
          <Service icon={<Instagram size={16} />} title="Instagram and Facebook: official Meta API" item={status.meta}
            detail={status.meta.connected ? [status.meta.page && `Page: ${status.meta.page}`, status.meta.instagram && `Instagram: @${status.meta.instagram}`].filter(Boolean).join(" · ") : ""}
            blurb="Posts straight to your Page and Instagram Business/Creator account: no browser sign-in, no captchas."
            how={<>
              Make a Meta app at <a className="link" href="https://developers.facebook.com/apps" target="_blank" rel="noreferrer">developers.facebook.com</a>,
              get a user token in the Graph API Explorer (pages_show_list, pages_manage_posts, instagram_basic, instagram_content_publish), and put it in
              backend/.env as <code>META_USER_TOKEN</code>, with <code>META_APP_ID</code> and <code>META_APP_SECRET</code> for a connection that lasts.
              Then run <code>.venv\Scripts\python -m app.connections meta</code>: it finds your Page and Instagram account and writes the lines below into .env.
            </>} />
          <Service icon={<Search size={16} />} title="Web search: Tavily" item={status.tavily}
            blurb="Faster, more complete research and trends. Without it MonoPlus uses free sources (news, DuckDuckGo, Wikipedia)."
            how={<>Get a free key (1,000 searches a month) at <a className="link" href="https://app.tavily.com/" target="_blank" rel="noreferrer">tavily.com</a>.</>} />
          <Service icon={<Clapperboard size={16} />} title="AI video shots: Hugging Face (free, optional)" item={status.huggingface}
            blurb="Only for AI scenes filmed by AI video. The 3D camera needs nothing. A free account gets a bigger daily share."
            how={<>Sign up at <a className="link" href="https://huggingface.co/join" target="_blank" rel="noreferrer">huggingface.co</a> and create a
              &ldquo;Read&rdquo; token in <a className="link" href="https://huggingface.co/settings/tokens" target="_blank" rel="noreferrer">Settings, Access Tokens</a>.</>} />
          <Service icon={<Bot size={16} />} title="Realistic presenters: HeyGen (paid, optional)" item={status.heygen}
            blurb="Realistic AI people presenting your products. Uses your HeyGen credits."
            how={<>Create an API key in <a className="link" href="https://app.heygen.com/settings" target="_blank" rel="noreferrer">HeyGen settings</a> (API).</>} />
        </div>
      )}
    </div>
  );
}

function Service({ icon, title, blurb, how, item, detail }: {
  icon: React.ReactNode; title: string; blurb: string; how: React.ReactNode; item: ConnectionItem; detail?: string;
}) {
  return (
    <section className="card p-5">
      <div className="flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand">{icon}</span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{title}</p>
          <p className="text-xs text-slate-500">{blurb}</p>
        </div>
        {item.connected
          ? <span className="chip bg-emerald-50 text-emerald-700"><CheckCircle2 size={12} /> Connected</span>
          : <span className="chip bg-slate-100 text-slate-500"><Circle size={12} /> Not set</span>}
      </div>
      {detail && <p className="mt-3 text-xs font-medium text-slate-700">{detail}</p>}
      <div className="mt-3 rounded-lg bg-slate-900 px-3 py-2 font-mono text-[12px] leading-relaxed text-slate-100">
        {item.env.map((name) => <div key={name}>{name}=<span className="text-slate-500">{item.connected ? "(set)" : "…"}</span></div>)}
      </div>
      <p className="mt-3 text-xs text-slate-500">{how}</p>
    </section>
  );
}
