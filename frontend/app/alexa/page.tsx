"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Braces, Check, Copy, ExternalLink, Loader2, Mic, MicOff, Send, Volume2, VolumeX } from "lucide-react";
import { API_URL, api, fmtDay, fmtTime, type AlexaReply } from "@/lib/api";

type Turn = { id: number; user: string; reply?: AlexaReply; error?: string };

const SUGGESTIONS = [
  "Create a two week campaign for sweetgreen.com on Instagram and LinkedIn",
  "Is my campaign ready?",
  "What's posting this week?",
  "Approve them all",
  "Humanize this: In today's fast-paced world, our seamless app is a game-changer!",
  "Research what customers complain about with salad chains",
];

function Card({ card }: { card: AlexaReply["card"] }) {
  switch (card.type) {
    case "campaign_started":
      return (
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-wider text-sky-300">Campaign started</p>
          <p className="text-lg font-semibold">{card.days} days · {(card.platforms || []).join(", ")}</p>
          <Link href={`/campaign/${card.campaign_id}`} className="inline-flex items-center gap-1 text-sm text-sky-300 hover:underline">Watch it build <ExternalLink size={12} /></Link>
        </div>
      );
    case "campaign_status":
      if (card.status === "GENERATING")
        return (
          <div>
            <p className="text-xs uppercase tracking-wider text-sky-300">Building your campaign</p>
            <ul className="mt-2 space-y-1 text-sm">
              {(card.steps || []).map((s: any) => (
                <li key={s.step} className="flex items-center gap-2">
                  {s.status === "done" ? <Check size={13} className="text-emerald-400" /> : s.status === "running" ? <Loader2 size={13} className="animate-spin text-sky-300" /> : <span className="h-3 w-3 rounded-full border border-white/30" />}
                  <span className={s.status === "pending" ? "text-white/40" : ""}>{s.step}</span>
                </li>
              ))}
            </ul>
          </div>
        );
      return (
        <div className="flex gap-4">
          {card.next_post?.image_url && (
            // eslint-disable-next-line @next/next/no-img-element
            <img src={card.next_post.image_url} alt="" className="h-28 w-24 rounded-lg object-cover" />
          )}
          <div className="space-y-1">
            <p className="text-xs uppercase tracking-wider text-sky-300">{card.brand}</p>
            <p className="text-lg font-semibold">{card.posts} posts · {card.approved} approved</p>
            {card.next_post && <p className="text-sm text-white/70">Next: {card.next_post.platform} · {fmtDay(card.next_post.publish_at)} {fmtTime(card.next_post.publish_at)}</p>}
            <Link href={`/campaign/${card.campaign_id}`} className="inline-flex items-center gap-1 text-sm text-sky-300 hover:underline">Open in MonoPlus <ExternalLink size={12} /></Link>
          </div>
        </div>
      );
    case "post_list":
      return (
        <div>
          <p className="text-xs uppercase tracking-wider text-sky-300">{card.count} upcoming</p>
          <div className="mt-2 grid grid-cols-3 gap-2">
            {(card.posts || []).map((p: any) => (
              <div key={p.post_id} className="overflow-hidden rounded-lg bg-white/5">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                {p.image_url && <img src={p.image_url} alt="" className="aspect-square w-full object-cover" />}
                <p className="truncate px-2 py-1 text-[11px] text-white/80">{p.platform} · {fmtDay(p.publish_at, { weekday: "short", day: "numeric" })}</p>
              </div>
            ))}
          </div>
        </div>
      );
    case "approval":
      return <p className="text-lg font-semibold">✓ {card.approved_total} of {card.posts} posts approved</p>;
    case "humanized":
      return (
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-wider text-sky-300">{card.human_sounding_before}% → {card.human_sounding_after}% human-sounding</p>
          <p className="text-base leading-relaxed">{card.text}</p>
        </div>
      );
    case "research":
      return (
        <div className="space-y-2">
          <p className="text-xs uppercase tracking-wider text-sky-300">Market research</p>
          {card.insights?.verified_trend && <p className="text-base">{card.insights.verified_trend}</p>}
          {card.insights?.content_angles?.length > 0 && (
            <ul className="list-disc space-y-0.5 pl-5 text-sm text-white/80">{card.insights.content_angles.slice(0, 3).map((a: string) => <li key={a}>{a}</li>)}</ul>
          )}
          <p className="text-xs text-white/50">{(card.sources || []).length} sources · saved to your Research library</p>
        </div>
      );
    case "brand":
      return (
        <div className="flex items-center gap-4">
          <div className="flex gap-1">
            {Object.values(card.colors || {}).map((c: any) => <span key={c} className="h-10 w-10 rounded-lg border border-white/20" style={{ background: c }} />)}
          </div>
          <div>
            <p className="text-lg font-semibold">{card.name}</p>
            <p className="text-sm text-white/70">{card.tagline}</p>
          </div>
        </div>
      );
    default:
      return null;
  }
}

export default function AlexaPage() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [voice, setVoice] = useState(true);
  const [showTrace, setShowTrace] = useState<number | null>(null);
  const [copied, setCopied] = useState(false);
  const session = useRef(`web-${Math.random().toString(36).slice(2, 10)}`);
  const recog = useRef<any>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const canListen = typeof window !== "undefined" && ("webkitSpeechRecognition" in window || "SpeechRecognition" in window);

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: "smooth" }); }, [turns]);

  function speak(s: string) {
    if (!voice || typeof window === "undefined" || !("speechSynthesis" in window)) return;
    window.speechSynthesis.cancel();
    const u = new SpeechSynthesisUtterance(s);
    u.rate = 1.03;
    window.speechSynthesis.speak(u);
  }

  async function ask(utterance: string) {
    const q = utterance.trim();
    if (!q || busy) return;
    const id = Date.now();
    setTurns((t) => [...t, { id, user: q }]);
    setText("");
    setBusy(true);
    try {
      const reply = await api.alexa(q, session.current);
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, reply } : x)));
      speak(reply.speech);
    } catch (e) {
      setTurns((t) => t.map((x) => (x.id === id ? { ...x, error: (e as Error).message } : x)));
    } finally {
      setBusy(false);
    }
  }

  function toggleMic() {
    if (listening) { recog.current?.stop(); return; }
    const SR = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SR) return;
    const r = new SR();
    r.lang = "en-US";
    r.interimResults = false;
    r.onresult = (e: any) => ask(e.results[0][0].transcript);
    r.onend = () => setListening(false);
    r.onerror = () => setListening(false);
    recog.current = r;
    setListening(true);
    r.start();
  }

  const endpoint = `${API_URL}/mcp`;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Alexa+</h1>
          <p className="mt-1 max-w-2xl text-sm text-slate-600">
            Talk to MonoPlus the way you would on an Echo Show. Each request is sent to MonoPlus&apos;s MCP server as a real JSON-RPC
            tool call; open “MCP call” under any answer to see it.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2 text-xs">
          <span className="text-slate-500">MCP endpoint</span>
          <code className="font-mono">{endpoint}</code>
          <button onClick={() => { navigator.clipboard.writeText(endpoint); setCopied(true); setTimeout(() => setCopied(false), 1500); }} className="text-slate-400 hover:text-ink" aria-label="Copy endpoint">
            {copied ? <Check size={13} /> : <Copy size={13} />}
          </button>
        </div>
      </div>

      <div className="mx-auto max-w-4xl overflow-hidden rounded-[2rem] border-[10px] border-slate-900 bg-gradient-to-br from-[#0b1d33] via-[#0d2440] to-[#111a2e] text-white shadow-pop">
        <div className="flex items-center justify-between px-6 pt-4 text-xs text-white/50">
          <span>Echo Show · simulated</span>
          <button onClick={() => setVoice((v) => !v)} className="flex items-center gap-1 hover:text-white" title="Read answers aloud">
            {voice ? <Volume2 size={14} /> : <VolumeX size={14} />} {voice ? "Voice on" : "Voice off"}
          </button>
        </div>
        <div className="h-[460px] space-y-5 overflow-y-auto px-6 py-5 scrollbar-thin">
          {turns.length === 0 && (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <span className="grid h-20 w-20 place-items-center rounded-full bg-gradient-to-br from-sky-400 to-blue-600 shadow-[0_0_60px_rgba(56,189,248,.45)]">
                <Mic size={30} />
              </span>
              <p className="mt-5 text-xl font-semibold">Try “Alexa, create a campaign for my website”</p>
              <p className="mt-1 text-sm text-white/60">or pick a suggestion below.</p>
            </div>
          )}
          {turns.map((t) => (
            <div key={t.id} className="space-y-3">
              <p className="ml-auto w-fit max-w-[80%] rounded-2xl rounded-br-sm bg-white/10 px-4 py-2 text-sm">{t.user}</p>
              {!t.reply && !t.error && <p className="flex items-center gap-2 text-sm text-white/60"><Loader2 size={14} className="animate-spin" /> Working on it…</p>}
              {t.error && <p className="text-sm text-red-300">{t.error}</p>}
              {t.reply && (
                <div className="space-y-3">
                  <div className="flex items-start gap-3">
                    <span className="mt-1 h-3 w-3 shrink-0 rounded-full bg-sky-400 shadow-[0_0_12px_rgba(56,189,248,.8)]" />
                    <p className="text-lg leading-snug">{t.reply.speech}</p>
                  </div>
                  {t.reply.card.type !== "text" && t.reply.card.type !== "error" && (
                    <div className="ml-6 rounded-2xl border border-white/10 bg-white/5 p-4"><Card card={t.reply.card} /></div>
                  )}
                  {t.reply.rpc && (
                    <div className="ml-6">
                      <button onClick={() => setShowTrace(showTrace === t.id ? null : t.id)} className="flex items-center gap-1 text-xs text-white/50 hover:text-white">
                        <Braces size={12} /> MCP call: {t.reply.tool}
                      </button>
                      {showTrace === t.id && (
                        <pre className="mt-2 max-h-64 overflow-auto rounded-xl bg-black/40 p-3 text-[11px] leading-relaxed text-sky-100">
                          {JSON.stringify(t.reply.rpc, null, 2)}
                        </pre>
                      )}
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
          <div ref={bottom} />
        </div>
        <form onSubmit={(e) => { e.preventDefault(); ask(text); }} className="flex items-center gap-2 border-t border-white/10 bg-black/20 p-3">
          {canListen && (
            <button type="button" onClick={toggleMic} className={`grid h-11 w-11 shrink-0 place-items-center rounded-full transition ${listening ? "animate-pulse bg-sky-500" : "bg-white/10 hover:bg-white/20"}`} aria-label="Speak">
              {listening ? <MicOff size={18} /> : <Mic size={18} />}
            </button>
          )}
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder={listening ? "Listening…" : "Ask Alexa…"}
            className="h-11 flex-1 rounded-full bg-white/10 px-4 text-sm text-white outline-none placeholder:text-white/40 focus:bg-white/15" />
          <button className="grid h-11 w-11 place-items-center rounded-full bg-sky-500 hover:bg-sky-400 disabled:opacity-50" disabled={busy || !text.trim()} aria-label="Send">
            {busy ? <Loader2 size={18} className="animate-spin" /> : <Send size={18} />}
          </button>
        </form>
      </div>

      <div className="mx-auto flex max-w-4xl flex-wrap justify-center gap-2">
        {SUGGESTIONS.map((s) => (
          <button key={s} onClick={() => ask(s)} disabled={busy} className="chip border border-slate-200 bg-white text-slate-600 hover:border-slate-300 disabled:opacity-50">{s}</button>
        ))}
      </div>
    </div>
  );
}
