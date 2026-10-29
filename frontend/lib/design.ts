/** The editor's design model: pages of layers, plus the starting layouts built from a post. */
import type { BrandKit, Platform, SocialPost } from "./api";

type Base = { id: string; x: number; y: number; rotation: number; opacity: number; locked?: boolean; hidden?: boolean; name?: string };
export type TextEl = Base & {
  type: "text"; text: string; width: number; fontFamily: string; fontSize: number; bold: boolean; italic: boolean; underline: boolean;
  uppercase: boolean; fill: string; align: "left" | "center" | "right"; lineHeight: number; letterSpacing: number;
  highlight?: string; shadow?: boolean;
};
export type ImageEl = Base & { type: "image"; src: string; width: number; height: number; cornerRadius: number; flipX?: boolean; fit?: "cover" | "contain" };
export type ShapeKind = "rect" | "circle" | "triangle" | "star" | "line";
export type ShapeEl = Base & {
  type: ShapeKind; width: number; height: number; fill: string; stroke: string; strokeWidth: number; cornerRadius: number;
  gradient?: { from: string; to: string; angle: 0 | 90 | 180 | 270 };
};
export type El = TextEl | ImageEl | ShapeEl;
export type Page = { id: string; background: string; elements: El[] };
export type Design = { version: 1; width: number; height: number; pages: Page[] };

export const SIZES: Record<Platform, [number, number]> = { instagram: [1080, 1350], facebook: [1200, 1200], linkedin: [1200, 1200], x: [1600, 900] };

/** Fonts offered in the editor (loaded from Google Fonts when the editor opens). */
export const FONTS = [
  "Inter", "Poppins", "Montserrat", "Playfair Display", "Lora", "Bebas Neue", "Oswald", "Anton", "Archivo Black", "DM Serif Display",
  "Dancing Script", "Pacifico", "Caveat", "Space Grotesk", "Noto Nastaliq Urdu",
];
// The styles each font really has: Google Fonts refuses a request for a style a font lacks.
const FONT_STYLES: Record<string, string> = {
  Inter: ":ital,wght@0,400;0,700;1,400;1,700", Poppins: ":ital,wght@0,400;0,700;1,400;1,700", Montserrat: ":ital,wght@0,400;0,700;1,400;1,700",
  "Playfair Display": ":ital,wght@0,400;0,700;1,400;1,700", Lora: ":ital,wght@0,400;0,700;1,400;1,700", Oswald: ":wght@400;700",
  "Space Grotesk": ":wght@400;700", Caveat: ":wght@400;700", "Dancing Script": ":wght@400;700", "Noto Nastaliq Urdu": ":wght@400;700",
};
/** One stylesheet per font, so one font failing to load never takes the others with it. */
export const FONT_LINKS = FONTS.map((f) => `https://fonts.googleapis.com/css2?family=${f.replace(/ /g, "+")}${FONT_STYLES[f] ?? ""}&display=swap`);

let counter = 0;
export const uid = () => `${Date.now().toString(36)}${(counter++).toString(36)}${Math.random().toString(36).slice(2, 6)}`;

export function text(over: Partial<TextEl> & { text: string }): TextEl {
  return {
    id: uid(), type: "text", x: 80, y: 80, rotation: 0, opacity: 1, width: 600, fontFamily: "Inter", fontSize: 64, bold: false, italic: false,
    underline: false, uppercase: false, fill: "#111111", align: "left", lineHeight: 1.15, letterSpacing: 0, ...over,
  };
}
export function image(over: Partial<ImageEl> & { src: string }): ImageEl {
  return { id: uid(), type: "image", x: 0, y: 0, rotation: 0, opacity: 1, width: 400, height: 400, cornerRadius: 0, ...over };
}
export function shape(kind: ShapeKind, over: Partial<ShapeEl> = {}): ShapeEl {
  return {
    id: uid(), type: kind, x: 100, y: 100, rotation: 0, opacity: 1, width: 300, height: kind === "line" ? 0 : 300, fill: "#6D5DFC",
    stroke: kind === "line" ? "#111111" : "", strokeWidth: kind === "line" ? 8 : 0, cornerRadius: 0, ...over,
  };
}

/** Black or white, whichever reads better on this colour. */
export function inkOn(hex: string): string {
  const h = hex.replace("#", "");
  const [r, g, b] = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2) || "00", 16));
  return 0.299 * r + 0.587 * g + 0.114 * b > 150 ? "#111111" : "#FFFFFF";
}

type Ctx = { post: SocialPost; brand: BrandKit | null; logo: string | null; w: number; h: number };

function photoOf(post: SocialPost): string {
  return post.background?.thumb_url || "";
}

/** Starting layouts. Each returns the layers of one page. */
export const TEMPLATES: { key: string; label: string; needsPhoto?: boolean; build: (c: Ctx, headline: string, body: string) => Page }[] = [
  {
    key: "photo-bottom", label: "Photo, headline at the bottom", needsPhoto: true,
    build: ({ post, brand, logo, w, h }, headline, body) => {
      const s = Math.min(w, h);
      const els: El[] = [
        image({ src: photoOf(post), width: w, height: h, fit: "cover", name: "Photo" }),
        shape("rect", { x: 0, y: h * 0.45, width: w, height: h * 0.55, fill: "#000000", gradient: { from: "rgba(0,0,0,0)", to: "rgba(0,0,0,0.78)", angle: 90 }, name: "Shade" }),
        text({ text: headline, x: s * 0.07, y: h - s * 0.42, width: w - s * 0.14, fontFamily: "Poppins", bold: true, fontSize: s * 0.075, fill: "#FFFFFF", name: "Headline" }),
      ];
      if (body) els.push(text({ text: body, x: s * 0.07, y: h - s * 0.17, width: w - s * 0.14, fontSize: s * 0.034, fill: "#F3F4F6", name: "Text" }));
      if (logo) els.push(image({ src: logo, x: s * 0.06, y: s * 0.06, width: s * 0.16, height: s * 0.16, fit: "contain", name: "Logo" }));
      return { id: uid(), background: brand?.primary_color || "#111111", elements: els };
    },
  },
  {
    key: "bold", label: "Bold colour",
    build: ({ brand, logo, w, h }, headline, body) => {
      const bg = brand?.primary_color || "#6D5DFC", ink = inkOn(bg), accent = brand?.accent_color || "#FF5A7A", s = Math.min(w, h);
      const els: El[] = [
        shape("circle", { x: w - s * 0.35, y: -s * 0.15, width: s * 0.6, height: s * 0.6, fill: accent, opacity: 0.9, name: "Circle" }),
        shape("rect", { x: s * 0.08, y: h * 0.38, width: s * 0.16, height: s * 0.02, fill: accent, cornerRadius: 8, name: "Bar" }),
        text({ text: headline, x: s * 0.08, y: h * 0.42, width: w - s * 0.16, fontFamily: "Bebas Neue", fontSize: s * 0.13, fill: ink, lineHeight: 1, name: "Headline" }),
      ];
      if (body) els.push(text({ text: body, x: s * 0.08, y: h * 0.75, width: w - s * 0.16, fontSize: s * 0.036, fill: ink, opacity: 0.9, name: "Text" }));
      if (logo) els.push(image({ src: logo, x: s * 0.08, y: s * 0.08, width: s * 0.14, height: s * 0.14, fit: "contain", name: "Logo" }));
      return { id: uid(), background: bg, elements: els };
    },
  },
  {
    key: "split", label: "Photo and colour, side by side", needsPhoto: true,
    build: ({ post, brand, logo, w, h }, headline, body) => {
      const bg = brand?.primary_color || "#111111", ink = inkOn(bg), s = Math.min(w, h), half = w >= h ? w / 2 : w;
      const photoH = w >= h ? h : h * 0.55;
      const els: El[] = [image({ src: photoOf(post), width: half, height: photoH, fit: "cover", name: "Photo" })];
      const tx = w >= h ? half + s * 0.06 : s * 0.07, ty = w >= h ? h * 0.3 : photoH + s * 0.06, tw = w >= h ? half - s * 0.12 : w - s * 0.14;
      els.push(text({ text: headline, x: tx, y: ty, width: tw, fontFamily: "Playfair Display", bold: true, fontSize: s * 0.068, fill: ink, name: "Headline" }));
      if (body) els.push(text({ text: body, x: tx, y: ty + s * 0.3, width: tw, fontSize: s * 0.032, fill: ink, opacity: 0.85, name: "Text" }));
      if (logo) els.push(image({ src: logo, x: w - s * 0.2, y: h - s * 0.2, width: s * 0.13, height: s * 0.13, fit: "contain", name: "Logo" }));
      return { id: uid(), background: bg, elements: els };
    },
  },
  {
    key: "quote", label: "Quote card",
    build: ({ brand, logo, w, h }, headline) => {
      const bg = "#FBF7F2", accent = brand?.primary_color || "#6D5DFC", s = Math.min(w, h);
      const els: El[] = [
        text({ text: "“", x: s * 0.08, y: h * 0.12, width: s * 0.3, fontFamily: "DM Serif Display", fontSize: s * 0.3, fill: accent, name: "Quote mark" }),
        text({ text: headline, x: s * 0.1, y: h * 0.36, width: w - s * 0.2, fontFamily: "DM Serif Display", fontSize: s * 0.075, fill: "#1F2937", align: "center", name: "Quote" }),
        shape("rect", { x: w / 2 - s * 0.06, y: h * 0.78, width: s * 0.12, height: s * 0.01, fill: accent, cornerRadius: 6, name: "Line" }),
      ];
      if (logo) els.push(image({ src: logo, x: w / 2 - s * 0.07, y: h * 0.83, width: s * 0.14, height: s * 0.1, fit: "contain", name: "Logo" }));
      return { id: uid(), background: bg, elements: els };
    },
  },
  {
    key: "minimal", label: "Minimal frame", needsPhoto: true,
    build: ({ post, brand, logo, w, h }, headline) => {
      const s = Math.min(w, h), pad = s * 0.06;
      const els: El[] = [
        image({ src: photoOf(post), x: pad, y: pad, width: w - 2 * pad, height: h * 0.72 - pad, fit: "cover", cornerRadius: s * 0.03, name: "Photo" }),
        text({ text: headline, x: pad, y: h * 0.76, width: w - 2 * pad - (logo ? s * 0.18 : 0), fontFamily: "Montserrat", bold: true, fontSize: s * 0.055, fill: "#111111", name: "Headline" }),
      ];
      if (logo) els.push(image({ src: logo, x: w - pad - s * 0.14, y: h * 0.77, width: s * 0.14, height: s * 0.12, fit: "contain", name: "Logo" }));
      return { id: uid(), background: brand?.secondary_color && inkOn(brand.secondary_color) === "#111111" ? brand.secondary_color : "#FFFFFF", elements: els };
    },
  },
];

export function sizeFor(post: SocialPost): [number, number] {
  return post.format === "carousel" ? [1080, 1350] : SIZES[post.platform];
}

/** A design for a post that hasn't been edited yet: every part a separate layer you can change. */
export function designFromPost(post: SocialPost, brand: BrandKit | null, logo: string | null): Design {
  const [w, h] = sizeFor(post);
  const ctx = { post, brand, logo, w, h };
  const hasPhoto = !!photoOf(post);
  const cover = (hasPhoto ? TEMPLATES[0] : TEMPLATES[1]).build(ctx, post.headline, post.format === "carousel" ? "" : post.cta);
  const pages = [cover];
  if (post.format === "carousel") {
    for (const s of post.slides) pages.push(TEMPLATES[s.background?.thumb_url ? 0 : 1].build({ ...ctx, post: { ...post, background: s.background ?? null } }, s.headline, s.body));
  }
  return { version: 1, width: w, height: h, pages };
}

/** The post's current images as page backgrounds, to draw on top of the automatic design. */
export function designFromImages(post: SocialPost): Design {
  const [w, h] = sizeFor(post);
  const urls = post.image_urls.length ? post.image_urls : post.image_url ? [post.image_url] : [];
  return { version: 1, width: w, height: h, pages: urls.map((u) => ({ id: uid(), background: "#FFFFFF", elements: [image({ src: u.split("?")[0], width: w, height: h, fit: "cover", name: "Current design" })] })) };
}
