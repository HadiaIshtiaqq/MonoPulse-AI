# MonoPlus

**Ask Alexa to run your social media.** MonoPlus turns a business website or Instagram handle into a month of on-brand posts (captions, designed images and swipeable carousels) and exposes it all to Alexa+ through a self-hosted MCP server: *"Alexa, make a two-week campaign for tartinebakery.com"*, *"Is it ready?"*, *"Approve them all."*

Built for **Build, Ship, Shape: Amazon Developer Hackathon**. License: [MIT](LICENSE) · Third-party notices: [third_party/NOTICE.md](third_party/NOTICE.md)

| Submission field | |
|---|---|
| Primary track | **Alexa+**: self-hosted MCP server, protocol revision **2025-11-25**, **Streamable HTTP** ([backend/app/mcp_server.py](backend/app/mcp_server.py)), plus a simulated Alexa+ experience in the web app ([frontend/app/alexa/page.tsx](frontend/app/alexa/page.tsx)) |
| Mini challenge | **AWS Builder**: Amazon Bedrock Converse API with Amazon Nova models powers every AI step when `AWS_BEDROCK_ENABLED=1` ([backend/app/llm.py](backend/app/llm.py)) |
| Mini challenge | **Open Source**: _TODO: the Open Source challenge asks for an additional project or a contribution (fork, branch or PR) made during the hackathon. Add its URL, your GitHub username and a short description here._ |
| Repository | Public, MIT-licensed: https://github.com/HadiaIshtiaqq/MonoPulse-AI |
| Demo video | _TODO: public YouTube/Vimeo link, under 3 minutes, in English_ |
| Live demo | _TODO: deployed URL (Alexa+ needs the MCP endpoint on public HTTPS)_ |

---

## The problem

Small businesses know they should post every day, and almost none do. Agencies cost thousands a month, and the cheap AI post generators produce copy that reads like a chatbot, ignore what's happening this week, and still need someone at a desk to drive them. The owner of a bakery or a gym is on their feet all day. A voice assistant they already talk to is the natural place for this to live.

## What it does

- **One input, a month of posts.** MonoPlus reads the website (logo, colours, products, tone), checks today's industry news, plans a strategy, writes every caption, removes the AI-sounding patterns, and designs branded images and carousels for Instagram, LinkedIn, X and Facebook.
- **Alexa+ can drive it.** Seven MCP tools let Alexa+ (or any MCP client) create a campaign, follow its progress, list what's posting, approve posts, read the brand kit, humanize copy and research the market.
- **A full web studio when you sit down.** Calendar, list and feed views; a post editor with platform-accurate previews; brand-kit editing; stock or uploaded photos; carousel slide editing; scheduling; direct posting; ZIP export.

## How it works

```
 "Alexa, make a two-week campaign for tartinebakery.com"
            │
            ▼
 Alexa+ (or the simulated Echo Show page)
            │  JSON-RPC 2.0 over Streamable HTTP, MCP 2025-11-25
            ▼
 POST /mcp ── tools/call create_campaign ──────────────────────────────┐
                                                                       ▼
 MonoPlus agent pipeline (FastAPI, Python)                        runs in the background
   1. Brand reader ───── website → name, logo, palette, products, voice
   2. Trend engine ───── live news + trending topics (Tavily, or free Google News / DuckDuckGo)
   3. Strategist ─────── positioning, 4 content pillars, weekly themes        ┐
   4. Copywriter ─────── every caption + carousel slides, in parallel batches  │ Amazon Bedrock (Nova Pro / Nova Lite)
   5. Humanizer ──────── detects 13 AI-writing patterns, fact-guarded          │ or NVIDIA Nemotron on Nebius
   6. SEO formatter ──── hashtags, alt text, platform limits                    ┘
   7. Designer ───────── branded images and carousels (Pillow)
            │
            ▼
 "Is it ready?" → get_campaign_status · "Approve them all" → approve_posts
 Scheduler posts approved posts at their time (Instagram, Facebook, LinkedIn, X APIs)
```

---

## Alexa+ track: the MCP server

**Endpoint:** `POST {PUBLIC_API_URL}/mcp` · protocol revision `2025-11-25` (also negotiates `2025-06-18` and `2025-03-26`) · Streamable HTTP.

| Behaviour | Implementation |
|---|---|
| Single MCP endpoint | `POST /mcp` takes one JSON-RPC message. Requests get `application/json`; notifications and responses get `202 Accepted`. `GET /mcp` returns `405` (no server-initiated stream); `DELETE /mcp` ends a session. |
| Lifecycle | `initialize` negotiates the protocol version, returns capabilities, server info and instructions, and issues an `Mcp-Session-Id`. `notifications/initialized` and `ping` are handled. |
| Headers | Unknown sessions get `404`; unsupported `MCP-Protocol-Version` values get `400`. |
| Security | The `Origin` header is validated (DNS-rebinding protection). With `MONOPLUS_ACCESS_KEY` set, requests need `Authorization: Bearer <key>`; otherwise `401` with `WWW-Authenticate`. |
| Errors | Unknown tools return JSON-RPC `-32602`. Tool failures return `isError: true` with a readable message, so the assistant can recover. |
| Results | Every tool returns spoken-style `content` text plus `structuredContent` for screens. |

**Tools**

| Tool | What Alexa can do with it |
|---|---|
| `create_campaign` | "Make a two-week campaign for tartinebakery.com on Instagram." Starts generation; returns the campaign id and a review link. |
| `get_campaign_status` | "Is it ready?" Live step progress while generating, then posts, approvals and the next post. |
| `list_upcoming_posts` | "What's posting this week?" Unpublished posts in the next N days with image links. |
| `approve_posts` | "Approve them all." Approves every draft, or specific post ids. |
| `humanize_text` | "Make this sound less like AI: …" Fact-guarded rewrite; returns how human it sounds before and after. |
| `research_market` | "What do customers complain about with salad chains?" A cited summary with content ideas, saved to the research library. |
| `get_brand_profile` | "What are my brand colours?" Colours, logo, voice and value props. |

**Verified with the official MCP Python SDK** (`mcp` 2.3.0 client, `streamable_http_client` + `ClientSession`): the client negotiated `2025-11-25`, listed all seven tools, created a real campaign for sweetgreen.com, polled it to completion, approved its posts, read the brand kit, humanized text and ran live research. The repo's test suite covers the same protocol rules ([backend/tests/test_mcp_alexa.py](backend/tests/test_mcp_alexa.py)).

**Try it yourself**

```bash
# MCP Inspector (official debugging client)
npx @modelcontextprotocol/inspector     # Transport: Streamable HTTP, URL: http://localhost:8000/mcp

# or raw JSON-RPC
curl -s localhost:8000/mcp -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"curl","version":"1"}}}'
```

### Simulated Alexa+ experience

The **Alexa+** page in the web app is an Echo Show-style simulation. Speak (browser speech recognition) or type a request, and the answer is read aloud. Each request goes through [backend/app/alexa.py](backend/app/alexa.py):

1. The request is mapped to an MCP tool and its arguments. When a model is configured, it picks the tool from the MCP tool schemas, the way an assistant does; otherwise keyword rules handle it.
2. The tool call is sent as a real JSON-RPC `tools/call` message through the same handler that serves `/mcp`.
3. The reply comes back as speech plus a screen card: a campaign progress checklist, upcoming posts with images, the humanized text, research findings or brand colours. "MCP call" under each answer shows the exact JSON-RPC request and response.

If something required is missing, such as the website, Alexa asks for it instead of guessing.

---

## AWS Builder: Amazon Bedrock

With `AWS_BEDROCK_ENABLED=1`, every AI step uses the **Bedrock Converse API** through `boto3` ([backend/app/llm.py](backend/app/llm.py), `ModelRouter._complete_bedrock`). Agents ask for a *purpose* and the router picks the model tier:

| Tier | Default model | Used for |
|---|---|---|
| Heavy | `amazon.nova-pro-v1:0` | strategy, copywriting, humanizer rewrites, tone rewrites, research plans and reports |
| Fast | `amazon.nova-lite-v1:0` | brand-profile extraction, hashtags and SEO, research insights, Alexa+ intent routing |

Calls run concurrently (bounded), with adaptive retries, token usage recorded per call, and `GET /api/telemetry` showing the split. Credentials come from the standard AWS chain. Enable model access for both models in the Bedrock console, and use a region where they're available on demand (default `us-east-1`).

> The Bedrock path is covered by a unit test with a stubbed Converse client. Run it against your own AWS account before submitting, and describe what you saw in the product feedback.

The same router also supports NVIDIA Nemotron on Nebius Token Factory (`NEBIUS_API_KEY`). It automatically switches to an available Nemotron model if a configured id isn't offered to your key.

---

## Features in the web app

- **Create:** paste a website or handle, pick platforms and 7/14/30 days, and optionally attach market research.
- **Campaign workspace:** a drag-and-drop calendar and a list view in your local time zone, an Instagram-style feed preview, an editable brand kit (colours, logo, voice; every post re-renders) and the strategy.
- **Post studio:** Instagram, LinkedIn, X and Facebook previews; templates (bold, split, quote, photo); licensed stock photos (Pexels, or Creative Commons via Openverse) or your own uploads; headline position and size; carousel slide editor; caption, humanizer and tone rewrite.
- **Humanizer:** built on two MIT projects. [blader/humanizer](https://github.com/blader/humanizer) supplies the pattern catalogue from Wikipedia's "Signs of AI writing". [lynote-ai/humanize-text](https://github.com/lynote-ai/humanize-text) supplies the translation-chain "Deep" mode. A fact guard rejects any rewrite that drops a price, date, link, @handle or #hashtag.
- **Research:** plans searches, reads sources, and writes a cited report with insights and content angles. It works without any API key, using free search and an extractive summary.
- **Publishing:** direct posting through the Instagram Graph, Facebook Pages, LinkedIn Posts and X v2 APIs; auto-posting of approved posts at their time; or "Open app" plus "Mark as posted"; or ZIP export.
- **No watermark** on anything MonoPlus renders.

## Run it locally

Requirements: Python 3.12+ and Node 18+.

```bash
cp .env.example .env              # set AWS_BEDROCK_ENABLED=1 + AWS credentials (or NEBIUS_API_KEY)

cd backend
python -m venv .venv
.venv/bin/pip install -r requirements.txt          # Windows: .venv\Scripts\pip
.venv/bin/uvicorn app.main:app --port 8000          # API + MCP at http://localhost:8000/mcp

cd ../frontend                    # new terminal
npm install
npm run dev                       # http://localhost:3000  (Alexa+ page: /alexa)
```

**With no keys at all** everything still runs: template captions, the rule-based humanizer, free web search, extractive research summaries, and the full MCP server and Alexa+ simulation.

**Tests:** `cd backend && .venv/bin/python -m pytest -q` runs 77 tests, with the network mocked. They cover the MCP transport and tool flows, the Alexa+ simulation, the Bedrock request shape, scraping, the humanizer and its fact guard, rendering and carousels, each publishing API sequence, the access key, SSRF guards and scheduling.

### Deploying for Alexa+

Alexa+ needs the MCP endpoint on **public HTTPS**. Build [backend/Dockerfile](backend/Dockerfile) and run it on any container host, such as AWS App Runner or ECS on Fargate. Then:

- Set `MONOPLUS_ACCESS_KEY` (the MCP client sends it as a Bearer token).
- Set `PUBLIC_API_URL` and `PUBLIC_APP_URL` to the public URLs.
- Set `CORS_ORIGINS` to the web app's origin.
- Mount a volume at `/data`.

The frontend is a standard Next.js app with `NEXT_PUBLIC_API_URL` pointing at the API.

## Repository layout

```
backend/app/
  mcp_server.py      MCP server: Streamable HTTP, 2025-11-25, seven tools
  alexa.py           simulated Alexa+ experience: utterance → MCP tool call → speech + card
  llm.py             model router: Amazon Bedrock (Converse) or Nemotron on Nebius
  agents/            pipeline, strategist, humanizer, research, trends, free search, renderer, photos
  scraper/           brand-kit reader (SSRF-guarded)
  social/            Instagram, Facebook, LinkedIn and X publishing
  main.py            REST API, access key, scheduler
backend/tests/       77 tests
frontend/            Next.js 14 + Tailwind web app (Create, Campaigns, Alexa+, Research, Humanizer)
third_party/         licences and notices for the humanizer projects
```

---

## Submission checklist (for the author)

- [ ] Confirm the hackathon is still accepting submissions.
- [ ] Deploy the API on public HTTPS and connect it to Alexa+ (or demo the simulated experience). Record the demo under 3 minutes, leading with Alexa+.
- [ ] Turn on Bedrock (`AWS_BEDROCK_ENABLED=1`) and run a full campaign on it before describing it in the feedback.
- [ ] Write the product feedback and friction logs below from your own experience.
- [ ] If any of this existed before the submission window, explain what changed during it. The public commit history of this repository starts on 24 October 2026.
- [ ] Open Source mini challenge: link the additional project or contribution.
- [ ] Repository access: this repo is public with an MIT license, so no reviewer invitations are needed.

## Product feedback

_To be written by the author. For each tool (Alexa+ / MCP, Amazon Bedrock, and anything else you used): what you used it for, what worked well, what needs work, how onboarding felt, and whether you'd build with it again._

## Friction log

_Optional; earns up to a 10% judging bonus. For each entry: the task, the steps you took, expected vs. actual, severity, any workaround, and an actionable suggestion._

## Feature requests

_Optional: what you'd want built, why it matters, and how urgent it is (critical / important / nice-to-have)._
