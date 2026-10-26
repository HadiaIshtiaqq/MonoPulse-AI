"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  ArrowRight, BadgeCheck, CalendarClock, ChevronDown, FlaskConical, Globe, Images, Loader2, Newspaper, PenLine, Sparkles, Wand2,
} from "lucide-react";
import { api, fmtDay, media, type CampaignSummary, type Platform, type ResearchTask, type SocialPost } from "@/lib/api";
import { PLATFORM_META, PlatformIcon } from "@/components/PlatformIcon";
import { CampaignCard } from "@/components/CampaignCard";
import { Reveal, useCycle } from "@/components/Motion";

const ALL_PLATFORMS: Platform[] = ["instagram", "linkedin", "x", "facebook"];
const EXAMPLES = ["tartinebakery.com", "sweetgreen.com", "@bluebottlecoffee", "basecamp.com"];

const STEPS = [
  { icon: Globe, title: "Reads your brand", body: "Logo, colours, products and tone pulled from your site. Fix anything in the brand kit." },
  { icon: Newspaper, title: "Checks today's news", body: "Tavily finds live industry stories and local events worth posting about." },
  { icon: PenLine, title: "Writes like you", body: "Nemotron drafts every caption, then the humanizer strips the AI tells." },
  { icon: Images, title: "Designs every post", body: "Your real products and photos, sized and written for Instagram, Facebook, LinkedIn and X." },
];

const PROMISES = [
  "No watermark, on every plan",
  "Every post written for each platform",
  "Carousels included",
  "Your products, your photos",
];

export default function CreatePage() {
  const router = useRouter();
  const [input, setInput] = useState("");
  const [platforms, setPlatforms] = useState<Platform[]>(["instagram", "facebook", "linkedin", "x"]);
  const [days, setDays] = useState(30);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [recent, setRecent] = useState<CampaignSummary[]>([]);
  const [research, setResearch] = useState<ResearchTask[]>([]);
  const [researchIds, setResearchIds] = useState<string[]>([]);
  const [showResearch, setShowResearch] = useState(false);
  const [upcoming, setUpcoming] = useState<{ campaign_id: string; brand: string; post: SocialPost }[]>([]);

  useEffect(() => {
    const preselect = new URLSearchParams(window.location.search).get("research");
    if (preselect) { setResearchIds([preselect]); setShowResearch(true); }
    api.researchTasks().then((t) => setResearch(t.filter((x) => x.status === "completed").slice(0, 8))).catch(() => {});
    api.campaigns().then(setRecent).catch(() => setError("Can't reach the API. Is the backend running on port 8000?"));
    api.upcoming(7).then(setUpcoming).catch(() => {});
  }, []);

  const placeholder = useCycle(EXAMPLES);

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
      <section className="relative overflow-hidden rounded-3xl border border-slate-200/80 bg-white px-5 py-10 shadow-card sm:px-10 sm:py-16">
        <div className="pointer-events-none absolute -right-24 -top-24 h-96 w-96 animate-float rounded-full bg-brand-gradient opacity-[0.14] blur-3xl" />
        <div className="pointer-events-none absolute -bottom-32 -left-16 h-80 w-80 animate-float-slow rounded-full bg-pop opacity-[0.10] blur-3xl" />
        <div className="pointer-events-none absolute left-1/3 top-10 h-40 w-40 animate-float-slow rounded-full bg-brand opacity-[0.06] blur-2xl" />
        {/* A faint dot grid that fades out towards the edges. */}
        <div className="pointer-events-none absolute inset-0 opacity-[0.35] [background-image:radial-gradient(#cbd5e1_1px,transparent_1px)] [background-size:22px_22px] [mask-image:radial-gradient(ellipse_at_center,black_30%,transparent_75%)]" />
        <div className="relative mx-auto max-w-3xl text-center">
          <span className="chip animate-fade-up border border-brand-100 bg-white/80 text-brand-700 shadow-sm backdrop-blur">
            <Sparkles size={12} className="animate-pulse" /> Your social media team, in one input
          </span>
          <h1 className="delay-1 mt-5 animate-fade-up text-4xl font-extrabold leading-[1.08] tracking-tight sm:text-6xl">
            A month of posts that sound like <span className="gradient-text">you</span>
          </h1>
          <p className="delay-2 mx-auto mt-5 max-w-2xl animate-fade-up text-base text-slate-600 sm:text-lg">
            Paste your website or Instagram handle. MonoPlus learns your brand, checks what&apos;s happening in your industry today,
            and designs a ready-to-post calendar of captions, graphics and carousels.
          </p>

          <form onSubmit={submit}
            className="delay-3 group/form mx-auto mt-9 max-w-2xl animate-scale-in rounded-2xl border border-slate-200 bg-white/90 p-2 text-left shadow-lift backdrop-blur transition-all duration-300 focus-within:border-brand-200 focus-within:shadow-glow-lg">
            <div className="flex items-center gap-2">
              <Globe className="ml-3 shrink-0 text-slate-400 transition-colors duration-300 group-focus-within/form:text-brand" size={20} />
              <input
                autoFocus
                value={input}
                onChange={(e) => setInput(e.target.value)}
                placeholder={`Try ${placeholder}`}
                aria-label="Your website or social handle"
                className="h-12 min-w-0 flex-1 bg-transparent text-base outline-none placeholder:text-slate-400"
              />
              <button className="btn-gradient group h-11 shrink-0 px-5" disabled={busy || !input.trim()}>
                {busy ? <Loader2 className="animate-spin" size={16} /> : <ArrowRight size={16} className="transition-transform duration-300 group-hover:translate-x-1" />}
                <span className="hidden sm:inline">{busy ? "Starting…" : "Create campaign"}</span>
              </button>
            </div>
            <div className="mt-2 flex flex-wrap items-center gap-2 border-t border-slate-100 px-2 pb-1 pt-3">
              {ALL_PLATFORMS.map((p) => {
                const on = platforms.includes(p);
                return (
                  <button type="button" key={p} onClick={() => toggle(p)} aria-pressed={on}
                    className={`chip border transition-all duration-200 active:scale-95 ${on ? "border-slate-300 bg-white text-ink shadow-sm" : "border-transparent bg-slate-100 text-slate-400 hover:text-slate-600"}`}>
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
              {platforms.length > 0 && (
                <span className="text-xs text-slate-500">
                  {days} posts{platforms.length > 1 ? `, each made for ${platforms.length} platforms` : ""}
                </span>
              )}
            </div>
            {research.length > 0 && (
              <div className="border-t border-slate-100 px-2 pb-1 pt-3">
                <button type="button" onClick={() => setShowResearch((s) => !s)} aria-expanded={showResearch}
                  className="flex items-center gap-1.5 text-xs font-medium text-slate-500 transition hover:text-ink">
                  <FlaskConical size={12} />
                  {researchIds.length ? `Using ${researchIds.length} research ${researchIds.length === 1 ? "brief" : "briefs"}` : `Attach research (${research.length})`}
                  <ChevronDown size={13} className={`transition-transform duration-300 ${showResearch ? "rotate-180" : ""}`} />
                </button>
                {showResearch && (
                  <div className="stagger mt-2 flex flex-wrap gap-2">
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
                    <span className="self-center text-[11px] text-slate-400">up to 3</span>
                  </div>
                )}
              </div>
            )}
          </form>
          {error && <p className="mt-3 animate-slide-down text-sm text-red-600">{error}</p>}
          <p className="delay-4 mt-4 animate-fade-in text-xs text-slate-500">
            Try:{" "}
            {EXAMPLES.map((x, i) => (
              <span key={x}>
                <button type="button" onClick={() => setInput(x)} className="font-medium text-slate-700 underline decoration-slate-300 underline-offset-2 hover:text-brand">{x}</button>
                {i < EXAMPLES.length - 1 ? " · " : ""}
              </span>
            ))}
          </p>
          <ul className="stagger mt-7 flex flex-wrap justify-center gap-x-5 gap-y-2 text-xs text-slate-600">
            {PROMISES.map((p) => <li key={p} className="flex items-center gap-1.5"><BadgeCheck size={14} className="text-emerald-500" /> {p}</li>)}
          </ul>
        </div>
      </section>

      <Reveal>
        <section className="stagger grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {STEPS.map(({ icon: Icon, title, body }, i) => (
            <div key={title} className="card card-hover group relative overflow-hidden p-5">
              <span className="absolute right-4 top-3 font-display text-4xl font-extrabold text-slate-100 transition-colors duration-500 group-hover:text-brand-100">{i + 1}</span>
              <span className="relative grid h-10 w-10 place-items-center rounded-xl bg-brand-soft text-brand transition-all duration-500 group-hover:rotate-[-8deg] group-hover:scale-110 group-hover:bg-brand group-hover:text-white group-hover:shadow-glow">
                <Icon size={18} />
              </span>
              <h3 className="relative mt-3 font-semibold">{title}</h3>
              <p className="relative mt-1 text-sm text-slate-600">{body}</p>
              <span className="absolute inset-x-0 bottom-0 h-0.5 origin-left scale-x-0 bg-brand-gradient transition-transform duration-500 group-hover:scale-x-100" />
            </div>
          ))}
        </section>
      </Reveal>

      {upcoming.length > 0 && (
        <Reveal>
          <section>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="flex items-center gap-2 text-lg font-bold"><CalendarClock size={18} className="text-brand" /> Up next this week</h2>
          </div>
          <div className="stagger flex gap-3 overflow-x-auto pb-2 pt-1 scrollbar-thin">
            {upcoming.slice(0, 12).map(({ campaign_id, brand, post }) => (
              <Link key={post.id} href={`/campaign/${campaign_id}?post=${post.id}`} className="card card-hover group w-44 shrink-0 overflow-hidden">
                <span className="block overflow-hidden">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={media(post.image_url)} alt="" className="zoom-on-hover aspect-square w-full bg-slate-100 object-contain" />
                </span>
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
        </Reveal>
      )}

      {recent.length > 0 && (
        <Reveal>
          <section>
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-lg font-bold">Recent campaigns</h2>
              <Link href="/campaigns" className="group text-sm font-medium text-brand">
                View all <span className="inline-block transition-transform duration-300 group-hover:translate-x-1">→</span>
              </Link>
            </div>
            <div className="stagger grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
              {recent.slice(0, 3).map((c) => <CampaignCard key={c.id} c={c} />)}
            </div>
          </section>
        </Reveal>
      )}

      {recent.length === 0 && !error && (
        <section className="card flex animate-fade-up flex-col items-center gap-2 p-8 text-center">
          <Wand2 className="animate-float text-brand" />
          <p className="font-semibold">Your campaigns will show up here</p>
          <p className="max-w-md text-sm text-slate-500">Start with your website above. A full 30-day calendar takes about half a minute.</p>
        </section>
      )}
    </div>
  );
}
