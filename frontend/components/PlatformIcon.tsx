import { Facebook, Instagram, Linkedin, Twitter } from "lucide-react";
import type { Platform } from "@/lib/api";

export const PLATFORM_META: Record<Platform, { label: string; color: string; bg: string }> = {
  instagram: { label: "Instagram", color: "text-pink-600", bg: "bg-pink-50" },
  linkedin: { label: "LinkedIn", color: "text-sky-700", bg: "bg-sky-50" },
  x: { label: "X", color: "text-slate-900", bg: "bg-slate-100" },
  facebook: { label: "Facebook", color: "text-blue-600", bg: "bg-blue-50" },
};

export function PlatformIcon({ platform, size = 14 }: { platform: Platform; size?: number }) {
  const cls = PLATFORM_META[platform].color;
  switch (platform) {
    case "instagram":
      return <Instagram size={size} className={cls} />;
    case "linkedin":
      return <Linkedin size={size} className={cls} />;
    case "facebook":
      return <Facebook size={size} className={cls} />;
    default:
      return <Twitter size={size} className={cls} />;
  }
}
