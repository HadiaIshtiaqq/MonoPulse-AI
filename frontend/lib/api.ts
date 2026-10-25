export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export type Platform = "instagram" | "linkedin" | "x" | "facebook";
export type PostStatus = "DRAFT" | "APPROVED" | "PUBLISHED";
export type Layout = "bold" | "split" | "quote" | "photo";
export type TextPosition = "auto" | "top" | "center" | "bottom";
export type HumanizeMode = "light" | "standard" | "deep";

export interface BrandKit {
  id: string;
  name: string;
  tagline: string;
  description: string;
  industry: string;
  location: string;
  value_props: string[];
  keywords: string[];
  primary_color: string;
  secondary_color: string;
  accent_color: string;
  palette: string[];
  logo_url: string | null;
  website_url: string | null;
  brand_voice_prompt: string;
  source_type: string;
  products: Product[];
  images: string[];
}

export interface Product {
  name: string;
  price: string;
  url: string;
  image_url: string;
  category: string;
}

export interface TrendItem {
  title: string;
  url: string;
  snippet: string;
  published_date: string | null;
  query: string;
}

export interface Slide {
  headline: string;
  body: string;
  background?: Background | null;
}

export interface Background {
  source: "stock" | "upload" | "website";
  path: string;
  thumb_url: string;
  credit: string;
  credit_url: string;
  license: string;
}

export interface SocialPost {
  id: string;
  campaign_id: string;
  day: number;
  platform: Platform;
  pillar: string;
  headline: string;
  caption: string;
  cta: string;
  hashtags: string[];
  alt_text: string;
  seo_keywords: string[];
  trend_title: string | null;
  trend_url: string | null;
  product: Product | null;
  layout: Layout;
  format: "single" | "carousel";
  slides: Slide[];
  background: Background | null;
  text_position: TextPosition;
  text_scale: number;
  image_url: string | null;
  image_urls: string[];
  publish_at: string;
  status: PostStatus;
  published_via: string | null;
  publish_error: string | null;
  remote_id: string | null;
  remote_url: string | null;
  is_humanized: boolean;
  original_caption: string | null;
  ai_tell_before: number | null;
  ai_tell_after: number | null;
}

export interface Strategy {
  positioning: string;
  audience: string;
  voice_rules: string[];
  pillars: { name: string; description: string }[];
  weekly_themes: string[];
}

export interface Campaign {
  id: string;
  source_input: string;
  brand: BrandKit | null;
  start_date: string;
  days: number;
  platforms: Platform[];
  status: "GENERATING" | "DRAFT" | "APPROVED" | "PUBLISHED" | "FAILED";
  strategy: Strategy | null;
  trends: TrendItem[];
  posts: SocialPost[];
  mode: "live" | "demo";
  timings: Record<string, number>;
  research_ids: string[];
}

export interface ResearchInsights {
  verified_trend: string;
  pricing_gap: string;
  feature_insights: string;
  audience_insight: string;
  content_angles: string[];
  confidence: number;
  confidence_rationale: string;
  opportunity: number;
}

export interface ResearchTask {
  id: string;
  topic: string;
  region: string;
  campaign_id: string | null;
  status: "pending" | "running" | "retry" | "completed" | "failed";
  attempts: number;
  report: string | null;
  insights: ResearchInsights | null;
  sources: { id: number; title: string; url: string; kind: string; published_at: string | null }[];
  error: string | null;
  created_at: string;
  completed_at: string | null;
}

export interface JobStep {
  key: string;
  label: string;
  status: "pending" | "running" | "done" | "skipped" | "error";
  detail: string;
  seconds: number | null;
}

export interface Job {
  id: string;
  campaign_id: string;
  status: "running" | "done" | "error";
  steps: JobStep[];
  error: string | null;
  brand?: BrandKit;
  trends?: TrendItem[];
  elapsed?: Record<string, number>;
}

export interface CampaignSummary {
  id: string;
  name: string;
  website: string | null;
  status: string;
  posts: number;
  approved: number;
  published: number;
  platforms: Platform[];
  start_date: string;
  days: number;
  primary_color: string | null;
  accent_color: string | null;
  thumbnails: string[];
  created_at: string;
}

export interface Health {
  mode: "live" | "demo";
  nebius: boolean;
  tavily: boolean;
  pexels: boolean;
  models: Record<string, string>;
}

export interface Pattern {
  id: string;
  label: string;
  count: number;
  example: string;
  weight: number;
}

export interface HumanizeStep {
  name: string;
  text: string;
  score: number;
  accepted: boolean;
  note: string;
}

export interface HumanizeResult {
  text: string;
  before: number;
  after: number;
  used_llm: boolean;
  mode?: HumanizeMode;
  patterns_before: Pattern[];
  patterns_after: Pattern[];
  steps: HumanizeStep[];
}

export interface StockPhoto {
  id: string;
  thumb: string;
  full: string;
  width: number;
  height: number;
  credit: string;
  credit_url: string;
  license: string;
  source: string;
}

export interface PublishingStatus {
  connected: Record<Platform, boolean>;
  webhook: boolean;
  auto_publish: boolean;
}


export type PostUpdate = Partial<
  Pick<SocialPost, "headline" | "caption" | "cta" | "hashtags" | "publish_at" | "status" | "layout" | "slides" | "text_position" | "text_scale">
> & { clear_background?: boolean };

const KEY_STORE = "monoplus_access_key";

export const accessKey = {
  get: () => {
    try { return typeof window === "undefined" ? "" : window.localStorage.getItem(KEY_STORE) || ""; } catch { return ""; }
  },
  set: (k: string) => { try { window.localStorage.setItem(KEY_STORE, k); } catch {} },
  clear: () => { try { window.localStorage.removeItem(KEY_STORE); } catch {} },
};

function authHeaders(): Record<string, string> {
  const k = accessKey.get();
  return k ? { "X-Access-Key": k } : {};
}

function locked() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event("monoplus:locked"));
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = typeof FormData !== "undefined" && init?.body instanceof FormData;
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { ...(isForm ? {} : { "Content-Type": "application/json" }), ...authHeaders(), ...((init?.headers as Record<string, string>) || {}) },
    cache: "no-store",
  });
  if (res.status === 401) locked();
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : Array.isArray(body.detail) ? body.detail.map((d: any) => d.msg).join("; ") : detail;
    } catch {}
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.status === 204 ? (undefined as T) : res.json();
}

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

export const api = {
  health: () => req<Health>("/api/health"),
  createCampaign: (body: { input: string; platforms: Platform[]; days: number; posts_per_day?: number; research_ids?: string[] }) =>
    req<{ campaign_id: string; job_id: string }>("/api/campaigns", json("POST", body)),
  job: (id: string) => req<Job>(`/api/jobs/${id}`),
  campaigns: () => req<CampaignSummary[]>("/api/campaigns"),
  campaign: (id: string) => req<Campaign>(`/api/campaigns/${id}`),
  deleteCampaign: (id: string) => req<void>(`/api/campaigns/${id}`, { method: "DELETE" }),
  approveAll: (id: string) => req<Campaign>(`/api/campaigns/${id}/approve-all`, { method: "POST" }),
  updateBrand: (id: string, body: Partial<Pick<BrandKit, "name" | "tagline" | "primary_color" | "secondary_color" | "accent_color" | "brand_voice_prompt">> & {
    logo_upload_id?: string;
    remove_logo?: boolean;
  }) => req<Campaign>(`/api/campaigns/${id}/brand`, json("PATCH", body)),
  exportUrl: (id: string) => `${API_URL}/api/campaigns/${id}/export${accessKey.get() ? `?key=${encodeURIComponent(accessKey.get())}` : ""}`,
  access: () => req<{ required: boolean; ok: boolean }>("/api/access"),
  upcoming: (days = 7) => req<{ campaign_id: string; brand: string; post: SocialPost }[]>(`/api/upcoming?days=${days}`),

  updatePost: (id: string, body: PostUpdate) => req<SocialPost>(`/api/posts/${id}`, json("PATCH", body)),
  setBackground: (id: string, body: { source: "stock"; photo_id: string } | { source: "upload"; upload_id: string } | { source: "website"; image_url: string }) =>
    req<SocialPost>(`/api/posts/${id}/background`, json("POST", body)),
  humanizePost: (id: string, mode: HumanizeMode = "standard") =>
    req<HumanizeResult & { post: SocialPost }>(`/api/posts/${id}/humanize`, json("POST", { mode })),
  rewritePost: (id: string, tone: string) => req<SocialPost>(`/api/posts/${id}/rewrite`, json("POST", { tone })),
  share: (id: string) =>
    req<{ platform: Platform; url: string; caption: string; image_url: string | null; image_urls: string[]; note: string }>(`/api/posts/${id}/share`),
  markPublished: (id: string) => req<SocialPost>(`/api/posts/${id}/mark-published`, { method: "POST" }),
  publishNow: (id: string) => req<SocialPost>(`/api/posts/${id}/publish`, { method: "POST" }),

  searchPhotos: (q: string, orientation = "square") =>
    req<{ source: string; photos: StockPhoto[] }>(`/api/photos/search?q=${encodeURIComponent(q)}&orientation=${orientation}`),
  upload: (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    return req<{ id: string; url: string }>("/api/uploads", { method: "POST", body: fd });
  },

  publishing: () => req<PublishingStatus>("/api/publishing"),
  setAutoPublish: (enabled: boolean) => req<PublishingStatus>("/api/publishing/auto", json("PUT", { enabled })),

  humanize: (text: string, mode: HumanizeMode = "standard") => req<HumanizeResult>("/api/humanize", json("POST", { text, mode })),

  researchTasks: () => req<ResearchTask[]>("/api/research/tasks"),
  researchTask: (id: string) => req<ResearchTask>(`/api/research/tasks/${id}`),
  queueResearch: (body: { topic: string; region?: string; campaign_id?: string | null }) => req<ResearchTask>("/api/research/tasks", json("POST", body)),
  deleteResearch: (id: string) => req<void>(`/api/research/tasks/${id}`, { method: "DELETE" }),
  memory: (q: string) =>
    req<{ kind: string; title: string; created_at: string; excerpt: string }[]>(`/api/research/memory?q=${encodeURIComponent(q)}`),
};

/** Reads a server-sent-events stream with fetch(), calling onEvent for each `data:` message. */
export async function streamEvents(path: string, onEvent: (ev: any) => void, signal?: AbortSignal) {
  const res = await fetch(`${API_URL}${path}`, { signal, headers: authHeaders() });
  if (res.status === 401) locked();
  if (!res.ok || !res.body) {
    let msg = res.statusText;
    try {
      msg = (await res.json()).detail ?? msg;
    } catch {}
    throw new Error(typeof msg === "string" ? msg : "Request failed");
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const line = buf.slice(0, idx).split("\n").find((l) => l.startsWith("data: "));
      buf = buf.slice(idx + 2);
      if (line) onEvent(JSON.parse(line.slice(6)));
    }
  }
}

export const media = (path: string | null | undefined) => (path ? `${API_URL}${path}` : "");

// ---- Local time: posts are stored in UTC but always shown and edited in the viewer's time zone.

const pad = (n: number) => String(n).padStart(2, "0");

/** YYYY-MM-DD of a moment in local time. */
export const localDayKey = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;

/** Value for <input type="datetime-local"> from an ISO timestamp. */
export const toLocalInput = (iso: string) => {
  const d = new Date(iso);
  return `${localDayKey(d)}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
};

/** ISO (UTC) timestamp from a datetime-local value, which the browser reads as local time. */
export const fromLocalInput = (v: string) => new Date(v).toISOString();

export const fmtDay = (iso: string, opts: Intl.DateTimeFormatOptions = { weekday: "short", month: "short", day: "numeric" }) =>
  new Date(iso).toLocaleDateString(undefined, opts);

export const fmtTime = (iso: string) => new Date(iso).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });

export function timeAgo(iso: string | null | undefined) {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (Number.isNaN(s)) return "";
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}
