export const API_URL = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "");

export type Platform = "instagram" | "linkedin" | "x" | "facebook";
export type ReelSceneKind = "hook" | "product" | "fact" | "cta";
/** One scene of a reel as the owner edits it; `photo` is a /media/… path or one of the brand's web photos. */
export type ReelScene = { kind: ReelSceneKind; text: string; sub: string; photo: string; tag?: string };
export type ReelLanguage = "en" | "roman" | "ur" | "mix";
export type ReelOptions = { palette: string; color: string; pace: "relaxed" | "normal" | "snappy"; case: "auto" | "normal" | "upper"; language?: ReelLanguage };
export type ReelPalette = { key: string; label: string; colors: string[] };
export type ReelOccasion = { key: string; label: string; greeting: string; colors: string[]; soon: string };
export type ReelOptionsInfo = {
  topics: { key: string; label: string; blurb: string; available: boolean }[];
  suggested_topic: string;
  occasions: ReelOccasion[];
  suggested_occasion: string;
  palettes: ReelPalette[];
  styles: ReelStyle[];
  languages: { key: ReelLanguage; label: string }[];
  trends: { key: string; label: string }[];
};
export type UgcAd = { id: string; product: string; format: string; engine: "builtin" | "person" | "avatar"; script: string[]; video_url: string;
  poster_url: string; seconds: number; avatar: string; look: string; caption: string; voice: boolean; created_at: string };
export type UgcAvatar = { id: string; name: string; preview: string; gender: string };
export type UgcOverview = { formats: { key: string; label: string; blurb: string }[]; heygen: boolean; voice: boolean; listening: boolean;
  looks: { key: string; label: string }[]; captions: { key: string; label: string }[];
  products: { index: number; name: string; price: string; image: string }[]; ads: UgcAd[] };
export type Connections = {
  meta: { connected: boolean; page: string; instagram: string; instagram_ready: boolean; from_env: boolean };
  nebius: { connected: boolean; from_env: boolean };
  tavily: { connected: boolean; from_env: boolean };
  heygen: { connected: boolean; from_env: boolean };
  file: string;
};
export type ReelResult = { post: SocialPost; seconds: number; scenes: string[]; used_llm: boolean; render_ms: number; style: string; topic: string; occasion: string };
export type ReelPhoto = { url: string; label: string; price: string; remote: boolean };
export type ReelStyle = { key: string; label: string; blurb: string };

export type PostStatus = "DRAFT" | "APPROVED" | "PUBLISHED";
export type Layout = "bold" | "split" | "quote" | "photo" | "frame" | "poster" | "minimal" | "duo" | "greeting";
export type PostKind = "spotlight" | "carousel" | "duo" | "tip" | "quote" | "sale" | "moment" | "question" | "greeting";
export const KIND_LABELS: Record<PostKind, string> = {
  spotlight: "Spotlight", carousel: "Carousel", duo: "This or that", tip: "Tip", quote: "Brand quote",
  sale: "Sale", moment: "Seasonal", question: "Question", greeting: "Greeting",
};
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
  logo_path?: string | null;
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
  group_id: string;
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
  compare: Product | null;
  kind: PostKind;
  gallery: Background[];
  layout: Layout;
  format: "single" | "carousel";
  slides: Slide[];
  background: Background | null;
  text_position: TextPosition;
  text_scale: number;
  image_url: string | null;
  image_urls: string[];
  design?: unknown | null; // the owner's own design from the editor
  video_url?: string | null;
  video_poster?: string | null;
  reel_scenes?: ReelScene[];
  reel_style?: string;
  reel_options?: ReelOptions;
  reel_topic?: string;
  reel_occasion?: string;
  occasion?: string;
  publish_at: string;
  status: PostStatus;
  published_via: string | null;
  publish_error: string | null;
  remote_id: string | null;
  remote_url: string | null;
  is_humanized: boolean;
  original_caption: string | null;
  caption_history?: string[];
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

export interface ContentMix {
  posts: number;
  types: Partial<Record<PostKind, number>>;
  layouts: number;
  repeated_headlines: number;
}

export interface Campaign {
  id: string;
  source_input: string;
  content_mix?: ContentMix;
  competitor_task_id?: string | null;
  brand: BrandKit | null;
  start_date: string;
  days: number;
  platforms: Platform[];
  status: "GENERATING" | "DRAFT" | "APPROVED" | "PUBLISHED" | "FAILED";
  design_version?: number;
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

export interface CompetitorProfile {
  name: string;
  url: string;
  tagline: string;
  price_range: string;
  median_price: number;
  currency: string;
  products_seen: number;
  on_sale: number;
  best_discount: number;
  lines: string[];
  segments: string[];
  claims: string[];
  socials: string[];
  sample_products: Product[];
  found_via: string;
  reachable: boolean;
  note: string;
}

export interface CompetitorReport {
  brand: CompetitorProfile | null;
  competitors: CompetitorProfile[];
  summary: string;
  position: string[];
  strengths: string[];
  gaps: string[];
  recommendations: { title: string; why: string; how: string }[];
  plan: { week: number; focus: string; actions: string[] }[];
  content_ideas: string[];
  method: "rules" | "model";
}

export interface ResearchTask {
  id: string;
  topic: string;
  kind: "question" | "competitors";
  brand_url: string;
  competitor_urls: string[];
  progress: string[];
  competitors: CompetitorReport | null;
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
  design_version?: number;
  protected?: boolean;
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

/** Where older versions kept the access key. It now lives in an httpOnly cookie the server sets,
 *  which page scripts can't read; a key found here is traded for that cookie once, then removed. */
const OLD_KEY_STORE = "monoplus_access_key";

export function takeOldAccessKey(): string {
  try {
    const k = window.localStorage.getItem(OLD_KEY_STORE) || "";
    window.localStorage.removeItem(OLD_KEY_STORE);
    return k;
  } catch {
    return "";
  }
}

function locked() {
  if (typeof window !== "undefined") window.dispatchEvent(new Event("monoplus:locked"));
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const isForm = typeof FormData !== "undefined" && init?.body instanceof FormData;
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { ...(isForm ? {} : { "Content-Type": "application/json" }), ...((init?.headers as Record<string, string>) || {}) },
      credentials: "include", // the access cookie
      cache: "no-store",
    });
  } catch {
    throw new Error("Can't reach MonoPlus right now. Check your internet connection and try again in a moment.");
  }
  if (res.status === 401) locked();
  if (res.status >= 500) {
    throw new Error("Something went wrong on our side. Please try again; if it keeps happening, refresh the page.");
  }
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
  approveAll: (id: string) => req<Campaign & { approved_ids: string[] }>(`/api/campaigns/${id}/approve-all`, { method: "POST" }),
  undoApprove: (id: string, postIds: string[]) => req<Campaign>(`/api/campaigns/${id}/undo-approve`, json("POST", { post_ids: postIds })),
  redraw: (id: string) => req<Campaign>(`/api/campaigns/${id}/redraw`, { method: "POST" }),
  updateBrand: (id: string, body: Partial<Pick<BrandKit, "name" | "tagline" | "primary_color" | "secondary_color" | "accent_color" | "brand_voice_prompt">> & {
    logo_upload_id?: string;
    remove_logo?: boolean;
  }) => req<Campaign>(`/api/campaigns/${id}/brand`, json("PATCH", body)),
  exportUrl: (id: string) => `${API_URL}/api/campaigns/${id}/export`,
  access: () => req<{ required: boolean; ok: boolean }>("/api/access"),
  /** Resolves true when the key is right (the server then keeps it in a cookie), false when it isn't. */
  login: async (key: string) => {
    const res = await fetch(`${API_URL}/api/access/login`, {
      method: "POST", credentials: "include", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key }),
    });
    return res.ok;
  },
  logout: () => req<{ ok: boolean }>("/api/access/logout", { method: "POST" }),
  upcoming: (days = 7) => req<{ campaign_id: string; brand: string; post: SocialPost }[]>(`/api/upcoming?days=${days}`),

  updatePost: (id: string, body: PostUpdate) => req<SocialPost>(`/api/posts/${id}`, json("PATCH", body)),
  setBackground: (id: string, body: { source: "stock"; photo_id: string } | { source: "upload"; upload_id: string } | { source: "website"; image_url: string }) =>
    req<SocialPost>(`/api/posts/${id}/background`, json("POST", body)),
  humanizePost: (id: string, mode: HumanizeMode = "standard") =>
    req<HumanizeResult & { post: SocialPost }>(`/api/posts/${id}/humanize`, json("POST", { mode })),
  rewritePost: (id: string, tone: string) => req<SocialPost>(`/api/posts/${id}/rewrite`, json("POST", { tone })),
  /** Renders in the background on the server and resolves when the reel is ready (it can take a while). */
  makeReel: async (id: string, body: { scenes?: ReelScene[]; style?: string; options?: ReelOptions; topic?: string; occasion?: string; trend?: string } = {}) => {
    const { job_id } = await req<{ job_id: string }>(`/api/posts/${id}/reel?background=true`, json("POST", body));
    for (;;) {
      await new Promise((r) => setTimeout(r, 1500));
      const job = await req<{ status: "running" | "done" | "error"; result?: ReelResult; error?: string }>(`/api/reel-jobs/${job_id}`);
      if (job.status === "done" && job.result) return job.result;
      if (job.status === "error") throw new Error(job.error || "The reel couldn't be made. Please try again.");
    }
  },
  reelStyles: () => req<ReelStyle[]>("/api/reel-styles"),
  reelOptions: (id: string) => req<ReelOptionsInfo>(`/api/posts/${id}/reel/options`),
  captionLanguage: (id: string, language: ReelLanguage) =>
    req<{ post: SocialPost; rewritten: boolean }>(`/api/posts/${id}/caption-language`, json("POST", { language })),
  humanizeReel: (id: string, scenes: ReelScene[]) =>
    req<{ scenes: ReelScene[]; before: number; after: number; used_llm: boolean }>(`/api/posts/${id}/reel/humanize`, json("POST", { scenes })),
  reelPhotos: (id: string) => req<ReelPhoto[]>(`/api/posts/${id}/reel/photos`),
  share: (id: string) =>
    req<{ platform: Platform; url: string; caption: string; image_url: string | null; image_urls: string[]; note: string }>(`/api/posts/${id}/share`),
  markPublished: (id: string) => req<SocialPost>(`/api/posts/${id}/mark-published`, { method: "POST" }),
  publishNow: (id: string) => req<SocialPost>(`/api/posts/${id}/publish`, { method: "POST" }),
  browserStatus: () => req<{ available: boolean; signed_in: Record<string, boolean>; needs_check?: Record<string, boolean>; signing_in?: boolean; scheduled: boolean;
    error?: string; browser?: string }>("/api/browser"),
  browserLogin: (platform: Platform) => req<{ opened: boolean; note: string }>(`/api/browser/login/${platform}`, { method: "POST" }),
  browserPost: (id: string, submit: boolean, media: "images" | "reel") =>
    req<{ post: SocialPost; message: string }>(`/api/posts/${id}/browser-post`, json("POST", { submit, media })),
  saveDesign: (id: string, design: unknown, pages: string[]) => req<SocialPost>(`/api/posts/${id}/design`, json("PUT", { design, pages })),
  resetDesign: (id: string) => req<SocialPost>(`/api/posts/${id}/design`, { method: "DELETE" }),
  designPhoto: (id: string, body: { url?: string; stock_id?: string }) => req<{ url: string }>(`/api/posts/${id}/design/photo`, json("POST", body)),
  ugcOverview: (cid: string) => req<UgcOverview>(`/api/campaigns/${cid}/ugc`),
  ugcScript: (cid: string, body: { product: number; format: string }) => req<{ lines: string[]; used_llm: boolean }>(`/api/campaigns/${cid}/ugc/script`, json("POST", body)),
  ugcAvatars: () => req<UgcAvatar[]>("/api/ugc/avatars"),
  /** Starts the ad in the background and resolves when it's made (an AI presenter can take minutes). */
  uploadFootage: (clip: Blob, name = "recording.webm") => {
    const fd = new FormData();
    fd.append("file", clip, name);
    return req<{ id: string; url: string; seconds: number }>("/api/ugc/footage", { method: "POST", body: fd });
  },
  makeUgc: async (cid: string, body: { product: number; format: string; lines: string[]; engine: string; avatar_id?: string; avatar_name?: string;
    look?: string; caption?: string; voice?: boolean; footage?: string },
    onStep?: (step: string) => void) => {
    const { job_id } = await req<{ job_id: string }>(`/api/campaigns/${cid}/ugc`, json("POST", body));
    for (;;) {
      await new Promise((r) => setTimeout(r, 2000));
      const job = await req<{ status: string; step?: string; result?: UgcAd; error?: string }>(`/api/ugc-jobs/${job_id}`);
      if (job.step) onStep?.(job.step);
      if (job.status === "done" && job.result) return job.result;
      if (job.status === "error") throw new Error(job.error || "The ad couldn't be made.");
    }
  },
  deleteUgc: (cid: string, id: string) => req<void>(`/api/campaigns/${cid}/ugc/${id}`, { method: "DELETE" }),
  attachUgc: (cid: string, id: string, postId: string) => req<SocialPost>(`/api/campaigns/${cid}/ugc/${id}/attach`, json("POST", { post_id: postId })),
  connections: () => req<Connections>("/api/connections"),
  connectMeta: (body: { token: string; app_id?: string; app_secret?: string }) =>
    req<Connections & { result: { page: string; instagram: string; lasting: boolean; note: string } }>("/api/connections/meta", json("PUT", body)),
  saveKeys: (body: { nebius_api_key?: string; tavily_api_key?: string; heygen_api_key?: string }) => req<Connections>("/api/connections/keys", json("PUT", body)),
  disconnect: (name: "meta" | "nebius" | "tavily" | "heygen") => req<Connections>(`/api/connections/${name}`, { method: "DELETE" }),
  browserSignOut: () => req<{ signed_out: boolean }>("/api/browser/sign-out", { method: "POST" }),
  browserScheduled: (enabled: boolean) => req<{ scheduled: boolean }>("/api/browser/scheduled", json("PUT", { enabled })),

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
  researchCompetitors: (body: { url?: string; campaign_id?: string | null; competitor_urls?: string[] }) =>
    req<ResearchTask>("/api/research/competitors", json("POST", body)),
  memory: (q: string) =>
    req<{ kind: string; title: string; created_at: string; excerpt: string }[]>(`/api/research/memory?q=${encodeURIComponent(q)}`),
};

/** Reads a server-sent-events stream with fetch(), calling onEvent for each `data:` message. */
export async function streamEvents(path: string, onEvent: (ev: any) => void, signal?: AbortSignal) {
  const res = await fetch(`${API_URL}${path}`, { signal, credentials: "include" });
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

/** The brand's logo as MonoPlus saved it (rendered to PNG, the same copy posts use), else the site's URL. */
export function logoSrc(b: { logo_url: string | null; logo_path?: string | null } | null | undefined): string | null {
  if (!b) return null;
  const file = b.logo_path?.split(/[\\/]/).pop();
  if (file) return media(`/media/${file}`);
  if (!b.logo_url) return null;
  return b.logo_url.startsWith("/") ? media(b.logo_url) : b.logo_url;
}

export const PLATFORM_ORDER: Platform[] = ["instagram", "facebook", "linkedin", "x"];
export const groupKey = (p: SocialPost) => p.group_id || p.id;

/** Posts grouped into ideas: each group holds one post's versions for every platform,
 *  groups ordered by their first posting time, versions in a fixed platform order. */
export function groupPosts(posts: SocialPost[]): SocialPost[][] {
  const groups = new Map<string, SocialPost[]>();
  for (const p of posts) groups.set(groupKey(p), [...(groups.get(groupKey(p)) ?? []), p]);
  const firstAt = (g: SocialPost[]) => g.reduce((m, p) => (p.publish_at < m ? p.publish_at : m), g[0].publish_at);
  return [...groups.values()]
    .map((g) => g.sort((a, b) => PLATFORM_ORDER.indexOf(a.platform) - PLATFORM_ORDER.indexOf(b.platform)))
    .sort((a, b) => firstAt(a).localeCompare(firstAt(b)));
}

/** A group's overall state: all approved, partly posted, and so on. */
export function groupStatus(g: SocialPost[]): "DRAFT" | "APPROVED" | "PUBLISHED" {
  if (g.every((p) => p.status === "PUBLISHED")) return "PUBLISHED";
  if (g.every((p) => p.status !== "DRAFT")) return "APPROVED";
  return "DRAFT";
}

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
