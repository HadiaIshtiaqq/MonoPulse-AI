"use client";

import { useEffect, useRef, useState } from "react";
import { Circle, Loader2, RotateCcw, Square, X } from "lucide-react";

/** Record a real person in the browser, reading the script from a teleprompter over the camera. */
export function Recorder({ script, onDone, onClose }: { script: string[]; onDone: (clip: Blob) => void; onClose: () => void }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const promptRef = useRef<HTMLDivElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const recRef = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const [state, setState] = useState<"starting" | "ready" | "countdown" | "recording" | "review" | "error">("starting");
  const [error, setError] = useState("");
  const [count, setCount] = useState(3);
  const [speed, setSpeed] = useState(40); // pixels per second
  const [clip, setClip] = useState<Blob | null>(null);
  const [seconds, setSeconds] = useState(0);

  useEffect(() => {
    let live = true;
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: "user", width: { ideal: 1080 }, height: { ideal: 1920 }, aspectRatio: { ideal: 9 / 16 } }, audio: true })
      .then((s) => {
        if (!live) { s.getTracks().forEach((t) => t.stop()); return; }
        streamRef.current = s;
        if (videoRef.current) { videoRef.current.srcObject = s; videoRef.current.play().catch(() => {}); }
        setState("ready");
      })
      .catch((e) => { setError(e?.name === "NotAllowedError" ? "Camera and microphone access was refused. Allow them in the browser's address bar, then try again." : "No camera or microphone was found."); setState("error"); });
    return () => { live = false; streamRef.current?.getTracks().forEach((t) => t.stop()); };
  }, []);

  // The teleprompter scrolls while recording.
  useEffect(() => {
    if (state !== "recording") return;
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const el = promptRef.current;
      if (el) el.scrollTop = ((now - start) / 1000) * speed;
      setSeconds(Math.floor((now - start) / 1000));
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [state, speed]);

  function begin() {
    setState("countdown");
    setCount(3);
    let n = 3;
    const timer = setInterval(() => {
      n -= 1;
      setCount(n);
      if (n === 0) { clearInterval(timer); record(); }
    }, 800);
  }

  function record() {
    const s = streamRef.current;
    if (!s) return;
    const type = ["video/webm;codecs=vp9,opus", "video/webm;codecs=vp8,opus", "video/webm", "video/mp4"].find((t) => MediaRecorder.isTypeSupported(t)) || "";
    const rec = new MediaRecorder(s, type ? { mimeType: type, videoBitsPerSecond: 6_000_000 } : undefined);
    chunks.current = [];
    rec.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data); };
    rec.onstop = () => {
      const blob = new Blob(chunks.current, { type: rec.mimeType || "video/webm" });
      setClip(blob);
      setState("review");
      if (videoRef.current) { videoRef.current.srcObject = null; videoRef.current.src = URL.createObjectURL(blob); videoRef.current.muted = false; videoRef.current.loop = true; videoRef.current.play().catch(() => {}); }
    };
    recRef.current = rec;
    rec.start(500);
    if (promptRef.current) promptRef.current.scrollTop = 0;
    setState("recording");
  }

  function stop() { recRef.current?.stop(); }

  function retake() {
    setClip(null);
    const v = videoRef.current;
    if (v && streamRef.current) { v.src = ""; v.srcObject = streamRef.current; v.muted = true; v.loop = false; v.play().catch(() => {}); }
    setState("ready");
  }

  return (
    <div className="fixed inset-0 z-[60] grid place-items-center bg-black/80 p-4">
      <div className="relative flex h-full max-h-[92vh] w-full max-w-[460px] flex-col overflow-hidden rounded-3xl bg-black shadow-2xl">
        <video ref={videoRef} muted playsInline className="absolute inset-0 h-full w-full object-cover" style={{ transform: state === "review" ? undefined : "scaleX(-1)" }} />
        <button onClick={onClose} className="absolute right-3 top-3 z-10 rounded-full bg-black/50 p-2 text-white hover:bg-black/70" title="Close"><X size={18} /></button>
        {state !== "review" && state !== "error" && (
          <div ref={promptRef} className="relative z-10 mx-4 mt-14 max-h-[38%] overflow-hidden rounded-2xl bg-black/45 px-5 py-4 text-center text-[22px] font-semibold leading-snug text-white">
            {script.map((l, i) => <p key={i} className="mb-3">{l}</p>)}
            <div className="h-48" />
          </div>
        )}
        {state === "countdown" && <div className="absolute inset-0 z-20 grid place-items-center text-8xl font-bold text-white drop-shadow-lg">{count}</div>}
        {state === "starting" && <div className="absolute inset-0 grid place-items-center text-white"><Loader2 className="animate-spin" /></div>}
        {state === "error" && <div className="relative z-10 m-auto max-w-xs rounded-2xl bg-white p-5 text-center text-sm">{error}</div>}
        <div className="relative z-10 mt-auto space-y-3 p-4">
          {state === "ready" && (
            <label className="flex items-center gap-2 rounded-xl bg-black/45 px-3 py-2 text-xs text-white">
              Scroll speed
              <input type="range" min={15} max={90} value={speed} onChange={(e) => setSpeed(Number(e.target.value))} className="flex-1 accent-white" />
            </label>
          )}
          <div className="flex items-center justify-center gap-3">
            {state === "ready" && (
              <button onClick={begin} className="flex items-center gap-2 rounded-full bg-red-600 px-6 py-3 font-semibold text-white shadow-lg hover:bg-red-500"><Circle size={16} className="fill-white" /> Record</button>
            )}
            {state === "recording" && (
              <button onClick={stop} className="flex items-center gap-2 rounded-full bg-white px-6 py-3 font-semibold text-red-600 shadow-lg">
                <Square size={14} className="fill-red-600" /> Stop · {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
              </button>
            )}
            {state === "review" && clip && (
              <>
                <button onClick={retake} className="flex items-center gap-2 rounded-full bg-white/90 px-5 py-3 text-sm font-semibold text-ink"><RotateCcw size={15} /> Retake</button>
                <button onClick={() => onDone(clip)} className="rounded-full bg-brand px-6 py-3 text-sm font-semibold text-white shadow-lg">Use this take</button>
              </>
            )}
          </div>
          {state === "ready" && <p className="text-center text-xs text-white/80">Hold the phone upright, look at the camera, and read at a natural pace. Aim for 15 to 45 seconds.</p>}
        </div>
      </div>
    </div>
  );
}
