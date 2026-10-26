"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from "lucide-react";

type Tone = "success" | "error" | "info";
type Toast = { id: number; tone: Tone; text: string; leaving?: boolean };
type Ask = { title: string; body?: string; confirm?: string; danger?: boolean };

type Feedback = {
  toast: (text: string, tone?: Tone) => void;
  confirm: (ask: Ask) => Promise<boolean>;
};

const Ctx = createContext<Feedback>({
  toast: () => {},
  confirm: async ({ title }) => window.confirm(title),
});

/** Toasts and a confirm dialog anywhere in the app: `const { toast, confirm } = useFeedback()`. */
export const useFeedback = () => useContext(Ctx);

const ICONS = { success: CheckCircle2, error: XCircle, info: Info };
const TONES = {
  success: "text-emerald-500",
  error: "text-red-500",
  info: "text-brand",
};

export function FeedbackProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [ask, setAsk] = useState<(Ask & { resolve: (ok: boolean) => void }) | null>(null);
  const seq = useRef(0);

  const dismiss = useCallback((id: number) => {
    setToasts((t) => t.map((x) => (x.id === id ? { ...x, leaving: true } : x)));
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), 250);
  }, []);

  const toast = useCallback((text: string, tone: Tone = "success") => {
    const id = ++seq.current;
    setToasts((t) => [...t.slice(-3), { id, tone, text }]);
    setTimeout(() => dismiss(id), tone === "error" ? 6000 : 3500);
  }, [dismiss]);

  const confirm = useCallback((a: Ask) => new Promise<boolean>((resolve) => setAsk({ ...a, resolve })), []);

  return (
    <Ctx.Provider value={{ toast, confirm }}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-4 bottom-4 z-[70] flex flex-col items-center gap-2 sm:inset-x-auto sm:right-6 sm:items-end">
        {toasts.map(({ id, tone, text, leaving }) => {
          const Icon = ICONS[tone];
          return (
            <div key={id} role={tone === "error" ? "alert" : "status"}
              className={`pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-2xl border border-slate-200 bg-white/95 px-4 py-3 text-sm shadow-pop backdrop-blur transition-all duration-200 ${leaving ? "translate-y-2 opacity-0" : "animate-scale-in"}`}>
              <Icon size={18} className={`mt-px shrink-0 ${TONES[tone]}`} />
              <p className="flex-1 text-slate-700">{text}</p>
              <button onClick={() => dismiss(id)} aria-label="Dismiss" className="-m-1 rounded-md p-1 text-slate-400 transition hover:bg-slate-100 hover:text-slate-600">
                <X size={14} />
              </button>
            </div>
          );
        })}
      </div>
      {ask && <ConfirmDialog ask={ask} onDone={(ok) => { ask.resolve(ok); setAsk(null); }} />}
    </Ctx.Provider>
  );
}

function ConfirmDialog({ ask, onDone }: { ask: Ask; onDone: (ok: boolean) => void }) {
  const okRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    okRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onDone(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onDone]);

  return (
    <div className="fixed inset-0 z-[60] grid animate-fade-in place-items-center bg-ink/40 p-4 backdrop-blur-sm" onClick={() => onDone(false)}>
      <div role="alertdialog" aria-modal="true" aria-labelledby="confirm-title"
        className="w-full max-w-sm animate-scale-in rounded-2xl bg-white p-6 shadow-pop" onClick={(e) => e.stopPropagation()}>
        <div className={`grid h-11 w-11 place-items-center rounded-full ${ask.danger ? "bg-red-50 text-red-500" : "bg-brand-soft text-brand"}`}>
          <AlertTriangle size={20} />
        </div>
        <h2 id="confirm-title" className="mt-4 text-base font-semibold">{ask.title}</h2>
        {ask.body && <p className="mt-1.5 text-sm text-slate-500">{ask.body}</p>}
        <div className="mt-6 flex justify-end gap-2">
          <button className="btn-ghost" onClick={() => onDone(false)}>Cancel</button>
          <button ref={okRef} onClick={() => onDone(true)}
            className={ask.danger ? "btn-danger" : "btn-primary"}>
            {ask.confirm ?? "Confirm"}
          </button>
        </div>
      </div>
    </div>
  );
}
