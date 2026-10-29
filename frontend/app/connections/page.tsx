"use client";

import { useCallback, useEffect, useState } from "react";
import { CheckCircle2, ExternalLink, Instagram, KeyRound, Loader2, Search, ShieldCheck, Sparkles, Unplug } from "lucide-react";
import { api, type Connections } from "@/lib/api";
import { useFeedback } from "@/components/Feedback";

/** Connect services by pasting their keys here, instead of editing a .env file. Keys are checked
 *  with the service, kept on this computer outside the project, and never shown again. */
export default function ConnectionsPage() {
  const [status, setStatus] = useState<Connections | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.connections().then(setStatus).catch((e) => setError((e as Error).message)), []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold">Connections</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-500">
          Connect the official APIs once and MonoPlus posts and researches without browser sign-ins. Keys are checked with each
          service before they&apos;re saved, kept on this computer outside the project folder, and never shown again.
        </p>
      </div>
      {error && <p className="rounded-xl bg-red-50 px-4 py-3 text-sm text-red-700">{error}</p>}
      {!status ? (
        <div className="flex items-center gap-2 text-sm text-slate-500"><Loader2 size={14} className="animate-spin" /> Loading…</div>
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <MetaCard status={status} onChange={setStatus} />
          <div className="space-y-5">
            <KeyCard
              icon={<Sparkles size={16} />} title="AI writing: Nemotron on Nebius" field="nebius_api_key" name="nebius" status={status.nebius}
              onChange={setStatus}
              blurb="Captions, reels and research reports written by NVIDIA Nemotron instead of templates."
              how={<>Create a key in <a className="link" href="https://tokenfactory.nebius.com/" target="_blank" rel="noreferrer">Nebius Token Factory</a> (API keys), then paste it here.</>}
            />
            <KeyCard
              icon={<Search size={16} />} title="Web search: Tavily" field="tavily_api_key" name="tavily" status={status.tavily} onChange={setStatus}
              blurb="Faster, more complete research and trends. Without it MonoPlus uses free sources (news, DuckDuckGo, Wikipedia)."
              how={<>Get a free key (1,000 searches a month) at <a className="link" href="https://app.tavily.com/" target="_blank" rel="noreferrer">tavily.com</a>.</>}
            />
          </div>
        </div>
      )}
      {status && (
        <p className="flex items-start gap-2 text-xs text-slate-500">
          <ShieldCheck size={14} className="mt-0.5 shrink-0 text-emerald-600" />
          Stored in <code className="font-mono">{status.file}</code>. Keys never leave this computer except to the service they belong to,
          and are hidden from logs and error messages. Settings in <code className="font-mono">backend/.env</code> take priority.
        </p>
      )}
    </div>
  );
}

function MetaCard({ status, onChange }: { status: Connections; onChange: (s: Connections) => void }) {
  const { toast, confirm } = useFeedback();
  const [token, setToken] = useState("");
  const [appId, setAppId] = useState("");
  const [secret, setSecret] = useState("");
  const [busy, setBusy] = useState(false);
  const m = status.meta;

  async function connect(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      const res = await api.connectMeta({ token, app_id: appId, app_secret: secret });
      onChange(res);
      setToken(""); setSecret("");
      toast(res.result.note || `Connected: ${res.result.instagram ? `@${res.result.instagram} on Instagram and ` : ""}${res.result.page} on Facebook`,
        res.result.note ? "info" : "success");
    } catch (err) { toast((err as Error).message, "error"); }
    finally { setBusy(false); }
  }

  async function disconnect() {
    if (!(await confirm({ title: "Disconnect Instagram and Facebook?", body: "MonoPlus forgets the token. You can connect again any time.", confirm: "Disconnect", danger: true }))) return;
    onChange(await api.disconnect("meta"));
    toast("Disconnected", "info");
  }

  return (
    <section className="card p-5">
      <div className="flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-gradient-to-br from-fuchsia-500 via-pink-500 to-amber-400 text-white"><Instagram size={18} /></span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">Instagram and Facebook (official)</p>
          <p className="text-xs text-slate-500">Posts and reads profiles through Meta&apos;s Graph API: no browser sign-in, no captchas.</p>
        </div>
        {m.connected && <span className="chip bg-emerald-50 text-emerald-700"><CheckCircle2 size={12} /> Connected</span>}
      </div>

      {m.connected ? (
        <div className="mt-4 space-y-2 text-sm">
          {m.instagram ? <p>Instagram: <b>@{m.instagram}</b></p> : <p className="text-amber-700">No Instagram account is linked to this Facebook Page yet.</p>}
          {m.page && <p>Facebook Page: <b>{m.page}</b></p>}
          {m.from_env ? <p className="text-xs text-slate-500">Set in backend/.env.</p> : (
            <button onClick={disconnect} className="btn-ghost btn-sm mt-1"><Unplug size={14} /> Disconnect</button>
          )}
        </div>
      ) : (
        <>
          <ol className="mt-4 list-decimal space-y-1.5 pl-5 text-xs leading-relaxed text-slate-600">
            <li>Your Instagram must be a <b>Business or Creator</b> account, linked to a <b>Facebook Page</b> you manage (Instagram app → Settings → Account type; then link the Page).</li>
            <li>Create an app at <a className="link" href="https://developers.facebook.com/apps/" target="_blank" rel="noreferrer">developers.facebook.com</a> (type: Business).</li>
            <li>Open the <a className="link" href="https://developers.facebook.com/tools/explorer/" target="_blank" rel="noreferrer">Graph API Explorer <ExternalLink size={10} className="inline" /></a>, pick your app, add the permissions
              <code className="mx-1 font-mono">pages_show_list, pages_manage_posts, pages_read_engagement, instagram_basic, instagram_content_publish, business_management</code>
              and press <b>Generate Access Token</b>.</li>
            <li>Paste the token below. Add the app&apos;s ID and secret (App settings → Basic) so the connection doesn&apos;t expire.</li>
          </ol>
          <form onSubmit={connect} className="mt-4 space-y-2">
            <input className="input" type="password" autoComplete="off" placeholder="Access token" value={token} onChange={(e) => setToken(e.target.value)} />
            <div className="grid grid-cols-2 gap-2">
              <input className="input" autoComplete="off" placeholder="App ID (optional)" value={appId} onChange={(e) => setAppId(e.target.value)} />
              <input className="input" type="password" autoComplete="off" placeholder="App secret (optional)" value={secret} onChange={(e) => setSecret(e.target.value)} />
            </div>
            <button className="btn-primary w-full" disabled={busy || !token.trim()}>
              {busy ? <Loader2 size={15} className="animate-spin" /> : <KeyRound size={15} />} Check and connect
            </button>
          </form>
        </>
      )}
    </section>
  );
}

function KeyCard({ icon, title, blurb, how, field, name, status, onChange }: {
  icon: React.ReactNode; title: string; blurb: string; how: React.ReactNode; field: "nebius_api_key" | "tavily_api_key";
  name: "nebius" | "tavily"; status: { connected: boolean; from_env: boolean }; onChange: (s: Connections) => void;
}) {
  const { toast } = useFeedback();
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);

  async function save(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      onChange(await api.saveKeys({ [field]: key.trim() }));
      setKey("");
      toast(`${title.split(":")[0]} connected`, "success");
    } catch (err) { toast((err as Error).message, "error"); }
    finally { setBusy(false); }
  }

  return (
    <section className="card p-5">
      <div className="flex items-start gap-3">
        <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-brand-soft text-brand">{icon}</span>
        <div className="min-w-0 flex-1">
          <p className="font-semibold">{title}</p>
          <p className="text-xs text-slate-500">{blurb}</p>
        </div>
        {status.connected && <span className="chip bg-emerald-50 text-emerald-700"><CheckCircle2 size={12} /> Connected</span>}
      </div>
      {status.connected ? (
        status.from_env ? <p className="mt-3 text-xs text-slate-500">Set in backend/.env.</p> : (
          <button onClick={async () => { onChange(await api.disconnect(name)); toast("Disconnected", "info"); }} className="btn-ghost btn-sm mt-3">
            <Unplug size={14} /> Disconnect
          </button>
        )
      ) : (
        <form onSubmit={save} className="mt-3 space-y-2">
          <p className="text-xs text-slate-600">{how}</p>
          <div className="flex gap-2">
            <input className="input" type="password" autoComplete="off" placeholder="Paste the key" value={key} onChange={(e) => setKey(e.target.value)} />
            <button className="btn-primary shrink-0" disabled={busy || !key.trim()}>{busy ? <Loader2 size={15} className="animate-spin" /> : null} Check and save</button>
          </div>
        </form>
      )}
    </section>
  );
}
