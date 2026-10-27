import { useId } from "react";

/** The MonoPlus mark: an "M+" on the brand gradient (the same drawing as app/icon.svg). */
export function BrandMark({ size = 36, className = "" }: { size?: number; className?: string }) {
  const id = useId().replace(/:/g, "");
  return (
    <svg viewBox="0 0 48 48" width={size} height={size} className={className} role="img" aria-label="MonoPlus">
      <defs>
        <linearGradient id={`${id}g`} x1="0" y1="0" x2="48" y2="48" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#5B47FB" />
          <stop offset=".58" stopColor="#9B3DF5" />
          <stop offset="1" stopColor="#FF5C8A" />
        </linearGradient>
        <linearGradient id={`${id}s`} x1="0" y1="0" x2="0" y2="24" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#fff" stopOpacity=".28" />
          <stop offset="1" stopColor="#fff" stopOpacity="0" />
        </linearGradient>
      </defs>
      <rect width="48" height="48" rx="13" fill={`url(#${id}g)`} />
      <rect width="48" height="24" rx="13" fill={`url(#${id}s)`} />
      <path d="M11.5 34V16.5l9.5 10.5 9.5-10.5V34" fill="none" stroke="#fff" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M38 9.5v7M34.5 13h7" stroke="#fff" strokeWidth="3" strokeLinecap="round" className="origin-[38px_13px] transition-transform duration-500 group-hover:rotate-90" />
    </svg>
  );
}
