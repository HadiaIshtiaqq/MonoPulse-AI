"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { FlaskConical, LayoutGrid, Menu, Plus, Wand2, X } from "lucide-react";

const NAV = [
  { href: "/campaigns", label: "Campaigns", icon: LayoutGrid, match: (p: string) => p.startsWith("/campaign") },
  { href: "/research", label: "Research", icon: FlaskConical, match: (p: string) => p.startsWith("/research") },
  { href: "/humanizer", label: "Humanizer", icon: Wand2, match: (p: string) => p.startsWith("/humanizer") },
];

function Logo() {
  return (
    <Link href="/" className="flex items-center gap-2.5">
      <span className="grid h-9 w-9 place-items-center rounded-xl bg-brand-gradient text-lg font-bold text-white shadow-lift">M</span>
      <span className="font-display text-lg font-bold tracking-tight">
        Mono<span className="text-brand">Plus</span>
      </span>
    </Link>
  );
}

export function Sidebar() {
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  useEffect(() => setOpen(false), [pathname]);

  const nav = (
    <div className="space-y-5">
      <Link href="/" className={`btn-gradient w-full py-2.5 ${pathname === "/" ? "ring-4 ring-brand-100" : ""}`}>
        <Plus size={16} /> New campaign
      </Link>
      <nav className="space-y-1">
        {NAV.map(({ href, label, icon: Icon, match }) => {
          const active = match(pathname);
          return (
            <Link key={href} href={href}
              className={`flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm transition ${active ? "bg-brand-soft font-semibold text-brand-700" : "text-slate-600 hover:bg-slate-100 hover:text-ink"}`}>
              <Icon size={18} className={active ? "text-brand" : "text-slate-400"} />
              {label}
            </Link>
          );
        })}
      </nav>
    </div>
  );

  return (
    <>
      <aside className="sticky top-0 hidden h-screen w-60 shrink-0 flex-col gap-7 border-r border-slate-200/80 bg-white px-4 py-5 lg:flex">
        <Logo />
        {nav}
      </aside>

      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur lg:hidden">
        <Logo />
        <button onClick={() => setOpen((o) => !o)} className="rounded-lg p-2 hover:bg-slate-100" aria-label="Menu">
          {open ? <X size={20} /> : <Menu size={20} />}
        </button>
      </header>
      {open && <div className="fixed inset-x-0 top-[61px] z-30 border-b border-slate-200 bg-white p-4 shadow-lift lg:hidden">{nav}</div>}
    </>
  );
}
