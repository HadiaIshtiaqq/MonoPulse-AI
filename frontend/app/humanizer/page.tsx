"use client";

import { useState } from "react";
import { ArrowDown, Check, Copy, ExternalLink, Loader2, Wand2, X } from "lucide-react";
import { api, type HumanizeMode, type HumanizeResult } from "@/lib/api";
import { humanPct, tellTone } from "@/components/TellScore";

const SAMPLE =
  "In today's fast-paced digital landscape, it is important to elevate your morning routine. At Bluebird Bakery, we do not just bake bread — we unlock a seamless journey of flavor! Furthermore, our cutting-edge sourdough serves as a testament to our passion. Nestled in the heart of Austin, look no further. Loaves are $6 until Sunday.";

const MODES: { id: HumanizeMode; label: string; desc: string }[] = [
  { id: "light", label: "Light", desc: "Instant rule pass. No model." },
  { id: "standard", label: "Standard", desc: "Rules + Nemotron rewrite guided by the pattern list." },
  { id: "deep", label: "Deep", desc: "Translation chain EN→ZH→JA→EN on Nemotron, then Standard." },
];

export default function HumanizerLab() {
  const [text, setText] = useState(SAMPLE);
  const [mode, setMode] = useState<HumanizeMode>("standard");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<HumanizeResult | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  async function run() {
    setBusy(true);
    setError("");
    try {
      setResult(await api.humanize(text, mode));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Humanizer</h1>
        <p className="mt-1 max-w-3xl text-sm text-slate-600">
          Finds the patterns that make text read as AI-written and removes them without touching your facts. Prices, dates,
          links, @handles and #hashtags are guarded: any step that drops one is rejected.
        </p>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card flex flex-col p-4">
          <div className="mb-2 flex items-center justify-between">
            <p className="label">Your text</p>
            {result && <span className={`chip ${tellTone(result.before)}`}>{humanPct(result.before)}% human-sounding</span>}
          </div>
          <textarea value={text} onChange={(e) => setText(e.target.value)} className="input min-h-[240px] flex-1 resize-none leading-relaxed" />
          <div className="mt-3 grid grid-cols-3 gap-2">
            {MODES.map((m) => (
              <button key={m.id} onClick={() => setMode(m.id)}
                className={`rounded-xl border p-2.5 text-left transition ${mode === m.id ? "border-brand bg-brand-soft" : "border-slate-200 hover:border-slate-300"}`}>
                <p className={`text-sm font-semibold ${mode === m.id ? "text-brand-700" : ""}`}>{m.label}</p>
                <p className="mt-0.5 text-[11px] leading-snug text-slate-500">{m.desc}</p>
              </button>
            ))}
          </div>
          <button onClick={run} disabled={busy || !text.trim()} className="btn-gradient mt-3">
            {busy ? <Loader2 size={16} className="animate-spin" /> : <Wand2 size={16} />} Humanize
          </button>
          {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
        </div>

        <div className="card flex flex-col p-4">
          <div className="mb-2 flex items-center justify-between">
            <p className="label">Result</p>
            {result && <span className={`chip ${tellTone(result.after)}`}>{humanPct(result.after)}% human-sounding</span>}
          </div>
          <div className="min-h-[240px] flex-1 whitespace-pre-wrap rounded-xl bg-slate-50 p-3 text-sm leading-relaxed">
            {result ? result.text : <span className="text-slate-400">Your humanized text appears here.</span>}
          </div>
          {result && (
            <div className="mt-3 flex items-center justify-between">
              <p className="text-xs text-slate-500">{result.used_llm ? "Rules + Nemotron 3 Ultra" : "Rule pass only"}{result.mode === "deep" ? " · translation chain" : ""}</p>
              <button onClick={() => { navigator.clipboard.writeText(result.text); setCopied(true); setTimeout(() => setCopied(false), 1500); }} className="btn-ghost btn-sm">
                {copied ? <Check size={13} /> : <Copy size={13} />} Copy
              </button>
            </div>
          )}
        </div>
      </div>

      {result && (
        <div className="grid gap-4 lg:grid-cols-5">
          <div className="card p-4 lg:col-span-2">
            <p className="font-semibold">Patterns found</p>
            <p className="text-xs text-slate-500">From Wikipedia&apos;s &ldquo;Signs of AI writing&rdquo;, via blader/humanizer.</p>
            {result.patterns_before.length === 0 ? <p className="mt-3 text-sm text-emerald-700">None. This already reads human.</p> : (
              <ul className="mt-3 space-y-2">
                {result.patterns_before.map((p) => {
                  const left = result.patterns_after.find((a) => a.id === p.id);
                  return (
                    <li key={p.id} className="flex items-start gap-2 text-sm">
                      {left ? <X size={15} className="mt-0.5 shrink-0 text-amber-500" /> : <Check size={15} className="mt-0.5 shrink-0 text-emerald-500" />}
                      <span className="min-w-0">
                        <span className={left ? "" : "text-slate-500"}>{p.label}</span>
                        <span className="ml-1 text-xs text-slate-400">×{p.count}{p.example && ` · “${p.example}”`}</span>
                        {left && <span className="block text-xs text-amber-600">{left.count} left</span>}
                      </span>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>
          <div className="card p-4 lg:col-span-3">
            <p className="font-semibold">Pipeline trace</p>
            <ol className="mt-3 space-y-2">
              {result.steps.map((s, i) => (
                <li key={i}>
                  {i > 0 && <ArrowDown size={14} className="mx-auto mb-2 text-slate-300" />}
                  <div className={`rounded-xl border p-3 ${s.accepted ? "border-slate-200" : "border-dashed border-red-200 bg-red-50/40"}`}>
                    <div className="flex items-center justify-between gap-2">
                      <p className="text-sm font-medium">{s.name}</p>
                      <span className="flex items-center gap-1.5 text-xs">
                        {s.note && <span className={s.accepted ? "text-slate-400" : "text-red-600"}>{s.accepted ? s.note : `rejected: ${s.note}`}</span>}
                        {s.note !== "intermediate" && <span className={`chip ${tellTone(s.score)}`}>{humanPct(s.score)}%</span>}
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-xs text-slate-600">{s.text || "(empty)"}</p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}

      <div className="card flex flex-wrap items-center gap-x-6 gap-y-2 p-4 text-xs text-slate-500">
        <span className="font-semibold text-slate-700">Built on open source (MIT):</span>
        <a href="https://github.com/blader/humanizer" target="_blank" rel="noreferrer" className="flex items-center gap-1 hover:text-ink">blader/humanizer: pattern catalogue <ExternalLink size={11} /></a>
        <a href="https://github.com/lynote-ai/humanize-text" target="_blank" rel="noreferrer" className="flex items-center gap-1 hover:text-ink">lynote-ai/humanize-text: translation chain <ExternalLink size={11} /></a>
        <span>“Human-sounding” measures how free the text is of these patterns. It is not a commercial AI-detector score.</span>
      </div>
    </div>
  );
}
