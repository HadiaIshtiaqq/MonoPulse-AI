"use client";

import { useEffect, useState } from "react";
import { KeyRound, Loader2 } from "lucide-react";
import { api, takeOldAccessKey } from "@/lib/api";
import { BrandMark } from "./BrandMark";

/** Shows an unlock screen only when the server has MONOPLUS_ACCESS_KEY set and we don't hold it. */
export function AccessGate({ children }: { children: React.ReactNode }) {
  const [state, setState] = useState<"checking" | "open" | "locked">("checking");
  const [key, setKey] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    (async () => {
      const old = takeOldAccessKey(); // a key an older version left in local storage becomes the cookie
      if (old) await api.login(old).catch(() => false);
      const a = await api.access();
      setState(!a.required || a.ok ? "open" : "locked");
    })().catch(() => setState("open"));
    const onLocked = () => setState("locked");
    window.addEventListener("monoplus:locked", onLocked);
    return () => window.removeEventListener("monoplus:locked", onLocked);
  }, []);

  async function unlock(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (await api.login(key.trim())) {
        setState("open");
        window.location.reload();
      } else {
        setError("That key isn't right.");
      }
    } catch {
      setError("Can't reach the server.");
    } finally {
      setBusy(false);
    }
  }

  if (state === "checking") return <div className="grid min-h-screen place-items-center"><Loader2 className="animate-spin text-slate-400" /></div>;
  if (state === "open") return <>{children}</>;
  return (
    <div className="grid min-h-screen place-items-center bg-[#F7F7FB] p-4">
      <form onSubmit={unlock} className="card w-full max-w-sm animate-scale-in p-6 text-center shadow-pop">
        <span className="relative mx-auto block w-fit animate-pop-in">
          <BrandMark size={52} className="rounded-2xl shadow-glow" />
          <span className="absolute -bottom-1 -right-1 grid h-6 w-6 place-items-center rounded-full bg-white text-brand shadow-lift"><KeyRound size={12} /></span>
        </span>
        <h1 className="mt-4 text-xl font-bold">Unlock MonoPlus</h1>
        <p className="mt-1 text-sm text-slate-500">Enter the access key for this workspace.</p>
        <input autoFocus type="password" className="input mt-5" placeholder="Access key" value={key} onChange={(e) => setKey(e.target.value)} />
        {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
        <button className="btn-primary mt-4 w-full" disabled={busy || !key.trim()}>{busy ? <Loader2 size={14} className="animate-spin" /> : null} Unlock</button>
      </form>
    </div>
  );
}
