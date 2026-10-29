"use client";

import { Suspense, useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Bot, Camera, Check, Clapperboard, Download, Film, Hand, Loader2, Mic, Plus, RefreshCw, Sparkles, Trash2, Upload, Wand2, X } from "lucide-react";
import { api, media, type Campaign, type CampaignSummary, type UgcAd, type UgcAvatar, type UgcOverview, type UgcScene, type UgcVoice } from "@/lib/api";
import { useFeedback } from "@/components/Feedback";
import { Recorder } from "@/components/Recorder";

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
  const [engine, setEngine] = useState<"builtin" | "scenes" | "presenter" | "person" | "avatar">("scenes");
  const [style, setStyle] = useState("worn");
  const [source, setSource] = useState<"local" | "ai">("local");
  const [shots, setShots] = useState<UgcScene[]>([]);
  const [planning, setPlanning] = useState(false);
  const [language, setLanguage] = useState("en");
  const [voiceKey, setVoiceKey] = useState("");
  const [character, setCharacter] = useState("amna");
  const [look, setLook] = useState("");
  const [captionStyle, setCaptionStyle] = useState("");
  const [voice, setVoice] = useState(false);
  const [footage, setFootage] = useState<{ id: string; url: string; seconds: number } | null>(null);
  const [recording, setRecording] = useState(false);
  const [uploading, setUploading] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
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

  async function takeClip(clip: Blob, name?: string) {
    setRecording(false);
    setUploading(true);
    try { setFootage(await api.uploadFootage(clip, name)); }
    catch (e) { toast((e as Error).message, "error"); }
    finally { setUploading(false); }
  }

  // AI scenes: a shot for each line (up to four), planned for the product, editable before filming.
  const shotCount = Math.min(4, Math.max(1, lines.filter((l) => l.trim()).length));
  async function planShots() {
    setPlanning(true);
    try { setShots((await api.ugcScenes(cid, { product, lines: shotCount, style })).scenes); }
    catch (e) { toast((e as Error).message, "error"); }
    finally { setPlanning(false); }
  }
  useEffect(() => { if (engine === "scenes" && info?.products.length) planShots(); }, [engine, product, style, shotCount, info?.products.length]); // eslint-disable-line react-hooks/exhaustive-deps

  async function writeScript() {
    setWriting(true);
    try { setLines((await api.ugcScript(cid, { product, format, language })).lines); }
    catch (e) { toast((e as Error).message, "error"); }
    finally { setWriting(false); }
  }
  // A fresh script whenever the product or format changes.
  useEffect(() => { if (info?.products.length) writeScript(); }, [product, format, language, info?.products.length]); // eslint-disable-line react-hooks/exhaustive-deps
  // The voice follows the script's language and the presenter, until you pick one yourself.
  const [voicePicked, setVoicePicked] = useState(false);
  useEffect(() => {
    if (voicePicked || !info) return;
    const gender = engine === "presenter" ? info.presenters.find((p) => p.key === character)?.gender ?? "female" : "female";
    const lang = language === "ur" ? "ur" : "en";
    const match = info.voices.find((v) => v.language === lang && v.gender === gender && v.clear) ?? info.voices[0];
    if (match) setVoiceKey(match.key);
  }, [info, language, character, engine, voicePicked]);

  async function make() {
    setJob({ step: "Starting" });
    try {
      // "No presenter": the same voice and captions over a product video, without a character.
      const noPresenter = engine === "presenter" && character === "none";
      const ad = await api.makeUgc(cid, {
        product, format, lines: lines.filter((l) => l.trim()), engine: noPresenter ? "builtin" : engine, avatar_id: avatar?.id,
        avatar_name: avatar?.name, look, caption: captionStyle, voice: (engine === "builtin" && voice) || noPresenter, footage: footage?.id,
        voice_key: voiceKey || undefined, character: engine === "presenter" && !noPresenter ? character : undefined, language,
        style: engine === "scenes" ? style : undefined, scenes: engine === "scenes" ? shots.slice(0, shotCount) : undefined,
        source: engine === "scenes" ? source : undefined,
      }, (step) => setJob({ step }));
      setInfo((i) => (i ? { ...i, ads: [ad, ...i.ads] } : i));
      toast(engine === "scenes" ? "Your AI scenes ad is ready" : engine === "avatar" || engine === "presenter" ? "Your presenter ad is ready" : engine === "person" ? "Your video is edited and captioned" : "Your UGC ad is ready", "success");
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
      {recording && <Recorder script={lines.filter((l) => l.trim())} onClose={() => setRecording(false)} onDone={(clip) => takeClip(clip)} />}
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
                <div className="flex items-center gap-2">
                  <div className="seg">
                    {info.languages.map((l) => <button key={l.key} data-active={language === l.key} onClick={() => setLanguage(l.key)}>{l.label}</button>)}
                  </div>
                  <button onClick={writeScript} disabled={writing} className="btn-ghost btn-sm">{writing ? <Loader2 size={14} className="animate-spin" /> : <Wand2 size={14} />} Write again</button>
                </div>
              </div>
              <div className="space-y-2">
                {lines.map((l, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="w-5 shrink-0 text-right text-xs text-slate-400">{i + 1}</span>
                    <input className="input" dir="auto" value={l} maxLength={140} onChange={(e) => setLines(lines.map((x, j) => (j === i ? e.target.value : x)))} />
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
              <button onClick={() => setEngine("scenes")}
                className={`mb-2 w-full rounded-xl border p-4 text-left ${engine === "scenes" ? "border-brand bg-brand-soft" : "border-slate-200"}`}>
                <p className="flex items-center gap-2 font-semibold"><Clapperboard size={16} /> AI scenes <span className="chip bg-brand text-white">Premium look, free</span></p>
                <p className="mt-1 text-xs text-slate-600">
                  A new shot for every line, like Flow or Higgsfield ads: your product filmed with a 3D camera right on this computer (free, no
                  limits), or AI video of it being worn, applied or held. Worn, faceless or soft aesthetic, with a voice or music and captions.
                </p>
              </button>
              <div className="grid gap-2 sm:grid-cols-3">
                <button onClick={() => setEngine("builtin")} className={`rounded-xl border p-4 text-left ${engine === "builtin" ? "border-brand bg-brand-soft" : "border-slate-200"}`}>
                  <p className="flex items-center gap-2 font-semibold"><Film size={16} /> Product video</p>
                  <p className="mt-1 text-xs text-slate-600">Your product photo filmed phone-style, a new look every time, with an optional AI voice. Free, about 15 seconds.</p>
                </button>
                <button onClick={() => setEngine("person")} className={`rounded-xl border p-4 text-left ${engine === "person" ? "border-brand bg-brand-soft" : "border-slate-200"}`}>
                  <p className="flex items-center gap-2 font-semibold"><Camera size={16} /> Real person</p>
                  <p className="mt-1 text-xs text-slate-600">Record yourself (teleprompter included) or upload a clip. MonoPlus captions it, adds the product and an end card. Free.</p>
                </button>
                <button onClick={() => setEngine("presenter")} className={`rounded-xl border p-4 text-left ${engine === "presenter" ? "border-brand bg-brand-soft" : "border-slate-200"}`}>
                  <p className="flex items-center gap-2 font-semibold"><Bot size={16} /> Cartoon presenter</p>
                  <p className="mt-1 text-xs text-slate-600">An illustrated character speaks your script beside your product. Free, made on this computer, works offline.</p>
                </button>
              </div>
              {info.heygen && (
                <button onClick={() => setEngine("avatar")} className={`mt-2 w-full rounded-xl border px-4 py-2.5 text-left text-xs ${engine === "avatar" ? "border-brand bg-brand-soft" : "border-slate-200 text-slate-600"}`}>
                  <span className="font-semibold">Realistic presenter (HeyGen, paid)</span> · you connected HeyGen, so its realistic presenters are available too.
                </button>
              )}
              {engine === "scenes" && (
                <div className="mt-4 space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="w-16 text-xs font-medium text-slate-600">Filmed by</span>
                    <div className="seg">
                      <button data-active={source === "local"} onClick={() => setSource("local")}>3D camera, on this computer</button>
                      <button data-active={source === "ai"} onClick={() => setSource("ai")}>AI video (Hugging Face)</button>
                    </div>
                  </div>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="w-16 text-xs font-medium text-slate-600">Style</span>
                    <div className="seg">
                      {info.scenes.styles.map((s) => (
                        <button key={s.key} data-active={style === s.key}
                          onClick={() => { setStyle(s.key); if (s.key === "aesthetic" && info.formats.some((f) => f.key === "aesthetic")) setFormat("aesthetic"); }}>
                          <span className="inline-flex items-center gap-1">{s.key === "faceless" && <Hand size={13} />}{s.label}</span>
                        </button>
                      ))}
                    </div>
                  </div>
                  {source === "ai" && <div>
                    <div className="mb-1.5 flex items-center justify-between">
                      <p className="text-xs font-medium text-slate-600">
                        The shots, one per line{shotCount < lines.filter((l) => l.trim()).length ? " (later lines reuse them)" : ""}
                      </p>
                      <button onClick={planShots} disabled={planning} className="btn-ghost btn-sm">
                        {planning ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />} New shots
                      </button>
                    </div>
                    <div className="space-y-1.5">
                      {shots.slice(0, shotCount).map((s, i) => (
                        <div key={i} className="flex items-center gap-2">
                          <span className="w-12 shrink-0 text-[11px] text-slate-400">Shot {i + 1}</span>
                          <input className="input text-xs" value={s.prompt} maxLength={300}
                            onChange={(e) => setShots(shots.map((x, j) => (j === i ? { ...x, prompt: e.target.value } : x)))} />
                        </div>
                      ))}
                    </div>
                  </div>}
                  {style === "aesthetic" ? (
                    <p className="rounded-xl bg-brand-soft px-3 py-2 text-xs text-brand-700">
                      No voice: soft music composed for this ad (yours to post anywhere), slow dissolves, a warm film look and quiet captions.
                      Want a trending sound? Add it in Instagram or TikTok when you post.
                    </p>
                  ) : (
                    <>
                      <VoicePicker voices={info.voices} value={voiceKey} onChange={(k) => { setVoiceKey(k); setVoicePicked(true); }} language={language} />
                      <Chips label="Captions" value={captionStyle} onChange={setCaptionStyle} options={[{ key: "", label: "Surprise me" }, ...info.captions]} />
                    </>
                  )}
                  {source === "local" ? (
                    <p className="text-xs text-slate-500">
                      MonoPlus works out the depth of your product photo and films it with a moving 3D camera (dolly, orbit, rise, a little
                      handheld sway), a new crop and move for every line. Everything runs on this computer: no account, no daily limit, nothing sent
                      anywhere. The 3D model downloads once (about 100 MB). It moves the camera, not the person: for hands and people moving, choose AI video.
                    </p>
                  ) : (
                  <p className="text-xs text-slate-500">
                    Each shot starts from your product photo and is filmed by Wan 2.2, an open-source video model, on Hugging Face&apos;s free GPUs: about a
                    minute per shot. Only the photo and the shot description are sent.{" "}
                    {info.scenes.huggingface ? "Your free Hugging Face account is connected for a bigger share." : (
                      <>Without an account the free share covers only a few shots: <Link href="/connections" className="link">connect a free Hugging Face account</Link> for more.</>
                    )}{" "}
                    If the share runs out mid-ad, the shots already filmed carry the rest.
                    {style === "worn" && <> When an ad shows AI-generated people, turn on the platform&apos;s &ldquo;AI-generated&rdquo; label when you post.</>}
                  </p>
                  )}
                </div>
              )}
              {engine === "presenter" && (
                <div className="mt-4 space-y-3">
                  <p className="text-xs font-medium text-slate-600">Choose a presenter</p>
                  <div className="grid grid-cols-4 gap-2 sm:grid-cols-7">
                    <button onClick={() => setCharacter("none")} title="No presenter: your product, a voice and captions"
                      className={`flex flex-col overflow-hidden rounded-xl border-2 bg-white ${character === "none" ? "border-brand" : "border-slate-200 hover:border-slate-300"}`}>
                      <span className="grid aspect-square w-full place-items-center text-slate-400"><Film size={28} /></span>
                      <p className="py-1 text-center text-[11px] font-medium">No presenter</p>
                    </button>
                    {info.presenters.map((p) => (
                      <button key={p.key} onClick={() => setCharacter(p.key)} title={p.name}
                        className={`overflow-hidden rounded-xl border-2 bg-[#EEECFA] ${character === p.key ? "border-brand" : "border-transparent hover:border-slate-200"}`}>
                        {/* eslint-disable-next-line @next/next/no-img-element */}
                        <img src={media(p.preview)} alt={p.name} className="aspect-square w-full object-cover" />
                        <p className="py-1 text-center text-[11px] font-medium">{p.name}</p>
                      </button>
                    ))}
                  </div>
                  <VoicePicker voices={info.voices} value={voiceKey} onChange={(k) => { setVoiceKey(k); setVoicePicked(true); }} language={language} />
                  <Chips label="Captions" value={captionStyle} onChange={setCaptionStyle} options={[{ key: "", label: "Surprise me" }, ...info.captions]} />
                  <p className="text-xs text-slate-500">
                    {character === "none"
                      ? "No character: your product filmed phone-style with a new look each time, the voice reading the script, and captions."
                      : "The presenter is an illustrated, fictional character: it waves, points at your product when it's mentioned, talks with its hands, and its lips follow the voice. It wears your brand colour and logo."}
                  </p>
                </div>
              )}
              {engine === "builtin" && (
                <div className="mt-4 space-y-3">
                  <Chips label="Look" value={look} onChange={setLook} options={[{ key: "", label: "Surprise me" }, ...info.looks]} />
                  <Chips label="Captions" value={captionStyle} onChange={setCaptionStyle} options={[{ key: "", label: "Surprise me" }, ...info.captions]} />
                  <label className={`flex items-start gap-2 rounded-xl border px-3 py-2.5 text-sm ${info.voice ? "cursor-pointer border-slate-200" : "border-dashed border-slate-200 text-slate-400"}`}>
                    <input type="checkbox" checked={voice} disabled={!info.voice} onChange={(e) => setVoice(e.target.checked)} className="mt-0.5 accent-brand" />
                    <span>
                      <span className="flex items-center gap-1.5 font-medium"><Mic size={14} /> AI voice reads the script</span>
                      <span className="block text-xs text-slate-500">
                        {info.voice ? "Free voices made on this computer, in several accents and languages. Each downloads once (about 60 MB)." : "Not installed on this computer: pip install piper-tts"}
                      </span>
                    </span>
                  </label>
                  {voice && <VoicePicker voices={info.voices} value={voiceKey} onChange={(k) => { setVoiceKey(k); setVoicePicked(true); }} language={language} />}
                </div>
              )}
              {engine === "person" && (
                <div className="mt-4 space-y-3">
                  {footage ? (
                    <div className="flex gap-3 rounded-xl border border-slate-200 p-3">
                      <video src={media(footage.url)} className="h-40 w-24 rounded-lg bg-black object-cover" controls playsInline />
                      <div className="text-sm">
                        <p className="font-medium">Your clip · {Math.round(footage.seconds)}s</p>
                        <p className="mt-1 text-xs text-slate-500">MonoPlus will trim it to the speech, caption what you say (in the script&apos;s spelling when you read it), show the product when you mention it, and add an end card.</p>
                        <button onClick={() => setFootage(null)} className="btn-ghost btn-sm mt-2">Use another clip</button>
                      </div>
                    </div>
                  ) : (
                    <div className="grid gap-2 sm:grid-cols-2">
                      <button onClick={() => setRecording(true)} disabled={uploading} className="btn-primary"><Camera size={15} /> Record with teleprompter</button>
                      <button onClick={() => fileRef.current?.click()} disabled={uploading} className="btn-ghost">
                        {uploading ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />} Upload a phone video
                      </button>
                      <input ref={fileRef} type="file" accept="video/*" hidden onChange={(e) => { const f = e.target.files?.[0]; if (f) takeClip(f, f.name); e.target.value = ""; }} />
                    </div>
                  )}
                  <Chips label="Captions" value={captionStyle} onChange={setCaptionStyle} options={[{ key: "", label: "Surprise me" }, ...info.captions.filter((c) => c.key !== "karaoke")]} />
                  {!info.listening && <p className="text-xs text-amber-700">Captions need speech recognition: pip install faster-whisper</p>}
                  <p className="text-xs text-slate-500">Film yourself, your team, or a customer or creator who has agreed to appear. That&apos;s what real UGC is.</p>
                </div>
              )}
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
              <button onClick={make} disabled={!!job || !lines.some((l) => l.trim()) || (engine === "avatar" && (!info.heygen || !avatar)) || (engine === "person" && !footage) || (engine === "scenes" && (planning || !shots.length))}
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

function VoicePicker({ voices, value, onChange, language }: { voices: UgcVoice[]; value: string; onChange: (k: string) => void; language: string }) {
  const groups = Array.from(new Set(voices.map((v) => v.accent)));
  const chosen = voices.find((v) => v.key === value);
  const mismatch = chosen && ((language === "ur") !== (chosen.language === "ur"));
  return (
    <div className="rounded-xl border border-slate-200 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="flex items-center gap-1.5 text-xs font-medium text-slate-600"><Mic size={13} /> Voice</span>
        <select value={value} onChange={(e) => onChange(e.target.value)} className="input w-auto flex-1 py-1.5 text-sm">
          {groups.map((g) => (
            <optgroup key={g} label={g}>
              {voices.filter((v) => v.accent === g).map((v) => (
                <option key={v.key} value={v.key}>{v.name} · {v.gender}{v.clear ? "" : " · for testing"}</option>
              ))}
            </optgroup>
          ))}
        </select>
        {value && <audio key={value} src={media(`/api/ugc/voices/${value}/sample.wav`)} controls preload="none" className="h-8 w-44" />}
      </div>
      {chosen && !chosen.clear && (
        <p className="mt-2 text-xs text-amber-700">&ldquo;{chosen.name}&rdquo; is built on a voice trained on research-licensed recordings: fine for trying out, check before using it in paid ads.</p>
      )}
      {mismatch && (
        <p className="mt-2 text-xs text-amber-700">
          {language === "ur" ? "This script is in Urdu: choose an Urdu voice (Ayesha or Fasih)." : language === "roman"
            ? "Voices can't read Roman Urdu well. Switch the script to اردو (Urdu) for an Urdu voice, or keep English."
            : "This voice reads Urdu script; the script is in English."}
        </p>
      )}
      {!mismatch && language === "roman" && (
        <p className="mt-2 text-xs text-amber-700">Voices can&apos;t read Roman Urdu well. Switch the script to اردو (Urdu) for an Urdu voice, or keep English.</p>
      )}
    </div>
  );
}

function Chips({ label, value, options, onChange }: { label: string; value: string; options: { key: string; label: string }[]; onChange: (v: string) => void }) {
  return (
    <div>
      <p className="mb-1.5 text-xs font-medium text-slate-600">{label}</p>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => (
          <button key={o.key || "auto"} onClick={() => onChange(o.key)}
            className={`rounded-full border px-3 py-1 text-xs font-medium ${value === o.key ? "border-brand bg-brand-soft text-brand" : "border-slate-200 text-slate-600 hover:border-slate-300"}`}>
            {o.key === "" ? <Sparkles size={11} className="mr-1 inline" /> : null}{o.label}
          </button>
        ))}
      </div>
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
        <p className="font-semibold">
          {ad.product} · {ad.format.replace("_", " ")}
          {ad.engine === "avatar" ? ` · HeyGen presenter${ad.avatar ? ` (${ad.avatar})` : ""}` : ad.engine === "presenter" ? ` · presenter ${ad.avatar}`
            : ad.engine === "person" ? " · real person" : ad.engine === "scenes" ? ` · ${ad.source === "ai" ? "AI video" : "3D camera"}${ad.look === "faceless" ? ", faceless" : ad.look === "aesthetic" ? ", aesthetic" : ""}` : ad.look ? ` · ${ad.look}${ad.voice ? ", voiced" : ""}` : ""}
        </p>
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
