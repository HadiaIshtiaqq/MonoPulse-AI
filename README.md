# MonoPlus

**Paste a website URL or social handle and get a 30-day, on-brand social media calendar: designed posts, swipeable carousels and human-sounding captions, ready to schedule.**

Built for the Nebius x NVIDIA Global AI Hackathon, Best Apps and Agents track. License: [MIT](LICENSE). Third-party notices: [third_party/NOTICE.md](third_party/NOTICE.md).

Small businesses can't afford an agency, and the cheap URL-to-post tools produce generic copy that reads like a chatbot and ignores what's happening this week. Reviews of Predis.ai, the best-known tool here, point at the same gaps: unreliable website import, AI text that isn't usable as-is, and a watermark on free-plan posts. MonoPlus runs a pipeline of agents that pulls your real brand (logo, colours, voice), looks up live trends in your industry, writes the posts with NVIDIA Nemotron, strips the AI tells out of the copy, and renders branded images, all in under 30 seconds.

## How it works

```
URL / @handle
  │
  ▼
1. Ingestor ─────────── scrapes HTML + CSS: name, logo, palette, value props   (Nemotron Nano: brand profile JSON)
  │
  ▼
2. Trend engine ─────── Tavily: industry news, local events, trending topics
  │
  ▼
3. Strategist ───────── positioning, 4 content pillars, weekly themes           (Nemotron 3 Ultra)
  │
  ▼
4. Copywriter ───────── 30 posts written in parallel batches                    (Nemotron 3 Ultra)
  │
  ▼
5. Humanizer ────────── rule pass + rewrite of anything still robotic           (Nemotron 3 Ultra)
  │
  ▼
6. Formatter / SEO ──── hashtags, alt text, SEO keywords, platform limits       (Nemotron Nano)
  │
  ▼
7. Renderer ─────────── Pillow: bold / split / quote / photo templates, multi-page carousels, per platform
  │
  ▼
Design studio ──────── calendar, feed preview, brand kit, platform-native previews, photos, carousel editor
  │
  ▼
Publishing ─────────── 1-click post, or scheduled auto-publish via a Zapier / Make / n8n webhook, or ZIP export
```

### Model tiering on Nebius Token Factory

All model calls go through one router ([backend/app/llm.py](backend/app/llm.py)). Agents name the *purpose* of a call and the router picks the tier:

| Tier | Model (configurable) | Purposes |
|---|---|---|
| Heavy | Nemotron 3 Ultra | strategy, copywriting, humanize, tone rewrite, research planning and reports |
| Fast | Nemotron Nano / Super | brand-profile extraction, hashtags and SEO, formatting, research insight extraction |

Fast-tier calls are sent with `/no_think` so Nano skips its reasoning trace. Every call is logged with tier, latency and tokens, available to developers at `GET /api/telemetry` (kept out of the user-facing UI).

To hit the 30-second target for 30 posts, the strategy is one Ultra call, and copy is then written in concurrent batches (`COPY_BATCH_SIZE`, default 6 posts per call). Formatting runs in concurrent Nano batches and images render in a thread pool.

### The humanizer

[backend/app/agents/humanizer.py](backend/app/agents/humanizer.py) is built on two MIT-licensed open-source projects:

- **[blader/humanizer](https://github.com/blader/humanizer)**: its pattern catalogue, based on Wikipedia's "Signs of AI writing", drives detection of tells such as "not X but Y" contrasts, staged run-ups, sales language, chatbot residue and dash chains, as well as the scoring weights, the rule pass and the Nemotron rewrite prompt.
- **[lynote-ai/humanize-text](https://github.com/lynote-ai/humanize-text)**: its translation-chain method powers **Deep** mode, a high-temperature rewrite through Chinese and Japanese and back to English. It runs on Nemotron instead of DeepSeek, Google Translate and Niutrans.

There are three modes:

- **Light** runs the rule pass only and is instant.
- **Standard** runs the rule pass, then a pattern-guided Nemotron 3 Ultra rewrite if any tells remain. Campaigns use this mode by default.
- **Deep** runs the translation chain, then the standard pass.

A **fact guard** rejects any step that drops a price, number, date, link, @handle, #hashtag or the brand name, so humanizing can't change the offer. The Humanizer page shows the patterns found and fixed, plus every pipeline step, including rejected ones.

The **AI-tell score** (0 to 100, lower reads more human) is our own transparent heuristic over that catalogue plus sentence-length variance. It is **not** a commercial AI-detector score, and like both upstream projects we don't promise any detector result.

### Design studio

- **Templates:** bold, split, quote and **photo** layouts. Photo posts use licensed stock (Pexels, or Creative Commons via Openverse filtered to commercial-use licenses, with credits kept) or **your own uploaded photos**. You can set the headline position and size.
- **Carousels:** about one in four Instagram and LinkedIn posts is a swipeable carousel with a cover, 3 to 5 content slides and a call-to-action slide. You can edit, add and remove slides.
- **Brand kit:** edit the name, tagline, colours (with the palette found on your site) and voice, and upload a logo. Every post re-renders.
- **Previews:** Instagram, LinkedIn, X and Facebook mockups with carousel paging, plus a feed grid showing how the month looks on your profile.
- **No watermark** on anything MonoPlus renders.

### Market research agent

The **Research** page ([backend/app/agents/research.py](backend/app/agents/research.py)) answers open questions about your market, such as "What are customers complaining about with bakeries in Austin?":

1. It recalls earlier findings from research memory.
2. Nemotron 3 Ultra plans 4 to 6 searches across news, web, social (Reddit, X, Instagram, TikTok) and jobs.
3. Tavily runs the searches in parallel and reads the top pages in full with Tavily Extract.
4. Ultra writes a markdown report where every claim cites its numbered source.
5. Nemotron Nano extracts structured insights: trend, audience insight, pricing gap, content angles, and confidence and opportunity scores.

Each step streams live to the page. You can also queue a question to run in the background, retried up to 3 times. You can optionally research from a brand's point of view by choosing one of your campaigns.

Every finished report goes into the research library. **Attach up to 3 reports when creating a campaign** and their findings and content angles are passed to the strategist and copywriter, so the posts build on real market evidence. The campaign's Strategy tab lists the research it used.

Without keys, research still runs but says plainly that live search is unavailable instead of inventing findings.

### Publishing

- **Direct posting** ([backend/app/social/](backend/app/social/)) through the official APIs. A platform is connected when its keys are set in `.env` (see `.env.example`); keys never appear in the UI.
  - **Instagram (Graph API):** single images and carousels of up to 10 slides, sent as JPEG. Instagram downloads images by URL. When the API runs on localhost, images are first staged as unpublished photos on your linked Facebook Page, so direct posting works without a public server.
  - **Facebook Page:** single photo or multi-photo posts.
  - **LinkedIn (Posts + Images API):** single image or multi-image posts. Hashtags stay clickable.
  - **X (v2 media upload + posts):** up to 4 images.
  - **"Post now"** publishes immediately and links to the live post. With **Auto-post approved** switched on (in the campaign header), approved posts go out at their scheduled time; the scheduler checks every minute.
- **Not connected yet?** "Open Instagram" copies the caption and opens the app. You then click "Mark as posted", so posts are never marked live by accident.
- **Optional webhook:** set `PUBLISH_WEBHOOK_URL` to route unconnected platforms through Zapier, Make or n8n. Payloads are signed with HMAC-SHA256.
- **Export:** a ZIP of every image plus `posts.csv` and photo credits, for any scheduler.

Direct posting is covered by tests that replay each platform's API flow, but it hasn't been run against live accounts. Each platform needs its own developer app and permission approval (Meta app review for `instagram_content_publish`, LinkedIn's Community Management API, and an X developer app).

## Run it locally

Requirements: Python 3.12+ and Node 18+.

```bash
# 1. Backend
cp .env.example .env            # add NEBIUS_API_KEY and TAVILY_API_KEY
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip
.venv/bin/uvicorn app.main:app --port 8000

# 2. Frontend (new terminal)
cd frontend
npm install
npm run dev                      # http://localhost:3000
```

Then check which Nemotron model ids your key can see and put them in `.env`:

```bash
curl http://localhost:8000/api/models
```

**No keys?** The app still runs end to end in *demo mode*: template copy instead of Nemotron, no trend search, with a "demo mode" badge in the UI. That lets anyone test the scraper, humanizer, renderer and calendar.

### Tests

```bash
cd backend && .venv/bin/python -m pytest -q
```

These cover scraper parsing (logo, palette, industry), input detection, humanizer rules, tier routing, JSON parsing of model output, rendering in every platform and layout, the X character limit, and a full 30-day campaign under 30 seconds (network mocked).

### Deploying on Nebius

The backend ships with a [Dockerfile](backend/Dockerfile) and can run as a **Nebius Serverless Endpoint** on port 8000. Set `PUBLIC_API_URL` to the endpoint URL and `CORS_ORIGINS` to the frontend origin. Mount a volume at `/data` to keep campaigns and images. The frontend is a standard Next.js app (Vercel or any Node host) with `NEXT_PUBLIC_API_URL` pointing at the backend.

## API

| Method | Path | |
|---|---|---|
| POST | `/api/campaigns` | `{input, platforms, days}` starts generation, returns `{campaign_id, job_id}` |
| GET | `/api/jobs/{id}` | step-by-step progress, brand kit and trends as they arrive |
| GET | `/api/campaigns/{id}` | full campaign: brand, strategy, trends, posts |
| PATCH | `/api/posts/{id}` | edit headline, caption, hashtags, layout, date or status (re-renders the image when needed) |
| POST | `/api/posts/{id}/rewrite` | `{tone}` Ultra rewrite |
| POST | `/api/posts/{id}/humanize` | run the humanizer again |
| GET | `/api/posts/{id}/share` | 1-click redirect links |
| POST | `/api/humanize` | humanize arbitrary text |
| GET | `/api/telemetry` | model-routing stats |
| PATCH | `/api/campaigns/{id}/brand` | edit brand kit (colours, logo, voice) and re-render all posts |
| GET | `/api/campaigns/{id}/export` | ZIP of images + `posts.csv` |
| POST | `/api/posts/{id}/background` | set a stock or uploaded background photo |
| POST | `/api/posts/{id}/publish` | post directly to the platform now |
| GET | `/api/photos/search?q=` | licensed stock photos (Pexels or Openverse) |
| POST | `/api/uploads` | upload an image (logo or background) |
| GET | `/api/publishing` | which platforms are connected (no secrets) and auto-post state |
| PUT | `/api/publishing/auto` | turn auto-posting of approved posts on or off |
| GET | `/api/upcoming?days=7` | posts due soon across campaigns |
| GET | `/api/research/stream?q=&region=&campaign_id=` | live research as server-sent events (saved to the library) |
| GET/POST | `/api/research/tasks` | research library / queue a background research task |
| GET/DELETE | `/api/research/tasks/{id}` | one report with sources and insights |
| GET | `/api/research/memory?q=` | search past findings |

## Project layout

```
backend/app/
  scraper/ingestor.py     brand kit extraction
  agents/trends.py        Tavily
  agents/strategist.py    strategy + copy (Ultra)
  agents/humanizer.py     anti-AI pass
  agents/formatter.py     hashtags/SEO/limits (Nano)
  agents/renderer.py      Pillow templates
  agents/pipeline.py      orchestration and timing
  llm.py                  Token Factory client and tier router
frontend/                 Next.js 14 + Tailwind dashboard
```

## Known limitations

- The scraper uses httpx and BeautifulSoup, so sites that render entirely in JavaScript give it less text to work with. SVG-only logos are skipped in favour of the site's PNG icon.
- Instagram and other social profiles can't be scraped directly. Handles are researched through Tavily, which also tries to find and scrape the business's website.
- Storage is a JSON file, which is fine for a single instance.

## Feedback on Nebius Token Factory and Nemotron

_TODO before submission: fill in from real usage (latency you saw per tier, ease of the OpenAI-compatible API, model availability, anything that tripped you up)._
