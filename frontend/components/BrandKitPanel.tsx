"use client";

import { useEffect, useRef, useState } from "react";
import { ImageUp, Loader2, RefreshCw, Trash2 } from "lucide-react";
import { api, media, type BrandKit, type Campaign } from "@/lib/api";

type Form = Pick<BrandKit, "name" | "tagline" | "primary_color" | "secondary_color" | "accent_color" | "brand_voice_prompt">;

function pick(b: BrandKit): Form {
  return { name: b.name, tagline: b.tagline, primary_color: b.primary_color, secondary_color: b.secondary_color, accent_color: b.accent_color, brand_voice_prompt: b.brand_voice_prompt };
}

function ColorField({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  return (
    <label className="flex items-center gap-3 rounded-xl border border-slate-200 p-2.5">
      <input type="color" value={value} onChange={(e) => onChange(e.target.value.toUpperCase())} className="h-10 w-10 cursor-pointer rounded-lg border-0 bg-transparent p-0" />
      <span className="min-w-0">
        <span className="label block">{label}</span>
        <input value={value} onChange={(e) => onChange(e.target.value)} className="w-24 bg-transparent font-mono text-sm outline-none" maxLength={7} />
      </span>
    </label>
  );
}

export function BrandKitPanel({ campaign, onSaved }: { campaign: Campaign; onSaved: (c: Campaign) => void }) {
  const brand = campaign.brand!;
  const [form, setForm] = useState<Form>(pick(brand));
  const [busy, setBusy] = useState<string | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => setForm(pick(brand)), [brand]);

  const dirty = JSON.stringify(form) !== JSON.stringify(pick(brand));
  const validHex = (v: string) => /^#[0-9A-Fa-f]{6}$/.test(v);
  const valid = validHex(form.primary_color) && validHex(form.secondary_color) && validHex(form.accent_color) && form.name.trim().length > 0;

  async function save(extra: Parameters<typeof api.updateBrand>[1] = {}, key = "save") {
    setBusy(key);
    setMsg(null);
    try {
      const c = await api.updateBrand(campaign.id, { ...form, ...extra });
      onSaved(c);
      setMsg({ ok: true, text: `${key === "rerender" ? "Done" : "Saved"}. All ${c.posts.length} posts were re-rendered with your brand kit.` });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(null);
    }
  }

  async function uploadLogo(file: File) {
    setBusy("logo");
    try {
      const up = await api.upload(file);
      await save({ logo_upload_id: up.id }, "logo");
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
      setBusy(null);
    }
  }

  const logoSrc = brand.logo_url ? (brand.logo_url.startsWith("/") ? media(brand.logo_url) : brand.logo_url) : null;

  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <div className="card space-y-4 p-5 lg:col-span-2">
        <div>
          <h2 className="text-lg font-bold">Brand kit</h2>
          <p className="text-sm text-slate-500">Extracted from {brand.website_url ? <a href={brand.website_url} className="underline" target="_blank" rel="noreferrer">your site</a> : "your handle"}. Fix anything here and every post updates.</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <label className="block text-sm"><span className="label">Brand name</span>
            <input className="input mt-1" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} maxLength={80} />
          </label>
          <label className="block text-sm"><span className="label">Tagline</span>
            <input className="input mt-1" value={form.tagline} onChange={(e) => setForm({ ...form, tagline: e.target.value })} maxLength={140} />
          </label>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <ColorField label="Primary" value={form.primary_color} onChange={(v) => setForm({ ...form, primary_color: v })} />
          <ColorField label="Dark / text" value={form.secondary_color} onChange={(v) => setForm({ ...form, secondary_color: v })} />
          <ColorField label="Accent" value={form.accent_color} onChange={(v) => setForm({ ...form, accent_color: v })} />
        </div>
        {brand.palette.length > 0 && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
            Found on your site:
            {brand.palette.map((c) => (
              <button key={c} onClick={() => setForm({ ...form, primary_color: c })} title={`Use ${c} as primary`} className="h-6 w-6 rounded-md border border-black/10" style={{ background: c }} />
            ))}
          </div>
        )}
        <label className="block text-sm"><span className="label">Brand voice</span>
          <textarea className="input mt-1 min-h-[90px]" value={form.brand_voice_prompt} onChange={(e) => setForm({ ...form, brand_voice_prompt: e.target.value })} maxLength={600}
            placeholder="How does this brand talk? e.g. warm, a little cheeky, never corporate." />
          <span className="text-xs text-slate-400">Used by the copywriter and the humanizer for every caption.</span>
        </label>
        {msg && <p className={`rounded-xl px-3 py-2 text-sm ${msg.ok ? "bg-emerald-50 text-emerald-800" : "bg-red-50 text-red-700"}`}>{msg.text}</p>}
        {!valid && <p className="text-xs text-red-600">Colours must be 6-digit hex codes like #2563EB, and the brand needs a name.</p>}
        <div className="flex flex-wrap items-center gap-3">
          <button className="btn-primary" disabled={!valid || busy !== null} onClick={() => save({}, dirty ? "save" : "rerender")}>
            {busy === "save" || busy === "rerender" ? <Loader2 size={14} className="animate-spin" /> : <RefreshCw size={14} />}
            {dirty ? "Save & re-render posts" : "Re-render all posts"}
          </button>
          {dirty && (
            <button className="btn-ghost" disabled={busy !== null} onClick={() => setForm(pick(brand))}>Discard changes</button>
          )}
          {(busy === "save" || busy === "rerender") && <span className="text-xs text-slate-500">Redrawing every post with your brand…</span>}
        </div>
      </div>

      <div className="space-y-4">
        <div className="card p-5">
          <p className="label mb-3">Logo</p>
          <div className="grid h-32 place-items-center rounded-xl border border-dashed border-slate-300 bg-slate-50">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            {logoSrc ? <img src={logoSrc} alt="Logo" className="max-h-24 max-w-[80%] object-contain" /> : <span className="text-sm text-slate-400">No logo</span>}
          </div>
          <div className="mt-3 flex gap-2">
            <button className="btn-ghost btn-sm flex-1" onClick={() => fileRef.current?.click()} disabled={busy !== null}>
              {busy === "logo" ? <Loader2 size={14} className="animate-spin" /> : <ImageUp size={14} />} Upload logo
            </button>
            {brand.logo_url && (
              <button className="btn-ghost btn-sm" onClick={() => save({ remove_logo: true }, "logo")} disabled={busy !== null} aria-label="Remove logo"><Trash2 size={14} /></button>
            )}
          </div>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
            onChange={(e) => { const f = e.target.files?.[0]; if (f) uploadLogo(f); e.target.value = ""; }} />
          <p className="mt-2 text-xs text-slate-400">A PNG with a transparent background works best.</p>
        </div>
        <div className="card overflow-hidden">
          <div className="h-24" style={{ background: `linear-gradient(135deg, ${form.primary_color}, ${form.accent_color})` }} />
          <div className="p-4" style={{ color: form.secondary_color }}>
            <p className="font-display text-lg font-bold">{form.name || "Brand name"}</p>
            <p className="text-sm opacity-80">{form.tagline || "Your tagline"}</p>
          </div>
        </div>
      </div>
    </div>
  );
}
