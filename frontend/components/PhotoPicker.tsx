"use client";

import { useRef, useState } from "react";
import { ImageUp, Loader2, Search } from "lucide-react";
import { api, type StockPhoto } from "@/lib/api";

export function PhotoPicker({
  defaultQuery,
  onPickStock,
  onPickUpload,
  busy,
  sitePhotos = [],
  onPickSite,
}: {
  defaultQuery: string;
  onPickStock: (p: StockPhoto) => void;
  onPickUpload: (uploadId: string) => void;
  busy: boolean;
  sitePhotos?: { url: string; label: string }[];
  onPickSite?: (url: string) => void;
}) {
  const [q, setQ] = useState(defaultQuery);
  const [results, setResults] = useState<StockPhoto[] | null>(null);
  const [source, setSource] = useState("");
  const [searching, setSearching] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  async function search(e?: React.FormEvent) {
    e?.preventDefault();
    if (q.trim().length < 2) return;
    setSearching(true);
    setError("");
    try {
      const r = await api.searchPhotos(q.trim(), "portrait");
      setResults(r.photos);
      setSource(r.source);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSearching(false);
    }
  }

  async function upload(file: File) {
    setError("");
    try {
      const up = await api.upload(file);
      onPickUpload(up.id);
    } catch (err) {
      setError((err as Error).message);
    }
  }

  return (
    <div className="space-y-2">
      {sitePhotos.length > 0 && onPickSite && (
        <div className="space-y-1.5">
          <p className="text-[11px] font-medium text-slate-500">From your website</p>
          <div className="grid max-h-56 grid-cols-4 gap-1.5 overflow-y-auto pr-1 scrollbar-thin">
            {sitePhotos.map((p) => (
              <button key={p.url} type="button" disabled={busy} onClick={() => onPickSite(p.url)} title={p.label}
                className="group relative aspect-[4/5] overflow-hidden rounded-lg bg-slate-100 ring-brand transition hover:ring-2 disabled:opacity-50">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={p.url} alt={p.label} loading="lazy" className="h-full w-full object-cover transition group-hover:scale-105" />
              </button>
            ))}
          </div>
          <p className="pt-1 text-[11px] font-medium text-slate-500">Or search stock photos</p>
        </div>
      )}
      <div className="flex gap-2">
        <form onSubmit={search} className="relative flex-1">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input className="input pl-8" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search free stock photos" />
        </form>
        <button type="button" className="btn-ghost btn-sm" onClick={() => search()} disabled={searching || busy}>
          {searching ? <Loader2 size={14} className="animate-spin" /> : "Search"}
        </button>
        <button type="button" className="btn-ghost btn-sm" onClick={() => fileRef.current?.click()} disabled={busy} title="Use your own photo">
          <ImageUp size={14} /> Upload
        </button>
        <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" className="hidden"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload(f); e.target.value = ""; }} />
      </div>
      {searching && source !== "pexels" && <p className="text-[11px] text-slate-500">Searching Creative Commons photos (Openverse). This can take up to half a minute; add a free PEXELS_API_KEY for instant results.</p>}
      {error && <p className="text-xs text-red-600">{error}</p>}
      {results && results.length === 0 && <p className="text-xs text-slate-500">No photos found. Try a broader word.</p>}
      {results && results.length > 0 && (
        <>
          <div className="grid max-h-56 grid-cols-4 gap-1.5 overflow-y-auto pr-1 scrollbar-thin">
            {results.map((p) => (
              <button key={p.id} type="button" disabled={busy} onClick={() => onPickStock(p)} title={p.credit}
                className="group relative aspect-[4/5] overflow-hidden rounded-lg bg-slate-100 ring-brand transition hover:ring-2 disabled:opacity-50">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={p.thumb} alt="" loading="lazy" className="h-full w-full object-cover transition group-hover:scale-105" />
              </button>
            ))}
          </div>
          <p className="text-[11px] text-slate-400">
            {source === "pexels" ? "Photos from Pexels, free for commercial use." : "Creative Commons photos via Openverse, filtered to licenses that allow commercial use and edits. Credits are kept with the post and in exports."}
          </p>
        </>
      )}
    </div>
  );
}
