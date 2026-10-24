"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowRight, BadgeCheck, CalendarClock, FlaskConical, Globe, Images, Loader2, Newspaper, PenLine, Sparkles, Wand2,
} from "lucide-react";
import { api, fmtDay, media, type CampaignSummary, type Platform, type ResearchTask, type SocialPost } from "@/lib/api";
import { PLATFORM_META, PlatformIcon } from "@/components/PlatformIcon";
import { CampaignCard } from "@/components/CampaignCard";

const ALL_PLATFORMS: Platform[] = ["instagram", "linkedin", "x", "facebook"];
const EXAMPLES = ["tartinebakery.com", "sweetgreen.com", "@bluebottlecoffee", "basecamp.com"];

const STEPS = [
  { icon: Globe, title: "Reads your brand", body: "Logo, colours, products and tone pulled from your site. Fix anything in the brand kit." },
  { icon: Newspaper, title: "Checks today's news", body: "Tavily finds live industry stories and local events worth posting about." },
  { icon: PenLine, title: "Writes like you", body: "Nemotron drafts every caption, then the humanizer strips the AI tells." },
  { icon: Images, title: "Designs every post", body: "Branded graphics, photo posts and swipeable carousels for each platform." },
];

const PROMISES = [
  "No watermark, on every plan",
  "Captions checked against 26 AI-writing patterns",
  "Carousels included",
  "Your photos or licensed stock",
];

export default function CreatePage() {
  const router = useRouter();
  const [input, setInput] = useState("");
  const [platforms, setPlatforms] = useState<Platform[]>(["instagram", "linkedin", "x"]);
  const [days, setDays] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recent, setRecent] = useState<CampaignSummary[]>([]);
  const [research, setResearch] = useState<ResearchTask[]>([]);
  const [researchIds, setResearchIds] = useState<string[]>([]);
  const [upcoming, setUpcoming] = useState<{ campaign_id: string; brand: string; post: SocialPost }[]>([]);

  useEffect(() => {
    const preselect = new URLSearchParams(window.location.search).get("research");
    if (preselect) setResearchIds([preselect]);
    api.researchTasks().then((t) => setResearch(t.filter((x) => x.status === "completed").slice(0, 8))).catch(() => {});
    api.campaigns().then(setRecent).catch(() => setError("Can't reach the API. Is the backend running on port 8000?"));
    api.upcoming(7).then(setUpcoming).catch(() => {});
  }, []);

  const toggle = (p: Platform) =>
    setPlatforms((cur) => (cur.includes(p) ? (cur.length > 1 ? cur.filter((x) => x !== p) : cur) : [...cur, p]));

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!input.trim()) return;
    setBusy(true);
    setError("");
    try {
      const { campaign_id, job_id } = await api.createCampaign({ input: input.trim(), platforms, days, research_ids: researchIds });
      router.push(`/campaign/${campaign_id}?job=${job_id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  return (
    <div className="space-y-10">
      <section className="relative overflow-hidden rounded-3xl border border-slate-200/80 bg-white px-5 py-10 shadow-card sm:px-10 sm:py-14">
        <div className="pointer-events-none absolute -right-24 -top-24 h-80 w-80 rounded-full bg-brand-gradient opacity-[0.12] blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 -left-16 h-72 w-72 rounded-full bg-pop opacity-[0.08] blur-3xl" />
        <div className="relative mx-auto max-w-3xl text-center">
          <span className="chip bg-brand-soft text-brand-700"><Sparkles size={12} /> Your social media team, in one input</span>
          <h1 className="mt-4 text-4xl font-extrabold leading-[1.1] tracking-tight sm:text-5xl">
            A month of posts that sound like <span className="bg-brand-gradient bg-clip-text text-transparent">you</span>
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-base text-slate-600">
            Paste your website or Instagram handle. MonoPlus learns your brand, checks what&apos;s happening in your industry today,
            and designs a ready-to-post calendar of captions, graphics and carousels.
          </p>

          <form onSubmit={submit} className="mx-auto mt-8 max-w-2xl rounded-2xl border border-slate-200 bg-white p-2 text-left shadow-lift">
            <div className="flex items-center gap-2">
              <Globe className="ml-3 shrink-0 text-slate-400" size={20} />
              <input
                autoFocus
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder="yourbusiness.com or @yourhandle"
                className="h-12 min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-slate-400"
              />
              <button className="btn-gradient h-11 shrink-0 px-5" disabled={busy || !input.trim()}>
                {busy ? <Loader2 className="animate-spin" size={16} /> : <ArrowRight size={16} />}
                <span className="hidden sm:inline">Create campaign</span>
              </button>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-slate-100 px-2 pb-1 pt-3">
              {ALL_PLATFORMS.map((p) => {
                const on = platforms.includes(p);
                return (
                  <button type="button" key={p} onClick={() => toggle(p)} aria-pressed={on}
                    className={`chip border transition ${on ? "border-slate-300 bg-white text-ink shadow-sm" : "border-transparent bg-slate-100 text-slate-400"}`}>
                    <PlatformIcon platform={p} size={12} /> {PLATFORM_META[p].label}
                  </button>
                );
              })}
              <span className="mx-1 hidden h-4 w-px bg-slate-200 sm:block" />
              <div className="seg">
                {[7, 14, 30].map((d) => (
                  <button type="button" key={d} data-active={days === d} onClick={() => setDays(d)}>{d} days</button>
                ))}
              </div>
            </div>
            {research.length > 0 && (
              <div className="flex flex-wrap items-center gap-2 border-t border-slate-100 px-2 pb-1 pt-3">
                <span className="flex items-center gap-1 text-xs font-medium text-slate-500"><FlaskConical size={12} /> Use research:</span>
                {research.map((r) => {
                  const on = researchIds.includes(r.id);
                  return (
                    <button type="button" key={r.id} title={r.topic}
                      onClick={() => setResearchIds((ids) => (on ? ids.filter((x) => x !== r.id) : ids.length < 3 ? [...ids, r.id] : ids))}
                      className={`chip max-w-[220px] truncate border ${on ? "border-brand bg-brand-soft text-brand-700" : "border-transparent bg-slate-100 text-slate-600"}`}>
                      {r.topic}
                    </button>
                  );
                })}
              </div>
            )}
          </form>
          {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
          <p className="mt-4 text-xs text-slate-500">
            Try:{" "}
            {EXAMPLES.map((x, i) => (
              <span key={x}>
                <button type="button" onClick={() => setInput(x)} className="font-medium text-slate-700 underline decoration-slate-300 underline-offset-2 hover:text-brand">{x}</button>
                {i < EXAMPLES.length - 1 ? " · " : ""}
              </span>
            ))}
          </p>
          <ul className="mt-6 flex flex-wrap justify-center gap-x-5 gap-y-2 text-xs text-slate-600">
            {PROMISES.map((p) => <li key={p} className="flex items-center gap-1.5"><BadgeCheck size={14} className="text-emerald-500" /> {p}</li>)}
          </ul>
        </div>
      </section>

      <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        {STEPS.map(({ icon: Icon, title, body }, i) => (
          <div key={title} className="card relative p-5">
            <span className="absolute right-4 top-4 font-display text-3xl font-extrabold text-slate-100">{i + 1}</span>
            <span className="grid h-10 w-10 place-items-center rounded-xl bg-brand-soft text-brand"><Icon size={18} /></span>
            <h3 className="mt-3 font-semibold">{title}</h3>
            <p className="mt-1 text-sm text-slate-600">{body}</p>
          </div>
        ))}
      </section>

      {upcoming.length > 0 && (
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-lg font-bold"><CalendarClock size={18} className="text-brand" /> Up next this week</h2>
          </div>
          <div className="flex gap-3 overflow-x-auto pb-2 scrollbar-thin">
            {upcoming.slice(0, 12).map(({ campaign_id, brand, post }) => (
              <Link key={post.id} href={`/campaign/${campaign_id}?post=${post.id}`} className="card w-44 shrink-0 overflow-hidden transition hover:shadow-lift">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={media(post.image_url)} alt="" className="aspect-square w-full bg-slate-100 object-contain" />
                <div className="p-2.5">
                  <p className="flex items-center gap-1 text-[11px] text-slate-500">
                    <PlatformIcon platform={post.platform} size={11} />
                    {fmtDay(post.publish_at, { weekday: "short", day: "numeric" })} · {brand}
                  </p>
                  <p className="mt-0.5 truncate text-xs font-medium">{post.headline}</p>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      {recent.length > 0 && (
        <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-lg font-bold">Recent campaigns</h2>
            <Link href="/campaigns" className="text-sm font-medium text-brand hover:underline">View all →</Link>
          </div>
          <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {recent.slice(0, 3).map((c) => <CampaignCard key={c.id} c={c} />)}
          </div>
        </section>
      )}

      {recent.length === 0 && !error && (
        <section className="card flex flex-col items-center gap-2 p-8 text-center">
          <Wand2 className="text-brand" />
          <p className="font-semibold">Your campaigns will show up here</p>
          <p className="max-w-md text-sm text-slate-500">Start with your website above. A full 30-day calendar takes about half a minute.</p>
        </section>
      )}
    </div>
  );
}
