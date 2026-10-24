"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Loader2, Plus, Search } from "lucide-react";
import { api, type CampaignSummary } from "@/lib/api";
import { CampaignCard } from "@/components/CampaignCard";

export default function CampaignsPage() {
  const [list, setList] = useState<CampaignSummary[] | null>(null);
  const [q, setQ] = useState("");
  const [error, setError] = useState("");

  useEffect(() => { api.campaigns().then(setList).catch((e) => setError(e.message)); }, []);

  async function remove(id: string) {
    const c = list?.find((x) => x.id === id);
    if (!confirm(`Delete the ${c?.name ?? ""} campaign and all its posts?`)) return;
    await api.deleteCampaign(id);
    setList((l) => l?.filter((x) => x.id !== id) ?? null);
  }

  const shown = (list ?? []).filter((c) => c.name.toLowerCase().includes(q.toLowerCase()) || (c.website ?? "").includes(q.toLowerCase()));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold">Campaigns</h1>
          <p className="mt-1 text-sm text-slate-500">Every content calendar you&apos;ve generated.</p>
        </div>
        <div className="flex gap-2">
          <label className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input className="input w-56 pl-8" placeholder="Search brands" value={q} onChange={(e) => setQ(e.target.value)} />
          </label>
          <Link href="/" className="btn-primary"><Plus size={16} /> New campaign</Link>
        </div>
      </div>
      {error && <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
      {list === null ? (
        <Loader2 className="animate-spin text-slate-400" />
      ) : shown.length === 0 ? (
        <div className="card p-10 text-center">
          <p className="font-semibold">{list.length ? "No campaigns match that search" : "No campaigns yet"}</p>
          <Link href="/" className="btn-primary mt-4">Create your first campaign</Link>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
          {shown.map((c) => <CampaignCard key={c.id} c={c} onDelete={remove} />)}
        </div>
      )}
    </div>
  );
}
