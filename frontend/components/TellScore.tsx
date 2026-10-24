export function tellTone(score: number | null) {
  if (score === null) return "bg-slate-100 text-slate-500";
  if (score < 15) return "bg-emerald-50 text-emerald-700";
  if (score < 35) return "bg-amber-50 text-amber-700";
  return "bg-red-50 text-red-700";
}

/** Our AI-tell score (0-100, lower is better) shown the way people read it: % human-sounding. */
export const humanPct = (score: number | null) => (score === null ? null : Math.max(0, Math.round(100 - score)));

export function TellScore({ before, after }: { before: number | null; after: number | null }) {
  const pct = humanPct(after);
  return (
    <span className="inline-flex items-center gap-1.5 text-xs" title="How free the caption is of common AI-writing patterns.">
      {before !== null && after !== null && before > after && (
        <span className="text-slate-400 line-through">{humanPct(before)}%</span>
      )}
      <span className={`chip ${tellTone(after)}`}>{pct === null ? "–" : `${pct}% human-sounding`}</span>
    </span>
  );
}
