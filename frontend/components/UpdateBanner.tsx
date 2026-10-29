"use client";

import { useEffect, useState } from "react";
import { RefreshCw } from "lucide-react";

const MINE = process.env.NEXT_PUBLIC_BUILD_ID ?? "";

/** When MonoPlus is updated while a tab is open, the tab still runs the old version. This checks the
 *  server's build every minute (and when the tab comes back into view) and offers a reload. */
export function UpdateBanner() {
  const [stale, setStale] = useState(false);
  useEffect(() => {
    let stop = false;
    async function check() {
      try {
        const r = await fetch("/build-id", { cache: "no-store" });
        const { id } = (await r.json()) as { id: string };
        if (!stop && id && MINE && id !== MINE) setStale(true);
      } catch { /* offline or restarting: try again later */ }
    }
    const timer = setInterval(check, 60_000);
    const onFocus = () => { if (document.visibilityState === "visible") check(); };
    document.addEventListener("visibilitychange", onFocus);
    check();
    return () => { stop = true; clearInterval(timer); document.removeEventListener("visibilitychange", onFocus); };
  }, []);
  if (!stale) return null;
  return (
    <div role="status" className="fixed inset-x-0 top-0 z-[60] flex items-center justify-center gap-3 bg-ink px-4 py-2 text-sm text-white shadow-lg">
      MonoPlus has been updated. Reload to use the new version.
      <button onClick={() => window.location.reload()} className="inline-flex items-center gap-1.5 rounded-lg bg-white px-3 py-1 text-xs font-semibold text-ink">
        <RefreshCw size={13} /> Reload
      </button>
    </div>
  );
}
