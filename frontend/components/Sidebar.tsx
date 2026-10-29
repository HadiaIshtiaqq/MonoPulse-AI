"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { Clapperboard, Cpu, FlaskConical, LayoutGrid, Menu, Plug, Plus, Search, Wand2, X } from "lucide-react";
import { useCommandPalette } from "./CommandPalette";
import { BrandMark } from "./BrandMark";

const NAV = [
  { href: "/campaigns", label: "Campaigns", icon: LayoutGrid, match: (p: string) => p.startsWith("/campaign") },
  { href: "/research", label: "Research", icon: FlaskConical, match: (p: string) => p.startsWith("/research") },
  { href: "/ugc", label: "UGC ads", icon: Clapperboard, match: (p: string) => p.startsWith("/ugc") },
  { href: "/humanizer", label: "Humanizer", icon: Wand2, match: (p: string) => p.startsWith("/humanizer") },
  { href: "/nemotron", label: "Nemotron", icon: Cpu, match: (p: string) => p.startsWith("/nemotron") },
  { href: "/connections", label: "Connections", icon: Plug, match: (p: string) => p.startsWith("/connections") },
];

function Logo() {
  return (
    <Link href="/" className="group flex items-center gap-2.5">
      <BrandMark size={36} className="rounded-xl shadow-glow transition-transform duration-500 group-hover:rotate-[-6deg] group-hover:scale-105" />
      <span className="font-display text-lg font-bold tracking-tight">
        Mono<span className="text-brand">Plus</span>
      </span>
    </Link>
  );
}

function Nav({ pathname }: { pathname: string }) {
  const listRef = useRef<HTMLElement>(null);
  const [pill, setPill] = useState<{ top: number; height: number } | null>(null);
  const active = NAV.findIndex((n) => n.match(pathname));

  // A highlight that slides to the active item instead of jumping.
  useLayoutEffect(() => {
    const el = active >= 0 ? (listRef.current?.children[active + 1] as HTMLElement | undefined) : undefined;
    setPill(el ? { top: el.offsetTop, height: el.offsetHeight } : null);
  }, [active]);

  return (
    <nav ref={listRef} className="relative space-y-1">
      <span aria-hidden className="absolute inset-x-0 rounded-xl bg-brand-soft transition-all duration-500 ease-out"
        style={pill ? { top: pill.top, height: pill.height, opacity: 1 } : { top: 0, height: 0, opacity: 0 }} />
      {NAV.map(({ href, label, icon: Icon }, i) => {
        const on = i === active;
        return (
          <Link key={href} href={href}
            className={`group relative flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition-colors duration-200 ${on ? "font-semibold text-brand-700" : "text-slate-600 hover:bg-slate-100/80 hover:text-ink"}`}>
            <Icon size={18} className={`transition-all duration-300 group-hover:scale-110 ${on ? "text-brand" : "text-slate-400 group-hover:text-slate-600"}`} />
            {label}
            {on && <span className="ml-auto h-1.5 w-1.5 animate-pop-in rounded-full bg-brand" />}
          </Link>
        );
      })}
    </nav>
  );
}

function SearchButton() {
  const openPalette = useCommandPalette();
  return (
    <button onClick={openPalette}
      className="flex w-full items-center gap-2.5 rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-400 transition hover:border-slate-300 hover:text-slate-600 hover:shadow-sm">
      <Search size={15} />
      Search
      <span className="ml-auto flex gap-0.5"><kbd className="kbd">Ctrl</kbd><kbd className="kbd">K</kbd></span>
    </button>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [pathname]);

  const body = (
    <div className="space-y-5">
      <Link href="/" className={`btn-gradient group w-full py-2.5 ${pathname === "/" ? "ring-4 ring-brand-100" : ""}`}>
        <Plus size={16} className="transition-transform duration-300 group-hover:rotate-90" /> New campaign
      </Link>
      <SearchButton />
      <Nav pathname={pathname} />
    </div>
  );

  return (
    <>
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col gap-7 border-r border-slate-200/80 bg-white/80 px-4 py-5 backdrop-blur-xl lg:flex">
        <Logo />
        {body}
        <p className="mt-auto px-1 text-[11px] text-slate-400">Powered by NVIDIA Nemotron on Nebius</p>
      </aside>

      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-200 bg-white/80 px-4 py-3 backdrop-blur-xl lg:hidden">
        <Logo />
        <button onClick={() => setOpen((o) => !o)} className="rounded-lg p-2 transition hover:bg-slate-100" aria-label="Menu" aria-expanded={open}>
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>
      </header>
      {open && <div className="fixed inset-x-0 top-[61px] z-30 animate-slide-down border-b border-slate-200 bg-white p-4 shadow-lift lg:hidden">{body}</div>}
    </>
  );
}
