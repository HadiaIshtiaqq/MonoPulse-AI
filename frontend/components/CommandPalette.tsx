"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { Clapperboard, CornerDownLeft, FlaskConical, LayoutGrid, Megaphone, Plug, Plus, Search, Cpu } from "lucide-react";
import { api, type CampaignSummary } from "@/lib/api";

type Item = { id: string; label: string; hint?: string; group: string; icon: typeof Search; href: string };

const PAGES: Item[] = [
  { id: "new", label: "New campaign", hint: "Paste a website or handle", group: "Go to", icon: Plus, href: "/" },
  { id: "campaigns", label: "Campaigns", group: "Go to", icon: LayoutGrid, href: "/campaigns" },
  { id: "research", label: "Research", hint: "Competitors, trends, strategy", group: "Go to", icon: FlaskConical, href: "/research" },
  { id: "nemotron", label: "Nemotron", hint: "Live model calls, tiers and the daily cap", group: "Go to", icon: Cpu, href: "/nemotron" },
  { id: "ugc", label: "UGC ads", hint: "Phone-style video ads and AI presenters", group: "Go to", icon: Clapperboard, href: "/ugc" },
  { id: "connections", label: "Connections", hint: "What's connected, and how to set it up in .env", group: "Go to", icon: Plug, href: "/connections" },
];

/** "https://www.brand.com/collections/x?utm=…" -> "brand.com" */
function host(url?: string | null) {
  if (!url) return undefined;
  try { return new URL(url.includes("://") ? url : `https://${url}`).hostname.replace(/^www\./, ""); } catch { return url; }
}

const Ctx = createContext<() => void>(() => {});
/** Opens the ⌘K / Ctrl+K palette. */
export const useCommandPalette = () => useContext(Ctx);

export function CommandPaletteProvider({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const show = useCallback(() => setOpen(true), []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <Ctx.Provider value={show}>
      {children}
      {open && <Palette onClose={() => setOpen(false)} />}
    </Ctx.Provider>
  );
}

function Palette({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const pathname = usePathname();
  const [q, setQ] = useState("");
  const [active, setActive] = useState(0);
  const [campaigns, setCampaigns] = useState<CampaignSummary[]>([]);
  const listRef = useRef<HTMLDivElement>(null);
  const opened = useRef(pathname);

  useEffect(() => { api.campaigns().then(setCampaigns).catch(() => {}); }, []);
  useEffect(() => { if (pathname !== opened.current) onClose(); }, [pathname, onClose]);

  const items = useMemo(() => {
    const all: Item[] = [
      ...PAGES,
      ...campaigns.map((c) => ({
        id: c.id, label: c.name, hint: host(c.website), group: "Campaigns", icon: Megaphone, href: `/campaign/${c.id}`,
      })),
    ];
    const words = q.toLowerCase().split(/\s+/).filter(Boolean);
    const hits = all.filter((i) => words.every((w) => `${i.label} ${i.hint ?? ""}`.toLowerCase().includes(w)));
    if (q) return hits;
    const recent = new Set(campaigns.slice(0, 6).map((c) => c.id));
    return hits.filter((i) => i.group !== "Campaigns" || recent.has(i.id));
  }, [q, campaigns]);

  useEffect(() => setActive(0), [q]);
  useEffect(() => {
    listRef.current?.querySelector(`[data-index="${active}"]`)?.scrollIntoView({ block: "nearest" });
  }, [active]);

  function go(i: Item | undefined) {
    if (!i) return;
    onClose();
    router.push(i.href);
  }

  function onKey(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive((a) => Math.min(a + 1, items.length - 1)); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive((a) => Math.max(a - 1, 0)); }
    else if (e.key === "Enter") { e.preventDefault(); go(items[active]); }
    else if (e.key === "Escape") onClose();
  }

  let group = "";
  return (
    <div className="fixed inset-0 z-[60] animate-fade-in bg-ink/40 p-4 pt-[12vh] backdrop-blur-sm" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Command palette" onClick={(e) => e.stopPropagation()}
        className="mx-auto w-full max-w-lg animate-scale-in overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-pop">
        <label className="flex items-center gap-3 border-b border-slate-100 px-4">
          <Search size={18} className="text-slate-400" />
          <input autoFocus value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey}
            placeholder="Jump to a campaign or page…" aria-label="Search"
            className="h-14 flex-1 bg-transparent text-[15px] outline-none placeholder:text-slate-400" />
          <kbd className="kbd">Esc</kbd>
        </label>
        <div ref={listRef} className="max-h-[50vh] overflow-y-auto p-2" role="listbox">
          {items.length === 0 && <p className="px-3 py-8 text-center text-sm text-slate-500">Nothing matches &ldquo;{q}&rdquo;</p>}
          {items.map((it, i) => {
            const heading = it.group !== group ? (group = it.group) : null;
            const Icon = it.icon;
            const on = i === active;
            return (
              <div key={`${it.group}-${it.id}`}>
                {heading && <p className="label px-3 pb-1 pt-3">{heading}</p>}
                <button data-index={i} role="option" aria-selected={on} onMouseMove={() => setActive(i)} onClick={() => go(it)}
                  className={`flex w-full items-center gap-3 rounded-xl px-3 py-2.5 text-left text-sm transition-colors ${on ? "bg-brand-soft text-brand-700" : "text-slate-700"}`}>
                  <Icon size={16} className={on ? "text-brand" : "text-slate-400"} />
                  <span className="min-w-0 shrink-0 truncate font-medium" style={{ maxWidth: "70%" }}>{it.label}</span>
                  {it.hint && <span className="ml-auto truncate pl-3 text-xs text-slate-400">{it.hint}</span>}
                  {on && <CornerDownLeft size={14} className={`shrink-0 text-brand ${it.hint ? "" : "ml-auto"}`} />}
                </button>
              </div>
            );
          })}
        </div>
        <div className="flex items-center gap-4 border-t border-slate-100 bg-slate-50/80 px-4 py-2 text-[11px] text-slate-500">
          <span><kbd className="kbd">↑</kbd> <kbd className="kbd">↓</kbd> move</span>
          <span><kbd className="kbd">↵</kbd> open</span>
          <span className="ml-auto"><kbd className="kbd">Ctrl</kbd> <kbd className="kbd">K</kbd> toggle</span>
        </div>
      </div>
    </div>
  );
}
