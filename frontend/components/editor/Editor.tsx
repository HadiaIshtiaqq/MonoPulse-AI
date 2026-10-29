"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlignCenter, AlignCenterHorizontal, AlignCenterVertical, AlignEndHorizontal, AlignEndVertical, AlignLeft, AlignRight, AlignStartHorizontal,
  AlignStartVertical, ArrowDown, ArrowLeft, ArrowUp, Bold, Circle as CircleIcon, Copy, Download, Eye, EyeOff, FlipHorizontal, ImagePlus, Italic,
  Layers, LayoutTemplate, Loader2, Lock, Minus, Palette, Plus, Redo2, RotateCcw, Save, Search, Shapes, Square, Star as StarIcon, Trash2,
  Triangle, Type, Underline, Undo2, Unlock, Upload,
} from "lucide-react";
import { api, logoSrc, media, type BrandKit, type SocialPost, type StockPhoto } from "@/lib/api";
import {
  FONT_LINKS, FONTS, TEMPLATES, designFromImages, designFromPost, image, inkOn, shape, sizeFor, text, uid,
  type Design, type El, type ImageEl, type Page, type ShapeEl, type ShapeKind, type TextEl,
} from "@/lib/design";
import { useFeedback } from "@/components/Feedback";
import type { CanvasHandle } from "./Canvas";

const Canvas = dynamic(() => import("./Canvas").then((m) => m.Canvas), { ssr: false, loading: () => <Loader2 className="animate-spin text-slate-400" /> });

type Tab = "templates" | "text" | "photos" | "elements" | "brand" | "layers";
const TABS: { key: Tab; label: string; icon: typeof Type }[] = [
  { key: "templates", label: "Templates", icon: LayoutTemplate }, { key: "text", label: "Text", icon: Type },
  { key: "photos", label: "Photos", icon: ImagePlus }, { key: "elements", label: "Elements", icon: Shapes },
  { key: "brand", label: "Brand", icon: Palette }, { key: "layers", label: "Layers", icon: Layers },
];
const HISTORY = 100;

export function Editor({ post, brand, campaignId, onSaved }: { post: SocialPost; brand: BrandKit | null; campaignId: string; onSaved: (p: SocialPost) => void }) {
  const { toast, confirm } = useFeedback();
  const logo = logoSrc(brand);
  const logoRef = logo && logo.includes("/media/") ? logo.slice(logo.indexOf("/media/")).split("?")[0] : logo;
  const [design, setDesign] = useState<Design>(() => (post.design as Design | null) ?? designFromPost(post, brand, logoRef));
  const [past, setPast] = useState<Design[]>([]);
  const [future, setFuture] = useState<Design[]>([]);
  const [pageIndex, setPageIndex] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("templates");
  const [editing, setEditing] = useState<TextEl | null>(null);
  const [busy, setBusy] = useState<"save" | "download" | null>(null);
  const [dirty, setDirty] = useState(false);
  const [zoom, setZoom] = useState<number | null>(null); // null = fit
  const canvasRef = useRef<CanvasHandle>(null);
  const areaRef = useRef<HTMLDivElement>(null);
  const [area, setArea] = useState({ w: 800, h: 600 });
  const lastPush = useRef<{ key: string; at: number }>({ key: "", at: 0 });

  const page = design.pages[Math.min(pageIndex, design.pages.length - 1)];
  const selected = page.elements.find((e) => e.id === selectedId) ?? null;
  const fit = Math.min((area.w - 64) / design.width, (area.h - 64) / design.height);
  const scale = Math.max(0.05, zoom ?? fit);

  // Fonts for the editor, loaded once.
  useEffect(() => {
    for (const href of FONT_LINKS) {
      if (document.querySelector(`link[href="${href}"]`)) continue;
      const l = document.createElement("link");
      l.rel = "stylesheet"; l.href = href;
      document.head.appendChild(l);
    }
  }, []);
  useEffect(() => {
    const el = areaRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setArea({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    const warn = (e: BeforeUnloadEvent) => { if (dirty) { e.preventDefault(); e.returnValue = ""; } };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  /** Change the design. Rapid changes to the same thing (a slider) become one undo step. */
  const update = useCallback((fn: (d: Design) => Design, key = "") => {
    setDesign((d) => {
      const now = Date.now();
      const merge = key && lastPush.current.key === key && now - lastPush.current.at < 700;
      lastPush.current = { key, at: now };
      if (!merge) setPast((p) => [...p.slice(-HISTORY + 1), d]);
      setFuture([]);
      return fn(d);
    });
    setDirty(true);
  }, []);
  const updatePage = useCallback((fn: (p: Page) => Page, key = "") =>
    update((d) => ({ ...d, pages: d.pages.map((p, i) => (i === Math.min(pageIndex, d.pages.length - 1) ? fn(p) : p)) }), key), [update, pageIndex]);
  const updateEl = useCallback((id: string, patch: Partial<El>, key = "") =>
    updatePage((p) => ({ ...p, elements: p.elements.map((e) => (e.id === id ? ({ ...e, ...patch } as El) : e)) }), key ? `${id}:${key}` : ""), [updatePage]);
  const add = useCallback((el: El) => {
    updatePage((p) => ({ ...p, elements: [...p.elements, el] }));
    setSelectedId(el.id);
  }, [updatePage]);

  function undo() {
    setPast((p) => {
      if (!p.length) return p;
      setFuture((f) => [design, ...f].slice(0, HISTORY));
      setDesign(p[p.length - 1]);
      return p.slice(0, -1);
    });
  }
  function redo() {
    setFuture((f) => {
      if (!f.length) return f;
      setPast((p) => [...p, design].slice(-HISTORY));
      setDesign(f[0]);
      return f.slice(1);
    });
  }
  function remove(id: string | null = selectedId) {
    if (!id) return;
    updatePage((p) => ({ ...p, elements: p.elements.filter((e) => e.id !== id) }));
    setSelectedId(null);
  }
  function duplicate() {
    if (!selected) return;
    const copy = { ...selected, id: uid(), x: selected.x + 30, y: selected.y + 30 } as El;
    add(copy);
  }
  function arrange(dir: "up" | "down" | "top" | "bottom", id = selectedId) {
    updatePage((p) => {
      const i = p.elements.findIndex((e) => e.id === id);
      if (i < 0) return p;
      const els = [...p.elements];
      const [el] = els.splice(i, 1);
      const to = dir === "top" ? els.length : dir === "bottom" ? 0 : dir === "up" ? Math.min(els.length, i + 1) : Math.max(0, i - 1);
      els.splice(to, 0, el);
      return { ...p, elements: els };
    });
  }
  function align(where: "left" | "hcenter" | "right" | "top" | "vcenter" | "bottom") {
    if (!selected) return;
    const node = canvasRef.current?.stage()?.findOne(`#${selected.id}`);
    const box = node?.getClientRect({ relativeTo: node.getLayer() ?? undefined });
    const w = box?.width ?? selected.width, h = box?.height ?? ("height" in selected ? selected.height : 100);
    const dx = (box?.x ?? selected.x) - selected.x, dy = (box?.y ?? selected.y) - selected.y;
    const patch: Partial<El> =
      where === "left" ? { x: -dx } : where === "hcenter" ? { x: (design.width - w) / 2 - dx } : where === "right" ? { x: design.width - w - dx }
        : where === "top" ? { y: -dy } : where === "vcenter" ? { y: (design.height - h) / 2 - dy } : { y: design.height - h - dy };
    updateEl(selected.id, patch);
  }

  // Keyboard: delete, undo/redo, duplicate, nudge, save.
  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      const typing = (e.target as HTMLElement)?.closest("input, textarea, select, [contenteditable]");
      const mod = e.ctrlKey || e.metaKey;
      if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); save(); return; }
      if (typing) return;
      if (mod && e.key.toLowerCase() === "z") { e.preventDefault(); if (e.shiftKey) redo(); else undo(); }
      else if (mod && e.key.toLowerCase() === "y") { e.preventDefault(); redo(); }
      else if (mod && e.key.toLowerCase() === "d") { e.preventDefault(); duplicate(); }
      else if ((e.key === "Delete" || e.key === "Backspace") && selected && !selected.locked) { e.preventDefault(); remove(); }
      else if (e.key === "Escape") setSelectedId(null);
      else if (selected && !selected.locked && e.key.startsWith("Arrow")) {
        e.preventDefault();
        const step = e.shiftKey ? 10 : 1;
        const d = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] }[e.key] ?? [0, 0];
        updateEl(selected.id, { x: selected.x + d[0], y: selected.y + d[1] }, "nudge");
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  async function exportPages(): Promise<string[]> {
    const pages: string[] = [];
    const keep = pageIndex;
    setSelectedId(null);
    const { preload } = await import("./Canvas");
    for (let i = 0; i < design.pages.length; i++) {
      await preload(design.pages[i]);
      setPageIndex(i);
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => setTimeout(r, 60))));
      pages.push(canvasRef.current!.exportPng());
    }
    setPageIndex(keep);
    return pages;
  }

  async function save() {
    setBusy("save");
    try {
      const pages = await exportPages();
      const saved = await api.saveDesign(post.id, design, pages);
      onSaved(saved);
      setDirty(false);
      toast(pages.length > 1 ? `Saved: ${pages.length} pages are now this post's images` : "Saved: this is now the post's image", "success");
    } catch (e) {
      const msg = (e as Error).message;
      toast(/tainted|insecure/i.test(msg) ? "A picture on this page can't be exported. Replace it with one from the Photos panel." : msg, "error");
    } finally { setBusy(null); }
  }

  async function download() {
    setBusy("download");
    try {
      setSelectedId(null);
      await new Promise((r) => requestAnimationFrame(() => setTimeout(r, 30)));
      const a = document.createElement("a");
      a.href = canvasRef.current!.exportPng();
      a.download = `${(brand?.name || "post").replace(/\W+/g, "-").toLowerCase()}-page-${pageIndex + 1}.png`;
      a.click();
    } finally { setBusy(null); }
  }

  async function resetToAutomatic() {
    if (!(await confirm({ title: "Back to the automatic design?", body: "Your layers on every page are discarded and MonoPlus draws the post again.", confirm: "Reset", danger: true }))) return;
    try {
      const fresh = await api.resetDesign(post.id);
      onSaved(fresh);
      setDesign(designFromPost(fresh, brand, logoRef));
      setPast([]); setFuture([]); setDirty(false);
      toast("Back to the automatic design", "info");
    } catch (e) { toast((e as Error).message, "error"); }
  }

  const textStyleBar = selected?.type === "text" ? selected : null;
  const shapeBar = selected && selected.type !== "text" && selected.type !== "image" ? (selected as ShapeEl) : null;
  const imageBar = selected?.type === "image" ? selected : null;

  return (
    <div className="fixed inset-0 z-50 flex flex-col bg-[#EEF0F5] text-ink">
      {/* Top bar */}
      <header className="flex h-14 shrink-0 items-center gap-2 bg-gradient-to-r from-[#5B47FB] via-[#7C3AED] to-[#C026D3] px-3 text-white">
        <Link href={`/campaign/${campaignId}?post=${post.id}`} onClick={(e) => { if (dirty && !window.confirm("Leave without saving your changes?")) e.preventDefault(); }}
          className="flex items-center gap-1.5 rounded-lg px-2 py-1.5 text-sm font-medium hover:bg-white/15"><ArrowLeft size={16} /> Back</Link>
        <div className="mx-2 h-6 w-px bg-white/25" />
        <button onClick={undo} disabled={!past.length} title="Undo (Ctrl+Z)" className="rounded-lg p-2 hover:bg-white/15 disabled:opacity-40"><Undo2 size={17} /></button>
        <button onClick={redo} disabled={!future.length} title="Redo (Ctrl+Shift+Z)" className="rounded-lg p-2 hover:bg-white/15 disabled:opacity-40"><Redo2 size={17} /></button>
        <p className="ml-2 hidden truncate text-sm text-white/85 md:block">
          {brand?.name} · {post.platform} {post.format === "carousel" ? "carousel" : "post"} · {design.width}×{design.height}
          {dirty ? <span className="ml-2 rounded-full bg-white/20 px-2 py-0.5 text-xs">Unsaved changes</span> : null}
        </p>
        <div className="ml-auto flex items-center gap-1.5">
          {post.design ? (
            <button onClick={resetToAutomatic} className="hidden items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm hover:bg-white/15 sm:flex" title="Discard your design and use MonoPlus's automatic one">
              <RotateCcw size={15} /> Automatic design
            </button>
          ) : null}
          <button onClick={download} disabled={busy !== null} className="flex items-center gap-1.5 rounded-lg bg-white/15 px-3 py-1.5 text-sm font-medium hover:bg-white/25">
            {busy === "download" ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />} <span className="hidden sm:inline">Download</span>
          </button>
          <button onClick={save} disabled={busy !== null} className="flex items-center gap-1.5 rounded-lg bg-white px-3.5 py-1.5 text-sm font-semibold text-[#5B47FB] shadow hover:bg-white/90">
            {busy === "save" ? <Loader2 size={15} className="animate-spin" /> : <Save size={15} />} Save
          </button>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        {/* Icon rail */}
        <nav className="flex w-[72px] shrink-0 flex-col items-center gap-1 border-r border-slate-200 bg-white py-2">
          {TABS.map((t) => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`flex w-16 flex-col items-center gap-1 rounded-xl py-2 text-[11px] font-medium ${tab === t.key ? "bg-brand-soft text-brand" : "text-slate-500 hover:bg-slate-50 hover:text-ink"}`}>
              <t.icon size={20} /> {t.label}
            </button>
          ))}
        </nav>
        {/* Panel */}
        <aside className="w-[300px] shrink-0 overflow-y-auto border-r border-slate-200 bg-white p-4">
          {tab === "templates" && <TemplatesPanel post={post} brand={brand} logo={logoRef} size={[design.width, design.height]}
            onApply={async (p) => {
              if (page.elements.length && !(await confirm({ title: "Replace this page?", body: "The template replaces the layers on this page. You can undo it.", confirm: "Replace" }))) return;
              updatePage(() => ({ ...p, id: page.id })); setSelectedId(null);
            }}
            onUseCurrent={() => { const d = designFromImages(post); if (d.pages[pageIndex]) { updatePage(() => ({ ...d.pages[pageIndex], id: page.id })); } }} />}
          {tab === "text" && <TextPanel w={design.width} brand={brand} onAdd={add} />}
          {tab === "photos" && <PhotosPanel post={post} brand={brand} w={design.width} h={design.height} onAdd={add}
            onBackground={(src) => updatePage((p) => ({ ...p, elements: [image({ src, width: design.width, height: design.height, fit: "cover", name: "Background photo" }), ...p.elements] }))} />}
          {tab === "elements" && <ElementsPanel w={design.width} h={design.height} brand={brand} onAdd={add} />}
          {tab === "brand" && <BrandPanel brand={brand} logo={logoRef} w={design.width} onAdd={add}
            onColour={(c) => (selected ? updateEl(selected.id, selected.type === "text" ? { fill: c } : selected.type === "image" ? {} : { fill: c, gradient: undefined } as Partial<ShapeEl>) : updatePage((p) => ({ ...p, background: c })))} />}
          {tab === "layers" && <LayersPanel page={page} selectedId={selectedId} onSelect={setSelectedId} onArrange={arrange}
            onToggle={(id, k) => { const el = page.elements.find((e) => e.id === id)!; updateEl(id, { [k]: !el[k] } as Partial<El>); }} onRemove={remove} />}
        </aside>

        {/* Workspace */}
        <main className="flex min-w-0 flex-1 flex-col">
          <ContextBar page={page} selected={selected} brand={brand}
            onPageColour={(c) => updatePage((p) => ({ ...p, background: c }), "pagebg")}
            onChange={(patch, key) => selected && updateEl(selected.id, patch, key)}
            onAlign={align} onArrange={(d) => arrange(d)} onDuplicate={duplicate} onRemove={() => remove()}
            textEl={textStyleBar} shapeEl={shapeBar} imageEl={imageBar} />
          <div ref={areaRef} className="relative flex min-h-0 flex-1 items-center justify-center overflow-auto p-8"
            onMouseDown={(e) => { if (e.target === e.currentTarget) setSelectedId(null); }}>
            <div className="relative" style={{ width: design.width * scale, height: design.height * scale }}>
              <Canvas handle={canvasRef} page={page} width={design.width} height={design.height} scale={scale} selectedId={selectedId}
                onSelect={setSelectedId} onChange={(el) => updateEl(el.id, el)} onEditText={(el) => setEditing(el)} />
              {editing && (
                <InlineText el={editing} scale={scale} onDone={(value) => {
                  if (value !== editing.text) updateEl(editing.id, { text: value });
                  setEditing(null);
                }} />
              )}
            </div>
          </div>
          {/* Pages and zoom */}
          <footer className="flex h-14 shrink-0 items-center gap-2 border-t border-slate-200 bg-white px-3">
            <div className="flex min-w-0 flex-1 items-center gap-1.5 overflow-x-auto">
              {design.pages.map((p, i) => (
                <button key={p.id} onClick={() => { setPageIndex(i); setSelectedId(null); }}
                  className={`h-9 shrink-0 rounded-lg border px-3 text-xs font-semibold ${i === pageIndex ? "border-brand bg-brand-soft text-brand" : "border-slate-200 text-slate-600 hover:border-slate-300"}`}>
                  {i === 0 && design.pages.length > 1 ? "Cover" : `Page ${i + 1}`}
                </button>
              ))}
              {post.format === "carousel" && design.pages.length < 10 && (
                <>
                  <button onClick={() => { update((d) => ({ ...d, pages: [...d.pages, { id: uid(), background: brand?.primary_color || "#FFFFFF", elements: [] }] })); setPageIndex(design.pages.length); }}
                    className="flex h-9 shrink-0 items-center gap-1 rounded-lg border border-dashed border-slate-300 px-3 text-xs text-slate-600 hover:border-brand hover:text-brand"><Plus size={13} /> Page</button>
                  <button onClick={() => { update((d) => ({ ...d, pages: [...d.pages.slice(0, pageIndex + 1), { ...page, id: uid(), elements: page.elements.map((e) => ({ ...e, id: uid() })) }, ...d.pages.slice(pageIndex + 1)] })); setPageIndex(pageIndex + 1); }}
                    className="flex h-9 shrink-0 items-center gap-1 rounded-lg px-2 text-xs text-slate-500 hover:text-ink" title="Duplicate page"><Copy size={13} /></button>
                </>
              )}
              {design.pages.length > 1 && (
                <button onClick={() => { update((d) => ({ ...d, pages: d.pages.filter((_, i) => i !== pageIndex) })); setPageIndex(Math.max(0, pageIndex - 1)); }}
                  className="flex h-9 shrink-0 items-center gap-1 rounded-lg px-2 text-xs text-slate-500 hover:text-red-600" title="Delete page"><Trash2 size={13} /></button>
              )}
            </div>
            <div className="flex items-center gap-1 text-xs text-slate-600">
              <button onClick={() => setZoom(Math.max(0.1, scale - 0.1))} className="rounded p-1.5 hover:bg-slate-100"><Minus size={14} /></button>
              <button onClick={() => setZoom(null)} className="w-14 rounded px-1 py-1 text-center font-medium hover:bg-slate-100" title="Fit">{Math.round(scale * 100)}%</button>
              <button onClick={() => setZoom(Math.min(3, scale + 0.1))} className="rounded p-1.5 hover:bg-slate-100"><Plus size={14} /></button>
            </div>
          </footer>
        </main>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ inline text editing */

function InlineText({ el, scale, onDone }: { el: TextEl; scale: number; onDone: (v: string) => void }) {
  const [value, setValue] = useState(el.text);
  const ref = useRef<HTMLTextAreaElement>(null);
  useEffect(() => { ref.current?.focus(); ref.current?.select(); }, []);
  return (
    <textarea ref={ref} value={value} onChange={(e) => setValue(e.target.value)} onBlur={() => onDone(value)}
      onKeyDown={(e) => { if (e.key === "Escape" || (e.key === "Enter" && (e.ctrlKey || e.metaKey))) onDone(value); }}
      style={{
        position: "absolute", left: el.x * scale, top: el.y * scale, width: el.width * scale, minHeight: el.fontSize * el.lineHeight * scale * 1.2,
        fontFamily: el.fontFamily, fontSize: el.fontSize * scale, fontWeight: el.bold ? 700 : 400, fontStyle: el.italic ? "italic" : "normal",
        lineHeight: el.lineHeight, letterSpacing: el.letterSpacing * scale, textAlign: el.align, color: el.fill,
        transform: `rotate(${el.rotation}deg)`, transformOrigin: "top left", background: "rgba(255,255,255,0.08)",
        outline: "2px solid #7C5CFF", border: "none", resize: "none", overflow: "hidden", padding: 0, margin: 0,
        textTransform: el.uppercase ? "uppercase" : "none",
      }} />
  );
}

/* ------------------------------------------------------------------ context toolbar */

function Swatch({ value, onChange, brand, title }: { value: string; onChange: (c: string) => void; brand: BrandKit | null; title: string }) {
  const colours = Array.from(new Set([brand?.primary_color, brand?.secondary_color, brand?.accent_color, "#FFFFFF", "#111111"].filter(Boolean) as string[]));
  return (
    <div className="flex items-center gap-1" title={title}>
      <label className="relative h-7 w-7 cursor-pointer overflow-hidden rounded-md border border-slate-300" style={{ background: value.startsWith("#") ? value : "#ffffff" }}>
        <input type="color" value={/^#[0-9a-f]{6}$/i.test(value) ? value : "#000000"} onChange={(e) => onChange(e.target.value.toUpperCase())} className="absolute inset-0 cursor-pointer opacity-0" />
      </label>
      {colours.map((c) => <button key={c} onClick={() => onChange(c)} className="h-5 w-5 rounded-full border border-slate-200" style={{ background: c }} title={c} />)}
    </div>
  );
}

function Num({ value, onChange, min, max, step = 1, title, suffix = "" }: { value: number; onChange: (v: number) => void; min: number; max: number; step?: number; title: string; suffix?: string }) {
  return (
    <label className="flex items-center gap-1 text-xs text-slate-500" title={title}>
      <span className="hidden xl:inline">{title}</span>
      <input type="number" value={Math.round(value * 100) / 100} min={min} max={max} step={step}
        onChange={(e) => { const v = Number(e.target.value); if (!Number.isNaN(v)) onChange(Math.max(min, Math.min(max, v))); }}
        className="w-16 rounded-md border border-slate-300 px-1.5 py-1 text-xs text-ink" />{suffix}
    </label>
  );
}

function IconBtn({ on, onClick, title, children, danger }: { on?: boolean; onClick: () => void; title: string; children: React.ReactNode; danger?: boolean }) {
  return (
    <button onClick={onClick} title={title}
      className={`rounded-md p-1.5 ${on ? "bg-brand-soft text-brand" : danger ? "text-slate-600 hover:bg-red-50 hover:text-red-600" : "text-slate-600 hover:bg-slate-100 hover:text-ink"}`}>
      {children}
    </button>
  );
}

function ContextBar({ page, selected, brand, onPageColour, onChange, onAlign, onArrange, onDuplicate, onRemove, textEl, shapeEl, imageEl }: {
  page: Page; selected: El | null; brand: BrandKit | null; onPageColour: (c: string) => void; onChange: (p: Partial<El>, key?: string) => void;
  onAlign: (w: "left" | "hcenter" | "right" | "top" | "vcenter" | "bottom") => void; onArrange: (d: "up" | "down" | "top" | "bottom") => void;
  onDuplicate: () => void; onRemove: () => void; textEl: TextEl | null; shapeEl: ShapeEl | null; imageEl: ImageEl | null;
}) {
  if (!selected) {
    return (
      <div className="flex h-12 shrink-0 items-center gap-3 border-b border-slate-200 bg-white px-4 text-sm">
        <span className="text-slate-500">Page colour</span>
        <Swatch value={page.background} onChange={onPageColour} brand={brand} title="Page colour" />
        <span className="ml-auto hidden text-xs text-slate-400 lg:inline">Double-click text to edit · Ctrl+Z undo · Ctrl+D duplicate · arrows nudge</span>
      </div>
    );
  }
  return (
    <div className="flex min-h-12 shrink-0 flex-wrap items-center gap-2 border-b border-slate-200 bg-white px-3 py-1.5 text-sm">
      {textEl && (
        <>
          <select value={textEl.fontFamily} onChange={(e) => onChange({ fontFamily: e.target.value })}
            className="rounded-md border border-slate-300 px-2 py-1 text-xs" style={{ fontFamily: textEl.fontFamily }}>
            {FONTS.map((f) => <option key={f} value={f} style={{ fontFamily: f }}>{f}</option>)}
          </select>
          <Num value={textEl.fontSize} min={8} max={600} title="Size" onChange={(v) => onChange({ fontSize: v }, "size")} />
          <Swatch value={textEl.fill} onChange={(c) => onChange({ fill: c }, "fill")} brand={brand} title="Text colour" />
          <IconBtn on={textEl.bold} onClick={() => onChange({ bold: !textEl.bold })} title="Bold"><Bold size={15} /></IconBtn>
          <IconBtn on={textEl.italic} onClick={() => onChange({ italic: !textEl.italic })} title="Italic"><Italic size={15} /></IconBtn>
          <IconBtn on={textEl.underline} onClick={() => onChange({ underline: !textEl.underline })} title="Underline"><Underline size={15} /></IconBtn>
          <IconBtn on={textEl.uppercase} onClick={() => onChange({ uppercase: !textEl.uppercase })} title="Capitals"><span className="text-[11px] font-bold">aA</span></IconBtn>
          {(["left", "center", "right"] as const).map((a) => (
            <IconBtn key={a} on={textEl.align === a} onClick={() => onChange({ align: a })} title={`Align ${a}`}>
              {a === "left" ? <AlignLeft size={15} /> : a === "center" ? <AlignCenter size={15} /> : <AlignRight size={15} />}
            </IconBtn>
          ))}
          <Num value={textEl.lineHeight} min={0.6} max={3} step={0.05} title="Line height" onChange={(v) => onChange({ lineHeight: v }, "lh")} />
          <Num value={textEl.letterSpacing} min={-10} max={60} title="Spacing" onChange={(v) => onChange({ letterSpacing: v }, "ls")} />
          <label className="flex items-center gap-1 text-xs text-slate-500" title="Highlight behind the text">
            <input type="checkbox" checked={!!textEl.highlight} onChange={(e) => onChange({ highlight: e.target.checked ? brand?.accent_color || "#FFE066" : undefined })} />
            Highlight
          </label>
          {textEl.highlight && <Swatch value={textEl.highlight} onChange={(c) => onChange({ highlight: c }, "hl")} brand={brand} title="Highlight colour" />}
          <label className="flex items-center gap-1 text-xs text-slate-500"><input type="checkbox" checked={!!textEl.shadow} onChange={(e) => onChange({ shadow: e.target.checked })} /> Shadow</label>
        </>
      )}
      {shapeEl && (
        <>
          <Swatch value={shapeEl.type === "line" ? shapeEl.stroke || shapeEl.fill : shapeEl.fill}
            onChange={(c) => onChange(shapeEl.type === "line" ? { stroke: c } : { fill: c, gradient: undefined }, "fill")} brand={brand} title="Colour" />
          {shapeEl.type !== "line" && (
            <>
              <span className="text-xs text-slate-500">Border</span>
              <Swatch value={shapeEl.stroke || "#111111"} onChange={(c) => onChange({ stroke: c, strokeWidth: shapeEl.strokeWidth || 4 }, "stroke")} brand={brand} title="Border colour" />
            </>
          )}
          <Num value={shapeEl.strokeWidth} min={0} max={80} title={shapeEl.type === "line" ? "Thickness" : "Border"} onChange={(v) => onChange({ strokeWidth: v }, "sw")} />
          {shapeEl.type === "rect" && <Num value={shapeEl.cornerRadius} min={0} max={1000} title="Corners" onChange={(v) => onChange({ cornerRadius: v }, "cr")} />}
        </>
      )}
      {imageEl && (
        <>
          <Num value={imageEl.cornerRadius} min={0} max={1000} title="Corners" onChange={(v) => onChange({ cornerRadius: v }, "cr")} />
          <IconBtn on={!!imageEl.flipX} onClick={() => onChange({ flipX: !imageEl.flipX })} title="Flip"><FlipHorizontal size={15} /></IconBtn>
          <select value={imageEl.fit ?? "cover"} onChange={(e) => onChange({ fit: e.target.value as ImageEl["fit"] })} className="rounded-md border border-slate-300 px-2 py-1 text-xs">
            <option value="cover">Fill the frame</option><option value="contain">Fit inside</option>
          </select>
        </>
      )}
      <div className="mx-1 h-6 w-px bg-slate-200" />
      <label className="flex items-center gap-1 text-xs text-slate-500" title="Transparency">
        <span className="hidden xl:inline">Opacity</span>
        <input type="range" min={0.05} max={1} step={0.05} value={selected.opacity} onChange={(e) => onChange({ opacity: Number(e.target.value) }, "opacity")} className="w-20 accent-brand" />
      </label>
      <IconBtn onClick={() => onAlign("left")} title="Align to left edge"><AlignStartVertical size={15} /></IconBtn>
      <IconBtn onClick={() => onAlign("hcenter")} title="Centre horizontally"><AlignCenterVertical size={15} /></IconBtn>
      <IconBtn onClick={() => onAlign("right")} title="Align to right edge"><AlignEndVertical size={15} /></IconBtn>
      <IconBtn onClick={() => onAlign("top")} title="Align to top"><AlignStartHorizontal size={15} /></IconBtn>
      <IconBtn onClick={() => onAlign("vcenter")} title="Centre vertically"><AlignCenterHorizontal size={15} /></IconBtn>
      <IconBtn onClick={() => onAlign("bottom")} title="Align to bottom"><AlignEndHorizontal size={15} /></IconBtn>
      <IconBtn onClick={() => onArrange("up")} title="Bring forward"><ArrowUp size={15} /></IconBtn>
      <IconBtn onClick={() => onArrange("down")} title="Send backward"><ArrowDown size={15} /></IconBtn>
      <IconBtn onClick={() => onChange({ locked: !selected.locked })} on={selected.locked} title={selected.locked ? "Unlock" : "Lock"}>{selected.locked ? <Lock size={15} /> : <Unlock size={15} />}</IconBtn>
      <IconBtn onClick={onDuplicate} title="Duplicate (Ctrl+D)"><Copy size={15} /></IconBtn>
      <IconBtn onClick={onRemove} title="Delete" danger><Trash2 size={15} /></IconBtn>
    </div>
  );
}

/* ------------------------------------------------------------------ panels */

function PanelTitle({ children }: { children: React.ReactNode }) {
  return <p className="mb-2 mt-4 text-xs font-semibold uppercase tracking-wide text-slate-500 first:mt-0">{children}</p>;
}

function TemplatesPanel({ post, brand, logo, size, onApply, onUseCurrent }: {
  post: SocialPost; brand: BrandKit | null; logo: string | null; size: [number, number]; onApply: (p: Page) => void; onUseCurrent: () => void;
}) {
  const hasPhoto = !!post.background?.thumb_url;
  const ctx = { post, brand, logo, w: size[0], h: size[1] };
  return (
    <div>
      <PanelTitle>Start this page from</PanelTitle>
      <div className="grid grid-cols-2 gap-2">
        {TEMPLATES.filter((t) => !t.needsPhoto || hasPhoto).map((t) => {
          const p = t.build(ctx, post.headline, post.cta);
          return (
            <button key={t.key} onClick={() => onApply(p)} className="group overflow-hidden rounded-xl border border-slate-200 text-left hover:border-brand">
              <MiniPreview page={p} w={size[0]} h={size[1]} />
              <p className="px-2 py-1.5 text-[11px] font-medium text-slate-600 group-hover:text-brand">{t.label}</p>
            </button>
          );
        })}
      </div>
      <button onClick={onUseCurrent} className="btn-ghost btn-sm mt-3 w-full">Edit on top of the current image</button>
      <p className="mt-2 text-[11px] leading-relaxed text-slate-500">Templates use this post&apos;s headline, photo, logo and brand colours. Every part stays editable.</p>
    </div>
  );
}

/** A quick drawing of a page's layout (blocks, not pixels) for the template list. */
function MiniPreview({ page, w, h }: { page: Page; w: number; h: number }) {
  const k = 130 / w;
  return (
    <div className="relative overflow-hidden" style={{ width: "100%", aspectRatio: `${w} / ${h}`, background: page.background }}>
      {page.elements.map((e) => {
        const style: React.CSSProperties = { position: "absolute", left: `${(e.x / w) * 100}%`, top: `${(e.y / h) * 100}%`, width: `${(e.width / w) * 100}%`, opacity: e.opacity };
        if (e.type === "text") return <div key={e.id} style={{ ...style, color: e.fill, fontFamily: e.fontFamily, fontWeight: e.bold ? 700 : 400, fontSize: Math.max(5, e.fontSize * k), lineHeight: 1.05, textAlign: e.align, overflow: "hidden", maxHeight: "40%" }}>{e.text}</div>;
        if (e.type === "image") return <div key={e.id} style={{ ...style, height: `${(e.height / h) * 100}%`, background: "#CBD5E1", borderRadius: e.cornerRadius * k }} />;
        return <div key={e.id} style={{ ...style, height: `${(Math.max(2, e.height) / h) * 100}%`, background: e.gradient ? `linear-gradient(${e.gradient.from}, ${e.gradient.to})` : e.fill, borderRadius: e.type === "circle" ? "50%" : e.cornerRadius * k }} />;
      })}
    </div>
  );
}

function TextPanel({ w, brand, onAdd }: { w: number; brand: BrandKit | null; onAdd: (e: El) => void }) {
  const ink = "#111111", s = w;
  const presets: { label: string; make: () => TextEl; style: React.CSSProperties }[] = [
    { label: "Add a heading", make: () => text({ text: "Add a heading", fontFamily: "Poppins", bold: true, fontSize: s * 0.08, width: s * 0.8, x: s * 0.1, y: s * 0.2, fill: ink }), style: { fontSize: 22, fontWeight: 700 } },
    { label: "Add a subheading", make: () => text({ text: "Add a subheading", fontFamily: "Poppins", fontSize: s * 0.045, width: s * 0.8, x: s * 0.1, y: s * 0.35, fill: ink }), style: { fontSize: 16, fontWeight: 600 } },
    { label: "Add body text", make: () => text({ text: "Add a little bit of body text", fontSize: s * 0.03, width: s * 0.7, x: s * 0.1, y: s * 0.45, fill: ink }), style: { fontSize: 13 } },
  ];
  const combos: { label: string; make: () => TextEl }[] = [
    { label: "BIG SALE", make: () => text({ text: "BIG SALE", fontFamily: "Bebas Neue", fontSize: s * 0.16, width: s * 0.8, x: s * 0.1, y: s * 0.3, fill: brand?.primary_color || ink, align: "center" }) },
    { label: "New arrival", make: () => text({ text: "New arrival", fontFamily: "Playfair Display", italic: true, fontSize: s * 0.08, width: s * 0.8, x: s * 0.1, y: s * 0.3, fill: ink, align: "center" }) },
    { label: "Limited time", make: () => text({ text: "LIMITED TIME", fontFamily: "Montserrat", bold: true, letterSpacing: s * 0.01, fontSize: s * 0.04, width: s * 0.8, x: s * 0.1, y: s * 0.3, fill: "#FFFFFF", align: "center", highlight: brand?.accent_color || "#FF5A7A" }) },
    { label: "Thank you", make: () => text({ text: "Thank you", fontFamily: "Dancing Script", fontSize: s * 0.1, width: s * 0.8, x: s * 0.1, y: s * 0.3, fill: ink, align: "center" }) },
    { label: "شکریہ", make: () => text({ text: "شکریہ", fontFamily: "Noto Nastaliq Urdu", fontSize: s * 0.08, width: s * 0.8, x: s * 0.1, y: s * 0.3, fill: ink, align: "center" }) },
  ];
  return (
    <div>
      <PanelTitle>Text</PanelTitle>
      <div className="space-y-2">
        {presets.map((p) => (
          <button key={p.label} onClick={() => onAdd(p.make())} className="w-full rounded-xl border border-slate-200 px-3 py-3 text-left hover:border-brand" style={p.style}>{p.label}</button>
        ))}
      </div>
      <PanelTitle>Styles</PanelTitle>
      <div className="grid grid-cols-2 gap-2">
        {combos.map((c) => {
          const el = c.make();
          return (
            <button key={c.label} onClick={() => onAdd(c.make())} className="flex h-16 items-center justify-center rounded-xl border border-slate-200 bg-slate-50 px-1 hover:border-brand"
              style={{ fontFamily: el.fontFamily, fontWeight: el.bold ? 700 : 400, fontStyle: el.italic ? "italic" : "normal", color: el.highlight ? "#fff" : el.fill, fontSize: 16 }}>
              <span style={el.highlight ? { background: el.highlight, padding: "2px 6px", borderRadius: 4 } : undefined}>{c.label}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function PhotosPanel({ post, brand, w, h, onAdd, onBackground }: {
  post: SocialPost; brand: BrandKit | null; w: number; h: number; onAdd: (e: El) => void; onBackground: (src: string) => void;
}) {
  const { toast } = useFeedback();
  const [busy, setBusy] = useState<string | null>(null);
  const [q, setQ] = useState(brand?.industry || "");
  const [stock, setStock] = useState<StockPhoto[] | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const brandPhotos = useMemo(() => Array.from(new Set([
    ...(post.background?.thumb_url ? [post.background.thumb_url] : []),
    ...(brand?.products ?? []).map((p) => p.image_url).filter(Boolean),
    ...(brand?.images ?? []),
  ])).slice(0, 30), [post, brand]);

  async function place(get: () => Promise<string>, key: string, asBackground = false) {
    setBusy(key);
    try {
      const src = await get();
      if (asBackground) onBackground(src);
      else {
        const { loadImage } = await import("./Canvas");
        const img = await loadImage(src).catch(() => null);
        const ratio = img ? img.height / img.width : 1;
        const width = w * 0.6;
        onAdd(image({ src, x: (w - width) / 2, y: (h - width * ratio) / 2, width, height: width * ratio, name: "Photo" }));
      }
    } catch (e) { toast((e as Error).message, "error"); }
    finally { setBusy(null); }
  }
  const local = (url: string) => (url.startsWith("/media/") ? Promise.resolve(url) : api.designPhoto(post.id, { url }).then((r) => r.url));

  return (
    <div>
      <PanelTitle>Upload</PanelTitle>
      <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => {
        const f = e.target.files?.[0];
        if (f) place(() => api.upload(f).then((r) => r.url), "upload");
        e.target.value = "";
      }} />
      <button onClick={() => fileRef.current?.click()} className="btn-primary w-full" disabled={busy !== null}>
        {busy === "upload" ? <Loader2 size={15} className="animate-spin" /> : <Upload size={15} />} Upload a photo
      </button>
      {brandPhotos.length > 0 && (
        <>
          <PanelTitle>{brand?.name}&apos;s photos</PanelTitle>
          <div className="grid grid-cols-3 gap-1.5">
            {brandPhotos.map((u) => (
              <div key={u} className="group relative aspect-square overflow-hidden rounded-lg bg-slate-100">
                {/* eslint-disable-next-line @next/next/no-img-element */}
                <img src={u.startsWith("/media/") ? media(u) : u} alt="" loading="lazy" className="h-full w-full object-cover" />
                <div className="absolute inset-0 hidden flex-col justify-end gap-1 bg-black/40 p-1 group-hover:flex">
                  <button onClick={() => place(() => local(u), u)} className="rounded bg-white/95 px-1 py-0.5 text-[10px] font-semibold">Add</button>
                  <button onClick={() => place(() => local(u), u, true)} className="rounded bg-white/95 px-1 py-0.5 text-[10px] font-semibold">Background</button>
                </div>
                {busy === u && <div className="absolute inset-0 grid place-items-center bg-white/60"><Loader2 size={16} className="animate-spin" /></div>}
              </div>
            ))}
          </div>
        </>
      )}
      <PanelTitle>Free stock photos</PanelTitle>
      <form onSubmit={async (e) => { e.preventDefault(); setBusy("search"); try { setStock((await api.searchPhotos(q, w > h ? "landscape" : "portrait")).photos); } catch (err) { toast((err as Error).message, "error"); } finally { setBusy(null); } }}
        className="flex gap-1.5">
        <input className="input" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search photos" />
        <button className="btn-ghost shrink-0 px-3" disabled={busy !== null}>{busy === "search" ? <Loader2 size={14} className="animate-spin" /> : <Search size={14} />}</button>
      </form>
      {stock && (
        <div className="mt-2 grid grid-cols-2 gap-1.5">
          {stock.map((p) => (
            <div key={p.id} className="group relative aspect-square overflow-hidden rounded-lg bg-slate-100">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={p.thumb} alt="" loading="lazy" className="h-full w-full object-cover" />
              <div className="absolute inset-0 hidden flex-col justify-end gap-1 bg-black/40 p-1 group-hover:flex">
                <button onClick={() => place(() => api.designPhoto(post.id, { stock_id: p.id }).then((r) => r.url), p.id)} className="rounded bg-white/95 px-1 py-0.5 text-[10px] font-semibold">Add</button>
                <button onClick={() => place(() => api.designPhoto(post.id, { stock_id: p.id }).then((r) => r.url), p.id, true)} className="rounded bg-white/95 px-1 py-0.5 text-[10px] font-semibold">Background</button>
              </div>
              {busy === p.id && <div className="absolute inset-0 grid place-items-center bg-white/60"><Loader2 size={16} className="animate-spin" /></div>}
            </div>
          ))}
          {stock.length === 0 && <p className="col-span-2 text-xs text-slate-500">No photos found. Try other words.</p>}
        </div>
      )}
    </div>
  );
}

function ElementsPanel({ w, h, brand, onAdd }: { w: number; h: number; brand: BrandKit | null; onAdd: (e: El) => void }) {
  const p = brand?.primary_color || "#6D5DFC", a = brand?.accent_color || "#FF5A7A", s = Math.min(w, h);
  const items: { label: string; icon: React.ReactNode; make: () => El }[] = [
    { label: "Square", icon: <Square size={22} />, make: () => shape("rect", { x: w / 2 - s * 0.15, y: h / 2 - s * 0.15, width: s * 0.3, height: s * 0.3, fill: p }) },
    { label: "Rounded", icon: <Square size={22} className="rounded-md" />, make: () => shape("rect", { x: w / 2 - s * 0.15, y: h / 2 - s * 0.1, width: s * 0.3, height: s * 0.2, fill: p, cornerRadius: s * 0.03 }) },
    { label: "Circle", icon: <CircleIcon size={22} />, make: () => shape("circle", { x: w / 2 - s * 0.12, y: h / 2 - s * 0.12, width: s * 0.24, height: s * 0.24, fill: a }) },
    { label: "Triangle", icon: <Triangle size={22} />, make: () => shape("triangle", { x: w / 2 - s * 0.12, y: h / 2 - s * 0.12, width: s * 0.24, height: s * 0.24, fill: p }) },
    { label: "Star", icon: <StarIcon size={22} />, make: () => shape("star", { x: w / 2 - s * 0.12, y: h / 2 - s * 0.12, width: s * 0.24, height: s * 0.24, fill: a }) },
    { label: "Line", icon: <Minus size={22} />, make: () => shape("line", { x: w / 2 - s * 0.2, y: h / 2, width: s * 0.4, stroke: p, strokeWidth: s * 0.008 }) },
  ];
  const badges: { label: string; make: () => El[] }[] = [
    { label: "SALE badge", make: () => { const c = shape("circle", { x: w - s * 0.32, y: s * 0.06, width: s * 0.26, height: s * 0.26, fill: a, name: "Badge" }); return [c, text({ text: "SALE\n20% OFF", x: c.x, y: c.y + s * 0.07, width: c.width, fontFamily: "Bebas Neue", fontSize: s * 0.05, fill: inkOn(a), align: "center", lineHeight: 1, name: "Badge text" })]; } },
    { label: "NEW pill", make: () => [text({ text: "NEW", x: s * 0.06, y: s * 0.06, width: s * 0.18, fontFamily: "Montserrat", bold: true, fontSize: s * 0.035, fill: inkOn(a), align: "center", highlight: a, letterSpacing: s * 0.004, name: "Pill" })] },
    { label: "Shade at the bottom", make: () => [shape("rect", { x: 0, y: h * 0.5, width: w, height: h * 0.5, fill: "#000", gradient: { from: "rgba(0,0,0,0)", to: "rgba(0,0,0,0.75)", angle: 90 }, name: "Shade" })] },
    { label: "Colour band", make: () => [shape("rect", { x: 0, y: h * 0.78, width: w, height: h * 0.22, fill: p, name: "Band" })] },
  ];
  return (
    <div>
      <PanelTitle>Shapes</PanelTitle>
      <div className="grid grid-cols-3 gap-2">
        {items.map((i) => (
          <button key={i.label} onClick={() => onAdd(i.make())} className="flex aspect-square flex-col items-center justify-center gap-1 rounded-xl border border-slate-200 text-[11px] text-slate-600 hover:border-brand hover:text-brand">
            {i.icon}{i.label}
          </button>
        ))}
      </div>
      <PanelTitle>Ready-made</PanelTitle>
      <div className="space-y-2">
        {badges.map((b) => (
          <button key={b.label} onClick={() => b.make().forEach(onAdd)} className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-left text-sm hover:border-brand">{b.label}</button>
        ))}
      </div>
    </div>
  );
}

function BrandPanel({ brand, logo, w, onAdd, onColour }: { brand: BrandKit | null; logo: string | null; w: number; onAdd: (e: El) => void; onColour: (c: string) => void }) {
  const colours = Array.from(new Set([brand?.primary_color, brand?.secondary_color, brand?.accent_color, ...(brand?.palette ?? [])].filter(Boolean) as string[]));
  return (
    <div>
      <PanelTitle>Logo</PanelTitle>
      {logo ? (
        <button onClick={() => onAdd(image({ src: logo, x: w * 0.06, y: w * 0.06, width: w * 0.2, height: w * 0.2, fit: "contain", name: "Logo" }))}
          className="grid h-24 w-full place-items-center rounded-xl border border-slate-200 bg-[repeating-conic-gradient(#f1f5f9_0_25%,#fff_0_50%)] bg-[length:16px_16px] p-3 hover:border-brand">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src={logo.startsWith("/media/") ? media(logo) : logo} alt="Logo" className="max-h-full max-w-full object-contain" />
        </button>
      ) : <p className="text-xs text-slate-500">No logo yet. Add one in the campaign&apos;s Brand kit.</p>}
      <PanelTitle>Brand colours</PanelTitle>
      <p className="mb-2 text-[11px] text-slate-500">Click a colour to apply it to the selected layer, or to the page when nothing is selected.</p>
      <div className="flex flex-wrap gap-2">
        {colours.map((c) => <button key={c} onClick={() => onColour(c)} className="h-10 w-10 rounded-xl border border-slate-200 shadow-sm" style={{ background: c }} title={c} />)}
      </div>
      {brand?.name && (
        <>
          <PanelTitle>Brand name</PanelTitle>
          <button onClick={() => onAdd(text({ text: brand.name, fontFamily: "Montserrat", bold: true, fontSize: w * 0.05, width: w * 0.6, x: w * 0.2, y: w * 0.1, fill: brand.primary_color || "#111", align: "center" }))}
            className="w-full rounded-xl border border-slate-200 px-3 py-2.5 text-left text-sm font-semibold hover:border-brand">{brand.name}</button>
        </>
      )}
    </div>
  );
}

function LayersPanel({ page, selectedId, onSelect, onArrange, onToggle, onRemove }: {
  page: Page; selectedId: string | null; onSelect: (id: string) => void; onArrange: (d: "up" | "down", id: string) => void;
  onToggle: (id: string, k: "hidden" | "locked") => void; onRemove: (id: string) => void;
}) {
  const label = (e: El) => e.name || (e.type === "text" ? e.text.slice(0, 28) || "Text" : e.type === "image" ? "Image" : e.type[0].toUpperCase() + e.type.slice(1));
  return (
    <div>
      <PanelTitle>Layers (top first)</PanelTitle>
      {page.elements.length === 0 && <p className="text-xs text-slate-500">This page is empty. Add text, photos or shapes.</p>}
      <ul className="space-y-1">
        {[...page.elements].reverse().map((e) => (
          <li key={e.id} className={`flex items-center gap-1 rounded-lg border px-2 py-1.5 text-xs ${e.id === selectedId ? "border-brand bg-brand-soft" : "border-slate-200"}`}>
            <button onClick={() => !e.locked && onSelect(e.id)} className={`min-w-0 flex-1 truncate text-left ${e.hidden ? "text-slate-400" : ""}`}>{label(e)}</button>
            <button onClick={() => onArrange("up", e.id)} title="Up" className="rounded p-1 hover:bg-white"><ArrowUp size={12} /></button>
            <button onClick={() => onArrange("down", e.id)} title="Down" className="rounded p-1 hover:bg-white"><ArrowDown size={12} /></button>
            <button onClick={() => onToggle(e.id, "hidden")} title={e.hidden ? "Show" : "Hide"} className="rounded p-1 hover:bg-white">{e.hidden ? <EyeOff size={12} /> : <Eye size={12} />}</button>
            <button onClick={() => onToggle(e.id, "locked")} title={e.locked ? "Unlock" : "Lock"} className="rounded p-1 hover:bg-white">{e.locked ? <Lock size={12} /> : <Unlock size={12} />}</button>
            <button onClick={() => onRemove(e.id)} title="Delete" className="rounded p-1 text-slate-500 hover:bg-white hover:text-red-600"><Trash2 size={12} /></button>
          </li>
        ))}
      </ul>
    </div>
  );
}
