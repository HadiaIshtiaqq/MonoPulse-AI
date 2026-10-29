"use client";

import { Suspense, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Bot, Check, Clapperboard, Download, Film, Loader2, Plus, Sparkles, Trash2, Wand2, X } from "lucide-react";
import { api, media, type Campaign, type CampaignSummary, type UgcAd, type UgcAvatar, type UgcOverview } from "@/lib/api";
import { useFeedback } from "@/components/Feedback";

export default function UgcPage() {
  return <Suspense fallback={null}><Studio /></Suspense>;
}

function Studio() {
  const router = useRouter();
  const params = useSearchParams();
  const { toast, confirm } = useFeedback();
  const [campaigns, setCampaigns] = useState<CampaignSummary[] | null>(null);
  const cid = params.get("c") || "";
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [info, setInfo] = useState<UgcOverview | null>(null);
  const [product, setProduct] = useState(0);
  const [format, setFormat] = useState("pov");
  const [lines, setLines] = useState<string[]>([]);
  const [writing, setWriting] = useState(false);
  const [engine, setEngine] = useState<"builtin" | "avatar">("builtin");
  const [avatars, setAvatars] = useState<UgcAvatar[] | null>(null);
  const [avatar, setAvatar] = useState<UgcAvatar | null>(null);
  const [job, setJob] = useState<{ step: string } | null>(null);

  useEffect(() => { api.campaigns().then(setCampaigns).catch(() => setCampaigns([])); }, []);
  const load = useCallback(async () => {
    if (!cid) return;
    try {
      const [c, o] = await Promise.all([api.campaign(cid), api.ugcOverview(cid)]);
      setCampaign(c); setInfo(o);
    } catch (e) { toast((e as Error).message, "error"); }
  }, [cid, toast]);
  useEffect(() => { setInfo(null); setLines([]); load(); }, [load]);
  useEffect(() => {
    if (engine === "avatar" && info?.heygen && avatars === null) api.ugcAvatars().then(setAvatars).catch((e) => { setAvatars([]); toast((e as Error).message, "error"); });
  }, [engine, info, avatars, toast]);

  async function writeScript() {
    setWriting(true);
    try { setLines((await api.ugcScript(cid, { product, format })).lines); }
    catch (e) { toast((e as Error).message, "error"); }
    finally { setWriting(false); }
  }
  // A fresh script whenever the product or format changes.
  useEffect(() => { if (info?.products.length) writeScript(); }, [product, format, info?.products.length]); // eslint-disable-line react-hooks/exhaustive-deps

  async function make() {
    setJob({ step: "Starting" });
    try {
      const ad = await api.makeUgc(cid, { product, format, lines: lines.filter((l) => l.trim()), engine, avatar_id: avatar?.id, avatar_name: avatar?.name },
        (step) => setJob({ step }));
      setInfo((i) => (i ? { ...i, ads: [ad, ...i.ads] } : i));
      toast(engine === "avatar" ? "Your AI presenter ad is ready" : "Your UGC ad is ready", "success");
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setJob(null); }
  }

  if (!cid) {
    return (
      <div className="space-y-6">
        <Header />
        <p className="text-sm text-slate-600">Pick a brand to make ads for:</p>
        {!campaigns ? <Loader2 className="animate-spin text-slate-400" /> : (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {campaigns.map((c) => (
              <button key={c.id} onClick={() => router.push(`/ugc?c=${c.id}`)} className="card flex items-center gap-3 p-4 text-left hover:border-brand">
                <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl text-white" style={{ background: c.primary_color || "#6D5DFC" }}><Clapperboard size={17} /></span>
                <span className="min-w-0"><span className="block truncate font-semibold">{c.name}</span><span className="text-xs text-slate-500">{c.posts} posts</span></span>
              </button>
            ))}
            {campaigns.length === 0 && <p className="text-sm text-slate-500">Create a campaign first: <Link href="/" className="link">New campaign</Link>.</p>}
          </div>
        )}
      </div>
    );
  }
  if (!info || !campaign) return <div className="space-y-6"><Header /><Loader2 className="animate-spin text-slate-400" /></div>;
  const chosen = info.products[product];

  return (
    <div className="space-y-6">
      <Header brand={campaign.brand?.name} onSwitch={() => router.push("/ugc")} />
      {info.products.length === 0 ? (
        <p className="rounded-xl bg-amber-50 px-4 py-3 text-sm text-amber-900">No product photos were found for {campaign.brand?.name}. UGC ads are built around a product photo.</p>
      ) : (
        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
          <div className="min-w-0 space-y-6">
            <section className="card p-5">
              <p className="label mb-3">1. Product</p>
              <div className="flex gap-3 overflow-x-auto pb-1">
                {info.products.map((p) => (
                  <button key={p.index} onClick={() => setProduct(p.index)}
                    className={`w-32 shrink-0 overflow-hidden rounded-xl border-2 text-left ${p.index === product ? "border-brand" : "border-transparent hover:border-slate-200"}`}>
                    {/* eslint-disable-next-line @next/next/no-img-element */}
                    <img src={p.image.startsWith("/media/") ? media(p.image) : p.image} alt="" className="aspect-square w-full bg-slate-100 object-cover" />
                    <p className="truncate px-2 pt-1.5 text-xs font-medium">{p.name}</p>
                    <p className="px-2 pb-1.5 text-[11px] text-slate-500">{p.price}</p>
                  </button>
                ))}
              </div>
            </section>

            <section className="card p-5">
              <p className="label mb-3">2. Format</p>
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {info.formats.map((f) => (
                  <button key={f.key} onClick={() => setFormat(f.key)}
                    className={`rounded-xl border p-3 text-left ${f.key === format ? "border-brand bg-brand-soft" : "border-slate-200 hover:border-slate-300"}`}>
                    <p className="text-sm font-semibold">{f.label}</p>
                    <p className="mt-0.5 text-xs text-slate-500">{f.blurb}</p>
                  </button>
                ))}
              </div>
            </section>

            <section className="card p-5">
              <div className="mb-3 flex items-center justify-between">
                <p className="label">3. Script</p>
                <button onClick={writeScript} disabled={writing} className="btn-ghost btn-sm">{writing ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />} Write again</button>
              </div>
              <div className="space-y-2">
                {lines.map((l, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="w-5 shrink-0 text-right text-xs text-slate-400">{i + 1}</span>
                    <input className="input" value={l} maxLength={140} onChange={(e) => setLines(lines.map((x, j) => (j === i ? e.target.value : x)))} />
                    <button onClick={() => setLines(lines.filter((_, j) => j !== i))} className="rounded p-1.5 text-slate-400 hover:text-red-600" title="Remove line"><X size={14} /></button>
                  </div>
                ))}
                {lines.length < 8 && <button onClick={() => setLines([...lines, ""])} className="btn-ghost btn-sm"><Plus size={14} /> Add a line</button>}
              </div>
              <p className="mt-3 text-xs text-slate-500">
                Scripts use only real facts about {chosen?.name}: its name, price, sale and {campaign.brand?.name}&apos;s own promises. Keep it that way:
                ads that invent results or reviews mislead buyers and get taken down.
              </p>
            </section>

            <section className="card p-5">
              <p className="label mb-3">4. How it&apos;s made</p>
              <div className="grid gap-2 sm:grid-cols-2">
                <button onClick={() => setEngine("builtin")} className={`rounded-xl border p-4 text-left ${engine === "builtin" ? "border-brand bg-brand-soft" : "border-slate-200"}`}>
                  <p className="flex items-center gap-2 font-semibold"><Film size={16} /> Phone-style product video</p>
                  <p className="mt-1 text-xs text-slate-600">Handheld camera feel on your product photo, big word-by-word captions. Free, made on this computer in about 10 seconds.</p>
                </button>
                <button onClick={() => setEngine("avatar")} className={`rounded-xl border p-4 text-left ${engine === "avatar" ? "border-brand bg-brand-soft" : "border-slate-200"}`}>
                  <p className="flex items-center gap-2 font-semibold"><Bot size={16} /> AI presenter</p>
                  <p className="mt-1 text-xs text-slate-600">A realistic AI person speaks your script in front of the product (HeyGen). Takes a few minutes; uses your HeyGen credits.</p>
                </button>
              </div>
              {engine === "avatar" && !info.heygen && (
                <p className="mt-3 rounded-xl bg-brand-soft px-3 py-2 text-xs text-brand-700">
                  Connect HeyGen first: <Link href="/connections" className="font-semibold underline">Open Connections</Link>.
                </p>
              )}
              {engine === "avatar" && info.heygen && (
                <div className="mt-4">
                  <p className="mb-2 text-xs font-medium text-slate-600">Choose a presenter</p>
                  {avatars === null ? <Loader2 size={16} className="animate-spin text-slate-400" /> : (
                    <div className="grid max-h-72 grid-cols-3 gap-2 overflow-y-auto sm:grid-cols-5">
                      {avatars.map((a) => (
                        <button key={a.id} onClick={() => setAvatar(a)} className={`overflow-hidden rounded-xl border-2 ${avatar?.id === a.id ? "border-brand" : "border-transparent"}`} title={a.name}>
                          {/* eslint-disable-next-line @next/next/no-img-element */}
                          {a.preview ? <img src={a.preview} alt={a.name} className="aspect-[3/4] w-full bg-slate-100 object-cover" /> : <div className="aspect-[3/4] bg-slate-100" />}
                          <p className="truncate px-1 py-1 text-[10px]">{a.name}</p>
                        </button>
                      ))}
                    </div>
                  )}
                  <p className="mt-3 text-xs text-slate-500">
                    When you post an ad with an AI person, turn on the platform&apos;s &ldquo;AI-generated&rdquo; label (Meta and TikTok require it for realistic AI people).
                  </p>
                </div>
              )}
              <button onClick={make} disabled={!!job || !lines.some((l) => l.trim()) || (engine === "avatar" && (!info.heygen || !avatar))}
                className="btn-gradient mt-4 w-full">
                {job ? <Loader2 size={16} className="animate-spin" /> : <Sparkles size={16} />} {job ? job.step : "Make the ad"}
              </button>
            </section>
          </div>

          <aside className="space-y-3">
            <p className="label">Your ads ({info.ads.length})</p>
            {info.ads.length === 0 && <p className="text-sm text-slate-500">Ads you make appear here.</p>}
            {info.ads.map((ad) => (
              <AdCard key={ad.id} ad={ad} campaign={campaign}
                onDelete={async () => {
                  if (!(await confirm({ title: "Delete this ad?", confirm: "Delete", danger: true }))) return;
                  await api.deleteUgc(cid, ad.id);
                  setInfo((i) => (i ? { ...i, ads: i.ads.filter((x) => x.id !== ad.id) } : i));
                }} />
            ))}
          </aside>
        </div>
      )}
    </div>
  );
}

function Header({ brand, onSwitch }: { brand?: string; onSwitch?: () => void }) {
  return (
    <div className="flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="flex items-center gap-2 text-2xl font-bold"><Clapperboard size={22} className="text-brand" /> UGC ads{brand ? <span className="text-slate-400">· {brand}</span> : null}</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">Short vertical video ads in the casual, phone-shot style that performs on Reels and TikTok, made from your real products.</p>
      </div>
      {onSwitch && <button onClick={onSwitch} className="btn-ghost btn-sm">Change brand</button>}
    </div>
  );
}

function AdCard({ ad, campaign, onDelete }: { ad: UgcAd; campaign: Campaign; onDelete: () => void }) {
  const { toast } = useFeedback();
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const posts = campaign.posts.filter((p) => p.platform === "instagram" || p.platform === "facebook").slice(0, 60);
  return (
    <div className="card overflow-hidden">
      <video src={media(ad.video_url)} poster={ad.poster_url ? media(ad.poster_url) : undefined} controls playsInline className="aspect-[9/16] max-h-[420px] w-full bg-black object-contain" />
      <div className="space-y-2 p-3 text-xs">
        <p className="font-semibold">{ad.product} · {ad.format.replace("_", " ")}{ad.engine === "avatar" ? ` · AI presenter${ad.avatar ? ` (${ad.avatar})` : ""}` : ""}</p>
        <p className="line-clamp-2 text-slate-500">{ad.script.join(" / ")}</p>
        <div className="flex gap-1.5">
          <select value={target} onChange={(e) => setTarget(e.target.value)} className="input py-1 text-xs">
            <option value="">Use on a post…</option>
            {posts.map((p) => <option key={p.id} value={p.id}>{new Date(p.publish_at).toLocaleDateString()} · {p.platform} · {p.headline.slice(0, 30)}</option>)}
          </select>
          <button disabled={!target || busy} className="btn-ghost btn-sm shrink-0" onClick={async () => {
            setBusy(true);
            try { await api.attachUgc(campaign.id, ad.id, target); toast("The post now uses this video", "success"); setTarget(""); }
            catch (e) { toast((e as Error).message, "error"); } finally { setBusy(false); }
          }}>{busy ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}</button>
        </div>
        <div className="flex gap-1.5">
          <a href={media(ad.video_url)} download className="btn-ghost btn-sm flex-1"><Download size={13} /> Download</a>
          <button onClick={onDelete} className="btn-ghost btn-sm text-slate-500 hover:text-red-600"><Trash2 size={13} /></button>
        </div>
      </div>
    </div>
  );
}
