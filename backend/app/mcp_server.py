"""Self-hosted MCP server for MonoPlus (Alexa+ track).

Transport: Streamable HTTP, protocol revision 2025-11-25 (also negotiates 2025-06-18 and
2025-03-26). One endpoint, /mcp:
  POST    one JSON-RPC message. Requests get an application/json response; notifications
          and responses get 202 Accepted with no body.
  GET     405: this server doesn't offer a server-initiated SSE stream.
  DELETE  ends the session named in Mcp-Session-Id.

Every tool calls the same code the web app uses, so Alexa+ (or any MCP client) can create a
campaign, check on it, approve posts, humanize copy and research a market.
"""
from __future__ import annotations

import hmac
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from . import config
from .agents import humanizer, pipeline, research
from .schemas import CreateCampaignRequest, PostStatus, ResearchTask
from .store import store

log = logging.getLogger(__name__)
router = APIRouter(tags=["MCP"])

LATEST = "2025-11-25"
SUPPORTED = (LATEST, "2025-06-18", "2025-03-26")
SERVER_INFO = {"name": "monoplus", "title": "MonoPlus social media studio", "version": "1.0.0"}
INSTRUCTIONS = (
    "MonoPlus turns a business website or social handle into a month of on-brand social posts. "
    "Typical flow: create_campaign -> get_campaign_status until it is ready -> list_upcoming_posts -> approve_posts. "
    "Campaign generation runs in the background and takes about a minute."
)
_sessions: dict[str, str] = {}  # session id -> negotiated protocol version

PLATFORM_ALIASES = {"twitter": "x", "x": "x", "instagram": "instagram", "ig": "instagram", "linkedin": "linkedin", "facebook": "facebook", "fb": "facebook"}


class ToolError(Exception):
    """A tool ran but couldn't do what was asked; reported to the model as isError=true."""


# --------------------------------------------------------------------------- tools

TOOLS: list[dict[str, Any]] = [
    {
        "name": "create_campaign",
        "title": "Create a social media campaign",
        "description": "Read a business website or social handle and generate a calendar of on-brand posts (captions, hashtags, "
                       "designed images and carousels). Runs in the background; poll get_campaign_status with the returned campaign_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "website_or_handle": {"type": "string", "description": "Business website (example.com) or social handle (@name)."},
                "days": {"type": "integer", "minimum": 1, "maximum": 31, "default": 30, "description": "Length of the calendar in days."},
                "platforms": {"type": "array", "items": {"type": "string", "enum": ["instagram", "linkedin", "x", "facebook"]},
                              "description": "Platforms to post on. Defaults to Instagram, LinkedIn and X."},
            },
            "required": ["website_or_handle"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": True},
    },
    {
        "name": "get_campaign_status",
        "title": "Check a campaign",
        "description": "Progress of a campaign that is generating, or a summary (posts, approvals, next post) once it is ready.",
        "inputSchema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}, "required": ["campaign_id"]},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "list_upcoming_posts",
        "title": "List upcoming posts",
        "description": "Posts scheduled in the next few days across all campaigns that haven't been published yet, soonest first.",
        "inputSchema": {"type": "object", "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 60, "default": 7}}},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "approve_posts",
        "title": "Approve posts",
        "description": "Approve draft posts in a campaign so they're ready to publish at their scheduled time. "
                       "Approves every draft unless post_ids is given.",
        "inputSchema": {
            "type": "object",
            "properties": {"campaign_id": {"type": "string"}, "post_ids": {"type": "array", "items": {"type": "string"}}},
            "required": ["campaign_id"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False},
    },
    {
        "name": "humanize_text",
        "title": "Make text sound human",
        "description": "Remove common AI-writing patterns from marketing copy without changing prices, dates, links, @handles or #hashtags.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "maxLength": 5000},
                "mode": {"type": "string", "enum": ["light", "standard", "deep"], "default": "standard"},
            },
            "required": ["text"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
    {
        "name": "research_market",
        "title": "Research a market question",
        "description": "Search live news, the web and social discussion about a question and return a cited summary with content ideas. "
                       "Takes 10 to 60 seconds. The report is saved and can be attached to a campaign.",
        "inputSchema": {
            "type": "object",
            "properties": {"question": {"type": "string", "minLength": 3}, "region": {"type": "string", "default": ""}},
            "required": ["question"],
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": True},
    },
    {
        "name": "get_brand_profile",
        "title": "Get a brand kit",
        "description": "The brand kit MonoPlus extracted for a campaign: name, tagline, colours, logo, voice and value propositions.",
        "inputSchema": {"type": "object", "properties": {"campaign_id": {"type": "string"}}, "required": ["campaign_id"]},
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    },
]
TOOL_NAMES = {t["name"] for t in TOOLS}


def _campaign(cid: str):
    c = store.campaigns.get(str(cid or ""))
    if not c:
        raise ToolError(f"No campaign with id {cid!r}. Use create_campaign first or check the id.")
    return c


def _post_summary(p, campaign) -> dict:
    return {"post_id": p.id, "campaign_id": campaign.id, "brand": campaign.brand.name if campaign.brand else "",
            "platform": p.platform.value, "format": p.format, "headline": p.headline,
            "caption": p.caption[:280], "publish_at": p.publish_at.isoformat(), "status": p.status.value,
            "image_url": f"{config.PUBLIC_API_URL}{p.image_url.split('?')[0]}" if p.image_url else None}


async def call_tool(name: str, args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Run a tool. Returns (short spoken-style summary, structured result)."""
    if name == "create_campaign":
        target = str(args.get("website_or_handle") or args.get("input") or "").strip()
        if len(target) < 2:
            raise ToolError("Tell me the business website or social handle to build the campaign from.")
        raw = args.get("platforms") or ["instagram", "linkedin", "x"]
        platforms = list(dict.fromkeys(PLATFORM_ALIASES[p.lower()] for p in raw if str(p).lower() in PLATFORM_ALIASES))
        try:
            req = CreateCampaignRequest(input=target, days=int(args.get("days", 30)), platforms=platforms or ["instagram", "linkedin", "x"])
        except (ValidationError, ValueError) as exc:
            raise ToolError(f"Invalid campaign options: {exc}") from exc
        campaign, job = pipeline.start(req)
        result = {"campaign_id": campaign.id, "status": "GENERATING", "days": req.days, "platforms": [p.value for p in req.platforms],
                  "review_url": f"{config.PUBLIC_APP_URL}/campaign/{campaign.id}"}
        return f"Started a {req.days}-day campaign for {target}. It'll be ready in about a minute.", result

    if name == "get_campaign_status":
        c = _campaign(args.get("campaign_id"))
        job = next((j for j in store.jobs.values() if j.campaign_id == c.id), None)
        if c.status.value == "GENERATING":
            steps = [{"step": s.label, "status": s.status} for s in job.steps] if job else []
            current = next((s["step"] for s in steps if s["status"] == "running"), "Starting")
            return f"Still working: {current.lower()}.", {"campaign_id": c.id, "status": "GENERATING", "steps": steps}
        if c.status.value == "FAILED":
            reason = job.error if job and job.error else "the website couldn't be read"
            return f"That campaign failed: {reason}.", {"campaign_id": c.id, "status": "FAILED", "error": reason}
        approved = sum(p.status is not PostStatus.DRAFT for p in c.posts)
        upcoming = sorted((p for p in c.posts if p.status is not PostStatus.PUBLISHED), key=lambda p: p.publish_at)
        nxt = _post_summary(upcoming[0], c) if upcoming else None
        result = {"campaign_id": c.id, "status": c.status.value, "brand": c.brand.name if c.brand else "", "posts": len(c.posts),
                  "carousels": sum(p.format == "carousel" for p in c.posts), "approved": approved,
                  "published": sum(p.status is PostStatus.PUBLISHED for p in c.posts), "next_post": nxt,
                  "review_url": f"{config.PUBLIC_APP_URL}/campaign/{c.id}"}
        brand = c.brand.name if c.brand else "the brand"
        return f"{brand}'s campaign is ready: {len(c.posts)} posts, {approved} approved.", result

    if name == "list_upcoming_posts":
        days = max(1, min(60, int(args.get("days", 7))))
        now = datetime.now(timezone.utc)
        rows = [(c, p) for c in store.campaigns.values() for p in c.posts
                if p.status is not PostStatus.PUBLISHED and now - timedelta(hours=1) <= p.publish_at <= now + timedelta(days=days)]
        rows.sort(key=lambda cp: cp[1].publish_at)
        posts = [_post_summary(p, c) for c, p in rows[:20]]
        speech = (f"You have {len(rows)} post{'s' if len(rows) != 1 else ''} coming up in the next {days} days."
                  if rows else f"Nothing is scheduled for the next {days} days.")
        return speech, {"days": days, "count": len(rows), "posts": posts}

    if name == "approve_posts":
        c = _campaign(args.get("campaign_id"))
        ids = set(args.get("post_ids") or [])
        unknown = ids - {p.id for p in c.posts}
        if unknown:
            raise ToolError(f"These posts aren't in the campaign: {', '.join(sorted(unknown))}")
        changed = 0
        for p in c.posts:
            if p.status is PostStatus.DRAFT and (not ids or p.id in ids):
                p.status, p.publish_error = PostStatus.APPROVED, None
                changed += 1
        store.save()
        total = sum(p.status is not PostStatus.DRAFT for p in c.posts)
        return f"Approved {changed} post{'s' if changed != 1 else ''}.", {"campaign_id": c.id, "approved_now": changed, "approved_total": total, "posts": len(c.posts)}

    if name == "humanize_text":
        text = str(args.get("text") or "").strip()
        if not text:
            raise ToolError("Give me the text to humanize.")
        mode = args.get("mode") if args.get("mode") in ("light", "standard", "deep") else "standard"
        res = await humanizer.humanize(text[:5000], threshold=0, mode=mode)
        fixed = sorted({p["label"] for p in res.patterns_before} - {p["label"] for p in res.patterns_after})
        result = {"text": res.text, "human_sounding_before": max(0, round(100 - res.before)), "human_sounding_after": max(0, round(100 - res.after)),
                  "patterns_fixed": fixed, "mode": res.mode}
        return f"Done. It now reads {result['human_sounding_after']}% human-sounding.", result

    if name == "research_market":
        question = str(args.get("question") or "").strip()
        if len(question) < 3:
            raise ToolError("Ask a market question, for example 'what do customers complain about with local bakeries?'.")
        task = ResearchTask(topic=question, region=str(args.get("region") or ""), status="running")
        store.research[task.id] = task
        async for _ in research.execute(task):
            pass
        insights = task.insights.model_dump() if task.insights else None
        summary = (task.report or "").split("## Sources")[0].strip()
        result = {"research_id": task.id, "summary": summary[:2500], "insights": insights,
                  "sources": [s.model_dump() for s in task.sources[:8]]}
        lead = insights["verified_trend"] if insights and insights.get("verified_trend") else f"I found {len(task.sources)} sources."
        return lead, result

    if name == "get_brand_profile":
        c = _campaign(args.get("campaign_id"))
        if not c.brand:
            raise ToolError("That campaign is still reading the website. Try again in a moment.")
        b = c.brand
        logo = (f"{config.PUBLIC_API_URL}{b.logo_url}" if b.logo_url and b.logo_url.startswith("/") else b.logo_url)
        result = {"name": b.name, "tagline": b.tagline, "industry": b.industry, "location": b.location, "website": b.website_url,
                  "colors": {"primary": b.primary_color, "secondary": b.secondary_color, "accent": b.accent_color},
                  "logo_url": logo, "voice": b.brand_voice_prompt, "value_props": b.value_props}
        return f"{b.name}: {b.tagline or b.industry}.", result

    raise KeyError(name)


# --------------------------------------------------------------------------- JSON-RPC


def _rpc_error(req_id, code: int, message: str, status: int = 200) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}, status_code=status)


async def handle(message: dict, session_version: str = LATEST) -> tuple[dict | None, dict[str, str]]:
    """Process one JSON-RPC message. Returns (response body or None for notifications, extra headers)."""
    method, req_id, params = message.get("method"), message.get("id"), message.get("params") or {}
    is_request = "id" in message and method is not None
    if method is None or not is_request:
        return None, {}  # notification (e.g. notifications/initialized) or a response to us: nothing to send

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED else LATEST
        session = uuid.uuid4().hex
        _sessions[session] = version
        return {"jsonrpc": "2.0", "id": req_id, "result": {
            "protocolVersion": version,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": SERVER_INFO,
            "instructions": INSTRUCTIONS,
        }}, {"Mcp-Session-Id": session}

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}, {}

    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}, {}

    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in TOOL_NAMES:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": f"Unknown tool: {name}"}}, {}
        if not isinstance(args, dict):
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32602, "message": "arguments must be an object"}}, {}
        try:
            summary, result = await call_tool(name, args)
            body = {"content": [{"type": "text", "text": f"{summary}\n\n{json.dumps(result, ensure_ascii=False, default=str)}"}],
                    "structuredContent": result, "isError": False}
        except ToolError as exc:
            body = {"content": [{"type": "text", "text": str(exc)}], "isError": True}
        except Exception as exc:  # noqa: BLE001 - tool failures are reported to the model, not as protocol errors
            log.exception("MCP tool %s failed", name)
            body = {"content": [{"type": "text", "text": f"{name} failed: {exc}"}], "isError": True}
        return {"jsonrpc": "2.0", "id": req_id, "result": body}, {}

    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Method not found: {method}"}}, {}


def _authorized(request: Request) -> bool:
    if not config.ACCESS_KEY:
        return True
    auth = request.headers.get("authorization", "")
    given = auth[7:].strip() if auth.lower().startswith("bearer ") else request.headers.get("x-access-key", "")
    return hmac.compare_digest(given.encode(), config.ACCESS_KEY.encode())


def _origin_ok(request: Request) -> bool:
    # Browsers send Origin; validating it blocks DNS-rebinding attacks (required by the spec).
    origin = request.headers.get("origin")
    return origin is None or origin in config.CORS_ORIGINS or "*" in config.CORS_ORIGINS


@router.post("/mcp")
async def mcp_post(request: Request):
    if not _origin_ok(request):
        return JSONResponse({"error": "Origin not allowed"}, status_code=403)
    if not _authorized(request):
        return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32001, "message": "Unauthorized"}},
                            status_code=401, headers={"WWW-Authenticate": 'Bearer realm="monoplus"'})
    try:
        message = json.loads(await request.body())
    except (ValueError, UnicodeDecodeError):
        return _rpc_error(None, -32700, "Parse error", 400)
    if isinstance(message, list):
        return _rpc_error(None, -32600, "Batching is not supported in this protocol revision", 400)
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _rpc_error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request", 400)

    session = request.headers.get("mcp-session-id")
    if message.get("method") != "initialize":
        if session and session not in _sessions:
            return _rpc_error(message.get("id"), -32001, "Session not found; re-initialize", 404)
        version = request.headers.get("mcp-protocol-version")
        if version and version not in SUPPORTED:
            return _rpc_error(message.get("id"), -32600, f"Unsupported MCP-Protocol-Version: {version}", 400)

    body, headers = await handle(message, _sessions.get(session or "", LATEST))
    if body is None:
        return Response(status_code=202)
    return JSONResponse(body, headers=headers)


@router.get("/mcp")
async def mcp_get():
    # This server answers every request inline and doesn't push server-initiated messages.
    return Response(status_code=405, headers={"Allow": "POST, DELETE"})


@router.delete("/mcp")
async def mcp_delete(request: Request):
    if not _authorized(request):
        return Response(status_code=401)
    session = request.headers.get("mcp-session-id")
    if not session or _sessions.pop(session, None) is None:
        return Response(status_code=404)
    return Response(status_code=204)
