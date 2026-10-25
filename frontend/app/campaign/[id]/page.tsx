"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useParams, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ArrowLeft, CalendarClock, CalendarDays, CheckCheck, Download, Grid3x3, Layers, Lightbulb, List, Loader2, Palette, Send } from "lucide-react";
import { api, fmtDay, fmtTime, groupKey, groupPosts, media, type Campaign, type Job, type PublishingStatus, type SocialPost } from "@/lib/api";
import { GenerationProgress } from "@/components/GenerationProgress";
import { CalendarView } from "@/components/CalendarView";
import { QueueList } from "@/components/QueueList";
import { FeedGrid } from "@/components/FeedGrid";
import { BrandKitPanel } from "@/components/BrandKitPanel";
import { PostEditor } from "@/components/PostEditor";
import { StrategyPanel } from "@/components/StrategyPanel";
import { PLATFORM_META, PlatformIcon } from "@/components/PlatformIcon";

type Tab = "plan" | "feed" | "brand" | "strategy";

function CampaignPage() {
  const { id } = useParams<{ id: string }>();
  const params = useSearchParams();
  const jobId = params.get("job");
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [pub, setPub] = useState<PublishingStatus | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("plan");
  const [view, setView] = useState<"calendar" | "list">("calendar");
  const [openId, setOpenId] = useState<string | null>(params.get("post"));
  const [elapsed, setElapsed] = useState(0);
  const t0 = useRef(Date.now());

  const load = useCallback(() => api.campaign(id).then(setCampaign).catch((e) => setError(e.message)), [id]);
  useEffect(() => { load(); api.publishing().then(setPub).catch(() => {}); }, [load]);

  const generating = campaign?.status === "GENERATING";

  useEffect(() => {
    if (!generating) return;
    if (!jobId) {
      const t = setInterval(load, 2000);
      return () => clearInterval(t);
    }
    let alive = true;
    const tick = setInterval(() => setElapsed((Date.now() - t0.current) / 1000), 100);
    const poll = async () => {
      try {
        const j = await api.job(jobId);
        if (!alive) return;
        setJob(j);
        if (j.status !== "running") {
          if (j.elapsed?.total) setElapsed(j.elapsed.total);
          load();
          return;
        }
      } catch {}
      if (alive) setTimeout(poll, 700);
    };
    poll();
    return () => { alive = false; clearInterval(tick); };
  }, [generating, jobId, load]);

  const ordered = useMemo(() => [...(campaign?.posts ?? [])].sort((a, b) => a.publish_at.localeCompare(b.publish_at)), [campaign?.posts]);

  const replacePost = (p: SocialPost) => setCampaign((c) => (c ? { ...c, posts: c.posts.map((x) => (x.id === p.id ? p : x)) } : c));

  async function move(p: SocialPost, newDate: string) {
    // Move every platform version of the post, each keeping its own local time of day.
    const [y, m, d] = newDate.split("-").map(Number);
    const versions = (campaign?.posts ?? []).filter((v) => groupKey(v) === groupKey(p));
    await Promise.all(versions.map(async (v) => {
      const old = new Date(v.publish_at);
      const publish_at = new Date(y, m - 1, d, old.getHours(), old.getMinutes()).toISOString();
      replacePost({ ...v, publish_at });
      try { replacePost(await api.updatePost(v.id, { publish_at })); } catch (e) { replacePost(v); setError((e as Error).message); }
    }));
  }

  async function approve(p: SocialPost) {
    try { replacePost(await api.updatePost(p.id, { status: "APPROVED" })); } catch (e) { setError((e as Error).message); }
  }

  async function retry() {
    if (!campaign?.source_input) return;
    const { campaign_id, job_id } = await api.createCampaign({
      input: campaign.source_input, platforms: campaign.platforms, days: campaign.days, research_ids: campaign.research_ids,
    });
    window.location.assign(`/campaign/${campaign_id}?job=${job_id}`);
  }

  if (error && !campaign) return <p className="rounded-xl bg-red-50 p-4 text-red-700">{error}</p>;
  if (!campaign) return <Loader2 className="mx-auto mt-20 animate-spin text-slate-400" />;

  if (generating || (campaign.status === "FAILED" && job)) {
    return job ? <GenerationProgress job={job} elapsed={elapsed} onRetry={campaign.source_input ? retry : undefined} /> : (
      <div className="card mx-auto mt-10 flex max-w-md items-center gap-3 p-6"><Loader2 className="animate-spin text-brand" /> Generating this campaign…</div>
    );
  }
  if (campaign.status === "FAILED" || !campaign.brand) {
    return (
      <div className="card mx-auto mt-10 max-w-lg p-8 text-center">
        <p className="text-lg font-semibold">This campaign couldn&apos;t be generated</p>
        <p className="mt-1 text-sm text-slate-500">The website may have blocked our reader. Try again, use the homepage URL, or your Instagram handle.</p>
        <div className="mt-5 flex justify-center gap-2">
          {campaign.source_input && <button onClick={retry} className="btn-primary">Try again</button>}
          <Link href="/" className="btn-ghost">New campaign</Link>
        </div>
      </div>
    );
  }

  const b = campaign.brand;
  const approved = campaign.posts.filter((p) => p.status !== "DRAFT").length;
  const published = campaign.posts.filter((p) => p.status === "PUBLISHED").length;
  const next = ordered.find((p) => p.status !== "PUBLISHED" && new Date(p.publish_at).getTime() > Date.now());
  const groups = groupPosts(campaign.posts);
  const open = campaign.posts.find((p) => p.id === openId) ?? null;
  const gi = open ? groups.findIndex((g) => g.some((v) => v.id === open.id)) : -1;
  // Previous / next move between posts, staying on the same platform when that post has it.
  const sibling = (g: SocialPost[]) => (g.find((v) => v.platform === open?.platform) ?? g[0]).id;
  const anyConnected = !!pub && (Object.values(pub.connected).some(Boolean) || pub.webhook);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-4">
        <Link href="/campaigns" className="rounded-xl p-2 hover:bg-slate-200/70" aria-label="Back to campaigns"><ArrowLeft size={18} /></Link>
        {b.logo_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={b.logo_url.startsWith("/") ? media(b.logo_url) : b.logo_url} alt={`${b.name} logo`}
            className="h-14 w-14 shrink-0 rounded-2xl border border-slate-200 bg-white object-contain p-1.5 shadow-lift" />
        ) : (
          <span className="h-14 w-14 shrink-0 rounded-2xl shadow-lift" style={{ background: `linear-gradient(135deg, ${b.primary_color}, ${b.accent_color})` }} />
        )}
        <div className="min-w-0">
          <h1 className="truncate text-2xl font-bold">{b.name}</h1>
          <p className="flex items-center gap-2 truncate text-sm text-slate-500">
            {[b.industry, b.location].filter(Boolean).join(" · ")}
            <span className="flex gap-1">{campaign.platforms.map((p) => <PlatformIcon key={p} platform={p} size={13} />)}</span>
          </p>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {anyConnected && (
            <label className="flex cursor-pointer items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm" title="Approved posts are published automatically at their scheduled time">
              <span className={`relative h-5 w-9 rounded-full transition ${pub?.auto_publish ? "bg-brand" : "bg-slate-300"}`}>
                <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition ${pub?.auto_publish ? "left-[18px]" : "left-0.5"}`} />
              </span>
              <input type="checkbox" className="sr-only" checked={!!pub?.auto_publish} onChange={async (e) => setPub(await api.setAutoPublish(e.target.checked))} />
              Auto-post approved
            </label>
          )}
          <a href={api.exportUrl(campaign.id)} className="btn-ghost"><Download size={16} /> Export</a>
          <button onClick={async () => setCampaign(await api.approveAll(campaign.id))} disabled={approved === campaign.posts.length} className="btn-primary">
            <CheckCheck size={16} /> Approve all
          </button>
        </div>
      </div>

      {b.source_type === "handle" && !b.website_url && !b.logo_url && tab !== "brand" && (
        <div className="flex flex-wrap items-center gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <Palette size={18} className="shrink-0 text-amber-600" />
          <p className="min-w-0 flex-1">We couldn&apos;t find a website for this handle, so your posts use default colours. Add your logo and brand colours to make them yours.</p>
          <button onClick={() => setTab("brand")} className="btn-dark btn-sm">Set up brand kit</button>
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          {
            label: "Posts", value: groups.length, icon: Layers,
            sub: campaign.platforms.length > 1 ? `× ${campaign.platforms.length} platforms = ${campaign.posts.length} versions` : `over ${campaign.days} days`,
          },
          { label: "Approved", value: `${approved}/${campaign.posts.length}`, sub: approved === campaign.posts.length ? "all set" : `${campaign.posts.length - approved} to review`, icon: CheckCheck },
          { label: "Posted", value: published, sub: published ? "live on your channels" : "nothing posted yet", icon: Send },
          {
            label: "Next post",
            value: next ? fmtDay(next.publish_at, { month: "short", day: "numeric" }) : "–",
            sub: next ? `${PLATFORM_META[next.platform].label} · ${fmtTime(next.publish_at)}` : "no upcoming posts",
            icon: CalendarClock,
          },
        ].map(({ label, value, sub, icon: Icon }) => (
          <div key={label} className="card flex items-center gap-3 px-4 py-3">
            <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand"><Icon size={18} /></span>
            <div className="min-w-0">
              <p className="label">{label}</p>
              <p className="text-xl font-bold leading-tight">{value}</p>
              <p className="truncate text-[11px] text-slate-500">{sub}</p>
            </div>
          </div>
        ))}
      </div>

      <div className="flex items-end justify-between gap-3 border-b border-slate-200">
        <div className="no-scrollbar flex gap-1 overflow-x-auto overflow-y-hidden">
          {([["plan", "Schedule", CalendarDays], ["feed", "Feed preview", Grid3x3], ["brand", "Brand kit", Palette], ["strategy", "Strategy", Lightbulb]] as const).map(([key, label, Icon]) => (
            <button key={key} onClick={() => setTab(key)}
              className={`-mb-px flex items-center gap-2 whitespace-nowrap border-b-2 px-4 py-2.5 text-sm font-medium ${tab === key ? "border-brand text-brand" : "border-transparent text-slate-500 hover:text-ink"}`}>
              <Icon size={15} /> {label}
            </button>
          ))}
        </div>
        {tab === "plan" && (
          <div className="seg mb-2 hidden sm:inline-flex">
            <button data-active={view === "calendar"} onClick={() => setView("calendar")} className="flex items-center gap-1"><CalendarDays size={13} /> Calendar</button>
            <button data-active={view === "list"} onClick={() => setView("list")} className="flex items-center gap-1"><List size={13} /> List</button>
          </div>
        )}
      </div>

      {error && <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {tab === "plan" && (view === "list" ? (
        <QueueList posts={campaign.posts} onOpen={(p) => setOpenId(p.id)} onApprove={approve} />
      ) : (
        <>
          <div className="sm:hidden"><QueueList posts={campaign.posts} onOpen={(p) => setOpenId(p.id)} onApprove={approve} /></div>
          <div className="hidden sm:block">
            <p className="mb-3 text-xs text-slate-500">Each post has a version for every platform; click a platform icon to open that version. Drag a post to another day to move every version.</p>
            <CalendarView posts={campaign.posts} startDate={campaign.start_date} days={campaign.days} onOpen={(p) => setOpenId(p.id)} onMove={move} />
          </div>
        </>
      ))}
      {tab === "feed" && <FeedGrid posts={campaign.posts} brand={b} platforms={campaign.platforms} onOpen={(p) => setOpenId(p.id)} />}
      {tab === "brand" && <BrandKitPanel campaign={campaign} onSaved={setCampaign} />}
      {tab === "strategy" && <StrategyPanel campaign={campaign} />}

      {open && (
        <PostEditor
          post={open}
          brand={b}
          connected={pub?.connected[open.platform] || !!pub?.webhook}
          onClose={() => setOpenId(null)}
          onChange={replacePost}
          versions={gi >= 0 ? groups[gi] : [open]}
          onSwitch={setOpenId}
          onPrev={gi > 0 ? () => setOpenId(sibling(groups[gi - 1])) : undefined}
          onNext={gi >= 0 && gi < groups.length - 1 ? () => setOpenId(sibling(groups[gi + 1])) : undefined}
        />
      )}
    </div>
  );
}

export default function Page() {
  return (
    <Suspense fallback={<Loader2 className="mx-auto mt-20 animate-spin text-slate-400" />}>
      <CampaignPage />
    </Suspense>
  );
}
